export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { submitToIndexNow } from '../../../lib/indexnow';
import { logger } from '../../../lib/logger';

export const POST: APIRoute = async ({ request }) => {
  try {
    // Get article ID from request body
    const body = await request.json();
    const id = body.id;

    if (!id) {
      return new Response(JSON.stringify({ error: 'Article ID is required' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

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