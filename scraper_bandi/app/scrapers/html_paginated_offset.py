"""Strategy `html_paginated_offset`: HTML server-side con paginazione offset.

Pattern usato da Italia Domani: GET indice con `&resultsOffset={offset}` step
batch_size finche' la pagina ritorna meno risultati di batch_size o nessuno.

Per ogni pagina: parsing BeautifulSoup, dispatch all'adapter per ogni nodo
selezionato.

Parametri:
  - index_url_template: URL template con `{offset}`.
  - batch_size: dimensione step (es. 20).
  - item_selector: tuple (tag_name, attr_dict) per BS4 find_all (es. ('div', {'class': 'item-wrapper'})).
                   Se None, l'adapter riceve direttamente il `soup`.
  - adapter: nome registry adapter.
  - rate_limit_s: sleep tra pagine (default 1.0).
  - max_offset: anti-loop (default 2000).
  - duplicate_threshold: stop dopo N item duplicati consecutivi (default 5).
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..logger import logger
from .base import BandoItem, BandoScraper


class HtmlPaginatedOffsetScraper(BandoScraper):
    name = "html_paginated_offset"

    def __init__(
        self,
        index_url_template: str,
        batch_size: int,
        adapter: str,
        item_selector: tuple[str, dict] | None = None,
        item_selector_class: str | None = None,
        rate_limit_s: float = 1.0,
        max_offset: int = 2000,
        duplicate_threshold: int | None = 5,
        **kw: Any,
    ):
        self.index_url_template = index_url_template
        self.batch_size = batch_size
        self.adapter_name = adapter
        # Default selector per Italia Domani: div.item-wrapper
        self.item_selector = item_selector
        self.item_selector_class = item_selector_class or "item-wrapper"
        self.rate_limit_s = rate_limit_s
        self.max_offset = max_offset
        self.duplicate_threshold = duplicate_threshold

    def _make_session(self):
        import requests
        from ..settings import get_settings
        settings = get_settings()
        s = requests.Session()
        s.headers.update({
            "User-Agent": settings.http_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return s

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        from bs4 import BeautifulSoup
        from .adapters import get_adapter

        adapter_fn = get_adapter(self.adapter_name)
        fonte_id = int(fonte["id"])

        items: list[BandoItem] = []
        seen_titles: set[str] = set()
        consecutive_dup = 0
        offset = 0
        page_count = 0
        session = self._make_session()

        while offset <= self.max_offset:
            page_count += 1
            url = self.index_url_template.format(offset=offset)
            logger.info(
                "[{}] fonte_id={} page={} offset={} url={}",
                self.name, fonte_id, page_count, offset, url[:120],
            )
            try:
                resp = await asyncio.to_thread(
                    lambda: session.get(url, timeout=30)
                )
            except Exception as e:
                logger.warning("[{}] fonte_id={} page={} request error: {}",
                               self.name, fonte_id, page_count, e)
                break

            if resp.status_code != 200:
                logger.warning("[{}] fonte_id={} page={} HTTP {}",
                               self.name, fonte_id, page_count, resp.status_code)
                break

            try:
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                soup = BeautifulSoup(resp.text, "html.parser")

            # Trova nodi item-wrapper
            def _match_wrapper(tag):
                if tag.name != "div":
                    return False
                cls = tag.get("class") or []
                return self.item_selector_class in cls

            rows = soup.find_all(_match_wrapper)
            if not rows:
                logger.info("[{}] fonte_id={} page={} no items, stop",
                            self.name, fonte_id, page_count)
                break

            page_new = 0
            page_dup = 0
            for row in rows:
                try:
                    item = adapter_fn(row, fonte_id)
                except Exception as e:
                    logger.debug("[{}] adapter error: {}", self.name, e)
                    continue
                if item is None or not item.titolo_raw:
                    continue
                key = item.link_bando or item.titolo_raw
                if key in seen_titles:
                    page_dup += 1
                    continue
                seen_titles.add(key)
                items.append(item)
                page_new += 1

            logger.info(
                "[{}] fonte_id={} page={} rows={} new={} dup={}",
                self.name, fonte_id, page_count, len(rows), page_new, page_dup,
            )

            # Stop se pagina meno piena del batch
            if len(rows) < self.batch_size:
                logger.info("[{}] fonte_id={} fine dati (rows < batch_size)",
                            self.name, fonte_id)
                break

            # Early-stop duplicati
            if self.duplicate_threshold is not None and page_new == 0 and page_dup > 0:
                consecutive_dup += page_dup
                if consecutive_dup >= self.duplicate_threshold:
                    logger.info("[{}] fonte_id={} early-stop", self.name, fonte_id)
                    break
            else:
                consecutive_dup = 0

            offset += self.batch_size
            if self.rate_limit_s > 0:
                await asyncio.sleep(self.rate_limit_s)

        logger.info("[{}] fonte_id={} DONE | pages={} items={}",
                    self.name, fonte_id, page_count, len(items))
        return items
