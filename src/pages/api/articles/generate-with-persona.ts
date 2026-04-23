export const prerender = false;

import type { APIRoute } from 'astro';
import { Agent } from 'undici';

const BACKEND_URL = import.meta.env.BACKEND_URL || 'http://localhost:8000';

// La skill news-angle-rewriter-persona (Firecrawl + Claude Agent SDK +
// fact-check + validazione tono/persona) richiede tipicamente 5-7 minuti.
// Il default di undici e' 5 minuti, quindi estendiamo a 15 minuti per
// evitare 502 spurii mentre il backend sta ancora completando.
const longRunAgent = new Agent({
  headersTimeout: 15 * 60 * 1000,
  bodyTimeout: 15 * 60 * 1000,
  connectTimeout: 30 * 1000,
});

export const POST: APIRoute = async ({ request }) => {
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];
  if (apiKey !== import.meta.env.API_SECRET_KEY) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Body JSON non valido', detail: String(err) }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/api/articles/generate-with-persona`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      // @ts-ignore undici dispatcher option non tipizzata nel fetch standard
      dispatcher: longRunAgent,
    });
    const data = await res.json();
    return new Response(JSON.stringify(data), {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Backend non raggiungibile', detail: String(err) }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
