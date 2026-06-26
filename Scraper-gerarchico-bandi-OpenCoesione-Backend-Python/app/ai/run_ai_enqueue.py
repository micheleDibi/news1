from __future__ import annotations

import argparse
import json
import logging

from app.services.ai_pipeline_service import AiPipelineService


logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _enqueue_progress_logger(report_every: int):
    def _callback(current: int, total: int, bando_id: int, stats: dict[str, int]) -> None:
        if current % max(1, report_every) != 0 and current != total:
            return
        logger.info(
            "AI enqueue progress=%s/%s bando_id=%s considered=%s enqueued=%s already_present=%s not_required=%s",
            current,
            total,
            bando_id,
            int(stats.get("considered", 0)),
            int(stats.get("enqueued", 0)),
            int(stats.get("already_present", 0)),
            int(stats.get("not_required", 0)),
        )

    return _callback


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Enqueue AI job di classificazione per bandi incompleti")
    parser.add_argument("--limit", type=int, default=100, help="Numero massimo di bandi da valutare")
    parser.add_argument("--report-every", type=int, default=100, help="Frequenza log progresso (ogni N bandi valutati)")
    args = parser.parse_args()

    service = AiPipelineService()
    logger.info("AI enqueue avvio limit=%s report_every=%s", args.limit, max(1, args.report_every))
    result = service.enqueue_from_existing_bandi(
        limit=args.limit,
        progress_callback=_enqueue_progress_logger(max(1, args.report_every)),
    )
    logger.info(
        "AI enqueue completato considered=%s enqueued=%s already_present=%s not_required=%s",
        int(result.get("considered", 0)),
        int(result.get("enqueued", 0)),
        int(result.get("already_present", 0)),
        int(result.get("not_required", 0)),
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()