# -*- coding: utf-8 -*-
"""Lunghezze e motivi di scarto della skill SEO (T-C2, bando 772894).

Il 772894 (CCIAA Pistoia-Prato, fonte OE) e' rimasto `enriched` dal 22/08:
Opus scriveva un titolo di 88 caratteri e `_validate_payload` buttava l'intero
payload, gia' pagato, a ogni giro. Qui si verifica che:

  * sui bandi non pubblicati un titolo troppo lungo NON si taglia (si congela
    alla pubblicazione): si usa il `titolo_breve` se sta in 80 caratteri,
    altrimenti UNA richiamata al modello, altrimenti scarto con motivo. La
    descrizione troppo lunga si accorcia all'ultima frase intera;
  * sui pubblicati il titolo non si scrive e non si giudica;
  * ogni scarto porta un motivo, che finisce nella riga del giro
    (`payload_failed_motivi`, al massimo 50 voci, poi `payload_failed_altri`).

Nessuna rete, nessun modello, nessun DB.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.supporto import carica_modulo

seo_skill = carica_modulo("seo_skill")
runner = carica_modulo("bando_seo_runner")
db = carica_modulo("db")

#: Il titolo del 772894 come lo riscrive il modello (riprodotto il 30/09).
TITOLO_772894 = ("Contributi a fondo perduto per l'internazionalizzazione delle imprese "
                 "di Pistoia e Prato")
#: Un titolo entro gli 80 caratteri, dove il titolo non e' cio' che si prova.
TITOLO_CORTO = "Contributi CCIAA Pistoia-Prato per l'internazionalizzazione"
#: La riscrittura attesa dalla richiamata: entro 80, con entrambi i luoghi.
TITOLO_RISCRITTO = "Contributi a fondo perduto per l'export delle imprese di Pistoia e Prato"
DESCRIZIONE = ("La Camera di Commercio di Pistoia-Prato mette a disposizione 494.450 euro a "
               "fondo perduto per sostenere l'internazionalizzazione di micro, piccole e medie "
               "imprese. Domande entro il 15 ottobre 2026.")


def payload_772894(**campi):
    base = {
        "slug": "cciaa-pistoia-prato-contributi-internazionalizzazione",
        "titolo": TITOLO_772894,
        "descrizione_breve": DESCRIZIONE,
        "contenuto": {"sections": [
            {"type": "h2", "text": "Chi può candidarsi"},
            {"type": "paragraph", "segments": [{"kind": "text", "text": "Le MPMI."}]},
        ]},
        "livello": "flash_bando", "allegati": [], "ente_erogatore": "CCIAA Pistoia-Prato",
        "tematica": ["Internazionalizzazione"], "link_candidatura": None,
        "link_candidatura_source": "missing",
    }
    base.update(campi)
    return base


def valida(payload, *, ripara, diagnosi=None):
    with mock.patch.object(db, "slug_exists", return_value=False):
        return asyncio.run(seo_skill._validate_payload(
            payload, 772894, {"titolo_raw": "CCIAA Pistoia-Prato"}, "",
            reachability_check=False, link_ammessi=[], allegati_ammessi=[],
            ripara_lunghezze=ripara, diagnosi=diagnosi,
        ))


def risposta_tool(nome, dati, stop="tool_use"):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=nome, input=dati)],
                           stop_reason=stop, usage={"input_tokens": 100, "output_tokens": 20})


def cliente(*risposte):
    """Un client finto che restituisce le risposte in ordine."""
    crea = mock.AsyncMock(side_effect=list(risposte))
    return SimpleNamespace(messages=SimpleNamespace(create=crea))


def sistema(payload, client, diagnosi=None, contatori=None):
    return asyncio.run(seo_skill.sistema_titolo(
        payload, 772894, {"titolo_raw": "CCIAA Pistoia-Prato - Bando internazionalizzazione"},
        client=client, model="claude-opus-4-7", contatori=contatori,
        listino={"claude-opus-4-7": (5.0, 25.0)}, diagnosi=diagnosi,
    ))


class TestSistemaTitolo(unittest.TestCase):
    """Revisione #25: il titolo non si taglia mai a macchina."""

    def test_entro_il_limite_nessuna_chiamata(self):
        payload = payload_772894(titolo=TITOLO_CORTO)
        client = cliente()
        self.assertTrue(sistema(payload, client))
        self.assertEqual(payload["titolo"], TITOLO_CORTO)
        client.messages.create.assert_not_awaited()

    def test_prima_il_titolo_breve(self):
        payload = payload_772894(titolo_breve="Internazionalizzazione, CCIAA Pistoia-Prato")
        client = cliente()
        self.assertTrue(sistema(payload, client))
        self.assertEqual(payload["titolo"], "Internazionalizzazione, CCIAA Pistoia-Prato")
        client.messages.create.assert_not_awaited()

    def test_titolo_breve_troppo_lungo_o_vuoto_non_vale(self):
        for breve in ("x" * 81, "   ", None):
            with self.subTest(breve=breve):
                payload = payload_772894(titolo_breve=breve)
                client = cliente(risposta_tool("riscrivi_titolo", {"titolo": TITOLO_RISCRITTO}))
                self.assertTrue(sistema(payload, client))
                self.assertEqual(payload["titolo"], TITOLO_RISCRITTO)

    def test_una_richiamata_con_il_motivo_e_senza_taglio(self):
        payload = payload_772894()
        client = cliente(risposta_tool("riscrivi_titolo", {"titolo": TITOLO_RISCRITTO}))
        contatori = carica_modulo("bilancio").Contatori()
        self.assertTrue(sistema(payload, client, contatori=contatori))
        # Il 772894 non diventa piu' «…di Pistoia»: i due luoghi restano.
        self.assertEqual(payload["titolo"], TITOLO_RISCRITTO)
        self.assertIn("Pistoia e Prato", payload["titolo"])
        self.assertFalse(payload["titolo"].endswith("di Pistoia"))
        client.messages.create.assert_awaited_once()
        argomenti = client.messages.create.await_args.kwargs
        messaggio = argomenti["messages"][0]["content"]
        self.assertIn("Il titolo ha 88 caratteri", messaggio)
        self.assertIn("senza perdere enti o luoghi", messaggio)
        self.assertIn(TITOLO_772894, messaggio)
        self.assertEqual(argomenti["tools"][0]["name"], "riscrivi_titolo")
        self.assertEqual(argomenti["max_tokens"], 300)
        self.assertEqual(contatori.chiamate, 1)                 # la richiamata si paga

    def test_ancora_lungo_dopo_la_richiamata_scarto_con_motivo(self):
        payload = payload_772894()
        lungo = "Contributi " + "x" * 74                        # 85 caratteri
        client = cliente(risposta_tool("riscrivi_titolo", {"titolo": lungo}))
        diagnosi = {}
        self.assertFalse(sistema(payload, client, diagnosi))
        self.assertEqual(diagnosi["motivo"], "titolo 85 caratteri anche dopo la richiamata")
        self.assertEqual(payload["titolo"], TITOLO_772894)      # nessun taglio
        client.messages.create.assert_awaited_once()            # una sola richiamata

    def test_richiamata_senza_risposta_scarto_con_motivo(self):
        payload = payload_772894()
        client = cliente(SimpleNamespace(content=[], stop_reason="end_turn", usage=None))
        diagnosi = {}
        self.assertFalse(sistema(payload, client, diagnosi))
        self.assertEqual(diagnosi["motivo"],
                         "titolo 88 caratteri anche dopo la richiamata (richiamata senza risposta)")

    def test_il_taglio_meccanico_del_titolo_non_esiste_piu(self):
        self.assertFalse(hasattr(seo_skill, "accorcia_titolo"))


class TestEnrichSeoTitolo(unittest.TestCase):
    """Di punta in punta: due chiamate al massimo, e solo sui non pubblicati."""

    def _arricchisci(self, client, **opzioni):
        diagnosi = {}
        with mock.patch.object(seo_skill, "_get_anthropic_client", return_value=client), \
             mock.patch.object(db, "slug_exists", return_value=False):
            esito = asyncio.run(seo_skill.enrich_seo(
                {"id": 772894, "titolo_raw": "CCIAA Pistoia-Prato - Bando"}, "",
                diagnosi=diagnosi, **opzioni))
        return esito, diagnosi

    def test_non_pubblicato_richiamata_e_payload_salvo(self):
        client = cliente(risposta_tool("save_seo_bando", payload_772894()),
                         risposta_tool("riscrivi_titolo", {"titolo": TITOLO_RISCRITTO}))
        esito, _d = self._arricchisci(client, ripara_lunghezze=True)
        self.assertIsNotNone(esito)
        self.assertEqual(esito["titolo"], TITOLO_RISCRITTO)
        self.assertEqual(client.messages.create.await_count, 2)

    def test_non_pubblicato_ancora_lungo_nel_motivo_del_giro(self):
        lungo = "Contributi " + "x" * 74
        client = cliente(risposta_tool("save_seo_bando", payload_772894()),
                         risposta_tool("riscrivi_titolo", {"titolo": lungo}))
        esito, diagnosi = self._arricchisci(client, ripara_lunghezze=True)
        self.assertIsNone(esito)
        self.assertEqual(diagnosi["motivo"], "titolo 85 caratteri anche dopo la richiamata")
        self.assertEqual(client.messages.create.await_count, 2)

    def test_pubblicato_nessuna_richiamata(self):
        client = cliente(risposta_tool("save_seo_bando", payload_772894()))
        esito, _d = self._arricchisci(client, titolo_congelato=True)
        self.assertIsNotNone(esito)
        self.assertEqual(esito["titolo"], TITOLO_772894)        # non si scrive: non si tocca
        self.assertEqual(client.messages.create.await_count, 1)


class TestAccorciaDescrizione(unittest.TestCase):
    def test_taglio_all_ultima_frase_intera(self):
        prima = "A" * 170 + " frase uno finita qui."          # 192 caratteri: >= 180
        testo = prima + " " + "b" * 200
        self.assertEqual(seo_skill.accorcia_descrizione(testo), prima)
        # Sotto i 180 la frase intera non basta: taglio alla parola.
        corta = "A" * 150 + " frase uno finita qui."
        self.assertTrue(seo_skill.accorcia_descrizione(corta + " " + "b " * 150).endswith("…"))

    def test_frase_troppo_corta_taglio_alla_parola_con_puntini(self):
        testo = "Breve. " + " ".join(["parola"] * 60)
        corta = seo_skill.accorcia_descrizione(testo)
        self.assertLessEqual(len(corta), 320)
        self.assertGreaterEqual(len(corta), 180)
        self.assertTrue(corta.endswith("parola…"), corta[-20:])

    def test_il_punto_delle_migliaia_non_chiude_la_frase(self):
        testo = "Dotazione di 1.500.000 euro " + " ".join(["per le imprese"] * 30)
        corta = seo_skill.accorcia_descrizione(testo)
        self.assertTrue(corta.startswith("Dotazione di 1.500.000 euro"))
        self.assertTrue(corta.endswith("…"))
        self.assertLessEqual(len(corta), 320)

    def test_entro_il_limite_resta_com_e(self):
        self.assertEqual(seo_skill.accorcia_descrizione(DESCRIZIONE), DESCRIZIONE)


class TestValidazione(unittest.TestCase):
    def test_la_validazione_non_taglia_il_titolo(self):
        # Il titolo lo sistema `sistema_titolo`, prima: qui un titolo lungo
        # e' uno scarto anche con `ripara_lunghezze`.
        diagnosi = {}
        self.assertIsNone(valida(payload_772894(), ripara=True, diagnosi=diagnosi))
        self.assertEqual(diagnosi["motivo"], "titolo 88 caratteri (1-80)")

    def test_senza_riparazione_resta_lo_scarto_con_motivo(self):
        diagnosi = {}
        self.assertIsNone(valida(payload_772894(), ripara=False, diagnosi=diagnosi))
        self.assertEqual(diagnosi["motivo"], "titolo 88 caratteri (1-80)")

    def test_descrizione_lunga_tagliata_solo_se_si_ripara(self):
        lunga = DESCRIZIONE + " " + "Il contributo copre le spese per fiere e missioni. " * 4
        self.assertGreater(len(lunga), 320)
        esito = valida(payload_772894(titolo=TITOLO_CORTO, descrizione_breve=lunga), ripara=True)
        self.assertIsNotNone(esito)
        self.assertTrue(180 <= len(esito["descrizione_breve"]) <= 320)
        self.assertTrue(esito["descrizione_breve"].endswith("."))
        diagnosi = {}
        self.assertIsNone(valida(payload_772894(titolo=TITOLO_CORTO, descrizione_breve=lunga),
                                 ripara=False, diagnosi=diagnosi))
        self.assertEqual(diagnosi["motivo"],
                         f"descrizione_breve {len(lunga.strip())} caratteri (180-320)")

    def test_descrizione_corta_resta_scartata(self):
        diagnosi = {}
        self.assertIsNone(valida(payload_772894(titolo=TITOLO_CORTO, descrizione_breve="Troppo corta."),
                                 ripara=True, diagnosi=diagnosi))
        self.assertEqual(diagnosi["motivo"], "descrizione_breve 13 caratteri (180-320)")

    def test_campo_mancante_con_motivo(self):
        diagnosi = {}
        self.assertIsNone(valida(payload_772894(allegati=None), ripara=True, diagnosi=diagnosi))
        self.assertEqual(diagnosi["motivo"], "campo mancante: allegati")


class TestChiamata(unittest.TestCase):
    def _cliente(self, risposta=None, errore=None):
        crea = mock.AsyncMock(return_value=risposta, side_effect=errore)
        return SimpleNamespace(messages=SimpleNamespace(create=crea))

    def test_risposta_senza_tool_con_stop_reason(self):
        risposta = SimpleNamespace(content=[SimpleNamespace(type="text", text="...")],
                                   stop_reason="max_tokens", usage=None)
        diagnosi = {}
        esito = asyncio.run(seo_skill._call_anthropic_tool(
            self._cliente(risposta), "m", 100, "s", "u", seo_skill.SAVE_SEO_BANDO_TOOL,
            diagnosi=diagnosi))
        self.assertIsNone(esito)
        self.assertEqual(diagnosi["motivo"], "risposta senza il tool (stop_reason=max_tokens)")

    def test_errore_4xx_non_ripetibile(self):
        import anthropic
        import httpx
        risposta_http = httpx.Response(400, request=httpx.Request("POST", "https://api.invalid"))
        errore = anthropic.BadRequestError("credito esaurito", response=risposta_http, body=None)
        diagnosi = {}
        esito = asyncio.run(seo_skill._call_anthropic_tool(
            self._cliente(errore=errore), "m", 100, "s", "u", seo_skill.SAVE_SEO_BANDO_TOOL,
            diagnosi=diagnosi))
        self.assertIsNone(esito)
        self.assertEqual(diagnosi["motivo"], "API 400 non ripetibile")

    def test_payload_troncato_dal_tetto_di_token(self):
        troncato = payload_772894(titolo=TITOLO_CORTO)
        del troncato["tematica"]
        risposta = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="save_seo_bando", input=troncato)],
            stop_reason="max_tokens", usage=None)
        diagnosi = {}
        with mock.patch.object(seo_skill, "_get_anthropic_client",
                               return_value=self._cliente(risposta)):
            esito = asyncio.run(seo_skill.enrich_seo(
                {"id": 772894, "titolo_raw": "CCIAA"}, "", ripara_lunghezze=True,
                diagnosi=diagnosi))
        self.assertIsNone(esito)
        self.assertEqual(diagnosi["motivo"],
                         "campo mancante: tematica (risposta troncata: max_tokens)")


class TestRunner(unittest.TestCase):
    def _genera(self, stato):
        arricchisci = mock.AsyncMock(return_value=None)
        with mock.patch.object(runner, "_firecrawl_scrape_markdown",
                               new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_httpx_fetch_text", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci):
            generazione = asyncio.run(runner.genera_per_bando(
                {"id": 1, "link_bando": "", "stato_processing": stato}, {"id": 1}))
        return arricchisci.await_args.kwargs, generazione

    def test_si_ripara_solo_il_non_pubblicato(self):
        kwargs, _g = self._genera("enriched")
        self.assertTrue(kwargs["ripara_lunghezze"])
        kwargs, _g = self._genera("completed")
        self.assertFalse(kwargs["ripara_lunghezze"])

    def test_motivo_sconosciuto_se_nessuno_lo_scrive(self):
        _k, generazione = self._genera("enriched")
        self.assertIsNone(generazione.payload)
        self.assertEqual(generazione.motivo, "motivo sconosciuto")

    def test_i_motivi_in_ordine_numerico(self):
        esito = runner.motivi_del_giro({1262408: "b", 18278: "a", "x": "c"})
        self.assertEqual(list(esito["payload_failed_motivi"]), ["18278", "1262408", "x"])

    def test_tetto_dei_motivi(self):
        motivi = {i: f"motivo {i}" for i in range(52)}
        esito = runner.motivi_del_giro(motivi)
        self.assertEqual(len(esito["payload_failed_motivi"]), 50)
        self.assertEqual(esito["payload_failed_altri"], 2)
        self.assertEqual(runner.motivi_del_giro({}),
                         {"payload_failed_motivi": {}, "payload_failed_altri": 0})

    def test_la_riga_del_giro_porta_i_motivi(self):
        async def arricchisci(ctx, markdown, **kwargs):
            if ctx["id"] == 772894:
                kwargs["diagnosi"]["motivo"] = "titolo 88 caratteri (1-80)"
                return None
            return {"slug": "x", "titolo": "T", "descrizione_breve": "",
                    "contenuto": {"sections": []}, "livello": "flash_bando"}

        def contesto(b, _c):
            if b["id"] == 3:
                raise RuntimeError("catalogo rotto")
            return {"id": b["id"]}

        bandi = [{"id": 772894, "link_bando": ""}, {"id": 2, "link_bando": ""},
                 {"id": 3, "link_bando": ""}]
        with mock.patch.object(runner, "select_bandi_to_complete", return_value=bandi), \
             mock.patch.object(runner, "load_catalogo", return_value={}), \
             mock.patch.object(runner, "build_bando_input_context", side_effect=contesto), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci), \
             mock.patch.object(runner, "update_bando_completed",
                               new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(runner, "logger", mock.MagicMock()), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEDUP_CANONICAL", None)
            contatori = asyncio.run(runner.run())
        self.assertEqual(contatori["payload_failed"], 2)
        self.assertEqual(contatori["payload_failed_motivi"], {
            "3": "contesto non costruito: RuntimeError",
            "772894": "titolo 88 caratteri (1-80)",
        })
        self.assertEqual(contatori["payload_failed_altri"], 0)


class TestTitoloCongelato(unittest.TestCase):
    """Su un pubblicato il titolo non si scrive mai (rerun dei completed,
    seo-rigenera): la sua lunghezza non deve buttare il payload pagato. La
    descrizione invece si valida come prima, perche' seo-rigenera la scrive."""

    def _cliente(self, payload):
        risposta = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="save_seo_bando", input=payload)],
            stop_reason="tool_use", usage={"input_tokens": 1, "output_tokens": 1})
        return SimpleNamespace(messages=SimpleNamespace(create=mock.AsyncMock(return_value=risposta)))

    def _rete_finta(self, payload):
        return (
            mock.patch.object(seo_skill, "_get_anthropic_client", return_value=self._cliente(payload)),
            mock.patch.object(db, "slug_exists", return_value=False),
            mock.patch.object(runner, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="")),
            mock.patch.object(runner, "_httpx_fetch_text", new=mock.AsyncMock(return_value="")),
            mock.patch.object(runner, "_link_del_bando", return_value=([], False)),
        )

    def test_descrizione_facoltativa_non_scarta(self):
        with mock.patch.object(db, "slug_exists", return_value=False):
            esito = asyncio.run(seo_skill._validate_payload(
                payload_772894(descrizione_breve="Corta."), 1, {}, "",
                reachability_check=False, titolo_congelato=True, descrizione_facoltativa=True))
        self.assertIsNotNone(esito)
        self.assertEqual(esito["descrizione_breve"], "Corta.")

    def test_il_rerun_dei_completed_valida_ancora_la_descrizione(self):
        # Il rerun scrive sempre la descrizione: niente descrizione facoltativa.
        kwargs = {}

        async def arricchisci(ctx, markdown, **opzioni):
            kwargs.update(opzioni)
            return None

        with mock.patch.object(runner, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_httpx_fetch_text", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci):
            asyncio.run(runner.genera_per_bando(
                {"id": 1, "link_bando": "", "stato_processing": "completed"}, {"id": 1}))
        self.assertFalse(kwargs["descrizione_facoltativa"])
        kwargs.clear()
        with mock.patch.object(runner, "_firecrawl_scrape_markdown", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_httpx_fetch_text", new=mock.AsyncMock(return_value="")), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci):
            asyncio.run(runner.genera_per_bando(
                {"id": 1, "link_bando": "", "stato_processing": "enriched"}, {"id": 1},
                descrizione_facoltativa=True))
        self.assertFalse(kwargs["descrizione_facoltativa"])   # mai sui non pubblicati

    def test_validazione_titolo_congelato(self):
        with mock.patch.object(db, "slug_exists", return_value=False):
            esito = asyncio.run(seo_skill._validate_payload(
                payload_772894(), 1, {}, "", reachability_check=False, titolo_congelato=True))
        self.assertIsNotNone(esito)
        self.assertEqual(esito["titolo"], TITOLO_772894)        # non toccato: non si scrive
        diagnosi = {}
        with mock.patch.object(db, "slug_exists", return_value=False):
            self.assertIsNone(asyncio.run(seo_skill._validate_payload(
                payload_772894(descrizione_breve="Corta."), 1, {}, "",
                reachability_check=False, titolo_congelato=True, diagnosi=diagnosi)))
        self.assertIn("descrizione_breve", diagnosi["motivo"])

    def test_rerun_dei_completed_non_butta_il_payload(self):
        riga = {"id": 18145, "link_bando": "", "stato_processing": "completed"}
        aggiorna = mock.AsyncMock(return_value=True)
        rete = self._rete_finta(payload_772894())
        with rete[0], rete[1], rete[2], rete[3], rete[4], \
             mock.patch.object(runner, "select_bandi_to_complete", return_value=[riga]), \
             mock.patch.object(runner, "load_catalogo", return_value={}), \
             mock.patch.object(runner, "build_bando_input_context",
                               side_effect=lambda b, c: {"id": b["id"]}), \
             mock.patch.object(runner, "update_bando_completed", new=aggiorna), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEDUP_CANONICAL", None)
            contatori = asyncio.run(runner.run(include_completed=True))
        self.assertEqual(contatori["payload_ok"], 1)
        self.assertEqual(contatori["payload_failed"], 0)
        aggiorna.assert_awaited_once()
        self.assertTrue(aggiorna.await_args.kwargs["gia_pubblicato"])  # titolo non scritto

    def test_la_prova_di_seo_rigenera_non_butta_il_payload(self):
        import tempfile
        from pathlib import Path
        riga = {"id": 18145, "slug": "x", "stato_processing": "completed", "pubblicato": True,
                "bando_master_id": None, "link_bando": "", "descrizione_breve": DESCRIZIONE,
                "contenuto": {"sections": [{"type": "h2", "text": "Chi"}]}}
        rete = self._rete_finta(payload_772894())
        with tempfile.TemporaryDirectory() as cartella, rete[0], rete[1], rete[2], rete[3], \
                rete[4]:
            esito = asyncio.run(runner.run_seo_rigenera(
                [18145], righe=[riga], catalogo={}, contesto=lambda b, c: {"id": b["id"]},
                uscita=Path(cartella) / "p.json", stampa=lambda _r: None))
        self.assertEqual(esito["falliti"], 0)
        self.assertEqual(esito["proposte_salvate"], 1)


class TestPrompt(unittest.TestCase):
    def test_regola_2_dice_del_taglio(self):
        self.assertIn("massimo 80 caratteri contati, spazi compresi", seo_skill.SEO_SYSTEM_PROMPT)
        self.assertIn("un titolo più lungo viene rifiutato e dovrai riscriverlo",
                      seo_skill.SEO_SYSTEM_PROMPT)
        self.assertNotIn("tagliato all'ultima parola intera", seo_skill.SEO_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
