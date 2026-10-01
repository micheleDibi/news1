# -*- coding: utf-8 -*-
"""Il preprocess del giro 2 (contratto §6.3 con §19.5): pagina a 8 000 caratteri e ripieghi.

Fino al 30/09/2026 il modello vedeva i primi 4 000 caratteri della pagina,
quasi solo menu, e su LazioEuropa perdeva la scadenza. Ora entrano la testa
intera e le sezioni utili fino a 8 000, e dopo il modello, senza chiamarlo di
nuovo, la scadenza che manca si cerca nel lettore per ente, nella finestra di
presentazione e, per ultima, nell'etichetta dell'aggregatore citata sulla
scheda. I prompt non cambiano; `data_scadenza_verificata` non si tocca mai.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_preprocess_base
"""
import asyncio
import hashlib
import json
import re
import unittest
from datetime import date, time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from tests.supporto import carica_modulo

pre = carica_modulo("preprocessor")
runner = carica_modulo("bando_preprocess_runner")
scarico = carica_modulo("scarico")
etichette = carica_modulo("etichette_stato")
enricher = carica_modulo("enricher")
dv = carica_modulo("date_validation")

FIXTURE = Path(__file__).parent / "fixtures" / "etichette_stato"
OGGI = date(2026, 10, 2)

#: Le impronte dei due prompt: il giro 2 non li cambia. L'01/10/2026 (§21.1 del
#: contratto del giro 3) il system prompt prende una riga sola nel blocco
#: «STATO_BANDO DATA-DRIVEN» (con la scadenza da oggi in poi un 'chiuso' vale
#: 'aperto'): impronta di prima b4f292b7…53baa, la riga nuova la verifica
#: `test_la_sola_riga_nuova_del_21_1`. Il tool non cambia.
SHA_SYSTEM_PROMPT = "d0c8da21729dc8f9ee776b50f2080f7adfd2bb69d1dc2f993daa223b1577f594"
RIGA_21_1 = "- Se data_scadenza >= {oggi} (oggi) -> un 'chiuso' vale 'aperto'\n"
SHA_ANALYZE_TOOL = "89d1144086ba132c742f6dc7e32f5dc59c59fc067e283ace58373d0028e8fb90"


def _fixture(nome: str) -> str:
    return (FIXTURE / nome).read_text(encoding="utf-8")


def _candidata(data, quote, source="official_page"):
    return {"date": data, "source": source, "quote": quote}


def _valida(**campi):
    base = {"is_valid_bando": True, "confidence_score": 0.9, "rejection_reason": None,
            "stato_bando": "aperto", "data_pubblicazione": None, "data_apertura": None,
            "data_scadenza": None, "ora_apertura": None, "ora_scadenza": None,
            "_origine_scadenza": None, "_date_presunte_respinte": 0}
    base.update(campi)
    return base


class PromptInvariati(unittest.TestCase):

    def test_system_prompt_e_tool_non_cambiano(self):
        self.assertEqual(hashlib.sha256(pre.SYSTEM_PROMPT_TEMPLATE.encode()).hexdigest(),
                         SHA_SYSTEM_PROMPT)
        tool = json.dumps(pre.ANALYZE_TOOL, sort_keys=True, ensure_ascii=False)
        self.assertEqual(hashlib.sha256(tool.encode()).hexdigest(), SHA_ANALYZE_TOOL)

    def test_la_sola_riga_nuova_del_21_1(self):
        # Tolta la riga del §21.1 il prompt torna quello del giro 2, byte per byte.
        self.assertEqual(pre.SYSTEM_PROMPT_TEMPLATE.count(RIGA_21_1), 1)
        prima = pre.SYSTEM_PROMPT_TEMPLATE.replace(RIGA_21_1, "")
        self.assertEqual(hashlib.sha256(prima.encode()).hexdigest(),
                         "b4f292b7665536e6c02d55f2eaede4c7f173ac34ef8296b5d576dea4ad353baa")
        self.assertIn(">= 2 ottobre 2026 (oggi) -> un 'chiuso' vale 'aperto'", pre.system_prompt(OGGI))


class BloccoDellaPagina(unittest.TestCase):

    def test_budget_e_testa(self):
        self.assertEqual(pre.BUDGET_PROMPT_CHAR, 8000)
        self.assertEqual(pre.TESTA_PROMPT_CHAR, 1500)
        testo = "\n\n".join(f"Titolo {i}\nParagrafo {i} con la scadenza del 30/10/2026. " * 5
                            for i in range(200))
        blocco = pre.blocco_pagina(testo)
        self.assertLessEqual(len(blocco), pre.BUDGET_PROMPT_CHAR)
        self.assertTrue(blocco.startswith(testo[:pre.TESTA_PROMPT_CHAR]))
        self.assertEqual(pre.blocco_pagina(""), "")
        self.assertEqual(pre.blocco_pagina("corto"), "corto")

    def test_budget_diverso_si_rispetta(self):
        testo = "Aperto. " + "Sezione con date 30/10/2026 e domande.\n\n" * 400
        self.assertLessEqual(len(pre.blocco_pagina(testo, 4000)), 4000)

    def test_il_markdown_con_i_suoi_a_capo_resta_com_e(self):
        markdown = "# Bando\n\nTesto\n\n## Scadenza\nentro il 30/10/2026\n"
        self.assertEqual(pre.testo_strutturato(markdown, "<p>altro</p>"), markdown)
        self.assertEqual(pre.testo_strutturato("riga sola", None), "riga sola")

    def test_le_pagine_lazioeuropa_hanno_etichetta_e_scadenza_nel_blocco(self):
        # Le pagine vere del 30/09 (le 47 in cache non sono nel repo: queste
        # sono le 5 fixture del lettore). Il preprocess riceve il testo
        # visibile di httpx, una riga sola: il blocco si costruisce sui
        # paragrafi ricostruiti dall'HTML.
        nomi = sorted(p.name for p in FIXTURE.glob("lazioeuropa_*.html"))
        self.assertEqual(len(nomi), 5)
        persi_col_taglio_a_4000 = 0
        for nome in nomi:
            with self.subTest(pagina=nome):
                html = _fixture(nome)
                piatto = scarico.testo_da_html(html)
                blocco = pre.blocco_pagina(pre.testo_strutturato(piatto, html))
                self.assertLessEqual(len(blocco), pre.BUDGET_PROMPT_CHAR)
                lettura = etichette.leggi(html, "https://www.lazioeuropa.it/bandi/x", "", oggi=OGGI)
                self.assertIn(lettura.etichetta, blocco)
                for frase in re.findall(r"entro le ore \d{1,2}[:.]\d{2} del \d{1,2} \w+ \d{4}", piatto, re.I):
                    self.assertIn(dv.norm_cit(frase), dv.norm_cit(blocco), frase)
                    if dv.norm_cit(frase) not in dv.norm_cit(piatto[:4000]):
                        persi_col_taglio_a_4000 += 1
        # la ragione del cambio: col vecchio taglio queste scadenze restavano fuori
        self.assertGreaterEqual(persi_col_taglio_a_4000, 3)

    def test_il_prompt_usa_il_blocco(self):
        markdown = "Testa del bando\n\n" + "Sezione lunga senza date.\n\n" * 600 + "Scadenza: 30/10/2026\n"
        prompt = pre._build_user_prompt({"titolo_raw": "Bando"}, {}, markdown=markdown)
        self.assertIn(pre.blocco_pagina(markdown), prompt)
        self.assertIn("Scadenza: 30/10/2026", prompt)


class ProvenienzaEOre(unittest.TestCase):

    def test_provenienza_dall_host_di_link_bando(self):
        self.assertEqual(pre.provenienza_di("https://www.obiettivoeuropa.com/bandi/x/"), "aggregatore")
        self.assertEqual(pre.provenienza_di("https://www.lazioeuropa.it/bandi/x"), "ente")
        self.assertIsNone(pre.provenienza_di(""))
        self.assertIsNone(pre.provenienza_di(None))

    def test_la_provenienza_arriva_a_validate_date_candidate(self):
        viste = []

        def finta(*args, **kwargs):
            viste.append(kwargs.get("provenienza"))
            return None

        with patch.object(dv, "validate_date_candidate", finta):
            pre._validate_analysis(_valida(), "testo", 1, provenienza="aggregatore")
        self.assertEqual(viste, ["aggregatore"] * 3)

    def test_ore_dalla_citazione(self):
        testo = ("Le domande si presentano a partire dalle ore 09:30 del 01/10/2026 "
                 "ed entro le ore 12:00 del 30/10/2026.")
        esito = pre._validate_analysis(_valida(
            data_apertura=_candidata("2026-10-01", "a partire dalle ore 09:30 del 01/10/2026"),
            data_scadenza=_candidata("2026-10-30", "entro le ore 12:00 del 30/10/2026"),
        ), testo, 1)
        self.assertEqual(esito["data_scadenza"], "2026-10-30")
        self.assertEqual(esito["ora_scadenza"], "12:00:00")
        self.assertEqual(esito["ora_apertura"], "09:30:00")
        self.assertEqual(esito["_origine_scadenza"], "modello")

    def test_senza_ora_nella_citazione_nessuna_ora(self):
        testo = "Scadenza: 30/10/2026."
        esito = pre._validate_analysis(_valida(data_scadenza=_candidata("2026-10-30", "Scadenza: 30/10/2026")),
                                       testo, 1)
        self.assertEqual(esito["data_scadenza"], "2026-10-30")
        self.assertIsNone(esito["ora_scadenza"])

    def test_contatore_delle_date_presunte(self):
        testo = "Data presunta di scadenza: 30/10/2026. Pubblicato il 01/09/2026."
        esito = pre._validate_analysis(_valida(
            data_scadenza=_candidata("2026-10-30", "Data presunta di scadenza: 30/10/2026"),
            data_pubblicazione=_candidata("2026-09-01", "Pubblicato il 01/09/2026"),
        ), testo, 1)
        self.assertIsNone(esito["data_scadenza"])
        self.assertEqual(esito["data_pubblicazione"], "2026-09-01")
        self.assertEqual(esito["_date_presunte_respinte"], 1)
        # una citazione che non e' nella pagina non e' una data presunta: e' un'altra cosa
        esito = pre._validate_analysis(_valida(
            data_scadenza=_candidata("2026-10-30", "Data presunta: 30/10/2026")), "altro testo", 1)
        self.assertEqual(esito["_date_presunte_respinte"], 0)


def _lettura(stato="aperto", termine=None, puo_chiudere=False, estrattore="lazioeuropa", solo_segnale=False):
    return etichette.Lettura(estrattore, stato, stato.capitalize(), puo_chiudere=puo_chiudere,
                             solo_segnale=solo_segnale, termine_finale=termine)


class DopoIlModello(unittest.TestCase):

    BANDO = {"id": 1, "raw_data": {}}

    def test_lettore_per_ente_da_la_scadenza_se_il_modello_non_l_ha_data(self):
        termine = etichette.TermineFinale(date(2026, 10, 29), time(17, 0), "entro le ore 17:00 del 29 ottobre 2026")
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, "", _lettura(termine=termine), oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["ora_scadenza"], esito["_origine_scadenza"]),
                         ("2026-10-29", "17:00:00", "lettore"))
        self.assertEqual(esito["stato_bando"], "aperto")

    def test_la_scadenza_del_modello_non_si_tocca(self):
        termine = etichette.TermineFinale(date(2026, 12, 31), None, "x")
        analisi = _valida(data_scadenza="2026-10-30", ora_scadenza="12:00:00", _origine_scadenza="modello")
        esito = pre.completa_dopo_il_modello(analisi, self.BANDO, "", _lettura(termine=termine), oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["ora_scadenza"], esito["_origine_scadenza"]),
                         ("2026-10-30", "12:00:00", "modello"))

    def test_un_termine_prima_della_pubblicazione_non_vale(self):
        termine = etichette.TermineFinale(date(2026, 8, 1), None, "x")
        esito = pre.completa_dopo_il_modello(_valida(data_pubblicazione="2026-09-01"), self.BANDO, "",
                                             _lettura(termine=termine), oggi=OGGI)
        self.assertIsNone(esito["data_scadenza"])

    def test_chiuso_del_lettore_chiude_solo_con_puo_chiudere(self):
        chiuso = pre.completa_dopo_il_modello(_valida(), self.BANDO, "",
                                              _lettura("chiuso", puo_chiudere=True), oggi=OGGI)
        self.assertEqual(chiuso["stato_bando"], "chiuso")
        self.assertTrue(chiuso["_chiuso_da_lettore"])
        segnale = pre.completa_dopo_il_modello(_valida(), self.BANDO, "",
                                               _lettura("chiuso", puo_chiudere=False), oggi=OGGI)
        self.assertEqual(segnale["stato_bando"], "aperto")

    def test_finestra_di_presentazione(self):
        testo = ("L'invio delle Domande deve avvenire a partire dalle ore 12:00 del 30 settembre 2026 "
                 "ed entro le ore 17:00 del 29 ottobre 2026.")
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, testo, None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["ora_scadenza"], esito["_origine_scadenza"]),
                         ("2026-10-29", "17:00:00", "finestra"))

    def test_finestra_presunta_o_non_di_presentazione_non_vale(self):
        for testo in ("Le domande potranno essere presentate indicativamente dal 01/10/2026 al 30/10/2026.",
                      "La fiera si svolge dal 01/10/2026 al 30/10/2026."):
            with self.subTest(testo=testo):
                esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, testo, None, oggi=OGGI)
                self.assertIsNone(esito["data_scadenza"])

    def test_una_scadenza_passata_chiude(self):
        testo = "Le domande si presentano dal 01/09/2026 al 30/09/2026."
        esito = pre.completa_dopo_il_modello(_valida(), self.BANDO, testo, None, oggi=OGGI)
        self.assertEqual((esito["data_scadenza"], esito["stato_bando"]), ("2026-09-30", "chiuso"))

    def test_un_bando_non_valido_non_si_tocca(self):
        analisi = _valida(is_valid_bando=False, stato_bando=None)
        testo = "Le domande si presentano dal 01/10/2026 al 30/10/2026."
        esito = pre.completa_dopo_il_modello(analisi, self.BANDO, testo, None, oggi=OGGI)
        self.assertIsNone(esito["data_scadenza"])


class SchedaDellAggregatore(unittest.TestCase):
    """La `deadline_label` citata sulla scheda dell'aggregatore (§19.5).

    NB: nelle fixture manca una scheda vera dell'aggregatore. Le forme della
    citazione («Scadenza: <etichetta>», «Scadenza: <data>», l'etichetta intera)
    sono quelle approvate dal lead il 30/09; il testo qui sotto e' sintetico.
    """

    def _oe(self, status, etichetta="Scade il 30/11/2026", **extra):
        return {"id": 9, "raw_data": {"status": status, "deadline_label": etichetta, **extra}}

    def test_status_1_con_la_citazione_sulla_scheda(self):
        for testo in ("Programma X. Scadenza: 30/11/2026. Beneficiari: imprese.",
                      "Programma X. Scadenza: Scade il 30/11/2026 Beneficiari: imprese.",
                      "Programma X. Scade il 30/11/2026. Beneficiari: imprese."):
            with self.subTest(testo=testo):
                esito = pre.completa_dopo_il_modello(_valida(), self._oe("1"), testo, None, oggi=OGGI)
                self.assertEqual((esito["data_scadenza"], esito["_origine_scadenza"]),
                                 ("2026-11-30", "etichetta_oe"))
                self.assertIsNone(esito["ora_scadenza"])

    def test_senza_citazione_nessuna_data(self):
        for testo in ("Programma X. Beneficiari: imprese.", "La scadenza è il 30/11/2026.",
                      "Scadenza: 31/12/2026"):
            with self.subTest(testo=testo):
                esito = pre.completa_dopo_il_modello(_valida(), self._oe("1"), testo, None, oggi=OGGI)
                self.assertIsNone(esito["data_scadenza"])

    def test_etichetta_passata_o_status_diverso_da_1(self):
        testo = "Scadenza: 30/09/2026. Scadenza: 30/11/2026."
        passata = pre.completa_dopo_il_modello(_valida(), self._oe("1", "Scade il 30/09/2026"),
                                               testo, None, oggi=OGGI)
        self.assertIsNone(passata["data_scadenza"])
        for status in ("", "3", None):
            with self.subTest(status=status):
                esito = pre.completa_dopo_il_modello(_valida(), self._oe(status), testo, None, oggi=OGGI)
                self.assertIsNone(esito["data_scadenza"])

    def test_status_2_e_in_apertura(self):
        esito = pre.completa_dopo_il_modello(_valida(stato_bando="aperto"), self._oe("2"), "", None, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "in apertura prossimamente")
        self.assertTrue(esito["_status2_in_apertura"])

    def test_status_2_con_scadenza_passata_resta_chiuso(self):
        esito = pre.completa_dopo_il_modello(_valida(data_scadenza="2026-09-01", _origine_scadenza="modello"),
                                             self._oe("2"), "", None, oggi=OGGI)
        self.assertEqual(esito["stato_bando"], "chiuso")
        self.assertFalse(esito["_status2_in_apertura"])

    def test_on_arrival_non_conta(self):
        testo = "Programma X. Beneficiari: imprese."
        esito = pre.completa_dopo_il_modello(_valida(), self._oe("1", on_arrival=True), testo, None, oggi=OGGI)
        self.assertEqual((esito["stato_bando"], esito["data_scadenza"]), ("aperto", None))


class LetturaDellaPagina(unittest.IsolatedAsyncioTestCase):

    def test_lettore_generico_e_solo_segnale_restano_fuori(self):
        pagina = scarico.Risposta(url="https://www.lazioeuropa.it/bandi/x", stato=200,
                                  html=_fixture("lazioeuropa_aperto_1072674.html"))
        lettura = pre.lettura_per_ente(pagina, pagina.url, "", OGGI)
        self.assertEqual((lettura.estrattore, lettura.stato), ("lazioeuropa", "aperto"))
        generica = scarico.Risposta(url="https://www.esempio.it/b", stato=200,
                                    html="<main><h1>Bando chiuso</h1><p>Il bando è chiuso.</p></main>")
        self.assertIsNone(pre.lettura_per_ente(generica, generica.url, "", OGGI))
        self.assertIsNone(pre.lettura_per_ente(None, "u", "", OGGI))

    async def test_la_rilettura_non_chiama_mai_firecrawl(self):
        chiamate = []

        async def firecrawl(url):
            chiamate.append(url)
            return {"html": "<p>x</p>", "markdown": "x"}

        async def nessuna_attesa(host):
            return None

        # una pagina da app client-side su un host che richiede JS: con
        # `principale=True` scatterebbe il ripiego
        shell = "<html><body><div id='app'></div>" + "<script>x</script>" * 50 + "</body></html>"
        trasporto = httpx.MockTransport(lambda richiesta: httpx.Response(200, text=shell))
        finto = scarico.Scarico(transport=trasporto, firecrawl=firecrawl, throttle=nessuna_attesa,
                                host_richiede_js=("www.ente.it",), tentativi=0)
        with patch.object(scarico, "scarico_corrente", lambda: finto):
            pagina = await pre._pagina_in_cache("https://www.ente.it/bando")
        self.assertEqual(chiamate, [])
        self.assertIsNotNone(pagina)
        # controprova: la pagina principale lo userebbe
        await finto.scarica("https://www.ente.it/altro", principale=True)
        self.assertEqual(chiamate, ["https://www.ente.it/altro"])
        await finto.chiudi()

    async def test_tempo_scaduto_e_nessuna_pagina(self):
        class Lento:
            async def scarica(self, url, **kwargs):
                await asyncio.sleep(1)

        with patch.object(scarico, "scarico_corrente", lambda: Lento()), \
                patch.object(pre, "TETTO_LETTORE_S", 0.01):
            self.assertIsNone(await pre._pagina_in_cache("https://www.ente.it/b"))


class AnalyzeBandoIntero(unittest.IsolatedAsyncioTestCase):

    async def test_lazioeuropa_senza_scadenza_dal_modello(self):
        html = _fixture("lazioeuropa_aperto_1072674.html")
        link = "https://www.lazioeuropa.it/bandi/x"
        piatto = scarico.testo_da_html(html)
        prompt_visti = []

        class Finto:
            chiesti = []

            async def scarica(self, url, **kwargs):
                self.chiesti.append(kwargs)
                return scarico.Risposta(url=url, stato=200, html=html, testo=piatto, url_finale=url)

        async def modello(client, *, user_prompt, **kwargs):
            prompt_visti.append(user_prompt)
            return object()

        risposta_modello = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto",
                            "data_pubblicazione": None, "data_apertura": None, "data_scadenza": None}
        finto = Finto()
        with patch.object(enricher, "_firecrawl_scrape_markdown", AsyncMock(return_value=piatto)), \
                patch.object(scarico, "scarico_corrente", lambda: finto), \
                patch.object(pre, "_get_anthropic_client", lambda: object()), \
                patch.object(pre, "_call_anthropic_with_retry", modello), \
                patch.object(pre, "_extract_tool_input", lambda r: dict(risposta_modello)), \
                patch.object(pre, "oggi_roma", lambda *a: OGGI):
            esito = await pre.analyze_bando({"id": 1072674, "titolo_raw": "Bando", "link_bando": link,
                                             "raw_data": {}}, {})
        self.assertEqual(finto.chiesti, [{"principale": False}])
        self.assertIn("entro le ore 17:00 del 29 ottobre 2026", prompt_visti[0])
        self.assertEqual((esito["data_scadenza"], esito["ora_scadenza"], esito["_origine_scadenza"]),
                         ("2026-10-29", "17:00:00", "lettore"))
        self.assertEqual(esito["stato_bando"], "aperto")


class Runner(unittest.IsolatedAsyncioTestCase):

    def test_le_ore_si_scrivono_solo_quando_ci_sono(self):
        con = runner._build_update(1, _valida(data_scadenza="2026-10-30", ora_scadenza="12:00:00"))
        self.assertEqual(con["ora_scadenza"], "12:00:00")
        self.assertNotIn("ora_apertura", con)
        senza = runner._build_update(1, _valida(data_scadenza="2026-10-30"))
        self.assertNotIn("ora_scadenza", senza)
        self.assertNotIn("data_scadenza_verificata", con)
        rifiutato = runner._build_update(1, _valida(is_valid_bando=False, ora_scadenza="12:00:00"))
        self.assertNotIn("ora_scadenza", rifiutato)

    async def test_contatori_del_giro(self):
        analisi = {
            1: _valida(data_scadenza="2026-10-30", ora_scadenza="12:00:00", _origine_scadenza="lettore",
                       _date_presunte_respinte=1),
            2: _valida(data_scadenza="2026-10-30", _origine_scadenza="finestra"),
            3: _valida(data_scadenza="2026-11-30", _origine_scadenza="etichetta_oe"),
            4: _valida(stato_bando="chiuso", _chiuso_da_lettore=True, _date_presunte_respinte=2),
            5: _valida(stato_bando="in apertura prossimamente", _status2_in_apertura=True,
                       data_apertura="2026-11-01", ora_apertura="09:00:00"),
        }

        async def analizza(bando, fonte):
            return dict(analisi[bando["id"]])

        righe = [{"id": i, "fonte_id": 1} for i in analisi]
        with patch.object(runner, "select_bandi_scraped", lambda limit=None: righe), \
                patch.object(runner, "select_fonti_by_ids", lambda ids: {}), \
                patch.object(runner, "enrich_fonti_with_names", lambda f: f), \
                patch.object(runner, "analyze_bando", analizza):
            contatori = await runner.run(dry_run=True)
        attesi = {"scadenze_da_lettore": 1, "scadenze_da_finestra": 1, "scadenze_da_etichetta_oe": 1,
                  "chiusi_da_lettore": 1, "status2_in_apertura": 1, "date_presunte_respinte": 3,
                  "with_ora_scadenza": 1, "with_ora_apertura": 1, "with_data_scadenza": 3}
        for chiave, valore in attesi.items():
            with self.subTest(contatore=chiave):
                self.assertEqual(contatori[chiave], valore)


if __name__ == "__main__":
    unittest.main()
