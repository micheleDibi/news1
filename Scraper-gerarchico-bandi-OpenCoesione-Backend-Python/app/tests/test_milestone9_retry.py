from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import app.services.bando_discovery_service as service_module
from app.scrapers.fonte_level2 import FonteLevel2Error
from app.services.bando_discovery_service import BandoDiscoveryService


@dataclass
class _StatefulFonte:
    id: int
    link: str
    formato_link: str = "HTML"
    stato_processing: str = "ready"
    retry_count: int = 0
    max_retry: int = 2


class _FakeFonteRepo:
    def __init__(self, fonte: _StatefulFonte) -> None:
        self.fonte = fonte

    def get_all_active_with_limit(self, limit=None):
        if self.fonte.stato_processing == "failed_final":
            return []
        if self.fonte.stato_processing in {"ready", "pending"}:
            return [self.fonte]
        return []

    def mark_processing_started(self, fonte_id: int) -> None:
        self.fonte.stato_processing = "processing"

    def mark_processing_success(self, fonte_id: int) -> None:
        self.fonte.stato_processing = "ready"
        self.fonte.retry_count = 0

    def register_processing_error(
        self,
        fonte_id: int,
        *,
        error_type: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int,
    ):
        self.fonte.retry_count += 1
        should_retry = recoverable and self.fonte.retry_count < self.fonte.max_retry
        self.fonte.stato_processing = "pending" if should_retry else "failed_final"
        return {
            "found": True,
            "fonte_id": self.fonte.id,
            "entity_url": self.fonte.link,
            "stato_processing": self.fonte.stato_processing,
            "retry_count": self.fonte.retry_count,
            "max_retry": self.fonte.max_retry,
            "recoverable": recoverable,
        }


class _FakeBandoRepo:
    def __init__(self) -> None:
        self.retry_calls = 0

    def upsert_candidates(self, payload):
        return {"processed": len(payload), "inserted": 0, "updated": 0, "unchanged": len(payload), "bando_ids": []}

    def register_processing_error_by_hash(
        self,
        hash_bando: str,
        *,
        error_type: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int,
    ):
        self.retry_calls += 1
        return {
            "found": True,
            "bando_id": 101,
            "fonte_id": 1,
            "entity_url": "https://example.org/bando.pdf",
            "stato_processing": "pending" if recoverable else "failed_final",
            "retry_count": 1,
            "max_retry": 3,
            "recoverable": recoverable,
        }


class _FakeErrorRepo:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def insert_definitive_error(self, **kwargs):
        self.items.append(kwargs)


class _FakeAiPipeline:
    @staticmethod
    def enqueue_from_candidates(payload, bando_ids):
        return {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": 0}


def _build_service(fonte_repo, scanner):
    service = BandoDiscoveryService()
    service.fonte_repo = fonte_repo
    service.bando_repo = _FakeBandoRepo()
    service.error_repo = _FakeErrorRepo()
    service.scanner = scanner
    service.classifier = SimpleNamespace(classify_candidates=lambda payload, fonte=None: payload)
    service.ai_pipeline = _FakeAiPipeline()
    service._create_log_entry = lambda *args, **kwargs: 1
    service._finalize_success = lambda *args, **kwargs: None
    service._finalize_error = lambda *args, **kwargs: None
    return service


def test_retry_timeout_esaurimento_e_spostamento_errori_definitivi():
    fonte = _StatefulFonte(id=1, link="https://example.org/fonte")
    fonte_repo = _FakeFonteRepo(fonte)
    scanner = SimpleNamespace(
        scan_fonte=lambda fonte_obj: (_ for _ in ()).throw(
            FonteLevel2Error("Timeout fetch fonte", recoverable=True, http_status_code=503)
        )
    )

    service = _build_service(fonte_repo, scanner)

    result_1 = service.run(limit=1)
    assert result_1["retry"]["fonti_pending"] == 1
    assert result_1["retry"]["errori_definitivi"] == 0

    result_2 = service.run(limit=1)
    assert result_2["retry"]["fonti_failed_final"] == 1
    assert result_2["retry"]["errori_definitivi"] == 1
    assert len(service.error_repo.items) == 1

    result_3 = service.run(limit=1)
    assert result_3["fonti_scansionate"] == 0


def test_ripresa_automatica_al_run_successivo_dopo_pending():
    fonte = _StatefulFonte(id=2, link="https://example.org/fonte-2")
    fonte_repo = _FakeFonteRepo(fonte)

    calls = {"n": 0}

    def _scan(_fonte):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FonteLevel2Error("Errore temporaneo", recoverable=True)
        return []

    scanner = SimpleNamespace(scan_fonte=_scan)
    service = _build_service(fonte_repo, scanner)

    first = service.run(limit=1)
    assert first["retry"]["fonti_pending"] == 1
    assert fonte.stato_processing == "pending"

    second = service.run(limit=1)
    assert second["retry"]["fonti_pending"] == 0
    assert fonte.stato_processing == "ready"
    assert fonte.retry_count == 0


def test_retry_su_pdf_temporaneamente_non_leggibile():
    fonte = _StatefulFonte(id=3, link="https://example.org/fonte-pdf", formato_link="PDF")
    fonte_repo = _FakeFonteRepo(fonte)
    scanner = SimpleNamespace(
        scan_fonte=lambda fonte_obj: [SimpleNamespace(hash_bando="hash-pdf-1")]
    )

    service = _build_service(fonte_repo, scanner)

    original_converter = service_module.candidates_to_upsert_payload

    def _raise_pdf_error(*args, **kwargs):
        raise RuntimeError("PDF temporaneamente non leggibile")

    service_module.candidates_to_upsert_payload = _raise_pdf_error
    try:
        result = service.run(limit=1)
    finally:
        service_module.candidates_to_upsert_payload = original_converter

    assert result["retry"]["bandi_pending"] == 1
    assert result["retry"]["bandi_failed_final"] == 0
    assert service.bando_repo.retry_calls == 1
