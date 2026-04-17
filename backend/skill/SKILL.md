---
name: news-angle-rewriter
description: Prende l'URL di una notizia pubblicata da un competitor (Orizzonte Scuola, Tecnica della Scuola, etc.), analizza come è stata coperta, trova un angolo originale con dati esclusivi, fact-checka tutto, e genera un articolo JSON strutturato ottimizzato SEO. Usa questa skill quando l'utente fornisce un URL di notizia e chiede di riscriverla con un angolo diverso, o quando chiede "riscrivi questa notizia", "trova un angolo diverso", "analizza questa notizia e riscrivila", "angle finder", "cambia angolo".
---

# News Angle Rewriter

Skill per generare articoli SEO con angolo originale partendo da notizie già pubblicate dai competitor.

## Modalità di esecuzione

- **Programmatica (backend)**: `from backend.app.skill_runner import generate_article_for_news` — la skill gira in-process, ritorna un `dict` con il payload JSON e NON scrive file. Invocata da `POST /api/news/reconstruct/{news_id}` per salvare direttamente la bozza in Supabase `articles`.
- **CLI (sviluppatore)**: `python scripts/run_agent_sdk_json.py <URL>` — ancora supportata, salva `output/articolo_<slug>.json`.

In entrambi i casi le variabili `ANTHROPIC_API_KEY` e `FIRECRAWL_API_KEY` sono lette dall'ambiente del processo; nel backend vengono caricate da `backend/app/main.py` tramite `load_dotenv()` e non esiste più un `.env` dedicato alla skill.

## Requisiti Input Utente

L'utente DEVE fornire:
1. **URL della notizia** da analizzare (oppure testo della notizia)

L'utente PUÒ opzionalmente fornire:
2. **Livello desiderato**: flash (breve) | editoriale (approfondimento) | evergreen (guida)
3. **Interlink**: URL di articoli del proprio sito da linkare internamente
4. **Target di riferimento**: a chi si rivolge (docenti, studenti, personale ATA, etc.)

Se il livello non è specificato, la skill lo determina automaticamente.

## ⚠️ REGOLE CRITICHE

1. **MAI riscrivere e basta** — L'articolo DEVE avere un angolo diverso dai competitor
2. **MAI inventare dati** — Ogni dato deve essere verificato con fonti primarie
3. **MAI superare i limiti di parole** per livello
4. **MAI usare frasi della blacklist** (vedi references/blacklist_frasi.md)
5. **SEMPRE sentence case** nei titoli (solo prima lettera maiuscola)
6. **SEMPRE fact-check** prima di generare l'articolo finale
7. **SEMPRE output JSON** con metadati SEO, report angolo e fact-check

## Workflow Completo

### STEP 0: Lettura guide obbligatorie

**OBBLIGATORIO** — Prima di iniziare, leggi SEMPRE i file reference della skill:

- `references/angolo_guide.md`
- `references/seo_guidelines.md`
- `references/blacklist_frasi.md`
- `references/article_structure.md`

Usa lo strumento Read per leggerli tutti prima di procedere.

### STEP 1: Leggi la notizia dall'URL

**Strategia di scraping a 3 livelli (fallback):**

1. **Firecrawl** (prioritario): Usa lo script helper dedicato tramite il tool Bash:

   ```bash
   python scripts/firecrawl_scrape.py "[URL]" --format markdown --max-chars 6000
   ```

   Lo script stampa su stdout il contenuto Markdown estratto da Firecrawl (gestisce JavaScript, Cloudflare e la maggior parte dei blocchi anti-bot). Il comando shell `firecrawl scrape` NON esiste: usa sempre lo script.
2. **Web search ricostruttivo**: Se lo script Firecrawl esce con errore o produce output vuoto, ricadi su `WebFetch`/`WebSearch` con keyword estratte dall'URL per ricostruire i fatti principali da più fonti.
3. **Testo dall'utente**: Se anche il web search non restituisce dati sufficienti, chiedi all'utente di incollare il testo dell'articolo direttamente.

**Scraping PDF istituzionali (priorità massima):**

Se l'articolo cita ordinanze, decreti, circolari o bandi, cerca il PDF originale sul sito istituzionale (MIM, GU, INPS, ecc.) e scrapalo con lo script `firecrawl_scrape.py`. Il PDF è la fonte primaria assoluta: contiene scadenze esatte, articoli di legge, eccezioni. Non fidarti mai di come le testate li riportano — estrai i dati direttamente dal documento ufficiale.

Dall'articolo recuperato, estrai:

- Titolo originale
- Testata/fonte
- Fatti principali (chi, cosa, quando, dove, perché)
- Dati numerici citati
- Keyword principale (max 4 parole)
- Tema (scuola, università, ricerca, lavoro, cultura, tecnologia)
- **Riferimenti normativi citati** (OM, DL, DM, circolare) → cercare e scrapare il PDF originale

Classifica automaticamente il livello dell'articolo da generare:
- **flash** (350-500 parole): se è un bando, circolare, scadenza, interpello, notizia breve
- **editoriale** (600-900 parole): se è un tema con dati, polemica, riforma, impatto concreto
- **evergreen** (1000-1500 parole): se è una guida procedurale sempreverde

### STEP 2: Analisi competitor e ricerca angolo

Usa `web_search` per:

1. **Cercare la stessa notizia** con la keyword principale
2. **Leggere i primi 5-8 risultati** dei competitor (Orizzonte Scuola, Tecnica della Scuola, Tuttoscuola, Corriere, Repubblica, etc.)
3. **Per ogni competitor annotare**: che angolo hanno usato, che dati citano, cosa NON dicono
4. **Cercare dati aggiuntivi** che nessun competitor ha usato:
   - Dati ISTAT regionali (se il tema ha variazioni territoriali)
   - Dati storici (per confronto con anni precedenti)
   - Dati europei Eurostat/OCSE (per confronto internazionale)
   - Dati economici concreti (stipendi reali netti, costi, budget)
   - Dichiarazioni di sindacati o associazioni non citate

5. **Proporre un angolo specifico** basato sui gap trovati. L'angolo DEVE contenere dati concreti.

**ANGOLI FORTI (da seguire):**
- "Il dato nazionale nasconde un divario regionale: [dati specifici Nord vs Sud]"
- "Tradotto in netti, l'aumento di X€ lordi = Y€ netti, meno dell'inflazione cumulata"
- "La scadenza è tra 3 giorni ma il 60% delle scuole non ha ancora presentato domanda"
- "L'Italia migliora ma resta sotto la media OCSE di X punti"
- "Il confronto con il [anno precedente] mostra che [dato peggiorato/migliorato di X%]"

**ANGOLI DEBOLI (da scartare):**
- "Analizzare il fenomeno e le sue implicazioni"
- "Approfondire il tema con diverse prospettive"
- "Spiegare l'importanza della questione"

Se NON riesci a trovare un angolo forte con almeno 1 dato aggiuntivo verificabile:
- Se il livello era "editoriale" → declassa a "flash"
- Se il livello era "flash" → genera comunque, ma come notizia breve senza analisi
- Comunica all'utente: "Non ho trovato un angolo forte. Genero come flash."

### STEP 3: Fact-check

Verifica OGNI dato che apparirà nell'articolo. Priorità delle fonti per la verifica:

1. **PDF istituzionali** (massima affidabilità): ordinanze, decreti, circolari scrapati direttamente. Se hai già scrapato il PDF nello step 1, usa quello.
2. **Pagine istituzionali**: siti .gov.it, ISTAT, Eurostat, INPS
3. **Web search**: solo se le fonti primarie non sono disponibili

Per ogni dato:
1. Cerca la **fonte primaria** (non articoli che lo citano, ma il PDF/pagina istituzionale originale)
2. Conferma il numero esatto
3. Se il dato è diverso da quello trovato, correggi
4. Se non è verificabile, rimuovilo dall'angolo

Comunica all'utente i risultati del fact-check:
```
✅ Dato X: CONFERMATO (fonte: [url])
⚠️ Dato Y: PARZIALMENTE CORRETTO — il valore esatto è Z (fonte: [url])
❌ Dato W: NON VERIFICABILE — rimosso dall'angolo
```

### STEP 4: Generazione articolo

Genera l'articolo usando l'angolo verificato. La struttura dipende dal livello:

#### Livello FLASH (350-500 parole):
```
TITLE: [max 55 caratteri, keyword prime 3 parole]
DESCRIPTION: [max 155 caratteri]
H1: [diverso dal title, max 70 caratteri]

Contenuto:
- Prima frase: il fatto principale
- Se c'è scadenza, nella seconda riga
- Fatti essenziali senza riempitivo
- Link fonte ufficiale
- NESSUN indice, NESSUN H3
- Max 2 sezioni H2 se necessario
```

#### Livello EDITORIALE (600-900 parole):
```
TITLE: [max 60 caratteri, con dato specifico o elemento di curiosità]
DESCRIPTION: [max 155 caratteri, promessa di informazione unica]
H1: [diverso dal title, max 75 caratteri, più descrittivo]

Contenuto:
- Apertura con il fatto più rilevante o dato che colpisce
- MAI aprire con "In un contesto di..." o frasi generiche
- L'angolo specifico è il cuore: tutto ruota attorno a quello
- Dati aggiuntivi integrati naturalmente con fonti
- Analisi: perché conta, cosa cambia per docenti/studenti
- Chiusura con prospettiva concreta
- MAI chiusura riassuntiva generica
- Keyword principale max 3 volte in tutto
- Interlink nei punti pertinenti (se forniti dall'utente)
```

#### Livello EVERGREEN (1000-1500 parole):
```
TITLE: [max 60 caratteri, formato "[Cosa] [Anno]: guida completa"]
DESCRIPTION: [max 155 caratteri, specifica il target]
H1: [diverso dal title, max 75 caratteri]

Struttura obbligatoria:
1. Indice con anchor link
2. "In breve" (4-5 punti chiave, max 80 parole)
3. Guida passo-passo numerata con scadenze reali
4. Errori comuni (3-4)
5. FAQ (3-5 domande, risposte 2-3 righe)

Ogni dato normativo deve citare il riferimento di legge.
Date specifiche, mai "nei prossimi mesi".
```

### STEP 5: Output JSON

Genera il JSON finale usando **esclusivamente** lo script `scripts/generate_json_output.py`. Non usare mai altri formati di output (niente DOCX, niente Markdown, niente testo libero).

```python
from scripts.generate_json_output import create_seo_article_json

content_sections = []

# Aggiungi le sezioni dall'articolo generato
# Tipo: 'paragraph', 'h2', 'h3', 'bullet_list', 'numbered_list'
# I link usano formato: [LINK:anchor text|URL]
# I grassetti usano formato: **testo**

create_seo_article_json(
    title=h1_articolo,
    meta_title=title_seo,
    meta_description=description_seo,
    content_sections=content_sections,
    fonti=lista_fonti_usate,
    angolo=angolo_usato,
    livello=livello,
    factcheck_report=risultati_factcheck,
    competitor_report=lista_competitor,
    keyword=keyword_principale,
    source_url=url_notizia_originale,
    output_path='./output/articolo_[keyword_slug].json'
)
```

Il JSON prodotto contiene:
1. **`generated_at`**, **`source_url`**, **`livello`**, **`keyword`**
2. **`seo`**: `meta_title`, `meta_description`, `h1` (con lunghezze controllate)
3. **`angolo`**: stringa con l'angolo scelto
4. **`competitor_report`**: lista `{fonte, angolo_usato, gap}`
5. **`factcheck_report`**: lista `{dato, stato, fonte_primaria}` con stati `confermato | parzialmente_corretto | non_verificabile`
6. **`article.sections`**: sezioni strutturate (`h2`, `h3`, `paragraph`, `bullet_list`, `numbered_list`). Paragrafi e liste contengono **`segments`** già parsati in `{kind: "text|bold|link", text, url?}` — niente markup residuo
7. **`fonti`**: lista `{dato, fonte_url}`
8. **`validation`**: esito con `passed`, `warnings`, `word_count`, lunghezze title/description/H1, `keyword_count`

Al termine comunica all'utente **solo** il percorso del JSON generato e un riassunto di `validation`.

## Checklist Pre-Output

Prima di generare il JSON, verifica TUTTO. Lo script esegue automaticamente le validazioni e le include nel campo `validation`, ma verifica anche manualmente:

**Conteggio parole:**
- [ ] Conta le parole delle content_sections PRIMA di chiamare lo script
- [ ] Se sotto il minimo del livello: espandi la sezione angolo (sezione 2) e impatto pratico (sezione 3)
- [ ] Se sopra il massimo: taglia i passaggi meno essenziali, MAI l'angolo

**Metadati SEO:**
- [ ] Title ≤ 60 caratteri (≤ 55 per flash)
- [ ] Title con keyword nelle prime 3-4 parole
- [ ] Title in sentence case (solo prima lettera maiuscola)
- [ ] Description ≤ 155 caratteri con CTA
- [ ] H1 DIVERSO dal title
- [ ] H1 ≤ 75 caratteri (≤ 70 per flash)

**Contenuto:**
- [ ] Parole entro i limiti del livello (flash 350-500, editoriale 600-900, evergreen 1000-1500)
- [ ] Apertura con fatto concreto, NON generica
- [ ] Chiusura con prospettiva concreta, NON riassuntiva
- [ ] Keyword principale max 3 ripetizioni totali
- [ ] Nessuna frase della blacklist presente
- [ ] Tutti i dati fact-checkati e confermati
- [ ] Angolo effettivamente diverso dai competitor

**Link in uscita (CRITICO):**
- [ ] Ogni link punta SOLO a siti istituzionali (.gov.it, .europa.eu, ISTAT, INPS, ecc.)
- [ ] Ogni link è stato verificato con scrape: pagina con contenuto reale, no redirect, no pagina vuota
- [ ] Ogni link ha anchor text descrittiva che dice all'utente cosa troverà
- [ ] Nessun URL nudo, nessun "clicca qui", nessun "fonte"
- [ ] Nessun link a testate, blog, sindacati o qualsiasi sito non istituzionale

**Anti-invenzione:**
- [ ] Nessun dato inventato
- [ ] Ogni dato numerico ha una fonte verificabile
- [ ] Nessuna dichiarazione attribuita senza fonte

## Esempi di Utilizzo

### Esempio 1: URL di notizia
```
Utente: "Riscrivi questa notizia con un angolo diverso:
https://www.orizzontescuola.it/dispersione-scolastica-in-calo/"
```

### Esempio 2: URL con livello specificato
```
Utente: "Fammi un editoriale partendo da questa notizia:
https://www.tecnicadellascuola.it/contratto-scuola-firmato"
```

### Esempio 3: URL con interlink
```
Utente: "Riscrivi con angolo diverso. Linka anche questi articoli del mio sito:
URL: https://www.orizzontescuola.it/100-milioni-ai-scuola/
Interlink: https://edunews24.it/scuola/formazione-docenti-ai
https://edunews24.it/scuola/piano-scuola-40"
```

## Resources

### Scripts
- `generate_json_output.py`: **Unico output ufficiale.** Genera JSON strutturato con metadati SEO, report angolo/factcheck, articolo con sezioni e segmenti inline (text/bold/link) già parsati, e blocco di validazione
- `run_agent_sdk_json.py`: runner Claude Agent SDK che esegue la skill end-to-end via API e salva il JSON in `./output/`

### References
- `angolo_guide.md`: Come trovare un angolo forte con esempi concreti
- `seo_guidelines.md`: Regole SEO per titoli, meta, struttura
- `blacklist_frasi.md`: Frasi AI vietate da eliminare
- `article_structure.md`: Struttura articolo per ogni livello
