import { categories } from '../lib/categories';

export async function GET() {
  try {
    // Start XML content for categories
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    // Add static pages
    xml += `
  <url>
    <loc>https://edunews24.it/interpelli</loc>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`;
    xml += `
  <url>
    <loc>https://edunews24.it/selezione-personale</loc>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`;

    // Add all categories from the categories.ts file
    categories.forEach(category => {
      xml += `
  <url>
    <loc>https://edunews24.it/${category.slug}</loc>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>`;
    });

    // Close XML
    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        // Cache for a day since categories don't change often but might be updated
        'Cache-Control': 'public, max-age=43200' // Cache for 12 hours
      }
    });

  } catch (error) {
    console.error('Error generating sitemap for categories:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }
}