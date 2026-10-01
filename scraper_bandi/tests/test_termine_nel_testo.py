# -*- coding: utf-8 -*-
"""`date_validation.termine_nel_testo` (contratto `bandi-giro-2` §6.2 e §19.5).

Un termine indicato e' un indizio, mai una prova: vale solo nella frase di una
domanda da presentare (o nelle due forme strette decise dal lead il 30/09),
fuori dalle frasi di fiere, eventi, spese, progetti, rendiconti, lavori e avvio
attivita', mai da una data presunta; con piu' date vince la piu' tarda.

I titoli e le descrizioni sono quelli veri del DB al 30/09/2026 (letti in GET).
Funzione pura: nessuna rete.
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

dv = carica_modulo("date_validation")
termine = dv.termine_nel_testo


class TestNegativiObbligatori(unittest.TestCase):
    """I cinque casi di §6.2 e §19.5: nessun termine."""

    def test_18346_spese_sostenute(self):
        self.assertIsNone(termine(
            "Contributi Liguria per patenti speciali di guida a persone con disabilità",
            "Regione Liguria eroga contributi a fondo perduto alle persone con disabilità per il "
            "conseguimento o la riclassificazione delle patenti speciali di guida di categoria A e "
            "B. Ammissibili le spese sostenute dal 1° gennaio 2025 al 31 dicembre 2025."))

    def test_1009878_date_del_forum(self):
        self.assertIsNone(termine(
            "Sei imprese del Lazio al Forum Euromediterraneo dell'acqua 2026",
            "La Regione Lazio, tramite Lazio Innova, seleziona 6 imprese e startup regionali per "
            "partecipare al Forum Euromediterraneo dell'acqua 2026 a Roma dal 29 settembre al 2 "
            "ottobre 2026. Contributo a fondo perduto tramite PR FESR Lazio 2021-2027."))

    def test_1257967_e_1257980_date_della_fiera(self):
        for descrizione in (
            "Regione Lazio e Camera di Commercio di Roma, tramite Lazio Innova e Sviluppo e "
            "Territorio, selezionano 28 MPMI del Lazio per partecipare gratuitamente a Roma Sposa "
            "2026, in programma dal 30 ottobre al 1° novembre 2026 al Centro Congressi La Nuvola.",
            "Lazio Innova e Camera di Commercio di Roma selezionano 28 MPMI del Lazio per "
            "partecipare gratuitamente a Roma Sposa 2026, in programma dal 30 ottobre al 1° "
            "novembre 2026 al Centro Congressi La Nuvola, con contributo del PR FESR Lazio 2021-2027.",
        ):
            self.assertIsNone(termine(
                "Roma Sposa 2026: 28 imprese del Lazio selezionate per il salone della sposa",
                descrizione))

    def test_940320_data_di_pubblicazione(self):
        self.assertIsNone(termine(
            "Percorsi IFTS 2026/2027 in Emilia-Romagna: bando regionale FSE+",
            "La Regione Emilia-Romagna finanzia con risorse FSE+ 2021/2027 i percorsi di "
            "Istruzione e formazione tecnica superiore (IFTS) per l'anno formativo 2026/2027. "
            "Bando a fondo perduto rivolto agli organismi di formazione accreditati, pubblicato "
            "il 31 agosto 2026."))

    def test_940320_avvio_delle_attivita(self):
        # La frase della pagina: l'avvio delle attivita' non e' un termine.
        self.assertIsNone(termine(None, (
            "Termine per l'avvio delle attività Le operazioni approvate dovranno essere avviate "
            "entro e non oltre il 15 ottobre 2027 con la presentazione del calendario.")))


class TestPositiviDel30Settembre(unittest.TestCase):
    """Termini passati e futuri delle descrizioni vere."""

    CASI = {
        # passati
        3042: ("Domande dal 21 al 31 luglio 2025.", date(2025, 7, 31)),
        2365: ("Candidature entro le 17.00 del 30 giugno 2026.", date(2026, 6, 30)),
        3044: ("Istanze degli enti accreditati dal 19 al 30 giugno 2025 sul portale Sicilia FSE.",
               date(2025, 6, 30)),
        2919: ("Domande dal 20 marzo 2026 fino al 31 luglio 2026 (proroga).", date(2026, 7, 31)),
        # futuri
        1262518: ("Istanze via PEC entro le ore 12 del 13 novembre 2026.", date(2026, 11, 13)),
        905743: ("Domande dal 31 agosto 2026 al 2 ottobre 2026 tramite FINDOM.", date(2026, 10, 2)),
        1239631: ("Domande entro le ore 18.00 del 1° ottobre 2026.", date(2026, 10, 1)),
        803614: ("Procedura a sportello, domande fino al 15 luglio 2029.", date(2029, 7, 15)),
    }

    def test_descrizioni(self):
        for bando_id, (descrizione, atteso) in self.CASI.items():
            with self.subTest(bando=bando_id):
                self.assertEqual(termine("Titolo", descrizione), atteso)

    def test_nel_titolo(self):
        # 1120620: il termine sta nel titolo, e il titolo si legge da solo.
        self.assertEqual(termine(
            "L'Italia delle donne 2026-2027: candidature entro il 18 dicembre 2026",
            "Il Dipartimento per le Pari Opportunità pubblica la terza edizione dell'avviso."),
            date(2026, 12, 18))

    def test_con_piu_date_vince_la_piu_tarda(self):
        self.assertEqual(termine("Avviso", (
            "Domande entro il 30 settembre 2026. Riapertura: domande entro il 15 ottobre 2026.")),
            date(2026, 10, 15))
        self.assertEqual(termine(
            "Domande entro il 20 dicembre 2026", "Domande entro il 30 settembre 2026."),
            date(2026, 12, 20))


class TestFormeStrette(unittest.TestCase):
    """Senza verbo di presentazione: solo l'etichetta «Scadenza» e lo sportello."""

    def test_positivi_del_lead(self):
        self.assertEqual(termine(None, "Scadenza 30 ottobre 2026."), date(2026, 10, 30))   # 1046001
        self.assertEqual(termine(None, "Scadenza 28 luglio 2025."), date(2025, 7, 28))     # 3043
        self.assertEqual(termine(None, "Sportello aperto dal 7 luglio 2026 fino al 29 ottobre 2028."),
                         date(2028, 10, 29))                                              # 125724

    def test_varianti_dell_etichetta(self):
        for frase, atteso in (
            ("Scadenza domande: 15/12/2026.", date(2026, 12, 15)),
            ("Scadenza presentazione – 15 dicembre 2026", date(2026, 12, 15)),
            ("Contributi alle imprese. Scadenza: ore 12:00 del 15/12/2026.", date(2026, 12, 15)),
            ("Avviso regionale (scadenza 15/12/2026)", date(2026, 12, 15)),
            ("Lo sportello chiude il 15/12/2026.", date(2026, 12, 15)),
            ("Sportello aperto fino al 31 dicembre 2026.", date(2026, 12, 31)),
            ("Dotazione di 40 milioni, sportello aperto fino al 31 dicembre 2026.", date(2026, 12, 31)),
        ):
            with self.subTest(frase=frase):
                self.assertEqual(termine(None, frase), atteso)

    def test_negativi_del_lead(self):
        self.assertIsNone(termine(None, "Scadenza rendicontazione 30/06/2027."))
        self.assertIsNone(termine(None, "Scadenza del progetto 31/12/2027."))

    def test_fuori_dalle_forme_strette(self):
        for frase in (
            "Il bando ha scadenza fissata dalla Regione al 30/10/2026.",   # non a inizio frase
            "Sportello aperto dal 5 luglio 2025 al 31 dicembre 2026.",     # 5699: senza «fino»
            "Bandi A e B a sportello aperti dal 3 febbraio 2026 fino al 11 febbraio 2027.",  # 352147
            "Contributi fino al 31 dicembre 2026.",
        ):
            with self.subTest(frase=frase):
                self.assertIsNone(termine(None, frase))


class TestEsclusioni(unittest.TestCase):
    def test_frasi_d_altro(self):
        for frase in (
            "Domande per partecipare alla fiera di Rimini dal 4 al 7 novembre 2026.",
            "Domande di partecipazione all'evento entro il 30/10/2026.",
            "Domande per la manifestazione in programma il 30/10/2026, entro il 15/10/2026.",
            "Domande di rimborso delle spese ammissibili entro il 31/12/2026.",
            "Domande di saldo dopo la realizzazione del progetto entro il 31/12/2027.",
            "Domande di pagamento a conclusione delle attività entro il 31/12/2027.",
            "Domande di proroga per l'ultimazione degli interventi entro il 31/12/2027.",
            "Istanza di rendicontazione entro il 30/06/2027.",
            "Domande per i lavori di ristrutturazione entro il 31/12/2026.",
        ):
            with self.subTest(frase=frase):
                self.assertIsNone(termine(None, frase))

    def test_eventuale_e_manifestazione_di_interesse_non_escludono(self):
        self.assertEqual(termine(None, "Domande, con gli eventuali allegati, entro il 30/10/2026."),
                         date(2026, 10, 30))
        self.assertEqual(termine(None, "Manifestazioni di interesse: domande entro il 30/10/2026."),
                         date(2026, 10, 30))
        self.assertEqual(termine(None, "Invio della manifestazione d'interesse entro il 30/10/2026."),
                         date(2026, 10, 30))


class TestDatePresunteERuoli(unittest.TestCase):
    def test_data_presunta_respinta(self):
        for frase in (
            "Domande entro la data presunta del 30/10/2026.",
            "Apertura prevista dal 27 ottobre 2025 al 31 dicembre 2026, domande online.",
            "Domande indicativamente entro il 30/10/2026.",
        ):
            with self.subTest(frase=frase):
                self.assertIsNone(termine(None, frase))

    def test_previsto_lontano_non_conta(self):
        self.assertEqual(termine(None, (
            "Le domande, secondo le modalità previste dall'avviso approvato dalla Giunta, vanno "
            "presentate entro il 30/10/2026.")), date(2026, 10, 30))

    def test_imprevisto_non_e_una_previsione(self):
        self.assertEqual(termine(None, "Salvo imprevisti, domande entro il 30/10/2026."),
                         date(2026, 10, 30))

    def test_solo_il_ruolo_scadenza(self):
        # Una data senza parole di scadenza (ruolo ignoto) o di apertura non e' un termine.
        self.assertIsNone(termine(None, "Domande: 30/10/2026."))
        self.assertIsNone(termine(None, "Domande a partire dal 30/10/2026."))
        self.assertIsNone(termine(None, "Domande ai sensi del Decreto del 30/10/2026."))

    def test_testi_vuoti(self):
        self.assertIsNone(termine(None, None))
        self.assertIsNone(termine("", ""))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
