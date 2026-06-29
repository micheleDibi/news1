"""
Dataclass/Pydantic models che rispecchiano le tabelle PostgreSQL esistenti.
Questi modelli sono di sola lettura rispetto alle tabelle di riferimento:
scraper e AI non possono inserire record nelle tabelle di lookup.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Tabelle di riferimento (READ-ONLY per scraper e AI)
# ---------------------------------------------------------------------------


class Fonte(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    categoria_programma_id: Optional[int] = None
    tipologia_programma_id: Optional[int] = None
    tipo_link: Optional[str] = None
    titolo: Optional[str] = None
    link: Optional[str] = None
    formato_link: Optional[str] = None
    attivo: Optional[bool] = None
    note_aggiuntive: Optional[str] = None
    # Campi aggiunti dalla migrazione
    stato_processing: str = "ready"
    retry_count: int = 0
    max_retry: int = 3
    next_retry_at: Optional[datetime] = None
    last_error_type: Optional[str] = None
    last_error_message: Optional[str] = None
    last_error_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CategoriaProgramma(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Bando(BaseModel):
    """Mirror Pydantic della tabella `bando` post-migrazione v4.

    Vedi `backend/sql/bando_v4_collapse.sql` per lo schema autoritativo.
    Campi v3 (stato_bando, importo, importo_numerico, is_bando_confermato,
    ai_processing_*, ai_last_attempt_at) rimossi.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    fonte_id: Optional[int] = None
    hash_bando: Optional[str] = None
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    codice_bando: Optional[str] = None
    fondo: Optional[str] = None
    data_pubblicazione: Optional[datetime] = None
    data_apertura: Optional[datetime] = None
    data_scadenza: Optional[datetime] = None
    link_bando: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None
    tipologia_bando_id: Optional[int] = None
    modalita_erogazione_id: Optional[int] = None
    programma_id: Optional[int] = None
    data_extra: Optional[dict[str, Any]] = None
    primo_scraping_at: Optional[datetime] = None
    ultimo_scraping_at: Optional[datetime] = None
    # Campi retry / processing fonte
    stato_processing: str = "ready"
    retry_count: int = 0
    max_retry: int = 3
    next_retry_at: Optional[datetime] = None
    last_error_type: Optional[str] = None
    last_error_message: Optional[str] = None
    last_error_at: Optional[datetime] = None
    # v4 — state machine
    state: str = "discovered"
    state_detail: dict[str, Any] = {}
    state_updated_at: Optional[datetime] = None
    attempts: int = 0
    # v4 — editorial (skill-side)
    slug: Optional[str] = None
    source_url: Optional[str] = None
    livello: Optional[str] = None
    titolo_breve: Optional[str] = None
    descrizione_breve: Optional[str] = None
    contenuto: Optional[dict[str, Any]] = None
    date_quotes: dict[str, Any] = {}
    # v4 — classification normalizzata (skill autoritativa)
    tipologia: Optional[str] = None
    programma: Optional[str] = None
    modalita_erogazione: Optional[str] = None
    area_geografica: Optional[str] = None
    tematica: Optional[list[str]] = None
    beneficiari: Optional[list[str]] = None
    codici_ateco: Optional[list[str]] = None
    # v4 — importi/ente/link
    importo_totale_eur: Optional[int] = None
    importo_max_per_progetto_eur: Optional[int] = None
    ente_erogatore: Optional[str] = None
    link_candidatura: Optional[str] = None
    link_candidatura_source: Optional[str] = None
    allegati: Optional[list[dict[str, Any]]] = None
    # OCR (non v4, ma ancora attivo)
    ocr_required: bool = False
    ocr_status: str = "not_required"
    ocr_last_attempt_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Beneficiario(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    codice_fiscale: Optional[str] = None
    tipo: Optional[str] = None
    creato_il: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Tabelle operative
# ---------------------------------------------------------------------------

class BandoBeneficiari(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bando_id: int
    beneficiario_id: int
    creato_il: Optional[datetime] = None


class ScrapingLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: Optional[UUID] = None
    fonte_id: Optional[int] = None
    parent_log_id: Optional[int] = None
    tipo_operazione: Optional[str] = None
    url_processato: Optional[str] = None
    request_params: Optional[dict[str, Any]] = None
    stato: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    tempo_esecuzione_ms: Optional[int] = None
    bandi_trovati: Optional[int] = None
    bandi_nuovi: Optional[int] = None
    bandi_aggiornati: Optional[int] = None
    bandi_invariati: Optional[int] = None
    pagine_crawlate: Optional[int] = None
    ai_calls_count: int = 0
    ai_tokens_used: int = 0
    errori: Optional[int] = None
    errore_tipo: Optional[str] = None
    errore_messaggio: Optional[str] = None
    errore_stack: Optional[str] = None
    response_summary: Optional[dict[str, Any]] = None
    note: Optional[str] = None


class ScrapingErroreDefinitivo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: Optional[UUID] = None
    scraping_log_id: Optional[int] = None
    fonte_id: Optional[int] = None
    bando_id: Optional[int] = None
    entity_type: str
    entity_url: Optional[str] = None
    errore_tipo: str
    errore_messaggio: Optional[str] = None
    errore_stack: Optional[str] = None
    http_status_code: Optional[int] = None
    retry_count: int = 0
    contesto: Optional[dict[str, Any]] = None
    creato_il: Optional[datetime] = None
    risolto: bool = False
    risolto_il: Optional[datetime] = None
    note_risoluzione: Optional[str] = None


# v4: AiJobQueue rimossa. Il worker AI Opus pre-skill e' stato deprecato.
# La tabella `ai_job_queue` resta nel DB (vuota) per audit, drop in futura cleanup.


class OcrJobQueue(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_uuid: UUID
    bando_id: Optional[int] = None
    fonte_id: Optional[int] = None
    url_documento: str
    stato: str = "queued"
    tentativi: int = 0
    max_tentativi: int = 3
    disponibile_da: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errore_tipo: Optional[str] = None
    errore_messaggio: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    testo_estratto: Optional[str] = None
    metadati_ocr: Optional[dict[str, Any]] = None
    creato_il: Optional[datetime] = None
    aggiornato_il: Optional[datetime] = None
