# Blacklist frasi AI — bandi

Frasi tipiche da scrittura LLM da **eliminare prima di generare il JSON**. La presenza di una qualsiasi di queste frasi nel contenuto va segnalata come warning di validazione.

## Aperture vietate

- "In un contesto di..."
- "Nell'ambito di..."
- "Nel quadro di..."
- "Alla luce di..."
- "Tenuto conto di..."
- "La crescente attenzione verso..."
- "L'importanza sempre maggiore di..."
- "Si segnala che..."
- "Si informa che..."
- "Si rende noto che..."
- "È stato di recente pubblicato..."
- "Recentemente è stato pubblicato..."
- "Negli ultimi anni..."

## Chiusure vietate

- "Per ulteriori informazioni si rimanda a..."
- "Per approfondire l'argomento..."
- "Concludendo..."
- "In conclusione..."
- "In definitiva..."
- "Riassumendo..."
- "Tirando le somme..."
- "Restate sintonizzati"
- "Vi terremo aggiornati"
- "Continuate a seguirci"
- "Per maggiori dettagli consultare..."
- "Non esitate a contattarci"

## Vuoti / riempitivi

- "il fenomeno"
- "le implicazioni"
- "diverse prospettive"
- "molteplici sfaccettature"
- "rappresenta una sfida"
- "costituisce un'opportunità"
- "riveste particolare importanza"
- "assume rilevanza"
- "merita particolare attenzione"
- "non può prescindere da"
- "non può che"
- "non si può non"

## Bullshit promozionale

- "imperdibile occasione"
- "opportunità unica"
- "tutto quello che devi sapere"
- "la guida definitiva"
- "il bando che cambia tutto"
- "rivoluzionario"
- "innovativo" (a meno che il bando stesso si definisca così, e in quel caso vincolato a un dato)
- "cambia le regole del gioco"

## Espressioni AI-generated tipiche

- "vale la pena sottolineare"
- "è importante notare"
- "è opportuno evidenziare"
- "occorre rilevare"
- "non da meno"
- "non per ultimo"
- "in tal senso"
- "in questo contesto" (in apertura)
- "in tale ottica"
- "in particolare"
- "in primis"
- "in particolare modo"
- "appare evidente"
- "risulta evidente"
- "è di tutta evidenza"

## Frasi vuote attribuzione

- "secondo gli esperti"
- "secondo gli analisti"
- "secondo fonti vicine a..."
- "fonti informate riferiscono"
- "come noto"
- "come è noto"
- "come emerso"

Se citi una fonte, citala per nome con link istituzionale. Mai attribuzioni generiche.

## Inglesismi inutili nei bandi

Per il pubblico target dei bandi (PA, scuole, imprese italiane), evita inglesismi quando esiste l'equivalente italiano:
- "stakeholder" → "soggetti coinvolti"
- "deadline" → "scadenza"
- "call" → "bando" / "avviso"
- "funding" → "finanziamento"
- "target" → "destinatari"
- "asset" → "risorsa"

Eccezioni: termini tecnici consolidati nei bandi UE (es. "Joint Secretariat", "Lead Partner", "Project Partner" nei bandi Interreg). Mantieni il termine originale tra virgolette se è proprio del programma.

## Verifica

Il generatore `generate_json_output.py` esegue un check case-insensitive su queste frasi e popola `validation.warnings` con un avviso per ogni occorrenza trovata. Un articolo con warning su frasi blacklist viene comunque generato (non bloccante) ma va corretto a mano prima dell'upload.
