import { supabase } from '../supabase';
import { todayRomeISO } from '../supabase-bandi';
import { corpus } from '../corpus';
import { orIlike, sanitizzaRicerca } from './postgrest';
import type { DefLista, Valori } from './parametri';
import { PAGINE_FILTRO } from '../../config/pagine-filtro';
import type { SelezioneBando } from '../../types/bandi';

/**
 * Lettura degli annunci di selezione personale.
 *
 * Colonne della card soltanto: select('*') porterebbe anche article_content, che da
 * solo e' l'84% dei byte di ogni riga e non compare mai in lista.
 */
export const COLONNE_CARD_SELEZIONE =
  'id, slug, codice, titolo, article_title, article_subtitle, figura_ricercata, ' +
  'num_posti, tipo_procedura, data_pubblicazione, data_scadenza, ' +
  'sedi, categorie, settori, enti_riferimento, calculated_status, status_label';

export interface FiltroSelezione {
  /** Colonna array su cui applicare il contains. */
  colonna: 'sedi' | 'categorie' | 'settori';
  /** Valori DB ESATTI (spazi finali compresi): sono quelli che la query deve trovare. */
  valori: string[];
}

export interface CriteriSelezione {
  filtri?: FiltroSelezione[];
  /** Termine di ricerca gia' sanificato. */
  ricerca?: string;
}

/** Valore per l'operatore array `cs`, sempre fra virgolette. */
const quotato = (v: string) => `"${v.replace(/"/g, '')}"`;

function applica(query: any, criteri: CriteriSelezione) {
  for (const f of criteri.filtri ?? []) {
    if (!f.valori.length) continue;
    // NON usare .contains(): supabase-js emette cs.{Avviso OIV } senza virgolette e
    // PostgREST perde tutte le righe dei valori con spazi in coda o virgole dentro
    // (verificato: "Avviso OIV " passa da 92 risultati a 0). Serve la forma quotata.
    if (f.valori.length === 1) {
      query = query.filter(f.colonna, 'cs', `{${quotato(f.valori[0])}}`);
    } else {
      // Piu' grafie dello stesso valore ("Emilia Romagna" / "Emilia-Romagna"): OR.
      query = query.or(f.valori.map((v) => `${f.colonna}.cs.{${quotato(v)}}`).join(','));
    }
  }
  if (criteri.ricerca) {
    query = query.or(orIlike(['article_title', 'titolo', 'codice'], criteri.ricerca));
  }
  return query;
}

export interface PaginaSelezione {
  righe: SelezioneBando[];
  totale: number;
  aperti: number;
}

/**
 * Una pagina di risultati con gli annunci NON SCADUTI in cima.
 *
 * calculated_status vale 'OPEN' su tutte e 12.441 le righe, anche su quelle scadute da
 * mesi: l'unico dato affidabile e' data_scadenza. Non potendo ordinare per
 * un'espressione via PostgREST, si fanno due letture distinte — prima gli annunci
 * ancora aperti in ordine di scadenza piu' vicina, poi gli scaduti dal piu' recente —
 * e si prende la finestra che serve. Il confine fra i due gruppi viene da un conteggio
 * esatto, non dalla cache, cosi' nessun annuncio viene saltato o ripetuto.
 */
export async function caricaSelezione(
  criteri: CriteriSelezione,
  pagina: number,
  perPagina: number,
): Promise<PaginaSelezione> {
  const oggi = todayRomeISO();
  const lista = () => applica(supabase.from('selezione_personale').select(COLONNE_CARD_SELEZIONE).eq('status', 'completed'), criteri);
  const conta = () => applica(supabase.from('selezione_personale').select('id', { count: 'exact', head: true }).eq('status', 'completed'), criteri);

  const [{ count: totale }, { count: aperti }] = await Promise.all([
    conta(),
    conta().gte('data_scadenza', oggi),
  ]);

  const totaleN = totale ?? 0;
  const apertiN = aperti ?? 0;
  const da = (pagina - 1) * perPagina;
  const a = da + perPagina - 1;
  const righe: SelezioneBando[] = [];

  // Gruppo 1: ancora aperti, scadenza piu' vicina per prima.
  if (da < apertiN) {
    const { data } = await lista()
      .gte('data_scadenza', oggi)
      .order('data_scadenza', { ascending: true })
      .order('id', { ascending: false })
      .range(da, Math.min(a, apertiN - 1));
    righe.push(...((data ?? []) as unknown as SelezioneBando[]));
  }

  // Gruppo 2: scaduti, dal piu' recente.
  if (a >= apertiN) {
    const daScaduti = Math.max(0, da - apertiN);
    const quanti = perPagina - righe.length;
    if (quanti > 0) {
      const { data } = await lista()
        .lt('data_scadenza', oggi)
        .order('data_scadenza', { ascending: false })
        .order('id', { ascending: false })
        .range(daScaduti, daScaduti + quanti - 1);
      righe.push(...((data ?? []) as unknown as SelezioneBando[]));
    }
  }

  return { righe, totale: totaleN, aperti: apertiN };
}

// ---------------------------------------------------------------------------
// Lista server-side
// ---------------------------------------------------------------------------

const PER_PAGINA = PAGINE_FILTRO.find((c) => c.sezione === 'selezione-personale')!.perPagina;

/** I valori dei filtri sono SLUG: l'URL resta leggibile e le grafie divergenti convergono. */
export const DEF_SELEZIONE: DefLista = {
  sezione: 'selezione-personale',
  base: '/selezione-personale',
  frammento: '/api/lista/selezione-personale',
  perPagina: PER_PAGINA,
  parametri: [
    { nome: 'q' },
    { nome: 'categoria', dimensione: 'categoria' },
    { nome: 'settore' },
    { nome: 'sede' },
  ],
  parametroRicerca: 'q',
};

/** Faccetta -> valori DB esatti. null se lo slug non esiste. */
async function valoriDiSlug(dimensione: string, slug: string): Promise<string[] | null> {
  const c = await corpus('selezione-personale');
  return c.faccette[dimensione]?.get(slug)?.valoriDb ?? null;
}

export async function caricaListaSelezione(valori: Valori, pagina: number): Promise<PaginaSelezione> {
  const termine = sanitizzaRicerca(valori.q?.[0] ?? '');
  const filtri: FiltroSelezione[] = [];

  for (const [parametro, colonna] of [
    ['categoria', 'categorie'],
    ['settore', 'settori'],
    ['sede', 'sedi'],
  ] as const) {
    const slug = valori[parametro]?.[0];
    if (!slug) continue;
    const valoriDb = await valoriDiSlug(parametro === 'sede' ? 'sede' : parametro === 'settore' ? 'settore' : 'categoria', slug);
    // Slug inesistente: lista vuota, non lista intera sotto un URL che promette un filtro.
    if (!valoriDb) return { righe: [], totale: 0, aperti: 0 };
    filtri.push({ colonna, valori: valoriDb });
  }

  return caricaSelezione({ filtri, ricerca: termine || undefined }, pagina, PER_PAGINA);
}

export interface OpzioniFiltroSelezione {
  categorie: Array<{ slug: string; etichetta: string }>;
  settori: Array<{ slug: string; etichetta: string }>;
  sedi: Array<{ slug: string; etichetta: string }>;
}

/**
 * Opzioni dei select, dal corpus. Prima venivano ricalcolate a ogni pageview con una
 * select senza .range(): su 12.441 righe PostgREST ne restituiva 1000, cioe' le
 * opzioni erano costruite sull'8% del corpus.
 */
export async function opzioniFiltroSelezione(): Promise<OpzioniFiltroSelezione> {
  const c = await corpus('selezione-personale');
  const ordina = (dim: string) =>
    [...(c.faccette[dim]?.values() ?? [])]
      .map((v) => ({ slug: v.slug, etichetta: v.etichetta }))
      .sort((a, b) => a.etichetta.localeCompare(b.etichetta, 'it'));
  return { categorie: ordina('categoria'), settori: ordina('settore'), sedi: ordina('sede') };
}
