import { supabase } from '../lib/supabase';
import { supabaseBandi, FONTE_BANDI } from '../lib/supabase-bandi';
import {
  SITO, lastmodIso, numeroChunk, sitemapindex,
  rispostaXml, rispostaErrore, type VoceIndice,
} from '../lib/sitemap';

/**
 * Indice delle sitemap. Prima elencava 8 file statici con lastmod = data odierna per
 * tutti: un segnale sempre "modificato oggi", che Google impara a ignorare. Ora le tre
 * sezioni sono spezzate in blocchi da 1000 URL e ogni voce porta il lastmod reale del
 * proprio blocco.
 *
 * Ogni query controlla `error` e rilancia: il `catch` del GET risponde con
 * `rispostaErrore`. Ignorare l'errore e' peggio che sbagliare, qui: un conteggio
 * che torna 0 perche' la query e' fallita fa rispondere 200 a un indice senza
 * nessuna voce `sitemap-<sezione>/N.xml`, cioe' ritira in silenzio da Google
 * tutti gli URL di quella sezione.
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
        const { count, error } = await supabase.from('interpelli')
          .select('id', { count: 'exact', head: true })
          .eq('link_type', 'single').eq('status', 'completed');
        if (error) throw error;
        return count ?? 0;
      },
      async (offset) => {
        const { data, error } = await supabase.from('interpelli')
          .select('interpello_date')
          .eq('link_type', 'single').eq('status', 'completed')
          .order('interpello_date', { ascending: false }).order('id', { ascending: false })
          .range(offset, offset);
        if (error) throw error;
        return lastmodIso(data?.[0]?.interpello_date);
      },
    );

    const selezione = await leggiSezione(
      'sitemap-selezione-personale',
      async () => {
        const { count, error } = await supabase.from('selezione_personale')
          .select('id', { count: 'exact', head: true }).eq('status', 'completed');
        if (error) throw error;
        return count ?? 0;
      },
      async (offset) => {
        const { data, error } = await supabase.from('selezione_personale')
          .select('data_pubblicazione, updated_at')
          .eq('status', 'completed')
          .order('data_pubblicazione', { ascending: false }).order('id', { ascending: false })
          .range(offset, offset);
        if (error) throw error;
        return lastmodIso(data?.[0]?.updated_at ?? data?.[0]?.data_pubblicazione);
      },
    );

    // Bandi: tabella e condizione di pubblicazione da FONTE_BANDI
    // (src/lib/bandi/pubblicazione.ts), non piu' ricopiate qui. Il conteggio di
    // questo file decide quanti blocchi vengono dichiarati: se restasse
    // indietro rispetto a /sitemap-bandi/N.xml l'indice annuncerebbe blocchi
    // vuoti (o ne nasconderebbe di pieni). Sulla vista `bando_pubblico` le
    // operazioni sono zero, perche' il predicato ce l'ha dentro.
    const bandi = await leggiSezione(
      'sitemap-bandi',
      async () => {
        let query = supabaseBandi.from(FONTE_BANDI.tabella)
          .select('id', { count: 'exact', head: true });
        for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
          query = query.filter(colonna, operatore, valore);
        }
        const { count, error } = await query;
        if (error) throw error;
        return count ?? 0;
      },
      async (offset) => {
        // `updated_at` come nei blocchi: `ultimo_cambiamento_at` (§7.5 del
        // piano) arriva con la migrazione 01, oggi non applicata. Attenzione:
        // `updated_at` non e' fra le colonne della vista `bando_pubblico`
        // (§13.2, «assenti per scelta»), quindi questo file non e' ancora
        // pronto per `BANDI_FONTE_LETTURA=bando_pubblico`: accendere il flag
        // prima di aver spostato la select su `ultimo_cambiamento_at` da 42703
        // qui, sui blocchi e sulla scheda (vedi il runbook di F2).
        let query = supabaseBandi.from(FONTE_BANDI.tabella)
          .select('data_pubblicazione, updated_at');
        for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
          query = query.filter(colonna, operatore, valore);
        }
        const { data, error } = await query
          .order('data_pubblicazione', { ascending: false, nullsFirst: false })
          .order('id', { ascending: false })
          .range(offset, offset);
        if (error) throw error;
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
