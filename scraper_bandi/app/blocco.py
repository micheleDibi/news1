"""Lock di esecuzione della pipeline bandi (piano §6.2, fix 8.a.13, §16.2 M14).

Oggi due giri sovrapposti (il cron delle 06:00 ancora vivo quando parte quello
delle 12:00, oppure una CLI lanciata a mano) lavorano sulle stesse righe: due
scarichi dello stesso host, due UPDATE sullo stesso bando, contatori doppi e
tetti che non tengono. Il lock e' una riga in `pipeline_lock(nome,
acquisito_at, scade_at, proprietario)` presa e rilasciata da due RPC
(`lock_acquisisci` / `lock_rilascia`, EXECUTE solo a `service_role`).

**Tre esiti, non due** (M14). Le migrazioni le applica il committente: finche'
la 04 non e' passata le RPC non esistono. Un lock «non disponibile» non deve
valere «occupato» (fermerebbe la pipeline per sempre) ne' passare inosservato:

  - `acquisito` — si procede, e si rilascia nel `finally`;
  - `occupato`  — un altro giro sta lavorando: lo step ritorna
    `{'status': 'ok', 'saltato_per_lock': True}` e la CLI esce con 3;
  - `assente`   — la RPC non c'e': si procede **senza** lock, con un warning.

Nessun `SystemExit` qui dentro: gli exit code vivono solo in `__main__.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .logger import logger

ACQUISITO = "acquisito"
OCCUPATO = "occupato"
ASSENTE = "assente"

RPC_ACQUISISCI = "lock_acquisisci"
RPC_RILASCIA = "lock_rilascia"

TTL_PREDEFINITO_S = 3 * 3600      # un giro lungo (scrape + seo) sta sotto le 3 h


@dataclass(frozen=True)
class Blocco:
    """Esito di `acquisisci`. `proseguire` dice se lo step puo' partire."""
    nome: str
    proprietario: str
    esito: str
    dettaglio: dict[str, Any] | None = None

    @property
    def proseguire(self) -> bool:
        """Si prosegue se il lock e' nostro o se il lock non esiste affatto."""
        return self.esito in (ACQUISITO, ASSENTE)

    @property
    def da_rilasciare(self) -> bool:
        return self.esito == ACQUISITO


def _chiama_rpc(nome: str, parametri: dict[str, Any], client: Any | None) -> Any:
    if client is None:
        from .db import get_supabase
        client = get_supabase()
    return client.rpc(nome, parametri).execute()


def _disponibile(nome_rpc: str, controllo: Any | None) -> bool:
    if controllo is None:
        from .db import controllo as predefinito
        controllo = predefinito
    try:
        return bool(controllo.rpc_disponibile(nome_rpc))
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[blocco] controllo RPC fallito, procedo senza lock: {}", e)
        return False


def _preso(risultato: Any) -> bool:
    """La RPC ritorna `true` se il lock e' stato preso.

    PostgREST incapsula il valore in `.data`, che puo' essere il booleano, una
    lista di righe o un dizionario: si accettano tutte le forme, perche' una
    lettura sbagliata qui farebbe girare due pipeline insieme.
    """
    dati = getattr(risultato, "data", risultato)
    if isinstance(dati, list):
        dati = dati[0] if dati else False
    if isinstance(dati, dict):
        for chiave in ("acquisito", "lock_acquisisci", "ok", "risultato"):
            if chiave in dati:
                dati = dati[chiave]
                break
    return bool(dati)


def acquisisci(
    nome: str,
    proprietario: str,
    ttl_s: int = TTL_PREDEFINITO_S,
    *,
    client: Any | None = None,
    controllo: Any | None = None,
    rpc: Callable[[str, dict[str, Any], Any], Any] = _chiama_rpc,
) -> Blocco:
    """Prova a prendere il lock `nome`. Non solleva mai."""
    if not _disponibile(RPC_ACQUISISCI, controllo):
        logger.warning(
            "[blocco] RPC {} assente (migrazione 04 non applicata): proseguo senza lock",
            RPC_ACQUISISCI,
        )
        return Blocco(nome, proprietario, ASSENTE)

    parametri = {"p_nome": nome, "p_proprietario": proprietario, "p_ttl_s": int(ttl_s)}
    try:
        risultato = rpc(RPC_ACQUISISCI, parametri, client)
    except Exception as e:
        # Un errore della RPC non e' «occupato»: e' «non so». Meglio proseguire
        # senza lock (comportamento di oggi) che fermare la pipeline al buio.
        logger.warning("[blocco] {} fallita, proseguo senza lock: {}", RPC_ACQUISISCI, e)
        return Blocco(nome, proprietario, ASSENTE, {"errore": str(e)})

    if _preso(risultato):
        logger.info("[blocco] lock {} acquisito da {} (ttl={}s)", nome, proprietario, ttl_s)
        return Blocco(nome, proprietario, ACQUISITO)
    logger.warning("[blocco] lock {} occupato: step saltato", nome)
    return Blocco(nome, proprietario, OCCUPATO)


def rilascia(
    blocco: Blocco,
    *,
    client: Any | None = None,
    rpc: Callable[[str, dict[str, Any], Any], Any] = _chiama_rpc,
) -> bool:
    """Rilascia un lock acquisito. Sui lock `assente`/`occupato` non fa nulla."""
    if not blocco.da_rilasciare:
        return False
    parametri = {"p_nome": blocco.nome, "p_proprietario": blocco.proprietario}
    try:
        rpc(RPC_RILASCIA, parametri, client)
    except Exception as e:
        # Il TTL fa da rete di sicurezza: un rilascio fallito scade da solo.
        logger.warning("[blocco] rilascio di {} fallito (scadra' da solo): {}", blocco.nome, e)
        return False
    logger.info("[blocco] lock {} rilasciato", blocco.nome)
    return True


def esito_saltato(blocco: Blocco) -> dict[str, Any]:
    """Il dizionario che lo step ritorna quando il lock e' occupato."""
    return {"status": "ok", "saltato_per_lock": True, "lock": blocco.nome}


__all__ = [
    "ACQUISITO", "ASSENTE", "Blocco", "OCCUPATO", "RPC_ACQUISISCI", "RPC_RILASCIA",
    "TTL_PREDEFINITO_S", "acquisisci", "esito_saltato", "rilascia",
]
