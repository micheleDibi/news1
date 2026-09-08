/**
 * Unicita' dello slug degli articoli.
 *
 * Serve perche' `src/pages/[category]/[slug].astro` usa `.single()` due
 * volte: se due articoli condividono lo stesso slug, Supabase restituisce un
 * errore e la rotta risponde 410 su un articolo che invece esiste. Il
 * fallback a `[slug].astro:26-31` interroga per solo slug, senza categoria,
 * quindi il controllo deve essere GLOBALE, non per categoria.
 */
import { supabase } from './supabase';
import { slugifica, slugValido } from './slug';

const MAX_TENTATIVI = 20;

/** True se lo slug e' gia' usato da un articolo diverso da `escludiId`. */
export async function slugOccupato(
  slug: string,
  escludiId?: string | number | null
): Promise<boolean> {
  let query = supabase.from('articles').select('id').eq('slug', slug).limit(1);
  if (escludiId !== undefined && escludiId !== null) {
    query = query.neq('id', escludiId);
  }
  const { data, error } = await query;
  if (error) {
    // In caso di errore si preferisce bloccare: meglio un salvataggio in
    // meno che due articoli sullo stesso URL.
    throw error;
  }
  return Array.isArray(data) && data.length > 0;
}

/**
 * Restituisce `base` se libero, altrimenti `base-2`, `base-3`, ... fino a
 * MAX_TENTATIVI. null se non si trova nulla di libero.
 */
export async function trovaSlugLibero(
  base: string,
  escludiId?: string | number | null
): Promise<string | null> {
  for (let tentativo = 1; tentativo <= MAX_TENTATIVI; tentativo++) {
    const candidato = tentativo === 1 ? base : `${base}-${tentativo}`;
    if (!(await slugOccupato(candidato, escludiId))) return candidato;
  }
  return null;
}

/**
 * Slug da usare alla CREAZIONE di un articolo: quello proposto se conforme,
 * altrimenti generato dal titolo con `slugifica()` (accent-safe: "Perche'"
 * e "Perché" danno entrambi "perche", quindi correggere un accento nel
 * titolo non puo' cambiare l'URL).
 */
export function slugDaTitolo(
  slugProposto: unknown,
  titolo: unknown
): string | null {
  if (typeof slugProposto === 'string' && slugValido(slugProposto)) {
    return slugProposto;
  }
  const generato = slugifica(typeof titolo === 'string' ? titolo : '');
  return slugValido(generato) ? generato : null;
}
