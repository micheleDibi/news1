"""Pre-processing dei bandi via Claude Haiku 4.5.

Per ogni bando con stato_processing='scraped':
  1. Costruisce un payload con titolo + descrizione + URL + raw_data + contesto fonte.
  2. Chiama Claude Haiku con tool use per garantire JSON strutturato.
  3. Ritorna analisi {is_valid_bando, confidence_score, rejection_reason, stato_bando}.

L'aggiornamento DB è fatto dall'orchestrator (bando_preprocess_runner).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from collections.abc import Mapping
from typing import Any, Mapping
from urllib.parse import urlsplit, unquote

from .logger import logger
from .settings import get_settings
from .stato_bando import data_italiana, oggi_roma


# Budget del testo di pagina nel prompt di preprocess (contratto del giro 2,
# §6.3 con §19.5). Con i soli primi 4 000 caratteri il modello vedeva quasi
# solo menu, e su LazioEuropa perdeva la scadenza. Ora entrano le prime
# TESTA_PROMPT_CHAR battute intere (dove stanno titolo ed etichetta di stato)
# e, fino a BUDGET_PROMPT_CHAR, le sezioni con date e parole utili scelte da
# `impronte.seleziona_sezioni`. BUDGET_PROMPT_CHAR e' la sola costante da
# riportare a 4000 se, nei 7 giorni d'ombra, la quota di bandi con scadenza o
# la distribuzione degli stati derivano.
BUDGET_PROMPT_CHAR = 8000
TESTA_PROMPT_CHAR = 1500

# Tetto per rileggere la pagina con il lettore per ente dopo il modello. Quasi
# sempre e' una lettura dalla cache del giro (l'ha appena presa il markdown);
# altrimenti una GET httpx, mai il ripiego a pagamento.
TETTO_LETTORE_S = 30.0


# URL slug pattern: identifica gli URL che sembrano indici di sezione
# (no slug specifico dopo il segmento "navigazione"). Esempi positivi:
#   /bandi, /bandi/, /opportunita-di-finanziamento, /avvisi/, /calendario/
#   /bandi-aperti, /elenco-avvisi-pubblicati, /bandi?page=3
_INDEX_LAST_SEGMENT_PATTERNS = (
    r"^bandi$", r"^bandi-(aperti|chiusi|attivi|in-uscita|21-27|2021-2027|fesr|fse|fse-plus)$",
    r"^avvisi$", r"^avvisi-(pubblicati|aperti|attivi)$",
    r"^opportunita$", r"^opportunita-(di-finanziamento|e-bandi|aperte)$",
    r"^calendario$", r"^calendario-(degli-)?inviti$", r"^calendario-(degli-)?avvisi$",
    r"^elenco-(avvisi|bandi)(-pubblicati)?$", r"^archivio$",
    r"^get-involved$", r"^apply-for-(the-)?call$", r"^calls(-for-proposals)?$",
    r"^preavvisi$", r"^calendario-(di-)?preavviso$", r"^bandi-fesr$", r"^bandi-fse$",
)
_INDEX_LAST_SEGMENT_RE = re.compile("|".join(_INDEX_LAST_SEGMENT_PATTERNS), re.IGNORECASE)


def _is_likely_index_url(url: str) -> bool:
    """Heuristic: True se l'URL sembra una pagina indice/elenco bandi
    (non un dettaglio singolo). Usato come segnale aggiuntivo per il LLM."""
    if not url:
        return False
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    # Path completamente vuoto o solo root -> non indica nulla
    if not path or path == "":
        return False
    # Ultimo segmento + (eventuale query) sono indicatori
    last = path.rsplit("/", 1)[-1].lower()
    if not last:
        return False
    if _INDEX_LAST_SEGMENT_RE.match(last):
        return True
    # Query parameters tipici di paginazione/filtri -> probabilmente indice
    if parts.query and any(p in parts.query.lower() for p in ("page=", "filter_", "sort_", "size=", "stato=", "values=")):
        return True
    return False


def _extract_slug_title(url: str) -> str:
    """Deriva un 'titolo' leggibile dallo slug URL.

    Esempi:
      /opportunita/.../bandi-21-27/investimenti-produttivi -> "Investimenti produttivi"
      /avvisi-pubblici/fesr/avviso-pubblico-mini-pia       -> "Avviso pubblico mini pia"
      /bandi/                                              -> "" (indice, nessuno slug specifico)
    """
    if not url:
        return ""
    path = urlsplit(url).path.rstrip("/")
    if not path:
        return ""
    last = path.rsplit("/", 1)[-1]
    last = unquote(last)
    # Tokenize kebab/snake case
    tokens = re.split(r"[-_]+", last)
    tokens = [t for t in tokens if t and not t.isdigit()]
    if not tokens or len(tokens) < 2:
        return ""
    # Capitalize first only
    return " ".join(tokens).strip().capitalize()


# Tool schema v2: forza struttura JSON via tool use API. Include estrazione
# delle 3 date con citation obbligatoria (triple-gate validation post-call).
_DATE_OBJ_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {
            "type": ["string", "null"],
            "description": "ISO YYYY-MM-DD o null se non identificabile dal markdown.",
        },
        "source": {
            "type": "string",
            "enum": ["official_pdf", "official_page", "inferred", "missing"],
            "description": (
                "'official_pdf' = link/citazione PDF ufficiale; "
                "'official_page' = direttamente nel contenuto HTML; "
                "'inferred' = ricavata da contesto non esplicito; "
                "'missing' = non identificabile (in tal caso date=null e quote=null)."
            ),
        },
        "quote": {
            "type": ["string", "null"],
            "description": (
                "Frammento LETTERALE del markdown (max 300 char) contenente la data. "
                "OBBLIGATORIO se date non null. Sarà verificato come substring esatta."
            ),
        },
    },
    "required": ["date", "source", "quote"],
}


ANALYZE_TOOL = {
    "name": "save_bando_analysis",
    "description": (
        "Salva il risultato dell'analisi del bando + estrai le 3 date dal markdown. "
        "Devi SEMPRE chiamare questo tool con la tua valutazione."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_valid_bando": {
                "type": "boolean",
                "description": (
                    "True se è un vero bando/avviso/call per finanziamenti UE 2021-2027. "
                    "False se è pagina indice/archivio/contenuto generico/link sbagliato/header tabella/titolo troppo generico."
                ),
            },
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidenza nella classificazione (0=incertissimo, 1=certissimo).",
            },
            "rejection_reason": {
                "type": ["string", "null"],
                "description": (
                    "Se is_valid_bando=false, motivo breve in italiano "
                    "(es. 'pagina indice', 'titolo generico', 'header tabella', "
                    "'link di navigazione', 'documento generico'). "
                    "null se is_valid_bando=true."
                ),
            },
            "stato_bando": {
                "type": "string",
                "enum": ["aperto", "chiuso", "in apertura prossimamente", "unknown"],
                "description": (
                    "Stato ATTUALE del bando, basato sulle date estratte e sul contenuto. "
                    "Sarà poi riconciliato automaticamente con le date: "
                    "data_scadenza < oggi -> forzato 'chiuso'; "
                    "data_apertura > oggi -> forzato 'in apertura prossimamente'."
                ),
            },
            "data_pubblicazione": _DATE_OBJ_SCHEMA,
            "data_apertura": _DATE_OBJ_SCHEMA,
            "data_scadenza": _DATE_OBJ_SCHEMA,
        },
        "required": [
            "is_valid_bando", "confidence_score", "stato_bando",
            "data_pubblicazione", "data_apertura", "data_scadenza",
        ],
    },
}


SYSTEM_PROMPT_TEMPLATE = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027 \
(FESR, FSE+, JTF, INTERREG). Il tuo compito è validare ogni record candidato a "bando" \
estratto da portali istituzionali (regioni, ministeri, programmi CTE), eliminando i falsi positivi.

== REGOLA AUREA: BANDO SINGOLO, NON ELENCO ==
Il tuo OBIETTIVO PRINCIPALE è distinguere:
  A) Pagina di DETTAGLIO di UN SINGOLO bando -> VALIDO
  B) Pagina di ELENCO / INDICE / CATEGORIA che lista PIÙ bandi -> NON VALIDO

Pattern URL tipici di INDICE / CATEGORIA / ELENCO (RIFIUTA SEMPRE):
  /bandi, /bandi/, /bandi-aperti, /bandi-21-27, /bandi-fesr, /bandi-fse
  /opportunita, /opportunita-di-finanziamento, /opportunita-e-bandi
  /avvisi, /avvisi-pubblicati, /elenco-avvisi-pubblicati
  /calendario, /calendario-degli-inviti, /calendario-avvisi, /calendario-preavviso
  /preavvisi, /archivio, /elenco-bandi
  /apply-for-the-call, /get-involved, /calls, /calls-for-proposals
  query string con ?page=, ?filter_, ?sort_, ?stato=
  URL che non ha uno slug specifico (es. "regione.it/bandi" senza nulla dopo)

Pattern URL tipici di DETTAGLIO SINGOLO BANDO (ACCETTA se confermato dal titolo):
  /opportunita-di-finanziamento/2026/{slug-bando-descrittivo}
  /avvisi-pubblici/fesr/{slug-bando}
  /publiccompetition/12345:bando-incentivi-assunzioni-donne.html
  /bandi/avviso-pubblico-mini-pia-piani-di-sviluppo-industriale
  /-/{slug-bando-specifico} (Liferay friendly URL)
  Pattern con anno o ID numerico + slug descrittivo

== ALTRI FALSI POSITIVI DA RIFIUTARE ==
- Header di tabella (titolo come "Avviso", "Oggetto", "Titolo", "Avviso pubblico", "Attuazione")
- Link di navigazione (titolo come "Home", "Indietro", "Tutte le opportunità", "Tutti i bandi")
- Documenti generici (manuali, guide, regolamenti SENZA call associata)
- Pagine di programma/asse SENZA call specifica (es. "Asse 1 — Innovazione")
- Titoli troppo corti/generici (meno di 3 parole significative tipo "PR FESR")
- Link a documenti accessori (manuali utente, FAQ, video)
- Brochure/calendari riassuntivi (NON un singolo bando)

== ACCETTI COME VALIDO SOLO SE ==
Identifichi inequivocabilmente UN BANDO/AVVISO/CALL SPECIFICO con almeno UN segnale forte:
- Nome del bando descrittivo (es. "Voucher digitalizzazione PMI 2026")
- Codice avviso (es. "Avviso pubblico n. 499/2025", "Bando 26AB")
- Oggetto identificabile (es. "Incentivi assunzioni donne vittime di violenza")
- Beneficiari specifici (es. "Microimprese del commercio in sede fissa")
- Importo / dotazione finanziaria
- Scadenza / data presentazione domanda
- Riferimento normativo (DGR/DDR/Decreto specifico)

== STATO BANDO ==
- "aperto": il bando è attivo, le candidature sono aperte
- "chiuso": il bando è scaduto / completato / archiviato
- "in apertura prossimamente": preavviso / pre-informativa / call non ancora aperta
- "unknown": impossibile determinare (penalizza la confidence!)

INDIZI utili per lo stato:
- Tipo fonte = "Preavviso" -> molto probabilmente "in apertura prossimamente"
- Tipo fonte = "Opportunità" + link in /bandi-aperti/ -> "aperto"
- Descrizione contiene "scaduto", "chiuso", "archivio", date passate -> "chiuso"
- raw_data ha 'data_pubblicazione_prevista' / 'data_apertura_prevista' futura -> "in apertura prossimamente"
- raw_data ha 'data_scadenza' passata -> "chiuso"
- Senza indizi precisi e tipo "Opportunità": "aperto" (default ragionevole)

== CONFIDENZA ==
- 0.9-1.0: certezza (titolo descrittivo + URL specifico + segnali coerenti)
- 0.7-0.9: alta confidenza con piccoli dubbi
- 0.5-0.7: media (segnali deboli, possibili interpretazioni multiple)
- <0.5: incerto (usa per casi dubbi: meglio rifiutare con questa confidence)

== ESTRAZIONE DATE (CRITICO) ==
Data attuale: {oggi}. Formato italiano DD/MM/YYYY. Output sempre ISO YYYY-MM-DD.

Devi estrarre 3 date dal CONTENUTO PAGINA (markdown Firecrawl) — non dal titolo o raw_data:
- **data_pubblicazione**: data di PUBBLICAZIONE del bando sulla fonte ufficiale (BUR, GU, sito ente).
  Frasi tipiche: "pubblicato il", "data di pubblicazione", "avviso pubblicato in data".
  NON è la data odierna, NON è la data di scraping.
- **data_apertura**: data da cui le candidature sono ACCETTABILI.
  Frasi tipiche: "presentazione domande dal", "apertura sportello a partire da", "dalle ore X del DD/MM".
- **data_scadenza**: TERMINE ULTIMO per presentare.
  Frasi tipiche: "termine presentazione domande", "scade il", "entro le ore X del DD/MM", "deadline".

BLACKLIST contesti NORMATIVI (queste sono date della legge citata, NON del bando):
- "ai sensi del DPR/L/DGR/DM n. X del DD/MM/YYYY"
- "in attuazione di [normativa] del DD/MM/YYYY"
- "visto il [decreto] del DD/MM/YYYY"
- "richiamato il [provvedimento] del DD/MM/YYYY"

REGOLE:
1. Se una data non è chiaramente nel markdown: imposta date=null, source='missing', quote=null.
2. La quote DEVE essere una sottostringa LETTERALE e CONTIGUA del markdown (max 300 char) contenente la data.
   Sarà verificata. NON parafrasare, NON ricostruire.
3. Source:
   - 'official_pdf' se la data è in un link/riferimento a PDF ufficiale del bando
   - 'official_page' se nel contenuto HTML della pagina ufficiale
   - 'inferred' (sconsigliato) se ricavata da contesto non esplicito
   - 'missing' se non trovata o se non sei sicuro (date=null, quote=null)
4. Coerenza: data_pubblicazione <= data_apertura <= data_scadenza.
5. Se nel markdown NON ci sono date chiare, USA missing per tutte e tre (non indovinare).

== STATO_BANDO DATA-DRIVEN ==
Lo stato_bando emesso dal LLM sarà RICONCILIATO automaticamente con le date:
- Se data_scadenza < {oggi} (oggi) -> stato forzato a 'chiuso' (ignoro tua scelta)
- Se data_apertura > {oggi} (oggi) -> stato forzato a 'in apertura prossimamente'
- Altrimenti rispetta la tua decisione (aperto/chiuso/in apertura)

Quindi: emetti lo stato che pensi corretto, ma SAI che le date hanno priorità.
"""


def system_prompt(oggi=None) -> str:
    """System prompt con la data corrente in Europe/Rome (fix 8.a.4: niente
    mese+anno cablati). Sostituzione testuale, non .format(): il template
    contiene graffe letterali negli esempi di URL. `oggi` sovrascrivibile nei test."""
    return SYSTEM_PROMPT_TEMPLATE.replace("{oggi}", data_italiana(oggi or oggi_roma()))


def blocco_pagina(testo: str | None, budget: int = BUDGET_PROMPT_CHAR) -> str:
    """Il testo di pagina che entra nel prompt, al massimo `budget` caratteri.

    La testa (`TESTA_PROMPT_CHAR`) entra intera, perche' li' stanno il titolo e
    l'etichetta di stato; del resto entrano le sezioni con date e parole utili,
    nell'ordine del documento. Stringa vuota se non c'e' testo.
    """
    if not testo:
        return ""
    testa = testo[:TESTA_PROMPT_CHAR]
    resto = testo[TESTA_PROMPT_CHAR:]
    spazio = budget - len(testa) - 1          # 1 = l'a capo fra le due parti
    if not resto.strip() or spazio <= 0:
        return testa[:budget]
    from .impronte import seleziona_sezioni
    scelte = seleziona_sezioni(resto, spazio)
    return f"{testa}\n{scelte}" if scelte else testa


def _truncate(text: str | None, max_chars: int) -> str:
    """Tronca a max_chars con ellipsi. None -> stringa vuota."""
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def _build_user_prompt(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
    markdown: str = "",
) -> str:
    """Costruisce il user prompt per un singolo bando.

    Se markdown != "", include il contenuto Firecrawl della pagina del bando
    (usato per estrazione date affidabile).
    """
    titolo = _truncate(bando.get("titolo_raw"), 500)
    descrizione = _truncate(bando.get("descrizione_raw"), 2000)

    raw_data = bando.get("raw_data") or {}
    raw_data_str = _truncate(
        json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else "",
        2000,
    )

    fonte_url = fonte_ctx.get("link") or ""
    tipo_link = bando.get("tipo_link") or fonte_ctx.get("tipo_link") or ""
    categoria = fonte_ctx.get("categoria_nome") or ""
    tipologia = fonte_ctx.get("tipologia_nome") or ""

    link_bando_raw = bando.get("link_bando") or ""
    link_bando_display = link_bando_raw or "(nessun link)"

    # Segnali aggiuntivi derivati dal URL: titolo dallo slug + flag indice.
    slug_title = _extract_slug_title(link_bando_raw) if link_bando_raw else ""
    looks_index = _is_likely_index_url(link_bando_raw) if link_bando_raw else False

    # Hint di analisi URL
    url_hints: list[str] = []
    if looks_index:
        url_hints.append(
            "⚠ ATTENZIONE: l'URL del link bando ha un pattern tipico di PAGINA INDICE/ELENCO "
            "(es. termina con /bandi, /opportunita, /calendario, ?page=, ?filter_). "
            "Questo è un FORTISSIMO segnale per rifiutare come 'pagina indice'."
        )
    if slug_title and not titolo:
        url_hints.append(
            f"Titolo derivato dallo slug URL (perché titolo_raw vuoto): {slug_title!r}. "
            "Valuta se questo slug descrive un BANDO SPECIFICO (accetta) o una SEZIONE/INDICE (rifiuta)."
        )
    elif slug_title and len(titolo) < 10:
        url_hints.append(
            f"Titolo molto breve. Slug URL: {slug_title!r}. Usalo come segnale aggiuntivo."
        )
    hints_block = ("\nANALISI URL:\n- " + "\n- ".join(url_hints)) if url_hints else ""

    # Budget del prompt (fix 8.a.2): il testo arriva intero da `scarico.py` e
    # si riduce QUI, dove entra nel prompt, non alla sorgente.
    md_block = blocco_pagina(markdown) if markdown else "(non disponibile)"

    return f"""Analizza questo record candidato a bando.

CONTESTO FONTE
- URL fonte: {fonte_url}
- Tipo fonte: {tipo_link}  ("Opportunità" = pagina di bandi aperti; "Preavviso" = calendario futuri)
- Programma: {tipologia}  (es. PR FESR Lombardia)
- Categoria: {categoria}  (Regionale / Nazionale / CTE)

RECORD ESTRATTO
- Titolo: {titolo or "(vuoto)"}
- Descrizione: {descrizione or "(vuoto)"}
- Link bando: {link_bando_display}
- raw_data: {raw_data_str or "(vuoto)"}{hints_block}

CONTENUTO PAGINA (markdown Firecrawl del bando):
{md_block}

Chiama il tool `save_bando_analysis` con:
1. is_valid_bando, confidence_score, rejection_reason, stato_bando (valutazione qualitativa).
2. data_pubblicazione, data_apertura, data_scadenza (estratte dal MARKDOWN sopra, con citation).
   Se markdown non disponibile o non contiene date chiare: imposta date=null, source='missing', quote=null."""


# --- spesa del passo (giro 3, contratto `bandi-giro-3` §4) --------------------
#
# Il client Anthropic di questo modulo e' uno solo e lo usano preprocess, il
# ripiego `bando_resolver.resolve_bando`, l'enrich e la SEO. Il passo che deve
# contare la propria spesa apre `conta_spesa(contatori)`: ogni chiamata fatta
# dentro quel contesto (anche nei task che il passo crea con `gather`) finisce
# nei suoi `bilancio.Contatori` tramite l'involucro del client. Fuori dal
# contesto non si conta niente: la SEO, che conta da se' con i suoi contatori
# espliciti, non viene contata due volte.

_SPESA_DEL_PASSO: ContextVar[Any] = ContextVar("spesa_del_passo", default=None)


@contextmanager
def conta_spesa(contatori: Any):
    """Dentro il `with` le chiamate al modello si sommano a `contatori`."""
    token = _SPESA_DEL_PASSO.set(contatori)
    try:
        yield contatori
    finally:
        _SPESA_DEL_PASSO.reset(token)


#: Le voci dello scarico che entrano nella riga di spesa di un passo (§19.1).
VOCI_SCARICO: tuple[str, ...] = ("fetch", "fetch_304", "crediti_firecrawl")


def istantanea_scarico() -> dict[str, int]:
    """I contatori dello scarico del processo adesso: l'inizio del delta di un
    passo (giro 3, §19.1). Non crea lo scarico se non c'e' ancora (crearlo
    legge il registro dal DB): in quel caso non ha ancora scaricato niente, e
    il delta parte da zero."""
    try:
        from . import scarico
        corrente = getattr(scarico, "_SCARICO", None)
        contatori = getattr(corrente, "contatori", None)
    except Exception:                                      # pragma: no cover - difesa
        contatori = None
    return {nome: int(getattr(contatori, nome, 0) or 0) for nome in VOCI_SCARICO}


def aggiungi_delta_scarico(spesa: Any, prima: Mapping[str, int]) -> None:
    """Somma a `spesa` cio' che lo scarico ha fatto da `prima` (§19.1): ogni
    passo scrive nella sua riga i propri crediti, e nessun altro li riconta.
    Contatori azzerati nel frattempo (`scarico.svuota`): si conta da zero."""
    dopo = istantanea_scarico()
    for nome in VOCI_SCARICO:
        base, valore = int(prima.get(nome, 0) or 0), dopo[nome]
        delta = valore - base if valore >= base else valore
        if delta > 0:
            setattr(spesa, nome, int(getattr(spesa, nome, 0) or 0) + delta)


def registra_uso(modello: Any, risposta: Any) -> None:
    """Somma una risposta del modello ai contatori del passo, se ce n'e' uno.
    Non solleva: un conto non fatto e' un avviso, non un giro fallito."""
    contatori = _SPESA_DEL_PASSO.get()
    if contatori is None or risposta is None:
        return
    try:
        from . import bilancio
        bilancio.registra_chiamata(contatori, str(modello or ""), getattr(risposta, "usage", None),
                                   get_settings().listino_modelli)
    except Exception as e:                              # pragma: no cover - difesa
        logger.warning("[spesa] chiamata non contata: {}", e)


class _MessaggiContati:
    """`client.messages` con il conto: `create` chiama quello vero e poi conta."""

    def __init__(self, messaggi: Any) -> None:
        self._messaggi = messaggi

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        risposta = await self._messaggi.create(*args, **kwargs)
        registra_uso(kwargs.get("model"), risposta)
        return risposta

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._messaggi, nome)


class ClienteContato:
    """Involucro sottile del client Anthropic: tutto passa a quello vero, e
    `messages.create` conta la spesa nel contesto del passo (`conta_spesa`)."""

    def __init__(self, cliente: Any) -> None:
        self._cliente = cliente
        self.messages = _MessaggiContati(cliente.messages)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._cliente, nome)


@lru_cache(maxsize=1)
def _get_anthropic_client():
    """Singleton client async Anthropic, con il conto della spesa (§4)."""
    import anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY mancante in .env. Il pre-processor non può funzionare."
        )
    return ClienteContato(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key))


def _auto_reject(bando: dict[str, Any]) -> dict[str, Any] | None:
    """Pre-filter Python: se il bando ha contenuto trascurabile, salta il LLM
    e ritorna direttamente un rejection. Risparmio chiamate API."""
    titolo = (bando.get("titolo_raw") or "").strip()
    raw_data = bando.get("raw_data") or {}
    link = (bando.get("link_bando") or "").strip()

    # Vuoto totale
    if not titolo and not raw_data and not link:
        return {
            "is_valid_bando": False,
            "confidence_score": 1.0,
            "rejection_reason": "record vuoto (no titolo, no link, no metadati)",
            "stato_bando": "unknown",
        }
    # Titolo troppo corto e nessun altro segnale
    if titolo and len(titolo) < 5 and not link and not raw_data:
        return {
            "is_valid_bando": False,
            "confidence_score": 0.95,
            "rejection_reason": f"titolo troppo breve: {titolo!r}",
            "stato_bando": "unknown",
        }
    return None


async def _call_anthropic_with_retry(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str,
    max_retries: int = 3,
) -> Any:
    """Chiama l'API con retry exponential su rate limit / server errors."""
    import anthropic
    delay_base = 2.0
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[ANALYZE_TOOL],
                tool_choice={"type": "tool", "name": "save_bando_analysis"},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            last_err = e
            # Su 4xx non-429 non ha senso ritentare
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[preprocess] API status {} non retryabile: {}", status, e)
                raise
            sleep_s = (delay_base ** attempt) + random.uniform(0, 0.5)
            logger.warning(
                "[preprocess] retry attempt {}/{} dopo errore {}: sleep {:.1f}s",
                attempt + 1, max_retries, type(e).__name__, sleep_s,
            )
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Anthropic API: max_retries esauriti. Ultimo errore: {last_err}")


def _extract_tool_input(response: Any) -> dict[str, Any]:
    """Estrae l'argomento del tool call dal response Anthropic."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "save_bando_analysis":
            return dict(block.input)
    raise RuntimeError(
        f"Tool call save_bando_analysis non trovato nel response. "
        f"Blocks: {[getattr(b, 'type', None) for b in response.content]}"
    )


def _presunta_respinta(candidate: Any, markdown: str, label: str) -> bool:
    """Vero se la candidata passerebbe tutti i gate tranne G10 (data presunta).

    Serve solo al contatore `date_presunte_respinte`: nei 7 giorni d'ombra
    distingue l'effetto del prompt a 8 000 caratteri da quello di G10.
    """
    from . import date_validation as dv
    if not isinstance(candidate, dict):
        return False
    parsed = dv.parse_iso(candidate.get("date") if isinstance(candidate.get("date"), str) else None)
    quote = candidate.get("quote")
    if (parsed is None or not isinstance(quote, str) or not quote
            or candidate.get("source") not in dv._AUTHORITATIVE_SOURCES
            or dv.norm_cit(quote) not in dv.norm_cit(markdown)):
        return False
    compatibili = [d for d in dv.estrai_date_con_ruolo(quote)
                   if d.data == parsed and dv.ruolo_compatibile(d.ruolo, label)]
    return bool(compatibili) and all(dv.e_presunta(dv._intorno(quote, d)) for d in compatibili)


def _ora(candidate: Any, data: Any, ruolo: str) -> str | None:
    """L'ora della data validata, letta nella sua citazione ("HH:MM:SS")."""
    from .date_validation import ora_nella_citazione
    if data is None or not isinstance(candidate, dict):
        return None
    ora = ora_nella_citazione(candidate.get("quote"), data, ruolo)
    return ora.isoformat() if ora is not None else None


def _validate_analysis(
    analysis: dict[str, Any],
    markdown: str,
    bando_id: Any,
    *,
    provenienza: str | None = None,
) -> dict[str, Any]:
    """Validazione output LLM con triple-gate sulle date.

    Le date vengono validate via _validate_date_candidate (substring + source
    autoritativo + regex date in quote). Se NON passa il gate -> None.
    `provenienza` ('ente' | 'aggregatore') e' l'host di `link_bando`, deciso
    dal codice (§6.3).

    Poi applica reconciliation guard data-driven:
      - data_scadenza < oggi -> stato_bando='chiuso'
      - data_apertura > oggi -> 'in apertura prossimamente'
    """
    from .date_validation import validate_date_candidate, reconcile_stato_bando

    is_valid = bool(analysis.get("is_valid_bando", False))
    try:
        conf = float(analysis.get("confidence_score", 0.0))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0

    stato_llm = analysis.get("stato_bando", "unknown")
    if stato_llm not in ("aperto", "chiuso", "in apertura prossimamente", "unknown"):
        stato_llm = "unknown"

    rej = analysis.get("rejection_reason")
    if is_valid:
        rej = None
    elif rej:
        rej = str(rej)[:500]

    # Triple-gate validation sulle 3 date (solo per bandi validi: se rejected, le date
    # non hanno senso comunque).
    pub_date = None
    apt_date = None
    scad_date = None
    presunte = 0
    if is_valid:
        pub_date = validate_date_candidate(
            analysis.get("data_pubblicazione"), markdown, bando_id, "pubblicazione",
            log_prefix="preprocess/date", provenienza=provenienza,
        )
        apt_date = validate_date_candidate(
            analysis.get("data_apertura"), markdown, bando_id, "apertura",
            log_prefix="preprocess/date", provenienza=provenienza,
        )
        scad_date = validate_date_candidate(
            analysis.get("data_scadenza"), markdown, bando_id, "scadenza",
            log_prefix="preprocess/date", provenienza=provenienza,
        )
        for campo, label, valida in (("data_pubblicazione", "pubblicazione", pub_date),
                                     ("data_apertura", "apertura", apt_date),
                                     ("data_scadenza", "scadenza", scad_date)):
            if valida is None and _presunta_respinta(analysis.get(campo), markdown, label):
                presunte += 1
        # Coerenza temporale: pub <= apt <= scad. Se incoerente -> coerce tutte a None.
        from .date_validation import check_dates_coherence
        if not check_dates_coherence(pub_date, apt_date, scad_date):
            logger.warning(
                "[preprocess/{}] date incoerenti pub={} apt={} scad={} -> coerce tutte a None",
                bando_id, pub_date, apt_date, scad_date,
            )
            pub_date = apt_date = scad_date = None

    # Reconciliation data-driven: forza coerenza tra stato_bando e date estratte.
    stato_final = reconcile_stato_bando(stato_llm, apt_date, scad_date)
    if is_valid and stato_final != stato_llm and stato_final is not None:
        logger.info(
            "[preprocess/{}] stato_bando reconciled: LLM={!r} -> data-driven={!r} (apt={} scad={})",
            bando_id, stato_llm, stato_final, apt_date, scad_date,
        )

    return {
        "is_valid_bando": is_valid,
        "confidence_score": conf,
        "rejection_reason": rej,
        "stato_bando": stato_final,
        "data_pubblicazione": pub_date.isoformat() if pub_date else None,
        "data_apertura": apt_date.isoformat() if apt_date else None,
        "data_scadenza": scad_date.isoformat() if scad_date else None,
        "ora_apertura": _ora(analysis.get("data_apertura"), apt_date, "apertura"),
        "ora_scadenza": _ora(analysis.get("data_scadenza"), scad_date, "scadenza"),
        "_origine_scadenza": "modello" if scad_date else None,
        "_date_presunte_respinte": presunte,
        # Giro 3 (§8, §9): la frase della pagina che giustifica ogni data
        # passata dal gate. La rielaborazione dei pubblicati la porta negli
        # eventi di rettifica; nessuna colonna di `bando` la riceve.
        "_citazioni": {
            "data_pubblicazione": _citazione(analysis.get("data_pubblicazione"), pub_date),
            "data_apertura": _citazione(analysis.get("data_apertura"), apt_date),
            "data_scadenza": _citazione(analysis.get("data_scadenza"), scad_date),
        },
    }


def _citazione(candidata: Any, valida: Any) -> str | None:
    """La quote del modello per una data che ha passato il gate, o None."""
    if valida is None or not isinstance(candidata, Mapping):
        return None
    testo = str(candidata.get("quote") or "").strip()
    return testo or None


def provenienza_di(link: str | None) -> str | None:
    """'aggregatore' se `link_bando` sta su un aggregatore, 'ente' altrimenti (§6.3)."""
    from .dominio_ufficiale import dominio_di, e_aggregatore
    host = dominio_di(link) if link else None
    if not host:
        return None
    return "aggregatore" if e_aggregatore(host) else "ente"


def _coerente(pub: Any, apt: Any, fine: Any) -> bool:
    """Una scadenza candidata non precede ne' la pubblicazione ne' l'apertura."""
    return (pub is None or fine >= pub) and (apt is None or fine >= apt)


def _scadenza_oe_citata(raw: Mapping[str, Any], markdown: str, bando_id: Any, oggi: Any) -> Any:
    """La data della `deadline_label` di OE, solo se la scheda la cita (§19.5).

    Vale con status '1', una data da oggi in poi e la citazione «Scadenza: …»
    nel testo della scheda scaricata; poi passa da `validate_date_candidate`
    con provenienza aggregatore, come le scadenze OE che il modello legge gia'.
    La citazione e' «Scadenza: <etichetta>», «Scadenza: <data della
    etichetta>» oppure l'etichetta intera («Scade il 30/11/2026»): nient'altro
    (forme approvate dal lead il 30/09; manca ancora una scheda vera nelle
    fixture).
    """
    from .date_validation import norm_cit, termine_da_etichetta_oe, validate_date_candidate
    termine = termine_da_etichetta_oe(dict(raw))
    if termine is None or termine[0] < oggi:
        return None
    data = termine[0]
    etichetta = str(raw.get("deadline_label") or "").strip()
    testo = norm_cit(markdown)
    for citazione in (f"Scadenza: {etichetta}", f"Scadenza: {data:%d/%m/%Y}", etichetta):
        if norm_cit(citazione) in testo:
            return validate_date_candidate(
                {"date": data.isoformat(), "source": "official_page", "quote": citazione},
                markdown, bando_id, "scadenza", log_prefix="preprocess/oe",
                provenienza="aggregatore")
    return None


def completa_dopo_il_modello(
    analysis: dict[str, Any],
    bando: Mapping[str, Any],
    markdown: str,
    lettura: Any = None,
    *,
    oggi: Any = None,
    markdown_etichetta: str | None = None,
) -> dict[str, Any]:
    """Quello che il preprocess aggiunge dopo il modello, senza chiamarlo (§6.3, §19.5). Pura.

    Solo per un bando valido; la scadenza del modello non si tocca mai.
    1. Lettore per ente (`lettura`, gia' filtrata: niente generico, niente solo
       segnale): il termine finale diventa `data_scadenza` se il modello non
       l'ha data; un 'chiuso' con `puo_chiudere` porta lo stato a 'chiuso'.
    2. Finestra di presentazione nel testo della pagina: la fine piu' tarda,
       certa e con un verbo di presentazione, se la scadenza manca ancora.
    3. OE: la `deadline_label` citata sulla scheda (status '1'), per ultima
       perche' e' la fonte meno affidabile. Status '2' → 'in apertura
       prossimamente', salvo un 'chiuso' per date. `on_arrival` non si usa.
       Giro 3 (§8): quando il testo letto e' la pagina ufficiale, la
       citazione si cerca nel testo della scheda OE (`markdown_etichetta`).
    Le date nuove non precedono mai pubblicazione e apertura.
    """
    from .date_validation import estrai_finestra, parse_iso, reconcile_stato_bando
    risultato = dict(analysis)
    risultato.setdefault("_origine_scadenza", "modello" if analysis.get("data_scadenza") else None)
    if not analysis.get("is_valid_bando"):
        return risultato
    giorno = oggi or oggi_roma()
    pub = parse_iso(analysis.get("data_pubblicazione"))
    apt = parse_iso(analysis.get("data_apertura"))
    scad = parse_iso(analysis.get("data_scadenza"))
    ora_scad = analysis.get("ora_scadenza")
    origine = risultato["_origine_scadenza"]
    chiuso_da_lettore = False

    if lettura is not None:
        termine = getattr(lettura, "termine_finale", None)
        if scad is None and termine is not None and _coerente(pub, apt, termine.data):
            scad, origine = termine.data, "lettore"
            ora_scad = termine.ora.isoformat() if termine.ora is not None else None
        chiuso_da_lettore = lettura.stato == "chiuso" and bool(lettura.puo_chiudere)

    if scad is None:
        finestre = [f for f in estrai_finestra(markdown)
                    if f.fine is not None and f.per_presentare and not f.presunta
                    and _coerente(pub, apt, f.fine)]
        if finestre:
            ultima = max(finestre, key=lambda f: f.fine)
            scad, origine = ultima.fine, "finestra"
            ora_scad = ultima.ora_fine.isoformat() if ultima.ora_fine is not None else None

    raw = bando.get("raw_data")
    status = str(raw.get("status") or "").strip() if isinstance(raw, Mapping) else ""
    if scad is None and status == "1":
        testo_scheda = markdown if markdown_etichetta is None else markdown_etichetta
        dalla_scheda = _scadenza_oe_citata(raw, testo_scheda, bando.get("id"), giorno)
        if dalla_scheda is not None and _coerente(pub, apt, dalla_scheda):
            scad, origine, ora_scad = dalla_scheda, "etichetta_oe", None

    stato = reconcile_stato_bando(analysis.get("stato_bando"), apt, scad, today=giorno)
    status2 = False
    if chiuso_da_lettore:
        stato = "chiuso"
    elif status == "2" and stato != "chiuso":
        stato, status2 = "in apertura prossimamente", True

    risultato.update({
        "stato_bando": stato,
        "data_scadenza": scad.isoformat() if scad else None,
        "ora_scadenza": ora_scad if scad else None,
        "_origine_scadenza": origine if scad else None,
        "_chiuso_da_lettore": chiuso_da_lettore,
        "_status2_in_apertura": status2,
    })
    return risultato


#: Gli elementi che nel testo della pagina fanno un paragrafo a se'.
_BLOCCHI_HTML: tuple[str, ...] = (
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "dt", "dd", "blockquote",
    "section", "article", "div",
)
_SPAZI_IN_RIGA_RE = re.compile(r"[ \t\u00a0]+")
_A_CAPO_RE = re.compile(r" *\n *")
_RIGHE_VUOTE_RE = re.compile(r"\n{3,}")


def testo_strutturato(markdown: str, html: str | None) -> str:
    """Il testo della pagina diviso in paragrafi, per il blocco del prompt.

    Il markdown di Firecrawl ha gia' i suoi a capo e resta com'e'. Il testo
    visibile che arriva da httpx invece e' una riga sola, menu compresi, e
    `seleziona_sezioni` non ci troverebbe nessuna sezione: su LazioEuropa la
    scadenza restava fuori. In quel caso il testo si ricostruisce dall'HTML
    della stessa risposta, ripulito come per le impronte (`impronte.pulisci`,
    niente menu ne' contorno), con un paragrafo per elemento di blocco e gli
    spazi fra un tag e l'altro («le ore 17:00», non «le ore17:00»).
    """
    if not html or markdown.count("\n") >= 3:
        return markdown
    from .impronte import pulisci
    zuppa = pulisci(html)
    radice = zuppa.body or zuppa
    for tag in radice.find_all(_BLOCCHI_HTML):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")
    testo = _SPAZI_IN_RIGA_RE.sub(" ", radice.get_text(" "))
    testo = _RIGHE_VUOTE_RE.sub("\n\n", _A_CAPO_RE.sub("\n", testo)).strip()
    return testo or markdown


async def _pagina_in_cache(link: str) -> Any:
    """La risposta della pagina del bando, di norma dalla cache del giro.

    `scarica_markdown` l'ha appena messa in cache sotto la stessa chiave, quindi
    qui non si scarica niente. Se la cache non c'e' e' una GET httpx
    (`principale=False`): MAI il ripiego a pagamento.
    """
    from . import scarico as scarico_mod
    try:
        risposta = await asyncio.wait_for(
            scarico_mod.scarico_corrente().scarica(link, principale=False), TETTO_LETTORE_S)
    except Exception as e:                    # tempo scaduto, rete, host vietato
        logger.debug("[preprocess] pagina non riletta {}: {}", link, e)
        return None
    return risposta if risposta.ok else None


def lettura_per_ente(pagina: Any, link: str, titolo: str, oggi: Any) -> Any:
    """La lettura di un lettore per ente sulla pagina, o None.

    Il lettore generico e le letture solo segnale non cambiano niente
    all'ingresso: restano fuori.
    """
    from .etichette_stato import leggi
    if pagina is None or not getattr(pagina, "html", ""):
        return None
    lettura = leggi(pagina.html, getattr(pagina, "url_finale", "") or link, titolo, oggi=oggi)
    if lettura is None or lettura.estrattore == "generico" or lettura.solo_segnale:
        return None
    return lettura


async def analyze_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
    *,
    url_lettura: str | None = None,
) -> dict[str, Any]:
    """Analizza un singolo bando via Claude Haiku 4.5 con Firecrawl markdown.

    1. Pre-filter auto-reject.
    2. Markdown della pagina via `scarico.py` (cache per giro, ripiego
       Firecrawl solo se la pagina httpx non basta).
    3. Se markdown vuoto/troppo corto -> sentinel _needs_fallback=True per
       triggerare bando_resolver lato runner.
    4. LLM Haiku 4.5 con tool use esteso (validità + stato + 3 date).
    5. Triple-gate validation date + reconciliation data-driven.

    `url_lettura` (giro 3, §8): la pagina da leggere, di norma la fonte
    ufficiale scelta con `dominio_ufficiale.scegli_fonte`. Scarico, rilettura
    dalla cache, provenienza e lettore per ente lavorano su di lei; il prompt
    continua a mostrare `link_bando`. Senza, si legge `link_bando` come prima.

    Args:
        bando: dict con id, titolo_raw, descrizione_raw, link_bando, raw_data, tipo_link.
        fonte_ctx: dict con link (URL fonte), tipo_link, categoria_nome, tipologia_nome.

    Returns:
        dict {is_valid_bando, confidence_score, rejection_reason, stato_bando,
              data_pubblicazione, data_apertura, data_scadenza, _citazioni,
              _needs_fallback (bool, true se richiede bando_resolver)}.
    """
    bando_id = bando.get("id")

    # 1. Pre-filter difensivo
    auto = _auto_reject(bando)
    if auto is not None:
        logger.debug("[preprocess/{}] auto-reject: {}", bando_id, auto["rejection_reason"])
        # Aggiungi 3 date null + flag no-fallback (auto-reject e' definitivo)
        auto = {
            **auto,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": False,
        }
        return auto

    # 2. Markdown della pagina da leggere (se disponibile). Il wrapper storico
    # chiama `scarico.py`: cache per giro, nessun fallimento memorizzato.
    link_bando = str(bando.get("link_bando") or "")
    link = str(url_lettura or link_bando)
    markdown = ""
    if link:
        from .enricher import _firecrawl_scrape_markdown
        try:
            markdown = await _firecrawl_scrape_markdown(link)
        except Exception as e:
            logger.debug("[preprocess/{}] scarico fallito: {}", bando_id, e)

    # 3. Markdown vuoto/troppo corto -> richiede fallback bando_resolver
    if not markdown or len(markdown) < 200:
        logger.info(
            "[preprocess/{}] markdown vuoto/troppo corto ({} char) -> need fallback",
            bando_id, len(markdown),
        )
        return {
            "is_valid_bando": False,
            "confidence_score": 0.0,
            "rejection_reason": None,
            "stato_bando": None,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": True,
        }

    # 4. LLM call Haiku 4.5, sul testo della pagina con i suoi paragrafi (la
    #    stessa risposta serve dopo al lettore per ente).
    pagina = await _pagina_in_cache(link)
    markdown = testo_strutturato(markdown, getattr(pagina, "html", None))
    settings = get_settings()
    client = _get_anthropic_client()
    user_prompt = _build_user_prompt(bando, fonte_ctx, markdown=markdown)

    response = await _call_anthropic_with_retry(
        client,
        model=settings.preprocess_model,
        # max_tokens esteso per ospitare 3 date * 300 char quote + overhead JSON
        max_tokens=max(settings.preprocess_max_tokens, 800),
        system=system_prompt(),
        user_prompt=user_prompt,
    )

    raw_analysis = _extract_tool_input(response)

    # 5. Validation + reconciliation
    provenienza = provenienza_di(link)
    analysis = _validate_analysis(raw_analysis, markdown, bando_id, provenienza=provenienza)

    # 6. Dopo il modello (§6.3, §19.5): lettore per ente, finestra, etichetta
    #    OE. Il lettore non legge le schede degli aggregatori.
    if analysis["is_valid_bando"]:
        giorno = oggi_roma()
        lettura = None
        if provenienza == "ente":
            lettura = lettura_per_ente(pagina, link, str(bando.get("titolo_raw") or ""), giorno)
        completata = completa_dopo_il_modello(analysis, bando, markdown, lettura, oggi=giorno)
        if (not completata.get("data_scadenza") and link != link_bando and link_bando
                and _status_oe(bando) == "1"):
            # Giro 3 (§8): letta la pagina ufficiale, la scadenza e' ancora
            # vuota. La citazione dell'etichetta OE sta sulla scheda: si
            # rilegge `link_bando` (cache del giro, al piu' una GET httpx) e
            # si cerca solo quella, senza modello.
            scheda = await _pagina_in_cache(link_bando)
            testo_scheda = getattr(scheda, "testo", "") or ""
            if testo_scheda:
                completata = completa_dopo_il_modello(
                    analysis, bando, markdown, lettura, oggi=giorno,
                    markdown_etichetta=testo_scheda)
        analysis = completata
    analysis["_needs_fallback"] = False

    logger.debug(
        "[preprocess/{}] valid={} conf={:.2f} stato={} rej={!r} dates: pub={} apt={} scad={}",
        bando_id,
        analysis["is_valid_bando"],
        analysis["confidence_score"],
        analysis["stato_bando"],
        analysis.get("rejection_reason"),
        analysis.get("data_pubblicazione"),
        analysis.get("data_apertura"),
        analysis.get("data_scadenza"),
    )
    return analysis


def _status_oe(bando: Mapping[str, Any]) -> str:
    """Lo `status` di una riga OE in `raw_data` ('1' aperto, '2' in apertura)."""
    raw = bando.get("raw_data")
    return str(raw.get("status") or "").strip() if isinstance(raw, Mapping) else ""
