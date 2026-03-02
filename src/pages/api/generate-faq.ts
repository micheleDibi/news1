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

  const FAQ_PROMPT = `Sei un esperto di content marketing e SEO per il settore istruzione, scuola e università in Italia.

Analizza il titolo e il contenuto dell'articolo forniti e genera da 4 a 6 domande frequenti (FAQ) pertinenti e utili.

Requisiti:
- Le domande devono essere quelle che un lettore si porrebbe naturalmente dopo aver letto l'articolo
- Le risposte devono essere concise ma esaustive (2-4 frasi ciascuna)
- Usa un tono informativo e professionale
- Le domande devono coprire aspetti diversi dell'argomento
- Tutte in italiano
- Le risposte devono basarsi sulle informazioni presenti nell'articolo

IMPORTANTE: Restituisci ESCLUSIVAMENTE un JSON valido nel formato:
{"faqs": [{"question": "Domanda 1?", "answer": "Risposta 1."}, {"question": "Domanda 2?", "answer": "Risposta 2."}]}`;

  try {
    const { title, content } = await request.json();

    if (!title || !content) {
      return new Response(JSON.stringify({ error: 'Title and content are required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const userContent = `
Titolo: ${title}
Contenuto: ${content}

Genera 4-6 FAQ pertinenti per questo articolo. Rispondi solo con JSON.`;

    const combinedInput = `${FAQ_PROMPT}\n\n${userContent}`;

    const response = await fetch('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${import.meta.env.OPENAI_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: 'gpt-4.1',
        input: combinedInput,
        temperature: 0.7
      })
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`OpenAI error: ${errText}`);
    }

    const data = await response.json();

    let text = '';
    const messageOutput = data.output?.find((item: any) => item.type === 'message');
    if (messageOutput && messageOutput.content && messageOutput.content[0] && messageOutput.content[0].text) {
      text = messageOutput.content[0].text;
    }

    let json;
    try {
      json = JSON.parse(text);
    } catch (parseError) {
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
    console.error('Error in generate-faq API:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};
