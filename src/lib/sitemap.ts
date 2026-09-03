/**
 * Primitive condivise dalle sitemap. Nascono da src/pages/sitemap-bandi.xml.ts, che
 * era l'unica delle tre di sezione a fare le cose per bene: loop a blocchi, tiebreak
 * deterministico sull'ordinamento, hardening dello slug e lastmod omesso se nullo.
 */

export const SITO = 'https://edunews24.it';

/** URL per file sitemap. Il limite del formato e' 50.000: qui stiamo molto sotto. */
export const URL_PER_SITEMAP = 1000;

/** Dimensione dei blocchi di lettura da PostgREST (che tronca a 1000 di default). */
export const BLOCCO_DB = 1000;

const SLUG_SAFE = /^[A-Za-z0-9_-]+$/;

/** Slug gia' sicuro in un URL, altrimenti percent-encoded. */
export function locSicura(slug: string): string {
  return SLUG_SAFE.test(slug) ? slug : encodeURIComponent(slug);
}

export function escapeXml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * ISO 8601 di una data, oppure null se manca o non e' parsabile.
 * Non lancia mai: prima di questo helper un interpello_date NULL faceva finire
 * l'intera sitemap in un 500 (new Date(null).toISOString() -> RangeError).
 */
export function lastmodIso(valore: string | null | undefined): string | null {
  if (!valore) return null;
  const d = new Date(valore);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Il piu' recente fra piu' lastmod, o null se non ce n'e' nessuno valido. */
export function lastmodMassimo(valori: Array<string | null | undefined>): string | null {
  let max: number | null = null;
  for (const v of valori) {
    if (!v) continue;
    const t = new Date(v).getTime();
    if (Number.isNaN(t)) continue;
    if (max === null || t > max) max = t;
  }
  return max === null ? null : new Date(max).toISOString();
}

export interface VoceUrl {
  loc: string;
  lastmod?: string | null;
  changefreq?: string;
  priority?: string;
}

export function urlset(voci: VoceUrl[]): string {
  const corpo = voci
    .map((v) => {
      let s = `\n  <url>\n    <loc>${escapeXml(v.loc)}</loc>`;
      if (v.lastmod) s += `\n    <lastmod>${v.lastmod}</lastmod>`;
      if (v.changefreq) s += `\n    <changefreq>${v.changefreq}</changefreq>`;
      if (v.priority) s += `\n    <priority>${v.priority}</priority>`;
      return s + `\n  </url>`;
    })
    .join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${corpo}
</urlset>`;
}

export interface VoceIndice {
  loc: string;
  lastmod?: string | null;
}

export function sitemapindex(voci: VoceIndice[]): string {
  const corpo = voci
    .map((v) => {
      let s = `\n  <sitemap>\n    <loc>${escapeXml(v.loc)}</loc>`;
      if (v.lastmod) s += `\n    <lastmod>${v.lastmod}</lastmod>`;
      return s + `\n  </sitemap>`;
    })
    .join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${corpo}
</sitemapindex>`;
}

/** Risposta XML standard delle sitemap del repo. */
export function rispostaXml(xml: string, maxAge = 86400): Response {
  return new Response(xml, {
    status: 200,
    headers: {
      'Content-Type': 'application/xml',
      'Cache-Control': `public, max-age=${maxAge}`,
    },
  });
}

/** Parametro di chunk non valido: 400, come sitemap-articoli/[date].xml.ts:26. */
export function rispostaParametroNonValido(): Response {
  return new Response('Formato non valido. Richiede: N.xml con N intero >= 1', {
    status: 400,
    headers: { 'Content-Type': 'text/plain' },
  });
}

/** Chunk oltre l'ultimo: 404. */
export function rispostaChunkInesistente(): Response {
  return new Response('Sitemap non trovata', {
    status: 404,
    headers: { 'Content-Type': 'text/plain', 'X-Robots-Tag': 'noindex' },
  });
}

export function rispostaErrore(contesto: string, errore: unknown): Response {
  console.error(`Errore nella generazione di ${contesto}:`, errore);
  return new Response(`Errore nella generazione di ${contesto}`, {
    status: 500,
    headers: { 'Content-Type': 'text/plain' },
  });
}

/** Numero di file dell'indice per un totale di URL. Almeno 1, anche a zero righe. */
export function numeroChunk(totale: number): number {
  return Math.max(1, Math.ceil(totale / URL_PER_SITEMAP));
}
