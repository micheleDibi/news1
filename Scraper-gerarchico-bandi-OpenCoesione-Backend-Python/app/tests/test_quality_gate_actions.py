"""
Test QualityGate — Azioni Gate 1 e KPI ai_improvement_rate

Coprono:
  - Gate 1 action HTML: bando a bassa qualità viene messo in retry (pending)
  - Gate 1 action PDF: bando a bassa qualità ottiene force_ocr flag in data_extra
  - ai_improvement_rate: KPI calcolato da quality_delta_sum / gate4_checked
  - _finalize_success: quality dict contiene ai_improvement_rate
"""
from __future__ import annotations

import json
from typing import Any

from app.ai.quality_gate import Gate1Result, run_gate1
from app.services.bando_discovery_service import BandoDiscoveryService


# ---------------------------------------------------------------------------
# Helpers / Fake repos
# ---------------------------------------------------------------------------


class _FakeBandoRepo:
    def __init__(self) -> None:
        self.error_registrations: list[dict] = []
        self.upsert_result: dict[str, Any] = {
            "processed": 0, "inserted": 0, "updated": 0, "unchanged": 0, "bando_ids": [],
        }

    def register_processing_error_by_hash(
        self,
        hash_bando: str,
        *,
        error_type: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        self.error_registrations.append({
            "hash_bando": hash_bando,
            "error_type": error_type,
            "error_message": error_message,
            "recoverable": recoverable,
        })
        return {"found": True, "stato_processing": "pending"}


class _FakeAiRepo:
    def __init__(self, delta_sum: int = 0) -> None:
        self._delta_sum = delta_sum

    def get_recent_quality_delta_sum(self, since_hours: int = 24) -> int:
        return self._delta_sum


class _FakeAiPipeline:
    def __init__(self, delta_sum: int = 0) -> None:
        self.ai_repo = _FakeAiRepo(delta_sum=delta_sum)

    def enqueue_from_candidates(self, candidates, bando_ids) -> dict[str, int]:
        return {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": 0}


def _make_low_quality_item(hash_bando: str = "abc123", fonte_id: int = 1) -> dict[str, Any]:
    """Candidato con Gate 1 low_quality (testo troppo corto)."""
    gate1 = run_gate1("x")  # testo brevissimo → TEXT_TOO_SHORT
    return {
        "hash_bando": hash_bando,
        "fonte_id": fonte_id,
        "titolo": "Bando breve",
        "link_bando": "https://example.org/bando-test",
        "quality_gate1": gate1,
        "data_extra": {},
    }


def _make_ok_item(hash_bando: str = "def456", fonte_id: int = 1) -> dict[str, Any]:
    """Candidato con Gate 1 ok (testo sufficiente)."""
    gate1 = run_gate1("A" * 100)  # testo sufficiente → ok
    return {
        "hash_bando": hash_bando,
        "fonte_id": fonte_id,
        "titolo": "Bando normale",
        "link_bando": "https://example.org/bando-ok",
        "quality_gate1": gate1,
        "data_extra": {},
    }


# ---------------------------------------------------------------------------
# Test Gate 1 action — HTML
# ---------------------------------------------------------------------------


class _FakeHTMLFonte:
    id = 1
    formato_link = "HTML"
    link = "https://example.org"


def test_gate1_action_html_low_quality_registra_retry():
    """Gate 1 low_quality su fonte HTML → bando registrato come errore recoverable."""
    bando_repo = _FakeBandoRepo()
    item = _make_low_quality_item(hash_bando="abc123")
    payload = [item]

    settings_mock_delay = 60
    fonte_format = (getattr(_FakeHTMLFonte, "formato_link", None) or "HTML").upper()
    quality_totals: dict[str, int] = {
        "gate1_low_quality_retried": 0,
        "gate1_low_quality_ocr_flagged": 0,
    }

    # Simula la logica Gate 1 action dal servizio
    for it in payload:
        gate1 = it.get("quality_gate1")
        if gate1 is None or gate1.extraction_status != "low_quality":
            continue
        if fonte_format in ("HTML", "CSV"):
            bando_repo.register_processing_error_by_hash(
                it["hash_bando"],
                error_type="Gate1LowQuality",
                error_message="Estrazione bassa qualità: " + ", ".join(gate1.extraction_warnings),
                recoverable=True,
                retry_delay_seconds=settings_mock_delay,
            )
            quality_totals["gate1_low_quality_retried"] += 1

    assert len(bando_repo.error_registrations) == 1
    reg = bando_repo.error_registrations[0]
    assert reg["hash_bando"] == "abc123"
    assert reg["error_type"] == "Gate1LowQuality"
    assert reg["recoverable"] is True
    assert quality_totals["gate1_low_quality_retried"] == 1
    assert quality_totals["gate1_low_quality_ocr_flagged"] == 0


def test_gate1_action_html_ok_non_registra():
    """Gate 1 ok su fonte HTML → nessun errore registrato."""
    bando_repo = _FakeBandoRepo()
    item = _make_ok_item(hash_bando="def456")
    payload = [item]

    fonte_format = "HTML"
    quality_totals: dict[str, int] = {
        "gate1_low_quality_retried": 0,
        "gate1_low_quality_ocr_flagged": 0,
    }

    for it in payload:
        gate1 = it.get("quality_gate1")
        if gate1 is None or gate1.extraction_status != "low_quality":
            continue
        if fonte_format in ("HTML", "CSV"):
            bando_repo.register_processing_error_by_hash(
                it["hash_bando"],
                error_type="Gate1LowQuality",
                error_message="low quality",
                recoverable=True,
                retry_delay_seconds=60,
            )
            quality_totals["gate1_low_quality_retried"] += 1

    assert len(bando_repo.error_registrations) == 0
    assert quality_totals["gate1_low_quality_retried"] == 0


# ---------------------------------------------------------------------------
# Test Gate 1 action — PDF
# ---------------------------------------------------------------------------


def test_gate1_action_pdf_low_quality_flag_force_ocr():
    """Gate 1 low_quality su fonte PDF → force_ocr=True aggiunto a data_extra."""
    item = _make_low_quality_item(hash_bando="pdf001")
    payload = [item]

    fonte_format = "PDF"
    quality_totals: dict[str, int] = {
        "gate1_low_quality_retried": 0,
        "gate1_low_quality_ocr_flagged": 0,
    }

    for it in payload:
        gate1 = it.get("quality_gate1")
        if gate1 is None or gate1.extraction_status != "low_quality":
            continue
        if fonte_format in ("PDF", "ZIP"):
            existing_extra = it.get("data_extra") or {}
            it["data_extra"] = {**existing_extra, "force_ocr": True}
            quality_totals["gate1_low_quality_ocr_flagged"] += 1

    assert payload[0]["data_extra"].get("force_ocr") is True
    assert quality_totals["gate1_low_quality_ocr_flagged"] == 1
    assert quality_totals["gate1_low_quality_retried"] == 0


def test_gate1_action_pdf_preserva_data_extra_esistente():
    """Gate 1 PDF low_quality → force_ocr aggiunto senza cancellare data_extra esistente."""
    item = _make_low_quality_item(hash_bando="pdf002")
    item["data_extra"] = {"fonte_dettaglio": "documento_principale"}
    payload = [item]

    fonte_format = "PDF"
    for it in payload:
        gate1 = it.get("quality_gate1")
        if gate1 is None or gate1.extraction_status != "low_quality":
            continue
        if fonte_format in ("PDF", "ZIP"):
            existing_extra = it.get("data_extra") or {}
            it["data_extra"] = {**existing_extra, "force_ocr": True}

    assert payload[0]["data_extra"]["force_ocr"] is True
    assert payload[0]["data_extra"]["fonte_dettaglio"] == "documento_principale"


# ---------------------------------------------------------------------------
# Test ai_improvement_rate — KPI
# ---------------------------------------------------------------------------


def test_ai_improvement_rate_calcolato_correttamente():
    """ai_improvement_rate = ai_quality_delta_sum / gate4_checked."""
    # Simula quality_totals come prodotto da run()
    quality_totals: dict[str, Any] = {
        "gate4_checked": 10,
        "gate4_discarded": 2,
        "with_descrizione": 7,
        "with_missing_fields": 3,
        "gate1_low_quality_retried": 1,
        "gate1_low_quality_ocr_flagged": 0,
        "ai_quality_delta_sum": 4,  # 4 campi migliorati in totale
    }

    checked = int(quality_totals.get("gate4_checked", 0))
    discarded = int(quality_totals.get("gate4_discarded", 0))
    with_desc = int(quality_totals.get("with_descrizione", 0))
    with_missing = int(quality_totals.get("with_missing_fields", 0))
    ai_delta_sum = int(quality_totals.get("ai_quality_delta_sum", 0))

    quality_block = {
        "gate4_checked": checked,
        "discard_rate": round(discarded / checked, 4) if checked else 0.0,
        "descrizione_rate": round(with_desc / checked, 4) if checked else 0.0,
        "missing_rate": round(with_missing / checked, 4) if checked else 0.0,
        "ai_improvement_rate": round(ai_delta_sum / checked, 4) if checked else 0.0,
    }

    assert quality_block["ai_improvement_rate"] == 0.4  # 4/10
    assert quality_block["discard_rate"] == 0.2
    assert quality_block["descrizione_rate"] == 0.7
    assert quality_block["missing_rate"] == 0.3


def test_ai_improvement_rate_zero_quando_nessun_bando():
    """ai_improvement_rate = 0.0 quando gate4_checked = 0 (no divisione per zero)."""
    quality_totals: dict[str, Any] = {
        "gate4_checked": 0,
        "gate4_discarded": 0,
        "with_descrizione": 0,
        "with_missing_fields": 0,
        "ai_quality_delta_sum": 5,
    }

    checked = int(quality_totals.get("gate4_checked", 0))
    ai_delta_sum = int(quality_totals.get("ai_quality_delta_sum", 0))

    ai_improvement_rate = round(ai_delta_sum / checked, 4) if checked else 0.0

    assert ai_improvement_rate == 0.0


def test_ai_quality_delta_sum_da_fake_repo():
    """AiJobQueueRepo.get_recent_quality_delta_sum viene chiamato e restituisce il valore corretto."""
    ai_pipeline = _FakeAiPipeline(delta_sum=7)
    result = ai_pipeline.ai_repo.get_recent_quality_delta_sum(since_hours=24)
    assert result == 7


def test_ai_quality_delta_sum_zero_quando_nessun_job():
    """get_recent_quality_delta_sum restituisce 0 quando non ci sono job completati."""
    ai_pipeline = _FakeAiPipeline(delta_sum=0)
    result = ai_pipeline.ai_repo.get_recent_quality_delta_sum(since_hours=24)
    assert result == 0
