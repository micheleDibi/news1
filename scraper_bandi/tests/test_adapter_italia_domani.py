# -*- coding: utf-8 -*-
"""Adapter Italia Domani (fix 8.a.17 b): scelta del link del bando.

Sul codice vecchio `row.find("a", href=True)` prendeva il primo <a> della
card, cioe' il toggle dell'accordion (`href="#collapse-1"`), e il link
finiva su `https://www.italiadomani.gov.it#collapse-1`.
"""
import unittest

from bs4 import BeautifulSoup

from tests.supporto import carica_modulo

italia_domani = carica_modulo("scrapers.adapters.italia_domani")


def card(anchors: str) -> object:
    """div.item-wrapper minimale con titolo e gli anchor passati."""
    html = f"""
    <div class="item-wrapper" id="notice-42">
      <p class="text ellipsis">Avviso pubblico per asili nido e scuole dell'infanzia</p>
      {anchors}
    </div>
    """
    return BeautifulSoup(html, "lxml").find("div", class_="item-wrapper")


class TestSceltaLink(unittest.TestCase):
    def test_preferisce_vai_al_bando_completo(self):
        row = card("""
          <a href="#collapse-1" data-toggle="collapse">Dettagli</a>
          <a href="javascript:void(0)">Apri</a>
          <a href="mailto:info@example.invalid">Scrivici</a>
          <a href="/it/altro/dettaglio.html">Scheda</a>
          <a class="btn" href="https://www.gazzettaufficiale.it/eli/id/2026/09/10/26A05123/sg">
            VAI AL BANDO COMPLETO
          </a>
        """)
        item = italia_domani.to_bando_item(row, fonte_id=450)
        self.assertEqual(
            item.link_bando,
            "https://www.gazzettaufficiale.it/eli/id/2026/09/10/26A05123/sg",
        )

    def test_vai_al_bando_completo_vince_anche_se_dopo_altri_link_validi(self):
        row = card("""
          <a href="/it/prima.html">Prima</a>
          <a href="https://www.invitalia.it/bando">Vai al bando completo</a>
        """)
        item = italia_domani.to_bando_item(row, fonte_id=450)
        self.assertEqual(item.link_bando, "https://www.invitalia.it/bando")

    def test_senza_bottone_primo_href_navigabile(self):
        row = card("""
          <a href="#collapse-1">Dettagli</a>
          <a href="  ">Vuoto</a>
          <a href="JAVASCRIPT:apri()">Apri</a>
          <a href="/it/investimenti/scheda.html">Scheda</a>
          <a href="https://www.mur.gov.it/x">Altro</a>
        """)
        item = italia_domani.to_bando_item(row, fonte_id=450)
        self.assertEqual(item.link_bando, "https://www.italiadomani.gov.it/it/investimenti/scheda.html")

    def test_solo_href_scartati_link_none(self):
        row = card("""
          <a href="#">Su</a>
          <a href="#collapse-1">Dettagli</a>
          <a href="javascript:void(0)">Apri</a>
          <a href="mailto:info@example.invalid">Scrivici</a>
        """)
        item = italia_domani.to_bando_item(row, fonte_id=450)
        self.assertIsNotNone(item)
        self.assertIsNone(item.link_bando)

    def test_resto_della_card_invariato(self):
        row = card('<a href="https://www.consip.it/b">Vai al bando completo</a>')
        item = italia_domani.to_bando_item(row, fonte_id=450)
        self.assertEqual(item.titolo_raw, "Avviso pubblico per asili nido e scuole dell'infanzia")
        self.assertEqual(item.tipo_link, "Opportunità")
        self.assertEqual(item.raw_data["external_id"], "notice-42")
        self.assertIs(item.raw_data["pnrr"], True)


if __name__ == "__main__":
    unittest.main()
