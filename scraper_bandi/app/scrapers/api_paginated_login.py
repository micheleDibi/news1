"""Strategy `json_api_paginated_login`: variante di json_api_paginated con sessione autenticata.

Estende JsonApiPaginatedScraper override-andando solo `_make_session()` per
restituire una requests.Session ottenuta da un auth provider registrato
in `scrapers/auth/__init__.py`.

Nessun ripiego sulla sessione anonima: se le credenziali mancano o il
provider fallisce, `_make_session()` solleva SessioneOEError e `scrape()`
fallisce per intero (il runner conta l'errore per la fonte). Con una sessione
anonima OE restituisce 5 record/pagina invece di 50 e il dataset sarebbe
silenziosamente ridotto.

Parametri aggiuntivi rispetto a json_api_paginated:
  - auth_provider: nome registry (es. 'obiettivo_europa').
  - username, password: opzionali (default da settings).
  - min_risultati_prima_pagina (ereditato): da impostare a 50 nel registro
    per OE, cosi' una prima pagina "anonima" fa fallire la fonte.
"""
from __future__ import annotations

from typing import Any

from ..logger import logger
from .api_paginated import JsonApiPaginatedScraper
from .auth.obiettivo_europa import Credenziali, SessioneOEError
from .base import BandoItem, esito

# Record per pagina dell'API di Obiettivo Europa con sessione autenticata. E'
# il numero con cui §6.1 scrive la regola di copertura («OE: pagine x 50 >=
# count»); il registro non lo dichiara perche' la paginazione e' a cursore e
# `page_size` non serve a costruire l'URL.
RISULTATI_PER_PAGINA = 50


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

    async def scrape(self, fonte: dict[str, Any]) -> list[BandoItem]:
        """Come la versione base, piu' la verifica di copertura di §6.1.

        La paginazione a cursore dice «non c'e' una pagina dopo», non «ho letto
        tutti i record»: fra dedup intra-pagina e una pagina corta per un
        guasto del server si puo' arrivare in fondo avendone visti la meta'.
        `count` e' il totale che l'API dichiara, e qui si confronta con le
        pagine lette. Se il conto non torna l'esito resta **troncato**, cosi'
        nessun «sparito dalla fonte» nasce da una lettura parziale — e su OE
        sarebbero centinaia di righe in un colpo solo.
        """
        items = await super().scrape(fonte)
        letto = dict(self.ultimo_esito)
        pagine = int(letto.get("pagine") or 0)
        count = int(letto.get("count") or 0)
        per_pagina = int(self.page_size or RISULTATI_PER_PAGINA)
        if not letto.get("troncato") and count > 0 and pagine * per_pagina < count:
            logger.warning(
                "[{}] fonte_id={} copertura parziale: {} pagine x {} < count={}",
                self.name, fonte.get("id"), pagine, per_pagina, count,
            )
            self.ultimo_esito = esito(pagine, troncato=True, count=count)
        return items

    def _make_session(self):
        """Ritorna una session autenticata via auth provider registrato.

        Raises:
            SessioneOEError (senza credenziali nel messaggio) se le
            credenziali mancano o il provider non riesce ad autenticarsi.
        """
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

        # Oggetto con repr opaco: da qui in poi username/password non
        # compaiono come nomi sulle righe che possono sollevare (loguru
        # `diagnose` stamperebbe i valori nel traceback).
        credenziali = Credenziali(username or "", password or "")
        if not credenziali:
            logger.error(
                "[ALLARME] login Obiettivo Europa fallito: credenziali mancanti per "
                "auth_provider={!r} (OBIETTIVO_EUROPA_USERNAME/PASSWORD); "
                "la fonte non viene processata",
                self.auth_provider_name,
            )
            raise SessioneOEError(
                f"credenziali mancanti per auth_provider={self.auth_provider_name!r}"
            )

        try:
            return provider(*credenziali)
        except Exception as e:
            logger.error(
                "[ALLARME] login Obiettivo Europa fallito (auth_provider={!r}): {}; "
                "la fonte non viene processata",
                self.auth_provider_name, e,
            )
            if isinstance(e, SessioneOEError):
                raise
            raise SessioneOEError(
                f"auth provider {self.auth_provider_name!r} fallito: {e}"
            ) from e

    def _errore_prima_pagina(self, n_risultati: int) -> Exception:
        """Con login, una prima pagina corta significa sessione anonima."""
        logger.error(
            "[ALLARME] login Obiettivo Europa fallito: la prima pagina restituisce "
            "{} risultati (attesi >= {}): sessione non autenticata; "
            "la fonte non viene processata",
            n_risultati, self.min_risultati_prima_pagina,
        )
        return SessioneOEError(
            f"prima pagina con {n_risultati} risultati "
            f"(attesi >= {self.min_risultati_prima_pagina}): sessione non autenticata"
        )
