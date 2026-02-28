export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import { categories } from '../../lib/categories';

export const POST: APIRoute = async ({ request }) => {
  try {
    const { query, category } = await request.json();

    let supabaseQuery = supabase
      .from('articles')
      .select('*')
      .eq('isdraft', false)
      .order('published_at', { ascending: false });

    // Add full-text search with proper query escaping
    if (query) {
      const searchTerm = query.replace(/%/g, '\\%').replace(/_/g, '\\_');
      supabaseQuery = supabaseQuery.or(
        `title.ilike.%${searchTerm}%,excerpt.ilike.%${searchTerm}%,content.ilike.%${searchTerm}%`
      );
    }

    // Add category filter if specified and not 'All'
    if (category && category !== 'All') {
      supabaseQuery = supabaseQuery.eq('category', category);
    }

    // Limit results
    supabaseQuery = supabaseQuery.limit(10);

    // Execute the query
    const { data: articles, error } = await supabaseQuery;

    if (error) {
      console.error('Search query error:', error);
      throw error;
    }

    // Transform articles to include category colors
    const transformedArticles = articles?.map(article => ({
      ...article,
      categoryColor: categories.find(c => c.name === article.category)?.color || 'sport-500'
    }));

    return new Response(JSON.stringify({ 
      articles: transformedArticles || [],
      query,
      category,
      count: transformedArticles?.length || 0
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    console.error('Search error:', error);
    return new Response(JSON.stringify({ 
      error: error instanceof Error ? error.message : 'Internal Server Error',
      query,
      category
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 