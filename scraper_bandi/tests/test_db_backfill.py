# -*- coding: utf-8 -*-
"""`db.py`: le letture e le scritture dei comandi di §6.2 e §6.4.

Tutto quello che c'e' qui dentro passa da `db.controllo`, e la ragione e'
sempre la stessa: le migrazioni v11 le applica il committente quando vuole, e
finche' non l'ha fatto `bando_evento` non esiste, `archiviato` non e' un valore
ammesso e `bando_applica_evento` non e' esposta. Un 42703 su una di queste
righe fermerebbe un lotto su **tutte** le righe, non su una.

Nessuna rete: lo schema arriva da un fornitore iniettato e il client e' finto.
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

db = carica_modulo("db")


def _tabella(*colonne):
    return {"properties": {nome: {} for nome in colonne}}


#: Il DB vivo: 36 colonne su `bando`, nessuna delle tabelle nuove.
_BANDO_OGGI = (
    "id", "slug", "titolo", "contenuto", "stato_processing", "stato_bando",
    "data_scadenza", "link_candidatura", "link_candidatura_source",
)
SCHEMA_OGGI = {
    "definitions": {"bando": _tabella(*_BANDO_OGGI)},
    "paths": {"/bando": {}},
}

#: Dopo le migrazioni 01-04: `pubblicato`, `bando_evento` e la RPC.
SCHEMA_DOPO = {
    "definitions": {
        "bando": _tabella(*_BANDO_OGGI, "pubblicato",
                          "fonte_ufficiale_url", "fonte_ufficiale_stato"),
        "bando_evento": _tabella(
            "id", "bando_id", "tipo", "campo", "valore_prima", "valore_dopo",
            "data_evento", "rilevato_at", "applicato", "verificato", "leggibile",
            "url_prova", "citazione", "confidenza", "gate"),
    },
    "paths": {"/bando": {}, "/bando_evento": {}, "/rpc/bando_applica_evento": {}},
}


class _Negazione:
    """`query.not_.is_(...)`: PostgREST lo espone come attributo, non come
    chiamata, e un `__getattr__` che ritorna una funzione non basterebbe."""

    def __init__(self, query):
        self._query = query

    def __getattr__(self, nome):
        def _chiama(*argomenti):
            self._query.filtri.append((f"not.{nome}", *argomenti))
            return self._query
        return _chiama


class _Query:
    """Registra i filtri invece di eseguirli: nessuna richiesta parte."""

    def __init__(self, dati=()):
        self.dati = list(dati)
        self.colonne = ""
        self.filtri: list[tuple] = []
        self.rpc_chiamate: list[tuple] = []
        self.risposta_rpc = True

    def __getattr__(self, nome):
        if nome == "not_":
            return _Negazione(self)

        def _chiama(*argomenti):
            self.filtri.append((nome, *argomenti))
            return self
        return _chiama

    def table(self, nome):
        self.filtri.append(("table", nome))
        return self

    def select(self, colonne):
        self.colonne = colonne
        self.filtri.append(("select", colonne))
        return self

    def rpc(self, nome, parametri):
        self.rpc_chiamate.append((nome, parametri))
        return type("R", (), {
            "execute": lambda _s: type("D", (), {"data": self.risposta_rpc})()})()

    def execute(self):
        return type("R", (), {"data": self.dati})()


def _strumento(schema):
    return db.Controllo(fornitore_schema=lambda: schema)


class TestSelectEventi(unittest.TestCase):
    def test_senza_tabella_non_parte_nessuna_richiesta(self):
        query = _Query([{"id": 1}])
        righe = db.select_eventi(client=query, strumento=_strumento(SCHEMA_OGGI))
        self.assertEqual(righe, [])
        self.assertEqual(query.filtri, [])

    def test_colonne_esplicite_mai_asterisco(self):
        query = _Query()
        db.select_eventi(client=query, strumento=_strumento(SCHEMA_DOPO))
        # `select=*` su `bando_evento` risponde 42501: i grant sono per colonna.
        self.assertNotIn("*", query.colonne)
        self.assertIn("citazione", query.colonne.split(","))

    def test_filtri_di_tipo_stato_e_limite(self):
        query = _Query()
        db.select_eventi(
            client=query, strumento=_strumento(SCHEMA_DOPO),
            tipi=("proroga", "rettifica"), applicato=False, verificato=True, limit=50)
        self.assertIn(("in_", "tipo", ["proroga", "rettifica"]), query.filtri)
        self.assertIn(("eq", "applicato", False), query.filtri)
        self.assertIn(("eq", "verificato", True), query.filtri)
        self.assertIn(("limit", 50), query.filtri)
        # Ordine stabile: `data_evento` e' NULL su molte righe.
        self.assertIn(("order", "id"), query.filtri)

    def test_dal_guarda_data_evento_oppure_rilevato_at(self):
        # Un evento datato dall'ente prima dell'ombra ma rilevato dopo (e
        # viceversa) deve entrare: con un solo predicato se ne perderebbe meta'.
        query = _Query()
        db.select_eventi(client=query, strumento=_strumento(SCHEMA_DOPO),
                         dal=date(2026, 9, 1))
        self.assertIn(
            ("or_", "data_evento.gte.2026-09-01,rilevato_at.gte.2026-09-01"),
            query.filtri)

    def test_limite_zero_significa_nessuna_riga(self):
        query = _Query()
        db.select_eventi(client=query, strumento=_strumento(SCHEMA_DOPO), limit=0)
        self.assertIn(("limit", 0), query.filtri)

    def test_un_errore_del_client_degrada(self):
        class _Rotto(_Query):
            def execute(self):
                raise RuntimeError("42501")

        righe = db.select_eventi(client=_Rotto(), strumento=_strumento(SCHEMA_DOPO))
        self.assertEqual(righe, [])


class TestSelectBandiPubblicati(unittest.TestCase):
    def test_prima_della_01_il_predicato_e_completed_piu_slug(self):
        query = _Query()
        db.select_bandi_pubblicati_contenuto(
            client=query, strumento=_strumento(SCHEMA_OGGI))
        self.assertIn(("eq", "stato_processing", "completed"), query.filtri)
        self.assertIn(("not.is_", "slug", "null"), query.filtri)

    def test_dopo_la_01_basta_pubblicato(self):
        query = _Query()
        db.select_bandi_pubblicati_contenuto(
            client=query, strumento=_strumento(SCHEMA_DOPO))
        self.assertIn(("eq", "pubblicato", True), query.filtri)
        self.assertNotIn(("eq", "stato_processing", "completed"), query.filtri)

    def test_con_gli_id_si_leggono_quelli_e_basta(self):
        query = _Query()
        db.select_bandi_pubblicati_contenuto(
            client=query, strumento=_strumento(SCHEMA_DOPO), bando_ids=(1, 2))
        self.assertIn(("in_", "id", [1, 2]), query.filtri)
        self.assertNotIn(("eq", "pubblicato", True), query.filtri)

    def test_solo_le_colonne_che_lo_schema_espone(self):
        query = _Query()
        db.select_bandi_pubblicati_contenuto(
            client=query, strumento=_strumento(SCHEMA_OGGI))
        chieste = query.colonne.split(",")
        self.assertIn("contenuto", chieste)
        self.assertNotIn("fonte_ufficiale_url", chieste)


class TestSelectProcessed(unittest.TestCase):
    def test_filtra_i_processed_non_pubblicati(self):
        query = _Query()
        db.select_processed_da_archiviare(
            client=query, strumento=_strumento(SCHEMA_DOPO), limit=10)
        self.assertIn(("eq", "stato_processing", "processed"), query.filtri)
        self.assertIn(("eq", "pubblicato", False), query.filtri)
        self.assertIn(("limit", 10), query.filtri)

    def test_senza_la_colonna_pubblicato_non_si_chiede(self):
        query = _Query()
        db.select_processed_da_archiviare(
            client=query, strumento=_strumento(SCHEMA_OGGI))
        self.assertNotIn(("eq", "pubblicato", False), query.filtri)


class TestApplicaEvento(unittest.TestCase):
    def test_senza_rpc_non_si_applica_niente(self):
        query = _Query()
        self.assertFalse(db.applica_evento(
            7, client=query, strumento=_strumento(SCHEMA_OGGI)))
        self.assertEqual(query.rpc_chiamate, [])

    def test_con_rpc_passa_l_id(self):
        query = _Query()
        self.assertTrue(db.applica_evento(
            7, client=query, strumento=_strumento(SCHEMA_DOPO)))
        self.assertEqual(query.rpc_chiamate,
                         [("bando_applica_evento", {"p_evento_id": 7})])

    def test_evento_gia_applicato_ritorna_falso(self):
        # La funzione SQL risponde `false`: e' un esito, non un errore, ma non
        # va contato come applicazione.
        query = _Query()
        query.risposta_rpc = False
        self.assertFalse(db.applica_evento(
            7, client=query, strumento=_strumento(SCHEMA_DOPO)))

    def test_rpc_che_solleva_degrada(self):
        class _Rotto(_Query):
            def rpc(self, nome, parametri):
                raise RuntimeError("23514")

        self.assertFalse(db.applica_evento(
            7, client=_Rotto(), strumento=_strumento(SCHEMA_DOPO)))


class _Scrittura:
    """`controllo.aggiorna` finto: registra e non esegue."""

    def __init__(self, colonne):
        self.colonne = set(colonne)
        self.scritture: list[tuple] = []

    def ha(self, tabella, colonna):
        return colonna in self.colonne

    def colonne_mancanti(self, tabella, payload):
        return tuple(c for c in payload if c not in self.colonne)

    def aggiorna(self, tabella, id_riga, payload, **kwargs):
        self.scritture.append((tabella, id_riga, dict(payload)))
        return {"scritto": True, "ignorate": (), "motivo": ""}


class TestArchiviaBando(unittest.TestCase):
    def test_prima_della_01_non_si_tenta_nemmeno(self):
        # Il CHECK in tabella ammette ancora cinque valori: un UPDATE con
        # `archiviato` risponderebbe 23514 su ogni riga del lotto.
        strumento = _Scrittura({"id", "stato_processing"})
        esito = db.archivia_bando(700, strumento=strumento)
        self.assertFalse(esito["scritto"])
        self.assertEqual(esito["saltato"], "colonne_assenti")
        self.assertEqual(strumento.scritture, [])

    def test_dopo_la_01_scrive_solo_stato_processing(self):
        strumento = _Scrittura({"id", "stato_processing", "pubblicato"})
        self.assertTrue(db.archivia_bando(700, strumento=strumento)["scritto"])
        tabella, id_riga, payload = strumento.scritture[0]
        self.assertEqual((tabella, id_riga), ("bando", 700))
        # Nient'altro: mai `pubblicato`, mai `slug`, mai `data_pubblicazione`.
        self.assertEqual(payload, {"stato_processing": "archiviato"})


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
