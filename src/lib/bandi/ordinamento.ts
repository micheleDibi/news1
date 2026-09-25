/**
 * Ordinamento della lista bandi (`?ordina=`).
 *
 * «Scadenza più vicina», il predefinito del design, non e' un ordine su una
 * colonna sola: un `data_scadenza asc` puro metterebbe in pagina 1 i bandi
 * chiusi da anni. La lista si legge quindi in tre segmenti consecutivi:
 *   1. scadenza da oggi in avanti, la piu' vicina prima;
 *   2. senza scadenza (spesso «a sportello», aperti fino a esaurimento);
 *   3. gia' scaduti, i piu' recenti prima.
 * PostgREST non sa ordinare per segmento, quindi si conta ogni segmento e si
 * chiede a ciascuno solo il tratto che cade nella pagina: `pianoPagina` fa
 * questo conto, qui dove e' testabile.
 *
 * Modulo «foglia»: nessun import impuro.
 */

/** Valori ammessi di `?ordina=`; l'assenza vale «Scadenza più vicina». */
export const ORDINAMENTI = ['importo', 'recenti'] as const;
export type Ordinamento = 'scadenza' | typeof ORDINAMENTI[number];

/** Voci del select «Ordina per», nell'ordine del design. */
export const VOCI_ORDINA: ReadonlyArray<{ valore: string; etichetta: string }> = [
  { valore: '', etichetta: 'Scadenza più vicina' },
  { valore: 'importo', etichetta: 'Importo più alto' },
  { valore: 'recenti', etichetta: 'Più recenti' },
];

/** Ordinamento effettivo da `?ordina=`: un valore ignoto vale il predefinito. */
export function ordinamentoDa(valore: string | undefined): Ordinamento {
  return valore === 'importo' || valore === 'recenti' ? valore : 'scadenza';
}

export interface Tratto {
  /** Indice del segmento (0, 1, 2…). */
  segmento: number;
  /** Estremi inclusivi, relativi all'inizio del segmento: vanno in `.range(da, a)`. */
  da: number;
  a: number;
}

/**
 * I tratti di ciascun segmento che cadono nell'intervallo globale [da, a]
 * (estremi inclusivi, come `.range()`), nell'ordine dei segmenti. I segmenti
 * vuoti o fuori pagina non compaiono.
 */
export function pianoPagina(da: number, a: number, dimensioni: readonly number[]): Tratto[] {
  const tratti: Tratto[] = [];
  if (a < da) return tratti;
  let inizio = 0;
  dimensioni.forEach((n, segmento) => {
    const fine = inizio + Math.max(0, n) - 1;
    const primo = Math.max(da, inizio);
    const ultimo = Math.min(a, fine);
    if (n > 0 && primo <= ultimo) tratti.push({ segmento, da: primo - inizio, a: ultimo - inizio });
    inizio += Math.max(0, n);
  });
  return tratti;
}
