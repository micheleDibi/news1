"""
Runner CLI per il report di salute dello scraper.

Uso:
    python -m app.scrapers.run_health_check
    python -m app.scrapers.run_health_check --format text
    python -m app.scrapers.run_health_check --format json
    python -m app.scrapers.run_health_check --section bandi
"""
from __future__ import annotations

import argparse
import json
import sys

from app.services.health_service import HealthService

# Mappa emoji semaforo
_EMOJI = {"ok": "🟢", "GIALLO": "🟡", "ROSSO": "🔴", "VERDE": "🟢"}

_SECTION_LABELS = {
    "esecuzione": "Esecuzione",
    "fonti": "Copertura fonti",
    "bandi": "Qualità bandi",
    "ai_queue": "Coda AI",
    "errori": "Errori definitivi",
    "storico": "Storico e consistenza",
}


def _format_text(report: dict) -> str:
    lines: list[str] = []
    semaforo = report["semaforo"]
    emoji = _EMOJI.get(semaforo, "⚪")
    lines.append(f"\n{emoji}  SALUTE SCRAPER: {semaforo}")
    lines.append(f"   Generato: {report['generated_at']}")
    lines.append("")

    for sec_key, sec_label in _SECTION_LABELS.items():
        section = report["sections"].get(sec_key)
        if not section:
            continue
        sec_semaforo = section.get("semaforo", "ok")
        sec_emoji = _EMOJI.get(sec_semaforo, "⚪")
        lines.append(f"  {sec_emoji} {sec_label}")

        for ind in section.get("indicators", []):
            status = ind.get("status", "ok")
            ind_emoji = _EMOJI.get(status, "⚪")
            value = ind.get("value")
            unit = ind.get("unit", "")
            value_str = f"{value}{unit}" if value is not None else "—"
            lines.append(f"       {ind_emoji} {ind['label']}: {value_str}")

        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report salute scraper bandi")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Formato output (default: text)",
    )
    parser.add_argument(
        "--section",
        choices=list(_SECTION_LABELS.keys()),
        default=None,
        help="Mostra solo la sezione specificata",
    )
    parser.add_argument(
        "--fail-on-red",
        action="store_true",
        default=False,
        help="Esce con codice 1 se il semaforo complessivo è ROSSO",
    )
    args = parser.parse_args()

    service = HealthService()
    report = service.get_report()

    # Filtra sezione se richiesta
    if args.section:
        report["sections"] = {args.section: report["sections"].get(args.section, {})}
        section_statuses = [
            ind["status"]
            for ind in report["sections"][args.section].get("indicators", [])
        ]
        report["semaforo"] = (
            "ROSSO" if "ROSSO" in section_statuses
            else "GIALLO" if "GIALLO" in section_statuses
            else "VERDE"
        )

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(_format_text(report))

    if args.fail_on_red and report["semaforo"] == "ROSSO":
        sys.exit(1)


if __name__ == "__main__":
    main()
