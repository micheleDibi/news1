"""
Scheduler per la pipeline interpelli.
Esegue la pipeline 4 volte al giorno (ogni 6 ore): 00:00, 06:00, 12:00, 18:00.

Uso: python -m app.interpelli_sender (dalla cartella backend/)
"""

import time
import schedule

from .interpelli import run_interpelli_pipeline
from .logger import logger


def schedule_interpelli_pipeline():
    """Schedula la pipeline interpelli 4 volte al giorno."""
    for hour in ("00:00", "06:00", "12:00", "18:00"):
        schedule.every().day.at(hour).do(run_interpelli_pipeline)

    logger.info("Pipeline interpelli schedulata: 00:00, 06:00, 12:00, 18:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("Avvio immediato della pipeline...")
        run_interpelli_pipeline()
        logger.info("Avvio scheduler...")
        schedule_interpelli_pipeline()
    except KeyboardInterrupt:
        logger.info("Shutdown scheduler interpelli.")
    except Exception as e:
        logger.error("Errore: {}", e)
