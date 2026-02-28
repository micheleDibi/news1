import { supabase, type Article } from '../lib/supabase';
// Remove categories import, no longer needed
// import { categories } from '../lib/categories';

function isoWithOffset(isoUtc: string, offsetHours = 1): string {
    const date = new Date(isoUtc);
    date.setHours(date.getHours() + offsetHours);
    const base = date.toISOString().slice(0, -1);
    const sign = offsetHours >= 0 ? '+' : '-';
    const pad  = (n: number) => String(Math.abs(n)).padStart(2, '0');
    return `${base}${sign}${pad(offsetHours)}:00`;
}

// Add XML escaping function with CDATA handling
function escapeXml(unsafe: string): string {
    // First replace any existing CDATA sections to prevent double escaping
    const withoutCDATA = unsafe.replace(/<!\[CDATA\[(.*?)\]\]>/g, '$1');
    
    // Then escape special characters
    return withoutCDATA
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;')
        .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, ''); // Remove control characters
}

export async function GET() {
  try {
    // Calculate the date 48 hours ago
    const fortyEightHoursAgo = new Date();
    fortyEightHoursAgo.setHours(fortyEightHoursAgo.getHours() - 48);
    const fortyEightHoursAgoISO = fortyEightHoursAgo.toISOString();

    // Get published articles from the last 48 hours
    const { data: articles, error } = await supabase
      .from('articles')
      .select('title, slug, category_slug, published_at, image_url') // Select only needed fields
      .eq('isdraft', false)
      .gte('published_at', fortyEightHoursAgoISO) // Filter by date
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Start XML content - only the root element
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">`;

    // Add article URLs
    (articles as Pick<Article, 'title' | 'slug' | 'image_url' | 'category_slug' | 'published_at'>[]).forEach(article => {
      // const lastmod = new Date(article.published_at).toISOString();
      // Use category_slug if available, otherwise handle potential missing value
      const categorySlug = article.category_slug || 'general'; // Provide a default or handle error
            

    const lastModIso = isoWithOffset(article.published_at, 1);
      xml += `
  <url>
    <loc>https://edunews24.it/${categorySlug}/${article.slug}</loc>
    <news:news>
      <news:publication>
        <news:name>Edunews24</news:name>
        <news:language>it</news:language>
      </news:publication>
      <news:publication_date>${lastModIso}</news:publication_date>
      <news:title><![CDATA[${escapeXml(article.title)}]]></news:title>
    </news:news>
    <image:image>
      <image:loc>${escapeXml(article.image_url)}</image:loc>
    </image:image>

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