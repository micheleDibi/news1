# -*- coding: utf-8 -*-
"""Pulizia v2 su pagine vere (contratto interno di ottobre 2026, §4).

Il 29/09/2026 il 28 % delle pagine monitorate era «cieco»: `testo_norm` di tre
righe o meno, cioe' il solo `<title>`, e il monitor non poteva vedere nessun
cambiamento. La proroga del bando 455779 (Valle d'Aosta, al 30/10) e quella
del 1262082 (Piemonte) sono sfuggite cosi'. Su 611 pagine vere scaricate il
30/09 la v1 ne lasciava cieche 164, la v2 una (mase.gov.it: in Liferay il
testo sta in un frammento chiamato «breadcrumb-e-contenuto»).

Le fixture in `tests/fixtures/impronte/` sono le pagine pubbliche scaricate il
30/09/2026, con il corpo di `<script>`/`<style>`, gli attributi `data-*` e gli
spazi ripetuti tolti per il peso (il testo normalizzato resta identico,
verificato alla preparazione) e il nome del responsabile del procedimento
sostituito. Restano solo recapiti d'ufficio.

- `piemonte_2886.html`: `<main class="… sidebar-offcanvas">`, tutte le 147
  pagine di bandi.regione.piemonte.it;
- `vda_455779.html`: ASP.NET, un solo `<form>` avvolge la pagina e non c'e'
  `<main>`;
- `elementor_czkrvv_17553.html`: Elementor, ogni blocco e' un
  `elementor-widget-*`;
- `calabria_18089.html`: HTML malformato, lxml annida il contenuto dentro la
  sezione `rc-breadcrumb`. Limite noto: la colonna della «Descrizione tecnica»
  ha la classe `rc-menu-vertical-divider` e cade ancora per «menu» (3 pagine).

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_impronte_pagine_reali
"""
import unittest
from pathlib import Path
from urllib.parse import urljoin

from tests.supporto import carica_modulo

impronte = carica_modulo("impronte")
allegati = carica_modulo("allegati")

CARTELLA = Path(__file__).resolve().parent / "fixtures" / "impronte"

URL_PIEMONTE = ("https://bandi.regione.piemonte.it/contributi-finanziamenti/"
                "energie-rinnovabili-nelle-imprese-2026")


def _pagina(nome: str) -> str:
    return (CARTELLA / nome).read_text(encoding="utf-8")


class PagineReali(unittest.TestCase):
    """Per ogni pagina: piu' di tre righe, il titolo del bando nel corpo (non
    solo nel `<title>`, che e' la prima riga), una frase del contenuto, e il
    contorno ancora fuori."""

    CASI = (
        (
            "piemonte_2886.html",
            "Energie rinnovabili nelle Imprese 2026",
            "Il Bando, rivolto alle imprese piemontesi, promuove esclusivamente la "
            "diffusione delle fonti rinnovabili.",
            ("Piazza Piemonte 1", "seguici su"),
        ),
        (
            "vda_455779.html",
            "Intervento SRD03 - Investimenti nelle aziende agricole per la "
            "diversificazione in attività non agricole",
            # La proroga che il monitor non ha visto (RIPRESA §4.4, A4).
            "la scadenza è stata prorogata alle ore 23.59 del 30 ottobre 2026",
            ("Amministrazione trasparente", "Posta certificata"),
        ),
        (
            "elementor_czkrvv_17553.html",
            "AVVISO PER SUPPORTO A INIZIATIVE PROMOZIONALI ATTIVATE DA ENTI DEL TERZO "
            "SETTORE E ALTRI SOGGETTI PRIVATI",
            "Determinazione del Segretario Generale n. 456 del 27/08/2026",
            # Il menu e l'elenco delle ultime notizie (`elementor-widget-posts`).
            ("Registro imprese", "Leggi di più"),
        ),
        (
            "calabria_18089.html",
            "AVVISO PUBBLICO per l'erogazione di contributi economici alle persone con "
            "alopecia da chemioterapia finalizzati all'acquisto di protesi tricologica "
            "annualità 2026",
            "Dipartimento per l’Inclusione sociale, la Sussidiarietà e il Welfare di Comunità",
            ("1522 Numero Antiviolenza", "ORGANI DI GOVERNO"),
        ),
    )

    def test_testo_normalizzato(self):
        for nome, titolo, frase, contorno in self.CASI:
            with self.subTest(pagina=nome):
                testo = impronte.testo_normalizzato(_pagina(nome))
                righe = testo.splitlines()
                self.assertGreater(len(righe), 3)
                self.assertIn(titolo, righe[1:])
                self.assertIn(frase, testo)
                for pezzo in contorno:
                    self.assertNotIn(pezzo, testo)

    def test_le_sezioni_vedono_il_contenuto(self):
        # `sezioni()` alimenta le impronte per sezione e il prompt SEO
        # (`seleziona_sezioni`): passa dalla stessa `pulisci`.
        for nome, titolo, _frase, _contorno in self.CASI:
            with self.subTest(pagina=nome):
                titoli = [s.titolo for s in impronte.sezioni(_pagina(nome))]
                self.assertIn(titolo, titoli)

    def test_i_link_della_pagina_non_vengono_dal_contorno(self):
        html = _pagina("piemonte_2886.html")
        link = set(impronte.link_pagina(html))
        self.assertTrue(link)
        self.assertFalse(link & _link_del_contorno(html))


class AllegatiPiemonte(unittest.TestCase):
    """`allegati.estrai` usa la stessa `pulisci`: con la v1 le pagine del
    Piemonte non davano nessun allegato, perche' il `<main>` spariva."""

    def test_allegati_estratti_e_nessuno_dal_contorno(self):
        html = _pagina("piemonte_2886.html")
        estrazione = allegati.estrai(
            html, URL_PIEMONTE, "Energie rinnovabili nelle Imprese 2026")
        self.assertGreater(len(estrazione.allegati), 0)
        del_contorno = _link_del_contorno(html)
        for allegato in estrazione.allegati:
            with self.subTest(url=allegato.url):
                self.assertNotIn(impronte.normalizza_url(allegato.url), del_contorno)
        self.assertIn(
            "Bando 2026 - Azione II.2ii.2 e Allegati",
            [a.forma()["label"] for a in estrazione.allegati],
        )


def _link_del_contorno(html: str) -> set[str]:
    """Gli href che stanno in header, nav, footer e aside della pagina grezza,
    normalizzati sia come scritti (`link_pagina`) sia assoluti (`allegati`)."""
    zuppa = impronte._zuppa(html)
    trovati: set[str] = set()
    for nodo in zuppa.find_all(("header", "nav", "footer", "aside")):
        for ancora in nodo.find_all("a"):
            href = (ancora.get("href") or "").strip()
            for forma in (href, urljoin(URL_PIEMONTE, href)):
                normalizzato = impronte.normalizza_url(forma)
                if normalizzato:
                    trovati.add(normalizzato)
    return trovati


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
