# Struttura contenuto per livello

I bandi hanno due livelli editoriali. Il livello determina lunghezza, struttura e profondità informativa.

## Quando usare quale livello

**flash_bando** (350-500 parole) — default. Usalo quando:
- Il bando ha poche informazioni sostanziali (1-2 pagine PDF)
- Lo scope è ristretto (es. un singolo voucher di importo modesto)
- Non ci sono allegati esplicativi né FAQ ufficiali
- Il bando è di nicchia (rivolto a pochi soggetti specifici)

**guida_bando** (800-1200 parole) — usalo quando si verifica almeno una di queste condizioni:
- Il regolamento è articolato (5+ pagine PDF, fasi multiple)
- C'è una graduatoria con criteri di valutazione esplicitati
- Il bando prevede sportelli multipli o finestre temporali
- Sono presenti FAQ ufficiali sul portale
- L'importo totale supera i 5M€ (potenziale alto interesse editoriale)
- I beneficiari sono molteplici e variegati

Se sei in dubbio: parti da `flash_bando`. Meglio una scheda essenziale che una guida diluita.

## flash_bando (350-500 parole)

### Struttura

```
[occhiello]: "Regione X · scade il GG/MM/AAAA · fino a €X per progetto"

H1 (titolo): nome del bando + anno (sentence case, ≤80 char)

[descrizione_breve, 200-300 char per la card lista]

Sezioni del contenuto:

1. PARAGRAFO APERTURA (60-100 parole)
   - Cosa finanzia il bando, in una frase
   - Importo totale stanziato
   - A chi è rivolto, in breve

2. H2 "Chi può candidarsi" (80-120 parole)
   - Lista bullet dei beneficiari (mantieni fraseggio originale)
   - Eventuali requisiti aggiuntivi (sede, dimensione, settore)

3. H2 "Come e quando candidarsi" (80-120 parole)
   - Scadenza esatta (giorno + ora se nota)
   - Modalità di presentazione (online, PEC, sportello)
   - LINK al portale di candidatura (anchor descrittivo)

4. PARAGRAFO CHIUSURA (40-60 parole)
   - Importo massimo per progetto (se noto)
   - Riferimento normativo (DGR, DM)
   - LINK al PDF/pagina ufficiale come "fonte"

NESSUN indice, NESSUN H3, NESSUNA FAQ.
```

### Esempio di apertura buona

> La Regione Lombardia ha stanziato 12,5 milioni di euro per finanziare progetti di formazione professionale destinati alle micro, piccole e medie imprese del territorio. Il bando "Formazione 4.0 — annualità 2026" è aperto fino al 30 settembre 2026 e prevede un contributo massimo di 250.000 euro per singolo progetto.

### Esempio di apertura cattiva (da evitare)

> In un contesto di crescente attenzione alla formazione delle competenze digitali nelle imprese, la Regione Lombardia ha pubblicato un nuovo bando volto a sostenere percorsi formativi innovativi.

Differenza chiave: il primo dà 3 dati concreti nei primi 30 parole; il secondo è riempitivo.

## guida_bando (800-1200 parole)

### Struttura

```
[occhiello]: stesso formato del flash

H1 (titolo): nome bando + anno + qualificatore (es. "guida completa")

[descrizione_breve, 200-300 char]

Sezioni del contenuto:

1. INDICE (anchor link alle H2)

2. H2 "In breve" (80-120 parole)
   - 4-5 bullet point con: cosa finanzia, importo totale, beneficiari principali, scadenza, link candidatura

3. H2 "A chi si rivolge il bando" (150-200 parole)
   - Paragrafo introduttivo
   - bullet_list di beneficiari (dettagliata)
   - Eventuali requisiti specifici (dimensione, sede, settore, anzianità)
   - Esclusioni esplicite (chi NON può candidarsi)

4. H2 "Cosa finanzia" (150-200 parole)
   - Tipologia di spese ammissibili
   - Importo massimo per progetto
   - Eventuale cofinanziamento richiesto (% di copertura)
   - Durata dei progetti

5. H2 "Come presentare la domanda" (150-200 parole)
   - numbered_list dei passaggi
   - Documenti richiesti (bullet_list)
   - LINK al portale di candidatura
   - Modalità (online via SPID/CIE, PEC, sportello fisico)

6. H2 "Scadenze e tempistiche" (80-120 parole)
   - Scadenza principale (data + ora)
   - Eventuali fasi successive (graduatoria, avvio progetti, rendicontazione)
   - Sportello aperto fino esaurimento? Indicarlo

7. H2 "Errori comuni da evitare" (80-120 parole) — solo se hai info concrete dalle FAQ ufficiali o da circolari di chiarimento. Se non hai info, OMETTI questa sezione.
   - 3-4 bullet di errori frequenti
   - Riferimento alle FAQ ufficiali se esistono

8. H2 "FAQ" (100-150 parole) — solo se sul portale del bando ci sono FAQ ufficiali. NON inventare FAQ.
   - 3-5 domande-risposta brevi (2-3 righe per risposta)
   - Usa il blocco di tipo "faq" nello schema sections

9. PARAGRAFO CHIUSURA (40-60 parole)
   - Riferimento normativo completo
   - LINK al PDF/pagina ufficiale
```

### Regole di sezione

- Ogni H2 deve avere almeno 80 parole. Se non hai contenuto sufficiente, accorpa o ometti.
- L'indice in cima è obbligatorio per guida_bando.
- Le FAQ vanno generate **solo** se il portale ufficiale ha FAQ. Non inventare. Una guida senza FAQ è ok.
- "Errori comuni" stesso principio: solo se hai prove.

## Sezioni "segments" — formato comune

Ogni paragrafo o item di lista è una lista di `segments`, ciascuno è:

```json
{"kind": "text", "text": "..."}
{"kind": "bold", "text": "..."}
{"kind": "link", "text": "anchor visibile", "url": "https://..."}
```

Mai concatenare HTML grezzo. Mai lasciare markdown `**testo**` o `[testo](url)` nel JSON finale: il generatore li parsa in segments.

## Anchor dei link

- **Sempre descrittivo**: "consulta il bando integrale sul portale della Regione Lombardia", non "clicca qui" / "fonte" / "leggi qui".
- **Mai URL nudo** nell'anchor.
- **Solo link istituzionali**: portale del bando, PDF ufficiale, sistema di candidatura, sito Regione/Ministero/UE.
- **Vietato linkare** testate, blog, social, sindacati.

## Apertura e chiusura — anti-pattern

Frasi di apertura **vietate**:
- "In un contesto di..."
- "Nell'ambito delle politiche..."
- "La crescente attenzione verso..."
- "Si segnala che..."
- "È stato pubblicato..."

Frasi di chiusura **vietate**:
- "Per ulteriori informazioni si rimanda a..."
- "Concludendo..."
- "In conclusione..."
- "Per approfondire l'argomento..."
- "Restate sintonizzati per gli aggiornamenti"

Apri con un fatto concreto (ente, importo, scadenza). Chiudi con l'azione concreta (riferimento normativo + link al PDF ufficiale).
