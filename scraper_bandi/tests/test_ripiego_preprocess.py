# -*- coding: utf-8 -*-
"""Il ripiego del preprocess non scarta un bando per un errore passeggero.

Quando la pagina del bando e' troppo corta, il preprocess passa al ripiego
`bando_resolver.resolve_bando`: scarica la pagina della FONTE e chiede a
Sonnet. Fino al 28/09/2026 ogni fallimento del ripiego diventava
`is_valid_bando: False`, e il runner scriveva `rejected`: stato terminale,
nessun codice lo ritenta. Col credito Anthropic esaurito, o con l'host della
fonte giu' per un giorno, un bando vero spariva per sempre (25 righe
«fallback fallito: Firecrawl …» a DB, misurate il 28/09).

Ora un errore passeggero (rete, 5xx, 429, filtro WAF, eccezione del modello)
lascia il bando `scraped` e il giro dopo riprova, come gia' succede quando
fallisce il percorso principale. Una pagina che risponde ma e' vuota, o che non
esiste piu' (404), resta un rifiuto.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_ripiego_preprocess
"""
import unittest
from unittest.mock import patch

import httpx

from tests.supporto import carica_modulo

bando_resolver = carica_modulo("bando_resolver")
runner = carica_modulo("bando_preprocess_runner")
scarico = carica_modulo("scarico")

BANDO = {
    "id": 7,
    "titolo_raw": "Contributi alle imprese per la transizione digitale 2026",
    "descrizione_raw": "",
    "link_bando": None,
    "raw_data": {"ente": "Regione"},
}
FONTE = {"link": "https://www.regione.it/bandi/elenco", "tipo_link": "html"}
TESTO_LUNGO = "Avviso pubblico per contributi alle imprese. " * 20


class _Scarico:
    def __init__(self, risposta=None, errore=None):
        self.risposta, self.errore = risposta, errore
        self.chiesti = []

    async def scarica(self, url, **kwargs):
        self.chiesti.append((url, kwargs))
        if self.errore is not None:
            raise self.errore
        return self.risposta


def _risposta(stato, testo=""):
    return scarico.Risposta(url=FONTE["link"], stato=stato, testo=testo)


class RipiegoDelResolver(unittest.IsolatedAsyncioTestCase):

    async def _risolvi(self, finto, *, modello=None):
        async def _modello_fallito(*args, **kwargs):
            raise RuntimeError("Your credit balance is too low")

        with patch.object(scarico, "scarico_corrente", lambda: finto), \
                patch.object(bando_resolver, "_get_anthropic_client", lambda: object()), \
                patch.object(bando_resolver, "_call_anthropic_resolver",
                             modello or _modello_fallito):
            return await bando_resolver.resolve_bando(dict(BANDO), dict(FONTE))

    async def test_redirect_infiniti_e_url_non_valida_sono_un_rifiuto(self):
        for errore in (httpx.TooManyRedirects("troppi redirect"), httpx.InvalidURL("url")):
            with self.subTest(errore=type(errore).__name__):
                esito = await self._risolvi(_Scarico(errore=errore))
                self.assertFalse(esito.get("_errore_transitorio"))
                self.assertFalse(esito["is_valid_bando"])
                self.assertTrue(esito["rejection_reason"].startswith("fallback fallito:"))

    async def test_altre_eccezioni_dello_scarico_sono_un_rinvio(self):
        # Un corpo gzip corrotto da un CDN, un errore imprevisto: nel dubbio
        # si riprova, un rejected non torna indietro.
        for errore in (httpx.DecodingError("gzip"), RuntimeError("imprevisto")):
            with self.subTest(errore=type(errore).__name__):
                esito = await self._risolvi(_Scarico(errore=errore))
                self.assertTrue(esito.get("_errore_transitorio"))

    async def test_ripiego_firecrawl_fallito_e_un_errore_passeggero(self):
        risposta = scarico.Risposta(url=FONTE["link"], stato=200, testo="app", ripiego_fallito=True)
        esito = await self._risolvi(_Scarico(risposta))
        self.assertTrue(esito.get("_errore_transitorio"))

    async def test_ripiego_fallito_ma_testo_sufficiente_si_usa_il_testo(self):
        # Il ripiego non serviva a niente: il testo di httpx basta, si va avanti.
        risposta = scarico.Risposta(url=FONTE["link"], stato=200, testo=TESTO_LUNGO,
                                    ripiego_fallito=True)
        finto = _Scarico(risposta)
        chiamato = []

        async def modello(*args, **kwargs):
            chiamato.append(1)
            raise RuntimeError("fine della prova")

        await self._risolvi(finto, modello=modello)
        self.assertEqual(chiamato, [1])

    async def test_un_bando_vecchio_resta_in_attesa(self):
        # Nessun limite d'eta': dopo giorni senza credito un solo guasto della
        # fonte scarterebbe per sempre un bando vero. Lo segnala l'allarme
        # sull'ingresso fermo, non lo decide un orologio.
        vecchio = dict(BANDO, created_at="2026-07-01T10:00:00+00:00")
        with patch.object(scarico, "scarico_corrente", lambda: _Scarico(_risposta(503))):
            esito = await bando_resolver.resolve_bando(vecchio, dict(FONTE))
        self.assertTrue(esito.get("_errore_transitorio"))

    async def test_stati_passeggeri(self):
        for stato in (None, 403, 406, 429, 500, 502, 503):
            with self.subTest(stato=stato):
                esito = await self._risolvi(_Scarico(_risposta(stato)))
                self.assertTrue(esito.get("_errore_transitorio"), stato)

    async def test_pagina_sparita_resta_un_rifiuto(self):
        for stato in (404, 410):
            with self.subTest(stato=stato):
                esito = await self._risolvi(_Scarico(_risposta(stato)))
                self.assertFalse(esito.get("_errore_transitorio"))
                self.assertFalse(esito["is_valid_bando"])
                self.assertTrue(esito["rejection_reason"].startswith("fallback fallito:"))

    async def test_pagina_vuota_resta_un_rifiuto(self):
        esito = await self._risolvi(_Scarico(_risposta(200, "poco testo")))
        self.assertFalse(esito.get("_errore_transitorio"))
        self.assertFalse(esito["is_valid_bando"])

    async def test_modello_fallito_e_un_errore_passeggero(self):
        finto = _Scarico(_risposta(200, TESTO_LUNGO))
        esito = await self._risolvi(finto)
        self.assertTrue(esito.get("_errore_transitorio"))
        # La fonte si scarica come pagina principale: il ripiego Firecrawl resta
        # disponibile come prima.
        self.assertTrue(finto.chiesti[0][1].get("principale"))


class RunnerDelPreprocess(unittest.IsolatedAsyncioTestCase):
    """Il runner non scrive niente per un bando in errore passeggero."""

    async def _giro(self, analisi_ripiego):
        scritti = []

        async def analizza(bando, fonte):
            return {"_needs_fallback": True}

        async def ripiego(bando, fonte):
            return dict(analisi_ripiego)

        async def aggiorna(righe):
            scritti.extend(righe)
            return {"updated": len(righe), "failed": 0}

        with patch.object(runner, "select_bandi_scraped", lambda limit=None: [dict(BANDO, fonte_id=3)]), \
                patch.object(runner, "select_fonti_by_ids", lambda ids: {3: dict(FONTE)}), \
                patch.object(runner, "enrich_fonti_with_names", lambda f: f), \
                patch.object(runner, "analyze_bando", analizza), \
                patch.object(runner, "resolve_bando", ripiego), \
                patch.object(runner, "update_bandi_postanalysis", aggiorna):
            contatori = await runner.run()
        return contatori, scritti

    async def test_errore_passeggero_lascia_il_bando_scraped(self):
        contatori, scritti = await self._giro({
            "is_valid_bando": False, "confidence_score": 0.0,
            "rejection_reason": "fallback rinviato: Sonnet API error",
            "_fallback_used": True, "_fallback_failed": True, "_errore_transitorio": True,
        })
        self.assertEqual(scritti, [], "un errore passeggero non deve diventare rejected")
        self.assertEqual(contatori["rejected"], 0)
        self.assertEqual(contatori["errors"], 1)
        self.assertEqual(contatori["fallback_rinviati"], 1)

    async def test_rifiuto_vero_si_scrive_ancora(self):
        contatori, scritti = await self._giro({
            "is_valid_bando": False, "confidence_score": 0.0,
            "rejection_reason": "fallback fallito: Firecrawl fonte vuoto/non raggiungibile",
            "stato_bando": None, "_fallback_used": True, "_fallback_failed": True,
        })
        self.assertEqual(len(scritti), 1)
        self.assertEqual(scritti[0]["stato_processing"], "rejected")
        self.assertEqual(contatori["fallback_rinviati"], 0)


if __name__ == "__main__":
    unittest.main()
