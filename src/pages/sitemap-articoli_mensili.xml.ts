import { supabase, type Article } from '../lib/supabase';

// Funzione per formattare le date ISO con fuso orario corretto
function isoWithOffset(isoUtc: string, offsetHours = 1): string {
    const date = new Date(isoUtc);
    date.setHours(date.getHours() + offsetHours);
    const base = date.toISOString().slice(0, -1);
    const sign = offsetHours >= 0 ? '+' : '-';
    const pad  = (n: number) => String(Math.abs(n)).padStart(2, '0');
    return `${base}${sign}${pad(offsetHours)}:00`;
}

// Funzione per fare escape dei caratteri XML
function escapeXml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

export async function GET({ url }: { url: URL }) {
  try {
    // Estrai i parametri dalla query string
    const params = url.searchParams;
    const anno = params.get('anno');
    const mese = params.get('mese');

    // Verifica se tutti i parametri necessari sono presenti
    if (!anno || !mese) {
      return new Response('Parametri mancanti. Richiede: anno e mese.', { 
        status: 400,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    // Calcola l'inizio e la fine del mese specificato
    const startOfMonth = new Date(`${anno}-${mese}-01T00:00:00Z`);
    const endOfMonth = new Date(parseInt(anno), parseInt(mese), 0, 23, 59, 59, 999); // Ultimo giorno del mese
    endOfMonth.setUTCHours(23, 59, 59, 999); // Assicura che sia fine giornata UTC

    console.log(`Fetching articles for ${anno}-${mese}, from ${startOfMonth.toISOString()} to ${endOfMonth.toISOString()}`);

    // Get all published articles with pagination
    let allArticles: Pick<Article, 'title' | 'slug' | 'category_slug' | 'published_at' | 'image_url'>[] = [];
    let page = 0;
    const pageSize = 1000;
    let hasMoreData = true;

    while (hasMoreData) {
      const { data: articles, error } = await supabase
        .from('articles')
        .select('title, slug, category_slug, published_at, image_url')
        .eq('isdraft', false)
        .gte('published_at', startOfMonth.toISOString())
        .lte('published_at', endOfMonth.toISOString())
        .order('published_at', { ascending: false })
        .range(page * pageSize, (page + 1) * pageSize - 1);

      if (error) {
        throw error;
      }

      if (articles && articles.length > 0) {
        allArticles = [...allArticles, ...articles];
        
        // Check if we received a full page of results
        if (articles.length < pageSize) {
          hasMoreData = false;
        }
      } else {
        hasMoreData = false;
      }
      
      page++;
    }

    // Log the total number of articles retrieved for debugging
    console.log(`Total articles retrieved for ${anno}-${mese}: ${allArticles.length}`);

    // Start XML content
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">`;

    // Add article URLs per il mese specificato
    if (allArticles && allArticles.length > 0) {
      console.log(`Found ${allArticles.length} articles for ${anno}-${mese}`);
      allArticles.forEach(article => {
        const lastmod = isoWithOffset(article.published_at, 1);
        const categorySlug = article.category_slug || 'general'; // Fornisce un valore di default se manca
        
        xml += `
  <url>
    <loc>https://edunews24.it/${escapeXml(categorySlug)}/${escapeXml(article.slug)}</loc>
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
      console.log(`No articles found for ${anno}-${mese}`);
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
    console.error('Error generating sitemap-articoli-mensili:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}
