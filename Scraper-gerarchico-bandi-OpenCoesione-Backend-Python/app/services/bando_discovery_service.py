from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ai.quality_gate import run_gate2, run_gate4
from app.config.settings import settings
from app.config.session import get_session_id, new_session_id
from app.db.connection import get_db_connection
from app.repos.base import BandoRepo, FonteRepo, ScrapingErrorRepo, ScrapingLogRepo
from app.services.ai_pipeline_service import AiPipelineService
from app.services.classification_service import ControlledClassificationService
from app.scrapers.fonte_level2 import FonteLevel2Error, FonteLevel2Scanner, candidates_to_upsert_payload


logger = logging.getLogger(__name__)


class BandoDiscoveryService:
    def __init__(self) -> None:
        self.fonte_repo = FonteRepo()
        self.bando_repo = BandoRepo()
        self.error_repo = ScrapingErrorRepo()
        self.log_repo = ScrapingLogRepo()
        self.scanner = FonteLevel2Scanner()
        self.classifier = ControlledClassificationService()
        self.ai_pipeline = AiPipelineService(
            bando_repo=self.bando_repo,
            classifier=self.classifier,
        )

    def run(self, limit: int | None = None) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        session_id = get_session_id() or new_session_id()
        log_id = self._create_log_entry(str(session_id), started_at, limit)

        total_candidates = 0
        errors = 0
        retry_totals = {
            "fonti_pending": 0,
            "fonti_failed_final": 0,
            "bandi_pending": 0,
            "bandi_failed_final": 0,
            "errori_definitivi": 0,
        }
        upsert_totals = {"processed": 0, "inserted": 0, "updated": 0, "unchanged": 0}
        ai_totals = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": 0}
        page_fetch_totals = {"attempted": 0, "failed": 0}
        quality_totals: dict[str, Any] = {
            "gate4_checked": 0,
            "gate4_discarded": 0,
            "with_descrizione": 0,
            "with_missing_fields": 0,
            "gate1_low_quality_retried": 0,
            "gate1_low_quality_ocr_flagged": 0,
        }

        try:
            fonti = self.fonte_repo.get_all_active_with_limit(limit=limit)
            total_fonti = len(fonti)
            for idx, fonte in enumerate(fonti, start=1):
                fonte_started_at = datetime.now(timezone.utc)
                fonte_t0 = time.perf_counter()
                logger.info(
                    "Progress fonte %s/%s (fonte_id=%s, url=%s)",
                    idx,
                    total_fonti,
                    int(fonte.id),
                    fonte.link,
                )
                fonte_log_id = self.log_repo.create_fonte_log_entry(
                    str(session_id),
                    log_id,
                    int(fonte.id),
                    fonte.link,
                    fonte_started_at,
                )
                self.fonte_repo.mark_processing_started(int(fonte.id))
                try:
                    candidates = self.scanner.scan_fonte(fonte)
                    total_candidates += len(candidates)

                    payload: list[dict[str, Any]] = []
                    for candidate in candidates:
                        page_fetch_totals["attempted"] += 1
                        try:
                            candidate_payload = candidates_to_upsert_payload([candidate], scraping_log_id=fonte_log_id)
                            if candidate_payload:
                                raw_data_obj = candidate_payload[0].get("raw_data_obj") or {}
                                if raw_data_obj.get("fetch_error"):
                                    page_fetch_totals["failed"] += 1
                                payload.append(candidate_payload[0])
                        except Exception as candidate_exc:  # noqa: BLE001
                            errors += 1
                            recoverable = self._is_recoverable_error(candidate_exc)
                            bando_result = self.bando_repo.register_processing_error_by_hash(
                                candidate.hash_bando,
                                error_type=candidate_exc.__class__.__name__,
                                error_message=str(candidate_exc),
                                recoverable=recoverable,
                                retry_delay_seconds=settings.scraper_retry_delay_seconds,
                            )
                            self._accumulate_bando_retry_stats(
                                retry_totals,
                                bando_result,
                                session_id=str(session_id),
                                scraping_log_id=fonte_log_id,
                                source="candidate_parse",
                                source_url=getattr(fonte, "link", None),
                                error=candidate_exc,
                            )

                    payload = self.classifier.classify_candidates(payload, fonte=fonte)

                    # Gate 2 + Gate 4: qualità post-classificazione
                    filtered_payload: list[dict[str, Any]] = []
                    for item in payload:
                        gate2 = run_gate2(item)
                        item["quality_gate2"] = gate2
                        quality_totals["gate4_checked"] += 1
                        if gate2.missing_fields:
                            quality_totals["with_missing_fields"] += 1
                        desc = item.get("descrizione")
                        if desc and len(str(desc).strip()) >= 30:
                            quality_totals["with_descrizione"] += 1
                        gate4 = run_gate4(item, gate1=item.get("quality_gate1"))
                        item["quality_gate4"] = gate4
                        if gate4.pass_gate:
                            filtered_payload.append(item)
                        else:
                            quality_totals["gate4_discarded"] += 1
                            self.error_repo.insert_definitive_error(
                                session_id=str(session_id),
                                scraping_log_id=fonte_log_id,
                                fonte_id=int(fonte.id),
                                entity_type="bando",
                                entity_url=item.get("link_bando"),
                                errore_tipo="QualityGate4Discard",
                                errore_messaggio=gate4.discard_reason or "gate4_failed",
                                retry_count=0,
                                contesto={"gate4_reason": gate4.discard_reason},
                            )
                    payload = filtered_payload

                    stats = self.bando_repo.upsert_candidates(payload)
                    for key in upsert_totals:
                        upsert_totals[key] += int(stats.get(key, 0))

                    # Gate 1 action: retry HTML o flag OCR per estrazioni a bassa qualità
                    fonte_format = (getattr(fonte, "formato_link", None) or "HTML").upper()
                    for item in payload:
                        gate1 = item.get("quality_gate1")
                        if gate1 is None or gate1.extraction_status != "low_quality":
                            continue
                        if fonte_format in ("HTML", "CSV"):
                            self.bando_repo.register_processing_error_by_hash(
                                item["hash_bando"],
                                error_type="Gate1LowQuality",
                                error_message="Estrazione bassa qualità: " + ", ".join(gate1.extraction_warnings),
                                recoverable=True,
                                retry_delay_seconds=settings.scraper_retry_delay_seconds,
                            )
                            quality_totals["gate1_low_quality_retried"] += 1
                        elif fonte_format in ("PDF", "ZIP"):
                            existing_extra = item.get("data_extra") or {}
                            item["data_extra"] = {**existing_extra, "force_ocr": True}
                            quality_totals["gate1_low_quality_ocr_flagged"] += 1

                    # v4: AI pipeline pre-skill deprecata. I bandi vanno direttamente
                    # in stato `discovered`, drenati dal sender (skill autoritativa).
                    ai_stats = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": int(stats.get("inserted", 0)) + int(stats.get("updated", 0))}
                    for key in ai_totals:
                        ai_totals[key] += int(ai_stats.get(key, 0))

                    self.fonte_repo.mark_processing_success(int(fonte.id))
                    fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
                    self.log_repo.update_fonte_log_success(
                        fonte_log_id,
                        elapsed_ms=fonte_elapsed_ms,
                        bandi_trovati=len(candidates),
                        bandi_nuovi=int(stats.get("inserted", 0)),
                        bandi_aggiornati=int(stats.get("updated", 0)),
                        bandi_invariati=int(stats.get("unchanged", 0)),
                        ai_calls_count=int(ai_stats.get("enqueued", 0)),
                    )
                    logger.debug(
                        "Fonte completata %s/%s (fonte_id=%s): candidati=%s, insert=%s, update=%s, unchanged=%s, ai_enqueued=%s, elapsed_ms=%s",
                        idx,
                        total_fonti,
                        int(fonte.id),
                        len(candidates),
                        int(stats.get("inserted", 0)),
                        int(stats.get("updated", 0)),
                        int(stats.get("unchanged", 0)),
                        int(ai_stats.get("enqueued", 0)),
                        fonte_elapsed_ms,
                    )
                except FonteLevel2Error as exc:
                    errors += 1
                    fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
                    self.log_repo.update_fonte_log_error(
                        fonte_log_id,
                        elapsed_ms=fonte_elapsed_ms,
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                        error_stack=traceback.format_exc(),
                    )
                    retry_info = self.fonte_repo.register_processing_error(
                        int(fonte.id),
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                        recoverable=bool(getattr(exc, "recoverable", True)),
                        retry_delay_seconds=settings.scraper_retry_delay_seconds,
                    )
                    self._accumulate_fonte_retry_stats(
                        retry_totals,
                        retry_info,
                        session_id=str(session_id),
                        scraping_log_id=fonte_log_id,
                        fonte_id=int(fonte.id),
                        http_status_code=getattr(exc, "http_status_code", None),
                        source="scan_fonte",
                        error=exc,
                    )
                    logger.warning(
                        "Fonte errore %s/%s (fonte_id=%s): %s",
                        idx,
                        total_fonti,
                        int(fonte.id),
                        str(exc),
                    )
                    continue
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
                    self.log_repo.update_fonte_log_error(
                        fonte_log_id,
                        elapsed_ms=fonte_elapsed_ms,
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                        error_stack=traceback.format_exc(),
                    )
                    retry_info = self.fonte_repo.register_processing_error(
                        int(fonte.id),
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                        recoverable=self._is_recoverable_error(exc),
                        retry_delay_seconds=settings.scraper_retry_delay_seconds,
                    )
                    self._accumulate_fonte_retry_stats(
                        retry_totals,
                        retry_info,
                        session_id=str(session_id),
                        scraping_log_id=fonte_log_id,
                        fonte_id=int(fonte.id),
                        source="generic_fonte_processing",
                        error=exc,
                    )
                    logger.exception(
                        "Fonte errore inatteso %s/%s (fonte_id=%s)",
                        idx,
                        total_fonti,
                        int(fonte.id),
                    )
                    continue

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            try:
                ai_delta_sum = self.ai_pipeline.ai_repo.get_recent_quality_delta_sum(since_hours=24)
                quality_totals["ai_quality_delta_sum"] = ai_delta_sum
            except Exception:  # noqa: BLE001
                quality_totals["ai_quality_delta_sum"] = 0
            self._finalize_success(
                log_id,
                elapsed_ms,
                total_candidates,
                len(fonti),
                errors,
                upsert_totals,
                retry_totals,
                quality_totals,
                page_fetch_totals,
            )

            return {
                "session_id": str(session_id),
                "scraping_log_id": log_id,
                "fonti_scansionate": len(fonti),
                "bandi_identificati": total_candidates,
                "errori_fonti": errors,
                **upsert_totals,
                "ai_jobs": ai_totals,
                "retry": retry_totals,
                "page_fetch": {
                    "attempted": int(page_fetch_totals.get("attempted", 0)),
                    "failed": int(page_fetch_totals.get("failed", 0)),
                    "failure_rate": round(
                        int(page_fetch_totals.get("failed", 0)) / int(page_fetch_totals.get("attempted", 0)),
                        4,
                    ) if int(page_fetch_totals.get("attempted", 0)) else 0.0,
                },
            }
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self._finalize_error(log_id, elapsed_ms, exc)
            raise

    def _create_log_entry(self, session_id: str, started_at: datetime, limit: int | None) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.scraping_log (
                        fonte_id,
                        session_id,
                        tipo_operazione,
                        stato,
                        url_processato,
                        request_params,
                        started_at
                    ) VALUES (
                        NULL,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        session_id,
                        "scan_fonti_livello2",
                        "processing",
                        "multiple-fonti",
                        json.dumps({"limit": limit}),
                        started_at,
                    ),
                )
                row = cur.fetchone()
        return int(row["id"])

    @staticmethod
    def _finalize_success(
        log_id: int,
        elapsed_ms: int,
        total_candidates: int,
        pagine_crawlate: int,
        errors: int,
        upsert_totals: dict[str, int],
        retry_totals: dict[str, int],
        quality_totals: dict[str, Any] | None = None,
        page_fetch_totals: dict[str, int] | None = None,
    ) -> None:
        checked = int((quality_totals or {}).get("gate4_checked", 0))
        discarded = int((quality_totals or {}).get("gate4_discarded", 0))
        with_desc = int((quality_totals or {}).get("with_descrizione", 0))
        with_missing = int((quality_totals or {}).get("with_missing_fields", 0))
        ai_delta_sum = int((quality_totals or {}).get("ai_quality_delta_sum", 0))
        fetch_attempted = int((page_fetch_totals or {}).get("attempted", 0))
        fetch_failed = int((page_fetch_totals or {}).get("failed", 0))
        summary = {
            "fonti_error": errors,
            "upsert": upsert_totals,
            "retry": retry_totals,
            "page_fetch": {
                "attempted": fetch_attempted,
                "failed": fetch_failed,
                "failure_rate": round(fetch_failed / fetch_attempted, 4) if fetch_attempted else 0.0,
            },
            "quality": {
                "gate4_checked": checked,
                "discard_rate": round(discarded / checked, 4) if checked else 0.0,
                "descrizione_rate": round(with_desc / checked, 4) if checked else 0.0,
                "missing_rate": round(with_missing / checked, 4) if checked else 0.0,
                "ai_improvement_rate": round(ai_delta_sum / checked, 4) if checked else 0.0,
            },
        }
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = %s,
                        bandi_trovati = %s,
                        bandi_nuovi = %s,
                        bandi_aggiornati = %s,
                        bandi_invariati = %s,
                        tempo_esecuzione_ms = %s,
                        pagine_crawlate = %s,
                        response_summary = %s::jsonb,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "completed",
                        total_candidates,
                        upsert_totals.get("inserted", 0),
                        upsert_totals.get("updated", 0),
                        upsert_totals.get("unchanged", 0),
                        elapsed_ms,
                        pagine_crawlate,
                        json.dumps(summary),
                        log_id,
                    ),
                )

    def _accumulate_fonte_retry_stats(
        self,
        retry_totals: dict[str, int],
        retry_info: dict[str, Any],
        *,
        session_id: str,
        scraping_log_id: int,
        fonte_id: int,
        source: str,
        error: Exception,
        http_status_code: int | None = None,
    ) -> None:
        stato = str(retry_info.get("stato_processing") or "")
        if stato == "pending":
            retry_totals["fonti_pending"] += 1
            return
        if stato != "failed_final":
            return

        retry_totals["fonti_failed_final"] += 1
        retry_totals["errori_definitivi"] += 1
        self.error_repo.insert_definitive_error(
            session_id=session_id,
            scraping_log_id=scraping_log_id,
            fonte_id=fonte_id,
            entity_type="fonte",
            entity_url=retry_info.get("entity_url") or None,
            errore_tipo=error.__class__.__name__,
            errore_messaggio=str(error),
            errore_stack=traceback.format_exc(),
            http_status_code=http_status_code,
            retry_count=int(retry_info.get("retry_count") or 0),
            contesto={
                "source": source,
                "recoverable": bool(retry_info.get("recoverable", False)),
                "max_retry": int(retry_info.get("max_retry") or settings.scraper_retry_max),
            },
        )

    def _accumulate_bando_retry_stats(
        self,
        retry_totals: dict[str, int],
        retry_info: dict[str, Any],
        *,
        session_id: str,
        scraping_log_id: int,
        source: str,
        source_url: str | None,
        error: Exception,
    ) -> None:
        if not bool(retry_info.get("found", False)):
            return

        stato = str(retry_info.get("stato_processing") or "")
        if stato == "pending":
            retry_totals["bandi_pending"] += 1
            return
        if stato != "failed_final":
            return

        retry_totals["bandi_failed_final"] += 1
        retry_totals["errori_definitivi"] += 1
        self.error_repo.insert_definitive_error(
            session_id=session_id,
            scraping_log_id=scraping_log_id,
            fonte_id=retry_info.get("fonte_id"),
            bando_id=retry_info.get("bando_id"),
            entity_type="bando",
            entity_url=retry_info.get("entity_url") or source_url,
            errore_tipo=error.__class__.__name__,
            errore_messaggio=str(error),
            retry_count=int(retry_info.get("retry_count") or 0),
            contesto={
                "source": source,
                "recoverable": bool(retry_info.get("recoverable", False)),
                "max_retry": int(retry_info.get("max_retry") or settings.scraper_retry_max),
            },
        )

    def run_single_fonte(self, fonte_id: int) -> dict[str, Any]:
        """Esegue la pipeline per una singola fonte, identificata per id."""
        fonte = self.fonte_repo.get_by_id(fonte_id)
        if fonte is None:
            raise ValueError(f"Fonte con id={fonte_id} non trovata")

        session_id = get_session_id() or new_session_id()
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        log_id = self._create_log_entry(str(session_id), started_at, limit=1)

        retry_totals: dict[str, int] = {
            "fonti_pending": 0,
            "fonti_failed_final": 0,
            "bandi_pending": 0,
            "bandi_failed_final": 0,
            "errori_definitivi": 0,
        }
        upsert_totals: dict[str, int] = {"processed": 0, "inserted": 0, "updated": 0, "unchanged": 0}
        ai_totals: dict[str, int] = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": 0}
        page_fetch_totals = {"attempted": 0, "failed": 0}
        total_candidates = 0
        errors = 0

        fonte_started_at = datetime.now(timezone.utc)
        fonte_t0 = time.perf_counter()
        fonte_log_id = self.log_repo.create_fonte_log_entry(
            str(session_id), log_id, int(fonte.id), fonte.link, fonte_started_at
        )
        self.fonte_repo.mark_processing_started(int(fonte.id))
        try:
            candidates = self.scanner.scan_fonte(fonte)
            total_candidates = len(candidates)

            payload: list[dict[str, Any]] = []
            for candidate in candidates:
                page_fetch_totals["attempted"] += 1
                try:
                    candidate_payload = candidates_to_upsert_payload([candidate], scraping_log_id=fonte_log_id)
                    if candidate_payload:
                        raw_data_obj = candidate_payload[0].get("raw_data_obj") or {}
                        if raw_data_obj.get("fetch_error"):
                            page_fetch_totals["failed"] += 1
                        payload.append(candidate_payload[0])
                except Exception as candidate_exc:  # noqa: BLE001
                    errors += 1
                    recoverable = self._is_recoverable_error(candidate_exc)
                    bando_result = self.bando_repo.register_processing_error_by_hash(
                        candidate.hash_bando,
                        error_type=candidate_exc.__class__.__name__,
                        error_message=str(candidate_exc),
                        recoverable=recoverable,
                        retry_delay_seconds=settings.scraper_retry_delay_seconds,
                    )
                    self._accumulate_bando_retry_stats(
                        retry_totals, bando_result,
                        session_id=str(session_id), scraping_log_id=fonte_log_id,
                        source="candidate_parse", source_url=getattr(fonte, "link", None),
                        error=candidate_exc,
                    )

            payload = self.classifier.classify_candidates(payload, fonte=fonte)
            stats = self.bando_repo.upsert_candidates(payload)
            for key in upsert_totals:
                upsert_totals[key] += int(stats.get(key, 0))

            # v4: AI pipeline pre-skill deprecata.
            ai_stats = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": int(stats.get("inserted", 0)) + int(stats.get("updated", 0))}
            for key in ai_totals:
                ai_totals[key] += int(ai_stats.get(key, 0))

            self.fonte_repo.mark_processing_success(int(fonte.id))
            fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
            self.log_repo.update_fonte_log_success(
                fonte_log_id,
                elapsed_ms=fonte_elapsed_ms,
                bandi_trovati=len(candidates),
                bandi_nuovi=int(stats.get("inserted", 0)),
                bandi_aggiornati=int(stats.get("updated", 0)),
                bandi_invariati=int(stats.get("unchanged", 0)),
                ai_calls_count=int(ai_stats.get("enqueued", 0)),
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
            self.log_repo.update_fonte_log_error(
                fonte_log_id,
                elapsed_ms=fonte_elapsed_ms,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                error_stack=traceback.format_exc(),
            )
            retry_info = self.fonte_repo.register_processing_error(
                int(fonte.id),
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                recoverable=self._is_recoverable_error(exc),
                retry_delay_seconds=settings.scraper_retry_delay_seconds,
            )
            self._accumulate_fonte_retry_stats(
                retry_totals, retry_info,
                session_id=str(session_id), scraping_log_id=fonte_log_id,
                fonte_id=int(fonte.id), source="run_single_fonte", error=exc,
            )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        self._finalize_success(
            log_id,
            elapsed_ms,
            total_candidates,
            1,
            errors,
            upsert_totals,
            retry_totals,
            None,
            page_fetch_totals,
        )
        return {
            "session_id": str(session_id),
            "scraping_log_id": log_id,
            "fonte_id": fonte_id,
            "fonti_scansionate": 1,
            "bandi_identificati": total_candidates,
            "errori_fonti": errors,
            **upsert_totals,
            "ai_jobs": ai_totals,
            "retry": retry_totals,
            "page_fetch": {
                "attempted": int(page_fetch_totals.get("attempted", 0)),
                "failed": int(page_fetch_totals.get("failed", 0)),
                "failure_rate": round(
                    int(page_fetch_totals.get("failed", 0)) / int(page_fetch_totals.get("attempted", 0)),
                    4,
                ) if int(page_fetch_totals.get("attempted", 0)) else 0.0,
            },
        }

    def run_pending_queue(self) -> dict[str, Any]:
        """Riesegue solo le fonti in stato pending la cui next_retry_at è scaduta."""
        pending_fonti = self.fonte_repo.get_pending()
        if not pending_fonti:
            return {
                "session_id": None,
                "fonti_pending_processate": 0,
                "bandi_identificati": 0,
                "errori_fonti": 0,
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "processed": 0,
                "retry": {
                    "fonti_pending": 0,
                    "fonti_failed_final": 0,
                    "bandi_pending": 0,
                    "bandi_failed_final": 0,
                    "errori_definitivi": 0,
                },
            }

        session_id = get_session_id() or new_session_id()
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        log_id = self._create_log_entry(str(session_id), started_at, limit=len(pending_fonti))

        retry_totals: dict[str, int] = {
            "fonti_pending": 0,
            "fonti_failed_final": 0,
            "bandi_pending": 0,
            "bandi_failed_final": 0,
            "errori_definitivi": 0,
        }
        upsert_totals: dict[str, int] = {"processed": 0, "inserted": 0, "updated": 0, "unchanged": 0}
        ai_totals: dict[str, int] = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": 0}
        page_fetch_totals = {"attempted": 0, "failed": 0}
        total_candidates = 0
        errors = 0

        for fonte in pending_fonti:
            fonte_started_at = datetime.now(timezone.utc)
            fonte_t0 = time.perf_counter()
            fonte_log_id = self.log_repo.create_fonte_log_entry(
                str(session_id), log_id, int(fonte.id), fonte.link, fonte_started_at
            )
            self.fonte_repo.mark_processing_started(int(fonte.id))
            try:
                candidates = self.scanner.scan_fonte(fonte)
                total_candidates += len(candidates)

                payload: list[dict[str, Any]] = []
                for candidate in candidates:
                    page_fetch_totals["attempted"] += 1
                    try:
                        candidate_payload = candidates_to_upsert_payload([candidate], scraping_log_id=fonte_log_id)
                        if candidate_payload:
                            raw_data_obj = candidate_payload[0].get("raw_data_obj") or {}
                            if raw_data_obj.get("fetch_error"):
                                page_fetch_totals["failed"] += 1
                            payload.append(candidate_payload[0])
                    except Exception as candidate_exc:  # noqa: BLE001
                        errors += 1
                        recoverable = self._is_recoverable_error(candidate_exc)
                        bando_result = self.bando_repo.register_processing_error_by_hash(
                            candidate.hash_bando,
                            error_type=candidate_exc.__class__.__name__,
                            error_message=str(candidate_exc),
                            recoverable=recoverable,
                            retry_delay_seconds=settings.scraper_retry_delay_seconds,
                        )
                        self._accumulate_bando_retry_stats(
                            retry_totals, bando_result,
                            session_id=str(session_id), scraping_log_id=fonte_log_id,
                            source="candidate_parse", source_url=getattr(fonte, "link", None),
                            error=candidate_exc,
                        )

                payload = self.classifier.classify_candidates(payload, fonte=fonte)
                stats = self.bando_repo.upsert_candidates(payload)
                for key in upsert_totals:
                    upsert_totals[key] += int(stats.get(key, 0))

                # v4: AI pipeline pre-skill deprecata.
                ai_stats = {"considered": 0, "enqueued": 0, "already_present": 0, "not_required": int(stats.get("inserted", 0)) + int(stats.get("updated", 0))}
                for key in ai_totals:
                    ai_totals[key] += int(ai_stats.get(key, 0))

                self.fonte_repo.mark_processing_success(int(fonte.id))
                fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
                self.log_repo.update_fonte_log_success(
                    fonte_log_id,
                    elapsed_ms=fonte_elapsed_ms,
                    bandi_trovati=len(candidates),
                    bandi_nuovi=int(stats.get("inserted", 0)),
                    bandi_aggiornati=int(stats.get("updated", 0)),
                    bandi_invariati=int(stats.get("unchanged", 0)),
                    ai_calls_count=int(ai_stats.get("enqueued", 0)),
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                fonte_elapsed_ms = int((time.perf_counter() - fonte_t0) * 1000)
                self.log_repo.update_fonte_log_error(
                    fonte_log_id,
                    elapsed_ms=fonte_elapsed_ms,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    error_stack=traceback.format_exc(),
                )
                retry_info = self.fonte_repo.register_processing_error(
                    int(fonte.id),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    recoverable=self._is_recoverable_error(exc),
                    retry_delay_seconds=settings.scraper_retry_delay_seconds,
                )
                self._accumulate_fonte_retry_stats(
                    retry_totals, retry_info,
                    session_id=str(session_id), scraping_log_id=fonte_log_id,
                    fonte_id=int(fonte.id), source="run_pending_queue", error=exc,
                )
                continue

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        self._finalize_success(
            log_id,
            elapsed_ms,
            total_candidates,
            len(pending_fonti),
            errors,
            upsert_totals,
            retry_totals,
            None,
            page_fetch_totals,
        )
        return {
            "session_id": str(session_id),
            "scraping_log_id": log_id,
            "fonti_pending_processate": len(pending_fonti),
            "bandi_identificati": total_candidates,
            "errori_fonti": errors,
            **upsert_totals,
            "ai_jobs": ai_totals,
            "retry": retry_totals,
            "page_fetch": {
                "attempted": int(page_fetch_totals.get("attempted", 0)),
                "failed": int(page_fetch_totals.get("failed", 0)),
                "failure_rate": round(
                    int(page_fetch_totals.get("failed", 0)) / int(page_fetch_totals.get("attempted", 0)),
                    4,
                ) if int(page_fetch_totals.get("attempted", 0)) else 0.0,
            },
        }

    @staticmethod
    def _is_recoverable_error(exc: Exception) -> bool:
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = int(exc.response.status_code)
            return status in {408, 425, 429} or status >= 500
        if isinstance(exc, FonteLevel2Error):
            return bool(getattr(exc, "recoverable", True))
        lowered = str(exc).lower()
        recoverable_markers = [
            "timeout",
            "tempor",
            "connection reset",
            "connection aborted",
            "service unavailable",
            "too many requests",
            "rate limit",
        ]
        return any(marker in lowered for marker in recoverable_markers)

    @staticmethod
    def _finalize_error(log_id: int, elapsed_ms: int, exc: Exception) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.scraping_log
                    SET stato = %s,
                        errore_tipo = %s,
                        errore_messaggio = %s,
                        errore_stack = %s,
                        tempo_esecuzione_ms = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        "failed",
                        exc.__class__.__name__,
                        str(exc)[:4000],
                        traceback.format_exc(),
                        elapsed_ms,
                        log_id,
                    ),
                )
