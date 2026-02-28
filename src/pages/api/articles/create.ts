export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { slugify } from '../../../lib/utils';
import { pingSearchEngines } from '../../../lib/seo';

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

    // Set default image if not provided
    if (!article.image_url) {
      const titleSeed = slugify(article.title || `seed-${Date.now()}`);
      article.image_url = `https://picsum.photos/seed/${titleSeed}/800/600`;
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
      console.error('Supabase error:', error);
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

    // Ping search engines if article is published
    if (!data.isdraft) {
      try {
        await pingSearchEngines(`https://edunews24.it/${data.category_slug}/${data.slug}`);
      } catch (error) {
        console.error('Error pinging search engines:', error);
        // Don't fail the request if pinging fails
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
    console.error('Error creating article:', {
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
