"""
Milestone 7 — Test pipeline AI asincrona

Coprono i 5 casi definiti nel WP:
  - Test enqueue job AI
  - Test worker su caso semplice
  - Test rifiuto output non valido
  - Test idempotenza job AI
  - Test classificazione solo da dizionario esistente
"""
from __future__ import annotations

from typing import Any

from app.ai.quality_gate import run_title_gate
from app.ai.output_validator import AiClassificationOutputValidator, AllowedValue
from app.services.ai_pipeline_service import AiPipelineService


# ---------------------------------------------------------------------------
# Fake repos condivisi
# ---------------------------------------------------------------------------


class _FakeAiRepo:
    def __init__(
        self,
        jobs: list[dict[str, Any]] | None = None,
        enqueue_result: dict[str, Any] | None = None,
    ) -> None:
        self._jobs = jobs or []
        self._enqueue_result = enqueue_result if enqueue_result is not None else {"enqueued": True}
        self.completed_jobs: list[tuple[int, dict]] = []
        self.failed_jobs: list[int] = []
        self.discarded_logs: list[dict] = []
        self.enqueued_jobs: list[tuple[int, dict]] = []

    def claim_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._jobs[:limit]

    def complete_job(self, job_id: int, response: dict[str, Any]) -> None:
        self.completed_jobs.append((job_id, response))

    def fail_job(
        self,
        job_id: int,
        *,
        errore_tipo: str,
        errore_messaggio: str,
        retry_delay_seconds: int,
    ) -> dict[str, Any]:
        self.failed_jobs.append(job_id)
        return {"stato": "failed"}

    def enqueue_classification_job(self, bando_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.enqueued_jobs.append((bando_id, payload))
        return self._enqueue_result

    def log_discarded_classification(
        self,
        *,
        bando_id: int,
        ai_job_id: int,
        discarded_payload: dict[str, Any],
    ) -> None:
        self.discarded_logs.append(
            {"bando_id": bando_id, "ai_job_id": ai_job_id, "discarded": discarded_payload}
        )


class _FakeBandoRepo:
    def __init__(self) -> None:
        self.flags: list[dict] = []
        self.applied: list[dict] = []

    def set_ai_processing_flags(
        self,
        bando_id: int,
        *,
        required: bool,
        status: str,
        attempted: bool = False,
    ) -> None:
        self.flags.append({"bando_id": bando_id, "required": required, "status": status})

    def apply_ai_classification(
        self,
        bando_id: int,
        validated: dict[str, Any],
        ai_job_id: int | None = None,
    ) -> dict[str, Any]:
        self.applied.append({"bando_id": bando_id, "validated": validated})
        return {"applied": bool(validated)}


class _FakeClassifier:
    """Classifier con dizionario controllato configurabile."""

    def __init__(self, allowed_ids: dict[str, list[int]] | None = None) -> None:
        self._allowed_ids = allowed_ids or {"tipologia_bando_id": [1, 2, 3]}

    def build_ai_validator(self) -> AiClassificationOutputValidator:
        avs = {
            field: [AllowedValue(id=av_id, label=f"Label {av_id}") for av_id in ids]
            for field, ids in self._allowed_ids.items()
        }
        return AiClassificationOutputValidator(avs)

    def prepare_ai_fallback_payload(self, unresolved_fields: list[str]) -> dict[str, Any]:
        return {"allowed_values": {f: [] for f in unresolved_fields}, "mode": "strict"}


class _FakeAiClient:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response or {}
        self.calls: list[dict[str, Any]] = []

    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        return self._response


def _make_candidate_with_missing_fields() -> dict[str, Any]:
    """Candidato con tutti i campi di classificazione mancanti."""
    return {
        "titolo": "Bando test enqueue",
        "descrizione": "Descrizione del bando di test",
        "codice_bando": None,
        "fondo": None,
        "link_bando": "https://example.org/bando-test",
        "tipologia_bando_id": None,
        "modalita_erogazione_id": None,
        "programma_id": None,
        "regione_ids": [],
        "settore_ids": [],
        "beneficiario_ids": [],
        "codice_ateco_ids": [],
        "raw_data_obj": {},
        "data_extra": {},
    }


def _make_candidate_fully_classified() -> dict[str, Any]:
    """Candidato con tutti i campi di classificazione già valorizzati."""
    return {
        "titolo": "Bando già classificato",
        "link_bando": "https://example.org/bando-classificato",
        "tipologia_bando_id": 1,
        "modalita_erogazione_id": 1,
        "programma_id": 1,
        "regione_ids": [1],
        "settore_ids": [1],
        "beneficiario_ids": [1],
        "codice_ateco_ids": [1],
        "raw_data_obj": {},
        "data_extra": {},
    }


# ---------------------------------------------------------------------------
# Test 1 — Enqueue job AI
# ---------------------------------------------------------------------------


def test_enqueue_job_ai():
    """Un candidato con campi di classificazione mancanti viene accodato nella coda AI."""
    ai_repo = _FakeAiRepo(enqueue_result={"enqueued": True})
    bando_repo = _FakeBandoRepo()
    classifier = _FakeClassifier()

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
    )

    candidates = [_make_candidate_with_missing_fields()]
    bando_ids = [42]

    result = service.enqueue_from_candidates(candidates, bando_ids)

    assert result["considered"] == 1
    assert result["enqueued"] == 1
    assert result["not_required"] == 0
    assert result["already_present"] == 0
    assert len(ai_repo.enqueued_jobs) == 1
    assert ai_repo.enqueued_jobs[0][0] == 42  # bando_id corretto
    # Il flag AI deve essere impostato a "queued"
    assert any(f["status"] == "queued" for f in bando_repo.flags)


def test_title_gate_tollera_raw_data_non_dict():
    """Il title gate non deve crashare quando raw_data arriva come lista o JSON non-oggetto."""
    result_list = run_title_gate(
        {
            "titolo": "Avviso contributi imprese innovative",
            "descrizione": "Avviso contributi imprese innovative Regione X",
            "link_bando": "https://example.org/avviso-contributi-imprese-innovative",
            "raw_data_obj": [],
        }
    )
    result_json_array = run_title_gate(
        {
            "titolo": "Avviso contributi imprese innovative",
            "descrizione": "Avviso contributi imprese innovative Regione X",
            "link_bando": "https://example.org/avviso-contributi-imprese-innovative",
            "raw_data": "[]",
        }
    )

    assert isinstance(result_list.pass_gate, bool)
    assert isinstance(result_json_array.pass_gate, bool)


# ---------------------------------------------------------------------------
# Test 2 — Worker su caso semplice
# ---------------------------------------------------------------------------


def test_worker_su_caso_semplice():
    """Il worker AI applica una classificazione valida su un job semplice."""
    job = {"id": 1, "bando_id": 42, "payload": {"contesto": {"titolo": "Bando test"}}}
    ai_repo = _FakeAiRepo(jobs=[job])
    bando_repo = _FakeBandoRepo()
    # tipologia_bando_id: 2 è nel dizionario → deve essere applicato
    classifier = _FakeClassifier(allowed_ids={"tipologia_bando_id": [1, 2, 3]})
    ai_client = _FakeAiClient(response={"tipologia_bando_id": 2})

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
        ai_client=ai_client,
    )

    result = service.process_queue(limit=10)

    assert result["claimed"] == 1
    assert result["completed"] == 1
    assert result["failed"] == 0
    assert result["discarded_payloads"] == 0
    # La classificazione valida deve essere applicata
    assert len(bando_repo.applied) == 1
    assert bando_repo.applied[0]["validated"] == {"tipologia_bando_id": 2}
    # Il job deve essere completato con gate3 nel response
    assert len(ai_repo.completed_jobs) == 1
    _job_id, response = ai_repo.completed_jobs[0]
    assert "gate3" in response
    assert response["gate3"]["ai_applied_fields"] == ["tipologia_bando_id"]
    assert response["gate3"]["ai_rejected_fields"] == []
    assert response["gate3"]["quality_delta"] == 0  # nessun gate2 passato


def test_worker_salta_titolo_generico_prima_dell_ai():
    """Il worker non chiama OpenAI se il titolo è generico e incoerente con il contesto."""
    job = {
        "id": 11,
        "bando_id": 501,
        "payload": {
            "contesto": {
                "titolo": "Bandi e Gare",
                "descrizione": "Bandi e Gare",
                "link_bando": "https://example.org/bandi",
                "raw_data": {
                    "page_content_snippet_300": "Bandi e Gare | Cerca dipartimento | Home",
                },
            },
            "unresolved_fields": ["tipologia_bando_id", "is_bando_confermato"],
        },
    }
    ai_repo = _FakeAiRepo(jobs=[job])
    bando_repo = _FakeBandoRepo()
    classifier = _FakeClassifier(allowed_ids={"tipologia_bando_id": [1, 2, 3]})
    ai_client = _FakeAiClient(response={"tipologia_bando_id": 2})

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
        ai_client=ai_client,
    )

    result = service.process_queue(limit=10)

    assert result["claimed"] == 1
    assert result["completed"] == 1
    assert result["failed"] == 0
    assert result["discarded_payloads"] == 1
    assert result["skipped_title_gate"] == 1
    assert len(ai_client.calls) == 0
    assert len(bando_repo.applied) == 0
    assert len(ai_repo.discarded_logs) == 1
    assert ai_repo.completed_jobs[0][1]["title_gate"]["pass_gate"] is False


def test_worker_riformula_titolo_generico_prima_dell_ai():
    """Se il titolo è generico ma il contesto è ricco, il worker lo riformula prima della classifica."""
    rewritten_title = "Avviso pubblico per la concessione di contributi alle imprese innovative"
    job = {
        "id": 12,
        "bando_id": 502,
        "payload": {
            "contesto": {
                "titolo": "Bandi e Gare",
                "descrizione": rewritten_title,
                "link_bando": "https://example.org/bandi/contributi-imprese-innovative",
                "raw_data": {
                    "page_content_snippet_300": f"{rewritten_title} | Regione X | Scadenza 30/09/2026",
                },
            },
            "unresolved_fields": ["tipologia_bando_id", "is_bando_confermato"],
        },
    }
    ai_repo = _FakeAiRepo(jobs=[job])
    bando_repo = _FakeBandoRepo()
    classifier = _FakeClassifier(allowed_ids={"tipologia_bando_id": [1, 2, 3]})
    ai_client = _FakeAiClient(response={"tipologia_bando_id": 2})

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
        ai_client=ai_client,
    )

    result = service.process_queue(limit=10)

    assert result["claimed"] == 1
    assert result["completed"] == 1
    assert result["failed"] == 0
    assert result["discarded_payloads"] == 0
    assert result["skipped_title_gate"] == 0
    assert len(ai_client.calls) == 1
    assert ai_client.calls[0]["contesto"]["titolo"] == rewritten_title
    assert len(bando_repo.applied) == 1
    assert ai_repo.completed_jobs[0][1]["title_gate"]["rewritten_title"] == rewritten_title


# ---------------------------------------------------------------------------
# Test 3 — Rifiuto output non valido
# ---------------------------------------------------------------------------


def test_rifiuto_output_non_valido():
    """L'output AI con valori fuori dizionario viene scartato e loggato."""
    job = {"id": 2, "bando_id": 99, "payload": {}}
    ai_repo = _FakeAiRepo(jobs=[job])
    bando_repo = _FakeBandoRepo()
    # 999 NON è nel dizionario consentito [1, 2, 3]
    classifier = _FakeClassifier(allowed_ids={"tipologia_bando_id": [1, 2, 3]})
    ai_client = _FakeAiClient(response={"tipologia_bando_id": 999})

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
        ai_client=ai_client,
    )

    result = service.process_queue(limit=10)

    assert result["completed"] == 1
    assert result["failed"] == 0
    # L'output invalido deve essere contato come scartato
    assert result["discarded_payloads"] == 1
    # Il log dello scarto deve essere presente
    assert len(ai_repo.discarded_logs) == 1


def test_worker_fallback_is_bando_false_quando_mancante():
    """Se is_bando_confermato è unresolved ma manca nell'output AI, fallback a False."""
    job = {
        "id": 3,
        "bando_id": 77,
        "payload": {
            "contesto": {"titolo": "Pagina generica"},
            "unresolved_fields": ["is_bando_confermato"],
        },
    }
    ai_repo = _FakeAiRepo(jobs=[job])
    bando_repo = _FakeBandoRepo()
    classifier = _FakeClassifier(allowed_ids={"tipologia_bando_id": [1, 2, 3]})
    ai_client = _FakeAiClient(response={})

    service = AiPipelineService(
        bando_repo=bando_repo,
        ai_repo=ai_repo,
        classifier=classifier,
        ai_client=ai_client,
    )

    result = service.process_queue(limit=10)

    assert result["claimed"] == 1
    assert result["completed"] == 1
    assert len(bando_repo.applied) == 1
    assert bando_repo.applied[0]["validated"].get("is_bando_confermato") is False


# ---------------------------------------------------------------------------
# Test 4 — Idempotenza job AI
# ---------------------------------------------------------------------------


def test_idempotenza_job_ai():
    """Accodare due volte lo stesso bando incrementa already_present, non crea duplicati."""
    bando_repo = _FakeBandoRepo()
    classifier = _FakeClassifier()
    candidates = [_make_candidate_with_missing_fields()]
    bando_ids = [77]

    # Prima chiamata: job accodato
    ai_repo_first = _FakeAiRepo(enqueue_result={"enqueued": True})
    service1 = AiPipelineService(bando_repo=bando_repo, ai_repo=ai_repo_first, classifier=classifier)
    result1 = service1.enqueue_from_candidates(candidates, bando_ids)

    assert result1["enqueued"] == 1
    assert result1["already_present"] == 0

    # Seconda chiamata: job già presente
    ai_repo_second = _FakeAiRepo(enqueue_result={"enqueued": False})
    service2 = AiPipelineService(bando_repo=bando_repo, ai_repo=ai_repo_second, classifier=classifier)
    result2 = service2.enqueue_from_candidates(candidates, bando_ids)

    assert result2["enqueued"] == 0
    assert result2["already_present"] == 1
    # In totale 2 chiamate a enqueue_classification_job, non uno solo
    assert len(ai_repo_second.enqueued_jobs) == 1  # la seconda chiamata ha un solo job


# ---------------------------------------------------------------------------
# Test 5 — Classificazione solo da dizionario esistente
# ---------------------------------------------------------------------------


def test_classificazione_solo_da_dizionario_esistente():
    """Il validator AI accetta solo valori presenti nel dizionario chiuso del DB."""
    validator = AiClassificationOutputValidator(
        allowed_values={
            "tipologia_bando_id": [
                AllowedValue(id=1, label="Bando europeo"),
                AllowedValue(id=2, label="Bando nazionale"),
            ],
            "programma_id": [
                AllowedValue(id=10, label="FESR Campania"),
            ],
        }
    )

    # Valori validi → applicati
    result_ok = validator.validate({"tipologia_bando_id": 1, "programma_id": 10})
    assert result_ok == {"tipologia_bando_id": 1, "programma_id": 10}

    # Valori fuori dizionario → scartati
    result_ko = validator.validate({"tipologia_bando_id": 999, "programma_id": 42})
    assert result_ko == {}

    # Mix: uno valido, uno no → solo quello valido
    result_mixed = validator.validate({"tipologia_bando_id": 2, "programma_id": 99})
    assert result_mixed == {"tipologia_bando_id": 2}

    # Campo non previsto nel dizionario → scartato
    result_unknown = validator.validate({"campo_ignoto": 1})
    assert result_unknown == {}

    # Riconoscimento per label (case-insensitive)
    result_label = validator.validate({"tipologia_bando_id": "Bando europeo"})
    assert result_label == {"tipologia_bando_id": 1}
