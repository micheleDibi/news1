# -*- coding: utf-8 -*-
"""`sorveglia` e `salute` con i codici (contratto `bandi-giro-2` §10 e §13).

Cosa si prova, senza rete (il DB e systemd sono finti):

- `stato_servizio` legge systemd senza shell, con un timeout, e dice «non
  misurato» (None) invece di «fermo» quando non puo' sapere;
- `fotografa` mette servizio, memoria e job orario DENTRO le misure prima di
  `stato_da_misure`; con il DB giu' l'errore e' un allarme redatto e il
  servizio si giudica lo stesso; `_stato_salute` la richiama;
- `esegui` legge la memoria per prima, scrive la riga unica per ultima, con
  un riepilogo che passa `valida_v1` o con quello minimo; exit 0 anche con
  allarmi, 1 su un errore, un upsert fallito o un DB che non risponde (misure
  o schema non leggibili); `--dry-run` non scrive; senza la migrazione 12
  (schema leggibile, tabella assente) un warning ed exit 0;
- nessuna chiamata di rete oltre a PostgREST: il modulo non importa client HTTP.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_sorveglianza
"""
import ast
import contextlib
import io
import json
import os
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.supporto import APP, carica_modulo

sorveglianza = carica_modulo("sorveglianza")
db = carica_modulo("db")
telemetria = carica_modulo("telemetria")
riepilogo_salute = carica_modulo("riepilogo_salute")
settings = carica_modulo("settings")
cli = carica_modulo("__main__")

ADESSO = datetime(2026, 10, 1, 6, 5, tzinfo=timezone.utc)
ATTIVO = {"active_state": "active", "sub_state": "running", "n_restarts": 2}


class StatoServizio(unittest.TestCase):
    def _esegui(self, stdout="", returncode=0, errore=None):
        chiamate = []

        def esegui(comando, **opzioni):
            chiamate.append((comando, opzioni))
            if errore is not None:
                raise errore
            return SimpleNamespace(returncode=returncode, stdout=stdout)
        return esegui, chiamate

    def test_legge_systemd_senza_shell_e_con_timeout(self):
        esegui, chiamate = self._esegui("ActiveState=active\nSubState=running\nNRestarts=3\n")
        self.assertEqual(sorveglianza.stato_servizio("edunews-bandi-sender", esegui=esegui),
                         {"active_state": "active", "sub_state": "running", "n_restarts": 3})
        (comando, opzioni), = chiamate
        # Le opzioni prima, poi `--`: dopo, il nome non puo' piu' essere un'opzione.
        self.assertEqual(comando, ["systemctl", "show", "-p", "ActiveState,SubState,NRestarts",
                                   "--", "edunews-bandi-sender"])
        self.assertEqual(opzioni["timeout"], 5)
        self.assertNotIn("shell", opzioni)

    def test_non_misurato_invece_di_fermo(self):
        casi = [
            self._esegui(returncode=1)[0],
            self._esegui(errore=subprocess.TimeoutExpired("systemctl", 5))[0],
            self._esegui("SubState=dead\n")[0],                       # niente ActiveState
        ]
        for esegui in casi:
            with self.subTest(esegui=esegui):
                self.assertIsNone(sorveglianza.stato_servizio("x", esegui=esegui))

    def test_nrestarts_illeggibile(self):
        esegui, _ = self._esegui("ActiveState=activating\nSubState=auto-restart\nNRestarts=\n")
        self.assertEqual(sorveglianza.stato_servizio("x", esegui=esegui)["n_restarts"], None)

    def test_nome_non_valido_non_esegue_niente(self):
        esegui, chiamate = self._esegui("ActiveState=active\n")
        self.assertIsNone(sorveglianza.stato_servizio("sender; rm -rf /", esegui=esegui))
        self.assertEqual(chiamate, [])

    def test_un_nome_che_sembra_un_opzione_non_esegue_niente(self):
        # «-H» farebbe interrogare a systemctl un host remoto via ssh.
        esegui, chiamate = self._esegui("ActiveState=active\n")
        for nome in ("-Hutente@host", "--host=utente@host", "-p", ".nascosto", "@istanza", ""):
            with self.subTest(nome=nome):
                self.assertIsNone(sorveglianza.stato_servizio(nome, esegui=esegui))
        self.assertEqual(chiamate, [])
        # un'istanza di template resta ammessa
        self.assertEqual(sorveglianza.stato_servizio("sender@1.service", esegui=esegui)["active_state"],
                         "active")

    def test_sul_mac_niente_systemctl(self):
        with patch.object(sorveglianza.shutil, "which", return_value=None):
            self.assertIsNone(sorveglianza.stato_servizio("edunews-bandi-sender"))

    def test_nome_del_servizio(self):
        with patch.dict(os.environ, {"SORVEGLIA_SERVIZIO_SENDER": ""}):
            self.assertEqual(sorveglianza.nome_servizio(), "edunews-bandi-sender")
        with patch.dict(os.environ, {"SORVEGLIA_SERVIZIO_SENDER": "altro-sender"}):
            self.assertEqual(sorveglianza.nome_servizio(), "altro-sender")


class _DbFinto:
    """Le cinque funzioni di `db` che la sorveglianza usa, con l'ordine delle chiamate."""

    def __init__(self, *, misure=None, memoria=None, disponibile=True, scrive=True,
                 misure_errore=None):
        self.ordine: list[str] = []
        self.scritte: list[dict] = []
        self._misure = misure if misure is not None else {}
        self._memoria = memoria
        self._disponibile = disponibile
        self._scrive = scrive
        self._errore = misure_errore

    def leggi_memoria_riepilogo(self):
        self.ordine.append("memoria")
        return self._memoria

    def misure_salute(self, *, adesso=None):
        self.ordine.append("misure")
        if self._errore is not None:
            raise self._errore
        return dict(self._misure)

    def job_orario(self):
        self.ordine.append("job_orario")
        return None

    def riepilogo_disponibile(self):
        self.ordine.append("disponibile")
        return self._disponibile

    def scrivi_riepilogo_monitoraggio(self, riga):
        self.ordine.append("scrivi")
        self.scritte.append(riga)
        return self._scrive

    def patch(self, caso):
        for nome in ("leggi_memoria_riepilogo", "misure_salute", "job_orario",
                     "riepilogo_disponibile", "scrivi_riepilogo_monitoraggio"):
            gestore = patch.object(db, nome, getattr(self, nome))
            gestore.start()
            caso.addCleanup(gestore.stop)
        gestore = patch.object(sorveglianza, "stato_servizio", return_value=dict(ATTIVO))
        gestore.start()
        caso.addCleanup(gestore.stop)


class Fotografa(unittest.TestCase):
    def test_servizio_memoria_e_job_orario_dentro_le_misure(self):
        finto = _DbFinto()
        finto.patch(self)
        memoria = {"nrestarts": [], "dal": {}}
        with patch.object(telemetria, "stato_da_misure", wraps=telemetria.stato_da_misure) as spia:
            foto = sorveglianza.fotografa(adesso=ADESSO, memoria=memoria, servizio=dict(ATTIVO))
        misure = spia.call_args.args[0]
        self.assertEqual(misure["servizio"], ATTIVO)
        self.assertEqual(misure["memoria"], memoria)
        self.assertIn("job_orario", misure)
        self.assertEqual(foto.stato.servizio, ATTIVO)
        self.assertNotIn("memoria", finto.ordine)       # passata: non si rilegge

    def test_db_giu_allarme_redatto_e_servizio_giudicato(self):
        finto = _DbFinto(misure_errore=ConnectionError("rifiutata: apikey=segretissima"))
        finto.patch(self)
        foto = sorveglianza.fotografa(adesso=ADESSO, memoria=None,
                                      servizio={"active_state": "failed", "sub_state": "failed",
                                                "n_restarts": 9})
        self.assertIn("ConnectionError", foto.stato.misure_db_errore)
        self.assertNotIn("segretissima", foto.stato.misure_db_errore)
        codici = {v.codice for v in telemetria.salute(foto.stato, adesso=ADESSO).voci}
        self.assertIn("misure_non_disponibili", codici)
        self.assertIn("servizio_non_attivo", codici)

    def test_modalita_e_configurazione_della_verifica_dalle_impostazioni(self):
        from dataclasses import replace
        finto = _DbFinto()
        finto.patch(self)
        vere = settings.get_settings()
        casi = [
            (replace(vere, verifica_stato_modalita="ombra", verifica_stato_scartate=()), "ombra", True),
            (replace(vere, verifica_stato_modalita="attivo", verifica_stato_scartate=()), "attivo", True),
            (replace(vere, verifica_stato_modalita="ombra",
                     verifica_stato_scartate=("VERIFICA_STATO_MODALITA",)), "ombra", False),
        ]
        for impostazioni, modalita, valida in casi:
            with self.subTest(modalita=modalita, valida=valida), \
                    patch.object(settings, "get_settings", return_value=impostazioni):
                foto = sorveglianza.fotografa(adesso=ADESSO, memoria={}, servizio=dict(ATTIVO))
                self.assertEqual(foto.stato.verifica_stato_modalita, modalita)
                self.assertIs(foto.stato.verifica_stato_config_valida, valida)
                codici = {v.codice for v in telemetria.salute(foto.stato, adesso=ADESSO).voci}
                self.assertEqual("configurazione:verifica_stato" in codici, not valida)

    def test_la_configurazione_della_verifica_passa_anche_col_db_giu(self):
        from dataclasses import replace
        finto = _DbFinto(misure_errore=ConnectionError("giu'"))
        finto.patch(self)
        impostazioni = replace(settings.get_settings(), verifica_stato_modalita="attivo",
                               verifica_stato_scartate=("VERIFICA_STATO_TETTO_S",))
        with patch.object(settings, "get_settings", return_value=impostazioni):
            foto = sorveglianza.fotografa(adesso=ADESSO, memoria=None, servizio=dict(ATTIVO))
        self.assertIsNotNone(foto.stato.misure_db_errore)
        self.assertEqual(foto.stato.verifica_stato_modalita, "attivo")
        self.assertIs(foto.stato.verifica_stato_config_valida, False)

    def test_stato_salute_la_richiama(self):
        stato = telemetria.Stato()
        with patch.object(sorveglianza, "fotografa",
                          return_value=sorveglianza.Fotografia(stato=stato)) as spia:
            self.assertIs(cli._stato_salute(), stato)
        spia.assert_called_once_with()


class MemoriaNuova(unittest.TestCase):
    def test_serie_di_sei_ore_trenta_punti_e_dal_dei_segnali(self):
        vecchi = [[(ADESSO - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ"), 1]]
        vecchi += [[(ADESSO - timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), 2]
                   for i in range(40, 0, -1)]
        vecchi += [["non una data", 3], ["2026-10-01T05:00:00Z"]]
        riepilogo = {"segnali": [{"codice": "produttore_fermo", "dal": "2026-10-01T01:00:00Z"},
                                 {"codice": "job_orario", "dal": "2026-10-01T06:05:00Z"}]}
        memoria = sorveglianza.memoria_nuova({"nrestarts": vecchi}, ATTIVO, riepilogo, ADESSO)
        self.assertEqual(len(memoria["nrestarts"]), 30)
        self.assertEqual(memoria["nrestarts"][-1], ["2026-10-01T06:05:00Z", 2])
        self.assertTrue(all(p[0] >= "2026-10-01T00:05:00Z" for p in memoria["nrestarts"]))
        self.assertEqual(memoria["dal"], {"produttore_fermo": "2026-10-01T01:00:00Z",
                                          "job_orario": "2026-10-01T06:05:00Z"})

    def test_senza_memoria_ne_servizio(self):
        self.assertEqual(sorveglianza.memoria_nuova(None, None, {"segnali": []}, ADESSO),
                         {"nrestarts": [], "dal": {}})


class Esegui(unittest.TestCase):
    def _esegui(self, finto, **opzioni):
        finto.patch(self)
        righe: list[str] = []
        codice = sorveglianza.esegui(adesso=ADESSO, stampa=righe.append, **opzioni)
        return codice, righe

    def test_ordine_e_riga_scritta(self):
        finto = _DbFinto(memoria={"nrestarts": [["2026-10-01T05:50:00Z", 1]], "dal": {}})
        codice, _ = self._esegui(finto)
        self.assertEqual(codice, 0)
        self.assertEqual(finto.ordine[0], "memoria")
        self.assertEqual(finto.ordine[-1], "scrivi")
        self.assertEqual(finto.ordine.count("memoria"), 1)
        (riga,) = finto.scritte
        self.assertEqual(set(riga), {"calcolato_at", "intervallo_ritardo", "versione",
                                     "riepilogo", "memoria"})
        self.assertEqual((riga["calcolato_at"], riga["intervallo_ritardo"], riga["versione"]),
                         ("2026-10-01T06:05:00Z", "45 minutes", 1))
        self.assertEqual(riepilogo_salute.valida_v1(riga["riepilogo"]), [])
        self.assertEqual(riga["memoria"]["nrestarts"],
                         [["2026-10-01T05:50:00Z", 1], ["2026-10-01T06:05:00Z", 2]])
        self.assertEqual(riga["memoria"]["dal"],
                         {s["codice"]: s["dal"] for s in riga["riepilogo"]["segnali"]})
        # Il nome del servizio e le chiavi di configurazione non escono.
        testo = json.dumps(riga)
        self.assertNotIn("edunews", testo)
        self.assertNotIn("sender", testo)

    def test_exit_zero_anche_con_allarmi(self):
        finto = _DbFinto()
        finto.patch(self)
        fermo = {"active_state": "failed", "sub_state": "failed", "n_restarts": 2}
        with patch.object(sorveglianza, "stato_servizio", return_value=fermo):
            codice = sorveglianza.esegui(adesso=ADESSO, stampa=lambda _riga: None)
        self.assertEqual(codice, 0)
        riepilogo = finto.scritte[0]["riepilogo"]
        self.assertEqual(riepilogo["stato"], "guasto")
        self.assertIn("servizio_non_attivo", [s["codice"] for s in riepilogo["segnali"]])

    def test_db_giu_scrive_se_puo_ed_esce_uno(self):
        # Le misure non arrivano ma la riga si puo' scrivere: il pannello vede
        # «guasto» con `misure_non_disponibili`, il journal un errore, systemd un 1.
        finto = _DbFinto(misure_errore=ConnectionError("rifiutata: apikey=segretissima"))
        registro = MagicMock()
        with patch.object(sorveglianza, "logger", registro):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 1)
        riepilogo = finto.scritte[0]["riepilogo"]
        self.assertEqual(riepilogo["stato"], "guasto")
        self.assertIn("misure_non_disponibili", [s["codice"] for s in riepilogo["segnali"]])
        registro.error.assert_called_once()
        self.assertIn("ConnectionError", str(registro.error.call_args))
        self.assertNotIn("segretissima", str(registro.error.call_args))
        registro.warning.assert_not_called()

    def test_schema_non_leggibile_non_e_la_12_mancante(self):
        finto = _DbFinto(disponibile=None)
        registro = MagicMock()
        with patch.object(sorveglianza, "logger", registro):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 1)
        self.assertEqual(finto.scritte, [])
        registro.error.assert_called_once()
        self.assertNotIn("migrazione 12", str(registro.error.call_args))
        registro.warning.assert_not_called()

    def test_db_giu_e_tabella_assente_esce_uno_senza_parlare_della_12(self):
        finto = _DbFinto(disponibile=False, misure_errore=ConnectionError("giu'"))
        registro = MagicMock()
        with patch.object(sorveglianza, "logger", registro):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 1)
        self.assertEqual(finto.scritte, [])
        registro.warning.assert_not_called()
        registro.error.assert_called_once()

    def test_dry_run_con_il_db_giu_esce_uno(self):
        finto = _DbFinto(misure_errore=ConnectionError("giu'"))
        with patch.object(sorveglianza, "logger", MagicMock()):
            codice, righe = self._esegui(finto, dry_run=True)
        self.assertEqual(codice, 1)
        self.assertEqual(finto.scritte, [])
        self.assertEqual(riepilogo_salute.valida_v1(json.loads(righe[0])), [])

    def test_upsert_fallito_exit_uno(self):
        codice, _ = self._esegui(_DbFinto(scrive=False))
        self.assertEqual(codice, 1)

    def test_errore_interno_exit_uno(self):
        finto = _DbFinto()
        with patch.object(riepilogo_salute, "riepilogo_pannello", side_effect=RuntimeError("x")), \
                patch.object(sorveglianza, "logger", MagicMock()):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 1)
        self.assertEqual(finto.scritte, [])

    def test_dry_run_legge_stampa_e_non_scrive(self):
        finto = _DbFinto()
        codice, righe = self._esegui(finto, dry_run=True)
        self.assertEqual(codice, 0)
        self.assertEqual(finto.scritte, [])
        self.assertNotIn("disponibile", finto.ordine)
        self.assertIn("memoria", finto.ordine)
        stampato = json.loads(righe[0])
        self.assertEqual(riepilogo_salute.valida_v1(stampato), [])
        self.assertTrue(any(r.startswith("sorveglia: codici:") for r in righe))

    def test_senza_la_12_warning_ed_exit_zero(self):
        finto = _DbFinto(disponibile=False)
        registro = MagicMock()
        with patch.object(sorveglianza, "logger", registro):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 0)
        self.assertEqual(finto.scritte, [])
        registro.warning.assert_called_once()

    def test_riepilogo_non_valido_scrive_il_minimo(self):
        finto = _DbFinto(memoria={"nrestarts": [], "dal": {
            "riepilogo_non_valido": "2026-10-01T05:35:00Z"}})
        registro = MagicMock()
        with patch.object(riepilogo_salute, "valida_v1", return_value=["segnali[0].testo non neutro"]), \
                patch.object(sorveglianza, "logger", registro):
            codice, _ = self._esegui(finto)
        self.assertEqual(codice, 0)
        scritto = finto.scritte[0]["riepilogo"]
        self.assertEqual(scritto["stato"], "guasto")
        self.assertEqual([s["codice"] for s in scritto["segnali"]], ["riepilogo_non_valido"])
        self.assertEqual(scritto["segnali"][0]["dal"], "2026-10-01T05:35:00Z")
        # Il dettaglio va solo nel journal.
        self.assertIn("non neutro", str(registro.warning.call_args))
        self.assertNotIn("non neutro", json.dumps(finto.scritte[0]))

    def test_memoria_illeggibile_nessun_errore(self):
        finto = _DbFinto(memoria=None)
        codice, _ = self._esegui(finto)
        self.assertEqual(codice, 0)
        self.assertEqual(finto.scritte[0]["memoria"]["nrestarts"], [["2026-10-01T06:05:00Z", 2]])


class NessunaRete(unittest.TestCase):
    def test_nessun_client_di_rete(self):
        albero = ast.parse((APP / "sorveglianza.py").read_text(encoding="utf-8"))
        importati = set()
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Import):
                importati.update(a.name.split(".")[0] for a in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
                importati.add(nodo.module.split(".")[0])
        for vietato in ("httpx", "requests", "smtplib", "urllib", "socket", "telegram",
                        "aiohttp", "http"):
            self.assertNotIn(vietato, importati)


class Cli(unittest.TestCase):
    def test_sorveglia_e_il_dry_run(self):
        with patch.object(sorveglianza, "esegui", return_value=0) as esegui, \
                patch.object(cli, "logger", MagicMock()):
            self.assertEqual(cli.main(["sorveglia", "--dry-run"]), 0)
            esegui.assert_called_once_with(dry_run=True)
        with patch.object(sorveglianza, "esegui", return_value=1) as esegui, \
                patch.object(cli, "logger", MagicMock()):
            self.assertEqual(cli.main(["sorveglia"]), 1)
            esegui.assert_called_once_with(dry_run=False)

    def test_salute_stampa_i_codici(self):
        uscita, errori = io.StringIO(), io.StringIO()
        with patch.object(cli, "_stato_salute", return_value=telemetria.Stato(login_oe_ok=False)), \
                contextlib.redirect_stdout(uscita), contextlib.redirect_stderr(errori):
            codice = cli.main(["salute"])
        self.assertEqual(codice, 1)
        self.assertIn("salute: codici: accesso_fonte_riservata (allarme)", uscita.getvalue())

    def test_salute_sana_nessun_codice(self):
        uscita = io.StringIO()
        with patch.object(cli, "_stato_salute", return_value=telemetria.Stato()), \
                contextlib.redirect_stdout(uscita):
            cli.main(["salute"])
        self.assertIn("salute: codici: nessuno", uscita.getvalue())


if __name__ == "__main__":
    unittest.main()
