# Linee guida SEO

## Title tag
- Max 55 caratteri per flash, 60 per editoriale/evergreen
- Keyword principale nelle prime 3-4 parole
- Un solo concetto per titolo
- Se c'è un dato numerico, metterlo nel titolo
- SEMPRE sentence case (solo prima lettera maiuscola)
- Mai nome del sito nel title

### Esempi corretti:
- ✅ "Dispersione scolastica 8,2%: al Sud è ancora al 16%" (54 char)
- ✅ "Contratto scuola: +143€ lordi ma solo 85€ netti" (49 char)
- ✅ "AI a scuola: 100 milioni, come candidarsi entro il 17/4" (56 char)

### Esempi sbagliati:
- ❌ "Dispersione Scolastica al Minimo Storico: L'Italia Scende All'8,2% e Supera L'Obiettivo di Agenda 2030" (102 char, tagliato in SERP)
- ❌ "Analisi Approfondita Del Nuovo Contratto Scuola 2025-2027" (capital case, generico)

## H1
- DIVERSO dal title (obbligatorio)
- Max 70 caratteri per flash, 75 per editoriale/evergreen
- Può essere più descrittivo del title
- Aggiunge informazione che il title non ha

## Meta description
- Max 155 caratteri
- Deve promettere un'informazione che il lettore non trova altrove
- Deve contenere una CTA implicita (motivo per cliccare)
- NON ripetere il title

## Struttura contenuto
- H2 per sezioni principali
- H3 SOLO come sotto-sezione di un H2 (mai H3 senza H2 padre)
- Keyword nel primo paragrafo
- Grassetto per concetti chiave (non per frasi intere)
- Paragrafi corti: max 3-4 frasi per paragrafo
- Frasi variabili: alternare brevi (8-12 parole) e medie (15-20 parole)

## Link in uscita (outbound)

Inserire SEMPRE link a fonti verificabili. Rafforza E-E-A-T e credibilità, specialmente in ambito YMYL (scuola/lavoro/concorsi).

### Quanti link per livello

| Livello | Link | Verso chi |
|---------|------|-----------|
| Flash | 1-2 max | Fonte primaria (GU, MIM, ordinanza) |
| Editoriale | 2 max | Fonti istituzionali + dati (ISTAT, Eurostat, OCSE) |
| Evergreen | 2 max | Mix istituzionali + guide ufficiali |

### Massimo 1 link per dominio

In ogni articolo, **massimo un solo link verso lo stesso dominio**. Se linki una pagina di inps.it, non puoi linkare un'altra pagina di inps.it nello stesso articolo. Vale per tutti i domini, inclusi mim.gov.it, istat.it, ecc. Se devi citare due risorse dallo stesso dominio, scegli quella più specifica e pertinente (es. il PDF del decreto, non la homepage).

### Sempre linkare
- Ordinanze, decreti, leggi citate → **preferire il link diretto al PDF** sul sito istituzionale. Il PDF è la massima qualità: documento ufficiale, non interpretato, verificabile. Mai indicare "(PDF)" nell'anchor text.
- Dati statistici citati → link alla fonte primaria (ISTAT, Eurostat, OCSE)
- Bandi o scadenze → link alla pagina ufficiale del bando
- Portali istituzionali citati nel testo (es. "Istanze on line") → linkare sempre

### Mai linkare — TUTTO il resto è competitor

**Regola unica:** link in uscita SOLO verso fonti istituzionali. Qualsiasi altro sito è da considerare competitor e non va mai linkato nel corpo dell'articolo.

**Fonti istituzionali ammesse:**
- Ministeri (.gov.it): MIM, MEF, Ministero del Lavoro
- Gazzetta Ufficiale (gazzettaufficiale.it)
- Enti pubblici: ISTAT, INPS, INDIRE, INVALSI, INAIL
- Enti europei: Eurostat, OCSE, Commissione Europea (.europa.eu)
- Università pubbliche (.edu, .ac.it)

**Competitor (MAI linkare):**
- Testate giornalistiche (Orizzonte Scuola, Tecnica della Scuola, Tuttoscuola, ItaliaOggi, Corriere, Repubblica, ecc.)
- Blog e portali settoriali (AScuolaOggi, Studenti.it, Skuola.net, ecc.)
- Sindacati (FLC CGIL, UIL Scuola, CISL Scuola, SNALS, ecc.)
- Qualsiasi altro sito non istituzionale

Le fonti non istituzionali si usano solo per la ricerca interna e vanno nel report competitor/fonti del DOCX, mai nel testo dell'articolo.

### Verifica link — OBBLIGATORIA prima di inserirli

Ogni link in uscita DEVE essere verificato con scrape prima di finire nell'articolo. Nessuna eccezione.

**Checklist per ogni link:**
1. Scrape l'URL con Firecrawl e conferma che la pagina ha contenuto reale (non vuota, non redirect)
2. Verifica che la pagina di atterraggio sia pertinente al contesto in cui e linkata
3. Mai usare `/en/` su siti .gov.it (la versione inglese e spesso vuota o redirect)
4. Mai usare URL con encoding inutile (`mobilita-2026-2027` non `mobilit%C3%A0-2026-2027`)

Un link rotto o che atterra su una pagina sbagliata danneggia la fiducia dell'utente e la reputazione del sito.

### Anchor text — SEMPRE descrittiva e onesta

Ogni link DEVE avere un'anchor text che descrive chiaramente dove porta. L'utente deve sapere cosa troverà prima di cliccare.

**Formato:** `[LINK:anchor descrittiva|URL]`

**Anchor corrette:**
- `[LINK:Ordinanza mobilità 2026/2027 - MIM|https://...]` — dice cosa troverà
- `[LINK:Dati ISTAT dispersione scolastica 2025|https://...]` — specifica il dato
- `[LINK:Portale Istanze on line|https://...]` — identifica lo strumento

**Anchor vietate:**
- `[LINK:clicca qui|...]` — manipolativa
- `[LINK:fonte|...]` — generica, non dice nulla
- `[LINK:qui|...]` — inutile
- `[LINK:link|...]` — ridondante
- URL nudi senza anchor — mai inserire un URL visibile nel testo
