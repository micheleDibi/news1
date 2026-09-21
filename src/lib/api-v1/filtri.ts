/**
 * Piano delle query dell'API /api/v1 (puro).
 *
 * Qui, e solo qui, stanno le condizioni di pubblicazione, gli ordinamenti, i filtri e
 * i limiti: fonte-supabase.ts esegue il piano senza aggiungere nulla. Le condizioni
 * di pubblicazione valgono per OGNI modo (elenco, dettaglio, feed): un dettaglio non
 * deve mai servire una bozza.
 *
 * A PostgREST arrivano solo: costanti, enum, interi, istanti riformattati da noi,
 * valori presi da whitelist (registro regioni, riferimento categorie, valori del
 * corpus ammessi) e cursori validati. Mai stringhe grezze del client.
 */
import { ELEMENTI_FEED, MARGINE_FUSO_MS } from './costanti';
import { muroRoma, muroUtc } from './tempo';
import type { FiltriElenco } from './parametri';
import type { PosizioneCursore } from './cursore';
import type { NomeSelect, Operazione, PianoQuery, Risorsa, Tabella } from './contratto';

export type ModoQuery = 'elenco' | 'dettaglio' | 'feed';

export interface ContestoPiano {
  modo: ModoQuery;
  /** Filtri validati (solo per gli elenchi). */
  filtri: FiltriElenco | null;
  /** Articoli: slug delle categorie valide del riferimento (esclude categorie inesistenti come 'bandi'). */
  slugCategorieValide: readonly string[];
  /** Articoli: categoria gia' verificata sul riferimento (filtro dell'elenco o feed di categoria). */
  categoria: string | null;
  /** Interpelli e selezione: valori DB ammessi per la regione richiesta (null = nessun filtro regione). */
  valoriRegione: readonly string[] | null;
  /** YYYY-MM-DD di Roma (feed della selezione: esclude gli scaduti). */
  oggi: string;
  /** Posizione dopo cui continuare (keyset). */
  dopo: PosizioneCursore | null;
  /** Dettaglio: id richiesto. */
  id: number | null;
  /** Elenco: righe da leggere (limit + 1 per sapere se ce ne sono altre). */
  righe: number;
}

/** Colonna di ordinamento (e del cursore) per ciascuna risorsa. */
export const COLONNA_ORDINAMENTO: ReadonlyMap<Risorsa, string> = new Map<Risorsa, string>([
  ['articles', 'published_at'],
  ['interpelli', 'interpello_date'],
  ['selezione-personale', 'data_pubblicazione'],
  ['bandi', 'created_at'],
]);

const TABELLA: ReadonlyMap<Risorsa, Tabella> = new Map<Risorsa, Tabella>([
  ['articles', 'articles'],
  ['interpelli', 'interpelli'],
  ['selezione-personale', 'selezione_personale'],
  ['bandi', 'bando'],
]);

// ---------------------------------------------------------------------------
// Costruttori di valori PostgREST
// ---------------------------------------------------------------------------

function tra(valore: string): string {
  return '"' + valore.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

/**
 * Lista per l'operatore `in`: ogni elemento sempre fra doppi apici con escape di `\` e `"`.
 * NON usare `.in()` di postgrest-js 1.17.7: quota solo i valori che contengono `,()` e
 * non fa escape. Lista vuota -> errore: PostgREST risponderebbe 200 [] a `in.()`.
 */
export function listaInPg(valori: readonly string[]): string {
  const unici = [...new Set(valori)];
  if (unici.length === 0) throw new RangeError('listaInPg: lista vuota');
  return '(' + unici.map(tra).join(',') + ')';
}

/** Letterale di array Postgres per `cs`/`ov`: {"a","b"} con lo stesso escape. */
export function letteraleArrayPg(valori: readonly string[]): string {
  const unici = [...new Set(valori)];
  if (unici.length === 0) throw new RangeError('letteraleArrayPg: lista vuota');
  return '{' + unici.map(tra).join(',') + '}';
}

/**
 * Condizione keyset per un ordinamento `colonna desc, id desc`: le righe strettamente
 * dopo (grezzo, id). Il valore grezzo arriva dal cursore gia' validato (nessun `" , ( ) \`)
 * e va comunque fra doppi apici: contiene `:`, `.` e `+`.
 */
export function condizioneKeyset(colonna: string, dopo: PosizioneCursore): string {
  const valore = tra(dopo.grezzo);
  return `${colonna}.lt.${valore},and(${colonna}.eq.${valore},id.lt.${dopo.id})`;
}

// ---------------------------------------------------------------------------
// Piano per risorsa
// ---------------------------------------------------------------------------

const filtro = (colonna: string, operatore: Extract<Operazione, { tipo: 'filtro' }>['operatore'], valore: string): Operazione =>
  ({ tipo: 'filtro', colonna, operatore, valore });
const or = (espressione: string): Operazione => ({ tipo: 'or', espressione });
const ordina = (colonna: string, crescente: boolean): Operazione => ({ tipo: 'ordina', colonna, crescente });
const limite = (n: number): Operazione => ({ tipo: 'limite', n });

const isoUtc = (ms: number) => new Date(ms).toISOString();

function limiteDelModo(contesto: ContestoPiano): Operazione {
  if (contesto.modo === 'dettaglio') return limite(1);
  if (contesto.modo === 'feed') return limite(ELEMENTI_FEED);
  return limite(contesto.righe);
}

function coda(risorsa: Risorsa, contesto: ContestoPiano): Operazione[] {
  const colonna = COLONNA_ORDINAMENTO.get(risorsa) as string;
  const ops: Operazione[] = [];
  if (contesto.modo === 'dettaglio') {
    if (contesto.id === null) throw new RangeError('pianoQuery: dettaglio senza id');
    ops.push(filtro('id', 'eq', String(contesto.id)));
  }
  if (contesto.modo === 'elenco' && contesto.dopo) ops.push(or(condizioneKeyset(colonna, contesto.dopo)));
  ops.push(ordina(colonna, false), ordina('id', false), limiteDelModo(contesto));
  return ops;
}

function pianoArticoli(contesto: ContestoPiano): Operazione[] {
  const f = contesto.filtri;
  const ops: Operazione[] = [
    filtro('isdraft', 'eq', 'false'),
    contesto.categoria !== null
      ? filtro('category_slug', 'eq', contesto.categoria)
      : filtro('category_slug', 'in', listaInPg(contesto.slugCategorieValide)),
    filtro('published_at', 'not.is', 'null'),
  ];
  if (contesto.modo === 'elenco' && f) {
    // published_at e' senza fuso e mescola UTC e ora di Roma: l'istante vero sta in
    // [muro - 2h, muro]. Sul DB un superinsieme esatto, il taglio preciso nell'app.
    if (f.since !== null) ops.push(filtro('published_at', 'gte', muroUtc(f.since)));
    if (f.until !== null) ops.push(filtro('published_at', 'lt', muroUtc(f.until + MARGINE_FUSO_MS)));
    if (f.has_video === true) ops.push(filtro('video_url', 'like', 'http*'));
    if (f.has_video === false) ops.push(or('video_url.is.null,video_url.not.like.http*'));
  }
  return [...ops, ...coda('articles', contesto)];
}

function pianoInterpelli(contesto: ContestoPiano): Operazione[] {
  const f = contesto.filtri;
  const ops: Operazione[] = [
    filtro('link_type', 'eq', 'single'),
    filtro('status', 'eq', 'completed'),
    filtro('interpello_date', 'not.is', 'null'),
  ];
  if (contesto.modo === 'elenco' && f) {
    if (contesto.valoriRegione !== null) ops.push(filtro('interpello_regione', 'in', listaInPg(contesto.valoriRegione)));
    // interpello_date e' un timestamp senza fuso con il giorno della fonte: muro di Roma.
    if (f.since !== null) ops.push(filtro('interpello_date', 'gte', muroRoma(f.since)));
    if (f.until !== null) ops.push(filtro('interpello_date', 'lt', muroRoma(f.until)));
  }
  return [...ops, ...coda('interpelli', contesto)];
}

function pianoSelezione(contesto: ContestoPiano): Operazione[] {
  const f = contesto.filtri;
  const ops: Operazione[] = [
    filtro('status', 'eq', 'completed'),
    filtro('data_pubblicazione', 'not.is', 'null'),
  ];
  if (contesto.modo === 'feed') {
    // Feed: solo annunci non scaduti (stessa regola della lista del sito), ordinati per
    // aggiornamento: per data_pubblicazione il feed perderebbe gran parte dei nuovi.
    return [
      ...ops,
      filtro('data_scadenza', 'gte', `${contesto.oggi}T00:00:00+00:00`),
      ordina('updated_at', false),
      ordina('id', false),
      limite(ELEMENTI_FEED),
    ];
  }
  if (contesto.modo === 'elenco' && f) {
    if (contesto.valoriRegione !== null) ops.push(filtro('sedi', 'ov', letteraleArrayPg(contesto.valoriRegione)));
    if (f.national === true) ops.push(filtro('sedi', 'cs', '{"Nazionale"}'));
    if (f.national === false) ops.push(or('sedi.is.null,sedi.not.cs.{Nazionale}'));
    if (f.since !== null) ops.push(filtro('data_pubblicazione', 'gte', isoUtc(f.since)));
    if (f.until !== null) ops.push(filtro('data_pubblicazione', 'lt', isoUtc(f.until)));
    if (f.updated_since !== null) ops.push(filtro('updated_at', 'gte', isoUtc(f.updated_since)));
  }
  return [...ops, ...coda('selezione-personale', contesto)];
}

function pianoBandi(contesto: ContestoPiano): Operazione[] {
  const f = contesto.filtri;
  // Filtro equivalente alla RLS pubblica, ripetuto: l'API resta corretta anche se la policy cambia.
  const ops: Operazione[] = [
    filtro('stato_processing', 'eq', 'completed'),
    filtro('slug', 'not.is', 'null'),
    filtro('created_at', 'not.is', 'null'),
  ];
  if (contesto.modo === 'elenco' && f) {
    if (f.region !== null) ops.push(filtro('filtro_regione.regioni.slug', 'eq', f.region));
    if (f.national === true) ops.push(filtro('area_geografica', 'ilike', 'nazionale'));
    if (f.national === false) ops.push(or('area_geografica.is.null,area_geografica.not.ilike.nazionale'));
    if (f.since !== null) ops.push(filtro('created_at', 'gte', isoUtc(f.since)));
    if (f.until !== null) ops.push(filtro('created_at', 'lt', isoUtc(f.until)));
    if (f.updated_since !== null) ops.push(filtro('updated_at', 'gte', isoUtc(f.updated_since)));
  }
  return [...ops, ...coda('bandi', contesto)];
}

function selectDi(risorsa: Risorsa, contesto: ContestoPiano): NomeSelect {
  switch (risorsa) {
    case 'articles': return 'articolo';
    case 'interpelli': return 'interpello';
    case 'selezione-personale': return 'selezione';
    case 'bandi': return contesto.modo === 'elenco' && contesto.filtri?.region ? 'bando-con-regione' : 'bando';
  }
}

export function pianoQuery(risorsa: Risorsa, contesto: ContestoPiano): PianoQuery {
  let operazioni: Operazione[];
  switch (risorsa) {
    case 'articles': operazioni = pianoArticoli(contesto); break;
    case 'interpelli': operazioni = pianoInterpelli(contesto); break;
    case 'selezione-personale': operazioni = pianoSelezione(contesto); break;
    case 'bandi': operazioni = pianoBandi(contesto); break;
  }
  return {
    db: risorsa === 'bandi' ? 'bandi' : 'principale',
    tabella: TABELLA.get(risorsa) as Tabella,
    select: selectDi(risorsa, contesto),
    operazioni,
  };
}

export type TipoRiferimento = 'categories' | 'secondary_categories' | 'profiles';

/** Tabelle di riferimento: piccole, sempre con ordinamento e limite espliciti. */
export function pianoRiferimento(tipo: TipoRiferimento): PianoQuery {
  switch (tipo) {
    case 'categories':
      return { db: 'principale', tabella: 'categories', select: 'categorie',
        operazioni: [ordina('order_id', true), ordina('slug', true), limite(100)] };
    case 'secondary_categories':
      return { db: 'principale', tabella: 'secondary_categories', select: 'secondarie',
        operazioni: [ordina('slug', true), limite(300)] };
    case 'profiles':
      return { db: 'principale', tabella: 'profiles', select: 'profili',
        operazioni: [ordina('id', true), limite(500)] };
  }
}

// ---------------------------------------------------------------------------
// Esecuzione su un builder (postgrest-js o finto nei test)
// ---------------------------------------------------------------------------

/** Il sottoinsieme del builder di postgrest-js usato dai piani. */
export interface CostruttoreQuery {
  filter(colonna: string, operatore: string, valore: string): CostruttoreQuery;
  or(espressione: string): CostruttoreQuery;
  order(colonna: string, opzioni: { ascending: boolean }): CostruttoreQuery;
  limit(n: number): CostruttoreQuery;
}

/** Traduce ogni operazione in UNA chiamata del builder; e' l'unico punto che chiama i metodi di filtro. */
export function applicaPiano(costruttore: CostruttoreQuery, operazioni: readonly Operazione[]): CostruttoreQuery {
  let q = costruttore;
  for (const op of operazioni) {
    switch (op.tipo) {
      case 'filtro': q = q.filter(op.colonna, op.operatore, op.valore); break;
      case 'or': q = q.or(op.espressione); break;
      case 'ordina': q = q.order(op.colonna, { ascending: op.crescente }); break;
      case 'limite': q = q.limit(op.n); break;
    }
  }
  return q;
}
