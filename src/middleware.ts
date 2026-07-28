import { defineMiddleware } from 'astro:middleware';
import { API_CATALOG, API_CATALOG_CONTENT_TYPE, API_CATALOG_PATH } from './lib/api-catalog';

export const onRequest = defineMiddleware(async ({ request, rewrite }, next) => {
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

  if (host === 'linkinbio.edunews24.it' && url.pathname !== '/linkinbio') {
    return rewrite('/linkinbio');
  }

  return next();
});
