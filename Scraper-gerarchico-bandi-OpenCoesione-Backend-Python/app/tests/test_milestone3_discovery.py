"""
Test Milestone 3 — Discovery dinamica delle fonti.
"""
from __future__ import annotations

import uuid

import pytest

from app.config.settings import settings
from app.db.connection import get_db_connection
from app.repos.base import CategoriaProgrammaRepo, FonteRepo, TipologiaProgrammaRepo
from app.scrapers.root_discovery import RootDiscovery


def test_parsing_pagina_principale_estrazione_categorie_e_programmi():
    html = """
    <html><body>
      <h2>Programmi Regionali</h2>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-abruzzo">PR FESR Abruzzo</a>
      <h2>Programmi Nazionali</h2>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pn-fesr-cultura">PN FESR Cultura</a>
    </body></html>
    """

    rd = RootDiscovery(root_url=settings.source_root_url)
    rows = rd.discover_fonte_records(html)

    assert len(rows) == 2
    assert rows[0].categoria_programma_nome == "Programma Regionale"
    assert rows[0].tipologia_programma_nome == "PR FESR"
    assert rows[1].categoria_programma_nome == "Programma Nazionale"
    assert rows[1].tipologia_programma_nome == "PN FESR"


def test_riconoscimento_corretto_link_e_formato():
    html = """
    <html><body>
      <h2>Programmi Regionali</h2>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-documento.pdf">PR FESR Documento</a>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-dataset.csv">PR FESR Dataset</a>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-archivio.zip">PR FESR Archivio</a>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-preavviso">Preavviso PR FESR</a>
    </body></html>
    """

    rd = RootDiscovery(root_url=settings.source_root_url)
    rows = rd.discover_fonte_records(html)

    assert [r.formato_link for r in rows] == ["PDF", "CSV", "ZIP", "HTML"]
    assert rows[-1].tipo_link == "Preavviso"


def test_deduplicazione_fonti():
    html = """
    <html><body>
      <h2>Programmi Regionali</h2>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-abruzzo">PR FESR Abruzzo</a>
    <a href="https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-abruzzo#sezione">PR FESR Abruzzo dup</a>
    </body></html>
    """

    rd = RootDiscovery(root_url=settings.source_root_url)
    rows = rd.discover_fonte_records(html)

    assert len(rows) == 1
    assert rows[0].link == "https://opencoesione.gov.it/it/opportunita_2021_2027/pr-fesr-abruzzo"


def test_gestione_html_inattesa_non_fallisce():
    html = """
    <html><body>
      <div>Contenuto senza heading e senza pattern programma</div>
      <a href="javascript:void(0)">Link non valido</a>
      <a href="mailto:test@example.com">Mail</a>
    </body></html>
    """

    rd = RootDiscovery(root_url=settings.source_root_url)
    rows = rd.discover_fonte_records(html)

    assert rows == []


@pytest.mark.integration
def test_sync_update_fonti_esistenti():
    categoria_map = CategoriaProgrammaRepo().get_name_to_id_map()
    tipologia_map = TipologiaProgrammaRepo().get_name_to_id_map()

    categoria_id = categoria_map["Programma Regionale"]
    tipologia_id = tipologia_map["PR FESR"]

    unique_link = f"https://example.org/fonte-test-{uuid.uuid4()}"
    fonte_repo = FonteRepo()

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.fonte (
                        categoria_programma_id,
                        tipologia_programma_id,
                        tipo_link,
                        titolo,
                        link,
                        formato_link,
                        attivo,
                        note_aggiuntive
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        categoria_id,
                        tipologia_id,
                        "Opportunità",
                        "Titolo old",
                        unique_link,
                        "HTML",
                        True,
                        "old note",
                    ),
                )

        result = fonte_repo.sync_discovered_sources(
            [
                {
                    "link": unique_link,
                    "titolo": "Titolo new",
                    "categoria_programma_id": categoria_id,
                    "tipologia_programma_id": tipologia_id,
                    "tipo_link": "Preavviso",
                    "formato_link": "PDF",
                    "note_aggiuntive": "updated note",
                }
            ]
        )

        assert result["updated"] == 1
        assert result["inserted"] == 0

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT titolo, tipo_link, formato_link, note_aggiuntive
                    FROM public.fonte
                    WHERE link = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (unique_link,),
                )
                row = cur.fetchone()

        assert row["titolo"] == "Titolo new"
        assert row["tipo_link"] == "Preavviso"
        assert row["formato_link"] == "PDF"
    finally:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.fonte WHERE link = %s", (unique_link,))
