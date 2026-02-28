import type { Bando } from '../types/bandi';
import fs from 'fs/promises';
import path from 'path';

const dataFilePath = path.resolve(process.cwd(), 'src/data/bandi.json');

// Function to generate URL-friendly slug from bando data (same as in [slug].astro)
function generateBandoSlug(bando: Bando): string {
  const parts = [
    bando.figuraRicercata,
    bando.sedi?.join('-'),
    bando.entiRiferimento?.join('-'),
    bando.codice
  ].filter(Boolean); // Remove empty/null values
  
  return parts
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9\-]/g, '-') // Replace non-alphanumeric chars with hyphens
    .replace(/-+/g, '-') // Replace multiple hyphens with single hyphen
    .replace(/^-|-$/g, ''); // Remove leading/trailing hyphens
}

async function loadBandiData(): Promise<Bando[]> {
  try {
    const jsonData = await fs.readFile(dataFilePath, 'utf-8');
    const data = JSON.parse(jsonData);
    if (Array.isArray(data)) {
       return data as Bando[];
    } else {
      console.error('Error: bandi.json does not contain a valid array.');
      return [];
    }
  } catch (error) {
    console.error('Error reading or parsing src/data/bandi.json:', error);
    return [];
  }
}

export async function GET() {
  try {
    const bandiData = await loadBandiData();

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    bandiData.forEach(bando => {
      if (bando.dataPubblicazione) {
        const slug = generateBandoSlug(bando);
        if (slug) {
          xml += `
  <url>
    <loc>https://edunews24.it/selezione-personale/${slug}</loc>
    <lastmod>${new Date(bando.dataPubblicazione).toISOString()}</lastmod>
  </url>`;
        }
      }
    });

    xml += `
</urlset>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400' // Cache for 24 hours
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-selezione-personale:', error);
    return new Response('Error generating sitemap-selezione-personale', { status: 500 });
  }
} 