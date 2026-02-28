import { supabase, type Article } from '../lib/supabase';
import { categories } from '../lib/categories';

export async function GET() {
  try {
    // Get all published articles
    const { data: articles, error } = await supabase
      .from('articles')
      .select('*')
      .eq('isdraft', false)
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Start XML content
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- Homepage -->
  <url>
    <loc>https://edunews24.it/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <!-- Category pages -->`;

    // Add all categories from the categories.ts file
    categories.forEach(category => {
      xml += `
  <url>
    <loc>https://edunews24.it/category/${category.slug}</loc>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`;
    });

    // Add static pages
    xml += `
  <!-- Static pages -->
  <url>
    <loc>https://edunews24.it/privacy</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>
  <url>
    <loc>https://edunews24.it/chi-siamo</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>
  <url>
    <loc>https://edunews24.it/collaborazione</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>`;

    // Add article URLs
    (articles as Article[]).forEach(article => {
      const lastmod = new Date(article.published_at).toISOString();
      xml += `
  <url>
    <loc>https://edunews24.it/${article.category_slug}/${article.slug}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.5</priority>
  </url>`;
    });

    // Close XML
    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml'
      }
    });

  } catch (error) {
    console.error('Error generating sitemap:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
} 