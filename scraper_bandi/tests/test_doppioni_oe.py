# -*- coding: utf-8 -*-
"""Doppioni ObiettivoEuropa prima della SEO (contratto di ottobre, §6).

I casi guida sono i quattro doppioni OE pubblicati dal giro delle 12 del 29/09
e fusi a mano il 30/09 (F3-F6 di `correzioni-2026-09-29.sql`). I dati sono
quelli del DB, letti in GET il 30/09, nello stato che il bando OE aveva
all'ingresso della SEO: `ente_erogatore` e `importo_totale_eur` ancora NULL.

Si verificano i due criteri, la controparte sempre non OE, l'annullamento a
mano, e che nel giro della SEO un doppione esca prima di Opus con un rifiuto e
una riga di journal, senza fermare lo step se qualcosa va storto.

Nessuna rete, nessun modello, nessun DB.
"""
import asyncio
import os
import types
import unittest
from unittest import mock

from tests.supporto import carica_modulo

gemelli = carica_modulo("gemelli")
runner = carica_modulo("bando_seo_runner")
db = carica_modulo("db")

URL_F5 = ("https://bandi.regione.piemonte.it/contributi-finanziamenti/"
          "contributi-iniziative-istituzionali-manifestazioni-eventi-2026")

#: I master pubblicati (fonti 237 e 250, non OE).
PUBBLICATI = [
    {"id": 1240069, "fonte_id": 250, "pubblicato": True, "bando_master_id": None,
     "ente_erogatore": "Regione Piemonte", "importo_totale_eur": 1000000,
     "data_scadenza": "2026-10-22", "fonte_ufficiale_url": URL_F5},
    {"id": 1261831, "fonte_id": 250, "pubblicato": True, "bando_master_id": None,
     "ente_erogatore": "Regione Piemonte - Direzione Welfare", "importo_totale_eur": 60000,
     "data_scadenza": "2026-10-30",
     "fonte_ufficiale_url": "https://bandi.regione.piemonte.it/contributi-finanziamenti/"
                            "possesso-responsabile-animali-compagnia-finanziamenti-ai-comuni"},
    {"id": 1261867, "fonte_id": 250, "pubblicato": True, "bando_master_id": None,
     "ente_erogatore": "Regione Piemonte", "importo_totale_eur": 200000,
     "data_scadenza": "2026-10-31",
     "fonte_ufficiale_url": "https://bandi.regione.piemonte.it/contributi-finanziamenti/"
                            "avviso-pubblico-finanziamento-societa-mutuo-soccorso-attivita-almeno-60-anni"},
    {"id": 1262080, "fonte_id": 237, "pubblicato": True, "bando_master_id": None,
     "ente_erogatore": "Regione Lazio", "importo_totale_eur": 500000,
     "data_scadenza": "2026-10-29", "fonte_ufficiale_url": None},
]


def candidato(bando_id, titolo, budget, scadenza, url=None, **campi):
    """Un bando OE all'ingresso della SEO: ente e importo ancora NULL."""
    riga = {
        "id": bando_id, "fonte_id": 449, "stato_processing": "enriched",
        "titolo_raw": titolo, "ente_erogatore": None, "importo_totale_eur": None,
        "raw_data": {"source": "obiettivo_europa", "budget": budget},
        "data_scadenza": scadenza, "fonte_ufficiale_url": url, "rejection_reason": None,
        "link_bando": f"https://www.obiettivoeuropa.com/bandi/{bando_id}",
    }
    riga.update(campi)
    return riga


F3 = candidato(1262369, "Lazio - Polizia Locale Plus: parte corrente", 500000, "2026-10-29")
F4 = candidato(1262406, "Piemonte - Progetti per interventi di ristrutturazione e manutenzione "
                        "straordinaria degli immobili delle Società di Mutuo Soccorso e "
                        "Cooperative ex S.O.M.S.", 200000, "2026-10-31")
F5 = candidato(1262410, "Piemonte - Contributi per iniziative istituzionali, manifestazioni ed "
                        "eventi", 1000000, "2026-10-22", url=URL_F5)
F6 = candidato(1262413, "Piemonte - Finanziamenti ai Comuni per campagne educative, formative, "
                        "informative sul possesso responsabile di cani", 60000, "2026-10-30")


def indice(righe=PUBBLICATI):
    return gemelli.IndiceDoppioniOE.da_pubblicati(righe)


class TestCasiDel29(unittest.TestCase):
    def test_f3_f6_sono_tutti_presi(self):
        attesi = {
            1262369: (1262080, "ente-importo-scadenza"),
            1262406: (1261867, "ente-importo-scadenza"),
            1262410: (1240069, "url"),                   # anche la chiave: vince l'URL
            1262413: (1261831, "ente-importo-scadenza"),
        }
        for riga in (F3, F4, F5, F6):
            with self.subTest(bando=riga["id"]):
                self.assertEqual(gemelli.doppione_oe(riga, indice()), attesi[riga["id"]])

    def test_motivo_del_rifiuto(self):
        self.assertEqual(gemelli.motivo_doppione(1262080, "ente-importo-scadenza"),
                         "doppione probabile di 1262080: ente-importo-scadenza")
        self.assertEqual(gemelli.motivo_doppione(1240069, "url"),
                         "doppione probabile di 1240069: url")


class TestCriteri(unittest.TestCase):
    def test_controparte_oe_ignorata(self):
        # Il caso della formazione in Toscana (759891-759895): lotti diversi,
        # stessa pagina elenco e stessi importi. OE contro OE non vale.
        pagina = "https://www.regione.toscana.it/formazione-ecosistemi"
        pubblicati = [{"id": 759891, "fonte_id": 449, "pubblicato": True, "bando_master_id": None,
                       "ente_erogatore": "Regione Toscana", "importo_totale_eur": 133000,
                       "data_scadenza": "2026-10-12", "fonte_ufficiale_url": pagina}]
        riga = candidato(759895, "Toscana - Formazione Marmo", 133000, "2026-10-12", url=pagina)
        self.assertIsNone(gemelli.doppione_oe(riga, indice(pubblicati)))

    def test_fusi_e_non_pubblicati_non_sono_controparti(self):
        fuso = dict(PUBBLICATI[3], bando_master_id=1)
        spento = dict(PUBBLICATI[3], pubblicato=False)
        for controparte in (fuso, spento):
            with self.subTest(controparte=controparte):
                self.assertIsNone(gemelli.doppione_oe(F3, indice([controparte])))

    def test_criterio_2_vuole_tutti_e_tre(self):
        for riga in (
            dict(F3, raw_data={}),                          # niente budget
            dict(F3, data_scadenza=None),                   # niente scadenza
            dict(F3, titolo_raw="Polizia Locale Plus"),     # niente prefisso d'ente
            dict(F3, raw_data={"budget": 500001}),          # importo diverso
            dict(F3, data_scadenza="2026-10-30"),           # scadenza diversa
        ):
            with self.subTest(riga=riga):
                self.assertIsNone(gemelli.doppione_oe(riga, indice()))

    def test_le_colonne_vincono_sui_campi_grezzi(self):
        riga = dict(F3, ente_erogatore="Regione Lazio", importo_totale_eur=500000,
                    titolo_raw="Senza prefisso", raw_data={})
        self.assertEqual(gemelli.doppione_oe(riga, indice()), (1262080, "ente-importo-scadenza"))

    def test_a_parita_vince_l_id_piu_basso(self):
        doppio = dict(PUBBLICATI[3], id=999)
        self.assertEqual(gemelli.doppione_oe(F3, indice(PUBBLICATI + [doppio]))[0], 999)


class TestBudgetStrani(unittest.TestCase):
    """Revisione avversaria S3: un budget infinito dall'API OE fermava lo step."""

    def test_budget_infinito_o_enorme_non_solleva(self):
        import json
        infinito = json.loads('{"budget": 1e400}')["budget"]        # float('inf')
        for budget in (infinito, float("-inf"), float("nan"), "Infinity", "1e400", 10 ** 400):
            with self.subTest(budget=budget):
                riga = dict(F3, raw_data={"budget": budget})
                self.assertIsNone(gemelli.importo_del_candidato(riga))
                self.assertIsNone(gemelli.doppione_oe(riga, indice()))

    def test_budget_normali(self):
        self.assertEqual(gemelli.importo_del_candidato(dict(F3, raw_data={"budget": "500000"})),
                         500000)
        self.assertEqual(gemelli.importo_del_candidato(dict(F3, raw_data={"budget": 500000.7})),
                         500000)
        self.assertIsNone(gemelli.importo_del_candidato(dict(F3, raw_data={"budget": 0})))

    def test_un_errore_su_un_bando_non_ferma_gli_altri(self):
        def doppione(bando, indice_):
            if bando["id"] == F4["id"]:
                raise OverflowError("int too large")
            return gemelli.doppione_oe(bando, indice_)

        with mock.patch.object(runner, "doppione_oe", side_effect=doppione), \
             mock.patch.object(runner, "logger", mock.MagicMock()):
            restanti, contatori = asyncio.run(runner.escludi_doppioni_oe(
                [F3, F4], leggi_pubblicati=lambda: PUBBLICATI,
                rifiuta=mock.MagicMock(return_value=True)))
        self.assertEqual([b["id"] for b in restanti], [F4["id"]])  # va alla SEO come prima
        self.assertEqual(contatori["doppioni_oe"], 1)                # F3 escluso lo stesso
        self.assertEqual(contatori["doppioni_oe_errori"], 1)


class TestEnteNormalizzato(unittest.TestCase):
    def test_forme_dello_stesso_ente(self):
        casi = {
            "Regione Piemonte - Direzione Welfare": "piemonte",
            "Piemonte": "piemonte",
            "Regione Lazio": "lazio",
            "CCIAA Pistoia-Prato": "pistoia prato",
            "Camera di Commercio di Pistoia-Prato": "pistoia prato",
            "Camera di commercio industria artigianato e agricoltura di Cosenza": "cosenza",
            "Regione Autonoma Valle d'Aosta": "valle d aosta",
            "Provincia autonoma di Trento (APSS)": "trento",
            "Comune di Città di Castello": "citta di castello",
            "GAL Valle d’Aosta": "valle d aosta",
            # Revisione del 30/09 (dopo il terzo ciclo): falsi negativi.
            "Camera di Commercio Industria Artigianato Agricoltura di Basilicata": "basilicata",
            "C.C.I.A.A. di Potenza": "potenza",
            "Regione Autonoma della Sardegna": "sardegna",
            # Le stesse forme con le preposizioni articolate.
            "Camera di Commercio della Maremma e del Tirreno": "maremma e del tirreno",
            "Regione del Veneto": "veneto",
            "C.C.I.A.A. Potenza": "potenza",
            "Camera di commercio Pistoia": "pistoia",
        }
        for testo, atteso in casi.items():
            with self.subTest(testo=testo):
                self.assertEqual(gemelli.ente_normalizzato(testo), atteso)

    def test_vuoti(self):
        self.assertEqual(gemelli.ente_normalizzato(None), "")
        self.assertEqual(gemelli.ente_normalizzato("Regione"), "")
        self.assertIsNone(gemelli.chiave_doppione("Regione", 100, "2026-10-01"))

    def test_ente_del_candidato(self):
        self.assertEqual(gemelli.ente_del_candidato(F6), "Piemonte")
        self.assertEqual(gemelli.ente_del_candidato({"titolo_raw": "CCIAA Pistoia-Prato - Bando"}),
                         "CCIAA Pistoia-Prato")
        self.assertEqual(gemelli.ente_del_candidato({"titolo_raw": "Bando Pistoia-Prato"}), "")


class TestCandidati(unittest.TestCase):
    def test_solo_oe_enriched_non_annullati(self):
        self.assertTrue(gemelli.candidato_oe(F3))
        self.assertFalse(gemelli.candidato_oe(dict(F3, fonte_id=250)))
        self.assertFalse(gemelli.candidato_oe(dict(F3, stato_processing="completed")))
        self.assertFalse(gemelli.candidato_oe(dict(F3, pubblicato=True)))
        self.assertFalse(gemelli.candidato_oe(
            dict(F3, rejection_reason="doppione escluso a mano")))

    def test_l_update_di_annullamento_e_documentato(self):
        documento = gemelli.candidato_oe.__doc__ or ""
        self.assertIn("rejection_reason = 'doppione escluso a mano'", documento)
        self.assertIn("set stato_processing = 'enriched'", documento)


class TestGiroSeo(unittest.TestCase):
    def _escludi(self, bandi, **opzioni):
        parametri = dict(leggi_pubblicati=lambda: PUBBLICATI,
                         rifiuta=mock.MagicMock(return_value=True))
        parametri.update(opzioni)
        with mock.patch.object(runner, "logger", mock.MagicMock()) as registro:
            restanti, contatori = asyncio.run(runner.escludi_doppioni_oe(bandi, **parametri))
        return restanti, contatori, parametri, registro

    def test_il_doppione_esce_dal_giro_con_rifiuto_e_journal(self):
        altro = {"id": 5, "fonte_id": 250, "stato_processing": "enriched"}
        restanti, contatori, p, registro = self._escludi([F3, altro])
        self.assertEqual([b["id"] for b in restanti], [5])
        self.assertEqual(contatori["doppioni_oe"], 1)
        p["rifiuta"].assert_called_once_with(
            1262369, "doppione probabile di 1262080: ente-importo-scadenza")
        riga = registro.warning.call_args
        self.assertIn("doppione OE", riga.args[0])
        self.assertEqual(riga.args[1:3], (1262369, 1262080))

    def test_dry_run_non_scrive_ma_esclude(self):
        restanti, contatori, p, _r = self._escludi([F4], dry_run=True)
        self.assertEqual(restanti, [])
        self.assertEqual(contatori["doppioni_oe"], 1)
        p["rifiuta"].assert_not_called()

    def test_senza_candidati_oe_nessuna_lettura(self):
        leggi = mock.MagicMock(side_effect=AssertionError("non deve leggere"))
        altro = {"id": 5, "fonte_id": 250, "stato_processing": "enriched"}
        restanti, contatori, _p, _r = self._escludi([altro], leggi_pubblicati=leggi)
        self.assertEqual(restanti, [altro])
        self.assertEqual(contatori["doppioni_oe"], 0)

    def test_pubblicati_illeggibili_la_seo_va_avanti(self):
        leggi = mock.MagicMock(side_effect=RuntimeError("PostgREST giu'"))
        restanti, contatori, p, _r = self._escludi([F3], leggi_pubblicati=leggi)
        self.assertEqual(restanti, [F3])
        self.assertTrue(contatori["doppioni_oe_controllo_saltato"])
        p["rifiuta"].assert_not_called()

    def test_rifiuto_non_scritto_resta_fuori_dal_giro(self):
        rifiuta = mock.MagicMock(side_effect=RuntimeError("5xx"))
        restanti, contatori, _p, _r = self._escludi([F6], rifiuta=rifiuta)
        self.assertEqual(restanti, [])
        self.assertEqual(contatori["doppioni_oe_non_scritti"], 1)

    def test_annullato_a_mano_va_alla_seo(self):
        annullato = dict(F3, rejection_reason="doppione escluso a mano")
        restanti, contatori, p, _r = self._escludi([annullato])
        self.assertEqual(restanti, [annullato])
        p["rifiuta"].assert_not_called()

    def test_run_non_chiama_opus_per_il_doppione(self):
        arricchisci = mock.AsyncMock(return_value=None)
        altro = {"id": 5, "fonte_id": 250, "stato_processing": "enriched", "link_bando": ""}
        rifiuta = mock.MagicMock(return_value=True)
        with mock.patch.object(runner, "select_bandi_to_complete", return_value=[F5, altro]), \
             mock.patch.object(runner, "select_pubblicati_per_doppioni_oe",
                               return_value=PUBBLICATI), \
             mock.patch.object(runner, "rifiuta_doppione", rifiuta), \
             mock.patch.object(runner, "load_catalogo", return_value={}), \
             mock.patch.object(runner, "build_bando_input_context",
                               side_effect=lambda b, c: {"id": b["id"]}), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci), \
             mock.patch.object(runner, "logger", mock.MagicMock()), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEDUP_CANONICAL", None)
            contatori = asyncio.run(runner.run())
        self.assertEqual([c.args[0]["id"] for c in arricchisci.await_args_list], [5])
        rifiuta.assert_called_once_with(1262410, "doppione probabile di 1240069: url")
        self.assertEqual(contatori["selected"], 2)
        self.assertEqual(contatori["doppioni_oe"], 1)

    def test_run_solo_doppioni(self):
        with mock.patch.object(runner, "select_bandi_to_complete", return_value=[F3]), \
             mock.patch.object(runner, "select_pubblicati_per_doppioni_oe",
                               return_value=PUBBLICATI), \
             mock.patch.object(runner, "rifiuta_doppione", mock.MagicMock(return_value=True)), \
             mock.patch.object(runner, "enrich_seo",
                               new=mock.AsyncMock(side_effect=AssertionError("niente Opus"))), \
             mock.patch.object(runner, "logger", mock.MagicMock()):
            contatori = asyncio.run(runner.run())
        self.assertEqual((contatori["selected"], contatori["doppioni_oe"]), (1, 1))


class TestDb(unittest.TestCase):
    def test_rifiuto_solo_da_enriched(self):
        client = mock.MagicMock()
        catena = client.table.return_value.update.return_value.eq.return_value.eq.return_value
        catena.execute.return_value = types.SimpleNamespace(data=[{"id": 1262369}])
        self.assertTrue(db.rifiuta_doppione(1262369, "doppione probabile di 1262080: url",
                                            client=client))
        client.table.return_value.update.assert_called_once_with(
            {"stato_processing": "rejected",
             "rejection_reason": "doppione probabile di 1262080: url"})
        client.table.return_value.update.return_value.eq.assert_called_once_with("id", 1262369)
        client.table.return_value.update.return_value.eq.return_value.eq.assert_called_once_with(
            "stato_processing", "enriched")

    def test_bando_non_piu_enriched_non_risulta_rifiutato(self):
        client = mock.MagicMock()
        catena = client.table.return_value.update.return_value.eq.return_value.eq.return_value
        catena.execute.return_value = types.SimpleNamespace(data=[])
        self.assertFalse(db.rifiuta_doppione(1, "m", client=client))

    def test_la_select_della_seo_legge_rejection_reason(self):
        self.assertIn("rejection_reason", db.COLONNE_SEO_BASE)

    def test_pubblicati_scorsi_senza_fusi(self):
        strumento = mock.MagicMock()
        strumento.tabella_esiste.return_value = True
        strumento.colonne.return_value = set(db.COLONNE_DOPPIONI_OE)
        strumento.ha.return_value = True
        client = mock.MagicMock()
        query = client.table.return_value.select.return_value
        query.eq.return_value = query
        query.is_.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.range.return_value = query
        query.execute.return_value = types.SimpleNamespace(data=PUBBLICATI)
        righe = db.select_pubblicati_per_doppioni_oe(client=client, strumento=strumento)
        self.assertEqual([r["id"] for r in righe], [r["id"] for r in PUBBLICATI])
        query.is_.assert_any_call("bando_master_id", "null")
        query.eq.assert_any_call("pubblicato", True)


if __name__ == "__main__":
    unittest.main()
