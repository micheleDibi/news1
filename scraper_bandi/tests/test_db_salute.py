# -*- coding: utf-8 -*-
"""Misure della salute del giro 2 e riga del riepilogo (contratto `bandi-giro-2` §14).

Cosa si prova, senza rete (client finto che registra ogni chiamata):

- `misure_salute` aggiunge le chiavi del percorso B leggendo e basta: le
  ultime righe del giro e del monitor con i soli contatori mirati, i fermi in
  lavorazione, l'ultimo bando entrato, i tre conteggi sugli eventi con
  `count=exact`. Una colonna assente vale `None`, non zero;
- i contatori mirati tornano nella forma annidata del jsonb, e una chiave
  assente resta distinguibile da uno zero;
- `job_orario`, `leggi_memoria_riepilogo` e `scrivi_riepilogo_monitoraggio`
  non sollevano mai; senza la migrazione 12 non partono richieste; l'upsert
  scrive sempre `id=1` e mai `aggiornato_at`, che e' l'orologio del DB.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_db_salute
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

db = carica_modulo("db")
telemetria = carica_modulo("telemetria")

# 06:00 UTC = 08:00 a Roma.
ADESSO = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)

_SCRITTURE = ("insert", "update", "upsert", "delete", "rpc")
#: Nessuna risposta RPC prevista: una chiamata e' un errore del test.
_NESSUNA = object()


class _Risposta:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    """Query finta: registra le chiamate, restituisce righe e conteggio della tabella."""

    def __init__(self, client, tabella):
        self._client, self.tabella = client, tabella
        self.chiamate: list[tuple] = []
        client.query.append(self)

    @property
    def not_(self):
        self.chiamate.append(("not_",))
        return self

    def __getattr__(self, nome):
        if nome in _SCRITTURE and not self._client.scrive:
            raise AssertionError(f"lettura che scrive: {nome} su {self.tabella}")

        def _passo(*args, **kwargs):
            self.chiamate.append((nome, args, kwargs))
            return self
        return _passo

    def ha(self, nome, *args):
        return any(c[0] == nome and (not args or c[1] == args) for c in self.chiamate)

    def argomenti(self, nome):
        return next(c for c in self.chiamate if c[0] == nome)

    def execute(self):
        if self._client.errore is not None:
            raise self._client.errore
        righe, conto = self._client.risposte(self)
        return _Risposta(list(righe), conto)


class _Client:
    def __init__(self, righe=None, conti=None, *, scrive=False, errore=None, rpc=_NESSUNA):
        self._righe = righe or {}
        #: `[(tabella, filtri, conteggio)]`: il primo i cui filtri ci sono tutti.
        self._conti = conti or []
        self.scrive = scrive
        self.errore = errore
        self._rpc = rpc
        self.query: list[_Query] = []
        self.rpc_chiamate: list[tuple] = []

    def table(self, nome):
        return _Query(self, nome)

    def rpc(self, nome, parametri, **opzioni):
        if not self.scrive and self._rpc is _NESSUNA:
            raise AssertionError(f"rpc inattesa: {nome}")
        self.rpc_chiamate.append((nome, parametri, opzioni))
        esito = self._rpc

        class _Esegui:
            def execute(self_inner):
                if isinstance(esito, Exception):
                    raise esito
                return _Risposta(esito)
        return _Esegui()

    def risposte(self, query):
        """Righe per tabella; per le select con `count=exact` il conteggio per filtro."""
        conteggio = any(c[0] == "select" and c[2].get("count") == "exact" for c in query.chiamate)
        if conteggio:
            conto = next((v for tabella, filtri, v in self._conti if tabella == query.tabella
                          and all(query.ha(*f) for f in filtri)), None)
            return [], conto
        righe = self._righe.get(query.tabella, [])
        if callable(righe):
            righe = righe(query)
        return righe, None

    def su(self, tabella):
        return [q for q in self.query if q.tabella == tabella]


class _Strumento:
    """Schema finto: tabelle, colonne (vuoto = tutte) e RPC esposte."""

    def __init__(self, colonne=None, rpc=(), leggibile=True):
        self._colonne = colonne if colonne is not None else {
            "bando": set(), "pipeline_run": set(), "pipeline_lock": set(),
            "bando_controllo": set(), "bando_evento": set(),
        }
        self._rpc = set(rpc)
        self._leggibile = leggibile

    def schema_leggibile(self):
        return self._leggibile

    def tabella_esiste(self, nome):
        return nome in self._colonne

    def colonne(self, nome):
        return frozenset(self._colonne.get(nome, ()))

    def ha(self, tabella, colonna):
        presenti = self._colonne.get(tabella)
        return presenti is not None and (not presenti or colonna in presenti)

    def rpc_disponibile(self, nome):
        return nome in self._rpc


# --- contatori mirati --------------------------------------------------------

class ContatoriMirati(unittest.TestCase):
    def test_select_usa_la_freccia_json_e_un_alias_per_percorso(self):
        selezione = db._select_con_contatori(db.CONTATORI_PIPELINE)
        voci = selezione.split(",")
        for colonna in db.COLONNE_RIGA_RUN:
            self.assertIn(colonna, voci)
        for percorso in db.CONTATORI_PIPELINE:
            with self.subTest(percorso=percorso):
                self.assertIn(f"{db._alias_contatore(percorso)}:contatori->"
                              + "->".join(percorso), voci)
        # `->>` darebbe testo: le liste (`passi_non_ok`) arriverebbero come stringhe.
        self.assertNotIn("->>", selezione)
        alias = [db._alias_contatore(p) for p in db.CONTATORI_PIPELINE + db.CONTATORI_MONITOR]
        self.assertEqual(len(alias), len(set(alias)))
        # Nessun alias coincide con una colonna vera della riga.
        self.assertFalse(set(alias) & set(db.COLONNE_RIGA_RUN))

    def test_ricostruisce_la_forma_annidata_e_toglie_gli_assenti(self):
        riga = {"id": 141, "giro": "18:00", "esito": "ok",
                db._alias_contatore(("passi_non_ok",)): ["seo"],
                db._alias_contatore(("scrape", "fonti_errors")): 0,
                db._alias_contatore(("scrape", "fonti_processate")): 78,
                db._alias_contatore(("seo", "doppioni_oe")): None,
                db._alias_contatore(("enrich", "enriched_db_ok")): None}
        uscita = db._contatori_mirati(riga, db.CONTATORI_PIPELINE)
        self.assertEqual(uscita["id"], 141)
        self.assertEqual(uscita["contatori"], {
            "passi_non_ok": ["seo"],
            "scrape": {"fonti_errors": 0, "fonti_processate": 78},
        })
        # Lo zero resta, l'assente sparisce; nessun alias nella riga.
        self.assertNotIn("seo", uscita["contatori"])
        self.assertFalse(any(k.startswith("c_") for k in uscita))

    def test_i_percorsi_coprono_le_regole_del_percorso_b(self):
        """Le chiavi misurate da D1 per le regole di §8 (misure-giro-2-2026-10.md)."""
        attesi = {
            ("passi_non_ok",), ("riavvio_dopo_crash",),
            ("scrape", "fonti_errors"), ("scrape", "fonti_processate"),
            ("scrape", "fonti_in_errore"),
            ("preprocess", "errors"), ("preprocess", "processed_total"),
            ("enrich", "enriched_total"), ("enrich", "enriched_db_ok"),
            ("seo", "selected"), ("seo", "doppioni_oe"), ("seo", "payload_ok"),
        }
        self.assertLessEqual(attesi, set(db.CONTATORI_PIPELINE))
        self.assertLessEqual({("eventi_non_applicati",), ("eventi_non_scritti",),
                              ("classificazioni",), ("classificazioni_fallite",)},
                             set(db.CONTATORI_MONITOR))

    def test_i_contatori_di_sosta_e_fusione_della_seo(self):
        """Revisione del 01/10: chi la SEO tiene fuori dalla pubblicazione, e perche'."""
        import asyncio
        attesi = ("trattenuti", "trattenuti_senza_appiglio",
                  "fusi_prima_della_pubblicazione", "fusioni_non_riuscite")
        self.assertLessEqual({("seo", nome) for nome in attesi}, set(db.CONTATORI_PIPELINE))
        # Gli stessi nomi che `trattieni_e_fondi` scrive nei contatori dello step.
        runner = carica_modulo("bando_seo_runner")
        _, contatori = asyncio.run(runner.trattieni_e_fondi([]))
        for nome in attesi:
            with self.subTest(nome=nome):
                self.assertIn(nome, contatori)
        riga = {"id": 7, db._alias_contatore(("seo", "trattenuti")): 3,
                db._alias_contatore(("seo", "fusi_prima_della_pubblicazione")): 1}
        self.assertEqual(db._contatori_mirati(riga, db.CONTATORI_PIPELINE)["contatori"],
                         {"seo": {"trattenuti": 3, "fusi_prima_della_pubblicazione": 1}})


# --- misure_salute: le chiavi del giro 2 -------------------------------------

def _pipeline(query):
    if query.ha("eq", "step", "pipeline") and any(
            c[0] == "select" and "c_passi_non_ok" in c[1][0] for c in query.chiamate):
        return [{"id": 141, "giro": "18:00", "avviato_at": "2026-09-30T16:47:00+00:00",
                 "concluso_at": "2026-09-30T16:52:00+00:00", "esito": "ok",
                 "interrotto_per_tetto": False,
                 "c_passi_non_ok": ["seo"], "c_preprocess__errors": 25,
                 "c_preprocess__processed_total": 25, "c_riavvio_dopo_crash": None}]
    if query.ha("eq", "step", "monitor") and any(
            c[0] == "select" and "c_eventi_non_scritti" in c[1][0] for c in query.chiamate):
        return [{"id": 138, "giro": "18:00", "esito": "ok",
                 "c_eventi_non_applicati": None, "c_eventi_non_scritti": 2}]
    return []


class MisureDelGiro2(unittest.TestCase):
    CONTI = [
        ("bando", (("in_", "stato_processing", ["processed", "enriched"]),), 3),
        ("bando_evento", (("gte",),), 11),
        ("bando_evento", (("eq", "verificato", True), ("eq", "applicato", False)), 4),
        ("bando_evento", (("eq", "applicato", True), ("eq", "leggibile", False)), 2),
    ]

    def _misure(self, client=None, strumento=None):
        client = client or _Client(
            {"pipeline_run": _pipeline,
             "bando": lambda q: ([{"created_at": "2026-09-30T16:49:12+00:00"}]
                                 if q.ha("select", "created_at") else [])},
            self.CONTI)
        return client, db.misure_salute(adesso=ADESSO, client=client,
                                        strumento=strumento or _Strumento())

    def test_legge_e_basta(self):
        client, misure = self._misure()
        self.assertTrue(client.query)
        self.assertEqual(client.rpc_chiamate, [])
        self.assertNotIn("job_orario", misure)

    def test_ultime_pipeline_con_i_contatori_mirati(self):
        client, misure = self._misure()
        query = next(q for q in client.su("pipeline_run")
                     if q.ha("eq", "step", "pipeline")
                     and "c_passi_non_ok" in q.argomenti("select")[1][0])
        self.assertEqual(query.argomenti("limit")[1], (db.RIGHE_ULTIME_PIPELINE,))
        self.assertEqual(db.RIGHE_ULTIME_PIPELINE, 20)
        ordini = [c for c in query.chiamate if c[0] == "order"]
        self.assertEqual(ordini, [("order", ("avviato_at",), {"desc": True}),
                                  ("order", ("id",), {"desc": True})])
        # Nessun filtro su `giro`: servono anche le righe di boot e quelle saltate.
        self.assertFalse(query.ha("is_"))
        self.assertEqual(misure["ultime_pipeline"], [{
            "id": 141, "giro": "18:00", "avviato_at": "2026-09-30T16:47:00+00:00",
            "concluso_at": "2026-09-30T16:52:00+00:00", "esito": "ok",
            "interrotto_per_tetto": False,
            "contatori": {"passi_non_ok": ["seo"],
                          "preprocess": {"errors": 25, "processed_total": 25}},
        }])

    def test_ultimi_monitor_di_regime(self):
        client, misure = self._misure()
        query = next(q for q in client.su("pipeline_run")
                     if q.ha("eq", "step", "monitor")
                     and "c_eventi_non_scritti" in q.argomenti("select")[1][0])
        self.assertTrue(query.ha("not_"))
        self.assertTrue(query.ha("is_", "giro", "null"))
        self.assertEqual(query.argomenti("limit")[1], (db.RIGHE_ULTIMI_MONITOR,))
        self.assertEqual(misure["ultimi_monitor"], [
            {"id": 138, "giro": "18:00", "esito": "ok",
             "contatori": {"eventi_non_scritti": 2}}])

    def test_fermi_in_lavorazione_contati_dal_server(self):
        client, misure = self._misure()
        self.assertEqual(misure["fermi_in_lavorazione"], 3)
        query = next(q for q in client.su("bando")
                     if q.ha("in_", "stato_processing", ["processed", "enriched"]))
        self.assertEqual(query.argomenti("select"), ("select", ("id",), {"count": "exact"}))
        self.assertEqual(query.argomenti("in_")[1], ("stato_processing", ["processed", "enriched"]))
        # 13 ore prima delle 08:00 di Roma: le 19:00 del giorno prima, ora di Roma.
        self.assertEqual(telemetria.ORE_SCRAPED_FERMO, 13)
        self.assertEqual(query.argomenti("lt")[1], ("created_at", "2026-09-30T19:00:00+02:00"))
        self.assertEqual(query.argomenti("limit")[1], (1,))

    def test_ultimo_bando_nuovo_senza_i_null(self):
        client, misure = self._misure()
        self.assertEqual(misure["ultimo_bando_nuovo_at"], "2026-09-30T16:49:12+00:00")
        query = next(q for q in client.su("bando") if q.ha("select", "created_at"))
        self.assertTrue(query.ha("not_"))
        self.assertTrue(query.ha("is_", "created_at", "null"))
        self.assertIn(("order", ("created_at",), {"desc": True}), query.chiamate)

    def test_conteggi_degli_eventi(self):
        client, misure = self._misure()
        self.assertEqual(misure["proposte_7g"], 11)
        self.assertEqual(misure["ammessi_non_applicati"], 4)
        self.assertEqual(misure["in_attesa_pubblicazione"], 2)
        eventi = client.su("bando_evento")
        self.assertEqual(len(eventi), 3)
        for query in eventi:
            self.assertEqual(query.argomenti("select"), ("select", ("id",), {"count": "exact"}))
        proposte = next(q for q in eventi if q.ha("gte"))
        self.assertEqual(proposte.argomenti("gte")[1], ("rilevato_at", "2026-09-24T08:00:00+02:00"))

    def test_senza_ultimo_bando_vale_none(self):
        client = _Client({"pipeline_run": _pipeline}, self.CONTI)
        _, misure = self._misure(client=client)
        self.assertIsNone(misure["ultimo_bando_nuovo_at"])

    def test_colonne_assenti_valgono_none(self):
        strumento = _Strumento({
            "bando": {"id", "stato_processing"},
            "bando_evento": {"id", "applicato"},
        })
        client, misure = self._misure(strumento=strumento)
        for chiave in ("ultime_pipeline", "ultimi_monitor", "fermi_in_lavorazione",
                       "ultimo_bando_nuovo_at", "proposte_7g", "ammessi_non_applicati",
                       "in_attesa_pubblicazione"):
            with self.subTest(chiave=chiave):
                self.assertIsNone(misure[chiave])
        self.assertEqual(client.su("bando_evento"), [])

    def test_conteggio_mancante_non_e_zero(self):
        client = _Client({"pipeline_run": _pipeline}, conti=[])
        _, misure = self._misure(client=client)
        self.assertIsNone(misure["fermi_in_lavorazione"])
        self.assertIsNone(misure["proposte_7g"])

    def test_errore_di_rete_si_solleva(self):
        """Come le misure di oggi: «non so» non deve sembrare «tutto bene»."""
        with self.assertRaises(ConnectionError):
            self._misure(client=_Client(errore=ConnectionError("giu'")))


# --- job orario --------------------------------------------------------------

class JobOrario(unittest.TestCase):
    STRUMENTO = _Strumento(rpc={db.RPC_JOB_ORARIO})

    def test_senza_la_12_nessuna_chiamata(self):
        client = _Client()
        self.assertIsNone(db.job_orario(client=client, strumento=_Strumento()))
        self.assertEqual(client.rpc_chiamate, [])

    def test_restituisce_l_oggetto(self):
        dati = {"misurato": True, "ultimo_esito": "succeeded", "falliti_24h": 0}
        client = _Client(rpc=dati)
        self.assertEqual(db.job_orario(client=client, strumento=self.STRUMENTO), dati)
        # In GET: dal Mac `salute` e `sorveglia --dry-run` fanno solo GET (§1).
        self.assertEqual(client.rpc_chiamate, [(db.RPC_JOB_ORARIO, {}, {"get": True})])
        client = _Client(rpc=[dati])
        self.assertEqual(db.job_orario(client=client, strumento=self.STRUMENTO), dati)

    def test_errore_o_forma_strana_valgono_none(self):
        for esito in (RuntimeError("42501"), "succeeded", [], [1, 2], None):
            with self.subTest(esito=esito):
                self.assertIsNone(db.job_orario(client=_Client(rpc=esito),
                                                strumento=self.STRUMENTO))


# --- riga del riepilogo --------------------------------------------------------

class RigaDelRiepilogo(unittest.TestCase):
    STRUMENTO = _Strumento({db.TABELLA_RIEPILOGO: set()})

    def test_riepilogo_disponibile(self):
        """Tre risposte: la tabella c'e', manca (12 non applicata), non si sa (schema illeggibile).

        `sorveglia` esce 0 solo col `False`: un DB giu' non deve sembrare una
        migrazione mancante.
        """
        self.assertIs(db.riepilogo_disponibile(strumento=self.STRUMENTO), True)
        self.assertIs(db.riepilogo_disponibile(strumento=_Strumento({"bando": set()})), False)
        self.assertIsNone(db.riepilogo_disponibile(
            strumento=_Strumento({db.TABELLA_RIEPILOGO: set()}, leggibile=False)))

    def test_schema_leggibile_sul_controllo_vero(self):
        """`Controllo.schema_leggibile`: falso quando lo schema ha degradato a `{}`."""
        def giu():
            raise ConnectionError("DB giu'")

        definizioni = {"definitions": {db.TABELLA_RIEPILOGO: {"properties": {"id": {}}}}}
        componenti = {"components": {"schemas": {"bando": {"properties": {"id": {}}}}}}
        casi = [(giu, False, None), (lambda: {}, False, None),
                (lambda: definizioni, True, True), (lambda: componenti, True, False)]
        for fornitore, leggibile, disponibile in casi:
            controllo = db.Controllo(fornitore_schema=fornitore)
            with self.subTest(leggibile=leggibile, disponibile=disponibile), \
                    patch.object(db, "logger", MagicMock()):
                self.assertIs(controllo.schema_leggibile(), leggibile)
                self.assertIs(db.riepilogo_disponibile(strumento=controllo), disponibile)

    def test_colonne_del_contratto_senza_aggiornato_at(self):
        """§2.1: `aggiornato_at` lo scrive solo il trigger, con l'orologio del DB."""
        self.assertEqual(set(db.COLONNE_RIEPILOGO),
                         {"id", "calcolato_at", "intervallo_ritardo", "versione",
                          "riepilogo", "memoria"})
        self.assertNotIn("aggiornato_at", db.COLONNE_RIEPILOGO)

    def test_memoria_letta_dalla_riga_unica(self):
        memoria = {"nrestarts": [["2026-10-01T05:50:00+00:00", 3]], "dal": {}}
        client = _Client({db.TABELLA_RIEPILOGO: [{"memoria": memoria}]})
        self.assertEqual(db.leggi_memoria_riepilogo(client=client, strumento=self.STRUMENTO),
                         memoria)
        query = client.su(db.TABELLA_RIEPILOGO)[0]
        # Solo la memoria: il riepilogo non serve a chi lo riscrive.
        self.assertEqual(query.argomenti("select")[1], ("memoria",))
        self.assertTrue(query.ha("eq", "id", 1))

    def test_memoria_assente_o_illeggibile(self):
        # Primo giro: riga assente → memoria vuota.
        self.assertEqual(db.leggi_memoria_riepilogo(
            client=_Client({db.TABELLA_RIEPILOGO: []}), strumento=self.STRUMENTO), {})
        self.assertEqual(db.leggi_memoria_riepilogo(
            client=_Client({db.TABELLA_RIEPILOGO: [{"memoria": "rotta"}]}),
            strumento=self.STRUMENTO), {})
        # Senza la 12 o con la rete giu': None, senza sollevare.
        client = _Client()
        self.assertIsNone(db.leggi_memoria_riepilogo(client=client, strumento=_Strumento()))
        self.assertEqual(client.query, [])
        self.assertIsNone(db.leggi_memoria_riepilogo(
            client=_Client(errore=ConnectionError("giu'")), strumento=self.STRUMENTO))

    def test_upsert_della_riga_unica(self):
        client = _Client(scrive=True)
        riga = {"id": 7, "calcolato_at": "2026-10-01T06:05:00+00:00",
                "intervallo_ritardo": "45 minutes", "versione": 1,
                "riepilogo": {"versione": 1}, "memoria": {"dal": {}},
                "aggiornato_at": "2020-01-01T00:00:00+00:00", "estranea": "x"}
        self.assertTrue(db.scrivi_riepilogo_monitoraggio(
            riga, client=client, strumento=self.STRUMENTO))
        query = client.su(db.TABELLA_RIEPILOGO)[0]
        _, (scritta,), opzioni = query.argomenti("upsert")
        self.assertEqual(opzioni, {"on_conflict": "id"})
        self.assertEqual(scritta["id"], 1)
        self.assertEqual(set(scritta), set(db.COLONNE_RIEPILOGO))
        self.assertEqual(scritta["intervallo_ritardo"], "45 minutes")

    def test_solo_le_colonne_esposte(self):
        client = _Client(scrive=True)
        strumento = _Strumento({db.TABELLA_RIEPILOGO: {"id", "calcolato_at", "versione",
                                                      "riepilogo"}})
        db.scrivi_riepilogo_monitoraggio(
            {"calcolato_at": "x", "versione": 1, "riepilogo": {}, "memoria": {}},
            client=client, strumento=strumento)
        _, (scritta,), _ = client.su(db.TABELLA_RIEPILOGO)[0].argomenti("upsert")
        self.assertEqual(set(scritta), {"id", "calcolato_at", "versione", "riepilogo"})

    def test_senza_la_12_warning_e_nessuna_richiesta(self):
        client = _Client(scrive=True)
        finto = MagicMock()
        with patch.object(db, "logger", finto):
            esito = db.scrivi_riepilogo_monitoraggio(
                {"versione": 1}, client=client, strumento=_Strumento())
        self.assertIs(esito, False)
        self.assertEqual(client.query, [])
        finto.warning.assert_called_once()

    def test_upsert_fallito_non_solleva(self):
        client = _Client(scrive=True, errore=RuntimeError("23514"))
        self.assertIs(db.scrivi_riepilogo_monitoraggio(
            {"versione": 1}, client=client, strumento=self.STRUMENTO), False)


if __name__ == "__main__":
    unittest.main()
