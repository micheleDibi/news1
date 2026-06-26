"""Caricamento del CSV bandi con normalizzazione URL, deduplica vs stato persistente e filtri.

Uso CLI:
    python scripts/load_csv.py --csv ../elenco_bandi.csv --state ./state/processed.json --limit 10
    python scripts/load_csv.py --csv ../elenco_bandi.csv --state ./state/processed.json --limit 5 --domain interreg
    python scripts/load_csv.py --csv ../elenco_bandi.csv --state ./state/processed.json --limit 10 --include-processed

Output su stdout: JSON con `total_in_csv`, `already_processed`, `candidates_after_filter`, `batch`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
SOURCES_PATH = HERE.parent / "config" / "sources.json"


def load_sources() -> dict:
    if not SOURCES_PATH.exists():
        return {}
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def normalize_url(raw: str) -> str:
    """Risolve i redirect di portale ricorrenti e rimuove parametri di tracking."""
    url = raw.strip()
    if not url:
        return ""

    parsed = urlparse(url)

    # Caso Lombardia: https://ue.regione.lombardia.it/site/to-menu-url?url=https://target
    if parsed.netloc.endswith("regione.lombardia.it") and "to-menu-url" in parsed.path:
        qs = parse_qs(parsed.query)
        target = qs.get("url", [None])[0]
        if target:
            return normalize_url(unquote(target))

    # Caso generico: ?redirect=... o ?url=...
    if parsed.query:
        qs = parse_qs(parsed.query)
        for key in ("redirect", "url", "destination", "to"):
            if key in qs and qs[key][0].startswith(("http://", "https://")):
                return normalize_url(unquote(qs[key][0]))

    # Rimuovi parametri di tracking noti senza alterare path
    tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                       "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid"}
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_qs = {k: v for k, v in qs.items() if k not in tracking_params}
        if cleaned_qs != qs:
            from urllib.parse import urlencode, urlunparse
            new_query = urlencode(cleaned_qs, doseq=True)
            parsed = parsed._replace(query=new_query)
            url = urlunparse(parsed)

    return url.rstrip("/")


def extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def hint_for(url: str, sources: dict) -> dict | None:
    domain = extract_domain(url)
    if domain in sources:
        return sources[domain]
    # match suffisso
    for src_domain, hint in sources.items():
        if domain.endswith("." + src_domain):
            return hint
    return None


def read_csv(csv_path: Path) -> list[str]:
    rows: list[str] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "link_bando" not in reader.fieldnames:
            raise ValueError(f"CSV deve avere colonna 'link_bando'. Colonne trovate: {reader.fieldnames}")
        for row in reader:
            link = (row.get("link_bando") or "").strip()
            if link:
                rows.append(link)
    return rows


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"processed": []}
    return json.loads(state_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Carica e filtra il CSV dei bandi")
    ap.add_argument("--csv", required=True, help="Percorso del CSV con colonna link_bando")
    ap.add_argument("--state", required=True, help="Percorso del file di stato processed.json")
    ap.add_argument("--limit", type=int, default=10, help="Massimo numero di candidati da restituire (default 10, hard cap 50)")
    ap.add_argument("--domain", default=None, help="Filtra solo URL il cui dominio contiene questa stringa")
    ap.add_argument("--include-processed", action="store_true", help="Non escludere gli URL gia' processati")
    args = ap.parse_args()

    limit = max(1, min(50, args.limit))

    csv_path = Path(args.csv).resolve()
    state_path = Path(args.state).resolve()
    if not csv_path.exists():
        print(json.dumps({"error": f"CSV non trovato: {csv_path}"}), file=sys.stderr)
        return 2

    raw_urls = read_csv(csv_path)
    total_in_csv = len(raw_urls)

    normalized = []
    seen = set()
    for u in raw_urls:
        nu = normalize_url(u)
        if nu and nu not in seen:
            seen.add(nu)
            normalized.append(nu)

    state = load_state(state_path)
    processed_set = {entry["url"] for entry in state.get("processed", [])}
    already_processed = sum(1 for u in normalized if u in processed_set)

    sources = load_sources()
    candidates: list[dict] = []
    for url in normalized:
        if not args.include_processed and url in processed_set:
            continue
        domain = extract_domain(url)
        if args.domain and args.domain.lower() not in domain:
            continue
        candidates.append({
            "url": url,
            "domain": domain,
            "hint": hint_for(url, sources),
        })

    batch = candidates[:limit]

    print(json.dumps({
        "csv_path": str(csv_path),
        "state_path": str(state_path),
        "total_in_csv": total_in_csv,
        "unique_after_normalize": len(normalized),
        "already_processed": already_processed,
        "candidates_after_filter": len(candidates),
        "batch_size": len(batch),
        "batch": batch,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
