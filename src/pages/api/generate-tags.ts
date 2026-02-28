export const prerender = false;

import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  // Authorization check
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];
  if (apiKey !== import.meta.env.API_SECRET_KEY) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  const TAGS_PROMPT = `Sei un esperto SEO e content strategist. DEVI restituire SOLO un JSON valido con la struttura esatta: {"tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]}.

Analizza il titolo, contenuto e sottotitolo forniti e genera esattamente 5-8 tag/parole chiave ottimizzate per:
- Massima indicizzazione sui motori di ricerca (SEO)
- Rilevanza per il contenuto dell'articolo
- Potenziale di ricerca elevato
- Diversità semantica (evita sinonimi)

I tag devono essere:
- In italiano
- Specifici e pertinenti
- Non troppo generici
- Misti tra parole singole e frasi brevi (2-3 parole max)
- Orientati al pubblico interessato all'argomento

IMPORTANTE: Restituisci SOLO il JSON valido senza testo aggiuntivo.`;

  try {
    const { title, content, excerpt } = await request.json();

    if (!title || !content) {
      return new Response(JSON.stringify({ error: 'Title and content are required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Build prompts for OpenAI - same pattern as existing code
    const systemContent = TAGS_PROMPT;
    const userContent = `
Titolo: ${title}
Sottotitolo/Estratto: ${excerpt || 'N/A'}
Contenuto: ${content}

Genera 5-8 tags ottimizzati per questo articolo. Rispondi solo con JSON.`;
    
    const combinedInput = `${systemContent}\n\n${userContent}`;

    const response = await fetch('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${import.meta.env.OPENAI_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: 'gpt-4.1',
        tools: [{"type": "web_search_preview"}],
        input: combinedInput,
        temperature: 0.7
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`OpenAI error: ${errText}`);
    }

    const data = await response.json();
    console.log('Tags generation response:', data);

    let text = '';
    const messageOutput = data.output?.find((item: any) => item.type === 'message');
    if (messageOutput && messageOutput.content && messageOutput.content[0] && messageOutput.content[0].text) {
      text = messageOutput.content[0].text;
    }

    console.log('Raw OpenAI tags response:', text);

    let json;
    try {
      json = JSON.parse(text);
    } catch (parseError) {
      // Strip any control characters that break JSON.parse
      const cleaned = text.replace(/[\u0000-\u0019]+/g, '');
      try {
        json = JSON.parse(cleaned);
      } catch {
        const match = cleaned.match(/\{[\s\S]*\}/);
        if (match) {
          const objStr = match[0].replace(/[\u0000-\u0019]+/g, '');
          json = JSON.parse(objStr);
        } else {
          throw parseError;
        }
      }
    }

    return new Response(JSON.stringify(json), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    console.error('Error in generate-tags API:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 