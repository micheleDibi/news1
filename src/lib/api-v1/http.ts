/**
 * Risposte HTTP dell'API /api/v1: header comuni, profili di Cache-Control,
 * ETag/304, problem+json (RFC 9457) e preflight CORS. Puro: costruisce Response.
 */
import { createHash } from 'node:crypto';
import { RATE_LIMIT_POLICY, SITO, URL_DOCUMENTAZIONE, URL_OPENAPI, URL_TERMINI } from './costanti';
import type { ProblemaApi } from './errori';

export type ProfiloCache =
  | 'elenco'
  | 'dettaglio'
  | 'feed'
  | 'statico'
  | 'openapi'
  | 'stantio'
  | 'errore'
  | 'nessuna';

/** Profili del piano (§7): s-maxage + stale-while-revalidate per Cloudflare. */
export const CACHE_CONTROL: ReadonlyMap<ProfiloCache, string> = new Map<ProfiloCache, string>([
  ['elenco', 'public, max-age=60, s-maxage=300, stale-while-revalidate=300, stale-if-error=86400'],
  ['dettaglio', 'public, max-age=300, s-maxage=900, stale-while-revalidate=900, stale-if-error=86400'],
  ['feed', 'public, max-age=300, s-maxage=600, stale-while-revalidate=600, stale-if-error=86400'],
  ['statico', 'public, max-age=900, s-maxage=3600, stale-while-revalidate=3600, stale-if-error=86400'],
  ['openapi', 'public, max-age=3600, s-maxage=86400'],
  ['stantio', 'public, max-age=30, s-maxage=60'],
  ['errore', 'public, max-age=60, s-maxage=60'],
  ['nessuna', 'no-store'],
]);

export const TIPO_JSON = 'application/json; charset=utf-8';
export const TIPO_PROBLEMA = 'application/problem+json; charset=utf-8';
export const TIPO_JSON_FEED = 'application/feed+json; charset=utf-8';
export const TIPO_RSS = 'application/rss+xml; charset=utf-8';
export const TIPO_OPENAPI = 'application/vnd.oai.openapi+json;version=3.1';

export const METODI_AMMESSI = 'GET, HEAD, OPTIONS';

/** Link presenti su ogni risposta v1. */
export const LINK_COMUNI: readonly string[] = [
  `<${URL_OPENAPI}>; rel="service-desc"`,
  `<${URL_TERMINI}>; rel="terms-of-service"`,
];

const ESPOSTI = 'ETag, Link, Retry-After, RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset, RateLimit-Policy';

/** Header di ogni risposta v1 (200, 304, errori, OPTIONS). ACAO statico: niente Vary: Origin. */
export function intestazioniComuni(): Headers {
  return new Headers({
    'Vary': 'Accept-Encoding',
    'X-Robots-Tag': 'noindex',
    'X-Content-Type-Options': 'nosniff',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Expose-Headers': ESPOSTI,
    'Cross-Origin-Resource-Policy': 'cross-origin',
    'RateLimit-Policy': RATE_LIMIT_POLICY,
    'Content-Language': 'it',
  });
}

/** ETag debole: W/"<27 caratteri base64url dello SHA-256 del corpo>". */
export function etagDebole(corpo: string): string {
  return `W/"${createHash('sha256').update(corpo).digest('base64url').slice(0, 27)}"`;
}

/** Confronto debole di If-None-Match (lista, W/, *). */
export function ifNoneMatchCorrisponde(intestazione: string | null, etag: string): boolean {
  if (!intestazione) return false;
  const nudo = (v: string) => v.trim().replace(/^W\//, '');
  const atteso = nudo(etag);
  return intestazione.split(',').some((v) => v.trim() === '*' || nudo(v) === atteso);
}

function aggiungiLink(intestazioni: Headers, link: readonly string[]): void {
  const tutti = [...link, ...LINK_COMUNI];
  if (tutti.length > 0) intestazioni.set('Link', tutti.join(', '));
}

/** Corpo problem+json. `percorso` e' il solo pathname: instance non riporta mai la query. */
export function corpoProblema(problema: ProblemaApi, percorso: string): string {
  const corpo: Record<string, unknown> = {
    type: `${URL_DOCUMENTAZIONE}#error-${problema.codice}`,
    title: problema.titolo,
    status: problema.status,
    detail: problema.dettaglio,
    // Gli slash iniziali si collassano: con '//api/v1/x' new URL leggerebbe 'api' come host.
    instance: new URL(`${SITO}/${percorso.replace(/^\/+/, '')}`).href,
    code: problema.codice,
  };
  if (problema.errori.length > 0) {
    corpo.errors = problema.errori.map((e) => (e.allowed
      ? { parameter: e.parameter, detail: e.detail, allowed: [...e.allowed] }
      : { parameter: e.parameter, detail: e.detail }));
  }
  if (problema.retryAfter !== null) corpo.retry_after = problema.retryAfter;
  if (problema.primo !== null) corpo.first = problema.primo;
  return JSON.stringify(corpo);
}

/** 400 e 404 sono cacheabili per poco; il resto mai. */
export function profiloProblema(problema: ProblemaApi): ProfiloCache {
  return problema.status === 400 || problema.status === 404 ? 'errore' : 'nessuna';
}

export function rispostaProblema(
  problema: ProblemaApi,
  percorso: string,
  extra: Readonly<Record<string, string>> = {},
): Response {
  const intestazioni = intestazioniComuni();
  intestazioni.set('Content-Type', TIPO_PROBLEMA);
  intestazioni.set('Cache-Control', CACHE_CONTROL.get(profiloProblema(problema)) as string);
  if (problema.retryAfter !== null) intestazioni.set('Retry-After', String(problema.retryAfter));
  if (problema.status === 405) intestazioni.set('Allow', METODI_AMMESSI);
  for (const [nome, valore] of Object.entries(extra)) intestazioni.set(nome, valore);
  aggiungiLink(intestazioni, []);
  return new Response(corpoProblema(problema, percorso), { status: problema.status, headers: intestazioni });
}

export interface OpzioniContenuto {
  contentType: string;
  profilo: ProfiloCache;
  etag: string;
  link: readonly string[];
  extra?: Readonly<Record<string, string>>;
}

function intestazioniContenuto(opzioni: OpzioniContenuto): Headers {
  const intestazioni = intestazioniComuni();
  intestazioni.set('Content-Type', opzioni.contentType);
  intestazioni.set('Cache-Control', CACHE_CONTROL.get(opzioni.profilo) as string);
  intestazioni.set('ETag', opzioni.etag);
  for (const [nome, valore] of Object.entries(opzioni.extra ?? {})) intestazioni.set(nome, valore);
  aggiungiLink(intestazioni, opzioni.link);
  return intestazioni;
}

export function rispostaContenuto(corpo: string, opzioni: OpzioniContenuto): Response {
  return new Response(corpo, { status: 200, headers: intestazioniContenuto(opzioni) });
}

/** 304: stessi header del 200 (ETag, Cache-Control, Link, CORS), senza corpo ne' Content-Type. */
export function risposta304(opzioni: OpzioniContenuto): Response {
  const intestazioni = intestazioniContenuto(opzioni);
  intestazioni.delete('Content-Type');
  return new Response(null, { status: 304, headers: intestazioni });
}

/** Preflight CORS: sola lettura, nessuna credenziale. */
export function rispostaPreflight(): Response {
  const intestazioni = intestazioniComuni();
  intestazioni.set('Access-Control-Allow-Methods', METODI_AMMESSI);
  intestazioni.set('Access-Control-Allow-Headers', 'Accept, If-None-Match, Cache-Control');
  intestazioni.set('Access-Control-Max-Age', '86400');
  intestazioni.set('Cache-Control', 'public, max-age=86400');
  return new Response(null, { status: 204, headers: intestazioni });
}
