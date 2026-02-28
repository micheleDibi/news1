import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

// Handle CORS preflight requests
export const OPTIONS: APIRoute = async ({ request }) => {
  return new Response(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400'
    }
  });
};

export const GET: APIRoute = async ({ request }) => {
  try {
    const url = new URL(request.url);
    const pageParam = url.searchParams.get('page');
    const limit = parseInt(url.searchParams.get('limit') || '1000');
    
    // If no page parameter is provided, fetch ALL articles
    if (!pageParam) {
      console.log('📰 Fetching ALL articles (no page parameter provided)');
      let allArticles: any[] = [];
      let currentPage = 1;
      let hasMorePages = true;
      
      while (hasMorePages) {
        const offset = (currentPage - 1) * limit;
        console.log(`🔄 Fetching page ${currentPage} (offset: ${offset}, limit: ${limit})`);
        
        const { data: articles, error } = await supabase
          .from('articles')
          .select('title, slug, excerpt, image_url, published_at, category, category_slug, tags, summary, secondary_category_slugs')
          .eq('isdraft', false)
          .order('published_at', { ascending: false })
          .range(offset, offset + limit - 1);

        if (error) {
          console.error('Error fetching articles:', error);
          return new Response(JSON.stringify({ error: error.message }), {
            status: 500,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          });
        }

        if (articles && articles.length > 0) {
          console.log(`✅ Retrieved ${articles.length} articles from page ${currentPage}`);
          allArticles = allArticles.concat(articles);
          // If we got fewer articles than the limit, we've reached the end
          hasMorePages = articles.length === limit;
          currentPage++;
        } else {
          console.log(`🛑 No more articles found on page ${currentPage}`);
          hasMorePages = false;
        }
      }

      console.log(`🎉 Finished fetching ALL articles. Total: ${allArticles.length} articles`);
      return new Response(JSON.stringify({ articles: allArticles }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    // Original pagination logic when page parameter is provided
    const page = parseInt(pageParam);
    console.log(`📄 Fetching paginated articles - Page: ${page}, Limit: ${limit}`);
    
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
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    // Get paginated articles
    const { data: articles, error } = await supabase
      .from('articles')
      .select('title, slug, excerpt, image_url, published_at, category, category_slug, tags, summary, secondary_category_slugs')
      .eq('isdraft', false)
      .order('published_at', { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error('Error fetching articles:', error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    console.log(`✅ Retrieved ${articles?.length || 0} articles for page ${page} (Total in DB: ${totalCount})`);

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
        'Access-Control-Allow-Origin': '*'
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