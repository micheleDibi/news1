# -*- coding: utf-8 -*-
"""Host morti nel resolver e nei ricontrolli (contratto di ottobre 2026, §5).

Il caso di prova e' quello del 28/09/2026: il DNS di regione.basilicata.it era
rotto, ogni URL pagava tre tentativi, un solo bando ha impiegato 247 secondi e
i 101 URL di quell'host rischiavano cento minuti di ricontrolli l'08/10. Oggi:

- un host che non risolve si interroga una volta sola per giro (`scarico.py`);
- un bando senza `trovata` con un candidato su quell'host non riceve verdetto,
  non consuma un tentativo e non cambia lo stato della fonte;
- un bando oltre `TETTO_TEMPO_BANDO_S` passa al giro dopo allo stesso modo;
- nei ricontrolli il rinviato slitta a domani, e nient'altro, cosi' 101 bandi
  morti non occupano a ogni giro i 60 posti della selezione.

Nessuna rete: lo scarico vero con `httpx.MockTransport`, il DB con dei patch.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_host_morti
"""
import asyncio
import socket
import time
import unittest
import unittest.mock
from datetime import date

import httpx

from tests.supporto import carica_modulo
from tests.test_fonte_ufficiale import (
    CORPO_COMPLETO, ENTE, IMPORTO, TABELLA_ENTE, TITOLO, URL_BUONO, pagina,
)

fu = carica_modulo("fonte_ufficiale")
scarico = carica_modulo("scarico")

HOST_MORTO = "portalebandi.regione.basilicata.it"
OGGI = date(2026, 10, 8)


async def _niente(*_args):
    """Throttle e backoff istantanei."""


def _dns_rotto(request: httpx.Request):
    """Un nome che non risolve (EAI_NONAME, il codice del sistema): e' il caso
    che fa saltare l'host. EAI_AGAIN no (test in `test_scarico`)."""
    try:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    except socket.gaierror as causa:
        raise httpx.ConnectError(
            "Name or service not known", request=request) from causa


class _LockFinto:
    proseguire = True
    stato = "acquisito"


def _bando(i: int, link: str, secondo: str | None = None):
    """Un bando con il primo candidato in `raw_data` e l'eventuale secondo in
    `link_bando`: e' l'ordine del passo 1 di `candidati_strutturati`."""
    valori = {
        "id": i, "titolo": TITOLO, "ente_erogatore": ENTE,
        # La scadenza che `CORPO_COMPLETO` dichiara: senza, la pagina buona
        # non passa i gate e non diventa `trovata`.
        "data_scadenza": "2026-09-30", "importo_totale_eur": IMPORTO,
        "raw_data": {"external_link": link},
    }
    if secondo:
        valori["link_bando"] = secondo
    return valori


def _ambiente(*, rete=_dns_rotto, pagine=None, **kwargs):
    """Scarico vero (DNS compreso) per ogni host, tranne le pagine date."""
    richieste: list[str] = []

    def gestore(request):
        richieste.append(str(request.url))
        return rete(request)

    reale = scarico.Scarico(
        transport=httpx.MockTransport(gestore), throttle=_niente, dormi=_niente)
    mappa = dict(pagine or {})

    async def scarica(url):
        if url in mappa:
            return mappa[url]
        return fu.pagina_da_risposta(await reale.scarica(url, come_fonte=True))

    parametri = dict(tabella=TABELLA_ENTE, scarica=scarica, oggi=OGGI)
    parametri.update(kwargs)
    return fu.Ambiente(**parametri), richieste, reale


def _giro(bandi, amb, *, modo="ricontrolli", dry_run=False):
    """`fu.run` con il DB finto; ritorna (riepilogo, esiti scritti, rinvii)."""
    scritti: list = []
    rinvii: list = []

    def _scrivi(esito, **_k):
        scritti.append(esito)
        return {"status": "ok"}

    def _aggiorna(bando_id, payload, **_k):
        rinvii.append((bando_id, dict(payload)))
        return {"scritto": True}

    with unittest.mock.patch.object(fu.blocco, "acquisisci", return_value=_LockFinto()), \
            unittest.mock.patch.object(fu.blocco, "rilascia", lambda _l: None), \
            unittest.mock.patch.object(
                fu.db, "select_bandi_da_risolvere", return_value=list(bandi)), \
            unittest.mock.patch.object(fu.db, "select_controlli", return_value={}), \
            unittest.mock.patch.object(fu.db, "select_link_da_verificare", return_value=[]), \
            unittest.mock.patch.object(
                fu.db, "select_pubblicati_per_gemelli", return_value=[]), \
            unittest.mock.patch.object(fu.db, "aggiorna_controllo", _aggiorna), \
            unittest.mock.patch.object(fu, "schede_gia_lette", return_value=frozenset()), \
            unittest.mock.patch.object(fu, "_registra", lambda *_a, **_k: None), \
            unittest.mock.patch.object(fu, "scrivi_esito", _scrivi):
        riepilogo = asyncio.run(
            fu.run(dry_run=dry_run, attivo=False, modo=modo, ambiente=amb))
    return riepilogo, scritti, rinvii


class TestBasilicata(unittest.TestCase):
    """101 bandi sullo stesso host col DNS rotto: il caso del 28/09."""

    def _bandi(self, quanti=101):
        return [_bando(i, f"https://{HOST_MORTO}/avvisi-e-bandi/avviso-{i}/")
                for i in range(1, quanti + 1)]

    def test_una_sola_risoluzione_nessun_verdetto_nessun_tentativo(self):
        amb, richieste, _ = _ambiente()
        avvio = time.monotonic()
        riepilogo, scritti, rinvii = _giro(self._bandi(), amb)
        self.assertLess(time.monotonic() - avvio, 10)
        # Tre richieste in tutto (un URL, due ritentativi), non 303.
        self.assertEqual(len(richieste), 3)
        # Nessun esito scritto: niente `in_verifica`, niente tentativi.
        self.assertEqual(scritti, [])
        self.assertEqual(riepilogo["esaminati"], 101)
        self.assertEqual(riepilogo["rinviati_dns"], 101)
        self.assertEqual(riepilogo["in_verifica"], 0)
        self.assertEqual(riepilogo["non_trovate"], 0)
        self.assertEqual(riepilogo["errori"], 0)
        self.assertEqual(riepilogo["host_irraggiungibili"], 1)
        self.assertEqual(riepilogo["host_irraggiungibili_elenco"], [HOST_MORTO])
        # Giro 3 (§7): i ricontrolli non hanno piu' cadenza (li prende tutti
        # ogni giro, in ordine di ultimo controllo), quindi il rinvio non
        # scrive niente, come nei nuovi.
        self.assertEqual(rinvii, [])

    def test_nei_nuovi_il_rinvio_non_scrive_niente(self):
        amb, _richieste, _ = _ambiente()
        riepilogo, scritti, rinvii = _giro(self._bandi(3), amb, modo="nuovi")
        self.assertEqual(riepilogo["rinviati_dns"], 3)
        self.assertEqual(scritti, [])
        self.assertEqual(rinvii, [])

    def test_in_dry_run_il_rinvio_non_scrive_niente(self):
        amb, _richieste, _ = _ambiente()
        riepilogo, _scritti, rinvii = _giro(self._bandi(3), amb, dry_run=True)
        self.assertEqual(riepilogo["rinviati_dns"], 3)
        self.assertEqual(rinvii, [])


class TestVerdettoConHostMorto(unittest.TestCase):
    def test_un_altro_candidato_trovato_si_scrive_come_sempre(self):
        morto = f"https://{HOST_MORTO}/avvisi-e-bandi/avviso/"
        amb, _richieste, _ = _ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)})
        riepilogo, scritti, rinvii = _giro([_bando(1, morto, URL_BUONO)], amb)
        self.assertEqual([e.stato for e in scritti], [fu.STATO_TROVATA])
        self.assertEqual(scritti[0].url, URL_BUONO)
        self.assertEqual(riepilogo["rinviati_dns"], 0)
        self.assertEqual(riepilogo["trovate"], 1)
        self.assertEqual(riepilogo["host_irraggiungibili"], 1)
        self.assertEqual(rinvii, [])

    def test_un_errore_di_rete_senza_dns_resta_un_in_verifica(self):
        # Timeout isolato: l'host esiste, e il comportamento e' quello di oggi.
        def timeout(_request):
            raise httpx.ConnectTimeout("timeout")

        amb, richieste, _ = _ambiente(rete=timeout)
        riepilogo, scritti, rinvii = _giro(
            [_bando(1, "https://ente.example.it/a"), _bando(2, "https://ente.example.it/b")],
            amb)
        self.assertEqual([e.stato for e in scritti], [fu.STATO_IN_VERIFICA] * 2)
        self.assertEqual(len(richieste), 6)           # nessun host saltato
        self.assertEqual(riepilogo["rinviati_dns"], 0)
        self.assertEqual(riepilogo["host_irraggiungibili"], 0)
        self.assertEqual(rinvii, [])


class TestTettoDiTempo(unittest.TestCase):
    def test_oltre_il_tetto_il_bando_passa_al_giro_dopo(self):
        lento = "https://lento.example.it/avviso"

        async def scarica(url):
            if url == lento:
                await asyncio.sleep(5)
            return pagina(url, corpo=CORPO_COMPLETO)

        amb = fu.Ambiente(tabella=TABELLA_ENTE, scarica=scarica, oggi=OGGI,
                          tetto_tempo_bando_s=0.05)
        avvio = time.monotonic()
        riepilogo, scritti, rinvii = _giro([_bando(1, lento), _bando(2, URL_BUONO)], amb)
        self.assertLess(time.monotonic() - avvio, 3)
        # Il bando lento non ha verdetto ne' tentativo; quello dopo si lavora.
        # Giro 3 (§7): nessuna data scritta, il giro dopo lo riprende comunque.
        self.assertEqual([e.bando_id for e in scritti], [2])
        self.assertEqual(riepilogo["rinviati_tempo"], 1)
        self.assertEqual(rinvii, [])

    def test_il_tetto_predefinito(self):
        self.assertEqual(fu.TETTO_TEMPO_BANDO_S, 120.0)
        self.assertEqual(fu.Ambiente().tetto_tempo_bando_s, fu.TETTO_TEMPO_BANDO_S)


class TestRigaDelGiro(unittest.TestCase):
    def test_elenco_degli_host_al_massimo_venti(self):
        contatori = fu.Contatori(host_morti={f"ente{n:02d}.it" for n in range(25)})
        riga = contatori.come_dizionario()
        self.assertEqual(riga["host_irraggiungibili"], 25)
        self.assertEqual(len(riga["host_irraggiungibili_elenco"]), 20)
        self.assertEqual(riga["host_irraggiungibili_elenco"][0], "ente00.it")

    def test_la_pagina_porta_il_segno_dello_scarico(self):
        risposta = scarico.Risposta(url="https://x.it", stato=None, host_irraggiungibile=True)
        self.assertTrue(fu.pagina_da_risposta(risposta).host_irraggiungibile)
        self.assertFalse(fu.pagina_da_risposta(
            scarico.Risposta(url="https://x.it", stato=200)).host_irraggiungibile)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
