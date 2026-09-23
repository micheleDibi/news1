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


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
