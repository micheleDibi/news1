# -*- coding: utf-8 -*-
"""Bug fix dei runner (piano §8.a: 4, 9, 10, 11, 15 e parte B 24) con test AST
e mock, senza rete e senza DB:
  - `_do_one` del runner SEO ritorna sempre tuple di 4 elementi;
  - `reconcile_canonical_key` trova `asyncio` ed e' chiamata solo con
    DEDUP_CANONICAL attivo;
  - `update_bando_completed(gia_pubblicato=True)` congela slug e titolo e non
    tocca stato_processing; la select del runner porta stato_processing;
  - refine fallito o sotto soglia -> nessuna `update_bando_refinement`, nessun
    'aperto' di ripiego, confidenza persistita quando si scrive;
  - il safety net dell'enrich runner usa `oggi_roma` + `reconcile_stato_bando`;
  - nessun mese+anno cablato nei tre file dei prompt.
"""
import ast
import asyncio
import os
import re
import unittest
from datetime import date
from unittest import mock

from tests.supporto import APP, carica_modulo

db = carica_modulo("db")
seo = carica_modulo("bando_seo_runner")
er = carica_modulo("bando_enrich_runner")
en = carica_modulo("enricher")
pre = carica_modulo("preprocessor")
br = carica_modulo("bando_resolver")


# ---------------------------------------------------------------------------
# Finto client Supabase: registra le catene di chiamate, non tocca la rete.
# ---------------------------------------------------------------------------

class _Risposta:
    def __init__(self, data):
        self.data = data
        self.count = None


class _Costruttore:
    def __init__(self, sb, tabella):
        self._sb = sb
        self._tabella = tabella
        self._catena = []

    def __getattr__(self, nome):
        def metodo(*args, **kwargs):
            self._catena.append((nome, args, kwargs))
            return self
        return metodo

    def execute(self):
        self._sb.catene.append((self._tabella, list(self._catena)))
        return _Risposta(self._sb.risposta(self._tabella, self._catena))


class FakeSupabase:
    def __init__(self, risposta=None):
        self.catene = []
        self._risposta = risposta or (lambda tabella, catena: [])

    def table(self, nome):
        return _Costruttore(self, nome)

    def risposta(self, tabella, catena):
        return self._risposta(tabella, catena)

    def payload_update(self, tabella="bando"):
        return [
            args[0]
            for t, catena in self.catene
            for (nome, args, _kw) in catena
            if t == tabella and nome == "update"
        ]

    def colonne_select(self, tabella="bando"):
        return [
            args[0]
            for t, catena in self.catene
            for (nome, args, _kw) in catena
            if t == tabella and nome == "select"
        ]


def _funzione(albero, nome):
    for nodo in ast.walk(albero):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nome:
            return nodo
    raise AssertionError(f"funzione {nome} non trovata")


# ---------------------------------------------------------------------------
# Fix 9: _do_one ritorna 4 elementi
# ---------------------------------------------------------------------------

class TestSeoRunnerDoOne(unittest.TestCase):
    def test_tutte_le_return_sono_tuple_di_4(self):
        albero = ast.parse((APP / "bando_seo_runner.py").read_text(encoding="utf-8"))
        do_one = _funzione(albero, "_do_one")
        returns = [n for n in ast.walk(do_one) if isinstance(n, ast.Return)]
        self.assertGreaterEqual(len(returns), 2)
        for r in returns:
            self.assertIsInstance(r.value, ast.Tuple, f"riga {r.lineno}: return non tupla")
            self.assertEqual(len(r.value.elts), 4, f"riga {r.lineno}: {len(r.value.elts)} elementi")

    def _esegui(self, bandi, dedup=None, build_fallisce=False):
        payload = {"slug": "x", "titolo": "T", "contenuto": {"sections": []}, "livello": "flash_bando"}
        if build_fallisce:
            build = mock.Mock(side_effect=RuntimeError("catalogo rotto"))
        else:
            build = mock.Mock(side_effect=lambda b, c: {"id": b["id"]})
        with mock.patch.object(seo, "select_bandi_to_complete", return_value=bandi), \
             mock.patch.object(seo, "load_catalogo", return_value={}), \
             mock.patch.object(seo, "build_bando_input_context", build), \
             mock.patch.object(seo, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="md")), \
             mock.patch.object(seo, "_httpx_fetch_text", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(seo, "enrich_seo", new=mock.AsyncMock(return_value=dict(payload))), \
             mock.patch.object(seo, "update_bando_completed", new=mock.AsyncMock(return_value=True)) as upd, \
             mock.patch.object(seo, "reconcile_canonical_key",
                               new=mock.AsyncMock(return_value={"action": "created"})) as rec, \
             mock.patch.dict(os.environ, {}, clear=False):
            if dedup is None:
                os.environ.pop("DEDUP_CANONICAL", None)
            else:
                os.environ["DEDUP_CANONICAL"] = dedup
            contatori = asyncio.run(seo.run())
        return contatori, upd, rec

    def test_build_context_fallito_non_rompe_il_gather(self):
        # Sul codice vecchio il ritorno a 3 elementi faceva esplodere lo spacchettamento a 4.
        contatori, upd, _rec = self._esegui([{"id": 1, "link_bando": ""}], build_fallisce=True)
        self.assertEqual(contatori["selected"], 1)
        self.assertEqual(contatori["payload_failed"], 1)
        self.assertEqual(contatori["completed_db_ok"], 0)
        self.assertEqual(upd.await_count, 0)

    def test_reconcile_non_chiamata_senza_flag(self):
        contatori, upd, rec = self._esegui([{"id": 1, "link_bando": ""}])
        self.assertEqual(upd.await_count, 1)
        self.assertEqual(rec.await_count, 0)
        self.assertEqual(contatori["canonical_created"], 0)

    def test_reconcile_chiamata_solo_con_flag(self):
        contatori, _upd, rec = self._esegui([{"id": 1, "link_bando": ""}], dedup="true")
        self.assertEqual(rec.await_count, 1)
        self.assertEqual(contatori["canonical_created"], 1)
        _c, _u, rec = self._esegui([{"id": 1, "link_bando": ""}], dedup="false")
        self.assertEqual(rec.await_count, 0)

    def test_gia_pubblicato_dallo_stato_processing(self):
        bandi = [
            {"id": 1, "link_bando": "", "stato_processing": "completed"},
            {"id": 2, "link_bando": "", "stato_processing": "enriched"},
        ]
        _c, upd, _r = self._esegui(bandi)
        per_id = {c.args[0]: c.kwargs for c in upd.await_args_list}
        self.assertTrue(per_id[1]["gia_pubblicato"])
        self.assertFalse(per_id[2]["gia_pubblicato"])

    def test_dedup_canonical_attivo(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEDUP_CANONICAL", None)
            self.assertFalse(seo._dedup_canonical_attivo())
            os.environ["DEDUP_CANONICAL"] = "true"
            self.assertTrue(seo._dedup_canonical_attivo())
            os.environ["DEDUP_CANONICAL"] = "0"
            self.assertFalse(seo._dedup_canonical_attivo())


# ---------------------------------------------------------------------------
# Fix 10 e parte B 24: db.py
# ---------------------------------------------------------------------------

class TestDb(unittest.TestCase):
    def test_asyncio_importato_a_livello_di_modulo(self):
        self.assertIs(db.asyncio, asyncio)
        albero = ast.parse((APP / "db.py").read_text(encoding="utf-8"))
        a_modulo = [
            n for n in albero.body
            if isinstance(n, ast.Import) and any(a.name == "asyncio" for a in n.names)
        ]
        self.assertEqual(len(a_modulo), 1)
        for nodo in ast.walk(albero):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for interno in ast.walk(nodo):
                    if isinstance(interno, ast.Import):
                        self.assertFalse(
                            any(a.name == "asyncio" for a in interno.names),
                            f"import asyncio locale in {nodo.name}",
                        )

    def test_reconcile_canonical_key_non_solleva_nameerror(self):
        def risposta(tabella, catena):
            nomi = [n for n, _a, _k in catena]
            if "single" in nomi:
                return {"id": 1, "fonte_id": 2, "canonical_key": None}
            return []
        sb = FakeSupabase(risposta)
        with mock.patch.object(db, "get_supabase", return_value=sb):
            esito = asyncio.run(db.reconcile_canonical_key(
                1, {"titolo": "Voucher digitalizzazione", "ente_erogatore": "Regione X"},
            ))
        # Sul codice vecchio: NameError assorbita -> {'action': 'failed', 'error': "name 'asyncio'..."}
        self.assertEqual(esito["action"], "created")
        self.assertEqual(len(sb.payload_update()), 1)
        self.assertIn("canonical_key", sb.payload_update()[0])

    def test_payload_completed_filtro_puro(self):
        payload = {
            "slug": "nuovo-slug", "titolo": "Titolo nuovo", "titolo_breve": "Breve",
            "contenuto": {"sections": []}, "livello": "flash_bando", "campo_estraneo": 1,
        }
        normale = db._payload_completed(payload)
        self.assertEqual(normale["slug"], "nuovo-slug")
        self.assertEqual(normale["titolo"], "Titolo nuovo")
        self.assertEqual(normale["stato_processing"], "completed")
        self.assertNotIn("campo_estraneo", normale)

        pubblicato = db._payload_completed(payload, gia_pubblicato=True)
        self.assertNotIn("slug", pubblicato)
        self.assertNotIn("titolo", pubblicato)
        self.assertNotIn("stato_processing", pubblicato)
        self.assertEqual(pubblicato["titolo_breve"], "Breve")
        self.assertEqual(pubblicato["contenuto"], {"sections": []})

        senza_marca = db._payload_completed(payload, mark_completed=False)
        self.assertNotIn("stato_processing", senza_marca)
        self.assertIn("slug", senza_marca)

    def test_update_bando_completed_gia_pubblicato(self):
        sb = FakeSupabase()
        payload = {"slug": "s", "titolo": "t", "titolo_breve": "b"}
        with mock.patch.object(db, "get_supabase", return_value=sb):
            self.assertTrue(asyncio.run(db.update_bando_completed(5, payload, gia_pubblicato=True)))
            self.assertTrue(asyncio.run(db.update_bando_completed(5, payload)))
        primo, secondo = sb.payload_update()
        self.assertEqual(primo, {"titolo_breve": "b"})
        self.assertEqual(secondo, {"slug": "s", "titolo": "t", "titolo_breve": "b", "stato_processing": "completed"})

    def test_select_bandi_to_complete_porta_stato_processing(self):
        sb = FakeSupabase()
        with mock.patch.object(db, "get_supabase", return_value=sb):
            self.assertEqual(db.select_bandi_to_complete(), [])
        (colonne,) = sb.colonne_select()
        self.assertIn("stato_processing", [c.strip() for c in colonne.split(",")])

    def test_update_bando_refinement_con_confidenza(self):
        sb = FakeSupabase()
        with mock.patch.object(db, "get_supabase", return_value=sb):
            self.assertTrue(asyncio.run(db.update_bando_refinement(7, "aperto", confidence=0.9)))
            self.assertTrue(asyncio.run(db.update_bando_refinement(7, "chiuso")))
        con, senza = sb.payload_update()
        self.assertEqual(con, {"stato_bando": "aperto", "confidence_score": 0.9})
        self.assertEqual(senza, {"stato_bando": "chiuso"})


# ---------------------------------------------------------------------------
# Fix 11: refine senza ripiego 'aperto'
# ---------------------------------------------------------------------------

_RES_VUOTO = {
    "tipologia_bando_id": None, "modalita_erogazione_id": None, "programma_id": None,
    "beneficiari_ids": [], "codici_ateco_ids": [], "regioni_ids": [], "settori_ids": [],
}


class TestRefineSenzaRipiego(unittest.TestCase):
    def _esegui(self, bandi, refine, oggi=date(2026, 9, 22)):
        with mock.patch.object(er, "select_bandi_to_enrich", return_value=bandi), \
             mock.patch.object(er, "select_fonti_by_ids", return_value={}), \
             mock.patch.object(er, "enrich_fonti_with_names", side_effect=lambda d: d), \
             mock.patch.object(er, "load_catalogo", return_value={}), \
             mock.patch.object(er, "refine_stato_bando", new=mock.AsyncMock(**refine)) as ref, \
             mock.patch.object(er, "update_bando_refinement", new=mock.AsyncMock(return_value=True)) as upd_ref, \
             mock.patch.object(er, "enrich_bando", new=mock.AsyncMock(return_value=dict(_RES_VUOTO))) as enrich, \
             mock.patch.object(er, "update_bando_enriched", new=mock.AsyncMock(return_value=True)) as upd_enr, \
             mock.patch.object(er, "oggi_roma", return_value=oggi):
            contatori = asyncio.run(er.run())
        return contatori, ref, upd_ref, enrich, upd_enr

    def test_refine_fallito_nessuna_update(self):
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": None}]
        contatori, _ref, upd_ref, enrich, upd_enr = self._esegui(
            bandi, {"return_value": (None, 0.0, "LLM fallito: nessuna determinazione")},
        )
        self.assertEqual(upd_ref.await_count, 0)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(upd_enr.await_count, 0)
        self.assertEqual(contatori["refined_total"], 1)
        self.assertEqual(contatori["refined_to_aperto"], 0)
        self.assertEqual(contatori["refined_undetermined"], 1)

    def test_refine_che_solleva_nessuna_update(self):
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": None}]
        contatori, _ref, upd_ref, enrich, _u = self._esegui(bandi, {"side_effect": RuntimeError("boom")})
        self.assertEqual(upd_ref.await_count, 0)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["refined_to_aperto"], 0)

    def test_bassa_confidenza_nessuna_update_ne_promozione(self):
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": None}]
        contatori, _ref, upd_ref, enrich, _u = self._esegui(bandi, {"return_value": ("aperto", 0.3, "dubbio")})
        self.assertEqual(upd_ref.await_count, 0)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["refined_to_aperto"], 0)

    def test_alta_confidenza_scrive_con_confidenza_e_promuove(self):
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": None}]
        contatori, _ref, upd_ref, enrich, upd_enr = self._esegui(bandi, {"return_value": ("aperto", 0.9, "ok")})
        upd_ref.assert_awaited_once_with(1, "aperto", confidence=0.9)
        self.assertEqual(enrich.await_count, 1)
        self.assertEqual(upd_enr.await_args.args[1], "aperto")
        self.assertEqual(contatori["refined_to_aperto"], 1)
        self.assertEqual(contatori["enriched_db_ok"], 1)

    def test_chiuso_con_confidenza_scrive_ma_non_promuove(self):
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": None}]
        contatori, _ref, upd_ref, enrich, _u = self._esegui(bandi, {"return_value": ("chiuso", 0.8, "scaduto")})
        upd_ref.assert_awaited_once_with(1, "chiuso", confidence=0.8)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["refined_to_chiuso"], 1)

    def test_safety_net_usa_oggi_roma_e_reconcile(self):
        # Con «oggi» fissato al 2020 la scadenza 2020-06-30 NON e' passata: il
        # codice vecchio (date.today()) l'avrebbe forzata a 'chiuso'.
        bandi = [{"id": 1, "fonte_id": None, "link_bando": "", "stato_bando": "aperto",
                  "data_scadenza": "2020-06-30", "data_apertura": None}]
        contatori, _r, _u, _e, upd_enr = self._esegui(bandi, {"return_value": (None, 0.0, "")}, oggi=date(2020, 1, 1))
        self.assertEqual(upd_enr.await_args.args[1], "aperto")
        self.assertEqual(contatori["safety_net_forced_chiuso"], 0)
        # Con «oggi» dopo la scadenza -> 'chiuso'.
        contatori, _r, _u, _e, upd_enr = self._esegui(bandi, {"return_value": (None, 0.0, "")}, oggi=date(2020, 7, 1))
        self.assertEqual(upd_enr.await_args.args[1], "chiuso")
        self.assertEqual(contatori["safety_net_forced_chiuso"], 1)
        # Apertura futura -> 'in apertura prossimamente'.
        bandi = [{"id": 2, "fonte_id": None, "link_bando": "", "stato_bando": "aperto",
                  "data_scadenza": None, "data_apertura": "2020-03-01"}]
        contatori, _r, _u, _e, upd_enr = self._esegui(bandi, {"return_value": (None, 0.0, "")}, oggi=date(2020, 1, 1))
        self.assertEqual(upd_enr.await_args.args[1], "in apertura prossimamente")
        self.assertEqual(contatori["safety_net_forced_in_apertura"], 1)

    def test_nessun_aperto_di_ripiego_nel_sorgente(self):
        sorgente = (APP / "bando_enrich_runner.py").read_text(encoding="utf-8")
        self.assertNotIn('or "aperto"', sorgente)
        self.assertNotIn('("aperto", 0.0', sorgente)


class TestEnricherRefine(unittest.TestCase):
    def _refine(self, risultato):
        bando = {"id": 9, "titolo_raw": "Bando X", "descrizione_raw": "", "raw_data": {}, "link_bando": ""}
        with mock.patch.object(en, "_call_anthropic_tool", new=mock.AsyncMock(return_value=risultato)) as chiamata, \
             mock.patch.object(en, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(en, "_get_anthropic_client", return_value=object()):
            esito = asyncio.run(en.refine_stato_bando(bando, {"tipo_link": "Opportunità"}))
        return esito, chiamata

    def test_llm_fallito_ritorna_none(self):
        (stato, conf, motivo), _c = self._refine(None)
        self.assertIsNone(stato)
        self.assertEqual(conf, 0.0)
        self.assertTrue(motivo)

    def test_fuori_enum_ritorna_none(self):
        (stato, conf, motivo), _c = self._refine({"stato_bando": "boh", "confidence": 0.95})
        self.assertIsNone(stato)
        self.assertEqual(conf, 0.0)
        self.assertIn("boh", motivo)

    def test_valore_valido(self):
        (stato, conf, motivo), chiamata = self._refine({"stato_bando": "chiuso", "confidence": 0.8, "reason": "scaduto"})
        self.assertEqual((stato, conf, motivo), ("chiuso", 0.8, "scaduto"))
        oggi = en.data_italiana(en.oggi_roma())
        self.assertIn(oggi, chiamata.await_args.kwargs["system"])
        self.assertIn(oggi, chiamata.await_args.kwargs["user_prompt"])

    def test_tipo_preavviso_non_da_piu_in_apertura_di_ripiego(self):
        bando = {"id": 9, "titolo_raw": "Bando X", "raw_data": {}, "link_bando": "", "tipo_link": "Preavviso"}
        with mock.patch.object(en, "_call_anthropic_tool", new=mock.AsyncMock(return_value=None)), \
             mock.patch.object(en, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(en, "_get_anthropic_client", return_value=object()):
            stato, _conf, _m = asyncio.run(en.refine_stato_bando(bando, {"tipo_link": "Preavviso"}))
        self.assertIsNone(stato)


# ---------------------------------------------------------------------------
# Fix 4: nessun mese+anno cablato nei prompt
# ---------------------------------------------------------------------------

_MESE_ANNO_RE = re.compile(
    r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre) 20\d\d\b",
    re.IGNORECASE,
)


class TestPromptSenzaDateCablate(unittest.TestCase):
    def test_nessun_letterale_mese_anno(self):
        for nome in ("preprocessor.py", "enricher.py", "bando_resolver.py"):
            righe = (APP / nome).read_text(encoding="utf-8").splitlines()
            for numero, riga in enumerate(righe, 1):
                if riga.lstrip().startswith("#"):
                    continue
                self.assertIsNone(_MESE_ANNO_RE.search(riga), f"{nome}:{numero}: {riga.strip()!r}")

    def test_preprocessor_system_prompt_con_data(self):
        prompt = pre.system_prompt(date(2026, 9, 22))
        self.assertIn("Data attuale: 22 settembre 2026.", prompt)
        self.assertIn("< 22 settembre 2026 (oggi)", prompt)
        self.assertIn("> 22 settembre 2026 (oggi)", prompt)
        self.assertNotIn("{oggi}", prompt)
        self.assertIn("{slug-bando-descrittivo}", prompt)  # graffe letterali preservate

    def test_enricher_refine_system_con_data(self):
        prompt = en.refine_system(date(2026, 9, 22))
        self.assertIn("La data attuale è 22 settembre 2026.", prompt)
        self.assertNotIn("{oggi}", prompt)

    def test_resolver_system_prompt_con_data_e_anni(self):
        prompt = br.resolver_system_prompt(date(2026, 9, 22))
        self.assertIn("data attuale: 22 settembre 2026", prompt)
        self.assertIn('"edizione 2024" / "Bando 2025" + 22 settembre 2026', prompt)
        self.assertIn('"Bando 2026" / "anno 2026"', prompt)
        self.assertNotIn("{", prompt)

    def test_default_usa_oggi_roma(self):
        for modulo, funzione in ((pre, "system_prompt"), (en, "refine_system"), (br, "resolver_system_prompt")):
            with mock.patch.object(modulo, "oggi_roma", return_value=date(2031, 3, 5)):
                self.assertIn("5 marzo 2031", getattr(modulo, funzione)())

    def test_call_sites_usano_le_funzioni(self):
        self.assertIn("system=system_prompt(),", (APP / "preprocessor.py").read_text(encoding="utf-8"))
        self.assertIn("system=refine_system(),", (APP / "enricher.py").read_text(encoding="utf-8"))
        self.assertIn("system=resolver_system_prompt(),", (APP / "bando_resolver.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
