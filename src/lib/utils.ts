// Add this utility function to create URL-friendly slugs
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/università/g, 'universita') // Replace università with universita
    .replace(/[^\w\s-]/g, '') // Remove special characters
    .replace(/\s+/g, '-') // Replace spaces with hyphens
    .replace(/--+/g, '-') // Replace multiple hyphens with single hyphen
    .trim();
}

// Function to generate article URLs
export function getArticleUrl(article: { category: string; title: string; slug?: string }): string {
  const categorySlug = slugify(article.category);
  // Use existing slug if available, otherwise generate from title
  const articleSlug = article.slug || slugify(article.title);
  return `/${categorySlug}/${articleSlug}`;
} 

export const secondsToIsoDuration = (totalSeconds: number): string => {
  const safeSeconds = Math.max(0, Math.round(totalSeconds || 0));
  const minutes = Math.floor(safeSeconds / 60); //Math.floor scarta la parte decimale
  const seconds = safeSeconds % 60;
  const minutePart = minutes ? `${minutes}M` : ''; // se minutes>0 rende ed una stringa tipo 2M, altimenti vuoto
  const secondPart = `${seconds || !minutes ? `${seconds}S` : ''}`;//se second>0 oppure non ci sono minuti rende i secondi tipo 15S altrimenti vuoto
  return `PT${minutePart}${secondPart || '0S'}`; //concatenazione
};

export function filenameToIsoDate (filename: string): string | null {
  const match= filename.match(/(\d{4})-(\d{2})-(\d{2}) at (\d{2}).(\d{2}).(\d{2})/);
  if (!match) return null;
  const [_,y,m,d,hh,mm,ss]=match;
  return `${y}-${m}-${d}T${hh}:${mm}:${ss}Z`;
}