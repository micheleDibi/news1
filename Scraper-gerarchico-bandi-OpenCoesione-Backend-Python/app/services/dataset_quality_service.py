from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.repos.base import HealthRepo


class DatasetQualityService:
    """Prepara analisi dataset e campioni per review manuale dei bandi sospetti."""

    def __init__(self, repo: HealthRepo | None = None) -> None:
        self._repo = repo or HealthRepo()

    def build_review_report(self, sample_limit: int = 50) -> dict[str, Any]:
        sample = self._repo.list_suspect_bandi(limit=sample_limit)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self._repo.get_dataset_review_summary(),
            "sample": sample,
            "sample_limit": sample_limit,
        }

    def export_sample_csv(self, sample: list[dict[str, Any]], output_path: str) -> str:
        fieldnames = [
            "id",
            "fonte_id",
            "titolo",
            "link_bando",
            "stato_bando",
            "stato_processing",
            "motivi_sospetto",
            "esito_validazione",
            "note_validazione",
        ]
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in sample:
                out = {key: row.get(key) for key in fieldnames}
                out["esito_validazione"] = ""
                out["note_validazione"] = ""
                writer.writerow(out)
        return str(target)

    def export_cleanup_sql_preview(
        self,
        output_path: str,
        *,
        id_scope: str,
        sample: list[dict[str, Any]],
    ) -> str:
        if id_scope == "all":
            ids = self._repo.list_suspect_bando_ids()
        else:
            ids = [int(r["id"]) for r in sample if r.get("id") is not None]

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        sql_lines: list[str] = [
            "-- Preview SQL NON ESECUTIVA: bonifica dataset sospetti",
            "-- Applicare solo dopo validazione manuale del cliente.",
            f"-- Scope: {id_scope}",
            f"-- Numero record nello scope: {len(ids)}",
            "",
        ]

        if not ids:
            sql_lines.append("-- Nessun ID disponibile nello scope selezionato.")
        else:
            joined = ", ".join(str(i) for i in ids)
            sql_lines.extend(
                [
                    "-- 1) Preview record target",
                    f"SELECT id, fonte_id, titolo, link_bando FROM public.bando WHERE id IN ({joined}) ORDER BY id;",
                    "",
                    "-- 2) Esempio UPDATE soft-delete logico (da eseguire solo dopo conferma)",
                    (
                        "-- UPDATE public.bando SET stato_processing = 'failed_final', "
                        "last_error_type = 'non_pertinente_dataset', "
                        "last_error_message = 'Bonifica Go-Live validata manualmente' "
                        f"WHERE id IN ({joined});"
                    ),
                    "",
                    "-- 3) Esempio hard-delete (sconsigliato, solo con decisione esplicita)",
                    f"-- DELETE FROM public.bando WHERE id IN ({joined});",
                ]
            )

        target.write_text("\n".join(sql_lines), encoding="utf-8")
        return str(target)