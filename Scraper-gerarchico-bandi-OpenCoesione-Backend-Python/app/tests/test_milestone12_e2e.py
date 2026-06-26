"""
Milestone 12 — Test end-to-end (mock-based)

Coprono i flussi critici della pipeline completa:
  - fonte HTML
  - fonte PDF
  - fonte PDF scansionato (OCR)
  - bando già esistente (unchanged)
  - errore recuperabile → pending
  - errore definitivo → failed_final
  - classificazione AI valida
  - output AI non valido → scartato
  - pending → retry → successo
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import app.services.bando_discovery_service as service_module
from app.scrapers.fonte_level2 import BandoCandidate, FonteLevel2Error
from app.services.bando_discovery_service import BandoDiscoveryService


# ---------------------------------------------------------------------------
# Helpers condivisi
# ---------------------------------------------------------------------------

@dataclass
class _Fonte:
    id: int
    link: str
    formato_link: str = "HTML"
    stato_processing: str = "ready"
    retry_count: int = 0
    max_retry: int = 3


def _make_candidate(fonte_id: int, idx: int = 0, formato: str = "HTML", ocr: bool = False) -> BandoCandidate:
    raw: dict[str, Any] = {"titolo": f"Bando {idx}", "link": f"https://example.org/b{idx}"}
    if ocr:
        raw["ocr_used"] = True
        raw["ocr_engine"] = "tesseract"
    return BandoCandidate(
        fonte_id=fonte_id,
        titolo=f"Bando {idx}",
        link_bando=f"https://example.org/b{idx}",
        hash_bando=f"hash-{fonte_id}-{idx}",
        formato_fonte=formato,
        source_url=f"https://example.org/fonte{fonte_id}",
        raw_data_obj=raw,
    )


class _FakeFonteRepo:
    def __init__(self, fonti: list[_Fonte]) -> None:
        self.fonti = fonti

    def get_all_active_with_limit(self, limit=None):
        return [f for f in self.fonti if f.stato_processing in {"ready", "pending"}]

    def get_pending(self):
        return [f for f in self.fonti if f.stato_processing == "pending"]

    def get_by_id(self, fonte_id: int):
        return next((f for f in self.fonti if f.id == fonte_id), None)

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
    """Upsert configurabile per simulare insert/update/unchanged."""

    def __init__(self, preset: dict[str, int] | None = None) -> None:
        self._preset = preset or {}
        self.upserted_payloads: list[list[dict]] = []

    def upsert_candidates(self, payload: list[dict]) -> dict[str, Any]:
        self.upserted_payloads.append(payload)
        n = len(payload)
        inserted = self._preset.get("inserted", n)
        updated = self._preset.get("updated", 0)
        unchanged = self._preset.get("unchanged", 0)
        return {
            "processed": n,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "bando_ids": list(range(100, 100 + n)),
        }

    def register_processing_error_by_hash(self, hash_bando, *, error_type, error_message, recoverable, retry_delay_seconds):
        return {
            "found": True,
            "bando_id": 999,
            "fonte_id": 1,
            "entity_url": None,
            "stato_processing": "pending" if recoverable else "failed_final",
            "retry_count": 1,
            "max_retry": 3,
            "recoverable": recoverable,
        }

    def set_ai_processing_flags(self, bando_id, *, required, status):
        pass


class _FakeErrorRepo:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def insert_definitive_error(self, **kwargs):
        self.items.append(kwargs)


class _FakeAiPipeline:
    def __init__(self, enqueued: int = 0) -> None:
        self._enqueued = enqueued

    def enqueue_from_candidates(self, payload, bando_ids):
        n = len(payload)
        return {
            "considered": n,
            "enqueued": self._enqueued,
            "already_present": 0,
            "not_required": n - self._enqueued,
        }


class _FakeLogRepo:
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
            "stato": "processing",
            "errore_tipo": None,
            "errore_stack": None,
        })
        return log_id

    def update_fonte_log_success(self, log_id, *, elapsed_ms, bandi_trovati, bandi_nuovi, bandi_aggiornati, bandi_invariati, ai_calls_count=0, ai_tokens_used=0):
        for e in self.fonte_logs:
            if e["id"] == log_id:
                e["stato"] = "completed"
                e["bandi_trovati"] = bandi_trovati

    def update_fonte_log_error(self, log_id, *, elapsed_ms, error_type, error_message, error_stack=None):
        for e in self.fonte_logs:
            if e["id"] == log_id:
                e["stato"] = "failed"
                e["errore_tipo"] = error_type
                e["errore_stack"] = error_stack


def _build_service(
    fonte_repo,
    scanner,
    *,
    bando_repo=None,
    ai_pipeline=None,
    classifier=None,
) -> tuple[BandoDiscoveryService, _FakeLogRepo, _FakeErrorRepo]:
    log_repo = _FakeLogRepo()
    error_repo = _FakeErrorRepo()
    service = BandoDiscoveryService()
    service.fonte_repo = fonte_repo
    service.bando_repo = bando_repo or _FakeBandoRepo()
    service.error_repo = error_repo
    service.log_repo = log_repo
    service.scanner = scanner
    service.classifier = classifier or SimpleNamespace(classify_candidates=lambda payload, fonte=None: payload)
    service.ai_pipeline = ai_pipeline or _FakeAiPipeline()
    service._create_log_entry = lambda *a, **kw: 1
    service._finalize_success = lambda *a, **kw: None
    service._finalize_error = lambda *a, **kw: None
    return service, log_repo, error_repo


def _noop_payload(candidates, scraping_log_id=None):
    return [
        {
            "hash_bando": c.hash_bando,
            "titolo": c.titolo,
            "link_bando": c.link_bando,
            "fonte_id": c.fonte_id,
            "raw_data": "{}",
        }
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# Test 1 — E2E fonte HTML: pipeline completa con 3 candidati
# ---------------------------------------------------------------------------

def test_e2e_fonte_html_pipeline_completa():
    """Fonte HTML produce 3 candidati, pipeline completa: log completed, 3 inserted."""
    fonti = [_Fonte(id=1, link="https://example.org/bandi-html", formato_link="HTML")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 3, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(1, i, "HTML") for i in range(3)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    service, log_repo, error_repo = _build_service(fonte_repo, scanner, bando_repo=bando_repo)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["fonti_scansionate"] == 1
    assert result["bandi_identificati"] == 3
    assert result["inserted"] == 3
    assert result["errori_fonti"] == 0
    log = log_repo.fonte_logs[0]
    assert log["stato"] == "completed"
    assert log["bandi_trovati"] == 3


# ---------------------------------------------------------------------------
# Test 2 — E2E fonte PDF: candidati con formato PDF correttamente propagato
# ---------------------------------------------------------------------------

def test_e2e_fonte_pdf_pipeline_completa():
    """Fonte PDF produce 2 candidati con formato_fonte=PDF; pipeline termina senza errori."""
    fonti = [_Fonte(id=2, link="https://example.org/avviso.pdf", formato_link="PDF")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 2, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(2, i, "PDF") for i in range(2)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    service, log_repo, _ = _build_service(fonte_repo, scanner, bando_repo=bando_repo)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["fonti_scansionate"] == 1
    assert result["bandi_identificati"] == 2
    assert result["inserted"] == 2
    assert result["errori_fonti"] == 0
    # il formato_fonte nei candidati deve essere PDF
    assert all(c.formato_fonte == "PDF" for c in candidates)
    assert log_repo.fonte_logs[0]["stato"] == "completed"


# ---------------------------------------------------------------------------
# Test 3 — E2E fonte PDF scansionato (OCR): raw_data contiene flag ocr_used
# ---------------------------------------------------------------------------

def test_e2e_fonte_pdf_scansionato_ocr():
    """Pipeline con candidato OCR: raw_data include ocr_used=True, log completed."""
    fonti = [_Fonte(id=3, link="https://example.org/scan.pdf", formato_link="PDF")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 1, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(3, 0, "PDF", ocr=True)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    captured_payloads: list[list[dict]] = []

    def _ocr_payload(cands, scraping_log_id=None):
        result = []
        for c in cands:
            entry = {
                "hash_bando": c.hash_bando,
                "titolo": c.titolo,
                "link_bando": c.link_bando,
                "fonte_id": c.fonte_id,
                "raw_data": '{"ocr_used": true}',
            }
            result.append(entry)
        captured_payloads.append(result)
        return result

    service, log_repo, _ = _build_service(fonte_repo, scanner, bando_repo=bando_repo)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _ocr_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["bandi_identificati"] == 1
    assert result["inserted"] == 1
    # verifica che il candidato abbia il flag OCR nel raw_data_obj
    assert candidates[0].raw_data_obj.get("ocr_used") is True
    assert log_repo.fonte_logs[0]["stato"] == "completed"


# ---------------------------------------------------------------------------
# Test 4 — E2E bando già esistente: upsert restituisce tutto unchanged
# ---------------------------------------------------------------------------

def test_e2e_bando_gia_esistente_unchanged():
    """Se il bando esiste già senza modifiche, l'upsert restituisce unchanged=N e inserted=0."""
    fonti = [_Fonte(id=4, link="https://example.org/esistente", formato_link="HTML")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 0, "updated": 0, "unchanged": 2})
    candidates = [_make_candidate(4, i) for i in range(2)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    service, log_repo, _ = _build_service(fonte_repo, scanner, bando_repo=bando_repo)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["unchanged"] == 2
    assert result["errori_fonti"] == 0
    assert log_repo.fonte_logs[0]["stato"] == "completed"


# ---------------------------------------------------------------------------
# Test 5 — E2E errore recuperabile: fonte va in stato pending
# ---------------------------------------------------------------------------

def test_e2e_errore_recuperabile_fonte_va_in_pending():
    """Un errore recuperabile sul scan deve portare la fonte a stato pending (< max_retry)."""
    fonte = _Fonte(id=5, link="https://example.org/lenta", formato_link="HTML", retry_count=0, max_retry=3)
    fonte_repo = _FakeFonteRepo([fonte])
    scanner = SimpleNamespace(
        scan_fonte=lambda f: (_ for _ in ()).throw(
            FonteLevel2Error("timeout", recoverable=True, http_status_code=504)
        )
    )

    service, log_repo, error_repo = _build_service(fonte_repo, scanner)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["errori_fonti"] == 1
    assert result["retry"]["fonti_pending"] == 1
    assert result["retry"]["fonti_failed_final"] == 0
    assert fonte.stato_processing == "pending"
    # nessun errore definitivo registrato
    assert len(error_repo.items) == 0
    assert log_repo.fonte_logs[0]["stato"] == "failed"
    assert "timeout" in log_repo.fonte_logs[0]["errore_tipo"].lower() or log_repo.fonte_logs[0]["errore_tipo"] == "FonteLevel2Error"


# ---------------------------------------------------------------------------
# Test 6 — E2E errore definitivo: failed_final dopo max_retry
# ---------------------------------------------------------------------------

def test_e2e_errore_definitivo_dopo_max_retry():
    """Errore recuperabile su fonte a retry_count == max_retry-1 → failed_final + errore definitivo."""
    fonte = _Fonte(id=6, link="https://example.org/rotta", formato_link="HTML", retry_count=2, max_retry=3)
    fonte_repo = _FakeFonteRepo([fonte])
    scanner = SimpleNamespace(
        scan_fonte=lambda f: (_ for _ in ()).throw(
            FonteLevel2Error("server error", recoverable=True, http_status_code=503)
        )
    )

    service, log_repo, error_repo = _build_service(fonte_repo, scanner)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["retry"]["fonti_failed_final"] == 1
    assert result["retry"]["errori_definitivi"] == 1
    assert fonte.stato_processing == "failed_final"
    # deve essere registrato un errore definitivo
    assert len(error_repo.items) == 1
    assert error_repo.items[0]["entity_type"] == "fonte"
    assert log_repo.fonte_logs[0]["stato"] == "failed"
    assert log_repo.fonte_logs[0]["errore_stack"] is not None


# ---------------------------------------------------------------------------
# Test 7 — E2E classificazione AI valida: payload arricchito con tipologia_bando_id
# ---------------------------------------------------------------------------

def test_e2e_classificazione_ai_valida_arricchisce_payload():
    """Il classificatore aggiunge tipologia_bando_id al payload; l'upsert riceve i dati arricchiti."""
    fonti = [_Fonte(id=7, link="https://example.org/bando-ai", formato_link="HTML")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 1, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(7, 0)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    enriched_flag: list[bool] = []

    def _fake_classify(payload, fonte=None):
        enriched = [dict(p, tipologia_bando_id=42) for p in payload]
        enriched_flag.append(True)
        return enriched

    classifier = SimpleNamespace(classify_candidates=_fake_classify)

    service, log_repo, _ = _build_service(fonte_repo, scanner, bando_repo=bando_repo, classifier=classifier)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert enriched_flag, "il classificatore non è stato chiamato"
    # il bando_repo deve aver ricevuto il payload arricchito
    assert bando_repo.upserted_payloads, "upsert non chiamato"
    upserted = bando_repo.upserted_payloads[0]
    assert len(upserted) == 1
    assert upserted[0].get("tipologia_bando_id") == 42
    assert result["inserted"] == 1


# ---------------------------------------------------------------------------
# Test 8 — E2E output AI non valido: campo non riconosciuto scartato dal classificatore
# ---------------------------------------------------------------------------

def test_e2e_output_ai_non_valido_scartato():
    """Se il classificatore riceve un valore non presente nel catalogo, non lo propaga nel payload."""
    fonti = [_Fonte(id=8, link="https://example.org/bando-ai-bad", formato_link="HTML")]
    fonte_repo = _FakeFonteRepo(fonti)
    bando_repo = _FakeBandoRepo(preset={"inserted": 1, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(8, 0)]
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    def _fake_classify_reject(payload, fonte=None):
        # Simula un classificatore che riceve "TipologiaInventata" dal modello AI
        # e non la propaga perché non è nel dizionario
        return [dict(p) for p in payload]  # ritorna senza aggiungere tipologia_bando_id

    classifier = SimpleNamespace(classify_candidates=_fake_classify_reject)

    service, log_repo, _ = _build_service(fonte_repo, scanner, bando_repo=bando_repo, classifier=classifier)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    assert result["errori_fonti"] == 0
    upserted = bando_repo.upserted_payloads[0]
    assert "tipologia_bando_id" not in upserted[0], (
        "un valore AI non valido non dovrebbe essere presente nel payload finale"
    )
    assert log_repo.fonte_logs[0]["stato"] == "completed"


# ---------------------------------------------------------------------------
# Test 9 — E2E pending → retry → successo
# ---------------------------------------------------------------------------

def test_e2e_pending_retry_successo():
    """
    Una fonte in stato pending (errore recuperabile precedente) viene ripresa
    dal run successivo, lo scan riesce, la fonte torna a ready e il log è completed.
    """
    # La fonte è già in pending con retry_count=1 (ha già fallito una volta)
    fonte = _Fonte(
        id=9,
        link="https://example.org/temporaneamente-down",
        formato_link="HTML",
        stato_processing="pending",
        retry_count=1,
        max_retry=3,
    )
    fonte_repo = _FakeFonteRepo([fonte])
    bando_repo = _FakeBandoRepo(preset={"inserted": 2, "updated": 0, "unchanged": 0})
    candidates = [_make_candidate(9, i) for i in range(2)]
    # Il secondo tentativo riesce: lo scanner non solleva eccezioni
    scanner = SimpleNamespace(scan_fonte=lambda f: candidates)

    service, log_repo, error_repo = _build_service(fonte_repo, scanner, bando_repo=bando_repo)

    original = service_module.candidates_to_upsert_payload
    service_module.candidates_to_upsert_payload = _noop_payload
    try:
        result = service.run()
    finally:
        service_module.candidates_to_upsert_payload = original

    # La pipeline deve completarsi senza errori
    assert result["errori_fonti"] == 0
    assert result["bandi_identificati"] == 2
    assert result["inserted"] == 2
    # La fonte deve essere tornata a ready con retry_count azzerato
    assert fonte.stato_processing == "ready"
    assert fonte.retry_count == 0
    # Nessun errore definitivo
    assert len(error_repo.items) == 0
    # Il log deve essere completed
    assert log_repo.fonte_logs[0]["stato"] == "completed"
    assert log_repo.fonte_logs[0]["bandi_trovati"] == 2
