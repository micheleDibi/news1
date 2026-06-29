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


def select_bandi_scraped(limit: int | None = None) -> list[dict[str, Any]]:
    """SELECT bandi pronti per pre-processing (stato_processing='scraped').

    Supabase REST API ha un default `max_rows=1000` per response. Per
    superarlo, paginariamo via `range(offset, offset+page_size-1)`
    finche' la pagina non e' piena.

    Se `limit` e' impostato, ci fermiamo quando lo raggiungiamo.
    """
    sb = get_supabase()
    PAGE = 1000  # supabase default cap
    all_rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        # quanti record vogliamo in QUESTA pagina
        remaining = (limit - len(all_rows)) if limit else None
        page_size = PAGE if not remaining else min(PAGE, remaining)
        if page_size <= 0:
            break

        try:
            res = (
                sb.table("bando")
                .select("id, fonte_id, titolo_raw, descrizione_raw, link_bando, raw_data, tipo_link")
                .eq("stato_processing", "scraped")
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        except Exception as e:
            logger.exception("[db] select_bandi_scraped offset={} fallito: {}", offset, e)
            raise

        rows = res.data or []
        if not rows:
            break
        all_rows.extend(rows)
        logger.debug("[db] select_bandi_scraped: pagina offset={} -> {} righe (totale {})",
                     offset, len(rows), len(all_rows))
        # Se la pagina e' MENO piena del massimo, abbiamo finito.
        if len(rows) < page_size:
            break
        offset += page_size
        if limit and len(all_rows) >= limit:
            break

    logger.info("[db] select_bandi_scraped: {} bandi pronti", len(all_rows))
    return all_rows


def select_fonti_by_ids(fonte_ids: list[int]) -> dict[int, dict[str, Any]]:
    """SELECT delle fonti per gli id specificati. Ritorna dict {id: fonte_row}."""
    if not fonte_ids:
        return {}
    sb = get_supabase()
    try:
        res = (
            sb.table("fonte")
            .select("id, link, tipo_link, categoria_programma_id, tipologia_programma_id")
            .in_("id", fonte_ids)
            .execute()
        )
    except Exception as e:
        logger.exception("[db] select_fonti_by_ids fallito: {}", e)
        raise
    return {row["id"]: row for row in (res.data or [])}


@lru_cache(maxsize=1)
def _categoria_lookup() -> dict[int, str]:
    sb = get_supabase()
    try:
        res = sb.table("categoria_programma").select("id, nome").execute()
        return {r["id"]: r["nome"] for r in (res.data or [])}
    except Exception as e:
        logger.warning("[db] categoria_lookup fallito: {}", e)
        return {}


@lru_cache(maxsize=1)
def _tipologia_lookup() -> dict[int, str]:
    sb = get_supabase()
    try:
        res = sb.table("tipologia_programma").select("id, nome").execute()
        return {r["id"]: r["nome"] for r in (res.data or [])}
    except Exception as e:
        logger.warning("[db] tipologia_lookup fallito: {}", e)
        return {}


def enrich_fonti_with_names(fonti_by_id: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Aggiunge categoria_nome e tipologia_nome a ogni fonte (lookup in cache)."""
    cat_map = _categoria_lookup()
    tip_map = _tipologia_lookup()
    for fonte in fonti_by_id.values():
        fonte["categoria_nome"] = cat_map.get(fonte.get("categoria_programma_id"), "")
        fonte["tipologia_nome"] = tip_map.get(fonte.get("tipologia_programma_id"), "")
    return fonti_by_id


_TRANSIENT_ERROR_MARKERS = (
    "server disconnected",
    "remoteprotocolerror",
    "connection reset",
    "connection aborted",
    "connection closed",
    "read timeout",
    "connecttimeout",
    "503",  # service unavailable
    "504",  # gateway timeout
    "h2: stream",
)


def _is_transient_error(exc: Exception) -> bool:
    """True se l'eccezione e' transient (network/server temporaneo)."""
    s = (str(exc) + " " + type(exc).__name__).lower()
    return any(marker in s for marker in _TRANSIENT_ERROR_MARKERS)


async def update_bandi_postanalysis(
    updates: list[dict[str, Any]],
    concurrency: int = 10,
    max_retries: int = 3,
) -> dict[str, int]:
    """UPDATE batch dei bandi post-analisi LLM con retry su errori transient.

    Ogni update: {id, stato_processing, confidence_score, stato_bando|None,
    rejection_reason|None, data_pubblicazione|None, data_apertura|None,
    data_scadenza|None}. Tutte le chiavi (eccetto 'id') sono incluse nel payload
    UPDATE: chi non vuole sovrascrivere un campo deve ometterlo dal dict.

    NB: NON usiamo upsert(on_conflict='id') perche' postgrest interpreta
    quella sintassi come INSERT ... ON CONFLICT DO UPDATE: prova prima
    l'INSERT con i soli campi passati, che fallisce sul NOT NULL di
    fonte_id (non passato perche' gia' presente nel DB).

    Soluzione: UPDATE per id, in parallelo con asyncio.Semaphore + retry
    con backoff exponential su httpx.RemoteProtocolError ('Server
    disconnected' dopo che HTTP/2 ha cumulato troppi stream sulla stessa
    connessione idle).

    Concorrenza ridotta da 20 a 10 di default per ridurre la pressione
    sulla connessione HTTP/2 persistente di postgrest.
    """
    import asyncio
    import random

    if not updates:
        return {"updated": 0, "failed": 0}

    sb = get_supabase()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _update_one(rec: dict[str, Any]) -> bool:
        rec_id = rec.get("id")
        if rec_id is None:
            logger.warning("[db] update_bandi_postanalysis: record senza id, skip")
            return False
        payload = {k: v for k, v in rec.items() if k != "id"}

        last_err: Exception | None = None
        for attempt in range(max_retries):
            async with sem:
                try:
                    await asyncio.to_thread(
                        lambda: sb.table("bando").update(payload).eq("id", rec_id).execute()
                    )
                    return True
                except Exception as e:
                    last_err = e
                    if not _is_transient_error(e) or attempt == max_retries - 1:
                        break
                    sleep_s = (2 ** attempt) + random.uniform(0, 0.3)
                    logger.debug(
                        "[db] update id={} retry {}/{} dopo {}: sleep {:.1f}s",
                        rec_id, attempt + 1, max_retries, type(e).__name__, sleep_s,
                    )
                    await asyncio.sleep(sleep_s)
        logger.error("[db] update bando id={} fallito definitivamente: {}", rec_id, last_err)
        return False

    # Pass 1: gather con concorrenza alta
    results = await asyncio.gather(*[_update_one(r) for r in updates])
    n_ok = sum(1 for r in results if r)
    n_failed = len(updates) - n_ok

    # Pass 2: retry seriale dei falliti (potrebbe essere un picco transient)
    if n_failed > 0 and n_failed < 100:
        failed_indices = [i for i, ok in enumerate(results) if not ok]
        logger.warning(
            "[db] retry seriale di {} update falliti dopo gather...",
            len(failed_indices),
        )
        recovered = 0
        for i in failed_indices:
            ok = await _update_one(updates[i])
            if ok:
                recovered += 1
        if recovered:
            n_ok += recovered
            n_failed -= recovered
            logger.info("[db] retry seriale ha recuperato {} update", recovered)

    if n_failed:
        logger.warning(
            "[db] update_bandi_postanalysis: {} OK, {} FALLITI (irreversibili)",
            n_ok, n_failed,
        )
    else:
        logger.info("[db] update_bandi_postanalysis: {}/{} OK", n_ok, len(updates))
    return {"updated": n_ok, "failed": n_failed}


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


# ---------------------------------------------------------------------------
# Step v7: enrichment
# ---------------------------------------------------------------------------

def select_bandi_to_enrich(
    limit: int | None = None,
    include_enriched: bool = False,
) -> list[dict[str, Any]]:
    """SELECT bandi candidati al enrichment.

    Criterio default: stato_processing='processed' AND
              (stato_bando IN ('aperto','in apertura prossimamente') OR stato_bando IS NULL).
    Se include_enriched=True: include anche i bandi gia' 'enriched' (per re-run
    idempotente — la fase B sostituira' FK + junction + date eventualmente
    aggiornate).
    Paginato 1000 alla volta per superare il cap default Supabase.
    """
    sb = get_supabase()
    PAGE = 1000
    all_rows: list[dict[str, Any]] = []
    offset = 0

    # Costruisco il filtro: stato_processing='processed' AND
    # (stato_bando=aperto OR stato_bando=in_apertura OR stato_bando IS NULL).
    # supabase-py non ha OR diretto su clausole eterogenee; uso .or_().
    or_clause = (
        "stato_bando.eq.aperto,"
        "stato_bando.eq.in apertura prossimamente,"
        "stato_bando.is.null"
    )
    stato_processing_values = ["processed"]
    if include_enriched:
        stato_processing_values.append("enriched")

    while True:
        remaining = (limit - len(all_rows)) if limit else None
        page_size = PAGE if not remaining else min(PAGE, remaining)
        if page_size <= 0:
            break

        try:
            res = (
                sb.table("bando")
                .select(
                    "id, fonte_id, titolo_raw, descrizione_raw, link_bando, raw_data, "
                    "tipo_link, stato_bando, "
                    "data_pubblicazione, data_apertura, data_scadenza"
                )
                .in_("stato_processing", stato_processing_values)
                .or_(or_clause)
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        except Exception as e:
            logger.exception("[db] select_bandi_to_enrich offset={} fallito: {}", offset, e)
            raise

        rows = res.data or []
        if not rows:
            break
        all_rows.extend(rows)
        logger.debug("[db] select_bandi_to_enrich pagina offset={} -> {} righe (totale {})",
                     offset, len(rows), len(all_rows))
        if len(rows) < page_size:
            break
        offset += page_size
        if limit and len(all_rows) >= limit:
            break

    logger.info("[db] select_bandi_to_enrich: {} bandi candidati", len(all_rows))
    return all_rows


_CATALOGO_TABLES = {
    "tipologie": ("tipologie_bando", "id, nome"),
    "programmi": ("programmi", "id, nome"),
    "modalita": ("modalita_erogazione", "id, nome"),
    "beneficiari": ("beneficiari", "id, nome"),
    "codici_ateco": ("codici_ateco", "id, codice, descrizione"),
    "regioni": ("regioni", "id, nome"),
    "settori": ("settori", "id, nome"),
}


@lru_cache(maxsize=1)
def load_catalogo() -> dict[str, list[dict[str, Any]]]:
    """Carica tutte le 7 tabelle catalogo. Cache singleton.

    Schema:
      tipologie:    {id, nome}
      programmi:    {id, nome}
      modalita:     {id, nome}
      beneficiari:  {id, nome}
      codici_ateco: {id, codice, descrizione}
      regioni:      {id, nome}
      settori:      {id, nome}

    Se una tabella non esiste o e' vuota, ritorna [].
    """
    sb = get_supabase()
    catalogo: dict[str, list[dict[str, Any]]] = {}
    for key, (table, columns) in _CATALOGO_TABLES.items():
        try:
            res = sb.table(table).select(columns).order("id").execute()
            rows = res.data or []
            catalogo[key] = rows
            logger.info("[db] catalogo `{}`: {} record", table, len(rows))
        except Exception as e:
            logger.warning("[db] catalogo `{}` lookup fallito: {}", table, e)
            catalogo[key] = []
    return catalogo


def _is_transient_error_local(exc: Exception) -> bool:
    """Riusa la heuristic gia' definita."""
    return _is_transient_error(exc)


async def update_bando_refinement(bando_id: int, stato_bando: str) -> bool:
    """UPDATE solo stato_bando per la fase A (refinement). NON cambia
    stato_processing (resta 'processed')."""
    import asyncio

    sb = get_supabase()
    payload = {"stato_bando": stato_bando}
    try:
        await asyncio.to_thread(
            lambda: sb.table("bando").update(payload).eq("id", bando_id).execute()
        )
        return True
    except Exception as e:
        logger.exception("[db] update_bando_refinement id={} fallito: {}", bando_id, e)
        return False


_JUNCTION_TABLES = {
    "beneficiari": ("bando_beneficiari", "beneficiario_id"),
    "codici_ateco": ("bando_codici_ateco", "codice_ateco_id"),
    "regioni": ("bando_regioni", "regione_id"),
    "settori": ("bando_settori", "settore_id"),
}


async def update_bando_enriched(
    bando_id: int,
    stato_bando: str,
    tipologia_bando_id: int | None,
    modalita_erogazione_id: int | None,
    programma_id: int | None,
    beneficiari_ids: list[int],
    codici_ateco_ids: list[int],
    regioni_ids: list[int],
    settori_ids: list[int],
    data_pubblicazione: str | None = None,
    data_apertura: str | None = None,
    data_scadenza: str | None = None,
) -> bool:
    """UPDATE bando (FK + stato_processing='enriched') + DELETE-then-INSERT
    per le 4 junction tables.

    Le 3 date sono opzionali: incluse nel payload UPDATE solo se non None
    (override scraper solo se LLM ha passato il gate substring + source).

    NB: Supabase REST non ha transazioni multi-table. Se uno step fallisce,
    log WARNING e RETURN False. Il bando resta in 'processed' (la transition
    a 'enriched' viene fatta SOLO se tutti gli UPDATE/INSERT sono OK).
    Idempotente: re-run sostituisce le junction esistenti.
    """
    import asyncio

    sb = get_supabase()

    # Step 1: DELETE junction esistenti
    for key, (table, _fk) in _JUNCTION_TABLES.items():
        try:
            await asyncio.to_thread(
                lambda t=table: sb.table(t).delete().eq("bando_id", bando_id).execute()
            )
        except Exception as e:
            logger.warning(
                "[db] DELETE junction {} per bando_id={} fallito: {}",
                table, bando_id, e,
            )
            # Continue anyway: l'INSERT successivo potrebbe duplicare ma in
            # genere le junction hanno UNIQUE (bando_id, xxx_id) o PK composta.

    # Step 2: INSERT junction nuove
    junction_data = [
        ("beneficiari", beneficiari_ids),
        ("codici_ateco", codici_ateco_ids),
        ("regioni", regioni_ids),
        ("settori", settori_ids),
    ]
    for key, ids in junction_data:
        if not ids:
            continue
        table, fk = _JUNCTION_TABLES[key]
        records = [{"bando_id": bando_id, fk: i} for i in ids]
        try:
            await asyncio.to_thread(
                lambda t=table, r=records: sb.table(t).insert(r).execute()
            )
        except Exception as e:
            logger.exception(
                "[db] INSERT junction {} per bando_id={} fallito: {}",
                table, bando_id, e,
            )
            return False

    # Step 3: UPDATE bando (FK + stato_processing='enriched' + stato_bando +
    # eventuali date che hanno passato il gate dell'enricher).
    payload: dict[str, Any] = {
        "tipologia_bando_id": tipologia_bando_id,
        "modalita_erogazione_id": modalita_erogazione_id,
        "programma_id": programma_id,
        "stato_bando": stato_bando,
        "stato_processing": "enriched",
    }
    if data_pubblicazione is not None:
        payload["data_pubblicazione"] = data_pubblicazione
    if data_apertura is not None:
        payload["data_apertura"] = data_apertura
    if data_scadenza is not None:
        payload["data_scadenza"] = data_scadenza
    try:
        await asyncio.to_thread(
            lambda: sb.table("bando").update(payload).eq("id", bando_id).execute()
        )
        return True
    except Exception as e:
        logger.exception("[db] UPDATE bando id={} fallito: {}", bando_id, e)
        return False


# ---------------------------------------------------------------------------
# Step v8: skill SEO (enriched -> completed)
# ---------------------------------------------------------------------------

def select_bandi_to_complete(
    limit: int | None = None,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    """SELECT bandi candidati alla skill SEO.

    Criterio default: stato_processing='enriched'.
    Se include_completed=True: include anche 'completed' (re-run idempotente).
    Paginato 1000 per superare il cap default Supabase.

    Colonne selezionate: tutto quanto serve a build_bando_input_context (raw
    scraper + FK + date estratte dall'enricher).
    """
    sb = get_supabase()
    PAGE = 1000
    all_rows: list[dict[str, Any]] = []
    offset = 0

    stato_values = ["enriched"]
    if include_completed:
        stato_values.append("completed")

    while True:
        remaining = (limit - len(all_rows)) if limit else None
        page_size = PAGE if not remaining else min(PAGE, remaining)
        if page_size <= 0:
            break

        try:
            res = (
                sb.table("bando")
                .select(
                    "id, fonte_id, titolo_raw, descrizione_raw, link_bando, raw_data, "
                    "tipo_link, stato_bando, "
                    "data_pubblicazione, data_apertura, data_scadenza, "
                    "tipologia_bando_id, modalita_erogazione_id, programma_id"
                )
                .in_("stato_processing", stato_values)
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        except Exception as e:
            logger.exception("[db] select_bandi_to_complete offset={} fallito: {}", offset, e)
            raise

        rows = res.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
        if limit and len(all_rows) >= limit:
            break

    logger.info("[db] select_bandi_to_complete: {} bandi candidati (include_completed={})",
                len(all_rows), include_completed)
    return all_rows


def _select_junction_ids(table: str, fk_column: str, bando_id: int) -> list[int]:
    sb = get_supabase()
    try:
        res = sb.table(table).select(fk_column).eq("bando_id", bando_id).execute()
        return [r[fk_column] for r in (res.data or []) if r.get(fk_column) is not None]
    except Exception as e:
        logger.warning("[db] junction {} per bando_id={} fallito: {}", table, bando_id, e)
        return []


def build_bando_input_context(
    bando_row: dict[str, Any],
    catalogo: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compone il dict di contesto per il prompt skill: tutti i dati DB
    accumulati nelle fasi precedenti, con FK + junction risolte a nomi.

    Riusa load_catalogo() singleton per i nomi.
    """
    bando_id = bando_row["id"]

    # FK -> nomi
    def _lookup_name(catalog_key: str, target_id: int | None) -> str | None:
        if target_id is None:
            return None
        for row in catalogo.get(catalog_key, []):
            if row.get("id") == target_id:
                return row.get("nome")
        return None

    tipologia_nome = _lookup_name("tipologie", bando_row.get("tipologia_bando_id"))
    modalita_nome = _lookup_name("modalita", bando_row.get("modalita_erogazione_id"))
    programma_nome = _lookup_name("programmi", bando_row.get("programma_id"))

    # Junction -> nomi
    beneficiari_ids = _select_junction_ids("bando_beneficiari", "beneficiario_id", bando_id)
    regioni_ids = _select_junction_ids("bando_regioni", "regione_id", bando_id)
    settori_ids = _select_junction_ids("bando_settori", "settore_id", bando_id)
    ateco_ids = _select_junction_ids("bando_codici_ateco", "codice_ateco_id", bando_id)

    def _names_from_catalog(catalog_key: str, ids: list[int]) -> list[str]:
        if not ids:
            return []
        by_id = {row["id"]: row.get("nome") for row in catalogo.get(catalog_key, [])}
        return [by_id[i] for i in ids if by_id.get(i)]

    beneficiari_nomi = _names_from_catalog("beneficiari", beneficiari_ids)
    regioni_nomi = _names_from_catalog("regioni", regioni_ids)
    settori_nomi = _names_from_catalog("settori", settori_ids)

    # Codici ATECO: schema diverso (codice + descrizione)
    ateco_by_id = {row["id"]: row for row in catalogo.get("codici_ateco", [])}
    ateco_records: list[dict[str, str]] = []
    for aid in ateco_ids:
        row = ateco_by_id.get(aid)
        if row:
            ateco_records.append({
                "codice": row.get("codice", ""),
                "descrizione": row.get("descrizione", ""),
            })

    return {
        "id": bando_id,
        "fonte_id": bando_row.get("fonte_id"),
        "titolo_raw": bando_row.get("titolo_raw"),
        "descrizione_raw": bando_row.get("descrizione_raw"),
        "raw_data": bando_row.get("raw_data") or {},
        "link_bando": bando_row.get("link_bando"),
        "tipo_link": bando_row.get("tipo_link"),
        "stato_bando": bando_row.get("stato_bando"),
        "data_pubblicazione": bando_row.get("data_pubblicazione"),
        "data_apertura": bando_row.get("data_apertura"),
        "data_scadenza": bando_row.get("data_scadenza"),
        "tipologia": tipologia_nome,
        "modalita_erogazione": modalita_nome,
        "programma": programma_nome,
        "beneficiari": beneficiari_nomi,
        "codici_ateco": ateco_records,
        "regioni": regioni_nomi,
        "settori": settori_nomi,
    }


def slug_exists(slug: str, exclude_bando_id: int | None = None) -> bool:
    """True se lo slug e' gia' usato da un altro bando (UNIQUE in DB)."""
    sb = get_supabase()
    try:
        q = sb.table("bando").select("id").eq("slug", slug)
        if exclude_bando_id is not None:
            q = q.neq("id", exclude_bando_id)
        res = q.limit(1).execute()
        return bool(res.data)
    except Exception as e:
        logger.warning("[db] slug_exists({}) fallito: {}", slug, e)
        return False


_SEO_PAYLOAD_COLUMNS = (
    "slug",
    "titolo",
    "titolo_breve",
    "descrizione_breve",
    "contenuto",
    "livello",
    "allegati",
    "ente_erogatore",
    "area_geografica",
    "tematica",
    "importo_totale_eur",
    "importo_max_per_progetto_eur",
    "link_candidatura",
    "link_candidatura_source",
)


async def reconcile_canonical_key(
    bando_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Calcola canonical_key dal payload SEO completo + gestisce dedup cross-source.

    Pipeline:
      1. compute canonical_key = SHA256(norm_titolo|norm_ente|data_scadenza|importo)
      2. Se canonical_key=None (titolo o ente mancanti): skip, no-op.
      3. SELECT esistente con quella canonical_key (escludendo self).
      4a. Se nessuno la possiede: UPDATE bando SET canonical_key=... (claim).
      4b. Se gia' esiste un master con quella key:
          - UPDATE bando master SET fonti_aggiuntive = array_append(..., self.fonte_id)
            (se non gia' presente).
          - UPDATE self SET stato_processing = 'completed_duplicate'.

    Ritorna: {action: 'created'|'merged_into_master'|'skipped'|'failed',
              master_id?: int, canonical_key?: str}
    """
    from .normalize import compute_canonical_key

    titolo = payload.get("titolo") or payload.get("titolo_breve")
    ente = payload.get("ente_erogatore")
    data_scadenza = payload.get("data_scadenza")
    importo = payload.get("importo_totale_eur")

    ck = compute_canonical_key(titolo, ente, data_scadenza, importo)
    if not ck:
        return {"action": "skipped", "reason": "no_titolo_or_ente"}

    sb = get_supabase()

    # Recupera fonte_id del bando corrente (servira' se siamo duplicato).
    try:
        cur_res = await asyncio.to_thread(
            lambda: sb.table("bando").select("id, fonte_id, canonical_key").eq("id", bando_id).single().execute()
        )
        cur_row = cur_res.data or {}
    except Exception as e:
        logger.warning("[db/reconcile] bando_id={} SELECT corrente fallito: {}", bando_id, e)
        return {"action": "failed", "error": str(e)}

    # Se gia' ha la stessa canonical_key, no-op (idempotente).
    if cur_row.get("canonical_key") == ck:
        return {"action": "noop", "canonical_key": ck}

    fonte_id_cur = cur_row.get("fonte_id")

    # Cerca un master esistente con quella canonical_key (escluso self).
    try:
        master_res = await asyncio.to_thread(
            lambda: sb.table("bando")
            .select("id, fonti_aggiuntive")
            .eq("canonical_key", ck)
            .neq("id", bando_id)
            .limit(1)
            .execute()
        )
        master_rows = master_res.data or []
    except Exception as e:
        logger.warning("[db/reconcile] bando_id={} SELECT master fallito: {}", bando_id, e)
        return {"action": "failed", "error": str(e)}

    if not master_rows:
        # Nessun duplicato: claim canonical_key per noi.
        try:
            await asyncio.to_thread(
                lambda: sb.table("bando").update({"canonical_key": ck}).eq("id", bando_id).execute()
            )
            return {"action": "created", "canonical_key": ck}
        except Exception as e:
            # Race condition possibile: qualcuno ha appena claimato la key.
            # Re-try la SELECT del master.
            logger.debug("[db/reconcile] bando_id={} claim fallito ({}), re-check master", bando_id, e)
            try:
                master_res2 = await asyncio.to_thread(
                    lambda: sb.table("bando")
                    .select("id, fonti_aggiuntive")
                    .eq("canonical_key", ck)
                    .neq("id", bando_id)
                    .limit(1)
                    .execute()
                )
                master_rows = master_res2.data or []
            except Exception as e2:
                return {"action": "failed", "error": str(e2)}

    if master_rows:
        master = master_rows[0]
        master_id = master["id"]
        master_fonti = master.get("fonti_aggiuntive") or []

        # Append fonte_id corrente all'array del master se non gia' presente.
        if fonte_id_cur is not None and fonte_id_cur not in master_fonti:
            new_fonti = list(master_fonti) + [fonte_id_cur]
            try:
                await asyncio.to_thread(
                    lambda: sb.table("bando").update({"fonti_aggiuntive": new_fonti}).eq("id", master_id).execute()
                )
            except Exception as e:
                logger.warning("[db/reconcile] bando_id={} append fonti_aggiuntive fallito: {}",
                               master_id, e)

        # Marca questo bando come 'completed_duplicate'.
        try:
            await asyncio.to_thread(
                lambda: sb.table("bando").update({
                    "stato_processing": "completed_duplicate",
                }).eq("id", bando_id).execute()
            )
        except Exception as e:
            logger.warning("[db/reconcile] bando_id={} mark duplicate fallito: {}", bando_id, e)
            return {"action": "failed", "error": str(e)}

        logger.info(
            "[db/reconcile] bando_id={} merged into master_id={} (canonical_key={})",
            bando_id, master_id, ck[:12] + "...",
        )
        return {"action": "merged_into_master", "master_id": master_id, "canonical_key": ck}

    return {"action": "failed", "reason": "unexpected_state"}


async def update_bando_completed(
    bando_id: int,
    payload: dict[str, Any],
    mark_completed: bool = True,
) -> bool:
    """UPDATE bando con i 14 campi del payload skill + stato_processing='completed'.

    payload deve contenere SOLO i 14 campi consentiti (filtrati comunque per
    sicurezza). Idempotente: re-run sostituisce i valori esistenti.
    """
    import asyncio

    sb = get_supabase()
    update_dict: dict[str, Any] = {
        col: payload[col] for col in _SEO_PAYLOAD_COLUMNS if col in payload
    }
    if mark_completed:
        update_dict["stato_processing"] = "completed"

    try:
        await asyncio.to_thread(
            lambda: sb.table("bando").update(update_dict).eq("id", bando_id).execute()
        )
        return True
    except Exception as e:
        logger.exception("[db] update_bando_completed id={} fallito: {}", bando_id, e)
        return False
