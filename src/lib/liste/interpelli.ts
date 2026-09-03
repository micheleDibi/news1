import { supabase } from '../supabase';
import { corpus } from '../corpus';
import { orIlike, sanitizzaRicerca } from './postgrest';
import type { DefLista, Valori } from './parametri';
import { PAGINE_FILTRO } from '../../config/pagine-filtro';

/**
 * Dominio della sezione interpelli: tipo della riga e slug canonico.
 *
 * Lo slug NON e' salvato a DB: si ricalcola da interpello_name + provincia|citta +
 * regione + id. Prima di questo modulo la stessa funzione era copiata in tre file
 * del frontend (la pagina elenco, il dettaglio e la sitemap) piu' una quarta volta
 * dentro lo script client. Resta una copia in backend/app/interpelli.py:46-59, fuori
 * dal perimetro di questo intervento: se si tocca l'algoritmo va allineata anche quella.
 */
export interface Interpello {
  id: number;
  interpello_name: string;
  interpello_date: string;
  interpello_description: string;
  interpello_link: string;
  interpello_regione?: string;
  interpello_provincia?: string;
  interpello_citta?: string;
  classe_concorso?: string;
  article_title?: string;
  article_subtitle?: string;
  article_content?: string;
  link_type?: string;
  status?: string;
  created_at?: string;
}

/** Riga minima sufficiente a calcolare lo slug (la usa anche la sitemap). */
export type InterpelloSlugabile = Pick<Interpello, 'id'> &
  Partial<Pick<Interpello, 'interpello_name' | 'interpello_provincia' | 'interpello_citta' | 'interpello_regione'>>;

export function slugInterpello(interpello: InterpelloSlugabile): string {
  const parts = [
    interpello.interpello_name,
    interpello.interpello_provincia || interpello.interpello_citta,
    interpello.interpello_regione,
    interpello.id?.toString(),
  ].filter(Boolean);

  return parts
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9\-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

/**
 * Colonne necessarie alla card. NON include article_content: con select('*') venti
 * righe pesano 156 KB contro gli 11 KB effettivamente usati.
 */
export const COLONNE_CARD_INTERPELLO =
  'id, interpello_name, interpello_date, interpello_description, interpello_link, ' +
  'interpello_regione, interpello_provincia, interpello_citta, classe_concorso, ' +
  'article_title, article_subtitle';

// ---------------------------------------------------------------------------
// Lista server-side
// ---------------------------------------------------------------------------

const PER_PAGINA = PAGINE_FILTRO.find((c) => c.sezione === 'interpelli')!.perPagina;

/**
 * Stato della lista nell'URL. I valori dei filtri sono SLUG, non valori grezzi del
 * DB: cosi' `?regione=emilia-romagna` cattura entrambe le grafie presenti in tabella
 * ("Emilia-Romagna" e "Emilia Romagna") e l'URL e' leggibile.
 */
export const DEF_INTERPELLI: DefLista = {
  sezione: 'interpelli',
  base: '/interpelli',
  frammento: '/api/lista/interpelli',
  perPagina: PER_PAGINA,
  parametri: [
    { nome: 'q' },
    { nome: 'regione', dimensione: 'regione' },
    { nome: 'provincia', dimensione: 'provincia' },
    { nome: 'classe', dimensione: 'classe' },
  ],
  parametroRicerca: 'q',
};

export interface PaginaInterpelli {
  righe: Interpello[];
  totale: number;
}

/** Valori DB corrispondenti a uno slug di faccetta; null se lo slug non esiste. */
async function valoriDiSlug(dimensione: string, slug: string): Promise<string[] | null> {
  const c = await corpus('interpelli');
  const voce = c.faccette[dimensione]?.get(slug);
  return voce ? voce.valoriDb : null;
}

export async function caricaInterpelli(valori: Valori, pagina: number): Promise<PaginaInterpelli> {
  let query = supabase
    .from('interpelli')
    .select(COLONNE_CARD_INTERPELLO, { count: 'exact' })
    .eq('link_type', 'single')
    // Le 5 righe in status='error' non hanno articolo generato: fuori da lista,
    // conteggio e sitemap, cosi' il numero e' lo stesso ovunque.
    .eq('status', 'completed');

  const termine = sanitizzaRicerca(valori.q?.[0] ?? '');
  if (termine) {
    query = query.or(orIlike(['article_title', 'article_subtitle', 'interpello_name', 'interpello_description'], termine));
  }

  for (const [parametro, colonna] of [
    ['regione', 'interpello_regione'],
    ['provincia', 'interpello_provincia'],
    ['classe', 'classe_concorso'],
  ] as const) {
    const slug = valori[parametro]?.[0];
    if (!slug) continue;
    const valoriDb = await valoriDiSlug(parametro, slug);
    // Slug inesistente: nessun risultato, non lista intera. Meglio una lista vuota
    // che una lista non filtrata sotto un URL che promette un filtro.
    if (!valoriDb) return { righe: [], totale: 0 };
    query = query.in(colonna, valoriDb);
  }

  const da = (pagina - 1) * PER_PAGINA;
  const { data, count, error } = await query
    .order('interpello_date', { ascending: false })
    .order('id', { ascending: false })
    .range(da, da + PER_PAGINA - 1);

  if (error) {
    // PGRST103: offset oltre il totale. A pagina 1 non e' un errore, e' un filtro
    // senza risultati; oltre la prima pagina il chiamante fara' 404.
    if ((error as { code?: string }).code !== 'PGRST103') console.error('[lista interpelli]', error);
    return { righe: [], totale: 0 };
  }

  return { righe: (data ?? []) as unknown as Interpello[], totale: count ?? 0 };
}

export interface OpzioniFiltroInterpelli {
  regioni: Array<{ slug: string; etichetta: string }>;
  province: Array<{ slug: string; etichetta: string }>;
  classi: Array<{ slug: string; etichetta: string }>;
  /** slug regione -> province di quella regione, per il select dipendente. */
  provincePerRegione: Record<string, Array<{ slug: string; etichetta: string }>>;
}

/**
 * Opzioni dei select, dal corpus. La versione precedente le calcolava a ogni pageview
 * con una select senza .range(): PostgREST tronca a 1000 righe su 1046, quindi le
 * opzioni erano incomplete e quali mancassero dipendeva dall'ordine di ritorno.
 */
export async function opzioniFiltroInterpelli(): Promise<OpzioniFiltroInterpelli> {
  const c = await corpus('interpelli');
  const ordina = (dim: string) =>
    [...(c.faccette[dim]?.values() ?? [])]
      .map((v) => ({ slug: v.slug, etichetta: v.etichetta }))
      .sort((a, b) => a.etichetta.localeCompare(b.etichetta, 'it'));

  const etichettaProvincia = (slug: string) => c.faccette.provincia?.get(slug)?.etichetta ?? slug;
  const provincePerRegione: Record<string, Array<{ slug: string; etichetta: string }>> = {};
  for (const [chiave, perA] of c.incroci) {
    if (chiave !== 'regione|provincia') continue;
    for (const [slugRegione, perB] of perA) {
      provincePerRegione[slugRegione] = [...perB.keys()]
        .map((slug) => ({ slug, etichetta: etichettaProvincia(slug) }))
        .sort((a, b) => a.etichetta.localeCompare(b.etichetta, 'it'));
    }
  }

  return {
    regioni: ordina('regione'),
    province: ordina('provincia'),
    classi: ordina('classe'),
    provincePerRegione,
  };
}
