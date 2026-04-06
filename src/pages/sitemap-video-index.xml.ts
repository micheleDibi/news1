import { supabase } from '../lib/supabase';

function getTodayDateWithItalianTimezone(): string {
  const now = new Date();
  const options: Intl.DateTimeFormatOptions = {
    timeZone: 'Europe/Rome',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  };
  const formatter = new Intl.DateTimeFormat('it-IT', options);
  const parts = formatter.formatToParts(now);
  const year = parts.find(part => part.type === 'year')?.value || '';
  const month = parts.find(part => part.type === 'month')?.value || '';
  const day = parts.find(part => part.type === 'day')?.value || '';
  return `${year}-${month}-${day}`;
}

export async function GET() {
  try {
    // Ottieni tutti gli articoli con video per estrarre i mesi distinti
    const { data: articles, error } = await supabase
      .from('articles')
      .select('published_at')
      .eq('isdraft', false)
      .not('video_url', 'is', null)
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Raggruppa per anno-mese
    const months = new Map<string, string>();
    (articles || []).forEach(a => {
      const d = new Date(a.published_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      if (!months.has(key)) {
        months.set(key, new Date(a.published_at).toISOString());
      } else {
        const existing = new Date(months.get(key)!);
        const current = new Date(a.published_at);
        if (current > existing) {
          months.set(key, current.toISOString());
        }
      }
    });

    const today = getTodayDateWithItalianTimezone();

    // Ordina mesi dal più recente
    const sortedMonths = Array.from(months.entries()).sort((a, b) => b[0].localeCompare(a[0]));

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://edunews24.it/sitemap-video.xml</loc>
    <lastmod>${today}</lastmod>
  </sitemap>`;

    for (const [month, lastmod] of sortedMonths) {
      xml += `
  <sitemap>
    <loc>https://edunews24.it/sitemap-video/${month}.xml.gz</loc>
    <lastmod>${new Date(lastmod).toISOString()}</lastmod>
  </sitemap>`;
    }

    xml += `
</sitemapindex>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=3600',
      },
    });

  } catch (error) {
    console.error('Error generating video sitemap index:', error);
    return new Response('Error generating video sitemap index', { status: 500 });
  }
}
