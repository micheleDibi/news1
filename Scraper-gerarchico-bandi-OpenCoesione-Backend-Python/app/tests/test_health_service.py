"""
Test per HealthService e HealthRepo.

I test usano mock del HealthRepo per evitare connessioni DB reali.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.health_service import HealthService, _age_hours, _semaforo_value


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_repo(
    *,
    last_run: dict | None = None,
    fonti_stats: dict | None = None,
    bandi_quality: dict | None = None,
    ai_queue_stats: dict | None = None,
    error_stats: dict | None = None,
    storico_stats: dict | None = None,
) -> MagicMock:
    now = datetime.now(timezone.utc)
    mock = MagicMock()
    mock.get_last_run.return_value = last_run if last_run is not None else {
        "stato": "completed",
        "completed_at": now - timedelta(hours=1),
        "tempo_esecuzione_ms": 5 * 60 * 1000,
        "bandi_trovati": 50,
        "bandi_nuovi": 10,
        "bandi_aggiornati": 5,
        "bandi_invariati": 35,
        "errori": 0,
        "response_summary": {},
    }
    mock.get_fonti_stats.return_value = fonti_stats if fonti_stats is not None else {
        "by_stato": {"ready": 20, "processing": 0},
        "totale_attive": 20,
        "failed_final": 0,
        "pending": 0,
        "processing_stuck": 0,
    }
    mock.get_bandi_quality.return_value = bandi_quality if bandi_quality is not None else {
        "totale": 100,
        "senza_descrizione": 30,
        "senza_scadenza": 40,
        "senza_importo": 50,
        "senza_classificazione": 20,
        "stato_programmato": 60,
        "failed_final": 0,
        "sospetti_rumore": 2,
        "duplicati": 0,
        "pct_con_descrizione": 70.0,
        "pct_con_classificazione": 80.0,
        "pct_sospetti_rumore": 2.0,
        "ultime_3_run_totale": 3,
        "ultime_3_run_completed": 3,
    }
    mock.get_ai_queue_stats.return_value = ai_queue_stats if ai_queue_stats is not None else {
        "by_stato": {"queued": 5, "completed": 90, "failed": 0},
        "queued": 5,
        "failed": 0,
        "processing_stuck": 0,
        "avg_completion_seconds": 15.0,
    }
    mock.get_error_stats.return_value = error_stats if error_stats is not None else {
        "totale": 2,
        "aperti": 0,
        "risolti": 2,
        "top_tipi": [],
    }
    mock.get_storico_stats.return_value = storico_stats if storico_stats is not None else {
        "righe_ultime_24h": 10,
        "bandi_incoerenti_date": 0,
    }
    return mock


# ---------------------------------------------------------------------------
# Test helper functions
# ---------------------------------------------------------------------------

def test_semaforo_value_verde():
    assert _semaforo_value(["ok", "ok", "ok"]) == "VERDE"


def test_semaforo_value_giallo():
    assert _semaforo_value(["ok", "GIALLO", "ok"]) == "GIALLO"


def test_semaforo_value_rosso_wins():
    assert _semaforo_value(["ok", "GIALLO", "ROSSO"]) == "ROSSO"


def test_age_hours_recente():
    dt = datetime.now(timezone.utc) - timedelta(hours=2)
    result = _age_hours(dt)
    assert result is not None
    assert 1.9 < result < 2.1


def test_age_hours_none():
    assert _age_hours(None) is None


def test_age_hours_stringa_iso():
    dt = datetime.now(timezone.utc) - timedelta(hours=5)
    result = _age_hours(dt.isoformat())
    assert result is not None
    assert 4.9 < result < 5.1


# ---------------------------------------------------------------------------
# Test HealthService — semaforo complessivo sano
# ---------------------------------------------------------------------------

def test_get_report_sano():
    service = HealthService()
    service._repo = _make_repo()
    report = service.get_report()

    assert report["semaforo"] == "VERDE"
    assert "generated_at" in report
    assert "sections" in report
    assert set(report["sections"].keys()) == {
        "esecuzione", "fonti", "bandi", "ai_queue", "errori", "storico"
    }


def test_get_report_struttura_sezione():
    service = HealthService()
    service._repo = _make_repo()
    report = service.get_report()

    sec = report["sections"]["bandi"]
    assert "indicators" in sec
    assert "semaforo" in sec
    assert "raw" in sec
    assert isinstance(sec["indicators"], list)
    assert all("label" in i and "value" in i and "status" in i for i in sec["indicators"])


# ---------------------------------------------------------------------------
# Test: run fallito → sezione esecuzione ROSSO                             #
# ---------------------------------------------------------------------------

def test_section_esecuzione_run_fallito():
    now = datetime.now(timezone.utc)
    service = HealthService()
    service._repo = _make_repo(last_run={
        "stato": "failed",
        "completed_at": now - timedelta(hours=1),
        "tempo_esecuzione_ms": 10_000,
        "bandi_trovati": 0,
        "bandi_nuovi": 0,
        "bandi_aggiornati": 0,
        "bandi_invariati": 0,
        "errori": 1,
        "response_summary": {},
    })
    report = service.get_report()
    assert report["sections"]["esecuzione"]["semaforo"] == "ROSSO"


def test_section_esecuzione_run_vecchio():
    old_time = datetime.now(timezone.utc) - timedelta(hours=30)
    service = HealthService()
    service._repo = _make_repo(last_run={
        "stato": "completed",
        "completed_at": old_time,
        "tempo_esecuzione_ms": 5_000,
        "bandi_trovati": 10,
        "bandi_nuovi": 2,
        "bandi_aggiornati": 0,
        "bandi_invariati": 8,
        "errori": 0,
        "response_summary": {},
    })
    report = service.get_report()
    # 30 ore fa → supera WARNING (25h) ma non CRITICAL (48h) → GIALLO
    semaforo_esec = report["sections"]["esecuzione"]["semaforo"]
    assert semaforo_esec in ("GIALLO", "ROSSO")


def test_section_esecuzione_nessun_run():
    service = HealthService()
    service._repo = _make_repo(last_run={})
    report = service.get_report()
    assert report["sections"]["esecuzione"]["semaforo"] == "ROSSO"


# ---------------------------------------------------------------------------
# Test: fonti failed_final → sezione fonti ROSSO                           #
# ---------------------------------------------------------------------------

def test_section_fonti_failed_final_critico():
    service = HealthService()
    service._repo = _make_repo(fonti_stats={
        "by_stato": {"ready": 10, "failed_final": 10},
        "totale_attive": 20,
        "failed_final": 10,
        "pending": 0,
        "processing_stuck": 0,
    })
    report = service.get_report()
    assert report["sections"]["fonti"]["semaforo"] == "ROSSO"


def test_section_fonti_stuck_processing():
    service = HealthService()
    service._repo = _make_repo(fonti_stats={
        "by_stato": {"ready": 18, "processing": 2},
        "totale_attive": 20,
        "failed_final": 0,
        "pending": 0,
        "processing_stuck": 2,
    })
    report = service.get_report()
    assert report["sections"]["fonti"]["semaforo"] == "ROSSO"


# ---------------------------------------------------------------------------
# Test: bandi duplicati → sezione bandi ROSSO                              #
# ---------------------------------------------------------------------------

def test_section_bandi_duplicati():
    service = HealthService()
    service._repo = _make_repo(bandi_quality={
        "totale": 100,
        "senza_descrizione": 30,
        "senza_scadenza": 40,
        "senza_importo": 50,
        "senza_classificazione": 20,
        "stato_programmato": 60,
        "failed_final": 0,
        "sospetti_rumore": 2,
        "duplicati": 5,
        "pct_con_descrizione": 70.0,
        "pct_con_classificazione": 80.0,
        "pct_sospetti_rumore": 2.0,
        "ultime_3_run_totale": 3,
        "ultime_3_run_completed": 3,
    })
    report = service.get_report()
    assert report["sections"]["bandi"]["semaforo"] == "ROSSO"


def test_section_bandi_descrizione_critica():
    service = HealthService()
    service._repo = _make_repo(bandi_quality={
        "totale": 100,
        "senza_descrizione": 95,  # solo 5% con descrizione
        "senza_scadenza": 40,
        "senza_importo": 50,
        "senza_classificazione": 20,
        "stato_programmato": 60,
        "failed_final": 0,
        "sospetti_rumore": 2,
        "duplicati": 0,
        "pct_con_descrizione": 5.0,
        "pct_con_classificazione": 80.0,
        "pct_sospetti_rumore": 2.0,
        "ultime_3_run_totale": 3,
        "ultime_3_run_completed": 3,
    })
    report = service.get_report()
    assert report["sections"]["bandi"]["semaforo"] == "ROSSO"


def test_section_bandi_rumore_critico():
    service = HealthService()
    service._repo = _make_repo(bandi_quality={
        "totale": 100,
        "senza_descrizione": 10,
        "senza_scadenza": 10,
        "senza_importo": 10,
        "senza_classificazione": 10,
        "stato_programmato": 20,
        "failed_final": 0,
        "sospetti_rumore": 20,
        "duplicati": 0,
        "pct_con_descrizione": 90.0,
        "pct_con_classificazione": 90.0,
        "pct_sospetti_rumore": 20.0,
        "ultime_3_run_totale": 3,
        "ultime_3_run_completed": 3,
    })
    report = service.get_report()
    assert report["sections"]["bandi"]["semaforo"] == "ROSSO"


def test_section_bandi_stabilita_run_insufficiente():
    service = HealthService()
    service._repo = _make_repo(bandi_quality={
        "totale": 100,
        "senza_descrizione": 10,
        "senza_scadenza": 10,
        "senza_importo": 10,
        "senza_classificazione": 10,
        "stato_programmato": 20,
        "failed_final": 0,
        "sospetti_rumore": 2,
        "duplicati": 0,
        "pct_con_descrizione": 90.0,
        "pct_con_classificazione": 90.0,
        "pct_sospetti_rumore": 2.0,
        "ultime_3_run_totale": 2,
        "ultime_3_run_completed": 2,
    })
    report = service.get_report()
    assert report["sections"]["bandi"]["semaforo"] == "GIALLO"


# ---------------------------------------------------------------------------
# Test: AI queue bloccata → sezione ai_queue ROSSO                         #
# ---------------------------------------------------------------------------

def test_section_ai_queue_stuck():
    service = HealthService()
    service._repo = _make_repo(ai_queue_stats={
        "by_stato": {"processing": 3},
        "queued": 0,
        "failed": 0,
        "processing_stuck": 3,
        "avg_completion_seconds": None,
    })
    report = service.get_report()
    assert report["sections"]["ai_queue"]["semaforo"] == "ROSSO"


def test_section_ai_queue_troppi_queued():
    service = HealthService()
    service._repo = _make_repo(ai_queue_stats={
        "by_stato": {"queued": 600},
        "queued": 600,
        "failed": 0,
        "processing_stuck": 0,
        "avg_completion_seconds": 20.0,
    })
    report = service.get_report()
    assert report["sections"]["ai_queue"]["semaforo"] == "ROSSO"


# ---------------------------------------------------------------------------
# Test: errori aperti → sezione errori GIALLO/ROSSO                        #
# ---------------------------------------------------------------------------

def test_section_errori_giallo():
    service = HealthService()
    service._repo = _make_repo(error_stats={
        "totale": 3,
        "aperti": 3,
        "risolti": 0,
        "top_tipi": [{"entity_type": "fonte", "errore_tipo": "HTTPError", "n": 3}],
    })
    report = service.get_report()
    assert report["sections"]["errori"]["semaforo"] == "GIALLO"


def test_section_errori_rosso():
    service = HealthService()
    service._repo = _make_repo(error_stats={
        "totale": 25,
        "aperti": 25,
        "risolti": 0,
        "top_tipi": [],
    })
    report = service.get_report()
    assert report["sections"]["errori"]["semaforo"] == "ROSSO"


# ---------------------------------------------------------------------------
# Test: storico date incoerenti → sezione storico ROSSO                    #
# ---------------------------------------------------------------------------

def test_section_storico_incoerenti():
    service = HealthService()
    service._repo = _make_repo(storico_stats={
        "righe_ultime_24h": 10,
        "bandi_incoerenti_date": 2,
    })
    report = service.get_report()
    assert report["sections"]["storico"]["semaforo"] == "ROSSO"


# ---------------------------------------------------------------------------
# Test: semaforo complessivo aggrega correttamente                          #
# ---------------------------------------------------------------------------

def test_semaforo_complessivo_rosso_se_sezione_rossa():
    now = datetime.now(timezone.utc)
    service = HealthService()
    service._repo = _make_repo(last_run={
        "stato": "failed",
        "completed_at": now,
        "tempo_esecuzione_ms": 5_000,
        "bandi_trovati": 0,
        "bandi_nuovi": 0,
        "bandi_aggiornati": 0,
        "bandi_invariati": 0,
        "errori": 1,
        "response_summary": {},
    })
    report = service.get_report()
    assert report["semaforo"] == "ROSSO"
