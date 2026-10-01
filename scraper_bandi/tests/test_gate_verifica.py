# -*- coding: utf-8 -*-
"""Gate e proposte del percorso verifica_stato (contratto `bandi-giro-2` §5.5, §5.6, §4, §19.4).

  - `valuta_verifica`: G1, G2v, G3v, G5, G6, G7e, G8, G9, G10, tutti obbligatori;
  - G7e: doppia lettura strutturata ad almeno 60 ore, stesso estrattore, stesso
    url finale normalizzato, stessa etichetta e, per le date, stessa data;
  - il modello non produce mai una chiusura; il generico non produce mai eventi;
  - `proposte_verifica`: ramo per ramo, con `in_aggiornamenti` solo per le notizie;
  - dalla pagina vera alla proposta ammessa, sulle fixture del #73.

Funzioni pure: nessuna rete, nessun DB.
"""
import json
import unittest
from datetime import date, datetime, time, timedelta, timezone

from tests.supporto import RADICE, carica_modulo

ev = carica_modulo("eventi")
es = carica_modulo("etichette_stato")
scarico = carica_modulo("scarico")

ADESSO = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
OGGI = date(2026, 10, 1)
#: Un host verificabile anche con il solo seed (pattern `regione.*.it`).
URL = "https://www.bandi.regione.lombardia.it/servizi/servizio/catalogo/dettaglio/x-RLO1"
TESTO = ("Stato: Chiuso. Il bando è chiuso. Scade il: 25/07/2025, ore 12:00. "
         "Domande entro il 30/10/2026. Data chiusura 23/6/2026. Data presunta di scadenza: 30/11/2026.")
FIXTURE = RADICE / "tests" / "fixtures" / "etichette_stato"
INDICE = json.loads((FIXTURE / "indice.json").read_text(encoding="utf-8"))


def _lettura(ore_fa=0, *, estrattore="lombardia", url=URL, etichetta="Chiuso", stato="chiuso", date_=()):
    return ev.LetturaStato(ADESSO - timedelta(hours=ore_fa), estrattore, url, etichetta, stato, tuple(date_))


def _ctx(**kwargs):
    base = dict(bando_id=1, stato="aperto", pagina_tipo="i", url_finale=URL, testo_pagina=TESTO,
                livello_titolo="alto", lettura=_lettura(), storia=(_lettura(61),), adesso=ADESSO)
    base.update(kwargs)
    return ev.ContestoVerifica(**base)


def _chiusura(**kwargs):
    base = dict(tipo="chiusura", ramo="A", citazione="Chiuso", url_prova=URL, metodo="estrattore:lombardia",
                valore_dopo={"stato_bando": "chiuso"}, etichetta="Chiuso")
    base.update(kwargs)
    return ev.Proposta(**base)


def _rettifica(data=date(2026, 10, 30), citazione="Domande entro il 30/10/2026", **kwargs):
    base = dict(tipo="rettifica", ramo="A", citazione=citazione, url_prova=URL, metodo="estrattore:lombardia",
                campo="data_scadenza", valore_dopo={"data_scadenza": data.isoformat()})
    base.update(kwargs)
    return ev.Proposta(**base)


def _falliti(proposta, ctx):
    return {g: m for g, m in ev.valuta_verifica(proposta, ctx).falliti}


class TestAmmessa(unittest.TestCase):
    def test_chiusura_con_doppia_lettura_ammessa(self):
        giudizio = ev.valuta_verifica(_chiusura(), _ctx())
        self.assertTrue(giudizio.ammesso, giudizio.motivo)
        self.assertEqual(giudizio.nuovo_stato, "chiuso")
        self.assertEqual(giudizio.gate, "G2v")
        self.assertEqual(set(giudizio.superati),
                         {"G1", "G2v", "G3v", "G5", "G6", "G7e", "G8", "G9", "G10"})

    def test_formato_del_p_gate(self):
        giudizio = ev.valuta_verifica(_chiusura(), _ctx(storia=()))
        gate = ev.gate_verifica(giudizio, _chiusura())
        self.assertEqual(gate["percorso"], "verifica_stato")
        self.assertEqual(gate["g7"], "doppia_lettura_strutturata")
        self.assertEqual(gate["falliti"][0]["gate"], "G7e")
        self.assertIn("G1", gate["superati"])
        modello = _rettifica(metodo="modello")
        self.assertEqual(ev.gate_verifica(ev.valuta_verifica(modello, _ctx()), modello)["g7"], "doppio_modello")


class TestG7e(unittest.TestCase):
    def test_una_sola_lettura(self):
        self.assertIn("una sola lettura", _falliti(_chiusura(), _ctx(storia=()))["G7e"])

    def test_confine_delle_60_ore(self):
        self.assertIn("G7e", _falliti(_chiusura(), _ctx(storia=(_lettura(59),))))
        self.assertNotIn("G7e", _falliti(_chiusura(), _ctx(storia=(_lettura(61),))))
        self.assertNotIn("G7e", _falliti(_chiusura(), _ctx(storia=(_lettura(60),))))

    def test_url_etichetta_estrattore_diversi(self):
        casi = {
            "url diverso": _lettura(61, url=URL + "-altro"),
            "etichetta diversa": _lettura(61, etichetta="Aperto", stato="aperto"),
        }
        for motivo, precedente in casi.items():
            with self.subTest(motivo=motivo):
                self.assertIn(motivo, _falliti(_chiusura(), _ctx(storia=(precedente,)))["G7e"])
        self.assertIn("una sola lettura", _falliti(_chiusura(), _ctx(storia=(_lettura(61, estrattore="toscana"),)))["G7e"])

    def test_conta_l_ultima_lettura_senza_discordanti_in_mezzo(self):
        # Revisione del #74: Chiuso t0, Aperto t1, Chiuso t2 → non passa.
        oscillante = (_lettura(96), _lettura(40, etichetta="Aperto", stato="aperto"))
        self.assertIn("etichetta diversa", _falliti(_chiusura(), _ctx(storia=oscillante))["G7e"])
        # Due letture concordi di fila, la piu' vecchia a 96 h: passa anche con una a 24 h in mezzo.
        concordi = (_lettura(96), _lettura(24))
        self.assertNotIn("G7e", _falliti(_chiusura(), _ctx(storia=concordi)))
        # Solo letture concordi recenti: non basta.
        self.assertIn("meno di 60 h", _falliti(_chiusura(), _ctx(storia=(_lettura(30), _lettura(10))))["G7e"])
        # Una lettura su un altro url non interrompe la catena dell'url letto.
        altro_url = (_lettura(96), _lettura(40, url=URL + "-altro", etichetta="Aperto", stato="aperto"))
        self.assertNotIn("G7e", _falliti(_chiusura(), _ctx(storia=altro_url)))

    def test_url_normalizzato_uguale(self):
        precedente = _lettura(61, url=URL.replace("https://www.", "https://") + "/#stato")
        self.assertNotIn("G7e", _falliti(_chiusura(), _ctx(storia=(precedente,))))

    def test_per_le_date_serve_la_stessa_data(self):
        data = date(2026, 10, 30)
        attuale = _lettura(etichetta="Aperto", stato="aperto", date_=[("scadenza", data)])
        stessa = _lettura(61, etichetta="Aperto", stato="aperto", date_=[("scadenza", data)])
        diversa = _lettura(61, etichetta="Aperto", stato="aperto", date_=[("scadenza", date(2026, 11, 30))])
        self.assertNotIn("G7e", _falliti(_rettifica(data), _ctx(lettura=attuale, storia=(stessa,))))
        self.assertIn("data diversa", _falliti(_rettifica(data), _ctx(lettura=attuale, storia=(diversa,)))["G7e"])

    def test_il_modello_non_chiude_mai(self):
        motivo = _falliti(_chiusura(metodo="modello"), _ctx())["G7e"]
        self.assertIn("il modello non produce mai chiusura", motivo)

    def test_una_data_del_modello_vuole_il_g7_doppio(self):
        self.assertIn("G7e", _falliti(_rettifica(metodo="modello"), _ctx()))

    def test_il_generico_non_produce_eventi(self):
        proposta = _chiusura(metodo="estrattore:generico")
        ctx = _ctx(lettura=_lettura(estrattore="generico"), storia=(_lettura(61, estrattore="generico"),))
        self.assertIn("generico", _falliti(proposta, ctx)["G7e"])


class TestAltriGate(unittest.TestCase):
    def test_g1_citazione(self):
        self.assertIn("G1", _falliti(_chiusura(citazione="Bando chiuso per esaurimento"), _ctx()))
        self.assertIn("G1", _falliti(_chiusura(citazione=""), _ctx()))

    def test_g2v_tipo_di_pagina_e_host(self):
        for tipo in ("iv", "illeggibile"):
            self.assertIn("G2v", _falliti(_chiusura(), _ctx(pagina_tipo=tipo)))
        for tipo in ("i", "ii", "ii-c", "iii"):
            self.assertNotIn("G2v", _falliti(_chiusura(), _ctx(pagina_tipo=tipo)))
        aggregatore = "https://www.obiettivoeuropa.com/bandi/x"
        self.assertIn("G2v", _falliti(_chiusura(url_prova=aggregatore), _ctx(url_finale=aggregatore)))

    def test_g3v_titolo(self):
        self.assertIn("G3v", _falliti(_chiusura(), _ctx(livello_titolo="basso")))
        self.assertIn("G3v", _falliti(_chiusura(), _ctx(livello_titolo=None)))
        self.assertNotIn("G3v", _falliti(_chiusura(), _ctx(livello_titolo="medio")))

    def test_g5_direzione(self):
        self.assertIn("G5", _falliti(_chiusura(data_evento=date(2026, 10, 2)), _ctx()))
        self.assertNotIn("G5", _falliti(_chiusura(data_evento=date(2025, 7, 25)), _ctx()))
        self.assertIn("G5", _falliti(_chiusura(tipo="proroga"), _ctx()))

    def test_g5_data_verificata(self):
        scadenza = ev.Proposta("data_verificata", "I", "Domande entro il 30/10/2026", URL,
                               "estrattore:lombardia", campo="data_scadenza",
                               valore_dopo={"data_scadenza": "2026-10-30"})
        self.assertIn("gia' verificata", _falliti(scadenza, _ctx(scadenza_verificata=True))["G5"])
        apertura = ev.Proposta("data_verificata", "I", "Domande dal 1/9/2026", URL, "estrattore:lombardia",
                               campo="data_apertura", valore_dopo={"data_apertura": "2026-09-01"})
        self.assertIn("apertura passata", _falliti(apertura, _ctx(stato="in apertura prossimamente"))["G5"])
        insieme = _ctx(stato="in apertura prossimamente", proposte_insieme=(scadenza,))
        self.assertNotIn("G5", _falliti(apertura, insieme))

    def test_g6_parola(self):
        self.assertIn("G6", _falliti(_chiusura(citazione="Stato:"), _ctx()))
        self.assertNotIn("G6", _falliti(_chiusura(citazione="Il bando è chiuso"), _ctx()))

    def test_g6_invitalia_data_chiusura(self):
        # Decisione del lead: «chius» vale per la data di scadenza solo da un
        # lettore strutturato e solo nel percorso verifica.
        citazione = "Data chiusura 23/6/2026"
        strutturata = _rettifica(date(2026, 6, 23), citazione, metodo="estrattore:invitalia")
        self.assertEqual(ev.gv6_parola(strutturata, _ctx()), (True, ""))
        dal_modello = _rettifica(date(2026, 6, 23), citazione, metodo="modello")
        self.assertFalse(ev.gv6_parola(dal_modello, _ctx())[0])
        # Il monitor non cambia: la stessa citazione non passa il suo G6.
        self.assertFalse(ev.g6_parola(ev.Evento("rettifica", citazione, campo="data_scadenza",
                                               valore="2026-06-23"), ev.Contesto())[0])

    def test_g8_dedup_col_tipo_vero(self):
        recenti = ({"tipo": "chiusura", "campo": None, "valore_dopo": {"stato_bando": "chiuso"},
                    "data_evento": "2026-09-20"},)
        self.assertIn("G8", _falliti(_chiusura(), _ctx(eventi_recenti=recenti)))
        verificata = ev.Proposta("data_verificata", "I", "Domande entro il 30/10/2026", URL,
                                 "estrattore:lombardia", campo="data_scadenza",
                                 valore_dopo={"data_scadenza": "2026-10-30"})
        gia = ({"tipo": "data_verificata", "campo": "data_scadenza",
                "valore_dopo": {"data_scadenza": "2026-10-30"}, "data_evento": "2026-09-28"},)
        self.assertIn("G8", _falliti(verificata, _ctx(eventi_recenti=gia)))
        rettifica = ({"tipo": "rettifica", "campo": "data_scadenza",
                      "valore_dopo": {"data_scadenza": "2026-10-30"}, "data_evento": "2026-09-28"},)
        self.assertNotIn("G8", _falliti(verificata, _ctx(eventi_recenti=rettifica)))

    def test_g8_finestra_su_rilevato_at(self):
        # Una chiusura registrata 2 giorni fa con data_evento il termine letto
        # (2025-07-25): nel percorso verifica conta quando e' stata registrata.
        recenti = ({"tipo": "chiusura", "campo": None, "valore_dopo": {"stato_bando": "chiuso"},
                    "data_evento": "2025-07-25", "rilevato_at": (ADESSO - timedelta(days=2)).isoformat()},)
        self.assertIn("G8", _falliti(_chiusura(), _ctx(eventi_recenti=recenti)))
        # Registrata 40 giorni fa: fuori finestra.
        vecchia = ({**recenti[0], "rilevato_at": (ADESSO - timedelta(days=40)).isoformat()},)
        self.assertNotIn("G8", _falliti(_chiusura(), _ctx(eventi_recenti=vecchia)))
        # Il G8 del monitor resta su data_evento.
        evento = ev.Evento("chiusura", "Chiuso", URL)
        self.assertTrue(ev.g8_dedup(evento, ev.Contesto(eventi_recenti=recenti, oggi=OGGI))[0])

    def test_g9_dallo_stato_riletto(self):
        # Riga 24: da «in apertura» il worker chiude, solo con il percorso verifica.
        self.assertNotIn("G9", _falliti(_chiusura(ramo="I"), _ctx(stato="in apertura prossimamente")))
        self.assertEqual(ev.valuta_verifica(_chiusura(ramo="I"), _ctx(stato="in apertura prossimamente"))
                         .nuovo_stato, "chiuso")
        # Gia' chiuso nel frattempo: nessuna transizione, niente da dire.
        self.assertIsNone(ev.valuta_verifica(_chiusura(), _ctx(stato="chiuso")).nuovo_stato)

    def test_g10_data_presunta(self):
        proposta = _rettifica(date(2026, 11, 30), "Data presunta di scadenza: 30/11/2026")
        self.assertIn("G10", _falliti(proposta, _ctx()))


class TestTransizioneEvento(unittest.TestCase):
    def test_chiusura_da_in_apertura_solo_col_percorso_verifica(self):
        chiusura = ev.Evento("chiusura")
        self.assertIsNone(ev.transizione_evento("in apertura prossimamente", chiusura))
        self.assertIsNone(ev.transizione_evento("in apertura prossimamente", chiusura, percorso="monitor"))
        self.assertEqual(ev.transizione_evento("in apertura prossimamente", chiusura,
                                               percorso="verifica_stato"), "chiuso")
        self.assertEqual(ev.transizione_evento("aperto", chiusura), "chiuso")


def _lettura_es(estrattore, stato, *, etichetta="Chiuso", puo_chiudere=False, solo_segnale=False,
                termine=None, date_=()):
    return es.Lettura(estrattore, stato, etichetta, puo_chiudere=puo_chiudere, solo_segnale=solo_segnale,
                      termine_finale=termine, date=tuple(date_), citazione_stato=etichetta)


class TestProposte(unittest.TestCase):
    def _ctx(self, **kwargs):
        return _ctx(lettura=None, storia=(), **kwargs)

    def test_ramo_a(self):
        passato = es.TermineFinale(date(2025, 7, 25), time(12, 0), "Scade il: 25/07/2025, ore 12:00")
        futuro = es.TermineFinale(date(2027, 1, 19), time(12, 0), "entro e non oltre le ore 12 del 19/01/2027")
        casi = [
            # 18344: «Chiuso» con puo_chiudere e il termine passato → chiusura datata.
            (_lettura_es("lombardia", "chiuso", puo_chiudere=True, termine=passato),
             [("chiusura", None, date(2025, 7, 25))]),
            # 2387: «Chiuso» senza termine → chiusura senza data.
            (_lettura_es("lazioeuropa", "chiuso", puo_chiudere=True), [("chiusura", None, None)]),
            # 2339: aperto con un termine futuro → rettifica.
            (_lettura_es("formazionelavoro_er", "aperto", etichetta="Bando Aperto", termine=futuro),
             [("rettifica", "data_scadenza", None)]),
            # 256211: chiuso per date (puo_chiudere falso) → rettifica con la data passata.
            (_lettura_es("fesr_er", "chiuso", etichetta="In corso", termine=passato),
             [("rettifica", "data_scadenza", None)]),
            (_lettura_es("lombardia", "aperto", etichetta="Aperto"), []),
            (_lettura_es("calabria", "chiuso", etichetta="Valutazione", solo_segnale=True), []),
            (_lettura_es("generico", "chiuso", etichetta="Bando chiuso", solo_segnale=True), []),
        ]
        for lettura, attese in casi:
            with self.subTest(estrattore=lettura.estrattore, etichetta=lettura.etichetta):
                proposte = ev.proposte_verifica("A", lettura, self._ctx())
                self.assertEqual([(p.tipo, p.campo, p.data_evento) for p in proposte], attese)
        rettifica = ev.proposte_verifica("A", casi[2][0], self._ctx())[0]
        self.assertEqual(rettifica.valore_dopo, {"data_scadenza": "2027-01-19", "ora_scadenza": "12:00"})
        self.assertEqual(rettifica.metodo, "estrattore:formazionelavoro_er")

    def test_ramo_i(self):
        passato = es.TermineFinale(date(2026, 8, 10), time(12, 0), "entro le ore 12:00 del 10 agosto 2026")
        futuro = es.TermineFinale(date(2026, 10, 29), time(17, 0), "entro le ore 17:00 del 29 ottobre 2026")
        # 2375: chiuso con la scadenza passata → solo data_verificata, poi chiude il cron.
        proposte = ev.proposte_verifica("I", _lettura_es("lazioeuropa", "chiuso", puo_chiudere=True,
                                                         termine=passato), self._ctx(stato="in apertura prossimamente"))
        self.assertEqual([(p.tipo, p.campo) for p in proposte], [("data_verificata", "data_scadenza")])
        self.assertFalse(proposte[0].in_aggiornamenti)
        # Chiuso senza date → chiusura (riga 24).
        proposte = ev.proposte_verifica("I", _lettura_es("lazioeuropa", "chiuso", puo_chiudere=True),
                                        self._ctx(stato="in apertura prossimamente"))
        self.assertEqual([p.tipo for p in proposte], ["chiusura"])
        # 1072674: aperto con la scadenza futura → data_verificata e apertura.
        proposte = ev.proposte_verifica("I", _lettura_es("lazioeuropa", "aperto", etichetta="Aperto",
                                                         termine=futuro), self._ctx(stato="in apertura prossimamente"))
        self.assertEqual([p.tipo for p in proposte], ["data_verificata", "apertura"])
        # Scadenza gia' verificata: non si ripropone.
        proposte = ev.proposte_verifica("I", _lettura_es("lazioeuropa", "aperto", etichetta="Aperto",
                                                         termine=futuro),
                                        self._ctx(stato="in apertura prossimamente", scadenza_verificata=True))
        self.assertEqual([p.tipo for p in proposte], ["apertura"])
        # In apertura senza date: niente.
        self.assertEqual(ev.proposte_verifica("I", _lettura_es("puglia", "in_apertura", etichetta="Prossimo avvio"),
                                              self._ctx()), [])

    def test_notizia_o_correzione(self):
        lettura = _lettura_es("lombardia", "chiuso", puo_chiudere=True)
        aperta = _lettura(10 * 24, etichetta="Aperto", stato="aperto")
        chiusa = _lettura(3 * 24)
        # Una lettura «aperto» 7 giorni prima della prima chiusura: notizia.
        ctx = _ctx(lettura=_lettura(), storia=(aperta, chiusa))
        self.assertTrue(ev.proposte_verifica("A", lettura, ctx)[0].in_aggiornamenti)
        # Mai visto aperto: correzione (la prima passata sui 44 «Chiuso» di LazioEuropa).
        self.assertFalse(ev.proposte_verifica("A", lettura, _ctx(lettura=_lettura(), storia=(chiusa,)))[0]
                         .in_aggiornamenti)
        # Aperto piu' di 30 giorni prima della prima chiusura: correzione.
        vecchia = _lettura(40 * 24, etichetta="Aperto", stato="aperto")
        self.assertFalse(ev.proposte_verifica("A", lettura, _ctx(lettura=_lettura(), storia=(vecchia, chiusa)))[0]
                         .in_aggiornamenti)

    def test_retroattivita_oltre_quattordici_giorni(self):
        aperta = _lettura(10 * 24, etichetta="Aperto", stato="aperto")
        ctx = _ctx(lettura=_lettura(), storia=(aperta,))
        vecchia = es.TermineFinale(OGGI - timedelta(days=20), None, "Scade il: 11/09/2026")
        recente = es.TermineFinale(OGGI - timedelta(days=5), None, "Scade il: 26/09/2026")
        self.assertFalse(ev.proposte_verifica("A", _lettura_es("lombardia", "chiuso", puo_chiudere=True,
                                                               termine=vecchia), ctx)[0].in_aggiornamenti)
        self.assertTrue(ev.proposte_verifica("A", _lettura_es("lombardia", "chiuso", puo_chiudere=True,
                                                              termine=recente), ctx)[0].in_aggiornamenti)


class TestRigaVerifica(unittest.TestCase):
    def test_ombra_e_attivo(self):
        proposta = _chiusura(in_aggiornamenti=True, data_evento=date(2025, 7, 25))
        ctx = _ctx()
        giudizio = ev.valuta_verifica(proposta, ctx)
        ombra = ev.riga_verifica(proposta, ctx, giudizio)
        self.assertEqual((ombra["leggibile"], ombra["in_aggiornamenti"], ombra["applicato"]), (False, False, False))
        attivo = ev.riga_verifica(proposta, ctx, giudizio, modalita="attivo")
        self.assertEqual((attivo["leggibile"], attivo["in_aggiornamenti"]), (True, True))
        self.assertEqual(attivo["valore_dopo"], {"stato_bando": "chiuso"})
        self.assertEqual(attivo["valore_prima"], {"stato_bando": "aperto"})
        self.assertEqual(attivo["data_evento"], "2025-07-25")
        self.assertEqual(attivo["metodo"], "estrattore:lombardia")
        self.assertEqual(attivo["origine"], "worker")
        self.assertEqual(attivo["gate"]["percorso"], "verifica_stato")
        self.assertIsInstance(attivo["confidenza"], int)
        # I parametri della RPC si ricavano come per il monitor.
        parametri = ev.parametri_registra_evento(attivo)
        self.assertEqual(parametri["p_metodo"], "estrattore:lombardia")
        self.assertEqual(parametri["p_gate"]["g7"], "doppia_lettura_strutturata")

    def test_chiusura_senza_data_e_rettifica_col_giorno(self):
        ctx = _ctx()
        riga = ev.riga_verifica(_chiusura(), ctx, ev.valuta_verifica(_chiusura(), ctx))
        self.assertIsNone(riga["data_evento"])
        rettifica = _rettifica()
        riga = ev.riga_verifica(rettifica, ctx, ev.valuta_verifica(rettifica, ctx))
        self.assertEqual(riga["data_evento"], "2026-10-01")
        self.assertEqual(riga["valore_prima"], {"data_scadenza": None})


class TestStoria(unittest.TestCase):
    def test_voce_andata_e_ritorno(self):
        lettura = _lettura(date_=[("scadenza", date(2026, 10, 30))])
        voce = lettura.come_voce()
        self.assertEqual(ev.LetturaStato.da(voce), lettura)
        self.assertEqual(ev.LetturaStato.da(json.loads(json.dumps(voce))), lettura)

    def test_forme_tollerate(self):
        voce = {"at": "2026-09-28T10:00:00.12345Z", "estrattore": "lombardia", "url": URL,
                "etichetta": "Chiuso", "stato": "chiuso", "date": {"scadenza": "2026-10-30"}}
        letta = ev.LetturaStato.da(voce)
        self.assertEqual(letta.date, (("scadenza", date(2026, 10, 30)),))
        self.assertEqual(letta.at, datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc))
        self.assertIsNone(ev.LetturaStato.da({"estrattore": "x"}))
        self.assertIsNone(ev.LetturaStato.da("x"))


class TestDallaPaginaVera(unittest.TestCase):
    """Fixture del #73: lettore → proposta → gate, con la lettura di tre giorni prima uguale."""

    def _giro(self, nome, ramo, stato):
        html = (FIXTURE / nome).read_text(encoding="utf-8")
        url = INDICE[nome]["url"]
        lettura = es.leggi(html, url, "", oggi=OGGI)
        attuale = ev.LetturaStato(ADESSO, lettura.estrattore, url, lettura.etichetta, lettura.stato,
                                  tuple((d.ruolo, d.data) for d in lettura.date))
        precedente = ev.LetturaStato(ADESSO - timedelta(hours=72), attuale.estrattore, attuale.url,
                                     attuale.etichetta, attuale.stato, attuale.date)
        ctx = ev.ContestoVerifica(
            bando_id=INDICE[nome]["bando_id"], stato=stato, pagina_tipo="i", url_finale=url,
            testo_pagina=scarico.testo_da_html(html), livello_titolo="alto",
            lettura=attuale, storia=(precedente,), adesso=ADESSO,
            tabella_domini=carica_modulo("dominio_ufficiale").costruisci(fonti=[{"link": url}]))
        proposte = ev.proposte_verifica(ramo, lettura, ctx)
        return [(p.tipo, p.campo, ev.valuta_verifica(p, ctx)) for p in proposte]

    def test_lombardia_18344_chiusura_ammessa(self):
        esiti = self._giro("lombardia_chiuso_18344.html", "A", "aperto")
        self.assertEqual([(t, c) for t, c, _ in esiti], [("chiusura", None)])
        self.assertTrue(esiti[0][2].ammesso, esiti[0][2].motivo)

    def test_formazionelavoro_2339_rettifica_ammessa(self):
        esiti = self._giro("formazionelavoro_aperto_2339.html", "A", "aperto")
        self.assertEqual([(t, c) for t, c, _ in esiti], [("rettifica", "data_scadenza")])
        self.assertTrue(esiti[0][2].ammesso, esiti[0][2].motivo)

    def test_lazioeuropa_106753_data_verificata_con_la_frase_della_pagina(self):
        # Il termine arriva senza citazione: la proposta prende la frase dalla pagina.
        esiti = self._giro("lazioeuropa_chiuso_106753.html", "I", "in apertura prossimamente")
        self.assertEqual([(t, c) for t, c, _ in esiti], [("data_verificata", "data_scadenza")])
        self.assertTrue(esiti[0][2].ammesso, esiti[0][2].motivo)

    def test_invitalia_17868_chiusura(self):
        esiti = self._giro("invitalia_chiuso_17868.html", "A", "aperto")
        self.assertEqual([(t, c) for t, c, _ in esiti], [("chiusura", None)])
        self.assertTrue(esiti[0][2].ammesso, esiti[0][2].motivo)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
