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

// Funzione per ottenere l'inizio e la fine del giorno corrente in formato ISO con fuso orario italiano
function getTodayStartEndISO(): { startISO: string, endISO: string } {
  const now = new Date();
  
  // Imposta il fuso orario italiano
  const options: Intl.DateTimeFormatOptions = { timeZone: 'Europe/Rome' };
  const formatter = new Intl.DateTimeFormat('en-US', options);
  const parts = formatter.formatToParts(now);
  
  // Estrai anno, mese e giorno
  const year = parseInt(parts.find(part => part.type === 'year')?.value || '0');
  const month = parseInt(parts.find(part => part.type === 'month')?.value || '0') - 1; // mese in JavaScript è 0-indexed
  const day = parseInt(parts.find(part => part.type === 'day')?.value || '0');
  
  // Crea date per inizio e fine giornata nel fuso orario locale
  const todayStart = new Date(Date.UTC(year, month, day, 0, 0, 0));
  const todayEnd = new Date(Date.UTC(year, month, day, 23, 59, 59, 999));
  
  return {
    startISO: todayStart.toISOString(),
    endISO: todayEnd.toISOString()
  };
}

export async function GET() {
  try {
    // Ottieni l'inizio e la fine del giorno corrente in formato ISO
    const { startISO, endISO } = getTodayStartEndISO();
    
    console.log(`Fetching articles from ${startISO} to ${endISO}`);
    
    // Get published articles from the current day only
    const { data: articles, error } = await supabase
      .from('articles')
      .select('*')
      .eq('isdraft', false)
      .gte('published_at', startISO)
      .lte('published_at', endISO)
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Start XML content - solo per gli articoli del giorno corrente
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">`;

    // Add article URLs - solo articoli di oggi
    if (articles && articles.length > 0) {
      console.log(`Found ${articles.length} articles for today`);
      (articles as Article[]).forEach(article => {
        const lastmod = isoWithOffset(article.published_at, 1);
        const categorySlug = article.category_slug || 'general'; // Fornisce un valore di default se manca
        xml += `
  <url>
    <loc>https://edunews24.it/${categorySlug}/${article.slug}</loc>
    <lastmod>${lastmod}</lastmod>
    <image:image>
      <image:loc>${escapeXml(article.image_url)}</image:loc>
    </image:image>
  </url>`;
      });
    } else {
      console.log('No articles found for today');
    }

    // Close XML
    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        // Cache per un tempo più breve perché è contenuto giornaliero
        'Cache-Control': 'public, max-age=3600' // Cache per 1 ora
      }
    });

  } catch (error) {
    console.error('Error generating sitemap:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
} 