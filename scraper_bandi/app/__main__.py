"""CLI entry-point: `python -m app <comando>`.

Comandi:
  discover    Esegue il discover delle fonti dalla pagina OpenCoesione e
              popola la tabella `fonte` su Supabase DB B.
"""
from __future__ import annotations

import asyncio
import sys

from .logger import logger


def _cmd_discover() -> None:
    from .orchestrator import run
    counters = asyncio.run(run())
    logger.info("[main] counters finali: {}", counters)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print("Usage: python -m app <comando>\n  comandi: discover", file=sys.stderr)
        return 2

    cmd = args[0]
    if cmd == "discover":
        try:
            _cmd_discover()
        except Exception:
            logger.exception("[main] errore fatale durante {}", cmd)
            return 1
        return 0

    print(f"Comando sconosciuto: {cmd}", file=sys.stderr)
    print("Comandi disponibili: discover", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
