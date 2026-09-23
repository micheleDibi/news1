# -*- coding: utf-8 -*-
"""Adapter Obiettivo Europa (fix 8.a.17 a): schema reale dell'API.

Sul codice vecchio questi test fallivano: `tipo_link` non scattava mai su
`on_arrival` (confrontava `status` con 'forthcoming'), `raw_data` non
portava `id`/`modified`/`updates_active` ed emetteva `deadline_days_left`
piu' chiavi che l'API non ha mai avuto.
"""
import unittest

from tests.supporto import carica_modulo

oe = carica_modulo("scrapers.adapters.obiettivo_europa")


def record_reale(**extra):
    """Record simile a quelli restituiti da /api/call/ (22/09/2026)."""
    base = {
        "id": 18426,
        "title": "Avviso pubblico per il sostegno alle imprese culturali",
        "url": "/bandi/avviso-imprese-culturali-2026/",
        "status": 2,
        "published": "2026-09-15",
        "modified": "2026-09-20T10:32:11+02:00",
        "deadline_label": "Scade il 30/11/2026",
        "deadline_days_left": 69,
        "on_arrival": False,
        "updates_active": True,
        "is_recent": True,
        "is_copiloted": False,
        "like": 3,
        "visited": 120,
        "budget": "2.000.000 €",
        "pnrr": False,
        "section_program": "regionali",
        "sectors": [{"id": 4, "title": "Cultura"}],
        "beneficiaries": [{"id": 1, "title": "PMI"}, {"id": 2, "title": "Grandi imprese"}],
        "types": [{"id": 7, "title": "Contributo a fondo perduto"}],
        "regions": [{"id": 12, "title": "Marche"}],
        "programs": [{"id": 3, "title": "PR FESR Marche 2021-2027"}],
        "evaluation_procedures": [{"id": 1, "title": "Valutativa a graduatoria"}],
        "ateco_codes": ["90.01", "90.02"],
        "municipality_sizes": [],
    }
    base.update(extra)
    return base


CHIAVI_MAI_EMESSE = (
    "identifier", "opening_date", "deadline", "programme_title", "programme",
    "action_type_title", "type_of_action", "topics", "deadline_days_left",
)


class TestTipoLink(unittest.TestCase):
    def test_on_arrival_true_e_preavviso(self):
        item = oe.to_bando_item(record_reale(on_arrival=True, status=1), fonte_id=449)
        self.assertEqual(item.tipo_link, "Preavviso")

    def test_on_arrival_false_e_opportunita(self):
        item = oe.to_bando_item(record_reale(on_arrival=False, status=1), fonte_id=449)
        self.assertEqual(item.tipo_link, "Opportunità")

    def test_status_intero_non_decide_il_tipo(self):
        # status=1 o 2 non e' un flag aperto/chiuso: conta solo on_arrival
        for status in (1, 2):
            item = oe.to_bando_item(record_reale(on_arrival=False, status=status), fonte_id=449)
            self.assertEqual(item.tipo_link, "Opportunità", status)


class TestRawData(unittest.TestCase):
    def setUp(self):
        self.item = oe.to_bando_item(record_reale(), fonte_id=449)
        self.raw = self.item.raw_data

    def test_id_come_stringa(self):
        self.assertIn("id", self.raw)
        self.assertIsInstance(self.raw["id"], str)
        self.assertEqual(self.raw["id"], "18426")

    def test_status_come_stringa(self):
        self.assertEqual(self.raw["status"], "2")

    def test_chiavi_nuove_presenti(self):
        self.assertEqual(self.raw["modified"], "2026-09-20T10:32:11+02:00")
        self.assertIs(self.raw["updates_active"], True)

    def test_chiavi_conservate(self):
        self.assertEqual(self.raw["source"], "obiettivo_europa")
        self.assertEqual(self.raw["published"], "2026-09-15")
        self.assertEqual(self.raw["deadline_label"], "Scade il 30/11/2026")
        self.assertEqual(self.raw["budget"], "2.000.000 €")
        self.assertIs(self.raw["pnrr"], False)
        self.assertIs(self.raw["on_arrival"], False)
        self.assertEqual(self.raw["sectors"], ["Cultura"])
        self.assertEqual(self.raw["beneficiaries"], ["PMI", "Grandi imprese"])
        self.assertEqual(self.raw["types"], ["Contributo a fondo perduto"])
        self.assertEqual(self.raw["regions"], ["Marche"])
        self.assertEqual(self.raw["programs"], ["PR FESR Marche 2021-2027"])
        self.assertEqual(self.raw["evaluation_procedures"], ["Valutativa a graduatoria"])
        self.assertEqual(self.raw["ateco_codes"], ["90.01", "90.02"])

    def test_chiavi_mai_emesse_assenti(self):
        for chiave in CHIAVI_MAI_EMESSE:
            self.assertNotIn(chiave, self.raw, chiave)

    def test_deadline_days_left_non_riscrive_raw_data(self):
        # Due giri a distanza di un giorno: raw_data identico
        oggi = oe.to_bando_item(record_reale(deadline_days_left=69), fonte_id=449)
        domani = oe.to_bando_item(record_reale(deadline_days_left=68), fonte_id=449)
        self.assertEqual(oggi.raw_data, domani.raw_data)

    def test_id_assente_non_emette_la_chiave(self):
        rec = record_reale()
        del rec["id"]
        item = oe.to_bando_item(rec, fonte_id=449)
        self.assertNotIn("id", item.raw_data)


class TestLinkETitolo(unittest.TestCase):
    def test_url_relativo_risolto_sulla_base(self):
        item = oe.to_bando_item(record_reale(), fonte_id=449)
        self.assertEqual(
            item.link_bando,
            "https://www.obiettivoeuropa.com/bandi/avviso-imprese-culturali-2026/",
        )
        self.assertEqual(item.fonte_id, 449)
        self.assertIsNone(item.descrizione_raw)  # l'API non emette description

    def test_senza_titolo_o_url_skip(self):
        self.assertIsNone(oe.to_bando_item(record_reale(title=""), fonte_id=449))
        self.assertIsNone(oe.to_bando_item(record_reale(url=None), fonte_id=449))

    def test_docstring_descrive_lo_schema_reale(self):
        doc = oe.__doc__ or ""
        for chiave in ("\"id\"", "\"modified\"", "\"on_arrival\"", "\"updates_active\""):
            self.assertIn(chiave, doc)
        self.assertNotIn("\"is_forthcoming\": bool", doc)
        self.assertNotIn("open|closed|forthcoming", doc)


if __name__ == "__main__":
    unittest.main()
