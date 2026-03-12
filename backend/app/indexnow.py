"""
Modulo IndexNow per notificare i motori di ricerca di URL nuovi/aggiornati.
Usato dai pipeline interpelli e selezione personale.
"""

import os
import requests
from typing import List

from .logger import logger

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
SITE_HOST = "edunews24.it"
KEY_LOCATION = f"https://{SITE_HOST}/api/indexnow-key"


def submit_to_indexnow(urls: List[str]) -> None:
    """
    Invia una lista di URL a IndexNow.
    Fire-and-forget: logga errori ma non blocca mai il pipeline.
    """
    api_key = os.getenv("INDEXNOW_API_KEY")
    if not api_key:
        logger.warning("[IndexNow] INDEXNOW_API_KEY non configurata, skip notifica")
        return

    if not urls:
        return

    try:
        body = {
            "host": SITE_HOST,
            "key": api_key,
            "keyLocation": KEY_LOCATION,
            "urlList": urls,
        }
        resp = requests.post(
            INDEXNOW_ENDPOINT,
            json=body,
            timeout=10,
        )
        logger.info("[IndexNow] POST batch ({} URL) → {}", len(urls), resp.status_code)
    except Exception as e:
        logger.error("[IndexNow] Errore invio: {}", e)
