# -*- coding: utf-8 -*-
"""csv_parser (fix 8.a.17 c): colonne LINK/URL → link_bando, hash invariato.

Sul codice vecchio ogni riga usciva con `link_bando=None` anche quando il
file aveva una colonna LINK con un URL valido. Il download e' finto
(`fetch_bytes` sostituito): nessuna rete.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.supporto import carica_modulo

csv_parser = carica_modulo("scrapers.csv_parser")

FONTE = {"id": 321, "link": "https://esempio.invalid/calendario.csv",
         "tipo_link": "Preavviso", "formato_link": "CSV"}


def scrape_csv(testo: str, **kwargs):
    contenuto = testo.encode("utf-8")
    scraper = csv_parser.CsvParserScraper(**kwargs)
    with patch.object(csv_parser, "fetch_bytes", new=AsyncMock(return_value=contenuto)) as finto:
        items = asyncio.run(scraper.scrape(FONTE))
        finto.assert_awaited_once()
    return items


class TestColonnaLink(unittest.TestCase):
    def test_link_valido_in_link_bando_con_flag(self):
        items = scrape_csv(
            "Titolo;LINK;Scadenza\n"
            "Avviso formazione continua;https://www.regione.example.it/bandi/1;2026-12-31\n"
            "Avviso senza link;n.d.;2026-10-01\n"
            "Avviso con link vuoto;;2026-10-01\n",
            delimiter=";",
        )
        self.assertEqual(len(items), 3)
        con_link, senza_link, vuoto = items

        self.assertEqual(con_link.link_bando, "https://www.regione.example.it/bandi/1")
        self.assertIs(con_link.raw_data["hash_senza_link"], True)
        # i discriminatori dell'hash senza link restano identici a prima
        self.assertEqual(con_link.raw_data["row_index"], 0)
        self.assertEqual(con_link.raw_data["source_url"], FONTE["link"])
        self.assertEqual(con_link.titolo_raw, "Avviso formazione continua")

        self.assertIsNone(senza_link.link_bando)
        self.assertNotIn("hash_senza_link", senza_link.raw_data)
        self.assertIsNone(vuoto.link_bando)
        self.assertNotIn("hash_senza_link", vuoto.raw_data)

    def test_nome_colonna_case_insensitive_con_strip(self):
        items = scrape_csv(
            "Titolo, Url ,Note\n"
            "Avviso uno,http://www.comune.example.it/avviso,ok\n",
            delimiter=",",
        )
        self.assertEqual(items[0].link_bando, "http://www.comune.example.it/avviso")
        self.assertIs(items[0].raw_data["hash_senza_link"], True)

    def test_url_non_http_ignorato(self):
        items = scrape_csv(
            "Titolo;url\n"
            "Avviso ftp;ftp://files.example.it/a.pdf\n"
            "Avviso js;javascript:alert(1)\n"
            "Avviso relativo;/bandi/123\n"
            "Avviso senza host;https://\n",
            delimiter=";",
        )
        self.assertEqual(len(items), 4)
        for item in items:
            self.assertIsNone(item.link_bando, item.titolo_raw)
            self.assertNotIn("hash_senza_link", item.raw_data)

    def test_senza_colonna_link_comportamento_invariato(self):
        items = scrape_csv(
            "Titolo;Fondo;Importo\n"
            "Avviso A;FSE+;100000\n"
            "Avviso B;FESR;250000\n",
            delimiter=";",
        )
        self.assertEqual([i.link_bando for i in items], [None, None])
        for item in items:
            self.assertNotIn("hash_senza_link", item.raw_data)
            self.assertEqual(item.tipo_link, "Preavviso")
            self.assertEqual(item.fonte_id, 321)

    def test_prima_colonna_link_valida_vince(self):
        items = scrape_csv(
            "Titolo;link;URL\n"
            "Avviso doppio;n.d.;https://www.ente.example.it/b\n",
            delimiter=";",
        )
        self.assertEqual(items[0].link_bando, "https://www.ente.example.it/b")


class TestUrlHttpValido(unittest.TestCase):
    def test_valori(self):
        self.assertEqual(csv_parser._url_http_valido("  https://a.it/x "), "https://a.it/x")
        self.assertEqual(csv_parser._url_http_valido("HTTP://a.it"), "HTTP://a.it")
        for brutto in (None, "", "   ", 12, 1.5, True, "ftp://a.it", "https://", "www.a.it", "#"):
            self.assertIsNone(csv_parser._url_http_valido(brutto), brutto)


if __name__ == "__main__":
    unittest.main()
