"""Scheduler della pipeline scraping bandi: 4 esecuzioni/giorno.

Esecuzioni programmate: 00:00, 06:00, 12:00, 18:00 (ora locale del processo).

Il giro e' **esplicito** (§16.2 M13): ogni schedulazione passa la propria ora a
`run_bandi_pipeline(giro=...)`, cosi' gli step che girano solo in alcuni giri
(il monitor, secondo `MONITOR_GIRI`) sanno in quale si trovano. Senza il
parametro dovrebbero indovinarlo dall'orologio, che al minuto 59 del giro
precedente da' la risposta sbagliata.

L'esecuzione immediata al boot passa `giro="boot"`, che non e' un'ora dello
scheduler: un riavvio esegue gli step di sempre ma non il monitor, che ha le
sue finestre (`MONITOR_GIRI`) e il suo costo in crediti.

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

from .bandi_pipeline import GIRI_SCHEDULER, run_bandi_pipeline
from .logger import logger

# Giro dell'esecuzione immediata al boot. NON e' una delle ore dello scheduler,
# quindi gli step legati a `MONITOR_GIRI` (il monitor) restano fuori: un riavvio
# — deploy, crash-restart, systemd — non deve far partire lo step piu' caro in
# crediti fuori dalle sue finestre. `giro=None` vale «sempre» per la CLI
# lanciata a mano, ma un avvio automatico non e' una CLI.
GIRO_BOOT = "boot"


def _run_sync(giro: str | None = None) -> None:
    """Wrapper sync per asyncio.run (necessario per schedule library)."""
    try:
        asyncio.run(run_bandi_pipeline(giro=giro))
    except Exception as e:
        logger.exception("[bandi_sender] Errore non gestito durante run: {}", e)


def schedule_bandi_pipeline() -> None:
    """Schedula 4 esecuzioni/giorno e loop infinito."""
    # Le ore sono una costante condivisa con `settings.GIRI_SCHEDULER`, che le
    # usa per validare `MONITOR_GIRI`: ripeterle qui farebbe nascere due elenchi
    # e un monitor configurato su un'ora inesistente.
    for hour in GIRI_SCHEDULER:
        schedule.every().day.at(hour).do(_run_sync, giro=hour)
    logger.info(
        "[bandi_sender] Pipeline schedulata: {} ({}x/day)",
        ", ".join(GIRI_SCHEDULER), len(GIRI_SCHEDULER),
    )
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("[bandi_sender] Avvio immediato della pipeline (giro={})...", GIRO_BOOT)
        _run_sync(giro=GIRO_BOOT)
        logger.info("[bandi_sender] Pipeline iniziale completata. Avvio scheduler...")
        schedule_bandi_pipeline()
    except KeyboardInterrupt:
        logger.info("[bandi_sender] Shutdown richiesto da utente.")
    except Exception as e:
        logger.exception("[bandi_sender] Errore fatale: {}", e)
