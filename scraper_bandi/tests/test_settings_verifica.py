# -*- coding: utf-8 -*-
"""Variabili del percorso A (contratto `bandi-giro-2` §12 e §19.11).

Un valore sconosciuto o fuori intervallo torna al default e finisce in
`verifica_stato_scartate`, che accende configurazione:verifica_stato in
`salute`: mai un'eccezione all'avvio del sender. In `.env.example` solo i nomi.
"""
import os
import re
import unittest
from unittest.mock import patch

from tests.supporto import RADICE, carica_modulo

settings = carica_modulo("settings")

NOMI = ("VERIFICA_STATO_MODALITA", "VERIFICA_STATO_TETTO_S", "VERIFICA_STATO_USA_MODELLO",
        "INGRESSO_SOSTA_GIRI", "INDICEPA_URL")


def _leggi(**ambiente):
    pulito = {k: v for k, v in os.environ.items() if k not in NOMI}
    pulito.update(ambiente)
    with patch.dict(os.environ, pulito, clear=True):
        settings.get_settings.cache_clear()
        try:
            return settings.get_settings()
        finally:
            settings.get_settings.cache_clear()


class TestDefault(unittest.TestCase):
    def test_senza_variabili(self):
        s = _leggi()
        self.assertEqual((s.verifica_stato_modalita, s.verifica_stato_tetto_s,
                          s.verifica_stato_usa_modello, s.ingresso_sosta_giri),
                         ("ombra", 1800, True, 4))
        self.assertEqual(s.indicepa_url, settings.INDICEPA_URL_PREDEFINITO)
        self.assertTrue(s.verifica_stato_config_valida)

    def test_vuote_valgono_default(self):
        s = _leggi(**{nome: "" for nome in NOMI})
        self.assertEqual(s.verifica_stato_modalita, "ombra")
        self.assertTrue(s.verifica_stato_usa_modello)
        self.assertTrue(s.verifica_stato_config_valida)

    def test_costruzione_a_mano_ha_i_default(self):
        s = settings.get_settings()
        import dataclasses
        minimo = {f.name: getattr(s, f.name) for f in dataclasses.fields(s)
                  if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        nuovo = settings.Settings(**minimo)
        self.assertEqual(nuovo.verifica_stato_modalita, "ombra")
        self.assertEqual(nuovo.indicepa_url, settings.INDICEPA_URL_PREDEFINITO)


class TestValoriValidi(unittest.TestCase):
    def test_attivo_e_interi(self):
        s = _leggi(VERIFICA_STATO_MODALITA="Attivo", VERIFICA_STATO_TETTO_S="60",
                   INGRESSO_SOSTA_GIRI="12", VERIFICA_STATO_USA_MODELLO="false",
                   INDICEPA_URL="https://esempio.invalid/enti.xlsx")
        self.assertEqual((s.verifica_stato_modalita, s.verifica_stato_tetto_s, s.ingresso_sosta_giri),
                         ("attivo", 60, 12))
        self.assertFalse(s.verifica_stato_usa_modello)
        self.assertEqual(s.indicepa_url, "https://esempio.invalid/enti.xlsx")
        self.assertTrue(s.verifica_stato_config_valida)


class TestValoriScartati(unittest.TestCase):
    def test_fuori_enum_o_intervallo(self):
        casi = {
            "VERIFICA_STATO_MODALITA": ("attiva", "verifica_stato_modalita", "ombra"),
            "VERIFICA_STATO_TETTO_S": ("3601", "verifica_stato_tetto_s", 1800),
            "INGRESSO_SOSTA_GIRI": ("-1", "ingresso_sosta_giri", 4),
            "INDICEPA_URL": ("http://esempio.invalid/enti.xlsx", "indicepa_url", settings.INDICEPA_URL_PREDEFINITO),
        }
        for nome, (valore, campo, atteso) in casi.items():
            with self.subTest(variabile=nome):
                s = _leggi(**{nome: valore})
                self.assertEqual(getattr(s, campo), atteso)
                self.assertEqual(s.verifica_stato_scartate, (nome,))
                self.assertFalse(s.verifica_stato_config_valida)


class TestEnvExample(unittest.TestCase):
    def test_solo_i_nomi(self):
        testo = (RADICE / ".env.example").read_text(encoding="utf-8")
        for nome in NOMI:
            with self.subTest(variabile=nome):
                riga = re.search(rf"^{nome}=(.*)$", testo, re.MULTILINE)
                self.assertIsNotNone(riga, nome)
                self.assertEqual(riga.group(1), "")
        self.assertIn("# PUBLIC_SUPABASE_BANDI_ANON_KEY=", testo)
        self.assertIn("facoltativa: serve a misurare la vista come anon (vista_ms)", testo.lower())


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
