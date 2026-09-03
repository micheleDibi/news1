/**
 * Slug per i segmenti URL delle pagine filtro.
 *
 * NON usare slugify() di src/lib/utils.ts: quella non decompone gli accenti
 * (`citta'` diventa "citt"), mangia gli apostrofi ("Valle d'Aosta" diventa
 * "valle daosta") e non gestisce lo slash ("Scelta PA/sede").
 */
export function slugifica(testo: string): string {
  return testo
    .normalize('NFD')                      // "e'" -> "e" + segno diacritico
    .replace(/[\u0300-\u036f]/g, '')       // via i diacritici combinanti
    .replace(/[\u2019'`\u00b4]/g, ' ')     // apostrofo tipografico e dritto -> separatore
    .replace(/[\/\\]/g, ' ')               // slash -> separatore
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');              // gli spazi finali del DB spariscono qui
}

/** Un segmento URL valido: minuscolo, cifre e trattini singoli. */
export const SLUG_VALIDO = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function slugValido(s: string | undefined | null): boolean {
  return typeof s === 'string' && SLUG_VALIDO.test(s);
}
