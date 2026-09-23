# -*- coding: utf-8 -*-
"""`db.controllo`: l'adattatore sullo schema reale (piano §16.2 M12, A21).

Le migrazioni v11 le applica il committente: fino ad allora `bando` ha 36
colonne e le RPC nuove non esistono. Qui si verifica che il codice degradi
invece di sollevare.

Nessuna rete: lo schema arriva da un fornitore iniettato.
"""
import unittest

from tests.supporto import carica_modulo

db = carica_modulo("db")

SCHEMA_OGGI = {
    "definitions": {
        "bando": {"properties": {"id": {}, "slug": {}, "stato_processing": {}, "link_bando": {}}},
        "fonte": {"properties": {"id": {}, "link": {}}},
    },
    "paths": {"/bando": {}, "/fonte": {}, "/rpc/vecchia_rpc": {}},
}

SCHEMA_DOPO_MIGRAZIONI = {
    "definitions": {
        "bando": {"properties": {"id": {}, "slug": {}, "tentativi_seo": {}, "pubblicato": {}}},
        "pipeline_run": {"properties": {"id": {}, "step": {}}},
    },
    "paths": {"/rpc/lock_acquisisci": {}, "/rpc/lock_rilascia": {}},
}


class _Tabella:
    def __init__(self, registro, nome, errore=None):
        self._registro, self._nome, self._errore = registro, nome, errore
        self._payload = None
        self._filtro = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, colonna, valore):
        self._filtro = (colonna, valore)
        return self

    def execute(self):
        if self._errore is not None:
            raise self._errore
        self._registro.append((self._nome, self._payload, self._filtro))
        return self


class _Client:
    def __init__(self, errore=None):
        self.scritture: list[tuple] = []
        self._errore = errore

    def table(self, nome):
        return _Tabella(self.scritture, nome, self._errore)


def _controllo(schema, client=None):
    return db.Controllo(lambda: schema, client_factory=lambda: client or _Client())


class TestSchema(unittest.TestCase):
    def test_una_sola_lettura_per_processo(self):
        letture = []

        def fornitore():
            letture.append(1)
            return SCHEMA_OGGI

        c = db.Controllo(fornitore)
        for _ in range(5):
            c.colonne("bando")
            c.rpc_disponibile("x")
        self.assertEqual(len(letture), 1)

    def test_errore_di_lettura_da_insieme_vuoto(self):
        # «Non so» si traduce in «degrada», mai in un'eccezione che ferma lo step.
        def fornitore():
            raise RuntimeError("rete giu'")

        c = db.Controllo(fornitore)
        self.assertEqual(c.colonne("bando"), frozenset())
        self.assertFalse(c.ha("bando", "id"))
        self.assertFalse(c.rpc_disponibile("lock_acquisisci"))
        self.assertFalse(c.tabella_esiste("bando"))

    def test_azzera_rilegge(self):
        letture = []

        def fornitore():
            letture.append(1)
            return SCHEMA_OGGI

        c = db.Controllo(fornitore)
        c.colonne("bando")
        c.azzera()
        c.colonne("bando")
        self.assertEqual(len(letture), 2)

    def test_openapi_3_components_schemas(self):
        c = db.Controllo(lambda: {"components": {"schemas": {"bando": {"properties": {"id": {}}}}}})
        self.assertEqual(c.colonne("bando"), frozenset({"id"}))

    def test_schema_malformato(self):
        for schema in ({}, {"definitions": None}, {"definitions": {"bando": 3}}):
            with self.subTest(schema=schema):
                self.assertEqual(db.Controllo(lambda s=schema: s).colonne("bando"), frozenset())


class TestInterrogazioni(unittest.TestCase):
    def test_colonne_e_ha(self):
        c = _controllo(SCHEMA_OGGI)
        self.assertEqual(c.colonne("bando"), frozenset({"id", "slug", "stato_processing", "link_bando"}))
        self.assertTrue(c.ha("bando", "slug"))
        # Le colonne v11 non esistono ancora: ogni filtro che le usa deve
        # passare da `ha()` e degradare (senza, PostgREST risponde 42703).
        self.assertFalse(c.ha("bando", "tentativi_seo"))
        self.assertFalse(c.ha("bando", "pubblicato"))

    def test_tabella_sconosciuta(self):
        c = _controllo(SCHEMA_OGGI)
        self.assertFalse(c.tabella_esiste("bando_controllo"))
        self.assertEqual(c.colonne("bando_controllo"), frozenset())

    def test_ha_tutte(self):
        c = _controllo(SCHEMA_OGGI)
        self.assertTrue(c.ha_tutte("bando", ["id", "slug"]))
        self.assertFalse(c.ha_tutte("bando", ["id", "pubblicato"]))
        self.assertFalse(c.ha_tutte("bando_evento", []))

    def test_rpc_disponibile(self):
        self.assertFalse(_controllo(SCHEMA_OGGI).rpc_disponibile("lock_acquisisci"))
        self.assertTrue(_controllo(SCHEMA_DOPO_MIGRAZIONI).rpc_disponibile("lock_acquisisci"))

    def test_colonne_mancanti(self):
        c = _controllo(SCHEMA_OGGI)
        self.assertEqual(c.colonne_mancanti("bando", ["id", "pubblicato"]), ("pubblicato",))
        # Tabella sconosciuta: tutto manca.
        self.assertEqual(c.colonne_mancanti("ignota", ["a", "b"]), ("a", "b"))


class TestAggiorna(unittest.TestCase):
    def test_no_op_se_le_colonne_mancano(self):
        client = _Client()
        esito = _controllo(SCHEMA_OGGI, client).aggiorna("bando", 1, {"tentativi_seo": 3})
        self.assertFalse(esito["scritto"])
        self.assertEqual(esito["motivo"], "colonne_assenti")
        self.assertEqual(client.scritture, [])

    def test_scrive_le_colonne_presenti_e_scarta_le_altre(self):
        client = _Client()
        esito = _controllo(SCHEMA_OGGI, client).aggiorna(
            "bando", 7, {"slug": "x", "pubblicato": True})
        self.assertTrue(esito["scritto"])
        self.assertEqual(esito["ignorate"], ("pubblicato",))
        self.assertEqual(client.scritture, [("bando", {"slug": "x"}, ("id", 7))])

    def test_dopo_le_migrazioni_scrive_tutto(self):
        client = _Client()
        esito = _controllo(SCHEMA_DOPO_MIGRAZIONI, client).aggiorna(
            "bando", 7, {"tentativi_seo": 2, "pubblicato": True})
        self.assertTrue(esito["scritto"])
        self.assertEqual(esito["ignorate"], ())

    def test_payload_vuoto(self):
        client = _Client()
        self.assertFalse(_controllo(SCHEMA_OGGI, client).aggiorna("bando", 1, {})["scritto"])
        self.assertEqual(client.scritture, [])

    def test_errore_del_client_degrada(self):
        client = _Client(errore=RuntimeError("42501"))
        esito = _controllo(SCHEMA_OGGI, client).aggiorna("bando", 1, {"slug": "x"})
        self.assertFalse(esito["scritto"])
        self.assertIn("42501", esito["motivo"])

    def test_colonna_id_personalizzabile(self):
        client = _Client()
        _controllo(SCHEMA_OGGI, client).aggiorna("fonte", 3, {"link": "x"}, colonna_id="id")
        self.assertEqual(client.scritture[0][2], ("id", 3))


class TestIstanzaDiProcesso(unittest.TestCase):
    def test_esiste_ed_e_una_sola(self):
        self.assertIsInstance(db.controllo, db.Controllo)
        from tests.supporto import carica_modulo as ricarica
        self.assertIs(ricarica("db").controllo, db.controllo)


if __name__ == "__main__":
    unittest.main()
