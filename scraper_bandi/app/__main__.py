"""CLI entry-point: `python -m app <comando> [opzioni]`.

Comandi:
  discover       Step 1 — Estrae le fonti dalla pagina OpenCoesione e popola
                 la tabella `fonte` su Supabase DB B.
  scrape-bandi   Step 2 — Per ogni fonte ready+attivo, esegue scraping della
                 pagina + popola la tabella `bando`.
  preprocess     Step intermedio — Per ogni bando in stato 'scraped',
                 analizza con Claude Haiku 4.5: valida + stato_bando +
                 confidence_score. Opzioni:
                   --dry-run    Non scrive il DB, solo log dei risultati.
                   --limit N    Processa solo i primi N (smoke test).
  enrich         Step v7 — Per ogni bando 'processed' con stato_bando
                 aperto/in_apertura/NULL: refinement stato (se NULL) +
                 estrazione FK (tipologia, modalita, programma) +
                 junction (beneficiari, ateco, regioni, settori).
                 Stato finale: 'enriched'. Opzioni: --dry-run, --limit N.
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


def _cmd_preprocess(argv: list[str]) -> None:
    from .bando_preprocess_runner import run as preprocess_run
    dry_run = "--dry-run" in argv
    limit: int | None = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit richiede un intero (es. --limit 10)", file=sys.stderr)
            sys.exit(2)
    counters = asyncio.run(preprocess_run(dry_run=dry_run, limit=limit))
    logger.info("[main] counters finali: {}", counters)


def _cmd_enrich(argv: list[str]) -> None:
    from .bando_enrich_runner import run as enrich_run
    dry_run = "--dry-run" in argv
    limit: int | None = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit richiede un intero (es. --limit 10)", file=sys.stderr)
            sys.exit(2)
    counters = asyncio.run(enrich_run(dry_run=dry_run, limit=limit))
    logger.info("[main] counters finali: {}", counters)


_COMMANDS: dict[str, callable] = {
    "discover": _cmd_discover,
    "scrape-bandi": _cmd_scrape_bandi,
    "preprocess": None,  # gestito a parte per parsing argv
    "enrich": None,      # gestito a parte per parsing argv
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
    cmd_argv = args[1:]

    if cmd not in _COMMANDS:
        print(f"Comando sconosciuto: {cmd}", file=sys.stderr)
        print("Comandi disponibili: " + ", ".join(_COMMANDS.keys()), file=sys.stderr)
        return 2

    try:
        if cmd == "preprocess":
            _cmd_preprocess(cmd_argv)
        elif cmd == "enrich":
            _cmd_enrich(cmd_argv)
        else:
            _COMMANDS[cmd]()
    except Exception:
        logger.exception("[main] errore fatale durante {}", cmd)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
