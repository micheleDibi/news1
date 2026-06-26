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
1. **Hint dominio override** `{"ente": "...", "tipologia": "...", "area": "..."}` (default: derivato da `config/sources.json`; l'override utente vince).
2. **Percorso di output** del JSON (default: stdout; es. `output/<slug>.json` per scrivere su file).
3. **Livello forzato** `flash_bando` | `guida_bando` (default: lo classifica la skill).

## ⚠️ REGOLE CRITICHE

1. **MAI inventare campi strutturati** — Se `scadenza`, `importo` o `beneficiari` non sono ricavabili dal bando, il campo resta `null` (o array vuoto). Mai stimare.
2. **MAI emettere un bando senza link_candidatura verificato** — `link_candidatura` deve puntare a una pagina raggiungibile (verificata con scrape secondario), altrimenti ricondotto a `source_url` con nota.
3. **MAI superare i limiti SEO** — `meta_title` ≤ 60 char, `meta_description` ≤ 155 char, `titolo` (H1) ≤ 80 char, `meta_title` ≠ `titolo`.
4. **MAI usare frasi della blacklist** (vedi `references/blacklist_frasi.md`).
5. **SEMPRE sentence case** nei titoli (solo prima lettera maiuscola, no Title Case; sigle e nomi propri restano).
6. **SEMPRE citare la fonte istituzionale** — Ogni dato strutturato deve avere un'entry in `fonti[]` con `dato` + `fonte_url`.
7. **SEMPRE produrre JSON valido** che mappa 1:1 le colonne della tabella `bandi` su Supabase.
8. **MAI contenuto generico/placeholder** — Genera SEMPRE contenuto editoriale ricco e specifico per quel bando (vedi STEP 6). Niente sezioni stub.

## Workflow

### STEP 0 — Lettura guide obbligatorie

**OBBLIGATORIO** — Prima di iniziare, leggi con lo strumento `Read` tutte le reference:

- `references/bando_data_extraction.md` — quali campi estrarre e come riconoscerli
- `references/article_structure.md` — struttura editoriale per livello (flash/guida)
- `references/seo_guidelines.md` — regole meta/titolo/slug
- `references/blacklist_frasi.md` — frasi vietate

### STEP 1 — Hint dominio

Estrai il dominio dall'URL e cercane il match (esatto o per suffisso) in `config/sources.json` per pre-compilare `ente` / `tipologia` / `area`. Unisci con l'eventuale override utente (**l'override vince**). Se il dominio non è mappato → hint vuoto (vedi edge case "Dominio non mappato"). Gli hint sono default: vanno SEMPRE sovrascritti se il bando dichiara qualcosa di diverso.

### STEP 2 — Scrape pagina bando

```bash
python scripts/firecrawl_scrape.py "[URL]" --format markdown --max-chars 20000
```

Output: contenuto markdown su stdout (salvalo in un file di scratch). Se Firecrawl restituisce vuoto o errore:
1. Riprova con `--format html`
2. Se ancora vuoto: ricadi su `WebFetch` con l'URL ed estrai il testo principale
3. Se ancora nulla: **STOP** — riporta `scrape_failed` all'utente. NON emettere un JSON inventato.

Richiede la variabile d'ambiente `FIRECRAWL_API_KEY`.

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

Se fallisce: imposta `link_candidatura = source_url` e annota in `factcheck_report`/`fonti`.

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
    "scadenza_stato": "aperto | in_scadenza | scaduto | null",
    "importo_totale_eur": 12500000,
    "importo_max_per_progetto_eur": 250000,
    "link_candidatura": "...",
    "riferimento_normativo": "..."
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
- **Landing / pagina elenco bandi** — Se l'URL è una pagina che linka molti bandi (nessuna scadenza/importo unico, molti link a sotto-pagine, titolo generico tipo "Bandi aperti"): **NON inventare e non sceglierne uno a caso.** STOP, riporta che è una pagina elenco, elenca i link candidati trovati e chiedi l'URL specifico. Nessun JSON.
- **link_candidatura non verificabile** — Usa `source_url` + nota in `fonti`/`factcheck_report`.
- **`ente_erogatore` mancante (NOT NULL)** — Prova: estrattore → hint `sources.json` → derivazione da dominio/contenuto. Non deve mai uscire `null`. Se davvero ignoto, la validazione blocca: segnala all'utente invece di emettere un record non valido.
- **Word count fuori range** — guida insufficiente → declassa a flash; flash troppo corto → aggiungi dettaglio fattuale (mai riempitivi/blacklist). Itera finché in range.
- **Dominio non mappato in `sources.json`** — Nessun hint: deriva ente/area dal contenuto; `tipologia` solo tra i valori canonici (`FESR|FSE|Interreg|nazionale|regionale|misto|JTF`) o `null`. Annota in `factcheck_report` che l'hint è derivato.

## Checklist Pre-Output

**Campi strutturati:**
- [ ] `source_url` presente e raggiungibile
- [ ] `ente_erogatore` valorizzato (mai null)
- [ ] `slug` valido lowercase/kebab-case ≤ 80 char (l'unicità la gestisce il progetto a valle)
- [ ] `scadenza` in formato ISO o null (mai stringhe libere)
- [ ] `scadenza_stato` coerente con `scadenza` e data odierna
- [ ] `importo_totale_eur` e `importo_max_per_progetto_eur` interi in euro (no centesimi, no float)
- [ ] `link_candidatura` verificato o ricondotto a `source_url` con nota
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
- `config/sources.json` — Mapping dominio → hint (ente, tipologia, area).
- `references/*.md` — Guide di estrazione, struttura articolo, SEO, blacklist.

### Archivio
- `archive/` — Vecchia modalità batch (`run_batch.py`, `load_csv.py`, `upload_to_supabase.py`, `state/`), non più usata: orchestrazione/dedup/storage sono ora responsabilità del progetto che incorpora la skill.
