"""Pipeline QualityGate — Controllo qualità a 4 livelli.

Ogni gate è una funzione pura (no dipendenze DB) che restituisce un dataclass frozen.
I risultati vengono salvati nel payload e poi raccolti nel response_summary del scraping_log.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    r"(?:facebook|twitter|instagram|linkedin|youtube|tiktok)\.com",
    r"/privacy[\-_]?polic",
    r"/cookie[\-_]?polic",
    r"\blogin\b|\blogout\b|\bsignin\b|\bsignup\b",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

_VALID_STATI = frozenset({"aperto", "chiuso", "programmato"})

_TITLE_GENERIC_PATTERNS = [
    r"^avvisi?$",
    r"^bandi?$",
    r"^bandi e gare$",
    r"^bandi e opportunita$",
    r"^bandi e opportunità$",
    r"^gare$",
    r"^opportunita$",
    r"^opportunità$",
    r"^call$",
    r"^home$",
    r"^news$",
    r"^project gateway$",
    r"^ask us a question$",
    r"^apply for (?:the )?call$",
]

_TITLE_GENERIC_RE = re.compile("|".join(_TITLE_GENERIC_PATTERNS), re.IGNORECASE)
_TITLE_SPLIT_RE = re.compile(r"[\s|>»/_-]+")

# ---------------------------------------------------------------------------
# Gate 1 — Post-estrazione
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate1Result:
    """Risultato del Gate 1: qualità del testo estratto da HTML/PDF/OCR."""

    extraction_status: str           # "ok" | "low_quality"
    extraction_quality_score: int    # 0–100
    extraction_warnings: list[str] = field(default_factory=list)


def run_gate1(text: str) -> Gate1Result:
    """Gate 1: valuta la qualità del testo estratto da HTML/PDF/OCR.

    Check:
    - Testo non vuoto → EMPTY_TEXT
    - Lunghezza ≥ 50 caratteri → TEXT_TOO_SHORT
    - Rapporto alfabetico ≥ 40% → LOW_ALPHA_RATIO
    - Nessun pattern rumore → NOISE_PATTERN
    """
    if not text:
        return Gate1Result(
            extraction_status="low_quality",
            extraction_quality_score=0,
            extraction_warnings=["EMPTY_TEXT"],
        )

    warnings: list[str] = []
    score = 100

    if len(text) < 50:
        warnings.append("TEXT_TOO_SHORT")
        score -= 40

    alpha_chars = sum(1 for c in text if c.isalpha())
    alpha_ratio = alpha_chars / len(text)
    if alpha_ratio < 0.40:
        warnings.append("LOW_ALPHA_RATIO")
        score -= 30

    if _NOISE_RE.search(text):
        warnings.append("NOISE_PATTERN")
        score -= 20

    score = max(0, score)
    status = "ok" if not warnings else "low_quality"
    return Gate1Result(
        extraction_status=status,
        extraction_quality_score=score,
        extraction_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Gate 2 — Post-parsing (pre-AI)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate2Result:
    """Risultato del Gate 2: completezza e validità dei campi dopo il parsing."""

    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[str] = field(default_factory=list)
    ai_required: bool = False
    ai_targets: list[str] = field(default_factory=list)
    blocking_fields: list[str] = field(default_factory=list)


def run_gate2(payload: dict[str, Any]) -> Gate2Result:
    """Gate 2: controlla completezza e validità dei campi dopo parse_bando_fields.

    Campi bloccanti (blocca upsert se mancanti): titolo, link_bando, hash_bando.
    Campi target AI (mancanti/invalidi → accodati per completamento AI): descrizione,
    data_scadenza, importo_numerico, classificazione.
    """
    blocking: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    ai_targets: list[str] = []

    # Campi bloccanti obbligatori
    for mandatory in ("titolo", "link_bando", "hash_bando"):
        v = payload.get(mandatory)
        if not v or not str(v).strip():
            blocking.append(mandatory)

    # stato_bando: il parser applica fallback a "programmato", ma validiamo comunque
    stato = payload.get("stato_bando")
    if stato not in _VALID_STATI:
        invalid.append("stato_bando")

    # descrizione: almeno 30 caratteri → target AI
    descrizione = payload.get("descrizione")
    if not descrizione or len(str(descrizione).strip()) < 30:
        missing.append("descrizione")
        ai_targets.append("descrizione")

    # data_scadenza: assenza → target AI
    if payload.get("data_scadenza") is None:
        missing.append("data_scadenza")
        ai_targets.append("data_scadenza")

    # importo_numerico: se presente deve essere parsabile come Decimal
    importo_num = payload.get("importo_numerico")
    if importo_num is not None:
        try:
            Decimal(str(importo_num))
        except (InvalidOperation, ValueError):
            invalid.append("importo_numerico")
            ai_targets.append("importo_numerico")

    # classificazione: almeno programma_id o tipologia_bando_id
    has_classification = (
        payload.get("programma_id") is not None
        or payload.get("tipologia_bando_id") is not None
    )
    if not has_classification:
        missing.append("classificazione")
        for clf in ("programma_id", "tipologia_bando_id", "modalita_erogazione_id"):
            if payload.get(clf) is None:
                ai_targets.append(clf)

    ai_required = bool(missing or invalid)
    return Gate2Result(
        missing_fields=missing,
        invalid_fields=invalid,
        ai_required=ai_required,
        ai_targets=list(dict.fromkeys(ai_targets)),  # dedup mantenendo ordine
        blocking_fields=blocking,
    )


# ---------------------------------------------------------------------------
# Gate 3 — Post-AI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate3Result:
    """Risultato del Gate 3: analisi output AI applicato vs scartato."""

    ai_applied_fields: list[str] = field(default_factory=list)
    ai_rejected_fields: list[str] = field(default_factory=list)
    ai_reject_reasons: dict[str, str] = field(default_factory=dict)
    quality_delta: int = 0


def run_gate3(
    raw_ai_output: dict[str, Any],
    validated_output: dict[str, Any],
    gate2_result: Gate2Result | None = None,
) -> Gate3Result:
    """Gate 3: classifica i campi AI applicati vs scartati e calcola il quality_delta.

    quality_delta = numero di campi target di Gate 2 coperti dall'AI.
    """
    applied: list[str] = []
    rejected: list[str] = []
    reasons: dict[str, str] = {}

    for field_name, raw_value in (raw_ai_output or {}).items():
        if field_name in validated_output:
            applied.append(field_name)
        else:
            rejected.append(field_name)
            reasons[field_name] = "NULL_VALUE" if raw_value is None else "OUT_OF_DICTIONARY"

    gate2_targets = set(gate2_result.ai_targets) if gate2_result else set()
    quality_delta = sum(1 for f in applied if f in gate2_targets)

    return Gate3Result(
        ai_applied_fields=applied,
        ai_rejected_fields=rejected,
        ai_reject_reasons=reasons,
        quality_delta=quality_delta,
    )


# ---------------------------------------------------------------------------
# Gate 4 — Persistenza e audit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate4Result:
    """Risultato del Gate 4: pass/fail prima dell'upsert finale."""

    pass_gate: bool
    discard_reason: str | None = None


@dataclass(frozen=True)
class TitleGateResult:
    """Risultato del pre-gate titolo usato all'inizio del worker AI."""

    pass_gate: bool
    discard_reason: str | None = None
    score: int = 0
    warnings: list[str] = field(default_factory=list)
    rewritten_title: str | None = None
    rewrite_source: str | None = None


def run_title_gate(payload: dict[str, Any]) -> TitleGateResult:
    """Gate iniziale AI: controlla, e se serve riformula, il titolo prima della classificazione."""
    title = _normalize_text(payload.get("titolo"))
    descrizione = _normalize_text(payload.get("descrizione"))
    link_bando = _normalize_text(payload.get("link_bando"))
    raw_data_obj = _coerce_raw_data_obj(payload.get("raw_data") or payload.get("raw_data_obj"))
    snippet_candidates = [
        _normalize_text(raw_data_obj.get("page_content_snippet_300")),
        _normalize_text(raw_data_obj.get("pdf_text_snippet_300")),
        _normalize_text(raw_data_obj.get("page_pdf_text_snippet_300")),
        _normalize_text(raw_data_obj.get("page_content_snippet")),
        _normalize_text(raw_data_obj.get("pdf_text_snippet")),
        _normalize_text(raw_data_obj.get("page_pdf_text_snippet")),
    ]

    if not title:
        return TitleGateResult(False, "MISSING_TITLE", 0, ["EMPTY_TITLE"])

    warnings: list[str] = []
    score = 100
    lowered = title.lower()
    title_tokens = _token_set(title)
    signal_texts = [descrizione, link_bando, *snippet_candidates]
    signal_text = " ".join(text for text in signal_texts if text)
    signal_tokens = _token_set(signal_text) if signal_text else set()
    rewritten_title, rewrite_source, rewrite_score, rewrite_warnings = _rewrite_title_candidate(
        title=title,
        descrizione=descrizione,
        link_bando=link_bando,
        snippet_candidates=snippet_candidates,
        raw_data_obj=raw_data_obj,
    )

    if len(title) < 12:
        warnings.append("TITLE_TOO_SHORT")
        score -= 30

    if _TITLE_GENERIC_RE.match(lowered):
        warnings.append("GENERIC_TITLE")
        score -= 60

    if _NOISE_RE.search(title):
        warnings.append("TITLE_NOISE_PATTERN")
        score -= 25

    if not title_tokens:
        warnings.append("NO_TITLE_TOKENS")
        score -= 30

    if signal_text:
        overlap = title_tokens & signal_tokens
        if not overlap:
            warnings.append("NO_OVERLAP_WITH_CONTEXT")
            score -= 35
        elif len(overlap) == 1:
            warnings.append("WEAK_CONTEXT_OVERLAP")
            score -= 15
        else:
            score += min(10, len(overlap) * 3)

    if link_bando:
        slug_tokens = _token_set(link_bando)
        slug_overlap = title_tokens & slug_tokens
        if not slug_overlap:
            warnings.append("NO_OVERLAP_WITH_LINK")
            score -= 20
        elif len(slug_overlap) == 1:
            warnings.append("WEAK_LINK_OVERLAP")
            score -= 10
        else:
            score += min(10, len(slug_overlap) * 2)

    if descrizione and _is_title_like(descrizione) and title.lower() == descrizione.lower():
        warnings.append("TITLE_EQUALS_DESCRIPTION")
        score -= 10

    score = max(0, min(100, max(score, rewrite_score)))

    if rewritten_title and rewritten_title != title:
        warnings.extend(rewrite_warnings)
        return TitleGateResult(
            True,
            None,
            score,
            warnings,
            rewritten_title=rewritten_title,
            rewrite_source=rewrite_source,
        )

    if _TITLE_GENERIC_RE.match(lowered):
        reason = "TITLE_GATE_BLOCKED:" + ",".join(warnings or ["GENERIC_TITLE"])
        return TitleGateResult(False, reason, score, warnings, rewritten_title=rewritten_title, rewrite_source=rewrite_source)

    if score < 55:
        reason = "TITLE_GATE_BLOCKED:" + ",".join(warnings or ["LOW_SCORE"])
        return TitleGateResult(False, reason, score, warnings)

    return TitleGateResult(True, None, score, warnings, rewritten_title=title, rewrite_source="original")


def _coerce_raw_data_obj(value: Any) -> dict[str, Any]:
    """Normalizza raw_data in un dict anche quando arriva come JSON string o tipo inatteso."""
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    return {}


def run_gate4(
    payload: dict[str, Any],
    gate1: Gate1Result | None = None,
) -> Gate4Result:
    """Gate 4: ultima difesa prima dell'upsert. Blocca record non persistibili.

    Check:
    - Campi obbligatori: titolo, link_bando, hash_bando
    - extraction_quality_score ≥ 20 (se disponibile)
    """
    for mandatory in ("titolo", "link_bando", "hash_bando"):
        v = payload.get(mandatory)
        if not v or not str(v).strip():
            return Gate4Result(
                pass_gate=False,
                discard_reason=f"MISSING_MANDATORY_FIELD:{mandatory}",
            )

    if gate1 is not None and gate1.extraction_quality_score < 20:
        return Gate4Result(
            pass_gate=False,
            discard_reason=f"LOW_EXTRACTION_QUALITY:{gate1.extraction_quality_score}",
        )

    return Gate4Result(pass_gate=True, discard_reason=None)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _token_set(text: str | None) -> set[str]:
    lowered = _normalize_text(text).lower()
    return {token for token in re.findall(r"[a-z0-9àèéìòù]{3,}", lowered)}


def _is_title_like(text: str | None) -> bool:
    normalized = _normalize_text(text).lower()
    return bool(normalized) and len(normalized) <= 180


def _rewrite_title_candidate(
    *,
    title: str,
    descrizione: str,
    link_bando: str,
    snippet_candidates: list[str],
    raw_data_obj: dict[str, Any],
) -> tuple[str | None, str | None, int, list[str]]:
    candidates: list[tuple[int, str, str]] = []

    def _add_candidate(text: str | None, source: str, base_score: int = 0) -> None:
        normalized = _normalize_text(text)
        if not normalized:
            return
        cleaned = _cleanup_title_fragment(normalized)
        if not cleaned:
            return
        if _TITLE_GENERIC_RE.match(cleaned.lower()):
            return
        if len(cleaned) < 12:
            return
        fragment_tokens = _token_set(cleaned)
        descrizione_tokens = _token_set(descrizione)
        link_tokens = _token_set(link_bando)
        keyword_hits = sum(1 for keyword in ("avviso", "bando", "call", "voucher", "contribut", "finanzi", "opportunit", "incentiv", "agevolaz", "fondo", "misura") if keyword in cleaned.lower())
        overlap_descrizione = len(fragment_tokens & descrizione_tokens)
        overlap_link = len(fragment_tokens & link_tokens)
        if keyword_hits == 0 and overlap_descrizione == 0 and overlap_link == 0:
            return
        candidate_score = base_score + _score_title_candidate(cleaned, descrizione=descrizione, link_bando=link_bando, snippet_candidates=snippet_candidates)
        if candidate_score <= 0:
            return
        candidates.append((candidate_score, cleaned, source))

    _add_candidate(title, "original", base_score=0)
    _add_candidate(descrizione, "descrizione", base_score=8)
    _add_candidate(raw_data_obj.get("page_title"), "page_title", base_score=4)
    _add_candidate(raw_data_obj.get("candidate_title"), "candidate_title", base_score=3)
    _add_candidate(_slug_to_title(link_bando), "link_slug", base_score=1)
    for idx, snippet in enumerate(snippet_candidates):
        for fragment in _split_title_fragments(snippet):
            _add_candidate(fragment, f"snippet_{idx}", base_score=6)

    if not candidates:
        return None, None, 0, ["NO_TITLE_REWRITE_CANDIDATE"]

    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    best_score, best_title, best_source = candidates[0]

    warnings: list[str] = []
    if best_title != title:
        warnings.append("TITLE_REWRITTEN")
        warnings.append(f"TITLE_SOURCE_{best_source.upper()}")

    return best_title, best_source, best_score, warnings


def _split_title_fragments(text: str | None) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    fragments: list[str] = []
    for piece in re.split(r"[\n\r\t|]+|\s{2,}|\s+-\s+|\s+[>»]\s+", normalized):
        candidate = _cleanup_title_fragment(piece)
        if candidate:
            fragments.append(candidate)
    return fragments


def _cleanup_title_fragment(text: str) -> str | None:
    cleaned = " ".join(str(text).strip().split())
    cleaned = cleaned.strip(" |-:;.,")
    if not cleaned:
        return None
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip()
    return cleaned or None


def _score_title_candidate(
    text: str,
    *,
    descrizione: str,
    link_bando: str,
    snippet_candidates: list[str],
) -> int:
    lowered = text.lower()
    score = 0
    if any(keyword in lowered for keyword in ("avviso", "bando", "call", "voucher", "contribut", "finanzi", "opportunit", "incentiv", "agevolaz", "fondo", "misura")):
        score += 10
    if re.search(r"\b20\d{2}\b", lowered):
        score += 2
    if 15 <= len(text) <= 140:
        score += 3
    if descrizione and lowered in _normalize_text(descrizione).lower():
        score += 4
    if link_bando:
        slug_tokens = _token_set(link_bando)
        overlap = _token_set(text) & slug_tokens
        score += min(8, len(overlap) * 3)
    for snippet in snippet_candidates:
        if not snippet:
            continue
        snippet_tokens = _token_set(snippet)
        overlap = _token_set(text) & snippet_tokens
        score += min(10, len(overlap) * 2)
    if _TITLE_GENERIC_RE.match(lowered):
        score -= 60
    if _NOISE_RE.search(lowered):
        score -= 20
    return score


def _slug_to_title(link_bando: str | None) -> str | None:
    if not link_bando:
        return None
    parts = [part for part in re.split(r"[/?#&=]+", str(link_bando)) if part]
    if not parts:
        return None
    last_part = parts[-1]
    tokens = re.split(r"[-_\.]+", last_part)
    tokens = [token for token in tokens if token and not token.isdigit()]
    if not tokens:
        return None
    title = " ".join(token.capitalize() for token in tokens)
    return _cleanup_title_fragment(title)
