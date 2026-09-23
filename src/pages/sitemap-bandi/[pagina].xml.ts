import { supabaseBandi, FONTE_BANDI } from '../../lib/supabase-bandi';
import {
  SITO, URL_PER_SITEMAP, locSicura, lastmodIso, urlset, numeroChunk,
  rispostaXml, rispostaParametroNonValido, rispostaChunkInesistente, rispostaErrore,
} from '../../lib/sitemap';

/**
 * Blocco N della sitemap dei bandi.
 *
 * Tabella e condizione di pubblicazione arrivano da `FONTE_BANDI`
 * (`src/lib/bandi/pubblicazione.ts`) e non sono piu' ricopiate qui. Erano due
 * delle quattro copie dello stesso predicato, ed e' il posto in cui una copia
 * rimasta indietro fa il danno peggiore: la sitemap continuerebbe a dichiarare
 * a Google URL che le liste non mostrano piu'.
 *
 * Le operazioni restano ripetute rispetto alla RLS di proposito — la sitemap
 * deve essere corretta anche se la policy cambia — ma ora sono scritte in un
 * posto solo. Sulla vista `bando_pubblico` sono zero, perche' il predicato ce
 * l'ha dentro: ripetere `stato_processing` darebbe 42703.
 */
export async function GET({ params }: { params: { pagina: string } }) {
  try {
    if (!/^[1-9]\d*$/.test(params.pagina)) return rispostaParametroNonValido();
    const n = Number(params.pagina);

    let conteggio = supabaseBandi
      .from(FONTE_BANDI.tabella)
      .select('id', { count: 'exact', head: true });
    for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
      conteggio = conteggio.filter(colonna, operatore, valore);
    }
    const { count, error: erroreConteggio } = await conteggio;
    if (erroreConteggio) throw erroreConteggio;

    if (n > numeroChunk(count ?? 0)) return rispostaChunkInesistente();

    const da = (n - 1) * URL_PER_SITEMAP;
    // `updated_at` resta la colonna del lastmod: `ultimo_cambiamento_at` (§7.5
    // del piano) nasce con la migrazione 01, che non e' applicata, e chiederla
    // oggi farebbe fallire l'intera sitemap con un 42703. Il rovescio: dopo
    // questo giro anche la sitemap segue `FONTE_BANDI`, e `updated_at` non e'
    // fra le colonne della vista `bando_pubblico` (§13.2, «assenti per
    // scelta»). Il file non e' ancora pronto per la vista: prima di accendere
    // `BANDI_FONTE_LETTURA=bando_pubblico` va spostata questa select (e quella
    // di sitemap-index) su `ultimo_cambiamento_at` — runbook di F2.
    let pagina = supabaseBandi
      .from(FONTE_BANDI.tabella)
      .select('id, slug, updated_at, data_pubblicazione');
    for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
      pagina = pagina.filter(colonna, operatore, valore);
    }
    const { data, error } = await pagina
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
