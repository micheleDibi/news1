# -*- coding: utf-8 -*-
"""`MONITOR_TIPI_ATTIVI`: attivazione per tipo di evento (contratto di ottobre
2026, §3).

Con `MONITOR_MODALITA=ombra`, gli eventi dei tipi attivi **nati nel giro** e
ammessi dai gate diventano applicati e leggibili nello stesso giro, con tre
scritture: `bando_registra_evento` (riga d'ombra, che restituisce l'id),
`bando_applica_evento`, `leggibile=true` (RIPRESA §5.8). Gli altri tipi restano
in ombra; gli eventi gia' registrati prima (la dedup della RPC risponde
`nuovo=false`) non si toccano: il reviewer ha visto che le aperture vecchie in
coda possono riaprire un chiuso.

I gate non sono l'oggetto di questi test: `eventi.valuta` e' sostituito da un
giudizio «ammesso», e tutto il resto (riga, chiave di `valore_dopo`, colonne,
date da rigenerare) gira col codice vero. Il caso end-to-end della proroga
passa anche dall'adattatore di produzione (`FonteDatiSupabase`) con un DB finto
che applica davvero `valore_dopo`. Dato di T-D5: le 9 proroghe ammesse dal
24/09 erano tutte giuste.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_tipi_attivi
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.supporto import carica_modulo
from tests.test_monitoraggio import (
    ADESSO, VERSIONE, _FonteSenzaLimite, _Risposta, _bando, _impostazioni, _lock_libero,
)

monitoraggio = carica_modulo("monitoraggio")
eventi = carica_modulo("eventi")
db = carica_modulo("db")

TIPI = ("faq", "nuovo_allegato", "graduatoria", "esito", "proroga")
URL_PROVA = "https://www.lazioeuropa.it/bandi/avviso-1/"

PAGINA_PROROGA = ('<main><h1>Avviso</h1><p>Termine prorogato al 30 novembre 2026.</p>'
                  '<p><a href="https://www.lazioeuropa.it/determina.pdf">Determina</a></p></main>')

AMMESSO = eventi.Giudizio(ammesso=True, gate="G2", superati=("G1", "G2", "G4", "G7"),
                          confidenza=0.95, leggibile=True)


def _riga(**extra):
    # `contenuto` e `descrizione_breve` stanno nella riga perche' la fonte dati
    # di prova li restituisce da `righe` (`testi_del_bando`): la rigenerazione
    # della prosa li rilegge, come in produzione.
    base = dict(testo_norm="Avviso\nDomande entro il 30 ottobre 2026.",
                impronta_contenuto="vecchia", impronte_sezioni={"__link__": [], **VERSIONE},
                data_scadenza="2026-10-30",
                contenuto="Le domande vanno presentate entro il 30 ottobre 2026.",
                descrizione_breve=None)
    base.update(extra)
    return _bando(**base)


def _proroga():
    return eventi.Evento(tipo="proroga", valore="2026-11-30", url_prova=URL_PROVA,
                         citazione="Termine prorogato al 30 novembre 2026")


def _faq():
    return eventi.Evento(tipo="faq", url_prova="https://www.lazioeuropa.it/faq.pdf",
                         citazione="Pubblicate le FAQ")


async def _scarica(url, **kw):
    return _Risposta(html=PAGINA_PROROGA)


def _classificatore(*proposte):
    async def classifica(ctx):
        return list(proposte)
    return classifica


class _DbFinto:
    """Il DB bandi ridotto all'osso, con le interfacce di `db.controllo` e del
    client: la registrazione, l'applicazione (che riversa davvero `valore_dopo`
    nelle colonne del bando) e l'UPDATE di `leggibile`."""

    def __init__(self, bando, *, nuovo=True, applica=True, eccezione=None):
        self.bando = dict(bando)
        self.eventi: dict[int, dict] = {}
        self.chiamate: list[tuple] = []
        self._nuovo = nuovo
        self._applica = applica
        self._eccezione = eccezione

    # --- come `db.controllo` ---
    def rpc_disponibile(self, _nome):
        return True

    def aggiorna(self, tabella, evento_id, payload):
        self.chiamate.append(("aggiorna", tabella, evento_id, dict(payload)))
        self.eventi[evento_id].update(payload)
        return {"scritto": True, "ignorate": (), "motivo": ""}

    # --- come il client supabase ---
    def rpc(self, nome, parametri):
        self.chiamate.append(("rpc", nome, dict(parametri)))
        if nome == eventi.RPC_REGISTRA_EVENTO:
            evento_id = len(self.eventi) + 1
            self.eventi[evento_id] = {
                "tipo": parametri["p_tipo"], "valore_dopo": parametri["p_valore_dopo"],
                "applicato": False, "leggibile": parametri["p_leggibile"],
            }
            dati = {"id": evento_id, "nuovo": self._nuovo, "applicato": False}
        elif nome == db.RPC_APPLICA_EVENTO:
            if self._eccezione is not None:
                raise self._eccezione
            evento = self.eventi[parametri["p_evento_id"]]
            if self._applica:
                self.bando.update(evento["valore_dopo"])
                evento["applicato"] = True
            dati = self._applica
        else:                                              # pragma: no cover - difesa
            raise AssertionError(f"RPC inattesa: {nome}")
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=dati))

    def rpc_chiamate(self, nome):
        return [c[2] for c in self.chiamate if c[0] == "rpc" and c[1] == nome]


class _FonteE2E(_FonteSenzaLimite):
    """Coda e memoria finte, ma le tre scritture dell'attivazione passano
    dall'adattatore di produzione (`FonteDatiSupabase`) sopra `_DbFinto`."""

    def __init__(self, db_finto, **kw):
        super().__init__(**kw)
        self._reale = monitoraggio.FonteDatiSupabase(controllo=db_finto, client=db_finto)

    def registra_evento_rpc(self, riga):
        return self._reale.registra_evento_rpc(riga)

    def applica_evento(self, evento_id):
        return self._reale.applica_evento(evento_id)

    def rendi_leggibile(self, evento_id, *, in_aggiornamenti=True):
        return self._reale.rendi_leggibile(evento_id, in_aggiornamenti=in_aggiornamenti)


def _patch_gate():
    return patch.object(monitoraggio.eventi_mod, "valuta", lambda evento, ctx: AMMESSO)


class TestProrogaEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Il caso chiesto dal committente: proroga attiva, dalla pagina a IndexNow."""

    async def test_proroga_attiva_dalla_pagina_a_indexnow(self):
        db_finto = _DbFinto({"id": 1, "data_scadenza": "2026-10-30", "stato_bando": "aperto"})
        dati = _FonteE2E(db_finto, righe=[_riga()])
        rigenerate = []

        async def rigenera(riga, evento_riga, *, vecchia, nuova, ruolo):
            rigenerate.append((ruolo, vecchia, nuova))
            return {"scritto": True, "via": "llm"}

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
                scarica=_scarica, classifica=_classificatore(_proroga()),
                rigenerazione=rigenera, tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)

        # 1. registrazione: la data sta nella colonna giusta, mai in `valore`,
        #    e la riga nasce non applicata e non leggibile.
        (registrazione,) = db_finto.rpc_chiamate(eventi.RPC_REGISTRA_EVENTO)
        self.assertEqual(registrazione["p_tipo"], "proroga")
        self.assertEqual(registrazione["p_valore_dopo"], {"data_scadenza": "2026-11-30"})
        self.assertFalse(registrazione["p_applica"])
        self.assertFalse(registrazione["p_leggibile"])
        # 2. applicazione: la RPC finta riversa `valore_dopo` nella colonna.
        self.assertEqual(db_finto.rpc_chiamate(db.RPC_APPLICA_EVENTO), [{"p_evento_id": 1}])
        self.assertEqual(db_finto.bando["data_scadenza"], "2026-11-30")
        # 3. leggibile (con il box), dopo l'applicazione.
        self.assertEqual(db_finto.chiamate[-1],
                         ("aggiorna", db.TABELLA_EVENTO, 1,
                          {"leggibile": True, "in_aggiornamenti": True}))
        self.assertTrue(db_finto.eventi[1]["applicato"])
        # La prosa riscritta con la data nuova, e la pagina a IndexNow.
        from datetime import date
        self.assertEqual(rigenerate, [("scadenza", date(2026, 10, 30), date(2026, 11, 30))])
        self.assertEqual(esito["slug_modificati"], ["avviso-1"])
        # La riga del giro.
        self.assertEqual(esito["tipi_attivi"], list(TIPI))
        self.assertEqual(esito["applicati_per_tipo"], {"proroga": 1})
        self.assertEqual(esito["eventi_non_applicati"], 0)
        self.assertEqual(esito["modalita"], "ombra")
        # Nessun INSERT d'ombra in piu': la riga l'ha scritta la RPC.
        self.assertEqual(dati.registrati, [])

    async def test_proroga_non_attiva_resta_in_ombra(self):
        db_finto = _DbFinto({"id": 1, "data_scadenza": "2026-10-30"})
        dati = _FonteE2E(db_finto, righe=[_riga()])
        rigenerate = []

        async def rigenera(*a, **k):
            rigenerate.append(a)
            return {"scritto": True}

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=("faq",)), fonte_dati=dati,
                scarica=_scarica, classifica=_classificatore(_proroga()),
                rigenerazione=rigenera, tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(db_finto.chiamate, [])             # niente RPC, niente UPDATE
        self.assertEqual(db_finto.bando["data_scadenza"], "2026-10-30")
        self.assertEqual(rigenerate, [])
        self.assertEqual(esito["slug_modificati"], [])
        self.assertEqual(esito["applicati_per_tipo"], {})
        # L'evento c'e', in ombra, come oggi.
        (ombra,) = dati.registrati
        self.assertFalse(ombra["applicato"])
        self.assertFalse(ombra["leggibile"])

    async def test_evento_gia_registrato_non_si_tocca(self):
        # Un'apertura registrata prima dell'attivazione (dedup della RPC):
        # applicarla potrebbe riaprire un bando chiuso.
        db_finto = _DbFinto({"id": 1, "stato_bando": "chiuso", "data_apertura": None},
                            nuovo=False)
        dati = _FonteE2E(db_finto, righe=[_riga()])
        apertura = eventi.Evento(tipo="apertura", valore="2026-11-01", url_prova=URL_PROVA,
                                 citazione="Domande dal 1 novembre 2026")
        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=("apertura",)),
                fonte_dati=dati, scarica=_scarica, classifica=_classificatore(apertura),
                tabella_domini={}, lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(len(db_finto.rpc_chiamate(eventi.RPC_REGISTRA_EVENTO)), 1)
        self.assertEqual(db_finto.rpc_chiamate(db.RPC_APPLICA_EVENTO), [])
        self.assertFalse(any(c[0] == "aggiorna" for c in db_finto.chiamate))
        self.assertEqual(db_finto.bando["stato_bando"], "chiuso")
        # Non e' un'applicazione fallita: nessun allarme.
        self.assertEqual(esito["eventi_non_applicati"], 0)
        self.assertEqual(esito["applicati_per_tipo"], {})
        self.assertEqual(esito["slug_modificati"], [])

    async def test_rpc_di_applicazione_fallita_niente_leggibile_e_allarme(self):
        for nome, db_finto in (
            ("rifiuto", _DbFinto({"id": 1, "data_scadenza": "2026-10-30"}, applica=False)),
            ("5xx", _DbFinto({"id": 1, "data_scadenza": "2026-10-30"},
                             eccezione=RuntimeError("503 Service Unavailable"))),
        ):
            with self.subTest(errore=nome):
                dati = _FonteE2E(db_finto, righe=[_riga()])
                with _patch_gate():
                    esito = await monitoraggio.run(
                        impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
                        scarica=_scarica, classifica=_classificatore(_proroga()),
                        tabella_domini={}, lock=_lock_libero(), adesso=ADESSO,
                        casuale=lambda: 0.5)
                self.assertFalse(any(c[0] == "aggiorna" for c in db_finto.chiamate))
                self.assertEqual(db_finto.bando["data_scadenza"], "2026-10-30")
                self.assertFalse(db_finto.eventi[1]["applicato"])
                self.assertFalse(db_finto.eventi[1]["leggibile"])
                self.assertEqual(esito["eventi_non_applicati"], 1)
                self.assertTrue(any("non applicati" in a for a in esito["allarmi"]))
                self.assertEqual(esito["slug_modificati"], [])
                # Mai un INSERT «applicato» dopo una RPC fallita.
                self.assertEqual(dati.registrati, [])


class TestControlloPerTipo(unittest.IsolatedAsyncioTestCase):
    """Un controllo alla volta, con la fonte dati di base (le tre scritture
    finiscono in liste)."""

    async def _controlla(self, *proposte, dati=None, tipi=TIPI, **kw):
        dati = dati if dati is not None else monitoraggio.FonteDati()
        with _patch_gate():
            esito = await monitoraggio.controlla(
                _riga(), scarica=_scarica, classifica=_classificatore(*proposte),
                fonte_dati=dati, tipi_attivi=tipi, adesso=ADESSO, casuale=lambda: 0.5, **kw)
        return esito, dati

    async def test_faq_attiva_tre_scritture_in_ordine(self):
        esito, dati = await self._controlla(_faq())
        self.assertEqual([r["tipo"] for r in dati.registrati_rpc], ["faq"])
        self.assertEqual(dati.applicati, [1])
        self.assertEqual(dati.resi_leggibili, [(1, True)])
        self.assertEqual(dati.registrati, [])
        self.assertEqual(esito.eventi_applicati, 1)
        self.assertEqual(esito.tipi_applicati, ["faq"])
        self.assertEqual(esito.eventi[0]["applicato"], True)

    async def test_tipo_non_attivo_insert_d_ombra_come_oggi(self):
        rettifica = eventi.Evento(tipo="rettifica", campo="importo_totale_eur", valore="2000000",
                                  url_prova=URL_PROVA, citazione="Dotazione rettificata")
        esito, dati = await self._controlla(rettifica)
        self.assertEqual(dati.registrati_rpc, [])
        self.assertEqual(len(dati.registrati), 1)
        self.assertEqual(esito.eventi_applicati, 0)
        self.assertEqual(esito.eventi_non_applicati, 0)

    async def test_registrazione_fallita_ripiega_sull_ombra(self):
        class _SenzaRpc(monitoraggio.FonteDati):
            def registra_evento_rpc(self, riga):
                return None

        esito, dati = await self._controlla(_faq(), dati=_SenzaRpc())
        (ombra,) = dati.registrati                          # l'evento non si perde
        self.assertFalse(ombra["applicato"])
        self.assertFalse(ombra["leggibile"])
        self.assertFalse(ombra["in_aggiornamenti"])
        self.assertEqual(dati.applicati, [])
        self.assertEqual(esito.eventi_non_applicati, 1)

    async def test_applicato_ma_non_leggibile(self):
        class _SenzaLeggibile(monitoraggio.FonteDati):
            def rendi_leggibile(self, evento_id, *, in_aggiornamenti=True):
                return False

        esito, dati = await self._controlla(_proroga(), dati=_SenzaLeggibile())
        self.assertEqual(dati.applicati, [1])
        # La colonna e' cambiata: si conta applicato (prosa, IndexNow), e si
        # dice che il box non lo mostra.
        self.assertEqual(esito.eventi_applicati, 1)
        self.assertEqual(esito.eventi_invisibili, 1)
        self.assertTrue(esito.rigenerazione_dovuta)

    async def test_stato_solo_proposto_leggibile_non_applicato(self):
        sospensione = eventi.Evento(tipo="sospensione", url_prova=URL_PROVA,
                                    citazione="Il bando e' sospeso")
        esito, dati = await self._controlla(sospensione, tipi=("sospensione",),
                                            stati_estesi=False)
        self.assertEqual(dati.applicati, [])                # la colonna non si tocca
        self.assertEqual(dati.resi_leggibili, [(1, True)])
        self.assertEqual(esito.eventi_applicati, 0)

    async def test_dry_run_non_scrive_niente(self):
        esito, dati = await self._controlla(_faq(), dry_run=True)
        self.assertEqual(dati.registrati_rpc, [])
        self.assertEqual(dati.applicati, [])
        self.assertEqual(dati.registrati, [])
        self.assertEqual(esito.eventi_applicati, 0)

    async def test_in_attivo_resta_il_percorso_del_rilascio_2(self):
        # Con MONITOR_MODALITA=attivo ogni tipo passa dalla RPC unica di
        # `eventi.applica`: l'attivazione per tipo non entra in gioco.
        applicazione = eventi.Applicazione(
            riga={"bando_id": 1, "tipo": "faq", "applicato": True, "leggibile": True},
            applicato=True, scritto=True, giudizio=AMMESSO)
        with patch.object(monitoraggio.eventi_mod, "applica", lambda p, c: applicazione):
            esito, dati = await self._controlla(_faq(), modalita="attivo")
        self.assertEqual(dati.registrati_rpc, [])
        self.assertEqual(esito.eventi_applicati, 1)


class TestRielaborazioneDopoGliEventi(unittest.IsolatedAsyncioTestCase):
    """Giro 3, §5: una rettifica di contenuto o allegati, o una riapertura,
    applicata rimette il bando in coda alla rielaborazione."""

    async def _controlla(self, evento, *, tipi, **kw):
        dati = monitoraggio.FonteDati()
        with _patch_gate():
            esito = await monitoraggio.controlla(
                _riga(), scarica=_scarica, classifica=_classificatore(evento),
                fonte_dati=dati, tipi_attivi=tipi, adesso=ADESSO, casuale=lambda: 0.5, **kw)
        return esito, dati

    def _rettifica(self, campo, valore="nuovo testo"):
        return eventi.Evento(tipo="rettifica", campo=campo, valore=valore, url_prova=URL_PROVA,
                             citazione="Rettifica dell'avviso")

    async def test_rettifica_di_contenuto_e_di_allegati(self):
        for campo in ("contenuto", "allegati"):
            with self.subTest(campo=campo):
                esito, dati = await self._controlla(self._rettifica(campo), tipi=("rettifica",))
                self.assertEqual(esito.eventi_applicati, 1)
                self.assertEqual(dati.azzerati, [1])
                self.assertTrue(esito.rielaborazione_richiesta)

    async def test_riapertura(self):
        riapertura = eventi.Evento(tipo="riapertura", valore="2026-12-15", url_prova=URL_PROVA,
                                   citazione="Il bando e' riaperto fino al 15 dicembre 2026")
        esito, dati = await self._controlla(riapertura, tipi=("riapertura",))
        self.assertEqual(esito.eventi_applicati, 1)
        self.assertEqual(dati.azzerati, [1])

    async def test_altri_eventi_no(self):
        for evento, tipi in ((_faq(), TIPI), (_proroga(), TIPI),
                             (self._rettifica("data_scadenza", "2026-11-30"), ("rettifica",))):
            with self.subTest(tipo=evento.tipo, campo=evento.campo):
                esito, dati = await self._controlla(evento, tipi=tipi)
                self.assertEqual(dati.azzerati, [])
                self.assertFalse(esito.rielaborazione_richiesta)

    async def test_solo_se_applicato_e_mai_in_dry_run(self):
        # In ombra (tipo non attivo) l'evento non e' applicato: niente marcatore.
        esito, dati = await self._controlla(self._rettifica("contenuto"), tipi=())
        self.assertEqual((esito.eventi_applicati, dati.azzerati), (0, []))
        esito, dati = await self._controlla(self._rettifica("contenuto"), tipi=("rettifica",),
                                            dry_run=True)
        self.assertEqual(dati.azzerati, [])

    def test_regola_pura(self):
        self.assertTrue(monitoraggio.rimette_in_rielaborazione("riapertura", None))
        self.assertTrue(monitoraggio.rimette_in_rielaborazione("rettifica", "allegati"))
        self.assertFalse(monitoraggio.rimette_in_rielaborazione("rettifica", "data_apertura"))
        self.assertFalse(monitoraggio.rimette_in_rielaborazione("proroga", None))

    def test_supabase_senza_la_funzione_di_b4_non_fa_niente(self):
        fonte = monitoraggio.FonteDatiSupabase(controllo=object(), client=object())
        with patch.object(db, "azzera_rielaborazione", None, create=True):
            self.assertFalse(fonte.azzera_rielaborazione(1))
        # `db.azzera_rielaborazione` risponde con un dict: conta `scritto`
        # (§18.8), non il fatto che abbia risposto.
        chiamate = []
        for risposta, atteso in (({"scritto": True}, True),
                                 ({"scritto": False, "motivo": "nessuna riga della fonte"}, False)):
            with self.subTest(risposta=risposta), \
                    patch.object(db, "azzera_rielaborazione",
                                 lambda i, _r=risposta: (chiamate.append(i), _r)[1], create=True):
                self.assertIs(fonte.azzera_rielaborazione(7), atteso)
        self.assertEqual(chiamate, [7, 7])


class TestTipiTuttiEMigrazione14(unittest.IsolatedAsyncioTestCase):
    """Giro 3, §3: con `tutti`, sospensione/revoca/annullamento solo con la 14
    applicata e `MONITOR_STATI_ESTESI` vero; altrimenti in ombra, senza allarme."""

    async def _giro(self, *, sospensioni, stati_estesi):
        dati = _FonteSenzaLimite(righe=[_riga()])
        dati.sospensioni = sospensioni
        with _patch_gate():
            return await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=eventi.TIPI_PROPONIBILI,
                                           monitor_stati_estesi=stati_estesi),
                fonte_dati=dati, scarica=_scarica, classifica=_classificatore(_faq()),
                tabella_domini={}, lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5)

    async def test_senza_la_14_restano_in_ombra(self):
        for sospensioni, estesi in ((False, True), (True, False), (False, False)):
            with self.subTest(sospensioni=sospensioni, estesi=estesi):
                esito = await self._giro(sospensioni=sospensioni, stati_estesi=estesi)
                self.assertEqual(esito["tipi_in_attesa_migrazione_14"],
                                 ["sospensione", "revoca", "annullamento_revoca"])
                for tipo in eventi.TIPI_STATI_ESTESI:
                    self.assertNotIn(tipo, esito["tipi_attivi"])
                self.assertIn("faq", esito["tipi_attivi"])
                self.assertFalse(any("migrazione" in a for a in esito["allarmi"]))

    async def test_con_la_14_e_gli_stati_estesi_tutti_attivi(self):
        esito = await self._giro(sospensioni=True, stati_estesi=True)
        self.assertEqual(esito["tipi_attivi"], list(eventi.TIPI_PROPONIBILI))
        self.assertEqual(esito["tipi_in_attesa_migrazione_14"], [])

    def test_regola_pura(self):
        attivi, attesa = eventi.tipi_attivi_effettivi(("faq", "revoca", "faq"), capacita=True,
                                                      stati_estesi=False)
        self.assertEqual((attivi, attesa), (("faq",), ("revoca",)))
        self.assertEqual(eventi.tipi_attivi_effettivi(("revoca",), capacita=True, stati_estesi=True),
                         (("revoca",), ()))


class TestGiroPerTipo(unittest.IsolatedAsyncioTestCase):
    async def _giro(self, **kw):
        dati = _FonteSenzaLimite(righe=[_riga()])
        parametri = dict(
            impostazioni=_impostazioni(monitor_tipi_attivi=TIPI), fonte_dati=dati,
            scarica=_scarica, classifica=_classificatore(_faq()), tabella_domini={},
            lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5)
        parametri.update(kw)
        with _patch_gate():
            return await monitoraggio.run(**parametri), dati

    async def test_faq_applicata_va_a_indexnow(self):
        esito, dati = await self._giro()
        self.assertEqual(esito["slug_modificati"], ["avviso-1"])
        self.assertEqual(esito["applicati_per_tipo"], {"faq": 1})
        self.assertEqual(len(dati.resi_leggibili), 1)

    async def test_ombra_esplicita_spegne_i_tipi(self):
        esito, dati = await self._giro(attivo=False)
        self.assertEqual(esito["tipi_attivi"], [])
        self.assertEqual(dati.registrati_rpc, [])
        self.assertEqual(esito["slug_modificati"], [])

    async def test_dry_run_spegne_i_tipi(self):
        esito, dati = await self._giro(dry_run=True)
        self.assertEqual(esito["tipi_attivi"], [])
        self.assertEqual(dati.registrati_rpc, [])

    async def test_valori_ignorati_fanno_allarme_a_ogni_giro(self):
        esito, _dati = await self._giro(impostazioni=_impostazioni(
            monitor_tipi_attivi=("faq",), monitor_tipi_attivi_ignorati=("profroga",)))
        self.assertTrue(any("MONITOR_TIPI_ATTIVI" in a and "profroga" in a
                            for a in esito["allarmi"]))
        self.assertEqual(esito["applicati_per_tipo"], {"faq": 1})

    async def test_senza_tipi_attivi_niente_cambia(self):
        esito, dati = await self._giro(impostazioni=_impostazioni())
        self.assertEqual(esito["tipi_attivi"], [])
        self.assertEqual(dati.registrati_rpc, [])
        self.assertEqual(len(dati.registrati), 1)
        self.assertEqual(esito["slug_modificati"], [])


class TestCorrezioniDellaRevisione(unittest.IsolatedAsyncioTestCase):
    """Revisione avversaria del 30/09/2026 (#35): non verificati, comando di
    ripresa negli allarmi, IndexNow sugli invisibili."""

    async def _controlla(self, *proposte, dati, **kw):
        with _patch_gate():
            return await monitoraggio.controlla(
                _riga(), scarica=_scarica, classifica=_classificatore(*proposte),
                fonte_dati=dati, tipi_attivi=TIPI, adesso=ADESSO, casuale=lambda: 0.5, **kw)

    async def test_non_verificato_per_il_db_resta_in_ombra(self):
        # Il G4 di Python accetta anche gli host delle fonti, il DB solo
        # `dominio_ufficiale`: applicarlo lascerebbe la colonna cambiata e
        # l'evento invisibile (il 23514 di `leggibile`).
        class _NonVerificato(monitoraggio.FonteDati):
            def evento_verificato(self, evento_id, riga):
                return False

        dati = _NonVerificato()
        esito = await self._controlla(_proroga(), dati=dati)
        self.assertEqual(len(dati.registrati_rpc), 1)       # registrato, in ombra
        self.assertEqual(dati.applicati, [])
        self.assertEqual(dati.resi_leggibili, [])
        self.assertEqual(esito.eventi_non_verificati, 1)
        self.assertEqual(esito.eventi_non_applicati, 0)     # nessun allarme di ripresa
        self.assertEqual(esito.eventi_applicati, 0)
        self.assertFalse(esito.rigenerazione_dovuta)

    async def test_nuovo_sconosciuto_resta_in_ombra(self):
        # La risposta della RPC non dice se l'evento e' nato adesso: non si
        # applica e non si rende leggibile, e non e' un'applicazione fallita.
        class _SenzaNuovo(monitoraggio.FonteDati):
            def registra_evento_rpc(self, riga):
                self.registrati_rpc.append(dict(riga))
                return {"id": 1, "nuovo": None}

        dati = _SenzaNuovo()
        esito = await self._controlla(_proroga(), dati=dati)
        self.assertEqual(dati.applicati, [])
        self.assertEqual(dati.resi_leggibili, [])
        self.assertEqual(esito.eventi_applicati, 0)
        self.assertEqual(esito.eventi_non_applicati, 0)
        self.assertIn("non dice se e' nuovo", esito.eventi[0]["motivo"])

    async def test_verificato_illeggibile_non_si_applica(self):
        class _Illeggibile(monitoraggio.FonteDati):
            def evento_verificato(self, evento_id, riga):
                return None

        dati = _Illeggibile()
        esito = await self._controlla(_faq(), dati=dati)
        self.assertEqual(dati.applicati, [])
        # In ombra come il non verificato, ma contato come errore: i due casi
        # non si confondono.
        self.assertEqual(esito.errori_verifica, 1)
        self.assertEqual(esito.eventi_non_verificati, 0)
        self.assertEqual(esito.eventi_non_applicati, 0)

    async def test_il_giro_conta_gli_errori_di_verifica(self):
        class _Illeggibile(_FonteSenzaLimite):
            def evento_verificato(self, evento_id, riga):
                return None

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI),
                fonte_dati=_Illeggibile(righe=[_riga()]), scarica=_scarica,
                classifica=_classificatore(_faq()), tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito["errori_verifica"], 1)
        self.assertEqual(esito["eventi_non_verificati"], 0)
        self.assertEqual(esito["slug_modificati"], [])

    def test_verificato_letto_dal_db(self):
        chiamate = []

        def select_eventi(**kw):
            chiamate.append(kw)
            return [{"id": 3, "verificato": False}, {"id": 4, "verificato": True}]

        fonte = monitoraggio.FonteDatiSupabase(controllo=object(), client=object())
        riga = {"bando_id": 7, "tipo": "proroga"}
        with patch.object(db, "select_eventi", select_eventi):
            self.assertTrue(fonte.evento_verificato(4, riga))
            self.assertFalse(fonte.evento_verificato(3, riga))
            self.assertIsNone(fonte.evento_verificato(5, riga))
        # Per id, il filtro esatto (correzione finale del 30/09/2026).
        self.assertEqual([tuple(c["ids"]) for c in chiamate], [(4,), (3,), (5,)])
        self.assertEqual(tuple(chiamate[0]["colonne"]), ("id", "verificato"))
        self.assertNotIn("bando_id", chiamate[0])

    async def test_l_allarme_dice_gli_id(self):
        class _Rifiuta(monitoraggio.FonteDati):
            def applica_evento(self, evento_id):
                return db.ESITO_RIFIUTATO

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI),
                fonte_dati=type("F", (_Rifiuta, _FonteSenzaLimite), {})(righe=[_riga()]),
                scarica=_scarica, classifica=_classificatore(_proroga()), tabella_domini={},
                lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5)
        (allarme,) = [a for a in esito["allarmi"] if "non applicati" in a]
        # Il filtro esatto: per tipo e giorno prenderebbe anche l'arretrato
        # dell'ombra (T-D5, revisione avversaria del 30/09/2026).
        self.assertIn("applica-eventi --ids 1 --attivo", allarme)
        self.assertNotIn("--tipo", allarme)

    def test_senza_id_si_ripiega_sul_tipo_con_dry_run(self):
        # Il monitor attivo del rilascio 2 non restituisce l'id qui.
        comando = monitoraggio._comando_di_ripresa([7, None], ["proroga", "faq"],
                                                   ADESSO.date())
        self.assertIn("applica-eventi --tipo faq,proroga --dal 2026-09-23 --dry-run", comando)
        self.assertEqual(monitoraggio._comando_di_ripresa([7, 3], ["faq"], ADESSO.date()),
                         "applica-eventi --ids 3,7 --attivo")

    async def test_faq_invisibile_non_va_a_indexnow(self):
        class _SenzaLeggibile(_FonteSenzaLimite):
            def rendi_leggibile(self, evento_id, *, in_aggiornamenti=True):
                return False

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI),
                fonte_dati=_SenzaLeggibile(righe=[_riga()]), scarica=_scarica,
                classifica=_classificatore(_faq()), tabella_domini={}, lock=_lock_libero(),
                adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito["eventi_invisibili"], 1)
        self.assertEqual(esito["slug_modificati"], [])
        self.assertTrue(any("applica-eventi --ids 1 --attivo" in a
                            for a in esito["allarmi"]))

    async def test_applica_eventi_con_gli_id_filtra_esatto(self):
        # Il comando di ripresa: la selezione passa gli id a `select_eventi`,
        # sia per gli eventi da applicare sia per gli invisibili da riparare.
        chiamate = []

        def select_eventi(**kw):
            chiamate.append(kw)
            return []

        with patch.object(db, "select_eventi", select_eventi), \
                patch.object(monitoraggio, "_capacita_eventi", lambda: (True, True)), \
                patch.object(monitoraggio, "eventi_gia_rifiutati", lambda: frozenset()):
            esito = await monitoraggio.run_applica_eventi(
                attivo=True, ids=(12, 13), impostazioni=_impostazioni(), lock=_lock_libero())
        self.assertEqual(esito["ids"], [12, 13])
        self.assertTrue(chiamate)
        for kw in chiamate:
            self.assertEqual(tuple(kw["ids"]), (12, 13))

    async def test_proroga_invisibile_con_prosa_riscritta_va_a_indexnow(self):
        # La colonna e la prosa sono cambiate: la pagina e' diversa anche se il
        # box non mostra l'evento.
        class _SenzaLeggibile(_FonteSenzaLimite):
            def rendi_leggibile(self, evento_id, *, in_aggiornamenti=True):
                return False

        async def rigenera(*a, **k):
            return {"scritto": True, "via": "llm"}

        with _patch_gate():
            esito = await monitoraggio.run(
                impostazioni=_impostazioni(monitor_tipi_attivi=TIPI),
                fonte_dati=_SenzaLeggibile(righe=[_riga()]), scarica=_scarica,
                classifica=_classificatore(_proroga()), rigenerazione=rigenera,
                tabella_domini={}, lock=_lock_libero(), adesso=ADESSO, casuale=lambda: 0.5)
        self.assertEqual(esito["slug_modificati"], ["avviso-1"])


class TestSaluteStampaITipi(unittest.TestCase):
    """`salute` dice quali tipi il monitor applica anche in ombra (§3)."""

    def setUp(self):
        self.cli = carica_modulo("__main__")
        self.settings = carica_modulo("settings")
        self.telemetria = carica_modulo("telemetria")

    def _esegui(self, argv, stato):
        import contextlib
        import io
        from unittest.mock import MagicMock
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.cli, "_stato_salute", return_value=stato), \
                patch.object(self.cli, "logger", MagicMock()), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            codice = self.cli.main(argv)
        return codice, stdout.getvalue(), stderr.getvalue()

    def test_i_tipi_attivi_si_stampano(self):
        codice, stdout, _ = self._esegui(
            ["salute"], self.telemetria.Stato(tipi_attivi=TIPI))
        self.assertEqual(codice, 0)
        self.assertIn("salute: tipi attivi del monitor: "
                      "faq, nuovo_allegato, graduatoria, esito, proroga", stdout)
        self.assertIn("nessun allarme", stdout)

    def test_nessun_tipo_attivo(self):
        _codice, stdout, _ = self._esegui(["salute"], self.telemetria.Stato())
        self.assertIn("salute: tipi attivi del monitor: nessuno", stdout)

    def test_valori_ignorati_allarme_ed_exit_1(self):
        codice, _stdout, stderr = self._esegui(["salute"], self.telemetria.Stato(
            tipi_attivi=("faq",), tipi_attivi_ignorati=("profroga",)))
        self.assertEqual(codice, 1)
        self.assertIn("profroga", stderr)

    def test_json(self):
        import json
        _codice, stdout, _ = self._esegui(
            ["salute", "--json"], self.telemetria.Stato(tipi_attivi=("faq",)))
        self.assertEqual(json.loads(stdout)["tipi_attivi"], ["faq"])

    def test_lo_stato_legge_le_impostazioni(self):
        from dataclasses import replace
        db = carica_modulo("db")
        impostazioni = replace(
            self.settings.get_settings(), monitor_tipi_attivi=("faq", "proroga"),
            monitor_tipi_attivi_ignorati=("profroga",))
        with patch.object(self.settings, "get_settings", return_value=impostazioni), \
                patch.object(db, "misure_salute", side_effect=ConnectionError("giu'")):
            stato = self.cli._stato_salute()
        self.assertEqual(stato.tipi_attivi, ("faq", "proroga"))
        self.assertEqual(stato.tipi_attivi_ignorati, ("profroga",))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
