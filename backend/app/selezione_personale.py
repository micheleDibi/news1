"""
Pipeline completa per scraping bandi INPA, salvataggio su Supabase e generazione articoli.

Flusso:
1. Fetch bandi aperti da INPA API
2. Dedup e salvataggio su Supabase
3. Arricchimento + generazione articolo con Claude Opus 4.6
4. Report finale

Eseguibile con: python -m app.selezione_personale (dalla cartella backend/)
"""

import re
import json
import requests
from datetime import datetime
from typing import List, Dict, Optional, Any

import anthropic
from dotenv import load_dotenv
import os

load_dotenv()

from .database import get_supabase_client
from .indexnow import submit_to_indexnow
from .logger import logger

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

INPA_API_URL = "https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/search-better"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4321")

CLAUDE_MODEL = "claude-opus-4-6"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.inpa.gov.it/",
}


def _llm_json_request(
    system_prompt: str,
    user_content: str,
    temperature: float = 0,
    max_tokens: int = 4096,
) -> dict:
    """Chiama Claude Opus 4.6 per ottenere una risposta JSON."""
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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



def _generate_slug(titolo: str, codice: str, enti: list = None) -> str:
    """Genera uno slug URL-friendly dal titolo e codice del bando."""
    parts = [titolo or "", codice or ""]
    if enti:
        parts.append("-".join(enti[:2]))

    slug = "-".join(parts)
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    # Limita lunghezza slug
    if len(slug) > 200:
        slug = slug[:200].rsplit("-", 1)[0]
    return slug


# ===========================================================================
# STEP 1 – Fetch bandi da INPA API
# ===========================================================================

def fetch_bandi_from_inpa(size: int = 2000) -> List[Dict]:
    """Scarica i bandi aperti dall'API INPA."""
    logger.info("Fetching bandi da INPA API (size={})", size)

    payload = {
        "text": "",
        "categoriaId": None,
        "regioneId": None,
        "status": ["OPEN"],
        "settoreId": None,
        "provinciaCodice": None,
        "dateFrom": None,
        "dateTo": None,
        "livelliAnzianitaIds": None,
        "tipoImpiegoId": None,
        "salaryMin": None,
        "salaryMax": None,
        "enteRiferimentoName": "",
    }

    try:
        url = f"{INPA_API_URL}?page=0&size={size}"
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=60)
        if resp.status_code != 200:
            logger.error("Errore HTTP {} dall'API INPA", resp.status_code)
            return []

        data = resp.json()
        bandi = data.get("content", [])
        total = data.get("totalElements", 0)
        logger.info("Scaricati {} bandi su {} totali", len(bandi), total)
        return bandi

    except Exception as e:
        logger.error("Errore fetch INPA: {}", e)
        return []


# ===========================================================================
# STEP 2 – Salvataggio su Supabase con dedup
# ===========================================================================

def _extract_bando_row(bando: dict) -> dict:
    """Estrae i campi dal JSON INPA e li mappa alle colonne Supabase."""
    codice = bando.get("codice", "")
    titolo = bando.get("titolo", "")
    enti = bando.get("entiRiferimento", []) or []

    return {
        "codice": codice,
        "titolo": titolo,
        "descrizione": bando.get("descrizione", ""),
        "descrizione_breve": bando.get("descrizioneBreve", ""),
        "figura_ricercata": bando.get("figuraRicercata", ""),
        "num_posti": bando.get("numPosti"),
        "tipo_procedura": bando.get("tipoProcedura", ""),
        "data_pubblicazione": bando.get("dataPubblicazione"),
        "data_scadenza": bando.get("dataScadenza"),
        "data_visibilita": bando.get("dataVisibilita"),
        "sedi": bando.get("sedi", []) or [],
        "categorie": bando.get("categorie", []) or [],
        "settori": bando.get("settori", []) or [],
        "enti_riferimento": enti,
        "salary_min": bando.get("salaryMin"),
        "salary_max": bando.get("salaryMax"),
        "link_reindirizzamento": bando.get("linkReindirizzamento"),
        "calculated_status": bando.get("calculatedStatus", ""),
        "status_label": bando.get("statusLabel", ""),
        "allegato_media_id": bando.get("allegatoMediaId"),
        "slug": _generate_slug(titolo, codice, enti),
        "status": "pending",
    }


def save_new_bandi_to_supabase(bandi: List[Dict]) -> int:
    """Salva i bandi nuovi su Supabase, dedup su codice."""
    if not bandi:
        return 0

    supabase = get_supabase_client()

    # Estrai codici per dedup
    codici = [b.get("codice", "") for b in bandi if b.get("codice")]
    if not codici:
        return 0

    # Query codici gia esistenti (in batch da 500)
    existing_codici = set()
    for i in range(0, len(codici), 500):
        batch = codici[i : i + 500]
        existing = (
            supabase.table("selezione_personale")
            .select("codice")
            .in_("codice", batch)
            .execute()
        )
        existing_codici.update(row["codice"] for row in (existing.data or []))

    # Filtra nuovi
    new_rows = []
    for bando in bandi:
        codice = bando.get("codice", "")
        if codice and codice not in existing_codici:
            new_rows.append(_extract_bando_row(bando))

    if not new_rows:
        logger.info("Nessun nuovo bando da salvare")
        return 0

    # Inserisci in batch da 100
    inserted = 0
    for i in range(0, len(new_rows), 100):
        batch = new_rows[i : i + 100]
        resp = supabase.table("selezione_personale").insert(batch).execute()
        inserted += len(resp.data) if resp.data else 0

    logger.info("Salvati {} nuovi bandi su Supabase", inserted)
    return inserted


# ===========================================================================
# STEP 3 – Generazione articolo con Claude
# ===========================================================================

ARTICLE_PROMPT = """Sei un giornalista esperto del settore lavoro pubblico e concorsi in Italia. Scrivi per EduNews24, una testata giornalistica online autorevole.

Genera un articolo professionale su un bando di concorso/selezione pubblica partendo dalle informazioni fornite.

## Stile di scrittura

- Tono autorevole ma accessibile, come un editoriale del Corriere della Sera o di Repubblica
- Varia la lunghezza e la struttura delle frasi: alterna frasi brevi e incisive a periodi piu articolati
- Usa espressioni giornalistiche italiane naturali (es. "stando a quanto emerge", "come sottolineato da", "la questione resta aperta")
- Evita formule ripetitive e strutture prevedibili
- Non usare mai espressioni come "in conclusione", "in questo articolo", "e importante sottolineare che" o altri cliche da testo generato
- Privilegia i fatti e i dati concreti rispetto alle considerazioni generiche
- Quando possibile, contestualizza con riferimenti al quadro normativo o istituzionale italiano

## Struttura obbligatoria

1. **Indice**: all'inizio dell'articolo, crea un indice con link alle sezioni. Formato:
   - [Titolo Sezione 1](#titolo-sezione-1)
   - [Titolo Sezione 2](#titolo-sezione-2)
   (usa il formato slug per le ancore: minuscolo, trattini al posto degli spazi)

2. **Titoli e sottotitoli**:
   - Usa ## (H2) per i titoli delle sezioni principali
   - Usa ### (H3) SOLO se il contenuto e un approfondimento diretto della sezione H2 padre
   - Se il tema cambia, apri un nuovo ## (H2)
   - Ogni H2 deve avere un id ancora corrispondente all'indice

3. **Corpo dell'articolo**:
   - Usa **grassetto** per concetti chiave e nomi propri rilevanti
   - Usa _corsivo_ per termini tecnici o citazioni
   - Usa elenchi puntati quando servono per chiarezza
   - Paragrafi ben separati e di lunghezza variabile

4. **Sezioni H2 obbligatorie**:
   - Introduzione (contesto del bando/concorso)
   - Dettagli del bando (ente, figure ricercate, posti, sedi, date)
   - Come candidarsi (procedura, documenti, link)
   - Requisiti richiesti (se deducibili)

5. **Sezione FAQ** (3-5 domande frequenti con risposte dettagliate):
   - Usa formato ### per ogni domanda
   - Risposte concrete e pratiche

## Lunghezza

L'articolo deve essere esaustivo e completo: se servono 800 parole va bene, se ne servono 2000 va bene. La qualita e la completezza vengono prima della lunghezza.

## Output

Rispondi ESCLUSIVAMENTE con un JSON valido nel formato:
{
  "article_title": "Titolo giornalistico riscritto",
  "article_subtitle": "Sottotitolo esplicativo",
  "article_content": "Contenuto completo in markdown",
  "article_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6", "keyword7", "keyword8", "keyword9", "keyword10"]
}

Le keywords devono essere 10 parole chiave SEO strategiche in italiano, mix short-tail e long-tail, pertinenti al bando specifico."""


def generate_article_for_bando(bando: dict) -> Optional[dict]:
    """Genera un articolo giornalistico per un singolo bando."""
    try:
        sedi = bando.get("sedi") or []
        enti = bando.get("enti_riferimento") or []
        categorie = bando.get("categorie") or []
        settori = bando.get("settori") or []

        user_content = (
            f"Titolo bando: {bando.get('titolo', '')}\n"
            f"Codice: {bando.get('codice', '')}\n"
            f"Descrizione: {bando.get('descrizione', '')}\n"
            f"Descrizione breve: {bando.get('descrizione_breve', '')}\n"
            f"Figura ricercata: {bando.get('figura_ricercata', '')}\n"
            f"Numero posti: {bando.get('num_posti', 'N/D')}\n"
            f"Tipo procedura: {bando.get('tipo_procedura', '')}\n"
            f"Ente: {', '.join(enti) if enti else 'N/D'}\n"
            f"Sedi: {', '.join(sedi) if sedi else 'N/D'}\n"
            f"Categorie: {', '.join(categorie) if categorie else 'N/D'}\n"
            f"Settori: {', '.join(settori) if settori else 'N/D'}\n"
            f"Data pubblicazione: {bando.get('data_pubblicazione', 'N/D')}\n"
            f"Data scadenza: {bando.get('data_scadenza', 'N/D')}\n"
            f"Link ufficiale: {bando.get('link_reindirizzamento', 'N/D')}\n"
        )
        if bando.get("salary_min") or bando.get("salary_max"):
            user_content += f"Retribuzione: {bando.get('salary_min', 'N/D')} - {bando.get('salary_max', 'N/D')}\n"

        data = _llm_json_request(
            system_prompt=ARTICLE_PROMPT,
            user_content=user_content,
            temperature=0.7,
            max_tokens=8000,
        )

        return {
            "article_title": data.get("article_title", bando.get("titolo", "")),
            "article_subtitle": data.get("article_subtitle", ""),
            "article_content": data.get("article_content", ""),
            "article_keywords": data.get("article_keywords", []),
        }

    except Exception as e:
        logger.error("Errore generazione articolo per '{}': {}", bando.get('titolo', ''), e)
        return None


def generate_articles_for_pending() -> int:
    """Genera articoli per tutti i bandi in status pending."""
    supabase = get_supabase_client()
    pending = (
        supabase.table("selezione_personale")
        .select("*")
        .eq("status", "pending")
        .limit(50)
        .execute()
    )
    items = pending.data or []
    if not items:
        logger.info("Nessun bando in attesa di articolo")
        return 0

    logger.info("Generazione articoli per {} bandi...", len(items))
    success_count = 0

    for item in items:
        logger.info("Generando articolo per: {}...", item.get('titolo', '')[:60])
        article = generate_article_for_bando(item)
        if article:
            # Rigenera slug con article_title se disponibile
            slug = _generate_slug(
                article["article_title"],
                item.get("codice", ""),
                item.get("enti_riferimento"),
            )
            supabase.table("selezione_personale").update(
                {
                    "article_title": article["article_title"],
                    "article_subtitle": article["article_subtitle"],
                    "article_content": article["article_content"],
                    "article_keywords": article["article_keywords"],
                    "slug": slug,
                    "status": "completed",
                    "updated_at": datetime.now().isoformat(),
                }
            ).eq("id", item["id"]).execute()
            success_count += 1
            logger.info("Articolo generato: {}...", article['article_title'][:60])

            # Notify IndexNow
            submit_to_indexnow([
                f"https://edunews24.it/selezione-personale/{slug}",
                "https://edunews24.it/selezione-personale",
            ])
        else:
            supabase.table("selezione_personale").update(
                {"status": "error", "updated_at": datetime.now().isoformat()}
            ).eq("id", item["id"]).execute()

    logger.info("Generati {}/{} articoli", success_count, len(items))
    return success_count


# ===========================================================================
# Orchestratore pipeline
# ===========================================================================

def run_selezione_personale_pipeline() -> Dict[str, Any]:
    """Esegue la pipeline completa selezione personale."""
    logger.info("=" * 60)
    logger.info("AVVIO PIPELINE SELEZIONE PERSONALE")
    logger.info("=" * 60)

    result: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "process": "selezione_personale",
        "status": "started",
    }

    try:
        # Step 1: Fetch bandi da INPA
        logger.info("--- STEP 1: Fetch bandi da INPA API ---")
        bandi = fetch_bandi_from_inpa()
        result["bandi_fetched"] = len(bandi)

        # Step 2: Salva nuovi su Supabase
        logger.info("--- STEP 2: Salvataggio nuovi bandi ---")
        saved = save_new_bandi_to_supabase(bandi)
        result["bandi_saved"] = saved

        # Step 3: Genera articoli per pending
        logger.info("--- STEP 3: Generazione articoli ---")
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
    run_selezione_personale_pipeline()
