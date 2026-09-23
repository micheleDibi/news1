# -*- coding: utf-8 -*-
"""`segnali.py`: confronto del listing, priorita', «sparito dalla fonte» (§6.1).

Il test che conta davvero e' `test_riscrittura_identica_evitata`: sul codice
precedente ogni giro riscriveva ~1 419 righe di Obiettivo Europa perche'
l'API emette `deadline_days_left`, che scala di 1 ogni notte. Qui quella riga
non viene nemmeno proposta all'upsert.

Nessuna rete, nessun DB: `confronta` e' una funzione pura.
"""
import unittest
from datetime import datetime, timedelta, timezone

from tests.supporto import carica_modulo

segnali = carica_modulo("segnali")

FONTE_OE = {"id": 449, "link": "https://www.obiettivoeuropa.com/api/call/"}
FONTE_INCENTIVI = {"id": 500, "link": "https://www.incentivi.gov.it/solr/coredrupal/select"}
FONTE_ID_PNRR = {"id": 501, "link": "https://www.italiadomani.gov.it/opportunita/"}
FONTE_HTML = {"id": 12, "link": "https://www.lazioeuropa.it/bandi/"}

ADESSO = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _record_oe(**raw):
    grezzo = {
        "source": "obiettivo_europa",
        "id": "942936",
        "status": "1",
        "deadline_label": "Scade il 06/10/2026",
        "on_arrival": False,
        "published": "2026-07-01",
        "budget": 1_000_000,
        "modified": "2026-09-01T10:00:00+02:00",
        "updates_active": True,
        "deadline_days_left": 13,
        "is_recent": True,
        "like": 3,
        "visited": 120,
        "is_copiloted": False,
    }
    grezzo.update(raw)
    return {
        "fonte_id": 449,
        "hash_bando": "h-oe",
        "tipo_link": "Opportunità",
        "link_bando": "https://www.obiettivoeuropa.com/bandi/psicologia-scolastica/",
        "titolo_raw": "Psicologia scolastica",
        "descrizione_raw": None,
        "raw_data": grezzo,
    }


def _riga(record, **extra):
    riga = dict(record, id=905315, stato_processing="completed", slug="psicologia-scolastica",
                stato_bando="aperto", data_scadenza="2026-10-06")
    riga.update(extra)
    return riga


class TestEstratto(unittest.TestCase):
    def test_solo_le_chiavi_di_sezione_6_1(self):
        estratto = segnali.estratto(_record_oe())
        self.assertEqual(set(estratto), set(segnali.CHIAVI_OE))

    def test_volatili_escluse(self):
        estratto = segnali.estratto(_record_oe())
        for volatile in segnali.VOLATILI_OE:
            self.assertNotIn(volatile, estratto)

    def test_stringa_vuota_vale_assente(self):
        # Gli adapter tolgono i vuoti da raw_data, il DB puo' averli conservati:
        # non devono generare un segnale l'uno contro l'altro.
        a = segnali.estratto(_record_oe(deadline_label=""))
        b = segnali.estratto(_record_oe(deadline_label="   "))
        self.assertEqual(a["deadline_label"], b["deadline_label"])
        self.assertIsNone(a["deadline_label"])

    def test_tipo_link_entra_nel_confronto(self):
        # `tipo_link` e' una colonna di `bando` ricalcolata da `on_arrival`:
        # e' il segnale «il bando e' passato da preavviso a opportunita'».
        self.assertIn("tipo_link", segnali.estratto(_record_oe()))

    def test_calendario_esclude_le_posizionali_ma_tiene_source_url(self):
        record = {
            "fonte_id": 7, "hash_bando": "h", "tipo_link": "Preavviso",
            "link_bando": None, "titolo_raw": "Avviso",
            "raw_data": {"source_url": "https://x.it/cal.csv", "row_index": 3,
                         "page": 2, "dotazione": "1.000.000"},
        }
        estratto = segnali.estratto(record)
        self.assertIn("source_url", estratto)
        self.assertIn("dotazione", estratto)
        self.assertNotIn("row_index", estratto)
        self.assertNotIn("page", estratto)


class TestImpronta(unittest.TestCase):
    def test_stabile_al_riordino_delle_chiavi(self):
        primo = _record_oe()
        secondo = _record_oe()
        secondo["raw_data"] = dict(reversed(list(secondo["raw_data"].items())))
        self.assertEqual(segnali.impronta_raw(primo), segnali.impronta_raw(secondo))

    def test_insensibile_ai_volatili(self):
        self.assertEqual(
            segnali.impronta_raw(_record_oe(deadline_days_left=13)),
            segnali.impronta_raw(_record_oe(deadline_days_left=12, visited=999)),
        )

    def test_sensibile_alla_scadenza(self):
        self.assertNotEqual(
            segnali.impronta_raw(_record_oe()),
            segnali.impronta_raw(_record_oe(deadline_label="Scade il 01/12/2026")),
        )


class TestConfronta(unittest.TestCase):
    def test_riscrittura_identica_evitata(self):
        # IL test: solo `deadline_days_left` e' cambiato. Sul codice vecchio
        # questa riga finiva nell'upsert; qui non deve nemmeno comparire.
        esistente = _riga(_record_oe(deadline_days_left=14))
        nuovo = _record_oe(deadline_days_left=13)
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.da_scrivere, ())
        self.assertEqual(esito.identici, 1)
        self.assertEqual(esito.segnali, ())

    def test_record_nuovo_va_scritto(self):
        esito = segnali.confronta(FONTE_OE, [_record_oe()], {}, adesso=ADESSO)
        self.assertEqual(len(esito.nuovi), 1)
        self.assertEqual(esito.identici, 0)

    def test_scadenza_cambiata_priorita_90_e_scheda_oe(self):
        esistente = _riga(_record_oe())
        nuovo = _record_oe(deadline_label="Scade il 01/12/2026")
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(len(esito.cambiati), 1)
        self.assertEqual(esito.priorita["h-oe"], segnali.PRIORITA_ALTA)
        self.assertEqual(esito.schede_oe_da_riscaricare, ("h-oe",))

    def test_modified_priorita_60(self):
        esistente = _riga(_record_oe())
        nuovo = _record_oe(modified="2026-09-22T08:00:00+02:00")
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-oe"], segnali.PRIORITA_MEDIA)
        self.assertEqual(esito.schede_oe_da_riscaricare, ())

    def test_budget_priorita_40(self):
        esistente = _riga(_record_oe())
        nuovo = _record_oe(budget=2_000_000)
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-oe"], segnali.PRIORITA_BASSA)

    def test_priorita_e_la_massima_fra_i_campi(self):
        esistente = _riga(_record_oe())
        nuovo = _record_oe(budget=2_000_000, status="2")
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-oe"], segnali.PRIORITA_ALTA)

    def test_nessuna_data_ne_stato_nel_segnale(self):
        # Regola unica di §6.1: da un diff di listing non nasce nessuna
        # transizione. La riga dell'evento non deve contenere colonne di stato.
        esistente = _riga(_record_oe())
        nuovo = _record_oe(deadline_label="Scade il 01/12/2026")
        esito = segnali.confronta(FONTE_OE, [nuovo], {"h-oe": esistente}, adesso=ADESSO)
        riga = esito.segnali[0].come_riga()
        for vietata in ("data_scadenza", "data_apertura", "stato_bando", "cursore"):
            self.assertNotIn(vietata, riga)
        self.assertFalse(riga["leggibile"])
        self.assertFalse(riga["in_aggiornamenti"])
        self.assertFalse(riga["applicato"])
        self.assertEqual(riga["tipo"], segnali.TIPO_SEGNALE)

    def test_mismatch_deadline_label_contro_colonna(self):
        # Il controllo gratuito che copre 1 419 righe su 1 702: la riga non e'
        # cambiata, ma l'etichetta dice una scadenza diversa dalla colonna.
        esistente = _riga(_record_oe(), data_scadenza="2026-12-01")
        esito = segnali.confronta(FONTE_OE, [_record_oe()], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.da_scrivere, ())      # niente da riscrivere
        self.assertEqual(len(esito.segnali), 1)
        self.assertEqual(esito.priorita["h-oe"], segnali.PRIORITA_ALTA)
        self.assertTrue(esito.segnali[0].oe_scheda_da_riscaricare)

    def test_nessun_mismatch_quando_coincidono(self):
        esistente = _riga(_record_oe(), data_scadenza="2026-10-06")
        esito = segnali.confronta(FONTE_OE, [_record_oe()], {"h-oe": esistente}, adesso=ADESSO)
        self.assertEqual(esito.segnali, ())

    def test_incentivi_close_date_e_ds_last_update(self):
        base = {
            "fonte_id": 500, "hash_bando": "h-inc", "tipo_link": "Opportunità",
            "link_bando": "https://www.incentivi.gov.it/it/x",
            "titolo_raw": "Incentivo",
            "raw_data": {"source": "incentivi_gov_it", "nid": "77",
                         "open_date": "2026-01-01", "close_date": "2026-10-06",
                         "external_link": "https://ente.it/x",
                         "budget_allocation": 5.0, "ds_last_update": "2026-09-01"},
        }
        esistente = dict(base, id=1, stato_processing="completed", slug="x")
        chiuso = dict(base)
        chiuso["raw_data"] = dict(base["raw_data"], close_date="2026-12-01")
        esito = segnali.confronta(FONTE_INCENTIVI, [chiuso], {"h-inc": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-inc"], segnali.PRIORITA_ALTA)

        tocco = dict(base)
        tocco["raw_data"] = dict(base["raw_data"], ds_last_update="2026-09-22")
        esito = segnali.confronta(FONTE_INCENTIVI, [tocco], {"h-inc": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-inc"], segnali.PRIORITA_MEDIA)

    def test_italia_domani_stato_priorita_90(self):
        base = {
            "fonte_id": 501, "hash_bando": "h-id", "tipo_link": "Opportunità",
            "link_bando": "https://www.italiadomani.gov.it/x",
            "titolo_raw": "PNRR",
            "raw_data": {"source": "italia_domani", "stato": "Aperto",
                         "data_apertura": "01/01/2026", "data_chiusura": "06/10/2026",
                         "amministrazione_titolare": "MIM"},
        }
        esistente = dict(base, id=2, stato_processing="completed", slug="x")
        chiuso = dict(base)
        chiuso["raw_data"] = dict(base["raw_data"], stato="Chiuso")
        esito = segnali.confronta(FONTE_ID_PNRR, [chiuso], {"h-id": esistente}, adesso=ADESSO)
        self.assertEqual(esito.priorita["h-id"], segnali.PRIORITA_ALTA)

    def test_html_titolo_e_link(self):
        base = {"fonte_id": 12, "hash_bando": "h-html", "tipo_link": "Opportunità",
                "link_bando": "https://www.lazioeuropa.it/bandi/a/", "titolo_raw": "Avviso A",
                "raw_data": None}
        esistente = dict(base, id=3, stato_processing="completed", slug="a")
        nuovo = dict(base, titolo_raw="Avviso A - prorogato")
        esito = segnali.confronta(FONTE_HTML, [nuovo], {"h-html": esistente}, adesso=ADESSO)
        self.assertEqual(len(esito.cambiati), 1)
        self.assertEqual(esito.segnali[0].campi, ("titolo_raw",))


class TestCopertura(unittest.TestCase):
    def test_senza_dichiarazione_non_e_piena(self):
        self.assertFalse(segnali.copertura_piena(None, 100))

    def test_troncato_non_e_piena(self):
        self.assertFalse(segnali.copertura_piena({"pagine": 3, "troncato": True, "count": 0}, 100))

    def test_conteggio_dichiarato_non_raggiunto(self):
        self.assertFalse(
            segnali.copertura_piena({"pagine": 3, "troncato": False, "count": 200}, 100))

    def test_piena(self):
        self.assertTrue(
            segnali.copertura_piena({"pagine": 4, "troncato": False, "count": 100}, 100))

    def test_chiave_mancante_vale_troncato(self):
        self.assertFalse(segnali.copertura_piena({"pagine": 4, "count": 0}, 100))


class TestSpariti(unittest.TestCase):
    def _esistenti(self, **extra):
        vecchio = (ADESSO - timedelta(days=5)).isoformat()
        riga = {
            "id": 1, "hash_bando": "h-vivo", "stato_processing": "completed",
            "slug": "vivo", "stato_bando": "aperto", "data_scadenza": "2026-12-31",
            "ultimo_visto_in_fonte_at": vecchio, "raw_data": {"source": "obiettivo_europa"},
        }
        riga.update(extra)
        return {"h-vivo": riga}

    def test_pubblicato_vivo_e_assente_da_tre_giri(self):
        trovati = segnali.spariti(self._esistenti(), [], adesso=ADESSO)
        self.assertEqual(len(trovati), 1)
        self.assertEqual(trovati[0].tipo, segnali.TIPO_SPARITO)
        self.assertEqual(trovati[0].priorita, segnali.PRIORITA_SPARITO)

    def test_chiuso_fuori_listing_non_genera_evento(self):
        # Sono i 545 OE chiusi gia' fuori dal listing: la normalita'.
        trovati = segnali.spariti(
            self._esistenti(stato_bando="chiuso", data_scadenza="2026-01-01"), [], adesso=ADESSO)
        self.assertEqual(trovati, ())

    def test_non_pubblicato_non_genera_evento(self):
        trovati = segnali.spariti(
            self._esistenti(stato_processing="enriched", slug=None), [], adesso=ADESSO)
        self.assertEqual(trovati, ())

    def test_visto_in_questo_giro(self):
        self.assertEqual(segnali.spariti(self._esistenti(), ["h-vivo"], adesso=ADESSO), ())

    def test_assenza_troppo_recente(self):
        recente = (ADESSO - timedelta(hours=6)).isoformat()
        trovati = segnali.spariti(
            self._esistenti(ultimo_visto_in_fonte_at=recente), [], adesso=ADESSO)
        self.assertEqual(trovati, ())

    def test_mai_visto_non_genera_evento(self):
        trovati = segnali.spariti(
            self._esistenti(ultimo_visto_in_fonte_at=None), [], adesso=ADESSO)
        self.assertEqual(trovati, ())

    def test_confronta_non_emette_spariti_senza_copertura(self):
        esistenti = self._esistenti()
        esito = segnali.confronta(
            FONTE_OE, [], esistenti,
            esito={"pagine": 1, "troncato": True, "count": 0}, adesso=ADESSO,
        )
        self.assertEqual(esito.spariti, ())

    def test_confronta_emette_spariti_con_copertura(self):
        esistenti = self._esistenti()
        esito = segnali.confronta(
            FONTE_OE, [], esistenti,
            esito={"pagine": 1, "troncato": False, "count": 0}, adesso=ADESSO,
        )
        self.assertEqual(len(esito.spariti), 1)

    def test_listing_dimezzato_blocca_gli_spariti(self):
        # La fonte e' passata da 100 a 10 elementi: e' un guasto, non 90 bandi
        # ritirati dall'ente.
        esistenti = self._esistenti()
        esito = segnali.confronta(
            FONTE_OE, [], esistenti,
            esito={"pagine": 1, "troncato": False, "count": 0},
            elementi_giro_precedente=100, adesso=ADESSO,
        )
        self.assertFalse(esito.copertura_piena)
        self.assertEqual(esito.spariti, ())


class TestScadenzaDaLabel(unittest.TestCase):
    def test_etichetta_semplice(self):
        self.assertEqual(
            segnali.scadenza_da_label("Scade il 06/10/2026").isoformat(), "2026-10-06")

    def test_etichetta_estesa(self):
        self.assertEqual(
            segnali.scadenza_da_label("Scade il 1° dicembre 2026").isoformat(), "2026-12-01")

    def test_costrutto_dal_al_da_la_scadenza(self):
        # «dal X al Y» assegna i ruoli: Y e' la scadenza, X l'apertura.
        self.assertEqual(
            segnali.scadenza_da_label("dal 22/10/2026 al 01/12/2026").isoformat(),
            "2026-12-01",
        )

    def test_due_date_senza_ruolo_non_sono_una_scadenza(self):
        # Due date «ignote» nella stessa etichetta: non si indovina.
        self.assertIsNone(segnali.scadenza_da_label("06/10/2026 e 01/12/2026"))

    def test_senza_data(self):
        self.assertIsNone(segnali.scadenza_da_label("A sportello"))
        self.assertIsNone(segnali.scadenza_da_label(None))


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
