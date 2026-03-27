export const prerender = false;

import type { APIRoute } from 'astro';

const BACKEND_URL = import.meta.env.BACKEND_URL || 'http://localhost:8000';

export const POST: APIRoute = async ({ params }) => {
  try {
    const res = await fetch(`${BACKEND_URL}/api/news/publish/${params.id}`, {
      method: 'POST',
    });
    const data = await res.json();
    return new Response(JSON.stringify(data), {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'Backend non raggiungibile' }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
