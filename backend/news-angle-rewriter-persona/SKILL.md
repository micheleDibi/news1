---
name: news-angle-rewriter-persona
description: Variante di news-angle-rewriter che consente all'utente di scegliere TONO (Neutrale, Formale, Informale, Persuasivo, Umoristico, Serio, Ottimistico, Motivazionale, Rispettoso, Assertivo, Conversazione) e PERSONA (Copywriter, Giornalista, Blogger, Esperto di settore, Freelance, Accademico, Saggista, Attivista, Divulgatore Scientifico, Insegnante). Prende l'URL di una notizia pubblicata da un competitor — oppure un argomento/topic, nel qual caso seleziona automaticamente l'articolo competitor più autorevole e recente — analizza come è stata coperta, trova un angolo originale coerente con la persona scelta, fact-checka tutto, e genera un articolo JSON ottimizzato SEO scritto nel tono richiesto. Usa questa skill quando l'utente fornisce un URL, un testo o un topic di notizia insieme a una scelta di tono e persona, o quando chiede "riscrivi come [persona] con tono [tono]", "adatta questa notizia alla voce di un [persona]".
---

# News Angle Rewriter – Persona Edition

Variante della skill `news-angle-rewriter` con due parametri aggiuntivi scelti dall'utente: **tono** e **persona**. La logica di scraping, analisi competitor, fact-check e output JSON è identica; cambiano **STEP 2 (scelta angolo)** e **STEP 4 (scrittura)** in base alla combinazione richiesta. Tutti i vincoli originali (blacklist, limiti parole, sentence case, link solo istituzionali) restano invariati.

## Modalità di esecuzione

- **Programmatica (backend)**: `from backend.app.skill_runner import generate_article_for_news` — la skill gira in-process, ritorna un `dict` con il payload JSON e NON scrive file. Invocata da `POST /api/news/reconstruct/{news_id}` passando anche `tono` e `persona` scelti dalla UI.
- **CLI (sviluppatore)**: `python scripts/run_agent_sdk_json.py <URL> --tono <tono> --persona <persona>` — ancora supportata, salva `output/articolo_<slug>.json`.

In entrambi i casi le variabili `ANTHROPIC_API_KEY` e `FIRECRAWL_API_KEY` sono lette dall'ambiente del processo.

## Requisiti Input Utente

L'utente DEVE fornire:
1. **Input notizia** — almeno uno di:
   - **URL della notizia** da analizzare (preferito)
   - **Testo della notizia** incollato direttamente
   - **Argomento/topic** — la skill seleziona automaticamente l'articolo competitor più autorevole e recente via STEP 0.5

L'utente PUÒ opzionalmente fornire:
2. **Tono**: `Neutrale` (default) | `Formale` | `Informale` | `Persuasivo` | `Umoristico` | `Serio` | `Ottimistico` | `Motivazionale` | `Rispettoso` | `Assertivo` | `Conversazione`
3. **Persona**: `Giornalista` (default) | `Copywriter` | `Blogger` | `Esperto di settore` | `Freelance` | `Accademico` | `Saggista` | `Attivista` | `Divulgatore Scientifico` | `Insegnante`
4. **Livello desiderato**: `flash` (breve) | `editoriale` (approfondimento) | `evergreen` (guida)
5. **Interlink**: URL di articoli del proprio sito da linkare internamente
6. **Target di riferimento**: a chi si rivolge (docenti, studenti, personale ATA, ecc.)

**Default fissi**: se tono o persona non sono specificati, la skill parte con `Giornalista + Neutrale` senza chiedere conferma. Se il livello non è specificato, la skill lo determina automaticamente dallo step 1.

## ⚠️ REGOLE CRITICHE

1. **MAI riscrivere e basta** — L'articolo DEVE avere un angolo diverso dai competitor
2. **MAI inventare dati** — Ogni dato deve essere verificato con fonti primarie
3. **MAI superare i limiti di parole** per livello (tono e persona non sbloccano il limite)
4. **MAI usare frasi della blacklist** (vedi `references/blacklist_frasi.md`), nemmeno quando il tono lo suggerirebbe
5. **SEMPRE sentence case** nei titoli (solo prima lettera maiuscola)
6. **SEMPRE fact-check** prima di generare l'articolo finale
7. **SEMPRE output JSON** con metadati SEO, report angolo, fact-check, tono e persona usati
8. **SEMPRE rispettare la tabella dei blocchi tono/persona** — se la combinazione è incoerente, NON generare l'articolo

## Workflow Completo

### STEP 0: Lettura guide obbligatorie

**OBBLIGATORIO** — Prima di iniziare, leggi SEMPRE i file reference della skill:

- `references/angolo_guide.md`
- `references/seo_guidelines.md`
- `references/blacklist_frasi.md`
- `references/article_structure.md`
- `references/tono_persona_guide.md`  ← **nuovo, obbligatorio anche se l'utente usa i default**

Usa lo strumento Read per leggerli tutti prima di procedere. Il reference `tono_persona_guide.md` contiene:
- Descrizione dettagliata di ciascuna delle 11 opzioni di tono e delle 10 opzioni di persona
- Tabella delle combinazioni bloccate con messaggio utente esatto da usare
- Regole di priorità quando tono e persona suggeriscono scelte diverse

### STEP 0.5: Risoluzione topic → URL (solo se input = argomento)

Applica questo step **solo** se l'utente ha fornito un argomento/topic senza URL e senza testo. Se ha fornito URL o testo, salta direttamente allo STEP 1.

**1. Ricerca candidati**

Usa `web_search` con le keyword del topic, ordinando per data più recente. Raccogli 8-10 candidati annotando: titolo, URL, fonte/dominio, data di pubblicazione, snippet.

**2. Classificazione per tier di autorevolezza**

- **Tier 1** (massima autorevolezza):
  - Domini istituzionali: `.gov.it`, MIM, MUR, INPS, ISTAT, Eurostat, Agenzia Entrate, Gazzetta Ufficiale
  - Testate nazionali generaliste: Corriere della Sera, Repubblica, ANSA, Sole24Ore, La Stampa
- **Tier 2** (specializzate scuola/istruzione):
  - Orizzonte Scuola, Tecnica della Scuola, Tuttoscuola, Scuolainforma
- **Tier 3** (scartati salvo sia l'unico risultato disponibile):
  - Blog personali, aggregatori automatici, siti minori non redazionali, social media, UGC

**3. Ranking ponderato**

Per ciascun candidato calcola uno score 0-100:

- **Autorevolezza (40%)**: Tier 1 = 40 · Tier 2 = 28 · Tier 3 = 10
- **Rilevanza (35%)**:
  - Keyword topic presente nel titolo: +20
  - Tema coerente con dominio Edunews24 (scuola, università, ricerca, lavoro, cultura, tecnologia): +15
- **Freshness (25%)**:
  - ≤7 giorni: 25
  - 8-30 giorni: 12
  - \>30 giorni: 0 (escluso, salvo notizia normativa/evergreen dove il dato resta valido)

**4. Selezione e comunicazione**

Seleziona silenziosamente il candidato con score più alto. **NON** chiedere conferma all'utente. Comunica in una riga sola:

```
Topic: [topic utente] → selezionato: [URL] ([fonte], [data pubblicazione]). Procedo.
```

Poi prosegui allo STEP 1 usando l'URL selezionato come input.

**5. Fallback: nessun candidato valido**

Se dopo il ranking nessun candidato supera la soglia minima — ovvero:
- tutti i risultati sono Tier 3, **oppure**
- tutti i risultati hanno freshness >30 giorni (e la notizia non è normativa/evergreen), **oppure**
- la web search non restituisce risultati pertinenti al topic

ferma il workflow e rispondi:

```
⚠️ Non ho trovato coperture recenti e autorevoli sul topic: "[topic]".

Fornisci uno di:
- URL specifico dell'articolo competitor da rigenerare
- Testo dell'articolo incollato direttamente
- Un topic più circoscritto (es. invece di "AI in agricoltura", prova "bando PNRR agricoltura 4.0 2026")

Non procedo finché non ricevo un input più specifico.
```

Non generare JSON, non chiamare lo script di output. Aspetta la risposta dell'utente.

### STEP 1: Recupera il contenuto della notizia

**Strategia di scraping a 3 livelli (fallback):**

1. **Firecrawl** (prioritario): usa lo script helper dedicato tramite il tool Bash:

   ```bash
   python scripts/firecrawl_scrape.py "[URL]" --format markdown --max-chars 6000
   ```

2. **Web search ricostruttivo**: se lo script Firecrawl fallisce o produce output vuoto, ricadi su `WebFetch`/`WebSearch` con keyword estratte dall'URL.
3. **Testo dall'utente**: se anche il web search non basta, chiedi all'utente di incollare il testo dell'articolo direttamente.

**Scraping PDF istituzionali (priorità massima):**

Se l'articolo cita ordinanze, decreti, circolari o bandi, cerca il PDF originale sul sito istituzionale (MIM, GU, INPS, ecc.) e scrapalo con lo stesso script. Il PDF è la fonte primaria assoluta.

Dall'articolo recuperato, estrai:
- Titolo originale
- Testata/fonte
- Fatti principali (chi, cosa, quando, dove, perché)
- Dati numerici citati
- Keyword principale (max 4 parole)
- Tema (scuola, università, ricerca, lavoro, cultura, tecnologia)
- Riferimenti normativi citati

Classifica automaticamente:
- **Livello** dell'articolo: flash (350-500 parole, bando/circolare/scadenza), editoriale (600-900 parole, riforma/polemica/impatto), evergreen (1000-1500 parole, guida sempreverde)
- **Natura della notizia** per la validazione tono/persona:
  - *istituzionale*: bando, decreto, ordinanza, circolare, DM, DL, DPR, concorso, avviso, interpello, scadenze GU/MIM/INPS, procedure amministrative
  - *negativa*: tagli, bocciature, dispersione, inchieste, scandali, licenziamenti, crisi, infortuni, bilancio peggiorato
  - *neutra/positiva*: tutto il resto

Salvati queste due classificazioni: ti servono per validare tono+persona allo STEP 1.5.

### STEP 1.5: Validazione combinazione tono + persona (NUOVO)

Prima di procedere oltre, confronta la combinazione `tono + persona` richiesta con la tabella dei blocchi in `references/tono_persona_guide.md`:

| # | Blocco | Applicare quando |
|---|---|---|
| 1 | `Umoristico` + qualsiasi persona | natura notizia = *istituzionale* |
| 2 | `Umoristico` + {`Accademico`, `Esperto di settore`, `Insegnante`} | sempre |
| 3 | `Conversazione` + `Accademico` | sempre |
| 4 | `Persuasivo` + `Giornalista` | natura notizia = *istituzionale* o cronaca/normativa |
| 5 | `Motivazionale` o `Ottimistico` + qualsiasi persona | natura notizia = *negativa* |
| 6 | `Informale` + `Accademico` | sempre |

Se la combinazione ricade in uno dei blocchi, **ferma immediatamente il workflow** e rispondi all'utente con questo messaggio (compilando i placeholder):

```
⚠️ Combinazione non consentita: [tono] + [persona] su [tipo notizia rilevato].

Motivo: [motivo dalla tabella del reference].

Alternative consigliate:
- Mantieni la persona [persona], cambia tono in [alternativa_1] o [alternativa_2]
- Mantieni il tono [tono], cambia persona in [alternativa_1] o [alternativa_2]
- Oppure scegli un URL di notizia non [istituzionale/negativa]

Non procedo alla generazione. Rispondi con una combinazione valida per continuare.
```

Le alternative specifiche per blocco sono nel reference. NON generare JSON parziale, NON chiamare lo script di output. Aspetta la risposta dell'utente.

Se la combinazione è valida, procedi allo STEP 2.

### STEP 2: Analisi competitor e ricerca angolo (condizionato dalla persona)

Usa `web_search` per:

1. Cercare la stessa notizia con la keyword principale
2. Leggere i primi 5-8 risultati dei competitor (Orizzonte Scuola, Tecnica della Scuola, Tuttoscuola, Corriere, Repubblica, ecc.)
3. Per ogni competitor annotare: angolo usato, dati citati, cosa NON dicono
4. Cercare dati aggiuntivi che nessun competitor ha usato:
   - Dati ISTAT regionali (se il tema ha variazioni territoriali)
   - Dati storici (per confronto con anni precedenti)
   - Dati europei Eurostat/OCSE
   - Dati economici concreti (stipendi netti, costi, budget)
   - Dichiarazioni di sindacati/associazioni non citate

5. **Proporre l'angolo tenendo conto della persona scelta.** Tra i gap trovati, privilegia quello più coerente con la persona (vedi `references/tono_persona_guide.md` sezione "Angoli preferiti"):
   - **Giornalista**: fatto principale + contesto + confronto dati + reazioni
   - **Accademico**: confronto storico o internazionale, analisi strutturale
   - **Attivista**: divario/ingiustizia, gap tra dato ufficiale e campo
   - **Divulgatore Scientifico**: "perché funziona così", meccanismo spiegato
   - **Esperto di settore**: dettaglio tecnico-normativo non notato dagli altri
   - **Insegnante**: impatto concreto in aula
   - **Copywriter**: beneficio/urgenza/azione per il lettore
   - **Blogger**: punto di vista personale su un fatto ampio
   - **Freelance**: sintesi operativa, checklist di scadenze
   - **Saggista**: il fatto come sintomo di processo più ampio

L'angolo DEVE contenere dati concreti verificabili, indipendentemente dalla persona.

Se NON riesci a trovare un angolo forte coerente con la persona:
- Prima fallback: cerca un angolo forte *generico* (ignorando la persona) e adattalo nello stile di scrittura
- Secondo fallback: se nemmeno questo emerge, declassa il livello (editoriale → flash, flash → notizia breve)
- Comunica all'utente: "Non ho trovato un angolo coerente con persona=[X]. Uso angolo generico: [angolo]. Lo adatto comunque nello stile [persona]+[tono] per la scrittura."

### STEP 3: Fact-check

Verifica OGNI dato che apparirà nell'articolo. **Il fact-check è indipendente da tono e persona**: nessuna combinazione giustifica saltare o ammorbidire la verifica.

Priorità fonti:
1. PDF istituzionali (massima affidabilità)
2. Pagine istituzionali (.gov.it, ISTAT, Eurostat, INPS)
3. Web search (solo se le fonti primarie non sono disponibili)

Per ogni dato:
1. Cerca la fonte primaria
2. Conferma il numero esatto
3. Se il dato è diverso, correggi
4. Se non è verificabile, rimuovilo

Report al termine:
```
✅ Dato X: CONFERMATO (fonte: [url])
⚠️ Dato Y: PARZIALMENTE CORRETTO — valore esatto Z (fonte: [url])
❌ Dato W: NON VERIFICABILE — rimosso
```

### STEP 4: Generazione articolo (condizionata da tono + persona)

Genera l'articolo usando l'angolo verificato. La struttura di base dipende dal **livello**, la **struttura retorica** dipende dalla **persona**, il **registro lessicale** dipende dal **tono**.

**Regole di priorità quando tono e persona entrano in conflitto**:
- La **persona** prevale sulla **struttura retorica** (apertura, sviluppo, chiusura)
- Il **tono** prevale sul **registro lessicale** (scelta parole, costruzione frasi)
- In ogni caso prevale il rispetto dei vincoli SEO e blacklist

**Applicazione simultanea** (vedi `references/tono_persona_guide.md`):
1. Scegli la struttura retorica della persona:
   - Es. Giornalista: lead (chi/cosa/quando/dove/perché) → contesto → dati → reazioni
   - Es. Accademico: dato → riferimento normativo/studio → analisi → implicazioni
   - Es. Attivista: dato che smaschera divario → conseguenze → richiesta
2. Applica il registro del tono:
   - Es. Neutrale: indicative, verbi al presente, niente esclamazioni
   - Es. Formale: subordinate articolate, lessico normativo
   - Es. Assertivo: affermazioni nette supportate, no attenuazioni
3. Verifica che l'apertura segua la persona ma nel registro del tono. Evita sempre aperture generiche tipo "In un contesto di..."

#### Livello FLASH (350-500 parole)
```
TITLE: [max 55 caratteri, keyword nelle prime 3 parole]
DESCRIPTION: [max 155 caratteri]
H1: [diverso dal title, max 70 caratteri]

Contenuto:
- Prima frase: il fatto principale (nello stile della persona)
- Se c'è scadenza, nella seconda riga
- Fatti essenziali senza riempitivo
- Link fonte ufficiale
- NESSUN indice, NESSUN H3
- Max 2 sezioni H2 se necessario
```

#### Livello EDITORIALE (600-900 parole)
```
TITLE: [max 60 caratteri, con dato specifico]
DESCRIPTION: [max 155 caratteri, promessa di informazione unica]
H1: [diverso dal title, max 75 caratteri]

Contenuto:
- Apertura nello stile della persona (mai "In un contesto di...")
- Angolo specifico come cuore: tutto ruota attorno
- Dati aggiuntivi integrati con fonti
- Analisi: perché conta, cosa cambia per docenti/studenti
- Chiusura con prospettiva concreta, nello stile della persona
- MAI chiusura riassuntiva generica
- Keyword principale max 3 volte in tutto
- Interlink nei punti pertinenti (se forniti)
```

#### Livello EVERGREEN (1000-1500 parole)
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

Il registro della guida è governato dal tono.
La voce delle FAQ è governata dalla persona.
```

### STEP 5: Output JSON

Genera il JSON finale usando **esclusivamente** lo script `scripts/generate_json_output.py` passando anche `tono` e `persona`:

```python
from scripts.generate_json_output import create_seo_article_json

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
    tono=tono_scelto,           # NUOVO
    persona=persona_scelta,     # NUOVO
    output_path='./output/articolo_[keyword_slug].json'
)
```

Il JSON contiene gli stessi campi della skill base più un blocco `meta`:

```json
"meta": {
  "tono": "Neutrale",
  "persona": "Giornalista"
}
```

Al termine comunica all'utente **solo** il percorso del JSON generato e un riassunto di `validation` + `meta`.

## Checklist Pre-Output

Oltre alla checklist della skill base, verifica:

**Tono e Persona:**
- [ ] Combinazione `tono + persona` non rientra nella tabella dei blocchi per la natura della notizia
- [ ] Apertura coerente con la struttura retorica della persona scelta
- [ ] Registro lessicale coerente con il tono scelto (vedi `tono_persona_guide.md` "evitare/preferire")
- [ ] Nessuna frase della blacklist è stata introdotta dal tono (es. il tono Persuasivo NON può usare "è il momento di aspettare che" se "aspettare" è vietato)
- [ ] `meta.tono` e `meta.persona` presenti nel JSON di output

**Anti-drift:**
- [ ] L'articolo rispetta il limite parole del livello, anche se il tono tende a espandere (es. Conversazione) o comprimere (es. Freelance)
- [ ] Il fact-check non è stato ammorbidito per soddisfare il tono (es. Ottimistico non omette dati sfavorevoli)

Tutto il resto della checklist è ereditato da `news-angle-rewriter` (parole, metadati SEO, contenuto, link in uscita, anti-invenzione).

## Esempi di Utilizzo

### Esempio 1: combinazione valida
```
Utente: "Riscrivi questa notizia come Divulgatore Scientifico, tono Conversazione:
https://www.orizzontescuola.it/dispersione-scolastica-in-calo/"
```
→ La skill classifica la notizia come *neutra*, valida la combinazione (`Conversazione + Divulgatore Scientifico` non è bloccata), cerca un angolo con meccanismo spiegabile (es. "perché la dispersione cala al Nord ma non al Sud?"), scrive con registro dialogico.

### Esempio 2: combinazione bloccata
```
Utente: "Fammi un editoriale con persona Insegnante e tono Umoristico su:
https://www.tecnicadellascuola.it/ordinanza-esame-di-stato"
```
→ La skill rileva `Umoristico + Insegnante` (blocco #2) **e** natura istituzionale (blocco #1). Ferma il workflow e risponde col messaggio di blocco, proponendo `Informale + Insegnante` o `Umoristico + Blogger` su notizia non istituzionale.

### Esempio 3: default
```
Utente: "Riscrivi con angolo diverso questa notizia:
https://www.orizzontescuola.it/contratto-scuola-firmato"
```
→ L'utente non ha specificato tono/persona: la skill usa `Giornalista + Neutrale` senza chiedere.

## Resources

### Scripts
- `generate_json_output.py`: unico output ufficiale, genera JSON con `meta.tono` e `meta.persona`
- `run_agent_sdk_json.py`: runner Claude Agent SDK con flag `--tono` e `--persona`
- `firecrawl_scrape.py`: helper scraping

### References
- `angolo_guide.md`: come trovare un angolo forte con esempi concreti
- `seo_guidelines.md`: regole SEO per titoli, meta, struttura
- `blacklist_frasi.md`: frasi AI vietate
- `article_structure.md`: struttura articolo per ogni livello
- `tono_persona_guide.md`: descrizione di tutti i 11 toni e 10 persone, tabella blocchi, messaggio utente per combinazioni non consentite
