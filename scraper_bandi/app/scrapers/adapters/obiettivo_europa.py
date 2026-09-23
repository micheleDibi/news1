"""Adapter: API JSON Obiettivo Europa → BandoItem.

Schema REALE del record API (https://www.obiettivoeuropa.com/api/call/,
verificato il 22/09/2026, anonimo e autenticato):
  {
    "id": 12345,                     # chiave esterna stabile del bando su OE
    "title": "...",
    "url": "/bandi/slug/",           # relativo → BASE_URL + url
    "status": 1 | 2,                 # intero: NON e' un flag aperto/chiuso
    "published": "YYYY-MM-DD",
    "modified": "YYYY-MM-DDTHH:MM:SS+02:00",   # timestamp ISO di modifica lato OE
    "deadline_label": "...",         # testo in italiano (es. "Scade il 30/09/2026")
    "deadline_days_left": int,       # cambia ogni giorno: NON salvato in raw_data
    "on_arrival": bool,              # True = bando in uscita → tipo_link 'Preavviso'
    "updates_active": bool,
    "is_recent": bool, "is_copiloted": bool, "like": ..., "visited": ...,
    "budget": ...,
    "pnrr": bool,
    "section_program": ...,
    "sectors": [{title}, ...],
    "beneficiaries": [{title}, ...],
    "types": [{title}, ...],
    "regions": [{title}, ...],
    "programs": [{title}, ...],
    "evaluation_procedures": [{title}, ...],
    "ateco_codes": [...],
    "municipality_sizes": [...]
  }

NON esistono (mai emesse dall'API): identifier, opening_date, deadline,
description, topics, programme, programme_title, action_type_title,
type_of_action, is_forthcoming. Non esiste nemmeno un endpoint di dettaglio
(`/api/call/{id}/` → 404): la scheda va letta in HTML.
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

    # L'API non emette `description`: la lettura resta tollerante (se un giorno
    # comparisse) ma oggi descrizione_raw e' sempre None.
    descrizione = _to_str(record.get("description")).strip() or None
    if descrizione and len(descrizione) > 4000:
        descrizione = descrizione[:4000] + "..."

    # tipo_link: l'unico segnale "in uscita" dell'API e' `on_arrival`.
    # `status` e' un intero (1/2) e non vale mai 'forthcoming'.
    tipo_link = "Preavviso" if bool(record.get("on_arrival")) else "Opportunità"

    # raw_data: payload compatto per l'enricher LLM (FK + junction) e per la
    # chiave esterna (`id`) usata dal riconoscimento dei gemelli.
    # Escluso di proposito `deadline_days_left`: cambia ogni giorno e
    # riscriverebbe raw_data a ogni giro senza informazione nuova.
    raw_data: dict[str, Any] = {
        "source": "obiettivo_europa",
        "id": _to_str(record.get("id")).strip() or None,
        "status": _to_str(record.get("status")).strip() or None,
        "published": _to_str(record.get("published")) or None,
        "modified": _to_str(record.get("modified")) or None,
        "deadline_label": _to_str(record.get("deadline_label")) or None,
        "budget": record.get("budget"),
        "pnrr": bool(record.get("pnrr")),
        "on_arrival": bool(record.get("on_arrival")),
        "updates_active": bool(record.get("updates_active")),
        # Tag estratti (sole stringhe title)
        "sectors": _extract_titles(record.get("sectors")),
        "beneficiaries": _extract_titles(record.get("beneficiaries")),
        "programs": _extract_titles(record.get("programs")),
        "types": _extract_titles(record.get("types")),
        "regions": _extract_titles(record.get("regions")),
        "evaluation_procedures": _extract_titles(record.get("evaluation_procedures")),
        "ateco_codes": record.get("ateco_codes") or [],
    }
    # Strip null/empty per JSONB compatto (i booleani False restano)
    raw_data = {k: v for k, v in raw_data.items() if v not in (None, "", [], {})}

    return BandoItem(
        fonte_id=fonte_id,
        tipo_link=tipo_link,
        link_bando=link,
        titolo_raw=titolo,
        descrizione_raw=descrizione,
        raw_data=raw_data,
    )
