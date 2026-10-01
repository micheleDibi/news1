"""Filtro d'ingresso: un bando nuovo si pubblica adesso o sosta? (contratto del giro 2, §5.10 con §19.4).

Puro: niente DB, niente rete, niente orologio implicito. Lo usano la SEO prima
di pubblicare (`bando_seo_runner`) e la fase ingresso di `verifica-stato`.

La sosta non e' un rifiuto. Un «aperto» senza `data_scadenza`, senza una
conferma di un lettore per ente e senza un termine indicato futuro aspetta al
massimo `sosta_giri` giri (6 ore l'uno) da `trattenuto_dal`: il tempo che la
fase ingresso gli cerchi una scadenza. Poi si pubblica comunque
(`rilasciato_a_tempo`). Resta fermo sempre, invece, un bando senza appigli:
nessun link (ne' `link_bando`, ne' `fonte_ufficiale_url`, ne' righe
`bando_link`) e nessuna data. Quello non ha niente che nessuno possa rileggere.

Il verdetto e' sempre quello «attivo». In ombra il chiamante pubblica
comunque e conta soltanto.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from .stato_bando import _istante, _solo_giorno, adesso_roma

#: Durata di un giro del sender (00/06/12/18).
ORE_PER_GIRO = 6
#: Giri di sosta predefiniti; il valore vero arriva da
#: `settings.ingresso_sosta_giri` (INGRESSO_SOSTA_GIRI).
SOSTA_GIRI_PREDEFINITA = 4

MOTIVO_SOSTA = "sosta"
MOTIVO_RILASCIATO = "rilasciato_a_tempo"
MOTIVO_SENZA_APPIGLIO = "senza_appiglio"
MOTIVI_INGRESSO: tuple[str, ...] = (MOTIVO_SOSTA, MOTIVO_RILASCIATO, MOTIVO_SENZA_APPIGLIO)

#: Le date di `bando` che bastano a dare un appiglio.
_DATE_BANDO: tuple[str, ...] = ("data_pubblicazione", "data_apertura", "data_scadenza")


def _ha_link(controllo: Mapping[str, Any]) -> bool:
    """`bando_link` puo' arrivare come booleano, conteggio o lista di righe."""
    valore = controllo.get("bando_link")
    if isinstance(valore, bool):
        return valore
    if isinstance(valore, int):
        return valore > 0
    if isinstance(valore, (Sequence, Mapping)) and not isinstance(valore, str):
        return len(valore) > 0
    return False


def senza_appiglio(riga: Mapping[str, Any], controllo: Mapping[str, Any] | None) -> bool:
    """Vero se il bando non ha ne' un link ne' una data: resta sempre fermo."""
    controllo = controllo or {}
    if riga.get("link_bando") or riga.get("fonte_ufficiale_url") or _ha_link(controllo):
        return False
    if any(_solo_giorno(riga.get(campo)) for campo in _DATE_BANDO):
        return False
    return _solo_giorno(controllo.get("termine_indicato")) is None


def _conferma_di_estrattore(controllo: Mapping[str, Any]) -> bool:
    """Una voce della storia con «aperto» letto da un lettore per ente.

    Il lettore generico non conferma mai (legge solo chiusure), e una lettura
    del modello non ha estrattore: nessuna delle due toglie la sosta.
    """
    lettura = controllo.get("lettura_stato")
    storia = lettura.get("storia") if isinstance(lettura, Mapping) else None
    for voce in storia if isinstance(storia, Sequence) and not isinstance(storia, str) else ():
        if not isinstance(voce, Mapping):
            continue
        estrattore = voce.get("estrattore")
        if estrattore and estrattore != "generico" and voce.get("stato") == "aperto":
            return True
    return False


def pubblicabile(
    riga: Mapping[str, Any],
    controllo: Mapping[str, Any] | None,
    adesso: datetime,
    *,
    sosta_giri: int = SOSTA_GIRI_PREDEFINITA,
) -> tuple[bool, str | None]:
    """(si pubblica?, motivo). Motivo None: nessuna ragione per aspettare.

    - `senza_appiglio`: nessun link e nessuna data → (False, …), sempre;
    - un bando che non e' un «aperto» senza `data_scadenza` → (True, None);
    - con una conferma di un lettore per ente nella storia, o con un
      `termine_indicato` da oggi in poi → (True, None);
    - altrimenti `sosta` finche' non sono passati `sosta_giri` giri da
      `trattenuto_dal` → (False, 'sosta'). Con `trattenuto_dal` NULL la sosta
      comincia adesso: il chiamante lo scrive;
    - passata la sosta → (True, 'rilasciato_a_tempo').
    """
    controllo = controllo or {}
    if senza_appiglio(riga, controllo):
        return False, MOTIVO_SENZA_APPIGLIO
    if riga.get("stato_bando") != "aperto" or _solo_giorno(riga.get("data_scadenza")):
        return True, None
    if int(sosta_giri) <= 0:                  # 0 = sosta spenta
        return True, None
    if _conferma_di_estrattore(controllo):
        return True, None
    momento = adesso_roma(adesso)
    termine = _solo_giorno(controllo.get("termine_indicato"))
    if termine is not None and termine >= momento.date().isoformat():
        return True, None
    dal = _istante(controllo.get("trattenuto_dal"))
    if dal is None or momento - dal < timedelta(hours=ORE_PER_GIRO * int(sosta_giri)):
        return False, MOTIVO_SOSTA
    return True, MOTIVO_RILASCIATO


__all__ = [
    "MOTIVI_INGRESSO", "MOTIVO_RILASCIATO", "MOTIVO_SENZA_APPIGLIO", "MOTIVO_SOSTA",
    "ORE_PER_GIRO", "SOSTA_GIRI_PREDEFINITA", "pubblicabile", "senza_appiglio",
]
