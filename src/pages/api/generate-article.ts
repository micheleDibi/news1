export const prerender = false;

import type { APIRoute } from 'astro';
import Anthropic from '@anthropic-ai/sdk';
import { supabase } from '../../lib/supabase';

const STOP_WORDS_IT = new Set([
  "di", "a", "da", "in", "con", "su", "per", "tra", "fra", "il", "lo", "la",
  "i", "gli", "le", "un", "uno", "una", "e", "o", "ma", "che", "non", "si",
  "del", "dello", "della", "dei", "degli", "delle", "al", "allo", "alla",
  "ai", "agli", "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle",
  "nel", "nello", "nella", "nei", "negli", "nelle", "sul", "sullo", "sulla",
  "sui", "sugli", "sulle", "come", "se", "anche", "piu", "sono", "stato",
  "essere", "ha", "hanno", "questo", "questa", "questi", "queste", "quello",
]);

function extractSignificantWords(text: string): Set<string> {
  return new Set(
    text.split(/\W+/)
      .map(w => w.toLowerCase())
      .filter(w => w.length > 2 && !STOP_WORDS_IT.has(w))
  );
}

async function findRelatedArticles(prompt: string): Promise<{ title: string; slug: string; category_slug: string; score: number }[]> {
  try {
    const { data, error } = await supabase
      .from('articles')
      .select('id, title, slug, category_slug, tags')
      .eq('isdraft', false);

    if (error || !data || data.length === 0) {
      console.log('No articles found for interlinking');
      return [];
    }

    const promptWords = extractSignificantWords(prompt);
    if (promptWords.size === 0) return [];

    const scored: { title: string; slug: string; category_slug: string; score: number }[] = [];

    for (const article of data) {
      // Parse tags
      let existingTags: string[] = [];
      const rawTags = article.tags;
      if (Array.isArray(rawTags)) {
        existingTags = rawTags.filter((t: any) => typeof t === 'string' && t);
      } else if (typeof rawTags === 'string') {
        try { existingTags = JSON.parse(rawTags); } catch { existingTags = []; }
        if (!Array.isArray(existingTags)) existingTags = [];
      }
      const existingTagsSet = new Set(existingTags.map(t => t.toLowerCase().trim()));

      // Tag overlap score (weight 0.6) - match prompt words against tags
      let tagOverlap = 0;
      for (const word of promptWords) {
        if (existingTagsSet.has(word)) tagOverlap++;
        // Also check if prompt word is contained in multi-word tags
        for (const tag of existingTagsSet) {
          if (tag.includes(word) || word.includes(tag)) { tagOverlap++; break; }
        }
      }
      const tagScore = (tagOverlap / Math.max(promptWords.size, 1)) * 0.6;

      // Title keyword overlap score (weight 0.4) - rebalanced since no category
      const titleWords = extractSignificantWords(article.title || '');
      let titleOverlap = 0;
      for (const word of promptWords) {
        if (titleWords.has(word)) titleOverlap++;
      }
      const titleScore = (titleOverlap / Math.max(promptWords.size, 1)) * 0.4;

      const totalScore = tagScore + titleScore;

      if (totalScore > 0.1) {
        scored.push({
          title: article.title,
          slug: article.slug,
          category_slug: article.category_slug,
          score: totalScore,
        });
      }
    }

    scored.sort((a, b) => b.score - a.score);
    const top = scored.slice(0, 3);

    if (top.length > 0) {
      console.log(`Found ${top.length} related articles for interlinking:`);
      for (const a of top) {
        console.log(`  - ${a.title} (score: ${a.score.toFixed(3)}) -> /${a.category_slug}/${a.slug}`);
      }
    }

    return top;
  } catch (e) {
    console.error('Error finding related articles:', e);
    return [];
  }
}

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
5. **Interlink**: se vengono forniti articoli correlati, inseriscili NATURALMENTE nel testo nei punti dove il contesto lo rende pertinente. Formato: [Titolo Articolo](/category-slug/slug). Non forzare l'inserimento se non e contestualmente rilevante. Non creare una sezione separata per i link.

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

    // Find related articles for interlinking
    const relatedArticles = await findRelatedArticles(prompt);
    let interlinksText = '';
    if (relatedArticles.length > 0) {
      interlinksText = '\n\nArticoli correlati disponibili per interlinking (inseriscili naturalmente nel testo dove pertinente):\n';
      for (let i = 0; i < relatedArticles.length; i++) {
        const a = relatedArticles[i];
        interlinksText += `${i + 1}. [${a.title}](/${a.category_slug}/${a.slug})\n`;
      }
    }

    const userContent = `Topic: ${prompt}
Numero di paragrafi: ${paragraphs}
Parole per paragrafo: ${wordsPerParagraph}
Tono: ${tone}
Persona: ${persona}${sourceUrl ? `\nSource URL: ${sourceUrl}` : ''}${interlinksText}

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
