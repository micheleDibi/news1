"""`http.indirizzo_pubblico` (giro 3, contratto §18.6): niente richieste verso
loopback, reti private, link-local, multicast o indirizzi non pubblici.

Il DNS e' sostituito da `risolvi=`: nessun test va in rete.
"""
from __future__ import annotations

import unittest

from tests.supporto import carica_modulo

http = carica_modulo("http")


def _dns(tabella):
    def risolvi(host):
        if host not in tabella:
            raise OSError("nome sconosciuto")
        return tabella[host]
    return risolvi


class IpPubblico(unittest.TestCase):
    def test_pubblici(self):
        for ip in ("8.8.8.8", "151.101.1.69", "2a00:1450:4002:80a::200e"):
            self.assertTrue(http.ip_pubblico(ip), ip)

    def test_interni_e_non_pubblici(self):
        for ip in ("127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
                   "100.64.0.1", "0.0.0.0", "224.0.0.1", "239.255.255.250", "240.0.0.1",
                   "255.255.255.255", "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1",
                   "ff02::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "192.0.2.10",
                   "fe80::1%en0", "non-un-ip"):
            self.assertFalse(http.ip_pubblico(ip), ip)


class IndirizzoPubblico(unittest.TestCase):
    # `staticmethod`: una funzione come attributo di classe diventerebbe un
    # metodo legato, e il DNS finto riceverebbe `self` come host.
    DNS = staticmethod(_dns({
        "www.regione.marche.it": ["151.101.1.69"],
        "interno.ente.it": ["10.1.2.3"],
        "misto.ente.it": ["151.101.1.69", "127.0.0.1"],
        "localhost": ["127.0.0.1", "::1"],
        "vuoto.ente.it": [],
    }))

    def ok(self, url):
        return http.indirizzo_pubblico(url, risolvi=self.DNS)

    def test_host_pubblico(self):
        self.assertTrue(self.ok("https://www.regione.marche.it/bandi?id=3"))
        self.assertTrue(self.ok("http://www.regione.marche.it./bando.pdf"))

    def test_host_che_risolve_a_rete_interna(self):
        self.assertFalse(self.ok("https://interno.ente.it/x"))
        self.assertFalse(self.ok("http://localhost:8000/summarize_news"))

    def test_basta_un_indirizzo_interno(self):
        self.assertFalse(self.ok("https://misto.ente.it/"))

    def test_dns_fallito_o_vuoto(self):
        self.assertFalse(self.ok("https://inesistente.example/"))
        self.assertFalse(self.ok("https://vuoto.ente.it/"))

    def test_ip_scritto_nell_url_senza_dns(self):
        def mai(_host):
            raise AssertionError("un IP letterale non passa dal DNS")

        self.assertFalse(http.indirizzo_pubblico("http://127.0.0.1:8000/", risolvi=mai))
        self.assertFalse(http.indirizzo_pubblico("http://169.254.169.254/latest/", risolvi=mai))
        self.assertFalse(http.indirizzo_pubblico("http://[::1]/", risolvi=mai))
        self.assertFalse(http.indirizzo_pubblico("http://[::ffff:7f00:1]/", risolvi=mai))
        self.assertTrue(http.indirizzo_pubblico("https://8.8.8.8/", risolvi=mai))

    def test_schemi_e_url_malformati(self):
        for url in ("file:///etc/passwd", "ftp://www.regione.marche.it/x",
                    "gopher://www.regione.marche.it/", "www.regione.marche.it/x", "",
                    None, "https://", "http://[::1/", "javascript:alert(1)"):
            self.assertFalse(self.ok(url), url)

    def test_credenziali_nell_url_non_ingannano(self):
        # L'host vero e' dopo la @.
        self.assertFalse(self.ok("http://www.regione.marche.it@localhost/"))
        self.assertTrue(self.ok("http://utente@www.regione.marche.it/"))


class Classifica(unittest.TestCase):
    """I tre esiti: il DNS giu' non e' un giudizio sull'URL."""

    DNS = staticmethod(_dns({"pubblico.it": ["8.8.8.8"], "interno.it": ["10.0.0.1"],
                             "vuoto.it": []}))

    def test_tre_esiti(self):
        c = lambda u: http.classifica_indirizzo(u, risolvi=self.DNS)  # noqa: E731
        self.assertEqual(c("https://pubblico.it/a"), http.PUBBLICO)
        self.assertEqual(c("https://interno.it/a"), http.RIFIUTATO)
        self.assertEqual(c("http://127.0.0.1/"), http.RIFIUTATO)
        self.assertEqual(c("ftp://pubblico.it/a"), http.RIFIUTATO)
        self.assertEqual(c("https://nessuno.it/a"), http.IRRISOLTO)
        self.assertEqual(c("https://vuoto.it/a"), http.IRRISOLTO)


class CacheDns(unittest.TestCase):
    def setUp(self):
        http._DNS_RECENTI.clear()
        self.addCleanup(http._DNS_RECENTI.clear)

    def test_le_risoluzioni_riuscite_si_ricordano_i_fallimenti_no(self):
        from unittest.mock import patch
        chiamate = []

        def getaddrinfo(host, *_a, **_k):
            chiamate.append(host)
            if host == "giu.it":
                raise OSError("DNS giu'")
            return [(None, None, None, "", ("8.8.8.8", 0))]

        with patch.object(http.socket, "getaddrinfo", getaddrinfo):
            self.assertTrue(http.indirizzo_pubblico("https://ente.it/a"))
            self.assertTrue(http.indirizzo_pubblico("https://ente.it/b"))
            self.assertFalse(http.indirizzo_pubblico("https://giu.it/a"))
            self.assertFalse(http.indirizzo_pubblico("https://giu.it/a"))
        self.assertEqual(chiamate, ["ente.it", "giu.it", "giu.it"])


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
