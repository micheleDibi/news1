# -*- coding: utf-8 -*-
"""Lettori dello stato sulle pagine ufficiali (contratto `bandi-giro-2` §6.1 e §19.5).

Le fixture in `tests/fixtures/etichette_stato/` sono pagine vere scaricate una
volta il 01/10/2026 (curl, 1 s di pausa), tagliate (niente script, stili,
immagini, menu, piedi) e ripulite da email e telefoni; `indice.json` dice da
quale URL viene ognuna. Dove una forma non si e' trovata su nessuna pagina
vera (Piemonte «concluso», Calabria «Conclusione», Toscana «Chiuso», FVG
«[BANDO CHIUSO]», una colonna laterale con altri bandi chiusi) il test cambia
l'etichetta dentro una pagina vera, e lo dice.

Funzioni pure: nessuna rete.
"""
import json
import re
import unittest
from datetime import date, time

from tests.supporto import RADICE, carica_modulo

es = carica_modulo("etichette_stato")

CARTELLA = RADICE / "tests" / "fixtures" / "etichette_stato"
INDICE = json.loads((CARTELLA / "indice.json").read_text(encoding="utf-8"))
#: 01/10/2026, il giorno delle fixture.
OGGI = date(2026, 10, 1)


def _html(nome: str) -> str:
    return (CARTELLA / nome).read_text(encoding="utf-8")


def _leggi(nome: str, html: str | None = None, url: str | None = None):
    return es.leggi(html if html is not None else _html(nome), url or INDICE[nome]["url"], "",
                    oggi=OGGI)


def _sintesi(lettura):
    if lettura is None:
        return None
    t = lettura.termine_finale
    return (lettura.estrattore, lettura.stato, lettura.puo_chiudere, lettura.solo_segnale,
            (t.data, t.ora) if t else None)


#: L'esito atteso di ogni fixture: (estrattore, stato, puo_chiudere, solo_segnale, termine).
ATTESI = {
    # primo lotto (§6.1)
    "piemonte_aperto_18454.html": ("piemonte", "aperto", False, False, None),
    "piemonte_scaduto_2890.html": ("piemonte", "chiuso", True, False, None),
    "piemonte_attuato_2971.html": ("piemonte", "uscito", False, False, None),
    # «Esito» (graduatoria pubblicata), il bando collegato di 150489: solo segnale (#76).
    "piemonte_esito_collegato_150489.html": ("piemonte", "chiuso", False, True, None),
    # «Data presunta di apertura del bando metà Giugno 2026»: passata, non decide.
    "piemonte_preinformazione_2940.html": ("piemonte", "non_decisiva", False, False, None),
    "lazioeuropa_prossima_apertura_2363.html": ("lazioeuropa", "in_apertura", False, False, None),
    "lazioeuropa_aperto_1072674.html": ("lazioeuropa", "aperto", False, False,
                                        (date(2026, 10, 29), time(17, 0))),
    "lazioeuropa_chiuso_2387.html": ("lazioeuropa", "chiuso", True, False, None),
    "lazioeuropa_chiuso_106753.html": ("lazioeuropa", "chiuso", True, False,
                                       (date(2026, 7, 24), time(12, 0))),
    "lazioeuropa_chiuso_2375.html": ("lazioeuropa", "chiuso", True, False,
                                     (date(2026, 8, 10), time(12, 0))),
    "lombardia_aperto_17664.html": ("lombardia", "aperto", False, False, None),
    "lombardia_chiuso_18344.html": ("lombardia", "chiuso", True, False,
                                    (date(2025, 7, 25), time(12, 0))),
    "calabria_aperto_17903.html": ("calabria", "aperto", False, False, None),
    "calabria_chiuso_17978.html": ("calabria", "chiuso", True, False, None),
    "calabria_valutazione_18337.html": ("calabria", "chiuso", False, True, None),
    "calabria_valutazione_18231.html": ("calabria", "chiuso", False, True, None),
    "calabria_pubblicazione_18315.html": ("calabria", "non_decisiva", False, False, None),
    # VERITA_NOTA: 1261858 «in apertura» confermato.
    "calabria_preinformazione_1261858.html": ("calabria", "in_apertura", False, False, None),
    "calabria_rc_pubblicata_18089.html": ("calabria_rc", "non_decisiva", False, False, None),
    # «Prossimo avvio» con «Data presunta di apertura: II semestre 2025», passata.
    "puglia_prossimo_avvio_10253.html": ("puglia", "non_decisiva", False, False, None),
    "formazionelavoro_aperto_2339.html": ("formazionelavoro_er", "aperto", False, False,
                                          (date(2027, 1, 19), time(12, 0))),
    # «Bando Chiuso» e' solo segnale, ma il termine passato e' certo: vincono le date.
    "formazionelavoro_chiuso_2340.html": ("formazionelavoro_er", "chiuso", False, False,
                                          (date(2026, 9, 24), time(12, 0))),
    "fesr_in_corso_256211.html": ("fesr_er", "chiuso", False, False,
                                  (date(2026, 9, 25), time(16, 0))),
    "pninclusione_preavviso_327381.html": ("pninclusione", "in_apertura", False, False, None),
    # «Data presunta apertura bando/avviso: Settembre 2026», passata.
    "pninclusione_preavviso_577475.html": ("pninclusione", "non_decisiva", False, False, None),
    # secondo lotto
    "invitalia_attivo_18281.html": ("invitalia", "aperto", False, False, None),
    "invitalia_chiuso_17868.html": ("invitalia", "chiuso", True, False, (date(2026, 6, 23), None)),
    "toscana_aperto_18145.html": ("toscana", "aperto", False, False, None),
    "toscana_in_corso_17989.html": ("toscana", "chiuso", False, False,
                                    (date(2026, 6, 30), time(13, 0))),
    "fvg_aperto_18308.html": ("fvg", "aperto", False, False, None),
    # generico: host senza lettore dedicato
    "generico_so_camcom_18276.html": ("generico", "chiuso", False, True, None),
    "generico_va_camcom_18262.html": ("generico", "chiuso", False, True, None),
    "generico_puglia_sospeso_5699.html": ("generico", "chiuso", False, True, None),
    "generico_neg_esaurimento_18564.html": None,
    "sconosciuto_sicilia_3042.html": None,
}


class TestFixture(unittest.TestCase):
    def test_ogni_fixture_ha_il_suo_esito(self):
        for nome, atteso in ATTESI.items():
            with self.subTest(fixture=nome):
                self.assertEqual(_sintesi(_leggi(nome)), atteso)

    def test_nessun_dato_personale_nelle_fixture(self):
        # Revisione del #73: email offuscate da Cloudflare, email nominative e
        # nomi dei responsabili non devono restare in nessuna fixture.
        vietati = {
            "email offuscata": re.compile(r"email-protection#[0-9a-f]{10,}"),
            "data-cfemail": re.compile(r"data-cfemail"),
            "email nominativa": re.compile(r"[\w+-]+\.[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
            "Dott. + nome": re.compile(r"(?i:dott)(?:ssa|\.ssa)?\.?\s+[A-Z][a-z]+"),
        }
        for nome in sorted(p.name for p in CARTELLA.glob("*.html")):
            testo = _html(nome)
            for motivo, modello in vietati.items():
                with self.subTest(fixture=nome, motivo=motivo):
                    self.assertIsNone(modello.search(testo))

    def test_ogni_fixture_e_nell_indice_e_senza_dati_personali(self):
        nomi = {p.name for p in CARTELLA.glob("*.html")}
        self.assertEqual(nomi, set(INDICE))
        self.assertTrue(set(ATTESI) <= nomi)
        for nome in nomi:
            testo = _html(nome)
            with self.subTest(fixture=nome):
                self.assertLess(len(testo.encode("utf-8")), 80_000)
                email = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", testo)
                self.assertTrue(all(e.endswith("esempio.invalid") for e in email), email[:3])


class TestRegoleDelContratto(unittest.TestCase):
    def test_fesr_ignora_in_corso_e_chiude_per_le_date(self):
        lettura = _leggi("fesr_in_corso_256211.html")
        self.assertIn("In corso", lettura.etichetta)
        self.assertEqual(lettura.stato, "chiuso")
        self.assertFalse(lettura.puo_chiudere)
        self.assertEqual(lettura.termine_finale.data, date(2026, 9, 25))
        # Il termine entra fra le date della lettura (G7e le confronta).
        self.assertEqual([(d.ruolo, d.data) for d in lettura.date], [("scadenza", date(2026, 9, 25))])

    def test_valutazione_e_chiuso_solo_segnale(self):
        for nome in ("calabria_valutazione_18337.html", "calabria_valutazione_18231.html"):
            lettura = _leggi(nome)
            self.assertEqual((lettura.stato, lettura.solo_segnale, lettura.puo_chiudere),
                             ("chiuso", True, False))

    def test_pubblicata_e_pubblicazione_non_decidono(self):
        self.assertEqual(_leggi("calabria_pubblicazione_18315.html").stato, "non_decisiva")
        self.assertEqual(_leggi("calabria_rc_pubblicata_18089.html").stato, "non_decisiva")

    def test_markup_sconosciuto(self):
        # Host con lettore ma senza il suo markup: None, e niente generico.
        self.assertIsNone(_leggi("sconosciuto_sicilia_3042.html",
                                 url="https://www.lazioeuropa.it/bandi/qualcosa/"))
        self.assertIsNone(_leggi("sconosciuto_sicilia_3042.html"))
        html = _html("lombardia_aperto_17664.html").replace(">Aperto<", ">In arrivo<")
        self.assertIsNone(_leggi("lombardia_aperto_17664.html", html=html))

    def test_le_date_vincono_su_un_etichetta_aperta(self):
        # Toscana «In corso» con scadenza 30.06.2026 passata: chiuso, strada rettifica.
        lettura = _leggi("toscana_in_corso_17989.html")
        self.assertEqual((lettura.stato, lettura.puo_chiudere), ("chiuso", False))
        # Un «Chiuso» con puo_chiudere resta tale (§5.6 e): 18344 e la verita' nota.
        lettura = _leggi("lombardia_chiuso_18344.html")
        self.assertEqual((lettura.stato, lettura.puo_chiudere), ("chiuso", True))

    def test_nessuna_data_presunta_come_termine(self):
        html = _html("toscana_in_corso_17989.html").replace(
            "Data di scadenza presentazione domande:",
            "Data di scadenza presentazione domande (presunta):")
        lettura = _leggi("toscana_in_corso_17989.html", html=html)
        self.assertIsNone(lettura.termine_finale)
        self.assertEqual(lettura.stato, "non_decisiva")
        # Le date presunte di pre-informazione non diventano mai un termine.
        for nome in ("piemonte_preinformazione_2940.html", "pninclusione_preavviso_577475.html",
                     "puglia_prossimo_avvio_10253.html"):
            self.assertIsNone(_leggi(nome).termine_finale)

    def test_finestre_periodiche_senza_termine_non_decidono(self):
        html = ('<html><body><main><div class="single-bandi-status">Aperto</div>'
                "<p>Le domande si presentano in finestre annuali.</p></main></body></html>")
        lettura = es.leggi(html, "https://www.lazioeuropa.it/bandi/x/", "", oggi=OGGI)
        self.assertEqual(lettura.stato, "non_decisiva")

    def test_sospeso_strutturato_e_solo_segnale(self):
        html = _html("calabria_aperto_17903.html").replace("</i> Aperto </span>", "</i> Sospeso </span>", 1)
        self.assertIn("Sospeso", html)
        lettura = _leggi("calabria_aperto_17903.html", html=html)
        self.assertEqual((lettura.stato, lettura.solo_segnale, lettura.puo_chiudere),
                         ("chiuso", True, False))


class TestEtichetteSenzaPaginaVera(unittest.TestCase):
    """Forme previste dal contratto e non trovate il 01/10: etichetta cambiata in una pagina vera.

    Una chiusura mai vista su una pagina vera vale SOLO SEGNALE finche' non
    entra una fixture vera (revisione del #73).
    """

    def test_piemonte_concluso(self):
        html = _html("piemonte_scaduto_2890.html").replace("stato-scaduto", "stato-concluso") \
            .replace(">Scaduto<", ">Concluso<")
        self.assertEqual(_sintesi(_leggi("piemonte_scaduto_2890.html", html=html)),
                         ("piemonte", "chiuso", False, True, None))

    def test_calabria_conclusione(self):
        html = _html("calabria_chiuso_17978.html").replace("</i> Chiuso </span>", "</i> Conclusione </span>", 1)
        self.assertIn("Conclusione", html)
        self.assertEqual(_sintesi(_leggi("calabria_chiuso_17978.html", html=html)),
                         ("calabria", "chiuso", False, True, None))

    def test_toscana_chiuso(self):
        html = re.sub(r"(is-)open(\"><span class=\"rtds-sr-only\">Stato: </span>\s*)Aperto",
                      r"\1closed\2Chiuso", _html("toscana_aperto_18145.html"), count=1)
        self.assertIn("is-closed", html)
        self.assertEqual(_sintesi(_leggi("toscana_aperto_18145.html", html=html)),
                         ("toscana", "chiuso", False, True, None))

    def test_fvg_chiuso_solo_segnale(self):
        html = _html("fvg_aperto_18308.html").replace("[BANDO APERTO]", "[BANDO CHIUSO]")
        self.assertEqual(_sintesi(_leggi("fvg_aperto_18308.html", html=html)),
                         ("fvg", "chiuso", False, True, None))


class TestGenerico(unittest.TestCase):
    def _generico(self, nome, html=None):
        return es.leggi_generico(html if html is not None else _html(nome), INDICE[nome]["url"], "",
                                 oggi=OGGI)

    def test_positivi(self):
        for nome, etichetta in (("generico_so_camcom_18276.html", "Bando Chiuso"),
                                ("generico_va_camcom_18262.html", "Domande chiuse"),
                                ("generico_puglia_sospeso_5699.html", "Avviso pubblico sospeso")):
            with self.subTest(fixture=nome):
                lettura = self._generico(nome)
                self.assertEqual((lettura.stato, lettura.solo_segnale, lettura.puo_chiudere),
                                 ("chiuso", True, False))
                self.assertEqual(lettura.etichetta, etichetta)

    def test_mai_aperto_mai_chiusura(self):
        for nome in INDICE:
            with self.subTest(fixture=nome):
                lettura = self._generico(nome)
                if lettura is not None:
                    self.assertEqual((lettura.estrattore, lettura.stato, lettura.solo_segnale,
                                      lettura.puo_chiudere), ("generico", "chiuso", True, False))

    def test_negativi(self):
        # «termini aperti (fino ad esaurimento delle risorse disponibili)»
        self.assertIsNone(self._generico("generico_neg_esaurimento_18564.html"))
        # «Bando Aperto» (fesr) e «Attivo» (invitalia): il generico non dice mai aperto.
        self.assertIsNone(self._generico("generico_neg_bando_aperto_326536.html"))
        self.assertIsNone(self._generico("invitalia_attivo_18281.html"))

    def test_colonna_laterale_con_altri_bandi_chiusi(self):
        # Nessuna pagina vera l'aveva il 01/10: una colonna laterale inserita
        # nella pagina vera di 18564, con altri bandi chiusi.
        laterale = ('<aside class="sidebar"><h3>Altri bandi</h3><ul>'
                    "<li>Bando Alfa: domande chiuse</li><li>Avviso Beta - Bando chiuso</li>"
                    '</ul></aside><div class="related-posts"><p>Bando Gamma scaduto</p></div>')
        html = _html("generico_neg_esaurimento_18564.html").replace("</body>", laterale + "</body>")
        self.assertIsNone(self._generico("generico_neg_esaurimento_18564.html", html=html))
        # La stessa frase nel corpo invece conta.
        nel_corpo = re.sub(r"(<main[^>]*>)", r"\1<p>Avviso Beta - Bando chiuso.</p>",
                           _html("generico_neg_esaurimento_18564.html"), count=1)
        self.assertIsNotNone(self._generico("generico_neg_esaurimento_18564.html", html=nel_corpo))

    def test_futuro_e_potenziale_non_contano(self):
        for frase in ("Il bando sarà chiuso il 30/11/2026.", "Lo sportello potrà essere sospeso.",
                      "Domande chiuse il 30/11/2026.", "Bando aperto fino ad esaurimento fondi.",
                      "Domande fino al 30/11/2026, salvo chiusura anticipata dello sportello."):
            with self.subTest(frase=frase):
                html = f"<html><body><main><h1>Avviso</h1><p>{frase}</p></main></body></html>"
                self.assertIsNone(es.leggi_generico(html, "https://ente.example.it/x", "", oggi=OGGI))
        html = "<html><body><main><p>Domande chiuse il 15/09/2026.</p></main></body></html>"
        self.assertIsNotNone(es.leggi_generico(html, "https://ente.example.it/x", "", oggi=OGGI))

    def test_host_senza_lettore_usa_il_generico(self):
        html = "<html><body><main><h1>Bando chiuso</h1></main></body></html>"
        self.assertEqual(es.leggi(html, "https://www.ente.example.it/x", "", oggi=OGGI).estrattore,
                         "generico")
        # Un host con lettore non ricade mai sul generico.
        self.assertIsNone(es.leggi(html, "https://www.lazioeuropa.it/x", "", oggi=OGGI))


class TestPurezzaEDati(unittest.TestCase):
    def test_estrattori(self):
        self.assertEqual(es.ESTRATTORI, (
            "piemonte", "lazioeuropa", "lombardia", "calabria", "calabria_rc", "puglia",
            "formazionelavoro_er", "fesr_er", "pninclusione", "invitalia", "toscana", "fvg",
            "generico"))
        dedicati = {k for chiavi in es.LETTORI_PER_HOST.values() for k in chiavi}
        self.assertEqual(dedicati, set(es.ESTRATTORI) - {"generico"})
        for lettura in filter(None, (_leggi(n) for n in INDICE)):
            self.assertIn(lettura.estrattore, es.ESTRATTORI)
            self.assertIn(lettura.stato, es.STATI_LETTURA)

    def test_lettura_immutabile(self):
        lettura = _leggi("calabria_aperto_17903.html")
        with self.assertRaises(Exception):
            lettura.stato = "chiuso"


class TestSorellaEPeriodo(unittest.TestCase):
    def test_sorella_preavviso(self):
        base = "https://pninclusione21-27.lavoro.gov.it"
        self.assertEqual(es.sorella_preavviso(f"{base}/preavvisi/leps-pippi"), f"{base}/avvisi/leps-pippi")
        self.assertEqual(es.sorella_preavviso(f"{base}/preavvisi/x?y=1#z"), f"{base}/avvisi/x")
        for url in (f"{base}/avvisi/leps-pippi", "https://altro.gov.it/preavvisi/x", None, ""):
            self.assertIsNone(es.sorella_preavviso(url))

    def test_periodo_indicativo(self):
        for testo, atteso in (
            ("ottobre-novembre 2026", date(2026, 11, 30)),
            ("ottobre 2026 - novembre 2026", date(2026, 11, 30)),
            ("Settembre-ottobre 2026", date(2026, 10, 31)),
            ("giugno/luglio 2026", date(2026, 7, 31)),
            ("metà Giugno 2026", date(2026, 6, 30)),
            ("Fine giugno 2026", date(2026, 6, 30)),
            ("dicembre 2025 - febbraio 2026", date(2026, 2, 28)),
            ("Emanazione Settembre 2026 con sessioni annuali da avviarsi nel mese di settembre 2026",
             date(2026, 9, 30)),
            ("II semestre 2025", date(2025, 12, 31)),
            ("primo trimestre 2026", date(2026, 3, 31)),
        ):
            with self.subTest(testo=testo):
                self.assertEqual(es.periodo_indicativo(testo), atteso)

    def test_periodi_incerti(self):
        for testo in ("2027-2029", "procedura a sportello\n2028-2030", "da definire",
                      "1^ finestra: settembre-ottobre 2026\n2^ finestra: primavera 2027",
                      "4^ scadenza:settembre 2026", "Aprile - giugno 2026 con finestre annuali",
                      "", None, 12):
            with self.subTest(testo=testo):
                self.assertIsNone(es.periodo_indicativo(testo))

    def test_periodo_dal_raw_data_dei_calendari(self):
        self.assertEqual(es.periodo_indicativo({"col_6": "ottobre-novembre 2026", "row_index": 10}),
                         date(2026, 11, 30))                                         # VdA PDF
        self.assertEqual(es.periodo_indicativo({"Unnamed: 6": "Settembre-ottobre 2026"}),
                         date(2026, 10, 31))                                         # VdA CSV
        self.assertIsNone(es.periodo_indicativo({"DATA_CHIUSUR A": "da definire"}))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
