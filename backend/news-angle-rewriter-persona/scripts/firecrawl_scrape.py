#!/usr/bin/env python3
"""Helper CLI per usare Firecrawl dall'interno della skill news-angle-rewriter.

La SKILL.md indica "firecrawl scrape URL" come tool prioritario ma quel
comando shell non esiste: Firecrawl e' solo una libreria Python/REST.
Questo script sopperisce permettendo all'agente di invocare Firecrawl
via Bash tool:

    python scripts/firecrawl_scrape.py <url> [--format markdown|html]

Stampa su stdout il contenuto estratto nel formato richiesto (default
markdown). La variabile d'ambiente FIRECRAWL_API_KEY deve essere
presente (ereditata dal .env del backend).
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    from firecrawl import Firecrawl  # firecrawl-py (gia' in backend/requirements.txt)
except ImportError as e:
    print(f"firecrawl-py non installato: {e}", file=sys.stderr)
    print("Esegui: pip install firecrawl-py", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape di una URL via Firecrawl (output su stdout).")
    parser.add_argument("url", help="URL da scrapare")
    parser.add_argument(
        "--format",
        choices=["markdown", "html"],
        default="markdown",
        help="Formato di output (default: markdown)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="Se >0, tronca l'output ai primi N caratteri (utile per prompt lunghi)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        print("FIRECRAWL_API_KEY non impostata nell'ambiente", file=sys.stderr)
        return 1

    try:
        fc = Firecrawl(api_key=api_key)
        result = fc.scrape(args.url, formats=[args.format])
    except Exception as e:
        print(f"Firecrawl scrape fallita: {e}", file=sys.stderr)
        return 1

    content = getattr(result, args.format, None) or ""
    if args.max_chars and len(content) > args.max_chars:
        content = content[: args.max_chars] + "\n\n[...troncato...]"

    sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
