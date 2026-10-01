"""Skill SEO (step v8): enriched -> completed.

Single LLM call Claude Opus 4.7 + tool use `save_seo_bando`. Genera
contenuto editoriale + meta per ogni bando già arricchito da preprocess
+ enricher v7. Output: 14 campi che vanno direttamente in tabella `bando`.

NESSUN side effect su FK/junction/date (già coperte dall'enricher).
NESSUNA decisione di validità (già fatta dal preprocess).
NESSUN verifier post-call (le date sono già validate; campi editoriali
sono opinionali).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import unicodedata
from typing import Any, Iterable, Mapping

from . import bilancio
from .impronte import normalizza_url
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

SEO_SYSTEM_PROMPT = """Sei un redattore SEO senior specializzato in bandi pubblici italiani per finanziamenti UE 2021-2027 (FESR, FSE+, Interreg, JTF, PNRR). Il tuo compito è produrre la scheda editoriale completa di UN bando, basandoti SOLO sui dati forniti (record DB + markdown della pagina).

CONTESTO PIPELINE
I dati che ricevi sono il risultato di tre fasi precedenti:
1. Scraper: titolo_raw, descrizione_raw, raw_data, link_bando.
2. Preprocess: ha validato che è un bando vero (assumi validità).
3. Enricher: ha estratto FK + junction (tipologia, modalità, programma, beneficiari, regioni, settori, codici_ateco) + 3 date (data_pubblicazione, data_apertura, data_scadenza) con anti-hallucination quote-validated.

Tu NON estrai date (già fatte). Tu NON decidi se è un bando valido (già deciso). Tu generi: contenuto editoriale + meta + classificazione qualitativa (livello, tematica, importi, link_candidatura).

CHIAMA IL TOOL save_seo_bando UNA VOLTA con il payload completo.

REGOLE EDITORIALI

1. **Sentence case** ovunque (titolo, H2, descrizione, sezioni). Prima lettera maiuscola; sigle/nomi propri in maiuscolo (PNRR, FESR, FSE, JTF, INPS, ANAS, Lombardia, ecc.).

2. **Titolo (≤80 char)**: massimo 80 caratteri contati, spazi compresi: un titolo più lungo viene rifiutato e dovrai riscriverlo. Comincia con fatto concreto. Esempi:
   - "Aiuti a fondo perduto per startup innovative in Lombardia"
   - "Bando ricerca PNRR 2026 per università del Sud"
   Evita: "Opportunità interessante per...", "Avviso pubblico relativo a..."

3. **descrizione_breve (180-320 char)**: include ente, tipologia, scadenza in formato italiano (es. "30 settembre 2026"). Tono informativo, no marketing.

4. **slug**: kebab-case lowercase, ≤80 char. Rimuovi stopword italiane (di, il, la, lo, le, gli, e, con, per, da, in, su, a, al, alla, dei, del, della, delle, degli). Esempio: "Bando ricerca PNRR 2026 per università del Sud" → "bando-ricerca-pnrr-2026-università-sud".

5. **Apertura del contenuto** (primi 30 parole): fatto concreto (ente + scadenza + importo o destinatari). Vietate aperture vaghe ("In un contesto di crescente attenzione...", "Nell'ambito delle politiche...").

6. **Blacklist frasi** (case-insensitive, NON usare):
   - "In un contesto di..."
   - "Nell'ambito delle politiche..."
   - "Al fine di promuovere..."
   - "Si rende noto che..."
   - "È opportuno sottolineare..."
   - "In tale prospettiva..."
   - "Con la presente..."

7. **Link nel contenuto**: SOLO istituzionali (.gov.it, .europa.eu, ec.europa.eu, regione.*, source_url del bando, link_candidatura, PDF ufficiali, .it se ente pubblico). MAI link a testate giornalistiche, blog, sindacati, social.

8. **livello**:
   - **flash_bando** (default): 350-500 parole, 2 sezioni H2: "Chi può candidarsi" e "Come e quando".
   - **guida_bando**: 800-1200 parole, 7-8 sezioni H2 incluse "In breve", "A chi si rivolge", "Cosa finanzia", "Come presentare", "Scadenze", "Errori comuni" (solo alle condizioni della regola 18), "FAQ", chiusura. Usa solo se: regolamento articolato, fasi multiple, FAQ ufficiali nel markdown, importo > 5M€.

9. **contenuto.sections** struttura: ogni sezione è un oggetto con `type` (h2, paragraph, bullet_list, numbered_list, faq):
   - h2: `{type: "h2", text: "Titolo sezione"}`
   - paragraph: `{type: "paragraph", segments: [{kind: "text", text: "..."}, {kind: "bold", text: "..."}, {kind: "link", text: "...", url: "..."}]}`
   - bullet_list / numbered_list: `{type: "...", items: [{segments: [...]}, ...]}`
   - faq: `{type: "faq", items: [{q: "Domanda?", a: {segments: [...]}}]}`

10. **ente_erogatore**: deve essere visibile nei dati input (titolo_raw, descrizione_raw, raw_data o markdown). Non inventare.

11. **importi**: solo se chiaramente identificabili. Null se non determinabili. Numeri in EURO interi (es. 12500000 per 12,5 milioni).

12. **link_candidatura**: URL al modulo/sportello di candidatura, NON al testo del bando. Esempi validi: bandi.regione.lombardia.it, sportello.servizi.lazio.it, formandoit.it/portale, ecc. Se trovato esplicitamente nel markdown come call-to-action → source='extracted'. Se NON trovi: link_candidatura=null + source='missing'. **MAI fallback a source_url** se non chiaramente indicato come sportello.

13. **tematica**: 1-3 stringhe libere brevi che catturino il dominio (es. "Ricerca e innovazione", "Inclusione sociale", "Transizione digitale", "Agricoltura sostenibile"). NO frasi lunghe.

14. **allegati**: estrai dal markdown TUTTI i link a documenti (.pdf, .doc, .docx, .zip, .xlsx, .xls, .rtf, .odt, .ods) come oggetti {label, url, tipo}. label = testo del link o nome file. url = assoluto. tipo = estensione lowercase.

15. **Date**: NON estrarre. Usa SOLO quelle già fornite in input (data_pubblicazione, data_apertura, data_scadenza). Citarle nel contenuto in formato italiano (es. "30 settembre 2026", "20 marzo 2026"). Se null nel input, NON menzionarle.

16. **Stato del bando — MAI in prosa**: il testo resta pubblicato per anni mentre lo stato (aperto/chiuso) cambia alla scadenza; il sito lo mostra già con un badge calcolato in tempo reale. NON affermare MAI lo stato corrente in contenuto, descrizione_breve o FAQ: vietate frasi come "attualmente aperto", "il bando è aperto", "risulta aperto", "ancora aperto", "è ancora possibile candidarsi", "restano X giorni". Esprimi apertura e chiusura SOLO con date assolute: "le domande possono essere presentate dal 1 marzo 2026 al 30 settembre 2026", "domande entro il 30 settembre 2026".

17. **Accenti italiani**: scrivi "è", "à", "ù", "ò", "ì", "é" con l'accento vero. Mai la vocale nuda al loro posto ("universita", "puo", "gia", "piu", "perche", "modalita") e mai l'apostrofo come accento ("e'", "citta'", "sara'", "validita'"). Vale in ogni campo del payload: titolo, descrizione_breve, contenuto, meta e FAQ.

18. **Chi partecipa e a quali condizioni: solo ciò che dice la fonte.** Beneficiari, forme di partecipazione ("in forma singola o associata", reti di imprese, aggregazioni, partenariati, ATI/ATS/RTI, consorzi, capofila), requisiti (sede, anzianità, dimensione, fatturato, codici ATECO), esclusioni e vincoli (numero minimo di partner, cumulabilità, cofinanziamento) si scrivono SOLO se si leggono nel MARKDOWN o nella CLASSIFICAZIONE (beneficiari, regioni, settori, ATECO). Se la fonte non dice niente, il testo non dice niente: vietate le formule di completamento ("in forma singola o associata", "anche in forma aggregata", "reti di imprese e aggregazioni", "in possesso dei requisiti previsti"). Quando la fonte prevede una forma di partecipazione, riportala con le sue parole (es. "almeno due partner, di cui uno capofila").
   - "Chi può candidarsi" e "A chi si rivolge" elencano i beneficiari della classificazione e quelli scritti nel markdown, nient'altro. Se mancano i dettagli, rimanda all'avviso ufficiale senza anticiparli.
   - "Errori comuni" solo se ogni errore discende da un requisito esplicito della fonte; altrimenti la sezione si omette.
   - Con il testo dell'aggregatore (intestazione "TESTO DELL'AGGREGATORE") la fonte è povera: scrivi meno, non di più.

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

async def _reachability_check(
    url: str,
    timeout_s: float = 5.0,
    *,
    pubblico: Any = None,
    transport: Any = None,
) -> bool:
    """HEAD request: True se status < 400. Fallback a GET su 405/403.

    Il `link_candidatura` lo sceglie il modello (contratto `bandi-giro-3`
    §19.6): l'URL di partenza e ogni `Location` dei redirect passano dalla
    guardia sugli indirizzi (`http.indirizzo_pubblico_async`) PRIMA della
    richiesta, e i redirect si seguono a mano. Un host interno vale «non
    raggiungibile» (il link si declassa a `missing`). `pubblico` (un DNS finto)
    e `transport` (una rete finta) sono per i test.
    """
    import httpx

    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False,
                                     transport=transport) as client:
            try:
                r = await _richiesta_guardata(client, "HEAD", url, pubblico)
                if r is not None and r.status_code in (405, 403):
                    r = await _richiesta_guardata(client, "GET", url, pubblico)
                return r is not None and r.status_code < 400
            except Exception:
                return False
    except Exception:
        return False


#: Salti massimi dei redirect seguiti a mano (quelli di httpx per difetto).
MAX_REDIRECT_LINK = 20


async def _indirizzo_ammesso(url: str, pubblico: Any = None) -> bool:
    """La guardia sugli indirizzi interni (§18.6). Nel dubbio no."""
    try:
        if pubblico is not None:
            return bool(await pubblico(url))
        from . import http as http_mod
        return bool(await http_mod.indirizzo_pubblico_async(url))
    except Exception as e:
        logger.debug("[seo] guardia sugli indirizzi fallita: {}", type(e).__name__)
        return False


async def _richiesta_guardata(client: Any, metodo: str, url: str, pubblico: Any = None) -> Any:
    """`metodo` su `url` con i redirect seguiti a mano, la guardia su ogni salto.

    None se un salto porta a un host non pubblico (la richiesta non parte) o se
    i salti superano `MAX_REDIRECT_LINK`. Il corpo non si legge: serve lo stato.
    """
    corrente = url
    for _ in range(MAX_REDIRECT_LINK + 1):
        if not await _indirizzo_ammesso(corrente, pubblico):
            logger.info("[seo] link_candidatura: host non pubblico, nessuna richiesta")
            return None
        risposta = await client.send(client.build_request(metodo, corrente), stream=True)
        try:
            prossima = risposta.next_request
        finally:
            await risposta.aclose()
        if prossima is None:
            return risposta
        metodo = prossima.method
        corrente = str(prossima.url)
    return None


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = (
    "slug", "titolo", "descrizione_breve", "contenuto", "livello",
    "allegati", "ente_erogatore", "tematica", "link_candidatura_source",
)


# ---------------------------------------------------------------------------
# Gate sugli URL del contenuto (piano §5, «gate anti-allucinazione»)
# ---------------------------------------------------------------------------
#
# Il modello scrive i segmenti `link` del `contenuto` guardando il markdown
# della pagina: puo' quindi produrre un URL plausibile che nessuno ha mai
# scaricato, oppure ricopiare un link verso l'aggregatore. §5 chiude la porta
# con un'appartenenza, non con un giudizio: **ogni URL di un segmento `link`
# deve stare nell'unione fra fonte ufficiale, allegati ammessi e `bando_link`
# pubblicabili**, altrimenti il segmento viene degradato a testo (il testo
# resta, sparisce solo il collegamento).
#
# `ammessi=None` significa «nessun elenco disponibile»: il gate non si applica
# e vale il comportamento di prima. Un insieme **vuoto** e' invece una
# risposta: nessun URL e' provato, quindi nessun link va pubblicato. Tenere
# distinti i due casi e' cio' che permette di attivare il gate un pezzo alla
# volta senza spegnere i link di tutto l'archivio al primo rilascio.


def normalizza_ammessi(urls: Iterable[str] | None) -> frozenset[str] | None:
    """Gli URL ammessi in forma normalizzata, o None se l'elenco non c'e'."""
    if urls is None:
        return None
    normalizzati = (normalizza_url(str(u)) for u in urls if u)
    return frozenset(u for u in normalizzati if u)


def _url_ammesso(url: Any, ammessi: frozenset[str]) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    normalizzato = normalizza_url(url)
    return bool(normalizzato) and normalizzato in ammessi


def degrada_link_non_ammessi(
    contenuto: Any, ammessi: frozenset[str] | None,
) -> tuple[Any, int]:
    """(contenuto ripulito, quanti segmenti degradati).

    La visita e' generica — dizionari e liste, a qualunque profondita' — perche'
    i segmenti `link` compaiono nei paragrafi, negli `items` degli elenchi e
    nelle risposte delle FAQ: elencare i contenitori significherebbe dimenticarne
    uno alla prossima forma di sezione.
    """
    if ammessi is None:
        return contenuto, 0
    degradati = 0

    def visita(nodo: Any) -> Any:
        nonlocal degradati
        if isinstance(nodo, Mapping):
            if nodo.get("kind") == "link" and not _url_ammesso(nodo.get("url"), ammessi):
                degradati += 1
                testo = nodo.get("text") or nodo.get("url") or ""
                return {"kind": "text", "text": str(testo)}
            return {chiave: visita(valore) for chiave, valore in nodo.items()}
        if isinstance(nodo, list):
            return [visita(valore) for valore in nodo]
        return nodo

    return visita(contenuto), degradati


def filtra_allegati(
    allegati: Any, ammessi: frozenset[str] | None,
) -> tuple[list[dict[str, str]], int]:
    """Intersezione con gli allegati verificati da `allegati.py` (§5, §13.4).

    Il modello «estrae dal markdown tutti i link a documenti»: qui restano solo
    quelli che hanno risposto 2xx e che compaiono nell'HTML della pagina di
    riferimento. E' la promessa di §13.4, che un LLM non puo' mantenere.
    """
    righe = [a for a in (allegati or []) if isinstance(a, dict)]
    if ammessi is None:
        return righe, 0
    tenuti = [a for a in righe if _url_ammesso(a.get("url"), ammessi)]
    return tenuti, len(righe) - len(tenuti)


# ---------------------------------------------------------------------------
# Affermazioni non sostenute dalla fonte (contratto di ottobre, §7)
# ---------------------------------------------------------------------------
#
# Il 29/09 BandoFit ha segnalato tre schede con forme di partecipazione che
# l'atto dell'ente non prevede (18145, 18278, 171905), e il controllo del giro
# delle 12 ne ha trovate altre otto. Nove di quegli undici bandi non hanno
# ancora oggi una fonte ufficiale: il modello ha letto la scheda
# dell'aggregatore e ha riempito «Chi può candidarsi» con formule di
# completamento. La regola 18 del prompt lo vieta; questo controllo misura se
# il modello l'ha rispettata.
#
# Copre solo le forme di partecipazione, perche' sono formule riconoscibili e
# la loro presenza nella fonte si verifica con una ricerca. Requisiti e
# beneficiari in generale no: «sede in Sicilia da almeno tre anni» non ha una
# forma fissa, e per loro resta il prompt.
#
# Ogni famiglia ha due espressioni: quella che la riconosce nel testo generato
# e quella, piu' larga, che la trova sostenuta nella fonte. Nel dubbio vince la
# fonte: un falso «sostenuta» lascia passare una frase, un falso «non
# sostenuta» farebbe riscrivere una scheda giusta.

_I = re.IGNORECASE
_SIGLE_RAGGRUPPAMENTO = r"(?-i:\b(?:ATI|ATS|RTI|RTS)\b)"

FAMIGLIE_PARTECIPAZIONE: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "forma singola o associata",
        re.compile(
            r"\bforma\s+(?:singola\s+o\s+)?associata\b|\bsingol[aoie]\s+o\s+associat[aoie]\b"
            r"|\bforma\s+(?:aggregata|congiunta)\b", _I),
        re.compile(
            r"\bassociat[aoie]\b|\bforma\s+(?:aggregata|congiunta)\b|\baggregazion"
            r"|\braggruppament", _I),
    ),
    (
        "reti di imprese",
        re.compile(
            r"\bret[ei]\s+(?:di\s+)?impres[ae]\b|\bcontratt[oi]\s+di\s+rete\b"
            r"|\bret[ei]-(?:soggetto|contratto)\b", _I),
        re.compile(
            r"\bret[ei]\s+(?:di\s+)?impres|\bcontratt[oi]\s+di\s+rete\b"
            r"|\bret[ei]-(?:soggetto|contratto)\b", _I),
    ),
    (
        "aggregazioni",
        re.compile(r"\baggregazion[ei]\b", _I),
        re.compile(
            r"\baggregazion|\baggregat[aoie]\b|\braggruppament"
            r"|\bassociazion[ei]\s+temporane", _I),
    ),
    (
        "partenariati",
        re.compile(r"\bpartenariat[oi]\b|\bpartner(?:ship)?\b", _I),
        re.compile(
            r"\bpartenariat|\bpartner|\bcapofila\b|\braggruppament|\baggregazion", _I),
    ),
    (
        "raggruppamenti temporanei",
        re.compile(
            r"\braggruppament[oi]\s+temporane[oi]\b|\bassociazion[ei]\s+temporane[ae]\b|"
            + _SIGLE_RAGGRUPPAMENTO, _I),
        re.compile(
            r"\braggruppament|\bassociazion[ei]\s+temporane|" + _SIGLE_RAGGRUPPAMENTO, _I),
    ),
    (
        "consorzi",
        re.compile(r"\bconsorzi[oa]?\b", _I),
        re.compile(r"\bconsorzi", _I),
    ),
    (
        "capofila",
        re.compile(r"\bcapofila\b|\bmandatari[oa]\b", _I),
        re.compile(r"\bcapofila\b|\bmandatari", _I),
    ),
)

_SPAZI_RE = re.compile(r"\s+")


def _spazi(testo: Any) -> str:
    """Spazi (anche NBSP e a capo) ridotti a uno: il markdown ne e' pieno."""
    return _SPAZI_RE.sub(" ", str(testo or ""))


def affermazioni_non_sostenute(testo: str, fonte: str) -> tuple[tuple[str, str], ...]:
    """(famiglia, parole trovate) per ogni forma di partecipazione affermata in
    `testo` e assente dalla `fonte`. Vuota se il testo non ne afferma.

    `testo` e' cio' che il modello ha scritto (descrizione e contenuto, vedi
    `testo_del_contenuto`), `fonte` cio' che ha letto (`fonte_del_bando`).
    """
    testo, fonte = _spazi(testo), _spazi(fonte)
    esito: list[tuple[str, str]] = []
    for famiglia, nel_testo, nella_fonte in FAMIGLIE_PARTECIPAZIONE:
        trovata = nel_testo.search(testo)
        if trovata and not nella_fonte.search(fonte):
            esito.append((famiglia, trovata.group(0)))
    return tuple(esito)


def testo_del_contenuto(contenuto: Any) -> str:
    """Il testo leggibile di un `contenuto` (dict, o JSON salvato come stringa).

    Si raccolgono le chiavi `text` (titoli e segmenti) e `q` (domande delle
    FAQ), a qualunque profondita'; gli URL dei segmenti `link` restano fuori.
    Una stringa che non e' JSON e' gia' testo.
    """
    if isinstance(contenuto, str):
        try:
            contenuto = json.loads(contenuto)
        except ValueError:
            return contenuto
    pezzi: list[str] = []

    def visita(nodo: Any) -> None:
        if isinstance(nodo, Mapping):
            for chiave, valore in nodo.items():
                if chiave in ("text", "q") and isinstance(valore, str):
                    pezzi.append(valore)
                else:
                    visita(valore)
        elif isinstance(nodo, list):
            for valore in nodo:
                visita(valore)

    visita(contenuto)
    return " ".join(pezzi)


def fonte_del_bando(input_ctx: Mapping[str, Any], markdown: str = "") -> str:
    """Tutto cio' che il modello legge su un bando: campi grezzi dello scraper,
    classificazione dell'enricher (i «cataloghi collegati» del §7) e testo della
    pagina. E' il termine di paragone di `affermazioni_non_sostenute`."""
    ateco = " ".join(
        str(a.get("descrizione") or "") for a in (input_ctx.get("codici_ateco") or [])
        if isinstance(a, Mapping)
    )
    pezzi = [
        input_ctx.get("titolo_raw"),
        input_ctx.get("descrizione_raw"),
        json.dumps(input_ctx.get("raw_data") or {}, ensure_ascii=False, default=str),
        input_ctx.get("tipologia"),
        input_ctx.get("modalita_erogazione"),
        input_ctx.get("programma"),
        " ".join(input_ctx.get("beneficiari") or []),
        " ".join(input_ctx.get("regioni") or []),
        " ".join(input_ctx.get("settori") or []),
        ateco,
        markdown,
    ]
    return " ".join(str(p) for p in pezzi if p)


def affermazioni_del_payload(
    payload: Mapping[str, Any], input_ctx: Mapping[str, Any], markdown: str = "",
) -> tuple[tuple[str, str], ...]:
    """`affermazioni_non_sostenute` su descrizione breve e contenuto di un payload."""
    testo = " ".join((
        str(payload.get("descrizione_breve") or ""),
        testo_del_contenuto(payload.get("contenuto")),
    ))
    return affermazioni_non_sostenute(testo, fonte_del_bando(input_ctx, markdown))


# ---------------------------------------------------------------------------
# Lunghezze (contratto di ottobre, T-C2)
# ---------------------------------------------------------------------------
#
# Il bando 772894 e' rimasto `enriched` dal 22/08: a ogni giro Opus scriveva un
# titolo di 88 caratteri («Contributi a fondo perduto per
# l'internazionalizzazione delle imprese di Pistoia e Prato») e il gate
# buttava l'intero payload, gia' pagato. Dal 23/09 sono circa 26 chiamate. Il
# modello scrive fino al limite: dei 2 186 titoli completati, 467 hanno 75-80
# caratteri.
#
# Il TITOLO non si taglia mai a macchina: alla pubblicazione si congela (anche
# per lo slug e per BandoFit), e «…delle imprese di Pistoia» senza «e Prato» e'
# un titolo sbagliato per sempre (revisione #25). Sui non pubblicati, oltre 80
# caratteri (`sistema_titolo`): prima il `titolo_breve` del payload se sta in
# 80, poi UNA richiamata al modello per il solo titolo, con il motivo scritto,
# poi lo scarto con motivo. La DESCRIZIONE breve invece si accorcia (ultima
# frase intera): non e' congelata e non porta lo slug.
#
# Solo sui NON pubblicati: il titolo di un pubblicato non si scrive mai, e la
# sua descrizione non si accorcia senza che nessuno l'abbia letta.

TITOLO_MAX = 80
DESCRIZIONE_MIN = 180
DESCRIZIONE_MAX = 320

#: Parole che non possono chiudere un titolo o una frase tagliata.
_CONNETTIVI_CODA = frozenset({
    "di", "del", "dello", "della", "dei", "degli", "delle", "e", "ed", "o", "od",
    "per", "a", "al", "allo", "alla", "ai", "agli", "alle", "in", "nel", "nello",
    "nella", "nei", "negli", "nelle", "con", "su", "sul", "sullo", "sulla", "sui",
    "sugli", "sulle", "da", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "tra", "fra", "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "che",
})
_PUNTEGGIATURA_CODA = " ,;:–—-(/"


def _parole_entro(testo: str, massimo: int) -> str:
    """Le parole intere di `testo` che stanno in `massimo` caratteri, senza
    connettivi ne' punteggiatura in coda. Vuoto se nemmeno la prima ci sta."""
    scelte: list[str] = []
    for parola in testo.split():
        if len(" ".join(scelte + [parola])) > massimo:
            break
        scelte.append(parola)
    while scelte and (
        scelte[-1].lower().strip(",;:") in _CONNETTIVI_CODA
        or not scelte[-1].strip(_PUNTEGGIATURA_CODA)
    ):
        scelte.pop()
    return " ".join(scelte).rstrip(_PUNTEGGIATURA_CODA)


def accorcia_descrizione(
    testo: str, massimo: int = DESCRIZIONE_MAX, minimo: int = DESCRIZIONE_MIN,
) -> str:
    """La descrizione entro `massimo` caratteri.

    Prima scelta l'ultima frase intera che ci sta, se ne restano almeno
    `minimo`; altrimenti l'ultima parola intera piu' «…». Un punto seguito da
    una cifra («1.500 euro») non chiude una frase.
    """
    testo = " ".join(str(testo or "").split())
    if len(testo) <= massimo:
        return testo
    fine_frase = max(
        (i + 1 for i, c in enumerate(testo[:massimo])
         if c in ".!?" and (i + 1 == len(testo) or testo[i + 1] == " ")),
        default=0,
    )
    if fine_frase >= minimo:
        return testo[:fine_frase]
    return (_parole_entro(testo, massimo - 1) or testo[:massimo - 1]) + "…"


def _scarta(diagnosi: dict[str, Any] | None, motivo: str) -> None:
    """Annota perche' il payload e' stato scartato (lo legge `pipeline_run`)."""
    if diagnosi is not None:
        diagnosi["motivo"] = motivo


async def _validate_payload(
    payload: dict[str, Any],
    bando_id: int,
    input_ctx: dict[str, Any],
    markdown: str,
    reachability_check: bool,
    *,
    link_ammessi: Iterable[str] | None = None,
    allegati_ammessi: Iterable[str] | None = None,
    ripara_lunghezze: bool = False,
    titolo_congelato: bool = False,
    descrizione_facoltativa: bool = False,
    diagnosi: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Gate Python: ritorna il payload normalizzato o None se invalid.

    Effetti:
      - slug: fallback slugify se invalid + risoluzione collisione UNIQUE.
      - link_candidatura: reachability check (graceful demote a 'missing').
      - ente_erogatore: warning se non substring (no block).
      - lunghezze fuori range: block; con `ripara_lunghezze` (bandi non
        pubblicati) una descrizione troppo lunga si accorcia invece. Il titolo
        no: lo sistema `sistema_titolo` prima di arrivare qui.
        Con `titolo_congelato` (pubblicati: rerun dei completed e
        `seo-rigenera`) il titolo non si controlla affatto, perche' non verra'
        scritto: scartare per lui buttava una chiamata pagata. Con
        `descrizione_facoltativa` (solo `seo-rigenera`, che la descrizione la
        riscrive soltanto se la vecchia e' segnalata) la lunghezza della
        descrizione non scarta il payload: la giudica il chiamante, se e
        quando la usa.
      - allegati: filter url validi, max 20, poi intersezione con
        `allegati_ammessi` (§5: solo i documenti verificati 2xx).
      - contenuto: ogni segmento `link` il cui URL non sta in `link_ammessi`
        viene degradato a testo (§5, gate anti-allucinazione).

    `link_ammessi`/`allegati_ammessi` a None disattivano i due gate: e' il caso
    del bando che il resolver non ha ancora visto. In `diagnosi["motivo"]`
    finisce la ragione dello scarto.
    """
    # 1. Required fields
    for f in _REQUIRED_FIELDS:
        if payload.get(f) is None:
            logger.warning("[seo] bando_id={} payload manca campo required '{}'", bando_id, f)
            _scarta(diagnosi, f"campo mancante: {f}")
            return None

    # 2. Lunghezze hard
    titolo = (payload.get("titolo") or "").strip()
    if not titolo_congelato and not (1 <= len(titolo) <= TITOLO_MAX):
        logger.warning("[seo] bando_id={} titolo lunghezza non valida: {}", bando_id, len(titolo))
        _scarta(diagnosi, f"titolo {len(titolo)} caratteri (1-{TITOLO_MAX})")
        return None
    desc = (payload.get("descrizione_breve") or "").strip()
    if ripara_lunghezze and len(desc) > DESCRIZIONE_MAX:
        corta = accorcia_descrizione(desc)
        logger.info("[seo] bando_id={} descrizione_breve accorciata ({} -> {})",
                    bando_id, len(desc), len(corta))
        desc = payload["descrizione_breve"] = corta
    if not descrizione_facoltativa and not (DESCRIZIONE_MIN <= len(desc) <= DESCRIZIONE_MAX):
        logger.warning(
            "[seo] bando_id={} descrizione_breve lunghezza fuori range (180-320): {}",
            bando_id, len(desc),
        )
        _scarta(diagnosi, f"descrizione_breve {len(desc)} caratteri "
                          f"({DESCRIZIONE_MIN}-{DESCRIZIONE_MAX})")
        return None
    titolo_breve = payload.get("titolo_breve")
    if titolo_breve and len(titolo_breve) > 100:
        payload["titolo_breve"] = titolo_breve[:100]

    # 3. Enum re-check (tool gia' enforce)
    if payload.get("livello") not in ("flash_bando", "guida_bando"):
        logger.warning("[seo] bando_id={} livello non enum: {!r}", bando_id, payload.get("livello"))
        _scarta(diagnosi, f"livello non valido: {payload.get('livello')!r}")
        return None
    if payload.get("link_candidatura_source") not in ("extracted", "fallback_source", "missing"):
        logger.warning(
            "[seo] bando_id={} link_candidatura_source non enum: {!r}",
            bando_id, payload.get("link_candidatura_source"),
        )
        _scarta(diagnosi, "link_candidatura_source non valido: "
                          f"{payload.get('link_candidatura_source')!r}")
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
        _scarta(diagnosi, f"slug in collisione: {raw_slug}")
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

    # 7. allegati: filter validi + max 20 (poi l'intersezione al punto 10)
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

    # 10. Gate degli URL (§5). Va per ultimo, dopo che allegati e contenuto
    # sono gia' normalizzati: degradare un segmento prima della normalizzazione
    # lo rimetterebbe in gioco al passo successivo.
    ammessi_link = normalizza_ammessi(link_ammessi)
    ammessi_allegati = normalizza_ammessi(allegati_ammessi)
    payload["allegati"], scartati = filtra_allegati(payload.get("allegati"), ammessi_allegati)
    if scartati:
        logger.info(
            "[seo] bando_id={} {} allegati non verificati scartati dal gate", bando_id, scartati,
        )
    payload["contenuto"], degradati = degrada_link_non_ammessi(
        payload.get("contenuto"), ammessi_link,
    )
    if degradati:
        logger.info(
            "[seo] bando_id={} {} link del contenuto degradati a testo (URL non provato)",
            bando_id, degradati,
        )

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
    novita = blocco_novita(input_ctx.get("novita"))

    return f"""Genera la scheda editoriale del seguente bando.

== DATI ACCUMULATI (scraper + preprocess + enricher) ==

ID interno: {input_ctx.get("id")}
Titolo grezzo (scraper): {titolo or "(vuoto)"}
Descrizione grezza (scraper): {descrizione or "(vuota)"}
Link bando: {link_bando}
Tipo link: {tipo_link}

DATE (già estratte e validate dall'enricher v7):
- data_pubblicazione: {pub}
- data_apertura: {apt}
- data_scadenza: {scad}

CLASSIFICAZIONE (già fatta dall'enricher v7):
- Tipologia: {tipologia}
- Modalità erogazione: {modalita}
- Programma: {programma}
- Beneficiari: {beneficiari}
- Regioni coperte: {regioni}
- Settori intervento: {settori}
- Codici ATECO: {ateco_str}

RAW_DATA (metadata scraper, JSONB):
{raw_data_str or "(vuoto)"}

{novita}== MARKDOWN PAGINA UFFICIALE (Firecrawl) ==

{md_block}

== ISTRUZIONI ==

1. Costruisci ente_erogatore, area_geografica, tematica, importi, link_candidatura, allegati ATTRAVERSO ANALISI dei dati sopra. NON inventare.
2. Scrivi contenuto editoriale (`contenuto.sections`) seguendo il livello scelto: flash_bando (350-500 parole, 2 H2) o guida_bando (800-1200 parole, 7-8 H2 + FAQ).
3. Cita le date in formato italiano (es. "30 settembre 2026") nel contenuto. Le date sono affidabili (già validate substring + source autoritativo).
4. Slug kebab-case ≤80 char, no stopword italiane.
5. Titolo ≤80 char, sentence case, fatto concreto in apertura.
6. Chi può partecipare, in quale forma e con quali requisiti: solo ciò che si legge nel markdown o nella classificazione (regola 18). Se la fonte tace, il testo tace.

Chiama il tool save_seo_bando con il payload completo."""


#: Quante novita' e quanti caratteri per citazione entrano nel prompt.
MAX_NOVITA = 10
MAX_CITAZIONE_NOVITA = 400


def blocco_novita(novita: Any) -> str:
    """Il blocco «novita' pubblicate dall'ente» del prompt (giro 3, §6). Puro.

    Lo usa la riscrittura di una scheda gia' pubblicata dopo un evento (faq,
    graduatoria, esito, rettifica di contenuto o allegati, o una data che la
    sostituzione senza modello non ha saputo riallineare). Senza novita' il
    prompt resta identico a quello di sempre: stringa vuota. L'URL della prova
    entra come testo, non come link: il gate dei link resta quello del payload.
    """
    if not isinstance(novita, (list, tuple)) or not novita:
        return ""
    righe: list[str] = []
    for voce in list(novita)[:MAX_NOVITA]:
        if not isinstance(voce, Mapping):
            continue
        tipo = str(voce.get("tipo") or "aggiornamento")
        campo = voce.get("campo")
        etichetta = f"{tipo} ({campo})" if campo else tipo
        citazione = _truncate(str(voce.get("citazione") or "").strip(), MAX_CITAZIONE_NOVITA)
        fonte = str(voce.get("url_prova") or "").strip()
        riga = f"- {etichetta}: «{citazione}»" if citazione else f"- {etichetta}"
        if fonte:
            riga += f" (pagina: {fonte})"
        righe.append(riga)
    if not righe:
        return ""
    return (
        "== NOVITÀ PUBBLICATE DALL'ENTE (da integrare nella scheda) ==\n\n"
        + "\n".join(righe)
        + "\n\nLa scheda è già pubblicata: riscrivi il contenuto integrando queste novità "
        "dove servono (date nuove, FAQ, graduatoria, esiti, documenti), senza togliere "
        "informazioni ancora valide e senza inventare dettagli che le citazioni non dicono. "
        "Vale la regola 16: mai lo stato del bando in prosa.\n\n"
    )


# ---------------------------------------------------------------------------
# Retry helper (riusa pattern enricher)
# ---------------------------------------------------------------------------

async def _call_anthropic_tool(
    client, model: str, max_tokens: int,
    system: str, user_prompt: str, tool: dict,
    max_retries: int = 3,
    *,
    contatori: bilancio.Contatori | None = None,
    listino: Mapping[str, tuple[float, float]] | None = None,
    diagnosi: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Anthropic call con tool use forzato + retry exponential.

    Con `contatori` ogni risposta ricevuta si somma alla spesa (token e $ dal
    listino), anche quando non contiene il tool: la chiamata e' pagata lo
    stesso. Senza, nessun conto: e' il caso della pipeline, la cui riga di
    giro non lo registra oggi. In `diagnosi` finiscono `stop_reason` e, se
    non torna un payload, il motivo.
    """
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
            if contatori is not None:
                bilancio.registra_chiamata(
                    contatori, model, getattr(response, "usage", None), listino or {},
                )
            if diagnosi is not None:
                diagnosi["stop_reason"] = getattr(response, "stop_reason", None)
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == tool["name"]:
                    return dict(block.input)
            _scarta(diagnosi, "risposta senza il tool "
                              f"(stop_reason={getattr(response, 'stop_reason', None)})")
            return None
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if isinstance(e, anthropic.APIStatusError) and status and 400 <= status < 500 and status != 429:
                logger.error("[seo] API status {} non retryabile: {}", status, e)
                _scarta(diagnosi, f"API {status} non ripetibile")
                return None
            _scarta(diagnosi, f"tentativi esauriti: {type(e).__name__}")
            sleep_s = (2 ** attempt) * 2 + random.uniform(0, 1)
            logger.warning(
                "[seo] retry {}/{} dopo {}: sleep {:.1f}s",
                attempt + 1, max_retries, type(e).__name__, sleep_s,
            )
            await asyncio.sleep(sleep_s)
        except Exception as e:
            logger.exception("[seo] errore inatteso: {}", e)
            _scarta(diagnosi, f"errore inatteso: {type(e).__name__}")
            return None
    return None


# ---------------------------------------------------------------------------
# Titolo troppo lungo: titolo_breve, poi una richiamata (revisione #25)
# ---------------------------------------------------------------------------

RISCRIVI_TITOLO_TOOL = {
    "name": "riscrivi_titolo",
    "description": "Salva il titolo H1 riscritto, entro 80 caratteri spazi compresi.",
    "input_schema": {
        "type": "object",
        "properties": {"titolo": {"type": "string", "maxLength": TITOLO_MAX}},
        "required": ["titolo"],
    },
}

RISCRIVI_TITOLO_SYSTEM = (
    "Sei il redattore SEO della scheda di un bando pubblico italiano. Riscrivi SOLO il "
    "titolo H1. Regole: al massimo 80 caratteri contati, spazi compresi; sentence case; "
    "comincia con il fatto concreto; NON togliere enti, luoghi o sigle del titolo attuale "
    "(accorcia le altre parole); NON aggiungere niente che non sia nel titolo attuale o nei "
    "dati. Chiama il tool riscrivi_titolo una volta."
)


def prompt_riscrivi_titolo(
    titolo: str, payload: Mapping[str, Any], input_ctx: Mapping[str, Any],
) -> str:
    """Il messaggio della richiamata: il motivo esplicito e i soli dati che servono."""
    return (
        f"Il titolo ha {len(titolo)} caratteri, il massimo è {TITOLO_MAX}: riscrivilo entro "
        f"{TITOLO_MAX} caratteri senza perdere enti o luoghi.\n\n"
        f"Titolo attuale: {titolo}\n"
        f"Ente erogatore: {payload.get('ente_erogatore') or '(non indicato)'}\n"
        f"Area geografica: {payload.get('area_geografica') or '(non indicata)'}\n"
        f"Titolo grezzo della fonte: {input_ctx.get('titolo_raw') or '(vuoto)'}"
    )


async def sistema_titolo(
    payload: dict[str, Any],
    bando_id: Any,
    input_ctx: Mapping[str, Any],
    *,
    client: Any,
    model: str,
    contatori: bilancio.Contatori | None = None,
    listino: Mapping[str, tuple[float, float]] | None = None,
    diagnosi: dict[str, Any] | None = None,
) -> bool:
    """Porta il titolo di un NON pubblicato entro 80 caratteri, o dice perche' no.

    1. il `titolo_breve` del payload, se ha 1-80 caratteri;
    2. altrimenti UNA richiamata al modello per il solo titolo, con il motivo;
    3. altrimenti False, con il motivo «titolo N caratteri anche dopo la
       richiamata» in `diagnosi`.

    Mai un taglio meccanico: il titolo si congela alla pubblicazione.
    """
    titolo = str(payload.get("titolo") or "").strip()
    if len(titolo) <= TITOLO_MAX:
        return True
    breve = str(payload.get("titolo_breve") or "").strip()
    if 1 <= len(breve) <= TITOLO_MAX:
        logger.info("[seo] bando_id={} titolo di {} caratteri: si usa titolo_breve {!r}",
                    bando_id, len(titolo), breve)
        payload["titolo"] = breve
        return True
    risposta = await _call_anthropic_tool(
        client, model=model, max_tokens=300, system=RISCRIVI_TITOLO_SYSTEM,
        user_prompt=prompt_riscrivi_titolo(titolo, payload, input_ctx),
        tool=RISCRIVI_TITOLO_TOOL, max_retries=1, contatori=contatori, listino=listino,
    )
    nuovo = str((risposta or {}).get("titolo") or "").strip()
    if 1 <= len(nuovo) <= TITOLO_MAX:
        logger.info("[seo] bando_id={} titolo riscritto dal modello ({} -> {}): {!r}",
                    bando_id, len(titolo), len(nuovo), nuovo)
        payload["titolo"] = nuovo
        return True
    lunghezza = len(nuovo) if nuovo else len(titolo)
    logger.warning("[seo] bando_id={} titolo di {} caratteri anche dopo la richiamata",
                   bando_id, lunghezza)
    _scarta(diagnosi, f"titolo {lunghezza} caratteri anche dopo la richiamata"
                      + ("" if nuovo else " (richiamata senza risposta)"))
    return False


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def enrich_seo(
    input_ctx: dict[str, Any],
    markdown: str,
    *,
    link_ammessi: Iterable[str] | None = None,
    allegati_ammessi: Iterable[str] | None = None,
    contatori: bilancio.Contatori | None = None,
    ripara_lunghezze: bool = False,
    titolo_congelato: bool = False,
    descrizione_facoltativa: bool = False,
    diagnosi: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Esegue 1 LLM call Opus + validation. Ritorna payload validato o None.

    `link_ammessi` e `allegati_ammessi` arrivano dal resolver (fonte ufficiale,
    allegati verificati, `bando_link` pubblicabili) e alimentano il gate del
    punto 10 di `_validate_payload`. `contatori` raccoglie la spesa della
    chiamata (lo passa `seo-rigenera`; la pipeline no). `ripara_lunghezze`
    (solo per i bandi non pubblicati) sistema un titolo troppo lungo con
    `sistema_titolo` e accorcia la descrizione invece di scartare;
    `titolo_congelato` solo per i pubblicati, il cui titolo non si scrive mai. `diagnosi["motivo"]` dice perche' il
    risultato e' None.
    """
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
        contatori=contatori,
        listino=getattr(settings, "listino_modelli", None),
        diagnosi=diagnosi,
    )
    if not raw_payload:
        logger.warning("[seo] bando_id={} LLM call fallita/vuota", bando_id)
        if diagnosi is not None and not diagnosi.get("motivo"):
            _scarta(diagnosi, "chiamata senza payload")
        return None

    if ripara_lunghezze and not titolo_congelato:
        titolo_ok = await sistema_titolo(
            raw_payload, bando_id, input_ctx, client=client, model=settings.seo_model,
            contatori=contatori, listino=getattr(settings, "listino_modelli", None),
            diagnosi=diagnosi,
        )
        if not titolo_ok:
            return None

    validated = await _validate_payload(
        raw_payload, bando_id, input_ctx, markdown,
        reachability_check=settings.seo_reachability_check,
        link_ammessi=link_ammessi,
        allegati_ammessi=allegati_ammessi,
        ripara_lunghezze=ripara_lunghezze,
        titolo_congelato=titolo_congelato,
        descrizione_facoltativa=descrizione_facoltativa,
        diagnosi=diagnosi,
    )
    if not validated:
        # Un payload troncato dal tetto di token arriva senza qualche campo:
        # detto cosi', il motivo porta dritto a SEO_MAX_TOKENS.
        if diagnosi is not None and diagnosi.get("stop_reason") == "max_tokens":
            diagnosi["motivo"] = f"{diagnosi.get('motivo', '')} (risposta troncata: max_tokens)"
        return None

    logger.debug(
        "[seo] bando_id={} OK livello={} slug={} ente={} importo={}",
        bando_id, validated.get("livello"), validated.get("slug"),
        validated.get("ente_erogatore"), validated.get("importo_totale_eur"),
    )
    return validated
