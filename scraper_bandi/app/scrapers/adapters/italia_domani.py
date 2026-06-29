"""Adapter: HTML Italia Domani PNRR → BandoItem.

Endpoint: https://www.italiadomani.gov.it/.../newnoticessearch.searchResults.html
Struttura HTML: div.item-wrapper × N per pagina.

Pattern observat dal repo esterno (srapingbandiitaliadomani/scraper.py):
  div.item-wrapper
    p.text.ellipsis             → descrizione (usato anche come titolo)
    div.col-lg-3 column p.text  → amministrazione_titolare
    div.col-lg-2 column p.text  → data_chiusura (data_scadenza)
    div.col-lg-2 column div.status-item.loading → stato
    a[href]                     → link
    div.col-12 column accordion
      div.col-lg-5
        div.info-time
          info-label / value:
            "data di apertura" → data_apertura
            "area geografica"  → area_geografica
            "tipologia"        → tipologia
            "destinatari"      → destinatari
      div.col-lg-7
        h5.item-title          → focus_pnrr
        single-info p          → descrizione_fondo_pnrr
"""
from __future__ import annotations

from typing import Any

from ..base import BandoItem


_BASE_URL = "https://www.italiadomani.gov.it"


def _text(el) -> str:
    return el.get_text(strip=True) if el else ""


def to_bando_item(row, fonte_id: int) -> BandoItem | None:
    """Converte un nodo HTML <div.item-wrapper> in BandoItem.

    `row` e' un BeautifulSoup Tag. Skip silenzioso se manca titolo.
    """
    # Titolo / descrizione: p.text.ellipsis
    desc_tag = row.find("p", class_="text ellipsis")
    titolo = _text(desc_tag)
    if not titolo:
        return None

    # Link
    link = None
    link_tag = row.find("a", href=True)
    if link_tag:
        href = (link_tag.get("href") or "").strip()
        if href:
            link = href if href.startswith("http") else f"{_BASE_URL}{href}"

    # ID dal markup
    row_id = row.get("id") or row.get("data-id")

    # Amministrazione titolare (col-lg-3)
    amm = None
    amm_col = row.find("div", class_="col-lg-3 column")
    if amm_col:
        amm_p = amm_col.find("p", class_="text ellipsis") or amm_col.find("p", class_="text")
        amm = _text(amm_p) or None

    # Stato + data_chiusura (entrambi in col-lg-2 columns)
    cols_l2 = row.find_all("div", class_="col-lg-2 column")
    data_chiusura = None
    stato = None
    for col in cols_l2:
        status_item = col.find("div", class_="status-item loading") or col.find("div", class_="status-item")
        if status_item and not stato:
            stato = _text(status_item) or None
            continue
        p = col.find("p", class_="text")
        if p and not data_chiusura:
            data_chiusura = _text(p) or None

    # Accordion: data_apertura, area_geografica, tipologia, destinatari, focus_pnrr
    data_apertura = None
    area_geografica = None
    tipologia = None
    destinatari = None
    focus_pnrr = None
    descrizione_fondo_pnrr = None

    accordion_col = row.find("div", class_="col-12 column")
    if accordion_col:
        accordion = accordion_col.find("div", class_="accordion accordion-investimenti acc-table") \
                    or accordion_col.find("div", class_="accordion")
        if accordion:
            item = accordion.find("div", class_="accordion-item")
            if item:
                collapse = item.find("div", class_="collapse show") or item.find("div", class_="collapse")
                if collapse:
                    card_body = collapse.find("div", class_="card-body")
                    if card_body:
                        row_div = card_body.find("div", class_="row")
                        if row_div:
                            # Colonna sinistra: info-time pairs
                            left = row_div.find("div", class_="col-lg-5")
                            if left:
                                for info in left.find_all("div", class_="info-time"):
                                    label_div = info.find("div", class_="info-label")
                                    value_div = info.find("div", class_="value")
                                    if not (label_div and value_div):
                                        continue
                                    label = _text(label_div).lower()
                                    value = _text(value_div)
                                    if not value:
                                        continue
                                    if "data di apertura" in label:
                                        data_apertura = value
                                    elif "area geografica" in label:
                                        area_geografica = value
                                    elif "tipologia" in label:
                                        tipologia = value
                                    elif "destinatari" in label:
                                        destinatari = value
                            # Colonna destra: focus PNRR
                            right = row_div.find("div", class_="col-lg-7 mt-4 mt-lg-0 button-col") \
                                    or row_div.find("div", class_="col-lg-7")
                            if right:
                                focus_item = right.find("div", class_="focus-item")
                                if focus_item:
                                    h5 = focus_item.find("h5", class_="item-title")
                                    focus_pnrr = _text(h5) or None
                                    info_content = focus_item.find("div", class_="focus-info-content")
                                    if info_content:
                                        single = info_content.find("div", class_="single-info")
                                        if single:
                                            p = single.find("p")
                                            descrizione_fondo_pnrr = _text(p) or None

    # raw_data: tutti i campi extra disponibili per l'enricher LLM.
    raw_data: dict[str, Any] = {
        "source": "italia_domani",
        "external_id": row_id,
        "amministrazione_titolare": amm,
        "data_apertura": data_apertura,
        "data_chiusura": data_chiusura,
        "stato": stato,
        "area_geografica": area_geografica,
        "tipologia": tipologia,
        "destinatari": destinatari,
        "focus_pnrr": focus_pnrr,
        "descrizione_fondo_pnrr": descrizione_fondo_pnrr,
        "pnrr": True,  # tutto il portale italiadomani e' PNRR
    }
    raw_data = {k: v for k, v in raw_data.items() if v not in (None, "", [], {})}

    return BandoItem(
        fonte_id=fonte_id,
        tipo_link="Opportunità",
        link_bando=link,
        titolo_raw=titolo,
        descrizione_raw=descrizione_fondo_pnrr,
        raw_data=raw_data,
    )
