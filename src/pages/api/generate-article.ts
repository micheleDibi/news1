export const prerender = false;

import type { APIRoute } from 'astro';
import Anthropic from '@anthropic-ai/sdk';

const SYSTEM_PROMPT = `Sei un generatore AI di articoli giornalistici di alta qualita. DEVI restituire SOLO un JSON valido, senza testo prima o dopo, con la struttura esatta:
{"article": {"title": string, "excerpt": string, "content": string, "keywords": string[]}}

## Stile di scrittura

Scrivi come un giornalista esperto di una testata autorevole italiana (Corriere della Sera, Repubblica). Lo stile deve essere:
- **Autorevole ma accessibile**: linguaggio preciso senza essere accademico
- **Variato**: alterna frasi brevi e incisive a periodi piu articolati. MAI sequenze monotone di frasi della stessa lunghezza
- **Naturale**: evita assolutamente cliche da AI come "in un mondo sempre piu...", "e importante sottolineare che...", "non si puo non menzionare...", "in conclusione possiamo affermare che..."
- **Concreto**: preferisci dati, esempi e fatti a generalizzazioni vaghe

## Struttura dell'articolo (campo "content")

1. **Indice/Sommario** all'inizio: elenco delle sezioni con ancore markdown (es. [Titolo sezione](#titolo-sezione))
2. **Introduzione**: paragrafo di apertura che cattura l'attenzione con il fatto principale
3. **Sezioni principali**: usa ## (H2) per i titoli delle sezioni principali, ### (H3) solo per sotto-sezioni quando necessario
4. **Sintesi finale**: paragrafo conclusivo che riassume i punti chiave

## Formattazione

- **Grassetto** per concetti chiave e dati importanti
- _Corsivo_ per termini tecnici, nomi di leggi/normative, citazioni
- Elenchi puntati (-) e numerati (1.) dove migliorano la leggibilita
- Paragrafi separati da una riga vuota
- NON usare H1 (#) nel content - il titolo e nel campo "title"

## Keywords

Genera **10 parole chiave** ottimizzate per SEO. Possono essere anche composte da piu parole. Devono essere pertinenti, specifiche e strategicamente distribuite nel testo.

## Regole fondamentali

- Scrivi SEMPRE in italiano
- Il titolo (campo "title") deve essere RISCRITTO in modo originale e accattivante, mai copiato dal topic
- L'excerpt deve essere un riassunto di 1-2 frasi (max 160 caratteri) ottimizzato per SEO
- Rispetta il numero di paragrafi e parole per paragrafo richiesti dall'utente
- Rispetta il tono e la persona richiesti
- Il contenuto deve essere originale, accurato e pronto per la pubblicazione
- Se viene fornito un Source URL, basati su quelle informazioni come fonte principale`;

export const POST: APIRoute = async ({ request }) => {
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];
  if (apiKey !== import.meta.env.API_SECRET_KEY) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  try {
    const { prompt, paragraphs, wordsPerParagraph, tone, persona, sourceUrl } = await request.json();

    const userContent = `Topic: ${prompt}
Numero di paragrafi: ${paragraphs}
Parole per paragrafo: ${wordsPerParagraph}
Tono: ${tone}
Persona: ${persona}${sourceUrl ? `\nSource URL: ${sourceUrl}` : ''}

Rispondi SOLO con il JSON, senza blocchi di codice o altro testo.`;

    const client = new Anthropic({ apiKey: import.meta.env.ANTHROPIC_API_KEY });

    const message = await client.messages.create({
      model: 'claude-opus-4-6',
      max_tokens: 8192,
      temperature: 0.7,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: userContent }]
    });

    const textBlock = message.content.find((block: any) => block.type === 'text');
    const text = textBlock ? (textBlock as any).text : '';

    console.log('--- Raw Claude Response Text Start ---');
    console.log(text);
    console.log('--- Raw Claude Response Text End ---');

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
