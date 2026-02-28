import { supabase, type Article } from '../lib/supabase';

// Funzione per escape dei caratteri speciali XML
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

// Funzione per formattare le date ISO con fuso orario corretto
function isoWithOffset(isoUtc: string, offsetHours = 1): string {
    const date = new Date(isoUtc);
    date.setHours(date.getHours() + offsetHours);
    const base = date.toISOString().slice(0, -1);
    const sign = offsetHours >= 0 ? '+' : '-';
    const pad  = (n: number) => String(Math.abs(n)).padStart(2, '0');
    return `${base}${sign}${pad(offsetHours)}:00`;
}

export async function GET({ url }: { url: URL }) {
  try {
    // Estrai i parametri dalla query string
    const params = url.searchParams;
    const anno = params.get('anno');
    const mese = params.get('mese');
    const giorno = params.get('giorno');

    // Verifica se tutti i parametri necessari sono presenti
    if (!anno || !mese || !giorno) {
      return new Response('Parametri mancanti. Richiede: anno, mese e giorno.', { 
        status: 400,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    // Calcola l'inizio e la fine della giornata specificata
    const startOfDay = new Date(`${anno}-${mese}-${giorno}T00:00:00Z`);
    const endOfDay = new Date(`${anno}-${mese}-${giorno}T23:59:59.999Z`);

    console.log(`Fetching articles for ${anno}-${mese}-${giorno}, from ${startOfDay.toISOString()} to ${endOfDay.toISOString()}`);

    // Ottieni gli articoli pubblicati nel giorno specificato
    const { data: articles, error } = await supabase
      .from('articles')
      .select('title, slug, category_slug, published_at, image_url')
      .eq('isdraft', false)
      .gte('published_at', startOfDay.toISOString())
      .lte('published_at', endOfDay.toISOString())
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Start XML content
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">`;

    // Add article URLs per il giorno specificato
    if (articles && articles.length > 0) {
      console.log(`Found ${articles.length} articles for ${anno}-${mese}-${giorno}`);
      (articles as Pick<Article, 'title' | 'slug' | 'category_slug' | 'published_at' | 'image_url'>[]).forEach(article => {
        const lastmod = isoWithOffset(article.published_at, 1);
        const categorySlug = article.category_slug || 'general'; // Fornisce un valore di default se manca
        
        xml += `
  <url>
    <loc>https://edunews24.it/${categorySlug}/${article.slug}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>hourly</changefreq>
    <priority>0.9</priority>`;
        
        // Aggiungi l'immagine se disponibile
        if (article.image_url) {
          xml += `
    <image:image>
      <image:loc>${escapeXml(article.image_url)}</image:loc>
    </image:image>`;
        }
        
        xml += `
  </url>`;
      });
    } else {
      console.log(`No articles found for ${anno}-${mese}-${giorno}`);
    }

    // Close XML
    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        // Cache per un tempo limitato
        'Cache-Control': 'public, max-age=3600' // Cache per 1 ora
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-articoli-giornalieri:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}
