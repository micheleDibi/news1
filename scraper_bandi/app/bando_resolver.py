"""Fallback skill per bandi senza markdown del bando.

Trigger (dal preprocess primary):
  - link_bando=NULL
  - Firecrawl del link_bando fallisce
  - markdown del bando vuoto o troppo corto (< 200 char)

Strategia:
  - Firecrawl markdown della FONTE (pagina indice di OpenCoesione/Regione che
    elenca il bando insieme ad altre opportunita').
  - LLM Sonnet 4.6 con extended reasoning per dedurre stato + date dal contesto
    indiretto.
  - Stesso tool schema del preprocess primary.
  - Stesso triple-gate + reconciliation.

Costo medio per bando fallback: ~$0.022 (Sonnet 4.6, ~5K tok input, ~500 tok output).
Su ~1000 bandi fallback attesi (33% dei 3000): ~$22.
"""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from .date_validation import (
    check_dates_coherence,
    reconcile_stato_bando,
    validate_date_candidate,
)
from .logger import logger
from .preprocessor import (
    ANALYZE_TOOL,
    _auto_reject,
    _extract_slug_title,
    _get_anthropic_client,
    _is_likely_index_url,
    _truncate,
)
from .settings import get_settings


RESOLVER_SYSTEM_PROMPT = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027 \
(FESR, FSE+, JTF, INTERREG). Stai analizzando un bando per il quale NON e' disponibile la \
pagina di dettaglio (link_bando assente o non raggiungibile via Firecrawl).

Ricevi invece il MARKDOWN DELLA PAGINA FONTE (la pagina indice/elenco della regione/ministero/\
programma che lista questo bando insieme ad altri). Dovrai usare RAGIONAMENTO ESTESO per dedurre:

1. Se e' un VERO BANDO o un falso positivo dell'estrazione.
2. Lo STATO ATTUALE del bando (aperto/chiuso/in apertura prossimamente).
3. Le 3 DATE chiave del bando.

== INFORMAZIONI A DISPOSIZIONE ==

- Titolo grezzo (dal scraper)
- Descrizione grezza (dal scraper)
- raw_data JSONB (metadati estratti, possono contenere date in formato vario)
- link_bando (eventualmente vuoto)
- tipo_link della fonte ('Opportunita'' o 'Preavviso')
- URL e markdown della FONTE (pagina indice)

== STRATEGIA DI RAGIONAMENTO ==

1. **Validita'**: cerca nella pagina fonte un blocco/riga/sezione che corrisponda a questo bando.
   Se non lo trovi affatto, il titolo o gli altri metadati ti permettono comunque di capire?
   Se trovi solo un riferimento vago (es. "Bando aiuti PMI 2024"), il titolo e la descrizione
   sono comunque concreti? -> is_valid_bando=true.
   Se invece il titolo e' generico tipo "Tutti i bandi", "Avvisi" -> false.

2. **Stato (data attuale: giugno 2026)**:
   - Tipo fonte 'Preavviso' + nessuna data passata -> probabilmente 'in apertura prossimamente'
   - "edizione 2024" / "Bando 2025" + giugno 2026 -> probabilmente 'chiuso'
   - "Bando 2026" / "anno 2026" o sezione "bandi aperti" -> probabilmente 'aperto'
   - raw_data ha data_scadenza nel passato -> 'chiuso'
   - raw_data ha data_apertura nel futuro -> 'in apertura prossimamente'
   - Se la pagina fonte e' un "calendario degli inviti" / "preavvisi" -> 'in apertura prossimamente'

3. **Date** (CRITICO - applica le STESSE regole del preprocess primary):
   - Cerca nel MARKDOWN DELLA FONTE date associate a QUESTO bando specifico (titolo simile,
     sezione dedicata).
   - **MAI** date di altri bandi della stessa fonte; **MAI** date odierne.
   - **Quote OBBLIGATORIA**: substring letterale del markdown fonte (max 300 char).
   - Source: 'official_page' se la data e' nel markdown fonte; 'inferred' se ricavata da
     contesto generale (es. anno 2024 -> "scadenza 31/12/2024"); 'missing' se non trovata.
   - BLACKLIST contesti normativi ("ai sensi del DPR del DD/MM/YYYY", "in attuazione di...").
   - Se le date NON sono identificabili nemmeno dalla fonte: date=null, source='missing', quote=null.

4. **Coerenza**: data_pubblicazione <= data_apertura <= data_scadenza.

== OUTPUT ==

Chiama save_bando_analysis con tutti i campi. Lo stato_bando sara' poi riconciliato
automaticamente con le date estratte (data_scadenza < oggi -> forzato 'chiuso')."""


def _build_resolver_prompt(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
    fonte_markdown: str,
) -> str:
    """Compone il prompt user con info bando + markdown della FONTE."""
    titolo = _truncate(bando.get("titolo_raw"), 500)
    descrizione = _truncate(bando.get("descrizione_raw"), 2000)
    raw_data = bando.get("raw_data") or {}
    raw_data_str = _truncate(
        json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else "",
        2500,
    )

    fonte_url = fonte_ctx.get("link") or ""
    tipo_link = bando.get("tipo_link") or fonte_ctx.get("tipo_link") or ""
    categoria = fonte_ctx.get("categoria_nome") or ""
    tipologia = fonte_ctx.get("tipologia_nome") or ""

    link_bando_raw = bando.get("link_bando") or ""
    link_bando_display = link_bando_raw or "(nessun link disponibile)"
    slug_title = _extract_slug_title(link_bando_raw) if link_bando_raw else ""
    looks_index = _is_likely_index_url(link_bando_raw) if link_bando_raw else False

    hints: list[str] = []
    if slug_title:
        hints.append(f"Slug URL: {slug_title!r}")
    if looks_index:
        hints.append("URL del bando ha pattern di INDICE (rifiuta come bando singolo).")
    hints_block = ("\nSEGNALI URL:\n- " + "\n- ".join(hints)) if hints else ""

    md_block = _truncate(fonte_markdown, 6000) if fonte_markdown else "(markdown fonte non disponibile)"

    return f"""Analizza questo bando senza accesso alla sua pagina dettagliata.

CONTESTO FONTE (la pagina indice)
- URL fonte: {fonte_url}
- Tipo fonte: {tipo_link}
- Programma: {tipologia}
- Categoria: {categoria}

RECORD ESTRATTO
- Titolo: {titolo or "(vuoto)"}
- Descrizione: {descrizione or "(vuoto)"}
- Link bando: {link_bando_display}
- raw_data: {raw_data_str or "(vuoto)"}{hints_block}

MARKDOWN DELLA FONTE (Firecrawl, ~6K char):
{md_block}

Chiama save_bando_analysis con la tua valutazione. Usa ragionamento esteso per dedurre stato e
date da segnali indiretti. Se le date non sono presenti nel markdown fonte (caso comune per
indici), imposta date=null, source='missing', quote=null per quelle non trovate."""


async def _call_anthropic_resolver(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str,
    max_retries: int = 3,
) -> Any:
    """Chiama Sonnet con retry exponential."""
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
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[resolver] API status {} non retryabile: {}", status, e)
                raise
            sleep_s = (delay_base ** attempt) + random.uniform(0, 0.5)
            logger.warning(
                "[resolver] retry attempt {}/{} dopo {}: sleep {:.1f}s",
                attempt + 1, max_retries, type(e).__name__, sleep_s,
            )
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Resolver API: max_retries esauriti. Ultimo errore: {last_err}")


def _extract_tool_input(response: Any) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "save_bando_analysis":
            return dict(block.input)
    raise RuntimeError("Tool call save_bando_analysis non trovato")


def _validate_resolver_output(
    analysis: dict[str, Any],
    fonte_markdown: str,
    bando_id: Any,
) -> dict[str, Any]:
    """Stessa validation di preprocessor._validate_analysis ma con log_prefix 'resolver/date'.
    Validation triple-gate sulle 3 date contro markdown FONTE.
    """
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

    pub_date = apt_date = scad_date = None
    if is_valid:
        pub_date = validate_date_candidate(
            analysis.get("data_pubblicazione"), fonte_markdown, bando_id, "pubblicazione",
            log_prefix="resolver/date",
        )
        apt_date = validate_date_candidate(
            analysis.get("data_apertura"), fonte_markdown, bando_id, "apertura",
            log_prefix="resolver/date",
        )
        scad_date = validate_date_candidate(
            analysis.get("data_scadenza"), fonte_markdown, bando_id, "scadenza",
            log_prefix="resolver/date",
        )
        if not check_dates_coherence(pub_date, apt_date, scad_date):
            logger.warning(
                "[resolver/{}] date incoerenti pub={} apt={} scad={} -> coerce tutte a None",
                bando_id, pub_date, apt_date, scad_date,
            )
            pub_date = apt_date = scad_date = None

    stato_final = reconcile_stato_bando(stato_llm, apt_date, scad_date)
    if is_valid and stato_final != stato_llm and stato_final is not None:
        logger.info(
            "[resolver/{}] stato_bando reconciled: LLM={!r} -> data-driven={!r}",
            bando_id, stato_llm, stato_final,
        )

    return {
        "is_valid_bando": is_valid,
        "confidence_score": conf,
        "rejection_reason": rej,
        "stato_bando": stato_final,
        "data_pubblicazione": pub_date.isoformat() if pub_date else None,
        "data_apertura": apt_date.isoformat() if apt_date else None,
        "data_scadenza": scad_date.isoformat() if scad_date else None,
        "_needs_fallback": False,
        "_fallback_used": True,
    }


async def resolve_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Risolve un bando senza markdown dedicato usando il markdown della FONTE.

    Args:
        bando: dict con id, titolo_raw, descrizione_raw, link_bando (eventualmente null),
               raw_data, tipo_link.
        fonte_ctx: dict con link (URL fonte), tipo_link, categoria_nome, tipologia_nome.

    Returns:
        dict {is_valid_bando, confidence_score, rejection_reason, stato_bando,
              data_*, _fallback_used=True}.

        Su fallimento totale (no fonte_link, no Firecrawl) -> rejection con _fallback_failed=True.
    """
    bando_id = bando.get("id")

    # Auto-reject se record vuoto
    auto = _auto_reject(bando)
    if auto is not None:
        return {
            **auto,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": False,
            "_fallback_used": True,
        }

    fonte_link = fonte_ctx.get("link") or ""
    if not fonte_link:
        logger.warning("[resolver/{}] fonte link assente, impossibile fallback", bando_id)
        return {
            "is_valid_bando": False,
            "confidence_score": 0.0,
            "rejection_reason": "fallback impossibile: no link bando, no link fonte",
            "stato_bando": None,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": False,
            "_fallback_used": True,
            "_fallback_failed": True,
        }

    # Firecrawl della FONTE
    from .enricher import _firecrawl_scrape_markdown
    fonte_markdown = ""
    try:
        fonte_markdown = await _firecrawl_scrape_markdown(fonte_link)
    except Exception as e:
        logger.debug("[resolver/{}] Firecrawl fonte fail: {}", bando_id, e)

    if not fonte_markdown or len(fonte_markdown) < 200:
        logger.warning(
            "[resolver/{}] Firecrawl fonte vuoto ({} char), fallback fallito",
            bando_id, len(fonte_markdown),
        )
        return {
            "is_valid_bando": False,
            "confidence_score": 0.0,
            "rejection_reason": "fallback fallito: Firecrawl fonte vuoto/non raggiungibile",
            "stato_bando": None,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": False,
            "_fallback_used": True,
            "_fallback_failed": True,
        }

    # Sonnet 4.6 call
    settings = get_settings()
    client = _get_anthropic_client()
    user_prompt = _build_resolver_prompt(bando, fonte_ctx, fonte_markdown)

    try:
        response = await _call_anthropic_resolver(
            client,
            model=settings.resolver_model,
            max_tokens=settings.resolver_max_tokens,
            system=RESOLVER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception as e:
        logger.exception("[resolver/{}] Sonnet call fallita: {}", bando_id, e)
        return {
            "is_valid_bando": False,
            "confidence_score": 0.0,
            "rejection_reason": f"fallback fallito: Sonnet API error",
            "stato_bando": None,
            "data_pubblicazione": None,
            "data_apertura": None,
            "data_scadenza": None,
            "_needs_fallback": False,
            "_fallback_used": True,
            "_fallback_failed": True,
        }

    raw_analysis = _extract_tool_input(response)
    result = _validate_resolver_output(raw_analysis, fonte_markdown, bando_id)

    logger.debug(
        "[resolver/{}] valid={} conf={:.2f} stato={} dates: pub={} apt={} scad={}",
        bando_id,
        result["is_valid_bando"],
        result["confidence_score"],
        result["stato_bando"],
        result.get("data_pubblicazione"),
        result.get("data_apertura"),
        result.get("data_scadenza"),
    )
    return result
