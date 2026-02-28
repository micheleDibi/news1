export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const POST: APIRoute = async ({ request }) => {
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

    const podcast = await request.json();

    // Validate required fields
    const requiredFields = ['title', 'description', 'audio_url', 'published_at'];
    const missingFields = requiredFields.filter(field => !podcast[field]);

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
    if (!podcast.image_url) {
      podcast.image_url = `https://picsum.photos/seed/${Math.random()}/800/600`;
    }

    const { data, error } = await supabase
      .from('podcasts')
      .insert([podcast])
      .select()
      .single();

    if (error) throw error;

    return new Response(JSON.stringify({ 
      success: true,
      podcast: data
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    console.error('Error creating podcast:', error);
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