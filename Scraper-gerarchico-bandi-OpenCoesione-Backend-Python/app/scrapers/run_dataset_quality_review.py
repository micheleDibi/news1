"""
Runner CLI per review dataset e pre-bonifica dei bandi sospetti.

Uso:
    python -m app.scrapers.run_dataset_quality_review
    python -m app.scrapers.run_dataset_quality_review --format json
    python -m app.scrapers.run_dataset_quality_review --sample-limit 100 --export-csv db/go_live_dataset_sospetti.csv
"""
from __future__ import annotations

import argparse
import json

from app.services.dataset_quality_service import DatasetQualityService


def _format_text(report: dict, exported_csv: str | None = None) -> str:
    summary = report["summary"]
    completeness = summary.get("field_completeness") or {}
    lines = [
        "REVIEW DATASET GO-LIVE",
        f"Generato: {report['generated_at']}",
        "",
        f"Bandi totali: {summary.get('totale_bandi', 0)}",
        f"Bandi sospetti: {summary.get('sospetti_totali', 0)} ({summary.get('pct_sospetti_totali', 0.0)}%)",
        f"Sospetti per host denylist: {summary.get('sospetti_host', 0)}",
        f"Sospetti per path denylist: {summary.get('sospetti_path', 0)}",
        f"Sospetti per keyword denylist: {summary.get('sospetti_keyword', 0)}",
        "",
        "Completezza campi (checklist punto 3):",
        f"- Required complete (titolo/link/hash/stato): {completeness.get('required_complete', 0)}/{completeness.get('totale', 0)} ({completeness.get('pct_required_complete', 0.0)}%)",
        f"- Raw data presenti: {completeness.get('with_raw_data', 0)}/{completeness.get('totale', 0)} ({completeness.get('pct_with_raw_data', 0.0)}%)",
        f"- Almeno una data valorizzata: {completeness.get('with_any_date', 0)}/{completeness.get('totale', 0)} ({completeness.get('pct_with_any_date', 0.0)}%)",
        f"- Importo numerico valorizzato: {completeness.get('with_importo_numerico', 0)}/{completeness.get('totale', 0)} ({completeness.get('pct_with_importo_numerico', 0.0)}%)",
        "",
        "Top fonti con sospetti:",
    ]

    for row in summary.get("top_fonti_sospette", []):
        lines.append(f"- fonte_id={row.get('fonte_id')} sospetti={row.get('sospetti')}")

    if not summary.get("top_fonti_sospette"):
        lines.append("- nessuna")

    lines.extend([
        "",
        f"Campione estratto: {len(report.get('sample', []))} record",
    ])
    if exported_csv:
        lines.append(f"CSV esportato: {exported_csv}")
    if report.get("exported_sql_preview"):
        lines.append(f"SQL preview esportato: {report['exported_sql_preview']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review dataset e campione manuale record sospetti")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Formato output (default: text)",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=50,
        help="Numero massimo di record sospetti nel campione manuale (default: 50)",
    )
    parser.add_argument(
        "--export-csv",
        default=None,
        help="Percorso CSV dove esportare il campione sospetto",
    )
    parser.add_argument(
        "--export-cleanup-sql",
        default=None,
        help="Percorso file .sql per preview bonifica non esecutiva",
    )
    parser.add_argument(
        "--cleanup-scope",
        choices=["sample", "all"],
        default="sample",
        help="Scope ID per SQL preview (default: sample)",
    )
    args = parser.parse_args()

    service = DatasetQualityService()
    report = service.build_review_report(sample_limit=args.sample_limit)
    exported_csv = None
    if args.export_csv:
        exported_csv = service.export_sample_csv(report["sample"], args.export_csv)
        report["exported_csv"] = exported_csv

    if args.export_cleanup_sql:
        report["exported_sql_preview"] = service.export_cleanup_sql_preview(
            args.export_cleanup_sql,
            id_scope=args.cleanup_scope,
            sample=report["sample"],
        )

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    print(_format_text(report, exported_csv=exported_csv))


if __name__ == "__main__":
    main()