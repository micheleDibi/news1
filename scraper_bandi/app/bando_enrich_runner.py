"""Orchestratore step v7: enrichment dei bandi.

Flusso a 2 fasi:
  PHASE A - REFINEMENT: per ogni bando con stato_bando=NULL, Firecrawl +
    LLM Haiku determinano lo stato. Se diventa 'chiuso' -> skip; altrimenti
    aggiunto agli enrich_targets.

  PHASE B - ENRICHMENT: per ogni bando aperto/in apertura, 7 LLM call
    PARALLELE (asyncio.gather) per estrarre FK + junction. Update DB:
    UPDATE bando SET FK + stato_processing='enriched' + DELETE/INSERT
    nelle 4 junction tables.

Concorrenza:
  - Phase A: Semaphore(ENRICH_CONCURRENCY_REFINE, default 3) per Firecrawl.
  - Phase B: Semaphore(ENRICH_CONCURRENCY, default 5) per bando — ogni
    bando spawnea 7 LLM call in parallelo (35 in-flight totali).

Idempotente: SELECT filtra 'processed' + (aperto/in_apertura/NULL).
I bandi gia' 'enriched' non rientrano. Re-run riparte dai pendenti.
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from .db import (
    enrich_fonti_with_names,
    load_catalogo,
    select_bandi_to_enrich,
    select_fonti_by_ids,
    update_bando_enriched,
    update_bando_refinement,
)
from .enricher import enrich_bando, refine_stato_bando
from .logger import logger
from .settings import get_settings


async def run(
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Esegue le 2 fasi di enrichment.

    Args:
        dry_run: se True, NON scrive il DB.
        limit: cap totale dei candidati (smoke test).
    """
    settings = get_settings()
    started = time.monotonic()
    logger.info(
        "[enrich] === START | model={} concurrency=({}, {}) dry_run={} ===",
        settings.enrich_model,
        settings.enrich_concurrency_refine,
        settings.enrich_concurrency,
        dry_run,
    )

    # 1. SELECT candidati
    bandi = select_bandi_to_enrich(limit=limit)
    if not bandi:
        logger.info("[enrich] nessun bando candidato all'enrichment")
        return {"refined_total": 0, "enriched_total": 0, "elapsed_s": 0}

    # 2. Pre-load fonti + nomi catalogo
    fonte_ids = list({b["fonte_id"] for b in bandi if b.get("fonte_id") is not None})
    fonti_by_id = select_fonti_by_ids(fonte_ids)
    fonti_by_id = enrich_fonti_with_names(fonti_by_id)
    logger.info("[enrich] preload: {} fonti uniche", len(fonti_by_id))

    # 3. Pre-load catalogo (load_catalogo e' @lru_cache singleton)
    catalogo = load_catalogo()
    logger.info(
        "[enrich] catalogo: tipologie={} programmi={} modalita={} "
        "beneficiari={} ateco={} regioni={} settori={}",
        len(catalogo.get("tipologie", [])),
        len(catalogo.get("programmi", [])),
        len(catalogo.get("modalita", [])),
        len(catalogo.get("beneficiari", [])),
        len(catalogo.get("codici_ateco", [])),
        len(catalogo.get("regioni", [])),
        len(catalogo.get("settori", [])),
    )

    # 4. Suddividi
    refine_targets = [b for b in bandi if b.get("stato_bando") is None]
    initial_enrich_targets = [
        b for b in bandi
        if b.get("stato_bando") in ("aperto", "in apertura prossimamente")
    ]
    logger.info(
        "[enrich] targets: {} refine (stato_bando=NULL), {} enrich (aperto/in_apertura)",
        len(refine_targets), len(initial_enrich_targets),
    )

    # ----------------------------------------------------------------------
    # PHASE A — Refinement (per bandi NULL)
    # ----------------------------------------------------------------------
    refined_counter = Counter()
    promoted_to_enrich: list[dict[str, Any]] = []

    if refine_targets:
        logger.info("[enrich] === PHASE A: refinement di {} bandi ===", len(refine_targets))
        sem_refine = asyncio.Semaphore(max(1, settings.enrich_concurrency_refine))

        async def _do_refine(b: dict[str, Any]) -> tuple[int, str, float, str]:
            bando_id = b["id"]
            fonte_ctx = fonti_by_id.get(b.get("fonte_id"), {})
            async with sem_refine:
                try:
                    stato, conf, reason = await refine_stato_bando(b, fonte_ctx)
                except Exception as e:
                    logger.exception("[enrich/refine] bando_id={} fallito: {}", bando_id, e)
                    return (bando_id, "aperto", 0.0, f"error: {e}")
                logger.debug(
                    "[enrich/refine] bando_id={} -> stato={} conf={:.2f} reason={!r}",
                    bando_id, stato, conf, reason,
                )
                if not dry_run:
                    await update_bando_refinement(bando_id, stato)
                return (bando_id, stato, conf, reason)

        refine_results = await asyncio.gather(*[_do_refine(b) for b in refine_targets])

        # Promuovi a Phase B i nuovi aperti/in_apertura
        refine_by_id = {bid: (stato, conf, reason) for bid, stato, conf, reason in refine_results}
        for b in refine_targets:
            stato, _conf, _reason = refine_by_id.get(b["id"], ("aperto", 0.0, ""))
            refined_counter[stato] += 1
            if stato in ("aperto", "in apertura prossimamente"):
                # Aggiorno il valore stato_bando locale prima di passare alla Phase B
                b = {**b, "stato_bando": stato}
                promoted_to_enrich.append(b)

        logger.info(
            "[enrich] PHASE A done: {} refinati ({} aperto, {} in_apertura, {} chiuso)",
            len(refine_targets),
            refined_counter.get("aperto", 0),
            refined_counter.get("in apertura prossimamente", 0),
            refined_counter.get("chiuso", 0),
        )

    # ----------------------------------------------------------------------
    # PHASE B — Enrichment FK + Junction
    # ----------------------------------------------------------------------
    enrich_targets = initial_enrich_targets + promoted_to_enrich
    enrich_counter = {
        "total": len(enrich_targets),
        "ok": 0,
        "db_failed": 0,
        "with_tipologia": 0,
        "with_modalita": 0,
        "with_programma": 0,
        "sum_beneficiari": 0,
        "sum_ateco": 0,
        "sum_regioni": 0,
        "sum_settori": 0,
    }

    if enrich_targets:
        logger.info("[enrich] === PHASE B: enrichment di {} bandi ===", len(enrich_targets))
        sem_enrich = asyncio.Semaphore(max(1, settings.enrich_concurrency))
        progress = {"done": 0}
        total = len(enrich_targets)

        async def _do_enrich(b: dict[str, Any]) -> tuple[int, dict | Exception]:
            bando_id = b["id"]
            fonte_ctx = fonti_by_id.get(b.get("fonte_id"), {})
            link = b.get("link_bando") or ""

            async with sem_enrich:
                # Carica HTML pagina (Firecrawl cached dalla PHASE A oppure
                # httpx fallback). Per i bandi senza link, html_text="".
                html_text = ""
                if link:
                    from .enricher import _firecrawl_scrape_markdown, _httpx_fetch_text
                    try:
                        html_text = await _firecrawl_scrape_markdown(link) if link else ""
                    except Exception:
                        html_text = await _httpx_fetch_text(link)

                try:
                    res = await enrich_bando(b, fonte_ctx, html_text, catalogo)
                except Exception as e:
                    logger.exception("[enrich] bando_id={} enrich_bando fallito: {}", bando_id, e)
                    progress["done"] += 1
                    return (bando_id, e)

                progress["done"] += 1
                if progress["done"] % 25 == 0 or progress["done"] == total:
                    logger.info("[enrich] progress {}/{}", progress["done"], total)
                return (bando_id, res)

        enrich_results = await asyncio.gather(*[_do_enrich(b) for b in enrich_targets])

        # Compose updates + write DB
        for bid, res in enrich_results:
            if isinstance(res, Exception):
                continue
            # Aggiorna counter
            if res["tipologia_bando_id"] is not None:
                enrich_counter["with_tipologia"] += 1
            if res["modalita_erogazione_id"] is not None:
                enrich_counter["with_modalita"] += 1
            if res["programma_id"] is not None:
                enrich_counter["with_programma"] += 1
            enrich_counter["sum_beneficiari"] += len(res["beneficiari_ids"])
            enrich_counter["sum_ateco"] += len(res["codici_ateco_ids"])
            enrich_counter["sum_regioni"] += len(res["regioni_ids"])
            enrich_counter["sum_settori"] += len(res["settori_ids"])

            if not dry_run:
                # Recupera stato_bando dal target (il "promoted" potrebbe avere
                # stato_bando aggiornato).
                bando_record = next((b for b in enrich_targets if b["id"] == bid), None)
                if not bando_record:
                    continue
                stato_bando = bando_record.get("stato_bando") or "aperto"
                ok = await update_bando_enriched(
                    bid,
                    stato_bando,
                    res["tipologia_bando_id"],
                    res["modalita_erogazione_id"],
                    res["programma_id"],
                    res["beneficiari_ids"],
                    res["codici_ateco_ids"],
                    res["regioni_ids"],
                    res["settori_ids"],
                )
                if ok:
                    enrich_counter["ok"] += 1
                else:
                    enrich_counter["db_failed"] += 1

    elapsed = time.monotonic() - started
    n_e = enrich_counter["total"] or 1
    counters: dict[str, Any] = {
        "refined_total": len(refine_targets),
        "refined_to_aperto": refined_counter.get("aperto", 0),
        "refined_to_in_apertura": refined_counter.get("in apertura prossimamente", 0),
        "refined_to_chiuso": refined_counter.get("chiuso", 0),
        "enriched_total": enrich_counter["total"],
        "enriched_db_ok": enrich_counter["ok"],
        "enriched_db_failed": enrich_counter["db_failed"],
        "with_tipologia": enrich_counter["with_tipologia"],
        "with_modalita": enrich_counter["with_modalita"],
        "with_programma": enrich_counter["with_programma"],
        "avg_beneficiari": round(enrich_counter["sum_beneficiari"] / n_e, 2),
        "avg_ateco": round(enrich_counter["sum_ateco"] / n_e, 2),
        "avg_regioni": round(enrich_counter["sum_regioni"] / n_e, 2),
        "avg_settori": round(enrich_counter["sum_settori"] / n_e, 2),
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("[enrich] === DONE | {} ===", counters)
    return counters
