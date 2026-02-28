export async function GET() {
  try {
    // Start XML content for static pages
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://edunews24.it/privacy</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>
  <url>
    <loc>https://edunews24.it/chi-siamo</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>
  <url>
    <loc>https://edunews24.it/collaborazione</loc>
    <changefreq>monthly</changefreq>
    <priority>1</priority>
  </url>

</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        // Cache for longer since these are static pages
        'Cache-Control': 'public, max-age=86400' // Cache for 24 hours
      }
    });

  } catch (error) {
    console.error('Error generating sitemap for static pages:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}
