# -*- coding: utf-8 -*-
"""Passo verifica-stato (contratto `bandi-giro-2` §5 con §19.4, §19.6, §19.11).

Pagine vere (le fixture di `etichette_stato`), una `FonteDati` finta che
registra ogni scrittura, la rete finta (una funzione `scarica` o lo `Scarico`
vero con `httpx.MockTransport`). Il modello e l'adattatore della prosa sono
sempre iniettati: nessuna rete, nessun DB, nessuna chiamata al modello.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_verifica_stato
"""
import asyncio
import contextlib
import io
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from bs4 import BeautifulSoup

from tests.supporto import RADICE, carica_modulo

vs = carica_modulo("verifica_stato")
ev = carica_modulo("eventi")
es = carica_modulo("etichette_stato")
scarico = carica_modulo("scarico")
du = carica_modulo("dominio_ufficiale")
db = carica_modulo("db")
cli = carica_modulo("__main__")

ADESSO = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
OGGI = date(2026, 10, 1)
FIXTURE = RADICE / "tests" / "fixtures" / "etichette_stato"
INDICE = json.loads((FIXTURE / "indice.json").read_text(encoding="utf-8"))
#: Un host che nessuna tabella rende verificante.
URL_PRIVATO = "https://www.sito-privato-esempio.com/bando"


def _pagina(nome):
    return INDICE[nome]["url"], (FIXTURE / nome).read_text(encoding="utf-8")


def _titolo(html):
    zuppa = BeautifulSoup(html, "lxml")
    voce = zuppa.find("h1") or zuppa.find("title")
    return voce.get_text(" ", strip=True)


def _impostazioni(**kwargs):
    # Senza i tetti di numero dismessi (giro 3, §3 e §13): se il passo li
    # leggesse ancora, SimpleNamespace solleverebbe AttributeError.
    base = dict(verifica_stato_modalita="ombra", verifica_stato_tetto_s=900,
                verifica_stato_usa_modello=False, ingresso_sosta_giri=4)
    base.update(kwargs)
    return SimpleNamespace(**base)


def _riga(bando_id, url, html, **extra):
    riga = {
        "id": bando_id, "slug": f"bando-{bando_id}", "titolo": _titolo(html), "descrizione_breve": "",
        "stato_bando": "aperto", "stato_processing": "completed", "pubblicato": True,
        "data_apertura": None, "data_apertura_verificata": False, "ora_apertura": None,
        "data_scadenza": None, "ora_scadenza": None,
        "pubblicato_at": "2026-08-01T00:00:00+00:00", "created_at": "2026-06-01T00:00:00+00:00",
        "fonte_id": 1, "link_bando": url, "bando_master_id": None,
        "fonte_ufficiale_url": url, "fonte_ufficiale_stato": "trovata",
        "host_fonte": du.dominio_di(url), "raw_data": {},
    }
    riga.update(extra)
    return riga


def _voce(url, lettura, ore_fa=72, stato=None):
    return ev.LetturaStato(ADESSO - timedelta(hours=ore_fa), lettura.estrattore, url, lettura.etichetta,
                           stato or lettura.stato,
                           tuple((d.ruolo, d.data) for d in lettura.date if not d.presunta)).come_voce()


def _gia_letto(url, html, ore_fa=72, **extra):
    """Il controllo di un bando gia' letto `ore_fa` ore fa con la stessa lettura (G7e)."""
    lettura = es.leggi(html, url, "", oggi=OGGI)
    controllo = {"lettura_stato": {"storia": [_voce(url, lettura, ore_fa)], "http": 200, "url": url},
                 "lettura_stato_at": (ADESSO - timedelta(hours=ore_fa)).isoformat(),
                 "prossima_lettura_at": (ADESSO - timedelta(hours=1)).isoformat()}
    controllo.update(extra)
    return controllo


class Rete:
    """`scarica` finta: url -> (stato HTTP, html[, url finale])."""

    def __init__(self, pagine=None, attesa=0.0):
        self.pagine = dict(pagine or {})
        self.chiamate = []
        self.attesa = attesa

    async def __call__(self, url, *, principale=False, redirect="tutti", **_):
        self.chiamate.append((url, principale, redirect))
        if self.attesa:
            await asyncio.sleep(self.attesa)
        voce = self.pagine.get(url)
        if voce is None:
            return scarico.Risposta(url=url, stato=404)
        stato, html, *finale = voce
        return scarico.Risposta(url=url, stato=stato, html=html, testo=scarico.testo_da_html(html),
                                url_finale=finale[0] if finale else "")


class FonteFinta(vs.FonteDati):
    def __init__(self, righe=(), letture=None, tabella=None, enriched=(), migrazione=True,
                 rpc=None, testi=None, rifiuta=(), consumo=None):
        self.righe = [dict(r) for r in righe]
        self._letture = dict(letture or {})
        self.tabella = tabella
        self._enriched = [dict(r) for r in enriched]
        self.migrazione = migrazione
        self.rpc = rpc
        self.testi = testi
        self.rifiuta = set(rifiuta)
        self.consumo = dict(consumo or {})
        self.riletti, self.eventi_letti = [], []
        self.recenti = {}
        self.link = {}
        self.scritte, self.ingressi, self.registrate = {}, [], []
        self.applicati, self.leggibili, self.runs = [], [], []

    def migrazione_presente(self):
        return self.migrazione

    def candidati(self):
        return [dict(r) for r in self.righe]

    def enriched(self):
        return [dict(r) for r in self._enriched]

    def letture(self, ids=None, dal=None):
        if ids is not None:
            return {i: dict(self._letture[i]) for i in ids if i in self._letture}
        return {i: dict(c) for i, c in self._letture.items()}

    def link_bando(self, ids):
        return {i: [dict(r) for r in self.link[i]] for i in ids if i in self.link}

    def tabella_domini(self):
        return self.tabella

    def eventi_recenti(self, bando_id, dal):
        self.eventi_letti.append(bando_id)
        return [dict(e) for e in self.recenti.get(bando_id, ())]

    def stato_attuale(self, bando_id):
        self.riletti.append(bando_id)
        return next((r["stato_bando"] for r in self.righe if r["id"] == bando_id), None)

    def consumo_oggi(self):
        # None = lettura fallita (§18.5), come `db.consumo_oggi`.
        return None if self.consumo is None else dict(self.consumo)

    def scrivi_lettura(self, bando_id, colonne):
        self.scritte[bando_id] = dict(colonne)
        return True

    def scrivi_ingresso(self, bando_id, colonne_bando, colonne_controllo):
        self.ingressi.append((bando_id, colonne_bando, colonne_controllo))
        if bando_id in self.rifiuta:
            return {"bando": False, "controllo": False, "rifiutato": "pubblicato"}
        return {"bando": bool(colonne_bando), "controllo": True, "rifiutato": None}

    def registra(self, riga):
        self.registrate.append(dict(riga))
        if self.rpc is not None:
            return self.rpc(riga)
        return {"id": len(self.registrate), "nuovo": True}

    def applica(self, evento_id):
        self.applicati.append(evento_id)
        return "applicato"

    def rendi_leggibile(self, evento_id, in_aggiornamenti):
        self.leggibili.append((evento_id, in_aggiornamenti))
        return True

    def testi_del_bando(self, bando_id):
        return self.testi

    def scrivi_run(self, riga):
        self.runs.append(riga)


def _passo(fonte, rete, **kwargs):
    kwargs.setdefault("impostazioni", _impostazioni())
    kwargs.setdefault("adesso", ADESSO)
    giro = kwargs.pop("giro", "06:00")
    return asyncio.run(vs.esegui_passo(giro, fonte_dati=fonte, scarica=rete, **kwargs))


def _tabella(*url):
    return du.costruisci(fonti=[{"link": u} for u in url])


def _chiusura_lombardia(**kwargs):
    """Il 18344 di Lombardia («Chiuso», puo' chiudere) letto anche 72 ore fa."""
    url, html = _pagina("lombardia_chiuso_18344.html")
    fonte = FonteFinta([_riga(18344, url, html)], {18344: _gia_letto(url, html)}, _tabella(url), **kwargs)
    return fonte, Rete({url: (200, html)}), url, html


class TestOmbra(unittest.TestCase):
    def test_nessun_evento_nessuno_stato_letto_nessun_esame(self):
        fonte, rete, url, _ = _chiusura_lombardia()
        esito = _passo(fonte, rete)
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(fonte.registrate, [])
        colonne = fonte.scritte[18344]
        self.assertNotIn("esaminato_attivo_at", colonne)
        self.assertFalse(any(c.startswith("stato_letto") for c in colonne))
        self.assertEqual(colonne["lettura_stato"]["proposta"]["trattenuta"], "ombra")
        self.assertEqual(colonne["lettura_stato"]["estrattore"], "lombardia")
        self.assertEqual(len(colonne["lettura_stato"]["storia"]), 2)
        self.assertEqual(esito["counters"]["proposte_per_tipo"], {"chiusura": 1})
        self.assertEqual(esito["proposte"], [{
            "bando_id": 18344, "tipo": "chiusura", "campo": None,
            "gate": {"superati": esito["proposte"][0]["gate"]["superati"], "falliti": []},
            "esito": "ammessa", "trattenuta": "ombra"}])
        self.assertEqual(esito["slug_modificati"], [])
        self.assertEqual(rete.chiamate, [(url, False, "stesso_host")])
        # Anche in ombra G9 legge lo stato di adesso e G5/G8 gli eventi recenti (revisione #96).
        self.assertEqual((fonte.riletti, fonte.eventi_letti), ([18344], [18344]))

    def test_chiusura_di_due_giorni_fa_scarta_la_proposta(self):
        # G8 anche in ombra: la stessa chiusura e' gia' stata registrata due giorni fa.
        fonte, rete, _, _ = _chiusura_lombardia()
        fonte.recenti[18344] = [{"tipo": "chiusura", "campo": None, "valore_dopo": {"stato_bando": "chiuso"},
                                 "data_evento": None, "rilevato_at": (ADESSO - timedelta(days=2)).isoformat()}]
        esito = _passo(fonte, rete)
        [proposta] = esito["proposte"]
        self.assertEqual((proposta["tipo"], proposta["esito"], proposta["gate"]["falliti"]),
                         ("chiusura", "scartata", ["G8"]))
        self.assertEqual(esito["counters"]["proposte_per_tipo"], {})
        self.assertFalse(fonte.scritte[18344]["lettura_stato"]["proposta"]["ammessa"])

    def test_riga_verifica_mai_registrata_in_ombra(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        with patch.object(vs.eventi_mod, "riga_verifica", wraps=ev.riga_verifica) as spia:
            _passo(fonte, rete)
        spia.assert_not_called()
        self.assertEqual(fonte.registrate, [])

    def test_riga_di_pipeline_run(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        _passo(fonte, rete)
        self.assertEqual(len(fonte.runs), 1)
        riga = fonte.runs[0]
        self.assertEqual((riga.step, riga.giro, riga.esito), ("verifica_stato", "06:00", "ok"))
        self.assertEqual((riga.contatori["fase"], riga.contatori["modalita"]), ("controlli", "ombra"))

    def test_dry_run_non_scrive_niente(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        esito = _passo(fonte, rete, dry_run=True)
        self.assertEqual((fonte.scritte, fonte.runs, fonte.registrate), ({}, [], []))
        self.assertEqual(len(esito["proposte"]), 1)


class TestAttivo(unittest.TestCase):
    def test_registra_applica_leggibile(self):
        fonte, rete, url, _ = _chiusura_lombardia()
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual([r["tipo"] for r in fonte.registrate], ["chiusura"])
        self.assertEqual(fonte.applicati, [1])
        self.assertEqual([e for e, _ in fonte.leggibili], [1])
        colonne = fonte.scritte[18344]
        self.assertEqual((colonne["stato_letto"], colonne["stato_letto_metodo"], colonne["stato_letto_url"]),
                         ("chiuso", "estrattore", url))
        self.assertEqual(colonne["stato_letto_su"], "aperto")
        self.assertIn("esaminato_attivo_at", colonne)
        self.assertEqual(esito["slug_modificati"], ["bando-18344"])
        self.assertEqual(esito["counters"]["slug_modificati"], ["bando-18344"])
        self.assertEqual(esito["ids_da_rigenerare"], [18344])
        self.assertEqual(esito["counters"]["applicati_per_tipo"], {"chiusura": 1})
        self.assertEqual(esito["counters"]["prosa_non_riscritta"], 0)

    def test_rpc_in_errore_nessun_insert(self):
        fonte, rete, _, _ = _chiusura_lombardia(rpc=lambda riga: None)
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(len(fonte.registrate), 1)
        self.assertEqual((fonte.applicati, fonte.leggibili), ([], []))
        self.assertEqual(esito["counters"]["eventi_non_scritti"], 1)
        self.assertEqual(esito["slug_modificati"], [])

    def test_rendi_leggibile_fallito_avvisa_nel_journal(self):
        fonte, rete, _, _ = _chiusura_lombardia(rpc=lambda riga: {"id": 41, "nuovo": True})
        fonte.rendi_leggibile = lambda evento_id, in_aggiornamenti: False
        with patch.object(vs, "logger", MagicMock()) as finto:
            esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(esito["counters"]["eventi_non_leggibili"], 1)
        avvisi = [c.args for c in finto.warning.call_args_list]
        self.assertIn(("[verifica_stato] evento {} applicato ma non leggibile (bando {})", 41, 18344), avvisi)

    def test_supabase_leggibile_falso_con_colonne_mancanti(self):
        for risposta, atteso in (({"scritto": False, "ignorate": ("leggibile",), "motivo": "colonne_assenti"}, False),
                                 ({"scritto": True, "ignorate": (), "motivo": ""}, True)):
            with self.subTest(atteso=atteso), patch.object(db, "rendi_evento_leggibile", return_value=risposta):
                self.assertIs(vs.FonteDatiSupabase().rendi_leggibile(41, True), atteso)

    def test_evento_gia_registrato_non_si_riapplica(self):
        fonte, rete, _, _ = _chiusura_lombardia(rpc=lambda riga: {"id": 7, "nuovo": False})
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(fonte.applicati, [])
        self.assertEqual(esito["slug_modificati"], [])

    def test_tabella_domini_del_contesto_e_quella_letta_dal_db(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        with patch.object(vs.eventi_mod, "valuta_verifica", wraps=ev.valuta_verifica) as spia:
            _passo(fonte, rete, modalita="attivo")
        self.assertIs(spia.call_args.args[1].tabella_domini, fonte.tabella)

    def test_nessun_tetto_di_chiusure_per_giro(self):
        # Giro 3, §13: niente VERIFICA_STATO_MAX_CHIUSURE (20). Le 21 chiusure
        # ammesse si registrano tutte nello stesso giro; resta il freno per host.
        url, html = _pagina("lombardia_chiuso_18344.html")
        ids = list(range(100, 121))
        fonte = FonteFinta([_riga(i, url, html) for i in ids], {i: _gia_letto(url, html) for i in ids},
                           _tabella(url))
        esito = _passo(fonte, Rete({url: (200, html)}), modalita="attivo")
        self.assertEqual(sorted(r["bando_id"] for r in fonte.registrate), ids)
        self.assertNotIn("chiusure_oltre_tetto", esito["counters"])
        self.assertEqual([p for p in esito["proposte"] if p["trattenuta"] == "tetto"], [])
        self.assertEqual(esito["copertura"],
                         {"candidati": 21, "fatti": 21, "rimasti": 0, "motivo_rimasti": None})


class TestFreno(unittest.TestCase):
    def _letture_del_freno(self, url, html, ore_chiuso):
        lettura = es.leggi(html, url, "", oggi=OGGI)
        return {900 + i: {"lettura_stato": {"storia": [
            _voce(url, lettura, 24 * 10, stato="aperto"), _voce(url, lettura, ore_chiuso, stato="chiuso")]}}
            for i in range(5)}

    def test_freno_scatta_e_trattiene(self):
        fonte, rete, url, html = _chiusura_lombardia()
        fonte._letture.update(self._letture_del_freno(url, html, ore_chiuso=48))
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(fonte.registrate, [])
        self.assertEqual(esito["counters"]["trattenute_per_freno"], {"lombardia": 1})
        self.assertEqual(esito["proposte"][0]["trattenuta"], "freno")
        self.assertEqual(fonte.scritte[18344]["prossima_lettura_at"], (ADESSO + timedelta(days=1)).isoformat())

    def test_freno_si_sblocca_fuori_dalla_finestra(self):
        fonte, rete, url, html = _chiusura_lombardia()
        fonte._letture.update(self._letture_del_freno(url, html, ore_chiuso=24 * 8))
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual([r["tipo"] for r in fonte.registrate], ["chiusura"])
        self.assertEqual(esito["counters"]["trattenute_per_freno"], {})

    def test_freno_puro(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        letture = self._letture_del_freno(url, html, ore_chiuso=48)
        freno = vs.Freno.da_letture(letture, ADESSO)
        self.assertEqual(freno.frenati(), {(du.dominio_di(url), "lombardia")})
        self.assertFalse(vs.Freno.da_letture(dict(list(letture.items())[:4]), ADESSO).frenati())


class TestPagine(unittest.TestCase):
    def test_illeggibile_nessun_fetch_ma_esaminato_in_attivo(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        riga = _riga(5, URL_PRIVATO, html, fonte_ufficiale_url=None, fonte_ufficiale_stato="non_trovata")
        fonte = FonteFinta([riga], {}, _tabella(url))
        rete = Rete()
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(rete.chiamate, [])
        colonne = fonte.scritte[5]
        self.assertIn("esaminato_attivo_at", colonne)
        self.assertEqual(colonne["lettura_stato"]["pagina"], "illeggibile")
        self.assertEqual(colonne["prossima_lettura_at"], (ADESSO + timedelta(days=14)).isoformat())
        self.assertEqual((esito["counters"]["illeggibili"], esito["counters"]["letti"]), (1, 0))

    def test_404_due_volte_pagina_rimossa(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        fonte = FonteFinta([_riga(6, url, html)], {}, _tabella(url))
        esito = _passo(fonte, Rete())
        prima = fonte.scritte[6]
        self.assertEqual(prima["lettura_stato"]["esito"], "da_riprovare")
        self.assertEqual(prima["prossima_lettura_at"], (ADESSO + timedelta(days=1)).isoformat())
        self.assertEqual((esito["counters"]["da_riprovare"], esito["counters"]["errori_rete"]), (1, 0))
        fonte = FonteFinta([_riga(6, url, html)], {6: {"lettura_stato": prima["lettura_stato"]}}, _tabella(url))
        esito = _passo(fonte, Rete())
        self.assertEqual(fonte.scritte[6]["lettura_stato"]["esito"], "pagina_rimossa")
        self.assertEqual(esito["counters"]["pagine_rimosse"], 1)

    def test_da_riprovare_di_fila_rallentano(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        controllo, cadenze = {}, []
        for _ in range(4):
            fonte = FonteFinta([_riga(6, url, html)], {6: controllo}, _tabella(url))
            _passo(fonte, Rete({url: (503, "")}))
            controllo = {"lettura_stato": fonte.scritte[6]["lettura_stato"]}
            cadenze.append(fonte.scritte[6]["prossima_lettura_at"])
        giorni = [(ADESSO + timedelta(days=g)).isoformat() for g in (1, 1, 3, 14)]
        self.assertEqual(cadenze, giorni)
        self.assertEqual(controllo["lettura_stato"]["da_riprovare_di_fila"], 4)
        # Un altro url ricomincia da capo.
        controllo["lettura_stato"]["url"] = "https://www.bandi.regione.lombardia.it/altra"
        fonte = FonteFinta([_riga(6, url, html)], {6: controllo}, _tabella(url))
        _passo(fonte, Rete({url: (503, "")}))
        self.assertEqual(fonte.scritte[6]["lettura_stato"]["da_riprovare_di_fila"], 1)

    def test_termine_dalla_pagina_resta_se_oggi_non_si_legge(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        controllo = {"termine_indicato": "2026-12-31", "termine_indicato_fonte": "pagina"}
        fonte = FonteFinta([_riga(6, url, html)], {6: controllo}, _tabella(url))
        _passo(fonte, Rete({url: (503, "")}))
        self.assertEqual(fonte.scritte[6]["lettura_stato"]["esito"], "da_riprovare")
        self.assertFalse({"termine_indicato", "termine_indicato_fonte"} & set(fonte.scritte[6]))

    def test_pagina_rimossa_toglie_il_termine_della_pagina(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        controllo = {"termine_indicato": "2026-12-31", "termine_indicato_fonte": "pagina",
                     "lettura_stato": {"http": 404, "url": url, "esito": "da_riprovare"}}
        fonte = FonteFinta([_riga(6, url, html)], {6: controllo}, _tabella(url))
        _passo(fonte, Rete())
        colonne = fonte.scritte[6]
        self.assertEqual(colonne["lettura_stato"]["esito"], "pagina_rimossa")
        self.assertEqual((colonne["termine_indicato"], colonne["termine_indicato_fonte"]), (None, None))

    def test_pagina_ii_c_col_titolo_basso_non_decide(self):
        # Il candidato prioritario sullo stesso host, che parla d'altro: non decide
        # e non marca il bando come «forse non un bando» (revisione ciclo 2).
        url, html = _pagina("lombardia_aperto_17664.html")
        riga = _riga(7, None, html, fonte_ufficiale_url=None, fonte_ufficiale_stato="in_verifica",
                     link_bando=None, host_fonte=du.dominio_di(url), titolo="Contributi per la pesca d'altura")
        fonte = FonteFinta([riga], {7: {"candidato_prioritario": url}}, _tabella(url))
        _passo(fonte, Rete({url: (200, html)}), modalita="attivo")
        lettura = fonte.scritte[7]["lettura_stato"]
        self.assertEqual((lettura["pagina"], lettura["esito"], lettura["livello_titolo"]), ("ii-c", "non_decisiva", "basso"))
        self.assertFalse(lettura["forse_non_un_bando"])
        self.assertNotIn("stato_letto", fonte.scritte[7])

    def test_pagina_iv_mai_eventi(self):
        fonte, rete, url, _ = _chiusura_lombardia()
        fonte.righe[0].update(fonte_ufficiale_stato="non_trovata", fonte_ufficiale_url=None,
                              host_fonte="altro-ente-esempio.it")
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(fonte.scritte[18344]["lettura_stato"]["pagina"], "iv")
        self.assertEqual(fonte.registrate, [])
        self.assertTrue(esito["proposte"])
        self.assertTrue(all(p["esito"] == "scartata" for p in esito["proposte"]))

    def test_generico_smentisce_e_non_propone(self):
        url, html = _pagina("generico_so_camcom_18276.html")
        fonte = FonteFinta([_riga(18276, url, html)], {18276: _gia_letto(url, html)}, _tabella(url))
        esito = _passo(fonte, Rete({url: (200, html)}), modalita="attivo")
        self.assertEqual(fonte.registrate, [])
        self.assertEqual(esito["proposte"], [])
        self.assertEqual(esito["counters"]["smentiti_generico"], 1)
        self.assertEqual(fonte.scritte[18276]["stato_letto"], "chiuso")

    def test_tabella_dal_db_decide_cosa_si_legge(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        privato = "https://bandi.ente-esempio.it/bando/1"
        riga = _riga(8, privato, html)
        righe_db = du.da_righe_db([{"host": "bandi.ente-esempio.it", "tipo": "ente", "confidenza": 0.9}])
        for tabella, chiamate in ((_tabella(url), 0), (du.costruisci(righe_db), 1)):
            with self.subTest(chiamate=chiamate):
                rete = Rete({privato: (200, html)})
                _passo(FonteFinta([riga], {}, tabella), rete)
                self.assertEqual(len(rete.chiamate), chiamate)

    def test_esiti_per_estrattore(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        url, html = _pagina("sconosciuto_sicilia_3042.html")
        fonte.righe.append(_riga(3042, url, html))
        fonte.tabella = _tabella(fonte.righe[0]["fonte_ufficiale_url"], url)
        rete.pagine[url] = (200, html)
        esito = _passo(fonte, rete)
        self.assertEqual(esito["counters"]["esiti_per_estrattore"],
                         {"lombardia": {"letture": 1, "esiti": 1}, "generico": {"letture": 1, "esiti": 0}})

    def test_seconda_lettura_g7e_in_coda(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        fonte._letture = {}
        esito = _passo(fonte, rete, modalita="attivo")
        self.assertEqual(fonte.registrate, [])
        self.assertEqual([(p["esito"], p["gate"]["falliti"]) for p in esito["proposte"]],
                         [("in_coda", ["G7e"])])
        self.assertEqual(fonte.scritte[18344]["prossima_lettura_at"], (ADESSO + timedelta(days=3)).isoformat())

    def test_link_collegato_del_piemonte(self):
        # «Attuato» con il bando vero collegato sullo stesso host: vince la pagina collegata.
        # La fixture 2971 non ha il link: lo si aggiunge nel corpo, come sulle pagine di 2892 e 2893.
        url, html = _pagina("piemonte_attuato_2971.html")
        html = html.replace("</h1>", '</h1><p><a href="/contributi-finanziamenti/bando-collegato">Bando</a></p>', 1)
        lettura = es.leggi(html, url, "", oggi=OGGI)
        self.assertEqual((lettura.stato, lettura.link_collegato),
                         ("uscito", "https://bandi.regione.piemonte.it/contributi-finanziamenti/bando-collegato"))
        _, scaduto = _pagina("piemonte_scaduto_2890.html")
        riga = _riga(2892, url, html, stato_bando="in apertura prossimamente", titolo=_titolo(scaduto))
        rete = Rete({url: (200, html), lettura.link_collegato: (200, scaduto)})
        fonte = FonteFinta([riga], {}, _tabella(url))
        _passo(fonte, rete)
        self.assertEqual(fonte.scritte[2892]["lettura_stato"]["pagina"], "iii")
        self.assertEqual(fonte.scritte[2892]["lettura_stato"]["stato"], "chiuso")


class TestAccorciatore(unittest.TestCase):
    """Lo `Scarico` vero con `httpx.MockTransport`: rpu.gl si segue fino in fondo."""

    def _scarico(self, mappa):
        async def niente(_valore):
            return None

        def gestore(request):
            return mappa.get(str(request.url), httpx.Response(404))

        return scarico.Scarico(transport=httpx.MockTransport(gestore), throttle=niente, dormi=niente,
                               tentativi=0)

    def _giro(self, destinazione, html):
        corto = "https://rpu.gl/abc12"
        url, _ = _pagina("lombardia_chiuso_18344.html")
        s = self._scarico({
            corto: httpx.Response(302, headers={"Location": destinazione}),
            destinazione: httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"}),
        })
        riga = _riga(5698, corto, html, fonte_ufficiale_url=None, fonte_ufficiale_stato="non_trovata",
                     host_fonte=du.dominio_di(url))
        fonte = FonteFinta([riga], {}, _tabella(url))

        async def corri():
            try:
                return await vs.esegui_passo("06:00", fonte_dati=fonte, scarica=s.scarica, adesso=ADESSO,
                                             impostazioni=_impostazioni())
            finally:
                await s.chiudi()

        return asyncio.run(corri()), fonte

    def test_rpu_gl_verso_host_non_verificante_rifiutato(self):
        _, html = _pagina("lombardia_chiuso_18344.html")
        esito, fonte = self._giro(URL_PRIVATO, html)
        self.assertEqual(esito["counters"]["letture_non_verificanti"], 1)
        self.assertEqual(fonte.scritte[5698]["lettura_stato"]["esito"], "illeggibile")
        self.assertEqual(fonte.scritte[5698]["lettura_stato"]["url"], URL_PRIVATO)

    def test_rpu_gl_verso_la_fonte_si_legge(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        esito, fonte = self._giro(url, html)
        self.assertEqual(esito["counters"]["letture_non_verificanti"], 0)
        self.assertEqual((fonte.scritte[5698]["lettura_stato"]["pagina"],
                          fonte.scritte[5698]["lettura_stato"]["estrattore"]), ("ii", "lombardia"))


class TestModello(unittest.TestCase):
    def _sicilia(self):
        url, html = _pagina("sconosciuto_sicilia_3042.html")
        testo = scarico.testo_da_html(html)
        chiamate = []

        async def modello(testo_pagina, riga):
            chiamate.append(riga["id"])
            return {"stato": "aperto", "citazione": testo[:60]}

        return FonteFinta([_riga(3042, url, html)], {}, _tabella(url)), Rete({url: (200, html)}), modello, chiamate

    def test_modello_iniettato_legge_ma_non_propone(self):
        fonte, rete, modello, chiamate = self._sicilia()
        esito = _passo(fonte, rete, modalita="attivo", leggi_modello=modello,
                       impostazioni=_impostazioni(verifica_stato_usa_modello=True))
        self.assertEqual(chiamate, [3042])
        self.assertEqual((fonte.scritte[3042]["stato_letto"], fonte.scritte[3042]["stato_letto_metodo"]),
                         ("aperto", "modello"))
        self.assertEqual((fonte.registrate, esito["proposte"]), ([], []))

    def test_senza_modello_o_spento_non_si_chiama(self):
        for kwargs in ({"senza_modello": True, "impostazioni": _impostazioni(verifica_stato_usa_modello=True)},
                       {"impostazioni": _impostazioni(verifica_stato_usa_modello=False)}):
            with self.subTest(kwargs=sorted(kwargs)):
                fonte, rete, modello, chiamate = self._sicilia()
                _passo(fonte, rete, leggi_modello=modello, **kwargs)
                self.assertEqual(chiamate, [])

    def test_bilancio_prima_del_modello(self):
        tetti = dict(tetto_fetch_giro=0, tetto_ricerche_giorno=0, tetto_crediti_giorno=0,
                     tetto_classificazioni_giorno=0, tetto_usd_giorno=1.0, tetto_crediti_mese=0,
                     tetto_usd_mese=0, backfill_tetto_crediti=0, backfill_tetto_usd=0)
        for consumo, chiamate_attese, saltati in (({"usd": 2.0}, [], 1), ({"usd": 0.5}, [3042], 0)):
            with self.subTest(consumo=consumo):
                fonte, rete, modello, chiamate = self._sicilia()
                fonte.consumo = consumo
                esito = _passo(fonte, rete, leggi_modello=modello,
                               impostazioni=_impostazioni(verifica_stato_usa_modello=True, **tetti))
                self.assertEqual(chiamate, chiamate_attese)
                self.assertEqual(esito["counters"]["modello_saltato_per_bilancio"], saltati)

    def test_consumo_illeggibile_niente_modello(self):
        # §18.5: se `db.consumo_oggi()` fallisce (None) il modello non si
        # chiama; la pagina si legge lo stesso con i lettori per ente.
        tetti = dict(tetto_fetch_giro=0, tetto_ricerche_giorno=0, tetto_crediti_giorno=0,
                     tetto_classificazioni_giorno=0, tetto_usd_giorno=1.0, tetto_crediti_mese=0,
                     tetto_usd_mese=0, backfill_tetto_crediti=0, backfill_tetto_usd=0)
        fonte, rete, modello, chiamate = self._sicilia()
        fonte.consumo = None
        esito = _passo(fonte, rete, leggi_modello=modello,
                       impostazioni=_impostazioni(verifica_stato_usa_modello=True, **tetti))
        self.assertEqual(chiamate, [])
        self.assertEqual(esito["counters"]["modello_saltato_per_bilancio"], 1)
        self.assertEqual(esito["counters"]["lavorati"], 1)

    def test_fonte_supabase_consumo_illeggibile_e_none(self):
        # La fonte di produzione non trasforma l'errore in «niente speso».
        fonte = vs.FonteDatiSupabase.__new__(vs.FonteDatiSupabase)
        db = carica_modulo("db")
        with patch.object(db, "consumo_oggi", side_effect=RuntimeError("503")):
            self.assertIsNone(fonte.consumo_oggi())

    def test_gate_di_parola(self):
        testo = "Il bando è chiuso dal 3 marzo. Le domande sono ammesse fino ad esaurimento delle risorse."
        self.assertIsNotNone(vs.lettura_modello_valida(testo, {"stato": "chiuso", "citazione": "Il bando è chiuso"}))
        for lettura in ({"stato": "chiuso", "citazione": "Le domande sono ammesse"},
                        {"stato": "chiuso", "citazione": "fino ad esaurimento delle risorse"},
                        {"stato": "aperto", "citazione": "una frase che non c'è"},
                        {"stato": "forse", "citazione": "Il bando è chiuso"}):
            with self.subTest(lettura=lettura):
                self.assertIsNone(vs.lettura_modello_valida(testo, lettura))


class TestConferme(unittest.TestCase):
    def _colonne(self, lettura, tipo="i", livello="alto", segnale=None):
        candidato = vs.Candidato(_riga(1, "https://x.it/b", "<h1>Titolo</h1>"),
                                 {"segnale_aggregatore_at": segnale}, "A", "aperto", None,
                                 vs.PaginaDaLeggere(tipo, "https://x.it/b"), 40)
        letto = vs.EsitoLettura("letta", vs.PaginaDaLeggere(tipo, "https://x.it/b"), url_finale="https://x.it/b",
                                lettura=lettura, metodo="estrattore", livello_titolo=livello)
        return vs.colonne_lettura(candidato, letto, None, attivo=True, termine=None, previsto_entro=None,
                                  prossima=ADESSO, adesso=ADESSO)

    def test_generico_mai_conferma(self):
        colonne = self._colonne(es.Lettura("generico", "aperto", "Bando aperto"))
        self.assertNotIn("stato_letto", colonne)
        self.assertIn("esaminato_attivo_at", colonne)

    def test_pagina_iv_conferma_solo_con_titolo_alto_e_senza_segnale(self):
        aperto = es.Lettura("lombardia", "aperto", "Aperto")
        self.assertEqual(self._colonne(aperto, "iv")["stato_letto"], "aperto")
        self.assertNotIn("stato_letto", self._colonne(aperto, "iv", livello="medio"))
        self.assertNotIn("stato_letto", self._colonne(aperto, "iv", segnale="2026-09-30T00:00:00+00:00"))
        self.assertEqual(self._colonne(es.Lettura("lombardia", "chiuso", "Chiuso"), "iv")["stato_letto"], "chiuso")

    def test_pagina_ii_c_conferma_solo_con_titolo_almeno_medio(self):
        aperto = es.Lettura("lombardia", "aperto", "Aperto")
        self.assertEqual(self._colonne(aperto, "ii-c", livello="medio")["stato_letto"], "aperto")
        self.assertEqual(self._colonne(aperto, "ii-c", livello="alto")["stato_letto"], "aperto")
        for livello in ("basso", None):
            with self.subTest(livello=livello):
                self.assertNotIn("stato_letto", self._colonne(aperto, "ii-c", livello=livello))

    def test_ombra_niente_sei_colonne(self):
        candidato = vs.Candidato(_riga(1, "https://x.it/b", "<h1>T</h1>"), {}, "A", "aperto", None,
                                 vs.PaginaDaLeggere("i", "https://x.it/b"), 40)
        letto = vs.EsitoLettura("letta", candidato.pagina, url_finale="https://x.it/b",
                                lettura=es.Lettura("lombardia", "aperto", "Aperto"), metodo="estrattore")
        colonne = vs.colonne_lettura(candidato, letto, None, attivo=False, termine=(date(2026, 12, 31), "testo"),
                                     previsto_entro=None, prossima=ADESSO, adesso=ADESSO)
        self.assertFalse({"stato_letto", "esaminato_attivo_at"} & set(colonne))
        self.assertEqual((colonne["termine_indicato"], colonne["termine_indicato_fonte"]), ("2026-12-31", "testo"))


class TestCadenzaETermine(unittest.TestCase):
    def _candidato(self, controllo=None, motivo=None):
        return vs.Candidato(_riga(1, "https://x.it/b", "<h1>T</h1>"), controllo or {}, "A", "aperto", motivo,
                            vs.PaginaDaLeggere("i", "https://x.it/b"), 40)

    def test_chiuso_appena_letto_tre_giorni_anche_senza_conferma(self):
        candidato = self._candidato(motivo="senza_conferma")
        for lettura, metodo in ((es.Lettura("lombardia", "chiuso", "Chiuso", puo_chiudere=True), "estrattore"),
                                (es.Lettura("piemonte", "uscito", "Attuato"), "estrattore"),
                                (vs.LetturaModello("chiuso", "Il bando è chiuso"), "modello"),
                                (vs.LetturaModello("uscito", "Il bando è uscito"), "modello")):
            with self.subTest(stato=lettura.stato, metodo=metodo):
                letto = vs.EsitoLettura("letta", candidato.pagina, lettura=lettura, metodo=metodo)
                self.assertEqual(vs.cadenza(candidato, letto, trattenuta=None, g7e_in_attesa=False,
                                            motivo="senza_conferma", adesso=ADESSO),
                                 ADESSO + timedelta(days=3))
        # Senza una lettura di stato resta la cadenza di «senza conferma».
        self.assertEqual(vs.cadenza(candidato, vs.EsitoLettura("letta", candidato.pagina), trattenuta=None,
                                    g7e_in_attesa=False, motivo="senza_conferma", adesso=ADESSO),
                         ADESSO + timedelta(days=14))

    def test_termine_e_fonte_come_coppia(self):
        candidato = self._candidato({"termine_indicato": "2026-12-31", "termine_indicato_fonte": "testo"})
        letto = vs.EsitoLettura("non_decisiva", candidato.pagina)

        def colonne(termine):
            return vs.colonne_lettura(candidato, letto, None, attivo=False, termine=termine,
                                      previsto_entro=None, prossima=ADESSO, adesso=ADESSO)

        cambiata = colonne((date(2026, 12, 31), "pagina"))
        self.assertEqual((cambiata["termine_indicato"], cambiata["termine_indicato_fonte"]),
                         ("2026-12-31", "pagina"))
        self.assertNotIn("termine_indicato_fonte", colonne((date(2026, 12, 31), "testo")))
        tolta = colonne(None)
        self.assertEqual((tolta["termine_indicato"], tolta["termine_indicato_fonte"]), (None, None))

    def test_termine_della_pagina_senza_testo_oggi(self):
        candidato = self._candidato({"termine_indicato": "2026-12-31", "termine_indicato_fonte": "pagina"})
        letto = vs.EsitoLettura("errore_rete", candidato.pagina)

        def colonne(termine, testo_letto):
            return vs.colonne_lettura(candidato, letto, None, attivo=False, termine=termine, previsto_entro=None,
                                      prossima=ADESSO, adesso=ADESSO, testo_letto=testo_letto)

        # Senza testo la coppia della pagina resta, anche se il testo dice altro o niente.
        for termine in (None, (date(2026, 11, 30), "testo"), (date(2026, 11, 30), "aggregatore")):
            with self.subTest(termine=termine):
                self.assertNotIn("termine_indicato", colonne(termine, False))
        # Un calendario ufficiale la sostituisce; con il testo letto vale la regola di sempre.
        self.assertEqual(colonne((date(2026, 11, 30), "calendario_ufficiale"), False)["termine_indicato_fonte"],
                         "calendario_ufficiale")
        self.assertEqual(colonne((date(2026, 11, 30), "testo"), True)["termine_indicato_fonte"], "testo")

    def test_termine_della_pagina_rimossa_non_si_conserva(self):
        candidato = self._candidato({"termine_indicato": "2026-12-31", "termine_indicato_fonte": "pagina"})
        letto = vs.EsitoLettura("pagina_rimossa", candidato.pagina, http=404)

        def colonne(termine):
            return vs.colonne_lettura(candidato, letto, None, attivo=False, termine=termine, previsto_entro=None,
                                      prossima=ADESSO, adesso=ADESSO, testo_letto=False)

        ricade = colonne((date(2026, 11, 30), "testo"))
        self.assertEqual((ricade["termine_indicato"], ricade["termine_indicato_fonte"]), ("2026-11-30", "testo"))
        nulla = colonne(None)
        self.assertEqual((nulla["termine_indicato"], nulla["termine_indicato_fonte"]), (None, None))


class TestProsa(unittest.TestCase):
    def _giro(self, rigenerazione, testi=None):
        return vs._Giro(FonteFinta(testi=testi), Rete(), {}, {}, ADESSO, True, False, lambda: 0.0,
                        rigenerazione=rigenerazione)

    def _proposta(self, tipo="data_verificata", campo="data_scadenza", valore="2026-07-24"):
        return ev.Proposta(tipo, ramo="I", citazione="c", url_prova="u", metodo="estrattore:lazioeuropa",
                           campo=campo, valore_dopo={campo: valore} if campo else {"stato_bando": "chiuso"})

    def _riallinea(self, giro, proposta, vecchia="2026-07-20"):
        riga = {"id": 5, "slug": "bando-5", "data_scadenza": vecchia}
        return asyncio.run(vs._riallinea_prosa(giro, riga, {"tipo": proposta.tipo}, proposta))

    def test_data_sostituita_con_l_adattatore(self):
        chiamate = []

        async def adattatore(bando, evento, *, vecchia, nuova, ruolo):
            chiamate.append((bando["contenuto"], vecchia, nuova, ruolo))
            return {"scritto": True}

        testi = {"contenuto": "Le domande si presentano entro il 20 luglio 2026.", "descrizione_breve": ""}
        self.assertTrue(self._riallinea(self._giro(adattatore, testi), self._proposta()))
        self.assertEqual(chiamate, [(testi["contenuto"], date(2026, 7, 20), date(2026, 7, 24), "scadenza")])

    def test_prosa_non_riallineata(self):
        async def solo_box(bando, evento, **_):
            return {"scritto": False, "via": "box", "motivi": ["gate fallito"]}

        testi = {"contenuto": "Scade il 20 luglio 2026.", "descrizione_breve": ""}
        self.assertFalse(self._riallinea(self._giro(solo_box, testi), self._proposta()))
        self.assertFalse(self._riallinea(self._giro(None, testi), self._proposta()))
        self.assertFalse(self._riallinea(self._giro(solo_box, None), self._proposta()))

    def test_niente_da_riscrivere(self):
        async def mai(*_a, **_k):
            raise AssertionError("non doveva essere chiamato")

        self.assertTrue(self._riallinea(self._giro(mai), self._proposta(tipo="chiusura", campo=None)))
        self.assertTrue(self._riallinea(self._giro(mai), self._proposta(), vecchia=None))
        self.assertTrue(self._riallinea(self._giro(mai), self._proposta(), vecchia="2026-07-24"))

    def test_nel_passo_slug_fuori_se_la_prosa_resta_vecchia(self):
        # In apertura con scadenza il 20/10; la pagina dice «aperto» fino al 29/10: data_verificata
        # (la data cambia, la prosa va riscritta) e apertura (niente da riscrivere).
        url, html = _pagina("lazioeuropa_aperto_1072674.html")
        riga = _riga(1072674, url, html, stato_bando="in apertura prossimamente", data_scadenza="2026-10-20")
        ammesso = ev.Giudizio(ammesso=True, gate="G2v", superati=("G1",), confidenza=0.9)
        for scritto, slug, non_riscritta in ((False, [], 1), (True, ["bando-1072674"], 0)):
            async def adattatore(bando, evento, **_):
                return {"scritto": scritto}

            with self.subTest(scritto=scritto), patch.object(vs.eventi_mod, "valuta_verifica", return_value=ammesso):
                fonte = FonteFinta([riga], {}, _tabella(url),
                                   testi={"contenuto": "Entro il 20 ottobre 2026.", "descrizione_breve": ""})
                esito = _passo(fonte, Rete({url: (200, html)}), modalita="attivo", rigenerazione=adattatore)
                self.assertEqual([r["tipo"] for r in fonte.registrate], ["data_verificata", "apertura"])
                self.assertEqual(esito["slug_modificati"], slug)
                self.assertEqual(esito["counters"]["prosa_non_riscritta"], non_riscritta)
                self.assertEqual(esito["ids_da_rigenerare"], [1072674])

    def test_in_ombra_la_prosa_non_si_tocca(self):
        url, html = _pagina("lazioeuropa_aperto_1072674.html")
        riga = _riga(1072674, url, html, stato_bando="in apertura prossimamente", data_scadenza="2026-10-20")
        ammesso = ev.Giudizio(ammesso=True, gate="G2v", superati=("G1",), confidenza=0.9)

        async def mai(*_a, **_k):
            raise AssertionError("in ombra la prosa non si riscrive")

        with patch.object(vs.eventi_mod, "valuta_verifica", return_value=ammesso):
            esito = _passo(FonteFinta([riga], {}, _tabella(url)), Rete({url: (200, html)}), rigenerazione=mai)
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["counters"]["prosa_non_riscritta"], 0)
        self.assertEqual({p["trattenuta"] for p in esito["proposte"]}, {"ombra"})


class TestIngresso(unittest.TestCase):
    def _fonte(self, **kwargs):
        url, html = _pagina("formazionelavoro_aperto_2339.html")
        riga = _riga(2339, url, html, pubblicato=False, stato_processing="enriched")
        return FonteFinta(enriched=[riga], tabella=_tabella(url), **kwargs), Rete({url: (200, html)})

    def test_attivo_scrive_la_scadenza(self):
        fonte, rete = self._fonte()
        esito = _passo(fonte, rete, fase="ingresso", modalita="attivo")
        [(bando_id, colonne_bando, controllo)] = fonte.ingressi
        self.assertEqual((bando_id, colonne_bando), (2339, {"data_scadenza": "2027-01-19", "ora_scadenza": "12:00"}))
        self.assertEqual(controllo["lettura_stato"]["storia"][-1]["estrattore"], "formazionelavoro_er")
        self.assertEqual(esito["counters"]["ingresso_date_scritte"], 1)
        self.assertEqual(fonte.scritte, {})
        self.assertEqual(fonte.runs[0].step, "verifica_stato_ingresso")

    def test_ombra_mai_colonne_di_bando(self):
        fonte, rete = self._fonte()
        esito = _passo(fonte, rete, fase="ingresso")
        [(_, colonne_bando, controllo)] = fonte.ingressi
        self.assertIsNone(colonne_bando)
        self.assertEqual(set(controllo), {"lettura_stato", "lettura_stato_at"})
        self.assertEqual(esito["counters"]["ingresso_date_scritte"], 0)

    def test_sosta_in_ombra_scrive_trattenuto_dal(self):
        fonte, _ = self._fonte()
        esito = _passo(fonte, Rete(), fase="ingresso")
        [(_, colonne_bando, controllo)] = fonte.ingressi
        self.assertIsNone(colonne_bando)
        self.assertEqual(controllo["trattenuto_dal"], ADESSO.isoformat())
        self.assertEqual(esito["counters"]["trattenuti"], 1)

    def test_senza_appiglio_fuori_dal_tetto_e_bando_link_contano(self):
        fonte, rete = self._fonte()
        leggibile = fonte._enriched[0]
        nuda = {**leggibile, "id": 1, "link_bando": None, "fonte_ufficiale_url": None,
                "fonte_ufficiale_stato": "non_trovata", "titolo": "Bando senza niente"}
        con_link = {**nuda, "id": 2}
        fonte._enriched = [nuda, con_link, leggibile]
        fonte.link = {2: [{"bando_id": 2, "url": "https://altro-esempio.it/allegato.pdf", "tipo": "allegato"}]}
        esito = _passo(fonte, rete, fase="ingresso")
        # La riga nuda non si legge e non conta fra i candidati; quella con un bando_link si'.
        self.assertEqual([i for i, _, _ in fonte.ingressi], [2, 2339])
        self.assertEqual((esito["counters"]["trattenuti_senza_appiglio"], esito["counters"]["candidati"]), (1, 2))
        self.assertEqual(esito["counters"]["trattenuti"], 2)  # la nuda e la 2, in sosta senza lettura

    def test_riga_pubblicata_mai_scritta(self):
        fonte, rete = self._fonte()
        fonte._enriched[0]["pubblicato"] = True
        esito = _passo(fonte, rete, fase="ingresso", modalita="attivo")
        self.assertEqual((fonte.ingressi, rete.chiamate, esito["counters"]["candidati"]), ([], [], 0))

    def test_rifiuto_del_db_non_conta_come_scritta(self):
        fonte, rete = self._fonte(rifiuta={2339})
        esito = _passo(fonte, rete, fase="ingresso", modalita="attivo")
        self.assertEqual(esito["counters"]["ingresso_date_scritte"], 0)

    def test_supabase_passa_da_aggiorna_ingresso(self):
        with patch.object(db, "aggiorna_ingresso", return_value={"bando": False}) as spia:
            vs.FonteDatiSupabase().scrivi_ingresso(1, None, {"lettura_stato_at": "x"})
        spia.assert_called_once_with(1, None, {"lettura_stato_at": "x"})

    def test_mai_modello_in_ingresso(self):
        fonte, rete = self._fonte()

        async def modello(*_a):
            raise AssertionError("niente modello in ingresso")

        esito = _passo(fonte, rete, fase="ingresso", leggi_modello=modello,
                       impostazioni=_impostazioni(verifica_stato_usa_modello=True))
        self.assertEqual(esito["status"], "ok")


class TestGuardie(unittest.TestCase):
    def test_migrazione_assente_saltato(self):
        fonte, rete, _, _ = _chiusura_lombardia(migrazione=False)
        esito = _passo(fonte, rete)
        self.assertEqual((esito["status"], esito["counters"]["motivo_saltato"]), ("saltato", "migrazione_assente"))
        self.assertEqual((rete.chiamate, fonte.scritte), ([], {}))
        self.assertEqual(fonte.runs[0].esito, "saltato")

    def test_errore_interno_non_solleva(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        fonte.candidati = MagicMock(side_effect=RuntimeError("rotto"))
        with patch.object(vs, "logger", MagicMock()):
            esito = _passo(fonte, rete)
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(fonte.runs[0].esito, "errore")

    def test_tetto_di_tempo_del_giro(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        orologio = iter(range(0, 100000, 1000))
        esito = _passo(fonte, rete, orologio=lambda: next(orologio))
        self.assertTrue(esito["counters"]["interrotto_per_tetto_tempo"])
        self.assertEqual((esito["counters"]["letti"], rete.chiamate), (0, []))
        self.assertTrue(fonte.runs[0].interrotto_per_tetto)

    def test_tetto_di_tempo_per_bando(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        rete.attesa = 0.2
        with patch.object(vs, "TETTO_TEMPO_BANDO_S", 0.01):
            esito = _passo(fonte, rete)
        self.assertEqual(esito["counters"]["errori_rete"], 1)
        self.assertEqual(fonte.scritte[18344]["lettura_stato"]["esito"], "errore_rete")

    def test_limit_solo_da_riga_di_comando(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        fonte = FonteFinta([_riga(i, url, html) for i in (1, 2, 3)], {}, _tabella(url))
        esito = _passo(fonte, Rete({url: (200, html)}), limit=2)
        self.assertEqual(esito["counters"]["letti"], 2)
        self.assertEqual(sorted(fonte.scritte), [1, 2])
        self.assertEqual(esito["copertura"],
                         {"candidati": 3, "fatti": 2, "rimasti": 1, "motivo_rimasti": None})


class TestGiro3SenzaTettiDiNumero(unittest.TestCase):
    """Contratto `bandi-giro-3` §1 e §13: tempo con rotazione, freno per host, copertura."""

    def test_senza_limit_si_leggono_tutti(self):
        # Il vecchio VERIFICA_STATO_TETTO_LETTURE (40) non c'e' piu'.
        url, html = _pagina("lombardia_chiuso_18344.html")
        ids = list(range(1, 46))
        fonte = FonteFinta([_riga(i, url, html) for i in ids], {}, _tabella(url))
        esito = _passo(fonte, Rete({url: (200, html)}))
        self.assertEqual(esito["counters"]["letti"], 45)
        self.assertEqual(sorted(fonte.scritte), ids)
        self.assertEqual(esito["copertura"]["rimasti"], 0)
        self.assertEqual(fonte.runs[0].contatori["copertura"], esito["copertura"])

    def test_rotazione_a_parita_di_priorita(self):
        # Stessa priorita' (rinnovo): prima chi e' stato letto meno di recente,
        # l'id decide solo a parita'.
        url, html = _pagina("lombardia_chiuso_18344.html")
        letture = {1: _gia_letto(url, html, ore_fa=30), 2: _gia_letto(url, html, ore_fa=90),
                   3: _gia_letto(url, html, ore_fa=60)}
        righe = [_riga(i, url, html) for i in (1, 2, 3)]
        candidati = vs.scegli_candidati(righe, letture, {}, _tabella(url), ADESSO)
        self.assertEqual({c.priorita for c in candidati}, {candidati[0].priorita})
        self.assertEqual([c.riga["id"] for c in candidati], [2, 3, 1])

    def test_mai_letto_prima_di_tutti(self):
        self.assertLess(vs._chiave_rotazione({}), vs._chiave_rotazione(
            {"lettura_stato_at": "2020-01-01T00:00:00+00:00"}))
        self.assertLess(vs._chiave_rotazione({"lettura_stato_at": "2026-09-01T00:00:00+00:00"}),
                        vs._chiave_rotazione({"lettura_stato_at": "2026-09-20T00:00:00+00:00"}))

    def test_il_tempo_lascia_fuori_con_motivo_tempo(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        fonte = FonteFinta([_riga(i, url, html) for i in (1, 2, 3)], {}, _tabella(url))
        orologio = iter([0, 0, 0, 0, 10_000, 10_000, 10_000, 10_000])
        esito = _passo(fonte, Rete({url: (200, html)}), orologio=lambda: next(orologio, 10_000))
        self.assertTrue(esito["counters"]["interrotto_per_tetto_tempo"])
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "tempo")
        self.assertGreater(esito["copertura"]["rimasti"], 0)
        self.assertEqual(esito["copertura"]["fatti"] + esito["copertura"]["rimasti"], 3)

    def test_tempo_predefinito_trenta_minuti(self):
        # VERIFICA_STATO_TETTO_S: 1800 per difetto (giro 3, §3) anche con
        # impostazioni parziali.
        url, html = _pagina("lombardia_chiuso_18344.html")
        fonte = FonteFinta([_riga(1, url, html)], {}, _tabella(url))
        impostazioni = SimpleNamespace(verifica_stato_modalita="ombra", verifica_stato_usa_modello=False,
                                       ingresso_sosta_giri=4)
        orologio = iter([0, 0, 1700, 1700, 1700, 1700])
        esito = _passo(fonte, Rete({url: (200, html)}), impostazioni=impostazioni,
                       orologio=lambda: next(orologio, 1700))
        self.assertFalse(esito["counters"]["interrotto_per_tetto_tempo"])
        self.assertEqual(esito["counters"]["letti"], 1)

    def test_errore_copertura_con_motivo_errore(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        fonte = FonteFinta([_riga(i, url, html) for i in (1, 2)], {}, _tabella(url))
        with patch.object(vs, "_leggi_candidato", AsyncMock(side_effect=RuntimeError("rotto"))), \
                patch.object(vs, "logger", MagicMock()):
            esito = _passo(fonte, Rete({url: (200, html)}))
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(esito["copertura"],
                         {"candidati": 2, "fatti": 1, "rimasti": 1, "motivo_rimasti": "errore"})

    def test_saltato_senza_copertura(self):
        fonte, rete, _, _ = _chiusura_lombardia(migrazione=False)
        self.assertNotIn("copertura", _passo(fonte, rete))


class TestReport(unittest.TestCase):
    def test_esiti_del_report(self):
        casi = {
            "chiusura": {"lettura_stato": {"esito": "letta", "stato": "chiuso",
                                           "proposta": {"tipo": "chiusura", "trattenuta": "ombra", "ammessa": True}}},
            "rettifica:2027-01-19": {"lettura_stato": {"esito": "letta", "stato": "aperto", "proposta": {
                "tipo": "rettifica", "ammessa": True, "valore_dopo": {"data_scadenza": "2027-01-19"}}}},
            "smentito": {"lettura_stato": {"esito": "letta", "stato": "chiuso", "solo_segnale": True}},
            "confermato": {"lettura_stato": {"esito": "letta", "stato": "aperto"}},
            "forse_non_un_bando": {"lettura_stato": {"esito": "non_decisiva", "forse_non_un_bando": True}},
            "dalla_sorella": {"lettura_stato": {"esito": "letta", "stato": "aperto", "dalla_sorella": True}},
            "termine_indicato:2026-12-31": {"lettura_stato": {"esito": "illeggibile", "pagina": "illeggibile"},
                                            "termine_indicato": "2026-12-31"},
            "segnalato": {"lettura_stato": {"esito": "non_decisiva"}, "segnale_aggregatore": "in_uscita"},
            "illeggibile": {"lettura_stato": {"esito": "illeggibile", "pagina": "illeggibile"}},
            "non_decisiva": {"lettura_stato": {"esito": "non_decisiva"}},
        }
        for atteso, controllo in casi.items():
            with self.subTest(atteso=atteso):
                self.assertEqual(vs.esito_report(controllo), atteso)

    def test_apertura_vince_su_data_verificata_1072674(self):
        # Ramo I (b): «aperto» con una scadenza futura certa e non ancora
        # verificata dà data_verificata e apertura; il report dice «apertura».
        url, html = _pagina("lazioeuropa_aperto_1072674.html")
        riga = _riga(1072674, url, html, stato_bando="in apertura prossimamente")
        fonte = FonteFinta([riga], {1072674: _gia_letto(url, html)}, _tabella(url))
        esito = _passo(fonte, Rete({url: (200, html)}))
        self.assertEqual(sorted((p["tipo"], p["esito"]) for p in esito["proposte"]),
                         [("apertura", "ammessa"), ("data_verificata", "ammessa")])
        controllo = {**fonte._letture[1072674], **fonte.scritte[1072674]}
        [riga_report] = vs.righe_report([riga], {1072674: controllo}, adesso=ADESSO)
        self.assertEqual(riga_report["esito"], vs.VERITA_NOTA[1072674])
        self.assertEqual(riga_report["esito"], "apertura")

    def test_verita_nota_nel_vocabolario(self):
        for bando_id, atteso in vs.VERITA_NOTA.items():
            with self.subTest(bando_id=bando_id):
                self.assertIn(atteso.split(":", 1)[0], vs.ESITI_VERITA)
        self.assertEqual({i: vs.VERITA_NOTA[i] for i in (2892, 2893, 661135, 150489)},
                         {2892: "chiusura", 2893: "chiusura", 661135: "chiusura", 150489: "smentito"})

    def test_righe_report_e_confronto(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        righe = [_riga(2387, url, html), _riga(9, url, html, stato_bando="chiuso")]
        letture = {2387: {"lettura_stato": {"esito": "letta", "stato": "chiuso", "pagina": "i",
                                            "proposta": {"tipo": "chiusura", "trattenuta": "ombra", "ammessa": True}}}}
        report = vs.righe_report(righe, letture, adesso=ADESSO)
        self.assertEqual([(r["id"], r["esito"], r["proposta"]) for r in report], [(2387, "chiusura", "chiusura")])
        self.assertEqual(vs.righe_report(righe, letture, adesso=ADESSO, ramo="apertura"), [])
        difformi = vs.confronta_verita(report)
        self.assertNotIn(2387, [d["id"] for d in difformi])
        self.assertIn({"id": 2892, "atteso": "chiusura", "trovato": None}, difformi)


class TestVeritaConfermataDalloStato(unittest.TestCase):
    """Giro 3, §13: un bando uscito dai candidati con lo stato gia' atteso non e' difforme."""

    VERITA = {661135: "chiusura", 1072674: "apertura", 2892: "chiusura", 150489: "smentito",
              2339: "rettifica:2027-01-19", 18337: "smentito"}

    def test_661135_chiuso_dal_job_orario_e_confermato(self):
        # Il caso vero: chiuso il 30/09 dal job orario, assente dal report.
        report = [{"id": 18337, "esito": "smentito"}]
        stati = {661135: "chiuso", 1072674: "aperto", 2892: "aperto", 150489: "chiuso", 2339: "aperto"}
        difformi = vs.confronta_verita(report, self.VERITA, stati=stati)
        self.assertNotIn(661135, [d["id"] for d in difformi])
        self.assertNotIn(1072674, [d["id"] for d in difformi])
        self.assertEqual(vs.confermati_da_stato(report, self.VERITA, stati=stati), [
            {"id": 661135, "atteso": "chiusura", "stato": "chiuso"},
            {"id": 1072674, "atteso": "apertura", "stato": "aperto"},
        ])
        # Assente ma aperto: difforme. «smentito» e «rettifica» usciti dai
        # candidati restano difformi anche con uno stato coerente.
        self.assertEqual([d["id"] for d in difformi], [2339, 2892, 150489])

    def test_presente_con_esito_diverso_resta_difforme(self):
        report = [{"id": 661135, "esito": "non_decisiva"}]
        difformi = vs.confronta_verita(report, {661135: "chiusura"}, stati={661135: "chiuso"})
        self.assertEqual(difformi, [{"id": 661135, "atteso": "chiusura", "trovato": "non_decisiva"}])
        self.assertEqual(vs.confermati_da_stato(report, {661135: "chiusura"}, stati={661135: "chiuso"}), [])

    def test_senza_stati_tutto_come_prima(self):
        difformi = vs.confronta_verita([], {661135: "chiusura"})
        self.assertEqual(difformi, [{"id": 661135, "atteso": "chiusura", "trovato": None}])
        self.assertEqual(vs.confermati_da_stato([], {661135: "chiusura"}), [])

    def test_solo_chiusura_e_apertura(self):
        self.assertEqual(vs.ESITO_STATO_ATTESO, {"chiusura": "chiuso", "apertura": "aperto"})
        self.assertIn(661135, vs.VERITA_NOTA)
        self.assertEqual(vs.VERITA_NOTA[661135], "chiusura")

    def test_stati_effettivi_dalle_colonne(self):
        chiamate = []

        def leggi(blocco):
            chiamate.append(list(blocco))
            return [
                {"id": 661135, "stato_bando": "chiuso", "data_scadenza": "2026-09-30"},
                # Aperto per colonna ma con la scadenza passata: l'effettivo e' chiuso.
                {"id": 7, "stato_bando": "aperto", "data_scadenza": "2026-09-01"},
                {"id": 8, "stato_bando": "aperto", "data_scadenza": "2027-01-01"},
            ]

        stati = vs.stati_effettivi([661135, 7, 8, 7, None], leggi=leggi, adesso=ADESSO)
        self.assertEqual(chiamate, [[661135, 7, 8]])
        self.assertEqual(stati, {661135: "chiuso", 7: "chiuso", 8: "aperto"})
        self.assertEqual(vs.stati_effettivi([], leggi=leggi), {})

    def test_stati_effettivi_a_blocchi_di_cento(self):
        blocchi = []
        vs.stati_effettivi(list(range(250)), leggi=lambda b: blocchi.append(len(b)) or [], adesso=ADESSO)
        self.assertEqual(blocchi, [100, 100, 50])


class TestComeLaChiamaLaCli(unittest.TestCase):
    """`__main__` chiama esegui_passo, righe_report e confronta_verita cosi'."""

    def _cli(self, argv, fonte, rete):
        uscita, errori = io.StringIO(), io.StringIO()
        with patch.object(vs, "FonteDatiSupabase", lambda: fonte), \
                patch.object(vs, "_scarica_predefinito", lambda: rete), \
                patch.object(cli, "logger", MagicMock()), \
                contextlib.redirect_stdout(uscita), contextlib.redirect_stderr(errori):
            codice = cli.main(argv)
        return codice, uscita.getvalue(), errori.getvalue()

    def test_verifica_stato_dry_run(self):
        fonte, rete, _, _ = _chiusura_lombardia()
        codice, uscita, errori = self._cli(
            ["verifica-stato", "--dry-run", "--senza-modello", "--ids", "18344", "--limit", "5"], fonte, rete)
        self.assertEqual(codice, 0, errori)
        self.assertIn("proposta 18344 chiusura -> ammessa", uscita)
        self.assertEqual((fonte.scritte, fonte.runs), ({}, []))

    def test_report_con_verita(self):
        url, html = _pagina("lombardia_chiuso_18344.html")
        righe = [_riga(2387, url, html)]
        letture = {2387: {"lettura_stato": {"esito": "letta", "stato": "chiuso",
                                            "proposta": {"tipo": "chiusura", "ammessa": True}}}}
        uscita = io.StringIO()
        stati = MagicMock(return_value={661135: "chiuso", 2892: "aperto"})
        with patch.object(db, "select_da_verificare", return_value=righe), \
                patch.object(db, "select_letture_stato", return_value=letture), \
                patch.object(vs, "stati_effettivi", stati), \
                patch.object(cli, "logger", MagicMock()), contextlib.redirect_stdout(uscita), \
                contextlib.redirect_stderr(io.StringIO()):
            codice = cli.main(["report-verifica-stato", "--verita", "--json"])
        dati = json.loads(uscita.getvalue())
        self.assertEqual(codice, 1)
        self.assertEqual(dati["report"][0]["esito"], "chiusura")
        self.assertNotIn(2387, [d["id"] for d in dati["difformi"]])
        # Gli stati si chiedono solo per gli id della verita' assenti dal report.
        chiesti = set(stati.call_args.args[0])
        self.assertNotIn(2387, chiesti)
        self.assertIn(661135, chiesti)
        self.assertNotIn(661135, [d["id"] for d in dati["difformi"]])
        self.assertIn(2892, [d["id"] for d in dati["difformi"]])
        self.assertEqual(dati["confermati_da_stato"], [{"id": 661135, "atteso": "chiusura", "stato": "chiuso"}])


class TestRun(unittest.TestCase):
    def test_run_accetta_rigenerazione_come_la_pipeline(self):
        fonte, rete, _, _ = _chiusura_lombardia()

        async def adattatore(*_a, **_k):
            return {"scritto": True}

        esito = asyncio.run(vs.run(giro="06:00", fase="controlli", rigenerazione=adattatore, fonte_dati=fonte,
                                   scarica=rete, adesso=ADESSO, impostazioni=_impostazioni()))
        self.assertEqual(esito["status"], "ok")
        self.assertIn("proposte", esito)


if __name__ == "__main__":
    unittest.main()
