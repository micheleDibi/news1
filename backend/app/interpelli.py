"""
Pipeline completa per scraping, classificazione e generazione articoli interpelli.

Flusso:
1. Scrape link giornalieri da scuolainterpelli.it
2. Filtra e salva nuovi link giornalieri su Supabase
3. Per ogni pagina giornaliera, estrai i singoli interpelli
4. Classifica ogni link (singolo vs lista) con Firecrawl + OpenAI
5. Arricchisci metadati (regione, provincia, citta, classe concorso) con OpenAI
6. Genera articolo giornalistico con FAQ per ogni interpello

Eseguibile con: python -m app.interpelli
"""

import re
import json
import requests
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from bs4 import BeautifulSoup
from firecrawl import Firecrawl
import anthropic
from dotenv import load_dotenv
import os

load_dotenv()

from .database import get_supabase_client
from .indexnow import submit_to_indexnow
from .google_indexing import notify_google_indexing
from .logger import logger

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

BASE_URL = "https://www.scuolainterpelli.it/interpelli-scuola-aggiornati/"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

CLAUDE_MODEL = "claude-opus-4-7"


def _generate_interpello_slug(item: dict) -> str:
    """Genera slug URL-friendly per un interpello (replica della logica frontend)."""
    import re
    parts = [
        item.get("interpello_name", ""),
        item.get("interpello_provincia") or item.get("interpello_citta", ""),
        item.get("interpello_regione", ""),
        str(item.get("id", "")),
    ]
    parts = [p for p in parts if p]
    raw = "-".join(parts).lower()
    raw = re.sub(r"[^a-z0-9\-]", "-", raw)
    raw = re.sub(r"-+", "-", raw)
    return raw.strip("-")


def _llm_json_request(
    system_prompt: str,
    user_content: str,
    temperature: float = 0,
    max_tokens: int = 4096,
) -> dict:
    """Chiama Claude Opus 4.6 per ottenere una risposta JSON."""
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Forza output JSON nel system prompt
    json_system = system_prompt + "\n\nIMPORTANTE: Rispondi SOLO con JSON valido. Esegui l'escape di tutte le virgolette nei valori stringa con backslash (\\\")"

    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=json_system,
        messages=[
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
    )
    raw = response.content[0].text.strip()
    # Gestisci eventuale blocco markdown ```json ... ```
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Primo tentativo di parsing
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: chiedi a Claude di fixare il JSON malformato
    try:
        fix_response = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system="Correggi il seguente JSON malformato. Rispondi SOLO con il JSON corretto, senza markdown, senza spiegazioni. Assicurati che tutte le virgolette dentro i valori stringa siano escapate con backslash.",
            messages=[
                {"role": "user", "content": raw},
            ],
            temperature=0,
        )
        fixed = fix_response.content[0].text.strip()
        if "```" in fixed:
            fixed = fixed.split("```")[1]
            if fixed.startswith("json"):
                fixed = fixed[4:]
            fixed = fixed.strip()
        return json.loads(fixed)
    except Exception as fix_err:
        logger.error("Impossibile fixare JSON: {}", fix_err)
        raise

MESI_ITALIANI = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class DailyLink:
    link_name: str
    link_url: str
    link_date: Optional[str] = None  # ISO format YYYY-MM-DD


@dataclass
class InterpelloEntry:
    interpello_name: str
    interpello_link: str
    interpello_date: Optional[str] = None
    interpello_description: str = ""
    interpello_regione: str = ""
    interpello_provincia: str = ""
    interpello_citta: str = ""
    classe_concorso: Optional[str] = None
    link_type: str = "single"


@dataclass
class LinkClassification:
    link_type: str  # "single" | "list"
    sub_links: List[str] = field(default_factory=list)


@dataclass
class InterpelloArticle:
    article_title: str
    article_subtitle: str
    article_content: str


# ===========================================================================
# STEP 1 – Scraping link giornalieri dalla pagina principale
# ===========================================================================

def _parse_date_from_url(url: str) -> Optional[str]:
    """Estrae la data dalla URL tipo /interpelli-scuola-5-marzo-2025/."""
    pattern = r"/interpelli-scuola-(\d{1,2})-([a-z]+)-(\d{4})/"
    match = re.search(pattern, url.lower())
    if not match:
        return None
    giorno, mese_str, anno = match.groups()
    mese = MESI_ITALIANI.get(mese_str)
    if not mese:
        return None
    return f"{anno}-{mese}-{int(giorno):02d}"


def _extract_daily_links_from_html(html: str) -> List[DailyLink]:
    """Parsa l'HTML della pagina principale ed estrae i link giornalieri."""
    soup = BeautifulSoup(html, "html.parser")
    links: List[DailyLink] = []

    for a_tag in soup.select("a[href*='interpelli-scuola-']"):
        href = a_tag.get("href", "")
        if not href or "/interpelli-scuola-aggiornati" in href:
            continue
        # Normalizza URL
        if not href.startswith("http"):
            href = "https://www.scuolainterpelli.it" + href
        name = a_tag.get_text(strip=True)
        if not name:
            continue
        date = _parse_date_from_url(href)
        links.append(DailyLink(link_name=name, link_url=href, link_date=date))

    # Dedup per URL
    seen = set()
    unique: List[DailyLink] = []
    for lk in links:
        if lk.link_url not in seen:
            seen.add(lk.link_url)
            unique.append(lk)
    return unique


def scrape_daily_links_from_main_page(max_pages: int = 5) -> List[DailyLink]:
    """Scrape delle pagine principali (con paginazione) per ottenere i link giornalieri."""
    all_links: List[DailyLink] = []

    for page_num in range(1, max_pages + 1):
        url = BASE_URL if page_num == 1 else f"{BASE_URL}{page_num}/"
        logger.info("Scraping pagina principale: {}", url)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                logger.info("Pagina {} non trovata (status {}), fermo paginazione.", page_num, resp.status_code)
                break
            page_links = _extract_daily_links_from_html(resp.text)
            logger.info("Trovati {} link giornalieri nella pagina {}", len(page_links), page_num)
            all_links.extend(page_links)
        except Exception as e:
            logger.error("Errore scraping pagina {}: {}", page_num, e)
            break

    # Dedup globale
    seen = set()
    unique: List[DailyLink] = []
    for lk in all_links:
        if lk.link_url not in seen:
            seen.add(lk.link_url)
            unique.append(lk)

    # Filtra solo oggi e ieri
    today = date.today()
    yesterday = today - timedelta(days=1)
    allowed = {today.isoformat(), yesterday.isoformat()}
    filtered = [lk for lk in unique if lk.link_date in allowed]
    logger.info("Link giornalieri unici: {}, filtrati (oggi/ieri): {}", len(unique), len(filtered))
    return filtered


# ===========================================================================
# STEP 2 – Filtraggio e salvataggio link giornalieri
# ===========================================================================

def filter_new_daily_links(links: List[DailyLink]) -> List[DailyLink]:
    """Filtra i link giornalieri gia presenti in Supabase."""
    if not links:
        return []
    supabase = get_supabase_client()
    urls = [lk.link_url for lk in links]
    existing = (
        supabase.table("interpelli_link_giornalieri")
        .select("link_url")
        .in_("link_url", urls)
        .execute()
    )
    existing_urls = {row["link_url"] for row in (existing.data or [])}
    new_links = [lk for lk in links if lk.link_url not in existing_urls]
    logger.info("Link nuovi: {} / {} totali", len(new_links), len(links))
    return new_links


def save_daily_links_to_supabase(links: List[DailyLink]) -> int:
    """Salva i link giornalieri su Supabase con upsert su link_url."""
    if not links:
        return 0
    supabase = get_supabase_client()
    rows = [
        {
            "link_name": lk.link_name,
            "link_url": lk.link_url,
            "link_date": lk.link_date,
            "status": "pending",
        }
        for lk in links
    ]
    resp = supabase.table("interpelli_link_giornalieri").upsert(
        rows, on_conflict="link_url"
    ).execute()
    count = len(resp.data) if resp.data else 0
    logger.info("Salvati {} link giornalieri su Supabase", count)
    return count


# ===========================================================================
# STEP 3 – Scraping interpelli dalle pagine giornaliere
# ===========================================================================

def _extract_class_code(text: str) -> Optional[str]:
    """Estrae la classe di concorso dal testo (es. ADEE, A022, ADMM)."""
    match = re.search(r"\b([A-Z]{2,4}\d{0,3})\b", text)
    return match.group(1) if match else None


def _extract_interpelli_from_html(html: str, date: Optional[str] = None) -> List[InterpelloEntry]:
    """Parsa l'HTML di una pagina giornaliera ed estrae gli interpelli.

    Struttura attesa:
    - h2 → Regione
    - h3 → Provincia/Citta
    - p > a[target="_blank"] → Link interpello
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: List[InterpelloEntry] = []

    content = soup.select_one(".entry-content, article, .post-content, main")
    if not content:
        content = soup

    current_region = ""
    current_province = ""

    for element in content.find_all(["h2", "h3", "p", "li"]):
        tag_name = element.name

        if tag_name == "h2":
            text = element.get_text(strip=True).upper()
            # Ignora titoli generici
            if any(skip in text.lower() for skip in ["interpelli scuola", "indice", "sommario", "condivid"]):
                continue
            current_region = text.title()
            current_province = ""

        elif tag_name == "h3":
            current_province = element.get_text(strip=True).title()

        elif tag_name in ("p", "li"):
            for a_tag in element.find_all("a", href=True):
                href = a_tag.get("href", "").strip()
                name = a_tag.get_text(strip=True)
                # Salta link interni / vuoti / ancore
                if (
                    not href
                    or not name
                    or href.startswith("#")
                    or "scuolainterpelli.it" in href
                ):
                    continue
                classe = _extract_class_code(name)
                entries.append(
                    InterpelloEntry(
                        interpello_name=name,
                        interpello_link=href,
                        interpello_date=date,
                        interpello_description=name,
                        interpello_regione=current_region,
                        interpello_provincia=current_province,
                        interpello_citta="",
                        classe_concorso=classe,
                    )
                )

    return entries


def scrape_interpelli_from_daily_page(url: str) -> List[InterpelloEntry]:
    """Scarica una pagina giornaliera e ne estrae gli interpelli."""
    logger.info("Scraping interpelli da: {}", url)
    date = _parse_date_from_url(url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            logger.error("Errore HTTP {} per {}", resp.status_code, url)
            return []
        entries = _extract_interpelli_from_html(resp.text, date)
        logger.info("Estratti {} interpelli", len(entries))
        return entries
    except Exception as e:
        logger.error("Errore scraping pagina giornaliera: {}", e)
        return []


def save_interpelli_to_supabase(entries: List[InterpelloEntry], source_url: str) -> int:
    """Salva gli interpelli su Supabase con dedup su interpello_link."""
    if not entries:
        return 0
    supabase = get_supabase_client()

    # Controlla link gia esistenti
    links_to_check = [e.interpello_link for e in entries]
    existing = (
        supabase.table("interpelli")
        .select("interpello_link")
        .in_("interpello_link", links_to_check)
        .execute()
    )
    existing_links = {row["interpello_link"] for row in (existing.data or [])}

    new_entries = [e for e in entries if e.interpello_link not in existing_links]
    if not new_entries:
        logger.info("Nessun nuovo interpello da salvare")
        return 0

    rows = [
        {
            "interpello_name": e.interpello_name,
            "interpello_link": e.interpello_link,
            "interpello_date": e.interpello_date,
            "interpello_description": e.interpello_description,
            "interpello_regione": e.interpello_regione,
            "interpello_provincia": e.interpello_provincia,
            "interpello_citta": e.interpello_citta,
            "classe_concorso": e.classe_concorso,
            "source_daily_link": source_url,
            "link_type": "single",
            "status": "pending",
        }
        for e in new_entries
    ]
    resp = supabase.table("interpelli").insert(rows).execute()
    count = len(resp.data) if resp.data else 0
    logger.info("Salvati {} nuovi interpelli da {}", count, source_url)
    return count


# ===========================================================================
# STEP 4 – Classificazione link interpello (Firecrawl + OpenAI)
# ===========================================================================

CLASSIFICATION_PROMPT = """Analizza il contenuto della pagina. Determina se contiene:
- UN SINGOLO interpello ("single"): dettagli specifici di una supplenza, un bando, un avviso per una specifica posizione
- UNA LISTA di interpelli ("list"): elenco con piu avvisi/link a posizioni diverse

Se "list", estrai i link individuali come sub_links (URL completi).

Rispondi ESCLUSIVAMENTE con un JSON valido:
{"link_type": "single" oppure "list", "sub_links": ["url1", "url2"] oppure []}"""


def classify_interpello_link(link: str, name: str) -> LinkClassification:
    """Classifica un link interpello come singolo o lista usando Firecrawl + OpenAI."""
    try:
        # Scrape con Firecrawl
        firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = firecrawl.scrape(link, formats=["markdown"])
        content = result.markdown if hasattr(result, "markdown") else ""
        if not content:
            logger.info("Nessun contenuto Firecrawl per {}", link)
            return LinkClassification(link_type="single")

        # Tronca a ~4000 caratteri per il prompt
        content_trimmed = content[:4000]

        # Classificazione con Claude
        data = _llm_json_request(
            system_prompt=CLASSIFICATION_PROMPT,
            user_content=f"Nome interpello: {name}\n\nContenuto pagina:\n{content_trimmed}",
        )
        return LinkClassification(
            link_type=data.get("link_type", "single"),
            sub_links=data.get("sub_links", []),
        )
    except Exception as e:
        logger.error("Errore classificazione {}: {}", link, e)
        return LinkClassification(link_type="single")


SUB_LINK_EXTRACTION_PROMPT = """Analizza il contenuto di questa pagina di un interpello scolastico ed estrai le informazioni principali.

Rispondi ESCLUSIVAMENTE con un JSON valido:
{
  "interpello_name": "nome/titolo dell'interpello",
  "interpello_description": "breve descrizione della posizione",
  "classe_concorso": "codice classe di concorso (es. A022, ADEE) oppure null",
  "interpello_citta": "citta oppure stringa vuota",
  "interpello_provincia": "provincia oppure stringa vuota",
  "interpello_regione": "regione oppure stringa vuota"
}"""


def _scrape_sub_link_details(url: str, parent: dict) -> InterpelloEntry:
    """Scrape un singolo sub-link per estrarre i dettagli specifici dell'interpello."""
    # Valori di fallback dal parent
    fallback = InterpelloEntry(
        interpello_name=f"{parent.get('interpello_name', '')} - Sub",
        interpello_link=url,
        interpello_date=parent.get("interpello_date"),
        interpello_description=parent.get("interpello_description", ""),
        interpello_regione=parent.get("interpello_regione", ""),
        interpello_provincia=parent.get("interpello_provincia", ""),
        interpello_citta=parent.get("interpello_citta", ""),
        classe_concorso=parent.get("classe_concorso"),
        link_type="single",
    )

    try:
        firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = firecrawl.scrape(url, formats=["markdown"])
        content = result.markdown if hasattr(result, "markdown") else ""
        if not content:
            logger.info("Nessun contenuto per sub-link {}, uso dati parent", url)
            return fallback

        content_trimmed = content[:4000]

        data = _llm_json_request(
            system_prompt=SUB_LINK_EXTRACTION_PROMPT,
            user_content=content_trimmed,
        )

        return InterpelloEntry(
            interpello_name=data.get("interpello_name") or fallback.interpello_name,
            interpello_link=url,
            interpello_date=parent.get("interpello_date"),
            interpello_description=data.get("interpello_description") or fallback.interpello_description,
            interpello_regione=data.get("interpello_regione") or fallback.interpello_regione,
            interpello_provincia=data.get("interpello_provincia") or fallback.interpello_provincia,
            interpello_citta=data.get("interpello_citta") or fallback.interpello_citta,
            classe_concorso=data.get("classe_concorso") or fallback.classe_concorso,
            link_type="single",
        )
    except Exception as e:
        logger.error("Errore scraping sub-link {}: {}", url, e)
        return fallback


def process_list_interpello(parent: dict, sub_links: List[str]) -> List[InterpelloEntry]:
    """Per un interpello di tipo lista, scrape ogni sub-link per estrarre i dettagli."""
    entries: List[InterpelloEntry] = []
    logger.info("Scraping {} sub-link dalla lista...", len(sub_links))
    for i, sub_url in enumerate(sub_links, 1):
        logger.info("[{}/{}] {}...", i, len(sub_links), sub_url[:80])
        entry = _scrape_sub_link_details(sub_url, parent)
        entries.append(entry)
    return entries


def classify_and_expand_all() -> int:
    """Classifica tutti gli interpelli pending e espande quelli di tipo lista."""
    supabase = get_supabase_client()
    pending = (
        supabase.table("interpelli")
        .select("*")
        .eq("status", "pending")
        .eq("link_type", "single")
        .execute()
    )
    items = pending.data or []
    if not items:
        logger.info("Nessun interpello da classificare")
        return 0

    logger.info("Classificazione di {} interpelli...", len(items))
    expanded_count = 0

    for item in items:
        link = item.get("interpello_link", "")
        name = item.get("interpello_name", "")
        item_id = item.get("id")

        classification = classify_interpello_link(link, name)
        logger.info("{}... -> {}", name[:60], classification.link_type)

        if classification.link_type == "list" and classification.sub_links:
            # Aggiorna parent come lista (completed = no articolo da generare)
            supabase.table("interpelli").update(
                {"link_type": "list", "status": "completed"}
            ).eq("id", item_id).execute()

            # Scrape e crea entry per ogni sub-link
            sub_entries = process_list_interpello(item, classification.sub_links)
            for entry in sub_entries:
                # Dedup
                existing = (
                    supabase.table("interpelli")
                    .select("id")
                    .eq("interpello_link", entry.interpello_link)
                    .execute()
                )
                if not (existing.data):
                    supabase.table("interpelli").insert(
                        {
                            "interpello_name": entry.interpello_name,
                            "interpello_link": entry.interpello_link,
                            "interpello_date": entry.interpello_date,
                            "interpello_description": entry.interpello_description,
                            "interpello_regione": entry.interpello_regione,
                            "interpello_provincia": entry.interpello_provincia,
                            "interpello_citta": entry.interpello_citta,
                            "classe_concorso": entry.classe_concorso,
                            "source_daily_link": item.get("source_daily_link", ""),
                            "link_type": "single",
                            "status": "classified",
                        }
                    ).execute()
                    expanded_count += 1
        else:
            # Singolo: segna come classificato
            supabase.table("interpelli").update(
                {"link_type": "single", "status": "classified"}
            ).eq("id", item_id).execute()

    logger.info("Classificazione completata. Espansi {} sub-link.", expanded_count)
    return expanded_count


# ===========================================================================
# STEP 5 – Enrichment metadati con OpenAI
# ===========================================================================

ENRICHMENT_PROMPT = """Sei un esperto del sistema scolastico italiano. Ti viene fornito il nome/descrizione di un interpello scolastico e le informazioni parziali gia estratte.

Il tuo compito e completare/correggere i seguenti campi:
- interpello_regione: la regione italiana (es. "Lombardia", "Sicilia")
- interpello_provincia: la provincia (es. "Milano", "L'Aquila")
- interpello_citta: la citta specifica se identificabile, altrimenti stringa vuota
- classe_concorso: il codice della classe di concorso (es. "A022", "ADEE", "ADMM"). Se non identificabile, null.

Usa le informazioni nel nome dell'interpello, nella descrizione e nel link per dedurre i dati mancanti.
Ad esempio, se il link contiene "csalaquila" la provincia e "L'Aquila" e la regione "Abruzzo".

Rispondi ESCLUSIVAMENTE con un JSON valido:
{
  "interpello_regione": "...",
  "interpello_provincia": "...",
  "interpello_citta": "...",
  "classe_concorso": "..." oppure null
}"""


def enrich_interpello_metadata(item: dict) -> dict:
    """Usa LLM per completare regione, provincia, citta e classe_concorso."""
    try:
        user_content = (
            f"Nome: {item.get('interpello_name', '')}\n"
            f"Descrizione: {item.get('interpello_description', '')}\n"
            f"Link: {item.get('interpello_link', '')}\n"
            f"Regione attuale: {item.get('interpello_regione', '')}\n"
            f"Provincia attuale: {item.get('interpello_provincia', '')}\n"
            f"Citta attuale: {item.get('interpello_citta', '')}\n"
            f"Classe concorso attuale: {item.get('classe_concorso', '')}\n"
        )

        data = _llm_json_request(
            system_prompt=ENRICHMENT_PROMPT,
            user_content=user_content,
        )
        return {
            "interpello_regione": data.get("interpello_regione") or item.get("interpello_regione", ""),
            "interpello_provincia": data.get("interpello_provincia") or item.get("interpello_provincia", ""),
            "interpello_citta": data.get("interpello_citta") or item.get("interpello_citta", ""),
            "classe_concorso": data.get("classe_concorso") or item.get("classe_concorso"),
        }
    except Exception as e:
        logger.error("Errore enrichment per '{}': {}", item.get('interpello_name', ''), e)
        return {}


def enrich_all_classified() -> int:
    """Arricchisce i metadati di tutti gli interpelli classificati."""
    supabase = get_supabase_client()
    pending = (
        supabase.table("interpelli")
        .select("*")
        .eq("status", "classified")
        .eq("link_type", "single")
        .execute()
    )
    items = pending.data or []
    if not items:
        logger.info("Nessun interpello da arricchire")
        return 0

    logger.info("Enrichment metadati per {} interpelli...", len(items))
    enriched_count = 0

    for item in items:
        enriched = enrich_interpello_metadata(item)
        if enriched:
            supabase.table("interpelli").update(
                {
                    "interpello_regione": enriched["interpello_regione"],
                    "interpello_provincia": enriched["interpello_provincia"],
                    "interpello_citta": enriched["interpello_citta"],
                    "classe_concorso": enriched["classe_concorso"],
                    "status": "enriched",
                }
            ).eq("id", item["id"]).execute()
            enriched_count += 1
            logger.info("Arricchito: {}... -> {}/{}/{}", item.get('interpello_name', '')[:50], enriched.get('interpello_regione'), enriched.get('interpello_provincia'), enriched.get('classe_concorso'))
        else:
            # Segna comunque come enriched per non bloccare la pipeline
            supabase.table("interpelli").update(
                {"status": "enriched"}
            ).eq("id", item["id"]).execute()
            enriched_count += 1

    logger.info("Enrichment completato: {}/{}", enriched_count, len(items))
    return enriched_count


# ===========================================================================
# STEP 6 – Generazione articolo (OpenAI gpt-4.1)
# ===========================================================================

ARTICLE_PROMPT = """Sei un giornalista esperto del settore istruzione italiana. Scrivi per EduNews24, una testata giornalistica online autorevole.

Genera un articolo professionale su un interpello scolastico partendo dalle informazioni fornite.

## Stile di scrittura
- Tono autorevole ma accessibile
- Varia la lunghezza delle frasi
- Usa espressioni giornalistiche italiane naturali
- Privilegia fatti e dati concreti
- Contestualizza con riferimenti normativi quando possibile

## Struttura obbligatoria

1. **Indice** con link markdown alle sezioni:
   - [Titolo Sezione](#titolo-sezione)

2. **Sezioni H2 obbligatorie**:
   - Introduzione (contesto dell'interpello)
   - Dettagli dell'interpello (classe di concorso, sede, date)
   - Come candidarsi (procedura, documenti)
   - Requisiti richiesti

3. **Sezione FAQ** (3-5 domande frequenti con risposte dettagliate):
   - Usa formato ### per ogni domanda
   - Risposte concrete e pratiche

## Output
Rispondi ESCLUSIVAMENTE con un JSON valido:
{"article_title": "...", "article_subtitle": "...", "article_content": "...contenuto markdown completo..."}"""


def generate_interpello_article(
    name: str,
    description: str,
    link: str,
    regione: str,
    provincia: str,
    citta: str,
    classe: Optional[str],
    date: Optional[str],
) -> Optional[InterpelloArticle]:
    """Genera un articolo giornalistico per un singolo interpello."""
    try:
        user_content = (
            f"Interpello: {name}\n"
            f"Descrizione: {description}\n"
            f"Link ufficiale: {link}\n"
            f"Regione: {regione}\n"
            f"Provincia: {provincia}\n"
        )
        if citta:
            user_content += f"Citta: {citta}\n"
        if classe:
            user_content += f"Classe di concorso: {classe}\n"
        if date:
            user_content += f"Data: {date}\n"

        data = _llm_json_request(
            system_prompt=ARTICLE_PROMPT,
            user_content=user_content,
            temperature=0.7,
            max_tokens=8000,
        )
        return InterpelloArticle(
            article_title=data.get("article_title", name),
            article_subtitle=data.get("article_subtitle", ""),
            article_content=data.get("article_content", ""),
        )
    except Exception as e:
        logger.error("Errore generazione articolo per '{}': {}", name, e)
        return None


def generate_articles_for_pending() -> int:
    """Genera articoli per tutti gli interpelli arricchiti senza articolo."""
    supabase = get_supabase_client()
    pending = (
        supabase.table("interpelli")
        .select("*")
        .eq("status", "enriched")
        .eq("link_type", "single")
        .execute()
    )
    items = pending.data or []
    if not items:
        logger.info("Nessun interpello in attesa di articolo")
        return 0

    logger.info("Generazione articoli per {} interpelli...", len(items))
    success_count = 0

    for item in items:
        article = generate_interpello_article(
            name=item.get("interpello_name", ""),
            description=item.get("interpello_description", ""),
            link=item.get("interpello_link", ""),
            regione=item.get("interpello_regione", ""),
            provincia=item.get("interpello_provincia", ""),
            citta=item.get("interpello_citta", ""),
            classe=item.get("classe_concorso"),
            date=item.get("interpello_date"),
        )
        if article:
            supabase.table("interpelli").update(
                {
                    "article_title": article.article_title,
                    "article_subtitle": article.article_subtitle,
                    "article_content": article.article_content,
                    "status": "completed",
                }
            ).eq("id", item["id"]).execute()
            success_count += 1
            logger.info("Articolo generato: {}...", article.article_title[:60])

            # Notify IndexNow
            slug = _generate_interpello_slug(item)
            submit_to_indexnow([
                f"https://edunews24.it/interpelli/{slug}",
                "https://edunews24.it/interpelli",
            ])

            # Notify Google Indexing API (JobPosting)
            notify_google_indexing([f"https://edunews24.it/interpelli/{slug}"])
        else:
            supabase.table("interpelli").update(
                {"status": "error"}
            ).eq("id", item["id"]).execute()

    logger.info("Generati {}/{} articoli", success_count, len(items))
    return success_count


# ===========================================================================
# Orchestratore pipeline
# ===========================================================================

def run_interpelli_pipeline() -> Dict[str, Any]:
    """Esegue la pipeline completa degli interpelli."""
    logger.info("=" * 60)
    logger.info("AVVIO PIPELINE INTERPELLI")
    logger.info("=" * 60)

    result: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "status": "started",
    }

    try:
        # Step 1: Scrape link giornalieri
        logger.info("--- STEP 1: Scraping link giornalieri ---")
        daily_links = scrape_daily_links_from_main_page()
        result["daily_links_found"] = len(daily_links)

        # Step 2: Filtra e salva nuovi
        logger.info("--- STEP 2: Filtraggio e salvataggio ---")
        new_links = filter_new_daily_links(daily_links)
        saved = save_daily_links_to_supabase(new_links)
        result["daily_links_saved"] = saved

        if not new_links:
            logger.info("Nessun nuovo link giornaliero, verifico interpelli pending...")

        # Step 3: Per ogni link giornaliero nuovo, scrape interpelli
        logger.info("--- STEP 3: Scraping interpelli ---")
        total_interpelli = 0
        for link in new_links:
            entries = scrape_interpelli_from_daily_page(link.link_url)
            count = save_interpelli_to_supabase(entries, link.link_url)
            total_interpelli += count
            # Aggiorna status del link giornaliero
            supabase = get_supabase_client()
            supabase.table("interpelli_link_giornalieri").update(
                {"status": "scraped", "updated_at": datetime.now().isoformat()}
            ).eq("link_url", link.link_url).execute()
        result["interpelli_saved"] = total_interpelli

        # Step 4: Classifica e espandi
        logger.info("--- STEP 4: Classificazione ---")
        expanded = classify_and_expand_all()
        result["expanded_sub_links"] = expanded

        # Step 5: Enrichment metadati
        logger.info("--- STEP 5: Enrichment metadati ---")
        enriched = enrich_all_classified()
        result["enriched"] = enriched

        # Step 6: Genera articoli
        logger.info("--- STEP 6: Generazione articoli ---")
        articles = generate_articles_for_pending()
        result["articles_generated"] = articles

        result["status"] = "completed"

    except Exception as e:
        logger.error("ERRORE PIPELINE: {}", e)
        result["status"] = "error"
        result["error"] = str(e)

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETATA: {}", result)
    logger.info("=" * 60)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_interpelli_pipeline()
