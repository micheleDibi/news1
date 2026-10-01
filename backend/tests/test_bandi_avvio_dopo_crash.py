# -*- coding: utf-8 -*-
"""Avvio del sender dopo un crash e uscita 1 (contratto `bandi-giro-2` §11).

- Se all'avvio `rilascia_lock_orfani` rilascia il lock del giro, il processo
  precedente e' morto a meta' giro: il giro di boot NON parte, si scrive una
  riga `pipeline_run` con `riavvio_dopo_crash` e parte lo scheduler. Cosi' un
  giro che fa cadere il processo non diventa un ciclo di riavvii.
- Un errore fatale dello scheduler esce con 1, perche' systemd
  (`Restart=on-failure`) lo riavvii: prima usciva con 0 e il sender restava giu'.
- Nessuna notifica: il docstring del sender («no Telegram/email per scelta
  utente») resta, e il sender non importa niente che parli con la rete.

Sender e pipeline si portano dietro `schedule`, loguru e supabase, che il python
di sistema non ha: le funzioni pure si estraggono dall'AST e si eseguono qui
con collaboratori finti; il `__main__` del sender si verifica sull'AST.

    cd backend && python3 -m unittest tests.test_bandi_avvio_dopo_crash
"""

import ast
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_PIPELINE = ast.parse((_APP / "bandi_pipeline.py").read_text(encoding="utf-8"))
_SENDER_TESTO = (_APP / "bandi_sender.py").read_text(encoding="utf-8")
_SENDER = ast.parse(_SENDER_TESTO)


def _costante(albero: ast.Module, nome: str):
    for nodo in albero.body:
        bersagli = []
        if isinstance(nodo, ast.Assign):
            bersagli = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            bersagli = [nodo.target.id]
        if nome in bersagli:
            return ast.literal_eval(nodo.value)
    raise LookupError(nome)


def _funzione(nome: str, **spazio):
    nodo = next(n for n in _PIPELINE.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    ambiente = {"Any": object, **spazio}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), "bandi_pipeline.py", "exec"), ambiente)
    return ambiente[nome]


LOCK_PIPELINE = _costante(_PIPELINE, "LOCK_PIPELINE")
MOTIVO = _costante(_PIPELINE, "MOTIVO_RIAVVIO_DOPO_CRASH")
lock_del_giro_rilasciato = _funzione("lock_del_giro_rilasciato", LOCK_PIPELINE=LOCK_PIPELINE)


def _voce(nome, proprietario="x@4100"):
    return {"nome": nome, "proprietario": proprietario, "motivo": "processo morto"}


class TestLockDelGiro(unittest.TestCase):
    def test_nomi(self):
        self.assertEqual(LOCK_PIPELINE, "bandi_pipeline")
        self.assertEqual(MOTIVO, "riavvio_dopo_crash")

    def test_rilasciato_il_lock_del_giro(self):
        esito = {"letti": 2, "rilasciati": [_voce("bandi_resolver"), _voce("bandi_pipeline")],
                 "falliti": [], "errore": ""}
        self.assertTrue(lock_del_giro_rilasciato(esito))

    def test_altri_lock_o_rilascio_fallito_non_bastano(self):
        casi = [
            {"rilasciati": [_voce("bandi_resolver"), _voce("monitor")], "falliti": []},
            # Il rilascio fallito lascia il lock preso: il boot si salta da solo per lock.
            {"rilasciati": [], "falliti": [_voce("bandi_pipeline")]},
            {"letti": 0, "rilasciati": [], "falliti": [], "errore": "rete giu'"},
            {},
            None,
            {"rilasciati": None},
            {"rilasciati": "bandi_pipeline"},
            {"rilasciati": ["bandi_pipeline"]},
        ]
        for esito in casi:
            with self.subTest(esito=esito):
                self.assertFalse(lock_del_giro_rilasciato(esito))


class _Riga:
    def __init__(self, **campi):
        self.__dict__.update(campi)


class _Telemetria:
    """`telemetria` finta: registra la riga costruita e quella scritta."""

    def __init__(self, scrittura_rotta=False):
        self.scritte: list = []
        self.esiti: list = []
        self._rotta = scrittura_rotta
        telemetria = self

        class PipelineRun:
            def __init__(self, step, giro=None):
                self.step, self.giro = step, giro

            def concludi(self, **campi):
                return _Riga(step=self.step, giro=self.giro, **campi)

        self.PipelineRun = PipelineRun

        def esito_da_contatori(**kwargs):
            telemetria.esiti.append(kwargs)
            return "saltato" if kwargs.get("saltato_per_lock") else "ok"

        def scrivi_pipeline_run(riga):
            if telemetria._rotta:
                raise RuntimeError("pipeline_run non raggiungibile")
            telemetria.scritte.append(riga)

        self.esito_da_contatori = esito_da_contatori
        self.scrivi_pipeline_run = scrivi_pipeline_run


class _Logger:
    def __init__(self):
        self.avvisi: list = []

    def warning(self, messaggio, *argomenti):
        self.avvisi.append(messaggio.format(*argomenti))


class TestRegistraAvvioSaltato(unittest.TestCase):
    def _registra(self, telemetria, logger=None):
        return _funzione("registra_avvio_saltato", _telemetria=telemetria,
                         logger=logger or _Logger(), MOTIVO_RIAVVIO_DOPO_CRASH=MOTIVO)

    def test_riga_del_boot_saltato(self):
        telemetria = _Telemetria()
        self._registra(telemetria)(giro="boot")
        self.assertEqual(len(telemetria.scritte), 1)
        riga = telemetria.scritte[0]
        self.assertEqual((riga.step, riga.giro), ("pipeline", "boot"))
        self.assertEqual(riga.contatori, {"riavvio_dopo_crash": 1})
        self.assertEqual(riga.esito, "saltato")
        self.assertEqual(telemetria.esiti, [{"saltato_per_lock": True}])
        self.assertEqual(riga.durata_s, 0.0)

    def test_giro_predefinito_e_motivo(self):
        telemetria = _Telemetria()
        self._registra(telemetria)("altro_motivo")
        riga = telemetria.scritte[0]
        self.assertEqual(riga.giro, "boot")
        self.assertEqual(riga.contatori, {"altro_motivo": 1})

    def test_non_solleva_mai(self):
        logger = _Logger()
        self._registra(_Telemetria(scrittura_rotta=True), logger)()
        self.assertEqual(len(logger.avvisi), 1)
        self.assertIn("non registrato", logger.avvisi[0])


class TestAvvioDelSender(unittest.TestCase):
    def setUp(self):
        self.principale = next(
            n for n in _SENDER.body
            if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test))
        self.prova = next(n for n in self.principale.body if isinstance(n, ast.Try))

    @staticmethod
    def _chiamate(nodi):
        return [ast.unparse(n.func) for nodo in nodi for n in ast.walk(nodo)
                if isinstance(n, ast.Call)]

    def test_boot_saltato_se_il_lock_del_giro_e_stato_rilasciato(self):
        corpo = self.prova.body
        ramo = next(n for n in corpo if isinstance(n, ast.If)
                    and "lock_del_giro_rilasciato" in ast.unparse(n.test))
        indice = corpo.index(ramo)
        # Il rilascio viene prima del ramo, lo scheduler dopo e in entrambi i casi.
        self.assertIn("rilascia_lock_orfani", self._chiamate(corpo[:indice]))
        self.assertIn("schedule_bandi_pipeline", self._chiamate(corpo[indice + 1:]))
        self.assertNotIn("schedule_bandi_pipeline", self._chiamate([ramo]))
        # Nel ramo del crash: la riga, e nessun giro.
        self.assertIn("registra_avvio_saltato", self._chiamate(ramo.body))
        self.assertNotIn("_run_sync", self._chiamate(ramo.body))
        chiamata = next(n for nodo in ramo.body for n in ast.walk(nodo)
                        if isinstance(n, ast.Call) and ast.unparse(n.func) == "registra_avvio_saltato")
        self.assertEqual({k.arg: ast.unparse(k.value) for k in chiamata.keywords},
                         {"giro": "GIRO_BOOT"})
        # Altrimenti il giro di boot, come prima.
        self.assertIn("_run_sync", self._chiamate(ramo.orelse))
        self.assertNotIn("registra_avvio_saltato", self._chiamate(ramo.orelse))
        # Il ramo guarda l'esito del rilascio, non una variabile qualsiasi.
        self.assertEqual(ast.unparse(ramo.test), "lock_del_giro_rilasciato(orfani)")
        assegnato = [n for n in ast.walk(ast.Module(body=corpo[:indice], type_ignores=[]))
                     if isinstance(n, ast.Assign) and ast.unparse(n.value) == "rilascia_lock_orfani()"]
        self.assertEqual([ast.unparse(a.targets[0]) for a in assegnato], ["orfani"])

    def test_errore_fatale_esce_con_uno(self):
        gestori = {ast.unparse(h.type): h for h in self.prova.handlers}
        fatale = gestori["Exception"]
        self.assertEqual(ast.unparse(fatale.body[0]),
                         "logger.exception('[bandi_sender] Errore fatale: {}', e)")
        self.assertIsInstance(fatale.body[-1], ast.Raise)
        self.assertEqual(ast.unparse(fatale.body[-1].exc), "SystemExit(1)")
        # Ctrl-C resta un'uscita pulita.
        interruzione = gestori["KeyboardInterrupt"]
        self.assertFalse(any(isinstance(n, ast.Raise) for n in ast.walk(interruzione)))

    def test_nessuna_notifica(self):
        self.assertIn("no Telegram/email per scelta utente", ast.get_docstring(_SENDER))
        importati = set()
        for nodo in ast.walk(_SENDER):
            if isinstance(nodo, ast.Import):
                importati.update(a.name.split(".")[0] for a in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                importati.add(nodo.module.split(".")[0])
        for vietato in ("httpx", "requests", "smtplib", "urllib", "telegram", "aiohttp"):
            self.assertNotIn(vietato, importati)


if __name__ == "__main__":
    unittest.main()
