export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const DELETE: APIRoute = async ({ params }) => {
  const { id } = params;

  try {
    const { error } = await supabase
      .from('podcasts')
      .delete()
      .eq('id', id);

    if (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
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
      .from('podcasts')
      .update(updates)
      .eq('id', id)
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
    console.error('Error updating podcast:', error);
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