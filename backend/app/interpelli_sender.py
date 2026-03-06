"""
Scheduler per la pipeline interpelli.
Esegue la pipeline 4 volte al giorno (ogni 6 ore): 00:00, 06:00, 12:00, 18:00.

Uso: python -m app.interpelli_sender (dalla cartella backend/)
"""

import time
import schedule
from datetime import datetime

from .interpelli import run_interpelli_pipeline


def schedule_interpelli_pipeline():
    """Schedula la pipeline interpelli 4 volte al giorno."""
    for hour in ("00:00", "06:00", "12:00", "18:00"):
        schedule.every().day.at(hour).do(run_interpelli_pipeline)

    print(f"[{datetime.now()}] Pipeline interpelli schedulata: 00:00, 06:00, 12:00, 18:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    try:
        print(f"[{datetime.now()}] Avvio immediato della pipeline...")
        run_interpelli_pipeline()
        print(f"[{datetime.now()}] Avvio scheduler...")
        schedule_interpelli_pipeline()
    except KeyboardInterrupt:
        print("\nShutdown scheduler interpelli.")
    except Exception as e:
        print(f"Errore: {e}")
