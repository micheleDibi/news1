# -*- coding: utf-8 -*-
"""Termini a quattro fonti (contratto `bandi-giro-2` §19.5): pagina, calendario
ufficiale, etichetta OE, e la precedenza fra le fonti. Piu' `e_presunta` e il
suo uso in `validate_date_candidate` (G10).

Le righe di calendario sono quelle vere del DB al 30/09/2026 (VdA 280, JTF
296), lette in GET; le frasi di pagina vengono dalle pagine pubbliche di
1257980 (lazioeuropa.it) e 940320 (formazionelavoro.regione.emilia-romagna.it).
Funzioni pure: nessuna rete.
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

dv = carica_modulo("date_validation")

#: 1257980: la fiera e il termine vero nella stessa pagina.
PAGINA_1257980 = (
    "La Regione Lazio, con Lazio Innova, nell’ambito della Convenzione per la partecipazione "
    "congiunta a iniziative e manifestazioni fieristiche, selezionano 28 imprese del Lazio "
    "interessate a partecipare a Roma Sposa 2026 – Salone Internazionale della Sposa, che si "
    "svolgerà dal 30 ottobre al 1° novembre 2026 presso il Centro Congressi La Nuvola. "
    "MODALITÀ DI PRESENTAZIONE DELLA DOMANDA DI PARTECIPAZIONE Le aziende interessate a "
    "partecipare alla collettiva regionale dovranno effettuare i seguenti adempimenti, entro le "
    "ore 11.00 del 2 ottobre 2026, pena la non ammissibilità della domanda: compilare il Form di "
    "registrazione."
)
#: 940320: il termine d'invio e l'avvio delle attivita' un anno dopo.
PAGINA_940320 = (
    "Modalità e termini per la presentazione della candidatura Le operazioni devono essere "
    "compilate esclusivamente attraverso l’apposita procedura applicativa web e devono essere "
    "inviate alla Pubblica Amministrazione per via telematica entro e non oltre le ore 12 del "
    "20/10/2026 , pena la non ammissibilità. Tempi ed esiti delle istruttorie Gli esiti saranno "
    "approvati di norma entro 90 giorni dalla data di scadenza dell’Avviso. Termine per l’avvio "
    "delle attività Le operazioni approvate dovranno essere avviate entro e non oltre il 15 "
    "ottobre 2027 con il numero minimo previsto di 15 partecipanti."
)


class TestTermineNellaPagina(unittest.TestCase):
    def test_1257980_il_termine_e_non_la_fiera(self):
        self.assertEqual(dv.termine_nella_pagina(PAGINA_1257980), (date(2026, 10, 2), "pagina"))

    def test_940320_il_termine_e_non_l_avvio(self):
        self.assertEqual(dv.termine_nella_pagina(PAGINA_940320), (date(2026, 10, 20), "pagina"))

    def test_pagina_senza_termine(self):
        self.assertIsNone(dv.termine_nella_pagina("Contributi alle imprese del territorio."))
        self.assertIsNone(dv.termine_nella_pagina(None))


class TestCalendario(unittest.TestCase):
    VDA, JTF = 280, 296

    def _vda(self, colonna):
        return {"page": 1, "col_6": colonna, "row_index": 8, "source_url": "https://x.invalid/c.pdf"}

    def test_vda_frasi_di_chiusura(self):
        for bando_id, colonna, atteso in (
            (803614, "procedura a sportello in corso\nchiusura domande: 15 luglio 2029", date(2029, 7, 15)),
            (803615, "in corso fino a 31 dicembre 2026", date(2026, 12, 31)),
            (803623, "procedura a sportello in corso\nchiusura: 30 ottobre 2026\n"
                     "Previste edizioni annuali fino al 2029", date(2026, 10, 30)),
            (5581, "in corso\nprocedura a sportello aperta fino al 31\ndicembre 2025", date(2025, 12, 31)),
        ):
            with self.subTest(bando=bando_id):
                self.assertEqual(dv.termine_da_calendario(self._vda(colonna), self.VDA, True),
                                 (atteso, "calendario_ufficiale"))

    def test_vda_colonna_csv(self):
        # Le stesse righe lette dal CSV hanno la colonna «Unnamed: 6» (803633).
        riga = {"row_index": 10, "Unnamed: 5": "2.000.000,00",
                "Unnamed: 6": "procedura a sportello in corso\nchiusura domande: 15 luglio 2029"}
        self.assertEqual(dv.termine_da_calendario(riga, self.VDA, True),
                         (date(2029, 7, 15), "calendario_ufficiale"))

    def test_vda_periodi_senza_giorno_o_presunti(self):
        for colonna in (
            "apertura domande: primo trimestre\n2026\nchiusura domande: 2029",       # 5545
            "Procedura a sportello con emanazione a settembre 2026 e chiusura a marzo 2030",
            "febbraio-marzo 2026",
            "2^ finestra: 08/09/2026 - 08/10/2026\n3^ finestra: 23/12/2026 - 28/01/2027",
            "chiusura prevista: 30 ottobre 2026",
            "Data di apertura e chiusura",
        ):
            with self.subTest(colonna=colonna):
                self.assertIsNone(dv.termine_da_calendario(self._vda(colonna), self.VDA, True))

    def test_jtf_colonna_di_chiusura(self):
        riga = {"DATA_APERTUR A": "27/10/2025", "DATA_CHIUSUR A": "2026-12-31 00:00:00",
                "STATO_OPPOR TUNITA": "Pubblicato", "row_index": 17}          # 5697..5700
        self.assertEqual(dv.termine_da_calendario(riga, self.JTF, True),
                         (date(2026, 12, 31), "calendario_ufficiale"))
        riga["DATA_CHIUSUR A"] = "31/12/2026"
        self.assertEqual(dv.termine_da_calendario(riga, self.JTF, True)[0], date(2026, 12, 31))
        riga["DATA_CHIUSUR A"] = "da definire"                                # 5692
        self.assertIsNone(dv.termine_da_calendario(riga, self.JTF, True))

    def test_solo_calendari_ufficiali_su_host_verificante(self):
        riga = self._vda("in corso fino a 31 dicembre 2026")
        self.assertIsNone(dv.termine_da_calendario(riga, self.VDA, False))
        self.assertIsNone(dv.termine_da_calendario(riga, 449, True))
        self.assertIsNone(dv.termine_da_calendario(None, self.VDA, True))

    def test_fonte_id_come_stringa(self):
        riga = self._vda("in corso fino a 31 dicembre 2026")
        self.assertEqual(dv.termine_da_calendario(riga, "280", True),
                         (date(2026, 12, 31), "calendario_ufficiale"))
        for fonte_id in ("abc", None, "", "449"):
            with self.subTest(fonte_id=fonte_id):
                self.assertIsNone(dv.termine_da_calendario(riga, fonte_id, True))


class TestEtichettaOE(unittest.TestCase):
    def test_etichetta_con_data(self):
        for etichetta, atteso in (("30 ottobre 2026", date(2026, 10, 30)),     # 1046001
                                  ("20 gennaio 2027", date(2027, 1, 20))):     # 18228, status 2
            self.assertEqual(dv.termine_da_etichetta_oe({"deadline_label": etichetta, "status": "1"}),
                             (atteso, "aggregatore"))

    def test_etichette_senza_data(self):
        for raw in ({"deadline_label": "Fino ad esaurimento risorse"},
                    {"deadline_label": "Non disponibile"}, {"deadline_label": "Senza scadenza"},
                    {"deadline_label": None}, {}, None, "30 ottobre 2026"):
            with self.subTest(raw=raw):
                self.assertIsNone(dv.termine_da_etichetta_oe(raw))


class TestPrecedenza(unittest.TestCase):
    def test_ordine_delle_fonti(self):
        self.assertEqual(dv.FONTI_TERMINE, ("calendario_ufficiale", "pagina", "testo", "aggregatore"))
        cal, pag = (date(2026, 12, 31), "calendario_ufficiale"), (date(2026, 11, 30), "pagina")
        tes, agg = (date(2026, 10, 30), "testo"), (date(2027, 1, 20), "aggregatore")
        self.assertEqual(dv.termine_per_precedenza(agg, tes, pag, cal), cal)
        self.assertEqual(dv.termine_per_precedenza(agg, None, tes, pag), pag)
        self.assertEqual(dv.termine_per_precedenza(agg, tes), tes)
        self.assertEqual(dv.termine_per_precedenza(None, agg), agg)

    def test_nessun_candidato_o_fonte_sconosciuta(self):
        self.assertIsNone(dv.termine_per_precedenza())
        self.assertIsNone(dv.termine_per_precedenza(None, None))
        self.assertIsNone(dv.termine_per_precedenza((date(2026, 1, 1), "modello")))


class TestDatePresunte(unittest.TestCase):
    def test_e_presunta(self):
        for testo in ("data presunta di apertura", "Apertura prevista dal", "indicativamente entro",
                      "orientativamente a marzo", "data stimata", "primo trimestre 2026",
                      "secondo semestre", "PRESUNTA"):
            self.assertTrue(dv.e_presunta(testo), testo)
        for testo in ("entro il 30/10/2026", "salvo imprevisti", "", None):
            self.assertFalse(dv.e_presunta(testo), testo)

    def _candidata(self, quote, data="2026-10-30"):
        return {"date": data, "source": "official_page", "quote": quote}

    def test_validate_respinge_la_data_presunta(self):
        quote = "Data presunta di scadenza: 30/10/2026"
        self.assertIsNone(dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"))
        quote = "Apertura prevista dal 1° ottobre 2026 al 30 ottobre 2026"
        self.assertIsNone(dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"))

    def test_previsto_come_stabilito_da_la_data(self):
        # Revisione di #71: «previsto» dopo termine/scadenza/chiusura o in
        # «modalità/termini previsti» vuol dire «stabilito», non «presunto».
        for quote in ("Scadenza prevista dal bando: 30/10/2026",
                      "Termine ultimo previsto: 30 ottobre 2026",
                      "entro i termini previsti, ossia entro il 30/10/2026",
                      "con le modalità previste entro il 30/10/2026",
                      "Scadenza prevista per il 30/10/2026"):
            with self.subTest(quote=quote):
                self.assertFalse(dv.e_presunta(quote))
                self.assertEqual(
                    dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"),
                    date(2026, 10, 30))

    def test_previsioni_vere_restano_presunte(self):
        for testo in ("l'apertura è prevista per il 15 novembre",
                      "si prevede l'apertura nel mese di novembre",
                      "Apertura prevista dal 1° ottobre 2026",
                      "pubblicazione prevista nel mese di ottobre",
                      "prevista a partire da novembre",
                      "prevista entro il primo trimestre"):
            with self.subTest(testo=testo):
                self.assertTrue(dv.e_presunta(testo))

    def test_formule_certe_della_revisione_ciclo_2(self):
        # «previsto» con il termine come soggetto lontano piu' di 30 caratteri,
        # e una stima che non riguarda la data: le date sono certe.
        for quote in ("Il termine per la presentazione delle domande è previsto per il 30/10/2026",
                      "La scadenza per la presentazione delle domande è prevista per il 30/10/2026",
                      "Importo stimato: 100.000 euro. Scadenza: 30/10/2026"):
            with self.subTest(quote=quote):
                self.assertFalse(dv.e_presunta(quote))
                self.assertEqual(
                    dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"),
                    date(2026, 10, 30))

    def test_stime_e_periodi_legati_alla_data(self):
        for testo in ("Data stimata di apertura: 15/11/2026", "Scadenza stimata: 30/10/2026",
                      "apertura stimata per il 15 novembre", "II semestre 2025", "secondo trimestre del 2026",
                      # l'inciso: piu' vicina a «prevista» c'e' l'apertura, non la scadenza
                      "Il bando, con scadenza il 30/10, ha apertura prevista per il 15/09"):
            with self.subTest(testo=testo):
                self.assertTrue(dv.e_presunta(testo))
        for testo in ("costo stimato per il progetto: 30.000 euro, domande entro il 30/10/2026",
                      "rendicontazione trimestrale, domande entro il 30/10/2026",
                      # la frase prima non entra nell'inciso di «previsto»
                      "L'apertura è avvenuta il 1/09/2026. Il termine è previsto per il 30/10/2026"):
            with self.subTest(testo=testo):
                self.assertFalse(dv.e_presunta(testo))

    def test_il_soggetto_e_il_primo_nome_dell_inciso(self):
        # Revisione #120: i «termini» sono un complemento, il soggetto e' l'apertura.
        for testo in ("L'apertura dei termini per la presentazione delle domande è prevista per il 15/11/2026",
                      "L'apertura dei termini è prevista per il 15/11/2026",
                      "La riapertura dei termini è prevista per il 15/11/2026",
                      "La pubblicazione dell'avviso, con scadenza a 30 giorni, è prevista per il 15/11/2026"):
            with self.subTest(testo=testo):
                self.assertTrue(dv.e_presunta(testo))
                self.assertIsNone(dv.validate_date_candidate(
                    self._candidata(testo, "2026-11-15"), testo, 1, "apertura"))
        # Restano certi.
        for quote in ("Il termine per la presentazione delle domande è previsto per il 30/10/2026",
                      "La scadenza per la presentazione delle domande è prevista per il 30/10/2026",
                      "Importo stimato: 100.000 euro. Scadenza: 30/10/2026",
                      "Termine ultimo previsto: 30 ottobre 2026",
                      "Scadenza prevista dal bando: 30/10/2026",
                      "Scadenza prevista per il 30/10/2026"):
            with self.subTest(quote=quote):
                self.assertFalse(dv.e_presunta(quote))

    def test_contesto_di_g10_a_capo_e_data_precedente(self):
        # Revisione #120: l'a capo non chiude il contesto; la data precedente si'.
        quote = "Data presunta di apertura\n15/11/2026"
        self.assertIsNone(dv.validate_date_candidate(self._candidata(quote, "2026-11-15"), quote, 1, "apertura"))
        for quote in ("Data indicativa di apertura: 15/11/2026 Data di scadenza: 30/11/2026",
                      "Data presunta di apertura: 15/11/2026\nScadenza: 30/11/2026"):
            with self.subTest(quote=quote):
                self.assertEqual(
                    dv.validate_date_candidate(self._candidata(quote, "2026-11-30"), quote, 1, "scadenza"),
                    date(2026, 11, 30))
                self.assertIsNone(
                    dv.validate_date_candidate(self._candidata(quote, "2026-11-15"), quote, 1, "apertura"))

    def test_rinvio_al_bando_non_e_una_previsione(self):
        # Revisione #91: «come/secondo quanto previsto» e «previsto nel/dal
        # bando, avviso, decreto…» rinviano a un atto, non prevedono niente.
        for quote in ("Le domande saranno raccolte, secondo quanto previsto nel bando, entro il 30/10/2026",
                      "Le domande, come previsto, vanno inviate entro il 30/10/2026",
                      "Le domande vanno inviate, come previsto dall'avviso, entro il 30/10/2026",
                      "Le domande vanno inviate nei modi previsti dal regolamento entro il 30/10/2026",
                      "L'invio, previsto dalla disciplinare, si chiude il 30/10/2026"):
            with self.subTest(quote=quote):
                self.assertFalse(dv.e_presunta(quote))
                self.assertEqual(
                    dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"),
                    date(2026, 10, 30))
        # una previsione vera resta presunta
        for testo in ("l'apertura è prevista nel mese di novembre",
                      "pubblicazione prevista nel mese di ottobre"):
            with self.subTest(testo=testo):
                self.assertTrue(dv.e_presunta(testo))

    def test_validate_accetta_la_data_certa(self):
        quote = ("Le domande, secondo le modalità previste dall'avviso approvato dalla Giunta, "
                 "vanno presentate entro il 30/10/2026")
        self.assertEqual(dv.validate_date_candidate(self._candidata(quote), quote, 1, "scadenza"),
                         date(2026, 10, 30))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
