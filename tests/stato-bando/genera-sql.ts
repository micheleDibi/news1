/**
 * Generatore dei blocchi SQL della migrazione 04 dalla tabella condivisa
 * `tests/stato-bando/casi.json` (piano §16.2 M11: il generatore vive nei test,
 * perché `scripts/` è fuori perimetro).
 *
 * Due blocchi delimitati da marcatori, così il test può confrontarli byte per
 * byte con quelli presenti nel file SQL: se qualcuno ritocca l'SQL a mano o
 * aggiunge un caso al fixture senza rigenerare, il confronto fallisce.
 *
 * Funzioni pure: nessuna lettura di file, nessuna scrittura, nessun `process`.
 */

export interface CasoStatoBando {
  readonly id: string;
  readonly stato: string | null;
  readonly data_apertura: string | null;
  readonly apertura_verificata: boolean | null;
  readonly ora_apertura: string | null;
  readonly data_scadenza: string | null;
  readonly ora_scadenza: string | null;
  readonly adesso: string;
  readonly atteso: string | null;
  readonly nota: string;
}

export interface TransizioneSeed {
  readonly da: string | null;
  readonly a: string;
  readonly attore: string;
  readonly evento: string;
  readonly condizione: string;
}

export interface DatiStatoBando {
  readonly versione: number;
  readonly transizioni: readonly TransizioneSeed[];
  readonly casi: readonly CasoStatoBando[];
}

export const MARCATORE_CASI_INIZIO = '-- >>> CASI';
export const MARCATORE_CASI_FINE = '-- <<< CASI';
export const MARCATORE_TRANSIZIONI_INIZIO = '-- >>> TRANSIZIONI';
export const MARCATORE_TRANSIZIONI_FINE = '-- <<< TRANSIZIONI';

/** Letterale SQL: apici raddoppiati, NULL nudo per l'assenza di valore. */
function lett(valore: string | null): string {
  return valore === null ? 'NULL' : `'${valore.replace(/'/g, "''")}'`;
}

function booleano(valore: boolean | null): string {
  return valore === null ? 'NULL' : String(valore);
}

/**
 * Riga del `values`: i cast stanno solo sulla prima riga (`conCast`), che fissa
 * il tipo di ogni colonna; le righe successive li ereditano.
 */
function rigaCaso(caso: CasoStatoBando, conCast: boolean): string {
  const c = (valore: string, tipo: string) => (conCast ? `${valore}::${tipo}` : valore);
  return [
    c(lett(caso.id), 'text'),
    c(lett(caso.stato), 'text'),
    c(lett(caso.data_apertura), 'date'),
    c(booleano(caso.apertura_verificata), 'boolean'),
    c(lett(caso.ora_apertura), 'time'),
    c(lett(caso.data_scadenza), 'date'),
    c(lett(caso.ora_scadenza), 'time'),
    c(lett(caso.adesso), 'timestamptz'),
    c(lett(caso.atteso), 'text'),
  ].join(', ');
}

// Nomi delle colonne del DB (§13.0): nel fixture il campo si chiama
// `apertura_verificata`, a DB la colonna e' `data_apertura_verificata`.
const ARGOMENTI = 'c.stato, c.data_apertura, c.data_apertura_verificata, c.ora_apertura, c.data_scadenza, c.ora_scadenza, c.adesso';

/**
 * Blocco `-- >>> CASI … -- <<< CASI`: una sola select che confronta
 * `public.bando_stato_effettivo(...)` con l'atteso del fixture e restituisce
 * solo le righe discordanti. Va eseguito nel SQL Editor a ogni applicazione
 * della 04; l'esito atteso è zero righe.
 */
export function generaBloccoCasi(dati: DatiStatoBando): string {
  const righe: string[] = [
    `${MARCATORE_CASI_INIZIO} v${dati.versione} (generato da tests/stato-bando/genera-sql.ts: non modificare a mano)`,
    '-- Confronta public.bando_stato_effettivo() con tests/stato-bando/casi.json.',
    '-- Da eseguire nel SQL Editor a ogni applicazione della 04: atteso 0 righe.',
    '-- Firma attesa (posizionale, in quest\'ordine): public.bando_stato_effettivo(',
    '--   stato text, data_apertura date, data_apertura_verificata boolean,',
    '--   ora_apertura time, data_scadenza date, ora_scadenza time,',
    '--   adesso timestamptz) returns text.',
    'with casi (id, stato, data_apertura, data_apertura_verificata, ora_apertura, data_scadenza, ora_scadenza, adesso, atteso) as (',
    '  values',
  ];
  dati.casi.forEach((caso, indice) => {
    const virgola = indice === dati.casi.length - 1 ? '' : ',';
    righe.push(`    (${rigaCaso(caso, indice === 0)})${virgola}`);
  });
  righe.push(
    ')',
    'select',
    '  c.id,',
    '  c.atteso,',
    `  public.bando_stato_effettivo(${ARGOMENTI}) as ottenuto`,
    'from casi c',
    `where public.bando_stato_effettivo(${ARGOMENTI}) is distinct from c.atteso`,
    'order by c.id;',
    MARCATORE_CASI_FINE,
  );
  return righe.join('\n');
}

/**
 * Blocco `-- >>> TRANSIZIONI … -- <<< TRANSIZIONI`: seed della tabella interna
 * `bando_transizione` dalla stessa tabella di verità.
 *
 * Rieseguibile senza dipendere da nessun vincolo (§16.2 M5): il `where not
 * exists` confronta anche le righe di creazione con `is not distinct from`,
 * che `ON CONFLICT DO NOTHING` non saprebbe deduplicare (senza target non
 * deduplica nulla, e con un `UNIQUE (da, a, attore, evento)` le righe con
 * `da IS NULL` gli sfuggono, perché due NULL non sono uguali). L'`ON CONFLICT
 * DO NOTHING` resta come seconda cintura per le esecuzioni concorrenti.
 */
export function generaSeedTransizioni(dati: DatiStatoBando): string {
  const righe: string[] = [
    `${MARCATORE_TRANSIZIONI_INIZIO} v${dati.versione} (generato da tests/stato-bando/genera-sql.ts: non modificare a mano)`,
    '-- Seed di public.bando_transizione dalla tabella di §4 (tests/stato-bando/casi.json).',
    '-- da IS NULL = creazione della riga. Quello che non c\'è non è ammesso.',
    '-- Rieseguibile senza vincoli: il where not exists tratta come uguali anche',
    '-- le righe con da IS NULL, che ON CONFLICT DO NOTHING non deduplicherebbe.',
    'insert into public.bando_transizione (da, a, attore, evento, condizione)',
    'select v.da, v.a, v.attore, v.evento, v.condizione',
    'from (values',
  ];
  dati.transizioni.forEach((transizione, indice) => {
    const virgola = indice === dati.transizioni.length - 1 ? '' : ',';
    const cast = indice === 0 ? '::text' : '';
    const valori = [
      lett(transizione.da),
      lett(transizione.a),
      lett(transizione.attore),
      lett(transizione.evento),
      lett(transizione.condizione),
    ].map((valore) => `${valore}${cast}`).join(', ');
    righe.push(`  (${valori})${virgola}`);
  });
  righe.push(
    ') as v (da, a, attore, evento, condizione)',
    'where not exists (',
    '  select 1 from public.bando_transizione t',
    '  where t.da is not distinct from v.da',
    '    and t.a = v.a and t.attore = v.attore and t.evento = v.evento',
    ')',
    'on conflict do nothing;',
    MARCATORE_TRANSIZIONI_FINE,
  );
  return righe.join('\n');
}
