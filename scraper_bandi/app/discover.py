"""Fetch + parsing della pagina sorgente OpenCoesione.

Estrae i ~200 link organizzati in macro-blocchi:
  - Programmi Regionali (per ognuno: PR FESR, PR FSE+, ...)
  - Programmi Nazionali (PN ...)
  - Programmi CTE a Titolarità Italiana
  - Programmi CTE a Partecipazione Italiana

Ogni link estratto e' o di tipo "Opportunità" o "Preavviso" (testo del `<a>`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .classifier import (
    categoria_from_region_heading,
    categoria_from_section_header,
    normalize,
    tipo_link_from_anchor_text,
    tipologia_from_program_name,
)
from .logger import logger
from .settings import get_settings


@dataclass(frozen=True)
class FonteCandidate:
    """Una fonte candidata estratta dalla pagina OpenCoesione."""
    link: str
    categoria_programma_id: int | None
    tipologia_programma_id: int | None
    tipo_link: str  # 'Opportunità' | 'Preavviso'
    program_name: str | None    # debug: nome programma (es. 'PR FESR')
    section_name: str | None    # debug: nome sezione (es. 'ABRUZZO')


async def fetch_page() -> str:
    """GET la pagina sorgente. Ritorna l'HTML come stringa."""
    settings = get_settings()
    logger.info("[discover] GET {}", settings.opencoesione_url)
    async with httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": settings.http_user_agent},
        follow_redirects=True,
    ) as client:
        resp = await client.get(settings.opencoesione_url)
        resp.raise_for_status()
        logger.info(
            "[discover] HTML ricevuto: {} bytes status={}",
            len(resp.text), resp.status_code,
        )
        return resp.text


def _is_category_header(tag: Tag) -> int | None:
    """Se il tag e' un heading che identifica un macro-blocco
    `categoria_programma`, ritorna l'id. Altrimenti None."""
    if tag.name not in ("h1", "h2", "h3"):
        return None
    return categoria_from_section_header(tag.get_text(" ", strip=True))


def _iter_anchors_in_block(block: list[Tag]) -> Iterator[tuple[Tag, Tag | None, Tag | None]]:
    """Itera i `<a>` rilevanti dentro un macro-blocco (sequenza di tag tra
    due heading di categoria). Per ognuno ritorna (anchor, section_h3,
    parent_li). Filtra solo gli anchor con testo "Opportunità"/"Preavvisi"
    e href valido."""
    current_section: Tag | None = None
    for tag in block:
        # Aggiorna la sezione corrente quando incontriamo un h3 (regione/programma).
        if tag.name == "h3":
            current_section = tag
            continue

        # Cerca gli <a> dentro questo tag (o sue discendenze) con testo
        # "Opportunità"/"Preavvisi" e href presente.
        for a in tag.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            if tipo_link_from_anchor_text(text) is None:
                continue
            # Trova il <li> contenitore (per estrarre il nome del programma).
            li = a.find_parent("li")
            yield a, current_section, li


def _extract_program_name(li: Tag | None, anchor: Tag) -> str | None:
    """Estrae il nome del programma dal `<li>` (testo prima dei link)."""
    if li is None:
        return None
    # Cloniamo il testo del li rimuovendo il testo dei link figli,
    # cosi' resta il "nome programma" pulito (es. "PR FESR").
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, str):
            parts.append(child)
        elif getattr(child, "name", None) != "a":
            parts.append(child.get_text(" ", strip=True))
    name = " ".join(parts)
    name = " ".join(name.split())  # collapse whitespace
    return name or None


def parse_page(html: str, base_url: str | None = None) -> list[FonteCandidate]:
    """Estrae tutti i FonteCandidate dalla pagina indice OpenCoesione."""
    soup = BeautifulSoup(html, "lxml")
    if base_url is None:
        base_url = get_settings().opencoesione_url

    # Strategia di parsing:
    # 1. Scorri tutti i tag in body order.
    # 2. Quando incontri un heading di categoria, attiva quel blocco.
    # 3. Tutti gli <a> "Opportunità"/"Preavvisi" che vengono dopo (fino al
    #    prossimo heading di categoria) sono associati a quella categoria.
    body = soup.body or soup

    current_category: int | None = None
    candidates: list[FonteCandidate] = []
    seen: set[tuple[str, str]] = set()   # dedup per (link, tipo_link)

    # Raccoglie i top-level descendant in ordine DOM.
    # Usa find_all per riprodurre l'ordine naturale.
    all_tags = list(body.descendants)
    # Filtra solo i Tag (non NavigableString).
    all_tags = [t for t in all_tags if isinstance(t, Tag)]

    current_section_h3: Tag | None = None

    for tag in all_tags:
        # Cambio di macro-blocco
        new_category = _is_category_header(tag)
        if new_category is not None:
            current_category = new_category
            current_section_h3 = None
            logger.debug(
                "[discover] entro nel macro-blocco categoria_programma_id={} ({})",
                new_category, tag.get_text(" ", strip=True)[:80],
            )
            continue

        # Cambio di sezione (regione/programma) all'interno del macro-blocco
        if tag.name == "h3":
            current_section_h3 = tag
            continue

        # Cerca anchor rilevanti SOLO se siamo dentro un macro-blocco
        if current_category is None:
            continue

        # Considera SOLO i <a> diretti (non discendenti di tag gia' processati)
        if tag.name != "a":
            continue
        if not tag.has_attr("href"):
            continue

        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        tipo = tipo_link_from_anchor_text(text)
        if tipo is None:
            continue

        href = tag["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        # Risolvi URL relativi
        link = urljoin(base_url, href)

        dedup_key = (link, tipo)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Estrai nome programma dal `<li>` contenitore
        li = tag.find_parent("li")
        program_name = _extract_program_name(li, tag)

        # Sezione (regione/programma) per debug
        section_name = (
            current_section_h3.get_text(" ", strip=True)
            if current_section_h3 is not None else None
        )

        # Fallback categoria: se il macro-blocco non e' stato identificato
        # ma la sezione contiene un nome di regione -> Programma Regionale.
        categoria_id = current_category
        if categoria_id is None and section_name:
            categoria_id = categoria_from_region_heading(section_name)

        # Match tipologia dal nome del programma
        tipologia_id = (
            tipologia_from_program_name(program_name) if program_name else None
        )

        candidates.append(FonteCandidate(
            link=link,
            categoria_programma_id=categoria_id,
            tipologia_programma_id=tipologia_id,
            tipo_link=tipo,
            program_name=program_name,
            section_name=section_name,
        ))

    logger.info("[discover] estratti {} candidati distinti", len(candidates))

    # Breakdown diagnostico
    by_cat: dict[int | None, int] = {}
    by_tipo: dict[str, int] = {}
    unclassified_tipologia = 0
    for c in candidates:
        by_cat[c.categoria_programma_id] = by_cat.get(c.categoria_programma_id, 0) + 1
        by_tipo[c.tipo_link] = by_tipo.get(c.tipo_link, 0) + 1
        if c.tipologia_programma_id is None:
            unclassified_tipologia += 1
    logger.info("[discover] breakdown categoria_programma_id: {}", by_cat)
    logger.info("[discover] breakdown tipo_link: {}", by_tipo)
    if unclassified_tipologia:
        logger.warning(
            "[discover] {} candidati senza tipologia_programma matchata "
            "(programma_name non riconosciuto)",
            unclassified_tipologia,
        )

    return candidates
