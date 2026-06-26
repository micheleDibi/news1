# Estrazione dati strutturati da bandi

Questa guida descrive **cosa estrarre** da ogni bando e **come riconoscerlo** nei portali istituzionali italiani ed europei. È la fonte di verità per `scripts/extract_bando_fields.py` e per la generazione editoriale.

## Principi

1. **Solo prova testuale**. Un campo va valorizzato solo se trovi la prova nel testo del bando o nei suoi allegati. Mai stimare, mai dedurre.
2. **PDF batte HTML**. Se il bando ha un PDF di "Avviso pubblico" o "Regolamento", quello è la fonte primaria. Le pagine web di portale riassumono e a volte sbagliano.
3. **Allegati == bando**. Quando il bando è un calendario di avvisi (PDF tipo `Calendario-avvisi-FSE.pdf`), tratta ogni voce del calendario come un mini-bando. Ma per ora estrai solo il bando di copertina; gli avvisi singoli del calendario possono diventare bandi indipendenti in un futuro batch.
4. **Mai forzare**. Se un campo non c'è, resta `null` (o array vuoto per liste). Il template lista bandi del sito deve gestire i null.

## Campi target

### `ente_erogatore` (string, NOT NULL)

Chi pubblica il bando. È quasi sempre derivabile dal dominio + intestazione PDF.

Pattern frequenti:
- "Regione [Nome]" → `Regione Lombardia`, `Regione Liguria`, `Regione Toscana`
- "Ministero del/dell'/della [...]" → `Ministero dell'Istruzione e del Merito`
- "INVALSI", "INDIRE", "INAPP" → sigle istituzionali
- "Commissione europea" / "Programma Interreg [Nome]" → per i bandi UE
- "Provincia autonoma di Trento", "Regione autonoma Valle d'Aosta"

**Fallback**: se non trovi un'intestazione esplicita, usa il `hint.ente` da `config/sources.json` derivato dal dominio.

### `tipologia` (enum string, nullable)

Categoria del fondo. Valori canonici (scrivili così, lowercase tranne sigle):

| Valore | Quando usarlo |
|---|---|
| `FESR` | Fondo Europeo Sviluppo Regionale (`fesr.regione.*`, `prfesr*`) |
| `FSE` | Fondo Sociale Europeo (`fse.regione.*`, `sicilia-fse.it`, `coesione.regione.*`) |
| `Interreg` | Programmi di cooperazione territoriale (`interreg-*`, `interregeurope.eu`, `italy-croatia.eu`) |
| `nazionale` | Bandi PNRR, ministeriali, INAPP, INVALSI senza fondi UE |
| `regionale` | Bandi regionali finanziati con fondi propri della Regione |
| `misto` | Fondi co-finanziati (es. FSE+regionale, PNRR+FESR) |

Se non identifichi con certezza, `null` è meglio che sbagliare.

### `area_geografica` (string, nullable)

Dove si applica il bando.

- Bandi regionali: nome regione (`Lombardia`, `Toscana`, `Sicilia`)
- Bandi nazionali: `Italia`
- Bandi UE: `UE` o `transfrontaliera` per Interreg
- Bandi multi-regione: lista separata da virgola (`Liguria, Toscana, Sardegna`)

### `beneficiari` (array di string, mai null — `[]` se vuoto)

A chi si rivolge. **Stringhe libere** estratte dal bando (no normalizzazione enum).

Cerca paragrafi che iniziano con:
- "Possono presentare domanda...", "Destinatari...", "Soggetti ammissibili...", "Beneficiari..."
- "Il presente avviso è rivolto a..."

Esempi reali da bandi italiani:
- `["scuole secondarie di II grado", "centri di formazione professionale"]`
- `["micro, piccole e medie imprese", "consorzi di filiera"]`
- `["enti pubblici", "ONG", "associazioni di volontariato"]`
- `["docenti universitari", "ricercatori under 40"]`

Mantieni il fraseggio originale se è chiaro. Spezza in array dove il bando elenca con virgole o bullet.

### `tematica` (array di string, mai null — `[]` se vuoto)

Aree tematiche del bando. Stringhe libere.

Cerca:
- Titolo dell'avviso ("Avviso per la formazione 4.0 nel settore manifatturiero")
- Sezione "Obiettivi", "Finalità", "Ambito di intervento"
- Asse/Misura del programma operativo ("Asse III — Istruzione e formazione")

Esempi:
- `["formazione", "competenze digitali", "Industria 4.0"]`
- `["ricerca scientifica", "cooperazione transfrontaliera"]`
- `["inclusione sociale", "contrasto alla povertà"]`
- `["transizione ecologica", "efficientamento energetico"]`

### `scadenza` (date `YYYY-MM-DD`, nullable)

Termine ultimo per la presentazione delle domande. Cerca:
- "Le domande devono essere presentate entro le ore X del [data]"
- "Termine ultimo: [data]"
- "Scadenza: [data]"
- "Il presente avviso scade il [data]"
- Tabelle "Scadenze" con righe `Presentazione domande` + data

Formato accettato in input dal bando:
- `30 settembre 2026` → `2026-09-30`
- `30/09/2026` → `2026-09-30`
- `30.09.2026` → `2026-09-30`

**Ambiguità**: se il bando ha più scadenze (es. fasi successive), usa la PROSSIMA scadenza utile dalla data odierna. Se sono già tutte scadute, usa l'ultima. Annota nelle `fonti[]` quale scadenza hai scelto.

**Bandi a sportello**: se il bando dichiara "sportello aperto fino ad esaurimento risorse" senza data, lascia `scadenza = null` e scrivi nella descrizione "sportello aperto fino ad esaurimento risorse".

### `scadenza_stato` (enum string, nullable)

Calcolato automaticamente, NON estratto dal testo. Vedi `SKILL.md` STEP 4d.

### `importo_totale_eur` (bigint, nullable)

Dotazione finanziaria complessiva del bando in **euro interi**.

Cerca:
- "Dotazione finanziaria: € X"
- "Lo stanziamento totale è pari a € X"
- "Per il finanziamento del presente avviso sono stanziati € X"

Normalizzazione:
- `€ 12.500.000,00` → `12500000`
- `12,5 milioni di euro` → `12500000`
- `12.5 M€` → `12500000`
- `500 mila euro` → `500000`

**Mai** lasciare in centesimi. Mai usare float. Solo interi positivi.

### `importo_max_per_progetto_eur` (bigint, nullable)

Tetto massimo di finanziamento per singolo progetto/domanda.

Cerca:
- "Il contributo massimo è pari a € X"
- "Importo massimo per progetto: € X"
- "Ciascun progetto può ricevere fino a € X"

Stessa normalizzazione di `importo_totale_eur`.

Se il bando definisce intervalli (es. 50k-200k), usa il massimo.

### `link_candidatura` (URL, nullable)

URL della pagina/form per presentare la domanda. Spesso coincide con `source_url`, ma in molti portali c'è un link esplicito tipo:
- "Per presentare domanda accedere a: https://bandi.regione.*/avviso-xyz"
- "Modulo di domanda online: ..."
- "Sistema informativo Bandi On Line"

Se trovi un link diverso da `source_url` e che sembra essere un sistema di candidatura (parole chiave: "domanda", "candidatura", "modulo", "form", "presentazione"), usalo. Altrimenti `source_url`.

**Verifica obbligatoria**: il link deve essere raggiungibile (vedi `SKILL.md` STEP 4c).

### `riferimento_normativo` (string, nullable)

Atto che istituisce il bando. Cerca:
- "ai sensi della DGR n. XX/2026"
- "DM n. XX del [data]"
- "Regolamento UE n. XXXX/2021"
- "PNRR — Missione X, Componente Y, Investimento Z"
- "Decreto Direttoriale n. XX del [data]"

Riporta la sigla intera così come scritta nel bando.

## Domini e hint noti

I domini sotto sono i portali ricorrenti nel CSV `elenco_bandi.csv`. `config/sources.json` mappa ciascun dominio agli hint default. Usali come pre-compilato, ma **sovrascrivi sempre** se il bando concreto dichiara qualcosa di diverso.

| Dominio | Ente | Tipologia default | Area |
|---|---|---|---|
| `ue.regione.lombardia.it` | Regione Lombardia | misto | Lombardia |
| `fesr.regione.lombardia.it` | Regione Lombardia | FESR | Lombardia |
| `fse.regione.lombardia.it` | Regione Lombardia | FSE | Lombardia |
| `regione.liguria.it` | Regione Liguria | regionale | Liguria |
| `regione.toscana.it` | Regione Toscana | regionale | Toscana |
| `regione.piemonte.it` | Regione Piemonte | regionale | Piemonte |
| `bandi.regione.piemonte.it` | Regione Piemonte | regionale | Piemonte |
| `sicilia-fse.it` | Regione Siciliana | FSE | Sicilia |
| `coesione.regione.abruzzo.it` | Regione Abruzzo | misto | Abruzzo |
| `lazioeuropa.it` | Regione Lazio | misto | Lazio |
| `regione.sardegna.it` | Regione Sardegna | regionale | Sardegna |
| `programmazione-ue-2021-2027.regione.veneto.it` | Regione Veneto | misto | Veneto |
| `spazio-operatori.regione.veneto.it` | Regione Veneto | regionale | Veneto |
| `prfesr2127.regione.campania.it` | Regione Campania | FESR | Campania |
| `fse.regione.campania.it` | Regione Campania | FSE | Campania |
| `fesr.regione.emilia-romagna.it` | Regione Emilia-Romagna | FESR | Emilia-Romagna |
| `formazionelavoro.regione.emilia-romagna.it` | Regione Emilia-Romagna | FSE | Emilia-Romagna |
| `regione.umbria.it` | Regione Umbria | regionale | Umbria |
| `regione.puglia.it` | Regione Puglia | regionale | Puglia |
| `sistema.puglia.it` | Regione Puglia | regionale | Puglia |
| `jtf-taranto.regione.puglia.it` | Regione Puglia | JTF | Puglia |
| `new.regione.vda.it` | Regione Valle d'Aosta | regionale | Valle d'Aosta |
| `provincia.tn.it` | Provincia autonoma di Trento | regionale | Trentino |
| `interregeurope.eu` | Interreg Europe | Interreg | UE |
| `interreg-alcotra.eu` | Interreg Alcotra | Interreg | transfrontaliera Italia-Francia |
| `interreg-marittimo.eu` | Interreg Italia-Francia Marittimo | Interreg | transfrontaliera |
| `interreg-ipa-adrion.eu` | Interreg IPA Adrion | Interreg | transnazionale Adriatico-Ionico |
| `interreg-euro-med.eu` | Interreg Euro-MED | Interreg | transnazionale Mediterraneo |
| `interregnextmed.eu` | Interreg NEXT MED | Interreg | transfrontaliera mediterranea |
| `italy-croatia.eu` | Interreg Italia-Croazia | Interreg | transfrontaliera |

## Casi limite

### Calendario di avvisi (PDF tabellare)

Quando il PDF è un calendario tipo `Calendario-avvisi-FSE-06072023.pdf` con righe di avvisi:
1. Estrai il bando di copertina (titolo del calendario, ente, fondo)
2. Lista gli avvisi del calendario come **sezione "Avvisi previsti"** nel contenuto editoriale (numbered_list)
3. NON spezzare in N bandi distinti in questo batch — saranno N nuovi URL da aggiungere al CSV in una fase successiva

### Pagina di portale che linka 10 bandi

Quando l'URL è una landing che linka N bandi (es. "Tutti gli avvisi FESR aperti"):
1. Marca come `skipped_landing` nel riepilogo
2. Aggiungi i N link bando al CSV per il prossimo batch
3. Non generare un singolo articolo confuso

### Bando in lingua inglese (Interreg)

Per bandi UE in inglese:
1. Estrai i campi strutturati così come sono (mantieni "Joint Secretariat" come `ente_erogatore` se è quello)
2. Genera il contenuto editoriale in **italiano** (traduzione editoriale, non letterale)
3. Mantieni `riferimento_normativo` in inglese (es. "Regulation (EU) 2021/1058")
4. `area_geografica` in italiano (`transfrontaliera Italia-Croazia`, non `cross-border Italy-Croatia`)

### Importi in valute miste

Per bandi UE con cofinanziamento espresso in più valute:
- Usa l'importo totale UE in euro
- Se il bando dichiara solo cofinanziamento nazionale in altre valute, lascia `importo_totale_eur = null` e scrivi nel contenuto editoriale che la dotazione è in valuta locale
