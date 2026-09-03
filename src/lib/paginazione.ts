/**
 * Paginazione condivisa fra pagine elenco e pagine filtro.
 *
 * L'algoritmo dei numeri con ellissi e' portato da src/pages/[category].astro:178-221,
 * dove e' gia' in produzione. NON e' portata invece la guardia "pagina fuori range" di
 * quel file: e' rotta (quando PostgREST risponde PGRST103 il count resta null,
 * totalPages collassa a 1 e la condizione non scatta mai, tant'e' che /scuola?page=99999
 * risponde 200). Qui una pagina oltre l'ultima e' un 404.
 */

export const PUNTINI = '...';

const intervallo = (da: number, a: number): number[] =>
  Array.from({ length: a - da + 1 }, (_, i) => i + da);

export function elementiPaginazione(
  paginaCorrente: number,
  paginePresenti: number,
  vicini = 1,
): (string | number)[] {
  const massimo = vicini + 5;
  if (massimo >= paginePresenti) return intervallo(1, paginePresenti);

  const sinistra = Math.max(paginaCorrente - vicini, 1);
  const destra = Math.min(paginaCorrente + vicini, paginePresenti);
  const puntiniASinistra = sinistra > 2;
  const puntiniADestra = destra < paginePresenti - 2;
  const quanti = 3 + 2 * vicini;

  if (!puntiniASinistra && puntiniADestra) return [...intervallo(1, quanti), PUNTINI, paginePresenti];
  if (puntiniASinistra && !puntiniADestra) return [1, PUNTINI, ...intervallo(paginePresenti - quanti + 1, paginePresenti)];
  if (puntiniASinistra && puntiniADestra) return [1, PUNTINI, ...intervallo(sinistra, destra), PUNTINI, paginePresenti];
  return intervallo(1, paginePresenti);
}

export function numeroPagine(totale: number, perPagina: number): number {
  return Math.max(1, Math.ceil(totale / perPagina));
}

export function intervalloRange(pagina: number, perPagina: number): { da: number; a: number } {
  const da = (pagina - 1) * perPagina;
  return { da, a: da + perPagina - 1 };
}

export type EsitoPagina =
  | { tipo: 'ok'; pagina: number }
  /** ?page=1, ?page=0, ?page=abc: l'URL canonico e' quello pulito. */
  | { tipo: 'redirect'; href: string }
  /** Numero valido ma assurdo: 404 senza nemmeno interrogare il DB. */
  | { tipo: 'nonTrovata' };

/**
 * Legge ?page= dalla query string.
 * Pagina 1 non ha parametro: `?page=1` fa 301 verso l'URL pulito, cosi' non esistono
 * due URL con lo stesso contenuto.
 */
export function leggiPagina(url: URL, base: string): EsitoPagina {
  const grezzo = url.searchParams.get('page');
  if (grezzo === null) return { tipo: 'ok', pagina: 1 };
  if (grezzo === '1') return { tipo: 'redirect', href: base };
  if (!/^[1-9]\d{0,5}$/.test(grezzo)) return { tipo: 'redirect', href: base };
  return { tipo: 'ok', pagina: Number(grezzo) };
}

/**
 * URL di una pagina: la prima senza `?page=`, le altre con.
 *
 * `base` puo' gia' contenere una query string, perche' nelle pagine elenco porta i
 * filtri attivi (`/interpelli?regione=marche`): in quel caso il parametro va aggiunto
 * con `&`, non con un secondo `?`.
 */
export function hrefPagina(base: string, pagina: number): string {
  if (pagina <= 1) return base;
  return `${base}${base.includes('?') ? '&' : '?'}page=${pagina}`;
}

/** 404 reale con noindex. Stesso pattern di src/pages/bandi/[slug].astro:46-50. */
export function rispostaNonTrovata(titolo: string, messaggio: string, hrefRitorno: string, etichettaRitorno: string): Response {
  return new Response(
    `<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><title>404 - ${titolo}</title></head>` +
      `<body><h1>404 - ${titolo}</h1><p>${messaggio}</p>` +
      `<p><a href="${hrefRitorno}">${etichettaRitorno}</a></p></body></html>`,
    { status: 404, headers: { 'Content-Type': 'text/html', 'X-Robots-Tag': 'noindex' } },
  );
}
