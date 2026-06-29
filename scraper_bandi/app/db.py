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


# ---------------------------------------------------------------------------
# Step 2: bandi
# ---------------------------------------------------------------------------

def select_fonti_ready() -> list[dict[str, Any]]:
    """SELECT * FROM fonte WHERE stato_processing='ready' AND attivo=TRUE.

    Restituisce solo le fonti pronte per lo scraping bandi. Saltiamo
    'connection error' e 'deprecated' come da decisione utente.
    """
    sb = get_supabase()
    try:
        res = (
            sb.table("fonte")
            .select("id, link, tipo_link, formato_link, categoria_programma_id, tipologia_programma_id")
            .eq("stato_processing", "ready")
            .eq("attivo", True)
            .order("id")
            .execute()
        )
    except Exception as e:
        logger.exception("[db] select_fonti_ready fallito: {}", e)
        raise
    rows = res.data or []
    logger.info("[db] select_fonti_ready: {} fonti pronte", len(rows))
    return rows


def upsert_bandi(records: list[dict[str, Any]]) -> dict[str, int]:
    """UPSERT idempotente in `bando` con on_conflict='hash_bando'.

    Difesa anti-duplicati intra-batch sul hash_bando (PostgreSQL ON CONFLICT
    non puo' aggiornare la stessa riga due volte nello stesso comando).

    Inserisce in chunk da 500 per non superare il limite request size di
    Supabase REST.
    """
    if not records:
        return {"processed": 0, "dedup_collisions": 0}

    # Dedup intra-batch su hash_bando preservando il primo
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    collisions = 0
    for r in records:
        h = r.get("hash_bando")
        if not h:
            logger.warning("[db] record bando senza hash_bando: skip {}", r)
            continue
        if h in seen:
            collisions += 1
            continue
        seen.add(h)
        deduped.append(r)

    if collisions:
        logger.info("[db] dedup intra-batch bandi: {} collisioni", collisions)

    sb = get_supabase()
    CHUNK = 500
    total_processed = 0
    for i in range(0, len(deduped), CHUNK):
        chunk = deduped[i : i + CHUNK]
        try:
            sb.table("bando").upsert(chunk, on_conflict="hash_bando").execute()
            total_processed += len(chunk)
            logger.debug("[db] upsert bando chunk {}-{}", i, i + len(chunk))
        except Exception as e:
            logger.exception(
                "[db] upsert bando chunk {}-{} fallito: {}", i, i + len(chunk), e,
            )
            raise

    logger.info(
        "[db] upsert {} record in `bando` (input={}, dedup_collisions={})",
        total_processed, len(records), collisions,
    )
    return {"processed": total_processed, "dedup_collisions": collisions}
