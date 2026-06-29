"""Orchestratore step v8: skill SEO (enriched -> completed).

Per ogni bando con stato_processing='enriched':
  1. SELECT row + lookup catalogo FK/junction -> nomi
  2. Firecrawl markdown (cache LRU)
  3. enrich_seo() -> payload validato (slug, titolo, contenuto, ecc.)
  4. update_bando_completed() -> 14 campi + stato_processing='completed'

Concorrenza: Semaphore(SEO_CONCURRENCY=3) per Opus rate-limit.
Idempotente: re-run salta i gia' 'completed' (default). Opt-in
--rerun-completed include anche i completati.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .db import (
    build_bando_input_context,
    load_catalogo,
    select_bandi_to_complete,
    update_bando_completed,
)
from .enricher import _firecrawl_scrape_markdown, _httpx_fetch_text
from .logger import logger
from .seo_skill import enrich_seo
from .settings import get_settings


async def run(
    dry_run: bool = False,
    limit: int | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Esegue la skill SEO su tutti i bandi 'enriched'.

    Args:
        dry_run: se True, NON scrive il DB.
        limit: cap totale candidati (smoke test).
        include_completed: se True, include anche 'completed' (re-run).
    """
    settings = get_settings()
    started = time.monotonic()
    logger.info(
        "[seo] === START | model={} concurrency={} dry_run={} include_completed={} ===",
        settings.seo_model,
        settings.seo_concurrency,
        dry_run,
        include_completed,
    )

    # 1. SELECT candidati
    bandi = select_bandi_to_complete(limit=limit, include_completed=include_completed)
    if not bandi:
        logger.info("[seo] nessun bando candidato")
        return {"selected": 0, "elapsed_s": 0}

    # 2. Pre-load catalogo (lru_cache singleton)
    catalogo = load_catalogo()
    logger.info(
        "[seo] catalogo: tipologie={} programmi={} modalita={} "
        "beneficiari={} ateco={} regioni={} settori={}",
        len(catalogo.get("tipologie", [])),
        len(catalogo.get("programmi", [])),
        len(catalogo.get("modalita", [])),
        len(catalogo.get("beneficiari", [])),
        len(catalogo.get("codici_ateco", [])),
        len(catalogo.get("regioni", [])),
        len(catalogo.get("settori", [])),
    )

    # 3. Loop con Semaphore
    sem = asyncio.Semaphore(max(1, settings.seo_concurrency))
    progress = {"done": 0}
    total = len(bandi)

    async def _do_one(b: dict[str, Any]) -> tuple[int, dict[str, Any] | None, bool]:
        """Ritorna (bando_id, payload_validato_o_None, db_ok)."""
        bando_id = b["id"]
        async with sem:
            try:
                input_ctx = build_bando_input_context(b, catalogo)
            except Exception as e:
                logger.exception("[seo] bando_id={} build_input_context fallito: {}", bando_id, e)
                progress["done"] += 1
                return (bando_id, None, False)

            # Markdown via Firecrawl (cached), fallback httpx
            link = b.get("link_bando") or ""
            markdown = ""
            if link:
                try:
                    markdown = await _firecrawl_scrape_markdown(link)
                except Exception:
                    markdown = ""
                if not markdown:
                    try:
                        markdown = await _httpx_fetch_text(link)
                    except Exception:
                        markdown = ""

            # Skill LLM call + validation
            try:
                payload = await enrich_seo(input_ctx, markdown)
            except Exception as e:
                logger.exception("[seo] bando_id={} enrich_seo fallito: {}", bando_id, e)
                payload = None

            db_ok = False
            if payload and not dry_run:
                try:
                    db_ok = await update_bando_completed(bando_id, payload)
                except Exception as e:
                    logger.exception("[seo] bando_id={} update_bando_completed fallito: {}", bando_id, e)
                    db_ok = False
            elif payload and dry_run:
                db_ok = True  # consideriamo OK in dry-run

            progress["done"] += 1
            if progress["done"] % 25 == 0 or progress["done"] == total:
                logger.info("[seo] progress {}/{}", progress["done"], total)
            return (bando_id, payload, db_ok)

    results = await asyncio.gather(*[_do_one(b) for b in bandi])

    # 4. Counters
    selected = len(bandi)
    payloads_ok = [p for _, p, _ in results if p is not None]
    completed_db_ok = sum(1 for _, _, ok in results if ok)
    payload_failed = sum(1 for _, p, _ in results if p is None)
    payload_ok_db_failed = sum(1 for _, p, ok in results if p is not None and not ok)

    livello_flash = sum(1 for p in payloads_ok if p.get("livello") == "flash_bando")
    livello_guida = sum(1 for p in payloads_ok if p.get("livello") == "guida_bando")
    with_link_candidatura = sum(1 for p in payloads_ok if p.get("link_candidatura"))
    with_importo_totale = sum(1 for p in payloads_ok if p.get("importo_totale_eur") is not None)
    with_importo_max = sum(1 for p in payloads_ok if p.get("importo_max_per_progetto_eur") is not None)
    sum_allegati = sum(len(p.get("allegati") or []) for p in payloads_ok)
    sum_tematica = sum(len(p.get("tematica") or []) for p in payloads_ok)

    n_p = len(payloads_ok) or 1
    elapsed = time.monotonic() - started
    counters: dict[str, Any] = {
        "selected": selected,
        "payload_ok": len(payloads_ok),
        "payload_failed": payload_failed,
        "completed_db_ok": completed_db_ok,
        "payload_ok_db_failed": payload_ok_db_failed,
        "livello_flash": livello_flash,
        "livello_guida": livello_guida,
        "with_link_candidatura": with_link_candidatura,
        "with_importo_totale": with_importo_totale,
        "with_importo_max": with_importo_max,
        "avg_allegati": round(sum_allegati / n_p, 2),
        "avg_tematica": round(sum_tematica / n_p, 2),
        "dry_run": dry_run,
        "elapsed_s": round(elapsed, 1),
    }
    logger.info("[seo] === DONE | {} ===", counters)
    return counters
