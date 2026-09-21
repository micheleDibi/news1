/**
 * Stato editoriale dei bandi e data odierna a Roma: logica pura.
 *
 * Estratta da supabase-bandi.ts, che crea il client Supabase quando viene
 * importato e quindi non si puo' caricare sotto `node --test`. supabase-bandi.ts
 * la ri-esporta: i chiamanti esistenti non cambiano e il comportamento e'
 * identico (i parametri aggiunti sono facoltativi e servono solo ai test e
 * all'API /api/v1, che fissa "oggi" una volta per richiesta).
 */

// Stato editoriale del bando (data-driven dal preprocess v2).
export const STATI_BANDO = ['aperto', 'chiuso', 'in apertura prossimamente'] as const;
export type StatoBando = typeof STATI_BANDO[number];

/**
 * Data odierna (YYYY-MM-DD) nel fuso Europe/Rome, indipendente dal timezone
 * del server/browser. 'en-CA' formatta come ISO date.
 */
export function todayRomeISO(adesso: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Rome' }).format(adesso);
}

/**
 * Stato EFFETTIVO del bando da mostrare all'utente. La colonna `stato_bando`
 * viene scritta dal preprocess dello scraper e mai piu' aggiornata: un bando
 * con scadenza passata resterebbe "aperto" per sempre. Regola: se la
 * scadenza e' passata il bando e' 'chiuso' (dal giorno successivo alla
 * scadenza — il giorno stesso e' ancora valido), qualunque sia lo stato
 * salvato; la scadenza puo' solo chiudere, mai riaprire.
 */
export function effectiveStatoBando(
  stato: StatoBando | null | undefined,
  dataScadenza: string | null | undefined,
  oggi: string = todayRomeISO(),
): StatoBando | null {
  if (dataScadenza && String(dataScadenza).slice(0, 10) < oggi) return 'chiuso';
  return stato ?? null;
}
