export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { submitToIndexNow } from '../../../lib/indexnow';
import { logger } from '../../../lib/logger';
import { normalizzaArticolo } from '../../../lib/normalizza-articolo';
import { slugDaTitolo, trovaSlugLibero } from '../../../lib/slug-articolo';

export const POST: APIRoute = async ({ request }) => {
  try {
    // Check for API key
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

    // Get request body
    const article = await request.json();
    if (!article.created_at) {
      article.created_at = new Date().toISOString();
    }
    article.video_duration ??= null; //se arriva un numero rimane,altrimenti salva null

    // Set default isdraft if not provided (before validations)
    if (typeof article.isdraft !== 'boolean') {
      article.isdraft = true;
    }

    // Normalizzazione ortografica dei campi di prosa (allowlist esplicita).
    // Deve girare PRIMA della generazione dello slug: se il titolo cambia
    // dopo, titolo e slug divergono. `slugifica()` traslittera gli accenti,
    // quindi la correzione non puo' comunque spostare l'URL.
    const ortografia = normalizzaArticolo(article);
    if (ortografia.campiCorretti.length > 0) {
      logger.info(`Ortografia corretta su: ${ortografia.campiCorretti.join(', ')}`);
    }
    for (const saltato of ortografia.campiSaltati) {
      logger.warn(`Ortografia saltata su ${saltato.campo}: ${saltato.motivo}`);
    }

    // Validate required fields:
    // - Bozza e Pubblicato: stessi campi obbligatori, senza richiedere published_at (gestito lato server)
    const draftRequiredFields = ['title', 'content', 'category', 'excerpt'];
    const publishRequiredFields = [...draftRequiredFields];
    const requiredFields = article.isdraft === false
      ? publishRequiredFields
      : draftRequiredFields;
    const missingFields = requiredFields.filter(field => !article[field]);

    if (missingFields.length > 0) {
      return new Response(JSON.stringify({ 
        error: `Missing required fields: ${missingFields.join(', ')}` 
      }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Slug: si genera server-side quando manca o non e' conforme. Senza
    // questo controllo un POST senza slug inseriva NULL e IndexNow riceveva
    // "https://edunews24.it/undefined/undefined".
    const slugBase = slugDaTitolo(article.slug, article.title);
    if (!slugBase) {
      return new Response(JSON.stringify({
        error: 'Slug mancante e titolo non slugificabile'
      }), { status: 400, headers: { 'Content-Type': 'application/json' } });
    }
    const slugLibero = await trovaSlugLibero(slugBase);
    if (!slugLibero) {
      return new Response(JSON.stringify({
        error: 'Slug gia in uso', slug_richiesto: slugBase
      }), { status: 409, headers: { 'Content-Type': 'application/json' } });
    }
    article.slug = slugLibero;

    // Set default image if not provided
    if (!article.image_url) {
      article.image_url = '/edunews24_immagine_da_sostituire.png';
    }

    // Set default creator if not provided
    if (!article.creator) {
      article.creator = 'Unknown';
    }

    // Normalize publication timestamps
    if (article.isdraft === false) {
      const createdAt = article.created_at || new Date().toISOString();
      article.created_at = createdAt;
      article.published_at = createdAt;
    } else {
      article.published_at = null;
    }

    // Insert article with better error handling
    const { data, error } = await supabase
      .from('articles')
      .insert([article])
      .select()
      .single();

    if (error) {
      logger.error('Supabase error:', error);
      return new Response(JSON.stringify({ 
        error: 'Database error',
        details: error.message
      }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Notify IndexNow if article is published
    if (!data.isdraft) {
      try {
        await submitToIndexNow([
          `https://edunews24.it/${data.category_slug}/${data.slug}`,
          `https://edunews24.it/${data.category_slug}`,
          'https://edunews24.it/',
        ]);
      } catch (error) {
        logger.error('Error notifying IndexNow:', error);
      }
    }

    return new Response(JSON.stringify({ 
      success: true,
      article: data
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    // Enhanced error logging
    logger.error('Error creating article:', {
      error,
      type: error instanceof Error ? error.constructor.name : typeof error,
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });

    return new Response(JSON.stringify({ 
      error: 'Internal Server Error',
      details: error instanceof Error ? error.message : String(error)
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 
