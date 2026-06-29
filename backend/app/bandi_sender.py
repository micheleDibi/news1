"""Scheduler della pipeline scraping bandi: 4 esecuzioni/giorno.

Esecuzioni programmate: 00:00, 06:00, 12:00, 18:00 (ora locale del processo).

Pattern identico a interpelli_sender.py e selezione_personale_sender.py:
  1. Run immediato al boot del processo
  2. Loop infinito con schedule.run_pending() ogni 60s
  3. Solo log file (no Telegram/email per scelta utente — vedi plan v9)

Avvio in foreground:
    python -m backend.app.bandi_sender

Avvio in background con persistenza log:
    nohup python -m backend.app.bandi_sender > /dev/null 2>&1 &
    # I log finiscono in logs/backend-YYYY-MM-DD.log (loguru daily-rotated)

Avvio come systemd service (produzione):
    Vedi esempio commentato in scraper_bandi/README.md
"""
from __future__ import annotations

import asyncio
import time

import schedule

from .bandi_pipeline import run_bandi_pipeline
from .logger import logger


def _run_sync() -> None:
    """Wrapper sync per asyncio.run (necessario per schedule library)."""
    try:
        asyncio.run(run_bandi_pipeline())
    except Exception as e:
        logger.exception("[bandi_sender] Errore non gestito durante run: {}", e)


def schedule_bandi_pipeline() -> None:
    """Schedula 4 esecuzioni/giorno e loop infinito."""
    for hour in ("00:00", "06:00", "12:00", "18:00"):
        schedule.every().day.at(hour).do(_run_sync)
    logger.info(
        "[bandi_sender] Pipeline schedulata: 00:00, 06:00, 12:00, 18:00 (4x/day)",
    )
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("[bandi_sender] Avvio immediato della pipeline...")
        _run_sync()
        logger.info("[bandi_sender] Pipeline iniziale completata. Avvio scheduler...")
        schedule_bandi_pipeline()
    except KeyboardInterrupt:
        logger.info("[bandi_sender] Shutdown richiesto da utente.")
    except Exception as e:
        logger.exception("[bandi_sender] Errore fatale: {}", e)
