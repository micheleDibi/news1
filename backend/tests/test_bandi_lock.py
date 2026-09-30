# -*- coding: utf-8 -*-
"""Lock orfani all'avvio del sender dei bandi (contratto di ottobre, §8).

`backend/app/lock_orfani.py` e' puro e gira con il python di sistema, come
questi test. `bandi_pipeline.py` e `bandi_sender.py` invece importano i runner
di `scraper_bandi` e `schedule`, che qui non ci sono: di loro si verifica con
l'AST che il sender rilasci i lock PRIMA del giro di boot, e che il rilascio
passi dalla RPC e mai da un DELETE.

    cd backend && python3 -m unittest discover -s tests -t .
"""

import ast
import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

_RADICE = Path(__file__).resolve().parents[2]

# Stesso pacchetto finto di test_sanifica: su questa macchina esiste un altro
# package chiamato `app` sul sys.path (vedi CLAUDE.md).
_PACCHETTO = "edunews_app_test"
if _PACCHETTO not in sys.modules:
    _finto = types.ModuleType(_PACCHETTO)
    _finto.__path__ = [str(_RADICE / "backend" / "app")]
    sys.modules[_PACCHETTO] = _finto

lock_orfani = importlib.import_module(_PACCHETTO + ".lock_orfani")

AVVIO = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
PRIMA = "2026-09-30T10:00:00.87927+00:00"          # frazione a cinque cifre, come PostgREST
DOPO = "2026-09-30T12:00:05+00:00"
PID_CORRENTE = 5000
MORTI = {4100, 4200}


def vivo(pid):
    return pid not in MORTI


def lock(nome, proprietario, acquisito_at=PRIMA):
    return {"nome": nome, "proprietario": proprietario, "acquisito_at": acquisito_at,
            "scade_at": "2026-09-30T16:00:00+00:00"}


def orfani(righe, **opzioni):
    parametri = dict(pid_corrente=PID_CORRENTE, avvio=AVVIO, vivo=vivo)
    parametri.update(opzioni)
    return [(o.nome, o.proprietario) for o in lock_orfani.orfani(righe, **parametri)]


class Registro:
    def __init__(self):
        self.righe = []

    def warning(self, messaggio):
        self.righe.append(("warning", messaggio))

    def info(self, messaggio):
        self.righe.append(("info", messaggio))


class TestRegole(unittest.TestCase):
    def test_pipeline_e_resolver_di_un_processo_morto(self):
        righe = [lock("bandi_pipeline", "bandi_pipeline@4100"),
                 lock("bandi_resolver", "resolver@4200")]
        self.assertEqual(orfani(righe), [("bandi_pipeline", "bandi_pipeline@4100"),
                                         ("bandi_resolver", "resolver@4200")])

    def test_processo_vivo_non_si_tocca(self):
        righe = [lock("bandi_pipeline", "bandi_pipeline@4300"),
                 lock("bandi_resolver", "resolver@4300")]
        self.assertEqual(orfani(righe), [])

    def test_il_pid_corrente_non_si_tocca_mai(self):
        righe = [lock("bandi_pipeline", f"bandi_pipeline@{PID_CORRENTE}")]
        self.assertEqual(orfani(righe, vivo=lambda pid: False), [])

    def test_monitor_preso_prima_dell_avvio_senza_giri_vivi(self):
        righe = [lock("monitor", "monitor:06:00"),
                 lock("bandi_pipeline", "bandi_pipeline@4100")]
        self.assertEqual(orfani(righe), [("monitor", "monitor:06:00"),
                                         ("bandi_pipeline", "bandi_pipeline@4100")])

    def test_monitor_preso_dopo_l_avvio_resta(self):
        self.assertEqual(orfani([lock("monitor", "monitor:18:00", DOPO)]), [])

    def test_monitor_di_un_altro_sender_vivo_resta(self):
        righe = [lock("monitor", "monitor:06:00"),
                 lock("bandi_pipeline", "bandi_pipeline@4300")]      # vivo
        self.assertEqual(orfani(righe), [])

    def test_monitor_senza_data_leggibile_resta(self):
        self.assertEqual(orfani([lock("monitor", "monitor:06:00", "ieri")]), [])
        self.assertEqual(orfani([lock("monitor", "monitor:06:00", None)]), [])

    def test_i_cli_non_si_toccano_mai(self):
        righe = [lock("monitor", "monitor:cli"),
                 lock("monitor", "applica-eventi:cli"),
                 lock("bandi_pipeline", "seo-rigenera:cli")]
        self.assertEqual(orfani(righe, vivo=lambda pid: False), [])

    def test_formati_sconosciuti_non_si_toccano(self):
        righe = [lock("bandi_pipeline", "qualcuno"),
                 lock("bandi_pipeline", "bandi_pipeline@abc"),
                 lock("altro", "resolver@"),
                 lock("", "resolver@4100"),
                 {"nome": "monitor"}]
        self.assertEqual(orfani(righe, vivo=lambda pid: False), [])

    def test_istante_di_postgrest(self):
        self.assertEqual(lock_orfani.istante("2026-09-30T10:00:00.87927+00:00"),
                         datetime(2026, 9, 30, 10, 0, 0, 879270, tzinfo=timezone.utc))
        self.assertEqual(lock_orfani.istante("2026-09-30T10:00:00Z"),
                         datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(lock_orfani.istante("2026-09-30 10:00:00"),
                         datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc))
        self.assertIsNone(lock_orfani.istante("non una data"))

    def test_pid_enorme_vale_vivo_e_non_solleva(self):
        # Revisione avversaria S4: os.kill con un pid oltre 2**31 solleva
        # OverflowError, che non e' un OSError.
        self.assertTrue(lock_orfani.pid_vivo(2 ** 40))
        self.assertEqual(orfani([lock("bandi_pipeline", f"bandi_pipeline@{2 ** 40}")],
                                vivo=lock_orfani.pid_vivo), [])

    def test_la_docstring_dice_il_rischio_del_mac_per_entrambi(self):
        documento = " ".join((lock_orfani.__doc__ or "").split())
        self.assertIn("`resolver@<pid>`", documento)
        self.assertIn("`bandi_pipeline@<pid>`", documento)
        self.assertIn("Mac", documento)

    def test_pid_vivo_del_processo_stesso(self):
        import os
        self.assertTrue(lock_orfani.pid_vivo(os.getpid()))
        self.assertFalse(lock_orfani.pid_vivo(0))


class TestRilascio(unittest.TestCase):
    def _rilascia(self, righe, rilascia=None, leggi=None):
        registro = Registro()
        chiamate = []

        def rilascia_predefinito(nome, proprietario):
            chiamate.append((nome, proprietario))
            return True

        esito = lock_orfani.rilascia_orfani(
            leggi=leggi or (lambda: righe), rilascia=rilascia or rilascia_predefinito,
            pid_corrente=PID_CORRENTE, avvio=AVVIO, vivo=vivo, registro=registro,
        )
        return esito, chiamate, registro

    def test_rilascia_con_la_funzione_data_e_scrive_nel_journal(self):
        righe = [lock("bandi_pipeline", "bandi_pipeline@4100"),
                 lock("monitor", "monitor:cli")]
        esito, chiamate, registro = self._rilascia(righe)
        self.assertEqual(chiamate, [("bandi_pipeline", "bandi_pipeline@4100")])
        self.assertEqual(esito["letti"], 2)
        self.assertEqual([v["proprietario"] for v in esito["rilasciati"]], ["bandi_pipeline@4100"])
        avvisi = [m for livello, m in registro.righe if livello == "warning"]
        self.assertEqual(len(avvisi), 1)
        self.assertIn("bandi_pipeline@4100", avvisi[0])
        self.assertIn("processo 4100 non piu' vivo", avvisi[0])
        self.assertIn("1 lock orfani rilasciati", registro.righe[-1][1])

    def test_lettura_fallita_nessun_rilascio_e_nessuna_eccezione(self):
        def leggi():
            raise RuntimeError("PostgREST giu'")

        esito, chiamate, registro = self._rilascia([], leggi=leggi)
        self.assertEqual(chiamate, [])
        self.assertIn("PostgREST giu'", esito["errore"])
        self.assertIn("non leggibile", registro.righe[0][1])

    def test_rilascio_fallito_si_conta_e_si_prosegue(self):
        def rilascia(nome, proprietario):
            if proprietario == "resolver@4200":
                raise RuntimeError("5xx")
            return nome == "bandi_pipeline"

        righe = [lock("bandi_resolver", "resolver@4200"),
                 lock("bandi_pipeline", "bandi_pipeline@4100"),
                 lock("monitor", "monitor:06:00")]
        esito, _c, _r = self._rilascia(righe, rilascia=rilascia)
        self.assertEqual([v["proprietario"] for v in esito["rilasciati"]], ["bandi_pipeline@4100"])
        self.assertEqual(sorted(v["proprietario"] for v in esito["falliti"]),
                         ["monitor:06:00", "resolver@4200"])
        self.assertIn("5xx", esito["falliti"][0].get("errore", "") + esito["falliti"][1].get("errore", ""))


class TestCollegamenti(unittest.TestCase):
    """Sender e pipeline non si importano qui (schedule, supabase): AST."""

    def _albero(self, nome):
        return ast.parse((_RADICE / "backend" / "app" / nome).read_text(encoding="utf-8"))

    def test_il_sender_rilascia_prima_del_giro_di_boot(self):
        albero = self._albero("bandi_sender.py")
        principale = next(
            n for n in albero.body
            if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)
        )
        chiamate = [
            (n.lineno, ast.unparse(n.func)) for n in ast.walk(principale)
            if isinstance(n, ast.Call)
        ]
        riga_rilascio = min(r for r, f in chiamate if f == "rilascia_lock_orfani")
        riga_boot = min(r for r, f in chiamate if f == "_run_sync")
        self.assertLess(riga_rilascio, riga_boot)

    def test_la_pipeline_rilascia_con_la_rpc_e_mai_con_delete(self):
        albero = self._albero("bandi_pipeline.py")
        funzione = next(n for n in albero.body
                        if isinstance(n, ast.FunctionDef) and n.name == "rilascia_lock_orfani")
        testo = ast.unparse(funzione)
        # La RPC si chiama direttamente per leggerne il risultato (#27 P2):
        # `blocco.rilascia` dice True anche quando non ha cancellato niente.
        self.assertIn(".rpc(_blocco.RPC_RILASCIA", testo)
        self.assertIn("_valore_rpc(risposta)", testo)
        self.assertNotIn("_blocco.rilascia(", testo)
        self.assertIn("_lock_orfani.rilascia_orfani", testo)
        self.assertIn("os.getpid()", testo)
        modulo = (_RADICE / "backend" / "app" / "lock_orfani.py").read_text(encoding="utf-8")
        for sorgente in (testo, modulo):
            self.assertNotIn(".delete(", sorgente.lower())
            self.assertNotIn("delete from", sorgente.lower())


def _funzione_pura(file: str, nome: str):
    """Estrae una funzione pura dal sorgente e la esegue qui, senza importare
    il modulo (che si porta dietro supabase e i runner)."""
    albero = ast.parse((_RADICE / "backend" / "app" / file).read_text(encoding="utf-8"))
    nodo = next(n for n in albero.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    spazio: dict = {"Any": object}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), file, "exec"), spazio)
    return spazio[nome]


class TestValoreRpc(unittest.TestCase):
    """Il journal dice «rilasciato» solo se `lock_rilascia` ha cancellato."""

    def test_le_forme_della_risposta(self):
        valore_rpc = _funzione_pura("bandi_pipeline.py", "_valore_rpc")
        casi = [
            (types.SimpleNamespace(data=True), True),
            (types.SimpleNamespace(data=False), False),
            (types.SimpleNamespace(data=[True]), True),
            (types.SimpleNamespace(data=[]), False),
            (types.SimpleNamespace(data=[{"lock_rilascia": False}]), False),
            (types.SimpleNamespace(data={"lock_rilascia": True}), True),
            (types.SimpleNamespace(data=None), False),
            (types.SimpleNamespace(data="true"), True),
            (True, True),
        ]
        for risposta, atteso in casi:
            with self.subTest(risposta=risposta):
                self.assertIs(valore_rpc(risposta), atteso)

    def test_un_rilascio_a_vuoto_e_un_fallimento_nel_journal(self):
        registro = Registro()
        esito = lock_orfani.rilascia_orfani(
            leggi=lambda: [lock("bandi_pipeline", "bandi_pipeline@4100")],
            rilascia=lambda nome, proprietario: False,        # la RPC ha detto false
            pid_corrente=PID_CORRENTE, avvio=AVVIO, vivo=vivo, registro=registro,
        )
        self.assertEqual(esito["rilasciati"], [])
        self.assertEqual(len(esito["falliti"]), 1)
        self.assertTrue(any("non riuscito" in m for _l, m in registro.righe))


if __name__ == "__main__":
    unittest.main()
