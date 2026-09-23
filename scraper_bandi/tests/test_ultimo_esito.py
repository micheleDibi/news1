# -*- coding: utf-8 -*-
"""`scraper.ultimo_esito`: la dichiarazione di copertura di §6.1.

Serve a una decisione sola: un bando che non compare piu' nel listing e'
«sparito dalla fonte» **solo** se il listing e' stato letto per intero. Ogni
uscita anticipata (tetto `max_pages`, early-stop sui duplicati, errore HTTP,
pagina saltata) deve lasciare `troncato=True`, altrimenti una paginazione
interrotta a meta' produce centinaia di falsi «spariti» in un colpo solo.

Nessuna rete: la sessione HTTP e `fetch_html` sono sostituite.
"""
import asyncio
import unittest
from unittest.mock import patch

import httpx

from tests.supporto import carica_modulo

base = carica_modulo("scrapers.base")
api_paginated = carica_modulo("scrapers.api_paginated")
api_login = carica_modulo("scrapers.api_paginated_login")
httpx_bs4 = carica_modulo("scrapers.httpx_bs4")
segnali = carica_modulo("segnali")

FONTE = {"id": 449, "link": "https://esempio.it/api/", "tipo_link": "Opportunità",
         "formato_link": "JSON"}
FONTE_HTML = {"id": 12, "link": "https://esempio.it/bandi", "tipo_link": "Opportunità",
              "formato_link": "HTML"}


class _Risposta:
    def __init__(self, dati, stato=200):
        self.status_code = stato
        self._dati = dati

    def json(self):
        return self._dati


class _Sessione:
    """Sessione finta: restituisce le pagine in ordine, poi una pagina vuota."""

    def __init__(self, pagine, stato=200):
        self.pagine = list(pagine)
        self.stato = stato
        self.headers: dict[str, str] = {}
        self.chiamate = 0

    def get(self, url, params=None, timeout=None):
        self.chiamate += 1
        if self.stato != 200:
            return _Risposta({}, stato=self.stato)
        if self.pagine:
            return _Risposta(self.pagine.pop(0))
        return _Risposta({"results": [], "next": None})


def _record(i):
    return {"id": 1000 + i, "title": f"Bando {i}", "url": f"/bandi/{i}/", "status": 1}


def _scraper_cursore(**extra):
    parametri = dict(
        api_url_template="https://esempio.it/api/?page=1",
        pagination_type="cursor",
        page_size=None,
        response_path="results",
        next_field="next",
        adapter="obiettivo_europa",
        rate_limit_s=0,
        max_pages=10,
        duplicate_threshold=None,
    )
    parametri.update(extra)
    return api_paginated.JsonApiPaginatedScraper(**parametri)


def _scrape(scraper, sessione, fonte=FONTE):
    with patch.object(scraper, "_make_session", lambda: sessione):
        return asyncio.run(scraper.scrape(fonte))


class TestBase(unittest.TestCase):
    def test_default_e_troncato(self):
        # «Non so» vale «non ho visto tutto»: e' il default piu' prudente.
        self.assertTrue(base.BandoScraper.ultimo_esito["troncato"])
        self.assertTrue(base.esito_iniziale()["troncato"])

    def test_le_tre_chiavi(self):
        self.assertEqual(set(base.esito_iniziale()), {"pagine", "troncato", "count"})

    def test_esito_costruisce_le_tre_chiavi(self):
        self.assertEqual(
            base.esito(3, troncato=False, count=120),
            {"pagine": 3, "troncato": False, "count": 120},
        )


class TestApiPaginated(unittest.TestCase):
    def test_cursore_esaurito_e_copertura_piena(self):
        scraper = _scraper_cursore()
        pagine = [
            {"results": [_record(i) for i in range(3)], "next": "https://esempio.it/api/?page=2"},
            {"results": [_record(i) for i in range(3, 6)], "next": None},
        ]
        items = _scrape(scraper, _Sessione(pagine))
        self.assertEqual(len(items), 6)
        self.assertFalse(scraper.ultimo_esito["troncato"])
        self.assertEqual(scraper.ultimo_esito["pagine"], 2)
        self.assertTrue(segnali.copertura_piena(scraper.ultimo_esito, len(items)))

    def test_pagina_vuota_chiude_la_lettura(self):
        scraper = _scraper_cursore()
        pagine = [
            {"results": [_record(i) for i in range(3)], "next": "https://esempio.it/api/?page=2"},
        ]
        items = _scrape(scraper, _Sessione(pagine))
        self.assertEqual(len(items), 3)
        self.assertFalse(scraper.ultimo_esito["troncato"])

    def test_errore_http_lascia_troncato(self):
        scraper = _scraper_cursore()
        items = _scrape(scraper, _Sessione([], stato=500))
        self.assertEqual(items, [])
        self.assertTrue(scraper.ultimo_esito["troncato"])
        self.assertFalse(segnali.copertura_piena(scraper.ultimo_esito, 0))

    def test_max_pages_lascia_troncato(self):
        scraper = _scraper_cursore(max_pages=2)
        pagine = [
            {"results": [_record(i) for i in range(3)], "next": "https://esempio.it/api/?page=2"},
            {"results": [_record(i) for i in range(3, 6)], "next": "https://esempio.it/api/?page=3"},
        ]
        _scrape(scraper, _Sessione(pagine))
        self.assertEqual(scraper.ultimo_esito["pagine"], 2)
        self.assertTrue(scraper.ultimo_esito["troncato"])

    def test_early_stop_sui_duplicati_lascia_troncato(self):
        scraper = _scraper_cursore(duplicate_threshold=2)
        # Seconda pagina tutta duplicata: lo scrape si ferma, ma non ha visto
        # tutto il listing.
        pagine = [
            {"results": [_record(0), _record(1)], "next": "https://esempio.it/api/?page=2"},
            {"results": [_record(0), _record(1)], "next": "https://esempio.it/api/?page=3"},
        ]
        _scrape(scraper, _Sessione(pagine))
        self.assertTrue(scraper.ultimo_esito["troncato"])

    def test_solr_conteggio_raggiunto(self):
        scraper = api_paginated.JsonApiPaginatedScraper(
            api_url_template="https://esempio.it/solr/?start={start}",
            pagination_type="solr_start",
            page_size=2,
            response_path="response.docs",
            total_field="response.numFound",
            adapter="incentivi_gov_it",
            rate_limit_s=0,
            max_pages=10,
            duplicate_threshold=None,
        )
        doc = lambda i: {"zs_title": f"Incentivo {i}", "zs_url": f"/it/{i}", "zs_nid": str(i)}
        pagine = [
            {"response": {"docs": [doc(0), doc(1)], "numFound": 4}},
            {"response": {"docs": [doc(2), doc(3)], "numFound": 4}},
        ]
        items = _scrape(scraper, _Sessione(pagine))
        self.assertEqual(len(items), 4)
        self.assertFalse(scraper.ultimo_esito["troncato"])
        self.assertEqual(scraper.ultimo_esito["count"], 4)
        self.assertTrue(segnali.copertura_piena(scraper.ultimo_esito, len(items)))

    def test_istanze_diverse_non_condividono_l_esito(self):
        primo = _scraper_cursore()
        secondo = _scraper_cursore()
        _scrape(primo, _Sessione([{"results": [_record(0)], "next": None}]))
        self.assertFalse(primo.ultimo_esito["troncato"])
        # Il secondo non ha ancora letto niente: non deve ereditare la
        # copertura del primo (l'attributo di classe e' condiviso).
        self.assertTrue(secondo.ultimo_esito["troncato"])
        self.assertTrue(base.BandoScraper.ultimo_esito["troncato"])


class TestApiPaginatedLogin(unittest.TestCase):
    def _scraper(self, **extra):
        parametri = dict(
            auth_provider="obiettivo_europa",
            api_url_template="https://www.obiettivoeuropa.com/api/call/?page=1",
            pagination_type="cursor",
            page_size=None,
            response_path="results",
            next_field="next",
            total_field="count",
            adapter="obiettivo_europa",
            rate_limit_s=0,
            max_pages=10,
            duplicate_threshold=None,
        )
        parametri.update(extra)
        return api_login.JsonApiPaginatedLoginScraper(**parametri)

    def test_pagine_per_cinquanta_non_coprono_il_totale(self):
        # Regola di §6.1 «OE: pagine x 50 >= count»: una sola pagina letta
        # contro un `count` di 1 702 e' una lettura parziale, anche se il
        # cursore si e' esaurito.
        scraper = self._scraper()
        pagine = [{"results": [_record(i) for i in range(50)], "next": None, "count": 1702}]
        items = _scrape(scraper, _Sessione(pagine))
        self.assertEqual(len(items), 50)
        self.assertTrue(scraper.ultimo_esito["troncato"])
        self.assertEqual(scraper.ultimo_esito["count"], 1702)

    def test_copertura_piena_quando_il_conto_torna(self):
        scraper = self._scraper()
        pagine = [{"results": [_record(i) for i in range(50)], "next": None, "count": 50}]
        items = _scrape(scraper, _Sessione(pagine))
        self.assertFalse(scraper.ultimo_esito["troncato"])
        self.assertTrue(segnali.copertura_piena(scraper.ultimo_esito, len(items)))

    def test_senza_count_resta_il_giudizio_della_base(self):
        scraper = self._scraper(total_field=None)
        pagine = [{"results": [_record(i) for i in range(3)], "next": None}]
        _scrape(scraper, _Sessione(pagine))
        self.assertFalse(scraper.ultimo_esito["troncato"])


class TestHttpxBs4(unittest.TestCase):
    PAGINA = (
        "<html><body>"
        "<a href='/bandi/uno'>Avviso uno</a>"
        "<a href='/bandi/due'>Avviso due</a>"
        "</body></html>"
    )

    def _scrape(self, scraper, risposte):
        async def finto(url):
            esito = risposte.pop(0)
            if isinstance(esito, Exception):
                raise esito
            return esito

        with patch.object(httpx_bs4, "fetch_html", finto):
            return asyncio.run(scraper.scrape(FONTE_HTML))

    def test_tutte_le_pagine_lette(self):
        scraper = httpx_bs4.HttpxBs4Scraper(
            link_selector="a[href^='/bandi/']",
            pagination={"type": "url_param", "param": "page", "range": [0, 1]},
            max_pages=20,
        )
        self._scrape(scraper, [self.PAGINA, self.PAGINA])
        self.assertEqual(scraper.ultimo_esito["pagine"], 2)
        self.assertFalse(scraper.ultimo_esito["troncato"])

    def test_una_pagina_fallita_lascia_troncato(self):
        scraper = httpx_bs4.HttpxBs4Scraper(
            link_selector="a[href^='/bandi/']",
            pagination={"type": "url_param", "param": "page", "range": [0, 1]},
            max_pages=20,
        )
        self._scrape(scraper, [self.PAGINA, httpx.ConnectError("giu'")])
        self.assertEqual(scraper.ultimo_esito["pagine"], 1)
        self.assertTrue(scraper.ultimo_esito["troncato"])
        self.assertFalse(segnali.copertura_piena(scraper.ultimo_esito, 2))

    def test_cap_max_pages_lascia_troncato(self):
        scraper = httpx_bs4.HttpxBs4Scraper(
            link_selector="a[href^='/bandi/']",
            pagination={"type": "url_param", "param": "page", "range": [0, 9]},
            max_pages=2,
        )
        self._scrape(scraper, [self.PAGINA, self.PAGINA])
        self.assertEqual(scraper.ultimo_esito["pagine"], 2)
        self.assertTrue(scraper.ultimo_esito["troncato"])

    def test_pagina_singola(self):
        scraper = httpx_bs4.HttpxBs4Scraper(
            link_selector="a[href^='/bandi/']", max_pages=20)
        items = self._scrape(scraper, [self.PAGINA])
        self.assertEqual(len(items), 2)
        self.assertFalse(scraper.ultimo_esito["troncato"])


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
