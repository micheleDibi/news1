# -*- coding: utf-8 -*-
"""`salute` con i codici stabili (contratto `bandi-giro-2` §8, percorso B).

  - `CODICI_SALUTE` e' un elenco chiuso, con suffissi da liste chiuse;
  - ogni ramo di prima passa da `_voce` con lo stesso testo di prima;
  - i rami nuovi (produttore fermo, riavvii, servizio, passi degradati, fermi
    in lavorazione, ingresso guasto, accesso riservato, eventi, passi ripetuti,
    job orario) scattano ai loro confini e non prima;
  - le costanti copiate da altri moduli restano uguali agli originali.

Funzioni pure: nessuna rete, nessun DB.
"""
import re
import unittest
from datetime import datetime, timedelta, timezone

from tests.supporto import REPO, carica_modulo

telemetria = carica_modulo("telemetria")
Stato = telemetria.Stato

#: Giovedi' 01/10/2026 alle 12:30 di Roma (CEST, UTC+2).
ADESSO = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)
CODICI_PERCORSO_A = (
    # §8 A
    "verifica_stato_ferma", "leggibile_non_letto", "lettura_non_verificante",
    "estrattore_muto", "freno_chiusure", "prosa_non_riscritta",
    # §19.6
    "aperti_senza_conferma", "ingresso_trattenuti", "indicepa_non_aggiornato",
    "indicepa_import_anomalo", "vista_lenta",
)


def _iso(ore_fa: float) -> str:
    return (ADESSO - timedelta(hours=ore_fa)).isoformat()


def _riga(id_, giro, ore_fa, *, esito="ok", durata_h=0.1, contatori=None):
    """Una riga `step='pipeline'` come la restituisce `db.misure_salute`."""
    return {"id": id_, "giro": giro, "avviato_at": _iso(ore_fa),
            "concluso_at": _iso(ore_fa - durata_h), "esito": esito,
            "interrotto_per_tetto": False, "contatori": contatori or {}}


def _codici(stato, adesso=ADESSO):
    return [v.codice for v in telemetria.salute(stato, adesso=adesso).voci]


def _voce(stato, codice, adesso=ADESSO):
    voci = [v for v in telemetria.salute(stato, adesso=adesso).voci if v.codice == codice]
    return voci[0] if voci else None


class TestElencoChiuso(unittest.TestCase):
    def test_forma_dei_codici(self):
        for codice in telemetria.CODICI_SALUTE:
            with self.subTest(codice=codice):
                self.assertRegex(codice, r"^[a-z_]+(:[a-z0-9_]{1,32})?$")
                if ":" in codice:
                    prefisso, suffisso = codice.split(":")
                    self.assertIn(suffisso, telemetria.SUFFISSI_CODICE[prefisso])

    def test_niente_doppioni(self):
        self.assertEqual(len(set(telemetria.CODICI_SALUTE)), len(telemetria.CODICI_SALUTE))
        self.assertEqual(len(set(telemetria.PREFISSI_SALUTE)), len(telemetria.PREFISSI_SALUTE))

    def test_prefissi_coincidono_con_i_codici(self):
        self.assertEqual(
            set(telemetria.PREFISSI_SALUTE),
            {telemetria.prefisso_codice(c) for c in telemetria.CODICI_SALUTE})

    def test_codici_del_percorso_a(self):
        # Arrivati col #76 (§8 A e §19.6).
        for codice in CODICI_PERCORSO_A:
            self.assertIn(codice, telemetria.PREFISSI_SALUTE)
        self.assertIn("configurazione:verifica_stato", telemetria.CODICI_SALUTE)
        self.assertIn("estrattore_muto:lazioeuropa", telemetria.CODICI_SALUTE)
        self.assertNotIn("estrattore_muto:generico", telemetria.CODICI_SALUTE)

    def test_estrattori_come_etichette_stato(self):
        etichette = carica_modulo("etichette_stato")
        self.assertEqual(telemetria.ESTRATTORI_SALUTE,
                         tuple(k for k in etichette.ESTRATTORI if k != "generico"))
        self.assertEqual(telemetria.SUFFISSI_CODICE["estrattore_muto"], telemetria.ESTRATTORI_SALUTE)
        self.assertEqual(telemetria.SUFFISSI_CODICE["freno_chiusure"], telemetria.ESTRATTORI_SALUTE)

    def test_voce_fuori_elenco_rifiutata(self):
        voci = []
        with self.assertRaises(ValueError):
            telemetria._voce(voci, "codice_inventato", "allarme", "x")
        with self.assertRaises(ValueError):
            telemetria._voce(voci, "configurazione:inventata", "allarme", "x")
        with self.assertRaises(ValueError):
            telemetria._voce(voci, "estrattore_muto:generico", "allarme", "x")
        with self.assertRaises(ValueError):
            telemetria._voce(voci, "monitor_fermo", "grave", "x")
        self.assertEqual(voci, [])

    def test_lavorazione_del_lock(self):
        self.assertEqual(telemetria.lavorazione_del_lock("bandi_pipeline"), "giro")
        self.assertEqual(telemetria.lavorazione_del_lock("monitor"), "controllo_pagine")
        self.assertEqual(telemetria.lavorazione_del_lock("bandi_resolver"), "ricerca_fonti")
        self.assertEqual(telemetria.lavorazione_del_lock("qualunque"), "altro")


#: Uno stato per ogni codice che `salute` puo' produrre (riepilogo_non_valido
#: lo scrive solo `sorveglia`).
LOCK = telemetria.LockTenuto
STATI_PER_CODICE = {
    "monitor_fermo": Stato(ore_dall_ultimo_monitor_ok=25),
    "misure_non_disponibili": Stato(misure_db_errore="ConnectError"),
    "ingresso_fermo": Stato(bandi_scraped_fermi=4),
    "classificazione_non_disponibile": Stato(classificazioni_fallite_ultimo_monitor=3),
    "accesso_fonte_riservata": Stato(login_oe_ok=False),
    "limite_di_spesa": Stato(giri_consecutivi_a_tetto=2),
    "credito_ricerca_basso": Stato(crediti_residui_quota=0.1),
    "consumo_mensile_alto": Stato(consumo_mensile_quota=0.9),
    "fonti_da_verificare": Stato(quota_in_verifica_nuovi=0.4),
    "schede_senza_sezione": Stato(quota_schede_oe_con_sezione=0.5),
    "controlli_non_riusciti": Stato(quota_controlli_falliti=0.05),
    "scorta_piano_bassa": Stato(residuo_piano_su_tetto_mensile=2),
    "modello_fuori_listino": Stato(modelli_fuori_listino=("x",)),
    "non_misurato": Stato(non_misurati=("y",)),
    "configurazione:modalita": Stato(modalita_monitor="attivo", indexnow_configurata=False),
    "configurazione:indicizzazione": Stato(tipi_attivi=("faq",), indexnow_configurata=False),
    "configurazione:tipi_attivi": Stato(tipi_attivi_ignorati=("profroga",)),
    "configurazione:giri": Stato(monitor_giri_validi=False),
    "produttore_fermo": Stato(ultime_pipeline=(_riga(1, "06:00", 12),)),
    "riavvii_ripetuti": Stato(ultime_pipeline=(
        _riga(3, "boot", 1), _riga(2, "boot", 2), _riga(1, "boot", 3))),
    "servizio_non_attivo": Stato(servizio={"active_state": "failed", "sub_state": "failed"}),
    "passo_degradato:estrazione": Stato(ultime_pipeline=(
        _riga(1, "12:00", 0.4, contatori={"preprocess": {"errors": 24, "processed_total": 24}}),)),
    "passo_degradato:arricchimento": Stato(ultime_pipeline=(
        _riga(1, "12:00", 0.4, contatori={"enrich": {"enriched_total": 7}}),)),
    "passo_degradato:redazione": Stato(ultime_pipeline=(
        _riga(1, "12:00", 0.4, contatori={"seo": {"selected": 3, "payload_ok": 0}}),)),
    "fermi_in_lavorazione": Stato(fermi_in_lavorazione=2),
    "ingresso_guasto": Stato(ultime_pipeline=(
        _riga(1, "12:00", 0.4, contatori={"scrape": {"fonti_errors": 5, "fonti_processate": 0}}),)),
    "eventi_non_applicati": Stato(ultimi_monitor=(
        _riga(1, "06:00", 6, contatori={"eventi_non_applicati": 1}),)),
    "eventi_non_scritti": Stato(ultimi_monitor=(
        _riga(1, "06:00", 6, contatori={"eventi_non_scritti": 2}),)),
    "eventi_non_leggibili": Stato(ultimi_monitor=(
        _riga(1, "06:00", 6, contatori={"eventi_invisibili": 1}),)),
    "passi_ripetuti_non_ok": Stato(ultime_pipeline=(
        _riga(2, "12:00", 0.4, contatori={"passi_non_ok": ["seo"]}),
        _riga(1, "06:00", 6.4, contatori={"passi_non_ok": ["seo"]}))),
    "job_orario": Stato(job_orario={"misurato": True, "ultimo_ok_at": _iso(4), "falliti_24h": 0}),
    # percorso A
    "configurazione:verifica_stato": Stato(verifica_stato_config_valida=False),
    "verifica_stato_ferma": Stato(ultime_verifiche=(_riga(1, "06:00", 30),)),
    "leggibile_non_letto": Stato(letture_scadute=3),
    "lettura_non_verificante": Stato(ultime_verifiche=(
        _riga(1, "06:00", 1, contatori={"letture_non_verificanti": 2}),)),
    "prosa_non_riscritta": Stato(ultimi_monitor=(_riga(1, "06:00", 6, contatori={"prosa_non_riscritta": 1}),)),
    "aperti_senza_conferma": Stato(da_verificare={"aperto": {"senza_conferma": 70}}, aperti_senza_scadenza=100),
    "ingresso_trattenuti": Stato(ultimi_ingressi=(
        _riga(1, "06:00", 1, contatori={"trattenuti_senza_appiglio": 11}),)),
    "indicepa_non_aggiornato": Stato(ultimi_import_indicepa=()),
    "indicepa_import_anomalo": Stato(ultimi_import_indicepa=(
        _riga(1, "06:00", 1, contatori={"indicepa_esito": "anomalo", "indicepa_at": _iso(1)}),)),
    "vista_lenta": Stato(vista_ms=2500.0, vista_ms_ruolo="anon"),
}
for _chiave in telemetria.ESTRATTORI_SALUTE:
    STATI_PER_CODICE[f"estrattore_muto:{_chiave}"] = Stato(
        verifica_7g={_chiave: {"letture": 5, "esiti": 0}})
    STATI_PER_CODICE[f"freno_chiusure:{_chiave}"] = Stato(ultime_verifiche=(
        _riga(1, "06:00", 1, contatori={"trattenute_per_freno": {_chiave: 2}}),))
for _passo, _neutro in telemetria.PASSI_NEUTRI.items():
    STATI_PER_CODICE[f"copertura_incompleta:{_neutro}"] = Stato(ultime_pipeline=tuple(
        _riga(10 - _i, "06:00", 6 * _i + 1, contatori={_passo: {"copertura": {
            "candidati": 10, "fatti": 7, "rimasti": 3, "motivo_rimasti": "tempo"}}})
        for _i in range(4)))
for _variabile in telemetria.VARIABILI_GIRO_3:
    STATI_PER_CODICE[f"configurazione:{_variabile}"] = Stato(
        configurazione_scartate=(_variabile.upper(),))
for _suffisso in telemetria.SUFFISSI_LAVORAZIONE:
    _nome = {"giro": "bandi_pipeline", "controllo_pagine": "monitor",
             "ricerca_fonti": "bandi_resolver", "altro": "x"}[_suffisso]
    STATI_PER_CODICE[f"lavorazione_orfana:{_suffisso}"] = Stato(lock_tenuti=(LOCK(_nome, "p", 200),))
    STATI_PER_CODICE[f"lavorazione_lunga:{_suffisso}"] = Stato(lock_tenuti=(LOCK(_nome, "p", 90),))


class TestOgniCodiceHaUnRamo(unittest.TestCase):
    def test_ogni_stato_produce_il_suo_codice(self):
        for codice, stato in STATI_PER_CODICE.items():
            with self.subTest(codice=codice):
                self.assertIn(codice, _codici(stato))

    def test_nessun_codice_senza_ramo(self):
        # Un codice in elenco che nessun ramo produce e' un segnale morto.
        self.assertEqual(
            set(STATI_PER_CODICE),
            set(telemetria.CODICI_SALUTE) - {"riepilogo_non_valido"})


class TestTestiDiSempre(unittest.TestCase):
    """CLI, `--json` ed exit code non cambiano: `voci` si aggiunge e basta."""

    def test_allarmi_e_avvisi_sono_i_testi_delle_voci(self):
        stato = Stato(
            ore_dall_ultimo_monitor_ok=30, classificazioni_fallite_ultimo_monitor=1,
            classificazioni_riuscite_ultimo_monitor=9, lock_tenuti=(LOCK("monitor", "p", 70),),
            giri_consecutivi_a_tetto=2, motivo_ultimo_tetto="crediti",
            modelli_fuori_listino=("m",), non_misurati=("a", "b"))
        esito = telemetria.salute(stato, adesso=ADESSO)
        self.assertEqual(esito.allarmi, (
            "nessun monitor OK da 30 h",
            "tetto raggiunto in 2 giri consecutivi (l'ultimo: crediti)",
        ))
        self.assertEqual(esito.avvisi, (
            "classificazioni fallite nell'ultimo monitor: 1 su 10 "
            "(credito Anthropic esaurito o API giu')",
            "lock «monitor» tenuto da «p» da 70 min",
            "modello non a listino: m",
            "non misurato da salute: a, b",
        ))
        self.assertEqual(
            [v.codice for v in esito.voci],
            ["monitor_fermo", "classificazione_non_disponibile", "limite_di_spesa",
             "lavorazione_lunga:controllo_pagine", "modello_fuori_listino", "non_misurato"])
        self.assertEqual(esito.exit_code, 1)

    def test_testi_di_sempre_ramo_per_ramo(self):
        attesi = {
            "accesso_fonte_riservata": "login Obiettivo Europa fallito",
            "configurazione:modalita": "INDEXNOW_API_KEY assente con MONITOR_MODALITA=attivo",
            "configurazione:indicizzazione":
                "INDEXNOW_API_KEY assente con MONITOR_TIPI_ATTIVI valorizzata",
            "configurazione:giri": "MONITOR_GIRI contiene ore fuori dallo scheduler: voci "
                                   "ignorate, il monitor potrebbe non partire mai",
            "scorta_piano_bassa": "residuo del piano Firecrawl < 3x il tetto mensile: "
                                  "valutare MONITOR_SCENARIO=economico",
            "credito_ricerca_basso": "crediti residui 10% (< 15%)",
            "consumo_mensile_alto": "consumo mensile 90% (>= 80%)",
            "fonti_da_verificare": "fonti in verifica sui nuovi 40% (> 30%)",
            "controlli_non_riusciti": "controlli falliti >= 5 sul 5% dei vivi (> 2%)",
            "lavorazione_orfana:giro": "lock «bandi_pipeline» tenuto da «p» da 200 min: "
                                       "probabilmente orfano (lock_rilascia se nessun processo gira)",
        }
        for codice, testo in attesi.items():
            with self.subTest(codice=codice):
                self.assertEqual(_voce(STATI_PER_CODICE[codice], codice).testo_cli, testo)

    def test_come_dizionario_aggiunge_solo_voci(self):
        diz = telemetria.salute(Stato(ore_dall_ultimo_monitor_ok=25), adesso=ADESSO).come_dizionario()
        self.assertEqual(set(diz), {"allarmi", "avvisi", "exit_code", "tipi_attivi", "voci",
                                    "copertura", "informazioni"})
        self.assertEqual((diz["copertura"], diz["informazioni"]), ({}, []))
        self.assertEqual(diz["voci"], [{"codice": "monitor_fermo", "livello": "allarme",
                                        "testo_cli": "nessun monitor OK da 25 h", "misura": 25}])

    def test_stato_vuoto_nessuna_voce(self):
        # Una fotografia di prima del giro 2 non produce voci nuove (test_tipi_attivi).
        self.assertEqual(telemetria.salute(Stato()).voci, ())
        self.assertEqual(telemetria.salute(Stato(), adesso=ADESSO).voci, ())

    def test_segnali_di_spesa_senza_misura(self):
        for codice in ("limite_di_spesa", "credito_ricerca_basso", "consumo_mensile_alto",
                       "scorta_piano_bassa"):
            with self.subTest(codice=codice):
                self.assertIsNone(_voce(STATI_PER_CODICE[codice], codice).misura)

    def test_le_quote_restano_fra_zero_e_uno(self):
        for codice in ("fonti_da_verificare", "schede_senza_sezione", "controlli_non_riusciti"):
            misura = _voce(STATI_PER_CODICE[codice], codice).misura
            self.assertTrue(0 <= misura <= 1, (codice, misura))

    def test_login_e_righe_non_si_ripetono(self):
        righe = tuple(_riga(i, "12:00", 6 * i, contatori={"scrape": {"fonti_in_errore": [449]}})
                      for i in (1, 2))
        codici = _codici(Stato(login_oe_ok=False, ultime_pipeline=righe))
        self.assertEqual(codici.count("accesso_fonte_riservata"), 1)


class TestProduttoreFermo(unittest.TestCase):
    def _stato(self, ore_fa, *, lock=None, giro="06:00", esito="ok"):
        return Stato(ultime_pipeline=(_riga(1, giro, ore_fa, esito=esito),), lock=lock)

    def _lock(self, preso_ore_fa, scade_fra_ore, proprietario="bandi_pipeline@4242"):
        return ({"nome": "bandi_pipeline", "proprietario": proprietario,
                 "acquisito_at": _iso(preso_ore_fa), "scade_at": _iso(-scade_fra_ore)},)

    def test_sotto_le_sette_ore(self):
        self.assertNotIn("produttore_fermo", _codici(self._stato(6.5)))

    def test_oltre_le_sette_ore(self):
        voce = _voce(self._stato(8), "produttore_fermo")
        self.assertEqual(voce.livello, "allarme")
        self.assertEqual(voce.misura, 7.9)

    def test_giro_in_corso_partito_dopo_l_ultima_ora(self):
        # Alle 12:30 di Roma il giro delle 12 tiene il lock dalle 12:00.
        self.assertNotIn("produttore_fermo", _codici(self._stato(8, lock=self._lock(0.5, 3.5))))

    def test_il_lock_di_seo_rigenera_non_e_un_giro(self):
        # P2 della revisione #61: stesso nome, ma non e' il giro in corso.
        lock = self._lock(0.5, 3.5, proprietario="seo-rigenera:cli")
        self.assertIn("produttore_fermo", _codici(self._stato(8, lock=lock)))

    def test_lock_preso_prima_dell_ultima_ora_non_salva(self):
        self.assertIn("produttore_fermo", _codici(self._stato(8, lock=self._lock(1, 3))))

    def test_lock_scaduto_non_salva(self):
        self.assertIn("produttore_fermo", _codici(self._stato(8, lock=self._lock(0.4, -0.1))))

    def test_da_tredici_ore_comunque(self):
        # 7 + ORE_TTL_LOCK_GIRO (6 dal giro 3): un giro vero non tiene il lock oltre.
        self.assertIn("produttore_fermo", _codici(self._stato(13.2, lock=self._lock(0.5, 3.5))))
        self.assertNotIn("produttore_fermo", _codici(self._stato(12.5, lock=self._lock(0.5, 3.5))))

    def test_giri_saltati_e_di_avvio_non_contano(self):
        righe = (_riga(3, "12:00", 0.4, esito="saltato"), _riga(2, "boot", 2),
                 _riga(1, "06:00", 9))
        self.assertIn("produttore_fermo", _codici(Stato(ultime_pipeline=righe)))

    def test_senza_giri_conclusi_conta_dalla_riga_piu_vecchia(self):
        righe = (_riga(2, "boot", 1), _riga(1, "boot", 8))
        self.assertIn("produttore_fermo", _codici(Stato(ultime_pipeline=righe)))

    def test_ora_di_schedulazione_in_ora_di_roma(self):
        ultima = telemetria._ultima_ora_di_schedulazione
        # 06:30 di Roma d'estate (UTC+2): l'ultima e' le 06:00 = 04:00Z.
        self.assertEqual(ultima(datetime(2026, 10, 1, 4, 30, tzinfo=timezone.utc)),
                         datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc))
        # 05:30 di Roma: l'ultima e' la mezzanotte, cioe' le 22:00Z del giorno prima.
        self.assertEqual(ultima(datetime(2026, 10, 1, 3, 30, tzinfo=timezone.utc)),
                         datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc))
        # D'inverno (UTC+1) le 06:00 di Roma sono le 05:00Z.
        self.assertEqual(ultima(datetime(2026, 11, 2, 5, 30, tzinfo=timezone.utc)),
                         datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc))


class TestRiavvii(unittest.TestCase):
    def test_tre_avvii_in_sei_ore(self):
        righe = (_riga(3, "boot", 0.5, esito="saltato",
                       contatori={"riavvio_dopo_crash": 1}),
                 _riga(2, "boot", 2), _riga(1, "boot", 5.5))
        voce = _voce(Stato(ultime_pipeline=righe), "riavvii_ripetuti")
        self.assertEqual((voce.livello, voce.misura), ("allarme", 3))

    def test_due_avvii_o_uno_fuori_finestra(self):
        self.assertNotIn("riavvii_ripetuti", _codici(Stato(ultime_pipeline=(
            _riga(2, "boot", 1), _riga(1, "boot", 2)))))
        self.assertNotIn("riavvii_ripetuti", _codici(Stato(ultime_pipeline=(
            _riga(3, "boot", 1), _riga(2, "boot", 2), _riga(1, "boot", 6.5)))))

    def test_solo_le_righe_del_giro(self):
        righe = (_riga(3, "boot", 1), _riga(2, "boot", 2),
                 dict(_riga(1, "boot", 3), step="resolver"))
        self.assertNotIn("riavvii_ripetuti", _codici(Stato(ultime_pipeline=righe)))

    def test_nrestarts_salito_di_due(self):
        memoria = {"nrestarts": [[_iso(5), 1], [_iso(2), 2]]}
        stato = Stato(memoria=memoria, servizio={"active_state": "active", "n_restarts": 3})
        voce = _voce(stato, "riavvii_ripetuti")
        self.assertEqual(voce.misura, 2)

    def test_nrestarts_azzerato_o_vecchio_non_conta(self):
        # Un restart a mano azzera NRestarts: il calo non e' un riavvio.
        memoria = {"nrestarts": [[_iso(8), 0], [_iso(5), 5], [_iso(2), 0]]}
        stato = Stato(memoria=memoria, servizio={"active_state": "active", "n_restarts": 1})
        self.assertNotIn("riavvii_ripetuti", _codici(stato))

    def test_memoria_illeggibile_non_rompe(self):
        for memoria in ({"nrestarts": "x"}, {"nrestarts": [["x", 1], [1, 2, 3]]}, {}):
            stato = Stato(memoria=memoria, servizio={"active_state": "active", "n_restarts": 9})
            self.assertNotIn("riavvii_ripetuti", _codici(stato))


class TestServizio(unittest.TestCase):
    def test_stati_fermi(self):
        for attivo, sotto in (("failed", "failed"), ("inactive", "dead"),
                              ("activating", "auto-restart")):
            with self.subTest(attivo=attivo):
                self.assertIn("servizio_non_attivo", _codici(
                    Stato(servizio={"active_state": attivo, "sub_state": sotto})))

    def test_stati_attivi(self):
        for attivo, sotto in (("active", "running"), ("activating", "start")):
            self.assertNotIn("servizio_non_attivo", _codici(
                Stato(servizio={"active_state": attivo, "sub_state": sotto})))


class TestPassoDegradato(unittest.TestCase):
    def _codici(self, contatori, *, prima=None, modalita="ombra", gemelli="ombra"):
        righe = [_riga(2, "12:00", 0.4, contatori=contatori)]
        if prima is not None:
            righe.insert(0, _riga(3, "18:00", 0.1, esito="saltato"))
        return _codici(Stato(ultime_pipeline=tuple(righe), verifica_stato_modalita=modalita,
                             gemelli_modalita=gemelli))

    def test_estrazione_col_credito_esaurito_del_28_09(self):
        # Righe 107..119: errors = processed_total ed esito ok.
        self.assertIn("passo_degradato:estrazione",
                      self._codici({"preprocess": {"errors": 25, "processed_total": 25}}))
        self.assertNotIn("passo_degradato:estrazione",
                         self._codici({"preprocess": {"errors": 3, "processed_total": 25}}))
        self.assertNotIn("passo_degradato:estrazione",
                         self._codici({"preprocess": {"errors": 0, "processed_total": 0}}))

    def test_una_riga_saltata_non_nasconde_l_ultimo_giro(self):
        self.assertIn("passo_degradato:estrazione", self._codici(
            {"preprocess": {"errors": 4, "processed_total": 4}}, prima=True))

    def test_arricchimento(self):
        self.assertIn("passo_degradato:arricchimento",
                      self._codici({"enrich": {"enriched_total": 7}}))
        self.assertIn("passo_degradato:arricchimento",
                      self._codici({"enrich": {"enriched_total": 7, "enriched_db_ok": 0}}))
        self.assertNotIn("passo_degradato:arricchimento",
                         self._codici({"enrich": {"enriched_total": 7, "enriched_db_ok": 7}}))
        self.assertNotIn("passo_degradato:arricchimento",
                         self._codici({"enrich": {"enriched_total": 0}}))

    def test_redazione_solo_da_tre_bandi(self):
        # Il 772894 bloccato (selected=1, payload_ok=0 in 17 giri su 19) non basta.
        self.assertNotIn("passo_degradato:redazione",
                         self._codici({"seo": {"selected": 1, "payload_ok": 0}}))
        self.assertIn("passo_degradato:redazione",
                      self._codici({"seo": {"selected": 3, "payload_ok": 0}}))
        self.assertNotIn("passo_degradato:redazione",
                         self._codici({"seo": {"selected": 4, "doppioni_oe": 2, "payload_ok": 0}}))
        self.assertNotIn("passo_degradato:redazione",
                         self._codici({"seo": {"selected": 5, "payload_ok": 1}}))

    def test_redazione_senza_trattenuti_solo_con_la_verifica_attiva(self):
        # Con la verifica attiva la sosta non e' un passo guasto; in ombra
        # quelle righe si redigono lo stesso, quindi contano. I gemelli non
        # c'entrano.
        for chiave in ("trattenuti", "trattenuti_senza_appiglio"):
            for gemelli in ("ombra", "attivo"):
                with self.subTest(chiave=chiave, gemelli=gemelli):
                    seo = {"seo": {"selected": 4, chiave: 2, "payload_ok": 0}}
                    self.assertNotIn("passo_degradato:redazione",
                                     self._codici(seo, modalita="attivo", gemelli=gemelli))
                    self.assertIn("passo_degradato:redazione",
                                  self._codici(seo, modalita="ombra", gemelli=gemelli))

    def test_redazione_senza_fusi_solo_con_i_gemelli_attivi(self):
        # §18.8: dal giro 3 la fusione prima della pubblicazione segue
        # GEMELLI_MODALITA, non la verifica. Con i gemelli attivi e la verifica
        # in ombra le fuse non sono un guasto (era il falso allarme).
        for chiave in ("fusi_prima_della_pubblicazione", "fusioni_non_riuscite"):
            for verifica in ("ombra", "attivo"):
                with self.subTest(chiave=chiave, verifica=verifica):
                    seo = {"seo": {"selected": 4, chiave: 2, "payload_ok": 0}}
                    self.assertNotIn("passo_degradato:redazione",
                                     self._codici(seo, modalita=verifica, gemelli="attivo"))
                    self.assertIn("passo_degradato:redazione",
                                  self._codici(seo, modalita=verifica, gemelli="ombra"))

    def test_le_chiavi_tolte_seguono_ciascuna_il_proprio_interruttore(self):
        chiavi = telemetria.contatori_seo_non_da_redigere
        self.assertEqual(chiavi(Stato()), ("doppioni_oe",))
        self.assertEqual(chiavi(Stato(verifica_stato_modalita="attivo")),
                         ("doppioni_oe", "trattenuti", "trattenuti_senza_appiglio"))
        self.assertEqual(chiavi(Stato(gemelli_modalita="attivo")),
                         ("doppioni_oe", "fusi_prima_della_pubblicazione", "fusioni_non_riuscite"))
        self.assertEqual(set(chiavi(Stato(verifica_stato_modalita="attivo", gemelli_modalita="attivo"))),
                         set(telemetria.CONTATORI_SEO_NON_DA_REDIGERE))
        self.assertIn("passo_degradato:redazione",
                      self._codici({"seo": {"selected": 6, "trattenuti": 2, "doppioni_oe": 1,
                                            "payload_ok": 0}}, modalita="attivo"))
        # I doppioni OE si tolgono sempre.
        self.assertNotIn("passo_degradato:redazione",
                         self._codici({"seo": {"selected": 4, "doppioni_oe": 2, "payload_ok": 0}}))


class TestIngresso(unittest.TestCase):
    def _codici(self, scrape):
        return _codici(Stato(ultime_pipeline=(_riga(1, "12:00", 0.4, contatori={"scrape": scrape}),)))

    def test_ingresso_guasto_solo_se_nessuna_fonte_riesce(self):
        self.assertIn("ingresso_guasto", self._codici({"fonti_errors": 5, "fonti_processate": 0}))
        self.assertNotIn("ingresso_guasto", self._codici({"fonti_errors": 1, "fonti_processate": 70}))
        self.assertNotIn("ingresso_guasto", self._codici({"fonti_errors": 0, "fonti_processate": 0}))
        self.assertNotIn("ingresso_guasto", self._codici({"fonti_errors": 5}))

    def test_fermi_in_lavorazione_e_un_avviso(self):
        voce = _voce(Stato(fermi_in_lavorazione=2), "fermi_in_lavorazione")
        self.assertEqual((voce.livello, voce.misura), ("avviso", 2))
        self.assertEqual(_codici(Stato(fermi_in_lavorazione=0)), [])


class TestAccessoRiservato(unittest.TestCase):
    def _righe(self, *liste):
        return tuple(
            _riga(10 - i, "12:00", 0.4 + 6 * i,
                  contatori={} if valori is None else {"scrape": {"fonti_in_errore": valori}})
            for i, valori in enumerate(liste))

    def test_fonte_oe_in_errore_due_giri_di_fila(self):
        voce = _voce(Stato(ultime_pipeline=self._righe([449, 12], [450])),
                     "accesso_fonte_riservata")
        self.assertEqual(voce.livello, "allarme")

    def test_un_solo_giro_non_basta(self):
        for liste in (([449], []), ([], [449]), ([12], [13])):
            self.assertNotIn("accesso_fonte_riservata",
                             _codici(Stato(ultime_pipeline=self._righe(*liste))))

    def test_senza_la_chiave_non_si_misura(self):
        righe = self._righe([449], None)
        self.assertNotIn("accesso_fonte_riservata", _codici(Stato(ultime_pipeline=righe)))
        self.assertFalse(telemetria.accesso_riservato_misurato(righe))
        self.assertTrue(telemetria.accesso_riservato_misurato(self._righe([], [])))


class TestEventiEPassi(unittest.TestCase):
    def test_eventi_dell_ultimo_monitor(self):
        monitor = (_riga(2, "18:00", 1, contatori={"eventi_non_applicati": 0}),
                   _riga(1, "06:00", 13, contatori={"eventi_non_applicati": 4}))
        self.assertEqual(_codici(Stato(ultimi_monitor=monitor)), [])
        voce = _voce(Stato(ultimi_monitor=monitor[1:]), "eventi_non_applicati")
        self.assertEqual(voce.misura, 4)

    def test_eventi_assenti_valgono_zero(self):
        self.assertEqual(_codici(Stato(ultimi_monitor=(_riga(1, "06:00", 6),))), [])

    def test_eventi_non_scritti_del_monitor_e_del_passo(self):
        monitor = (_riga(1, "06:00", 6, contatori={"eventi_non_scritti": 2}),)
        verifica = (_riga(3, "06:00", 5, contatori={"fase": "controlli", "eventi_non_scritti": 3}),)
        solo_monitor = _voce(Stato(ultimi_monitor=monitor), "eventi_non_scritti")
        self.assertEqual((solo_monitor.misura, solo_monitor.testo_cli),
                         (2, "eventi non scritti nell'ultimo monitor: 2"))
        self.assertEqual(_voce(Stato(ultime_verifiche=verifica), "eventi_non_scritti").misura, 3)
        entrambi = _voce(Stato(ultimi_monitor=monitor, ultime_verifiche=verifica), "eventi_non_scritti")
        self.assertEqual(entrambi.misura, 5)
        self.assertIn("verifica dello stato: 3", entrambi.testo_cli)

    def test_eventi_del_passo_solo_dall_ultima_riga_dei_controlli(self):
        # La riga d'ingresso non scrive eventi; una riga saltata non conta.
        ingresso = _riga(4, "12:00", 1, contatori={"fase": "ingresso", "eventi_non_scritti": 9})
        saltata = _riga(3, "06:00", 2, esito="saltato", contatori={"eventi_non_scritti": 9})
        pulita = _riga(2, "06:00", 3, contatori={"fase": "controlli", "eventi_non_scritti": 0})
        vecchia = _riga(1, "18:00", 15, contatori={"fase": "controlli", "eventi_non_scritti": 4})
        self.assertNotIn("eventi_non_scritti",
                         _codici(Stato(ultime_verifiche=(ingresso, saltata, pulita, vecchia))))

    def test_eventi_non_leggibili_avviso_dal_monitor_e_dal_passo(self):
        monitor = (_riga(1, "06:00", 6, contatori={"eventi_invisibili": 1}),)
        verifica = (_riga(2, "06:00", 5, contatori={"fase": "controlli", "eventi_non_leggibili": 2}),)
        voce = _voce(Stato(ultimi_monitor=monitor, ultime_verifiche=verifica), "eventi_non_leggibili")
        self.assertEqual((voce.livello, voce.misura), ("avviso", 3))
        self.assertNotIn("eventi_non_leggibili", _codici(Stato(ultimi_monitor=(
            _riga(1, "06:00", 6, contatori={"eventi_invisibili": 0}),))))

    def test_da_riprovare_non_accende_niente(self):
        riga = _riga(1, "06:00", 1, contatori={"fase": "controlli", "da_riprovare": 7})
        self.assertEqual(_codici(Stato(ultime_verifiche=(riga,))), [])

    def test_passi_ripetuti(self):
        righe = (_riga(3, "18:00", 0.2, contatori={"passi_non_ok": ["monitor", "seo"]}),
                 _riga(2, "12:00", 3, esito="saltato"),
                 _riga(1, "12:00", 6, contatori={"passi_non_ok": ["seo"]}))
        voce = _voce(Stato(ultime_pipeline=righe), "passi_ripetuti_non_ok")
        self.assertEqual(voce.misura, 1)
        self.assertIn("seo", voce.testo_cli)

    def test_passi_diversi_o_chiave_assente(self):
        diversi = (_riga(2, "18:00", 0.2, contatori={"passi_non_ok": ["seo"]}),
                   _riga(1, "12:00", 6, contatori={"passi_non_ok": ["monitor"]}))
        vecchia = (_riga(2, "18:00", 0.2, contatori={"passi_non_ok": ["seo"]}),
                   _riga(1, "12:00", 6))
        for righe in (diversi, vecchia):
            self.assertNotIn("passi_ripetuti_non_ok", _codici(Stato(ultime_pipeline=righe)))


class TestJobOrario(unittest.TestCase):
    def _codici(self, **job):
        return _codici(Stato(job_orario={"misurato": True, **job}))

    def test_nessun_esito_riuscito_da_tre_ore(self):
        self.assertIn("job_orario", self._codici(ultimo_ok_at=_iso(3.5), falliti_24h=0))
        self.assertNotIn("job_orario", self._codici(ultimo_ok_at=_iso(1.5), falliti_24h=1))
        self.assertIn("job_orario", self._codici(ultimo_ok_at=None, falliti_24h=0))

    def test_due_fallimenti_in_ventiquattro_ore(self):
        self.assertIn("job_orario", self._codici(ultimo_ok_at=_iso(0.5), falliti_24h=2))

    def test_non_misurato_nessuna_voce(self):
        self.assertEqual(_codici(Stato(job_orario={"misurato": False})), [])


class TestStatoDaMisure(unittest.TestCase):
    BASE = {"monitor": [], "pipeline": [], "mese": [], "nuovi": [], "vivi": [],
            "falliti": [], "lock": []}

    def _campi(self, **misure):
        return telemetria.stato_da_misure({**self.BASE, **misure}, adesso=ADESSO)

    def test_senza_le_chiavi_nuove_si_dice_cosa_manca(self):
        campi = self._campi()
        for voce in ("giri del produttore", "eventi dell'ultimo monitor",
                     "bandi fermi in lavorazione", telemetria.NON_MISURATO_SERVIZIO,
                     telemetria.NON_MISURATO_JOB_ORARIO, "login Obiettivo Europa"):
            self.assertIn(voce, campi["non_misurati"])
        esito = telemetria.salute(Stato(**campi), adesso=ADESSO)
        self.assertEqual(esito.allarmi, ())

    def test_chiavi_nuove_passano_a_stato(self):
        righe = [_riga(2, "12:00", 0.4, contatori={"scrape": {"fonti_in_errore": []}}),
                 _riga(1, "06:00", 6.4, contatori={"scrape": {"fonti_in_errore": []}})]
        campi = self._campi(
            ultime_pipeline=righe, ultimi_monitor=[], fermi_in_lavorazione=3,
            ultimo_bando_nuovo_at="2026-10-01T09:00:00+00:00",
            servizio={"active_state": "active", "sub_state": "running", "n_restarts": 0},
            job_orario={"misurato": True, "ultimo_ok_at": _iso(0.5), "falliti_24h": 0},
            memoria={"nrestarts": []},
            lock=[{"nome": "monitor", "acquisito_at": _iso(0.1), "scade_at": _iso(-2)}])
        self.assertEqual(len(campi["ultime_pipeline"]), 2)
        self.assertEqual(campi["fermi_in_lavorazione"], 3)
        self.assertEqual(campi["servizio"]["active_state"], "active")
        self.assertEqual(campi["lock"][0]["nome"], "monitor")
        # Il login si misura dalle righe: non e' piu' fra i non misurati.
        for voce in ("login Obiettivo Europa", telemetria.NON_MISURATO_SERVIZIO,
                     telemetria.NON_MISURATO_JOB_ORARIO, "giri del produttore"):
            self.assertNotIn(voce, campi["non_misurati"])
        esito = telemetria.salute(Stato(**campi), adesso=ADESSO)
        self.assertEqual(esito.allarmi, ())
        self.assertEqual([v.codice for v in esito.voci],
                         ["fermi_in_lavorazione", "non_misurato"])

    def test_giri_letti_ma_nessuno_registrato(self):
        self.assertIn("giri del produttore (nessun giro registrato)",
                      self._campi(ultime_pipeline=[])["non_misurati"])

    def test_job_non_misurato_e_servizio_senza_stato(self):
        campi = self._campi(job_orario={"misurato": False}, servizio={"n_restarts": 1})
        self.assertIn(telemetria.NON_MISURATO_JOB_ORARIO, campi["non_misurati"])
        self.assertIn(telemetria.NON_MISURATO_SERVIZIO, campi["non_misurati"])
        self.assertNotIn("job_orario", campi)


class TestCostantiAllineate(unittest.TestCase):
    """Le costanti copiate qui per non importare moduli pesanti restano uguali."""

    def test_ore_dello_scheduler(self):
        settings = carica_modulo("settings")
        self.assertEqual(telemetria.GIRI_DI_REGIME, settings.GIRI_SCHEDULER)

    def test_fonti_ad_accesso_riservato(self):
        self.assertEqual(telemetria.FONTI_ACCESSO_RISERVATO,
                         frozenset(carica_modulo("fonte_ufficiale").FONTI_OE))
        self.assertEqual(telemetria.FONTI_ACCESSO_RISERVATO, carica_modulo("gemelli").FONTI_OE)

    def test_lock_del_giro_e_suo_ttl(self):
        testo = (REPO / "backend" / "app" / "bandi_pipeline.py").read_text(encoding="utf-8")
        self.assertIn(f'LOCK_PIPELINE = "{telemetria.LOCK_GIRO}"', testo)
        self.assertRegex(testo, rf"\nLOCK_TTL_S = {telemetria.ORE_TTL_LOCK_GIRO} \* 3600\n")
        self.assertEqual(telemetria.ORE_PRODUTTORE_FERMO_COMUNQUE, 13)

    def test_giro_di_avvio(self):
        testo = (REPO / "backend" / "app" / "bandi_sender.py").read_text(encoding="utf-8")
        self.assertIn(f'GIRO_BOOT = "{telemetria.GIRO_AVVIO}"', testo)

    def test_lock_noti(self):
        self.assertEqual(carica_modulo("monitoraggio").NOME_LOCK, "monitor")
        self.assertEqual(carica_modulo("fonte_ufficiale").LOCK_RESOLVER, "bandi_resolver")
        self.assertTrue(re.fullmatch(r"[a-z_]+", "".join(telemetria.LAVORAZIONI_PER_LOCK.values())))


class TestCodiciPercorsoA(unittest.TestCase):
    """Un test per ogni codice nuovo del percorso A (§8 A e §19.6)."""

    def test_verifica_stato_ferma(self):
        # Un passo riuscito 20 ore fa: niente; 30 ore fa: allarme.
        self.assertNotIn("verifica_stato_ferma", _codici(Stato(ultime_verifiche=(_riga(1, "06:00", 20),))))
        voce = _voce(Stato(ultime_verifiche=(_riga(1, "06:00", 30),)), "verifica_stato_ferma")
        self.assertEqual((voce.livello, round(voce.misura)), ("allarme", 30))
        # Nessuna riga del passo (subito dopo un deploy): avviso, non allarme (revisione #108).
        voce = _voce(Stato(ultime_verifiche=()), "verifica_stato_ferma")
        self.assertEqual((voce.livello, voce.misura, voce.testo_cli),
                         ("avviso", None, "verifica dello stato non ancora eseguita"))
        # Righe presenti ma nessuna riuscita: allarme senza misura.
        fallita = _riga(1, "06:00", 2, esito="errore")
        voce = _voce(Stato(ultime_verifiche=(fallita,)), "verifica_stato_ferma")
        self.assertEqual((voce.livello, voce.misura), ("allarme", None))
        # Saltato perche' la 13 non c'e': non si misura, niente allarme.
        saltato = _riga(1, "06:00", 30, esito="saltato", contatori={"motivo_saltato": "migrazione_assente"})
        self.assertNotIn("verifica_stato_ferma", _codici(Stato(ultime_verifiche=(saltato,))))
        # La fase ingresso non conta come passo dei controlli.
        ingresso = _riga(2, "12:00", 1, contatori={"fase": "ingresso"})
        self.assertIn("verifica_stato_ferma", _codici(Stato(ultime_verifiche=(ingresso, _riga(1, "06:00", 30)))))
        # Un giro fermato dal tetto di tempo e' vivo: niente allarme (revisione #96).
        interrotto = _riga(2, "06:00", 2, esito="interrotto_per_tetto")
        self.assertNotIn("verifica_stato_ferma",
                         _codici(Stato(ultime_verifiche=(interrotto, _riga(1, "06:00", 30)))))
        # Senza misura: niente.
        self.assertEqual(_codici(Stato()), [])

    def test_leggibile_non_letto_e_lettura_non_verificante(self):
        self.assertEqual(_voce(Stato(letture_scadute=3), "leggibile_non_letto").livello, "avviso")
        self.assertEqual(_codici(Stato(letture_scadute=0)), [])
        riga = _riga(1, "06:00", 1, contatori={"letture_non_verificanti": 2})
        self.assertEqual(_voce(Stato(ultime_verifiche=(riga,)), "lettura_non_verificante").misura, 2)

    def test_estrattore_muto(self):
        self.assertIn("estrattore_muto:lombardia",
                      _codici(Stato(verifica_7g={"lombardia": {"letture": 5, "esiti": 0}})))
        for valori in ({"letture": 4, "esiti": 0}, {"letture": 9, "esiti": 1}):
            self.assertEqual(_codici(Stato(verifica_7g={"lombardia": valori})), [])
        # Il generico e le chiavi sconosciute non accendono niente.
        self.assertEqual(_codici(Stato(verifica_7g={"generico": {"letture": 50, "esiti": 0},
                                                    "sconosciuto": {"letture": 50, "esiti": 0}})), [])

    def test_freno_chiusure(self):
        riga = _riga(1, "06:00", 1, contatori={"trattenute_per_freno": {"lazioeuropa": 3, "toscana": 0}})
        self.assertEqual([v.codice for v in telemetria.salute(Stato(ultime_verifiche=(riga,)), adesso=ADESSO).voci],
                         ["freno_chiusure:lazioeuropa"])

    def test_prosa_non_riscritta_da_monitor_o_verifica(self):
        verifica = _riga(1, "06:00", 1, contatori={"prosa_non_riscritta": 2})
        monitor = _riga(1, "06:00", 6, contatori={"prosa_non_riscritta": 1})
        self.assertEqual(_voce(Stato(ultime_verifiche=(verifica,), ultimi_monitor=(monitor,)),
                               "prosa_non_riscritta").misura, 3)

    def test_aperti_senza_conferma(self):
        self.assertIn("aperti_senza_conferma", _codici(Stato(
            da_verificare={"aperto": {"senza_conferma": 61}}, aperti_senza_scadenza=100)))
        self.assertNotIn("aperti_senza_conferma", _codici(Stato(
            da_verificare={"aperto": {"senza_conferma": 60}}, aperti_senza_scadenza=100)))
        self.assertEqual(_codici(Stato(da_verificare={"aperto": {}}, aperti_senza_scadenza=0)), [])

    def test_ingresso_trattenuti(self):
        self.assertNotIn("ingresso_trattenuti", _codici(Stato(ultimi_ingressi=(
            _riga(1, "06:00", 1, contatori={"trattenuti_senza_appiglio": 10}),))))
        # Soglia assoluta sui rilasciati a tempo nei 7 giorni (> 10), non il rapporto.
        pochi = (_riga(2, "12:00", 1, contatori={"trattenuti": 4, "rilasciati_a_tempo": 3}),
                 _riga(1, "06:00", 7, contatori={"trattenuti": 2, "rilasciati_a_tempo": 1}))
        self.assertNotIn("ingresso_trattenuti", _codici(Stato(ultimi_ingressi=pochi)))
        molti = (_riga(2, "12:00", 1, contatori={"trattenuti": 40, "rilasciati_a_tempo": 6}),
                 _riga(1, "06:00", 7, contatori={"trattenuti": 40, "rilasciati_a_tempo": 5}))
        voce = _voce(Stato(ultimi_ingressi=molti), "ingresso_trattenuti")
        self.assertEqual((voce.livello, voce.misura), ("avviso", 11))
        dieci = (_riga(1, "06:00", 1, contatori={"rilasciati_a_tempo": 10}),)
        self.assertNotIn("ingresso_trattenuti", _codici(Stato(ultimi_ingressi=dieci)))

    def test_indicepa_non_aggiornato_ombra_e_attivo(self):
        ombra = (_riga(1, "06:00", 24, contatori={"indicepa_esito": "ombra", "indicepa_at": _iso(24)}),)
        self.assertNotIn("indicepa_non_aggiornato", _codici(Stato(ultimi_import_indicepa=ombra)))
        # Con i domini attivi un import in ombra non conta (§18.8: la scrittura
        # segue DOMINI_MODALITA, non la verifica).
        self.assertIn("indicepa_non_aggiornato", _codici(Stato(ultimi_import_indicepa=ombra,
                                                               domini_modalita="attivo")))
        # La verifica attiva da sola non lo rende un allarme (era il falso allarme).
        self.assertNotIn("indicepa_non_aggiornato", _codici(Stato(ultimi_import_indicepa=ombra,
                                                                  verifica_stato_modalita="attivo")))
        vecchio = (_riga(1, "06:00", 41 * 24, contatori={"indicepa_esito": "ok", "indicepa_at": _iso(41 * 24)}),)
        self.assertIn("indicepa_non_aggiornato", _codici(Stato(ultimi_import_indicepa=vecchio)))
        self.assertEqual(_codici(Stato(ultimi_import_indicepa=None)), [])

    def test_indicepa_import_anomalo(self):
        def import_(**contatori):
            base = {"indicepa_esito": "ok", "indicepa_at": _iso(1), "indicepa_righe_lette": 20000,
                    "indicepa_righe_utili": 19000, "indicepa_esclusi": {"condiviso": 1000}}
            base.update(contatori)
            return Stato(ultimi_import_indicepa=(_riga(1, "06:00", 1, contatori=base),))
        self.assertEqual(_codici(import_()), [])
        self.assertIn("indicepa_import_anomalo", _codici(import_(indicepa_righe_utili=14999)))
        self.assertIn("indicepa_import_anomalo", _codici(import_(indicepa_esclusi={"condiviso": 4001})))
        self.assertIn("indicepa_import_anomalo", _codici(import_(indicepa_esito="anomalo")))

    def test_vista_lenta_allarme_solo_come_anon(self):
        self.assertEqual(_voce(Stato(vista_ms=2500.0, vista_ms_ruolo="anon"), "vista_lenta").livello, "allarme")
        self.assertEqual(_voce(Stato(vista_ms=2500.0, vista_ms_ruolo="servizio"), "vista_lenta").livello, "avviso")
        self.assertEqual(_codici(Stato(vista_ms=2000.0, vista_ms_ruolo="anon")), [])

    def test_configurazione_verifica_stato(self):
        self.assertEqual(_voce(Stato(verifica_stato_config_valida=False), "configurazione:verifica_stato").livello,
                         "allarme")


class TestIstante(unittest.TestCase):
    def test_frazioni_e_zulu(self):
        # P2 della revisione #61: PostgREST manda frazioni con meno di 6 cifre.
        atteso = datetime(2026, 10, 1, 10, 28, 47, 879270, tzinfo=timezone.utc)
        self.assertEqual(telemetria._istante("2026-10-01T10:28:47.87927+00:00"), atteso)
        self.assertEqual(telemetria._istante("2026-10-01 10:28:47.87927Z"), atteso)
        self.assertEqual(telemetria._istante("2026-10-01T10:28:47+00:00"),
                         datetime(2026, 10, 1, 10, 28, 47, tzinfo=timezone.utc))
        self.assertIsNone(telemetria._istante("boh"))


class TestStatoDaMisureA(unittest.TestCase):
    def test_chiavi_a(self):
        misure = {"monitor": [], "pipeline": [], "mese": [], "nuovi": [], "vivi": [], "falliti": [], "lock": [],
                  "da_verificare": {"aperto": {"senza_conferma": 2}}, "letture_scadute": 4,
                  "verifica_7g": {"lombardia": {"letture": 3, "esiti": 2}}, "vista_ms": 120.0,
                  "vista_ms_ruolo": "anon", "ultimi_import_indicepa": [], "ultime_verifiche": [],
                  "ultimi_ingressi": [], "aperti_senza_scadenza": 426}
        campi = telemetria.stato_da_misure(misure, adesso=ADESSO)
        self.assertEqual(campi["letture_scadute"], 4)
        self.assertEqual(campi["aperti_senza_scadenza"], 426)
        self.assertEqual(campi["ultime_verifiche"], ())
        self.assertNotIn(telemetria.NON_MISURATO_DA_VERIFICARE, campi["non_misurati"])

    def test_senza_la_13(self):
        campi = telemetria.stato_da_misure({"da_verificare": None}, adesso=ADESSO)
        self.assertIn(telemetria.NON_MISURATO_DA_VERIFICARE, campi["non_misurati"])
        # L'etichetta copre anche l'ombra con la 13 applicata (#117).
        self.assertEqual(telemetria.NON_MISURATO_DA_VERIFICARE,
                         "stato da verificare (verifica non attiva o migrazione 13 assente)")
        self.assertNotIn("da_verificare", campi)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()


def _giro(id_, ore_fa, coperture, *, giro="06:00", esito="ok"):
    """Una riga del giro con la copertura di alcuni passi (`{passo: (candidati, fatti, motivo)}`)."""
    return _riga(id_, giro, ore_fa, esito=esito, contatori={
        passo: {"copertura": telemetria.copertura(*valori)} for passo, valori in coperture.items()})


class TestCoperturaDelGiro3(unittest.TestCase):
    """Contratto `bandi-giro-3` §1: copertura per passo e `copertura_incompleta`."""

    def test_i_passi_sono_quelli_del_giro_e_del_riepilogo(self):
        db = carica_modulo("db")
        rs = carica_modulo("riepilogo_salute")
        self.assertEqual(tuple(telemetria.PASSI_NEUTRI), db.PASSI_DEL_GIRO)
        for passo, neutro in telemetria.PASSI_NEUTRI.items():
            self.assertEqual(rs.NOMI_PASSI_NEUTRI[passo], neutro)
        # Ogni copertura che `salute` cerca, `misure_salute` la legge.
        for passo in db.PASSI_DEL_GIRO:
            self.assertIn((passo, "copertura"), db.CONTATORI_PIPELINE)

    def test_quattro_giri_di_fila_si_tre_no(self):
        righe = [_giro(10 - i, 6 * i + 1, {"ricontrolli": (900, 400, "tempo")}) for i in range(4)]
        voce = _voce(Stato(ultime_pipeline=tuple(righe)), "copertura_incompleta:ricontrolli")
        self.assertIsNotNone(voce)
        self.assertEqual((voce.livello, voce.misura), ("allarme", 500))
        self.assertIn("ricontrolli", voce.testo_cli)
        self.assertNotIn("copertura_incompleta:ricontrolli", _codici(Stato(ultime_pipeline=tuple(righe[:3]))))

    def test_un_giro_completo_interrompe_la_serie(self):
        righe = [_giro(10 - i, 6 * i + 1, {"monitor": (700, 650 if i != 1 else 700, "tempo")})
                 for i in range(5)]
        self.assertNotIn("copertura_incompleta:controllo_pagine",
                         _codici(Stato(ultime_pipeline=tuple(righe))))

    def test_righe_senza_la_copertura_del_passo_si_saltano(self):
        # Il boot non fa la manutenzione: non azzera il conto e non lo allunga.
        righe = [_giro(9, 1, {"monitor": (10, 5, "tempo")}),
                 _giro(8, 3, {"seo": (4, 4)}, giro="boot"),
                 _giro(7, 7, {"monitor": (10, 5, "spesa")}),
                 _riga(6, "12:00", 13, contatori={"monitor": {"copertura": "rotta"}}),
                 _giro(5, 19, {"monitor": (10, 9, "tempo")}),
                 _giro(4, 25, {"monitor": (10, 9, "tempo")})]
        voce = _voce(Stato(ultime_pipeline=tuple(righe)), "copertura_incompleta:controllo_pagine")
        self.assertIsNotNone(voce)
        self.assertEqual(voce.misura, 5)

    def test_le_righe_saltate_non_contano(self):
        righe = [_giro(10 - i, 6 * i + 1, {"gemelli": (3, 1, "errore")},
                       esito="saltato" if i == 0 else "ok") for i in range(4)]
        self.assertNotIn("copertura_incompleta:doppioni", _codici(Stato(ultime_pipeline=tuple(righe))))

    def test_copertura_dell_ultimo_giro_per_passo(self):
        righe = (_giro(3, 1, {"seo": (5, 5)}, giro="boot"),
                 _giro(2, 7, {"monitor": (700, 640, "tempo"), "seo": (2, 2)}),
                 _giro(1, 13, {"monitor": (700, 700), "gemelli": (1, 1)}))
        esito = telemetria.salute(Stato(ultime_pipeline=righe), adesso=ADESSO)
        self.assertEqual(list(esito.copertura), ["seo", "monitor", "gemelli"])
        self.assertEqual(esito.copertura["seo"]["candidati"], 5)
        self.assertEqual(esito.copertura["monitor"],
                         {"candidati": 700, "fatti": 640, "rimasti": 60, "motivo_rimasti": "tempo"})
        self.assertIn("copertura monitor: 640/700 (rimasti 60: tempo)", esito.informazioni)
        self.assertIn("copertura seo: 5/5", esito.informazioni)
        self.assertEqual(esito.exit_code, 0)
        self.assertEqual(esito.voci, ())


class TestInformazioniDelGiro3(unittest.TestCase):
    def test_variabili_dismesse_informazione_non_allarme(self):
        esito = telemetria.salute(Stato(variabili_dismesse=("TETTO_FETCH_GIRO", "GEMELLI_FUSIONI_PER_GIRO")),
                                  adesso=ADESSO)
        self.assertEqual((esito.allarmi, esito.avvisi, esito.voci), ((), (), ()))
        self.assertEqual(esito.informazioni, (
            "variabili dismesse nel .env (non piu' lette): GEMELLI_FUSIONI_PER_GIRO, TETTO_FETCH_GIRO",))

    def test_sospensioni_in_attesa_della_migrazione_14(self):
        self.assertEqual(telemetria.salute(Stato(sospensioni_attive=False), adesso=ADESSO).informazioni,
                         ("sospensioni in attesa della migrazione 14",))
        for valore in (True, None):
            self.assertEqual(telemetria.salute(Stato(sospensioni_attive=valore), adesso=ADESSO).informazioni, ())

    def test_eventi_marcati_informazione_non_allarme(self):
        # §19.2: quanti eventi la 14 ha marcato (superato, transizione non
        # ammessa). Un'informazione col numero; zero o non misurato: niente.
        esito = telemetria.salute(
            Stato(eventi_marcati={"superato": 4, "transizione_non_ammessa": 2}), adesso=ADESSO)
        self.assertEqual((esito.allarmi, esito.avvisi, esito.voci, esito.exit_code), ((), (), (), 0))
        self.assertEqual(esito.informazioni, (
            "eventi marcati e non applicati: 4 superati, 2 con transizione non ammessa",))
        for valore in (None, {}, {"superato": 0, "transizione_non_ammessa": 0}):
            with self.subTest(marcati=valore):
                self.assertEqual(
                    telemetria.salute(Stato(eventi_marcati=valore), adesso=ADESSO).informazioni, ())

    def test_transizioni_da_decidere_informazione_non_allarme(self):
        # §18.2: la rielaborazione lascia alla redazione le date che chiedono
        # un cambio di stato; `salute` lo dice col numero, senza allarmi.
        esito = telemetria.salute(Stato(transizioni_da_decidere=3), adesso=ADESSO)
        self.assertEqual((esito.allarmi, esito.avvisi, esito.voci, esito.exit_code), ((), (), (), 0))
        self.assertEqual(esito.informazioni, (
            "rielaborazione: 3 transizioni di stato da decidere nell'ultimo giro "
            "(rettifiche registrate e non applicate)",))
        for valore in (0, None):
            with self.subTest(transizioni=valore):
                self.assertEqual(
                    telemetria.salute(Stato(transizioni_da_decidere=valore), adesso=ADESSO).informazioni,
                    ())

    def test_configurazione_scartata_nome_senza_valore(self):
        esito = telemetria.salute(Stato(configurazione_scartate=("TEMPO_MONITOR_S", "SCONOSCIUTA")),
                                  adesso=ADESSO)
        self.assertEqual([v.codice for v in esito.voci], ["configurazione:tempo_monitor_s"])
        self.assertEqual(esito.allarmi, ("TEMPO_MONITOR_S non valida: vale il default",))

    def test_variabili_del_giro_3_come_settings(self):
        settings = carica_modulo("settings")
        attese = {n.lower() for n in (*settings.INTERVALLI_TEMPI, *settings.MODALITA_GIRO_3)}
        self.assertEqual(set(telemetria.VARIABILI_GIRO_3), attese)
