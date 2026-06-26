"""Orchestratore CLI per il batch bandi.

Versione "scaffolding": gestisce caricamento CSV, presentazione, scrape via
Firecrawl, estrazione campi, generazione JSON con sezioni stub. La generazione
editoriale (testo SEO) e' demandata alla skill quando lanciata da Claude Code:
in CLI standalone produce un JSON con `contenuto.sections` minimo (apertura +
H2 placeholder) cosi' i passaggi tecnici si possono verificare anche senza
chiamare Anthropic.

Uso CLI (tecnico, per test e fallback):
    python scripts/run_batch.py --limit 5
    python scripts/run_batch.py --limit 5 --domain interreg
    python scripts/run_batch.py --limit 5 --include-scaduti
    python scripts/run_batch.py --limit 5 --dry-run        # solo load + scrape + extract, niente JSON

Quando lanciata dalla skill in Claude Code, l'agent puo' chiamare i singoli
script (load_csv.py, firecrawl_scrape.py, extract_bando_fields.py,
generate_json_output.py) componendo il workflow seguendo SKILL.md, e generando
contenuto editoriale ricco — questa CLI invece e' un esecutore deterministico.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
DEFAULT_CSV = (SKILL_ROOT.parent / "elenco_bandi.csv").resolve()
STATE_PATH = (SKILL_ROOT / "state" / "processed.json").resolve()
OUTPUT_ROOT = (SKILL_ROOT / "output").resolve()


def run_load_csv(limit: int, domain: str | None, include_processed: bool, csv_path: Path) -> dict:
    cmd = [
        sys.executable, str(HERE / "load_csv.py"),
        "--csv", str(csv_path),
        "--state", str(STATE_PATH),
        "--limit", str(limit),
    ]
    if domain:
        cmd += ["--domain", domain]
    if include_processed:
        cmd += ["--include-processed"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def run_firecrawl(url: str, fmt: str = "markdown") -> str | None:
    cmd = [sys.executable, str(HERE / "firecrawl_scrape.py"), url, "--format", fmt, "--max-chars", "20000"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout
    return None


def run_extract(markdown_text: str, url: str, hint: dict | None) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as tmp:
        tmp.write(markdown_text)
        tmp_path = tmp.name
    try:
        cmd = [
            sys.executable, str(HERE / "extract_bando_fields.py"),
            "--markdown-file", tmp_path,
            "--url", url,
            "--hint", json.dumps(hint or {}),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def update_state(entry: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {"processed": []}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # rimpiazza l'entry esistente per stesso url, altrimenti append
    state["processed"] = [e for e in state["processed"] if e.get("url") != entry["url"]]
    state["processed"].append(entry)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_stub_sections(titolo: str, fields: dict) -> list[dict]:
    """Sezioni minime quando la CLI gira fuori dalla skill (senza LLM).

    L'agent Claude Code che esegue la skill sostituira' queste sezioni con
    contenuto SEO ricco seguendo article_structure.md.
    """
    ente_text = fields.get("ente_erogatore") or "L'ente erogatore"
    apertura = (
        f"{ente_text} ha pubblicato un bando per il quale e' disponibile "
        "la documentazione ufficiale. Questa scheda riassume i dati strutturati "
        "estratti dal portale istituzionale."
    )
    if fields.get("importo_totale_eur"):
        apertura += f" Dotazione totale: {fields['importo_totale_eur']:,} €.".replace(",", ".")
    if fields.get("scadenza"):
        apertura += f" Scadenza: {fields['scadenza']}."

    return [
        {"type": "paragraph", "segments": [{"kind": "text", "text": apertura}]},
        {"type": "h2", "text": "Chi puo' candidarsi"},
        {"type": "paragraph", "segments": [{"kind": "text", "text": "Beneficiari estratti dalla pagina del bando: " + (", ".join(fields.get("beneficiari_candidates", [])) or "dato non estratto automaticamente, consultare il portale.")}]},
        {"type": "h2", "text": "Come e quando candidarsi"},
        {"type": "paragraph", "segments": [
            {"kind": "text", "text": "Tutte le informazioni di dettaglio sono disponibili sul portale ufficiale: "},
            {"kind": "link", "text": "consulta il bando integrale", "url": fields.get("link_candidatura") or fields.get("source_url", "")},
        ]},
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Orchestratore batch bandi (scaffolding CLI)")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--include-processed", action="store_true")
    ap.add_argument("--include-scaduti", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Skip generazione JSON, ferma dopo extract")
    args = ap.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"ERRORE: CSV non trovato: {csv_path}", file=sys.stderr)
        return 2

    print(f"[load_csv] csv={csv_path} limit={args.limit} domain={args.domain or '-'}")
    info = run_load_csv(args.limit, args.domain, args.include_processed, csv_path)
    print(json.dumps({k: v for k, v in info.items() if k != "batch"}, ensure_ascii=False, indent=2))
    if not info["batch"]:
        print("[load_csv] nessun candidato. Esco.")
        return 0

    today = dt.date.today().isoformat()
    batch_dir = OUTPUT_ROOT / f"batch_{today}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    # import locale per usare la funzione direttamente
    sys.path.insert(0, str(HERE))
    from generate_json_output import create_bando_json, slugify  # type: ignore

    summary = {"generated": 0, "skipped_scaduto": 0, "scrape_failed": 0, "errors": []}

    for idx, item in enumerate(info["batch"], start=1):
        url = item["url"]
        domain = item["domain"]
        hint = item.get("hint") or {}
        print(f"\n[{idx}/{len(info['batch'])}] {url}")

        md = run_firecrawl(url, "markdown") or run_firecrawl(url, "html")
        if not md:
            print(f"  [!] scrape fallito")
            summary["scrape_failed"] += 1
            update_state({"url": url, "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "status": "scrape_failed", "output_file": None, "slug": None})
            continue

        fields = run_extract(md, url, hint)
        fields["source_url"] = url

        scadenza = fields.get("scadenza")
        scaduto = False
        if scadenza:
            try:
                scaduto = dt.date.fromisoformat(scadenza) < dt.date.today()
            except ValueError:
                scaduto = False
        if scaduto and not args.include_scaduti:
            print(f"  [⏭️ ] scaduto il {scadenza}, skip")
            summary["skipped_scaduto"] += 1
            update_state({"url": url, "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "status": "skipped_scaduto", "output_file": None, "slug": None})
            continue

        if args.dry_run:
            print(f"  [dry-run] fields: {json.dumps({k: v for k, v in fields.items() if k not in ('beneficiari_candidates','tematica_candidates')}, ensure_ascii=False)}")
            continue

        # Titolo stub (in skill mode, l'agent generera' titolo ricco)
        ente = fields.get("ente_erogatore") or hint.get("ente") or "Ente non identificato"
        titolo = f"Bando {ente}"
        if scadenza:
            titolo = f"{titolo}: scadenza {scadenza}"
        titolo = titolo[:80]
        slug = slugify(titolo)

        # descrizione_breve stub (entro 180-320 char)
        desc = (
            f"{ente} ha pubblicato un bando di interesse per i potenziali beneficiari. "
            "Consulta la scheda per scadenza, importi e modalita' di candidatura."
        )
        if scadenza:
            desc = f"{ente} ha pubblicato un bando con scadenza {scadenza}. Scopri beneficiari, importi e come presentare domanda nella scheda completa con link al portale ufficiale."

        meta_title = f"Bando {ente}"[:60]
        meta_desc = desc[:155]

        sections = build_stub_sections(titolo, fields)

        try:
            payload = create_bando_json(
                source_url=url,
                source_domain=domain,
                titolo=titolo,
                occhiello=None,
                slug=slug,
                descrizione_breve=desc,
                meta_title=meta_title,
                meta_description=meta_desc,
                contenuto_sections=sections,
                bando_data={
                    "ente_erogatore": fields.get("ente_erogatore") or hint.get("ente"),
                    "tipologia": fields.get("tipologia") or hint.get("tipologia"),
                    "area_geografica": fields.get("area_geografica") or hint.get("area"),
                    "beneficiari": fields.get("beneficiari_candidates", []),
                    "tematica": fields.get("tematica_candidates", []),
                    "scadenza": scadenza,
                    "scadenza_stato": None,
                    "importo_totale_eur": fields.get("importo_totale_eur"),
                    "importo_max_per_progetto_eur": fields.get("importo_max_per_progetto_eur"),
                    "link_candidatura": fields.get("link_candidatura"),
                    "riferimento_normativo": fields.get("riferimento_normativo"),
                },
                factcheck_report=[],
                fonti=[{"dato": "source", "fonte_url": url}],
                livello="flash_bando",
                output_path=batch_dir / f"{idx:03d}_{slug}.json",
            )
            warnings = payload["validation"]["warnings"]
            tag = "✅" if payload["validation"]["passed"] else "⚠️"
            print(f"  [{tag}] {payload['validation']['word_count']}p · warnings: {len(warnings)}")
            summary["generated"] += 1
            update_state({
                "url": url,
                "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "status": "generated",
                "output_file": str((batch_dir / f"{idx:03d}_{slug}.json").relative_to(SKILL_ROOT)),
                "slug": slug,
            })
        except Exception as e:  # noqa: BLE001 — CLI scaffolding
            print(f"  [!] errore generazione: {e}")
            summary["errors"].append({"url": url, "error": str(e)})

    print("\n=== RIEPILOGO BATCH ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    riepilogo_path = batch_dir / "riepilogo.json"
    riepilogo_path.write_text(json.dumps({"date": today, "summary": summary, "info": info}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Output: {batch_dir}")
    print(f"Stato: {STATE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
