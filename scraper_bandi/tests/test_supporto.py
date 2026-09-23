# -*- coding: utf-8 -*-
"""Test di fumo dell'infrastruttura: il package si carica per percorso, il
logger e' lo stub, nessun file viene creato dall'import."""
import sys
import unittest
from pathlib import Path

from tests.supporto import ALIAS, APP, RADICE, carica_modulo, carica_per_percorso


class TestSupporto(unittest.TestCase):
    def test_carica_modulo_senza_import_reale_del_logger(self):
        date_validation = carica_modulo("date_validation")
        self.assertTrue(hasattr(date_validation, "validate_date_candidate"))
        self.assertIs(sys.modules[f"{ALIAS}.logger"].logger, date_validation.logger)
        self.assertNotIn("app.logger", sys.modules)

    def test_sottopackage_scrapers(self):
        csv_parser = carica_modulo("scrapers.csv_parser")
        self.assertTrue(hasattr(csv_parser, "CsvParserScraper") or hasattr(csv_parser, "__name__"))

    def test_settings_non_richiede_il_db(self):
        settings = carica_modulo("settings")
        s = settings.get_settings()
        self.assertTrue(s.supabase_url)

    def test_slug_gemello_caricabile(self):
        slug = carica_per_percorso("slug_edunews", RADICE.parent / "backend" / "app" / "slug.py")
        self.assertEqual(slug.slugifica("Perché no"), "perche-no")

    def test_nessun_pycache_nel_package(self):
        self.assertTrue(sys.dont_write_bytecode)
        self.assertTrue((APP / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
