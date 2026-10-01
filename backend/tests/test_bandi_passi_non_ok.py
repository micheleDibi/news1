# -*- coding: utf-8 -*-
"""`passi_non_ok` nella riga `pipeline` (contratto `bandi-giro-2` §11).

La sorveglianza deve poter dire «lo stesso passo non e' andato due giri di
fila», e il contatore `errori` non dice quale. `_passi_non_ok` da' i nomi veri
degli step, ordinati, senza il testo dell'errore: la riga finisce nel
riepilogo per il pannello, e un messaggio d'eccezione puo' portarsi dietro
host, URL o chiavi.

`bandi_pipeline.py` importa i runner di `scraper_bandi` (loguru, supabase), che
il python di sistema non ha: la funzione pura si estrae dall'AST e si esegue
qui, e il collegamento in `_registra` si verifica sull'AST.

    cd backend && python3 -m unittest tests.test_bandi_passi_non_ok
"""

import ast
import unittest
from pathlib import Path

_PIPELINE = Path(__file__).resolve().parents[1] / "app" / "bandi_pipeline.py"
_ALBERO = ast.parse(_PIPELINE.read_text(encoding="utf-8"))


def _funzione(nome: str):
    nodo = next(n for n in _ALBERO.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    spazio: dict = {"Any": object}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), str(_PIPELINE), "exec"), spazio)
    return spazio[nome], nodo


passi_non_ok, _ = _funzione("_passi_non_ok")


class TestPassiNonOk(unittest.TestCase):
    def test_tutti_ok(self):
        stato = {"steps": {"discover": {"status": "ok"}, "seo": {"status": "ok", "counters": {}}}}
        self.assertEqual(passi_non_ok(stato), [])

    def test_nomi_veri_ordinati(self):
        stato = {"steps": {
            "seo": {"status": "error", "error": "boom"},
            "discover": {"status": "ok"},
            "enrich": {"status": "error", "error_type": "RuntimeError"},
            "monitor": {"status": "ok", "saltato": "giro_non_previsto"},
        }}
        self.assertEqual(passi_non_ok(stato), ["enrich", "seo"])

    def test_senza_status_o_malformato_non_e_ok(self):
        """Stesso criterio di `errori` in `_registra`: solo `ok` e' ok."""
        stato = {"steps": {"resolver": {"saltato": "modulo_rotto"}, "scrape": None}}
        self.assertEqual(passi_non_ok(stato), ["resolver", "scrape"])

    def test_nessun_testo_d_errore(self):
        stato = {"steps": {"scrape": {
            "status": "error",
            "error": "ConnectError https://esempio.invalid/?apikey=segreta",
        }}}
        uscita = passi_non_ok(stato)
        self.assertEqual(uscita, ["scrape"])
        self.assertNotIn("segreta", repr(uscita))

    def test_giro_saltato_per_lock_e_stati_strani(self):
        self.assertEqual(passi_non_ok({"steps": {}}), [])
        self.assertEqual(passi_non_ok({}), [])
        self.assertEqual(passi_non_ok({"steps": None}), [])
        self.assertEqual(passi_non_ok(None), [])


class TestCollegamento(unittest.TestCase):
    def test_registra_scrive_passi_non_ok_dentro_il_try(self):
        registra = next(n for n in _ALBERO.body
                        if isinstance(n, ast.FunctionDef) and n.name == "_registra")
        prova = next(n for n in registra.body if isinstance(n, ast.Try))
        assegnazioni = [
            n for n in ast.walk(ast.Module(body=prova.body, type_ignores=[]))
            if isinstance(n, ast.Assign)
            and ast.unparse(n.targets[0]) == "contatori['passi_non_ok']"
        ]
        self.assertEqual(len(assegnazioni), 1)
        self.assertEqual(ast.unparse(assegnazioni[0].value), "_passi_non_ok(state)")
        # Il try di `_registra` cattura Exception: la telemetria non fa mai
        # fallire un giro.
        self.assertTrue(any(ast.unparse(h.type) == "Exception" for h in prova.handlers))

    def test_il_passo_verifica_stato_c_e(self):
        """Col percorso A (§19.10) il passo esiste: i suoi nomi entrano in `passi_non_ok`.

        L'ordine e le condizioni stanno in `test_bandi_verifica_stato`.
        """
        testo = _PIPELINE.read_text(encoding="utf-8")
        self.assertIn('state["steps"]["verifica_stato"]', testo)
        self.assertIn('state["steps"]["verifica_stato_ingresso"]', testo)


if __name__ == "__main__":
    unittest.main()
