/**
 * Risposta di /api/indexnow-key: dice solo se la chiave IndexNow e' configurata,
 * senza mai rivelarla. Chi deve leggere la chiave (i motori di ricerca, secondo il
 * protocollo IndexNow) la trova in /<chiave>.txt, che la restituisce solo a chi la
 * conosce gia'.
 *
 * Funzione pura, senza accesso a import.meta.env: cosi' la logica e' testabile con
 * node --test fuori da Astro (in Node `import.meta.env` e' undefined).
 */

const INTESTAZIONI = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Cache-Control': 'no-store',
} as const;

/**
 * 200 con corpo fisso `ok` se la chiave e' configurata (stringa non vuota),
 * 404 con «IndexNow key not configured» altrimenti. Mai la chiave nel corpo.
 */
export function rispostaStatoChiave(chiave: string | null | undefined): Response {
  if (!chiave) {
    return new Response('IndexNow key not configured', { status: 404, headers: INTESTAZIONI });
  }
  return new Response('ok', { status: 200, headers: INTESTAZIONI });
}
