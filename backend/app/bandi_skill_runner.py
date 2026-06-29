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
    hint_keys = sorted(hint.keys()) if hint else []
    logger.info(
        "[skill_runner] INVOKE link={} hint_keys={} (n={}) env: FIRECRAWL={} ANTHROPIC={}",
        link_bando, hint_keys, len(hint_keys),
        "present" if has_fc else "absent",
        "present" if has_anthropic else "absent",
    )
    if not has_fc:
        logger.warning(
            "[skill_runner] FIRECRAWL_API_KEY assente: la skill cadra' su "
            "WebFetch/WebSearch invece di Firecrawl (qualita' estrazione ridotta)."
        )
    if not has_anthropic:
        logger.warning(
            "[skill_runner] ANTHROPIC_API_KEY/AUTH_TOKEN assenti: la skill "
            "non potra' invocare Claude e fallira'."
        )
    if not hint:
        logger.warning(
            "[skill_runner] hint vuoto: la skill ricevera' meno contesto "
            "(catalogo/junction lookup potrebbero essere mancati)."
        )

    start = time.monotonic()
    try:
        payload = await _run_skill_bandi(link_bando=link_bando, hint=hint)
    except Exception as e:
        logger.exception(
            "[skill_runner] FAIL in {:.1f}s: {}",
            time.monotonic() - start, e,
        )
        raise

    elapsed = time.monotonic() - start
    validation = (payload or {}).get("validation") or {}
    sublinks = validation.get("discovered_sublinks") or []
    allegati = (payload.get("bando") or {}).get("allegati") if isinstance(payload.get("bando"), dict) else None
    logger.info(
        "[skill_runner] DONE in {:.1f}s livello={} slug={} is_valid={} rejection={} "
        "allegati={} sublinks={}",
        elapsed,
        payload.get("livello"),
        payload.get("slug"),
        validation.get("is_valid_bando"),
        validation.get("rejection_category"),
        len(allegati) if isinstance(allegati, list) else 0,
        len(sublinks) if isinstance(sublinks, list) else 0,
    )
    return payload
