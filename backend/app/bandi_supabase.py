"""Client Supabase dedicato al DB dello scraper bandi (DB B).

Separato da `database.get_supabase_client()` (DB A — Supabase principale di news1)
perche' lo scraper e la skill di enrichment vivono su un Supabase distinto
(qggfoubllzeojxqlguef.supabase.co).

Variabili d'ambiente richieste in `.env`:
    SUPABASE_URL_BANDI            URL del progetto Supabase B
    SUPABASE_SERVICE_KEY_BANDI    Service role key (solo backend, MAI nel frontend)
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_bandi_supabase() -> Client:
    url = os.getenv("SUPABASE_URL_BANDI")
    key = os.getenv("SUPABASE_SERVICE_KEY_BANDI")
    if not url or not key:
        raise ValueError(
            "Variabili mancanti: SUPABASE_URL_BANDI e/o SUPABASE_SERVICE_KEY_BANDI"
        )
    return create_client(url, key)
