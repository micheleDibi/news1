"""Adapter che espone la skill news-angle-rewriter al backend come coroutine.

La skill vive in `backend/skill/scripts/run_agent_sdk_json.py` ed è organizzata
come script standalone (non package Python). Questo wrapper iniettta la
directory degli scripts in `sys.path` e ri-esporta `run_skill` sotto un nome
di dominio (`generate_article_for_news`) per il chiamante backend.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Iterable

from .logger import logger

_SKILL_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skill" / "scripts"
if str(_SKILL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS_DIR))

from run_agent_sdk_json import run_skill  # type: ignore  # noqa: E402


async def generate_article_for_news(news_item, interlinks: Iterable[str] | None = None) -> dict:
    """Esegue la skill su una news row del backend e ritorna il payload JSON.

    Args:
        news_item: riga ORM `models.New` (serve solo `news_item.url`).
        interlinks: URL interni assoluti da suggerire come interlink nell'articolo.

    Returns:
        dict con la struttura definita da `generate_json_output.build_seo_article_payload`
        (seo, angolo, competitor_report, factcheck_report, article.sections, fonti,
        validation, livello, keyword, generated_at, source_url).
    """
    interlink_list = list(interlinks) if interlinks else []
    has_fc = bool(os.getenv("FIRECRAWL_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    logger.info(
        "[skill_runner] invoco skill: news_id={} url={} interlinks={} "
        "FIRECRAWL_API_KEY={} ANTHROPIC_API_KEY={}",
        getattr(news_item, "id", None), getattr(news_item, "url", None),
        len(interlink_list), has_fc, has_anthropic,
    )
    if not has_fc:
        logger.warning("[skill_runner] FIRECRAWL_API_KEY non presente in env: la skill "
                       "cadra' su WebFetch/WebSearch invece di Firecrawl.")

    start = time.monotonic()
    try:
        payload = await run_skill(
            url=news_item.url,
            livello=None,
            interlink=interlink_list,
            target=None,
        )
    except Exception as e:
        logger.exception("[skill_runner] skill fallita dopo {:.1f}s: {}",
                         time.monotonic() - start, e)
        raise

    logger.info("[skill_runner] skill completata in {:.1f}s", time.monotonic() - start)
    return payload
