import { slugifica } from './slug';

/**
 * Registro delle 20 regioni italiane: e' l'unica autorita' sugli slug regionali.
 *
 * Serve perche' le tre fonti scrivono gli stessi nomi in modo diverso:
 *   interpelli.interpello_regione  "Emilia-Romagna" (79 righe) e "Emilia Romagna" (4)
 *   selezione_personale.sedi[]     "Emilia Romagna", "Trentino Alto Adige", "Valle d'Aosta"
 *   bandi.regioni.nome             "Emilia-Romagna", "Trentino-Alto Adige/Sudtirol",
 *                                  "Valle d'Aosta/Vallee d'Aoste"
 * Lo slug NON si ricava slugificando il nome DB: "Valle d'Aosta/Vallee d'Aoste"
 * produrrebbe "valle-d-aosta-vallee-d-aoste". Gli slug qui sotto coincidono con la
 * colonna regioni.slug del DB bandi, che e' gia' nella forma pulita.
 *
 * ATTENZIONE: uno slug pubblicato non va piu' cambiato, diventerebbe un 404 su URL
 * gia' indicizzati.
 */
export interface Regione {
  /** Segmento URL definitivo. */
  slug: string;
  /** Forma canonica mostrata a video. */
  nome: string;
  /** Forma preposizionale per i testi generati: "nel Lazio", "nelle Marche". */
  inRegione: string;
  /** Tutte le grafie viste nei due database. */
  varianti: string[];
}

export const REGIONI: readonly Regione[] = [
  { slug: 'abruzzo', nome: 'Abruzzo', inRegione: 'in Abruzzo', varianti: ['Abruzzo'] },
  { slug: 'basilicata', nome: 'Basilicata', inRegione: 'in Basilicata', varianti: ['Basilicata'] },
  { slug: 'calabria', nome: 'Calabria', inRegione: 'in Calabria', varianti: ['Calabria'] },
  { slug: 'campania', nome: 'Campania', inRegione: 'in Campania', varianti: ['Campania'] },
  { slug: 'emilia-romagna', nome: 'Emilia-Romagna', inRegione: 'in Emilia-Romagna',
    varianti: ['Emilia-Romagna', 'Emilia Romagna'] },
  { slug: 'friuli-venezia-giulia', nome: 'Friuli-Venezia Giulia', inRegione: 'in Friuli-Venezia Giulia',
    varianti: ['Friuli-Venezia Giulia', 'Friuli Venezia Giulia'] },
  { slug: 'lazio', nome: 'Lazio', inRegione: 'nel Lazio', varianti: ['Lazio'] },
  { slug: 'liguria', nome: 'Liguria', inRegione: 'in Liguria', varianti: ['Liguria'] },
  { slug: 'lombardia', nome: 'Lombardia', inRegione: 'in Lombardia', varianti: ['Lombardia'] },
  { slug: 'marche', nome: 'Marche', inRegione: 'nelle Marche', varianti: ['Marche'] },
  { slug: 'molise', nome: 'Molise', inRegione: 'in Molise', varianti: ['Molise'] },
  { slug: 'piemonte', nome: 'Piemonte', inRegione: 'in Piemonte', varianti: ['Piemonte'] },
  { slug: 'puglia', nome: 'Puglia', inRegione: 'in Puglia', varianti: ['Puglia'] },
  { slug: 'sardegna', nome: 'Sardegna', inRegione: 'in Sardegna', varianti: ['Sardegna'] },
  { slug: 'sicilia', nome: 'Sicilia', inRegione: 'in Sicilia', varianti: ['Sicilia'] },
  { slug: 'toscana', nome: 'Toscana', inRegione: 'in Toscana', varianti: ['Toscana'] },
  { slug: 'trentino-alto-adige', nome: 'Trentino-Alto Adige', inRegione: 'in Trentino-Alto Adige',
    varianti: ['Trentino-Alto Adige', 'Trentino Alto Adige', 'Trentino-Alto Adige/Südtirol', 'Trentino-Alto Adige/Sudtirol'] },
  { slug: 'umbria', nome: 'Umbria', inRegione: 'in Umbria', varianti: ['Umbria'] },
  { slug: 'valle-d-aosta', nome: "Valle d'Aosta", inRegione: "in Valle d'Aosta",
    varianti: ["Valle d'Aosta", "Valle d’Aosta", "Valle d'Aosta/Vallée d'Aoste", "Valle d'Aosta/Vallee d'Aoste"] },
  { slug: 'veneto', nome: 'Veneto', inRegione: 'in Veneto', varianti: ['Veneto'] },
];

const perSlug = new Map(REGIONI.map((r) => [r.slug, r]));

/** Match su tutte le grafie note, piu' una rete di sicurezza sullo slug. */
const perValore = new Map<string, Regione>();
for (const r of REGIONI) {
  for (const v of r.varianti) {
    perValore.set(v, r);
    perValore.set(slugifica(v), r);
  }
  perValore.set(r.slug, r);
}

export function regionePerSlug(slug: string): Regione | null {
  return perSlug.get(slug) ?? null;
}

/** Riconosce un valore DB in qualunque grafia; null se non e' una regione. */
export function regionePerValore(valore: string | null | undefined): Regione | null {
  if (!valore) return null;
  return perValore.get(valore) ?? perValore.get(slugifica(valore)) ?? null;
}
