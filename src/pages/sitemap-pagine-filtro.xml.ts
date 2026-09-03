import { tuttePubblicate } from '../lib/pagine-filtro';
import { SITO, lastmodIso, urlset, rispostaXml, rispostaErrore } from '../lib/sitemap';

/**
 * Sitemap delle pagine filtro long-tail (regione, provincia, classe, categoria,
 * settore, programma, tipologia) e delle relative pagine indice.
 *
 * L'elenco e' calcolato dai dati, non scritto a mano: una combinazione entra qui solo
 * se supera la soglia in src/config/pagine-filtro.ts, cioe' esattamente quando la sua
 * pagina risponde 200. Le URL con ?page=N non vanno in sitemap.
 *
 * E' l'unico endpoint sitemap che aspetta la costruzione del corpus a freddo: e' un
 * endpoint per crawler, qualche secondo in piu' non e' un problema.
 */
export async function GET() {
  try {
    const pagine = await tuttePubblicate();
    const voci = pagine.map((p) => ({
      loc: `${SITO}${p.href}`,
      lastmod: lastmodIso(p.ultimaData),
      changefreq: 'daily',
      priority: p.hub ? '0.7' : '0.6',
    }));
    return rispostaXml(urlset(voci), 43200);
  } catch (error) {
    return rispostaErrore('sitemap-pagine-filtro', error);
  }
}
