/**
 * Da riferimento validato delle categorie a CategoriaDto[] (piano §3.8).
 *
 * Nessuna lettura: il riferimento e' gia' validato e ordinato (position asc con i
 * null in fondo, poi slug) e le secondarie sono gia' ordinate per nome. Oggetti
 * costruiti campo per campo nell'ordine del contratto; URL assoluti.
 */
import { urlApi } from './url';
import type { CategoriaDto, RiferimentoCategorie } from './contratto';

export function mappaCategorie(rif: RiferimentoCategorie): CategoriaDto[] {
  return rif.ordinate.map((categoria): CategoriaDto => ({
    slug: categoria.slug,
    name: categoria.name,
    color: categoria.color,
    position: categoria.position,
    url: categoria.url,
    secondary_categories: (rif.secondariePerParent.get(categoria.slug) ?? []).map((s) => ({ slug: s.slug, name: s.name })),
    links: {
      articles: urlApi('/articles', new URLSearchParams({ category: categoria.slug })),
      feed_json: urlApi(`/feeds/articles/${categoria.slug}.json`),
      feed_rss: urlApi(`/feeds/articles/${categoria.slug}.xml`),
    },
  }));
}
