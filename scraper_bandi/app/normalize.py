"""Helpers di normalizzazione + hash."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def hash_bando(fonte_id: int, link_or_titolo: str) -> str:
    """SHA256(fonte_id|link_or_titolo) come hex string.

    - Per bandi CON link: SHA256(fonte_id|link_bando).
    - Per bandi SENZA link: SHA256(fonte_id|normalize_titolo(titolo_raw)).
    """
    payload = f"{int(fonte_id)}|{link_or_titolo}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_titolo(titolo: str | None) -> str:
    """Normalizza un titolo per dedup: NFKD + strip accents + casefold +
    collapse whitespace + rimuove punteggiatura finale."""
    if not titolo:
        return ""
    nfkd = unicodedata.normalize("NFKD", titolo)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"\s+", " ", no_accents.strip()).casefold()
    return cleaned.rstrip(" .,:;-_/")


def is_valid_http_url(url: str | None) -> bool:
    """True se la stringa sembra un URL http/https valido."""
    if not url:
        return False
    return url.startswith(("http://", "https://"))
