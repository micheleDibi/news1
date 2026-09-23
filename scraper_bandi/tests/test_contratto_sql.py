# -*- coding: utf-8 -*-
"""Parita' fra il codice Python e le firme scritte nelle migrazioni v11.

Le migrazioni non sono applicate: nessuno di questi errori si vede girando il
worker, perche' la RPC non esiste ancora e il codice degrada con un log. Si
vedranno tutti insieme il giorno dopo la 04, e saranno indistinguibili da
«il monitor non trova niente». Qui si confrontano, riga per riga, i nomi che
il codice manda con i nomi che il file SQL dichiara.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import re
import unittest

from tests.supporto import REPO, carica_modulo

db = carica_modulo("db")
eventi = carica_modulo("eventi")

SQL = REPO / "backend" / "sql"
MIGRAZIONE_02 = SQL / "bando_v11_02_tabelle_di_servizio.sql"
MIGRAZIONE_04 = SQL / "bando_v11_04_transizioni.sql"

#: `p_nome tipo` dentro la lista dei parametri di una CREATE FUNCTION.
_PARAMETRO = re.compile(r"^\s*(p_[a-z_]+)\s+[a-z]", re.MULTILINE)


def parametri_di(percorso, funzione: str) -> tuple[str, ...]:
    """I parametri dichiarati da `CREATE ... FUNCTION public.<funzione>(...)`."""
    testo = percorso.read_text(encoding="utf-8")
    inizio = testo.index(f"FUNCTION public.{funzione}(")
    fine = testo.index("\n)", inizio)
    return tuple(_PARAMETRO.findall(testo[inizio:fine]))


class ParametriDelleRPC(unittest.TestCase):
    """PostgREST risolve le RPC **per nome**: un nome sbagliato e' PGRST202."""

    def test_registra_evento_usa_i_parametri_della_04(self):
        dichiarati = parametri_di(MIGRAZIONE_04, "bando_registra_evento")
        self.assertIn("p_bando_id", dichiarati)
        # Nessun `p_evento`, nessun `p_colonne`: la riga non si passa intera.
        self.assertNotIn("p_evento", dichiarati)
        self.assertNotIn("p_colonne", dichiarati)
        mandati = set(eventi.parametri_registra_evento({"bando_id": 1, "tipo": "proroga"}))
        self.assertEqual(mandati, set(eventi.PARAMETRI_REGISTRA_EVENTO))
        self.assertEqual(mandati - set(dichiarati), set())

    def test_fondi_usa_i_parametri_della_04(self):
        dichiarati = parametri_di(MIGRAZIONE_04, "bando_fondi")
        self.assertEqual(dichiarati, db.PARAMETRI_FONDI)
        # L'ordine conta: il doppione per primo. Invertirlo fonderebbe il
        # master dentro il doppione.
        self.assertEqual(dichiarati[0], "p_dup")

    def test_fondi_manda_il_doppione_come_p_dup(self):
        visti = {}

        class _Rpc:
            def __init__(self, nome, parametri):
                visti["nome"], visti["parametri"] = nome, parametri

            def execute(self):
                return type("R", (), {"data": 900})()

        class _Client:
            def rpc(self, nome, parametri):
                return _Rpc(nome, parametri)

        class _Strumento:
            def rpc_disponibile(self, _nome):
                return True

        effettivo = db.fondi_bandi(
            900, 901, "gemello esatto", client=_Client(), strumento=_Strumento())
        self.assertEqual(visti["parametri"], {
            "p_dup": 901, "p_master": 900, "p_motivo": "gemello esatto"})
        self.assertEqual(effettivo, 900)


class ColonneGenerate(unittest.TestCase):
    """`GENERATED ALWAYS AS (...) STORED`: valorizzarle e' un 428C9."""

    def test_il_codice_conosce_tutte_le_colonne_generate(self):
        generate = set()
        for percorso in sorted(SQL.glob("bando_v11_0*.sql")):
            testo = percorso.read_text(encoding="utf-8")
            for riga in testo.splitlines():
                if "GENERATED ALWAYS AS (" in riga and "IDENTITY" not in riga:
                    nome = riga.replace("ADD COLUMN IF NOT EXISTS", "").split()
                    if nome:
                        generate.add(nome[0])
        self.assertTrue(generate, "nessuna colonna generata trovata nelle migrazioni")
        self.assertEqual(generate - set(db.COLONNE_GENERATE), set())

    def test_la_riga_dell_evento_non_valorizza_dominio_prova(self):
        self.assertIn("dominio_prova", db.COLONNE_GENERATE)
        self.assertEqual(
            db.senza_generate({"bando_id": 1, "dominio_prova": "ente.it"}),
            {"bando_id": 1},
        )


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
