from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import app.services.bando_discovery_service as service_module
from app.scrapers.fonte_level2 import FonteLevel2Error
from app.services.bando_discovery_service import BandoDiscoveryService


# ---------------------------------------------------------------------------
# Fake collaboratori
# ---------------------------------------------------------------------------

@dataclass
class _Fonte:
    id: int
    link: str
    formato_link: str = "HTML"
    stato_processing: str = "ready"
    retry_count: int = 0
    max_retry: int = 3


class _FakeFonteRepo:
    def __init__(self, fonti: list[_Fonte]) -> None:
        self.fonti = fonti

    def get_all_active_with_limit(self, limit=None):
        return [f for f in self.fonti if f.stato_processing in {"ready", "pending"}]

    def mark_processing_started(self, fonte_id: int) -> None:
        for f in self.fonti:
            if f.id == fonte_id:
                f.stato_processing = "processing"

    def mark_processing_success(self, fonte_id: int) -> None:
        for f in self.fonti:
            if f.id == fonte_id:
                f.stato_processing = "ready"
                f.retry_count = 0

    def register_processing_error(self, fonte_id, *, error_type, error_message, recoverable, retry_delay_seconds):
        for f in self.fonti:
            if f.id == fonte_id:
                f.retry_count += 1
                should_retry = recoverable and f.retry_count < f.max_retry
                f.stato_processing = "pending" if should_retry else "failed_final"
                return {
                    "found": True,
                    "fonte_id": f.id,
                    "entity_url": f.link,
                    "stato_processing": f.stato_processing,
                    "retry_count": f.retry_count,
                    "max_retry": f.max_retry,
                    "recoverable": recoverable,
                }
        return {"found": False}


class _FakeBandoRepo:
    def upsert_candidates(self, payload):
        return {
            "processed": len(payload),
            "inserted": 2,
            "updated": 1,
            "unchanged": len(payload) - 3 if len(payload) >= 3 else 0,
            "bando_ids": list(range(100, 100 + len(payload))),
        }

    def register_processing_error_by_hash(self, hash_bando, *, error_type, error_message, recoverable, retry_delay_seconds):
        return {
            "found": True,
            "bando_id": 999,
            "fonte_id": 1,
            "entity_url": None,
            "stato_processing": "pending",
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
        return {"considered": len(payload), "enqueued": len(payload), "already_present": 0, "not_required": 0}


class _FakeLogRepo:
    """Simula ScrapingLogRepo in memoria."""

    def __init__(self) -> None:
        self._next_id = 10
        self.fonte_logs: list[dict[str, Any]] = []

    def create_fonte_log_entry(self, session_id, parent_log_id, fonte_id, fonte_url, started_at) -> int:
        log_id = self._next_id
        self._next_id += 1
        self.fonte_logs.append({
            "id": log_id,
            "session_id": session_id,
            "parent_log_id": parent_log_id,
            "fonte_id": fonte_id,
            "fonte_url": fonte_url,
            "stato": "processing",
            "errore_tipo": None,
            "errore_messaggio": None,
            "errore_stack": None,
            "bandi_trovati": None,
            "bandi_nuovi": None,
            "bandi_aggiornati": None,
            "bandi_invariati": None,
            "ai_calls_count": 0,
            "elapsed_ms": None,
        })
        return log_id

    def update_fonte_log_success(self, log_id, *, elapsed_ms, bandi_trovati, bandi_nuovi, bandi_aggiornati, bandi_invariati, ai_calls_count=0, ai_tokens_used=0):
        for entry in self.fonte_logs:
            if entry["id"] == log_id:
                entry["stato"] = "completed"
                entry["elapsed_ms"] = elapsed_ms
                entry["bandi_trovati"] = bandi_trovati
                entry["bandi_nuovi"] = bandi_nuovi
                entry["bandi_aggiornati"] = bandi_aggiornati
                entry["bandi_invariati"] = bandi_invariati
                entry["ai_calls_count"] = ai_calls_count

    def update_fonte_log_error(self, log_id, *, elapsed_ms, error_type, error_message, error_stack=None):
        for entry in self.fonte_logs:
            if entry["id"] == log_id:
                entry["stato"] = "failed"
                entry["elapsed_ms"] = elapsed_ms
                entry["errore_tipo"] = error_type
                entry["errore_messaggio"] = error_message
                entry["errore_stack"] = error_stack


def _build_service(fonte_repo, scanner, candidates_factory=None, bando_repo=None):
    """Costruisce un BandoDiscoveryService con tutti i collaboratori sostituiti."""
    log_repo = _FakeLogRepo()
    service = BandoDiscoveryService()
    service.fonte_repo = fonte_repo
    service.bando_repo = bando_repo or _FakeBandoRepo()
    service.error_repo = _FakeErrorRepo()
    service.log_repo = log_repo
    service.scanner = scanner
    service.classifier = SimpleNamespace(classify_candidates=lambda payload, fonte=None: payload)
    service.ai_pipeline = _FakeAiPipeline()
    service._create_log_entry = lambda *args, **kwargs: 1
    service._finalize_success = lambda *args, **kwargs: None
    service._finalize_error = lambda *args, **kwargs: None
    return service, log_repo


# ---------------------------------------------------------------------------
# Test 1 — Log run completo: ogni fonte ha un entry finalizzato correttamente
# ---------------------------------------------------------------------------

def test_log_run_completo_ogni_fonte_ha_entry():
    """Ogni fonte processata con successo deve produrre un entry completed nel log."""
    fonti = [
        _Fonte(id=1, link="https://example.org/fonte-1"),
        _Fonte(id=2, link="https://example.org/fonte-2"),
    ]
    fonte_repo = _FakeFonteRepo(fonti)

    def _make_candidates(fonte_obj):
        return [
            SimpleNamespace(hash_bando=f"hash-{fonte_obj.id}-{i}")
            for i in range(3)
        ]

    scanner = SimpleNamespace(scan_fonte=_make_candidates)
    service, log_repo = _build_service(fonte_repo, scanner)

    def _payload(candidates, scraping_log_id=None):
        return [
            {"hash_bando": c.hash_bando, "titolo": "T", "link_bando": "http://x", "fonte_id": 1, "raw_data": "{}"}
            for c in candidates
        ]

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["fonti_scansionate"] == 2
    assert len(log_repo.fonte_logs) == 2

    for entry in log_repo.fonte_logs:
        assert entry["stato"] == "completed", f"Stato atteso 'completed', trovato '{entry['stato']}'"
        assert entry["parent_log_id"] == 1
        assert entry["bandi_trovati"] == 3
        assert entry["bandi_nuovi"] == 2
        assert entry["bandi_aggiornati"] == 1
        assert entry["elapsed_ms"] is not None
        assert entry["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# Test 2 — Log run con errore: entry deve risultare failed con stacktrace
# ---------------------------------------------------------------------------

def test_log_run_con_errore_entry_failed_con_stacktrace():
    """Quando una fonte fallisce, l'entry deve avere stato 'failed' e stacktrace."""
    fonte = _Fonte(id=10, link="https://example.org/fonte-err")
    fonte_repo = _FakeFonteRepo([fonte])
    scanner = SimpleNamespace(
        scan_fonte=lambda _: (_ for _ in ()).throw(
            FonteLevel2Error("Connection refused", recoverable=True)
        )
    )
    service, log_repo = _build_service(fonte_repo, scanner)

    service.run()

    assert len(log_repo.fonte_logs) == 1
    entry = log_repo.fonte_logs[0]
    assert entry["stato"] == "failed"
    assert entry["errore_tipo"] == "FonteLevel2Error"
    assert "Connection refused" in entry["errore_messaggio"]
    assert entry["errore_stack"] is not None
    assert len(entry["errore_stack"]) > 0


# ---------------------------------------------------------------------------
# Test 3 — Correlazione session_id: tutti gli entry condividono session_id
# ---------------------------------------------------------------------------

def test_correlazione_session_id_tutti_gli_entry_condividono_session():
    """Ogni entry per-fonte deve avere lo stesso session_id della run globale."""
    fonti = [_Fonte(id=i, link=f"https://example.org/fonte-{i}") for i in range(1, 4)]
    fonte_repo = _FakeFonteRepo(fonti)
    scanner = SimpleNamespace(scan_fonte=lambda _: [])
    service, log_repo = _build_service(fonte_repo, scanner)

    result = service.run()

    session_id = result["session_id"]
    assert len(log_repo.fonte_logs) == 3

    for entry in log_repo.fonte_logs:
        assert entry["session_id"] == session_id, (
            f"session_id dell'entry ({entry['session_id']}) != session_id del run ({session_id})"
        )


# ---------------------------------------------------------------------------
# Test 4 — Consistenza conteggi: somma dei log per-fonte == totale run
# ---------------------------------------------------------------------------

def test_consistenza_conteggi_somma_per_fonte_uguale_totale_run():
    """La somma di inserted+updated+unchanged di tutti gli entry deve coincidere con i totali del run."""
    fonti = [_Fonte(id=i, link=f"https://example.org/fonte-{i}") for i in range(1, 4)]
    fonte_repo = _FakeFonteRepo(fonti)

    def _candidates(fonte_obj):
        return [SimpleNamespace(hash_bando=f"h-{fonte_obj.id}-{j}") for j in range(4)]

    scanner = SimpleNamespace(scan_fonte=_candidates)
    service, log_repo = _build_service(fonte_repo, scanner)

    def _payload(candidates, scraping_log_id=None):
        return [
            {"hash_bando": c.hash_bando, "titolo": "T", "link_bando": "http://x", "fonte_id": 1, "raw_data": "{}"}
            for c in candidates
        ]

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    total_trovati = sum(e["bandi_trovati"] for e in log_repo.fonte_logs if e["bandi_trovati"] is not None)
    total_nuovi = sum(e["bandi_nuovi"] for e in log_repo.fonte_logs if e["bandi_nuovi"] is not None)
    total_aggiornati = sum(e["bandi_aggiornati"] for e in log_repo.fonte_logs if e["bandi_aggiornati"] is not None)

    assert total_trovati == result["bandi_identificati"]
    assert total_nuovi == result["inserted"]
    assert total_aggiornati == result["updated"]


# ---------------------------------------------------------------------------
# Test 5 — Stacktrace presente solo in caso di errore
# ---------------------------------------------------------------------------

def test_stacktrace_presente_solo_in_caso_di_errore():
    """Un entry per-fonte senza errore non deve avere stacktrace; uno con errore sì."""
    fonte_ok = _Fonte(id=20, link="https://example.org/ok")
    fonte_err = _Fonte(id=21, link="https://example.org/err")
    fonte_repo = _FakeFonteRepo([fonte_ok, fonte_err])

    def _scan(fonte_obj):
        if fonte_obj.id == 21:
            raise RuntimeError("Errore generico inatteso")
        return []

    scanner = SimpleNamespace(scan_fonte=_scan)
    service, log_repo = _build_service(fonte_repo, scanner)

    service.run()

    assert len(log_repo.fonte_logs) == 2

    ok_entry = next(e for e in log_repo.fonte_logs if e["fonte_id"] == 20)
    err_entry = next(e for e in log_repo.fonte_logs if e["fonte_id"] == 21)

    assert ok_entry["stato"] == "completed"
    assert ok_entry["errore_stack"] is None

    assert err_entry["stato"] == "failed"
    assert err_entry["errore_stack"] is not None
    assert "RuntimeError" in err_entry["errore_stack"]
