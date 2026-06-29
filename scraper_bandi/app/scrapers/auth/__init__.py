"""Auth providers per scraper di fonti autenticate.

Pattern: ogni provider espone `obtain_session(username, password) -> requests.Session`
che restituisce una Session gia' autenticata (cookie validi, headers settati).

Registry centralizzato in get_auth_provider(name) usato da
`json_api_paginated_login` strategy.
"""
from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    import requests


def get_auth_provider(name: str) -> Callable[[str, str], "requests.Session"]:
    """Lookup callable per nome registry.

    Raises:
        ValueError se name non noto.
    """
    if name == "obiettivo_europa":
        from .obiettivo_europa import obtain_session
        return obtain_session
    raise ValueError(f"Auth provider sconosciuto: {name!r}")


__all__ = ["get_auth_provider"]
