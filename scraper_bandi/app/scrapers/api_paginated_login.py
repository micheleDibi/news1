"""Strategy `json_api_paginated_login`: variante di json_api_paginated con sessione autenticata.

Estende JsonApiPaginatedScraper override-andando solo `_make_session()` per
restituire una requests.Session ottenuta da un auth provider registrato
in `scrapers/auth/__init__.py`.

Parametri aggiuntivi rispetto a json_api_paginated:
  - auth_provider: nome registry (es. 'obiettivo_europa').
  - username, password: opzionali (default da settings).
"""
from __future__ import annotations

from typing import Any

from ..logger import logger
from .api_paginated import JsonApiPaginatedScraper


class JsonApiPaginatedLoginScraper(JsonApiPaginatedScraper):
    name = "json_api_paginated_login"

    def __init__(
        self,
        auth_provider: str,
        username: str | None = None,
        password: str | None = None,
        **kw: Any,
    ):
        super().__init__(**kw)
        self.auth_provider_name = auth_provider
        self._username_override = username
        self._password_override = password

    def _make_session(self):
        """Ritorna una session autenticata via auth provider registrato."""
        from .auth import get_auth_provider
        from ..settings import get_settings

        provider = get_auth_provider(self.auth_provider_name)
        settings = get_settings()

        # Credenziali: override esplicito > settings per provider noto
        username = self._username_override
        password = self._password_override
        if not username or not password:
            if self.auth_provider_name == "obiettivo_europa":
                username = settings.obiettivo_europa_username
                password = settings.obiettivo_europa_password

        if not username or not password:
            logger.warning(
                "[{}] credenziali mancanti per auth_provider={!r}; "
                "lo scraper userà una session non autenticata (dataset ridotto)",
                self.name, self.auth_provider_name,
            )
            # Fallback: session base non autenticata
            return super()._make_session()

        try:
            return provider(username, password)
        except Exception as e:
            logger.warning(
                "[{}] auth provider {!r} fallito ({}); fallback session non autenticata",
                self.name, self.auth_provider_name, e,
            )
            return super()._make_session()
