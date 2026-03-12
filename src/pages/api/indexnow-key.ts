export const prerender = false;

import type { APIRoute } from 'astro';

export const GET: APIRoute = async () => {
  const apiKey = import.meta.env.INDEXNOW_API_KEY;

  if (!apiKey) {
    return new Response('IndexNow key not configured', { status: 404 });
  }

  return new Response(apiKey, {
    status: 200,
    headers: { 'Content-Type': 'text/plain' },
  });
};
