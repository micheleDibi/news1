"""Adapter che espone la skill news-angle-rewriter-persona al backend come coroutine.

La skill vive in `backend/news-angle-rewriter-persona/scripts/run_agent_sdk_json.py`.
Il file ha lo stesso nome della skill base (`backend/skill/scripts/run_agent_sdk_json.py`)
quindi invece di iniettare il percorso in `sys.path` usiamo `importlib` con un nome di
modulo unico per evitare collisioni.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from .logger import logger

_PERSONA_SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent / "news-angle-rewriter-persona" / "scripts"
)
_PERSONA_MODULE_NAME = "news_angle_rewriter_persona_runner"


def _load_persona_runner():
    if _PERSONA_MODULE_NAME in sys.modules:
        return sys.modules[_PERSONA_MODULE_NAME]
    source = _PERSONA_SCRIPTS_DIR / "run_agent_sdk_json.py"
    spec = importlib.util.spec_from_file_location(_PERSONA_MODULE_NAME, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossibile caricare la skill persona da {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PERSONA_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_persona_module = _load_persona_runner()
_run_skill_persona = _persona_module.run_skill


async def generate_article_with_persona(
    *,
    url: str,
    livello: str | None = None,
    tono: str = "Neutrale",
    persona: str = "Giornalista",
    target: str | None = None,
    interlinks: Iterable[str] | None = None,
) -> dict:
    """Esegue la skill persona e ritorna il payload JSON.

    Args:
        url: URL della notizia da scrapare oppure topic libero (STEP 0.5 del SKILL.md).
        livello: `flash` | `editoriale` | `evergreen` oppure None per auto-detect.
        tono: uno degli 11 toni ammessi (default Neutrale).
        persona: una delle 10 persone ammesse (default Giornalista).
        target: target di riferimento (docenti, studenti, ecc.).
        interlinks: URL assoluti del proprio sito da linkare internamente.

    Returns:
        dict con payload (seo, angolo, competitor_report, factcheck_report,
        article.sections, fonti, validation, livello, keyword, source_url,
        generated_at, meta={tono, persona}).

    Raises:
        ValueError: tono o persona non validi.
        RuntimeError: la skill non ha prodotto JSON (es. combinazione tono+persona
            bloccata dallo STEP 1.5).
    """
    interlink_list = list(interlinks) if interlinks else []
    has_fc = bool(os.getenv("FIRECRAWL_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    logger.info(
        "[persona_runner] invoco skill: url={} livello={} tono={} persona={} "
        "target={} interlinks={} FIRECRAWL_API_KEY={} ANTHROPIC_API_KEY={}",
        url, livello, tono, persona, target, len(interlink_list),
        has_fc, has_anthropic,
    )
    if not has_fc:
        logger.warning(
            "[persona_runner] FIRECRAWL_API_KEY non presente: la skill cadra' su "
            "WebFetch/WebSearch invece di Firecrawl."
        )

    start = time.monotonic()
    try:
        payload = await _run_skill_persona(
            url=url,
            livello=livello,
            interlink=interlink_list,
            target=target,
            tono=tono,
            persona=persona,
        )
    except Exception as e:
        logger.exception(
            "[persona_runner] skill fallita dopo {:.1f}s: {}",
            time.monotonic() - start, e,
        )
        raise

    logger.info(
        "[persona_runner] skill completata in {:.1f}s", time.monotonic() - start
    )
    return payload
