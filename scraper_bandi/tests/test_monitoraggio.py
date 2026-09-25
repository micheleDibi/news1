# -*- coding: utf-8 -*-
"""`monitoraggio.py`: fasi, frequenze, jitter, tetti, lock, ombra (§6.2).

Il test centrale e' `TestJitterCoorte`: i 416 bandi a sportello, seminati tutti
nello stesso istante, non devono ricadere tutti lo stesso giorno. Senza il
jitter pieno alla semina il tetto del giro (420 fetch) scatterebbe *per
costruzione*, ogni giorno, per sempre — cioe' il piano non sarebbe eseguibile.

Nessuna rete e nessun DB: scarico, classificatore e fonte dati sono iniettati.
"""
import io
import json
import sys
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from tests.supporto import ALIAS, carica_modulo

monitoraggio = carica_modulo("monitoraggio")
eventi = carica_modulo("eventi")
blocco = carica_modulo("blocco")

ADESSO = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
OGGI = date(2026, 9, 23)


def _impostazioni(**extra):
    base = dict(
        monitor_modalita="ombra",
        monitor_scenario="bilanciato",
        monitor_giri=("06:00", "18:00"),
        monitor_stati_estesi=False,
        tetto_fetch_giro=420,
        tetto_ricerche_giorno=0,
        tetto_crediti_giorno=0,
        tetto_classificazioni_giorno=0,
        tetto_usd_giorno=0.0,
        tetto_crediti_mese=0,
        tetto_usd_mese=0.0,
        backfill_tetto_crediti=0,
        backfill_tetto_usd=0.0,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _bando(**extra):
    base = {
        "id": 1,
        "slug": "avviso-1",
        "pubblicato": True,
        "bando_master_id": None,
        "fonte_ufficiale_stato": "trovata",
        "fonte_ufficiale_url": "https://www.lazioeuropa.it/bandi/avviso-1/",
        "stato_bando": "aperto",
        "data_scadenza": None,
        "prossimo_controllo_at": (ADESSO - timedelta(hours=1)).isoformat(),
        "impronta_contenuto": "",
        "controlli_falliti": 0,
    }
    base.update(extra)
    return base


class _Risposta:
    def __init__(self, stato=200, html="", testo="", etag=None):
        self.stato = stato
        self.html = html
        self.testo = testo or html
        self.markdown = ""
        self.etag = etag
        self.last_modified = None

    @property
    def ok(self):
        return self.stato is not None and 200 <= self.stato < 300

    @property
    def vuota(self):
        return not (self.testo.strip() or self.html.strip())


async def _nessun_evento(ctx):
    """Classificatore inerte: non propone niente.

    Serve perche' `controlla` esce PRIMA del fetch quando il classificatore
    manca (un giro senza modello non deve pagare una GET per riga). I test dei
    pre-filtri vogliono invece arrivare al fetch, quindi ne iniettano uno.
    """
    return []


class _FonteSenzaLimite(monitoraggio.FonteDati):
    """Come la base, ma ignora il limite: serve a far mordere il tetto."""

    def candidati(self, *, limite=0, adesso=None, forza=False):
        return [dict(r) for r in self.righe]


# --- fasi e frequenze -------------------------------------------------------

class TestFase(unittest.TestCase):
    def test_sportello(self):
        self.assertEqual(
            monitoraggio.fase(_bando(), oggi=OGGI), monitoraggio.FASE_SPORTELLO)

    def test_aperto_entro_7(self):
        riga = _bando(data_scadenza="2026-09-28")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_APERTO_VICINO)

    def test_aperto_8_30(self):
        riga = _bando(data_scadenza="2026-10-15")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_APERTO_MEDIO)

    def test_aperto_oltre_30(self):
        riga = _bando(data_scadenza="2026-12-31")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_APERTO_LONTANO)

    def test_scadenza_passata_e_chiuso_anche_senza_cron(self):
        # La fase segue lo stato EFFETTIVO: un bando con la scadenza di ieri
        # non va ricontrollato come «aperto entro 7 giorni» ogni giorno.
        riga = _bando(data_scadenza="2026-09-22")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_CHIUSO)

    def test_iap_senza_data(self):
        riga = _bando(stato_bando="in apertura prossimamente", data_apertura=None)
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_IAP_IGNOTA)

    def test_iap_entro_7(self):
        riga = _bando(stato_bando="in apertura prossimamente", data_apertura="2026-09-28")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_IAP_VICINA)

    def test_iap_oltre_7(self):
        riga = _bando(stato_bando="in apertura prossimamente", data_apertura="2026-10-22")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_IAP_LONTANA)

    def test_iap_raggiunta_non_verificata(self):
        riga = _bando(stato_bando="in apertura prossimamente", data_apertura="2026-09-20",
                      data_apertura_verificata=False)
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_IAP_RAGGIUNTA)

    def test_sospeso_resta_sospeso_con_la_scadenza_passata(self):
        riga = _bando(stato_bando="sospeso", data_scadenza="2026-01-01")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_SOSPESO)

    def test_revocato(self):
        riga = _bando(stato_bando="revocato")
        self.assertEqual(monitoraggio.fase(riga, oggi=OGGI), monitoraggio.FASE_REVOCATO)


class TestFrequenze(unittest.TestCase):
    def test_tutte_le_fasi_hanno_una_frequenza_in_ogni_scenario(self):
        for scenario, tabella in monitoraggio.FREQUENZE.items():
            for fase in monitoraggio.FASI:
                with self.subTest(scenario=scenario, fase=fase):
                    self.assertIn(fase, tabella)

    def test_numeri_di_sezione_6_2(self):
        casi = [
            ("economico", monitoraggio.FASE_SPORTELLO, 7),
            ("bilanciato", monitoraggio.FASE_SPORTELLO, 3),
            ("massimo", monitoraggio.FASE_SPORTELLO, 1.5),
            ("economico", monitoraggio.FASE_APERTO_LONTANO, 14),
            ("bilanciato", monitoraggio.FASE_APERTO_LONTANO, 7),
            ("economico", monitoraggio.FASE_SOSPESO, 3),
            ("bilanciato", monitoraggio.FASE_SOSPESO, 2),
        ]
        for scenario, fase, atteso in casi:
            with self.subTest(scenario=scenario, fase=fase):
                self.assertEqual(monitoraggio.FREQUENZE[scenario][fase], atteso)

    def test_revocato_non_si_ricontrolla(self):
        riga = _bando(stato_bando="revocato")
        self.assertIsNone(monitoraggio.frequenza(riga, scenario="bilanciato", oggi=OGGI))
        self.assertIsNone(
            monitoraggio.prossimo_controllo(riga, scenario="bilanciato", adesso=ADESSO))

    def test_coda_del_chiuso_a_scatti(self):
        # +3, +10, +30, poi mensile (bilanciato).
        casi = [(0, 3.0), (2, 1.0), (3, 7.0), (11, 19.0), (30, 30.0), (45, 15.0)]
        for trascorsi, atteso in casi:
            scadenza = (OGGI - timedelta(days=trascorsi)).isoformat()
            riga = _bando(stato_bando="chiuso", data_scadenza=scadenza)
            with self.subTest(trascorsi=trascorsi):
                self.assertEqual(
                    monitoraggio.giorni_chiuso(riga, "bilanciato", oggi=OGGI), atteso)

    def test_chiuso_oltre_il_limite_si_ferma(self):
        # Il massimo arriva a 15 mesi, l'economico e il bilanciato a 12: un
        # chiuso da 400 giorni esce dalla coda solo nei primi due.
        riga_400 = _bando(stato_bando="chiuso",
                          data_scadenza=(OGGI - timedelta(days=400)).isoformat())
        self.assertIsNone(monitoraggio.giorni_chiuso(riga_400, "bilanciato", oggi=OGGI))
        self.assertIsNone(monitoraggio.giorni_chiuso(riga_400, "economico", oggi=OGGI))
        self.assertIsNotNone(monitoraggio.giorni_chiuso(riga_400, "massimo", oggi=OGGI))

        riga_500 = _bando(stato_bando="chiuso",
                          data_scadenza=(OGGI - timedelta(days=500)).isoformat())
        self.assertIsNone(monitoraggio.giorni_chiuso(riga_500, "massimo", oggi=OGGI))


class TestVolatilita(unittest.TestCase):
    def test_evento_verificato_avvicina(self):
        self.assertAlmostEqual(
            monitoraggio.moltiplicatore_volatilita(1.0, eventi_verificati=1), 0.7)

    def test_tre_controlli_senza_diff_allontanano(self):
        self.assertAlmostEqual(
            monitoraggio.moltiplicatore_volatilita(1.0, controlli_senza_diff=3), 1.3)

    def test_due_controlli_non_bastano(self):
        self.assertAlmostEqual(
            monitoraggio.moltiplicatore_volatilita(1.0, controlli_senza_diff=2), 1.0)

    def test_limiti_rispettati(self):
        self.assertEqual(monitoraggio.moltiplicatore_volatilita(10.0), monitoraggio.VOLATILITA_MAX)
        self.assertEqual(monitoraggio.moltiplicatore_volatilita(0.01), monitoraggio.VOLATILITA_MIN)


class TestPriorita(unittest.TestCase):
    def test_base_per_fase(self):
        self.assertEqual(
            monitoraggio.priorita(
                _bando(stato_bando="in apertura prossimamente",
                       data_apertura="2026-09-20"), oggi=OGGI),
            90,
        )
        self.assertEqual(monitoraggio.priorita(_bando(), oggi=OGGI), 30)
        self.assertEqual(
            monitoraggio.priorita(_bando(stato_bando="chiuso",
                                         data_scadenza="2026-09-01"), oggi=OGGI), 10)

    def test_bonus_cumulativi_e_tetto_a_100(self):
        riga = _bando(segnale_fonte=True, evento_in_attesa=True, segnale_macchina=True)
        self.assertEqual(monitoraggio.priorita(riga, oggi=OGGI), 85)
        alta = _bando(stato_bando="in apertura prossimamente", data_apertura="2026-09-20",
                      segnale_fonte=True, evento_in_attesa=True)
        self.assertEqual(monitoraggio.priorita(alta, oggi=OGGI), 100)

    def test_priorita_dei_segnali_non_viene_abbassata(self):
        riga = _bando(priorita_controllo=90)
        self.assertEqual(monitoraggio.priorita(riga, oggi=OGGI), 90)


class TestSelezione(unittest.TestCase):
    def test_solo_oe_non_entra_mai(self):
        # Fonte ufficiale non trovata: l'unico URL e' quello dell'aggregatore.
        righe = [_bando(id=1, fonte_ufficiale_stato="in_verifica"),
                 _bando(id=2, fonte_ufficiale_stato="non_trovata"),
                 _bando(id=3)]
        scelti = monitoraggio.seleziona(righe, adesso=ADESSO)
        self.assertEqual([r["id"] for r in scelti], [3])

    def test_doppione_non_entra(self):
        righe = [_bando(id=1, bando_master_id=9), _bando(id=2)]
        self.assertEqual([r["id"] for r in monitoraggio.seleziona(righe, adesso=ADESSO)], [2])

    def test_non_pubblicato_non_entra(self):
        righe = [_bando(id=1, pubblicato=False), _bando(id=2)]
        self.assertEqual([r["id"] for r in monitoraggio.seleziona(righe, adesso=ADESSO)], [2])

    def test_prossimo_controllo_futuro_non_entra(self):
        futuro = (ADESSO + timedelta(days=1)).isoformat()
        righe = [_bando(id=1, prossimo_controllo_at=futuro), _bando(id=2)]
        self.assertEqual([r["id"] for r in monitoraggio.seleziona(righe, adesso=ADESSO)], [2])

    def test_ordine_priorita_poi_data_poi_id(self):
        vecchio = (ADESSO - timedelta(days=2)).isoformat()
        recente = (ADESSO - timedelta(minutes=5)).isoformat()
        righe = [
            _bando(id=10, prossimo_controllo_at=recente),
            _bando(id=11, prossimo_controllo_at=vecchio),
            _bando(id=12, prossimo_controllo_at=vecchio, priorita_controllo=90),
            _bando(id=9, prossimo_controllo_at=vecchio),
        ]
        scelti = monitoraggio.seleziona(righe, adesso=ADESSO)
        self.assertEqual([r["id"] for r in scelti], [12, 9, 11, 10])

    def test_tetto_tronca(self):
        righe = [_bando(id=i) for i in range(10)]
        self.assertEqual(len(monitoraggio.seleziona(righe, tetto=3, adesso=ADESSO)), 3)


class TestJitterCoorte(unittest.TestCase):
    """§6.2: 416 bandi a sportello seminati insieme non cadono lo stesso giorno."""

    COORTE = 416

    def _semina(self, scenario, semina=True):
        # Sorteggio deterministico e uniforme: i test non devono dipendere dal
        # seme di `random`, e una coorte «perfettamente uniforme» e' il caso
        # peggiore realistico (nessuna fortuna statistica).
        giorni = Counter()
        for i in range(self.COORTE):
            frazione = (i + 0.5) / self.COORTE
            quando = monitoraggio.prossimo_controllo(
                _bando(id=i), scenario=scenario, adesso=ADESSO,
                casuale=lambda f=frazione: f, semina=semina,
            )
            giorni[quando.date()] += 1
        return giorni

    def test_senza_jitter_cadrebbero_tutti_insieme(self):
        # Il caso che il piano vuole evitare: `casuale` fisso = nessuna
        # dispersione. Serve a dimostrare che il test misura davvero il jitter.
        giorni = Counter()
        for i in range(self.COORTE):
            quando = monitoraggio.prossimo_controllo(
                _bando(id=i), scenario="bilanciato", adesso=ADESSO,
                casuale=lambda: 0.5, semina=False,
            )
            giorni[quando.date()] += 1
        self.assertEqual(max(giorni.values()), self.COORTE)

    def test_semina_nessun_giorno_oltre_il_40_percento(self):
        # Il criterio di §6.2 vale dove puo' valere: con una cadenza di almeno
        # due giorni. Nel «massimo» la cadenza dello sportello e' 1,5 giorni,
        # e nessuna dispersione puo' portare un giorno sotto il 40 % — il
        # giorno centrale contiene per forza 1/1,5 della finestra. Li' la
        # garanzia che conta e' quella del test successivo (il carico sta sotto
        # la capienza giornaliera), non la percentuale.
        for scenario in ("economico", "bilanciato"):
            with self.subTest(scenario=scenario):
                giorni = self._semina(scenario)
                quota = max(giorni.values()) / self.COORTE
                self.assertLessEqual(
                    quota, 0.40,
                    f"{scenario}: il giorno piu' carico ha il {quota:.0%} della coorte",
                )

    def test_semina_sta_sotto_la_capienza_giornaliera(self):
        # Capienza = tetto per giro x giri al giorno. E' la condizione che
        # rende il piano eseguibile: senza dispersione i 416 sportello
        # scadrebbero insieme e il tetto scatterebbe per costruzione.
        capienza = {"economico": 460 * 1, "bilanciato": 420 * 2, "massimo": 270 * 4}
        for scenario, tetto in capienza.items():
            with self.subTest(scenario=scenario):
                giorni = self._semina(scenario)
                self.assertLess(max(giorni.values()), tetto)

    def test_semina_non_supera_mai_la_cadenza(self):
        # La dispersione piena sparpaglia di piu', non di meno: nessun bando
        # viene controllato piu' tardi della sua cadenza nominale.
        limite = ADESSO + timedelta(days=monitoraggio.FREQUENZE["bilanciato"][
            monitoraggio.FASE_SPORTELLO])
        for frazione in (0.0, 0.5, 0.999):
            quando = monitoraggio.prossimo_controllo(
                _bando(), scenario="bilanciato", adesso=ADESSO,
                casuale=lambda f=frazione: f, semina=True)
            self.assertLessEqual(quando, limite)

    def test_regime_resta_entro_il_25_percento(self):
        cadenza = monitoraggio.FREQUENZE["bilanciato"][monitoraggio.FASE_SPORTELLO]
        for frazione, atteso in ((0.0, 0.75), (1.0, 1.25)):
            quando = monitoraggio.prossimo_controllo(
                _bando(), scenario="bilanciato", adesso=ADESSO,
                casuale=lambda f=frazione: f, semina=False)
            self.assertAlmostEqual(
                (quando - ADESSO).total_seconds() / 86400, cadenza * atteso, places=6)


class TestGiornoDiScadenza(unittest.TestCase):
    def test_controllo_ancorato_dopo_l_ora_dichiarata(self):
        # Cadenza 1 giorno (aperto entro 7) x jitter 1,25 = il 24 alle 18:00,
        # cioe' DOPO le 12:00 del giorno di scadenza: il controllo si ancora
        # a pochi minuti dopo l'ora, l'unico istante in cui dice qualcosa.
        riga = _bando(data_scadenza="2026-09-24", ora_scadenza="12:00:00")
        quando = monitoraggio.prossimo_controllo(
            riga, scenario="bilanciato", adesso=ADESSO, casuale=lambda: 1.0)
        self.assertEqual(quando.date(), date(2026, 9, 24))
        self.assertEqual((quando.hour, quando.minute), (12, 15))

    def test_nessun_ancoraggio_prima_del_giorno_di_scadenza(self):
        riga = _bando(data_scadenza="2026-09-28", ora_scadenza="12:00:00")
        quando = monitoraggio.prossimo_controllo(
            riga, scenario="bilanciato", adesso=ADESSO, casuale=lambda: 1.0)
        self.assertLess(quando.date(), date(2026, 9, 28))

    def test_senza_ora_nessun_ancoraggio(self):
        # Stessa riga del test precedente ma senza `ora_scadenza`: nessun
        # ancoraggio, resta la cadenza (1 giorno x 1,25 dalle 14:00 di Roma).
        riga = _bando(data_scadenza="2026-09-24")
        quando = monitoraggio.prossimo_controllo(
            riga, scenario="bilanciato", adesso=ADESSO, casuale=lambda: 1.0)
        self.assertEqual((quando.date(), quando.hour, quando.minute),
                         (date(2026, 9, 24), 20, 0))


class TestBackoff(unittest.TestCase):
    def test_esponenziale_con_tetto_a_7_giorni(self):
        casi = [(0, 6), (1, 12), (2, 24), (5, 24 * 7), (12, 24 * 7)]
        for falliti, ore in casi:
            with self.subTest(falliti=falliti):
                quando = monitoraggio.prossimo_dopo_errore(falliti, adesso=ADESSO)
                self.assertAlmostEqual(
                    (quando - ADESSO).total_seconds() / 3600, ore, places=3)


# --- controllo di un singolo bando ------------------------------------------

class TestControlla(unittest.IsolatedAsyncioTestCase):
    async def test_304_non_costa_niente(self):
        async def scarica(url, **kw):
            return _Risposta(stato=304)

        dati = monitoraggio.FonteDati()
        esito = await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=_nessun_evento, fonte_dati=dati,
            adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito.esito, "304")
        self.assertFalse(esito.classificato)
        self.assertEqual(dati.scritture[0][1]["controlli_falliti"], 0)

    async def test_segnale_macchina_ferma_prima_del_fetch(self):
        chiamate = []

        async def scarica(url, **kw):
            chiamate.append(url)
            return _Risposta(html="x")

        async def segnale(riga):
            return False

        esito = await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=_nessun_evento, segnale_macchina=segnale,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito.esito, "invariato")
        self.assertEqual(esito.fetch, 0)
        self.assertEqual(chiamate, [])

    async def test_impronta_invariata_niente_llm(self):
        html = "<h1>Avviso</h1><p>Le domande entro il 6 ottobre 2026.</p>"
        impronte = carica_modulo("impronte")
        riga = _bando(impronta_contenuto=impronte.impronta_contenuto(html), testo_norm=html)

        async def scarica(url, **kw):
            return _Risposta(html=html)

        classificatore = MagicMock()
        esito = await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classificatore,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito.esito, "invariato")
        self.assertFalse(esito.classificato)
        classificatore.assert_not_called()

    async def test_errore_5xx_fa_backoff(self):
        async def scarica(url, **kw):
            return _Risposta(stato=503)

        dati = monitoraggio.FonteDati()
        esito = await monitoraggio.controlla(
            _bando(controlli_falliti=1), scarica=scarica, classifica=_nessun_evento,
            fonte_dati=dati, adesso=ADESSO)
        self.assertEqual(esito.esito, "errore")
        self.assertEqual(esito.colonne["controlli_falliti"], 2)
        self.assertAlmostEqual(
            (esito.prossimo - ADESSO).total_seconds() / 3600, 24, places=3)

    async def test_cinque_fallimenti_bloccano(self):
        async def scarica(url, **kw):
            raise RuntimeError("timeout")

        dati = monitoraggio.FonteDati()
        sospesi = []
        with patch.object(monitoraggio, "_sospendi_fonte", sospesi.append):
            esito = await monitoraggio.controlla(
                _bando(controlli_falliti=4), scarica=scarica, classifica=_nessun_evento,
                fonte_dati=dati, adesso=ADESSO, modalita="attivo")
        # `elaborazione_bloccata` e `fonte_ufficiale_stato` NON sono colonne di
        # `bando_controllo` (02:1138-1162): la prima e' un tipo di evento, la
        # seconda sta su `bando`. Scritte qui venivano scartate in silenzio.
        self.assertNotIn("elaborazione_bloccata", esito.colonne)
        self.assertNotIn("fonte_ufficiale_stato", esito.colonne)
        # Il bando esce dalla coda per davvero: ricontrollo lontano + la
        # colonna di `bando` che lo rimanda al resolver.
        self.assertEqual(sospesi, [_bando()["id"]])
        self.assertEqual(
            esito.colonne["prossimo_controllo_at"], esito.prossimo.isoformat())
        self.assertGreaterEqual(
            (esito.prossimo - ADESSO).total_seconds(),
            monitoraggio.BACKOFF_MASSIMO_ORE * 3600 - 1)
        self.assertEqual(dati.registrati[0]["tipo"], "elaborazione_bloccata")
        self.assertFalse(dati.registrati[0]["leggibile"])

    async def test_in_ombra_i_cinque_fallimenti_non_toccano_bando(self):
        # `fonte_ufficiale_stato` e' una colonna pubblica di `bando`: in ombra
        # il monitor non ne tocca nessuna. Il ricontrollo lontano invece si
        # scrive lo stesso, perche' sta su `bando_controllo`.
        async def scarica(url, **kw):
            raise RuntimeError("timeout")

        dati = monitoraggio.FonteDati()
        sospesi = []
        with patch.object(monitoraggio, "_sospendi_fonte", sospesi.append):
            esito = await monitoraggio.controlla(
                _bando(controlli_falliti=4), scarica=scarica, classifica=_nessun_evento,
                fonte_dati=dati, adesso=ADESSO)
        self.assertEqual(sospesi, [])
        self.assertIn("prossimo_controllo_at", esito.colonne)
        self.assertEqual(dati.registrati[0]["tipo"], "elaborazione_bloccata")

    async def test_senza_fonte_ufficiale_si_salta(self):
        async def scarica(url, **kw):       # pragma: no cover - non deve girare
            raise AssertionError("non deve scaricare")

        esito = await monitoraggio.controlla(
            _bando(fonte_ufficiale_url=None), scarica=scarica, classifica=_nessun_evento,
            adesso=ADESSO)
        self.assertEqual(esito.esito, "saltato")

    async def test_head_allegati_prima_del_fetch(self):
        ordine = []

        async def scarica(url, **kw):
            ordine.append("get")
            return _Risposta(stato=304)

        async def head(riga):
            ordine.append("head")
            return [{"url": "https://ente.it/a.pdf", "esito_http": 404}]

        dati = monitoraggio.FonteDati()
        esito = await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=_nessun_evento, head_allegati=head,
            fonte_dati=dati, adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(ordine, ["head", "get"])
        self.assertEqual(esito.allegati[0]["pubblicabile"], False)
        self.assertEqual(dati.registrati[0]["tipo"], "elaborazione_bloccata")

    async def test_head_allegati_che_solleva_non_ferma_il_controllo(self):
        async def scarica(url, **kw):
            return _Risposta(stato=304)

        async def head(riga):
            raise RuntimeError("HEAD rifiutata")

        esito = await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=_nessun_evento, head_allegati=head,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito.esito, "304")
        self.assertEqual(esito.allegati, [])

    async def test_pagine_collegate_al_massimo_due(self):
        scaricati = []

        async def scarica(url, **kw):
            scaricati.append(url)
            return _Risposta(html=f"<h1>{url}</h1><p>prorogato al 1 dicembre 2026</p>")

        async def collegate(riga):
            return ["https://a.it/1", "https://a.it/2", "https://a.it/3"]

        async def classifica(ctx):
            return []

        await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=classifica, pagine_collegate=collegate,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(len(scaricati), 1 + monitoraggio.MAX_PAGINE_COLLEGATE)


# --- giro completo ----------------------------------------------------------

class TestRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_lock_occupato_salta_senza_errori(self):
        finto = MagicMock()
        finto.acquisisci.return_value = blocco.Blocco("monitor", "x", blocco.OCCUPATO)
        finto.esito_saltato.side_effect = blocco.esito_saltato
        finto.rilascia.return_value = False
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(), lock=finto)
        self.assertEqual(esito["status"], "ok")
        self.assertTrue(esito["saltato_per_lock"])

    async def test_senza_classificatore_il_giro_si_dichiara_non_configurato(self):
        """Un giro che non ha potuto fare niente non deve sembrare riuscito.

        Senza `ANTHROPIC_API_KEY` `controlla` esce al passo 0 su ogni riga e
        non salva niente: nessuna riga esce dalla coda, due giri di fila
        guardano gli stessi id e l'esito era `status: ok`, exit 0. E' il caso
        per cui esiste `EXIT_NON_CONFIGURATO`, e la chiave `saltato` e' quella
        che `__main__._codice_da_contatori` traduce in 5.
        """
        async def scarica(url, **kw):
            return _Risposta(html="<h1>x</h1><p>testo</p>")

        with patch.object(monitoraggio, "classificatore_da_impostazioni",
                          lambda *a, **k: None), \
                patch.object(monitoraggio, "controlla") as controlla:
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(),
                fonte_dati=monitoraggio.FonteDati(righe=[_bando(id=1), _bando(id=2)]),
                scarica=scarica, lock=_lock_libero(), adesso=ADESSO,
            )
        controlla.assert_not_called()
        self.assertEqual(esito["saltato"], "scarico_non_configurato")
        self.assertEqual(esito["candidati"], 2)
        self.assertEqual(esito["controllati"], 0)

    async def test_il_riepilogo_dichiara_se_il_G7_e_soddisfacibile(self):
        # G7 chiede una seconda prova indipendente: senza `seconda_opinione` e
        # senza `pagine_collegate` nessun evento con transizione o con una
        # data puo' passare, e meta' del monitor e' muta. Il riepilogo lo dice,
        # invece di lasciar credere che il monitor non trovi niente.
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(),
            lock=_lock_libero())
        self.assertFalse(esito["g7_disponibile"])
        self.assertFalse(esito["g7_concordanza"])
        self.assertFalse(esito["g7_prova_indipendente"])

        async def collegate(*a, **k):                     # pragma: no cover
            return ()

        async def seconda(*a, **k):                       # pragma: no cover
            return None

        # Un solo adattatore NON basta: la variante G2' del gate (primo
        # controllo, mismatch senza diff — il caso guida di §6.2) pretende
        # ENTRAMBE le prove, e un riepilogo che dicesse «G7 soddisfacibile»
        # mentre ogni evento G2' viene respinto sarebbe proprio l'equivoco che
        # questo campo esiste per evitare.
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(),
            pagine_collegate=collegate, lock=_lock_libero())
        self.assertFalse(esito["g7_disponibile"])
        self.assertTrue(esito["g7_prova_indipendente"])
        self.assertFalse(esito["g7_concordanza"])

        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(),
            pagine_collegate=collegate, seconda_opinione=seconda,
            lock=_lock_libero())
        self.assertTrue(esito["g7_disponibile"])

    async def test_ogni_uscita_anticipata_porta_allarmi_e_g7(self):
        # `allarmi` e i tre campi del G7 nascono per essere letti da fuori
        # (`pipeline_run`): una uscita anticipata che non li avesse manderebbe
        # in KeyError chi li legge, proprio nei giri saltati.
        async def collegate(*a, **k):                     # pragma: no cover
            return ()

        async def seconda(*a, **k):                       # pragma: no cover
            return None

        comuni = dict(pagine_collegate=collegate, seconda_opinione=seconda)
        occupato = MagicMock()
        occupato.acquisisci.return_value = blocco.Blocco("monitor", "x", blocco.OCCUPATO)
        occupato.esito_saltato.side_effect = blocco.esito_saltato
        occupato.rilascia.return_value = False

        class _SenzaColonne(monitoraggio.FonteDati):
            def disponibile(self):
                return False, "colonne_assenti"

        uscite = [
            await monitoraggio.run(
                impostazioni=_impostazioni(), giro="12:00",
                fonte_dati=monitoraggio.FonteDati(), lock=_lock_libero(), **comuni),
            await monitoraggio.run(
                impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(),
                lock=occupato, **comuni),
            await monitoraggio.run(
                impostazioni=_impostazioni(), fonte_dati=_SenzaColonne(),
                lock=_lock_libero(), **comuni),
        ]
        for uscita in uscite:
            with self.subTest(saltato=uscita.get("saltato")):
                self.assertEqual(uscita["allarmi"], [])
                self.assertTrue(uscita["g7_disponibile"])
                self.assertEqual(uscita["slug_modificati"], [])
                self.assertIn("saltato_per_lock", uscita)
                self.assertIn("interrotto_per_tetto", uscita)

    async def test_lock_assente_prosegue(self):
        finto = MagicMock()
        finto.acquisisci.return_value = blocco.Blocco("monitor", "x", blocco.ASSENTE)
        finto.esito_saltato.side_effect = blocco.esito_saltato
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=monitoraggio.FonteDati(), lock=finto)
        self.assertFalse(esito["saltato_per_lock"])

    async def test_colonne_assenti_degrada(self):
        class _Assente(monitoraggio.FonteDati):
            def disponibile(self):
                return False, "colonne_assenti"

        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=_Assente(), lock=_lock_libero())
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["saltato"], "colonne_assenti")

    async def test_giro_non_previsto(self):
        esito = await monitoraggio.run(
            giro="12:00", impostazioni=_impostazioni(),
            fonte_dati=monitoraggio.FonteDati(), lock=_lock_libero())
        self.assertEqual(esito["saltato"], "giro_non_previsto")

    async def test_tetto_raggiunto_non_solleva(self):
        async def scarica(url, **kw):
            return _Risposta(html="<h1>x</h1><p>testo</p>")

        async def classifica(ctx):
            return []

        dati = _FonteSenzaLimite(righe=[_bando(id=i) for i in range(5)])
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(tetto_fetch_giro=2),
            fonte_dati=dati, scarica=scarica, classifica=classifica,
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
        )
        self.assertEqual(esito["status"], "ok")
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual(esito["controllati"], 2)
        self.assertIn("tetto fetch", esito["motivo"])

    async def test_ombra_non_produce_slug_da_notificare(self):
        # In ombra nessun URL va a IndexNow: il contenuto pubblico non cambia.
        async def scarica(url, **kw):
            return _Risposta(html="<h1>Avviso</h1><p>termini prorogati al 1 dicembre 2026</p>")

        async def classifica(ctx):
            return [eventi.Evento(
                tipo="proroga", campo="data_scadenza", valore="2026-12-01",
                citazione="termini prorogati al 1 dicembre 2026",
                url_prova=ctx.pagine[0].url)]

        dati = monitoraggio.FonteDati(righe=[_bando(data_scadenza="2026-10-06")])
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(monitor_modalita="ombra"),
            fonte_dati=dati, scarica=scarica, classifica=classifica,
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
        )
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(esito["slug_modificati"], [])

    async def test_dry_run_forza_l_ombra_anche_con_attivo(self):
        esito = await monitoraggio.run(
            dry_run=True, attivo=True, impostazioni=_impostazioni(),
            fonte_dati=monitoraggio.FonteDati(), lock=_lock_libero())
        self.assertEqual(esito["modalita"], "ombra")

    async def test_senza_rete_non_scarica_niente(self):
        dati = monitoraggio.FonteDati(righe=[_bando(id=1), _bando(id=2)])
        esito = await monitoraggio.run(
            senza_rete=True, impostazioni=_impostazioni(), fonte_dati=dati,
            lock=_lock_libero(), adesso=ADESSO,
        )
        self.assertEqual(esito["status"], "ok")
        # `controllati` conta le righe davvero controllate: un giro senza rete
        # non ne controlla nessuna, e dire «controllati: 2» lo faceva
        # somigliare a un giro riuscito. I due bandi sono `saltati`, con il
        # motivo scritto nel riepilogo (e quindi in `pipeline_run`).
        self.assertEqual(esito["controllati"], 0)
        self.assertEqual(esito["saltati"], 2)
        self.assertEqual(esito["motivo_saltati"], "senza rete")
        self.assertEqual(esito["fetch"], 0)
        self.assertEqual(esito["classificazioni"], 0)

    async def test_senza_iniezione_usa_lo_scarico_del_giro(self):
        # Il monitor non apre connessioni per conto suo: chiede il client
        # unico a `scarico.py`. Qui si verifica che lo chieda davvero.
        chiamate = []

        def finto():
            chiamate.append(True)
            return None

        with patch.object(monitoraggio, "_scarico_predefinito", finto):
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(),
                fonte_dati=monitoraggio.FonteDati(righe=[_bando(id=1)]),
                lock=_lock_libero(), adesso=ADESSO,
            )
        self.assertEqual(chiamate, [True])
        self.assertEqual(esito["fetch"], 0)

    async def test_errore_imprevisto_non_risale(self):
        class _Esplosiva(monitoraggio.FonteDati):
            def candidati(self, *, limite=0, adesso=None, forza=False):
                raise RuntimeError("PostgREST giu'")

        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=_Esplosiva(), lock=_lock_libero())
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(esito["slug_modificati"], [])

    async def test_lock_rilasciato_anche_in_errore(self):
        class _Esplosiva(monitoraggio.FonteDati):
            def candidati(self, *, limite=0, adesso=None, forza=False):
                raise RuntimeError("giu'")

        finto = _lock_libero()
        await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=_Esplosiva(), lock=finto)
        finto.rilascia.assert_called_once()


class TestAllegati(unittest.TestCase):
    """Pre-filtro HEAD sugli allegati: zero token, garanzia di §13.4."""

    def test_404_toglie_la_riga_da_pubblicabile(self):
        aggiornamenti, interni = monitoraggio.controlla_allegati(
            _bando(), [{"url": "https://ente.it/a.pdf", "esito_http": 404}])
        self.assertEqual(aggiornamenti[0]["pubblicabile"], False)
        self.assertEqual(interni[0]["tipo"], "elaborazione_bloccata")
        self.assertFalse(interni[0]["leggibile"])

    def test_410_come_404(self):
        aggiornamenti, _ = monitoraggio.controlla_allegati(
            _bando(), [{"url": "https://ente.it/a.pdf", "esito_http": 410}])
        self.assertFalse(aggiornamenti[0]["pubblicabile"])

    def test_sha_cambiato_resta_un_segnale_interno(self):
        # Una HEAD non produce nessuna citazione: senza citazione i gate G1 e
        # G4 non possono passare, quindi l'evento resta interno.
        aggiornamenti, interni = monitoraggio.controlla_allegati(
            _bando(), [{"url": "https://ente.it/a.pdf", "esito_http": 200,
                        "sha256": "abc", "cambiato": True}])
        self.assertEqual(aggiornamenti[0]["sha256"], "abc")
        self.assertEqual(interni[0]["tipo"], "segnale_fonte")
        self.assertFalse(interni[0]["leggibile"])
        self.assertFalse(interni[0]["in_aggiornamenti"])

    def test_200_invariato_non_produce_niente(self):
        aggiornamenti, interni = monitoraggio.controlla_allegati(
            _bando(), [{"url": "https://ente.it/a.pdf", "esito_http": 200,
                        "sha256": "abc", "cambiato": False}])
        self.assertEqual((aggiornamenti, interni), ([], []))

    def test_url_vuoto_ignorato(self):
        aggiornamenti, interni = monitoraggio.controlla_allegati(
            _bando(), [{"url": "", "esito_http": 404}, None])
        self.assertEqual((aggiornamenti, interni), ([], []))


class TestNewsUrl(unittest.TestCase):
    def test_una_voce_per_host(self):
        mappa = monitoraggio.news_url_per_host()
        self.assertIn("lazioeuropa.it", mappa)
        self.assertTrue(mappa["lazioeuropa.it"].startswith("https://www.lazioeuropa.it/wp-json/"))

    def test_host_senza_www(self):
        for host in monitoraggio.news_url_per_host():
            self.assertFalse(host.startswith("www."))


def _zittisci_io(caso):
    """Telemetria, tabella dei domini e RPC fuori dai test di `run()`.

    Sono i tre punti in cui il giro andrebbe a cercare il DB: la riga
    `pipeline_run`, la whitelist dei domini e il controllo della RPC
    `bando_registra_evento`. Nessun test di questo file deve aprire una
    connessione, nemmeno una che poi fallisce.
    """
    for bersaglio in (
        patch.object(monitoraggio, "_scrivi_telemetria", MagicMock()),
        patch.object(monitoraggio, "_tabella_domini_del_giro", lambda: None),
        patch.object(eventi, "_rpc_disponibile", lambda controllo: False),
    ):
        bersaglio.start()
        caso.addCleanup(bersaglio.stop)


def _lock_libero():
    finto = MagicMock()
    finto.acquisisci.return_value = blocco.Blocco("monitor", "test", blocco.ACQUISITO)
    finto.esito_saltato.side_effect = blocco.esito_saltato
    finto.rilascia.return_value = True
    return finto


# --- ombra: report e applicazione differita ---------------------------------

class TestOmbra(unittest.TestCase):
    def _esito(self, ammesso=True):
        giudizio = {"gate": "G2'", "ammesso": ammesso, "confidenza": 0.9,
                    "superati": ["G1", "G2'"],
                    "falliti": [] if ammesso else [{"gate": "G7", "motivo": "nessuna prova"}]}
        voce = {"riga": {"tipo": "proroga", "campo": "data_scadenza",
                         "url_prova": "https://ente.it/x", "citazione": "prorogato"},
                "giudizio": giudizio}
        esito = monitoraggio.EsitoControllo(bando_id=1, fase="sportello")
        if ammesso:
            esito.eventi = (voce,)
        else:
            esito.respinti = (voce,)
        return esito

    def test_report_contiene_gate_superati_e_falliti(self):
        righe = monitoraggio.report_ombra([self._esito(True), self._esito(False)])
        self.assertEqual(len(righe), 2)
        self.assertEqual(righe[0]["gate"], "G2'")
        self.assertIn("G7", righe[1]["falliti"])

    def test_campione_limita(self):
        esiti = [self._esito() for _ in range(10)]
        self.assertEqual(len(monitoraggio.report_ombra(esiti, campione=3)), 3)

    def test_filtro_per_tipo(self):
        righe = monitoraggio.report_ombra([self._esito()], tipo="revoca")
        self.assertEqual(righe, ())

    def test_applica_eventi_dry_run_non_scrive(self):
        applicati = []
        esito = monitoraggio.applica_eventi(
            [{"id": 1, "tipo": "proroga", "data_evento": "2026-09-20",
              "verificato": True, "applicato": False}],
            dal=date(2026, 9, 1), dry_run=True,
            applica=lambda r: applicati.append(r) or True,
        )
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["applicati"], 0)
        self.assertEqual(applicati, [])

    def test_applica_eventi_a_blocchi(self):
        righe = [{"id": i, "tipo": "proroga", "data_evento": "2026-09-20",
                  "verificato": True, "applicato": False}
                 for i in range(200)]
        esito = monitoraggio.applica_eventi(righe, limit=50, dry_run=False, applica=lambda r: True)
        self.assertEqual(esito["candidati"], 50)
        self.assertEqual(esito["applicati"], 50)

    def test_applica_eventi_salta_i_gia_applicati(self):
        righe = [{"id": 1, "tipo": "proroga", "data_evento": "2026-09-20", "applicato": True}]
        self.assertEqual(monitoraggio.applica_eventi(righe)["candidati"], 0)

    def test_applica_eventi_filtra_per_data_e_tipo(self):
        righe = [
            {"id": 1, "tipo": "proroga", "data_evento": "2026-08-01", "verificato": True},
            {"id": 2, "tipo": "proroga", "data_evento": "2026-09-20", "verificato": True},
            {"id": 3, "tipo": "revoca", "data_evento": "2026-09-20", "verificato": True},
        ]
        esito = monitoraggio.applica_eventi(righe, dal=date(2026, 9, 1), tipo="proroga")
        self.assertEqual(esito["candidati"], 1)

    def test_applica_eventi_scarta_gli_interni(self):
        # Senza `--tipo` diventerebbero candidati anche gli eventi che lo
        # stesso monitor registra (`elaborazione_bloccata` da `_errore`,
        # `segnale_fonte` dalle HEAD sugli allegati): §13.5 li dichiara sempre
        # interni e non hanno nessuna colonna da applicare.
        righe = [
            {"id": 1, "tipo": "elaborazione_bloccata", "data_evento": "2026-09-20"},
            {"id": 2, "tipo": "segnale_fonte", "data_evento": "2026-09-20"},
            {"id": 3, "tipo": "sparito_dalla_fonte", "data_evento": "2026-09-20"},
        ]
        self.assertEqual(monitoraggio.applica_eventi(righe)["candidati"], 0)

    def test_applica_eventi_scarta_i_non_verificati(self):
        # In ombra si registrano anche i respinti: applicarli a posteriori
        # vorrebbe dire scrivere cio' che i gate avevano bocciato.
        righe = [
            {"id": 1, "tipo": "proroga", "data_evento": "2026-09-20", "verificato": False},
            {"id": 2, "tipo": "proroga", "data_evento": "2026-09-20", "verificato": True},
        ]
        esito = monitoraggio.applica_eventi(righe)
        self.assertEqual(esito["candidati"], 1)


# --- memoria del monitor: testo_norm, ETag, impronte ------------------------

class TestMemoriaDelControllo(unittest.IsolatedAsyncioTestCase):
    """Le colonne che rendono economico il controllo successivo (§6.2).

    Senza `testo_norm`, `etag` e `last_modified` a DB il monitor riparte da
    zero a ogni giro: nessun 304 possibile, nessun diff possibile, e ogni
    evento giudicato con G2' — cioe' il caso che §6.2 vuole eccezionale.
    """

    HTML = ("<h1>Avviso</h1><p>Le domande entro il 6 ottobre 2026.</p>"
            "<h2>Dotazione</h2><p>Tre milioni di euro.</p>")

    async def _scarica(self, url, **kw):
        return _Risposta(html=self.HTML, etag='W/"abc123"')

    async def test_secondo_controllo_non_arriva_al_modello(self):
        # Due `controlla` di fila sullo stesso HTML, riusando le colonne
        # restituite dal primo: il secondo deve fermarsi sull'impronta.
        chiamate = []

        async def classifica(ctx):
            chiamate.append(ctx)
            return []

        dati = monitoraggio.FonteDati()
        riga = _bando()
        primo = await monitoraggio.controlla(
            riga, scarica=self._scarica, classifica=classifica, fonte_dati=dati,
            adesso=ADESSO, casuale=lambda: 0.5)
        self.assertTrue(primo.classificato)
        self.assertEqual(len(chiamate), 1)

        # Le colonne scritte dal primo controllo sono l'unico stato che
        # sopravvive al redeploy: il secondo giro rilegge da li'.
        self.assertIn("testo_norm", primo.colonne)
        self.assertIn("impronte_sezioni", primo.colonne)
        self.assertEqual(primo.colonne["etag"], 'W/"abc123"')

        secondo = await monitoraggio.controlla(
            dict(riga, **primo.colonne), scarica=self._scarica, classifica=classifica,
            fonte_dati=dati, adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(secondo.esito, "invariato")
        self.assertFalse(secondo.classificato)
        self.assertEqual(len(chiamate), 1)

    async def test_etag_torna_nella_get_condizionale(self):
        intestazioni = []

        async def scarica(url, **kw):
            intestazioni.append((kw.get("etag"), kw.get("modificata_dopo")))
            return _Risposta(stato=304)

        dati = monitoraggio.FonteDati()
        primo = await monitoraggio.controlla(
            _bando(), scarica=self._scarica, classifica=_nessun_evento,
            fonte_dati=dati, adesso=ADESSO, casuale=lambda: 0.5)
        await monitoraggio.controlla(
            dict(_bando(), **primo.colonne), scarica=scarica, classifica=_nessun_evento,
            fonte_dati=dati, adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(intestazioni, [('W/"abc123"', None)])

    def test_il_testo_va_a_db_compresso_e_torna_uguale(self):
        compresso = monitoraggio.comprimi_testo("Le domande entro il 6 ottobre 2026.")
        self.assertTrue(compresso.startswith(monitoraggio.PREFISSO_BYTEA))
        self.assertEqual(
            monitoraggio.testo_da_colonna(compresso), "Le domande entro il 6 ottobre 2026.")

    def test_testo_in_chiaro_e_colonna_illeggibile(self):
        # Righe scritte prima della compressione e fixture: si leggono uguale.
        self.assertEqual(monitoraggio.testo_da_colonna("testo vecchio"), "testo vecchio")
        self.assertIsNone(monitoraggio.testo_da_colonna(None))
        self.assertIsNone(monitoraggio.testo_da_colonna("\\xnonesadecimale"))

    def test_le_colonne_della_memoria_sono_richieste(self):
        for colonna in ("testo_norm", "impronte_sezioni", "etag", "last_modified"):
            with self.subTest(colonna=colonna):
                self.assertIn(colonna, monitoraggio.COLONNE_CONTROLLO)


# --- volatilita': una cricca a senso unico (F4) -----------------------------

#: Le colonne che `bando_controllo` ha davvero (02:1138-1163). Non c'e'
#: `controlli_senza_diff`: `aggiorna_controllo` la scarta via
#: `colonne_mancanti`, quindi alla rilettura vale sempre 0.
COLONNE_CONTROLLO_A_DB = frozenset({
    "bando_id", "ultimo_controllo_at", "prossimo_controllo_at", "priorita_controllo",
    "volatilita", "controlli_falliti", "tentativi_resolver", "tentativi_pipeline",
    "candidato_prioritario", "impronta_contenuto", "impronte_sezioni", "testo_norm",
    "impronta_raw", "ultimo_visto_in_fonte_at", "rigenerazioni_fallite",
    "richiede_js", "etag", "last_modified", "created_at", "updated_at",
})


class TestVolatilitaAttraversoIGiri(unittest.TestCase):
    """La volatilita' letta a DB puo' solo scendere, quindi non si rilegge.

    `moltiplicatore_volatilita` ha due direzioni: un evento verificato
    abbassa `m` (x0,7), tre controlli senza diff lo rialzano (x1,3). La
    seconda non funziona, perche' `controlli_senza_diff` **non esiste** in
    `bando_controllo`: `aggiorna_controllo` la scarta in silenzio e alla
    rilettura vale 0, sotto la soglia di `CONTROLLI_PER_CALMA`. Rileggere la
    sola volatilita' la fa comporre giro dopo giro fino a `VOLATILITA_MIN`,
    e nulla puo' piu' riportarla su: ogni bando cambiato due volte resterebbe
    controllato al doppio della frequenza per sempre — piu' fetch e piu'
    classificazioni sul tetto giornaliero in dollari.
    """

    BANDO_ID = 1                                   # l'id di `_bando()`

    def setUp(self):
        self.db = carica_modulo("db")
        self.tabella = {self.BANDO_ID: {"bando_id": self.BANDO_ID, "volatilita": 1.0}}
        self.chieste: list[tuple] = []

    def _controlli(self, ids, **kwargs):
        colonne = tuple(kwargs.get("colonne") or ())
        self.chieste.append(colonne)
        return {i: {k: v for k, v in self.tabella[i].items()
                    if not colonne or k in colonne or k == "bando_id"}
                for i in ids if i in self.tabella}

    def _giro(self, *, cambiato):
        """Un giro completo: lettura della memoria, controllo, scrittura."""
        bando = _bando(data_scadenza="2027-06-30")
        with patch.object(self.db, "select_controlli", self._controlli):
            riga = monitoraggio.FonteDatiSupabase(
                controllo=object())._con_memoria([bando])[0]
        colonne = monitoraggio._colonne_invariato(
            riga, None, ADESSO, cambiato=cambiato)
        # Cio' che arriva davvero a DB: `aggiorna_controllo` scarta le colonne
        # che lo schema non espone, e non lo dice a chi ha chiamato.
        self.tabella[self.BANDO_ID].update(
            {k: v for k, v in colonne.items() if k in COLONNE_CONTROLLO_A_DB})
        return riga, colonne

    def test_la_seconda_lettura_non_chiede_la_volatilita(self):
        self._giro(cambiato=False)
        self.assertNotIn("volatilita", self.chieste[-1])
        # La memoria vera, invece, si chiede tutta.
        for colonna in monitoraggio.COLONNE_CONTROLLO:
            self.assertIn(colonna, self.chieste[-1])

    def test_due_giri_cambiati_non_dimezzano_la_cadenza_per_sempre(self):
        # Due giri con un evento verificato, poi cinque senza. Con la
        # volatilita' riletta: 1,0 -> 0,7 -> 0,5 e li' resta, cioe' meta'
        # cadenza per sempre. Senza: al massimo 0,7, e il giro dopo si
        # riparte da 1,0.
        scritte = []
        for giro in range(1, 8):
            _, colonne = self._giro(cambiato=giro <= 2)
            scritte.append(colonne["volatilita"])
        self.assertNotIn(monitoraggio.VOLATILITA_MIN, scritte)
        self.assertGreaterEqual(min(scritte), monitoraggio.VOLATILITA_EVENTO)
        # I giri senza cambiamenti tornano alla cadenza piena.
        self.assertEqual(scritte[2:], [1.0] * 5)

    def test_il_fattore_calma_resterebbe_inerte_anche_dopo_dieci_giri(self):
        # `controlli_senza_diff` non arriva mai a DB: la prova che la calma
        # non puo' compensare la discesa, ed e' il motivo per cui la discesa
        # non deve accumularsi.
        for _ in range(10):
            riga, _ = self._giro(cambiato=False)
            self.assertEqual(int(riga.get("controlli_senza_diff") or 0), 0)
        self.assertNotIn("controlli_senza_diff", self.tabella[self.BANDO_ID])


# --- tabella dei domini: G4 non puo' vivere di seed -------------------------

class TestCostruzioneTabellaDomini(unittest.TestCase):
    """La funzione che legge il DB, provata da sola e senza rete."""

    def test_costruita_da_dominio_ufficiale_e_fonte(self):
        db = carica_modulo("db")
        dominio_ufficiale = carica_modulo("dominio_ufficiale")
        with patch.object(db, "select_fonti_per_domini",
                          lambda: [{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}]):
            tabella = monitoraggio._tabella_domini_del_giro()
        # `lazioeuropa.it` non e' nel seed compilato: solo la tabella viva
        # lo rende verificabile, ed e' il caso guida di §6.2.
        self.assertFalse(dominio_ufficiale.verificabile(
            "lazioeuropa.it", dominio_ufficiale.TABELLA_SEED))
        self.assertTrue(dominio_ufficiale.verificabile("lazioeuropa.it", tabella))

    def test_costruzione_fallita_degrada_sul_seed(self):
        db = carica_modulo("db")

        def esplode():
            raise RuntimeError("PostgREST giu'")

        with patch.object(db, "select_fonti_per_domini", esplode):
            self.assertIsNone(monitoraggio._tabella_domini_del_giro())


class TestTabellaDomini(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_run_senza_tabella_la_costruisce_e_g4_passa(self):
        # Senza questa costruzione `g4_prova` ripiega su TABELLA_SEED e boccia
        # ogni ente fuori dai 20 host compilati: in produzione il caso guida
        # di §6.2 (bando 905315 su lazioeuropa.it) non passerebbe mai.
        dominio_ufficiale = carica_modulo("dominio_ufficiale")
        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}])

        html = ("<h1>Avviso</h1><p>I termini sono prorogati: le domande "
                "si presentano entro il 1&deg; dicembre 2026.</p>")

        async def scarica(url, **kw):
            return _Risposta(html=html)

        async def classifica(ctx):
            return [eventi.Evento(
                tipo="proroga", campo="data_scadenza", valore="2026-12-01",
                citazione="I termini sono prorogati: le domande si presentano "
                          "entro il 1° dicembre 2026",
                url_prova=ctx.pagine[0].url)]

        async def seconda(ctx):
            return await classifica(ctx)

        # Un «prima» c'e' (non e' il percorso G2'), quindi al G7 basta la
        # concordanza del secondo modello: l'unico gate che puo' ancora
        # respingere e' il G4, cioe' proprio quello che la tabella decide.
        riga = _bando(
            data_scadenza="2026-10-06",
            testo_norm="Avviso\n\nLe domande entro il 6 ottobre 2026.",
            impronta_contenuto="impronta-vecchia",
        )

        def giro(tabella_iniettata):
            async def esegui():
                dati = monitoraggio.FonteDati(righe=[dict(riga)])
                with patch.object(monitoraggio, "_tabella_domini_del_giro",
                                  lambda: tabella_iniettata):
                    return await monitoraggio.run(
                        attivo=True, impostazioni=_impostazioni(), fonte_dati=dati,
                        scarica=scarica, classifica=classifica, seconda_opinione=seconda,
                        lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
                    )
            return esegui()

        con_tabella = await giro(tabella)
        self.assertEqual(con_tabella["eventi"], 1, con_tabella)
        self.assertEqual(con_tabella["respinti"], 0)

        # Controprova: con la sola tabella compilata (il ripiego di `g4_prova`)
        # lo stesso identico evento viene respinto, e il motivo e' il G4.
        senza_tabella = await giro(None)
        self.assertEqual(senza_tabella["eventi"], 0)
        self.assertEqual(senza_tabella["respinti"], 1)


# --- tetti: i crediti Firecrawl devono poter mordere ------------------------

class TestTettoCrediti(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_i_crediti_dello_scarico_fanno_scattare_il_tetto(self):
        # Il monitor non conta i crediti da se': li prende dal client unico.
        # Senza `bilancio.unisci_scarico` resterebbero 0 e il tetto dei
        # crediti non potrebbe mai mordere, malgrado ogni ripiego Firecrawl
        # della pagina principale ne costi uno.
        spesi = SimpleNamespace(fetch=0, fetch_304=0, crediti_firecrawl=0, errori=0)

        async def scarica(url, **kw):
            spesi.fetch += 1
            spesi.crediti_firecrawl += 1
            return _Risposta(html="<h1>x</h1><p>testo</p>")

        def azzera():
            spesi.fetch = 0
            spesi.crediti_firecrawl = 0

        dati = _FonteSenzaLimite(righe=[_bando(id=i) for i in range(5)])
        with patch.object(monitoraggio, "_scarico_predefinito", lambda: scarica), \
                patch.object(monitoraggio, "_azzera_scarico", lambda: None), \
                patch.object(monitoraggio, "_contatori_scarico", lambda: spesi), \
                patch.object(monitoraggio, "_azzera_contatori_scarico", azzera):
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(tetto_crediti_giorno=2),
                fonte_dati=dati, classifica=_nessun_evento,
                lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
            )
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertIn("crediti", esito["motivo"])
        self.assertEqual(esito["controllati"], 2)


# --- classificatore di produzione -------------------------------------------

class TestClassificatore(unittest.IsolatedAsyncioTestCase):
    """Haiku con lo strumento di `eventi.py`, e il suo costo contato."""

    def test_senza_chiave_non_ce_n_e_uno(self):
        # Ed e' la ragione per cui `controlla` esce prima del fetch: un giro
        # senza modello non deve pagare una GET per riga.
        bilancio = carica_modulo("bilancio")
        self.assertIsNone(monitoraggio.classificatore_da_impostazioni(
            _impostazioni(anthropic_api_key=""), bilancio.Contatori()))
        self.assertIsNone(monitoraggio.classificatore_da_impostazioni(
            _impostazioni(), bilancio.Contatori()))

    async def test_la_chiamata_entra_nei_contatori(self):
        import anthropic

        bilancio = carica_modulo("bilancio")
        inviato = {}

        class _Messaggi:
            async def create(self, **kw):
                inviato.update(kw)
                return SimpleNamespace(
                    content=[SimpleNamespace(
                        type="tool_use", name="salva_eventi",
                        input={"eventi": [{
                            "tipo": "proroga", "valore": "2026-12-01",
                            "citazione": "prorogato al 1 dicembre 2026",
                            "url_prova": "https://ente.it/x"}]})],
                    usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                )

        class _Cliente:
            def __init__(self, api_key=None):
                self.messages = _Messaggi()

        contatori = bilancio.Contatori()
        impostazioni = _impostazioni(
            anthropic_api_key="chiave-finta",
            listino_modelli={"claude-haiku-4-5": (1.0, 5.0)},
        )
        with patch.object(anthropic, "AsyncAnthropic", _Cliente):
            classifica = monitoraggio.classificatore_da_impostazioni(impostazioni, contatori)
            self.assertIsNotNone(classifica)
            proposte = await classifica(eventi.Contesto(bando_id=1, oggi=OGGI))

        self.assertEqual(len(proposte), 1)
        self.assertEqual(proposte[0].tipo, "proroga")
        # Lo strumento e le istruzioni sono quelli di `eventi.py`, non copie.
        self.assertEqual(inviato["tools"], [eventi.STRUMENTO_SALVA_EVENTI])
        self.assertEqual(inviato["system"], eventi.ISTRUZIONI_CLASSIFICATORE)
        self.assertEqual(inviato["model"], monitoraggio.MODELLO_CLASSIFICATORE)
        # E il costo e' contato: e' cio' che alimenta il tetto in $.
        uso = contatori.modelli[monitoraggio.MODELLO_CLASSIFICATORE]
        self.assertEqual(uso.chiamate, 1)
        self.assertEqual(uso.token_ingresso, 1000)
        self.assertGreater(contatori.usd, 0)
        self.assertEqual(contatori.fuori_listino, ())


# --- dry-run: davvero a secco ----------------------------------------------

class TestDryRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_dry_run_non_scrive_niente(self):
        # Il vincolo del committente chiede che ogni sottocomando che scrive
        # abbia un `--dry-run` reale: non basta forzare l'ombra, perche'
        # `bando_controllo` e gli eventi interni si scriverebbero comunque.
        async def scarica(url, **kw):
            return _Risposta(html="<h1>Avviso</h1><p>termini prorogati al 1 dicembre 2026</p>")

        async def classifica(ctx):
            return [eventi.Evento(
                tipo="proroga", campo="data_scadenza", valore="2026-12-01",
                citazione="termini prorogati al 1 dicembre 2026",
                url_prova=ctx.pagine[0].url)]

        dati = monitoraggio.FonteDati(righe=[_bando(data_scadenza="2026-10-06")])
        esito = await monitoraggio.run(
            dry_run=True, attivo=True, impostazioni=_impostazioni(),
            fonte_dati=dati, scarica=scarica, classifica=classifica,
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
        )
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(esito["controllati"], 1)
        self.assertEqual(dati.scritture, [])
        self.assertEqual(dati.registrati, [])

    async def test_dry_run_non_registra_nemmeno_gli_errori(self):
        async def scarica(url, **kw):
            raise RuntimeError("timeout")

        dati = monitoraggio.FonteDati()
        esito = await monitoraggio.controlla(
            _bando(controlli_falliti=4), scarica=scarica, classifica=_nessun_evento,
            fonte_dati=dati, adesso=ADESSO, dry_run=True)
        self.assertEqual(esito.esito, "errore")
        self.assertEqual(dati.scritture, [])
        self.assertEqual(dati.registrati, [])


# --- G8 dentro il giro ------------------------------------------------------

class TestDedupNelloStessoControllo(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _zittisci_io(self)

    async def test_due_faq_identiche_una_sola_passa(self):
        # `faq` passa il G2 col solo link nuovo e non ha una data che il G5
        # possa usare per respingere la seconda: se il contesto non avanza
        # anche sugli eventi, il box «Aggiornamenti» mostra due volte la
        # stessa notizia.
        html = ("<h1>Avviso</h1><p>Sono online le FAQ dell'avviso.</p>"
                "<p><a href='https://www.lazioeuropa.it/faq.pdf'>FAQ</a></p>")

        async def scarica(url, **kw):
            return _Risposta(html=html)

        def proposta():
            return eventi.Evento(
                tipo="faq", citazione="Sono online le FAQ dell'avviso",
                url_prova="https://www.lazioeuropa.it/bandi/avviso-1/")

        async def classifica(ctx):
            return [proposta(), proposta()]

        dominio_ufficiale = carica_modulo("dominio_ufficiale")
        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}])
        riga = _bando(
            testo_norm="Avviso\n\nNessuna novita'.",
            impronta_contenuto="diversa-da-quella-nuova",
        )
        esito = await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classifica,
            fonte_dati=monitoraggio.FonteDati(), modalita="attivo",
            tabella_domini=tabella, adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(len(esito.eventi), 1, (esito.eventi, esito.respinti))
        self.assertEqual(len(esito.respinti), 1)
        falliti = [f["gate"] for f in esito.respinti[0]["giudizio"]["falliti"]]
        self.assertEqual(falliti, ["G8"])


# --- ingressi della riga di comando (§6.2) ----------------------------------

def _esito_in_memoria(ammesso):
    """Un `EsitoControllo` come lo lascia un giro appena concluso.

    Con questo il report vede anche i **respinti**, che `eventi.applica` non
    scrive mai a DB: e' la differenza fra le due sorgenti del comando.
    """
    voce = {
        "riga": {"tipo": "proroga", "campo": "data_scadenza",
                 "url_prova": "https://ente.it/x", "citazione": "prorogato"},
        "giudizio": {
            "gate": "G2'", "ammesso": ammesso, "confidenza": 0.9,
            "superati": ["G1", "G2'"],
            "falliti": [] if ammesso else [{"gate": "G7", "motivo": "nessuna prova"}],
        },
    }
    esito = monitoraggio.EsitoControllo(bando_id=1, fase="sportello")
    if ammesso:
        esito.eventi = (voce,)
    else:
        esito.respinti = (voce,)
    return esito


def _evento_db(**extra):
    """Una riga di `bando_evento` come la scrive `eventi.riga_evento`."""
    riga = {
        "id": 10,
        "bando_id": 905315,
        "tipo": "proroga",
        "campo": "data_scadenza",
        "valore_prima": {"data_scadenza": "2026-10-06"},
        "valore_dopo": {"data_scadenza": "2026-12-01"},
        "data_evento": "2026-09-18",
        "rilevato_at": "2026-09-23T06:00:00+00:00",
        "verificato": True,
        "leggibile": False,
        "applicato": False,
        "url_prova": "https://www.lazioeuropa.it/bandi/x",
        "citazione": "il termine e' prorogato al 1 dicembre 2026",
        "confidenza": 92,
        "gate": "G2'",
    }
    riga.update(extra)
    return riga


class TestReportOmbra(unittest.IsolatedAsyncioTestCase):
    """`report-ombra`: la misura che apre la tappa D."""

    async def test_csv_dalle_righe_di_bando_evento(self):
        uscita = io.StringIO()
        esito = await monitoraggio.run_report_ombra(
            righe=[_evento_db(), _evento_db(id=11, verificato=False)],
            uscita=uscita, campione=10,
        )
        testo = uscita.getvalue().splitlines()
        self.assertEqual(testo[0], ",".join(monitoraggio.INTESTAZIONI_REPORT))
        self.assertEqual(len(testo), 3)
        self.assertEqual(esito["eventi"], 2)
        self.assertEqual(esito["ammessi"], 1)
        self.assertEqual(esito["respinti"], 1)
        self.assertEqual(esito["precisione"], 0.5)
        self.assertEqual(esito["sorgente"], "bando_evento")

    async def test_campione_taglia_le_righe_non_la_lettura(self):
        uscita = io.StringIO()
        esito = await monitoraggio.run_report_ombra(
            righe=[_evento_db(id=i) for i in range(10)], uscita=uscita, campione=3)
        self.assertEqual(esito["eventi"], 3)
        self.assertEqual(len(uscita.getvalue().splitlines()), 4)

    async def test_tipo_filtra(self):
        esito = await monitoraggio.run_report_ombra(
            righe=[_evento_db(), _evento_db(id=11, tipo="faq")],
            uscita=io.StringIO(), tipo="faq",
        )
        self.assertEqual(esito["eventi"], 1)

    async def test_precisione_non_basta_senza_cento_eventi(self):
        # §6.2: 95 % **e** almeno 100 eventi. Una precisione del 100 % su tre
        # eventi non autorizza nessuna attivazione. Il verdetto si emette solo
        # dalla sorgente `esiti`, l'unica che vede anche i respinti.
        esito = await monitoraggio.run_report_ombra(
            esiti=[_esito_in_memoria(True) for _ in range(3)], uscita=io.StringIO())
        self.assertEqual(esito["precisione"], 1.0)
        self.assertFalse(esito["sufficiente"])
        esito = await monitoraggio.run_report_ombra(
            esiti=[_esito_in_memoria(True) for _ in range(120)],
            uscita=io.StringIO(), campione=120)
        self.assertTrue(esito["sufficiente"])

    async def test_da_bando_evento_senza_respinti_nessun_verdetto(self):
        # Un campione di soli ammessi viene da giri anteriori al 24/09/2026,
        # quando i respinti morivano con il processo: la precisione sarebbe
        # calcolata su una popolazione parziale e darebbe sempre 100%.
        # `sufficiente` **sparisce**, non vale `False`.
        esito = await monitoraggio.run_report_ombra(
            righe=[_evento_db(id=i) for i in range(120)],
            uscita=io.StringIO(), campione=120, dal=date(2026, 9, 1))
        self.assertNotIn("sufficiente", esito)
        self.assertIn("non ci sono respinti", esito["avvertenza"])

    async def test_da_bando_evento_con_respinti_il_verdetto_c_e(self):
        # Da quando `controlla` registra i respinti (`verificato=false` e il
        # campo `gate`), il comando autonomo misura i gate come la sorgente in
        # memoria: il verdetto deve tornare, altrimenti il periodo d'ombra non
        # si puo' chiudere mai.
        righe = [_evento_db(id=i) for i in range(114)]
        righe += [_evento_db(id=900 + i, verificato=False,
                            gate={"falliti": [{"gate": "G6", "motivo": "senza parola chiave"}]})
                  for i in range(6)]
        esito = await monitoraggio.run_report_ombra(
            righe=righe, uscita=io.StringIO(), campione=120, dal=date(2026, 9, 1))
        self.assertNotIn("avvertenza", esito)
        self.assertIn("sufficiente", esito)
        self.assertEqual(esito["eventi"], 120)
        self.assertEqual(esito["respinti"], 6)
        self.assertEqual(esito["precisione"], 0.95)
        self.assertTrue(esito["sufficiente"], esito)

    async def test_senza_g7_nessun_verdetto(self):
        esito = await monitoraggio.run_report_ombra(
            esiti=[_esito_in_memoria(True) for _ in range(120)],
            uscita=io.StringIO(), campione=120, g7_disponibile=False)
        self.assertNotIn("sufficiente", esito)
        self.assertIn("G7", esito["avvertenza"])

    async def test_gli_eventi_interni_non_entrano_nella_misura(self):
        # Con un `segnale_fonte` per riga cambiata a ogni giro il registro
        # sarebbe quasi solo interno, e la precisione misurerebbe quello.
        righe = monitoraggio.report_ombra_da_eventi([
            _evento_db(id=1),
            _evento_db(id=2, tipo="segnale_fonte", verificato=False),
            _evento_db(id=3, tipo="elaborazione_bloccata", verificato=False),
        ])
        self.assertEqual([r["bando_id"] for r in righe], [905315])

    async def test_dal_arriva_alla_lettura(self):
        # Senza `--dal` la lettura parte dagli `id` piu' bassi e il campione
        # resta per sempre quello dei primi eventi mai registrati.
        passati = {}

        def select_eventi(**kwargs):
            passati.update(kwargs)
            return []

        db = carica_modulo("db")
        with patch.object(db, "select_eventi", select_eventi):
            await monitoraggio.run_report_ombra(
                dal=date(2026, 9, 1), uscita=io.StringIO())
        self.assertEqual(passati["dal"], date(2026, 9, 1))

    async def test_senza_limit_si_legge_quanto_serve_al_campione(self):
        # `bando_evento` e' un registro che cresce e basta: un comando di
        # misura non deve poterselo portare via tutto.
        passati = {}

        def select_eventi(**kwargs):
            passati.update(kwargs)
            return []

        db = carica_modulo("db")
        with patch.object(db, "select_eventi", select_eventi):
            await monitoraggio.run_report_ombra(campione=25, uscita=io.StringIO())
        self.assertEqual(passati["limit"], 25)
        with patch.object(db, "select_eventi", select_eventi):
            await monitoraggio.run_report_ombra(
                campione=25, limit=500, uscita=io.StringIO())
        self.assertEqual(passati["limit"], 500)

    async def test_nessun_evento_non_e_una_bocciatura(self):
        esito = await monitoraggio.run_report_ombra(righe=[], uscita=io.StringIO())
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["saltato"], "nessun_evento")

    async def test_gate_come_giudizio_completo(self):
        # La colonna e' jsonb: se un giorno ci finisse l'intero giudizio, il
        # report deve leggerlo invece di rompersi.
        riga = _evento_db(gate={
            "gate": "G2", "superati": ["G1", "G2"], "confidenza": 0.87,
            "falliti": [{"gate": "G7", "motivo": "nessuna prova"}]})
        voce = monitoraggio.riga_report_da_evento(riga)
        self.assertEqual(voce["superati"], "G1,G2")
        self.assertEqual(voce["falliti"], "G7: nessuna prova")
        self.assertEqual(voce["confidenza"], 0.87)

    async def test_esiti_in_memoria_passano_dal_gemello(self):
        # Con gli esiti di un giro appena finito si vedono anche i respinti,
        # che a DB non arrivano mai.
        esito = await monitoraggio.run_report_ombra(
            esiti=[_esito_in_memoria(True), _esito_in_memoria(False)],
            uscita=io.StringIO(),
        )
        self.assertEqual(esito["sorgente"], "esiti")
        self.assertEqual(esito["eventi"], 2)
        self.assertEqual(esito["ammessi"], 1)


class TestApplicaEventi(unittest.IsolatedAsyncioTestCase):
    """`applica-eventi`: il riversamento a posteriori (§6.2)."""

    def setUp(self):
        zitto = patch.object(monitoraggio, "_scrivi_run", MagicMock())
        zitto.start()
        self.addCleanup(zitto.stop)

    async def _esegui(self, righe, **kwargs):
        applicati = []

        def applica(riga):
            applicati.append(riga.get("id"))
            return True

        kwargs.setdefault("lock", _lock_libero())
        kwargs.setdefault("impostazioni", _impostazioni())
        esito = await monitoraggio.run_applica_eventi(
            righe=righe, applica=applica, **kwargs)
        return esito, applicati

    async def test_ombra_per_difetto_non_applica_niente(self):
        esito, applicati = await self._esegui([_evento_db()])
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["applicati"], 0)
        self.assertEqual(applicati, [])
        self.assertEqual(esito["modalita"], "ombra")

    async def test_attivo_applica(self):
        esito, applicati = await self._esegui([_evento_db()], attivo=True)
        self.assertEqual(esito["applicati"], 1)
        self.assertEqual(applicati, [10])

    async def test_dry_run_e_piu_forte_di_attivo(self):
        esito, applicati = await self._esegui(
            [_evento_db()], attivo=True, dry_run=True)
        self.assertEqual(applicati, [])
        self.assertEqual(esito["modalita"], "ombra")

    async def test_blocco_massimo_cinquanta(self):
        # Il blocco e' il freno: senza, un solo giro riverserebbe mesi di
        # ombra e non ci sarebbe un giro intermedio per accorgersi di un
        # errore.
        righe = [_evento_db(id=i) for i in range(80)]
        esito, applicati = await self._esegui(righe, attivo=True)
        self.assertEqual(esito["blocco"], monitoraggio.BLOCCO_APPLICAZIONE)
        self.assertEqual(len(applicati), 50)

    async def test_limit_puo_solo_abbassare_il_blocco(self):
        righe = [_evento_db(id=i) for i in range(80)]
        esito, _ = await self._esegui(righe, attivo=True, limit=200)
        self.assertEqual(esito["blocco"], monitoraggio.BLOCCO_APPLICAZIONE)
        esito, applicati = await self._esegui(righe, attivo=True, limit=5)
        self.assertEqual(esito["blocco"], 5)
        self.assertEqual(len(applicati), 5)

    async def test_tipi_si_attivano_uno_alla_volta(self):
        righe = [_evento_db(id=1, tipo="proroga"),
                 _evento_db(id=2, tipo="sospensione"),
                 _evento_db(id=3, tipo="rettifica")]
        esito, applicati = await self._esegui(
            righe, attivo=True, tipi=("proroga", "rettifica"))
        self.assertEqual(applicati, [1, 3])
        self.assertEqual(esito["per_tipo"], {"proroga": 1, "rettifica": 1})

    async def test_non_verificati_e_gia_applicati_restano_fuori(self):
        righe = [_evento_db(id=1, verificato=False),
                 _evento_db(id=2, applicato=True),
                 _evento_db(id=3, tipo="segnale_fonte"),
                 _evento_db(id=4)]
        _, applicati = await self._esegui(righe, attivo=True)
        self.assertEqual(applicati, [4])

    async def test_dal_guarda_entrambe_le_date(self):
        # Stessa regola di `db.select_eventi` (`or_(data_evento.gte,
        # rilevato_at.gte)`): un evento **datato dall'ente** prima dell'ombra
        # ma **rilevato** dentro l'ombra entra comunque. Il filtro Python piu'
        # stretto del filtro SQL faceva di peggio che perderli: consumavano il
        # blocco da 50 e venivano scartati, e poiche' la lettura riparte dagli
        # `id` piu' bassi non applicati, il comando ripresentava all'infinito
        # lo stesso blocco applicando zero.
        righe = [_evento_db(id=1, data_evento="2026-08-01",
                            rilevato_at="2026-09-23T06:00:00+00:00"),
                 _evento_db(id=2, data_evento="2026-09-20")]
        _, applicati = await self._esegui(righe, attivo=True, dal=date(2026, 9, 1))
        self.assertEqual(applicati, [1, 2])

    async def test_dal_esclude_chi_e_vecchio_su_entrambe_le_date(self):
        righe = [_evento_db(id=1, data_evento="2026-08-01",
                            rilevato_at="2026-08-02T06:00:00+00:00"),
                 _evento_db(id=2, data_evento="2026-09-20")]
        _, applicati = await self._esegui(righe, attivo=True, dal=date(2026, 9, 1))
        self.assertEqual(applicati, [2])

    async def test_un_evento_senza_verificato_non_si_applica(self):
        # «Nel dubbio, falso»: una riga letta prima che la colonna esistesse
        # non e' una riga che ha superato i gate.
        righe = [_evento_db(id=1)]
        del righe[0]["verificato"]
        _, applicati = await self._esegui(righe, attivo=True)
        self.assertEqual(applicati, [])

    async def test_ombra_esplicita_vince_sull_ambiente(self):
        # `--ombra` con `MONITOR_MODALITA=attivo`: la CLI passa `attivo=False`
        # (esplicito), e non si applica niente.
        esito, applicati = await self._esegui(
            [_evento_db()], attivo=False,
            impostazioni=_impostazioni(monitor_modalita="attivo"))
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(applicati, [])
        # `None` invece significa «non detto»: decide l'ambiente.
        esito, applicati = await self._esegui(
            [_evento_db()], attivo=None,
            impostazioni=_impostazioni(monitor_modalita="attivo"))
        self.assertEqual(esito["modalita"], "attivo")
        self.assertEqual(applicati, [10])

    async def _da_db(self, pagine, *, rifiuti=(), **kwargs):
        """Il giro che legge davvero dalla selezione, con `db` sostituito."""
        visti = []

        def _eventi(**parametri):
            if "elaborazione_bloccata" in tuple(parametri.get("tipi") or ()):
                return [{"id": 900 + i, "riferisce_a": r}
                        for i, r in enumerate(rifiuti)]
            visti.append(dict(parametri))
            return list(pagine.get(parametri.get("offset"), []))

        applicati = []
        finto = MagicMock()
        finto.select_eventi.side_effect = _eventi
        kwargs.setdefault("lock", _lock_libero())
        kwargs.setdefault("impostazioni", _impostazioni())
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True), \
                patch.object(monitoraggio, "PAGINA_SELEZIONE_EVENTI", 5):
            esito = await monitoraggio.run_applica_eventi(
                applica=lambda riga: applicati.append(riga.get("id")) or True,
                **kwargs)
        return esito, applicati, visti

    async def test_applica_eventi_scorre_oltre_gli_eventi_rifiutati(self):
        """Gli eventi che la RPC ha gia' rifiutato non riconsumano il blocco.

        `bando_applica_evento` ritorna `false` su tre uscite (RPC assente,
        date incoerenti, transizione non ammessa prima della 06) lasciando
        `applicato=false`: l'evento resta all'id piu' basso e si riprendeva una
        fetta del blocco a ogni lancio. Con dodici eventi bloccati il blocco da
        50 diventava 38 per sempre; con cinquanta, «letti 50, candidati 50,
        applicati 0» — con exit 0.
        """
        pagine = {
            0: [_evento_db(id=i) for i in range(1, 6)],
            5: [_evento_db(id=i) for i in range(6, 9)],
        }
        esito, applicati, visti = await self._da_db(
            pagine, rifiuti=range(1, 6), attivo=True, limit=2)
        self.assertEqual(applicati, [6, 7])
        self.assertEqual(esito["bloccati"], 5)
        self.assertEqual(esito["attraversati"], 7)
        self.assertEqual([v.get("offset") for v in visti[:2]], [0, 5])

    async def test_applica_eventi_limit_conta_le_righe_da_applicare(self):
        # I filtri Python (tipo interno, non verificato, gia' applicato)
        # scartavano righe DOPO il limite della select: il `--limit` contava
        # le righe lette, non quelle da applicare.
        pagine = {
            0: [_evento_db(id=i, verificato=False) for i in range(1, 6)],
            5: [_evento_db(id=i) for i in range(6, 9)],
        }
        esito, applicati, visti = await self._da_db(pagine, attivo=True, limit=2)
        self.assertEqual(applicati, [6, 7])
        self.assertEqual(esito["letti"], 2)
        self.assertEqual(esito["candidati"], 2)
        # Alla query si chiede una pagina (ridotta a 5 dal patch), non il 2
        # dell'operatore.
        self.assertEqual(visti[0].get("limit"), 5)

    async def test_i_rifiuti_della_rpc_si_vedono_nel_riepilogo(self):
        # Un blocco fermo non deve somigliare a un giro riuscito.
        esito = await monitoraggio.run_applica_eventi(
            righe=[_evento_db(id=1), _evento_db(id=2)], attivo=True,
            applica=lambda riga: False,
            lock=_lock_libero(), impostazioni=_impostazioni(),
        )
        self.assertEqual(esito["applicati"], 0)
        self.assertEqual(esito["rifiutati"], 2)

    async def test_lock_occupato_esce_senza_applicare(self):
        finto = MagicMock()
        finto.acquisisci.return_value = blocco.Blocco("monitor", "altro", blocco.OCCUPATO)
        finto.esito_saltato.side_effect = blocco.esito_saltato
        esito, applicati = await self._esegui(
            [_evento_db()], attivo=True, lock=finto)
        self.assertTrue(esito["saltato_per_lock"])
        self.assertEqual(applicati, [])

    async def test_un_guasto_non_solleva(self):
        esplosivo = MagicMock()
        esplosivo.acquisisci.return_value = blocco.Blocco(
            "monitor", "test", blocco.ACQUISITO)
        esplosivo.rilascia.return_value = True
        with patch.object(monitoraggio, "applica_eventi",
                          side_effect=RuntimeError("giu'")):
            esito = await monitoraggio.run_applica_eventi(
                righe=[_evento_db()], attivo=True, lock=esplosivo,
                impostazioni=_impostazioni(), applica=lambda r: True)
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(esito["applicati"], 0)
        esplosivo.rilascia.assert_called_once()


# --- i rifiuti che la RPC non annota (F1) -----------------------------------

class _DbEventi:
    """Il minimo di `app.db` che `applica-eventi` usa, con `bando_evento` in
    memoria. Nessuna rete e nessun DB: la RPC e' una funzione che dice `False`,
    com'e' `bando_applica_evento` prima della migrazione 06."""

    TABELLA_EVENTO = "bando_evento"

    #: I tre esiti, come in `db`. Il finto li espone perche' la differenza fra
    #: «la RPC ha detto no» e «la RPC non c'era» decide se il rifiuto viene
    #: annotato — e l'annotazione non si puo' disfare.
    ESITO_APPLICATO = "applicato"
    ESITO_RIFIUTATO = "rifiutato"
    ESITO_NON_TENTATO = "non_tentato"

    def __init__(self, eventi, *, esito_rpc="rifiutato", ha_riferisce_a=True):
        self.eventi = [dict(e) for e in eventi]
        self.esito_rpc = esito_rpc
        self.inseriti: list[dict] = []
        self.colonne_chieste: list[tuple] = []
        # `db.controllo`: lo schema com'e' oggi, senza rete.
        self.controllo = SimpleNamespace(
            ha=lambda _tabella, colonna: colonna != "riferisce_a" or ha_riferisce_a)
        # Le due scritture dell'attivazione sono due: la RPC e la visibilita'.
        self.resi_leggibili: list[tuple] = []

    def select_eventi(self, *, tipi=(), dal=None, applicato=None, verificato=None,
                      leggibile=None, bando_id=None, con_riferimento=None,
                      limit=None, offset=0, colonne=None, **_):
        self.colonne_chieste.append(tuple(colonne or ()))
        righe = list(self.eventi)
        if tipi:
            righe = [r for r in righe if r.get("tipo") in tuple(tipi)]
        if con_riferimento is not None:
            righe = [r for r in righe
                     if (r.get("riferisce_a") is not None) is con_riferimento]
        if applicato is not None:
            righe = [r for r in righe if bool(r.get("applicato")) is applicato]
        if verificato is not None:
            righe = [r for r in righe if bool(r.get("verificato")) is verificato]
        if leggibile is not None:
            righe = [r for r in righe if bool(r.get("leggibile")) is leggibile]
        if bando_id is not None:
            righe = [r for r in righe if r.get("bando_id") == bando_id]
        righe.sort(key=lambda r: r.get("id"))
        righe = righe[max(0, int(offset or 0)):]
        if limit is not None:
            righe = righe[:int(limit)]
        return [dict(r) for r in righe]

    def applica_evento_esito(self, evento_id, **_):
        return self.esito_rpc

    def rendi_evento_leggibile(self, evento_id, *, in_aggiornamenti=True, **_):
        # La seconda scrittura dell'attivazione: senza, l'evento resta senza
        # cursore e il box «Aggiornamenti» non lo mostra.
        self.resi_leggibili.append((evento_id, in_aggiornamenti))
        return {"scritto": True, "ignorate": (), "motivo": ""}

    def applica_evento(self, evento_id, **_):
        return self.esito_rpc == self.ESITO_APPLICATO

    def registra_evento(self, evento, **_):
        nuovo = dict(evento, id=10_000 + len(self.inseriti))
        self.inseriti.append(nuovo)
        self.eventi.append(nuovo)
        return True


class TestRifiutiAnnotati(unittest.IsolatedAsyncioTestCase):
    """Un rifiuto che la RPC non annota deve annotarselo Python (§6.2).

    `bando_applica_evento` scrive l'`elaborazione_bloccata` con `riferisce_a`
    **solo** sul ramo `data_pubblicazione > data_scadenza` (04:468-487). Gli
    altri tre esiti che lasciano `applicato=false` — transizione non ammessa
    (23514, che `db.applica_evento` trasforma in `False`), `sospeso`/`revocato`
    prima della 06 (`RETURN false` con la sola `RAISE NOTICE`), RPC assente —
    non scrivono niente. Senza marcatore quegli eventi restano agli id piu'
    bassi, passano `applicabile()` e riconsumano il blocco a ogni lancio.
    """

    def setUp(self):
        zitto = patch.object(monitoraggio, "_scrivi_run", MagicMock())
        zitto.start()
        self.addCleanup(zitto.stop)

    #: Il tipo dei casi: `proroga`, non `revoca`. Il rifiuto di una revoca
    #: prima della migrazione 06 e' un'attesa, non un giudizio, e non va
    #: annotato (vedi `TestRifiutiNonDefinitivi`); quello di una proroga che la
    #: tabella delle transizioni non ammette e' definitivo.
    @staticmethod
    def _eventi(quanti=50, tipo="proroga"):
        return [{"id": i, "bando_id": 500 + i, "tipo": tipo, "campo": "stato",
                 "verificato": True, "applicato": False,
                 "rilevato_at": "2026-09-01T06:00:00+00:00"}
                for i in range(1, quanti + 1)]

    async def _lancia(self, finto, **kwargs):
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True):
            kwargs.setdefault("lock", _lock_libero())
            kwargs.setdefault("impostazioni", _impostazioni())
            return await monitoraggio.run_applica_eventi(**kwargs)

    async def test_due_lanci_di_fila_non_ripetono_lo_stesso_blocco(self):
        """`applica-eventi --tipo proroga --attivo --limit 50`, due volte.

        Prima: «letti: 50, candidati: 50, applicati: 0, rifiutati: 50,
        bloccati: 0» **identico** al primo lancio, per sempre. Il marcatore
        deve sopravvivere al processo, e per questo e' una riga in tabella e
        non un cursore in memoria.
        """
        finto = _DbEventi(self._eventi())
        primo = await self._lancia(
            finto, attivo=True, limit=50, tipi=("proroga",))
        secondo = await self._lancia(
            finto, attivo=True, limit=50, tipi=("proroga",))

        # Il primo lancio non applica niente e li rifiuta tutti: e' la RPC che
        # risponde `false`, cioe' un rifiuto vero.
        self.assertEqual(
            (primo["candidati"], primo["applicati"], primo["rifiutati"]),
            (50, 0, 50))
        # Il secondo non ripropone niente: gli stessi cinquanta eventi sono
        # ora riconosciuti come gia' rifiutati e scavalcati.
        self.assertEqual(
            (secondo["candidati"], secondo["rifiutati"], secondo["bloccati"]),
            (0, 0, 50),
            "il secondo lancio ripete il primo: il blocco da 50 resta "
            "consumato dagli stessi eventi a ogni lancio")
        # L'annotazione e' cio' che sopravvive al processo, e non si
        # moltiplica: una per evento, non una per giro.
        self.assertEqual(primo["segnalati"], 50)
        self.assertEqual(secondo["segnalati"], 0)
        self.assertEqual(len(finto.inseriti), 50)

    async def test_l_annotazione_punta_all_evento_ed_e_interna(self):
        finto = _DbEventi(self._eventi(quanti=1))
        await self._lancia(finto, attivo=True, limit=1, tipi=("proroga",))
        annotazione = finto.inseriti[0]
        self.assertEqual(annotazione["tipo"], "elaborazione_bloccata")
        # `riferisce_a` e' la forma che usa gia' la RPC: `eventi_gia_rifiutati`
        # ne legge una sola, non due.
        self.assertEqual(annotazione["riferisce_a"], 1)
        self.assertEqual(annotazione["bando_id"], 501)
        self.assertEqual(annotazione["valore_dopo"]["evento_id"], 1)
        # Interno per definizione (§13.5): mai leggibile, mai verificato — il
        # CHECK `bando_evento_verificato_prova_check` vorrebbe prova e citazione.
        self.assertFalse(annotazione["leggibile"])
        self.assertFalse(annotazione["verificato"])
        self.assertFalse(annotazione["in_aggiornamenti"])
        self.assertIn(annotazione["origine"], ("pipeline", "worker", "cron"))

    async def test_non_si_annota_due_volte_lo_stesso_rifiuto(self):
        # Il ramo delle date annota da se' (04:468-487): Python non deve
        # aggiungere una seconda riga. `elaborazione_bloccata` sta fuori dal
        # dedup parziale della 02, quindi il DB non lo impedirebbe.
        finto = _DbEventi(self._eventi(quanti=1))
        finto.eventi.append({
            "id": 900, "bando_id": 501, "tipo": "elaborazione_bloccata",
            "riferisce_a": 1, "applicato": False, "verificato": False,
        })
        esito = await self._lancia(finto, attivo=True, limit=1, tipi=("proroga",))
        # Gia' noto: non si riprova nemmeno ad applicarlo.
        self.assertEqual(esito["bloccati"], 1)
        self.assertEqual(finto.inseriti, [])

    async def test_in_dry_run_non_si_scrive_e_il_lancio_dopo_ripete(self):
        """In `--dry-run` non si applica niente, quindi non c'e' niente da
        annotare: il lancio successivo ripresenta gli stessi candidati, ed e'
        giusto cosi'."""
        finto = _DbEventi(self._eventi(quanti=3))
        primo = await self._lancia(
            finto, attivo=True, dry_run=True, limit=50, tipi=("proroga",))
        secondo = await self._lancia(
            finto, attivo=True, dry_run=True, limit=50, tipi=("proroga",))
        self.assertEqual(primo["candidati"], 3)
        self.assertEqual(primo["segnalati"], 0)
        self.assertEqual(finto.inseriti, [])
        self.assertEqual(secondo["candidati"], 3)
        self.assertEqual(secondo["bloccati"], 0)

    async def test_chi_inietta_applica_non_scrive_niente_da_solo(self):
        # I test e la pipeline che passano il proprio `applica` portano anche
        # la propria annotazione: `run_applica_eventi` non scrive per loro.
        finto = _DbEventi(self._eventi(quanti=2))
        esito = await self._lancia(
            finto, attivo=True, limit=2, tipi=("proroga",),
            applica=lambda riga: False)
        self.assertEqual(esito["rifiutati"], 2)
        self.assertEqual(esito["segnalati"], 0)
        self.assertEqual(finto.inseriti, [])

    async def test_un_segnala_iniettato_viene_chiamato_una_volta_per_rifiuto(self):
        visti = []
        finto = _DbEventi(self._eventi(quanti=2))
        esito = await self._lancia(
            finto, attivo=True, limit=2, tipi=("proroga",),
            applica=lambda riga: False,
            segnala=lambda riga: visti.append(riga.get("id")) or True)
        self.assertEqual(visti, [1, 2])
        self.assertEqual(esito["segnalati"], 2)

    async def test_un_annotazione_che_fallisce_non_ferma_il_giro(self):
        finto = _DbEventi(self._eventi(quanti=2))
        esito = await self._lancia(
            finto, attivo=True, limit=2, tipi=("proroga",),
            applica=lambda riga: False,
            segnala=MagicMock(side_effect=RuntimeError("PostgREST giu'")))
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["rifiutati"], 2)
        self.assertEqual(esito["segnalati"], 0)

    async def test_gli_applicati_non_vengono_annotati(self):
        finto = _DbEventi(self._eventi(quanti=2), esito_rpc=True)
        esito = await self._lancia(finto, attivo=True, limit=2, tipi=("proroga",))
        self.assertEqual(esito["applicati"], 2)
        self.assertEqual(finto.inseriti, [])

    async def test_senza_la_colonna_riferisce_a_non_si_scrive_niente(self):
        # `db.registra_evento` scarta le chiavi che lo schema non espone: un
        # marcatore senza `riferisce_a` sarebbe invisibile a
        # `eventi_gia_rifiutati`, e `bando_evento` crescerebbe di una riga per
        # evento a ogni lancio senza sbloccare niente.
        finto = _DbEventi(self._eventi(quanti=2), ha_riferisce_a=False)
        esito = await self._lancia(finto, attivo=True, limit=2, tipi=("proroga",))
        self.assertEqual(esito["rifiutati"], 2)
        self.assertEqual(esito["segnalati"], 0)
        self.assertEqual(finto.inseriti, [])

    def test_l_annotazione_si_costruisce_anche_senza_bando(self):
        # Un evento senza `bando_id` non puo' essere annotato (`NOT NULL` e
        # chiave esterna): si dice `False`, non si solleva.
        self.assertFalse(monitoraggio._segnala_rifiuto({"id": 1}))
        self.assertFalse(monitoraggio._segnala_rifiuto({"bando_id": 7}))


# --- rifiuti gia' noti: una colonna sola, e oltre le mille righe (F10) -------

class _ClientPostgrest:
    """Un client finto con il tetto del server: `max-rows` = 1 000.

    E' il punto del difetto: una `.limit(2000)` non solleva e non avvisa,
    restituisce mille righe come se fossero tutte.
    """

    TETTO = 1000

    def __init__(self, righe):
        self.righe = [dict(r) for r in righe]
        self.pagine: list[tuple] = []
        self.colonne = ""
        self.filtri: list[tuple] = []
        self._quanto = None
        self._salto = 0
        self._negato = False

    def table(self, _nome):
        self._quanto, self._salto = None, 0
        self.filtri = []
        self._negato = False
        return self

    def select(self, colonne):
        self.colonne = colonne
        return self

    def in_(self, _colonna, _valori):
        return self

    def eq(self, _colonna, _valore):
        return self

    def is_(self, colonna, valore):
        """`is null`. Con la negazione davanti diventa «ha un valore»."""
        self.filtri.append(("is" if not self._negato else "not_is", colonna, valore))
        self._negato = False
        return self

    @property
    def not_(self):
        """`query.not_.is_(...)`: in postgrest la negazione e' un attributo."""
        self._negato = True
        return self

    def order(self, _colonna):
        return self

    def limit(self, quanto):
        self._quanto = int(quanto)
        return self

    def range(self, inizio, fine):
        self._salto = int(inizio)
        self._quanto = int(fine) - int(inizio) + 1
        return self

    def execute(self):
        righe = list(self.righe)
        for genere, colonna, _valore in self.filtri:
            if genere == "not_is":
                righe = [r for r in righe if r.get(colonna) is not None]
            elif genere == "is":
                righe = [r for r in righe if r.get(colonna) is None]
        quanto = min(self._quanto or self.TETTO, self.TETTO)
        fetta = righe[self._salto:self._salto + quanto]
        self.pagine.append((self._salto, quanto, len(fetta)))
        return SimpleNamespace(data=[dict(r) for r in fetta])


SCHEMA_EVENTI = {
    "definitions": {"bando_evento": {"properties": {nome: {} for nome in (
        "id", "bando_id", "tipo", "campo", "valore_prima", "valore_dopo",
        "data_evento", "rilevato_at", "applicato", "verificato", "leggibile",
        "url_prova", "citazione", "confidenza", "gate", "riferisce_a")}}},
    "paths": {"/bando_evento": {}, "/rpc/bando_applica_evento": {}},
}


class TestRifiutiNonDefinitivi(unittest.IsolatedAsyncioTestCase):
    """Un rifiuto che non e' un giudizio non va annotato: l'annotazione e' per sempre.

    `bando_evento` non concede DELETE nemmeno a `service_role` (migrazione 02,
    `REVOKE DELETE, TRUNCATE`) e il trigger di immutabilita' vieta di cambiare
    `riferisce_a`: una volta scritta, l'annotazione non si disfa e
    `eventi_gia_rifiutati` scavalca quell'evento per sempre. Quindi si annota
    solo cio' che nessuna migrazione futura potrebbe sbloccare.

    Due casi che sembrano rifiuti e non lo sono:

    * **RPC assente** (migrazione 04 non applicata). `db.applica_evento` tornava
      `False` con un semplice log, indistinguibile da un rifiuto vero: un solo
      `applica-eventi --attivo` lanciato prima della 04 avrebbe annotato tutto
      l'arretrato dell'ombra, e la 04 non l'avrebbe piu' recuperato.
    * **`sospensione`/`revoca` prima della migrazione 06**. La 04 li respinge
      per costruzione (`RETURN false` con la sola `RAISE NOTICE`) finche' il
      CHECK di `stato_bando` non ammette cinque valori. Sono esattamente gli
      eventi che la 06 serve ad applicare.
    """

    def setUp(self):
        zitto = patch.object(monitoraggio, "_scrivi_run", MagicMock())
        zitto.start()
        self.addCleanup(zitto.stop)

    @staticmethod
    def _eventi(quanti=5, tipo="revoca"):
        return [{"id": i, "bando_id": 500 + i, "tipo": tipo, "campo": "stato",
                 "verificato": True, "applicato": False,
                 "rilevato_at": "2026-09-01T06:00:00+00:00"}
                for i in range(1, quanti + 1)]

    async def _lancia(self, finto, **kwargs):
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True):
            kwargs.setdefault("lock", _lock_libero())
            kwargs.setdefault("impostazioni", _impostazioni())
            return await monitoraggio.run_applica_eventi(**kwargs)

    async def test_rpc_assente_non_e_un_rifiuto_e_la_04_recupera_tutto(self):
        """Primo lancio senza la 04, secondo con la 04: gli eventi si applicano.

        Prima della correzione il primo lancio annotava cinque rifiuti e il
        secondo trovava cinque `bloccati` e zero applicati — in modo
        irreversibile, perche' le annotazioni non si cancellano.
        """
        finto = _DbEventi(self._eventi(tipo="proroga"),
                          esito_rpc=_DbEventi.ESITO_NON_TENTATO)
        primo = await self._lancia(finto, attivo=True, limit=5, tipi=("proroga",))
        self.assertEqual(primo["applicati"], 0)
        self.assertEqual(primo["rifiutati"], 0)
        self.assertEqual(primo["non_tentati"], 5)
        self.assertEqual(primo["segnalati"], 0)
        self.assertEqual(finto.inseriti, [], "un non-tentativo e' stato annotato "
                                             "come rifiuto: e' irreversibile")

        finto.esito_rpc = _DbEventi.ESITO_APPLICATO
        secondo = await self._lancia(finto, attivo=True, limit=5, tipi=("proroga",))
        self.assertEqual(secondo["candidati"], 5)
        self.assertEqual(secondo["applicati"], 5)
        self.assertEqual(secondo["bloccati"], 0)

    async def test_un_eccezione_non_e_un_rifiuto(self):
        def _solleva(_riga):
            raise RuntimeError("rete giu'")

        finto = _DbEventi(self._eventi(quanti=2, tipo="proroga"))
        esito = await self._lancia(
            finto, attivo=True, limit=2, tipi=("proroga",),
            applica=_solleva, segnala=lambda riga: True)
        self.assertEqual(esito["non_tentati"], 2)
        self.assertEqual(esito["rifiutati"], 0)
        self.assertEqual(esito["segnalati"], 0)

    async def test_revoca_prima_della_06_non_viene_annotata(self):
        """Il rifiuto di una revoca e' un calendario, non un giudizio."""
        finto = _DbEventi(self._eventi(tipo="revoca"))
        primo = await self._lancia(finto, attivo=True, limit=5, tipi=("revoca",))
        self.assertEqual(primo["rifiutati"], 5)
        self.assertEqual(primo["segnalati"], 0)
        self.assertEqual(finto.inseriti, [])
        # E il lancio successivo li ripresenta: e' il comportamento giusto,
        # perche' dopo la 06 dovranno essere applicati.
        secondo = await self._lancia(finto, attivo=True, limit=5, tipi=("revoca",))
        self.assertEqual(secondo["candidati"], 5)
        self.assertEqual(secondo["bloccati"], 0)

    async def test_dopo_la_06_la_revoca_rifiutata_si_annota(self):
        finto = _DbEventi(self._eventi(tipo="revoca"))
        esito = await self._lancia(
            finto, attivo=True, limit=5, tipi=("revoca",),
            impostazioni=_impostazioni(monitor_stati_estesi=True))
        self.assertEqual(esito["rifiutati"], 5)
        self.assertEqual(esito["segnalati"], 5)

    async def test_la_rettifica_che_propone_uno_stato_nuovo_aspetta_la_06(self):
        righe = self._eventi(quanti=1, tipo="rettifica")
        righe[0]["valore_dopo"] = {"stato_proposto": "sospeso"}
        finto = _DbEventi(righe)
        esito = await self._lancia(finto, attivo=True, limit=1, tipi=("rettifica",))
        self.assertEqual(esito["rifiutati"], 1)
        self.assertEqual(esito["segnalati"], 0)

    async def test_riprova_rifiutati_rimette_in_coda_le_annotazioni(self):
        """La via di rientro: le annotazioni non si possono cancellare."""
        finto = _DbEventi(self._eventi(quanti=3, tipo="proroga"))
        await self._lancia(finto, attivo=True, limit=3, tipi=("proroga",))
        self.assertEqual(len(finto.inseriti), 3)
        bloccato = await self._lancia(finto, attivo=True, limit=3, tipi=("proroga",))
        self.assertEqual(bloccato["candidati"], 0)
        ripescato = await self._lancia(
            finto, attivo=True, limit=3, tipi=("proroga",), riprova_rifiutati=True)
        self.assertEqual(ripescato["candidati"], 3)
        self.assertTrue(ripescato["riprova_rifiutati"])

    def test_gli_esiti_coincidono_con_quelli_di_db(self):
        """Le tre stringhe sono ricopiate: se divergono, un non-tentativo
        tornerebbe a passare per rifiuto."""
        db = carica_modulo("db")
        self.assertEqual(monitoraggio.ESITO_APPLICATO, db.ESITO_APPLICATO)
        self.assertEqual(monitoraggio.ESITO_RIFIUTATO, db.ESITO_RIFIUTATO)
        self.assertEqual(monitoraggio.ESITO_NON_TENTATO, db.ESITO_NON_TENTATO)

    def test_il_booleano_dei_chiamanti_storici_resta_un_rifiuto(self):
        self.assertEqual(monitoraggio._esito_applicazione(False),
                         monitoraggio.ESITO_RIFIUTATO)
        self.assertEqual(monitoraggio._esito_applicazione(True),
                         monitoraggio.ESITO_APPLICATO)


class TestRifiutiNoti(unittest.TestCase):
    """`eventi_gia_rifiutati`: legge poco, e legge tutto (§6.2)."""

    def _leggi(self, righe):
        """`eventi_gia_rifiutati` con il `db` vero ma client e schema finti."""
        db = carica_modulo("db")
        client = _ClientPostgrest(righe)
        vero = db.select_eventi
        strumento = db.Controllo(fornitore_schema=lambda: SCHEMA_EVENTI)

        def _select(**parametri):
            return vero(client=client, strumento=strumento, **parametri)

        with patch.object(db, "select_eventi", _select):
            return monitoraggio.eventi_gia_rifiutati(), client

    def test_si_chiede_una_colonna_sola(self):
        # La lettura parte a ogni lancio, anche in `--dry-run`: portarsi
        # dietro `valore_dopo`, `citazione` e il `gate` jsonb di duemila righe
        # per estrarre un intero era la parte piu' cara del comando.
        _, client = self._leggi([{"id": 1, "riferisce_a": 7}])
        self.assertEqual(sorted(client.colonne.split(",")), ["id", "riferisce_a"])
        self.assertNotIn("valore_dopo", client.colonne)
        self.assertNotIn("citazione", client.colonne)
        self.assertNotIn("gate", client.colonne)

    def test_oltre_le_mille_righe_la_lista_resta_completa(self):
        # `TETTO_RIFIUTI_NOTI` e' 2 000 e il tetto del server e' 1 000: con una
        # `.limit(2000)` gli eventi bloccati dal 1 001esimo in poi sparivano
        # dalla lista e tornavano a riconsumare il blocco a ogni lancio.
        righe = [{"id": i, "riferisce_a": 100_000 + i} for i in range(1, 1501)]
        noti, client = self._leggi(righe)
        self.assertEqual(len(noti), 1500)
        self.assertIn(100_000 + 1500, noti)
        # Due pagine, la seconda con il salto: i builder di postgrest
        # accumulano i parametri, quindi ogni pagina e' una query nuova.
        self.assertEqual([p[0] for p in client.pagine], [0, 1000])

    def test_il_troncamento_al_tetto_si_dichiara(self):
        # Il tetto e' l'unico limite dichiarato: se morde, la lista e' una
        # FETTA e gli eventi che ne restano fuori tornano in coda per sempre.
        # Non poterlo sapere e' peggio del troncamento.
        righe = [{"id": i, "riferisce_a": 100_000 + i}
                 for i in range(1, monitoraggio.TETTO_RIFIUTI_NOTI + 200)]
        registro = MagicMock()
        with patch.object(monitoraggio, "logger", registro):
            noti, _ = self._leggi(righe)
        self.assertEqual(len(noti), monitoraggio.TETTO_RIFIUTI_NOTI)
        detti = [a for chiamata in registro.warning.call_args_list
                 for a in chiamata.args]
        self.assertIn(monitoraggio.ALLARME_RIFIUTI_TRONCATI, detti)


# --- contatori del giro e allarmi nel riepilogo ------------------------------

class TestContatoriEAllarmi(unittest.IsolatedAsyncioTestCase):
    """`run(contatori=...)` e la riga «allarmi» del riepilogo (§6.2)."""

    def setUp(self):
        _zittisci_io(self)

    async def _giro(self, *, contatori=None, dati=None, **extra):
        async def scarica(url, **kw):
            return _Risposta(html="<h1>x</h1><p>testo</p>")

        return await monitoraggio.run(
            impostazioni=_impostazioni(**extra),
            fonte_dati=dati if dati is not None else monitoraggio.FonteDati(
                righe=[_bando(id=1)]),
            scarica=scarica, classifica=_nessun_evento, contatori=contatori,
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
        )

    async def test_il_giro_usa_i_contatori_del_chiamante(self):
        # E' cio' che permette alla seconda opinione — costruita FUORI da
        # `run` — di far entrare il proprio costo nei tetti di questo giro.
        bilancio = carica_modulo("bilancio")
        miei = bilancio.Contatori()
        esito = await self._giro(contatori=miei)
        self.assertEqual(esito["classificazioni"], 1)
        self.assertEqual(miei.classificazioni, 1)

    async def test_il_costo_gia_speso_dal_chiamante_conta_per_il_tetto(self):
        # La seconda opinione registra in questi contatori PRIMA che `run`
        # li guardi: se il giro ne creasse di propri, il tetto in $ non
        # vedrebbe mai le chiamate piu' care del monitor.
        bilancio = carica_modulo("bilancio")
        miei = bilancio.Contatori()
        bilancio.registra_chiamata(
            miei, monitoraggio.MODELLO_SECONDA_OPINIONE,
            {"input_tokens": 1_000_000, "output_tokens": 0},
            {monitoraggio.MODELLO_SECONDA_OPINIONE: (3.0, 15.0)})
        self.assertGreater(miei.usd, 1.5)
        esito = await self._giro(contatori=miei, tetto_usd_giorno=1.5)
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertIn("usd", esito["motivo"])
        self.assertIn(esito["motivo"], esito["allarmi"])

    async def test_senza_contatori_il_giro_se_li_crea(self):
        esito = await self._giro()
        self.assertEqual(esito["classificazioni"], 1)

    async def test_il_riepilogo_porta_gli_allarmi_della_selezione(self):
        # La coda troncata viveva solo in una riga di log: ora e' un allarme
        # del giro, quindi finisce anche in `pipeline_run.contatori`.
        class _CodaPiena(monitoraggio.FonteDati):
            def candidati(self, *, limite=0, adesso=None, forza=False):
                self.allarmi = ["coda del monitor troncata a 5000 righe"]
                return []

        esito = await self._giro(dati=_CodaPiena())
        self.assertEqual(esito["allarmi"], ["coda del monitor troncata a 5000 righe"])

    async def test_senza_allarmi_la_riga_resta_vuota(self):
        esito = await self._giro()
        self.assertEqual(esito["allarmi"], [])


# --- seconda opinione di produzione (G7) ------------------------------------

class _Risposta_LLM:
    """Risposta dell'SDK con un solo blocco `tool_use`."""

    def __init__(self, voci, ingresso=1000, uscita=200):
        self.content = [SimpleNamespace(
            type="tool_use", name="salva_eventi", input={"eventi": list(voci)})]
        self.usage = SimpleNamespace(input_tokens=ingresso, output_tokens=uscita)


def _voce(campo="data_scadenza", valore="2026-12-01"):
    return {"tipo": "rettifica", "campo": campo, "valore": valore,
            "citazione": "differimento dei termini", "url_prova": "https://ente.it/x"}


class _ClienteFinto:
    """`anthropic.AsyncAnthropic` di prova: registra le chiamate, non ne fa."""

    def __init__(self, risposte=None, errore=None):
        self.chiamate = []
        self._risposte = list(risposte or [])
        self._errore = errore

        cliente = self

        class _Messaggi:
            async def create(self, **kw):
                cliente.chiamate.append(kw)
                if cliente._errore is not None:
                    raise cliente._errore
                return (cliente._risposte.pop(0) if cliente._risposte
                        else _Risposta_LLM([_voce()]))

        self.messages = _Messaggi()


def _con_cliente(caso, cliente):
    import anthropic
    bersaglio = patch.object(anthropic, "AsyncAnthropic", lambda api_key=None: cliente)
    bersaglio.start()
    caso.addCleanup(bersaglio.stop)


class TestSecondaOpinione(unittest.IsolatedAsyncioTestCase):
    """Sonnet sullo stesso contesto: la seconda prova del G7 (§6.2)."""

    def _impostazioni_con_chiave(self, **extra):
        return _impostazioni(
            anthropic_api_key="chiave-finta",
            listino_modelli={monitoraggio.MODELLO_SECONDA_OPINIONE: (3.0, 15.0)},
            **extra)

    def test_senza_chiave_niente_seconda_opinione(self):
        # E' cio' che tiene il comportamento uguale a quello di oggi: senza
        # chiave il G7 resta soddisfacibile solo con una prova indipendente.
        bilancio = carica_modulo("bilancio")
        self.assertIsNone(monitoraggio.seconda_opinione_da_impostazioni(
            _impostazioni(anthropic_api_key=""), bilancio.Contatori()))
        self.assertIsNone(monitoraggio.seconda_opinione_da_impostazioni(
            _impostazioni(), bilancio.Contatori()))

    async def test_la_chiamata_entra_nei_contatori(self):
        bilancio = carica_modulo("bilancio")
        cliente = _ClienteFinto()
        _con_cliente(self, cliente)
        contatori = bilancio.Contatori()
        seconda = monitoraggio.seconda_opinione_da_impostazioni(
            self._impostazioni_con_chiave(), contatori)
        self.assertIsNotNone(seconda)

        letti = await seconda(eventi.Contesto(bando_id=1, oggi=OGGI))

        self.assertEqual([e.tipo for e in letti], ["rettifica"])
        inviato = cliente.chiamate[0]
        # Stesso strumento e stesse istruzioni di `eventi.py`, non copie.
        self.assertEqual(inviato["tools"], [eventi.STRUMENTO_SALVA_EVENTI])
        self.assertEqual(inviato["system"], eventi.ISTRUZIONI_CLASSIFICATORE)
        # Modello DIVERSO dal classificatore: una conferma chiesta a chi ha
        # gia' risposto non e' una prova.
        self.assertEqual(inviato["model"], monitoraggio.MODELLO_SECONDA_OPINIONE)
        self.assertNotEqual(
            monitoraggio.MODELLO_SECONDA_OPINIONE, monitoraggio.MODELLO_CLASSIFICATORE)
        uso = contatori.modelli[monitoraggio.MODELLO_SECONDA_OPINIONE]
        self.assertEqual(uso.chiamate, 1)
        self.assertEqual(uso.token_ingresso, 1000)
        self.assertGreater(contatori.usd, 0)
        self.assertEqual(contatori.fuori_listino, ())

    async def test_il_modello_e_a_listino(self):
        # Un modello fuori listino costerebbe 0 e il tetto in $ non lo vedrebbe.
        impostazioni_vere = carica_modulo("settings")
        self.assertIn(monitoraggio.MODELLO_SECONDA_OPINIONE,
                      impostazioni_vere._LISTINO_DEFAULT)

    async def test_un_errore_vale_none_e_non_si_ritenta(self):
        bilancio = carica_modulo("bilancio")
        cliente = _ClienteFinto(errore=RuntimeError("rete giu'"))
        _con_cliente(self, cliente)
        contatori = bilancio.Contatori()
        seconda = monitoraggio.seconda_opinione_da_impostazioni(
            self._impostazioni_con_chiave(), contatori)

        self.assertIsNone(await seconda(eventi.Contesto(bando_id=1, oggi=OGGI)))
        # Un solo tentativo: il G7 ha l'altra strada, e un retry per bando
        # moltiplicherebbe il conto proprio quando la rete va male.
        self.assertEqual(len(cliente.chiamate), 1)
        self.assertEqual(contatori.modelli, {})

    async def test_nessun_evento_vale_none(self):
        cliente = _ClienteFinto(risposte=[_Risposta_LLM([])])
        _con_cliente(self, cliente)
        seconda = monitoraggio.seconda_opinione_da_impostazioni(
            self._impostazioni_con_chiave(), carica_modulo("bilancio").Contatori())
        self.assertIsNone(await seconda(eventi.Contesto(bando_id=1, oggi=OGGI)))

    async def test_restituisce_tutti_gli_eventi(self):
        # Un differimento reale ne produce DUE (apertura e scadenza): tenere
        # solo il primo bocciarebbe al G7 la seconda rettifica della pagina.
        cliente = _ClienteFinto(risposte=[_Risposta_LLM([
            _voce("data_apertura", "2026-10-22"), _voce("data_scadenza", "2026-12-01")])])
        _con_cliente(self, cliente)
        seconda = monitoraggio.seconda_opinione_da_impostazioni(
            self._impostazioni_con_chiave(), carica_modulo("bilancio").Contatori())
        letti = await seconda(eventi.Contesto(bando_id=1, oggi=OGGI))
        self.assertEqual([e.campo for e in letti], ["data_apertura", "data_scadenza"])

    async def test_non_vede_la_proposta_del_primo_modello(self):
        # E' il punto del gate: se la seconda opinione leggesse l'evento
        # proposto, la domanda diventerebbe «confermi?» e la risposta sarebbe
        # quasi sempre si'. Deve ricevere lo stesso contesto, senza proposta.
        cliente = _ClienteFinto()
        _con_cliente(self, cliente)
        seconda = monitoraggio.seconda_opinione_da_impostazioni(
            self._impostazioni_con_chiave(), carica_modulo("bilancio").Contatori())
        ctx = eventi.Contesto(
            bando_id=1, oggi=OGGI,
            pagine=(eventi.Pagina(url="https://ente.it/x", testo="testo"),))
        await seconda(ctx)
        messaggio = cliente.chiamate[0]["messages"][0]["content"]
        self.assertEqual(messaggio, eventi.prompt_utente(ctx))
        self.assertNotIn("2026-12-01", messaggio)
        self.assertNotIn("rettifica", messaggio)

    async def test_dentro_controlla_il_contesto_arriva_senza_proposta(self):
        # La prova end-to-end della stessa regola: `controlla` chiama il
        # secondo modello PRIMA di mettergli la proposta nel contesto.
        visti = []

        async def classifica(ctx):
            return [eventi.Evento(tipo="proroga", valore="2026-12-01",
                                  citazione="prorogato", url_prova="https://ente.it/x")]

        async def seconda(ctx):
            visti.append(ctx)
            return None

        async def scarica(url, **kw):
            return _Risposta(html="<h1>Avviso</h1><p>prorogato al 1 dicembre 2026</p>")

        await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=classifica, seconda_opinione=seconda,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(len(visti), 1)
        self.assertIsNone(visti[0].seconda_opinione)


class TestG7NelRiepilogo(unittest.IsolatedAsyncioTestCase):
    """I due costruttori veri dentro un giro vero: `g7_disponibile` (LAVORO 3)."""

    def setUp(self):
        _zittisci_io(self)

    async def _giro(self, chiave):
        bilancio = carica_modulo("bilancio")
        _con_cliente(self, _ClienteFinto())
        impostazioni = _impostazioni(
            anthropic_api_key=chiave,
            listino_modelli={monitoraggio.MODELLO_SECONDA_OPINIONE: (3.0, 15.0)})
        contatori = bilancio.Contatori()
        return await monitoraggio.run(
            impostazioni=impostazioni,
            fonte_dati=monitoraggio.FonteDati(righe=[_bando(id=1)]),
            scarica=_nessuno_scarico, classifica=_nessun_evento,
            contatori=contatori,
            seconda_opinione=monitoraggio.seconda_opinione_da_impostazioni(
                impostazioni, contatori),
            pagine_collegate=monitoraggio.pagine_collegate_da_impostazioni(
                impostazioni, scarica=_nessuno_scarico, news_per_host={}),
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5,
        )

    async def test_con_la_chiave_il_riepilogo_dice_che_il_g7_c_e(self):
        esito = await self._giro("chiave-finta")
        self.assertTrue(esito["g7_disponibile"])

    async def test_senza_chiave_la_seconda_opinione_non_nasce(self):
        bilancio = carica_modulo("bilancio")
        self.assertIsNone(monitoraggio.seconda_opinione_da_impostazioni(
            _impostazioni(anthropic_api_key=""), bilancio.Contatori()))


async def _nessuno_scarico(url, **kw):
    return _Risposta(html="<h1>x</h1><p>testo</p>")


# --- pagine collegate di produzione (§6.2) ----------------------------------

class _RispostaWeb:
    def __init__(self, html="", stato=200):
        self.stato = stato
        self.html = html
        self.testo = html
        self.markdown = ""
        self.etag = None
        self.last_modified = None

    @property
    def ok(self):
        return self.stato is not None and 200 <= self.stato < 300

    @property
    def vuota(self):
        return not (self.html or self.testo)


class _Scaricatore:
    """Scarico di prova: registra ogni GET e non tocca la rete."""

    def __init__(self, risposte=None, errore_su=()):
        self.risposte = dict(risposte or {})
        self.errore_su = set(errore_su)
        self.chiamate = []

    async def __call__(self, url, **kw):
        self.chiamate.append((url, kw))
        if url in self.errore_su:
            raise RuntimeError("host muto")
        return self.risposte.get(url) or _RispostaWeb(stato=404)


WP = "https://ente.it/wp-json/wp/v2/posts"
NEWS = "https://ente.it/notizie/"


def _bando_collegate(**extra):
    base = {
        "id": 7,
        "titolo": "Avviso psicologia scolastica nelle scuole del Lazio",
        "fonte_ufficiale_url": "https://www.ente.it/bandi/psicologia-scolastica/",
        "ultimo_controllo_at": "2026-09-16T10:00:00+00:00",
    }
    base.update(extra)
    return base


class TestPagineCollegate(unittest.IsolatedAsyncioTestCase):
    """WordPress, `news_url` del registro e SEDIA: tre strade, tutte GET."""

    def _adattatore(self, scaricatore, news=None):
        return monitoraggio.pagine_collegate_da_impostazioni(
            _impostazioni(), scarica=scaricatore, news_per_host=news or {})

    async def test_wordpress_cerca_tre_token_e_dopo_l_ultimo_controllo(self):
        corpo = json.dumps([
            {"link": "https://ente.it/notizie/21558",
             "title": {"rendered": "Psicologia scolastica: differimento dei termini"}},
        ])
        scarica = _Scaricatore()
        scarica.risposte = {}
        # L'URL si compone qui dentro: lo si accetta qualunque sia, poi lo si
        # legge dalle chiamate registrate.
        async def prendi(url, **kw):
            scarica.chiamate.append((url, kw))
            return _RispostaWeb(html=corpo)

        collegate = self._adattatore(prendi, {"ente.it": WP})
        trovate = await collegate(_bando_collegate())

        self.assertEqual(trovate, ("https://ente.it/notizie/21558",))
        chiesto = scarica.chiamate[0][0]
        self.assertTrue(chiesto.startswith(WP + "?"))
        # «avviso» e «nelle» non restringono niente: con loro dentro due dei
        # tre token della ricerca sarebbero sprecati.
        self.assertIn("search=psicologia+scolastica+scuole", chiesto)
        self.assertIn("after=2026-09-16T12%3A00%3A00", chiesto)

    async def test_wordpress_senza_ultimo_controllo_usa_la_finestra(self):
        # Il primo controllo di un bando e' il caso in cui il G7 gira in
        # variante G2' e pretende ANCHE la prova indipendente: e' l'ultimo
        # momento in cui ha senso pescare fra i post di sempre. Senza
        # `ultimo_controllo_at` si ripiega su `oggi - GIORNI_RICERCA_WP`.
        async def prendi(url, **kw):
            prendi.url = url
            return _RispostaWeb(html="[]")

        collegate = monitoraggio.pagine_collegate_da_impostazioni(
            _impostazioni(), scarica=prendi, news_per_host={"ente.it": WP},
            adesso=ADESSO)
        await collegate(_bando_collegate(ultimo_controllo_at=None))
        atteso = (monitoraggio.adesso_roma(ADESSO)
                  - timedelta(days=monitoraggio.GIORNI_RICERCA_WP))
        self.assertIn(
            "after=" + quote(atteso.replace(tzinfo=None).isoformat(timespec="seconds")),
            prendi.url)

    async def test_wordpress_scarta_il_post_scorrelato(self):
        # `?search=` e' un OR ordinato per pertinenza, non un AND: senza
        # soglia il primo post qualunque cosa dica diventerebbe una prova del
        # G7, e su un portale regionale molti bandi condividono la scadenza.
        corpo = json.dumps([
            {"link": "https://ente.it/n/1",
             "title": {"rendered": "Sagra della porchetta: il programma"}},
            {"link": "https://ente.it/n/2",
             "title": {"rendered": "Psicologia scolastica: differimento dei termini"}},
        ])

        async def prendi(url, **kw):
            return _RispostaWeb(html=corpo)

        collegate = self._adattatore(prendi, {"ente.it": WP})
        self.assertEqual(await collegate(_bando_collegate()),
                         ("https://ente.it/n/2",))

    async def test_wordpress_tiene_la_notizia_lunga_del_caso_guida(self):
        # Il rovescio del test precedente, ed e' il motivo per cui il filtro
        # del ramo WP non e' un Jaccard: la notizia giusta e' quasi sempre piu'
        # lunga della scheda, e sul Jaccard dei titoli interi questa coppia
        # vale 0,18 — meno di quanto serva a scartare la sagra di paese.
        lungo = ("Psicologia scolastica nelle scuole del Lazio: differimento "
                 "dei termini di presentazione delle domande")
        corpo = json.dumps([{"link": "https://ente.it/n/21558",
                             "title": {"rendered": lungo}}])
        bando = _bando_collegate(titolo="Avviso pubblico Psicologia scolastica")

        async def prendi(url, **kw):
            return _RispostaWeb(html=corpo)

        collegate = self._adattatore(prendi, {"ente.it": WP})
        self.assertEqual(await collegate(bando), ("https://ente.it/n/21558",))
        # La misura che lo tiene dentro e quella che lo butterebbe fuori.
        self.assertLess(
            monitoraggio._somiglianza_titoli(bando["titolo"], lungo),
            monitoraggio.SOGLIA_TITOLI_COLLEGATE)
        self.assertGreaterEqual(
            monitoraggio._copertura_ricerca(
                monitoraggio._token_ricerca(bando["titolo"]), lungo),
            monitoraggio.COPERTURA_RICERCA_WP)

    async def test_wordpress_senza_titolo_non_interroga(self):
        # `?search=` vuoto restituirebbe gli ultimi post del sito: un fetch per
        # bando che non riguarda quel bando.
        scarica = _Scaricatore()
        collegate = self._adattatore(scarica, {"ente.it": WP})
        self.assertEqual(await collegate(_bando_collegate(titolo="")), ())
        self.assertEqual(scarica.chiamate, [])

    async def test_news_url_generico_filtra_con_jaccard(self):
        html = (
            '<a href="/notizie/psicologia">Avviso psicologia scolastica nelle '
            'scuole del Lazio</a>'
            '<a href="/notizie/agricoltura">Bando agricoltura biologica 2026</a>'
        )
        scarica = _Scaricatore({NEWS: _RispostaWeb(html=html)})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        trovate = await collegate(_bando_collegate())
        self.assertEqual(trovate, ("https://ente.it/notizie/psicologia",))
        # Una sola GET per host per giro: l'URL e' quello del registro.
        self.assertEqual([u for u, _ in scarica.chiamate], [NEWS])

    async def test_mai_piu_di_due_pagine(self):
        corpo = json.dumps([
            {"link": f"https://ente.it/n/{i}",
             "title": {"rendered": "Psicologia scolastica: differimento dei termini"}}
            for i in range(5)
        ])

        async def prendi(url, **kw):
            return _RispostaWeb(html=corpo)

        collegate = self._adattatore(prendi, {"ente.it": WP})
        trovate = await collegate(_bando_collegate())
        self.assertEqual(len(trovate), monitoraggio.MAX_PAGINE_COLLEGATE)

    async def test_solo_httpx_mai_il_ripiego_firecrawl(self):
        # `principale=False` e' cio' che vieta il credito: il ripiego e'
        # ammesso solo sulla pagina principale del bando (§6.2).
        scarica = _Scaricatore({NEWS: _RispostaWeb(html="<a href='/x'>x</a>")})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        await collegate(_bando_collegate())
        self.assertTrue(scarica.chiamate)
        for _, kw in scarica.chiamate:
            self.assertIs(kw["principale"], False)

    async def test_host_che_fallisce_viene_ignorato(self):
        scarica = _Scaricatore(errore_su={NEWS})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        self.assertEqual(await collegate(_bando_collegate()), ())

    async def test_host_muto_costa_una_sola_get_per_giro(self):
        # La cache dello scarico memorizza solo le risposte buone: senza
        # memoria qui dentro, un host in avaria si ripagherebbe una GET (piu'
        # i suoi ritentativi) per OGNI bando, a ogni giro, e il tetto `fetch`
        # arriverebbe prima del previsto controllando meno bandi.
        scarica = _Scaricatore(errore_su={NEWS})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        for identificativo in range(5):
            self.assertEqual(await collegate(_bando_collegate(id=identificativo)), ())
        self.assertEqual(len(scarica.chiamate), 1)

    async def test_host_in_5xx_costa_una_sola_get_per_giro(self):
        scarica = _Scaricatore({NEWS: _RispostaWeb(stato=503)})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        for identificativo in range(3):
            await collegate(_bando_collegate(id=identificativo))
        self.assertEqual(len(scarica.chiamate), 1)

    async def test_la_pagina_di_notizie_si_legge_una_volta_per_giro(self):
        html = ('<a href="/notizie/psicologia">Avviso psicologia scolastica '
                'nelle scuole del Lazio</a>')
        scarica = _Scaricatore({NEWS: _RispostaWeb(html=html)})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        for identificativo in range(4):
            self.assertEqual(await collegate(_bando_collegate(id=identificativo)),
                             ("https://ente.it/notizie/psicologia",))
        self.assertEqual(len(scarica.chiamate), 1)

    async def test_la_scheda_del_bando_non_e_una_pagina_collegata(self):
        # L'invariante di `_prove_da_pagine`: la scheda non puo' essere la
        # conferma di se stessa. Una voce `news_url` generica che la elenca
        # con `www.` in meno passerebbe il confronto fra stringhe grezze, e il
        # G7 — il gate per cui tutto questo esiste — si soddisferebbe con la
        # pagina che ha generato l'evento.
        varianti = (
            "https://ente.it/bandi/psicologia-scolastica/",     # senza www.
            "https://www.ente.it/bandi/psicologia-scolastica",  # senza slash
            "http://www.ente.it/bandi/psicologia-scolastica/",  # http
        )
        for variante in varianti:
            with self.subTest(variante=variante):
                html = (f'<a href="{variante}">Avviso psicologia scolastica '
                        'nelle scuole del Lazio</a>')
                scarica = _Scaricatore({NEWS: _RispostaWeb(html=html)})
                collegate = self._adattatore(scarica, {"ente.it": NEWS})
                self.assertEqual(await collegate(_bando_collegate()), ())

    async def test_controlla_scarta_la_scheda_fra_le_collegate(self):
        # La stessa guardia accanto a chi dichiara l'invariante: `controlla`
        # riceve gli URL da un adattatore qualunque, non solo dal nostro.
        scaricati = []

        async def scarica(url, **kw):
            scaricati.append(url)
            return _Risposta(html="<h1>Avviso</h1><p>scadenza 1 dicembre 2026</p>")

        async def collegate(riga):
            # La scheda con lo slash finale in piu': e' la stessa pagina.
            return [str(riga["fonte_ufficiale_url"]).rstrip("/") + "/"]

        visti = []

        async def classifica(ctx):
            visti.append(ctx)
            return []

        riga = _bando()
        riga["fonte_ufficiale_url"] = "https://www.ente.it/bandi/x"
        await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classifica, pagine_collegate=collegate,
            fonte_dati=monitoraggio.FonteDati(), adesso=ADESSO, casuale=lambda: 0.5)
        # Una sola GET (la scheda) e nessuna pagina `collegata`: quindi
        # nessuna prova indipendente estratta da se stessa.
        self.assertEqual(scaricati, ["https://www.ente.it/bandi/x"])
        self.assertEqual([p.collegata for p in visti[0].pagine], [False])
        self.assertEqual(monitoraggio._prove_da_pagine(visti[0].pagine), [])

    async def test_titolo_di_sole_parole_vuote_non_interroga(self):
        # Con un titolo tutto di parole vuote la ricerca non restringe
        # niente: meglio nessuna query — e nessuna GET — di un fetch per bando
        # che torna mezzo sito.
        scarica = _Scaricatore()
        collegate = self._adattatore(scarica, {"ente.it": WP})
        self.assertEqual(
            await collegate(_bando_collegate(titolo="Avviso del bando")), ())
        self.assertEqual(scarica.chiamate, [])

    async def test_risposta_non_2xx_non_produce_pagine(self):
        scarica = _Scaricatore({NEWS: _RispostaWeb(stato=503)})
        collegate = self._adattatore(scarica, {"ente.it": NEWS})
        self.assertEqual(await collegate(_bando_collegate()), ())

    async def test_json_storto_non_solleva(self):
        async def prendi(url, **kw):
            return _RispostaWeb(html="non e' json")

        collegate = self._adattatore(prendi, {"ente.it": WP})
        self.assertEqual(await collegate(_bando_collegate()), ())

    async def test_host_senza_news_url_non_fa_nessuna_get(self):
        scarica = _Scaricatore()
        collegate = self._adattatore(scarica, {"altro.it": NEWS})
        self.assertEqual(await collegate(_bando_collegate()), ())
        self.assertEqual(scarica.chiamate, [])

    async def test_sedia_per_i_bandi_europei(self):
        # L'identifier si legge dal titolo, non si inventa: `url_topic` e'
        # deterministico e in minuscolo (con l'ID maiuscolo il portale da' 404).
        scarica = _Scaricatore()
        collegate = self._adattatore(scarica, {})
        trovate = await collegate(_bando_collegate(
            titolo="HORIZON-CL2-2026-01-DEMOCRACY-01 Bando europeo",
            fonte_ufficiale_url="https://ec.europa.eu/info/funding-tenders/x"))
        self.assertEqual(trovate, (
            "https://ec.europa.eu/info/funding-tenders/opportunities/data/"
            "topicDetails/horizon-cl2-2026-01-democracy-01.json",))
        # Nessuna GET: l'indirizzo e' deterministico, lo scarico lo fa
        # `controlla` insieme alle altre pagine collegate.
        self.assertEqual(scarica.chiamate, [])

    async def test_bando_italiano_non_produce_url_sedia(self):
        collegate = self._adattatore(_Scaricatore(), {})
        self.assertEqual(await collegate(_bando_collegate()), ())

    async def test_le_pagine_arrivano_al_contesto_come_collegate(self):
        # Prova d'innesto: l'adattatore ritorna URL, `controlla` li scarica e
        # li marca `collegata=True` — che e' cio' che li rende prove del G7.
        async def scarica(url, **kw):
            if url.endswith("/psicologia"):
                return _Risposta(html="<p>nuova scadenza 1 dicembre 2026</p>")
            return _Risposta(html="<h1>Avviso</h1><p>testo</p>")

        async def collegate(riga):
            return ["https://ente.it/notizie/psicologia"]

        visti = []

        async def classifica(ctx):
            visti.append(ctx)
            return []

        await monitoraggio.controlla(
            _bando(), scarica=scarica, classifica=classifica,
            pagine_collegate=collegate, fonte_dati=monitoraggio.FonteDati(),
            adesso=ADESSO, casuale=lambda: 0.5)
        pagine = visti[0].pagine
        self.assertEqual([p.collegata for p in pagine], [False, True])

if __name__ == "__main__":       # pragma: no cover
    unittest.main()


class TestLottoDelMonitor(unittest.TestCase):
    """`--lotto` sposta il monitor sui tetti del backfill.

    Il tetto di trenta classificazioni al giorno e' giusto **a regime**, dove il
    modello si chiama solo sulle pagine che sono cambiate davvero. Alla
    **semina** no: al primo controllo un bando non ha un «prima» con cui
    confrontarsi, quindi passa dal modello sempre.

    Misurato il 24/09/2026 sul primo giro vero: `candidati: 50, controllati:
    30`, fermato dal tetto dopo tre minuti, con 213 bandi da seminare. Sette
    giorni per finire una cosa che il piano voleva in un lotto solo (L6, sui
    tetti di backfill). Il comando non aveva il modo di dirlo.
    """

    def setUp(self):
        self.bilancio = carica_modulo("bilancio")

    def test_senza_lotto_lo_step_resta_quello_del_regime(self):
        self.assertEqual(monitoraggio.STEP, "monitor")
        self.assertFalse(self.bilancio.e_backfill(monitoraggio.STEP))

    def test_col_lotto_lo_step_diventa_un_backfill(self):
        # E' il prefisso che `bilancio.verifica` guarda per cambiare tetti.
        self.assertTrue(self.bilancio.e_backfill("backfill:L6"))

    def test_i_due_insiemi_di_tetti_sono_diversi(self):
        # Se coincidessero, il flag non servirebbe a niente.
        tetti = self.bilancio.Tetti(classificazioni_giorno=30,
                                    backfill_crediti=8000, backfill_usd=60.0)
        # `usd` e' una proprieta' calcolata dai modelli: il tetto che morde qui
        # e' quello delle classificazioni, che e' esattamente il numero che ha
        # fermato il giro vero al trentesimo bando.
        molte = self.bilancio.Contatori(classificazioni=30)
        regime = self.bilancio.verifica(molte, tetti, step="monitor", gia_oggi={})
        lotto = self.bilancio.verifica(molte, tetti, step="backfill:L6", gia_oggi={})
        self.assertFalse(regime.consentito, "a regime il tetto deve mordere")
        self.assertTrue(lotto.consentito, "nel lotto no: ha i suoi tetti")


class TestRespintiADatabase(unittest.IsolatedAsyncioTestCase):
    """Un respinto che muore con il processo e' un giro pagato per niente.

    Misurato in produzione il 24/09/2026 sulla semina del monitor: 390
    classificazioni per 5,17 dollari, 691 proposte, **zero** eventi a DB.
    `report-ombra` legge `bando_evento`, quindi non trovava niente da misurare
    e la precisione richiesta da §6.2 (95% su almeno 100 eventi) non era
    calcolabile. I respinti vanno registrati: portano il campo `gate`, che dice
    quale gate ha respinto, ed e' la sola informazione che serve.
    """

    async def _giro(self, quante_proposte):
        eventi = carica_modulo("eventi")
        dominio_ufficiale = carica_modulo("dominio_ufficiale")

        html = ("<h1>Avviso</h1><p>Sono online le FAQ dell'avviso.</p>"
                "<p><a href='https://www.lazioeuropa.it/faq.pdf'>FAQ</a></p>")

        async def scarica(url, **_k):
            return _Risposta(html=html)

        async def classifica(_ctx):
            return [eventi.Evento(
                tipo="faq", citazione="Sono online le FAQ dell'avviso",
                url_prova="https://www.lazioeuropa.it/bandi/avviso-1/")
                for _ in range(quante_proposte)]

        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}])
        fonte = monitoraggio.FonteDati()
        riga = _bando(testo_norm="Avviso\n\nNessuna novita'.",
                      impronta_contenuto="diversa-da-quella-nuova")
        esito = await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classifica, fonte_dati=fonte,
            modalita="ombra", tabella_domini=tabella, adesso=ADESSO,
            casuale=lambda: 0.5)
        return esito, fonte.registrati

    async def test_il_respinto_arriva_a_db_con_il_suo_gate(self):
        esito, registrati = await self._giro(2)
        self.assertGreaterEqual(len(esito.respinti), 1)
        respinti_a_db = [r for r in registrati if not r.get("verificato")]
        self.assertTrue(respinti_a_db, "nessun respinto registrato: l'ombra non misura niente")
        riga = respinti_a_db[0]
        self.assertFalse(riga["leggibile"], "un respinto non deve essere leggibile")
        self.assertFalse(riga["applicato"])
        self.assertTrue(riga.get("gate"), "senza `gate` non si sa quale gate ha respinto")

    async def test_il_respinto_non_e_applicabile(self):
        # La cintura: anche se un domani `applica-eventi` leggesse queste righe,
        # `applicabile()` le esclude perche' `verificato` e' falso.
        _esito, registrati = await self._giro(2)
        for riga in (r for r in registrati if not r.get("verificato")):
            self.assertFalse(monitoraggio.applicabile(riga))

    async def test_il_tetto_per_bando_vale(self):
        # Un modello che proponesse cinquanta eventi su una pagina non deve
        # poter scrivere cinquanta righe.
        _esito, registrati = await self._giro(monitoraggio.RESPINTI_A_DB_PER_BANDO + 6)
        respinti_a_db = [r for r in registrati if not r.get("verificato")]
        self.assertLessEqual(len(respinti_a_db), monitoraggio.RESPINTI_A_DB_PER_BANDO)


class TestEventiRifiutatiDalDatabase(unittest.IsolatedAsyncioTestCase):
    """Un giro che non riesce a scrivere gli eventi non e' un giro riuscito.

    Il 25/09/2026 ogni INSERT di evento veniva rifiutato da Postgres
    (`confidenza` frazionaria in una colonna `smallint`),
    `db.registra_evento` ne faceva un warning e il riepilogo diceva
    `eventi: 0` come se i gate avessero respinto tutto. Due giorni di ombra
    pagati e buttati, senza un numero che lo dicesse.
    """

    class _FonteRifiuta(monitoraggio.FonteDati):
        """Il DB rifiuta ogni evento, come faceva la colonna smallint."""

        def registra_evento(self, riga):
            return False

    async def _giro(self, fonte):
        eventi_mod = carica_modulo("eventi")
        dominio_ufficiale = carica_modulo("dominio_ufficiale")
        html = ("<h1>Avviso</h1><p>Sono online le FAQ dell'avviso.</p>"
                "<p><a href='https://www.lazioeuropa.it/faq.pdf'>FAQ</a></p>")

        async def scarica(url, **_k):
            return _Risposta(html=html)

        async def classifica(_ctx):
            return [eventi_mod.Evento(
                tipo="faq", citazione="Sono online le FAQ dell'avviso",
                url_prova="https://www.lazioeuropa.it/bandi/avviso-1/")]

        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}])
        riga = _bando(testo_norm="Avviso\n\nNessuna novita'.",
                      impronta_contenuto="diversa-da-quella-nuova")
        return await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classifica, fonte_dati=fonte,
            modalita="ombra", tabella_domini=tabella, adesso=ADESSO,
            casuale=lambda: 0.5)

    async def test_il_rifiuto_si_conta(self):
        esito = await self._giro(self._FonteRifiuta())
        self.assertGreaterEqual(esito.eventi_non_scritti, 1,
                                "un INSERT rifiutato deve comparire in un contatore")

    async def test_senza_rifiuti_il_contatore_resta_a_zero(self):
        esito = await self._giro(monitoraggio.FonteDati())
        self.assertEqual(esito.eventi_non_scritti, 0)


class TestForzaLaCoda(unittest.TestCase):
    """`--forza` ignora la cadenza, non le altre tre condizioni.

    Il 25/09/2026, finita la semina, la coda era vuota fino al pomeriggio (0
    candidati alle 09:15, 56 alle 18:00): non c'era modo di verificare una
    correzione appena fatta senza aspettare ore. Il resolver ha `--forza` da
    sempre, il monitor no.
    """

    def _riga(self, **extra):
        base = {"id": 1, "pubblicato": True, "bando_master_id": None,
                "fonte_ufficiale_stato": "trovata",
                "prossimo_controllo_at": "2026-12-31T00:00:00+00:00"}
        base.update(extra)
        return base

    def test_la_cadenza_futura_non_ferma_il_forza(self):
        riga = self._riga()
        self.assertFalse(monitoraggio.selezionabile(riga))
        self.assertTrue(monitoraggio.selezionabile(riga, forza=True))
        self.assertEqual(len(monitoraggio.seleziona([riga], forza=True)), 1)
        self.assertEqual(len(monitoraggio.seleziona([riga])), 0)

    def test_le_altre_tre_condizioni_restano(self):
        # Non pubblicato, doppione fuso, fonte non trovata: su queste righe non
        # c'e' niente di lecito da scaricare, nemmeno a mano. La terza e' la piu'
        # importante: l'unico URL che avremmo sarebbe quello dell'aggregatore.
        for campo, valore in (("pubblicato", False),
                              ("bando_master_id", 99),
                              ("fonte_ufficiale_stato", "in_verifica")):
            with self.subTest(campo=campo):
                riga = self._riga(**{campo: valore})
                self.assertFalse(monitoraggio.selezionabile(riga, forza=True),
                                 f"--forza non deve superare il filtro su {campo}")

    def test_una_riga_gia_da_controllare_non_cambia(self):
        riga = self._riga(prossimo_controllo_at="2020-01-01T00:00:00+00:00")
        self.assertTrue(monitoraggio.selezionabile(riga))
        self.assertTrue(monitoraggio.selezionabile(riga, forza=True))


class TestDuplicatoNonERifiuto(unittest.IsolatedAsyncioTestCase):
    """Un evento che c'era gia' non e' un fallimento del giro.

    Misurato il 25/09/2026: `eventi_non_scritti: 2` con l'allarme «il database
    li ha rifiutati», su due eventi che erano semplicemente **duplicati** —
    l'indice di dedup della migrazione 02 aveva fatto il suo lavoro. E' il caso
    normale quando si rifa' un giro sulle stesse righe con `--forza`, e
    confonderlo con un guasto fa gridare un allarme su un lavoro riuscito.
    """

    class _Duplica(monitoraggio.FonteDati):
        def registra_evento_esito(self, riga):
            from scraper_app import db
            return db.EVENTO_GIA_PRESENTE

    class _Rifiuta(monitoraggio.FonteDati):
        def registra_evento_esito(self, riga):
            from scraper_app import db
            return db.EVENTO_RIFIUTATO

    async def _giro(self, fonte):
        eventi_mod = carica_modulo("eventi")
        dominio_ufficiale = carica_modulo("dominio_ufficiale")
        html = ("<h1>Avviso</h1><p>Sono online le FAQ dell'avviso.</p>"
                "<p><a href='https://www.lazioeuropa.it/faq.pdf'>FAQ</a></p>")

        async def scarica(url, **_k):
            return _Risposta(html=html)

        async def classifica(_ctx):
            return [eventi_mod.Evento(
                tipo="faq", citazione="Sono online le FAQ dell'avviso",
                url_prova="https://www.lazioeuropa.it/bandi/avviso-1/")]

        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 1, "link": "https://www.lazioeuropa.it/bandi/"}])
        riga = _bando(testo_norm="Avviso\n\nNessuna novita'.",
                      impronta_contenuto="diversa-da-quella-nuova")
        return await monitoraggio.controlla(
            riga, scarica=scarica, classifica=classifica, fonte_dati=fonte,
            modalita="ombra", tabella_domini=tabella, adesso=ADESSO,
            casuale=lambda: 0.5)

    async def test_il_duplicato_non_si_conta(self):
        esito = await self._giro(self._Duplica())
        self.assertEqual(esito.eventi_non_scritti, 0,
                         "un evento gia' presente non e' un rifiuto")

    async def test_il_rifiuto_vero_si_conta(self):
        esito = await self._giro(self._Rifiuta())
        self.assertGreaterEqual(esito.eventi_non_scritti, 1)


class TestPopolazioneDelReport(unittest.IsolatedAsyncioTestCase):
    """Il report misura le proposte del classificatore, non il registro.

    Due difetti misurati il 25/09/2026, uno sopra l'altro, su un giro che aveva
    appena ammesso 6 eventi su 17:

    * il filtro escludeva i soli `TIPI_INTERNI`, quindi nel campione entravano
      le 2 143 righe `pubblicazione` del backfill della 02, i
      `fonte_ufficiale_*` e le transizioni del cron — tutti `verificato=false`
      per costruzione: la precisione usciva **0**;
    * i tipi si filtravano **dopo** la lettura, quindi `--campione 100` leggeva
      100 righe e le prime erano 336 `segnale_fonte`: il report diceva
      `eventi: 0`. E' lo stesso difetto del `--limit` che conta le righe lette
      invece di quelle utili, gia' corretto in `link-verifica` e nel resolver.
    """

    async def test_solo_i_tipi_proponibili_entrano_nel_campione(self):
        eventi_mod = carica_modulo("eventi")
        righe = [
            {"id": 1, "tipo": "pubblicazione", "verificato": False},
            {"id": 2, "tipo": "segnale_fonte", "verificato": False},
            {"id": 3, "tipo": "chiusura_automatica", "verificato": False},
            {"id": 4, "tipo": "fonte_ufficiale_verificata", "verificato": False},
            {"id": 5, "tipo": "faq", "verificato": True, "gate": {"falliti": []}},
            {"id": 6, "tipo": "apertura", "verificato": False,
             "gate": {"falliti": [{"gate": "G7", "motivo": "nessuna seconda prova"}]}},
        ]
        esito = await monitoraggio.run_report_ombra(
            righe=righe, uscita=io.StringIO(), campione=100, dal=date(2026, 9, 25))
        self.assertEqual(esito["eventi"], 2, "solo `faq` e `apertura` sono proposte")
        self.assertEqual(esito["ammessi"], 1)
        self.assertEqual(esito["respinti"], 1)
        for riga in righe[:4]:
            self.assertIn(riga["tipo"],
                          set(righe[i]["tipo"] for i in range(4)))
        self.assertNotIn(righe[0]["tipo"], eventi_mod.TIPI_PROPONIBILI)

    async def test_la_lettura_chiede_i_tipi_al_database(self):
        # Se i tipi non vanno nella query, il `--limit` li taglia prima che il
        # filtro li veda.
        eventi_mod = carica_modulo("eventi")
        visti = {}

        def select_eventi(**kwargs):
            visti.update(kwargs)
            return []

        with patch.object(carica_modulo("db"), "select_eventi", select_eventi):
            await monitoraggio.run_report_ombra(
                uscita=io.StringIO(), campione=50, dal=date(2026, 9, 25))
        self.assertEqual(tuple(visti["tipi"]), tuple(eventi_mod.TIPI_PROPONIBILI))

    async def test_un_tipo_chiesto_a_mano_resta_quello(self):
        visti = {}

        def select_eventi(**kwargs):
            visti.update(kwargs)
            return []

        with patch.object(carica_modulo("db"), "select_eventi", select_eventi):
            await monitoraggio.run_report_ombra(
                uscita=io.StringIO(), campione=50, tipo="proroga", dal=date(2026, 9, 25))
        self.assertEqual(tuple(visti["tipi"]), ("proroga",))


class TestApplicareVuolDireRendereVisibile(unittest.IsolatedAsyncioTestCase):
    """Attivare un tipo significa renderlo **visibile**, non solo applicarlo.

    Misurato in produzione il 25/09/2026: `applica-eventi --tipo faq --attivo`
    e `--tipo nuovo_allegato --attivo` hanno riferito `applicati: 1` e
    `applicati: 4`, e le cinque righe erano `leggibile=false, cursore=NULL` —
    cioe' invisibili al pubblico, box «Aggiornamenti» vuoto. La RPC
    `bando_applica_evento` riversa `valore_dopo` nelle colonne di `bando` e
    marca l'evento `applicato`, ma non tocca `leggibile`, e il trigger del
    cursore scatta su `UPDATE OF leggibile`. Servono due scritture.
    """

    def _eventi(self, quanti=3, tipo="faq"):
        return [{"id": 100 + i, "bando_id": 900 + i, "tipo": tipo,
                 "verificato": True, "applicato": False, "leggibile": False,
                 "rilevato_at": "2026-09-25T09:00:00+00:00",
                 "data_evento": "2026-09-25"}
                for i in range(quanti)]

    async def _lancia(self, finto, *, attivo=True, **extra):
        # Due patch e non uno: `monitoraggio` fa `from . import db` dentro le
        # funzioni, e nella suite completa il package ha gia' l'attributo.
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True):
            return await monitoraggio.run_applica_eventi(
                dal=date(2026, 9, 25), attivo=attivo, lock=_lock_libero(),
                impostazioni=_impostazioni(), **extra)

    async def test_ogni_applicato_diventa_leggibile(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        esito = await self._lancia(finto, limit=3, tipi=("faq",))
        self.assertEqual(esito["applicati"], 3)
        self.assertEqual(len(finto.resi_leggibili), 3,
                         "applicato ma invisibile: il box resta vuoto")
        for _id, in_aggiornamenti in finto.resi_leggibili:
            self.assertTrue(in_aggiornamenti, "una faq deve andare nel box")

    async def test_un_evento_non_applicato_non_si_rende_visibile(self):
        # Se la RPC ha detto no, l'evento non deve comparire nel box: sarebbe
        # una notizia data al lettore senza che le colonne la sostengano.
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_RIFIUTATO)
        await self._lancia(finto, limit=3, tipi=("faq",))
        self.assertEqual(finto.resi_leggibili, [])

    async def test_una_rpc_assente_non_rende_visibile_niente(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_NON_TENTATO)
        await self._lancia(finto, limit=3, tipi=("faq",))
        self.assertEqual(finto.resi_leggibili, [])

    async def test_in_ombra_non_si_scrive_niente(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        await self._lancia(finto, attivo=False, limit=3)
        self.assertEqual(finto.resi_leggibili, [])


class TestRiparaGliApplicatiInvisibili(unittest.IsolatedAsyncioTestCase):
    """Un'attivazione interrotta a meta' deve potersi chiudere.

    `bando_applica_evento` marca l'evento `applicato` e non tocca `leggibile`.
    Se il secondo UPDATE non parte, l'evento resta applicato alle colonne e
    assente dal box — e nessun lancio successivo lo ripesca, perche' la
    selezione cerca `applicato=false`. Misurato il 25/09/2026 su cinque eventi
    che il comando aveva dichiarato applicati: `applica-eventi` rispondeva
    `letti: 0` a ogni rilancio, anche con `--riprova-rifiutati`.
    """

    def _eventi(self):
        return [
            {"id": 200, "bando_id": 900, "tipo": "faq", "verificato": True,
             "applicato": True, "leggibile": False,
             "rilevato_at": "2026-09-25T09:00:00+00:00", "data_evento": "2026-09-25"},
            {"id": 201, "bando_id": 901, "tipo": "nuovo_allegato", "verificato": True,
             "applicato": True, "leggibile": False,
             "rilevato_at": "2026-09-25T09:00:00+00:00", "data_evento": "2026-09-25"},
            # Gia' visibile: non si tocca.
            {"id": 202, "bando_id": 902, "tipo": "faq", "verificato": True,
             "applicato": True, "leggibile": True,
             "rilevato_at": "2026-09-25T09:00:00+00:00", "data_evento": "2026-09-25"},
            # Evento di sistema: applicato e invisibile per costruzione.
            {"id": 203, "bando_id": 903, "tipo": "pubblicazione", "verificato": True,
             "applicato": True, "leggibile": False,
             "rilevato_at": "2026-09-25T09:00:00+00:00", "data_evento": "2026-09-25"},
        ]

    async def _lancia(self, finto, *, attivo=True, **extra):
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True):
            return await monitoraggio.run_applica_eventi(
                dal=date(2026, 9, 25), attivo=attivo, lock=_lock_libero(),
                impostazioni=_impostazioni(), **extra)

    async def test_gli_applicati_invisibili_diventano_visibili(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        esito = await self._lancia(finto, limit=50)
        self.assertEqual(esito["resi_visibili"], 2)
        ids = sorted(i for i, _ in finto.resi_leggibili)
        self.assertEqual(ids, [200, 201])

    async def test_non_tocca_i_gia_visibili_ne_quelli_di_sistema(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        await self._lancia(finto, limit=50)
        toccati = [i for i, _ in finto.resi_leggibili]
        self.assertNotIn(202, toccati, "era gia' visibile")
        self.assertNotIn(203, toccati, "`pubblicazione` non va nel box")

    async def test_in_ombra_non_ripara_niente(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        esito = await self._lancia(finto, attivo=False, limit=50)
        self.assertEqual(esito["resi_visibili"], 0)
        self.assertEqual(finto.resi_leggibili, [])

    async def test_il_dry_run_non_ripara_niente(self):
        finto = _DbEventi(self._eventi(), esito_rpc=_DbEventi.ESITO_APPLICATO)
        esito = await self._lancia(finto, dry_run=True, limit=50)
        self.assertEqual(esito["resi_visibili"], 0)
        self.assertEqual(finto.resi_leggibili, [])
