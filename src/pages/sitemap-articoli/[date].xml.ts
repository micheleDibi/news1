import { supabase, type Article } from '../../lib/supabase';

function isoWithOffset(isoUtc: string, offsetHours = 1): string {
    const date = new Date(isoUtc);
    date.setHours(date.getHours() + offsetHours);
    const base = date.toISOString().slice(0, -1);
    const sign = offsetHours >= 0 ? '+' : '-';
    const pad  = (n: number) => String(Math.abs(n)).padStart(2, '0');
    return `${base}${sign}${pad(offsetHours)}:00`;
}

function escapeXml(unsafe: string): string {
    return unsafe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;')
        .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

export async function GET({ params }: { params: { date: string } }) {
  try {
    const dateParts = params.date.split('-');
    if (dateParts.length !== 3) {
      return new Response('Formato data non valido. Richiede: YYYY-MM-DD', {
        status: 400,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    const [anno, mese, giorno] = dateParts;

    const startOfDay = new Date(`${anno}-${mese}-${giorno}T00:00:00Z`);
    const endOfDay = new Date(`${anno}-${mese}-${giorno}T23:59:59.999Z`);

    const { data: articles, error } = await supabase
      .from('articles')
      .select('title, slug, category_slug, published_at, updated_at, image_url')
      .eq('isdraft', false)
      .gte('published_at', startOfDay.toISOString())
      .lte('published_at', endOfDay.toISOString())
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">`;

    if (articles && articles.length > 0) {
      (articles as Pick<Article, 'title' | 'slug' | 'category_slug' | 'published_at' | 'updated_at' | 'image_url'>[]).forEach(article => {
        const lastmod = isoWithOffset(article.updated_at || article.published_at, 1);
        const categorySlug = article.category_slug || 'general';

        xml += `
  <url>
    <loc>https://edunews24.it/${categorySlug}/${article.slug}</loc>
    <lastmod>${lastmod}</lastmod>`;

        if (article.image_url) {
          xml += `
    <image:image>
      <image:loc>${escapeXml(article.image_url)}</image:loc>
    </image:image>`;
        }

        xml += `
  </url>`;
      });
    }

    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=3600'
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-articoli:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}
