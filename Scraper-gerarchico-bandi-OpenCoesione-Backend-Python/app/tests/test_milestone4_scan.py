"""
Test Milestone 4 — Scraping secondo livello e identificazione bandi.
"""
from __future__ import annotations

import argparse
import json
import uuid

import pytest

from app.db.connection import get_db_connection, get_raw_connection
from app.scrapers.fonte_level2 import FonteLevel2Scanner, candidates_to_upsert_payload
from app.services.bando_discovery_service import BandoDiscoveryService


class DummyFonte:
    def __init__(self, fonte_id: int, link: str, formato_link: str = "HTML") -> None:
        self.id = fonte_id
        self.link = link
        self.formato_link = formato_link


class _FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.content = text.encode("utf-8")
        self.charset_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, mapping: dict[str, _FakeResponse], *args, **kwargs) -> None:
        self.mapping = mapping

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str):
        return self.mapping[url]


def test_identificazione_bandi_da_html(monkeypatch):
    html = """
    <html><body>
      <article><a href="https://example.org/bandi/avviso-1">Avviso pubblico imprese</a></article>
      <article><a href="https://example.org/privacy">Privacy policy</a></article>
            <article><a href="https://facebook.com/opencoesione">Seguici su Facebook</a></article>
      <article><a href="https://example.org/bandi/call-2">Call startup innovative</a></article>
    </body></html>
    """
    mapping = {
        "https://example.org/fonte-html": _FakeResponse(text=html),
    }

    import app.scrapers.fonte_level2 as level2_mod

    monkeypatch.setattr(level2_mod.httpx, "Client", lambda *args, **kwargs: _FakeClient(mapping, *args, **kwargs))

    scanner = FonteLevel2Scanner()
    fonte = DummyFonte(10, "https://example.org/fonte-html", "HTML")
    candidates = scanner.scan_fonte(fonte)

    assert len(candidates) == 2
    assert all("privacy" not in c.link_bando for c in candidates)
    assert all("facebook.com" not in c.link_bando for c in candidates)


def test_filtra_call_center_e_numero_verde(monkeypatch):
    html = """
    <html><body>
      <article><a href="https://www.regione.piemonte.it/web/amministrazione/regione-utile/call-center/800-333-444-numero-verde-regione-piemonte">Call Center Numero verde 800 333 444</a></article>
      <article><a href="https://example.org/bandi/avviso-1">Avviso contributi imprese</a></article>
    </body></html>
    """
    mapping = {
        "https://example.org/fonte-html": _FakeResponse(text=html),
    }

    import app.scrapers.fonte_level2 as level2_mod

    monkeypatch.setattr(level2_mod.httpx, "Client", lambda *args, **kwargs: _FakeClient(mapping, *args, **kwargs))

    scanner = FonteLevel2Scanner()
    fonte = DummyFonte(10, "https://example.org/fonte-html", "HTML")
    candidates = scanner.scan_fonte(fonte)

    assert len(candidates) == 1
    assert candidates[0].link_bando == "https://example.org/bandi/avviso-1"


def test_filtra_path_istituzionali_piemonte():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Finanziamenti regionali",
        url="https://www.regione.piemonte.it/web/temi/protezione-civile-difesa-suolo-opere-pubbliche/opere-pubbliche/finanziamenti-regionali",
        context="Contributi e bandi",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "PIEMONTE_INSTITUTIONAL_PATH"


def test_filtra_root_domain_portale_bandi_piemonte():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Contributi e finanziamenti , Gare d'appalto, Nomine",
        url="https://bandi.regione.piemonte.it",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "ROOT_DOMAIN_NO_PATH"


def test_filtra_interreg_marittimo_index_pages():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Interreg Marittimo-IT FR-Maritime",
        url="https://interreg-marittimo.eu/avvisi",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_interreg_central_result_pages():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Second call results",
        url="https://www.interreg-central.eu/second-call-results",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_interreg_italia_svizzera_progetti_finanziati_page():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Progetti finanziati",
        url="https://www.interreg-italiasvizzera.eu/wps/portal/site/interreg-italia-svizzera/progetti/progetti-finanziati",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_interreg_italia_svizzera_avvisi_page():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Avvisi",
        url="https://www.interreg-italiasvizzera.eu/wps/portal/site/interreg-italia-svizzera/avvisi",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_interreg_central_project_gateway_with_trailing_slash():
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Explore second call projects",
        url="https://www.interreg-central.eu/project-gateway/?&call=02",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


# --- P3: deny rules su fonti ad alta incidenza sospetti ---

def test_filtra_calabriaeuropa_bandi_lista():
    """Blocca /bandi (lista con filtri) per calabriaeuropa — fonte_id=3."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Bandi e Opportunità",
        url="https://calabriaeuropa.regione.calabria.it/bandi",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_calabriaeuropa_bandi_con_query_string():
    """Blocca /bandi/ con query string (URL fonte stessa) per calabriaeuropa — fonte_id=3."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="",
        url="https://calabriaeuropa.regione.calabria.it/bandi/?pr=&sort_order=ULTIMO+PUBBLICATO&filter_fund=PR+Calabria+FESR",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_lazioeuropa_bandi_lista():
    """Blocca /bandi (lista generale) per lazioeuropa — fonte_id=15."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Bandi",
        url="https://www.lazioeuropa.it/bandi",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_lazioeuropa_psr_bandi_graduatorie():
    """Blocca pagina archivio PSR 2014-2022 per lazioeuropa — fonte_id=15."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Bandi e graduatorie",
        url="https://www.lazioeuropa.it/psr-feasr/psr-bandi-e-graduatorie",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_lazioeuropa_pnrr_misure_indice():
    """Blocca pagina indice misure PNRR/PNC per lazioeuropa — fonte_id=15."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Misure PNRR e PNC Regione Lazio – Avvisi e Bandi",
        url="https://www.lazioeuropa.it/pnrr-pnc/misure-pnrr-e-pnc-regione-lazio",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_filtra_sardegna_atti_bandi_archivi():
    """Blocca /atti-bandi-archivi (indice generale) per regione.sardegna.it — fonti 27/28."""
    accepted = FonteLevel2Scanner._link_diagnostics(
        title="Atti, Bandi e Archivi",
        url="https://www.regione.sardegna.it/atti-bandi-archivi",
        context="",
    )
    assert accepted["accepted"] is False
    assert accepted["reason_reject"] == "HOST_SPECIFIC_DENY_PATH"


def test_identificazione_bandi_da_csv(monkeypatch):
    csv_text = (
        "id,url\n"
        "1,https://example.org/bandi/avviso-1\n"
        "2,https://facebook.com/opencoesione\n"
        "3,https://example.org/privacy\n"
        "4,https://example.org/bandi/avviso-2\n"
    )
    mapping = {
        "https://example.org/fonte.csv": _FakeResponse(text=csv_text),
    }

    import app.scrapers.fonte_level2 as level2_mod

    monkeypatch.setattr(level2_mod.httpx, "Client", lambda *args, **kwargs: _FakeClient(mapping, *args, **kwargs))

    scanner = FonteLevel2Scanner()
    fonte = DummyFonte(11, "https://example.org/fonte.csv", "CSV")
    candidates = scanner.scan_fonte(fonte)

    assert len(candidates) == 2
    assert all(c.formato_fonte == "CSV" for c in candidates)
    assert all("facebook.com" not in c.link_bando for c in candidates)
    assert all("privacy" not in c.link_bando for c in candidates)


def test_gestione_pdf_come_fonte_lista():
    scanner = FonteLevel2Scanner()
    fonte = DummyFonte(12, "https://example.org/fonte.pdf", "PDF")
    candidates = scanner.scan_fonte(fonte)

    assert len(candidates) == 1
    assert candidates[0].link_bando == "https://example.org/fonte.pdf"
    assert candidates[0].formato_fonte == "PDF"


def test_unicita_hash_bando():
    scanner = FonteLevel2Scanner()
    h1 = scanner._build_hash(100, "https://example.org/a")
    h2 = scanner._build_hash(100, "https://example.org/a")
    h3 = scanner._build_hash(101, "https://example.org/a")
    h4 = scanner._build_hash(100, "https://example.org/b")

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


@pytest.mark.integration
def test_log_corretto_dei_conteggi(monkeypatch):
    service = BandoDiscoveryService()

    unique_link = f"https://example.org/test-bando-{uuid.uuid4()}"

    # 1) limita fonti per test rapido
    monkeypatch.setattr(service.fonte_repo, "get_all_active_with_limit", lambda limit=None: [DummyFonte(1, "https://example.org/fonte-html", "HTML")])

    # 2) mock scanner con un candidato deterministico
    candidate = service.scanner._make_candidate(
        fonte_id=1,
        title="Avviso test",
        link_bando=unique_link,
        fonte_format="HTML",
        source_url="https://example.org/fonte-html",
        parent_context="https://example.org/fonte-html",
    )
    monkeypatch.setattr(service.scanner, "scan_fonte", lambda fonte: [candidate])

    # 3) esecuzione run
    result = service.run(limit=1)

    assert result["fonti_scansionate"] == 1
    assert result["bandi_identificati"] == 1
    assert result["processed"] == 1

    # 4) verifica log
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stato, bandi_trovati, bandi_nuovi, bandi_aggiornati, bandi_invariati, response_summary
                FROM public.scraping_log
                WHERE id = %s
                """,
                (result["scraping_log_id"],),
            )
            row = cur.fetchone()

    assert row["stato"] == "completed"
    assert row["bandi_trovati"] == 1
    assert row["bandi_nuovi"] + row["bandi_aggiornati"] + row["bandi_invariati"] == 1
    assert row["response_summary"] is not None

    # cleanup bando inserito dal test
    conn = get_raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.bando WHERE link_bando = %s", (unique_link,))
        conn.commit()
    finally:
        conn.close()
