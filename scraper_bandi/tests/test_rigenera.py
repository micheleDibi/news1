# -*- coding: utf-8 -*-
"""`rigenera.py`: box «Aggiornamenti», sostituzione in prosa, gate, scrittura.

La regola che il test difende e' quella di §6.2: la data si sostituisce **solo
nelle frasi che parlano di quel ruolo**. Senza il vincolo, una riscrittura
«6 ottobre -> 1 dicembre» cambierebbe anche la data del decreto citato, cioe'
falsificherebbe la fonte dentro l'articolo.

Nessuna rete e nessun modello: il riscrittore e la scrittura sono iniettati.
"""
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tests.supporto import ALIAS, carica_modulo

rigenera = carica_modulo("rigenera")

VECCHIA = date(2026, 10, 6)
NUOVA = date(2026, 12, 1)


class TestVoce(unittest.TestCase):
    def test_voce_per_tipo(self):
        casi = [
            ({"tipo": "proroga", "data_evento": "2026-12-01"}, "prorogato al 1 dicembre 2026"),
            ({"tipo": "graduatoria", "data_evento": "2026-12-10"}, "graduatoria il 10 dicembre 2026"),
            ({"tipo": "esito", "data_evento": "2026-12-10"}, "esiti il 10 dicembre 2026"),
            ({"tipo": "faq", "data_evento": "2026-12-10"}, "FAQ il 10 dicembre 2026"),
        ]
        for evento, atteso in casi:
            with self.subTest(tipo=evento["tipo"]):
                self.assertIn(atteso, rigenera.voce_aggiornamento(evento).testo)

    def test_voce_di_rettifica_per_campo(self):
        voce = rigenera.voce_aggiornamento(
            {"tipo": "rettifica", "campo": "data_apertura",
             "valore_dopo": {"data_apertura": "2026-10-22"}})
        self.assertIn("Apertura differita al 22 ottobre 2026", voce.testo)

    def test_sospensione_nomina_l_ente(self):
        voce = rigenera.voce_aggiornamento(
            {"tipo": "sospensione", "data_evento": "2026-09-20",
             "dominio_prova": "lazioeuropa.it"})
        self.assertIn("lazioeuropa.it", voce.testo)
        self.assertIn("sospeso", voce.testo)

    def test_tipo_sconosciuto_ha_una_voce_generica(self):
        voce = rigenera.voce_aggiornamento({"tipo": "boh", "data_evento": "2026-09-20"})
        self.assertIn("Aggiornamento pubblicato", voce.testo)

    def test_box_solo_eventi_leggibili_e_in_aggiornamenti(self):
        eventi = [
            {"tipo": "proroga", "data_evento": "2026-09-01",
             "leggibile": True, "in_aggiornamenti": True},
            {"tipo": "apertura_automatica", "data_evento": "2026-09-02",
             "leggibile": True, "in_aggiornamenti": False},
            {"tipo": "revoca", "data_evento": "2026-09-03",
             "leggibile": False, "in_aggiornamenti": True},
        ]
        voci = rigenera.box_aggiornamenti(eventi)
        self.assertEqual(len(voci), 1)
        self.assertEqual(voci[0].tipo, "proroga")

    def test_box_ordinato_dal_piu_recente(self):
        eventi = [
            {"tipo": "proroga", "data_evento": "2026-09-01",
             "leggibile": True, "in_aggiornamenti": True},
            {"tipo": "graduatoria", "data_evento": "2026-09-10",
             "leggibile": True, "in_aggiornamenti": True},
        ]
        voci = rigenera.box_aggiornamenti(eventi)
        self.assertEqual([v.tipo for v in voci], ["graduatoria", "proroga"])


class TestSostituzione(unittest.TestCase):
    def test_sostituisce_nella_frase_con_la_parola_del_ruolo(self):
        testo = "Le domande vanno presentate entro il 6 ottobre 2026."
        nuovo, n = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertEqual(n, 1)
        self.assertIn("1 dicembre 2026", nuovo)
        self.assertNotIn("6 ottobre 2026", nuovo)

    def test_non_tocca_la_data_di_un_decreto(self):
        # LA regola: la frase parla dell'atto, non del termine.
        testo = (
            "Il bando e' stato adottato con determinazione DD 12 del 6 ottobre 2026. "
            "Le domande vanno presentate entro il 6 ottobre 2026."
        )
        nuovo, n = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertEqual(n, 1)
        self.assertIn("DD 12 del 6 ottobre 2026", nuovo)
        self.assertIn("entro il 1 dicembre 2026", nuovo)

    def test_frase_senza_parola_di_ruolo_resta(self):
        testo = "La conferenza di presentazione si e' tenuta il 6 ottobre 2026."
        nuovo, n = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertEqual(n, 0)
        self.assertEqual(nuovo, testo)

    def test_ruolo_apertura(self):
        testo = "Lo sportello e' attivo a partire dal 6 ottobre 2026."
        nuovo, n = rigenera.sostituisci_data(testo, VECCHIA, date(2026, 10, 22), "apertura")
        self.assertEqual(n, 1)
        self.assertIn("22 ottobre 2026", nuovo)

    def test_forma_numerica_conservata(self):
        testo = "Le domande entro il 06/10/2026."
        nuovo, _ = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertIn("01/12/2026", nuovo)

    def test_separatore_numerico_conservato(self):
        testo = "Le domande entro il 06.10.2026."
        nuovo, _ = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertIn("01.12.2026", nuovo)

    def test_forma_iso_conservata(self):
        testo = "Scadenza: 2026-10-06."
        nuovo, _ = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertIn("2026-12-01", nuovo)

    def test_piu_frasi_sostituite(self):
        testo = (
            "Le domande entro il 6 ottobre 2026. "
            "Il termine di chiusura e' il 6 ottobre 2026."
        )
        _, n = rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "scadenza")
        self.assertEqual(n, 2)

    def test_data_uguale_non_fa_niente(self):
        testo = "Le domande entro il 6 ottobre 2026."
        nuovo, n = rigenera.sostituisci_data(testo, VECCHIA, VECCHIA, "scadenza")
        self.assertEqual((nuovo, n), (testo, 0))

    def test_ruolo_sconosciuto_non_fa_niente(self):
        testo = "Le domande entro il 6 ottobre 2026."
        self.assertEqual(rigenera.sostituisci_data(testo, VECCHIA, NUOVA, "boh"), (testo, 0))


class TestParagrafi(unittest.TestCase):
    def test_individua_i_paragrafi_con_la_data(self):
        testo = (
            "Primo paragrafo senza date.\n\n"
            "Le domande entro il 6 ottobre 2026.\n\n"
            "Terzo paragrafo."
        )
        self.assertEqual(rigenera.paragrafi_con_data(testo, VECCHIA), (1,))

    def test_data_normativa_non_conta(self):
        testo = "Adottato con DGR 445 del 6 ottobre 2026."
        self.assertEqual(rigenera.paragrafi_con_data(testo, VECCHIA), ())


class TestGate(unittest.TestCase):
    PRIMA = "Le domande entro il 6 ottobre 2026 per un importo di 500.000 euro (Regione Lazio)."

    def test_riscrittura_valida(self):
        dopo = "Le domande entro il 1 dicembre 2026 per un importo di 500.000 euro (Regione Lazio)."
        esito = rigenera.gate_riscrittura(self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertTrue(esito.ammesso, esito.motivo)

    def test_data_nuova_assente(self):
        dopo = "Le domande entro dicembre per un importo di 500.000 euro (Regione Lazio)."
        esito = rigenera.gate_riscrittura(self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(esito.ammesso)
        self.assertIn("non compare", esito.motivo)

    def test_data_vecchia_ancora_presente(self):
        dopo = (
            "Le domande entro il 1 dicembre 2026 (gia' 6 ottobre 2026) "
            "per un importo di 500.000 euro (Regione Lazio)."
        )
        esito = rigenera.gate_riscrittura(self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(esito.ammesso)
        self.assertIn("ancora nel testo", esito.motivo)

    def test_importo_cambiato(self):
        dopo = "Le domande entro il 1 dicembre 2026 per un importo di 900.000 euro (Regione Lazio)."
        esito = rigenera.gate_riscrittura(self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(esito.ammesso)
        self.assertIn("Importi cambiati", esito.motivo.capitalize())

    def test_nome_proprio_sparito(self):
        dopo = "Le domande entro il 1 dicembre 2026 per un importo di 500.000 euro."
        esito = rigenera.gate_riscrittura(self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(esito.ammesso)
        self.assertIn("Regione", esito.motivo)

    def test_altra_data_cambiata(self):
        prima = (
            "Adottato il 1 settembre 2026. Le domande entro il 6 ottobre 2026 "
            "per un importo di 500.000 euro (Regione Lazio)."
        )
        dopo = (
            "Adottato il 2 settembre 2026. Le domande entro il 1 dicembre 2026 "
            "per un importo di 500.000 euro (Regione Lazio)."
        )
        esito = rigenera.gate_riscrittura(prima, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(esito.ammesso)
        self.assertIn("altre date", esito.motivo)

    def test_descrizione_breve_fuori_finestra(self):
        dopo = "Le domande entro il 1 dicembre 2026 per un importo di 500.000 euro (Regione Lazio)."
        corta = rigenera.gate_riscrittura(
            self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA, descrizione_breve="x" * 100)
        self.assertFalse(corta.ammesso)
        lunga = rigenera.gate_riscrittura(
            self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA, descrizione_breve="x" * 400)
        self.assertFalse(lunga.ammesso)
        giusta = rigenera.gate_riscrittura(
            self.PRIMA, dopo, vecchia=VECCHIA, nuova=NUOVA, descrizione_breve="x" * 250)
        self.assertTrue(giusta.ammesso, giusta.motivo)

    def test_finestra_dichiarata(self):
        self.assertEqual((rigenera.DESCRIZIONE_MIN, rigenera.DESCRIZIONE_MAX), (180, 320))


class TestRigenera(unittest.IsolatedAsyncioTestCase):
    BANDO = {
        "id": 905315,
        "slug": "psicologia-scolastica",
        "titolo": "Psicologia scolastica",
        "contenuto": (
            "Avviso Psicologia scolastica della Regione Lazio.\n\n"
            "Le domande vanno presentate entro il 6 ottobre 2026.\n\n"
            "Il bando e' stato adottato con determinazione DD 12 del 18 settembre 2026."
        ),
        "descrizione_breve": "x" * 250,
    }
    EVENTO = {"tipo": "proroga", "campo": "data_scadenza", "data_evento": "2026-12-01",
              "valore_dopo": {"data_scadenza": "2026-12-01"}, "url_prova": "https://ente.it/x"}

    async def test_sostituzione_deterministica_basta(self):
        scritture = []
        esito = await rigenera.rigenera(
            self.BANDO, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA, ruolo="scadenza",
            attivo=True, scrivi=_scrivi(scritture),
        )
        self.assertEqual(esito.via, "sostituzione")
        self.assertEqual(esito.sostituzioni, 1)
        self.assertTrue(esito.scritto)
        payload = scritture[0][1]
        self.assertIn("1 dicembre 2026", payload["contenuto"])
        self.assertIn("DD 12 del 18 settembre 2026", payload["contenuto"])

    async def test_slug_e_titolo_non_entrano_mai_nel_payload(self):
        scritture = []
        await rigenera.rigenera(
            self.BANDO, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA,
            attivo=True, scrivi=_scrivi(scritture),
        )
        payload = scritture[0][1]
        self.assertNotIn("slug", payload)
        self.assertNotIn("titolo", payload)
        self.assertEqual(set(payload), {"contenuto"})

    async def test_non_scrive_se_non_attivo(self):
        scritture = []
        esito = await rigenera.rigenera(
            self.BANDO, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA,
            attivo=False, scrivi=_scrivi(scritture),
        )
        self.assertFalse(esito.scritto)
        self.assertEqual(scritture, [])
        self.assertIn("contenuto", esito.payload)

    async def test_senza_date_resta_il_box(self):
        esito = await rigenera.rigenera(self.BANDO, self.EVENTO)
        self.assertEqual(esito.via, "box")
        self.assertEqual(len(esito.voci), 1)
        self.assertIn("prorogato", esito.voci[0].testo)

    async def test_riscrittura_dei_paragrafi_rimasti(self):
        # La data resta in un paragrafo che non nomina il ruolo: la
        # sostituzione deterministica non lo tocca, il riscrittore si'.
        bando = dict(self.BANDO, contenuto=(
            "Avviso della Regione Lazio.\n\n"
            "La finestra si chiude il 6 ottobre 2026 secondo il calendario."
        ))
        chiamate = []

        async def riscrittore(paragrafo, vecchia, nuova):
            chiamate.append(paragrafo)
            return paragrafo.replace("6 ottobre 2026", "1 dicembre 2026")

        esito = await rigenera.rigenera(
            bando, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA, ruolo="pubblicazione",
            riscrittore=riscrittore,
        )
        self.assertEqual(esito.via, "riscrittura")
        self.assertEqual(len(chiamate), 1)
        self.assertIn("1 dicembre 2026", esito.payload["contenuto"])

    async def test_tre_tentativi_poi_box(self):
        bando = dict(self.BANDO, contenuto=(
            "Avviso della Regione Lazio.\n\n"
            "La finestra si chiude il 6 ottobre 2026 secondo il calendario."
        ))
        tentativi = []

        async def pessimo(paragrafo, vecchia, nuova):
            tentativi.append(paragrafo)
            return "Testo completamente diverso senza date."

        scritture = []
        esito = await rigenera.rigenera(
            bando, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA, ruolo="pubblicazione",
            riscrittore=pessimo, attivo=True, scrivi=_scrivi(scritture),
        )
        self.assertEqual(len(tentativi), rigenera.TENTATIVI_MASSIMI)
        self.assertEqual(esito.via, "box")
        self.assertFalse(esito.scritto)
        self.assertEqual(scritture, [])
        # Il box resta pubblicato comunque: e' la garanzia di §6.2.
        self.assertEqual(len(esito.voci), 1)

    async def test_riscrittore_che_solleva_non_ferma_il_box(self):
        bando = dict(self.BANDO, contenuto=(
            "Avviso della Regione Lazio.\n\n"
            "La finestra si chiude il 6 ottobre 2026 secondo il calendario."
        ))

        async def esplode(paragrafo, vecchia, nuova):
            raise RuntimeError("modello non disponibile")

        esito = await rigenera.rigenera(
            bando, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA, ruolo="pubblicazione",
            riscrittore=esplode,
        )
        self.assertEqual(esito.via, "box")
        self.assertEqual(len(esito.voci), 1)

    async def test_anche_la_descrizione_breve_si_aggiorna(self):
        # E' la meta description e il testo della card: lasciarla vecchia
        # rimetterebbe in pagina, sulla superficie piu' vista di tutte, la
        # stessa contraddizione fra prosa e colonne che il modulo elimina.
        descrizione = (
            "Contributi della Regione Lazio per gli sportelli di ascolto "
            "psicologico nelle scuole del territorio regionale: le domande "
            "vanno presentate entro il 6 ottobre 2026 sulla piattaforma "
            "regionale dedicata agli avvisi del FSE+."
        )
        self.assertTrue(
            rigenera.DESCRIZIONE_MIN <= len(descrizione) <= rigenera.DESCRIZIONE_MAX)
        scritture = []
        esito = await rigenera.rigenera(
            dict(self.BANDO, descrizione_breve=descrizione), self.EVENTO,
            vecchia=VECCHIA, nuova=NUOVA, ruolo="scadenza",
            attivo=True, scrivi=_scrivi(scritture),
        )
        self.assertEqual(esito.sostituzioni_descrizione, 1)
        payload = scritture[0][1]
        self.assertIn("entro il 1 dicembre 2026", payload["descrizione_breve"])
        self.assertNotIn("6 ottobre 2026", payload["descrizione_breve"])

    async def test_descrizione_fuori_dalla_finestra_seo_resta_intatta(self):
        # «1 dicembre» e' un carattere piu' lungo di «6 ottobre»: su una
        # descrizione gia' al limite la riscrittura sfora i 320 caratteri.
        # Allora non si tocca — meglio una meta description vecchia che una
        # troncata da Google — e il contenuto si scrive lo stesso.
        descrizione = (
            "Contributi della Regione Lazio per gli sportelli di ascolto "
            "psicologico nelle scuole del territorio regionale: le domande "
            "vanno presentate entro il 6 ottobre 2026 sulla piattaforma "
            "regionale dedicata agli avvisi del FSE+ " + "e" * 98 + "."
        )
        self.assertEqual(len(descrizione), rigenera.DESCRIZIONE_MAX)
        scritture = []
        esito = await rigenera.rigenera(
            dict(self.BANDO, descrizione_breve=descrizione), self.EVENTO,
            vecchia=VECCHIA, nuova=NUOVA, ruolo="scadenza",
            attivo=True, scrivi=_scrivi(scritture),
        )
        self.assertEqual(esito.sostituzioni_descrizione, 0)
        self.assertEqual(set(scritture[0][1]), {"contenuto"})

    async def test_descrizione_senza_la_data_vecchia_non_si_tocca(self):
        scritture = []
        await rigenera.rigenera(
            self.BANDO, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA, ruolo="scadenza",
            attivo=True, scrivi=_scrivi(scritture),
        )
        self.assertEqual(set(scritture[0][1]), {"contenuto"})

    async def test_scrittura_fallita_non_solleva(self):
        async def scrivi(bando_id, payload):
            raise RuntimeError("PostgREST giu'")

        esito = await rigenera.rigenera(
            self.BANDO, self.EVENTO, vecchia=VECCHIA, nuova=NUOVA,
            attivo=True, scrivi=scrivi,
        )
        self.assertFalse(esito.scritto)


# --- lotto L7: `run_rigenera` (§6.4) ----------------------------------------

def _contenuto(*paragrafi, link=None):
    """`contenuto` nella forma jsonb che la skill SEO produce davvero.

    `link` aggiunge una sezione con un segmento `link`: e' il caso che la
    serializzazione `json.dumps` -> sostituzione -> `json.loads` rovinava,
    perche' la data compariva anche dentro l'URL.
    """
    sezioni = [
        {"type": "paragraph", "segments": [{"kind": "text", "text": testo}]}
        for testo in paragrafi
    ]
    if link is not None:
        sezioni.append({"type": "paragraph", "segments": [
            {"kind": "text", "text": "Il documento: "},
            {"kind": "link", "text": "avviso", "url": link},
        ]})
    return {"sections": sezioni}


def _url_di(contenuto):
    """Gli URL dei segmenti `link`, per verificare che nessuno sia cambiato."""
    trovati = []
    for sezione in contenuto.get("sections", ()):
        for segmento in sezione.get("segments", ()):
            if segmento.get("kind") == "link":
                trovati.append(segmento.get("url"))
    return trovati


def _bando(**extra):
    riga = {
        "id": 905315,
        "slug": "psicologia-scolastica-lazio",
        "titolo": "Psicologia scolastica",
        "contenuto": _contenuto(
            "Le domande vanno presentate entro il 6 ottobre 2026.",
            "Il bando attua il DD 12 del 6 ottobre 2026.",
        ),
        "descrizione_breve": "x" * 200,
        "stato_processing": "completed",
        "pubblicato": True,
    }
    riga.update(extra)
    return riga


def _testo(contenuto):
    """Tutto il testo dei segmenti, per leggere il risultato senza schemi."""
    pezzi = []
    for sezione in contenuto.get("sections", ()):
        for segmento in sezione.get("segments", ()):
            pezzi.append(segmento.get("text") or "")
    return " ".join(pezzi)


def _evento(**extra):
    riga = {
        "id": 7,
        "bando_id": 905315,
        "tipo": "proroga",
        "campo": "data_scadenza",
        "valore_prima": {"data_scadenza": "2026-10-06"},
        "valore_dopo": {"data_scadenza": "2026-12-01"},
        "data_evento": "2026-09-18",
        "verificato": True,
    }
    riga.update(extra)
    return riga


class TestDateDaEvento(unittest.TestCase):
    def test_proroga_e_sempre_la_scadenza(self):
        self.assertEqual(
            rigenera.date_da_evento(_evento(campo=None)),
            (VECCHIA, NUOVA, "scadenza"))

    def test_rettifica_apertura(self):
        esito = rigenera.date_da_evento(_evento(
            tipo="rettifica", campo="data_apertura",
            valore_prima={"data_apertura": "2026-10-06"},
            valore_dopo={"data_apertura": "2026-10-22"}))
        self.assertEqual(esito, (VECCHIA, date(2026, 10, 22), "apertura"))

    def test_senza_data_nuova_non_si_rigenera(self):
        # Una `chiusura` lascia `data_scadenza` intatta (§6.2): non c'e'
        # nessuna data vecchia da sostituire in prosa.
        self.assertIsNone(rigenera.date_da_evento(
            _evento(tipo="chiusura", campo=None, valore_dopo={}))[1])


class TestContenutoMalformato(unittest.TestCase):
    def test_riconosce_le_nove_righe(self):
        casi = [
            ('{"sections": [', True),          # troncato (id 18035)
            ('{"sections": []}', False),       # stringa ma JSON buono
            ({"sections": []}, False),
            ({"testo": "x"}, True),            # oggetto senza sections
            ([], True),
            (None, False),                     # NULL non e' malformato
        ]
        for valore, atteso in casi:
            with self.subTest(valore=valore):
                self.assertEqual(rigenera.contenuto_malformato(valore), atteso)


class TestRunRigenera(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # La riga `pipeline_run` esiste (§6.4 M19) ma qui non si scrive: il
        # test non deve nemmeno provare a risolvere l'host di Supabase.
        for bersaglio in (
            patch.object(rigenera, "_scrivi_run", MagicMock()),
            patch.object(rigenera, "_tetti", lambda: rigenera.bilancio.Tetti()),
        ):
            bersaglio.start()
            self.addCleanup(bersaglio.stop)

    async def test_ombra_per_difetto_non_scrive(self):
        scritture = []
        esito = await rigenera.run_rigenera(
            righe=[_bando()], eventi=[_evento()], scrivi=_scrivi(scritture))
        self.assertEqual(esito["step"], "backfill:L7")
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(scritture, [])
        self.assertEqual(esito["scritti"], 0)

    async def test_attivo_sostituisce_solo_la_frase_del_ruolo(self):
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, righe=[_bando()], eventi=[_evento()],
            scrivi=_scrivi(scritture))
        self.assertEqual(esito["scritti"], 1)
        scritto = scritture[0][1]["contenuto"]
        # Torna un jsonb, non la stringa su cui `rigenera()` ha lavorato: il
        # `repr` di un dizionario Python in colonna sarebbe illeggibile per
        # la scheda e per BandoFit.
        self.assertIsInstance(scritto, dict)
        testo = _testo(scritto)
        self.assertIn("entro il 1 dicembre 2026", testo)
        # Il decreto citato conserva la sua data: e' la regola di §6.2.
        self.assertIn("DD 12 del 6 ottobre 2026", testo)

    async def test_dry_run_e_piu_forte_di_attivo(self):
        scritture = []
        await rigenera.run_rigenera(
            attivo=True, dry_run=True, righe=[_bando()], eventi=[_evento()],
            scrivi=_scrivi(scritture))
        self.assertEqual(scritture, [])

    async def test_due_eventi_sullo_stesso_bando_si_incatenano(self):
        # Il differimento arriva in coppia: la seconda passata deve partire dal
        # contenuto gia' corretto dalla prima, altrimenti l'ultima scrittura
        # vince e una delle due date resta vecchia in prosa.
        bando = _bando(contenuto=_contenuto(
            "Le domande si presentano dal 1 ottobre 2026.",
            "Le domande si presentano entro il 6 ottobre 2026."))
        eventi = [
            _evento(id=1, tipo="rettifica", campo="data_apertura",
                    valore_prima={"data_apertura": "2026-10-01"},
                    valore_dopo={"data_apertura": "2026-10-22"}),
            _evento(id=2),
        ]
        scritture = []
        await rigenera.run_rigenera(
            attivo=True, righe=[bando], eventi=eventi, scrivi=_scrivi(scritture))
        self.assertEqual(len(scritture), 2)
        finale = _testo(scritture[-1][1]["contenuto"])
        self.assertIn("dal 22 ottobre 2026", finale)
        self.assertIn("entro il 1 dicembre 2026", finale)

    async def test_slug_e_titolo_non_entrano_mai_nel_payload(self):
        scritture = []
        await rigenera.run_rigenera(
            attivo=True, righe=[_bando()], eventi=[_evento()],
            scrivi=_scrivi(scritture))
        self.assertNotIn("slug", scritture[0][1])
        self.assertNotIn("titolo", scritture[0][1])
        self.assertNotIn("stato_processing", scritture[0][1])
        self.assertNotIn("pubblicato", scritture[0][1])

    async def test_contenuto_malformato_non_entra_nel_modo_date(self):
        # Il testo non esiste: non c'e' niente da sostituire, e tentarlo
        # riscriverebbe una stringa rotta dentro una colonna gia' rotta.
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, righe=[_bando(contenuto='{"sections": [')],
            eventi=[_evento()], scrivi=_scrivi(scritture))
        self.assertEqual(scritture, [])
        self.assertEqual(esito["saltati"], 1)
        self.assertEqual(esito["candidati"], 0)

    async def test_bando_mancante_non_ferma_il_lotto(self):
        esito = await rigenera.run_rigenera(
            attivo=True, righe=[], eventi=[_evento()], scrivi=_scrivi([]))
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["saltati"], 1)

    async def test_malformati_elenca_e_segnala(self):
        segnalati = []
        esito = await rigenera.run_rigenera(
            malformati=True, attivo=True,
            righe=[_bando(contenuto='{"sections": ['), _bando(id=2)],
            segnala=lambda bando_id, evento: segnalati.append((bando_id, evento)) or True,
        )
        self.assertEqual(esito["modo"], "malformati")
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["ids"], [905315])
        self.assertEqual(esito["segnalati"], 1)
        self.assertEqual(segnalati[0][1]["tipo"], "elaborazione_bloccata")
        # Evento interno: mai un cursore, mai nel box «Aggiornamenti».
        self.assertFalse(segnalati[0][1]["leggibile"])
        self.assertFalse(segnalati[0][1]["in_aggiornamenti"])

    async def test_malformati_in_ombra_non_segnala(self):
        segnalati = []
        esito = await rigenera.run_rigenera(
            malformati=True, righe=[_bando(contenuto='{"sections": [')],
            segnala=lambda bando_id, evento: segnalati.append(bando_id) or True,
        )
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(segnalati, [])

    async def test_gli_url_non_si_toccano_mai(self):
        # Il difetto piu' grave della consegna: con la serializzazione
        # `json.dumps` la sostituzione della data lavorava per offset e
        # riscriveva anche `.../2026-10-06/avviso.pdf`, cioe' fabbricava un
        # link mai esistito dentro una riga pubblicata.
        url = "https://www.regione.marche.it/archivio/2026-10-06/avviso.pdf"
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True,
            righe=[_bando(contenuto=_contenuto(
                "Le domande vanno presentate entro il 6 ottobre 2026.", link=url))],
            eventi=[_evento()], scrivi=_scrivi(scritture))
        self.assertEqual(esito["scritti"], 1)
        scritto = scritture[0][1]["contenuto"]
        self.assertEqual(_url_di(scritto), [url])
        self.assertIn("entro il 1 dicembre 2026", _testo(scritto))

    async def test_il_gate_butta_una_riscrittura_che_cambia_un_url(self):
        prima = "Domande entro il 6 ottobre 2026: https://ente.it/2026-10-06/a.pdf"
        dopo = "Domande entro il 1 dicembre 2026: https://ente.it/2026-12-01/a.pdf"
        gate = rigenera.gate_riscrittura(prima, dopo, vecchia=VECCHIA, nuova=NUOVA)
        self.assertFalse(gate.ammesso)
        self.assertIn("URL", gate.motivo)

    async def test_il_modo_date_guarda_solo_gli_eventi_gia_applicati(self):
        # In ombra un evento nasce `verificato=True, applicato=False`:
        # rigenerare prima di `applica-eventi` metterebbe in prosa una data
        # che la colonna non ha ancora.
        finto = MagicMock()
        finto.select_eventi.return_value = []
        # `from . import db` legge l'attributo del package se c'e' gia': va
        # sostituito anche quello, altrimenti vince il modulo vero.
        with patch.object(sys.modules[ALIAS], "db", finto, create=True), \
                patch.dict(sys.modules, {f"{ALIAS}.db": finto}):
            await rigenera.run_rigenera(righe=[])
        self.assertIs(finto.select_eventi.call_args.kwargs["applicato"], True)
        self.assertIs(finto.select_eventi.call_args.kwargs["verificato"], True)

    async def test_non_riscrive_un_contenuto_identico(self):
        """Il secondo giro sullo stesso evento non deve scrivere niente.

        Al secondo passaggio la sostituzione non trova piu' la data vecchia
        (zero sostituzioni), ma il gate passa lo stesso — la data nuova c'e' e
        la vecchia no — e il payload conteneva un `contenuto` byte per byte
        uguale a quello gia' in tabella, contato in `scritti`.
        """
        gia_corretto = _bando(contenuto=_contenuto(
            "Le domande vanno presentate entro il 1 dicembre 2026.",
            "Il bando attua il DD 12 del 6 ottobre 2026.",
        ))
        esito = await rigenera.rigenera(
            {"id": 905315, "contenuto": rigenera._testo_del_contenuto(
                gia_corretto)[0]["contenuto"]},
            _evento(), vecchia=VECCHIA, nuova=NUOVA, attivo=True,
            scrivi=_scrivi([]),
        )
        self.assertEqual(esito.payload, {})
        self.assertFalse(esito.scritto)

    async def test_il_modo_date_scorre_oltre_gli_eventi_senza_lavoro(self):
        """Nessuna scrittura di questo comando tocca `bando_evento`.

        Un evento verificato e applicato resta tale per sempre: i primi N per
        id erano gli stessi a ogni lancio, e i bandi la cui prosa e' gia' in
        linea riconsumavano il limite senza che niente cambiasse.
        """
        # Cinque eventi su bandi il cui testo dice gia' la data nuova: nessun
        # lavoro. I tre della pagina dopo sono quelli veri.
        gia_corretto = _contenuto("Le domande vanno presentate entro il 1 dicembre 2026.")
        pagine = {
            0: [_evento(id=i, bando_id=i) for i in range(1, 6)],
            5: [_evento(id=i, bando_id=i) for i in range(6, 9)],
        }
        bandi = {i: _bando(id=i, contenuto=gia_corretto) for i in range(1, 6)}
        bandi.update({i: _bando(id=i) for i in range(6, 9)})
        visti = []

        def _eventi(**parametri):
            visti.append(dict(parametri))
            return list(pagine.get(parametri.get("offset"), []))

        def _righe(**parametri):
            return [bandi[i] for i in parametri.get("bando_ids", ()) if i in bandi]

        finto = MagicMock()
        finto.select_eventi.side_effect = _eventi
        finto.select_bandi_pubblicati_contenuto.side_effect = _righe
        scritture = []
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True), \
                patch.object(rigenera, "PAGINA_SELEZIONE", 5):
            esito = await rigenera.run_rigenera(
                attivo=True, limit=2, scrivi=_scrivi(scritture))
        self.assertEqual(esito["saltati"], 5)
        self.assertEqual(esito["attraversati"], 7)
        self.assertEqual(esito["candidati"], 2)
        self.assertEqual(esito["scritti"], 2)
        self.assertEqual([v.get("offset") for v in visti[:2]], [0, 5])
        self.assertEqual(visti[0].get("limit"), 5)

    async def test_malformati_scorre_oltre_le_righe_sane(self):
        """9 righe irrecuperabili su 2 104: il limite non lo consumano le sane.

        Il filtro `contenuto_malformato` stava DOPO il `--limit`, quindi
        `--limit 500` trovava solo le malformate che stavano nei primi 500 id
        — per sempre, a ogni lancio.
        """
        pagine = {
            0: [_bando(id=i) for i in range(1, 6)],                     # sane
            5: [_bando(id=i, contenuto='{"sections": [') for i in (6, 7, 8)],
        }
        visti = []

        def _righe(**parametri):
            visti.append(dict(parametri))
            return list(pagine.get(parametri.get("offset"), []))

        finto = MagicMock()
        finto.select_bandi_pubblicati_contenuto.side_effect = _righe
        segnalati = []
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True), \
                patch.object(rigenera, "PAGINA_SELEZIONE", 5):
            esito = await rigenera.run_rigenera(
                malformati=True, attivo=True, limit=2,
                segnala=lambda bando_id, evento: segnalati.append(bando_id) or True)
        self.assertEqual(esito["candidati"], 2)
        self.assertEqual(esito["saltati"], 5)
        self.assertEqual(esito["attraversati"], 7)
        self.assertEqual(segnalati, [6, 7])
        self.assertEqual([v.get("offset") for v in visti[:2]], [0, 5])

    async def test_malformati_non_registra_due_volte_lo_stesso_evento(self):
        # `db.registra_evento` e' un INSERT nudo senza deduplica: senza questa
        # guardia ogni lancio aggiungeva un evento per riga (misurato: 4
        # eventi per 2 righe in due lanci).
        with patch.object(rigenera, "_bandi_gia_segnalati",
                          lambda ids: frozenset(ids)), \
                patch.object(rigenera, "_segnala_malformato") as segnala:
            esito = await rigenera.run_rigenera(
                malformati=True, attivo=True,
                righe=[_bando(contenuto='{"sections": [')])
        segnala.assert_not_called()
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["doppioni"], 1)
        self.assertEqual(esito["segnalati"], 0)

    async def test_un_residuo_senza_riscrittore_non_consuma_il_limite(self):
        """L'evento che nessuno strumento di questo lancio puo' chiudere.

        La data vecchia resta in una frase **senza parola di ruolo**: la
        sostituzione deterministica non la tocca per disegno e il gate finale
        respinge tutto, payload vuoto. Solo il riscrittore potrebbe togliere
        quel residuo, e dalla riga di comando il riscrittore non c'e'.

        Prima, l'evento era «lavoro»: si prendeva un posto del `--limit`,
        rigenerava a vuoto (`candidati: 1, rigenerati: 1, scritti: 0`) e — non
        essendo `bando_evento` mai toccata da questo comando — tornava in testa
        alla selezione a ogni lancio, per sempre.
        """
        bando = _bando(contenuto=_contenuto(
            "Le domande vanno presentate entro il 1 dicembre 2026.",
            "Il bando e' stato illustrato in un incontro il 6 ottobre 2026.",
        ))
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, limit=1, righe=[bando], eventi=[_evento()],
            scrivi=_scrivi(scritture))
        self.assertEqual(scritture, [])
        self.assertEqual(esito["candidati"], 0)
        self.assertEqual(esito["rigenerati"], 0)
        self.assertEqual(esito["saltati"], 1)
        # Il riepilogo lo dice: non e' una riga gia' a posto, e' una riga che
        # aspetta il modello.
        self.assertEqual(esito["senza_riscrittore"], 1)

    async def test_sostituzione_e_residuo_insieme_restano_fuori_dal_limite(self):
        # Il caso misto: una frase di ruolo (sostituibile) e una di contesto
        # (residuo). Il gate finale respinge **anche** la sostituzione buona,
        # quindi non si scrive niente nemmeno qui: se consumasse il limite
        # sarebbe lo stesso giro a vuoto.
        bando = _bando(contenuto=_contenuto(
            "Le domande vanno presentate entro il 6 ottobre 2026.",
            "Il bando e' stato illustrato in un incontro il 6 ottobre 2026.",
        ))
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, limit=1, righe=[bando], eventi=[_evento()],
            scrivi=_scrivi(scritture))
        self.assertEqual(scritture, [])
        self.assertEqual(esito["candidati"], 0)
        self.assertEqual(esito["senza_riscrittore"], 1)

    async def test_gli_irrisolvibili_non_rubano_il_limite_ai_risolvibili(self):
        """L'effetto composto: due eventi irrisolvibili davanti a uno risolvibile.

        Gli eventi si scorrono per id e nessuna scrittura di questo comando li
        fa uscire dalla selezione: con `--limit 1` i due davanti riempivano il
        limite a ogni lancio e il terzo non veniva mai raggiunto.
        """
        fermo = _contenuto(
            "Le domande vanno presentate entro il 1 dicembre 2026.",
            "Il bando e' stato illustrato in un incontro il 6 ottobre 2026.",
        )
        righe = [_bando(id=1, contenuto=fermo), _bando(id=2, contenuto=fermo),
                 _bando(id=3)]
        eventi = [_evento(id=1, bando_id=1), _evento(id=2, bando_id=2),
                  _evento(id=3, bando_id=3)]
        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, limit=1, righe=righe, eventi=eventi,
            scrivi=_scrivi(scritture))
        self.assertEqual([b for b, _ in scritture], [3])
        self.assertEqual(esito["scritti"], 1)
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["senza_riscrittore"], 2)

    async def test_con_il_riscrittore_il_residuo_e_lavoro(self):
        # L'altra faccia: quando il riscrittore c'e' davvero, il residuo torna
        # a essere lavoro e il passo 3 di §6.2 parte.
        bando = _bando(contenuto=_contenuto(
            "Le domande vanno presentate entro il 1 dicembre 2026.",
            "Il bando e' stato illustrato in un incontro il 6 ottobre 2026.",
        ))

        async def riscrittore(paragrafo, vecchia, nuova):
            return paragrafo.replace("6 ottobre 2026", "1 dicembre 2026")

        scritture = []
        esito = await rigenera.run_rigenera(
            attivo=True, limit=1, righe=[bando], eventi=[_evento()],
            riscrittore=riscrittore, scrivi=_scrivi(scritture))
        self.assertEqual(esito["senza_riscrittore"], 0)
        self.assertEqual(esito["candidati"], 1)
        self.assertEqual(esito["scritti"], 1)
        testo = _testo(scritture[0][1]["contenuto"])
        self.assertNotIn("6 ottobre 2026", testo)

    async def test_un_blocco_di_un_altro_autore_non_e_un_doppione(self):
        """`elaborazione_bloccata` non e' firmata solo da questo comando.

        Lo scrivono anche il monitor dopo cinque controlli falliti
        (`origine='worker'`) e la RPC `bando_applica_evento` sui rifiuti di data
        (`origine='pipeline'`, `campo='date'`). Prendendoli per nostri, un bando
        col contenuto malformato **e** la pagina irraggiungibile non veniva
        segnalato mai: «candidati: 9, segnalati: 0, doppioni: 9», che si legge
        «gia' fatto».
        """
        eventi_per_bando = {
            # Solo il monitor: la nostra segnalazione non c'e' ancora.
            6: [{"id": 11, "bando_id": 6, "tipo": "elaborazione_bloccata",
                 "origine": "worker", "campo": None,
                 "valore_dopo": {"motivo": "5 controlli falliti"}}],
            # La nostra, in mezzo a una del monitor: e' un doppione vero.
            7: [{"id": 12, "bando_id": 7, "tipo": "elaborazione_bloccata",
                 "origine": "worker", "campo": "allegati", "valore_dopo": {}},
                {"id": 13, "bando_id": 7, "tipo": "elaborazione_bloccata",
                 "origine": "pipeline", "campo": "contenuto", "valore_dopo": {}}],
            # Solo il rifiuto della RPC (migrazione 04): non e' nostro.
            8: [{"id": 14, "bando_id": 8, "tipo": "elaborazione_bloccata",
                 "origine": "pipeline", "campo": "date", "riferisce_a": 99,
                 "valore_dopo": {"motivo": "data_pubblicazione > data_scadenza"}}],
        }

        def _eventi(**parametri):
            return list(eventi_per_bando.get(parametri.get("bando_id"), ()))

        finto = MagicMock()
        finto.select_eventi.side_effect = _eventi
        finto.registra_evento.return_value = True
        rotte = [_bando(id=i, contenuto='{"sections": [') for i in (6, 7, 8)]
        with patch.dict(sys.modules, {f"{ALIAS}.db": finto}), \
                patch.object(sys.modules[ALIAS], "db", finto, create=True):
            esito = await rigenera.run_rigenera(
                malformati=True, attivo=True, righe=rotte)
        self.assertEqual(esito["candidati"], 3)
        self.assertEqual(esito["segnalati"], 2)
        self.assertEqual(esito["doppioni"], 1)
        segnalati = [c.args[0].get("bando_id")
                     for c in finto.registra_evento.call_args_list]
        self.assertEqual(segnalati, [6, 8])

    async def test_lotto_nomina_la_riga_di_pipeline_run(self):
        esito = await rigenera.run_rigenera(lotto="L9", righe=[], eventi=[])
        self.assertEqual(esito["step"], "backfill:L9")

    async def test_un_guasto_non_solleva(self):
        with patch.object(rigenera, "_lotto_date", side_effect=RuntimeError("giu'")):
            esito = await rigenera.run_rigenera(righe=[], eventi=[])
        self.assertEqual(esito["status"], "errore")


def _scrivi(registro):
    async def scrivi(bando_id, payload):
        registro.append((bando_id, payload))
        return True
    return scrivi


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
