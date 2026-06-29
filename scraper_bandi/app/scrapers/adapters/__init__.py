"""Adapter: mapping da JSON/HTML grezzo del portale → BandoItem standard.

Pattern: ogni adapter espone una callable `to_bando_item(record, fonte_id) -> BandoItem | None`.
Registry centralizzato in get_adapter(name) usato dalle 3 strategie v10
(json_api_paginated, json_api_paginated_login, html_paginated_offset).
"""
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..base import BandoItem


def get_adapter(name: str) -> Callable[[Any, int], "BandoItem | None"]:
    """Lookup adapter per nome registry.

    Raises:
        ValueError se name non noto.
    """
    if name == "obiettivo_europa":
        from .obiettivo_europa import to_bando_item
        return to_bando_item
    if name == "incentivi_gov_it":
        from .incentivi_gov_it import to_bando_item
        return to_bando_item
    if name == "italia_domani":
        from .italia_domani import to_bando_item
        return to_bando_item
    raise ValueError(f"Adapter sconosciuto: {name!r}")


__all__ = ["get_adapter"]
