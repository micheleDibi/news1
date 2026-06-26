"""Upload manuale di un batch di bandi su Supabase.

Lo script legge tutti i JSON di un batch (output/batch_YYYY-MM-DD/), li valida
una seconda volta a livello di campi obbligatori e li inserisce nella tabella
`bandi` via REST API Supabase (PostgREST).

Uso:
    python scripts/upload_to_supabase.py --batch 2026-06-17 --dry-run
    python scripts/upload_to_supabase.py --batch 2026-06-17
    python scripts/upload_to_supabase.py --batch 2026-06-17 --upsert      # upsert su source_url
    python scripts/upload_to_supabase.py --file output/batch_X/003_bando-y.json

Variabili d'ambiente richieste:
    SUPABASE_URL              es. https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY      service role key (NON anon: serve scrittura su bandi)

Exit code:
    0 = ok (anche dry-run)
    1 = warning di validazione bloccanti
    2 = errore di rete / API
    3 = configurazione mancante
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import error, request

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
OUTPUT_ROOT = SKILL_ROOT / "output"

REQUIRED_FIELDS = ("source_url", "source_domain", "slug", "titolo", "descrizione_breve",
                   "meta_title", "meta_description", "contenuto")
REQUIRED_BANDO = ("ente_erogatore",)


def supabase_insert(rows: list[dict], *, supabase_url: str, service_key: str, upsert: bool) -> dict:
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/bandi"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else ""),
    }
    if upsert:
        endpoint += "?on_conflict=source_url"
    body = json.dumps(rows).encode("utf-8")
    req = request.Request(endpoint, data=body, method="POST", headers=headers)
    with request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
        return {"status": resp.status, "body": json.loads(text) if text else []}


def map_to_row(payload: dict) -> dict:
    """Trasforma il JSON skill nel record per la tabella bandi."""
    bando = payload.get("bando") or {}
    return {
        "source_url": payload.get("source_url"),
        "source_domain": payload.get("source_domain"),
        "slug": payload.get("slug"),
        "titolo": payload.get("titolo"),
        "occhiello": payload.get("occhiello"),
        "descrizione_breve": payload.get("descrizione_breve"),
        "contenuto": payload.get("contenuto"),
        "meta_title": payload.get("meta_title"),
        "meta_description": payload.get("meta_description"),
        "ente_erogatore": bando.get("ente_erogatore"),
        "tipologia": bando.get("tipologia"),
        "area_geografica": bando.get("area_geografica"),
        "beneficiari": bando.get("beneficiari") or [],
        "tematica": bando.get("tematica") or [],
        "scadenza": bando.get("scadenza"),
        "scadenza_stato": bando.get("scadenza_stato"),
        "importo_totale_eur": bando.get("importo_totale_eur"),
        "importo_max_per_progetto_eur": bando.get("importo_max_per_progetto_eur"),
        "link_candidatura": bando.get("link_candidatura"),
        "riferimento_normativo": bando.get("riferimento_normativo"),
        "status": "draft",
        "factcheck_report": payload.get("factcheck_report") or [],
        "validation": payload.get("validation") or {},
        "fonti": payload.get("fonti") or [],
    }


def precheck(payload: dict, source_file: Path) -> list[str]:
    errors: list[str] = []
    for f in REQUIRED_FIELDS:
        if not payload.get(f):
            errors.append(f"{source_file.name}: campo obbligatorio mancante: {f}")
    bando = payload.get("bando") or {}
    for f in REQUIRED_BANDO:
        if not bando.get(f):
            errors.append(f"{source_file.name}: bando.{f} obbligatorio mancante")
    v = payload.get("validation") or {}
    if not v.get("passed", False):
        warns = v.get("warnings", [])
        errors.append(f"{source_file.name}: validazione skill NON passata ({len(warns)} warning) — risolvi prima di pubblicare")
    return errors


def collect_files(batch: str | None, file_arg: str | None) -> list[Path]:
    if file_arg:
        p = Path(file_arg).resolve()
        if not p.exists():
            raise FileNotFoundError(p)
        return [p]
    if not batch:
        raise ValueError("specifica --batch YYYY-MM-DD oppure --file PATH")
    batch_dir = OUTPUT_ROOT / f"batch_{batch}"
    if not batch_dir.exists():
        raise FileNotFoundError(batch_dir)
    return sorted(batch_dir.glob("*.json"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload manuale batch bandi su Supabase")
    ap.add_argument("--batch", default=None, help="Data batch in formato YYYY-MM-DD")
    ap.add_argument("--file", default=None, help="Singolo file JSON (alternativa a --batch)")
    ap.add_argument("--dry-run", action="store_true", help="Valida e mostra cosa verrebbe inserito, senza chiamare Supabase")
    ap.add_argument("--upsert", action="store_true", help="Usa upsert su source_url invece di insert")
    args = ap.parse_args()

    try:
        files = collect_files(args.batch, args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 2

    if args.batch:
        files = [f for f in files if f.name != "riepilogo.json"]

    if not files:
        print("Nessun file da elaborare.")
        return 0

    rows: list[dict] = []
    all_errors: list[str] = []
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            all_errors.append(f"{f.name}: JSON invalido: {e}")
            continue
        errs = precheck(payload, f)
        if errs:
            all_errors.extend(errs)
            continue
        rows.append(map_to_row(payload))

    if all_errors:
        print("=== PRE-CHECK FALLITI ===", file=sys.stderr)
        for e in all_errors:
            print(f" - {e}", file=sys.stderr)
        if rows:
            print(f"\n{len(rows)} record OK su {len(files)} file. Rimuovi --strict per pubblicare solo i validi.", file=sys.stderr)
        return 1

    print(f"Pronti {len(rows)} record per upload (upsert={args.upsert}).")
    if args.dry_run:
        print(json.dumps(rows[:1], ensure_ascii=False, indent=2)[:2000])
        print("\n[dry-run] niente scritto su Supabase.")
        return 0

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not supabase_url or not service_key:
        print("ERRORE: SUPABASE_URL e SUPABASE_SERVICE_KEY non impostati", file=sys.stderr)
        return 3

    try:
        result = supabase_insert(rows, supabase_url=supabase_url, service_key=service_key, upsert=args.upsert)
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERRORE Supabase HTTP {e.code}: {body}", file=sys.stderr)
        return 2
    except error.URLError as e:
        print(f"ERRORE rete Supabase: {e.reason}", file=sys.stderr)
        return 2

    print(f"Upload OK: HTTP {result['status']}, righe inserite/aggiornate: {len(result['body'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
