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


# Tool schema: forza struttura JSON via tool use API.
ANALYZE_TOOL = {
    "name": "save_bando_analysis",
    "description": (
        "Salva il risultato dell'analisi del bando. "
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
                    "Stato attuale del bando. "
                    "'aperto'=candidature aperte; "
                    "'chiuso'=scaduto/completato; "
                    "'in apertura prossimamente'=preavviso/pre-informativa; "
                    "'unknown'=impossibile determinare (penalizza confidence)."
                ),
            },
        },
        "required": ["is_valid_bando", "confidence_score", "stato_bando"],
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
"""


def _truncate(text: str | None, max_chars: int) -> str:
    """Tronca a max_chars con ellipsi. None -> stringa vuota."""
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def _build_user_prompt(bando: dict[str, Any], fonte_ctx: dict[str, Any]) -> str:
    """Costruisce il user prompt per un singolo bando."""
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

    return f"""Analizza questo record candidato a bando:

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

Chiama il tool `save_bando_analysis` con la tua valutazione."""


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


def _validate_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Validazione output LLM. Coerce + default su error."""
    is_valid = bool(analysis.get("is_valid_bando", False))
    try:
        conf = float(analysis.get("confidence_score", 0.0))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0

    stato = analysis.get("stato_bando", "unknown")
    if stato not in ("aperto", "chiuso", "in apertura prossimamente", "unknown"):
        stato = "unknown"

    rej = analysis.get("rejection_reason")
    if is_valid:
        rej = None
    elif rej:
        rej = str(rej)[:500]

    return {
        "is_valid_bando": is_valid,
        "confidence_score": conf,
        "rejection_reason": rej,
        "stato_bando": stato,
    }


async def analyze_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Analizza un singolo bando via Claude Haiku 4.5.

    Args:
        bando: dict con id, titolo_raw, descrizione_raw, link_bando, raw_data, tipo_link.
        fonte_ctx: dict con link (URL fonte), tipo_link, categoria_nome, tipologia_nome.

    Returns:
        dict {is_valid_bando, confidence_score, rejection_reason, stato_bando}.
    """
    # Pre-filter difensivo
    auto = _auto_reject(bando)
    if auto is not None:
        logger.debug("[preprocess/{}] auto-reject: {}", bando.get("id"), auto["rejection_reason"])
        return auto

    settings = get_settings()
    client = _get_anthropic_client()
    user_prompt = _build_user_prompt(bando, fonte_ctx)

    response = await _call_anthropic_with_retry(
        client,
        model=settings.preprocess_model,
        max_tokens=settings.preprocess_max_tokens,
        system=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    raw_analysis = _extract_tool_input(response)
    analysis = _validate_analysis(raw_analysis)

    logger.debug(
        "[preprocess/{}] valid={} conf={:.2f} stato={} rej={!r}",
        bando.get("id"),
        analysis["is_valid_bando"],
        analysis["confidence_score"],
        analysis["stato_bando"],
        analysis.get("rejection_reason"),
    )
    return analysis
