"""
Gestione del session_id per ogni esecuzione dello scraper.
Ogni run riceve un UUID univoco che viene propagato ai log e alle tabelle operative.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog.contextvars

_current_session_id: Optional[uuid.UUID] = None


def new_session_id() -> uuid.UUID:
    """Genera un nuovo UUID per la sessione corrente e lo registra nel context structlog."""
    global _current_session_id
    _current_session_id = uuid.uuid4()
    structlog.contextvars.bind_contextvars(session_id=str(_current_session_id))
    return _current_session_id


def get_session_id() -> Optional[uuid.UUID]:
    """Restituisce il session_id della sessione corrente (None se non ancora inizializzata)."""
    return _current_session_id


def reset_session_id() -> None:
    """Azzera il session_id corrente e pulisce il context structlog (utile nei test)."""
    global _current_session_id
    _current_session_id = None
    structlog.contextvars.clear_contextvars()
