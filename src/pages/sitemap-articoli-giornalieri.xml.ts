// Redirect 301 al nuovo URL path-based
// Vecchio formato: /sitemap-articoli-giornalieri.xml?anno=2024&mese=01&giorno=15
// Nuovo formato:   /sitemap-articoli/2024-01-15.xml

export async function GET({ url }: { url: URL }) {
  const params = url.searchParams;
  const anno = params.get('anno');
  const mese = params.get('mese');
  const giorno = params.get('giorno');

  if (!anno || !mese || !giorno) {
    return new Response('Parametri mancanti. Richiede: anno, mese e giorno.', {
      status: 400,
      headers: { 'Content-Type': 'text/plain' }
    });
  }

  const paddedMese = mese.padStart(2, '0');
  const paddedGiorno = giorno.padStart(2, '0');
  const newUrl = `https://edunews24.it/sitemap-articoli/${anno}-${paddedMese}-${paddedGiorno}.xml`;

  return new Response(null, {
    status: 301,
    headers: {
      'Location': newUrl,
      'Cache-Control': 'public, max-age=86400'
    }
  });
}
