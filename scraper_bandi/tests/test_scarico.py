# -*- coding: utf-8 -*-
"""Scarico unico del giro (piano §6.2, fix 8.a.1/8.a.2/8.a.12/8.a.27).

Rete finta con `httpx.MockTransport` e ripiego Firecrawl finto: nessun test
tocca la rete, la chiave Firecrawl o il DB.
"""
import asyncio
import unittest

import httpx

from tests.supporto import carica_modulo

scarico = carica_modulo("scarico")


async def _niente_throttle(_host: str) -> None:
    """Il throttle vero dorme un secondo per host: nei test non serve."""


async def _niente_attesa(_secondi: float) -> None:
    """Sostituisce `asyncio.sleep` nel backoff: i ritentativi restano istantanei."""


class _Orologio:
    """Tempo pilotato, per far scadere la cache senza aspettare un'ora."""

    def __init__(self) -> None:
        self.adesso = 1000.0

    def __call__(self) -> float:
        return self.adesso

    def avanza(self, secondi: float) -> None:
        self.adesso += secondi


def _costruisci(risposte, *, firecrawl=None, **kwargs):
    """`risposte` e' una lista di `httpx.Response` o un callable(request)."""
    chiamate: list[httpx.Request] = []

    if callable(risposte):
        def gestore(request: httpx.Request) -> httpx.Response:
            chiamate.append(request)
            return risposte(request)
    else:
        coda = list(risposte)

        def gestore(request: httpx.Request) -> httpx.Response:
            chiamate.append(request)
            return coda.pop(0) if coda else httpx.Response(404)

    s = scarico.Scarico(
        transport=httpx.MockTransport(gestore),
        firecrawl=firecrawl,
        throttle=_niente_throttle,
        dormi=_niente_attesa,
        **kwargs,
    )
    return s, chiamate


def _esegui(corutina):
    return asyncio.run(corutina)


PAGINA = "<html><body><h1>Bando</h1><p>Testo della pagina ufficiale.</p></body></html>"


class TestBlocklist(unittest.TestCase):
    def test_i_dieci_aggregatori_del_piano(self):
        self.assertEqual(len(scarico.AGGREGATORI), 10)
        self.assertIn("obiettivoeuropa.com", scarico.AGGREGATORI)

    def test_host_e_sottodomini(self):
        self.assertTrue(scarico.in_blocklist("https://www.obiettivoeuropa.com/bandi/1"))
        self.assertTrue(scarico.in_blocklist("https://api.fasi.eu/call"))
        self.assertTrue(scarico.in_blocklist("ticonsiglio.com"))
        self.assertFalse(scarico.in_blocklist("https://regione.lazio.it/bandi"))
        # Non basta contenere il nome: dev'essere l'host o un suo sottodominio.
        self.assertFalse(scarico.in_blocklist("https://nonbandi.it/x"))

    def test_host_senza_schema_con_percorso_o_porta(self):
        # Senza schema `urlsplit` mette tutto nel path e l'host sarebbe vuoto:
        # il vietato passerebbe inosservato.
        self.assertTrue(scarico.in_blocklist("obiettivoeuropa.com/bandi/1"))
        self.assertTrue(scarico.in_blocklist("www.fasi.eu:443"))
        self.assertFalse(scarico.in_blocklist("regione.lazio.it:8080"))

    def test_scarico_come_fonte_di_un_aggregatore_solleva_e_non_fa_richieste(self):
        # La denylist vale per la FONTE UFFICIALE (fix 8.a.12), non per ogni
        # scarico: la si chiede con `come_fonte=True`.
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)])
        with self.assertRaises(scarico.ScaricoVietatoError):
            _esegui(s.scarica("https://www.obiettivoeuropa.com/api/call/", come_fonte=True))
        self.assertEqual(chiamate, [])
        self.assertEqual(s.contatori.vietati, 1)

    def test_la_scheda_di_un_aggregatore_si_scarica(self):
        # `link_bando` di migliaia di righe e' una pagina di obiettivoeuropa.com:
        # vietarla a tappeto manderebbe in 'rejected' ogni bando OE nuovo.
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)])
        scarico.imposta_scarico(s)
        try:
            testo = _esegui(scarico.scarica_markdown("https://www.obiettivoeuropa.com/bandi/x/"))
        finally:
            scarico.imposta_scarico(None)
        self.assertIn("Testo della pagina", testo)
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(s.contatori.vietati, 0)

    def test_blocklist_iniettabile(self):
        s, _ = _costruisci([httpx.Response(200, text=PAGINA)], blocklist={"esempio.it"})
        # Iniettata nel costruttore vale sempre, anche senza `come_fonte`.
        with self.assertRaises(scarico.ScaricoVietatoError):
            _esegui(s.scarica("https://esempio.it/x"))
        # Con una blocklist diversa gli aggregatori non sono piu' vietati.
        self.assertFalse(scarico.in_blocklist("https://fasi.eu", {"esempio.it"}))


class TestCache(unittest.TestCase):
    def test_due_chiamate_un_solo_fetch(self):
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)])
        primo = _esegui(s.scarica("https://ente.it/bando"))
        secondo = _esegui(s.scarica("https://ente.it/bando"))
        self.assertEqual(len(chiamate), 1)
        self.assertEqual(primo.testo, secondo.testo)
        self.assertFalse(primo.da_cache)
        self.assertTrue(secondo.da_cache)
        self.assertEqual(s.contatori.fetch, 1)
        self.assertEqual(s.contatori.da_cache, 1)

    def test_il_fallimento_non_entra_in_cache(self):
        # E' il difetto 8.a.1: con `_FIRECRAWL_CACHE` un 500 restava per sempre.
        s, chiamate = _costruisci([
            httpx.Response(500, text="errore"),
            httpx.Response(500, text="errore"),
            httpx.Response(500, text="errore"),
            httpx.Response(200, text=PAGINA),
        ])
        primo = _esegui(s.scarica("https://ente.it/bando"))
        self.assertEqual(primo.stato, 500)
        secondo = _esegui(s.scarica("https://ente.it/bando"))
        self.assertIn("Testo della pagina", secondo.testo)
        self.assertFalse(secondo.da_cache)

    def test_il_corpo_vuoto_non_entra_in_cache(self):
        s, chiamate = _costruisci([httpx.Response(200, text=""), httpx.Response(200, text=PAGINA)])
        self.assertEqual(_esegui(s.scarica("https://ente.it/x")).testo, "")
        self.assertIn("Bando", _esegui(s.scarica("https://ente.it/x")).testo)
        self.assertEqual(len(chiamate), 2)

    def test_ttl_scaduto_rifa_il_fetch(self):
        orologio = _Orologio()
        s, chiamate = _costruisci(
            [httpx.Response(200, text=PAGINA), httpx.Response(200, text=PAGINA)],
            ttl_s=3600.0, orologio=orologio,
        )
        _esegui(s.scarica("https://ente.it/x"))
        orologio.avanza(3601)
        _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(len(chiamate), 2)

    def test_svuota_azzera_la_cache_ma_non_i_contatori(self):
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)] * 2)
        _esegui(s.scarica("https://ente.it/x"))
        s.svuota()
        _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(len(chiamate), 2)
        self.assertEqual(s.contatori.fetch, 2)
        s.nuovo_giro()
        self.assertEqual(s.contatori.fetch, 0)


class TestRitentativi(unittest.TestCase):
    def test_un_500_poi_il_successo(self):
        s, chiamate = _costruisci([httpx.Response(503), httpx.Response(200, text=PAGINA)])
        risposta = _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(len(chiamate), 2)

    def test_tre_tentativi_al_massimo(self):
        s, chiamate = _costruisci([httpx.Response(503)] * 5)
        risposta = _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(risposta.stato, 503)
        self.assertEqual(len(chiamate), 3)          # 1 tentativo + 2 ritentativi

    def test_429_e_ritentabile(self):
        s, chiamate = _costruisci([httpx.Response(429), httpx.Response(200, text=PAGINA)])
        self.assertEqual(_esegui(s.scarica("https://ente.it/x")).stato, 200)
        self.assertEqual(len(chiamate), 2)

    def test_404_non_si_ritenta(self):
        s, chiamate = _costruisci([httpx.Response(404), httpx.Response(200, text=PAGINA)])
        self.assertEqual(_esegui(s.scarica("https://ente.it/x")).stato, 404)
        self.assertEqual(len(chiamate), 1)

    def test_timeout_ritentato_poi_risposta_senza_stato(self):
        def gestore(_request):
            raise httpx.ConnectTimeout("timeout")
        s, chiamate = _costruisci(gestore)
        risposta = _esegui(s.scarica("https://ente.it/x"))
        self.assertIsNone(risposta.stato)
        self.assertEqual(len(chiamate), 3)
        self.assertEqual(s.contatori.errori, 1)

    def test_timeout_conta_i_tentativi_nel_fetch(self):
        # `tetto_fetch_giro` e' l'unico tetto per giro: se i timeout non si
        # contassero, una fonte irraggiungibile busserebbe a costo zero.
        def gestore(_request):
            raise httpx.ConnectTimeout("timeout")
        s, chiamate = _costruisci(gestore)
        _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(len(chiamate), 3)
        self.assertEqual(s.contatori.fetch, 3)


class TestCondizionale(unittest.TestCase):
    def test_304_conta_a_parte_e_non_entra_in_cache(self):
        s, chiamate = _costruisci([httpx.Response(304), httpx.Response(200, text=PAGINA)])
        risposta = _esegui(s.scarica("https://ente.it/x", etag='"abc"'))
        self.assertEqual(risposta.stato, 304)
        self.assertEqual(s.contatori.fetch_304, 1)
        self.assertEqual(chiamate[0].headers["if-none-match"], '"abc"')
        _esegui(s.scarica("https://ente.it/x"))
        self.assertEqual(len(chiamate), 2)

    def test_if_modified_since(self):
        s, chiamate = _costruisci([httpx.Response(304)])
        _esegui(s.scarica("https://ente.it/x", modificata_dopo="Mon, 22 Sep 2026 10:00:00 GMT"))
        self.assertIn("if-modified-since", chiamate[0].headers)


class TestLimiteDimensione(unittest.TestCase):
    def test_corpo_oltre_il_limite_viene_troncato(self):
        grosso = "<html><body>" + ("x" * 5000) + "</body></html>"
        s, _ = _costruisci([httpx.Response(200, text=grosso)], limite_byte=1000)
        risposta = _esegui(s.scarica("https://ente.it/x"))
        self.assertTrue(risposta.troncata)
        self.assertLessEqual(len(risposta.html.encode("utf-8", "replace")), 1000)


class TestRipiegoFirecrawl(unittest.TestCase):
    def _firecrawl_finto(self, chiamate: list):
        async def finto(url: str) -> dict:
            chiamate.append(url)
            return {"html": "<html><body>Testo reso dal browser</body></html>",
                    "markdown": "# Bando\n\nTesto reso dal browser"}
        return finto

    def test_403_sulla_pagina_principale_ripiega(self):
        fatte: list[str] = []
        s, _ = _costruisci([httpx.Response(403)], firecrawl=self._firecrawl_finto(fatte))
        risposta = _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(fatte, ["https://ente.it/bando"])
        self.assertEqual(risposta.via, "firecrawl")
        self.assertEqual(s.contatori.crediti_firecrawl, 1)

    def test_le_sottopagine_non_ripiegano_mai(self):
        fatte: list[str] = []
        s, _ = _costruisci([httpx.Response(403)], firecrawl=self._firecrawl_finto(fatte))
        risposta = _esegui(s.scarica("https://ente.it/allegati/modulo"))
        self.assertEqual(fatte, [])
        self.assertEqual(risposta.stato, 403)
        self.assertEqual(s.contatori.crediti_firecrawl, 0)

    def test_app_shell_ripiega(self):
        shell = "<html><head>" + "<script>var a=1;" + "y" * 900 + "</script></head><body></body></html>"
        fatte: list[str] = []
        s, _ = _costruisci([httpx.Response(200, text=shell)], firecrawl=self._firecrawl_finto(fatte))
        risposta = _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(len(fatte), 1)
        self.assertIn("browser", risposta.markdown)

    def test_pagina_piena_non_ripiega(self):
        fatte: list[str] = []
        testo = "<html><body><p>" + ("parola " * 200) + "</p></body></html>"
        s, _ = _costruisci([httpx.Response(200, text=testo)], firecrawl=self._firecrawl_finto(fatte))
        _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(fatte, [])
        self.assertEqual(s.contatori.crediti_firecrawl, 0)

    def test_host_richiede_js_ripiega_subito(self):
        fatte: list[str] = []
        testo = "<html><body><p>" + ("parola " * 200) + "</p></body></html>"
        s, _ = _costruisci(
            [httpx.Response(200, text=testo)],
            firecrawl=self._firecrawl_finto(fatte),
            host_richiede_js={"ente.it"},
        )
        _esegui(s.scarica("https://www.ente.it/bando", principale=True))
        self.assertEqual(len(fatte), 1)

    def test_host_richiede_js_su_app_shell_ripiega(self):
        shell = "<html><head><script>var a=1;" + "y" * 900 + "</script></head><body></body></html>"
        fatte: list[str] = []
        s, _ = _costruisci(
            [httpx.Response(200, text=shell)],
            firecrawl=self._firecrawl_finto(fatte),
            host_richiede_js={"ente.it"},
        )
        risposta = _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(len(fatte), 1)
        self.assertIn("browser", risposta.markdown)

    def test_host_richiede_js_ma_pagina_morta_non_paga_il_credito(self):
        # Nel monitor il 404/410 e' il segnale cercato: non deve costare un
        # credito a ogni controllo solo perche' l'host e' a JS.
        fatte: list[str] = []
        for stato in (404, 410, 500):
            with self.subTest(stato=stato):
                risposte = [httpx.Response(stato)] * 3   # i 5xx si ritentano
                s, _ = _costruisci(
                    risposte,
                    firecrawl=self._firecrawl_finto(fatte),
                    host_richiede_js={"ente.it"},
                )
                _esegui(s.scarica("https://ente.it/bando", principale=True))
                self.assertEqual(fatte, [])
                self.assertEqual(s.contatori.crediti_firecrawl, 0)

    def test_host_richiede_js_ma_rete_caduta_non_paga_il_credito(self):
        fatte: list[str] = []

        def gestore(_request):
            raise httpx.ConnectTimeout("timeout")

        s, _ = _costruisci(
            gestore, firecrawl=self._firecrawl_finto(fatte), host_richiede_js={"ente.it"},
        )
        _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(fatte, [])
        self.assertEqual(s.contatori.crediti_firecrawl, 0)

    def test_ripiego_fallito_lascia_la_risposta_httpx_e_conta_il_credito(self):
        async def esplode(_url: str) -> dict:
            raise RuntimeError("Firecrawl giu'")
        s, _ = _costruisci([httpx.Response(403)], firecrawl=esplode)
        risposta = _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(risposta.stato, 403)
        # Il credito si conta comunque: una chiamata fallita puo' essere stata
        # fatturata e il tetto deve restare pessimista.
        self.assertEqual(s.contatori.crediti_firecrawl, 1)

    def test_304_non_ripiega(self):
        fatte: list[str] = []
        s, _ = _costruisci([httpx.Response(304)], firecrawl=self._firecrawl_finto(fatte))
        _esegui(s.scarica("https://ente.it/bando", principale=True, etag='"a"'))
        self.assertEqual(fatte, [])


class TestAppShell(unittest.TestCase):
    def test_soglie(self):
        self.assertFalse(scarico.e_app_shell("", ""))
        molto_testo = "parola " * 200
        self.assertFalse(scarico.e_app_shell(f"<html>{molto_testo}</html>", molto_testo))
        shell = "<html><script>" + "z" * 800 + "</script><body>ciao</body></html>"
        self.assertTrue(scarico.e_app_shell(shell, "ciao"))


class TestNessunTroncamentoAllaSorgente(unittest.TestCase):
    def test_il_testo_arriva_intero(self):
        # Fix 8.a.2: il budget e' del prompt, non della cache.
        lungo = "<html><body><p>" + ("a" * 9000) + "</p></body></html>"
        s, _ = _costruisci([httpx.Response(200, text=lungo)])
        risposta = _esegui(s.scarica("https://ente.it/x"))
        self.assertGreater(len(risposta.testo), 8000)


class TestSottopagine(unittest.TestCase):
    def test_sottopagina_fallita_si_salta_e_si_conta(self):
        s, _ = _costruisci([httpx.Response(500)] * 3)
        _esegui(s.scarica("https://ente.it/allegati/modulo"))
        self.assertEqual(s.contatori.sottopagine_saltate, 1)
        self.assertEqual(s.contatori.crediti_firecrawl, 0)

    def test_sottopagina_vuota_si_conta(self):
        s, _ = _costruisci([httpx.Response(200, text="")])
        _esegui(s.scarica("https://ente.it/allegati/modulo"))
        self.assertEqual(s.contatori.sottopagine_saltate, 1)

    def test_sottopagina_riuscita_e_304_non_si_contano(self):
        s, _ = _costruisci([httpx.Response(200, text=PAGINA), httpx.Response(304)])
        _esegui(s.scarica("https://ente.it/allegati/a"))
        _esegui(s.scarica("https://ente.it/allegati/b", etag='"x"'))
        self.assertEqual(s.contatori.sottopagine_saltate, 0)

    def test_la_pagina_principale_non_conta_come_sottopagina(self):
        s, _ = _costruisci([httpx.Response(404)])
        _esegui(s.scarica("https://ente.it/bando", principale=True))
        self.assertEqual(s.contatori.sottopagine_saltate, 0)


class TestCicloDiVita(unittest.TestCase):
    def test_due_giri_in_due_event_loop(self):
        """Il sender fa un `asyncio.run` per giro nello stesso processo: il
        client non puo' sopravvivere al loop che l'ha creato."""
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)] * 4)

        primo = _esegui(s.scarica("https://ente.it/x"))
        client_primo_giro = s._client
        self.assertEqual(primo.stato, 200)
        self.assertEqual(s.contatori.fetch, 1)

        s.nuovo_giro()                       # inizio del giro successivo
        secondo = _esegui(s.scarica("https://ente.it/x"))   # loop nuovo

        self.assertEqual(secondo.stato, 200)
        self.assertFalse(secondo.da_cache)   # la cache e' del giro, non del processo
        self.assertEqual(s.contatori.fetch, 1)              # contatori ripartiti da zero
        self.assertEqual(len(chiamate), 2)
        self.assertIsNot(s._client, client_primo_giro)      # client ricostruito

    def test_chiudi_dopo_la_fine_del_loop_non_solleva(self):
        s, _ = _costruisci([httpx.Response(200, text=PAGINA)])
        _esegui(s.scarica("https://ente.it/x"))
        # Il loop del giro e' gia' chiuso: `aclose()` solleverebbe.
        _esegui(s.chiudi())
        self.assertIsNone(s._client)

    def test_chiudi_nello_stesso_loop_chiude_il_client(self):
        s, _ = _costruisci([httpx.Response(200, text=PAGINA)])

        async def giro():
            await s.scarica("https://ente.it/x")
            client = s._client
            await s.chiudi()
            return client

        client = _esegui(giro())
        self.assertIsNone(s._client)
        self.assertTrue(client.is_closed)


class TestWrapperStorici(unittest.TestCase):
    """I due nomi che i quattro chiamanti importano da `enricher`."""

    def setUp(self):
        self.enricher = carica_modulo("enricher")

    def tearDown(self):
        scarico.imposta_scarico(None)

    def test_la_scheda_su_un_aggregatore_arriva_ai_chiamanti(self):
        # E' il `link_bando` dei bandi di Obiettivo Europa: se tornasse ""
        # il preprocess chiederebbe il fallback, il resolver fallirebbe a sua
        # volta e il bando finirebbe in 'rejected', che e' terminale.
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)] * 2)
        scarico.imposta_scarico(s)
        markdown = _esegui(
            self.enricher._firecrawl_scrape_markdown("https://www.obiettivoeuropa.com/bandi/x/"))
        testo = _esegui(
            self.enricher._httpx_fetch_text("https://www.obiettivoeuropa.com/bandi/x/"))
        self.assertIn("Testo della pagina", markdown)
        self.assertIn("Testo della pagina", testo)
        self.assertEqual(s.contatori.vietati, 0)
        self.assertEqual(len(chiamate), 1)          # il secondo arriva dalla cache

    def test_come_fonte_su_un_aggregatore_torna_vuoto(self):
        # Fix 8.a.12: l'endpoint API dell'aggregatore non e' una fonte ufficiale.
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)])
        scarico.imposta_scarico(s)
        vuoto = _esegui(self.enricher._firecrawl_scrape_markdown(
            "https://www.obiettivoeuropa.com/api/call/", come_fonte=True))
        self.assertEqual(vuoto, "")
        self.assertEqual(chiamate, [])
        self.assertEqual(s.contatori.vietati, 1)

    def test_come_fonte_su_un_host_lecito_scarica(self):
        s, _ = _costruisci([httpx.Response(200, text=PAGINA)])
        scarico.imposta_scarico(s)
        testo = _esegui(self.enricher._httpx_fetch_text(
            "https://regione.lazio.it/bando", come_fonte=True))
        self.assertIn("Testo della pagina", testo)


class TestSingleton(unittest.TestCase):
    def tearDown(self):
        scarico.imposta_scarico(None)

    def test_imposta_e_svuota(self):
        s, chiamate = _costruisci([httpx.Response(200, text=PAGINA)] * 2)
        scarico.imposta_scarico(s)
        self.assertIs(scarico.scarico_corrente(), s)
        _esegui(scarico.scarica_testo("https://ente.it/x"))
        scarico.svuota()
        self.assertEqual(scarico.contatori().fetch, 0)
        _esegui(scarico.scarica_testo("https://ente.it/x"))
        self.assertEqual(len(chiamate), 2)


if __name__ == "__main__":
    unittest.main()
