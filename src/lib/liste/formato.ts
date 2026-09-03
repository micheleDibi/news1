import { format, parseISO, isValid } from 'date-fns';
import { it } from 'date-fns/locale';

/**
 * Formattazione date delle liste. Le tre sezioni usano tre formati e tre fallback
 * diversi: sono tenuti distinti di proposito, per non cambiare l'aspetto delle card
 * mentre si estrae il markup in componenti.
 */

/** Interpelli: "03 settembre 2026". */
export function formatDataEstesa(dateString: string): string {
  try {
    const parsedDate = parseISO(dateString);
    if (!isValid(parsedDate)) return 'Data non valida';
    return format(parsedDate, 'dd MMMM yyyy', { locale: it });
  } catch {
    return 'Data non valida';
  }
}

/** Selezione personale: "03 set 2026". */
export function formatDataBreve(dateString: string): string {
  try {
    const parsedDate = parseISO(dateString);
    if (!isValid(parsedDate)) return 'Data non valida';
    return format(parsedDate, 'dd MMM yyyy', { locale: it });
  } catch {
    return 'Data non valida';
  }
}

/** Bandi: "3 settembre 2026"; null diventa un trattino, una data illeggibile resta grezza. */
export function formatDataBando(s: string | null | undefined): string {
  if (!s) return '—';
  try {
    const d = parseISO(s);
    if (!isValid(d)) return s;
    return format(d, 'd MMMM yyyy', { locale: it });
  } catch {
    return s;
  }
}

/** Importo in euro senza decimali, come nelle card dei bandi. */
export function formatImportoEuro(n: number | null | undefined): string {
  if (n == null) return '—';
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(n);
}
