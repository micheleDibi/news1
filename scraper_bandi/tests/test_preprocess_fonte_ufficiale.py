# -*- coding: utf-8 -*-
"""Il preprocess sulla fonte ufficiale e la sua spesa (contratto `bandi-giro-3` §8 e §4).

- `analyze_bando(url_lettura=...)` legge la pagina dell'ente trovata dal
  resolver precoce invece della scheda dell'aggregatore; il prompt continua a
  mostrare `link_bando`; l'uscita porta le citazioni delle date;
- per OE, se la scadenza resta vuota, si rilegge la scheda dalla cache e si
  cerca solo l'etichetta citata, senza modello;
- il runner prova la pagina ufficiale, poi `link_bando`, poi il ripiego del
  resolver;
- la spesa si conta con l'involucro del client condiviso (`conta_spesa`), anche
  per la chiamata Sonnet di `bando_resolver.resolve_bando`, e la riga di spesa
  non si scrive in dry-run.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_preprocess_fonte_ufficiale
"""
import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.supporto import carica_modulo

pre = carica_modulo("preprocessor")
runner = carica_modulo("bando_preprocess_runner")
scarico = carica_modulo("scarico")
enricher = carica_modulo("enricher")
bando_resolver = carica_modulo("bando_resolver")
telemetria = carica_modulo("telemetria")
bilancio = carica_modulo("bilancio")

OGGI = date(2026, 10, 2)
LINK_OE = "https://www.obiettivoeuropa.com/bandi/contributi-formazione"
UFFICIALE = "https://www.regione.marche.it/bandi/contributi-formazione"
RIEMPITIVO = ("Il presente avviso disciplina le modalita' di presentazione delle domande di "
              "contributo per i percorsi di formazione professionale rivolti alle imprese. ") * 4


class _Scarico:
    """`scarico_corrente()` finto: una pagina per URL, e l'elenco delle richieste."""

    def __init__(self, pagine):
        self.pagine = pagine
        self.chiesti: list[str] = []

    async def scarica(self, url, **_kwargs):
        self.chiesti.append(url)
        testo = self.pagine.get(url, "")
        return scarico.Risposta(url=url, stato=200 if testo else 404, html=f"<p>{testo}</p>",
                                testo=testo, url_finale=url)


def _bando(**extra):
    valori = {"id": 7, "titolo_raw": "Contributi formazione", "link_bando": LINK_OE,
              "raw_data": {"status": "1", "deadline_label": "30 novembre 2026"}}
    valori.update(extra)
    return valori


async def _analizza(bando, pagine, risposta_modello, **kwargs):
    finto = _Scarico(pagine)
    prompt: list[str] = []

    async def modello(client, *, user_prompt, **_k):
        prompt.append(user_prompt)
        return object()

    async def markdown(url, **_k):
        finto.chiesti.append(f"md:{url}")
        return pagine.get(url, "")

    with patch.object(enricher, "_firecrawl_scrape_markdown", markdown), \
            patch.object(scarico, "scarico_corrente", lambda: finto), \
            patch.object(pre, "_get_anthropic_client", lambda: object()), \
            patch.object(pre, "_call_anthropic_with_retry", modello), \
            patch.object(pre, "_extract_tool_input", lambda r: dict(risposta_modello)), \
            patch.object(pre, "oggi_roma", lambda *a: OGGI):
        esito = await pre.analyze_bando(bando, {}, **kwargs)
    return esito, finto.chiesti, prompt


class AnalisiSullaPaginaUfficiale(unittest.IsolatedAsyncioTestCase):
    MODELLO = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto",
               "data_pubblicazione": None, "data_apertura": None,
               "data_scadenza": {"date": "2026-10-30", "source": "official_page",
                                 "quote": "entro il 30/10/2026"}}

    async def test_legge_l_ufficiale_e_il_prompt_mostra_link_bando(self):
        pagine = {UFFICIALE: f"Le domande vanno presentate entro il 30/10/2026. {RIEMPITIVO}"}
        esito, chiesti, prompt = await _analizza(_bando(), pagine, self.MODELLO,
                                                 url_lettura=UFFICIALE)
        self.assertEqual(chiesti[:2], [f"md:{UFFICIALE}", UFFICIALE])
        self.assertNotIn(LINK_OE, chiesti)
        self.assertIn(LINK_OE, prompt[0])
        self.assertNotIn(UFFICIALE, prompt[0])
        self.assertEqual(esito["data_scadenza"], "2026-10-30")
        self.assertEqual(esito["_citazioni"]["data_scadenza"], "entro il 30/10/2026")
        self.assertIsNone(esito["_citazioni"]["data_apertura"])

    async def test_senza_url_lettura_si_legge_link_bando(self):
        pagine = {LINK_OE: f"Scadenza: 30 novembre 2026. {RIEMPITIVO}"}
        modello = dict(self.MODELLO, data_scadenza=None)
        _esito, chiesti, _prompt = await _analizza(_bando(), pagine, modello)
        self.assertEqual(chiesti[0], f"md:{LINK_OE}")

    async def test_oe_scadenza_dall_etichetta_citata_sulla_scheda(self):
        # La pagina ufficiale non porta date; la scheda OE cita l'etichetta.
        pagine = {UFFICIALE: f"Avviso per la formazione. {RIEMPITIVO}",
                  LINK_OE: f"Scadenza: 30 novembre 2026. {RIEMPITIVO}"}
        modello = dict(self.MODELLO, data_scadenza=None)
        esito, chiesti, _prompt = await _analizza(_bando(), pagine, modello,
                                                  url_lettura=UFFICIALE)
        self.assertIn(LINK_OE, chiesti, "la scheda si rilegge dalla cache")
        self.assertEqual((esito["data_scadenza"], esito["_origine_scadenza"]),
                         ("2026-11-30", "etichetta_oe"))

    async def test_oe_senza_citazione_sulla_scheda_nessuna_data(self):
        pagine = {UFFICIALE: f"Avviso per la formazione. {RIEMPITIVO}",
                  LINK_OE: f"Scheda senza la data. {RIEMPITIVO}"}
        modello = dict(self.MODELLO, data_scadenza=None)
        esito, _chiesti, _prompt = await _analizza(_bando(), pagine, modello,
                                                   url_lettura=UFFICIALE)
        self.assertIsNone(esito["data_scadenza"])

    async def test_pagina_ufficiale_troppo_corta_chiede_il_ripiego(self):
        esito, _chiesti, _prompt = await _analizza(_bando(), {UFFICIALE: "breve"}, self.MODELLO,
                                                   url_lettura=UFFICIALE)
        self.assertTrue(esito["_needs_fallback"])


class CatenaDelRunner(unittest.IsolatedAsyncioTestCase):
    """Prima la pagina ufficiale, poi `link_bando`, poi `resolve_bando`."""

    async def _giro(self, righe, risposte, *, dry_run=True):
        chiamate: list[tuple] = []
        scritte: list = []

        async def analizza(bando, fonte, **kwargs):
            url = kwargs.get("url_lettura")
            chiamate.append((bando["id"], url))
            return dict(risposte[(bando["id"], url)])

        async def ripiego(bando, fonte):
            chiamate.append((bando["id"], "resolve_bando"))
            return {"is_valid_bando": False, "confidence_score": 0.0, "rejection_reason": "x",
                    "stato_bando": None, "_fallback_used": True}

        with patch.object(runner, "select_bandi_scraped", lambda limit=None: righe), \
                patch.object(runner, "select_fonti_by_ids", lambda ids: {}), \
                patch.object(runner, "enrich_fonti_with_names", lambda f: f), \
                patch.object(runner, "analyze_bando", analizza), \
                patch.object(runner, "resolve_bando", ripiego), \
                patch.object(runner, "update_bandi_postanalysis",
                             AsyncMock(return_value={"updated": 0, "failed": 0})), \
                patch.object(telemetria, "scrivi_pipeline_run", scritte.append):
            contatori = await runner.run(dry_run=dry_run)
        return contatori, chiamate, scritte

    async def test_i_crediti_del_passo_nella_sua_riga(self):
        # §19.1: solo cio' che scarica il passo, non i crediti di prima.
        finto = scarico.Scarico()
        scarico.imposta_scarico(finto)
        self.addCleanup(scarico.imposta_scarico, None)
        finto.contatori.crediti_firecrawl = 7                     # passi precedenti
        valida = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto",
                  "_needs_fallback": False}
        risposte = {(1, UFFICIALE): valida, (3, UFFICIALE + "/3"): valida,
                    (2, None): valida, (4, None): valida}

        def conta(chiave):
            finto.contatori.crediti_firecrawl += 1                # un ripiego Firecrawl
            finto.contatori.fetch += 2
            return dict(risposte[chiave])

        contatori, scritte = await self._giro_con(
            self._righe(), lambda b, url: conta((b["id"], url)), dry_run=False)
        self.assertEqual(contatori["spesa"]["crediti_firecrawl"], 4)
        self.assertEqual(contatori["spesa"]["fetch"], 8)
        self.assertEqual(scritte[0].crediti_effettivi, 4)

    async def _giro_con(self, righe, analizza_sync, *, dry_run=True):
        scritte: list = []

        async def analizza(bando, fonte, **kwargs):
            return analizza_sync(bando, kwargs.get("url_lettura"))

        with patch.object(runner, "select_bandi_scraped", lambda limit=None: righe), \
                patch.object(runner, "select_fonti_by_ids", lambda ids: {}), \
                patch.object(runner, "enrich_fonti_with_names", lambda f: f), \
                patch.object(runner, "analyze_bando", analizza), \
                patch.object(runner, "update_bandi_postanalysis",
                             AsyncMock(return_value={"updated": 0, "failed": 0})), \
                patch.object(telemetria, "scrivi_pipeline_run", scritte.append):
            contatori = await runner.run(dry_run=dry_run)
        return contatori, scritte

    def _righe(self):
        return [
            {"id": 1, "link_bando": LINK_OE, "fonte_ufficiale_url": UFFICIALE,
             "fonte_ufficiale_stato": "trovata"},
            {"id": 2, "link_bando": LINK_OE, "fonte_ufficiale_url": None,
             "fonte_ufficiale_stato": "non_trovata"},
            {"id": 3, "link_bando": LINK_OE, "fonte_ufficiale_url": UFFICIALE + "/3",
             "fonte_ufficiale_stato": "trovata"},
            {"id": 4, "link_bando": LINK_OE, "fonte_ufficiale_url": UFFICIALE + "/bando.pdf",
             "fonte_ufficiale_stato": "trovata"},
        ]

    async def test_l_ordine_dei_ripieghi(self):
        valida = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto",
                  "_needs_fallback": False}
        serve = {"_needs_fallback": True, "is_valid_bando": False, "confidence_score": 0.0}
        risposte = {
            (1, UFFICIALE): valida,
            (2, None): valida,
            (3, UFFICIALE + "/3"): serve, (3, None): serve,
            (4, None): valida,
        }
        contatori, chiamate, _s = await self._giro(self._righe(), risposte)
        self.assertEqual(sorted(chiamate, key=lambda c: (c[0], str(c[1]))), [
            (1, UFFICIALE), (2, None), (3, None), (3, UFFICIALE + "/3"), (3, "resolve_bando"),
            (4, None),
        ])
        self.assertEqual(contatori["letti_da_ufficiale"], 2, "il PDF non si legge come pagina")
        self.assertEqual(contatori["ripiego_su_link_bando"], 1)
        self.assertEqual(contatori["copertura"],
                         {"candidati": 4, "fatti": 4, "rimasti": 0, "motivo_rimasti": None})

    async def test_uno_scarto_sull_ufficiale_si_rilegge_su_link_bando(self):
        # Revisione #145: si scarta solo se anche `link_bando` dice «non valido».
        valida = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto"}
        scarto = {"is_valid_bando": False, "confidence_score": 0.8,
                  "rejection_reason": "pagina generica", "_needs_fallback": False}
        serve = {"_needs_fallback": True, "is_valid_bando": False, "confidence_score": 0.0}
        righe = [dict(self._righe()[0], id=i, fonte_ufficiale_url=f"{UFFICIALE}/{i}")
                 for i in (1, 2, 3)]
        risposte = {
            (1, f"{UFFICIALE}/1"): scarto, (1, None): valida,     # bando vero salvato
            (2, f"{UFFICIALE}/2"): scarto, (2, None): scarto,     # scartato davvero
            (3, f"{UFFICIALE}/3"): scarto, (3, None): serve,      # decide il ripiego
        }
        contatori, chiamate, _s = await self._giro(righe, risposte)
        self.assertIn((3, "resolve_bando"), chiamate)
        self.assertEqual(contatori["riletti_prima_dello_scarto"], 3)
        self.assertEqual(contatori["scarti_evitati_con_link_bando"], 1)
        self.assertEqual(contatori["valid"], 1)
        self.assertEqual(contatori["rejected"], 2)

    async def test_in_dry_run_nessuna_riga_di_spesa(self):
        risposte = {(2, None): {"is_valid_bando": True, "confidence_score": 0.9,
                                "stato_bando": "aperto"}}
        contatori, _c, scritte = await self._giro([self._righe()[1]], risposte, dry_run=True)
        self.assertEqual(scritte, [])
        self.assertIn("costo_usd", contatori)
        self.assertIn("spesa", contatori)

    async def test_fuori_dal_dry_run_la_riga_del_passo(self):
        risposte = {(2, None): {"is_valid_bando": True, "confidence_score": 0.9,
                                "stato_bando": "aperto"}}
        _contatori, _c, scritte = await self._giro([self._righe()[1]], risposte, dry_run=False)
        self.assertEqual([r.step for r in scritte], ["preprocess"])
        self.assertEqual(scritte[0].contatori["copertura"]["candidati"], 1)


class _Risposta:
    def __init__(self, ingresso=1000, uscita=100):
        self.usage = SimpleNamespace(input_tokens=ingresso, output_tokens=uscita)


class _ClienteFinto:
    def __init__(self):
        self.messages = self

    async def create(self, **kwargs):
        return _Risposta()


class SpesaContataDalClient(unittest.TestCase):
    def test_conta_solo_dentro_il_contesto(self):
        cliente = pre.ClienteContato(_ClienteFinto())
        spesa = bilancio.Contatori()

        async def giro():
            await cliente.messages.create(model="claude-haiku-4-5")
            with pre.conta_spesa(spesa):
                await asyncio.gather(*(cliente.messages.create(model="claude-haiku-4-5")
                                       for _ in range(3)))
            await cliente.messages.create(model="claude-haiku-4-5")

        asyncio.run(giro())
        uso = spesa.modelli["claude-haiku-4-5"]
        self.assertEqual((uso.chiamate, uso.token_ingresso, uso.token_uscita), (3, 3000, 300))
        self.assertAlmostEqual(spesa.usd, 3 * (1000 * 1.0 + 100 * 5.0) / 1e6)

    def test_il_resolver_usa_lo_stesso_client_e_viene_contato(self):
        # `bando_resolver` importa `_get_anthropic_client` da qui: la chiamata
        # Sonnet del ripiego passa dall'involucro senza toccare il suo file.
        self.assertIs(bando_resolver._get_anthropic_client, pre._get_anthropic_client)
        spesa = bilancio.Contatori()
        cliente = pre.ClienteContato(_ClienteFinto())

        async def giro():
            with pre.conta_spesa(spesa):
                await bando_resolver._call_anthropic_resolver(
                    cliente, model="claude-sonnet-4-6", max_tokens=10, system="s",
                    user_prompt="u")

        asyncio.run(giro())
        self.assertEqual(spesa.modelli["claude-sonnet-4-6"].chiamate, 1)

    def test_l_involucro_lascia_passare_il_resto(self):
        vero = _ClienteFinto()
        vero.altro = "attributo"
        cliente = pre.ClienteContato(vero)
        self.assertEqual(cliente.altro, "attributo")
        self.assertEqual(cliente.messages.create.__name__, "create")

    def test_il_contesto_non_trapela_dopo_il_passo(self):
        spesa = bilancio.Contatori()
        with pre.conta_spesa(spesa):
            pass
        pre.registra_uso("claude-haiku-4-5", _Risposta())
        self.assertEqual(spesa.modelli, {})


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
