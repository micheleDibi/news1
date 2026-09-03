/**
 * Sitemap storica di interpelli, ora spezzata in blocchi da 1000 URL sotto
 * /sitemap-interpelli/N.xml ed elencata direttamente in /sitemap-index.xml.
 *
 * L'URL resta valido con un 301 perche' e' gia' stato inviato a Search Console e
 * puo' essere referenziato altrove. Servire qui il contenuto dell'indice non era
 * possibile: sitemap-index.xml elenca questo file, e un file indice non puo'
 * elencare altri file indice.
 */
export async function GET() {
  return new Response(null, {
    status: 301,
    headers: {
      Location: 'https://edunews24.it/sitemap-index.xml',
      'Cache-Control': 'public, max-age=86400',
    },
  });
}
