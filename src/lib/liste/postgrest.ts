/**
 * Aiuti per comporre i filtri PostgREST delle liste.
 */

/**
 * Ripulisce il termine di ricerca dai metacaratteri dell'albero logico di PostgREST.
 * Oggi il termine viene interpolato grezzo dentro `or=(...)`: basta una virgola o una
 * parentesi per ottenere un 400 PGRST100 e una lista vuota senza spiegazioni.
 */
export function sanitizzaRicerca(testo: string): string {
  return testo
    .replace(/[(),*:"'\\]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80);
}

/** 'article_title.ilike.*x*,interpello_name.ilike.*x*' da passare a .or(). */
export function orIlike(colonne: string[], termine: string): string {
  return colonne.map((c) => `${c}.ilike.*${termine}*`).join(',');
}
