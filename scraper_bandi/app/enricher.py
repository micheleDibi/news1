"""Enrichment dei bandi via Claude Haiku 4.5 + `scarico.py`.

Due famiglie di funzioni:

A) refine_stato_bando(): determinazione obbligatoria dello stato per i bandi
   con stato_bando=NULL. Scarica la pagina (se presente) tramite `scarico.py`
   — httpx, ripiego Firecrawl solo se serve — + LLM per analisi.

B) extract_* (7 funzioni): classificazione FK + junction per i bandi
   aperti/in apertura. Una LLM call per categoria, eseguite in PARALLELO
   via asyncio.gather.

Vincolo assoluto: nessun nuovo valore creato nelle tabelle catalogo.
Solo lookup di valori esistenti. Se il LLM ritorna un id non in catalogo:
filtrato out silenziosamente.
"""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from .logger import logger
from .preprocessor import _get_anthropic_client
from .settings import get_settings
from .stato_bando import data_italiana, oggi_roma


# Riusiamo il helper del preprocessor per costanza
def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s if len(s) <= max_chars else s[: max_chars - 3] + "..."


# ---------------------------------------------------------------------------
# Scarico: due wrapper sottili su `scarico.py` (fix 8.a.1 e 8.a.2)
# ---------------------------------------------------------------------------
#
# I nomi restano questi perche' quattro chiamanti li importano gia'
# (`bando_enrich_runner`, `bando_resolver`, `bando_seo_runner`, `preprocessor`)
# e i test li sostituiscono con dei mock; ma la cache, il client, il throttle,
# i ritentativi e il contatore dei crediti stanno tutti in `scarico.py`.
#
# Due differenze di comportamento volute rispetto alla vecchia
# `_FIRECRAWL_CACHE`:
#   1. un fallimento non entra piu' in cache (prima un 500 passeggero
#      condannava quell'URL per tutta la vita del processo);
#   2. il testo NON viene troncato qui. Il budget appartiene al prompt che
#      consuma il testo: `_build_classify_prompt` (2 500), `refine_stato_bando`
#      (3 000), `preprocessor._build_user_prompt` (4 000),
#      `bando_resolver._build_resolver_prompt` (6 000), e il ritaglio esplicito
#      in `bando_seo_runner`. Troncare alla sorgente buttava via testo che a
#      valle serviva (fix 8.a.2).
#
# La firma resta compatibile: `come_fonte` e' un keyword-only con default
# falso, quindi i quattro chiamanti non cambiano. Chi prende la pagina come
# FONTE UFFICIALE (oggi `bando_resolver._resolve_fonte`, che scarica
# `fonte['link']`) deve passare `come_fonte=True` per avere la denylist degli
# aggregatori del fix 8.a.12.


async def _firecrawl_scrape_markdown(url: str, *, come_fonte: bool = False) -> str:
    """Markdown della pagina principale del bando (Firecrawl solo se serve).

    `come_fonte=True` solo quando l'URL viene preso come **fonte ufficiale**:
    allora vale la denylist degli aggregatori (fix 8.a.12) e un host vietato
    ritorna "" con un warning invece di un testo plausibile. Il default e'
    falso perche' la scheda di un bando su un aggregatore e' spesso l'unica
    pagina esistente (`link_bando` di migliaia di righe punta a
    obiettivoeuropa.com): vietarla a tappeto manderebbe in `rejected` ogni
    bando nuovo di quella fonte.
    """
    from .scarico import ScaricoVietatoError, scarica_markdown
    try:
        return await scarica_markdown(url, come_fonte=come_fonte)
    except ScaricoVietatoError as e:
        logger.warning("[enricher] scarico vietato per {}: {}", url, e)
        return ""
    except Exception as e:
        logger.warning("[enricher] scarico fallito per {}: {}", url, e)
        return ""


async def _httpx_fetch_text(url: str, *, come_fonte: bool = False) -> str:
    """Testo visibile via httpx, senza ripiego Firecrawl (nessun credito).

    Per `come_fonte` vale quanto scritto sopra.
    """
    from .scarico import ScaricoVietatoError, scarica_testo
    try:
        return await scarica_testo(url, come_fonte=come_fonte)
    except ScaricoVietatoError as e:
        logger.debug("[enricher] scarico vietato per {}: {}", url, e)
        return ""
    except Exception as e:
        logger.debug("[enricher] httpx fetch fail per {}: {}", url, e)
        return ""


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

REFINE_STATO_TOOL = {
    "name": "save_refinement",
    "description": "Salva la determinazione dello stato del bando dopo analisi pagina.",
    "input_schema": {
        "type": "object",
        "properties": {
            "stato_bando": {
                "type": "string",
                "enum": ["aperto", "chiuso", "in apertura prossimamente"],
                "description": (
                    "Stato OBBLIGATORIO del bando. "
                    "'aperto'=candidature attualmente accettate; "
                    "'chiuso'=scadenza passata o stato esplicitamente chiuso; "
                    "'in apertura prossimamente'=preavviso, data di apertura futura, non ancora attivo."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidenza nella classificazione.",
            },
            "reason": {
                "type": "string",
                "description": "Motivo breve (max 200 char) basato sui segnali trovati.",
            },
        },
        "required": ["stato_bando", "confidence"],
    },
}


def _single_select_tool(name: str, catalog: list[dict[str, Any]], item_descr: str) -> dict:
    """Costruisce un tool single-select con enum sui valori catalogo."""
    valid_ids = [int(c["id"]) for c in catalog]
    return {
        "name": f"save_{name}",
        "description": f"Seleziona UN id dal catalogo {item_descr} (o null se nessuno applicabile).",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": ["integer", "null"],
                    "enum": valid_ids + [None] if valid_ids else [None],
                    "description": f"id del {item_descr} (None se non identificabile o non in catalogo).",
                },
            },
            "required": ["id"],
        },
    }


def _multi_select_tool(name: str, catalog: list[dict[str, Any]], item_descr: str) -> dict:
    """Costruisce un tool multi-select con array di id dal catalogo."""
    valid_ids = [int(c["id"]) for c in catalog]
    return {
        "name": f"save_{name}",
        "description": (
            f"Seleziona TUTTI gli id applicabili dal catalogo {item_descr}. "
            f"Array vuoto se nessuno applicabile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "integer", "enum": valid_ids} if valid_ids else {"type": "integer"},
                    "description": f"Array di id {item_descr} applicabili.",
                },
            },
            "required": ["ids"],
        },
    }


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

REFINE_SYSTEM_TEMPLATE = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027. \
Determina lo STATO ATTUALE del bando in modo obbligatorio.

SEGNALI per determinare lo stato:

APERTO (le candidature sono accettate ora):
- Presenza di "scadenza", "data scadenza", "presentare domanda entro" con data FUTURA
- Badge/etichetta esplicita "Aperto", "Bando attivo", "Aperto al pubblico"
- Link a portale per inviare domande attivo
- Fase del bando: "presentazione domande", "istruttoria in corso"

CHIUSO (scadenza passata o ufficialmente chiuso):
- "scadenza" con data PASSATA rispetto a oggi
- Badge "Chiuso", "Bando scaduto", "Termini scaduti", "Esiti pubblicati"
- Presenza di "graduatorie pubblicate", "elenco beneficiari", "rendicontazione"
- "Avviso archiviato"

IN APERTURA PROSSIMAMENTE (preavviso, non ancora aperto):
- Badge "Preavviso", "Pre-informativa", "In uscita", "Programmato"
- Date di apertura FUTURE
- Assenza di indicazione "scadenza" specifica + tipo fonte "Preavviso"
- "Calendario inviti", "Inviti programmati"

Se senti dubbi: ragiona dal tipo di fonte (Preavviso vs Opportunità) e dal contenuto raw_data.
La data attuale è {oggi}."""


def refine_system(oggi=None) -> str:
    """System prompt del refinement con la data corrente in Europe/Rome
    (fix 8.a.4: niente mese+anno cablati). `oggi` sovrascrivibile nei test."""
    return REFINE_SYSTEM_TEMPLATE.replace("{oggi}", data_italiana(oggi or oggi_roma()))


CLASSIFY_SYSTEM_TEMPLATE = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027. \
Classifica il bando rispetto al catalogo {category}.

VINCOLO ASSOLUTO: scegli SOLO id presenti nel catalogo fornito. \
NON inventare id. Se nessuna opzione è chiaramente applicabile, ritorna null/array vuoto.

Sii RIGOROSO: solo se trovi un match chiaro nei dati del bando (titolo, descrizione, \
URL, raw_data, pagina). In caso di incertezza, preferisci NON selezionare."""


def _format_catalog(catalog: list[dict[str, Any]], key_extra: str | None = None) -> str:
    """Formatta il catalogo come tabella compatta per il prompt."""
    if not catalog:
        return "(catalogo vuoto)"
    lines = []
    for c in catalog:
        cid = c.get("id")
        if key_extra == "ateco":
            nome = f"{c.get('codice','?')} — {c.get('descrizione','')}"
        else:
            nome = c.get("nome", "?")
        lines.append(f"  {cid}: {nome}")
    return "\n".join(lines)


def _build_classify_prompt(
    bando: dict[str, Any], fonte_ctx: dict[str, Any], html_text: str,
    catalog: list[dict[str, Any]], category_descr: str, ateco: bool = False,
) -> str:
    titolo = _truncate(bando.get("titolo_raw"), 300)
    descrizione = _truncate(bando.get("descrizione_raw"), 1000)
    raw_data = bando.get("raw_data") or {}
    raw_data_str = _truncate(
        json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else "",
        1000,
    )
    link = bando.get("link_bando") or "(nessun link)"
    fonte_url = fonte_ctx.get("link") or ""
    tipo_link = bando.get("tipo_link") or fonte_ctx.get("tipo_link") or ""
    cat_str = _format_catalog(catalog, key_extra="ateco" if ateco else None)
    html_block = f"\n\nCONTENUTO PAGINA (estratto):\n{_truncate(html_text, 2500)}" if html_text else ""

    return f"""Classifica il bando rispetto al catalogo {category_descr}.

CATALOGO disponibile:
{cat_str}

RECORD BANDO:
- Titolo: {titolo or "(vuoto)"}
- Descrizione: {descrizione or "(vuoto)"}
- Link: {link}
- raw_data: {raw_data_str or "(vuoto)"}
- Fonte URL: {fonte_url}
- Tipo fonte: {tipo_link}{html_block}

Chiama il tool corrispondente con la tua selezione (solo id dal catalogo, no inventati)."""


# ---------------------------------------------------------------------------
# Retry helper (riusa pattern preprocessor)
# ---------------------------------------------------------------------------

async def _call_anthropic_tool(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str, tool: dict,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    """Anthropic call con tool use forzato + retry exponential. Ritorna l'input
    del tool call, o None se fallisce."""
    import anthropic
    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool["name"]:
                    return dict(block.input)
            return None
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[enricher] API status {} non retryabile: {}", status, e)
                return None
            sleep_s = (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning("[enricher] retry {}/{} dopo {}: sleep {:.1f}s",
                           attempt + 1, max_retries, type(e).__name__, sleep_s)
            await asyncio.sleep(sleep_s)
        except Exception as e:
            logger.exception("[enricher] errore inatteso: {}", e)
            return None
    return None


# ---------------------------------------------------------------------------
# A. Refinement stato_bando
# ---------------------------------------------------------------------------

async def refine_stato_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
) -> tuple[str | None, float, str]:
    """Determina lo stato del bando via Firecrawl + LLM. Ritorna
    (stato_bando, confidence, reason).

    Fix 8.a.11: se il LLM fallisce o risponde fuori enum lo stato e' None
    con confidenza 0.0 (mai 'aperto' di ripiego): il bando resta
    'processed' e viene ritentato al giro successivo."""
    settings = get_settings()
    client = _get_anthropic_client()

    link = bando.get("link_bando") or ""
    page_text = ""
    if link:
        page_text = await _firecrawl_scrape_markdown(link)

    titolo = _truncate(bando.get("titolo_raw"), 300)
    descrizione = _truncate(bando.get("descrizione_raw"), 1000)
    raw_data = bando.get("raw_data") or {}
    raw_data_str = _truncate(
        json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else "",
        1500,
    )
    tipo_link = bando.get("tipo_link") or fonte_ctx.get("tipo_link") or ""
    fonte_url = fonte_ctx.get("link") or ""

    oggi_testo = data_italiana(oggi_roma())
    user_prompt = f"""Determina lo STATO ATTUALE del bando seguente (data: {oggi_testo}).

CONTESTO FONTE
- URL fonte: {fonte_url}
- Tipo fonte: {tipo_link}

RECORD BANDO
- Titolo: {titolo or "(vuoto)"}
- Descrizione: {descrizione or "(vuoto)"}
- Link bando: {link or "(nessuno)"}
- raw_data: {raw_data_str or "(vuoto)"}

CONTENUTO PAGINA (estratto Firecrawl markdown):
{_truncate(page_text, 3000) or "(non disponibile)"}

Chiama save_refinement con la tua determinazione."""

    result = await _call_anthropic_tool(
        client,
        model=settings.enrich_model,
        max_tokens=settings.enrich_max_tokens,
        system=refine_system(),
        user_prompt=user_prompt,
        tool=REFINE_STATO_TOOL,
    )
    if not result:
        # Nessun ripiego euristico: senza determinazione lo stato resta NULL.
        logger.warning(
            "[enricher/refine] bando_id={} LLM fallito: nessuno stato (resta 'processed')",
            bando.get("id"),
        )
        return (None, 0.0, "LLM fallito: nessuna determinazione")

    stato = result.get("stato_bando")
    if stato not in ("aperto", "chiuso", "in apertura prossimamente"):
        logger.warning(
            "[enricher/refine] bando_id={} stato fuori enum: {!r} (resta 'processed')",
            bando.get("id"), stato,
        )
        return (None, 0.0, f"stato fuori enum: {stato!r}")
    try:
        conf = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    reason = str(result.get("reason", ""))[:200]
    return (stato, conf, reason)


# ---------------------------------------------------------------------------
# B. Extract FK / junction
# ---------------------------------------------------------------------------

async def _extract_single(
    bando: dict[str, Any], fonte_ctx: dict[str, Any], html_text: str,
    catalog: list[dict[str, Any]], category_descr: str, tool_name: str,
    ateco: bool = False,
) -> int | None:
    """Helper per single-select FK extraction."""
    if not catalog:
        return None
    settings = get_settings()
    client = _get_anthropic_client()

    tool = _single_select_tool(tool_name, catalog, category_descr)
    user_prompt = _build_classify_prompt(bando, fonte_ctx, html_text, catalog, category_descr, ateco=ateco)
    system = CLASSIFY_SYSTEM_TEMPLATE.format(category=category_descr)

    result = await _call_anthropic_tool(
        client, model=settings.enrich_model, max_tokens=settings.enrich_max_tokens,
        system=system, user_prompt=user_prompt, tool=tool,
    )
    if not result:
        return None
    val = result.get("id")
    if val is None:
        return None
    try:
        val_int = int(val)
    except (TypeError, ValueError):
        return None
    valid_ids = {int(c["id"]) for c in catalog}
    return val_int if val_int in valid_ids else None


async def _extract_multi(
    bando: dict[str, Any], fonte_ctx: dict[str, Any], html_text: str,
    catalog: list[dict[str, Any]], category_descr: str, tool_name: str,
    ateco: bool = False,
) -> list[int]:
    """Helper per multi-select junction extraction."""
    if not catalog:
        return []
    settings = get_settings()
    client = _get_anthropic_client()

    tool = _multi_select_tool(tool_name, catalog, category_descr)
    user_prompt = _build_classify_prompt(bando, fonte_ctx, html_text, catalog, category_descr, ateco=ateco)
    system = CLASSIFY_SYSTEM_TEMPLATE.format(category=category_descr)

    result = await _call_anthropic_tool(
        client, model=settings.enrich_model, max_tokens=settings.enrich_max_tokens,
        system=system, user_prompt=user_prompt, tool=tool,
    )
    if not result:
        return []
    ids = result.get("ids", []) or []
    valid_ids = {int(c["id"]) for c in catalog}
    out: list[int] = []
    seen: set[int] = set()
    for i in ids:
        try:
            i_int = int(i)
        except (TypeError, ValueError):
            continue
        if i_int in valid_ids and i_int not in seen:
            out.append(i_int)
            seen.add(i_int)
    return out


# 7 funzioni public

async def extract_tipologia(bando, fonte_ctx, html_text, tipologie) -> int | None:
    return await _extract_single(bando, fonte_ctx, html_text, tipologie, "tipologia di bando", "tipologia")


async def extract_modalita(bando, fonte_ctx, html_text, modalita) -> int | None:
    return await _extract_single(bando, fonte_ctx, html_text, modalita, "modalità di erogazione", "modalita")


async def extract_programma(bando, fonte_ctx, html_text, programmi) -> int | None:
    return await _extract_single(bando, fonte_ctx, html_text, programmi, "programma di finanziamento UE", "programma")


async def extract_beneficiari(bando, fonte_ctx, html_text, beneficiari) -> list[int]:
    return await _extract_multi(bando, fonte_ctx, html_text, beneficiari, "beneficiari ammissibili", "beneficiari")


async def extract_codici_ateco(bando, fonte_ctx, html_text, ateco) -> list[int]:
    return await _extract_multi(bando, fonte_ctx, html_text, ateco, "codici ATECO", "codici_ateco", ateco=True)


async def extract_regioni(bando, fonte_ctx, html_text, regioni) -> list[int]:
    return await _extract_multi(bando, fonte_ctx, html_text, regioni, "regioni geografiche coperte", "regioni")


async def extract_settori(bando, fonte_ctx, html_text, settori) -> list[int]:
    return await _extract_multi(bando, fonte_ctx, html_text, settori, "settori di intervento", "settori")


# ---------------------------------------------------------------------------
# C. Wrapper per bando (7 call PARALLELE: FK + junction)
# ---------------------------------------------------------------------------
#
# Nota v9: la date extraction (precedentemente extract_date qui) e' stata
# SPOSTATA in preprocessor.py per ottenere stato_bando data-driven gia' a monte
# (riduce falsi positivi 'aperto' su bandi gia' scaduti). L'enricher si occupa
# solo di FK + junction.

async def enrich_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
    html_text: str,
    catalogo: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Esegue 7 extract_* di classificazione in parallelo (FK + junction).
    Ritorna dict pronto per update_bando_enriched."""
    results = await asyncio.gather(
        extract_tipologia(bando, fonte_ctx, html_text, catalogo.get("tipologie", [])),
        extract_modalita(bando, fonte_ctx, html_text, catalogo.get("modalita", [])),
        extract_programma(bando, fonte_ctx, html_text, catalogo.get("programmi", [])),
        extract_beneficiari(bando, fonte_ctx, html_text, catalogo.get("beneficiari", [])),
        extract_codici_ateco(bando, fonte_ctx, html_text, catalogo.get("codici_ateco", [])),
        extract_regioni(bando, fonte_ctx, html_text, catalogo.get("regioni", [])),
        extract_settori(bando, fonte_ctx, html_text, catalogo.get("settori", [])),
        return_exceptions=True,
    )
    # Coerce eccezioni a None/[]
    tipologia = results[0] if not isinstance(results[0], Exception) else None
    modalita = results[1] if not isinstance(results[1], Exception) else None
    programma = results[2] if not isinstance(results[2], Exception) else None
    beneficiari = results[3] if not isinstance(results[3], Exception) else []
    ateco = results[4] if not isinstance(results[4], Exception) else []
    regioni = results[5] if not isinstance(results[5], Exception) else []
    settori = results[6] if not isinstance(results[6], Exception) else []

    return {
        "tipologia_bando_id": tipologia,
        "modalita_erogazione_id": modalita,
        "programma_id": programma,
        "beneficiari_ids": beneficiari,
        "codici_ateco_ids": ateco,
        "regioni_ids": regioni,
        "settori_ids": settori,
    }
