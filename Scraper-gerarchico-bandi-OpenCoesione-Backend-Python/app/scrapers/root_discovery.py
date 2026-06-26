from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


def _decode_httpx_html(response: httpx.Response) -> str:
    """Decodifica HTML da risposta httpx con charset dichiarata o fallback utf-8."""
    encoding = getattr(response, "charset_encoding", None) or "utf-8"
    try:
        return response.content.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return response.content.decode("utf-8", errors="replace")

from app.config.settings import settings


@dataclass(frozen=True)
class FonteLink:
    url: str
    label: str


@dataclass(frozen=True)
class DiscoveredFonte:
    link: str
    titolo: str
    categoria_programma_nome: str | None
    tipologia_programma_nome: str | None
    tipo_link: str
    formato_link: str
    contesto: str


class RootDiscoveryError(RuntimeError):
    pass


class RootDiscovery:
    def __init__(self, root_url: str | None = None, timeout_seconds: int | None = None) -> None:
        self.root_url = (root_url or settings.source_root_url).strip()
        self.timeout_seconds = timeout_seconds or settings.scraper_timeout_seconds
        parsed_root = urlparse(self.root_url)
        self._root_netloc = parsed_root.netloc
        self._root_path = parsed_root.path.rstrip("/")

    def fetch_root_html(self) -> str:
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.get(self.root_url)
                response.raise_for_status()
            return _decode_httpx_html(response)
        except httpx.HTTPError as exc:
            raise RootDiscoveryError(f"Errore nel recupero della root URL: {self.root_url}") from exc

    def discover_fonte_links(self, html: str) -> list[FonteLink]:
        soup = BeautifulSoup(html, "lxml")

        seen: set[str] = set()
        results: list[FonteLink] = []

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            try:
                absolute_url = urljoin(self.root_url, href)
                parsed = urlparse(absolute_url)
            except ValueError:
                # href con sintassi URL non valida (es. '[' non bilanciata): salta
                continue

            if parsed.scheme not in ("http", "https"):
                continue

            if not self._is_direct_child_link(parsed):
                continue

            normalized_url = parsed._replace(fragment="").geturl().rstrip("/")
            if not normalized_url or normalized_url in seen:
                continue

            label = " ".join(anchor.get_text(" ", strip=True).split())
            if not label:
                label = normalized_url

            seen.add(normalized_url)
            results.append(FonteLink(url=normalized_url, label=label))

        return results

    def discover_fonte_records(self, html: str) -> list[DiscoveredFonte]:
        soup = BeautifulSoup(html, "lxml")

        seen: set[str] = set()
        results: list[DiscoveredFonte] = []

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            try:
                absolute_url = urljoin(self.root_url, href)
                parsed = urlparse(absolute_url)
            except ValueError:
                # href con sintassi URL non valida (es. '[' non bilanciata): salta
                continue

            if parsed.scheme not in ("http", "https"):
                continue

            # Per link interni al dominio radice, accetta solo figli diretti
            # (evita link di navigazione del sito). I link su domini esterni
            # sono le fonti effettive (siti regionali/nazionali) e passano sempre.
            if parsed.netloc == self._root_netloc and not self._is_direct_child_link(parsed):
                continue

            normalized_url = parsed._replace(fragment="").geturl().rstrip("/")
            if not normalized_url or normalized_url in seen:
                continue

            # Evita link di navigazione ovvi e auto-link root.
            if normalized_url == self.root_url.rstrip("/"):
                continue
            if normalized_url.endswith("/en/opportunita_2021_2027"):
                continue

            label = " ".join(anchor.get_text(" ", strip=True).split())
            if not label:
                label = normalized_url

            context = self._extract_context(anchor)
            combined_text = f"{label} {context} {normalized_url}".strip()
            categoria = self._infer_categoria_programma(combined_text)
            tipologia = self._infer_tipologia_programma(combined_text)

            # Scarta link non riconducibili ai programmi obiettivo.
            if categoria is None and tipologia is None:
                continue

            results.append(
                DiscoveredFonte(
                    link=normalized_url,
                    titolo=label,
                    categoria_programma_nome=categoria,
                    tipologia_programma_nome=tipologia,
                    tipo_link=self._infer_tipo_link(combined_text),
                    formato_link=self._infer_formato_link(normalized_url),
                    contesto=context,
                )
            )
            seen.add(normalized_url)

        return results

    def _is_direct_child_link(self, parsed_url) -> bool:
        if parsed_url.netloc != self._root_netloc:
            return False

        candidate_path = (parsed_url.path or "").rstrip("/")
        if not candidate_path:
            return False

        if candidate_path == self._root_path:
            return False

        root_prefix = f"{self._root_path}/"
        if not candidate_path.startswith(root_prefix):
            return False

        suffix = candidate_path[len(root_prefix):].strip("/")
        if not suffix:
            return False

        # Fonte valida solo se figlio diretto della SOURCE_ROOT_URL.
        return "/" not in suffix

    def run(self) -> list[FonteLink]:
        html = self.fetch_root_html()
        return self.discover_fonte_links(html)

    def run_records(self) -> list[DiscoveredFonte]:
        html = self.fetch_root_html()
        return self.discover_fonte_records(html)

    @staticmethod
    def _extract_context(anchor) -> str:
        headings = anchor.find_all_previous(re.compile(r"^h[1-6]$"), limit=8)
        for heading in headings:
            text = " ".join(heading.get_text(" ", strip=True).split())
            if RootDiscovery._infer_categoria_programma(text) is not None:
                return text

        heading = anchor.find_previous(re.compile(r"^h[1-6]$"))
        if heading:
            text = " ".join(heading.get_text(" ", strip=True).split())
            if text:
                return text

        parent = anchor.find_parent(["li", "p", "div", "section"])
        if parent:
            text = " ".join(parent.get_text(" ", strip=True).split())
            return text[:240]
        return ""

    @staticmethod
    def _infer_tipo_link(text: str) -> str:
        lowered = text.lower()
        return "Preavviso" if "preavviso" in lowered else "Opportunità"

    @staticmethod
    def _infer_formato_link(url: str) -> str:
        lowered = url.lower()
        if lowered.endswith(".pdf"):
            return "PDF"
        if lowered.endswith(".csv"):
            return "CSV"
        if lowered.endswith(".zip"):
            return "ZIP"
        return "HTML"

    @staticmethod
    def _infer_categoria_programma(text: str) -> str | None:
        lowered = text.lower()
        if "partecipazione italiana" in lowered:
            return "Programma CTE a Partecipazione Italiana"
        if "titolarità italiana" in lowered or "titolarita italiana" in lowered:
            return "Programma CTE a Titolarità Italiana"
        if "programmi cte a partecipazione italiana" in lowered:
            return "Programma CTE a Partecipazione Italiana"
        if "programmi cte a titolarità italiana" in lowered or "programmi cte a titolarita italiana" in lowered:
            return "Programma CTE a Titolarità Italiana"
        if "nazionale" in lowered or lowered.startswith("pn ") or " pn " in lowered:
            return "Programma Nazionale"
        if "programmi nazionali" in lowered:
            return "Programma Nazionale"
        if "regionale" in lowered or "regionali" in lowered or lowered.startswith("pr ") or " pr " in lowered:
            return "Programma Regionale"

        tipologia = RootDiscovery._infer_tipologia_programma(text)
        if tipologia:
            if tipologia.startswith("PR "):
                return "Programma Regionale"
            if tipologia.startswith("PN "):
                return "Programma Nazionale"
        return None

    @staticmethod
    def _infer_tipologia_programma(text: str) -> str | None:
        lowered = text.lower()
        if "interreg ipa" in lowered or " ipa" in lowered:
            return "INTERREG IPA"
        if "interreg next" in lowered or " next" in lowered:
            return "INTERREG NEXT"
        if "interreg" in lowered:
            return "INTERREG FESR"
        if "just transition" in lowered or "jtf" in lowered:
            return "PN Just Transition Fund"
        if ("pn" in lowered) and ("fesr" in lowered) and ("fse" in lowered):
            return "PN FESR e FSE+"
        if ("pn" in lowered) and ("fesr" in lowered):
            return "PN FESR"
        if ("pn" in lowered) and ("fse" in lowered):
            return "PN FSE+"
        if ("pr" in lowered) and ("fesr" in lowered) and ("fse" in lowered):
            return "PR FESR e FSE+"
        if ("pr" in lowered) and ("fesr" in lowered):
            return "PR FESR"
        if ("pr" in lowered) and ("fse" in lowered):
            # In tabella il valore e' "PR FRE+".
            return "PR FRE+"
        return None



def extract_fonte_links_from_html(html: str, root_url: str | None = None) -> list[FonteLink]:
    """Helper testabile separatamente dalla rete."""
    return RootDiscovery(root_url=root_url).discover_fonte_links(html)


def unique_urls(links: Iterable[FonteLink]) -> list[str]:
    return [link.url for link in links]
