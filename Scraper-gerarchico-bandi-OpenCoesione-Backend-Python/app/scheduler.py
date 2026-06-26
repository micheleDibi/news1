"""
Scheduler per l'esecuzione pianificata dello scraper bandi OpenCoesione.

Usa APScheduler con BlockingScheduler per i job cron.

Comandi:
  python -m app.scheduler start         # avvia lo scheduler (bloccante)
  python -m app.scheduler run-now       # esegue subito un ciclo completo e termina
  python -m app.scheduler run-pending-now  # esegue subito la coda pending e termina

Configurazione cron via variabili d'ambiente (opzionale):
  SCHEDULER_CRON_FULL      Espressione cron per run completo (default: "0 2 * * *")
  SCHEDULER_CRON_PENDING   Espressione cron per run-pending  (default: "0 */4 * * *")
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.cli import _setup_logging
from app.config.settings import settings
from app.services.bando_discovery_service import BandoDiscoveryService

logger = logging.getLogger(__name__)

# Valori di default per le espressioni cron
_DEFAULT_CRON_FULL = "0 2 * * *"      # ogni giorno alle 02:00
_DEFAULT_CRON_PENDING = "0 */4 * * *"  # ogni 4 ore


def _job_run_full() -> None:
    """Job schedulato: esegue il run completo."""
    logger.info("Scheduler: avvio run completo")
    try:
        service = BandoDiscoveryService()
        result = service.run()
        logger.info("Scheduler: run completo completato — %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scheduler: run completo fallito: %s", exc)


def _job_run_pending() -> None:
    """Job schedulato: esegue la coda pending."""
    logger.info("Scheduler: avvio run-pending")
    try:
        service = BandoDiscoveryService()
        result = service.run_pending_queue()
        logger.info("Scheduler: run-pending completato — %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scheduler: run-pending fallito: %s", exc)


def _parse_cron(expr: str) -> dict[str, Any]:
    """Converte un'espressione cron 5-campi in kwargs per CronTrigger."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Espressione cron non valida (attesi 5 campi): '{expr}'")
    minute, hour, day, month, day_of_week = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def build_scheduler(
    cron_full: str = _DEFAULT_CRON_FULL,
    cron_pending: str = _DEFAULT_CRON_PENDING,
) -> BlockingScheduler:
    """Costruisce e restituisce lo scheduler configurato (non ancora avviato)."""
    scheduler = BlockingScheduler()

    scheduler.add_job(
        _job_run_full,
        trigger=CronTrigger(**_parse_cron(cron_full)),
        id="run_full",
        name="Scraping completo",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _job_run_pending,
        trigger=CronTrigger(**_parse_cron(cron_pending)),
        id="run_pending",
        name="Retry coda pending",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler


def cmd_start(args: argparse.Namespace) -> int:  # noqa: ARG001
    cron_full = getattr(args, "cron_full", None) or _DEFAULT_CRON_FULL
    cron_pending = getattr(args, "cron_pending", None) or _DEFAULT_CRON_PENDING
    scheduler = build_scheduler(cron_full=cron_full, cron_pending=cron_pending)
    logger.info(
        "Scheduler avviato — run_full='%s'  run_pending='%s'",
        cron_full,
        cron_pending,
    )
    scheduler.start()
    return 0


def cmd_run_now(args: argparse.Namespace) -> int:  # noqa: ARG001
    _job_run_full()
    return 0


def cmd_run_pending_now(args: argparse.Namespace) -> int:  # noqa: ARG001
    _job_run_pending()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper-scheduler",
        description="Scheduler APScheduler per lo scraper bandi OpenCoesione",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---- start ----
    start_p = subparsers.add_parser("start", help="Avvia lo scheduler in modo bloccante")
    start_p.add_argument(
        "--cron-full",
        default=_DEFAULT_CRON_FULL,
        dest="cron_full",
        help=f"Espressione cron per run completo (default: '{_DEFAULT_CRON_FULL}')",
    )
    start_p.add_argument(
        "--cron-pending",
        default=_DEFAULT_CRON_PENDING,
        dest="cron_pending",
        help=f"Espressione cron per run-pending (default: '{_DEFAULT_CRON_PENDING}')",
    )
    start_p.set_defaults(func=cmd_start)

    # ---- run-now ----
    now_p = subparsers.add_parser("run-now", help="Esegue subito un ciclo completo e termina")
    now_p.set_defaults(func=cmd_run_now)

    # ---- run-pending-now ----
    pending_now_p = subparsers.add_parser("run-pending-now", help="Esegue subito la coda pending e termina")
    pending_now_p.set_defaults(func=cmd_run_pending_now)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler fermato")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Errore scheduler: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
