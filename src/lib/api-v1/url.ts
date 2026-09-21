/**
 * URL emessi dall'API /api/v1: media, schede, articoli e link dell'API stessa.
 *
 * Regole (piano §3.1 regola 5 e §3.5):
 * - ogni URL in uscita e' assoluto e normalizzato con WHATWG `URL`;
 * - la base e' sempre SITO, mai l'host di request.url;
 * - un URL che non supera i controlli diventa null (il chiamante decide se il
 *   campo resta null o se la riga va scartata), non viene "aggiustato".
 *
 * Modulo puro: nessun I/O, nessun accesso all'ambiente.
 */
import { getArticlePublicUrl } from '../utils';
import { locSicura } from '../sitemap';
import { BASE_API, SITO } from './costanti';

/** Oltre questa lunghezza un URL di media non viene esposto. */
const LUNGHEZZA_MASSIMA_URL = 2048;

/** Etichetta DNS accettata: minuscole (WHATWG le ha gia' abbassate), cifre, `_` e `-`. */
const ETICHETTA_HOST = /^[a-z0-9_-]{1,63}$/;

const ORIGINE_SITO = new URL(SITO).origin;

/**
 * Host sintatticamente pulito, cosi' come lo restituisce `URL.hostname`:
 * etichette `[a-z0-9_-]` da 1 a 63 caratteri, nessuna vuota (niente `ex..com`
 * ne' il punto finale), oppure un IPv6 fra parentesi quadre (gia' validato dal
 * parser WHATWG). Serve perche' WHATWG accetta host come `ex"ample.com` o
 * `ex&ample.com`.
 */
export function hostValido(hostname: string): boolean {
  if (hostname.startsWith('[') && hostname.endsWith(']')) return hostname.length > 2;
  if (hostname === '') return false;
  return hostname.split('.').every((etichetta) => ETICHETTA_HOST.test(etichetta));
}

function analizza(testo: string, base?: string): URL | null {
  try {
    return base === undefined ? new URL(testo) : new URL(testo, base);
  } catch {
    return null;
  }
}

/**
 * URL assoluto di un'immagine o di un video, oppure null.
 *
 * - non stringa, vuoto, solo spazi, oltre 2048 caratteri, non analizzabile -> null;
 * - schema diverso da http/https (blob:, data:, javascript:, ftp:) -> null;
 * - credenziali nell'URL -> null (una `@` nel percorso e' invece legittima);
 * - host non valido -> null;
 * - `/percorso` -> SITO + percorso (e deve restare sull'origine del sito:
 *   `/\evil.com/x` verrebbe letto da WHATWG come `//evil.com/x`);
 * - `//host/x` -> `https://host/x`;
 * - http(s) valido, anche di terzi -> href normalizzato.
 */
export function urlMediaAssoluto(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const testo = v.trim();
  if (testo === '' || testo.length > LUNGHEZZA_MASSIMA_URL) return null;

  let url: URL | null;
  if (testo.startsWith('//')) {
    url = analizza(`https:${testo}`);
  } else if (testo.startsWith('/')) {
    url = analizza(testo, SITO);
    if (url !== null && url.origin !== ORIGINE_SITO) return null;
  } else {
    url = analizza(testo);
  }
  if (url === null) return null;
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.username !== '' || url.password !== '') return null;
  if (!hostValido(url.hostname)) return null;
  return url.href;
}

/**
 * URL pubblico di un articolo: `getArticlePublicUrl` (mai `getArticleUrl`, che
 * slugifica il nome della categoria) normalizzato con WHATWG, che codifica i
 * segmenti. null se mancano categoria o slug, se l'URL non e' analizzabile o
 * se non individua esattamente la pagina `/{categoria}/{slug}` del sito: uno
 * slug con `?`, `#`, `/` o uguale a `..` produrrebbe un link a un'altra pagina.
 */
export function urlArticolo(categorySlug: unknown, slug: unknown): string | null {
  if (typeof categorySlug !== 'string' || typeof slug !== 'string') return null;
  const grezzo = getArticlePublicUrl({ category_slug: categorySlug, slug });
  if (grezzo === null) return null;
  const url = analizza(grezzo);
  if (url === null || url.origin !== ORIGINE_SITO) return null;
  if (url.search !== '' || url.hash !== '') return null;
  const segmenti = url.pathname.split('/');
  if (segmenti.length !== 3 || segmenti[1] === '' || segmenti[2] === '') return null;
  return url.href;
}

/**
 * URL della scheda di un'opportunita' (selezione personale, bandi, interpelli):
 * `basePath` viene da configSezione, lo slug passa da `locSicura`.
 */
export function urlScheda(basePath: string, slug: string): string {
  return new URL(`${basePath}/${locSicura(slug)}`, SITO).href;
}

/**
 * URL assoluto dell'API: BASE_API + percorso (che inizia con '/' oppure e'
 * vuoto) e la query solo se non e' vuota. L'ordine dei parametri e' quello
 * della URLSearchParams ricevuta: la forma canonica e' compito del chiamante.
 */
export function urlApi(percorso: string, query?: URLSearchParams | null): string {
  const stringaQuery = query ? query.toString() : '';
  const completo = stringaQuery === '' ? `${BASE_API}${percorso}` : `${BASE_API}${percorso}?${stringaQuery}`;
  return new URL(completo).href;
}

const MIME_VIDEO: ReadonlyMap<string, string> = new Map([
  ['mp4', 'video/mp4'],
  ['mov', 'video/quicktime'],
  ['webm', 'video/webm'],
]);

/**
 * Tipo MIME di un video dall'estensione del percorso (query e frammento
 * ignorati, maiuscole indifferenti): mp4, mov e webm; altro -> null.
 */
export function mimeVideo(url: string): string | null {
  const analizzato = analizza(url);
  const percorso = analizzato !== null ? analizzato.pathname : url.split(/[?#]/, 1)[0];
  const ultimo = percorso.slice(percorso.lastIndexOf('/') + 1);
  const punto = ultimo.lastIndexOf('.');
  if (punto <= 0) return null;
  return MIME_VIDEO.get(ultimo.slice(punto + 1).toLowerCase()) ?? null;
}
