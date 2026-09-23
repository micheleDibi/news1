# -*- coding: utf-8 -*-
"""Login Obiettivo Europa e scraper json_api_paginated_login: nessuna rete.

`requests.Session` viene sostituita da una sessione finta che risponde alla
pagina di login, al POST e a `/api/call/?page=1`; il backoff usa una funzione
di attesa finta. Coperto:
  - login ok → sessione validata (>= 50 risultati) e messa in cache;
  - login ko → SessioneOEError dopo 3 tentativi con attese 60/120 s;
  - login ok ma 5 risultati (sessione anonima) → SessioneOEError;
  - cache non piu' valida → rinnovo;
  - credenziali mancanti → SessioneOEError senza alcuna chiamata HTTP;
  - il CSRF non compare nei log; username/password mai nei messaggi;
  - lo scraper con login NON ripiega mai sulla sessione anonima e logga
    '[ALLARME] login Obiettivo Europa fallito';
  - `min_risultati_prima_pagina` fa fallire la prima pagina corta.
"""
from __future__ import annotations

import asyncio
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from loguru import logger

from tests.supporto import carica_modulo

oe = carica_modulo("scrapers.auth.obiettivo_europa")
auth_pkg = carica_modulo("scrapers.auth")
api_paginated = carica_modulo("scrapers.api_paginated")
api_login = carica_modulo("scrapers.api_paginated_login")

UTENTE = "utente-di-test@example.invalid"
PASSWORD = "parola-segreta-di-test"
CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
LOGIN_URL = "https://www.obiettivoeuropa.com/account/login/"
API_URL = "https://www.obiettivoeuropa.com/api/call/"


def _record_oe(i: int) -> dict:
    return {"id": i, "title": f"Bando di prova {i}", "url": f"/bandi/bando-di-prova-{i}/"}


class RispostaFinta:
    def __init__(self, status_code=200, text="", json_data=None, url=""):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.url = url

    def json(self):
        if self._json is None:
            raise ValueError("risposta non JSON")
        return self._json


class Scenario:
    """Stato condiviso tra le SessioneFinta create in un test."""

    def __init__(self, login_ok=True, risultati=50, post_esplode=False):
        self.login_ok = login_ok
        # int, oppure lista consumata in ordine (l'ultimo valore si ripete)
        self.risultati = risultati
        self.post_esplode = post_esplode
        self.post = 0
        self.get_api = 0
        self.sessioni = 0

    def prossimi_risultati(self) -> int:
        if isinstance(self.risultati, list):
            if len(self.risultati) > 1:
                return self.risultati.pop(0)
            return self.risultati[0]
        return self.risultati


class SessioneFinta:
    """Sostituto di requests.Session: nessuna rete."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        scenario.sessioni += 1

    def get(self, url, **kw):
        if url == LOGIN_URL:
            return RispostaFinta(
                200,
                text=f'<form><input type=hidden name=csrfmiddlewaretoken value={CSRF}></form>',
            )
        if url.startswith(API_URL):
            self.scenario.get_api += 1
            n = self.scenario.prossimi_risultati()
            return RispostaFinta(
                200, json_data={"results": [_record_oe(i) for i in range(n)], "next": None},
            )
        raise AssertionError(f"GET inatteso: {url}")

    def post(self, url, data=None, **kw):
        assert url == LOGIN_URL
        self.scenario.post += 1
        if self.scenario.post_esplode:
            raise ConnectionError("rete assente")
        assert data["csrfmiddlewaretoken"] == CSRF
        if self.scenario.login_ok and data["password"] == PASSWORD:
            self.cookies["sessionid"] = "sessione-finta"
            return RispostaFinta(200, url="https://www.obiettivoeuropa.com/area-personale/")
        return RispostaFinta(200, url=LOGIN_URL)


@contextmanager
def sessione_finta(scenario: Scenario):
    with patch("requests.Session", lambda: SessioneFinta(scenario)):
        yield


@contextmanager
def cattura_log():
    messaggi: list[str] = []
    hid = logger.add(lambda m: messaggi.append(m.record["message"]), level="TRACE")
    try:
        yield messaggi
    finally:
        logger.remove(hid)


def _nessun_segreto(testo: str) -> bool:
    return UTENTE not in testo and PASSWORD not in testo and CSRF[:12] not in testo


class TestObtainSession(unittest.TestCase):
    def setUp(self):
        oe.clear_cache()
        self.attese: list[float] = []

    def tearDown(self):
        oe.clear_cache()

    def test_costanti_di_rinnovo(self):
        self.assertEqual(oe.RISULTATI_MINIMI_AUTENTICATO, 50)
        self.assertEqual(oe.TENTATIVI_MAX, 3)
        self.assertEqual(oe.BACKOFF_S, (60, 120, 240))
        self.assertTrue(issubclass(oe.SessioneOEError, RuntimeError))

    def test_login_ok_valida_e_mette_in_cache(self):
        sc = Scenario(login_ok=True, risultati=50)
        with sessione_finta(sc):
            s1 = oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
            self.assertIsInstance(s1, SessioneFinta)
            self.assertEqual(s1.headers["Accept"], "application/json")
            self.assertEqual(sc.post, 1)
            self.assertEqual(sc.get_api, 1)  # validazione dopo il login
            self.assertEqual(self.attese, [])

            # Seconda chiamata: la cache viene rivalidata con l'API, non con il cookie
            s2 = oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
            self.assertIs(s2, s1)
            self.assertEqual(sc.post, 1)
            self.assertEqual(sc.get_api, 2)

    def test_login_ko_solleva_dopo_backoff_senza_ripiego(self):
        sc = Scenario(login_ok=False)
        with sessione_finta(sc), cattura_log() as log:
            with self.assertRaises(oe.SessioneOEError) as ctx:
                oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
        self.assertEqual(sc.post, 3)
        self.assertEqual(self.attese, [60, 120])
        messaggio = str(ctx.exception)
        self.assertIn("3 tentativi", messaggio)
        self.assertTrue(_nessun_segreto(messaggio), messaggio)
        self.assertTrue(_nessun_segreto(str(ctx.exception.__cause__)))
        self.assertTrue(all(_nessun_segreto(m) for m in log), log)

    def test_cinque_risultati_e_sessione_anonima(self):
        sc = Scenario(login_ok=True, risultati=5)
        with sessione_finta(sc):
            with self.assertRaises(oe.SessioneOEError) as ctx:
                oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
        messaggio = str(ctx.exception)
        self.assertIn("5 risultati", messaggio)
        self.assertIn("50", messaggio)
        self.assertEqual(sc.post, 3)
        self.assertEqual(self.attese, [60, 120])
        self.assertTrue(_nessun_segreto(messaggio), messaggio)
        with self.assertRaises(oe.SessioneOEError):
            # Anche dopo il fallimento non resta nulla in cache
            with patch("requests.Session", lambda: SessioneFinta(Scenario(login_ok=False))):
                oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)

    def test_cache_non_valida_viene_rinnovata(self):
        # 1° obtain: login + validazione (50). 2° obtain: la cache risponde 5 →
        # rinnovo → nuovo login validato a 50.
        sc = Scenario(login_ok=True, risultati=[50, 5, 50])
        with sessione_finta(sc):
            s1 = oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
            s2 = oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
        self.assertIsNot(s2, s1)
        self.assertEqual(sc.post, 2)
        self.assertEqual(self.attese, [])

    def test_valida_sessione(self):
        sc = Scenario(risultati=[50, 5])
        s = SessioneFinta(sc)
        self.assertTrue(oe.valida_sessione(s))
        self.assertFalse(oe.valida_sessione(s))

        class SessioneRotta:
            def get(self, *a, **k):
                raise ConnectionError("rete assente")

        self.assertFalse(oe.valida_sessione(SessioneRotta()))

    def test_credenziali_mancanti_senza_chiamate_http(self):
        sc = Scenario()
        with sessione_finta(sc):
            for u, p in (("", ""), (UTENTE, ""), ("", PASSWORD), (None, None)):
                with self.assertRaises(oe.SessioneOEError) as ctx:
                    oe.obtain_session(u, p, attesa=self.attese.append)
                self.assertIn("OBIETTIVO_EUROPA_USERNAME", str(ctx.exception))
        self.assertEqual(sc.sessioni, 0)
        self.assertEqual(self.attese, [])

    def test_csrf_e_credenziali_mai_nei_log(self):
        sc = Scenario(login_ok=True, risultati=50)
        with sessione_finta(sc), cattura_log() as log:
            oe.obtain_session(UTENTE, PASSWORD, attesa=self.attese.append)
        self.assertTrue(log, "atteso almeno il log di login OK")
        for m in log:
            self.assertNotIn(CSRF[:12], m)
            self.assertTrue(_nessun_segreto(m), m)

    def test_credenziali_hanno_repr_opaco(self):
        cred = oe.Credenziali(UTENTE, PASSWORD)
        self.assertTrue(_nessun_segreto(repr(cred)))
        self.assertEqual(list(cred), [UTENTE, PASSWORD])
        self.assertFalse(oe.Credenziali("", PASSWORD))


def _parametri_oe(**extra) -> dict:
    return dict(
        api_url_template="https://www.obiettivoeuropa.com/api/call/?page=1&ordering=-published",
        pagination_type="cursor",
        page_size=None,
        response_path="results",
        next_field="next",
        adapter="obiettivo_europa",
        rate_limit_s=0,
        **extra,
    )


class TestScraperLogin(unittest.TestCase):
    """json_api_paginated_login: mai ripiego anonimo."""

    FONTE = {"id": 449, "link": API_URL, "tipo_link": "Opportunità", "formato_link": "JSON"}

    def setUp(self):
        oe.clear_cache()

    def test_credenziali_mancanti_fanno_fallire_la_fonte(self):
        # settings di test: OBIETTIVO_EUROPA_USERNAME/PASSWORD vuoti (tests/supporto.py)
        scraper = api_login.JsonApiPaginatedLoginScraper(
            auth_provider="obiettivo_europa", **_parametri_oe(),
        )

        def sessione_vietata():
            raise AssertionError("nessuna sessione anonima deve essere creata")

        with patch("requests.Session", sessione_vietata), cattura_log() as log:
            with self.assertRaises(oe.SessioneOEError):
                scraper._make_session()
            with self.assertRaises(oe.SessioneOEError):
                asyncio.run(scraper.scrape(self.FONTE))
        allarmi = [m for m in log if m.startswith("[ALLARME] login Obiettivo Europa fallito")]
        self.assertEqual(len(allarmi), 2, log)

    def test_provider_fallito_non_ripiega(self):
        scraper = api_login.JsonApiPaginatedLoginScraper(
            auth_provider="obiettivo_europa", username=UTENTE, password=PASSWORD,
            **_parametri_oe(),
        )
        chiamate: list[tuple[str, str]] = []

        def provider_ko(username, password):
            chiamate.append((username, password))
            raise oe.SessioneOEError("login Obiettivo Europa fallito dopo 3 tentativi")

        def provider_generico(username, password):
            raise RuntimeError("errore imprevisto")

        def sessione_vietata():
            raise AssertionError("nessuna sessione anonima deve essere creata")

        with patch("requests.Session", sessione_vietata):
            with patch.object(auth_pkg, "get_auth_provider", lambda name: provider_ko):
                with cattura_log() as log:
                    with self.assertRaises(oe.SessioneOEError) as ctx:
                        scraper._make_session()
            self.assertEqual(chiamate, [(UTENTE, PASSWORD)])
            self.assertTrue(_nessun_segreto(str(ctx.exception)))
            self.assertTrue(any("[ALLARME] login Obiettivo Europa fallito" in m for m in log), log)
            self.assertTrue(all(_nessun_segreto(m) for m in log), log)

            with patch.object(auth_pkg, "get_auth_provider", lambda name: provider_generico):
                with self.assertRaises(oe.SessioneOEError) as ctx:
                    scraper._make_session()
            self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_traceback_con_diagnose_senza_segreti(self):
        # Il runner fa logger.exception() sull'errore di scrape(): con
        # diagnose=True loguru stampa i valori delle variabili delle righe
        # fallite. Le credenziali viaggiano in oggetti con repr opaco e non
        # devono comparire, in nessuna frame del traceback ne' nella catena.
        scraper = api_login.JsonApiPaginatedLoginScraper(
            auth_provider="obiettivo_europa", username=UTENTE, password=PASSWORD,
            **_parametri_oe(),
        )
        for scenario in (Scenario(login_ok=False), Scenario(post_esplode=True)):
            formattati: list[str] = []
            hid = logger.add(formattati.append, level="ERROR", backtrace=True, diagnose=True)
            try:
                # Qui il provider e' quello reale (nessun `attesa` iniettabile
                # dallo scraper): il backoff va azzerato o il test dormirebbe 3'.
                with sessione_finta(scenario), patch.object(oe, "BACKOFF_S", (0, 0, 0)):
                    try:
                        asyncio.run(scraper.scrape(self.FONTE))
                    except oe.SessioneOEError as e:
                        logger.exception("[bando_runner] fonte_id=449 scrape fallito: {}", e)
            finally:
                logger.remove(hid)
            traceback_completo = "".join(formattati)
            self.assertIn("Traceback", traceback_completo)
            self.assertIn("_login", traceback_completo)  # le frame interne ci sono
            self.assertTrue(_nessun_segreto(traceback_completo), traceback_completo)

    def test_provider_ok_ritorna_la_sessione_autenticata(self):
        scraper = api_login.JsonApiPaginatedLoginScraper(
            auth_provider="obiettivo_europa", username=UTENTE, password=PASSWORD,
            **_parametri_oe(min_risultati_prima_pagina=50),
        )
        sc = Scenario(login_ok=True, risultati=50)
        with sessione_finta(sc):
            items = asyncio.run(scraper.scrape(self.FONTE))
        self.assertEqual(len(items), 50)
        self.assertEqual(sc.post, 1)


class SessioneApiFinta:
    def __init__(self, n: int):
        self.n = n
        self.headers: dict[str, str] = {}

    def get(self, url, params=None, timeout=None):
        return RispostaFinta(
            200, json_data={"results": [_record_oe(i) for i in range(self.n)], "next": None},
        )


class TestMinRisultatiPrimaPagina(unittest.TestCase):
    FONTE = {"id": 449, "link": API_URL, "tipo_link": "Opportunità", "formato_link": "JSON"}

    def _scrape(self, scraper, n):
        with patch.object(scraper, "_make_session", lambda: SessioneApiFinta(n)):
            return asyncio.run(scraper.scrape(self.FONTE))

    def test_default_nessun_controllo(self):
        scraper = api_paginated.JsonApiPaginatedScraper(**_parametri_oe())
        self.assertIsNone(scraper.min_risultati_prima_pagina)
        self.assertEqual(len(self._scrape(scraper, 5)), 5)

    def test_prima_pagina_corta_solleva(self):
        scraper = api_paginated.JsonApiPaginatedScraper(
            **_parametri_oe(min_risultati_prima_pagina=50),
        )
        with self.assertRaises(api_paginated.RisultatiInsufficientiError) as ctx:
            self._scrape(scraper, 5)
        self.assertIn("5 risultati", str(ctx.exception))
        self.assertIn("50", str(ctx.exception))
        with self.assertRaises(api_paginated.RisultatiInsufficientiError):
            self._scrape(scraper, 0)
        self.assertEqual(len(self._scrape(scraper, 50)), 50)

    def test_con_login_solleva_sessione_oe_error(self):
        scraper = api_login.JsonApiPaginatedLoginScraper(
            auth_provider="obiettivo_europa", **_parametri_oe(min_risultati_prima_pagina=50),
        )
        with cattura_log() as log:
            with self.assertRaises(oe.SessioneOEError):
                self._scrape(scraper, 5)
        self.assertTrue(any(m.startswith("[ALLARME] login Obiettivo Europa fallito") for m in log), log)


if __name__ == "__main__":
    unittest.main()
