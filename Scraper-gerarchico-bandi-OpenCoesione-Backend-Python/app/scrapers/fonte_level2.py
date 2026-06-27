from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


from app.ai.quality_gate import run_gate1
from app.ocr.document_enrichment import enrich_from_pdf_links
from app.ocr.page_detail_fetcher import fetch_bando_detail_page
from app.config.settings import settings
from app.parsers.bando_parser import parse_bando_fields
from app.scrapers.firecrawl_client import get_firecrawl_client


@dataclass(frozen=True)
class BandoCandidate:
    fonte_id: int
    titolo: str
    link_bando: str
    hash_bando: str
    formato_fonte: str
    source_url: str
    raw_data_obj: dict[str, Any]


class FonteLevel2Error(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        recoverable: bool = True,
        http_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.http_status_code = http_status_code


class FonteLevel2Scanner:
    _HOST_SPECIFIC_DENY_EXACT_PATHS: dict[str, tuple[str, ...]] = {
        "interreg-marittimo.eu": (
            "/avvisi",
            "/progetti-finanziati1",
        ),
        "www.interreg-italiasvizzera.eu": (
            "/wps/portal/site/interreg-italia-svizzera/avvisi",
            "/wps/portal/site/interreg-italia-svizzera/progetti/progetti-finanziati",
        ),
        "www.interreg-central.eu": (
            "/calls-for-proposals",
            "/capitalisation-call-closed",
            "/third-call-results",
            "/second-call-results",
            "/project-gateway",
        ),
        # P3 — fonti con alta incidenza sospetti: pagine indice/lista/archivio non-bando
        "calabriaeuropa.regione.calabria.it": (
            "/bandi",  # lista filtrata; sito richiede cookie/JS → redirect a "Contatti"
        ),
        "www.lazioeuropa.it": (
            "/bandi",                                      # lista generale bandi
            "/psr-feasr/psr-bandi-e-graduatorie",          # archivio PSR 2014-2022 concluso
            "/psr-feasr/psr-cronoprogramma-bandi",         # cronoprogramma PSR 2014-2022 concluso
            "/pnrr-pnc/misure-pnrr-e-pnc-regione-lazio",  # indice misure PNRR (no bando singolo)
        ),
        "www.regione.sardegna.it": (
            "/atti-bandi-archivi",  # indice generale atti/bandi/archivi (non bando specifico)
        ),
    }

    _ALLOW_KEYWORDS = (
        "bando",
        "bandi",
        "avviso",
        "avvisi",
        "opportunit",
        "call",
        "voucher",
        "contribut",
        "finanzi",
        "incentiv",
        "manifestazione",
        "domanda",
        "graduatoria",
        "selezione",
        "invito",
        "agevolaz",
    )

    _DENY_KEYWORDS = (
        "privacy",
        "cookie",
        "accessibil",
        "note legali",
        "contatti",
        "call center",
        "numero verde",
        "regione utile",
        "direzioni-settori-regionali",
        "raccordo amministrativo",
        "facebook",
        "instagram",
        "linkedin",
        "twitter",
        "youtube",
        "whatsapp",
        "telegram",
        "feed",
        "rss",
        "wp-content",
        "wp-json",
        "wordpress.org",
        "login",
        "logout",
        "amministrazione trasparente",
        "mappa del sito",
        "newsletter",
        "lavora con noi",
    )

    _DENY_HOSTS = (
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "t.me",
        "wa.me",
    )

    _DENY_PATH_PARTS = (
        "/privacy",
        "/cookie",
        "/contatti",
        "/call-center",
        "/regione-utile",
        "/login",
        "/logout",
        "/rss",
        "/feed",
        "/tag/",
        "/tags/",
        "/categoria/",
        "/categorie/",
        "/category/",
        "/author/",
        # Pagine indice / ricerca / archivio che NON sono bandi singoli.
        # Inclusi per evitare slug tipo "regione-piemonte-ricerca-voucher" o
        # "bandi-finanziamenti-regione-piemonte-portale-ricerca" che superavano
        # il filtro di 2 segnali keyword.
        "/ricerca",
        "/search",
        "/cerca",
        "/portale",
        "/elenco-bandi",
        "/lista-bandi",
        "/archivio",
        "/archive",
        "/indice",
        "/filtra",
        "/filter/",
    )

    def __init__(self, timeout_seconds: int | None = None) -> None:
        self.timeout_seconds = timeout_seconds or settings.scraper_timeout_seconds

    def scan_fonte(self, fonte: Any) -> list[BandoCandidate]:
        fonte_format = (getattr(fonte, "formato_link", None) or "HTML").upper()
        source_url = str(getattr(fonte, "link", "") or "")
        fonte_id = int(getattr(fonte, "id"))

        if not source_url:
            return []

        if fonte_format == "CSV":
            return self._scan_csv(fonte_id, source_url, fonte_format)
        if fonte_format == "PDF":
            return self._scan_single_file(fonte_id, source_url, fonte_format)
        if fonte_format == "ZIP":
            return self._scan_single_file(fonte_id, source_url, fonte_format)
        return self._scan_html(fonte_id, source_url, fonte_format)

    def _scan_html(self, fonte_id: int, source_url: str, fonte_format: str) -> list[BandoCandidate]:
        # Firecrawl primario (stealth/auto), httpx hard-fallback. Vedi firecrawl_client.
        fetch = get_firecrawl_client().scrape(source_url)
        if not fetch.html:
            # Trasforma in FonteLevel2Error con stesso shape che il caller si aspetta.
            status_code = fetch.status_code
            recoverable = (
                status_code in {408, 425, 429} or (status_code is not None and status_code >= 500)
                or status_code is None  # timeout / errore di rete: ritentabile
            )
            raise FonteLevel2Error(
                f"Fetch fonte HTML fallita ({fetch.fetched_via}): {source_url} — {fetch.error}",
                recoverable=recoverable,
                http_status_code=status_code,
            )

        soup = BeautifulSoup(fetch.html, "lxml")
        candidates: list[BandoCandidate] = []
        seen: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            try:
                absolute = urljoin(source_url, href)
                parsed = urlparse(absolute)
            except ValueError:
                # URL malformato (es. '[' non bilanciata interpretata come IPv6): salta
                continue
            if parsed.scheme not in ("http", "https"):
                continue

            normalized = parsed._replace(fragment="").geturl().rstrip("/")
            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            title = " ".join(anchor.get_text(" ", strip=True).split()) or normalized
            parent_context = self._extract_anchor_context(anchor)
            if not self._is_probable_bando_link(title=title, url=normalized, context=parent_context):
                continue

            candidates.append(
                self._make_candidate(
                    fonte_id,
                    title,
                    normalized,
                    fonte_format,
                    source_url,
                    parent_context=parent_context or source_url,
                    fetched_via=fetch.fetched_via,
                )
            )

        return candidates

    def _scan_csv(self, fonte_id: int, source_url: str, fonte_format: str) -> list[BandoCandidate]:
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(source_url)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FonteLevel2Error(
                f"Timeout fetch fonte CSV: {source_url}",
                recoverable=True,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = int(exc.response.status_code)
            recoverable = status_code in {408, 425, 429} or status_code >= 500
            raise FonteLevel2Error(
                f"HTTP {status_code} fetch fonte CSV: {source_url}",
                recoverable=recoverable,
                http_status_code=status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise FonteLevel2Error(f"Errore fetch fonte CSV: {source_url}", recoverable=True) from exc

        text = response.text
        reader = csv.reader(io.StringIO(text))
        candidates: list[BandoCandidate] = []
        seen: set[str] = set()

        for row in reader:
            for cell in row:
                val = (cell or "").strip()
                if val.startswith("http://") or val.startswith("https://"):
                    try:
                        normalized = urlparse(val)._replace(fragment="").geturl().rstrip("/")
                    except ValueError:
                        # URL malformato nella cella CSV: salta
                        continue
                    if normalized and normalized not in seen:
                        if not self._is_probable_bando_link(title=normalized, url=normalized, context=source_url):
                            continue
                        seen.add(normalized)
                        candidates.append(
                            self._make_candidate(
                                fonte_id,
                                title=normalized,
                                link_bando=normalized,
                                fonte_format=fonte_format,
                                source_url=source_url,
                                parent_context=source_url,
                            )
                        )

        # fallback: se non troviamo URL nel CSV, trattiamo il CSV come fonte singola
        if not candidates:
            candidates.append(self._make_candidate(fonte_id, source_url, source_url, fonte_format, source_url, parent_context=source_url))

        return candidates

    def _scan_single_file(self, fonte_id: int, source_url: str, fonte_format: str) -> list[BandoCandidate]:
        return [self._make_candidate(fonte_id, source_url, source_url, fonte_format, source_url, parent_context=source_url)]

    @staticmethod
    def _build_hash(fonte_id: int, link_bando: str) -> str:
        payload = f"{fonte_id}|{link_bando}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _make_candidate(
        self,
        fonte_id: int,
        title: str,
        link_bando: str,
        fonte_format: str,
        source_url: str,
        parent_context: str,
        fetched_via: str | None = None,
    ) -> BandoCandidate:
        hash_bando = self._build_hash(fonte_id, link_bando)
        diagnostics = self._link_diagnostics(title=title, url=link_bando, context=parent_context)
        if fetched_via:
            diagnostics["fetched_via"] = fetched_via
        raw_obj = {
            "livello": "fonte_scan",
            "fonte_id": fonte_id,
            "fonte_formato": fonte_format,
            "source_url": source_url,
            "parent_context": parent_context,
            "candidate_title": title,
            "candidate_url": link_bando,
            "link_diagnostics": diagnostics,
        }
        return BandoCandidate(
            fonte_id=fonte_id,
            titolo=title[:4000],
            link_bando=link_bando,
            hash_bando=hash_bando,
            formato_fonte=fonte_format,
            source_url=source_url,
            raw_data_obj=raw_obj,
        )

    @staticmethod
    def _extract_anchor_context(anchor) -> str:
        parent = anchor.find_parent(["li", "article", "section", "div", "p"])
        if not parent:
            return ""
        text = " ".join(parent.get_text(" ", strip=True).split())
        return text[:240]

    @staticmethod
    def _is_probable_bando_link(title: str, url: str, context: str) -> bool:
        return FonteLevel2Scanner._link_diagnostics(title=title, url=url, context=context)["accepted"]

    @staticmethod
    def _link_diagnostics(title: str, url: str, context: str) -> dict[str, Any]:
        lowered_title = (title or "").lower()
        lowered_context = (context or "").lower()
        parsed = urlparse(url or "")
        lowered_host = (parsed.netloc or "").lower()
        lowered_path = (parsed.path or "").lower()
        lowered_path_normalized = lowered_path.rstrip("/") or "/"

        diagnostics: dict[str, Any] = {
            "accepted": False,
            "score": 0,
            "reason_accept": None,
            "reason_reject": None,
            "signals": {
                "title_has_allow": False,
                "path_has_allow": False,
                "context_has_allow": False,
            },
        }

        if any(lowered_host.endswith(host) for host in FonteLevel2Scanner._DENY_HOSTS):
            diagnostics["reason_reject"] = "DENY_HOST"
            return diagnostics

        if any(part in lowered_path for part in FonteLevel2Scanner._DENY_PATH_PARTS):
            diagnostics["reason_reject"] = "DENY_PATH"
            return diagnostics

        for host, denied_paths in FonteLevel2Scanner._HOST_SPECIFIC_DENY_EXACT_PATHS.items():
            if lowered_host.endswith(host) and any(lowered_path_normalized == path.rstrip("/") for path in denied_paths):
                diagnostics["reason_reject"] = "HOST_SPECIFIC_DENY_PATH"
                return diagnostics

        if "regione.piemonte.it" in lowered_host:
            # P1.1: blocca pagine istituzionali Piemonte che storicamente generano falsi positivi.
            if not lowered_path or lowered_path == "/":
                diagnostics["reason_reject"] = "ROOT_DOMAIN_NO_PATH"
                return diagnostics
            if any(
                part in lowered_path
                for part in (
                    "/web/amministrazione/",
                    "/web/temi/protezione-civile",
                    "/web/organizzazione/",
                    "/direzioni-settori-regionali/",
                )
            ):
                diagnostics["reason_reject"] = "PIEMONTE_INSTITUTIONAL_PATH"
                return diagnostics

        combined = f"{lowered_title} {lowered_host} {lowered_path} {lowered_context}"
        if any(k in combined for k in FonteLevel2Scanner._DENY_KEYWORDS):
            diagnostics["reason_reject"] = "DENY_KEYWORD"
            return diagnostics

        # Scarta file evidentemente non pertinenti alla pubblicazione del bando.
        if re.search(r"\.(?:jpg|jpeg|png|gif|svg|ico|css|js|xml)(?:\?|$)", lowered_path):
            diagnostics["reason_reject"] = "NON_HTML_OR_PDF"
            return diagnostics

        title_has_allow = any(k in lowered_title for k in FonteLevel2Scanner._ALLOW_KEYWORDS)
        path_has_allow = any(k in lowered_path for k in FonteLevel2Scanner._ALLOW_KEYWORDS)
        context_has_allow = any(k in lowered_context for k in FonteLevel2Scanner._ALLOW_KEYWORDS)
        diagnostics["signals"] = {
            "title_has_allow": title_has_allow,
            "path_has_allow": path_has_allow,
            "context_has_allow": context_has_allow,
        }

        # Richiede almeno due segnali indipendenti per ridurre i falsi positivi.
        signals = int(title_has_allow) + int(path_has_allow) + int(context_has_allow)
        diagnostics["score"] = signals
        if signals >= 2:
            diagnostics["accepted"] = True
            diagnostics["reason_accept"] = "MULTI_SIGNAL"
            return diagnostics

        # Eccezione: titolo forte + riferimento temporale tipico di pubblicazione.
        if title_has_allow and re.search(r"\b20\d{2}\b", lowered_title):
            diagnostics["accepted"] = True
            diagnostics["score"] = max(diagnostics["score"], 2)
            diagnostics["reason_accept"] = "TITLE_PLUS_YEAR"
            return diagnostics

        diagnostics["reason_reject"] = "INSUFFICIENT_SIGNALS"
        return diagnostics


def candidates_to_upsert_payload(candidates: list[BandoCandidate], scraping_log_id: int | None = None) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for c in candidates:
        # Arricchisci raw_data_obj con i dati della pagina di dettaglio
        page_detail = fetch_bando_detail_page(c.link_bando)

        # P4: enrichment documentale da PDF allegati della pagina dettaglio.
        pdf_links = page_detail.get("page_pdf_links") or []
        needs_pdf_enrichment = bool(pdf_links) and (
            not page_detail.get("page_importo")
            or not page_detail.get("page_dates")
            or not page_detail.get("page_description")
        )
        pdf_enrichment = enrich_from_pdf_links(pdf_links, max_pdfs=1) if needs_pdf_enrichment else {}

        enriched_raw_data = {**c.raw_data_obj, **page_detail, **pdf_enrichment}
        
        # Parsifica usando raw_data_obj arricchito
        parsed = parse_bando_fields(title=c.titolo, link_bando=c.link_bando, raw_data_obj=enriched_raw_data)
        
        # Gate 1 — qualità del testo estratto
        corpus = " ".join(filter(None, [
            c.titolo or "",
            c.link_bando or "",
            str(c.raw_data_obj.get("candidate_title") or ""),
            str(c.raw_data_obj.get("parent_context") or ""),
        ])).strip()
        gate1 = run_gate1(corpus)
        payload.append(
            {
                "fonte_id": c.fonte_id,
                "titolo": parsed.titolo,
                "descrizione": parsed.descrizione,
                "codice_bando": parsed.codice_bando,
                "stato_bando": parsed.stato_bando,
                "data_pubblicazione": parsed.data_pubblicazione,
                "data_apertura": parsed.data_apertura,
                "data_scadenza": parsed.data_scadenza,
                "link_bando": c.link_bando,
                "hash_bando": c.hash_bando,
                "importo": parsed.importo,
                "importo_numerico": parsed.importo_numerico,
                "data_extra": parsed.data_extra,
                "raw_data": json.dumps(enriched_raw_data, ensure_ascii=True),
                "raw_data_obj": enriched_raw_data,
                "scraping_log_id": scraping_log_id,
                "quality_gate1": gate1,
            }
        )
    return payload
