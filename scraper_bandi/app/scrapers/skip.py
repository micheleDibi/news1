"""Strategy `skip_no_bandi`: no-op per fonti senza bandi (hub informativi,
404, redirect generici, ecc.). Ritorna lista vuota senza errore."""
from __future__ import annotations

from typing import Any

from ..logger import logger
from .base import BandoItem, BandoScraper


class SkipScraper(BandoScraper):
    name = "skip_no_bandi"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "pagina senza bandi"

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        logger.info(
            "[skip] fonte_id={} SKIP url={} reason={}",
            fonte.get("id"), fonte.get("link"), self.reason,
        )
        return []
