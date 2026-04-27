export const prerender = false;

import type { APIRoute } from 'astro';

const BACKEND_URL = import.meta.env.BACKEND_URL || 'http://localhost:8000';

export const GET: APIRoute = async ({ params, request }) => {
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];
  if (apiKey !== import.meta.env.API_SECRET_KEY) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const res = await fetch(
      `${BACKEND_URL}/api/articles/generation-status/${params.jobId}`,
      { method: 'GET' }
    );
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
