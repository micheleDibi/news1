import { supabaseBandi } from '../lib/supabase-bandi';

interface BandoSlug {
  slug: string;
  updated_at: string | null;
  data_pubblicazione: string | null;
}

export async function GET() {
  try {
    let all: BandoSlug[] = [];
    let page = 0;
    const pageSize = 1000;
    let hasMore = true;

    while (hasMore) {
      const { data, error } = await supabaseBandi
        .from('bando')
        .select('slug, updated_at, data_pubblicazione')
        .eq('stato_processing', 'completed')
        .not('slug', 'is', null)
        .order('data_pubblicazione', { ascending: false, nullsFirst: false })
        .order('id', { ascending: true })
        .range(page * pageSize, (page + 1) * pageSize - 1);

      if (error) {
        throw error;
      }

      const rows = (data ?? []) as BandoSlug[];
      if (rows.length > 0) {
        all = [...all, ...rows];
        if (rows.length < pageSize) hasMore = false;
      } else {
        hasMore = false;
      }
      page++;
    }

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    // Gli slug sono generati safe (alfanumerico + trattini), ma uno slug
    // anomalo con `&`/`<` invaliderebbe l'XML: fuori pattern → percent-encoding
    // (URL e XML safe), nessuna URL viene mai droppata.
    const SLUG_SAFE = /^[A-Za-z0-9_-]+$/;

    all.forEach((bando) => {
      if (!bando.slug) return;
      const safeSlug = SLUG_SAFE.test(bando.slug) ? bando.slug : encodeURIComponent(bando.slug);
      const lastmod = bando.updated_at ?? bando.data_pubblicazione;
      xml += `
  <url>
    <loc>https://edunews24.it/bandi/${safeSlug}</loc>`;
      if (lastmod) {
        try {
          xml += `
    <lastmod>${new Date(lastmod).toISOString()}</lastmod>`;
        } catch {
          // skip lastmod se data non parsabile
        }
      }
      xml += `
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`;
    });

    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400',
      },
    });
  } catch (error) {
    console.error('Error generating sitemap-bandi:', error);
    return new Response('Error generating sitemap-bandi', { status: 500 });
  }
}
