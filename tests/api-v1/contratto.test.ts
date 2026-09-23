/**
 * Test di contratto: gli output reali dell'API (mapper e gestore con una FonteDati
 * finta) e gli esempi del documento OpenAPI sono validati contro gli schemi di
 * openapi.ts con un mini validatore JSON Schema scritto qui (nessuna dipendenza).
 *
 * - Una proprieta' presente nell'output ma non dichiarata dallo schema e' un errore:
 *   una colonna interna che trapela o un campo nuovo senza schema non passano.
 * - date-time: RFC 3339 senza frazioni di secondo e con l'offset di Europe/Rome in
 *   quell'istante (calcolato con Intl e timeZone esplicito: la suite gira con
 *   TZ=Asia/Kathmandu).
 * - Nei testi (campi senza format 'uri') nessun URL verso host diversi da edunews24.it.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { documentoOpenApi } from '../../src/lib/api-v1/openapi.ts';
import { CODICI_ERRORE } from '../../src/lib/api-v1/errori.ts';
import { SLUG_REGIONI } from '../../src/lib/api-v1/parametri.ts';
import { SEZIONI } from '../../src/lib/api-v1/sezioni.ts';
import { mappaArticolo } from '../../src/lib/api-v1/mappa-articoli.ts';
import { mappaCategorie } from '../../src/lib/api-v1/mappa-categorie.ts';
import { mappaBando, mappaInterpello, mappaSelezione } from '../../src/lib/api-v1/mappa-opportunita.ts';
import { costruisciRiferimentoCategorie, costruisciRiferimentoProfili } from '../../src/lib/api-v1/riferimenti.ts';
import { creaGestore } from '../../src/lib/api-v1/gestore.ts';
import {
  CATEGORIE, DETTAGLIO_ARTICOLO, DETTAGLIO_BANDO, DETTAGLIO_INTERPELLO, DETTAGLIO_SELEZIONE, ELENCO_ARTICOLI,
  ELENCO_BANDI, ELENCO_INTERPELLI, ELENCO_SELEZIONE, FEED, INDICE, NON_TROVATO,
} from '../../src/lib/api-v1/risorse.ts';
import { Limitatore } from '../../src/lib/api-v1/limitatore.ts';
import { Semaforo } from '../../src/lib/api-v1/semaforo.ts';
import { CacheRisposte } from '../../src/lib/api-v1/cache.ts';
import { ErroreDati } from '../../src/lib/api-v1/errori.ts';
import {
  RICHIESTA_ERRORE_PARAMETRI, esempioErroreLimite, esempioErroreParametri,
} from '../../src/lib/api-v1/testi-doc.ts';
import {
  BANDO_COMPLETO, COLONNE_VIETATE_BANDO, COLONNE_VIETATE_INTERPELLO, COLONNE_VIETATE_SELEZIONE, INTERPELLO_COMPLETO,
  SELEZIONE_COMPLETA,
} from './fixture/opportunita-complete.ts';
import { RIGHE_CATEGORIE, RIGHE_PROFILI, RIGHE_SECONDARIE } from './fixture/riferimenti-base.ts';
import type { DipendenzeGestore } from '../../src/lib/api-v1/gestore.ts';
import type { DescrittoreRotta, DipendenzeRisorse, RisultatoRisorsa } from '../../src/lib/api-v1/risorse.ts';
import type {
  FonteDati, NomeSelect, PianoQuery, RighePerSelect, RigaArticolo, RigaBando, RigaInterpello, RigaSelezione,
} from '../../src/lib/api-v1/contratto.ts';

type Oggetto = Record<string, unknown>;
type Schema = Oggetto;

const DOC = documentoOpenApi();
const COMPONENTI = DOC.components as Oggetto;
const SCHEMI = COMPONENTI.schemas as Record<string, Schema>;
const OGGI = '2026-09-21';

// ---------------------------------------------------------------------------
// Mini validatore JSON Schema: solo le parole chiave usate da openapi.ts
// ---------------------------------------------------------------------------

interface StringaVista {
  percorso: string;
  /** Nome del campo che contiene la stringa (per gli elementi di un array: il campo dell'array). */
  chiave: string;
  valore: string;
  /** Campo con format 'uri' o valore fissato da `const` nello schema: non e' testo libero. */
  esente: boolean;
}

interface Esito {
  errori: string[];
  stringhe: StringaVista[];
}

function schemaDaRef(schema: Schema): Schema {
  let s = schema;
  while (typeof s.$ref === 'string') {
    const prefisso = '#/components/schemas/';
    assert.ok(s.$ref.startsWith(prefisso), `$ref non gestito: ${s.$ref}`);
    const destinazione = SCHEMI[s.$ref.slice(prefisso.length)];
    assert.ok(destinazione, `schema assente: ${s.$ref}`);
    s = destinazione;
  }
  return s;
}

/** Proprieta' dichiarate da uno schema, seguendo $ref e allOf; null se non ne dichiara. */
function dichiarate(schema: Schema): Set<string> | null {
  const s = schemaDaRef(schema);
  const nomi = new Set(Object.keys((s.properties as Oggetto | undefined) ?? {}));
  let trovate = s.properties !== undefined;
  for (const parte of (s.allOf as Schema[] | undefined) ?? []) {
    const figlie = dichiarate(parte);
    if (figlie === null) continue;
    trovate = true;
    for (const nome of figlie) nomi.add(nome);
  }
  return trovate ? nomi : null;
}

function tipoDi(v: unknown): string {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number';
  return typeof v;
}

const OFFSET_ROMA = new Intl.DateTimeFormat('en-US', { timeZone: 'Europe/Rome', timeZoneName: 'longOffset' });

/** Offset di Europe/Rome nell'istante dato, come "+02:00". */
function offsetRoma(ms: number): string {
  const nome = OFFSET_ROMA.formatToParts(new Date(ms)).find((p) => p.type === 'timeZoneName')?.value ?? '';
  return nome === 'GMT' ? '+00:00' : nome.replace('GMT', '');
}

function giornoValido(v: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  return m !== null && new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))).toISOString().slice(0, 10) === v;
}

function istanteValido(v: string): boolean {
  const m = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):[0-5]\d:[0-5]\d([+-]\d{2}:\d{2})$/.exec(v);
  if (m === null || !giornoValido(m[1])) return false;
  const ms = Date.parse(v);
  return !Number.isNaN(ms) && m[3] === offsetRoma(ms);
}

function uriValida(v: string): boolean {
  try {
    const url = new URL(v);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}

/**
 * `hostname` come lo promette il contratto: minuscolo, senza `www.`, etichette
 * separate da punti. E' piu' stretto della RFC di proposito: due host uguali
 * scritti in modo diverso sono due chiavi diverse per chi ci costruisce sopra.
 */
function hostnameValido(v: string): boolean {
  if (v !== v.toLowerCase() || v.startsWith('www.') || v.endsWith('.')) return false;
  return /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(v);
}

const FORMATI: ReadonlyMap<unknown, (v: string) => boolean> = new Map<unknown, (v: string) => boolean>([
  ['uri', uriValida], ['date-time', istanteValido], ['date', giornoValido], ['hostname', hostnameValido],
]);

function valida(v: unknown, schema: Schema, percorso: string, esito: Esito, chiave = '', parteDiAllOf = false): void {
  const s = schemaDaRef(schema);
  const errore = (testo: string): void => { esito.errori.push(`${percorso || '(radice)'}: ${testo}`); };

  for (const parte of (s.allOf as Schema[] | undefined) ?? []) valida(v, parte, percorso, esito, chiave, true);
  for (const parola of ['oneOf', 'anyOf'] as const) {
    const rami = s[parola] as Schema[] | undefined;
    if (rami === undefined) continue;
    const esiti = rami.map((ramo): Esito => {
      const e: Esito = { errori: [], stringhe: [] };
      valida(v, ramo, percorso, e, chiave);
      return e;
    });
    const validi = esiti.filter((e) => e.errori.length === 0);
    if (validi.length === 0 || (parola === 'oneOf' && validi.length > 1)) {
      errore(`${parola}: ${validi.length} rami validi su ${rami.length} [${esiti.map((e) => e.errori[0] ?? 'ok').join(' | ')}]`);
    } else {
      esito.stringhe.push(...validi[0].stringhe);
    }
  }
  if (s.type !== undefined) {
    const tipi = Array.isArray(s.type) ? (s.type as string[]) : [s.type as string];
    const tipo = tipoDi(v);
    if (!tipi.includes(tipo) && !(tipo === 'integer' && tipi.includes('number'))) {
      errore(`tipo ${tipo}, atteso ${tipi.join('|')}`);
      return;
    }
  }
  if ('const' in s && v !== s.const) errore(`atteso ${JSON.stringify(s.const)}, trovato ${JSON.stringify(v)}`);
  if (Array.isArray(s.enum) && !s.enum.includes(v)) errore(`fuori enum: ${JSON.stringify(v)}`);
  if (typeof v === 'string') {
    if (typeof s.minLength === 'number' && [...v].length < s.minLength) errore('stringa sotto minLength');
    if (typeof s.maxLength === 'number' && [...v].length > s.maxLength) errore('stringa oltre maxLength');
    if (typeof s.pattern === 'string' && !new RegExp(s.pattern, 'u').test(v)) errore(`non rispetta ${s.pattern}: ${v}`);
    if (s.format !== undefined && !(FORMATI.get(s.format)?.(v) ?? false)) errore(`format ${String(s.format)} non valido: ${v}`);
    esito.stringhe.push({
      percorso, chiave, valore: v,
      esente: s.format === 'uri' || s.format === 'hostname' || 'const' in s,
    });
  }
  if (typeof v === 'number') {
    if (typeof s.minimum === 'number' && v < s.minimum) errore(`${v} sotto minimum ${s.minimum}`);
    if (typeof s.maximum === 'number' && v > s.maximum) errore(`${v} oltre maximum ${s.maximum}`);
  }
  if (Array.isArray(v) && s.items !== undefined) {
    v.forEach((elemento, i) => valida(elemento, s.items as Schema, `${percorso}[${i}]`, esito, chiave));
  }
  if (tipoDi(v) === 'object') {
    const o = v as Oggetto;
    for (const nome of (s.required as string[] | undefined) ?? []) if (!Object.hasOwn(o, nome)) errore(`manca ${nome}`);
    for (const [nome, sotto] of Object.entries((s.properties as Record<string, Schema> | undefined) ?? {})) {
      if (Object.hasOwn(o, nome)) valida(o[nome], sotto, `${percorso}.${nome}`, esito, nome);
    }
    // Le parti di un allOf dichiarano solo una fetta: il controllo spetta allo schema che le unisce.
    const nomi = parteDiAllOf ? null : dichiarate(s);
    if (nomi !== null) for (const nome of Object.keys(o)) if (!nomi.has(nome)) errore(`proprietà non dichiarata: ${nome}`);
  }
}

const CHIAVI_ESENTI: ReadonlySet<string> = new Set(['link', 'instance', 'type', 'url']);
/** URL o host "www." nel testo; le email (info@www.x.it) restano menzioni, come da contratto. */
const URL_NEL_TESTO = /(?:https?:\/\/|(?<!@)www\.)[^\s"'<>]+/giu;

/** Stringhe di testo libero che citano un host diverso da edunews24.it. */
function urlEsterni(stringhe: readonly StringaVista[]): string[] {
  const perPercorso = new Map<string, StringaVista>();
  for (const s of stringhe) {
    const vista = perPercorso.get(s.percorso);
    perPercorso.set(s.percorso, vista ? { ...vista, esente: vista.esente || s.esente } : s);
  }
  const problemi: string[] = [];
  for (const s of perPercorso.values()) {
    if (s.esente || CHIAVI_ESENTI.has(s.chiave)) continue;
    for (const m of s.valore.matchAll(URL_NEL_TESTO)) {
      let host: string;
      try {
        host = new URL(/^www\./i.test(m[0]) ? `https://${m[0]}` : m[0]).hostname;
      } catch {
        host = '(non analizzabile)';
      }
      if (host !== 'edunews24.it') problemi.push(`${s.percorso}: ${m[0]}`);
    }
  }
  return problemi;
}

function esitoDi(valore: unknown, schema: Schema): Esito {
  const esito: Esito = { errori: [], stringhe: [] };
  valida(valore, schema, '', esito);
  return esito;
}

function verifica(valore: unknown, schema: Schema, etichetta: string): void {
  const esito = esitoDi(valore, schema);
  assert.deepEqual(esito.errori, [], `${etichetta}: difforme dallo schema`);
  assert.deepEqual(urlEsterni(esito.stringhe), [], `${etichetta}: URL esterni nel testo`);
}

const rif = (nome: string): Schema => ({ $ref: `#/components/schemas/${nome}` });

// ---------------------------------------------------------------------------
// Schemi delle risposte dichiarate in OpenAPI
// ---------------------------------------------------------------------------

function contenutoRisposta(risposta: Oggetto, tipoMedia: string, etichetta: string): Schema {
  let r = risposta;
  if (typeof r.$ref === 'string') {
    r = (COMPONENTI.responses as Record<string, Oggetto>)[r.$ref.replace('#/components/responses/', '')];
    assert.ok(r, `${etichetta}: risposta non risolvibile`);
  }
  const media = (r.content as Record<string, Oggetto> | undefined)?.[tipoMedia];
  assert.ok(media, `${etichetta}: tipo ${tipoMedia} non dichiarato`);
  return media.schema as Schema;
}

/** Schema del corpo per GET `percorso` (path OpenAPI) con quello status e quel Content-Type. */
function schemaRisposta(percorso: string, status: number, tipoMedia: string): Schema {
  const operazione = (DOC.paths as Record<string, Oggetto>)[percorso]?.get as Oggetto | undefined;
  assert.ok(operazione, `path assente: ${percorso}`);
  const risposta = (operazione.responses as Record<string, Oggetto>)[String(status)];
  assert.ok(risposta, `${percorso}: status ${status} non dichiarato`);
  return contenutoRisposta(risposta, tipoMedia, `${percorso} ${status}`);
}

/** Schema di una risposta riusabile (per i casi senza operazione: 404 di path ignoti, 405). */
function schemaComponente(nome: string, tipoMedia: string): Schema {
  return contenutoRisposta({ $ref: `#/components/responses/${nome}` }, tipoMedia, nome);
}

function tipoMediaDi(r: Response): string {
  return (r.headers.get('Content-Type') ?? '').split(';')[0].trim();
}

// ---------------------------------------------------------------------------
// Fixture e ambiente del gestore (come gestore.test.ts)
// ---------------------------------------------------------------------------

const { riferimento: CATEGORIE_RIF } = costruisciRiferimentoCategorie(RIGHE_CATEGORIE, RIGHE_SECONDARIE);
const PROFILI_RIF = costruisciRiferimentoProfili(RIGHE_PROFILI);
const CONTESTO_ARTICOLI = { categorie: CATEGORIE_RIF, profili: PROFILI_RIF };

function articolo(id: number, publishedAt: string, extra: Partial<RigaArticolo> = {}): RigaArticolo {
  return {
    id, slug: `articolo-${id}`, title: `**Titolo** ${id}`, title_summary: `Titolo _breve_ ${id}`,
    excerpt: `Estratto con [un link](https://www.miur.gov.it/x) ${id}`,
    summary: '### Paragrafo 1\n\nGli **uffici scolastici** avviano le convocazioni. Vedi https://www.miur.gov.it/pagina.',
    category_slug: 'scuola', secondary_category_slugs: ['insegnanti', 'ata'],
    image_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/a.webp', thumbnail_url: '', video_url: '',
    video_duration: null, published_at: publishedAt, tags: ['supplenze', 'GPS'], creator: 'Nome Reale Riservato', ...extra,
  };
}

const ARTICOLI: RigaArticolo[] = [
  articolo(3, '2026-09-21T07:18:28.177', {
    video_url: 'https://cdn.example.com/v/clip.mp4', video_duration: 72, creator: 'u-giornalista',
  }),
  articolo(2, '2026-01-10T08:00:00+00:00', { creator: 'u-url', summary: null, excerpt: null, title_summary: null }),
  articolo(1, '2026-09-20T08:53:20.936282'),
];

const INTERPELLO: RigaInterpello = { ...INTERPELLO_COMPLETO, ...COLONNE_VIETATE_INTERPELLO };
const SELEZIONE: RigaSelezione = { ...SELEZIONE_COMPLETA, ...COLONNE_VIETATE_SELEZIONE };
const BANDO: RigaBando = { ...BANDO_COMPLETO, ...COLONNE_VIETATE_BANDO };

class FonteFinta implements FonteDati {
  righe = new Map<NomeSelect, unknown[]>();
  errore: Error | null = null;

  async leggi<S extends NomeSelect>(piano: PianoQuery<S>, _segnale: AbortSignal): Promise<RighePerSelect[S][]> {
    if (this.errore) throw this.errore;
    const tutte = (this.righe.get(piano.select) ?? []) as RighePerSelect[S][];
    const limite = piano.operazioni.find((o) => o.tipo === 'limite');
    return tutte.slice(0, limite && limite.tipo === 'limite' ? limite.n : undefined);
  }
}

interface Ambiente {
  fonte: FonteFinta;
  dipendenze: DipendenzeGestore;
}

function ambiente(capacita = 1000): Ambiente {
  const fonte = new FonteFinta();
  fonte.righe.set('articolo', ARTICOLI);
  fonte.righe.set('interpello', [INTERPELLO]);
  fonte.righe.set('selezione', [SELEZIONE]);
  fonte.righe.set('bando', [BANDO]);
  fonte.righe.set('bando-con-regione', [BANDO]);
  const orologio = (): number => Date.UTC(2026, 8, 21, 10, 0, 0);
  const risorse: DipendenzeRisorse = {
    fonte,
    categorie: { async ottieni() { return CATEGORIE_RIF; }, seCaldo() { return CATEGORIE_RIF; } },
    profili: { async ottieni() { return PROFILI_RIF; }, seCaldo() { return PROFILI_RIF; } },
    valoriRegioneCorpus: () => [],
    limiteDichiarato: { requests: capacita, window_seconds: capacita },
    registra: () => {},
  };
  const dipendenze: DipendenzeGestore = {
    risorse,
    limitatore: new Limitatore({ capacita, ricaricaPerSecondo: 1, maxChiavi: 1000, orologio }),
    semaforo: new Semaforo({ slot: 4, coda: 8, attesaMs: 500 }),
    cache: new CacheRisposte<RisultatoRisorsa>({ maxVoci: 100, maxByte: 10_000_000, orologio, misura: (r) => r.corpo.length }),
    modalitaFiducia: 'diretta',
    politicaRateLimit: `${capacita};w=${capacita}`,
    orologio,
    registra: () => {},
  };
  return { fonte, dipendenze };
}

async function chiama(
  amb: Ambiente,
  descrittore: DescrittoreRotta,
  percorsoEQuery: string,
  opzioni: { params?: Record<string, string | undefined>; metodo?: string } = {},
): Promise<Response> {
  const url = new URL(percorsoEQuery, 'https://edunews24.it');
  const gestore = creaGestore(descrittore, amb.dipendenze);
  const contesto = {
    request: new Request(url, { method: opzioni.metodo ?? 'GET' }),
    url,
    params: opzioni.params ?? {},
    clientAddress: '203.0.113.7',
  };
  return opzioni.metodo && opzioni.metodo !== 'GET' ? gestore.ALL(contesto) : gestore.GET(contesto);
}

/** Corpo JSON della risposta, validato contro lo schema OpenAPI indicato. */
async function corpoValidato(r: Response, status: number, schema: Schema, etichetta: string): Promise<unknown> {
  assert.equal(r.status, status, etichetta);
  const corpo: unknown = await r.json();
  verifica(corpo, schema, etichetta);
  return corpo;
}

// ---------------------------------------------------------------------------
// Il validatore stesso: deve accorgersi delle difformita'
// ---------------------------------------------------------------------------

test('validatore: riconosce le difformità', () => {
  const errori = (valore: unknown, schema: Schema): string[] => esitoDi(valore, schema).errori;
  const regione = { slug: 'lazio', name: 'Lazio' };
  assert.deepEqual(errori(regione, rif('Regione')), []);
  assert.notDeepEqual(errori({ ...regione, extra: 1 }, rif('Regione')), [], 'proprietà non dichiarata');
  assert.notDeepEqual(errori({ slug: 'lazio' }, rif('Regione')), [], 'required');
  assert.notDeepEqual(errori({ ...regione, slug: 'atlantide' }, rif('Regione')), [], 'enum');
  assert.notDeepEqual(errori({ ...regione, name: '' }, rif('Regione')), [], 'minLength');
  assert.notDeepEqual(errori({ name: 'Autore', url: 'x' }, rif('Autore')), [], 'proprietà non dichiarata');
  assert.notDeepEqual(errori({ code: 'x', description: 3 }, rif('CodiceAteco')), [], 'tipo');
  assert.deepEqual(errori(1.5, { type: 'number' }), []);
  assert.deepEqual(errori(2, { type: 'number' }), [], 'integer compreso in number');
  assert.notDeepEqual(errori(1.5, { type: 'integer' }), []);
  assert.notDeepEqual(errori(0, { type: 'integer', minimum: 1 }), []);
  assert.notDeepEqual(errori('#12345', { type: 'string', pattern: '^#[0-9A-Fa-f]{6}$' }), []);
  // oneOf: esattamente un ramo; null ammesso solo dove dichiarato.
  assert.deepEqual(errori(null, { oneOf: [rif('Video'), { type: 'null' }] }), []);
  assert.notDeepEqual(errori(null, rif('Video')), []);
  // Proprietà spezzate su allOf: la somma delle parti è dichiarata, il resto no.
  const base = { type: 'object', properties: { a: { type: 'string' } } };
  const unione = { allOf: [base, { type: 'object', properties: { b: { type: 'string' } } }] };
  assert.deepEqual(errori({ a: 'x', b: 'y' }, unione), []);
  assert.notDeepEqual(errori({ a: 'x', b: 'y', c: 'z' }, unione), []);
  // Formati.
  const istante = { type: 'string', format: 'date-time' };
  assert.deepEqual(errori('2026-09-21T09:18:28+02:00', istante), []);
  assert.deepEqual(errori('2026-01-10T09:00:00+01:00', istante), []);
  assert.deepEqual(errori('2026-10-25T02:30:00+01:00', istante), [], 'seconda 02:30 del cambio d\'ora');
  for (const cattivo of [
    '2026-09-21T07:18:28Z', '2026-09-21T09:18:28.177+02:00', '2026-01-10T10:00:00+02:00', '2026-09-21 09:18:28+02:00',
    '2026-02-30T10:00:00+01:00', '2026-09-21T24:00:00+02:00', '2026-09-21T09:18:28',
  ]) {
    assert.notDeepEqual(errori(cattivo, istante), [], cattivo);
  }
  const giorno = { type: 'string', format: 'date' };
  assert.deepEqual(errori('2028-02-29', giorno), []);
  for (const cattivo of ['2026-02-29', '2026-9-21', '21/09/2026', '2026-09-21T00:00:00+02:00']) {
    assert.notDeepEqual(errori(cattivo, giorno), [], cattivo);
  }
  const indirizzo = { type: 'string', format: 'uri' };
  assert.deepEqual(errori('https://edunews24.it/scuola', indirizzo), []);
  for (const cattivo of ['/scuola', 'edunews24.it', 'javascript:alert(1)', 'ftp://edunews24.it/x']) {
    assert.notDeepEqual(errori(cattivo, indirizzo), [], cattivo);
  }
  // URL esterni nel testo libero (non nei campi uri, non nelle email).
  const testo = { type: 'object', properties: { t: { type: 'string' }, u: indirizzo } };
  const esterni = (t: string): string[] => urlEsterni(esitoDi({ t, u: 'https://esterno.example/x' }, testo).stringhe);
  assert.deepEqual(esterni('Vedi https://edunews24.it/scuola e http://edunews24.it/x.'), []);
  assert.deepEqual(esterni('Scrivi a info@www.scuola.it'), []);
  assert.equal(esterni('Vedi https://www.miur.gov.it/x').length, 1);
  assert.equal(esterni('Vedi www.miur.gov.it').length, 1);
  assert.equal(esterni('Vedi www.edunews24.it').length, 1, 'www.edunews24.it non è edunews24.it');
  assert.equal(esterni('Vedi https://edunews24.it.esterno.example/x').length, 1);
});

// ---------------------------------------------------------------------------
// (b) Esempi del documento
// ---------------------------------------------------------------------------

test('ogni esempio di components.examples rispetta lo schema del media type che lo usa', () => {
  const perEsempio = new Map<string, Schema[]>();
  const visita = (nodo: unknown): void => {
    if (Array.isArray(nodo)) {
      nodo.forEach(visita);
      return;
    }
    if (nodo === null || typeof nodo !== 'object') return;
    const o = nodo as Oggetto;
    if (o.schema !== undefined && o.examples !== null && typeof o.examples === 'object') {
      for (const riferimento of Object.values(o.examples as Record<string, Oggetto>)) {
        const nome = String(riferimento.$ref).replace('#/components/examples/', '');
        perEsempio.set(nome, [...(perEsempio.get(nome) ?? []), o.schema as Schema]);
      }
    }
    Object.values(o).forEach(visita);
  };
  visita(DOC.paths);
  visita(COMPONENTI.responses);

  const esempi = COMPONENTI.examples as Record<string, Oggetto>;
  assert.ok(Object.keys(esempi).length >= 9);
  for (const [nome, esempio] of Object.entries(esempi)) {
    const schemi = perEsempio.get(nome) ?? [];
    assert.ok(schemi.length > 0, `esempio ${nome} non usato da nessun media type`);
    for (const schema of schemi) verifica(esempio.value, schema, `esempio ${nome}`);
  }
  // Anche l'esempio dello schema Video.
  for (const esempio of (SCHEMI.Video.examples as unknown[])) verifica(esempio, rif('Video'), 'esempio Video');
});

test('gli esempi d\'errore coincidono con le risposte reali (corpo e header)', async () => {
  const amb = ambiente();
  const r400 = await chiama(amb, ELENCO_ARTICOLI, `/api/v1${RICHIESTA_ERRORE_PARAMETRI}`);
  assert.deepEqual(await r400.json(), esempioErroreParametri());

  // Capacità e ricarica predefinite (60, 1/s): il 429 alla prima richiesta oltre il limite.
  const limitato = ambiente(60);
  for (let i = 0; i < 60; i++) assert.equal((await chiama(limitato, ELENCO_BANDI, '/api/v1/bandi')).status, 200);
  const r429 = await chiama(limitato, ELENCO_BANDI, '/api/v1/bandi');
  assert.deepEqual(await r429.json(), esempioErroreLimite());
  const intestazioni = COMPONENTI.headers as Record<string, Oggetto>;
  for (const nome of ['Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset', 'RateLimit-Policy']) {
    assert.equal(r429.headers.get(nome), String(intestazioni[nome].example), nome);
  }
});

// ---------------------------------------------------------------------------
// (c) Output dei mapper
// ---------------------------------------------------------------------------

test('mapper: interpello, selezione, bando, articolo e categorie rispettano gli schemi', () => {
  const interpello = mappaInterpello(INTERPELLO);
  assert.ok(interpello);
  verifica(interpello, rif('Interpello'), 'mappaInterpello');
  verifica(interpello, rif('Opportunita'), 'mappaInterpello come Opportunita');

  for (const [descrizione, extra] of [
    ['fixture completa', {}],
    ['scadenza «ore 24:00»', { data_scadenza: '2026-10-06T22:00:00+00:00' }],
    ['scadenza implausibile', { data_scadenza: '2099-12-31T21:59:00+00:00' }],
    ['senza scadenza né aggiornamento', { data_scadenza: null, updated_at: null, sedi: ['Nazionale'] }],
  ] as const) {
    const selezione = mappaSelezione({ ...SELEZIONE, ...extra }, OGGI);
    assert.ok(selezione, descrizione);
    verifica(selezione, rif('SelezionePersonale'), `mappaSelezione, ${descrizione}`);
    verifica(selezione, rif('Opportunita'), `mappaSelezione come Opportunita, ${descrizione}`);
  }

  for (const [descrizione, extra] of [
    ['fixture completa', {}],
    ['scadenza implausibile', { data_scadenza: '2099-12-31' }],
    ['campi vuoti', {
      data_scadenza: null, data_apertura: null, data_pubblicazione: null, importo_totale_eur: null, tipologia: null,
      programma: null, modalita: null, bando_regioni: [], bando_settori: null, bando_codici_ateco: [], stato_bando: null,
    }],
  ] as const) {
    const bando = mappaBando({ ...BANDO, ...extra }, OGGI);
    assert.ok(bando, descrizione);
    verifica(bando, rif('Bando'), `mappaBando, ${descrizione}`);
    verifica(bando, rif('Opportunita'), `mappaBando come Opportunita, ${descrizione}`);
  }

  for (const riga of ARTICOLI) {
    const dto = mappaArticolo(riga, CONTESTO_ARTICOLI);
    assert.ok(dto, `articolo ${String(riga.id)}`);
    verifica(dto, rif('Articolo'), `mappaArticolo ${String(riga.id)}`);
  }

  const categorie = mappaCategorie(CATEGORIE_RIF);
  assert.ok(categorie.length > 0);
  for (const categoria of categorie) verifica(categoria, rif('Categoria'), `mappaCategorie ${categoria.slug}`);
});

// ---------------------------------------------------------------------------
// (c) Corpi prodotti dal gestore
// ---------------------------------------------------------------------------

test('gestore: elenchi, dettagli, categorie e indice rispettano gli schemi di risposta del 200', async () => {
  const amb = ambiente();
  const elenchi: readonly (readonly [DescrittoreRotta, string, string])[] = [
    [ELENCO_ARTICOLI, '/articles', '?category=scuola&limit=2&since=2026-01-01'],
    [ELENCO_INTERPELLI, '/interpelli', '?region=emilia-romagna'],
    [ELENCO_SELEZIONE, '/selezione-personale', '?national=false&updated_since=2026-09-20T00:00:00Z'],
    [ELENCO_BANDI, '/bandi', '?region=lazio&until=2026-12-31'],
  ];
  for (const [descrittore, percorso, query] of elenchi) {
    const r = await chiama(amb, descrittore, `/api/v1${percorso}${query}`);
    const corpo = await corpoValidato(r, 200, schemaRisposta(percorso, 200, tipoMediaDi(r)), `GET ${percorso}${query}`) as Oggetto;
    assert.ok((corpo.data as unknown[]).length > 0, percorso);
  }

  const dettagli: readonly (readonly [DescrittoreRotta, string, number])[] = [
    [DETTAGLIO_ARTICOLO, '/articles', 3],
    [DETTAGLIO_INTERPELLO, '/interpelli', INTERPELLO_COMPLETO.id as number],
    [DETTAGLIO_SELEZIONE, '/selezione-personale', SELEZIONE_COMPLETA.id as number],
    [DETTAGLIO_BANDO, '/bandi', BANDO_COMPLETO.id as number],
  ];
  for (const [descrittore, percorso, id] of dettagli) {
    amb.fonte.righe.set('articolo', ARTICOLI.filter((a) => a.id === id));
    const r = await chiama(amb, descrittore, `/api/v1${percorso}/${id}`, { params: { id: String(id) } });
    await corpoValidato(r, 200, schemaRisposta(`${percorso}/{id}`, 200, tipoMediaDi(r)), `GET ${percorso}/${id}`);
  }

  const categorie = await chiama(amb, CATEGORIE, '/api/v1/categories');
  await corpoValidato(categorie, 200, schemaRisposta('/categories', 200, tipoMediaDi(categorie)), 'GET /categories');
  const indice = await chiama(amb, INDICE, '/api/v1?ignorato=1');
  await corpoValidato(indice, 200, schemaRisposta('/', 200, tipoMediaDi(indice)), 'GET /');
});

test('gestore: i feed JSON rispettano lo schema JsonFeed', async () => {
  const amb = ambiente();
  for (const percorso of [
    'articles.json', 'articles/scuola.json', 'interpelli.json', 'selezione-personale.json', 'bandi.json',
  ]) {
    const r = await chiama(amb, FEED, `/api/v1/feeds/${percorso}`, { params: { percorso } });
    const chiave = percorso.startsWith('articles/') ? '/feeds/articles/{category}.json' : `/feeds/${percorso}`;
    const corpo = await corpoValidato(r, 200, schemaRisposta(chiave, 200, tipoMediaDi(r)), `feed ${percorso}`) as Oggetto;
    assert.ok((corpo.items as unknown[]).length > 0, percorso);
  }
});

test('gestore: problem+json di 400, 404, 405, 429 e 503 rispettano gli schemi dichiarati', async () => {
  const amb = ambiente();
  const casi400: readonly (readonly [DescrittoreRotta, string, string, Record<string, string>])[] = [
    [ELENCO_ARTICOLI, '/articles', `/api/v1${RICHIESTA_ERRORE_PARAMETRI}`, {}],
    [ELENCO_ARTICOLI, '/articles', '/api/v1/articles?category=sport', {}],
    [ELENCO_ARTICOLI, '/articles', '/api/v1/articles?constructor=1&limit=x', {}],
    [ELENCO_ARTICOLI, '/articles', '/api/v1/articles?category=scuola&cursor=eyJ2IjoxfQ', {}],
    [ELENCO_BANDI, '/bandi', '/api/v1/bandi?region=atlantide&since=ieri', {}],
    [DETTAGLIO_ARTICOLO, '/articles/{id}', '/api/v1/articles/5?x=1', { id: '5' }],
    [DETTAGLIO_BANDO, '/bandi/{id}', '/api/v1/bandi/abc', { id: 'abc' }],
    [CATEGORIE, '/categories', `/api/v1/categories?${'p=1&'.repeat(600)}`, {}],
  ];
  for (const [descrittore, percorso, url, params] of casi400) {
    const r = await chiama(amb, descrittore, url, { params });
    await corpoValidato(r, 400, schemaRisposta(percorso, 400, tipoMediaDi(r)), `400 ${url.slice(0, 80)}`);
  }

  amb.fonte.righe.set('bando', []);
  const assente = await chiama(amb, DETTAGLIO_BANDO, '/api/v1/bandi/7', { params: { id: '7' } });
  await corpoValidato(assente, 404, schemaRisposta('/bandi/{id}', 404, tipoMediaDi(assente)), '404 dettaglio');
  const feed = await chiama(amb, FEED, '/api/v1/feeds/articles/sport.json', { params: { percorso: 'articles/sport.json' } });
  await corpoValidato(feed, 404, schemaRisposta('/feeds/articles/{category}.json', 404, tipoMediaDi(feed)), '404 feed');
  // Path ignoto e metodo non ammesso non hanno un'operazione GET: si usano le risposte riusabili.
  const ignoto = await chiama(amb, NON_TROVATO, '/api/v1/constructor');
  await corpoValidato(ignoto, 404, schemaComponente('NonTrovato', tipoMediaDi(ignoto)), '404 path ignoto');
  const post = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { metodo: 'POST' });
  await corpoValidato(post, 405, schemaComponente('MetodoNonConsentito', tipoMediaDi(post)), '405');

  const limitato = ambiente(1);
  await chiama(limitato, ELENCO_BANDI, '/api/v1/bandi');
  const troppe = await chiama(limitato, ELENCO_BANDI, '/api/v1/bandi');
  await corpoValidato(troppe, 429, schemaRisposta('/bandi', 429, tipoMediaDi(troppe)), '429');

  const guasto = ambiente();
  guasto.fonte.errore = new ErroreDati('disponibilita', '57014');
  const r503 = await chiama(guasto, ELENCO_INTERPELLI, '/api/v1/interpelli');
  await corpoValidato(r503, 503, schemaRisposta('/interpelli', 503, tipoMediaDi(r503)), '503');
});

// ---------------------------------------------------------------------------
// (e) Enum dello schema allineati alle costanti del codice
// ---------------------------------------------------------------------------

test('enum dello schema = costanti del codice', () => {
  const proprieta = (nome: string): Record<string, Oggetto> => SCHEMI[nome].properties as Record<string, Oggetto>;
  assert.deepEqual(proprieta('Regione').slug.enum, SLUG_REGIONI);
  assert.deepEqual(proprieta('Sezione').slug.enum, SEZIONI);
  assert.deepEqual(proprieta('OpportunitaBase').type.enum, ['interpello', 'selezione-personale', 'bando']);
  const discriminatore = SCHEMI.Opportunita.discriminator as Oggetto;
  assert.equal(discriminatore.propertyName, 'type');
  assert.deepEqual(Object.keys(discriminatore.mapping as Oggetto), ['interpello', 'selezione-personale', 'bando']);
  assert.deepEqual(proprieta('Problema').code.enum, CODICI_ERRORE);
});
