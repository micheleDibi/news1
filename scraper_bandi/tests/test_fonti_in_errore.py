# -*- coding: utf-8 -*-
"""`bando_runner`: il contatore `fonti_in_errore` (contratto `bandi-giro-2` §8).

`fonti_errors` dice quante fonti sono andate in errore; `fonti_in_errore` dice
quali, con i soli `fonte_id` interi, riempita negli stessi tre punti
(`get_scraper`, `scrape`, `upsert`). E' da li' che `salute` vede una fonte ad
accesso riservato (Obiettivo Europa) in errore due giri di fila.

DB, registro e scraper sono mock: nessuna rete, nessuna scrittura.
"""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

bando_runner = carica_modulo("bando_runner")
registro = carica_modulo("registro")
telemetria = carica_modulo("telemetria")


def _item(fonte):
    return bando_runner.BandoItem(
        fonte_id=fonte["id"], tipo_link="Opportunità", link_bando=f"{fonte['link']}/bando-1",
        titolo_raw="Avviso pubblico formazione", descrizione_raw=None, raw_data=None,
    )


class _Scraper:
    """Un bando per fonte; `scrape` fallisce sulle fonti indicate."""
    name = "finto"

    def __init__(self, fallisce=()):
        self._fallisce = set(fallisce)

    async def scrape(self, fonte):
        if fonte["id"] in self._fallisce:
            raise RuntimeError("pagina giu'")
        return [_item(fonte)]


class TestFontiInErrore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fonti = [
            {"id": 449, "link": "https://oe.example.it/a", "tipo_link": "Opportunità"},
            {"id": 2, "link": "https://b.example.it", "tipo_link": "Opportunità"},
            {"id": 3, "link": "https://c.example.it", "tipo_link": "Opportunità"},
        ]
        self.config = {f["link"]: {"strategy": "finta"} for f in self.fonti}
        self.upsert = MagicMock(return_value={"processed": 1, "dedup_collisions": 0})
        self.get_scraper = MagicMock(return_value=_Scraper())
        self.select = MagicMock(side_effect=lambda: list(self.fonti))
        patches = [
            patch.dict(bando_runner.SCRAPER_CONFIG, self.config, clear=True),
            patch.object(bando_runner, "get_scraper", self.get_scraper),
            patch.object(bando_runner, "select_fonti_ready", self.select),
            patch.object(bando_runner, "upsert_bandi", self.upsert),
            patch.object(bando_runner, "logger", MagicMock()),
            patch.object(bando_runner, "leggi_esistenti", MagicMock(return_value={})),
            patch.object(bando_runner, "scrivi_segnali", MagicMock(return_value=0)),
            patch.object(bando_runner, "aggiorna_controlli", MagicMock(return_value=0)),
            patch.object(bando_runner, "conteggi_da_fonte_run", MagicMock(return_value={})),
            patch.object(bando_runner, "_telemetria_fonte", MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Stessa accortezza di test_bando_runner_record: l'indice del registro
        # e' in cache, e quello costruito col registro finto non deve restare.
        registro.indice.cache_clear()
        self.addCleanup(registro.indice.cache_clear)

    async def test_giro_pulito_lista_vuota(self):
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_errors"], 0)
        self.assertEqual(counters["fonti_in_errore"], [])
        self.assertEqual(counters["fonti_processate"], 3)

    async def test_get_scraper_fallito(self):
        def get_scraper(nome, **_):
            if self.get_scraper.call_count == 1:
                raise ValueError("strategia sconosciuta")
            return _Scraper()
        self.get_scraper.side_effect = get_scraper
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_errors"], 1)
        self.assertEqual(counters["fonti_in_errore"], [449])

    async def test_scrape_fallito(self):
        self.get_scraper.return_value = _Scraper(fallisce={2})
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_errors"], 1)
        self.assertEqual(counters["fonti_in_errore"], [2])
        self.assertEqual(counters["fonti_processate"], 2)

    async def test_upsert_fallito(self):
        def upsert(righe):
            if righe[0]["fonte_id"] == 3:
                raise ConnectionError("503")
            return {"processed": len(righe), "dedup_collisions": 0}
        self.upsert.side_effect = upsert
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_errors"], 1)
        self.assertEqual(counters["fonti_in_errore"], [3])

    async def test_tutti_e_tre_i_punti_nello_stesso_giro(self):
        self.get_scraper.side_effect = lambda nome, **_: (
            (_ for _ in ()).throw(ValueError("x")) if self.get_scraper.call_count == 1
            else _Scraper(fallisce={2}))
        self.upsert.side_effect = ConnectionError("503")
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_errors"], 3)
        self.assertEqual(counters["fonti_in_errore"], [449, 2, 3])
        # Le fonti tentate sono processate + in errore (misure del giro 2, M6).
        self.assertEqual(counters["fonti_processate"], 0)

    async def test_solo_gli_id_interi(self):
        self.fonti = [
            {"id": "7", "link": "https://d.example.it", "tipo_link": "Opportunità"},
            {"id": True, "link": "https://e.example.it", "tipo_link": "Opportunità"},
            {"id": 8, "link": "https://f.example.it", "tipo_link": "Opportunità"},
        ]
        self.config.clear()
        self.config.update({f["link"]: {"strategy": "finta"} for f in self.fonti})
        with patch.dict(bando_runner.SCRAPER_CONFIG, self.config, clear=True):
            registro.indice.cache_clear()
            self.get_scraper.return_value = _Scraper(fallisce={"7", True, 8})
            counters = await bando_runner.run()
        # Il conteggio resta quello di sempre; la lista porta solo gli interi.
        self.assertEqual(counters["fonti_errors"], 3)
        self.assertEqual(counters["fonti_in_errore"], [8])

    async def test_dry_run_non_scrive_e_non_conta_upsert(self):
        self.upsert.side_effect = ConnectionError("503")
        counters = await bando_runner.run(dry_run=True)
        self.upsert.assert_not_called()
        self.assertEqual(counters["fonti_in_errore"], [])

    async def test_la_lista_arriva_a_salute(self):
        # Dal runner al jsonb della riga `pipeline` e da li' a `salute`: una
        # fonte OE in errore in due giri di fila e' un allarme.
        self.get_scraper.return_value = _Scraper(fallisce={449})
        counters = json.loads(json.dumps(await bando_runner.run()))
        righe = tuple(
            {"id": i, "giro": giro, "esito": "ok", "avviato_at": avvio,
             "concluso_at": avvio, "contatori": {"scrape": counters}}
            for i, giro, avvio in ((2, "12:00", "2026-10-01T10:00:00+00:00"),
                                   (1, "06:00", "2026-10-01T04:00:00+00:00"))
        )
        esito = telemetria.salute(
            telemetria.Stato(ultime_pipeline=righe),
            adesso=datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc))
        self.assertIn("accesso_fonte_riservata", [v.codice for v in esito.voci])


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
