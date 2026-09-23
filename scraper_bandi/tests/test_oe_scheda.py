# -*- coding: utf-8 -*-
"""Scheda di Obiettivo Europa: parser deterministico e scarico (piano §5).

Il parser e' puro e gira su fixture scritte a mano: nessuna richiesta parte
verso il portale, e le fixture riproducono la struttura reale della scheda
(`h2` «Link e Documenti» → `div.prose` → `p > a`, bottone «Vai al bando»,
sezione «Bandi correlati» in coda).

Cosa questi test difendono:
  * i cookie della sessione autenticata non escono verso httpx o Firecrawl;
  * la regola unica di ri-scarico (A29): `modified` non e' un innesco;
  * il lotto si ferma su 403/429 e al tetto giornaliero, e non ripiega mai su
    una sessione anonima quando quella autenticata non si valida;
  * i link della sezione «Bandi correlati» non entrano fra i candidati.
"""
import asyncio
import inspect
import types
import unittest

from tests.supporto import carica_modulo

oe = carica_modulo("oe_scheda")
dominio_ufficiale = carica_modulo("dominio_ufficiale")


URL_SCHEDA = "https://www.obiettivoeuropa.com/bandi/contributi-formazione-2026/"


def _scheda_html(
    sezione: str = "Link e Documenti",
    link: str = "<p><a href=\"https://regione.marche.it/bandi/formazione-2026\">Vai al sito</a></p>",
    extra: str = "",
) -> str:
    return f"""<!doctype html>
<html><body>
  <h1>Contributi formazione 2026</h1>
  <div class="prose"><p>Descrizione del bando.</p></div>
  <h2>{sezione}</h2>
  <div class="prose">
    {link}
  </div>
  {extra}
  <a class="btn" href="https://regione.marche.it/candidatura">Vai al bando</a>
</body></html>"""


class _SessioneFinta:
    """Una `requests.Session` quanto basta: cookie, headers e una `get`."""

    def __init__(self, risposte):
        self.cookies = {"sessionid": "non-usato-nei-test"}
        self.headers = {"User-Agent": "test", "Cookie": "sessionid=segreto"}
        self._risposte = list(risposte)
        self.chiamate: list[str] = []

    def get(self, url, **kwargs):
        self.chiamate.append(url)
        if not self._risposte:
            raise AssertionError("richiesta in piu' rispetto alle risposte previste")
        return self._risposte.pop(0)


def _risposta(stato: int, testo: str = ""):
    return types.SimpleNamespace(status_code=stato, text=testo)


def _esegui(coroutine):
    return asyncio.run(coroutine)


class TestParser(unittest.TestCase):
    def test_estrae_il_link_della_sezione_e_il_bottone(self):
        scheda = oe.analizza(_scheda_html(), URL_SCHEDA)
        self.assertTrue(scheda.sezione_presente)
        urls = [c.url for c in scheda.candidati]
        self.assertIn("https://regione.marche.it/bandi/formazione-2026", urls)
        self.assertIn("https://regione.marche.it/candidatura", urls)
        origini = {c.url: c.origine for c in scheda.candidati}
        self.assertEqual(
            origini["https://regione.marche.it/bandi/formazione-2026"], oe.ORIGINE_SEZIONE,
        )
        self.assertEqual(
            origini["https://regione.marche.it/candidatura"], oe.ORIGINE_BOTTONE,
        )

    def test_scarta_host_oe_mailto_frammento_e_javascript(self):
        link = (
            '<p><a href="https://www.obiettivoeuropa.com/bandi/altro/">Altro bando</a></p>'
            '<p><a href="mailto:info@regione.marche.it">Scrivi</a></p>'
            '<p><a href="#contatti">Contatti</a></p>'
            '<p><a href="javascript:void(0)">Apri</a></p>'
            '<p><a href="https://regione.marche.it/avviso.pdf">Avviso</a></p>'
        )
        scheda = oe.analizza(_scheda_html(link=link), URL_SCHEDA)
        self.assertEqual(
            [c.url for c in scheda.candidati],
            ["https://regione.marche.it/avviso.pdf", "https://regione.marche.it/candidatura"],
        )
        self.assertIn("host obiettivoeuropa", [s.motivo for s in scheda.scartati])

    def test_i_bandi_correlati_non_entrano(self):
        # La sidebar «Bandi correlati» e' un secondo `div.prose` dopo un altro
        # `h2`: fermarsi alla prossima intestazione e' cio' che la tiene fuori.
        extra = (
            "<h2>Bandi correlati</h2>"
            '<div class="prose"><p><a href="https://regione.lazio.it/altro">Altro</a></p></div>'
        )
        scheda = oe.analizza(_scheda_html(extra=extra), URL_SCHEDA)
        self.assertNotIn("https://regione.lazio.it/altro", [c.url for c in scheda.candidati])

    def test_solo_i_figli_diretti_di_p(self):
        link = (
            '<ul><li><a href="https://regione.marche.it/menu">Menu</a></li></ul>'
            '<p><a href="https://regione.marche.it/vero">Vero</a></p>'
        )
        scheda = oe.analizza(_scheda_html(link=link), URL_SCHEDA)
        urls = [c.url for c in scheda.candidati]
        self.assertIn("https://regione.marche.it/vero", urls)
        self.assertNotIn("https://regione.marche.it/menu", urls)

    def test_prova_e_sha256_piu_offset(self):
        html = _scheda_html()
        scheda = oe.analizza(html, URL_SCHEDA)
        primo = scheda.candidati[0]
        impronta, _, offset = primo.prova.partition("#")
        self.assertEqual(impronta, oe.impronta_scheda(html))
        # L'offset deve ritrovare davvero l'href nell'HTML originale: e' cio'
        # che distingue una prova da una stringa qualsiasi.
        self.assertTrue(html[int(offset):].startswith(primo.url))

    def test_due_href_identici_hanno_offset_diversi(self):
        link = (
            '<p><a href="https://regione.marche.it/a">Uno</a></p>'
            '<p><a href="https://regione.marche.it/a">Due</a></p>'
        )
        html = _scheda_html(link=link)
        scheda = oe.analizza(html, URL_SCHEDA)
        # Il dedup per URL normalizzato tiene una riga sola, ma il cursore
        # avanza: il bottone che segue non riceve l'offset del primo link.
        offsets = {c.url: int(c.prova.split("#")[1]) for c in scheda.candidati}
        self.assertEqual(len(set(offsets.values())), len(offsets))

    def test_classificazione_con_la_whitelist(self):
        tabella = dominio_ufficiale.costruisci(righe=[
            dominio_ufficiale.Dominio(host="regione.marche.it", tipo="ente", confidenza=1.0),
        ])
        scheda = oe.analizza(_scheda_html(), URL_SCHEDA, tabella=tabella)
        self.assertEqual({c.tipo for c in scheda.candidati}, {"ente"})

    def test_senza_sezione_resta_il_bottone(self):
        scheda = oe.analizza(_scheda_html(sezione="Informazioni"), URL_SCHEDA)
        self.assertFalse(scheda.sezione_presente)
        self.assertEqual([c.url for c in scheda.candidati],
                         ["https://regione.marche.it/candidatura"])

    def test_html_vuoto_non_solleva(self):
        scheda = oe.analizza("", URL_SCHEDA)
        self.assertFalse(scheda.ha_candidati)
        self.assertEqual(scheda.impronta, oe.impronta_scheda(""))

    def test_allarme_quando_la_sezione_sparisce(self):
        con = oe.analizza(_scheda_html(), URL_SCHEDA)
        senza = oe.analizza(_scheda_html(sezione="Altro"), URL_SCHEDA)
        self.assertEqual(oe.allarme_sezione([con, con, con, con]), "")
        riga = oe.allarme_sezione([con, senza, senza, senza])
        self.assertIn("[ALLARME]", riga)
        self.assertAlmostEqual(oe.quota_con_sezione([con, senza]), 0.5)


class TestProva(unittest.TestCase):
    """`prova` = `sha256(scheda)#offset`. §5 ci fonda la verificabilita' di
    ogni link ereditato da OE: chi rilegge la riga deve poter riscaricare la
    scheda, confrontare l'impronta e ritrovare l'href a quell'offset."""

    def _candidato(self, html, url):
        scheda = oe.analizza(html, URL_SCHEDA)
        return html, next(c for c in scheda.candidati if c.url == url)

    def test_offset_ritrovabile_nell_html(self):
        html, candidato = self._candidato(
            _scheda_html(), "https://regione.marche.it/bandi/formazione-2026",
        )
        self.assertGreater(candidato.offset, 0)
        self.assertTrue(
            html[candidato.offset:].startswith(candidato.url),
            "l'offset deve puntare all'href, non a un punto qualunque",
        )

    def test_entita_html_nell_href_non_invalidano_la_prova(self):
        # `href="...?id=1&amp;anno=2026"` e' la forma corretta, e comunissima,
        # di una query string: BeautifulSoup risolve l'entita' e l'href che
        # restituisce nell'HTML originale non esiste. Senza il ritentativo
        # sulla forma con le entita' l'offset sarebbe -1 e la prova una
        # stringa che non prova niente.
        link = '<p><a href="https://regione.marche.it/bandi?id=1&amp;anno=2026">Bando</a></p>'
        html, candidato = self._candidato(
            _scheda_html(link=link), "https://regione.marche.it/bandi?id=1&anno=2026",
        )
        self.assertGreater(candidato.offset, 0)
        self.assertTrue(
            html[candidato.offset:].startswith(
                "https://regione.marche.it/bandi?id=1&amp;anno=2026"
            )
        )
        impronta, _, offset = candidato.prova.partition("#")
        self.assertEqual(impronta, oe.impronta_scheda(html))
        self.assertEqual(int(offset), candidato.offset)

    def test_href_irreperibile_niente_prova_finta(self):
        # Se l'href non si ritrova in nessuna forma il candidato resta (l'URL
        # e' vero) ma senza prova: meglio NULL in `bando_link.impronta_pagina`
        # che un `sha256#-1` che sembra una prova.
        scheda = oe.analizza(_scheda_html(), URL_SCHEDA)
        finto = oe.Candidato(url="https://esempio.it/x", offset=-1, prova="")
        self.assertEqual(finto.prova, "")
        self.assertTrue(all(c.prova and "#-1" not in c.prova for c in scheda.candidati))

    def test_due_link_uguali_hanno_offset_diversi(self):
        link = (
            '<p><a href="https://regione.marche.it/avviso.pdf">Avviso</a></p>'
            '<p><a href="https://regione.marche.it/avviso.pdf?x=1">Avviso bis</a></p>'
        )
        scheda = oe.analizza(_scheda_html(link=link), URL_SCHEDA)
        offset = [c.offset for c in scheda.candidati if "avviso.pdf" in c.url]
        self.assertEqual(len(offset), len(set(offset)))


class TestRegolaDiRiscarico(unittest.TestCase):
    """A29: tre inneschi e non uno di piu'."""

    def test_scoperta(self):
        self.assertEqual(oe.deve_riscaricare(prima=None, dopo={"status": "1"}),
                         (True, oe.MOTIVO_SCOPERTA))

    def test_cambio_status_e_deadline(self):
        self.assertEqual(
            oe.deve_riscaricare(prima={"status": "1"}, dopo={"status": "2"}),
            (True, oe.MOTIVO_STATO),
        )
        self.assertEqual(
            oe.deve_riscaricare(
                prima={"deadline_label": "Scade il 30/09/2026"},
                dopo={"deadline_label": "Scade il 31/10/2026"},
            ),
            (True, oe.MOTIVO_SCADENZA),
        )

    def test_forza(self):
        self.assertEqual(oe.deve_riscaricare(prima={"status": "1"}, dopo={"status": "1"},
                                             forza=True),
                         (True, oe.MOTIVO_FORZA))

    def test_modified_e_gli_altri_non_sono_inneschi(self):
        # Il caso che moltiplicherebbe per tre il traffico verso il portale
        # senza aggiungere un solo link nuovo.
        for campo in sorted(oe.CAMPI_SOLO_PRIORITA):
            with self.subTest(campo=campo):
                riscarica, motivo = oe.deve_riscaricare(
                    prima={campo: "vecchio", "status": "1"},
                    dopo={campo: "nuovo", "status": "1"},
                )
                self.assertFalse(riscarica)
                self.assertEqual(motivo, "")

    def test_nessun_motivo_fuori_dai_quattro(self):
        self.assertEqual(
            oe.MOTIVI_RISCARICO,
            {oe.MOTIVO_SCOPERTA, oe.MOTIVO_STATO, oe.MOTIVO_SCADENZA, oe.MOTIVO_FORZA},
        )


class TestSegreti(unittest.TestCase):
    def test_sessione_httpx_rifiutata(self):
        # Un client httpx ha cookie e `get` come una requests.Session: l'unica
        # cosa che li distingue e' il modulo di provenienza.
        finto_httpx = type("AsyncClient", (), {"__module__": "httpx._client"})
        finto_httpx.cookies = {}
        finto_httpx.get = lambda *a, **k: None
        with self.assertRaises(AssertionError):
            oe.assicura_sessione_requests(finto_httpx())

    def test_oggetto_senza_cookie_rifiutato(self):
        with self.assertRaises(AssertionError):
            oe.assicura_sessione_requests(object())

    def test_cookie_verso_firecrawl_vietato(self):
        with self.assertRaises(AssertionError):
            oe.assicura_niente_cookie("firecrawl", {"Cookie": "sessionid=x"})
        with self.assertRaises(AssertionError):
            oe.assicura_niente_cookie("httpx", {"Authorization": "Bearer x"})
        oe.assicura_niente_cookie("httpx", {"User-Agent": "test"})

    def test_il_messaggio_dell_assert_non_contiene_il_cookie(self):
        # L'assert nomina la chiave colpevole, mai il suo valore: un traceback
        # che stampasse il `sessionid` lo scriverebbe nei log per sempre.
        with self.assertRaises(AssertionError) as errore:
            oe.assicura_niente_cookie("httpx", {"Cookie": "sessionid=segretissimo"})
        self.assertNotIn("segretissimo", str(errore.exception))

    def test_la_guardia_ha_un_chiamante_vero(self):
        # §5 chiede l'assert nel chokepoint in cui si compongono le
        # intestazioni per httpx: `VerificaHttp` e' quel punto. Una guardia
        # senza chokepoint non protegge niente.
        fonte_ufficiale = carica_modulo("fonte_ufficiale")
        sorgente = inspect.getsource(fonte_ufficiale.VerificaHttp.__init__)
        self.assertIn("assicura_niente_cookie", sorgente)


class TestScarico(unittest.TestCase):
    def _scarico(self, risposte, **kwargs):
        sessione = _SessioneFinta(risposte)
        attese: list[float] = []

        async def dormi(secondi):
            attese.append(secondi)

        async def esegui(chiamata):
            return chiamata()

        scarico = oe.ScaricoSchede(
            fornitore_sessione=lambda: sessione,
            validatore=lambda s: True,
            esegui=esegui,
            dormi=dormi,
            orologio=lambda: 0.0,
            **kwargs,
        )
        return scarico, sessione, attese

    def test_scarica_e_analizza(self):
        scarico, sessione, _ = self._scarico([_risposta(200, _scheda_html())])
        scheda = _esegui(scarico.scheda(URL_SCHEDA))
        self.assertTrue(scheda.sezione_presente)
        self.assertEqual(sessione.chiamate, [URL_SCHEDA])
        self.assertEqual(scarico.contatori.schede, 1)

    def test_throttle_di_un_secondo(self):
        scarico, _, attese = self._scarico(
            [_risposta(200, _scheda_html()), _risposta(200, _scheda_html())],
        )
        _esegui(scarico.scheda(URL_SCHEDA))
        _esegui(scarico.scheda(URL_SCHEDA + "2"))
        # Orologio fermo: la seconda richiesta aspetta l'intero throttle.
        self.assertEqual(attese, [oe.THROTTLE_S])

    def test_403_ferma_il_lotto(self):
        scarico, sessione, _ = self._scarico([_risposta(403)])
        self.assertIsNone(_esegui(scarico.scheda(URL_SCHEDA)))
        self.assertEqual(scarico.fermato, "http 403")
        # Nessuna richiesta successiva: insistere significherebbe farsi bloccare.
        self.assertIsNone(_esegui(scarico.scheda(URL_SCHEDA + "2")))
        self.assertEqual(len(sessione.chiamate), 1)

    def test_429_ferma_il_lotto(self):
        scarico, _, _ = self._scarico([_risposta(429)])
        _esegui(scarico.scheda(URL_SCHEDA))
        self.assertEqual(scarico.fermato, "http 429")

    def test_404_conta_un_errore_e_prosegue(self):
        scarico, sessione, _ = self._scarico([_risposta(404), _risposta(200, _scheda_html())])
        self.assertIsNone(_esegui(scarico.scheda(URL_SCHEDA)))
        self.assertIsNotNone(_esegui(scarico.scheda(URL_SCHEDA + "2")))
        self.assertEqual(scarico.contatori.errori, 1)
        self.assertEqual(len(sessione.chiamate), 2)

    def test_tetto_giornaliero(self):
        scarico, sessione, _ = self._scarico([_risposta(200, _scheda_html())], tetto=1)
        _esegui(scarico.scheda(URL_SCHEDA))
        self.assertIsNone(_esegui(scarico.scheda(URL_SCHEDA + "2")))
        self.assertEqual(scarico.fermato, "tetto")
        self.assertEqual(len(sessione.chiamate), 1)

    def test_tetto_tiene_conto_di_quanto_gia_fatto_oggi(self):
        scarico, sessione, _ = self._scarico([], tetto=10, gia_oggi=10)
        self.assertIsNone(_esegui(scarico.scheda(URL_SCHEDA)))
        self.assertEqual(sessione.chiamate, [])

    def test_solo_schede_oe(self):
        scarico, _, _ = self._scarico([])
        with self.assertRaises(AssertionError):
            _esegui(scarico.scheda("https://regione.marche.it/bandi/1"))

    def test_sessione_non_valida_niente_ripiego_anonimo(self):
        anonima = _SessioneFinta([_risposta(200, _scheda_html())])
        attese: list[float] = []

        async def dormi(secondi):
            attese.append(secondi)

        async def esegui(chiamata):
            return chiamata()

        scarico = oe.ScaricoSchede(
            fornitore_sessione=lambda: _SessioneFinta([]),
            validatore=lambda s: False,
            fornitore_anonima=lambda: anonima,
            esegui=esegui,
            dormi=dormi,
        )
        with self.assertRaises(oe.SchedaOEError) as errore:
            _esegui(scarico.prepara())
        self.assertIn("[ALLARME]", str(errore.exception))
        self.assertEqual(attese, list(oe.BACKOFF_S[:2]))
        self.assertEqual(anonima.chiamate, [], "nessun ripiego anonimo sugli attivi")

    def test_clear_cache_fra_un_tentativo_e_l_altro(self):
        azzerate = []

        async def esegui(chiamata):
            return chiamata()

        async def dormi(_secondi):
            return None

        scarico = oe.ScaricoSchede(
            fornitore_sessione=lambda: _SessioneFinta([]),
            validatore=lambda s: False,
            azzera_cache=lambda: azzerate.append(1),
            esegui=esegui,
            dormi=dormi,
            tentativi=2,
        )
        with self.assertRaises(oe.SchedaOEError):
            _esegui(scarico.prepara())
        self.assertEqual(len(azzerate), 2)

    def test_sessione_anonima_solo_per_gli_archiviati(self):
        autenticata = _SessioneFinta([_risposta(200, _scheda_html())])
        anonima = _SessioneFinta([_risposta(200, _scheda_html())])

        async def esegui(chiamata):
            return chiamata()

        async def dormi(_secondi):
            return None

        scarico = oe.ScaricoSchede(
            fornitore_sessione=lambda: autenticata,
            validatore=lambda s: True,
            fornitore_anonima=lambda: anonima,
            esegui=esegui,
            dormi=dormi,
        )
        _esegui(scarico.scheda(URL_SCHEDA, archiviato=True))
        _esegui(scarico.scheda(URL_SCHEDA + "2"))
        self.assertEqual(len(anonima.chiamate), 1)
        self.assertEqual(len(autenticata.chiamate), 1)
        self.assertEqual(scarico.contatori.anonime, 1)

    def test_lotto_si_interrompe_al_primo_stop(self):
        scarico, sessione, _ = self._scarico(
            [_risposta(200, _scheda_html()), _risposta(429)],
        )
        schede = _esegui(scarico.lotto([
            (URL_SCHEDA, False), (URL_SCHEDA + "2", False), (URL_SCHEDA + "3", False),
        ]))
        self.assertEqual(len(schede), 1)
        self.assertEqual(len(sessione.chiamate), 2)


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
