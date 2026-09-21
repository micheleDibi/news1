/**
 * Testo semplice dell'API /api/v1 (piano §3.1 regole 6-7 e §3.4).
 *
 * Ogni campo di testo esposto passa da `pulisciTesto` o da `sintesiDaMarkdown`:
 * - niente markup ne' entita' (commenti e tag HTML via, entita' decodificate);
 * - niente caratteri di controllo ne' surrogati spaiati, spazi collassati;
 * - nessun link a fonti esterne: un URL esterno diventa il solo nome host
 *   (`https://www.inpa.gov.it/bandi` -> `inpa.gov.it`), gli URL di edunews24.it
 *   restano, un campo fatto solo di un URL esterno diventa null.
 *
 * Modulo puro: nessun I/O, nessun accesso all'ambiente, nessuna dipendenza dal fuso.
 * Le regex sono scritte per restare lineari anche su input patologici (il DB e'
 * scrivibile con la chiave anon, vedi piano §14.4): i commenti HTML si cercano
 * con indexOf, le enfasi markdown hanno un contenuto di lunghezza limitata.
 */
import { hostValido } from './url';

// ---------------------------------------------------------------------------
// 1. Commenti HTML
// ---------------------------------------------------------------------------

/** Via i commenti HTML completi (`<!-- ... -->`); un `<!--` senza chiusura resta testo. */
function rimuoviCommenti(testo: string): string {
  let inizio = testo.indexOf('<!--');
  if (inizio === -1) return testo;
  let esito = '';
  let posizione = 0;
  while (inizio !== -1) {
    const fine = testo.indexOf('-->', inizio + 4);
    if (fine === -1) break;
    esito += testo.slice(posizione, inizio);
    posizione = fine + 3;
    inizio = testo.indexOf('<!--', posizione);
  }
  return esito + testo.slice(posizione);
}

// ---------------------------------------------------------------------------
// 2. Entita'
// ---------------------------------------------------------------------------

/**
 * Tabella chiusa delle entita' nominate. I nomi sono sensibili alle maiuscole
 * (`&Agrave;` != `&agrave;`); un'entita' fuori tabella resta com'e'.
 */
const ENTITA_NOMINATE: ReadonlyMap<string, string> = new Map([
  ['nbsp', '\u00A0'], ['amp', '&'], ['lt', '<'], ['gt', '>'], ['quot', '"'], ['apos', "'"],
  ['laquo', '«'], ['raquo', '»'], ['rsquo', '’'], ['lsquo', '‘'], ['ldquo', '“'], ['rdquo', '”'],
  ['sbquo', '‚'], ['bdquo', '„'], ['ndash', '–'], ['mdash', '—'], ['hellip', '…'],
  ['euro', '€'], ['deg', '°'], ['bull', '•'], ['middot', '·'], ['times', '×'],
  ['copy', '©'], ['reg', '®'], ['trade', '™'], ['ordm', 'º'], ['ordf', 'ª'], ['sect', '§'],
  ['shy', '\u00AD'], ['ensp', '\u2002'], ['emsp', '\u2003'], ['thinsp', '\u2009'],
  ['agrave', 'à'], ['egrave', 'è'], ['eacute', 'é'], ['igrave', 'ì'], ['ograve', 'ò'], ['ugrave', 'ù'],
  ['Agrave', 'À'], ['Egrave', 'È'], ['Eacute', 'É'], ['Igrave', 'Ì'], ['Ograve', 'Ò'], ['Ugrave', 'Ù'],
  ['aacute', 'á'], ['iacute', 'í'], ['oacute', 'ó'], ['uacute', 'ú'],
  ['Aacute', 'Á'], ['Iacute', 'Í'], ['Oacute', 'Ó'], ['Uacute', 'Ú'],
  ['auml', 'ä'], ['euml', 'ë'], ['iuml', 'ï'], ['ouml', 'ö'], ['uuml', 'ü'],
  ['ccedil', 'ç'], ['Ccedil', 'Ç'], ['ntilde', 'ñ'], ['Ntilde', 'Ñ'],
]);

/**
 * Riferimenti numerici 0x80-0x9F: come fanno i browser (HTML, "numeric character
 * reference end state"), si leggono in windows-1252. Senza questa tabella
 * `l&#146;anno` perderebbe l'apostrofo, perche' U+0092 e' un carattere di controllo.
 */
const WINDOWS_1252: ReadonlyMap<number, number> = new Map([
  [0x80, 0x20AC], [0x82, 0x201A], [0x83, 0x0192], [0x84, 0x201E], [0x85, 0x2026],
  [0x86, 0x2020], [0x87, 0x2021], [0x88, 0x02C6], [0x89, 0x2030], [0x8A, 0x0160],
  [0x8B, 0x2039], [0x8C, 0x0152], [0x8E, 0x017D], [0x91, 0x2018], [0x92, 0x2019],
  [0x93, 0x201C], [0x94, 0x201D], [0x95, 0x2022], [0x96, 0x2013], [0x97, 0x2014],
  [0x98, 0x02DC], [0x99, 0x2122], [0x9A, 0x0161], [0x9B, 0x203A], [0x9C, 0x0153],
  [0x9E, 0x017E], [0x9F, 0x0178],
]);

const ENTITA = /&(?:#([0-9]+)|#[xX]([0-9A-Fa-f]+)|([A-Za-z][A-Za-z0-9]*));/g;

function decodificaNumerica(cifre: string, base: 10 | 16): string | null {
  // Oltre 8 cifre significative il valore e' comunque fuori da Unicode.
  const significative = cifre.replace(/^0+/, '');
  if (significative.length > 8) return null;
  const codice = significative === '' ? 0 : Number.parseInt(significative, base);
  if (codice === 0 || codice > 0x10FFFF || (codice >= 0xD800 && codice <= 0xDFFF)) return null;
  return String.fromCodePoint(WINDOWS_1252.get(codice) ?? codice);
}

/**
 * Un solo passaggio: `&amp;lt;` diventa `&lt;` letterale e li' resta.
 * Numeriche non valide (0, surrogati, oltre U+10FFFF) e nominate sconosciute
 * restano invariate.
 */
function decodificaEntita(testo: string): string {
  if (!testo.includes('&')) return testo;
  return testo.replace(ENTITA, (intera: string, decimale?: string, esadecimale?: string, nome?: string) => {
    if (decimale !== undefined) return decodificaNumerica(decimale, 10) ?? intera;
    if (esadecimale !== undefined) return decodificaNumerica(esadecimale, 16) ?? intera;
    if (nome !== undefined) return ENTITA_NOMINATE.get(nome) ?? intera;
    return intera;
  });
}

// ---------------------------------------------------------------------------
// 3. Tag
// ---------------------------------------------------------------------------

/**
 * Solo i tag reali: `<` seguito da una lettera (o da `/` e una lettera).
 * "voto < 6" e "<< Addetti >>" non corrispondono. `[^<>]*` si ferma al `<`
 * successivo, quindi la ricerca resta lineare.
 */
const TAG = /<\/?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?\/?>/g;

function rimuoviTag(testo: string): string {
  return testo.includes('<') ? testo.replace(TAG, ' ') : testo;
}

// ---------------------------------------------------------------------------
// 4. Caratteri
// ---------------------------------------------------------------------------

/** Surrogato alto non seguito da un basso, o basso non preceduto da un alto. */
const SURROGATO_SPAIATO = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

/** Separatori di riga (CRLF, CR, NEL, U+2028, U+2029). */
const FINE_RIGA = /\r\n?|[\u0085\u2028\u2029]/g;

/**
 * Controlli C0 e C1 (tranne \t \n \v \f \r, gestiti come spazi), DEL, e gli
 * invisibili senza significato nel testo semplice: soft hyphen, zero width
 * space, BOM. ZWJ e ZWNJ restano (servono alle emoji composte).
 */
const CONTROLLI = /[\u0000-\u0008\u000E-\u001F\u007F-\u009F\u00AD\u200B\uFEFF]/g;

/** Tutti gli spazi tranne l'a capo (compresi nbsp e gli spazi tipografici). */
const SPAZI_SENZA_A_CAPO = /[^\S\n]+/g;

/**
 * Surrogati spaiati via, poi controlli via, poi spazi collassati.
 * Con `preservaACapo` le righe restano separate (e ripulite ai bordi): serve a
 * `sintesiDaMarkdown` per riconoscere titoli ed elenchi.
 */
function pulisciCaratteri(testo: string, preservaACapo: boolean): string {
  const base = testo
    .replace(SURROGATO_SPAIATO, '')
    .replace(FINE_RIGA, '\n')
    .replace(CONTROLLI, '');
  if (!preservaACapo) return base.replace(/\s+/g, ' ').trim();
  return base
    .replace(SPAZI_SENZA_A_CAPO, ' ')
    .split('\n')
    .map((riga) => riga.trim())
    .join('\n')
    .trim();
}

function preparaTesto(v: string, preservaACapo: boolean): string {
  return pulisciCaratteri(rimuoviTag(decodificaEntita(rimuoviCommenti(v))), preservaACapo);
}

/**
 * Testo semplice: commenti HTML via, entita' decodificate in un solo passaggio,
 * tag reali sostituiti da uno spazio (dopo la decodifica: `&lt;b&gt;` e' un tag),
 * controlli e surrogati spaiati via, spazi collassati, trim.
 */
export function normalizzaTestoSemplice(v: string): string {
  return preparaTesto(v, false);
}

// ---------------------------------------------------------------------------
// URL esterni
// ---------------------------------------------------------------------------

/**
 * Destinazione di un link markdown: `(url)`, `(<url con spazi>)`, con un
 * eventuale titolo; ammette un livello di parentesi nell'URL (Wikipedia).
 */
const DESTINAZIONE_MD =
  String.raw`\(\s*(?:<[^<>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?\s*\)`;
const IMMAGINE_MD = new RegExp(String.raw`!\[[^\[\]\n]*\]` + DESTINAZIONE_MD, 'g');
const LINK_MD = new RegExp(String.raw`\[([^\[\]\n]*)\]` + DESTINAZIONE_MD, 'g');

/** `![alt](url)` -> niente; `[testo](url)` -> testo. */
function sostituisciLinkMarkdown(testo: string): string {
  if (!testo.includes('](')) return testo;
  return testo.replace(IMMAGINE_MD, '').replace(LINK_MD, '$1');
}

/** `<https://...>` e `<www....>` perdono le parentesi angolari. */
const AUTOLINK = /<((?:https?:\/\/|www\.)[^\s<>]*)>/gi;

/**
 * URL nudo. Lo schema http(s) viene riconosciuto ovunque (anche attaccato a una
 * parola: meglio `vedixyz.it` che un link esterno che sfugge); `www.` solo se
 * non fa parte di un'email, di un percorso o di un nome piu' lungo.
 */
const URL_NUDO = /(?:https?:\/\/|(?<![\w@\/.-])www\.)[^\s<>"«»]+/gi;

/** Lo stesso URL, ma come intero valore. */
const SOLO_URL = /^(?:https?:\/\/|www\.)[^\s<>"«»]+$/i;

/** Punteggiatura finale che appartiene alla frase, non all'URL. */
// Il lookbehind fa partire il tentativo solo all'inizio di una serie di punteggiatura:
// senza, su 'https://a.it/' + '.'.repeat(n) + 'x' la ricerca sarebbe quadratica.
const PUNTEGGIATURA_FINALE = /(?<![.,;:!?)\]»”'"])[.,;:!?)\]»”'"]+$/;

interface UrlNelTesto {
  /** L'URL senza la punteggiatura finale. */
  url: string;
  /** La punteggiatura finale esclusa dall'URL. */
  coda: string;
  /** Nome host minuscolo, null se l'URL non e' analizzabile. */
  host: string | null;
}

function leggiUrl(corrispondenza: string): UrlNelTesto {
  const punteggiatura = PUNTEGGIATURA_FINALE.exec(corrispondenza);
  const url = punteggiatura ? corrispondenza.slice(0, punteggiatura.index) : corrispondenza;
  const coda = punteggiatura ? punteggiatura[0] : '';
  let host: string | null;
  try {
    const conSchema = /^www\./i.test(url) ? `https://${url}` : url;
    const nome = new URL(conSchema).hostname.toLowerCase();
    host = hostValido(nome) ? nome : null;
  } catch {
    host = null;
  }
  return { url, coda, host };
}

function hostInterno(host: string): boolean {
  return host === 'edunews24.it' || host.endsWith('.edunews24.it');
}

/** Host per il testo: minuscolo (gia' abbassato da WHATWG) e senza `www.` iniziale. */
function hostPerTesto(host: string): string {
  return host.startsWith('www.') ? host.slice(4) : host;
}

/**
 * Toglie i link a fonti esterne dal testo (piano, domanda 4):
 * 1. `![alt](url)` via, `[testo](url)` -> testo;
 * 2. `<https://...>` -> `https://...`;
 * 3. URL nudo esterno -> nome host (`www.inpa.gov.it` -> `inpa.gov.it`);
 *    URL di edunews24.it invariato; URL non analizzabile -> rimosso;
 * 4. valore composto da un solo URL esterno -> null;
 * 5. spazi collassati e trim.
 * Email (`x@pec.regione.it`) e domini senza schema ne' `www.` (`7zip.com`)
 * restano: sono menzioni, non link.
 */
export function rimuoviUrlEsterni(v: string): string | null {
  const senzaLink = sostituisciLinkMarkdown(v).replace(AUTOLINK, '$1');

  const intero = senzaLink.trim();
  if (SOLO_URL.test(intero)) {
    const { host } = leggiUrl(intero);
    if (host === null || !hostInterno(host)) return null;
  }

  const sostituito = senzaLink.replace(URL_NUDO, (corrispondenza: string) => {
    const { coda, host } = leggiUrl(corrispondenza);
    if (host === null) return coda;
    if (hostInterno(host)) return corrispondenza;
    return hostPerTesto(host) + coda;
  });
  return sostituito.replace(/\s+/g, ' ').trim();
}

/**
 * Testo di un campo esposto: normalizzazione, URL esterni, trim.
 * Non stringa, vuoto o fatto solo di un URL esterno -> null.
 */
export function pulisciTesto(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const esito = rimuoviUrlEsterni(normalizzaTestoSemplice(v));
  if (esito === null) return null;
  const testo = esito.trim();
  return testo === '' ? null : testo;
}

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------

/** Righe che non portano testo: recinti di codice, righe orizzontali, sottolineature, separatori di tabella, definizioni di link. */
const RIGA_RECINTO = /^(?:`{3,}|~{3,})/;
const RIGA_ORIZZONTALE = /^(?:[-*_]\s*){3,}$/;
const RIGA_SOTTOLINEATURA = /^(?:=+|-+)$/;
const RIGA_SEPARATORE_TABELLA = /^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?$/;
const RIGA_DEFINIZIONE_LINK = /^\[[^\]\n]+\]:\s*(?:<[^<>\n]*>|\S+)(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?$/;

const MARCATORE_CITAZIONE = /^(?:>\s*)+/;
const MARCATORE_TITOLO = /^#{1,6}(?:\s+|$)/;
const CHIUSURA_TITOLO = /\s+#+$/;
const MARCATORE_ELENCO = /^(?:[-*+]|\d{1,9}[.)])\s+/;
const CASELLA_ATTIVITA = /^\[[ xX]\]\s+/;

/** Codice inline: il contenuto resta, i backtick no. */
// La serie di apertura parte dal primo backtick e la prende intera (come CommonMark):
// senza i due controlli, una lunga serie di backtick rende la ricerca quadratica.
const CODICE_INLINE = /(?<!`)(`+)(?!`)([^`\n]{1,300})\1(?!`)/g;

/**
 * Enfasi. Il contenuto e' limitato a 300 caratteri su una riga: basta per
 * qualunque enfasi reale e tiene lineare la ricerca. `_` e `*` singoli solo ai
 * bordi di parola (`esame_di_stato`, `2*3*4` restano).
 */
const ENFASI: readonly RegExp[] = [
  /\*\*(?=\S)([^\n]{1,300}?)(?<=\S)\*\*/g,
  /(?<![\p{L}\p{N}_])__(?=\S)([^\n]{1,300}?)(?<=\S)__(?![\p{L}\p{N}_])/gu,
  /(?<![\p{L}\p{N}*\\])\*(?=[^\s*])([^\n]{1,300}?)(?<=[^\s*])\*(?![\p{L}\p{N}*])/gu,
  /(?<![\p{L}\p{N}_\\])_(?=[^\s_])([^\n]{1,300}?)(?<=[^\s_])_(?![\p{L}\p{N}_])/gu,
  /~~(?=\S)([^\n]{1,300}?)(?<=\S)~~/g,
];

/**
 * Intestazioni di servizio lasciate dal generatore delle sintesi ("### Paragrafo 1",
 * "Primo paragrafo (200 parole)", "**Paragrafo 1:** testo"): sparisce il prefisso,
 * resta l'eventuale testo che segue.
 */
const IMPALCATURA =
  /^(?:paragrafo\s*\d{1,2}|(?:primo|secondo|terzo|quarto|ultimo)\s+paragrafo|riassunto(?:\s+in\s+\p{L}+\s+paragrafi)?)(?:\s*\([^()\n]{0,40}\))?\s*(?:[:.–—-]\s*|$)/iu;
/** Un titolo gia' chiuso da punteggiatura non riceve il punto finale. */
const TITOLO_CHIUSO = /[.!?…:;]["»”’)]{0,3}$/u;

function pulisciRigaMarkdown(grezza: string): string | null {
  let riga = grezza;
  if (
    RIGA_RECINTO.test(riga) || RIGA_ORIZZONTALE.test(riga) || RIGA_SOTTOLINEATURA.test(riga)
    || RIGA_SEPARATORE_TABELLA.test(riga) || RIGA_DEFINIZIONE_LINK.test(riga)
  ) {
    return null;
  }
  riga = riga.replace(MARCATORE_CITAZIONE, '');
  const titolo = MARCATORE_TITOLO.test(riga);
  if (titolo) riga = riga.replace(MARCATORE_TITOLO, '').replace(CHIUSURA_TITOLO, '');
  riga = riga.replace(MARCATORE_ELENCO, '').replace(CASELLA_ATTIVITA, '');
  riga = sostituisciLinkMarkdown(riga).replace(CODICE_INLINE, '$2');
  for (const enfasi of ENFASI) riga = riga.replace(enfasi, '$1');
  riga = riga.trim().replace(IMPALCATURA, '').trim();
  if (riga === '') return null;
  // Un titolo unito alla frase seguente la chiude con un punto ("Titolo. Testo...").
  return titolo && !TITOLO_CHIUSO.test(riga) ? `${riga}.` : riga;
}

/** Toglie il markup markdown riga per riga e unisce tutto con uno spazio. */
function rimuoviMarkdown(testo: string): string {
  const righe: string[] = [];
  for (const grezza of testo.split('\n')) {
    const riga = pulisciRigaMarkdown(grezza);
    if (riga !== null) righe.push(riga);
  }
  return righe.join(' ').replace(/\s+/g, ' ').trim();
}

// ---------------------------------------------------------------------------
// Taglio a fine frase
// ---------------------------------------------------------------------------

/**
 * Fine frase: `.`, `!`, `?` o `…`, eventuali chiusure (virgolette, parentesi),
 * poi spazio seguito da maiuscola o virgolette d'apertura, oppure fine testo.
 * I decimali (`3.5`, `1.500`) non corrispondono: dopo il punto non c'e' spazio.
 */
const FINE_FRASE = /[.!?…]["»”’)]{0,3}(?=\s+(?:\p{Lu}|[«"“])|$)/gu;

/** Abbreviazioni (minuscole, senza il punto finale) che non chiudono una frase. */
const ABBREVIAZIONI: ReadonlySet<string> = new Set([
  'art', 'artt', 'n', 'nn', 'nr', 'num', 'es', 'ecc', 'pag', 'pagg', 'p', 'pp', 'cap', 'capp',
  'lett', 'all', 'tab', 'fig', 'vol', 'par', 'cfr', 'ca', 'cit', 'ss', 'sgg', 'segg', 'op',
  'prof', 'prof.ssa', 'proff', 'dott', 'dott.ssa', 'dr', 'dott.ri', 'sig', 'sigg', 'sig.ra',
  'sig.na', 'on', 'avv', 'ing', 'arch', 'geom', 'rag', 'sen', 'mons', 'gen', 'egr', 'gent',
  'spett', 'tel', 'co', 'd.lgs', 'd.l', 'l', 'reg', 'cod', 'min', 'univ', 'ist',
]);

/**
 * La parola che precede il punto e' un'abbreviazione? Voci della tabella,
 * lettere singole (`L.`, `n.`, iniziali) e sigle puntate brevi (`D.Lgs`,
 * `D.P.R`, `S.p.A`).
 */
function abbreviazione(testo: string, punto: number): boolean {
  const spazio = testo.lastIndexOf(' ', punto - 1);
  const grezza = testo.slice(spazio + 1, punto);
  // Dopo un'elisione conta solo la parte finale: "dell'art." -> "art".
  const elisione = Math.max(grezza.lastIndexOf("'"), grezza.lastIndexOf('’'));
  const parola = grezza.slice(elisione + 1).replace(/^[(«"“‘[]+/, '').toLowerCase();
  if (parola === '') return false;
  if (ABBREVIAZIONI.has(parola)) return true;
  if (/^\p{L}$/u.test(parola)) return true;
  return /^\p{L}(?:\.\p{L}{1,4})+$/u.test(parola);
}

/** Taglio in codice UTF-16 che non lascia a meta' una coppia di surrogati. */
function tagliaSicuro(testo: string, lunghezza: number): string {
  const codice = testo.charCodeAt(lunghezza - 1);
  const fine = codice >= 0xD800 && codice <= 0xDBFF ? lunghezza - 1 : lunghezza;
  return testo.slice(0, fine);
}

/**
 * Accorcia a `massimo` unita' UTF-16 (quindi anche a non piu' di `massimo`
 * code point): all'ultimo fine frase in [massimo/2, massimo]; altrimenti
 * all'ultimo spazio entro massimo-1, piu' `…`.
 */
function accorcia(testo: string, massimo: number): string | null {
  if (testo.length <= massimo) return testo;

  let taglio = -1;
  FINE_FRASE.lastIndex = 0;
  for (let m = FINE_FRASE.exec(testo); m !== null; m = FINE_FRASE.exec(testo)) {
    const fine = m.index + m[0].length;
    if (fine > massimo) break;
    if (fine < massimo / 2) continue;
    if (m[0][0] === '.' && abbreviazione(testo, m.index)) continue;
    taglio = fine;
  }
  if (taglio !== -1) return testo.slice(0, taglio);

  const spazio = testo.lastIndexOf(' ', massimo - 1);
  const prefisso = spazio > 0 ? testo.slice(0, spazio) : tagliaSicuro(testo, massimo - 1);
  const pulito = prefisso.replace(/[\s,;:]+$/, '');
  return pulito === '' ? null : `${pulito}…`;
}

/**
 * Sintesi in testo semplice di un campo markdown (articles.summary):
 * normalizzazione con gli a capo preservati, markdown via, paragrafi uniti,
 * URL esterni sostituiti, poi taglio a `massimo` caratteri calcolato sul testo
 * gia' ripulito. Non stringa o risultato vuoto -> null.
 */
export function sintesiDaMarkdown(v: unknown, massimo: number): string | null {
  if (!Number.isInteger(massimo) || massimo < 2) {
    throw new RangeError('sintesiDaMarkdown: massimo deve essere un intero >= 2');
  }
  const testo = pulisciTestoMarkdown(v);
  return testo === null ? null : accorcia(testo, massimo);
}

/**
 * Come pulisciTesto, ma per i campi scritti in markdown (titoli ed excerpt degli
 * articoli): toglie anche il markup markdown, senza tagliare. Non va usata sui testi
 * ufficiali delle opportunita', dove `_` e `*` possono far parte del testo.
 */
export function pulisciTestoMarkdown(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const senzaUrl = rimuoviUrlEsterni(rimuoviMarkdown(preparaTesto(v, true)));
  if (senzaUrl === null) return null;
  const testo = senzaUrl.trim();
  return testo === '' ? null : testo;
}

// ---------------------------------------------------------------------------
// Elenchi
// ---------------------------------------------------------------------------

/**
 * Elenco di stringhe (es. tags): se non e' un array -> []; ogni elemento passa
 * da `pulisciTesto`, i null spariscono, i duplicati pure (vince il primo,
 * l'ordine resta). Con `senzaMaiuscole` il confronto ignora le maiuscole
 * (toLowerCase, indipendente dal locale del processo).
 */
export function pulisciElenco(v: unknown, opzioni?: { senzaMaiuscole?: boolean }): string[] {
  if (!Array.isArray(v)) return [];
  const senzaMaiuscole = opzioni?.senzaMaiuscole === true;
  const elenco: readonly unknown[] = v;
  const visti = new Set<string>();
  const esito: string[] = [];
  for (const elemento of elenco) {
    const testo = pulisciTesto(elemento);
    if (testo === null) continue;
    const chiave = senzaMaiuscole ? testo.toLowerCase() : testo;
    if (visti.has(chiave)) continue;
    visti.add(chiave);
    esito.push(testo);
  }
  return esito;
}
