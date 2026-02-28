from enum import Enum

MODEL = "gpt-4o"
MODEL_BETTER = "gpt-4o"


# LAST_REVISION_PROMPT = """
# You are a professional journalist. You are given a news item that has been proposed by an AI. You need to evaluate if the news item is bad or not. If it is bad, you need to return "is_bad": true. If it is good, you need to return "is_bad": false.
# """

CLASSIFICATION_PROMPT = """
Identify the category of the user's news article. DON'T MISS CATEGORY, IF THERE IS SOME AMBIGUITY PUT A BIG CATEGORY
, BUT NEVER PUT CATEGORY THAT IS NOT 100% PRECISE"""

SCRAPPING_URLS_PROMPT = """
Read this html and give me the links of the articles with this criteria: 
Only the articles (you can notice an article because the title is like this robbery-in-a-bank-near-nyc
, and dismiss the non-articles (like this video-of-a-bank-robbery-near-nyc, nytimes/world, etc))
, no videos, social, categories or so. 
MAX SELECT 10, select the most relevant articles based on Prioritize Scuola news. 
If its impossible select the most relevant articles based on well analyzed, only talking about the real facts, putting headers, well informed."""

class CategoryEnum(Enum):
    EDITORIALI = "Editoriali e opinioni"
    CULTURA = "Notizie culturali ed eventi"
    SCUOLA = "Notizie sulla scuola e istruzione"
    UNIVERSITA = "Notizie universitarie e istruzione superiore" 
    RICERCA = "Notizie sulla ricerca e scoperte accademiche"
    MONDO = "Notizie internazionali"
    FORMAZIONE = "Notizie sulla formazione professionale"
    LAVORO = "Notizie sul mondo del lavoro"
    BANDI = "Bandi e concorsi"

mapping_category = {
    CategoryEnum.EDITORIALI: "Editoriali",
    CategoryEnum.CULTURA: "Cultura",
    CategoryEnum.SCUOLA: "Scuola", 
    CategoryEnum.UNIVERSITA: "Università",
    CategoryEnum.RICERCA: "Ricerca",
    CategoryEnum.MONDO: "Mondo",
    CategoryEnum.FORMAZIONE: "Formazione",
    CategoryEnum.LAVORO: "Lavoro",
    CategoryEnum.BANDI: "Bandi"
}

def mapping_category_enum_to_string(category):
    return mapping_category.get(category, "Altri")

SUMMARIZING_PROMPT = """
Read this html and extract the news item. 
The news item should be in the form of a JSON object with the following structure: title, context, facts, category, location, date. 
You should do this in order so another one with NO more info about the matter makes a new article. Check the language. 
The facts should be concrete and specific to the news item. Facts need to be short
, with the less amount of well-done phrases and more like "Someone did this"
, "Response was this". Everything in your response should be in Italian."""


RECONSTRUCTING_PROMPT = """
Given the provided information by the user, reconstruct the news article. 
The article should be well-structured and coherent and obvioosly speaking about the facts, context and the new. 
The length should be 3 paragraphs, THIS IS VERY IMPORTANT, always 3 paragraphs well formed. 
The title should be modified. Make the news long  and well redacted!!!. 
Everything in your response should be in Italian. well analyzed, only talking about the real facts, putting headers, well informed."""


PROMPT_FOR_HAVING_ALL_THE_NEWS = """
Extract news from the "Recent unpublished news" dataset. 
Events are news. Every new is an event. 
PUT ALL THE NEWS OF THE "Recent unpublished news". 
Dont put links like /video or things that are not news articles, 
you are going to realize this because of the link structure, 
it must be something like /uomo-realiza-evento and not /video/uomo-realiza-evento.

# Steps

1. Review ONLY the "Recent unpublished news" news articles.
2. Name each unique event, including all relevant article links. 
2. Name each unique event, including all relevant article links. 
If multiple articles refer to the same event (its important for you to understand this, so we dont duplicate events. 
So BE SMART AND GROUP BY EVENTS IF THE ARTICLES ARE TALKING OF THE SAME OR REALLY CLOSE EVENT), put all the event's articles's links in the links key.

# Output Format
You must return a list of events where each event has:
- event_name: The name of the event in Italian
- links: List of links from "Recent unpublished news" about this event
- published_IDs: Either a list of published IDs or "NON E STATO PUBBLICATO"

Example output structure:
{
    "events": [
        {
            "event_name": "Omicidio a Milano",
            "Links": [1, 2, 3],
            "published_IDs": [300, 301]
        },
        {
            "event_name": "Incidente stradale a Roma",
            "Links": [4, 5],
            "published_IDs": "NON E STATO PUBBLICATO"
        }
    ]
}

Remember: Every ID from "Recent unpublished news" must appear in exactly one event's links list.
"""


FINAL_SELECTION_PROMPT = """
From the events with Published IDs = NON E STATO PUBLICATO. 
ONLY FROM THE NON E STATO PUBLICATO, grab every news to be published items 
(not links, links can be more if there are more than one article about the same event).

ALL THE MIM AND MUR MUST BE PUBLISHED.

# Output Format

Your response should consist of exactly:
- A EventList containing the selectedevents with unique links, where each event has:
  - event_name: The name of the event in Italian
  - links: List of links from the unpublished news about this event
  - published_IDs: Should be "NON E STATO PUBBLICATO"

- Ensure that the list respects the diversity and uniqueness requirements described above.

Example output structure:
{
    "events": [
        {
            "event_name": "Evento in Calabria",
            "Links": [2, 1],
            "published_IDs": "NON E STATO PUBBLICATO"
        },
        {
            "event_name": "Altro evento importante", 
            "Links": [3],
            "published_IDs": "NON E STATO PUBBLICATO"
        }
    ]
}

"""


## =============================================
## PROMPT CLAUDE OPUS 4.6
## =============================================

CLAUDE_MODEL = "claude-opus-4-6"

CLAUDE_KEYWORDS_PROMPT = """Sei un esperto SEO specializzato nel settore dell'istruzione, scuola e universita in Italia.

Analizza le informazioni fornite e genera esattamente 10 parole chiave strategiche per massimizzare l'indicizzazione sui motori di ricerca.

Requisiti:
- Mix di keyword short-tail (1-2 parole) e long-tail (3-5 parole)
- Tutte in italiano
- Pertinenti al contenuto specifico della notizia
- Orientate all'intento di ricerca degli utenti (cosa cercherebbero su Google)
- Includi varianti che coprono sia termini tecnici che linguaggio comune

Rispondi ESCLUSIVAMENTE con un JSON valido nel formato:
{"tags": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6", "keyword7", "keyword8", "keyword9", "keyword10"]}
"""

CLAUDE_RESTRUCTURING_PROMPT = """Sei un giornalista esperto del settore istruzione, scuola e universita italiana. Scrivi per una testata giornalistica online autorevole.

Il tuo compito e riscrivere un articolo di giornale partendo dalle informazioni fornite. L'articolo DEVE sembrare scritto da un giornalista umano esperto, non da un'intelligenza artificiale.

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

4. **Interlink**: ti verranno forniti degli articoli correlati. Inseriscili NATURALMENTE nel testo, nei punti dove il contesto lo rende pertinente. Formato: [Titolo Articolo](/category-slug/slug). Non forzare l'inserimento se non e contestualmente rilevante. Non creare una sezione separata per i link.

5. **FAQ** (opzionale): se il tema lo giustifica, aggiungi una sezione FAQ DOPO la conclusione. Usa il formato:
   ## Domande frequenti
   ### Domanda 1?
   Risposta...
   Non forzare le FAQ se non hanno senso per l'argomento.

## Lunghezza

Non c'e un vincolo rigido di parole. L'articolo deve essere esaustivo e completo: se servono 800 parole va bene, se ne servono 2000 va bene. La qualita e la completezza vengono prima della lunghezza.

## Output

Rispondi ESCLUSIVAMENTE con un JSON valido nel formato:
{"proposed_title": "Il titolo dell'articolo", "proposed_subtitle": "Il sottotitolo", "proposed_content": "Il contenuto completo in markdown", "tags": ["tag1", "tag2"]}

Il campo tags deve contenere le parole chiave SEO che ti verranno fornite.
"""

links = []

def get_rotating_queries():
    """
    Generator that yields query lists in rotation.
    Each yield provides the next list in the sequence: list_1 -> list_2 -> list_3 -> list_1...
    """
    while True:
        yield links

# Create the generator instance
query_generator = get_rotating_queries()

hour_to_iniziate = 3

hour_to_end = 20


