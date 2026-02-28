import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import { categories } from '../../lib/categories';

export const GET: APIRoute = async ({ request }) => {
  try {
    // Fetch all published articles
    const { data: articles, error } = await supabase
      .from('articles')
      .select('id, slug, category_slug, published_at, updated_at')
      .eq('isdraft', false)
      .order('published_at', { ascending: false });

    if (error) throw error;

    // Generate XML sitemap
    const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- Home page -->
  <url>
    <loc>https://edunews24.it/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  
  <!-- Category pages -->
  ${categories.map(category => `
  <url>
    <loc>https://edunews24.it/${category.slug}</loc>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`).join('')}
  
  <!-- Static pages -->
  <url>
    <loc>https://edunews24.it/privacy</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>
  <url>
    <loc>https://edunews24.it/terms</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>
  <url>
    <loc>https://edunews24.it/about</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>https://edunews24.it/contact</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  
  <!-- Generated dynamically for articles -->
  ${articles.map(article => {
    const url = `https://edunews24.it/${article.category_slug}/${article.slug}`;
    const lastmod = article.updated_at || article.published_at;
    return `
  <url>
    <loc>${url}</loc>
    <lastmod>${new Date(lastmod).toISOString().split('T')[0]}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>`;
  }).join('')}
</urlset>`;

    return new Response(sitemap, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=3600'
      }
    });
  } catch (error) {
    console.error('Error generating sitemap:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}; 