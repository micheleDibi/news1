import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async ({ request, rewrite }, next) => {
  const host = request.headers.get('host')?.split(':')[0];
  const url = new URL(request.url);

  if (host === 'linkinbio.edunews24.it' && url.pathname !== '/linkinbio') {
    return rewrite('/linkinbio');
  }

  return next();
});
