# -*- coding: utf-8 -*-
"""L'enrich sulla fonte ufficiale (contratto `bandi-giro-3` §8 e §4).

- il testo da classificare e lo stato si prendono dalla pagina scelta con
  `dominio_ufficiale.scegli_fonte`, non dalla scheda dell'aggregatore;
- una chiamata al modello fallita e' distinta da «nessuna voce»
  (`_fallite`): la rielaborazione dei pubblicati non deve svuotare una
  dimensione piena per colpa di un errore (§9);
- la spesa del passo finisce in una riga propria, mai in dry-run.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_enrich_fonte
"""
import asyncio
import unittest
from unittest import mock

from tests.supporto import carica_modulo

en = carica_modulo("enricher")
er = carica_modulo("bando_enrich_runner")
telemetria = carica_modulo("telemetria")
scarico = carica_modulo("scarico")

LINK_OE = "https://www.obiettivoeuropa.com/bandi/contributi"
UFFICIALE = "https://www.regione.marche.it/bandi/contributi"
CATALOGO = [{"id": 1, "nome": "Marche"}, {"id": 2, "nome": "Lazio"}]


def _esegui(coroutine):
    return asyncio.run(coroutine)


class ChiamateFallite(unittest.TestCase):
    def _multi(self, risposta, catalogo=CATALOGO):
        fallite: set[str] = set()
        with mock.patch.object(en, "_get_anthropic_client", return_value=object()), \
                mock.patch.object(en, "_call_anthropic_tool",
                                  new=mock.AsyncMock(return_value=risposta)):
            ids = _esegui(en._extract_multi({}, {}, "", catalogo, "regioni", "regioni",
                                            fallite=fallite))
        return ids, fallite

    def test_la_chiamata_fallita_e_segnata(self):
        self.assertEqual(self._multi(None), ([], {"regioni"}))

    def test_nessuna_voce_non_e_un_fallimento(self):
        self.assertEqual(self._multi({"ids": []}), ([], set()))
        self.assertEqual(self._multi({"ids": [2, 9]}), ([2], set()))

    def test_catalogo_vuoto_non_e_un_fallimento(self):
        self.assertEqual(self._multi(None, catalogo=[]), ([], set()))

    def test_anche_il_single_select(self):
        fallite: set[str] = set()
        with mock.patch.object(en, "_get_anthropic_client", return_value=object()), \
                mock.patch.object(en, "_call_anthropic_tool", new=mock.AsyncMock(return_value=None)):
            valore = _esegui(en._extract_single({}, {}, "", CATALOGO, "tipologia", "tipologia",
                                                fallite=fallite))
        self.assertIsNone(valore)
        self.assertEqual(fallite, {"tipologia"})

    def test_enrich_bando_dice_quali_dimensioni_sono_fallite(self):
        async def chiama(client, *, tool, **_k):
            nome = tool["name"]                       # «save_<dimensione>»
            if nome == "save_regioni":
                return None
            if nome == "save_programma":
                return {"id": None}
            return {"ids": [1]} if "ids" in str(tool) else {"id": 1}

        catalogo = {nome: CATALOGO for nome in (
            "tipologie", "modalita", "programmi", "beneficiari", "codici_ateco", "regioni", "settori")}
        with mock.patch.object(en, "_get_anthropic_client", return_value=object()), \
                mock.patch.object(en, "_call_anthropic_tool", new=chiama), \
                mock.patch.object(en, "extract_settori",
                                  new=mock.AsyncMock(side_effect=RuntimeError("boom"))):
            esito = _esegui(en.enrich_bando({}, {}, "", catalogo))
        self.assertEqual(esito["_fallite"], ("regioni", "settori"))
        self.assertEqual(esito["regioni_ids"], [])
        self.assertIsNone(esito["programma_id"], "una risposta senza voce non e' un fallimento")
        self.assertEqual(en.DIMENSIONI_ENRICH,
                         ("tipologia", "modalita", "programma", "beneficiari", "codici_ateco",
                          "regioni", "settori"))


class CatalogoVuoto(unittest.TestCase):
    """§19.4: una dimensione con il catalogo vuoto (tabella non letta) e' una
    dimensione fallita, non «nessuna voce»; il modello non si chiama."""

    def test_catalogo_vuoto_e_fallita(self):
        chieste: list[str] = []

        async def chiama(client, *, tool, **_k):
            chieste.append(tool["name"])
            return {"ids": [1]} if "ids" in str(tool) else {"id": 1}

        catalogo = {nome: CATALOGO for nome in (
            "tipologie", "modalita", "programmi", "beneficiari", "codici_ateco", "settori")}
        catalogo["regioni"] = []
        with mock.patch.object(en, "_get_anthropic_client", return_value=object()), \
                mock.patch.object(en, "_call_anthropic_tool", new=chiama):
            esito = _esegui(en.enrich_bando({}, {}, "", catalogo))
        self.assertEqual(esito["_fallite"], ("regioni",))
        self.assertNotIn("save_regioni", chieste)
        self.assertEqual(len(chieste), 6)

    def test_chiave_mancante_vale_vuoto(self):
        async def chiama(client, *, tool, **_k):
            return {"ids": [1]} if "ids" in str(tool) else {"id": 1}

        with mock.patch.object(en, "_get_anthropic_client", return_value=object()), \
                mock.patch.object(en, "_call_anthropic_tool", new=chiama):
            esito = _esegui(en.enrich_bando({}, {}, "", {}))
        self.assertEqual(set(esito["_fallite"]), set(en.DIMENSIONI_ENRICH))


_RES = {"tipologia_bando_id": None, "modalita_erogazione_id": None, "programma_id": None,
        "beneficiari_ids": [], "codici_ateco_ids": [], "regioni_ids": [], "settori_ids": [],
        "_fallite": ()}


class RunnerSullaFonteUfficiale(unittest.TestCase):
    def _esegui(self, bandi, *, dry_run=True, risultato=None, scarica=None):
        letti: list[str] = []
        scritte: list = []

        async def markdown(url, **_k):
            letti.append(url)
            if scarica is not None:
                scarica(url)
            return "testo"

        refine = mock.AsyncMock(return_value=("aperto", 0.9, "ok"))
        enrich = mock.AsyncMock(return_value=dict(risultato or _RES))
        with mock.patch.object(er, "select_bandi_to_enrich", return_value=bandi), \
                mock.patch.object(er, "select_fonti_by_ids", return_value={}), \
                mock.patch.object(er, "enrich_fonti_with_names", side_effect=lambda d: d), \
                mock.patch.object(er, "load_catalogo", return_value={}), \
                mock.patch.object(er, "refine_stato_bando", new=refine), \
                mock.patch.object(er, "update_bando_refinement",
                                  new=mock.AsyncMock(return_value=True)), \
                mock.patch.object(er, "enrich_bando", new=enrich), \
                mock.patch.object(er, "update_bando_enriched", new=mock.AsyncMock(return_value=True)), \
                mock.patch.object(en, "_firecrawl_scrape_markdown", new=markdown), \
                mock.patch.object(telemetria, "scrivi_pipeline_run", scritte.append):
            contatori = asyncio.run(er.run(dry_run=dry_run))
        return contatori, refine, letti, scritte

    def _bando(self, **extra):
        valori = {"id": 1, "fonte_id": None, "link_bando": LINK_OE, "stato_bando": None,
                  "fonte_ufficiale_url": UFFICIALE, "fonte_ufficiale_stato": "trovata"}
        valori.update(extra)
        return valori

    def test_i_crediti_del_passo_nella_sua_riga(self):
        # §19.1: refine ed enrich scrivono il proprio delta, non quello del giro.
        finto = scarico.Scarico()
        scarico.imposta_scarico(finto)
        self.addCleanup(scarico.imposta_scarico, None)
        finto.contatori.crediti_firecrawl = 11

        def scarica(_url):
            finto.contatori.crediti_firecrawl += 1                # il ripiego Firecrawl

        contatori, _r, _l, scritte = self._esegui(
            [self._bando(), self._bando(id=2)], dry_run=False, scarica=scarica)
        self.assertEqual(contatori["spesa"]["crediti_firecrawl"], 2)
        self.assertEqual(scritte[0].crediti_effettivi, 2)

    def test_refine_ed_enrich_leggono_la_pagina_ufficiale(self):
        contatori, refine, letti, _s = self._esegui([self._bando()])
        self.assertEqual(refine.await_args.args[0]["link_bando"], UFFICIALE)
        self.assertEqual(letti, [UFFICIALE])
        self.assertEqual(contatori["letti_da_ufficiale"], 1)

    def test_senza_fonte_trovata_resta_link_bando(self):
        _c, refine, letti, _s = self._esegui([self._bando(fonte_ufficiale_stato="in_verifica")])
        self.assertEqual(refine.await_args.args[0]["link_bando"], LINK_OE)
        self.assertEqual(letti, [LINK_OE])

    def test_le_chiamate_fallite_si_contano(self):
        risultato = dict(_RES, _fallite=("regioni", "settori"))
        contatori, _r, _l, _s = self._esegui([self._bando(stato_bando="aperto")],
                                             risultato=risultato)
        self.assertEqual((contatori["con_chiamate_fallite"], contatori["dimensioni_fallite"]),
                         (1, 2))

    def test_spesa_e_copertura_mai_in_dry_run(self):
        contatori, _r, _l, scritte = self._esegui([self._bando()], dry_run=True)
        self.assertEqual(scritte, [])
        self.assertEqual(contatori["copertura"],
                         {"candidati": 1, "fatti": 1, "rimasti": 0, "motivo_rimasti": None})
        self.assertIn("costo_usd", contatori)
        _c, _r, _l, scritte = self._esegui([self._bando()], dry_run=False)
        self.assertEqual([r.step for r in scritte], ["enrich"])
        self.assertIn("copertura", scritte[0].contatori)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
