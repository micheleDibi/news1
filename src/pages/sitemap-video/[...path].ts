import { gzipSync } from 'node:zlib';
import { supabase } from '../../lib/supabase';

const siteUrl = 'https://edunews24.it';
const VIDEO_FILE_REGEX = /\.(mp4|mov|m4v|avi|mpeg|mpg|webm)$/i;

function stripControlChars(text: string): string {
    return text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '');
}

const distinctPlayer = (playerUrl: string | undefined, loc: string) =>
  playerUrl && playerUrl !== loc ? playerUrl : undefined;

export async function GET({ params }: { params: { path: string } }) {
  try {
    const rawPath = params.path;

    // Parse: "2024-01.xml.gz" o "2024-01.xml"
    const gzMatch = rawPath.match(/^(\d{4})-(\d{2})\.xml(\.gz)?$/);
    if (!gzMatch) {
      return new Response('Formato non valido. Richiede: YYYY-MM.xml o YYYY-MM.xml.gz', {
        status: 400,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    const [, anno, mese, isGz] = gzMatch;
    const year = parseInt(anno);
    const month = parseInt(mese);

    const startOfMonth = new Date(Date.UTC(year, month - 1, 1, 0, 0, 0));
    const endOfMonth = new Date(Date.UTC(year, month, 0, 23, 59, 59, 999));

    // Query articoli con video per il mese specificato
    const { data: articles, error } = await supabase
      .from('articles')
      .select('video_url, video_duration, thumbnail_url, image_url, published_at, updated_at, category_slug, slug, isdraft, title, excerpt, summary')
      .eq('isdraft', false)
      .not('video_url', 'is', null)
      .gte('published_at', startOfMonth.toISOString())
      .lte('published_at', endOfMonth.toISOString())
      .order('published_at', { ascending: false });

    if (error) {
      throw error;
    }

    // Costruisci le video entries
    const entries = (articles || [])
      .map(a => {
        const videoPageUrl = `${siteUrl}/video/videomaker-${encodeURIComponent(a.slug)}`;
        const fileUrl = (typeof a.video_url === 'string' && a.video_url.trim()) || '';
        if (!fileUrl) return null;

        const isDirectFile = VIDEO_FILE_REGEX.test(fileUrl);
        const contentUrl = isDirectFile ? fileUrl : undefined;
        const playerUrl = !isDirectFile ? distinctPlayer(fileUrl, videoPageUrl) : undefined;
        const safePlayerUrl = playerUrl && playerUrl !== videoPageUrl ? playerUrl : undefined;
        const safeContentUrl = contentUrl && contentUrl !== videoPageUrl ? contentUrl : undefined;
        if (!safeContentUrl && !safePlayerUrl) return null;

        const thumbDb = (a as any).thumbnail_url as string | null;
        const imageUrl = (a as any).image_url as string | null;
        const fallbackThumb = fileUrl.replace(/\.(mp4|mov|m4v|avi|mpeg|mpg)$/i, '.webp');
        const thumb = (thumbDb && thumbDb.trim()) || (imageUrl && imageUrl.trim()) || fallbackThumb;
        const duration = typeof (a as any).video_duration === 'number' ? Math.round((a as any).video_duration) : undefined;
        const lastmod = a.updated_at || a.published_at;

        return {
          loc: videoPageUrl,
          lastmod: lastmod ? new Date(lastmod).toISOString() : undefined,
          title: a.title || 'Video dell\'articolo',
          description: (a as any).summary || a.excerpt || 'Video incluso nell\'articolo.',
          thumbnail: thumb,
          contentUrl: safeContentUrl,
          playerUrl: safePlayerUrl,
          duration,
          publicationDate: a.published_at ? new Date(a.published_at).toISOString() : undefined,
        };
      })
      .filter(Boolean) as any[];

    // Dedup
    const seen = new Set<string>();
    const uniqueEntries = entries.filter(e => {
      if (!e?.loc || seen.has(e.loc)) return false;
      seen.add(e.loc);
      return true;
    });

    // Genera XML
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset
  xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
  xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">`;

    for (const e of uniqueEntries) {
      xml += `
  <url>
    <loc>${e.loc}</loc>
    ${e.lastmod ? `<lastmod>${e.lastmod}</lastmod>` : ''}
    <video:video>
      <video:thumbnail_loc>${e.thumbnail}</video:thumbnail_loc>
      <video:title><![CDATA[${stripControlChars(e.title).trim()}]]></video:title>
      <video:description><![CDATA[${stripControlChars(e.description).trim()}]]></video:description>
      ${e.contentUrl ? `<video:content_loc>${e.contentUrl}</video:content_loc>` : ''}
      ${e.playerUrl && e.playerUrl !== e.loc ? `<video:player_loc allow_embed="yes">${e.playerUrl}</video:player_loc>` : ''}
      ${e.duration ? `<video:duration>${e.duration}</video:duration>` : ''}
      ${e.publicationDate ? `<video:publication_date>${e.publicationDate}</video:publication_date>` : ''}
      <video:family_friendly>yes</video:family_friendly>
    </video:video>
  </url>`;
    }

    xml += `
</urlset>`;

    // Rispondi con gzip o plain XML
    if (isGz) {
      const compressed = gzipSync(Buffer.from(xml, 'utf-8'));
      return new Response(compressed, {
        status: 200,
        headers: {
          'Content-Type': 'application/x-gzip',
          'Cache-Control': 'public, max-age=86400',
        },
      });
    }

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400',
      },
    });

  } catch (error) {
    console.error('Error generating monthly video sitemap:', error);
    return new Response('Error generating video sitemap', { status: 500 });
  }
}
