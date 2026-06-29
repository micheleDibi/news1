"""Strategy `json_api_paginated`: REST/Algolia/Solr-style con paginazione.

Pattern generico riusabile per:
  - Incentivi Gov IT (Solr: start/rows pagination, response.docs + response.numFound)
  - Obiettivo Europa senza login (REST: page param, results array + next cursor)
  - Algolia/altre API JSON paginated

Parametri:
  - api_url_template: stringa con placeholder (es. {start}, {page}).
  - pagination_type: 'solr_start' | 'page' | 'offset' | 'cursor'.
  - page_size: dimensione pagina (per solr_start/offset).
  - page_start: indice iniziale (default 1 per 'page', 0 per altri).
  - response_path: dotted path al payload nella risposta JSON (es. 'response.docs' per Solr, 'results' per REST).
  - total_field: dotted path al totale (es. 'response.numFound') (opzionale).
  - next_field: campo che contiene URL prossima pagina (per cursor pagination) (opzionale).
  - adapter: nome adapter (vedi `adapters/__init__.py`) per mapping record → BandoItem.
  - rate_limit_s: sleep tra request consecutive (default 0.3).
  - max_pages: anti-loop, limite massimo pagine (default 100).
  - duplicate_threshold: stop dopo N record consecutivi gia' in DB (early-stop).
    Default 20. Disabilita con None.
  - extra_params: dict di query string params aggiuntivi (opzionale).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..logger import logger
from .base import BandoItem, BandoScraper


def _get_nested(obj: Any, path: str) -> Any:
    """Naviga un dict via dotted path (es. 'response.docs')."""
    if not path:
        return obj
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


class JsonApiPaginatedScraper(BandoScraper):
    """Scraper generico per API JSON paginated.

    NB: usa `requests` (sync) sotto `asyncio.to_thread` per non bloccare l'event
    loop. Le API JSON sono normalmente veloci (200-500ms), nessun setup async
    necessario.
    """
    name = "json_api_paginated"

    def __init__(
        self,
        api_url_template: str,
        pagination_type: str,
        page_size: int | None,
        response_path: str,
        adapter: str,
        total_field: str | None = None,
        next_field: str | None = None,
        page_start: int = 1,
        rate_limit_s: float = 0.3,
        max_pages: int = 100,
        duplicate_threshold: int | None = 20,
        extra_params: dict[str, Any] | None = None,
        **kw: Any,
    ):
        self.api_url_template = api_url_template
        self.pagination_type = pagination_type
        self.page_size = page_size
        self.response_path = response_path
        self.adapter_name = adapter
        self.total_field = total_field
        self.next_field = next_field
        self.page_start = page_start
        self.rate_limit_s = rate_limit_s
        self.max_pages = max_pages
        self.duplicate_threshold = duplicate_threshold
        self.extra_params = extra_params or {}
        # Per default pagination_type=page parte da 1; solr_start/offset da 0.
        if pagination_type in ("solr_start", "offset") and page_start == 1:
            self.page_start = 0

    def _build_url(self, page_or_start: int) -> str:
        """Sostituisce il placeholder appropriato nel template."""
        if self.pagination_type == "page":
            return self.api_url_template.format(page=page_or_start)
        if self.pagination_type in ("solr_start", "offset"):
            # Per Solr: '{start}'; per offset generico: '{offset}'
            if "{start}" in self.api_url_template:
                return self.api_url_template.format(start=page_or_start)
            return self.api_url_template.format(offset=page_or_start)
        if self.pagination_type == "cursor":
            # Cursor: il template è solo l'URL iniziale, le pagine successive
            # arrivano dal next_field.
            return self.api_url_template
        raise ValueError(f"pagination_type sconosciuto: {self.pagination_type!r}")

    def _make_session(self):
        """Override-able: ritorna requests.Session per fare le call.
        Versione base usa una session non autenticata.
        """
        import requests
        from ..settings import get_settings
        settings = get_settings()
        s = requests.Session()
        s.headers.update({
            "User-Agent": settings.http_user_agent,
            "Accept": "application/json",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return s

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        """Itera le pagine via API e ritorna BandoItem aggregati."""
        from .adapters import get_adapter
        adapter_fn = get_adapter(self.adapter_name)
        fonte_id = int(fonte["id"])

        items: list[BandoItem] = []
        seen_links: set[str] = set()
        consecutive_dup = 0
        page_count = 0

        session = self._make_session()

        # Stato pagination
        if self.pagination_type == "cursor":
            next_url: str | None = self._build_url(0)
            counter = self.page_start
        else:
            next_url = None
            counter = self.page_start

        while page_count < self.max_pages:
            page_count += 1
            if self.pagination_type == "cursor":
                if not next_url:
                    break
                url = next_url
            else:
                url = self._build_url(counter)

            logger.info(
                "[{}] fonte_id={} page={} url={}",
                self.name, fonte_id, page_count, url[:120],
            )
            try:
                resp = await asyncio.to_thread(
                    lambda: session.get(url, params=self.extra_params, timeout=30)
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
                data = resp.json()
            except Exception as e:
                logger.warning("[{}] fonte_id={} page={} JSON parse error: {}",
                               self.name, fonte_id, page_count, e)
                break

            records = _get_nested(data, self.response_path) or []
            if not records:
                logger.info("[{}] fonte_id={} page={} no records, stop",
                            self.name, fonte_id, page_count)
                break

            page_new = 0
            page_dup = 0
            for rec in records:
                try:
                    item = adapter_fn(rec, fonte_id)
                except Exception as e:
                    logger.debug("[{}] adapter error on record: {}", self.name, e)
                    continue
                if item is None:
                    continue
                # Dedup intra-pagina (link)
                if item.link_bando and item.link_bando in seen_links:
                    page_dup += 1
                    continue
                if item.link_bando:
                    seen_links.add(item.link_bando)
                items.append(item)
                page_new += 1

            logger.info(
                "[{}] fonte_id={} page={} records={} new={} dup={}",
                self.name, fonte_id, page_count, len(records), page_new, page_dup,
            )

            # Early-stop heuristic: se TUTTA la pagina e' duplicati intra-batch
            if self.duplicate_threshold is not None and page_new == 0 and page_dup > 0:
                consecutive_dup += page_dup
                if consecutive_dup >= self.duplicate_threshold:
                    logger.info("[{}] fonte_id={} early-stop su {} duplicati",
                                self.name, fonte_id, consecutive_dup)
                    break
            else:
                consecutive_dup = 0

            # Pagination avanzamento
            if self.pagination_type == "cursor":
                next_url = _get_nested(data, self.next_field or "next") if self.next_field else None
                if not next_url:
                    break
            elif self.pagination_type == "page":
                counter += 1
            elif self.pagination_type in ("solr_start", "offset"):
                if self.page_size is None:
                    break
                counter += self.page_size
                # Check totale per stop preciso
                if self.total_field:
                    total = _get_nested(data, self.total_field)
                    if isinstance(total, int) and counter >= total:
                        break

            # Rate limit
            if self.rate_limit_s > 0:
                await asyncio.sleep(self.rate_limit_s)

        logger.info(
            "[{}] fonte_id={} DONE | pages={} items={}",
            self.name, fonte_id, page_count, len(items),
        )
        return items
