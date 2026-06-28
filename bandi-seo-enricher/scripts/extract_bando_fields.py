"""Estrattore di campi strutturati da bando (markdown scrapato).

Approccio: regex + euristiche conservative. Tutti i campi sono nullable: se non
c'e' prova testuale chiara, restituisce null. Non stima mai.

Per l'estrazione semantica piu' ricca (beneficiari/tematica come stringhe libere
che richiedono interpretazione) restituisce solo *candidati grezzi*: il vero
fraseggio definitivo va scelto in fase di generazione editoriale leggendo il
markdown completo.

Uso CLI:
    python scripts/extract_bando_fields.py --markdown-file /tmp/bando.md --url "https://..." --hint '{"ente":"Regione X","tipologia":"FESR","area":"Lombardia"}'

Output: JSON su stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}


# -------------------- scadenza --------------------

DATE_PATTERNS = [
    # 30 settembre 2026
    re.compile(r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})\b", re.IGNORECASE),
    # 30/09/2026 oppure 30-09-2026 oppure 30.09.2026
    re.compile(r"\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b"),
    # 2026-09-30 (ISO)
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
]

DEADLINE_CONTEXTS = [
    r"scaden[zt]a",
    r"termine ultim[oa]",
    r"entro le ore \d{1,2}[:\.]?\d{0,2} del",
    r"entro il giorno",
    r"entro il",
    r"present(?:ate|are le) (?:domande|richieste|candidature)? entro",
    r"present(?:azione|are) (?:della |delle )?domand[ea] entro",
    r"il (?:presente )?avviso scade",
    r"termine per la presentazione",
    r"chiusura present[az]ione",
]
DEADLINE_CONTEXT_RE = re.compile("|".join(DEADLINE_CONTEXTS), re.IGNORECASE)

# Contesti per data di PUBBLICAZIONE del bando dalla fonte ufficiale.
# Pubblicazione del decreto/avviso, BUR/Gazzetta, delibera Giunta/Consiglio.
# NON la data in cui noi l'abbiamo scrapato — quella e' tracciata in primo_scraping_at del DB.
PUBLICATION_CONTEXTS = [
    r"pubblicat[oa] (?:il|in data)?",
    r"data (?:di )?pubblicazione",
    r"pubblicazione (?:in |sul |sulla )?bur(?:l|c)?",
    r"pubblicazione (?:in |sulla )?gazzetta(?: ufficiale)?",
    r"gazzetta ufficiale (?:n\.|numero) \d+ del",
    r"decret(?:o|i) (?:dirigenzial[ei] )?(?:n\.|numero) [\w\.\-/]+ del",
    r"delib(?:era|erazione)(?: di giunta(?: regionale)?| del consiglio)? (?:n\.|numero) [\w\.\-/]+ del",
    r"determin(?:a|azione) (?:dirigenzial[ei] )?(?:n\.|numero) [\w\.\-/]+ del",
    r"d\.?g\.?r\.? (?:n\.|numero)? [\w\.\-/]+ del",
    r"d\.?d\.?g\.? (?:n\.|numero)? [\w\.\-/]+ del",
    r"prot(?:ocollo|\.) (?:n\.|numero) [\w\.\-/]+ del",
    r"emanat[oa] (?:il|in data)?",
    r"approvat[oa] (?:con (?:dgr|dd|ddg|delibera|decreto) [\w\.\-/]+ )?(?:il|del|in data)?",
]
PUBLICATION_CONTEXT_RE = re.compile("|".join(PUBLICATION_CONTEXTS), re.IGNORECASE)

# v3: blacklist context per evitare false-positive da decreti citati come BASE NORMATIVA
# ("ai sensi del...", "in attuazione del...", "visto il..."): in quel caso il "del X/Y/Z"
# NON e' la data di pubblicazione del bando corrente ma una citazione storica.
PUBLICATION_BLACKLIST_CONTEXTS = [
    r"in attuazione",
    r"ai sensi (?:del|della|dell|di)",
    r"vist[oa] (?:il|la|l'|lo|gli|le|i)",
    r"visto il decreto",
    r"in conformit[aà]",
    r"in coerenza con",
    r"sulla base (?:del|della|dei|delle)",
    r"a norma (?:del|della|dell)",
    r"come previsto (?:dal|dalla|dai|dalle)",
    r"emanat[oa] (?:in attuazione|ai sensi)",
]
PUBLICATION_BLACKLIST_RE = re.compile("|".join(PUBLICATION_BLACKLIST_CONTEXTS), re.IGNORECASE)

# v3: lunghezza del frammento citato (consistente con DB CHECK e validator Python).
QUOTE_MAX_LEN = 300
QUOTE_CTX_BEFORE = 25
QUOTE_CTX_AFTER = 200


def _build_quote(text: str, match_start: int) -> str:
    """Estrae un frammento del testo intorno a `match_start` per uso come quote autoritativo.

    Bilanciato: ~25 char di contesto prima, ~200 dopo (la data + label di solito ci sta).
    Tronca a QUOTE_MAX_LEN. Whitespace normalizzato a singolo spazio.
    """
    start = max(0, match_start - QUOTE_CTX_BEFORE)
    end = min(len(text), match_start + QUOTE_CTX_AFTER)
    fragment = text[start:end]
    fragment = re.sub(r"\s+", " ", fragment).strip()
    if len(fragment) > QUOTE_MAX_LEN:
        fragment = fragment[:QUOTE_MAX_LEN]
    return fragment


def _parse_match(m: re.Match, pattern_idx: int) -> Optional[str]:
    try:
        if pattern_idx == 0:
            d, mon, y = int(m.group(1)), MONTHS_IT[m.group(2).lower()], int(m.group(3))
        elif pattern_idx == 1:
            d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mon, d).isoformat()
    except (ValueError, KeyError):
        return None


def extract_scadenza(text: str) -> dict:
    """Cerca la data piu' rilevante associata a un contesto di scadenza.

    Strategia:
    - Per ogni occorrenza di un contesto di scadenza, cerca la PRIMA data dopo
      di esso entro 200 caratteri.
    - Se ce ne sono piu' d'una, sceglie la PROSSIMA dalla data odierna; se
      tutte sono passate, sceglie l'ultima.

    Restituisce anche `scadenza_quote`: frammento letterale del testo intorno
    al match scelto (v3 — citation strict, max 300 char).
    """
    candidates: list[tuple[str, int]] = []  # (iso, ctx_start)
    for ctx_match in DEADLINE_CONTEXT_RE.finditer(text):
        window = text[ctx_match.start(): ctx_match.start() + 200]
        for idx, pat in enumerate(DATE_PATTERNS):
            m = pat.search(window)
            if m:
                iso = _parse_match(m, idx)
                if iso:
                    candidates.append((iso, ctx_match.start()))
                    break

    if not candidates:
        return {
            "scadenza": None,
            "scadenza_quote": None,
            "candidates_count": 0,
            "method": "no_context_match",
        }

    today = date.today().isoformat()
    future = sorted((iso, ctx) for iso, ctx in candidates if iso >= today)
    if future:
        chosen_iso, chosen_ctx = future[0]
    else:
        sorted_desc = sorted(candidates, key=lambda t: t[0])
        chosen_iso, chosen_ctx = sorted_desc[-1]
    return {
        "scadenza": chosen_iso,
        "scadenza_quote": _build_quote(text, chosen_ctx),
        "candidates_count": len(candidates),
        "method": "context_proximity",
    }


# -------------------- data_pubblicazione --------------------

def extract_data_pubblicazione(text: str) -> dict:
    """Cerca la data di PUBBLICAZIONE del bando dalla fonte ufficiale.

    Strategia analoga a `extract_scadenza` ma diversa per filtro semantico:
    - cerca finestra di 200 char dopo un contesto di pubblicazione (PUBLICATION_CONTEXTS)
    - **v3**: scarta il candidato se nella finestra ±200 char compare un blacklist context
      (es. "in attuazione del", "ai sensi del", "visto il decreto") — segno che il decreto
      e' citato come BASE NORMATIVA, non come pubblicazione del bando corrente.
    - prende la prima data trovata in quella finestra
    - preferisce la data piu' RECENTE tra i candidati (la pubblicazione e' un evento singolo:
      su pagine con piu' decreti vince quello piu' recente, di solito quello attuale).

    Ritorna sempre `source` enum: `official_page` se trovato qui (la skill puo' poi
    promuoverlo a `official_pdf` se viene dal parse di un PDF), o `missing`.
    Include anche `data_pubblicazione_quote` (frammento letterale del testo).
    """
    candidates: list[tuple[str, int]] = []  # (iso, ctx_start)
    for ctx_match in PUBLICATION_CONTEXT_RE.finditer(text):
        ctx_start = ctx_match.start()
        # v3: blacklist context window — se la finestra contiene "ai sensi del", "in attuazione",
        # "visto il", il match e' una citazione storica, non la pubblicazione corrente. Scarta.
        blacklist_window_start = max(0, ctx_start - 200)
        blacklist_window_end = min(len(text), ctx_start + 200)
        blacklist_window = text[blacklist_window_start:blacklist_window_end]
        if PUBLICATION_BLACKLIST_RE.search(blacklist_window):
            continue

        window = text[ctx_start: ctx_start + 200]
        for idx, pat in enumerate(DATE_PATTERNS):
            m = pat.search(window)
            if m:
                iso = _parse_match(m, idx)
                if iso:
                    candidates.append((iso, ctx_start))
                    break

    if not candidates:
        return {
            "data_pubblicazione": None,
            "data_pubblicazione_source": "missing",
            "data_pubblicazione_quote": None,
            "candidates_count": 0,
            "method": "no_context_match",
        }

    # Tra i candidati preferiamo la data piu' recente: i bandi spesso citano decreti
    # precedenti come storia, e quello piu' recente e' di solito la pubblicazione attuale.
    sorted_desc = sorted(candidates, key=lambda t: t[0], reverse=True)
    chosen_iso, chosen_ctx = sorted_desc[0]
    return {
        "data_pubblicazione": chosen_iso,
        "data_pubblicazione_source": "official_page",
        "data_pubblicazione_quote": _build_quote(text, chosen_ctx),
        "candidates_count": len(candidates),
        "method": "context_proximity",
    }


# -------------------- importi --------------------

# Regex unica per numeri europei tipo: 12.500.000,00 / 12500000 / 12,5 / 500.000
NUMBER_RE = re.compile(r"\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:,\d+)?")
EURO_NEAR = re.compile(r"(?:€|euro|EUR)", re.IGNORECASE)


def _to_euro_int(num_str: str, multiplier: int = 1) -> Optional[int]:
    """Converte '12.500.000,00' o '12,5' in intero euro applicando moltiplicatore."""
    raw = num_str.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return None
    val *= multiplier
    if val < 0 or val > 10**12:
        return None
    return int(round(val))


AMOUNT_PATTERNS_TOTALE = [
    re.compile(r"(?:dotaz(?:ione)?|stanziament[oi]|risorse|budget|fondi)(?:\s+(?:finanziar[ia]e?|complessiv[oa]|tot(?:ale|ali))?)?(?:\s+pari\s+a)?(?:\s+(?:di|pari\s+a))?\s*(?:€\s*|euro\s*|EUR\s*)?(\d[\d\.\s,]*)\s*(?:€|euro|EUR|mln|milioni|mila|M€|k€)?", re.IGNORECASE),
]
AMOUNT_PATTERNS_MAX = [
    re.compile(r"(?:contributo|finanziamento|importo)\s+massim[oa](?:\s+per\s+(?:progetto|domand[ae]))?\s*(?:di|pari\s+a)?\s*(?:€\s*|euro\s*|EUR\s*)?(\d[\d\.\s,]*)\s*(?:€|euro|EUR|mln|milioni|mila|M€|k€)?", re.IGNORECASE),
    re.compile(r"fino\s+a\s*(?:€\s*|euro\s*|EUR\s*)?(\d[\d\.\s,]*)\s*(?:€|euro|EUR|mln|milioni|mila|M€|k€)?(?:\s+per\s+(?:progetto|domand[ae]|beneficiario))", re.IGNORECASE),
]


def _detect_multiplier(window: str) -> int:
    w = window.lower()
    if "milion" in w or "mln" in w or "m€" in w or " m euro" in w:
        return 1_000_000
    if "mila" in w or "k€" in w:
        return 1_000
    return 1


def extract_importo(text: str, patterns: list[re.Pattern]) -> Optional[int]:
    for pat in patterns:
        for m in pat.finditer(text):
            num_str = m.group(1)
            # finestra a destra del match per intercettare "milioni"/"mila"
            tail = text[m.end(): m.end() + 30]
            multiplier = _detect_multiplier(num_str + " " + tail)
            val = _to_euro_int(num_str, multiplier)
            if val and val >= 100:  # scarta cifre minuscole verosimilmente non importi
                return val
    return None


# -------------------- ente_erogatore --------------------

ENTE_PATTERNS = [
    re.compile(r"(Regione\s+[A-ZÀ-Ü][a-zà-ü\-']+(?:\s+[A-ZÀ-Ü][a-zà-ü\-']+)?)"),
    re.compile(r"(Ministero\s+(?:del|dell['’]|della|delle|degli|dei)\s+[A-ZÀ-Ü][a-zà-ü\-' ]+)"),
    re.compile(r"(Provincia\s+autonoma\s+di\s+[A-ZÀ-Ü][a-zà-ü]+)"),
    re.compile(r"(Commissione\s+europea)"),
    re.compile(r"(Programma\s+Interreg\s+[A-Za-zÀ-Üà-ü\-']+(?:\s+[A-Za-zÀ-Üà-ü\-']+)*)"),
]


def extract_ente(text: str) -> Optional[str]:
    for pat in ENTE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


# -------------------- riferimento normativo --------------------

NORM_PATTERNS = [
    re.compile(r"\bDGR\s+n\.?\s*[\d/\.\-]+(?:\s+del\s+\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})?", re.IGNORECASE),
    re.compile(r"\bD\.?\s*M\.?\s+n\.?\s*[\d/\.\-]+(?:\s+del\s+\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})?", re.IGNORECASE),
    re.compile(r"\bDecreto\s+(?:Direttoriale|Dirigenziale|Ministeriale)\s+n\.?\s*[\d/\.\-]+", re.IGNORECASE),
    re.compile(r"\bDeliberazione(?:\s+della\s+Giunta(?:\s+Regionale)?)?\s+n\.?\s*[\d/\.\-]+", re.IGNORECASE),
    re.compile(r"\bReg(?:olamento)?\.?\s*\(?UE\)?\s+n?\.?\s*[\d/\.\-]+", re.IGNORECASE),
    re.compile(r"\bPNRR\s*[-—]\s*Missione\s+\d+[^,\.\n]{0,80}", re.IGNORECASE),
]


def extract_riferimento(text: str) -> Optional[str]:
    for pat in NORM_PATTERNS:
        m = pat.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


# -------------------- link candidatura --------------------

CAND_KEYWORDS = re.compile(
    r"(domand[ea]|candidat[ou]ra|present[az]ione|modulo|form|sportello|sistema\s+informativo|bandi\s+on\s+line)",
    re.IGNORECASE,
)
LINK_RE = re.compile(r"\((https?://[^\s\)]+)\)")
LINK_TEXT_RE = re.compile(r"\[([^\]]{1,120})\]\((https?://[^\s\)]+)\)")


def extract_link_candidatura(text: str, source_url: str) -> Optional[str]:
    """Cerca un link in cui l'anchor o il testo vicino contenga parole della candidatura.

    Restituisce None se non trova nulla di evidente: in tal caso il chiamante
    usa source_url come fallback.
    """
    for m in LINK_TEXT_RE.finditer(text):
        anchor, url = m.group(1), m.group(2)
        if CAND_KEYWORDS.search(anchor) and url != source_url:
            return url

    # fallback: link nudo in un paragrafo che parla di candidatura
    paragraphs = re.split(r"\n\s*\n", text)
    for p in paragraphs:
        if CAND_KEYWORDS.search(p):
            for um in LINK_RE.finditer(p):
                if um.group(1) != source_url:
                    return um.group(1)
    return None


# -------------------- candidati beneficiari / tematica --------------------

BENEFICIARI_HEADERS = re.compile(
    r"^(?:#+\s*)?(beneficiar[ie]|destinatari|soggetti\s+ammissibili|chi\s+pu[oò]\s+(?:partecipare|candidarsi)|destinatar[ie]\s+(?:finali|del\s+bando))\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
TEMATICA_HEADERS = re.compile(
    r"^(?:#+\s*)?(obiettivi|finalit[aà]|ambit[oi]\s+di\s+intervento|temat(?:ica|iche)|priorit[aà])\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _candidates_after_header(text: str, header_re: re.Pattern, max_lines: int = 15) -> list[str]:
    out: list[str] = []
    for h in header_re.finditer(text):
        tail = text[h.end():].splitlines()
        for line in tail[:max_lines]:
            line = line.strip()
            if not line:
                continue
            if line.startswith(("#", "---", "===")):
                break  # nuova sezione
            # bullet markdown
            if line.startswith(("-", "*", "•", "·")):
                bullet = line.lstrip("-*•·").strip()
                if bullet:
                    out.append(bullet)
            # frase con elenco virgole inline ("aziende, enti pubblici e associazioni")
            elif "," in line and len(line) < 250:
                out.extend([s.strip() for s in re.split(r"[,;]", line) if s.strip()])
    # dedup preservando ordine
    seen = set()
    deduped: list[str] = []
    for item in out:
        normalized = item.lower()
        if normalized not in seen and len(item) >= 3:
            seen.add(normalized)
            deduped.append(item)
    return deduped[:20]


def extract_beneficiari_candidates(text: str) -> list[str]:
    return _candidates_after_header(text, BENEFICIARI_HEADERS)


def extract_tematica_candidates(text: str) -> list[str]:
    return _candidates_after_header(text, TEMATICA_HEADERS)


# -------------------- entry point --------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Estrae campi strutturati da bando markdown")
    ap.add_argument("--markdown-file", required=True)
    ap.add_argument("--url", required=True, help="URL sorgente del bando")
    ap.add_argument(
        "--hint",
        default="{}",
        help=(
            "JSON hint dal backend (l'orchestrator news1 costruisce l'hint dai dati "
            "relazionali del DB scraper). Chiavi tipiche: ente, tipologia, area, "
            "programma, beneficiari, settori, ateco."
        ),
    )
    args = ap.parse_args()

    md_path = Path(args.markdown_file)
    if not md_path.exists():
        print(json.dumps({"error": f"file non trovato: {md_path}"}), file=sys.stderr)
        return 2

    text = md_path.read_text(encoding="utf-8")
    try:
        hint = json.loads(args.hint)
    except json.JSONDecodeError:
        hint = {}

    scad = extract_scadenza(text)
    pub = extract_data_pubblicazione(text)
    ente_extracted = extract_ente(text)

    result = {
        "source_url": args.url,
        "hint_used": hint,
        "scadenza": scad["scadenza"],
        "scadenza_quote": scad.get("scadenza_quote"),
        "scadenza_extraction": {
            "candidates_count": scad["candidates_count"],
            "method": scad["method"],
        },
        "data_pubblicazione": pub["data_pubblicazione"],
        "data_pubblicazione_source": pub["data_pubblicazione_source"],
        "data_pubblicazione_quote": pub.get("data_pubblicazione_quote"),
        "data_pubblicazione_extraction": {
            "candidates_count": pub["candidates_count"],
            "method": pub["method"],
        },
        "importo_totale_eur": extract_importo(text, AMOUNT_PATTERNS_TOTALE),
        "importo_max_per_progetto_eur": extract_importo(text, AMOUNT_PATTERNS_MAX),
        "ente_erogatore": ente_extracted or hint.get("ente"),
        "tipologia": hint.get("tipologia"),
        "area_geografica": hint.get("area"),
        "link_candidatura": extract_link_candidatura(text, args.url),
        "riferimento_normativo": extract_riferimento(text),
        "beneficiari_candidates": extract_beneficiari_candidates(text),
        "tematica_candidates": extract_tematica_candidates(text),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
