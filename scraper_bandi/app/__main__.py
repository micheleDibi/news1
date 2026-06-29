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
                 junction (beneficiari, ateco, regioni, settori) +
                 estrazione date (pubblicazione/apertura/scadenza con gate
                 substring + source autoritativo).
                 Stato finale: 'enriched'.
                 Opzioni: --dry-run, --limit N, --rerun-enriched
                 (--rerun-enriched include anche bandi gia' 'enriched').
  seo            Step v8 — Skill SEO Opus 4.7: per ogni bando 'enriched'
                 genera contenuto editoriale + meta (slug, titolo,
                 titolo_breve, descrizione_breve, contenuto, livello,
                 allegati, ente_erogatore, area_geografica, tematica,
                 importi, link_candidatura). Stato finale: 'completed'.
                 Opzioni: --dry-run, --limit N, --rerun-completed.
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
    include_enriched = "--rerun-enriched" in argv
    limit: int | None = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit richiede un intero (es. --limit 10)", file=sys.stderr)
            sys.exit(2)
    counters = asyncio.run(
        enrich_run(dry_run=dry_run, limit=limit, include_enriched=include_enriched)
    )
    logger.info("[main] counters finali: {}", counters)


def _cmd_seo(argv: list[str]) -> None:
    from .bando_seo_runner import run as seo_run
    dry_run = "--dry-run" in argv
    include_completed = "--rerun-completed" in argv
    limit: int | None = None
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit richiede un intero (es. --limit 10)", file=sys.stderr)
            sys.exit(2)
    counters = asyncio.run(
        seo_run(dry_run=dry_run, limit=limit, include_completed=include_completed)
    )
    logger.info("[main] counters finali: {}", counters)


_COMMANDS: dict[str, callable] = {
    "discover": _cmd_discover,
    "scrape-bandi": _cmd_scrape_bandi,
    "preprocess": None,  # gestito a parte per parsing argv
    "enrich": None,      # gestito a parte per parsing argv
    "seo": None,         # gestito a parte per parsing argv
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
        elif cmd == "seo":
            _cmd_seo(cmd_argv)
        else:
            _COMMANDS[cmd]()
    except Exception:
        logger.exception("[main] errore fatale durante {}", cmd)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
