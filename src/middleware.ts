import { defineMiddleware } from 'astro:middleware';

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

  if (host === 'linkinbio.edunews24.it' && url.pathname !== '/linkinbio') {
    return rewrite('/linkinbio');
  }

  return next();
});
