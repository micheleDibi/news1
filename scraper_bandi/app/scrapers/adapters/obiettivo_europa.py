"""Adapter: API JSON Obiettivo Europa → BandoItem.

Schema record API (https://www.obiettivoeuropa.com/api/call/):
  {
    "title": "...",
    "url": "/bandi/slug/",          # relative → BASE_URL + url
    "identifier": "CALL-123",
    "status": "open|closed|forthcoming",
    "opening_date": "YYYY-MM-DD",
    "deadline": "YYYY-MM-DD",
    "deadline_label": "...",
    "deadline_days_left": int,
    "programme_title": "...",
    "programme": "...",
    "action_type_title": "...",
    "type_of_action": "...",
    "description": "...",
    "budget": "...",
    "topics": [...],
    "published": "YYYY-MM-DD",
    "is_forthcoming": bool,
    "pnrr": bool,
    "on_arrival": bool,
    "sectors": [{title}, ...],
    "beneficiaries": [{title}, ...],
    "programs": [{title}, ...],
    "types": [{title}, ...],
    "regions": [{title}, ...],
    "evaluation_procedures": [{title}, ...],
    "ateco_codes": [...]
  }
"""
from __future__ import annotations

from typing import Any

from ..base import BandoItem


_BASE_URL = "https://www.obiettivoeuropa.com"


def _extract_titles(items: list | None) -> list[str]:
    """Estrae solo i 'title' da una lista di tag-object {title: ...}."""
    if not items:
        return []
    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            t = it.get("title")
            if t:
                out.append(str(t))
        elif isinstance(it, str):
            out.append(it)
    return out


def _to_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val)


def to_bando_item(record: dict[str, Any], fonte_id: int) -> BandoItem | None:
    """Converte un record JSON di Obiettivo Europa in BandoItem.

    Skip silenzioso (return None) se mancano titolo o URL.
    """
    titolo = _to_str(record.get("title")).strip()
    url_rel = _to_str(record.get("url")).strip()

    if not titolo or not url_rel:
        return None

    link = url_rel if url_rel.startswith("http") else f"{_BASE_URL}{url_rel}"

    descrizione = _to_str(record.get("description")).strip() or None
    if descrizione and len(descrizione) > 4000:
        descrizione = descrizione[:4000] + "..."

    # tipo_link: se is_forthcoming True o status='forthcoming' → Preavviso
    is_forthcoming = bool(record.get("is_forthcoming"))
    status = _to_str(record.get("status")).lower()
    tipo_link = "Preavviso" if (is_forthcoming or status == "forthcoming") else "Opportunità"

    # raw_data: tutto il payload ricco, l'enricher LLM lo userà per FK + junction.
    raw_data: dict[str, Any] = {
        "source": "obiettivo_europa",
        "identifier": _to_str(record.get("identifier")) or None,
        "status": status or None,
        "opening_date": _to_str(record.get("opening_date")) or None,
        "deadline": _to_str(record.get("deadline")) or None,
        "deadline_label": _to_str(record.get("deadline_label")) or None,
        "deadline_days_left": record.get("deadline_days_left"),
        "programme_title": _to_str(record.get("programme_title")) or None,
        "programme": _to_str(record.get("programme")) or None,
        "action_type_title": _to_str(record.get("action_type_title")) or None,
        "type_of_action": _to_str(record.get("type_of_action")) or None,
        "budget": record.get("budget"),
        "topics": record.get("topics") or [],
        "published": _to_str(record.get("published")) or None,
        "pnrr": bool(record.get("pnrr")),
        "on_arrival": bool(record.get("on_arrival")),
        # Tag estratti (sole stringhe title)
        "sectors": _extract_titles(record.get("sectors")),
        "beneficiaries": _extract_titles(record.get("beneficiaries")),
        "programs": _extract_titles(record.get("programs")),
        "types": _extract_titles(record.get("types")),
        "regions": _extract_titles(record.get("regions")),
        "evaluation_procedures": _extract_titles(record.get("evaluation_procedures")),
        "ateco_codes": record.get("ateco_codes") or [],
    }
    # Strip null/empty per JSONB compatto
    raw_data = {k: v for k, v in raw_data.items() if v not in (None, "", [], {})}

    return BandoItem(
        fonte_id=fonte_id,
        tipo_link=tipo_link,
        link_bando=link,
        titolo_raw=titolo,
        descrizione_raw=descrizione,
        raw_data=raw_data,
    )
