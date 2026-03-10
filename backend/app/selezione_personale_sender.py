"""
Scheduler per la pipeline selezione personale.
Esegue la pipeline 4 volte al giorno (ogni 6 ore): 00:00, 06:00, 12:00, 18:00.

Uso: python -m app.selezione_personale_sender (dalla cartella backend/)
"""

import time
import schedule

from .selezione_personale import run_selezione_personale_pipeline
from .logger import logger


def schedule_selezione_personale_pipeline():
    """Schedula la pipeline selezione personale 4 volte al giorno."""
    for hour in ("00:00", "06:00", "12:00", "18:00"):
        schedule.every().day.at(hour).do(run_selezione_personale_pipeline)

    logger.info("Pipeline selezione personale schedulata: 00:00, 06:00, 12:00, 18:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        logger.info("Avvio immediato della pipeline...")
        run_selezione_personale_pipeline()
        logger.info("Avvio scheduler...")
        schedule_selezione_personale_pipeline()
    except KeyboardInterrupt:
        logger.info("Shutdown scheduler selezione personale.")
    except Exception as e:
        logger.error("Errore: {}", e)
