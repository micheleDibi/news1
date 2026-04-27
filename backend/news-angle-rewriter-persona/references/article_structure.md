# Struttura articolo per livello

## FLASH (450-550 parole)

```
[Fatto principale in 1-2 frasi. Chi, cosa, quando.]
[Scadenza se presente.]

## [Sezione 1: dettaglio principale]
[3-5 frasi con i fatti essenziali e il contesto immediato]

## [Sezione 2: impatto pratico o dettaglio aggiuntivo]
[3-5 frasi con cosa cambia per il lettore]

[Chiusura con azione concreta o conseguenza pratica. 1-2 frasi.]
```

NO indice. NO H3. NO FAQ. NO contestualizzazione storica.
Max 2 sezioni H2. Link a 1-2 fonti primarie (ordinanze, GU, MIM).

**Chiusura flash:** l'ultima frase deve contenere un'azione concreta per il lettore o una conseguenza pratica. MAI chiudere con un elenco di date o una lista puntata.

## EDITORIALE (600-900 parole)

```
[Apertura: fatto più rilevante o dato che colpisce. 1-2 frasi.]

## [Sezione 1: il contesto immediato]
[I fatti. Cosa è successo. Dati principali. 150-200 parole]

## [Sezione 2: L'ANGOLO - qui è il valore unico]
[Dati aggiuntivi, confronti, analisi. 200-300 parole.
Questo è il cuore dell'articolo.]

## [Sezione 3: impatto pratico]
[Cosa cambia concretamente per il lettore. 150-200 parole]

[Chiusura: prospettiva futura concreta. 1-2 frasi.
NO riassunto. NO "in conclusione".]
```

Indice solo se >3 sezioni H2. NO FAQ (non è una guida).

## EVERGREEN (1000-1500 parole)

L'indice DEVE essere inserito come prima sezione con `{"type": "auto_index"}`. Lo script `generate_json_output.py` slugifica ogni H2 (`id` univoco, accenti rimossi solo nello slug) e costruisce il paragrafo "Indice:" con link `#slug` cliccabili. Non scrivere mai l'indice come paragrafo di testo: rimarrebbe testo statico senza ancore.

**Vincoli sulle liste**: massimo **1 `bullet_list` + 1 `numbered_list`** in tutto l'articolo. "In breve" usa il bullet, la guida passo-passo (o moduli) usa il numbered. Tutte le altre enumerazioni (errori comuni, vantaggi, criteri) vanno rese come paragrafi discorsivi con grassetto sui termini chiave.

**Chiusura**: l'articolo NON può finire con una lista né con la FAQ. Subito dopo l'ultima risposta della FAQ inserisci un `paragraph` di chiusura (2-3 frasi, nello stile della persona): prospettiva concreta, conseguenza pratica, riflessione. Mai riassunto, mai "in conclusione".

```
{"type": "auto_index"}  ← espanso automaticamente

## In breve
[4-5 punti chiave. Max 80 parole. UNICO bullet_list]

## [Sezione passo-passo o moduli]
1. [Passo/modulo 1 con scadenza o dettaglio specifico]
2. [Passo/modulo 2]
3. [Passo/modulo 3]
   ← UNICO numbered_list

## Errori comuni
**[Errore 1]**: [paragrafo di 1-2 frasi con come evitarlo].
**[Errore 2]**: [paragrafo di 1-2 frasi].
**[Errore 3]**: [paragrafo di 1-2 frasi].
   ← 3-4 paragrafi separati, NON un bullet_list

## Domande frequenti

### [Domanda 1]?
[Risposta 2-3 righe]

### [Domanda 2]?
[Risposta 2-3 righe]

[Paragrafo di chiusura discorsivo, 2-3 frasi, senza h2 dedicato.
Stile della persona, NO riassunto, NO "in conclusione".]
```
