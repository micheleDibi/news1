"""Pre-processing dei bandi via Claude Haiku 4.5.

Per ogni bando con stato_processing='scraped':
  1. Costruisce un payload con titolo + descrizione + URL + raw_data + contesto fonte.
  2. Chiama Claude Haiku con tool use per garantire JSON strutturato.
  3. Ritorna analisi {is_valid_bando, confidence_score, rejection_reason, stato_bando}.

L'aggiornamento DB e' fatto dall'orchestrator (bando_preprocess_runner).
"""
from __future__ import annotations

import asyncio
import json
import random
from functools import lru_cache
from typing import Any

from .logger import logger
from .settings import get_settings


# Tool schema: forza struttura JSON via tool use API.
ANALYZE_TOOL = {
    "name": "save_bando_analysis",
    "description": (
        "Salva il risultato dell'analisi del bando. "
        "Devi SEMPRE chiamare questo tool con la tua valutazione."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_valid_bando": {
                "type": "boolean",
                "description": (
                    "True se e' un vero bando/avviso/call per finanziamenti UE 2021-2027. "
                    "False se e' pagina indice/archivio/contenuto generico/link sbagliato/header tabella/titolo troppo generico."
                ),
            },
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidenza nella classificazione (0=incertissimo, 1=certissimo).",
            },
            "rejection_reason": {
                "type": ["string", "null"],
                "description": (
                    "Se is_valid_bando=false, motivo breve in italiano "
                    "(es. 'pagina indice', 'titolo generico', 'header tabella', "
                    "'link di navigazione', 'documento generico'). "
                    "null se is_valid_bando=true."
                ),
            },
            "stato_bando": {
                "type": "string",
                "enum": ["aperto", "chiuso", "in apertura prossimamente", "unknown"],
                "description": (
                    "Stato attuale del bando. "
                    "'aperto'=candidature aperte; "
                    "'chiuso'=scaduto/completato; "
                    "'in apertura prossimamente'=preavviso/pre-informativa; "
                    "'unknown'=impossibile determinare (penalizza confidence)."
                ),
            },
        },
        "required": ["is_valid_bando", "confidence_score", "stato_bando"],
    },
}


SYSTEM_PROMPT = """Sei un esperto di bandi pubblici italiani per finanziamenti UE 2021-2027 \
(FESR, FSE+, JTF, INTERREG). Il tuo compito e' validare ogni record candidato a "bando" \
estratto da portali istituzionali (regioni, ministeri, programmi CTE), eliminando i falsi positivi.

Sei AGGRESSIVO nel rifiutare:
- Pagine indice/archivio (titolo come "Bandi", "Avvisi", "Opportunita'", "Calendario", "Elenco")
- Header di tabella (titolo come "Avviso", "Oggetto", "Titolo", "Avviso pubblico")
- Link di navigazione (titolo come "Home", "Indietro", "Tutte le opportunita'", "Tutti i bandi")
- Documenti generici (manuali, guide, regolamenti SENZA call associata)
- Slug generici di sezione (es. "/bandi", "/opportunita-di-finanziamento", "/avvisi")
- Pagine di programma/asse SENZA call specifica
- Titoli troppo corti/generici (meno di 3 parole significative)

Accetti come VALIDO solo se identifichi inequivocabilmente un BANDO/AVVISO/CALL specifico \
con almeno UN segnale forte: nome del bando descrittivo, codice avviso, oggetto identificabile, \
beneficiari specifici, importo, scadenza, riferimento normativo (DGR/DDR/Decreto).

Stato bando:
- "aperto": il bando e' attivo, le candidature sono aperte
- "chiuso": il bando e' scaduto / completato / archiviato
- "in apertura prossimamente": preavviso / pre-informativa / call non ancora aperta
- "unknown": impossibile determinare (penalizza la confidence!)

INDIZI utili per stato:
- Se tipo fonte = "Preavviso" e raw_data ha 'data_pubblicazione_prevista' futura -> "in apertura prossimamente"
- Se tipo fonte = "Opportunita'" e link punta a /bandi-aperti/ -> probabilmente "aperto"
- Se descrizione contiene "scaduto", "chiuso", "archivio" -> "chiuso"
- Senza indizi precisi e con tipo "Opportunita'": tendenzialmente "aperto" (default ragionevole)

Confidenza:
- 0.9-1.0: certezza
- 0.7-0.9: alta confidenza con piccoli dubbi
- 0.5-0.7: media (segnali deboli)
- <0.5: incerto (usa per casi dubbi)
"""


def _truncate(text: str | None, max_chars: int) -> str:
    """Tronca a max_chars con ellipsi. None -> stringa vuota."""
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def _build_user_prompt(bando: dict[str, Any], fonte_ctx: dict[str, Any]) -> str:
    """Costruisce il user prompt per un singolo bando."""
    titolo = _truncate(bando.get("titolo_raw"), 500)
    descrizione = _truncate(bando.get("descrizione_raw"), 2000)

    raw_data = bando.get("raw_data") or {}
    raw_data_str = _truncate(
        json.dumps(raw_data, ensure_ascii=False, default=str) if raw_data else "",
        2000,
    )

    fonte_url = fonte_ctx.get("link") or ""
    tipo_link = bando.get("tipo_link") or fonte_ctx.get("tipo_link") or ""
    categoria = fonte_ctx.get("categoria_nome") or ""
    tipologia = fonte_ctx.get("tipologia_nome") or ""

    link_bando = bando.get("link_bando") or "(nessun link)"

    return f"""Analizza questo record candidato a bando:

CONTESTO FONTE
- URL fonte: {fonte_url}
- Tipo fonte: {tipo_link}  ("Opportunita'" = pagina di bandi aperti; "Preavviso" = calendario futuri)
- Programma: {tipologia}  (es. PR FESR Lombardia)
- Categoria: {categoria}  (Regionale / Nazionale / CTE)

RECORD ESTRATTO
- Titolo: {titolo or "(vuoto)"}
- Descrizione: {descrizione or "(vuoto)"}
- Link bando: {link_bando}
- raw_data: {raw_data_str or "(vuoto)"}

Chiama il tool `save_bando_analysis` con la tua valutazione."""


@lru_cache(maxsize=1)
def _get_anthropic_client():
    """Singleton client async Anthropic."""
    import anthropic
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY mancante in .env. Il pre-processor non puo' funzionare."
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _auto_reject(bando: dict[str, Any]) -> dict[str, Any] | None:
    """Pre-filter Python: se il bando ha contenuto trascurabile, salta il LLM
    e ritorna direttamente un rejection. Risparmio chiamate API."""
    titolo = (bando.get("titolo_raw") or "").strip()
    raw_data = bando.get("raw_data") or {}
    link = (bando.get("link_bando") or "").strip()

    # Vuoto totale
    if not titolo and not raw_data and not link:
        return {
            "is_valid_bando": False,
            "confidence_score": 1.0,
            "rejection_reason": "record vuoto (no titolo, no link, no metadati)",
            "stato_bando": "unknown",
        }
    # Titolo troppo corto e nessun altro segnale
    if titolo and len(titolo) < 5 and not link and not raw_data:
        return {
            "is_valid_bando": False,
            "confidence_score": 0.95,
            "rejection_reason": f"titolo troppo breve: {titolo!r}",
            "stato_bando": "unknown",
        }
    return None


async def _call_anthropic_with_retry(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str,
    max_retries: int = 3,
) -> Any:
    """Chiama l'API con retry exponential su rate limit / server errors."""
    import anthropic
    delay_base = 2.0
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[ANALYZE_TOOL],
                tool_choice={"type": "tool", "name": "save_bando_analysis"},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            last_err = e
            # Su 4xx non-429 non ha senso ritentare
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[preprocess] API status {} non retryabile: {}", status, e)
                raise
            sleep_s = (delay_base ** attempt) + random.uniform(0, 0.5)
            logger.warning(
                "[preprocess] retry attempt {}/{} dopo errore {}: sleep {:.1f}s",
                attempt + 1, max_retries, type(e).__name__, sleep_s,
            )
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Anthropic API: max_retries esauriti. Ultimo errore: {last_err}")


def _extract_tool_input(response: Any) -> dict[str, Any]:
    """Estrae l'argomento del tool call dal response Anthropic."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "save_bando_analysis":
            return dict(block.input)
    raise RuntimeError(
        f"Tool call save_bando_analysis non trovato nel response. "
        f"Blocks: {[getattr(b, 'type', None) for b in response.content]}"
    )


def _validate_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Validazione output LLM. Coerce + default su error."""
    is_valid = bool(analysis.get("is_valid_bando", False))
    try:
        conf = float(analysis.get("confidence_score", 0.0))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.0

    stato = analysis.get("stato_bando", "unknown")
    if stato not in ("aperto", "chiuso", "in apertura prossimamente", "unknown"):
        stato = "unknown"

    rej = analysis.get("rejection_reason")
    if is_valid:
        rej = None
    elif rej:
        rej = str(rej)[:500]

    return {
        "is_valid_bando": is_valid,
        "confidence_score": conf,
        "rejection_reason": rej,
        "stato_bando": stato,
    }


async def analyze_bando(
    bando: dict[str, Any],
    fonte_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Analizza un singolo bando via Claude Haiku 4.5.

    Args:
        bando: dict con id, titolo_raw, descrizione_raw, link_bando, raw_data, tipo_link.
        fonte_ctx: dict con link (URL fonte), tipo_link, categoria_nome, tipologia_nome.

    Returns:
        dict {is_valid_bando, confidence_score, rejection_reason, stato_bando}.
    """
    # Pre-filter difensivo
    auto = _auto_reject(bando)
    if auto is not None:
        logger.debug("[preprocess/{}] auto-reject: {}", bando.get("id"), auto["rejection_reason"])
        return auto

    settings = get_settings()
    client = _get_anthropic_client()
    user_prompt = _build_user_prompt(bando, fonte_ctx)

    response = await _call_anthropic_with_retry(
        client,
        model=settings.preprocess_model,
        max_tokens=settings.preprocess_max_tokens,
        system=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    raw_analysis = _extract_tool_input(response)
    analysis = _validate_analysis(raw_analysis)

    logger.debug(
        "[preprocess/{}] valid={} conf={:.2f} stato={} rej={!r}",
        bando.get("id"),
        analysis["is_valid_bando"],
        analysis["confidence_score"],
        analysis["stato_bando"],
        analysis.get("rejection_reason"),
    )
    return analysis
