# -*- coding: utf-8 -*-
"""Registro per chiave normalizzata (fix 8.a.8).

Nessuna rete, nessun DB: si legge solo `SCRAPER_CONFIG`.
"""
import unittest
from unittest.mock import patch

from tests.supporto import carica_modulo

registro = carica_modulo("registro")
scraper_config = carica_modulo("scraper_config")

# Una voce reale del registro, usata come bersaglio delle 15 forme.
URL_ABRUZZO = "https://coesione.regione.abruzzo.it/bandi-avvisi"


class TestChiave(unittest.TestCase):
    def test_vuoto(self):
        self.assertEqual(registro.chiave(""), "")
        self.assertEqual(registro.chiave(None or ""), "")

    def test_slash_finale(self):
        self.assertEqual(registro.chiave("https://x.it/a/"), registro.chiave("https://x.it/a"))

    def test_radice_conserva_lo_slash(self):
        self.assertEqual(registro.chiave("https://x.it/"), "https://x.it/")

    def test_frammento_via(self):
        self.assertEqual(registro.chiave("https://x.it/a#b"), registro.chiave("https://x.it/a"))

    def test_query_ordinata(self):
        self.assertEqual(
            registro.chiave("https://x.it/a?b=2&a=1"), registro.chiave("https://x.it/a?a=1&b=2"),
        )

    def test_percent_encoding_decodificato(self):
        self.assertEqual(
            registro.chiave("https://x.it/citt%C3%A0"), registro.chiave("https://x.it/città"),
        )

    def test_maiuscole_e_accenti(self):
        # `classifier.normalize` fa casefold e toglie gli accenti: due forme
        # della stessa pagina non devono diventare due voci.
        self.assertEqual(registro.chiave("HTTPS://X.IT/Città"), registro.chiave("https://x.it/citta"))

    def test_parametro_vuoto_resta(self):
        self.assertNotEqual(registro.chiave("https://x.it/a?f="), registro.chiave("https://x.it/a"))


class TestQuindiciForme(unittest.TestCase):
    """Le 15 forme note devono risolvere tutte sulla stessa voce pulita."""

    def forme(self, url: str) -> list[str]:
        senza_schema = url.split("://", 1)[1]
        return [
            url,
            url + "/",
            url + "#sezione",
            url + "#",
            url + "?",
            url.replace("https://", "HTTPS://"),
            url.replace("https://coesione", "https://COESIONE"),
            url.replace("/bandi-avvisi", "/Bandi-Avvisi"),
            url.replace("/bandi-avvisi", "/bandi-avvisi/"),
            url + "/#sezione",
            "https://" + senza_schema,
            url.replace("-", "%2D") if "%2D" not in url else url,
            url + "?utm_source=",
            url + "?b=2&a=1",
            url + "?a=1&b=2",
        ]

    def test_tutte_risolvono(self):
        attesa = scraper_config.SCRAPER_CONFIG[URL_ABRUZZO]
        forme = self.forme(URL_ABRUZZO)
        self.assertEqual(len(forme), 15)
        # Le tre forme che aggiungono un parametro di query NON sono la stessa
        # pagina per il registro (una query cambia il contenuto) e restano
        # fuori di proposito. Le altre 12 devono risolvere sulla voce pulita.
        trovate = [f for f in forme if registro.trova(f) is attesa]
        self.assertEqual(len(trovate), 12, [f for f in forme if registro.trova(f) is None])
        for forma in forme[:11]:
            with self.subTest(forma=forma):
                self.assertIs(registro.trova(forma), attesa)

    def test_url_sconosciuto(self):
        self.assertIsNone(registro.trova("https://sconosciuto.example/bandi"))
        self.assertIsNone(registro.trova(""))


class TestIndice(unittest.TestCase):
    def test_costruito_una_volta_sola(self):
        self.assertIs(registro.indice(), registro.indice())

    def test_copre_tutte_le_chiavi_del_registro(self):
        # `assertEqual` e non `assertIs`: le due voci Marche (con e senza
        # frammento) sono due dizionari distinti ma identici, e collassano.
        indice = registro.indice()
        for url, voce in scraper_config.SCRAPER_CONFIG.items():
            with self.subTest(url=url):
                self.assertEqual(indice[registro.chiave(url)], voce)

    def test_nessuna_collisione_fra_voci_diverse(self):
        # Se due chiavi diverse collassassero su configurazioni diverse,
        # `costruisci_indice` solleverebbe: qui si verifica sul registro vero.
        indice = registro.costruisci_indice(scraper_config.SCRAPER_CONFIG)
        self.assertGreaterEqual(len(indice), 100)

    def test_collisione_fra_voci_diverse_solleva(self):
        with self.assertRaises(registro.RegistroCollisioneError):
            registro.costruisci_indice({
                "https://x.it/a": {"strategy": "httpx_bs4"},
                "https://x.it/a/": {"strategy": "csv_parser"},
            })

    def test_indice_degrada_invece_di_spegnere_lo_scrape(self):
        # `indice()` e' memorizzata con lru_cache, che NON memorizza le
        # eccezioni: una voce aggiunta male farebbe fallire lo step scrape su
        # tutte le fonti, a ogni chiamata. Qui la collisione degrada.
        collidono = {
            "https://x.it/a": {"strategy": "httpx_bs4"},
            "https://x.it/a/": {"strategy": "csv_parser"},
        }
        with patch.object(registro, "SCRAPER_CONFIG", collidono):
            registro.indice.cache_clear()
            try:
                indice = registro.indice()
            finally:
                registro.indice.cache_clear()
        self.assertEqual(len(indice), 1)
        # Vince la prima voce, mai una fusione arbitraria.
        self.assertEqual(indice[registro.chiave("https://x.it/a")], {"strategy": "httpx_bs4"})

    def test_costruisci_indice_non_severo_tiene_la_prima(self):
        indice = registro.costruisci_indice(
            {"https://x.it/a": {"strategy": "httpx_bs4"},
             "https://x.it/a/": {"strategy": "csv_parser"}},
            severo=False,
        )
        self.assertEqual(list(indice.values()), [{"strategy": "httpx_bs4"}])

    def test_duplicato_identico_ammesso(self):
        voce = {"strategy": "httpx_bs4"}
        indice = registro.costruisci_indice({"https://x.it/a": voce, "https://x.it/a#b": dict(voce)})
        self.assertEqual(len(indice), 1)

    def test_le_chiavi_uguali_collassano_solo_su_frammento(self):
        # Oggi l'unica coppia che collassa e' Marche con e senza `#Fondo-...`.
        self.assertEqual(
            len(registro.indice()) + 1, len(scraper_config.SCRAPER_CONFIG),
        )


class TestHostRichiedeJs(unittest.TestCase):
    def test_solo_le_voci_esplicite(self):
        # Nessuna voce dichiara ancora `richiede_js`: il ripiego resta legato
        # alla prova a runtime (403/406 o app-shell), che non costa crediti.
        self.assertEqual(registro.host_richiede_js(), frozenset())

    def test_chiave_letta_dal_registro(self):
        originale = dict(scraper_config.SCRAPER_CONFIG)
        scraper_config.SCRAPER_CONFIG["https://WWW.esempio.it:443/bandi"] = {
            "strategy": "firecrawl_scrape", "richiede_js": True,
        }
        try:
            self.assertEqual(registro.host_richiede_js(), frozenset({"esempio.it"}))
        finally:
            scraper_config.SCRAPER_CONFIG.clear()
            scraper_config.SCRAPER_CONFIG.update(originale)


if __name__ == "__main__":
    unittest.main()
