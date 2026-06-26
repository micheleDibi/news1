# SEO guidelines — bandi

Regole specifiche per la categoria bandi su edunews24.it. Si applicano a `meta_title`, `meta_description`, `titolo` (H1), `slug` e struttura interna.

## Intent di ricerca

Le query target dei bandi sono **prevalentemente informazionali ad alto intento**:
- "[nome bando] scadenza"
- "[nome bando] come fare domanda"
- "[nome bando] beneficiari"
- "bando [tematica] [regione] [anno]"
- "fondi [FESR/FSE/Interreg] [regione]"

L'utente cerca **info azionabili**: scadenza, importo, link domanda. Il contenuto deve dare queste tre cose nei primi 200 caratteri, sempre.

## `meta_title` (≤ 60 caratteri)

Formula consigliata:
```
[Nome bando]: scadenza GG/MM, fino a €X per progetto
[Tematica] [Regione] [Anno]: bando da €X
```

Esempi:
- ✅ `Formazione 4.0 Lombardia: scade 30/9, fino a 250k` (54 char)
- ✅ `Bando ricerca PNRR 2026: 8 milioni per università` (49 char)
- ❌ `Nuovo bando della Regione Lombardia per la formazione professionale` (no scadenza, no importo, troppo lungo)

Regole:
- Keyword principale nelle **prime 3-4 parole**.
- **Sentence case** (solo la prima lettera in maiuscolo, più sigle e nomi propri).
- Includi un dato numerico concreto se sta in 60 char (scadenza abbreviata GG/MM o importo).
- Mai claim ("imperdibile", "esclusivo", "tutto quello che devi sapere").

## `meta_description` (≤ 155 caratteri)

Formula:
```
[Cosa finanzia in 1 frase]. Scadenza [data], dotazione €X. Beneficiari: [lista 2-3]. Scopri come candidarti.
```

Esempi:
- ✅ `Bando Formazione 4.0 Regione Lombardia per micro, piccole e medie imprese: 12,5M€ totali, fino a 250k per progetto. Scade il 30/9/2026. Tutte le info.` (151 char)
- ❌ `Un nuovo bando della Regione Lombardia per le imprese del territorio. Scopri tutti i dettagli sul nostro sito.` (vuoto)

Regole:
- Includi **scadenza** se nota (la query "[bando] scadenza" è frequente).
- Includi **importo** se notevole.
- CTA esplicito alla fine: "scopri come candidarti", "guida completa", "tutti i requisiti".
- Una sola CTA, mai due.

## `titolo` (H1) (≤ 80 caratteri)

Diverso dal `meta_title`, più descrittivo. Formula:
```
[Nome bando] [anno]: [info distintiva]
[Tipologia bando] [tematica] [regione/area] [anno]
```

Esempi:
- ✅ `Bando Formazione 4.0 Lombardia 2026: requisiti, scadenze e importi`
- ✅ `Avviso FSE Sicilia 2026 per l'inclusione sociale: 5M€ disponibili`
- ❌ `Nuovo bando della Regione Lombardia` (vago)

Regole:
- **Diverso dal meta_title** (mai duplicare).
- **Sentence case** + sigle in maiuscolo + nomi propri.
- Includi **anno** se identificato.
- Nessuna keyword stuffing.

## `slug` (≤ 80 caratteri)

Lowercase, kebab-case, basato sul titolo ma snellito.

Regole:
- Rimuovi stop word italiane (`il, la, di, da, in, per, su, e, a, il, gli, le, dei, delle, dello, della, un, una, uno, con`).
- Rimuovi accenti e caratteri speciali.
- Trasforma spazi e punteggiatura in `-`.
- Mai più trattini consecutivi.
- Massimo 80 caratteri (tronca al confine di parola).

Esempi:
- Titolo: `Bando Formazione 4.0 Lombardia 2026: requisiti, scadenze e importi`
- Slug: `bando-formazione-4-0-lombardia-2026`

- Titolo: `Avviso FSE Sicilia 2026 per l'inclusione sociale: 5M€ disponibili`
- Slug: `avviso-fse-sicilia-2026-inclusione-sociale`

## Descrizione breve (`descrizione_breve`, 200-300 caratteri)

Usata nella card della lista bandi. Deve rispondere a:
- COSA è il bando (1 frase)
- QUANDO scade
- QUANTO finanzia

Esempi:
- ✅ `Formazione 4.0: la Regione Lombardia stanzia 12,5M€ per imprese che vogliono qualificare il personale su competenze digitali e tecnologie avanzate. Contributi fino a 250k per progetto. Scade il 30 settembre 2026.` (216 char)

## Struttura interna H2/H3

- **flash_bando**: massimo 2 H2, mai H3.
- **guida_bando**: 5-7 H2, H3 solo dentro "FAQ" se necessario.
- Ogni H2 contiene la keyword secondaria (es. "come candidarsi", "scadenze", "beneficiari").
- Mai keyword stuffing.

## Keyword density

- Keyword principale (es. "bando formazione 4.0") max **3 occorrenze** in tutto l'articolo.
- Varianti e sinonimi liberamente.
- Mai aprire con la keyword esatta in stile robotic ("Bando formazione 4.0 è...").

## Link interni e ancore

Quando inserisci link interni a edunews24.it (vietato linkare altre testate):
- Ancora descrittiva: "consulta gli interpelli aperti per ATA"
- Mai "clicca qui", "leggi qui"
- Massimo 2 link interni per articolo (per non disperdere intent)

## Dati strutturati lato sito

I campi del blocco `bando` del JSON serviranno al frontend per:
- Generare `JSON-LD` schema.org `Grant` o `FundingScheme` (`name`, `provider`, `dateModified`, `applicationDeadline`, `description`)
- Filtri lista per `beneficiari`, `tematica`, `area_geografica`, `scadenza_stato`
- Badge "in scadenza" / "scaduto" sulle card

Compila i campi con questi usi in mente: bandi senza `scadenza` non potranno comparire nei filtri "in scadenza"; bandi senza `ente_erogatore` non genereranno JSON-LD valido.

## Sentence case — esempi pratici

- ✅ `Bando formazione 4.0 Lombardia` (sentence case)
- ✅ `Bando PNRR per la ricerca` (sigla in maiuscolo)
- ✅ `Avviso FSE+ Lombardia 2026` (sigla + numero romano? no, arabo)
- ❌ `Bando Formazione 4.0 Lombardia` (Title Case)
- ❌ `BANDO FORMAZIONE 4.0 LOMBARDIA` (tutto maiuscolo)
- ❌ `bando formazione 4.0 lombardia` (tutto minuscolo)

Regola: prima lettera maiuscola, poi minuscolo. Eccezioni: sigle (PNRR, FSE, FESR, UE, INPS, MIUR), nomi propri (Lombardia, Sicilia), numeri ordinali romani (XX), nomi di programmi (Erasmus+, Horizon Europe).
