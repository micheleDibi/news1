"""Orchestratore step intermedio: pre-processing bandi via LLM.

Flusso:
  1. SELECT WHERE stato_processing='scraped' (cap a batch_size)
  2. Pre-load fonti + lookup categoria/tipologia (cache LRU)
  3. asyncio.gather su tutti i bandi (Semaphore=PREPROCESS_CONCURRENCY)
  4. Compose updates: valid -> stato_processing='processed' + stato_bando;
     invalid -> stato_processing='rejected' + rejection_reason
  5. Batch UPDATE (chunk 100)
  6. Counters cumulativi loggati

Idempotente: ri-eseguendo, solo i record ancora 'scraped' vengono presi
(quelli gia' processed/rejected restano).
"""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from .bando_resolver import resolve_bando
from .db import (
    enrich_fonti_with_names,
    select_bandi_scraped,
    select_fonti_by_ids,
    update_bandi_postanalysis,
)
from .logger import logger
from .preprocessor import analyze_bando
from .settings import get_settings


def _build_update(bando_id: int, analysis: dict[str, Any]) -> dict[str, Any]:
    """Compose un record di UPDATE dal risultato dell'analisi.

    Include le 3 date estratte (data_pubblicazione, data_apertura, data_scadenza)
    se presenti — sono gia' state validate (triple-gate) + reconciled (data-driven
    forza stato_bando).
    """
    update: dict[str, Any] = {
        "id": bando_id,
        "confidence_score": float(analysis["confidence_score"]),
    }
    if analysis["is_valid_bando"]:
        update["stato_processing"] = "processed"
        # stato_bando puo' essere None (LLM='unknown' o reconciliation a None)
        st = analysis["stato_bando"]
        update["stato_bando"] = st if st in ("aperto", "chiuso", "in apertura prossimamente") else None
        update["rejection_reason"] = None
        # 3 date (None se non passate il triple-gate)
        update["data_pubblicazione"] = analysis.get("data_pubblicazione")
        update["data_apertura"] = analysis.get("data_apertura")
        update["data_scadenza"] = analysis.get("data_scadenza")
    else:
        update["stato_processing"] = "rejected"
        update["stato_bando"] = None
        update["rejection_reason"] = analysis.get("rejection_reason") or "non classificato come bando"
        update["data_pubblicazione"] = None
        update["data_apertura"] = None
        update["data_scadenza"] = None
    return update


async def run(
    batch_size: int | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Esegue il pre-processing su tutti i bandi 'scraped'.

    Args:
        batch_size: cap del SELECT iniziale. None = nessun cap (TUTTI i scraped).
        dry_run: se True, NON scrive il DB, ritorna solo i counter.
        limit: alternativo a batch_size per smoke test (es. limit=10).
    """
    settings = get_settings()
    started = time.monotonic()
    logger.info(
        "[preprocess] === START | model={} concurrency_llm={} concurrency_firecrawl={} "
        "resolver_model={} dry_run={} ===",
        settings.preprocess_model,
        settings.preprocess_concurrency,
        settings.preprocess_firecrawl_concurrency,
        settings.resolver_model,
        dry_run,
    )

    # Se non viene passato ne' limit ne' batch_size, processa TUTTI i scraped.
    select_limit = limit if limit is not None else batch_size
    rows = select_bandi_scraped(limit=select_limit)
    if not rows:
        logger.info("[preprocess] nessun bando in stato 'scraped': nulla da fare")
        return {
            "processed_total": 0, "valid": 0, "rejected": 0,
            "errors": 0, "elapsed_s": 0,
        }

    # Pre-load fonti + arricchimento nomi categoria/tipologia
    fonte_ids = list({r["fonte_id"] for r in rows if r.get("fonte_id") is not None})
    fonti_by_id = select_fonti_by_ids(fonte_ids)
    fonti_by_id = enrich_fonti_with_names(fonti_by_id)
    logger.info("[preprocess] preload: {} fonti uniche", len(fonti_by_id))

    # Concorrenza split: Firecrawl (rate-limit) e LLM (rate-limit Anthropic) sono
    # bottleneck distinti. La Firecrawl call sta DENTRO analyze_bando, quindi un
    # singolo semaforo intorno a _analyze_one limita entrambi. Tieni il piu'
    # restrittivo dei due: Firecrawl di solito ~5.
    effective_concurrency = min(
        settings.preprocess_concurrency,
        settings.preprocess_firecrawl_concurrency,
    )
    logger.info(
        "[preprocess] effective concurrency (min of LLM/Firecrawl) = {}",
        effective_concurrency,
    )

    sem = asyncio.Semaphore(effective_concurrency)
    progress = {"done": 0}
    total = len(rows)

    async def _analyze_one(bando: dict[str, Any]) -> tuple[int, dict[str, Any] | Exception]:
        async with sem:
            bando_id = bando["id"]
            fonte_ctx = fonti_by_id.get(bando.get("fonte_id"), {})
            try:
                # Primary: preprocess con markdown link_bando
                analysis = await analyze_bando(bando, fonte_ctx)
                # Trigger fallback se markdown bando vuoto
                if analysis.get("_needs_fallback"):
                    logger.info(
                        "[preprocess/{}] -> fallback bando_resolver (Sonnet+Firecrawl fonte)",
                        bando_id,
                    )
                    analysis = await resolve_bando(bando, fonte_ctx)
                progress["done"] += 1
                if progress["done"] % 50 == 0 or progress["done"] == total:
                    logger.info("[preprocess] progress {}/{}", progress["done"], total)
                return bando_id, analysis
            except Exception as e:
                progress["done"] += 1
                logger.exception("[preprocess] bando_id={} fallito: {}", bando_id, e)
                return bando_id, e

    results = await asyncio.gather(*[_analyze_one(b) for b in rows])

    # Compose updates
    valid_updates: list[dict[str, Any]] = []
    rejected_updates: list[dict[str, Any]] = []
    errors = 0
    stato_bando_dist: Counter[str | None] = Counter()
    confidence_sum = 0.0
    confidence_n = 0
    fallback_used = 0
    fallback_failed = 0
    with_pub = 0
    with_apt = 0
    with_scad = 0

    for bid, res in results:
        if isinstance(res, Exception):
            errors += 1
            continue
        analysis = res
        update = _build_update(bid, analysis)
        confidence_sum += update["confidence_score"]
        confidence_n += 1
        if analysis.get("_fallback_used"):
            fallback_used += 1
            if analysis.get("_fallback_failed"):
                fallback_failed += 1
        if update["stato_processing"] == "processed":
            valid_updates.append(update)
            stato_bando_dist[update.get("stato_bando")] += 1
            if update.get("data_pubblicazione"):
                with_pub += 1
            if update.get("data_apertura"):
                with_apt += 1
            if update.get("data_scadenza"):
                with_scad += 1
        else:
            rejected_updates.append(update)

    # UPDATE DB (async: UPDATE per id con concorrenza interna)
    n_updated = 0
    n_failed = 0
    if not dry_run:
        all_updates = valid_updates + rejected_updates
        res_upd = await update_bandi_postanalysis(all_updates)
        n_updated = res_upd.get("updated", 0)
        n_failed = res_upd.get("failed", 0)

    avg_conf = confidence_sum / confidence_n if confidence_n else 0.0
    elapsed = time.monotonic() - started

    counters: dict[str, Any] = {
        "processed_total": total,
        "valid": len(valid_updates),
        "rejected": len(rejected_updates),
        "errors": errors,
        "by_stato_bando": dict(stato_bando_dist),
        "avg_confidence": round(avg_conf, 3),
        "with_data_pubblicazione": with_pub,
        "with_data_apertura": with_apt,
        "with_data_scadenza": with_scad,
        "fallback_used": fallback_used,
        "fallback_failed": fallback_failed,
        "db_updated": n_updated,
        "db_failed": n_failed,
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("[preprocess] === DONE | {} ===", counters)
    return counters
