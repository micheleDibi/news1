/**
 * Slug canonico di un interpello: logica pura.
 *
 * Lo slug NON e' salvato a DB: si ricalcola da interpello_name + provincia|citta +
 * regione + id. Estratto da liste/interpelli.ts (che importa il client Supabase e
 * il corpus, quindi non si carica sotto `node --test`); quel modulo lo ri-esporta
 * e i chiamanti non cambiano.
 *
 * GEMELLO PYTHON: `_generate_interpello_slug` in backend/app/interpelli.py. Le due
 * funzioni devono restare identiche nel comportamento: gli URL delle schede sono
 * indicizzati. La parita' e' verificata da tests/estrazioni/slug-interpello.test.ts.
 */
export interface CampiSlugInterpello {
  id: number;
  interpello_name?: string | null;
  interpello_provincia?: string | null;
  interpello_citta?: string | null;
  interpello_regione?: string | null;
}

export function slugInterpello(interpello: CampiSlugInterpello): string {
  const parts = [
    interpello.interpello_name,
    interpello.interpello_provincia || interpello.interpello_citta,
    interpello.interpello_regione,
    interpello.id?.toString(),
  ].filter(Boolean);

  return parts
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9\-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}
