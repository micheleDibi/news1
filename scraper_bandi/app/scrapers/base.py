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

    Dopo ogni `scrape()` lo scraper dichiara in `ultimo_esito` **quanto** della
    fonte ha davvero letto (piano §6.1). Serve a una decisione sola, ma seria:
    un bando che non compare piu' nel listing e' «sparito dalla fonte» solo se
    il listing e' stato letto per intero. Senza questa dichiarazione una
    paginazione interrotta a meta' produrrebbe centinaia di falsi «spariti»,
    che a loro volta alzerebbero la priorita' di altrettanti controlli inutili.

    I tre campi (`esito_iniziale`) sono volutamente pochi:
      - `pagine`   pagine effettivamente lette;
      - `troncato` vero se la lettura si e' fermata prima della fine (tetto
        `max_pages`, early-stop sui duplicati, errore HTTP, pagina saltata).
        **Il valore di partenza e' True**: «non so» vale «non ho visto tutto»;
      - `count`    totale dichiarato dalla fonte (`numFound`, `count`), 0 se la
        fonte non lo dichiara.

    Ogni `scrape()` che dichiara l'esito **assegna un dizionario nuovo** a
    `self.ultimo_esito` (mai `self.ultimo_esito[...] = ...`): il valore di
    classe qui sotto e' condiviso da tutte le istanze, e mutarlo farebbe
    leggere a una fonte l'esito di un'altra. Le strategie che non lo
    dichiarano restano a «troncato», cioe' non producono mai «spariti».
    """
    name: str = "base"

    #: Esito dell'ultimo `scrape()`; lo legge `segnali.copertura_piena`.
    ultimo_esito: dict[str, Any] = {"pagine": 0, "troncato": True, "count": 0}

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        raise NotImplementedError(
            f"Strategy {self.name!r}: scrape() non implementato"
        )


def esito_iniziale() -> dict[str, Any]:
    """L'esito prima di qualunque lettura: zero pagine e copertura ignota."""
    return {"pagine": 0, "troncato": True, "count": 0}


def esito(pagine: int, *, troncato: bool, count: int = 0) -> dict[str, Any]:
    """Costruttore dell'esito, cosi' le tre chiavi si scrivono in un posto solo."""
    return {"pagine": int(pagine), "troncato": bool(troncato), "count": int(count or 0)}
