"""Configurazione runtime: legge .env e fornisce singleton `settings`.

Variabili obbligatorie:
  - SUPABASE_URL_BANDI
  - SUPABASE_SERVICE_KEY_BANDI

Variabili opzionali (con default):
  - OPENCOESIONE_URL         (pagina sorgente)
  - REACHABILITY_TIMEOUT_S   (timeout HEAD/GET per testare attivo)
  - REACHABILITY_CONCURRENCY (concorrenza asyncio per reachability)
  - HTTP_USER_AGENT          (UA delle request)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15 EduNews24-ScraperBandi/1.0"
)

_DEFAULT_OPENCOESIONE_URL = "https://opencoesione.gov.it/it/opportunita_2021_2027/"


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    opencoesione_url: str
    reachability_timeout_s: float
    reachability_concurrency: int
    http_user_agent: str
    # Step 2 (scraping bandi)
    firecrawl_api_key: str        # vuota se non impostata: strategie firecrawl_* falliranno
    host_throttle_delay_s: float  # delay min tra request stesso host
    # Step intermedio: pre-processing via LLM
    anthropic_api_key: str        # obbligatoria per preprocess
    preprocess_model: str
    preprocess_concurrency: int
    preprocess_max_tokens: int
    # Step v7: enrichment via LLM + Firecrawl
    enrich_model: str
    enrich_concurrency: int
    enrich_concurrency_refine: int
    enrich_max_tokens: int


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Carica .env dal CWD e dalla root del sub-progetto.
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    load_dotenv()  # fallback CWD

    supabase_url = os.getenv("SUPABASE_URL_BANDI", "").strip()
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY_BANDI", "").strip()

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Mancano SUPABASE_URL_BANDI / SUPABASE_SERVICE_KEY_BANDI in .env. "
            "Copia .env.example -> .env e compila le credenziali del DB B."
        )

    return Settings(
        supabase_url=supabase_url,
        supabase_service_key=supabase_key,
        opencoesione_url=os.getenv("OPENCOESIONE_URL", _DEFAULT_OPENCOESIONE_URL).strip()
            or _DEFAULT_OPENCOESIONE_URL,
        reachability_timeout_s=_float_env("REACHABILITY_TIMEOUT_S", 15.0),
        reachability_concurrency=max(1, _int_env("REACHABILITY_CONCURRENCY", 10)),
        http_user_agent=os.getenv("HTTP_USER_AGENT", _DEFAULT_USER_AGENT).strip()
            or _DEFAULT_USER_AGENT,
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", "").strip(),
        host_throttle_delay_s=_float_env("HOST_THROTTLE_DELAY_S", 1.0),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        preprocess_model=os.getenv("PREPROCESS_MODEL", "claude-haiku-4-5-20251001").strip()
            or "claude-haiku-4-5-20251001",
        preprocess_concurrency=max(1, _int_env("PREPROCESS_CONCURRENCY", 20)),
        preprocess_max_tokens=max(64, _int_env("PREPROCESS_MAX_TOKENS", 256)),
        enrich_model=os.getenv("ENRICH_MODEL", "claude-haiku-4-5-20251001").strip()
            or "claude-haiku-4-5-20251001",
        enrich_concurrency=max(1, _int_env("ENRICH_CONCURRENCY", 5)),
        enrich_concurrency_refine=max(1, _int_env("ENRICH_CONCURRENCY_REFINE", 3)),
        enrich_max_tokens=max(64, _int_env("ENRICH_MAX_TOKENS", 200)),
    )
