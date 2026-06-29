"""Orchestratore della pipeline bandi (v4 — skill autoritativa totale).

Due fasi compongono il flusso end-to-end:

1. **Scraper** (sotto-progetto Python autonomo `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python`):
   invocato come subprocess (`python -m app.cli run`) con `cwd=BANDI_SCRAPER_DIR`.
   Lo scraper fa discovery dei link e inserisce i candidati nella tabella `bando`
   con `state='discovered'`. Niente piu' classificazione AI pre-skill (deprecata in v4).

2. **Skill SEO enrichment** (`bandi-seo-enricher`): in-process via Claude Agent SDK
   (vedi `bandi_skill_runner.py`). Per ogni bando in `state='discovered'`:
   - costruisce `hint_dominio` dai dati relazionali gia' presenti nel DB,
   - invoca la skill che produce JSON validato (livello flash_bando o guida_bando)
     + verifier adversarial Haiku 4.5,
   - persiste l'output via `update_bando_from_payload` che decide lo stato finale
     (`confirmed`/`rejected`/`refuted`/`error`).

I bandi non vengono cancellati ne' duplicati: la skill arricchisce il record
esistente. In caso di errore transient (`attempts < BANDI_SKILL_MAX_ATTEMPTS`)
il record resta in `state='error'` e viene riprovato dal batch successivo.

Parallelismo (v4):
  - Scraper subprocess gira in `asyncio.to_thread` PARALLELO alla skill batch
    (la state machine `state` e' interamente di proprieta' della skill, lo
    scraper UPDATE tocca solo i campi raw — nessuna race in DB).
  - Skill enrichment processa fino a `BANDI_SKILL_CONCURRENCY` bandi
    in parallelo via `asyncio.Semaphore` (default 3).
  - `run_skill_enrichment_batch` drena la coda FINO A ESAURIMENTO via loop
    round-per-round (chunk SELECT = `BANDI_SKILL_BATCH_SIZE`, default 10):
    nessun cap hard sul totale, lo scraper in parallelo puo' aggiungere
    candidati che il loop raccoglie al round successivo.

ENV vars:
  - BANDI_SCRAPER_DIR         path al sotto-progetto scraper (obbligatoria)
  - BANDI_SCRAPER_PYTHON      interprete python del scraper (default: 'python')
  - BANDI_SCRAPER_TIMEOUT_S   timeout subprocess scraper in s (default: 1800 = 30 min)
  - BANDI_SCRAPER_RUN_LIMIT   limite fonti per ciclo scraper (opzionale)
  - BANDI_SKILL_BATCH_SIZE    chunk SELECT per round drain (default: 10).
                              NON e' un cap totale: il loop drena fino a coda vuota.
  - BANDI_SKILL_MAX_ATTEMPTS  retry skill su singolo bando (default: 3)
  - BANDI_SKILL_CONCURRENCY   skill paralleli max per round (default: 3)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
import threading
import time
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

from dotenv import load_dotenv

# Carica .env del backend al primo import (stesso pattern di interpelli.py / selezione_personale.py)
load_dotenv()

from .bandi_skill_runner import run_bandi_skill
from .bandi_supabase import get_bandi_supabase
from .logger import logger


# ---------------------------------------------------------------------------
# Fase 1 — scraper come subprocess
# ---------------------------------------------------------------------------

def _scraper_dir() -> str:
    d = os.getenv("BANDI_SCRAPER_DIR")
    if not d:
        raise RuntimeError("BANDI_SCRAPER_DIR non impostato in env")
    return d


def _scraper_python() -> str:
    return os.getenv("BANDI_SCRAPER_PYTHON") or "python"


# Variabili che lo scraper deve leggere dal suo `.env` interno (non da quello di
# news1). Pydantic-settings legge prima dall'env del processo e poi cade sul
# `.env`: se lasciamo passare le variabili del parent (es. `DATABASE_URL` di
# news1 = sqlite di sviluppo), sovrascrivono il `DATABASE_URL` Supabase del DB B
# atteso dallo scraper.
_SCRAPER_ENV_BLOCKLIST = (
    "DATABASE_URL",
    "DATABASE_POOLER_HOST", "DATABASE_POOLER_PORT",
    "DATABASE_CONNECT_TIMEOUT_SECONDS", "DATABASE_SSLMODE",
    "SUPABASE_URL", "SUPABASE_KEY",
    "OPENAI_API_KEY", "OPENAI_MODEL",
    "TESSERACT_CMD", "OCR_LANGUAGE",
    "SOURCE_ROOT_URL",
    "SCRAPER_CONCURRENCY", "SCRAPER_TIMEOUT_SECONDS",
    "SCRAPER_RETRY_MAX", "SCRAPER_RETRY_DELAY_SECONDS",
    "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
    "LOG_LEVEL", "LOG_JSON",
)


def _scraper_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for var in _SCRAPER_ENV_BLOCKLIST:
        env.pop(var, None)
    return env


def _scraper_timeout_s() -> int:
    """Timeout del subprocess scraper in secondi. Default 30 min.

    Override via `BANDI_SCRAPER_TIMEOUT_S` per scraper lunghi (50+ fonti × Firecrawl).
    """
    try:
        return int(os.getenv("BANDI_SCRAPER_TIMEOUT_S", "1800"))
    except ValueError:
        return 1800


def _stream_log_to_logger(log_path: str, label: str, stop_event: threading.Event) -> None:
    """Thread reader: tail-follow del log file del subprocess.

    Rilancia ogni riga al logger principale come `[bandi/<label>/stream] ...`
    cosi' che `journalctl -u edunews-bandi-sender -f` veda il progress del
    subprocess in tempo reale (non solo al termine).
    """
    try:
        # Apertura ritardata: il subprocess sta scrivendo, il file potrebbe
        # non esistere ancora per qualche istante. Aspetta fino a 5s.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not os.path.exists(log_path):
            time.sleep(0.1)
        if not os.path.exists(log_path):
            logger.warning("[bandi/{}/stream] log file non disponibile dopo 5s: {}", label, log_path)
            return

        with open(log_path, "r", errors="replace") as f:
            while not stop_event.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                logger.info("[bandi/{}/stream] {}", label, line.rstrip())
            # Drain finale: leggi le righe scritte tra l'ultimo readline e stop_event.
            for line in f.readlines():
                if line.strip():
                    logger.info("[bandi/{}/stream] {}", label, line.rstrip())
    except Exception:
        logger.exception("[bandi/{}/stream] reader thread crash", label)


def _run_scraper_module(module: str, args: list[str], label: str) -> int:
    """Esegue `python -m <module> [args...]` con cwd e env dello scraper.

    Lo stdout/stderr e' rediretto a `/tmp/bandi_<label>_<timestamp>.log`
    in line-buffered. Un thread reader (`_stream_log_to_logger`) tail-follow
    il file e rilancia ogni riga al logger principale, cosi' che la console
    journalctl veda il progress del subprocess in real-time.

    Su timeout (`BANDI_SCRAPER_TIMEOUT_S`, default 30 min) il subprocess
    e' killato e la funzione ritorna rc=-2.
    """
    cmd = [_scraper_python(), "-m", module, *args]
    timeout = _scraper_timeout_s()
    log_path = f"/tmp/bandi_{label}_{int(time.time())}.log"
    logger.info(
        "[bandi/{}] START cwd={} cmd={} log={} timeout={}s",
        label, _scraper_dir(), " ".join(cmd), log_path, timeout,
    )
    started = time.monotonic()
    log_fp = open(log_path, "w", buffering=1)
    stop_event = threading.Event()
    reader = threading.Thread(
        target=_stream_log_to_logger,
        args=(log_path, label, stop_event),
        daemon=True,
        name=f"scraper-stream-{label}",
    )
    reader.start()
    proc: subprocess.Popen[str] | None = None
    rc = -1
    try:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=_scraper_dir(),
                env=_scraper_subprocess_env(),
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError as e:
            logger.error("[bandi/{}] python non trovato: {}", label, e)
            return -1

        logger.info("[bandi/{}] subprocess pid={} attendo (timeout={}s)", label, proc.pid, timeout)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.error(
                "[bandi/{}] TIMEOUT raggiunto ({}s) -> killing pid={}",
                label, timeout, proc.pid,
            )
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.error("[bandi/{}] kill non risponde entro 10s, lascio zombie", label)
            elapsed = time.monotonic() - started
            logger.error(
                "[bandi/{}] TIMEOUT after {:.0f}s rc=-2 (log={})",
                label, elapsed, log_path,
            )
            return -2
    finally:
        # Da' qualche istante extra al reader per drenare le ultime righe
        # scritte tra la fine del subprocess e lo stop_event.
        time.sleep(0.5)
        stop_event.set()
        try:
            log_fp.close()
        except Exception:
            pass
        reader.join(timeout=5)
        if reader.is_alive():
            logger.warning("[bandi/{}/stream] reader thread non si e' chiuso entro 5s", label)

    elapsed = time.monotonic() - started
    logger.info(
        "[bandi/{}] DONE in {:.1f}s rc={} log={}",
        label, elapsed, rc, log_path,
    )
    return rc


def run_scraper_full() -> int:
    """Esegue una scan completa di tutte le fonti attive (cli `run`).

    v4: lo scraping inserisce direttamente i candidati con `state='discovered'`
    (l'enqueue su `ai_job_queue` e' deprecato). La skill enrichment li drena.
    """
    args: list[str] = ["run"]
    limit = os.getenv("BANDI_SCRAPER_RUN_LIMIT")
    if limit:
        args += ["--limit", str(limit)]
    return _run_scraper_module("app.cli", args, "scraper-full")


def run_scraper_pending() -> int:
    """Retry sulle fonti/bandi in coda `pending` (cli `run-pending`)."""
    return _run_scraper_module("app.cli", ["run-pending"], "scraper-pending")


# v4: il worker AI Opus pre-skill (`run_ai_worker_drain`) e' stato deprecato.
# La skill `bandi-seo-enricher` e' ora autoritativa sull'estrazione + validazione,
# quindi non c'e' piu' classificazione intermedia. Lo scraper passa direttamente
# alla skill enrichment via state='discovered'.


# ---------------------------------------------------------------------------
# Fase 2 — skill enrichment
# ---------------------------------------------------------------------------

# Campi del bando rilevanti da passare come hint alla skill (schema v4).
# Solo colonne sopravvissute alla migrazione v4: niente seo_*, niente skill_*,
# niente *_norm, niente is_bando_confermato/rejection_category.
_BANDO_CORE_COLUMNS = (
    "id, titolo, descrizione, codice_bando, fondo, link_bando, "
    "data_pubblicazione, data_apertura, data_scadenza, "
    "tipologia_bando_id, modalita_erogazione_id, programma_id, "
    "state, state_detail, attempts, "
    "ultimo_scraping_at, raw_data, data_extra"
)


# Stati ammessi della tabella `bando` (vedi backend/sql/bando_v4_collapse.sql).
class BandoState:
    DISCOVERED = "discovered"
    ENRICHING = "enriching"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    REFUTED = "refuted"
    ERROR = "error"
    STALE = "stale"


def _slugify(text: str) -> str:
    """Slug minimal per fallback (kebab-case ascii)."""
    if not text:
        return "bando"
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm[:120] or "bando"


def _safe_select_names(sb, table: str, ids: list[int]) -> list[str]:
    """Best-effort SELECT name FROM <table> WHERE id IN (...). Ritorna [] su errore."""
    if not ids:
        return []
    try:
        res = sb.table(table).select("nome").in_("id", ids).execute()
        return [r["nome"] for r in (res.data or []) if r.get("nome")]
    except Exception as e:
        logger.warning("[bandi/hint] lookup {} ids={} failed: {}", table, ids, e)
        return []


def _safe_select_ateco(sb, ids: list[int]) -> list[str]:
    if not ids:
        return []
    try:
        res = sb.table("codici_ateco").select("codice, descrizione").in_("id", ids).execute()
        out = []
        for r in res.data or []:
            code = r.get("codice")
            desc = r.get("descrizione")
            if code and desc:
                out.append(f"{code} {desc}")
            elif code:
                out.append(code)
        return out
    except Exception as e:
        logger.warning("[bandi/hint] lookup codici_ateco ids={} failed: {}", ids, e)
        return []


def _try_junction_lookup(sb, junction: str, fk_field: str, bando_id: int) -> list[int]:
    """Tenta di leggere una tabella di join bando_<lookup>. Best-effort."""
    try:
        res = sb.table(junction).select(fk_field).eq("bando_id", bando_id).execute()
        return [r[fk_field] for r in (res.data or []) if r.get(fk_field) is not None]
    except Exception:
        return []


def build_hint_from_bando(sb, bando: dict[str, Any]) -> dict[str, Any]:
    """Costruisce `hint_dominio` per la skill `bandi-seo-enricher` dai dati relazionali.

    L'hint e' un suggerimento (prior) per il modello; la skill estrarra' poi i campi
    autoritativi dalla pagina istituzionale. Restituisce un dict serializzabile JSON.
    """
    bando_id = bando.get("id")
    hint: dict[str, Any] = {}

    # 1) Tipologia normalizzata via lookup (resta un nome italiano grezzo, la skill
    #    la normalizzera' in FESR/FSE/Interreg/nazionale/regionale/misto/JTF).
    tipologia_id = bando.get("tipologia_bando_id")
    if tipologia_id:
        names = _safe_select_names(sb, "tipologie_bando", [tipologia_id])
        if names:
            hint["tipologia_grezza"] = names[0]

    # 2) Programma (es. "PR Lombardia FESR 2021-2027")
    programma_id = bando.get("programma_id")
    if programma_id:
        names = _safe_select_names(sb, "programmi", [programma_id])
        if names:
            hint["programma"] = names[0]

    # 3) Modalita erogazione
    modalita_id = bando.get("modalita_erogazione_id")
    if modalita_id:
        names = _safe_select_names(sb, "modalita_erogazione", [modalita_id])
        if names:
            hint["modalita_erogazione"] = names[0]

    # 4) Beneficiari (M-N via bando_beneficiari)
    beneficiari_ids = _try_junction_lookup(sb, "bando_beneficiari", "beneficiario_id", bando_id) if bando_id else []
    if beneficiari_ids:
        beneficiari_names = _safe_select_names(sb, "beneficiari", beneficiari_ids)
        if beneficiari_names:
            hint["beneficiari"] = beneficiari_names

    # 5) Regioni (M-N via bando_regioni — pattern probabile)
    regioni_ids = _try_junction_lookup(sb, "bando_regioni", "regione_id", bando_id) if bando_id else []
    if regioni_ids:
        regioni_names = _safe_select_names(sb, "regioni", regioni_ids)
        if regioni_names:
            hint["regioni"] = regioni_names

    # 6) Settori (M-N via bando_settori)
    settori_ids = _try_junction_lookup(sb, "bando_settori", "settore_id", bando_id) if bando_id else []
    if settori_ids:
        settori_names = _safe_select_names(sb, "settori", settori_ids)
        if settori_names:
            hint["settori"] = settori_names

    # 7) Codici ATECO (M-N via bando_codici_ateco)
    ateco_ids = _try_junction_lookup(sb, "bando_codici_ateco", "codice_ateco_id", bando_id) if bando_id else []
    if ateco_ids:
        ateco_strings = _safe_select_ateco(sb, ateco_ids)
        if ateco_strings:
            hint["codici_ateco"] = ateco_strings

    # 8) Metadati grezzi dal parser
    if bando.get("codice_bando"):
        hint["codice_bando"] = bando["codice_bando"]
    if bando.get("fondo"):
        hint["fondo"] = bando["fondo"]
    if bando.get("data_scadenza"):
        hint["data_scadenza_grezza"] = str(bando["data_scadenza"])
    if bando.get("data_pubblicazione"):
        # Hint: data di pubblicazione gia' estratta da fase 1. La skill puo'
        # proporre la sua se ne trova una piu' autoritativa (es. dal PDF) col
        # campo `bando.data_pubblicazione_source` (vedi SKILL.md STEP 6b).
        hint["data_pubblicazione_grezza"] = str(bando["data_pubblicazione"])
    # (v4: `importo` e `importo_numerico` rimosse dallo schema — la skill estrae
    # autoritativamente `importo_totale_eur` / `importo_max_per_progetto_eur`.)

    # 9) Hint di matching: se il parser ha gia' un titolo/descrizione, dallo al modello
    if bando.get("titolo"):
        hint["titolo_grezzo"] = bando["titolo"]
    if bando.get("descrizione"):
        # Limita lunghezza per non far esplodere il prompt
        hint["descrizione_grezza"] = bando["descrizione"][:800]

    # Riepilogo conteggi (debug) per visibilita' "cosa abbiamo passato alla skill"
    sizes = {}
    for k, v in hint.items():
        if isinstance(v, list):
            sizes[k] = len(v)
        elif isinstance(v, str):
            sizes[k] = len(v)
        else:
            sizes[k] = 1
    logger.debug(
        "[bandi/hint/{}] keys_collected={} sizes={}",
        bando_id, sorted(hint.keys()), sizes,
    )

    return hint


def _pick(d: Any, key: str) -> Any:
    if isinstance(d, dict):
        return d.get(key)
    return None


_SCADENZA_OVERRIDE_SOURCES = {"official_pdf", "official_page"}

# v4 — discovery-by-skill: quando la skill marca un record come index_page o
# category_page, puo' emettere validation.discovered_sublinks con i sub-link
# figli da accodare come nuovi BandoCandidate. Limiti contro loop / spam.
_DISCOVERY_MAX_DEPTH = 3
_DISCOVERY_REDISCOVERABLE_REJECTIONS = {"index_page", "category_page"}
_DISCOVERY_SUBLINKS_PER_PARENT_MAX = 50


def _hash_bando_for_discovery(fonte_id: int, link_bando: str) -> str:
    """Stesso schema hash usato dal scraper (SHA256 'fonte_id|link_bando'),
    cosi' che il vincolo UNIQUE su `bando.hash_bando` faccia naturalmente
    dedup tra discovery-by-skill e ri-scrape successivo della stessa fonte.
    """
    payload = f"{int(fonte_id)}|{link_bando}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _insert_discovered_sublinks(
    sb,
    parent_bando_id: int,
    parent_fonte_id: int | None,
    parent_state_detail: dict[str, Any] | None,
    parent_source_url: str | None,
    payload: dict[str, Any],
    new_state: str,
    new_state_detail: dict[str, Any],
) -> int:
    """Accoda i sub-link emessi dalla skill come nuovi BandoCandidate.

    Eseguito solo se `new_state='rejected'` e `rejection_category` ∈ {index_page, category_page}.
    Best-effort: errori non bloccano l'enrichment del parent.
    Ritorna il numero di sublink effettivamente inseriti (gli altri sono duplicati gia' presenti).
    """
    rej = (new_state_detail or {}).get("rejection_category")
    if new_state != BandoState.REJECTED or rej not in _DISCOVERY_REDISCOVERABLE_REJECTIONS:
        return 0
    if parent_fonte_id is None:
        logger.warning("[bandi/discovery] parent bando_id={} senza fonte_id: skip sublinks", parent_bando_id)
        return 0

    validation = (payload or {}).get("validation") or {}
    raw_sublinks = validation.get("discovered_sublinks") or []
    if not isinstance(raw_sublinks, list) or not raw_sublinks:
        return 0

    # Anti-loop: profondita' del parent +1. Oltre _DISCOVERY_MAX_DEPTH stop.
    parent_depth = 0
    if isinstance(parent_state_detail, dict):
        try:
            parent_depth = int(parent_state_detail.get("discovery_depth") or 0)
        except (TypeError, ValueError):
            parent_depth = 0
    child_depth = parent_depth + 1
    if child_depth > _DISCOVERY_MAX_DEPTH:
        logger.warning(
            "[bandi/discovery/{}] anti-loop: parent_depth={} >= MAX {}, skip {} sublinks",
            parent_bando_id, parent_depth, _DISCOVERY_MAX_DEPTH, len(raw_sublinks),
        )
        return 0

    # Limita il numero per parent (defense contro skill rumorosa).
    received = len(raw_sublinks)
    sublinks = list(raw_sublinks)[:_DISCOVERY_SUBLINKS_PER_PARENT_MAX]
    capped = received - len(sublinks)
    if capped > 0:
        logger.warning(
            "[bandi/discovery/{}] cap raggiunto ({}): scarto {} sublinks oltre i primi {}",
            parent_bando_id, _DISCOVERY_SUBLINKS_PER_PARENT_MAX, capped,
            _DISCOVERY_SUBLINKS_PER_PARENT_MAX,
        )

    logger.info(
        "[bandi/discovery/{}] processing {} sublinks (depth {}/{}) parent_url={}",
        parent_bando_id, len(sublinks), child_depth, _DISCOVERY_MAX_DEPTH, parent_source_url,
    )

    inserted = 0
    skipped_duplicate = 0
    skipped_error = 0
    skipped_invalid = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for idx, entry in enumerate(sublinks, start=1):
        if not isinstance(entry, dict):
            skipped_invalid += 1
            continue
        url = (entry.get("url") or "").strip()
        label = (entry.get("label") or "").strip()
        if not url.startswith(("http://", "https://")):
            logger.debug(
                "[bandi/discovery/{}] skip sublink {} (url non http/https: {!r})",
                parent_bando_id, idx, url[:80],
            )
            skipped_invalid += 1
            continue
        hash_val = _hash_bando_for_discovery(parent_fonte_id, url)
        record = {
            "fonte_id": parent_fonte_id,
            "hash_bando": hash_val,
            "link_bando": url,
            "titolo": label or url,
            "state": BandoState.DISCOVERED,
            "state_detail": {
                "discovery_depth": child_depth,
                "parent_bando_id": parent_bando_id,
                "parent_source_url": parent_source_url,
            },
            "state_updated_at": now_iso,
            "attempts": 0,
            "raw_data": {"discovered_via": "skill_sublinks", "discovered_at": now_iso},
            "primo_scraping_at": now_iso,
            "ultimo_scraping_at": now_iso,
        }
        try:
            # ON CONFLICT (hash_bando) DO NOTHING — duplicato silenzioso = OK.
            sb.table("bando").upsert(
                record, on_conflict="hash_bando", ignore_duplicates=True
            ).execute()
            inserted += 1
            logger.info(
                "[bandi/discovery/{}] queued #{}: {} (label={!r})",
                parent_bando_id, idx, url, (label[:60] if label else None),
            )
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                skipped_duplicate += 1
                logger.debug(
                    "[bandi/discovery/{}] sublink #{} duplicato (hash gia' presente): {}",
                    parent_bando_id, idx, url,
                )
            else:
                skipped_error += 1
                logger.warning(
                    "[bandi/discovery/{}] insert sublink #{} fallito url={}: {}",
                    parent_bando_id, idx, url, e,
                )

    logger.info(
        "[bandi/discovery/{}] DONE depth={}/{} -> {} nuovi candidati "
        "(dup={}, invalid={}, err={}, ricevuti={}, capped={})",
        parent_bando_id, child_depth, _DISCOVERY_MAX_DEPTH,
        inserted, skipped_duplicate, skipped_invalid, skipped_error, received, capped,
    )
    return inserted


def _read_existing_for_audit(sb, bando_id: int) -> dict[str, Any] | None:
    """Legge (data_scadenza, data_pubblicazione, raw_data) per audit pre-skill override.

    Best-effort: ritorna None se il fetch fallisce (l'update procede comunque).
    """
    try:
        res = (
            sb.table("bando")
            .select("data_scadenza, data_pubblicazione, raw_data")
            .eq("id", bando_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("[bandi] read pre-skill audit failed bando_id={}: {}", bando_id, e)
        return None


def _derive_state(payload: dict[str, Any], verifier: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Calcola lo state machine target a partire dal payload skill + verdetto verifier.

    Ritorna una tupla (state, state_detail). Priorita':
        1. verifier='refuted' -> state=refuted (skill smentita)
        2. date incoerenti (pub>scad) -> state=rejected con rejection_category=not_a_funding_call
        3. skill ha bocciato (is_valid_bando=false o rejection_category presente) -> state=rejected
        4. skill ha confermato -> state=confirmed

    Il verifier='skipped' (API down/markdown vuoto) NON blocca: la skill resta autoritativa.
    """
    verifier = verifier or {}
    validation_obj = payload.get("validation") or {}
    bando_obj = payload.get("bando") or {}

    detail: dict[str, Any] = {
        "rejection_category": validation_obj.get("rejection_category"),
        "validation_reason": validation_obj.get("validation_reason"),
        "verifier_verdict": verifier.get("verdict"),
        "verifier_notes": verifier.get("notes"),
        "refuted_fields": verifier.get("refuted_fields"),
        "last_error": None,
        "last_error_at": None,
    }

    logger.debug(
        "[bandi/derive_state] inputs: is_valid={} rejection={} verifier_verdict={} refuted_fields={} "
        "data_pub={} data_scad={}",
        validation_obj.get("is_valid_bando"),
        validation_obj.get("rejection_category"),
        verifier.get("verdict"),
        verifier.get("refuted_fields"),
        _pick(bando_obj, "data_pubblicazione"),
        _pick(bando_obj, "scadenza"),
    )

    if (verifier.get("verdict") or "").lower() == "refuted":
        logger.info(
            "[bandi/derive_state] -> REFUTED (verifier ha smentito skill, refuted_fields={})",
            verifier.get("refuted_fields"),
        )
        return BandoState.REFUTED, detail

    scadenza_iso = _pick(bando_obj, "scadenza")
    pubblicazione_iso = _pick(bando_obj, "data_pubblicazione")
    if scadenza_iso and pubblicazione_iso:
        try:
            if date.fromisoformat(pubblicazione_iso) > date.fromisoformat(scadenza_iso):
                detail["rejection_category"] = detail.get("rejection_category") or "not_a_funding_call"
                prior = detail.get("validation_reason") or ""
                detail["validation_reason"] = f"{prior} [orchestrator: inconsistent dates]".strip()
                logger.info(
                    "[bandi/derive_state] -> REJECTED (date incoerenti: pub={} > scad={})",
                    pubblicazione_iso, scadenza_iso,
                )
                return BandoState.REJECTED, detail
        except ValueError:
            pass  # formato non-ISO: lascia al CHECK constraint DB

    is_valid_bando = validation_obj.get("is_valid_bando")
    if is_valid_bando is False or validation_obj.get("rejection_category"):
        if not detail.get("rejection_category"):
            detail["rejection_category"] = "not_a_funding_call"
        logger.info(
            "[bandi/derive_state] -> REJECTED (is_valid_bando={} rejection_category={})",
            is_valid_bando, detail.get("rejection_category"),
        )
        return BandoState.REJECTED, detail

    logger.info(
        "[bandi/derive_state] -> CONFIRMED (verifier_verdict={})",
        verifier.get("verdict") or "skipped/null",
    )
    return BandoState.CONFIRMED, detail


def update_bando_from_payload(sb, bando_id: int, payload: dict[str, Any]) -> None:
    """Persiste il payload della skill (schema v4) nelle colonne di `bando`.

    Schema v4: la tabella ha una sola colonna `state` (state machine) + `state_detail` JSONB
    per il "perche'". La skill emette il payload, il verifier (gia' incorporato dal caller in
    payload['skill_verifier_*']) corregge, l'orchestrator decide lo stato finale via
    `_derive_state`. Le date hanno citazione embedded in `date_quotes` JSONB.

    Risolve eventuali collisioni di `slug` aggiungendo suffisso `-{bando_id}`.
    """
    bando_obj = payload.get("bando") or {}

    # Composizione verifier (campi flat persistiti dall'orchestrator)
    verifier = {
        "verdict": payload.get("skill_verifier_verdict"),
        "notes": payload.get("skill_verifier_notes"),
        "refuted_fields": payload.get("skill_verifier_refuted_fields"),
    }

    new_state, state_detail = _derive_state(payload, verifier)

    # Estrazione date dal payload + costruzione date_quotes JSONB
    scadenza_iso = _pick(bando_obj, "scadenza")
    scadenza_source = _pick(bando_obj, "scadenza_source")
    scadenza_quote = _pick(bando_obj, "scadenza_quote")
    pubblicazione_iso = _pick(bando_obj, "data_pubblicazione")
    pubblicazione_source = _pick(bando_obj, "data_pubblicazione_source")
    pubblicazione_quote = _pick(bando_obj, "data_pubblicazione_quote")

    # Se state='rejected' per inconsistenza date, azzera le date persistite (CHECK DB).
    if new_state == BandoState.REJECTED and state_detail.get("rejection_category") == "not_a_funding_call":
        if scadenza_iso and pubblicazione_iso:
            try:
                if date.fromisoformat(pubblicazione_iso) > date.fromisoformat(scadenza_iso):
                    logger.warning(
                        "[bandi] date incoerenti bando_id={} pub={} > scad={}: azzero entrambe",
                        bando_id, pubblicazione_iso, scadenza_iso,
                    )
                    scadenza_iso = None
                    pubblicazione_iso = None
                    scadenza_quote = None
                    pubblicazione_quote = None
            except ValueError:
                pass

    date_quotes = {
        "pubblicazione": {
            "value": pubblicazione_iso,
            "source": pubblicazione_source,
            "quote": pubblicazione_quote,
        },
        "scadenza": {
            "value": scadenza_iso,
            "source": scadenza_source,
            "quote": scadenza_quote,
        },
    }

    record: dict[str, Any] = {
        "state": new_state,
        "state_detail": state_detail,
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
        # Editorial (skill autoritativa)
        "slug": payload.get("slug"),
        "livello": payload.get("livello"),
        "titolo": payload.get("titolo"),
        "titolo_breve": payload.get("occhiello"),
        "descrizione_breve": payload.get("descrizione_breve"),
        "contenuto": payload.get("contenuto"),
        # Dates + citation
        "date_quotes": date_quotes,
        # Classification (skill normalized)
        "tipologia": _pick(bando_obj, "tipologia"),
        "programma": _pick(bando_obj, "programma"),
        "modalita_erogazione": _pick(bando_obj, "modalita_erogazione"),
        "area_geografica": _pick(bando_obj, "area_geografica"),
        "tematica": _pick(bando_obj, "tematica"),
        "beneficiari": _pick(bando_obj, "beneficiari"),
        "codici_ateco": _pick(bando_obj, "codici_ateco"),
        # Amounts
        "importo_totale_eur": _pick(bando_obj, "importo_totale_eur"),
        "importo_max_per_progetto_eur": _pick(bando_obj, "importo_max_per_progetto_eur"),
        # Source/Ente
        "ente_erogatore": _pick(bando_obj, "ente_erogatore"),
        # Links
        "link_candidatura": _pick(bando_obj, "link_candidatura"),
        "link_candidatura_source": _pick(bando_obj, "link_candidatura_source"),
        # Allegati
        "allegati": payload.get("allegati") or _pick(bando_obj, "allegati"),
    }

    # Override scraper-side date SOLO se la skill ha source autorevole.
    # Per inferred/missing manteniamo il valore scraper di fase 1.
    if scadenza_iso and scadenza_source in _SCADENZA_OVERRIDE_SOURCES:
        record["data_scadenza"] = scadenza_iso
    if pubblicazione_iso and pubblicazione_source in _SCADENZA_OVERRIDE_SOURCES:
        record["data_pubblicazione"] = pubblicazione_iso

    # Rimuovi i None — Postgres mantiene il valore esistente se non specificato.
    record_clean = {k: v for k, v in record.items() if v is not None}

    # Slug obbligatorio solo se state='confirmed' (record pubblico).
    if new_state == BandoState.CONFIRMED:
        if not record_clean.get("slug"):
            record_clean["slug"] = _slugify(payload.get("titolo") or "") + f"-{bando_id}"
    else:
        # Per i record non pubblici lo slug non e' necessario; rimuovilo se vuoto
        # per non violare CHECK / UNIQUE inutilmente.
        if not record_clean.get("slug"):
            record_clean.pop("slug", None)

    logger.info(
        "[bandi/persist/{}] UPDATE state={} slug={} fields_set={}",
        bando_id, new_state, record_clean.get("slug"), sorted(record_clean.keys()),
    )
    try:
        sb.table("bando").update(record_clean).eq("id", bando_id).execute()
    except Exception as e:
        msg = str(e)
        if "23505" in msg or "duplicate key" in msg.lower() or "unique" in msg.lower():
            original_slug = record_clean.get("slug") or _slugify(payload.get("titolo") or "")
            record_clean["slug"] = f"{original_slug}-{bando_id}"
            logger.warning(
                "[bandi/persist/{}] slug collision -> retry con slug={}",
                bando_id, record_clean["slug"],
            )
            sb.table("bando").update(record_clean).eq("id", bando_id).execute()
            logger.info("[bandi/persist/{}] UPDATE OK (slug collision risolta)", bando_id)
        else:
            logger.exception("[bandi/persist/{}] UPDATE fallito (non-slug): {}", bando_id, e)
            raise
    else:
        logger.info("[bandi/persist/{}] UPDATE OK", bando_id)

    # v4 — discovery-by-skill: se la skill ha bocciato come index_page / category_page
    # e ha emesso `validation.discovered_sublinks`, accodali come nuovi BandoCandidate.
    # Best-effort: errori non bloccano il salvataggio del parent (gia' fatto sopra).
    rejection_cat = (state_detail or {}).get("rejection_category")
    if new_state == BandoState.REJECTED and rejection_cat in _DISCOVERY_REDISCOVERABLE_REJECTIONS:
        try:
            parent_row = (
                sb.table("bando")
                .select("fonte_id, state_detail, link_bando")
                .eq("id", bando_id)
                .single()
                .execute()
            )
            parent_data = parent_row.data or {}
            _insert_discovered_sublinks(
                sb,
                parent_bando_id=bando_id,
                parent_fonte_id=parent_data.get("fonte_id"),
                parent_state_detail=parent_data.get("state_detail"),
                parent_source_url=parent_data.get("link_bando"),
                payload=payload,
                new_state=new_state,
                new_state_detail=state_detail,
            )
        except Exception as e:
            logger.warning(
                "[bandi/discovery] fetch parent_bando_id={} for sublinks failed: {}",
                bando_id, e,
            )


# v4: `_denormalize_bando_lookups` rimossa. Scriveva su `programma_nome`,
# `modalita_erogazione_nome`, `codici_ateco_norm` — tutte colonne droppate dalla
# migrazione `bando_v4_collapse.sql`. La normalizzazione e' autoritativa
# skill-side: la skill emette gia' `programma`, `modalita_erogazione`,
# `codici_ateco` normalizzati.


def _max_attempts() -> int:
    try:
        return int(os.getenv("BANDI_SKILL_MAX_ATTEMPTS", "3"))
    except ValueError:
        return 3


def _set_error_state(sb, bando_id: int, current_attempts: int, error_msg: str) -> None:
    """Marca un bando come error con incremento attempts e dettaglio errore."""
    sb.table("bando").update({
        "state": BandoState.ERROR,
        "state_detail": {
            "last_error": error_msg[:500],
            "last_error_at": datetime.now(timezone.utc).isoformat(),
        },
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
        "attempts": current_attempts + 1,
    }).eq("id", bando_id).execute()


async def _enrich_one(sb, bando: dict[str, Any]) -> bool:
    """Arricchisce un singolo bando. Ritorna True se confermato, False altrimenti.

    Flow v4:
      1. Lock soft: state='enriching', attempts+=1
      2. Costruisci hint dai dati relazionali (catalogo legacy, junction tables)
      3. Invoca skill — su errore: state='error', attempts++ (riprovabile)
      4. update_bando_from_payload: la skill scrive payload + il derive_state decide
         lo stato finale (confirmed/rejected/refuted) in base a verifier + coerenza date
    """
    bando_id = bando["id"]
    link = bando.get("link_bando")
    current_attempts = int(bando.get("attempts") or 0)
    enrich_started = time.monotonic()

    if not link:
        logger.warning(
            "[bandi/skill/{}] SKIP: link_bando assente -> state='stale'",
            bando_id,
        )
        sb.table("bando").update({
            "state": BandoState.STALE,
            "state_detail": {"last_error": "link_bando assente", "last_error_at": datetime.now(timezone.utc).isoformat()},
            "state_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bando_id).execute()
        return False

    # 1) Lock soft (ottimistico, no transaction): state='enriching', attempts++
    new_attempt = current_attempts + 1
    logger.info(
        "[bandi/skill/{}] step 1/4 LOCK -> state='enriching' attempt={}/{} link={}",
        bando_id, new_attempt, _max_attempts(), link,
    )
    sb.table("bando").update({
        "state": BandoState.ENRICHING,
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
        "attempts": new_attempt,
    }).eq("id", bando_id).execute()

    # 2) Hint dai dati relazionali (catalogo legacy + junction)
    logger.info("[bandi/skill/{}] step 2/4 build_hint", bando_id)
    hint = build_hint_from_bando(sb, bando)
    logger.debug(
        "[bandi/skill/{}] hint pronto: keys={} sizes={}",
        bando_id,
        sorted(hint.keys()),
        {k: (len(v) if isinstance(v, (list, dict)) else 1) for k, v in hint.items()},
    )

    # 3) Invoca skill (Claude Agent SDK in-process)
    logger.info("[bandi/skill/{}] step 3/4 invoking skill", bando_id)
    skill_started = time.monotonic()
    try:
        payload = await run_bandi_skill(link_bando=link, hint=hint)
    except Exception as e:
        skill_elapsed = time.monotonic() - skill_started
        logger.exception(
            "[bandi/skill/{}] skill FALLITA in {:.1f}s (attempt {}): {}",
            bando_id, skill_elapsed, new_attempt, e,
        )
        _set_error_state(sb, bando_id, current_attempts, str(e))
        return False
    skill_elapsed = time.monotonic() - skill_started
    logger.info(
        "[bandi/skill/{}] skill OK in {:.1f}s livello={} is_valid={} rejection={}",
        bando_id,
        skill_elapsed,
        payload.get("livello"),
        (payload.get("validation") or {}).get("is_valid_bando"),
        (payload.get("validation") or {}).get("rejection_category"),
    )

    # 4) Persisti payload — derive_state interno decide stato finale (confirmed/rejected/refuted)
    logger.info("[bandi/skill/{}] step 4/4 persisting payload + state derivation", bando_id)
    try:
        update_bando_from_payload(sb, bando_id, payload)
    except Exception as e:
        logger.exception("[bandi/skill/{}] update DB FALLITO: {}", bando_id, e)
        _set_error_state(sb, bando_id, current_attempts, f"db update: {str(e)[:480]}")
        return False

    # v4: niente piu' _denormalize_bando_lookups — la skill emette gia'
    # `programma`, `modalita_erogazione`, `codici_ateco` normalizzati.

    total_elapsed = time.monotonic() - enrich_started
    logger.info(
        "[bandi/skill/{}] DONE in {:.1f}s slug={}",
        bando_id, total_elapsed, payload.get("slug"),
    )
    return True


def _skill_concurrency() -> int:
    """Concurrency level per skill enrichment (asyncio.Semaphore).

    Default 3: throughput ~9 bandi/min (vs ~3 sequenziale). Anthropic Opus
    e Firecrawl accettano tranquillamente 3-5 concorrenti senza 429.
    Alzabile a 5-8 via env `BANDI_SKILL_CONCURRENCY` se rate-limit OK.
    """
    try:
        return max(1, int(os.getenv("BANDI_SKILL_CONCURRENCY", "3")))
    except ValueError:
        return 3


async def run_skill_enrichment_batch(batch_size: int = 10) -> dict[str, int]:
    """Drena la coda della skill enrichment FINO A ESAURIMENTO.

    NON e' piu' un "batch one-shot" con cap fisso: ogni round fa SELECT di
    `batch_size` record (chunk per non scaricare migliaia di righe in memoria),
    processa in parallelo (Semaphore=BANDI_SKILL_CONCURRENCY), e poi ri-SELECT
    finche' la coda e' vuota. Lo scraper in parallelo puo' aggiungere nuovi
    candidati: il loop li raccoglie nel round successivo.

    Selezione v4:
      - `state = 'discovered'` (oppure 'error' per retry)
      - `attempts < BANDI_SKILL_MAX_ATTEMPTS`
    Ordinati per `ultimo_scraping_at ASC` (FIFO, priorita' ai bandi piu' vecchi).

    Restituisce i contatori cumulativi su tutti i round.
    """
    sb = get_bandi_supabase()
    max_att = _max_attempts()
    concurrency = _skill_concurrency()
    overall_started = time.monotonic()
    counters = {"processed": 0, "confirmed": 0, "rejected": 0, "refuted": 0, "error": 0}
    rounds = 0

    logger.info(
        "[bandi/skill] DRAIN START chunk={} max_attempts={} concurrency={} ordering=ultimo_scraping_at:asc",
        batch_size, max_att, concurrency,
    )

    sem = asyncio.Semaphore(concurrency)

    while True:
        rounds += 1
        round_started = time.monotonic()
        try:
            res = (
                sb.table("bando")
                .select(_BANDO_CORE_COLUMNS)
                .in_("state", [BandoState.DISCOVERED, BandoState.ERROR])
                .lt("attempts", max_att)
                .order("ultimo_scraping_at", desc=False)
                .limit(batch_size)
                .execute()
            )
        except Exception as e:
            logger.exception("[bandi/skill] SELECT round {} fallito: {}", rounds, e)
            break

        rows = res.data or []
        if not rows:
            if rounds == 1:
                logger.info(
                    "[bandi/skill] DRAIN coda vuota all'avvio: nessun bando in state IN "
                    "(discovered,error) con attempts<{}",
                    max_att,
                )
            else:
                logger.info("[bandi/skill] DRAIN coda esaurita dopo {} round", rounds - 1)
            break

        # Breakdown stati pre-round
        state_breakdown: dict[str, int] = {}
        for r in rows:
            s = r.get("state") or "?"
            state_breakdown[s] = state_breakdown.get(s, 0) + 1
        round_total = len(rows)
        logger.info(
            "[bandi/skill] === ROUND {} === {} bandi ({}) | concurrency={} (totale gia' processati={})",
            rounds, round_total,
            " + ".join(f"{n} {s}" for s, n in sorted(state_breakdown.items())),
            concurrency, counters["processed"],
        )

        round_progress = {"completed": 0}

        async def _process_bando(idx: int, bando: dict[str, Any]) -> None:
            bando_id = bando.get("id")
            async with sem:
                counters["processed"] += 1
                logger.info(
                    "[bandi/skill] >>> START round={} {}/{} bando_id={} state={} attempts={}/{} (in-flight={}/{})",
                    rounds, idx, round_total, bando_id, bando.get("state"),
                    int(bando.get("attempts") or 0), max_att,
                    concurrency - sem._value, concurrency,
                )
                await _enrich_one(sb, bando)
                try:
                    cur = sb.table("bando").select("state, slug").eq("id", bando_id).single().execute()
                    data = cur.data or {}
                    new_state = data.get("state")
                    new_slug = data.get("slug")
                except Exception:
                    logger.exception("[bandi/skill] re-read state fallito bando_id={}", bando_id)
                    new_state = BandoState.ERROR
                    new_slug = None
                if new_state == BandoState.CONFIRMED:
                    counters["confirmed"] += 1
                elif new_state == BandoState.REJECTED:
                    counters["rejected"] += 1
                elif new_state == BandoState.REFUTED:
                    counters["refuted"] += 1
                else:
                    counters["error"] += 1
                round_progress["completed"] += 1
                logger.info(
                    "[bandi/skill] <<< END round={} {}/{} ({}/{} round) bando_id={} -> state={} slug={} | totale={}",
                    rounds, idx, round_total, round_progress["completed"], round_total,
                    bando_id, new_state, new_slug, counters,
                )

        await asyncio.gather(*[_process_bando(i, b) for i, b in enumerate(rows, start=1)])

        round_elapsed = time.monotonic() - round_started
        logger.info(
            "[bandi/skill] === ROUND {} DONE in {:.1f}s ({} bandi, totale processati={}) ===",
            rounds, round_elapsed, round_total, counters["processed"],
        )

        # Safety: se il round non ha completato nessuno (es. tutti gli enrich
        # hanno crashato), evita loop infinito.
        if round_progress["completed"] == 0:
            logger.warning(
                "[bandi/skill] DRAIN round {} non ha completato nessun bando: stop",
                rounds,
            )
            break

    overall_elapsed = time.monotonic() - overall_started
    rate_per_min = (counters["processed"] / overall_elapsed * 60) if overall_elapsed > 0 else 0
    logger.info(
        "[bandi/skill] DRAIN DONE in {:.1f}s, {} round, {:.1f} bandi/min, concurrency={} | counters={}",
        overall_elapsed, rounds, rate_per_min, concurrency, counters,
    )
    return counters


# ---------------------------------------------------------------------------
# Pipeline composite (usate dal sender)
# ---------------------------------------------------------------------------

async def _run_parallel_scraper_skill(
    scraper_fn: "callable", scraper_label: str
) -> None:
    """Esegue scraper subprocess (via `asyncio.to_thread`) IN PARALLELO alla
    skill enrichment batch.

    La state machine `state` e' di proprieta' della skill: lo scraper UPDATE
    tocca solo titolo/descrizione/raw_data/ultimo_scraping_at — nessuna race
    su `state`/`state_detail`/`attempts`/`slug`/editorial fields.

    Se uno dei due task solleva, l'altro continua (return_exceptions=True):
    cosi' un eventuale errore scraper non blocca il drain skill (e viceversa).
    """
    logger.info("[bandi/pipeline] {} + skill batch IN PARALLELO", scraper_label)
    scraper_task = asyncio.create_task(asyncio.to_thread(scraper_fn))
    skill_task = asyncio.create_task(run_skill_enrichment_batch(_batch_size()))

    results = await asyncio.gather(scraper_task, skill_task, return_exceptions=True)
    scraper_result, skill_result = results

    if isinstance(scraper_result, Exception):
        logger.exception(
            "[bandi/pipeline] {} FALLITO: {}", scraper_label, scraper_result,
        )
    else:
        logger.info("[bandi/pipeline] {} -> rc={}", scraper_label, scraper_result)

    if isinstance(skill_result, Exception):
        logger.exception(
            "[bandi/pipeline] skill batch FALLITO: {}", skill_result,
        )
    else:
        logger.info("[bandi/pipeline] skill batch -> counters={}", skill_result)


def run_full_pipeline() -> None:
    """Pipeline 4x/giorno: scraper full ∥ skill enrichment batch (PARALLELI).

    v4: rimossa fase intermedia `run_ai_worker_drain()` (worker AI deprecato,
    la skill e' ora autoritativa sulla classificazione). Scraper + skill
    girano in parallelo via `asyncio.gather` — la skill drena i bandi gia'
    in coda (state='discovered'/'error') mentre lo scraper scopre quelli
    nuovi che entreranno nel batch successivo.
    """
    logger.info("[bandi] pipeline FULL: start")
    asyncio.run(_run_parallel_scraper_skill(run_scraper_full, "scraper-full"))
    logger.info("[bandi] pipeline FULL: done")


def run_pending_pipeline() -> None:
    """Pipeline pending (1x/4h): retry scraper ∥ skill enrichment batch (PARALLELI)."""
    logger.info("[bandi] pipeline PENDING: start")
    asyncio.run(_run_parallel_scraper_skill(run_scraper_pending, "scraper-pending"))
    logger.info("[bandi] pipeline PENDING: done")


def run_skill_only_pipeline() -> None:
    """Pipeline 30min: solo skill backfill (smaltisce lo storico)."""
    logger.info("[bandi] pipeline skill-only: start")
    asyncio.run(run_skill_enrichment_batch(_batch_size()))
    logger.info("[bandi] pipeline skill-only: done")


def _batch_size() -> int:
    try:
        return int(os.getenv("BANDI_SKILL_BATCH_SIZE", "10"))
    except ValueError:
        return 10
