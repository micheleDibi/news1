# -*- coding: utf-8 -*-
"""`scarico`: URL finale e redirect solo sullo stesso host (contratto `bandi-giro-2` §7).

  - `Risposta.url_finale` vale `url` se nessuno lo dice, ed e' l'URL dopo i
    redirect quando si segue una catena;
  - `redirect='tutti'` (default) e' il comportamento di sempre;
  - `redirect='stesso_host'` si ferma sul primo redirect verso un altro host e
    restituisce quel 3xx, con `url_finale` sull'ultimo URL dello stesso host.

Rete finta con `httpx.MockTransport`: nessuna rete vera.
"""
import asyncio
import unittest

import httpx

from tests.supporto import carica_modulo

scarico = carica_modulo("scarico")

PAGINA = "<html><body><h1>Avviso</h1><p>Domande entro il 30/11/2026.</p></body></html>"
ENTE = "https://www.ente.example.it"


async def _niente(_valore) -> None:
    """Throttle e backoff istantanei."""


def _scarico(mappa):
    """`mappa`: url -> httpx.Response (i redirect con l'intestazione Location)."""
    chiamate: list[str] = []

    def gestore(request: httpx.Request) -> httpx.Response:
        chiamate.append(str(request.url))
        return mappa.get(str(request.url), httpx.Response(404))

    s = scarico.Scarico(transport=httpx.MockTransport(gestore), throttle=_niente, dormi=_niente,
                        tentativi=0)
    return s, chiamate


def _redirect(verso: str, stato: int = 301) -> httpx.Response:
    return httpx.Response(stato, headers={"Location": verso})


def _pagina() -> httpx.Response:
    return httpx.Response(200, text=PAGINA, headers={"content-type": "text/html; charset=utf-8"})


def _esegui(corutina):
    return asyncio.run(corutina)


class TestRisposta(unittest.TestCase):
    def test_url_finale_vale_url_se_non_detto(self):
        risposta = scarico.Risposta(url="https://a.example.it/x", stato=200)
        self.assertEqual(risposta.url_finale, "https://a.example.it/x")

    def test_url_finale_esplicito(self):
        risposta = scarico.Risposta(url="https://a.example.it/x", stato=200,
                                    url_finale="https://a.example.it/y")
        self.assertEqual((risposta.url, risposta.url_finale),
                         ("https://a.example.it/x", "https://a.example.it/y"))


class TestTutti(unittest.TestCase):
    def test_senza_redirect(self):
        s, _ = _scarico({f"{ENTE}/avviso": _pagina()})
        risposta = _esegui(s.scarica(f"{ENTE}/avviso"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(risposta.url_finale, f"{ENTE}/avviso")

    def test_redirect_sullo_stesso_host(self):
        s, _ = _scarico({f"{ENTE}/vecchio": _redirect(f"{ENTE}/nuovo"),
                         f"{ENTE}/nuovo": _pagina()})
        risposta = _esegui(s.scarica(f"{ENTE}/vecchio"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(risposta.url, f"{ENTE}/vecchio")
        self.assertEqual(risposta.url_finale, f"{ENTE}/nuovo")
        self.assertIn("30/11/2026", risposta.testo)

    def test_redirect_verso_un_altro_host_si_segue_come_sempre(self):
        s, chiamate = _scarico({"https://rpu.gl/abc": _redirect(f"{ENTE}/avviso", 302),
                                f"{ENTE}/avviso": _pagina()})
        risposta = _esegui(s.scarica("https://rpu.gl/abc"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(risposta.url_finale, f"{ENTE}/avviso")
        self.assertEqual(chiamate, ["https://rpu.gl/abc", f"{ENTE}/avviso"])

    def test_redirect_sconosciuto_rifiutato(self):
        s, chiamate = _scarico({})
        with self.assertRaises(ValueError):
            _esegui(s.scarica(f"{ENTE}/avviso", redirect="qualcuno"))
        self.assertEqual(chiamate, [])


class TestStessoHost(unittest.TestCase):
    def test_301_sullo_stesso_host_si_segue(self):
        s, _ = _scarico({f"{ENTE}/preavvisi/x": _redirect(f"{ENTE}/avvisi/x"),
                         f"{ENTE}/avvisi/x": _pagina()})
        risposta = _esegui(s.scarica(f"{ENTE}/preavvisi/x", redirect="stesso_host"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(risposta.url_finale, f"{ENTE}/avvisi/x")
        self.assertTrue(risposta.ok)

    def test_www_e_host_nudo_sono_lo_stesso_host(self):
        s, _ = _scarico({"https://ente.example.it/a": _redirect(f"{ENTE}/a"),
                         f"{ENTE}/a": _pagina()})
        risposta = _esegui(s.scarica("https://ente.example.it/a", redirect="stesso_host"))
        self.assertEqual(risposta.stato, 200)
        self.assertEqual(risposta.url_finale, f"{ENTE}/a")

    def test_redirect_verso_un_altro_host_si_ferma(self):
        s, chiamate = _scarico({
            f"{ENTE}/a": _redirect(f"{ENTE}/b", 302),
            f"{ENTE}/b": _redirect("https://www.obiettivoeuropa.com/bando/1", 301),
            "https://www.obiettivoeuropa.com/bando/1": _pagina(),
        })
        risposta = _esegui(s.scarica(f"{ENTE}/a", redirect="stesso_host"))
        self.assertEqual(risposta.stato, 301)
        self.assertFalse(risposta.ok)
        self.assertEqual(risposta.url, f"{ENTE}/a")
        self.assertEqual(risposta.url_finale, f"{ENTE}/b")
        self.assertEqual(risposta.testo, "")
        # L'altro host non si interroga mai.
        self.assertEqual(chiamate, [f"{ENTE}/a", f"{ENTE}/b"])
        self.assertEqual(s.contatori.errori, 0)

    def test_redirect_relativo(self):
        s, _ = _scarico({f"{ENTE}/a": _redirect("/b"), f"{ENTE}/b": _pagina()})
        risposta = _esegui(s.scarica(f"{ENTE}/a", redirect="stesso_host"))
        self.assertEqual(risposta.url_finale, f"{ENTE}/b")

    def test_catena_infinita_sullo_stesso_host(self):
        s, _ = _scarico({f"{ENTE}/a": _redirect(f"{ENTE}/b"), f"{ENTE}/b": _redirect(f"{ENTE}/a")})
        with self.assertRaises(httpx.TooManyRedirects):
            _esegui(s.scarica(f"{ENTE}/a", redirect="stesso_host"))

    def test_404_dopo_il_redirect(self):
        s, _ = _scarico({f"{ENTE}/a": _redirect(f"{ENTE}/sparito")})
        risposta = _esegui(s.scarica(f"{ENTE}/a", redirect="stesso_host"))
        self.assertEqual(risposta.stato, 404)
        self.assertEqual(risposta.url_finale, f"{ENTE}/sparito")

    def test_niente_ripiego_firecrawl(self):
        # Il ripiego rilegge `url` seguendo i redirect ovunque: con 'stesso_host'
        # sarebbe la pagina di un altro host attribuita all'ente.
        chiamate_firecrawl: list[str] = []

        async def firecrawl(url):
            chiamate_firecrawl.append(url)
            return {"html": PAGINA, "markdown": "Avviso"}

        def gestore(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="negato")

        s = scarico.Scarico(transport=httpx.MockTransport(gestore), throttle=_niente, dormi=_niente,
                            tentativi=0, firecrawl=firecrawl)
        risposta = _esegui(s.scarica(f"{ENTE}/a", principale=True, redirect="stesso_host"))
        self.assertEqual(chiamate_firecrawl, [])
        self.assertEqual(risposta.stato, 403)
        self.assertEqual(risposta.url_finale, f"{ENTE}/a")
        self.assertEqual(risposta.via, "httpx")
        # Con 'tutti' il ripiego resta quello di sempre.
        risposta = _esegui(s.scarica(f"{ENTE}/a", principale=True))
        self.assertEqual(chiamate_firecrawl, [f"{ENTE}/a"])
        self.assertEqual(risposta.via, "firecrawl")

    def test_la_cache_distingue_la_modalita(self):
        s, chiamate = _scarico({
            f"{ENTE}/a": _redirect("https://altro.example.it/a"),
            "https://altro.example.it/a": _pagina(),
        })
        tutti = _esegui(s.scarica(f"{ENTE}/a"))
        fermo = _esegui(s.scarica(f"{ENTE}/a", redirect="stesso_host"))
        di_nuovo = _esegui(s.scarica(f"{ENTE}/a"))
        self.assertEqual(tutti.stato, 200)
        self.assertEqual(fermo.stato, 301)
        self.assertTrue(di_nuovo.da_cache)
        self.assertEqual(di_nuovo.url_finale, "https://altro.example.it/a")
        self.assertEqual(len(chiamate), 3)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
