import { defineMiddleware } from 'astro:middleware';
import { API_CATALOG, API_CATALOG_CONTENT_TYPE, API_CATALOG_PATH } from './lib/api-catalog';
import { WEB_BOT_AUTH_JWKS, WEB_BOT_AUTH_CONTENT_TYPE, WEB_BOT_AUTH_DIRECTORY_PATH } from './lib/web-bot-auth';
import { wantsMarkdown, htmlToMarkdown, estimateTokens } from './lib/markdown-negotiation';
import { riscaldaCorpus } from './lib/corpus';

// Riscaldamento della cache delle faccette: parte al primo hit del processo e non
// blocca la richiesta. Serve a evitare che la prima visita a una pagina filtro paghi
// la costruzione del corpus (qualche secondo).
let corpusRiscaldato = false;

export const onRequest = defineMiddleware(async ({ request, rewrite }, next) => {
  if (!corpusRiscaldato) {
    corpusRiscaldato = true;
    riscaldaCorpus();
  }

  const host = request.headers.get('host')?.split(':')[0];
  const url = new URL(request.url);

  // Difesa in profondità: la chiave del service account Google non deve mai
  // essere servita via HTTP. Se per qualsiasi motivo finisse tra gli asset
  // statici, blocchiamo comunque la richiesta a livello applicativo.
  if (url.pathname === '/google-credentials.json' ||
      url.pathname.endsWith('/google-credentials.json')) {
    return new Response('Not Found', { status: 404 });
  }

  // Catalogo API (RFC 9727) per la discovery da parte di agenti: il route
  // scanner di Astro ignora i path che iniziano col punto, quindi il
  // well-known va servito qui.
  if (url.pathname === API_CATALOG_PATH) {
    return new Response(JSON.stringify(API_CATALOG), {
      headers: {
        'Content-Type': API_CATALOG_CONTENT_TYPE,
        'Cache-Control': 'public, max-age=86400',
        'Link': `<${API_CATALOG_PATH}>; rel="api-catalog"`,
      },
    });
  }

  // Web Bot Auth: directory JWKS delle chiavi pubbliche (dotpath ignorato dal
  // route scanner di Astro, quindi va servito qui come l'api-catalog).
  if (url.pathname === WEB_BOT_AUTH_DIRECTORY_PATH) {
    return new Response(JSON.stringify(WEB_BOT_AUTH_JWKS), {
      headers: {
        'Content-Type': WEB_BOT_AUTH_CONTENT_TYPE,
        'Cache-Control': 'public, max-age=86400',
      },
    });
  }

  if (host === 'linkinbio.edunews24.it' && url.pathname !== '/linkinbio') {
    return rewrite('/linkinbio');
  }

  const res = await next();

  // Markdown for Agents: solo se l'agente lo chiede e la risposta è una pagina
  // HTML 200. Il filtro esclude di suo sitemap (XML), api (JSON), redirect e
  // 404; per browser e crawler classici la risposta resta identica.
  if (
    request.method === 'GET' &&
    wantsMarkdown(request) &&
    res.status === 200 &&
    (res.headers.get('content-type') ?? '').includes('text/html')
  ) {
    const markdown = htmlToMarkdown(await res.text());
    const headers = new Headers(res.headers); // preserva Link ed altri header
    headers.set('Content-Type', 'text/markdown; charset=utf-8');
    headers.set('Vary', 'Accept');
    headers.set('x-markdown-tokens', String(estimateTokens(markdown)));
    headers.delete('Content-Length'); // il body è cambiato
    return new Response(markdown, { status: 200, headers });
  }

  return res;
});
