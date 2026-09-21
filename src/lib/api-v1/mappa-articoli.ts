/**
 * Da riga `articles` a ArticoloDto (piano §3.6 e §3.7).
 *
 * L'oggetto e' costruito campo per campo nell'ordine del contratto, mai con lo
 * spread della riga: `creator` (nome reale) e le colonne interne non possono uscire.
 * Una riga inservibile (id, slug, categoria, URL o data non validi) da' null: il
 * chiamante la scarta e la registra nel log.
 *
 * Modulo puro: nessun I/O, nessuna dipendenza dal fuso del processo.
 */
import { AUTORE_REDAZIONE, LUNGHEZZA_SINTESI } from './costanti';
import { nomeValido } from './riferimenti';
import { istantePublishedAt, rfc3339Roma } from './tempo';
import { pulisciElenco, pulisciTestoMarkdown, sintesiDaMarkdown } from './testo';
import { mimeVideo, urlArticolo, urlMediaAssoluto } from './url';
import type {
  ArticoloDto, CategoriaSecondariaDto, ProfiloRif, RiferimentoCategorie, RiferimentoProfili, RigaArticolo, VideoDto,
} from './contratto';

export interface ContestoArticoli {
  categorie: RiferimentoCategorie;
  profili: RiferimentoProfili;
}

/** Intero sicuro > 0 da un numero o da una stringa di sole cifre; altrimenti null. */
export function interoPositivo(v: unknown): number | null {
  let n: number;
  if (typeof v === 'number') {
    n = v;
  } else if (typeof v === 'string') {
    const testo = v.trim();
    if (!/^[0-9]{1,16}$/.test(testo)) return null;
    n = Number(testo);
  } else {
    return null;
  }
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

/**
 * Nome dell'autore da mostrare (piano §3.6), come la pagina dell'articolo:
 * 1. `creator` coincide con un id -> quel profilo;
 * 2. altrimenti `creator` cercato fra i full_name: una sola corrispondenza ->
 *    quel profilo; zero o piu' -> nessuno.
 * Il profilo da' il suo nome pubblico solo se e' visualizzabile e il nome
 * ripulito non e' vuoto ed e' di al massimo 80 caratteri; in ogni altro caso
 * "Redazione EduNews24". Mai `creator` ne' `full_name` in uscita.
 */
export function nomeAutore(creator: unknown, profili: RiferimentoProfili): string {
  if (typeof creator !== 'string' || creator === '') return AUTORE_REDAZIONE;
  let profilo: ProfiloRif | null = profili.perId.get(creator) ?? null;
  if (profilo === null) {
    const omonimi = profili.perNomeCompleto.get(creator);
    profilo = omonimi !== undefined && omonimi.length === 1 ? omonimi[0] : null;
  }
  if (profilo === null || !profilo.visualizzabile) return AUTORE_REDAZIONE;
  return nomeValido(profilo.publicName) ?? AUTORE_REDAZIONE;
}

/**
 * Secondarie dell'articolo: quelle del riferimento con parent = categoria
 * principale il cui slug compare in `secondary_category_slugs`, nell'ordine
 * del riferimento (nome, poi slug). Le orfane e gli elementi non stringa spariscono.
 */
function secondarieArticolo(
  slugCategoria: string,
  slugSecondari: unknown,
  categorie: RiferimentoCategorie,
): CategoriaSecondariaDto[] {
  if (!Array.isArray(slugSecondari)) return [];
  const elenco: readonly unknown[] = slugSecondari;
  const richiesti = new Set<string>();
  for (const s of elenco) if (typeof s === 'string') richiesti.add(s);
  if (richiesti.size === 0) return [];
  const esito: CategoriaSecondariaDto[] = [];
  for (const secondaria of categorie.secondariePerParent.get(slugCategoria) ?? []) {
    if (richiesti.has(secondaria.slug)) esito.push({ slug: secondaria.slug, name: secondaria.name });
  }
  return esito;
}

function videoArticolo(riga: RigaArticolo): VideoDto | null {
  const url = urlMediaAssoluto(riga.video_url);
  if (url === null) return null;
  return {
    url,
    mime_type: mimeVideo(url),
    thumbnail_url: urlMediaAssoluto(riga.thumbnail_url) ?? urlMediaAssoluto(riga.image_url),
    duration_seconds: interoPositivo(riga.video_duration),
  };
}

/**
 * ArticoloDto dalla riga, oppure null se la riga va scartata:
 * id non intero positivo, slug assente, categoria fuori dal riferimento (esclude
 * i 9 articoli 'bandi'), URL pubblico non costruibile, `published_at` non riconosciuto.
 */
export function mappaArticolo(riga: RigaArticolo, contesto: ContestoArticoli): ArticoloDto | null {
  const id = riga.id;
  if (typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0) return null;
  if (typeof riga.slug !== 'string') return null;
  const slug = riga.slug.trim();
  if (slug === '') return null;
  if (typeof riga.category_slug !== 'string') return null;
  const categoria = contesto.categorie.perSlug.get(riga.category_slug);
  if (categoria === undefined) return null;
  const url = urlArticolo(riga.category_slug, riga.slug);
  if (url === null) return null;
  const istante = istantePublishedAt(riga.published_at);
  if (istante === null) return null;

  return {
    type: 'article',
    id,
    slug,
    url,
    // Titoli ed excerpt sono scritti in markdown (es. un titolo in **grassetto**).
    title: pulisciTestoMarkdown(riga.title) ?? pulisciTestoMarkdown(riga.title_summary) ?? slug,
    title_summary: pulisciTestoMarkdown(riga.title_summary),
    excerpt: pulisciTestoMarkdown(riga.excerpt),
    summary: sintesiDaMarkdown(riga.summary, LUNGHEZZA_SINTESI),
    category: { slug: categoria.slug, name: categoria.name, color: categoria.color, url: categoria.url },
    secondary_categories: secondarieArticolo(categoria.slug, riga.secondary_category_slugs, contesto.categorie),
    image_url: urlMediaAssoluto(riga.image_url),
    thumbnail_url: urlMediaAssoluto(riga.thumbnail_url),
    video: videoArticolo(riga),
    published_at: rfc3339Roma(istante),
    tags: pulisciElenco(riga.tags, { senzaMaiuscole: true }),
    author: { name: nomeAutore(riga.creator, contesto.profili) },
  };
}
