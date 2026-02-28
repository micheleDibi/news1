import { supabase, type Article } from '../lib/supabase';
// Remove categories import, no longer needed
// import { categories } from '../lib/categories';

export async function GET() {
  try {
    // Calculate the date 48 hours ago
    const fortyEightHoursAgo = new Date();
    fortyEightHoursAgo.setHours(fortyEightHoursAgo.getHours() - 48);
    const fortyEightHoursAgoISO = fortyEightHoursAgo.toISOString();

    // Get published articles from the last 48 hours
    const { data: articles, error } = await supabase
      .from('articles')
      .select('slug, category_slug, published_at') // Select only needed fields
      .eq('isdraft', false)
      .gte('published_at', fortyEightHoursAgoISO) // Filter by date
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Start XML content - only the root element
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    // Add article URLs
    (articles as Pick<Article, 'slug' | 'category_slug' | 'published_at'>[]).forEach(article => {
      const lastmod = new Date(article.published_at).toISOString();
      // Use category_slug if available, otherwise handle potential missing value
      const categorySlug = article.category_slug || 'general'; // Provide a default or handle error
      xml += `
  <url>
    <loc>https://edunews24.it/${categorySlug}/${article.slug}</loc>
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
        // Add cache control headers if needed, e.g., shorter cache for recent news
        // 'Cache-Control': 'public, max-age=600' // Cache for 10 minutes
      }
    });

  } catch (error) {
    console.error('Error generating recent news sitemap:', error);
    return new Response('Error generating recent news sitemap', { status: 500 });
  }
} 