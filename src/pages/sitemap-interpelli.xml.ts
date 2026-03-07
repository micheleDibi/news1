import { supabase } from '../lib/supabase';

interface Interpello {
  id: number;
  interpello_name: string;
  interpello_date: string;
  interpello_regione?: string;
  interpello_provincia?: string;
  interpello_citta?: string;
}

// Function to generate URL-friendly slug from interpello data (same as in [slug].astro)
function generateInterpelloSlug(interpello: Interpello): string {
  const parts = [
    interpello.interpello_name,
    interpello.interpello_provincia || interpello.interpello_citta,
    interpello.interpello_regione,
    interpello.id?.toString()
  ].filter(Boolean);

  return parts
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9\-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

export async function GET() {
  try {
    let allInterpelli: Interpello[] = [];
    let page = 0;
    const pageSize = 1000;
    let hasMoreData = true;

    while (hasMoreData) {
      const { data: interpelli, error } = await supabase
        .from('interpelli')
        .select('id, interpello_name, interpello_date, interpello_regione, interpello_provincia, interpello_citta')
        .order('interpello_date', { ascending: false })
        .range(page * pageSize, (page + 1) * pageSize - 1);

      if (error) {
        throw error;
      }

      if (interpelli && interpelli.length > 0) {
        allInterpelli = [...allInterpelli, ...interpelli];
        
        if (interpelli.length < pageSize) {
          hasMoreData = false;
        }
      } else {
        hasMoreData = false;
      }
      
      page++;
    }

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    allInterpelli.forEach(interpello => {
      const slug = generateInterpelloSlug(interpello);
      if (slug) {
        xml += `
  <url>
    <loc>https://edunews24.it/interpelli/${slug}</loc>
    <lastmod>${new Date(interpello.interpello_date).toISOString()}</lastmod>
  </url>`;
      }
    });

    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400' // Cache for 24 hours
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-interpelli:', error);
    return new Response('Error generating sitemap-interpelli', { status: 500 });
  }
} 