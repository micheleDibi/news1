from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from app.ai.openai_classifier import OpenAiClassificationClient
from app.ai.quality_gate import run_gate3, run_title_gate
from app.config.settings import settings
from app.repos.base import AiJobQueueRepo, BandoRepo
from app.services.classification_service import ControlledClassificationService


@dataclass(frozen=True)
class AiQueueStats:
    considered: int = 0
    enqueued: int = 0
    already_present: int = 0
    not_required: int = 0


class AiPipelineService:
    """Pipeline AI asincrona: enqueue e worker con validazione su dizionario chiuso."""

    def __init__(
        self,
        bando_repo: BandoRepo | None = None,
        ai_repo: AiJobQueueRepo | None = None,
        classifier: ControlledClassificationService | None = None,
        ai_client: OpenAiClassificationClient | None = None,
    ) -> None:
        self.bando_repo = bando_repo or BandoRepo()
        self.ai_repo = ai_repo or AiJobQueueRepo()
        self.classifier = classifier or ControlledClassificationService()
        self.ai_client = ai_client or OpenAiClassificationClient()

    def enqueue_from_candidates(
        self,
        candidates: list[dict[str, Any]],
        bando_ids: list[int],
        progress_callback: Callable[[int, int, int, dict[str, int]], None] | None = None,
    ) -> dict[str, int]:
        considered = 0
        enqueued = 0
        already_present = 0
        not_required = 0
        skipped_title_gate = 0
        total = min(len(candidates), len(bando_ids))

        for idx, (candidate, bando_id) in enumerate(zip(candidates, bando_ids), start=1):
            considered += 1
            title_gate = run_title_gate(self._title_gate_payload(candidate))
            if not title_gate.pass_gate:
                self.bando_repo.set_ai_processing_flags(
                    int(bando_id),
                    required=False,
                    status="title_gate_skipped",
                    attempted=False,
                )
                skipped_title_gate += 1
                if progress_callback is not None:
                    progress_callback(
                        idx,
                        total,
                        int(bando_id),
                        {
                            "considered": considered,
                            "enqueued": enqueued,
                            "already_present": already_present,
                            "not_required": not_required,
                        },
                    )
                continue

                if title_gate.rewritten_title:
                    candidate = self._with_rewritten_title(candidate, title_gate.rewritten_title, title_gate)

            unresolved_fields = self._unresolved_fields(candidate)

            if not unresolved_fields:
                self.bando_repo.set_ai_processing_flags(
                    int(bando_id),
                    required=False,
                    status="not_required",
                )
                not_required += 1
                if progress_callback is not None:
                    progress_callback(
                        idx,
                        total,
                        int(bando_id),
                        {
                            "considered": considered,
                            "enqueued": enqueued,
                            "already_present": already_present,
                            "not_required": not_required,
                        },
                    )
                continue

            job_payload = self._build_job_payload(candidate, bando_id=int(bando_id), unresolved_fields=unresolved_fields)
            enqueue_result = self.ai_repo.enqueue_classification_job(int(bando_id), job_payload)

            self.bando_repo.set_ai_processing_flags(
                int(bando_id),
                required=True,
                status="queued",
            )

            if enqueue_result.get("enqueued"):
                enqueued += 1
            else:
                already_present += 1

            if progress_callback is not None:
                progress_callback(
                    idx,
                    total,
                    int(bando_id),
                    {
                        "considered": considered,
                        "enqueued": enqueued,
                        "already_present": already_present,
                        "not_required": not_required,
                    },
                )

        return {
            "considered": considered,
            "enqueued": enqueued,
            "already_present": already_present,
            "not_required": not_required,
            "skipped_title_gate": skipped_title_gate,
        }

    def enqueue_from_existing_bandi(
        self,
        limit: int | None = None,
        progress_callback: Callable[[int, int, int, dict[str, int]], None] | None = None,
    ) -> dict[str, int]:
        candidates = self.bando_repo.get_candidates_for_ai_enqueue(limit=limit)
        if not candidates:
            return {
                "considered": 0,
                "enqueued": 0,
                "already_present": 0,
                "not_required": 0,
                "skipped_title_gate": 0,
            }

        normalized_candidates: list[dict[str, Any]] = []
        bando_ids: list[int] = []
        for row in candidates:
            bando_ids.append(int(row["id"]))
            normalized_candidates.append(
                {
                    "titolo": row.get("titolo"),
                    "descrizione": row.get("descrizione"),
                    "codice_bando": row.get("codice_bando"),
                    "fondo": row.get("fondo"),
                    "link_bando": row.get("link_bando"),
                    "raw_data_obj": row.get("raw_data") or {},
                    "data_extra": row.get("data_extra") or {},
                    "tipologia_bando_id": row.get("tipologia_bando_id"),
                    "modalita_erogazione_id": row.get("modalita_erogazione_id"),
                    "programma_id": row.get("programma_id"),
                    "is_bando_confermato": row.get("is_bando_confermato"),
                }
            )

        return self.enqueue_from_candidates(
            normalized_candidates,
            bando_ids,
            progress_callback=progress_callback,
        )

    def process_queue(
        self,
        *,
        limit: int = 10,
        progress_callback: Callable[[int, int, int, int], None] | None = None,
        inter_call_delay_s: float = 0.0,
    ) -> dict[str, int]:
        claimed_jobs = self.ai_repo.claim_jobs(limit=limit)
        if not claimed_jobs:
            return {
                "claimed": 0,
                "completed": 0,
                "failed": 0,
                "discarded_payloads": 0,
                "skipped_title_gate": 0,
            }

        completed = 0
        failed = 0
        discarded_payloads = 0
        skipped_title_gate = 0

        validator = self.classifier.build_ai_validator()
        total_jobs = len(claimed_jobs)
        for idx, job in enumerate(claimed_jobs, start=1):
            job_id = int(job["id"])
            bando_id = int(job["bando_id"])
            payload = job.get("payload") or {}

            if progress_callback is not None:
                progress_callback(idx, total_jobs, job_id, bando_id)

            try:
                title_gate = run_title_gate(self._title_gate_payload(payload.get("contesto") or payload))
                if not title_gate.pass_gate:
                    discarded_payloads += 1
                    skipped_title_gate += 1
                    discarded = {"title_gate": title_gate.discard_reason, "warnings": title_gate.warnings}
                    self.bando_repo.set_ai_processing_flags(
                        bando_id,
                        required=False,
                        status="title_gate_skipped",
                        attempted=True,
                    )
                    self.ai_repo.log_discarded_classification(
                        bando_id=bando_id,
                        ai_job_id=job_id,
                        discarded_payload=discarded,
                    )
                    self.ai_repo.complete_job(
                        job_id,
                        {
                            "raw_output": {},
                            "validated_output": {},
                            "discarded_output": discarded,
                            "apply_result": {"applied": False, "changed_fields": []},
                            "gate3": {
                                "ai_applied_fields": [],
                                "ai_rejected_fields": [],
                                "ai_reject_reasons": {},
                                "quality_delta": 0,
                            },
                            "title_gate": {
                                "pass_gate": False,
                                "discard_reason": title_gate.discard_reason,
                                "warnings": title_gate.warnings,
                                "score": title_gate.score,
                                "rewritten_title": title_gate.rewritten_title,
                                "rewrite_source": title_gate.rewrite_source,
                            },
                        },
                    )
                    completed += 1
                    continue

                if title_gate.rewritten_title:
                    payload = self._with_rewritten_title(payload, title_gate.rewritten_title, title_gate)

                raw_ai_output = self.ai_client.classify(payload)
                validated = validator.validate(raw_ai_output)
                unresolved_fields = payload.get("unresolved_fields") or []
                if (
                    "is_bando_confermato" in unresolved_fields
                    and validated.get("is_bando_confermato") is None
                ):
                    # Fallback conservativo per chiudere i NULL residui su classificazione binaria.
                    validated["is_bando_confermato"] = False
                discarded = _extract_discarded(raw_ai_output, validated)
                gate3 = run_gate3(raw_ai_output, validated)

                apply_result = self.bando_repo.apply_ai_classification(
                    bando_id,
                    validated,
                    ai_job_id=job_id,
                )

                if discarded:
                    self.ai_repo.log_discarded_classification(
                        bando_id=bando_id,
                        ai_job_id=job_id,
                        discarded_payload=discarded,
                    )
                    discarded_payloads += 1

                self.ai_repo.complete_job(
                    job_id,
                    {
                        "raw_output": raw_ai_output,
                        "validated_output": validated,
                        "discarded_output": discarded,
                        "apply_result": apply_result,
                        "title_gate": {
                            "pass_gate": True,
                            "discard_reason": None,
                            "warnings": title_gate.warnings,
                            "score": title_gate.score,
                            "rewritten_title": title_gate.rewritten_title,
                            "rewrite_source": title_gate.rewrite_source,
                        },
                        "gate3": {
                            "ai_applied_fields": gate3.ai_applied_fields,
                            "ai_rejected_fields": gate3.ai_rejected_fields,
                            "ai_reject_reasons": gate3.ai_reject_reasons,
                            "quality_delta": gate3.quality_delta,
                        },
                    },
                )
                completed += 1
                if inter_call_delay_s > 0 and idx < total_jobs:
                    time.sleep(inter_call_delay_s)
            except Exception as exc:
                retry_state = self.ai_repo.fail_job(
                    job_id,
                    errore_tipo=exc.__class__.__name__,
                    errore_messaggio=str(exc),
                    retry_delay_seconds=settings.scraper_retry_delay_seconds,
                )
                bando_status = "failed" if retry_state.get("stato") == "failed" else "queued"
                self.bando_repo.set_ai_processing_flags(
                    bando_id,
                    required=True,
                    status=bando_status,
                    attempted=True,
                )
                failed += 1

        return {
            "claimed": len(claimed_jobs),
            "completed": completed,
            "failed": failed,
            "discarded_payloads": discarded_payloads,
            "skipped_title_gate": skipped_title_gate,
        }

    def _build_job_payload(
        self,
        candidate: dict[str, Any],
        *,
        bando_id: int,
        unresolved_fields: list[str],
    ) -> dict[str, Any]:
        ai_fallback = self.classifier.prepare_ai_fallback_payload(unresolved_fields)
        context = {
            "bando_id": bando_id,
            "titolo": candidate.get("titolo"),
            "descrizione": candidate.get("descrizione"),
            "codice_bando": candidate.get("codice_bando"),
            "fondo": candidate.get("fondo"),
            "link_bando": candidate.get("link_bando"),
            "raw_data": candidate.get("raw_data_obj") or {},
            "metadati": candidate.get("data_extra") or {},
        }
        return {
            "contesto": context,
            "unresolved_fields": unresolved_fields,
            "allowed_values": ai_fallback.get("allowed_values", {}),
            "mode": ai_fallback.get("mode"),
        }

    @staticmethod
    def _title_gate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
        context = candidate.get("contesto") if isinstance(candidate, dict) else None
        if isinstance(context, dict):
            base = dict(context)
            base["raw_data"] = base.get("raw_data") or {}
            return base
        return candidate if isinstance(candidate, dict) else {}

    @staticmethod
    def _with_rewritten_title(candidate: dict[str, Any], rewritten_title: str, title_gate: Any) -> dict[str, Any]:
        updated = dict(candidate)
        updated["titolo"] = rewritten_title
        if "contesto" in updated and isinstance(updated["contesto"], dict):
            context = dict(updated["contesto"])
            context["titolo"] = rewritten_title
            context["title_gate"] = {
                "pass_gate": True,
                "discard_reason": None,
                "warnings": getattr(title_gate, "warnings", []),
                "score": getattr(title_gate, "score", 0),
                "rewritten_title": rewritten_title,
                "rewrite_source": getattr(title_gate, "rewrite_source", None),
            }
            updated["contesto"] = context
        else:
            updated["title_gate"] = {
                "pass_gate": True,
                "discard_reason": None,
                "warnings": getattr(title_gate, "warnings", []),
                "score": getattr(title_gate, "score", 0),
                "rewritten_title": rewritten_title,
                "rewrite_source": getattr(title_gate, "rewrite_source", None),
            }
        return updated

    @staticmethod
    def _unresolved_fields(candidate: dict[str, Any]) -> list[str]:
        unresolved: list[str] = []

        # is_bando_confermato è sempre richiesto finché non classificato dall'AI.
        if candidate.get("is_bando_confermato") is None:
            unresolved.append("is_bando_confermato")

        single_fields = [
            "tipologia_bando_id",
            "modalita_erogazione_id",
            "programma_id",
        ]
        for field in single_fields:
            if candidate.get(field) is None:
                unresolved.append(field)

        list_fields = [
            "regione_ids",
            "settore_ids",
            "beneficiario_ids",
            "codice_ateco_ids",
        ]
        for field in list_fields:
            value = candidate.get(field)
            if not value:
                unresolved.append(field)
        return unresolved


def _extract_discarded(raw_output: dict[str, Any], validated_output: dict[str, Any]) -> dict[str, Any]:
    discarded: dict[str, Any] = {}
    for key, raw_value in (raw_output or {}).items():
        if key not in validated_output:
            discarded[key] = raw_value
            continue
        if validated_output.get(key) != raw_value:
            discarded[key] = raw_value
    return discarded