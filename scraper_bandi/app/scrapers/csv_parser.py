"""Strategy `csv_parser`: scarica un CSV/XLSX da URL e produce BandoItem.

Usato per ~8 fonti (Sardegna asset CDN, Trento dataset, Toscana, JTF,
Umbria, ecc.). I bandi listati nei CSV non hanno tipicamente un link
individuale: vanno tutti salvati come bandi SENZA link, con `titolo_raw`
+ `raw_data` JSONB.

Parametri (registry):
  - file_url_override: se settato, scarica QUESTO URL invece di fonte.link
                       (utile quando la fonte e' un wrapper o redirect).
  - titolo_columns: lista di nomi colonna candidati per il titolo del bando
                    (matchato case-insensitive). Se nessuno matcha, usa la
                    prima colonna stringa non vuota.
  - encoding: encoding del file (default 'utf-8' con fallback 'latin-1').
  - delimiter: separatore CSV (default sniff).
  - sheet_name: per XLSX, il nome o indice foglio (default 0).
"""
from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlsplit

from ..http import fetch_bytes
from ..logger import logger
from .base import BandoItem, BandoScraper


# Nomi colonna candidati comuni per "titolo" (case-insensitive, normalized)
DEFAULT_TITOLO_COLUMNS = (
    "titolo", "titolo_avviso", "oggetto", "oggetto_avviso",
    "denominazione", "nome", "descrizione", "avviso", "bando",
    "azione", "intervento", "titolo intervento",
)


def _is_xlsx(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith((".xlsx", ".xls"))


def _looks_like_xlsx(content: bytes) -> bool:
    """True se il content inizia con il magic byte ZIP (PK\\x03\\x04) tipico di
    XLSX/ODS/DOCX. Molti endpoint download (es. WPDM WordPress) consegnano
    XLSX anche se l'URL non ha estensione .xlsx."""
    return content[:4] == b"PK\x03\x04"


def _read_csv_with_fallback(
    content: bytes,
    encoding: str | None,
    delimiter: str | None,
    skiprows: int | None = None,
):
    """Tenta read_csv con varie combinazioni di encoding/delimiter/quoting.

    Strategia di fallback multipla:
      1. encoding utf-8/latin-1/cp1252 + sniff sep + quoting standard
      2. on_bad_lines='skip' per saltare righe malformate
      3. quoting=csv.QUOTE_NONE come ultima spiaggia (no quote escape)
      4. skiprows configurabile per saltare righe narrative di header
    """
    import csv as _csv

    import pandas as pd

    encodings = [encoding] if encoding else ["utf-8", "latin-1", "cp1252"]

    # Combinazioni in ordine di preferenza (encoding, sep, quoting, on_bad_lines)
    attempts: list[dict[str, Any]] = []
    for enc in encodings:
        # Standard sniff + skip bad lines
        attempts.append({
            "encoding": enc, "sep": delimiter,
            "engine": "python" if not delimiter else "c",
            "on_bad_lines": "skip",
        })
        # QUOTE_NONE: ignora le quote (utile per CSV con header narrativo malformato)
        attempts.append({
            "encoding": enc, "sep": delimiter,
            "engine": "python" if not delimiter else "c",
            "quoting": _csv.QUOTE_NONE,
            "on_bad_lines": "skip",
        })

    last_err: Exception | None = None
    for attempt in attempts:
        try:
            buf = io.BytesIO(content)
            if skiprows is not None:
                attempt["skiprows"] = skiprows
            df = pd.read_csv(buf, **attempt)
            # Se ha 0 righe e abbiamo provato skiprows=None, lascia che successivi tentativi
            # mantengano. Se invece ha 0 righe e abbiamo gia' skippato, lo accettiamo (vuoto).
            return df
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"read_csv fallito con tutte le combinazioni: {last_err}")


def _read_xlsx(content: bytes, sheet_name):
    """Legge un XLSX/ZIP-OOXML.

    Forziamo `engine='openpyxl'`: senza, pandas prova a inferire l'engine
    dall'estensione del file. Quando il content e' un BytesIO senza nome
    (es. download da endpoint WPDM senza .xlsx nell'URL) pandas magari
    rileva il magic byte ZIP e cerca 'io.excel.zip.reader' che non esiste.
    """
    import pandas as pd
    return pd.read_excel(io.BytesIO(content), sheet_name=sheet_name, engine="openpyxl")


def _pick_titolo_column(df, titolo_candidates: list[str]) -> str | None:
    """Sceglie la colonna che e' verosimilmente il titolo del bando."""
    cols_lower = {c.lower().strip(): c for c in df.columns if isinstance(c, str)}
    for cand in titolo_candidates:
        c = cand.lower().strip()
        if c in cols_lower:
            return cols_lower[c]
    # Match parziale (es. "titolo_avviso" matcha "Titolo Avviso")
    for cand in titolo_candidates:
        c = cand.lower().strip().replace("_", " ")
        for k, v in cols_lower.items():
            if c in k.replace("_", " "):
                return v
    # Fallback: prima colonna stringa con contenuto non vuoto
    for c in df.columns:
        try:
            sample = df[c].dropna().astype(str).head(3).tolist()
            if sample and all(len(s.strip()) > 5 for s in sample):
                return c
        except Exception:
            continue
    return None


class CsvParserScraper(BandoScraper):
    name = "csv_parser"

    def __init__(
        self,
        file_url_override: str | None = None,
        titolo_columns: list[str] | None = None,
        encoding: str | None = None,
        delimiter: str | None = None,
        sheet_name: Any = 0,
        skiprows: int | None = None,
        **_extra: Any,
    ) -> None:
        self.file_url_override = file_url_override
        self.titolo_columns = list(titolo_columns) if titolo_columns else list(DEFAULT_TITOLO_COLUMNS)
        self.encoding = encoding
        self.delimiter = delimiter
        self.sheet_name = sheet_name
        self.skiprows = skiprows

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        url = self.file_url_override or fonte["link"]
        logger.info("[csv] fonte_id={} download url={}", fonte.get("id"), url)

        try:
            content = await fetch_bytes(url, timeout_s=120.0)
        except Exception as e:
            logger.exception("[csv] fonte_id={} download fallito: {}", fonte.get("id"), e)
            return []

        # Difesa: rileva content HTML restituito da una URL che doveva essere CSV
        head = content[:256].lstrip().lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head[:200]:
            logger.error(
                "[csv] fonte_id={} URL e' una pagina HTML, non un CSV/XLSX. "
                "Registry mal-mappato: cambia strategy a hybrid_httpx_firecrawl. url={}",
                fonte.get("id"), url,
            )
            return []

        # Auto-detect XLSX: magic byte ZIP/OOXML (anche se URL non finisce in .xlsx)
        is_xlsx = _is_xlsx(url) or _looks_like_xlsx(content)
        if is_xlsx and not _is_xlsx(url):
            logger.info(
                "[csv] fonte_id={} URL senza .xlsx ma magic byte ZIP/OOXML rilevato -> parse come XLSX",
                fonte.get("id"),
            )

        try:
            if is_xlsx:
                df = _read_xlsx(content, self.sheet_name)
            else:
                df = _read_csv_with_fallback(
                    content, self.encoding, self.delimiter, self.skiprows,
                )
        except Exception as e:
            logger.exception("[csv] fonte_id={} parse fallito: {}", fonte.get("id"), e)
            return []

        if df is None or len(df) == 0:
            logger.warning("[csv] fonte_id={} dataframe vuoto", fonte.get("id"))
            return []

        # Validazione qualita': se il df ha 1 sola colonna, il sniff sep e'
        # fallito (probabilmente il file ha un header narrativo che ha
        # rovinato il riconoscimento delle colonne). Skip con warning.
        if len(df.columns) < 2:
            logger.warning(
                "[csv] fonte_id={} parse degenere ({} colonna): file probabilmente "
                "mal-formato con header narrativo. Considera 'skiprows' nel registry. cols={}",
                fonte.get("id"), len(df.columns), list(df.columns),
            )
            return []

        titolo_col = _pick_titolo_column(df, self.titolo_columns)
        if not titolo_col:
            logger.warning(
                "[csv] fonte_id={} nessuna colonna titolo identificabile (colonne: {})",
                fonte.get("id"), list(df.columns),
            )
            return []

        logger.info(
            "[csv] fonte_id={} righe={} cols={} titolo_col={!r}",
            fonte.get("id"), len(df), list(df.columns), titolo_col,
        )

        items: list[BandoItem] = []
        # Uso enumerate per ottenere SEMPRE un int come row_index (l'indice
        # nativo del df potrebbe essere una tupla per MultiIndex).
        for row_position, (_idx, row) in enumerate(df.iterrows()):
            titolo = row.get(titolo_col)
            if titolo is None or (isinstance(titolo, float) and titolo != titolo):  # NaN
                continue
            titolo_str = str(titolo).strip()
            if not titolo_str or titolo_str.lower() in ("nan", "none", "null"):
                continue

            # raw_data = tutto il record (serializzabile)
            raw: dict[str, Any] = {"row_index": row_position, "source_url": url}
            for col, val in row.items():
                if col == titolo_col:
                    continue
                if val is None or (isinstance(val, float) and val != val):
                    continue
                key = str(col).strip() or f"col_{row_position}"
                raw[key] = str(val).strip() if not isinstance(val, (int, float, bool)) else val

            items.append(BandoItem(
                fonte_id=fonte["id"],
                tipo_link=fonte["tipo_link"],
                link_bando=None,
                titolo_raw=titolo_str,
                descrizione_raw=None,
                raw_data=raw,
            ))

        logger.info("[csv] fonte_id={} estratti {} bandi", fonte.get("id"), len(items))
        return items
