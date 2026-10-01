# -*- coding: utf-8 -*-
"""Variabili del giro 3 (contratto `bandi-giro-3` §3).

Interruttori di gemelli e IndicePA, tempi dei passi, `MONITOR_TIPI_ATTIVI=tutti`
e i $ per scenario. Un valore sconosciuto o fuori intervallo torna al default e
il suo NOME (mai il valore) finisce in `configurazione_scartate`, che `salute`
porta come `configurazione:<nome>`: mai un'eccezione all'avvio del sender.

Il `.env` vero non entra: `load_dotenv` e' sostituito, cosi' i default si
misurano sul codice e non sulla configurazione di questa macchina.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_settings_giro3
"""
import dataclasses
import os
import re
import unittest
from unittest.mock import MagicMock, patch

from tests.supporto import RADICE, carica_modulo

settings = carica_modulo("settings")
eventi = carica_modulo("eventi")

#: Le variabili toccate qui: tolte dall'ambiente prima di ogni lettura.
NOMI = ("GEMELLI_MODALITA", "DOMINI_MODALITA", "TEMPO_PRECOCE_S", "TEMPO_RICONTROLLI_S",
        "TEMPO_LINK_VERIFICA_S", "TEMPO_RIELABORAZIONE_S", "TEMPO_MONITOR_S",
        "MONITOR_TIPI_ATTIVI", "MONITOR_SCENARIO", "TETTO_USD_GIORNO", "TETTO_USD_MESE",
        "VERIFICA_STATO_TETTO_S", "VERIFICA_STATO_MODALITA", "MONITOR_GIRI",
        "TETTO_CLASSIFICAZIONI_GIORNO", "TETTO_FETCH_GIRO", "VERIFICA_STATO_TETTO_LETTURE",
        "VERIFICA_STATO_MAX_CHIUSURE", "VERIFICA_STATO_TETTO_INGRESSO", "GEMELLI_FUSIONI_PER_GIRO")

#: Variabile → (campo di `Settings`, default).
TEMPI = {
    "TEMPO_PRECOCE_S": ("tempo_precoce_s", 600),
    "TEMPO_RICONTROLLI_S": ("tempo_ricontrolli_s", 3600),
    "TEMPO_LINK_VERIFICA_S": ("tempo_link_verifica_s", 1200),
    "TEMPO_RIELABORAZIONE_S": ("tempo_rielaborazione_s", 3600),
    "TEMPO_MONITOR_S": ("tempo_monitor_s", 3600),
}


def _leggi(registro=None, **ambiente):
    pulito = {k: v for k, v in os.environ.items() if k not in NOMI}
    pulito.update(ambiente)
    with patch.dict(os.environ, pulito, clear=True), \
            patch.object(settings, "load_dotenv", lambda *a, **k: False), \
            patch.object(settings, "logger", registro or MagicMock()):
        settings.get_settings.cache_clear()
        try:
            return settings.get_settings()
        finally:
            settings.get_settings.cache_clear()


class TestDefault(unittest.TestCase):
    def test_senza_variabili(self):
        s = _leggi()
        self.assertEqual((s.gemelli_modalita, s.domini_modalita), ("ombra", "ombra"))
        for nome, (campo, default) in TEMPI.items():
            with self.subTest(variabile=nome):
                self.assertEqual(getattr(s, campo), default)
        self.assertEqual(s.configurazione_scartate, ())
        self.assertEqual(s.verifica_stato_tetto_s, 1800)
        self.assertEqual(s.monitor_giri, settings.GIRI_SCHEDULER)
        self.assertEqual(s.monitor_tipi_attivi, ())

    def test_vuote_valgono_default(self):
        s = _leggi(**{nome: "  " for nome in TEMPI}, GEMELLI_MODALITA="", DOMINI_MODALITA="")
        self.assertEqual(s.configurazione_scartate, ())
        self.assertEqual(s.tempo_monitor_s, 3600)
        self.assertEqual(s.gemelli_modalita, "ombra")

    def test_costruzione_a_mano_ha_i_default(self):
        s = _leggi()
        minimo = {f.name: getattr(s, f.name) for f in dataclasses.fields(s)
                  if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
        nuovo = settings.Settings(**minimo)
        self.assertEqual((nuovo.gemelli_modalita, nuovo.domini_modalita), ("ombra", "ombra"))
        self.assertEqual((nuovo.tempo_precoce_s, nuovo.tempo_ricontrolli_s,
                          nuovo.tempo_link_verifica_s, nuovo.tempo_rielaborazione_s,
                          nuovo.tempo_monitor_s), (600, 3600, 1200, 3600, 3600))
        self.assertEqual(nuovo.verifica_stato_tetto_s, 1800)
        self.assertEqual(nuovo.configurazione_scartate, ())


class TestValoriValidi(unittest.TestCase):
    def test_attivo_senza_distinzione_di_maiuscole(self):
        s = _leggi(GEMELLI_MODALITA=" Attivo ", DOMINI_MODALITA="ATTIVO")
        self.assertEqual((s.gemelli_modalita, s.domini_modalita), ("attivo", "attivo"))
        self.assertEqual(s.configurazione_scartate, ())

    def test_gli_interruttori_sono_indipendenti_dalla_verifica(self):
        # §3: VERIFICA_STATO_MODALITA governa solo verifica e sosta.
        s = _leggi(VERIFICA_STATO_MODALITA="attivo")
        self.assertEqual((s.gemelli_modalita, s.domini_modalita), ("ombra", "ombra"))
        s = _leggi(GEMELLI_MODALITA="attivo")
        self.assertEqual(s.verifica_stato_modalita, "ombra")

    def test_estremi_degli_intervalli(self):
        for valore in ("60", "7200"):
            s = _leggi(**{nome: valore for nome in TEMPI})
            for nome, (campo, _) in TEMPI.items():
                with self.subTest(variabile=nome, valore=valore):
                    self.assertEqual(getattr(s, campo), int(valore))
            self.assertEqual(s.configurazione_scartate, ())
        self.assertEqual(_leggi(VERIFICA_STATO_TETTO_S="3600").verifica_stato_tetto_s, 3600)


class TestValoriScartati(unittest.TestCase):
    def test_fuori_enum_o_intervallo(self):
        casi = {
            "GEMELLI_MODALITA": ("attiva", "gemelli_modalita", "ombra"),
            "DOMINI_MODALITA": ("si", "domini_modalita", "ombra"),
            "TEMPO_PRECOCE_S": ("59", "tempo_precoce_s", 600),
            "TEMPO_RICONTROLLI_S": ("7201", "tempo_ricontrolli_s", 3600),
            "TEMPO_LINK_VERIFICA_S": ("venti minuti", "tempo_link_verifica_s", 1200),
            "TEMPO_RIELABORAZIONE_S": ("-1", "tempo_rielaborazione_s", 3600),
            "TEMPO_MONITOR_S": ("3600.5", "tempo_monitor_s", 3600),
        }
        for nome, (valore, campo, atteso) in casi.items():
            with self.subTest(variabile=nome):
                s = _leggi(**{nome: valore})
                self.assertEqual(getattr(s, campo), atteso)
                self.assertEqual(s.configurazione_scartate, (nome,))
                # Il gruppo della verifica resta valido: sono due allarmi diversi.
                self.assertEqual(s.verifica_stato_scartate, ())

    def test_piu_scartate_nell_ordine(self):
        s = _leggi(DOMINI_MODALITA="x", GEMELLI_MODALITA="y", TEMPO_MONITOR_S="0",
                   TEMPO_PRECOCE_S="0")
        self.assertEqual(s.configurazione_scartate,
                         ("GEMELLI_MODALITA", "DOMINI_MODALITA", "TEMPO_PRECOCE_S",
                          "TEMPO_MONITOR_S"))

    def test_l_allarme_dice_il_nome_e_mai_il_valore(self):
        registro = MagicMock()
        _leggi(registro, TEMPO_MONITOR_S="sk-segreto-incollato")
        testo = " ".join(str(c) for c in registro.warning.call_args_list)
        self.assertIn("TEMPO_MONITOR_S", testo)
        self.assertIn("[ALLARME]", testo)
        self.assertNotIn("sk-segreto-incollato", testo)
        s = _leggi(TEMPO_MONITOR_S="sk-segreto-incollato")
        self.assertNotIn("sk-segreto-incollato", repr(s))

    def test_niente_allarme_se_tutto_valido(self):
        registro = MagicMock()
        _leggi(registro, TEMPO_MONITOR_S="900")
        self.assertFalse([c for c in registro.warning.call_args_list
                          if "TEMPO_" in str(c)])

    def test_verifica_stato_tetto_s_fuori_dal_nuovo_intervallo(self):
        s = _leggi(VERIFICA_STATO_TETTO_S="59")
        self.assertEqual(s.verifica_stato_tetto_s, 1800)
        self.assertEqual(s.verifica_stato_scartate, ("VERIFICA_STATO_TETTO_S",))


class TestTipiAttiviTutti(unittest.TestCase):
    def test_tutti_vale_i_dodici_tipi_del_monitor(self):
        s = _leggi(MONITOR_TIPI_ATTIVI="tutti")
        self.assertEqual(s.monitor_tipi_attivi, eventi.TIPI_PROPONIBILI)
        self.assertEqual(len(s.monitor_tipi_attivi), 12)
        self.assertEqual(s.monitor_tipi_attivi_ignorati, ())

    def test_senza_distinzione_di_maiuscole_e_in_mezzo_ad_altre_voci(self):
        for valore in ("Tutti", " TUTTI ", "faq, tutti", "tutti,proroga,faq"):
            with self.subTest(valore=valore):
                s = _leggi(MONITOR_TIPI_ATTIVI=valore)
                self.assertEqual(s.monitor_tipi_attivi, eventi.TIPI_PROPONIBILI)
                self.assertEqual(s.monitor_tipi_attivi_ignorati, ())

    def test_un_refuso_accanto_a_tutti_resta_un_allarme(self):
        s = _leggi(MONITOR_TIPI_ATTIVI="tutti,profroga")
        self.assertEqual(s.monitor_tipi_attivi, eventi.TIPI_PROPONIBILI)
        self.assertEqual(s.monitor_tipi_attivi_ignorati, ("profroga",))

    def test_senza_tutti_resta_l_elenco(self):
        s = _leggi(MONITOR_TIPI_ATTIVI="proroga,faq")
        self.assertEqual(s.monitor_tipi_attivi, ("proroga", "faq"))
        self.assertEqual(_leggi(MONITOR_TIPI_ATTIVI="").monitor_tipi_attivi, ())


class TestSpesaPerScenario(unittest.TestCase):
    def test_dollari_per_scenario(self):
        attesi = {"economico": (3.0, 90.0), "bilanciato": (5.0, 150.0), "massimo": (10.0, 300.0)}
        for scenario, (giorno, mese) in attesi.items():
            with self.subTest(scenario=scenario):
                s = _leggi(MONITOR_SCENARIO=scenario)
                self.assertEqual((s.tetto_usd_giorno, s.tetto_usd_mese), (giorno, mese))

    def test_bilanciato_di_default(self):
        s = _leggi()
        self.assertEqual(s.monitor_scenario, "bilanciato")
        self.assertEqual((s.tetto_usd_giorno, s.tetto_usd_mese), (5.0, 150.0))

    def test_le_variabili_esplicite_vincono_ancora(self):
        s = _leggi(TETTO_USD_GIORNO="7.5", TETTO_USD_MESE="200")
        self.assertEqual((s.tetto_usd_giorno, s.tetto_usd_mese), (7.5, 200.0))

    def test_crediti_invariati(self):
        # §3 «Invariati»: i crediti Firecrawl non cambiano con il giro 3.
        s = _leggi()
        self.assertEqual((s.tetto_crediti_giorno, s.tetto_crediti_mese), (120, 5000))


class TestVariabiliDismesse(unittest.TestCase):
    """B6 (§3 «Dismessi»): i campi non ci sono piu', i nomi rimasti
    nell'ambiente si elencano, mai i valori."""

    DISMESSE = ("TETTO_CLASSIFICAZIONI_GIORNO", "TETTO_FETCH_GIRO",
                "VERIFICA_STATO_TETTO_LETTURE", "VERIFICA_STATO_MAX_CHIUSURE",
                "VERIFICA_STATO_TETTO_INGRESSO", "GEMELLI_FUSIONI_PER_GIRO")

    def test_i_campi_non_esistono_piu(self):
        campi = {f.name for f in dataclasses.fields(settings.Settings)}
        for campo in ("tetto_classificazioni_giorno", "tetto_fetch_giro",
                      "verifica_stato_tetto_letture", "verifica_stato_max_chiusure",
                      "verifica_stato_tetto_ingresso", "gemelli_fusioni_per_giro"):
            with self.subTest(campo=campo):
                self.assertNotIn(campo, campi)
        self.assertEqual(settings.VARIABILI_DISMESSE, self.DISMESSE)

    def test_senza_dismesse_elenco_vuoto(self):
        self.assertEqual(_leggi().variabili_dismesse, ())

    def test_i_nomi_presenti_e_mai_i_valori(self):
        s = _leggi(TETTO_FETCH_GIRO="420", GEMELLI_FUSIONI_PER_GIRO="sk-segreto",
                   VERIFICA_STATO_TETTO_LETTURE="")
        self.assertEqual(s.variabili_dismesse,
                         ("TETTO_FETCH_GIRO", "VERIFICA_STATO_TETTO_LETTURE",
                          "GEMELLI_FUSIONI_PER_GIRO"))
        self.assertNotIn("sk-segreto", repr(s))

    def test_non_sono_un_allarme_di_configurazione(self):
        s = _leggi(TETTO_FETCH_GIRO="420")
        self.assertEqual((s.configurazione_scartate, s.verifica_stato_scartate), ((), ()))

    def test_il_tetto_per_scenario_e_solo_spesa(self):
        for voci in settings._TETTI_SCENARIO.values():
            self.assertNotIn("fetch_giro", voci)

    def test_l_esempio_non_le_assegna_piu(self):
        testo = (RADICE / ".env.example").read_text(encoding="utf-8")
        for nome in self.DISMESSE:
            with self.subTest(variabile=nome):
                self.assertIsNone(re.search(rf"^{nome}=", testo, re.MULTILINE))


class TestEnvExample(unittest.TestCase):
    def test_solo_i_nomi(self):
        testo = (RADICE / ".env.example").read_text(encoding="utf-8")
        for nome in ("GEMELLI_MODALITA", "DOMINI_MODALITA", *TEMPI):
            with self.subTest(variabile=nome):
                riga = re.search(rf"^{nome}=(.*)$", testo, re.MULTILINE)
                self.assertIsNotNone(riga, nome)
                self.assertEqual(riga.group(1), "")
        self.assertIn("(60-3600, default 1800)", testo)
        self.assertIn("`tutti`", testo)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
