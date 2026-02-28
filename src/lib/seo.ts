/**
 * SEO utility functions for EduNews24
 */

import { secondsToIsoDuration } from './utils';
import { randomVideos } from './randomVideos';

/**
 * Pings search engines to notify them of new content
 * @param url The URL of the new content
 */
export async function pingSearchEngines(url: string): Promise<void> {
  const searchEngines = [
    `https://www.google.com/ping?sitemap=${encodeURIComponent(url)}`,
    `https://www.bing.com/ping?sitemap=${encodeURIComponent(url)}`
  ];

  try {
    await Promise.all(
      searchEngines.map(engine => 
        fetch(engine, { method: 'GET' })
          .then(response => {
            if (!response.ok) {
              console.warn(`Failed to ping search engine: ${engine}`);
            }
          })
          .catch(error => {
            console.error(`Error pinging search engine: ${engine}`, error);
          })
      )
    );
    console.log('Successfully pinged search engines');
  } catch (error) {
    console.error('Error pinging search engines:', error);
  }
}

/**
 * Generates structured data for an article
 * @param article The article data
 * @returns JSON-LD structured data as a string
 */
export function generateArticleStructuredData(article: any): string {
  const articleUrl = `https://edunews24.it/${article.category_slug}/${article.slug}`;
  const timestamp = new Date(article.published_at).toISOString();
  const modifiedTimestamp = article.updated_at ? new Date(article.updated_at).toISOString() : timestamp;
  
  const structuredData: any = {
    "@context": "http://schema.org",
    "@type": "NewsArticle",
    "headline": article.title,
    "url": articleUrl,
    "image": {
      "@type": "ImageObject",
      "url": article.image_url,
      "width": "1200",
      "height": "800"
    },
    "thumbnailUrl": article.image_url,
    "dateCreated": timestamp,
    "articleBody": article.content,
    "articleSection": article.category,
    "keywords": article.tags && article.tags.length > 0 ? article.tags : ["intelligenza artificiale", "scuola", "studenti", "educazione", "tecnologia"],
    "mainEntityOfPage": articleUrl,
    "datePublished": timestamp,
    "dateModified": modifiedTimestamp,
    "timeZone": "GMT+1",
    "author": {
      "@context": "http://schema.org",
      "@type": "Person",
      "name": article.creator || "Redazione EduNews24",
      "url": "https://edunews24.it"
    },
    "creator": {
      "@type": "Person",
      "name": article.creator || "Redazione EduNews24"
    },
    "publisher": {
      "@type": "Organization",
      "name": "EduNews24",
      "logo": {
        "@context": "http://schema.org",
        "@type": "ImageObject",
        "url": "https://edunews24.it/logo.png",
        "width": "516",
        "height": "120"
      }
    },
    "speakable": {
      "@context": "http://schema.org",
      "@type": "SpeakableSpecification",
      "cssSelector": [".article-excerpt", "h1", ".article-content p:first-of-type"],
      "value": article.excerpt
    },
    "isAccessibleForFree": true
  };

  // Add audio if available
  if (article.audio_url) {
    structuredData.audio = {
      "@type": "AudioObject",
      "contentUrl": article.audio_url,
      "description": `Audio version of article: ${article.title}`,
      "duration": article.audio_duration || "PT2M",
      "encodingFormat": "audio/mpeg",
      "name": article.title
    };
  }

  //Add video if available 
  if (article.video_url){
    structuredData.video={
      "@type": "VideoObject",
      "name": "Video articolo: "+article.title ,
      "description": article.summary,
      "thumbnailUrl": article.thumbnail_url || article.image_url,
      "contentUrl": article.video_url,
      "uploadDate": timestamp,
      //se article.video_duration eiste viene convertito in iso altrimenti undefined
      "duration":article.video_duration ? secondsToIsoDuration(article.video_duration) : undefined    
    };
  }

  /* // Add universal videos for every article
  const universalVideos = [];
  
  // Static video (always the same)
  universalVideos.push({
    "@type": "VideoObject",
    "name": "Come Ricevere le Nostre Notizie in Tempo Reale",
    "description": "Installa il nostro plugin WordPress ufficiale per ricevere notizie in tempo reale. Guida completa all'installazione, configurazione e attivazione del componente nel tuo dashboard.",
    "contentUrl": "https://edunews24.it/video-api.mp4",
    "thumbnailUrl": "https://edunews24.it/video-api.png",
    "uploadDate": "2025-06-30T00:00:00Z",
    "duration": "PT10S"
  });

  // Random video (one from the randomVideos array)
  const encodedList = randomVideos.map(encodeURIComponent);
  const randomVideoFile = encodedList[Math.floor(Math.random() * encodedList.length)];
  const randomVideoPath = `https://edunews24.it/random-chisiamo/${randomVideoFile}`;
  const randomThumbnailPath = randomVideoPath.replace(/\.mp4/i, '.png');
  
  universalVideos.push({
    "@type": "VideoObject",
    "name": "Chi siamo - EduNews24",
    "description": "Scopri la missione e la visione del nostro sito di notizie indipendente. Dal 2024 offriamo informazione di qualità, approfondimenti e analisi sui temi che contano, con l'obiettivo di tenere la nostra comunità sempre informata e aggiornata.",
    "contentUrl": randomVideoPath,
    "thumbnailUrl": randomThumbnailPath,
    "uploadDate": "2025-06-30T00:00:00Z",
    "duration": "PT10S"
  });

  // Add universal videos to structured data
  if (structuredData.video) {
    // If article already has a video, make it an array with all videos
    structuredData.video = [structuredData.video, ...universalVideos];
  } else {
    // If no article video, just add the universal videos
    structuredData.video = universalVideos;
  }
  */

  return JSON.stringify(structuredData);
}

/**
 * Generates breadcrumb structured data for an article
 * @param article The article data
 * @returns JSON-LD structured data for breadcrumbs as a string
 */
export function generateBreadcrumbStructuredData(article: any): string {
  const breadcrumbData = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {
        "@type": "ListItem",
        "position": 1,
        "item": {
          "@type": "Thing",
          "id": "https://edunews24.it/",
          "name": "Home"
        }
      },
      {
        "@type": "ListItem",
        "position": 2,
        "item": {
          "@type": "Thing",
          "id": `https://edunews24.it/${article.category_slug}`,
          "name": article.category
        }
      }
    ]
  };

  // Add article item if it exists (for article pages, not for category pages)
  if (article.slug) {
    const articleUrl = `https://edunews24.it/${article.category_slug}/${article.slug}`;
    breadcrumbData.itemListElement.push({
      "@type": "ListItem",
      "position": 3,
      "item": {
        "@type": "WebPage",
        "id": articleUrl,
        "name": article.title
      }
    });
  }

  return JSON.stringify(breadcrumbData);
}

/**
 * Generates ItemList structured data for a list of articles (e.g., category page)
 * @param articles Array of article objects (should have title, url, image)
 * @param listName Name of the list (e.g., category name)
 * @param listUrl Canonical URL of the list page
 * @returns JSON-LD structured data for ItemList as a string
 */
export function generateItemListStructuredData(articles: any[], listName: string, listUrl: string): string {
  const itemListElement = articles.map((article, index) => ({
    "@type": "ListItem",
    "position": index + 1,
    "url": `https://edunews24.it${article.href}`, // Assuming article.href is the relative path
    "name": article.title,
    // Optionally add image if available in the article object
    ...(article.image && { "image": article.image }) 
  }));

  const structuredData = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "name": listName,
    "url": listUrl,
    "numberOfItems": articles.length,
    "itemListElement": itemListElement
  };

  return JSON.stringify(structuredData);
}

/**
 * Generates meta tags for social sharing
 * @param article The article data
 * @returns Object with meta tag properties
 */
export function generateSocialMetaTags(article: any): Record<string, string> {
  return {
    title: article.title,
    description: article.excerpt || `Leggi l'articolo "${article.title}" su EduNews24`,
    image: article.image_url,
    url: `https://edunews24.it/${article.category_slug}/${article.slug}`,
    type: 'article',
    publishedTime: article.published_at,
    modifiedTime: article.updated_at || article.published_at,
    author: article.creator || "EduNews24 Staff",
    section: article.category
  };
} 








