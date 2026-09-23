# -*- coding: utf-8 -*-
"""Che cosa di `archivia-processed` finisce in `pipeline_run.contatori`.

Il riepilogo del lotto L8 porta `ids_lavorabili`: l'elenco degli id che
restano da lavorare a `risolvi-fonte`/`enrich`/`seo`. Serve a chi legge il log
— dire «150» senza dire quali non basta a nessuno — ma **non** e' un contatore:
il `--limit` non lo tocca (le righe lavorabili non consumano un'archiviazione)
e la scansione le raccoglie tutte, quindi cresce con il corpus. Finche' e'
entrato nel jsonb della telemetria, ogni giro ne scriveva una copia dentro
`pipeline_run`.

Nessuna rete, nessun DB: righe e archiviazione sono iniettate, `_scrivi_run` e'
una spia.
"""
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

backfill = carica_modulo("backfill")

OGGI = date(2026, 9, 23)


def _processed(**extra):
    riga = {
        "id": 700,
        "stato_processing": "processed",
        "stato_bando": "chiuso",
        "data_scadenza": "2026-08-01",
        "fonte_ufficiale_stato": "trovata",
        "pubblicato": False,
    }
    riga.update(extra)
    return riga


class TestIdsLavorabiliFuoriDallaTelemetria(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.spia = MagicMock()
        zitto = patch.object(backfill, "_scrivi_run", self.spia)
        zitto.start()
        self.addCleanup(zitto.stop)

    async def _giro(self, quanti_lavorabili: int):
        righe = [
            # Chiusa da poco e con la fonte trovata: va in lavorazione, non
            # nell'archivio, e non consuma nessun `--limit`.
            _processed(id=i) for i in range(1, quanti_lavorabili + 1)
        ]
        righe.append(_processed(id=900, data_scadenza="2026-01-10"))  # archiviabile
        return await backfill.run_archivia_processed(
            righe=righe, oggi=OGGI, archivia=lambda i: {"scritto": True})

    async def test_il_riepilogo_di_ritorno_elenca_ancora_gli_id(self):
        esito = await self._giro(3)
        self.assertEqual(esito["ids_lavorabili"], [1, 2, 3])
        self.assertEqual(esito["lavorabili"], 3)

    async def test_la_riga_di_pipeline_run_porta_il_numero_non_l_elenco(self):
        await self._giro(3)
        contatori = self.spia.call_args.args[1]
        self.assertNotIn("ids_lavorabili", contatori)
        # Il numero resta: e' cio' che serve a chi legge `pipeline_run` per
        # sapere quanto residuo c'e' ancora, ed e' un intero.
        self.assertEqual(contatori["lavorabili"], 3)
        self.assertEqual(contatori["archiviabili"], 1)

    async def test_il_jsonb_non_cresce_con_il_corpus(self):
        # La prova del difetto: con dieci volte le righe lavorabili la riga di
        # telemetria deve restare identica, chiave per chiave.
        await self._giro(3)
        piccolo = dict(self.spia.call_args.args[1])
        self.spia.reset_mock()
        await self._giro(30)
        grande = dict(self.spia.call_args.args[1])
        self.assertEqual(set(piccolo), set(grande))
        self.assertEqual(grande["lavorabili"], 30)
        self.assertTrue(
            all(isinstance(v, (int, float, str, bool)) or v is None
                for v in grande.values()),
            grande,
        )


if __name__ == "__main__":
    unittest.main()
