"""Client Supabase DB B + helper per upsert e mark-deprecated della tabella `fonte`."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

from supabase import Client, create_client

from .logger import logger
from .settings import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Singleton client Supabase (service-role key, write su DB B)."""
    settings = get_settings()
    logger.info("[db] init supabase client url={}", settings.supabase_url)
    return create_client(settings.supabase_url, settings.supabase_service_key)


def upsert_fonti(records: list[dict[str, Any]]) -> dict[str, int]:
    """UPSERT idempotente in `fonte` con on_conflict='link'.

    Difesa anti-duplicati: PostgreSQL ON CONFLICT non puo' aggiornare la
    stessa riga due volte nello stesso comando. Se nel batch ci sono
    record con `link` duplicato, dedup preservando il PRIMO trovato.

    Restituisce contatori {processed, dedup_collisions}.
    """
    if not records:
        return {"processed": 0, "dedup_collisions": 0}

    # Dedup per link preservando il primo (l'orchestrator gia' applica
    # priorita' Opportunita'>Preavviso, qui difesa best-effort).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    collisions = 0
    for r in records:
        link = r.get("link")
        if not link:
            continue
        if link in seen:
            collisions += 1
            logger.warning("[db] dedup link duplicato pre-upsert: {}", link)
            continue
        seen.add(link)
        deduped.append(r)

    sb = get_supabase()
    logger.info(
        "[db] upsert {} record in `fonte` (input={}, dedup_collisions={})",
        len(deduped), len(records), collisions,
    )
    try:
        sb.table("fonte").upsert(deduped, on_conflict="link").execute()
    except Exception as e:
        logger.exception("[db] upsert fallito: {}", e)
        raise
    return {"processed": len(deduped), "dedup_collisions": collisions}


def mark_deprecated(active_links: set[str]) -> int:
    """Marca come `deprecated` ogni fonte gia' in DB il cui `link` NON e' tra
    quelli appena scoperti. Skip i record gia' deprecati (no UPDATE noop).

    Ritorna il numero di righe segnate come deprecate in questo run.
    """
    sb = get_supabase()

    # Per evitare un IN gigante via Supabase REST (URL troppo lungo), facciamo
    # SELECT di tutti i link non-deprecated e diffidiamo lato Python.
    try:
        res = (
            sb.table("fonte")
            .select("id, link, stato_processing")
            .neq("stato_processing", "deprecated")
            .execute()
        )
    except Exception as e:
        logger.exception("[db] SELECT pre-deprecation fallito: {}", e)
        raise

    rows = res.data or []
    to_deprecate_ids = [
        r["id"] for r in rows
        if r.get("link") and r["link"] not in active_links
    ]

    if not to_deprecate_ids:
        logger.info("[db] nessuna fonte da marcare deprecated")
        return 0

    logger.warning(
        "[db] marco {} fonti come deprecated (non piu' presenti nella pagina sorgente)",
        len(to_deprecate_ids),
    )
    try:
        sb.table("fonte").update({
            "stato_processing": "deprecated",
            "attivo": False,
        }).in_("id", to_deprecate_ids).execute()
    except Exception as e:
        logger.exception("[db] UPDATE deprecation fallito: {}", e)
        raise

    return len(to_deprecate_ids)


def count_existing_fonti() -> int:
    """Conteggio totale fonti gia' in DB (per i counters)."""
    sb = get_supabase()
    try:
        res = sb.table("fonte").select("id", count="exact").execute()
        return int(getattr(res, "count", 0) or 0)
    except Exception as e:
        logger.warning("[db] count_existing_fonti fallito: {}", e)
        return 0


def select_known_links() -> set[str]:
    """Set dei `link` gia' presenti in DB (per distinguere new vs updated nei counters)."""
    sb = get_supabase()
    try:
        res = sb.table("fonte").select("link").execute()
        return {r["link"] for r in (res.data or []) if r.get("link")}
    except Exception as e:
        logger.warning("[db] select_known_links fallito: {}", e)
        return set()
