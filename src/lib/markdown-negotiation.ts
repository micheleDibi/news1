/**
 * Content negotiation "Markdown for Agents": quando una richiesta arriva con
 * `Accept: text/markdown`, il middleware serve una versione markdown della
 * pagina invece dell'HTML. I browser normali ricevono l'HTML come sempre.
 */
import { NodeHtmlMarkdown } from 'node-html-markdown';

/** True se il client chiede esplicitamente markdown. */
export function wantsMarkdown(request: Request): boolean {
  return (request.headers.get('accept') ?? '').includes('text/markdown');
}

/**
 * Converte l'HTML di una pagina in markdown. Estrae il contenuto principale
 * (`<main>`, unico per pagina; header/nav/ticker/footer del Layout restano
 * fuori); se non c'è `<main>` (es. eu-funding) ripiega sull'intero documento.
 * Il titolo della pagina viene anteposto come H1 quando la <main> non ne ha
 * gia' uno in cima.
 */
export function htmlToMarkdown(html: string): string {
  const mainMatch = html.match(/<main\b[^>]*>([\s\S]*)<\/main>/i);
  const source = mainMatch ? mainMatch[1] : html;
  const body = NodeHtmlMarkdown.translate(source).trim();

  const title = extractTitle(html);
  if (title && !body.startsWith('# ')) {
    return `# ${title}\n\n${body}\n`;
  }
  return `${body}\n`;
}

/** Stima grezza dei token per l'header x-markdown-tokens (~4 char/token). */
export function estimateTokens(markdown: string): number {
  return Math.ceil(markdown.length / 4);
}

function extractTitle(html: string): string | null {
  const m = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (!m) return null;
  const raw = m[1].replace(/\s+/g, ' ').trim();
  // Toglie il suffisso brand (" - EduNews24") per non duplicarlo nell'H1.
  return raw.replace(/\s*[-|]\s*EduNews24\s*$/i, '').trim() || null;
}
