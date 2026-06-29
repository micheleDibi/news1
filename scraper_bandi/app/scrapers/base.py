"""Interfaccia base per gli scraper di bandi."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BandoItem:
    """Un bando estratto da una fonte.

    Casi:
      A) Bando con URL di dettaglio:
         - link_bando: URL pagina dettaglio (non None).
         - titolo_raw: titolo visualizzato (opzionale, dal testo del link/card).
         - raw_data: None (l'enrichment skill estrarra' tutto dal link).

      B) Bando senza URL (calendari PDF/CSV o JS-only):
         - link_bando: None.
         - titolo_raw: titolo del bando (obbligatorio per dedup).
         - raw_data: JSONB con info aggiuntive (fondo, data_pubb_prevista,
                     asse, beneficiari, dotazione, fonte_riga, ecc.).
    """
    fonte_id: int
    tipo_link: str                          # 'Opportunità' | 'Preavviso'
    link_bando: str | None
    titolo_raw: str | None
    descrizione_raw: str | None = None
    raw_data: dict[str, Any] | None = None


class BandoScraper:
    """Base class astratta. Ogni strategia implementa `scrape(fonte)`.

    Il parametro `fonte` e' un dict con almeno le chiavi:
      - id (int)
      - link (str)             URL della fonte
      - tipo_link (str)        'Opportunità' o 'Preavviso'
      - formato_link (str)     'HTML' | 'PDF' | 'CSV'
    """
    name: str = "base"

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        raise NotImplementedError(
            f"Strategy {self.name!r}: scrape() non implementato"
        )
