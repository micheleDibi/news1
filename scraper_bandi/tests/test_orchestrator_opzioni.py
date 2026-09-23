# -*- coding: utf-8 -*-
"""`orchestrator.run(dry_run, limit)` (fix 19/28): con dry_run niente
`upsert_fonti` ne' `mark_deprecated` (ma i contatori restano calcolati);
`limit` tronca le fonti scoperte prima della reachability e salta sempre il
mark deprecated (l'elenco e' parziale); `run()` senza argomenti scrive come
prima. Pagina, reachability e DB sono mock: nessuna rete, nessuna scrittura."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.supporto import carica_modulo

orchestrator = carica_modulo("orchestrator")
FonteCandidate = orchestrator.FonteCandidate

LINK_A = "https://a.example.it/bandi"
LINK_B = "https://b.example.it/bandi"
LINK_C = "https://c.example.it/bandi"
LINK_VECCHIO = "https://vecchia.example.it/bandi"   # in DB ma non piu' in pagina


def _candidato(link: str) -> FonteCandidate:
    return FonteCandidate(
        link=link, categoria_programma_id=1, tipologia_programma_id=None,
        tipo_link="Opportunità", program_name=None, section_name=None,
    )


def _reachability(urls):
    # Tutte attive tranne C: cosi' i counters distinguono anche connection_error.
    return [SimpleNamespace(url=u, attivo=(u != LINK_C), formato_link="HTML") for u in urls]


class TestOrchestratorOpzioni(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.candidati = [_candidato(LINK_A), _candidato(LINK_B), _candidato(LINK_C)]
        self.check_many = AsyncMock(side_effect=_reachability)
        self.upsert = MagicMock(return_value={"processed": 3, "dedup_collisions": 0})
        self.mark_deprecated = MagicMock(return_value=1)
        self.log = MagicMock()
        patches = [
            patch.object(orchestrator, "fetch_page", AsyncMock(return_value="<html></html>")),
            patch.object(orchestrator, "parse_page", MagicMock(return_value=list(self.candidati))),
            patch.object(orchestrator, "check_many", self.check_many),
            patch.object(orchestrator, "select_known_links", MagicMock(return_value={LINK_A, LINK_VECCHIO})),
            patch.object(orchestrator, "upsert_fonti", self.upsert),
            patch.object(orchestrator, "mark_deprecated", self.mark_deprecated),
            patch.object(orchestrator, "logger", self.log),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_default_scrive_come_prima(self):
        counters = await orchestrator.run()
        self.upsert.assert_called_once()
        self.assertEqual([r["link"] for r in self.upsert.call_args.args[0]], [LINK_A, LINK_B, LINK_C])
        self.mark_deprecated.assert_called_once_with({LINK_A, LINK_B, LINK_C})
        self.assertEqual(counters, {
            "discovered": 3, "new": 2, "updated": 1, "deprecated": 1, "connection_error": 1,
        })

    async def test_dry_run_non_scrive_ma_conta(self):
        counters = await orchestrator.run(dry_run=True)
        self.upsert.assert_not_called()
        self.mark_deprecated.assert_not_called()
        self.assertEqual(counters, {
            "discovered": 3, "new": 2, "updated": 1, "deprecated": 0, "connection_error": 1,
        })

    async def test_dry_run_logga_cosa_farebbe(self):
        await orchestrator.run(dry_run=True)
        messaggi = [str(c.args[0]) for c in self.log.info.call_args_list]
        self.assertTrue(any("upsert_fonti saltato" in m for m in messaggi))
        self.assertTrue(any("mark_deprecated saltato" in m for m in messaggi))

    async def test_limit_tronca_le_fonti_scoperte_prima_della_reachability(self):
        counters = await orchestrator.run(limit=2)
        self.check_many.assert_awaited_once_with([LINK_A, LINK_B])
        self.upsert.assert_called_once()
        self.assertEqual([r["link"] for r in self.upsert.call_args.args[0]], [LINK_A, LINK_B])
        self.assertEqual(counters["discovered"], 2)
        self.assertEqual(counters["connection_error"], 0)

    async def test_limit_salta_sempre_il_mark_deprecated(self):
        counters = await orchestrator.run(limit=2)
        self.mark_deprecated.assert_not_called()
        self.assertEqual(counters["deprecated"], 0)
        self.log.warning.assert_called_once()

    async def test_limit_zero(self):
        counters = await orchestrator.run(limit=0)
        self.check_many.assert_awaited_once_with([])
        self.mark_deprecated.assert_not_called()
        self.assertEqual(counters["discovered"], 0)

    async def test_dry_run_e_limit_insieme(self):
        counters = await orchestrator.run(dry_run=True, limit=1)
        self.upsert.assert_not_called()
        self.mark_deprecated.assert_not_called()
        self.assertEqual((counters["discovered"], counters["new"], counters["updated"]), (1, 0, 1))

    async def test_nessun_candidato_resta_un_errore_senza_scritture(self):
        orchestrator.parse_page.return_value = []
        for kwargs in ({}, {"dry_run": True}, {"limit": 5}):
            with self.subTest(kwargs=kwargs):
                counters = await orchestrator.run(**kwargs)
                self.assertEqual(counters["discovered"], 0)
        self.upsert.assert_not_called()
        self.mark_deprecated.assert_not_called()
        self.check_many.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
