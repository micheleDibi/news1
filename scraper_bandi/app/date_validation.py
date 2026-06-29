"""Validation helpers per date estratte da LLM (preprocess + bando_resolver + enricher).

Triple-gate sulle date:
  1. ISO format check (YYYY-MM-DD)
  2. Source autoritativo (official_pdf | official_page)
  3. Quote substring del markdown E data nella quote coincide con declared

Le date che falliscono il gate vengono coercite a None.
Originariamente in enricher.py (v7); estratto qui per riuso da preprocess v2.
"""
from __future__ import annotations

import re
from datetime import date as date_cls
from typing import Any

from .logger import logger


_AUTHORITATIVE_SOURCES = {"official_pdf", "official_page"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATE_IN_QUOTE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})"                                  # ISO
    r"|(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"               # DD/MM/YYYY o DD-MM-YYYY o DD.MM.YYYY
    r"|(\d{1,2})\s+(gen(?:naio)?|feb(?:braio)?|mar(?:zo)?|apr(?:ile)?|mag(?:gio)?|giu(?:gno)?|"
    r"lug(?:lio)?|ago(?:sto)?|set(?:tembre)?|ott(?:obre)?|nov(?:embre)?|dic(?:embre)?)\s+(\d{4})",  # 31 dicembre 2026
    re.IGNORECASE,
)

_MONTH_IT = {
    "gen": 1, "gennaio": 1,
    "feb": 2, "febbraio": 2,
    "mar": 3, "marzo": 3,
    "apr": 4, "aprile": 4,
    "mag": 5, "maggio": 5,
    "giu": 6, "giugno": 6,
    "lug": 7, "luglio": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "settembre": 9,
    "ott": 10, "ottobre": 10,
    "nov": 11, "novembre": 11,
    "dic": 12, "dicembre": 12,
}


def parse_iso(s: str | None) -> date_cls | None:
    if not s or not _ISO_DATE_RE.match(s):
        return None
    try:
        return date_cls.fromisoformat(s)
    except ValueError:
        return None


def extract_date_from_quote(quote: str) -> date_cls | None:
    """Cerca UNA data nella quote (ISO, DD/MM/YYYY, '31 dicembre 2026'). Prima match."""
    m = _DATE_IN_QUOTE_RE.search(quote)
    if not m:
        return None
    if m.group(1):  # ISO
        return parse_iso(m.group(1))
    if m.group(2):  # DD/MM/YYYY
        try:
            return date_cls(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            return None
    if m.group(5):  # 31 dicembre 2026
        month_key = m.group(6).lower()
        month = _MONTH_IT.get(month_key) or _MONTH_IT.get(month_key[:3])
        if not month:
            return None
        try:
            return date_cls(int(m.group(7)), month, int(m.group(5)))
        except ValueError:
            return None
    return None


def validate_date_candidate(
    candidate: dict[str, Any] | None,
    html_text: str,
    bando_id: Any,
    label: str,
    log_prefix: str = "date",
) -> date_cls | None:
    """Triple-gate sulla candidata date emessa dal LLM.

    Ritorna la data parsed se passa, altrimenti None.
    Argomenti:
      candidate: {date: ISO, source: enum, quote: str} dal tool_use
      html_text: markdown contro cui verificare substring (richiesto)
      bando_id: per logging
      label: 'pubblicazione' | 'apertura' | 'scadenza' per logging
      log_prefix: prefix nei log debug (es. 'preprocess/date' o 'enricher/date')
    """
    if not candidate or not isinstance(candidate, dict):
        return None
    raw_date = candidate.get("date")
    source = candidate.get("source") or ""
    quote = candidate.get("quote") or ""

    if not raw_date or not isinstance(raw_date, str):
        return None
    parsed = parse_iso(raw_date)
    if parsed is None:
        logger.debug("[{}] bando_id={} {} date non ISO: {!r}", log_prefix, bando_id, label, raw_date)
        return None
    if source not in _AUTHORITATIVE_SOURCES:
        logger.debug("[{}] bando_id={} {} source non autoritativa: {!r}", log_prefix, bando_id, label, source)
        return None
    if not quote or not isinstance(quote, str):
        logger.debug("[{}] bando_id={} {} quote vuota", log_prefix, bando_id, label)
        return None
    if quote.strip().lower() not in (html_text or "").lower():
        logger.debug("[{}] bando_id={} {} quote NON substring del markdown", log_prefix, bando_id, label)
        return None
    quote_date = extract_date_from_quote(quote)
    if quote_date != parsed:
        logger.debug(
            "[{}] bando_id={} {} mismatch quote_date={} vs declared={}",
            log_prefix, bando_id, label, quote_date, parsed,
        )
        return None
    return parsed


def check_dates_coherence(
    pub: date_cls | None,
    apt: date_cls | None,
    scad: date_cls | None,
) -> bool:
    """True se l'ordine pub <= apt <= scad e' rispettato tra le date non-None.
    False se almeno una coppia viola l'ordine.
    """
    if pub and apt and pub > apt:
        return False
    if apt and scad and apt > scad:
        return False
    if pub and scad and pub > scad:
        return False
    return True


def reconcile_stato_bando(
    stato_llm: str | None,
    data_apertura: date_cls | None,
    data_scadenza: date_cls | None,
    today: date_cls | None = None,
) -> str | None:
    """Reconciliation guard data-driven.

    Forza:
      - data_scadenza < today -> 'chiuso' (ignora LLM)
      - data_apertura > today -> 'in apertura prossimamente'
      - stato_llm in ('aperto','chiuso','in apertura prossimamente') -> ritorna tale
      - stato_llm == 'unknown' -> None (NULL in DB)
      - altrimenti None
    """
    if today is None:
        today = date_cls.today()

    if data_scadenza is not None and data_scadenza < today:
        return "chiuso"
    if data_apertura is not None and data_apertura > today:
        return "in apertura prossimamente"
    if stato_llm in ("aperto", "chiuso", "in apertura prossimamente"):
        return stato_llm
    return None
