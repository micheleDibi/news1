"""Orchestratore della pipeline bandi.

Due fasi compongono il flusso end-to-end:

1. **Scraper** (sotto-progetto Python autonomo `Scraper-gerarchico-bandi-OpenCoesione-Backend-Python`):
   invocato come subprocess (`python -m app.scheduler run-now` / `run-pending-now`)
   con `cwd=BANDI_SCRAPER_DIR`. Lo scraper popola/aggiorna la tabella `bando`
   su Supabase B + esegue la classificazione AI (OpenAI gpt-4o-mini) sui campi
   relazionali (tipologia, modalita_erogazione, programma, regioni, settori,
   beneficiari, codici_ateco) usando dizionari chiusi.

2. **Skill SEO enrichment** (`bandi-seo-enricher`): in-process via Claude Agent SDK
   (vedi `bandi_skill_runner.py`). Per ogni bando che ha completato la fase AI ma
   non ha ancora contenuto editoriale (`skill_processing_status IN ('queued','failed')`):
   - costruisce `hint_dominio` dai dati relazionali gia' presenti nel DB,
   - invoca la skill che produce JSON validato (livello flash_bando o guida_bando),
   - persiste l'output nelle colonne SEO del bando (vedi
     `backend/sql/bando_alter_seo_fields.sql`).

I bandi non vengono cancellati ne' duplicati: la skill arricchisce il record
esistente. In caso di errore terminale (`skill_attempts >= BANDI_SKILL_MAX_ATTEMPTS`)
il bando resta in stato `failed` e va revisionato manualmente.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
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


def _run_scraper_module(module: str, args: list[str], label: str) -> int:
    """Esegue `python -m <module> [args...]` con cwd e env dello scraper."""
    cmd = [_scraper_python(), "-m", module, *args]
    logger.info("[bandi/{}] start: cwd={} cmd={}", label, _scraper_dir(), " ".join(cmd))
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=_scraper_dir(),
            env=_scraper_subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        logger.error("[bandi/{}] python non trovato: {}", label, e)
        return -1

    elapsed = time.monotonic() - started
    # Tronca stdout/stderr per non saturare il log
    stdout_tail = (result.stdout or "")[-2000:]
    stderr_tail = (result.stderr or "")[-2000:]
    logger.info(
        "[bandi/{}] done in {:.1f}s rc={}\nSTDOUT(tail)={}\nSTDERR(tail)={}",
        label, elapsed, result.returncode, stdout_tail, stderr_tail,
    )
    return result.returncode


def run_scraper_full() -> int:
    """Esegue una scan completa di tutte le fonti attive (cli `run`).

    Lo scraping accoda i bandi nella `ai_job_queue` (campo `ai_processing_required=true`)
    ma NON processa la coda — questo lo fa `run_ai_worker_drain()`.
    """
    args: list[str] = ["run"]
    limit = os.getenv("BANDI_SCRAPER_RUN_LIMIT")
    if limit:
        args += ["--limit", str(limit)]
    return _run_scraper_module("app.cli", args, "scraper-full")


def run_scraper_pending() -> int:
    """Retry sulle fonti/bandi in coda `pending` (cli `run-pending`)."""
    return _run_scraper_module("app.cli", ["run-pending"], "scraper-pending")


def run_ai_worker_drain() -> int:
    """Processa la `ai_job_queue` fino a svuotarla (classifica bandi via OpenAI).

    Necessario tra scraping e skill enrichment: lo scraper accoda i job AI ma il
    worker dedicato e' separato. Solo dopo questo passaggio i bandi passano a
    `ai_processing_status='completed'` e diventano selezionabili dalla skill.
    """
    return _run_scraper_module(
        "app.ai.run_ai_worker",
        ["--limit", "10", "--drain-all"],
        "ai-worker-drain",
    )


# ---------------------------------------------------------------------------
# Fase 2 — skill enrichment
# ---------------------------------------------------------------------------

# Campi del bando rilevanti da passare come hint alla skill.
_BANDO_CORE_COLUMNS = (
    "id, titolo, descrizione, codice_bando, fondo, link_bando, "
    "stato_bando, data_pubblicazione, data_apertura, data_scadenza, "
    "importo, importo_numerico, "
    "tipologia_bando_id, modalita_erogazione_id, programma_id, "
    "ai_processing_status, skill_processing_status, skill_attempts, "
    "ultimo_scraping_at, raw_data, data_extra"
)


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
    if bando.get("importo"):
        hint["importo_grezzo"] = bando["importo"]
    if bando.get("importo_numerico") is not None:
        hint["importo_numerico_grezzo"] = bando["importo_numerico"]

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


def update_bando_from_payload(sb, bando_id: int, payload: dict[str, Any]) -> None:
    """Persiste il JSON output della skill nelle colonne di `bando`.

    Verdetto autoritativo: la skill (fase 2) sovrascrive `is_bando_confermato`,
    e — se la data ha source autorevole (PDF/pagina ufficiale) — anche
    `data_scadenza` e `data_pubblicazione`. Per audit, prima della sovrascrittura
    salva i valori precedenti in `raw_data["data_scadenza_pre_skill"]` e
    `raw_data["data_pubblicazione_pre_skill"]`.

    Risolve eventuali collisioni di `slug` aggiungendo suffisso `-{bando_id}`.
    """
    bando_obj = payload.get("bando") or {}
    validation_obj = payload.get("validation") or {}

    is_valid_bando = validation_obj.get("is_valid_bando")
    if not isinstance(is_valid_bando, bool):
        # Retrocompatibilita': vecchi payload senza il blocco validation → assume True.
        is_valid_bando = True

    seo: dict[str, Any] = {
        "slug": payload.get("slug"),
        "seo_livello": payload.get("livello"),
        "seo_titolo": payload.get("titolo"),
        "seo_occhiello": payload.get("occhiello"),
        "seo_descrizione_breve": payload.get("descrizione_breve"),
        "seo_meta_title": payload.get("meta_title"),
        "seo_meta_description": payload.get("meta_description"),
        "seo_contenuto": payload.get("contenuto"),
        "seo_factcheck": payload.get("factcheck_report"),
        "seo_fonti": payload.get("fonti"),
        "seo_validation": validation_obj or None,
        "allegati": payload.get("allegati"),
        "ente_erogatore": _pick(bando_obj, "ente_erogatore"),
        "tipologia_normalizzata": _pick(bando_obj, "tipologia"),
        "area_geografica": _pick(bando_obj, "area_geografica"),
        "tematica": _pick(bando_obj, "tematica"),
        "beneficiari_norm": _pick(bando_obj, "beneficiari"),
        "scadenza_stato": _pick(bando_obj, "scadenza_stato"),
        "importo_totale_eur": _pick(bando_obj, "importo_totale_eur"),
        "importo_max_per_progetto_eur": _pick(bando_obj, "importo_max_per_progetto_eur"),
        "link_candidatura": _pick(bando_obj, "link_candidatura"),
        "riferimento_normativo": _pick(bando_obj, "riferimento_normativo"),
        # Verdetto autoritativo della skill (override fase 1)
        "is_bando_confermato": is_valid_bando,
        "validation_reason": validation_obj.get("validation_reason"),
        "rejection_category": validation_obj.get("rejection_category"),
        # Provenienza delle date (sempre persistite per audit)
        "data_scadenza_source": _pick(bando_obj, "scadenza_source"),
        "data_pubblicazione_source": _pick(bando_obj, "data_pubblicazione_source"),
        # Verifica link candidatura: bool sempre persistito (anche False).
        "link_candidatura_verified": bool(_pick(bando_obj, "link_candidatura_verified")),
    }

    # Sovrascrittura date autoritative: SOLO se la skill ha una source autorevole
    # (PDF o pagina ufficiale). Per inferred/missing manteniamo il valore di fase 1
    # — meglio una buona stima che NULL, e l'ordinamento DESC NULLS LAST nel listing
    # frontend mette in fondo i record senza data.
    scadenza_iso = _pick(bando_obj, "scadenza")
    scadenza_source = _pick(bando_obj, "scadenza_source")
    pubblicazione_iso = _pick(bando_obj, "data_pubblicazione")
    pubblicazione_source = _pick(bando_obj, "data_pubblicazione_source")

    will_override_scadenza = (
        scadenza_iso and scadenza_source in _SCADENZA_OVERRIDE_SOURCES
    )
    will_override_pubblicazione = (
        pubblicazione_iso and pubblicazione_source in _SCADENZA_OVERRIDE_SOURCES
    )

    if will_override_scadenza or will_override_pubblicazione:
        existing = _read_existing_for_audit(sb, bando_id)
        merged_raw: dict[str, Any] | None = None
        if existing is not None:
            prev_raw = existing.get("raw_data") or {}
            if not isinstance(prev_raw, dict):
                prev_raw = {}
            merged_raw = dict(prev_raw)
            if will_override_scadenza:
                prev_scadenza = existing.get("data_scadenza")
                if prev_scadenza and str(prev_scadenza) != str(scadenza_iso):
                    merged_raw["data_scadenza_pre_skill"] = str(prev_scadenza)
                    merged_raw["data_scadenza_pre_skill_source"] = "scraper_fallback"
            if will_override_pubblicazione:
                prev_pubblicazione = existing.get("data_pubblicazione")
                if prev_pubblicazione and str(prev_pubblicazione) != str(pubblicazione_iso):
                    merged_raw["data_pubblicazione_pre_skill"] = str(prev_pubblicazione)
                    merged_raw["data_pubblicazione_pre_skill_source"] = "scraper_fallback"
        if merged_raw is not None:
            seo["raw_data"] = merged_raw
        if will_override_scadenza:
            seo["data_scadenza"] = scadenza_iso
        if will_override_pubblicazione:
            seo["data_pubblicazione"] = pubblicazione_iso

    # Rimuovi solo i None che NON sono verdetti booleani / campi di flag espliciti.
    # is_bando_confermato e link_candidatura_verified DEVONO essere persistiti anche
    # quando False — sono il verdetto della skill, non assenza di dato.
    always_keep = {"is_bando_confermato", "link_candidatura_verified"}
    seo_clean = {k: v for k, v in seo.items() if (v is not None or k in always_keep)}

    if "slug" not in seo_clean or not seo_clean.get("slug"):
        seo_clean["slug"] = _slugify(seo.get("seo_titolo") or "") + f"-{bando_id}"

    try:
        sb.table("bando").update(seo_clean).eq("id", bando_id).execute()
    except Exception as e:
        msg = str(e)
        if "23505" in msg or "duplicate key" in msg.lower() or "unique" in msg.lower():
            # Collisione slug: aggiungi suffisso e ritenta una volta
            original_slug = seo_clean.get("slug", _slugify(""))
            seo_clean["slug"] = f"{original_slug}-{bando_id}"
            logger.warning(
                "[bandi] slug collision bando_id={} → retry con slug={}",
                bando_id, seo_clean["slug"],
            )
            sb.table("bando").update(seo_clean).eq("id", bando_id).execute()
        else:
            raise


def _denormalize_bando_lookups(sb, bando_id: int, bando: dict[str, Any]) -> None:
    """Popola le colonne denormalizzate del bando per i filtri del frontend.

    - `programma_nome` da lookup `programmi` via `programma_id`
    - `modalita_erogazione_nome` da lookup `modalita_erogazione` via `modalita_erogazione_id`
    - `codici_ateco_norm` (TEXT[]) da join `bando_codici_ateco` → `codici_ateco`

    Idempotente: i campi sono ricalcolati a ogni chiamata. Best-effort: errori sulle
    singole query non bloccano l'enrichment (loggati come warning, campo lasciato `None`).
    """
    updates: dict[str, Any] = {}

    programma_id = bando.get("programma_id")
    if programma_id:
        names = _safe_select_names(sb, "programmi", [programma_id])
        if names:
            updates["programma_nome"] = names[0]

    modalita_id = bando.get("modalita_erogazione_id")
    if modalita_id:
        names = _safe_select_names(sb, "modalita_erogazione", [modalita_id])
        if names:
            updates["modalita_erogazione_nome"] = names[0]

    ateco_ids = _try_junction_lookup(sb, "bando_codici_ateco", "codice_ateco_id", bando_id)
    if ateco_ids:
        try:
            res = sb.table("codici_ateco").select("codice, descrizione").in_("id", ateco_ids).execute()
            codici = []
            seen: set[str] = set()
            for r in res.data or []:
                code = (r.get("codice") or "").strip()
                desc = (r.get("descrizione") or "").strip()
                if not code:
                    continue
                value = f"{code} — {desc}" if desc else code
                if value in seen:
                    continue
                seen.add(value)
                codici.append(value)
            if codici:
                updates["codici_ateco_norm"] = codici
        except Exception as e:
            logger.warning("[bandi/denorm] lookup codici_ateco failed bando_id={}: {}", bando_id, e)

    if not updates:
        return
    try:
        sb.table("bando").update(updates).eq("id", bando_id).execute()
    except Exception as e:
        logger.warning("[bandi/denorm] UPDATE failed bando_id={} updates={}: {}", bando_id, list(updates), e)


def _max_attempts() -> int:
    try:
        return int(os.getenv("BANDI_SKILL_MAX_ATTEMPTS", "3"))
    except ValueError:
        return 3


async def _enrich_one(sb, bando: dict[str, Any]) -> bool:
    """Arricchisce un singolo bando. Ritorna True se completato, False altrimenti."""
    bando_id = bando["id"]
    link = bando.get("link_bando")
    if not link:
        logger.warning("[bandi/skill] bando_id={} salto: link_bando assente", bando_id)
        sb.table("bando").update({
            "skill_processing_status": "skipped",
            "skill_last_error": "link_bando assente",
        }).eq("id", bando_id).execute()
        return False

    # 1) marca processing
    sb.table("bando").update({"skill_processing_status": "processing"}).eq("id", bando_id).execute()

    # 2) costruisci hint
    hint = build_hint_from_bando(sb, bando)

    # 3) invoca skill
    try:
        payload = await run_bandi_skill(link_bando=link, hint=hint)
    except Exception as e:
        attempts = (bando.get("skill_attempts") or 0) + 1
        logger.exception("[bandi/skill] bando_id={} skill fallita (attempt {}): {}", bando_id, attempts, e)
        sb.table("bando").update({
            "skill_processing_status": "failed",
            "skill_last_error": str(e)[:500],
            "skill_attempts": attempts,
        }).eq("id", bando_id).execute()
        return False

    # 4) persisti payload + mark completed
    try:
        update_bando_from_payload(sb, bando_id, payload)
    except Exception as e:
        attempts = (bando.get("skill_attempts") or 0) + 1
        logger.exception("[bandi/skill] bando_id={} update DB fallito: {}", bando_id, e)
        sb.table("bando").update({
            "skill_processing_status": "failed",
            "skill_last_error": f"db update: {str(e)[:480]}",
            "skill_attempts": attempts,
        }).eq("id", bando_id).execute()
        return False

    # 5) denormalizza lookup (programma/modalita/ATECO) per i filtri del frontend.
    # Best-effort: errori qui non invalidano l'enrichment.
    _denormalize_bando_lookups(sb, bando_id, bando)

    sb.table("bando").update({
        "skill_processing_status": "completed",
        "skill_processing_at": datetime.now(timezone.utc).isoformat(),
        "skill_last_error": None,
    }).eq("id", bando_id).execute()
    logger.info("[bandi/skill] bando_id={} arricchito OK (slug={})", bando_id, payload.get("slug"))
    return True


async def run_skill_enrichment_batch(batch_size: int = 10) -> dict[str, int]:
    """Arricchisce fino a `batch_size` bandi pronti per la skill.

    Selezione:
      - `ai_processing_status='completed'` (classificazione AI dello scraper terminata)
      - `skill_processing_status IN ('queued','failed')`
      - `skill_attempts < BANDI_SKILL_MAX_ATTEMPTS`
    Ordinati per `ultimo_scraping_at DESC` (priorita' ai bandi piu' freschi).

    Esegue serialmente (1 skill alla volta) per controllare il consumo token Claude.
    Restituisce un dict con i contatori `{processed, completed, failed, skipped}`.
    """
    sb = get_bandi_supabase()
    max_att = _max_attempts()

    logger.info("[bandi/skill] batch start: size={} max_attempts={}", batch_size, max_att)
    try:
        # Fase 1 conclusa = AI completata OPPURE non necessaria (deterministico bastava).
        # Senza `not_required` perderemmo i bandi con matching pulito.
        res = (
            sb.table("bando")
            .select(_BANDO_CORE_COLUMNS)
            .in_("ai_processing_status", ["completed", "not_required"])
            .in_("skill_processing_status", ["queued", "failed"])
            .lt("skill_attempts", max_att)
            .order("ultimo_scraping_at", desc=True)
            .limit(batch_size)
            .execute()
        )
    except Exception as e:
        logger.exception("[bandi/skill] SELECT batch fallito: {}", e)
        return {"processed": 0, "completed": 0, "failed": 0, "skipped": 0}

    rows = res.data or []
    counters = {"processed": 0, "completed": 0, "failed": 0, "skipped": 0}
    if not rows:
        logger.info("[bandi/skill] nessun bando pronto per enrichment")
        return counters

    for bando in rows:
        counters["processed"] += 1
        ok = await _enrich_one(sb, bando)
        # Ri-leggi lo status per distinguere completed/skipped/failed
        try:
            cur = sb.table("bando").select("skill_processing_status").eq("id", bando["id"]).single().execute()
            status = (cur.data or {}).get("skill_processing_status")
        except Exception:
            status = "completed" if ok else "failed"
        if status == "completed":
            counters["completed"] += 1
        elif status == "skipped":
            counters["skipped"] += 1
        else:
            counters["failed"] += 1

    logger.info("[bandi/skill] batch done: {}", counters)
    return counters


# ---------------------------------------------------------------------------
# Pipeline composite (usate dal sender)
# ---------------------------------------------------------------------------

def run_full_pipeline() -> None:
    """Pipeline 4x/giorno: scraper full → worker AI (drain) → skill enrichment batch."""
    logger.info("[bandi] pipeline full: start")
    run_scraper_full()
    run_ai_worker_drain()
    asyncio.run(run_skill_enrichment_batch(_batch_size()))
    logger.info("[bandi] pipeline full: done")


def run_pending_pipeline() -> None:
    """Pipeline pending (1x/4h): retry scraper → worker AI (drain) → skill enrichment batch."""
    logger.info("[bandi] pipeline pending: start")
    run_scraper_pending()
    run_ai_worker_drain()
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
