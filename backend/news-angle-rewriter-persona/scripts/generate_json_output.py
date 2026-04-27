#!/usr/bin/env python3
"""
Genera JSON con report SEO + articolo strutturato per news-angle-rewriter-persona.
Variante della skill base: include nei metadati `tono` e `persona` scelti dall'utente.

Output unico ufficiale: metadati SEO, report angolo, fact-check, articolo con
sezioni e segmenti inline (text/bold/link) parsati, blocco validazione,
blocco meta con tono+persona.
"""
import json
import os
import re
import unicodedata
from datetime import datetime


BLACKLIST = [
    "in un contesto di", "importante sottolineare", "non è un caso che",
    "come è noto", "questione assume rilevanza", "opportuno evidenziare",
    "in conclusione si tratta", "aspetto particolarmente rilevante",
    "questa misura si inserisce", "assume un ruolo cruciale",
    "rappresenta una sfida", "fondamentale comprendere", "in questo scenario",
    "alla luce di quanto", "merita particolare attenzione",
    "non si può non menzionare", "giova ricordare", "preme sottolineare",
    "doveroso evidenziare", "a tal proposito", "nel panorama attuale",
    "la maggior parte degli articoli non spiega",
    "il dato che i competitor non citano",
    "a differenza di quanto riportato",
    "nessuno ne parla ma", "quello che non ti dicono",
]

WORD_LIMITS = {
    'flash': (450, 550),
    'editoriale': (600, 900),
    'evergreen': (1000, 1500),
}

TITLE_LIMITS = {'flash': 55, 'editoriale': 60, 'evergreen': 60}
H1_LIMITS = {'flash': 70, 'editoriale': 75, 'evergreen': 75}

TONI_VALIDI = {
    "Neutrale", "Formale", "Informale", "Persuasivo", "Umoristico",
    "Serio", "Ottimistico", "Motivazionale", "Rispettoso", "Assertivo",
    "Conversazione",
}

PERSONE_VALIDE = {
    "Copywriter", "Giornalista", "Blogger", "Esperto di settore",
    "Freelance", "Accademico", "Saggista", "Attivista",
    "Divulgatore Scientifico", "Insegnante",
}

TONO_DEFAULT = "Neutrale"
PERSONA_DEFAULT = "Giornalista"


def _slugify(text, used=None):
    """Slug stabile per ancore HTML: minuscole, accenti rimossi, alfanumerico-trattino.

    Se `used` è un set, garantisce unicità appendendo -2, -3, ... ai duplicati.
    """
    s = unicodedata.normalize('NFKD', text or '')
    s = s.encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    base = s or 'sezione'
    if used is None:
        return base
    candidate = base
    n = 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _parse_inline(text):
    """Converte `[LINK:anchor|url]` e `**bold**` in segmenti strutturati."""
    segments = []
    parts = re.split(r'(\[LINK:.*?\|.*?\]|\*\*.*?\*\*)', text)
    for part in parts:
        if not part:
            continue
        link_match = re.match(r'\[LINK:(.*?)\|(.*?)\]', part)
        bold_match = re.match(r'\*\*(.*?)\*\*', part)
        if link_match:
            segments.append({
                "kind": "link",
                "text": link_match.group(1),
                "url": link_match.group(2),
            })
        elif bold_match:
            segments.append({"kind": "bold", "text": bold_match.group(1)})
        else:
            segments.append({"kind": "text", "text": part})
    return segments


def _count_words(content_sections):
    total = 0
    for s in content_sections:
        text = s.get('text', '')
        if isinstance(text, list):
            for t in text:
                total += len(t.split())
        else:
            total += len(text.split())
    return total


def _extract_plain_text(content_sections):
    parts = []
    for s in content_sections:
        text = s.get('text', '')
        if isinstance(text, list):
            parts.extend(text)
        else:
            parts.append(text)
    full = ' '.join(parts).lower()
    full = re.sub(r'\[LINK:.*?\|.*?\]', '', full)
    full = re.sub(r'\*\*', '', full)
    return full


def _normalize_meta(tono, persona):
    """Valida tono e persona, ritorna (tono_normalizzato, persona_normalizzata).

    Applica i default se i parametri sono None o stringa vuota.
    Solleva ValueError se il valore passato non è in enum.
    """
    t = (tono or "").strip() or TONO_DEFAULT
    p = (persona or "").strip() or PERSONA_DEFAULT
    if t not in TONI_VALIDI:
        raise ValueError(
            f"Tono non valido: {t!r}. Valori ammessi: {sorted(TONI_VALIDI)}"
        )
    if p not in PERSONE_VALIDE:
        raise ValueError(
            f"Persona non valida: {p!r}. Valori ammessi: {sorted(PERSONE_VALIDE)}"
        )
    return t, p


def validate_seo(title, meta_title, meta_description, content_sections, livello, keyword=None):
    warnings = []

    max_title = TITLE_LIMITS.get(livello, 60)
    if len(meta_title) > max_title:
        warnings.append(f"TITLE troppo lungo: {len(meta_title)} char (max {max_title})")

    if len(meta_description) > 155:
        warnings.append(f"DESCRIPTION troppo lunga: {len(meta_description)} char (max 155)")

    max_h1 = H1_LIMITS.get(livello, 75)
    if len(title) > max_h1:
        warnings.append(f"H1 troppo lungo: {len(title)} char (max {max_h1})")

    if title.strip().lower() == meta_title.strip().lower():
        warnings.append("H1 e TITLE sono identici (devono essere diversi)")

    word_count = _count_words(content_sections)
    min_w, max_w = WORD_LIMITS.get(livello, (0, 9999))
    if word_count < min_w:
        warnings.append(f"Parole insufficienti: {word_count} (min {min_w} per {livello})")
    elif word_count > max_w:
        warnings.append(f"Troppe parole: {word_count} (max {max_w} per {livello})")

    full_text = _extract_plain_text(content_sections)
    found_blacklist = [b for b in BLACKLIST if b in full_text]
    if found_blacklist:
        warnings.append(f"Frasi blacklist trovate: {found_blacklist}")

    kw_count = None
    if keyword:
        kw_count = full_text.count(keyword.lower())
        if kw_count > 3:
            warnings.append(f"Keyword '{keyword}' ripetuta {kw_count} volte (max 3)")

    bullet_count = sum(1 for s in content_sections if s.get('type') == 'bullet_list')
    numbered_count = sum(1 for s in content_sections if s.get('type') == 'numbered_list')
    if bullet_count > 1:
        warnings.append(f"Troppi bullet_list: {bullet_count} (max 1 per articolo)")
    if numbered_count > 1:
        warnings.append(f"Troppi numbered_list: {numbered_count} (max 1 per articolo)")

    closing_types = {'bullet_list', 'numbered_list', 'auto_index', 'h2', 'h3'}
    last_real = None
    for s in reversed(content_sections):
        t = s.get('type')
        if t and t != 'auto_index':
            last_real = t
            break
    if last_real in closing_types - {'auto_index'}:
        warnings.append(
            f"Chiusura non discorsiva: ultima sezione è '{last_real}'. "
            "Aggiungi un paragraph finale di 2-3 frasi nello stile della persona."
        )

    return {
        "passed": len(warnings) == 0,
        "warnings": warnings,
        "word_count": word_count,
        "title_length": len(meta_title),
        "description_length": len(meta_description),
        "h1_length": len(title),
        "keyword_count": kw_count,
    }


def _normalize_sections(content_sections):
    """Converte le content_sections in oggetti JSON con segmenti parsati.

    - h2/h3 ricevono un campo `id` slugificato dal text (univoco) per ancore HTML.
    - Sezioni di tipo `auto_index` vengono espanse in un paragrafo con link
      cliccabili verso ciascun h2 della pagina (anchor #slug).
    """
    out = []
    used_ids = set()
    h2_index = []
    auto_index_positions = []

    for s in content_sections:
        t = s.get('type', 'paragraph')
        text = s.get('text', '')
        if t in ('h2', 'h3'):
            sid = _slugify(text, used_ids)
            entry = {"type": t, "id": sid, "text": text}
            if t == 'h2':
                h2_index.append({"id": sid, "text": text})
            out.append(entry)
        elif t == 'auto_index':
            auto_index_positions.append(len(out))
            out.append(None)
        elif t == 'paragraph':
            out.append({"type": t, "segments": _parse_inline(text)})
        elif t in ('bullet_list', 'numbered_list'):
            items = text if isinstance(text, list) else [text]
            out.append({
                "type": t,
                "items": [_parse_inline(i) for i in items],
            })
        else:
            out.append({"type": t, "text": text})

    if auto_index_positions:
        if h2_index:
            segments = [{"kind": "bold", "text": "Indice:"}]
            for i, h in enumerate(h2_index):
                segments.append({"kind": "text", "text": " " if i == 0 else " | "})
                segments.append({
                    "kind": "link",
                    "text": h["text"],
                    "url": f"#{h['id']}",
                })
            idx_section = {"type": "paragraph", "segments": segments}
            for pos in auto_index_positions:
                out[pos] = idx_section
        else:
            out = [s for s in out if s is not None]

    return out


def build_seo_article_payload(
    title, meta_title, meta_description,
    content_sections, fonti, angolo, livello,
    factcheck_report, competitor_report=None,
    keyword=None, source_url=None,
    tono=None, persona=None,
):
    """Costruisce il payload JSON strutturato senza side effect filesystem.

    I parametri tono e persona sono normalizzati ai default se None/vuoti
    e validati contro gli enum.
    """
    tono_norm, persona_norm = _normalize_meta(tono, persona)
    validation = validate_seo(title, meta_title, meta_description, content_sections, livello, keyword)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_url": source_url,
        "livello": livello,
        "keyword": keyword,
        "meta": {
            "tono": tono_norm,
            "persona": persona_norm,
        },
        "seo": {
            "meta_title": meta_title,
            "meta_description": meta_description,
            "h1": title,
        },
        "angolo": angolo,
        "competitor_report": competitor_report or [],
        "factcheck_report": factcheck_report or [],
        "article": {
            "h1": title,
            "sections": _normalize_sections(content_sections),
            "plain_text_preview": _extract_plain_text(content_sections)[:400],
        },
        "fonti": fonti or [],
        "validation": validation,
    }


def create_seo_article_json(
    title, meta_title, meta_description,
    content_sections, fonti, angolo, livello,
    factcheck_report, competitor_report=None,
    keyword=None, output_path='./output/articolo.json',
    source_url=None,
    tono=None, persona=None,
):
    """Crea JSON completo con report + articolo e lo scrive su disco."""
    payload = build_seo_article_payload(
        title=title,
        meta_title=meta_title,
        meta_description=meta_description,
        content_sections=content_sections,
        fonti=fonti,
        angolo=angolo,
        livello=livello,
        factcheck_report=factcheck_report,
        competitor_report=competitor_report,
        keyword=keyword,
        source_url=source_url,
        tono=tono,
        persona=persona,
    )

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[OK] JSON salvato: {output_path}")
    meta = payload["meta"]
    print(f"[OK] Voce: persona={meta['persona']} | tono={meta['tono']}")
    validation = payload["validation"]
    if validation["warnings"]:
        print("[!] Warning SEO:")
        for w in validation["warnings"]:
            print(f"  - {w}")
    else:
        print(f"[OK] Validazione superata | parole: {validation['word_count']}")

    return payload
