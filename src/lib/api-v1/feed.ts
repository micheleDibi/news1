/**
 * Feed dell'API /api/v1: JSON Feed 1.1 e RSS 2.0 degli ultimi elementi di una
 * risorsa (o di una categoria di articoli). Modulo puro: riceve DTO gia' mappati
 * (stessa mappatura del REST) e restituisce il corpo serializzato.
 *
 * - Il percorso del feed si analizza con whitelist e confronti su array
 *   costanti: mai lookup su oggetti letterali (`constructor.json` -> null).
 * - L'XML esce SOLO da `elemento()`, che applica `testoXml()` a ogni testo e a
 *   ogni attributo: niente concatenazioni a mano, niente CDATA.
 * - Le date dei DTO sono gia' RFC 3339 con offset: per RSS si convertono in ms
 *   con istanteTimestamptz e poi in RFC 822 (sempre con l'offset di Roma).
 */
import { configSezione } from '../../config/pagine-filtro';
import { formatDataBando } from '../liste/formato';
import { escapeXml } from '../sitemap';
import { SLUG_VALIDO } from '../slug';
import { BASE_API, CONTENT_SIGNAL, ELEMENTI_FEED, SITO, TESTO_ATTRIBUZIONE, URL_TERMINI } from './costanti';
import { sezioneDto } from './sezioni';
import { istanteTimestamptz, rfc822 } from './tempo';
import type {
  ArticoloDto, OpportunitaDto, Risorsa, SezioneOpportunita, StatoOpportunita, TipoOpportunita,
} from './contratto';

export type FormatoFeed = 'json' | 'xml';

export interface RichiestaFeed {
  risorsa: Risorsa;
  /** Slug della categoria (solo per gli articoli), null per il feed globale. */
  categoria: string | null;
  formato: FormatoFeed;
}

export type ElementoFeed = ArticoloDto | OpportunitaDto;

const RISORSE_FEED: readonly Risorsa[] = ['articles', 'interpelli', 'selezione-personale', 'bandi'];
const FORMATI_FEED: readonly FormatoFeed[] = ['json', 'xml'];
const LUNGHEZZA_MASSIMA_SLUG = 64;
/** Difesa sulla lunghezza: nessun percorso valido si avvicina a questo valore. */
const LUNGHEZZA_MASSIMA_PERCORSO = 128;

// ---------------------------------------------------------------------------
// Percorso
// ---------------------------------------------------------------------------

function separaEstensione(nomeFile: string): { base: string; formato: FormatoFeed } | null {
  const punto = nomeFile.lastIndexOf('.');
  if (punto <= 0) return null;
  const estensione = nomeFile.slice(punto + 1);
  const formato = FORMATI_FEED.find((f) => f === estensione);
  if (formato === undefined) return null;
  return { base: nomeFile.slice(0, punto), formato };
}

/**
 * Analizza il parametro rest della rotta feed (`feeds/[...percorso].ts`).
 * Accetta ESATTAMENTE `<risorsa>.<json|xml>` e `articles/<slug>.<json|xml>`;
 * tutto il resto -> null (404). L'appartenenza della categoria al riferimento la
 * verifica il chiamante: qui si controlla solo la forma dello slug.
 */
export function analizzaPercorsoFeed(percorso: string | undefined): RichiestaFeed | null {
  if (typeof percorso !== 'string' || percorso === '' || percorso.length > LUNGHEZZA_MASSIMA_PERCORSO) return null;
  const segmenti = percorso.split('/');
  if (segmenti.length === 1) {
    const file = separaEstensione(segmenti[0]);
    if (file === null) return null;
    const risorsa = RISORSE_FEED.find((r) => r === file.base);
    return risorsa === undefined ? null : { risorsa, categoria: null, formato: file.formato };
  }
  if (segmenti.length === 2 && segmenti[0] === 'articles') {
    const file = separaEstensione(segmenti[1]);
    if (file === null || file.base.length > LUNGHEZZA_MASSIMA_SLUG || !SLUG_VALIDO.test(file.base)) return null;
    return { risorsa: 'articles', categoria: file.base, formato: file.formato };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Metadati del canale
// ---------------------------------------------------------------------------

export interface MetadatiFeed {
  titolo: string;
  descrizione: string;
  homePageUrl: string;
  feedUrl: string;
  apiUrl: string;
}

function sezioneDiRisorsa(risorsa: Risorsa): SezioneOpportunita | null {
  return risorsa === 'articles' ? null : risorsa;
}

const RIMANDO_TERMINI =
  `Riuso secondo i termini ${URL_TERMINI}: attribuzione "${TESTO_ATTRIBUZIONE}" con link all'originale.`;

/**
 * Titolo, descrizione e URL di un feed. `nomeCategoria` e' il nome validato dal
 * riferimento delle categorie (se manca si ripiega sullo slug).
 */
export function metadatiFeed(richiesta: RichiestaFeed, nomeCategoria: string | null): MetadatiFeed {
  const estensione = richiesta.formato;
  const sezione = sezioneDiRisorsa(richiesta.risorsa);

  if (sezione === null) {
    if (richiesta.categoria === null) {
      return {
        titolo: 'EduNews24 – Ultimi articoli',
        descrizione: `Gli ultimi ${ELEMENTI_FEED} articoli di EduNews24, con sintesi e link all'articolo ` +
          `completo. ${RIMANDO_TERMINI}`,
        homePageUrl: SITO,
        feedUrl: `${BASE_API}/feeds/articles.${estensione}`,
        apiUrl: `${BASE_API}/articles`,
      };
    }
    const nome = nomeCategoria ?? richiesta.categoria;
    return {
      titolo: `EduNews24 – ${nome}`,
      descrizione: `Gli ultimi ${ELEMENTI_FEED} articoli di EduNews24 nella categoria ${nome}, con sintesi e ` +
        `link all'articolo completo. ${RIMANDO_TERMINI}`,
      homePageUrl: `${SITO}/${richiesta.categoria}`,
      feedUrl: `${BASE_API}/feeds/articles/${richiesta.categoria}.${estensione}`,
      apiUrl: `${BASE_API}/articles?category=${richiesta.categoria}`,
    };
  }

  const etichetta = configSezione(sezione).etichetta;
  const contenuto = sezione === 'selezione-personale'
    ? `Le ${ELEMENTI_FEED} schede aggiornate più di recente della sezione ${etichetta} di EduNews24, ` +
      'escluse quelle scadute'
    : `Le ultime ${ELEMENTI_FEED} schede della sezione ${etichetta} di EduNews24`;
  return {
    titolo: `EduNews24 – ${etichetta}`,
    descrizione: `${contenuto}, con sintesi e link alla scheda completa. ${RIMANDO_TERMINI}`,
    homePageUrl: sezioneDto(sezione).url,
    feedUrl: `${BASE_API}/feeds/${sezione}.${estensione}`,
    apiUrl: `${BASE_API}/${sezione}`,
  };
}

// ---------------------------------------------------------------------------
// Voce neutra: un solo punto decide testo, etichette e date per entrambi i formati
// ---------------------------------------------------------------------------

type EstensioneVoce =
  | { type: 'article'; category: string }
  | { type: TipoOpportunita; status: StatoOpportunita | null; deadline_on: string | null };

interface VideoVoce {
  url: string;
  mimeType: string;
  durata: number | null;
}

interface VoceFeed {
  id: string;
  url: string;
  titolo: string;
  sintesi: string | null;
  testo: string;
  immagine: string | null;
  pubblicazione: string;
  modifica: string | null;
  autore: string | null;
  etichette: string[];
  video: VideoVoce | null;
  /** Istante usato per lastBuildDate (RFC 3339). */
  riferimentoAggiornamento: string;
  estensione: EstensioneVoce;
}

/** Tag URI (RFC 4151) stabile della voce. */
function idVoce(tipo: string, id: number): string {
  return `tag:edunews24.it,2026:${tipo}/${id}`;
}

/** Senza vuoti e senza duplicati (confronto senza distinguere maiuscole), nell'ordine dato. */
function senzaDuplicati(valori: readonly string[]): string[] {
  const visti = new Set<string>();
  const risultato: string[] = [];
  for (const valore of valori) {
    const pulito = valore.trim();
    if (pulito === '') continue;
    const chiave = pulito.toLowerCase();
    if (visti.has(chiave)) continue;
    visti.add(chiave);
    risultato.push(pulito);
  }
  return risultato;
}

/** Sintesi, riga "Scadenza" e attribuzione, separate da una riga vuota. */
function testoVoce(sintesi: string | null, scadenza: string | null, rimando: string): string {
  const righe: string[] = [];
  if (sintesi !== null && sintesi !== '') righe.push(sintesi);
  if (scadenza !== null) righe.push(`Scadenza: ${formatDataBando(scadenza)}`);
  righe.push(rimando);
  return righe.join('\n\n');
}

function voceArticolo(a: ArticoloDto): VoceFeed {
  const sintesi = a.summary ?? a.excerpt;
  const video = a.video !== null && a.video.mime_type !== null
    ? { url: a.video.url, mimeType: a.video.mime_type, durata: a.video.duration_seconds }
    : null;
  return {
    id: idVoce('article', a.id),
    url: a.url,
    titolo: a.title,
    sintesi,
    testo: testoVoce(sintesi, null, `Leggi l'articolo completo su EduNews24: ${a.url}`),
    immagine: a.image_url,
    pubblicazione: a.published_at,
    modifica: null,
    autore: a.author.name,
    etichette: senzaDuplicati([a.category.name, ...a.tags]),
    video,
    riferimentoAggiornamento: a.published_at,
    estensione: { type: 'article', category: a.category.slug },
  };
}

function voceOpportunita(o: OpportunitaDto): VoceFeed {
  return {
    id: idVoce(o.type, o.id),
    url: o.url,
    titolo: o.title,
    sintesi: o.summary,
    testo: testoVoce(o.summary, o.deadline_on, `Scheda completa su EduNews24: ${o.url}`),
    immagine: null,
    pubblicazione: o.published_at,
    modifica: o.updated_at,
    autore: null,
    etichette: senzaDuplicati([o.section.name, ...o.regions.map((r) => r.name)]),
    video: null,
    // Selezione: il feed e' ordinato per aggiornamento; le altre per pubblicazione.
    riferimentoAggiornamento: o.type === 'selezione-personale' ? (o.updated_at ?? o.published_at) : o.published_at,
    estensione: { type: o.type, status: o.status, deadline_on: o.deadline_on },
  };
}

function voceDi(elemento: ElementoFeed): VoceFeed {
  return elemento.type === 'article' ? voceArticolo(elemento) : voceOpportunita(elemento);
}

// ---------------------------------------------------------------------------
// JSON Feed 1.1
// ---------------------------------------------------------------------------

function vuoto(valore: unknown): boolean {
  return valore === null || valore === undefined || valore === '' || (Array.isArray(valore) && valore.length === 0);
}

/**
 * Oggetto con i soli membri non vuoti, nell'ordine dato. Le chiavi sono costanti
 * di questo modulo; Object.fromEntries crea proprieta' proprie (anche per nomi
 * speciali), quindi nessun effetto sul prototipo.
 */
function membriNonVuoti(coppie: ReadonlyArray<readonly [string, unknown]>): Record<string, unknown> {
  return Object.fromEntries(coppie.filter(([, valore]) => !vuoto(valore)));
}

function voceJson(v: VoceFeed): Record<string, unknown> {
  const allegati = v.video === null
    ? []
    : [membriNonVuoti([
      ['url', v.video.url],
      ['mime_type', v.video.mimeType],
      ['duration_in_seconds', v.video.durata],
    ])];
  return membriNonVuoti([
    ['id', v.id],
    ['url', v.url],
    ['title', v.titolo],
    ['summary', v.sintesi],
    ['content_text', v.testo],
    ['image', v.immagine],
    ['date_published', v.pubblicazione],
    ['date_modified', v.modifica],
    ['authors', v.autore === null ? [] : [{ name: v.autore }]],
    ['tags', v.etichette],
    ['attachments', allegati],
    // L'estensione e' sempre un oggetto: i suoi null restano (forma fissa per tipo).
    ['_edunews24', v.estensione],
  ]);
}

/** JSON Feed 1.1 (application/feed+json). Mai content_html. */
export function serializzaJsonFeed(meta: MetadatiFeed, elementi: readonly ElementoFeed[]): string {
  const feed = {
    version: 'https://jsonfeed.org/version/1.1',
    title: meta.titolo,
    home_page_url: meta.homePageUrl,
    feed_url: meta.feedUrl,
    description: meta.descrizione,
    favicon: `${SITO}/favicon.ico`,
    language: 'it-IT',
    authors: [{ name: 'EduNews24', url: SITO }],
    _edunews24: { api: meta.apiUrl, terms: URL_TERMINI, content_signal: CONTENT_SIGNAL },
    items: elementi.map((e) => voceJson(voceDi(e))),
  };
  return JSON.stringify(feed);
}

// ---------------------------------------------------------------------------
// XML
// ---------------------------------------------------------------------------

/** Frammento XML costruito da `elemento()`: un testo qualsiasi non e' assegnabile. */
export type FrammentoXml = string & { readonly __frammentoXml: true };

export type AttributiXml = ReadonlyArray<readonly [string, string | number | null]>;

/**
 * Caratteri ammessi in XML 1.0: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] |
 * [#x10000-#x10FFFF]. Con il flag `u` un surrogato spaiato e' un code point a se'
 * (fuori da tutti gli intervalli) e viene rimosso; una coppia valida no.
 */
const NON_XML = /[^\t\n\r -퟿-�\u{10000}-\u{10FFFF}]/gu;

/** Nomi di elementi e attributi: costanti del modulo, validate per difesa. */
const NOME_XML = /^[A-Za-z_][A-Za-z0-9._-]*(?::[A-Za-z_][A-Za-z0-9._-]*)?$/;

/** Testo sicuro per XML 1.0: caratteri non ammessi rimossi, poi escape delle entita'. */
export function testoXml(valore: string): string {
  return escapeXml(valore.replace(NON_XML, ''));
}

function verificaNome(nome: string): void {
  if (!NOME_XML.test(nome)) throw new Error('Nome XML non valido');
}

const FRAMMENTO_VUOTO = '' as FrammentoXml;

/**
 * Unico costruttore di XML. `contenuto`:
 * - stringa: testo, passato da testoXml();
 * - array: figli gia' costruiti da elemento() (i frammenti vuoti si scartano);
 * - null: nessun contenuto.
 * Un elemento senza contenuto (anche testo di soli spazi, o figli tutti vuoti)
 * diventa `<nome attr="…"/>` se ha attributi, altrimenti viene omesso (frammento
 * vuoto): nessun elemento vuoto nell'output. Gli attributi null sono omessi.
 */
export function elemento(nome: string, attributi: AttributiXml, contenuto: string | null | readonly FrammentoXml[]): FrammentoXml {
  verificaNome(nome);
  let testoAttributi = '';
  for (const [chiave, valore] of attributi) {
    if (valore === null) continue;
    verificaNome(chiave);
    testoAttributi += ` ${chiave}="${testoXml(String(valore))}"`;
  }
  if (typeof contenuto === 'string') {
    const testo = testoXml(contenuto);
    if (testo.trim() !== '') return `<${nome}${testoAttributi}>${testo}</${nome}>` as FrammentoXml;
  } else if (contenuto !== null) {
    const figli = contenuto.filter((figlio) => figlio !== '');
    if (figli.length > 0) return `<${nome}${testoAttributi}>\n${figli.join('\n')}\n</${nome}>` as FrammentoXml;
  }
  return testoAttributi === '' ? FRAMMENTO_VUOTO : (`<${nome}${testoAttributi}/>` as FrammentoXml);
}

// ---------------------------------------------------------------------------
// RSS 2.0
// ---------------------------------------------------------------------------

const NS_ATOM = 'http://www.w3.org/2005/Atom';
const NS_DC = 'http://purl.org/dc/elements/1.1/';
const NS_MEDIA = 'http://search.yahoo.com/mrss/';
const COPYRIGHT = `© EduNews24 – riuso secondo i termini ${URL_TERMINI} con link all'originale`;

function dataRss(rfc3339: string): string | null {
  const ms = istanteTimestamptz(rfc3339);
  return ms === null ? null : rfc822(ms);
}

function voceRss(v: VoceFeed): FrammentoXml {
  return elemento('item', [], [
    elemento('title', [], v.titolo),
    elemento('link', [], v.url),
    elemento('guid', [['isPermaLink', 'false']], v.id),
    elemento('pubDate', [], dataRss(v.pubblicazione)),
    elemento('dc:creator', [], v.autore),
    ...v.etichette.map((etichetta) => elemento('category', [], etichetta)),
    elemento('description', [], v.testo),
    v.immagine === null ? FRAMMENTO_VUOTO : elemento('media:thumbnail', [['url', v.immagine]], null),
    v.video === null
      ? FRAMMENTO_VUOTO
      : elemento('media:content', [
        ['url', v.video.url],
        ['medium', 'video'],
        ['type', v.video.mimeType],
        ['duration', v.video.durata],
      ], null),
  ]);
}

/** Istante piu' recente fra le voci (ms), null se non ci sono voci con una data leggibile. */
function ultimoAggiornamento(voci: readonly VoceFeed[]): number | null {
  let massimo: number | null = null;
  for (const v of voci) {
    const ms = istanteTimestamptz(v.riferimentoAggiornamento);
    if (ms !== null && (massimo === null || ms > massimo)) massimo = ms;
  }
  return massimo;
}

/** RSS 2.0 (application/rss+xml) con i namespace atom, dc e media. */
export function serializzaRss(meta: MetadatiFeed, elementi: readonly ElementoFeed[]): string {
  const voci = elementi.map(voceDi);
  const ultimo = ultimoAggiornamento(voci);
  const canale = elemento('channel', [], [
    elemento('title', [], meta.titolo),
    elemento('link', [], meta.homePageUrl),
    elemento('description', [], meta.descrizione),
    elemento('language', [], 'it-it'),
    elemento('copyright', [], COPYRIGHT),
    elemento('lastBuildDate', [], ultimo === null ? null : rfc822(ultimo)),
    elemento('ttl', [], '10'),
    elemento('atom:link', [['rel', 'self'], ['type', 'application/rss+xml'], ['href', meta.feedUrl]], null),
    ...voci.map(voceRss),
  ]);
  const rss = elemento('rss', [
    ['version', '2.0'],
    ['xmlns:atom', NS_ATOM],
    ['xmlns:dc', NS_DC],
    ['xmlns:media', NS_MEDIA],
  ], [canale]);
  return `<?xml version="1.0" encoding="UTF-8"?>\n${rss}\n`;
}
