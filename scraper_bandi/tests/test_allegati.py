# -*- coding: utf-8 -*-
"""Allegati deterministici (piano §5, §13.4).

La fixture obbligatoria del piano e' la pagina con i «bandi correlati»: e' il
caso che il modello sbaglia sistematicamente e che §13.4 promette a BandoFit di
non sbagliare mai. I riquadri dei correlati stanno **dentro `<main>`**, che e'
l'unica posizione che mette alla prova il filtro per id/class di
`impronte.NODI_RUMORE`: in un `<aside>` o fuori da `<main>` cadrebbero comunque,
per il tag o per l'ambito, e il test resterebbe verde anche con il filtro rotto.

Nessun test tocca la rete: la verifica HTTP e' la funzione iniettata di §5.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest

from tests.supporto import carica_modulo

allegati = carica_modulo("allegati")

URL = "https://regione.marche.it/bandi/psicologia-scolastica"
TITOLO = "Avviso per la psicologia scolastica 2026"

PAGINA = """
<html><body>
  <nav><a href="/bandi/tutti.pdf">Elenco di tutti i bandi</a></nav>
  <main>
    <h1>Avviso per la psicologia scolastica 2026</h1>
    <p><a href="/doc/avviso-psicologia.pdf">Avviso integrale</a></p>
    <p><a href="doc/modulo-domanda.docx">Scarica</a></p>
    <p><a href="/bandi/psicologia-scolastica/faq">FAQ psicologia scolastica</a></p>
    <p><a href="/modulistica">Modulistica</a></p>
    <p><a href="mailto:urp@regione.marche.it">Scrivici</a></p>
    <p><a href="#top">Torna su</a></p>
    <p><a href="https://obiettivoeuropa.com/bandi/942936">Scheda su Obiettivo Europa</a></p>
    <p><a href="/doc/avviso-psicologia.pdf?utm_source=news">Avviso (copia)</a></p>
    <div class="bandi-correlati">
      <h2>Bandi correlati</h2>
      <p><a href="/doc/altro-bando.pdf">Bando per la formazione docenti</a></p>
    </div>
    <section class="box-correlati">
      <p><a href="/doc/terzo-bando.pdf">Terzo bando</a></p>
    </section>
    <div class="widget-newsletter"><a href="/doc/newsletter.pdf">Iscriviti</a></div>
  </main>
  <aside class="bandi-related">
    <p><a href="/doc/aside-correlato.pdf">Bando in colonna laterale</a></p>
  </aside>
  <div class="sidebar"><a href="/doc/sidebar.pdf">Documento della sidebar</a></div>
</body></html>
"""

# Il PDF del bando correlato con l'estensione ammessa e l'ancora parlante: senza
# il filtro sui nodi sarebbe un allegato a tutti gli effetti.
CORRELATI = (
    "https://regione.marche.it/doc/altro-bando.pdf",
    "https://regione.marche.it/doc/terzo-bando.pdf",
    "https://regione.marche.it/doc/newsletter.pdf",
    "https://regione.marche.it/doc/aside-correlato.pdf",
    "https://regione.marche.it/doc/sidebar.pdf",
)


def verifica_ok(url):
    """Trasporto finto: PDF per i documenti, HTML per le pagine."""
    if any(url.endswith(e) for e in (".pdf", ".docx")):
        tipo = "application/pdf" if url.endswith(".pdf") else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return (200, tipo, "ab" * 32, 'W/"7"', "Wed, 16 Sep 2026 10:00:00 GMT")
    return (200, "text/html; charset=utf-8", None, None, None)


class BandiCorrelati(unittest.TestCase):
    """La fixture obbligatoria di §5."""

    def setUp(self):
        self.estrazione = allegati.estrai(PAGINA, URL, TITOLO, verifica=verifica_ok)

    def test_i_pdf_dei_bandi_correlati_non_entrano(self):
        url = [a.url for a in self.estrazione.allegati]
        for correlato in CORRELATI:
            self.assertNotIn(correlato, url)

    def test_i_correlati_dentro_main_non_arrivano_nemmeno_agli_scarti(self):
        # Sono spariti nella pulizia, prima che si leggesse il primo href: se
        # comparissero fra gli scarti vorrebbe dire che il filtro li ha lasciati
        # passare e che qualcun altro li ha fermati per caso.
        visti = {a.url for a in self.estrazione.allegati}
        visti |= {s.url for s in self.estrazione.scartati}
        self.assertNotIn("https://regione.marche.it/doc/altro-bando.pdf", visti)
        self.assertNotIn("https://regione.marche.it/doc/terzo-bando.pdf", visti)

    def test_i_link_di_navigazione_non_entrano(self):
        url = [a.url for a in self.estrazione.allegati]
        self.assertNotIn("https://regione.marche.it/bandi/tutti.pdf", url)

    def test_gli_allegati_veri_entrano_una_volta_sola(self):
        self.assertEqual(
            [a.url for a in self.estrazione.allegati],
            [
                "https://regione.marche.it/doc/avviso-psicologia.pdf",
                "https://regione.marche.it/bandi/doc/modulo-domanda.docx",
            ],
        )

    def test_forma_fissa(self):
        for allegato in self.estrazione.allegati:
            self.assertEqual(set(allegato.forma()), {"label", "url", "tipo"})
        self.assertEqual(
            self.estrazione.forma()[0],
            {
                "label": "Avviso integrale",
                "url": "https://regione.marche.it/doc/avviso-psicologia.pdf",
                "tipo": "pdf",
            },
        )

    def test_etichetta_dal_nome_del_file_quando_l_ancora_e_generica(self):
        self.assertEqual(self.estrazione.allegati[1].label, "Modulo domanda")

    def test_aggregatore_scartato_con_il_suo_motivo(self):
        motivi = {s.url: s.motivo for s in self.estrazione.scartati}
        self.assertEqual(
            motivi.get("https://obiettivoeuropa.com/bandi/942936"), "dominio aggregatore"
        )

    def test_dati_per_bando_link(self):
        primo = self.estrazione.allegati[0].verifica
        self.assertEqual(primo.esito_http, 200)
        self.assertEqual(primo.sha256, "ab" * 32)
        self.assertEqual(primo.etag, 'W/"7"')
        self.assertTrue(primo.ok)


class Sottopagine(unittest.TestCase):
    def test_figlia_del_percorso_ammessa(self):
        estrazione = allegati.estrai(PAGINA, URL, TITOLO, verifica=verifica_ok)
        self.assertEqual(
            estrazione.sottopagine,
            ("https://regione.marche.it/bandi/psicologia-scolastica/faq",),
        )

    def test_parole_deboli_da_sole_non_bastano(self):
        # `/modulistica` non e' figlia del percorso e la sua ancora e' una sola
        # parola debole: aprirla sarebbe un fetch a caso.
        estrazione = allegati.estrai(PAGINA, URL, TITOLO, verifica=verifica_ok)
        self.assertNotIn("https://regione.marche.it/modulistica", estrazione.sottopagine)

    def test_ancora_con_meta_dei_token_del_titolo(self):
        html = ('<main><h1>Avviso psicologia scolastica</h1>'
                '<p><a href="/altro/psicologia-scolastica-avviso">Avviso psicologia scolastica</a></p></main>')
        estrazione = allegati.estrai(html, URL, "Avviso psicologia scolastica")
        self.assertEqual(
            estrazione.sottopagine,
            ("https://regione.marche.it/altro/psicologia-scolastica-avviso",),
        )

    def test_tetto_di_sei(self):
        voci = "".join(
            f'<p><a href="/bandi/psicologia-scolastica/pagina-{i}">Pagina {i}</a></p>'
            for i in range(10)
        )
        estrazione = allegati.estrai(f"<main><h1>{TITOLO}</h1>{voci}</main>", URL, TITOLO)
        self.assertEqual(len(estrazione.sottopagine), allegati.MAX_SOTTOPAGINE)
        self.assertIn(
            "oltre il tetto delle sottopagine", {s.motivo for s in estrazione.scartati}
        )


class VerificaHttp(unittest.TestCase):
    HTML = '<main><h1>Bando</h1><p><a href="/doc/a.pdf">Avviso</a></p></main>'

    def test_404_scartato(self):
        estrazione = allegati.estrai(
            self.HTML, URL, "Bando", verifica=lambda u: (404, None, None, None, None)
        )
        self.assertEqual(estrazione.allegati, ())
        self.assertEqual(estrazione.scartati[0].motivo, "http 404")

    def test_senza_verifica_l_allegato_resta_non_verificato(self):
        # Il 2xx e' una condizione del contratto: senza verifica l'allegato
        # esiste ma non e' pubblicabile, e deve vedersi.
        estrazione = allegati.estrai(self.HTML, URL, "Bando")
        self.assertEqual(len(estrazione.allegati), 1)
        self.assertIsNone(estrazione.allegati[0].verifica)

    def test_content_type_promuove_un_url_senza_estensione(self):
        html = '<main><h1>Bando</h1><p><a href="/download/9912">Scarica il decreto</a></p></main>'
        estrazione = allegati.estrai(
            html, URL, "Bando",
            verifica=lambda u: (200, "application/pdf; charset=binary", None, None, None),
        )
        self.assertEqual(estrazione.allegati[0].tipo, "pdf")

    def test_content_type_html_non_e_un_allegato(self):
        html = '<main><h1>Bando</h1><p><a href="/download/9912">Scarica il decreto</a></p></main>'
        estrazione = allegati.estrai(
            html, URL, "Bando", verifica=lambda u: (200, "text/html", None, None, None)
        )
        self.assertEqual(estrazione.allegati, ())
        self.assertIn("content-type non ammesso", estrazione.scartati[0].motivo)

    def test_verifica_accetta_anche_un_dizionario(self):
        estrazione = allegati.estrai(
            self.HTML, URL, "Bando",
            verifica=lambda u: {"esito_http": 200, "content_type": "application/pdf"},
        )
        self.assertEqual(estrazione.allegati[0].verifica.esito_http, 200)


class Unione(unittest.TestCase):
    def test_dedup_fra_pagina_e_sottopagina(self):
        principale = allegati.estrai(
            '<main><h1>Bando</h1><p><a href="/doc/a.pdf">Scarica</a></p></main>',
            URL, "Bando", verifica=verifica_ok,
        )
        sottopagina = allegati.estrai(
            '<main><h1>Bando</h1><p><a href="/doc/a.pdf">Avviso integrale</a></p></main>',
            URL + "/allegati", "Bando", verifica=verifica_ok,
        )
        unita = allegati.unisci(principale, sottopagina)
        self.assertEqual(len(unita.allegati), 1)
        # L'etichetta parlante vince su «Scarica».
        self.assertEqual(unita.allegati[0].label, "Avviso integrale")

    def test_tetto(self):
        voci = "".join(f'<p><a href="/doc/{i}.pdf">Documento {i}</a></p>' for i in range(30))
        estrazione = allegati.estrai(f"<main><h1>Bando</h1>{voci}</main>", URL, "Bando")
        self.assertEqual(len(allegati.unisci(estrazione, massimo=20).allegati), 20)


class Aiutanti(unittest.TestCase):
    def test_estensione(self):
        self.assertEqual(allegati.estensione("https://x.it/a/b.PDF?x=1"), "pdf")
        self.assertEqual(allegati.estensione("https://x.it/a/b"), "")

    def test_copertura(self):
        self.assertEqual(
            allegati.copertura("Avviso psicologia scolastica", "Psicologia scolastica: avviso"), 1.0
        )
        self.assertAlmostEqual(
            allegati.copertura("Avviso psicologia scolastica", "psicologia scolastica"), 2 / 3
        )
        self.assertEqual(allegati.copertura("", "qualsiasi"), 0.0)

    def test_etichetta_da(self):
        self.assertEqual(allegati.etichetta_da("Clicca qui", "https://x.it/avviso_2026.pdf"), "Avviso 2026")
        self.assertEqual(allegati.etichetta_da("Avviso integrale", "https://x.it/a.pdf"), "Avviso integrale")


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
