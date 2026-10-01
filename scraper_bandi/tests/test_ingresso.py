# -*- coding: utf-8 -*-
"""Il filtro d'ingresso (`ingresso.pubblicabile`, contratto del giro 2 §5.10).

Un «aperto» senza scadenza e senza prova sosta al massimo quattro giri prima
della pubblicazione, il tempo che la fase ingresso gli cerchi una scadenza; un
bando senza link ne' date resta fermo sempre. Tutto il resto si pubblica.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_ingresso
"""
import unittest
from datetime import datetime, timedelta, timezone

from tests.supporto import carica_modulo

ingresso = carica_modulo("ingresso")

ADESSO = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)          # 10:00 a Roma
APERTO = {"stato_bando": "aperto", "data_scadenza": None,
          "link_bando": "https://www.regione.lazio.it/bandi/1"}


def _storia(*voci):
    return {"lettura_stato": {"storia": list(voci)}}


class Sosta(unittest.TestCase):

    def test_aperto_senza_scadenza_ne_prova_sosta(self):
        self.assertEqual(ingresso.pubblicabile(APERTO, {}, ADESSO), (False, "sosta"))

    def test_la_sosta_dura_quattro_giri_da_trattenuto_dal(self):
        for ore, atteso in ((0, (False, "sosta")), (23, (False, "sosta")),
                            (24, (True, "rilasciato_a_tempo")), (40, (True, "rilasciato_a_tempo"))):
            with self.subTest(ore=ore):
                controllo = {"trattenuto_dal": (ADESSO - timedelta(hours=ore)).isoformat()}
                self.assertEqual(ingresso.pubblicabile(APERTO, controllo, ADESSO), atteso)

    def test_sosta_giri_dal_chiamante(self):
        controllo = {"trattenuto_dal": (ADESSO - timedelta(hours=7)).isoformat()}
        self.assertEqual(ingresso.pubblicabile(APERTO, controllo, ADESSO, sosta_giri=1),
                         (True, "rilasciato_a_tempo"))
        self.assertEqual(ingresso.pubblicabile(APERTO, controllo, ADESSO, sosta_giri=2),
                         (False, "sosta"))

    def test_zero_giri_spegne_la_sosta(self):
        self.assertEqual(ingresso.pubblicabile(APERTO, {}, ADESSO, sosta_giri=0), (True, None))

    def test_trattenuto_dal_con_frazioni_e_z(self):
        controllo = {"trattenuto_dal": "2026-10-01T07:59:59.87927Z"}
        self.assertEqual(ingresso.pubblicabile(APERTO, controllo, ADESSO),
                         (True, "rilasciato_a_tempo"))


class NienteSosta(unittest.TestCase):

    def test_con_scadenza_o_non_aperto(self):
        for riga in ({**APERTO, "data_scadenza": "2026-12-31"},
                     {**APERTO, "stato_bando": "in apertura prossimamente"},
                     {**APERTO, "stato_bando": "chiuso"}):
            with self.subTest(riga=riga):
                self.assertEqual(ingresso.pubblicabile(riga, {}, ADESSO), (True, None))

    def test_conferma_di_un_lettore_per_ente(self):
        controllo = _storia({"at": "2026-10-01T10:00:00+00:00", "estrattore": "lazioeuropa",
                             "url": "u", "etichetta": "Aperto", "stato": "aperto", "date": []})
        self.assertEqual(ingresso.pubblicabile(APERTO, controllo, ADESSO), (True, None))

    def test_generico_modello_e_chiusure_non_confermano(self):
        for voce in ({"estrattore": "generico", "stato": "aperto"},
                     {"estrattore": None, "stato": "aperto"},
                     {"estrattore": "lazioeuropa", "stato": "chiuso"},
                     {"estrattore": "lazioeuropa", "stato": "non_decisiva"}):
            with self.subTest(voce=voce):
                self.assertEqual(ingresso.pubblicabile(APERTO, _storia(voce), ADESSO), (False, "sosta"))

    def test_termine_indicato_da_oggi_in_poi(self):
        # oggi a Roma e' il 2 ottobre
        self.assertEqual(ingresso.pubblicabile(APERTO, {"termine_indicato": "2026-10-02"}, ADESSO),
                         (True, None))
        self.assertEqual(ingresso.pubblicabile(APERTO, {"termine_indicato": "2026-10-01"}, ADESSO),
                         (False, "sosta"))


class SenzaAppiglio(unittest.TestCase):

    NUDO = {"stato_bando": "aperto", "data_scadenza": None, "link_bando": None,
            "fonte_ufficiale_url": None, "data_pubblicazione": None, "data_apertura": None}

    def test_senza_link_e_senza_date_resta_fermo_sempre(self):
        vecchio = {"trattenuto_dal": (ADESSO - timedelta(days=30)).isoformat()}
        self.assertTrue(ingresso.senza_appiglio(self.NUDO, {}))
        self.assertEqual(ingresso.pubblicabile(self.NUDO, vecchio, ADESSO), (False, "senza_appiglio"))
        # vale anche fuori dagli aperti: e' un PDF di programma senza nessun appiglio
        chiuso = {**self.NUDO, "stato_bando": "chiuso"}
        self.assertEqual(ingresso.pubblicabile(chiuso, {}, ADESSO, sosta_giri=0),
                         (False, "senza_appiglio"))

    def test_un_solo_appiglio_basta(self):
        casi = (
            ({**self.NUDO, "link_bando": "https://ente.it/b"}, {}),
            ({**self.NUDO, "fonte_ufficiale_url": "https://ente.it/b"}, {}),
            ({**self.NUDO, "data_pubblicazione": "2026-09-01"}, {}),
            ({**self.NUDO, "data_apertura": "2026-09-01"}, {}),
            ({**self.NUDO, "data_scadenza": "2026-12-31"}, {}),
            (self.NUDO, {"termine_indicato": "2026-01-01"}),
            (self.NUDO, {"bando_link": True}),
            (self.NUDO, {"bando_link": 2}),
            (self.NUDO, {"bando_link": [{"id": 1}]}),
        )
        for riga, controllo in casi:
            with self.subTest(riga=riga, controllo=controllo):
                self.assertFalse(ingresso.senza_appiglio(riga, controllo))

    def test_bando_link_vuoto_non_e_un_appiglio(self):
        for valore in (False, 0, [], None, ""):
            with self.subTest(valore=valore):
                self.assertTrue(ingresso.senza_appiglio(self.NUDO, {"bando_link": valore}))


if __name__ == "__main__":
    unittest.main()
