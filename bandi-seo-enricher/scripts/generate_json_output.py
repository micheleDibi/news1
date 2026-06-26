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
    output_path: str | Path | None = None,
) -> dict:
    if livello not in WORD_RANGES:
        raise ValueError(f"livello non valido: {livello}. Atteso uno di {list(WORD_RANGES)}")

    final_slug = slug or slugify(titolo)

    # Auto-calcolo scadenza_stato dalla scadenza (se l'utente non lo passa o non e' coerente, ricomputa)
    auto_stato = _compute_scadenza_stato(bando_data.get("scadenza"))
    bando_data = {**bando_data}
    bando_data.setdefault("scadenza_stato", auto_stato)
    if bando_data.get("scadenza") and bando_data["scadenza_stato"] != auto_stato:
        bando_data["scadenza_stato"] = auto_stato

    # Validation
    warnings: list[str] = []
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
    if not _validate_date_iso(bando_data.get("scadenza")):
        warnings.append(f"scadenza non in formato ISO: {bando_data.get('scadenza')}")
    if bando_data.get("scadenza_stato") not in (None, "aperto", "in_scadenza", "scaduto"):
        warnings.append(f"scadenza_stato non valido: {bando_data.get('scadenza_stato')}")
    if bando_data.get("tipologia") not in (None, "FESR", "FSE", "Interreg", "nazionale", "regionale", "misto", "JTF"):
        warnings.append(f"tipologia non canonica: {bando_data.get('tipologia')}")
    for k in ("importo_totale_eur", "importo_max_per_progetto_eur"):
        v = bando_data.get(k)
        if v is not None and (not isinstance(v, int) or v < 0):
            warnings.append(f"{k} deve essere int positivo o null, trovato: {v!r}")
    for k in ("beneficiari", "tematica"):
        v = bando_data.get(k)
        if not isinstance(v, list):
            warnings.append(f"{k} deve essere una lista (anche vuota), trovato: {type(v).__name__}")

    if not bando_data.get("link_candidatura"):
        bando_data["link_candidatura"] = source_url

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
            "area_geografica": bando_data.get("area_geografica"),
            "beneficiari": bando_data.get("beneficiari", []) or [],
            "tematica": bando_data.get("tematica", []) or [],
            "scadenza": bando_data.get("scadenza"),
            "scadenza_stato": bando_data.get("scadenza_stato"),
            "importo_totale_eur": bando_data.get("importo_totale_eur"),
            "importo_max_per_progetto_eur": bando_data.get("importo_max_per_progetto_eur"),
            "link_candidatura": bando_data.get("link_candidatura"),
            "riferimento_normativo": bando_data.get("riferimento_normativo"),
        },
        "factcheck_report": factcheck_report or [],
        "fonti": fonti or [],
        "validation": {
            "passed": len(warnings) == 0,
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
