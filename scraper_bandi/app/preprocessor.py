"""Pre-processing dei bandi via Claude Haiku 4.5.

Per ogni bando con stato_processing='scraped':
  1. Costruisce un payload con titolo + descrizione + URL + raw_data + contesto fonte.
  2. Chiama Claude Haiku con tool use per garantire JSON strutturato.
  3. Ritorna analisi {is_valid_bando, confidence_score, rejection_reason, stato_bando}.

L'aggiornamento DB e' fatto dall'orchestrator (bando_preprocess_runner).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, unquote

from .logger import logger
from .settings import get_settings


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
                "OBBLIGATORIO se date non null. Sara' verificato come substring esatta."
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
                    "True se e' un vero bando/avviso/call per finanziamenti UE 2021-2027. "
                    "False se e' pagina indice/archivio/contenuto generico/link sbagliato/header tabella/titolo troppo generico."
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
                    "Sara' poi riconciliato automaticamente con le date: "
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


SYSTEM_PROMPT = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027 \
(FESR, FSE+, JTF, INTERREG). Il tuo compito e' validare ogni record candidato a "bando" \
estratto da portali istituzionali (regioni, ministeri, programmi CTE), eliminando i falsi positivi.

== REGOLA AUREA: BANDO SINGOLO, NON ELENCO ==
Il tuo OBIETTIVO PRINCIPALE e' distinguere:
  A) Pagina di DETTAGLIO di UN SINGOLO bando -> VALIDO
  B) Pagina di ELENCO / INDICE / CATEGORIA che lista PIU' bandi -> NON VALIDO

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
- Link di navigazione (titolo come "Home", "Indietro", "Tutte le opportunita'", "Tutti i bandi")
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
- "aperto": il bando e' attivo, le candidature sono aperte
- "chiuso": il bando e' scaduto / completato / archiviato
- "in apertura prossimamente": preavviso / pre-informativa / call non ancora aperta
- "unknown": impossibile determinare (penalizza la confidence!)

INDIZI utili per lo stato:
- Tipo fonte = "Preavviso" -> molto probabilmente "in apertura prossimamente"
- Tipo fonte = "Opportunita'" + link in /bandi-aperti/ -> "aperto"
- Descrizione contiene "scaduto", "chiuso", "archivio", date passate -> "chiuso"
- raw_data ha 'data_pubblicazione_prevista' / 'data_apertura_prevista' futura -> "in apertura prossimamente"
- raw_data ha 'data_scadenza' passata -> "chiuso"
- Senza indizi precisi e tipo "Opportunita'": "aperto" (default ragionevole)

== CONFIDENZA ==
- 0.9-1.0: certezza (titolo descrittivo + URL specifico + segnali coerenti)
- 0.7-0.9: alta confidenza con piccoli dubbi
- 0.5-0.7: media (segnali deboli, possibili interpretazioni multiple)
- <0.5: incerto (usa per casi dubbi: meglio rifiutare con questa confidence)

== ESTRAZIONE DATE (CRITICO) ==
Data attuale: giugno 2026. Formato italiano DD/MM/YYYY. Output sempre ISO YYYY-MM-DD.

Devi estrarre 3 date dal CONTENUTO PAGINA (markdown Firecrawl) — non dal titolo o raw_data:
- **data_pubblicazione**: data di PUBBLICAZIONE del bando sulla fonte ufficiale (BUR, GU, sito ente).
  Frasi tipiche: "pubblicato il", "data di pubblicazione", "avviso pubblicato in data".
  NON e' la data odierna, NON e' la data di scraping.
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
1. Se una data non e' chiaramente nel markdown: imposta date=null, source='missing', quote=null.
2. La quote DEVE essere una sottostringa LETTERALE e CONTIGUA del markdown (max 300 char) contenente la data.
   Sara' verificata. NON parafrasare, NON ricostruire.
3. Source:
   - 'official_pdf' se la data e' in un link/riferimento a PDF ufficiale del bando
   - 'official_page' se nel contenuto HTML della pagina ufficiale
   - 'inferred' (sconsigliato) se ricavata da contesto non esplicito
   - 'missing' se non trovata o se non sei sicuro (date=null, quote=null)
4. Coerenza: data_pubblicazione <= data_apertura <= data_scadenza.
5. Se nel markdown NON ci sono date chiare, USA missing per tutte e tre (non indovinare).

== STATO_BANDO DATA-DRIVEN ==
Lo stato_bando emesso dal LLM sara' RICONCILIATO automaticamente con le date:
- Se data_scadenza < giugno 2026 (oggi) -> stato forzato a 'chiuso' (ignoro tua scelta)
- Se data_apertura > giugno 2026 (oggi) -> stato forzato a 'in apertura prossimamente'
- Altrimenti rispetta la tua decisione (aperto/chiuso/in apertura)

Quindi: emetti lo stato che pensi corretto, ma SAI che le date hanno priorita'.
"""


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
            "Questo e' un FORTISSIMO segnale per rifiutare come 'pagina indice'."
        )
    if slug_title and not titolo:
        url_hints.append(
            f"Titolo derivato dallo slug URL (perche' titolo_raw vuoto): {slug_title!r}. "
            "Valuta se questo slug descrive un BANDO SPECIFICO (accetta) o una SEZIONE/INDICE (rifiuta)."
        )
    elif slug_title and len(titolo) < 10:
        url_hints.append(
            f"Titolo molto breve. Slug URL: {slug_title!r}. Usalo come segnale aggiuntivo."
        )
    hints_block = ("\nANALISI URL:\n- " + "\n- ".join(url_hints)) if url_hints else ""

    md_block = _truncate(markdown, 4000) if markdown else "(non disponibile)"

    return f"""Analizza questo record candidato a bando.

CONTESTO FONTE
- URL fonte: {fonte_url}
- Tipo fonte: {tipo_link}  ("Opportunita'" = pagina di bandi aperti; "Preavviso" = calendario futuri)
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


@lru_cache(maxsize=1)
def _get_anthropic_client():
    """Singleton client async Anthropic."""
    import anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY mancante in .env. Il pre-processor non puo' funzionare."
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


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


def _validate_analysis(
    analysis: dict[str, Any],
    markdown: str,
    bando_id: Any,
) -> dict[str, Any]:
    """Validazione output LLM con triple-gate sulle date.

    Le date vengono validate via _validate_date_candidate (substring + source
    autoritativo + regex date in quote). Se NON passa il gate -> None.

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
    if is_valid:
        pub_date = validate_date_candidate(
            analysis.get("data_pubblicazione"), markdown, bando_id, "pubblicazione",
            log_prefix="preprocess/date",
        )
        apt_date = validate_date_candidate(
            analysis.get("data_apertura"), markdown, bando_id, "apertura",
            log_prefix="preprocess/date",
        )
        scad_date = validate_date_candidate(
            analysis.get("data_scadenza"), markdown, bando_id, "scadenza",
            log_prefix="preprocess/date",
        )
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
    }


async def analyze_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Analizza un singolo bando via Claude Haiku 4.5 con Firecrawl markdown.

    1. Pre-filter auto-reject.
    2. Firecrawl markdown del link_bando (cache LRU condivisa con enricher).
    3. Se markdown vuoto/troppo corto -> sentinel _needs_fallback=True per
       triggerare bando_resolver lato runner.
    4. LLM Haiku 4.5 con tool use esteso (validita + stato + 3 date).
    5. Triple-gate validation date + reconciliation data-driven.

    Args:
        bando: dict con id, titolo_raw, descrizione_raw, link_bando, raw_data, tipo_link.
        fonte_ctx: dict con link (URL fonte), tipo_link, categoria_nome, tipologia_nome.

    Returns:
        dict {is_valid_bando, confidence_score, rejection_reason, stato_bando,
              data_pubblicazione, data_apertura, data_scadenza,
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

    # 2. Firecrawl markdown del link_bando (se disponibile)
    link = bando.get("link_bando") or ""
    markdown = ""
    if link:
        from .enricher import _firecrawl_scrape_markdown
        try:
            markdown = await _firecrawl_scrape_markdown(link)
        except Exception as e:
            logger.debug("[preprocess/{}] Firecrawl fail: {}", bando_id, e)

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

    # 4. LLM call Haiku 4.5
    settings = get_settings()
    client = _get_anthropic_client()
    user_prompt = _build_user_prompt(bando, fonte_ctx, markdown=markdown)

    response = await _call_anthropic_with_retry(
        client,
        model=settings.preprocess_model,
        # max_tokens esteso per ospitare 3 date * 300 char quote + overhead JSON
        max_tokens=max(settings.preprocess_max_tokens, 800),
        system=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    raw_analysis = _extract_tool_input(response)

    # 5. Validation + reconciliation
    analysis = _validate_analysis(raw_analysis, markdown, bando_id)
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
