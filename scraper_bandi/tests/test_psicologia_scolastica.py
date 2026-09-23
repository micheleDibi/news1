# -*- coding: utf-8 -*-
"""Caso end-to-end «Psicologia scolastica» (piano §6.2), percorso G2'.

Il caso reale, ricostruito come caso L6 (la semina delle impronte arriva DOPO
il differimento del 18/09, quindi un «prima» non esiste e il percorso e' G2'):

  * il bando 905315 di lazioeuropa e' `in apertura prossimamente` e in colonna
    ha `data_scadenza = 2026-10-06`;
  * la pagina ufficiale, al primo controllo, dice «con determinazione DD 12 del
    18/09/2026 e' stato disposto il differimento dei termini: le domande si
    presentano dal 22 ottobre al 1° dicembre 2026»;
  * `estrai_date_con_ruolo` legge il costrutto «dal X al Y» (22/10 apertura,
    1/12 scadenza) e scarta 18/09 come data **normativa**;
  * le due coppie (data, ruolo) sono assenti dalle colonne -> mismatch -> il
    classificatore propone due `rettifica`;
  * G1-G9 passano, con G2' e il G7 rafforzato (seconda opinione **e** pagina
    collegata: il post 21558 della REST API di WordPress);
  * l'applicazione scrive le due date con i flag `*_verificata`, l'evento e'
    leggibile e in `in_aggiornamenti`, e la prosa sostituisce «6 ottobre 2026»
    con «1 dicembre 2026» **solo** nelle frasi con una parola di scadenza;
  * lo slug torna al chiamante per IndexNow.

Le fixture sono scritte qui e non scaricate: il test non fa rete.
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

monitoraggio = carica_modulo("monitoraggio")
eventi = carica_modulo("eventi")
rigenera = carica_modulo("rigenera")
date_validation = carica_modulo("date_validation")
dominio_ufficiale = carica_modulo("dominio_ufficiale")
blocco = carica_modulo("blocco")

BANDO_ID = 905315
SLUG = "psicologia-scolastica-nelle-scuole-del-lazio"
URL_BANDO = "https://www.lazioeuropa.it/bandi/psicologia-scolastica/"
URL_NOTIZIA = "https://www.lazioeuropa.it/2026/09/18/differimento-psicologia-scolastica/"

ADESSO = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
OGGI = date(2026, 9, 23)

# --- fixture ----------------------------------------------------------------

PAGINA_BANDO = """<!doctype html>
<html lang="it">
<head><title>Psicologia scolastica | Lazio Europa</title></head>
<body>
<nav id="main-menu"><a href="/bandi/">Tutti i bandi</a></nav>
<main>
  <h1>Avviso pubblico «Psicologia scolastica nelle scuole del Lazio»</h1>
  <p>La Regione Lazio sostiene l'attivazione di sportelli di ascolto psicologico
  nelle istituzioni scolastiche del territorio regionale.</p>
  <h2>Termini di presentazione</h2>
  <p>Con determinazione DD 12 del 18/09/2026 e' stato disposto il differimento
  dei termini: le domande si presentano dal 22 ottobre al 1&deg; dicembre 2026.</p>
  <h2>Dotazione</h2>
  <p>La dotazione complessiva e' di 4.500.000 euro.</p>
</main>
<aside class="bandi-correlati"><a href="/bandi/altro-avviso/">Altro avviso</a></aside>
<footer>Regione Lazio</footer>
</body></html>
"""

PAGINA_NOTIZIA = """<!doctype html>
<html lang="it"><body><main>
<h1>Psicologia scolastica: differiti i termini</h1>
<p>La presentazione delle domande e' differita: la finestra va dal 22 ottobre
al 1&deg; dicembre 2026.</p>
</main></body></html>
"""

CONTENUTO_PUBBLICATO = (
    "La Regione Lazio finanzia gli sportelli di ascolto psicologico "
    "nelle scuole del territorio.\n\n"
    "Le domande vanno presentate entro il 6 ottobre 2026 sulla piattaforma "
    "regionale.\n\n"
    "L'avviso e' stato adottato con determinazione DD 12 del 6 ottobre 2026 "
    "e la dotazione complessiva e' di 4.500.000 euro."
)

TABELLA_DOMINI = dominio_ufficiale.Tabella(
    dominio_ufficiale.SEED + (
        dominio_ufficiale.Dominio(
            host="lazioeuropa.it", tipo="ente", confidenza=0.95,
            ente="Regione Lazio — Lazio Europa"),
    )
)

CITAZIONE = (
    "differimento dei termini: le domande si presentano "
    "dal 22 ottobre al 1° dicembre 2026"
)


def _bando_in_archivio():
    """La riga come sta in `bando` PRIMA del controllo (mai vista la pagina)."""
    return {
        "id": BANDO_ID,
        "slug": SLUG,
        "titolo": "Psicologia scolastica nelle scuole del Lazio",
        "pubblicato": True,
        "bando_master_id": None,
        "stato_processing": "completed",
        "stato_bando": "in apertura prossimamente",
        "data_apertura": None,
        "data_apertura_verificata": False,
        "data_scadenza": "2026-10-06",
        "ora_scadenza": None,
        "data_pubblicazione": None,
        "fonte_ufficiale_stato": "trovata",
        "fonte_ufficiale_url": URL_BANDO,
        "prossimo_controllo_at": (ADESSO - timedelta(hours=2)).isoformat(),
        # Semina L6: nessuna impronta, nessun testo precedente.
        "impronta_contenuto": None,
        "testo_norm": None,
        "controlli_falliti": 0,
        "contenuto": CONTENUTO_PUBBLICATO,
        "descrizione_breve": "x" * 250,
        "prove": (),
    }


class _Risposta:
    def __init__(self, html, stato=200):
        self.stato = stato
        self.html = html
        self.markdown = ""
        self.etag = None
        self.last_modified = None

    @property
    def testo(self):
        impronte = carica_modulo("impronte")
        return impronte.testo_normalizzato(self.html)

    @property
    def ok(self):
        return 200 <= self.stato < 300

    @property
    def vuota(self):
        return not self.html.strip()


def _proposte():
    """Cio' che il classificatore (Haiku) emette su questo diff."""
    return [
        eventi.Evento(
            tipo="rettifica", campo="data_apertura", valore="2026-10-22",
            citazione=CITAZIONE, url_prova=URL_BANDO, confidenza_llm=0.9,
        ),
        eventi.Evento(
            tipo="rettifica", campo="data_scadenza", valore="2026-12-01",
            citazione=CITAZIONE, url_prova=URL_BANDO, confidenza_llm=0.9,
        ),
    ]


async def _scarica(url, **kw):
    if url == URL_BANDO:
        return _Risposta(PAGINA_BANDO)
    if url == URL_NOTIZIA:
        return _Risposta(PAGINA_NOTIZIA)
    raise AssertionError(f"URL non previsto dalla fixture: {url}")


async def _classifica(ctx):
    return _proposte()


async def _seconda_opinione(ctx):
    # Sonnet concorda su entrambe le letture.
    return _proposte()


async def _pagine_collegate(riga):
    # `wp/v2/posts?search=psicologia scolastica&after=...` restituisce il post.
    return [URL_NOTIZIA]


def _rigeneratore(registro):
    """Rigeneratore finto che riscrive davvero la prosa con `rigenera.py`.

    Il monitor lo chiama solo in attivo e solo per le date: e' il punto in cui
    la pagina pubblica smette di dire «6 ottobre» mentre la colonna dice
    «1 dicembre». Senza, lo slug non deve finire in `slug_modificati`.
    """
    async def rigenerazione(bando, evento, *, vecchia, nuova, ruolo):
        async def scrivi(bando_id, payload):
            registro.append((bando_id, dict(payload)))
            return True

        esito = await rigenera.rigenera(
            bando, evento, vecchia=vecchia, nuova=nuova, ruolo=ruolo,
            attivo=True, scrivi=scrivi,
        )
        return esito

    return rigenerazione


class TestLetturaDellaPagina(unittest.TestCase):
    """Il pezzo deterministico: le date e i loro ruoli."""

    def test_costrutto_dal_al_e_data_normativa(self):
        impronte = carica_modulo("impronte")
        testo = impronte.testo_normalizzato(PAGINA_BANDO)
        trovate = date_validation.estrai_date_con_ruolo(testo)
        per_data = {d.data: d.ruolo for d in trovate}
        self.assertEqual(per_data[date(2026, 10, 22)], "apertura")
        self.assertEqual(per_data[date(2026, 12, 1)], "scadenza")
        # La data del decreto non e' ne' apertura ne' scadenza.
        self.assertEqual(per_data[date(2026, 9, 18)], "normativa")

    def test_i_bandi_correlati_non_entrano_nel_testo(self):
        impronte = carica_modulo("impronte")
        testo = impronte.testo_normalizzato(PAGINA_BANDO)
        self.assertNotIn("Altro avviso", testo)


class TestPercorsoG2Primo(unittest.TestCase):
    def _ctx(self):
        impronte = carica_modulo("impronte")
        testo = impronte.testo_normalizzato(PAGINA_BANDO)
        return eventi.Contesto(
            bando_id=BANDO_ID,
            stato_bando="in apertura prossimamente",
            data_apertura=None,
            data_scadenza=date(2026, 10, 6),
            pagine=(
                eventi.Pagina(url=URL_BANDO, testo=testo,
                              impronta=impronte.impronta_contenuto(PAGINA_BANDO)),
                eventi.Pagina(url=URL_NOTIZIA,
                              testo=impronte.testo_normalizzato(PAGINA_NOTIZIA),
                              impronta=impronte.impronta_contenuto(PAGINA_NOTIZIA),
                              collegata=True),
            ),
            diff=None,
            testo_prima=None,
            prove=(
                eventi.Prova(genere="pagina_collegata", data=date(2026, 10, 22),
                             ruolo="apertura", url=URL_NOTIZIA),
                eventi.Prova(genere="pagina_collegata", data=date(2026, 12, 1),
                             ruolo="scadenza", url=URL_NOTIZIA),
            ),
            seconda_opinione=_proposte(),
            tabella_domini=TABELLA_DOMINI,
            oggi=OGGI,
            stati_estesi=False,
            modalita="attivo",
        )

    def test_gate_applicato_e_g2_primo(self):
        for evento in _proposte():
            with self.subTest(campo=evento.campo):
                giudizio = eventi.valuta(evento, self._ctx())
                self.assertEqual(giudizio.gate, "G2'")

    def test_scadenza_passa_tutti_i_gate(self):
        scadenza = _proposte()[1]
        giudizio = eventi.valuta(scadenza, self._ctx())
        self.assertTrue(giudizio.ammesso, giudizio.motivo)
        self.assertIn("G7", giudizio.superati)

    def test_apertura_da_sola_cade_sulla_coerenza(self):
        # Valutata PRIMA della scadenza, l'apertura del 22/10 e' incoerente con
        # la scadenza ancora in colonna (6/10): e' il motivo per cui il monitor
        # ordina le proposte dalla data piu' lontana.
        apertura = _proposte()[0]
        giudizio = eventi.valuta(apertura, self._ctx())
        self.assertFalse(giudizio.ammesso)
        self.assertIn("G5", [g for g, _ in giudizio.falliti])

    def test_ordine_delle_proposte(self):
        ordinate = monitoraggio.ordina_proposte(_proposte())
        self.assertEqual([e.campo for e in ordinate], ["data_scadenza", "data_apertura"])

    def test_senza_seconda_opinione_g7_respinge(self):
        from dataclasses import replace
        ctx = replace(self._ctx(), seconda_opinione=None)
        giudizio = eventi.valuta(_proposte()[1], ctx)
        self.assertFalse(giudizio.ammesso)
        self.assertIn("G7", [g for g, _ in giudizio.falliti])

    def test_senza_pagina_collegata_g7_respinge(self):
        from dataclasses import replace
        ctx = replace(self._ctx(), prove=())
        giudizio = eventi.valuta(_proposte()[1], ctx)
        self.assertFalse(giudizio.ammesso)
        self.assertIn("G7", [g for g, _ in giudizio.falliti])

    def test_modified_non_sostituisce_la_pagina_collegata(self):
        from dataclasses import replace
        ctx = replace(self._ctx(), prove=(
            eventi.Prova(genere="modified", data=date(2026, 12, 1), ruolo="scadenza"),))
        giudizio = eventi.valuta(_proposte()[1], ctx)
        self.assertFalse(giudizio.ammesso)

    def test_data_del_decreto_respinta(self):
        # Se il modello leggesse 18/09 come nuovo termine, G3 la ferma.
        sbagliata = eventi.Evento(
            tipo="rettifica", campo="data_scadenza", valore="2026-09-18",
            citazione="Con determinazione DD 12 del 18/09/2026 e' stato disposto il differimento",
            url_prova=URL_BANDO,
        )
        giudizio = eventi.valuta(sbagliata, self._ctx())
        self.assertFalse(giudizio.ammesso)
        self.assertIn("G3", [g for g, _ in giudizio.falliti])


def _zittisci_io(caso):
    """Telemetria e RPC fuori dal test: nessuna connessione, nemmeno fallita.

    La migrazione 02/04 non e' applicata, quindi `bando_registra_evento` non
    esiste: qui lo si dichiara invece di andare a scoprirlo con una GET.
    """
    for bersaglio in (
        patch.object(monitoraggio, "_scrivi_telemetria", MagicMock()),
        patch.object(eventi, "_rpc_disponibile", lambda controllo: False),
    ):
        bersaglio.start()
        caso.addCleanup(bersaglio.stop)


class TestControlloCompleto(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_controllo_attivo_applica_entrambe_le_date(self):
        registrati = []
        scritture = []

        class _Dati(monitoraggio.FonteDati):
            def registra_evento(self, riga):
                registrati.append(dict(riga))
                return True

            def salva_controllo(self, bando_id, payload):
                scritture.append((bando_id, dict(payload)))
                return True

        esito = await monitoraggio.controlla(
            _bando_in_archivio(),
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            fonte_dati=_Dati(),
            modalita="attivo",
            scenario="bilanciato",
            tabella_domini=TABELLA_DOMINI,
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )

        self.assertEqual(esito.esito, "ok")
        self.assertTrue(esito.classificato)
        self.assertEqual(len(esito.eventi), 2, esito.respinti)
        self.assertEqual(esito.respinti, ())

        # Le colonne di `bando` stanno in `colonne_bando`: sono di un'altra
        # tabella e le scrive la RPC, non l'upsert delle colonne calde.
        colonne = esito.colonne_bando
        self.assertEqual(colonne["data_scadenza"], "2026-12-01")
        self.assertEqual(colonne["data_apertura"], "2026-10-22")
        self.assertTrue(colonne["data_scadenza_verificata"])
        self.assertTrue(colonne["data_apertura_verificata"])
        # `rettifica` non cambia lo stato: resta «in apertura prossimamente».
        self.assertNotIn("stato_bando", colonne)
        # E non trapelano nel payload di `bando_controllo`: prima ci finivano
        # e a scartarle era solo il filtro di `db.controllo`.
        for colonna in ("data_scadenza", "data_apertura",
                        "data_scadenza_verificata", "stato_bando"):
            self.assertNotIn(colonna, esito.colonne)
            self.assertNotIn(colonna, scritture[0][1])

        # Gli eventi sono leggibili e vanno nel box «Aggiornamenti».
        for riga in registrati:
            self.assertTrue(riga["leggibile"])
            self.assertTrue(riga["in_aggiornamenti"])
            self.assertTrue(riga["verificato"])
            self.assertEqual(riga["gate"], "G2'")
            self.assertEqual(riga["url_prova"], URL_BANDO)
            # `dominio_prova` NON sta nella riga: in tabella e' GENERATED
            # ALWAYS (02:581) e un INSERT che la valorizzi risponde 428C9.
            # Il dominio lo calcola Postgres da `url_prova`.
            self.assertNotIn("dominio_prova", riga)

        # Tre pagine scaricate in tutto: la scheda e la pagina collegata.
        self.assertEqual(esito.fetch, 2)
        self.assertEqual(scritture[0][0], BANDO_ID)

    async def test_in_ombra_niente_colonne_leggibili(self):
        esito = await monitoraggio.controlla(
            _bando_in_archivio(),
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            fonte_dati=monitoraggio.FonteDati(),
            modalita="ombra",
            tabella_domini=TABELLA_DOMINI,
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )
        self.assertEqual(len(esito.eventi), 2)
        for voce in esito.eventi:
            self.assertFalse(voce["riga"]["leggibile"])
            self.assertFalse(voce["riga"]["applicato"])
            self.assertFalse(voce["scritto"])


class TestGiroCompleto(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    def _impostazioni(self):
        return SimpleNamespace(
            monitor_modalita="attivo",
            monitor_scenario="bilanciato",
            monitor_giri=("06:00", "18:00"),
            monitor_stati_estesi=False,
            tetto_fetch_giro=420,
            tetto_ricerche_giorno=0,
            tetto_crediti_giorno=0,
            tetto_classificazioni_giorno=0,
            tetto_usd_giorno=0.0,
            tetto_crediti_mese=0,
            tetto_usd_mese=0.0,
            backfill_tetto_crediti=0,
            backfill_tetto_usd=0.0,
        )

    def _lock(self):
        finto = MagicMock()
        finto.acquisisci.return_value = blocco.Blocco("monitor", "test", blocco.ACQUISITO)
        finto.esito_saltato.side_effect = blocco.esito_saltato
        return finto

    async def test_slug_restituito_per_indexnow(self):
        scritture = []
        dati = monitoraggio.FonteDati(righe=[_bando_in_archivio()])
        esito = await monitoraggio.run(
            attivo=True,
            impostazioni=self._impostazioni(),
            fonte_dati=dati,
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            rigenerazione=_rigeneratore(scritture),
            tabella_domini=TABELLA_DOMINI,
            lock=self._lock(),
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["eventi"], 2)
        self.assertEqual(esito["respinti"], 0)
        self.assertEqual(esito["slug_modificati"], [SLUG])
        # La prosa e' stata davvero riscritta: non si notifica Google una
        # pagina il cui contenuto e' rimasto com'era.
        self.assertTrue(scritture)
        finale = scritture[-1][1]["contenuto"]
        self.assertIn("1 dicembre 2026", finale)
        # Il differimento arriva in coppia: la seconda rigenerazione parte dal
        # testo gia' riscritto dalla prima, non da quello in archivio, cosi'
        # l'ultima scrittura non cancella la precedente.
        self.assertNotIn("entro il 6 ottobre 2026", finale)
        # La data del decreto resta la sua: e' la fonte, non il termine.
        self.assertIn("DD 12 del 6 ottobre 2026", finale)

    async def test_senza_rigenerazione_lo_slug_non_va_a_indexnow(self):
        # Le colonne cambiano, la prosa no: notificare Google una pagina che
        # continua a dire «6 ottobre 2026» e' peggio che non notificarla.
        dati = monitoraggio.FonteDati(righe=[_bando_in_archivio()])
        esito = await monitoraggio.run(
            attivo=True,
            impostazioni=self._impostazioni(),
            fonte_dati=dati,
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            tabella_domini=TABELLA_DOMINI,
            lock=self._lock(),
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )
        self.assertEqual(esito["eventi"], 2)
        self.assertEqual(esito["slug_modificati"], [])

    async def test_ombra_non_notifica_indexnow(self):
        # Con `MONITOR_MODALITA=ombra` gli eventi si raccolgono ma il contenuto
        # pubblico non cambia: nessun URL va a IndexNow.
        impostazioni = self._impostazioni()
        impostazioni.monitor_modalita = "ombra"
        dati = monitoraggio.FonteDati(righe=[_bando_in_archivio()])
        esito = await monitoraggio.run(
            impostazioni=impostazioni,
            fonte_dati=dati,
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            tabella_domini=TABELLA_DOMINI,
            lock=self._lock(),
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(esito["eventi"], 2)
        self.assertEqual(esito["slug_modificati"], [])

    async def test_dry_run_non_notifica_indexnow(self):
        dati = monitoraggio.FonteDati(righe=[_bando_in_archivio()])
        esito = await monitoraggio.run(
            dry_run=True,
            impostazioni=self._impostazioni(),
            fonte_dati=dati,
            scarica=_scarica,
            classifica=_classifica,
            seconda_opinione=_seconda_opinione,
            pagine_collegate=_pagine_collegate,
            tabella_domini=TABELLA_DOMINI,
            lock=self._lock(),
            adesso=ADESSO,
            casuale=lambda: 0.5,
        )
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(esito["slug_modificati"], [])


class TestRigenerazioneDellaProsa(unittest.IsolatedAsyncioTestCase):
    async def test_sostituzione_solo_nelle_frasi_di_scadenza(self):
        scritture = []

        async def scrivi(bando_id, payload):
            scritture.append((bando_id, payload))
            return True

        evento = {
            "tipo": "rettifica", "campo": "data_scadenza",
            # `data_evento` e' QUANDO l'ente lo ha dichiarato (oggi), non il
            # nuovo valore della scadenza: quello sta in `valore_dopo`.
            "valore_dopo": {"data_scadenza": "2026-12-01"},
            "data_evento": OGGI.isoformat(), "url_prova": URL_BANDO,
        }
        esito = await rigenera.rigenera(
            _bando_in_archivio(), evento,
            vecchia=date(2026, 10, 6), nuova=date(2026, 12, 1), ruolo="scadenza",
            attivo=True, scrivi=scrivi,
        )

        self.assertEqual(esito.via, "sostituzione")
        self.assertEqual(esito.sostituzioni, 1)
        self.assertTrue(esito.scritto)
        contenuto = scritture[0][1]["contenuto"]
        self.assertIn("entro il 1 dicembre 2026", contenuto)
        # La data del decreto resta quella che era: e' la fonte, non il termine.
        self.assertIn("DD 12 del 6 ottobre 2026", contenuto)
        # Importo e nome dell'ente intatti.
        self.assertIn("4.500.000 euro", contenuto)
        self.assertIn("Regione Lazio", contenuto)

    async def test_voce_del_box(self):
        evento = {
            "tipo": "rettifica", "campo": "data_scadenza",
            # `data_evento` e' QUANDO l'ente lo ha dichiarato (oggi), non il
            # nuovo valore della scadenza: quello sta in `valore_dopo`.
            "valore_dopo": {"data_scadenza": "2026-12-01"},
            "data_evento": OGGI.isoformat(), "url_prova": URL_BANDO,
        }
        esito = await rigenera.rigenera(_bando_in_archivio(), evento)
        self.assertEqual(len(esito.voci), 1)
        self.assertIn("1 dicembre 2026", esito.voci[0].testo)
        self.assertEqual(esito.voci[0].url, URL_BANDO)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
