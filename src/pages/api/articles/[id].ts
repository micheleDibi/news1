export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { submitToIndexNow } from '../../../lib/indexnow';
import { logger } from '../../../lib/logger';

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
        await submitToIndexNow([
          `https://edunews24.it/${data.category_slug}/${data.slug}`,
          `https://edunews24.it/${data.category_slug}`,
          'https://edunews24.it/',
        ]);
      } catch (e) {
        logger.error('Error notifying IndexNow:', e);
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
