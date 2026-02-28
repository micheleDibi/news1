function getTodayDateWithItalianTimezone(): string {
  const now = new Date();
  
  // Imposta il fuso orario italiano (UTC+2)
  const options: Intl.DateTimeFormatOptions = { 
    timeZone: 'Europe/Rome',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  };
  
  const formatter = new Intl.DateTimeFormat('it-IT', options);
  const parts = formatter.formatToParts(now);
  
  // Estrai anno, mese e giorno dalla data formattata
  const year = parts.find(part => part.type === 'year')?.value || '';
  const month = parts.find(part => part.type === 'month')?.value || '';
  const day = parts.find(part => part.type === 'day')?.value || '';
  
  return `${year}-${month}-${day}`;
}

export async function GET() {
  try {
    // Ottieni la data odierna con fuso orario italiano
    const today = getTodayDateWithItalianTimezone();

    // Start XML content - only the root element
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-articoli.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-pagine.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-news.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-selezione-personale.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-interpelli.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
   <sitemap>
      <loc>https://www.edunews24.it/sitemap-categorie.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
    <sitemap>
      <loc>https://www.edunews24.it/sitemap-video.xml</loc>
      <lastmod>${today}</lastmod>
   </sitemap>
</sitemapindex>`;

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