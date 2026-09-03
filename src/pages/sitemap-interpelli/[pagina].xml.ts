import { supabase } from '../../lib/supabase';
import { slugInterpello, type Interpello } from '../../lib/liste/interpelli';
import {
  SITO, URL_PER_SITEMAP, locSicura, lastmodIso, urlset, numeroChunk,
  rispostaXml, rispostaParametroNonValido, rispostaChunkInesistente, rispostaErrore,
} from '../../lib/sitemap';

/**
 * Blocco N della sitemap degli interpelli. Filtri allineati alla pagina elenco:
 * solo link_type='single' e status='completed'. La vecchia sitemap monolitica non
 * filtrava nulla e dichiarava anche i 101 record 'list' (slug "visualizza-interpelli-*"),
 * pagine orfane che nessuna lista collega, e i 5 record in errore senza articolo.
 */
export async function GET({ params }: { params: { pagina: string } }) {
  try {
    if (!/^[1-9]\d*$/.test(params.pagina)) return rispostaParametroNonValido();
    const n = Number(params.pagina);

    const { count, error: erroreConteggio } = await supabase
      .from('interpelli')
      .select('id', { count: 'exact', head: true })
      .eq('link_type', 'single')
      .eq('status', 'completed');
    if (erroreConteggio) throw erroreConteggio;

    if (n > numeroChunk(count ?? 0)) return rispostaChunkInesistente();

    const da = (n - 1) * URL_PER_SITEMAP;
    const { data, error } = await supabase
      .from('interpelli')
      .select('id, interpello_name, interpello_date, interpello_regione, interpello_provincia, interpello_citta')
      .eq('link_type', 'single')
      .eq('status', 'completed')
      .order('interpello_date', { ascending: false })
      // Tiebreak: senza, i confini fra un blocco e l'altro possono ripetere o saltare righe.
      .order('id', { ascending: false })
      .range(da, da + URL_PER_SITEMAP - 1);
    if (error) throw error;

    const voci = (data as Interpello[] ?? [])
      .map((i) => ({ slug: slugInterpello(i), data: i.interpello_date }))
      .filter((v) => v.slug)
      .map((v) => ({
        loc: `${SITO}/interpelli/${locSicura(v.slug)}`,
        // interpello_date e' l'unico campo temporale: la tabella non ha updated_at.
        lastmod: lastmodIso(v.data),
        changefreq: 'weekly',
        priority: '0.7',
      }));

    return rispostaXml(urlset(voci));
  } catch (error) {
    return rispostaErrore('sitemap-interpelli', error);
  }
}
