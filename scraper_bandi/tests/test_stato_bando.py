# -*- coding: utf-8 -*-
"""Stato dei bandi in tre linguaggi (piano §4): il lato Python.

Gira sugli stessi casi del gemello TypeScript, letti da
`tests/stato-bando/casi.json` nella radice del repo: se una modifica tocca un
solo linguaggio, uno dei due runner fallisce.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import ast
import hashlib
import inspect
import json
import re
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from unittest import mock

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


# Gli ingressi della regola `stato_da_verificare` nell'ordine della firma
# (contratto interno del giro 2, §3 con §19.3). L'impronta di un caso della
# sezione `certezza` e' gemella di `chiaveCertezza()` nel test TypeScript: id,
# i sedici ingressi e l'atteso; `regola` e `nota` non entrano.
_INGRESSI_CERTEZZA = (
    "stato", "data_apertura", "apertura_verificata", "ora_apertura", "data_scadenza",
    "ora_scadenza", "pubblicato_at", "previsto_entro", "termine_indicato", "stato_letto",
    "stato_letto_su", "stato_letto_at", "stato_letto_metodo", "esaminato_attivo_at",
    "segnale_aggregatore_at", "adesso",
)


def _chiave_certezza(caso):
    campi = ("id",) + _INGRESSI_CERTEZZA + ("atteso",)
    return "\u0000".join(_canonico(caso[campo]) for campo in campi)


def _da_verificare(caso, modulo=stato_bando):
    """I timestamp restano testo, come arrivano da PostgREST; `adesso` e' un datetime."""
    return modulo.stato_da_verificare(
        *[caso[campo] for campo in _INGRESSI_CERTEZZA[:-1]],
        datetime.fromisoformat(caso["adesso"]),
    )


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
        # dal revocato si esce SOLO con l'annullamento della revoca, letto dal
        # worker (migrazione 14): nessun'altra uscita, nessun altro attore
        uscite = [t for t in righe if t["da"] == "revocato"]
        self.assertTrue(uscite)
        for t in uscite:
            self.assertEqual((t["attore"], t["evento"]), ("worker", "annullamento_revoca"), t["a"])
            self.assertEqual(t.get("migrazione"), 14, t["a"])
        self.assertEqual(sorted(t["a"] for t in uscite),
                         ["aperto", "chiuso", "in apertura prossimamente"])
        # un sospeso si chiude SOLO con una 'chiusura' del worker, mai d'ufficio (A3)
        chiusure_sospeso = [t for t in righe if t["da"] == "sospeso" and t["a"] == "chiuso"]
        self.assertTrue(chiusure_sospeso)
        for t in chiusure_sospeso:
            self.assertEqual((t["attore"], t["evento"]), ("worker", "chiusura"))
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
        # il worker porta un «in apertura» a chiuso SOLO con 'chiusura'
        # (contratto interno del giro 2, §4: etichetta strutturata, doppia lettura)
        chiusure = [
            t for t in righe
            if t["attore"] == "worker" and t["da"] == "in apertura prossimamente" and t["a"] == "chiuso"
        ]
        self.assertTrue(chiusure)
        for t in chiusure:
            self.assertEqual(t["evento"], "chiusura")

    def test_riga_24_entra_con_la_13(self):
        """23 righe dalla 04, una dalla 13: il seed della 04 non cambia."""
        righe = self.dati["transizioni"]
        self.assertEqual(len([t for t in righe if "migrazione" not in t]), 23)
        self.assertEqual(
            [(t["da"], t["a"], t["attore"], t["evento"], t["migrazione"])
             for t in stato_bando.TRANSIZIONI if t.get("migrazione") == 13],
            [("in apertura prossimamente", "chiuso", "worker", "chiusura", 13)],
        )

    def test_quattro_righe_entrano_con_la_14(self):
        """28 righe in tutto: 23 dalla 04, una dalla 13, quattro dalla 14."""
        self.assertEqual(len(stato_bando.TRANSIZIONI), 28)
        self.assertEqual(
            [(t["da"], t["a"], t["attore"], t["evento"], t["migrazione"])
             for t in stato_bando.TRANSIZIONI if t.get("migrazione") == 14],
            [
                ("sospeso", "chiuso", "worker", "chiusura", 14),
                ("revocato", "aperto", "worker", "annullamento_revoca", 14),
                ("revocato", "chiuso", "worker", "annullamento_revoca", 14),
                ("revocato", "in apertura prossimamente", "worker", "annullamento_revoca", 14),
            ],
        )
        # nessuna migrazione oltre la 14, e le righe stanno in ordine di migrazione
        migrazioni = [t.get("migrazione", 4) for t in stato_bando.TRANSIZIONI]
        self.assertEqual(migrazioni, sorted(migrazioni))
        self.assertLessEqual(max(migrazioni), 14)


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


class TestCertezza(unittest.TestCase):
    """Regola `stato_da_verificare` v2, sezione `certezza` di casi.json."""

    dati = _carica()["certezza"]
    REGOLE = (
        ("R0",) + tuple(f"I{n}" for n in range(1, 7)) + ("I6bis", "I7")
        + tuple(f"A{n}" for n in range(1, 9))
    )

    def test_fixture_protetto(self):
        self.assertEqual(self.dati["versione"], 2)
        casi = self.dati["casi"]
        self.assertGreaterEqual(len(casi), 80)
        self.assertGreaterEqual(len(casi), self.dati["conteggio_minimo"])
        for caso in casi:
            with self.subTest(caso["id"]):
                self.assertEqual(
                    hashlib.sha256(_chiave_certezza(caso).encode("utf-8")).hexdigest(),
                    caso["sha256"],
                    "il fixture e' stato modificato senza rigenerare lo sha256",
                )
        self.assertEqual(len({c["sha256"] for c in casi}), len(casi))
        self.assertEqual(len({c["id"] for c in casi}), len(casi))

    def test_vocabolario_e_parametri_allineati(self):
        self.assertEqual(list(stato_bando.MOTIVI_DA_VERIFICARE), self.dati["motivi"])
        self.assertEqual(list(stato_bando.STATI_LETTI), self.dati["stati_letti"])
        self.assertEqual(list(stato_bando.METODI_LETTURA), self.dati["metodi"])
        self.assertEqual(
            {
                "giorni_grazia_pubblicazione": stato_bando.GIORNI_GRAZIA_PUBBLICAZIONE,
                "giorni_validita_conferma": stato_bando.GIORNI_VALIDITA_CONFERMA,
                "giorni_grazia_ramo_a": stato_bando.GIORNI_GRAZIA_RAMO_A,
            },
            self.dati["parametri"],
        )

    def test_ogni_regola_e_ogni_motivo_coperti(self):
        casi = self.dati["casi"]
        for regola in self.REGOLE:
            self.assertTrue([c for c in casi if c["regola"] == regola], regola)
        for motivo in self.dati["motivi"]:
            self.assertTrue([c for c in casi if c["atteso"] == motivo], motivo)
        for caso in casi:
            self.assertIn(caso["regola"], self.REGOLE, caso["id"])

    def test_tabella_dei_casi_condivisa(self):
        for caso in self.dati["casi"]:
            with self.subTest(caso["id"]):
                self.assertEqual(_da_verificare(caso), caso["atteso"], f"{caso['regola']}: {caso['nota']}")

    def test_accetta_date_e_datetime_oltre_alle_stringhe(self):
        adesso = datetime(2026, 9, 30, 12, 0, tzinfo=stato_bando.ROMA)
        conferma = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
        esame = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
        pubblicato = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        # conferma dell'estrattore di 5 giorni fa: nessun motivo
        self.assertIsNone(stato_bando.stato_da_verificare(
            "aperto", None, None, None, None, None, pubblicato, None, None,
            "aperto", "aperto", conferma, "estrattore", esame, None, adesso,
        ))
        # termine come date: ieri e' passato, oggi no
        self.assertEqual(stato_bando.stato_da_verificare(
            "aperto", None, None, None, None, None, pubblicato, None, date(2026, 9, 29),
            None, None, None, None, esame, None, adesso,
        ), "termine_passato")
        self.assertIsNone(stato_bando.stato_da_verificare(
            "aperto", None, None, None, None, None, pubblicato, None, date(2026, 9, 30),
            None, None, None, None, esame, None, adesso,
        ))
        # data_apertura come date nel ramo I
        self.assertEqual(stato_bando.stato_da_verificare(
            "in apertura prossimamente", date(2026, 9, 29), False, None, None, None,
            pubblicato, None, None, None, None, None, None, None, None, adesso,
        ), "data_apertura_passata")

    def _conferma(self, stato_letto_at, adesso=None):
        return stato_bando.stato_da_verificare(
            "aperto", None, None, None, None, None, "2026-09-01T10:00:00+00:00", None, None,
            "aperto", "aperto", stato_letto_at, "estrattore", "2026-09-29T08:00:00+00:00", None,
            adesso or datetime(2026, 9, 30, 12, 0, tzinfo=stato_bando.ROMA),
        )

    def test_timestamp_come_li_restituisce_postgrest(self):
        for testo in (
            "2026-09-25T08:00:00.12345+00:00",
            "2026-09-25T08:00:00Z",
            "2026-09-25 08:00:00+00",
            "2026-09-25T08:00:00+0000",
            "2026-09-25",
        ):
            with self.subTest(testo):
                self.assertIsNone(self._conferma(testo))
        # malformato = None: la conferma non vale e resta senza_conferma
        for testo in ("boh", "25/09/2026", "2026-09-25T25:00:00Z", 20260925):
            with self.subTest(testo):
                self.assertEqual(self._conferma(testo), "senza_conferma")

    def test_naive_interpretato_come_utc(self):
        # 30/08 23:50 UTC e' gia' il 31/08 a Roma: 30 giorni prima del 30/09.
        self.assertIsNone(self._conferma("2026-08-30T23:50:00"))
        self.assertIsNone(self._conferma(datetime(2026, 8, 30, 23, 50)))
        # 30/08 21:50 UTC e' ancora il 30/08 a Roma: 31 giorni, scaduta.
        self.assertEqual(self._conferma(datetime(2026, 8, 30, 21, 50)), "senza_conferma")
        # anche `adesso` naive vale UTC: 30/09 22:30 UTC e' il 1/10 a Roma
        self.assertEqual(
            self._conferma("2026-08-31T08:00:00+00:00", adesso=datetime(2026, 9, 30, 22, 30)),
            "senza_conferma",
        )

    def test_senza_adesso_usa_orologio(self):
        self.assertEqual(
            stato_bando.stato_da_verificare(
                "aperto", None, None, None, None, None, None, None, "2000-01-01",
                None, None, None, None, "2000-01-02T00:00:00+00:00", None,
            ),
            "termine_passato",
        )
        self.assertIsNone(stato_bando.stato_da_verificare(
            "aperto", None, None, None, "2999-01-01", None, None, None, None,
            None, None, None, None, None, None,
        ))

    def test_firma_nell_ordine_del_contratto(self):
        """Stesso ordine della funzione SQL (§2.2 punto 4 con §19.2)."""
        parametri = list(inspect.signature(stato_bando.stato_da_verificare).parameters)
        self.assertEqual(tuple(parametri), _INGRESSI_CERTEZZA)
        self.assertIsNone(
            inspect.signature(stato_bando.stato_da_verificare).parameters["adesso"].default,
        )


# `fromisoformat` di Python 3.10: niente «Z», fusi solo ±HH:MM, frazioni di
# secondo di 3 o 6 cifre. In produzione il venv puo' essere un 3.10, mentre qui
# i test girano sul 3.12, che accetta tutto: senza questa simulazione una
# frazione a 5 cifre di PostgREST passerebbe qui e fallirebbe la' in silenzio
# (la conferma diventerebbe None e il bando «senza_conferma»).
_FORMA_310 = re.compile(
    r"\d{4}-\d{2}-\d{2}(.\d{2}(:\d{2}(:\d{2}(\.(\d{3}|\d{6}))?)?)?([+-]\d{2}:\d{2})?)?"
)


class _Datetime310(datetime):
    @classmethod
    def fromisoformat(cls, testo):
        if not _FORMA_310.fullmatch(testo):
            raise ValueError(f"Invalid isoformat string: {testo!r}")
        return datetime.fromisoformat(testo)


class TestParserPython310(unittest.TestCase):
    def test_la_simulazione_e_severa_come_il_310(self):
        for testo in (
            "2026-09-25T08:00:00.87927+00:00", "2026-09-25T08:00:00Z", "2026-09-25T08:00:00+00",
            "2026-09-25T08:00:00.9+00:00",
        ):
            with self.subTest(testo), self.assertRaises(ValueError):
                _Datetime310.fromisoformat(testo)
        self.assertEqual(
            _Datetime310.fromisoformat("2026-09-25T08:00:00.879270+00:00"),
            datetime(2026, 9, 25, 8, 0, 0, 879270, tzinfo=timezone.utc),
        )

    def test_forma_normalizzata(self):
        normalizza = stato_bando._iso_per_fromisoformat
        self.assertEqual(normalizza("2026-09-25T08:00:00.87927+00:00"), "2026-09-25T08:00:00.879270+00:00")
        self.assertEqual(normalizza("2026-09-25T08:00:00.9Z"), "2026-09-25T08:00:00.900000+00:00")
        self.assertEqual(normalizza("2026-09-25 08:00:00+00"), "2026-09-25T08:00:00+00:00")
        self.assertEqual(normalizza("2026-09-25T08:00:00-0130"), "2026-09-25T08:00:00-01:30")
        self.assertEqual(normalizza("2026-09-25T08:00:00.1234567+02:00"), "2026-09-25T08:00:00.123456+02:00")
        self.assertEqual(normalizza("2026-09-25T08:00:00"), "2026-09-25T08:00:00")
        self.assertEqual(normalizza("2026-09-25"), "2026-09-25")

    def test_istanti_di_postgrest_sul_310(self):
        attesi = {
            "2026-09-25T08:00:00.87927+00:00": datetime(2026, 9, 25, 8, 0, 0, 879270, tzinfo=timezone.utc),
            "2026-09-25T08:00:00.9Z": datetime(2026, 9, 25, 8, 0, 0, 900000, tzinfo=timezone.utc),
            "2026-09-25 10:00:00+02": datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
            "2026-09-25T08:00:00": datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        }
        with mock.patch.object(stato_bando, "datetime", _Datetime310):
            for testo, atteso in attesi.items():
                with self.subTest(testo):
                    self.assertEqual(stato_bando._istante(testo), atteso)
            self.assertIsNone(stato_bando._istante("2026-09-25T08:00:00."))

    def test_tabella_dei_casi_sul_310(self):
        """Tutti i casi, compresi quelli con frazioni di 5 e 1 cifra, col parser del 3.10."""
        with mock.patch.object(stato_bando, "datetime", _Datetime310):
            for caso in _carica()["certezza"]["casi"]:
                with self.subTest(caso["id"]):
                    self.assertEqual(_da_verificare(caso), caso["atteso"], caso["nota"])


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
        for caso in dati["certezza"]["casi"]:
            with self.subTest(caso["id"]):
                self.assertEqual(_da_verificare(caso, isolato), caso["atteso"])


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
