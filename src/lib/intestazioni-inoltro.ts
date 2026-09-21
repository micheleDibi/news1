/**
 * Guardia sugli header di inoltro (X-Forwarded-Host/Proto/Port e Host).
 *
 * Astro 5.4.2 costruisce request.url concatenando questi header senza validarli
 * (node_modules/astro/dist/core/app/node.js, createRequest) e instrada su quell'URL.
 * Un valore come `X-Forwarded-Host: edunews24.it/api/interpelli?` fa servire un'altra
 * rotta sotto il path richiesto: con una cache davanti (Cloudflare) e' cache
 * poisoning. Il middleware rifiuta con 400 le richieste i cui header non hanno la
 * forma attesa. Solo sintassi: nessun elenco di host, nessuna dipendenza dal DB.
 *
 * Il rimedio definitivo e' l'aggiornamento di Astro; questa guardia resta comunque.
 */

/** Autorita' `host[:porta]`: nome DNS (anche con `_` e punto finale) o IPv6 fra quadre. */
const AUTORITA = /^(?:(?:[A-Za-z0-9_-]{1,63}\.)*[A-Za-z0-9_-]{1,63}\.?|\[[0-9A-Fa-f:.]{2,45}\])(?::\d{1,5})?$/;
const PROTOCOLLO = /^https?$/;
const PORTA = /^\d{1,5}$/;
const LUNGHEZZA_MASSIMA = 255;

export type IntestazioneRifiutata = 'x-forwarded-host' | 'x-forwarded-proto' | 'x-forwarded-port' | 'host';

interface LettoreIntestazioni {
  get(nome: string): string | null;
}

/** Ogni valore separato da virgola, senza spazi ai bordi, deve rispettare `forma`. */
function valoriConformi(grezzo: string, forma: RegExp): boolean {
  if (grezzo.length > LUNGHEZZA_MASSIMA) return false;
  return grezzo.split(',').every((valore) => forma.test(valore.trim()));
}

/**
 * Restituisce null se gli header sono accettabili, altrimenti il nome del primo
 * header malformato. Un header presente ma vuoto conta come malformato: Astro lo
 * userebbe cosi' com'e' (`https:///percorso` sposta il path nell'host).
 */
export function verificaIntestazioniInoltro(intestazioni: LettoreIntestazioni): IntestazioneRifiutata | null {
  const host = intestazioni.get('x-forwarded-host');
  if (host !== null && !valoriConformi(host, AUTORITA)) return 'x-forwarded-host';

  const protocollo = intestazioni.get('x-forwarded-proto');
  if (protocollo !== null && !valoriConformi(protocollo, PROTOCOLLO)) return 'x-forwarded-proto';

  const porta = intestazioni.get('x-forwarded-port');
  if (porta !== null && !valoriConformi(porta, PORTA)) return 'x-forwarded-port';

  // Host conta solo quando manca X-Forwarded-Host (e' il ripiego di Astro).
  if (host === null) {
    const hostDiretto = intestazioni.get('host');
    if (hostDiretto !== null && !valoriConformi(hostDiretto, AUTORITA)) return 'host';
  }
  return null;
}
