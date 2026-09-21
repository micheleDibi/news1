/**
 * Parametri degli elenchi /api/v1: specifica, validazione rigorosa (400 con tutti
 * gli errori, mai valori grezzi verso PostgREST) e forma canonica.
 *
 * Le stringhe del client non diventano mai chiavi di oggetti letterali: solo Map,
 * Set e array (`?constructor=1` o `?__proto__=1` sono parametri sconosciuti come gli altri).
 */
import { SLUG_VALIDO } from '../slug';
import { REGIONI, regionePerSlug } from '../regioni';
import {
  LIMITE_MASSIMO, LIMITE_PREDEFINITO, LUNGHEZZA_MASSIMA_CURSORE, LUNGHEZZA_MASSIMA_QUERY, LUNGHEZZA_MASSIMA_VALORE,
} from './costanti';
import { ProblemaApi, type ErroreParametro } from './errori';
import { leggiParametroIstante, rfc3339Roma } from './tempo';
import type { Risorsa } from './contratto';

export type NomeParametro =
  | 'category'
  | 'has_video'
  | 'region'
  | 'national'
  | 'since'
  | 'until'
  | 'updated_since'
  | 'limit'
  | 'cursor';

/** Ordine canonico: link self/next, chiave di cache, hash del cursore, OpenAPI, meta.filters. */
export const ORDINE_PARAMETRI: readonly NomeParametro[] = [
  'category', 'has_video', 'region', 'national', 'since', 'until', 'updated_since', 'limit', 'cursor',
];

export const SPEC_PARAMETRI: ReadonlyMap<Risorsa, readonly NomeParametro[]> = new Map<Risorsa, readonly NomeParametro[]>([
  ['articles', ['category', 'has_video', 'since', 'until', 'limit', 'cursor']],
  ['interpelli', ['region', 'since', 'until', 'limit', 'cursor']],
  ['selezione-personale', ['region', 'national', 'since', 'until', 'updated_since', 'limit', 'cursor']],
  ['bandi', ['region', 'national', 'since', 'until', 'updated_since', 'limit', 'cursor']],
]);

/** Colonna su cui agiscono since/until per ciascuna risorsa (documentazione). */
export const COLONNA_DATA: ReadonlyMap<Risorsa, string> = new Map<Risorsa, string>([
  ['articles', 'published_at'],
  ['interpelli', 'published_at (data della fonte)'],
  ['selezione-personale', 'published_at (data di pubblicazione su inPA)'],
  ['bandi', 'published_at (inserimento in EduNews24)'],
]);

export const SLUG_REGIONI: readonly string[] = REGIONI.map((r) => r.slug);

export interface FiltriElenco {
  category: string | null;
  has_video: boolean | null;
  region: string | null;
  national: boolean | null;
  /** Istanti in ms, gia' troncati al secondo. */
  since: number | null;
  until: number | null;
  updated_since: number | null;
  limit: number;
  /** Cursore opaco non ancora decodificato (lo decodifica cursore.ts). */
  cursor: string | null;
}

export type EsitoValidazione = { ok: true; filtri: FiltriElenco } | { ok: false; problema: ProblemaApi };

const LIMITE = /^[1-9]\d{0,2}$/;
const BASE64URL = /^[A-Za-z0-9_-]+$/;

function booleano(valore: string): boolean | null {
  if (valore === 'true') return true;
  if (valore === 'false') return false;
  return null;
}

function problemaParametri(errori: ErroreParametro[], sconosciuti: boolean): ProblemaApi {
  const n = errori.length;
  const dettaglio = n === 1
    ? 'La richiesta contiene un parametro non valido.'
    : `La richiesta contiene ${n} parametri non validi.`;
  return new ProblemaApi(sconosciuti ? 'unknown-parameter' : 'invalid-parameter', dettaglio, { errori });
}

/**
 * Valida la query di un elenco. `lunghezzaQuery` e' la lunghezza della query grezza
 * (senza '?'). La categoria qui si controlla solo nella forma: l'appartenenza al
 * riferimento delle categorie la verifica il chiamante (erroreCategoria).
 */
export function validaQueryElenco(risorsa: Risorsa, query: URLSearchParams, lunghezzaQuery: number): EsitoValidazione {
  const ammessi = new Set<string>(SPEC_PARAMETRI.get(risorsa) ?? []);
  const errori: ErroreParametro[] = [];
  let sconosciuti = false;

  if (lunghezzaQuery > LUNGHEZZA_MASSIMA_QUERY) {
    return { ok: false, problema: problemaParametri([{ parameter: '(query)', detail: `La query supera ${LUNGHEZZA_MASSIMA_QUERY} caratteri.` }], false) };
  }

  const filtri: FiltriElenco = {
    category: null, has_video: null, region: null, national: null,
    since: null, until: null, updated_since: null, limit: LIMITE_PREDEFINITO, cursor: null,
  };

  for (const nome of new Set(query.keys())) {
    if (!ammessi.has(nome)) {
      sconosciuti = true;
      errori.push({ parameter: nome.slice(0, 64), detail: 'Parametro non previsto per questa risorsa.', allowed: [...ammessi] });
      continue;
    }
    const valori = query.getAll(nome);
    if (valori.length > 1) {
      errori.push({ parameter: nome, detail: 'Il parametro compare piu\' di una volta.' });
      continue;
    }
    const valore = valori[0];
    if (valore === '') {
      errori.push({ parameter: nome, detail: 'Il parametro e\' vuoto.' });
      continue;
    }
    const massimo = nome === 'cursor' ? LUNGHEZZA_MASSIMA_CURSORE : LUNGHEZZA_MASSIMA_VALORE;
    if (valore.length > massimo) {
      errori.push({ parameter: nome, detail: `Il valore supera ${massimo} caratteri.` });
      continue;
    }

    switch (nome as NomeParametro) {
      case 'category':
        if (valore.length > 64 || !SLUG_VALIDO.test(valore)) {
          errori.push({ parameter: nome, detail: 'Deve essere lo slug di una categoria (vedi /api/v1/categories).' });
        } else filtri.category = valore;
        break;
      case 'has_video':
      case 'national': {
        const b = booleano(valore);
        if (b === null) errori.push({ parameter: nome, detail: 'Deve essere "true" o "false".' });
        else if (nome === 'has_video') filtri.has_video = b;
        else filtri.national = b;
        break;
      }
      case 'region':
        if (!regionePerSlug(valore)) {
          errori.push({ parameter: nome, detail: 'Regione sconosciuta.', allowed: SLUG_REGIONI });
        } else filtri.region = valore;
        break;
      case 'since':
      case 'updated_since':
      case 'until': {
        const ms = leggiParametroIstante(valore, nome === 'until' ? 'fine' : 'inizio');
        if (ms === null) {
          errori.push({ parameter: nome, detail: 'Deve essere una data YYYY-MM-DD o un istante RFC 3339 con fuso (es. 2026-09-21T09:00:00+02:00), anni 2000-2100.' });
        } else if (nome === 'since') filtri.since = ms;
        else if (nome === 'until') filtri.until = ms;
        else filtri.updated_since = ms;
        break;
      }
      case 'limit':
        if (!LIMITE.test(valore) || Number(valore) > LIMITE_MASSIMO) {
          errori.push({ parameter: nome, detail: `Deve essere un intero tra 1 e ${LIMITE_MASSIMO}.` });
        } else filtri.limit = Number(valore);
        break;
      case 'cursor':
        if (!BASE64URL.test(valore)) {
          errori.push({ parameter: nome, detail: 'Cursore non valido: usare il valore ricevuto in links.next.' });
        } else filtri.cursor = valore;
        break;
    }
  }

  if (filtri.since !== null && filtri.until !== null && filtri.since >= filtri.until) {
    errori.push({ parameter: 'until', detail: 'Deve essere successivo a since.' });
  }

  if (errori.length > 0) return { ok: false, problema: problemaParametri(errori, sconosciuti) };
  return { ok: true, filtri };
}

/** Dettagli e categorie: nessun parametro ammesso (indice, openapi e feed ignorano la query). */
export function validaQueryAssente(query: URLSearchParams, lunghezzaQuery: number): ProblemaApi | null {
  if (lunghezzaQuery > LUNGHEZZA_MASSIMA_QUERY) {
    return problemaParametri([{ parameter: '(query)', detail: `La query supera ${LUNGHEZZA_MASSIMA_QUERY} caratteri.` }], false);
  }
  const nomi = [...new Set(query.keys())];
  if (nomi.length === 0) return null;
  return problemaParametri(
    nomi.map((nome) => ({ parameter: nome.slice(0, 64), detail: 'Questa risorsa non accetta parametri.' })),
    true,
  );
}

/** Categoria sintatticamente valida ma assente dal riferimento. */
export function erroreCategoria(ammesse: readonly string[]): ProblemaApi {
  return problemaParametri([{ parameter: 'category', detail: 'Categoria sconosciuta.', allowed: ammesse }], false);
}

/** Id numerico di un path di dettaglio; null se malformato. */
export function validaIdPercorso(valore: string | undefined): number | null {
  if (valore === undefined || !/^[1-9]\d{0,15}$/.test(valore)) return null;
  const id = Number(valore);
  return Number.isSafeInteger(id) ? id : null;
}

function valoreCanonico(nome: NomeParametro, filtri: FiltriElenco): string | null {
  switch (nome) {
    case 'category': return filtri.category;
    case 'has_video': return filtri.has_video === null ? null : String(filtri.has_video);
    case 'region': return filtri.region;
    case 'national': return filtri.national === null ? null : String(filtri.national);
    case 'since': return filtri.since === null ? null : rfc3339Roma(filtri.since);
    case 'until': return filtri.until === null ? null : rfc3339Roma(filtri.until);
    case 'updated_since': return filtri.updated_since === null ? null : rfc3339Roma(filtri.updated_since);
    case 'limit': return filtri.limit === LIMITE_PREDEFINITO ? null : String(filtri.limit);
    case 'cursor': return filtri.cursor;
  }
}

/** Query canonica: ordine fisso, valori predefiniti omessi, istanti nella forma rfc3339Roma. */
export function queryCanonica(
  risorsa: Risorsa,
  filtri: FiltriElenco,
  opzioni: { conLimite: boolean; conCursore: boolean },
): URLSearchParams {
  const ammessi = new Set(SPEC_PARAMETRI.get(risorsa) ?? []);
  const q = new URLSearchParams();
  for (const nome of ORDINE_PARAMETRI) {
    if (!ammessi.has(nome)) continue;
    if (nome === 'limit' && !opzioni.conLimite) continue;
    if (nome === 'cursor' && !opzioni.conCursore) continue;
    const valore = valoreCanonico(nome, filtri);
    if (valore !== null) q.append(nome, valore);
  }
  return q;
}

/** meta.filters: tutti i filtri della risorsa (senza limit e cursor), in ordine canonico, null se assenti. */
export function filtriMeta(risorsa: Risorsa, filtri: FiltriElenco): Array<[string, string | boolean | null]> {
  const voci: Array<[string, string | boolean | null]> = [];
  for (const nome of SPEC_PARAMETRI.get(risorsa) ?? []) {
    if (nome === 'limit' || nome === 'cursor') continue;
    if (nome === 'has_video') voci.push([nome, filtri.has_video]);
    else if (nome === 'national') voci.push([nome, filtri.national]);
    else voci.push([nome, valoreCanonico(nome, filtri)]);
  }
  return voci;
}
