# -*- coding: utf-8 -*-
"""Letture e scritture del percorso A in `db.py` (contratto `bandi-giro-2` §14, §19.13).

Cosa si prova, senza rete (client finto che registra ogni chiamata):

- le letture del passo verifica-stato scorrono oltre le 1 000 righe, non
  scrivono e sollevano su un errore di rete (una lettura vuota vorrebbe dire
  «mai letto» e farebbe perdere la storia delle letture);
- le scritture della 13 scartano le colonne che lo schema non ha e danno
  `False` invece di un'eccezione;
- `aggiorna_ingresso` non tocca mai una riga pubblicata;
- `inserisci_domini_nuovi` manda solo `INSERT ... ON CONFLICT DO NOTHING`
  (upsert con `ignore_duplicates`), mai un UPDATE o una DELETE;
- le misure nuove di `misure_salute`: la finestra dei fermi in lavorazione,
  l'arretrato, le proposte senza i tipi di servizio, il tempo della vista.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_db_verifica_stato
"""
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

db = carica_modulo("db")

# 06:00 UTC = 08:00 a Roma.
ADESSO = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)

_SCRITTURE = ("insert", "update", "upsert", "delete")


class _Risposta:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    def __init__(self, client, tabella):
        self._client, self.tabella = client, tabella
        self.chiamate: list[tuple] = []
        client.query.append(self)

    @property
    def not_(self):
        self.chiamate.append(("not_",))
        return self

    def __getattr__(self, nome):
        if nome in _SCRITTURE and nome not in self._client.scritture_ammesse:
            raise AssertionError(f"scrittura inattesa: {nome} su {self.tabella}")

        def _passo(*args, **kwargs):
            self.chiamate.append((nome, args, kwargs))
            return self
        return _passo

    def ha(self, nome, *args):
        return any(c[0] == nome and (not args or c[1] == args) for c in self.chiamate)

    def argomenti(self, nome):
        return next(c for c in self.chiamate if c[0] == nome)

    def scrittura(self):
        return next((c for c in self.chiamate if c[0] in _SCRITTURE), None)

    def execute(self):
        errore = self._client.errori.get(self.tabella)
        if errore is not None:
            raise errore
        if any(c[0] == "select" and c[2].get("count") == "exact" for c in self.chiamate):
            return _Risposta([], self._client.conto(self))
        risposta = self._client.risposte.get(self.tabella, [])
        righe = list(risposta(self) if callable(risposta) else risposta)
        if self.scrittura() is None:
            intervallo = next((c[1] for c in self.chiamate if c[0] == "range"), None)
            limite = next((c[1][0] for c in self.chiamate if c[0] == "limit"), None)
            if intervallo is not None:
                righe = righe[intervallo[0]:intervallo[1] + 1]
            elif limite is not None:
                righe = righe[:limite]
        return _Risposta(righe)


class _Client:
    def __init__(self, risposte=None, *, scritture=(), errori=None, conti=None):
        self.risposte = risposte or {}
        self.scritture_ammesse = set(scritture)
        self.errori = errori or {}
        self._conti = conti or []
        self.query: list[_Query] = []

    def table(self, nome):
        return _Query(self, nome)

    def rpc(self, *args, **kwargs):
        raise AssertionError("nessuna rpc nel percorso A di db.py")

    def conto(self, query):
        return next((v for tabella, filtri, v in self._conti if tabella == query.tabella
                     and all(query.ha(*f) for f in filtri)), None)

    def su(self, tabella):
        return [q for q in self.query if q.tabella == tabella]


class _Strumento:
    """Schema finto: `colonne=None` vuol dire «tutte» per le tabelle elencate."""

    def __init__(self, tabelle=None):
        self._tabelle = tabelle if tabelle is not None else {
            "bando": set(), "bando_controllo": set(), "fonte": set(),
            "dominio_ufficiale": set(), "bando_evento": set(), "pipeline_run": set(),
            "pipeline_lock": set(), "bando_pubblico": set(),
        }
        # Con la 13: le colonne nuove di `bando_controllo` ci sono.
        if "bando_controllo" in self._tabelle and not self._tabelle["bando_controllo"]:
            self._tabelle["bando_controllo"] = {
                "bando_id", "candidato_prioritario", "controlli_falliti", *db.COLONNE_LETTURA_STATO}

    def tabella_esiste(self, nome):
        return nome in self._tabelle

    def colonne(self, nome):
        return frozenset(self._tabelle.get(nome, ()))

    def ha(self, tabella, colonna):
        presenti = self._tabelle.get(tabella)
        return presenti is not None and (not presenti or colonna in presenti)


SENZA_LA_13 = {"bando": set(), "fonte": set(),
               "bando_controllo": {"bando_id", "controlli_falliti", "prossimo_controllo_at"}}


def _bandi(quanti, **extra):
    return [{"id": i, "fonte_id": 237 if i % 2 else 280, "stato_bando": "aperto", **extra}
            for i in range(1, quanti + 1)]


FONTI = [{"id": 237, "link": "https://www.lazioeuropa.it/bandi/"},
         {"id": 280, "link": "https://new.regione.vda.it/calendario"}]


class Colonne(unittest.TestCase):
    def test_diciassette_colonne_della_13(self):
        self.assertEqual(len(db.COLONNE_LETTURA_STATO), 17)
        self.assertEqual(len(set(db.COLONNE_LETTURA_STATO)), 17)
        for colonna in ("esaminato_attivo_at", "termine_indicato_fonte", "segnale_aggregatore",
                        "segnale_aggregatore_at", "trattenuto_dal", "stato_letto", "lettura_stato"):
            self.assertIn(colonna, db.COLONNE_LETTURA_STATO)


class SelectDaVerificare(unittest.TestCase):
    def test_scorre_oltre_mille_e_porta_l_host_della_fonte(self):
        client = _Client({"bando": _bandi(1500), "fonte": FONTI})
        righe = db.select_da_verificare(client=client, strumento=_Strumento())
        self.assertEqual(len(righe), 1500)
        self.assertEqual(righe[0]["host_fonte"], "lazioeuropa.it")
        self.assertEqual(righe[1]["host_fonte"], "new.regione.vda.it")
        lettura = client.su("bando")[0]
        self.assertTrue(lettura.ha("eq", "pubblicato", True))
        self.assertTrue(lettura.ha("is_", "bando_master_id", "null"))
        self.assertEqual(lettura.argomenti("or_")[1], (
            'stato_bando.eq."in apertura prossimamente",'
            "and(stato_bando.eq.aperto,data_scadenza.is.null)",))
        self.assertIn(("order", ("id",), {}), lettura.chiamate)
        # Nessun filtro sulla fonte ufficiale (§5.2).
        self.assertFalse(any("fonte_ufficiale_stato" in str(c[1]) for c in lettura.chiamate
                             if c[0] != "select"))
        self.assertEqual(len(client.su("bando")), 2)

    def test_colonne_per_g5_e_data_verificata(self):
        client = _Client({"bando": _bandi(3), "fonte": FONTI})
        db.select_da_verificare(client=client, strumento=_Strumento())
        colonne = client.su("bando")[0].argomenti("select")[1][0].split(",")
        for colonna in ("data_scadenza_verificata", "data_pubblicazione",
                        "data_apertura_verificata"):
            self.assertIn(colonna, colonne)
        # Anche la fase ingresso legge le stesse colonne.
        client = _Client({"bando": [], "fonte": FONTI})
        db.select_enriched_da_leggere(client=client, strumento=_Strumento())
        self.assertIn("data_scadenza_verificata",
                      client.su("bando")[0].argomenti("select")[1][0].split(","))

    def test_errore_di_rete_solleva(self):
        client = _Client(errori={"bando": ConnectionError("giu'")})
        with self.assertRaises(ConnectionError):
            db.select_da_verificare(client=client, strumento=_Strumento())

    def test_senza_tabella(self):
        self.assertEqual(db.select_da_verificare(client=_Client(), strumento=_Strumento({})), [])


class SelectLettureStato(unittest.TestCase):
    RIGHE = [{"bando_id": i, "lettura_stato": {"esito": "letta"}} for i in range(1, 1201)]

    def test_per_ids(self):
        client = _Client({"bando_controllo": lambda q: [
            r for r in self.RIGHE if r["bando_id"] in q.argomenti("in_")[1][1]]})
        letture = db.select_letture_stato([3, 5, 7], client=client, strumento=_Strumento())
        self.assertEqual(sorted(letture), [3, 5, 7])
        query = client.su("bando_controllo")[0]
        self.assertEqual(query.argomenti("in_")[1][0], "bando_id")
        colonne = query.argomenti("select")[1][0].split(",")
        self.assertIn("candidato_prioritario", colonne)
        self.assertIn("trattenuto_dal", colonne)

    def test_dal_e_tutte_scorrono(self):
        client = _Client({"bando_controllo": self.RIGHE})
        letture = db.select_letture_stato(dal=ADESSO, client=client, strumento=_Strumento())
        self.assertEqual(len(letture), 1200)
        self.assertEqual(client.su("bando_controllo")[0].argomenti("gte")[1],
                         ("lettura_stato_at", ADESSO.isoformat()))
        client = _Client({"bando_controllo": self.RIGHE})
        db.select_letture_stato(client=client, strumento=_Strumento())
        self.assertTrue(client.su("bando_controllo")[0].ha("is_", "lettura_stato_at", "null"))

    def test_senza_la_13_nessuna_lettura(self):
        client = _Client()
        self.assertEqual(db.select_letture_stato(client=client, strumento=_Strumento(SENZA_LA_13)), {})
        self.assertEqual(client.query, [])

    def test_errore_di_rete_solleva(self):
        with self.assertRaises(ConnectionError):
            db.select_letture_stato(client=_Client(errori={"bando_controllo": ConnectionError()}),
                                    strumento=_Strumento())


class AggiornaLetturaStato(unittest.TestCase):
    def test_solo_le_colonne_della_13(self):
        client = _Client(scritture={"upsert"})
        esito = db.aggiorna_lettura_stato(
            7, {"lettura_stato": {"esito": "letta"}, "termine_indicato": "2026-12-31",
                "termine_indicato_fonte": "pagina", "prossimo_controllo_at": "x", "testo_norm": "y"},
            client=client, strumento=_Strumento())
        self.assertTrue(esito)
        _, (riga,), opzioni = client.su("bando_controllo")[0].scrittura()
        self.assertEqual(opzioni, {"on_conflict": "bando_id"})
        self.assertEqual(set(riga), {"bando_id", "lettura_stato", "termine_indicato",
                                     "termine_indicato_fonte"})

    def test_senza_la_13_false_senza_richieste(self):
        client = _Client(scritture={"upsert"})
        self.assertIs(db.aggiorna_lettura_stato(
            7, {"lettura_stato": {}}, client=client, strumento=_Strumento(SENZA_LA_13)), False)
        self.assertEqual(client.query, [])

    def test_check_rifiutato_false_senza_eccezione(self):
        client = _Client(scritture={"upsert"}, errori={"bando_controllo": RuntimeError("23514")})
        self.assertIs(db.aggiorna_lettura_stato(
            7, {"termine_indicato": "2026-12-31"}, client=client, strumento=_Strumento()), False)


class SelectEnrichedDaLeggere(unittest.TestCase):
    def test_aperti_senza_scadenza_e_status_due_uniti(self):
        def bando(query):
            if query.ha("eq", "raw_data->>status", "2"):
                return [{"id": 5, "fonte_id": 449}, {"id": 9, "fonte_id": 449}]
            return [{"id": 9, "fonte_id": 449}, {"id": 2, "fonte_id": 237}]
        client = _Client({"bando": bando, "fonte": FONTI})
        righe = db.select_enriched_da_leggere(client=client, strumento=_Strumento())
        self.assertEqual([r["id"] for r in righe], [2, 5, 9])
        letture = client.su("bando")
        for query in letture:
            self.assertTrue(query.ha("eq", "stato_processing", "enriched"))
            self.assertTrue(query.ha("eq", "pubblicato", False))
        aperti = next(q for q in letture if q.ha("eq", "stato_bando", "aperto"))
        self.assertTrue(aperti.ha("is_", "data_scadenza", "null"))


class AggiornaIngresso(unittest.TestCase):
    def _client(self, riga, *, aggiornate=None):
        def bando(query):
            if query.scrittura() is not None:
                return [riga] if aggiornate is None else aggiornate
            return [riga] if riga else []
        return _Client({"bando": bando}, scritture={"update", "upsert"})

    def test_una_riga_pubblicata_non_si_tocca(self):
        for riga in ({"id": 1, "pubblicato": True, "stato_processing": "completed"},
                     {"id": 1, "pubblicato": False, "stato_processing": "completed"}):
            with self.subTest(riga=riga):
                client = self._client(riga)
                esito = db.aggiorna_ingresso(1, {"data_scadenza": "2026-12-31"},
                                             {"trattenuto_dal": "2026-10-01"},
                                             client=client, strumento=_Strumento())
                self.assertEqual(esito, {"bando": False, "controllo": False, "rifiutato": "pubblicato"})
                self.assertTrue(all(q.scrittura() is None for q in client.query))

    def test_solo_scadenza_ora_e_chiuso(self):
        client = self._client({"id": 1, "pubblicato": False, "stato_processing": "enriched"})
        esito = db.aggiorna_ingresso(
            1,
            {"data_scadenza": "2026-12-31", "ora_scadenza": "12:00", "stato_bando": "chiuso",
             "data_scadenza_verificata": True, "titolo": "x"},
            {"lettura_stato": {"storia": []}, "trattenuto_dal": "2026-10-01T06:00:00+00:00"},
            client=client, strumento=_Strumento())
        self.assertEqual(esito, {"bando": True, "controllo": True, "rifiutato": None})
        aggiornamento = next(q for q in client.su("bando") if q.scrittura())
        _, (payload,), _ = aggiornamento.scrittura()
        self.assertEqual(payload, {"data_scadenza": "2026-12-31", "ora_scadenza": "12:00",
                                   "stato_bando": "chiuso"})
        # Il filtro sulla riga non pubblicata sta anche nell'UPDATE.
        self.assertTrue(aggiornamento.ha("eq", "pubblicato", False))
        self.assertTrue(aggiornamento.ha("eq", "id", 1))

    def test_nessuno_stato_diverso_da_chiuso(self):
        client = self._client({"id": 1, "pubblicato": False, "stato_processing": "enriched"})
        esito = db.aggiorna_ingresso(1, {"stato_bando": "aperto"}, None,
                                     client=client, strumento=_Strumento())
        self.assertEqual(esito["bando"], False)
        self.assertTrue(all(q.scrittura() is None for q in client.query))

    def test_pubblicata_nel_frattempo(self):
        client = self._client({"id": 1, "pubblicato": False, "stato_processing": "enriched"},
                              aggiornate=[])
        esito = db.aggiorna_ingresso(1, {"data_scadenza": "2026-12-31"},
                                     {"trattenuto_dal": "2026-10-01"},
                                     client=client, strumento=_Strumento())
        self.assertEqual(esito["rifiutato"], "pubblicato")
        self.assertEqual(client.su("bando_controllo"), [])

    def test_lettura_fallita_nessuna_scrittura(self):
        client = _Client(errori={"bando": ConnectionError()}, scritture={"update", "upsert"})
        esito = db.aggiorna_ingresso(1, {"data_scadenza": "2026-12-31"}, None,
                                     client=client, strumento=_Strumento())
        self.assertEqual(esito["rifiutato"], "lettura_fallita")


class DominiUfficiali(unittest.TestCase):
    def test_scorre_per_id(self):
        righe = [{"id": i, "host": f"ente{i}.it"} for i in range(1, 2501)]
        client = _Client({"dominio_ufficiale": righe})
        self.assertEqual(len(db.select_domini_ufficiali(client=client, strumento=_Strumento())), 2500)
        self.assertIn(("order", ("id",), {}), client.su("dominio_ufficiale")[0].chiamate)

    def test_errore_vale_lista_vuota(self):
        client = _Client(errori={"dominio_ufficiale": ConnectionError()})
        self.assertEqual(db.select_domini_ufficiali(client=client, strumento=_Strumento()), [])

    def test_host_dei_link(self):
        client = _Client({"bando": [
            {"id": 1, "link_bando": "https://www.lazioeuropa.it/bandi/a", "fonte_ufficiale_url": None},
            {"id": 2, "link_bando": "https://obiettivoeuropa.com/b",
             "fonte_ufficiale_url": "https://lazioeuropa.it/bandi/b"},
        ]})
        self.assertEqual(db.select_host_dei_link(client=client, strumento=_Strumento()),
                         ["lazioeuropa.it", "obiettivoeuropa.com"])


class HostDeiLinkConBandoLink(unittest.TestCase):
    def test_anche_gli_host_di_bando_link(self):
        """I 51 host che l'import rende verificanti vengono da `bando_link` (M10)."""
        client = _Client({
            "bando": [{"id": 1, "link_bando": "https://obiettivoeuropa.com/b",
                       "fonte_ufficiale_url": None}],
            "bando_link": lambda q: [{"id": 7, "bando_id": 1, "url": "https://www.comune.esempio.it/avviso"}]
            if q.argomenti("in_")[1] == ("bando_id", [1]) else [],
        })
        strumento = _Strumento({"bando": set(), "bando_link": {"id", "bando_id", "url"}})
        self.assertEqual(db.select_host_dei_link(client=client, strumento=strumento),
                         ["comune.esempio.it", "obiettivoeuropa.com"])


class UltimiImportIndicePA(unittest.TestCase):
    def test_righe_dello_step_domini_con_i_contatori(self):
        def pipeline_run(query):
            if query.ha("eq", "step", "domini"):
                return [{"id": 300, "avviato_at": "2026-10-01T04:00:00+00:00", "esito": "ok",
                         "c_indicepa_esito": "ok", "c_indicepa_righe_utili": 22891,
                         "c_indicepa_esclusi": {"host_condiviso": 59}, "c_indicepa_inseriti": None}]
            return []
        client = _Client({"pipeline_run": pipeline_run})
        misure = db.misure_salute(adesso=ADESSO, client=client, strumento=_Strumento())
        (riga,) = misure["ultimi_import_indicepa"]
        self.assertEqual(riga["contatori"], {"indicepa_esito": "ok", "indicepa_righe_utili": 22891,
                                             "indicepa_esclusi": {"host_condiviso": 59}})
        query = next(q for q in client.su("pipeline_run") if q.ha("eq", "step", "domini"))
        self.assertEqual(query.argomenti("limit")[1], (3,))
        self.assertEqual(db.STEP_DOMINI, carica_modulo("fonte_ufficiale").STEP_DOMINI)


class SegnaleAggregatore(unittest.TestCase):
    def test_solo_le_tre_chiavi_a_blocchi(self):
        client = _Client(scritture={"upsert"})
        righe = [{"bando_id": i, "segnale_aggregatore": "in_uscita",
                  "segnale_aggregatore_at": "2026-10-01T06:00:00+00:00", "extra": 1}
                 for i in range(1, 251)] + [{"bando_id": 999, "segnale_aggregatore": None,
                                             "segnale_aggregatore_at": None}]
        self.assertEqual(db.aggiorna_segnale_aggregatore(righe, client=client,
                                                         strumento=_Strumento()), 251)
        blocchi = [q.scrittura() for q in client.su("bando_controllo")]
        self.assertEqual([len(b[1][0]) for b in blocchi], [200, 51])
        for _nome, (blocco,), opzioni in blocchi:
            self.assertEqual(opzioni, {"on_conflict": "bando_id"})
            for riga in blocco:
                self.assertEqual(set(riga), {"bando_id", "segnale_aggregatore",
                                             "segnale_aggregatore_at"})
        self.assertIsNone(blocchi[-1][1][0][-1]["segnale_aggregatore"])

    def test_senza_la_13(self):
        client = _Client(scritture={"upsert"})
        self.assertEqual(db.aggiorna_segnale_aggregatore(
            [{"bando_id": 1, "segnale_aggregatore": "in_uscita"}],
            client=client, strumento=_Strumento(SENZA_LA_13)), 0)
        self.assertEqual(client.query, [])


class InserisciDominiNuovi(unittest.TestCase):
    ESISTENTI = [{"id": 1, "host": "regione.lazio.it"}, {"id": 2, "host": "lazioeuropa.it"}]

    def _client(self, **opzioni):
        def domini(query):
            scrittura = query.scrittura()
            if scrittura is None:
                return self.ESISTENTI
            return scrittura[1][0]                    # ON CONFLICT DO NOTHING: tornano le inserite
        return _Client({"dominio_ufficiale": domini}, scritture={"upsert"}, **opzioni)

    def test_solo_host_assenti_e_solo_insert_senza_conflitti(self):
        client = self._client()
        righe = ([{"host": "regione.lazio.it", "tipo": "ente"},
                  {"host": "Comune.Roma.it", "tipo": "ente", "id": 77},
                  {"host": "comune.roma.it", "tipo": "ente"},
                  {"host": "", "tipo": "ente"}]
                 + [{"host": f"ente{i}.it", "tipo": "ente", "origine": "indicepa"}
                    for i in range(1, 1101)])
        esito = db.inserisci_domini_nuovi(righe, lotto=500, client=client, strumento=_Strumento())
        self.assertEqual(esito, {"lette": 1104, "gia_presenti": 1, "scartate": 1,
                                 "inserite": 1101, "lotti_falliti": 0, "errore": None})
        scritture = [q.scrittura() for q in client.su("dominio_ufficiale") if q.scrittura()]
        # La riga senza `origine` va in un lotto suo: chiavi uniformi per lotto.
        self.assertEqual([len(s[1][0]) for s in scritture], [1, 500, 500, 100])
        for nome, (lotto,), opzioni in scritture:
            self.assertEqual(nome, "upsert")
            self.assertEqual(opzioni, {"on_conflict": "host", "ignore_duplicates": True})
            self.assertTrue(all("id" not in r for r in lotto))
            self.assertEqual(len({tuple(sorted(r)) for r in lotto}), 1)
        self.assertEqual(scritture[0][1][0][0]["host"], "comune.roma.it")

    def test_chiavi_uniformi_per_lotto(self):
        """postgrest-py manda `columns=` con l'unione: una chiave mancante diventerebbe NULL."""
        client = self._client()
        righe = [{"host": "a.it", "tipo": "ente", "attivo": True},
                 {"host": "b.it", "tipo": "ente"},
                 {"host": "c.it", "tipo": "ente", "attivo": True}]
        esito = db.inserisci_domini_nuovi(righe, client=client, strumento=_Strumento())
        self.assertEqual(esito["inserite"], 3)
        lotti = [q.scrittura()[1][0] for q in client.su("dominio_ufficiale") if q.scrittura()]
        self.assertEqual(sorted(sorted(r["host"] for r in lotto) for lotto in lotti),
                         [["a.it", "c.it"], ["b.it"]])
        for lotto in lotti:
            self.assertEqual(len({tuple(sorted(r)) for r in lotto}), 1)

    def test_lettura_fallita_nessuna_scrittura(self):
        client = _Client(errori={"dominio_ufficiale": ConnectionError()}, scritture={"upsert"})
        esito = db.inserisci_domini_nuovi([{"host": "ente.it"}], client=client, strumento=_Strumento())
        self.assertEqual((esito["errore"], esito["inserite"]), ("lettura_fallita", 0))

    def test_lotto_fallito_contato(self):
        class _Rotto(_Client):
            def table(self_inner, nome):
                query = super().table(nome)
                originale = query.execute

                def execute():
                    if query.scrittura() is not None:
                        raise RuntimeError("timeout")
                    return originale()
                query.execute = execute
                return query
        client = _Rotto({"dominio_ufficiale": self.ESISTENTI}, scritture={"upsert"})
        esito = db.inserisci_domini_nuovi([{"host": "ente.it"}], client=client, strumento=_Strumento())
        self.assertEqual((esito["lotti_falliti"], esito["inserite"]), (1, 0))


class MisureDelPercorsoA(unittest.TestCase):
    CONTI = [
        ("bando", (("in_", "stato_processing", ["processed", "enriched"]), ("gte",)), 4),
        ("bando", (("in_", "stato_processing", ["processed", "enriched"]),), 573),
        ("bando_evento", (("gte",),), 289),
    ]

    def _misure(self, **opzioni):
        client = opzioni.pop("client", None) or _Client({}, conti=self.CONTI)
        return client, db.misure_salute(adesso=ADESSO, client=client, strumento=_Strumento(),
                                        **opzioni)

    def test_fermi_nella_finestra_e_arretrato(self):
        client, misure = self._misure()
        self.assertEqual((misure["fermi_in_lavorazione"], misure["arretrato_in_lavorazione"]),
                         (4, 573))
        fermi = next(q for q in client.su("bando") if q.ha("in_") and q.ha("gte"))
        self.assertEqual(fermi.argomenti("gte")[1], ("created_at", "2026-09-24T08:00:00+02:00"))
        self.assertEqual(fermi.argomenti("lt")[1], ("created_at", "2026-09-30T19:00:00+02:00"))
        arretrato = next(q for q in client.su("bando") if q.ha("in_") and not q.ha("gte"))
        self.assertFalse(arretrato.ha("lt"))

    def test_proposte_senza_i_tipi_di_servizio(self):
        client, misure = self._misure()
        self.assertEqual(misure["proposte_7g"], 289)
        proposte = next(q for q in client.su("bando_evento") if q.ha("gte"))
        self.assertTrue(proposte.ha("not_"))
        self.assertEqual(proposte.argomenti("in_")[1], (
            "tipo", ["fonte_ufficiale_non_trovata", "fonte_ufficiale_verificata",
                     "segnale_fonte", "sparito_dalla_fonte"]))

    def test_vista_come_anon_se_c_e_la_chiave(self):
        anon = _Client({"bando_pubblico": [{"id": 1}]})
        client, misure = self._misure(client_anon=anon)
        self.assertEqual(misure["vista_ms_ruolo"], "anon")
        self.assertIsInstance(misure["vista_ms"], float)
        # Con la service key si legge solo `da_verificare`, mai la pagina di prova.
        self.assertEqual([q for q in client.su("bando_pubblico")
                          if "slug" in q.argomenti("select")[1][0]], [])
        lettura = anon.su("bando_pubblico")[0]
        self.assertEqual(lettura.argomenti("limit")[1], (20,))
        self.assertIn("stato_effettivo", lettura.argomenti("select")[1][0])

    def test_vista_misura_la_select_della_verifica_7(self):
        """Revisione del 01/10: le colonne che passano da `dominio_ufficiale`."""
        anon = _Client({"bando_pubblico": []})
        self._misure(client_anon=anon)
        lettura = anon.su("bando_pubblico")[0]
        self.assertEqual(lettura.argomenti("select")[1][0].split(","), [
            "id", "slug", "titolo", "stato_effettivo", "data_scadenza", "link_bando",
            "link_candidatura", "allegati", "stato_da_verificare"])
        self.assertEqual(lettura.argomenti("in_")[1],
                         ("stato_effettivo", ["aperto", "in apertura prossimamente"]))
        ordini = [(c[1], c[2]) for c in lettura.chiamate if c[0] == "order"]
        self.assertEqual(ordini, [(("data_pubblicazione",), {"desc": True, "nullsfirst": False}),
                                  (("id",), {})])
        self.assertNotIn("fonte_ufficiale_e_atto", lettura.argomenti("select")[1][0])

    def test_vista_senza_la_13_non_chiede_stato_da_verificare(self):
        anon = _Client({"bando_pubblico": []})
        strumento = _Strumento({"bando": set(), "bando_controllo": set(), "pipeline_run": set(),
                                "bando_pubblico": {"id", "slug", "titolo", "stato_effettivo",
                                                   "data_scadenza", "link_bando",
                                                   "link_candidatura", "allegati"}})
        client = _Client({}, conti=self.CONTI)
        misure = db.misure_salute(adesso=ADESSO, client=client, strumento=strumento,
                                  client_anon=anon)
        lettura = anon.su("bando_pubblico")[0]
        self.assertNotIn("stato_da_verificare", lettura.argomenti("select")[1][0])
        self.assertIn("allegati", lettura.argomenti("select")[1][0])
        self.assertIsInstance(misure["vista_ms"], float)

    def test_vista_con_la_service_key_senza_anon(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(db.VARIABILE_ANON, None)
            client, misure = self._misure()
        self.assertEqual(misure["vista_ms_ruolo"], "servizio")
        self.assertEqual(len([q for q in client.su("bando_pubblico")
                              if "slug" in q.argomenti("select")[1][0]]), 1)

    def test_la_chiave_anon_viene_dall_ambiente_e_non_si_stampa(self):
        anon = _Client({"bando_pubblico": []})
        registro = MagicMock()
        with patch.dict(os.environ, {db.VARIABILE_ANON: "chiave-anon-di-prova"}), \
                patch.object(db, "create_client", return_value=anon) as crea, \
                patch.object(db, "logger", registro):
            _, misure = self._misure()
        self.assertEqual(misure["vista_ms_ruolo"], "anon")
        self.assertEqual(crea.call_args[0][1], "chiave-anon-di-prova")
        self.assertNotIn("chiave-anon-di-prova", repr(registro.mock_calls))

    def test_vista_rotta_vale_none(self):
        anon = _Client(errori={"bando_pubblico": RuntimeError("57014 statement timeout")})
        _, misure = self._misure(client_anon=anon)
        self.assertEqual((misure["vista_ms"], misure["vista_ms_ruolo"]), (None, "anon"))


class MisureAdellaVerifica(unittest.TestCase):
    """`da_verificare`, `letture_scadute` e `verifica_7g` (§14 parte A)."""

    def _pipeline_run(self, ultima=None, settimana=()):
        def risposte(query):
            if not query.ha("eq", "step", "verifica_stato"):
                return []
            if query.ha("gte"):
                return list(settimana)
            return [ultima] if ultima else []
        return risposte

    def _misure(self, risposte, strumento=None, conti=None, verifica_attiva=True):
        client = _Client(risposte, conti=conti or [])
        return client, db.misure_salute(adesso=ADESSO, client=client,
                                        strumento=strumento or _Strumento(),
                                        verifica_attiva=verifica_attiva)

    def test_da_verificare_none_finche_la_verifica_e_in_ombra(self):
        """Revisione del 01/10, ciclo 2: in ombra il riepilogo per BandoFit resta null."""
        vista = [{"id": 4, "stato_effettivo": "aperto", "stato_da_verificare": "senza_conferma"}]
        settimana = [{"id": 1, "esiti": {"piemonte": {"letture": 5, "esiti": 3}}}]
        client, misure = self._misure(
            {"bando_pubblico": vista, "pipeline_run": self._pipeline_run(settimana=settimana)},
            verifica_attiva=False)
        self.assertIsNone(misure["da_verificare"])
        # Nessuna lettura dei motivi; le altre misure del percorso A restano.
        self.assertEqual([q for q in client.su("bando_pubblico")
                          if "stato_da_verificare" in q.argomenti("select")[1][0]
                          and q.ha("is_")], [])
        self.assertEqual(misure["verifica_7g"], {"piemonte": {"letture": 5, "esiti": 3}})
        # In attivo, la stessa vista da' l'oggetto.
        _, misure = self._misure({"bando_pubblico": vista}, verifica_attiva=True)
        self.assertEqual(misure["da_verificare"]["aperto"], {"senza_conferma": 1})

    def test_la_modalita_si_legge_dalle_impostazioni(self):
        vista = [{"id": 4, "stato_effettivo": "aperto", "stato_da_verificare": "senza_conferma"}]
        for impostazioni, atteso in (
                (SimpleNamespace(verifica_stato_modalita="attivo"), True),
                (SimpleNamespace(verifica_stato_modalita="ombra"), False),
                (SimpleNamespace(), False)):
            with self.subTest(impostazioni=impostazioni), \
                    patch.object(db, "get_settings", return_value=impostazioni):
                _, misure = self._misure({"bando_pubblico": vista}, verifica_attiva=None)
            self.assertEqual(misure["da_verificare"] is not None, atteso)
        with patch.object(db, "get_settings", side_effect=RuntimeError("env")):
            _, misure = self._misure({"bando_pubblico": vista}, verifica_attiva=None)
        self.assertIsNone(misure["da_verificare"])

    def test_senza_la_13_valgono_none(self):
        strumento = _Strumento({"bando": set(), "pipeline_run": set(),
                                "bando_controllo": {"bando_id", "controlli_falliti"},
                                "bando_pubblico": {"id", "stato_effettivo"}})
        _, misure = self._misure({}, strumento)
        self.assertIsNone(misure["da_verificare"])
        self.assertIsNone(misure["letture_scadute"])
        self.assertIsNone(misure["verifica_7g"])        # nessuna riga del passo

    def test_da_verificare_per_ramo_motivo_e_numeri_del_passo(self):
        vista = [
            {"id": 1, "stato_effettivo": "in apertura prossimamente",
             "stato_da_verificare": "senza_conferma"},
            {"id": 2, "stato_effettivo": "in apertura prossimamente",
             "stato_da_verificare": "senza_conferma"},
            {"id": 3, "stato_effettivo": "aperto", "stato_da_verificare": "termine_passato"},
            {"id": 4, "stato_effettivo": "aperto", "stato_da_verificare": "senza_conferma"},
        ]
        ultima = {"id": 90, "c_modalita": "attivo",
                  "c_proposte_per_tipo": {"chiusura": 5, "rettifica": 2},
                  "c_applicati_per_tipo": {"chiusura": 5},
                  "c_trattenute_per_freno": {"lazioeuropa": 3, "piemonte": 0},
                  "c_pagine_rimosse": 2, "c_forse_non_bandi": None}
        conti = [("bando_evento", (("eq", "tipo", "chiusura"), ("eq", "origine", "worker"),
                                   ("eq", "applicato", True)), 7)]
        client, misure = self._misure(
            {"bando_pubblico": vista, "pipeline_run": self._pipeline_run(ultima)}, conti=conti)
        self.assertEqual(misure["da_verificare"], {
            "in_apertura": {"senza_conferma": 2},
            "aperto": {"termine_passato": 1, "senza_conferma": 1},
            "proposte_in_ombra_per_tipo": {"rettifica": 2},
            "host_frenati": 1, "pagine_rimosse": 2, "forse_non_bandi": 0,
            "chiusure_applicate_7g": 7,
        })
        lettura = next(q for q in client.su("bando_pubblico")
                       if "stato_da_verificare" in q.argomenti("select")[1][0])
        self.assertTrue(lettura.ha("is_", "stato_da_verificare", "null"))
        chiusure = next(q for q in client.su("bando_evento") if q.ha("eq", "tipo", "chiusura"))
        self.assertEqual(chiusure.argomenti("gte")[1], ("rilevato_at", "2026-09-24T08:00:00+02:00"))

    def test_in_ombra_tutte_le_proposte_sono_in_ombra(self):
        ultima = {"id": 91, "c_modalita": "ombra", "c_proposte_per_tipo": {"chiusura": 4}}
        _, misure = self._misure({"bando_pubblico": [], "pipeline_run": self._pipeline_run(ultima)})
        self.assertEqual(misure["da_verificare"]["proposte_in_ombra_per_tipo"], {"chiusura": 4})
        self.assertEqual(misure["da_verificare"]["in_apertura"], {})

    def test_letture_scadute_solo_sui_candidati_leggibili(self):
        def controllo(query):
            return [{"bando_id": 1}, {"bando_id": 2}, {"bando_id": 99}]
        def bando(query):
            return [{"id": 1}, {"id": 2}, {"id": 3}] if query.ha("or_") else []
        client, misure = self._misure({"bando_controllo": controllo, "bando": bando})
        self.assertEqual(misure["letture_scadute"], 2)
        lettura = next(q for q in client.su("bando_controllo") if q.ha("neq"))
        self.assertEqual(lettura.argomenti("neq")[1], ("lettura_stato->>pagina", "illeggibile"))
        self.assertEqual(lettura.argomenti("lt")[1], ("lettura_stato_at", "2026-09-15T08:00:00+02:00"))

    def test_verifica_7g_somma_gli_esiti(self):
        settimana = [
            {"id": 1, "esiti": {"piemonte": {"letture": 5, "esiti": 3}, "lazioeuropa": {"letture": 2}}},
            {"id": 2, "esiti": {"piemonte": {"letture": 4, "esiti": 0}}},
            {"id": 3, "esiti": None},
        ]
        client, misure = self._misure({"pipeline_run": self._pipeline_run(settimana=settimana)})
        self.assertEqual(misure["verifica_7g"], {"piemonte": {"letture": 9, "esiti": 3},
                                                 "lazioeuropa": {"letture": 2, "esiti": 0}})
        query = next(q for q in client.su("pipeline_run")
                     if q.ha("eq", "step", "verifica_stato") and q.ha("gte"))
        self.assertEqual(query.argomenti("gte")[1], ("avviato_at", "2026-09-24T08:00:00+02:00"))


class MisurePerICodiciA(unittest.TestCase):
    """`ultime_verifiche`, `ultimi_ingressi`, `aperti_senza_scadenza`, prosa del monitor (#76)."""

    def _misure(self, pipeline_run, conti=None, strumento=None):
        client = _Client({"pipeline_run": pipeline_run}, conti=conti or [])
        return client, db.misure_salute(adesso=ADESSO, client=client,
                                        strumento=strumento or _Strumento())

    def test_righe_delle_due_fasi(self):
        def pipeline_run(query):
            if query.ha("eq", "step", "verifica_stato") and query.ha("limit", 10):
                return [{"id": 7, "esito": "ok", "c_fase": "controlli", "c_modalita": "ombra",
                         "c_trattenute_per_freno": {"lazioeuropa": 2}, "c_prosa_non_riscritta": 1,
                         "c_motivo_saltato": None}]
            if query.ha("eq", "step", "verifica_stato_ingresso"):
                return [{"id": 8, "esito": "ok", "c_trattenuti": 3, "c_rilasciati_a_tempo": 1}]
            return []
        client, misure = self._misure(pipeline_run)
        self.assertEqual(misure["ultime_verifiche"], [{
            "id": 7, "esito": "ok",
            "contatori": {"fase": "controlli", "modalita": "ombra",
                          "trattenute_per_freno": {"lazioeuropa": 2}, "prosa_non_riscritta": 1}}])
        self.assertEqual(misure["ultimi_ingressi"], [{
            "id": 8, "esito": "ok", "contatori": {"trattenuti": 3, "rilasciati_a_tempo": 1}}])
        ingressi = next(q for q in client.su("pipeline_run")
                        if q.ha("eq", "step", "verifica_stato_ingresso"))
        self.assertEqual(ingressi.argomenti("gte")[1], ("avviato_at", "2026-09-24T08:00:00+02:00"))
        # Recenti prima, come le altre serie: la regola guarda l'ultima riga.
        self.assertEqual([c for c in ingressi.chiamate if c[0] == "order"],
                         [("order", ("avviato_at",), {"desc": True}),
                          ("order", ("id",), {"desc": True})])

    def test_aperti_senza_scadenza_dalla_vista(self):
        conti = [("bando_pubblico", (("eq", "stato_effettivo", "aperto"),
                                     ("is_", "data_scadenza", "null")), 425)]
        _, misure = self._misure(lambda q: [], conti=conti)
        self.assertEqual(misure["aperti_senza_scadenza"], 425)

    def test_senza_tabelle_valgono_none(self):
        _, misure = self._misure(lambda q: [], strumento=_Strumento({"bando": set()}))
        for chiave in ("ultime_verifiche", "ultimi_ingressi", "aperti_senza_scadenza"):
            self.assertIsNone(misure[chiave])

    def test_la_prosa_del_monitor_e_fra_i_contatori(self):
        self.assertIn(("prosa_non_riscritta",), db.CONTATORI_MONITOR)

    def test_eventi_non_leggibili_del_monitor_e_della_verifica(self):
        self.assertIn(("eventi_invisibili",), db.CONTATORI_MONITOR)
        self.assertIn(("eventi_non_leggibili",), db.CONTATORI_ULTIME_VERIFICHE)

        def pipeline_run(query):
            if query.ha("eq", "step", "monitor"):
                return [{"id": 3, "esito": "ok", "c_eventi_invisibili": 2}]
            if query.ha("eq", "step", "verifica_stato") and query.ha("limit", 10):
                return [{"id": 7, "esito": "ok", "c_eventi_non_leggibili": 1}]
            return []
        _, misure = self._misure(pipeline_run)
        self.assertEqual(misure["ultimi_monitor"][0]["contatori"], {"eventi_invisibili": 2})
        self.assertEqual(misure["ultime_verifiche"][0]["contatori"], {"eventi_non_leggibili": 1})


class PubblicatiPerGemelli(unittest.TestCase):
    def test_con_calendario_porta_master_e_raw_delle_righe_senza_link(self):
        def bando(query):
            if query.ha("in_"):
                return [{"id": 2, "raw_data": {"col_1": "x"}}]
            return [{"id": 1, "link_bando": "https://ente.it/a", "bando_master_id": None},
                    {"id": 2, "link_bando": None, "bando_master_id": None}]
        client = _Client({"bando": bando})
        righe = db.select_pubblicati_per_gemelli(con_calendario=True, client=client,
                                                 strumento=_Strumento())
        self.assertIn("bando_master_id", client.su("bando")[0].argomenti("select")[1][0])
        self.assertEqual(client.su("bando")[1].argomenti("in_")[1], ("id", [2]))
        self.assertEqual(righe[1]["raw_data"], {"col_1": "x"})
        self.assertNotIn("raw_data", righe[0])

    def test_con_calendario_un_errore_si_solleva(self):
        client = _Client(errori={"bando": ConnectionError()})
        with self.assertRaises(ConnectionError):
            db.select_pubblicati_per_gemelli(con_calendario=True, client=client,
                                             strumento=_Strumento())
        self.assertEqual(db.select_pubblicati_per_gemelli(client=_Client(errori={
            "bando": ConnectionError()}), strumento=_Strumento()), [])


if __name__ == "__main__":
    unittest.main()
