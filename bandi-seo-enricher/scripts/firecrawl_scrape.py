"""Helper Firecrawl con fallback. Stampa il contenuto scrapato su stdout (markdown o html).

Uso CLI:
    python scripts/firecrawl_scrape.py "https://..." --format markdown --max-chars 20000
    python scripts/firecrawl_scrape.py "https://..." --format html --max-chars 20000
    python scripts/firecrawl_scrape.py "https://..." --check-only          # exit 0 se la pagina e' raggiungibile e non vuota

Variabile d'ambiente richiesta:
    FIRECRAWL_API_KEY

Exit code:
    0 = scrape ok (o pagina raggiungibile in --check-only)
    1 = scrape vuoto o pagina non utile
    2 = errore di rete / API
    3 = configurazione mancante
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib import error, request

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"
DEFAULT_TIMEOUT_S = 60
MAX_RETRIES = 2


def call_firecrawl(url: str, fmt: str, api_key: str) -> dict:
    body = json.dumps({
        "url": url,
        "formats": [fmt],
        "onlyMainContent": True,
        "waitFor": 1500,
    }).encode("utf-8")
    req = request.Request(
        FIRECRAWL_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape URL via Firecrawl")
    ap.add_argument("url")
    ap.add_argument("--format", choices=("markdown", "html"), default="markdown")
    ap.add_argument("--max-chars", type=int, default=20000)
    ap.add_argument("--check-only", action="store_true",
                    help="Non stampa il contenuto, esce 0 se la pagina e' raggiungibile e non vuota")
    args = ap.parse_args()

    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        print("ERRORE: variabile d'ambiente FIRECRAWL_API_KEY non impostata", file=sys.stderr)
        return 3

    last_err: str | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = call_firecrawl(args.url, args.format, api_key)
        except error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.reason}"
        except error.URLError as e:
            last_err = f"URL error: {e.reason}"
        except (TimeoutError, OSError) as e:
            last_err = f"timeout/IO: {e}"
        except json.JSONDecodeError as e:
            last_err = f"risposta non-JSON: {e}"
        else:
            data = payload.get("data") or {}
            content = data.get(args.format) or ""
            if isinstance(content, str) and content.strip():
                if args.check_only:
                    return 0
                truncated = content[:args.max_chars]
                sys.stdout.write(truncated)
                sys.stdout.flush()
                return 0
            last_err = "contenuto vuoto"

        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)

    print(f"ERRORE Firecrawl per {args.url}: {last_err}", file=sys.stderr)
    return 1 if last_err == "contenuto vuoto" else 2


if __name__ == "__main__":
    sys.exit(main())
