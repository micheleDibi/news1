/**
 * Generatore dei blocchi SQL delle migrazioni 04 e 13 dalla tabella condivisa
 * `tests/stato-bando/casi.json` (piano §16.2 M11: il generatore vive nei test,
 * perché `scripts/` è fuori perimetro).
 *
 * Blocchi delimitati da marcatori, così i test possono confrontarli byte per
 * byte con quelli presenti nei file SQL: se qualcuno ritocca l'SQL a mano o
 * aggiunge un caso al fixture senza rigenerare, il confronto fallisce. I due
 * blocchi della 13 (CERTEZZA e delta delle transizioni) rispettano le righe di
 * al massimo 45 caratteri delle migrazioni nuove (`LARGHEZZA_MIGRAZIONI`).
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
  /** Migrazione che semina la riga; assente = seed della 04. */
  readonly migrazione?: number;
}

/**
 * Caso della regola `stato_da_verificare`: gli ingressi nell'ordine della
 * firma di `bando_stato_da_verificare` (contratto interno del giro 2, §3 con
 * §19.3), poi l'atteso. `regola` e `nota` sono documentazione.
 */
export interface CasoCertezza {
  readonly id: string;
  readonly stato: string | null;
  readonly data_apertura: string | null;
  readonly apertura_verificata: boolean | null;
  readonly ora_apertura: string | null;
  readonly data_scadenza: string | null;
  readonly ora_scadenza: string | null;
  readonly pubblicato_at: string | null;
  readonly previsto_entro: string | null;
  readonly termine_indicato: string | null;
  readonly stato_letto: string | null;
  readonly stato_letto_su: string | null;
  readonly stato_letto_at: string | null;
  readonly stato_letto_metodo: string | null;
  readonly esaminato_attivo_at: string | null;
  readonly segnale_aggregatore_at: string | null;
  readonly adesso: string;
  readonly atteso: string | null;
  readonly regola: string;
  readonly nota: string;
}

export interface DatiCertezza {
  readonly versione: number;
  readonly parametri: {
    readonly giorni_grazia_pubblicazione: number;
    readonly giorni_validita_conferma: number;
    readonly giorni_grazia_ramo_a: number;
  };
  readonly motivi: readonly string[];
  readonly stati_letti: readonly string[];
  readonly metodi: readonly string[];
  readonly conteggio_minimo: number;
  readonly casi: readonly CasoCertezza[];
}

export interface DatiStatoBando {
  readonly versione: number;
  readonly transizioni: readonly TransizioneSeed[];
  readonly casi: readonly CasoStatoBando[];
  readonly certezza?: DatiCertezza;
}

export const MARCATORE_CASI_INIZIO = '-- >>> CASI';
export const MARCATORE_CASI_FINE = '-- <<< CASI';
export const MARCATORE_TRANSIZIONI_INIZIO = '-- >>> TRANSIZIONI';
export const MARCATORE_TRANSIZIONI_FINE = '-- <<< TRANSIZIONI';
// Prefissi: la riga intera porta la versione (`-- >>> CERTEZZA v2`) o la
// migrazione (`-- >>> TRANSIZIONI delta 13`), e cosi' anche la chiusura.
export const MARCATORE_CERTEZZA_INIZIO = '-- >>> CERTEZZA';
export const MARCATORE_CERTEZZA_FINE = '-- <<< CERTEZZA';
export const MARCATORE_DELTA_INIZIO = '-- >>> TRANSIZIONI delta';
export const MARCATORE_DELTA_FINE = '-- <<< TRANSIZIONI delta';

/** Righe di al massimo 45 caratteri nelle migrazioni dalla 12 in poi. */
export const LARGHEZZA_MIGRAZIONI = 45;

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
  // Solo le righe della 04: quelle con `migrazione` le semina il delta di
  // quella migrazione, e il blocco della 04 resta identico byte per byte.
  const seed = dati.transizioni.filter((transizione) => transizione.migrazione === undefined);
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
  seed.forEach((transizione, indice) => {
    const virgola = indice === seed.length - 1 ? '' : ',';
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

/**
 * Dispone i valori su righe di al massimo `LARGHEZZA_MIGRAZIONI` caratteri:
 * la prima riga comincia con `apertura`, le successive con `rientro`, i valori
 * sono separati da `, ` e l'ultimo è seguito da `coda`. Un valore più largo
 * della riga resta intero: il test sulla larghezza lo segnala.
 */
function impagina(valori: readonly string[], apertura: string, rientro: string, coda: string): string[] {
  const righe: string[] = [];
  let corrente = '';
  valori.forEach((valore, indice) => {
    const pezzo = `${valore}${indice === valori.length - 1 ? coda : ','}`;
    if (indice === 0) {
      corrente = `${apertura}${pezzo}`;
    } else if (corrente.length + 1 + pezzo.length > LARGHEZZA_MIGRAZIONI) {
      righe.push(corrente);
      corrente = `${rientro}${pezzo}`;
    } else {
      corrente = `${corrente} ${pezzo}`;
    }
  });
  righe.push(corrente);
  return righe;
}

/**
 * Spezza un testo in pezzi che, come letterali SQL, non superano `massimo`
 * caratteri; si va a capo dopo uno spazio quando si può. La concatenazione
 * dei pezzi restituisce il testo intatto.
 */
function spezza(testo: string, massimo: number): string[] {
  const pezzi: string[] = [];
  let corrente = '';
  for (const parola of testo.match(/[^ ]+ *| +/g) ?? []) {
    // una parola più larga del pezzo si spezza carattere per carattere
    const unita = lett(parola).length > massimo ? [...parola] : [parola];
    for (const unitaTesto of unita) {
      if (corrente !== '' && lett(corrente + unitaTesto).length > massimo) {
        pezzi.push(corrente);
        corrente = '';
      }
      corrente += unitaTesto;
    }
  }
  if (corrente !== '' || pezzi.length === 0) pezzi.push(corrente);
  return pezzi;
}

// Colonne del `values` e tipo con cui ogni ingresso arriva alla funzione, in
// ordine di firma (contratto interno del giro 2, §2.2 punto 4 e §19.2).
const INGRESSI_CERTEZZA: readonly (readonly [keyof CasoCertezza, string])[] = [
  ['stato', 'text'],
  ['data_apertura', 'date'],
  ['apertura_verificata', 'boolean'],
  ['ora_apertura', 'time'],
  ['data_scadenza', 'date'],
  ['ora_scadenza', 'time'],
  ['pubblicato_at', 'timestamptz'],
  ['previsto_entro', 'date'],
  ['termine_indicato', 'date'],
  ['stato_letto', 'text'],
  ['stato_letto_su', 'text'],
  ['stato_letto_at', 'timestamptz'],
  ['stato_letto_metodo', 'text'],
  ['esaminato_attivo_at', 'timestamptz'],
  ['segnale_aggregatore_at', 'timestamptz'],
  ['adesso', 'timestamptz'],
];

function valoreSql(valore: string | boolean | null): string {
  return typeof valore === 'boolean' ? booleano(valore) : lett(valore);
}

/**
 * Blocco `-- >>> CERTEZZA vN … -- <<< CERTEZZA vN` della migrazione 13: una
 * select che confronta `public.bando_stato_da_verificare(...)` con l'atteso
 * della sezione `certezza` e restituisce solo le righe discordanti (atteso: 0
 * righe). Il `values` non porta cast (ogni colonna resta testo, o booleano),
 * i tipi li fissano i cast sugli argomenti posizionali della chiamata.
 */
export function generaBloccoCertezza(certezza: DatiCertezza): string {
  const colonne = ['id', ...INGRESSI_CERTEZZA.map(([nome]) => nome), 'atteso'];
  const righe: string[] = [
    `${MARCATORE_CERTEZZA_INIZIO} v${certezza.versione}`,
    '-- Generato da tests/stato-bando/',
    '-- genera-sql.ts: non modificare a mano.',
    '-- Confronta la funzione',
    '-- public.bando_stato_da_verificare()',
    '-- con la sezione certezza di',
    `-- tests/stato-bando/casi.json (${certezza.casi.length} casi).`,
    '-- Da eseguire nel SQL Editor dopo la 13:',
    '-- atteso 0 righe.',
    'with casi (',
    ...impagina(colonne, '  ', '  ', ''),
    ') as (',
    '  values',
  ];
  certezza.casi.forEach((caso, indice) => {
    const valori = colonne.map((nome) => valoreSql(caso[nome as keyof CasoCertezza] as string | boolean | null));
    righe.push(...impagina(valori, '    (', '     ', indice === certezza.casi.length - 1 ? ')' : '),'));
  });
  righe.push(
    '), esiti as (',
    '  select',
    '    c.id,',
    '    c.atteso,',
    '    public.bando_stato_da_verificare(',
    ...INGRESSI_CERTEZZA.map(([nome, tipo], indice) =>
      `      c.${nome}::${tipo}${indice === INGRESSI_CERTEZZA.length - 1 ? '' : ','}`),
    '    ) as ottenuto',
    '  from casi c',
    ')',
    'select e.id, e.atteso, e.ottenuto',
    'from esiti e',
    'where e.ottenuto is distinct from e.atteso',
    'order by e.id;',
    `${MARCATORE_CERTEZZA_FINE} v${certezza.versione}`,
  );
  return righe.join('\n');
}

/**
 * Blocco `-- >>> TRANSIZIONI delta N … -- <<< TRANSIZIONI delta N`: le righe
 * della lista bianca che entrano con la migrazione `migrazione` (campo
 * `migrazione` delle transizioni), con lo stesso `where not exists` del seed
 * della 04. La condizione è spezzata in letterali concatenati per stare nelle
 * righe di 45 caratteri; il rollback le toglie per (da, a, attore, evento).
 */
export function generaDeltaTransizioni(dati: DatiStatoBando, migrazione: number): string {
  const delta = dati.transizioni.filter((transizione) => transizione.migrazione === migrazione);
  if (delta.length === 0) throw new Error(`nessuna transizione con migrazione ${migrazione}`);
  const righe: string[] = [
    `${MARCATORE_DELTA_INIZIO} ${migrazione}`,
    '-- Generato da tests/stato-bando/',
    '-- genera-sql.ts: non modificare a mano.',
    '-- Righe di public.bando_transizione che',
    `-- entrano con la migrazione ${migrazione} (campo`,
    '-- migrazione di tests/stato-bando/',
    '-- casi.json). Rieseguibile: where not',
    '-- exists come nel seed della 04.',
    'insert into public.bando_transizione',
    '  (da, a, attore, evento, condizione)',
    'select v.da, v.a, v.attore, v.evento,',
    '  v.condizione',
    'from (values',
  ];
  delta.forEach((transizione, indice) => {
    const cast = indice === 0 ? '::text' : '';
    const valori = [transizione.da, transizione.a, transizione.attore, transizione.evento]
      .map((valore) => `${lett(valore)}${cast}`);
    righe.push(...impagina(valori, '  (', '   ', ','));
    const coda = indice === delta.length - 1 ? ')' : '),';
    const pezzi = spezza(transizione.condizione, LARGHEZZA_MIGRAZIONI - 11);
    pezzi.forEach((pezzo, posizione) => {
      const inizio = posizione === 0 ? '   ' : '    || ';
      righe.push(`${inizio}${lett(pezzo)}${posizione === pezzi.length - 1 ? coda : ''}`);
    });
  });
  righe.push(
    ') as v (da, a, attore, evento, condizione)',
    'where not exists (',
    '  select 1 from public.bando_transizione t',
    '  where t.da is not distinct from v.da',
    '    and t.a = v.a',
    '    and t.attore = v.attore',
    '    and t.evento = v.evento',
    ')',
    'on conflict do nothing;',
    `${MARCATORE_DELTA_FINE} ${migrazione}`,
  );
  return righe.join('\n');
}
