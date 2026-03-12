export const prerender = false;

import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ params }) => {
  const apiKey = import.meta.env.INDEXNOW_API_KEY;

  if (!apiKey || params.key !== apiKey) {
    return new Response('Not found', { status: 404 });
  }

  return new Response(apiKey, {
    status: 200,
    headers: { 'Content-Type': 'text/plain' },
  });
};
