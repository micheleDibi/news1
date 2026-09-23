# -*- coding: utf-8 -*-
"""Un solo «oggi» per la pipeline (fix 8.a.15): `stato_bando.oggi_roma` in
Europe/Rome, anche a cavallo della mezzanotte UTC; `reconcile_stato_bando` e il
safety net dell'enrich runner non usano piu' `date.today()`."""
import ast
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from tests.supporto import APP, carica_modulo

stato_bando = carica_modulo("stato_bando")
date_validation = carica_modulo("date_validation")


class TestOrologioRoma(unittest.TestCase):
    def test_roma_e_la_zona(self):
        self.assertEqual(str(stato_bando.ROMA), "Europe/Rome")

    def test_adesso_roma_e_aware_in_roma(self):
        adesso = stato_bando.adesso_roma()
        self.assertIsNotNone(adesso.tzinfo)
        self.assertEqual(adesso.tzinfo, stato_bando.ROMA)
        self.assertEqual(stato_bando.oggi_roma(), adesso.date())

    def test_mezzanotte_utc_con_ora_legale(self):
        # 22/09 22:30 UTC e' gia' il 23/09 00:30 a Roma (UTC+2): UTC direbbe il 22.
        istante = datetime(2026, 9, 22, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(istante.date(), date(2026, 9, 22))
        self.assertEqual(stato_bando.oggi_roma(istante), date(2026, 9, 23))
        self.assertEqual(stato_bando.adesso_roma(istante).hour, 0)

    def test_mezzanotte_utc_con_ora_solare(self):
        # In gennaio Roma e' UTC+1: 23:30 UTC e' domani, 22:30 UTC e' ancora oggi.
        self.assertEqual(
            stato_bando.oggi_roma(datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)),
            date(2026, 1, 16),
        )
        self.assertEqual(
            stato_bando.oggi_roma(datetime(2026, 1, 15, 22, 30, tzinfo=timezone.utc)),
            date(2026, 1, 15),
        )

    def test_naive_interpretato_come_utc(self):
        # Un datetime senza fuso non deve dipendere dall'ora locale della macchina.
        self.assertEqual(stato_bando.oggi_roma(datetime(2026, 9, 22, 22, 30)), date(2026, 9, 23))
        self.assertEqual(stato_bando.oggi_roma(datetime(2026, 9, 22, 21, 59)), date(2026, 9, 22))

    def test_altro_fuso_convertito(self):
        # 23/09 07:30 a Tokyo (UTC+9) = 23/09 00:30 a Roma.
        tokyo = timezone(timedelta(hours=9))
        istante = datetime(2026, 9, 23, 7, 30, tzinfo=tokyo)
        self.assertEqual(stato_bando.oggi_roma(istante), date(2026, 9, 23))
        self.assertEqual(stato_bando.adesso_roma(istante).hour, 0)

    def test_data_italiana(self):
        self.assertEqual(stato_bando.data_italiana(date(2026, 9, 22)), "22 settembre 2026")
        self.assertEqual(stato_bando.data_italiana(date(2027, 1, 1)), "1 gennaio 2027")
        self.assertEqual(stato_bando.data_italiana(date(2026, 12, 31)), "31 dicembre 2026")

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

    def test_stato_effettivo_e_arrivata(self):
        # Il segnaposto «arriva in un giro successivo» e' stato sostituito dalla
        # funzione vera: i suoi casi stanno in tests/test_stato_bando.py.
        self.assertTrue(callable(stato_bando.stato_effettivo))


class TestReconcileUsaOggiRoma(unittest.TestCase):
    def test_reconcile_chiama_oggi_roma(self):
        # Sul codice vecchio (date.today()) l'attributo oggi_roma non esiste nel
        # modulo e patch.object solleva AttributeError.
        with mock.patch.object(date_validation, "oggi_roma", return_value=date(2026, 9, 23)) as orologio:
            self.assertEqual(
                date_validation.reconcile_stato_bando("aperto", None, date(2026, 9, 22)), "chiuso",
            )
            self.assertEqual(
                date_validation.reconcile_stato_bando("aperto", None, date(2026, 9, 23)), "aperto",
            )
            self.assertEqual(
                date_validation.reconcile_stato_bando("aperto", date(2026, 9, 24), None),
                "in apertura prossimamente",
            )
        self.assertEqual(orologio.call_count, 3)

    def test_today_esplicito_non_consulta_orologio(self):
        with mock.patch.object(
            date_validation, "oggi_roma", side_effect=AssertionError("non deve essere chiamato"),
        ):
            self.assertEqual(
                date_validation.reconcile_stato_bando(
                    "aperto", None, date(2026, 1, 1), today=date(2026, 1, 1),
                ),
                "aperto",
            )

    def test_a_cavallo_della_mezzanotte_utc(self):
        # Alle 22:30 UTC del 30/09 a Roma e' gia' il 1/10: la scadenza 30/09 e' passata.
        istante = datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc)
        oggi = date_validation.oggi_roma(istante)
        self.assertEqual(
            date_validation.reconcile_stato_bando("aperto", None, date(2026, 9, 30), today=oggi),
            "chiuso",
        )
        self.assertEqual(
            date_validation.reconcile_stato_bando("aperto", None, date(2026, 9, 30), today=istante.date()),
            "aperto",
        )

    def test_nessuna_chiamata_a_today_nei_moduli(self):
        for nome in ("date_validation.py", "bando_enrich_runner.py"):
            albero = ast.parse((APP / nome).read_text(encoding="utf-8"))
            for nodo in ast.walk(albero):
                if (
                    isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr == "today"
                ):
                    self.fail(f"{nome}: chiamata .today() alla riga {nodo.lineno}")

    def test_enrich_runner_importa_oggi_roma_e_reconcile(self):
        runner = carica_modulo("bando_enrich_runner")
        self.assertIs(runner.oggi_roma, stato_bando.oggi_roma)
        self.assertIs(runner.reconcile_stato_bando, date_validation.reconcile_stato_bando)


if __name__ == "__main__":
    unittest.main()
