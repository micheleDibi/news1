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

ENV vars:
  - BANDI_SCRAPER_DIR        path al sotto-progetto scraper (obbligatoria)
  - BANDI_SCRAPER_PYTHON     interprete python del scraper (default: 'python')
  - BANDI_SCRAPER_TIMEOUT_S  timeout subprocess scraper in s (default: 1800 = 30 min)
  - BANDI_SCRAPER_RUN_LIMIT  limite fonti per ciclo scraper (opzionale)
  - BANDI_SKILL_BATCH_SIZE   bandi per ciclo skill (default: 10)
  - BANDI_SKILL_MAX_ATTEMPTS retry skill (default: 3)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
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


def _run_scraper_module(module: str, args: list[str], label: str) -> int:
    """Esegue `python -m <module> [args...]` con cwd e env dello scraper.

    Lo stdout/stderr e' rediretto a `/tmp/bandi_<label>_<timestamp>.log`
    in line-buffered: e' possibile fare `tail -f` mentre il subprocess gira
    (cosa impossibile con `capture_output=True` che assorbe fino a fine).

    Su timeout (`BANDI_SCRAPER_TIMEOUT_S`, default 30 min) il subprocess e' killato
    e la funzione ritorna rc=-2.
    """
    cmd = [_scraper_python(), "-m", module, *args]
    timeout = _scraper_timeout_s()
    log_path = f"/tmp/bandi_{label}_{int(time.time())}.log"
    logger.info(
        "[bandi/{}] start: cwd={} cmd={} log={} timeout={}s",
        label, _scraper_dir(), " ".join(cmd), log_path, timeout,
    )
    started = time.monotonic()
    log_fp = open(log_path, "w", buffering=1)
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

        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            elapsed = time.monotonic() - started
            logger.error(
                "[bandi/{}] timeout after {:.0f}s rc=-2 (log={})",
                label, elapsed, log_path,
            )
            return -2
    finally:
        try:
            log_fp.close()
        except Exception:
            pass

    elapsed = time.monotonic() - started
    tail_lines: list[str] = []
    try:
        with open(log_path, "r", errors="replace") as f:
            tail_lines = f.readlines()[-50:]
    except OSError:
        pass
    logger.info(
        "[bandi/{}] done in {:.1f}s rc={} log={}\nTAIL(50 lines)=\n{}",
        label, elapsed, rc, log_path, "".join(tail_lines),
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
        logger.info(
            "[bandi/discovery] depth max raggiunta parent_bando_id={} parent_depth={}: skip {} sublinks",
            parent_bando_id, parent_depth, len(raw_sublinks),
        )
        return 0

    # Limita il numero per parent (defense contro skill rumorosa).
    sublinks = list(raw_sublinks)[:_DISCOVERY_SUBLINKS_PER_PARENT_MAX]
    inserted = 0
    skipped_duplicate = 0
    skipped_error = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for entry in sublinks:
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or "").strip()
        label = (entry.get("label") or "").strip()
        if not url.startswith(("http://", "https://")):
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
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                skipped_duplicate += 1
            else:
                skipped_error += 1
                logger.warning("[bandi/discovery] insert sublink failed url={}: {}", url, e)

    logger.info(
        "[bandi/discovery] parent_bando_id={} depth={}/{} → {} candidati nuovi "
        "(dup={}, err={}, ricevuti={})",
        parent_bando_id, child_depth, _DISCOVERY_MAX_DEPTH,
        inserted, skipped_duplicate, skipped_error, len(sublinks),
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

    if (verifier.get("verdict") or "").lower() == "refuted":
        return BandoState.REFUTED, detail

    scadenza_iso = _pick(bando_obj, "scadenza")
    pubblicazione_iso = _pick(bando_obj, "data_pubblicazione")
    if scadenza_iso and pubblicazione_iso:
        try:
            if date.fromisoformat(pubblicazione_iso) > date.fromisoformat(scadenza_iso):
                detail["rejection_category"] = detail.get("rejection_category") or "not_a_funding_call"
                prior = detail.get("validation_reason") or ""
                detail["validation_reason"] = f"{prior} [orchestrator: inconsistent dates]".strip()
                return BandoState.REJECTED, detail
        except ValueError:
            pass  # formato non-ISO: lascia al CHECK constraint DB

    is_valid_bando = validation_obj.get("is_valid_bando")
    if is_valid_bando is False or validation_obj.get("rejection_category"):
        if not detail.get("rejection_category"):
            detail["rejection_category"] = "not_a_funding_call"
        return BandoState.REJECTED, detail

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

    try:
        sb.table("bando").update(record_clean).eq("id", bando_id).execute()
    except Exception as e:
        msg = str(e)
        if "23505" in msg or "duplicate key" in msg.lower() or "unique" in msg.lower():
            original_slug = record_clean.get("slug") or _slugify(payload.get("titolo") or "")
            record_clean["slug"] = f"{original_slug}-{bando_id}"
            logger.warning(
                "[bandi] slug collision bando_id={} → retry con slug={}",
                bando_id, record_clean["slug"],
            )
            sb.table("bando").update(record_clean).eq("id", bando_id).execute()
        else:
            raise

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

    if not link:
        logger.warning("[bandi/skill] bando_id={} salto: link_bando assente", bando_id)
        sb.table("bando").update({
            "state": BandoState.STALE,
            "state_detail": {"last_error": "link_bando assente", "last_error_at": datetime.now(timezone.utc).isoformat()},
            "state_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bando_id).execute()
        return False

    # 1) Lock soft (ottimistico, no transaction): state='enriching', attempts++
    sb.table("bando").update({
        "state": BandoState.ENRICHING,
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
        "attempts": current_attempts + 1,
    }).eq("id", bando_id).execute()

    # 2) Hint dai dati relazionali (catalogo legacy + junction)
    hint = build_hint_from_bando(sb, bando)

    # 3) Invoca skill
    try:
        payload = await run_bandi_skill(link_bando=link, hint=hint)
    except Exception as e:
        logger.exception("[bandi/skill] bando_id={} skill fallita (attempt {}): {}", bando_id, current_attempts + 1, e)
        _set_error_state(sb, bando_id, current_attempts, str(e))
        return False

    # 4) Persisti payload — derive_state interno decide stato finale (confirmed/rejected/refuted)
    try:
        update_bando_from_payload(sb, bando_id, payload)
    except Exception as e:
        logger.exception("[bandi/skill] bando_id={} update DB fallito: {}", bando_id, e)
        _set_error_state(sb, bando_id, current_attempts, f"db update: {str(e)[:480]}")
        return False

    # v4: niente piu' _denormalize_bando_lookups — la skill emette gia'
    # `programma`, `modalita_erogazione`, `codici_ateco` normalizzati.

    logger.info("[bandi/skill] bando_id={} processato (slug={})", bando_id, payload.get("slug"))
    return True


async def run_skill_enrichment_batch(batch_size: int = 10) -> dict[str, int]:
    """Arricchisce fino a `batch_size` bandi in stato `discovered`.

    Selezione v4:
      - `state = 'discovered'` (oppure 'error' per retry)
      - `attempts < BANDI_SKILL_MAX_ATTEMPTS`
    Ordinati per `ultimo_scraping_at ASC` (FIFO, priorita' ai bandi piu' vecchi non processati).

    Esegue serialmente (1 skill alla volta) per controllare il consumo token Claude.
    Restituisce un dict con i contatori `{processed, confirmed, rejected, refuted, error}`.
    """
    sb = get_bandi_supabase()
    max_att = _max_attempts()

    logger.info("[bandi/skill] batch start: size={} max_attempts={}", batch_size, max_att)
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
        logger.exception("[bandi/skill] SELECT batch fallito: {}", e)
        return {"processed": 0, "confirmed": 0, "rejected": 0, "refuted": 0, "error": 0}

    rows = res.data or []
    counters = {"processed": 0, "confirmed": 0, "rejected": 0, "refuted": 0, "error": 0}
    if not rows:
        logger.info("[bandi/skill] nessun bando pronto per enrichment")
        return counters

    for bando in rows:
        counters["processed"] += 1
        await _enrich_one(sb, bando)
        # Ri-leggi lo state finale per i contatori (confirmed/rejected/refuted/error)
        try:
            cur = sb.table("bando").select("state").eq("id", bando["id"]).single().execute()
            new_state = (cur.data or {}).get("state")
        except Exception:
            new_state = BandoState.ERROR
        if new_state == BandoState.CONFIRMED:
            counters["confirmed"] += 1
        elif new_state == BandoState.REJECTED:
            counters["rejected"] += 1
        elif new_state == BandoState.REFUTED:
            counters["refuted"] += 1
        else:
            counters["error"] += 1

    logger.info("[bandi/skill] batch done: {}", counters)
    return counters


# ---------------------------------------------------------------------------
# Pipeline composite (usate dal sender)
# ---------------------------------------------------------------------------

def run_full_pipeline() -> None:
    """Pipeline 4x/giorno: scraper full → skill enrichment batch.

    v4: rimossa fase intermedia `run_ai_worker_drain()` (worker AI deprecato,
    la skill e' ora autoritativa sulla classificazione).
    """
    logger.info("[bandi] pipeline full: start")
    run_scraper_full()
    asyncio.run(run_skill_enrichment_batch(_batch_size()))
    logger.info("[bandi] pipeline full: done")


def run_pending_pipeline() -> None:
    """Pipeline pending (1x/4h): retry scraper → skill enrichment batch."""
    logger.info("[bandi] pipeline pending: start")
    run_scraper_pending()
    asyncio.run(run_skill_enrichment_batch(_batch_size()))
    logger.info("[bandi] pipeline pending: done")


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
