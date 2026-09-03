import { supabase } from '../../lib/supabase';
import {
  SITO, URL_PER_SITEMAP, locSicura, lastmodIso, urlset, numeroChunk,
  rispostaXml, rispostaParametroNonValido, rispostaChunkInesistente, rispostaErrore,
} from '../../lib/sitemap';

/**
 * Blocco N della sitemap di selezione personale. La vecchia sitemap monolitica faceva
 * UNA query senza .range(): PostgREST tronca a 1000 righe, quindi dichiarava 1000 URL
 * su 12.441. Qui ogni blocco legge la propria finestra.
 */
export async function GET({ params }: { params: { pagina: string } }) {
  try {
    if (!/^[1-9]\d*$/.test(params.pagina)) return rispostaParametroNonValido();
    const n = Number(params.pagina);

    const { count, error: erroreConteggio } = await supabase
      .from('selezione_personale')
      .select('id', { count: 'exact', head: true })
      .eq('status', 'completed');
    if (erroreConteggio) throw erroreConteggio;

    if (n > numeroChunk(count ?? 0)) return rispostaChunkInesistente();

    const da = (n - 1) * URL_PER_SITEMAP;
    const { data, error } = await supabase
      .from('selezione_personale')
      .select('id, slug, data_pubblicazione, updated_at')
      .eq('status', 'completed')
      .order('data_pubblicazione', { ascending: false })
      .order('id', { ascending: false })
      .range(da, da + URL_PER_SITEMAP - 1);
    if (error) throw error;

    const voci = (data ?? [])
      .filter((b) => b.slug)
      .map((b) => ({
        loc: `${SITO}/selezione-personale/${locSicura(b.slug as string)}`,
        lastmod: lastmodIso(b.updated_at ?? b.data_pubblicazione),
        changefreq: 'weekly',
        priority: '0.7',
      }));

    return rispostaXml(urlset(voci));
  } catch (error) {
    return rispostaErrore('sitemap-selezione-personale', error);
  }
}
