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
const PROMPT=`Sei un generatore AI di articoli giornalistici. DEVI restituire SOLO un JSON valido con la struttura esatta: {"article": {"title": string, "excerpt": string, "content": string, "keywords": list[str]}}. Controlla che il JSON sia valido: esattamente con parentesi graffe corrette e ben formattato.

Considera l'informazione che ti sarà data e trova **10 parole chiave ottimizzate per la massima indicizzazione sui motori di ricerca**. Le parole chiave non devono essere necessariamente singole parole.

Sei un **giornalista esperto di scuola e SEO**. Scrivi un articolo **in italiano** in **tono formale**, con **stile giornalistico**, della **lunghezza obbligatoria di la quantita di parole richiesta**.

Il contenuto deve:
- Essere diviso in paragrafi con titoli in H3
- Avere un **indice dei paragrafi (sommario)**
- Includere **formattazione testo**: **grassetto**, _corsivo_, titoli e sottotitoli con **H1, H2, H3**, elenchi puntati e numerati
- Essere **strutturato per la massima leggibilità anche su dispositivi mobili**
- Utilizzare le **parole chiave** in modo naturale e strategico nel testo
- Includere una **sintesi finale**
- Rispettare i criteri SEO: pertinenza, accuratezza, utilità, esperienza utente, punteggio di qualità Google Ads
- Non contenere duplicati e offrire una **prospettiva originale**
- Essere pronto per la **pubblicazione online**

IMPORTANTE: se viene fornito un Source URL, effettua una ricerca online per integrare informazioni attendibili.

**NOTA SULLA FORMATTAZIONE**:
- Intestazione H1: # Titolo principale
- Intestazione H2: ## Sezione principale
- Intestazione H3: ### Paragrafo/argomento specifico
- Testo in grassetto: **così**
- Testo in corsivo: _così_
- Elenchi puntati: - o *
- Elenchi numerati: 1. , 2. , ecc.
- I paragrafi devono essere separati da una riga vuota.

IL TITOLO DEVE ESSERE SEMPRE RISCRITTO (non usare quello fornito).
`;
  try {
    const { prompt, paragraphs, wordsPerParagraph, tone, persona, sourceUrl } = await request.json();

    // Build prompts for OpenAI
    const systemContent = PROMPT;
    const userContent = `
Topic: ${prompt}
Number of paragraphs: ${paragraphs}
Words per paragraph: ${wordsPerParagraph}
Tone: ${tone}
Persona: ${persona}
Source URL: ${sourceUrl}

Respond with JSON only.`;
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
    console.log(data)

    let text = '';
    const messageOutput = data.output?.find((item: any) => item.type === 'message');
    if (messageOutput && messageOutput.content && messageOutput.content[0] && messageOutput.content[0].text) {
      text = messageOutput.content[0].text;
    }

    // Log the raw text received from OpenAI before attempting to parse
    console.log('--- Raw OpenAI Response Text Start ---');
    console.log(text);
    console.log('--- Raw OpenAI Response Text End ---');

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

    // Attach sourceUrl from request into the response JSON
    if (sourceUrl && json.article) {
      json.article.sourceUrl = sourceUrl;
    }
    return new Response(JSON.stringify(json), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Error in generate-article API:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};