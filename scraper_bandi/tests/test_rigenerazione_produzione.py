# -*- coding: utf-8 -*-
"""L'adattatore di rigenerazione in produzione, con `MONITOR_TIPI_ATTIVI`.

Revisione avversaria del 30/09/2026, P1: `_rigenerazione_di_produzione()`
restituiva None se `MONITOR_MODALITA != attivo`. Con i tipi attivi in ombra una
proroga cambiava `data_scadenza` e la prosa restava con la data vecchia, lo
slug non andava a IndexNow e nessun allarme lo diceva. I test di
`test_tipi_attivi` passavano l'adattatore dall'esterno, e non l'hanno visto.

La funzione della pipeline sta in `backend/app/bandi_pipeline.py`, che importa
i runner di `scraper_bandi` come package `app`: su questa macchina c'e' un
altro `app` sul sys.path. Qui la si legge dal sorgente, per percorso, e la si
esegue con impostazioni e `app.rigenera` finti.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_rigenerazione_produzione
"""
import ast
import functools
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

from tests.supporto import REPO, carica_modulo
from tests.test_tipi_attivi import (
    ADESSO, TIPI, _FonteSenzaLimite, _classificatore, _impostazioni, _lock_libero, _patch_gate,
    _proroga, _riga, _scarica,
)

monitoraggio = carica_modulo("monitoraggio")
cli = carica_modulo("__main__")

PIPELINE = REPO / "backend" / "app" / "bandi_pipeline.py"


def _funzione_della_pipeline(impostazioni):
    """`_rigenerazione_di_produzione` di bandi_pipeline.py, eseguita da sola."""
    albero = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    (nodo,) = [n for n in albero.body
               if isinstance(n, ast.FunctionDef) and n.name == "_rigenerazione_di_produzione"]
    spazio: dict = {"functools": functools, "logger": MagicMock(), "Callable": Callable,
                    "Any": Any, "_get_settings": lambda: impostazioni}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), str(PIPELINE), "exec"), spazio)
    return spazio["_rigenerazione_di_produzione"]


def _app_finto():
    """`app.rigenera` con i due nomi che la pipeline usa."""
    rigenera = types.ModuleType("app.rigenera")
    rigenera.rigenera = lambda *a, **k: None
    rigenera.scrivi_su_db = lambda *a, **k: None
    app = types.ModuleType("app")
    app.rigenera = rigenera
    return app, rigenera


class TestPipeline(unittest.TestCase):
    def _costruisci(self, **impostazioni):
        app, rigenera = _app_finto()
        funzione = _funzione_della_pipeline(SimpleNamespace(**impostazioni))
        with patch.dict(sys.modules, {"app": app, "app.rigenera": rigenera}):
            return funzione(), rigenera

    def test_ombra_con_tipi_attivi_costruisce_l_adattatore(self):
        adattatore, rigenera = self._costruisci(
            monitor_modalita="ombra", monitor_tipi_attivi=TIPI)
        self.assertIsInstance(adattatore, functools.partial)
        self.assertIs(adattatore.func, rigenera.rigenera)
        self.assertEqual(adattatore.keywords, {"attivo": True, "scrivi": rigenera.scrivi_su_db})

    def test_attivo_costruisce_l_adattatore(self):
        adattatore, _ = self._costruisci(monitor_modalita="attivo", monitor_tipi_attivi=())
        self.assertIsNotNone(adattatore)

    def test_ombra_senza_tipi_non_costruisce_niente(self):
        # Un giro che non applica niente non deve poter raggiungere
        # `scrivi_su_db`.
        adattatore, _ = self._costruisci(monitor_modalita="ombra", monitor_tipi_attivi=())
        self.assertIsNone(adattatore)

    def test_impostazioni_senza_il_campo(self):
        adattatore, _ = self._costruisci(monitor_modalita="ombra")
        self.assertIsNone(adattatore)


class TestRigaDiComando(unittest.TestCase):
    """La gemella in `__main__.py`: `_rigenerazione_serve` decide."""

    def _serve(self, *, attivo=False, ombra=False, dry_run=False, modalita="ombra", tipi=()):
        return cli._rigenerazione_serve(
            attivo=attivo, ombra=ombra, dry_run=dry_run,
            impostazioni=SimpleNamespace(monitor_modalita=modalita, monitor_tipi_attivi=tipi))

    def test_tabella(self):
        self.assertTrue(self._serve(tipi=TIPI))                    # ombra + tipi attivi
        self.assertTrue(self._serve(attivo=True))                  # --attivo
        self.assertTrue(self._serve(modalita="attivo"))            # MONITOR_MODALITA=attivo
        self.assertFalse(self._serve())                            # ombra, niente tipi
        self.assertFalse(self._serve(tipi=TIPI, ombra=True))       # --ombra
        self.assertFalse(self._serve(tipi=TIPI, dry_run=True))     # --dry-run
        self.assertFalse(self._serve(attivo=True, dry_run=True))

    def test_il_comando_monitor_la_usa(self):
        catturati = {}

        def esegui(nome, funzione, argv, **kw):
            catturati["parametri"] = kw["extra"](cli._leggi_opzioni(argv))
            return 0

        impostazioni = SimpleNamespace(monitor_modalita="ombra", monitor_tipi_attivi=TIPI)
        settings = carica_modulo("settings")
        with patch.object(cli, "_esegui_v11", esegui), \
                patch.object(cli, "_adattatori_g7", lambda: {}), \
                patch.object(settings, "get_settings", lambda: impostazioni), \
                patch.object(cli, "_rigenerazione_di_produzione",
                             side_effect=lambda scrive: ("adattatore", scrive)):
            cli._cmd_monitor([])
            self.assertEqual(catturati["parametri"]["rigenerazione"], ("adattatore", True))
            cli._cmd_monitor(["--ombra"])
            self.assertEqual(catturati["parametri"]["rigenerazione"], ("adattatore", False))


class TestAllarmeProsaVecchia(unittest.IsolatedAsyncioTestCase):
    """Date applicate e prosa non riscritta: e' un allarme, e niente IndexNow."""

    async def test_proroga_senza_rigenerazione(self):
        dati = _FonteSenzaLimite(righe=[_riga()])
        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
                scarica=_scarica, classifica=_classificatore(_proroga()),
                rigenerazione=None, tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito["applicati_per_tipo"], {"proroga": 1})
        self.assertEqual(esito["prosa_non_riscritta"], 1)
        self.assertEqual(esito["slug_modificati"], [])
        self.assertTrue(any("prosa non riscritta" in a for a in esito["allarmi"]))

    async def test_rigenerazione_fallita(self):
        async def rigenera(*a, **k):
            return {"scritto": False, "via": ""}

        dati = _FonteSenzaLimite(righe=[_riga()])
        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
                scarica=_scarica, classifica=_classificatore(_proroga()),
                rigenerazione=rigenera, tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito["prosa_non_riscritta"], 1)
        self.assertEqual(esito["slug_modificati"], [])


DESCRIZIONE = (
    "La Regione finanzia progetti di inclusione digitale delle imprese del territorio con "
    "contributi a fondo perduto. Le domande si presentano entro il 30 ottobre 2026 sulla "
    "piattaforma regionale dei bandi, con la documentazione indicata nell'avviso."
)

CONTENUTO_JSON = {"sections": [
    {"type": "h2", "text": "Come e quando"},
    {"type": "paragraph", "segments": [
        {"kind": "text", "text": "Le domande vanno presentate entro il 30 ottobre 2026 "},
        {"kind": "link", "text": "sulla piattaforma", "url": "https://bandi.regione.it/avviso"},
        {"kind": "text", "text": "."},
    ]},
]}


class TestConIlModuloRigeneraVero(unittest.IsolatedAsyncioTestCase):
    """Revisione avversaria del 30/09/2026 (P1, secondo ciclo): la riga del
    monitor non portava `contenuto`, `rigenera` usciva «solo box» e il giro lo
    contava come riscritto. Qui l'adattatore e' quello di produzione
    (`functools.partial(rigenera.rigenera, attivo=True, scrivi=…)`), con il
    modulo `rigenera` VERO; finto e' solo lo scrittore sul DB."""

    def setUp(self):
        self.rigenera = carica_modulo("rigenera")
        self.scritture = []

        async def scrivi(bando_id, payload):
            self.scritture.append((bando_id, payload))
            return True

        self.adattatore = functools.partial(
            self.rigenera.rigenera, attivo=True, scrivi=scrivi)

    async def _giro(self, **riga):
        dati = _FonteSenzaLimite(righe=[_riga(**riga)])
        with _patch_gate():
            return await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
                scarica=_scarica, classifica=_classificatore(_proroga()),
                rigenerazione=self.adattatore, tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)

    async def test_la_data_nuova_finisce_nel_contenuto_scritto(self):
        self.assertTrue(180 <= len(DESCRIZIONE) <= 320)
        esito = await self._giro(contenuto=CONTENUTO_JSON, descrizione_breve=DESCRIZIONE)
        (bando_id, payload), = self.scritture
        self.assertEqual(bando_id, 1)
        # Il jsonb torna jsonb (con la stessa struttura e lo stesso link), non
        # testo e non `str(dict)`.
        contenuto = payload["contenuto"]
        self.assertIsInstance(contenuto, dict)
        testo = str(contenuto)
        self.assertIn("30 novembre 2026", testo)
        self.assertNotIn("30 ottobre 2026", testo)
        self.assertIn("https://bandi.regione.it/avviso", testo)
        self.assertEqual(contenuto["sections"][0], CONTENUTO_JSON["sections"][0])
        # La meta description e il testo della card, anche loro.
        self.assertIn("30 novembre 2026", payload["descrizione_breve"])
        self.assertEqual(esito["prosa_non_riscritta"], 0)
        self.assertEqual(esito["slug_modificati"], ["avviso-1"])

    async def test_ripiego_sul_box_e_un_allarme(self):
        # Il testo non cita la scadenza: niente da sostituire, il gate respinge
        # e `rigenera` ripiega sul box. La prosa non dice la data nuova.
        esito = await self._giro(contenuto={"sections": [{"type": "paragraph", "segments": [
            {"kind": "text", "text": "Le domande si presentano sulla piattaforma regionale."}]}]},
            descrizione_breve=DESCRIZIONE)
        self.assertEqual(self.scritture, [])
        self.assertEqual(esito["prosa_non_riscritta"], 1)
        self.assertEqual(esito["slug_modificati"], [])
        self.assertTrue(any("prosa non riscritta" in a for a in esito["allarmi"]))

    async def test_contenuto_assente_e_un_allarme(self):
        esito = await self._giro(contenuto=None)
        self.assertEqual(self.scritture, [])
        self.assertEqual(esito["prosa_non_riscritta"], 1)
        self.assertEqual(esito["slug_modificati"], [])

    async def test_testo_gia_in_linea_non_e_un_allarme(self):
        # Il testo dice gia' la data nuova: niente da scrivere, e non e' un
        # ripiego (l'unico `via="box"` legittimo).
        esito = await self._giro(
            contenuto="Le domande vanno presentate entro il 30 novembre 2026.",
            descrizione_breve=None)
        self.assertEqual(self.scritture, [])
        self.assertEqual(esito["prosa_non_riscritta"], 0)
        self.assertEqual(esito["slug_modificati"], ["avviso-1"])


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
