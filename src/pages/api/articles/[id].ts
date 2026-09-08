export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { submitToIndexNow } from '../../../lib/indexnow';
import { logger } from '../../../lib/logger';
import { normalizzaArticolo } from '../../../lib/normalizza-articolo';
import { slugifica, slugValido } from '../../../lib/slug';
import { slugOccupato } from '../../../lib/slug-articolo';

export const DELETE: APIRoute = async ({ params }) => {
  const { id } = params;

  try {
    // Fetch article data before deleting (needed for IndexNow URL)
    const { data: article } = await supabase
      .from('articles')
      .select('slug, category_slug')
      .eq('id', id)
      .single();

    const { error } = await supabase
      .from('articles')
      .delete()
      .eq('id', id);

    if (error) {
      logger.error('Error deleting article:', error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Notify IndexNow about deleted article
    if (article) {
      try {
        await submitToIndexNow(`https://edunews24.it/${article.category_slug}/${article.slug}`);
      } catch (e) {
        logger.error('Error notifying IndexNow:', e);
      }
    }

    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    logger.error('Server error when deleting article:', error);
    return new Response(JSON.stringify({ error: 'Internal Server Error' }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
};

export const PUT: APIRoute = async ({ request, params }) => {
  try {
    const authHeader = request.headers.get('Authorization');
    const apiKey = authHeader?.split('Bearer ')[1];

    if (apiKey !== import.meta.env.API_SECRET_KEY) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const { id } = params;
    const updates = await request.json();

    // Never allow overwriting created_at via update
    delete (updates as any).created_at;

    // Riga attuale: serve per il congelamento dello slug e per capire se la
    // categoria e' davvero cambiata.
    const { data: attuale } = await supabase
      .from('articles')
      .select('slug, category, category_slug, isdraft')
      .eq('id', id)
      .single();

    // --- Normalizzazione ortografica -----------------------------------
    // Allowlist esplicita di campi, mai una ricorsione cieca sul payload:
    // qui passano anche source, image_url e gli slug, che non vanno toccati.
    // Questo e' l'unico punto da cui il ramo "persona in modifica" e il testo
    // digitato a mano raggiungono il database.
    const ortografia = normalizzaArticolo(updates);
    if (ortografia.campiCorretti.length > 0) {
      logger.info(`Ortografia corretta sull'articolo ${id}: ${ortografia.campiCorretti.join(', ')}`);
    }
    for (const saltato of ortografia.campiSaltati) {
      logger.warn(`Ortografia saltata su ${saltato.campo} (articolo ${id}): ${saltato.motivo}`);
    }

    // --- Congelamento dello slug ---------------------------------------
    // Lo slug si genera una volta sola. Un update non puo' cambiarlo se non
    // e' stato richiesto esplicitamente con l'header X-Slug-Intent, che deve
    // contenere lo slug desiderato: un campo del body sarebbe attivabile per
    // sbaglio, visto che il form fa lo spread dell'intero stato.
    // Lo slug viene scartato in silenzio, non rifiutato: un 409 farebbe
    // fallire il salvataggio di un redattore per un problema che il server
    // sa risolvere da solo. Il 409 resta sul percorso di modifica esplicita.
    let slugCongelato = false;
    if (attuale && typeof updates.slug === 'string' && updates.slug !== attuale.slug) {
      const richiesto = updates.slug;
      const intento = request.headers.get('X-Slug-Intent');
      if (intento === null || intento !== richiesto) {
        delete updates.slug;
        slugCongelato = true;
        logger.warn(
          `Slug congelato sull'articolo ${id}: richiesto "${richiesto}", mantenuto "${attuale.slug}"`
        );
      } else if (!slugValido(richiesto)) {
        return new Response(JSON.stringify({
          error: 'Slug non conforme',
          slug_richiesto: richiesto,
          slug_normalizzato: slugifica(richiesto),
        }), { status: 400, headers: { 'Content-Type': 'application/json' } });
      } else if (await slugOccupato(richiesto, id)) {
        return new Response(JSON.stringify({
          error: 'Slug gia in uso da un altro articolo',
          slug_richiesto: richiesto,
          slug_attuale: attuale.slug,
        }), { status: 409, headers: { 'Content-Type': 'application/json' } });
      }
    }

    // Stesso principio per category_slug: si riscrive solo se e' cambiato
    // anche il NOME della categoria. Altrimenti una divergenza fra
    // slugify(nome) e categories.slug sposterebbe l'URL in silenzio.
    if (attuale && typeof updates.category_slug === 'string'
        && updates.category_slug !== attuale.category_slug) {
      const categoriaCambiata =
        typeof updates.category === 'string' && updates.category !== attuale.category;
      if (!categoriaCambiata) {
        logger.warn(
          `category_slug congelato sull'articolo ${id}: richiesto "${updates.category_slug}", mantenuto "${attuale.category_slug}"`
        );
        delete updates.category_slug;
      }
    }

    // Se l'articolo è (o diventa) pubblicato, aggiorna la data di pubblicazione
    if (updates.isdraft === false) {
      updates.published_at = new Date().toISOString();
    }

    if (Object.keys(updates).length === 0) {
      return new Response(JSON.stringify({ 
        error: 'No fields provided for update'
      }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const { data, error } = await supabase
      .from('articles')
      .update(updates)
      .eq('id', id)
      .select()
      .single();

    if (error) throw error;

    // Notify IndexNow about updated/published article
    if (data && !data.isdraft) {
      try {
        const urls = [
          `https://edunews24.it/${data.category_slug}/${data.slug}`,
          `https://edunews24.it/${data.category_slug}`,
          'https://edunews24.it/',
        ];
        // Se lo slug e' stato cambiato di proposito, il vecchio URL diventa
        // un 410: segnalarlo comunque a IndexNow e' l'unica mitigazione a
        // costo zero, visto che non esiste una tabella di storico slug.
        if (attuale && attuale.slug && attuale.slug !== data.slug) {
          urls.push(`https://edunews24.it/${attuale.category_slug}/${attuale.slug}`);
        }
        await submitToIndexNow(urls);
      } catch (e) {
        logger.error('Error notifying IndexNow:', e);
      }
    }

    return new Response(JSON.stringify({
      success: true,
      article: data,
      slug_congelato: slugCongelato,
      ortografia: ortografia.segnalazioni
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    logger.error('Error updating article:', error);
    return new Response(JSON.stringify({ 
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 
