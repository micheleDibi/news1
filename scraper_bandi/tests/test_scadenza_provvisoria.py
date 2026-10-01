# -*- coding: utf-8 -*-
"""`date_validation.scadenza_provvisoria` (contratto `bandi-giro-3` §7).

La scadenza che una riga appena entrata dichiara prima del preprocess: la usa
il resolver precoce solo come conferma (+15). Pura, senza modello ne' rete. I
valori sono quelli visti a DB l'01/10/2026 (chiavi di `raw_data` per fonte).

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_scadenza_provvisoria
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

dv = carica_modulo("date_validation")


def _scadenza(**raw):
    return dv.scadenza_provvisoria({"id": 1, "raw_data": raw})


class TestPerFonte(unittest.TestCase):
    def test_obiettivo_europa_deadline_label(self):
        self.assertEqual(_scadenza(deadline_label="12 ottobre 2026"), date(2026, 10, 12))
        self.assertEqual(_scadenza(deadline_label="Scade il 30/09/2026", deadline_days_left="3"),
                         date(2026, 9, 30))

    def test_incentivi_close_date(self):
        self.assertEqual(_scadenza(source="incentivi_gov_it", close_date="2026-12-31T23:59:59Z"),
                         date(2026, 12, 31))

    def test_italia_domani_data_chiusura(self):
        for valore in ("31/12/2026", "31 dicembre 2026"):
            with self.subTest(valore=valore):
                self.assertEqual(_scadenza(source="italia_domani", data_chiusura=valore),
                                 date(2026, 12, 31))

    def test_italia_domani_non_prende_un_apertura(self):
        self.assertIsNone(_scadenza(source="italia_domani",
                                    data_chiusura="apertura dal 1 dicembre 2026"))

    def test_calendari(self):
        self.assertEqual(_scadenza(DATA_CHIUSURA="2026-12-23 00:00:00"), date(2026, 12, 23))
        self.assertEqual(_scadenza(data_chiusura_invito="30 settembre 2023"), date(2023, 9, 30))
        # Con piu' date di chiusura vale la piu' tarda.
        self.assertEqual(_scadenza(scadenza="15/11/2026", termine_presentazione="20/11/2026"),
                         date(2026, 11, 20))

    def test_l_ordine_delle_fonti(self):
        # OE prima di tutto, poi Incentivi, poi Italia Domani, poi i calendari.
        self.assertEqual(_scadenza(deadline_label="12 ottobre 2026", close_date="2026-12-31",
                                   scadenza="01/01/2027"), date(2026, 10, 12))
        self.assertEqual(_scadenza(close_date="2026-12-31", scadenza="01/01/2027"),
                         date(2026, 12, 31))


class TestNienteDaLeggere(unittest.TestCase):
    def test_valori_veri_che_non_sono_date(self):
        casi = (
            {"data_chiusura": "feb-25"},
            {"DATA_CHIUSUR A": "da definire"},
            {"data_di_chiusura_del\nbando": "DA DEFINIRE"},
            {"scadenza": "None"},
            {"Data indicativa di chiusura (mese-anno)": "1° trimestre 2025"},
            {"deadline_days_left": "0"},
        )
        for raw in casi:
            with self.subTest(raw=raw):
                self.assertIsNone(_scadenza(**raw))

    def test_una_data_presunta_non_vale(self):
        self.assertIsNone(_scadenza(scadenza="presunta: 15/11/2026"))
        self.assertIsNone(_scadenza(deadline_label="prevista per il 15 novembre 2026"))

    def test_chiavi_che_non_sono_termini(self):
        self.assertIsNone(_scadenza(data_apertura="01/10/2026", pubblicazione="30/09/2026"))

    def test_riga_senza_raw_data(self):
        self.assertIsNone(dv.scadenza_provvisoria({"id": 1}))
        self.assertIsNone(dv.scadenza_provvisoria({"id": 1, "raw_data": "testo"}))
        self.assertIsNone(dv.scadenza_provvisoria(None))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
