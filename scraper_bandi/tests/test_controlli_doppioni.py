# -*- coding: utf-8 -*-
"""`bando_runner.aggiorna_controlli`: una sola riga per bando in ogni UPSERT (§21.2).

Il caso visto in produzione l'01/10 (fonte 276): una fonte produce due volte lo
stesso elemento, l'hash compare due volte in `confronto.visti` e lo stesso
`bando_id` finisce due volte nello stesso UPSERT su `bando_controllo`. Postgres
rifiuta l'intero blocco con 21000 «ON CONFLICT DO UPDATE command cannot affect
row a second time»: due blocchi da 200 persi. Qui si verifica che:

  - un hash ripetuto in `visti` produce una sola riga di presenza;
  - due hash diversi con lo stesso `id` producono una sola riga, e per
    `priorita_controllo` vale il massimo fra le chiavi e quello gia' scritto,
    sempre in 0..100;
  - con piu' di 200 righe e doppioni a cavallo del confine di blocco nessun
    blocco (e nessun UPSERT) contiene due volte lo stesso `bando_id`;
  - gli `id` None si scartano, la tabella assente vale 0;
  - il valore restituito conta le righe davvero mandate.

Il client finto si comporta come Postgres: un blocco con due righe dello stesso
`bando_id` alza un'eccezione 21000 (e `_upsert_controllo` lo conta 0).
Nessuna rete, nessuna scrittura.
"""
import unittest
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

from tests.supporto import carica_modulo

bando_runner = carica_modulo("bando_runner")
segnali_mod = carica_modulo("segnali")

ADESSO = datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc)
COLONNE = ("bando_id", "ultimo_visto_in_fonte_at", "priorita_controllo")
CHIAVI_PRESENZA = {"bando_id", "ultimo_visto_in_fonte_at"}
CHIAVI_PRIORITA = {"bando_id", "priorita_controllo"}
BLOCCO = bando_runner.BLOCCO_LETTURA


class _Controllo:
    """`db.controllo` finto: niente rete, colonne dichiarate a mano."""

    def __init__(self, tabelle):
        self._tabelle = {k: frozenset(v) for k, v in tabelle.items()}

    def colonne(self, tabella):
        return self._tabelle.get(tabella, frozenset())

    def tabella_esiste(self, tabella):
        return bool(self.colonne(tabella))


class _Errore21000(Exception):
    pass


class _Upsert:
    def __init__(self, client, tabella):
        self._client = client
        self._tabella = tabella
        self._righe = []
        self._conflitto = None

    def upsert(self, righe, on_conflict=None):
        self._righe = [dict(r) for r in righe]
        self._conflitto = on_conflict
        return self

    def execute(self):
        chiavi = [r.get(self._conflitto) for r in self._righe]
        ripetute = sorted(k for k, n in Counter(chiavi).items() if n > 1)
        self._client.blocchi.append(SimpleNamespace(
            tabella=self._tabella, righe=self._righe, conflitto=self._conflitto,
            riuscito=not ripetute))
        if ripetute:
            raise _Errore21000(
                "21000 ON CONFLICT DO UPDATE command cannot affect row a second "
                f"time ({self._conflitto} ripetuti: {ripetute[:5]})")
        return SimpleNamespace(data=list(self._righe))


class _ClientFinto:
    """Registra ogni blocco mandato; rifiuta come Postgres quelli con doppioni."""

    def __init__(self):
        self.blocchi = []

    def table(self, nome):
        return _Upsert(self, nome)

    def di(self, colonna):
        """I blocchi del passo che scrive `colonna`."""
        return [b for b in self.blocchi if b.righe and colonna in b.righe[0]]


def _aggiorna(confronto, esistenti, client, tabelle=None):
    return bando_runner.aggiorna_controlli(
        confronto, esistenti, adesso=ADESSO, client=client,
        strumento=_Controllo({"bando_controllo": COLONNE} if tabelle is None else tabelle),
    )


def _confronto(visti=(), priorita=None):
    # `aggiorna_controlli` legge solo `visti` e `priorita` (con getattr).
    return SimpleNamespace(visti=tuple(visti), priorita=dict(priorita or {}))


class TestControlliSenzaDoppioni(unittest.TestCase):

    def _nessun_doppione(self, client):
        """Nessun blocco con id ripetuti, e per passo una sola riga per bando."""
        for blocco in client.blocchi:
            self.assertEqual(blocco.tabella, "bando_controllo")
            self.assertEqual(blocco.conflitto, "bando_id")
            ids = [r["bando_id"] for r in blocco.righe]
            ripetuti = sorted(k for k, n in Counter(ids).items() if n > 1)
            self.assertEqual(ripetuti, [], "blocco con id ripetuti")
            self.assertLessEqual(len(blocco.righe), BLOCCO)
            self.assertTrue(blocco.riuscito)
        for colonna in ("ultimo_visto_in_fonte_at", "priorita_controllo"):
            ids = [r["bando_id"] for b in client.di(colonna) for r in b.righe]
            ripetuti = sorted(k for k, n in Counter(ids).items() if n > 1)
            self.assertEqual(ripetuti, [], f"{colonna}: stesso bando in due blocchi")

    def _chiavi_uniformi(self, client):
        for b in client.di("ultimo_visto_in_fonte_at"):
            self.assertTrue(all(set(r) == CHIAVI_PRESENZA for r in b.righe))
        for b in client.di("priorita_controllo"):
            self.assertTrue(all(set(r) == CHIAVI_PRIORITA for r in b.righe))

    def test_hash_ripetuto_in_visti_una_riga_sola(self):
        # E' la forma del Confronto vero: `visti` non e' deduplicato.
        confronto = segnali_mod.Confronto(visti=("h1", "h2", "h1", "h1"))
        esistenti = {"h1": {"id": 101}, "h2": {"id": 102}}
        client = _ClientFinto()
        scritte = _aggiorna(confronto, esistenti, client)
        self._nessun_doppione(client)
        self._chiavi_uniformi(client)
        self.assertEqual(len(client.blocchi), 1)
        righe = client.blocchi[0].righe
        self.assertEqual([r["bando_id"] for r in righe], [101, 102])
        self.assertTrue(all(r["ultimo_visto_in_fonte_at"] == ADESSO.isoformat() for r in righe))
        self.assertEqual(scritte, 2)

    def test_due_hash_stesso_id_vince_la_priorita_massima(self):
        esistenti = {
            "ha": {"id": 101, "priorita_controllo": 30},
            "hb": {"id": 101, "priorita_controllo": 30},
            "hc": {"id": 102},
        }
        confronto = _confronto(visti=("ha", "hb", "hc"),
                               priorita={"ha": 40, "hb": 70, "hc": 20})
        client = _ClientFinto()
        scritte = _aggiorna(confronto, esistenti, client)
        self._nessun_doppione(client)
        self._chiavi_uniformi(client)
        presenza = [r for b in client.di("ultimo_visto_in_fonte_at") for r in b.righe]
        self.assertEqual([r["bando_id"] for r in presenza], [101, 102])
        priorita = [r for b in client.di("priorita_controllo") for r in b.righe]
        self.assertEqual(priorita, [{"bando_id": 101, "priorita_controllo": 70},
                                    {"bando_id": 102, "priorita_controllo": 20}])
        self.assertEqual(scritte, 4)

    def test_la_priorita_gia_scritta_vince_se_piu_alta(self):
        # 95 a DB batte 40 e 70 delle due chiavi; vale anche se una sola delle
        # due righe lette porta il valore gia' scritto.
        esistenti = {
            "ha": {"id": 101, "priorita_controllo": 95},
            "hb": {"id": 101, "priorita_controllo": 95},
            "hc": {"id": 102, "priorita_controllo": None},
            "hd": {"id": 102, "priorita_controllo": 85},
        }
        confronto = _confronto(priorita={"ha": 40, "hb": 70, "hc": 60, "hd": 10})
        client = _ClientFinto()
        scritte = _aggiorna(confronto, esistenti, client)
        self._nessun_doppione(client)
        priorita = [r for b in client.di("priorita_controllo") for r in b.righe]
        self.assertEqual(priorita, [{"bando_id": 101, "priorita_controllo": 95},
                                    {"bando_id": 102, "priorita_controllo": 85}])
        self.assertEqual(scritte, 2)

    def test_priorita_sempre_fra_0_e_100(self):
        esistenti = {
            "ha": {"id": 101}, "hb": {"id": 101},
            "hc": {"id": 102}, "hd": {"id": 102},
        }
        confronto = _confronto(priorita={"ha": 150, "hb": 40, "hc": -5, "hd": -20})
        client = _ClientFinto()
        _aggiorna(confronto, esistenti, client)
        self._nessun_doppione(client)
        priorita = [r for b in client.di("priorita_controllo") for r in b.righe]
        self.assertEqual(priorita, [{"bando_id": 101, "priorita_controllo": 100},
                                    {"bando_id": 102, "priorita_controllo": 0}])

    def test_oltre_un_blocco_con_doppioni_a_cavallo_del_confine(self):
        # 300 bandi, 400 hash visti: h0..h249 e poi h150..h299. I doppioni
        # h150..h199 stanno a cavallo del confine dei 200; h200..h249 cadrebbero
        # due volte nel secondo blocco.
        esistenti = {f"h{i}": {"id": 1000 + i} for i in range(300)}
        visti = [f"h{i}" for i in range(250)] + [f"h{i}" for i in range(150, 300)]
        self.assertGreater(len(visti), BLOCCO)
        primo, resto = set(visti[:BLOCCO]), set(visti[BLOCCO:])
        self.assertTrue(primo & resto, "precondizione: doppioni a cavallo del confine")
        # Priorita': due hash per bando (a/b) per 150 bandi, 300 chiavi.
        for i in range(150):
            esistenti[f"a{i}"] = {"id": 5000 + i, "priorita_controllo": 80 if i % 2 == 0 else None}
            esistenti[f"b{i}"] = {"id": 5000 + i, "priorita_controllo": 80 if i % 2 == 0 else None}
        priorita = {f"a{i}": 10 for i in range(150)}
        priorita.update({f"b{i}": 60 for i in range(150)})
        client = _ClientFinto()
        scritte = _aggiorna(_confronto(visti=visti, priorita=priorita), esistenti, client)

        self._nessun_doppione(client)
        self._chiavi_uniformi(client)
        presenza = client.di("ultimo_visto_in_fonte_at")
        self.assertEqual([len(b.righe) for b in presenza], [BLOCCO, 100])
        self.assertEqual(sorted(r["bando_id"] for b in presenza for r in b.righe),
                         [1000 + i for i in range(300)])
        righe_priorita = [r for b in client.di("priorita_controllo") for r in b.righe]
        self.assertEqual(len(righe_priorita), 150)
        for r in righe_priorita:
            atteso = 80 if (r["bando_id"] - 5000) % 2 == 0 else 60
            self.assertEqual(r["priorita_controllo"], atteso)
        # Le righe davvero mandate: 300 presenze + 150 priorita'.
        self.assertEqual(scritte, 450)
        self.assertEqual(scritte, sum(len(b.righe) for b in client.blocchi if b.riuscito))

    def test_id_none_e_hash_sconosciuti_scartati(self):
        esistenti = {"h1": {"id": None, "priorita_controllo": 50},
                     "h2": {"id": 102}, "h3": {}}
        confronto = _confronto(visti=("h1", "h2", "h3", "h4", "h2"),
                               priorita={"h1": 90, "h2": 30, "h3": 90, "h4": 90})
        client = _ClientFinto()
        scritte = _aggiorna(confronto, esistenti, client)
        self._nessun_doppione(client)
        presenza = [r["bando_id"] for b in client.di("ultimo_visto_in_fonte_at") for r in b.righe]
        priorita = [r for b in client.di("priorita_controllo") for r in b.righe]
        self.assertEqual(presenza, [102])
        self.assertEqual(priorita, [{"bando_id": 102, "priorita_controllo": 30}])
        self.assertEqual(scritte, 2)

    def test_tabella_assente_vale_zero(self):
        client = _ClientFinto()
        scritte = _aggiorna(_confronto(visti=("h1", "h1"), priorita={"h1": 90}),
                            {"h1": {"id": 101}}, client, tabelle={})
        self.assertEqual(scritte, 0)
        self.assertEqual(client.blocchi, [])


if __name__ == "__main__":
    unittest.main()
