# -*- coding: utf-8 -*-
"""`MONITOR_GIRI` e le ore dello scheduler (§16.2 M13).

Il confronto che conta e' `giro in settings.monitor_giri`, dove `giro` puo'
essere solo una delle ore con cui `backend/app/bandi_sender.py` schedula la
pipeline. Una voce fuori da quell'insieme non fa partire il monitor e basta:
qui si verifica che venga scartata, segnalata e riportata da
`monitor_giri_validi`, che alimenta l'allarme di `telemetria.salute`.

Nessuna rete, nessun DB: si legge solo l'ambiente.
"""
import os
import unittest
from unittest.mock import patch

from tests.supporto import carica_modulo

settings = carica_modulo("settings")


def _giri(valore: str | None):
    ambiente = dict(os.environ)
    ambiente.pop("MONITOR_GIRI", None)
    if valore is not None:
        ambiente["MONITOR_GIRI"] = valore
    with patch.dict(os.environ, ambiente, clear=True):
        return settings._giri_env("MONITOR_GIRI", settings._GIRI_DEFAULT)


class TestGiriScheduler(unittest.TestCase):
    def test_le_quattro_ore_del_sender(self):
        self.assertEqual(settings.GIRI_SCHEDULER, ("00:00", "06:00", "12:00", "18:00"))

    def test_il_default_e_un_sottoinsieme_dello_scheduler(self):
        for giro in settings._GIRI_DEFAULT:
            self.assertIn(giro, settings.GIRI_SCHEDULER)


class TestGiriEnv(unittest.TestCase):
    def test_variabile_assente_usa_il_default(self):
        self.assertEqual(_giri(None), (settings._GIRI_DEFAULT, True))

    def test_variabile_vuota_usa_il_default(self):
        self.assertEqual(_giri("   "), (settings._GIRI_DEFAULT, True))

    def test_ore_valide(self):
        self.assertEqual(_giri("00:00, 12:00"), (("00:00", "12:00"), True))

    def test_normalizzazione_a_due_cifre(self):
        self.assertEqual(_giri("6:00")[0], ("06:00",))

    def test_duplicati_collassano(self):
        self.assertEqual(_giri("06:00,06:00")[0], ("06:00",))

    def test_ora_fuori_dallo_scheduler_scartata(self):
        # 07:00 e' un orario valido ma nessun giro parte alle 7: il monitor
        # non partirebbe mai e non lo direbbe nessuno.
        giri, validi = _giri("07:00,18:00")
        self.assertEqual(giri, ("18:00",))
        self.assertFalse(validi)

    def test_solo_ore_fuori_scheduler_ricade_sul_default(self):
        giri, validi = _giri("07:00,09:30")
        self.assertEqual(giri, settings._GIRI_DEFAULT)
        self.assertFalse(validi)

    def test_voce_malformata_scartata(self):
        giri, validi = _giri("18:00,ventidue")
        self.assertEqual(giri, ("18:00",))
        self.assertFalse(validi)

    def test_ora_impossibile_scartata(self):
        self.assertFalse(_giri("25:00")[1])


class TestSettingsCompleto(unittest.TestCase):
    def test_get_settings_riporta_la_validita(self):
        ambiente = dict(os.environ)
        ambiente["MONITOR_GIRI"] = "07:00,18:00"
        with patch.dict(os.environ, ambiente, clear=True):
            settings.get_settings.cache_clear()
            try:
                impostazioni = settings.get_settings()
            finally:
                settings.get_settings.cache_clear()
        self.assertEqual(impostazioni.monitor_giri, ("18:00",))
        self.assertFalse(impostazioni.monitor_giri_validi)

    def test_default_sano(self):
        ambiente = dict(os.environ)
        ambiente.pop("MONITOR_GIRI", None)
        with patch.dict(os.environ, ambiente, clear=True):
            settings.get_settings.cache_clear()
            try:
                impostazioni = settings.get_settings()
            finally:
                settings.get_settings.cache_clear()
        self.assertEqual(impostazioni.monitor_giri, ("06:00", "18:00"))
        self.assertTrue(impostazioni.monitor_giri_validi)


if __name__ == "__main__":
    unittest.main()



def _bool_env(nome: str, valore: str | None) -> bool:
    """Legge il flag booleano con l'ambiente ripulito dalla variabile."""
    ambiente = dict(os.environ)
    ambiente.pop(nome, None)
    if valore is not None:
        ambiente[nome] = valore
    with patch.dict(os.environ, ambiente, clear=True):
        return settings.bool_env(nome, False)


class TestStatiEstesi(unittest.TestCase):
    """`MONITOR_STATI_ESTESI` governa l'uso di `sospeso`/`revocato` sulla colonna.

    Il monitor la legge con `getattr(impostazioni, "monitor_stati_estesi", False)`:
    senza il campo nelle impostazioni la variabile sarebbe inerte e, applicata la
    migrazione 06, non ci sarebbe modo di attivare i due stati senza toccare il
    codice.
    """

    def test_il_campo_esiste_nelle_impostazioni(self):
        self.assertIn("monitor_stati_estesi", settings.Settings.__dataclass_fields__)

    def test_default_falso(self):
        self.assertFalse(_bool_env("MONITOR_STATI_ESTESI", None))

    def test_si_accende(self):
        for valore in ("true", "1", "si", "yes", "on"):
            with self.subTest(valore=valore):
                self.assertTrue(_bool_env("MONITOR_STATI_ESTESI", valore))

    def test_valore_non_riconosciuto_resta_falso(self):
        self.assertFalse(_bool_env("MONITOR_STATI_ESTESI", "forse"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
