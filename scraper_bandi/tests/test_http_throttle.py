# -*- coding: utf-8 -*-
"""Il freno per host di `http._wait_for_host` fra coroutine parallele.

Giro 3 (contratto `bandi-giro-3` §7): i ricontrolli lavorano fino a 5 bandi in
parallelo e la cortesia verso gli enti la garantisce questo freno condiviso.
Prima lo slot si scriveva DOPO il sonno: due coroutine entrate mentre una
terza dormiva leggevano lo stesso «ultimo» e partivano insieme. Il tempo qui e'
finto (orologio e sonno sostituiti), cosi' il test e' esatto e istantaneo.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_http_throttle
"""
import asyncio
import unittest
from unittest.mock import patch

from tests.supporto import carica_modulo

http = carica_modulo("http")


class _Orologio:
    """Tempo fermo e sonno finto: `sleep` registra quanto si dorme e cede il
    turno alle altre coroutine, come farebbe quello vero. La partenza di una
    richiesta e' quindi `adesso + attesa`: un valore esatto, senza aspettare."""

    def __init__(self):
        self.adesso = 1000.0
        self.attese: list[float] = []

    def monotonic(self):
        return self.adesso

    async def sleep(self, secondi):
        self.attese.append(round(secondi, 6))
        await _sleep_vero(0)
        await _sleep_vero(0)


_sleep_vero = asyncio.sleep


class TestFrenoFraCoroutine(unittest.TestCase):
    def setUp(self):
        self.orologio = _Orologio()
        http._HOST_LAST_REQUEST.clear()
        self.addCleanup(http._HOST_LAST_REQUEST.clear)

    def _esegui(self, *host, ritardo=1.0):
        async def tutte():
            await asyncio.gather(*(http._wait_for_host(h) for h in host))

        with patch.object(http, "_throttle_delay_s", return_value=ritardo), \
                patch.object(http.time, "monotonic", self.orologio.monotonic), \
                patch.object(http.asyncio, "sleep", self.orologio.sleep):
            asyncio.run(tutte())

    def test_tre_coroutine_sullo_stesso_host_partono_a_un_secondo(self):
        # Prima della correzione la seconda e la terza dormivano entrambe 1 s
        # (avevano letto lo stesso «ultimo») e partivano insieme.
        self._esegui("ente.it", "ente.it", "ente.it")
        self.assertEqual(sorted(self.orologio.attese), [1.0, 2.0])
        self.assertEqual(http._HOST_LAST_REQUEST["ente.it"], 1002.0)

    def test_cinque_lavori_paralleli_restano_in_fila(self):
        self._esegui(*(["obiettivoeuropa.com"] * 5))
        self.assertEqual(sorted(self.orologio.attese), [1.0, 2.0, 3.0, 4.0])

    def test_host_diversi_non_si_aspettano(self):
        self._esegui("a.it", "b.it", "c.it")
        self.assertEqual(self.orologio.attese, [])

    def test_dopo_l_intervallo_non_si_aspetta(self):
        self._esegui("ente.it")
        self.orologio.adesso += 5.0
        self._esegui("ente.it")
        self.assertEqual(self.orologio.attese, [])

    def test_dentro_l_intervallo_si_aspetta_il_resto(self):
        self._esegui("ente.it")
        self.orologio.adesso += 0.25
        self._esegui("ente.it")
        self.assertEqual(self.orologio.attese, [0.75])

    def test_senza_freno_nessuna_attesa(self):
        self._esegui("ente.it", "ente.it", ritardo=0.0)
        self.assertEqual(self.orologio.attese, [])
        self.assertNotIn("ente.it", http._HOST_LAST_REQUEST)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
