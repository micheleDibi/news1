# -*- coding: utf-8 -*-
"""Riepilogo neutro v1 per il pannello di BandoFit (contratto `bandi-giro-2` §9).

  - le 11 chiavi di primo livello sono quelle che la 12 copia nella busta;
  - le stringhe vengono solo da enum, ISO 8601 UTC o `TESTI_NEUTRI`: nessun
    dollaro, host, URL, PID, testo d'eccezione, motivo o nota esce;
  - `non_misurato` non e' mai un segnale e non porta lo stato ad «attenzione»;
  - `valida_v1` rifiuta ogni forma diversa, e `riepilogo_minimo` la passa.

Funzioni pure: nessuna rete, nessun DB.
"""
import ast
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.supporto import APP, carica_modulo
from tests.test_riepilogo_sql import chiavi_busta

rs = carica_modulo("riepilogo_salute")
telemetria = carica_modulo("telemetria")
Stato = telemetria.Stato

#: 01/10/2026 alle 12:30 di Roma.
ADESSO = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)


def _iso(ore_fa: float) -> str:
    return (ADESSO - timedelta(hours=ore_fa)).isoformat()


def _riga(id_, giro, ore_fa, *, esito="ok", contatori=None, **extra):
    return {"id": id_, "giro": giro, "avviato_at": _iso(ore_fa), "concluso_at": _iso(ore_fa - 0.1),
            "esito": esito, "interrotto_per_tetto": False, "contatori": contatori or {}, **extra}


def _misure(**altro):
    """Una fotografia sana, con la forma di `db.misure_salute` piu' le tre di `sorveglia`."""
    base = {
        "ultime_pipeline": [
            _riga(141, "12:00", 0.4, contatori={"passi_non_ok": []}),
            _riga(140, "boot", 3),
            _riga(139, "06:00", 6.4, contatori={"passi_non_ok": ["seo"]}),
        ],
        "ultimi_monitor": [_riga(138, "06:00", 6.3, contatori={
            "classificazioni": 12, "classificazioni_fallite": 0, "eventi_non_applicati": 0,
            "eventi_non_scritti": 0})],
        "lock": [],
        "scraped_fermi": [],
        "fermi_in_lavorazione": 0,
        "ultimo_bando_nuovo_at": _iso(2),
        "proposte_7g": 9, "ammessi_non_applicati": 0, "in_attesa_pubblicazione": 0,
        "servizio": {"active_state": "active", "sub_state": "running", "n_restarts": 0},
        "memoria": {"nrestarts": [], "dal": {}},
        "job_orario": {"misurato": True, "ultimo_avvio_at": _iso(0.5), "ultimo_esito": "succeeded",
                       "ultimo_ok_at": _iso(0.5), "falliti_24h": 0},
    }
    base.update(altro)
    return base


def _riepilogo(stato=None, misure=None):
    """Salute e riepilogo dalla stessa fotografia, come fa `sorveglia`."""
    misure = misure if misure is not None else _misure()
    campi = telemetria.stato_da_misure(misure, adesso=ADESSO)
    campi.update((stato or {}))
    salute = telemetria.salute(Stato(**campi), adesso=ADESSO)
    return rs.riepilogo_pannello(salute, misure, ADESSO)


class TestSchema(unittest.TestCase):
    def test_le_undici_chiavi_della_busta_della_12(self):
        self.assertEqual(rs.CHIAVI_V1, chiavi_busta())
        self.assertEqual(set(rs.SCHEMA_V1), {"versione", "calcolato_at", *chiavi_busta()})
        self.assertNotIn("consumo", rs.SCHEMA_V1)

    def test_riepilogo_con_le_chiavi_dello_schema(self):
        r = _riepilogo()
        self.assertEqual(list(r), ["versione", "calcolato_at", *rs.CHIAVI_V1])
        self.assertEqual(rs.valida_v1(r), [])

    def test_testi_e_unita_per_ogni_prefisso_di_salute(self):
        self.assertEqual(set(rs.TESTI_NEUTRI), set(telemetria.PREFISSI_SALUTE))
        self.assertEqual(set(rs.UNITA_MISURA), set(telemetria.PREFISSI_SALUTE))
        self.assertTrue(set(rs.UNITA_MISURA.values()) <= set(rs.UNITA))

    def test_testi_neutri_con_i_soli_segnaposti_della_loro_unita(self):
        segnaposto = {"conteggio": "{n}", "quota": "{quota}", "ore": "{ore}", "minuti": "{minuti}"}
        for codice, testo in rs.TESTI_NEUTRI.items():
            with self.subTest(codice=codice):
                self.assertTrue(rs.testo_neutro(testo))
                self.assertNotRegex(testo, r"\d")
                unita = rs.UNITA_MISURA[codice]
                trovati = set(__import__("re").findall(r"\{[a-z]+\}", testo))
                self.assertTrue(trovati <= {segnaposto.get(unita)}, trovati)
                if unita == "nessuna":
                    self.assertEqual(trovati, set())

    def test_segnali_di_spesa_senza_misura(self):
        for codice in ("limite_di_spesa", "credito_ricerca_basso", "consumo_mensile_alto"):
            self.assertEqual(rs.UNITA_MISURA[codice], "nessuna")

    def test_nomi_dei_passi(self):
        self.assertEqual(rs.NOMI_PASSI_NEUTRI, {
            "discover": "ingresso", "scrape": "lettura", "preprocess": "estrazione",
            "enrich": "arricchimento", "resolver": "ricerca_fonti", "seo": "redazione",
            "monitor": "controllo_pagine", "ricontrolli": "ricontrolli",
            "verifica_stato": "verifica_stato"})

    def test_solo_stdlib(self):
        albero = ast.parse((APP / "riepilogo_salute.py").read_text(encoding="utf-8"))
        moduli = {n.module if isinstance(n, ast.ImportFrom) else a.name
                  for n in ast.walk(albero) if isinstance(n, (ast.Import, ast.ImportFrom))
                  for a in (n.names if isinstance(n, ast.Import) else [None])}
        self.assertEqual(moduli, {"__future__", "re", "datetime", "typing"})


class TestTestoNeutro(unittest.TestCase):
    def test_rifiuti(self):
        for testo in ("vedi https://ente.it/bando", "host ://x", "scrivi a info@ente.it",
                      "00/06/12/18", "MONITOR_MODALITA assente", "SORVEGLIA_SERVIZIO_SENDER",
                      "www.lazioeuropa.it", "regione.lazio.it risponde", "EduNews24", "news1",
                      "credito Anthropic", "modello claude", "Haiku", "Firecrawl", "Obiettivo Europa",
                      "IndexNow", "Supabase giu'", "unita' systemd", "bandi_pipeline@123", None, 3):
            with self.subTest(testo=testo):
                self.assertFalse(rs.testo_neutro(testo))

    def test_frasi_normali(self):
        for testo in ("Nessun giro completato da 8 ore.", "La quota è 35%.", "all'ingresso",
                      "passo_degradato:redazione", "controllo_pagine"):
            self.assertTrue(rs.testo_neutro(testo), testo)


class TestSegnali(unittest.TestCase):
    def test_sano_e_ok_anche_con_i_non_misurati(self):
        # NON_MISURABILI_DAL_DB ha sempre due voci: `non_misurato` c'e' sempre
        # in salute, ma non e' un segnale e non porta ad «attenzione».
        r = _riepilogo()
        self.assertEqual(r["stato"], "ok")
        self.assertEqual(r["segnali"], [])
        self.assertIn("credito_ricerca", r["non_misurati"])

    def test_un_avviso_e_attenzione_un_allarme_e_guasto(self):
        r = _riepilogo({"fermi_in_lavorazione": 4})
        self.assertEqual(r["stato"], "attenzione")
        self.assertEqual(r["segnali"][0]["codice"], "fermi_in_lavorazione")
        self.assertEqual(r["segnali"][0]["misura"], 4)
        self.assertEqual(r["segnali"][0]["testo"],
                         "4 bandi sono fermi in lavorazione da più di mezza giornata.")
        r = _riepilogo({"fermi_in_lavorazione": 4, "ore_dall_ultimo_monitor_ok": 30})
        self.assertEqual(r["stato"], "guasto")
        self.assertEqual([s["livello"] for s in r["segnali"]], ["allarme", "avviso"])
        self.assertEqual(rs.valida_v1(r), [])

    def test_quote_ore_e_minuti(self):
        r = _riepilogo({"quota_in_verifica_nuovi": 0.4, "ore_dall_ultimo_monitor_ok": 30.26,
                        "lock_tenuti": (telemetria.LockTenuto("monitor", "monitor:06:00", 150, 180),)})
        per_codice = {s["codice"]: s for s in r["segnali"]}
        self.assertEqual(per_codice["fonti_da_verificare"]["misura"], 0.4)
        self.assertIn("40%", per_codice["fonti_da_verificare"]["testo"])
        self.assertEqual(per_codice["monitor_fermo"]["misura"], 30.3)
        self.assertEqual(per_codice["lavorazione_orfana:controllo_pagine"]["misura"], 150)
        self.assertEqual(rs.valida_v1(r), [])

    def test_stesso_codice_una_volta_sola(self):
        r = _riepilogo({"lock_tenuti": (telemetria.LockTenuto("x", "p", 70, 600),
                                        telemetria.LockTenuto("y", "p", 90, 600)),
                        "modelli_fuori_listino": ("a", "b")})
        codici = [s["codice"] for s in r["segnali"]]
        self.assertEqual(sorted(codici), ["lavorazione_lunga:altro", "modello_fuori_listino"])
        lunga = next(s for s in r["segnali"] if s["codice"] == "lavorazione_lunga:altro")
        self.assertEqual(lunga["misura"], 90)

    def test_dal_dalla_memoria(self):
        memoria = {"dal": {"produttore_fermo": _iso(5), "fermi_in_lavorazione": _iso(-3)}}
        misure = _misure(memoria=memoria, ultime_pipeline=[_riga(1, "06:00", 9)],
                         fermi_in_lavorazione=2)
        r = _riepilogo(misure=misure)
        dal = {s["codice"]: s["dal"] for s in r["segnali"]}
        self.assertEqual(dal["produttore_fermo"], "2026-10-01T05:30:00Z")
        # Un «dal» nel futuro non ha senso: vale adesso, come un codice nuovo.
        self.assertEqual(dal["fermi_in_lavorazione"], "2026-10-01T10:30:00Z")

    def test_al_massimo_quaranta_prima_gli_allarmi(self):
        voci = tuple(telemetria.Voce(f"lavorazione_lunga:{s}", "avviso", "x", 70)
                     for s in telemetria.SUFFISSI_LAVORAZIONE)
        voci += tuple(telemetria.Voce(c, "allarme", "x", 1) for c in (
            "ingresso_guasto", "eventi_non_scritti"))
        salute = telemetria.Salute(voci=voci)
        r = rs.riepilogo_pannello(salute, _misure(), ADESSO)
        self.assertEqual([s["livello"] for s in r["segnali"]][:2], ["allarme", "allarme"])
        molte = telemetria.Salute(voci=tuple(
            telemetria.Voce(c, "allarme", "x", 1) for c in telemetria.CODICI_SALUTE
            if c != "non_misurato"))
        self.assertLessEqual(len(rs.riepilogo_pannello(molte, _misure(), ADESSO)["segnali"]), 40)


class TestNienteCheNonSiaNeutro(unittest.TestCase):
    def test_nessun_dollaro_ne_credito(self):
        misure = _misure(mese=[{"step": "monitor", "usd": "123.45", "crediti": "98765"}])
        r = _riepilogo({"consumo_mensile_quota": 0.93, "crediti_residui_quota": 0.1,
                        "giri_consecutivi_a_tetto": 2,
                        "motivo_ultimo_tetto": "tetto usd 123.45 superato, 98765 crediti"},
                       misure=misure)
        testo = json.dumps(r, ensure_ascii=False)
        for vietato in ("123.45", "123,45", "98765", "usd", "$", "crediti"):
            self.assertNotIn(vietato, testo)
        per_codice = {s["codice"]: s for s in r["segnali"]}
        for codice in ("limite_di_spesa", "consumo_mensile_alto", "credito_ricerca_basso"):
            self.assertIsNone(per_codice[codice]["misura"])
        self.assertEqual(rs.valida_v1(r), [])

    def test_nessun_host_url_pid_o_eccezione(self):
        misure = _misure(
            lock=[{"nome": "bandi_pipeline", "proprietario": "bandi_pipeline@4242",
                   "acquisito_at": _iso(0.3), "scade_at": _iso(-3.7)}],
            ultime_pipeline=[_riga(141, "12:00", 0.4, motivo="lock tenuto da bandi_pipeline@4242",
                                   note="https://qggf.supabase.co errore 42501",
                                   contatori={"passi_non_ok": ["seo", "passo_nuovo"],
                                              "scrape": {"fonti_in_errore": [449]}})])
        r = _riepilogo({"misure_db_errore": "ConnectError: https://qggf.supabase.co timeout",
                        "tipi_attivi_ignorati": ("profroga",)}, misure=misure)
        testo = json.dumps(r, ensure_ascii=False)
        for vietato in ("4242", "supabase", "https", "ConnectError", "42501", "profroga",
                        "MONITOR", "bandi_pipeline", "449", "lock tenuto"):
            self.assertNotIn(vietato, testo)
        self.assertEqual(r["lavorazioni"], [{"nome": "giro", "da_min": 18.0, "ttl_min": 240.0,
                                             "stato": "regolare"}])
        self.assertEqual(r["giri"][0]["passi_non_ok"], ["altro", "redazione"])
        self.assertEqual(rs.valida_v1(r), [])

    def test_non_misurati_solo_dall_elenco_neutro(self):
        r = _riepilogo(misure=_misure(servizio=None, job_orario=None))
        self.assertEqual(r["non_misurati"], ["servizio", "job_orario", "accesso_fonte_riservata",
                                             "credito_ricerca", "schede_con_sezione",
                                             "da_verificare"])
        # «giri a tetto», «consumo mensile» e gli altri testi liberi non escono.
        r = _riepilogo(misure=_misure(pipeline=None, mese=None))
        self.assertTrue(set(r["non_misurati"]) <= set(rs.NON_MISURATI_V1))
        self.assertNotIn("giri", " ".join(r["non_misurati"]))

    def test_testi_dei_non_misurati_come_in_telemetria(self):
        self.assertEqual(set(rs.NON_MISURATI_NEUTRI), {
            *telemetria.NON_MISURABILI_DAL_DB, telemetria.NON_MISURATO_SERVIZIO,
            telemetria.NON_MISURATO_JOB_ORARIO})


class TestSezioni(unittest.TestCase):
    def test_produttore(self):
        r = _riepilogo()
        self.assertEqual(r["produttore"], {
            "ultimo_giro_at": "2026-10-01T10:12:00Z", "ore_dall_ultimo_giro": 0.3,
            "giri_24h": 3, "riavvii_24h": 1, "servizio": "attivo"})
        for servizio, atteso in (({"active_state": "failed"}, "non_attivo"),
                                 ({"active_state": "activating", "sub_state": "auto-restart"},
                                  "non_attivo"), (None, "non_misurato")):
            self.assertEqual(_riepilogo(misure=_misure(servizio=servizio))["produttore"]["servizio"],
                             atteso)

    def test_giri(self):
        misure = _misure(ultime_pipeline=[
            _riga(3, "06:00", 1, esito="interrotto_per_tetto", interrotto_per_tetto=True),
            _riga(2, "boot", 2, esito="saltato", contatori={"riavvio_dopo_crash": 1}),
            _riga(1, None, 3, esito="strano")])
        giri = _riepilogo(misure=misure)["giri"]
        self.assertEqual([(g["id"], g["giro"], g["esito"]) for g in giri],
                         [(3, "06", "interrotto_per_tetto"), (2, "avvio", "saltato"),
                          (1, "manuale", "errore")])
        self.assertEqual(giri[0]["durata_min"], 6.0)
        self.assertTrue(giri[0]["interrotto_per_tetto"])

    def test_controlli_ingresso_eventi_job(self):
        r = _riepilogo(misure=_misure(scraped_fermi=[{"id": 1}, {"id": 2}], fermi_in_lavorazione=5))
        self.assertEqual(r["controlli"][0], {
            "avviato_at": "2026-10-01T04:12:00Z", "esito": "ok", "classificazioni": 12,
            "classificazioni_fallite": 0, "eventi_non_applicati": 0})
        self.assertEqual(r["ingresso"], {"fermi_in_ingresso": 2, "fermi_in_lavorazione": 5,
                                         "ultimo_bando_nuovo_at": "2026-10-01T08:30:00Z"})
        self.assertEqual(r["eventi"], {"ammessi_non_applicati": 0, "proposte_7g": 9,
                                       "in_attesa_pubblicazione": 0})
        self.assertEqual(r["job_orario"]["ultimo_esito"], "succeeded")
        self.assertIsNone(r["da_verificare"])
        vuoto = _riepilogo(misure=_misure(job_orario={"misurato": False}))
        self.assertEqual(vuoto["job_orario"], {"ultimo_avvio_at": None, "ultimo_esito": "non_misurato",
                                               "ultimo_ok_at": None, "falliti_24h": None})

    def test_misure_assenti(self):
        salute = telemetria.salute(Stato(), adesso=ADESSO)
        r = rs.riepilogo_pannello(salute, {}, ADESSO)
        self.assertEqual(rs.valida_v1(r), [])
        self.assertEqual(r["giri"], [])
        self.assertIsNone(r["produttore"]["giri_24h"])

    def test_frazioni_a_cinque_cifre(self):
        misure = _misure(ultimo_bando_nuovo_at="2026-10-01T08:30:00.12345+00:00")
        self.assertEqual(_riepilogo(misure=misure)["ingresso"]["ultimo_bando_nuovo_at"],
                         "2026-10-01T08:30:00Z")


class TestValidaV1(unittest.TestCase):
    def _valido(self):
        return _riepilogo({"fermi_in_lavorazione": 3, "quota_in_verifica_nuovi": 0.4})

    def _errori(self, cambia):
        r = self._valido()
        cambia(r)
        return rs.valida_v1(r)

    def test_forme_rifiutate(self):
        casi = {
            "chiave in piu'": lambda r: r.update(consumo={"usd": 1}),
            "chiave mancante": lambda r: r.pop("giri"),
            "versione 2": lambda r: r.update(versione=2),
            "calcolato_at locale": lambda r: r.update(calcolato_at="2026-10-01T12:30:00+02:00"),
            "stato incoerente": lambda r: r.update(stato="ok"),
            "non_misurato fra i segnali": lambda r: r["segnali"].append({
                "codice": "non_misurato", "livello": "avviso", "testo": "x", "dal": r["calcolato_at"],
                "misura": None}),
            "codice sconosciuto": lambda r: r["segnali"][0].update(codice="inventato"),
            "misura con unita' nessuna": lambda r: r["segnali"].append({
                "codice": "consumo_mensile_alto", "livello": "allarme",
                "testo": rs.TESTI_NEUTRI["consumo_mensile_alto"], "dal": r["calcolato_at"],
                "misura": 0.93}),
            "quota fuori scala": lambda r: next(s for s in r["segnali"]
                                                if s["codice"] == "fonti_da_verificare").update(misura=1.5),
            "testo non neutro": lambda r: r["segnali"][0].update(testo="vedi https://ente.it"),
            "non misurato sconosciuto": lambda r: r["non_misurati"].append("giri a tetto"),
            "troppi giri": lambda r: r.update(giri=r["giri"] * 21),
            "lavorazione col nome del lock": lambda r: r["lavorazioni"].append(
                {"nome": "bandi_pipeline", "da_min": 1, "ttl_min": 2, "stato": "regolare"}),
            "host in un campo": lambda r: r["ingresso"].update(ultimo_bando_nuovo_at="x.supabase.co"),
            "da_verificare prima della 13": lambda r: r.update(da_verificare={}),
            "esito del job inventato": lambda r: r["job_orario"].update(ultimo_esito="boh"),
        }
        self.assertEqual(rs.valida_v1(self._valido()), [])
        for nome, cambia in casi.items():
            with self.subTest(caso=nome):
                self.assertNotEqual(self._errori(cambia), [])

    def test_non_oggetto(self):
        self.assertNotEqual(rs.valida_v1(None), [])
        self.assertNotEqual(rs.valida_v1([]), [])


class TestRiepilogoMinimo(unittest.TestCase):
    def test_minimo_valido_e_guasto(self):
        r = rs.riepilogo_minimo(ADESSO)
        self.assertEqual(rs.valida_v1(r), [])
        self.assertEqual(r["stato"], "guasto")
        self.assertEqual([s["codice"] for s in r["segnali"]], ["riepilogo_non_valido"])
        self.assertEqual(list(r), ["versione", "calcolato_at", *rs.CHIAVI_V1])

    def test_minimo_con_dal(self):
        self.assertEqual(rs.riepilogo_minimo(ADESSO, dal=_iso(2))["segnali"][0]["dal"],
                         "2026-10-01T08:30:00Z")


class TestCostantiRicopiate(unittest.TestCase):
    """Le costanti copiate da `telemetria` per restare in sola stdlib."""

    def test_uguali_agli_originali(self):
        self.assertEqual(tuple(rs._GIRI_DI_REGIME), telemetria.GIRI_DI_REGIME)
        self.assertEqual(rs._GIRO_AVVIO, telemetria.GIRO_AVVIO)
        self.assertEqual(rs._LAVORAZIONI_PER_LOCK, telemetria.LAVORAZIONI_PER_LOCK)
        self.assertEqual(rs.LAVORAZIONI_V1, telemetria.SUFFISSI_LAVORAZIONE)
        self.assertEqual((rs._LOCK_AVVISO_MIN, rs._LOCK_ALLARME_MIN),
                         (telemetria.LOCK_AVVISO_MIN, telemetria.LOCK_ALLARME_MIN))
        self.assertEqual(rs._STATI_SERVIZIO_FERMO, telemetria.STATI_SERVIZIO_FERMO)
        self.assertEqual(set(rs.ESITI_V1), {telemetria.ESITO_OK, telemetria.ESITO_ERRORE,
                                            telemetria.ESITO_SALTATO, telemetria.ESITO_INTERROTTO})
        self.assertEqual(rs.NOMI_VIETATI[:9], ("edunews", "news1", "anthropic", "claude", "haiku",
                                               "firecrawl", "obiettivo", "indexnow", "supabase"))


class TestPercorsoA(unittest.TestCase):
    """Riepilogo col percorso A (#76): codici A, testo generico, sezione da_verificare."""

    DA_VERIFICARE = {
        "in_apertura": {"data_apertura_passata": 3, "motivo_inventato": 9},
        "aperto": {"senza_conferma": 12, "smentito_dalla_fonte": 2},
        "proposte_in_ombra_per_tipo": {"chiusura": 4, "rettifica": 1, "tipo_inventato": 7},
        "chiusure_applicate_7g": 0, "host_frenati": 1, "pagine_rimosse": 2, "forse_non_bandi": 3,
    }

    def test_costanti_come_gli_originali(self):
        self.assertEqual(rs.MOTIVI_DA_VERIFICARE_V1, carica_modulo("stato_bando").MOTIVI_DA_VERIFICARE)
        self.assertEqual(rs.TIPI_PROPOSTA_V1, carica_modulo("eventi").TIPI_VERIFICA)

    def test_sezione_da_verificare(self):
        r = _riepilogo(misure=_misure(da_verificare=self.DA_VERIFICARE))
        self.assertEqual(r["da_verificare"], {
            "in_apertura": {"data_apertura_passata": 3},
            "aperto": {"smentito_dalla_fonte": 2, "senza_conferma": 12},
            "proposte_in_ombra_per_tipo": {"chiusura": 4, "rettifica": 1},
            "chiusure_applicate_7g": 0, "host_frenati": 1, "pagine_rimosse": 2, "forse_non_bandi": 3})
        self.assertNotIn("da_verificare", r["non_misurati"])
        self.assertEqual(rs.valida_v1(r), [])
        testo = json.dumps(r)
        self.assertNotIn("inventato", testo)

    def test_senza_la_13_null_e_non_misurato(self):
        r = _riepilogo()
        self.assertIsNone(r["da_verificare"])
        self.assertIn("da_verificare", r["non_misurati"])

    def test_valida_la_forma_di_da_verificare(self):
        r = _riepilogo(misure=_misure(da_verificare=self.DA_VERIFICARE))
        casi = {
            "chiave in piu'": lambda d: d.update(altro=1),
            "motivo fuori elenco": lambda d: d["aperto"].update(motivo_inventato=1),
            "conteggio negativo": lambda d: d.update(host_frenati=-1),
            "conteggio mancante": lambda d: d.update(pagine_rimosse=None),
        }
        for nome, cambia in casi.items():
            with self.subTest(caso=nome):
                copia = json.loads(json.dumps(r))
                cambia(copia["da_verificare"])
                self.assertNotEqual(rs.valida_v1(copia), [])

    def test_codici_a_con_testo_neutro(self):
        voci = (telemetria.Voce("aperti_senza_conferma", "avviso", "x", 0.72),
                telemetria.Voce("estrattore_muto:lazioeuropa", "allarme", "x", 6),
                telemetria.Voce("vista_lenta", "allarme", "vista bando_pubblico lenta: 2500 ms", None),
                telemetria.Voce("indicepa_non_aggiornato", "avviso", "IndicePA: x", None))
        r = rs.riepilogo_pannello(telemetria.Salute(voci=voci), _misure(), ADESSO)
        per_codice = {x["codice"]: x for x in r["segnali"]}
        self.assertEqual(per_codice["aperti_senza_conferma"]["testo"],
                         "La quota di bandi aperti senza conferma dalla fonte è 72%.")
        self.assertEqual(per_codice["estrattore_muto:lazioeuropa"]["misura"], 6)
        self.assertNotIn("bando_pubblico", json.dumps(r))
        self.assertEqual(rs.valida_v1(r), [])

    def test_verifica_stato_ferma_testo_per_livello(self):
        for livello, testo in (("avviso", "La verifica dello stato dei bandi non è ancora stata eseguita."),
                               ("allarme", "La verifica dello stato dei bandi non si conclude da oltre un giorno.")):
            with self.subTest(livello=livello):
                voci = (telemetria.Voce("verifica_stato_ferma", livello, "x", None),)
                r = rs.riepilogo_pannello(telemetria.Salute(voci=voci), _misure(), ADESSO)
                [segnale] = [x for x in r["segnali"] if x["codice"] == "verifica_stato_ferma"]
                self.assertEqual(segnale["testo"], testo)
                self.assertEqual(rs.valida_v1(r), [])
        self.assertTrue(all(rs.testo_neutro(t) for t in rs.TESTI_NEUTRI_PER_LIVELLO.values()))
        self.assertTrue(all(c in rs.TESTI_NEUTRI and l in rs.TESTO_SENZA_MISURA
                            for c, l in rs.TESTI_NEUTRI_PER_LIVELLO))

    def test_eventi_non_leggibili_con_testo_neutro(self):
        voci = (telemetria.Voce("eventi_non_leggibili", "avviso",
                                "eventi applicati e non resi leggibili nell'ultimo monitor: 3", 3),)
        r = rs.riepilogo_pannello(telemetria.Salute(voci=voci), _misure(), ADESSO)
        [segnale] = [x for x in r["segnali"] if x["codice"] == "eventi_non_leggibili"]
        self.assertEqual((segnale["testo"], segnale["misura"]),
                         ("3 eventi applicati non sono ancora visibili negli aggiornamenti.", 3))
        self.assertEqual(rs.UNITA_MISURA["eventi_non_leggibili"], "conteggio")
        self.assertEqual(rs.valida_v1(r), [])

    def test_prefisso_senza_testo_non_sparisce(self):
        voci = (telemetria.Voce("monitor_fermo", "allarme", "x", 30),)
        salute = telemetria.Salute(voci=voci + (types_voce("codice_futuro", "avviso", 3),))
        r = rs.riepilogo_pannello(salute, _misure(), ADESSO)
        futuro = next(x for x in r["segnali"] if x["codice"] == "codice_futuro")
        self.assertEqual((futuro["testo"], futuro["misura"]), ("Segnale di avviso.", None))
        self.assertEqual(rs.valida_v1(r), [])
        # Con un testo diverso dal generico non passa.
        futuro["testo"] = "Frase inventata."
        self.assertNotEqual(rs.valida_v1(r), [])


def types_voce(codice, livello, misura):
    """Una voce con un codice che telemetria non conosce ancora (bypassa `_voce`)."""
    from types import SimpleNamespace
    return SimpleNamespace(codice=codice, livello=livello, testo_cli="x", misura=misura)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
