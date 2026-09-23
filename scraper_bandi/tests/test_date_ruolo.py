# -*- coding: utf-8 -*-
"""Date con ruolo (piano §6.2, fix 8.a.24): `estrai_date_con_ruolo`, `norm_cit`
e `validate_date_candidate` che accetta una qualsiasi data compatibile della
quote (non piu' solo la prima)."""
import unittest
from datetime import date
from unittest import mock

from tests.supporto import carica_modulo

dv = carica_modulo("date_validation")


def ruoli(testo):
    return [(d.data.isoformat(), d.ruolo) for d in dv.estrai_date_con_ruolo(testo)]


class TestNormCit(unittest.TestCase):
    def test_nbsp_spazi_e_casefold(self):
        self.assertEqual(dv.norm_cit("Entro le   ORE\t12:00 "), "entro le ore 12:00")

    def test_apostrofi_e_trattini(self):
        self.assertEqual(
            dv.norm_cit("l’avviso – l‘ente — l´x l`y"),
            "l'avviso - l'ente - l'x l'y",
        )

    def test_nfkc(self):
        self.assertEqual(dv.norm_cit("ﬁne １２"), "fine 12")

    def test_vuoto(self):
        self.assertEqual(dv.norm_cit(None), "")
        self.assertEqual(dv.norm_cit("   "), "")


class TestCostruttoDalAl(unittest.TestCase):
    def test_differimento_con_anno_eliso(self):
        testo = "differimento dei termini: dal 22 ottobre al 1° dicembre 2026"
        trovate = dv.estrai_date_con_ruolo(testo)
        self.assertEqual(
            [(d.data, d.ruolo) for d in trovate],
            [(date(2026, 10, 22), "apertura"), (date(2026, 12, 1), "scadenza")],
        )
        self.assertEqual(testo[trovate[0].inizio:trovate[0].fine], "22 ottobre")
        self.assertEqual(testo[trovate[1].inizio:trovate[1].fine], "1° dicembre 2026")
        for d in trovate:
            self.assertEqual(d.citazione, "dal 22 ottobre al 1° dicembre 2026")

    def test_testo_reale_del_differimento(self):
        testo = (
            "Con Determinazione G12628 del 18/09/2026 è stato disposto il differimento "
            "dei termini: dal 22 ottobre al 1° dicembre 2026."
        )
        self.assertEqual(
            ruoli(testo),
            [("2026-09-18", "normativa"), ("2026-10-22", "apertura"), ("2026-12-01", "scadenza")],
        )

    def test_intervallo_numerico(self):
        self.assertEqual(
            ruoli("dal 01/03/2026 al 30/09/2026"),
            [("2026-03-01", "apertura"), ("2026-09-30", "scadenza")],
        )

    def test_costrutto_vince_sulle_parole_chiave(self):
        # «termini» e' parola di scadenza, ma il costrutto si valuta per primo.
        self.assertEqual(
            ruoli("termini: dal 22 ottobre al 1° dicembre 2026"),
            [("2026-10-22", "apertura"), ("2026-12-01", "scadenza")],
        )

    def test_dalle_ore_del_alle_ore_del(self):
        self.assertEqual(
            ruoli("dalle ore 9:00 del 15/10/2026 alle ore 12:00 del giorno 30/11/2026"),
            [("2026-10-15", "apertura"), ("2026-11-30", "scadenza")],
        )

    def test_anno_eliso_a_cavallo_dell_anno(self):
        self.assertEqual(
            ruoli("dal 15 dicembre al 31 gennaio 2027"),
            [("2026-12-15", "apertura"), ("2027-01-31", "scadenza")],
        )

    def test_solo_giorno_eredita_mese_e_anno(self):
        self.assertEqual(
            ruoli("dal 22 al 30 settembre 2026"),
            [("2026-09-22", "apertura"), ("2026-09-30", "scadenza")],
        )
        self.assertEqual(
            ruoli("dal 25 al 5 ottobre 2026"),
            [("2026-09-25", "apertura"), ("2026-10-05", "scadenza")],
        )

    def test_fino_al(self):
        self.assertEqual(
            ruoli("dal 1 marzo 2026 e fino al 30 settembre 2026"),
            [("2026-03-01", "apertura"), ("2026-09-30", "scadenza")],
        )

    def test_non_e_un_costrutto(self):
        # «dal 15 al 20%» non contiene date.
        self.assertEqual(ruoli("contributo dal 15 al 20% delle spese"), [])


class TestParoleChiave(unittest.TestCase):
    def test_centro_non_e_entro(self):
        self.assertEqual(ruoli("presso il centro servizi il 6 ottobre 2026"), [("2026-10-06", "ignoto")])

    def test_modalita_e_aziendale_non_sono_dal(self):
        self.assertEqual(ruoli("modalità di presentazione: 6 ottobre 2026"), [("2026-10-06", "ignoto")])
        self.assertEqual(ruoli("sicurezza aziendale, 6 ottobre 2026"), [("2026-10-06", "ignoto")])

    def test_entro_le_ore_del(self):
        self.assertEqual(ruoli("entro le ore 12:00 del 30/09/2026"), [("2026-09-30", "scadenza")])

    def test_normativa(self):
        for testo in (
            "Determinazione G12628 del 18/09/2026",
            "DGR n. 123 del 18/09/2026",
            "DD 45 del 18/09/2026",
            "Det. 12 del 18/09/2026",
            "ai sensi del decreto del 18/09/2026",
            "Delibera n. 4 del 18/09/2026",
            "Decreto Dirigenziale n. 9 del 18/09/2026",
        ):
            self.assertEqual(ruoli(testo), [("2026-09-18", "normativa")], testo)

    def test_sigle_sensibili_alle_maiuscole(self):
        self.assertEqual(ruoli("add 18/09/2026"), [("2026-09-18", "ignoto")])

    def test_pubblicazione(self):
        for testo in (
            "pubblicato sul BURL n. 40 del 10/09/2026",
            "pubblicata in data 10/09/2026",
            "GURI n. 200 del 10/09/2026",
            "BUR n. 40 del 10/09/2026",
        ):
            self.assertEqual(ruoli(testo), [("2026-09-10", "pubblicazione")], testo)

    def test_il_sostantivo_pubblicazione_non_e_parola_chiave(self):
        # La specifica elenca `\bpubblicat\w*`, che NON copre «pubblicazione»
        # (…caz…, non …cat…): la data resta 'ignoto', quindi compatibile con
        # qualunque label e mai scartata. Estendere la lista e' una decisione
        # del committente, non di questo giro.
        self.assertEqual(ruoli("Pubblicazione: 10/09/2026"), [("2026-09-10", "ignoto")])

    def test_apertura(self):
        for testo in (
            "a partire dal 01/10/2026",
            "apertura sportello 01/10/2026",
            "con decorrenza 01/10/2026",
            "dalle ore 10:00 del 01/10/2026",
        ):
            self.assertEqual(ruoli(testo), [("2026-10-01", "apertura")], testo)

    def test_scadenza(self):
        for testo in (
            "Scadenza: 30/09/2026",
            "termine 30/09/2026",
            "fino al 30/09/2026",
            "chiusura sportello 30/09/2026",
            "entro il 30 settembre 2026",
        ):
            self.assertEqual(ruoli(testo), [("2026-09-30", "scadenza")], testo)

    def test_piu_vicina_decide_la_normativa(self):
        self.assertEqual(
            ruoli("entro il termine di cui alla DGR 123 del 18/09/2026"),
            [("2026-09-18", "normativa")],
        )
        self.assertEqual(
            ruoli("ai sensi della L. 241/1990, entro il 30/09/2026"),
            [("2026-09-30", "scadenza")],
        )
        self.assertEqual(
            ruoli("Decreto del 10 settembre 2026, scadenza 30/10/2026"),
            [("2026-09-10", "normativa"), ("2026-10-30", "scadenza")],
        )

    def test_ruoli_diversi_nella_finestra_danno_ignoto(self):
        self.assertEqual(
            ruoli("termine di apertura dello sportello: 15/10/2026"),
            [("2026-10-15", "ignoto")],
        )
        self.assertEqual(
            ruoli("Pubblicato il 01/09/2026. Scadenza: 30/09/2026"),
            [("2026-09-01", "pubblicazione"), ("2026-09-30", "ignoto")],
        )

    def test_finestra_di_40_caratteri(self):
        riempitivo = "x" * 41
        self.assertEqual(ruoli(f"scadenza {riempitivo} 30/09/2026"), [("2026-09-30", "ignoto")])
        riempitivo = "x" * 30
        self.assertEqual(ruoli(f"scadenza {riempitivo} 30/09/2026"), [("2026-09-30", "scadenza")])

    def test_citazione_e_sottostringa(self):
        testo = "Le domande vanno presentate entro il 30/09/2026 tramite PEC."
        (trovata,) = dv.estrai_date_con_ruolo(testo)
        self.assertIn(trovata.citazione, testo)
        self.assertTrue(trovata.citazione.endswith("30/09/2026"))
        self.assertIn("entro", trovata.citazione)


class TestFormati(unittest.TestCase):
    def test_formati_riconosciuti(self):
        for testo in (
            "scadenza 2026-09-30",
            "scadenza 30/09/2026",
            "scadenza 30.09.2026",
            "scadenza 30-09-2026",
            "scadenza 30 settembre 2026",
            "scadenza 30 sett. 2026",
            "scadenza 30 set 2026",
        ):
            self.assertEqual(ruoli(testo), [("2026-09-30", "scadenza")], testo)
        self.assertEqual(ruoli("scadenza 1° dicembre 2026"), [("2026-12-01", "scadenza")])
        self.assertEqual(ruoli("scadenza 1 dicembre 2026"), [("2026-12-01", "scadenza")])

    def test_data_invalida_e_anno_eliso_fuori_costrutto(self):
        self.assertEqual(ruoli("scadenza 31/02/2026"), [])
        self.assertEqual(ruoli("entro il 30 settembre"), [])
        self.assertEqual(ruoli("entro il 30/09"), [])

    def test_ordinamento_e_vuoto(self):
        self.assertEqual(dv.estrai_date_con_ruolo(""), [])
        self.assertEqual(dv.estrai_date_con_ruolo(None), [])
        trovate = dv.estrai_date_con_ruolo("scadenza 30/09/2026; apertura 01/03/2026")
        self.assertEqual([d.inizio for d in trovate], sorted(d.inizio for d in trovate))

    def test_ruoli_ammessi(self):
        for d in dv.estrai_date_con_ruolo(
            "Pubblicato il 01/09/2026, DGR del 02/09/2026, dal 03/09/2026 al 04/09/2026, x 05/09/2026"
        ):
            self.assertIn(d.ruolo, dv.RUOLI_DATA)


class TestValidateDateCandidate(unittest.TestCase):
    def _cand(self, data, quote, source="official_page"):
        return {"date": data, "source": source, "quote": quote}

    def test_intervallo_accetta_la_scadenza(self):
        # Sul codice vecchio la PRIMA data (01/03) non coincide con 30/09 -> None.
        quote = "dal 01/03/2026 al 30/09/2026"
        html = f"Presentazione delle domande {quote}."
        self.assertEqual(
            dv.validate_date_candidate(self._cand("2026-09-30", quote), html, 1, "scadenza"),
            date(2026, 9, 30),
        )
        self.assertEqual(
            dv.validate_date_candidate(self._cand("2026-03-01", quote), html, 1, "apertura"),
            date(2026, 3, 1),
        )

    def test_ruolo_incompatibile_respinto(self):
        quote = "dal 01/03/2026 al 30/09/2026"
        html = f"Presentazione delle domande {quote}."
        self.assertIsNone(dv.validate_date_candidate(self._cand("2026-03-01", quote), html, 1, "scadenza"))
        self.assertIsNone(dv.validate_date_candidate(self._cand("2026-09-30", quote), html, 1, "apertura"))

    def test_normativa_mai(self):
        quote = "Determinazione G12628 del 18/09/2026"
        for label in ("pubblicazione", "apertura", "scadenza"):
            self.assertIsNone(dv.validate_date_candidate(self._cand("2026-09-18", quote), quote, 1, label))

    def test_ignoto_compatibile_con_tutto(self):
        quote = "presso il centro servizi il 6 ottobre 2026"
        for label in ("pubblicazione", "apertura", "scadenza"):
            self.assertEqual(
                dv.validate_date_candidate(self._cand("2026-10-06", quote), quote, 1, label),
                date(2026, 10, 6),
            )

    def test_seconda_data_della_quote(self):
        quote = "Pubblicato il 01/09/2026. Scadenza: 30/09/2026"
        self.assertEqual(
            dv.validate_date_candidate(self._cand("2026-09-30", quote), quote, 1, "scadenza"),
            date(2026, 9, 30),
        )
        self.assertEqual(
            dv.validate_date_candidate(self._cand("2026-09-01", quote), quote, 1, "pubblicazione"),
            date(2026, 9, 1),
        )
        self.assertIsNone(dv.validate_date_candidate(self._cand("2026-09-01", quote), quote, 1, "scadenza"))

    def test_confronto_normalizzato_quote_testo(self):
        # NBSP e apostrofo tipografico nel markdown, caratteri semplici nella quote.
        html = "L’avviso scade entro le ore 12:00 del 30/09/2026."
        quote = "L'avviso scade entro le ore 12:00 del 30/09/2026"
        self.assertEqual(
            dv.validate_date_candidate(self._cand("2026-09-30", quote), html, 1, "scadenza"),
            date(2026, 9, 30),
        )

    def test_quote_non_nel_testo(self):
        self.assertIsNone(
            dv.validate_date_candidate(self._cand("2026-09-30", "entro il 30/09/2026"), "altro testo", 1, "scadenza"),
        )

    def test_source_non_autoritativa(self):
        quote = "entro il 30/09/2026"
        self.assertIsNone(
            dv.validate_date_candidate(self._cand("2026-09-30", quote, source="inferred"), quote, 1, "scadenza"),
        )

    def test_data_non_nella_quote(self):
        quote = "entro il 30/09/2026"
        self.assertIsNone(dv.validate_date_candidate(self._cand("2026-09-29", quote), quote, 1, "scadenza"))

    def test_provenienza_aggregatore_ritorna_la_data_e_la_segnala(self):
        quote = "entro il 30/09/2026"
        with mock.patch.object(dv, "logger") as log:
            self.assertEqual(
                dv.validate_date_candidate(
                    self._cand("2026-09-30", quote), quote, 1, "scadenza", provenienza="aggregatore",
                ),
                date(2026, 9, 30),
            )
        messaggi = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("aggregatore", messaggi)
        with mock.patch.object(dv, "logger") as log:
            dv.validate_date_candidate(self._cand("2026-09-30", quote), quote, 1, "scadenza", provenienza="ente")
        self.assertEqual(log.info.call_count, 0)

    def test_extract_date_from_quote_resta(self):
        self.assertEqual(dv.extract_date_from_quote("dal 01/03/2026 al 30/09/2026"), date(2026, 3, 1))
        self.assertEqual(dv.extract_date_from_quote("31 dicembre 2026"), date(2026, 12, 31))
        self.assertIsNone(dv.extract_date_from_quote("nessuna data"))


if __name__ == "__main__":
    unittest.main()
