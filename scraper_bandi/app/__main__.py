"""CLI entry-point: `python -m app <comando>`.

Comandi:
  discover       Step 1 — Estrae le fonti dalla pagina OpenCoesione e popola
                 la tabella `fonte` su Supabase DB B.
  scrape-bandi   Step 2 — Per ogni fonte ready+attivo, esegue scraping della
                 pagina + popola la tabella `bando`.
"""
from __future__ import annotations

import asyncio
import sys

from .logger import logger


def _cmd_discover() -> None:
    from .orchestrator import run
    counters = asyncio.run(run())
    logger.info("[main] counters finali: {}", counters)


def _cmd_scrape_bandi() -> None:
    from .bando_runner import run
    counters = asyncio.run(run())
    logger.info("[main] counters finali: {}", counters)


_COMMANDS: dict[str, callable] = {
    "discover": _cmd_discover,
    "scrape-bandi": _cmd_scrape_bandi,
}


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print(
            "Usage: python -m app <comando>\n"
            "  comandi: " + ", ".join(_COMMANDS.keys()),
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"Comando sconosciuto: {cmd}", file=sys.stderr)
        print("Comandi disponibili: " + ", ".join(_COMMANDS.keys()), file=sys.stderr)
        return 2

    try:
        fn()
    except Exception:
        logger.exception("[main] errore fatale durante {}", cmd)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
