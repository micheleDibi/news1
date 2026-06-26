"""
CLI entry-point per lo scraper bandi OpenCoesione.

Comandi disponibili:
  run              Esegue lo scraping completo su tutte le fonti attive.
  run-fonte        Esegue lo scraping su una singola fonte (per id).
  run-pending      Riesegue solo le fonti in stato pending la cui retry è scaduta.

Esempio di utilizzo:
  python -m app.cli run
  python -m app.cli run --limit 10
  python -m app.cli run-fonte --fonte-id 42
  python -m app.cli run-pending
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from app.config.settings import settings
from app.services.bando_discovery_service import BandoDiscoveryService


def _setup_logging() -> None:
    level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Mantiene visibile solo il progress per-fonte durante la scan.
    logging.getLogger("app.services.bando_discovery_service").setLevel(logging.INFO)


def _print_result(result: dict) -> None:
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


def cmd_run(args: argparse.Namespace) -> int:
    limit = args.limit if args.limit and args.limit > 0 else None
    service = BandoDiscoveryService()
    result = service.run(limit=limit)
    _print_result(result)
    return 0


def cmd_run_fonte(args: argparse.Namespace) -> int:
    service = BandoDiscoveryService()
    result = service.run_single_fonte(fonte_id=args.fonte_id)
    _print_result(result)
    return 0


def cmd_run_pending(args: argparse.Namespace) -> int:  # noqa: ARG001
    service = BandoDiscoveryService()
    result = service.run_pending_queue()
    _print_result(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper-bandi",
        description="Scraper gerarchico bandi OpenCoesione",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---- run ----
    run_parser = subparsers.add_parser("run", help="Esegue lo scraping completo")
    run_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di fonti da processare (default: tutte)",
    )
    run_parser.set_defaults(func=cmd_run)

    # ---- run-fonte ----
    fonte_parser = subparsers.add_parser("run-fonte", help="Esegue lo scraping su una singola fonte")
    fonte_parser.add_argument(
        "--fonte-id",
        type=int,
        required=True,
        dest="fonte_id",
        help="ID della fonte da processare",
    )
    fonte_parser.set_defaults(func=cmd_run_fonte)

    # ---- run-pending ----
    pending_parser = subparsers.add_parser("run-pending", help="Riesegue le fonti in stato pending")
    pending_parser.set_defaults(func=cmd_run_pending)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        logging.exception("Errore non gestito durante l'esecuzione del comando: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
