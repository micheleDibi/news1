# -*- coding: utf-8 -*-
"""Rielaborazione dei pubblicati dalla fonte ufficiale (contratto `bandi-giro-3` §9).

Nessuna rete e nessun DB: le letture e le scritture di `db`, la lettura della
pagina, preprocess ed enrich, la prosa e la riscrittura sono sostituite. Si
verifica cio' che il passo scrive, e soprattutto cio' che non scrive mai: lo
stato, `data_pubblicazione`, una data verificata o non provata, una
dimensione svuotata da una chiamata fallita, qualunque cosa in dry-run.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_rielabora_fonte
"""
import asyncio
import contextlib
import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tests.supporto import carica_modulo

rf = carica_modulo("rielabora_fonte")
pre = carica_modulo("preprocessor")
telemetria = carica_modulo("telemetria")
bilancio = carica_modulo("bilancio")
db = carica_modulo("db")
rigenera = carica_modulo("rigenera")
scarico = carica_modulo("scarico")
monitoraggio = carica_modulo("monitoraggio")

OGGI = date(2026, 10, 2)
UFFICIALE = "https://www.regione.marche.it/bandi/contributi"
TESTO = ("Contributi per la formazione. Le domande vanno presentate entro il 30/11/2026. "
         "Possono partecipare le imprese della regione.")
CATALOGO = {
    "regioni": [{"id": 11, "nome": "Marche"}, {"id": 12, "nome": "Lazio"}],
    "settori": [{"id": 5, "nome": "Formazione"}],
    "beneficiari": [{"id": 3, "nome": "Imprese"}],
    "codici_ateco": [],
}


def _bando(**extra):
    valori = {
        "id": 7, "slug": "contributi-formazione", "titolo": "Contributi formazione",
        "titolo_raw": "Contributi formazione", "link_bando": "https://www.obiettivoeuropa.com/b",
        "raw_data": {}, "fonte_id": 1, "stato_bando": "aperto",
        "contenuto": "Il bando vale per le imprese del Lazio.",
        "data_pubblicazione": "2026-09-01", "data_apertura": None, "data_scadenza": "2026-10-30",
        "data_apertura_verificata": False, "data_scadenza_verificata": False,
        "tipologia_bando_id": 1, "modalita_erogazione_id": None, "programma_id": None,
        "fonte_ufficiale_url": UFFICIALE, "fonte_ufficiale_stato": "trovata",
        "fonte_ufficiale_link_id": 70,
    }
    valori.update(extra)
    return valori


def _analisi(**extra):
    valori = {"is_valid_bando": True, "confidence_score": 0.9, "stato_bando": "aperto",
              "data_pubblicazione": None, "data_apertura": None, "data_scadenza": "2026-11-30",
              "_citazioni": {"data_scadenza": "entro il 30/11/2026"}, "_needs_fallback": False}
    valori.update(extra)
    return valori


def _classifica(**extra):
    valori = {"tipologia_bando_id": 2, "modalita_erogazione_id": None, "programma_id": None,
              "regioni_ids": [11], "settori_ids": [], "beneficiari_ids": [3],
              "codici_ateco_ids": [], "_fallite": ()}
    valori.update(extra)
    return valori


class _Giro:
    """Esegue `rf.run` con tutto l'I/O registrato.

    Con `client=_ClientInMemoria(...)` le scritture passano dalle funzioni
    **vere** di `db` (`registra_evento_rpc`, `allinea_junction`,
    `aggiorna_fk_bando`, `aggiorna_link`) su tabelle in memoria che possono
    fallire: e' li' che si vedono le forme degli esiti, che un finto della
    funzione sotto test nasconderebbe (la lezione del P0 di #146).
    `prosa="vera"` usa `_rigenera_prosa` e `rigenera.rigenera` veri, con la
    sola scrittura finale registrata.
    """

    def __init__(self, *, righe=None, analisi=None, classifica=None, testo=TESTO,
                 junction=None, riscrittore=True, applicato=True, analizza=None,
                 prosa=None, client=None):
        self.righe = righe if righe is not None else [_bando()]
        self.analisi = analisi or (lambda b: _analisi())
        self.classifica = classifica or (lambda b: _classifica())
        self.testo = testo
        self.junction = junction if junction is not None else {
            7: {"regioni": [12], "settori": [5], "beneficiari": [3], "codici_ateco": []}}
        self.riscrittore = riscrittore
        self.applicato = applicato
        self.analizza = analizza
        self.prosa = prosa
        self.client = client
        self.crediti_veri = False
        self.esito_riscrittura = "scritta"
        self.classifica_vera = False
        self.catalogo = CATALOGO
        self.allinea = None
        # Gia' speso oggi dal passo (`db.consumo_passo_oggi`): None = illeggibile.
        self.gia_oggi: dict | None = {}
        # I crediti Firecrawl dello scarico (`rf._crediti_scarico`).
        self.crediti = [0]
        self.eventi: list[dict] = []
        self.junction_scritte: list[tuple] = []
        self.fk: list[tuple] = []
        self.marcatori: list[tuple] = []
        self.controlli: list[tuple] = []
        self.segnati: list[Any] = []
        self.righe_run: list[Any] = []
        self.prose: list[tuple] = []
        self.prose_scritte: list[tuple] = []
        self.riscritture: list[tuple] = []
        self.analizzati: list[Any] = []

    def esegui(self, **kwargs):
        async def analizza(bando, fonte, url):
            return dict(self.analisi(bando))

        async def analizza_e_registra(bando, fonte, url):
            self.analizzati.append(bando.get("id"))
            return await (self.analizza or analizza)(bando, fonte, url)

        async def testo(url):
            return self.testo

        async def classifica(bando, fonte, testo, catalogo):
            return dict(self.classifica(bando))

        async def prosa(bando, evento, *, vecchia, nuova, ruolo):
            self.prose.append((bando["id"], vecchia, nuova, ruolo))
            # Come la sostituzione vera: cambia la data, il resto resta.
            return (SimpleNamespace(scritto=True),
                    {"contenuto": str(bando["contenuto"]) + " Scadenza aggiornata."})

        async def riscrivi(bando_id, novita, *, spesa, tetti, **_k):
            self.riscritture.append((bando_id, novita))
            # Il conto lo fa la riscrittura: l'involucro del client non deve
            # contarla una seconda volta.
            pre.registra_uso("claude-opus-4-7", SimpleNamespace(
                usage=SimpleNamespace(input_tokens=1000, output_tokens=1000)))
            return SimpleNamespace(esito=self.esito_riscrittura, slug="contributi-formazione")

        def allinea(bando_id, dimensione, ids, **_k):
            self.junction_scritte.append((bando_id, dimensione, list(ids)))
            prima = self.junction[bando_id][dimensione]
            return {"cambiato": True, "prima": prima, "dopo": sorted(ids),
                    "tolti": [i for i in prima if i not in ids]}

        def evento(parametri, **_k):
            self.eventi.append(dict(parametri))
            return {"id": 1, "nuovo": True, "applicato": self.applicato}

        async def scrivi_prosa(bando_id, payload):
            self.prose_scritte.append((bando_id, dict(payload)))
            return True

        with contextlib.ExitStack() as pila:
            def p(obj, nome, valore):
                pila.enter_context(patch.object(obj, nome, valore))

            p(rf.db, "select_da_rielaborare", lambda **k: [dict(r) for r in self.righe])
            p(rf.db, "select_junction", lambda ids, **k: self.junction)
            if self.client is None:
                p(rf.db, "registra_evento_rpc", evento)
                p(rf.db, "allinea_junction", self.allinea or allinea)
                p(rf.db, "aggiorna_fk_bando",
                  lambda i, pl, **k: self.fk.append((i, dict(pl))) or {"scritto": True})
                p(rf.db, "aggiorna_link",
                  lambda i, pl, **k: self.marcatori.append((i, dict(pl))) or {"scritto": True})
                p(rf.db, "aggiorna_controllo",
                  lambda i, pl, **k: self.controlli.append((i, dict(pl))) or {"scritto": True})
                p(rf.db, "segna_cambiamento_pubblico",
                  lambda i, **k: self.segnati.append(i) or {"scritto": True})
            else:
                # Le funzioni vere di `db`, sulle tabelle in memoria.
                p(rf.db, "get_supabase", lambda: self.client)
                p(rf.db, "controllo", _ControlloPieno(self.client))
            if self.prosa == "vera":
                p(rigenera, "scrivi_su_db", scrivi_prosa)
            else:
                p(rf, "_rigenera_prosa", self.prosa or prosa)
            p(rf, "_contesto_fonti", lambda righe: {})
            p(rf, "_consumo_di_oggi", lambda: self.gia_oggi)
            if not self.crediti_veri:
                p(rf, "_crediti_scarico", lambda: self.crediti[0])
            p(rf, "_catalogo", lambda: self.catalogo)
            p(rf, "_analizza", analizza_e_registra)
            p(rf, "_testo_letto", testo)
            if not self.classifica_vera:
                p(rf, "_classifica", classifica)
            p(rf, "_riscrittore", lambda: riscrivi if self.riscrittore else None)
            p(rf, "oggi_roma", lambda *a: OGGI)
            p(telemetria, "scrivi_pipeline_run", self.righe_run.append)
            return asyncio.run(rf.run(**kwargs))


class _ControlloPieno(db.Controllo):
    """Lo schema ha tutte le tabelle, le colonne e le RPC; il client e' quello
    in memoria. Il resto di `Controllo` (cioe' `aggiorna`) e' quello vero."""

    def __init__(self, client):
        super().__init__(lambda: {}, client_factory=lambda: client)

    def tabella_esiste(self, _tabella):
        return True

    def ha(self, _tabella, _colonna):
        return True

    def rpc_disponibile(self, _nome):
        return True

    def colonne_mancanti(self, _tabella, _payload):
        return ()


class _ClientInMemoria:
    """PostgREST minimo in memoria per le funzioni vere di `db`.

    `guasti` = insieme di `(operazione, tabella)` che sollevano all'execute:
    operazione in `select`, `insert`, `delete`, `update`, e `("rpc", nome)`.
    La RPC `bando_registra_evento` registra l'evento e, con `p_applica`, scrive
    la data nella riga di `bando`, come quella vera.
    """

    def __init__(self, tabelle=None, *, guasti=()):
        self.tabelle = {n: [dict(r) for r in rr] for n, rr in (tabelle or {}).items()}
        self.guasti = set(guasti)
        self.rpc_chiamate: list[tuple[str, dict]] = []
        self.operazioni: list[tuple] = []

    def table(self, nome):
        return _QueryInMemoria(self, nome)

    def rpc(self, nome, parametri):
        client = self

        class _Chiamata:
            def execute(self):
                if ("rpc", nome) in client.guasti:
                    raise RuntimeError(f"rpc {nome} rifiutata")
                client.rpc_chiamate.append((nome, dict(parametri)))
                applica = bool(parametri.get("p_applica"))
                if applica:
                    for riga in client.tabelle.get("bando", []):
                        if riga.get("id") == parametri.get("p_bando_id"):
                            riga.update(parametri.get("p_valore_dopo") or {})
                dati = {"id": len(client.rpc_chiamate), "nuovo": True, "applicato": applica}
                return SimpleNamespace(data=dati)

        return _Chiamata()


class _QueryInMemoria:
    def __init__(self, client, nome):
        self.client, self.nome = client, nome
        self.filtri: list = []
        self.azione: tuple = ("select", None)

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.filtri.append(lambda r: r.get(c) == v)
        return self

    def in_(self, c, vs):
        self.filtri.append(lambda r: r.get(c) in vs)
        return self

    def insert(self, righe):
        self.azione = ("insert", righe)
        return self

    def delete(self):
        self.azione = ("delete", None)
        return self

    def update(self, payload):
        self.azione = ("update", payload)
        return self

    def upsert(self, riga, on_conflict=""):
        self.azione = ("upsert", (dict(riga), on_conflict))
        return self

    def execute(self):
        tipo, dati = self.azione
        if (tipo, self.nome) in self.client.guasti:
            raise RuntimeError(f"{tipo} su {self.nome} rifiutato")
        righe = self.client.tabelle.setdefault(self.nome, [])
        scelte = [r for r in righe if all(f(r) for f in self.filtri)]
        if tipo == "insert":
            nuove = [dict(r) for r in (dati if isinstance(dati, list) else [dati])]
            righe.extend(nuove)
            self.client.operazioni.append(("insert", self.nome, nuove))
            return SimpleNamespace(data=nuove)
        if tipo == "delete":
            self.client.tabelle[self.nome] = [r for r in righe if r not in scelte]
            self.client.operazioni.append(("delete", self.nome, scelte))
            return SimpleNamespace(data=scelte)
        if tipo == "update":
            for r in scelte:
                r.update(dati)
            self.client.operazioni.append(("update", self.nome, dict(dati)))
            return SimpleNamespace(data=scelte)
        if tipo == "upsert":
            riga, chiave = dati
            esistente = [r for r in righe if r.get(chiave) == riga.get(chiave)]
            if esistente:
                esistente[0].update(riga)
            else:
                righe.append(dict(riga))
            self.client.operazioni.append(("upsert", self.nome, dict(riga)))
            return SimpleNamespace(data=[riga])
        return SimpleNamespace(data=[dict(r) for r in scelte])


class FunzioniPure(unittest.TestCase):
    def test_marcatore(self):
        valore = rf.marcatore("testo", OGGI)
        self.assertTrue(valore.startswith("rielab:v1:2026-10-02:"))
        self.assertEqual(len(valore.rsplit(":", 1)[1]), 64)

    def test_citazione_provata(self):
        self.assertTrue(rf.citazione_provata("entro il 30/11/2026", date(2026, 11, 30), TESTO))
        self.assertTrue(rf.citazione_provata("ENTRO IL  30/11/2026", date(2026, 11, 30), TESTO))
        self.assertFalse(rf.citazione_provata(None, date(2026, 11, 30), TESTO))
        self.assertFalse(rf.citazione_provata("", date(2026, 11, 30), TESTO))
        self.assertFalse(rf.citazione_provata("entro il 15/12/2026", date(2026, 12, 15), TESTO),
                         "la citazione non e' nel testo letto")
        self.assertFalse(rf.citazione_provata("entro il 30/11/2026", date(2026, 12, 1), TESTO),
                         "la citazione non contiene la data")

    def test_serve_transizione(self):
        self.assertFalse(rf.serve_transizione("aperto", None, date(2026, 11, 30), OGGI))
        self.assertTrue(rf.serve_transizione("aperto", None, date(2026, 9, 1), OGGI))
        self.assertTrue(rf.serve_transizione("chiuso", None, date(2026, 11, 30), OGGI))
        self.assertTrue(rf.serve_transizione("in apertura prossimamente", date(2026, 9, 1),
                                             date(2026, 11, 30), OGGI))
        self.assertTrue(rf.serve_transizione("sospeso", None, date(2026, 11, 30), OGGI))

    def test_nomi_nel_testo(self):
        self.assertEqual(rf.nomi_nel_testo([12], CATALOGO["regioni"], "Imprese del lazio"),
                         ["Lazio"])
        self.assertEqual(rf.nomi_nel_testo([11], CATALOGO["regioni"], "Imprese del Lazio"), [])


class GiroAttivo(unittest.TestCase):
    def test_un_bando_completo(self):
        giro = _Giro()
        esito = giro.esegui()
        # Data: un evento di rettifica applicato, mai lo stato, mai data_pubblicazione.
        self.assertEqual(len(giro.eventi), 1)
        evento = giro.eventi[0]
        self.assertEqual((evento["p_tipo"], evento["p_origine"], evento["p_campo"]),
                         ("rettifica", "pipeline", "data_scadenza"))
        self.assertEqual(evento["p_valore_dopo"], {"data_scadenza": "2026-11-30"})
        self.assertIsNone(evento["p_citazione"])
        self.assertTrue(evento["p_applica"])
        self.assertFalse(evento["p_in_aggiornamenti"])
        self.assertEqual(evento["p_metodo"], "rielaborazione")
        self.assertEqual(evento["p_gate"]["citazione"], "entro il 30/11/2026")
        self.assertEqual(evento["p_url_prova"], UFFICIALE)
        self.assertNotIn("stato_bando", evento["p_valore_dopo"])
        self.assertEqual(giro.prose, [(7, date(2026, 10, 30), date(2026, 11, 30), "scadenza")])
        # Junction: solo regioni (settori fallita, beneficiari uguale).
        self.assertEqual(giro.junction_scritte, [(7, "regioni", [11])])
        self.assertEqual(giro.fk, [(7, {"tipologia_bando_id": 2})])
        # Lazio tolto e nominato nella scheda: riscrittura.
        self.assertEqual(len(giro.riscritture), 1)
        self.assertEqual(giro.riscritture[0][1][0]["non_piu_valide"], ["Lazio"])
        # Marcatore sulla riga della fonte.
        self.assertEqual(giro.marcatori[0][0], 70)
        self.assertTrue(giro.marcatori[0][1]["impronta_contenuto"].startswith("rielab:v1:2026-10-02:"))
        # Contatori, cambi, copertura, riga del passo.
        self.assertEqual((esito["date_applicate"], esito["junction_cambiate"], esito["fk_cambiate"],
                          esito["riscritture"], esito["rielaborati"]), (1, 1, 1, 1, 1))
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 1, "rimasti": 0, "motivo_rimasti": None})
        self.assertIn({"bando_id": 7, "dimensione": "regioni", "prima": [12], "dopo": [11]},
                      esito["cambi"])
        self.assertIn({"bando_id": 7, "dimensione": "tipologia_bando_id", "prima": 1, "dopo": 2},
                      esito["cambi"])
        self.assertEqual(esito["slug_modificati"], ["contributi-formazione"])
        self.assertEqual([r.step for r in giro.righe_run], ["backfill:rielaborazione"])
        self.assertIn("cambi", giro.righe_run[0].contatori)
        # La spesa di Opus la conta la riscrittura, non l'involucro (niente doppio).
        self.assertNotIn("claude-opus-4-7", esito["spesa"]["modelli"])

    def test_dry_run_non_scrive_niente(self):
        giro = _Giro()
        esito = giro.esegui(dry_run=True)
        for registro in (giro.eventi, giro.junction_scritte, giro.fk, giro.marcatori,
                         giro.controlli, giro.righe_run, giro.prose, giro.riscritture):
            self.assertEqual(registro, [])
        proposta = esito["proposte"][0]
        self.assertEqual(proposta["date"][0]["dopo"], "2026-11-30")
        self.assertEqual(proposta["riscrittura"], {"nominati": ["Lazio"]})
        self.assertEqual(len(proposta["cambi"]), 2)

    def test_data_verificata_non_si_tocca(self):
        giro = _Giro(righe=[_bando(data_scadenza_verificata=True)])
        esito = giro.esegui()
        self.assertEqual((giro.eventi, esito["discordanze_verificate"]), ([], 1))

    def test_data_non_provata_non_si_scrive(self):
        giro = _Giro(testo="Pagina senza la frase della scadenza.")
        esito = giro.esegui()
        self.assertEqual((giro.eventi, esito["date_non_provate"]), ([], 1))

    def test_date_incoerenti(self):
        analisi = lambda b: _analisi(data_apertura="2026-12-15",  # noqa: E731
                                     _citazioni={"data_apertura": "dal 15/12/2026",
                                                 "data_scadenza": "entro il 30/11/2026"})
        giro = _Giro(analisi=analisi, testo=TESTO + " Apertura dal 15/12/2026.")
        esito = giro.esegui()
        self.assertEqual(giro.eventi, [])
        self.assertEqual(esito["date_incoerenti"], 2)

    def test_mai_la_data_di_pubblicazione(self):
        analisi = lambda b: _analisi(data_scadenza="2026-10-30",  # noqa: E731
                                     data_pubblicazione="2026-09-20")
        giro = _Giro(analisi=analisi)
        giro.esegui()
        self.assertEqual(giro.eventi, [])

    def test_evento_non_applicato_nessuna_prosa(self):
        giro = _Giro(applicato=False)
        esito = giro.esegui()
        self.assertEqual((esito["date_non_applicate"], giro.prose), (1, []))

    def test_chiamata_fallita_o_vuota_non_svuota(self):
        classifica = lambda b: _classifica(regioni_ids=[], beneficiari_ids=[9],  # noqa: E731
                                           tipologia_bando_id=None,
                                           _fallite=("beneficiari", "settori"))
        giro = _Giro(classifica=classifica)
        esito = giro.esegui()
        self.assertEqual(giro.junction_scritte, [])
        self.assertEqual(giro.fk, [])
        self.assertEqual(esito["junction_cambiate"], 0)

    def test_pagina_illeggibile_si_riprova(self):
        giro = _Giro(analisi=lambda b: _analisi(_needs_fallback=True))
        esito = giro.esegui()
        # §19.5: il tentativo si annota, il bando resta in coda.
        self.assertEqual(giro.marcatori, [(70, {"impronta_contenuto": "rielab:v1:incompleto:1"})])
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 0, "rimasti": 1, "motivo_rimasti": "errore"})

    def test_non_valido_si_marca_e_si_conta(self):
        giro = _Giro(analisi=lambda b: _analisi(is_valid_bando=False))
        esito = giro.esegui()
        self.assertEqual(esito["non_validi"], 1)
        self.assertEqual(len(giro.marcatori), 1)
        self.assertEqual((giro.eventi, giro.junction_scritte), ([], []))

    def test_riscrittore_assente(self):
        giro = _Giro(riscrittore=False)
        esito = giro.esegui()
        self.assertEqual(esito["riscritture_non_disponibili"], 1)

    def test_tempo_finito(self):
        giro = _Giro()
        esito = giro.esegui(tempo_s=0.0)
        self.assertEqual(giro.marcatori, [])
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "tempo")


# --- revisione avversaria finale, ciclo 1 (contratto §18) ----------------------
# Le scritture passano dalle funzioni vere di `db` su `_ClientInMemoria`.

def _tabelle(**bando):
    riga = _bando(**bando)
    return {
        "bando": [{k: riga[k] for k in ("id", "stato_bando", "data_apertura", "data_scadenza",
                                         "tipologia_bando_id", "modalita_erogazione_id",
                                         "programma_id")}],
        "bando_regioni": [{"bando_id": 7, "regione_id": 12}],
        "bando_settori": [{"bando_id": 7, "settore_id": 5}],
        "bando_beneficiari": [{"bando_id": 7, "beneficiario_id": 3}],
        "bando_link": [{"id": 70, "bando_id": 7, "impronta_contenuto": None}],
    }


def _giro_vero(*, guasti=(), bando=None, **kwargs):
    bando = dict(bando or {})
    client = _ClientInMemoria(_tabelle(**bando), guasti=guasti)
    return _Giro(righe=[_bando(**bando)], client=client, **kwargs), client


def _marcatore(client):
    return client.tabelle["bando_link"][0].get("impronta_contenuto")


def _regioni(client):
    return sorted(r["regione_id"] for r in client.tabelle["bando_regioni"])


class FonteSoloUfficiale(unittest.TestCase):
    """§18.1: niente lavoro senza la pagina ufficiale (con `scegli_fonte` vero)."""

    def _senza_fonte(self, **bando):
        giro, client = _giro_vero(bando=bando)
        esito = giro.esegui()
        self.assertEqual(esito["senza_fonte_leggibile"], 1)
        self.assertEqual(giro.analizzati, [], "nessuna lettura, nessuna spesa")
        self.assertEqual((client.rpc_chiamate, client.operazioni), ([], []))
        self.assertIsNone(_marcatore(client))
        self.assertEqual(esito["copertura"]["candidati"], 0)
        return esito

    def test_pdf_ufficiale_ripiega_sull_aggregatore(self):
        self._senza_fonte(fonte_ufficiale_url="https://www.regione.marche.it/bando.pdf")

    def test_url_vuoto(self):
        self._senza_fonte(fonte_ufficiale_url=None, link_bando="")

    def test_aggregatore_come_fonte(self):
        self._senza_fonte(fonte_ufficiale_url="https://www.obiettivoeuropa.com/x")

    def test_nel_dry_run_si_vede(self):
        giro, _client = _giro_vero(bando={"fonte_ufficiale_url": "https://www.regione.marche.it/b.pdf"})
        esito = giro.esegui(dry_run=True)
        self.assertEqual(esito["proposte"][0]["motivo"], "senza fonte leggibile")

    def test_gli_altri_bandi_vanno_avanti(self):
        righe = [_bando(), _bando(id=8, fonte_ufficiale_link_id=80,
                                  fonte_ufficiale_url="https://www.regione.marche.it/b.pdf")]
        giro = _Giro(righe=righe)
        esito = giro.esegui()
        self.assertEqual(giro.analizzati, [7])
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 1, "rimasti": 0, "motivo_rimasti": None})


class DateConTransizione(unittest.TestCase):
    """§18.2: niente riaperture da una sola lettura; la scadenza passata si applica."""

    def test_chiuso_con_scadenza_futura_e_da_decidere(self):
        giro, client = _giro_vero(bando={"stato_bando": "chiuso", "data_scadenza": "2026-09-15"},
                                  prosa="vera")
        esito = giro.esegui()
        self.assertEqual(len(client.rpc_chiamate), 1)
        nome, parametri = client.rpc_chiamate[0]
        self.assertEqual(nome, "bando_registra_evento")
        self.assertEqual((parametri["p_tipo"], parametri["p_campo"]), ("rettifica", "data_scadenza"))
        self.assertIs(parametri["p_applica"], False)
        self.assertIs(parametri["p_leggibile"], False)
        self.assertIs(parametri["p_in_aggiornamenti"], False)
        self.assertEqual(parametri["p_metodo"], "rielaborazione")
        self.assertEqual(parametri["p_gate"]["citazione"], "entro il 30/11/2026")
        self.assertEqual(parametri["p_gate"]["pagina"], UFFICIALE)
        self.assertEqual(parametri["p_gate"]["stato_bando"], "chiuso")
        self.assertNotIn("stato_bando", parametri["p_valore_dopo"])
        # Niente di applicato: ne' la data ne' la prosa.
        self.assertEqual(client.tabelle["bando"][0]["data_scadenza"], "2026-09-15")
        self.assertEqual(giro.prose_scritte, [])
        self.assertEqual((esito["transizioni_da_decidere"], esito["date_applicate"]), (1, 0))
        # Il bando si marca: la decisione e' a mano.
        self.assertTrue(_marcatore(client).startswith("rielab:v1:"))
        self.assertEqual(esito["copertura"]["fatti"], 1)

    def test_aperto_con_scadenza_passata_si_applica_la_sola_data(self):
        analisi = lambda b: _analisi(data_scadenza="2026-09-20",  # noqa: E731
                                     _citazioni={"data_scadenza": "entro il 20/09/2026"})
        giro, client = _giro_vero(analisi=analisi, testo=TESTO + " Termine: entro il 20/09/2026.")
        esito = giro.esegui()
        parametri = client.rpc_chiamate[0][1]
        self.assertIs(parametri["p_applica"], True)
        self.assertEqual(parametri["p_valore_dopo"], {"data_scadenza": "2026-09-20"})
        self.assertNotIn("p_leggibile", parametri)
        self.assertEqual(client.tabelle["bando"][0]["data_scadenza"], "2026-09-20")
        self.assertEqual(client.tabelle["bando"][0]["stato_bando"], "aperto",
                         "lo stato lo allinea il job orario, non la rielaborazione")
        self.assertEqual((esito["date_applicate"], esito["transizioni_da_decidere"]), (1, 0))
        self.assertIsNotNone(_marcatore(client))

    def test_in_apertura_con_scadenza_passata_si_applica(self):
        analisi = lambda b: _analisi(data_scadenza="2026-09-20",  # noqa: E731
                                     _citazioni={"data_scadenza": "entro il 20/09/2026"})
        giro, client = _giro_vero(analisi=analisi, testo=TESTO + " Termine: entro il 20/09/2026.",
                                  bando={"stato_bando": "in apertura prossimamente"})
        esito = giro.esegui()
        self.assertIs(client.rpc_chiamate[0][1]["p_applica"], True)
        self.assertEqual(esito["date_applicate"], 1)

    def test_in_apertura_con_apertura_passata_e_da_decidere(self):
        analisi = lambda b: _analisi(data_apertura="2026-09-25",  # noqa: E731
                                     _citazioni={"data_apertura": "dal 25/09/2026",
                                                 "data_scadenza": "entro il 30/11/2026"})
        giro, client = _giro_vero(analisi=analisi, testo=TESTO + " Domande dal 25/09/2026.",
                                  bando={"stato_bando": "in apertura prossimamente"})
        esito = giro.esegui()
        self.assertEqual(sorted(c[1]["p_campo"] for c in client.rpc_chiamate),
                         ["data_apertura", "data_scadenza"])
        self.assertTrue(all(c[1]["p_applica"] is False for c in client.rpc_chiamate))
        self.assertEqual(esito["transizioni_da_decidere"], 1)

    def test_sospeso_e_da_decidere(self):
        giro, client = _giro_vero(bando={"stato_bando": "sospeso"})
        esito = giro.esegui()
        self.assertIs(client.rpc_chiamate[0][1]["p_applica"], False)
        self.assertEqual(esito["transizioni_da_decidere"], 1)

    def test_rpc_fallita_non_si_marca(self):
        giro, client = _giro_vero(bando={"stato_bando": "chiuso", "data_scadenza": "2026-09-15"},
                                  guasti={("rpc", "bando_registra_evento")})
        esito = giro.esegui()
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual((esito["incompleti"], esito["copertura"]["fatti"],
                          esito["copertura"]["motivo_rimasti"]), (1, 0, "errore"))


class MarcatoreSoloACompleto(unittest.TestCase):
    """§18.3: il marcatore solo a lavoro completo; cambi e FK solo se scritti."""

    def test_tutto_scritto_si_marca(self):
        giro, client = _giro_vero(prosa="vera")
        esito = giro.esegui()
        riga = client.tabelle["bando"][0]
        self.assertEqual(riga["data_scadenza"], "2026-11-30")
        self.assertEqual(riga["tipologia_bando_id"], 2)
        self.assertEqual(_regioni(client), [11])
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"))
        self.assertEqual((esito["rielaborati"], esito["incompleti"], esito["fk_cambiate"],
                          esito["junction_cambiate"]), (1, 0, 1, 1))
        self.assertEqual(esito["copertura"],
                         {"candidati": 1, "fatti": 1, "rimasti": 0, "motivo_rimasti": None})

    def test_rpc_fallita(self):
        giro, client = _giro_vero(guasti={("rpc", "bando_registra_evento")})
        esito = giro.esegui()
        self.assertEqual(client.tabelle["bando"][0]["data_scadenza"], "2026-10-30")
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual((esito["date_non_applicate"], esito["incompleti"],
                          esito["copertura"]["motivo_rimasti"]), (1, 1, "errore"))

    def test_junction_in_errore(self):
        giro, client = _giro_vero(guasti={("insert", "bando_regioni")})
        esito = giro.esegui()
        self.assertEqual(_regioni(client), [12])
        self.assertNotIn("regioni", [c["dimensione"] for c in esito["cambi"]])
        self.assertEqual(esito["junction_cambiate"], 0)
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)

    def test_junction_a_meta(self):
        giro, client = _giro_vero(guasti={("delete", "bando_regioni")})
        esito = giro.esegui()
        self.assertEqual(_regioni(client), [11, 12], "piu' voci, mai meno")
        cambio = [c for c in esito["cambi"] if c["dimensione"] == "regioni"][0]
        self.assertEqual((cambio["prima"], cambio["dopo"], cambio["parziale"]), ([12], [11, 12], True))
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["junction_parziali"], 1)

    def test_fk_non_scritte(self):
        giro, client = _giro_vero(guasti={("update", "bando")})
        esito = giro.esegui()
        self.assertEqual(client.tabelle["bando"][0]["tipologia_bando_id"], 1)
        self.assertEqual(esito["fk_cambiate"], 0)
        self.assertNotIn("tipologia_bando_id", [c["dimensione"] for c in esito["cambi"]])
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)

    def test_dimensione_saltata_per_una_chiamata_fallita(self):
        letture = iter([_classifica(), _classifica(_fallite=("beneficiari",))])
        giro, client = _giro_vero(classifica=lambda b: next(letture))
        esito = giro.esegui()
        self.assertEqual(_regioni(client), [11], "le altre dimensioni si allineano")
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)

    def test_marcatore_non_scritto(self):
        giro, client = _giro_vero(guasti={("update", "bando_link")})
        esito = giro.esegui()
        self.assertIsNone(_marcatore(client))
        self.assertEqual((esito["rielaborati"], esito["marcatori_non_scritti"],
                          esito["copertura"]["fatti"]), (0, 1, 0))

    def test_prosa_non_riallineata_va_a_riscrivi_scheda(self):
        # Un nodo con una riga vuota: `rigenera` non sa rimontarlo e non scrive.
        contenuto = {"sections": [{"type": "paragraph",
                                   "text": "Scadenza:\n\nentro il 30 ottobre 2026."}]}
        giro, client = _giro_vero(prosa="vera", bando={"contenuto": contenuto})
        esito = giro.esegui()
        self.assertEqual(giro.prose_scritte, [])
        self.assertEqual(esito["prose_non_riscritte"], 1)
        self.assertEqual(len(giro.riscritture), 1, "una sola riscrittura per bando")
        novita = giro.riscritture[0][1]
        data = [n for n in novita if n.get("campo") == "data_scadenza"][0]
        self.assertEqual((data["tipo"], data["citazione"], data["url_prova"], data["evento_id"]),
                         ("rettifica", "entro il 30/11/2026", UFFICIALE, 1))
        self.assertIsNotNone(_marcatore(client))

    def test_prosa_jsonb_nel_giro_vero(self):
        contenuto = {"sections": [
            {"type": "paragraph", "text": "Le domande vanno presentate entro il 30 ottobre 2026."},
            {"type": "paragraph", "text": "Il bando vale per le imprese del Lazio."}]}
        giro, _client = _giro_vero(prosa="vera", bando={"contenuto": contenuto})
        esito = giro.esegui()
        scritto = giro.prose_scritte[0][1]["contenuto"]
        self.assertIsInstance(scritto, dict)
        self.assertIn("30 novembre 2026", scritto["sections"][0]["text"])
        self.assertEqual(esito["prose_riallineate"], 1)


class CreditiFirecrawl(unittest.TestCase):
    """§18.4: i crediti dello scarico entrano nella spesa e nei tetti."""

    def setUp(self):
        self.scarico = scarico.Scarico()
        scarico.imposta_scarico(self.scarico)
        self.addCleanup(scarico.imposta_scarico, None)

    def _analizza_che_spende(self, crediti):
        async def analizza(bando, fonte, url):
            # Come il ripiego Firecrawl dello scarico vero.
            scarico.contatori().crediti_firecrawl += crediti
            return _analisi()
        return analizza

    def test_crediti_contati_e_tetto(self):
        righe = [_bando(id=i, fonte_ufficiale_link_id=i * 10) for i in (7, 8, 9)]
        giro = _Giro(righe=righe, analizza=self._analizza_che_spende(2),
                     junction={i: {"regioni": [11], "settori": [], "beneficiari": [3],
                                   "codici_ateco": []} for i in (7, 8, 9)})
        giro.crediti_veri = True
        self.scarico.contatori.crediti_firecrawl = 5          # spesi prima del passo
        with patch.object(rf, "_tetti", lambda: bilancio.Tetti(backfill_crediti=3)):
            esito = giro.esegui(parallelo=1)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual(esito["spesa"]["crediti_firecrawl"], 4, "solo i crediti del passo")
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "crediti")
        self.assertEqual(giro.righe_run[0].crediti_effettivi, 4)

    def test_giornata_somma_i_crediti(self):
        giro = _Giro(analizza=self._analizza_che_spende(3))
        giro.crediti_veri = True
        giro.gia_oggi = {"crediti": 7990.0, "usd": 0.0}
        with patch.object(rf, "_tetti", lambda: bilancio.Tetti(backfill_crediti=8000)):
            esito = giro.esegui()
        self.assertEqual(esito["spesa"]["crediti_firecrawl"], 3)

    def test_contatori_azzerati_a_meta(self):
        giro = _Giro()
        giro.crediti = [10]

        async def analizza(bando, fonte, url):
            giro.crediti[0] = 3                                # `svuota` e poi 3 crediti
            return _analisi()

        giro.analizza = analizza
        esito = giro.esegui()
        self.assertEqual(esito["spesa"]["crediti_firecrawl"], 3)

    def test_anche_nel_dry_run(self):
        giro = _Giro(analizza=self._analizza_che_spende(1))
        giro.crediti_veri = True
        esito = giro.esegui(dry_run=True)
        self.assertEqual(esito["spesa"]["crediti_firecrawl"], 1)


class TentativiEAbbandono(unittest.TestCase):
    """P2 di #160: un incompleto si annota; al terzo tentativo si marca come
    fatto con il motivo, e non si ripaga a ogni giro."""

    def test_tentativi_falliti(self):
        self.assertEqual(rf.tentativi_falliti(None), 0)
        self.assertEqual(rf.tentativi_falliti("rielab:v1:2026-10-01:abc"), 0)
        self.assertEqual(rf.tentativi_falliti("rielab:v1:incompleto:2"), 2)
        self.assertEqual(rf.tentativi_falliti("rielab:v1:incompleto:x"), 0)

    def test_secondo_tentativo(self):
        giro, client = _giro_vero(guasti={("insert", "bando_regioni")},
                                  bando={"_marcatore": "rielab:v1:incompleto:1"})
        esito = giro.esegui()
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:2")
        self.assertEqual((esito["incompleti"], esito["abbandonati"]), (1, 0))
        self.assertEqual(esito["copertura"]["fatti"], 0)

    def test_al_terzo_si_abbandona_con_il_motivo(self):
        giro, client = _giro_vero(guasti={("insert", "bando_regioni")},
                                  bando={"_marcatore": "rielab:v1:incompleto:2"})
        esito = giro.esegui()
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"),
                        "marcato come fatto: non torna in coda")
        self.assertFalse(db.da_rielaborare(_marcatore(client)))
        self.assertEqual((esito["abbandonati"], esito["incompleti"], esito["rielaborati"]),
                         (1, 0, 0))
        self.assertEqual(esito["motivi_abbandono"], {"junction regioni": 1})
        self.assertEqual(esito["copertura"]["fatti"], 1)
        self.assertEqual(giro.righe_run[0].contatori["motivi_abbandono"], {"junction regioni": 1})
        # Il resto del lavoro riuscito resta scritto (data e FK).
        self.assertEqual(client.tabelle["bando"][0]["data_scadenza"], "2026-11-30")

    def test_pagina_illeggibile_al_terzo_si_abbandona(self):
        # §19.5: una pagina dell'ente morta non si riscarica per sempre.
        giro, client = _giro_vero(analisi=lambda b: _analisi(_needs_fallback=True),
                                  bando={"_marcatore": "rielab:v1:incompleto:2"})
        esito = giro.esegui()
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"))
        self.assertEqual((esito["abbandonati"], esito["pagine_illeggibili"]), (1, 1))
        self.assertEqual(esito["motivi_abbandono"], {"pagina illeggibile": 1})
        self.assertEqual(esito["copertura"]["fatti"], 1)
        self.assertEqual(client.rpc_chiamate, [], "niente scritto oltre al marcatore")

    def test_eccezione_e_un_tentativo(self):
        async def esplode(bando, fonte, url):
            raise RuntimeError("guasto")

        giro, client = _giro_vero(analizza=esplode)
        esito = giro.esegui()
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual((esito["errori"], esito["incompleti"]), (1, 1))
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "errore")

    def test_eccezione_al_terzo_si_abbandona(self):
        async def esplode(bando, fonte, url):
            raise RuntimeError("guasto")

        giro, client = _giro_vero(analizza=esplode,
                                  bando={"_marcatore": "rielab:v1:incompleto:2"})
        esito = giro.esegui()
        self.assertFalse(db.da_rielaborare(_marcatore(client)))
        self.assertEqual(esito["motivi_abbandono"], {"errore RuntimeError": 1})
        self.assertEqual((esito["abbandonati"], esito["copertura"]["fatti"]), (1, 1))

    def test_nel_dry_run_non_si_annota(self):
        giro, client = _giro_vero(guasti={("insert", "bando_regioni")})
        esito = giro.esegui(dry_run=True)
        self.assertIsNone(_marcatore(client))
        self.assertEqual(esito["incompleti"], 0, "nel dry-run la junction non si scrive")


class CodaDelleRiscritture(unittest.TestCase):
    """P2 di #160: data in colonna, prosa non riallineata e `riscrivi_scheda`
    non riuscita → le novita' nella coda `__riscrittura__` del monitor, nella
    sua forma (letta con `monitoraggio.riscrittura_in_coda` vera)."""

    CONTENUTO = {"sections": [{"type": "paragraph",
                               "text": "Scadenza:\n\nentro il 30 ottobre 2026."}]}
    MEMORIA = {"s1": "impronta-sezione", "__link__": {"a": 1}, "__versione__": 3}

    def _giro(self, *, guasti=(), coda=None, **kwargs):
        giro, client = _giro_vero(prosa="vera", guasti=guasti,
                                  bando={"contenuto": self.CONTENUTO}, **kwargs)
        sezioni = dict(self.MEMORIA)
        if coda is not None:
            sezioni["__riscrittura__"] = coda
        client.tabelle["bando_controllo"] = [{"bando_id": 7, "impronte_sezioni": sezioni}]
        return giro, client

    def _coda(self, client):
        riga = client.tabelle["bando_controllo"][0]
        return riga, monitoraggio.riscrittura_in_coda(riga)

    def test_riscrittura_fallita_va_in_coda(self):
        giro, client = self._giro()
        giro.esito_riscrittura = "fallita"
        esito = giro.esegui()
        riga, coda = self._coda(client)
        self.assertIsNotNone(coda, "il monitor la vede")
        data = [n for n in coda["novita"] if n.get("campo") == "data_scadenza"][0]
        self.assertEqual((data["evento_id"], data["citazione"], data["url_prova"]),
                         (1, "entro il 30/11/2026", UFFICIALE))
        self.assertEqual(coda["tentativi"], 0)
        self.assertTrue(coda["dal"])
        # La memoria del monitor resta com'era.
        for chiave, valore in self.MEMORIA.items():
            self.assertEqual(riga["impronte_sezioni"][chiave], valore)
        self.assertIn("prossimo_controllo_at", riga)
        self.assertEqual((esito["riscritture_in_coda"], esito["riscritture_non_riuscite"]), (1, 1))
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"))

    def test_riscrittore_assente_va_in_coda(self):
        giro, client = self._giro(riscrittore=False)
        esito = giro.esegui()
        self.assertIsNotNone(self._coda(client)[1])
        self.assertEqual((esito["riscritture_non_disponibili"], esito["riscritture_in_coda"]), (1, 1))

    def test_si_unisce_alla_coda_che_c_e(self):
        vecchia = {"novita": [{"evento_id": 99, "tipo": "proroga", "campo": "data_scadenza",
                               "citazione": "prorogato", "url_prova": UFFICIALE}],
                   "tentativi": 2, "dal": "2026-09-30T06:00:00+00:00"}
        giro, client = self._giro(coda=vecchia)
        giro.esito_riscrittura = "rinviata"
        giro.esegui()
        coda = self._coda(client)[1]
        self.assertEqual([n["evento_id"] for n in coda["novita"]][:2], [99, 1])
        self.assertEqual((coda["tentativi"], coda["dal"]), (2, "2026-09-30T06:00:00+00:00"))

    def test_riscrittura_riuscita_niente_coda(self):
        giro, client = self._giro()
        esito = giro.esegui()
        self.assertIsNone(self._coda(client)[1])
        self.assertEqual(esito["riscritture_in_coda"], 0)

    def test_coda_illeggibile_non_si_scrive(self):
        # Una colonna riscritta con la sola coda cancellerebbe le impronte del
        # monitor: se la lettura fallisce non si scrive, e il lavoro e' incompleto.
        giro, client = self._giro(guasti={("select", "bando_controllo")})
        giro.esito_riscrittura = "fallita"
        esito = giro.esegui()
        riga, coda = self._coda(client)
        self.assertIsNone(coda)
        self.assertEqual(riga["impronte_sezioni"], self.MEMORIA)
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)


class CatalogoIlleggibile(unittest.TestCase):
    """§19.4: con `enrich_bando` vera, una dimensione senza catalogo e' fallita
    e il bando resta incompleto (niente marcatore)."""

    def test_catalogo_senza_regioni(self):
        enricher = carica_modulo("enricher")
        voci = [{"id": 3, "nome": "Imprese"}, {"id": 5, "nome": "Formazione"}]
        catalogo = {nome: voci for nome in (
            "tipologie", "modalita", "programmi", "beneficiari", "codici_ateco", "settori")}
        catalogo["regioni"] = []

        async def chiama(client, *, tool, **_k):
            return {"ids": [3]} if "ids" in str(tool) else {"id": 3}

        giro, client = _giro_vero()
        giro.classifica_vera = True
        giro.catalogo = catalogo
        with patch.object(enricher, "_get_anthropic_client", return_value=object()), \
                patch.object(enricher, "_call_anthropic_tool", new=chiama):
            esito = giro.esegui()
        self.assertEqual(_regioni(client), [12], "le regioni non si toccano")
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)


class CambiamentoPubblico(unittest.TestCase):
    """§20.1: junction cambiate → `ultimo_cambiamento_at` del bando avanza
    (una volta per bando), cosi' API, sitemap e BandoFit vedono il cambio.
    Funzioni vere di `db` sul client in memoria."""

    @staticmethod
    def _segni(client):
        return [op for op in client.operazioni
                if op[0] == "update" and op[1] == "bando" and "ultimo_cambiamento_at" in op[2]]

    def test_due_junction_un_solo_segno(self):
        classifica = lambda b: _classifica(regioni_ids=[11], beneficiari_ids=[3, 7])  # noqa: E731
        giro, client = _giro_vero(classifica=classifica)
        esito = giro.esegui()
        self.assertEqual(esito["junction_cambiate"], 2)
        segni = self._segni(client)
        self.assertEqual(len(segni), 1)
        self.assertEqual(list(segni[0][2]), ["ultimo_cambiamento_at"], "solo quella colonna")
        self.assertTrue(client.tabelle["bando"][0]["ultimo_cambiamento_at"].startswith("20"))
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"))

    def test_senza_junction_cambiate_niente_segno(self):
        classifica = lambda b: _classifica(regioni_ids=[12], beneficiari_ids=[3])  # noqa: E731
        giro, client = _giro_vero(classifica=classifica)
        esito = giro.esegui()
        self.assertEqual(esito["junction_cambiate"], 0)
        self.assertEqual(self._segni(client), [], "le FK le vede gia' il trigger")

    def test_nel_dry_run_niente_segno(self):
        giro, client = _giro_vero()
        giro.esegui(dry_run=True)
        self.assertEqual(self._segni(client), [])

    def test_junction_a_meta_segna_lo_stesso(self):
        giro, client = _giro_vero(guasti={("delete", "bando_regioni")})
        giro.esegui()
        self.assertEqual(len(self._segni(client)), 1, "le righe inserite ci sono")

    def test_dopo_un_segno_mancato_si_segna_al_giro_dopo(self):
        # P2 di #173: al giro dopo le junction sono gia' allineate (nessun
        # cambio), ma il bando arriva incompleto: il segno si riprova.
        classifica = lambda b: _classifica(regioni_ids=[12], beneficiari_ids=[3])  # noqa: E731
        giro, client = _giro_vero(classifica=classifica,
                                  bando={"_marcatore": "rielab:v1:incompleto:1"})
        esito = giro.esegui()
        self.assertEqual(esito["junction_cambiate"], 0)
        self.assertEqual(len(self._segni(client)), 1)
        self.assertTrue(_marcatore(client).startswith("rielab:v1:2026-10-02:"))

    def test_marcatore_d_altro_tipo_non_segna(self):
        classifica = lambda b: _classifica(regioni_ids=[12], beneficiari_ids=[3])  # noqa: E731
        giro, client = _giro_vero(classifica=classifica, bando={"_marcatore": "sha-del-monitor"})
        giro.esegui()
        self.assertEqual(self._segni(client), [])

    def test_rielaborazione_incompleta(self):
        self.assertTrue(rf.rielaborazione_incompleta("rielab:v1:incompleto:2"))
        self.assertFalse(rf.rielaborazione_incompleta("rielab:v1:2026-10-01:abc"))
        self.assertFalse(rf.rielaborazione_incompleta(None))

    def test_segno_non_scritto_lascia_incompleto(self):
        # FK invariate: l'unico UPDATE di `bando` e' il segno, e fallisce.
        classifica = lambda b: _classifica(tipologia_bando_id=1)  # noqa: E731
        giro, client = _giro_vero(classifica=classifica, guasti={("update", "bando")})
        esito = giro.esegui()
        self.assertEqual(_regioni(client), [11], "la junction e' scritta")
        self.assertNotIn("ultimo_cambiamento_at", client.tabelle["bando"][0])
        self.assertEqual(_marcatore(client), "rielab:v1:incompleto:1")
        self.assertEqual(esito["incompleti"], 1)


class ProsaVera(unittest.TestCase):
    """Revisione #146 (P0): la prosa riallineata si scrive nella forma della
    colonna (jsonb con `sections`), mai come `str(dict)`."""

    EVENTO = {"tipo": "rettifica", "campo": "data_scadenza",
              "valore_prima": {"data_scadenza": "2026-10-30"},
              "valore_dopo": {"data_scadenza": "2026-11-15"}}
    # Nella forbice 180-320 di `rigenera`: piu' corta fa scattare il box.
    DESCRIZIONE = ("Contributi a fondo perduto per la formazione dei dipendenti delle "
                   "imprese marchigiane: domande entro il 30 ottobre 2026, con "
                   "istruttoria a sportello e rendicontazione delle spese sostenute "
                   "entro dodici mesi dalla concessione del contributo.")

    def _riallinea(self, contenuto):
        scritti: list[tuple] = []

        async def scrivi_db(bando_id, payload):
            scritti.append((bando_id, dict(payload)))
            return True

        bando = {"id": 7, "slug": "x", "contenuto": contenuto,
                 "descrizione_breve": self.DESCRIZIONE}
        esito = asyncio.run(rf._rigenera_prosa(
            bando, self.EVENTO, vecchia=date(2026, 10, 30), nuova=date(2026, 11, 15),
            ruolo="scadenza", scrivi_db=scrivi_db))
        return esito, scritti

    def test_jsonb_resta_jsonb(self):
        contenuto = {"sections": [
            {"type": "paragraph", "text": "Le domande vanno presentate entro il 30 ottobre 2026."},
            {"type": "paragraph", "text": "Possono partecipare le imprese."}]}
        esito, scritti = self._riallinea(contenuto)
        self.assertIsNotNone(esito)
        self.assertTrue(esito[0].scritto)
        scritto = scritti[0][1]["contenuto"]
        self.assertIsInstance(scritto, dict)
        self.assertIn("15 novembre 2026", scritto["sections"][0]["text"])
        self.assertNotIn("30 ottobre", scritto["sections"][0]["text"])
        self.assertEqual(scritto["sections"][1]["text"], "Possono partecipare le imprese.")
        self.assertEqual(esito[1]["contenuto"], scritto, "il chiamante riceve la forma di colonna")

    def test_la_descrizione_scritta_torna_al_chiamante(self):
        contenuto = {"sections": [
            {"type": "paragraph", "text": "Le domande vanno presentate entro il 30 ottobre 2026."}]}
        esito, scritti = self._riallinea(contenuto)
        payload = scritti[0][1]
        # La seconda data del bando lavora su questa: se ripartisse dalla
        # descrizione letta, riporterebbe indietro la prima.
        self.assertIn("15 novembre 2026", payload["descrizione_breve"])
        self.assertEqual(esito[1]["descrizione_breve"], payload["descrizione_breve"])

    def test_stringa_json_resta_stringa_json(self):
        import json
        contenuto = json.dumps({"sections": [
            {"type": "paragraph", "text": "Le domande vanno presentate entro il 30 ottobre 2026."}]})
        esito, scritti = self._riallinea(contenuto)
        scritto = scritti[0][1]["contenuto"]
        self.assertIsInstance(scritto, str)
        self.assertIn("15 novembre 2026", json.loads(scritto)["sections"][0]["text"])

    def test_contenuto_non_scomponibile_non_si_tocca(self):
        contenuto = {"sections": [{"type": "paragraph",
                                   "text": "Primo paragrafo.\n\nentro il 30 ottobre 2026."}]}
        esito, scritti = self._riallinea(contenuto)
        self.assertIsNone(esito)
        self.assertEqual(scritti, [])

    def test_nel_giro_un_contenuto_non_trattabile_si_conta(self):
        async def prosa(*_a, **_k):
            return None

        esito = _Giro(prosa=prosa).esegui()
        self.assertEqual(esito["prose_riallineate"], 0)
        self.assertGreaterEqual(esito["prose_non_riscritte"], 1)


class JunctionAMeta(unittest.TestCase):
    """Revisione #146 (P2): INSERT riuscito e DELETE fallito."""

    def test_si_registra_si_conta_e_non_si_marca(self):
        giro = _Giro()

        def allinea(bando_id, dimensione, ids, **_k):
            prima = giro.junction[bando_id][dimensione]
            giro.junction_scritte.append((bando_id, dimensione, list(ids)))
            return {"cambiato": True, "parziale": True, "errore": "delete rifiutato",
                    "prima": prima, "dopo": sorted(set(prima) | set(ids)),
                    "inseriti": [i for i in ids if i not in prima], "tolti": []}

        giro.allinea = allinea
        esito = giro.esegui()
        self.assertGreaterEqual(esito["junction_parziali"], 1)
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "errore")
        self.assertEqual(giro.marcatori, [(70, {"impronta_contenuto": "rielab:v1:incompleto:1"})],
                         "il giro dopo deve ripassare")
        self.assertTrue(any(c.get("parziale") for c in esito["cambi"]))


class DueLetture(unittest.TestCase):
    """Decisione del lead dopo il dry-run dell'01/10 (§9): la classificazione
    si legge due volte, e cambia solo cio' su cui le due letture concordano."""

    def _alternate(self, *letture):
        chiamate = {"n": 0}

        def classifica(_bando):
            lettura = letture[chiamate["n"] % len(letture)]
            chiamate["n"] += 1
            return lettura
        return classifica, chiamate

    def test_concordi(self):
        # 1 manca in tutte e due: via; 2 c'e' in una: resta; 4 in tutte e due:
        # entra; 5 in una sola: non entra.
        self.assertEqual(rf.concordi([1, 2, 3], {2, 3, 4}, {3, 4, 5}), [2, 3, 4])
        self.assertEqual(rf.concordi([], {7}, {7}), [7])
        self.assertEqual(rf.concordi([7], {8}, {9}), [])

    def test_due_chiamate_per_bando(self):
        classifica, chiamate = self._alternate(_classifica())
        _Giro(classifica=classifica).esegui()
        self.assertEqual(chiamate["n"], 2)

    def test_letture_discordi(self):
        classifica, _c = self._alternate(
            _classifica(regioni_ids=[11, 13], tipologia_bando_id=2),
            _classifica(regioni_ids=[11, 14], tipologia_bando_id=3))
        giro = _Giro(classifica=classifica)
        esito = giro.esegui()
        # 12 non c'e' in nessuna lettura: via; 11 in tutte e due: entra; 13 e 14
        # in una sola: fuori.
        self.assertEqual(giro.junction_scritte, [(7, "regioni", [11])])
        self.assertEqual(esito["junction_discordi"], 1)
        self.assertEqual(giro.fk, [], "le due letture danno FK diverse: niente")
        self.assertEqual(esito["fk_discordi"], 1)

    def test_una_lettura_fallita_ferma_la_dimensione(self):
        classifica, _c = self._alternate(
            _classifica(_fallite=()), _classifica(_fallite=("regioni", "tipologia")))
        giro = _Giro(classifica=classifica)
        esito = giro.esegui()
        self.assertEqual(giro.junction_scritte, [])
        self.assertEqual(giro.fk, [])
        self.assertEqual(esito["junction_cambiate"], 0)

    def test_una_lettura_vuota_non_dice_niente(self):
        classifica, _c = self._alternate(_classifica(regioni_ids=[11]),
                                         _classifica(regioni_ids=[]))
        giro = _Giro(classifica=classifica)
        giro.esegui()
        self.assertEqual(giro.junction_scritte, [])

    def test_le_due_letture_si_pagano_nel_backfill(self):
        uso = SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=100))

        def classifica(_bando):
            pre.registra_uso("claude-haiku-4-5", uso)
            return _classifica()

        esito = _Giro(classifica=classifica).esegui()
        self.assertEqual(esito["spesa"]["modelli"]["claude-haiku-4-5"]["chiamate"], 2)
        self.assertEqual(rf.STEP, "backfill:rielaborazione")


class SpesaEParallelo(unittest.TestCase):
    def test_tetto_del_backfill_ferma_il_passo(self):
        uso = SimpleNamespace(usage=SimpleNamespace(input_tokens=10_000_000, output_tokens=0))

        def analisi(bando):
            pre.registra_uso("claude-haiku-4-5", uso)          # 10 $ al primo bando
            return _analisi()

        righe = [_bando(), _bando(id=8, fonte_ufficiale_link_id=80)]
        giro = _Giro(righe=righe, analisi=analisi,
                     junction={i: {"regioni": [11], "settori": [], "beneficiari": [3],
                                   "codici_ateco": []} for i in (7, 8)})
        with patch.object(rf, "_tetti", lambda: bilancio.Tetti(backfill_usd=1.0)):
            esito = giro.esegui(parallelo=1)
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual(esito["copertura"],
                         {"candidati": 2, "fatti": 1, "rimasti": 1, "motivo_rimasti": "spesa"})
        self.assertGreater(esito["costo_usd"], 1.0)

    def test_il_tetto_vale_sulla_giornata(self):
        # Revisione #146: 59,50 $ gia' spesi oggi da un lancio precedente, un
        # bando da 10 $: il secondo non parte (per lancio sarebbero partiti).
        uso = SimpleNamespace(usage=SimpleNamespace(input_tokens=10_000_000, output_tokens=0))

        def analisi(bando):
            pre.registra_uso("claude-haiku-4-5", uso)
            return _analisi()

        righe = [_bando(), _bando(id=8, fonte_ufficiale_link_id=80)]
        giro = _Giro(righe=righe, analisi=analisi,
                     junction={i: {"regioni": [11], "settori": [], "beneficiari": [3],
                                   "codici_ateco": []} for i in (7, 8)})
        giro.gia_oggi = {"crediti": 0.0, "usd": 59.5}
        with patch.object(rf, "_tetti", lambda: bilancio.Tetti(backfill_usd=60.0)):
            esito = giro.esegui(parallelo=1)
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual((esito["copertura"]["fatti"], esito["copertura"]["motivo_rimasti"]),
                         (1, "spesa"))
        self.assertEqual(giro.righe_run[0].contatori["consumo_oggi_prima"],
                         {"crediti": 0.0, "usd": 59.5})

    def test_giornata_gia_a_tetto_non_parte_nessuno(self):
        giro = _Giro()
        giro.gia_oggi = {"crediti": 8000.0, "usd": 0.0}
        with patch.object(rf, "_tetti", lambda: bilancio.Tetti(backfill_crediti=8000)):
            esito = giro.esegui()
        self.assertEqual(esito["esaminati"], 0)
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "crediti")
        self.assertEqual(giro.eventi, [])

    def test_consumo_illeggibile_non_parte(self):
        giro = _Giro()
        giro.gia_oggi = None
        esito = giro.esegui()
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual(esito["copertura"]["motivo_rimasti"], "spesa")
        self.assertEqual((giro.eventi, giro.marcatori, giro.righe_run), ([], [], []))

    def test_mai_due_bandi_dello_stesso_host(self):
        stato = {"ora": 0, "massimo": 0}

        async def analizza(bando, fonte, url):
            stato["ora"] += 1
            stato["massimo"] = max(stato["massimo"], stato["ora"])
            await asyncio.sleep(0.01)
            stato["ora"] -= 1
            return _analisi()

        righe = [_bando(id=i, fonte_ufficiale_link_id=i * 10) for i in range(1, 5)]
        giro = _Giro(righe=righe, analizza=analizza,
                     junction={i: {"regioni": [11], "settori": [], "beneficiari": [3],
                                   "codici_ateco": []} for i in range(1, 5)})
        # Stesso host per tutti e quattro: il lucchetto per host li mette in fila.
        esito = giro.esegui(parallelo=5)
        self.assertEqual(stato["massimo"], 1)
        self.assertEqual(esito["rielaborati"], 4)

    def test_host_diversi_vanno_in_parallelo(self):
        stato = {"ora": 0, "massimo": 0}

        async def analizza(bando, fonte, url):
            stato["ora"] += 1
            stato["massimo"] = max(stato["massimo"], stato["ora"])
            await asyncio.sleep(0.01)
            stato["ora"] -= 1
            return _analisi()

        righe = [_bando(id=i, fonte_ufficiale_link_id=i * 10,
                        fonte_ufficiale_url=f"https://ente{i}.it/bando") for i in range(1, 8)]
        giro = _Giro(righe=righe, analizza=analizza,
                     junction={i: {"regioni": [11], "settori": [], "beneficiari": [3],
                                   "codici_ateco": []} for i in range(1, 8)})
        esito = giro.esegui(parallelo=5)
        self.assertEqual(stato["massimo"], 5)
        self.assertEqual(esito["rielaborati"], 7)


class _LockFinto:
    def __init__(self, esito):
        self.esito = esito
        self.presi: list[tuple] = []
        self.rilasciati: list = []

    def acquisisci(self, nome, proprietario, ttl_s):
        self.presi.append((nome, proprietario, ttl_s))
        return SimpleNamespace(nome=nome, proprietario=proprietario,
                               proseguire=self.esito in ("acquisito", "assente"))

    def rilascia(self, preso):
        self.rilasciati.append(preso)


class LockDelComando(unittest.TestCase):
    """Revisione #146: fuori dal dry-run il comando prende il lock del giro."""

    def _lancia(self, esito_lock, *, dry_run=False):
        from unittest.mock import AsyncMock
        finto = AsyncMock(return_value={"status": "ok", "rielaborati": 1})
        lock = _LockFinto(esito_lock)
        with patch.object(rf, "run", finto), patch.object(rf, "tetto_tempo_s", lambda: 3600.0):
            esito = asyncio.run(rf.run_comando(dry_run=dry_run, ids=(7,), lock=lock))
        return esito, finto, lock

    def test_lock_preso_lavora_e_rilascia(self):
        esito, finto, lock = self._lancia("acquisito")
        self.assertEqual(lock.presi, [("bandi_pipeline", "rielabora-fonte:cli", 5400)])
        finto.assert_awaited_once_with(dry_run=False, ids=(7,))
        self.assertEqual(len(lock.rilasciati), 1)
        self.assertEqual(esito["rielaborati"], 1)

    def test_lock_occupato_non_parte(self):
        esito, finto, lock = self._lancia("occupato")
        finto.assert_not_awaited()
        self.assertTrue(esito["saltato_per_lock"])
        self.assertEqual(esito["copertura"]["candidati"], 0)
        self.assertEqual(lock.rilasciati, [])

    def test_dry_run_senza_lock(self):
        esito, finto, lock = self._lancia("occupato", dry_run=True)
        self.assertEqual(lock.presi, [])
        finto.assert_awaited_once_with(dry_run=True, ids=(7,))

    def test_rilascia_anche_se_il_passo_solleva(self):
        lock = _LockFinto("acquisito")

        async def esplode(**_k):
            raise RuntimeError("guasto")

        with patch.object(rf, "run", esplode), self.assertRaises(RuntimeError):
            asyncio.run(rf.run_comando(dry_run=False, lock=lock))
        self.assertEqual(len(lock.rilasciati), 1)

    def test_la_riga_di_comando_esce_con_il_codice_del_lock(self):
        cli = carica_modulo("__main__")
        from unittest.mock import AsyncMock
        finto = AsyncMock(return_value={"status": "ok", "saltato_per_lock": True,
                                        "lock": "bandi_pipeline", "copertura": {}})
        with patch.object(rf, "run_comando", finto):
            codice = cli._cmd_rielabora_fonte(["--ids", "7"])
        finto.assert_awaited_once_with(dry_run=False, ids=(7,))
        self.assertEqual(codice, cli.EXIT_LOCK)


class Comando(unittest.TestCase):
    """`rielabora-fonte [--dry-run] [--ids 1,2,3]` e `risolvi-fonte --precoce`."""

    def setUp(self):
        self.cli = carica_modulo("__main__")

    def test_dry_run_con_gli_id(self):
        from unittest.mock import AsyncMock
        finto = AsyncMock(return_value={"status": "ok", "proposte": [
            {"bando_id": 7, "url": UFFICIALE, "date": [
                {"campo": "data_scadenza", "prima": "2026-10-30", "dopo": "2026-11-30",
                 "citazione": "entro il 30/11/2026"}],
             "cambi": [{"dimensione": "regioni", "prima": [12], "dopo": [11]}],
             "riscrittura": {"nominati": ["Lazio"]}}], "copertura": {}})
        with patch.object(rf, "run", finto):
            codice = self.cli._cmd_rielabora_fonte(["--dry-run", "--ids", "7,8"])
        self.assertEqual(codice, 0)
        finto.assert_awaited_once_with(dry_run=True, ids=(7, 8))

    def test_dry_run_stampa_le_date_da_decidere(self):
        # §18.2: la CLI dice che la data non si applica e va decisa a mano.
        import contextlib
        import io
        from unittest.mock import AsyncMock
        finto = AsyncMock(return_value={"status": "ok", "copertura": {}, "proposte": [
            {"bando_id": 7, "url": UFFICIALE, "transizione_da_decidere": True, "cambi": [],
             "date": [{"campo": "data_scadenza", "prima": "2026-09-15", "dopo": "2026-11-30",
                       "citazione": "entro il 30/11/2026", "da_decidere": True}]},
            {"bando_id": 8, "url": UFFICIALE, "cambi": [],
             "date": [{"campo": "data_scadenza", "prima": "2026-10-30", "dopo": "2026-11-30",
                       "citazione": "entro il 30/11/2026"}]}]})
        uscita = io.StringIO()
        with patch.object(rf, "run", finto), contextlib.redirect_stdout(uscita):
            self.cli._cmd_rielabora_fonte(["--dry-run", "--ids", "7,8"])
        righe = uscita.getvalue().splitlines()
        self.assertIn("    data_scadenza: 2026-09-15 -> 2026-11-30 «entro il 30/11/2026» "
                      "[da decidere: non applicata]", righe)
        self.assertIn("    data nuova con transizione di stato: rettifica non applicata, "
                      "da decidere a mano", righe)
        self.assertIn("    data_scadenza: 2026-10-30 -> 2026-11-30 «entro il 30/11/2026»", righe)
        self.assertNotIn("al monitor", uscita.getvalue())

    def test_niente_limit(self):
        with self.assertRaises(self.cli.ErroreOpzioni):
            self.cli._cmd_rielabora_fonte(["--dry-run", "--limit", "5"])

    def test_registrato(self):
        self.assertIs(self.cli._COMMANDS["rielabora-fonte"], self.cli._cmd_rielabora_fonte)

    def test_risolvi_fonte_precoce(self):
        self.assertEqual(self.cli._modo_selezione(("--precoce",)), "precoce")
        self.assertIn("--precoce", self.cli.FLAG_RESOLVER)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
