"""Orchestratore step 2: scraping bandi da tutte le fonti `ready` + `attivo`.

Flusso:
  1. SELECT fonti ready+attivo dal DB (sequenziale).
  2. Per ogni fonte: lookup in SCRAPER_CONFIG -> strategy + params.
  3. Istanzia il scraper (factory get_scraper) + invoca scrape(fonte).
  4. Compose record con hash_bando (SHA256 fonte_id|link o fonte_id|titolo_norm).
  5. UPSERT in batch in `bando` (on_conflict=hash_bando).
  6. Counters cumulativi loggati.

Throttle: gestito a livello http.py (delay 1s tra request stesso host).
Concorrenza: sequenziale per fonte (1 alla volta).
"""
from __future__ import annotations

import time
from typing import Any

from .db import select_fonti_ready, upsert_bandi
from .logger import logger
from .normalize import hash_bando, is_valid_http_url, normalize_titolo
from .scraper_config import SCRAPER_CONFIG
from .scrapers import BandoItem, get_scraper


def _build_record(item: BandoItem) -> dict[str, Any]:
    """Compone il dict DB-ready per un BandoItem. Calcola hash_bando."""
    if item.link_bando and is_valid_http_url(item.link_bando):
        h = hash_bando(item.fonte_id, item.link_bando)
    else:
        # Bando senza link: hash su titolo normalizzato
        t_norm = normalize_titolo(item.titolo_raw or "")
        if not t_norm:
            return {}  # skip: ne' link ne' titolo significativo
        h = hash_bando(item.fonte_id, t_norm)

    return {
        "fonte_id": item.fonte_id,
        "hash_bando": h,
        "tipo_link": item.tipo_link,
        "link_bando": item.link_bando,
        "titolo_raw": item.titolo_raw,
        "descrizione_raw": item.descrizione_raw,
        "raw_data": item.raw_data,
    }


async def run() -> dict[str, int]:
    """Esegue lo scraping completo. Ritorna counters per il log finale."""
    started = time.monotonic()
    logger.info("[bando_runner] === START scraping bandi ===")

    fonti = select_fonti_ready()
    logger.info("[bando_runner] processero' {} fonti ready+attivo", len(fonti))

    overall = {
        "fonti_totali": len(fonti),
        "fonti_processate": 0,
        "fonti_skipped_no_strategy": 0,
        "fonti_skipped_skip_strategy": 0,
        "fonti_errors": 0,
        "bandi_estratti": 0,
        "bandi_con_link": 0,
        "bandi_senza_link": 0,
        "bandi_upsert_processed": 0,
    }

    for idx, fonte in enumerate(fonti, start=1):
        url = fonte["link"]
        fonte_id = fonte["id"]
        cfg = SCRAPER_CONFIG.get(url)

        if not cfg:
            logger.warning(
                "[bando_runner] {}/{} fonte_id={} url={} -- NO CONFIG IN REGISTRY, skip",
                idx, len(fonti), fonte_id, url,
            )
            overall["fonti_skipped_no_strategy"] += 1
            continue

        strategy_name = cfg.get("strategy", "skip_no_bandi")
        params = {k: v for k, v in cfg.items() if k != "strategy"}

        if strategy_name == "skip_no_bandi":
            logger.info(
                "[bando_runner] {}/{} fonte_id={} url={} strategy=skip ({})",
                idx, len(fonti), fonte_id, url, params.get("reason", ""),
            )
            overall["fonti_skipped_skip_strategy"] += 1
            continue

        logger.info(
            "[bando_runner] {}/{} fonte_id={} strategy={} url={}",
            idx, len(fonti), fonte_id, strategy_name, url,
        )

        # Istanzia scraper
        try:
            scraper = get_scraper(strategy_name, **params)
        except Exception as e:
            logger.exception(
                "[bando_runner] fonte_id={} get_scraper fallito strategy={}: {}",
                fonte_id, strategy_name, e,
            )
            overall["fonti_errors"] += 1
            continue

        # Esegui scraping
        try:
            items = await scraper.scrape(fonte)
        except Exception as e:
            logger.exception(
                "[bando_runner] fonte_id={} scrape fallito: {}",
                fonte_id, e,
            )
            overall["fonti_errors"] += 1
            continue

        # Compose record + counters
        records: list[dict[str, Any]] = []
        n_con_link = 0
        n_senza_link = 0
        for it in items:
            rec = _build_record(it)
            if not rec:
                continue
            records.append(rec)
            if rec["link_bando"]:
                n_con_link += 1
            else:
                n_senza_link += 1

        if records:
            try:
                res = upsert_bandi(records)
                overall["bandi_upsert_processed"] += res["processed"]
            except Exception as e:
                logger.exception("[bando_runner] fonte_id={} upsert fallito: {}", fonte_id, e)
                overall["fonti_errors"] += 1
                continue

        overall["fonti_processate"] += 1
        overall["bandi_estratti"] += len(records)
        overall["bandi_con_link"] += n_con_link
        overall["bandi_senza_link"] += n_senza_link

        logger.info(
            "[bando_runner] fonte_id={} -> {} bandi ({} con link, {} senza link)",
            fonte_id, len(records), n_con_link, n_senza_link,
        )

    elapsed = time.monotonic() - started
    logger.info(
        "[bando_runner] === DONE in {:.1f}s | counters={} ===",
        elapsed, overall,
    )
    return overall
