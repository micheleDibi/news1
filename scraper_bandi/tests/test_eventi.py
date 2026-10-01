# -*- coding: utf-8 -*-
"""`eventi.py`: i nove gate, la tabella delle transizioni, A30, i doppioni.

Ogni gate ha almeno un caso che passa e un contro-esempio che **deve** cadere:
un gate che non respinge niente e' un gate che non c'e'. I contro-esempi sono
quelli nominati dal piano (§6.2, §4):

  * G1  una citazione che il modello ha riassunto invece di copiare;
  * G2  una citazione che sta nella pagina ma non fra le righe aggiunte;
  * G2' una data che era gia' in colonna (o gia' nel testo precedente);
  * G3  la data di un decreto citato («ai sensi del DD 12 del 18/09/2026»);
  * G4  un href visto nell'HTML ma mai scaricato, e un aggregatore;
  * G5  la proroga di uno dei 416 bandi a sportello (vecchia scadenza NULL);
  * G6  una citazione senza la parola chiave del tipo;
  * G7  `modified` offerto come seconda prova (non vale mai);
  * G8  lo stesso evento due giri di fila;
  * G9  una transizione fuori dalla macchina a stati.

Nessuna rete, nessun modello: `valuta()` e' pura e `applica()` riceve la RPC.
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

eventi = carica_modulo("eventi")
impronte = carica_modulo("impronte")
dominio_ufficiale = carica_modulo("dominio_ufficiale")
stato_bando = carica_modulo("stato_bando")

OGGI = date(2026, 9, 23)
URL = "https://www.lazioeuropa.it/bandi/psicologia-scolastica/"
URL_AGGREGATORE = "https://www.obiettivoeuropa.com/bandi/psicologia-scolastica/"

# Tabella dei domini con l'ente del caso reale: senza, G4 respingerebbe tutto
# (lazioeuropa.it non e' nel seed compilato nel codice).
TABELLA = dominio_ufficiale.Tabella(
    dominio_ufficiale.SEED + (
        dominio_ufficiale.Dominio(host="lazioeuropa.it", tipo="ente", confidenza=0.95),
    )
)

TESTO_PRIMA = (
    "Avviso pubblico Psicologia scolastica.\n"
    "Le domande possono essere presentate entro il 6 ottobre 2026.\n"
)
TESTO_DOPO = (
    "Avviso pubblico Psicologia scolastica.\n"
    "Con determinazione DD 12 del 18/09/2026 e' stato disposto il differimento "
    "dei termini: le domande si presentano dal 22 ottobre al 1° dicembre 2026.\n"
)
CITAZIONE = (
    "differimento dei termini: le domande si presentano "
    "dal 22 ottobre al 1° dicembre 2026"
)


def _pagina(url=URL, testo=TESTO_DOPO, impronta="imp-1", collegata=False):
    return eventi.Pagina(url=url, testo=testo, impronta=impronta, collegata=collegata)


def _ctx(**extra):
    base = dict(
        bando_id=905315,
        stato_bando="aperto",
        data_scadenza=date(2026, 10, 6),
        pagine=(_pagina(),),
        diff=impronte.diff_sezioni(TESTO_PRIMA, TESTO_DOPO, oggi=OGGI),
        testo_prima=TESTO_PRIMA,
        tabella_domini=TABELLA,
        oggi=OGGI,
    )
    base.update(extra)
    return eventi.Contesto(**base)


def _proroga(**extra):
    base = dict(
        tipo="proroga",
        campo="data_scadenza",
        valore="2026-12-01",
        citazione=CITAZIONE,
        url_prova=URL,
    )
    base.update(extra)
    return eventi.Evento(**base)


class TestG1(unittest.TestCase):
    def test_citazione_sottostringa(self):
        self.assertTrue(eventi.g1_citazione(_proroga(), _ctx())[0])

    def test_citazione_riassunta_respinta(self):
        evento = _proroga(citazione="i termini sono stati prorogati a dicembre")
        ok, motivo = eventi.g1_citazione(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("nessuna pagina", motivo)

    def test_citazione_vuota_respinta(self):
        self.assertFalse(eventi.g1_citazione(_proroga(citazione=""), _ctx())[0])

    # Casi reali della prova generale del 28/09/2026: citazioni vere respinte
    # perche' `testo_normalizzato` spezza i tag inline su righe diverse.
    TESTO_SICILIA = ("AGGIORNAMENTO (24/09/2026): Con DDG n. 1725 del 17/09/2026 e' prorogato "
                     "il termine di presentazione delle domande alle ore 12:00 dell'8/11/2026\n.")
    CITAZIONE_SICILIA = ("Con DDG n. 1725 del 17/09/2026 e' prorogato il termine di "
                         "presentazione delle domande alle ore 12:00 dell'8/11/2026.")

    def test_spazio_prima_del_punto(self):
        ctx = _ctx(pagine=(_pagina(testo=self.TESTO_SICILIA),))
        evento = _proroga(citazione=self.CITAZIONE_SICILIA)
        self.assertTrue(eventi.g1_citazione(evento, ctx)[0])
        self.assertEqual(eventi.g4_prova(evento, ctx), (True, ""))

    def test_parole_incollate_dal_modello(self):
        ctx = _ctx(pagine=(_pagina(testo="Prossima Apertura\nvenerdì 11 Settembre 2026"),))
        evento = _proroga(citazione="Prossima Aperturavenerdì 11 Settembre 2026")
        self.assertTrue(eventi.g1_citazione(evento, ctx)[0])

    def test_le_cifre_di_righe_diverse_non_si_fondono(self):
        # «3» e «1/12» su due righe non sono «31/12».
        ctx = _ctx(pagine=(_pagina(testo="Lotto 3\n1/12/2026 pubblicazione"),))
        evento = _proroga(citazione="Lotto 31/12/2026")
        self.assertFalse(eventi.g1_citazione(evento, ctx)[0])

    def test_ignorare_gli_spazi_non_fa_passare_un_riassunto(self):
        ctx = _ctx(pagine=(_pagina(testo=self.TESTO_SICILIA),))
        evento = _proroga(citazione="prorogato il termine all'8 novembre")
        self.assertFalse(eventi.g1_citazione(evento, ctx)[0])


class TestG2(unittest.TestCase):
    def test_citazione_nelle_righe_aggiunte(self):
        self.assertTrue(eventi.g2_diff(_proroga(), _ctx())[0])

    def test_citazione_in_una_riga_non_toccata(self):
        # La frase c'e' nella pagina, ma era gia' li' prima: non prova niente.
        evento = _proroga(citazione="Avviso pubblico Psicologia scolastica")
        ok, motivo = eventi.g2_diff(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("righe aggiunte", motivo)

    def test_senza_diff_respinge(self):
        self.assertFalse(eventi.g2_diff(_proroga(), _ctx(diff=None))[0])

    def test_link_nuovo_basta_per_la_graduatoria(self):
        prima = "Avviso.\nNessun documento."
        dopo = "Avviso.\nNessun documento.\n<a href='https://www.lazioeuropa.it/g.pdf'>Graduatoria</a>"
        ctx = _ctx(diff=impronte.diff_sezioni(prima, dopo, oggi=OGGI))
        evento = eventi.Evento(tipo="graduatoria", citazione="Graduatoria", url_prova=URL)
        self.assertTrue(eventi.g2_diff(evento, ctx)[0])

    # Prova generale del 28/09/2026: 19 G2 superati su 19 per i tipi «da
    # link», perche' bastava che un link nuovo qualsiasi esistesse.
    def test_un_link_nuovo_non_basta_se_la_citazione_parla_d_altro(self):
        diff = impronte.Diff(
            righe_aggiunte=("Download: 2171",),
            link_aggiunti=("https://lazioeuropa.it/allegati/1266/2026-09-23/determina-327.pdf",),
            rumore=False, rilevante=True)
        evento = eventi.Evento(tipo="nuovo_allegato", url_prova=URL,
                               citazione="Determinazione DPG025/240 del 01/07/2026")
        self.assertFalse(eventi.g2_diff(evento, _ctx(diff=diff))[0])

    def test_la_citazione_puo_stare_nel_nome_del_documento_nuovo(self):
        diff = impronte.Diff(
            link_aggiunti=("https://lazioeuropa.it/allegati/faq-aggiornate-9-luglio-2026.pdf",),
            rumore=False, rilevante=True)
        evento = eventi.Evento(tipo="faq", url_prova=URL, citazione="FAQ aggiornate 9 luglio 2026")
        self.assertTrue(eventi.g2_diff(evento, _ctx(diff=diff))[0])

    def test_host_anno_e_mese_del_link_non_bastano(self):
        # Revisione del 29/09: i token dell'URL finivano in un sacco solo, e
        # «lazioeuropa», «2026», «09» facevano passare qualunque citazione.
        diff = impronte.Diff(
            link_aggiunti=("https://lazioeuropa.it/uploads/2026/09/modulo.pdf",),
            rumore=False, rilevante=True)
        evento = eventi.Evento(tipo="nuovo_allegato", url_prova=URL,
                               citazione="Avviso Lazioeuropa del 09/2026")
        self.assertFalse(eventi.g2_diff(evento, _ctx(diff=diff))[0])

    def test_il_nome_del_documento_nella_query_vale(self):
        # Toscana, Liguria, CCIAA: il nome del file sta nella query
        # (revisione del 29/09/2026). Le chiavi della query non contano.
        diff = impronte.Diff(
            link_aggiunti=("https://ente.it/download.php?file=graduatoria_definitiva_imprese.pdf",),
            rumore=False, rilevante=True)
        evento = eventi.Evento(tipo="graduatoria", url_prova=URL,
                               citazione="Graduatoria definitiva imprese")
        self.assertTrue(eventi.g2_diff(evento, _ctx(diff=diff))[0])
        chiavi = impronte.Diff(
            link_aggiunti=("https://ente.it/download.php?graduatoria=1&definitiva=2",),
            rumore=False, rilevante=True)
        self.assertFalse(eventi.g2_diff(evento, _ctx(diff=chiavi))[0])

    def test_i_nomi_dei_link_non_valgono_per_gli_altri_tipi(self):
        diff = impronte.Diff(
            link_aggiunti=("https://lazioeuropa.it/proroga-al-1-dicembre-2026.pdf",),
            rumore=False, rilevante=True)
        evento = _proroga(citazione="proroga al 1 dicembre 2026")
        self.assertFalse(eventi.g2_diff(evento, _ctx(diff=diff))[0])


class TestG2Primo(unittest.TestCase):
    """La variante «G2 primo»: primo controllo o mismatch senza diff."""

    def test_si_applica_al_primo_controllo(self):
        self.assertTrue(eventi.usa_g2_primo(_ctx(testo_prima=None, diff=None)))

    def test_si_applica_al_mismatch_senza_diff(self):
        vuoto = impronte.diff_sezioni(TESTO_DOPO, TESTO_DOPO, oggi=OGGI)
        self.assertTrue(eventi.usa_g2_primo(_ctx(diff=vuoto)))

    def test_non_si_applica_con_un_diff_pieno(self):
        self.assertFalse(eventi.usa_g2_primo(_ctx()))

    def test_data_nuova_rispetto_alle_colonne(self):
        ctx = _ctx(testo_prima=None, diff=None)
        self.assertTrue(eventi.g2_primo(_proroga(), ctx)[0])

    def test_data_gia_in_colonna_respinta(self):
        ctx = _ctx(testo_prima=None, diff=None, data_scadenza=date(2026, 12, 1))
        ok, motivo = eventi.g2_primo(_proroga(), ctx)
        self.assertFalse(ok)
        self.assertIn("gia' in colonna", motivo)

    def test_data_gia_nel_testo_precedente_respinta(self):
        prima = "Le domande si presentano entro il 1° dicembre 2026."
        ctx = _ctx(testo_prima=prima, diff=None)
        ok, motivo = eventi.g2_primo(_proroga(), ctx)
        self.assertFalse(ok)
        self.assertIn("testo precedente", motivo)

    def test_senza_data_respinta(self):
        ctx = _ctx(testo_prima=None, diff=None)
        evento = eventi.Evento(tipo="sospensione", citazione="sospeso", url_prova=URL)
        self.assertFalse(eventi.g2_primo(evento, ctx)[0])


class TestG3(unittest.TestCase):
    def test_ruolo_compatibile(self):
        self.assertTrue(eventi.g3_ruolo(_proroga(), _ctx())[0])

    def test_data_normativa_respinta(self):
        # «DD 12 del 18/09/2026» e' l'atto, non il termine del bando.
        evento = _proroga(
            valore="2026-09-18",
            citazione="Con determinazione DD 12 del 18/09/2026 e' stato disposto il differimento",
        )
        ok, motivo = eventi.g3_ruolo(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("normativo", motivo)

    def test_data_assente_dalla_citazione(self):
        evento = _proroga(valore="2027-01-15")
        self.assertFalse(eventi.g3_ruolo(evento, _ctx())[0])

    def test_evento_senza_data_passa(self):
        evento = eventi.Evento(tipo="sospensione", citazione="bando sospeso", url_prova=URL)
        self.assertTrue(eventi.g3_ruolo(evento, _ctx())[0])

    def test_graduatoria_datata_dall_atto(self):
        # Una graduatoria si pubblica con «Determinazione n. X del <data>»: la
        # data dell'atto E' la data dell'evento (evento 9747, 28/09/2026).
        evento = eventi.Evento(
            tipo="graduatoria", url_prova=URL, data_evento=date(2026, 9, 21),
            citazione="Graduatoria provvisoria: Determinazione DPG025/327 del 21/09/2026")
        self.assertTrue(eventi.g3_ruolo(evento, _ctx())[0])

    def test_la_data_di_un_atto_vecchio_non_vale(self):
        # Solo un atto recente: una graduatoria «del 21/03/2026» letta il
        # 23/09 non e' una graduatoria nuova.
        evento = eventi.Evento(
            tipo="graduatoria", url_prova=URL, data_evento=date(2026, 3, 21),
            citazione="Graduatoria: Determinazione DPG025/12 del 21/03/2026")
        self.assertFalse(eventi.g3_ruolo(evento, _ctx())[0])

    def test_un_atto_uscito_dopo_l_ultimo_controllo_vale_anche_se_vecchio(self):
        # Bando chiuso ricontrollato dopo 35 giorni: la graduatoria del 25/08,
        # uscita sul sito il 02/09, arriva al controllo del 29/09. Con la sola
        # finestra di 30 giorni da oggi si perdeva per sempre.
        evento = eventi.Evento(
            tipo="graduatoria", url_prova=URL, data_evento=date(2026, 8, 25),
            citazione="Graduatoria definitiva approvata con Determinazione n. 88 del 25/08/2026")
        giorno = date(2026, 9, 29)
        self.assertFalse(eventi.g3_ruolo(evento, _ctx(oggi=giorno))[0])
        self.assertTrue(eventi.g3_ruolo(
            evento, _ctx(oggi=giorno, ultimo_controllo=date(2026, 8, 30)))[0])

    def test_un_atto_molto_anteriore_all_ultimo_controllo_resta_vecchio(self):
        evento = eventi.Evento(
            tipo="graduatoria", url_prova=URL, data_evento=date(2026, 7, 1),
            citazione="Graduatoria: Determinazione DPG025/240 del 01/07/2026")
        ctx = _ctx(oggi=date(2026, 9, 25), ultimo_controllo=date(2026, 8, 20))
        self.assertFalse(eventi.g3_ruolo(evento, ctx)[0])

    def test_un_atto_futuro_non_vale(self):
        evento = eventi.Evento(
            tipo="graduatoria", url_prova=URL, data_evento=date(2026, 10, 15),
            citazione="Graduatoria: Determinazione n. 9 del 15/10/2026")
        self.assertFalse(eventi.g3_ruolo(
            evento, _ctx(ultimo_controllo=date(2026, 9, 20)))[0])

    def test_senza_data_evento_conta_la_data_dell_atto_citato(self):
        # 9750 e 9834: il modello non ha dichiarato la data, la citazione
        # era una determina di luglio (revisione del 29/09/2026).
        vecchio = eventi.Evento(
            tipo="nuovo_allegato", url_prova=URL,
            citazione="Determinazione DPG025/240 del 01/07/2026")
        ok, motivo = eventi.g3_ruolo(vecchio, _ctx())
        self.assertFalse(ok)
        self.assertIn("non e' recente", motivo)
        recente = eventi.Evento(
            tipo="nuovo_allegato", url_prova=URL,
            citazione="Determinazione DPG025/327 del 21/09/2026")
        self.assertTrue(eventi.g3_ruolo(recente, _ctx())[0])
        senza_atto = eventi.Evento(tipo="faq", url_prova=URL, citazione="FAQ aggiornate")
        self.assertTrue(eventi.g3_ruolo(senza_atto, _ctx())[0])

    def test_faq_e_allegati_datati_dall_atto(self):
        for tipo in ("faq", "nuovo_allegato"):
            evento = eventi.Evento(
                tipo=tipo, url_prova=URL, data_evento=date(2026, 9, 18),
                citazione="Pubblicato con Determinazione n. 40 del 18/09/2026")
            self.assertTrue(eventi.g3_ruolo(evento, _ctx())[0], tipo)

    def test_la_data_dell_atto_resta_esclusa_per_le_proroghe(self):
        evento = _proroga(
            valore="2026-09-18",
            citazione="Con determinazione DD 12 del 18/09/2026 e' stato disposto il differimento")
        self.assertFalse(eventi.g3_ruolo(evento, _ctx())[0])


class TestDataEventoDeiTipiDaLink(unittest.TestCase):
    """`data_evento` e' quando l'ente ha dichiarato il fatto, mai il giorno
    del controllo: tre atti di luglio sono usciti come «nuovi del 25/09»."""

    def test_evento_da_link_senza_data_resta_senza_data(self):
        evento = eventi.Evento(tipo="nuovo_allegato", citazione="Allegato B", url_prova=URL)
        riga = eventi.riga_evento(evento, _ctx(), eventi.Giudizio(ammesso=True))
        self.assertIsNone(riga["data_evento"])

    def test_evento_da_link_con_data(self):
        evento = eventi.Evento(tipo="faq", citazione="FAQ", url_prova=URL,
                               data_evento=date(2026, 7, 9))
        riga = eventi.riga_evento(evento, _ctx(), eventi.Giudizio(ammesso=True))
        self.assertEqual(riga["data_evento"], "2026-07-09")

    def test_gli_altri_tipi_ripiegano_sul_giorno(self):
        riga = eventi.riga_evento(_proroga(), _ctx(), eventi.Giudizio(ammesso=True))
        self.assertEqual(riga["data_evento"], OGGI.isoformat())



class TestChiaveDelValore(unittest.TestCase):
    """La data di una proroga senza `campo` finiva in `{"valore": …}`, chiave
    che `bando_applica_evento` scarta: l'evento risultava applicato e la
    scadenza restava quella vecchia (evento 9786, 28/09/2026)."""

    def _riga(self, evento, **ctx):
        return eventi.riga_evento(evento, _ctx(**ctx), eventi.Giudizio(ammesso=True))

    def test_proroga_senza_campo(self):
        riga = self._riga(_proroga(campo=None, valore="2026-11-08"))
        self.assertEqual(riga["valore_dopo"].get("data_scadenza"), "2026-11-08")
        self.assertNotIn("valore", riga["valore_dopo"])

    def test_apertura_e_riapertura_senza_campo(self):
        for tipo in ("apertura", "riapertura"):
            evento = eventi.Evento(tipo=tipo, valore="2026-10-01", citazione="x", url_prova=URL)
            riga = self._riga(evento)
            self.assertEqual(riga["valore_dopo"].get("data_apertura"), "2026-10-01", tipo)

    def test_la_chiave_e_quella_di_colonne_da_evento(self):
        for evento in (_proroga(campo=None), _proroga(),
                       eventi.Evento(tipo="apertura", valore="2026-10-01", citazione="x", url_prova=URL)):
            colonne = eventi.colonne_da_evento(evento, _ctx(), eventi.Giudizio(ammesso=True))
            dopo = self._riga(evento)["valore_dopo"]
            for colonna in ("data_apertura", "data_scadenza"):
                if colonna in colonne:
                    self.assertEqual(dopo.get(colonna), colonne[colonna], evento)

    def test_valore_prima_segue_la_stessa_colonna(self):
        evento = eventi.Evento(tipo="apertura", valore="2026-10-01", citazione="x", url_prova=URL)
        riga = self._riga(evento, data_apertura=date(2026, 9, 1))
        self.assertEqual(riga["valore_prima"].get("data_apertura"), "2026-09-01")

    def test_la_chiusura_non_scrive_la_data(self):
        # Voluto (§4): la scadenza resta quella dichiarata dall'ente.
        evento = eventi.Evento(tipo="chiusura", valore="2026-09-20", citazione="x", url_prova=URL)
        dopo = self._riga(evento)["valore_dopo"]
        self.assertNotIn("data_scadenza", dopo)

    def test_il_g8_riconosce_la_forma_nuova(self):
        passato = {"tipo": "proroga", "campo": None, "valore_dopo": {"data_scadenza": "2026-12-01"},
                   "data_evento": OGGI.isoformat()}
        ok, _ = eventi.g8_dedup(_proroga(campo=None), _ctx(eventi_recenti=(passato,)))
        self.assertFalse(ok)


class TestG4(unittest.TestCase):
    def test_pagina_scaricata(self):
        self.assertTrue(eventi.g4_prova(_proroga(), _ctx())[0])

    def test_href_mai_scaricato_respinto(self):
        # Il link stava nella sidebar: c'e' nell'HTML, nessuno l'ha aperto.
        evento = _proroga(url_prova="https://www.lazioeuropa.it/altro-bando/")
        ok, motivo = eventi.g4_prova(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("non e' una pagina scaricata", motivo)

    def test_aggregatore_respinto(self):
        ctx = _ctx(pagine=(_pagina(url=URL_AGGREGATORE),))
        evento = _proroga(url_prova=URL_AGGREGATORE)
        ok, motivo = eventi.g4_prova(evento, ctx)
        self.assertFalse(ok)
        self.assertIn("aggregatore", motivo)

    def test_dominio_sconosciuto_respinto(self):
        sconosciuto = "https://blog.example.com/bandi/x"
        ctx = _ctx(pagine=(_pagina(url=sconosciuto),))
        ok, motivo = eventi.g4_prova(_proroga(url_prova=sconosciuto), ctx)
        self.assertFalse(ok)
        self.assertIn("non verificabile", motivo)

    def test_senza_impronta_respinto(self):
        ctx = _ctx(pagine=(_pagina(impronta=""),))
        self.assertFalse(eventi.g4_prova(_proroga(), ctx)[0])

    def test_citazione_su_una_pagina_diversa(self):
        altra = "https://www.lazioeuropa.it/news/21558/"
        ctx = _ctx(pagine=(_pagina(), _pagina(url=altra, testo="Altro testo", collegata=True)))
        ok, _ = eventi.g4_prova(_proroga(url_prova=altra), ctx)
        self.assertFalse(ok)


class TestG5(unittest.TestCase):
    def test_proroga_che_posticipa(self):
        self.assertTrue(eventi.g5_direzione(_proroga(), _ctx())[0])

    def test_proroga_senza_vecchia_scadenza_respinta(self):
        # I 416 bandi a sportello: una scadenza che compare per la prima volta
        # NON e' una proroga, e trattarla come tale chiuderebbe il bando.
        ok, motivo = eventi.g5_direzione(_proroga(), _ctx(data_scadenza=None))
        self.assertFalse(ok)
        self.assertIn("rettifica data_scadenza", motivo)

    def test_rettifica_data_scadenza_su_sportello_ammessa(self):
        evento = eventi.Evento(
            tipo="rettifica", campo="data_scadenza", valore="2026-12-01",
            citazione="nuovo termine: 1° dicembre 2026", url_prova=URL,
        )
        self.assertTrue(eventi.g5_direzione(evento, _ctx(data_scadenza=None))[0])

    def test_proroga_che_anticipa_respinta(self):
        evento = _proroga(valore="2026-09-30")
        ok, motivo = eventi.g5_direzione(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("non posticipa", motivo)

    def test_chiusura_anticipata_nel_futuro_respinta(self):
        evento = eventi.Evento(
            tipo="chiusura", valore="2026-12-01",
            citazione="chiuso per esaurimento", url_prova=URL)
        ok, motivo = eventi.g5_direzione(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("nel futuro", motivo)

    def test_chiusura_non_tocca_la_scadenza(self):
        evento = eventi.Evento(
            tipo="chiusura", citazione="chiuso per esaurimento risorse", url_prova=URL)
        ctx = _ctx()
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="chiuso")
        colonne = eventi.colonne_da_evento(evento, ctx, giudizio)
        self.assertEqual(colonne, {"stato_bando": "chiuso"})
        self.assertNotIn("data_scadenza", colonne)

    def test_incoerenza_delle_date_risultanti(self):
        evento = _proroga(valore="2026-12-01")
        ctx = _ctx(data_pubblicazione=date(2027, 1, 1))
        ok, motivo = eventi.g5_direzione(evento, ctx)
        self.assertFalse(ok)
        self.assertIn("pubblicazione <= apertura <= scadenza", motivo)

    def test_differimento_a_data_passata_respinto(self):
        evento = eventi.Evento(
            tipo="rettifica", campo="data_apertura", valore="2026-01-01",
            citazione="apertura differita al 1 gennaio 2026", url_prova=URL)
        ctx = _ctx(stato_bando="in apertura prossimamente", data_scadenza=None)
        ok, motivo = eventi.g5_direzione(evento, ctx)
        self.assertFalse(ok)
        self.assertIn("gia' passata", motivo)


class TestG6(unittest.TestCase):
    def test_parola_chiave_presente(self):
        self.assertTrue(eventi.g6_parola(_proroga(), _ctx())[0])

    def test_senza_parola_chiave_respinta(self):
        evento = _proroga(citazione="le domande si presentano dal 22 ottobre al 1° dicembre 2026")
        ok, motivo = eventi.g6_parola(evento, _ctx())
        self.assertFalse(ok)
        self.assertIn("senza parola chiave", motivo)

    def test_ogni_tipo_ha_le_sue_parole(self):
        casi = [
            ("rettifica", "data_apertura", "apertura posticipata al 22 ottobre 2026"),
            ("rettifica", "data_scadenza", "nuovo termine: 1 dicembre 2026"),
            ("apertura", None, "lo sportello e' attivo a partire da oggi"),
            ("proroga", None, "termini prorogati"),
            ("sospensione", None, "il bando e' sospeso"),
            ("revoca", None, "l'avviso e' stato revocato"),
            ("chiusura", None, "chiuso per esaurimento delle risorse"),
            ("riapertura", None, "il bando e' nuovamente aperto"),
            ("graduatoria", None, "pubblicata la graduatoria"),
            ("esito", None, "pubblicati gli esiti dei progetti ammessi"),
            ("faq", None, "pubblicate nuove FAQ"),
        ]
        for tipo, campo, citazione in casi:
            with self.subTest(tipo=tipo, campo=campo):
                evento = eventi.Evento(tipo=tipo, campo=campo, citazione=citazione, url_prova=URL)
                self.assertTrue(eventi.g6_parola(evento, _ctx())[0])

    def test_nuovo_allegato_non_richiede_parole(self):
        evento = eventi.Evento(tipo="nuovo_allegato", citazione="Modulo A", url_prova=URL)
        self.assertTrue(eventi.g6_parola(evento, _ctx())[0])


class TestG7(unittest.TestCase):
    def test_concordanza_del_secondo_modello(self):
        ctx = _ctx(seconda_opinione=_proroga())
        self.assertTrue(eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)[0])

    def test_disaccordo_sul_tipo_non_vale(self):
        diverso = eventi.Evento(tipo="chiusura", citazione=CITAZIONE, url_prova=URL)
        ctx = _ctx(seconda_opinione=diverso)
        self.assertFalse(eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)[0])

    def test_disaccordo_sulla_data_non_vale(self):
        ctx = _ctx(seconda_opinione=_proroga(valore="2026-12-15"))
        self.assertFalse(eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)[0])

    def test_prova_indipendente_basta(self):
        ctx = _ctx(prove=(eventi.Prova(
            genere="pagina_collegata", data=date(2026, 12, 1), ruolo="scadenza"),))
        self.assertTrue(eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)[0])

    def test_modified_non_e_mai_una_prova(self):
        # `modified` dice che la pagina e' cambiata, non che l'abbiamo letta
        # bene: e' il segnale che ha innescato il controllo.
        ctx = _ctx(prove=(eventi.Prova(
            genere="modified", data=date(2026, 12, 1), ruolo="scadenza"),))
        ok, motivo = eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)
        self.assertFalse(ok)
        self.assertIn("nessuna seconda prova", motivo)

    def test_ds_last_update_non_e_mai_una_prova(self):
        ctx = _ctx(prove=(eventi.Prova(
            genere="ds_last_update", data=date(2026, 12, 1), ruolo="scadenza"),))
        self.assertFalse(eventi.g7_seconda_prova(_proroga(), ctx, doppia=False)[0])

    def test_transizione_senza_data_non_si_conferma_con_una_data_qualsiasi(self):
        # Una `chiusura` senza `valore` supera G3 (niente da confrontare) e
        # G5 (i rami sono tutti `if data is not None`): se il G7 accettasse
        # una prova di ruolo compatibile ma scorrelata, «lo sportello e'
        # chiuso il martedi» piu' una scadenza qualsiasi letta su una pagina
        # collegata basterebbe a portare `stato_bando` a `chiuso`.
        chiusura = eventi.Evento(
            tipo="chiusura",
            citazione="lo sportello e' chiuso il martedi e il giovedi",
            url_prova=URL,
        )
        ctx = _ctx(prove=(eventi.Prova(
            genere="pagina_collegata", data=date(2026, 12, 1), ruolo="scadenza"),))
        ok, motivo = eventi.g7_seconda_prova(chiusura, ctx, doppia=False)
        self.assertFalse(ok)
        self.assertIn("nessuna seconda prova", motivo)

    def test_apertura_senza_data_non_si_conferma_con_una_data_qualsiasi(self):
        apertura = eventi.Evento(
            tipo="apertura",
            citazione="le domande si presentano dal lunedi al venerdi",
            url_prova=URL,
        )
        ctx = _ctx(prove=(eventi.Prova(
            genere="pagina_collegata", data=date(2026, 10, 22), ruolo="apertura"),))
        self.assertFalse(eventi.g7_seconda_prova(apertura, ctx, doppia=False)[0])

    def test_senza_data_resta_la_concordanza_del_secondo_modello(self):
        # La sospensione e la revoca quasi mai dichiarano una data: per loro
        # la seconda prova e' il secondo modello, non la pagina collegata.
        sospensione = eventi.Evento(
            tipo="sospensione", citazione="l'avviso e' sospeso", url_prova=URL)
        ctx = _ctx(seconda_opinione=eventi.Evento(
            tipo="sospensione", citazione="l'avviso e' sospeso", url_prova=URL))
        self.assertTrue(eventi.g7_seconda_prova(sospensione, ctx, doppia=False)[0])

    def test_in_g2_primo_servono_entrambe(self):
        solo_modello = _ctx(seconda_opinione=_proroga())
        ok, motivo = eventi.g7_seconda_prova(_proroga(), solo_modello, doppia=True)
        self.assertFalse(ok)
        self.assertIn("prova indipendente", motivo)

        solo_prova = _ctx(prove=(eventi.Prova(
            genere="sedia", data=date(2026, 12, 1), ruolo="scadenza"),))
        ok, motivo = eventi.g7_seconda_prova(_proroga(), solo_prova, doppia=True)
        self.assertFalse(ok)
        self.assertIn("seconda opinione", motivo)

        entrambe = _ctx(
            seconda_opinione=_proroga(),
            prove=(eventi.Prova(genere="sedia", data=date(2026, 12, 1), ruolo="scadenza"),),
        )
        self.assertTrue(eventi.g7_seconda_prova(_proroga(), entrambe, doppia=True)[0])


class TestG8(unittest.TestCase):
    def test_nessun_precedente(self):
        self.assertTrue(eventi.g8_dedup(_proroga(), _ctx())[0])

    def test_stesso_evento_entro_30_giorni_respinto(self):
        passato = {
            "tipo": "proroga", "campo": "data_scadenza",
            "valore_dopo": {"data_scadenza": "2026-12-01"},
            "data_evento": "2026-09-10",
        }
        ok, motivo = eventi.g8_dedup(_proroga(), _ctx(eventi_recenti=(passato,)))
        self.assertFalse(ok)
        self.assertIn("gia' registrato", motivo)

    def test_stesso_evento_oltre_30_giorni_ammesso(self):
        passato = {
            "tipo": "proroga", "campo": "data_scadenza",
            "valore_dopo": {"data_scadenza": "2026-12-01"},
            "data_evento": "2026-07-01",
        }
        self.assertTrue(eventi.g8_dedup(_proroga(), _ctx(eventi_recenti=(passato,)))[0])

    def test_valore_diverso_non_e_un_doppione(self):
        passato = {
            "tipo": "proroga", "campo": "data_scadenza",
            "valore_dopo": {"data_scadenza": "2026-11-01"},
            "data_evento": "2026-09-10",
        }
        self.assertTrue(eventi.g8_dedup(_proroga(), _ctx(eventi_recenti=(passato,)))[0])

    def test_la_riga_del_giro_prima_deduplica_quella_di_oggi(self):
        # La riga la scrive `riga_evento`, quindi il dedup funziona solo se
        # `data_evento` e' il giorno della lettura. Con il vecchio ripiego su
        # `data_valore` usciva 2026-12-01, cioe' nel futuro: la differenza
        # `oggi - quando` era negativa e G8 non scattava piu'.
        ieri = eventi.Contesto(
            bando_id=905315, stato_bando="aperto", data_scadenza=date(2026, 10, 6),
            pagine=(_pagina(),), diff=None, testo_prima=TESTO_PRIMA,
            tabella_domini=TABELLA, oggi=date(2026, 9, 21),
        )
        giudizio = eventi.Giudizio(ammesso=True, gate="G2")
        riga = eventi.riga_evento(_proroga(), ieri, giudizio)
        self.assertEqual(riga["data_evento"], "2026-09-21")

        ok, motivo = eventi.g8_dedup(_proroga(), _ctx(eventi_recenti=(riga,)))
        self.assertFalse(ok)
        self.assertIn("gia' registrato", motivo)


class TestDataEvento(unittest.TestCase):
    """`data_evento` = QUANDO l'ente lo ha dichiarato, mai il nuovo valore."""

    def test_senza_dichiarazione_vale_oggi(self):
        giudizio = eventi.Giudizio(ammesso=True, gate="G2")
        riga = eventi.riga_evento(_proroga(), _ctx(), giudizio)
        self.assertEqual(riga["data_evento"], OGGI.isoformat())
        # Il nuovo valore sta dove deve stare.
        self.assertEqual(riga["valore_dopo"]["data_scadenza"], "2026-12-01")

    def test_la_data_dichiarata_dall_ente_vince(self):
        giudizio = eventi.Giudizio(ammesso=True, gate="G2")
        riga = eventi.riga_evento(
            _proroga(data_evento=date(2026, 9, 18)), _ctx(), giudizio)
        self.assertEqual(riga["data_evento"], "2026-09-18")

    def test_mai_una_data_nel_futuro(self):
        giudizio = eventi.Giudizio(ammesso=True, gate="G2")
        riga = eventi.riga_evento(_proroga(), _ctx(), giudizio)
        self.assertLessEqual(date.fromisoformat(riga["data_evento"]), OGGI)


class TestG9ETransizioni(unittest.TestCase):
    def test_tabella_derivata_da_stato_bando(self):
        # La tabella non e' una seconda copia: e' una vista di TRANSIZIONI.
        righe = eventi.tabella_transizioni()
        self.assertTrue(righe)
        for riga in righe:
            self.assertTrue(
                stato_bando.transizione_ammessa(riga["da"], riga["a"], "worker"),
                riga,
            )

    def test_transizioni_di_sezione_4(self):
        casi = [
            ("in apertura prossimamente", "apertura", None, "aperto"),
            ("in apertura prossimamente", "rettifica", "data_apertura", None),
            ("aperto", "proroga", "data_scadenza", "aperto"),
            ("chiuso", "proroga", "data_scadenza", "aperto"),
            ("chiuso", "riapertura", None, "aperto"),
            ("aperto", "sospensione", None, "sospeso"),
            ("in apertura prossimamente", "sospensione", None, "sospeso"),
            ("sospeso", "riapertura", None, "aperto"),
            ("aperto", "revoca", None, "revocato"),
            ("sospeso", "revoca", None, "revocato"),
            ("aperto", "chiusura", None, "chiuso"),
            ("chiuso", "graduatoria", None, None),
            ("chiuso", "esito", None, None),
            ("aperto", "faq", None, None),
            ("aperto", "nuovo_allegato", None, None),
        ]
        for stato, tipo, campo, atteso in casi:
            with self.subTest(stato=stato, tipo=tipo):
                evento = eventi.Evento(tipo=tipo, campo=campo, citazione="x", url_prova=URL)
                self.assertEqual(eventi.transizione_evento(stato, evento), atteso)

    def test_sospeso_si_chiude_solo_con_una_chiusura_e_la_14(self):
        # A3 resta: mai d'ufficio. Con la 14 un sospeso si chiude solo con una
        # `chiusura` letta dal worker (giro 3, §14); prima, G9 la respinge.
        chiusura = eventi.Evento(tipo="chiusura", citazione="x", url_prova=URL)
        self.assertEqual(eventi.transizione_evento("sospeso", chiusura), "chiuso")
        self.assertFalse(eventi.g9_transizione(chiusura, _ctx(stato_bando="sospeso"))[0])
        self.assertTrue(eventi.g9_transizione(
            chiusura, _ctx(stato_bando="sospeso", capacita_14=True))[0])
        sospensione = eventi.Evento(tipo="sospensione", citazione="x", url_prova=URL)
        self.assertNotEqual(eventi.transizione_evento("sospeso", sospensione), "chiuso")

    def test_revocato_e_terminale(self):
        for tipo in ("proroga", "riapertura", "apertura", "chiusura"):
            evento = eventi.Evento(tipo=tipo, citazione="x", url_prova=URL)
            self.assertIsNone(eventi.transizione_evento("revocato", evento))

    def test_g9_respinge_una_transizione_fuori_tabella(self):
        # Una `revoca` su una riga senza stato: None -> revocato non e' nella
        # lista bianca del worker (le righe di creazione sono della pipeline).
        evento = eventi.Evento(tipo="revoca", citazione="il bando e' revocato", url_prova=URL)
        self.assertEqual(eventi.transizione_evento(None, evento), "revocato")
        self.assertFalse(eventi.transizione_ammessa(None, "revocato", "worker"))
        ok, motivo = eventi.g9_transizione(evento, _ctx(stato_bando=None))
        self.assertFalse(ok)
        self.assertIn("non prevista", motivo)

    def test_g9_annullamento_revoca_esce_dal_revocato(self):
        # Migrazione 14 (giro 3, §14): dal revocato si esce con
        # `annullamento_revoca`, che ora e' nella lista bianca del worker.
        evento = eventi.Evento(
            tipo="annullamento_revoca",
            citazione="la revoca e' stata annullata", url_prova=URL)
        ok, motivo = eventi.g9_transizione(evento, _ctx(stato_bando="revocato", capacita_14=True))
        self.assertTrue(ok, motivo)
        # Senza la 14 la riga non vale: la RPC la respingerebbe.
        self.assertFalse(eventi.g9_transizione(evento, _ctx(stato_bando="revocato"))[0])


class TestG9EventiDiSoloStato(unittest.TestCase):
    """Contratto `bandi-giro-3` §20.2: senza stato di arrivo, un evento di solo
    stato passa solo se il bando e' gia' nello stato naturale del tipo."""

    def _evento(self, tipo, **extra):
        return eventi.Evento(tipo=tipo, citazione="x", url_prova=URL, **extra)

    def test_chiusura_dal_monitor_su_in_apertura_respinta(self):
        chiusura = self._evento("chiusura")
        ctx = _ctx(stato_bando="in apertura prossimamente", capacita_14=True)
        self.assertIsNone(eventi.stato_di_arrivo(chiusura, ctx))
        ok, motivo = eventi.g9_transizione(chiusura, ctx)
        self.assertFalse(ok)
        self.assertIn("senza transizione", motivo)

    def test_sospensione_su_chiuso_respinta(self):
        for capacita_14 in (False, True):
            with self.subTest(capacita_14=capacita_14):
                ok, motivo = eventi.g9_transizione(
                    self._evento("sospensione"), _ctx(stato_bando="chiuso", capacita_14=capacita_14))
                self.assertFalse(ok)
                self.assertIn("senza transizione", motivo)

    def test_chiusura_su_chiuso_ammessa(self):
        # Il bando e' gia' nello stato naturale: la notizia della chiusura resta.
        self.assertEqual(eventi.g9_transizione(self._evento("chiusura"),
                                               _ctx(stato_bando="chiuso")), (True, ""))

    def test_proroga_su_sospeso_ancora_ammessa_come_sola_data(self):
        proroga = self._evento("proroga", valore="2026-12-15")
        ctx = _ctx(stato_bando="sospeso", capacita_14=True, data_scadenza=date(2026, 10, 6))
        self.assertIsNone(eventi.stato_di_arrivo(proroga, ctx))
        self.assertEqual(eventi.g9_transizione(proroga, ctx), (True, ""))

    def test_gli_altri_tipi_senza_arrivo_restano_come_prima(self):
        # Eventi con date o senza stato: la regola non li tocca.
        for stato, tipo in (("in apertura prossimamente", "rettifica"), ("aperto", "apertura"),
                            ("aperto", "riapertura"), ("chiuso", "graduatoria"),
                            ("aperto", "faq"), ("aperto", "nuovo_allegato")):
            with self.subTest(stato=stato, tipo=tipo):
                self.assertTrue(eventi.g9_transizione(
                    self._evento(tipo, valore="2026-12-01"), _ctx(stato_bando=stato))[0])

    def test_annullamento_fuori_dal_revocato_respinto(self):
        for stato in ("aperto", "chiuso", "in apertura prossimamente"):
            with self.subTest(stato=stato):
                self.assertFalse(eventi.g9_transizione(
                    self._evento("annullamento_revoca"),
                    _ctx(stato_bando=stato, capacita_14=True))[0])

    def test_le_transizioni_vere_restano_ammesse(self):
        for stato, tipo in (("aperto", "chiusura"), ("aperto", "sospensione"),
                            ("in apertura prossimamente", "sospensione"), ("aperto", "revoca")):
            with self.subTest(stato=stato, tipo=tipo):
                self.assertTrue(eventi.g9_transizione(
                    self._evento(tipo), _ctx(stato_bando=stato, capacita_14=True))[0])

    def test_la_regola_pura(self):
        self.assertEqual(eventi.ARRIVO_NATURALE, {
            "chiusura": "chiuso", "sospensione": "sospeso", "revoca": "revocato",
            "annullamento_revoca": None})
        self.assertIsNone(eventi.solo_stato_senza_arrivo("chiusura", "chiuso"))
        self.assertIsNone(eventi.solo_stato_senza_arrivo("proroga", "sospeso"))
        self.assertIsNotNone(eventi.solo_stato_senza_arrivo("chiusura", "in apertura prossimamente"))
        self.assertIsNotNone(eventi.solo_stato_senza_arrivo("chiusura", None))
        self.assertIsNotNone(eventi.solo_stato_senza_arrivo("annullamento_revoca", "aperto"))
        self.assertLessEqual(set(eventi.ARRIVO_NATURALE), set(eventi.TIPI_CON_TRANSIZIONE))

    def test_gv9_stessa_regola_nel_percorso_verifica(self):
        from types import SimpleNamespace

        def proposta(tipo, **extra):
            return eventi.Proposta(tipo, ramo="I", citazione="x", url_prova=URL,
                                   metodo="estrattore:prova", **extra)

        def contesto(stato):
            return SimpleNamespace(stato=stato)

        # Dal percorso verifica la chiusura da «in apertura» c'e' (riga 24).
        self.assertTrue(eventi.gv9_transizione(proposta("chiusura"),
                                               contesto("in apertura prossimamente"))[0])
        self.assertTrue(eventi.gv9_transizione(proposta("chiusura"), contesto("chiuso"))[0])
        ok, motivo = eventi.gv9_transizione(proposta("chiusura"), contesto("revocato"))
        self.assertFalse(ok)
        self.assertIn("senza transizione", motivo)
        # Le date restano ammesse come prima.
        self.assertTrue(eventi.gv9_transizione(
            proposta("rettifica", campo="data_scadenza",
                     valore_dopo={"data_scadenza": "2026-12-01"}),
            contesto("sospeso"))[0])


class TestSospensioneERevocaGiro3(unittest.TestCase):
    """Contratto `bandi-giro-3` §14: G5, G8, G9 e lo stato dell'annullamento."""

    def _evento(self, tipo, **extra):
        return eventi.Evento(tipo=tipo, citazione="x", url_prova=URL, **extra)

    def test_g9_vuole_l_evento_della_riga(self):
        ctx = _ctx(stato_bando="sospeso", capacita_14=True)
        self.assertTrue(eventi.g9_transizione(self._evento("riapertura"), ctx)[0])
        self.assertTrue(eventi.g9_transizione(self._evento("revoca"), ctx)[0])
        # La regola pura: dal sospeso verso aperto solo con la riapertura.
        self.assertTrue(eventi.transizione_ammessa_evento("sospeso", "aperto", "riapertura",
                                                          capacita_14=True))
        self.assertFalse(eventi.transizione_ammessa_evento("sospeso", "aperto", "proroga",
                                                           capacita_14=True))
        self.assertFalse(eventi.transizione_ammessa_evento("revocato", "aperto", "riapertura",
                                                           capacita_14=True))
        self.assertTrue(eventi.transizione_ammessa_evento("aperto", "chiuso", "qualunque",
                                                          capacita_14=False))

    def test_g9_eventi_incompatibili(self):
        for stato, tipo in (("revocato", "proroga"), ("revocato", "apertura"),
                            ("revocato", "riapertura"), ("revocato", "chiusura"),
                            ("sospeso", "apertura"),
                            ("sospeso", "sospensione"), ("sospeso", "annullamento_revoca")):
            with self.subTest(stato=stato, tipo=tipo):
                ok, motivo = eventi.g9_transizione(
                    self._evento(tipo, valore="2026-12-01"),
                    _ctx(stato_bando=stato, capacita_14=True))
                self.assertFalse(ok)
                self.assertIn("incompatibile", motivo)
        # Un evento senza stato ne' date resta ammesso.
        self.assertTrue(eventi.g9_transizione(self._evento("faq"),
                                              _ctx(stato_bando="revocato"))[0])

    def test_annullamento_verso_lo_stato_delle_date(self):
        casi = (
            ({"data_apertura": None, "data_scadenza": date(2026, 12, 1)}, "aperto"),
            ({"data_apertura": None, "data_scadenza": date(2026, 9, 1)}, "chiuso"),
            ({"data_apertura": date(2026, 11, 1), "data_scadenza": date(2026, 12, 1)},
             "in apertura prossimamente"),
            ({"data_apertura": date(2026, 9, 1), "data_scadenza": date(2026, 12, 1)}, "aperto"),
        )
        evento = self._evento("annullamento_revoca")
        for date_bando, atteso in casi:
            with self.subTest(atteso=atteso, **{k: str(v) for k, v in date_bando.items()}):
                ctx = _ctx(stato_bando="revocato", capacita_14=True, **date_bando)
                self.assertEqual(eventi.stato_dopo_annullamento(ctx), atteso)
                self.assertEqual(eventi.stato_di_arrivo(evento, ctx), atteso)
                self.assertTrue(eventi.g9_transizione(evento, ctx)[0])

    def test_valuta_porta_lo_stato_calcolato_in_valore_dopo(self):
        ctx = _ctx(stato_bando="revocato", capacita_14=True, stati_estesi=True,
                   data_scadenza=date(2026, 9, 1), modalita="attivo")
        evento = self._evento("annullamento_revoca")
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato=eventi.stato_di_arrivo(evento, ctx))
        riga = eventi.riga_evento(evento, ctx, giudizio)
        self.assertEqual(riga["valore_dopo"], {"stato_bando": "chiuso"})
        self.assertEqual(riga["valore_prima"], {"stato_bando": "revocato"})

    def test_proroga_su_un_sospeso_e_solo_una_data(self):
        # P2 della revisione #153: la proroga letta durante la sospensione dei
        # termini non si perde. Lo stato non cambia (resta sospeso): la RPC
        # riceve solo la data nuova.
        proroga = self._evento("proroga", valore="2026-12-15")
        ctx = _ctx(stato_bando="sospeso", capacita_14=True, stati_estesi=True, modalita="attivo",
                   data_scadenza=date(2026, 10, 6))
        self.assertIsNone(eventi.stato_di_arrivo(proroga, ctx))
        self.assertTrue(eventi.g9_transizione(proroga, ctx)[0])
        self.assertTrue(eventi.g5_direzione(proroga, ctx)[0])
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato=eventi.stato_di_arrivo(proroga, ctx))
        riga = eventi.riga_evento(proroga, ctx, giudizio)
        self.assertEqual(riga["valore_dopo"], {"data_scadenza": "2026-12-15"})
        self.assertEqual(riga["valore_prima"], {"data_scadenza": "2026-10-06"})
        parametri = eventi.parametri_registra_evento(riga)
        self.assertEqual(parametri["p_valore_dopo"], {"data_scadenza": "2026-12-15"})
        self.assertNotIn("stato_bando", parametri["p_valore_dopo"])
        # Anche senza la 14: non e' una transizione, non dipende dalle righe nuove.
        self.assertTrue(eventi.g9_transizione(proroga, _ctx(stato_bando="sospeso",
                                                            data_scadenza=date(2026, 10, 6)))[0])

    def test_g5_riapertura_al_passato_solo_per_un_sospeso(self):
        passata = self._evento("riapertura", valore="2026-09-20")
        self.assertTrue(eventi.g5_direzione(passata, _ctx(stato_bando="sospeso"))[0])
        ok, motivo = eventi.g5_direzione(passata, _ctx(stato_bando="chiuso"))
        self.assertFalse(ok)
        self.assertIn("passata", motivo)

    def test_g8_anche_sulla_forma_stato_proposto(self):
        for dopo in ({"stato_proposto": "sospeso"}, {"stato_bando": "sospeso"}):
            with self.subTest(valore_dopo=dopo):
                recenti = ({"tipo": "sospensione", "campo": None, "valore_dopo": dopo,
                            "rilevato_at": "2026-09-20T08:00:00+00:00"},)
                ok, motivo = eventi.g8_dedup(self._evento("sospensione"),
                                             _ctx(eventi_recenti=recenti))
                self.assertFalse(ok)
                self.assertIn("gia' registrato", motivo)
        # Un valore vero diverso (non solo lo stato) resta un evento nuovo.
        recenti = ({"tipo": "sospensione", "campo": None,
                    "valore_dopo": {"stato_proposto": "sospeso", "data_scadenza": "2026-12-01"},
                    "rilevato_at": "2026-09-20T08:00:00+00:00"},)
        self.assertTrue(eventi.g8_dedup(self._evento("sospensione"), _ctx(eventi_recenti=recenti))[0])

    def test_g9_ammette_le_transizioni_della_tabella(self):
        self.assertTrue(eventi.g9_transizione(_proroga(), _ctx())[0])

    def test_il_monitor_non_chiude_da_in_apertura(self):
        # Riga 24 (contratto `bandi-giro-2` §4): da «in apertura» chiude solo
        # il percorso verifica_stato. Il monitor, senza percorso, resta com'era.
        chiusura = eventi.Evento(tipo="chiusura", citazione="bando chiuso", url_prova=URL)
        self.assertIsNone(eventi.transizione_evento("in apertura prossimamente", chiusura))
        self.assertEqual(eventi.transizione_evento("in apertura prossimamente", chiusura,
                                                   percorso=eventi.PERCORSO_VERIFICA), "chiuso")
        self.assertIn({"da": "in apertura prossimamente", "a": "chiuso", "evento": "chiusura"},
                      eventi.tabella_transizioni())


class TestValuta(unittest.TestCase):
    def _ctx_completo(self, **extra):
        base = dict(
            seconda_opinione=_proroga(),
            prove=(eventi.Prova(genere="pagina_collegata", data=date(2026, 12, 1),
                                ruolo="scadenza"),),
        )
        base.update(extra)
        return _ctx(**base)

    def test_evento_completo_passa(self):
        giudizio = eventi.valuta(_proroga(), self._ctx_completo())
        self.assertTrue(giudizio.ammesso, giudizio.motivo)
        self.assertEqual(giudizio.gate, "G2")
        self.assertGreater(giudizio.confidenza, 0.9)

    def test_gate_applicato_registrato(self):
        giudizio = eventi.valuta(
            _proroga(), self._ctx_completo(testo_prima=None, diff=None))
        self.assertEqual(giudizio.gate, "G2'")
        self.assertTrue(giudizio.ammesso, giudizio.motivo)

    def test_un_solo_gate_fallito_respinge_tutto(self):
        giudizio = eventi.valuta(
            _proroga(url_prova="https://www.lazioeuropa.it/mai-scaricata/"),
            self._ctx_completo(),
        )
        self.assertFalse(giudizio.ammesso)
        self.assertIn("G4", [g for g, _ in giudizio.falliti])

    def test_confidenza_llm_non_entra_nel_punteggio(self):
        # §6.2: la confidenza registrata e' deterministica, quella del modello
        # e' solo un tiebreak.
        ctx = self._ctx_completo()
        bassa = eventi.valuta(_proroga(confidenza_llm=0.1), ctx)
        alta = eventi.valuta(_proroga(confidenza_llm=1.0), ctx)
        self.assertEqual(bassa.confidenza, alta.confidenza)

    def test_evento_senza_transizione_non_richiede_g7(self):
        evento = eventi.Evento(tipo="faq", citazione="pubblicate nuove FAQ", url_prova=URL)
        prima = "Avviso.\nNessuna FAQ."
        dopo = "Avviso.\nNessuna FAQ.\nSono state pubblicate nuove FAQ."
        giudizio = eventi.valuta(evento, _ctx(
            diff=impronte.diff_sezioni(prima, dopo, oggi=OGGI),
            pagine=(_pagina(testo=dopo),),
        ))
        self.assertTrue(giudizio.ammesso, giudizio.motivo)
        self.assertNotIn("G7", giudizio.superati)


class TestA30(unittest.TestCase):
    """Prima della migrazione 06 `sospeso`/`revocato` non sono scrivibili."""

    def _sospensione(self):
        return eventi.Evento(
            tipo="sospensione",
            citazione="il procedimento e' sospeso fino a nuova comunicazione",
            url_prova=URL,
        )

    def test_nessuna_colonna_scritta_prima_della_06(self):
        ctx = _ctx(stati_estesi=False, modalita="attivo")
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="sospeso")
        self.assertEqual(eventi.colonne_da_evento(self._sospensione(), ctx, giudizio), {})

    def test_evento_leggibile_e_in_aggiornamenti(self):
        ctx = _ctx(stati_estesi=False, modalita="attivo")
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="sospeso")
        riga = eventi.riga_evento(self._sospensione(), ctx, giudizio)
        self.assertTrue(riga["leggibile"])
        self.assertTrue(riga["in_aggiornamenti"])
        self.assertFalse(riga["applicato"])
        self.assertEqual(riga["valore_dopo"]["stato_proposto"], "sospeso")
        self.assertNotIn("stato_bando", riga["valore_dopo"])

    def test_dopo_la_06_la_colonna_si_scrive(self):
        ctx = _ctx(stati_estesi=True, modalita="attivo")
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="sospeso")
        colonne = eventi.colonne_da_evento(self._sospensione(), ctx, giudizio)
        self.assertEqual(colonne["stato_bando"], "sospeso")
        riga = eventi.riga_evento(self._sospensione(), ctx, giudizio)
        self.assertTrue(riga["applicato"])

    def test_nessun_proxy_revocato_chiuso(self):
        revoca = eventi.Evento(tipo="revoca", citazione="revocato", url_prova=URL)
        ctx = _ctx(stati_estesi=False, modalita="attivo")
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="revocato")
        colonne = eventi.colonne_da_evento(revoca, ctx, giudizio)
        self.assertNotIn("stato_bando", colonne)


class TestApplica(unittest.TestCase):
    class _Controllo:
        def __init__(self, disponibile=True):
            self.disponibile = disponibile

        def rpc_disponibile(self, nome):
            return self.disponibile

    def _ctx_ok(self, **extra):
        base = dict(
            seconda_opinione=_proroga(),
            prove=(eventi.Prova(genere="pagina_collegata", data=date(2026, 12, 1),
                                ruolo="scadenza"),),
        )
        base.update(extra)
        return _ctx(**base)

    def test_ombra_non_scrive(self):
        chiamate = []
        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="ombra"),
            rpc=lambda n, p: chiamate.append((n, p)),
            controllo=self._Controllo(),
        )
        self.assertFalse(esito.scritto)
        self.assertEqual(esito.motivo, "modalita ombra")
        self.assertEqual(chiamate, [])
        # In ombra l'evento si registra comunque, ma non leggibile.
        self.assertFalse(esito.riga["leggibile"])

    def test_attivo_chiama_la_rpc(self):
        chiamate = []
        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="attivo"),
            rpc=lambda n, p: chiamate.append((n, p)),
            controllo=self._Controllo(),
        )
        self.assertTrue(esito.scritto)
        self.assertEqual(chiamate[0][0], eventi.RPC_REGISTRA_EVENTO)
        self.assertEqual(esito.colonne["data_scadenza"], "2026-12-01")
        self.assertTrue(esito.colonne["data_scadenza_verificata"])

    def test_applicato_e_quello_che_dice_la_rpc(self):
        # La RPC risponde {id, nuovo, applicato}: con date incoerenti o uno
        # stato che il CHECK non ammette l'evento si registra ma non si applica.
        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="attivo"),
            rpc=lambda n, p: {"id": 5, "nuovo": True, "applicato": False},
            controllo=self._Controllo(),
        )
        self.assertTrue(esito.scritto)
        self.assertFalse(esito.applicato)

    def test_applicato_anche_dalla_risposta_di_postgrest(self):
        risposta = type("R", (), {"data": {"id": 5, "nuovo": True, "applicato": True}})()
        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="attivo"),
            rpc=lambda n, p: risposta, controllo=self._Controllo(),
        )
        self.assertTrue(esito.applicato)

    def test_rpc_assente_degrada_in_ombra(self):
        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="attivo"),
            rpc=lambda n, p: None,
            controllo=self._Controllo(disponibile=False),
        )
        self.assertFalse(esito.scritto)
        self.assertEqual(esito.motivo, "rpc_assente")

    def test_rpc_fallita_non_solleva(self):
        def esplode(nome, parametri):
            raise RuntimeError("PGRST202")

        esito = eventi.applica(
            _proroga(), self._ctx_ok(modalita="attivo"),
            rpc=esplode, controllo=self._Controllo(),
        )
        self.assertFalse(esito.scritto)
        self.assertIn("rpc fallita", esito.motivo)

    def test_gate_falliti_non_scrivono(self):
        esito = eventi.applica(
            _proroga(url_prova=URL_AGGREGATORE), self._ctx_ok(modalita="attivo"),
            rpc=lambda n, p: None, controllo=self._Controllo(),
        )
        self.assertFalse(esito.scritto)
        self.assertEqual(esito.colonne, {})


class TestLeggiEventi(unittest.TestCase):
    class _Blocco:
        def __init__(self, nome, ingresso):
            self.name = nome
            self.input = ingresso

    class _Risposta:
        def __init__(self, contenuto):
            self.content = contenuto

    def test_lettura_del_tool(self):
        risposta = self._Risposta([self._Blocco("salva_eventi", {"eventi": [
            {"tipo": "proroga", "campo": "data_scadenza", "valore": "2026-12-01",
             "citazione": CITAZIONE, "url_prova": URL, "confidenza": 0.9},
        ]})])
        letti = eventi.leggi_eventi(risposta)
        self.assertEqual(len(letti), 1)
        self.assertEqual(letti[0].tipo, "proroga")
        self.assertEqual(letti[0].data_valore, date(2026, 12, 1))

    def test_tipo_non_proponibile_scartato(self):
        risposta = self._Risposta([self._Blocco("salva_eventi", {"eventi": [
            {"tipo": "fusione", "citazione": "x", "url_prova": URL},
            {"tipo": "ritiro", "citazione": "x", "url_prova": URL},
        ]})])
        self.assertEqual(eventi.leggi_eventi(risposta), ())

    def test_risposta_storta_non_solleva(self):
        self.assertEqual(eventi.leggi_eventi(None), ())
        self.assertEqual(eventi.leggi_eventi(self._Risposta([])), ())
        self.assertEqual(
            eventi.leggi_eventi(self._Risposta([self._Blocco("altro", {})])), ())

    def test_strumento_dichiara_solo_i_tipi_proponibili(self):
        enum = eventi.STRUMENTO_SALVA_EVENTI["input_schema"]["properties"]["eventi"][
            "items"]["properties"]["tipo"]["enum"]
        self.assertEqual(tuple(enum), eventi.TIPI_PROPONIBILI)
        for interno in eventi.TIPI_INTERNI:
            self.assertNotIn(interno, enum)


class TestPrompt(unittest.TestCase):
    def test_contiene_oggi_stato_date_e_pagine(self):
        testo = eventi.prompt_utente(_ctx())
        self.assertIn("2026-09-23", testo)
        self.assertIn("aperto", testo)
        self.assertIn("2026-10-06", testo)
        self.assertIn(URL, testo)

    def test_primo_controllo_lo_dichiara(self):
        testo = eventi.prompt_utente(_ctx(diff=None, testo_prima=None))
        self.assertIn("primo controllo", testo)

    def test_solo_link_cambiati_non_e_un_primo_controllo(self):
        diff = impronte.Diff(link_aggiunti=("https://lazioeuropa.it/faq.pdf",),
                             rumore=False, rilevante=True)
        testo = eventi.prompt_utente(_ctx(diff=diff))
        self.assertNotIn("primo controllo", testo)
        self.assertIn("solo i link", testo)


class TestAllineaDoppioni(unittest.TestCase):
    MASTER = {
        "id": 905315, "stato_bando": "aperto", "data_apertura": "2026-10-22",
        "data_scadenza": "2026-12-01", "link_candidatura": "https://ente.it/domanda",
        "fonte_ufficiale_url": URL,
    }

    def test_copia_stato_date_e_cta(self):
        doppioni = [{"id": 942936, "stato_processing": "completed"}]
        esiti = eventi.allinea_doppioni(self.MASTER, doppioni)
        self.assertEqual(len(esiti), 1)
        self.assertEqual(esiti[0].colonne["stato_bando"], "aperto")
        self.assertEqual(esiti[0].colonne["data_scadenza"], "2026-12-01")
        self.assertEqual(
            esiti[0].colonne["link_candidatura_source"], eventi.SORGENTE_CANDIDATURA_LINK)
        self.assertEqual(esiti[0].evento["tipo"], "rettifica")

    def test_sorgente_di_ripiego(self):
        master = dict(self.MASTER, link_candidatura=None)
        esiti = eventi.allinea_doppioni(master, [{"id": 1, "stato_processing": "completed"}])
        self.assertEqual(
            esiti[0].colonne["link_candidatura_source"], eventi.SORGENTE_CANDIDATURA_FONTE)

    def test_sorgente_assente(self):
        master = dict(self.MASTER, link_candidatura=None, fonte_ufficiale_url=None)
        esiti = eventi.allinea_doppioni(master, [{"id": 1, "stato_processing": "completed"}])
        self.assertEqual(
            esiti[0].colonne["link_candidatura_source"], eventi.SORGENTE_CANDIDATURA_ASSENTE)
        self.assertIsNone(esiti[0].colonne["link_candidatura"])

    def test_solo_i_valori_ammessi_dal_check(self):
        ammessi = {
            eventi.SORGENTE_CANDIDATURA_LINK,
            eventi.SORGENTE_CANDIDATURA_FONTE,
            eventi.SORGENTE_CANDIDATURA_ASSENTE,
        }
        self.assertEqual(ammessi, {"extracted", "fallback_source", "missing"})

    def test_date_incoerenti_bloccano_il_doppione(self):
        # Il doppione ha una data_pubblicazione posteriore alla scadenza del
        # master: non si scrive niente, si emette elaborazione_bloccata.
        doppioni = [{"id": 1, "stato_processing": "completed",
                     "data_pubblicazione": "2027-01-01"}]
        esiti = eventi.allinea_doppioni(self.MASTER, doppioni)
        self.assertTrue(esiti[0].bloccato)
        self.assertEqual(esiti[0].colonne, {})
        self.assertEqual(esiti[0].evento["tipo"], "elaborazione_bloccata")

    def test_doppione_non_completed_saltato(self):
        esiti = eventi.allinea_doppioni(
            self.MASTER, [{"id": 1, "stato_processing": "enriched"}])
        self.assertEqual(esiti[0].colonne, {})
        self.assertFalse(esiti[0].bloccato)

    def test_non_scrive_se_non_attivo(self):
        scritture = []
        esiti = eventi.allinea_doppioni(
            self.MASTER, [{"id": 1, "stato_processing": "completed"}],
            attivo=False, scrivi=lambda i, c: scritture.append((i, c)) or True,
        )
        self.assertFalse(esiti[0].scritto)
        self.assertEqual(scritture, [])

    def test_scrive_se_attivo(self):
        scritture = []
        esiti = eventi.allinea_doppioni(
            self.MASTER, [{"id": 1, "stato_processing": "completed"}],
            attivo=True, scrivi=lambda i, c: scritture.append((i, c)) or True,
        )
        self.assertTrue(esiti[0].scritto)
        self.assertEqual(scritture[0][0], 1)


class TestRegistraViaRpc(unittest.TestCase):
    """Primo passo dell'attivazione per tipo: registra senza applicare e
    restituisce `{id, nuovo}` (contratto di ottobre 2026, §3)."""

    class _Controllo:
        def __init__(self, disponibile=True):
            self.disponibile = disponibile

        def rpc_disponibile(self, _nome):
            return self.disponibile

    RIGA = {"bando_id": 7, "tipo": "proroga", "origine": "worker",
            "valore_dopo": {"data_scadenza": "2026-11-30"}, "applicato": True,
            "leggibile": True, "in_aggiornamenti": True, "citazione": "prorogato"}

    def test_non_applica_e_non_rende_leggibile(self):
        chiamate = []

        def rpc(nome, parametri):
            chiamate.append((nome, parametri))
            return type("R", (), {"data": {"id": 42, "nuovo": True, "applicato": False}})()

        esito = eventi.registra_via_rpc(self.RIGA, rpc=rpc, controllo=self._Controllo())
        self.assertEqual(esito, {"id": 42, "nuovo": True})
        ((nome, parametri),) = chiamate
        self.assertEqual(nome, eventi.RPC_REGISTRA_EVENTO)
        # Anche da una riga «attiva», la registrazione non applica niente.
        self.assertFalse(parametri["p_applica"])
        # Giro 3 (§14, nota di db e della revisione #141): un evento che la
        # RPC poi marca (superato, transizione non ammessa) deve restare
        # invisibile. Nasce `leggibile=false`, sempre.
        self.assertFalse(parametri["p_leggibile"])
        self.assertFalse(parametri["p_in_aggiornamenti"])
        self.assertEqual(parametri["p_valore_dopo"], {"data_scadenza": "2026-11-30"})
        self.assertEqual(set(parametri), set(eventi.PARAMETRI_REGISTRA_EVENTO))

    def test_la_dedup_dice_nuovo_false(self):
        def rpc(_nome, _parametri):
            return {"id": 9, "nuovo": False, "applicato": False}
        self.assertEqual(eventi.registra_via_rpc(self.RIGA, rpc=rpc, controllo=self._Controllo()),
                         {"id": 9, "nuovo": False})

    def test_senza_la_chiave_nuovo_non_si_sa(self):
        # Revisione avversaria del 30/09/2026: il default «vero» sceglieva il
        # ramo che applica. Chiave assente (o non booleana) → None → ombra.
        for risposta in ({"id": 9, "applicato": False}, {"id": 9, "nuovo": "si"}):
            with self.subTest(risposta=risposta):
                esito = eventi.registra_via_rpc(
                    self.RIGA, rpc=lambda _n, _p, r=risposta: r, controllo=self._Controllo())
                self.assertEqual(esito, {"id": 9, "nuovo": None})

    def test_rpc_assente_fallita_o_senza_id(self):
        def rotta(_nome, _parametri):
            raise RuntimeError("503")

        def muta(_nome, _parametri):
            return {"nuovo": True}

        self.assertIsNone(eventi.registra_via_rpc(
            self.RIGA, rpc=muta, controllo=self._Controllo(disponibile=False)))
        self.assertIsNone(eventi.registra_via_rpc(
            self.RIGA, rpc=rotta, controllo=self._Controllo()))
        self.assertIsNone(eventi.registra_via_rpc(
            self.RIGA, rpc=muta, controllo=self._Controllo()))


if __name__ == "__main__":       # pragma: no cover
    unittest.main()


class TestTipiDelPayload(unittest.TestCase):
    """Il payload deve stare nei tipi che la tabella ha davvero.

    Difetto misurato il 25/09/2026, dopo due giorni di ombra a vuoto:
    `bando_evento.confidenza` e' uno **smallint**, e qui ci finiva la frazione
    0-1 del giudizio. Postgres rifiutava ogni INSERT con 22P02 («invalid input
    syntax for type smallint: "0.65"»), `db.registra_evento` ne faceva un
    warning, e il giro si dichiarava riuscito: **nessun evento del monitor era
    mai arrivato a DB**. Il resolver scriveva sulla stessa colonna un intero
    0-100, quindi la tabella aveva due scale e nessuno l'aveva notato.

    I tipi qui sotto sono quelli letti dallo schema OpenAPI del DB di
    produzione il 25/09/2026: se una migrazione li cambia, questo test va
    aggiornato **insieme** alla migrazione.
    """

    #: colonna -> tipi Python ammessi (None e' sempre ammesso)
    TIPI = {
        "bando_id": (int,),
        "tipo": (str,),
        "origine": (str,),
        "campo": (str,),
        "valore_prima": (dict,),
        "valore_dopo": (dict,),
        "data_evento": (str,),
        "citazione": (str,),
        "url_prova": (str,),
        "verificato": (bool,),
        "leggibile": (bool,),
        "in_aggiornamenti": (bool,),
        "applicato": (bool,),
        "confidenza": (int,),          # smallint: NON un float
        "gate": (dict, str),           # jsonb
    }

    def _riga(self, **giudizio):
        valori = {"ammesso": False, "gate": "G2", "superati": ("G1",),
                  "falliti": (("G6", "senza parola chiave"),), "confidenza": 0.65}
        valori.update(giudizio)
        g = eventi.Giudizio(**valori)
        e = eventi.Evento(
            tipo="rettifica", campo="data_scadenza", valore="2026-12-01",
            citazione="il termine e' differito al 1 dicembre 2026",
            url_prova="https://regione.esempio.it/bando")
        ctx = eventi.Contesto(bando_id=1, stato_bando="aperto", modalita="ombra")
        return eventi.riga_evento(e, ctx, g)

    def test_ogni_campo_sta_nel_suo_tipo(self):
        riga = self._riga()
        for campo, valore in riga.items():
            with self.subTest(campo=campo):
                self.assertIn(campo, self.TIPI,
                              f"campo nuovo senza tipo dichiarato: {campo}")
                if valore is None:
                    continue
                self.assertIsInstance(valore, self.TIPI[campo])

    def test_la_confidenza_e_un_intero_da_0_a_100(self):
        # La stessa scala del resolver (`int(esito.confidenza)`), non due.
        for frazione, atteso in ((0.0, 0), (0.65, 65), (0.999, 100), (1.0, 100)):
            riga = self._riga(confidenza=frazione)
            self.assertIsInstance(riga["confidenza"], int)
            self.assertEqual(riga["confidenza"], atteso)

    def test_la_confidenza_fuori_scala_non_sfonda_lo_smallint(self):
        # Un giudizio malformato non deve poter scrivere 320 in una colonna che
        # per contratto tiene 0-100.
        for frazione in (-3.0, 12.5):
            riga = self._riga(confidenza=frazione)
            self.assertGreaterEqual(riga["confidenza"], 0)
            self.assertLessEqual(riga["confidenza"], 100)

    def test_gate_porta_i_falliti_e_non_solo_il_nome(self):
        # Senza i falliti, un respinto registrato non dice perche' e' stato
        # respinto: e' la sola informazione per cui si registra.
        riga = self._riga()
        self.assertIsInstance(riga["gate"], dict)
        self.assertEqual(riga["gate"]["g2"], "G2")
        self.assertEqual(riga["gate"]["superati"], ["G1"])
        self.assertEqual(riga["gate"]["falliti"],
                         [{"gate": "G6", "motivo": "senza parola chiave"}])
