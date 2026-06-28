---
name: bandi-seo-enricher
description: Arricchisce UN singolo bando (grant/tender italiano o europeo) dato il suo link. Scrapa la pagina istituzionale e gli eventuali PDF allegati, estrae i campi strutturati (scadenza, beneficiari, importo, ente, link candidatura), calcola lo stato scadenza e genera contenuto editoriale SEO su misura (flash o guida), restituendo UN JSON pronto per la tabella Supabase `bandi` di edunews24.it. Usa questa skill quando l'utente passa un URL di bando e chiede "arricchisci questo bando", "scheda questo bando", "genera il JSON di questo bando", "analizza questo bando". UNA sola URL per invocazione: NON gestisce CSV, batch, dedup, stato o upload (li gestisce il progetto che incorpora la skill).
---

# Bandi SEO Enricher

Skill **single-bando**: dato il link di UN bando nazionale o europeo, produce UN JSON con dati strutturati + contenuto SEO, pronto per la tabella `bandi` su Supabase.

## Quando usarla

L'utente (o il sistema che incorpora la skill) fornisce **un singolo URL di bando**. La skill scrapa la pagina e gli allegati, estrae i campi, genera contenuto editoriale su misura e restituisce **un solo JSON** (su stdout o, opzionalmente, su un file singolo).

La skill NON itera su liste/CSV, NON deduplica, NON tiene stato, NON fa upload: deduplica, orchestrazione e storage sono responsabilità del progetto a valle. Una invocazione = un bando = un JSON.

I bandi NON sono articoli editoriali: vivono nella tabella `bandi` con campi colonna (scadenza, importo, beneficiari) e pagina dettaglio dedicata `/bandi/<slug>`.

## Requisiti input

L'utente DEVE fornire:
- **1 URL del bando** (`link_bando`).

L'utente PUÒ opzionalmente fornire:
1. **Hint dominio override** `{"ente": "...", "tipologia": "...", "area": "..."}` (default: l'hint arriva dall'orchestrator che lo costruisce dai dati relazionali del DB del scraper; l'override utente vince).
2. **Percorso di output** del JSON (default: stdout; es. `output/<slug>.json` per scrivere su file).
3. **Livello forzato** `flash_bando` | `guida_bando` (default: lo classifica la skill).

## ⚠️ REGOLE CRITICHE

1. **MAI inventare campi strutturati** — Se `scadenza`, `importo` o `beneficiari` non sono ricavabili dal bando, il campo resta `null` (o array vuoto). Mai stimare.
2. **MAI usare `source_url` come fallback di `link_candidatura`** — Se non trovi un link verificato a un modulo/sportello di partecipazione: `link_candidatura = null`, `link_candidatura_source = "missing"`. Se hai trovato un link dedicato alla candidatura: `link_candidatura = <url>`, `link_candidatura_source = "extracted"`. Il fallback su `source_url` causava confusione (CTA puntavano alla stessa pagina del bando); usare `link_candidatura_source = "fallback_source"` SOLO se autorizzato dall'orchestrator. Il frontend gestisce NULL.
3. **MAI superare i limiti SEO** — `meta_title` ≤ 60 char, `meta_description` ≤ 155 char, `titolo` (H1) ≤ 80 char, `meta_title` ≠ `titolo`.
4. **MAI usare frasi della blacklist** (vedi `references/blacklist_frasi.md`).
5. **SEMPRE sentence case** nei titoli (solo prima lettera maiuscola, no Title Case; sigle e nomi propri restano).
6. **SEMPRE citare la fonte istituzionale** — Ogni dato strutturato deve avere un'entry in `fonti[]` con `dato` + `fonte_url`.
7. **SEMPRE produrre JSON valido** che mappa 1:1 le colonne della tabella `bandi` su Supabase.
8. **MAI contenuto generico/placeholder** — Genera SEMPRE contenuto editoriale ricco e specifico per quel bando (vedi STEP 6). Niente sezioni stub.
9. **SEMPRE dare un verdetto di validita'** — Compila `validation.is_valid_bando` (true/false). Sei l'autorita' finale: l'orchestrator usa il tuo verdetto per decidere se mostrare il record. Le pagine indice/ricerca/categoria/archivio = `is_valid_bando: false` con `rejection_category` (vedi STEP 2.5).
10. **COERENZA DATE** — `data_pubblicazione <= data_scadenza` SEMPRE. Se la tua estrazione produce date incoerenti (pubblicazione futura rispetto a scadenza, scadenza nel passato remoto rispetto a oggi senza essere uno storico chiaro), ALMENO una delle due e' sbagliata: lascia entrambe `null` con `source = "missing"` invece di persistere dati incoerenti. Un downstream verifier adversarial (Claude Haiku) controlla questa coerenza e bocciera' il payload se viola.
11. **DEFAULT REJECT** — In assenza di markers M1+M2+M3 espliciti (vedi STEP 2.5), `is_valid_bando = false`. NIENTE "true perche' nel titolo del sito c'e' la parola bando/call/opportunity". L'assenza di prove e' una bocciatura, non un dubbio.
12. **CITATION OBBLIGATORIA SULLE DATE** — Per ogni `scadenza` e `data_pubblicazione` non-null DEVI emettere il rispettivo `*_quote`: frammento LETTERALE del markdown/PDF sorgente (max 300 char) che contiene la data + 20-30 char di contesto. Se non riesci a citare letteralmente: `source = "missing"`, data `null`, quote `null`. Il validator Python rifiuta JSON con date senza quote.

## Workflow

### STEP 0 — Lettura guide obbligatorie

**OBBLIGATORIO** — Prima di iniziare, leggi con lo strumento `Read` tutte le reference:

- `references/bando_data_extraction.md` — quali campi estrarre e come riconoscerli
- `references/article_structure.md` — struttura editoriale per livello (flash/guida)
- `references/seo_guidelines.md` — regole meta/titolo/slug
- `references/blacklist_frasi.md` — frasi vietate

### STEP 1 — Hint dominio

L'hint dominio ti arriva **come parametro dal prompt** dell'orchestrator. L'orchestrator (`news1/backend/app/bandi.py::build_hint_from_bando`) lo costruisce dai dati relazionali del DB scraper: `tipologia_grezza`, `programma`, `beneficiari[]`, `regioni[]`, `settori[]`, `ateco[]`, metadati grezzi (codice_bando, fondo, data_scadenza_grezza, data_pubblicazione_grezza, importo_grezzo, titolo_grezzo, descrizione_grezza). **Non cercare file di config sul filesystem**: l'hint che ricevi nel prompt e' tutto cio' che ti serve. Gli hint sono default: vanno SEMPRE sovrascritti se il bando dichiara qualcosa di diverso.

### STEP 2 — Markdown sorgente

**v4 — Markdown pre-scaricato**: l'orchestrator ha gia' scaricato il markdown della pagina via Firecrawl e te lo passa nel system prompt sotto la variabile `MARKDOWN_INPUT_PATH`. Leggilo con `Read file_path=<MARKDOWN_INPUT_PATH>` come PRIMA cosa. Usa quel markdown come fonte autoritativa.

**NON re-invocare Firecrawl sulla stessa URL del bando** — e' spreco di tempo (~5s) e di quota API, e il verifier downstream riusa lo stesso markdown.

Firecrawl resta disponibile per scaricare URL aggiuntive (es. **PDF allegati** linkati dalla pagina principale):

```bash
python scripts/firecrawl_scrape.py "[URL_ALLEGATO_PDF]" --format markdown --max-chars 20000
```

Se per qualche motivo il markdown pre-scaricato non c'e' (variabile `MARKDOWN_INPUT_PATH` assente nel system prompt) o e' vuoto:
1. Tenta `python scripts/firecrawl_scrape.py "[URL_BANDO]" --format markdown --max-chars 20000`
2. Se Firecrawl restituisce vuoto: ricadi su `WebFetch`
3. Se ancora nulla: **STOP** — riporta `scrape_failed`. NON emettere un JSON inventato.

Richiede la variabile d'ambiente `FIRECRAWL_API_KEY`.

### STEP 2.5 — Verdetto di validita' (prima dell'estrazione)

Prima di estrarre qualsiasi campo, decidi se la pagina e' davvero **UN bando candidabile, singolo, attivo**. Usa il **check markers** sotto, NON una valutazione "a sentimento". Default: `is_valid_bando = false`. Si promuove a `true` SOLO se tutti i positive markers M1+M2+M3 sono presenti **e** nessun negative marker (N1-N4) scatta.

#### Positive markers — TUTTI E TRE richiesti per `is_valid_bando = true`

- **M1 — Titolo specifico di UNA call univoca**: identifica un'unica opportunita'. Esempi BOCCIATI: "Opportunities", "Bandi in corso", "Calendario preavvisi 2025", "Programma X 2021-2027", "Call 7 — Mediterranean Multiprogramme Mechanism", "Tutti i bandi della Regione Y". Esempi BUONI: "Voucher scuola Piemonte 2026-2027", "Avviso pubblico SUAP per esercizi vicinato 2026", "Interreg Euro-MED Call 2 — Progetti tematici 2022".
- **M2 — Ente erogatore identificabile come riga di testo nel contenuto** della pagina (non solo come logo nell'header del sito o footer istituzionale). Deve essere il soggetto che eroga il finanziamento per QUESTA call specifica.
- **M3 — Scadenza esplicita con LABEL** ("Termine presentazione domande", "Deadline", "Closing date", "Scade il", "Entro il giorno", "Termine ultimo") **+** una data parsabile (`YYYY-MM-DD`, `DD/MM/YYYY`, `30 settembre 2026`). **Senza label esplicita una data presente nel testo NON conta**: una data generica nel contenuto puo' essere un riferimento normativo, una data storica, una data di pubblicazione del programma, ecc.

#### Negative markers — UNO SOLO basta per `is_valid_bando = false`

- **N1 — Aggregator/listing**: la pagina enumera ≥3 sub-call con propri link figlio (`<a>` distinti verso URL diversi, ognuno con label tipo "Bando X", "Call Y", "Apply now"). Mappatura: `rejection_category = "index_page"`. Caso reale: `interregnextmed.eu/stay-informed/opportunities`.
- **N2 — Calendar / preavvisi / cronoprogramma**: filename PDF contiene `calendario|preavvisi|cronoprogramma|programmazione`, oppure il documento e' una tabella di future call previste con multiple scadenze in righe diverse. Mappatura: `rejection_category = "not_a_funding_call"`. Caso reale: `Calendario preavvisi FESR_III agg.2025-1.pdf` (Valle d'Aosta).
- **N3 — Programme landing page**: la pagina descrive il programma generale (priorita', assi tematici, governance, totale risorse pluriennale, organi di gestione) senza una scadenza specifica della call corrente. Mappatura: `rejection_category = "category_page"`. Tipico match: URL `/call-N-mechanism|programme|coordinated-call|annual`. Caso reale: `interreg-euro-med.eu/en/call-7-mediterranean-multiprogramme-mechanism-coordinated-call`.
- **N4 — URL match `/call-\d+-...` ma contenuto solo descrittivo**: senza M3 esplicito → `category_page`. Pagina del programma, non della call.

#### Enum `rejection_category` (fissi sei valori; mappa i casi sopra ai valori esistenti)

- `index_page` — pagina aggregatrice / listing di piu' bandi (N1, e classico "Tutti i bandi della Regione X").
- `search_results` — risultati di una ricerca interna ("ricerca voucher").
- `category_page` — pagina categoria/tag, programme landing page (N3, N4).
- `expired_archive` — archivio di bandi chiusi senza bando attivo specifico.
- `not_a_funding_call` — pagina che non parla di finanziamenti, calendari preavvisi (N2), modulistica generale, pagina istituzionale.
- `unreachable` — URL non raggiungibile o redirect verso pagina non-bando.

#### Output e comportamento

Sempre compila `validation.validation_reason` (1-2 frasi che spiegano la decisione, citando il marker scattato: "M3 mancante: nessuna label di scadenza nel markdown", "N1: 5 sub-call elencate nel listing", ecc).

**Se `is_valid_bando = false`:**
- Puoi saltare STEP 3-7 (estrazione, contenuto SEO) e produrre placeholder/null per i campi mancanti.
- DEVI comunque emettere il JSON con `validation.is_valid_bando = false`, `validation.rejection_category` valorizzato, `validation.validation_reason` esplicito.
- L'orchestrator usera' questo verdetto per nascondere il record dal frontend (RLS filtra `is_bando_confermato=false` e `rejection_category IS NOT NULL`).

**Se `is_valid_bando = true`:** procedi con STEP 3 → STEP 7, ricordando **regola critica #12 (citation obbligatoria sulle date)**.

### STEP 3 — PDF allegati e raccolta link documenti

Se nel markdown trovi link a PDF di bando/avviso/regolamento/allegato (estensione `.pdf`), scrapali con lo stesso comando e usali come **fonte primaria** per scadenza/importo/beneficiari. **Il PDF batte sempre la pagina web.** Se PDF e pagina divergono, vince il PDF e annota la discrepanza in `factcheck_report`.

**RACCOLTA ALLEGATI (obbligatorio)** — Durante la lettura del markdown della pagina istituzionale e dei PDF, raccogli TUTTI gli URL a file con estensioni `.pdf`, `.doc`, `.docx`, `.zip`, `.rtf`, `.xlsx`, `.xls`, `.odt`, `.ods` (modulistica, regolamenti, allegati tecnici, FAQ ufficiali, schemi di domanda). Per ogni allegato componi un oggetto:

```json
{"label": "Modulo di candidatura", "url": "https://.../modulo.pdf", "tipo": "pdf"}
```

- **`label`**: testo del link che porta al file (es. testo nel `[testo](url)` markdown). Fallback se il link è solo un'icona o un URL nudo: usa il nome del file senza estensione, con underscore/dash convertiti in spazi e sentence case.
- **`url`**: URL assoluto (risolvi gli URL relativi rispetto a `source_url`).
- **`tipo`**: una stringa tra `pdf | doc | docx | zip | rtf | xlsx | xls | odt | ods | altro` derivata dall'estensione (lowercase). Usa `altro` se l'estensione non è in lista.

Includi questi oggetti nell'array `allegati[]` del JSON di output (vedi STEP 7). Se la pagina non ha file allegati: emetti `"allegati": []`. Niente duplicati: deduplica per URL.

### STEP 4 — Estrazione campi strutturati

```bash
python scripts/extract_bando_fields.py --markdown-file [scratch.md] --url "[URL]" --hint '{"ente":"Regione Lombardia","tipologia":"FESR","area":"Lombardia"}'
```

Lo script applica regex/euristiche (IT-centriche) per estrarre: `scadenza` (ISO `YYYY-MM-DD`), `importo_totale_eur` / `importo_max_per_progetto_eur` (interi EUR), `ente_erogatore`, `link_candidatura`, `riferimento_normativo`, candidati `beneficiari` e `tematica`. Esegui l'estrazione anche sul testo PDF e unisci i risultati dando **priorità al PDF**.

I campi non trovati restano `null`. **Non sovrascrivere `null` con stime**: completa un campo solo con prova testuale. Per bandi in inglese (Interreg) l'estrattore spesso restituisce `null`: leggi tu il markdown e compila i campi con prova testuale.

### STEP 5 — Verifica link candidatura

Se `link_candidatura` è valorizzato e diverso da `source_url`:

```bash
python scripts/firecrawl_scrape.py "[link_candidatura]" --format markdown --max-chars 500 --check-only
```

- Se la verifica passa: `link_candidatura_source = "extracted"`.
- Se la verifica fallisce o `link_candidatura` non è estraibile dal bando: imposta `link_candidatura = null` e `link_candidatura_source = "missing"`. **NON usare `source_url` come fallback** — il frontend mostrera' solo `link_bando` (= source_url) come CTA secondaria "Apri la pagina ufficiale del bando".
- Solo se l'orchestrator lo autorizza (caso eccezionale): `link_candidatura = source_url`, `link_candidatura_source = "fallback_source"`.

Il fallback storico `link_candidatura = source_url` era confondente: mostrava al pubblico due link identici (entrambi alla pagina del bando) sotto due etichette diverse, come se fossero modulo e pagina ufficiale.

### STEP 6 — Generazione contenuto SEO (sempre ricco, mai stub)

Classifica il livello (criteri in `references/article_structure.md`):
- **flash_bando** (350-500 parole) — default per bandi con poche info (scadenza + beneficiari + link)
- **guida_bando** (800-1200 parole) — bando con contenuto sostanzioso: regolamento articolato, fasi multiple, FAQ ufficiali, allegati, criteri di valutazione, importo totale alto

Segui `references/article_structure.md` (struttura sezioni) e `references/seo_guidelines.md` (regole SEO). Genera:
- `titolo` (H1) — sentence case, ≤ 80 char, nome del bando + anno se rilevante
- `occhiello` (opzionale) — 1 frase per la card lista (es. "Regione Lombardia · scade il 30/09/2026 · fino a 250.000 € per progetto")
- `descrizione_breve` — **180-320 caratteri** (range validato dal codice), card della lista bandi
- `meta_title` ≤ 60 char, keyword nelle prime 3-4 parole, ≠ `titolo`
- `meta_description` ≤ 155 char, includere scadenza se nota + CTA esplicito
- `contenuto` strutturato in sezioni (vedi schema sotto)
- `slug` — lowercase, kebab-case, ≤ 80 char, dal `titolo` senza stop word italiane (se non lo passi, lo genera `slugify`)

Il contenuto deve essere **specifico per quel bando**: apertura con fatto concreto (chi, quanto, quando), MAI sezioni generiche o placeholder. **Nessun link in uscita verso testate, blog, sindacati**. Ammessi solo: portale del bando (source_url), link candidatura, PDF ufficiali, siti istituzionali (.gov.it, .europa.eu, ec.europa.eu, regione.*).

`scadenza_stato` NON va calcolato a mano: lo determina automaticamente `create_bando_json` da `scadenza`. In single-bando il JSON si emette SEMPRE, anche se `scaduto`.

**Scadenza autoritativa (`scadenza_source` + `scadenza_quote`)** — Per ogni `scadenza` estratta DEVI tracciare:

- `scadenza_source` (enum):
  - `official_pdf` — data trovata nel PDF allegato ufficiale del bando.
  - `official_page` — data trovata nella pagina HTML del bando con label esplicita ("Scadenza presentazione domande", "Termine ultimo").
  - `inferred` — data dedotta da contesto (es. "anno scolastico 2026/2027" → 30/06/2026). Non autoritativa.
  - `missing` — nessuna data trovata: `scadenza = null`, `scadenza_source = "missing"`, `scadenza_quote = null`.

- `scadenza_quote` (TEXT, max 300 char) — **OBBLIGATORIO se `scadenza` non-null e `source != "missing"`**. Deve essere un frammento **letterale** del markdown/PDF sorgente che contiene la data, con 20-30 char di contesto su entrambi i lati. NO parafrasi, NO traduzione, NO ricostruzione: il frammento deve essere ricercabile via `substring` (case-insensitive) sul markdown.

**Esempio positivo** (scadenza valida + quote ricercabile):
```
"scadenza": "2026-09-30",
"scadenza_source": "official_page",
"scadenza_quote": "...presentazione domande entro il **30 settembre 2026** alle ore 12:00, pena esclusione..."
```

**Esempi negativi** (rifiutati dal validator):
- `"scadenza_quote": "deadline TBD"` — la data nel quote non e' parsabile.
- `"scadenza_quote": "Bando con scadenza il prossimo settembre"` — la data citata non c'e' letteralmente.
- `"scadenza": "2026-09-30"` con `"scadenza_quote": null` (e source != "missing") — manca la prova.

L'orchestrator sovrascrive `data_scadenza` nel DB SOLO se `scadenza_source IN ('official_pdf', 'official_page')`. Per `inferred`/`missing` resta il valore originale dello scraper (o NULL). **Quando hai dubbi, preferisci `missing` a inventare una data**. Il validator Python rifiuta JSON con `scadenza` non-null senza `scadenza_quote` (eccetto `source = "missing"`).

### STEP 6b — Data di pubblicazione del bando (dalla fonte, mai la nostra)

Insieme alla `scadenza`, devi estrarre la `data_pubblicazione` REALE del bando — la data in cui l'ente l'ha pubblicato sulla **fonte ufficiale** (decreto, delibera, BUR, Gazzetta, comunicato istituzionale). **NON la data in cui noi l'abbiamo scrapato** e **MAI la data odierna**.

Cerca, in ordine di affidabilita':
- Data del decreto/avviso ("Decreto dirigenziale n. 1234 del 15/03/2026")
- Data della delibera ("DGR n. 567 del 28/02/2026")
- Data del protocollo ("Protocollo n. 0123 del 10/03/2026")
- "Pubblicato il …" o "Data di pubblicazione: …"
- Data sul BUR / BURL / BURC / Gazzetta Ufficiale citata dal bando ("GU n. 50 del 28/02/2026")

Compila anche `data_pubblicazione_source` (enum, identico a `scadenza_source`) **e `data_pubblicazione_quote`** (obbligatorio se data non-null e source != "missing"):

- `data_pubblicazione_source`:
  - `official_pdf` — data trovata nel PDF ufficiale del bando.
  - `official_page` — data trovata nella pagina HTML con label esplicita.
  - `inferred` — data dedotta da contesto (es. "anno scolastico 2026/2027" senza altre prove → 01/09/2026). Non autoritativa.
  - `missing` — niente data sulla fonte: `data_pubblicazione = null`, `data_pubblicazione_source = "missing"`, `data_pubblicazione_quote = null`.
- `data_pubblicazione_quote` (TEXT, max 300 char) — frammento **letterale** del markdown/PDF che contiene la data, con 20-30 char di contesto. Stessa regola del `scadenza_quote`.

**Esempio positivo**:
```
"data_pubblicazione": "2026-02-28",
"data_pubblicazione_source": "official_page",
"data_pubblicazione_quote": "...DGR n. 567 del **28/02/2026** pubblicata sul BURL n. 9..."
```

**Anti-hallucination cruciale**: NON estrarre date di decreti citati come base normativa ("ai sensi del DM n. 123 del 10/01/2020", "in attuazione della L. 78/2020 del 15/03/2020") — quelle sono riferimenti storici, NON pubblicazione del bando corrente. Una data e' di pubblicazione del bando SOLO se l'autorita' competente sta pubblicando proprio questa call (decreto/avviso/delibera che istituisce e apre il bando).

**Coerenza con scadenza (regola critica #10)**: `data_pubblicazione <= scadenza` sempre. Se la tua estrazione restituisce `pub > scad` → almeno una delle due e' un'allucinazione: lascia entrambe `null` con `source = "missing"`.

L'orchestrator sovrascrive `data_pubblicazione` nel DB SOLO se `data_pubblicazione_source IN ('official_pdf','official_page')` (stessa policy della scadenza). Il listing `/bandi` ordina per `data_pubblicazione DESC`, quindi una data corretta porta il bando in vetta; `missing` lo manda in fondo.

Un downstream verifier adversarial (Claude Haiku) controlla che il `data_pubblicazione_quote` sia substring del markdown e che le date siano coerenti. Se il verifier rifiuta, l'orchestrator imposta `is_bando_confermato = false`.

### STEP 7 — Assembla e valida il JSON

Scrivi i parametri editoriali in un file JSON di scratch (`scratchpad/<slug>.inputs.json`) con esattamente i kwargs di `create_bando_json` **tranne `output_path`**: `source_url`, `source_domain`, `titolo`, `occhiello`, `slug`, `descrizione_breve`, `meta_title`, `meta_description`, `contenuto_sections`, `bando_data`, `factcheck_report`, `fonti`, `livello`, `allegati` (array, anche vuoto). Poi:

```bash
# emette il JSON completo del bando su stdout (caso "solo JSON")
python scripts/generate_json_output.py --build-from scratchpad/<slug>.inputs.json

# oppure scrive anche un file singolo (stdout = solo esito validazione)
python scripts/generate_json_output.py --build-from scratchpad/<slug>.inputs.json --out output/<slug>.json
```

`--build-from` esegue la validazione **completa** (lunghezze meta/titolo, `ente_erogatore` NOT NULL, formato date ISO, calcolo `scadenza_stato`, range word_count, blacklist, fallback `slug`/`link_candidatura`) e include il blocco `validation`. **Usa sempre `--build-from`**, non costruire il JSON a mano (`--validate-only` controlla solo le sezioni, non tutto). Exit code: `0` se `validation.passed`, `1` altrimenti.

Se `validation.passed == false`: leggi `warnings`, correggi gli input nello scratch e **ri-esegui** finché passa.

### STEP 8 — Emetti il singolo JSON

Restituisci il JSON del bando (stdout e/o file richiesto). Report finale all'utente: `validation.passed`, `livello`, `word_count`, `ente`, `scadenza` + `scadenza_stato`, eventuali warning. Nessuna lista, nessun riepilogo, nessuno stato, nessun upload.

## Schema JSON di output (mapping tabella `bandi`)

Il JSON emesso segue questo schema, allineato 1:1 alla tabella Supabase:

```json
{
  "generated_at": "2026-06-26T10:30:00+00:00",
  "livello": "flash_bando | guida_bando",

  "source_url": "...",
  "source_domain": "...",

  "slug": "...",
  "titolo": "...",
  "occhiello": "... | null",
  "descrizione_breve": "...",
  "contenuto": {
    "sections": [
      {"type": "h2", "text": "..."},
      {"type": "paragraph", "segments": [{"kind":"text","text":"..."}, {"kind":"bold","text":"..."}, {"kind":"link","text":"...","url":"..."}]},
      {"type": "bullet_list", "items": [{"segments":[...]},...]},
      {"type": "numbered_list", "items": [...]},
      {"type": "faq", "items": [{"q":"...","a":{"segments":[...]}}]}
    ]
  },

  "meta_title": "...",
  "meta_description": "...",

  "bando": {
    "ente_erogatore": "...",
    "tipologia": "FESR | FSE | Interreg | nazionale | regionale | misto | JTF | null",
    "area_geografica": "...",
    "beneficiari": ["...", "..."],
    "tematica": ["...", "..."],
    "scadenza": "YYYY-MM-DD | null",
    "scadenza_source": "official_pdf | official_page | inferred | missing",
    "scadenza_quote": "... frammento letterale dal markdown (max 300 char) | null",
    "scadenza_stato": "aperto | in_scadenza | scaduto | null",
    "data_pubblicazione": "YYYY-MM-DD | null",
    "data_pubblicazione_source": "official_pdf | official_page | inferred | missing",
    "data_pubblicazione_quote": "... frammento letterale dal markdown (max 300 char) | null",
    "importo_totale_eur": 12500000,
    "importo_max_per_progetto_eur": 250000,
    "link_candidatura": "... | null",
    "link_candidatura_source": "extracted | fallback_source | missing",
    "programma": "PR Lombardia FESR 2021-2027 | null",
    "modalita_erogazione": "Fondo perduto | Tasso agevolato | Misto | null",
    "codici_ateco": ["62.01", "62.02"]
  },

  "allegati": [
    {"label": "Modulo di candidatura", "url": "https://.../modulo.pdf", "tipo": "pdf"},
    {"label": "Regolamento", "url": "https://.../regolamento.pdf", "tipo": "pdf"},
    {"label": "FAQ", "url": "https://.../faq.docx", "tipo": "docx"}
  ],

  "factcheck_report": [
    {"dato": "scadenza 30 settembre 2026", "stato": "confermato", "fonte_primaria": "https://.../bando.pdf"}
  ],

  "fonti": [
    {"dato": "...", "fonte_url": "..."}
  ],

  "validation": {
    "passed": true,
    "is_valid_bando": true,
    "validation_reason": "Pagina ufficiale del bando voucher scuola Piemonte 2026/2027 con PDF allegato, ente erogatore, scadenza esplicita.",
    "rejection_category": null,
    "warnings": [],
    "word_count": 980,
    "meta_title_length": 56,
    "meta_description_length": 152,
    "titolo_length": 65,
    "slug_length": 38,
    "descrizione_breve_length": 250
  }
}
```

## Casi limite (edge case)

- **Scaduto** — Emetti SEMPRE il JSON; `scadenza_stato="scaduto"` (calcolato). È il progetto a valle a decidere se pubblicare. Il testo resta fattuale (può indicare che i termini sono chiusi).
- **Scadenza null (a sportello)** — Lascia `scadenza=null` → `scadenza_stato=null`. Scrivi "sportello aperto fino a esaurimento risorse" SOLO se il bando lo dichiara; altrimenti di' che la scadenza non è indicata. Mai inventare date.
- **Bando in inglese (Interreg)** — L'estrattore IT-centrico spesso dà `scadenza`/`ente` null: compila tu dai testi con prova testuale; ente/tipologia/area dall'hint. Editoriale SEMPRE in italiano (traduzione editoriale), mantenendo nomi propri e `riferimento_normativo` originale.
- **Landing / pagina elenco bandi** — Se l'URL è una pagina che linka molti bandi (nessuna scadenza/importo unico, molti link a sotto-pagine, titolo generico tipo "Bandi aperti"): emetti il JSON con `validation.is_valid_bando=false` e `validation.rejection_category="index_page"` (vedi STEP 2.5). Compila `validation_reason` con una frase descrittiva. Puoi lasciare null/placeholder gli altri campi: l'orchestrator nascondera' il record dal frontend. **NON inventare campi a partire dai link figli.**
- **link_candidatura non verificabile** — Imposta `link_candidatura=null` e `link_candidatura_source="missing"`. NON usare `source_url` come fallback. Il frontend mostrera' solo `link_bando` come CTA secondaria.
- **`ente_erogatore` mancante (NOT NULL)** — Prova: estrattore → hint dal backend → derivazione da dominio/contenuto. Non deve mai uscire `null`. Se davvero ignoto, la validazione blocca: segnala all'utente invece di emettere un record non valido.
- **Word count fuori range** — guida insufficiente → declassa a flash; flash troppo corto → aggiungi dettaglio fattuale (mai riempitivi/blacklist). Itera finché in range.
- **Hint vuoto / dominio non riconosciuto dal backend** — Nessun prior: deriva ente/area dal contenuto; `tipologia` solo tra i valori canonici (`FESR|FSE|Interreg|nazionale|regionale|misto|JTF`) o `null`. Annota in `factcheck_report` che l'hint è derivato.

## Checklist Pre-Output

**Validita' (sempre, anche se is_valid_bando=false):**
- [ ] `validation.is_valid_bando` settato (true | false)
- [ ] Se false: `validation.rejection_category` + `validation.validation_reason` valorizzati
- [ ] Se false: il JSON viene comunque emesso (l'orchestrator si occupa di nasconderlo)

**Campi strutturati (se is_valid_bando=true):**
- [ ] `source_url` presente e raggiungibile
- [ ] `ente_erogatore` valorizzato (mai null)
- [ ] `slug` valido lowercase/kebab-case ≤ 80 char (l'unicità la gestisce il progetto a valle)
- [ ] `scadenza` in formato ISO o null (mai stringhe libere)
- [ ] `scadenza_source` valorizzato (official_pdf | official_page | inferred | missing)
- [ ] `scadenza_quote` presente e letterale (substring del markdown) se `scadenza` non-null e `source != "missing"`
- [ ] `scadenza_stato` coerente con `scadenza` e data odierna
- [ ] `data_pubblicazione` in formato ISO o null (estratta dalla fonte, MAI dalla data odierna o dal nostro scraping)
- [ ] `data_pubblicazione_source` valorizzato (official_pdf | official_page | inferred | missing)
- [ ] `data_pubblicazione_quote` presente e letterale se `data_pubblicazione` non-null e `source != "missing"`
- [ ] **Coerenza date**: `data_pubblicazione <= scadenza` SEMPRE (regola critica #10). Se incoerenti → entrambe null + source missing.
- [ ] `importo_totale_eur` e `importo_max_per_progetto_eur` interi in euro (no centesimi, no float)
- [ ] `link_candidatura` verificato (verified=true) oppure null (verified=false). MAI uguale a `source_url` come fallback
- [ ] `beneficiari` e `tematica` array (anche vuoti, mai null)
- [ ] `allegati` array (vuoto se la pagina non ha file), URL assoluti, tipo nell'enum, deduplicato per url

**SEO:**
- [ ] `meta_title` ≤ 60 char, keyword nelle prime 3-4 parole
- [ ] `meta_description` ≤ 155 char, include scadenza se nota, contiene CTA
- [ ] `titolo` (H1) ≤ 80 char, diverso dal `meta_title`
- [ ] `titolo` in sentence case (solo prima lettera maiuscola, sigle in maiuscolo)
- [ ] `descrizione_breve` 180-320 char, leggibile come card

**Contenuto:**
- [ ] Word count dentro i limiti del livello (flash 350-500, guida 800-1200)
- [ ] Apertura con fatto concreto (chi, quanto, quando), NON generica
- [ ] Nessuna frase della blacklist
- [ ] Tutti i dati numerici hanno una entry in `fonti[]`
- [ ] Nessun link verso testate/blog/sindacati; solo link istituzionali

**Anti-invenzione:**
- [ ] Nessun campo strutturato stimato — solo trovato testualmente
- [ ] Nessuna citazione attribuita senza fonte
- [ ] Nessuna "dichiarazione del Presidente" o simili inventate

## Esempi di utilizzo

### Esempio 1: bando singolo
```
Utente: "Arricchisci questo bando: https://www.regione.lombardia.it/.../bando-formazione-4-0"
→ scrape → extract → genera contenuto guida/flash → JSON su stdout con validation.passed=true.
```

### Esempio 2: con output su file
```
Utente: "Genera il JSON di [URL] e salvalo in output/"
→ ... → python scripts/generate_json_output.py --build-from scratch.json --out output/<slug>.json
```

### Esempio 3: bando in inglese (Interreg)
```
Utente: "Scheda questo bando: https://www.interreg-alcotra.eu/.../call"
→ scrape → campi compilati dal testo (estrattore IT dà null) → editoriale in italiano → JSON.
```

## Resources

### Scripts
- `firecrawl_scrape.py` — Helper Firecrawl con fallback (markdown → html → WebFetch). Single-URL.
- `extract_bando_fields.py` — Estrazione campi strutturati con regex + euristiche. Single-bando.
- `generate_json_output.py` — **Unico output ufficiale.** `--build-from <inputs.json>` costruisce + valida + emette il JSON del bando (stdout o `--out <file>`). Espone anche `create_bando_json()` e `--validate-only`.

### Config & reference
- `references/*.md` — Guide di estrazione, struttura articolo, SEO, blacklist.
- Hint dominio: NON da file. Ti arriva come parametro nel prompt dall'orchestrator (vedi STEP 1).

### Archivio
- `archive/` — Vecchia modalità batch (`run_batch.py`, `load_csv.py`, `upload_to_supabase.py`, `state/`), non più usata: orchestrazione/dedup/storage sono ora responsabilità del progetto che incorpora la skill.
