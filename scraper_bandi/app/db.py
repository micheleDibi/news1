"""Client Supabase DB B + helper per upsert e mark-deprecated della tabella `fonte`.

In coda al modulo vive `controllo` (classe `Controllo`): l'adattatore che sa
quali colonne e quali RPC il DB espone davvero, perche' le migrazioni v11 le
applica il committente e il codice deve girare anche prima (§16.2 M12).
"""
from __future__ import annotations

import asyncio
from datetime import datetime as datetime_cls
from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, Sequence

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

    v10: le fonti con `discoverable=FALSE` (es. fonti esterne manuali come
    Obiettivo Europa) sono ESCLUSE dal deprecation: non sono in OpenCoesione
    ma sono comunque attive e gestite separatamente.

    Ritorna il numero di righe segnate come deprecate in questo run.
    """
    sb = get_supabase()

    # Per evitare un IN gigante via Supabase REST (URL troppo lungo), facciamo
    # SELECT di tutti i link non-deprecated e diffidiamo lato Python.
    # v10: filtra solo discoverable=TRUE.
    try:
        res = (
            sb.table("fonte")
            .select("id, link, stato_processing, discoverable")
            .neq("stato_processing", "deprecated")
            .execute()
        )
    except Exception as e:
        logger.exception("[db] SELECT pre-deprecation fallito: {}", e)
        raise

    rows = res.data or []
    to_deprecate_ids = [
        r["id"] for r in rows
        if r.get("link")
           and r["link"] not in active_links
           and r.get("discoverable", True)  # default TRUE per back-compat
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


async def update_bando_refinement(
    bando_id: int,
    stato_bando: str,
    confidence: float | None = None,
) -> bool:
    """UPDATE stato_bando (e, se passata, confidence_score) per la fase A
    (refinement). NON cambia stato_processing (resta 'processed').

    Fix 8.a.11: il chiamante la invoca SOLO con stato non nullo e
    confidenza >= 0.6; la confidenza viene persistita per l'audit."""
    sb = get_supabase()
    payload: dict[str, Any] = {"stato_bando": stato_bando}
    if confidence is not None:
        payload["confidence_score"] = float(confidence)
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

#: Colonne che lo step SEO legge sempre: esistono tutte sul DB vivo, `allegati`
#: compresa (e' gia' in `_SEO_PAYLOAD_COLUMNS`).
COLONNE_SEO_BASE: tuple[str, ...] = (
    "id", "fonte_id", "titolo_raw", "descrizione_raw", "link_bando", "raw_data",
    "tipo_link", "stato_bando", "stato_processing",
    "data_pubblicazione", "data_apertura", "data_scadenza",
    "tipologia_bando_id", "modalita_erogazione_id", "programma_id",
    "allegati",
)

#: Colonne della migrazione 01: senza di loro `bando_seo_runner.scegli_fonte`
#: ricadrebbe sempre su `link_bando` — per i 1 702 OE, l'aggregatore — e
#: l'intestazione «PAGINA UFFICIALE: <url>» non nascerebbe mai. Si chiedono
#: solo se lo schema le espone davvero: su un DB non ancora migrato sarebbero
#: un 42703 che ferma lo step SEO su tutte le righe.
COLONNE_SEO_RESOLVER: tuple[str, ...] = (
    "fonte_ufficiale_url", "fonte_ufficiale_stato",
)


def _colonne_con_opzionali(
    tabella: str, base: Sequence[str], opzionali: Sequence[str], strumento: Any,
) -> str:
    """`select=` con le colonne base piu' le opzionali che lo schema espone.

    Diverso da `_colonne_disponibili`: li' uno schema illeggibile significa
    «chiedile tutte», perche' le desiderate esistono gia' sul DB vivo. Qui le
    opzionali sono colonne nuove, e nel dubbio non si chiedono.
    """
    presenti = strumento.colonne(tabella)
    scelte = list(base) + [c for c in opzionali if c in presenti]
    return ",".join(dict.fromkeys(scelte))


def select_bandi_to_complete(
    limit: int | None = None,
    include_completed: bool = False,
    *,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """SELECT bandi candidati alla skill SEO.

    Criterio default: stato_processing='enriched'.
    Se include_completed=True: include anche 'completed' (re-run idempotente).
    Paginato 1000 per superare il cap default Supabase.

    Colonne selezionate: tutto quanto serve a build_bando_input_context (raw
    scraper + FK + date estratte dall'enricher), piu' `allegati` e — quando la
    migrazione 01 e' applicata — `fonte_ufficiale_url`/`fonte_ufficiale_stato`,
    che sono cio' con cui §5 alimenta la SEO e il gate degli URL.
    """
    sb = get_supabase()
    colonne = _colonne_con_opzionali(
        "bando", COLONNE_SEO_BASE, COLONNE_SEO_RESOLVER, _controllo(strumento),
    )
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
                .select(colonne)
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


def _payload_completed(
    payload: dict[str, Any],
    mark_completed: bool = True,
    gia_pubblicato: bool = False,
) -> dict[str, Any]:
    """Filtro puro del payload SEO prima dell'UPDATE (testabile senza DB).

    - solo le colonne di _SEO_PAYLOAD_COLUMNS;
    - gia_pubblicato=True (riga gia' 'completed', quindi letta da BandoFit e
      dal frontend): `slug` e `titolo` restano congelati (lo slug e' l'URL
      pubblico, il titolo e' snapshot in saved_bandi/consultation_requests di
      BandoFit) e stato_processing NON viene toccato;
    - altrimenti mark_completed aggiunge stato_processing='completed'.
    """
    update_dict: dict[str, Any] = {
        col: payload[col] for col in _SEO_PAYLOAD_COLUMNS if col in payload
    }
    if gia_pubblicato:
        update_dict.pop("slug", None)
        update_dict.pop("titolo", None)
    elif mark_completed:
        update_dict["stato_processing"] = "completed"
    return update_dict


async def update_bando_completed(
    bando_id: int,
    payload: dict[str, Any],
    mark_completed: bool = True,
    gia_pubblicato: bool = False,
) -> bool:
    """UPDATE bando con i 14 campi del payload skill + stato_processing='completed'.

    payload deve contenere SOLO i 14 campi consentiti (filtrati comunque per
    sicurezza). Idempotente: re-run sostituisce i valori esistenti.
    Con gia_pubblicato=True (re-run su una riga gia' 'completed') slug e
    titolo non vengono riscritti e stato_processing resta com'e'.
    """
    sb = get_supabase()
    update_dict = _payload_completed(
        payload, mark_completed=mark_completed, gia_pubblicato=gia_pubblicato,
    )

    try:
        await asyncio.to_thread(
            lambda: sb.table("bando").update(update_dict).eq("id", bando_id).execute()
        )
        return True
    except Exception as e:
        logger.exception("[db] update_bando_completed id={} fallito: {}", bando_id, e)
        return False


# ---------------------------------------------------------------------------
# db.controllo — adattatore sullo schema reale (piano §16.2 M12, A21)
# ---------------------------------------------------------------------------
#
# Le migrazioni 01-07 le applica il committente nel SQL Editor, quando vuole.
# Nel frattempo il DB ha 36 colonne su `bando` e nessuna delle RPC nuove.
# Senza un adattatore, al primo rilascio un `.lt('tentativi_seo', 3)`
# risponderebbe 42703 («column does not exist») e fermerebbe l'intero step SEO
# su tutte le righe: un errore di configurazione diventerebbe un blocco totale.
#
# Regola: ogni filtro, ogni scrittura e ogni `.rpc(...)` su un oggetto nuovo
# passa da `controllo.ha(...)` / `controllo.rpc_disponibile(...)`; chi non trova
# l'oggetto degrada (lo step ritorna `{'status':'ok','saltato':'colonne_assenti'}`)
# invece di sollevare.
#
# Lo schema si legge UNA volta per processo dall'endpoint OpenAPI di PostgREST
# (`GET /rest/v1/`), che elenca tabelle, colonne e funzioni esposte. Un errore
# di rete non e' un'eccezione: e' un insieme vuoto, cioe' «non so, degrada».


class Controllo:
    """Conoscenza dello schema realmente esposto. Un'istanza per processo."""

    def __init__(
        self,
        fornitore_schema: Callable[[], dict[str, Any]] | None = None,
        *,
        client_factory: Callable[[], Client] | None = None,
    ) -> None:
        # `fornitore_schema` e' il punto di iniezione dei test: nessuna rete.
        self._fornitore = fornitore_schema
        self._client_factory = client_factory or get_supabase
        self._schema: dict[str, Any] | None = None
        self._letto = False

    # --- schema ------------------------------------------------------------

    def azzera(self) -> None:
        """Dimentica lo schema letto (test, e dopo una migrazione applicata)."""
        self._schema = None
        self._letto = False

    def schema(self) -> dict[str, Any]:
        """Il documento OpenAPI, letto una sola volta. `{}` se non leggibile."""
        if self._letto:
            return self._schema or {}
        self._letto = True
        fornitore = self._fornitore or _schema_openapi
        try:
            self._schema = fornitore() or {}
        except Exception as e:
            # Degradare e' il comportamento voluto: senza schema il codice non
            # filtra sulle colonne nuove e non scrive, ma continua a girare.
            logger.warning("[db.controllo] schema non leggibile, degrado: {}", e)
            self._schema = {}
        return self._schema

    # --- interrogazioni ----------------------------------------------------

    def colonne(self, tabella: str) -> frozenset[str]:
        """Colonne esposte per `tabella`; insieme vuoto = «non so»."""
        schema = self.schema()
        definizioni = schema.get("definitions")
        if not isinstance(definizioni, dict):
            # PostgREST >= 12 / OpenAPI 3: components.schemas
            componenti = schema.get("components")
            definizioni = componenti.get("schemas") if isinstance(componenti, dict) else None
        if not isinstance(definizioni, dict):
            return frozenset()
        voce = definizioni.get(tabella)
        proprieta = voce.get("properties") if isinstance(voce, dict) else None
        if not isinstance(proprieta, dict):
            return frozenset()
        return frozenset(proprieta)

    def ha(self, tabella: str, colonna: str) -> bool:
        """Vero solo se la colonna esiste davvero: nel dubbio, falso."""
        return colonna in self.colonne(tabella)

    def ha_tutte(self, tabella: str, colonne: Iterable[str]) -> bool:
        presenti = self.colonne(tabella)
        return bool(presenti) and all(c in presenti for c in colonne)

    def tabella_esiste(self, tabella: str) -> bool:
        return bool(self.colonne(tabella))

    def rpc_disponibile(self, nome: str) -> bool:
        """Vero se PostgREST espone `/rpc/<nome>`."""
        percorsi = self.schema().get("paths")
        return isinstance(percorsi, dict) and f"/rpc/{nome}" in percorsi

    def colonne_mancanti(self, tabella: str, payload: Iterable[str]) -> tuple[str, ...]:
        presenti = self.colonne(tabella)
        if not presenti:
            return tuple(payload)
        return tuple(c for c in payload if c not in presenti)

    # --- scrittura ---------------------------------------------------------

    def aggiorna(
        self,
        tabella: str,
        id_riga: Any,
        payload: dict[str, Any],
        *,
        colonna_id: str = "id",
    ) -> dict[str, Any]:
        """UPDATE che diventa un no-op se le colonne non esistono ancora.

        Le chiavi assenti dallo schema vengono scartate (con log); se non resta
        niente, non parte nessuna richiesta. Scartare invece di sollevare e'
        cio' che rende il codice di oggi installabile prima delle migrazioni.
        Ritorna `{scritto, ignorate, motivo}`.
        """
        if not payload:
            return {"scritto": False, "ignorate": (), "motivo": "payload vuoto"}

        mancanti = self.colonne_mancanti(tabella, payload)
        da_scrivere = {k: v for k, v in payload.items() if k not in mancanti}
        if mancanti:
            logger.info(
                "[db.controllo] {}: colonne assenti, ignorate {} (id={})",
                tabella, list(mancanti), id_riga,
            )
        if not da_scrivere:
            return {"scritto": False, "ignorate": mancanti, "motivo": "colonne_assenti"}

        try:
            client = self._client_factory()
            client.table(tabella).update(da_scrivere).eq(colonna_id, id_riga).execute()
        except Exception as e:
            logger.warning("[db.controllo] update {} id={} fallito: {}", tabella, id_riga, e)
            return {"scritto": False, "ignorate": mancanti, "motivo": str(e)}
        return {"scritto": True, "ignorate": mancanti, "motivo": ""}


def _schema_openapi() -> dict[str, Any]:
    """Una sola GET all'endpoint OpenAPI di PostgREST.

    La chiave sta solo nelle intestazioni e non compare mai nei log: in caso di
    errore si registra lo stato HTTP, non l'URL con i parametri.
    """
    import httpx

    impostazioni = get_settings()
    radice = impostazioni.supabase_url.rstrip("/") + "/rest/v1/"
    intestazioni = {
        "apikey": impostazioni.supabase_service_key,
        "Authorization": f"Bearer {impostazioni.supabase_service_key}",
        "Accept": "application/openapi+json",
    }
    risposta = httpx.get(radice, headers=intestazioni, timeout=10.0)
    risposta.raise_for_status()
    return risposta.json()


# Istanza di processo: `from .db import controllo`.
controllo = Controllo()


# ---------------------------------------------------------------------------
# Resolver della fonte ufficiale (piano §5) — letture e scritture nuove
# ---------------------------------------------------------------------------
#
# Regola di questa sezione, senza eccezioni: **ogni** oggetto nuovo passa da
# `controllo`. Le migrazioni v11 non sono applicate sul DB vivo, quindi una
# `select` su `bando_controllo` o un filtro su `fonte_ufficiale_stato`
# risponderebbero PGRST205/42703 e fermerebbero lo step su tutte le righe.
# Qui una colonna assente non e' un errore: e' un `{'saltato': 'colonne_assenti'}`
# con un log, e il giro prosegue.
#
# Nessuna funzione di questa sezione solleva: il resolver e' uno step di una
# pipeline che deve arrivare in fondo anche quando il DB e' a meta' strada.

TABELLA_CONTROLLO = "bando_controllo"
TABELLA_LINK = "bando_link"
TABELLA_EVENTO = "bando_evento"
TABELLA_DOMINIO = "dominio_ufficiale"
TABELLA_RUN = "pipeline_run"
RPC_FONDI = "bando_fondi"

#: I parametri di `bando_fondi`, **nell'ordine della firma** (04:795-799):
#: prima il doppione, poi il master. PostgREST risolve per nome, ma l'ordine
#: e' scritto qui apposta: chi rileggesse la chiamata dovendola riparare a
#: mano non deve poter dedurre l'ordine sbagliato e fondere il master dentro
#: il doppione.
PARAMETRI_FONDI: tuple[str, ...] = ("p_dup", "p_master", "p_motivo")

#: Le otto colonne che il resolver scrive su `bando`. Nient'altro: mai
#: `stato_processing`, `slug`, `contenuto`, `data_pubblicazione`, `updated_at`.
#:
#: `fonte_ufficiale_e_atto` NON e' qui: non e' una colonna di `bando` ma un
#: `EXISTS` calcolato dalla vista `bando_pubblico` su
#: `bando_link.tipo = 'atto'` (migrazione 05). Il resolver lo esprime scrivendo
#: il tipo giusto sulla riga di `bando_link`; provare a scriverlo qui darebbe
#: una colonna inesistente, silenziosamente ignorata, e un flag sempre falso.
COLONNE_FONTE_UFFICIALE: tuple[str, ...] = (
    "fonte_ufficiale_url",
    "fonte_ufficiale_host",
    "fonte_ufficiale_tipo",
    "fonte_ufficiale_stato",
    "fonte_ufficiale_confidenza",
    "fonte_ufficiale_metodo",
    "fonte_ufficiale_verificata_at",
    "fonte_ufficiale_link_id",
)

#: Colonne che il resolver non deve **mai** toccare su `bando` (§5). Le prime
#: tre sono la garanzia che l'HTML della scheda OE non finisca in tabella; le
#: altre sono il contratto con BandoFit su slug e pubblicazione.
CHIAVI_VIETATE_BANDO: tuple[str, ...] = (
    "testo_norm", "oe_html", "html", "slug", "contenuto",
    "stato_processing", "data_pubblicazione", "updated_at",
)
PREFISSI_VIETATI_BANDO: tuple[str, ...] = ("impronta_", "impronte_")


class PayloadBandoVietato(AssertionError):
    """Un payload verso `bando` contiene una chiave che il resolver non scrive.

    E' un `AssertionError` di proposito: non e' una condizione da gestire, e'
    un errore di programmazione. Il piano (§5) chiede un assert nel chokepoint
    di scrittura proprio perche' l'unica difesa contro «l'HTML della scheda
    finisce in una colonna» e' che il programma si fermi prima.
    """


def assicura_payload_bando(payload: Mapping[str, Any]) -> None:
    """Chokepoint: nessun testo, nessuna impronta, nessuno slug verso `bando`."""
    colpevoli = sorted(
        chiave for chiave in payload
        if chiave in CHIAVI_VIETATE_BANDO or chiave.startswith(PREFISSI_VIETATI_BANDO)
    )
    if colpevoli:
        raise PayloadBandoVietato(
            f"payload verso `bando` con chiavi vietate dal resolver: {colpevoli}"
        )


def _client(client: Any | None = None) -> Any:
    return client if client is not None else get_supabase()


def _controllo(strumento: Any | None = None) -> Any:
    return strumento if strumento is not None else controllo


def _saltato(motivo: str, **extra: Any) -> dict[str, Any]:
    return {"status": "ok", "saltato": motivo, **extra}


# --- letture ---------------------------------------------------------------

#: Colonne lette dal resolver. Esplicite (mai `*`): su `bando` un `select=*`
#: porterebbe dentro `raw_data` di tutte le righe, e dopo la 07 alcune colonne
#: non esistono piu'.
COLONNE_RESOLVER: tuple[str, ...] = (
    "id", "titolo", "titolo_raw", "link_bando", "ente_erogatore", "area_geografica",
    "data_scadenza", "data_apertura", "importo_totale_eur", "stato_processing",
    "stato_bando", "fonte_id", "raw_data", "contenuto", "allegati",
)


def _colonne_disponibili(tabella: str, desiderate: Sequence[str], strumento: Any) -> str:
    """`select=` con le sole colonne che lo schema espone davvero.

    Se lo schema non e' leggibile (`colonne()` vuoto) si chiedono tutte le
    desiderate: e' il comportamento di oggi, che su un DB non ancora migrato
    funziona perche' quelle colonne esistono gia'.
    """
    presenti = strumento.colonne(tabella)
    if not presenti:
        return ",".join(desiderate)
    scelte = [c for c in desiderate if c in presenti]
    return ",".join(scelte or ["id"])


def _pagina(query: Any, limit: int | None, offset: int) -> Any:
    """`limit`/`offset` su una query gia' ordinata, con le regole del package.

    Due convenzioni in un posto solo, perche' erano ricopiate in cinque select
    e in due di esse erano state ricopiate male:

    * `limit is not None` e non `if limit`: uno zero e' un limite, ed e' quello
      che un operatore mette per non toccare niente. Trattarlo come «nessun
      limite» farebbe girare `--limit 0 --attivo` sull'intero corpus: l'esatto
      contrario di cio' che ha chiesto;
    * `range()` e' l'unico modo di scorrere oltre i primi N con PostgREST, ed e'
      inclusivo agli estremi. Serve a chi salta le righe gia' lavorate: l'ordine
      e' per `id`, quindi l'offset e' stabile fra una pagina e l'altra.
    """
    offset = max(0, int(offset or 0))
    if limit is not None and offset and int(limit) > 0:
        return query.range(offset, offset + int(limit) - 1)
    if limit is not None:
        # Anche `--limit 0 --offset 800`: un `range(800, 799)` sarebbe un
        # intervallo vuoto alla rovescia, e un limite di zero righe si dice
        # con `limit(0)`.
        return query.limit(int(limit))
    if offset:
        return query.range(offset, offset + 999)
    return query


#: Quante righe PostgREST restituisce al massimo in una risposta (`max-rows`,
#: configurato sul server, misurato 1 000 su questo progetto). Non e' una
#: convenzione nostra ed e' la trappola piu' silenziosa del client: una
#: `.limit(5000)` non solleva e non avvisa, restituisce 1 000 righe come se
#: fossero tutte. Ogni lettura che puo' superarlo va **scorsa**, non limitata.
PAGINA_POSTGREST = 1000


def _scorri(
    costruisci: Callable[[int, int], Any],
    *,
    tetto: int | None = None,
    pagina: int = PAGINA_POSTGREST,
) -> list[dict[str, Any]]:
    """Legge una select a pagine finche' il server smette di dare righe.

    `costruisci(quanto, salto)` deve restituire una query **nuova** gia'
    impaginata (di norma `_pagina(costruisci_query(), quanto, salto)`): i
    builder di postgrest accumulano i parametri con `add`, quindi riusare lo
    stesso oggetto per due pagine produce `?limit=1000&limit=1000&offset=...`.

    Si ferma quando la pagina torna piu' corta di quanto chiesto (le righe sono
    finite) oppure al `tetto`, che resta l'unico limite dichiarato.
    """
    raccolte: list[dict[str, Any]] = []
    salto = 0
    while True:
        quanto = min(pagina, tetto - len(raccolte)) if tetto is not None else pagina
        if quanto <= 0:
            break
        blocco = list(costruisci(quanto, salto).execute().data or [])
        raccolte.extend(blocco)
        salto += len(blocco)
        if len(blocco) < quanto:
            break
    return raccolte


#: Quanti id per volta si passano a un `in_()`. Due motivi per non passarli
#: tutti: la URL che ne esce ha un limite lato server, e la risposta resta
#: comunque tagliata a `PAGINA_POSTGREST` (le righe per id possono essere piu'
#: di una: `bando_link` ne ha in media una e mezza).
BLOCCO_ID = 200


def _a_blocchi(valori: Sequence[Any], dimensione: int = BLOCCO_ID) -> list[list[Any]]:
    """Spezza una lista di id in blocchi, scartando i `None`."""
    elenco = [v for v in valori if v is not None]
    return [elenco[i:i + dimensione] for i in range(0, len(elenco), dimensione)]


def _per_id(
    costruisci: Callable[[list[Any]], Any],
    ids: Sequence[Any],
    *,
    ordine: str = "id",
) -> list[dict[str, Any]]:
    """Legge per lista di id: a blocchi, e ogni blocco scorso fino in fondo.

    `costruisci(blocco)` restituisce la query gia' filtrata sul blocco, senza
    ordinamento ne' impaginazione: li mette questa.
    """
    righe: list[dict[str, Any]] = []
    for blocco in _a_blocchi(ids):
        righe.extend(_scorri(
            lambda quanto, salto, _b=blocco: _pagina(
                costruisci(_b).order(ordine), quanto, salto),
        ))
    return righe


def select_bandi_da_risolvere(
    *,
    limit: int | None = None,
    offset: int = 0,
    modo: str = "nuovi",
    solo_oe: bool = False,
    solo_in_verifica: bool = False,
    bando_id: Any = None,
    forza: bool = False,
    fonti_oe: Sequence[int] = (),
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I bandi candidati al resolver, secondo la selezione di §5.

    `modo`: `nuovi` (enriched senza fonte), `backlog` (pubblicati senza fonte),
    `ricontrolli` (`in_verifica`/`non_trovata` con `prossimo_controllo_at`
    scaduto — e li ricontrolla **solo** il resolver).

    `forza` toglie il filtro «senza fonte»: e' l'unico modo di rifare una riga
    gia' `trovata`, e per questo si chiede a mano.

    Ogni filtro su una colonna nuova passa da `ha()`: senza la migrazione 01 la
    colonna `fonte_ufficiale_stato` non esiste e il filtro risponderebbe 42703.
    La scadenza del ricontrollo NON si filtra qui: `prossimo_controllo_at` sta
    in `bando_controllo`, e mescolare le due tabelle in una sola richiesta
    PostgREST costringerebbe a un embed che la RLS di `bando_controllo` non
    concede. La selezione per data la fa il chiamante, su `select_controlli`.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_RESOLVER, strumento)
    try:
        query = _client(client).table("bando").select(colonne)
        if bando_id is not None:
            query = query.eq("id", bando_id)
        else:
            query = _filtra_selezione(
                query, strumento,
                modo=modo, solo_oe=solo_oe, solo_in_verifica=solo_in_verifica,
                forza=forza, fonti_oe=fonti_oe,
            )
        # Tiebreak obbligatorio: `data_pubblicazione` e' NULL sul 92% delle
        # righe e senza `id` due pagine si sovrappongono (trappola nota).
        query = query.order("id")
        # Le due convenzioni («zero e' un limite», «oltre i primi N si scorre
        # con range()») stanno in `_pagina`, una volta per tutte le select.
        return list(_pagina(query, limit, offset).execute().data or [])
    except Exception as e:
        logger.warning("[db] select_bandi_da_risolvere fallita, nessun candidato: {}", e)
        return []


def _filtra_selezione(
    query: Any,
    strumento: Any,
    *,
    modo: str,
    solo_oe: bool,
    solo_in_verifica: bool,
    forza: bool,
    fonti_oe: Sequence[int],
) -> Any:
    ha_stato = strumento.ha("bando", "fonte_ufficiale_stato")
    ha_pubblicato = strumento.ha("bando", "pubblicato")
    senza_fonte = ha_stato and not forza
    # `neq` su NULL non e' vero: una riga con la colonna vuota non veniva mai
    # selezionata, e la colonna nasceva vuota. La migrazione 09 ha messo il
    # DEFAULT e riempito le righe, ma la selezione non deve dipendere da una
    # migrazione: un `INSERT` che scrive NULL esplicito, o il rollback della
    # 09, riaprirebbero il buco senza che nessun contatore lo dica.
    SENZA_FONTE = "fonte_ufficiale_stato.is.null,fonte_ufficiale_stato.neq.trovata"
    if modo == "backlog":
        query = query.eq("pubblicato", True) if ha_pubblicato else query.eq(
            "stato_processing", "completed")
        if senza_fonte:
            query = query.or_(SENZA_FONTE)
    elif modo == "ricontrolli":
        if ha_stato:
            query = query.in_("fonte_ufficiale_stato", ["in_verifica", "non_trovata"])
        # Il ricontrollo vale per le righe che una fonte ufficiale la useranno
        # davvero: i pubblicati, e gli `enriched` che stanno per diventarlo.
        # Senza questo filtro la selezione prendeva **4 076** righe invece di
        # 1 283 (misurato il 24/09/2026): 2 337 `rejected` — gli scarti della
        # pipeline, in gran parte righe di un calendario letto male — e 455
        # chiusi mai pubblicati, che sono materia del lotto L8. Due terzi del
        # lavoro finivano su pagine che non esisteranno, e su righe senza
        # candidato la cascata arriva fino alla ricerca a pagamento: il costo
        # non era solo tempo.
        query = (query.or_("pubblicato.eq.true,stato_processing.eq.enriched")
                 if ha_pubblicato
                 else query.in_("stato_processing", ["completed", "enriched"]))
    else:                                              # nuovi
        query = query.eq("stato_processing", "enriched")
        if senza_fonte:
            query = query.or_(SENZA_FONTE)
    if solo_in_verifica and ha_stato:
        query = query.eq("fonte_ufficiale_stato", "in_verifica")
    if solo_oe and fonti_oe:
        query = query.in_("fonte_id", list(fonti_oe))
    return query


#: Le colonne che `select_controlli` legge per difetto: quelle che servono al
#: resolver, cioe' la coda e i tentativi. Il monitor ne chiede altre — le
#: colonne calde, `testo_norm` in testa — e le chiede con `colonne=`: sono
#: decine di MB su 1 683 righe e non vanno lette da chi non le usa.
COLONNE_CONTROLLO_CODA: tuple[str, ...] = (
    "bando_id", "prossimo_controllo_at", "ultimo_controllo_at", "priorita_controllo",
    "tentativi_resolver", "candidato_prioritario",
)


def select_controlli(
    bando_ids: Sequence[Any],
    *,
    colonne: Sequence[str] | None = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[Any, dict[str, Any]]:
    """Righe di `bando_controllo` per id. `{}` se la tabella non c'e' ancora.

    `colonne` sostituisce l'elenco predefinito: e' il modo in cui il monitor
    chiede la propria **memoria** (`testo_norm`, `impronta_contenuto`, l'ETag,
    `controlli_falliti`) sulle sole righe che lavorera' davvero. Senza,
    leggeva le sei colonne del resolver e ogni giro ripartiva da zero:
    `controlli_falliti` valeva sempre 1 e la promessa «cinque fallimenti e il
    bando esce dalla coda» non si avverava mai. `_colonne_disponibili` scarta
    da se' cio' che lo schema non espone, quindi chiedere di piu' non rompe
    nulla su un DB non ancora migrato.
    """
    strumento = _controllo(strumento)
    if not bando_ids or not strumento.tabella_esiste(TABELLA_CONTROLLO):
        return {}
    colonne = _colonne_disponibili(
        TABELLA_CONTROLLO,
        tuple(colonne) if colonne else COLONNE_CONTROLLO_CODA,
        strumento,
    )
    try:
        # A blocchi e a pagine: la tabella e' 1:1 con `bando`, quindi con una
        # coda di 2 000 id la risposta unica ne riportava 1 000 e le righe
        # mancanti sembravano «mai controllate» — priorita' gonfiata,
        # `controlli_falliti` di nuovo a zero, memoria del giro persa.
        righe = _per_id(
            lambda blocco: _client(client).table(TABELLA_CONTROLLO)
            .select(colonne).in_("bando_id", blocco),
            list(bando_ids),
            ordine="bando_id",
        )
    except Exception as e:
        logger.warning("[db] select_controlli fallita: {}", e)
        return {}
    return {r.get("bando_id"): r for r in righe if r.get("bando_id") is not None}


def select_pubblicati_per_gemelli(
    *,
    limit: int = 5000,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati su cui `gemelli.py` cerca le corrispondenze esatte.

    Colonne minime: id, la chiave della fonte, i due URL confrontabili e cio'
    che serve a `scegli_master`. Mai `contenuto`, mai `raw_data` completo.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili(
        "bando",
        ("id", "titolo", "titolo_raw", "link_bando", "fonte_id", "fonte_ufficiale_url",
         "fonte_ufficiale_host", "fonte_ufficiale_tipo", "fonte_ufficiale_stato",
         "chiave_esterna", "data_scadenza", "pubblicato_at", "slug"),
        strumento,
    )
    def _costruisci() -> Any:
        query = _client(client).table("bando").select(colonne)
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", True)
        else:
            query = query.eq("stato_processing", "completed").not_.is_("slug", "null")
        return query.order("id")

    try:
        # `.limit(5000)` chiedeva 5 000 righe e ne riceveva 1 000: `max-rows`
        # taglia in silenzio. `gemelli.py` cercava quindi le corrispondenze
        # esatte sui primi 1 000 pubblicati per id — meno di meta' del corpus —
        # e i doppioni con id alto erano invisibili per costruzione.
        return _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto),
                       tetto=max(0, int(limit)))
    except Exception as e:
        logger.warning("[db] select_pubblicati_per_gemelli fallita: {}", e)
        return []


def select_link_delle_fonti(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> set[Any]:
    """Gli id di `bando_link` che sono la **fonte ufficiale** di un bando.

    Serve a `link-verifica` per distinguere due righe `raw` identiche in
    tabella: quella che nessuno ha mai visto in una pagina, e quella che il
    resolver ha scelto come fonte dopo averla scaricata e valutata. La seconda
    ha la prova per costruzione (`bando.fonte_ufficiale_verificata_at`), anche
    quando la riga di link non se la porta dietro.
    """
    strumento = _controllo(strumento)
    if not strumento.ha("bando", "fonte_ufficiale_link_id"):
        return set()
    try:
        righe = _scorri(
            lambda quanto, salto: _client(client).table("bando")
            .select("fonte_ufficiale_link_id")
            .eq("fonte_ufficiale_stato", "trovata")
            .not_.is_("fonte_ufficiale_link_id", "null")
            .order("id").limit(quanto).offset(salto)
        )
    except Exception as e:
        logger.warning("[db] select_link_delle_fonti fallita: {}", e)
        return set()
    return {r.get("fonte_ufficiale_link_id") for r in righe
            if r.get("fonte_ufficiale_link_id") is not None}


def select_link_da_verificare(
    *,
    limit: int | None = None,
    offset: int = 0,
    bando_id: Any = None,
    bando_ids: Sequence[Any] = (),
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Righe di `bando_link`, per una riga o per un lotto di id.

    `bando_ids` serve a chi deve sapere, per un intero lotto, quali bandi hanno
    gia' un link con la prova della scheda: una richiesta invece di una per
    bando.

    `offset` serve a `link-verifica`, che altrimenti ripasserebbe per sempre
    sulle stesse prime N righe: la tabella non ha nessun predicato che faccia
    uscire una riga gia' verificata, quindi l'avanzamento puo' arrivare solo
    dallo scorrimento. `updated_at` e' fra le colonne lette apposta: e' il
    marcatore che il trigger `trg_bando_link_updated_at` mantiene su ogni
    UPDATE, e senza leggerlo nessuno saprebbe quali righe sono gia' state
    guardate oggi.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_LINK):
        return []
    colonne = _colonne_disponibili(
        TABELLA_LINK,
        ("id", "bando_id", "url", "tipo", "origine", "etichetta", "esito_http",
         "pubblicabile", "ultimo_visto_at", "trovato_in_fonte_at", "content_type",
         "url_prova", "impronta_pagina", "updated_at"),
        strumento,
    )
    try:
        if bando_ids and bando_id is None and limit is None:
            # Il lotto si legge a blocchi e a pagine. Con una lista di 500 id
            # la risposta unica si fermava a 1 000 righe (`max-rows`) e i bandi
            # oltre quella soglia risultavano «scheda mai letta»: il lotto
            # `oe-dettaglio` li riscaricava tutti a ogni lancio.
            return _per_id(
                lambda blocco: _client(client).table(TABELLA_LINK)
                .select(colonne).in_("bando_id", blocco),
                list(bando_ids),
            )
        query = _client(client).table(TABELLA_LINK).select(colonne)
        if bando_id is not None:
            query = query.eq("bando_id", bando_id)
        elif bando_ids:
            query = query.in_("bando_id", list(bando_ids))
        query = query.order("id")
        return list(_pagina(query, limit, offset).execute().data or [])
    except Exception as e:
        logger.warning("[db] select_link_da_verificare fallita: {}", e)
        return []


def select_fonti_per_domini(
    *, client: Any | None = None, strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Righe di `fonte` da cui `dominio_ufficiale.da_fonti` ricava gli host."""
    strumento = _controllo(strumento)
    colonne = _colonne_disponibili("fonte", ("id", "link", "discoverable"), strumento)
    try:
        return list(
            _client(client).table("fonte").select(colonne).order("id").execute().data or []
        )
    except Exception as e:
        logger.warning("[db] select_fonti_per_domini fallita: {}", e)
        return []


# --- scritture -------------------------------------------------------------

def aggiorna_fonte_ufficiale(
    bando_id: Any,
    payload: Mapping[str, Any],
    *,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Le colonne `fonte_ufficiale_*` di una riga. Degrada se non esistono."""
    dati = dict(payload)
    assicura_payload_bando(dati)
    estranee = sorted(k for k in dati if k not in COLONNE_FONTE_UFFICIALE)
    if estranee:
        raise PayloadBandoVietato(
            f"il resolver scrive solo le colonne fonte_ufficiale_*: {estranee}"
        )
    return _controllo(strumento).aggiorna("bando", bando_id, dati)


def aggiorna_controllo(
    bando_id: Any,
    payload: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """UPSERT su `bando_controllo` (chiave primaria `bando_id`).

    Nessun ripiego sulle colonne di `bando` se la tabella manca (§5): le
    colonne calde stanno li' proprio per non toccare la tabella che BandoFit
    seq-scanna, e scriverle altrove annullerebbe il motivo della tabella.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_CONTROLLO):
        logger.info("[db] bando_controllo assente: niente scrittura (id={})", bando_id)
        return _saltato("colonne_assenti", scritto=False)
    mancanti = strumento.colonne_mancanti(TABELLA_CONTROLLO, payload)
    riga = {k: v for k, v in payload.items() if k not in mancanti}
    if not riga:
        return _saltato("colonne_assenti", scritto=False)
    riga["bando_id"] = bando_id
    try:
        (_client(client).table(TABELLA_CONTROLLO)
         .upsert(riga, on_conflict="bando_id").execute())
    except Exception as e:
        logger.warning("[db] upsert bando_controllo id={} fallito: {}", bando_id, e)
        return {"status": "ok", "scritto": False, "motivo": str(e)}
    return {"status": "ok", "scritto": True, "ignorate": mancanti}


def upsert_bando_link(
    righe: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> int:
    """UPSERT su `bando_link` per `(bando_id, url_normalizzato)` (§16.3.3).

    `ignore_duplicates=True` perche' `url` e' immutabile: una riga che esiste
    gia' non va riscritta con un URL diverso che normalizza allo stesso valore.
    Ritorna quante righe sono state inviate (0 = tabella assente o errore).
    """
    strumento = _controllo(strumento)
    if not righe or not strumento.tabella_esiste(TABELLA_LINK):
        return 0
    presenti = strumento.colonne(TABELLA_LINK)
    pulite = [
        {k: v for k, v in senza_generate(riga).items() if not presenti or k in presenti}
        for riga in righe
    ]
    pulite = [r for r in pulite if r.get("bando_id") is not None and r.get("url")]
    if not pulite:
        return 0
    try:
        (_client(client).table(TABELLA_LINK)
         .upsert(pulite, on_conflict="bando_id,url_normalizzato", ignore_duplicates=True)
         .execute())
    except Exception as e:
        logger.warning("[db] upsert bando_link fallito ({} righe): {}", len(pulite), e)
        return 0
    return len(pulite)


def aggiorna_link(
    link_id: Any,
    payload: Mapping[str, Any],
    *,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """UPDATE di una riga di `bando_link` (esito HTTP, pubblicabilita')."""
    return _controllo(strumento).aggiorna(TABELLA_LINK, link_id, dict(payload))


#: Colonne `GENERATED ALWAYS AS (...) STORED` delle tabelle di servizio: un
#: INSERT o un UPDATE che le valorizzi risponde 428C9 e fa fallire l'intera
#: riga. Si tolgono dal payload prima di scrivere; in **lettura** restano
#: colonne normali, ed e' per questo che `COLONNE_EVENTO` le tiene.
COLONNE_GENERATE: frozenset[str] = frozenset({
    "dominio_prova", "url_normalizzato", "dominio", "ricerca",
})


def senza_generate(riga: Mapping[str, Any]) -> dict[str, Any]:
    """La riga senza le colonne che Postgres calcola da solo."""
    return {k: v for k, v in riga.items() if k not in COLONNE_GENERATE}


#: I tre esiti di un INSERT in `bando_evento`. Servono a distinguere «il
#: database ha rifiutato» da «c'era gia'»: il secondo e' il caso normale
#: quando si rifa' un giro sulle stesse righe, e confonderli fa gridare un
#: allarme su un lavoro riuscito (misurato il 25/09/2026: `eventi_non_scritti:
#: 2` su due duplicati, con l'allarme «il database li ha rifiutati»).
EVENTO_SCRITTO = "scritto"
EVENTO_GIA_PRESENTE = "gia_presente"
EVENTO_RIFIUTATO = "rifiutato"


def registra_evento_esito(
    evento: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> str:
    """INSERT in `bando_evento`, con i tre esiti di `EVENTO_*`.

    Gemello di `applica_evento_esito`, e per la stessa ragione: chi conta il
    lavoro fatto deve poter distinguere un rifiuto da un duplicato. Il wrapper
    booleano `registra_evento` resta per i chiamanti che non guardano il
    motivo.
    """
    esito = _registra_evento(evento, client=client, strumento=strumento)
    return esito


def registra_evento(
    evento: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> bool:
    """INSERT in `bando_evento`. Falso se la tabella non c'e' o l'insert fallisce.

    Gli eventi del resolver in modalita' ombra arrivano qui con
    `leggibile=false` e `applicato=false`: il cursore non viene assegnato e
    nessun consumatore li vede finche' il committente non attiva il tipo.

    Un evento **gia' presente** risponde `False` come prima: per chi guarda
    solo il booleano «non ho scritto niente di nuovo» e' la risposta giusta.
    Chi deve distinguere usa `registra_evento_esito`.
    """
    return _registra_evento(
        evento, client=client, strumento=strumento) == EVENTO_SCRITTO


def _registra_evento(
    evento: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> str:
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_EVENTO):
        return EVENTO_RIFIUTATO
    presenti = strumento.colonne(TABELLA_EVENTO)
    riga = {k: v for k, v in senza_generate(evento).items()
            if not presenti or k in presenti}
    if not riga.get("bando_id") or not riga.get("tipo"):
        return EVENTO_RIFIUTATO
    try:
        _client(client).table(TABELLA_EVENTO).insert(riga).execute()
    except Exception as e:
        if _e_gia_registrato(e):
            # L'indice di dedup della 02 ha fatto il suo lavoro: quell'evento
            # c'e' gia', con lo stesso bando, tipo, campo, valore e giorno. Non
            # e' un guasto ed e' anzi il caso NORMALE quando si rifa' un giro
            # sulle stesse righe nella stessa giornata
            # (`risolvi-fonte --forza --anche-oggi`). Scriverlo a WARNING con il
            # corpo intero dell'errore riempiva il log di migliaia di righe e
            # nascondeva i guasti veri.
            logger.debug("[db] evento {} gia' registrato per il bando {}",
                         riga.get("tipo"), riga.get("bando_id"))
            return EVENTO_GIA_PRESENTE
        logger.warning("[db] insert bando_evento ({}) fallito: {}", riga.get("tipo"), e)
        return EVENTO_RIFIUTATO
    return EVENTO_SCRITTO


#: Il codice di Postgres per la violazione di un vincolo di unicita'.
_VIOLAZIONE_UNICITA = "23505"


def _e_gia_registrato(errore: Exception) -> bool:
    """L'insert e' stato rifiutato perche' la riga c'era gia'?

    Si guarda il codice di Postgres e non il testo del messaggio: il testo
    cambia con la lingua del server e con il nome dell'indice, il codice no.
    """
    codice = getattr(errore, "code", None)
    if codice is None:
        dettagli = getattr(errore, "details", None) or getattr(errore, "args", None)
        testo = str(dettagli or errore)
        return _VIOLAZIONE_UNICITA in testo
    return str(codice) == _VIOLAZIONE_UNICITA


def upsert_domini(
    righe: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> int:
    """UPSERT della whitelist in `dominio_ufficiale` (`python -m app domini --import`)."""
    strumento = _controllo(strumento)
    if not righe or not strumento.tabella_esiste(TABELLA_DOMINIO):
        logger.info("[db] dominio_ufficiale assente: import saltato")
        return 0
    presenti = strumento.colonne(TABELLA_DOMINIO)
    pulite = [
        {k: v for k, v in riga.items() if not presenti or k in presenti} for riga in righe
    ]
    pulite = [r for r in pulite if r.get("host")]
    if not pulite:
        return 0
    try:
        (_client(client).table(TABELLA_DOMINIO)
         .upsert(pulite, on_conflict="host").execute())
    except Exception as e:
        logger.warning("[db] upsert dominio_ufficiale fallito ({} righe): {}", len(pulite), e)
        return 0
    return len(pulite)


def fondi_bandi(
    master_id: Any,
    doppione_id: Any,
    motivo: str,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> Any:
    """RPC `bando_fondi`. Solo criteri esatti, solo fuori ombra (§5, §14).

    ATTENZIONE ai nomi: la firma in tabella e'
    `bando_fondi(p_dup integer, p_master integer, p_motivo text)` (04:795-799),
    cioe' il **doppione per primo**. Chi la chiamasse posizionalmente, o
    ricopiando l'ordine di questa funzione Python, fonderebbe il master dentro
    il doppione. Qui si passa sempre per nome.

    Ritorna l'id del master **effettivo** (la RPC appiattisce le catene e puo'
    scegliere un master diverso da quello proposto), oppure `None` se la RPC
    non c'e' o la chiamata e' fallita: il chiamante deve poter distinguere
    «fuso sul master che avevo scelto» da «fuso su un altro».
    """
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_FONDI):
        logger.info("[db] RPC {} assente: nessuna fusione applicata", RPC_FONDI)
        return None
    try:
        risposta = _client(client).rpc(
            RPC_FONDI, dict(zip(PARAMETRI_FONDI, (doppione_id, master_id, motivo)))
        ).execute()
    except Exception as e:
        logger.warning("[db] {} ({} <- {}) fallita: {}", RPC_FONDI, master_id, doppione_id, e)
        return None
    dati = getattr(risposta, "data", None)
    if isinstance(dati, int):
        return dati
    if isinstance(dati, list) and dati and isinstance(dati[0], int):
        return dati[0]
    # La RPC non ha detto quale master ha scelto: si assume quello proposto,
    # perche' la chiamata e' comunque andata a buon fine.
    return master_id


# ---------------------------------------------------------------------------
# Ombra e lotti di backfill (piano §6.2, §6.4) — letture e scritture
# ---------------------------------------------------------------------------
#
# Stessa regola della sezione precedente, senza eccezioni: ogni oggetto nuovo
# passa da `controllo`, niente sollevamenti, una colonna assente e' un
# `{'saltato': 'colonne_assenti'}` con un log.
#
# Qui vivono le quattro letture e le due scritture che servono ai cinque
# comandi di §6.2/§6.4 (`report-ombra`, `applica-eventi`, `rigenera`,
# `pulisci-contenuto`, `archivia-processed`). Nessuna di esse scrive `slug`,
# `titolo`, `pubblicato` o `data_pubblicazione`.

RPC_APPLICA_EVENTO = "bando_applica_evento"

#: Ramo terminale dei `processed` chiusi che nessuno lavorera' piu' (L8).
#: Lo ammette il CHECK riscritto dalla migrazione 01: prima di quella un
#: UPDATE con questo valore risponde 23514 e va evitato, non tentato.
STATO_ARCHIVIATO = "archiviato"

#: Colonne di `bando_evento` lette dai comandi dell'ombra. Esplicite: `select=*`
#: su questa tabella risponde 42501 (grant di colonna, §16.3 punto 3).
COLONNE_EVENTO: tuple[str, ...] = (
    "id", "bando_id", "tipo", "origine", "campo", "valore_prima", "valore_dopo",
    "data_evento", "rilevato_at", "applicato", "applicato_at", "leggibile",
    "verificato", "in_aggiornamenti", "url_prova", "dominio_prova",
    "citazione", "impronta_pagina", "confidenza", "gate", "metodo",
    # `riferisce_a` e' l'id dell'evento a cui questo si riferisce: e' come
    # `bando_applica_evento` annota un rifiuto (`elaborazione_bloccata`). Senza
    # leggerla, `applica-eventi` non potrebbe riconoscere gli eventi gia'
    # rifiutati e li ripresenterebbe a ogni lancio in testa al blocco.
    "riferisce_a",
)

#: Colonne dei pubblicati su cui lavorano `pulisci-contenuto` e `rigenera`.
COLONNE_BACKFILL_CONTENUTO: tuple[str, ...] = (
    "id", "slug", "titolo", "contenuto", "descrizione_breve", "link_bando",
    "link_candidatura", "link_candidatura_source", "stato_processing",
    "stato_bando", "data_apertura", "data_scadenza", "pubblicato",
    "fonte_ufficiale_url", "fonte_ufficiale_stato",
)

#: Colonne dei `processed` che `archivia-processed` deve poter giudicare.
COLONNE_BACKFILL_PROCESSED: tuple[str, ...] = (
    "id", "titolo", "slug", "stato_processing", "stato_bando", "data_apertura",
    "data_scadenza", "pubblicato", "fonte_ufficiale_stato", "fonte_ufficiale_url",
    "created_at", "updated_at",
)


def _pubblicati(query: Any, strumento: Any) -> Any:
    """Filtro «pubblicato» com'e' scritto oggi e come sara' dopo la 01.

    Prima della migrazione la colonna non esiste e il predicato vero e'
    `completed AND slug IS NOT NULL` (la stessa RLS pubblica di oggi).
    """
    if strumento.ha("bando", "pubblicato"):
        return query.eq("pubblicato", True)
    return query.eq("stato_processing", "completed").not_.is_("slug", "null")


def select_eventi(
    *,
    tipi: Sequence[str] = (),
    dal: Any = None,
    applicato: bool | None = None,
    verificato: bool | None = None,
    bando_id: Any = None,
    con_riferimento: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
    colonne: Sequence[str] | None = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Righe di `bando_evento` per i comandi dell'ombra. `[]` se la tabella manca.

    `dal` filtra su `data_evento` **oppure** `rilevato_at`: un evento datato
    dall'ente prima dell'inizio dell'ombra ma rilevato dopo (e viceversa) deve
    entrare comunque, altrimenti `applica-eventi --dal` ne perderebbe una parte
    e la baseline delle impronte non li ripresenterebbe mai piu' (§6.2).

    L'ordine e' `id` crescente: e' l'ordine in cui gli eventi sono stati
    raccolti, ed e' l'unico stabile (`data_evento` e' NULL su molte righe) —
    ed e' cio' che rende `offset` utilizzabile per scorrere oltre i primi N.
    Serve a chi deve superare le righe su cui non c'e' lavoro da fare: un
    evento che la RPC rifiuta resta `applicato=false` all'id piu' basso e
    riconsumerebbe il blocco a ogni lancio.

    `con_riferimento` filtra su `riferisce_a`: `True` restituisce solo le righe
    che ne hanno uno. Serve a chi legge gli `elaborazione_bloccata` cercando le
    **annotazioni di rifiuto**, che sono le sole a portarlo: quel tipo lo
    scrivono anche il monitor dopo cinque fallimenti, i gemelli e
    `rigenera --malformati`, tutti con `riferisce_a` NULL, e senza il filtro
    consumerebbero il tetto della lettura. Con l'ordine per `id` crescente
    cadrebbero fuori le annotazioni **piu' recenti**, cioe' proprio quelle che
    servono.

    `colonne` sostituisce l'elenco predefinito, come in `select_controlli`: chi
    cerca una sola colonna non deve portarsi dietro `valore_dopo`, `citazione`
    e il `gate` jsonb dell'intera tabella. `eventi_gia_rifiutati` legge cosi'
    i soli `riferisce_a`, e lo fa a ogni lancio di `applica-eventi`.

    Oltre le mille righe si **scorre**: il tetto di PostgREST taglia in
    silenzio (`PAGINA_POSTGREST`), quindi una `limit(2000)` restituiva 1 000
    righe come se fossero tutte — e una lista di «eventi gia' rifiutati»
    incompleta rimette in coda proprio gli eventi che non si possono applicare.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_EVENTO):
        logger.info("[db] {} assente: nessun evento da leggere", TABELLA_EVENTO)
        return []
    if verificato is not None and not strumento.ha(TABELLA_EVENTO, "verificato"):
        # Senza la colonna il filtro cadrebbe in silenzio e il chiamante si
        # ritroverebbe in mano anche i respinti, credendo di aver chiesto i
        # soli verificati. Meglio nessuna riga che righe sbagliate.
        logger.warning(
            "[db] {} senza colonna `verificato`: nessun evento restituito", TABELLA_EVENTO)
        return []
    scelte = _colonne_disponibili(
        TABELLA_EVENTO, tuple(colonne) if colonne else COLONNE_EVENTO, strumento)

    def _costruisci() -> Any:
        """Una query **nuova** a ogni pagina: i builder accumulano con `add`."""
        query = _client(client).table(TABELLA_EVENTO).select(scelte)
        if bando_id is not None:
            query = query.eq("bando_id", bando_id)
        if tipi:
            query = query.in_("tipo", list(tipi))
        if applicato is not None and strumento.ha(TABELLA_EVENTO, "applicato"):
            query = query.eq("applicato", applicato)
        if verificato is not None:
            query = query.eq("verificato", verificato)
        if con_riferimento is not None and strumento.ha(TABELLA_EVENTO, "riferisce_a"):
            query = (query.not_.is_("riferisce_a", "null") if con_riferimento
                     else query.is_("riferisce_a", "null"))
        if dal is not None:
            giorno = dal.isoformat() if hasattr(dal, "isoformat") else str(dal)
            if hasattr(query, "or_"):
                query = query.or_(
                    f"data_evento.gte.{giorno},rilevato_at.gte.{giorno}")
            else:                                        # pragma: no cover - client datato
                query = query.gte("rilevato_at", giorno)
        return query.order("id")

    salto = max(0, int(offset or 0))
    try:
        if limit is not None and int(limit) <= PAGINA_POSTGREST:
            # Una pagina sola e niente scorrimento: e' il caso di gran lunga
            # piu' frequente (`--limit`, le pagine di `_da_applicare`) e
            # l'unico in cui `offset` significa «salta le prime N e basta».
            return list(_pagina(_costruisci(), limit, salto).execute().data or [])
        return _scorri(
            lambda quanto, avanzamento: _pagina(
                _costruisci(), quanto, salto + avanzamento),
            tetto=int(limit) if limit is not None else None,
        )
    except Exception as e:
        logger.warning("[db] select_eventi fallita: {}", e)
        return []


#: Colonne di `bando` che la coda del monitor legge (§6.2). Le colonne calde
#: — `prossimo_controllo_at`, la priorita', le impronte, l'ETag — stanno su
#: `bando_controllo` e arrivano da `select_controlli`.
COLONNE_MONITOR: tuple[str, ...] = (
    "id", "slug", "titolo", "pubblicato", "stato_processing", "stato_bando",
    "bando_master_id", "fonte_ufficiale_stato", "fonte_ufficiale_url",
    "data_pubblicazione", "data_apertura", "ora_apertura",
    "data_scadenza", "ora_scadenza", "data_apertura_verificata",
)

#: Quante righe di `bando` la coda legge al massimo in un giro. La selezione
#: vera (`monitoraggio.seleziona`) ordina per priorita' e taglia al tetto del
#: giro, ma per ordinare bisogna prima leggere, e il filtro «ricontrollo
#: scaduto» sta su `bando_controllo`: incrociarlo in una sola richiesta
#: PostgREST vorrebbe un embed che la RLS di quella tabella non concede.
#:
#: Il numero non e' scelto a occhio: il piano misura **2 104 pubblicati** (di
#: cui 1 683 con fonte ufficiale trovata, gli unici che entrano nel fetch).
#: 5 000 e' quindi poco piu' del doppio del corpus di oggi — margine per la
#: crescita, ma non tanto da nascondere il giorno in cui il corpus lo supera.
#: Quel giorno la selezione per priorita' ordinerebbe una FETTA del corpus
#: senza che nessuno se ne accorga: per questo il superamento non e' solo una
#: riga di log ma un allarme del giro (`monitoraggio.FonteDatiSupabase`
#: lo raccoglie e `run` lo porta nel riepilogo, cioe' in `pipeline_run`).
TETTO_CODA_MONITOR = 5000

#: Il testo dell'allarme, qui e non nel chiamante: chi legge `pipeline_run` e
#: chi legge i log devono trovare la stessa frase.
ALLARME_CODA_TRONCATA = (
    f"coda del monitor troncata a {TETTO_CODA_MONITOR} righe: la selezione "
    "per priorita' non vede il resto del corpus"
)


def select_bandi_da_monitorare(
    *,
    limit: int | None = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati che il monitor puo' controllare. `[]` se `bando` non c'e'.

    Tre filtri, gli stessi di `monitoraggio.selezionabile`, fatti qui perche'
    sono quelli che tolgono righe davvero: pubblicato, non doppione, fonte
    ufficiale `trovata` (senza, l'unico URL che abbiamo e' l'aggregatore, e
    quei bandi li ripassa il resolver). La scadenza del ricontrollo no: sta su
    `bando_controllo`, e la applica il chiamante dopo la `select_controlli`.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_MONITOR, strumento)
    def _costruisci() -> Any:
        query = _pubblicati(_client(client).table("bando").select(colonne), strumento)
        if strumento.ha("bando", "fonte_ufficiale_stato"):
            query = query.eq("fonte_ufficiale_stato", "trovata")
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        # Tiebreak obbligatorio: `data_pubblicazione` e' NULL sul 92 % delle
        # righe (trappola nota), e senza `id` due pagine si sovrappongono.
        return query.order("id")

    tetto = int(limit) if limit is not None else TETTO_CODA_MONITOR
    try:
        # Si scorre invece di limitare: `.limit(5000)` tornava 1 000 righe
        # (`max-rows`), quindi la coda vedeva meno di meta' dei pubblicati con
        # fonte trovata e l'allarme qui sotto — tarato su 5 000 — non poteva
        # scattare mai. Il troncamento era silenzioso proprio dove era stato
        # scritto un allarme per non lasciarlo silenzioso.
        righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto),
                        tetto=max(0, tetto))
    except Exception as e:
        logger.warning("[db] select_bandi_da_monitorare fallita: {}", e)
        return []
    if limit is None and len(righe) >= TETTO_CODA_MONITOR:
        logger.warning("[ALLARME] [db] {}", ALLARME_CODA_TRONCATA)
    return righe


#: Le voci di `pipeline_run.contatori` che alimentano i tetti giornalieri di
#: `bilancio.verifica_giornalieri`. Stanno dentro il jsonb e non in colonne
#: proprie: `pipeline_run` ha `(id, step, giro, avviato_at, concluso_at,
#: esito, interrotto_per_tetto, motivo, contatori, note)` e nient'altro.
VOCI_CONSUMO: tuple[str, ...] = ("ricerche", "crediti", "classificazioni", "usd")


def consumo_oggi(
    *,
    adesso: Any = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, float]:
    """Quanto hanno gia' consumato oggi i giri precedenti (§6.2).

    Senza questa somma, con quattro giri al giorno il tetto giornaliero
    varrebbe quattro volte tanto. `{}` se `pipeline_run` non c'e' ancora: il
    tetto resta quello del singolo giro, che e' la degradazione giusta.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_RUN):
        return {}
    # La giornata e' quella del **calendario di Roma**, come ovunque nel
    # package (`oggi_roma`). Con la data UTC i giri delle 00:00 italiane
    # cadevano nel giorno precedente per un'ora (due in estate): il tetto
    # giornaliero ripartiva da zero a mezzanotte di Londra, non di Roma, e
    # nella finestra fra i due mezzanotti valeva il doppio. Si filtra
    # sull'ISTANTE di mezzanotte romana, non sulla sola data: `avviato_at` e'
    # un `timestamptz`, e una data nuda verrebbe letta come mezzanotte UTC.
    from .stato_bando import adesso_roma
    momento = adesso_roma(adesso if isinstance(adesso, datetime_cls) else None)
    inizio = momento.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        righe = list((
            _client(client).table(TABELLA_RUN).select("id,step,contatori")
            .gte("avviato_at", inizio).order("id").execute()
        ).data or [])
    except Exception as e:
        logger.warning("[db] consumo_oggi fallita: {}", e)
        return {}
    somma = {voce: 0.0 for voce in VOCI_CONSUMO}
    for riga in righe:
        contatori = riga.get("contatori")
        if not isinstance(contatori, Mapping):
            continue
        for voce in VOCI_CONSUMO:
            try:
                somma[voce] += float(contatori.get(voce) or 0)
            except (TypeError, ValueError):
                continue
    return somma


def select_bandi_pubblicati_contenuto(
    *,
    limit: int | None = None,
    offset: int = 0,
    bando_ids: Sequence[Any] = (),
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati con il `contenuto` da ripulire o rigenerare (L7).

    Il filtro «quali contengono davvero un link all'aggregatore» non e'
    esprimibile in PostgREST su una colonna jsonb: si legge il lotto e si
    sceglie in Python. E' il motivo per cui questi comandi hanno `--limit` —
    e il motivo per cui hanno bisogno di `offset`: la scelta avviene dopo la
    lettura, quindi senza scorrere il comando ripasserebbe per sempre sulle
    stesse prime N righe (nessuna scrittura di L7 le fa uscire dai pubblicati).
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_BACKFILL_CONTENUTO, strumento)
    try:
        query = _client(client).table("bando").select(colonne)
        if bando_ids:
            query = query.in_("id", list(bando_ids))
        else:
            query = _pubblicati(query, strumento)
        query = query.order("id")
        return list(_pagina(query, limit, offset).execute().data or [])
    except Exception as e:
        logger.warning("[db] select_bandi_pubblicati_contenuto fallita: {}", e)
        return []


def select_processed_da_archiviare(
    *,
    limit: int | None = None,
    offset: int = 0,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I `processed` candidati a L8. Mai una riga pubblicata.

    Il filtro `pubblicato=false` si aggiunge solo quando la colonna esiste:
    prima della 01 un `processed` non e' pubblicato per definizione (la RLS
    pubblica chiede `completed`), quindi non serve e non si puo' chiedere.

    `offset`: solo il ramo `archiviato` fa uscire una riga dalla selezione. Le
    righe che `destinazione()` manda a `salta` o a `lavorazione` restano
    `processed` per sempre e, stando in testa all'ordinamento per `id`,
    riconsumerebbero il `--limit` a ogni lancio. Si scorre.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_BACKFILL_PROCESSED, strumento)
    try:
        query = (
            _client(client).table("bando").select(colonne)
            .eq("stato_processing", "processed")
        )
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", False)
        query = query.order("id")
        return list(_pagina(query, limit, offset).execute().data or [])
    except Exception as e:
        logger.warning("[db] select_processed_da_archiviare fallita: {}", e)
        return []


#: I tre esiti di un'applicazione. Vanno distinti perche' da fuori si
#: assomigliano — l'evento resta `applicato=false` in tutti e tre i casi — ma
#: **solo uno e' un rifiuto**. «La RPC non c'era» e «la chiamata e' fallita»
#: sono un non-tentativo, e annotarli come rifiuto li renderebbe definitivi:
#: `bando_evento` non concede DELETE nemmeno a `service_role` (migrazione 02) e
#: il trigger di immutabilita' vieta di cambiare `riferisce_a`. Un solo
#: `applica-eventi --attivo` lanciato prima della 04 brucerebbe cosi' tutto
#: l'arretrato dell'ombra, senza modo di recuperarlo.
ESITO_APPLICATO = "applicato"
ESITO_RIFIUTATO = "rifiutato"
ESITO_NON_TENTATO = "non_tentato"


def applica_evento_esito(
    evento_id: Any,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> str:
    """RPC `bando_applica_evento`, con l'esito distinto fra rifiuto e non-tentativo.

    `ESITO_RIFIUTATO` solo quando la RPC ha risposto `false`, cioe' ha davvero
    guardato l'evento: transizione non ammessa, date incoerenti, stato che il
    CHECK non ammette ancora, evento gia' applicato. `ESITO_NON_TENTATO` se la
    RPC non c'e' (04 non applicata) o se la chiamata e' fallita: nessuno ha
    giudicato l'evento, e il lancio successivo deve poterlo riprovare.
    """
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_APPLICA_EVENTO):
        logger.info("[db] RPC {} assente: evento {} non tentato",
                    RPC_APPLICA_EVENTO, evento_id)
        return ESITO_NON_TENTATO
    try:
        risposta = _client(client).rpc(
            RPC_APPLICA_EVENTO, {"p_evento_id": evento_id}).execute()
    except Exception as e:
        logger.warning("[db] {} sull'evento {} fallita: {}",
                       RPC_APPLICA_EVENTO, evento_id, e)
        return ESITO_NON_TENTATO
    dati = getattr(risposta, "data", None)
    # La funzione ritorna `false` sugli eventi gia' applicati: e' un esito, non
    # un errore, ma non va contato come applicazione.
    if isinstance(dati, bool):
        return ESITO_APPLICATO if dati else ESITO_RIFIUTATO
    return ESITO_APPLICATO


def applica_evento(
    evento_id: Any,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> bool:
    """Come `applica_evento_esito`, ridotta a un booleano per i chiamanti storici.

    Chi deve decidere se annotare il rifiuto usa la versione con l'esito: qui
    un non-tentativo e un rifiuto sono indistinguibili, ed e' esattamente la
    confusione da cui nasce il danno irreversibile descritto sopra.
    """
    return applica_evento_esito(
        evento_id, client=client, strumento=strumento) == ESITO_APPLICATO


def archivia_bando(
    bando_id: Any,
    *,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Porta un `processed` chiuso allo stato terminale `archiviato` (L8).

    E' l'unico scrittore di `stato_processing` fuori dagli step della pipeline,
    e scrive **solo** questo valore: mai `pubblicato`, mai `slug`, mai una riga
    gia' pubblicata (la selezione le esclude, questo e' il secondo controllo).

    Degrada se la migrazione 01 non e' applicata: il CHECK in tabella ammette
    ancora cinque valori e l'UPDATE risponderebbe 23514 su ogni riga del lotto.
    `pubblicato` e `archiviato` arrivano con la stessa migrazione, quindi la
    presenza della colonna e' la prova che il valore e' scrivibile.
    """
    strumento = _controllo(strumento)
    if not strumento.ha("bando", "pubblicato"):
        logger.info(
            "[db] migrazione 01 non applicata: `{}` non ancora ammesso (id={})",
            STATO_ARCHIVIATO, bando_id,
        )
        return _saltato("colonne_assenti", scritto=False)
    return strumento.aggiorna(
        "bando", bando_id, {"stato_processing": STATO_ARCHIVIATO})
