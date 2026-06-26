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


def _run_scraper_command(args: list[str], label: str) -> int:
    # Usiamo `app.cli` (canonico, supporta --limit) anziche' `app.scheduler`
    # che espone solo run-now / run-pending-now senza argomenti.
    cmd = [_scraper_python(), "-m", "app.cli", *args]
    logger.info("[bandi/{}] start: cwd={} cmd={}", label, _scraper_dir(), " ".join(cmd))
    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=_scraper_dir(),
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
    """Esegue una scan completa di tutte le fonti attive (cli `run`)."""
    args: list[str] = ["run"]
    limit = os.getenv("BANDI_SCRAPER_RUN_LIMIT")
    if limit:
        args += ["--limit", str(limit)]
    return _run_scraper_command(args, "scraper-full")


def run_scraper_pending() -> int:
    """Retry sulle fonti/bandi in coda `pending` (cli `run-pending`)."""
    return _run_scraper_command(["run-pending"], "scraper-pending")


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


def update_bando_from_payload(sb, bando_id: int, payload: dict[str, Any]) -> None:
    """Persiste il JSON output della skill nelle colonne SEO di `bando`.

    Risolve eventuali collisioni di `slug` aggiungendo suffisso `-{bando_id}`.
    """
    bando_obj = payload.get("bando") or {}

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
        "seo_validation": payload.get("validation"),
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
    }
    # Rimuovi i None per non sovrascrivere con NULL
    seo_clean = {k: v for k, v in seo.items() if v is not None}

    if "slug" not in seo_clean:
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
        res = (
            sb.table("bando")
            .select(_BANDO_CORE_COLUMNS)
            .eq("ai_processing_status", "completed")
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
    """Pipeline 4x/giorno: scraper full + skill enrichment batch."""
    logger.info("[bandi] pipeline full: start")
    run_scraper_full()
    asyncio.run(run_skill_enrichment_batch(_batch_size()))
    logger.info("[bandi] pipeline full: done")


def run_pending_pipeline() -> None:
    """Pipeline pending (1x/4h): retry scraper + skill enrichment batch."""
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
