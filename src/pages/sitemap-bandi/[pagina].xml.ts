import { supabaseBandi } from '../../lib/supabase-bandi';
import {
  SITO, URL_PER_SITEMAP, locSicura, lastmodIso, urlset, numeroChunk,
  rispostaXml, rispostaParametroNonValido, rispostaChunkInesistente, rispostaErrore,
} from '../../lib/sitemap';

/**
 * Blocco N della sitemap dei bandi. I filtri duplicano la RLS pubblica
 * (stato_processing='completed' AND slug IS NOT NULL) come gia' faceva la monolitica.
 */
export async function GET({ params }: { params: { pagina: string } }) {
  try {
    if (!/^[1-9]\d*$/.test(params.pagina)) return rispostaParametroNonValido();
    const n = Number(params.pagina);

    const { count, error: erroreConteggio } = await supabaseBandi
      .from('bando')
      .select('id', { count: 'exact', head: true })
      .eq('stato_processing', 'completed')
      .not('slug', 'is', null);
    if (erroreConteggio) throw erroreConteggio;

    if (n > numeroChunk(count ?? 0)) return rispostaChunkInesistente();

    const da = (n - 1) * URL_PER_SITEMAP;
    const { data, error } = await supabaseBandi
      .from('bando')
      .select('id, slug, updated_at, data_pubblicazione')
      .eq('stato_processing', 'completed')
      .not('slug', 'is', null)
      .order('data_pubblicazione', { ascending: false, nullsFirst: false })
      // Tiebreak indispensabile: data_pubblicazione e' NULL sul 92% dei bandi.
      .order('id', { ascending: false })
      .range(da, da + URL_PER_SITEMAP - 1);
    if (error) throw error;

    const voci = (data ?? [])
      .filter((b) => b.slug)
      .map((b) => ({
        loc: `${SITO}/bandi/${locSicura(b.slug as string)}`,
        lastmod: lastmodIso(b.updated_at ?? b.data_pubblicazione),
        changefreq: 'monthly',
        priority: '0.7',
      }));

    return rispostaXml(urlset(voci));
  } catch (error) {
    return rispostaErrore('sitemap-bandi', error);
  }
}
