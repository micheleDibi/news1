/**
 * Rendering del corpo editoriale di un bando.
 *
 * Estratto dalla scheda (`src/pages/bandi/[slug].astro`) per tre motivi, tutti
 * bug reali:
 *  - i segmenti `link` finivano in pagina senza nessun filtro: 115 schede
 *    linkavano l'aggregatore da cui erano state raccolte, 31 presentandolo come
 *    «pagina ufficiale», e `escapeAttr` (che è solo `escapeText`) non ferma
 *    `javascript:`;
 *  - le FAQ venivano lette come `{question, answer}` mentre la skill e il tipo
 *    dichiarano `{q, a: {segments}}`: 23 schede rendevano accordion vuoti;
 *  - `contenuto` è una stringa JSON su 9 righe e un `.sections` su un oggetto
 *    malformato faceva saltare l'intera scheda.
 *
 * Restituisce HTML come stringa (non componenti `.astro`) così che il test
 * `superfici-bandi` possa verificare sotto `node --test` sia il markup sia il
 * Markdown per agenti che il middleware ne ricava, senza rendere un `.astro`.
 *
 * Modulo «foglia»: nessun import impuro.
 */
import { urlPubblicabile } from './domini';
import { slugifica } from '../slug';
import type { SegmentoBando, SezioneBando, VoceFaq } from './tipi';

/** Escape per testo e per valori di attributo: la stessa tabella copre entrambi. */
export function scappa(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c] as string));
}

function testoDi(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function proprieta(oggetto: unknown, nome: string): unknown {
  if (typeof oggetto !== 'object' || oggetto === null || Array.isArray(oggetto)) return undefined;
  return (oggetto as Record<string, unknown>)[nome];
}

// ---------------------------------------------------------------------------
// Normalizzazione dell'ingresso
// ---------------------------------------------------------------------------

/**
 * `contenuto` come lo restituisce PostgREST: normalmente un oggetto
 * `{sections: [...]}`, su 9 righe una stringa JSON. Il parse è guardato: un
 * JSON rotto non deve far fallire la scheda, deve solo lasciarla senza corpo.
 */
function oggettoContenuto(contenuto: unknown): unknown {
  if (typeof contenuto !== 'string') return contenuto;
  const testo = contenuto.trim();
  if (testo === '') return null;
  try {
    return JSON.parse(testo) as unknown;
  } catch {
    return null;
  }
}

/** Le sezioni utilizzabili di un `contenuto`; array vuoto se non ce ne sono. */
export function sezioniDa(contenuto: unknown): SezioneBando[] {
  const sezioni = proprieta(oggettoContenuto(contenuto), 'sections');
  if (!Array.isArray(sezioni)) return [];
  return sezioni.filter((s): s is SezioneBando => typeof proprieta(s, 'type') === 'string');
}

// ---------------------------------------------------------------------------
// Segmenti in linea
// ---------------------------------------------------------------------------

function segmentiDa(v: unknown): SegmentoBando[] {
  if (!Array.isArray(v)) return [];
  return v.filter((s): s is SegmentoBando => typeof proprieta(s, 'text') === 'string');
}

/**
 * Un segmento `link` diventa `<a>` **solo** se l'URL è pubblicabile; altrimenti
 * resta testo. `nofollow` oltre a `noopener noreferrer`: sono link che non
 * abbiamo scelto noi, non li vogliamo avallare.
 */
export function renderSegmenti(segmenti: unknown): string {
  return segmentiDa(segmenti).map((seg) => {
    const testo = scappa(seg.text);
    if (seg.kind === 'bold') return `<strong>${testo}</strong>`;
    if (seg.kind === 'link' && urlPubblicabile((seg as { url?: unknown }).url as string | undefined)) {
      const url = scappa(String((seg as { url: string }).url).trim());
      return `<a href="${url}" class="text-primary underline underline-offset-2 hover:text-primary-dark" target="_blank" rel="noopener noreferrer nofollow">${testo}</a>`;
    }
    return testo;
  }).join('');
}

// ---------------------------------------------------------------------------
// FAQ
// ---------------------------------------------------------------------------

/**
 * Forma dichiarata `{q, a: {segments}}`, con due tolleranze di lettura per le
 * righe già salvate: `{question, answer}` (23 righe) e `{q, a}` con `a` stringa.
 * La tolleranza sta **solo** qui: il resto del codice vede una forma sola.
 */
export function vociFaq(items: unknown): VoceFaq[] {
  if (!Array.isArray(items)) return [];
  const voci: VoceFaq[] = [];
  for (const item of items) {
    const domanda = testoDi(proprieta(item, 'q')) || testoDi(proprieta(item, 'question'));
    if (domanda.trim() === '') continue;
    const a = proprieta(item, 'a');
    const segmenti = segmentiDa(proprieta(a, 'segments'));
    if (segmenti.length > 0) {
      voci.push({ q: domanda, a: { segments: segmenti } });
      continue;
    }
    const piano = testoDi(a) || testoDi(proprieta(item, 'answer'));
    if (piano.trim() === '') continue;
    voci.push({ q: domanda, a: { segments: [{ kind: 'text', text: piano }] } });
  }
  return voci;
}

const FRECCIA_FAQ =
  '<svg class="shrink-0 w-5 h-5 text-[#5b6576] group-open:rotate-180 transition-transform motion-reduce:transition-none" fill="none" ' +
  'stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" ' +
  'stroke-width="2" d="M19 9l-7 7-7-7"/></svg>';

function renderFaq(items: unknown): string {
  const voci = vociFaq(items);
  if (voci.length === 0) return '';
  const dettagli = voci.map((voce) =>
    '<details class="group border-b border-[#e3e7ee]">' +
    '<summary class="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-4 font-heading text-[18px] ' +
    'font-semibold text-[#0a2244] hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ' +
    'focus-visible:outline-primary [&::-webkit-details-marker]:hidden">' +
    scappa(voce.q) + FRECCIA_FAQ + '</summary>' +
    `<p class="pb-4">${renderSegmenti(voce.a.segments)}</p>` +
    '</details>',
  ).join('');
  return `<div class="mt-8 border-t border-[#e3e7ee]">${dettagli}</div>`;
}

// ---------------------------------------------------------------------------
// Corpo
// ---------------------------------------------------------------------------

function renderVoci(items: unknown, tag: 'ul' | 'ol', classi: string): string {
  if (!Array.isArray(items)) return '';
  const voci = items.map((item) => `<li>${renderSegmenti(proprieta(item, 'segments'))}</li>`).join('');
  if (voci === '') return '';
  return `<${tag} class="${classi}">${voci}</${tag}>`;
}

/**
 * Gli id delle ancore degli H2, assegnati nell'ordine in cui compaiono: lo slug
 * del testo (`slugifica`, mai `slugify` di utils.ts) e, se è già preso, il primo
 * fra `-2`, `-3`… ancora libero. Contare le occorrenze per slug non basta:
 * `['FAQ', 'FAQ 2', 'FAQ']` darebbe due volte `faq-2`. Un testo che non produce
 * slug diventa `sezione`. L'indice «In questa pagina» della scheda legge questi
 * id dall'HTML reso, quindi l'algoritmo esiste in un posto solo.
 */
function ancoreH2(): (testo: string) => string {
  const usati = new Set<string>();
  return (testo) => {
    const base = slugifica(testo) || 'sezione';
    let id = base;
    for (let n = 2; usati.has(id); n++) id = `${base}-${n}`;
    usati.add(id);
    return id;
  };
}

/**
 * Corpo della scheda come HTML. I link passano dal filtro, le FAQ si leggono
 * nella forma giusta, gli H2 hanno un `id` per l'indice. Un `contenuto`
 * inutilizzabile dà stringa vuota.
 */
export function renderSezioni(contenuto: unknown): string {
  const pezzi: string[] = [];
  const ancora = ancoreH2();
  for (const sezione of sezioniDa(contenuto)) {
    if (sezione.type === 'h2') {
      const testo = testoDi(sezione.text);
      pezzi.push(
        `<h2 id="${ancora(testo)}" class="mt-11 mb-3 flex scroll-mt-4 items-baseline gap-3 font-heading text-[26px] font-bold tracking-[-.01em] text-[#0a2244] first:mt-0 [counter-increment:sezione] before:font-semibold before:text-[14px] before:tabular-nums before:text-[#004e9c] before:content-[counter(sezione,decimal-leading-zero)]">` +
        `${scappa(testo)}</h2>`,
      );
    } else if (sezione.type === 'h3') {
      pezzi.push(`<h3 class="mt-8 mb-2 font-heading text-[20px] font-semibold text-[#0a2244] first:mt-0">${scappa(testoDi(sezione.text))}</h3>`);
    } else if (sezione.type === 'paragraph') {
      const corpo = renderSegmenti(sezione.segments);
      if (corpo !== '') pezzi.push(`<p class="mt-4 first:mt-0 [h2+&]:mt-0 [h3+&]:mt-0">${corpo}</p>`);
    } else if (sezione.type === 'bullet_list') {
      pezzi.push(renderVoci(sezione.items, 'ul', 'mt-3 flex list-disc flex-col gap-2 pl-[22px] first:mt-0'));
    } else if (sezione.type === 'numbered_list') {
      pezzi.push(renderVoci(sezione.items, 'ol', 'mt-3 flex list-decimal flex-col gap-2 pl-[22px] first:mt-0'));
    } else if (sezione.type === 'faq') {
      pezzi.push(renderFaq(sezione.items));
    }
  }
  return pezzi.filter((p) => p !== '').join('');
}


/**
 * Avviso da mostrare quando c'è un `contenuto` ma non se ne ricava niente: la
 * scheda resta 200 (titolo, date, importi e CTA sono in colonne separate e
 * valgono da soli), ma il lettore deve sapere che il testo manca.
 */
export const AVVISO_CORPO_ASSENTE =
  'Il testo di questa scheda non è al momento disponibile: i dati qui sotto restano validi.';

export interface CorpoBando {
  /** HTML del corpo, stringa vuota se non si è reso niente. */
  html: string;
  /** Avviso da mostrare al posto del corpo, `null` se il corpo c'è o se manca del tutto. */
  avviso: string | null;
}

/**
 * Corpo e avviso in una passata sola.
 *
 * L'avviso si decide su quello che `renderSezioni` produce **davvero**, non sul
 * numero di sezioni: un `contenuto` che parsa e ha sezioni ma rende la stringa
 * vuota (`{sections:[{type:'paragraph',segments:[]}]}`, una faq senza domande,
 * solo `type` sconosciuti) lasciava la pagina muta e senza avviso, cioè proprio
 * il caso che questo modulo esiste per chiudere. In più evita il doppio parse
 * del JSON su ogni scheda.
 */
export function corpoBando(contenuto: unknown): CorpoBando {
  const html = renderSezioni(contenuto);
  const assente = contenuto === null || contenuto === undefined;
  return { html, avviso: !assente && html === '' ? AVVISO_CORPO_ASSENTE : null };
}
