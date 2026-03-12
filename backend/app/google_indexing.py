"""Google Indexing API – notifica Google per pagine con JobPosting structured data."""

import os
import requests
from loguru import logger

try:
    from google.oauth2 import service_account
    _HAS_GOOGLE_AUTH = True
except ImportError:
    _HAS_GOOGLE_AUTH = False

SCOPES = ["https://www.googleapis.com/auth/indexing"]
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


def notify_google_indexing(urls: list[str], action: str = "URL_UPDATED") -> None:
    """Notifica la Google Indexing API per una lista di URL (fire-and-forget).

    Args:
        urls: Lista di URL da notificare.
        action: Tipo di notifica ("URL_UPDATED" o "URL_DELETED").
    """
    if not _HAS_GOOGLE_AUTH:
        logger.warning("[GoogleIndexing] google-auth non installato, skip")
        return

    creds_path = os.getenv("CREDENTIALS_GOOGLE_SPEECH", "google-credentials.json")
    if not os.path.exists(creds_path):
        logger.warning("[GoogleIndexing] Credenziali non trovate: {}", creds_path)
        return

    try:
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        credentials.refresh(_google_auth_request())
    except Exception as e:
        logger.warning("[GoogleIndexing] Errore caricamento credenziali: {}", e)
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credentials.token}",
    }

    for url in urls:
        try:
            resp = requests.post(ENDPOINT, json={"url": url, "type": action}, headers=headers)
            logger.info("[GoogleIndexing] {} → {} {}", url, resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("[GoogleIndexing] Errore per {}: {}", url, e)


def _google_auth_request():
    """Crea un google.auth.transport.requests.Request per il refresh del token."""
    from google.auth.transport.requests import Request
    return Request()
