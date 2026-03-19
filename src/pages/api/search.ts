export const prerender = false;

import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import { categories } from '../../lib/categories';
import { logger } from '../../lib/logger';

export const POST: APIRoute = async ({ request }) => {
  let query = '';
  let category = '';

  try {
    const body = await request.json();
    query = body.query || '';
    category = body.category || '';

    let supabaseQuery = supabase
      .from('articles')
      .select('id, title, slug, excerpt, image_url, category, category_slug, published_at, tags')
      .eq('isdraft', false)
      .order('published_at', { ascending: false });

    if (query) {
      const searchTerm = query.replace(/%/g, '\\%').replace(/_/g, '\\_');
      supabaseQuery = supabaseQuery.or(
        `title.ilike.%${searchTerm}%,excerpt.ilike.%${searchTerm}%`
      );
    }

    if (category && category !== 'All') {
      supabaseQuery = supabaseQuery.eq('category', category);
    }

    supabaseQuery = supabaseQuery.limit(10);

    const { data: articles, error } = await supabaseQuery;

    if (error) {
      logger.error('Search query error:', error);
      throw error;
    }

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
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    logger.error('Search error:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error',
      query,
      category
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};
