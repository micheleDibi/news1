"""Skill SEO (step v8): enriched -> completed.

Single LLM call Claude Opus 4.7 + tool use `save_seo_bando`. Genera
contenuto editoriale + meta per ogni bando gia' arricchito da preprocess
+ enricher v7. Output: 14 campi che vanno direttamente in tabella `bando`.

NESSUN side effect su FK/junction/date (gia' coperte dall'enricher).
NESSUNA decisione di validita' (gia' fatta dal preprocess).
NESSUN verifier post-call (le date sono gia' validate; campi editoriali
sono opinionali).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import unicodedata
from typing import Any

from .logger import logger
from .preprocessor import _get_anthropic_client
from .settings import get_settings


_TRUNCATE_ELLIPSIS = "..."


def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s if len(s) <= max_chars else s[: max_chars - len(_TRUNCATE_ELLIPSIS)] + _TRUNCATE_ELLIPSIS


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

_ALLEGATO_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Etichetta umana del documento (es. 'Modulo di candidatura')."},
        "url": {"type": "string", "description": "URL assoluto del documento."},
        "tipo": {
            "type": "string",
            "enum": ["pdf", "doc", "docx", "zip", "xlsx", "xls", "rtf", "odt", "ods"],
            "description": "Estensione del file.",
        },
    },
    "required": ["label", "url", "tipo"],
}


_CONTENUTO_SECTION_SCHEMA = {
    "type": "object",
    "description": (
        "Sezione editoriale. type ∈ {h2, paragraph, bullet_list, numbered_list, faq}. "
        "Per h2: {type, text}. "
        "Per paragraph: {type, segments: [{kind: 'text'|'bold'|'link', text, url?}]}. "
        "Per bullet_list/numbered_list: {type, items: [{segments: [...]}]}. "
        "Per faq: {type, items: [{q: text, a: {segments: [...]}}]}."
    ),
}


SAVE_SEO_BANDO_TOOL = {
    "name": "save_seo_bando",
    "description": (
        "Salva il payload editoriale del bando: slug, titoli, descrizione, "
        "contenuto strutturato, classificazioni qualitative e link candidatura. "
        "Tutti i 14 campi obbligatori vanno popolati; quelli marcati nullable "
        "possono essere null se non determinabili dai dati forniti."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "maxLength": 80,
                "description": "Kebab-case lowercase, no stopword italiane (di, il, la, e, con, per, da, in, su, a), descrittivo del bando.",
            },
            "titolo": {
                "type": "string",
                "maxLength": 80,
                "description": "H1 sentence case. Comincia con fatto concreto. ≤80 char.",
            },
            "titolo_breve": {
                "type": ["string", "null"],
                "maxLength": 100,
                "description": "Occhiello breve per card lista (es. categoria bando + ente sintetico). Null se non utile.",
            },
            "descrizione_breve": {
                "type": "string",
                "minLength": 180,
                "maxLength": 320,
                "description": "Preview 180-320 char per card lista. Include ente, tipologia, scadenza in formato italiano.",
            },
            "contenuto": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": _CONTENUTO_SECTION_SCHEMA,
                        "minItems": 2,
                    },
                },
                "required": ["sections"],
                "description": "Contenuto editoriale strutturato in sezioni.",
            },
            "livello": {
                "type": "string",
                "enum": ["flash_bando", "guida_bando"],
                "description": (
                    "flash_bando: 350-500 parole, 2 H2 ('Chi può candidarsi', 'Come e quando'). "
                    "guida_bando: 800-1200 parole, 7-8 H2 con FAQ + errori comuni. "
                    "Scegli guida_bando se regolamento articolato, fasi multiple, importo >5M€."
                ),
            },
            "allegati": {
                "type": "array",
                "items": _ALLEGATO_SCHEMA,
                "description": "Documenti scaricabili (PDF/DOC/...) presenti nel markdown. Array vuoto se nessuno.",
            },
            "ente_erogatore": {
                "type": "string",
                "minLength": 1,
                "description": "Ente che eroga il bando. Deve apparire nei dati di input (titolo_raw, descrizione_raw, raw_data, markdown).",
            },
            "area_geografica": {
                "type": ["string", "null"],
                "description": "Area geografica (es. 'Lombardia', 'Sud Italia', 'Nazionale'). Null se non determinabile.",
            },
            "tematica": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 tag tematici brevi (es. 'Ricerca e innovazione', 'Inclusione sociale').",
            },
            "importo_totale_eur": {
                "type": ["integer", "null"],
                "minimum": 0,
                "description": "Dotazione totale in EURO interi. Null se non identificabile.",
            },
            "importo_max_per_progetto_eur": {
                "type": ["integer", "null"],
                "minimum": 0,
                "description": "Massimo per singolo progetto in EURO interi. Null se non identificabile.",
            },
            "link_candidatura": {
                "type": ["string", "null"],
                "description": "URL del portale candidatura (modulo, sportello). Null se non identificabile.",
            },
            "link_candidatura_source": {
                "type": "string",
                "enum": ["extracted", "fallback_source", "missing"],
                "description": (
                    "'extracted' = trovato esplicitamente nel markdown come link a candidatura/sportello; "
                    "'fallback_source' = usato source_url come fallback (sconsigliato); "
                    "'missing' = non identificabile (link_candidatura=null)."
                ),
            },
        },
        "required": [
            "slug", "titolo", "descrizione_breve", "contenuto", "livello",
            "allegati", "ente_erogatore", "tematica", "link_candidatura_source",
        ],
    },
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SEO_SYSTEM_PROMPT = """Sei un redattore SEO senior specializzato in bandi pubblici italiani per finanziamenti UE 2021-2027 (FESR, FSE+, Interreg, JTF, PNRR). Il tuo compito e' produrre la scheda editoriale completa di UN bando, basandoti SOLO sui dati forniti (record DB + markdown della pagina).

CONTESTO PIPELINE
I dati che ricevi sono il risultato di tre fasi precedenti:
1. Scraper: titolo_raw, descrizione_raw, raw_data, link_bando.
2. Preprocess: ha validato che e' un bando vero (assumi validita').
3. Enricher: ha estratto FK + junction (tipologia, modalita, programma, beneficiari, regioni, settori, codici_ateco) + 3 date (data_pubblicazione, data_apertura, data_scadenza) con anti-hallucination quote-validated.

Tu NON estrai date (gia' fatte). Tu NON decidi se e' un bando valido (gia' deciso). Tu generi: contenuto editoriale + meta + classificazione qualitativa (livello, tematica, importi, link_candidatura).

CHIAMA IL TOOL save_seo_bando UNA VOLTA con il payload completo.

REGOLE EDITORIALI

1. **Sentence case** ovunque (titolo, H2, descrizione, sezioni). Prima lettera maiuscola; sigle/nomi propri in maiuscolo (PNRR, FESR, FSE, JTF, INPS, ANAS, Lombardia, ecc.).

2. **Titolo (≤80 char)**: comincia con fatto concreto. Esempi:
   - "Aiuti a fondo perduto per startup innovative in Lombardia"
   - "Bando ricerca PNRR 2026 per università del Sud"
   Evita: "Opportunità interessante per...", "Avviso pubblico relativo a..."

3. **descrizione_breve (180-320 char)**: include ente, tipologia, scadenza in formato italiano (es. "30 settembre 2026"). Tono informativo, no marketing.

4. **slug**: kebab-case lowercase, ≤80 char. Rimuovi stopword italiane (di, il, la, lo, le, gli, e, con, per, da, in, su, a, al, alla, dei, del, della, delle, degli). Esempio: "Bando ricerca PNRR 2026 per università del Sud" → "bando-ricerca-pnrr-2026-universita-sud".

5. **Apertura del contenuto** (primi 30 parole): fatto concreto (ente + scadenza + importo o destinatari). Vietate aperture vaghe ("In un contesto di crescente attenzione...", "Nell'ambito delle politiche...").

6. **Blacklist frasi** (case-insensitive, NON usare):
   - "In un contesto di..."
   - "Nell'ambito delle politiche..."
   - "Al fine di promuovere..."
   - "Si rende noto che..."
   - "E' opportuno sottolineare..."
   - "In tale prospettiva..."
   - "Con la presente..."

7. **Link nel contenuto**: SOLO istituzionali (.gov.it, .europa.eu, ec.europa.eu, regione.*, source_url del bando, link_candidatura, PDF ufficiali, .it se ente pubblico). MAI link a testate giornalistiche, blog, sindacati, social.

8. **livello**:
   - **flash_bando** (default): 350-500 parole, 2 sezioni H2: "Chi può candidarsi" e "Come e quando".
   - **guida_bando**: 800-1200 parole, 7-8 sezioni H2 incluse "In breve", "A chi si rivolge", "Cosa finanzia", "Come presentare", "Scadenze", "Errori comuni", "FAQ", chiusura. Usa solo se: regolamento articolato, fasi multiple, FAQ ufficiali nel markdown, importo > 5M€.

9. **contenuto.sections** struttura: ogni sezione e' un oggetto con `type` (h2, paragraph, bullet_list, numbered_list, faq):
   - h2: `{type: "h2", text: "Titolo sezione"}`
   - paragraph: `{type: "paragraph", segments: [{kind: "text", text: "..."}, {kind: "bold", text: "..."}, {kind: "link", text: "...", url: "..."}]}`
   - bullet_list / numbered_list: `{type: "...", items: [{segments: [...]}, ...]}`
   - faq: `{type: "faq", items: [{q: "Domanda?", a: {segments: [...]}}]}`

10. **ente_erogatore**: deve essere visibile nei dati input (titolo_raw, descrizione_raw, raw_data o markdown). Non inventare.

11. **importi**: solo se chiaramente identificabili. Null se non determinabili. Numeri in EURO interi (es. 12500000 per 12,5 milioni).

12. **link_candidatura**: URL al modulo/sportello di candidatura, NON al testo del bando. Esempi validi: bandi.regione.lombardia.it, sportello.servizi.lazio.it, formandoit.it/portale, ecc. Se trovato esplicitamente nel markdown come call-to-action → source='extracted'. Se NON trovi: link_candidatura=null + source='missing'. **MAI fallback a source_url** se non chiaramente indicato come sportello.

13. **tematica**: 1-3 stringhe libere brevi che catturino il dominio (es. "Ricerca e innovazione", "Inclusione sociale", "Transizione digitale", "Agricoltura sostenibile"). NO frasi lunghe.

14. **allegati**: estrai dal markdown TUTTI i link a documenti (.pdf, .doc, .docx, .zip, .xlsx, .xls, .rtf, .odt, .ods) come oggetti {label, url, tipo}. label = testo del link o nome file. url = assoluto. tipo = estensione lowercase.

15. **Date**: NON estrarre. Usa SOLO quelle gia' fornite in input (data_pubblicazione, data_apertura, data_scadenza). Citarle nel contenuto in formato italiano (es. "30 settembre 2026", "20 marzo 2026"). Se null nel input, NON menzionarle.

16. **Stato del bando — MAI in prosa**: il testo resta pubblicato per anni mentre lo stato (aperto/chiuso) cambia alla scadenza; il sito lo mostra gia' con un badge calcolato in tempo reale. NON affermare MAI lo stato corrente in contenuto, descrizione_breve o FAQ: vietate frasi come "attualmente aperto", "il bando e' aperto", "risulta aperto", "ancora aperto", "e' ancora possibile candidarsi", "restano X giorni". Esprimi apertura e chiusura SOLO con date assolute: "le domande possono essere presentate dal 1 marzo 2026 al 30 settembre 2026", "domande entro il 30 settembre 2026".

OUTPUT: chiama il tool save_seo_bando UNA VOLTA con il payload. Niente testo libero prima/dopo."""


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

_SLUG_STOPWORDS = {
    "di", "il", "la", "lo", "le", "gli", "i", "e", "con", "per", "da", "in",
    "su", "a", "al", "alla", "ai", "alle", "agli", "del", "della", "dei",
    "delle", "degli", "dello", "un", "una", "uno", "che", "non", "si", "ci",
    "ne", "se", "ma", "o", "ed", "od",
}

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9-]+")
_SLUG_DUP_DASH_RE = re.compile(r"-+")


def slugify(text: str, max_len: int = 80) -> str:
    """Slugify italiano: lowercase, no accent, no stopword, kebab-case.

    Usato come fallback se la skill emette uno slug non conforme.
    """
    if not text:
        return ""
    # 1. Normalize unicode (rimuovi accenti)
    norm = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in norm if not unicodedata.combining(c))
    # 2. Lowercase
    lower = no_accents.lower()
    # 3. Sostituisci caratteri non validi con dash
    cleaned = _SLUG_INVALID_RE.sub("-", lower)
    # 4. Tokenize + remove stopwords
    tokens = [t for t in cleaned.split("-") if t and t not in _SLUG_STOPWORDS]
    slug = "-".join(tokens)
    # 5. Dedup dash + strip
    slug = _SLUG_DUP_DASH_RE.sub("-", slug).strip("-")
    # 6. Truncate a max_len (al limite di parola)
    if len(slug) > max_len:
        truncated = slug[:max_len]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        slug = truncated
    return slug


async def _resolve_slug_collision(slug: str, bando_id: int, max_attempts: int = 5) -> str | None:
    """Trova uno slug univoco aggiungendo suffissi -2, -3, ...

    Ritorna None se non riesce in max_attempts.
    """
    from .db import slug_exists  # import locale per evitare ciclo

    if not slug_exists(slug, exclude_bando_id=bando_id):
        return slug
    base = slug
    for suffix in range(2, max_attempts + 2):
        candidate = f"{base}-{suffix}"
        if len(candidate) > 80:
            candidate = candidate[:80].rsplit("-", 1)[0] + f"-{suffix}"
        if not slug_exists(candidate, exclude_bando_id=bando_id):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Reachability check
# ---------------------------------------------------------------------------

async def _reachability_check(url: str, timeout_s: float = 5.0) -> bool:
    """HEAD request: True se status < 400. Fallback a GET su 405/403."""
    import httpx

    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            try:
                r = await client.head(url)
                if r.status_code in (405, 403):
                    r = await client.get(url)
                return r.status_code < 400
            except Exception:
                return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = (
    "slug", "titolo", "descrizione_breve", "contenuto", "livello",
    "allegati", "ente_erogatore", "tematica", "link_candidatura_source",
)


async def _validate_payload(
    payload: dict[str, Any],
    bando_id: int,
    input_ctx: dict[str, Any],
    markdown: str,
    reachability_check: bool,
) -> dict[str, Any] | None:
    """Gate Python: ritorna il payload normalizzato o None se invalid.

    Effetti:
      - slug: fallback slugify se invalid + risoluzione collisione UNIQUE.
      - link_candidatura: reachability check (graceful demote a 'missing').
      - ente_erogatore: warning se non substring (no block).
      - lunghezze fuori range: block.
      - allegati: filter url validi, max 20.
    """
    # 1. Required fields
    for f in _REQUIRED_FIELDS:
        if payload.get(f) is None:
            logger.warning("[seo] bando_id={} payload manca campo required '{}'", bando_id, f)
            return None

    # 2. Lunghezze hard
    titolo = (payload.get("titolo") or "").strip()
    if not (1 <= len(titolo) <= 80):
        logger.warning("[seo] bando_id={} titolo lunghezza non valida: {}", bando_id, len(titolo))
        return None
    desc = (payload.get("descrizione_breve") or "").strip()
    if not (180 <= len(desc) <= 320):
        logger.warning(
            "[seo] bando_id={} descrizione_breve lunghezza fuori range (180-320): {}",
            bando_id, len(desc),
        )
        return None
    titolo_breve = payload.get("titolo_breve")
    if titolo_breve and len(titolo_breve) > 100:
        payload["titolo_breve"] = titolo_breve[:100]

    # 3. Enum re-check (tool gia' enforce)
    if payload.get("livello") not in ("flash_bando", "guida_bando"):
        logger.warning("[seo] bando_id={} livello non enum: {!r}", bando_id, payload.get("livello"))
        return None
    if payload.get("link_candidatura_source") not in ("extracted", "fallback_source", "missing"):
        logger.warning(
            "[seo] bando_id={} link_candidatura_source non enum: {!r}",
            bando_id, payload.get("link_candidatura_source"),
        )
        return None

    # 4. Slug: validate + fallback + collision
    raw_slug = (payload.get("slug") or "").strip().lower()
    if not raw_slug or not re.fullmatch(r"[a-z0-9-]+", raw_slug):
        fallback = slugify(titolo)
        if not fallback:
            fallback = f"bando-{bando_id}"
        logger.info("[seo] bando_id={} slug fallback: {!r} -> {!r}", bando_id, raw_slug, fallback)
        raw_slug = fallback
    resolved_slug = await _resolve_slug_collision(raw_slug, bando_id)
    if not resolved_slug:
        logger.warning("[seo] bando_id={} slug collision irrisolvibile: {!r}", bando_id, raw_slug)
        return None
    payload["slug"] = resolved_slug

    # 5. ente_erogatore substring (warning, no block)
    ente = (payload.get("ente_erogatore") or "").strip().lower()
    if ente:
        haystacks = [
            (markdown or "").lower(),
            (input_ctx.get("titolo_raw") or "").lower(),
            (input_ctx.get("descrizione_raw") or "").lower(),
            json.dumps(input_ctx.get("raw_data") or {}, ensure_ascii=False).lower(),
        ]
        if not any(ente in h for h in haystacks):
            logger.warning(
                "[seo] bando_id={} ente_erogatore non substring dei dati input: {!r}",
                bando_id, payload.get("ente_erogatore"),
            )

    # 6. link_candidatura reachability + source coerence
    link_cand = payload.get("link_candidatura")
    source = payload.get("link_candidatura_source")
    if link_cand and source == "extracted" and reachability_check:
        ok = await _reachability_check(link_cand)
        if not ok:
            logger.info(
                "[seo] bando_id={} link_candidatura non raggiungibile, demote a missing: {}",
                bando_id, link_cand,
            )
            payload["link_candidatura"] = None
            payload["link_candidatura_source"] = "missing"

    # 7. allegati: filter validi + max 20
    allegati = payload.get("allegati") or []
    cleaned_allegati = []
    seen_urls: set[str] = set()
    for att in allegati[:50]:
        if not isinstance(att, dict):
            continue
        url = (att.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        cleaned_allegati.append({
            "label": (att.get("label") or "").strip() or url.rsplit("/", 1)[-1],
            "url": url,
            "tipo": (att.get("tipo") or "").lower(),
        })
        if len(cleaned_allegati) >= 20:
            break
    payload["allegati"] = cleaned_allegati

    # 8. tematica: max 5, strip dupes
    tematica = payload.get("tematica") or []
    if not isinstance(tematica, list):
        tematica = []
    seen_temi: set[str] = set()
    cleaned_temi: list[str] = []
    for t in tematica:
        if not isinstance(t, str):
            continue
        t_clean = t.strip()
        if not t_clean or t_clean.lower() in seen_temi:
            continue
        seen_temi.add(t_clean.lower())
        cleaned_temi.append(t_clean)
        if len(cleaned_temi) >= 5:
            break
    payload["tematica"] = cleaned_temi

    # 9. importi: int >= 0 o None
    for k in ("importo_totale_eur", "importo_max_per_progetto_eur"):
        v = payload.get(k)
        if v is None:
            continue
        try:
            iv = int(v)
            if iv < 0:
                payload[k] = None
            else:
                payload[k] = iv
        except (TypeError, ValueError):
            payload[k] = None

    return payload


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_seo_prompt(input_ctx: dict[str, Any], markdown: str) -> str:
    """Compone il prompt user con tutti i dati pre-calcolati + markdown."""
    titolo = _truncate(input_ctx.get("titolo_raw"), 400)
    descrizione = _truncate(input_ctx.get("descrizione_raw"), 1500)
    raw_data_str = _truncate(
        json.dumps(input_ctx.get("raw_data") or {}, ensure_ascii=False, default=str),
        2000,
    )
    md_block = _truncate(markdown, 8000) if markdown else "(markdown non disponibile)"

    # FK
    tipologia = input_ctx.get("tipologia") or "(non classificata)"
    modalita = input_ctx.get("modalita_erogazione") or "(non classificata)"
    programma = input_ctx.get("programma") or "(non identificato)"

    # Junction
    beneficiari = ", ".join(input_ctx.get("beneficiari") or []) or "(nessuno classificato)"
    regioni = ", ".join(input_ctx.get("regioni") or []) or "(nessuna classificata)"
    settori = ", ".join(input_ctx.get("settori") or []) or "(nessuno classificato)"
    ateco_records = input_ctx.get("codici_ateco") or []
    ateco_str = "; ".join(f"{a['codice']}: {a['descrizione']}" for a in ateco_records) or "(nessuno)"

    # Date
    pub = input_ctx.get("data_pubblicazione") or "(non disponibile)"
    apt = input_ctx.get("data_apertura") or "(non disponibile)"
    scad = input_ctx.get("data_scadenza") or "(non disponibile)"

    # Tipo link. NB: stato_bando NON viene passato al modello: il testo
    # generato e' congelato nel DB e lo stato cambia alla scadenza — vedi
    # regola 16 del system prompt (mai affermare lo stato corrente in prosa).
    tipo_link = input_ctx.get("tipo_link") or "(non specificato)"
    link_bando = input_ctx.get("link_bando") or "(nessun link disponibile)"

    return f"""Genera la scheda editoriale del seguente bando.

== DATI ACCUMULATI (scraper + preprocess + enricher) ==

ID interno: {input_ctx.get("id")}
Titolo grezzo (scraper): {titolo or "(vuoto)"}
Descrizione grezza (scraper): {descrizione or "(vuota)"}
Link bando: {link_bando}
Tipo link: {tipo_link}

DATE (gia' estratte e validate dall'enricher v7):
- data_pubblicazione: {pub}
- data_apertura: {apt}
- data_scadenza: {scad}

CLASSIFICAZIONE (gia' fatta dall'enricher v7):
- Tipologia: {tipologia}
- Modalita' erogazione: {modalita}
- Programma: {programma}
- Beneficiari: {beneficiari}
- Regioni coperte: {regioni}
- Settori intervento: {settori}
- Codici ATECO: {ateco_str}

RAW_DATA (metadata scraper, JSONB):
{raw_data_str or "(vuoto)"}

== MARKDOWN PAGINA UFFICIALE (Firecrawl) ==

{md_block}

== ISTRUZIONI ==

1. Costruisci ente_erogatore, area_geografica, tematica, importi, link_candidatura, allegati ATTRAVERSO ANALISI dei dati sopra. NON inventare.
2. Scrivi contenuto editoriale (`contenuto.sections`) seguendo il livello scelto: flash_bando (350-500 parole, 2 H2) o guida_bando (800-1200 parole, 7-8 H2 + FAQ).
3. Cita le date in formato italiano (es. "30 settembre 2026") nel contenuto. Le date sono affidabili (gia' validate substring + source autoritativo).
4. Slug kebab-case ≤80 char, no stopword italiane.
5. Titolo ≤80 char, sentence case, fatto concreto in apertura.

Chiama il tool save_seo_bando con il payload completo."""


# ---------------------------------------------------------------------------
# Retry helper (riusa pattern enricher)
# ---------------------------------------------------------------------------

async def _call_anthropic_tool(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str, tool: dict,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    """Anthropic call con tool use forzato + retry exponential."""
    import anthropic
    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool["name"]:
                    return dict(block.input)
            return None
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[seo] API status {} non retryabile: {}", status, e)
                return None
            sleep_s = (2 ** attempt) * 2 + random.uniform(0, 1)
            logger.warning(
                "[seo] retry {}/{} dopo {}: sleep {:.1f}s",
                attempt + 1, max_retries, type(e).__name__, sleep_s,
            )
            await asyncio.sleep(sleep_s)
        except Exception as e:
            logger.exception("[seo] errore inatteso: {}", e)
            return None
    return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def enrich_seo(
    input_ctx: dict[str, Any],
    markdown: str,
) -> dict[str, Any] | None:
    """Esegue 1 LLM call Opus + validation. Ritorna payload validato o None."""
    bando_id = input_ctx["id"]
    settings = get_settings()
    client = _get_anthropic_client()

    raw_payload = await _call_anthropic_tool(
        client,
        model=settings.seo_model,
        max_tokens=settings.seo_max_tokens,
        system=SEO_SYSTEM_PROMPT,
        user_prompt=_build_seo_prompt(input_ctx, markdown),
        tool=SAVE_SEO_BANDO_TOOL,
    )
    if not raw_payload:
        logger.warning("[seo] bando_id={} LLM call fallita/vuota", bando_id)
        return None

    validated = await _validate_payload(
        raw_payload, bando_id, input_ctx, markdown,
        reachability_check=settings.seo_reachability_check,
    )
    if not validated:
        return None

    logger.debug(
        "[seo] bando_id={} OK livello={} slug={} ente={} importo={}",
        bando_id, validated.get("livello"), validated.get("slug"),
        validated.get("ente_erogatore"), validated.get("importo_totale_eur"),
    )
    return validated
