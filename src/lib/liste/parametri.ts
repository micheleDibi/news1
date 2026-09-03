import { slugifica } from '../slug';
import { regionePerValore } from '../regioni';
import type { Sezione } from '../../config/pagine-filtro';

/**
 * Stato della lista nell'URL.
 *
 * Non astrae la query: le tre sezioni hanno database, colonne e operatori diversi.
 * Qui vive solo cio' che e' davvero comune — leggere i parametri, validarli e
 * riserializzarli sempre nello stesso ordine, cosi' il canonical e' stabile a
 * prescindere dall'ordine in cui l'utente ha cliccato i filtri.
 */

export const SITO = 'https://edunews24.it';

export interface DefParametro {
  /** Nome nella query string e nell'attributo name del controllo. */
  nome: string;
  /** true se il parametro accetta piu' valori (le multiselect dei bandi). */
  multiplo?: boolean;
  /** Dimensione filtro corrispondente, se il parametro e' promuovibile a pagina statica. */
  dimensione?: string;
}

export interface DefLista {
  sezione: Sezione;
  /** Percorso della pagina 1 senza query. */
  base: string;
  /** Rotta che restituisce solo il frammento della lista. */
  frammento: string;
  perPagina: number;
  /** Ordine canonico dei parametri. `page` e' implicito e va sempre in coda. */
  parametri: readonly DefParametro[];
  /** Parametro della ricerca testuale libera: non e' mai promuovibile. */
  parametroRicerca?: string;
}

/** Valori normalizzati: nome del parametro -> valori (array vuoto = assente). */
export type Valori = Record<string, string[]>;

export function leggiFiltri(url: URL, def: DefLista): Valori {
  const valori: Valori = {};
  for (const p of def.parametri) {
    const grezzi = p.multiplo ? url.searchParams.getAll(p.nome) : [url.searchParams.get(p.nome) ?? ''];
    // I valori NON si trimmano: alcune categorie hanno uno spazio finale
    // significativo ("Avviso OIV ") e senza quello la query non trova nulla.
    const puliti = [...new Set(grezzi.filter((v) => v !== null && v !== ''))];
    if (p.multiplo) puliti.sort((a, b) => (/^\d+$/.test(a) && /^\d+$/.test(b) ? Number(a) - Number(b) : a.localeCompare(b)));
    valori[p.nome] = puliti as string[];
  }
  return valori;
}

export function filtriAttivi(valori: Valori): number {
  return Object.values(valori).filter((v) => v.length > 0).length;
}

/** '' oppure '?a=1&b=2&page=3'. Ordine fisso, `page` in coda, mai `page=1`. */
export function serializzaQuery(def: DefLista, valori: Valori, pagina: number): string {
  const qs = new URLSearchParams();
  for (const p of def.parametri) for (const v of valori[p.nome] ?? []) qs.append(p.nome, v);
  if (pagina > 1) qs.set('page', String(pagina));
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export function urlLista(def: DefLista, valori: Valori, pagina: number): string {
  return `${def.base}${serializzaQuery(def, valori, pagina)}`;
}

export function urlAssoluta(def: DefLista, valori: Valori, pagina: number): string {
  return `${SITO}${urlLista(def, valori, pagina)}`;
}

export function urlFrammento(def: DefLista, valori: Valori, pagina: number): string {
  return `${def.frammento}${serializzaQuery(def, valori, pagina)}`;
}

/**
 * URL verso cui reindirizzare con 301, se la richiesta contiene forme non canoniche.
 *
 * Si interviene SOLO su `page=1` e sui parametri noti con valore vuoto — cioe' su
 * quello che produce il form quando l'utente lascia un select su "Tutte". I parametri
 * sconosciuti (utm_source, fbclid) vengono ignorati e NON causano redirect: farli
 * sparire romperebbe il tracciamento delle campagne.
 */
export function normalizzazioneRichiesta(url: URL, def: DefLista, valori: Valori, pagina: number): string | null {
  const paginaDaPulire = url.searchParams.get('page') !== null && pagina === 1;
  const vuotiDaPulire = def.parametri.some((p) =>
    url.searchParams.getAll(p.nome).some((v) => v === '') ||
    (!p.multiplo && url.searchParams.getAll(p.nome).length > 1),
  );
  if (!paginaDaPulire && !vuotiDaPulire) return null;

  // Si conservano gli altri parametri (utm_*, fbclid) cosi' come sono arrivati.
  const estranei = new URLSearchParams();
  const noti = new Set(def.parametri.map((p) => p.nome));
  for (const [k, v] of url.searchParams) if (!noti.has(k) && k !== 'page') estranei.append(k, v);

  const canonica = serializzaQuery(def, valori, pagina);
  const coda = estranei.toString();
  if (!coda) return `${def.base}${canonica}`;
  return `${def.base}${canonica ? `${canonica}&${coda}` : `?${coda}`}`;
}

/**
 * Se e' attiva UNA sola dimensione promuovibile (nessuna ricerca testuale, pagina 1),
 * restituisce la coppia dimensione/slug per cui esiste un URL statico equivalente.
 * Serve a mandare `?regione=Marche` su `/interpelli/regione/marche` con un 302.
 */
export function dimensioneUnica(def: DefLista, valori: Valori, pagina: number): { dimensione: string; slug: string } | null {
  if (pagina !== 1) return null;
  if (def.parametroRicerca && (valori[def.parametroRicerca]?.length ?? 0) > 0) return null;

  const attivi = def.parametri.filter((p) => (valori[p.nome]?.length ?? 0) > 0);
  if (attivi.length !== 1) return null;

  const p = attivi[0];
  if (!p.dimensione) return null;
  const vals = valori[p.nome];
  if (vals.length !== 1) return null;

  return { dimensione: p.dimensione, slug: slugValore(p.dimensione, vals[0]) };
}

/** Slug del valore di un filtro. Per le regioni passa dal registro, non dallo slugify. */
export function slugValore(dimensione: string, valore: string): string {
  if (dimensione === 'regione') {
    const reg = regionePerValore(valore);
    if (reg) return reg.slug;
  }
  return slugifica(valore);
}

export interface SeoLista {
  canonical: string;
  robots?: string;
}

/**
 * Canonical e direttive di indicizzazione della pagina elenco.
 *
 * Il canonical e' SEMPRE su se stessa. Un `noindex` accompagnato da un canonical che
 * punta altrove fa propagare il noindex al bersaglio: canonicalizzare `?q=dsga` verso
 * /interpelli rischierebbe di far uscire dall'indice /interpelli. L'equivalente
 * indicizzabile di una combinazione di filtri e' la pagina statica, raggiunta con un
 * 302 prima ancora di renderizzare.
 */
export function seoLista(def: DefLista, valori: Valori, pagina: number): SeoLista {
  return {
    canonical: urlAssoluta(def, valori, pagina),
    robots: filtriAttivi(valori) > 0 ? 'noindex, follow' : undefined,
  };
}
