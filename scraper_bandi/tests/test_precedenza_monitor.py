# -*- coding: utf-8 -*-
"""Giro 3, §22: prima il monitor, poi le riscritture delle schede.

Il 02/10, nel giro delle 00, le riscritture con Opus hanno preso 4,46 dei 5 $
del tetto giornaliero dentro il ciclo dei controlli, bando per bando: il
monitor ha fatto 10 classificazioni, ne ha rinviate 14, e alle 06, 12 e 18
nessuna. Qui si verifica la correzione:

- fase 1 (controllo e classificazione di tutte le pagine) prima di qualunque
  riscrittura, con un registro comune a classificatore e riscrittore;
- fase 2 nel tempo che resta, in ordine di `dal`, con la riserva per i giri
  che restano oggi e nel mese (`giri_rimasti`, `riscrittura_consentita`,
  `costo_massimo_riscrittura`);
- le code che chiedono solo date messe per la prima volta, o date che la prosa
  dice gia', si chiudono senza modello (§22.3);
- le risposte tagliate dal tetto di token si contano e vanno nel log (§22.4).

Niente rete, niente DB: orologio, «adesso», consumo, classificatore e
riscrittore sono finti. Dove serve la spesa vera delle riscritture si passa
dal riscrittore di produzione con `rigenera.riscrivi_scheda` sostituita da un
finto che conta i dollari e controlla il tetto come quella vera.
"""
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

monitoraggio = carica_modulo("monitoraggio")
eventi = carica_modulo("eventi")
bilancio = carica_modulo("bilancio")
blocco = carica_modulo("blocco")
rigenera = carica_modulo("rigenera")
impronte = carica_modulo("impronte")
stato_bando = carica_modulo("stato_bando")

ROMA = stato_bando.ROMA
GIRI = ("00:00", "06:00", "12:00", "18:00")
VERSIONE = {"__versione__": impronte.VERSIONE_PULIZIA}
#: Il giro delle 00 del 02/10 e' partito alle 01:54 di Roma (23:54 UTC del 01/10).
GIRO_DEL_2_OTTOBRE = datetime(2026, 10, 1, 23, 54, tzinfo=timezone.utc)
#: L'ultimo giro della giornata: dopo restano solo i 0,25 $ del margine.
ULTIMO_GIRO = datetime(2026, 10, 2, 18, 30, tzinfo=ROMA)
#: Costo di una classificazione e di una riscrittura misurati il 02/10.
COSTO_CLASSIFICAZIONE = 0.015
COSTO_RISCRITTURA = 0.144


def _impostazioni(**extra):
    base = dict(
        monitor_modalita="ombra",
        monitor_scenario="bilanciato",
        monitor_giri=GIRI,
        monitor_stati_estesi=False,
        tetto_ricerche_giorno=0,
        tetto_crediti_giorno=0,
        tetto_usd_giorno=0.0,
        tetto_crediti_mese=0,
        tetto_usd_mese=0.0,
        backfill_tetto_crediti=0,
        backfill_tetto_usd=0.0,
        seo_model="claude-opus-4-7",
        seo_max_tokens=4000,
        listino_modelli={"claude-opus-4-7": (5.0, 25.0)},
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _di_produzione(**extra):
    """Il giro attivo con i tetti di produzione (5 $ al giorno, 150 al mese)."""
    return _impostazioni(monitor_modalita="attivo", tetto_usd_giorno=5.0, tetto_usd_mese=150.0,
                         **extra)


def _url(ident):
    return f"https://www.lazioeuropa.it/bandi/avviso-{ident}/"


def _bando(ident, **extra):
    base = {
        "id": ident,
        "slug": f"avviso-{ident}",
        "pubblicato": True,
        "bando_master_id": None,
        "fonte_ufficiale_stato": "trovata",
        "fonte_ufficiale_url": _url(ident),
        "stato_bando": "aperto",
        "data_scadenza": None,
        "prossimo_controllo_at": None,
        "impronta_contenuto": "",
        "impronte_sezioni": dict(VERSIONE),
        "controlli_falliti": 0,
    }
    base.update(extra)
    return base


def _coda(ident, dal="2026-10-01T22:30:00+00:00", novita=None, tentativi=0):
    return {"novita": novita if novita is not None else [
        {"evento_id": 1000 + ident, "tipo": "faq", "citazione": f"faq {ident}"}],
        "tentativi": tentativi, "dal": dal}


def _in_coda(ident, coda=None, **extra):
    """Un bando con una riscrittura in coda e la pagina invariata (304)."""
    coda = coda if coda is not None else _coda(ident)
    return _bando(ident, etag="x", impronta_contenuto="h",
                  impronte_sezioni={"__link__": [], monitoraggio.CHIAVE_RISCRITTURA: coda,
                                    **VERSIONE}, **extra)


class _Risposta:
    def __init__(self, stato=200, html=""):
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
        return not (self.testo.strip() or self.html.strip())


def _scarica(cambiate=()):
    """Le pagine dei bandi in `cambiate` hanno un testo nuovo, le altre 304."""
    cambiate = set(cambiate)

    async def scarica(url, **_kw):
        ident = int(str(url).rstrip("/").rsplit("-", 1)[1])
        if ident in cambiate:
            return _Risposta(html=f"<main><h1>Avviso {ident}</h1><p>Testo nuovo {ident}.</p></main>")
        return _Risposta(stato=304)
    return scarica


class _Fonte(monitoraggio.FonteDati):
    """La fonte dati in memoria, senza la selezione: l'ordine e' quello dato."""

    def candidati(self, *, limite=0, adesso=None, forza=False):
        return [dict(r) for r in self.righe]


def _classificatore(registro, contatori, costo=COSTO_CLASSIFICAZIONE):
    """Haiku finto: scrive nel registro e conta la spesa nei contatori del giro."""
    async def classifica(ctx):
        registro.append(("classifica", ctx.bando_id))
        bilancio.registra_chiamata(contatori, "haiku-finto", {"input_tokens": round(costo * 1e6)},
                                   {"haiku-finto": (1.0, 0.0)})
        return []
    return classifica


class _Opus:
    """`rigenera.riscrivi_scheda` finta: stesso controllo del tetto di quella
    vera (`bilancio.verifica` sullo step `rigenerazione_scheda`), poi conta il
    costo di una chiamata sulla spesa delle riscritture."""

    def __init__(self, registro, costo=COSTO_RISCRITTURA):
        self.registro = registro
        self.costo = costo

    async def __call__(self, bando_id, novita, *, spesa, tetti, gia_oggi=None, **_kw):
        controllo = bilancio.verifica(spesa, tetti, step=rigenera.STEP_RISCRITTURA, gia_oggi=gia_oggi)
        if not controllo.consentito:
            return rigenera.Riscrittura(bando_id=bando_id, esito=rigenera.ESITO_RINVIATA,
                                        motivo=controllo.motivo)
        self.registro.append(("riscrivi", bando_id))
        bilancio.registra_chiamata(spesa, "opus-finto", {"input_tokens": round(self.costo * 1e6)},
                                   {"opus-finto": (1.0, 0.0)})
        return rigenera.Riscrittura(bando_id=bando_id, esito=rigenera.ESITO_SCRITTA,
                                    slug=f"avviso-{bando_id}")


class _ContatoriScarico:
    """I contatori del client unico del giro (`scarico.contatori()`), finti:
    `azzera` e' `_azzera_contatori_scarico`."""

    def __init__(self):
        self.azzera()

    def azzera(self):
        self.fetch = self.fetch_304 = self.crediti_firecrawl = self.errori = 0


class _OpusConRipiego(_Opus):
    """Come `_Opus`, ma la pagina che la riscrittura rilegge
    (`genera_per_bando`) passa dal ripiego Firecrawl, come su un host JS,
    dietro un WAF o con un app-shell: un fetch e un credito sullo scarico."""

    def __init__(self, registro, scarico, costo=COSTO_RISCRITTURA):
        super().__init__(registro, costo)
        self.scarico = scarico

    async def __call__(self, bando_id, novita, **kw):
        esito = await super().__call__(bando_id, novita, **kw)
        if esito.esito == rigenera.ESITO_SCRITTA:
            self.scarico.fetch += 1
            self.scarico.crediti_firecrawl += 1
        return esito


class _Riscrittore:
    """Riscrittore iniettato: registra e risponde con l'esito chiesto per bando."""

    def __init__(self, registro=None, esiti=None, motivi=None):
        self.registro = registro if registro is not None else []
        self.esiti = esiti or {}
        self.motivi = motivi or {}
        self.chiamate = []

    async def __call__(self, bando_id, novita):
        self.chiamate.append((bando_id, [dict(v) for v in novita]))
        self.registro.append(("riscrivi", bando_id))
        return SimpleNamespace(esito=self.esiti.get(bando_id, "scritta"), slug=f"avviso-{bando_id}",
                               motivo=self.motivi.get(bando_id, ""))


class _Orologio:
    """Restituisce i valori dati in ordine, poi sempre l'ultimo."""

    def __init__(self, *valori):
        self.valori = list(valori) or [0.0]

    def __call__(self):
        return self.valori.pop(0) if len(self.valori) > 1 else self.valori[0]


def _lock_libero():
    finto = MagicMock()
    finto.acquisisci.return_value = blocco.Blocco("monitor", "test", blocco.ACQUISITO)
    finto.esito_saltato.side_effect = blocco.esito_saltato
    finto.rilascia.return_value = True
    return finto


class _Giro(unittest.IsolatedAsyncioTestCase):
    """Un giro di `monitoraggio.run` senza rete ne' DB, con le righe
    `pipeline_run` raccolte in `self.righe_run`."""

    def setUp(self):
        self.righe_run = []
        for bersaglio in (
            patch.object(monitoraggio.telemetria, "scrivi_pipeline_run", self.righe_run.append),
            patch.object(monitoraggio, "_tabella_domini_del_giro", lambda: None),
            patch.object(eventi, "_rpc_disponibile", lambda controllo: False),
        ):
            bersaglio.start()
            self.addCleanup(bersaglio.stop)

    def riga_run(self, step):
        trovate = [r for r in self.righe_run if r.step == step]
        self.assertEqual(len(trovate), 1, f"una riga {step}")
        return trovate[0].contatori

    async def giro_di_produzione(self, dati, *, impostazioni, adesso, cambiate=(),
                                 classifica=None, opus=None, contatori=None, orologio=None,
                                 scarico=None):
        """Il giro con lo scarico «proprio» e il riscrittore di produzione,
        che passa da `rigenera.riscrivi_scheda` (qui `opus`). Senza un
        classificatore il giro si dichiarerebbe non configurato. `scarico`
        sono i contatori finti del client del giro (zero se non dati)."""
        contatori = contatori if contatori is not None else bilancio.Contatori()
        classifica = classifica or _classificatore([], contatori)
        scarico = scarico if scarico is not None else _ContatoriScarico()
        with patch.object(monitoraggio, "_scarico_predefinito", lambda: _scarica(cambiate)), \
                patch.object(monitoraggio, "_azzera_scarico", lambda: None), \
                patch.object(monitoraggio, "_host_richiede_js_dello_scarico", lambda: frozenset()), \
                patch.object(monitoraggio, "_contatori_scarico", lambda: scarico), \
                patch.object(monitoraggio, "_azzera_contatori_scarico", scarico.azzera), \
                patch.object(monitoraggio, "_host_morti_dello_scarico", lambda: ()), \
                patch.object(monitoraggio.rigenera_mod, "riscrivi_scheda", opus):
            return await monitoraggio.run(
                impostazioni=impostazioni, fonte_dati=dati, classifica=classifica,
                contatori=contatori, lock=_lock_libero(), adesso=adesso,
                casuale=lambda: 0.5, orologio=orologio or (lambda: 0.0))

    def code_scritte(self, dati, ident):
        """Le code `__riscrittura__` scritte per un bando (None = tolta)."""
        return [c["impronte_sezioni"].get(monitoraggio.CHIAVE_RISCRITTURA)
                for i, c in dati.scritture if i == ident and "impronte_sezioni" in c]


# --- funzioni pure ------------------------------------------------------------

class TestGiriRimasti(unittest.TestCase):
    def test_giorno_con_i_quattro_giri(self):
        casi = ((0, 0, 3), (1, 54, 3), (5, 59, 3), (6, 0, 2), (11, 59, 2), (12, 0, 1),
                (17, 59, 1), (18, 0, 0), (23, 59, 0))
        for ora, minuti, attesi in casi:
            with self.subTest(ora=f"{ora:02d}:{minuti:02d}"):
                adesso = datetime(2026, 10, 2, ora, minuti, tzinfo=ROMA)
                self.assertEqual(monitoraggio.giri_rimasti(adesso, GIRI)[0], attesi)

    def test_solo_due_giri(self):
        adesso = datetime(2026, 10, 2, 1, 0, tzinfo=ROMA)
        self.assertEqual(monitoraggio.giri_rimasti(adesso, ("06:00", "18:00"))[0], 2)

    def test_istante_utc_portato_a_roma(self):
        # 23:54 UTC del 01/10 sono le 01:54 del 02/10 a Roma: il giro delle 00.
        self.assertEqual(monitoraggio.giri_rimasti(GIRO_DEL_2_OTTOBRE, GIRI), (3, 3 + 4 * 29))

    def test_cambio_d_ora_del_25_ottobre(self):
        # Alle 03:00 del 25/10/2026 si torna a +01:00. Con l'ora legale
        # «fissa» le 04:30 UTC sarebbero le 06:30 (2 giri), invece sono le 05:30.
        casi = (
            (datetime(2026, 10, 24, 4, 30, tzinfo=timezone.utc), 2),   # 06:30 +02:00
            (datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), 3),   # 02:30 +02:00
            (datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc), 3),   # 02:30 +01:00
            (datetime(2026, 10, 25, 4, 30, tzinfo=timezone.utc), 3),   # 05:30 +01:00
            (datetime(2026, 10, 25, 5, 30, tzinfo=timezone.utc), 2),   # 06:30 +01:00
            (datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc), 0),  # 23:30 +01:00
        )
        for adesso, attesi in casi:
            with self.subTest(adesso=adesso.isoformat()):
                self.assertEqual(monitoraggio.giri_rimasti(adesso, GIRI)[0], attesi)

    def test_mese(self):
        casi = (
            (datetime(2026, 10, 31, 18, 30, tzinfo=ROMA), (0, 0)),
            (datetime(2026, 10, 30, 18, 30, tzinfo=ROMA), (0, 4)),
            (datetime(2026, 10, 2, 1, 54, tzinfo=ROMA), (3, 3 + 4 * 29)),
            # Il mese di Roma, non quello UTC: alle 00:30 dell'01/11 a Roma e'
            # gia' novembre (in UTC e' ancora il 31/10).
            (datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc), (3, 3 + 4 * 29)),
        )
        for adesso, attesi in casi:
            with self.subTest(adesso=adesso.isoformat()):
                self.assertEqual(monitoraggio.giri_rimasti(adesso, GIRI), attesi)

    def test_orari_non_validi_ignorati(self):
        adesso = datetime(2026, 10, 2, 1, 0, tzinfo=ROMA)
        self.assertEqual(monitoraggio.giri_rimasti(adesso, ("06:00", "x", "25:00", "", None)),
                         (1, 1 + 29))
        self.assertEqual(monitoraggio.giri_rimasti(adesso, ()), (0, 0))


class TestCostoMassimo(unittest.TestCase):
    def test_segue_seo_max_tokens_e_listino(self):
        # 12 000 token d'ingresso + SEO_MAX_TOKENS d'uscita al listino SEO.
        self.assertAlmostEqual(monitoraggio.costo_massimo_riscrittura(_impostazioni()), 0.16)
        self.assertAlmostEqual(
            monitoraggio.costo_massimo_riscrittura(_impostazioni(seo_max_tokens=8000)), 0.26)
        self.assertAlmostEqual(monitoraggio.costo_massimo_riscrittura(_impostazioni(
            seo_model="m", listino_modelli={"m": (3.0, 15.0)})), 0.096)
        self.assertEqual(monitoraggio.TOKEN_INGRESSO_RISCRITTURA_MAX, 12000)

    def test_fuori_listino_vale_zero_come_in_bilancio(self):
        self.assertEqual(monitoraggio.costo_massimo_riscrittura(_impostazioni(seo_model="ignoto")),
                         0.0)
        self.assertEqual(monitoraggio.costo_massimo_riscrittura(SimpleNamespace()), 0.0)


class TestRiscritturaConsentita(unittest.TestCase):
    TETTI = bilancio.Tetti(usd_giorno=5.0, usd_mese=150.0)

    def consentita(self, consumo, tetti=None, costo=0.16, giri_oggi=3, giri_mese=119):
        return monitoraggio.riscrittura_consentita(
            consumo, tetti or self.TETTI, costo_massimo=costo, giri_oggi=giri_oggi,
            giri_mese=giri_mese)

    def test_le_costanti(self):
        self.assertEqual((monitoraggio.QUOTA_RISERVA_GIRO, monitoraggio.MARGINE_GIRO_USD),
                         (0.20, 0.25))

    def test_sotto_la_riserva_si_sopra_no(self):
        # Alle 00: riserva 3 x 1 $ + 0,25 = 3,25, quindi limite 1,75.
        self.assertTrue(self.consentita({"usd": 1.0}).consentito)
        self.assertTrue(self.consentita({"usd": 1.59}).consentito)       # 1,75 esatti
        rinviata = self.consentita({"usd": 1.6})
        self.assertFalse(rinviata.consentito)
        self.assertEqual((rinviata.voce, rinviata.motivo_rimasti), ("usd", "spesa"))
        self.assertIn("riserva", rinviata.motivo)
        # Alle 18 resta solo il margine: limite 4,75.
        self.assertTrue(self.consentita({"usd": 4.5}, giri_oggi=0).consentito)
        self.assertFalse(self.consentita({"usd": 4.6}, giri_oggi=0).consentito)

    def test_tetto_a_zero_nessun_tetto_e_nessuna_riserva(self):
        self.assertTrue(self.consentita({"usd": 999.0, "usd_mese": 9999.0},
                                        tetti=bilancio.Tetti()).consentito)
        self.assertTrue(self.consentita(None, tetti=bilancio.Tetti()).consentito)
        self.assertEqual(monitoraggio.riserva_usd(0.0, 3), 0.0)
        self.assertEqual(monitoraggio.riserva_usd(5.0, 3), 3.25)

    def test_consumo_illeggibile_rinviata(self):
        esito = self.consentita(None)
        self.assertFalse(esito.consentito)
        self.assertEqual(esito.motivo, bilancio.MOTIVO_CONSUMO_ILLEGGIBILE)

    def test_giorno_con_margine_ma_mese_oltre_la_riserva(self):
        # Il 02/10 alle 01:54: 119 giri nel mese, riserva 119,25, limite 30,75.
        self.assertTrue(self.consentita({"usd": 0.5, "usd_mese": 30.5}).consentito)
        mese = self.consentita({"usd": 0.5, "usd_mese": 30.7})
        self.assertFalse(mese.consentito)
        self.assertIn("mese", mese.motivo)
        # Il mese non letto non si controlla (come `bilancio.verifica`).
        self.assertTrue(self.consentita({"usd": 0.5}).consentito)


class TestDateDellaNovita(unittest.TestCase):
    def test_data_messa_per_la_prima_volta_dalla_rielaborazione(self):
        evento = {"id": 1, "tipo": "rettifica", "campo": "data_apertura", "valore_prima": None,
                  "valore_dopo": {"data_apertura": "2026-11-02"},
                  "gate": {"prima": None, "contesto": "rielaborazione"}}
        self.assertEqual(monitoraggio.date_della_novita(evento),
                         (True, None, date(2026, 11, 2), "apertura"))

    def test_data_di_prima_dal_monitor_o_dal_gate(self):
        monitor = {"tipo": "proroga", "valore_prima": {"data_scadenza": "2026-10-15"},
                   "valore_dopo": {"data_scadenza": "2026-10-30"}}
        self.assertEqual(monitoraggio.date_della_novita(monitor),
                         (True, date(2026, 10, 15), date(2026, 10, 30), "scadenza"))
        gate = {"tipo": "rettifica", "campo": "data_scadenza",
                "valore_dopo": {"data_scadenza": "2026-10-30"}, "gate": {"prima": "2026-10-15"}}
        self.assertEqual(monitoraggio.date_della_novita(gate)[:2], (True, date(2026, 10, 15)))

    def test_data_di_prima_ignota_o_non_una_data(self):
        ignota = {"tipo": "rettifica", "campo": "data_scadenza",
                  "valore_dopo": {"data_scadenza": "2026-10-30"}}
        self.assertFalse(monitoraggio.date_della_novita(ignota)[0])
        illeggibile = dict(ignota, gate={"prima": "domani"})
        self.assertFalse(monitoraggio.date_della_novita(illeggibile)[0])
        for evento in ({"tipo": "faq"}, {"tipo": "rettifica", "campo": "contenuto"},
                       {"tipo": "rettifica", "campo": "data_scadenza"}, None):
            with self.subTest(evento=evento):
                self.assertIsNone(monitoraggio.date_della_novita(evento))


class TestOrdinaRiscritture(unittest.TestCase):
    def test_dal_crescente_poi_id_le_nuove_in_fondo(self):
        adesso = datetime(2026, 10, 2, 18, 30, tzinfo=ROMA)
        nuova = monitoraggio.EsitoControllo(bando_id=1, novita=[{"tipo": "faq"}])
        coppie = [
            (_bando(1), nuova),
            (_in_coda(2, _coda(2, dal="2026-10-01T08:00:00+00:00")), monitoraggio.EsitoControllo()),
            (_in_coda(4, _coda(4, dal="2026-09-30T08:00:00+00:00")), monitoraggio.EsitoControllo()),
            (_in_coda(3, _coda(3, dal="2026-09-30T08:00:00+00:00")), monitoraggio.EsitoControllo()),
            (_in_coda(5, _coda(5, dal="illeggibile")), monitoraggio.EsitoControllo()),
        ]
        ordinate = monitoraggio.ordina_riscritture(coppie, adesso=adesso)
        self.assertEqual([r["id"] for r, _e in ordinate], [5, 3, 4, 2, 1])


# --- il giro: fase 1 prima della fase 2 --------------------------------------

class TestOrdineDelleFasi(_Giro):
    async def test_tutte_le_classificazioni_prima_di_ogni_riscrittura(self):
        # Il bando in coda viene PRIMA nella selezione: fino al 02/10 la sua
        # riscrittura partiva prima delle classificazioni degli altri due.
        registro = []
        dati = _Fonte(righe=[_in_coda(1), _bando(2), _bando(3)])
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=dati, scarica=_scarica({2, 3}),
            classifica=_classificatore(registro, bilancio.Contatori()),
            lock=_lock_libero(), adesso=GIRO_DEL_2_OTTOBRE, casuale=lambda: 0.5,
            riscrittore=_Riscrittore(registro))
        self.assertEqual(registro, [("classifica", 2), ("classifica", 3), ("riscrivi", 1)])
        self.assertEqual((esito["classificazioni"], esito["riscritture"]), (2, 1))


class TestRipetizioneDel2Ottobre(_Giro):
    """Il giro delle 00 del 02/10: 0,386 $ gia' spesi dalla catena d'ingresso,
    3 pagine cambiate, 40 bandi in coda, una riscrittura da 0,144 $."""

    async def test_il_monitor_classifica_e_le_riscritture_si_fermano_alla_riserva(self):
        registro = []
        contatori = bilancio.Contatori()
        in_coda = [_in_coda(i) for i in range(1, 41)]
        dati = _Fonte(righe=[*in_coda, _bando(101), _bando(102), _bando(103)],
                      consumo={"usd": 0.386064, "usd_mese": 10.0})
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=GIRO_DEL_2_OTTOBRE,
            cambiate={101, 102, 103}, classifica=_classificatore(registro, contatori),
            opus=_Opus(registro), contatori=contatori)

        # Le tre classificazioni sono fatte, e prima di ogni riscrittura.
        classificate = [i for tipo, i in registro if tipo == "classifica"]
        self.assertEqual(classificate, [101, 102, 103])
        self.assertEqual(registro[:3], [("classifica", i) for i in (101, 102, 103)])
        self.assertEqual((esito["classificazioni"], esito["classificazioni_rinviate"]), (3, 0))

        # Riserva delle 00: 3 giri x 1 $ + 0,25. Le riscritture si fermano
        # prima di toccarla: 0,386 + 0,045 + 9 x 0,144 = 1,727 <= 1,75, e la
        # decima (1,727 + 0,16 di costo massimo) la toccherebbe.
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual(riga["riserva_usd"], 3.25)
        spesa_totale = 0.386064 + contatori.usd + riga["usd"]
        self.assertLessEqual(spesa_totale, 5.0 - 3.0 - 0.25)
        self.assertEqual((esito["riscritture"], esito["riscritture_rinviate"]), (9, 31))
        self.assertEqual((riga["riscritture"], riga["rinviate_per_riserva"]), (9, 31))
        self.assertEqual(riga["copertura"],
                         {"candidati": 40, "fatti": 9, "rimasti": 31, "motivo_rimasti": "spesa"})
        # Rotazione: le riscritte sono le prime 9 per `dal` (tutte uguali) e id.
        self.assertEqual([i for tipo, i in registro if tipo == "riscrivi"], list(range(1, 10)))
        # Le rinviate restano in coda com'erano: tentativi e `dal` invariati.
        for ident in range(10, 41):
            for coda in self.code_scritte(dati, ident):
                self.assertEqual(coda, _coda(ident))


class TestUltimoGiro(_Giro):
    async def test_alle_18_si_usa_il_resto_senza_superare_il_tetto(self):
        registro = []
        dati = _Fonte(righe=[_in_coda(i) for i in range(1, 11)],
                      consumo={"usd": 4.0, "usd_mese": 10.0})
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=ULTIMO_GIRO, opus=_Opus(registro))
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        # 4,0 + 5 x 0,144 = 4,72 <= 4,75; la sesta porterebbe il costo massimo
        # oltre il limite. Fino al 02/10 la riscrittura vera controllava solo
        # «gia' speso < 5»: la settima chiamata arrivava a 5,008.
        self.assertLessEqual(4.0 + riga["usd"], 5.0 - 0.25)
        self.assertEqual(esito["riscritture"], 5)
        self.assertGreater(4.0 + riga["usd"], 5.0 - 0.25 - monitoraggio.costo_massimo_riscrittura(
            _di_produzione()))
        self.assertEqual(riga["riserva_usd"], 0.25)


class TestTempoFinitoInFase1(_Giro):
    PRIMA = "<main><h1>Avviso</h1><p>Domande entro il 30 ottobre 2026.</p></main>"
    DOPO = ("<main><h1>Avviso</h1><p>Domande entro il 30 ottobre 2026.</p>"
            "<p>Pubblicate le FAQ e la graduatoria finale.</p></main>")

    def riga(self, ident):
        return _bando(ident, slug=f"avviso-{ident}", impronta_contenuto="vecchia",
                      testo_norm=monitoraggio.comprimi_testo(impronte.testo_normalizzato(self.PRIMA)),
                      impronte_sezioni={"__link__": [], **VERSIONE}, data_scadenza="2026-10-30")

    async def test_nessuna_riscrittura_e_le_novita_restano_in_coda(self):
        async def scarica(url, **_kw):
            return _Risposta(html=self.DOPO)

        async def classifica(ctx):
            return [eventi.Evento(tipo="faq", url_prova=_url(ctx.bando_id),
                                  citazione="Pubblicate le FAQ")]

        ammesso = eventi.Giudizio(ammesso=True, gate="G2", superati=("G1", "G2", "G4", "G7"),
                                  confidenza=0.95, leggibile=True)
        riscrittore = _Riscrittore()
        dati = _Fonte(righe=[self.riga(1), self.riga(2)])
        # Avvio e primo bando a 0 s, poi il tempo del giro e' finito.
        with patch.object(monitoraggio.eventi_mod, "valuta", lambda evento, ctx: ammesso):
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=("faq",)), fonte_dati=dati,
                scarica=scarica, classifica=classifica, lock=_lock_libero(),
                adesso=GIRO_DEL_2_OTTOBRE, casuale=lambda: 0.5, riscrittore=riscrittore,
                orologio=_Orologio(0.0, 0.0, monitoraggio.TEMPO_MONITOR_S + 1))
        self.assertTrue(esito["interrotto_per_tempo"])
        self.assertEqual(riscrittore.chiamate, [])
        self.assertEqual((esito["riscritture"], esito["riscritture_rinviate"]), (0, 1))
        coda = self.code_scritte(dati, 1)[-1]
        self.assertEqual([v["tipo"] for v in coda["novita"]], ["faq"])
        self.assertEqual(coda["tentativi"], 0)
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual((riga["rinviate_per_tempo"], riga["copertura"]["motivo_rimasti"]),
                         (1, "tempo"))


class TestRotazione(_Giro):
    async def test_soldi_per_una_chiamata_va_la_voce_piu_vecchia(self):
        registro = []
        code = {1: _coda(1, dal="2026-10-01T08:00:00+00:00"),
                2: _coda(2, dal="2026-10-02T09:00:00+00:00"),
                3: _coda(3, dal="2026-09-30T08:00:00+00:00")}
        dati = _Fonte(righe=[_in_coda(i, code[i]) for i in (1, 2, 3)],
                      consumo={"usd": 4.45, "usd_mese": 10.0})
        # Alle 18:30 il limite e' 4,75: 4,45 + 0,16 ci sta, 4,594 + 0,16 no.
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=ULTIMO_GIRO, opus=_Opus(registro))
        self.assertEqual(registro, [("riscrivi", 3)])
        self.assertEqual((esito["riscritture"], esito["riscritture_rinviate"]), (1, 2))
        # La riscritta esce dalla coda; le rinviate conservano il loro `dal`.
        self.assertEqual(self.code_scritte(dati, 3), [None])
        for ident in (1, 2):
            for coda in self.code_scritte(dati, ident):
                self.assertEqual(coda["dal"], code[ident]["dal"])
        # Solo la scheda riscritta e' una pagina nuova per IndexNow.
        self.assertEqual(esito["slug_modificati"], ["avviso-3"])


class TestRotazioneDeiChiusi(_Giro):
    """Un chiuso con la coda rinviata in fase 2 torna al giro dopo (§22.1),
    invece di aspettare la cadenza (3, 10 o 30 giorni) scritta dal controllo:
    a coda invariata la fase 2 non scriveva niente."""

    def dopo_il_giro(self, dati, riga):
        """La riga com'e' dopo il giro: tutte le scritture del bando, in ordine."""
        dopo = dict(riga)
        for ident, colonne in dati.scritture:
            if ident == riga["id"]:
                dopo.update(colonne)
        return dopo

    def verifica_al_giro_dopo(self, dati, chiuso, aperto):
        adesso = monitoraggio.adesso_roma(GIRO_DEL_2_OTTOBRE)
        dopo = self.dopo_il_giro(dati, chiuso)
        self.assertEqual(dopo["prossimo_controllo_at"], adesso.isoformat())
        # La coda resta com'era: `dal` e tentativi invariati (rotazione di §1).
        self.assertEqual(dopo["impronte_sezioni"][monitoraggio.CHIAVE_RISCRITTURA], _coda(1))
        for ora in (6, 12, 18):
            giro_dopo = datetime(2026, 10, 2, ora, 30, tzinfo=ROMA)
            with self.subTest(ora=ora):
                self.assertTrue(monitoraggio.selezionabile(dopo, adesso=giro_dopo))
                self.assertTrue(monitoraggio.selezionabile(self.dopo_il_giro(dati, aperto),
                                                           adesso=giro_dopo))

    async def test_rinviato_per_riserva(self):
        # Alle 01:54 il limite e' 1,75 $: 1,7 + 0,16 di costo massimo lo supera.
        registro = []
        chiuso = _in_coda(1, stato_bando="chiuso", data_scadenza="2026-06-30")
        aperto = _in_coda(2)
        dati = _Fonte(righe=[chiuso, aperto], consumo={"usd": 1.7, "usd_mese": 10.0})
        await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=GIRO_DEL_2_OTTOBRE, opus=_Opus(registro))
        self.assertEqual(registro, [])
        self.assertEqual(self.riga_run(rigenera.STEP_RISCRITTURA)["rinviate_per_riserva"], 2)
        self.verifica_al_giro_dopo(dati, chiuso, aperto)

    async def test_rinviato_per_tempo(self):
        # Avvio e i due controlli a 0 s, poi il tempo del giro e' finito.
        registro = []
        chiuso = _in_coda(1, stato_bando="chiuso", data_scadenza="2026-06-30")
        aperto = _in_coda(2)
        dati = _Fonte(righe=[chiuso, aperto], consumo={"usd": 0.0, "usd_mese": 0.0})
        await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=GIRO_DEL_2_OTTOBRE, opus=_Opus(registro),
            orologio=_Orologio(0.0, 0.0, 0.0, monitoraggio.TEMPO_MONITOR_S + 1))
        self.assertEqual(registro, [])
        self.assertEqual(self.riga_run(rigenera.STEP_RISCRITTURA)["rinviate_per_tempo"], 2)
        self.verifica_al_giro_dopo(dati, chiuso, aperto)


class TestCreditiDelleRiscritture(_Giro):
    """I fetch e i crediti Firecrawl della pagina riletta dalla riscrittura in
    fase 2 entrano nei contatori del giro, una volta sola, bando per bando."""

    async def test_contati_una_volta_sola_nella_riga_del_monitor(self):
        scarico = _ContatoriScarico()
        contatori = bilancio.Contatori()
        dati = _Fonte(righe=[_in_coda(i) for i in range(1, 6)],
                      consumo={"usd": 0.0, "usd_mese": 0.0})
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=ULTIMO_GIRO,
            opus=_OpusConRipiego([], scarico), contatori=contatori, scarico=scarico)
        self.assertEqual(esito["riscritture"], 5)
        self.assertEqual((contatori.crediti_firecrawl, contatori.fetch), (5, 5))
        # Nella riga del monitor, non in quella delle riscritture: mai in due.
        monitor = [r for r in self.righe_run if r.step == monitoraggio.STEP]
        self.assertEqual([r.crediti for r in monitor], [5])
        self.assertEqual(sum(r.crediti for r in self.righe_run), 5)
        self.assertEqual(self.riga_run(rigenera.STEP_RISCRITTURA)["crediti_firecrawl"], 0)
        # E niente resta nello scarico, che il giro dopo azzererebbe.
        self.assertEqual(scarico.crediti_firecrawl, 0)

    async def test_il_tetto_dei_crediti_vede_le_riscritture_precedenti(self):
        # Tetto di 3 crediti al giorno: la quarta riscrittura vede i 3 crediti
        # delle prime tre (`_gia_con(gia_oggi, contatori)`) e si rinvia.
        registro = []
        scarico = _ContatoriScarico()
        dati = _Fonte(righe=[_in_coda(i) for i in range(1, 6)],
                      consumo={"usd": 0.0, "usd_mese": 0.0, "crediti": 0, "crediti_mese": 0})
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(tetto_crediti_giorno=3), adesso=ULTIMO_GIRO,
            opus=_OpusConRipiego(registro, scarico), scarico=scarico)
        self.assertEqual(registro, [("riscrivi", i) for i in (1, 2, 3)])
        self.assertEqual((esito["riscritture"], esito["riscritture_rinviate"]), (3, 2))


# --- regressioni ----------------------------------------------------------------

class TestRegressioni(_Giro):
    async def test_consumo_illeggibile_niente_modello_e_niente_opus(self):
        registro = []
        contatori = bilancio.Contatori()
        dati = _Fonte(righe=[_in_coda(1), _bando(2)], consumo=None)
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=GIRO_DEL_2_OTTOBRE, cambiate={2},
            classifica=_classificatore(registro, contatori), opus=_Opus(registro),
            contatori=contatori)
        self.assertEqual(registro, [])
        self.assertEqual((esito["classificazioni_rinviate"], esito["riscritture_rinviate"]), (1, 1))
        for coda in self.code_scritte(dati, 1):
            self.assertEqual(coda, _coda(1))
        # Il rinvio e' del consumo illeggibile (§18.5), non della riserva.
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual((riga["rinviate_per_riserva"], riga["copertura"]["motivo_rimasti"]),
                         (0, "spesa"))

    async def test_lo_slug_della_fase_2_va_in_slug_modificati_e_nella_riga(self):
        registro = []
        dati = _Fonte(righe=[_in_coda(1, _coda(1, dal="2026-10-01T08:00:00+00:00")),
                             _in_coda(2, _coda(2, dal="2026-09-30T08:00:00+00:00"))],
                      consumo={"usd": 4.45, "usd_mese": 10.0})
        esito = await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=ULTIMO_GIRO, opus=_Opus(registro))
        self.assertEqual(esito["slug_modificati"], ["avviso-2"])
        riga = [r for r in self.righe_run if r.step == rigenera.STEP_RISCRITTURA][0]
        self.assertEqual(riga.slug_modificati, ("avviso-2",))

    async def test_riserva_usd_nella_riga_delle_riscritture(self):
        # Giro delle 06 (06:30 di Roma): restano le 12 e le 18.
        dati = _Fonte(righe=[_in_coda(1)], consumo={"usd": 0.0, "usd_mese": 0.0})
        await self.giro_di_produzione(
            dati, impostazioni=_di_produzione(), adesso=datetime(2026, 10, 2, 6, 30, tzinfo=ROMA),
            opus=_Opus([]))
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual((riga["riserva_usd"], riga["riscritture"]), (2.25, 1))


# --- §22.3 e §22.4 ----------------------------------------------------------------

class TestChiusuraSenzaModello(_Giro):
    """Le code che chiedono solo date messe per la prima volta (da NULL) o date
    che la prosa dice gia' si chiudono senza Opus."""

    def evento(self, ident, campo="data_apertura", prima=None, dopo="2026-11-02", **extra):
        riga = {"id": ident, "tipo": "rettifica", "campo": campo, "valore_prima": None,
                "valore_dopo": {campo: dopo}, "gate": {"prima": prima, "contesto": "rielaborazione"}}
        riga.update(extra)
        return riga

    def voce(self, evento_id, tipo="rettifica", campo="data_apertura"):
        return {"evento_id": evento_id, "tipo": tipo, "campo": campo, "citazione": "x"}

    async def test_solo_date_da_null_o_gia_in_linea(self):
        righe = [
            # 1: data messa per la prima volta (rielaborazione, gate.prima NULL).
            _in_coda(1, _coda(1, novita=[self.voce(501)]), contenuto="Testo."),
            # 2: data con un valore di prima che la prosa dice gia'.
            _in_coda(2, _coda(2, novita=[self.voce(502, campo="data_scadenza")]),
                     contenuto="Domande entro il 30 ottobre 2026."),
            # 3: una data da NULL e una FAQ: la FAQ chiede Opus.
            _in_coda(3, _coda(3, novita=[self.voce(503), self.voce(504, tipo="faq", campo=None)]),
                     contenuto="Testo."),
            # 4: data con un valore di prima che la sostituzione non riallinea.
            _in_coda(4, _coda(4, novita=[self.voce(505, campo="data_scadenza")]),
                     contenuto="Domande entro il 15 ottobre 2026."),
            # 5: evento che non si rilegge.
            _in_coda(5, _coda(5, novita=[self.voce(599)]), contenuto="Testo."),
            # 6: data riallineata senza modello (la sostituzione ha scritto).
            _in_coda(6, _coda(6, novita=[self.voce(506, campo="data_scadenza")]),
                     contenuto="Domande entro il 15 ottobre 2026."),
        ]
        dati = _Fonte(righe=righe, eventi={
            1: [self.evento(501)],
            2: [self.evento(502, campo="data_scadenza", prima="2026-10-15", dopo="2026-10-30")],
            3: [self.evento(503), {"id": 504, "tipo": "faq"}],
            4: [self.evento(505, campo="data_scadenza", prima="2026-10-01", dopo="2026-10-30")],
            6: [self.evento(506, campo="data_scadenza", prima="2026-10-15", dopo="2026-10-30")],
        })
        rigenerate = []

        async def rigenerazione(bando, evento, *, vecchia, nuova, ruolo):
            rigenerate.append((bando["id"], vecchia, nuova, ruolo))
            if bando["id"] == 2:
                return {"via": "box", "scritto": False,
                        "motivi": ["contenuto gia' in linea: nessuna scrittura"]}
            if bando["id"] == 6:
                return {"via": "sostituzione", "scritto": True,
                        "payload": {"contenuto": "Domande entro il 30 ottobre 2026."}}
            return {"via": "box", "scritto": False, "motivi": ["gate: data vecchia"]}

        riscrittore = _Riscrittore()
        esito = await monitoraggio.run(
            impostazioni=_impostazioni(), fonte_dati=dati, scarica=_scarica(),
            classifica=_classificatore([], bilancio.Contatori()), rigenerazione=rigenerazione,
            lock=_lock_libero(), adesso=GIRO_DEL_2_OTTOBRE, casuale=lambda: 0.5,
            riscrittore=riscrittore)

        self.assertEqual(sorted(i for i, _n in riscrittore.chiamate), [3, 4, 5])
        # Il bando con la data da NULL non chiede nemmeno la sostituzione.
        self.assertEqual(sorted(i for i, *_ in rigenerate), [2, 4, 6])
        self.assertIn((2, date(2026, 10, 15), date(2026, 10, 30), "scadenza"), rigenerate)
        for ident in (1, 2, 6):
            self.assertEqual(self.code_scritte(dati, ident), [None])
        self.assertEqual(esito["chiuse_senza_modello"], 3)
        self.assertEqual(esito["riscritture"], 3)
        # La prosa riallineata senza modello e' una pagina nuova.
        self.assertIn("avviso-6", esito["slug_modificati"])
        self.assertNotIn("avviso-1", esito["slug_modificati"])
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual(riga["chiuse_senza_modello"], 3)
        self.assertEqual(riga["copertura"]["fatti"], 6)

    async def test_novita_nuove_del_giro_non_si_chiudono(self):
        # Una coda da NULL, ma il giro porta una novita' nuova: si riscrive.
        riga = _in_coda(1, _coda(1, novita=[self.voce(501)]))
        esito = monitoraggio.EsitoControllo(bando_id=1, novita=[{"evento_id": 9, "tipo": "faq"}])
        dati = _Fonte(righe=[riga], eventi={1: [self.evento(501)]})
        chiusa = await monitoraggio._chiudi_senza_modello(
            riga, esito, scrittore=dati, rigenerazione=None,
            adesso=monitoraggio.adesso_roma(GIRO_DEL_2_OTTOBRE))
        self.assertFalse(chiusa)
        self.assertEqual(dati.scritture, [])


class TestRisposteTroncate(_Giro):
    async def test_si_contano_e_il_motivo_va_nel_log(self):
        troncata = ("SEO fallita: payload manca campo required: allegati "
                    "(risposta troncata: max_tokens)")
        riscrittore = _Riscrittore(esiti={1: "fallita", 2: "fallita"},
                                   motivi={1: troncata, 2: "testo riscritto fuori forma"})
        dati = _Fonte(righe=[_in_coda(1), _in_coda(2)])
        log = MagicMock()
        with patch.object(monitoraggio, "logger", log):
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(), fonte_dati=dati, scarica=_scarica(),
                classifica=_classificatore([], bilancio.Contatori()), lock=_lock_libero(),
                adesso=GIRO_DEL_2_OTTOBRE, casuale=lambda: 0.5, riscrittore=riscrittore)
        self.assertEqual((esito["riscritture_fallite"], esito["riscritture_troncate"]), (2, 1))
        riga = self.riga_run(rigenera.STEP_RISCRITTURA)
        self.assertEqual(riga["riscritture_troncate"], 1)
        avvisi = [" ".join(str(a) for a in c.args) for c in log.warning.call_args_list]
        self.assertTrue(any(troncata in a and "risposta troncata" in a for a in avvisi), avvisi)
        self.assertTrue(any("testo riscritto fuori forma" in a for a in avvisi), avvisi)
        # Il tentativo si conta come prima.
        self.assertEqual(self.code_scritte(dati, 1)[-1]["tentativi"], 1)


if __name__ == "__main__":
    unittest.main()
