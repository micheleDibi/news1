"""Scheduler per la pipeline bandi.

Schedula:
  - 00:00, 06:00, 12:00, 18:00 -> pipeline FULL (scraper completo + skill enrichment)
  -                ogni 4 ore  -> pipeline PENDING (retry scraper + skill enrichment)
  -                ogni 30 min -> SOLO skill enrichment (backfill storico)

Uso: `python -m app.bandi_sender` (dalla cartella backend/, con `.env` caricato
nel processo — di solito via `env` di systemd o `python-dotenv` in `__main__`).

Pattern identico a `interpelli_sender.py` e `selezione_personale_sender.py`.
"""
from __future__ import annotations

import time

import schedule

from .bandi import (
    run_full_pipeline,
    run_pending_pipeline,
    run_skill_only_pipeline,
)
from .logger import logger


_HOURS_FULL = ("00:00", "06:00", "12:00", "18:00")


def schedule_bandi_pipeline() -> None:
    for hour in _HOURS_FULL:
        schedule.every().day.at(hour).do(run_full_pipeline)
    # Retry intermedio (subprocess pending dello scraper + skill batch)
    # ogni 4 ore, sfasato di 2h rispetto ai full per non sovrapporli.
    schedule.every(4).hours.do(run_pending_pipeline)
    # Backfill storico: solo la skill, ogni 30 minuti, batch piccolo.
    schedule.every(30).minutes.do(run_skill_only_pipeline)

    logger.info(
        "Pipeline bandi schedulata: full {}, pending ogni 4h, skill-only ogni 30 min",
        ", ".join(_HOURS_FULL),
    )

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("Avvio immediato della pipeline bandi...")
        run_full_pipeline()
        logger.info("Avvio scheduler bandi...")
        schedule_bandi_pipeline()
    except KeyboardInterrupt:
        logger.info("Shutdown scheduler bandi.")
    except Exception as e:
        logger.error("Errore scheduler bandi: {}", e)
