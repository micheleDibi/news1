from __future__ import annotations

import argparse
import json
import logging
import math
import time

from app.services.ai_pipeline_service import AiPipelineService


logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Nasconde il rumore delle richieste HTTP verbose verso OpenAI.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)


def _progress_logger(batch_no: int):
    def _callback(current: int, total: int, job_id: int, bando_id: int) -> None:
        logger.info(
            "AI worker batch=%s call %s/%s (job_id=%s bando_id=%s)",
            batch_no,
            current,
            total,
            job_id,
            bando_id,
        )

    return _callback


def _format_batch_progress(batch_no: int, planned_batches: int) -> str:
    total = planned_batches if planned_batches > 0 else batch_no
    return f"{batch_no}/{total}"


def _format_duration_hms(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    total_seconds = max(0, int(round(float(seconds))))
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Worker AI asincrono per classificazione bandi")
    parser.add_argument("--limit", type=int, default=100, help="Numero massimo di job da processare per batch")
    parser.add_argument("--drain-all", action="store_true", help="Processa batch successivi fino a coda queued vuota")
    parser.add_argument("--report-every", type=int, default=1, help="Frequenza reporting progress (ogni N batch)")
    parser.add_argument("--call-delay", type=float, default=0.5, help="Delay in secondi tra una chiamata AI e la successiva (default 0.5)")
    args = parser.parse_args()

    service = AiPipelineService()

    if not args.drain_all:
        result = service.process_queue(
            limit=args.limit,
            progress_callback=_progress_logger(batch_no=1),
        )
        counts = service.ai_repo.get_status_counts()
        result["queue_status"] = counts
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return

    batch = 0
    totals = {
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "discarded_payloads": 0,
        "skipped_title_gate": 0,
    }
    started = time.perf_counter()
    eta_s: float | None = None
    # Rolling window: timestamp di fine di ogni batch (per ETA adattiva)
    _ROLLING_WINDOW = 5  # ultimi N batch
    batch_end_times: list[float] = []  # perf_counter() a fine ogni batch
    batch_completed: list[int] = []    # job completed in ogni batch

    initial_counts = service.ai_repo.get_status_counts()
    initial_queued = int(initial_counts.get("queued", 0))
    planned_batches = math.ceil(initial_queued / max(1, args.limit)) if initial_queued > 0 else 0

    if initial_queued == 0:
        totals["batches"] = 0
        totals["planned_batches"] = 0
        totals["elapsed_s"] = round(time.perf_counter() - started, 2)
        totals["elapsed_hms"] = _format_duration_hms(totals["elapsed_s"])
        totals["queue_status"] = initial_counts
        totals["eta_s"] = 0
        totals["eta_hms"] = _format_duration_hms(totals["eta_s"])
        print(json.dumps(totals, ensure_ascii=True, indent=2))
        return

    while True:
        batch += 1
        batch_progress = _format_batch_progress(batch, planned_batches)
        result = service.process_queue(
            limit=args.limit,
            progress_callback=_progress_logger(batch_no=batch),
            inter_call_delay_s=args.call_delay,
        )
        for key in totals:
            totals[key] += int(result.get(key, 0))

        counts = service.ai_repo.get_status_counts()
        queued = int(counts.get("queued", 0))
        now = time.perf_counter()
        elapsed_s = round(now - started, 2)

        # ETA adattiva: rolling window degli ultimi N batch.
        batch_end_times.append(now)
        batch_completed.append(max(0, int(result.get("completed", 0))))
        window_t = batch_end_times[-_ROLLING_WINDOW:]
        window_c = batch_completed[-_ROLLING_WINDOW:]
        window_duration = window_t[-1] - (batch_end_times[-_ROLLING_WINDOW - 1] if len(batch_end_times) > _ROLLING_WINDOW else started)
        window_jobs = sum(window_c)
        throughput = (window_jobs / window_duration) if window_duration > 0 and window_jobs > 0 else 0.0
        eta_s = round((queued / throughput), 2) if throughput > 0 else None

        if batch % max(1, args.report_every) == 0:
            logger.info(
                "AI worker batch=%s claimed=%s completed=%s failed=%s discarded=%s queued_remaining=%s elapsed=%s eta=%s",
                batch_progress,
                result.get("claimed", 0),
                result.get("completed", 0),
                result.get("failed", 0),
                result.get("discarded_payloads", 0),
                queued,
                _format_duration_hms(elapsed_s),
                _format_duration_hms(eta_s),
            )

        # Nessun job claimato: coda svuotata o solo job in backoff/failed.
        if int(result.get("claimed", 0)) == 0:
            break

    totals["batches"] = batch
    totals["planned_batches"] = planned_batches
    totals["elapsed_s"] = round(time.perf_counter() - started, 2)
    totals["elapsed_hms"] = _format_duration_hms(totals["elapsed_s"])
    totals["queue_status"] = service.ai_repo.get_status_counts()
    totals["eta_s"] = 0 if int(totals["queue_status"].get("queued", 0)) == 0 else eta_s
    totals["eta_hms"] = _format_duration_hms(totals["eta_s"])
    print(json.dumps(totals, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()