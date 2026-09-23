# -*- coding: utf-8 -*-
"""hybrid (fix 8.a.17 d): i file scoperti si ordinano prima di `[:max_files]`.

Sul codice vecchio il taglio seguiva l'ordine DOM: con tre calendari
elencati dal piu' vecchio al piu' nuovo e `max_files=2` si scaricavano i
due piu' vecchi. Rete finta: `fetch_html` e `get_scraper` sostituiti.
"""
import asyncio
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from tests.supporto import carica_modulo

hybrid = carica_modulo("scrapers.hybrid")
scrapers = carica_modulo("scrapers")
base = carica_modulo("scrapers.base")


class TestDataDaNomeFile(unittest.TestCase):
    def test_formati_riconosciuti(self):
        casi = {
            "https://x.it/doc/calendario_15-03-2026.pdf": date(2026, 3, 15),
            "https://x.it/doc/calendario_2025-12-01.pdf": date(2025, 12, 1),
            "https://x.it/doc/cal_20250101.csv": date(2025, 1, 1),
            "https://x.it/wp-content/uploads/2026/03/cal.pdf": date(2026, 3, 1),
            "https://x.it/cal_settembre-2025.pdf": date(2025, 9, 1),
            "https://x.it/Calendario%20Marzo_2026.xlsx": date(2026, 3, 1),
            "https://x.it/doc/calendario-2024.pdf": date(2024, 1, 1),
            "https://x.it/programmazione-2021-2027.pdf": date(2027, 1, 1),
            # giorno impossibile: resta l'anno
            "https://x.it/cal_31-02-2026.pdf": date(2026, 1, 1),
        }
        for url, atteso in casi.items():
            self.assertEqual(hybrid._data_da_nome_file(url), atteso, url)

    def test_senza_data_o_solo_nella_query(self):
        self.assertIsNone(hybrid._data_da_nome_file("https://x.it/download.php?id=20260101"))
        self.assertIsNone(hybrid._data_da_nome_file("https://x.it/calendario-preavvisi.pdf"))
        self.assertIsNone(hybrid._data_da_nome_file("https://x.it/doc/1234567890.pdf"))


class TestOrdinaFileScoperti(unittest.TestCase):
    def test_piu_recente_prima(self):
        dom = [
            "https://x.it/calendario_2024.pdf",
            "https://x.it/calendario_15-03-2026.pdf",
            "https://x.it/calendario_2025-12-01.pdf",
        ]
        self.assertEqual(hybrid.ordina_file_scoperti(dom), [
            "https://x.it/calendario_15-03-2026.pdf",
            "https://x.it/calendario_2025-12-01.pdf",
            "https://x.it/calendario_2024.pdf",
        ])

    def test_senza_date_ordine_dom_conservato(self):
        dom = [
            "https://x.it/download.php?id=3",
            "https://x.it/download.php?id=1",
            "https://x.it/download.php?id=2",
        ]
        self.assertEqual(hybrid.ordina_file_scoperti(dom), dom)
        self.assertEqual(hybrid.ordina_file_scoperti(dom), hybrid.ordina_file_scoperti(list(dom)))

    def test_datati_prima_dei_non_datati(self):
        dom = ["https://x.it/calendario.pdf", "https://x.it/calendario-2023.pdf"]
        self.assertEqual(
            hybrid.ordina_file_scoperti(dom),
            ["https://x.it/calendario-2023.pdf", "https://x.it/calendario.pdf"],
        )

    def test_a_parita_di_data_vince_last_modified(self):
        dom = ["https://x.it/a-2026.pdf", "https://x.it/b-2026.pdf", "https://x.it/c-2026.pdf"]
        modifiche = {
            "https://x.it/a-2026.pdf": datetime(2026, 1, 10),
            "https://x.it/b-2026.pdf": datetime(2026, 5, 2),
            "https://x.it/c-2026.pdf": None,
        }
        self.assertEqual(hybrid.ordina_file_scoperti(dom, modifiche), [
            "https://x.it/b-2026.pdf", "https://x.it/a-2026.pdf", "https://x.it/c-2026.pdf",
        ])


class TestParseDataModifica(unittest.TestCase):
    def test_iso_e_http(self):
        self.assertEqual(hybrid._parse_data_modifica("2026-03-15"), datetime(2026, 3, 15))
        # aware → naive UTC
        self.assertEqual(
            hybrid._parse_data_modifica("2026-03-15T10:00:00+02:00"), datetime(2026, 3, 15, 8, 0),
        )
        self.assertEqual(
            hybrid._parse_data_modifica("Wed, 21 Oct 2015 07:28:00 GMT"),
            datetime(2015, 10, 21, 7, 28),
        )
        for brutto in (None, "", "  ", "ieri", "31/02/2026"):
            self.assertIsNone(hybrid._parse_data_modifica(brutto), brutto)


class ScraperFinto(base.BandoScraper):
    """Sub-scraper che registra il file ricevuto e produce un item per file."""
    chiamate: list[str] = []

    def __init__(self, file_url_override: str | None = None, **_extra):
        self.file_url = file_url_override

    async def scrape(self, fonte):
        ScraperFinto.chiamate.append(self.file_url)
        return [base.BandoItem(
            fonte_id=fonte["id"], tipo_link=fonte["tipo_link"], link_bando=None,
            titolo_raw=f"riga di {self.file_url}", raw_data={"source_url": self.file_url},
        )]


INDICE_HTML = """
<html><body>
  <h1>Calendario inviti</h1>
  <ul>
    <li><a href="/doc/calendario_inviti_2024.pdf">Calendario 2024</a></li>
    <li><a href="/doc/calendario_inviti_15-03-2026.pdf">Calendario 2026 (agg. marzo)</a></li>
    <li><a href="/doc/calendario_inviti_2025-12-01.pdf">Calendario 2025</a></li>
    <li><a href="/doc/calendario_inviti_15-03-2026.pdf">stesso file, duplicato</a></li>
    <li><a href="#top">torna su</a></li>
    <li><a href="mailto:info@example.invalid">scrivi</a></li>
  </ul>
</body></html>
"""

FONTE = {"id": 99, "link": "https://esempio.invalid/calendario", "tipo_link": "Preavviso",
         "formato_link": "HTML"}


class TestScrapeConMaxFiles(unittest.TestCase):
    def setUp(self):
        ScraperFinto.chiamate = []

    def _scrape(self, **kwargs):
        scraper = hybrid.HybridScraper(**kwargs)
        with patch.object(hybrid, "fetch_html", new=AsyncMock(return_value=INDICE_HTML)), \
             patch.object(scrapers, "get_scraper", new=lambda strategy, **kw: ScraperFinto(**kw)):
            return asyncio.run(scraper.scrape(FONTE))

    def test_max_files_prende_i_piu_recenti(self):
        items = self._scrape(max_files=2)
        self.assertEqual(ScraperFinto.chiamate, [
            "https://esempio.invalid/doc/calendario_inviti_15-03-2026.pdf",
            "https://esempio.invalid/doc/calendario_inviti_2025-12-01.pdf",
        ])
        self.assertEqual(len(items), 2)

    def test_default_max_files_resta_tre(self):
        self.assertEqual(hybrid.HybridScraper().max_files, 3)
        self._scrape()
        self.assertEqual(len(ScraperFinto.chiamate), 3)
        self.assertEqual(ScraperFinto.chiamate[0],
                         "https://esempio.invalid/doc/calendario_inviti_15-03-2026.pdf")
        self.assertEqual(ScraperFinto.chiamate[-1],
                         "https://esempio.invalid/doc/calendario_inviti_2024.pdf")

    def test_last_modified_dal_markup_a_parita_di_nome(self):
        html = """
        <a href="/doc/cal_a.pdf" data-last-modified="2026-01-10T00:00:00Z">A</a>
        <a href="/doc/cal_b.pdf"><time datetime="2026-05-02">B</time></a>
        <a href="/doc/cal_c.pdf">C</a>
        """
        scraper = hybrid.HybridScraper(max_files=1)
        with patch.object(hybrid, "fetch_html", new=AsyncMock(return_value=html)), \
             patch.object(scrapers, "get_scraper", new=lambda strategy, **kw: ScraperFinto(**kw)):
            asyncio.run(scraper.scrape(FONTE))
        self.assertEqual(ScraperFinto.chiamate, ["https://esempio.invalid/doc/cal_b.pdf"])


if __name__ == "__main__":
    unittest.main()
