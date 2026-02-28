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

  const SUMMARY_PROMPT = `Sei un esperto copywriter e content strategist. DEVI restituire SOLO un JSON valido con la struttura esatta: {"title_summary": "titolo_del_riassunto", "summary": "contenuto_del_riassunto"}.

1. **TITLE_SUMMARY** Il titolo del riassunto (60 caratteri massimo).

2. **SUMMARY** (150 caratteri): Il contenuto del riassunto che:
   - Catturi tutti i punti chiave dell'articolo
   - Mantenga il tono giornalistico professionale
   - Includa le informazioni più importanti
   - Sia utile per i lettori che vogliono i punti salienti

Il riassunto deve essere:
- In italiano
- Scritto in modo professionale e giornalistico
- Coinvolgente per il lettore
- Strutturato logicamente

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
    const systemContent = SUMMARY_PROMPT;
    const userContent = `
Titolo: ${title}
Estratto esistente: ${excerpt || 'N/A'}
Contenuto: ${content}

Genera summary e title_summary ottimizzati per questo articolo. Rispondi solo con JSON.`;
    
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
    console.log('Summary generation response:', data);

    let text = '';
    const messageOutput = data.output?.find((item: any) => item.type === 'message');
    if (messageOutput && messageOutput.content && messageOutput.content[0] && messageOutput.content[0].text) {
      text = messageOutput.content[0].text;
    }

    console.log('Raw OpenAI summary response:', text);

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
    console.error('Error in generate-summary API:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 