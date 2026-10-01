# -*- coding: utf-8 -*-
"""Il «chiuso» del modello nella fase A di enrich (contratto del giro 3, §21.1, estensione).

La fase A (`refine_stato_bando` sulle righe `processed` con stato NULL)
scriveva il «chiuso» del modello senza guardare la scadenza: la riga restava
`processed` e chiusa, fuori da enrich e SEO, nascosta per sempre. Ora, dopo la
risposta del modello e il controllo di confidenza, lo stato passa da
`preprocessor.scarta_chiuso_del_modello` (scadenza della riga da oggi in poi ->
'aperto') e poi da `reconcile_stato_bando` (apertura futura -> «in apertura
prossimamente»). Lo stato che ne esce e' quello scritto e quello che decide la
promozione alla fase B; in dry-run vale uguale ma non si scrive. Il contatore
`chiuso_modello_scartato` sta fra quelli di enrich e conta gli scarti, non i
cambi di stato. Effetto voluto: un «aperto» o «in apertura» del modello con la
scadenza della riga gia' passata si scrive «chiuso» e non va alla fase B.

«Oggi» e' fisso, il modello e' finto, nessuna rete. L'orologio vero e' fermo su
una data lontana da OGGI (e dalla data reale): chi lo legge al posto
dell'«oggi» della fase A sbaglia e il test cade.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_chiuso_modello_enrich
"""
import asyncio
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from tests.supporto import carica_modulo

er = carica_modulo("bando_enrich_runner")
telemetria = carica_modulo("telemetria")
dv = carica_modulo("date_validation")
stato_bando = carica_modulo("stato_bando")

#: Il giorno del primo giro in produzione: l'«oggi» che la fase A deve usare.
OGGI = date(2026, 10, 1)

#: L'orologio vero durante i test. `stato_bando.adesso_roma` e' la fonte di
#: ogni `oggi_roma()` non sostituito, compreso quello di default di
#: `reconcile_stato_bando`. La data e' dopo tutte le scadenze dei casi: una
#: fase A che chiama la riconciliazione senza `today=oggi_refine` vede le
#: scadenze passate e chiude i bandi che dovevano restare aperti.
OROLOGIO_FINTO = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)
_ADESSO_VERO = stato_bando.adesso_roma


def _adesso_finto(adesso=None):
    """`adesso_roma` con l'orologio fermo su OROLOGIO_FINTO (un istante passato vale come prima)."""
    return _ADESSO_VERO(OROLOGIO_FINTO if adesso is None else adesso)


def _orologio_finto():
    return mock.patch.object(stato_bando, "adesso_roma", new=_adesso_finto)

_RES_VUOTO = {
    "tipologia_bando_id": None, "modalita_erogazione_id": None, "programma_id": None,
    "beneficiari_ids": [], "codici_ateco_ids": [], "regioni_ids": [], "settori_ids": [],
}


def _bando(id_=1, *, scadenza=None, apertura=None):
    """Una riga `processed` con lo stato NULL (bersaglio della fase A)."""
    return {"id": id_, "fonte_id": None, "link_bando": "", "stato_bando": None,
            "data_scadenza": scadenza, "data_apertura": apertura}


def _esegui(bandi, risposte, *, dry_run=False):
    """Lancia `run` con il modello finto: `risposte` e' {bando_id: (stato, conf, motivo)}."""
    chiamate_oggi: list[int] = []

    def oggi_fisso():
        chiamate_oggi.append(1)
        return OGGI

    async def refine(bando, _fonte):
        return risposte[bando["id"]]

    with mock.patch.object(er, "select_bandi_to_enrich", return_value=bandi), \
            mock.patch.object(er, "select_fonti_by_ids", return_value={}), \
            mock.patch.object(er, "enrich_fonti_with_names", side_effect=lambda d: d), \
            mock.patch.object(er, "load_catalogo", return_value={}), \
            mock.patch.object(er, "refine_stato_bando", new=refine), \
            mock.patch.object(er, "update_bando_refinement",
                              new=mock.AsyncMock(return_value=True)) as scrivi_stato, \
            mock.patch.object(er, "enrich_bando",
                              new=mock.AsyncMock(return_value=dict(_RES_VUOTO))) as enrich, \
            mock.patch.object(er, "update_bando_enriched",
                              new=mock.AsyncMock(return_value=True)) as scrivi_enrich, \
            mock.patch.object(er, "oggi_roma", new=oggi_fisso), \
            _orologio_finto(), \
            mock.patch.object(telemetria, "scrivi_pipeline_run", return_value=None):
        contatori = asyncio.run(er.run(dry_run=dry_run))
    return contatori, scrivi_stato, enrich, scrivi_enrich, len(chiamate_oggi)


def _promossi(enrich) -> list[tuple[int, str]]:
    """(id, stato) delle righe arrivate alla fase B."""
    return [(c.args[0]["id"], c.args[0]["stato_bando"]) for c in enrich.await_args_list]


class ChiusoDelModelloNellaFaseA(unittest.TestCase):
    def test_scadenza_futura_scritto_aperto_e_promosso(self):
        contatori, scrivi_stato, enrich, scrivi_enrich, _o = _esegui(
            [_bando(scadenza="2026-11-01")], {1: ("chiuso", 0.9, "il modello dice chiuso")})
        scrivi_stato.assert_awaited_once_with(1, "aperto", confidence=0.9)
        self.assertEqual(_promossi(enrich), [(1, "aperto")])
        self.assertEqual(scrivi_enrich.await_args.args[:2], (1, "aperto"))
        self.assertEqual(contatori["refined_to_aperto"], 1)
        self.assertEqual(contatori["refined_to_chiuso"], 0)
        self.assertEqual(contatori["chiuso_modello_scartato"], 1)

    def test_scadenza_oggi_vale_aperto(self):
        contatori, scrivi_stato, enrich, _s, _o = _esegui(
            [_bando(scadenza="2026-10-01")], {1: ("chiuso", 0.9, "")})
        scrivi_stato.assert_awaited_once_with(1, "aperto", confidence=0.9)
        self.assertEqual(_promossi(enrich), [(1, "aperto")])
        self.assertEqual(contatori["chiuso_modello_scartato"], 1)

    def test_scadenza_passata_resta_chiuso_e_non_promosso(self):
        contatori, scrivi_stato, enrich, _s, _o = _esegui(
            [_bando(scadenza="2026-09-30")], {1: ("chiuso", 0.9, "")})
        scrivi_stato.assert_awaited_once_with(1, "chiuso", confidence=0.9)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["refined_to_chiuso"], 1)
        self.assertEqual(contatori["chiuso_modello_scartato"], 0)

    def test_scadenza_assente_resta_chiuso(self):
        contatori, scrivi_stato, enrich, _s, _o = _esegui(
            [_bando(scadenza=None)], {1: ("chiuso", 0.9, "")})
        scrivi_stato.assert_awaited_once_with(1, "chiuso", confidence=0.9)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["chiuso_modello_scartato"], 0)

    def test_apertura_futura_vale_in_apertura_e_promosso(self):
        contatori, scrivi_stato, enrich, scrivi_enrich, _o = _esegui(
            [_bando(apertura="2026-10-15", scadenza="2026-11-30")], {1: ("chiuso", 0.8, "")})
        scrivi_stato.assert_awaited_once_with(1, "in apertura prossimamente", confidence=0.8)
        self.assertEqual(_promossi(enrich), [(1, "in apertura prossimamente")])
        self.assertEqual(scrivi_enrich.await_args.args[:2], (1, "in apertura prossimamente"))
        self.assertEqual(contatori["refined_to_in_apertura"], 1)
        self.assertEqual(contatori["chiuso_modello_scartato"], 1)

    def test_confidenza_sotto_soglia_nessuna_scrittura(self):
        contatori, scrivi_stato, enrich, _s, _o = _esegui(
            [_bando(scadenza="2026-11-01")], {1: ("chiuso", 0.3, "dubbio")})
        self.assertEqual(scrivi_stato.await_count, 0)
        self.assertEqual(enrich.await_count, 0)
        self.assertEqual(contatori["refined_undetermined"], 1)
        self.assertEqual(contatori["chiuso_modello_scartato"], 0)

    def test_aperto_del_modello_non_si_conta(self):
        contatori, scrivi_stato, enrich, _s, _o = _esegui(
            [_bando(scadenza="2026-11-01")], {1: ("aperto", 0.9, "")})
        scrivi_stato.assert_awaited_once_with(1, "aperto", confidence=0.9)
        self.assertEqual(_promossi(enrich), [(1, "aperto")])
        self.assertEqual(contatori["chiuso_modello_scartato"], 0)


class ScadenzaPassataNellaFaseA(unittest.TestCase):
    """Effetto voluto (§21.1, estensione): un «aperto» o «in apertura» del
    modello con la scadenza della riga gia' passata si scrive «chiuso» in fase A
    e non va alla fase B, come nel preprocess. Non e' uno scarto: il contatore
    resta a zero."""

    def test_aperto_o_in_apertura_con_scadenza_passata_scritto_chiuso_non_promosso(self):
        for stato in ("aperto", "in apertura prossimamente"):
            with self.subTest(stato=stato):
                contatori, scrivi_stato, enrich, scrivi_enrich, _o = _esegui(
                    [_bando(scadenza="2026-09-30")], {1: (stato, 0.9, f"il modello dice {stato}")})
                scrivi_stato.assert_awaited_once_with(1, "chiuso", confidence=0.9)
                self.assertEqual(enrich.await_count, 0)
                self.assertEqual(scrivi_enrich.await_count, 0)
                self.assertEqual((contatori["refined_to_aperto"], contatori["refined_to_in_apertura"],
                                  contatori["refined_to_chiuso"]), (0, 0, 1))
                self.assertEqual(contatori["enriched_total"], 0)
                self.assertEqual(contatori["chiuso_modello_scartato"], 0)


class OrologioFinto(unittest.TestCase):
    def test_l_orologio_vero_e_fermo_lontano_da_oggi(self):
        # Controllo della trappola: senza `today` la riconciliazione legge
        # l'orologio finto (non OGGI, non la data reale) e chiude un bando che
        # con OGGI sarebbe aperto. Se un giorno `oggi_roma` non passasse piu' da
        # `adesso_roma`, questo test lo direbbe prima che la trappola si spenga.
        with _orologio_finto():
            self.assertEqual(dv.oggi_roma(), OROLOGIO_FINTO.date())
            self.assertNotEqual(dv.oggi_roma(), OGGI)
            self.assertEqual(dv.reconcile_stato_bando("aperto", None, date(2026, 11, 1)), "chiuso")
        self.assertEqual(dv.reconcile_stato_bando("aperto", None, date(2026, 11, 1), today=OGGI), "aperto")


class Contatore(unittest.TestCase):
    def test_conta_solo_i_chiusi_scartati(self):
        bandi = [
            _bando(1, scadenza="2027-07-26"),                       # scartato
            _bando(2, scadenza="2026-10-06"),                       # scartato
            _bando(3, scadenza="2026-09-30"),                       # passata: resta
            _bando(4),                                              # assente: resta
            _bando(5, scadenza="2026-11-01"),                       # sotto soglia
            _bando(6, apertura="2026-10-15", scadenza="2026-11-30"),  # scartato
            _bando(7, scadenza="2026-11-01"),                       # 'aperto' del modello
            # lo stato cambia senza scarto: non si contano
            _bando(8, apertura="2026-10-15", scadenza="2026-11-30"),  # aperto -> in apertura
            _bando(9, scadenza="2026-09-30"),                       # aperto -> chiuso
            _bando(10, scadenza="2026-09-30"),                      # in apertura -> chiuso
        ]
        risposte = {1: ("chiuso", 0.9, ""), 2: ("chiuso", 0.7, ""), 3: ("chiuso", 0.9, ""),
                    4: ("chiuso", 0.9, ""), 5: ("chiuso", 0.5, ""), 6: ("chiuso", 0.9, ""),
                    7: ("aperto", 0.9, ""), 8: ("aperto", 0.9, ""), 9: ("aperto", 0.9, ""),
                    10: ("in apertura prossimamente", 0.9, "")}
        contatori, scrivi_stato, enrich, _s, _o = _esegui(bandi, risposte)
        self.assertEqual(contatori["chiuso_modello_scartato"], 3)
        self.assertEqual(
            sorted(c.args[:2] for c in scrivi_stato.await_args_list),
            [(1, "aperto"), (2, "aperto"), (3, "chiuso"), (4, "chiuso"),
             (6, "in apertura prossimamente"), (7, "aperto"),
             (8, "in apertura prossimamente"), (9, "chiuso"), (10, "chiuso")],
        )
        self.assertEqual(sorted(_promossi(enrich)),
                         [(1, "aperto"), (2, "aperto"), (6, "in apertura prossimamente"),
                          (7, "aperto"), (8, "in apertura prossimamente")])
        self.assertEqual((contatori["refined_to_aperto"], contatori["refined_to_in_apertura"],
                          contatori["refined_to_chiuso"], contatori["refined_undetermined"]),
                         (3, 2, 4, 1))

    def test_dry_run_stessa_regola_nessuna_scrittura(self):
        bandi = [_bando(1, scadenza="2026-11-01"), _bando(2, scadenza="2026-09-30"),
                 _bando(3, scadenza="2026-09-30")]
        contatori, scrivi_stato, enrich, scrivi_enrich, chiamate_oggi = _esegui(
            bandi, {1: ("chiuso", 0.9, ""), 2: ("chiuso", 0.9, ""), 3: ("aperto", 0.9, "")},
            dry_run=True)
        self.assertEqual(scrivi_stato.await_count, 0)
        self.assertEqual(scrivi_enrich.await_count, 0)
        # 3: l'«aperto» del modello con la scadenza passata non va alla fase B
        # neanche in dry-run.
        self.assertEqual(_promossi(enrich), [(1, "aperto")])
        self.assertEqual(contatori["chiuso_modello_scartato"], 1)
        self.assertEqual(contatori["refined_to_aperto"], 1)
        self.assertEqual(contatori["refined_to_chiuso"], 2)
        # Un solo «oggi» per la fase A del lancio (in dry-run la fase B non
        # ricalcola lo stato, quindi non lo chiede).
        self.assertEqual(chiamate_oggi, 1)

    def test_senza_candidati_il_contatore_c_e(self):
        contatori, _st, _e, _se, _o = _esegui([], {})
        self.assertEqual(contatori["chiuso_modello_scartato"], 0)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
