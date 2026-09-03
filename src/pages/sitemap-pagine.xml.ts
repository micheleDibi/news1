// Solo pagine statiche editoriali. Le tre landing di sezione (/interpelli,
// /selezione-personale, /bandi) stanno tutte in sitemap-categorie.xml: dichiarare
// lo stesso <loc> in due file rende inutilizzabili i conteggi di Search Console.
export async function GET() {
  try {
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://edunews24.it/privacy</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>
  <url>
    <loc>https://edunews24.it/chi-siamo</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>
  <url>
    <loc>https://edunews24.it/collaborazione</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400'
      }
    });

  } catch (error) {
    console.error('Error generating sitemap for static pages:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}
