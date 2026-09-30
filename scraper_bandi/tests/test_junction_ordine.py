# -*- coding: utf-8 -*-
"""`db.select_junction_per_bandi` pagina con un ordine univoco (revisione
avversaria del 30/09, P2-h; contratto di ottobre §1).

Con il solo `bando_id` le righe dello stesso bando non hanno un ordine fisso, e
lo scorrimento a pagine di PostgREST puo' ripeterne o saltarne. L'ordine giusto
e' `bando_id, <colonna FK>`, la chiave della junction, come in
`src/lib/corpus.ts`. Si verifica sia con il builder vero di postgrest (la
stringa `order` che arriverebbe al server, senza rete) sia con un client finto
che simula le pagine.
"""
import types
import unittest
from unittest import mock

from tests.supporto import carica_modulo

db = carica_modulo("db")


class ClientRegistra:
    """Registra gli ordini chiesti e restituisce le righe a pagine, ordinate
    come le ordinerebbe il server."""

    def __init__(self, righe):
        self.righe = righe
        self.ordini = []

    def table(self, _nome):
        return QueryFinta(self)


class QueryFinta:
    def __init__(self, client):
        self.client = client
        self.chiavi = []
        self.blocco = []
        self.intervallo = None

    def select(self, _colonne):
        return self

    def in_(self, _colonna, valori):
        self.blocco = list(valori)
        return self

    def order(self, colonna):
        self.chiavi.append(colonna)
        return self

    def limit(self, quanto):
        self.intervallo = (0, quanto - 1)
        return self

    def range(self, da, a):
        self.intervallo = (da, a)
        return self

    def execute(self):
        self.client.ordini.append(tuple(self.chiavi))
        righe = [r for r in self.client.righe if r["bando_id"] in self.blocco]
        righe.sort(key=lambda r: tuple(r[c] for c in self.chiavi))
        da, a = self.intervallo if self.intervallo else (0, len(righe) - 1)
        return types.SimpleNamespace(data=righe[da:a + 1])


class TestOrdineUnivoco(unittest.TestCase):
    def test_ordine_bando_id_poi_colonna(self):
        righe = [{"bando_id": 1, "beneficiario_id": b} for b in (27, 16, 22)]
        client = ClientRegistra(righe)
        esito = db.select_junction_per_bandi("bando_beneficiari", "beneficiario_id", [1],
                                             client=client)
        self.assertEqual(client.ordini, [("bando_id", "beneficiario_id")])
        self.assertEqual(esito, {1: [16, 22, 27]})

    def test_la_stringa_order_che_arriva_a_postgrest(self):
        # Il builder vero: le due `.order()` diventano un solo parametro.
        from postgrest import SyncPostgrestClient
        client = SyncPostgrestClient("https://test.invalid/rest/v1")
        query = (client.table("bando_beneficiari").select("bando_id,beneficiario_id")
                 .in_("bando_id", [1, 2]).order("bando_id").order("beneficiario_id"))
        self.assertEqual(query.request.params.get("order"),
                         "bando_id.asc,beneficiario_id.asc")

    def test_oltre_una_pagina_nessuna_riga_persa_ne_ripetuta(self):
        # 2 500 righe in un blocco solo: tre pagine da 1 000.
        righe = [{"bando_id": b, "settore_id": s} for b in range(1, 51) for s in range(50)]
        client = ClientRegistra(list(reversed(righe)))
        esito = db.select_junction_per_bandi("bando_settori", "settore_id",
                                             list(range(1, 51)), client=client)
        self.assertEqual(sum(len(v) for v in esito.values()), 2500)
        self.assertTrue(all(v == list(range(50)) for v in esito.values()))
        self.assertTrue(all(o == ("bando_id", "settore_id") for o in client.ordini))
        self.assertEqual(len(client.ordini), 3)


if __name__ == "__main__":
    unittest.main()
