# -*- coding: utf-8 -*-
"""Il «chiuso» del modello con la scadenza da oggi in poi non vale (contratto del giro 3, §21.1).

Nel primo giro in produzione dell'01/10/2026 tre bandi aperti (2773, 1262487,
1262812: scadenze 26/07/2027, 01/11/2026, 06/10/2026, pagine ufficiali
«Aperto») erano `processed` e `chiuso`: il preprocess aveva accettato lo stato
proposto dal modello, perche' `reconcile_stato_bando` forza «chiuso» con la
scadenza passata ma non il contrario. Un `processed` chiuso non va ne' a enrich
ne' alla SEO: resta nascosto per sempre.

Ora, solo dove lo stato viene dal modello (preprocess e suo ripiego, righe mai
pubblicate), un «chiuso» con la scadenza che la riga avra' da oggi in poi vale
«aperto», poi la riconciliazione di sempre. Il «chiuso» con prova del lettore
per ente vince come prima. `reconcile_stato_bando` non cambia. «Oggi» e' fisso
nei test: mai l'orologio. Per tutto il modulo l'orologio vero e' fermo su una
data lontana da OGGI (e dalla data reale): chi lo legge al posto dell'«oggi»
passato sbaglia e il test cade.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_chiuso_modello
"""
import unittest
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, patch

from tests.supporto import carica_modulo

pre = carica_modulo("preprocessor")
runner = carica_modulo("bando_preprocess_runner")
bando_resolver = carica_modulo("bando_resolver")
scarico = carica_modulo("scarico")
etichette = carica_modulo("etichette_stato")
enricher = carica_modulo("enricher")
dv = carica_modulo("date_validation")
stato_bando = carica_modulo("stato_bando")

#: Il giorno del primo giro in produzione: l'«oggi» che i test passano.
OGGI = date(2026, 10, 1)
#: Le scadenze vere dei tre bandi chiusi per sbaglio.
SCADENZE_VERE = ("2027-07-26", "2026-11-01", "2026-10-06")

#: L'orologio vero durante i test del modulo. `stato_bando.adesso_roma` e' la
#: fonte di ogni `oggi_roma()` non sostituito (preprocess, ripiego, lettore,
#: default di `reconcile_stato_bando`). La data e' dopo tutte le scadenze dei
#: casi: una riconciliazione senza `today=giorno`, o un `oggi` passato e poi
#: ignorato, vede le scadenze passate e chiude i bandi che dovevano restare aperti.
OROLOGIO_FINTO = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)
_ADESSO_VERO = stato_bando.adesso_roma


def _adesso_finto(adesso=None):
    """`adesso_roma` con l'orologio fermo su OROLOGIO_FINTO (un istante passato vale come prima)."""
    return _ADESSO_VERO(OROLOGIO_FINTO if adesso is None else adesso)


def setUpModule():
    orologio = patch.object(stato_bando, "adesso_roma", new=_adesso_finto)
    orologio.start()
    unittest.addModuleCleanup(orologio.stop)


def _scadenza(iso: str) -> tuple[dict, str]:
    """Una scadenza del modello che passa il triplo controllo, e la sua pagina."""
    d = date.fromisoformat(iso)
    quote = f"Scadenza: {d:%d/%m/%Y}"
    return {"date": iso, "source": "official_page", "quote": quote}, f"Bando per le imprese. {quote}."


def _modello(stato="chiuso", **campi):
    """La risposta grezza del modello (prima di `_validate_analysis`)."""
    base = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": stato,
            "data_pubblicazione": None, "data_apertura": None, "data_scadenza": None}
    base.update(campi)
    return base


def _valida(**campi):
    """Un'analisi gia' validata (l'ingresso di `completa_dopo_il_modello`)."""
    base = {"is_valid_bando": True, "confidence_score": 0.9, "rejection_reason": None,
            "stato_bando": "chiuso", "data_pubblicazione": None, "data_apertura": None,
            "data_scadenza": None, "ora_apertura": None, "ora_scadenza": None,
            "_origine_scadenza": None, "_date_presunte_respinte": 0,
            "_chiuso_modello_scartato": False}
    base.update(campi)
    return base


def _lettura(stato="aperto", termine=None, puo_chiudere=False):
    return etichette.Lettura("lazioeuropa", stato, stato.capitalize(), puo_chiudere=puo_chiudere,
                             solo_segnale=False, termine_finale=termine)


#: Una finestra di presentazione con la fine nel futuro rispetto a OGGI.
FINESTRA_FUTURA = ("L'invio delle Domande deve avvenire a partire dalle ore 12:00 del 30 settembre 2026 "
                   "ed entro le ore 17:00 del 29 ottobre 2026.")


class LaRegola(unittest.TestCase):
    """La funzione pura, scritta una volta e usata nei due punti del preprocess e nel ripiego."""

    def test_scadenza_futura_o_di_oggi_scarta_il_chiuso(self):
        for scadenza in (date(2026, 10, 2), date(2027, 7, 26), OGGI):
            with self.subTest(scadenza=scadenza):
                self.assertEqual(pre.scarta_chiuso_del_modello("chiuso", scadenza, OGGI), ("aperto", True))

    def test_scadenza_passata_o_assente_non_cambia_niente(self):
        for scadenza in (date(2026, 9, 30), None):
            with self.subTest(scadenza=scadenza):
                self.assertEqual(pre.scarta_chiuso_del_modello("chiuso", scadenza, OGGI), ("chiuso", False))

    def test_gli_altri_stati_non_cambiano(self):
        for stato in ("aperto", "unknown", "in apertura prossimamente", None):
            for scadenza in (date(2026, 10, 6), date(2026, 9, 30), None):
                with self.subTest(stato=stato, scadenza=scadenza):
                    self.assertEqual(pre.scarta_chiuso_del_modello(stato, scadenza, OGGI), (stato, False))

    def test_reconcile_stato_bando_non_cambia(self):
        # La regola vive nel preprocess: la riconciliazione usata anche da
        # enrich e rielaborazione tiene il 'chiuso' con la scadenza futura.
        self.assertEqual(dv.reconcile_stato_bando("chiuso", None, date(2026, 10, 6), today=OGGI), "chiuso")

    def test_l_orologio_vero_e_fermo_lontano_da_oggi(self):
        # Controllo della trappola: gli `oggi_roma` di preprocess, ripiego e
        # riconciliazione leggono l'orologio finto (non OGGI, non la data
        # reale). Se un giorno `oggi_roma` non passasse piu' da `adesso_roma`,
        # questo test lo direbbe prima che la trappola si spenga.
        for modulo in (pre, bando_resolver, dv):
            with self.subTest(modulo=modulo.__name__):
                self.assertEqual(modulo.oggi_roma(), OROLOGIO_FINTO.date())
        self.assertNotEqual(OROLOGIO_FINTO.date(), OGGI)
        self.assertEqual(dv.reconcile_stato_bando("aperto", None, date(2026, 11, 1)), "chiuso")
        self.assertEqual(dv.reconcile_stato_bando("aperto", None, date(2026, 11, 1), today=OGGI), "aperto")


class NormalizzazioneDellAnalisi(unittest.TestCase):
    """Primo punto: la scadenza del modello, validata dal triplo controllo."""

    def test_le_tre_scadenze_vere_danno_aperto(self):
        for iso in SCADENZE_VERE:
            with self.subTest(scadenza=iso):
                candidata, testo = _scadenza(iso)
                esito = pre._validate_analysis(_modello(data_scadenza=candidata), testo, 1, oggi=OGGI)
                self.assertEqual(esito["data_scadenza"], iso)
                self.assertEqual(esito["stato_bando"], "aperto")
                self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_oggi_e_ancora_aperto(self):
        candidata, testo = _scadenza(OGGI.isoformat())
        esito = pre._validate_analysis(_modello(data_scadenza=candidata), testo, 1, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_passata_resta_chiuso(self):
        candidata, testo = _scadenza("2026-09-30")
        esito = pre._validate_analysis(_modello(data_scadenza=candidata), testo, 1, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_scadenza_assente_resta_chiuso(self):
        esito = pre._validate_analysis(_modello(), "Bando per le imprese, senza date.", 1, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_scadenza_non_validata_non_conta(self):
        # La scadenza che la riga avra' e' quella che passa il gate: una data
        # che la pagina non cita non riapre niente.
        candidata, _ = _scadenza("2026-10-06")
        esito = pre._validate_analysis(_modello(data_scadenza=candidata), "Testo senza la data.", 1, oggi=OGGI)
        self.assertIsNone(esito["data_scadenza"])
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_apertura_futura_con_scadenza_futura_e_in_apertura(self):
        testo = ("Le domande si presentano a partire dalle ore 09:30 del 15/10/2026 "
                 "ed entro le ore 12:00 del 30/11/2026.")
        esito = pre._validate_analysis(_modello(
            data_apertura={"date": "2026-10-15", "source": "official_page",
                           "quote": "a partire dalle ore 09:30 del 15/10/2026"},
            data_scadenza={"date": "2026-11-30", "source": "official_page",
                           "quote": "entro le ore 12:00 del 30/11/2026"},
        ), testo, 1, oggi=OGGI)
        self.assertEqual((esito["data_apertura"], esito["data_scadenza"]), ("2026-10-15", "2026-11-30"))
        self.assertEqual(esito["stato_bando"], "in apertura prossimamente")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_aperto_e_unknown_invariati(self):
        candidata, testo = _scadenza("2026-10-06")
        for stato, atteso in (("aperto", "aperto"), ("unknown", None)):
            with self.subTest(stato=stato):
                esito = pre._validate_analysis(_modello(stato, data_scadenza=candidata), testo, 1, oggi=OGGI)
                self.assertEqual(esito["stato_bando"], atteso)
                self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_bando_non_valido_nessuno_scarto(self):
        candidata, testo = _scadenza("2026-10-06")
        esito = pre._validate_analysis(_modello(is_valid_bando=False, data_scadenza=candidata), testo, 1,
                                       oggi=OGGI)
        self.assertFalse(esito["_chiuso_modello_scartato"])


class CompletamentoDalTesto(unittest.TestCase):
    """Secondo punto: la scadenza trovata dopo il modello (lettore, finestra, etichetta OE)."""

    BANDO = {"id": 1, "raw_data": {}}

    def test_scadenza_dalla_finestra_da_aperto(self):
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, FINESTRA_FUTURA, None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["_origine_scadenza"]), ("2026-10-29", "finestra"))
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_dal_lettore_da_aperto(self):
        termine = etichette.TermineFinale(date(2026, 10, 6), time(17, 0), "entro le ore 17:00 del 6 ottobre")
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, "", _lettura(termine=termine), oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["_origine_scadenza"]), ("2026-10-06", "lettore"))
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_dall_etichetta_oe_da_aperto(self):
        bando = {"id": 9, "raw_data": {"status": "1", "deadline_label": "Scade il 30/11/2026"}}
        testo = "Programma X. Scadenza: 30/11/2026. Beneficiari: imprese."
        esito = pre.completa_dopo_il_modello(_valida(), bando, testo, None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["_origine_scadenza"]), ("2026-11-30", "etichetta_oe"))
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_trovata_passata_resta_chiuso(self):
        testo = "Le domande si presentano dal 01/09/2026 al 30/09/2026."
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, testo, None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), ("2026-09-30", "chiuso"))
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_nessuna_scadenza_trovata_resta_chiuso(self):
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, "Nessuna data qui.", None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), (None, "chiuso"))
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_chiuso_del_lettore_vince_anche_con_la_scadenza_futura(self):
        termine = etichette.TermineFinale(date(2026, 10, 6), None, "x")
        lettura = _lettura("chiuso", termine=termine, puo_chiudere=True)
        # il modello diceva 'chiuso' senza scadenza: la scadenza la trova il lettore
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, "", lettura, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), ("2026-10-06", "chiuso"))
        self.assertTrue(esito["_chiuso_da_lettore"])
        self.assertFalse(esito["_chiuso_modello_scartato"])
        # il modello diceva 'chiuso' con la scadenza futura, gia' scartato al primo punto
        gia_scartato = _valida(stato_bando="aperto", data_scadenza="2026-10-06",
                               _origine_scadenza="modello", _chiuso_modello_scartato=True)
        esito = pre.completa_dopo_il_modello(gia_scartato, self.BANDO, "",
                                             _lettura("chiuso", puo_chiudere=True), oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_chiuso_del_lettore_senza_puo_chiudere_non_e_una_prova(self):
        termine = etichette.TermineFinale(date(2026, 10, 6), None, "x")
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, "",
                                             _lettura("chiuso", termine=termine, puo_chiudere=False), oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_lo_scarto_del_primo_punto_resta_contato(self):
        gia_scartato = _valida(stato_bando="aperto", data_scadenza="2026-10-06",
                               _origine_scadenza="modello", _chiuso_modello_scartato=True)
        esito = pre.completa_dopo_il_modello(gia_scartato, self.BANDO, "", None, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "aperto")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_apertura_futura_e_in_apertura(self):
        esito = pre.completa_dopo_il_modello(_valida(data_apertura="2026-10-15"), self.BANDO,
                                             FINESTRA_FUTURA, None, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "in apertura prossimamente")
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_aperto_e_unknown_invariati(self):
        for stato in ("aperto", None):
            with self.subTest(stato=stato):
                esito = pre.completa_dopo_il_modello(_valida(stato_bando=stato), self.BANDO,
                                                     FINESTRA_FUTURA, None, oggi=OGGI)
                self.assertEqual(esito["stato_bando"], stato)
                self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_i_due_punti_in_fila(self):
        # Il modello dice 'chiuso' e non da' la scadenza: il primo punto lascia
        # 'chiuso', il secondo trova la finestra e scarta.
        primo = pre._validate_analysis(_modello(), FINESTRA_FUTURA, 1, oggi=OGGI)
        self.assertEqual((primo["stato_bando"], primo["_chiuso_modello_scartato"]), ("chiuso", False))
        secondo = pre.completa_dopo_il_modello(primo, self.BANDO, FINESTRA_FUTURA, None, oggi=OGGI)
        self.assertEqual((secondo["stato_bando"], secondo["_chiuso_modello_scartato"]), ("aperto", True))
        # Il modello dice 'chiuso' con la scadenza futura: scarta il primo punto,
        # il secondo non cambia niente e lo scarto resta contato.
        candidata, testo = _scadenza("2026-11-01")
        primo = pre._validate_analysis(_modello(data_scadenza=candidata), testo, 1, oggi=OGGI)
        secondo = pre.completa_dopo_il_modello(primo, self.BANDO, testo, None, oggi=OGGI)
        self.assertEqual((secondo["stato_bando"], secondo["_chiuso_modello_scartato"]), ("aperto", True))


class AnalyzeBandoIntero(unittest.IsolatedAsyncioTestCase):
    """Il preprocess intero usa lo stesso «oggi» (Roma) nei due punti."""

    async def test_chiuso_del_modello_con_scadenza_futura(self):
        link = "https://www.regione.esempio.it/bandi/contributi"
        testo = ("# Contributi alle imprese\n\nAvviso pubblico per contributi alle imprese del territorio.\n\n"
                 "## Termini\n\nScadenza: 06/10/2026.\n\n" + "Dettagli del bando per le imprese. " * 10 + "\n")

        class Finto:
            async def scarica(self, url, **kwargs):
                return scarico.Risposta(url=url, stato=200, html="", testo=testo, url_finale=url)

        async def modello(client, **kwargs):
            return object()

        risposta_modello = _modello(data_scadenza={"date": "2026-10-06", "source": "official_page",
                                                   "quote": "Scadenza: 06/10/2026"})
        with patch.object(enricher, "_firecrawl_scrape_markdown", AsyncMock(return_value=testo)), \
                patch.object(scarico, "scarico_corrente", lambda: Finto()), \
                patch.object(pre, "_get_anthropic_client", lambda: object()), \
                patch.object(pre, "_call_anthropic_with_retry", modello), \
                patch.object(pre, "_extract_tool_input", lambda r: dict(risposta_modello)), \
                patch.object(pre, "oggi_roma", lambda *a: OGGI):
            esito = await pre.analyze_bando({"id": 1262812, "titolo_raw": "Contributi", "link_bando": link,
                                             "raw_data": {}}, {})
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), ("2026-10-06", "aperto"))
        self.assertTrue(esito["_chiuso_modello_scartato"])
        # controprova: con «oggi» dopo la scadenza resta chiuso
        with patch.object(enricher, "_firecrawl_scrape_markdown", AsyncMock(return_value=testo)), \
                patch.object(scarico, "scarico_corrente", lambda: Finto()), \
                patch.object(pre, "_get_anthropic_client", lambda: object()), \
                patch.object(pre, "_call_anthropic_with_retry", modello), \
                patch.object(pre, "_extract_tool_input", lambda r: dict(risposta_modello)), \
                patch.object(pre, "oggi_roma", lambda *a: date(2026, 10, 7)):
            esito = await pre.analyze_bando({"id": 1262812, "titolo_raw": "Contributi", "link_bando": link,
                                             "raw_data": {}}, {})
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_chiuso_modello_scartato"])


class RipiegoDelResolver(unittest.TestCase):
    """Il ripiego del preprocess (`bando_resolver`): righe `scraped`, stato dal modello."""

    def test_stessa_regola(self):
        candidata, testo = _scadenza("2026-11-01")
        fonte = "Elenco dei bandi della Regione. " * 5 + testo
        esito = bando_resolver._validate_resolver_output(_modello(data_scadenza=candidata), fonte, 7, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), ("2026-11-01", "aperto"))
        self.assertTrue(esito["_chiuso_modello_scartato"])

    def test_scadenza_passata_o_assente_resta_chiuso(self):
        candidata, testo = _scadenza("2026-09-30")
        for analisi, fonte in ((_modello(data_scadenza=candidata), testo), (_modello(), "Nessuna data.")):
            with self.subTest(scadenza=analisi["data_scadenza"]):
                esito = bando_resolver._validate_resolver_output(analisi, fonte, 7, oggi=OGGI)
                self.assertEqual(esito["stato_bando"], "chiuso")
                self.assertFalse(esito["_chiuso_modello_scartato"])

    def test_usa_la_funzione_del_preprocess(self):
        self.assertIs(bando_resolver.scarta_chiuso_del_modello, pre.scarta_chiuso_del_modello)


class Contatore(unittest.IsolatedAsyncioTestCase):

    async def test_chiuso_modello_scartato_nei_contatori(self):
        analisi = {
            1: _valida(stato_bando="aperto", data_scadenza="2026-10-06", _chiuso_modello_scartato=True),
            2: _valida(stato_bando="in apertura prossimamente", data_apertura="2026-10-15",
                       data_scadenza="2026-11-30", _chiuso_modello_scartato=True),
            3: _valida(stato_bando="chiuso", data_scadenza="2026-09-30"),
            4: _valida(stato_bando="chiuso", _chiuso_da_lettore=True),
            # scartato e poi rifiutato: non e' un `processed`, non si conta
            5: _valida(is_valid_bando=False, _chiuso_modello_scartato=True),
            6: {"_needs_fallback": True, "is_valid_bando": False},
        }

        async def analizza(bando, fonte, **kwargs):
            return dict(analisi[bando["id"]])

        async def ripiego(bando, fonte):
            return _valida(stato_bando="aperto", data_scadenza="2026-10-06",
                           _fallback_used=True, _chiuso_modello_scartato=True)

        righe = [{"id": i, "fonte_id": 1} for i in analisi]
        with patch.object(runner, "select_bandi_scraped", lambda limit=None: righe), \
                patch.object(runner, "select_fonti_by_ids", lambda ids: {}), \
                patch.object(runner, "enrich_fonti_with_names", lambda f: f), \
                patch.object(runner, "analyze_bando", analizza), \
                patch.object(runner, "resolve_bando", ripiego):
            contatori = await runner.run(dry_run=True)
        self.assertEqual(contatori["chiuso_modello_scartato"], 3)
        self.assertEqual(contatori["chiusi_da_lettore"], 1)
        self.assertEqual(contatori["fallback_used"], 1)


if __name__ == "__main__":
    unittest.main()
