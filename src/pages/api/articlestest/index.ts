import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

// Helper function to check if an origin is allowed by querying the database
async function isOriginAllowed(origin: string | null): Promise<boolean> {
  if (!origin) return false;
  
  try {
    const { data, error } = await supabase
      .from('api_access_requests')
      .select('site_url')
      .eq('status', 'approved')
      .eq('site_url', origin);
    
    if (error) {
      console.error('Error checking allowed origins:', error);
      return false;
    }
    
    return data && data.length > 0;
  } catch (error) {
    console.error('Error in origin check:', error);
    return false;
  }
}

// Handle CORS preflight requests
export const OPTIONS: APIRoute = async ({ request }) => {
  const origin = request.headers.get('origin');
  const referer = request.headers.get('referer');
  const requestOrigin = origin || (referer ? new URL(referer).origin : null);
  
  const isAllowed = await isOriginAllowed(requestOrigin);
  
  if (!isAllowed) {
    return new Response(null, {
      status: 403,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  return new Response(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': requestOrigin || '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400'
    }
  });
};

export const GET: APIRoute = async ({ request }) => {
  try {
    // Check origin authorization
    const origin = request.headers.get('origin');
    const referer = request.headers.get('referer');
    
    // Extract origin from referer if origin is not present
    const requestOrigin = origin || (referer ? new URL(referer).origin : null);
    
    const isAllowed = await isOriginAllowed(requestOrigin);
    
    if (!isAllowed) {
      return new Response(JSON.stringify({ 
        error: 'Unauthorized: Origin not allowed',
        code: 'ORIGIN_NOT_ALLOWED'
      }), {
        status: 403,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const url = new URL(request.url);
    const page = parseInt(url.searchParams.get('page') || '1');
    const limit = parseInt(url.searchParams.get('limit') || '1000');
    
    // Calculate offset for pagination
    const offset = (page - 1) * limit;

    // Get total count of articles
    const { count: totalCount, error: countError } = await supabase
      .from('articles')
      .select('*', { count: 'exact', head: true })
      .eq('isdraft', false);

    if (countError) {
      console.error('Error counting articles:', countError);
      return new Response(JSON.stringify({ error: countError.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': requestOrigin || '*'
        }
      });
    }

    // Get paginated articles
    const { data: articles, error } = await supabase
      .from('articles')
      .select('*')
      .eq('isdraft', false)
      .order('published_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error('Error fetching articles:', error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': requestOrigin || '*'
        }
      });
    }

    // Calculate pagination metadata
    const totalPages = Math.ceil((totalCount || 0) / limit);
    const hasNextPage = page < totalPages;
    const hasPrevPage = page > 1;

    const response = {
      articles,
      pagination: {
        currentPage: page,
        totalPages,
        totalCount,
        limit,
        hasNextPage,
        hasPrevPage,
        nextPage: hasNextPage ? page + 1 : null,
        prevPage: hasPrevPage ? page - 1 : null
      }
    };

    return new Response(JSON.stringify(response), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': requestOrigin || '*'
      }
    });

  } catch (err) {
    console.error('Server error fetching articles:', err);
    const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
    return new Response(JSON.stringify({ error: errorMessage }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }
}; 