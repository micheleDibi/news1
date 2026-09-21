/**
 * Errori dell'API /api/v1.
 *
 * - ProblemaApi: errore del client (4xx) o condizione nota (429, 503), serializzato
 *   come application/problem+json (RFC 9457) da http.ts.
 * - ErroreDati: errore dello strato dati, classificato per decidere fra 503 (o copia
 *   stantia), 404, 400 sul cursore e 500. Il messaggio di PostgREST non esce mai.
 *
 * Niente parameter properties nei costruttori: --experimental-strip-types non le supporta.
 */

export type CodiceErrore =
  | 'invalid-parameter'
  | 'unknown-parameter'
  | 'invalid-cursor'
  | 'not-found'
  | 'method-not-allowed'
  | 'rate-limited'
  | 'internal-error'
  | 'service-unavailable';

export const CODICI_ERRORE: readonly CodiceErrore[] = [
  'invalid-parameter',
  'unknown-parameter',
  'invalid-cursor',
  'not-found',
  'method-not-allowed',
  'rate-limited',
  'internal-error',
  'service-unavailable',
];

/** Titolo umano (italiano) e status HTTP di ciascun codice. */
export const DEFINIZIONE_ERRORE: ReadonlyMap<CodiceErrore, { status: number; titolo: string }> = new Map([
  ['invalid-parameter', { status: 400, titolo: 'Parametro non valido' }],
  ['unknown-parameter', { status: 400, titolo: 'Parametro sconosciuto' }],
  ['invalid-cursor', { status: 400, titolo: 'Cursore non valido' }],
  ['not-found', { status: 404, titolo: 'Risorsa non trovata' }],
  ['method-not-allowed', { status: 405, titolo: 'Metodo non consentito' }],
  ['rate-limited', { status: 429, titolo: 'Troppe richieste' }],
  ['internal-error', { status: 500, titolo: 'Errore interno' }],
  ['service-unavailable', { status: 503, titolo: 'Servizio non disponibile' }],
]);

export interface ErroreParametro {
  parameter: string;
  detail: string;
  allowed?: readonly string[];
}

export interface OpzioniProblema {
  errori?: readonly ErroreParametro[];
  /** Solo per invalid-cursor: link alla prima pagina senza cursore. */
  primo?: string | null;
  /** Secondi, per 429 e 503. */
  retryAfter?: number | null;
}

export class ProblemaApi extends Error {
  readonly codice: CodiceErrore;
  readonly status: number;
  readonly titolo: string;
  /** Testo per il client: mai valori ricevuti, mai messaggi interni. */
  readonly dettaglio: string;
  readonly errori: readonly ErroreParametro[];
  readonly primo: string | null;
  readonly retryAfter: number | null;

  constructor(codice: CodiceErrore, dettaglio: string, opzioni: OpzioniProblema = {}) {
    super(`${codice}: ${dettaglio}`);
    this.name = 'ProblemaApi';
    const definizione = DEFINIZIONE_ERRORE.get(codice);
    this.codice = codice;
    this.status = definizione?.status ?? 500;
    this.titolo = definizione?.titolo ?? 'Errore';
    this.dettaglio = dettaglio;
    this.errori = opzioni.errori ?? [];
    this.primo = opzioni.primo ?? null;
    this.retryAfter = opzioni.retryAfter ?? null;
  }
}

/**
 * Classe di un errore dello strato dati:
 * - disponibilita: rete, timeout, abort, 5xx, 57014, gateway -> 503 o copia stantia;
 * - permesso: 42501 (grant revocato) -> dipende dal chiamante;
 * - non-trovato: PGRST116 -> 404;
 * - data-non-valida: 22007/22008/22009 (con un cursore -> 400 invalid-cursor);
 * - programmazione: ogni altro 4xx, PGRST1xx, 42703, forma inattesa -> 500.
 */
export type ClasseErrore = 'disponibilita' | 'permesso' | 'non-trovato' | 'data-non-valida' | 'programmazione';

export class ErroreDati extends Error {
  readonly classe: ClasseErrore;
  /** Codice PostgREST/Postgres, se noto (solo per i log). */
  readonly codiceDb: string | null;

  constructor(classe: ClasseErrore, codiceDb: string | null = null, messaggio = 'errore dello strato dati') {
    super(messaggio);
    this.name = 'ErroreDati';
    this.classe = classe;
    this.codiceDb = codiceDb;
  }
}

/**
 * Classifica un errore di postgrest-js ({status, code}). In postgrest-js 1.17.7 un
 * errore di rete o un abort arriva con status 0 e code vuoto, '20' o '23'.
 */
export function classificaErrore(errore: { status?: number | null; code?: string | null }): ClasseErrore {
  const status = typeof errore.status === 'number' ? errore.status : 0;
  const codice = typeof errore.code === 'string' ? errore.code : '';
  if (codice === '42501') return 'permesso';
  if (codice === 'PGRST116') return 'non-trovato';
  if (codice === '22007' || codice === '22008' || codice === '22009') return 'data-non-valida';
  if (codice === '57014') return 'disponibilita';
  if (status === 0 || status >= 500 || status === 401 || status === 408 || status === 429) return 'disponibilita';
  return 'programmazione';
}
