# -*- coding: utf-8 -*-
"""app/logger.py: redazione dei segreti, cartella e livello da variabili d'ambiente.

Il modulo reale viene caricato per percorso (tests/supporto.py lo sostituisce
con uno stub per tutti gli altri test) con SCRAPER_BANDI_LOG_DIR puntato a una
cartella temporanea sotto tests/fixture/ e stderr rediretto su un buffer:
  - l'import non crea nulla (ne' in scraper_bandi/logs ne' nella temporanea);
  - il primo messaggio crea il file nella cartella temporanea;
  - stderr rispetta SCRAPER_BANDI_LOG_LEVEL, il file resta a DEBUG;
  - i segreti sono redatti su ENTRAMBI i sink.
Alla fine i sink del modulo vengono rimossi e lo stub ripristinato.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loguru import logger

from tests.supporto import APP, RADICE, carica_modulo, carica_per_percorso

LOGS_REALE = RADICE / "logs"
FIXTURE = RADICE / "tests" / "fixture"

SEGRETI = {
    "sessionid=abc123XYZ": "sessionid=[REDATTO]",
    "csrfmiddlewaretoken=Tok3nCSRF": "csrfmiddlewaretoken=[REDATTO]",
    "csrftoken=Tok3nCookie": "csrftoken=[REDATTO]",
    "Authorization: Bearer eyJhbGciOi.payload.firma": "Authorization: Bearer [REDATTO]",
    "password=hunter2": "password=[REDATTO]",
}


def _impronta(cartella: Path) -> dict[str, int]:
    if not cartella.exists():
        return {}
    return {p.name: p.stat().st_size for p in cartella.iterdir()}


class TestRedigi(unittest.TestCase):
    """Funzione pura: i pattern vengono redatti, il resto no."""

    @classmethod
    def setUpClass(cls):
        cls.buffer = io.StringIO()
        cls.temp = Path(tempfile.mkdtemp(prefix="log-", dir=_fixture()))
        ambiente = {"SCRAPER_BANDI_LOG_DIR": str(cls.temp), "SCRAPER_BANDI_LOG_LEVEL": "INFO"}
        cls.impronta_logs_prima = _impronta(LOGS_REALE)
        with patch.dict(os.environ, ambiente), contextlib.redirect_stderr(cls.buffer):
            cls.mod = carica_per_percorso("logger_reale_test", APP / "logger.py")

    @classmethod
    def tearDownClass(cls):
        logger.remove()
        logger.configure(patcher=lambda record: None)
        logger.add(sys.stderr, level=os.environ.get("SCRAPER_BANDI_TEST_LOG", "WARNING"))
        shutil.rmtree(cls.temp, ignore_errors=True)
        with contextlib.suppress(OSError):
            FIXTURE.rmdir()  # solo se vuota

    def test_pattern_redatti(self):
        for grezzo, atteso in SEGRETI.items():
            self.assertEqual(self.mod.redigi(f"prima {grezzo} dopo"), f"prima {atteso} dopo")

    def test_varianti_di_separatore_e_apici(self):
        redigi = self.mod.redigi
        self.assertEqual(redigi("Cookie: csrftoken=aaa; sessionid=bbb"),
                         "Cookie: csrftoken=[REDATTO]; sessionid=[REDATTO]")
        self.assertEqual(redigi("{'password': 'hunter2', 'login': 'x'}"),
                         "{'password': '[REDATTO]', 'login': 'x'}")
        self.assertEqual(redigi('{"sessionid": "abc"}'), '{"sessionid": "[REDATTO]"}')
        self.assertEqual(redigi('{"Authorization": "Bearer abc"}'),
                         '{"Authorization": "Bearer [REDATTO]"}')
        self.assertEqual(redigi("url=https://x.invalid/?sessionid=abc&page=1"),
                         "url=https://x.invalid/?sessionid=[REDATTO]&page=1")
        self.assertEqual(redigi("SESSIONID=abc"), "SESSIONID=[REDATTO]")
        self.assertEqual(redigi("authorization: bearer abc"), "authorization: bearer [REDATTO]")
        self.assertEqual(redigi("Authorization=Basic dXNlcjpwYXNz"), "Authorization=Basic [REDATTO]")

    def test_idempotente(self):
        redatto = self.mod.redigi("sessionid=abc password=x Authorization: Bearer y")
        self.assertEqual(self.mod.redigi(redatto), redatto)

    def test_il_resto_non_viene_toccato(self):
        intatti = [
            "[json_api_paginated] fonte_id=449 page=1 url=https://www.obiettivoeuropa.com/api/call/?page=1",
            "login OK | sessionid acquisito",
            "il campo password e' obbligatorio",
            # Non-regressione: i numeri di configurazione non sono segreti e
            # un log che li nasconde non serve piu' a niente.
            "max_tokens=4096",
            "preprocess_max_tokens: 8192, seo_concurrency=3",
            "timeout_s=30 retry=2",
            "Authorization header assente",
            "csrf token non trovato",
            "",
        ]
        for testo in intatti:
            self.assertEqual(self.mod.redigi(testo), testo)

    def test_i_nomi_veri_di_questo_repo(self):
        # Il `\b` di prima non scattava dopo un underscore: nessuno di questi
        # veniva redatto, benche' il docstring lo dichiarasse.
        casi = [
            ("obiettivo_europa_password=SegretoFinto1", "SegretoFinto1"),
            ("SUPABASE_SERVICE_KEY_BANDI: 'finta-chiave'", "finta-chiave"),
            ("anthropic_api_key=sk-ant-finta", "sk-ant-finta"),
            ("firecrawl_api_key='fc-finta'", "fc-finta"),
            ("indexnow_api_key=abcdef", "abcdef"),
            ("{'apikey': 'jwt.finto.qui'}", "jwt.finto.qui"),
            ("x-api-key: 12345", "12345"),
            ("access_token=AAA refresh_token=BBB", "AAA"),
        ]
        for testo, segreto in casi:
            with self.subTest(testo=testo):
                redatto = self.mod.redigi(testo)
                self.assertNotIn(segreto, redatto)
                self.assertIn(self.mod.REDATTO, redatto)

    def test_sovra_redazione_accettata(self):
        # `passwords=3` e' un conteggio, non un segreto: si perde comunque.
        # E' il prezzo del suffisso libero, e si paga volentieri per non
        # perdere `obiettivo_europa_password`.
        self.assertEqual(self.mod.redigi("passwords=3 utenti"),
                         "passwords=[REDATTO] utenti")

    def test_i_sink_non_stampano_le_variabili_dei_frame(self):
        # `diagnose=True` stampa sotto ogni riga del traceback il repr delle
        # variabili del frame, e il patcher lavora su `record['message']`:
        # quell'annotazione non passa dalla redazione.
        righe = [r.strip() for r in (APP / "logger.py").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual(righe.count("diagnose=False,"), 2)
        self.assertNotIn("diagnose=True,", righe)

    def test_settings_non_stampa_le_chiavi(self):
        settings = carica_modulo("settings")
        finto = settings.get_settings()
        testo = repr(finto)
        for campo in settings.CAMPI_SEGRETI:
            valore = getattr(finto, campo)
            if valore:
                with self.subTest(campo=campo):
                    self.assertNotIn(valore, testo)
        # Il resto resta leggibile: il repr serve a diagnosticare.
        self.assertIn("supabase_url=", testo)

    def test_cartella_e_livello_da_ambiente(self):
        mod = self.mod
        with patch.dict(os.environ, {"SCRAPER_BANDI_LOG_DIR": "", "SCRAPER_BANDI_LOG_LEVEL": ""}):
            self.assertEqual(mod.cartella_log(), LOGS_REALE)
            self.assertEqual(mod.livello_stderr(), "INFO")
        with patch.dict(os.environ, {"SCRAPER_BANDI_LOG_DIR": "  ", "SCRAPER_BANDI_LOG_LEVEL": "verboso"}):
            self.assertEqual(mod.cartella_log(), LOGS_REALE)
            self.assertEqual(mod.livello_stderr(), "INFO")
        with patch.dict(os.environ, {"SCRAPER_BANDI_LOG_DIR": "/tmp/x", "SCRAPER_BANDI_LOG_LEVEL": "warning"}):
            self.assertEqual(mod.cartella_log(), Path("/tmp/x"))
            self.assertEqual(mod.livello_stderr(), "WARNING")

    def test_sink_reali_lazy_e_redatti(self):
        # L'import non ha creato nulla: ne' nella temporanea ne' in logs/
        self.assertEqual(list(self.temp.iterdir()), [])
        self.assertEqual(_impronta(LOGS_REALE), self.impronta_logs_prima)

        segreto_info = "login sessionid=SEGRETO-INFO csrftoken=CSRF-INFO password=PWD-INFO"
        segreto_debug = "dettaglio Authorization: Bearer TOKEN-DEBUG csrfmiddlewaretoken=CSRF-DEBUG"
        self.mod.logger.info(segreto_info)
        self.mod.logger.debug(segreto_debug)
        self.mod.logger.complete()

        # Sink file: nella cartella temporanea, a DEBUG, redatto
        file_log = list(self.temp.glob("scraper-bandi-*.log"))
        self.assertEqual(len(file_log), 1, file_log)
        contenuto = file_log[0].read_text(encoding="utf-8")
        self.assertIn("sessionid=[REDATTO] csrftoken=[REDATTO] password=[REDATTO]", contenuto)
        self.assertIn("Authorization: Bearer [REDATTO] csrfmiddlewaretoken=[REDATTO]", contenuto)
        for segreto in ("SEGRETO-INFO", "CSRF-INFO", "PWD-INFO", "TOKEN-DEBUG", "CSRF-DEBUG"):
            self.assertNotIn(segreto, contenuto)

        # Sink stderr: livello INFO (il DEBUG non c'e'), redatto
        stderr = self.buffer.getvalue()
        self.assertIn("sessionid=[REDATTO] csrftoken=[REDATTO] password=[REDATTO]", stderr)
        self.assertNotIn("TOKEN-DEBUG", stderr)
        self.assertNotIn("Authorization: Bearer", stderr)
        for segreto in ("SEGRETO-INFO", "CSRF-INFO", "PWD-INFO"):
            self.assertNotIn(segreto, stderr)

        # logs/ del repo intatta
        self.assertEqual(_impronta(LOGS_REALE), self.impronta_logs_prima)


class TestTracebackSenzaSegreti(unittest.TestCase):
    """Un giro fallito non deve stampare i valori di .env.

    `logger.exception` gira con il `diagnose=True` dei sink di `logger.py`:
    loguru stampa allora, sotto ogni riga del traceback, il repr di tutte le
    variabili del frame. Nel `run()` del monitor c'e' `impostazioni`, cioe' un
    dataclass con `supabase_service_key`, `anthropic_api_key`,
    `firecrawl_api_key` e `obiettivo_europa_password`. Il patcher di redazione
    lavora su `record["message"]`, non sull'annotazione di diagnose, e il
    pattern `\bpassword` non combacia dentro `obiettivo_europa_password`.
    """

    SEGRETO = "sbk-VALORE-CHE-NON-DEVE-COMPARIRE"

    def setUp(self):
        from tests.supporto import carica_modulo

        # PRIMA i moduli: la registrazione del package di test rimuove tutti i
        # sink di loguru, e un sink aggiunto prima sparirebbe con loro.
        self.monitoraggio = carica_modulo("monitoraggio")
        self.blocco = carica_modulo("blocco")
        self.buffer = io.StringIO()
        # Lo stesso `diagnose` dei due sink di app/logger.py.
        self.sink = logger.add(self.buffer, level="DEBUG", diagnose=True,
                               backtrace=True, colorize=False)
        self.addCleanup(self._togli_sink)

    def _togli_sink(self):
        with contextlib.suppress(ValueError):
            logger.remove(self.sink)

    def test_il_giro_fallito_del_monitor_non_stampa_le_impostazioni(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        monitoraggio, blocco = self.monitoraggio, self.blocco

        # Impostazioni senza i `tetto_*`: `bilancio.tetti_da_impostazioni`
        # solleva su una riga che nomina `impostazioni`, cioe' esattamente il
        # frame che diagnose stamperebbe.
        impostazioni = SimpleNamespace(
            monitor_modalita="ombra",
            monitor_scenario="bilanciato",
            monitor_giri=("06:00",),
            supabase_service_key=self.SEGRETO,
            obiettivo_europa_password=self.SEGRETO,
        )
        lock = MagicMock()
        lock.acquisisci.return_value = blocco.Blocco("monitor", "test", blocco.ACQUISITO)
        lock.esito_saltato.side_effect = blocco.esito_saltato

        esito = asyncio.run(monitoraggio.run(
            impostazioni=impostazioni, fonte_dati=monitoraggio.FonteDati(), lock=lock))
        logger.complete()

        self.assertEqual(esito["status"], "errore")
        uscita = self.buffer.getvalue()
        # Il guasto si vede: c'e' il messaggio e c'e' il traceback.
        self.assertIn("[monitor] giro fallito", uscita)
        self.assertIn("tetti_da_impostazioni", uscita)
        # I valori no.
        self.assertNotIn(self.SEGRETO, uscita)
        self.assertNotIn("supabase_service_key=", uscita)


def _fixture() -> Path:
    FIXTURE.mkdir(parents=True, exist_ok=True)
    return FIXTURE


if __name__ == "__main__":
    unittest.main()
