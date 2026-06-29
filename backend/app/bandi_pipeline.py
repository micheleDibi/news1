"""Orchestratore completo del pipeline scraping bandi.

Chaining sequenziale dei 5 step:
  1. discover       — fonti da OpenCoesione → tabella `fonte`
  2. scrape-bandi   — scraping di ~108 fonti → tabella `bando`
  3. preprocess     — validazione + 3 date + reconciliation stato (Haiku + Sonnet fallback)
  4. enrich         — FK + junction tables (7 LLM call parallele)
  5. seo            — skill SEO (Opus 4.7) → contenuto editoriale + meta

Importa direttamente le `run()` async di scraper_bandi via manipolazione sys.path.
Niente subprocess (log integrato, traceback Python, niente overhead processo).

Failure handling: ogni step viene wrappato in try/except. Se uno fallisce, il
pipeline CONTINUA con gli step successivi (sono tutti idempotenti e operano
solo sui record nella loro coda). Lo stato per step viene persistito in dict
di sintesi e loggato al termine.

Idempotenza: ogni step opera solo sui record nella propria coda
(stato_processing iniziale). Re-eseguire e' sicuro.

Tempi attesi per ciclo (~80 min totali):
  discover    ~1 min
  scrape      ~20-30 min
  preprocess  ~10 min
  enrich      ~8 min
  seo         ~30 min
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Aggiungi scraper_bandi al sys.path per importare i runner come moduli locali.
_SCRAPER_BANDI = Path(__file__).resolve().parents[2] / "scraper_bandi"
if str(_SCRAPER_BANDI) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_BANDI))

# Import dei 5 step runner. NB: `app` qui si riferisce a scraper_bandi/app
# (grazie all'insert in sys.path sopra). Per non collidere con backend.app
# (questo modulo), li importiamo con alias.
from app.orchestrator import run as _discover_run  # type: ignore
from app.bando_runner import run as _scrape_run  # type: ignore
from app.bando_preprocess_runner import run as _preprocess_run  # type: ignore
from app.bando_enrich_runner import run as _enrich_run  # type: ignore
from app.bando_seo_runner import run as _seo_run  # type: ignore

from .logger import logger


async def _safe_run(name: str, fn: Callable, **kwargs) -> dict[str, Any]:
    """Wrap un step async in try/except + timing.

    Ritorna sempre un dict (mai solleva), in modo che il pipeline continui
    con gli step successivi.
    """
    started = time.monotonic()
    logger.info("--- bandi_pipeline: STEP {} START ---", name)
    try:
        result = await fn(**kwargs)
        elapsed = time.monotonic() - started
        logger.info(
            "--- bandi_pipeline: STEP {} OK | elapsed={:.1f}s | counters={} ---",
            name, elapsed, result,
        )
        return {
            "status": "ok",
            "elapsed_s": round(elapsed, 1),
            "counters": result,
        }
    except Exception as e:
        elapsed = time.monotonic() - started
        logger.exception(
            "--- bandi_pipeline: STEP {} FAILED | elapsed={:.1f}s | error={} ---",
            name, elapsed, e,
        )
        return {
            "status": "error",
            "elapsed_s": round(elapsed, 1),
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def run_bandi_pipeline() -> dict[str, Any]:
    """Esegue i 5 step in sequenza. Continue all'errore (steps idempotenti).

    Ritorna lo stato completo:
        {
          "started_at": ISO,
          "finished_at": ISO,
          "total_elapsed_s": float,
          "status": "completed" | "partial",
          "steps": {
            "discover":    {status, elapsed_s, counters? | error?},
            "scrape":      {...},
            "preprocess":  {...},
            "enrich":      {...},
            "seo":         {...},
          }
        }
    """
    pipeline_start = time.monotonic()
    state: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "steps": {},
    }
    logger.info("=" * 80)
    logger.info("=== BANDI PIPELINE START | {} ===", state["started_at"])
    logger.info("=" * 80)

    # Step 1: discover (no kwargs)
    state["steps"]["discover"] = await _safe_run("discover", _discover_run)

    # Step 2: scrape-bandi (no kwargs)
    state["steps"]["scrape"] = await _safe_run("scrape", _scrape_run)

    # Step 3: preprocess (parametri di default: tutti i 'scraped')
    state["steps"]["preprocess"] = await _safe_run("preprocess", _preprocess_run)

    # Step 4: enrich (no kwargs: opera su 'processed')
    state["steps"]["enrich"] = await _safe_run("enrich", _enrich_run)

    # Step 5: seo (no kwargs: opera su 'enriched')
    state["steps"]["seo"] = await _safe_run("seo", _seo_run)

    # Sintesi finale
    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    state["total_elapsed_s"] = round(time.monotonic() - pipeline_start, 1)
    all_ok = all(s["status"] == "ok" for s in state["steps"].values())
    state["status"] = "completed" if all_ok else "partial"

    logger.info("=" * 80)
    logger.info(
        "=== BANDI PIPELINE {} | finished_at={} | total_elapsed={:.0f}s ===",
        state["status"].upper(), state["finished_at"], state["total_elapsed_s"],
    )
    for step_name, step in state["steps"].items():
        logger.info(
            "  - {:12s} {:>5s} {:>6.0f}s",
            step_name, step["status"], step.get("elapsed_s", 0),
        )
    logger.info("=" * 80)

    return state


# ---------------------------------------------------------------------------
# CLI invocation diretto (utile per test smoke senza scheduler)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    final_state = asyncio.run(run_bandi_pipeline())
    print(f"\n=== FINAL STATE ===\n{final_state}\n")
