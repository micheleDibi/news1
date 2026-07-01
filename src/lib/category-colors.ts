// Single source of truth per i colori di categoria del sito.
//
// Il DB `categories.color` memorizza un NOME (es. 'scuola', 'sport-500'), NON
// un hex. Questo file mappa quei nomi ai loro valori hex correnti. Tutti i
// colorHexMap che circolavano nel codice (linkinbio, admin, amp, ecc.)
// importano da qui — nessun hex categoria va più hardcoded altrove.
//
// Chiavi speciali:
//   - 'sport-500' e 'breaking' sono colori BRAND, non categorie DB.
//   - 'interpelli' e 'selezione-personale' sono sezioni standalone (pagine
//     dedicate senza record in categories), inclusi qui per uniformità.
//   - 'red-500' | 'blue-500' | 'green-500' restano disponibili come colori
//     generici nel picker admin.

export const CATEGORY_COLORS: Record<string, string> = {
  scuola: '#2D6A4F',
  universita: '#1B3A7B',
  ricerca: '#0891B2',
  mondo: '#7C3AED',
  formazione: '#EA580C',
  editoriali: '#1E293B',
  cultura: '#B45309',
  lavoro: '#0D9488',
  tecnologia: '#2563EB',
  bandi: '#795548',
  interpelli: '#DC2626',
  'selezione-personale': '#CA8A04',
  'sport-500': '#004e9c',
  breaking: '#cc0000',
  'red-500': '#ef4444',
  'blue-500': '#3b82f6',
  'green-500': '#22c55e',
};

export const BRAND_PRIMARY = '#004e9c';

export function getCategoryHex(key: string | null | undefined, fallback: string = BRAND_PRIMARY): string {
  if (!key) return fallback;
  if (CATEGORY_COLORS[key]) return CATEGORY_COLORS[key];
  if (/^#[0-9A-Fa-f]{6}$/.test(key)) return key;
  return fallback;
}
