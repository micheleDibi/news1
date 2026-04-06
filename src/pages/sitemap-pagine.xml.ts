export async function GET() {
  try {
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://edunews24.it/privacy</loc>
  </url>
  <url>
    <loc>https://edunews24.it/chi-siamo</loc>
  </url>
  <url>
    <loc>https://edunews24.it/collaborazione</loc>
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
