/**
 * Host e denylist degli aggregatori: l'unico punto che decide se un URL può
 * comparire in una superficie pubblica.
 *
 * Il problema che risolve: l'80% del corpus arriva da un aggregatore, e oggi
 * 94 CTA su 230 e 115 schede portano lì. Un link a un aggregatore presentato
 * come «pagina ufficiale» è un errore editoriale prima che un problema SEO,
 * e `escapeAttr` (l'unica difesa precedente) non fermava nemmeno `javascript:`.
 *
 * Modulo «foglia»: nessun import impuro, nessuna variabile d'ambiente.
 */
import { DOMINI_AGGREGATORI } from '../../config/domini-aggregatori';

/**
 * Host di un URL: minuscolo, senza `www.` iniziale, senza punto finale.
 * `null` se la stringa non è un URL assoluto analizzabile.
 *
 * Il `www.` si toglie perché è l'unica etichetta che non distingue un sito da
 * un altro: `format: 'hostname'` dell'API promette la stessa forma.
 */
export function hostDi(url: string | null | undefined): string | null {
  if (typeof url !== 'string' || url.trim() === '') return null;
  let analizzato: URL;
  try {
    analizzato = new URL(url.trim());
  } catch {
    return null;
  }
  const host = analizzato.hostname.toLowerCase().replace(/\.$/, '');
  if (host === '') return null;
  return host.startsWith('www.') ? host.slice(4) : host;
}

/**
 * L'host è in denylist? Il confronto è per **etichette**, non per sottostringa:
 * `bandi.it` copre `www.bandi.it` e `api.bandi.it`, mai `contributibandi.it`.
 * Accetta sia un host già normalizzato sia uno con `www.` o maiuscole.
 */
export function eAggregatore(host: string | null | undefined): boolean {
  if (typeof host !== 'string') return false;
  const pulito = host.trim().toLowerCase().replace(/\.$/, '');
  if (pulito === '') return false;
  const senzaWww = pulito.startsWith('www.') ? pulito.slice(4) : pulito;
  for (const vietato of DOMINI_AGGREGATORI) {
    if (senzaWww === vietato || senzaWww.endsWith(`.${vietato}`)) return true;
  }
  return false;
}

/**
 * L'URL può essere reso come link in una pagina pubblica?
 *
 * Tre condizioni, tutte necessarie:
 *  1. schema `http:` o `https:` — chiude `javascript:`, `data:`, `mailto:` e
 *     ogni altro schema che l'escape dell'attributo non filtrava;
 *  2. un host analizzabile;
 *  3. host fuori dalla denylist.
 *
 * È la cintura su **ogni** URL in uscita, non la sola guardia: i link
 * pubblicabili li decide il produttore (`bando_link.pubblicabile`), questa
 * funzione impedisce che un errore a monte diventi un link in pagina.
 */
export function urlPubblicabile(url: string | null | undefined): boolean {
  if (typeof url !== 'string' || url.trim() === '') return false;
  let analizzato: URL;
  try {
    analizzato = new URL(url.trim());
  } catch {
    return false;
  }
  if (analizzato.protocol !== 'http:' && analizzato.protocol !== 'https:') return false;
  const host = hostDi(url);
  if (host === null) return false;
  return !eAggregatore(host);
}

/** Gli URL di un elenco che si possono rendere, nell'ordine di partenza. */
export function soloPubblicabili<T>(
  voci: readonly T[] | null | undefined,
  urlDi: (voce: T) => string | null | undefined,
): T[] {
  if (!Array.isArray(voci)) return [];
  return voci.filter((voce) => urlPubblicabile(urlDi(voce)));
}
