# -*- coding: utf-8 -*-
"""I passi del giro 2 e del giro 3 nella pipeline dei bandi (contratti
`bandi-giro-2` §11, §19.10 e `bandi-giro-3` §2).

Sull'AST di `backend/app/bandi_pipeline.py` (il python di sistema non ha i
runner di `scraper_bandi`): l'ordine e le condizioni dei passi, nessun lock
nuovo, la whitelist azzerata a inizio giro. Il comportamento con i moduli finti
sta in `scraper_bandi/tests/test_orchestrazione_pipeline.py`.

    cd backend && python3 -m unittest tests.test_bandi_verifica_stato
"""

import ast
import functools
import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

_PIPELINE = Path(__file__).resolve().parents[1] / "app" / "bandi_pipeline.py"

# `lock_orfani` e' puro: si importa per percorso sotto il pacchetto finto dei
# test del backend (vedi test_bandi_lock), per dare a `domini_dovuto` il suo
# `istante`.
_PACCHETTO = "edunews_app_test"
if _PACCHETTO not in sys.modules:
    _finto = types.ModuleType(_PACCHETTO)
    _finto.__path__ = [str(_PIPELINE.parent)]
    sys.modules[_PACCHETTO] = _finto
lock_orfani = importlib.import_module(_PACCHETTO + ".lock_orfani")
_ALBERO = ast.parse(_PIPELINE.read_text(encoding="utf-8"))


def _funzione(nome: str) -> ast.AST:
    return next(n for n in _ALBERO.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nome)


def _assegnazioni_degli_step(nodo: ast.AST) -> list[tuple[int, str, ast.AST]]:
    """(riga, nome dello step, nodo) per ogni `state["steps"]["<nome>"] = …`."""
    trovate = []
    for n in ast.walk(nodo):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript):
            testo = ast.unparse(n.targets[0])
            if testo.startswith("state['steps']['"):
                trovate.append((n.lineno, testo.split("'")[3], n))
    return sorted(trovate, key=lambda t: t[0])


def _prima_riga(passi, nome: str) -> int:
    return min(riga for riga, passo, _ in passi if passo == nome)


def _condizione_di(nodo_corpo: ast.AST, riga: int) -> str:
    """Il test dell'`if` piu' interno che contiene la riga, o ''."""
    migliore, testo = None, ""
    for n in ast.walk(nodo_corpo):
        if isinstance(n, ast.If) and n.lineno <= riga <= (n.end_lineno or n.lineno):
            dentro = any(riga >= c.lineno and riga <= (c.end_lineno or c.lineno) for c in n.body)
            if dentro and (migliore is None or n.lineno > migliore):
                migliore, testo = n.lineno, ast.unparse(n.test)
    return testo


class TestOrdineECondizioni(unittest.TestCase):
    def setUp(self):
        self.corpo = _funzione("run_bandi_pipeline")
        self.passi = _assegnazioni_degli_step(self.corpo)

    def test_ordine(self):
        # L'ordine del giro 3 (§2): ogni passo dopo il precedente.
        ordine = ["discover", "scrape", "domini", "resolver_precoce", "preprocess",
                  "enrich", "resolver", "ricontrolli", "verifica_stato_ingresso", "seo",
                  "link_verifica", "rielaborazione", "monitor", "verifica_stato", "gemelli"]
        righe = [_prima_riga(self.passi, nome) for nome in ordine]
        self.assertEqual(righe, sorted(righe))
        self.assertEqual(sorted({passo for _, passo, _ in self.passi}), sorted(ordine))

    def test_condizioni(self):
        condizione = lambda nome: _condizione_di(  # noqa: E731
            self.corpo, _prima_riga(self.passi, nome))
        # La manutenzione (8, 11-15) solo nei giri di MONITOR_GIRI; i gemelli
        # non piu' solo alle 06 (giro 3, §2).
        for nome in ("ricontrolli", "link_verifica", "rielaborazione", "monitor",
                     "verifica_stato", "gemelli"):
            with self.subTest(passo=nome):
                self.assertEqual(condizione(nome), "_giro_previsto(giro)")
        self.assertIn("_import_domini_dovuto()", condizione("domini"))
        # La catena d'ingresso gira in ogni giro: nessun if intorno.
        for nome in ("resolver_precoce", "preprocess", "enrich", "resolver",
                     "verifica_stato_ingresso", "seo"):
            with self.subTest(passo=nome):
                self.assertEqual(condizione(nome), "")

    def test_i_passi_chiamano_i_moduli_giusti(self):
        chiamate: dict[str, str] = {}
        for _, passo, nodo in self.passi:          # la prima: il ramo che esegue il passo
            chiamate.setdefault(passo, ast.unparse(nodo.value))
        self.assertIn("'app.verifica_stato'", chiamate["verifica_stato"])
        self.assertIn("fase='controlli'", chiamate["verifica_stato"])
        self.assertIn("rigenerazione=_rigenerazione_di_produzione(per_verifica=True)",
                      chiamate["verifica_stato"])
        self.assertIn("rigenerazione=_rigenerazione_di_produzione()", chiamate["monitor"])
        self.assertIn("fase='ingresso'", chiamate["verifica_stato_ingresso"])
        self.assertIn("funzione='esegui_passo'", chiamate["gemelli"])
        # Le tre passate del resolver (giro 3, §2): i ricontrolli senza limit.
        self.assertIn("modo='precoce'", chiamate["resolver_precoce"])
        self.assertIn("modo='nuovi'", chiamate["resolver"])
        self.assertIn("modo='ricontrolli'", chiamate["ricontrolli"])
        self.assertNotIn("limit", chiamate["ricontrolli"])
        self.assertIn("funzione='run_link_verifica'", chiamate["link_verifica"])
        self.assertIn("'app.rielabora_fonte'", chiamate["rielaborazione"])
        domini = [ast.unparse(n.value) for _, passo, n in self.passi if passo == "domini"]
        self.assertTrue(any("funzione='run_domini_import'" in c and "scarica_enti=True" in c
                            for c in domini))

    def test_nessun_lock_nuovo(self):
        acquisizioni = [ast.unparse(n) for n in ast.walk(_ALBERO)
                        if isinstance(n, ast.Call) and ast.unparse(n.func) == "_blocco.acquisisci"]
        self.assertEqual(acquisizioni, ["_blocco.acquisisci(LOCK_PIPELINE, proprietario, LOCK_TTL_S)"])

    def test_la_whitelist_si_azzera_a_inizio_giro(self):
        chiamate = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(self.corpo)
                    if isinstance(n, ast.Call)]
        azzera = min(r for r, f in chiamate if f == "_azzera_tabella_domini")
        svuota = min(r for r, f in chiamate if f == "_scarico.svuota")
        self.assertLess(svuota, azzera)
        self.assertLess(azzera, _prima_riga(self.passi, "discover"))


class TestDominiDovuto(unittest.TestCase):
    def setUp(self):
        nodi = [n for n in _ALBERO.body
                if (isinstance(n, ast.FunctionDef) and n.name == "domini_dovuto")
                or (isinstance(n, ast.Assign) and ast.unparse(n.targets[0]).startswith(
                    "ESITI_IMPORT_FATTO"))
                or (isinstance(n, ast.AnnAssign) and ast.unparse(n.target).startswith(
                    "ESITI_IMPORT_FATTO"))]
        spazio: dict = {"Any": object, "datetime": datetime, "_lock_orfani": lock_orfani}
        exec(compile(ast.Module(body=nodi, type_ignores=[]), str(_PIPELINE), "exec"), spazio)
        self.dovuto = spazio["domini_dovuto"]
        self.adesso = datetime(2026, 10, 15, 6, 0, tzinfo=timezone(timedelta(hours=2)))

    def test_ombra_e_attivo(self):
        ombra = [{"avviato_at": "2026-10-01T04:00:00Z", "esito": "ombra"}]
        self.assertFalse(self.dovuto(self.adesso, ombra, False))
        self.assertTrue(self.dovuto(self.adesso, ombra, True))
        ok = [{"avviato_at": "2026-10-01T04:00:00+00:00", "esito": "ok"}]
        self.assertFalse(self.dovuto(self.adesso, ok, True))

    def test_frazioni_a_cinque_cifre_di_postgrest(self):
        """Su Python 3.10 `fromisoformat` non le legge: l'import ripartirebbe ogni mattina."""
        riga = [{"avviato_at": "2026-10-01T04:00:12.87927+00:00", "esito": "ok"}]
        self.assertFalse(self.dovuto(self.adesso, riga, True))
        self.assertTrue(self.dovuto(self.adesso, [{"avviato_at": "boh", "esito": "ok"}], True))

    def test_non_usa_fromisoformat(self):
        testo = ast.unparse(_funzione("domini_dovuto"))
        self.assertIn("_lock_orfani.istante(", testo)
        self.assertNotIn("fromisoformat", testo)

    def test_mese_nuovo_e_fallito(self):
        self.assertTrue(self.dovuto(self.adesso, [], False))
        settembre = [{"avviato_at": "2026-09-30T04:00:00Z", "esito": "ok"}]
        self.assertTrue(self.dovuto(self.adesso, settembre, True))
        fallito = [{"avviato_at": "2026-10-14T04:00:00Z", "esito": "anomalo"}]
        self.assertTrue(self.dovuto(self.adesso, fallito, False))


def _esegui(*nomi: str, **spazio: Any) -> dict:
    """Le funzioni e gli assegnamenti di modulo `nomi`, eseguiti da soli."""
    nodi = []
    for n in _ALBERO.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in nomi:
            nodi.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            bersaglio = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if ast.unparse(bersaglio) in nomi:
                nodi.append(n)
    spazio.setdefault("Any", Any)
    exec(compile(ast.Module(body=nodi, type_ignores=[]), str(_PIPELINE), "exec"), spazio)
    return spazio


class TestRigaPipeline(unittest.TestCase):
    """Revisione del 01/10: la riga 'pipeline' non copia gli elenchi della verifica."""

    def setUp(self):
        spazio = _esegui("_contatori_della_riga", "PASSI_SOLO_CONTATORI",
                         "CHIAVI_PASSI_SOLO_CONTATORI")
        self.riga = spazio["_contatori_della_riga"]

    def test_solo_esito_e_contatori_della_verifica(self):
        esito_verifica = {"status": "ok", "counters": {"esaminati": 3, "slug_modificati": ["a"]},
                          "slug_modificati": ["a"], "ids_da_rigenerare": [7, 8],
                          "proposte": [{"bando_id": 7, "prova": "testo lungo"}]}
        state = {"steps": {
            "verifica_stato": {"status": "ok", "counters": dict(esito_verifica)},
            "verifica_stato_ingresso": {"status": "ok", "counters": dict(esito_verifica)},
            "seo": {"status": "ok", "counters": {"selected": 2, "proposte": ["resta"]}},
            "monitor": {"status": "ok", "saltato": "giro_non_previsto"},
        }}
        riga = self.riga(state)
        for passo in ("verifica_stato", "verifica_stato_ingresso"):
            self.assertEqual(riga[passo], {"status": "ok", "counters": esito_verifica["counters"]})
        # Gli altri passi restano come prima.
        self.assertEqual(riga["seo"], {"selected": 2, "proposte": ["resta"]})
        self.assertEqual(riga["monitor"], {})
        # Lo stato del giro non si tocca: `_slug_da_notificare` lo legge.
        self.assertEqual(state["steps"]["verifica_stato"]["counters"]["proposte"],
                         esito_verifica["proposte"])

    def test_registra_usa_la_riga_filtrata(self):
        testo = ast.unparse(_funzione("_registra"))
        self.assertIn("contatori = _contatori_della_riga(state)", testo)


class TestRigenerazioneDellaVerifica(unittest.TestCase):
    """Revisione del 01/10: con la verifica attiva l'adattatore c'e' anche a monitor in ombra."""

    def _costruisci(self, per_verifica: bool, **impostazioni):
        rigenera = types.ModuleType("app.rigenera")
        rigenera.rigenera = lambda *a, **k: None
        rigenera.scrivi_su_db = lambda *a, **k: None
        app = types.ModuleType("app")
        app.rigenera = rigenera
        spazio = _esegui("_rigenerazione_di_produzione", functools=functools,
                         logger=MagicMock(), Callable=Callable,
                         _get_settings=lambda: SimpleNamespace(**impostazioni))
        with patch.dict(sys.modules, {"app": app, "app.rigenera": rigenera}):
            return spazio["_rigenerazione_di_produzione"](per_verifica=per_verifica), rigenera

    def test_verifica_attiva_con_monitor_in_ombra(self):
        adattatore, rigenera = self._costruisci(
            True, monitor_modalita="ombra", monitor_tipi_attivi=(),
            verifica_stato_modalita="attivo")
        self.assertIsInstance(adattatore, functools.partial)
        self.assertIs(adattatore.func, rigenera.rigenera)
        self.assertEqual(adattatore.keywords, {"attivo": True, "scrivi": rigenera.scrivi_su_db})

    def test_al_monitor_la_verifica_attiva_non_basta(self):
        adattatore, _ = self._costruisci(
            False, monitor_modalita="ombra", monitor_tipi_attivi=(),
            verifica_stato_modalita="attivo")
        self.assertIsNone(adattatore)

    def test_tutto_in_ombra_niente(self):
        for per_verifica in (True, False):
            adattatore, _ = self._costruisci(
                per_verifica, monitor_modalita="ombra", monitor_tipi_attivi=(),
                verifica_stato_modalita="ombra")
            self.assertIsNone(adattatore)
            adattatore, _ = self._costruisci(per_verifica, monitor_modalita="ombra")
            self.assertIsNone(adattatore)

    def test_monitor_attivo_resta_com_era(self):
        for per_verifica in (True, False):
            adattatore, _ = self._costruisci(
                per_verifica, monitor_modalita="attivo", verifica_stato_modalita="ombra")
            self.assertIsNotNone(adattatore)


if __name__ == "__main__":
    unittest.main()
