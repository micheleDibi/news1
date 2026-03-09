import { createClient } from '@supabase/supabase-js';

export async function GET() {
  try {
    const supabaseUrl = import.meta.env.PUBLIC_SUPABASE_URL;
    const supabaseKey = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseKey) {
      return new Response('Missing Supabase credentials', { status: 500 });
    }

    const supabase = createClient(supabaseUrl, supabaseKey);

    const { data, error } = await supabase
      .from('selezione_personale')
      .select('slug, data_pubblicazione, updated_at')
      .eq('status', 'completed')
      .order('data_pubblicazione', { ascending: false });

    if (error) {
      console.error('Supabase error:', error);
      return new Response('Error fetching data', { status: 500 });
    }

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    (data || []).forEach(bando => {
      if (bando.slug) {
        const lastmod = bando.updated_at || bando.data_pubblicazione;
        xml += `
  <url>
    <loc>https://edunews24.it/selezione-personale/${bando.slug}</loc>
    <lastmod>${new Date(lastmod).toISOString()}</lastmod>
  </url>`;
      }
    });

    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400'
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-selezione-personale:', error);
    return new Response('Error generating sitemap-selezione-personale', { status: 500 });
  }
}
