"""Adapter che espone la skill `bandi-seo-enricher` al backend come coroutine.

Pattern speculare a `backend/app/skill_runner.py:1-65`: aggiunge in `sys.path`
la directory degli scripts della skill bandi e ri-esporta `run_skill_bandi` con
un wrapper di logging.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .logger import logger

_SKILL_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skill_bandi" / "scripts"
if str(_SKILL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS_DIR))

from run_agent_sdk_json_bandi import run_skill_bandi as _run_skill_bandi  # type: ignore  # noqa: E402


async def run_bandi_skill(link_bando: str, hint: dict | None = None) -> dict:
    """Esegue la skill `bandi-seo-enricher` su un singolo URL e ritorna il payload JSON.

    Args:
        link_bando: URL pubblico del bando (es. pagina istituzionale).
        hint: opzionale, dict con suggerimenti dominio per la skill
            (ente, tipologia, area, beneficiari[], settori[], ateco[], ...).
            Vengono passati come `hint_dominio` alla skill.

    Returns:
        dict con lo schema descritto in `bandi-seo-enricher/SKILL.md` (sezione "Schema JSON output").

    Raises:
        RuntimeError: se la skill non produce JSON valido.
    """
    has_fc = bool(os.getenv("FIRECRAWL_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    logger.info(
        "[bandi_skill_runner] invoco skill: link={} hint_keys={} "
        "FIRECRAWL_API_KEY={} ANTHROPIC_API_KEY={}",
        link_bando,
        list(hint.keys()) if hint else [],
        has_fc, has_anthropic,
    )
    if not has_fc:
        logger.warning(
            "[bandi_skill_runner] FIRECRAWL_API_KEY non presente: la skill cadra' "
            "su WebFetch/WebSearch invece di Firecrawl."
        )

    start = time.monotonic()
    try:
        payload = await _run_skill_bandi(link_bando=link_bando, hint=hint)
    except Exception as e:
        logger.exception(
            "[bandi_skill_runner] skill fallita dopo {:.1f}s: {}",
            time.monotonic() - start, e,
        )
        raise

    logger.info(
        "[bandi_skill_runner] skill completata in {:.1f}s, livello={}, slug={}",
        time.monotonic() - start,
        payload.get("livello"), payload.get("slug"),
    )
    return payload
