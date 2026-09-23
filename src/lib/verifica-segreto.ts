/**
 * Verifica del segreto condiviso degli endpoint interni (`Authorization: Bearer <chiave>`),
 * ad esempio /api/indexnow-notify.
 *
 * Fail-closed: se il segreto atteso non e' configurato (variabile d'ambiente assente o
 * vuota) nessuna richiesta e' autorizzata. Il confronto storico
 * `chiave !== import.meta.env.API_SECRET_KEY` con la variabile assente dava
 * `undefined !== undefined` = false, cioe' lasciava passare chiunque (fix 8.a.25).
 *
 * Funzione pura, senza accesso a import.meta.env: cosi' la logica e' testabile con
 * node --test fuori da Astro (in Node `import.meta.env` e' undefined).
 */

/**
 * True solo se il segreto e' configurato (stringa non vuota) e la chiave ricevuta
 * coincide esattamente con esso. Chiave assente o segreto assente → false.
 */
export function segretoValido(
  chiaveRicevuta: string | null | undefined,
  segretoAtteso: string | null | undefined,
): boolean {
  if (!segretoAtteso) return false;
  return chiaveRicevuta === segretoAtteso;
}
