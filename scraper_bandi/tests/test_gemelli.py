# -*- coding: utf-8 -*-
"""Gemelli, doppioni e master (piano §5 passo 2, §14, §16.2 M9).

I due test che il piano chiede per nome:
  * le edizioni «2025»/«2026» e i «lotto 1»/«lotto 2» **non** sono doppioni:
    il fuzzy li vede (0,97-0,98) ma non fonde mai;
  * la coppia reale 942936 (fonte 449) ↔ 905315 (fonte 237) e' un gemello
    esatto **per URL**, e le due righe sono di fonti diverse (§16.2 M9).

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest

from tests.supporto import carica_modulo

gemelli = carica_modulo("gemelli")

# Caso guida di §14: la scheda OE e la pagina di Lazio Europa.
OE_942936 = {
    "id": 942936,
    "fonte_id": 449,
    "tipo_link": "Opportunità",
    "titolo_raw": "Psicologia scolastica",
    "link_bando": "https://obiettivoeuropa.com/bandi/942936",
    "fonte_ufficiale_url": "https://www.lazioeuropa.it/bandi/psicologia-scolastica/",
    "raw_data": {"source": "obiettivo_europa", "id": "942936"},
}
LAZIO_905315 = {
    "id": 905315,
    "fonte_id": 237,
    "tipo_link": "Opportunità",
    "titolo_raw": None,                      # fonte 237 non porta il titolo
    "link_bando": "https://lazioeuropa.it/bandi/psicologia-scolastica",
    "fonte_ufficiale_stato": "trovata",
    "fonte_ufficiale_tipo": "ente",
    "pubblicato_at": "2026-01-02",
}


class CoppiaReale(unittest.TestCase):
    def test_gemello_esatto_per_url_cross_fonte(self):
        trovate = gemelli.criteri_esatti(OE_942936, [LAZIO_905315])
        self.assertEqual(len(trovate), 1)
        self.assertEqual(trovate[0].bando_id, 905315)
        self.assertEqual(trovate[0].criterio, "url")
        self.assertTrue(trovate[0].applicabile)

    def test_il_criterio_url_non_richiede_la_stessa_fonte(self):
        # §16.2 M9: le 24 coppie misurate e il caso guida sono tutte cross-fonte.
        self.assertNotEqual(OE_942936["fonte_id"], LAZIO_905315["fonte_id"])

    def test_il_master_e_la_pagina_dell_ente(self):
        master, corrispondenza = gemelli.trova_master(OE_942936, [LAZIO_905315])
        self.assertEqual(master["id"], 905315)
        self.assertEqual(corrispondenza.criterio, "url")

    def test_www_e_slash_finale_non_impediscono_il_riconoscimento(self):
        self.assertEqual(
            gemelli.url_del_bando(LAZIO_905315)[0],
            "https://lazioeuropa.it/bandi/psicologia-scolastica",
        )


class EdizioniELotti(unittest.TestCase):
    """Non sono doppioni: il fuzzy li propone, nessuno li fonde."""

    EDIZIONE_2025 = {
        "id": 1, "regione": "Marche", "fonte_id": 10,
        "titolo_raw": "Avviso pubblico per la formazione dei docenti - edizione 2025",
        "link_bando": "https://regione.marche.it/bandi/formazione-2025",
    }
    EDIZIONE_2026 = {
        "id": 2, "regione": "Marche", "fonte_id": 10,
        "titolo_raw": "Avviso pubblico per la formazione dei docenti - edizione 2026",
        "link_bando": "https://regione.marche.it/bandi/formazione-2026",
    }
    LOTTO_1 = {
        "id": 3, "ente_erogatore": "Comune di Esempio", "fonte_id": 11,
        "titolo_raw": "Bando servizi educativi - lotto 1",
        "link_bando": "https://comune.esempio.it/bandi/servizi-lotto-1",
    }
    LOTTO_2 = {
        "id": 4, "ente_erogatore": "Comune di Esempio", "fonte_id": 11,
        "titolo_raw": "Bando servizi educativi - lotto 2",
        "link_bando": "https://comune.esempio.it/bandi/servizi-lotto-2",
    }

    def test_nessun_criterio_esatto(self):
        self.assertEqual(gemelli.criteri_esatti(self.EDIZIONE_2025, [self.EDIZIONE_2026]), ())
        self.assertEqual(gemelli.criteri_esatti(self.LOTTO_1, [self.LOTTO_2]), ())

    def test_il_fuzzy_li_vede_ma_non_li_fonde(self):
        for candidato, altro in ((self.EDIZIONE_2025, self.EDIZIONE_2026),
                                 (self.LOTTO_1, self.LOTTO_2)):
            proposte = gemelli.possibili_doppioni(candidato, [altro])
            self.assertEqual(len(proposte), 1, candidato["titolo_raw"])
            self.assertGreaterEqual(proposte[0].similarita, gemelli.SOGLIA_FUZZY)
            self.assertFalse(proposte[0].applicato)

    def test_la_proposta_dice_perche_dubitare(self):
        proposta = gemelli.possibili_doppioni(self.EDIZIONE_2025, [self.EDIZIONE_2026])[0]
        self.assertEqual(
            proposta.differenze, ("anno 2025", "anno 2026", "edizione 2025", "edizione 2026")
        )
        proposta = gemelli.possibili_doppioni(self.LOTTO_1, [self.LOTTO_2])[0]
        self.assertEqual(proposta.differenze, ("lotto 1", "lotto 2"))

    def test_senza_blocking_nessuna_proposta(self):
        estraneo = dict(self.EDIZIONE_2026, id=9, regione="Puglia",
                        link_bando="https://regione.puglia.it/x")
        self.assertEqual(gemelli.possibili_doppioni(self.EDIZIONE_2025, [estraneo]), ())

    def test_titoli_diversi_sotto_soglia(self):
        altro = dict(self.EDIZIONE_2026, id=8,
                     titolo_raw="Contributi per la digitalizzazione delle scuole")
        self.assertEqual(gemelli.possibili_doppioni(self.EDIZIONE_2025, [altro]), ())

    def test_stessa_fonte_ufficiale_due_lotti_nessun_criterio_esatto(self):
        # Il passo 1 della cascata assegna la stessa pagina d'ente a due lotti
        # (e due righe Italia Domani sullo stesso portale si comportano uguale):
        # la coppia fonte ufficiale contro fonte ufficiale non e' in §16.2 M9 e
        # non deve autorizzare nessuna fusione.
        pagina = "https://regione.marche.it/bandi/avviso-servizi"
        uno = {"id": 10, "fonte_id": 7, "titolo_raw": "Avviso lotto 1",
               "link_bando": "https://regione.marche.it/bandi/1",
               "fonte_ufficiale_url": pagina}
        due = {"id": 11, "fonte_id": 7, "titolo_raw": "Avviso lotto 2",
               "link_bando": "https://regione.marche.it/bandi/2",
               "fonte_ufficiale_url": pagina}
        self.assertEqual(gemelli.criteri_esatti(uno, [due]), ())
        self.assertIsNone(gemelli.trova_master(uno, [due]))

    def test_il_link_bando_di_uno_e_la_fonte_ufficiale_dell_altro_basta(self):
        # E' la forma del caso guida: un lato della coincidenza e' un
        # `link_bando`, e allora il gemello e' certo.
        uno = {"id": 20, "fonte_id": 7, "link_bando": "https://oe.example/x",
               "fonte_ufficiale_url": "https://regione.marche.it/bandi/avviso"}
        due = {"id": 21, "fonte_id": 8, "link_bando": "https://regione.marche.it/bandi/avviso/"}
        trovate = gemelli.criteri_esatti(uno, [due])
        self.assertEqual((trovate[0].bando_id, trovate[0].criterio), (21, "url"))


class ChiaveEsterna(unittest.TestCase):
    def test_obiettivo_europa_usa_l_id(self):
        self.assertEqual(gemelli.chiave_esterna(OE_942936), "oe:942936")

    def test_obiettivo_europa_senza_id_usa_il_percorso(self):
        # Le 545 righe chiuse fuori listing non hanno `id`: il percorso
        # `/bandi/<slug>` resta stabile.
        riga = {"fonte_id": 449, "link_bando": "https://obiettivoeuropa.com/bandi/psicologia/",
                "raw_data": {"source": "obiettivo_europa"}}
        self.assertEqual(gemelli.chiave_esterna(riga), "oe:/bandi/psicologia")

    def test_incentivi_e_italia_domani(self):
        self.assertEqual(
            gemelli.chiave_esterna({"raw_data": {"source": "incentivi_gov_it", "nid": "7788"}}),
            "incentivi:7788",
        )
        self.assertEqual(
            gemelli.chiave_esterna({"raw_data": {"source": "italia_domani", "external_id": "M4C1"}}),
            "italiadomani:M4C1",
        )

    def test_calendario_codice_poi_titolo_e_data_poi_riga(self):
        self.assertEqual(
            gemelli.chiave_esterna({"codice": "AV-12", "titolo_raw": "Avviso"}),
            "calendario:AV-12",
        )
        self.assertEqual(
            gemelli.chiave_esterna({"titolo_raw": "Avviso scuole", "data_scadenza": "2026-12-01"}),
            "calendario:avviso scuole|2026-12-01",
        )
        self.assertEqual(
            gemelli.chiave_esterna({
                "titolo_raw": "Avviso scuole",
                "raw_data": {"source_url": "https://x.it/f.csv", "row_index": 4},
            }),
            "calendario:avviso scuole|https://x.it/f.csv|r4",
        )

    def test_nessuna_chiave_quando_non_c_e_niente_di_stabile(self):
        self.assertIsNone(gemelli.chiave_esterna({"raw_data": {}}))

    def test_la_chiave_vale_solo_dentro_la_stessa_fonte(self):
        a = {"id": 1, "fonte_id": 10, "raw_data": {"source": "incentivi_gov_it", "nid": "5"}}
        b = {"id": 2, "fonte_id": 11, "raw_data": {"source": "incentivi_gov_it", "nid": "5"}}
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())
        b_stessa_fonte = dict(b, fonte_id=10)
        trovate = gemelli.criteri_esatti(a, [b_stessa_fonte])
        self.assertEqual(trovate[0].criterio, "chiave_esterna")


class NumeroAtto(unittest.TestCase):
    def test_forme_riconosciute(self):
        self.assertEqual(gemelli.numero_atto({"titolo_raw": "DGR n. 123/2026 - approvazione"}), "dgr:123/2026")
        self.assertEqual(gemelli.numero_atto({"titolo_raw": "Determinazione n. 55 del 12/09/2026"}), "determina:55/2026")
        self.assertEqual(gemelli.numero_atto({"numero_atto": "D.D.G. 9 del 01-02-2026"}), "ddg:9/2026")

    def test_senza_anno_nessun_atto(self):
        # «DGR 123» combacerebbe con la delibera 123 di qualunque anno.
        self.assertIsNone(gemelli.numero_atto({"titolo_raw": "DGR n. 123 approvazione"}))

    def test_vale_la_prima_occorrenza_con_anno_non_la_prima_e_basta(self):
        self.assertEqual(
            gemelli.numero_atto(
                {"titolo_raw": "Avviso DD 12 - attuazione della Determinazione n. 55/2026"}
            ),
            "determina:55/2026",
        )

    def test_numeri_lunghi(self):
        self.assertEqual(
            gemelli.numero_atto({"titolo_raw": "Decreto 1234567/2026"}), "decreto:1234567/2026"
        )

    def test_stesso_atto_stesso_dominio(self):
        a = {"id": 1, "fonte_id": 1, "titolo_raw": "DGR n. 123/2026",
             "link_bando": "https://bandi.regione.marche.it/a"}
        b = {"id": 2, "fonte_id": 2, "titolo_raw": "Delibera DGR 123/2026 - avviso",
             "link_bando": "https://www.regione.marche.it/b"}
        trovate = gemelli.criteri_esatti(a, [b])
        self.assertEqual((trovate[0].bando_id, trovate[0].criterio), (2, "atto"))

    def test_stesso_atto_dominio_diverso_non_vale(self):
        a = {"id": 1, "titolo_raw": "DGR n. 123/2026", "link_bando": "https://regione.marche.it/a"}
        b = {"id": 2, "titolo_raw": "DGR n. 123/2026", "link_bando": "https://regione.puglia.it/b"}
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())

    def test_due_comuni_della_stessa_provincia_non_sono_lo_stesso_ente(self):
        # «Determinazione n. NN del GG/MM/AAAA» e' la forma piu' comune dei
        # titoli comunali: bastano due comuni della stessa provincia con lo
        # stesso numero nello stesso anno perche' il dominio registrabile, se
        # si fermasse a `bo.it`, li fondesse in automatico.
        a = {"id": 1, "titolo_raw": "Determinazione n. 55 del 12/09/2026 - servizi educativi",
             "link_bando": "https://comune.imola.bo.it/bandi/a"}
        b = {"id": 2, "titolo_raw": "Determinazione n. 55 del 12/09/2026 - contributi sport",
             "link_bando": "https://comune.casalecchio.bo.it/bandi/b"}
        self.assertEqual(gemelli.numero_atto(a), gemelli.numero_atto(b))
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())

    def test_comune_e_provincia_dello_stesso_capoluogo_non_si_fondono(self):
        a = {"id": 1, "titolo_raw": "Determinazione n. 7/2026",
             "link_bando": "https://comune.firenze.it/bandi/a"}
        b = {"id": 2, "titolo_raw": "Determinazione n. 7/2026",
             "link_bando": "https://provincia.firenze.it/bandi/b"}
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())

    def test_un_atto_su_un_aggregatore_non_vale(self):
        a = {"id": 1, "titolo_raw": "DGR n. 123/2026", "link_bando": "https://obiettivoeuropa.com/a"}
        b = {"id": 2, "titolo_raw": "DGR n. 123/2026", "link_bando": "https://obiettivoeuropa.com/b"}
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())


class SceltaDelMaster(unittest.TestCase):
    def test_ordine_di_sezione_14(self):
        ente = {"id": 2, "fonte_ufficiale_stato": "trovata", "fonte_ufficiale_tipo": "ente",
                "link_bando": "https://regione.marche.it/a", "pubblicato_at": "2026-05-01"}
        aggregatore = {"id": 1, "link_bando": "https://obiettivoeuropa.com/a",
                       "tipo_link": "Opportunità", "pubblicato_at": "2020-01-01"}
        self.assertEqual(gemelli.scegli_master([aggregatore, ente])["id"], 2)

    def test_non_aggregatore_prima_di_opportunita(self):
        a = {"id": 1, "link_bando": "https://obiettivoeuropa.com/a", "tipo_link": "Opportunità"}
        b = {"id": 2, "link_bando": "https://regione.marche.it/b", "tipo_link": "Preavviso"}
        self.assertEqual(gemelli.scegli_master([a, b])["id"], 2)

    def test_eventi_poi_data_poi_contenuto(self):
        base = {"link_bando": "https://regione.marche.it/x", "tipo_link": "Opportunità"}
        a = dict(base, id=1, eventi_verificati=0, pubblicato_at="2026-01-01", contenuto="xxx")
        b = dict(base, id=2, eventi_verificati=3, pubblicato_at="2026-06-01", contenuto="x")
        self.assertEqual(gemelli.scegli_master([a, b])["id"], 2)
        c = dict(base, id=3, eventi_verificati=3, pubblicato_at="2025-06-01", contenuto="x")
        self.assertEqual(gemelli.scegli_master([b, c])["id"], 3)

    def test_deterministico_a_parita_di_tutto(self):
        a = {"id": 7, "link_bando": "https://x.it/a"}
        b = {"id": 3, "link_bando": "https://x.it/b"}
        self.assertEqual(gemelli.scegli_master([a, b])["id"], gemelli.scegli_master([b, a])["id"])

    def test_elenco_vuoto(self):
        self.assertIsNone(gemelli.scegli_master([]))


class TrovaMaster(unittest.TestCase):
    def test_nessun_criterio_esatto_nessun_master(self):
        a = {"id": 1, "regione": "Marche", "titolo_raw": "Avviso formazione docenti 2025",
             "link_bando": "https://regione.marche.it/a"}
        b = {"id": 2, "regione": "Marche", "titolo_raw": "Avviso formazione docenti 2026",
             "link_bando": "https://regione.marche.it/b"}
        self.assertIsNone(gemelli.trova_master(a, [b]))

    def test_non_si_riconosce_da_sola(self):
        self.assertIsNone(gemelli.trova_master(LAZIO_905315, [LAZIO_905315]))



# --- riga di calendario e passo `gemelli` (contratto `bandi-giro-2` §19.9) ----
#
# Righe vere del DB bandi (lette in GET il 30/09/2026): calendari pubblici, senza
# dati personali. 803614-803623 sono il PDF del calendario FSE+ di VdA (fonte
# 280), 803629-803642 il CSV dello stesso calendario; 1260432 e 1260443 la
# stessa tabella su due pagine del documento Interreg Alpine Space; 5596 e 40744
# la stessa riga del foglio del PN Cultura letto in http e in https.

RIGHE_REALI = {5596: {'id': 5596,
        'fonte_id': 288,
        'link_bando': None,
        'titolo_raw': 'Avviso per la presentazione di proposte progettuali a valere sulla Linea di '
                      'intervento “Progetti locali di rigenerazione a base culturale” dell‘Azione '
                      '4.6.1.',
        'pubblicato_at': '2026-06-29T11:32:08.586756+00:00',
        'raw_data': {'AREA': 'Territori delle regioni: Molise, Campania, Puglia, Basilicata, '
                             'Calabria, Sicilia, Sardegna',
                     'FONDO': 'FESR',
                     'STATO': 'ITALIA',
                     'REGIONE': '14,15,16,17,18,19,20',
                     'PROGRAMMA': '2021IT16RFPR003',
                     'row_index': 0,
                     'source_url': 'http://pncultura2127.cultura.gov.it/wp-content/uploads/2026/06/CalendarioAvvisi_Opportunita_CCI2021IT16RFPR003.xlsx',
                     'DATA_APERTURA': '2026-06-30 00:00:00',
                     'DATA_CHIUSURA': '2026-10-30 00:00:00',
                     'AMMIN_EMANANTE': "Servizio V della DG BPM nell'ambito del DiAG del Ministero "
                                       'della Cultura',
                     'CODICE_FISCALE': 80188210589,
                     'IMPORTO_TOTALE': 29400000.0,
                     'CATEG_PROCEDURA': 'Aperta',
                     'IMPORTO_AMMESSO': 29400000.0,
                     'TIPO_RICHIEDENTE': 'Enti Locali',
                     'CATEG_RICHIEDENTE': 'Pubblica Amministrazione',
                     'STATO_OPPORTUNITA': 'Preavviso',
                     'OBIETTIVO_STRATEGICO': 'OS4'}},
 40744: {'id': 40744,
         'fonte_id': 288,
         'link_bando': None,
         'titolo_raw': 'Avviso per la presentazione di proposte progettuali a valere sulla Linea '
                       'di intervento “Progetti locali di rigenerazione a base culturale” '
                       'dell‘Azione 4.6.1.',
         'pubblicato_at': '2026-07-01T10:04:12.721733+00:00',
         'raw_data': {'AREA': 'Territori delle regioni: Molise, Campania, Puglia, Basilicata, '
                              'Calabria, Sicilia, Sardegna',
                      'FONDO': 'FESR',
                      'STATO': 'ITALIA',
                      'REGIONE': '14,15,16,17,18,19,20',
                      'PROGRAMMA': '2021IT16RFPR003',
                      'row_index': 0,
                      'source_url': 'https://pncultura2127.cultura.gov.it/wp-content/uploads/2026/06/CalendarioAvvisi_Opportunita_CCI2021IT16RFPR003.xlsx',
                      'DATA_APERTURA': '2026-06-30 00:00:00',
                      'DATA_CHIUSURA': '2026-10-30 00:00:00',
                      'AMMIN_EMANANTE': "Servizio V della DG BPM nell'ambito del DiAG del "
                                        'Ministero della Cultura',
                      'CODICE_FISCALE': 80188210589,
                      'IMPORTO_TOTALE': 29400000.0,
                      'CATEG_PROCEDURA': 'Aperta',
                      'IMPORTO_AMMESSO': 29400000.0,
                      'TIPO_RICHIEDENTE': 'Enti Locali',
                      'CATEG_RICHIEDENTE': 'Pubblica Amministrazione',
                      'STATO_OPPORTUNITA': 'Preavviso',
                      'OBIETTIVO_STRATEGICO': 'OS4'}},
 803610: {'id': 803610,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'f. 3-2025',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'page': 1,
                       'col_1': 'Avviso per il contributo in forma di voucher a\n'
                                'imprese ed enti di ricerca per il finanziamento di\n'
                                'borse di ricerca per giovani ricercatori',
                       'col_2': 'OS f) ESO4.6 Promuovere la parità di accesso e di completamento '
                                'di un’istruzione e una\n'
                                'formazione inclusive e di qualità, in particolare per i gruppi '
                                'svantaggiati, dall’educazione e\n'
                                'cura della prima infanzia, attraverso l’istruzione e la '
                                'formazione generale e professionale, fino\n'
                                'al livello terziario e all’istruzione e all’apprendimento degli '
                                'adulti, anche agevolando la\n'
                                'mobilità ai fini dell’apprendimento per tutti e l’accessibilità '
                                'per le persone con disabilità',
                       'col_3': "Valle d'Aosta",
                       'col_4': "Enti di ricerca e\nImprese con\nsede operativa in\nValle d'Aosta",
                       'col_5': '1.000.000,00',
                       'col_6': 'procedura a sportello\n'
                                'apertura: settembre 2026\n'
                                'chiusura: 31 dicembre 2029',
                       'row_index': 4,
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.pdf',
                       'table_index': 0}},
 803612: {'id': 803612,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'a.1-2026',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'page': 1,
                       'col_1': 'Avviso pubblico per il finanziamento di iniziative\n'
                                "formative per l'occupabilità (26AC)",
                       'col_2': 'OS a) ESO4.1 Migliorare l’accesso all’occupazione e le misure di '
                                'attivazione per tutte le\n'
                                'persone in cerca di lavoro, inparticolare i giovani, soprattutto '
                                'attraverso l’attuazione della\n'
                                'garanzia per i giovani, i disoccupati di lungo periodo e igruppi '
                                'svantaggiati nel mercato del\n'
                                'lavoro, nonché delle persone inattive, anche mediante la '
                                'promozione del lavoro autonomo e\n'
                                'dell’economia sociale',
                       'col_3': "Valle d'Aosta",
                       'col_4': 'Enti di\nformazione\naccreditati',
                       'col_5': '3.000.000,00',
                       'col_6': '2^ finestra: 08/09/2026 - 08/10/2026\n'
                                '3^ finestra: 23/12/2026 - 28/01/2027\n'
                                '4^ finestra: 15/06/2027 - 01/07/2026\n'
                                '5^ finestra: 07/09/2027 - 30/09/2027\n'
                                '6^ finestra: 27/12/2027-27/01/2028\n'
                                '7^ finestra: 13/06/2028 - 29/06/2028',
                       'row_index': 6,
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.pdf',
                       'table_index': 0}},
 803614: {'id': 803614,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'd.1-2026',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'page': 1,
                       'col_1': 'Avviso pubblico per l’assegnazione di voucher\n'
                                'formativi a favore delle micro imprese –\n'
                                'formazione continua',
                       'col_2': 'OS d) ESO 4.4 Promuovere l’adattamento dei lavoratori, delle '
                                'imprese e degli imprenditori ai\n'
                                'cambiamenti, un invecchiamento attivo e sano, come pure ambienti '
                                'di lavoro sani e adeguati\n'
                                'che tengano conto dei rischi per la salute',
                       'col_3': "Valle d'Aosta",
                       'col_4': 'Microimprese',
                       'col_5': '2.000.000,00',
                       'col_6': 'procedura a sportello in corso\nchiusura domande: 15 luglio 2029',
                       'row_index': 8,
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.pdf',
                       'table_index': 0}},
 803615: {'id': 803615,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'd.1-2023',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'page': 1,
                       'col_1': 'Avviso pubblico “Accrescimento delle\n'
                                'competenze della forza lavoro attraverso la\n'
                                'formazione continua 2023/2026” (Avviso 23AF)',
                       'col_2': 'OS d) ESO 4.4 Promuovere l’adattamento dei lavoratori, delle '
                                'imprese e degli imprenditori ai\n'
                                'cambiamenti, un invecchiamento attivo e sano, come pure ambienti '
                                'di lavoro sani e adeguati\n'
                                'che tengano conto dei rischi per la salute',
                       'col_3': "Valle d'Aosta",
                       'col_4': 'Enti di\nformazione e\nimprese',
                       'col_5': '3.000.000,00',
                       'col_6': 'in corso fino a 31 dicembre 2026',
                       'row_index': 9,
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.pdf',
                       'table_index': 0}},
 803623: {'id': 803623,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'c. 2-2025',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'page': 1,
                       'col_1': 'Misura di conciliazione vita-lavoro: Voucher di\nconciliazione',
                       'col_2': 'OS c) ESO4.3 - Promuovere una partecipazione equilibrata al '
                                'mercato del lavoro sotto il\n'
                                'profile del genere, parità di condizioni di lavoro e un migliore '
                                'equilibrio tra vita professionale e\n'
                                "vita privata, anche attraverso l'accesso a servizi economici di "
                                "assistenza all'infanzia e alle\n"
                                'persone non autosufficienti',
                       'col_3': "Valle d'Aosta",
                       'col_4': 'Cittadini',
                       'col_5': '1.900.000,00',
                       'col_6': 'procedura a sportello in corso\n'
                                'chiusura: 30 ottobre 2026\n'
                                'Previste edizioni annuali fino al 2029',
                       'row_index': 17,
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.pdf',
                       'table_index': 0}},
 803629: {'id': 803629,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'f. 3-2025',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'row_index': 6,
                       'Unnamed: 1': 'Avviso per il contributo in forma di voucher a imprese ed '
                                     'enti di ricerca per il finanziamento di borse di ricerca per '
                                     'giovani ricercatori',
                       'Unnamed: 2': 'OS f) ESO4.6 Promuovere la parità di accesso e di '
                                     'completamento di un\x92istruzione e una formazione inclusive '
                                     'e di qualità, in particolare per i gruppi svantaggiati, '
                                     'dall\x92educazione e cura della prima infanzia, attraverso '
                                     'l\x92istruzione e la formazione generale e professionale, '
                                     'fino al livello terziario e all\x92istruzione e '
                                     'all\x92apprendimento degli adulti, anche agevolando la '
                                     'mobilità ai fini dell\x92apprendimento per tutti e '
                                     'l\x92accessibilità per le persone con disabilità',
                       'Unnamed: 3': "Valle d'Aosta",
                       'Unnamed: 4': 'Enti di ricerca e Imprese con sede operativa in Valle '
                                     "d'Aosta",
                       'Unnamed: 5': '1.000.000,00',
                       'Unnamed: 6': 'procedura a sportello\n'
                                     'apertura: settembre 2026\n'
                                     'chiusura: 31 dicembre 2029',
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.csv'}},
 803631: {'id': 803631,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'a.1-2026',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'row_index': 8,
                       'Unnamed: 1': 'Avviso pubblico per il finanziamento di iniziative formative '
                                     "per l'occupabilità (26AC)",
                       'Unnamed: 2': 'OS a) ESO4.1 Migliorare l\x92accesso all\x92occupazione e le '
                                     'misure di attivazione per tutte le persone in cerca di '
                                     'lavoro, inparticolare i giovani, soprattutto attraverso '
                                     'l\x92attuazione della garanzia per i giovani, i disoccupati '
                                     'di lungo periodo e igruppi svantaggiati nel mercato del '
                                     'lavoro, nonché delle persone inattive, anche mediante la '
                                     'promozione del lavoro autonomo e dell\x92economia sociale',
                       'Unnamed: 3': "Valle d'Aosta",
                       'Unnamed: 4': 'Enti di formazione accreditati',
                       'Unnamed: 5': '3.000.000,00',
                       'Unnamed: 6': '2^ finestra: 08/09/2026 - 08/10/2026\n'
                                     '3^ finestra: 23/12/2026 - 28/01/2027\n'
                                     '4^ finestra: 15/06/2027 - 01/07/2026\n'
                                     '5^ finestra: 07/09/2027 - 30/09/2027\n'
                                     '6^ finestra: 27/12/2027-27/01/2028\n'
                                     '7^ finestra: 13/06/2028 - 29/06/2028',
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.csv'}},
 803633: {'id': 803633,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'd.1-2026',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'row_index': 10,
                       'Unnamed: 1': 'Avviso pubblico per l\x92assegnazione di voucher formativi a '
                                     'favore delle micro imprese \x96\n'
                                     'formazione continua',
                       'Unnamed: 2': 'OS d) ESO 4.4 Promuovere l\x92adattamento dei lavoratori, '
                                     'delle imprese e degli imprenditori ai cambiamenti, un '
                                     'invecchiamento attivo e sano, come pure ambienti di lavoro '
                                     'sani e adeguati che tengano conto dei rischi per la salute',
                       'Unnamed: 3': "Valle d'Aosta",
                       'Unnamed: 4': 'Microimprese',
                       'Unnamed: 5': '2.000.000,00',
                       'Unnamed: 6': 'procedura a sportello in corso\n'
                                     'chiusura domande: 15 luglio 2029',
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.csv'}},
 803634: {'id': 803634,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'd.1-2023',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'row_index': 11,
                       'Unnamed: 1': 'Avviso pubblico \x93Accrescimento delle competenze della '
                                     'forza lavoro attraverso la formazione continua 2023/2026\x94 '
                                     '(Avviso 23AF)',
                       'Unnamed: 2': 'OS d) ESO 4.4 Promuovere l\x92adattamento dei lavoratori, '
                                     'delle imprese e degli imprenditori ai cambiamenti, un '
                                     'invecchiamento attivo e sano, come pure ambienti di lavoro '
                                     'sani e adeguati che tengano conto dei rischi per la salute',
                       'Unnamed: 3': "Valle d'Aosta",
                       'Unnamed: 4': 'Enti di formazione e imprese',
                       'Unnamed: 5': '3.000.000,00',
                       'Unnamed: 6': 'in corso fino a 31 dicembre 2026',
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.csv'}},
 803642: {'id': 803642,
          'fonte_id': 280,
          'link_bando': None,
          'titolo_raw': 'c. 2-2025',
          'pubblicato_at': '2026-08-24T16:04:13.462061+00:00',
          'raw_data': {'row_index': 19,
                       'Unnamed: 1': 'Misura di conciliazione vita-lavoro: Voucher di '
                                     'conciliazione',
                       'Unnamed: 2': 'OS c) ESO4.3 - Promuovere una partecipazione equilibrata al '
                                     'mercato del lavoro sotto il profile del genere, parità di '
                                     'condizioni di lavoro e un migliore equilibrio tra vita '
                                     "professionale e vita privata, anche attraverso l'accesso a "
                                     "servizi economici di assistenza all'infanzia e alle persone "
                                     'non autosufficienti',
                       'Unnamed: 3': "Valle d'Aosta",
                       'Unnamed: 4': 'Cittadini',
                       'Unnamed: 5': '1.900.000,00',
                       'Unnamed: 6': 'procedura a sportello in corso \n'
                                     'chiusura: 30 ottobre 2026\n'
                                     '\n'
                                     'Previste edizioni annuali fino al 2029',
                       'source_url': 'https://new.regione.vda.it/Media/Regione/Hierarchy/299/29905/Calendario%20inviti%20FSE%20Plus%20agosto%202026.csv'}},
 1260432: {'id': 1260432,
           'fonte_id': 324,
           'link_bando': None,
           'titolo_raw': '(Interreg VI-B) Alpine Space',
           'pubblicato_at': '2026-09-23T14:17:34.624277+00:00',
           'raw_data': {'cci': 'Title',
                        'page': 2,
                        'row_index': 0,
                        'source_url': 'https://www.alpine-space.eu/wp-content/uploads/2024/02/Interreg_Alpine_Space_programme_2021-2027-1.pdf',
                        'table_index': 0}},
 1260443: {'id': 1260443,
           'fonte_id': 324,
           'link_bando': None,
           'titolo_raw': '(Interreg VI-B) Alpine Space',
           'pubblicato_at': '2026-09-23T14:48:25.919306+00:00',
           'raw_data': {'page': 3,
                        'col_0': 'Title',
                        'row_index': 2,
                        'source_url': 'https://www.alpine-space.eu/wp-content/uploads/2024/02/Interreg_Alpine_Space_programme_2021-2027-1.pdf',
                        'table_index': 0}}}

#: Le quattro coppie del contratto e le due misurate in piu' il 30/09.
COPPIE_DEL_CONTRATTO = ((803614, 803633), (803615, 803634), (803623, 803642), (1260432, 1260443))
COPPIE_IN_PIU = ((803610, 803629), (5596, 40744))


def _riga(bando_id, **modifiche):
    import copy
    riga = copy.deepcopy(RIGHE_REALI[bando_id])
    riga.update(modifiche)
    return riga


class RigaCalendario(unittest.TestCase):
    def test_le_coppie_del_contratto_e_quelle_misurate_in_piu(self):
        for a, b in COPPIE_DEL_CONTRATTO + COPPIE_IN_PIU:
            with self.subTest(coppia=(a, b)):
                trovate = gemelli.criteri_esatti(_riga(a), [_riga(b)])
                self.assertEqual([(c.bando_id, c.criterio) for c in trovate],
                                 [(b, "riga_calendario")])
                # Il criterio e' simmetrico.
                self.assertEqual([c.bando_id for c in gemelli.criteri_esatti(_riga(b), [_riga(a)])],
                                 [a])

    def test_il_dettaglio_dice_perche(self):
        vda = gemelli.criteri_esatti(_riga(803614), [_riga(803633)])[0]
        self.assertEqual(vda.dettaglio, "stessa chiusura|2029-07-15")
        interreg = gemelli.criteri_esatti(_riga(1260432), [_riga(1260443)])[0]
        self.assertTrue(interreg.dettaglio.startswith("stesso file|https://www.alpine-space.eu/"))

    def test_pdf_e_csv_hanno_la_stessa_descrizione(self):
        """Il CSV perde apostrofi e virgolette e rinomina le colonne."""
        self.assertIn("lassegnazione", gemelli.descrizione_calendario(_riga(803614)))
        for a, b in COPPIE_DEL_CONTRATTO:
            with self.subTest(coppia=(a, b)):
                self.assertEqual(gemelli.descrizione_calendario(_riga(a)),
                                 gemelli.descrizione_calendario(_riga(b)))

    def test_file_diversi_e_nessuna_data_non_bastano(self):
        """803612/803631: stessa riga, ma finestre senza «chiusura»: falso negativo prudente."""
        self.assertIsNone(gemelli.data_chiusura_calendario(_riga(803612)))
        self.assertEqual(gemelli.criteri_esatti(_riga(803612), [_riga(803631)]), ())

    def test_stessa_fonte_date_diverse(self):
        b = _riga(803633)
        b["raw_data"]["Unnamed: 6"] = "procedura a sportello in corso\nchiusura domande: 15 luglio 2030"
        self.assertEqual(gemelli.criteri_esatti(_riga(803614), [b]), ())

    def test_fonti_diverse(self):
        self.assertEqual(gemelli.criteri_esatti(_riga(803614), [_riga(803633, fonte_id=281)]), ())
        self.assertEqual(gemelli.criteri_esatti(_riga(1260432), [_riga(1260443, fonte_id=None)]), ())

    def test_un_link_esclude_il_criterio(self):
        con_link = _riga(803633, link_bando="https://new.regione.vda.it/avviso-voucher")
        self.assertEqual(gemelli.criteri_esatti(_riga(803614), [con_link]), ())
        self.assertEqual(gemelli.criteri_esatti(con_link, [_riga(803614)]), ())

    def test_descrizione_di_meno_di_tre_parole(self):
        a = {"id": 1, "fonte_id": 324, "titolo_raw": None,
             "raw_data": {"cci": "Title", "source_url": "https://x.eu/p.pdf", "page": 2}}
        b = {"id": 2, "fonte_id": 324, "titolo_raw": "",
             "raw_data": {"col_0": "Title", "source_url": "https://x.eu/p.pdf", "page": 3}}
        self.assertEqual(gemelli.descrizione_calendario(a), "")
        self.assertEqual(gemelli.criteri_esatti(a, [b]), ())

    def test_i_metadati_non_contano(self):
        a = _riga(1260432)
        b = _riga(1260432, id=9)
        b["raw_data"].update(page=40, row_index=7, table_index=3)
        self.assertEqual(gemelli.descrizione_calendario(a), gemelli.descrizione_calendario(b))

    def test_la_chiusura_e_la_data_dopo_la_parola(self):
        from datetime import date
        leggi = gemelli.data_chiusura_calendario
        self.assertEqual(leggi({"raw_data": {"col_6": "apertura: 1 gennaio 2027, chiusura: 31 marzo 2027"}}),
                         date(2027, 3, 31))
        self.assertEqual(leggi({"raw_data": {"col_6": "in corso fino a 31 dicembre 2026"}}),
                         date(2026, 12, 31))
        # Colonna di chiusura: la data della cella, anche senza la parola.
        self.assertEqual(leggi({"raw_data": {"DATA_APERTURA": "2026-06-30 00:00:00",
                                             "DATA_CHIUSURA": "2026-10-30 00:00:00"}}),
                         date(2026, 10, 30))
        self.assertIsNone(leggi({"raw_data": {"col_6": "apertura: 1 gennaio 2027"}}))
        self.assertIsNone(leggi({"raw_data": {"source_url": "chiusura 1 gennaio 2027"}}))


class _Fondi:
    def __init__(self, risposta="master"):
        self.chiamate: list = []
        self._risposta = risposta

    def __call__(self, master_id, doppione_id, motivo):
        self.chiamate.append((master_id, doppione_id, motivo))
        return master_id if self._risposta == "master" else self._risposta


def _pubblicati():
    # La pagina dell'ente con un titolo: senza, la coppia per URL non passerebbe
    # la prudenza sui titoli (e il caso guida deve fondersi).
    return [_riga(i, bando_master_id=None) for i in RIGHE_REALI] + [
        dict(OE_942936), dict(LAZIO_905315, titolo="Psicologia scolastica nelle scuole del Lazio"),
    ]


class PassoGemelli(unittest.TestCase):
    def _passo(self, righe=None, **opzioni):
        fondi = opzioni.pop("fondi", _Fondi())
        opzioni.setdefault("modalita", "attivo")
        opzioni.setdefault("tetto", 10)
        esito = gemelli.esegui_passo(
            "06:00", leggi=lambda: righe if righe is not None else _pubblicati(),
            fondi=fondi, **opzioni)
        return esito, fondi

    def test_ombra_elenca_conta_e_non_fonde(self):
        esito, fondi = self._passo(modalita="ombra")
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["modalita"], "ombra")
        self.assertEqual(esito["fusi"], 0)
        self.assertEqual(esito["fusioni_previste"], 7)
        self.assertEqual(esito["coppie_per_criterio"],
                         {"url": 1, "chiave_esterna": 0, "atto": 0, "riga_calendario": 6})
        self.assertEqual(esito["fusioni"], [
            [40744, 5596, "riga_calendario"],
            [803629, 803610, "riga_calendario"],
            [803633, 803614, "riga_calendario"],
            [803634, 803615, "riga_calendario"],
            [803642, 803623, "riga_calendario"],
            [942936, 905315, "url"],
            [1260443, 1260432, "riga_calendario"],
        ])

    def test_attivo_fonde_con_il_master_di_sezione_14(self):
        esito, fondi = self._passo()
        self.assertEqual(esito["fusi"], 7)
        # La scheda dell'aggregatore non diventa master perche' e' piu' vecchia.
        self.assertIn((905315, 942936, "gemello esatto: url"), fondi.chiamate)
        self.assertIn((1260432, 1260443, "gemello esatto: riga_calendario"), fondi.chiamate)

    def test_tetto(self):
        esito, fondi = self._passo(tetto=2)
        self.assertEqual(len(fondi.chiamate), 2)
        self.assertEqual((esito["fusi"], esito["oltre_tetto"]), (2, 5))
        self.assertEqual([c[1] for c in fondi.chiamate], [40744, 803629])

    def test_tetto_zero_spegne_senza_leggere(self):
        def leggi():
            raise AssertionError("con il tetto a zero non si legge niente")
        esito = gemelli.esegui_passo(None, modalita="attivo", tetto=0, leggi=leggi, fondi=_Fondi())
        self.assertEqual(esito["saltato"], "spento")

    def test_le_righe_gia_fuse_restano_fuori(self):
        righe = [_riga(803614, bando_master_id=None), _riga(803633, bando_master_id=803614)]
        esito, fondi = self._passo(righe)
        self.assertEqual((esito["esaminati"], esito["fusioni_previste"]), (1, 0))
        self.assertEqual(fondi.chiamate, [])

    def test_una_catena_e_un_gruppo_che_non_si_fonde_da_solo(self):
        """A=B e B=C sono un gruppo solo, ma C non ha una coppia diretta col master."""
        titolo = "Avviso formazione continua per le imprese 2026"
        a = {"id": 1, "fonte_id": 10, "link_bando": "https://ente.it/a", "titolo": titolo}
        b = {"id": 2, "fonte_id": 11, "link_bando": "https://ente.it/b",
             "fonte_ufficiale_url": "https://ente.it/a", "titolo": titolo}
        c = {"id": 3, "fonte_id": 12, "fonte_ufficiale_url": "https://ente.it/b", "titolo": titolo}
        self.assertEqual(gemelli.criteri_esatti(a, [c]), ())
        gruppi = gemelli.gruppi_di_gemelli(gemelli.coppie_certe([c, b, a]))
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(len(gruppi[0][1]), 2)
        esito, fondi = self._passo([c, b, a])
        self.assertEqual((esito["gruppi"], esito["gruppi_oltre_due"]), (0, 1))
        self.assertEqual((esito["fusioni_previste"], fondi.chiamate), (0, []))
        self.assertEqual(esito["coppie_per_criterio"]["url"], 0)

    def test_lettura_al_limite_nessuna_fusione(self):
        righe = _pubblicati()
        esito = gemelli.esegui_passo(None, modalita="attivo", tetto=10, leggi=lambda: righe,
                                     fondi=_Fondi(), limite_lettura=len(righe))
        self.assertEqual((esito["status"], esito["motivo"]), ("errore", "lettura_troncata"))
        self.assertNotIn("fusioni", esito)
        esito, _ = self._passo(righe)
        self.assertEqual(esito["status"], "ok")

    def test_fusione_non_riuscita_e_master_corretto(self):
        esito, _ = self._passo([_riga(803614), _riga(803633)], fondi=_Fondi(risposta=None))
        self.assertEqual((esito["fusi"], esito["fusioni_non_riuscite"]), (0, 1))
        esito, _ = self._passo([_riga(803614), _riga(803633)], fondi=_Fondi(risposta=42))
        self.assertEqual((esito["fusi"], esito["master_corretti"]), (1, 1))

    def test_il_fuzzy_non_fonde_mai(self):
        a = {"id": 1, "regione": "Marche", "titolo_raw": "Avviso formazione docenti 2025",
             "link_bando": "https://regione.marche.it/a"}
        b = {"id": 2, "regione": "Marche", "titolo_raw": "Avviso formazione docenti 2026",
             "link_bando": "https://regione.marche.it/b"}
        self.assertTrue(gemelli.possibili_doppioni(a, [b]))
        esito, fondi = self._passo([a, b])
        self.assertEqual((esito["fusioni_previste"], fondi.chiamate), (0, []))

    def test_errore_senza_messaggio(self):
        def leggi():
            raise RuntimeError("https://x.invalid/?apikey=segreta")
        esito = gemelli.esegui_passo(None, modalita="attivo", tetto=5, leggi=leggi, fondi=_Fondi())
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(esito["motivo"], "RuntimeError")
        self.assertNotIn("segreta", repr(esito))

    def test_modalita_sconosciuta_vale_ombra(self):
        esito, fondi = self._passo(modalita="ATTIVISSIMO")
        self.assertEqual((esito["modalita"], fondi.chiamate), ("ombra", []))

    def test_valori_da_settings(self):
        from unittest.mock import patch
        valori = {"verifica_stato_modalita": "attivo", "gemelli_fusioni_per_giro": 1}
        with patch.object(gemelli, "_impostazione", lambda nome, predefinito: valori[nome]):
            esito = gemelli.esegui_passo(None, leggi=_pubblicati, fondi=_Fondi())
        self.assertEqual((esito["modalita"], esito["tetto"], esito["fusi"]), ("attivo", 1, 1))

    def test_gli_indici_trovano_le_stesse_coppie_del_confronto_completo(self):
        righe = _pubblicati() + [
            {"id": 5, "fonte_id": 7, "titolo_raw": "DGR n. 123/2026",
             "fonte_ufficiale_url": "https://regione.marche.it/x"},
            {"id": 6, "fonte_id": 8, "titolo_raw": "Avviso D.G.R. 123/2026",
             "fonte_ufficiale_url": "https://regione.marche.it/y"},
        ]
        completo = set()
        for i, a in enumerate(righe):
            for b in righe[i + 1:]:
                if gemelli.criteri_esatti(a, [b]):
                    completo.add(frozenset((a["id"], b["id"])))
        indicizzato = {frozenset((a["id"], b["id"])) for a, b, _c in gemelli.coppie_certe(righe)}
        self.assertEqual(indicizzato, completo)
        self.assertIn(frozenset((5, 6)), completo)



class PrudenzaDelPassoSulleCoppiePerUrl(unittest.TestCase):
    """Le coppie per URL si fondono in automatico solo con tre prove in piu'."""

    TITOLO = "Incentivi alle imprese abruzzesi per assumere disoccupati"

    def _coppia(self, **b):
        a = {"id": 1, "fonte_id": 217, "link_bando": "https://coesione.regione.abruzzo.it/avvisi/x",
             "titolo": self.TITOLO, "data_scadenza": "2026-12-31"}
        seconda = {"id": 2, "fonte_id": 449, "link_bando": "https://obiettivoeuropa.com/bandi/2",
                   "fonte_ufficiale_url": "https://coesione.regione.abruzzo.it/avvisi/x",
                   "titolo": "Abruzzo: incentivi alle imprese per assumere disoccupati",
                   "data_scadenza": "2026-12-31"}
        seconda.update(b)
        return a, seconda

    def _passo(self, righe):
        fondi = _Fondi()
        esito = gemelli.esegui_passo(None, modalita="attivo", tetto=10, leggi=lambda: righe,
                                     fondi=fondi)
        return esito, fondi

    def test_la_coppia_pulita_si_fonde(self):
        esito, fondi = self._passo(list(self._coppia()))
        self.assertEqual(esito["fusi"], 1)
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {})
        self.assertEqual(fondi.chiamate, [(1, 2, "gemello esatto: url")])

    def test_a_url_in_tre_righe_e_una_pagina_hub(self):
        a, b = self._coppia()
        terza = {"id": 3, "fonte_id": 238, "link_bando": "https://www.lazioeuropa.it/bandi/y",
                 "fonte_ufficiale_url": a["link_bando"], "titolo": self.TITOLO}
        esito, fondi = self._passo([a, b, terza])
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {"url_condiviso": 2})
        self.assertEqual(esito["hub_esclusi"], 1)
        self.assertEqual(esito["coppie_per_criterio"]["url"], 0)
        # `criteri_esatti` resta com'e': per chi fonde a mano la coppia e' certa.
        self.assertTrue(gemelli.criteri_esatti(a, [b]))

    def test_una_riga_gia_fusa_conta_per_l_hub(self):
        a, b = self._coppia()
        fusa = {"id": 3, "fonte_id": 238, "link_bando": a["link_bando"], "bando_master_id": 99,
                "titolo": self.TITOLO}
        esito, fondi = self._passo([a, b, fusa])
        self.assertEqual((esito["hub_esclusi"], fondi.chiamate), (1, []))

    def test_b_titoli_diversi(self):
        esito, fondi = self._passo(list(self._coppia(
            titolo="Contributi per la digitalizzazione delle botteghe storiche", titolo_raw=None)))
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {"titoli_diversi": 1})
        a, b = self._coppia()
        self.assertGreaterEqual(gemelli.somiglianza_fra_righe(a, b), 0.30)

    def test_c_scadenze_diverse(self):
        esito, fondi = self._passo(list(self._coppia(data_scadenza="2027-03-31")))
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {"scadenze_diverse": 1})

    def test_c_una_scadenza_mancante_basta(self):
        esito, fondi = self._passo(list(self._coppia(data_scadenza=None)))
        self.assertEqual(esito["fusi"], 1)

    def test_due_lotti_non_si_fondono(self):
        """Il caso della revisione: il lotto 2 ha come fonte ufficiale la pagina del lotto 1."""
        lotto_1 = {"id": 1, "fonte_id": 217, "link_bando": "https://ente.it/avviso-lotto-1",
                   "titolo": "Avviso formazione per disoccupati - Lotto 1",
                   "data_scadenza": "2026-12-31"}
        lotto_2 = {"id": 2, "fonte_id": 217, "link_bando": "https://ente.it/avviso-lotto-2",
                   "fonte_ufficiale_url": "https://ente.it/avviso-lotto-1",
                   "titolo": "Avviso formazione per disoccupati - Lotto 2",
                   "data_scadenza": "2026-12-31"}
        self.assertTrue(gemelli.criteri_esatti(lotto_1, [lotto_2]))
        self.assertGreaterEqual(gemelli.somiglianza_fra_righe(lotto_1, lotto_2), 0.30)
        esito, fondi = self._passo([lotto_1, lotto_2])
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {"anni_o_lotti_diversi": 1})

    def test_anni_diversi_valgono_per_ogni_criterio(self):
        titolo = "Voucher formativi per le microimprese della Valle d'Aosta"
        a, b = _riga(803614, titolo=titolo), _riga(803633, titolo=titolo)
        corrispondenza = gemelli.criteri_esatti(a, [b])[0]
        self.assertEqual(corrispondenza.criterio, "riga_calendario")
        self.assertIsNone(gemelli.motivo_di_prudenza(a, b, corrispondenza, {}))
        b["titolo"] = titolo + " 2027"
        self.assertEqual(gemelli.motivo_di_prudenza(a, b, corrispondenza, {}),
                         "anni_o_lotti_diversi")
        # Anche sul titolo della fonte.
        c = _riga(803633, titolo_raw="d.1-2026 edizione 2027")
        self.assertEqual(gemelli.motivo_di_prudenza(a, c, corrispondenza, {}),
                         "anni_o_lotti_diversi")

    def test_gli_altri_criteri_non_passano_dalla_prudenza(self):
        """Le coppie di calendario non hanno titoli editoriali simili per forza."""
        a, b = _riga(803614), _riga(803633)
        corrispondenza = gemelli.criteri_esatti(a, [b])[0]
        self.assertIsNone(gemelli.motivo_di_prudenza(a, b, corrispondenza, {}))

    # --- revisione avversaria del 01/10, ciclo 2: lotti e numerazioni -------

    def _due_lotti(self, titolo_a, titolo_b, campo="titolo"):
        """Una coppia per URL pulita (pagina dell'ente in esattamente 2 righe,
        stessa scadenza), con i due titoli dati nel campo dato."""
        a, b = self._coppia()
        a[campo], b[campo] = titolo_a, titolo_b
        if campo == "titolo_raw":
            a["titolo"] = b["titolo"] = self.TITOLO
        return a, b

    def test_le_forme_numerate_non_si_fondono(self):
        casi = {
            "lotto n.": ("Avviso formazione per disoccupati - Lotto n. 1",
                         "Avviso formazione per disoccupati - Lotto n. 2"),
            "sportello": ("Incentivi alle imprese abruzzesi per assumere - Sportello 1",
                          "Incentivi alle imprese abruzzesi per assumere - Sportello 2"),
            "edizione romana": ("I edizione del premio alle imprese abruzzesi",
                                "II edizione del premio alle imprese abruzzesi"),
            "edizione ordinale": ("2ª edizione del premio alle imprese abruzzesi",
                                  "3° edizione del premio alle imprese abruzzesi"),
            "finestra in lettere": ("Prima finestra incentivi alle imprese abruzzesi",
                                    "Seconda finestra incentivi alle imprese abruzzesi"),
            "misura": ("Incentivi alle imprese abruzzesi - Misura 16.1",
                       "Incentivi alle imprese abruzzesi - Misura 16.2"),
            "azione": ("Incentivi alle imprese abruzzesi - Azione 1.1.2",
                       "Incentivi alle imprese abruzzesi - Azione 11.2"),
            "fase": ("Incentivi alle imprese abruzzesi - Fase II",
                     "Incentivi alle imprese abruzzesi - Fase III"),
            "linea": ("Incentivi alle imprese abruzzesi - Linea 1",
                      "Incentivi alle imprese abruzzesi - Linea 2"),
            "elenco": ("Incentivi alle imprese abruzzesi - Lotti 1/2",
                       "Incentivi alle imprese abruzzesi - Lotto 1"),
            "tranche": ("Incentivi alle imprese abruzzesi - tranche 2",
                        "Incentivi alle imprese abruzzesi - tranche III"),
            # Revisione #121: le lettere e le famiglie asse, intervento, modulo, avviso.
            "linea lettera": ("Incentivi alle imprese abruzzesi - Linea A",
                              "Incentivi alle imprese abruzzesi - Linea B"),
            "linea di intervento": ("Incentivi alle imprese abruzzesi - Linea di intervento A",
                                    "Incentivi alle imprese abruzzesi - Linea d’intervento B"),
            "misura lettera": ("Incentivi alle imprese abruzzesi - Misura A",
                               "Incentivi alle imprese abruzzesi - Misura B"),
            "misure elenco": ("Incentivi alle imprese abruzzesi - Misure A/B",
                              "Incentivi alle imprese abruzzesi - Misura A"),
            "azione lettera": ("Incentivi alle imprese abruzzesi - Azione B",
                               "Incentivi alle imprese abruzzesi - Azione C"),
            "fase lettera": ("Incentivi alle imprese abruzzesi - Fase A",
                             "Incentivi alle imprese abruzzesi - Fase B"),
            "asse": ("Incentivi alle imprese abruzzesi - Asse prioritario I",
                     "Incentivi alle imprese abruzzesi - Asse prioritario II"),
            "intervento": ("Incentivi alle imprese abruzzesi - Intervento 3.1",
                           "Incentivi alle imprese abruzzesi - Intervento 3.2"),
            "modulo": ("Incentivi alle imprese abruzzesi - Modulo A",
                       "Incentivi alle imprese abruzzesi - Modulo B"),
            "avviso n.": ("Avviso n. 3/2026 incentivi alle imprese abruzzesi",
                          "Avviso n. 4/2026 incentivi alle imprese abruzzesi"),
        }
        for nome, (titolo_a, titolo_b) in casi.items():
            for campo in ("titolo", "titolo_raw"):
                with self.subTest(forma=nome, campo=campo):
                    a, b = self._due_lotti(titolo_a, titolo_b, campo)
                    self.assertTrue(gemelli.criteri_esatti(a, [b]))
                    esito, fondi = self._passo([a, b])
                    self.assertEqual(fondi.chiamate, [])
                    self.assertEqual(esito["coppie_scartate_per_prudenza"],
                                     {"anni_o_lotti_diversi": 1})

    def test_anche_la_riga_di_calendario(self):
        titolo = "Voucher formativi per le microimprese della Valle d'Aosta"
        a, b = _riga(803614, titolo=titolo), _riga(803633, titolo=titolo)
        corrispondenza = gemelli.criteri_esatti(a, [b])[0]
        self.assertEqual(corrispondenza.criterio, "riga_calendario")
        b["titolo"] = titolo + " - Sportello n. 2"
        a["titolo"] = titolo + " - Sportello n. 1"
        self.assertEqual(gemelli.motivo_di_prudenza(a, b, corrispondenza, {}),
                         "anni_o_lotti_diversi")

    def test_le_differenze_lette(self):
        self.assertEqual(gemelli._differenze("Lotto n. 1", "Lotto n. 2"), ("lotto 1", "lotto 2"))
        self.assertEqual(gemelli._differenze("II edizione", "I edizione"),
                         ("edizione 1", "edizione 2"))
        self.assertEqual(gemelli._differenze("Sportello 1/2", "Sportello 1"), ("sportello 2",))
        self.assertEqual(gemelli._differenze("Lotto A", "Lotto B"), ("lotto A", "lotto B"))
        self.assertEqual(gemelli._differenze("LOTTO N.1 SERVIZI", "Lotto n° 1 servizi"), ())
        self.assertEqual(gemelli._differenze("Fase II", "fase 2"), ())

    def test_le_lettere_e_le_famiglie_nuove_lette(self):
        self.assertEqual(gemelli._differenze("Avviso Linea A", "Avviso Linea B"),
                         ("linea A", "linea B"))
        self.assertEqual(gemelli._differenze("Linea di intervento A/B", "Linea di intervento A"),
                         ("linea B",))
        self.assertEqual(gemelli._differenze("Misura A/B", "Misura A/C"), ("misura B", "misura C"))
        self.assertEqual(gemelli._differenze("Asse 1 FSE+", "Asse 2 FSE+"), ("asse 1", "asse 2"))
        self.assertEqual(gemelli._differenze("Avviso n. 3/2026", "Avviso n. 4/2026"),
                         ("avviso 3", "avviso 4"))
        # Il numero dell'avviso senza l'anno: l'anno si confronta per conto suo.
        self.assertEqual(gemelli._differenze("Avviso pubblico n. 3/2026", "Avviso n. 3 del 2026"), ())
        self.assertEqual(gemelli._differenze("Avviso 2026 formazione", "Avviso 2026 formazione"), ())

    def test_le_famiglie_di_programma_solo_se_in_entrambi(self):
        # Anche con le lettere e con le famiglie nuove: da una parte sola non bloccano.
        for a, b in (("Bando - Linea A", "Bando"), ("Bando - Asse 2", "Bando"),
                     ("Bando - Modulo B", "Bando"), ("Avviso n. 3/2026 - Bando", "Bando 2026"),
                     ("Bando - Intervento 4", "Bando")):
            with self.subTest(a=a):
                self.assertEqual(gemelli._differenze(a, b), ())
        # Le lettere non valgono per le famiglie d'istanza diverse dal lotto.
        self.assertEqual(gemelli._differenze("Sportello A", "Sportello B"), ())

    def test_i_falsi_numeri_non_contano(self):
        # «I lotti» e' l'articolo; «misura di», «a misura» non hanno numero.
        self.assertEqual(gemelli._differenze("I lotti del bando", "Lotti del bando"), ())
        self.assertEqual(gemelli._differenze("Contributi a misura di impresa",
                                             "Contributi a misura di impresa"), ())
        self.assertEqual(gemelli._differenze("Misura a sostegno", "Misura A sostegno"), ())
        self.assertEqual(gemelli._differenze("Contributi A Fondo Perduto - Misura A",
                                             "Contributi a fondo perduto - Misura A"), ())
        self.assertEqual(gemelli._differenze("LINEA A E B", "LINEA A E B"), ())

    def test_un_codice_di_programma_da_una_parte_sola_non_blocca(self):
        """Il caso vero 5596/40744: «(Azione 4.6.1)» solo nel titolo redazionale di una riga."""
        a, b = self._due_lotti(
            "Rigenerazione culturale nel Sud: 29,4 milioni per progetti locali (Azione 4.6.1)",
            "Rigenerazione culturale nel Sud Italia: 29,4 milioni per enti locali")
        self.assertIsNone(gemelli.motivo_di_prudenza(
            a, b, gemelli.Corrispondenza(1, "riga_calendario", "x"), {}))
        # Un lotto invece conta anche da una parte sola, come prima.
        self.assertEqual(gemelli._differenze("Avviso - Lotto 2", "Avviso"), ("lotto 2",))

    def test_un_campo_vuoto_da_una_parte_non_si_confronta(self):
        """I 7 gemelli per URL veri del 01/10: il titolo della fonte manca da una parte."""
        a, b = self._coppia()
        a["titolo_raw"] = "Incentivi alle imprese abruzzesi per assumere - periodo 2026-2028"
        b["titolo_raw"] = ""
        esito, fondi = self._passo([a, b])
        self.assertEqual(esito["fusi"], 1)
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {})
        # Pieni tutti e due e diversi: si ferma.
        b["titolo_raw"] = "Incentivi alle imprese abruzzesi per assumere - periodo 2027-2029"
        esito, fondi = self._passo([a, b])
        self.assertEqual((esito["fusi"], esito["coppie_scartate_per_prudenza"]),
                         (0, {"anni_o_lotti_diversi": 1}))

    def test_chiave_esterna_e_atto_non_si_fondono_mai_in_automatico(self):
        """Revisione del 01/10: in automatico solo 'url' e 'riga_calendario'."""
        titolo = "Contributi alle scuole paritarie - DGR n. 45/2026"
        atto_a = {"id": 1, "fonte_id": 217, "titolo": titolo, "data_scadenza": "2026-12-31",
                  "link_bando": "https://www.regione.marche.it/bandi/scuole-a"}
        atto_b = dict(atto_a, id=2, fonte_id=218,
                      link_bando="https://www.regione.marche.it/bandi/scuole-b")
        oe_vecchio = {"id": 3, "fonte_id": 449, "raw_data": {"id": "777"},
                      "titolo": "Voucher digitali per le imprese",
                      "link_bando": "https://obiettivoeuropa.com/bandi/vecchio"}
        oe_nuovo = dict(oe_vecchio, id=4, link_bando="https://obiettivoeuropa.com/bandi/nuovo")
        # `criteri_esatti` li vede ancora: restano proposte per chi fonde a mano.
        self.assertEqual(gemelli.criteri_esatti(atto_b, [atto_a])[0].criterio, "atto")
        self.assertEqual(gemelli.criteri_esatti(oe_nuovo, [oe_vecchio])[0].criterio,
                         "chiave_esterna")
        esito, fondi = self._passo([atto_a, atto_b, oe_vecchio, oe_nuovo])
        self.assertEqual(fondi.chiamate, [])
        self.assertEqual(esito["fusi"], 0)
        self.assertEqual(esito["coppie_scartate_per_prudenza"], {"criterio_non_automatico": 2})
        self.assertEqual(esito["coppie_per_criterio"],
                         {"url": 0, "chiave_esterna": 0, "atto": 0, "riga_calendario": 0})
        self.assertEqual(gemelli.CRITERI_AUTOMATICI, ("url", "riga_calendario"))
        for criterio in ("chiave_esterna", "atto"):
            self.assertEqual(gemelli.motivo_di_prudenza(
                atto_a, atto_b, gemelli.Corrispondenza(1, criterio, "x"), {}),
                "criterio_non_automatico")


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
