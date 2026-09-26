# -*- coding: utf-8 -*-
"""Telemetria: `pipeline_run`, `fonte_run`, riepilogo e `salute` (fix 8.a.14).

Nessuna rete: il client Supabase e l'adattatore `db.controllo` sono finti, e
`salute` e' una funzione pura che non tocca niente.
"""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

telemetria = carica_modulo("telemetria")


class _Controllo:
    def __init__(self, colonne_per_tabella=None):
        self._colonne = colonne_per_tabella or {}

    def colonne(self, tabella):
        return frozenset(self._colonne.get(tabella, ()))


class _Tabella:
    def __init__(self, registro, nome, risposta=None, errore=None):
        self._registro = registro
        self._nome = nome
        self._risposta = risposta
        self._errore = errore

    def insert(self, payload):
        self._registro.append((self._nome, payload))
        if self._errore is not None:
            raise self._errore
        return self

    def execute(self):
        return self._risposta


class _Client:
    def __init__(self, risposta=None, errore=None):
        self.scritture: list[tuple[str, dict]] = []
        self._risposta = risposta
        self._errore = errore

    def table(self, nome):
        return _Tabella(self.scritture, nome, self._risposta, self._errore)


class _Dati:
    def __init__(self, data):
        self.data = data


class TestPipelineRun(unittest.TestCase):
    def test_concludi_non_muta_l_originale(self):
        run = telemetria.PipelineRun(step="monitor", giro="06:00")
        concluso = run.concludi(durata_s=12.34, contatori={"fetch": 3}, crediti=7, costo_usd=0.5)
        self.assertIsNone(run.concluso_at)
        self.assertEqual(run.contatori, {})
        self.assertEqual(concluso.durata_s, 12.3)
        self.assertEqual(concluso.crediti, 7)
        self.assertEqual(concluso.contatori, {"fetch": 3})
        self.assertIsNotNone(concluso.concluso_at)

    def test_esito_da_contatori(self):
        self.assertEqual(telemetria.esito_da_contatori(), telemetria.ESITO_OK)
        self.assertEqual(telemetria.esito_da_contatori(errori=2), telemetria.ESITO_ERRORE)
        self.assertEqual(
            telemetria.esito_da_contatori(interrotto_per_tetto=True), telemetria.ESITO_INTERROTTO)
        # Il lock vince: se lo step non e' partito, gli errori non esistono.
        self.assertEqual(
            telemetria.esito_da_contatori(errori=5, saltato_per_lock=True), telemetria.ESITO_SALTATO)

    def test_riga_serializzabile(self):
        run = telemetria.PipelineRun(step="seo", slug_modificati=("a", "b"))
        riga = run.come_riga()
        self.assertEqual(riga["slug_modificati"], ["a", "b"])
        json.dumps(riga)


class TestRiepilogo(unittest.TestCase):
    def test_una_riga_json_ordinata(self):
        run = telemetria.PipelineRun(step="monitor", giro="18:00").concludi(
            durata_s=3.0, contatori={"fetch": 2}, crediti=1, costo_usd=0.125,
            interrotto_per_tetto=True, motivo="tetto fetch",
            slug_modificati=("bando-x",),
        )
        riga = telemetria.riepilogo(run)
        self.assertNotIn("\n", riga)
        dati = json.loads(riga)
        self.assertEqual(dati["step"], "monitor")
        self.assertEqual(dati["giro"], "18:00")
        self.assertTrue(dati["interrotto_per_tetto"])
        self.assertEqual(dati["slug_modificati"], 1)
        self.assertEqual(list(dati), sorted(dati))


class TestSalute(unittest.TestCase):
    def test_stato_sano(self):
        esito = telemetria.salute(telemetria.Stato())
        self.assertEqual(esito.allarmi, ())
        self.assertEqual(esito.exit_code, 0)

    def test_monitor_fermo_da_24_ore(self):
        esito = telemetria.salute(telemetria.Stato(ore_dall_ultimo_monitor_ok=25))
        self.assertEqual(esito.exit_code, 1)
        self.assertIn("nessun monitor OK", esito.allarmi[0])

    def test_tetto_in_due_giri_consecutivi(self):
        self.assertEqual(telemetria.salute(telemetria.Stato(giri_consecutivi_a_tetto=1)).allarmi, ())
        self.assertEqual(len(telemetria.salute(telemetria.Stato(giri_consecutivi_a_tetto=2)).allarmi), 1)

    def test_soglie_di_consumo(self):
        self.assertTrue(telemetria.salute(telemetria.Stato(crediti_residui_quota=0.14)).allarmi)
        self.assertFalse(telemetria.salute(telemetria.Stato(crediti_residui_quota=0.15)).allarmi)
        self.assertTrue(telemetria.salute(telemetria.Stato(consumo_mensile_quota=0.80)).allarmi)
        self.assertFalse(telemetria.salute(telemetria.Stato(consumo_mensile_quota=0.79)).allarmi)

    def test_qualita_della_pipeline(self):
        self.assertTrue(telemetria.salute(telemetria.Stato(quota_in_verifica_nuovi=0.31)).allarmi)
        self.assertTrue(
            telemetria.salute(telemetria.Stato(quota_schede_oe_con_sezione=0.79)).allarmi)
        self.assertTrue(telemetria.salute(telemetria.Stato(quota_controlli_falliti=0.03)).allarmi)

    def test_login_oe_fallito(self):
        self.assertIn(
            "login Obiettivo Europa fallito",
            telemetria.salute(telemetria.Stato(login_oe_ok=False)).allarmi,
        )

    def test_proposta_economico_ma_nessun_cambio_automatico(self):
        # A24: `salute` propone, lo switch resta manuale via MONITOR_SCENARIO.
        esito = telemetria.salute(telemetria.Stato(residuo_piano_su_tetto_mensile=2.5))
        self.assertIn("MONITOR_SCENARIO=economico", esito.allarmi[0])

    def test_indexnow_solo_in_attivo(self):
        # M15: in ombra la chiave non serve, e non deve generare rumore.
        self.assertEqual(
            telemetria.salute(
                telemetria.Stato(modalita_monitor="ombra", indexnow_configurata=False)).allarmi, (),
        )
        self.assertTrue(
            telemetria.salute(
                telemetria.Stato(modalita_monitor="attivo", indexnow_configurata=False)).allarmi,
        )

    def test_monitor_giri_fuori_dallo_scheduler(self):
        # M13: un MONITOR_GIRI su un'ora in cui la pipeline non parte mai e'
        # un monitor spento in silenzio. Deve dirlo subito, senza aspettare le
        # 24 h di «nessun monitor OK» (misura che oggi non esiste ancora).
        self.assertEqual(telemetria.salute(telemetria.Stato()).allarmi, ())
        esito = telemetria.salute(telemetria.Stato(monitor_giri_validi=False))
        self.assertEqual(esito.exit_code, 1)
        self.assertIn("MONITOR_GIRI", esito.allarmi[0])

    def test_modelli_fuori_listino_sono_avvisi_non_allarmi(self):
        esito = telemetria.salute(telemetria.Stato(modelli_fuori_listino=("claude-sonnet-5",)))
        self.assertEqual(esito.allarmi, ())
        self.assertEqual(esito.avvisi, ("modello non a listino: claude-sonnet-5",))
        self.assertEqual(esito.exit_code, 0)

    def test_righe_allarme_con_prefisso(self):
        esito = telemetria.salute(telemetria.Stato(login_oe_ok=False))
        self.assertTrue(telemetria.righe_allarme(esito)[0].startswith(telemetria.PREFISSO_ALLARME))

    def test_il_tetto_riporta_il_motivo_e_non_dice_piu_fetch(self):
        # Il 25/09/2026 i due giri a tetto erano per le classificazioni, non
        # per il fetch: il testo di prima avrebbe mandato a cercare altrove.
        esito = telemetria.salute(telemetria.Stato(
            giri_consecutivi_a_tetto=2,
            motivo_ultimo_tetto="tetto giornaliero classificazioni raggiunto (201/30)"))
        self.assertEqual(len(esito.allarmi), 1)
        self.assertNotIn("fetch", esito.allarmi[0])
        self.assertIn("201/30", esito.allarmi[0])

    def test_lock_tenuto_avviso_poi_allarme(self):
        lock = telemetria.LockTenuto
        breve = telemetria.salute(telemetria.Stato(lock_tenuti=(lock("pipeline", "sender", 12),)))
        self.assertEqual((breve.allarmi, breve.avvisi), ((), ()))
        lungo = telemetria.salute(telemetria.Stato(lock_tenuti=(lock("pipeline", "sender", 90),)))
        self.assertEqual(lungo.allarmi, ())
        self.assertIn("«pipeline»", lungo.avvisi[0])
        orfano = telemetria.salute(telemetria.Stato(lock_tenuti=(lock("monitor", "cli", 200),)))
        self.assertEqual(orfano.exit_code, 1)
        self.assertIn("orfano", orfano.allarmi[0])

    def test_db_non_leggibile_e_un_allarme(self):
        esito = telemetria.salute(telemetria.Stato(misure_db_errore="ConnectError: timeout"))
        self.assertEqual(esito.exit_code, 1)
        self.assertIn("misure sul DB non disponibili", esito.allarmi[0])

    def test_cio_che_non_si_misura_si_dice_negli_avvisi(self):
        esito = telemetria.salute(telemetria.Stato(non_misurati=("login Obiettivo Europa",)))
        self.assertEqual(esito.exit_code, 0)
        self.assertEqual(esito.avvisi, ("non misurato da salute: login Obiettivo Europa",))


class TestStatoDaMisure(unittest.TestCase):
    """Le misure di `salute` dalle righe del DB: funzione pura, nessuna rete."""

    ADESSO = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)

    def _misure(self, **kwargs):
        base = {"monitor": [], "pipeline": [], "mese": [], "nuovi": [],
                "vivi": [], "falliti": [], "lock": []}
        base.update(kwargs)
        return base

    def test_ore_dall_ultimo_monitor_ok(self):
        campi = telemetria.stato_da_misure(self._misure(monitor=[
            {"esito": "interrotto_per_tetto", "avviato_at": "2026-09-25T16:11:00+00:00"},
            {"esito": "ok", "avviato_at": "2026-09-25T04:00:00+00:00",
             "concluso_at": "2026-09-25T06:00:00+00:00"},
        ]), adesso=self.ADESSO)
        self.assertEqual(campi["ore_dall_ultimo_monitor_ok"], 26.0)
        self.assertTrue(telemetria.salute(telemetria.Stato(**campi)).allarmi)

    def test_nessun_monitor_ok_fra_le_righe_lette(self):
        campi = telemetria.stato_da_misure(self._misure(monitor=[
            {"esito": "errore", "avviato_at": "2026-09-25T16:00:00+00:00"},
            {"esito": "errore", "avviato_at": "2026-09-24T04:00:00+00:00"},
        ]), adesso=self.ADESSO)
        self.assertEqual(campi["ore_dall_ultimo_monitor_ok"], 52.0)

    def test_giri_consecutivi_a_tetto_e_motivo_annidato(self):
        tetto = {"interrotto_per_tetto": True, "motivo": "",
                 "contatori": {"seo": {"selected": 3},
                               "monitor": {"motivo": "tetto giornaliero classificazioni raggiunto (201/30)"}}}
        campi = telemetria.stato_da_misure(self._misure(pipeline=[
            tetto, dict(tetto), {"interrotto_per_tetto": False}, dict(tetto),
        ]), adesso=self.ADESSO)
        self.assertEqual(campi["giri_consecutivi_a_tetto"], 2)
        self.assertIn("201/30", campi["motivo_ultimo_tetto"])

    def test_in_verifica_sui_nuovi_solo_con_abbastanza_bandi(self):
        pochi = [{"fonte_ufficiale_stato": "in_verifica"}] * 4 + [{"fonte_ufficiale_stato": "trovata"}] * 5
        campi = telemetria.stato_da_misure(self._misure(nuovi=pochi), adesso=self.ADESSO)
        self.assertNotIn("quota_in_verifica_nuovi", campi)
        self.assertTrue(any("in verifica sui nuovi" in v for v in campi["non_misurati"]))
        abbastanza = pochi + [{"fonte_ufficiale_stato": "non_trovata"}] * 3
        campi = telemetria.stato_da_misure(self._misure(nuovi=abbastanza), adesso=self.ADESSO)
        self.assertAlmostEqual(campi["quota_in_verifica_nuovi"], 4 / 12)

    def test_controlli_falliti_contano_solo_i_vivi(self):
        campi = telemetria.stato_da_misure(self._misure(
            vivi=list(range(1, 101)), falliti=[3, 4, 500]), adesso=self.ADESSO)
        self.assertAlmostEqual(campi["quota_controlli_falliti"], 0.02)
        self.assertEqual(telemetria.salute(telemetria.Stato(**campi)).allarmi, ())

    def test_consumo_mensile_senza_i_lotti(self):
        mese = [
            {"step": "monitor", "crediti": "100", "usd": "1.5"},
            {"step": "resolver", "crediti": None, "usd": "0.5"},
            {"step": "backfill:L5", "crediti": "4000", "usd": "30"},
        ]
        campi = telemetria.stato_da_misure(self._misure(mese=mese), adesso=self.ADESSO,
                                           tetto_crediti_mese=5000, tetto_usd_mese=16.0)
        self.assertAlmostEqual(campi["consumo_mensile_quota"], 2.0 / 16.0)

    def test_senza_tetti_il_consumo_non_si_misura(self):
        campi = telemetria.stato_da_misure(self._misure(mese=[{"step": "monitor", "usd": "9"}]),
                                           adesso=self.ADESSO)
        self.assertNotIn("consumo_mensile_quota", campi)
        self.assertIn("consumo mensile", campi["non_misurati"])

    def test_lock_scaduti_ignorati_quelli_validi_misurati(self):
        campi = telemetria.stato_da_misure(self._misure(lock=[
            {"nome": "pipeline", "proprietario": "sender",
             "acquisito_at": "2026-09-26T04:00:00+00:00", "scade_at": "2026-09-26T08:00:00+00:00"},
            {"nome": "monitor", "proprietario": "cli",
             "acquisito_at": "2026-09-26T04:30:00+00:00", "scade_at": "2026-09-26T09:30:00+00:00"},
        ]), adesso=self.ADESSO)
        self.assertEqual(campi["lock_tenuti"], (telemetria.LockTenuto("monitor", "cli", 210.0),))
        self.assertEqual(telemetria.salute(telemetria.Stato(**campi)).exit_code, 1)

    def test_tabelle_assenti_finiscono_nei_non_misurati_senza_allarmi(self):
        campi = telemetria.stato_da_misure(
            {"monitor": None, "pipeline": None, "mese": None, "nuovi": None,
             "vivi": None, "falliti": None, "lock": None}, adesso=self.ADESSO)
        esito = telemetria.salute(telemetria.Stato(**campi))
        self.assertEqual(esito.allarmi, ())
        self.assertEqual(len(esito.avvisi), 1)
        for voce in ("login Obiettivo Europa", "giri a tetto", "lock di esecuzione",
                     "controlli falliti", "consumo mensile"):
            self.assertIn(voce, esito.avvisi[0])

    def test_uno_stato_sano_non_ha_allarmi(self):
        # La fotografia del 26/09/2026 alle 10: monitor delle 06 OK, ultimo giro
        # senza tetto, nessun lock.
        campi = telemetria.stato_da_misure(self._misure(
            monitor=[{"esito": "ok", "avviato_at": "2026-09-26T04:08:03+00:00",
                      "concluso_at": "2026-09-26T04:09:05+00:00"}],
            pipeline=[{"interrotto_per_tetto": False}, {"interrotto_per_tetto": False},
                      {"interrotto_per_tetto": True, "motivo": "x"}],
        ), adesso=self.ADESSO)
        esito = telemetria.salute(telemetria.Stato(**campi))
        self.assertEqual(esito.allarmi, ())
        self.assertEqual(campi["giri_consecutivi_a_tetto"], 0)


class TestScrittura(unittest.TestCase):
    def test_tabella_assente_non_scrive_e_non_solleva(self):
        client = _Client()
        run = telemetria.PipelineRun(step="seo")
        self.assertIsNone(
            telemetria.scrivi_pipeline_run(run, controllo=_Controllo(), client=client))
        self.assertEqual(client.scritture, [])

    def test_scrive_solo_le_colonne_esistenti(self):
        client = _Client(risposta=_Dati([{"id": 42}]))
        controllo = _Controllo({telemetria.TABELLA_RUN: ("id", "step", "giro", "esito")})
        run = telemetria.PipelineRun(step="monitor", giro="06:00")
        identificativo = telemetria.scrivi_pipeline_run(run, controllo=controllo, client=client)
        self.assertEqual(identificativo, 42)
        _tabella, payload = client.scritture[0]
        self.assertEqual(set(payload), {"step", "giro", "esito"})

    def test_errore_di_scrittura_degrada(self):
        client = _Client(errore=RuntimeError("42501"))
        controllo = _Controllo({telemetria.TABELLA_RUN: ("step",)})
        self.assertIsNone(
            telemetria.scrivi_pipeline_run(
                telemetria.PipelineRun(step="seo"), controllo=controllo, client=client))

    def test_fonte_run(self):
        # I nomi sono quelli della 02: `items`, non `elementi`; `pipeline_run_id`,
        # non `run_id`; `errore`, non `motivo`. Senza la traduzione i tre
        # valori sparivano dal payload senza un errore.
        client = _Client(risposta=_Dati([{"id": 7}]))
        controllo = _Controllo({telemetria.TABELLA_FONTE_RUN: (
            "fonte_id", "pipeline_run_id", "items", "nuovi", "cambiati",
            "troncato", "errore", "durata_s")})
        riga = telemetria.FonteRun(fonte_id=237, elementi=50, run_id=9)
        self.assertEqual(telemetria.scrivi_fonte_run(riga, controllo=controllo, client=client), 7)
        _tabella, payload = client.scritture[0]
        self.assertEqual(payload["fonte_id"], 237)
        self.assertEqual(payload["items"], 50)
        self.assertEqual(payload["pipeline_run_id"], 9)
        self.assertIsNone(payload["errore"])

    def test_fonte_run_racconta_esito_ed_errori_nella_colonna_errore(self):
        client = _Client(risposta=_Dati([{"id": 8}]))
        controllo = _Controllo({telemetria.TABELLA_FONTE_RUN: ("fonte_id", "errore")})
        riga = telemetria.FonteRun(
            fonte_id=237, esito=telemetria.ESITO_ERRORE, errori=3, motivo="403")
        telemetria.scrivi_fonte_run(riga, controllo=controllo, client=client)
        _tabella, payload = client.scritture[0]
        self.assertEqual(payload["errore"], "403; 3 errori")

    def test_i_cinque_valori_senza_colonna_finiscono_nei_contatori(self):
        # `pipeline_run` ha dieci colonne e nessuna per `durata_s`, `crediti`,
        # `costo_usd`, `slug_modificati`, `saltato_per_lock`: sono i numeri su
        # cui §6.2 fonda i tetti, e sparivano senza errore e senza log.
        riga = telemetria.PipelineRun(step="monitor").concludi(
            durata_s=12.5, crediti=7, costo_usd=0.25,
            slug_modificati=("bando-x",), saltato_per_lock=True,
            contatori={"fetch": 3},
        ).come_riga()
        self.assertEqual(riga["contatori"]["durata_s"], 12.5)
        self.assertEqual(riga["contatori"]["crediti"], 7)
        self.assertEqual(riga["contatori"]["costo_usd"], 0.25)
        # `usd` e' il nome che cerca `bilancio.verifica_giornalieri`.
        self.assertEqual(riga["contatori"]["usd"], 0.25)
        self.assertEqual(riga["contatori"]["slug_modificati"], ["bando-x"])
        self.assertTrue(riga["contatori"]["saltato_per_lock"])
        self.assertEqual(riga["contatori"]["fetch"], 3)

    def test_un_valore_davvero_perduto_si_dice(self):
        client = _Client(risposta=_Dati([{"id": 9}]))
        controllo = _Controllo({telemetria.TABELLA_RUN: ("step", "contatori")})
        with patch.object(telemetria, "logger", MagicMock()) as log:
            telemetria.scrivi_pipeline_run(
                telemetria.PipelineRun(step="seo"), controllo=controllo, client=client)
        self.assertTrue(log.warning.called)
        perduti = log.warning.call_args.args[2]
        # I cinque rispecchiati in `contatori` non sono perduti: non ci sono.
        self.assertNotIn("crediti", perduti)
        self.assertIn("esito", perduti)

    def test_nessuna_colonna_compatibile(self):
        client = _Client()
        controllo = _Controllo({telemetria.TABELLA_RUN: ("colonna_ignota",)})
        self.assertIsNone(
            telemetria.scrivi_pipeline_run(
                telemetria.PipelineRun(step="seo"), controllo=controllo, client=client))
        self.assertEqual(client.scritture, [])


if __name__ == "__main__":
    unittest.main()
