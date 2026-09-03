import { supabase } from '../lib/supabase';
import { supabaseBandi } from '../lib/supabase-bandi';
import {
  SITO, lastmodIso, numeroChunk, sitemapindex,
  rispostaXml, rispostaErrore, type VoceIndice,
} from '../lib/sitemap';

/**
 * Indice delle sitemap. Prima elencava 8 file statici con lastmod = data odierna per
 * tutti: un segnale sempre "modificato oggi", che Google impara a ignorare. Ora le tre
 * sezioni sono spezzate in blocchi da 1000 URL e ogni voce porta il lastmod reale del
 * proprio blocco.
 */

interface Sezione {
  percorso: string;              // 'sitemap-interpelli'
  totale: number;
  lastmodPerChunk: (string | null)[];
}

/** Conteggio + lastmod piu' recente di ogni blocco, con una query per blocco. */
async function leggiSezione(
  percorso: string,
  conta: () => Promise<number>,
  primoDelBlocco: (offset: number) => Promise<string | null>,
): Promise<Sezione> {
  const totale = await conta();
  const chunk = numeroChunk(totale);
  const lastmodPerChunk: (string | null)[] = [];
  for (let n = 1; n <= chunk; n++) {
    // Le righe sono ordinate per data decrescente: la prima del blocco e' la piu'
    // recente, quindi e' gia' il lastmod del blocco.
    lastmodPerChunk.push(await primoDelBlocco((n - 1) * 1000));
  }
  return { percorso, totale, lastmodPerChunk };
}

export async function GET() {
  try {
    const interpelli = await leggiSezione(
      'sitemap-interpelli',
      async () => {
        const { count } = await supabase.from('interpelli')
          .select('id', { count: 'exact', head: true })
          .eq('link_type', 'single').eq('status', 'completed');
        return count ?? 0;
      },
      async (offset) => {
        const { data } = await supabase.from('interpelli')
          .select('interpello_date')
          .eq('link_type', 'single').eq('status', 'completed')
          .order('interpello_date', { ascending: false }).order('id', { ascending: false })
          .range(offset, offset);
        return lastmodIso(data?.[0]?.interpello_date);
      },
    );

    const selezione = await leggiSezione(
      'sitemap-selezione-personale',
      async () => {
        const { count } = await supabase.from('selezione_personale')
          .select('id', { count: 'exact', head: true }).eq('status', 'completed');
        return count ?? 0;
      },
      async (offset) => {
        const { data } = await supabase.from('selezione_personale')
          .select('data_pubblicazione, updated_at')
          .eq('status', 'completed')
          .order('data_pubblicazione', { ascending: false }).order('id', { ascending: false })
          .range(offset, offset);
        return lastmodIso(data?.[0]?.updated_at ?? data?.[0]?.data_pubblicazione);
      },
    );

    const bandi = await leggiSezione(
      'sitemap-bandi',
      async () => {
        const { count } = await supabaseBandi.from('bando')
          .select('id', { count: 'exact', head: true })
          .eq('stato_processing', 'completed').not('slug', 'is', null);
        return count ?? 0;
      },
      async (offset) => {
        const { data } = await supabaseBandi.from('bando')
          .select('data_pubblicazione, updated_at')
          .eq('stato_processing', 'completed').not('slug', 'is', null)
          .order('data_pubblicazione', { ascending: false, nullsFirst: false })
          .order('id', { ascending: false })
          .range(offset, offset);
        return lastmodIso(data?.[0]?.updated_at ?? data?.[0]?.data_pubblicazione);
      },
    );

    const voci: VoceIndice[] = [
      { loc: `${SITO}/sitemap-articoli.xml` },
      { loc: `${SITO}/sitemap-pagine.xml` },
      { loc: `${SITO}/sitemap-news.xml` },
      { loc: `${SITO}/sitemap-categorie.xml` },
      { loc: `${SITO}/sitemap-video-index.xml` },
      { loc: `${SITO}/sitemap-pagine-filtro.xml` },
    ];

    for (const sez of [interpelli, selezione, bandi]) {
      sez.lastmodPerChunk.forEach((lastmod, i) => {
        voci.push({ loc: `${SITO}/${sez.percorso}/${i + 1}.xml`, lastmod });
      });
    }

    // Un file indice non puo' elencare altri file indice: i blocchi delle sezioni
    // stanno qui direttamente, e le tre sitemap monolitiche rispondono con un 301.
    return rispostaXml(sitemapindex(voci), 3600);
  } catch (error) {
    return rispostaErrore('sitemap-index', error);
  }
}
