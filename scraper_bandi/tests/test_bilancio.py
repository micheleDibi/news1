# -*- coding: utf-8 -*-
"""Contatori, listino e tetti (piano §6.2, §6.3, A23, A36, §16.2 M19).

Tutto puro: nessuna rete, nessun DB, nessun `SystemExit`.
"""
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
        c = bilancio.Contatori(fetch=10_000)
        self.assertTrue(bilancio.verifica_fetch(c, bilancio.Tetti()).consentito)

    def test_tetto_fetch_per_giro(self):
        tetti = bilancio.Tetti(fetch_giro=420)
        self.assertTrue(bilancio.verifica_fetch(bilancio.Contatori(fetch=419), tetti).consentito)
        esito = bilancio.verifica_fetch(bilancio.Contatori(fetch=420), tetti)
        self.assertFalse(esito.consentito)
        self.assertTrue(esito.interrotto_per_tetto)
        self.assertIn("fetch", esito.motivo)

    def test_esito_e_un_dizionario_non_un_exit(self):
        # §16/A15: dentro la pipeline non si esce mai, si ritorna un esito.
        esito = bilancio.verifica_fetch(bilancio.Contatori(fetch=5), bilancio.Tetti(fetch_giro=1))
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

    def test_tetto_giornaliero_ricerche_e_classificazioni(self):
        tetti = bilancio.Tetti(ricerche_giorno=50, classificazioni_giorno=30)
        self.assertFalse(
            bilancio.verifica_giornalieri(bilancio.Contatori(ricerche=50), tetti).consentito)
        self.assertFalse(
            bilancio.verifica_giornalieri(bilancio.Contatori(classificazioni=30), tetti).consentito)

    def test_tetto_giornaliero_usd(self):
        tetti = bilancio.Tetti(usd_giorno=1.5)
        c = bilancio.Contatori()
        bilancio.registra_chiamata(c, "claude-opus-4-7", {"input_tokens": 400_000}, LISTINO)
        self.assertFalse(bilancio.verifica_giornalieri(c, tetti).consentito)

    def test_mensile_con_riserva_del_dieci_percento(self):
        # A23: al tetto si fermano monitor e ricontrolli, il resolver continua
        # con una riserva del 10%.
        tetti = bilancio.Tetti(crediti_mese=5000)
        self.assertFalse(bilancio.verifica_mensili(crediti_mese=4500, usd_mese=0, tetti=tetti).consentito)
        self.assertTrue(bilancio.verifica_mensili(crediti_mese=4499, usd_mese=0, tetti=tetti).consentito)
        self.assertTrue(
            bilancio.verifica_mensili(crediti_mese=4500, usd_mese=0, tetti=tetti, riserva=0.0).consentito)

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
        tetti = bilancio.Tetti(fetch_giro=10, crediti_giorno=10, backfill_crediti=8000)
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
        tetti = bilancio.Tetti(fetch_giro=10, crediti_giorno=5, crediti_mese=1)
        esito = bilancio.verifica(bilancio.Contatori(fetch=10, crediti_firecrawl=5), tetti)
        self.assertIn("fetch", esito.motivo)

    def test_mensile_solo_se_passato(self):
        tetti = bilancio.Tetti(crediti_mese=5000)
        self.assertTrue(bilancio.verifica(bilancio.Contatori(), tetti).consentito)
        self.assertFalse(
            bilancio.verifica(bilancio.Contatori(), tetti, crediti_mese=5000).consentito)


class TestTettiDalleImpostazioni(unittest.TestCase):
    def test_scenario_bilanciato_di_default(self):
        impostazioni = settings.get_settings()
        self.assertEqual(impostazioni.monitor_scenario, "bilanciato")
        tetti = bilancio.tetti_da_impostazioni(impostazioni)
        self.assertEqual(tetti.fetch_giro, 420)
        self.assertEqual(tetti.crediti_mese, 5000)
        self.assertEqual(tetti.usd_mese, 16.0)
        self.assertEqual(tetti.ricerche_giorno, 50)     # M19: tetti di regime
        self.assertEqual(tetti.crediti_giorno, 120)
        self.assertEqual(tetti.backfill_crediti, 8000)
        self.assertEqual(tetti.backfill_usd, 60.0)


if __name__ == "__main__":
    unittest.main()
