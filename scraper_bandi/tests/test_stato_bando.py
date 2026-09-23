# -*- coding: utf-8 -*-
"""Stato dei bandi in tre linguaggi (piano §4): il lato Python.

Gira sugli stessi casi del gemello TypeScript, letti da
`tests/stato-bando/casi.json` nella radice del repo: se una modifica tocca un
solo linguaggio, uno dei due runner fallisce.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import ast
import hashlib
import json
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from tests.supporto import APP, REPO, carica_modulo, carica_per_percorso

stato_bando = carica_modulo("stato_bando")

CASI = REPO / "tests" / "stato-bando" / "casi.json"


def _carica():
    with open(CASI, encoding="utf-8-sig") as sorgente:
        return json.load(sorgente)


# Serializzazione canonica di un caso, gemella di `chiave()` in
# `tests/estrazioni/stato-bando.test.ts`: i campi che contano uniti da U+0000,
# con U+0001 al posto di null. `nota` non entra nell'impronta. Se le due copie
# divergono, uno dei due runner non ritrova lo `sha256` del fixture.
_CAMPI_IMPRONTA = (
    "id", "stato", "data_apertura", "apertura_verificata", "ora_apertura",
    "data_scadenza", "ora_scadenza", "adesso", "atteso",
)


def _canonico(valore):
    if valore is None:
        return "\u0001"
    if valore is True:
        return "true"
    if valore is False:
        return "false"
    return str(valore)


def _chiave(caso):
    return "\u0000".join(_canonico(caso[campo]) for campo in _CAMPI_IMPRONTA)


def _stato(caso, modulo=stato_bando):
    return modulo.stato_effettivo(
        caso["stato"],
        caso["data_apertura"],
        caso["apertura_verificata"],
        caso["ora_apertura"],
        caso["data_scadenza"],
        caso["ora_scadenza"],
        datetime.fromisoformat(caso["adesso"]),
    )


class TestFixture(unittest.TestCase):
    dati = _carica()

    def test_conteggio_minimo(self):
        """Nessuno deve poter cancellare casi in silenzio."""
        self.assertGreaterEqual(len(self.dati["casi"]), self.dati["conteggio_minimo"])

    def test_identificatori_unici(self):
        visti = [caso["id"] for caso in self.dati["casi"]]
        self.assertEqual(len(visti), len(set(visti)))

    def test_impronta_di_ogni_caso(self):
        """Nessuno deve poter cambiare un atteso o una data in silenzio."""
        for caso in self.dati["casi"]:
            with self.subTest(caso["id"]):
                self.assertEqual(
                    hashlib.sha256(_chiave(caso).encode("utf-8")).hexdigest(),
                    caso["sha256"],
                    "il fixture e' stato modificato senza rigenerare lo sha256",
                )
        impronte = [caso["sha256"] for caso in self.dati["casi"]]
        self.assertEqual(len(impronte), len(set(impronte)))

    def test_vocabolario_allineato(self):
        self.assertEqual(list(stato_bando.STATI_BANDO), self.dati["stati"])
        self.assertEqual(list(stato_bando.ATTORI_TRANSIZIONE), self.dati["attori"])

    def test_stati_persistiti(self):
        """La terna del CHECK finche' la 06 non e' applicata."""
        self.assertEqual(
            list(stato_bando.STATI_BANDO_PERSISTITI),
            ["aperto", "chiuso", "in apertura prossimamente"],
        )
        for stato in stato_bando.STATI_BANDO_PERSISTITI:
            self.assertIn(stato, stato_bando.STATI_BANDO)

    def test_transizioni_allineate(self):
        self.assertEqual([dict(t) for t in stato_bando.TRANSIZIONI], self.dati["transizioni"])


class TestTransizioni(unittest.TestCase):
    dati = _carica()

    def test_ogni_riga_e_ammessa(self):
        for t in self.dati["transizioni"]:
            with self.subTest(da=t["da"], a=t["a"], attore=t["attore"]):
                self.assertTrue(stato_bando.transizione_ammessa(t["da"], t["a"], t["attore"]))

    def test_lista_bianca_su_tutte_le_combinazioni(self):
        """Entrambe le direzioni: quello che non e' in tabella e' vietato."""
        chiavi = {(t["da"], t["a"], t["attore"]) for t in self.dati["transizioni"]}
        partenze = [None] + list(self.dati["stati"])
        for da in partenze:
            for a in self.dati["stati"]:
                for attore in self.dati["attori"]:
                    with self.subTest(da=da, a=a, attore=attore):
                        self.assertEqual(
                            stato_bando.transizione_ammessa(da, a, attore),
                            (da, a, attore) in chiavi,
                        )

    def test_invarianti(self):
        righe = self.dati["transizioni"]
        # revocato e' terminale
        self.assertFalse([t for t in righe if t["da"] == "revocato"])
        # nessuno chiude un sospeso d'ufficio (A3)
        self.assertFalse([t for t in righe if t["da"] == "sospeso" and t["a"] == "chiuso"])
        # il cron non tocca mai sospeso ne revocato
        for t in [r for r in righe if r["attore"] == "cron"]:
            self.assertNotIn(t["da"], ("sospeso", "revocato"))
            self.assertNotIn(t["a"], ("sospeso", "revocato"))
        # la pipeline scrive solo i tre stati che il CHECK a DB ammette oggi, e
        # solo alla creazione: non tocca mai una riga pubblicata, quindi in
        # `bando_transizione` non deve avere nessun passaggio fra stati
        for t in [r for r in righe if r["attore"] == "pipeline"]:
            self.assertNotIn(t["a"], ("sospeso", "revocato"))
            self.assertIsNone(t["da"], f"la pipeline non passa da {t['da']} a {t['a']}")
        # la redazione non ha scritture automatiche sullo stato
        self.assertFalse([t for t in righe if t["attore"] == "redazione"])
        # un chiuso riapre SOLO con un evento verificato del monitor (§4:
        # «unico modo per riaprire»; §13.3: un chiuso non riapre alla lettura)
        riaperture = [t for t in righe if t["da"] == "chiuso" and t["a"] == "aperto"]
        self.assertTrue(riaperture)
        for t in riaperture:
            self.assertEqual(t["attore"], "worker", t["evento"])


class TestStatoEffettivo(unittest.TestCase):
    dati = _carica()

    def test_tabella_dei_casi_condivisa(self):
        for caso in self.dati["casi"]:
            with self.subTest(caso["id"]):
                self.assertEqual(_stato(caso), caso["atteso"], caso["nota"])

    def test_accetta_date_e_time_oltre_alle_stringhe(self):
        adesso = datetime(2026, 9, 22, 12, 0, tzinfo=stato_bando.ROMA)
        self.assertEqual(
            stato_bando.stato_effettivo("aperto", None, None, None, date(2026, 9, 21), None, adesso),
            "chiuso",
        )
        self.assertEqual(
            stato_bando.stato_effettivo(
                "aperto", None, None, None, date(2026, 9, 22), time(8, 0), adesso,
            ),
            "chiuso",
        )
        self.assertEqual(
            stato_bando.stato_effettivo(
                "aperto", None, None, None, date(2026, 9, 22), time(18, 0), adesso,
            ),
            "aperto",
        )

    def test_naive_interpretato_come_utc(self):
        # 22:30 UTC del 22/09 e' gia' il 23/09 a Roma: la scadenza del 22 e' passata.
        naive = datetime(2026, 9, 22, 22, 30)
        self.assertEqual(
            stato_bando.stato_effettivo("aperto", None, None, None, "2026-09-22", None, naive),
            "chiuso",
        )
        self.assertEqual(
            stato_bando.stato_effettivo(
                "aperto", None, None, None, "2026-09-22", None,
                datetime(2026, 9, 22, 21, 59, tzinfo=timezone.utc),
            ),
            "aperto",
        )

    def test_senza_adesso_usa_orologio(self):
        self.assertEqual(
            stato_bando.stato_effettivo("aperto", None, None, None, "2000-01-01", None), "chiuso",
        )
        self.assertEqual(
            stato_bando.stato_effettivo("aperto", None, None, None, "2999-01-01", None), "aperto",
        )
        self.assertIsNone(stato_bando.stato_effettivo(None))

    def test_campi_malformati_non_inventano_stati(self):
        adesso = datetime(2026, 9, 22, 12, 0, tzinfo=stato_bando.ROMA)
        self.assertEqual(
            stato_bando.stato_effettivo("aperto", None, None, None, "boh", None, adesso), "aperto",
        )
        self.assertEqual(
            stato_bando.stato_effettivo(
                "aperto", None, None, None, "2026-09-22", "boh", adesso,
            ),
            "aperto",
        )
        # cifre non ASCII: str.isdigit() le accetterebbe, _cifre no
        self.assertEqual(
            stato_bando.stato_effettivo(
                "aperto", None, None, None, "２０２６-09-22", None, adesso,
            ),
            "aperto",
        )


class TestModuloCaricabilePerPercorso(unittest.TestCase):
    """Il test TypeScript lo esegue con `runpy.run_path`: nessun import interno."""

    def test_solo_stdlib_nessun_import_interno(self):
        albero = ast.parse((APP / "stato_bando.py").read_text(encoding="utf-8"))
        ammessi = {"__future__", "datetime", "zoneinfo"}
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.ImportFrom):
                self.assertEqual(nodo.level, 0, "stato_bando.py non deve avere import relativi")
                self.assertIn((nodo.module or "").split(".")[0], ammessi)
            elif isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    self.assertIn(alias.name.split(".")[0], ammessi)

    def test_caricato_fuori_dal_package_da_gli_stessi_risultati(self):
        isolato = carica_per_percorso("stato_bando_isolato", APP / "stato_bando.py")
        dati = _carica()
        for caso in dati["casi"]:
            with self.subTest(caso["id"]):
                self.assertEqual(_stato(caso, isolato), caso["atteso"])


class TestReconcileEUnWrapper(unittest.TestCase):
    """`reconcile_stato_bando` non deve avere una copia della regola."""

    def test_usa_la_funzione_unica(self):
        date_validation = carica_modulo("date_validation")
        self.assertIs(date_validation.stato_effettivo, stato_bando.stato_effettivo)

    def test_stesse_risposte_della_funzione_unica(self):
        date_validation = carica_modulo("date_validation")
        oggi = date(2026, 9, 22)
        prove = [
            ("aperto", None, None, "aperto"),
            ("aperto", None, date(2026, 9, 21), "chiuso"),
            ("aperto", None, date(2026, 9, 22), "aperto"),
            ("chiuso", None, date(2030, 1, 1), "chiuso"),
            ("aperto", date(2026, 12, 1), None, "in apertura prossimamente"),
            # la scadenza passata vince sull'apertura futura
            ("aperto", date(2026, 12, 1), date(2026, 9, 21), "chiuso"),
            ("unknown", None, None, None),
            (None, None, None, None),
            # uno stato fuori dai tre ammessi dall'LLM non passa MAI in scrittura
            ("sospeso", None, None, None),
            ("revocato", None, None, None),
            ("sospeso", None, date(2026, 9, 21), "chiuso"),
        ]
        for stato_llm, apertura, scadenza, atteso in prove:
            with self.subTest(stato_llm=stato_llm, apertura=apertura, scadenza=scadenza):
                self.assertEqual(
                    date_validation.reconcile_stato_bando(stato_llm, apertura, scadenza, today=oggi),
                    atteso,
                )

    def test_nessuna_copia_della_regola_nei_chiamanti(self):
        """Il safety net dell'enrich runner non ricalcola lo stato a mano."""
        sorgente = (APP / "bando_enrich_runner.py").read_text(encoding="utf-8")
        self.assertIn("reconcile_stato_bando(stato_bando, apt, scad, today=today)", sorgente)
        for vietato in ('== "chiuso" if', "data_scadenza <", "data_apertura >"):
            self.assertNotIn(vietato, sorgente)


if __name__ == "__main__":
    unittest.main()
