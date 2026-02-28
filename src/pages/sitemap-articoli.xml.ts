import { supabase, type Article } from '../lib/supabase';

// Interfaccia per il raggruppamento articoli
interface ArticleGroup {
  year: number;
  month: number;
  day: number;
  count: number;
  lastmod: string;
}

export async function GET() {
  try {
    // Get all published articles with pagination
    let allArticles: Pick<Article, 'title' | 'slug' | 'category_slug' | 'published_at'>[] = [];
    let page = 0;
    const pageSize = 1000;
    let hasMoreData = true;

    while (hasMoreData) {
      const { data: articles, error } = await supabase
        .from('articles')
        .select('title, slug, category_slug, published_at')
        .eq('isdraft', false)
        .order('published_at', { ascending: false })
        .range(page * pageSize, (page + 1) * pageSize - 1);

      if (error) {
        throw error;
      }

      if (articles && articles.length > 0) {
        allArticles = [...allArticles, ...articles];
        
        // Check if we received a full page of resultsa
        if (articles.length < pageSize) {
          hasMoreData = false;
        }
      } else {
        hasMoreData = false;
      }
      
      page++;
    }

    // Raggruppa gli articoli per anno, mese e giorno
    const articleGroups: Map<string, ArticleGroup> = new Map();

    if (allArticles.length > 0) {
      allArticles.forEach(article => {
        const pubDate = new Date(article.published_at);
        const year = pubDate.getFullYear();
        const month = pubDate.getMonth() + 1; // JavaScript mesi sono 0-indexed
        const day = pubDate.getDate();
        
        // Crea una chiave unica per questo gruppo anno/mese/giorno
        const groupKey = `${year}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
        
        if (articleGroups.has(groupKey)) {
          // Incrementa il conteggio per questo gruppo
          const group = articleGroups.get(groupKey)!;
          group.count++;
          
          // Aggiorna lastmod se questo articolo è più recente
          const currentLastmod = new Date(group.lastmod);
          const thisArticleDate = new Date(article.published_at);
          if (thisArticleDate > currentLastmod) {
            group.lastmod = article.published_at;
          }
        } else {
          // Crea un nuovo gruppo
          articleGroups.set(groupKey, {
            year,
            month,
            day,
            count: 1,
            lastmod: article.published_at
          });
        }
      });
    }

    // Start XML content - sitemap index
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;

    // Converti la Map in array e ordina per data (più recente prima)
    const sortedGroups = Array.from(articleGroups.values()).sort((a, b) => {
      // Ordina per anno (decrescente)
      if (a.year !== b.year) return b.year - a.year;
      // Poi per mese (decrescente)
      if (a.month !== b.month) return b.month - a.month;
      // Infine per giorno (decrescente)
      return b.day - a.day;
    });

    // Aggiungi sitemap per ogni gruppo anno/mese/giorno
    sortedGroups.forEach(group => {
      const { year, month, day, lastmod } = group;
      
      // Formatta la data per l'URL
      const formattedMonth = month.toString().padStart(2, '0');
      const formattedDay = day.toString().padStart(2, '0');
      
      // Formatta lastmod in formato W3C datetime (YYYY-MM-DDTHH:MM:SSZ)
      const lastmodDate = new Date(lastmod);
      const formattedLastmod = lastmodDate.toISOString();
      
      xml += `
  <sitemap>
    <loc>https://edunews24.it/sitemap-articoli-giornalieri.xml?anno=${year}&amp;mese=${formattedMonth}&amp;giorno=${formattedDay}</loc>
    <lastmod>${formattedLastmod}</lastmod>
  </sitemap>`;
    });

    // Close XML
    xml += `
</sitemapindex>`;

    return new Response(xml, {
      status: 200,
      headers: {
        'Content-Type': 'application/xml',
        'Cache-Control': 'public, max-age=86400' // Cache per 24 ore
      }
    });

  } catch (error) {
    console.error('Error generating sitemap-articoli:', error);
    return new Response('Error generating sitemap-articoli', { status: 500 });
  }
}