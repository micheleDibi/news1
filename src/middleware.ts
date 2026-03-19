import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async ({ request, rewrite }, next) => {
  const host = request.headers.get('host')?.split(':')[0];

  if (host === 'linkinbio.edunews24.it') {
    return rewrite('/linkinbio');
  }

  return next();
});
