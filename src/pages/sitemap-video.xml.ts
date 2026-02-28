import { supabase } from '../lib/supabase';
import { randomVideos } from '@/lib/randomVideos';

const siteUrl = 'https://edunews24.it';
const VIDEO_FILE_REGEX = /\.(mp4|mov|m4v|avi|mpeg|mpg|webm)$/i;

const distinctPlayer = (playerUrl: string | undefined, loc: string) =>
  playerUrl && playerUrl !== loc ? playerUrl : undefined;

type VideoEntry = {
  loc: string;              // pagina di visualizzazione
  lastmod?: string;
  title: string;
  description: string;
  thumbnail: string;
  contentUrl?: string;      // file mp4
  playerUrl?: string;       // pagina player/embed
  changefreq?: string;
  priority?: string;
  duration?: number;
  publicationDate?: string;
};

export async function GET() {
  // Articoli con video (da includere solo se hai una pagina di view per quel video)
  const { data: articles, error } = await supabase
    .from('articles')
    .select('video_url, video_duration, thumbnail_url, image_url, published_at, category_slug, slug, isdraft,title,excerpt,summary')
    .eq('isdraft', false)
    .not('video_url', 'is', null)
    .order('published_at', { ascending: false })
    .limit(1000);

  if (error) {
    console.error('Error getting articles with video:', error);
    return new Response('Error generating sitemap', { status: 500 });
  }

  // Statici: plugin API + 5 video “chi siamo”
  const staticVideos: VideoEntry[] = [
    {
      loc: `${siteUrl}/video/plugin-api`,
      lastmod: '2025-06-30T00:00:00Z',
      title: 'Come ricevere le nostre notizie in tempo reale',
      description:
        'Guida rapida per installare il plugin WordPress ufficiale di EduNews24 e ricevere le notizie in tempo reale.',
      thumbnail: `${siteUrl}/video-api.png`,
      contentUrl: `${siteUrl}/video-api.mp4`,
      playerUrl: undefined, // evitiamo player_loc uguale a loc
      changefreq: 'monthly',
      priority: '0.8',
      duration: 10,
      publicationDate: '2023-01-01T00:00:00Z',
    },
    ...randomVideos.map(name => {
      const base = name.replace(/\.mp4$/i, ''); // pagina senza estensione
      const encPage = encodeURIComponent(base);
      const encFile = encodeURIComponent(name);
      return {
        loc: `${siteUrl}/video/${encPage}`,
        lastmod: '2025-06-30T00:00:00Z',
        title: 'Chi siamo - EduNews24',
        description: 'Video di presentazione del team EduNews24.',
        thumbnail: `${siteUrl}/random-chisiamo/${encFile.replace(/\.mp4$/i, '.png')}`,
        contentUrl: `${siteUrl}/random-chisiamo/${encFile}`,
        playerUrl: undefined, // nessun player separato
        changefreq: 'monthly',
        priority: '0.6',
        duration: 10,
        publicationDate: '2023-01-01T00:00:00Z',
      };
    }),
  ];

  // Eventuali video degli articoli: ora puntano alla pagina videomaker dedicata
  const articleVideos: VideoEntry[] = (articles || [])
    .map(a => {
      const pageUrl = `${siteUrl}/${a.category_slug}/${a.slug}`;
      const videoPageUrl = `${siteUrl}/video/videomaker-${encodeURIComponent(a.slug)}`;
      const fileUrl = (typeof a.video_url === 'string' && a.video_url.trim()) || '';
      if (!fileUrl) return null;

      const isDirectFile = VIDEO_FILE_REGEX.test(fileUrl);
      const contentUrl = isDirectFile ? fileUrl : undefined;
      const playerUrl = !isDirectFile ? distinctPlayer(fileUrl, videoPageUrl) : undefined;
      // Evita player_loc/content_loc uguali a loc
      const safePlayerUrl = playerUrl && playerUrl !== videoPageUrl ? playerUrl : undefined;
      const safeContentUrl = contentUrl && contentUrl !== videoPageUrl ? contentUrl : undefined;
      if (!safeContentUrl && !safePlayerUrl) return null;

      const thumbDb = (a as any).thumbnail_url as string | null;
      const imageUrl = (a as any).image_url as string | null;
      // Fallback: prova a derivare una thumb dal file (es. mp4 -> webp/png)
      const fallbackThumb = fileUrl.replace(/\.(mp4|mov|m4v|avi|mpeg|mpg)$/i, '.webp');
      const thumb = (thumbDb && thumbDb.trim()) || (imageUrl && imageUrl.trim()) || fallbackThumb;
      const duration = typeof (a as any).video_duration === 'number' ? Math.round((a as any).video_duration) : undefined;

      return {
        loc: videoPageUrl, // pagina video dedicata
        lastmod: a.published_at ? new Date(a.published_at).toISOString() : undefined,
        title: a.title||'Video dell’articolo',
        description: (a as any).summary || a.excerpt||'Video incluso nell’articolo.',
        thumbnail: thumb,
        contentUrl: safeContentUrl,
        playerUrl: safePlayerUrl,
        changefreq: 'weekly',
        priority: '0.7',
        publicationDate: a.published_at ? new Date(a.published_at).toISOString() : undefined,
        duration,
      };
    })
    .filter(Boolean) as VideoEntry[];

  // Dedup
  const seen = new Set<string>();
  const entries = [...staticVideos, ...articleVideos].filter(e => {
    const hasVideoLink = Boolean(e.contentUrl || (e.playerUrl && e.playerUrl !== e.loc));
    if (!hasVideoLink || !e?.loc) return false;
    if (seen.has(e.loc)) return false;
    seen.add(e.loc);
    return true;
  });

  let xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset
  xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
  xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">`;

  for (const e of entries) {
    xml += `
  <url>
    <loc>${e.loc}</loc>
    ${e.lastmod ? `<lastmod>${e.lastmod}</lastmod>` : ''}
    ${e.changefreq ? `<changefreq>${e.changefreq}</changefreq>` : ''}
    ${e.priority ? `<priority>${e.priority}</priority>` : ''}
    <video:video>
      <video:thumbnail_loc>${e.thumbnail}</video:thumbnail_loc>
      <video:title><![CDATA[${e.title}]]></video:title>
      <video:description><![CDATA[${e.description}]]></video:description>
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

  return new Response(xml, {
    status: 200,
    headers: {
      'Content-Type': 'application/xml',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
