# -*- coding: utf-8 -*-
"""Contatori, listino e tetti (piano §6.2, §6.3, A23, A36, §16.2 M19).

Tutto puro: nessuna rete, nessun DB, nessun `SystemExit`.
"""
import dataclasses
import unittest

from tests.supporto import carica_modulo

bilancio = carica_modulo("bilancio")
settings = carica_modulo("settings")

LISTINO = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}


class TestListino(unittest.TestCase):
    def test_costo_dal_listino(self):
        usd, fuori = bilancio.costo_usd(1_000_000, 1_000_000, "claude-sonnet-4-6", LISTINO)
        self.assertAlmostEqual(usd, 18.0)
        self.assertFalse(fuori)

    def test_modello_non_a_listino_costa_zero_e_segnala(self):
        # A36: meglio un allarme che un numero inventato su cui poggia un tetto.
        usd, fuori = bilancio.costo_usd(1000, 1000, "claude-sonnet-5", LISTINO)
        self.assertEqual(usd, 0.0)
        self.assertTrue(fuori)

    def test_token_negativi_non_scontano(self):
        usd, _ = bilancio.costo_usd(-5000, 1_000_000, "claude-haiku-4-5", LISTINO)
        self.assertAlmostEqual(usd, 5.0)

    def test_token_da_uso_oggetto_e_dizionario(self):
        class Uso:
            input_tokens = 100
            output_tokens = 20
            cache_read_input_tokens = 5
        self.assertEqual(bilancio.token_da_uso(Uso()), (105, 20))
        self.assertEqual(
            bilancio.token_da_uso({"input_tokens": 7, "output_tokens": 3}), (7, 3),
        )
        self.assertEqual(bilancio.token_da_uso(None), (0, 0))

    def test_token_illeggibili_valgono_zero(self):
        self.assertEqual(bilancio.token_da_uso({"input_tokens": "boh"}), (0, 0))


class TestContatori(unittest.TestCase):
    def test_registra_chiamate_somma_per_modello(self):
        c = bilancio.Contatori()
        bilancio.registra_chiamata(c, "claude-haiku-4-5", {"input_tokens": 1_000_000}, LISTINO)
        bilancio.registra_chiamata(
            c, "claude-haiku-4-5", {"input_tokens": 0, "output_tokens": 1_000_000}, LISTINO)
        uso = c.modelli["claude-haiku-4-5"]
        self.assertEqual((uso.chiamate, uso.token_ingresso, uso.token_uscita), (2, 1_000_000, 1_000_000))
        self.assertAlmostEqual(c.usd, 6.0)
        self.assertEqual(c.chiamate, 2)

    def test_allarme_modello_non_a_listino_una_volta_sola(self):
        c = bilancio.Contatori()
        for _ in range(3):
            bilancio.registra_chiamata(c, "modello-ignoto", {"input_tokens": 10}, LISTINO)
        self.assertEqual(c.fuori_listino, ("modello-ignoto",))
        self.assertEqual(
            bilancio.allarmi_listino(c), (f"{bilancio.MODELLO_FUORI_LISTINO}: modello-ignoto",),
        )

    def test_come_dizionario_e_serializzabile(self):
        c = bilancio.Contatori(fetch=3)
        bilancio.registra_chiamata(c, "claude-haiku-4-5", {"input_tokens": 10}, LISTINO)
        dati = c.come_dizionario()
        self.assertEqual(dati["fetch"], 3)
        self.assertEqual(dati["modelli"]["claude-haiku-4-5"]["chiamate"], 1)

    def test_unisci_contatori_dello_scarico(self):
        scarico = carica_modulo("scarico")
        c = bilancio.Contatori(fetch=1)
        bilancio.unisci_scarico(c, scarico.Contatori(fetch=4, fetch_304=2, crediti_firecrawl=3, errori=1))
        self.assertEqual((c.fetch, c.fetch_304, c.crediti_firecrawl, c.errori), (5, 2, 3, 1))


class TestTetti(unittest.TestCase):
    def test_tetto_zero_non_morde(self):
        c = bilancio.Contatori(fetch=10_000, crediti_firecrawl=10_000, ricerche=10_000)
        self.assertTrue(bilancio.verifica(c, bilancio.Tetti(), step="monitor").consentito)

    def test_nessun_tetto_di_fetch_per_giro(self):
        # Giro 3, §1: il fetch per giro (420) non e' piu' un tetto.
        self.assertNotIn("fetch_giro", {f.name for f in dataclasses.fields(bilancio.Tetti)})
        self.assertFalse(hasattr(bilancio, "verifica_fetch"))
        c = bilancio.Contatori(fetch=100_000)
        self.assertTrue(bilancio.verifica(c, bilancio.Tetti(crediti_giorno=120), step="monitor").consentito)

    def test_esito_e_un_dizionario_non_un_exit(self):
        # §16/A15: dentro la pipeline non si esce mai, si ritorna un esito.
        esito = bilancio.verifica_giornalieri(bilancio.Contatori(crediti_firecrawl=5),
                                             bilancio.Tetti(crediti_giorno=1))
        self.assertEqual(
            esito.come_dizionario(),
            {"status": "ok", "interrotto_per_tetto": True, "motivo": esito.motivo},
        )

    def test_tetti_giornalieri_sommano_i_giri_precedenti(self):
        tetti = bilancio.Tetti(crediti_giorno=120)
        c = bilancio.Contatori(crediti_firecrawl=60)
        self.assertTrue(bilancio.verifica_giornalieri(c, tetti).consentito)
        esito = bilancio.verifica_giornalieri(c, tetti, gia_oggi={"crediti": 60})
        self.assertFalse(esito.consentito)
        self.assertIn("crediti", esito.motivo)

    def test_tetto_giornaliero_ricerche(self):
        tetti = bilancio.Tetti(ricerche_giorno=50)
        esito = bilancio.verifica_giornalieri(bilancio.Contatori(ricerche=50), tetti)
        self.assertFalse(esito.consentito)
        self.assertEqual((esito.voce, esito.motivo_rimasti), ("ricerche", "spesa"))

    def test_le_classificazioni_non_hanno_piu_un_tetto(self):
        # Giro 3, §1: «niente lotti». Il tetto delle 30 classificazioni al
        # giorno fermava tutto il ciclo del monitor; ora decide la spesa.
        self.assertNotIn("classificazioni_giorno", {f.name for f in dataclasses.fields(bilancio.Tetti)})
        c = bilancio.Contatori(classificazioni=10_000)
        self.assertTrue(bilancio.verifica(c, bilancio.Tetti(usd_giorno=5.0), step="monitor",
                                          gia_oggi={"classificazioni": 10_000}).consentito)

    def test_tetto_giornaliero_usd(self):
        tetti = bilancio.Tetti(usd_giorno=1.5)
        c = bilancio.Contatori()
        bilancio.registra_chiamata(c, "claude-opus-4-7", {"input_tokens": 400_000}, LISTINO)
        self.assertFalse(bilancio.verifica_giornalieri(c, tetti).consentito)

    def test_mensile_al_cento_per_cento(self):
        # Giro 3, §4: la riserva del 10 % per il resolver non serve piu', la
        # catena d'ingresso non si ferma mai. Il default morde al 100 %.
        tetti = bilancio.Tetti(crediti_mese=5000)
        self.assertTrue(bilancio.verifica_mensili(crediti_mese=4999, usd_mese=0, tetti=tetti).consentito)
        esito = bilancio.verifica_mensili(crediti_mese=5000, usd_mese=0, tetti=tetti)
        self.assertFalse(esito.consentito)
        self.assertEqual(esito.motivo_rimasti, "crediti")
        self.assertFalse(
            bilancio.verifica_mensili(crediti_mese=4500, usd_mese=0, tetti=tetti, riserva=0.10).consentito)

    def test_consumo_mensile_prende_il_peggiore(self):
        # Contatore 100, consumo reale del team 500 con 300 di baseline altrui
        # -> 200 e' la stima attribuibile: si prende quella.
        self.assertEqual(bilancio.consumo_mensile(100, 500, 300), 200)
        self.assertEqual(bilancio.consumo_mensile(100, 200, 300), 100)


class TestBackfill(unittest.TestCase):
    def test_riconoscimento_dello_step(self):
        self.assertTrue(bilancio.e_backfill("backfill:L2"))
        self.assertFalse(bilancio.e_backfill("monitor"))
        self.assertFalse(bilancio.e_backfill(""))

    def test_consumi_di_regime_senza_lotti_ne_riga_del_giro(self):
        # La riga `pipeline` risomma gli step: contarla raddoppia il resolver.
        self.assertTrue(bilancio.conta_nel_regime("monitor"))
        self.assertTrue(bilancio.conta_nel_regime("resolver"))
        self.assertFalse(bilancio.conta_nel_regime("pipeline"))
        self.assertFalse(bilancio.conta_nel_regime("backfill:L6"))

    def test_il_backfill_risponde_solo_ai_suoi_tetti(self):
        # M19: con i tetti di regime un lotto si fermerebbe al primo giro.
        tetti = bilancio.Tetti(crediti_giorno=10, backfill_crediti=8000)
        c = bilancio.Contatori(fetch=5000, crediti_firecrawl=1860)
        self.assertTrue(bilancio.verifica(c, tetti, step="backfill:L2").consentito)
        self.assertFalse(bilancio.verifica(c, tetti, step="monitor").consentito)

    def test_tetto_backfill_crediti_e_usd(self):
        tetti = bilancio.Tetti(backfill_crediti=8000, backfill_usd=60.0)
        self.assertFalse(
            bilancio.verifica_backfill(bilancio.Contatori(crediti_firecrawl=8000), tetti).consentito)
        c = bilancio.Contatori()
        bilancio.registra_chiamata(c, "claude-opus-4-7", {"input_tokens": 12_000_000}, LISTINO)
        self.assertFalse(bilancio.verifica_backfill(c, tetti).consentito)


class TestVerificaCompleta(unittest.TestCase):
    def test_ordine_dei_tetti(self):
        # Il giornaliero morde prima del mensile.
        tetti = bilancio.Tetti(crediti_giorno=5, crediti_mese=1)
        esito = bilancio.verifica(bilancio.Contatori(fetch=10, crediti_firecrawl=5), tetti,
                                  gia_oggi={"crediti_mese": 1})
        self.assertIn("giornaliero crediti", esito.motivo)

    def test_mensile_solo_se_passato(self):
        tetti = bilancio.Tetti(crediti_mese=5000)
        self.assertTrue(bilancio.verifica(bilancio.Contatori(), tetti).consentito)
        self.assertFalse(
            bilancio.verifica(bilancio.Contatori(), tetti, crediti_mese=5000).consentito)
        # Il giorno senza le chiavi del mese: nessun controllo mensile.
        self.assertTrue(bilancio.verifica(bilancio.Contatori(), tetti,
                                          gia_oggi={"crediti": 9_999}).consentito)


class TestSpesaDelGiro3(unittest.TestCase):
    """Contratto `bandi-giro-3` §4: 5 $ al giorno, 150 al mese, ingresso libero."""

    def _spesa(self, usd):
        c = bilancio.Contatori()
        if usd:
            bilancio.registra_chiamata(c, "m", {"input_tokens": int(usd * 1_000_000)}, {"m": (1.0, 0.0)})
        return c

    def test_mensile_dal_consumo_del_mese_di_consumo_oggi(self):
        # `db.consumo_oggi` porta `usd_mese`/`crediti_mese`: chi passa gia'
        # `gia_oggi` (monitor, verifica) applica il mensile senza altro codice.
        tetti = bilancio.Tetti(usd_giorno=5.0, usd_mese=150.0)
        gia = {"usd": 1.0, "usd_mese": 149.5, "crediti_mese": 10}
        self.assertTrue(bilancio.verifica(self._spesa(0.4), tetti, step="monitor", gia_oggi=gia).consentito)
        esito = bilancio.verifica(self._spesa(0.5), tetti, step="monitor", gia_oggi=gia)
        self.assertFalse(esito.consentito)
        self.assertIn("mensile", esito.motivo)
        self.assertEqual((esito.voce, esito.motivo_rimasti), ("usd", "spesa"))

    def test_crediti_del_mese(self):
        tetti = bilancio.Tetti(crediti_mese=5000)
        esito = bilancio.verifica(bilancio.Contatori(crediti_firecrawl=3), tetti, step="ricontrolli",
                                  gia_oggi={"crediti_mese": 4997})
        self.assertEqual((esito.consentito, esito.motivo_rimasti), (False, "crediti"))

    def test_giornaliero_prima_del_mensile(self):
        tetti = bilancio.Tetti(usd_giorno=5.0, usd_mese=150.0)
        esito = bilancio.verifica(self._spesa(1.0), tetti, step="verifica_stato",
                                  gia_oggi={"usd": 4.0, "usd_mese": 160.0})
        self.assertIn("giornaliero", esito.motivo)

    def test_valori_illeggibili_valgono_zero(self):
        tetti = bilancio.Tetti(usd_giorno=5.0, usd_mese=150.0)
        gia = {"usd": "x", "usd_mese": None, "crediti_mese": True}
        self.assertTrue(bilancio.verifica(self._spesa(1.0), tetti, step="monitor", gia_oggi=gia).consentito)

    def test_la_catena_d_ingresso_non_si_ferma_mai(self):
        self.assertEqual(bilancio.PASSI_INGRESSO,
                         frozenset({"preprocess", "enrich", "seo", "resolver_precoce", "resolver"}))
        tetti = bilancio.Tetti(ricerche_giorno=1, crediti_giorno=1, usd_giorno=1.0,
                               crediti_mese=1, usd_mese=1.0)
        c = self._spesa(9.0)
        c.ricerche, c.crediti_firecrawl, c.fetch = 9, 9, 9
        gia = {"usd": 9.0, "crediti": 9, "ricerche": 9, "usd_mese": 900.0, "crediti_mese": 900}
        for passo in sorted(bilancio.PASSI_INGRESSO):
            with self.subTest(passo=passo):
                self.assertTrue(bilancio.e_ingresso(passo))
                self.assertTrue(bilancio.verifica(c, tetti, step=passo, gia_oggi=gia).consentito)
        # La manutenzione risponde a tutto.
        for passo in ("monitor", "ricontrolli", "verifica_stato", "rigenerazione_scheda", ""):
            with self.subTest(passo=passo):
                self.assertFalse(bilancio.e_ingresso(passo))
                self.assertFalse(bilancio.verifica(c, tetti, step=passo, gia_oggi=gia).consentito)

    def test_esito_consentito_senza_motivo_dei_rimasti(self):
        self.assertIsNone(bilancio.OK.motivo_rimasti)
        self.assertEqual(bilancio.OK.voce, "")


class TestConsumoIlleggibile(unittest.TestCase):
    """Contratto `bandi-giro-3` §18.5: `db.consumo_oggi()` None = lettura fallita."""

    TETTI = bilancio.Tetti(usd_giorno=5.0, usd_mese=150.0, crediti_giorno=100)

    def test_per_la_manutenzione_vale_tetto_raggiunto(self):
        # Senza spesa nel giro: e' il consumo ignoto a fermare, non i contatori.
        for passo in ("monitor", "verifica_stato", "rigenerazione_scheda"):
            with self.subTest(passo=passo):
                esito = bilancio.verifica_con_consumo(
                    bilancio.Contatori(), self.TETTI, step=passo, consumo=None)
                self.assertFalse(esito.consentito)
                self.assertTrue(esito.interrotto_per_tetto)
                self.assertEqual(esito.motivo, bilancio.MOTIVO_CONSUMO_ILLEGGIBILE)
                self.assertEqual(esito.motivo_rimasti, "spesa")

    def test_l_ingresso_e_il_backfill_lo_ignorano(self):
        for passo in sorted(bilancio.PASSI_INGRESSO) + ["backfill:rielaborazione"]:
            with self.subTest(passo=passo):
                self.assertTrue(bilancio.verifica_con_consumo(
                    bilancio.Contatori(), self.TETTI, step=passo, consumo=None).consentito)

    def test_senza_tetti_di_regime_non_c_e_niente_da_superare(self):
        self.assertTrue(bilancio.verifica_con_consumo(
            bilancio.Contatori(), bilancio.Tetti(), step="monitor", consumo=None).consentito)

    def test_consumo_letto_e_la_verifica_di_sempre(self):
        gia = {"usd": 4.9, "usd_mese": 10.0}
        for consumo, atteso in (({}, True), (gia, True), ({"usd": 5.0}, False)):
            with self.subTest(consumo=consumo):
                self.assertEqual(bilancio.verifica_con_consumo(
                    bilancio.Contatori(), self.TETTI, step="monitor", consumo=consumo).consentito,
                    atteso)
                self.assertEqual(bilancio.verifica(
                    bilancio.Contatori(), self.TETTI, step="monitor", gia_oggi=consumo).consentito,
                    atteso)


class TestTettiDalleImpostazioni(unittest.TestCase):
    def test_scenario_bilanciato_di_default(self):
        impostazioni = settings.get_settings()
        self.assertEqual(impostazioni.monitor_scenario, "bilanciato")
        tetti = bilancio.tetti_da_impostazioni(impostazioni)
        self.assertEqual(tetti.usd_giorno, 5.0)
        self.assertEqual(tetti.crediti_mese, 5000)
        self.assertEqual(tetti.usd_mese, 150.0)      # giro 3, §3
        self.assertEqual(tetti.ricerche_giorno, 50)     # M19: tetti di regime
        self.assertEqual(tetti.crediti_giorno, 120)
        self.assertEqual(tetti.backfill_crediti, 8000)
        self.assertEqual(tetti.backfill_usd, 60.0)

    def test_le_variabili_dismesse_non_servono(self):
        # B6 toglie `tetto_fetch_giro` e `tetto_classificazioni_giorno` da
        # `Settings`: `tetti_da_impostazioni` non deve piu' leggerli.
        from types import SimpleNamespace
        impostazioni = SimpleNamespace(
            tetto_ricerche_giorno=50, tetto_crediti_giorno=120, tetto_usd_giorno=5.0,
            tetto_crediti_mese=5000, tetto_usd_mese=150.0, backfill_tetto_crediti=8000,
            backfill_tetto_usd=60.0)
        tetti = bilancio.tetti_da_impostazioni(impostazioni)
        self.assertEqual((tetti.usd_giorno, tetti.usd_mese), (5.0, 150.0))


if __name__ == "__main__":
    unittest.main()
