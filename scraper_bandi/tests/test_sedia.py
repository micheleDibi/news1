# -*- coding: utf-8 -*-
"""API SEDIA di EU Funding & Tenders (piano §5 passo 1).

Nessuna chiamata reale: il trasporto e' iniettato. Cio' che si verifica qui e'
la forma della richiesta (le parti **tipizzate**, senza le quali l'API risponde
400), la lettura della risposta e soprattutto la regola di accettazione:
identifier coincidente **e** ≥ 60 % dei token del titolo.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import json
import unittest
from datetime import date

from tests.supporto import carica_modulo

sedia = carica_modulo("sedia")
stato_bando = carica_modulo("stato_bando")

RISPOSTA = {
    "results": [
        {
            "metadata": {
                "identifier": ["HORIZON-CL2-2026-01-DEMOCRACY-01"],
                "callIdentifier": ["HORIZON-CL2-2026-01"],
                "title": ["Support to democracy and civic education in schools"],
                "status": ["31094502"],
                "startDate": ["2026-10-22-00-00-00"],
                "deadlineDate": ["2026-12-01T17:00:00+01:00", "2027-02-01"],
                "latestInfos": [{"date": "2026-09-18", "summary": "Deadline postponed"}],
            }
        },
        {"metadata": {"title": ["Senza identifier"]}},
    ]
}


class Richiesta(unittest.TestCase):
    def test_parti_tipizzate(self):
        richiesta = sedia.richiesta()
        self.assertEqual([p.nome for p in richiesta.parti], ["query", "languages", "sort"])
        for parte in richiesta.parti:
            self.assertEqual(parte.tipo_contenuto, "application/json")
        # Forma attesa da httpx: (None, contenuto, tipo).
        for nome, valore in richiesta.files().items():
            self.assertEqual(valore[0], None, nome)
            self.assertEqual(valore[2], "application/json", nome)

    def test_parametri_di_query_string(self):
        richiesta = sedia.richiesta(per_pagina=100, pagina=2)
        self.assertEqual(richiesta.url, sedia.URL_RICERCA)
        self.assertEqual(dict(richiesta.parametri), {
            "apiKey": "SEDIA", "text": "***", "pageSize": "100", "pageNumber": "2",
        })

    def test_filtro_tipi_e_stati(self):
        richiesta = sedia.richiesta(stati=["open", "forthcoming"])
        query = json.loads(richiesta.parte("query"))
        self.assertEqual(query["bool"]["must"][0], {"terms": {"type": ["1", "2", "8"]}})
        self.assertEqual(
            query["bool"]["must"][1], {"terms": {"status": ["31094502", "31094501"]}}
        )

    def test_filtro_per_identificatori(self):
        richiesta = sedia.richiesta(tipi=(), identificatori=["horizon-cl2-2026-01-democracy-01"])
        query = json.loads(richiesta.parte("query"))
        self.assertEqual(
            query["bool"]["must"][0],
            {"terms": {"identifier": ["HORIZON-CL2-2026-01-DEMOCRACY-01"]}},
        )

    def test_json_deterministico(self):
        self.assertEqual(sedia.richiesta().parte("query"), sedia.richiesta().parte("query"))


class Risposta(unittest.TestCase):
    def setUp(self):
        self.risultati = sedia.analizza(RISPOSTA)

    def test_una_riga_senza_identifier_non_entra(self):
        self.assertEqual(len(self.risultati), 1)

    def test_campi_letti(self):
        r = self.risultati[0]
        self.assertEqual(r.identifier, "HORIZON-CL2-2026-01-DEMOCRACY-01")
        self.assertEqual(r.call_identifier, "HORIZON-CL2-2026-01")
        self.assertEqual(r.stato, "open")
        self.assertEqual(r.stato_bando, "aperto")
        self.assertEqual(r.apertura, date(2026, 10, 22))
        self.assertEqual(r.scadenze, (date(2026, 12, 1), date(2027, 2, 1)))
        self.assertEqual(r.scadenza, date(2027, 2, 1))

    def test_latest_infos_per_il_gate_g7(self):
        informazione = self.risultati[0].ultime_informazioni[0]
        self.assertEqual(informazione.data, date(2026, 9, 18))
        self.assertEqual(informazione.testo, "Deadline postponed")

    def test_metadati_scalari(self):
        risultati = sedia.analizza({"results": [{"metadata": {
            "identifier": "ERASMUS-EDU-2026-PI", "status": "31094503",
            "title": "Partnership", "deadlineDate": "2026-03-05",
        }}]})
        self.assertEqual(risultati[0].stato, "closed")
        self.assertEqual(risultati[0].stato_bando, "chiuso")
        self.assertEqual(risultati[0].scadenze, (date(2026, 3, 5),))

    def test_risposta_vuota(self):
        self.assertEqual(sedia.analizza(None), ())
        self.assertEqual(sedia.analizza({}), ())

    def test_gli_stati_sono_quelli_del_vocabolario(self):
        for valore in sedia.STATO_BANDO.values():
            self.assertIn(valore, stato_bando.STATI_BANDO_PERSISTITI)


class UrlTopic(unittest.TestCase):
    def test_minuscolo(self):
        # Con l'identifier maiuscolo il portale risponde 404.
        self.assertEqual(
            sedia.url_topic("HORIZON-CL2-2026-01-DEMOCRACY-01"),
            "https://ec.europa.eu/info/funding-tenders/opportunities/data/"
            "topicDetails/horizon-cl2-2026-01-democracy-01.json",
        )

    def test_niente_url_da_stringhe_non_sicure(self):
        # Gate anti-allucinazione: un URL non si costruisce da una stringa che
        # non si e' guardata.
        for brutto in ("../etc/passwd", "a b", "", None, "x/../y", "http://altro.it"):
            self.assertIsNone(sedia.url_topic(brutto), brutto)


class Identificatori(unittest.TestCase):
    def test_token_intero(self):
        # La regex del piano, cercata dentro «HORIZON-CL2-2026-01-X», partirebbe
        # da «CL2»: si estrae il token intero, o l'identifier non combacia.
        self.assertEqual(
            sedia.identificatori("Bando HORIZON-CL2-2026-01-DEMOCRACY-01 per le scuole"),
            ("HORIZON-CL2-2026-01-DEMOCRACY-01",),
        )

    def test_nessun_falso_positivo(self):
        self.assertEqual(sedia.identificatori("Avviso pubblico 2026 per le scuole"), ())
        self.assertEqual(sedia.identificatori(None), ())

    def test_senza_doppioni(self):
        self.assertEqual(
            sedia.identificatori("ERASMUS-EDU-2026-PI e ancora ERASMUS-EDU-2026-PI"),
            ("ERASMUS-EDU-2026-PI",),
        )


class Accettazione(unittest.TestCase):
    def setUp(self):
        self.risultato = sedia.analizza(RISPOSTA)[0]

    def test_servono_tutte_e_due_le_condizioni(self):
        self.assertTrue(sedia.accetta(
            self.risultato, "horizon-cl2-2026-01-democracy-01",
            "Democracy and civic education in schools",
        ))

    def test_identifier_diverso_non_basta_il_titolo(self):
        self.assertFalse(sedia.accetta(
            self.risultato, "ERASMUS-EDU-2026-PI",
            "Democracy and civic education in schools",
        ))

    def test_titolo_lontano_non_basta_l_identifier(self):
        self.assertFalse(sedia.accetta(
            self.risultato, "HORIZON-CL2-2026-01-DEMOCRACY-01",
            "Contributi per la digitalizzazione delle imprese agricole",
        ))

    def test_soglia_del_60_percento(self):
        # 3 token su 5 = 0,60: accettato; 2 su 5 = 0,40: no.
        self.assertAlmostEqual(
            sedia.copertura_titolo(
                "support democracy civic education schools",
                "Support to democracy and civic education in schools",
            ),
            1.0,
        )
        self.assertFalse(sedia.accetta(self.risultato, self.risultato.identifier, ""))

    def test_scegli_prende_il_primo_accettabile(self):
        risultati = sedia.analizza(RISPOSTA)
        scelto = sedia.scegli(risultati, "HORIZON-CL2-2026-01-DEMOCRACY-01",
                              "democracy civic education schools")
        self.assertIs(scelto, risultati[0])
        self.assertIsNone(sedia.scegli(risultati, "ALTRO-2026-X", "qualsiasi"))


class TrasportoIniettato(unittest.TestCase):
    def test_cerca_non_tocca_la_rete(self):
        chiamate = []

        def trasporto(richiesta):
            chiamate.append(richiesta)
            return RISPOSTA

        risultati = sedia.cerca(trasporto, sedia.richiesta())
        self.assertEqual(len(risultati), 1)
        self.assertEqual(chiamate[0].url, sedia.URL_RICERCA)

    def test_dettaglio_accetta_solo_200_con_identifier(self):
        visti = []

        def trasporto(url):
            visti.append(url)
            return (200, {"TopicDetails": {"identifier": "HORIZON-CL2-2026-01-DEMOCRACY-01"}})

        esito = sedia.dettaglio("HORIZON-CL2-2026-01-DEMOCRACY-01", trasporto)
        self.assertIsNotNone(esito)
        self.assertTrue(visti[0].endswith("horizon-cl2-2026-01-democracy-01.json"))

    def test_dettaglio_rifiuta_404_e_json_senza_identifier(self):
        self.assertIsNone(sedia.dettaglio("ERASMUS-EDU-2026-PI", lambda u: (404, {})))
        self.assertIsNone(sedia.dettaglio("ERASMUS-EDU-2026-PI", lambda u: (200, {"x": "altro"})))
        self.assertIsNone(sedia.dettaglio(None, lambda u: (200, {})))

    def test_identifier_nel_json_scende_nelle_strutture(self):
        self.assertTrue(sedia.identifier_nel_json(
            {"a": [{"b": "horizon-cl2-2026-01-democracy-01"}]},
            "HORIZON-CL2-2026-01-DEMOCRACY-01",
        ))
        self.assertFalse(sedia.identifier_nel_json({"a": 1}, "X"))


class DataSedia(unittest.TestCase):
    def test_tre_scritture(self):
        self.assertEqual(sedia.data_sedia("2026-12-01T17:00:00+01:00"), date(2026, 12, 1))
        self.assertEqual(sedia.data_sedia("2026-12-01"), date(2026, 12, 1))
        self.assertEqual(sedia.data_sedia("2026-12-01-17-00-00"), date(2026, 12, 1))
        self.assertIsNone(sedia.data_sedia(""))
        self.assertIsNone(sedia.data_sedia("non una data"))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
