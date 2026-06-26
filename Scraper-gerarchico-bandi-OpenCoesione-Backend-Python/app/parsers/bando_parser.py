from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Any
from urllib.parse import urlparse


_MONTH_IT_TO_INT = {
    "gennaio": 1,
    "gen": 1,
    "febbraio": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "aprile": 4,
    "apr": 4,
    "maggio": 5,
    "mag": 5,
    "giugno": 6,
    "giu": 6,
    "luglio": 7,
    "lug": 7,
    "agosto": 8,
    "ago": 8,
    "settembre": 9,
    "set": 9,
    "ottobre": 10,
    "ott": 10,
    "novembre": 11,
    "nov": 11,
    "dicembre": 12,
    "dic": 12,
}

_MONTH_EN_TO_INT = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "december": 12,
    "dec": 12,
}

_MONTH_NAME_TO_INT: dict[str, int] = {**_MONTH_IT_TO_INT, **_MONTH_EN_TO_INT}

_DATE_TOKEN_PATTERN = (
    r"((?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)"
    r"|(?<!\d)\d{4}[./-]\d{1,2}[./-]\d{1,2}(?!\d)"
    r"|(?<!\d)\d{8}(?!\d)"
    r"|(?<!\d)\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|jun|jul|aug|sep|oct|dec|"
    r"gennaio|febbraio|marzo|aprile|maggio|giugno|"
    r"luglio|agosto|settembre|ottobre|novembre|dicembre|"
    r"gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\.?\s+\d{4}(?!\d))"
)

_ECONOMIC_CONTEXT_KEYWORDS = (
    "euro",
    "eur",
    "€",
    "importo",
    "dotazione",
    "finanziamento",
    "contribut",
    "budget",
    "grant",
    "funding",
    "fund",
    "fondo",
    "voucher",
    "allocation",
    "cofinanzi",
    "sovvenzione",
)

_TITLE_RELEVANT_KEYWORDS = (
    "bando",
    "avviso",
    "call",
    "proposal",
    "proposals",
    "project",
    "projects",
    "funding",
    "grant",
    "contribut",
    "finanzi",
    "opportunit",
    "voucher",
    "incentiv",
    "agevolaz",
    "misura",
    "startup",
    "imprese",
    "innovazione",
)

_TITLE_STOPWORDS = {
    "a",
    "al",
    "alla",
    "alle",
    "and",
    "avviso",
    "bando",
    "call",
    "con",
    "da",
    "del",
    "della",
    "delle",
    "di",
    "e",
    "for",
    "gli",
    "il",
    "in",
    "la",
    "le",
    "per",
    "projects",
    "project",
    "su",
    "the",
    "to",
    "un",
    "una",
}

_GENERIC_TITLE_PATTERNS = (
    r"^ask us a question$",
    r"^project gateway$",
    r"^next med$",
    r"^home$",
    r"^news$",
    r"^bandi$",
    r"^bandi e finanziamenti$",
    r"^bandi e opportunit(?:a|à)$",
    r"^avvisi(?: e bandi)?$",
    r"^contact(?: us|s)?$",
    r"^apply for (?:the )?call$",
    r"^calls? for proposals?$",
    r"^timeline of calls?$",
    r"^calls? for projects?$",
)

_NAVIGATION_NOISE_PATTERN = re.compile(
    r"\b(go to main menu|back main menu|go to search|skip to main content|content_types|main menu)\b",
    flags=re.IGNORECASE,
)


def _get_importo_plausibile_threshold() -> Decimal:
    """Legge la soglia importo plausibile da env/settings, con fallback conservativo."""
    raw = os.getenv("IMPORTO_PLAUSIBILE_THRESHOLD")
    if raw is not None and str(raw).strip():
        try:
            return max(Decimal(str(raw).strip()), Decimal("0"))
        except InvalidOperation:
            pass

    try:
        from app.config.settings import settings

        return max(Decimal(str(settings.importo_plausibile_threshold)), Decimal("0"))
    except Exception:
        return Decimal("1000")


@dataclass(frozen=True)
class ParsedBandoFields:
    titolo: str
    codice_bando: str | None
    descrizione: str | None
    stato_bando: str
    data_pubblicazione: date | None
    data_apertura: date | None
    data_scadenza: date | None
    importo: str | None
    importo_numerico: Decimal | None
    data_extra: dict[str, Any] | None


def parse_bando_fields(title: str, link_bando: str, raw_data_obj: dict[str, Any]) -> ParsedBandoFields:
    # Difesa: raw_data_obj potrebbe arrivare come lista/stringa (es. JSON array da DB)
    if not isinstance(raw_data_obj, dict):
        raw_data_obj = {}
    corpus = _build_corpus(title, link_bando, raw_data_obj)
    importo_threshold = _get_importo_plausibile_threshold()

    codice = _extract_codice_bando(corpus)
    stato = _extract_stato_bando(corpus)
    
    # Data: preferenza pagina dettaglio > ricerca etichettata > fallback prima data generica
    data_pubblicazione = None
    data_apertura = None
    data_scadenza = None
    generic_dates: list[date] = []
    
    page_dates = raw_data_obj.get("page_dates") or []
    if page_dates:
        # Se abbiamo date dalla pagina, usa la prima come pubblicazione
        parsed_page_dates = [_parse_date(str(d)) for d in page_dates]
        parsed_page_dates = [d for d in parsed_page_dates if d is not None]
        if parsed_page_dates:
            data_pubblicazione = parsed_page_dates[0]
            if len(parsed_page_dates) > 1:
                generic_dates = parsed_page_dates[1:]
    else:
        # Altrimenti ricerca etichettata nel corpus
        data_pubblicazione = _extract_labeled_date(corpus, ["pubblicazione", "pubblicato", "pubblicata"])
        data_apertura = _extract_labeled_date(corpus, ["apertura", "aperto", "aperta", "inizio", "opening", "opens", "start"])
        data_scadenza = _extract_labeled_date(corpus, ["scadenza", "scade", "termine", "deadline", "closes", "closing", "submission"])
        generic_dates = _extract_all_dates(corpus)
        if data_pubblicazione is None and generic_dates:
            data_pubblicazione = generic_dates[0]

    # Fallback P4: date da PDF allegato se pagina dettaglio non ne ha fornite.
    if data_pubblicazione is None:
        pdf_dates = raw_data_obj.get("page_pdf_dates") or []
        if pdf_dates:
            parsed_pdf_dates = [_parse_date(str(v)) for v in pdf_dates]
            parsed_pdf_dates = [d for d in parsed_pdf_dates if d is not None]
            if parsed_pdf_dates:
                data_pubblicazione = parsed_pdf_dates[0]
                generic_dates.extend(parsed_pdf_dates[1:])

    # Fallback aggiuntivo: molte sorgenti espongono la data direttamente nell'URL.
    if data_pubblicazione is None:
        url_date = _extract_date_from_urls(link_bando, str(raw_data_obj.get("source_url") or ""))
        if url_date is not None:
            data_pubblicazione = url_date

    # Se abbiamo almeno una data generica e mancano apertura/scadenza, usiamo le date residue.
    if generic_dates:
        unused_dates = [d for d in generic_dates if d is not None]
        if data_apertura is None and unused_dates:
            data_apertura = unused_dates[0]
        if data_scadenza is None:
            if len(unused_dates) >= 2:
                data_scadenza = unused_dates[-1]
            elif len(unused_dates) == 1 and data_apertura != unused_dates[0]:
                data_scadenza = unused_dates[0]
    
    # Comunque cerca apertura e scadenza etichettate
    if data_apertura is None:
        data_apertura = _extract_labeled_date(corpus, ["apertura", "aperto", "aperta", "inizio", "opening", "opens", "start"])
    if data_scadenza is None:
        data_scadenza = _extract_labeled_date(corpus, ["scadenza", "scade", "termine", "deadline", "closes", "closing", "submission"])

    # Importo: raccogliamo candidati da pagina, PDF e corpus e scegliamo il più plausibile.
    # Questo evita che un valore spurio piccolo (es. anno, prefisso, importo parziale)
    # blocchi il recupero di un importo migliore presente nello snippet o nel PDF.
    importo_candidates: list[tuple[str, Decimal]] = []

    def _add_importo_candidate(raw_value: Any, *, context_text: str = "") -> None:
        if raw_value is None:
            return
        raw_text = str(raw_value).strip()
        if not raw_text:
            return
        dec_value = _to_decimal_amount(raw_text)
        if dec_value is not None and _is_usable_importo_candidate(raw_text, dec_value, context_text, importo_threshold):
            importo_candidates.append((raw_text, dec_value))

    importo_context = " ".join(
        filter(
            None,
            [
                str(raw_data_obj.get("page_description") or ""),
                str(raw_data_obj.get("page_content_snippet") or ""),
                str(raw_data_obj.get("pdf_text_snippet") or ""),
                str(raw_data_obj.get("page_pdf_text_snippet") or ""),
            ],
        )
    )

    _add_importo_candidate(raw_data_obj.get("page_importo"), context_text=importo_context)
    _add_importo_candidate(raw_data_obj.get("page_pdf_importo"), context_text=importo_context)

    corpus_importo_raw, corpus_importo_num = _extract_importo(corpus)
    if corpus_importo_num is not None and corpus_importo_raw is not None:
        importo_candidates.append((corpus_importo_raw, corpus_importo_num))

    importo_raw: str | None = None
    importo_num: Decimal | None = None
    if importo_candidates:
        plausible_candidates = [item for item in importo_candidates if item[1] > importo_threshold]
        pool = plausible_candidates or importo_candidates
        importo_raw, importo_num = max(pool, key=lambda item: item[1])

    # Descrizione: preferenza pagina dettaglio > parent_context
    page_description = raw_data_obj.get("page_description")
    if page_description:
        descrizione = page_description[:4000]
    elif raw_data_obj.get("pdf_text_snippet") or raw_data_obj.get("page_pdf_text_snippet"):
        descrizione = str(raw_data_obj.get("pdf_text_snippet") or raw_data_obj.get("page_pdf_text_snippet"))[:4000]
    else:
        descrizione = None
        candidate_title = str(raw_data_obj.get("candidate_title") or "").strip()
        parent_context = str(raw_data_obj.get("parent_context") or "").strip()
        if parent_context and parent_context != candidate_title:
            descrizione = parent_context[:4000]

    page_title = raw_data_obj.get("page_title")
    final_titolo = _choose_best_title(
        page_title=page_title,
        fallback_title=title,
        link_bando=link_bando,
        raw_data_obj=raw_data_obj,
    )[:4000]

    # Extra: errori fetch, date candidates
    extra: dict[str, Any] = {}
    if generic_dates:
        extra["date_candidates"] = [d.isoformat() for d in generic_dates]
    page_fetch_error = raw_data_obj.get("fetch_error")
    if page_fetch_error:
        extra["page_fetch_error"] = page_fetch_error

    # Marker: se tutti i campi critici sono NULL (pagina di lista/indice, non dettaglio),
    # marchia il record come "sospetto" per escluderlo dai KPI e segnalarlo come da verificare.
    if (
        data_pubblicazione is None
        and data_apertura is None
        and data_scadenza is None
        and importo_num is None
    ):
        stato = "sospetto"

    return ParsedBandoFields(
        titolo=final_titolo,
        codice_bando=codice,
        descrizione=descrizione,
        stato_bando=stato,
        data_pubblicazione=data_pubblicazione,
        data_apertura=data_apertura,
        data_scadenza=data_scadenza,
        importo=importo_raw,
        importo_numerico=importo_num,
        data_extra=extra or None,
    )


def _build_corpus(title: str, link_bando: str, raw_data_obj: dict[str, Any]) -> str:
    chunks = [
        title or "",
        link_bando or "",
        str(raw_data_obj.get("candidate_title") or ""),
        str(raw_data_obj.get("candidate_url") or ""),
        str(raw_data_obj.get("parent_context") or ""),
        str(raw_data_obj.get("source_url") or ""),
        str(raw_data_obj.get("page_title") or ""),
        str(raw_data_obj.get("page_description") or ""),
        str(raw_data_obj.get("page_content_snippet") or ""),
        str(raw_data_obj.get("page_importo") or ""),
        str(raw_data_obj.get("page_pdf_importo") or ""),
        str(raw_data_obj.get("pdf_text_snippet") or ""),
        str(raw_data_obj.get("page_pdf_text_snippet") or ""),
    ]
    return " ".join(c.strip() for c in chunks if c).strip()


def _extract_codice_bando(text: str) -> str | None:
    patterns = [
        r"\b(?:cod(?:ice)?\s*(?:bando|avviso)?\s*[:\-]?\s*)([A-Za-z0-9_\-/.]{3,})\b",
        r"\b(?:cup|cig)\s*[:\-]?\s*([A-Za-z0-9_\-/.]{3,})\b",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1)[:255]
    return None


def _extract_stato_bando(text: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["chius", "scadut", "terminat", "closed"]):
        return "chiuso"
    if any(k in lowered for k in ["programm", "prossim", "in arrivo", "upcoming", "forthcoming"]):
        return "programmato"
    if any(k in lowered for k in ["apert", "attiv", "in corso"]) or re.search(r"\bis open\b", lowered):
        return "aperto"
    return "programmato"


def _extract_labeled_date(text: str, labels: list[str]) -> date | None:
    label_group = "|".join(re.escape(l) for l in labels)
    pattern = rf"(?:{label_group})([^\n]{{0,90}})"
    for m in re.finditer(pattern, text, flags=re.IGNORECASE):
        chunk = m.group(1) or ""
        date_match = re.search(_DATE_TOKEN_PATTERN, chunk, flags=re.IGNORECASE)
        if not date_match:
            continue
        parsed = _parse_date(date_match.group(1))
        if parsed is not None:
            return parsed
    return None


def _extract_all_dates(text: str) -> list[date]:
    matches = re.findall(_DATE_TOKEN_PATTERN, text, flags=re.IGNORECASE)
    out: list[date] = []
    seen: set[date] = set()
    for raw in matches:
        d = _parse_date(raw)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _parse_date(raw: str) -> date | None:
    s = raw.strip()

    # formato compatto: 20260515
    if re.match(r"^\d{8}$", s):
        year = int(s[:4])
        month = int(s[4:6])
        day = int(s[6:8])
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # formato testuale italiano/inglese: 15 marzo 2026 / 27 November 2025
    textual = re.match(
        r"^(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|jun|jul|aug|sep|oct|dec|"
        r"gennaio|febbraio|marzo|aprile|maggio|giugno|"
        r"luglio|agosto|settembre|ottobre|novembre|dicembre|"
        r"gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\.?\s+(\d{4})$",
        s,
        flags=re.IGNORECASE,
    )
    if textual:
        dd, mm_name, yyyy = textual.groups()
        mm = _MONTH_NAME_TO_INT.get(mm_name.lower())
        if mm is None:
            return None
        try:
            return date(int(yyyy), mm, int(dd))
        except ValueError:
            return None

    if re.match(r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}$", s):
        y, m, d = re.split(r"[./-]", s)
        try:
            return date(int(y), int(m), int(d))
        except ValueError:
            return None

    if re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", s):
        dd, mm, yy = re.split(r"[./-]", s)
        year = int(yy)
        if year < 100:
            year += 2000
        try:
            return date(year, int(mm), int(dd))
        except ValueError:
            return None

    return None


def _extract_importo(text: str) -> tuple[str | None, Decimal | None]:
    # Gestisce pattern tipo: € 1.234.567,89, 1,5 milioni di euro, 250 mila euro.
    candidates: list[tuple[str, Decimal]] = []

    multiplier_patterns = [
        (r"([0-9]+(?:[\.,][0-9]{1,2})?)\s*(?:milioni?|mln)\b", Decimal("1000000")),
        (r"([0-9]+(?:[\.,][0-9]{1,2})?)\s*(?:mila)\b", Decimal("1000")),
        (r"([0-9]+(?:[\.,][0-9]{1,2})?)\s+(?:millions?|mln)\s+(?:euros?|eur|€)", Decimal("1000000")),
        (r"([0-9]+(?:[\.,][0-9]{1,2})?)\s+(?:billions?|bln)\s+(?:euros?|eur|€)", Decimal("1000000000")),
    ]
    for pattern, mult in multiplier_patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw = (m.group(1) or "").strip()
            base_amount = _to_decimal_amount(raw)
            if base_amount is None:
                continue
            candidates.append((m.group(0).strip(), base_amount * mult))

    patterns = [
        r"(?:€|eur|euro)\s*([0-9][0-9\s\.,]{0,30})",
        r"([0-9][0-9\s\.,]{3,30})\s*(?:€|eur|euro)",
        r"(?:importo|dotazione(?:\s+finanziaria)?|finanziamento(?:\s+massimo)?|contributo(?:\s+massimo)?)"
        r"[^0-9]{0,20}([0-9][0-9\s\.,]{3,30})",
    ]
    for p in patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            raw = m.group(1).strip()
            dec = _to_decimal_amount(raw)
            if dec is not None:
                candidates.append((raw, dec))

    if not candidates:
        return None, None

    # In presenza di piu' importi (min/max), privilegia il valore piu' alto.
    best_raw, best_dec = max(candidates, key=lambda item: item[1])
    return best_raw, best_dec


def _has_strong_economic_context(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _ECONOMIC_CONTEXT_KEYWORDS)


def _is_usable_importo_candidate(raw_text: str, amount: Decimal, context_text: str, threshold: Decimal) -> bool:
    if amount <= 0:
        return False

    combined = f"{raw_text} {context_text}".strip()
    if amount <= threshold:
        if re.search(r"\d\s+\d", raw_text):
            return False
        if not _has_strong_economic_context(combined):
            return False

    if amount < Decimal("10") and not _has_strong_economic_context(combined):
        return False

    return True


def _is_url_like_title(value: str) -> bool:
    text = (value or "").strip()
    if not text or " " in text:
        return False
    if re.match(r"^(?:https?://|www\.)", text, flags=re.IGNORECASE):
        return True

    try:
        parsed = urlparse(f"https://{text}")
    except ValueError:
        # urlsplit solleva ValueError("Invalid IPv6 URL") su '[' non bilanciate;
        # un frammento non parsabile come URL non è un titolo URL-like.
        return False
    host = (parsed.netloc or "").lower()
    return bool(host and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", host))


def _normalize_title_text(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    if _is_url_like_title(text):
        return None
    text = _NAVIGATION_NOISE_PATTERN.split(text)[0].strip(" |-:")
    if "|" in text:
        text = text.split("|", 1)[0].strip()
    return text or None


def _normalize_title_tokens(text: str | None) -> set[str]:
    normalized = _normalize_title_text(text)
    if not normalized:
        return set()
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", normalized.lower())
        if token not in _TITLE_STOPWORDS
    }
    return tokens


def _is_generic_title(text: str | None) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    return any(re.match(pattern, lowered) for pattern in _GENERIC_TITLE_PATTERNS)


def _slug_to_title(link_bando: str) -> str | None:
    try:
        parsed = urlparse(link_bando or "")
    except ValueError:
        # URL malformato: impossibile derivare un titolo dallo slug
        return None
    segments = [s for s in (parsed.path or "").split("/") if s]
    if not segments:
        return None
    for segment in reversed(segments):
        candidate = re.sub(r"\.[a-z0-9]{1,5}$", "", segment, flags=re.IGNORECASE)
        if not candidate or re.fullmatch(r"20\d{2}|\d+", candidate):
            continue
        return re.sub(r"[-_]+", " ", candidate).strip().title()
    return None


def _split_title_like_fragments(text: str) -> list[str]:
    if not text:
        return []
    pieces = re.split(r"[\n\r\t|]+|\s{2,}|\s+-\s+|\s+[>»]\s+", text)
    fragments: list[str] = []
    for piece in pieces:
        candidate = _normalize_title_text(piece)
        if not candidate:
            continue
        if len(candidate) < 12 or len(candidate) > 180:
            continue
        fragments.append(candidate)
    return fragments


def _extract_title_from_snippets(link_bando: str, raw_data_obj: dict[str, Any]) -> str | None:
    slug_title = _slug_to_title(link_bando)
    slug_tokens = _normalize_title_tokens(slug_title)
    snippet_sources = [
        raw_data_obj.get("page_content_snippet_300"),
        raw_data_obj.get("pdf_text_snippet_300"),
        raw_data_obj.get("page_pdf_text_snippet_300"),
        raw_data_obj.get("page_content_snippet"),
        raw_data_obj.get("pdf_text_snippet"),
        raw_data_obj.get("page_pdf_text_snippet"),
        raw_data_obj.get("page_description"),
        raw_data_obj.get("parent_context"),
    ]

    candidates: list[tuple[int, str]] = []
    for snippet in snippet_sources:
        for fragment in _split_title_like_fragments(str(snippet or "")):
            if _is_generic_title(fragment):
                continue
            tokens = _normalize_title_tokens(fragment)
            if not tokens:
                continue
            overlap = len(tokens & slug_tokens) if slug_tokens else 0
            keyword_hits = sum(1 for keyword in _TITLE_RELEVANT_KEYWORDS if keyword in fragment.lower())
            if overlap == 0 and keyword_hits == 0:
                continue
            score = overlap * 4 + keyword_hits * 2
            if re.search(r"\b20\d{2}\b", fragment):
                score += 1
            if fragment.endswith(":"):
                score -= 2
            if score <= 0:
                continue
            candidates.append((score, fragment))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates[0][1]


def _score_title_candidate(text: str, *, link_bando: str) -> int:
    lowered = text.lower()
    score = 0
    if any(keyword in lowered for keyword in _TITLE_RELEVANT_KEYWORDS):
        score += 3
    if re.search(r"\b20\d{2}\b", lowered):
        score += 1
    if 12 <= len(text) <= 180:
        score += 1
    if _is_generic_title(text):
        score -= 5
    if _NAVIGATION_NOISE_PATTERN.search(text):
        score -= 5
    slug_tokens = _normalize_title_tokens(_slug_to_title(link_bando))
    overlap = len(_normalize_title_tokens(text) & slug_tokens)
    score += overlap * 2
    return score


def _choose_best_title(page_title: Any, fallback_title: str, link_bando: str, raw_data_obj: dict[str, Any]) -> str:
    snippet_title = _extract_title_from_snippets(link_bando, raw_data_obj)
    slug_title = _slug_to_title(link_bando)
    weighted_candidates = [
        (3, _normalize_title_text(snippet_title)),
        (0, _normalize_title_text(str(page_title or ""))),
        (1, _normalize_title_text(str(raw_data_obj.get("candidate_title") or ""))),
        (1, _normalize_title_text(fallback_title)),
        (-2, _normalize_title_text(slug_title)),
    ]
    cleaned = [(weight, candidate) for weight, candidate in weighted_candidates if candidate]
    if not cleaned:
        return slug_title or "Bando senza titolo"
    return max(cleaned, key=lambda item: _score_title_candidate(item[1], link_bando=link_bando) + item[0])[1]


def _extract_date_from_urls(*urls: str) -> date | None:
    for url in urls:
        if not url:
            continue

        # Pattern path tipici: /2026/05/31 oppure /31-05-2026 oppure .../20260531...
        patterns = [
            r"\b(20\d{2})[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])\b",
            r"\b(0?[1-9]|[12]\d|3[01])[/-](0?[1-9]|1[0-2])[/-](20\d{2})\b",
            r"\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b",
        ]
        for idx, p in enumerate(patterns):
            m = re.search(p, url)
            if not m:
                continue
            try:
                if idx == 0:
                    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if idx == 1:
                    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def _to_decimal_amount(raw: str) -> Decimal | None:
    # Manteniamo solo cifre e separatori numerici per gestire payload rumorosi.
    s = re.sub(r"[^0-9,\.]", "", raw or "").strip()
    if not s or not re.search(r"\d", s):
        return None

    if "," in s and "." in s:
        # Se l'ultimo separatore è la virgola, assumiamo formato EU (1.234,56).
        if s.rfind(",") > s.rfind("."):
            normalized = s.replace(".", "").replace(",", ".")
        else:
            # Altrimenti formato US (1,234.56).
            normalized = s.replace(",", "")
    elif "," in s:
        comma_parts = s.split(",")
        if len(comma_parts) == 2 and len(comma_parts[1]) <= 2:
            # Decimali con virgola: 1234,56
            normalized = s.replace(",", ".")
        else:
            # Migliaia con virgola: 1,234,567
            normalized = s.replace(",", "")
    elif "." in s:
        dot_parts = s.split(".")
        if len(dot_parts) > 2:
            # Migliaia con punti: 1.234.567
            normalized = s.replace(".", "")
        elif len(dot_parts) == 2 and len(dot_parts[1]) == 3:
            # Caso ambiguo ma tipicamente migliaia italiane senza virgola: 12.500
            normalized = s.replace(".", "")
        else:
            normalized = s
    else:
        normalized = s

    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
