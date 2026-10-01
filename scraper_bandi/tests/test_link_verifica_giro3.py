# -*- coding: utf-8 -*-
"""`link-verifica` nel giro 3 e le righe di link dei bandi nuovi (contratto
`bandi-giro-3` §10), piu' i due P2 della revisione #144 sul resolver.

- quarta prova: l'URL compare nell'HTML della pagina di riferimento del bando
  (l'ufficiale con la fonte `trovata`, altrimenti `link_bando`, anche se
  aggregatore, purche' risponda 2xx);
- una riga provata solo dall'aggregatore si riprova sulla pagina ufficiale
  quando la fonte diventa `trovata`, senza mai ritirarla;
- tempo `TEMPO_LINK_VERIFICA_S` con rotazione e copertura; freno per host in
  produzione;
- `righe_link_da_payload` per la SEO (M3);
- la verifica degli allegati del resolver passa dal lucchetto per host e non
  blocca l'event loop; i bandi rinviati non sono «fatti» nella copertura.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_link_verifica_giro3
"""
import asyncio
import threading
import time
import unittest
import unittest.mock
from types import SimpleNamespace
from typing import Any

from tests.supporto import carica_modulo

fu = carica_modulo("fonte_ufficiale")
http = carica_modulo("http")
oe = carica_modulo("oe_scheda")

UFFICIALE = "https://www.regione.marche.it/bandi/contributi"
OE = "https://www.obiettivoeuropa.com/bandi/contributi"
ALLEGATO = "https://www.regione.marche.it/allegati/avviso.pdf?v=1&a=2"
MODULO = "https://www.regione.marche.it/allegati/modulo.docx"

#: §18.6: la guardia degli indirizzi risolve gli host. Nei test niente DNS
#: vero: ogni host risolve a un indirizzo pubblico, tranne quelli di `INTERNI`
#: (rete interna) e di `GIU` (DNS che non risponde).
INTERNI = {"intranet.ente.it": ["10.0.0.7"], "localhost": ["127.0.0.1"]}
GIU = {"giu.ente.it"}


def _dns_finto(host):
    if host in GIU:
        raise OSError("DNS giu'")
    return INTERNI.get(host, ["93.184.216.34"])


_DNS = unittest.mock.patch.object(http, "_risolvi", _dns_finto)


def setUpModule():
    _DNS.start()


def tearDownModule():
    _DNS.stop()


def esegui(coroutine):
    return asyncio.run(coroutine)


class ProvaNellaPagina(unittest.TestCase):
    def test_url_assoluto_e_impronta_della_pagina(self):
        html = f'<p><a href="{MODULO}">Modulo</a></p>'
        prova = fu.prova_nella_pagina(MODULO, html, UFFICIALE)
        impronta, offset = prova.split("#")
        self.assertEqual(impronta, oe.impronta_scheda(html))
        self.assertEqual(int(offset), html.find(MODULO))

    def test_forma_con_le_entita(self):
        html = '<a href="https://www.regione.marche.it/allegati/avviso.pdf?v=1&amp;a=2">x</a>'
        self.assertIsNotNone(fu.prova_nella_pagina(ALLEGATO, html, UFFICIALE))

    def test_href_relativo_sullo_stesso_host(self):
        html = '<a href="/allegati/avviso.pdf?v=1&amp;a=2">Avviso</a>'
        prova = fu.prova_nella_pagina(ALLEGATO, html, UFFICIALE)
        self.assertIsNotNone(prova)
        self.assertEqual(int(prova.split("#")[1]), html.find("/allegati"))
        # Su un altro host il relativo non prova niente.
        self.assertIsNone(fu.prova_nella_pagina(ALLEGATO, html, "https://altro.it/bando"))

    def test_un_percorso_nudo_nel_testo_non_basta(self):
        html = "<p>Vedi la cartella /allegati/avviso.pdf?v=1&a=2 del sito.</p>"
        self.assertIsNone(fu.prova_nella_pagina(ALLEGATO, html, UFFICIALE))

    def test_niente_html_niente_prova(self):
        self.assertIsNone(fu.prova_nella_pagina(MODULO, "", UFFICIALE))
        self.assertIsNone(fu.prova_nella_pagina(MODULO, None, UFFICIALE))
        self.assertIsNone(fu.prova_nella_pagina(MODULO, "<p>altro</p>", UFFICIALE))


class NessunFalsoPositivoDaPrefisso(unittest.TestCase):
    """Revisione #147 (P1): un URL non e' «trovato» dentro un URL piu' lungo."""

    def test_i_due_casi_della_revisione(self):
        self.assertIsNone(fu.prova_nella_pagina(
            "https://ente.it/doc.php?id=1", '<a href="https://ente.it/doc.php?id=12">x</a>'))
        self.assertIsNone(fu.prova_nella_pagina(
            "https://ente.it/bandi/avviso",
            '<a href="https://ente.it/bandi/avviso-2024.pdf">x</a>'))

    def test_l_occorrenza_vera_dopo_quella_falsa(self):
        html = ('<a href="https://ente.it/doc.php?id=12">a</a> '
                '<a href="https://ente.it/doc.php?id=1">b</a>')
        prova = fu.prova_nella_pagina("https://ente.it/doc.php?id=1", html)
        self.assertEqual(int(prova.split("#")[1]), html.find('https://ente.it/doc.php?id=1"'))

    def test_i_confini_ammessi(self):
        url = "https://ente.it/a"
        for html in (f'<a href="{url}">', f"<a href='{url}'>", f"<p>{url}</p>", f"{url} testo",
                     f'<a href="{url}#sezione">', url):
            with self.subTest(html=html):
                self.assertIsNotNone(fu.prova_nella_pagina(url, html))
        for html in (f'<a href="{url}b">', f'<a href="{url}/x">', f'<a href="{url}?p=1">',
                     f'<a href="{url}.pdf">'):
            with self.subTest(html=html):
                self.assertIsNone(fu.prova_nella_pagina(url, html))

    def test_vale_anche_per_le_righe_dal_payload(self):
        bando = {"id": 1, "fonte_ufficiale_url": "https://ente.it/bando",
                 "fonte_ufficiale_stato": "trovata", "link_bando": OE}
        payload = {"link_candidatura_source": "missing",
                   "allegati": [{"label": "Doc", "url": "https://ente.it/doc.php?id=1", "tipo": "pdf"}]}
        righe = fu.righe_link_da_payload(bando, payload,
                                         '<a href="https://ente.it/doc.php?id=12">x</a>')
        self.assertIsNone(righe[0]["impronta_pagina"])


class PaginaDiRiferimento(unittest.TestCase):
    def test_ufficiale_con_la_fonte_trovata(self):
        bando = {"fonte_ufficiale_url": UFFICIALE, "fonte_ufficiale_stato": "trovata",
                 "link_bando": OE}
        self.assertEqual(fu.pagina_di_riferimento(bando), UFFICIALE)

    def test_link_bando_anche_se_aggregatore_senza_fonte(self):
        bando = {"fonte_ufficiale_url": UFFICIALE, "fonte_ufficiale_stato": "in_verifica",
                 "link_bando": OE}
        self.assertEqual(fu.pagina_di_riferimento(bando), OE)

    def test_un_pdf_ufficiale_torna_a_link_bando(self):
        bando = {"fonte_ufficiale_url": UFFICIALE + ".pdf", "fonte_ufficiale_stato": "trovata",
                 "link_bando": OE}
        self.assertEqual(fu.pagina_di_riferimento(bando), OE)


class RigheDalPayload(unittest.TestCase):
    BANDO = {"id": 9, "link_bando": OE, "fonte_ufficiale_url": UFFICIALE,
             "fonte_ufficiale_stato": "trovata"}
    HTML = (f'<a href="{MODULO}">Modulo</a> <a href="/allegati/avviso.pdf?v=1&amp;a=2">Avviso</a>'
            '<a href="https://portale.regione.marche.it/candidature">Candidati</a>')

    def _payload(self, **extra):
        valori = {
            "link_candidatura": "https://portale.regione.marche.it/candidature",
            "link_candidatura_source": "extracted",
            "allegati": [
                {"label": "Modulo", "url": MODULO, "tipo": "docx"},
                {"label": "Avviso", "url": ALLEGATO, "tipo": "pdf"},
                {"label": "Scheda", "url": OE + "/scheda.pdf", "tipo": "pdf"},
                {"label": "Senza schema", "url": "mailto:bandi@regione.marche.it", "tipo": ""},
                {"label": "Doppio", "url": MODULO, "tipo": "docx"},
            ],
        }
        valori.update(extra)
        return valori

    def test_candidatura_estratta_e_allegati_con_la_prova(self):
        righe = fu.righe_link_da_payload(self.BANDO, self._payload(), self.HTML)
        self.assertEqual([(r["tipo"], r["url"]) for r in righe], [
            ("candidatura", "https://portale.regione.marche.it/candidature"),
            ("allegato", MODULO), ("allegato", ALLEGATO),
        ])
        for riga in righe:
            with self.subTest(url=riga["url"]):
                self.assertEqual(riga["bando_id"], 9)
                self.assertFalse(riga["pubblicabile"])
                self.assertIsNone(riga["esito_http"])
                self.assertTrue(riga["impronta_pagina"])
                self.assertEqual(riga["url_prova"], UFFICIALE)
                self.assertIsNotNone(riga["trovato_in_fonte_at"])
                self.assertIn(riga["origine"],
                              ("ente", "portale_pubblico", "aggregatore", "raw"))
        self.assertEqual(righe[1]["etichetta"], "Modulo")
        self.assertEqual(righe[1]["content_type"], "docx")

    def test_la_candidatura_di_ripiego_non_e_una_riga(self):
        for sorgente in ("fallback_source", "missing"):
            with self.subTest(sorgente=sorgente):
                righe = fu.righe_link_da_payload(
                    self.BANDO, self._payload(link_candidatura_source=sorgente), self.HTML)
                self.assertNotIn("candidatura", [r["tipo"] for r in righe])

    def test_senza_html_nessuna_prova(self):
        righe = fu.righe_link_da_payload(self.BANDO, self._payload(), None)
        self.assertEqual(len(righe), 3)
        self.assertTrue(all(r["impronta_pagina"] is None and r["url_prova"] is None
                            and r["trovato_in_fonte_at"] is None for r in righe))

    def test_url_di_riferimento_esplicito(self):
        effettivo = UFFICIALE + "?pagina=1"
        righe = fu.righe_link_da_payload(self.BANDO, self._payload(), self.HTML,
                                         url_riferimento=effettivo)
        self.assertEqual({r["url_prova"] for r in righe}, {effettivo})

    def test_bando_senza_id(self):
        self.assertEqual(fu.righe_link_da_payload({}, self._payload(), self.HTML), [])


class _Pagina:
    def __init__(self, html, *, stato=200, url_finale=""):
        self.html = html
        self.stato = stato
        self.url_finale = url_finale

    @property
    def ok(self):
        return 200 <= self.stato < 300


class QuartaProva(unittest.TestCase):
    """`run_link_verifica` con righe, riferimenti e pagine iniettati."""

    def _esegui(self, righe, riferimenti, pagine, *, verifica=None, **kwargs):
        scritte: list[tuple] = []
        scaricate: list[str] = []

        async def scarica_pagina(url):
            scaricate.append(url)
            return pagine.get(url)

        def aggiorna(link_id, payload, **_k):
            scritte.append((link_id, dict(payload)))
            return {"scritto": True}

        with unittest.mock.patch.object(fu.db, "aggiorna_link", aggiorna), \
                unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: set()):
            esito = esegui(fu.run_link_verifica(
                righe=righe, attivo=True, riferimenti=riferimenti, scarica_pagina=scarica_pagina,
                verifica=verifica or (lambda _u: (200, "application/pdf", "", None, None)),
                tempo_s=kwargs.pop("tempo_s", 600.0), **kwargs))
        return esito, scritte, scaricate

    RIF_TROVATA = {"id": 9, "link_bando": OE, "fonte_ufficiale_url": UFFICIALE,
                   "fonte_ufficiale_stato": "trovata"}
    RIF_SENZA = {"id": 9, "link_bando": OE, "fonte_ufficiale_url": None,
                 "fonte_ufficiale_stato": "non_trovata"}

    def test_la_prova_sulla_pagina_ufficiale_rende_pubblicabile(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO}, {"id": 2, "bando_id": 9, "url": ALLEGATO}]
        pagine = {UFFICIALE: _Pagina(f'<a href="{MODULO}">m</a> <a href="/allegati/avviso.pdf?v=1'
                                     '&amp;a=2">a</a>', url_finale=UFFICIALE + "/")}
        esito, scritte, scaricate = self._esegui(righe, {9: self.RIF_TROVATA}, pagine)
        self.assertEqual(scaricate, [UFFICIALE], "una pagina per bando per giro")
        self.assertEqual(esito["prove_trovate"], 2)
        self.assertEqual(esito["pubblicabili"], 2)
        for _id, payload in scritte:
            self.assertTrue(payload["pubblicabile"])
            self.assertEqual(payload["url_prova"], UFFICIALE + "/")
            self.assertTrue(payload["impronta_pagina"])
            self.assertIn("trovato_in_fonte_at", payload)

    def test_senza_fonte_trovata_vale_link_bando_anche_su_aggregatore(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO}]
        pagine = {OE: _Pagina(f'<a href="{MODULO}">Modulo</a>')}
        esito, scritte, _s = self._esegui(righe, {9: self.RIF_SENZA}, pagine)
        self.assertEqual(esito["prove_trovate"], 1)
        self.assertEqual(scritte[0][1]["url_prova"], OE)
        self.assertTrue(scritte[0][1]["pubblicabile"])

    def test_pagina_di_riferimento_non_2xx_nessuna_prova(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO}]
        pagine = {OE: _Pagina(f'<a href="{MODULO}">m</a>', stato=404)}
        esito, scritte, _s = self._esegui(righe, {9: self.RIF_SENZA}, pagine)
        self.assertEqual((esito["prove_trovate"], esito["prove_mancate"]), (0, 1))
        self.assertEqual(esito["senza_prova"], 1)
        self.assertFalse(scritte[0][1]["pubblicabile"])
        self.assertNotIn("impronta_pagina", scritte[0][1])

    def test_un_link_che_non_risponde_o_su_aggregatore_non_cerca_la_prova(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO},
                 {"id": 2, "bando_id": 9, "url": OE + "/scheda.pdf"}]
        esito, _scritte, scaricate = self._esegui(
            righe, {9: self.RIF_TROVATA}, {UFFICIALE: _Pagina(f'<a href="{MODULO}">m</a>')},
            verifica=lambda url: (404 if url == MODULO else 200, None, "", None, None))
        self.assertEqual(scaricate, [])
        self.assertEqual(esito["prove_trovate"], 0)

    def test_la_prova_si_rifa_sulla_pagina_ufficiale(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO, "impronta_pagina": "vecchia#1",
                  "url_prova": OE, "trovato_in_fonte_at": "2026-09-01T00:00:00+00:00",
                  "pubblicabile": True}]
        pagine = {UFFICIALE: _Pagina(f'<a href="{MODULO}">m</a>')}
        esito, scritte, _s = self._esegui(righe, {9: self.RIF_TROVATA}, pagine)
        self.assertEqual(esito["prove_rifatte"], 1)
        self.assertEqual(scritte[0][1]["url_prova"], UFFICIALE)
        self.assertNotEqual(scritte[0][1]["impronta_pagina"], "vecchia#1")

    def test_mancata_sulla_ufficiale_non_si_ritira_niente(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO, "impronta_pagina": "vecchia#1",
                  "url_prova": OE, "trovato_in_fonte_at": "2026-09-01T00:00:00+00:00",
                  "pubblicabile": True}]
        pagine = {UFFICIALE: _Pagina("<p>pagina senza il link</p>")}
        esito, scritte, _s = self._esegui(righe, {9: self.RIF_TROVATA}, pagine)
        self.assertEqual(esito["solo_aggregatore"], 1)
        payload = scritte[0][1]
        self.assertTrue(payload["pubblicabile"])
        self.assertNotIn("impronta_pagina", payload)
        self.assertNotIn("url_prova", payload)

    def test_una_prova_gia_ufficiale_non_si_rifa(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO, "impronta_pagina": "x#1",
                  "url_prova": UFFICIALE, "pubblicabile": True}]
        esito, _scritte, scaricate = self._esegui(
            righe, {9: self.RIF_TROVATA}, {UFFICIALE: _Pagina("")})
        self.assertEqual(scaricate, [])
        self.assertEqual((esito["prove_rifatte"], esito["solo_aggregatore"]), (0, 0))

    def test_tempo_finito_con_copertura(self):
        righe = [{"id": i, "bando_id": 9, "url": MODULO} for i in range(3)]
        esito, scritte, _s = self._esegui(righe, {}, {}, tempo_s=0.0)
        self.assertEqual((esito["esaminati"], scritte), (0, []))
        self.assertEqual(esito["copertura"],
                         {"candidati": 3, "fatti": 0, "rimasti": 3, "motivo_rimasti": "tempo"})

    def test_copertura_piena_e_giro(self):
        righe = [{"id": 1, "bando_id": 9, "url": MODULO}]
        esito, _s, _p = self._esegui(righe, {}, {}, giro="06:00")
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 1, "rimasti": 0, "motivo_rimasti": None})
        self.assertEqual(esito["giro"], "06:00")


class RotazioneDelleRighe(unittest.TestCase):
    """Revisione #147 (P1): prima le righe mai verificate, poi dall'ultima
    verifica piu' vecchia, poi per id. Con un tempo che basta per meta' delle
    righe, la riga nuova con l'id piu' alto passa per prima."""

    RIGHE = [
        {"id": 1, "url": "https://a.it/1", "esito_http": 200, "updated_at": "2020-01-03T10:00:00+00:00"},
        {"id": 2, "url": "https://a.it/2", "esito_http": 404, "updated_at": "2020-01-01T10:00:00+00:00"},
        {"id": 3, "url": "https://a.it/3", "esito_http": 200, "updated_at": "2020-01-02T10:00:00.5+00:00"},
        {"id": 9, "url": "https://a.it/9", "esito_http": None, "updated_at": "2020-01-04T10:00:00+00:00"},
    ]

    def test_la_riga_nuova_per_prima_con_meta_del_tempo(self):
        verificati: list[str] = []
        # Il tempo «finisce» dopo due righe. Legato alle righe e non alle
        # chiamate: `time.monotonic` lo usa anche l'event loop.
        orologio = lambda: 100.0 if len(verificati) >= 2 else 0.0  # noqa: E731

        def seleziona(*, limit=None, offset=0, bando_id=None, **_k):
            return [dict(r) for r in self.RIGHE][offset:offset + (limit or 1000)]

        def verifica(url):
            verificati.append(url)
            return (200, None, "", None, None)

        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", seleziona), \
                unittest.mock.patch.object(fu.db, "select_riferimenti_bandi", lambda ids, **k: {}), \
                unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: set()), \
                unittest.mock.patch.object(fu.time, "monotonic", orologio):
            esito = esegui(fu.run_link_verifica(dry_run=True, verifica=verifica, tempo_s=5.0))
        self.assertEqual(verificati, ["https://a.it/9", "https://a.it/2"])
        self.assertEqual(esito["copertura"],
                         {"candidati": 4, "fatti": 2, "rimasti": 2, "motivo_rimasti": "tempo"})

    def test_l_ordine_completo_e_il_limit_dopo_l_ordine(self):
        def seleziona(*, limit=None, offset=0, bando_id=None, **_k):
            return [dict(r) for r in self.RIGHE][offset:offset + (limit or 1000)]

        contatori = {"saltate": 0}
        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", seleziona):
            tutte = fu._da_verificare(limit=None, offset=0, bando_id=None,
                                      oggi=fu.oggi_roma(), contatori=contatori)
            due = fu._da_verificare(limit=2, offset=0, bando_id=None,
                                    oggi=fu.oggi_roma(), contatori=contatori)
        self.assertEqual([r["id"] for r in tutte], [9, 2, 3, 1])
        self.assertEqual([r["id"] for r in due], [9, 2])


class FrenoInProduzione(unittest.TestCase):
    """Senza verificatore iniettato: freno per host e richiesta in un thread."""

    def test_freno_e_thread(self):
        attese: list[str] = []
        thread: list[int] = []
        principale = threading.get_ident()

        class _Verifica:
            def __init__(self, **_k):
                pass

            def __call__(self, url):
                thread.append(threading.get_ident())
                return (200, None, "", None, None)

            def chiudi(self):
                pass

        async def attendi(host):
            attese.append(host)

        righe = [{"id": 1, "url": MODULO}, {"id": 2, "url": "https://altro.it/a.pdf"}]
        with unittest.mock.patch.object(fu, "VerificaHttp", _Verifica), \
                unittest.mock.patch.object(http, "_wait_for_host", attendi), \
                unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: set()):
            esito = esegui(fu.run_link_verifica(righe=righe, dry_run=True, tempo_s=600.0))
        self.assertEqual(attese, ["www.regione.marche.it", "altro.it"])
        self.assertEqual(len(thread), 2)
        self.assertNotIn(principale, thread, "la HEAD non gira sull'event loop")
        self.assertEqual(esito["esaminati"], 2)


class AllegatiCortesi(unittest.TestCase):
    """P2 (1) della revisione #144: la verifica degli allegati del resolver."""

    HTML = ('<html><body><main><h1>Bando</h1>'
            '<a href="https://www.regione.marche.it/allegati/avviso.pdf">Avviso</a>'
            '<a href="https://www.regione.marche.it/allegati/modulo.pdf">Modulo</a>'
            '</main></body></html>')

    def test_estrai_in_un_thread_e_verifica_cortese_sul_loop(self):
        chiamate: list[tuple[str, int]] = []
        principale: list[int] = []

        async def cortese(url):
            chiamate.append((url, threading.get_ident()))
            return (200, "application/pdf", "", None, None)

        def sincrona(_url):                          # pragma: no cover - non deve servire
            raise AssertionError("la verifica sincrona non deve partire")

        candidato = fu.Candidato(url="https://www.regione.marche.it/bandi/x",
                                 pagina=fu.Pagina(url="https://www.regione.marche.it/bandi/x",
                                                  stato=200, html=self.HTML))
        amb = fu.Ambiente(verifica_allegato=sincrona, verifica_cortese=cortese)

        async def giro():
            principale.append(threading.get_ident())
            return await fu._passo_allegati(candidato, fu.Contesto(titolo="Bando"), amb)

        allegati, stati = esegui(giro())
        self.assertEqual(sorted(a["url"] for a in allegati), [
            "https://www.regione.marche.it/allegati/avviso.pdf",
            "https://www.regione.marche.it/allegati/modulo.pdf"])
        self.assertEqual({s for _u, s in stati}, {200})
        # Le coroutine cortesi girano sull'event loop, non nel thread di estrai.
        self.assertTrue(all(ident == principale[0] for _u, ident in chiamate))

    def test_un_host_appeso_non_blocca_il_thread(self):
        ciclo = asyncio.new_event_loop()
        pronto = threading.Event()

        def gira():
            asyncio.set_event_loop(ciclo)
            pronto.set()
            ciclo.run_forever()

        filo = threading.Thread(target=gira, daemon=True)
        filo.start()
        pronto.wait()
        try:
            async def appesa(_url):
                await asyncio.sleep(5)

            verifica = fu.verifica_sincrona_cortese(appesa, ciclo, timeout_s=0.05)
            inizio = time.monotonic()
            self.assertIsNone(verifica("https://ente.it/a.pdf"))
            self.assertLess(time.monotonic() - inizio, 2)
        finally:
            ciclo.call_soon_threadsafe(ciclo.stop)
            filo.join(timeout=2)
            ciclo.close()

    def test_l_ambiente_di_produzione_ha_la_verifica_cortese(self):
        tabella = fu.TABELLA_SEED
        with unittest.mock.patch.object(fu, "_tabella_corrente", return_value=tabella), \
                unittest.mock.patch.object(fu.oe_scheda, "scarico_predefinito", return_value=None):
            amb = fu._ambiente_predefinito(step="resolver", attivo=False)
        self.assertIsNotNone(amb.verifica_cortese)


class CoperturaSenzaRinviati(unittest.TestCase):
    """P2 (2) della revisione #144: un bando rinviato non e' «fatto»."""

    def test_rinviati_per_tempo_e_dns(self):
        contatori = fu.Contatori(rinviati_tempo=1, rinviati_dns=2)
        self.assertEqual(fu._copertura_del_giro(10, 10, None, contatori),
                         {"candidati": 10, "fatti": 7, "rimasti": 3, "motivo_rimasti": "tempo"})
        solo_dns = fu.Contatori(rinviati_dns=2)
        self.assertEqual(fu._copertura_del_giro(10, 10, None, solo_dns)["motivo_rimasti"], "errore")
        self.assertEqual(fu._copertura_del_giro(10, 10, None, fu.Contatori()),
                         {"candidati": 10, "fatti": 10, "rimasti": 0, "motivo_rimasti": None})

    def test_nel_giro_del_resolver(self):
        async def scarica(url):
            return fu.Pagina(url=url, stato=None, host_irraggiungibile=True)

        amb = fu.Ambiente(tabella=fu.TABELLA_SEED, scarica=scarica)
        righe = [{"id": 1, "titolo": "Bando", "raw_data": {"external_link": "https://morto.it/a"},
                  "link_bando": "https://morto.it/a", "fonte_ufficiale_stato": "in_verifica"}]
        with unittest.mock.patch.object(fu.blocco, "acquisisci",
                                        return_value=SimpleNamespace(proseguire=True)), \
                unittest.mock.patch.object(fu.blocco, "rilascia", lambda _l: None), \
                unittest.mock.patch.object(fu.db, "select_bandi_da_risolvere",
                                           lambda **k: righe if k.get("offset", 0) == 0 else []), \
                unittest.mock.patch.object(fu.db, "select_controlli", lambda ids, **k: {}), \
                unittest.mock.patch.object(fu.db, "select_pubblicati_per_gemelli",
                                           return_value=[]), \
                unittest.mock.patch.object(fu.db, "select_link_da_verificare", return_value=[]), \
                unittest.mock.patch.object(fu, "schede_gia_lette", return_value=frozenset()), \
                unittest.mock.patch.object(fu, "_registra", lambda *_a, **_k: None), \
                unittest.mock.patch.object(fu, "scrivi_esito", lambda *a, **k: {}):
            esito = esegui(fu.run(ambiente=amb, modo="ricontrolli", dry_run=True))
        self.assertEqual(esito["rinviati_dns"], 1)
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 0, "rimasti": 1, "motivo_rimasti": "errore"})


class GuardiaIndirizzi(unittest.TestCase):
    """§18.6: niente richieste verso la rete interna, nemmeno via redirect."""

    def _verifica(self, rotte, url):
        import httpx
        chieste: list[str] = []

        def gestore(richiesta):
            chieste.append(f"{richiesta.method} {richiesta.url}")
            stato, intestazioni = rotte.get(str(richiesta.url), (404, {}))
            return httpx.Response(stato, headers=intestazioni, content=b"%PDF-1.7 contenuto")

        verificatore = fu.VerificaHttp(transport=httpx.MockTransport(gestore))
        try:
            return verificatore(url), chieste, verificatore
        finally:
            verificatore.chiudi()

    def test_redirect_verso_la_rete_interna(self):
        rotte = {"https://ente.it/a.pdf": (302, {"location": "http://intranet.ente.it/x"})}
        esito, chieste, verificatore = self._verifica(rotte, "https://ente.it/a.pdf")
        self.assertIsNone(esito)
        self.assertEqual(chieste, ["HEAD https://ente.it/a.pdf"],
                         "l'indirizzo interno non si chiede, ne' in HEAD ne' in GET")
        self.assertEqual(verificatore.rifiutati, 1)

    def test_redirect_relativo_verso_localhost_per_ip(self):
        rotte = {"https://ente.it/a.pdf": (301, {"location": "http://127.0.0.1:8000/summarize_news"})}
        esito, chieste, _v = self._verifica(rotte, "https://ente.it/a.pdf")
        self.assertIsNone(esito)
        self.assertEqual(len(chieste), 1)

    def test_url_interno_non_parte_nessuna_richiesta(self):
        esito, chieste, verificatore = self._verifica({}, "http://localhost:8000/reconstruct_article")
        self.assertIsNone(esito)
        self.assertEqual(chieste, [])
        self.assertEqual(verificatore.rifiutati, 1)

    def test_redirect_pubblici_si_seguono(self):
        rotte = {"https://ente.it/a": (302, {"location": "/b"}),
                 "https://ente.it/b": (301, {"location": "https://cdn.ente.it/b.pdf"}),
                 "https://cdn.ente.it/b.pdf": (200, {"content-type": "application/pdf"})}
        esito, chieste, _v = self._verifica(rotte, "https://ente.it/a")
        self.assertEqual(esito["esito_http"], 200)
        self.assertEqual(esito["content_type"], "application/pdf")
        self.assertEqual(len(chieste), 3)

    def test_head_405_poi_get_con_la_guardia(self):
        import httpx
        chieste: list[str] = []

        def gestore(richiesta):
            chieste.append(richiesta.method)
            if richiesta.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(302, headers={"location": "http://intranet.ente.it/a"})

        verificatore = fu.VerificaHttp(transport=httpx.MockTransport(gestore))
        self.assertIsNone(verificatore("https://ente.it/a.pdf"))
        verificatore.chiudi()
        self.assertEqual(chieste, ["HEAD", "GET"], "il redirect interno della GET non si segue")

    def test_troppi_redirect(self):
        rotte = {f"https://ente.it/{i}": (302, {"location": f"/{i + 1}"}) for i in range(10)}
        esito, chieste, _v = self._verifica(rotte, "https://ente.it/0")
        self.assertIsNone(esito)
        self.assertLessEqual(len(chieste), 2 * (fu.MAX_REDIRECT_VERIFICA + 1))

    def _verifica_link(self, righe, *, verifica=None):
        scritte: list[tuple] = []
        chiesti: list[str] = []

        def aggiorna(link_id, payload, **_k):
            scritte.append((link_id, dict(payload)))
            return {"scritto": True}

        def verifica_finta(url):
            chiesti.append(url)
            return (200, "application/pdf", "", None, None)

        async def guardia(url):
            return http.classifica_indirizzo(url)

        with unittest.mock.patch.object(fu.db, "aggiorna_link", aggiorna), \
                unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: set()):
            esito = esegui(fu.run_link_verifica(
                righe=righe, attivo=True, verifica=verifica or verifica_finta,
                guardia=guardia, tempo_s=600.0))
        return esito, scritte, chiesti

    def test_link_verifica_ritira_un_indirizzo_interno(self):
        righe = [{"id": 1, "url": "http://intranet.ente.it/a.pdf", "pubblicabile": True,
                  "impronta_pagina": "x#1"},
                 {"id": 2, "url": ALLEGATO, "impronta_pagina": "y#2"}]
        esito, scritte, chiesti = self._verifica_link(righe)
        self.assertEqual(chiesti, [ALLEGATO], "l'indirizzo interno non si chiede")
        self.assertEqual(esito["indirizzi_rifiutati"], 1)
        self.assertEqual(scritte[0], (1, {"esito_http": 0, "content_type": None,
                                          "pubblicabile": False}))

    def test_link_verifica_dns_giu_non_ritira(self):
        # Un DNS che non risponde e' la nostra rete, non il link: la riga gia'
        # pubblicabile resta com'e' (nessuna risposta, `rimandati`).
        righe = [{"id": 1, "url": "https://giu.ente.it/a.pdf", "pubblicabile": True,
                  "impronta_pagina": "x#1"}]
        esito, scritte, _chiesti = self._verifica_link(righe, verifica=lambda u: None)
        self.assertEqual(esito["indirizzi_rifiutati"], 0)
        self.assertEqual(esito["rimandati"], 1)
        self.assertEqual(scritte, [])

    def test_link_verifica_in_produzione_ha_la_guardia(self):
        # Nessun `verifica` iniettato: la guardia c'e' anche se non la si passa.
        chieste: list[str] = []

        class _Verifica:
            def __init__(self, *a, **k):
                pass

            def __call__(self, url):
                chieste.append(url)
                return (200, "application/pdf", "", None, None)

            def chiudi(self):
                pass

        async def attendi(_host):
            return None

        righe = [{"id": 1, "url": "http://localhost/x"}, {"id": 2, "url": MODULO}]
        with unittest.mock.patch.object(fu, "VerificaHttp", _Verifica), \
                unittest.mock.patch.object(http, "_wait_for_host", attendi), \
                unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: set()):
            esito = esegui(fu.run_link_verifica(righe=righe, dry_run=True, tempo_s=600.0))
        self.assertEqual(chieste, [MODULO])
        self.assertEqual(esito["indirizzi_rifiutati"], 1)

    def test_righe_dal_payload_senza_indirizzi_interni(self):
        bando = {"id": 1, "fonte_ufficiale_url": UFFICIALE, "fonte_ufficiale_stato": "trovata",
                 "link_bando": OE}
        payload = {"link_candidatura_source": "extracted",
                   "link_candidatura": "http://169.254.169.254/latest/meta-data",
                   "allegati": [{"label": "Interno", "url": "https://intranet.ente.it/a.pdf"},
                                {"label": "Giu'", "url": "https://giu.ente.it/b.pdf"},
                                {"label": "Avviso", "url": ALLEGATO}]}
        righe = fu.righe_link_da_payload(bando, payload, None)
        self.assertEqual([r["url"] for r in righe], ["https://giu.ente.it/b.pdf", ALLEGATO],
                         "si scartano gli interni; un DNS giu' non basta a scartare")


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
