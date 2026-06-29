import { supabaseBandi } from '../../../lib/supabase-bandi';

/**
 * Endpoint OG image per pagine dettaglio bando.
 *
 * MVP: restituisce un SVG inline (1200x630) con titolo + ente + scadenza.
 * Zero dipendenze. Cache 24h.
 *
 * TODO future: migrare a PNG vero via `satori` + `@resvg/resvg-js` se i social
 * mostrano problemi con SVG come og:image. Per ora la pagina dettaglio
 * referenzia `/og/bandi/{slug}.svg` come og:image.
 */
export async function GET({ params }: { params: { slug: string } }) {
  const slug = params.slug;
  if (!slug) {
    return new Response('Slug mancante', { status: 400 });
  }

  try {
    const { data, error } = await supabaseBandi
      .from('bando')
      .select('titolo, titolo_breve, titolo_raw, ente_erogatore, data_scadenza, importo_totale_eur')
      .eq('slug', slug)
      .maybeSingle();

    if (error || !data) {
      return new Response('Bando non trovato', { status: 404 });
    }

    const titolo = (data.titolo ?? data.titolo_raw ?? 'Bando') as string;
    const ente = (data.ente_erogatore ?? '') as string;
    const scadenza = data.data_scadenza
      ? new Date(data.data_scadenza as string).toLocaleDateString('it-IT', {
          day: 'numeric', month: 'long', year: 'numeric',
        })
      : null;
    const importo = data.importo_totale_eur
      ? new Intl.NumberFormat('it-IT').format(data.importo_totale_eur as number) + ' €'
      : null;

    function esc(s: string): string {
      return s.replace(/[<>&"']/g, c =>
        ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[c] ?? c),
      );
    }

    const titoloDisplay = titolo.length > 80 ? titolo.slice(0, 77) + '...' : titolo;
    const enteDisplay = ente.length > 60 ? ente.slice(0, 57) + '...' : ente;

    const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e40af"/>
      <stop offset="100%" stop-color="#1e3a8a"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="60" y="60" width="1080" height="510" fill="white" rx="20"/>

  <text x="100" y="140" font-family="system-ui,-apple-system,sans-serif" font-size="22" font-weight="600" fill="#2563eb" letter-spacing="2">
    EDUNEWS24 · BANDI E FINANZIAMENTI
  </text>

  <foreignObject x="100" y="180" width="1000" height="240">
    <div xmlns="http://www.w3.org/1999/xhtml" style="font-family:system-ui,-apple-system,sans-serif;font-size:48px;font-weight:700;color:#0f172a;line-height:1.15;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;">
      ${esc(titoloDisplay)}
    </div>
  </foreignObject>

  ${enteDisplay ? `<text x="100" y="475" font-family="system-ui,-apple-system,sans-serif" font-size="26" fill="#475569">${esc(enteDisplay)}</text>` : ''}

  ${scadenza ? `<g>
    <rect x="100" y="500" width="280" height="40" fill="#dbeafe" rx="6"/>
    <text x="120" y="528" font-family="system-ui,-apple-system,sans-serif" font-size="20" fill="#1e40af" font-weight="600">Scadenza: ${esc(scadenza)}</text>
  </g>` : ''}

  ${importo ? `<g>
    <rect x="${scadenza ? 400 : 100}" y="500" width="240" height="40" fill="#dcfce7" rx="6"/>
    <text x="${scadenza ? 420 : 120}" y="528" font-family="system-ui,-apple-system,sans-serif" font-size="20" fill="#15803d" font-weight="600">${esc(importo)}</text>
  </g>` : ''}
</svg>`;

    return new Response(svg, {
      status: 200,
      headers: {
        'Content-Type': 'image/svg+xml; charset=utf-8',
        'Cache-Control': 'public, max-age=86400',
      },
    });
  } catch (e) {
    console.error('Error generating OG image for slug', slug, e);
    return new Response('Errore generazione OG image', { status: 500 });
  }
}
