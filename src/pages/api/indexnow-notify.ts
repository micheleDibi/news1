export const prerender = false;

import type { APIRoute } from 'astro';
import { submitToIndexNow } from '../../lib/indexnow';
import { segretoValido } from '../../lib/verifica-segreto';

export const POST: APIRoute = async ({ request }) => {
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];

  // Fail-closed: senza API_SECRET_KEY configurata nessuna chiave e' accettata
  // (il vecchio confronto diretto con la variabile assente dava
  // `undefined !== undefined` = false e lasciava passare chiunque; fix 8.a.25).
  if (!segretoValido(apiKey, import.meta.env.API_SECRET_KEY)) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const { urls } = await request.json();

    if (!urls || !Array.isArray(urls) || urls.length === 0) {
      return new Response(JSON.stringify({ error: 'urls array is required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    await submitToIndexNow(urls);

    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    console.error('[indexnow-notify] Error:', error);
    return new Response(JSON.stringify({ error: 'Internal Server Error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
