/**
 * Riempie gli slug MANCANTI degli articoli. Non tocca quelli esistenti.
 *
 * ATTENZIONE — questo script prima riscriveva `slug` e `category_slug` di
 * TUTTE le righe con `slugify()` di src/lib/utils.ts. Era l'unico punto del
 * repo capace di annullare in un colpo solo il congelamento dello slug: un
 * lancio distratto avrebbe cambiato l'URL di ogni articolo indicizzato, e la
 * rotta pubblica non ha redirect di storico (il fallback di
 * `[category]/[slug].astro` copre solo il cambio di CATEGORIA), quindi tutti
 * i vecchi indirizzi avrebbero risposto 410 Gone.
 *
 * Ora:
 *  - agisce solo sulle righe con slug o category_slug vuoti o non conformi;
 *  - usa `slugifica()` (accent-safe) invece di `slugify()`, che cancella gli
 *    accenti ("citta'" diventava "citt");
 *  - non parte senza la variabile d'ambiente MIGRAZIONE_SLUG=si;
 *  - stampa cosa farebbe e chiede un secondo flag per scrivere davvero.
 *
 *   MIGRAZIONE_SLUG=si npx astro exec scripts/migrate-slugs.ts          # prova
 *   MIGRAZIONE_SLUG=si SCRIVI=si npx astro exec scripts/migrate-slugs.ts # scrive
 */
import { supabase } from '../src/lib/supabase';
import { slugifica, slugValido } from '../src/lib/slug';

async function migrateArticleSlugs() {
  if (process.env.MIGRAZIONE_SLUG !== 'si') {
    console.error(
      'Rifiuto di partire: serve MIGRAZIONE_SLUG=si.\n' +
      'Questo script scrive sulla tabella articles. Leggi il commento in testa al file.'
    );
    process.exitCode = 1;
    return;
  }
  const scriviDavvero = process.env.SCRIVI === 'si';

  const { data: articles, error } = await supabase
    .from('articles')
    .select('id, title, category, slug, category_slug');

  if (error) {
    console.error('Errore nel leggere gli articoli:', error);
    process.exitCode = 1;
    return;
  }

  let daSistemare = 0;
  for (const article of articles ?? []) {
    const updates: Record<string, string> = {};

    // Solo gli slug ASSENTI o non conformi. Uno slug valido e' un URL gia'
    // pubblicato: rigenerarlo lo manderebbe in 410.
    if (!slugValido(article.slug)) {
      const nuovo = slugifica(article.title ?? '');
      if (slugValido(nuovo)) updates.slug = nuovo;
    }
    if (!slugValido(article.category_slug)) {
      const nuovo = slugifica(article.category ?? '');
      if (slugValido(nuovo)) updates.category_slug = nuovo;
    }
    if (Object.keys(updates).length === 0) continue;

    daSistemare++;
    console.log(
      `articolo ${article.id}: ${JSON.stringify(updates)}` +
      (scriviDavvero ? '' : '  [prova, non scritto]')
    );
    if (!scriviDavvero) continue;

    const { error: updateError } = await supabase
      .from('articles')
      .update(updates)
      .eq('id', article.id);
    if (updateError) {
      console.error(`Errore aggiornando l'articolo ${article.id}:`, updateError);
    }
  }

  console.log(
    `Righe da sistemare: ${daSistemare} su ${articles?.length ?? 0}.` +
    (scriviDavvero ? ' Scrittura eseguita.' : ' Nessuna scrittura: rilancia con SCRIVI=si.')
  );
}

migrateArticleSlugs();
