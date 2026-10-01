# -*- coding: utf-8 -*-
"""Finestre di presentazione con le ore (contratto `bandi-giro-2` §6.2).

`estrai_finestra` riconosce il costrutto «dal X al Y» di sempre e la forma di
LazioEuropa «a partire dalle ore … del X … entro le ore … del Y»;
`ora_nella_citazione` legge l'ora di una data senza toccare `_COSTRUTTO_RE`.
Funzioni pure: nessuna rete.
"""
import unittest
from datetime import date, time

from tests.supporto import carica_modulo

dv = carica_modulo("date_validation")


class TestEstraiFinestra(unittest.TestCase):
    def test_lazioeuropa_con_le_ore(self):
        finestre = dv.estrai_finestra(
            "Le domande possono essere presentate a partire dalle ore 12:00 del 15 settembre 2026 "
            "ed entro le ore 18:00 del 30 ottobre 2026.")
        self.assertEqual(len(finestre), 1)
        f = finestre[0]
        self.assertEqual((f.inizio, f.ora_inizio, f.fine, f.ora_fine),
                         (date(2026, 9, 15), time(12, 0), date(2026, 10, 30), time(18, 0)))
        self.assertTrue(f.per_presentare)
        self.assertFalse(f.presunta)
        self.assertIn(f.citazione, "a partire dalle ore 12:00 del 15 settembre 2026 ed entro le "
                                   "ore 18:00 del 30 ottobre 2026")

    def test_lazioeuropa_senza_ore(self):
        f = dv.estrai_finestra(
            "Domande a partire dal 1° ottobre 2026 e fino al 30 novembre 2026.")[0]
        self.assertEqual((f.inizio, f.ora_inizio, f.fine, f.ora_fine),
                         (date(2026, 10, 1), None, date(2026, 11, 30), None))

    def test_costrutto_con_le_ore(self):
        f = dv.estrai_finestra(
            "Le istanze vanno inviate dalle ore 10:00 del 1° ottobre 2026 alle ore 12:00 del "
            "30 ottobre 2026.")[0]
        self.assertEqual((f.inizio, f.ora_inizio, f.fine, f.ora_fine),
                         (date(2026, 10, 1), time(10, 0), date(2026, 10, 30), time(12, 0)))

    def test_costrutto_senza_ore_e_anno_eliso(self):
        f = dv.estrai_finestra("Domande dal 21 al 31 luglio 2025.")[0]            # 3042
        self.assertEqual((f.inizio, f.ora_inizio, f.fine, f.ora_fine),
                         (date(2025, 7, 21), None, date(2025, 7, 31), None))
        self.assertTrue(f.per_presentare)

    def test_la_fiera_non_e_una_finestra_di_presentazione(self):
        # 1257980: le date della manifestazione restano una finestra, ma non di domande.
        finestre = dv.estrai_finestra(
            "Selezionano 28 imprese interessate a partecipare a Roma Sposa 2026 – Salone "
            "Internazionale della Sposa, che si svolgerà dal 30 ottobre al 1° novembre 2026 presso "
            "il Centro Congressi La Nuvola. Domande entro le ore 11.00 del 2 ottobre 2026.")
        self.assertEqual(len(finestre), 1)
        self.assertEqual(finestre[0].fine, date(2026, 11, 1))
        self.assertFalse(finestre[0].per_presentare)

    def test_finestra_presunta(self):
        f = dv.estrai_finestra(
            "Apertura prevista dal 27 ottobre 2025 al 31 dicembre 2026, domande online.")[0]
        self.assertTrue(f.presunta)

    def test_piu_finestre_in_ordine(self):
        finestre = dv.estrai_finestra(
            "Prima finestra: domande dal 1 al 15 ottobre 2026. Seconda finestra: domande dal "
            "1 al 15 marzo 2027.")
        self.assertEqual([f.fine for f in finestre], [date(2026, 10, 15), date(2027, 3, 15)])

    def test_nessuna_finestra(self):
        self.assertEqual(dv.estrai_finestra("Domande entro il 30/10/2026."), [])
        self.assertEqual(dv.estrai_finestra(None), [])


class TestOraNellaCitazione(unittest.TestCase):
    def test_forme_prima_della_data(self):
        for citazione, data, atteso in (
            ("Candidature entro le 17.00 del 30 giugno 2026.", date(2026, 6, 30), time(17, 0)),
            ("inviate entro e non oltre le ore 12 del 20/10/2026 , pena", date(2026, 10, 20), time(12, 0)),
            ("entro le ore 11.00 del 2 ottobre 2026, pena", date(2026, 10, 2), time(11, 0)),
            ("Domande via PEC entro le 23:59 del 23 luglio 2026.", date(2026, 7, 23), time(23, 59)),
            ("entro le ore 18.00 del giorno 1° ottobre 2026", date(2026, 10, 1), time(18, 0)),
        ):
            with self.subTest(citazione=citazione):
                self.assertEqual(dv.ora_nella_citazione(citazione, data), atteso)

    def test_forme_dopo_la_data(self):
        self.assertEqual(dv.ora_nella_citazione("scadenza 30/10/2026, ore 18:00", date(2026, 10, 30)),
                         time(18, 0))
        self.assertEqual(dv.ora_nella_citazione("scade il 30/10/2026 alle ore 12", date(2026, 10, 30)),
                         time(12, 0))
        # fesr/formazionelavoro ER: «20 ottobre 2026 12:00 - Scadenza dei termini».
        self.assertEqual(dv.ora_nella_citazione("20 ottobre 2026 12:00 - Scadenza dei termini",
                                                date(2026, 10, 20)), time(12, 0))

    def test_mezzanotte(self):
        self.assertEqual(dv.ora_nella_citazione("entro le ore 24:00 del 30/10/2026", date(2026, 10, 30)),
                         time(23, 59))

    def test_00_00_vale_solo_scritto_per_esteso(self):
        # Revisione avversaria, ciclo 2: «00:00» e' l'orario vuoto dei CMS.
        for citazione in ("20 ottobre 2026 00:00 - Scadenza dei termini",
                          "scadenza 30/10/2026, 00:00",
                          "entro le 00:00 del 30/10/2026"):
            with self.subTest(citazione=citazione):
                data = date(2026, 10, 20) if "20 ottobre" in citazione else date(2026, 10, 30)
                self.assertIsNone(dv.ora_nella_citazione(citazione, data))
        for citazione in ("entro le ore 00:00 del 30/10/2026", "scadenza 30/10/2026, ore 00:00"):
            with self.subTest(citazione=citazione):
                self.assertEqual(dv.ora_nella_citazione(citazione, date(2026, 10, 30)), time(0, 0))
        finestra = dv.estrai_finestra("Domande dal 1/10/2026 al 30/10/2026 00:00, online.")[0]
        self.assertIsNone(finestra.ora_fine)
        finestra = dv.estrai_finestra("Domande dal 1/10/2026 al 30/10/2026 ore 00:00, online.")[0]
        self.assertEqual(finestra.ora_fine, time(0, 0))

    def test_stesso_giorno_apertura_e_scadenza(self):
        citazione = "domande dalle ore 9:00 alle ore 18:00 del 30/10/2026"
        self.assertEqual(dv.ora_nella_citazione(citazione, date(2026, 10, 30), "apertura"), time(9, 0))
        self.assertEqual(dv.ora_nella_citazione(citazione, date(2026, 10, 30), "scadenza"), time(18, 0))

    def test_l_ora_di_un_altra_data_non_passa(self):
        citazione = "dalle ore 9 del 1/10/2026 alle ore 12 del 30/10/2026"
        self.assertEqual(dv.ora_nella_citazione(citazione, date(2026, 10, 1), "apertura"), time(9, 0))
        self.assertEqual(dv.ora_nella_citazione(citazione, date(2026, 10, 30)), time(12, 0))

    def test_senza_ora_o_senza_data(self):
        self.assertIsNone(dv.ora_nella_citazione("entro il 30/10/2026", date(2026, 10, 30)))
        self.assertIsNone(dv.ora_nella_citazione("entro le ore 12 del 30/10/2026", date(2026, 11, 30)))
        self.assertIsNone(dv.ora_nella_citazione("entro le ore 25:00 del 30/10/2026", date(2026, 10, 30)))
        self.assertIsNone(dv.ora_nella_citazione(None, date(2026, 10, 30)))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
