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


#: Le colonne che il preprocess legge sempre (giro 3, §8: piu' quelle della
#: fonte ufficiale, `COLONNE_SEO_RESOLVER`, quando lo schema le espone).
COLONNE_PREPROCESS: tuple[str, ...] = (
    "id", "fonte_id", "titolo_raw", "descrizione_raw", "link_bando", "raw_data", "tipo_link",
)
#: Le colonne che l'enrich legge sempre (stesso discorso).
COLONNE_ENRICH: tuple[str, ...] = COLONNE_PREPROCESS + (
    "stato_bando", "data_pubblicazione", "data_apertura", "data_scadenza",
)


def select_bandi_scraped(
    limit: int | None = None, *, strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """SELECT bandi pronti per pre-processing (stato_processing='scraped').

    Giro 3 (§8): legge anche `fonte_ufficiale_url` e `fonte_ufficiale_stato`
    (se la migrazione 01 c'e'), cosi' il preprocess legge la pagina dell'ente
    trovata dal resolver precoce invece della scheda dell'aggregatore.

    Supabase REST API ha un default `max_rows=1000` per response. Per
    superarlo, paginariamo via `range(offset, offset+page_size-1)`
    finche' la pagina non e' piena.

    Se `limit` e' impostato, ci fermiamo quando lo raggiungiamo.
    """
    sb = get_supabase()
    colonne = _colonne_con_opzionali(
        "bando", COLONNE_PREPROCESS, COLONNE_SEO_RESOLVER, _controllo(strumento))
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
                .select(colonne)
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
    *,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """SELECT bandi candidati al enrichment.

    Criterio default: stato_processing='processed' AND
              (stato_bando IN ('aperto','in apertura prossimamente') OR stato_bando IS NULL).
    Se include_enriched=True: include anche i bandi gia' 'enriched' (per re-run
    idempotente — la fase B sostituira' FK + junction + date eventualmente
    aggiornate).
    Paginato 1000 alla volta per superare il cap default Supabase.
    Giro 3 (§8): legge anche le colonne della fonte ufficiale, se ci sono.
    """
    sb = get_supabase()
    colonne = _colonne_con_opzionali(
        "bando", COLONNE_ENRICH, COLONNE_SEO_RESOLVER, _controllo(strumento))
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
                .select(colonne)
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


#: Il catalogo letto per intero (§19.4): solo uno senza tabelle fallite resta
#: in memoria per il processo. `azzera_catalogo` lo dimentica.
_CATALOGO_LETTO: dict[str, list[dict[str, Any]]] | None = None


def azzera_catalogo() -> None:
    """Dimentica il catalogo in memoria (test, o dopo una modifica ai cataloghi)."""
    global _CATALOGO_LETTO
    _CATALOGO_LETTO = None


def load_catalogo() -> dict[str, list[dict[str, Any]]]:
    """Carica tutte le 7 tabelle catalogo. Cache singleton.

    Giro 3, §19.4: un catalogo con una tabella fallita **non** si mette in
    cache. Con `lru_cache` l'errore di un momento restava fino al riavvio del
    sender, e la rielaborazione marcava i bandi senza averli classificati. La
    lettura parziale si restituisce lo stesso (la tabella fallita vale `[]`, e
    l'enrich ne fa una dimensione fallita); la chiamata dopo riprova.

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
    global _CATALOGO_LETTO
    if _CATALOGO_LETTO is not None:
        return _CATALOGO_LETTO
    sb = get_supabase()
    catalogo: dict[str, list[dict[str, Any]]] = {}
    fallite: list[str] = []
    for key, (table, columns) in _CATALOGO_TABLES.items():
        try:
            res = sb.table(table).select(columns).order("id").execute()
            rows = res.data or []
            catalogo[key] = rows
            logger.info("[db] catalogo `{}`: {} record", table, len(rows))
        except Exception as e:
            logger.warning("[db] catalogo `{}` lookup fallito: {}", table, e)
            catalogo[key] = []
            fallite.append(table)
    if not fallite:
        _CATALOGO_LETTO = catalogo
    else:
        logger.warning("[db] catalogo incompleto ({}): non resta in memoria, si riprova",
                       ", ".join(fallite))
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
    # Il controllo dei doppioni OE (contratto di ottobre, §6) salta i bandi
    # annullati a mano, riconoscibili solo da qui.
    "rejection_reason",
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

    def _definizioni(self) -> dict[str, Any] | None:
        """Le definizioni delle tabelle nello schema, o None se non ci sono."""
        schema = self.schema()
        definizioni = schema.get("definitions")
        if not isinstance(definizioni, dict):
            # PostgREST >= 12 / OpenAPI 3: components.schemas
            componenti = schema.get("components")
            definizioni = componenti.get("schemas") if isinstance(componenti, dict) else None
        return definizioni if isinstance(definizioni, dict) else None

    def schema_leggibile(self) -> bool:
        """Vero se lo schema e' stato letto e descrive delle tabelle.

        Falso quando `schema()` ha degradato a `{}` (DB o rete giu', chiave
        sbagliata): allora di una tabella non si puo' dire che manca.
        """
        return bool(self._definizioni())

    def colonne(self, tabella: str) -> frozenset[str]:
        """Colonne esposte per `tabella`; insieme vuoto = «non so»."""
        definizioni = self._definizioni()
        if definizioni is None:
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
    # Giro 3 (§7): lo stato della fonte PRIMA del giro. Una riga gia'
    # `trovata` (`--forza`, `--id`) non si tocca nelle colonne del monitor.
    "fonte_ufficiale_stato",
)

#: I modi della selezione del resolver (§5; `precoce` dal giro 3, §7). Un modo
#: fuori elenco e' un errore di chi chiama, non un «nuovi» implicito.
MODI_RESOLVER: tuple[str, ...] = ("nuovi", "backlog", "ricontrolli", "precoce")
#: Gli stati che escono dai ricontrolli (giro 3, §7): un bando chiuso o
#: revocato non ha piu' bisogno di una fonte.
STATI_FUORI_RICONTROLLI: tuple[str, ...] = ("chiuso", "revocato")


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
    `ricontrolli` (`in_verifica`/`non_trovata`, pubblicati o `enriched`, non
    chiusi ne' revocati: tutti a ogni giro, giro 3 §7), `precoce` (`scraped` e
    `processed` senza fonte, giro 3 §7: il resto del filtro lo fa il
    chiamante). Un modo fuori da `MODI_RESOLVER` solleva `ValueError`.

    `forza` toglie il filtro «senza fonte»: e' l'unico modo di rifare una riga
    gia' `trovata`, e per questo si chiede a mano.

    Ogni filtro su una colonna nuova passa da `ha()`: senza la migrazione 01 la
    colonna `fonte_ufficiale_stato` non esiste e il filtro risponderebbe 42703.
    La scadenza del ricontrollo NON si filtra qui: `prossimo_controllo_at` sta
    in `bando_controllo`, e mescolare le due tabelle in una sola richiesta
    PostgREST costringerebbe a un embed che la RLS di `bando_controllo` non
    concede. La selezione per data la fa il chiamante, su `select_controlli`.
    """
    if modo not in MODI_RESOLVER:
        # Prima del `try`: un modo sbagliato non e' «nessun candidato».
        raise ValueError(f"modo del resolver sconosciuto: {modo!r}")
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
    if modo not in MODI_RESOLVER:
        # Un modo sconosciuto non e' un «nuovi» implicito (revisione #143).
        raise ValueError(f"modo del resolver sconosciuto: {modo!r}")
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
        # Giro 3 (§7): fuori i chiusi e i revocati (611 su 1 571, misura del
        # 01/10). `not.in` esclude anche i NULL: misurati 0 fra i candidati.
        query = query.not_.in_("stato_bando", list(STATI_FUORI_RICONTROLLI))
    elif modo == "precoce":
        # Giro 3 (§7): i bandi appena entrati, prima di preprocess ed enrich.
        # I `processed` chiusi o revocati, e cio' che `_auto_reject` scarta,
        # li toglie il chiamante: due `or` nella stessa query non si possono
        # combinare con certezza in PostgREST, e uno `scraped` ha spesso lo
        # stato ancora vuoto, che un `not.in` escluderebbe.
        query = query.in_("stato_processing", ["scraped", "processed"])
        if senza_fonte:
            query = query.or_(SENZA_FONTE)
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
    limit: int | None = None,
    con_calendario: bool = False,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati su cui `gemelli.py` cerca le corrispondenze esatte.

    Colonne minime: id, la chiave della fonte, i due URL confrontabili e cio'
    che serve a `scegli_master`. Mai `contenuto`, mai `raw_data` completo.

    `con_calendario=True` (il passo `gemelli`, contratto `bandi-giro-2` §19.9)
    aggiunge `bando_master_id`, per lasciare fuori le righe gia' fuse, e il
    `raw_data` delle sole righe senza `link_bando`: e' li' che il criterio
    `riga_calendario` legge la riga del calendario, e sono poche (86 al 30/09).

    `limit=None` (il default dal giro 3, §1 e §11: niente lotti) legge tutti i
    pubblicati; un numero resta un limite per chi lo chiede a mano.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili(
        "bando",
        ("id", "titolo", "titolo_raw", "link_bando", "fonte_id", "fonte_ufficiale_url",
         "fonte_ufficiale_host", "fonte_ufficiale_tipo", "fonte_ufficiale_stato",
         "chiave_esterna", "data_scadenza", "pubblicato_at", "slug")
        + (("bando_master_id",) if con_calendario else ()),
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
        righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto),
                        tetto=max(0, int(limit)) if limit is not None else None)
        if con_calendario and strumento.ha("bando", "raw_data"):
            senza_link = [r.get("id") for r in righe if not r.get("link_bando")]
            grezzi = {
                r.get("id"): r.get("raw_data") for r in _per_id(
                    lambda blocco: _client(client).table("bando")
                    .select("id,raw_data").in_("id", blocco),
                    senza_link)
            }
            for riga in righe:
                if riga.get("id") in grezzi:
                    riga["raw_data"] = grezzi[riga.get("id")]
        return righe
    except Exception as e:
        if con_calendario:
            # Il passo `gemelli` deve poter dire «non ho letto», non «nessun
            # gemello»: una lista vuota somiglia troppo a un giro pulito.
            raise
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


#: Le colonne di `bando` che servono a scegliere la pagina di riferimento di
#: un link (giro 3, §10: `dominio_ufficiale.scegli_fonte` o `link_bando`).
COLONNE_RIFERIMENTO: tuple[str, ...] = (
    "id", "link_bando", "fonte_ufficiale_url", "fonte_ufficiale_stato",
)


def select_riferimenti_bandi(
    bando_ids: Sequence[Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[Any, dict[str, Any]]:
    """`{bando_id: riga}` con `COLONNE_RIFERIMENTO`, per la quarta prova di
    `link-verifica` (giro 3, §10). A blocchi e a pagine (`_per_id`); `{}` se
    `bando` non c'e' o la lettura fallisce: senza riferimento la prova
    semplicemente non si fa."""
    strumento = _controllo(strumento)
    ids = list(dict.fromkeys(i for i in bando_ids if i is not None))
    if not ids or not strumento.tabella_esiste("bando"):
        return {}
    colonne = _colonne_disponibili("bando", COLONNE_RIFERIMENTO, strumento)
    try:
        righe = _per_id(
            lambda blocco: _client(client).table("bando").select(colonne).in_("id", blocco),
            ids,
        )
    except Exception as e:
        logger.warning("[db] select_riferimenti_bandi fallita: {}", e)
        return {}
    return {r.get("id"): dict(r) for r in righe}


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


#: La coda delle riscritture del monitor in `impronte_sezioni` (giro 3, §6):
#: `{novita: [...], tentativi: n, dal: iso}`. Stessa chiave e stessa forma di
#: `monitoraggio.CHIAVE_RISCRITTURA`, che la svuota.
CHIAVE_CODA_RISCRITTURA = "__riscrittura__"


def accoda_riscrittura(
    bando_id: Any,
    novita: Sequence[Mapping[str, Any]],
    *,
    adesso: Any = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Aggiunge `novita` alla coda delle riscritture che il monitor riprende.

    La rielaborazione la usa quando una data e' in colonna ma la prosa non si
    e' riallineata e nemmeno `riscrivi_scheda` l'ha riscritta (P2 di #160).
    `impronte_sezioni` e' la memoria del monitor (le impronte delle sezioni,
    `__link__`, `__versione__`): si legge la riga, si tocca solo la chiave
    della coda e si riscrive il resto com'era. **Se la lettura fallisce non si
    scrive**: una colonna riscritta con la sola coda cancellerebbe le impronte
    e il monitor vedrebbe cambiare tutte le sezioni. Le novita' si uniscono a
    quelle gia' in coda senza doppioni (`rigenera.unisci_novita`); i tentativi
    restano quelli del monitor. `prossimo_controllo_at` va ad adesso: anche un
    chiuso torna al giro dopo, come fa il monitor con la sua coda.
    """
    from datetime import datetime, timezone
    from .rigenera import unisci_novita
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_CONTROLLO) or not strumento.ha(
            TABELLA_CONTROLLO, "impronte_sezioni"):
        return {"scritto": False, "motivo": "colonne_assenti"}
    try:
        righe = (_client(client).table(TABELLA_CONTROLLO).select("bando_id,impronte_sezioni")
                 .eq("bando_id", bando_id).execute().data or [])
    except Exception as e:
        logger.warning("[db] coda delle riscritture del bando {} non letta: {}", bando_id, e)
        return {"scritto": False, "motivo": str(e)}
    sezioni_lette = righe[0].get("impronte_sezioni") if righe else None
    sezioni = dict(sezioni_lette) if isinstance(sezioni_lette, Mapping) else {}
    coda = sezioni.get(CHIAVE_CODA_RISCRITTURA)
    coda = dict(coda) if isinstance(coda, Mapping) else {}
    momento = adesso if isinstance(adesso, datetime_cls) else datetime.now(tz=timezone.utc)
    sezioni[CHIAVE_CODA_RISCRITTURA] = {
        "novita": unisci_novita(coda.get("novita") or (), novita),
        "tentativi": int(coda.get("tentativi") or 0),
        "dal": coda.get("dal") or momento.isoformat(),
    }
    return aggiorna_controllo(
        bando_id, {"impronte_sezioni": sezioni, "prossimo_controllo_at": momento.isoformat()},
        client=client, strumento=strumento)


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

#: Il marcatore della migrazione 11 e le sue due chiavi. `applica-eventi` lo
#: legge prima di mandare alla RPC un evento con `stato_proposto`, che la
#: versione della 04 brucerebbe (lo marca applicato senza toccare lo stato).
RPC_CAPACITA_EVENTI = "bando_capacita_eventi"
CAPACITA_TRADUZIONE = "traduce_stato_proposto"
CAPACITA_STATI_CINQUE = "stati_cinque"

#: Il marcatore della migrazione 14 (contratto `bandi-giro-3` §14 punto 5):
#: le transizioni di sospensione e revoca sono ammesse dal trigger. Lo legge
#: `capacita_sospensioni`; senza, il monitor tiene in ombra sospensione,
#: revoca e annullamento della revoca.
RPC_CAPACITA_SOSPENSIONI = "bando_capacita_sospensioni"

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
    #: `leggibile=False` serve a un caso solo: ripescare gli eventi applicati
    #: che non hanno mai ricevuto il cursore, cioe' quelli di un'attivazione
    #: interrotta a meta'. Restano invisibili per sempre, perche' la selezione
    #: normale cerca `applicato=false`.
    leggibile: bool | None = None,
    bando_id: Any = None,
    con_riferimento: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
    colonne: Sequence[str] | None = None,
    #: Filtro esatto sugli id: `applica-eventi --ids`, il comando di ripresa
    #: che gli allarmi del monitor scrivono (solo gli eventi di quel giro).
    ids: Sequence[Any] = (),
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
        if ids:
            query = query.in_("id", list(ids))
        if bando_id is not None:
            query = query.eq("bando_id", bando_id)
        if tipi:
            query = query.in_("tipo", list(tipi))
        if applicato is not None and strumento.ha(TABELLA_EVENTO, "applicato"):
            query = query.eq("applicato", applicato)
        if verificato is not None:
            query = query.eq("verificato", verificato)
        if leggibile is not None and strumento.ha(TABELLA_EVENTO, "leggibile"):
            query = query.eq("leggibile", leggibile)
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

    Si legge **tutto** (contratto `bandi-giro-3` §1 e §5: niente lotti). Il
    tetto di 5 000 righe e il suo allarme di «coda troncata» non ci sono piu':
    la selezione per priorita' deve ordinare il corpus intero, e l'unico
    freno del monitor e' il tempo, con rotazione. `limit` resta solo per chi
    lancia a mano un controllo su poche righe.
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

    tetto = max(0, int(limit)) if limit is not None else None
    try:
        # Si scorre invece di limitare: `.limit(5000)` tornava 1 000 righe
        # (`max-rows`), quindi la coda vedeva meno di meta' dei pubblicati con
        # fonte trovata senza che nessuno lo dicesse.
        return _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto),
                       tetto=tetto)
    except Exception as e:
        logger.warning("[db] select_bandi_da_monitorare fallita: {}", e)
        return []


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
) -> dict[str, float] | None:
    """Quanto hanno gia' consumato oggi e nel mese i giri precedenti (§6.2).

    Senza questa somma, con quattro giri al giorno il tetto giornaliero
    varrebbe quattro volte tanto. `{}` se `pipeline_run` non c'e' ancora: il
    tetto resta quello del singolo giro, che e' la degradazione giusta.
    **None se la lettura fallisce** (giro 3, §18.5): un consumo ignoto non e'
    «niente speso». La manutenzione lo tratta come tetto raggiunto
    (`bilancio.verifica_con_consumo`), l'ingresso lo ignora.

    Restituisce le `VOCI_CONSUMO` della giornata e, dal giro 3 (contratto
    `bandi-giro-3` §4 e §16), `crediti_mese` e `usd_mese` del mese: il tetto
    mensile si applica davvero, e per farlo basta **una** lettura, dalla
    mezzanotte del primo del mese di Roma, scorsa fino in fondo, con le sole
    voci estratte dal jsonb (le righe `pipeline` sono grandi). La giornata si
    separa qui, sull'istante di `avviato_at`.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_RUN):
        return {}
    # La giornata e il mese sono quelli del **calendario di Roma**, come
    # ovunque nel package (`oggi_roma`). Con la data UTC i giri delle 00:00
    # italiane cadevano nel giorno precedente per un'ora (due in estate): il
    # tetto giornaliero ripartiva da zero a mezzanotte di Londra, non di Roma,
    # e nella finestra fra i due mezzanotti valeva il doppio. Si filtra
    # sull'ISTANTE di mezzanotte romana, non sulla sola data: `avviato_at` e'
    # un `timestamptz`, e una data nuda verrebbe letta come mezzanotte UTC.
    from .stato_bando import _istante, adesso_roma
    momento = adesso_roma(adesso if isinstance(adesso, datetime_cls) else None)
    inizio_giorno = momento.replace(hour=0, minute=0, second=0, microsecond=0)
    inizio_mese = inizio_giorno.replace(day=1)
    voci = ",".join(f"{voce}:contatori->>{voce}" for voce in VOCI_CONSUMO)
    try:
        righe = _scorri(lambda quanto, salto: _pagina(
            _client(client).table(TABELLA_RUN).select(f"id,step,avviato_at,{voci}")
            .gte("avviato_at", inizio_mese.isoformat()).order("id"),
            quanto, salto))
    except Exception as e:
        logger.warning("[db] consumo_oggi fallita: {}", e)
        return None
    # I lotti una tantum (`step='backfill:Lx'`) hanno tetti propri e non
    # consumano quelli di regime (bilancio, M19). Sommarli qui voleva dire che
    # un lotto lanciato a mano la mattina fermava il monitor di regime per il
    # resto della giornata: il 25/09/2026 il giro delle 18:00 si e' fermato a
    # «tetto giornaliero classificazioni raggiunto (201/30)». Resta fuori anche
    # la riga del giro (`step='pipeline'`), che risomma i crediti del resolver
    # gia' presenti nella sua riga: contata due volte (`bilancio.conta_nel_regime`).
    # Lo stesso filtro vale per il mese.
    from .bilancio import conta_nel_regime
    somma = {voce: 0.0 for voce in VOCI_CONSUMO}
    somma.update({VOCE_CREDITI_MESE: 0.0, VOCE_USD_MESE: 0.0})
    for riga in righe:
        if not conta_nel_regime(str(riga.get("step") or "")):
            continue
        valori = {voce: _voce_numerica(riga.get(voce)) for voce in VOCI_CONSUMO}
        somma[VOCE_CREDITI_MESE] += valori["crediti"]
        somma[VOCE_USD_MESE] += valori["usd"]
        # Una riga con l'istante illeggibile conta nella giornata: per un
        # tetto di spesa e' meglio fermarsi un giro prima che spendere due volte.
        quando = _istante(riga.get("avviato_at"))
        if quando is not None and quando < inizio_giorno:
            continue
        for voce in VOCI_CONSUMO:
            somma[voce] += valori[voce]
    return somma


#: Le due chiavi del mese che `consumo_oggi` aggiunge alle `VOCI_CONSUMO`
#: della giornata (giro 3, §4: il tetto mensile si applica davvero).
VOCE_CREDITI_MESE = "crediti_mese"
VOCE_USD_MESE = "usd_mese"


def _voce_numerica(valore: Any) -> float:
    """Una voce di consumo estratta dal jsonb (`->>` la da' come testo). Un
    valore assente o non numerico vale 0; un booleano non e' un numero."""
    if valore is None or isinstance(valore, bool):
        return 0.0
    try:
        return float(valore)
    except (TypeError, ValueError):
        return 0.0


def consumo_passo_oggi(
    step: str,
    *,
    adesso: Any = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, float] | None:
    """`{crediti, usd}` delle righe di `step` dalla mezzanotte di Roma.

    Serve ai passi `backfill:` il cui tetto vale sulla giornata e non sul
    singolo lancio (la rielaborazione: 60 $ al giorno, revisione #146), e che
    `consumo_oggi` lascia fuori di proposito. `{}` se `pipeline_run` non c'e'
    (si parte da zero, come `consumo_oggi`); None se la lettura fallisce:
    il chiamante decide, e per un tetto di spesa la scelta prudente e'
    non partire.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_RUN):
        return {}
    from .stato_bando import adesso_roma
    momento = adesso_roma(adesso if isinstance(adesso, datetime_cls) else None)
    inizio_giorno = momento.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        righe = _scorri(lambda quanto, salto: _pagina(
            _client(client).table(TABELLA_RUN)
            .select("id,crediti:contatori->>crediti,usd:contatori->>usd")
            .eq("step", step).gte("avviato_at", inizio_giorno.isoformat()).order("id"),
            quanto, salto))
    except Exception as e:
        logger.warning("[db] consumo_passo_oggi({}) fallita: {}", step, e)
        return None
    return {
        "crediti": sum(_voce_numerica(r.get("crediti")) for r in righe),
        "usd": round(sum(_voce_numerica(r.get("usd")) for r in righe), 6),
    }


#: Tabella dei lock di esecuzione (`blocco.py`): la legge solo `salute`.
TABELLA_LOCK = "pipeline_lock"


def select_lock(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Le righe di `pipeline_lock`, scadute comprese: una per lock, poche.

    Le legge il sender all'avvio per rilasciare i propri lock orfani
    (`backend/app/lock_orfani.py`, contratto di ottobre §8). `[]` se la
    tabella non c'e'; un errore di rete si solleva, e il chiamante lo tratta
    come «non so, non rilascio niente».
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_LOCK):
        return []
    return list((
        _client(client).table(TABELLA_LOCK)
        .select("nome,proprietario,acquisito_at,scade_at").order("nome").execute()
    ).data or [])


def misure_salute(
    *,
    adesso: Any = None,
    client: Any | None = None,
    strumento: Any | None = None,
    client_anon: Any | None = None,
    verifica_attiva: bool | None = None,
) -> dict[str, Any]:
    """Le righe che `salute` giudica (`telemetria.stato_da_misure`). Solo letture.

    Fino al 26/09/2026 `salute` guardava tre valori di configurazione e diceva
    «nessun allarme» senza aver letto niente: il monitor fermo, i tetti, i lock
    orfani non potevano mai scattare. Qui si leggono.

    Una tabella o una colonna che lo schema non espone vale `None` (misura non
    disponibile, e `salute` lo dice negli avvisi). Se lo schema non e' leggibile
    affatto si solleva: «non so niente» non deve somigliare a «tutto bene».
    Ogni lettura che puo' superare le 1 000 righe passa da `_scorri`; i
    conteggi si chiedono al server (`count=exact`) invece di scaricare le righe.

    Le chiavi del giro 2 (contratto `bandi-giro-2` §8 e §14, percorso B):

    - `ultime_pipeline` / `ultimi_monitor`: righe recenti prima, con i soli
      contatori di `CONTATORI_PIPELINE` / `CONTATORI_MONITOR`, rimessi nella
      forma annidata del jsonb (`_contatori_mirati`);
    - `fermi_in_lavorazione`: bandi in `processed` o `enriched` entrati da
      oltre `ORE_SCRAPED_FERMO` ore e da meno di `GIORNI_FERMI_IN_LAVORAZIONE`
      giorni; `arretrato_in_lavorazione`: gli stessi senza finestra (solo
      informativo); `ultimo_bando_nuovo_at`: il `created_at` piu' recente;
    - `proposte_7g` (senza `TIPI_EVENTO_DI_SERVIZIO`), `ammessi_non_applicati`,
      `in_attesa_pubblicazione`: conteggi su `bando_evento`;
    - `vista_ms` / `vista_ms_ruolo` (percorso A, §19.6): quanto impiega una
      pagina di `bando_pubblico`, come anon se l'ambiente ha la anon key;
    - `da_verificare` (percorso A): `None` finche' `VERIFICA_STATO_MODALITA`
      non e' `attivo` (`verifica_attiva`, per difetto dalle impostazioni).
      In ombra il riepilogo per BandoFit lo deve dare `null` (contratto DB,
      revisione avversaria del 01/10, ciclo 2): passare da `null` a oggetto
      cambia il tipo, e lo si fa insieme all'attivazione.

    `job_orario` resta fuori: e' una RPC, e la chiama chi fa la fotografia.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        raise RuntimeError("schema del DB bandi non leggibile: la tabella `bando` non risulta")
    from datetime import timedelta
    from .stato_bando import adesso_roma
    from .telemetria import GIORNI_NUOVI, ORE_SCRAPED_FERMO, SOGLIA_CONTROLLI_FALLITI
    momento = adesso_roma(adesso if isinstance(adesso, datetime_cls) else None)
    sb = _client(client)
    misure: dict[str, Any] = {
        "monitor": None, "pipeline": None, "mese": None, "nuovi": None,
        "vivi": None, "falliti": None, "lock": None, "scraped_fermi": None,
        "ultime_pipeline": None, "ultimi_monitor": None,
        "fermi_in_lavorazione": None, "arretrato_in_lavorazione": None,
        "ultimo_bando_nuovo_at": None,
        "proposte_7g": None, "ammessi_non_applicati": None, "in_attesa_pubblicazione": None,
        "vista_ms": None, "vista_ms_ruolo": None, "ultimi_import_indicepa": None,
        "da_verificare": None, "letture_scadute": None, "verifica_7g": None,
        "ultime_verifiche": None, "ultimi_ingressi": None, "aperti_senza_scadenza": None,
    }

    if strumento.tabella_esiste(TABELLA_RUN):
        # Solo il monitor di regime: `giro` e' vuoto sui lanci a mano.
        # Il motivo di un giro fermato dal tetto sta nei contatori, non nella colonna.
        misure["monitor"] = list((
            sb.table(TABELLA_RUN)
            .select("avviato_at,concluso_at,esito,giro,interrotto_per_tetto,motivo:contatori->>motivo,"
                    "classificazioni:contatori->>classificazioni,"
                    "classificazioni_fallite:contatori->>classificazioni_fallite,"
                    "seconde_opinioni_fallite:contatori->>seconde_opinioni_fallite,"
                    "usd:contatori->>usd")
            .eq("step", "monitor").not_.is_("giro", "null")
            .order("avviato_at", desc=True).limit(60).execute()
        ).data or [])
        misure["pipeline"] = list((
            sb.table(TABELLA_RUN).select("avviato_at,esito,interrotto_per_tetto,motivo,contatori")
            .eq("step", "pipeline").order("avviato_at", desc=True).limit(10).execute()
        ).data or [])
        # Mese del calendario di Roma, come `consumo_oggi`. Solo le due voci
        # che servono, estratte dal jsonb: le righe `pipeline` sono grandi.
        inizio_mese = momento.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        misure["mese"] = _scorri(lambda quanto, salto: _pagina(
            sb.table(TABELLA_RUN)
            .select("id,step,crediti:contatori->>crediti,usd:contatori->>usd")
            .gte("avviato_at", inizio_mese.isoformat()).order("id"),
            quanto, salto))
        # Le ultime 20 righe del giro, anche quelle saltate e quelle di boot:
        # `riavvii_ripetuti` le conta, `passo_degradato` salta le saltate.
        # `id` come secondo ordine: due righe con lo stesso `avviato_at` non
        # devono scambiarsi di posto fra una lettura e l'altra.
        misure["ultime_pipeline"] = [
            _contatori_mirati(riga, CONTATORI_PIPELINE) for riga in (
                sb.table(TABELLA_RUN)
                .select(_select_con_contatori(CONTATORI_PIPELINE))
                .eq("step", "pipeline")
                .order("avviato_at", desc=True).order("id", desc=True)
                .limit(RIGHE_ULTIME_PIPELINE).execute()
            ).data or []]
        # Gli ultimi import di IndicePA (§19.8): la loro riga ha step='domini'.
        misure["ultimi_import_indicepa"] = [
            _contatori_mirati(riga, CONTATORI_INDICEPA) for riga in (
                sb.table(TABELLA_RUN)
                .select(_select_con_contatori(CONTATORI_INDICEPA))
                .eq("step", STEP_DOMINI)
                .order("avviato_at", desc=True).order("id", desc=True)
                .limit(RIGHE_IMPORT_INDICEPA).execute()
            ).data or []]
        # Solo il monitor di regime, come `monitor`: le chiavi degli eventi
        # sono misurate su queste righe (misure del giro 2, M6).
        misure["ultimi_monitor"] = [
            _contatori_mirati(riga, CONTATORI_MONITOR) for riga in (
                sb.table(TABELLA_RUN)
                .select(_select_con_contatori(CONTATORI_MONITOR))
                .eq("step", "monitor").not_.is_("giro", "null")
                .order("avviato_at", desc=True).order("id", desc=True)
                .limit(RIGHE_ULTIMI_MONITOR).execute()
            ).data or []]

    if all(strumento.ha("bando", c) for c in ("pubblicato", "pubblicato_at", "fonte_ufficiale_stato")):
        dal = (momento - timedelta(days=GIORNI_NUOVI)).isoformat()
        misure["nuovi"] = _scorri(lambda quanto, salto: _pagina(
            sb.table("bando").select("id,fonte_ufficiale_stato")
            .eq("pubblicato", True).gte("pubblicato_at", dal).order("id"),
            quanto, salto))

    if (strumento.ha("bando", "pubblicato")
            and strumento.ha("bando_controllo", "controlli_falliti")):
        vivi = _scorri(lambda quanto, salto: _pagina(
            sb.table("bando").select("id")
            .eq("pubblicato", True).not_.in_("stato_bando", ["chiuso", "revocato"]).order("id"),
            quanto, salto))
        misure["vivi"] = [r["id"] for r in vivi]
        falliti = _scorri(lambda quanto, salto: _pagina(
            sb.table("bando_controllo").select("bando_id")
            .gte("controlli_falliti", SOGLIA_CONTROLLI_FALLITI).order("bando_id"),
            quanto, salto))
        misure["falliti"] = [r["bando_id"] for r in falliti]

    if strumento.ha("bando", "created_at"):
        # I bandi entrati e mai passati dal preprocess: col credito Anthropic a
        # zero (dal 26/09/2026) restavano li' senza che niente lo dicesse.
        soglia = (momento - timedelta(hours=ORE_SCRAPED_FERMO)).isoformat()
        misure["scraped_fermi"] = _scorri(lambda quanto, salto: _pagina(
            sb.table("bando").select("id")
            .eq("stato_processing", "scraped").lt("created_at", soglia).order("id"),
            quanto, salto))
        # Lo stesso limite per chi e' passato dal preprocess e si e' fermato
        # dopo: arricchimento o redazione non lo portano a `completed`. Solo
        # gli ultimi `GIORNI_FERMI_IN_LAVORAZIONE` giorni: le 569 righe
        # `processed` ferme da giugno (misurate il 30/09) terrebbero l'avviso
        # acceso per sempre, e un avviso sempre acceso non avvisa piu'.
        # L'arretrato intero resta visibile in `arretrato_in_lavorazione`.
        dal_fermi = (momento - timedelta(days=GIORNI_FERMI_IN_LAVORAZIONE)).isoformat()
        misure["fermi_in_lavorazione"] = _conta(
            sb.table("bando").select("id", count="exact")
            .in_("stato_processing", list(STATI_IN_LAVORAZIONE))
            .gte("created_at", dal_fermi).lt("created_at", soglia))
        misure["arretrato_in_lavorazione"] = _conta(
            sb.table("bando").select("id", count="exact")
            .in_("stato_processing", list(STATI_IN_LAVORAZIONE)))
        # L'ultimo bando entrato, qualunque sia il suo stato: dice se
        # l'ingresso produce ancora righe. I NULL fuori, perche' in un ordine
        # decrescente Postgres li mette in testa.
        ultimo = list((
            sb.table("bando").select("created_at")
            .not_.is_("created_at", "null")
            .order("created_at", desc=True).limit(1).execute()
        ).data or [])
        misure["ultimo_bando_nuovo_at"] = ultimo[0].get("created_at") if ultimo else None

    if strumento.tabella_esiste(TABELLA_LOCK):
        misure["lock"] = list((
            sb.table(TABELLA_LOCK).select("nome,proprietario,acquisito_at,scade_at")
            .order("nome").execute()
        ).data or [])

    # Conteggi sugli eventi, ciascuno solo se le sue colonne esistono.
    if strumento.ha(TABELLA_EVENTO, "rilevato_at"):
        # Senza i tipi di servizio: al 30/09 erano 8 943 righe su 9 232 in una
        # settimana (fonte ufficiale trovata o no, segnali del listing), e il
        # numero non diceva piu' niente sulle proposte vere.
        dal_7g = (momento - timedelta(days=GIORNI_PROPOSTE)).isoformat()
        proposte = sb.table(TABELLA_EVENTO).select("id", count="exact").gte("rilevato_at", dal_7g)
        if strumento.ha(TABELLA_EVENTO, "tipo"):
            proposte = proposte.not_.in_("tipo", list(TIPI_EVENTO_DI_SERVIZIO))
        misure["proposte_7g"] = _conta(proposte)
    if strumento.ha(TABELLA_EVENTO, "verificato") and strumento.ha(TABELLA_EVENTO, "applicato"):
        # Ammessi dai gate e non ancora riversati in `bando`.
        misure["ammessi_non_applicati"] = _conta(
            sb.table(TABELLA_EVENTO).select("id", count="exact")
            .eq("verificato", True).eq("applicato", False))
    if strumento.ha(TABELLA_EVENTO, "applicato") and strumento.ha(TABELLA_EVENTO, "leggibile"):
        # Applicati ma senza cursore: `bando` e' cambiato, BandoFit non lo vede
        # (RIPRESA §5, trappola 8: servono due scritture).
        misure["in_attesa_pubblicazione"] = _conta(
            sb.table(TABELLA_EVENTO).select("id", count="exact")
            .eq("applicato", True).eq("leggibile", False))

    # Le tre misure del percorso A (§14 e §19.6): None finche' la 13 non c'e'.
    # `da_verificare` anche finche' la verifica non e' attiva.
    if verifica_attiva is None:
        verifica_attiva = _verifica_attiva()
    if verifica_attiva:
        misure["da_verificare"] = _misura_da_verificare(sb, strumento, momento)
    misure["letture_scadute"] = _misura_letture_scadute(sb, strumento, momento)
    if strumento.tabella_esiste(TABELLA_RUN):
        misure["verifica_7g"] = _misura_verifica_7g(sb, momento)
        # Le righe del passo per i codici A di `telemetria` (#76): le ultime
        # dieci della fase controlli, e quelle della fase ingresso della
        # settimana. Contatori mirati, nella forma annidata di `ultime_pipeline`.
        misure["ultime_verifiche"] = [
            _contatori_mirati(riga, CONTATORI_ULTIME_VERIFICHE) for riga in (
                sb.table(TABELLA_RUN)
                .select(_select_con_contatori(CONTATORI_ULTIME_VERIFICHE))
                .eq("step", STEP_VERIFICA_STATO)
                .order("avviato_at", desc=True).order("id", desc=True)
                .limit(RIGHE_ULTIME_VERIFICHE).execute()
            ).data or []]
        dal_ingressi = (momento - timedelta(days=GIORNI_VERIFICA)).isoformat()
        misure["ultimi_ingressi"] = [
            _contatori_mirati(riga, CONTATORI_INGRESSO) for riga in _scorri(
                lambda quanto, salto: _pagina(
                    sb.table(TABELLA_RUN).select(_select_con_contatori(CONTATORI_INGRESSO))
                    .eq("step", STEP_VERIFICA_INGRESSO).gte("avviato_at", dal_ingressi)
                    .order("avviato_at", desc=True).order("id", desc=True), quanto, salto))]
    if strumento.ha(VISTA_PUBBLICA, "stato_effettivo"):
        # Il denominatore di `aperti_senza_conferma` (§19.6): gli aperti senza
        # scadenza come li vede il sito.
        misure["aperti_senza_scadenza"] = _conta(
            sb.table(VISTA_PUBBLICA).select("id", count="exact")
            .eq("stato_effettivo", STATO_APERTO).is_("data_scadenza", "null"))

    if strumento.tabella_esiste(VISTA_PUBBLICA):
        colonne = COLONNE_VISTA_MS
        if strumento.ha(VISTA_PUBBLICA, COLONNA_VISTA_MS_DA_VERIFICARE):
            colonne = f"{colonne},{COLONNA_VISTA_MS_DA_VERIFICARE}"
        misure["vista_ms"], misure["vista_ms_ruolo"] = _misura_vista(
            sb, client_anon if client_anon is not None else _client_anon(), colonne=colonne)

    return misure


#: Quante righe `step='pipeline'` legge `misure_salute` per il giro 2 (§14).
RIGHE_ULTIME_PIPELINE = 20
#: Quante righe del monitor di regime legge `misure_salute` per il giro 2.
RIGHE_ULTIMI_MONITOR = 10
#: Finestra di `proposte_7g`, in giorni.
GIORNI_PROPOSTE = 7
#: I tipi di evento che non sono proposte ma lavoro di servizio del resolver
#: e del listing: fuori da `proposte_7g` (decisione del lead, 30/09).
TIPI_EVENTO_DI_SERVIZIO: tuple[str, ...] = (
    "fonte_ufficiale_non_trovata", "fonte_ufficiale_verificata",
    "segnale_fonte", "sparito_dalla_fonte",
)
#: Gli stati di chi e' entrato, e' passato dal preprocess e non e' ancora
#: `completed`: la misura `fermi_in_lavorazione`.
STATI_IN_LAVORAZIONE: tuple[str, ...] = ("processed", "enriched")
#: Quanto indietro guarda `fermi_in_lavorazione`, in giorni (decisione del
#: lead, 30/09): l'arretrato piu' vecchio sta in `arretrato_in_lavorazione`.
GIORNI_FERMI_IN_LAVORAZIONE = 7

#: La vista pubblica che il sito e BandoFit leggono con la anon key.
VISTA_PUBBLICA = "bando_pubblico"
#: La lettura di prova di `vista_ms` (§19.6, codice `vista_lenta`): la query
#: della Verifica 7 della 05 (in fondo alla 13, «Verifica a mano», punto 2),
#: cioe' la prima pagina dei non chiusi. `stato_da_verificare` (della 13) si
#: chiede solo se la vista ce l'ha: senza, la lettura fallirebbe e la misura
#: mancherebbe.
#:
#: Giro 3 (B30, contratto §10): niente `link_bando`, `link_candidatura` e
#: `allegati`. La migrazione 07 li toglie dalla vista, e una misura che li
#: chiede fallirebbe da quel giorno in poi (`vista_ms` None per sempre).
COLONNE_VISTA_MS = "id,slug,titolo,stato_effettivo,data_scadenza"
COLONNA_VISTA_MS_DA_VERIFICARE = "stato_da_verificare"
STATI_VISTA_MS: tuple[str, ...] = ("aperto", "in apertura prossimamente")
RIGHE_VISTA_MS = 20
#: La anon key del DB bandi, con lo stesso nome del `.env` del sito. Se c'e'
#: nell'ambiente del processo `vista_ms` si misura come anon, cioe' con la RLS
#: che il sito paga; senza, con la service key (che la RLS la salta).
VARIABILE_ANON = "PUBLIC_SUPABASE_BANDI_ANON_KEY"
RUOLO_ANON = "anon"
RUOLO_SERVIZIO = "servizio"


#: Lo step della riga di `pipeline_run` del passo verifica-stato.
STEP_VERIFICA_STATO = "verifica_stato"
#: Lo stato effettivo di un candidato -> il ramo della regola (§3, §19.3).
RAMI_DA_VERIFICARE: dict[str, str] = {
    "in apertura prossimamente": "in_apertura",
    "aperto": "aperto",
}
#: I contatori della riga del passo che il riepilogo porta (§5.9, §9.1).
CONTATORI_VERIFICA: tuple[tuple[str, ...], ...] = (
    ("modalita",), ("proposte_per_tipo",), ("applicati_per_tipo",),
    ("trattenute_per_freno",), ("pagine_rimosse",), ("forse_non_bandi",),
)
#: Lo step della riga della fase ingresso del passo (§5.10): diverso, perche'
#: «l'ultima riga `verifica_stato`» resti quella dei controlli.
STEP_VERIFICA_INGRESSO = "verifica_stato_ingresso"
RIGHE_ULTIME_VERIFICHE = 10
#: I contatori delle righe della fase controlli per i codici A (#76).
CONTATORI_ULTIME_VERIFICHE: tuple[tuple[str, ...], ...] = (
    ("fase",), ("modalita",), ("motivo_saltato",), ("letture_non_verificanti",),
    ("trattenute_per_freno",), ("prosa_non_riscritta",), ("eventi_non_scritti",),
    # Codice `eventi_non_leggibili`, come `eventi_invisibili` del monitor.
    ("eventi_non_leggibili",),
)
#: I contatori delle righe della fase ingresso (codice `ingresso_trattenuti`).
CONTATORI_INGRESSO: tuple[tuple[str, ...], ...] = (
    ("trattenuti",), ("trattenuti_senza_appiglio",), ("rilasciati_a_tempo",),
)
#: Dopo quanti giorni una lettura leggibile e' «scaduta» (codice `leggibile_non_letto`).
GIORNI_LETTURA_SCADUTA = 16
#: La finestra di `verifica_7g` e di `chiusure_applicate_7g`.
GIORNI_VERIFICA = 7


def _intero_o_zero(valore: Any) -> int:
    try:
        return int(valore or 0)
    except (TypeError, ValueError):
        return 0


def _verifica_attiva() -> bool:
    """`VERIFICA_STATO_MODALITA == 'attivo'`. Impostazioni illeggibili: ombra."""
    try:
        return getattr(get_settings(), "verifica_stato_modalita", "ombra") == "attivo"
    except Exception:
        return False


def _misura_da_verificare(sb: Any, strumento: Any, momento: Any) -> dict[str, Any] | None:
    """`da_verificare` del riepilogo (§9.1): i motivi per ramo e i numeri del passo.

    I conteggi vengono dalla vista, come li vedono il sito e BandoFit: una sola
    GET delle righe con un motivo (poche centinaia), contate qui per ramo e
    motivo, invece di dieci conteggi ognuno dei quali ricalcolerebbe la vista
    intera. Il ramo e' quello dello `stato_effettivo` (un «in apertura» con
    l'apertura raggiunta sta nel ramo A). `None` senza la 13.
    """
    from datetime import timedelta
    if not strumento.ha(VISTA_PUBBLICA, "stato_da_verificare"):
        return None
    esito: dict[str, Any] = {ramo: {} for ramo in RAMI_DA_VERIFICARE.values()}
    for riga in _scorri(lambda quanto, salto: _pagina(
            sb.table(VISTA_PUBBLICA).select("id,stato_effettivo,stato_da_verificare")
            .not_.is_("stato_da_verificare", "null").order("id"), quanto, salto)):
        ramo = RAMI_DA_VERIFICARE.get(str(riga.get("stato_effettivo") or ""))
        motivo = riga.get("stato_da_verificare")
        if ramo and motivo:
            esito[ramo][motivo] = esito[ramo].get(motivo, 0) + 1

    contatori: Mapping[str, Any] = {}
    if strumento.tabella_esiste(TABELLA_RUN):
        ultime = list((
            sb.table(TABELLA_RUN).select(_select_con_contatori(CONTATORI_VERIFICA))
            .eq("step", STEP_VERIFICA_STATO)
            .order("avviato_at", desc=True).order("id", desc=True).limit(1).execute()
        ).data or [])
        if ultime:
            contatori = _contatori_mirati(ultime[0], CONTATORI_VERIFICA)["contatori"]
    proposte = contatori.get("proposte_per_tipo")
    proposte = proposte if isinstance(proposte, Mapping) else {}
    applicati = contatori.get("applicati_per_tipo")
    applicati = applicati if isinstance(applicati, Mapping) else {}
    if contatori.get("modalita") == "attivo":
        # In attivo «in ombra» sono le proposte non applicate (tetto, freno).
        in_ombra = {t: max(0, _intero_o_zero(n) - _intero_o_zero(applicati.get(t)))
                    for t, n in proposte.items()}
    else:
        in_ombra = {t: _intero_o_zero(n) for t, n in proposte.items()}
    frenati = contatori.get("trattenute_per_freno")
    esito["proposte_in_ombra_per_tipo"] = {t: n for t, n in in_ombra.items() if n}
    esito["host_frenati"] = sum(
        1 for n in (frenati.values() if isinstance(frenati, Mapping) else ()) if _intero_o_zero(n))
    esito["pagine_rimosse"] = _intero_o_zero(contatori.get("pagine_rimosse"))
    esito["forse_non_bandi"] = _intero_o_zero(contatori.get("forse_non_bandi"))

    esito["chiusure_applicate_7g"] = 0
    if all(strumento.ha(TABELLA_EVENTO, c) for c in ("tipo", "origine", "applicato", "rilevato_at")):
        dal = (momento - timedelta(days=GIORNI_VERIFICA)).isoformat()
        esito["chiusure_applicate_7g"] = _conta(
            sb.table(TABELLA_EVENTO).select("id", count="exact")
            .eq("tipo", "chiusura").eq("origine", "worker").eq("applicato", True)
            .gte("rilevato_at", dal)) or 0
    return esito


def _misura_letture_scadute(sb: Any, strumento: Any, momento: Any) -> int | None:
    """Candidati con una pagina leggibile e l'ultima lettura piu' vecchia di 16 giorni.

    Due letture di soli id, incrociate qui: le letture scadute (non
    'illeggibile') e i candidati di `select_da_verificare`. `None` senza la 13.
    """
    from datetime import timedelta
    if not strumento.ha(TABELLA_CONTROLLO, "lettura_stato"):
        return None
    soglia = (momento - timedelta(days=GIORNI_LETTURA_SCADUTA)).isoformat()
    scadute = {r.get("bando_id") for r in _scorri(lambda quanto, salto: _pagina(
        sb.table(TABELLA_CONTROLLO).select("bando_id")
        .lt("lettura_stato_at", soglia).neq("lettura_stato->>pagina", "illeggibile")
        .order("bando_id"), quanto, salto))}
    if not scadute:
        return 0

    def _candidati() -> Any:
        query = sb.table("bando").select("id")
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", True)
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        return query.or_(
            f'stato_bando.eq."{STATO_IN_APERTURA}",'
            f"and(stato_bando.eq.{STATO_APERTO},data_scadenza.is.null)"
        ).order("id")

    candidati = {r.get("id") for r in _scorri(lambda quanto, salto: _pagina(
        _candidati(), quanto, salto))}
    return len(scadute & candidati)


def _misura_verifica_7g(sb: Any, momento: Any) -> dict[str, dict[str, int]] | None:
    """`esiti_per_estrattore` sommati sulle righe del passo degli ultimi 7 giorni.

    `{chiave: {letture, esiti}}`, per `estrattore_muto`. `None` se il passo non
    ha righe nella finestra: nessuna misura, non «zero letture».
    """
    from datetime import timedelta
    dal = (momento - timedelta(days=GIORNI_VERIFICA)).isoformat()
    righe = _scorri(lambda quanto, salto: _pagina(
        sb.table(TABELLA_RUN).select("id,esiti:contatori->esiti_per_estrattore")
        .eq("step", STEP_VERIFICA_STATO).gte("avviato_at", dal).order("id"),
        quanto, salto))
    if not righe:
        return None
    somma: dict[str, dict[str, int]] = {}
    for riga in righe:
        esiti = riga.get("esiti")
        if not isinstance(esiti, Mapping):
            continue
        for chiave, valori in esiti.items():
            if not isinstance(valori, Mapping):
                continue
            voce = somma.setdefault(str(chiave), {"letture": 0, "esiti": 0})
            voce["letture"] += _intero_o_zero(valori.get("letture"))
            voce["esiti"] += _intero_o_zero(valori.get("esiti"))
    return somma


def _client_anon() -> Any | None:
    """Un client con la anon key, se l'ambiente ce l'ha. La chiave non si stampa."""
    import os
    chiave = (os.environ.get(VARIABILE_ANON) or "").strip()
    if not chiave:
        return None
    try:
        return create_client(get_settings().supabase_url, chiave)
    except Exception as e:
        # Solo il tipo: il messaggio di un client rifiutato puo' citare la chiave.
        logger.warning("[db] client anon non creato: {}", type(e).__name__)
        return None


def _misura_vista(
    servizio: Any, anon: Any | None, *, colonne: str = COLONNE_VISTA_MS,
) -> tuple[float | None, str]:
    """(millisecondi, ruolo) della lettura di prova di `bando_pubblico`: filtro,
    ordine e limite della Verifica 7.

    `None` se la lettura fallisce: una misura mancante, non una vista veloce.
    """
    import time
    client, ruolo = (anon, RUOLO_ANON) if anon is not None else (servizio, RUOLO_SERVIZIO)
    inizio = time.monotonic()
    try:
        (client.table(VISTA_PUBBLICA).select(colonne)
         .in_("stato_effettivo", list(STATI_VISTA_MS))
         .order("data_pubblicazione", desc=True, nullsfirst=False).order("id")
         .limit(RIGHE_VISTA_MS).execute())
    except Exception as e:
        logger.warning("[db] lettura di prova di {} fallita ({}): {}",
                       VISTA_PUBBLICA, ruolo, type(e).__name__)
        return None, ruolo
    return round((time.monotonic() - inizio) * 1000, 1), ruolo

#: Le chiavi di `state["steps"]` del giro, nell'ordine (contratto
#: `bandi-giro-3` §2; `backend/app/bandi_pipeline.py`, che il test
#: d'orchestrazione confronta con questo elenco).
PASSI_DEL_GIRO: tuple[str, ...] = (
    "discover", "scrape", "domini", "resolver_precoce", "preprocess", "enrich",
    "resolver", "ricontrolli", "verifica_stato_ingresso", "seo", "link_verifica",
    "rielaborazione", "monitor", "verifica_stato", "gemelli",
)

#: I contatori della riga `step='pipeline'` che salute e sorveglia giudicano,
#: come percorsi dentro il jsonb. Chiavi misurate sul DB vivo il 30/09/2026
#: (`docs/bandi-monitor/misure-giro-2-2026-10.md`, M6): le fonti tentate sono
#: `fonti_processate + fonti_errors`, e `doppioni_oe` ed `enriched_db_ok`
#: mancano sulle righe vecchie (valgono 0). `passi_non_ok`,
#: `riavvio_dopo_crash` e `scrape.fonti_in_errore` arrivano col giro 2; i
#: contatori di sosta e fusione della SEO (`trattieni_e_fondi`) dalla
#: revisione del 01/10, perche' la sorveglianza veda chi resta fuori dalla
#: pubblicazione e perche'.
#:
#: Giro 3 (contratto §1 e §16): piu' la `copertura` di ciascuno dei 15 passi
#: del giro (`PASSI_DEL_GIRO`), che ogni passo mette al primo livello del
#: dizionario che restituisce e la riga del giro conserva.
CONTATORI_PIPELINE: tuple[tuple[str, ...], ...] = (
    ("passi_non_ok",),
    ("riavvio_dopo_crash",),
    ("saltato_per_lock",),
    ("scrape", "fonti_totali"),
    ("scrape", "fonti_processate"),
    ("scrape", "fonti_errors"),
    ("scrape", "fonti_in_errore"),
    ("preprocess", "processed_total"),
    ("preprocess", "errors"),
    ("enrich", "enriched_total"),
    ("enrich", "enriched_db_ok"),
    ("seo", "selected"),
    ("seo", "doppioni_oe"),
    ("seo", "payload_ok"),
    ("seo", "trattenuti"),
    ("seo", "trattenuti_senza_appiglio"),
    ("seo", "fusi_prima_della_pubblicazione"),
    ("seo", "fusioni_non_riuscite"),
) + tuple((passo, "copertura") for passo in PASSI_DEL_GIRO)
#: Lo step delle righe dell'import di IndicePA (`fonte_ufficiale.STEP_DOMINI`).
STEP_DOMINI = "domini"
#: Quante righe dell'import legge `misure_salute`.
RIGHE_IMPORT_INDICEPA = 3
#: I contatori dell'import che servono ai codici `indicepa_non_aggiornato` e
#: `indicepa_import_anomalo`.
CONTATORI_INDICEPA: tuple[tuple[str, ...], ...] = (
    ("indicepa_esito",), ("indicepa_at",), ("indicepa_modalita",),
    ("indicepa_righe_lette",), ("indicepa_righe_utili",), ("indicepa_ammessi",),
    ("indicepa_inseriti",), ("indicepa_esclusi",), ("indicepa_lotti_falliti",),
)
#: I contatori delle righe `step='monitor'` per il giro 2.
CONTATORI_MONITOR: tuple[tuple[str, ...], ...] = (
    ("classificazioni",),
    ("classificazioni_fallite",),
    ("eventi_non_applicati",),
    ("eventi_non_scritti",),
    # Codice A `prosa_non_riscritta` (§8): la prosa non riallineata alle date.
    ("prosa_non_riscritta",),
    # Codice `eventi_non_leggibili`: eventi applicati ma non resi leggibili.
    ("eventi_invisibili",),
)
#: Le colonne di `pipeline_run` lette insieme ai contatori mirati.
COLONNE_RIGA_RUN: tuple[str, ...] = (
    "id", "giro", "avviato_at", "concluso_at", "esito", "interrotto_per_tetto",
)


def _alias_contatore(percorso: Sequence[str]) -> str:
    """Alias PostgREST di un percorso: `("scrape", "fonti_errors")` → `c_scrape__fonti_errors`."""
    return "c_" + "__".join(percorso)


def _select_con_contatori(percorsi: Sequence[Sequence[str]]) -> str:
    """`select=` con le colonne di `COLONNE_RIGA_RUN` e un alias per percorso.

    Si usa `->` fino in fondo e non `->>`: PostgREST restituisce il valore
    JSON com'e' (numeri, liste, booleani), non il suo testo.
    """
    voci = list(COLONNE_RIGA_RUN)
    for percorso in percorsi:
        voci.append(f"{_alias_contatore(percorso)}:contatori->" + "->".join(percorso))
    return ",".join(voci)


def _contatori_mirati(
    riga: Mapping[str, Any],
    percorsi: Sequence[Sequence[str]],
) -> dict[str, Any]:
    """La riga con i contatori mirati rimessi dentro `contatori`, annidati.

    La forma e' quella del jsonb (`contatori.scrape.fonti_errors`), cosi' una
    regola di salute legge allo stesso modo questa riga e una riga intera. Un
    percorso che il DB restituisce `null` (chiave assente in quella riga) non
    compare: «assente» resta distinguibile da «zero».
    """
    alias = {_alias_contatore(p): tuple(p) for p in percorsi}
    uscita: dict[str, Any] = {k: v for k, v in riga.items() if k not in alias}
    contatori: dict[str, Any] = {}
    for nome, percorso in alias.items():
        valore = riga.get(nome)
        if valore is None:
            continue
        nodo = contatori
        for chiave in percorso[:-1]:
            nodo = nodo.setdefault(chiave, {})
        nodo[percorso[-1]] = valore
    uscita["contatori"] = contatori
    return uscita


def _conta(query: Any) -> int | None:
    """Il conteggio `count=exact` di una select gia' filtrata, senza scaricare righe.

    `None` se la risposta non porta il conteggio: una misura mancante, non uno zero.
    """
    conto = getattr(query.limit(1).execute(), "count", None)
    return int(conto) if isinstance(conto, int) and not isinstance(conto, bool) else None


# --- monitoraggio (migrazione 12, contratto `bandi-giro-2` §2.1 e §14) -------

#: La riga unica del riepilogo per il pannello. Scrive solo `sorveglia`.
TABELLA_RIEPILOGO = "monitoraggio_riepilogo"
#: Lo stato del job orario di pg_cron, letto con la service key.
RPC_JOB_ORARIO = "monitoraggio_job_orario"
#: L'unica riga ammessa da `CHECK (id = 1)`.
ID_RIEPILOGO = 1
#: Le colonne che `scrivi_riepilogo_monitoraggio` scrive. `aggiornato_at` non
#: c'e' di proposito: lo imposta il trigger con l'orologio del DB, ed e' su
#: quello che il pannello calcola il ritardo.
COLONNE_RIEPILOGO: tuple[str, ...] = (
    "id", "calcolato_at", "intervallo_ritardo", "versione", "riepilogo", "memoria",
)


def riepilogo_disponibile(*, strumento: Any | None = None) -> bool | None:
    """La tabella del riepilogo (migrazione 12) c'e'? Tre risposte:

    - `True`: c'e';
    - `False`: lo schema si legge e la tabella non c'e' (12 non applicata);
    - `None`: lo schema non si legge (DB o rete giu', chiave sbagliata), quindi
      non si sa.

    Serve a `sorveglia` per distinguere «niente da scrivere, la 12 non e'
    applicata» (exit 0) da «l'upsert e' fallito» o «il DB non risponde» (exit
    1): per `scrivi_riepilogo_monitoraggio` sono tutti un `False`, e un DB giu'
    non deve sembrare una migrazione mancante.
    """
    strumento = _controllo(strumento)
    if not strumento.schema_leggibile():
        return None
    return bool(strumento.tabella_esiste(TABELLA_RIEPILOGO))


def job_orario(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any] | None:
    """Lo stato del job orario delle transizioni (RPC di sola lettura della 12).

    `None` se la funzione non c'e' (12 non applicata), se la chiamata fallisce
    o se la risposta non e' un oggetto: la misura manca, e `salute` lo dice.
    """
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_JOB_ORARIO):
        logger.info("[db] RPC {} assente: migrazione 12 non applicata", RPC_JOB_ORARIO)
        return None
    try:
        # In GET: la funzione legge e basta, e dal Mac (`salute`, `sorveglia
        # --dry-run`) si fanno solo GET (§1).
        risposta = _client(client).rpc(RPC_JOB_ORARIO, {}, get=True).execute()
    except Exception as e:
        logger.warning("[db] {} fallita: {}", RPC_JOB_ORARIO, e)
        return None
    dati = getattr(risposta, "data", None)
    if isinstance(dati, list) and len(dati) == 1:
        dati = dati[0]
    return dict(dati) if isinstance(dati, Mapping) else None


def leggi_memoria_riepilogo(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any] | None:
    """La `memoria` di `sorveglia` salvata nella riga del riepilogo.

    `{}` se la riga non c'e' ancora (primo giro); `None` se la tabella manca o
    la lettura fallisce. Non solleva: senza memoria `sorveglia` riparte da
    adesso, non si ferma.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_RIEPILOGO):
        return None
    try:
        righe = list((
            _client(client).table(TABELLA_RIEPILOGO).select("memoria")
            .eq("id", ID_RIEPILOGO).limit(1).execute()
        ).data or [])
    except Exception as e:
        logger.warning("[db] lettura della memoria del riepilogo fallita: {}", e)
        return None
    if not righe:
        return {}
    memoria = righe[0].get("memoria")
    return dict(memoria) if isinstance(memoria, Mapping) else {}


def scrivi_riepilogo_monitoraggio(
    riga: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> bool:
    """Upsert della riga unica (`id=1`) del riepilogo. `True` solo se scritta.

    Si scrivono solo le chiavi di `COLONNE_RIEPILOGO` che lo schema espone;
    `id` e' sempre 1, qualunque cosa arrivi. Senza la tabella (12 non
    applicata) un warning e `False`, senza richieste. Non solleva.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_RIEPILOGO):
        logger.warning("[db] {} assente: migrazione 12 non applicata, riepilogo non scritto",
                       TABELLA_RIEPILOGO)
        return False
    presenti = strumento.colonne(TABELLA_RIEPILOGO)
    pulita = {
        k: v for k, v in riga.items()
        if k in COLONNE_RIEPILOGO and (not presenti or k in presenti)
    }
    pulita["id"] = ID_RIEPILOGO
    try:
        (_client(client).table(TABELLA_RIEPILOGO)
         .upsert(pulita, on_conflict="id").execute())
    except Exception as e:
        logger.warning("[db] upsert di {} fallito: {}", TABELLA_RIEPILOGO, e)
        return False
    return True


# --- verifica dello stato (contratto `bandi-giro-2` §14 e §19.13) ----------
#
# Le letture e le scritture del passo `verifica-stato`, della fase ingresso,
# del segnale dell'aggregatore e della lista bianca letta dal DB. Stessa regola
# delle sezioni precedenti per lo schema: una colonna o una tabella che la 13
# non ha ancora portato vale «niente» (`{}`, `[]`, `False`) con un log.
#
# Le **letture** che il passo usa per decidere (`select_da_verificare`,
# `select_letture_stato`, `select_enriched_da_leggere`) invece sollevano su un
# errore di rete: una lettura vuota vorrebbe dire «mai letto», e il passo
# riscriverebbe `lettura_stato` perdendo la `storia` su cui si fonda la doppia
# lettura del gate G7e.

#: Le colonne della 13 su `bando_controllo`: le 12 di §2.2 e le 5 di §19.2.
COLONNE_LETTURA_STATO: tuple[str, ...] = (
    "stato_letto", "stato_letto_su", "stato_letto_at", "stato_letto_url",
    "stato_letto_citazione", "stato_letto_metodo",
    "lettura_stato", "lettura_stato_at", "prossima_lettura_at", "letture_stato_nulle",
    "previsto_entro", "termine_indicato",
    "esaminato_attivo_at", "termine_indicato_fonte",
    "segnale_aggregatore", "segnale_aggregatore_at", "trattenuto_dal",
)
#: Le colonne di `bando` che il passo legge per un candidato.
COLONNE_DA_VERIFICARE: tuple[str, ...] = (
    "id", "slug", "titolo", "titolo_raw", "descrizione_breve",
    "stato_bando", "stato_processing", "pubblicato",
    "data_apertura", "data_apertura_verificata", "ora_apertura",
    "data_scadenza", "ora_scadenza", "pubblicato_at", "created_at",
    # Per il passo (#76): G5 («mai sovrascrivere una colonna gia' verificata»,
    # §5.6) e la data di pubblicazione che `data_verificata` non ripete.
    "data_scadenza_verificata", "data_pubblicazione",
    "fonte_id", "link_bando", "bando_master_id",
    "fonte_ufficiale_url", "fonte_ufficiale_stato", "fonte_ufficiale_tipo",
    "fonte_ufficiale_host", "raw_data",
)
STATO_IN_APERTURA = "in apertura prossimamente"
STATO_APERTO = "aperto"
#: Le sole colonne di `bando` che la fase ingresso scrive (§19.4, §5.7), e
#: solo su righe non pubblicate. `data_scadenza_verificata` non c'e': la tocca
#: solo un evento (CHECK della 03).
COLONNE_INGRESSO_BANDO: tuple[str, ...] = ("data_scadenza", "ora_scadenza", "stato_bando")
#: L'unico stato che la fase ingresso puo' scrivere.
STATO_INGRESSO = "chiuso"
#: Le colonne di `dominio_ufficiale` che la lista bianca legge.
COLONNE_DOMINIO: tuple[str, ...] = (
    "id", "host", "tipo", "confidenza", "ente", "codice_ipa", "fonte_id",
    "origine", "attivo", "note",
)
COLONNE_SEGNALE: tuple[str, ...] = ("segnale_aggregatore", "segnale_aggregatore_at")


def _host_delle_fonti(
    fonte_ids: Iterable[Any],
    *,
    client: Any | None,
    strumento: Any,
) -> dict[Any, str | None]:
    """`{fonte_id: host di fonte.link}` per le fonti date."""
    if not strumento.ha("fonte", "link"):
        return {}
    from .dominio_ufficiale import dominio_di
    righe = _per_id(
        lambda blocco: _client(client).table("fonte").select("id,link").in_("id", blocco),
        sorted({f for f in fonte_ids if f is not None}, key=str),
    )
    return {r.get("id"): dominio_di(str(r.get("link") or "")) for r in righe}


def _con_host_fonte(
    righe: list[dict[str, Any]],
    *,
    client: Any | None,
    strumento: Any,
) -> list[dict[str, Any]]:
    """Le righe con `host_fonte`, l'host della fonte di scraping (§5.3)."""
    host = _host_delle_fonti((r.get("fonte_id") for r in righe), client=client, strumento=strumento)
    for riga in righe:
        riga["host_fonte"] = host.get(riga.get("fonte_id"))
    return righe


def select_da_verificare(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I candidati del passo verifica-stato (§5.2), con `host_fonte`.

    Pubblicati non fusi, «in apertura» oppure «aperto» senza `data_scadenza`:
    e' un soprainsieme esatto dei candidati, perche' lo `stato_effettivo` (che
    puo' portare un «in apertura» ad «aperto») lo calcola il passo. Nessun
    filtro su `fonte_ufficiale_stato`. `[]` senza la tabella; un errore di
    rete si solleva.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_DA_VERIFICARE, strumento)

    def _costruisci() -> Any:
        query = _client(client).table("bando").select(colonne)
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", True)
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        return query.or_(
            f'stato_bando.eq."{STATO_IN_APERTURA}",'
            f"and(stato_bando.eq.{STATO_APERTO},data_scadenza.is.null)"
        ).order("id")

    righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))
    return _con_host_fonte(righe, client=client, strumento=strumento)


def select_letture_stato(
    ids: Iterable[Any] | None = None,
    dal: Any = None,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[Any, dict[str, Any]]:
    """`{bando_id: riga}` delle letture di `bando_controllo` (§14).

    Con `ids` quelle righe; altrimenti quelle con `lettura_stato_at` dal
    momento `dal`, o tutte quelle lette almeno una volta. Le colonne sono
    `COLONNE_LETTURA_STATO` piu' `candidato_prioritario` (la pagina ii-c di
    §19.4). `{}` senza la 13; un errore di rete si solleva.
    """
    strumento = _controllo(strumento)
    if not strumento.ha(TABELLA_CONTROLLO, "lettura_stato"):
        return {}
    colonne = _colonne_disponibili(
        TABELLA_CONTROLLO,
        ("bando_id", *COLONNE_LETTURA_STATO, "candidato_prioritario"),
        strumento,
    )
    sb = _client(client)
    if ids is not None:
        righe = _per_id(
            lambda blocco: sb.table(TABELLA_CONTROLLO).select(colonne).in_("bando_id", blocco),
            list(ids), ordine="bando_id",
        )
    else:
        def _costruisci() -> Any:
            query = sb.table(TABELLA_CONTROLLO).select(colonne)
            if dal is not None:
                inizio = dal.isoformat() if isinstance(dal, datetime_cls) else str(dal)
                query = query.gte("lettura_stato_at", inizio)
            else:
                query = query.not_.is_("lettura_stato_at", "null")
            return query.order("bando_id")

        righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))
    return {r.get("bando_id"): r for r in righe if r.get("bando_id") is not None}


def aggiorna_lettura_stato(
    bando_id: Any,
    colonne: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> bool:
    """Upsert su `bando_controllo` delle sole colonne della 13 che lo schema ha.

    `False` se non resta niente da scrivere (13 non applicata) o se la
    scrittura fallisce (i CHECK della 13: lettura completa, termine con la sua
    fonte). Non solleva.
    """
    strumento = _controllo(strumento)
    presenti = strumento.colonne(TABELLA_CONTROLLO)
    riga = {k: v for k, v in colonne.items() if k in COLONNE_LETTURA_STATO and k in presenti}
    scartate = sorted(set(colonne) - set(riga))
    if scartate:
        logger.info("[db] bando_controllo id={}: colonne non scritte {}", bando_id, scartate)
    if not riga:
        return False
    riga["bando_id"] = bando_id
    try:
        (_client(client).table(TABELLA_CONTROLLO)
         .upsert(riga, on_conflict="bando_id").execute())
    except Exception as e:
        logger.warning("[db] lettura dello stato di {} non scritta: {}", bando_id, e)
        return False
    return True


def select_enriched_da_leggere(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I candidati della fase ingresso (§19.4, §5.10), con `host_fonte`.

    Righe `enriched` non pubblicate: «aperto» senza `data_scadenza`, oppure
    schede OE con `status` '2'. Due letture unite per id invece di un `or=`
    con un percorso JSON dentro. Si leggono tutti: dal giro 3 il passo non ha
    un tetto di numero, solo il tempo (`VERIFICA_STATO_TETTO_S`) con rotazione.
    `[]` senza la tabella; un errore di rete si solleva.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_DA_VERIFICARE, strumento)
    sb = _client(client)

    def _base() -> Any:
        query = sb.table("bando").select(colonne).eq("stato_processing", "enriched")
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", False)
        return query

    aperti = _scorri(lambda quanto, salto: _pagina(
        _base().eq("stato_bando", STATO_APERTO).is_("data_scadenza", "null").order("id"),
        quanto, salto))
    in_uscita = []
    if strumento.ha("bando", "raw_data"):
        in_uscita = _scorri(lambda quanto, salto: _pagina(
            _base().eq("raw_data->>status", "2").order("id"), quanto, salto))
    per_id = {r.get("id"): r for r in (*aperti, *in_uscita) if r.get("id") is not None}
    righe = [per_id[i] for i in sorted(per_id, key=lambda i: (not isinstance(i, int), str(i)
                                                               if not isinstance(i, int) else i))]
    return _con_host_fonte(righe, client=client, strumento=strumento)


def aggiorna_ingresso(
    bando_id: Any,
    colonne_bando: Mapping[str, Any] | None,
    colonne_controllo: Mapping[str, Any] | None,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Le scritture della fase ingresso su una riga **non pubblicata** (§19.4).

    `{bando, controllo, rifiutato}`. Una riga pubblicata (o `completed`) si
    rifiuta senza scrivere niente: il contratto DB vuole che un pubblicato
    cambi solo per evento. Su `bando` passano solo `COLONNE_INGRESSO_BANDO`, e
    `stato_bando` solo se vale 'chiuso'. L'UPDATE porta anche il filtro
    `pubblicato=false`: se la riga viene pubblicata fra la lettura e la
    scrittura, non tocca niente. Non solleva.
    """
    esito: dict[str, Any] = {"bando": False, "controllo": False, "rifiutato": None}
    strumento = _controllo(strumento)
    sb = _client(client)
    try:
        lette = list((
            sb.table("bando").select("id,pubblicato,stato_processing")
            .eq("id", bando_id).limit(1).execute()
        ).data or [])
    except Exception as e:
        logger.warning("[db] ingresso {}: riga non letta, niente scritture: {}", bando_id, e)
        esito["rifiutato"] = "lettura_fallita"
        return esito
    if not lette:
        esito["rifiutato"] = "assente"
        return esito
    if lette[0].get("pubblicato") is True or lette[0].get("stato_processing") == "completed":
        logger.warning("[db] ingresso {}: riga pubblicata, nessuna scrittura", bando_id)
        esito["rifiutato"] = "pubblicato"
        return esito

    presenti = strumento.colonne("bando")
    payload: dict[str, Any] = {}
    scartate: list[str] = []
    for chiave, valore in (colonne_bando or {}).items():
        ammessa = chiave in COLONNE_INGRESSO_BANDO and (not presenti or chiave in presenti)
        if chiave == "stato_bando" and valore != STATO_INGRESSO:
            ammessa = False
        if ammessa:
            payload[chiave] = valore
        else:
            scartate.append(chiave)
    if scartate:
        logger.info("[db] ingresso {}: colonne di bando non scritte {}", bando_id, sorted(scartate))
    if payload:
        assicura_payload_bando(payload)
        try:
            scritte = (
                sb.table("bando").update(payload)
                .eq("id", bando_id).eq("pubblicato", False).execute()
            ).data or []
        except Exception as e:
            logger.warning("[db] ingresso {}: update di bando fallito: {}", bando_id, e)
            scritte = None
        if scritte == []:
            # Nessuna riga toccata: pubblicata nel frattempo.
            esito["rifiutato"] = "pubblicato"
            return esito
        esito["bando"] = bool(scritte)
    if colonne_controllo:
        esito["controllo"] = aggiorna_lettura_stato(
            bando_id, colonne_controllo, client=client, strumento=strumento)
    return esito


def select_domini_ufficiali(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Le righe di `dominio_ufficiale` per la lista bianca (§19.8), per id.

    `[]` senza la tabella o se la lettura fallisce (con un warning): chi la
    usa ripiega sul seed compilato, che e' il comportamento di prima.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_DOMINIO):
        return []
    colonne = _colonne_disponibili(TABELLA_DOMINIO, COLONNE_DOMINIO, strumento)
    try:
        return _scorri(lambda quanto, salto: _pagina(
            _client(client).table(TABELLA_DOMINIO).select(colonne).order("id"),
            quanto, salto))
    except Exception as e:
        logger.warning("[db] {} non letta, si usa il seed: {}", TABELLA_DOMINIO, e)
        return []


def select_host_dei_link(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[str]:
    """Gli host dei link dei pubblicati, ordinati: `link_bando`,
    `fonte_ufficiale_url` e gli `url` di `bando_link`.

    Serve al report dell'import di IndicePA: quanti host dei nostri link sono
    verificanti prima e dopo. Le righe di `bando_link` non sono un dettaglio:
    il 30/09 i 51 host che l'import rendeva verificanti venivano tutti da li'
    (misure-giro-2-percorso-a.md, M10). `[]` se la lettura fallisce, con un
    warning.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    from .dominio_ufficiale import dominio_di
    colonne = _colonne_disponibili("bando", ("id", "link_bando", "fonte_ufficiale_url"), strumento)

    def _costruisci() -> Any:
        query = _client(client).table("bando").select(colonne)
        if strumento.ha("bando", "pubblicato"):
            query = query.eq("pubblicato", True)
        return query.order("id")

    try:
        righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))
        collegati: list[dict[str, Any]] = []
        if strumento.ha(TABELLA_LINK, "url"):
            collegati = _per_id(
                lambda blocco: _client(client).table(TABELLA_LINK)
                .select("id,bando_id,url").in_("bando_id", blocco),
                [r.get("id") for r in righe], ordine="id",
            )
    except Exception as e:
        logger.warning("[db] host dei link non letti: {}", e)
        return []
    host = {
        dominio_di(str(riga.get(campo) or ""))
        for riga in righe for campo in ("link_bando", "fonte_ufficiale_url")
        if riga.get(campo)
    }
    host.update(dominio_di(str(riga.get("url") or "")) for riga in collegati if riga.get("url"))
    return sorted(h for h in host if h)


def aggiorna_segnale_aggregatore(
    righe: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> int:
    """Upsert del segnale dell'aggregatore su `bando_controllo` (§19.7). Righe scritte.

    Ogni riga e' `{bando_id, segnale_aggregatore, segnale_aggregatore_at}`; un
    `None` azzera (la riga e' ricomparsa pulita nel listing). Si scrivono solo
    quelle tre chiavi, a blocchi. `0` senza le colonne della 13. Non solleva.
    """
    strumento = _controllo(strumento)
    if not all(strumento.ha(TABELLA_CONTROLLO, c) for c in COLONNE_SEGNALE):
        logger.info("[db] segnale dell'aggregatore non scritto: colonne della 13 assenti")
        return 0
    pulite = [
        {"bando_id": r.get("bando_id"), **{c: r.get(c) for c in COLONNE_SEGNALE}}
        for r in righe if r.get("bando_id") is not None
    ]
    scritte = 0
    for blocco in _a_blocchi(pulite):
        try:
            (_client(client).table(TABELLA_CONTROLLO)
             .upsert(blocco, on_conflict="bando_id").execute())
        except Exception as e:
            logger.warning("[db] segnale dell'aggregatore: blocco di {} non scritto: {}",
                           len(blocco), e)
            continue
        scritte += len(blocco)
    return scritte


def inserisci_domini_nuovi(
    righe: Sequence[Mapping[str, Any]],
    lotto: int = 500,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Inserisce in `dominio_ufficiale` i soli host che non ci sono (§19.8).

    Una riga esistente non si modifica mai e niente si cancella: si leggono gli
    host presenti, si tengono gli assenti (una volta sola ciascuno) e si
    scrivono a lotti con `ON CONFLICT (host) DO NOTHING`
    (`upsert(ignore_duplicates=True)`), cosi' anche una riga comparsa nel
    frattempo resta com'e'. Se la lettura degli host presenti fallisce non si
    scrive niente. Non solleva.
    """
    esito: dict[str, Any] = {
        "lette": len(righe), "gia_presenti": 0, "scartate": 0,
        "inserite": 0, "lotti_falliti": 0, "errore": None,
    }
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste(TABELLA_DOMINIO):
        esito["errore"] = "tabella_assente"
        return esito
    presenti_colonne = strumento.colonne(TABELLA_DOMINIO)
    sb = _client(client)
    try:
        esistenti = {
            str(r.get("host") or "").strip().lower()
            for r in _scorri(lambda quanto, salto: _pagina(
                sb.table(TABELLA_DOMINIO).select("id,host").order("id"), quanto, salto))
        }
    except Exception as e:
        logger.warning("[db] {}: host presenti non letti, nessuna scrittura: {}", TABELLA_DOMINIO, e)
        esito["errore"] = "lettura_fallita"
        return esito

    nuove: dict[str, dict[str, Any]] = {}
    for riga in righe:
        host = str(riga.get("host") or "").strip().lower()
        if not host:
            esito["scartate"] += 1
            continue
        if host in esistenti:
            esito["gia_presenti"] += 1
            continue
        if host in nuove:
            continue
        pulita = {
            k: v for k, v in riga.items()
            if k != "id" and (not presenti_colonne or k in presenti_colonne)
        }
        pulita["host"] = host
        nuove[host] = pulita

    # Lotti con le stesse chiavi: postgrest-py manda `columns=` con l'unione
    # delle chiavi del lotto, e PostgREST scrive NULL (non il DEFAULT) nelle
    # chiavi che mancano a una riga. Righe con chiavi diverse vanno in lotti
    # diversi.
    per_chiavi: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for riga in nuove.values():
        per_chiavi.setdefault(tuple(sorted(riga)), []).append(riga)
    passo = max(1, int(lotto))
    blocchi = [
        gruppo[inizio:inizio + passo]
        for gruppo in per_chiavi.values()
        for inizio in range(0, len(gruppo), passo)
    ]
    for blocco in blocchi:
        try:
            risposta = (
                sb.table(TABELLA_DOMINIO)
                .upsert(blocco, on_conflict="host", ignore_duplicates=True).execute()
            )
        except Exception as e:
            logger.warning("[db] {}: lotto di {} host non scritto: {}",
                           TABELLA_DOMINIO, len(blocco), e)
            esito["lotti_falliti"] += 1
            continue
        esito["inserite"] += len(getattr(risposta, "data", None) or [])
    return esito


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


#: Le controparti del controllo dei doppioni OE (contratto di ottobre, §6):
#: quanto serve ai due criteri e a escludere fusi, non pubblicati e fonti OE.
COLONNE_DOPPIONI_OE: tuple[str, ...] = (
    "id", "fonte_id", "fonte_ufficiale_url", "ente_erogatore", "importo_totale_eur",
    "data_scadenza", "bando_master_id", "pubblicato",
)


def select_pubblicati_per_doppioni_oe(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati non fusi con cui confrontare i bandi OE prima della SEO.

    Si scorrono tutti (sono piu' di 2 000, PostgREST ne darebbe 1 000). Un
    errore non si nasconde: lo prende il chiamante, che salta il controllo e
    lascia girare la SEO come prima.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_DOPPIONI_OE, strumento)

    def _costruisci() -> Any:
        query = _pubblicati(_client(client).table("bando").select(colonne), strumento)
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        return query.order("id")

    return _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))


def rifiuta_doppione(bando_id: Any, motivo: str, *, client: Any | None = None) -> bool:
    """`rejected` con il motivo del §6, solo se il bando e' ancora `enriched`.

    Il filtro su `enriched` fa si' che non si tocchi mai un bando pubblicato
    o gia' lavorato da un altro giro; in quel caso la risposta e' vuota e il
    valore di ritorno e' False. Per annullare: vedi `gemelli`, sezione dei
    doppioni ObiettivoEuropa.
    """
    risposta = (
        _client(client).table("bando")
        .update({"stato_processing": "rejected", "rejection_reason": motivo})
        .eq("id", bando_id).eq("stato_processing", "enriched").execute()
    )
    return bool(getattr(risposta, "data", None))


#: Le colonne di `seo-rigenera` oltre a quelle dello step SEO: i due testi da
#: confrontare e cio' che serve a rifiutare i non pubblicati.
COLONNE_SEO_RIGENERA: tuple[str, ...] = ("slug", "contenuto", "descrizione_breve")

#: Colonne nuove (migrazioni 01 e 03): si chiedono solo se lo schema le espone.
COLONNE_SEO_RIGENERA_OPZIONALI: tuple[str, ...] = (
    "fonte_ufficiale_url", "fonte_ufficiale_stato", "pubblicato", "bando_master_id",
    # Il trigger della 01 lo avanza a ogni cambio di contenuto o descrizione:
    # l'UPDATE di `aggiorna_testo_seo` lo usa per non scrivere su un testo
    # cambiato fra il controllo e la scrittura.
    "ultimo_cambiamento_at",
)


def select_bandi_per_rigenera_seo(
    bando_ids: Sequence[Any] = (),
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """Le righe di `seo-rigenera`, con le colonne dello step SEO piu' i testi.

    Con `bando_ids` si leggono quegli id **senza filtro di pubblicazione**: e'
    il comando a rifiutare i non pubblicati e i fusi, e per dirlo all'operatore
    deve vederli. Senza id (`--solo-controllo` sull'intero archivio) si leggono
    i pubblicati non fusi, scorsi a pagine: sono piu' di 2 000 e PostgREST ne
    restituirebbe 1 000 senza dirlo.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando"):
        return []
    colonne = _colonne_con_opzionali(
        "bando", COLONNE_SEO_BASE + COLONNE_SEO_RIGENERA,
        COLONNE_SEO_RIGENERA_OPZIONALI, strumento,
    )
    if bando_ids:
        return _per_id(
            lambda blocco: _client(client).table("bando").select(colonne).in_("id", blocco),
            list(dict.fromkeys(bando_ids)),
        )

    def _costruisci() -> Any:
        query = _pubblicati(_client(client).table("bando").select(colonne), strumento)
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        return query.order("id")

    return _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))


def select_junction_per_bandi(
    tabella: str,
    colonna: str,
    bando_ids: Sequence[Any],
    *,
    client: Any | None = None,
) -> dict[Any, list[Any]]:
    """`{bando_id: [id del catalogo]}` di una junction, a blocchi di id.

    E' la lettura in blocco di `_select_junction_ids`: per l'intero archivio
    quella costerebbe una GET per bando e per tabella.

    L'ordine e' `bando_id, <colonna>`, univoco sulla coppia che fa da chiave
    della junction (come `src/lib/corpus.ts`): con il solo `bando_id` le pagine
    oltre le 1 000 righe potevano sovrapporsi o saltare righe (§1). Non `id`:
    le junction non sono tenute ad averlo. Le due `.order()` di postgrest si
    sommano in `order=bando_id.asc,<colonna>.asc`.
    """
    righe = _per_id(
        lambda blocco: _client(client).table(tabella).select(f"bando_id,{colonna}")
        .in_("bando_id", blocco).order("bando_id"),
        list(dict.fromkeys(bando_ids)),
        ordine=colonna,
    )
    esito: dict[Any, list[Any]] = {}
    for riga in righe:
        if riga.get(colonna) is not None:
            esito.setdefault(riga.get("bando_id"), []).append(riga[colonna])
    return esito


#: Le sole colonne che `seo-rigenera --attivo` puo' scrivere (contratto di
#: ottobre, §7). Slug, titolo, date, importi, stato e junction restano fuori.
CAMPI_TESTO_SEO: frozenset[str] = frozenset({"contenuto", "descrizione_breve"})


def aggiorna_testo_seo(
    bando_id: Any,
    campi: Mapping[str, Any],
    *,
    client: Any | None = None,
    ultimo_cambiamento_at: Any | None = None,
) -> bool:
    """UPDATE dei soli testi di una scheda pubblicata. True se la riga c'era.

    Una chiave fuori da `CAMPI_TESTO_SEO` e' un errore di programmazione e ferma
    il comando (`PayloadBandoVietato`, un AssertionError), come il chokepoint
    del resolver. Il filtro su `stato_processing='completed'` fa si' che una
    riga uscita dai pubblicati fra la lettura e la scrittura non venga toccata:
    in quel caso la risposta e' vuota e il valore di ritorno e' False.

    `ultimo_cambiamento_at`, se dato, e' quello letto al momento del controllo
    dell'hash: l'UPDATE lo pretende uguale, quindi un testo riscritto nel
    frattempo da un altro comando (`rigenera`, `monitor --attivo` da CLI, che
    non prendono il lock `bandi_pipeline`) non viene sovrascritto. Il trigger
    della migrazione 01 lo avanza a ogni cambio di `contenuto` e descrizione.
    """
    estranee = sorted(set(campi) - CAMPI_TESTO_SEO)
    if estranee or not campi:
        raise PayloadBandoVietato(
            f"seo-rigenera scrive solo {sorted(CAMPI_TESTO_SEO)}: ricevuto {sorted(campi)}"
        )
    query = (
        _client(client).table("bando").update(dict(campi))
        .eq("id", bando_id).eq("stato_processing", "completed")
    )
    if ultimo_cambiamento_at is not None:
        query = query.eq("ultimo_cambiamento_at", ultimo_cambiamento_at)
    return bool(getattr(query.execute(), "data", None))


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


def rendi_evento_leggibile(
    evento_id: Any,
    *,
    in_aggiornamenti: bool = True,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """`leggibile=true` (+ `in_aggiornamenti`) su un evento gia' applicato.

    E' il passo che mancava all'attivazione per tipo. `bando_applica_evento`
    riversa `valore_dopo` nelle colonne di `bando` e marca l'evento
    `applicato`, ma **non tocca `leggibile`**: il trigger del cursore scatta su
    `UPDATE OF leggibile` quando diventa vero, quindi finche' nessuno lo scrive
    l'evento resta senza cursore, la RLS di anon lo nasconde e il box
    «Aggiornamenti» non lo mostra. Misurato il 25/09/2026: `applica-eventi`
    riferiva `applicati: 5` e le cinque righe erano `leggibile=false,
    cursore=NULL`, cioe' invisibili — il comando dichiarava un lavoro che a
    metà non aveva fatto.

    Le due colonne si scrivono **in un solo UPDATE** (§16.3 punto 3) e sono
    fra le poche che `z_evento_immutabile` ammette di cambiare.
    """
    payload = {"leggibile": True, "in_aggiornamenti": bool(in_aggiornamenti)}
    return _controllo(strumento).aggiorna(TABELLA_EVENTO, evento_id, payload)


def transizione_non_ammessa(errore: BaseException) -> bool:
    """Vero se l'errore e' il 23514 della lista bianca delle transizioni.

    Solo quello: ogni altro 23514 (un CHECK violato da un nostro difetto) resta
    un «non tentato», perche' annotarlo come rifiuto escluderebbe per sempre un
    evento che nessuno ha giudicato.
    """
    codice = str(getattr(errore, "code", "") or "")
    messaggio = str(getattr(errore, "message", "") or errore)
    return codice == "23514" and "transizione non ammessa" in messaggio


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
        if transizione_non_ammessa(e):
            # La RPC ha guardato l'evento e l'ha respinto: e' un giudizio.
            # Contato come «non tentato», l'evento tornava in coda a ogni
            # lancio e consumava il blocco per sempre (28/09/2026).
            logger.info("[db] {}: evento {} respinto dalla lista bianca",
                        RPC_APPLICA_EVENTO, evento_id)
            return ESITO_RIFIUTATO
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


def capacita_eventi(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, bool]:
    """Che cosa sa fare il DB con gli eventi, dal marcatore della migrazione 11.

    `CAPACITA_TRADUZIONE`: il corpo vivo di `bando_applica_evento` traduce
    `stato_proposto` in `stato_bando`. `CAPACITA_STATI_CINQUE`: il CHECK di
    `stato_bando` ammette `sospeso` e `revocato` (migrazione 06). Né il corpo
    di una funzione né un CHECK sono visibili via PostgREST: per questo passano
    da una RPC in sola lettura.

    Nel dubbio tutto falso: RPC assente (11 non applicata), chiamata fallita,
    risposta che non sia un oggetto con `true` letterali. Un falso qui fa solo
    aspettare un evento; un vero sbagliato lo brucerebbe per sempre.
    """
    esito = {CAPACITA_TRADUZIONE: False, CAPACITA_STATI_CINQUE: False}
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_CAPACITA_EVENTI):
        logger.info("[db] RPC {} assente: migrazione 11 non applicata", RPC_CAPACITA_EVENTI)
        return esito
    try:
        risposta = _client(client).rpc(RPC_CAPACITA_EVENTI, {}).execute()
    except Exception as e:
        logger.warning("[db] {} fallita: {}", RPC_CAPACITA_EVENTI, e)
        return esito
    dati = getattr(risposta, "data", None)
    if isinstance(dati, Mapping):
        for chiave in esito:
            esito[chiave] = dati.get(chiave) is True
    return esito


def capacita_sospensioni(
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> bool:
    """Vero solo se la migrazione 14 e' applicata (marcatore
    `bando_capacita_sospensioni()` → `true`), sullo stampo di `capacita_eventi`.

    Nel dubbio falso: RPC assente, chiamata fallita, risposta che non sia il
    booleano `true` letterale. PostgREST puo' incapsulare lo scalare in una
    lista o in un oggetto con il nome della funzione: si guarda dentro, ma
    vale solo `True`, mai `"true"` o `1`. Un falso tiene in ombra un evento
    (si applica al giro dopo la migrazione); un vero sbagliato manderebbe
    alla RPC transizioni che il trigger rifiuta (23514).
    """
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_CAPACITA_SOSPENSIONI):
        logger.info("[db] RPC {} assente: migrazione 14 non applicata",
                    RPC_CAPACITA_SOSPENSIONI)
        return False
    try:
        risposta = _client(client).rpc(RPC_CAPACITA_SOSPENSIONI, {}).execute()
    except Exception as e:
        logger.warning("[db] {} fallita: {}", RPC_CAPACITA_SOSPENSIONI, e)
        return False
    dati = getattr(risposta, "data", None)
    if isinstance(dati, list):
        dati = dati[0] if len(dati) == 1 else None
    if isinstance(dati, Mapping):
        dati = dati.get(RPC_CAPACITA_SOSPENSIONI) if len(dati) == 1 else None
    return dati is True


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


# ---------------------------------------------------------------------------
# Rielaborazione dei pubblicati (giro 3, contratto `bandi-giro-3` §9)
# ---------------------------------------------------------------------------
#
# Letture e scritture di `app/rielabora_fonte.py`. Nessuna di queste funzioni
# scrive `stato_processing`, `stato_bando`, `slug`, `titolo` o una data: le
# date passano da un evento (`registra_evento_rpc`), la prosa da `rigenera`.

#: Il prefisso del marcatore su `bando_link.impronta_contenuto` della riga
#: della fonte: `rielab:v1:<YYYY-MM-DD>:<sha256 del testo letto>`.
MARCATORE_RIELABORAZIONE = "rielab:v1:"
#: Un bando rimasto incompleto (§18.3) porta `rielab:v1:incompleto:<n>`, con
#: `n` i tentativi falliti: resta in coda, e al terzo si marca come fatto con
#: il motivo (decisione del lead sui P2 di #160).
MARCATORE_INCOMPLETO = MARCATORE_RIELABORAZIONE + "incompleto:"


def da_rielaborare(marcatore: Any) -> bool:
    """Il bando e' ancora da rielaborare? Nessun marcatore, uno d'altro tipo,
    o un `rielab:v1:incompleto:<n>`."""
    testo = str(marcatore or "")
    return not testo.startswith(MARCATORE_RIELABORAZIONE) or testo.startswith(MARCATORE_INCOMPLETO)

#: Le colonne di `bando` che la rielaborazione legge: quelle che servono a
#: preprocess ed enrich, le date con la loro verifica, lo stato, la prosa, le
#: tre FK e la fonte ufficiale.
COLONNE_RIELABORAZIONE: tuple[str, ...] = (
    "id", "slug", "titolo", "titolo_raw", "descrizione_raw", "link_bando", "raw_data",
    "tipo_link", "fonte_id", "contenuto", "descrizione_breve", "stato_bando",
    "data_pubblicazione", "data_apertura", "data_scadenza",
    "data_apertura_verificata", "data_scadenza_verificata",
    "tipologia_bando_id", "modalita_erogazione_id", "programma_id",
    "fonte_ufficiale_url", "fonte_ufficiale_stato", "fonte_ufficiale_link_id",
)

#: Le tre FK che la rielaborazione puo' aggiornare (UPDATE delle sole tre).
COLONNE_FK_CLASSIFICAZIONE: tuple[str, ...] = (
    "tipologia_bando_id", "modalita_erogazione_id", "programma_id",
)


def select_da_rielaborare(
    *,
    ids: Sequence[Any] | None = None,
    client: Any | None = None,
    strumento: Any | None = None,
) -> list[dict[str, Any]]:
    """I pubblicati da rielaborare (§9), in ordine di id.

    Pubblicati, non fusi, con fonte `trovata` e la riga della fonte in
    `bando_link` (`fonte_ufficiale_link_id`) il cui `impronta_contenuto` e'
    NULL, non e' un marcatore `rielab:v1:` o e' quello di un tentativo rimasto
    incompleto (`rielab:v1:incompleto:<n>`). Il marcatore si legge per id dalla
    riga della fonte e si mette in `_marcatore`. Con `ids` (lancio a mano) il
    marcatore non filtra. `[]` se lo schema non ha ancora le colonne o se la
    lettura fallisce (con un log): senza candidati il passo non fa niente.
    """
    strumento = _controllo(strumento)
    if not strumento.tabella_esiste("bando") or not strumento.ha("bando", "fonte_ufficiale_link_id"):
        return []
    colonne = _colonne_disponibili("bando", COLONNE_RIELABORAZIONE, strumento)

    def _costruisci() -> Any:
        query = _pubblicati(_client(client).table("bando").select(colonne), strumento)
        query = query.eq("fonte_ufficiale_stato", "trovata").not_.is_(
            "fonte_ufficiale_link_id", "null")
        if strumento.ha("bando", "bando_master_id"):
            query = query.is_("bando_master_id", "null")
        if ids:
            query = query.in_("id", list(ids))
        return query.order("id")

    try:
        righe = _scorri(lambda quanto, salto: _pagina(_costruisci(), quanto, salto))
        link_ids = [r.get("fonte_ufficiale_link_id") for r in righe]
        marcatori = {
            r.get("id"): r.get("impronta_contenuto") for r in _per_id(
                lambda blocco: _client(client).table(TABELLA_LINK)
                .select("id,impronta_contenuto").in_("id", blocco),
                link_ids,
            )
        }
    except Exception as e:
        logger.warning("[db] select_da_rielaborare fallita: {}", e)
        return []
    for riga in righe:
        riga["_marcatore"] = marcatori.get(riga.get("fonte_ufficiale_link_id"))
    if ids:
        return righe
    return [r for r in righe if da_rielaborare(r.get("_marcatore"))]


def select_junction(
    bando_ids: Sequence[Any],
    *,
    client: Any | None = None,
) -> dict[Any, dict[str, list[int]]]:
    """`{bando_id: {dimensione: [id, ...]}}` per le quattro junction, a blocchi
    di id e scorse a pagine (ordine `bando_id` piu' la FK: unico)."""
    esito: dict[Any, dict[str, list[int]]] = {
        i: {dimensione: [] for dimensione in _JUNCTION_TABLES} for i in bando_ids
    }
    for dimensione, (tabella, fk) in _JUNCTION_TABLES.items():
        for blocco in _a_blocchi(list(bando_ids)):
            righe = _scorri(lambda quanto, salto, _b=blocco, _t=tabella, _f=fk: _pagina(
                _client(client).table(_t).select(f"bando_id,{_f}").in_("bando_id", _b)
                .order("bando_id").order(_f), quanto, salto))
            for riga in righe:
                valore = riga.get(fk)
                if valore is not None and riga.get("bando_id") in esito:
                    esito[riga["bando_id"]][dimensione].append(int(valore))
    for voce in esito.values():
        for dimensione in voce:
            voce[dimensione] = sorted(set(voce[dimensione]))
    return esito


def allinea_junction(
    bando_id: Any,
    dimensione: str,
    ids: Sequence[Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Porta una junction del bando agli `ids` (§9). Prima inserisce i nuovi,
    poi toglie gli usciti: un errore a meta' lascia piu' voci, mai meno.

    **Non svuota mai** una dimensione: con `ids` vuoti non si tocca niente
    (una chiamata dell'enrich fallita o «nessuna voce» non sono una prova che
    il bando non abbia regioni). Ritorna `{cambiato, prima, dopo, inseriti,
    tolti}` oppure `{cambiato: False, errore}`: il chiamante registra prima e
    dopo, cosi' si torna indietro con SQL.
    """
    if dimensione not in _JUNCTION_TABLES:
        raise ValueError(f"dimensione sconosciuta: {dimensione!r}")
    tabella, fk = _JUNCTION_TABLES[dimensione]
    nuovi = sorted({int(i) for i in ids if i is not None})
    if not nuovi:
        return {"cambiato": False, "motivo": "nessuna voce: dimensione invariata"}
    try:
        prima = sorted({
            int(r[fk]) for r in (_client(client).table(tabella).select(fk)
                                 .eq("bando_id", bando_id).execute().data or [])
            if r.get(fk) is not None
        })
    except Exception as e:
        logger.warning("[db] lettura di {} per il bando {} fallita: {}", tabella, bando_id, e)
        return {"cambiato": False, "errore": str(e)}
    da_inserire = [i for i in nuovi if i not in prima]
    da_togliere = [i for i in prima if i not in nuovi]
    if not da_inserire and not da_togliere:
        return {"cambiato": False, "prima": prima, "dopo": prima, "inseriti": [], "tolti": []}
    inseriti: list[int] = []
    try:
        if da_inserire:
            _client(client).table(tabella).insert(
                [{"bando_id": bando_id, fk: i} for i in da_inserire]).execute()
            inseriti = list(da_inserire)
        if da_togliere:
            (_client(client).table(tabella).delete()
             .eq("bando_id", bando_id).in_(fk, da_togliere).execute())
    except Exception as e:
        logger.warning("[db] allineamento di {} per il bando {} fallito: {}", tabella, bando_id, e)
        # A meta' (INSERT riuscito, DELETE fallito) il cambio c'e' stato: lo si
        # restituisce com'e', cosi' il chiamante lo registra e lo si puo'
        # togliere con SQL (revisione #146, P2).
        if inseriti:
            return {"cambiato": True, "parziale": True, "errore": str(e), "prima": prima,
                    "dopo": sorted(set(prima) | set(inseriti)), "inseriti": inseriti, "tolti": []}
        return {"cambiato": False, "errore": str(e), "prima": prima}
    return {"cambiato": True, "prima": prima, "dopo": nuovi,
            "inseriti": da_inserire, "tolti": da_togliere}


def aggiorna_fk_bando(
    bando_id: Any,
    payload: Mapping[str, Any],
    *,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """UPDATE delle sole tre FK di classificazione di un pubblicato (§9).
    Qualunque altra chiave e' un errore di chi chiama."""
    estranee = sorted(k for k in payload if k not in COLONNE_FK_CLASSIFICAZIONE)
    if estranee:
        raise PayloadBandoVietato(f"la rielaborazione scrive solo le tre FK: {estranee}")
    if not payload:
        return {"scritto": False, "motivo": "payload vuoto"}
    return _controllo(strumento).aggiorna("bando", bando_id, dict(payload))


#: L'unica colonna che `segna_cambiamento_pubblico` scrive (§20.1).
COLONNE_CAMBIAMENTO_PUBBLICO: tuple[str, ...] = ("ultimo_cambiamento_at",)


def segna_cambiamento_pubblico(
    bando_id: Any,
    *,
    adesso: Any = None,
    payload: Mapping[str, Any] | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """`ultimo_cambiamento_at = adesso` su un pubblicato, e nient'altro (§20.1).

    Il trigger `bando_cambiamento_pubblico` (migrazione 01) muove la colonna
    solo quando cambiano colonne di `bando`; le junction (regioni, settori,
    beneficiari, codici ATECO) sono altre tabelle, e senza questo UPDATE l'API
    (`updated_since`), il `lastmod` delle sitemap e BandoFit non vedrebbero i
    cambi della rielaborazione. Il trigger lascia stare un valore scritto
    direttamente. `payload` esiste solo per la guardia: qualunque chiave che
    non sia la colonna e' un errore di chi chiama, come in `aggiorna_fk_bando`.
    """
    from datetime import datetime, timezone
    momento = adesso if isinstance(adesso, datetime_cls) else datetime.now(tz=timezone.utc)
    dati = dict(payload) if payload is not None else {"ultimo_cambiamento_at": momento.isoformat()}
    estranee = sorted(k for k in dati if k not in COLONNE_CAMBIAMENTO_PUBBLICO)
    if estranee or not dati:
        raise PayloadBandoVietato(
            f"segna_cambiamento_pubblico scrive solo ultimo_cambiamento_at: {estranee}")
    return _controllo(strumento).aggiorna("bando", bando_id, dati)


def azzera_rielaborazione(
    bando_id: Any,
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any]:
    """Rimette a NULL il marcatore della rielaborazione del bando (§5, §9):
    il passo 12 lo rielabora al giro dopo. La chiama il monitor dopo una
    rettifica di contenuto o allegati, o una riapertura. Non solleva."""
    strumento = _controllo(strumento)
    if not strumento.ha("bando", "fonte_ufficiale_link_id"):
        return {"scritto": False, "motivo": "colonne_assenti"}
    try:
        righe = (_client(client).table("bando").select("fonte_ufficiale_link_id")
                 .eq("id", bando_id).execute().data or [])
    except Exception as e:
        logger.warning("[db] azzera_rielaborazione {}: lettura fallita: {}", bando_id, e)
        return {"scritto": False, "motivo": str(e)}
    link_id = righe[0].get("fonte_ufficiale_link_id") if righe else None
    if link_id is None:
        return {"scritto": False, "motivo": "nessuna riga della fonte"}
    return strumento.aggiorna(TABELLA_LINK, link_id, {"impronta_contenuto": None})


def registra_evento_rpc(
    parametri: Mapping[str, Any],
    *,
    client: Any | None = None,
    strumento: Any | None = None,
) -> dict[str, Any] | None:
    """`bando_registra_evento` con i parametri per nome (vedi
    `eventi.PARAMETRI_REGISTRA_EVENTO`). Ritorna la risposta (`{id, nuovo,
    applicato}`) o None se la RPC non c'e' o fallisce. Non solleva."""
    from .eventi import RPC_REGISTRA_EVENTO
    strumento = _controllo(strumento)
    if not strumento.rpc_disponibile(RPC_REGISTRA_EVENTO):
        logger.info("[db] RPC {} assente: evento non registrato", RPC_REGISTRA_EVENTO)
        return None
    try:
        risposta = _client(client).rpc(RPC_REGISTRA_EVENTO, dict(parametri)).execute()
    except Exception as e:
        logger.warning("[db] {} fallita per il bando {}: {}",
                       RPC_REGISTRA_EVENTO, parametri.get("p_bando_id"), e)
        return None
    dati = getattr(risposta, "data", None)
    if isinstance(dati, list):
        dati = dati[0] if dati else None
    return dict(dati) if isinstance(dati, Mapping) else None
