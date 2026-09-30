# -*- coding: utf-8 -*-
"""Normalizzazione, impronte e diff delle pagine (piano §6.2).

Il filo di tutti questi test: l'impronta deve cambiare **quando cambia il
bando**, e non quando cambia la pagina. Un contatore di visite o un «aggiornato
il» che muove l'impronta significa una classificazione LLM a vuoto per ogni
bando, a ogni giro.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest
from datetime import date

from tests.supporto import carica_modulo

impronte = carica_modulo("impronte")

OGGI = date(2026, 9, 23)

PAGINA = """
<html><body>
  <header><a href="/">Home</a></header>
  <nav class="main-menu"><a href="/bandi">Tutti i bandi</a></nav>
  <main>
    <h1>Avviso psicologia scolastica</h1>
    <p>Visualizzazioni: 1.234</p>
    <p>Le domande si presentano dal 22 ottobre al 1&deg; dicembre 2026, entro le ore 12:00.</p>
    <h2>Allegati</h2>
    <ul><li><a href="/doc/avviso.pdf?utm_source=newsletter">Avviso integrale</a></li></ul>
    <div class="sidebar-related"><a href="/altro/correlato.pdf">Bando correlato</a></div>
    <div class="bandi-correlati">
      <a href="/altro/secondo-correlato.pdf">Bando per la formazione docenti</a>
    </div>
  </main>
  <footer>Ultimo aggiornamento: 22/09/2026 10:33</footer>
</body></html>
"""


class Pulizia(unittest.TestCase):
    def test_via_i_tag_di_contorno_e_i_nodi_di_contorno(self):
        testo = impronte.testo_normalizzato(PAGINA)
        self.assertIn("Avviso psicologia scolastica", testo)
        self.assertNotIn("Tutti i bandi", testo)       # nav
        self.assertNotIn("Home", testo)                # header
        self.assertNotIn("Bando correlato", testo)     # nodo *related*
        self.assertNotIn("formazione docenti", testo)  # nodo *correlat*, dentro <main>
        self.assertNotIn("Ultimo aggiornamento", testo)

    def test_contatori_e_aggiornamenti_spariscono(self):
        self.assertEqual(impronte.ripulisci_testo("Visualizzazioni: 1.234"), "")
        self.assertEqual(impronte.ripulisci_testo("1.234 visite"), "")
        self.assertEqual(impronte.ripulisci_testo("Ultimo aggiornamento: 12/09/2026 10:33"), "")
        self.assertEqual(impronte.ripulisci_testo("Ultima modifica: 12 settembre 2026"), "")

    def test_un_orario_dentro_un_termine_non_si_tocca(self):
        # E' la scadenza: toglierlo significherebbe perdere `ora_scadenza`.
        self.assertEqual(
            impronte.ripulisci_testo("Domande entro le ore 12:00"),
            "Domande entro le ore 12:00",
        )
        self.assertEqual(
            impronte.ripulisci_testo("Sportello aperto 09:00 - 13:00"),
            "Sportello aperto",
        )

    def test_token_di_tracciamento_fuori_dal_testo(self):
        self.assertEqual(
            impronte.ripulisci_testo("Vedi https://x.it/a?utm_source=news&b=1"),
            "Vedi https://x.it/a&b=1",
        )


class Sezioni(unittest.TestCase):
    def test_titoli_h1_h4_e_link_per_sezione(self):
        sezioni = impronte.sezioni(PAGINA)
        self.assertEqual([s.titolo for s in sezioni],
                         ["Avviso psicologia scolastica", "Allegati"])
        self.assertEqual([s.livello for s in sezioni], [1, 2])
        self.assertIn("dal 22 ottobre al 1° dicembre 2026", sezioni[0].testo)
        self.assertEqual(sezioni[1].link, ("/doc/avviso.pdf?utm_source=newsletter",))

    def test_testo_senza_tag_diventa_paragrafi(self):
        sezioni = impronte.sezioni("Titolo del bando\nPrima riga\n\nAllegati\nAvviso integrale")
        self.assertEqual([s.titolo for s in sezioni], ["Titolo del bando", "Allegati"])


class Impronte(unittest.TestCase):
    def test_contatore_diverso_stessa_impronta(self):
        variante = PAGINA.replace("1.234", "9.876").replace("22/09/2026 10:33", "23/09/2026 08:01")
        self.assertEqual(impronte.impronta_contenuto(PAGINA), impronte.impronta_contenuto(variante))

    def test_data_diversa_impronta_diversa(self):
        variante = PAGINA.replace("1&deg; dicembre 2026", "15 gennaio 2027")
        self.assertNotEqual(impronte.impronta_contenuto(PAGINA), impronte.impronta_contenuto(variante))

    def test_impronta_dei_link_ignora_ordine_e_utm(self):
        a = impronte.impronta_link(["https://x.it/b.pdf", "https://x.it/a.pdf?utm_source=n"])
        b = impronte.impronta_link(["https://x.it/a.pdf", "https://x.it/b.pdf"])
        self.assertEqual(a, b)

    def test_un_bando_correlato_che_cambia_non_muove_l_impronta(self):
        # I «bandi correlati» cambiano ogni volta che l'ente pubblica un altro
        # bando: se entrassero nell'impronta, ogni pubblicazione altrui
        # costerebbe una classificazione LLM su questo bando.
        variante = PAGINA.replace("secondo-correlato.pdf", "terzo-correlato.pdf")
        variante = variante.replace("formazione docenti", "digitalizzazione")
        self.assertEqual(impronte.impronta_contenuto(PAGINA), impronte.impronta_contenuto(variante))

    def test_link_nuovo_cambia_impronta_contenuto(self):
        variante = PAGINA.replace(
            "</ul>", '<li><a href="/doc/modulo.docx">Modulo</a></li></ul>'
        )
        self.assertNotEqual(impronte.impronta_contenuto(PAGINA), impronte.impronta_contenuto(variante))

    def test_impronte_sezioni_per_titolo(self):
        mappa = impronte.impronte_sezioni(PAGINA)
        self.assertEqual(sorted(mappa), ["allegati", "avviso psicologia scolastica"])


class NormalizzaUrl(unittest.TestCase):
    """Gemello di `bando_normalizza_url(text)` della migrazione 02."""

    def test_forma_canonica(self):
        casi = {
            "HTTPS://WWW.Esempio.it:443/a/b/?utm_source=x&id=3#frag": "https://esempio.it/a/b?id=3",
            "https://esempio.it/a/": "https://esempio.it/a",
            "https://esempio.it/a?fbclid=1": "https://esempio.it/a",
            "  ": None,
            None: None,
        }
        for url, atteso in casi.items():
            self.assertEqual(impronte.normalizza_url(url), atteso, url)

    def test_lo_schema_non_si_unifica(self):
        # Due schemi diversi restano due URL diversi: l'uguaglianza di questa
        # stringa autorizza una fusione, e una fusione sbagliata non si disfa.
        self.assertNotEqual(
            impronte.normalizza_url("http://esempio.it/a"),
            impronte.normalizza_url("https://esempio.it/a"),
        )


class DiffSezioni(unittest.TestCase):
    PRIMA = "<main><h1>Bando</h1><p>Scadenza 30 settembre 2026.</p><p>Visite: 10</p></main>"

    def test_solo_contatore_e_rumore(self):
        dopo = self.PRIMA.replace("Visite: 10", "Visite: 4211")
        diff = impronte.diff_sezioni(self.PRIMA, dopo, oggi=OGGI)
        self.assertTrue(diff.vuoto)
        self.assertTrue(diff.rumore)

    def test_una_data_nuova_non_e_mai_rumore(self):
        dopo = "<main><h1>Bando</h1><p>Scadenza prorogata al 1 dicembre 2026.</p></main>"
        diff = impronte.diff_sezioni(self.PRIMA, dopo, oggi=OGGI)
        self.assertFalse(diff.rumore)
        self.assertTrue(diff.rilevante)
        self.assertEqual(diff.sezioni_cambiate, ("bando",))
        self.assertIn("Scadenza prorogata al 1 dicembre 2026.", diff.righe_aggiunte)

    def test_un_link_nuovo_non_e_mai_rumore(self):
        dopo = self.PRIMA.replace("</main>", '<p><a href="/g.pdf">Graduatoria</a></p></main>')
        diff = impronte.diff_sezioni(self.PRIMA, dopo, oggi=OGGI)
        self.assertFalse(diff.rumore)
        self.assertEqual(diff.link_aggiunti, ("/g.pdf",))

    def test_elenco_riordinato_e_rumore(self):
        prima = "<main><h2>Elenco</h2><ul><li>Alfa beta gamma delta</li><li>Epsilon zeta eta theta</li></ul></main>"
        dopo = "<main><h2>Elenco</h2><ul><li>Epsilon zeta eta theta</li><li>Alfa beta gamma delta</li></ul></main>"
        diff = impronte.diff_sezioni(prima, dopo, oggi=OGGI)
        self.assertTrue(diff.rumore)

    def test_data_di_oggi_e_rumore(self):
        prima = "<main><h2>Nota</h2><p>Pagina rivista il 22/09/2026 dal responsabile del procedimento unico</p></main>"
        dopo = "<main><h2>Nota</h2><p>Pagina rivista il 23/09/2026 dal responsabile del procedimento unico</p></main>"
        self.assertTrue(impronte.diff_sezioni(prima, dopo, oggi=OGGI).rumore)

    def test_una_data_passata_con_ruolo_non_e_rumore(self):
        # Rettifica retroattiva di un termine: le due righe differiscono solo
        # per delle cifre, ma la data ha ruolo «scadenza» e va guardata.
        prima = "<main><h2>Avviso</h2><p>Le domande si presentano entro il 10/09/2026 presso gli uffici comunali</p></main>"
        dopo = "<main><h2>Avviso</h2><p>Le domande si presentano entro il 12/09/2026 presso gli uffici comunali</p></main>"
        self.assertFalse(impronte.diff_sezioni(prima, dopo, oggi=OGGI).rumore)

    def test_una_data_futura_non_e_rumore_anche_senza_parole(self):
        prima = "<main><h2>Avviso</h2><p>Le domande si presentano il 10/12/2026 presso gli uffici comunali del capoluogo</p></main>"
        dopo = "<main><h2>Avviso</h2><p>Le domande si presentano il 18/12/2026 presso gli uffici comunali del capoluogo</p></main>"
        self.assertFalse(impronte.diff_sezioni(prima, dopo, oggi=OGGI).rumore)

    def test_taglio_a_6000_caratteri_ma_righe_intere(self):
        righe_prima = "".join(f"<p>Riga numero {i} del testo originale</p>" for i in range(400))
        righe_dopo = "".join(f"<p>Riga rifatta {i} del testo nuovo</p>" for i in range(400))
        diff = impronte.diff_sezioni(
            f"<main><h2>Corpo</h2>{righe_prima}</main>",
            f"<main><h2>Corpo</h2>{righe_dopo}</main>",
            oggi=OGGI,
        )
        self.assertTrue(diff.troncato)
        self.assertLessEqual(len(diff.testo), impronte.LIMITE_DIFF)
        # Le righe aggiunte si calcolano sul diff intero: il gate G2 confronta
        # la citazione con queste, e troncarle nasconderebbe la prova.
        self.assertEqual(len(diff.righe_aggiunte), 400)

    def test_sezione_nuova_e_sezione_sparita(self):
        dopo = self.PRIMA.replace("</main>", "<h2>FAQ</h2><p>Domande frequenti sul bando</p></main>")
        diff = impronte.diff_sezioni(self.PRIMA, dopo, oggi=OGGI)
        self.assertIn("faq", diff.sezioni_cambiate)
        contrario = impronte.diff_sezioni(dopo, self.PRIMA, oggi=OGGI)
        self.assertIn("faq", contrario.sezioni_cambiate)


class SelezioneSezioni(unittest.TestCase):
    PAGINA = """
      <main>
        <h1>Avviso per la psicologia scolastica</h1>
        <p>Lead del bando con la sua presentazione.</p>
        <h2>Colophon</h2><p>Note redazionali senza alcun interesse per il bando.</p>
        <h2>Termini</h2><p>Domande dal 22 ottobre al 1 dicembre 2026.</p>
        <h2>Beneficiari</h2><p>Istituti scolastici statali e paritari.</p>
      </main>
    """

    def test_titolo_e_lead_ci_sono_sempre(self):
        scelto = impronte.seleziona_sezioni(self.PAGINA, budget=120)
        self.assertIn("Avviso per la psicologia scolastica", scelto)
        self.assertLessEqual(len(scelto), 120)

    def test_le_sezioni_con_date_battono_il_colophon(self):
        scelto = impronte.seleziona_sezioni(self.PAGINA, budget=190)
        self.assertIn("1 dicembre 2026", scelto)
        self.assertNotIn("Note redazionali", scelto)

    def test_ordine_del_documento_non_del_punteggio(self):
        scelto = impronte.seleziona_sezioni(self.PAGINA, budget=4000)
        self.assertLess(scelto.index("Termini"), scelto.index("Beneficiari"))

    def test_allegati_in_coda_e_budget_rispettato(self):
        scelto = impronte.seleziona_sezioni(
            self.PAGINA, budget=400,
            allegati=[{"label": "Avviso", "url": "https://x.it/a.pdf", "tipo": "pdf"}],
        )
        self.assertTrue(scelto.endswith("- Avviso [pdf] https://x.it/a.pdf"))
        self.assertLessEqual(len(scelto), 400)

    def test_budget_rispettato_con_molte_sezioni_corte(self):
        # Ogni giunzione costa due caratteri: con quattro sezioni lo sforamento
        # non si vede, con quaranta si'.
        pagina = (
            "<main><h1>Titolo del bando</h1><p>Lead di presentazione.</p>"
            + "".join(f"<h2>Sezione {n}</h2><p>Scadenza del lotto {n}.</p>" for n in range(40))
            + "</main>"
        )
        for budget in (200, 400, 800, 1600):
            self.assertLessEqual(
                len(impronte.seleziona_sezioni(pagina, budget=budget)), budget, budget
            )

    def test_testo_senza_struttura(self):
        blob = "parola " * 5000
        self.assertLessEqual(len(impronte.seleziona_sezioni(blob, budget=500)), 500)



class DiffTesti(unittest.TestCase):
    """Il diff del monitor confronta testo con testo e link con link.

    Fino al 29/09/2026 il monitor confrontava il `testo_norm` salvato (testo
    semplice, diviso per righe) con l'HTML nuovo (diviso per titoli): le
    sezioni non combaciavano mai, ogni cambio d'impronta rendeva «nuova» la
    pagina intera e tutti i suoi link risultavano «comparsi». Il G2 passava
    19 volte su 19, e tre atti di luglio sono usciti come «nuovo allegato».
    """

    PRIMA = ("Avviso pubblico formazione\n"
             "Le domande si presentano entro il 30 ottobre 2026.\n"
             "Download: 2166")

    def test_cambia_solo_il_contatore(self):
        dopo = self.PRIMA.replace("2166", "2171")
        diff = impronte.diff_testi(self.PRIMA, dopo, oggi=OGGI)
        self.assertEqual(diff.righe_aggiunte, ("Download: 2171",))
        self.assertEqual(diff.righe_rimosse, ("Download: 2166",))
        self.assertTrue(diff.rumore)
        self.assertFalse(diff.rilevante)

    def test_una_riga_in_cima_non_sposta_le_altre(self):
        dopo = "AGGIORNAMENTO: termine prorogato al 1 dicembre 2026.\n" + self.PRIMA
        diff = impronte.diff_testi(self.PRIMA, dopo, oggi=OGGI)
        self.assertEqual(diff.righe_aggiunte,
                         ("AGGIORNAMENTO: termine prorogato al 1 dicembre 2026.",))
        self.assertEqual(diff.righe_rimosse, ())
        self.assertTrue(diff.rilevante)

    def test_link_confrontati_con_quelli_salvati(self):
        diff = impronte.diff_testi(
            self.PRIMA, self.PRIMA, oggi=OGGI,
            link_prima=("https://ente.it/bando.pdf",),
            link_dopo=("https://ente.it/bando.pdf", "https://ente.it/graduatoria.pdf"))
        self.assertEqual(diff.link_aggiunti, ("https://ente.it/graduatoria.pdf",))
        self.assertTrue(diff.rilevante)

    def test_senza_link_salvati_nessun_link_e_nuovo(self):
        # Il primo giro dopo il deploy non ha un «prima» per i link: dichiararli
        # tutti comparsi era il difetto.
        diff = impronte.diff_testi(
            self.PRIMA, self.PRIMA, oggi=OGGI,
            link_prima=None, link_dopo=("https://ente.it/bando.pdf",))
        self.assertEqual(diff.link_aggiunti, ())
        self.assertTrue(diff.vuoto)

    def test_primo_controllo(self):
        diff = impronte.diff_testi(None, self.PRIMA, oggi=OGGI)
        self.assertEqual(len(diff.righe_aggiunte), 3)
        self.assertEqual(diff.link_aggiunti, ())

    def test_link_della_pagina_normalizzati_e_ordinati(self):
        html = ('<main><a href="https://ente.it/b.pdf?utm_source=x">B</a>'
                '<a href="https://ente.it/a.pdf">A</a><a href="https://ente.it/a.pdf">A</a></main>')
        self.assertEqual(impronte.link_pagina(html),
                         (impronte.normalizza_url("https://ente.it/a.pdf"),
                          impronte.normalizza_url("https://ente.it/b.pdf?utm_source=x")))
        self.assertEqual(impronte.link_pagina("solo testo"), ())

    def test_il_jsessionid_non_cambia_i_link(self):
        # Regione Umbria: la prima pagina servita senza cookie riscrive ogni
        # href con un jsessionid nuovo (revisione del 29/09/2026).
        con = '<main><a href="/bandi/dettaglio;jsessionid=A1B2C3?id=7">Bando</a></main>'
        senza = '<main><a href="/bandi/dettaglio?id=7">Bando</a></main>'
        altra = '<main><a href="/bandi/dettaglio;JSESSIONID=ZZ9?id=7">Bando</a></main>'
        self.assertEqual(impronte.link_pagina(con), impronte.link_pagina(senza))
        self.assertEqual(impronte.link_pagina(altra), impronte.link_pagina(senza))


    def test_una_riga_spostata_non_e_aggiunta(self):
        # Revisione del 29/09: una riga che cambia solo posto usciva fra le
        # «aggiunte» e faceva passare al G2 un documento vecchio.
        prima = "Avviso\nGraduatoria provvisoria approvata\nScadenza 30 ottobre 2026"
        dopo = "Graduatoria provvisoria approvata\nAvviso\nScadenza 30 ottobre 2026"
        diff = impronte.diff_testi(prima, dopo, oggi=OGGI)
        self.assertEqual(diff.righe_aggiunte, ())
        self.assertEqual(diff.righe_rimosse, ())
        self.assertFalse(diff.rilevante)

    def test_una_data_cambiata_senza_parole_chiave_non_e_rumore(self):
        # Il monitor decide su `rumore`: una scadenza spostata non ha «proroga»
        # nella riga, ma va al modello (bando 514869, 29/09).
        prima = "Avviso\nDomande entro il 5 ottobre 2026."
        dopo = "Avviso\nDomande entro il 30 ottobre 2026."
        diff = impronte.diff_testi(prima, dopo, oggi=OGGI)
        self.assertFalse(diff.rumore)

    def test_i_link_dentro_i_titoli_contano(self):
        html = '<main><h4><a href="https://ente.it/allegato-b.pdf">Allegato B</a></h4></main>'
        self.assertEqual(impronte.link_pagina(html),
                         (impronte.normalizza_url("https://ente.it/allegato-b.pdf"),))


class ContenutoMaiContorno(unittest.TestCase):
    """Pulizia v2 (30/09/2026): il contenuto non e' mai contorno.

    Fino alla v1 il 28 % delle pagine monitorate era cieco: `pulisci` toglieva
    il nodo che conteneva il bando (un `<main>` con la classe
    `sidebar-offcanvas`, il `<form>` di ASP.NET, i blocchi di Elementor) e il
    monitor confrontava ogni volta il solo `<title>`. Le pagine vere sono in
    `test_impronte_pagine_reali.py`; qui c'e' una regola per test.
    """

    def test_main_con_una_classe_di_contorno_resta(self):
        html = """<html><body>
          <nav class="menu"><a href="/">Tutti i bandi</a></nav>
          <main class="main-content col sidebar-offcanvas" role="main">
            <h1>Energie rinnovabili nelle imprese</h1>
            <p>Le domande entro il 30 ottobre 2026.</p>
            <div class="bandi-correlati"><a href="/altro.pdf">Altro bando</a></div>
          </main></body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Energie rinnovabili nelle imprese", testo)
        self.assertIn("Le domande entro il 30 ottobre 2026.", testo)
        # I discendenti si giudicano come prima.
        self.assertNotIn("Tutti i bandi", testo)
        self.assertNotIn("Altro bando", testo)

    def test_il_form_che_avvolge_la_pagina_resta(self):
        # ASP.NET WebForms (Valle d'Aosta): un solo <form> per tutta la pagina,
        # nessun <main>. L'ancora e' l'h1 del bando.
        html = """<html><body><form id="form1" method="post">
          <div id="main_menu"><a href="/regione">La Regione</a></div>
          <div id="contenuto"><h1>Intervento SRD03</h1>
            <p>Scadenza prorogata alle ore 23.59 del 30 ottobre 2026.</p></div>
        </form>
        <div id="testata"><form class="ricerca"><label>Cerca nel sito</label></form></div>
        </body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Intervento SRD03", testo)
        self.assertIn("prorogata alle ore 23.59 del 30 ottobre 2026", testo)
        self.assertNotIn("La Regione", testo)
        # Un form che non contiene il contenuto e' contorno come prima.
        self.assertNotIn("Cerca nel sito", testo)

    def test_un_header_che_contiene_il_main_resta(self):
        # HTML malformato: lxml puo' annidare il <main> dentro l'<header>.
        html = """<html><body><header class="testata">
          <nav><a href="/">Home</a></nav>
          <main><h1>Avviso</h1><p>Contributi alle imprese del territorio.</p></main>
        </header></body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Contributi alle imprese del territorio.", testo)
        self.assertNotIn("Home", testo)

    def test_il_logo_in_h1_non_protegge_l_header(self):
        html = """<html><body>
          <header><h1>Regione Esempio</h1><a href="/accedi">Accedi</a></header>
          <div class="contenuto"><h1>Avviso contributi</h1><p>Domande entro il 5 novembre.</p></div>
        </body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Avviso contributi", testo)
        self.assertNotIn("Accedi", testo)
        self.assertNotIn("Regione Esempio", testo)

    def test_con_il_main_l_h1_fuori_non_protegge(self):
        # Con un <main> le ancore sono solo quelle: un h1 dentro un riquadro
        # di contorno fuori dal main non lo salva.
        html = """<html><body>
          <div class="sidebar"><h1>Ultime notizie</h1><p>Notizia del giorno</p></div>
          <main><h2>Avviso</h2><p>Testo del bando.</p></main>
        </body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Testo del bando.", testo)
        self.assertNotIn("Notizia del giorno", testo)

    def test_elementor_il_blocco_del_testo_resta_i_menu_e_i_correlati_no(self):
        html = """<html><body><div class="elementor elementor-7749">
          <div class="elementor-widget elementor-widget-theme-post-title">
            <div class="elementor-widget-container"><h1>Avviso Mirabilia</h1></div></div>
          <div class="elementor-widget elementor-widget-theme-post-content">
            <div class="elementor-widget-container"><p>Contributi per il mercato estero.</p></div></div>
          <div class="elementor-widget elementor-widget-nav-menu"><a href="/camera">La Camera</a></div>
          <div class="elementor-widget elementor-widget-posts">
            <article><h3>Altra notizia</h3><a href="/altra">Leggi di piu'</a></article></div>
        </div></body></html>"""
        testo = impronte.testo_normalizzato(html)
        self.assertIn("Avviso Mirabilia", testo)
        self.assertIn("Contributi per il mercato estero.", testo)
        self.assertNotIn("La Camera", testo)
        self.assertNotIn("Altra notizia", testo)


class VersionePulizia(unittest.TestCase):
    def test_la_versione_corrente_e_la_2(self):
        # Da incrementare a ogni cambio di `pulisci` che sposta le impronte:
        # e' cio' che fa riallineare le righe al monitor invece di confrontarle.
        self.assertEqual(impronte.VERSIONE_PULIZIA, 2)

    def test_versione_salvata(self):
        chiave = impronte.CHIAVE_VERSIONE
        self.assertEqual(chiave, "__versione__")
        self.assertEqual(impronte.versione_pulizia({chiave: 2, "__link__": []}), 2)
        # Righe di prima del 30/09/2026: niente chiave, versione 1.
        self.assertEqual(impronte.versione_pulizia({"__link__": []}), 1)
        self.assertEqual(impronte.versione_pulizia(None), 1)
        self.assertEqual(impronte.versione_pulizia("non una mappa"), 1)
        self.assertEqual(impronte.versione_pulizia({chiave: "illeggibile"}), 1)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
