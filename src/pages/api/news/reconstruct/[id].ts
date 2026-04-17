export const prerender = false;

import type { APIRoute } from 'astro';
import { Agent } from 'undici';

const BACKEND_URL = import.meta.env.BACKEND_URL || 'http://localhost:8000';

// La skill news-angle-rewriter (Firecrawl + Claude Agent SDK + fact-check)
// richiede tipicamente 5-7 minuti. Il default di undici e' 5 minuti, quindi
// estendiamo a 15 minuti per evitare 502 spurii mentre il backend sta ancora
// completando la generazione.
const longRunAgent = new Agent({
  headersTimeout: 15 * 60 * 1000,
  bodyTimeout: 15 * 60 * 1000,
  connectTimeout: 30 * 1000,
});

export const POST: APIRoute = async ({ params }) => {
  try {
    const res = await fetch(`${BACKEND_URL}/api/news/reconstruct/${params.id}`, {
      method: 'POST',
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
