"""Generatore JSON output per un singolo bando.

Mappa 1:1 le colonne della tabella Supabase `bandi` (vedi SKILL.md).
Esegue validazione di lunghezza/formato e include il blocco `validation`.

API:
    from generate_json_output import create_bando_json
    create_bando_json(...)

Lo script puo' anche essere invocato da CLI:
    # valida un JSON gia' costruito
    python scripts/generate_json_output.py --validate-only some_bando.json

    # costruisce + valida il JSON del bando dai kwargs di create_bando_json
    # (file JSON SENZA la chiave output_path) e lo stampa su stdout
    python scripts/generate_json_output.py --build-from inputs.json

    # come sopra ma scrive anche il file (stdout = solo esito validazione)
    python scripts/generate_json_output.py --build-from inputs.json --out output/slug.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BLACKLIST_PATH = HERE.parent / "references" / "blacklist_frasi.md"

META_TITLE_MAX = 60
META_DESC_MAX = 155
TITOLO_MAX = 80
DESC_BREVE_MIN = 180
DESC_BREVE_MAX = 320
SLUG_MAX = 80

WORD_RANGES = {
    "flash_bando": (350, 500),
    "guida_bando": (800, 1200),
}

ALLEGATI_TIPI = {"pdf", "doc", "docx", "zip", "rtf", "xlsx", "xls", "odt", "ods", "altro"}
URL_RE = re.compile(r"^https?://", re.IGNORECASE)

SCADENZA_SOURCE_VALUES = {"official_pdf", "official_page", "inferred", "missing"}
REJECTION_CATEGORIES = {
    "index_page", "search_results", "category_page",
    "expired_archive", "not_a_funding_call", "unreachable",
}

# v3: lunghezza massima del frammento del markdown citato come prova della data.
# Allineata a DB CHECK constraint bando_quote_length_check.
QUOTE_MAX_LEN = 300

STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "e", "ed", "o", "od", "ma", "se", "che", "non",
}


def slugify(value: str, max_len: int = SLUG_MAX) -> str:
    """Lowercase, kebab-case, senza stopword italiane, senza accenti."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    # tieni alfanum, spazi e trattini
    normalized = re.sub(r"[^a-z0-9\s\-]", " ", normalized)
    tokens = [t for t in re.split(r"[\s\-]+", normalized) if t and t not in STOPWORDS_IT]
    slug = "-".join(tokens)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if len(slug) <= max_len:
        return slug
    truncated = slug[:max_len]
    if "-" in truncated:
        truncated = truncated.rsplit("-", 1)[0]
    return truncated


def _load_blacklist() -> list[str]:
    if not BLACKLIST_PATH.exists():
        return []
    text = BLACKLIST_PATH.read_text(encoding="utf-8")
    phrases: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        # estrae il testo tra virgolette se presente, altrimenti tutto dopo "- "
        m = re.search(r"\"([^\"]+)\"|“([^”]+)”", s)
        if m:
            phrases.append(m.group(1) or m.group(2))
    return [p.strip().lower() for p in phrases if p.strip()]


def _segments_to_plain(segments: list[dict]) -> str:
    return " ".join(seg.get("text", "") for seg in segments if "text" in seg)


def _section_to_plain(section: dict) -> str:
    t = section.get("type")
    if t in ("paragraph",):
        return _segments_to_plain(section.get("segments", []))
    if t in ("h2", "h3"):
        return section.get("text", "")
    if t in ("bullet_list", "numbered_list"):
        return " ".join(_segments_to_plain(item.get("segments", [])) for item in section.get("items", []))
    if t == "faq":
        out = []
        for item in section.get("items", []):
            out.append(item.get("q", ""))
            a = item.get("a", {})
            out.append(_segments_to_plain(a.get("segments", [])))
        return " ".join(out)
    return ""


def _count_words(sections: list[dict]) -> int:
    plain = " ".join(_section_to_plain(s) for s in sections)
    plain = re.sub(r"\s+", " ", plain).strip()
    return len(plain.split()) if plain else 0


def _validate_sections(sections: list[dict]) -> list[str]:
    warnings: list[str] = []
    allowed = {"paragraph", "h2", "h3", "bullet_list", "numbered_list", "faq"}
    for i, s in enumerate(sections):
        if not isinstance(s, dict):
            warnings.append(f"section[{i}] non e' un dict")
            continue
        t = s.get("type")
        if t not in allowed:
            warnings.append(f"section[{i}] type sconosciuto: {t}")
            continue
        if t == "paragraph" and not s.get("segments"):
            warnings.append(f"section[{i}] paragraph senza segments")
        if t in ("h2", "h3") and not s.get("text"):
            warnings.append(f"section[{i}] {t} senza text")
        if t in ("bullet_list", "numbered_list") and not s.get("items"):
            warnings.append(f"section[{i}] {t} senza items")
    return warnings


def _check_blacklist(sections: list[dict]) -> list[str]:
    bl = _load_blacklist()
    if not bl:
        return []
    plain = " ".join(_section_to_plain(s) for s in sections).lower()
    return [f"frase blacklist trovata: \"{p}\"" for p in bl if p in plain]


def _validate_date_iso(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _validate_allegati(allegati: Any) -> tuple[list[dict], list[str]]:
    """Valida e normalizza la lista allegati. Ritorna (lista_pulita, warnings)."""
    warnings: list[str] = []
    if allegati is None:
        return [], warnings
    if not isinstance(allegati, list):
        warnings.append(f"allegati deve essere una lista, trovato: {type(allegati).__name__}")
        return [], warnings

    out: list[dict] = []
    seen_urls: set[str] = set()
    for i, item in enumerate(allegati):
        if not isinstance(item, dict):
            warnings.append(f"allegati[{i}] non e' un dict")
            continue
        url = (item.get("url") or "").strip()
        label = (item.get("label") or "").strip()
        tipo = (item.get("tipo") or "").strip().lower()
        if not url:
            warnings.append(f"allegati[{i}] url mancante")
            continue
        if not URL_RE.match(url):
            warnings.append(f"allegati[{i}] url non http(s): {url[:80]}")
            continue
        if not label:
            warnings.append(f"allegati[{i}] label mancante")
            continue
        if tipo not in ALLEGATI_TIPI:
            warnings.append(f"allegati[{i}] tipo non canonico: {tipo!r}")
            tipo = "altro"
        if url in seen_urls:
            continue  # dedup silenzioso
        seen_urls.add(url)
        out.append({"label": label, "url": url, "tipo": tipo})
    return out, warnings


def _compute_scadenza_stato(scadenza: str | None) -> str | None:
    if not scadenza:
        return None
    try:
        d = dt.date.fromisoformat(scadenza)
    except ValueError:
        return None
    today = dt.date.today()
    if d < today:
        return "scaduto"
    if (d - today).days <= 30:
        return "in_scadenza"
    return "aperto"


_SUBLINKS_MAX = 50
_SUBLINK_LABEL_MAX = 200
_REDISCOVERABLE_REJECTIONS = {"index_page", "category_page"}


def _normalize_sublinks(raw_sublinks: object, rejection_category: str | None) -> tuple[list[dict], list[str]]:
    """Normalizza e valida `validation.discovered_sublinks` emessi dalla skill.

    v4 (discovery-by-skill): quando la skill marca un record come index_page o
    category_page, puo' emettere un array `discovered_sublinks` con i link figli
    visibili nel markdown. L'orchestrator li accodera' come nuovi BandoCandidate.

    Ritorna (lista_normalizzata, warnings).
    """
    warnings: list[str] = []
    if raw_sublinks is None:
        return [], warnings
    if not isinstance(raw_sublinks, list):
        warnings.append(f"discovered_sublinks deve essere una lista, ricevuto: {type(raw_sublinks).__name__}")
        return [], warnings

    # I sublinks hanno senso solo per index_page e category_page. Per gli altri
    # rejection_category li scartiamo silenziosamente con warning.
    if rejection_category not in _REDISCOVERABLE_REJECTIONS and raw_sublinks:
        warnings.append(
            f"discovered_sublinks emessi con rejection_category={rejection_category!r}: "
            f"ignorati (consentiti solo per {sorted(_REDISCOVERABLE_REJECTIONS)})"
        )
        return [], warnings

    normalized: list[dict] = []
    seen_urls: set[str] = set()
    for idx, entry in enumerate(raw_sublinks):
        if not isinstance(entry, dict):
            warnings.append(f"discovered_sublinks[{idx}] non e' un oggetto: skip")
            continue
        url = entry.get("url")
        label = entry.get("label")
        if not isinstance(url, str) or not url.strip():
            warnings.append(f"discovered_sublinks[{idx}].url assente o non stringa: skip")
            continue
        url_s = url.strip()
        # Solo http/https assoluti
        if not (url_s.startswith("http://") or url_s.startswith("https://")):
            warnings.append(f"discovered_sublinks[{idx}].url non e' http/https assoluto: {url_s[:80]!r}: skip")
            continue
        # Dedup intra-payload
        if url_s in seen_urls:
            continue
        seen_urls.add(url_s)
        # Label normalizzata
        if label is None:
            label_s = url_s
        elif isinstance(label, str):
            label_s = label.strip() or url_s
        else:
            label_s = str(label)[:_SUBLINK_LABEL_MAX]
        if len(label_s) > _SUBLINK_LABEL_MAX:
            label_s = label_s[: _SUBLINK_LABEL_MAX - 1] + "…"
        normalized.append({"url": url_s, "label": label_s})

    if len(normalized) > _SUBLINKS_MAX:
        warnings.append(
            f"discovered_sublinks troncati a {_SUBLINKS_MAX} (ricevuti {len(normalized)})"
        )
        normalized = normalized[:_SUBLINKS_MAX]
    return normalized, warnings


def _normalize_validation(validation_data: dict | None) -> dict:
    """Normalizza il blocco validation in input.

    Default backward-compat: is_valid_bando=True quando non specificato.
    """
    raw = validation_data or {}
    is_valid = raw.get("is_valid_bando", True)
    if not isinstance(is_valid, bool):
        is_valid = bool(is_valid)
    reason = raw.get("validation_reason")
    if reason is not None and not isinstance(reason, str):
        reason = str(reason)
    rejection = raw.get("rejection_category")
    if rejection is not None and not isinstance(rejection, str):
        rejection = str(rejection)

    sublinks, sublink_warnings = _normalize_sublinks(raw.get("discovered_sublinks"), rejection)

    return {
        "is_valid_bando": is_valid,
        "validation_reason": reason,
        "rejection_category": rejection,
        "discovered_sublinks": sublinks,
        # warnings interni propagati al chiamante via _normalize_validation_warnings
        "_warnings": sublink_warnings,
    }


def create_bando_json(
    *,
    source_url: str,
    source_domain: str,
    titolo: str,
    occhiello: str | None,
    slug: str | None,
    descrizione_breve: str,
    meta_title: str,
    meta_description: str,
    contenuto_sections: list[dict],
    bando_data: dict,
    factcheck_report: list[dict],
    fonti: list[dict],
    livello: str,
    allegati: list[dict] | None = None,
    validation_data: dict | None = None,
    output_path: str | Path | None = None,
) -> dict:
    """Costruisce il JSON di un bando (single-bando).

    `validation_data` (opzionale) contiene il verdetto di validita' della skill:
      {"is_valid_bando": bool, "validation_reason": str|None, "rejection_category": str|None}

    Se `is_valid_bando=False` (pagina indice, ricerca, archivio, ecc.), gli altri
    campi possono restare placeholder/null: l'orchestrator nascondera' il record
    dal frontend. Le validazioni di lunghezza/contenuto SEO vengono saltate per
    non bloccare l'emissione del payload "respinto".

    Se `validation_data=None` (default), assume `is_valid_bando=True` per
    retrocompatibilita' con i call site preesistenti.
    """
    if livello not in WORD_RANGES:
        raise ValueError(f"livello non valido: {livello}. Atteso uno di {list(WORD_RANGES)}")

    validation = _normalize_validation(validation_data)
    is_valid_bando = validation["is_valid_bando"]

    final_slug = slug or slugify(titolo) or slugify(source_url)

    # Auto-calcolo scadenza_stato dalla scadenza (se l'utente non lo passa o non e' coerente, ricomputa)
    auto_stato = _compute_scadenza_stato(bando_data.get("scadenza"))
    bando_data = {**bando_data}
    bando_data.setdefault("scadenza_stato", auto_stato)
    if bando_data.get("scadenza") and bando_data["scadenza_stato"] != auto_stato:
        bando_data["scadenza_stato"] = auto_stato

    # Validation
    warnings: list[str] = []

    # Propaga warnings dalla normalizzazione di discovered_sublinks (v4).
    sublink_warnings = validation.pop("_warnings", [])
    if sublink_warnings:
        warnings.extend(sublink_warnings)

    # Per i record bocciati (is_valid_bando=False) salta tutte le validazioni di
    # forma editoriale/SEO: il payload e' un placeholder, non un articolo.
    if is_valid_bando:
        if len(meta_title) > META_TITLE_MAX:
            warnings.append(f"meta_title troppo lungo: {len(meta_title)} > {META_TITLE_MAX}")
        if len(meta_description) > META_DESC_MAX:
            warnings.append(f"meta_description troppo lunga: {len(meta_description)} > {META_DESC_MAX}")
        if len(titolo) > TITOLO_MAX:
            warnings.append(f"titolo troppo lungo: {len(titolo)} > {TITOLO_MAX}")
        if not (DESC_BREVE_MIN <= len(descrizione_breve) <= DESC_BREVE_MAX):
            warnings.append(f"descrizione_breve fuori range {DESC_BREVE_MIN}-{DESC_BREVE_MAX}: {len(descrizione_breve)}")
        if len(final_slug) > SLUG_MAX:
            warnings.append(f"slug troppo lungo: {len(final_slug)} > {SLUG_MAX}")
        if meta_title.strip().lower() == titolo.strip().lower():
            warnings.append("meta_title e titolo (H1) sono identici: devono essere diversi")

        word_count = _count_words(contenuto_sections)
        wmin, wmax = WORD_RANGES[livello]
        if not (wmin <= word_count <= wmax):
            warnings.append(f"word_count fuori range {livello} ({wmin}-{wmax}): {word_count}")

        warnings.extend(_validate_sections(contenuto_sections))
        warnings.extend(_check_blacklist(contenuto_sections))

        if not bando_data.get("ente_erogatore"):
            warnings.append("ente_erogatore mancante (NOT NULL nello schema)")
    else:
        word_count = _count_words(contenuto_sections)
        # Verdetto negativo: validation_reason richiesto, rejection_category opzionale ma
        # caldamente raccomandata. Avvisa se mancano per audit.
        if not validation.get("validation_reason"):
            warnings.append("validation_reason mancante: serve a tracciare perche' il record e' stato bocciato")
        rej = validation.get("rejection_category")
        if rej is not None and rej not in REJECTION_CATEGORIES:
            warnings.append(f"rejection_category non canonica: {rej!r}")

    allegati_clean, allegati_warnings = _validate_allegati(allegati)
    warnings.extend(allegati_warnings)

    # Validazioni "leggere" sempre (anche per bocciati): formato date, enum, tipi.
    if not _validate_date_iso(bando_data.get("scadenza")):
        warnings.append(f"scadenza non in formato ISO: {bando_data.get('scadenza')}")
    if bando_data.get("scadenza_stato") not in (None, "aperto", "in_scadenza", "scaduto"):
        warnings.append(f"scadenza_stato non valido: {bando_data.get('scadenza_stato')}")
    if bando_data.get("tipologia") not in (None, "FESR", "FSE", "Interreg", "nazionale", "regionale", "misto", "JTF"):
        warnings.append(f"tipologia non canonica: {bando_data.get('tipologia')}")
    scadenza_source = bando_data.get("scadenza_source")
    if scadenza_source is not None and scadenza_source not in SCADENZA_SOURCE_VALUES:
        warnings.append(f"scadenza_source non valido: {scadenza_source!r}")
    if scadenza_source is None and bando_data.get("scadenza"):
        # Se c'e' una scadenza ma manca la provenienza, segnala (necessaria per decidere
        # se l'orchestrator puo' sovrascrivere data_scadenza).
        warnings.append("scadenza_source mancante: necessario per decidere se sovrascrivere data_scadenza nel DB")
    if not _validate_date_iso(bando_data.get("data_pubblicazione")):
        warnings.append(f"data_pubblicazione non in formato ISO: {bando_data.get('data_pubblicazione')}")
    data_pubblicazione_source = bando_data.get("data_pubblicazione_source")
    if data_pubblicazione_source is not None and data_pubblicazione_source not in SCADENZA_SOURCE_VALUES:
        warnings.append(f"data_pubblicazione_source non valido: {data_pubblicazione_source!r}")
    if data_pubblicazione_source is None and bando_data.get("data_pubblicazione"):
        warnings.append(
            "data_pubblicazione_source mancante: necessario per decidere se sovrascrivere data_pubblicazione nel DB"
        )

    # v3 — V1: quote OBBLIGATORIA quando data presente e source != "missing".
    # Anti-hallucination: la skill DEVE citare letteralmente il frammento del markdown
    # che contiene la data. Senza quote → date non verificabili → bocciate dal validator.
    scadenza_quote_raw = bando_data.get("scadenza_quote")
    pubblicazione_quote_raw = bando_data.get("data_pubblicazione_quote")

    if bando_data.get("scadenza") and scadenza_source not in (None, "missing") and not scadenza_quote_raw:
        warnings.append(
            "V1_QUOTE_REQUIRED: scadenza_quote obbligatorio quando scadenza non-null e source != 'missing'"
        )
    if (
        bando_data.get("data_pubblicazione")
        and data_pubblicazione_source not in (None, "missing")
        and not pubblicazione_quote_raw
    ):
        warnings.append(
            "V1_QUOTE_REQUIRED: data_pubblicazione_quote obbligatorio quando data_pubblicazione non-null e source != 'missing'"
        )

    # v3 — V3: tronca quote troppo lunghi (DB CHECK constraint = 300 char).
    # Tronca con warning invece di fallire per non perdere il payload intero.
    scadenza_quote: str | None = None
    if isinstance(scadenza_quote_raw, str) and scadenza_quote_raw:
        if len(scadenza_quote_raw) > QUOTE_MAX_LEN:
            warnings.append(f"V3_QUOTE_TRUNCATED: scadenza_quote {len(scadenza_quote_raw)} > {QUOTE_MAX_LEN}")
            scadenza_quote = scadenza_quote_raw[:QUOTE_MAX_LEN]
        else:
            scadenza_quote = scadenza_quote_raw
    pubblicazione_quote: str | None = None
    if isinstance(pubblicazione_quote_raw, str) and pubblicazione_quote_raw:
        if len(pubblicazione_quote_raw) > QUOTE_MAX_LEN:
            warnings.append(
                f"V3_QUOTE_TRUNCATED: data_pubblicazione_quote {len(pubblicazione_quote_raw)} > {QUOTE_MAX_LEN}"
            )
            pubblicazione_quote = pubblicazione_quote_raw[:QUOTE_MAX_LEN]
        else:
            pubblicazione_quote = pubblicazione_quote_raw

    # v3 — V4: coerenza date (regola critica #10). Se incoerenti, forza entrambe a null
    # con source='missing': non possiamo persistere dati incoerenti, e il DB ha un CHECK
    # constraint bando_dates_consistency_check che bloccherebbe l'UPDATE comunque.
    scad_iso = bando_data.get("scadenza")
    pub_iso = bando_data.get("data_pubblicazione")
    if scad_iso and pub_iso and _validate_date_iso(scad_iso) and _validate_date_iso(pub_iso):
        try:
            if dt.date.fromisoformat(pub_iso) > dt.date.fromisoformat(scad_iso):
                warnings.append(
                    f"V4_INCONSISTENT_DATES: data_pubblicazione={pub_iso} > scadenza={scad_iso}: "
                    "force entrambe a null/missing per non persistere dati incoerenti"
                )
                bando_data["scadenza"] = None
                bando_data["scadenza_source"] = "missing"
                bando_data["data_pubblicazione"] = None
                bando_data["data_pubblicazione_source"] = "missing"
                scadenza_source = "missing"
                data_pubblicazione_source = "missing"
                scadenza_quote = None
                pubblicazione_quote = None
                # Ricomputa stato (auto_stato e' None se scadenza=None).
                bando_data["scadenza_stato"] = None
        except ValueError:
            pass  # gia' segnalato sopra come "non in formato ISO"
    for k in ("importo_totale_eur", "importo_max_per_progetto_eur"):
        v = bando_data.get(k)
        if v is not None and (not isinstance(v, int) or v < 0):
            warnings.append(f"{k} deve essere int positivo o null, trovato: {v!r}")
    for k in ("beneficiari", "tematica"):
        v = bando_data.get(k)
        if v is None:
            continue  # ammesso per bocciati / placeholder; il payload finale normalizza a []
        if not isinstance(v, list):
            warnings.append(f"{k} deve essere una lista (anche vuota), trovato: {type(v).__name__}")

    # v4: link_candidatura_source enum (extracted | fallback_source | missing).
    # Backward-compat: se il chiamante usa ancora link_candidatura_verified bool,
    # lo deriva. Niente fallback automatico a source_url: la skill decide.
    link_candidatura_source = bando_data.get("link_candidatura_source")
    if not link_candidatura_source:
        legacy_verified = bando_data.get("link_candidatura_verified")
        if legacy_verified is True:
            link_candidatura_source = "extracted"
        elif bando_data.get("link_candidatura"):
            link_candidatura_source = "missing"  # link presente ma non verificato → richiede attenzione
        else:
            link_candidatura_source = "missing"
    if link_candidatura_source not in ("extracted", "fallback_source", "missing"):
        warnings.append(f"link_candidatura_source non valido: {link_candidatura_source}")
    if bando_data.get("link_candidatura") and link_candidatura_source == "missing":
        warnings.append("link_candidatura presente ma source='missing': verificalo o azzera il link")

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "livello": livello,
        "source_url": source_url,
        "source_domain": source_domain,
        "slug": final_slug,
        "titolo": titolo,
        "occhiello": occhiello,
        "descrizione_breve": descrizione_breve,
        "contenuto": {"sections": contenuto_sections},
        "meta_title": meta_title,
        "meta_description": meta_description,
        "bando": {
            "ente_erogatore": bando_data.get("ente_erogatore"),
            "tipologia": bando_data.get("tipologia"),
            "programma": bando_data.get("programma"),
            "modalita_erogazione": bando_data.get("modalita_erogazione"),
            "area_geografica": bando_data.get("area_geografica"),
            "beneficiari": bando_data.get("beneficiari") or [],
            "codici_ateco": bando_data.get("codici_ateco") or [],
            "tematica": bando_data.get("tematica") or [],
            "scadenza": bando_data.get("scadenza"),
            "scadenza_source": scadenza_source,
            "scadenza_quote": scadenza_quote,
            "scadenza_stato": bando_data.get("scadenza_stato"),
            "data_pubblicazione": bando_data.get("data_pubblicazione"),
            "data_pubblicazione_source": data_pubblicazione_source,
            "data_pubblicazione_quote": pubblicazione_quote,
            "importo_totale_eur": bando_data.get("importo_totale_eur"),
            "importo_max_per_progetto_eur": bando_data.get("importo_max_per_progetto_eur"),
            "link_candidatura": bando_data.get("link_candidatura"),
            "link_candidatura_source": link_candidatura_source,
        },
        "allegati": allegati_clean,
        "factcheck_report": factcheck_report or [],
        "fonti": fonti or [],
        "validation": {
            "passed": len(warnings) == 0,
            "is_valid_bando": is_valid_bando,
            "validation_reason": validation["validation_reason"],
            "rejection_category": validation["rejection_category"],
            # v4 — discovery-by-skill: sub-link visibili nella pagina-indice/categoria
            # da accodare come nuovi BandoCandidate. Sempre presente (lista, anche vuota)
            # per semplificare il consumer in update_bando_from_payload.
            "discovered_sublinks": validation.get("discovered_sublinks") or [],
            "warnings": warnings,
            "word_count": word_count,
            "meta_title_length": len(meta_title),
            "meta_description_length": len(meta_description),
            "titolo_length": len(titolo),
            "slug_length": len(final_slug),
            "descrizione_breve_length": len(descrizione_breve),
        },
    }

    if output_path is not None:
        out_path = Path(output_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# -------------------- CLI: --validate-only --------------------

def _validate_only(json_path: Path) -> int:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    sections = (data.get("contenuto") or {}).get("sections", [])
    warnings = []
    warnings.extend(_validate_sections(sections))
    warnings.extend(_check_blacklist(sections))
    wc = _count_words(sections)
    livello = data.get("livello")
    if livello in WORD_RANGES:
        wmin, wmax = WORD_RANGES[livello]
        if not (wmin <= wc <= wmax):
            warnings.append(f"word_count fuori range {livello} ({wmin}-{wmax}): {wc}")
    out = {"file": str(json_path), "word_count": wc, "warnings": warnings, "passed": not warnings}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not warnings else 1


# -------------------- CLI: --build-from --------------------

def _build_from(inputs_path: Path, out: str | None) -> int:
    """Costruisce + valida il JSON del bando dai kwargs di create_bando_json.

    `inputs_path` e' un JSON con esattamente i parametri keyword di
    create_bando_json TRANNE `output_path` (lo determina --out).
    - senza --out: stampa il JSON completo del bando su stdout (caso "solo JSON").
    - con --out: scrive il file e stampa solo l'esito di validazione su stdout.
    """
    kwargs = json.loads(inputs_path.read_text(encoding="utf-8"))
    if "output_path" in kwargs:
        # output_path e' gestito da --out: ignora qualsiasi valore nel file
        kwargs.pop("output_path")
    payload = create_bando_json(**kwargs, output_path=out)
    validation = payload["validation"]
    if out is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(
            {"written": out, "passed": validation["passed"], "warnings": validation["warnings"]},
            ensure_ascii=False, indent=2,
        ))
    return 0 if validation["passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Costruisce/valida il JSON di un singolo bando (in alternativa, importa create_bando_json)"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--validate-only", help="Percorso JSON gia' costruito da validare")
    g.add_argument("--build-from", help="Percorso JSON con i kwargs di create_bando_json (senza output_path)")
    ap.add_argument("--out", default=None, help="Se presente con --build-from, scrive il JSON su questo path")
    args = ap.parse_args()
    if args.validate_only:
        return _validate_only(Path(args.validate_only))
    return _build_from(Path(args.build_from), args.out)


if __name__ == "__main__":
    sys.exit(main())
