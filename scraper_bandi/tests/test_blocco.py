# -*- coding: utf-8 -*-
"""Lock della pipeline: tre esiti e nessun `SystemExit` (fix 8.a.13, M14).

Nessuna chiamata reale al DB: la RPC e l'adattatore `db.controllo` sono finti.
"""
import unittest
from unittest import mock

from tests.supporto import carica_modulo

blocco = carica_modulo("blocco")


class _Controllo:
    """`db.controllo` finto: dice quali RPC esistono, senza toccare la rete."""

    def __init__(self, rpc=()):
        self.rpc = set(rpc)

    def rpc_disponibile(self, nome: str) -> bool:
        return nome in self.rpc


class _Rpc:
    """Registra le chiamate e ritorna cio' che gli si dice."""

    def __init__(self, risultati=None, errore=None):
        self.chiamate: list[tuple[str, dict]] = []
        self.risultati = list(risultati or [])
        self.errore = errore

    def __call__(self, nome, parametri, client):
        self.chiamate.append((nome, parametri))
        if self.errore is not None:
            raise self.errore
        return self.risultati.pop(0) if self.risultati else True


class _Risposta:
    """Forma tipica di PostgREST: il valore sta in `.data`."""

    def __init__(self, data):
        self.data = data


class TestAcquisisci(unittest.TestCase):
    def test_acquisito(self):
        rpc = _Rpc([_Risposta(True)])
        esito = blocco.acquisisci(
            "bandi_pipeline", "pid-1", 3600,
            controllo=_Controllo({blocco.RPC_ACQUISISCI}), rpc=rpc,
        )
        self.assertEqual(esito.esito, blocco.ACQUISITO)
        self.assertTrue(esito.proseguire)
        self.assertTrue(esito.da_rilasciare)
        self.assertEqual(
            rpc.chiamate,
            [(blocco.RPC_ACQUISISCI,
              {"p_nome": "bandi_pipeline", "p_proprietario": "pid-1", "p_ttl_s": 3600})],
        )

    def test_occupato(self):
        esito = blocco.acquisisci(
            "bandi_pipeline", "pid-2", 60,
            controllo=_Controllo({blocco.RPC_ACQUISISCI}), rpc=_Rpc([_Risposta(False)]),
        )
        self.assertEqual(esito.esito, blocco.OCCUPATO)
        self.assertFalse(esito.proseguire)
        self.assertFalse(esito.da_rilasciare)

    def test_assente_quando_la_rpc_non_esiste(self):
        # M14: la migrazione 04 la applica il committente. Finche' non c'e', il
        # giro prosegue SENZA lock, altrimenti la pipeline non partirebbe mai.
        rpc = _Rpc()
        esito = blocco.acquisisci("bandi_pipeline", "pid-3", 60, controllo=_Controllo(), rpc=rpc)
        self.assertEqual(esito.esito, blocco.ASSENTE)
        self.assertTrue(esito.proseguire)
        self.assertFalse(esito.da_rilasciare)
        self.assertEqual(rpc.chiamate, [])

    def test_errore_della_rpc_vale_assente_non_occupato(self):
        esito = blocco.acquisisci(
            "x", "pid", 60,
            controllo=_Controllo({blocco.RPC_ACQUISISCI}),
            rpc=_Rpc(errore=RuntimeError("rete giu'")),
        )
        self.assertEqual(esito.esito, blocco.ASSENTE)
        self.assertTrue(esito.proseguire)
        self.assertIn("rete giu'", esito.dettaglio["errore"])

    def test_controllo_che_esplode_non_ferma_il_giro(self):
        class Rotto:
            def rpc_disponibile(self, nome):
                raise RuntimeError("schema illeggibile")
        esito = blocco.acquisisci("x", "pid", 60, controllo=Rotto(), rpc=_Rpc())
        self.assertEqual(esito.esito, blocco.ASSENTE)

    def test_nessun_system_exit(self):
        for controllo in (_Controllo(), _Controllo({blocco.RPC_ACQUISISCI})):
            with self.subTest(controllo=controllo.rpc):
                try:
                    blocco.acquisisci("x", "pid", 1, controllo=controllo,
                                      rpc=_Rpc([_Risposta(False)]))
                except SystemExit:  # pragma: no cover
                    self.fail("acquisisci non deve mai sollevare SystemExit")


class TestLetturaDelRisultato(unittest.TestCase):
    def test_forme_ammesse(self):
        casi = [
            (_Risposta(True), True),
            (_Risposta(False), False),
            (_Risposta([True]), True),
            (_Risposta([]), False),
            (_Risposta([{"acquisito": True}]), True),
            (_Risposta({"acquisito": False}), False),
            (True, True),
            (None, False),
        ]
        for valore, atteso in casi:
            with self.subTest(valore=valore):
                self.assertEqual(blocco._preso(valore), atteso)


class TestRilascia(unittest.TestCase):
    def test_rilascia_solo_i_lock_acquisiti(self):
        rpc = _Rpc()
        preso = blocco.Blocco("x", "pid", blocco.ACQUISITO)
        self.assertTrue(blocco.rilascia(preso, rpc=rpc))
        self.assertEqual(rpc.chiamate, [(blocco.RPC_RILASCIA, {"p_nome": "x", "p_proprietario": "pid"})])

        rpc2 = _Rpc()
        for esito in (blocco.OCCUPATO, blocco.ASSENTE):
            self.assertFalse(blocco.rilascia(blocco.Blocco("x", "pid", esito), rpc=rpc2))
        self.assertEqual(rpc2.chiamate, [])

    def test_rilascio_fallito_non_solleva(self):
        preso = blocco.Blocco("x", "pid", blocco.ACQUISITO)
        self.assertFalse(blocco.rilascia(preso, rpc=_Rpc(errore=RuntimeError("giu'"))))


class TestEsitoSaltato(unittest.TestCase):
    def test_forma_del_dizionario(self):
        # E' il dizionario che lo step ritorna alla pipeline; l'exit 3 lo
        # produce solo la CLI.
        self.assertEqual(
            blocco.esito_saltato(blocco.Blocco("bandi_pipeline", "pid", blocco.OCCUPATO)),
            {"status": "ok", "saltato_per_lock": True, "lock": "bandi_pipeline"},
        )


class TestNessunAccessoAlDb(unittest.TestCase):
    def test_senza_client_e_senza_controllo_non_importa_db(self):
        # Se `acquisisci` provasse a costruire il client Supabase, questo mock
        # fallirebbe: la prova e' che con la RPC assente non ci arriva mai.
        with mock.patch.object(blocco, "_chiama_rpc", side_effect=AssertionError("mai")):
            esito = blocco.acquisisci("x", "pid", 60, controllo=_Controllo())
        self.assertEqual(esito.esito, blocco.ASSENTE)


if __name__ == "__main__":
    unittest.main()
