#!/usr/bin/env python3
"""Verifier adversarial per il payload della skill bandi-seo-enricher.

Pipeline v3 — defense in depth:
  fase 1 scraper (Python) → fase 2 skill (Opus 4.7) → fase 2.5 verifier (Haiku 4.5)

Il verifier riceve `(markdown_source, payload)` e con una chiamata Claude Haiku
controlla in modo avversariale che:
  - scadenza_quote sia substring letterale del markdown
  - data_pubblicazione_quote sia substring letterale del markdown
  - le date estratte siano coerenti (pub <= scad)
  - is_valid_bando rispetti negative markers N1-N4 (aggregator, calendario,
    programme landing)
  - ente_erogatore appaia nel markdown

Restituisce `{verdict: verified|refuted|skipped, refuted_fields: [...], notes: str}`.
La pipeline non si rompe in caso di errore: `verdict="skipped"` non blocca.

Costo per chiamata stimato: ~$0.0075 (Haiku 4.5: $1/MTok input, $5/MTok output).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

try:
    import anthropic  # type: ignore
except ImportError:  # pragma: no cover
    anthropic = None  # gestito a runtime nel call site

try:
    from loguru import logger as _logger  # type: ignore
except ImportError:  # pragma: no cover
    _logger = logging.getLogger("verifier_haiku")
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        _logger.addHandler(_h)
        _logger.setLevel(logging.INFO)


MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 400
MAX_MARKDOWN_CHARS = 20_000

VALID_VERDICTS = {"verified", "refuted", "skipped"}
KNOWN_REFUTED_FIELDS = {
    "scadenza", "data_pubblicazione",
    "is_valid_bando", "ente_erogatore", "consistency",
}


VERIFIER_SYSTEM_PROMPT = """Sei un verificatore avversariale rigoroso. La tua missione e' SMENTIRE per default e accettare solo con prove evidenti.

INPUT che ricevi:
  (1) MARKDOWN sorgente di una pagina di bando (max 20k char)
  (2) PAYLOAD strutturato emesso da un altro agente

VERIFICA, in ordine:

A. scadenza + scadenza_quote
   - Il `scadenza_quote` DEVE essere substring letterale del markdown (case-insensitive, normalizza whitespace). Se non lo trovi: refuted su "scadenza".
   - La data nel quote deve essere ragionevolmente equivalente a `scadenza`. Equivalenze ammesse:
       "30 settembre 2026" == "30/09/2026" == "30-09-2026" == "2026-09-30" == "Sept 30, 2026"
   - Se le date non coincidono → refuted su "scadenza".

B. data_pubblicazione + data_pubblicazione_quote
   - Stessi controlli di A su "data_pubblicazione".

C. Consistenza temporale (consistency)
   - Se entrambe presenti e scadenza < data_pubblicazione → refuted su "consistency".

D. is_valid_bando
   - Se la pagina ENUMERA piu' sub-call (>=3 link distinti a URL diversi con label tipo "Bando X", "Call Y", "Apply", "Opportunity Z") e is_valid_bando=true → refuted su "is_valid_bando".
   - Se il source_url contiene `calendario|preavvisi|cronoprogramma` (case-insensitive) e is_valid_bando=true → refuted su "is_valid_bando".
   - Se il source_url matcha regex `/call-\\d+-` MA il markdown NON contiene una label di scadenza ("Closing date", "Deadline", "Termine", "Scadenza") seguita da data parsabile, e is_valid_bando=true → refuted su "is_valid_bando".

E. ente_erogatore
   - Deve apparire letteralmente (substring case-insensitive) nel markdown. Se assente → refuted su "ente_erogatore".

OUTPUT:
Restituisci ESCLUSIVAMENTE un oggetto JSON, niente prosa fuori dal JSON, nessun fence markdown:
{
  "verdict": "verified" | "refuted",
  "refuted_fields": ["scadenza", "data_pubblicazione", "is_valid_bando", "ente_erogatore", "consistency"],
  "notes": "1-2 frasi che spiegano il perche' del verdetto"
}

Se non ci sono problemi: verdict="verified", refuted_fields=[], notes="OK".
"""


def _truncate(text: str, max_chars: int) -> str:
    if not isinstance(text, str):
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [TRUNCATED]"


def _build_user_message(markdown_source: str, payload: dict[str, Any]) -> str:
    """Costruisce il messaggio user con markdown + sottoinsieme rilevante del payload."""
    bando = payload.get("bando") or {}
    validation = payload.get("validation") or {}
    snippet = {
        "source_url": payload.get("source_url"),
        "scadenza": bando.get("scadenza"),
        "scadenza_source": bando.get("scadenza_source"),
        "scadenza_quote": bando.get("scadenza_quote"),
        "data_pubblicazione": bando.get("data_pubblicazione"),
        "data_pubblicazione_source": bando.get("data_pubblicazione_source"),
        "data_pubblicazione_quote": bando.get("data_pubblicazione_quote"),
        "ente_erogatore": bando.get("ente_erogatore"),
        "is_valid_bando": validation.get("is_valid_bando"),
        "rejection_category": validation.get("rejection_category"),
    }
    snippet_json = json.dumps(snippet, ensure_ascii=False, indent=2)
    md = _truncate(markdown_source or "", MAX_MARKDOWN_CHARS)
    return (
        "=== MARKDOWN SORGENTE ===\n"
        f"{md}\n\n"
        "=== PAYLOAD DA VERIFICARE ===\n"
        f"{snippet_json}\n\n"
        "Restituisci SOLO il JSON con verdict/refuted_fields/notes."
    )


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _parse_verdict_json(raw_text: str) -> dict[str, Any] | None:
    """Estrae il primo oggetto JSON valido dalla risposta del modello.

    Haiku occasionalmente avvolge il JSON in code-fence markdown nonostante il
    system prompt — preferiamo essere robusti che pignoli.
    """
    if not raw_text:
        return None
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(raw_text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _normalize_verdict(parsed: dict[str, Any]) -> dict[str, Any]:
    """Sanitizza il payload del verifier in un dict {verdict, refuted_fields, notes}."""
    verdict = parsed.get("verdict")
    if verdict not in VALID_VERDICTS:
        verdict = "refuted" if parsed.get("refuted_fields") else "verified"
    refuted_raw = parsed.get("refuted_fields") or []
    if not isinstance(refuted_raw, list):
        refuted_raw = []
    refuted_fields = [
        f for f in refuted_raw
        if isinstance(f, str) and f.strip() in KNOWN_REFUTED_FIELDS
    ]
    notes = parsed.get("notes")
    if not isinstance(notes, str):
        notes = ""
    return {
        "verdict": verdict,
        "refuted_fields": refuted_fields,
        "notes": notes[:1000],
    }


def _skipped(reason: str) -> dict[str, Any]:
    return {"verdict": "skipped", "refuted_fields": [], "notes": reason[:500]}


def verify_payload(markdown_source: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Verifica adversariale del payload skill via Claude Haiku 4.5.

    Restituisce sempre un dict con keys `verdict`, `refuted_fields`, `notes`.
    NON solleva eccezioni: ogni errore viene mappato a `verdict='skipped'` per
    non bloccare la pipeline. Il caller decide come trattare 'skipped' (di default,
    la RLS lo considera visibile come 'verified').
    """
    if anthropic is None:
        return _skipped("anthropic SDK non installato")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return _skipped("ANTHROPIC_API_KEY non configurata")
    if not isinstance(payload, dict) or not payload:
        return _skipped("payload vuoto o non-dict")
    if not isinstance(markdown_source, str) or not markdown_source.strip():
        return _skipped("markdown_source vuoto")

    user_msg = _build_user_message(markdown_source, payload)

    client = anthropic.Anthropic()
    attempts = 0
    last_err: Exception | None = None
    while attempts < 2:
        attempts += 1
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0,
                system=VERIFIER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            break
        except Exception as e:  # pragma: no cover (network)
            last_err = e
            _logger.warning("[VERIFIER] attempt {} failed: {}", attempts, e)
    else:
        return _skipped(f"anthropic call fallita: {last_err}")

    try:
        text_blocks = [
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", "") == "text"
        ]
        raw_text = "".join(text_blocks).strip()
    except Exception as e:  # pragma: no cover
        return _skipped(f"parse response fallito: {e}")

    parsed = _parse_verdict_json(raw_text)
    if parsed is None:
        return _skipped(f"verifier non ha emesso JSON valido: {raw_text[:200]}")

    return _normalize_verdict(parsed)


if __name__ == "__main__":  # smoke test manuale
    import sys
    if len(sys.argv) < 3:
        print("Uso: verifier_haiku.py <markdown_file> <payload_json_file>", file=sys.stderr)
        sys.exit(2)
    md = open(sys.argv[1], encoding="utf-8").read()
    pl = json.load(open(sys.argv[2], encoding="utf-8"))
    print(json.dumps(verify_payload(md, pl), ensure_ascii=False, indent=2))
