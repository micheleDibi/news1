from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.services.dataset_quality_service import DatasetQualityService


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_dataset_review_summary.return_value = {
        "totale_bandi": 100,
        "sospetti_totali": 7,
        "pct_sospetti_totali": 7.0,
        "sospetti_host": 3,
        "sospetti_path": 2,
        "sospetti_keyword": 5,
        "field_completeness": {
            "totale": 100,
            "required_complete": 98,
            "pct_required_complete": 98.0,
            "with_raw_data": 100,
            "pct_with_raw_data": 100.0,
            "with_any_date": 30,
            "pct_with_any_date": 30.0,
            "with_importo_numerico": 12,
            "pct_with_importo_numerico": 12.0,
        },
        "top_fonti_sospette": [{"fonte_id": 11, "sospetti": 4}],
    }
    repo.list_suspect_bandi.return_value = [
        {
            "id": 1,
            "fonte_id": 11,
            "titolo": "Privacy policy",
            "link_bando": "https://example.org/privacy",
            "stato_bando": "programmato",
            "stato_processing": "ready",
            "motivi_sospetto": "deny_path|deny_keyword",
        }
    ]
    repo.list_suspect_bando_ids.return_value = [1, 2, 3]
    return repo


def test_build_review_report_aggregates_summary_and_sample():
    service = DatasetQualityService(repo=_make_repo())

    report = service.build_review_report(sample_limit=25)

    assert "generated_at" in report
    assert report["sample_limit"] == 25
    assert report["summary"]["sospetti_totali"] == 7
    assert len(report["sample"]) == 1


def test_export_sample_csv_writes_expected_headers(tmp_path: Path):
    service = DatasetQualityService(repo=_make_repo())
    sample = service.build_review_report()["sample"]

    output = service.export_sample_csv(sample, str(tmp_path / "sample.csv"))

    content = Path(output).read_text(encoding="utf-8")
    assert "motivi_sospetto" in content
    assert "esito_validazione" in content
    assert "Privacy policy" in content
    assert "deny_path|deny_keyword" in content


def test_export_cleanup_sql_preview_all_scope(tmp_path: Path):
    service = DatasetQualityService(repo=_make_repo())
    sample = service.build_review_report()["sample"]

    output = service.export_cleanup_sql_preview(
        str(tmp_path / "preview.sql"),
        id_scope="all",
        sample=sample,
    )

    content = Path(output).read_text(encoding="utf-8")
    assert "Scope: all" in content
    assert "WHERE id IN (1, 2, 3)" in content