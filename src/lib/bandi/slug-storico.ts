/**
 * Che cosa risponde `/bandi/<slug>` quando lo slug non corrisponde a nessuna
 * riga visibile: 200, 301, 410, 404 o 503.
 *
 * La regola che questo modulo protegge (§16.2 M18) è controintuitiva e vale la
 * pena scriverla per esteso: **301 e 410 si emettono solo su una lettura
 * riuscita**. Oggi la scheda avvolge la query in un `try/catch` e risponde 404
 * a qualunque cosa: un timeout di PostgREST (anon ha 3 s di
 * `statement_timeout`) o un errore di rete diventano un 404, e un 404 ripetuto
 * fa deindicizzare la pagina. Un 503 con `Retry-After` invece non toglie niente
 * dall'indice, e per questo **non** porta `noindex`: sarebbe l'unico modo di
 * trasformare un guasto temporaneo in un danno permanente.
 *
 * Nessuna catena: se lo slug storico punta a un master che a sua volta non è
 * visibile, si risponde 410 e non si va a cercare il master del master.
 *
 * In F1 la mappa degli slug storici non esiste ancora (la creano le migrazioni
 * 02-05): il chiamante passa `{stato: 'non_eseguita'}` e il comportamento è
 * quello di oggi, 404, ma passando dalla stessa funzione.
 *
 * Modulo «foglia»: nessun import, nessun I/O. Le letture le fa il chiamante.
 */

/** Esito di una lettura su PostgREST, come lo vede il chiamante. */
export type Lettura<T> =
  | { readonly stato: 'ok'; readonly riga: T | null }
  | { readonly stato: 'errore' }
  | { readonly stato: 'non_eseguita' };

/**
 * Riga di `bando_slug_storico` già risolta dal chiamante:
 *  - `esito` è la colonna omonima (`301`, `410`, `annullato`);
 *  - `slugMaster` è lo slug **attualmente visibile** del bando di destinazione,
 *    oppure null se quel bando non è (più) pubblicato.
 */
export interface RigaSlugStorico {
  readonly esito: string | null;
  readonly slugMaster: string | null;
}

export interface LettureSlug {
  /** La scheda con lo slug richiesto. */
  readonly scheda: Lettura<unknown>;
  /** La mappa degli slug storici e delle fusioni; `non_eseguita` in F1. */
  readonly storico: Lettura<RigaSlugStorico>;
}

export type EsitoSlug =
  | { readonly stato: 200 }
  | { readonly stato: 301; readonly destinazione: string }
  | { readonly stato: 410 }
  | { readonly stato: 404 }
  | { readonly stato: 503; readonly ritentaDopoSecondi: number };

/** Secondi di `Retry-After` su un guasto di lettura: un giro di cron è 65'. */
export const RITENTA_DOPO_SECONDI = 60;

const ERRORE: EsitoSlug = { stato: 503, ritentaDopoSecondi: RITENTA_DOPO_SECONDI };

/**
 * Decide l'esito. Ordine: prima gli errori (503), poi la riga trovata (200),
 * poi la mappa storica (301/410), infine 404.
 */
export function esitoSlug(letture: LettureSlug): EsitoSlug {
  if (letture.scheda.stato === 'errore') return ERRORE;
  // `non_eseguita` sulla scheda non ha senso: senza quella lettura non c'è
  // niente da decidere, e un 404 «per omissione» è esattamente il bug da
  // chiudere. Meglio un 503, che è reversibile.
  if (letture.scheda.stato === 'non_eseguita') return ERRORE;
  if (letture.scheda.riga !== null && letture.scheda.riga !== undefined) return { stato: 200 };

  if (letture.storico.stato === 'errore') return ERRORE;
  if (letture.storico.stato === 'non_eseguita') return { stato: 404 };

  const riga = letture.storico.riga;
  if (riga === null) return { stato: 404 };

  // `annullato`: la riga è stata revocata a mano e non vale più niente. Uno
  // slug così torna a essere semplicemente ignoto.
  if (riga.esito === 'annullato') return { stato: 404 };
  if (riga.esito === '410') return { stato: 410 };

  if (riga.esito === '301') {
    const master = typeof riga.slugMaster === 'string' ? riga.slugMaster.trim() : '';
    // Destinazione non visibile: 410, mai un 301 verso un 404.
    if (master === '') return { stato: 410 };
    return { stato: 301, destinazione: `/bandi/${master}` };
  }

  // Esito sconosciuto o assente: il contenuto non c'è più, ma non sappiamo
  // dove sia andato. 410 è l'informazione vera.
  return { stato: 410 };
}
