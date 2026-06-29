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


# ---------------------------------------------------------------------------
# v10: canonical_key cross-source per dedup tra fonti diverse
# ---------------------------------------------------------------------------

# Stopword italiane minimali rilevanti per titoli di bandi.
# NB: lista volutamente piccola (no overcleaning). I bandi vanno deduplicati
# su parole chiave significative, non solo connettori.
_STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "di", "del", "dello", "della", "dei", "degli", "delle", "dell",
    "e", "ed", "a", "ad", "in", "con", "per", "su", "tra", "fra",
    "da", "dal", "dalla", "dai", "dalle", "degli", "al", "alla", "ai",
    "alle", "agli", "all",
}


def normalize_for_canonical(text: str | None) -> str:
    """Normalizzazione aggressiva per canonical_key.

    Pipeline:
      1. NFKD + strip accenti
      2. casefold (piu' aggressivo del lower per UNICODE)
      3. rimuove tutto cio' che non e' alfanumerico o spazio
      4. tokenize + rimuove stopword IT
      5. rejoin con singolo spazio

    Robust to: varianti case ('REGIONE LOMBARDIA' vs 'Regione Lombardia'),
    punteggiatura ('Voucher: 2026' vs 'Voucher 2026'), whitespace multipli,
    accenti ('citta'' vs 'citta'').
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = no_accents.casefold()
    # rimuove tutto cio' che non e' [a-z0-9 \s]
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS_IT]
    return " ".join(tokens)


def compute_canonical_key(
    titolo: str | None,
    ente: str | None,
    data_scadenza: str | None,
    importo_totale_eur: int | None,
) -> str | None:
    """Calcola canonical_key per dedup cross-source.

    Ritorna None se titolo o ente sono mancanti (insufficient signal per
    dedupplicare in modo affidabile). In quel caso il bando rimane senza
    canonical_key (potenziale duplicato non rilevato, ma niente falsi positivi).

    Components (in ordine):
      - normalize_for_canonical(titolo)
      - normalize_for_canonical(ente)
      - str(data_scadenza or "")     # YYYY-MM-DD oppure ""
      - str(importo_totale_eur or "")
    """
    if not titolo or not ente:
        return None
    norm_t = normalize_for_canonical(titolo)
    norm_e = normalize_for_canonical(ente)
    if not norm_t or not norm_e:
        return None
    parts = [
        norm_t,
        norm_e,
        str(data_scadenza or ""),
        str(importo_totale_eur or ""),
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
