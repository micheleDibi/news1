import { generateBreadcrumbStructuredData, generateItemListStructuredData } from '../seo';

/**
 * Dati strutturati e rel prev/next di una pagina filtro (/interpelli/regione/…,
 * /bandi/programma/…). Stavano scritti in PaginaFiltro.astro; ora li usano anche
 * le pagine filtro dei bandi, che hanno un guscio loro: un posto solo, cosi' le
 * due strade non possono divergere.
 */
export interface DatiFiltro {
  /** Nome e percorso della sezione nel breadcrumb (es. «Interpelli Scuola», «/interpelli»). */
  etichettaSezione: string;
  basePathSezione: string;
  /** Nome della pagina corrente nel breadcrumb. */
  etichettaCorrente: string;
  /** Percorso della pagina 1, senza query. */
  base: string;
  pagina: number;
  pagine: number;
  perPagina: number;
  /** Nome dell'ItemList (l'H1) e URL canonico. */
  nome: string;
  canonical: string;
  itemList: Array<{ href: string; title: string }>;
}

export interface StrutturaFiltro {
  breadcrumb: string;
  itemList: string | null;
  hrefPrec: string | null;
  hrefSucc: string | null;
}

export function datiStrutturatiFiltro(d: DatiFiltro): StrutturaFiltro {
  const breadcrumb = generateBreadcrumbStructuredData(
    { category: d.etichettaSezione, category_slug: d.basePathSezione.replace(/^\//, '') },
    { nome: d.etichettaCorrente, url: `https://edunews24.it${d.base}` },
  );
  // Le posizioni dell'ItemList proseguono da una pagina all'altra invece di ripartire da 1.
  const posizioneIniziale = (d.pagina - 1) * d.perPagina + 1;
  const itemList = d.itemList.length > 0
    ? generateItemListStructuredData(d.itemList, d.nome, d.canonical, posizioneIniziale)
    : null;
  // rel prev/next: Google non li usa piu' come segnale di paginazione, Bing si'.
  const hrefPrec = d.pagina > 2 ? `${d.base}?page=${d.pagina - 1}` : d.pagina === 2 ? d.base : null;
  const hrefSucc = d.pagina < d.pagine ? `${d.base}?page=${d.pagina + 1}` : null;
  return { breadcrumb, itemList, hrefPrec, hrefSucc };
}
