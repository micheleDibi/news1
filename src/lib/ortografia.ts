/**
 * Normalizzazione ortografica dei testi italiani generati dai modelli.
 *
 * Gemello di `backend/app/ortografia.py`: le due implementazioni devono
 * produrre lo stesso risultato carattere per carattere. Ogni modifica va
 * fatta su ENTRAMBI i file e verificata con la tabella di casi condivisa in
 * `tests/ortografia/casi.json`.
 *
 * Vincoli di parita' rispettati qui:
 * - mai `\b \w \d \s` nei pattern: le classi sono congelate a intervalli
 *   espliciti costruiti con String.fromCharCode. L'unica eccezione ammessa
 *   e' `[\s\S]`, che in entrambi i motori significa "qualunque carattere";
 * - mai lookbehind: si consuma il carattere di confine e lo si riemette;
 * - mai il flag `i`: le varianti di caso sono precalcolate;
 * - mai una stringa di rimpiazzo (`$&` corrompe il risultato): sempre una
 *   funzione, e per lo smascheramento split/join.
 *
 * Modulo server-only e senza dipendenze: nessun import, cosi' i test lo
 * caricano da soli.
 */

const TAB = String.fromCharCode(9);
const NL = String.fromCharCode(10);

const S_INIZIO = String.fromCharCode(0xe000);
const S_FINE = String.fromCharCode(0xe001);
const PUA = String.fromCharCode(0xe000) + '-' + String.fromCharCode(0xe00f);

const C =
  'A-Za-z0-9_' +
  String.fromCharCode(0x00c0) + '-' + String.fromCharCode(0x024f) +
  String.fromCharCode(0x0300) + '-' + String.fromCharCode(0x036f) +
  String.fromCharCode(0x1e00) + '-' + String.fromCharCode(0x1eff);

const APOS =
  "'" +
  String.fromCharCode(0x2018) + String.fromCharCode(0x2019) +
  String.fromCharCode(0x02bc) + String.fromCharCode(0x02b9) +
  String.fromCharCode(0x2032) + String.fromCharCode(0x0060) +
  String.fromCharCode(0x00b4);

const SX = '(^|[^' + C + '])';

const LIMITE_RIGHE_FENCE = 200;
const MAX_SEGN_PER_PAROLA = 3;
const MAX_SEGN_PER_TESTO = 12;

const MAIUSCOLE = new Map<string, string>();
for (let i = 0; i < 26; i++) {
  MAIUSCOLE.set(String.fromCharCode(97 + i), String.fromCharCode(65 + i));
}
for (const [basso, alto] of [
  [0x00e0, 0x00c0], [0x00e1, 0x00c1], [0x00e8, 0x00c8], [0x00e9, 0x00c9],
  [0x00ec, 0x00cc], [0x00ed, 0x00cd], [0x00f2, 0x00d2], [0x00f3, 0x00d3],
  [0x00f9, 0x00d9], [0x00fa, 0x00da],
]) {
  MAIUSCOLE.set(String.fromCharCode(basso), String.fromCharCode(alto));
}

function su(carattere: string): string {
  return MAIUSCOLE.get(carattere) ?? carattere;
}

function inizialeMaiuscola(testo: string): string {
  if (testo === '') return testo;
  return su(testo[0]) + testo.slice(1);
}

function tuttoMaiuscolo(testo: string): string {
  let fuori = '';
  for (const c of testo) fuori += su(c);
  return fuori;
}

// `-` e `/` sono letterali fuori da una classe in entrambi i motori, e `\-`
// fuori da una classe e' un errore in JS con il flag u: non si escapano.
const DA_ESCAPARE = new Set('.*+?^$}{()|[]\\'.split(''));

function esc(testo: string): string {
  let fuori = '';
  for (const c of testo) fuori += DA_ESCAPARE.has(c) ? '\\' + c : c;
  return fuori;
}

/** `pdf` -> `[Pp][Dd][Ff]`: alternativa al flag i, identica in Python. */
function classeInsensibile(parola: string): string {
  let fuori = '';
  for (const c of parola) {
    const alto = su(c);
    fuori += alto !== c ? '[' + c + alto + ']' : c;
  }
  return fuori;
}

function altInsensibile(parole: string[]): string {
  return parole.map(classeInsensibile).join('|');
}

// ----------------------------------------------------------- tabelle
//
// Generate da backend/app/ortografia.py: NON modificarle qui a mano.
// Il test di parita' in tests/ortografia/ fallisce se divergono.

const LISTA_2: [string, string][] = [
  ["perche", "perch\u00e9"],
  ["poiche", "poich\u00e9"],
  ["affinche", "affinch\u00e9"],
  ["benche", "bench\u00e9"],
  ["nonche", "nonch\u00e9"],
  ["sicche", "sicch\u00e9"],
  ["finche", "finch\u00e9"],
  ["purche", "purch\u00e9"],
  ["anziche", "anzich\u00e9"],
  ["dopodiche", "dopodich\u00e9"],
  ["cosicche", "cosicch\u00e9"],
  ["fuorche", "fuorch\u00e9"],
  ["dacche", "dacch\u00e9"],
  ["cioe", "cio\u00e8"],
  ["percio", "perci\u00f2"],
  ["puo", "pu\u00f2"],
  ["cosi", "cos\u00ec"],
  ["gia", "gi\u00e0"],
  ["piu", "pi\u00f9"],
  ["citta", "citt\u00e0"],
  ["universita", "universit\u00e0"],
  ["societa", "societ\u00e0"],
  ["liberta", "libert\u00e0"],
  ["qualita", "qualit\u00e0"],
  ["accessibilita", "accessibilit\u00e0"],
  ["attivita", "attivit\u00e0"],
  ["novita", "novit\u00e0"],
  ["possibilita", "possibilit\u00e0"],
  ["identita", "identit\u00e0"],
  ["comunita", "comunit\u00e0"],
  ["autorita", "autorit\u00e0"],
  ["realta", "realt\u00e0"],
  ["modalita", "modalit\u00e0"],
  ["priorita", "priorit\u00e0"],
  ["validita", "validit\u00e0"],
  ["verita", "verit\u00e0"],
  ["responsabilita", "responsabilit\u00e0"],
  ["difficolta", "difficolt\u00e0"],
  ["facolta", "facolt\u00e0"],
  ["specialita", "specialit\u00e0"],
  ["particolarita", "particolarit\u00e0"],
  ["opportunita", "opportunit\u00e0"],
  ["maturita", "maturit\u00e0"],
  ["idoneita", "idoneit\u00e0"],
  ["anzianita", "anzianit\u00e0"],
  ["continuita", "continuit\u00e0"],
  ["titolarita", "titolarit\u00e0"],
  ["disponibilita", "disponibilit\u00e0"],
  ["parita", "parit\u00e0"],
  ["professionalita", "professionalit\u00e0"],
  ["invalidita", "invalidit\u00e0"],
  ["annualita", "annualit\u00e0"],
  ["mensilita", "mensilit\u00e0"],
  ["obbligatorieta", "obbligatoriet\u00e0"],
  ["legalita", "legalit\u00e0"],
  ["scolarita", "scolarit\u00e0"],
  ["sanita", "sanit\u00e0"],
  ["pubblicita", "pubblicit\u00e0"],
  ["potra", "potr\u00e0"],
  ["dovra", "dovr\u00e0"],
  ["sapra", "sapr\u00e0"],
  ["vorra", "vorr\u00e0"],
  ["stara", "star\u00e0"],
  ["bastera", "baster\u00e0"],
  ["restera", "rester\u00e0"],
  ["tornera", "torner\u00e0"],
  ["arrivera", "arriver\u00e0"],
  ["iniziera", "inizier\u00e0"],
  ["partira", "partir\u00e0"],
  ["scadra", "scadr\u00e0"],
  ["chiudera", "chiuder\u00e0"],
  ["aprira", "aprir\u00e0"],
  ["entrera", "entrer\u00e0"],
  ["avra", "avr\u00e0"],
  ["seguira", "seguir\u00e0"],
  ["finira", "finir\u00e0"],
  ["servira", "servir\u00e0"],
  ["costera", "coster\u00e0"],
  ["durera", "durer\u00e0"],
  ["permettera", "permetter\u00e0"],
  ["consentira", "consentir\u00e0"],
  ["prevedera", "preveder\u00e0"],
  ["stabilira", "stabilir\u00e0"],
  ["decidera", "decider\u00e0"],
  ["ricevera", "ricever\u00e0"],
  ["otterra", "otterr\u00e0"],
  ["rimarra", "rimarr\u00e0"],
  ["avverra", "avverr\u00e0"],
  ["riguardera", "riguarder\u00e0"],
  ["cambiera", "cambier\u00e0"],
  ["aumentera", "aumenter\u00e0"],
  ["partecipera", "parteciper\u00e0"],
  ["presentera", "presenter\u00e0"],
  ["pubblichera", "pubblicher\u00e0"],
  ["comunichera", "comunicher\u00e0"],
  ["varera", "varer\u00e0"],
  ["andro", "andr\u00f2"],
  ["potro", "potr\u00f2"],
  ["dovro", "dovr\u00f2"],
  ["sapro", "sapr\u00f2"],
  ["vorro", "vorr\u00f2"],
  ["terro", "terr\u00f2"],
  ["lunedi", "luned\u00ec"],
  ["martedi", "marted\u00ec"],
  ["mercoledi", "mercoled\u00ec"],
  ["giovedi", "gioved\u00ec"],
  ["venerdi", "venerd\u00ec"],
  ["perch\u00e8", "perch\u00e9"],
  ["poich\u00e8", "poich\u00e9"],
  ["affinch\u00e8", "affinch\u00e9"],
  ["bench\u00e8", "bench\u00e9"],
  ["nonch\u00e8", "nonch\u00e9"],
  ["sicch\u00e8", "sicch\u00e9"],
  ["finch\u00e8", "finch\u00e9"],
  ["purch\u00e8", "purch\u00e9"],
  ["anzich\u00e8", "anzich\u00e9"],
  ["dopodich\u00e8", "dopodich\u00e9"],
  ["cosicch\u00e8", "cosicch\u00e9"],
  ["fuorch\u00e8", "fuorch\u00e9"],
  ["giacch\u00e8", "giacch\u00e9"],
  ["dacch\u00e8", "dacch\u00e9"],
  ["n\u00e8", "n\u00e9"],
  ["s\u00e8", "s\u00e9"],
  ["p\u00f2", "po'"],
  ["cio\u00e9", "cio\u00e8"],
  ["caff\u00e9", "caff\u00e8"],
  ["qual'\u00e8", "qual \u00e8"],
  ["qual'era", "qual era"],
  ["qual'erano", "qual erano"],
];

const LISTA_2B: [string, string][] = [
  ["sara", "sar\u00e0"],
  ["dara", "dar\u00e0"],
  ["fara", "far\u00e0"],
  ["andra", "andr\u00e0"],
  ["verra", "verr\u00e0"],
  ["caffe", "caff\u00e8"],
];

const SOLO_APOSTROFO: [string, string][] = [
  ["e'", "\u00e8"],
  ["si'", "s\u00ec"],
  ["la'", "l\u00e0"],
  ["li'", "l\u00ec"],
  ["giu'", "gi\u00f9"],
  ["eta'", "et\u00e0"],
  ["meta'", "met\u00e0"],
  ["pero'", "per\u00f2"],
  ["terra'", "terr\u00e0"],
  ["papa'", "pap\u00e0"],
  ["faro'", "far\u00f2"],
  ["saro'", "sar\u00f2"],
  ["daro'", "dar\u00f2"],
  ["verro'", "verr\u00f2"],
  ["staro'", "star\u00f2"],
  ["unita'", "unit\u00e0"],
  ["necessita'", "necessit\u00e0"],
  ["disabilita'", "disabilit\u00e0"],
  ["abilita'", "abilit\u00e0"],
  ["capacita'", "capacit\u00e0"],
  ["eredita'", "eredit\u00e0"],
  ["gratuita'", "gratuit\u00e0"],
];

const DENY: string[] = [
  "po'",
  "mo'",
  "fa'",
  "da'",
  "di'",
  "va'",
  "sta'",
  "be'",
  "to'",
  "ca'",
  "de'",
  "fra'",
  "pro'",
  "ne'",
  "a'",
  "co'",
  "vo'",
  "so'",
  "i'",
  "tra'",
  "me'",
  "ve'",
  "su'",
  "no'",
];

const LISTA_3A: [string, string][] = [
  ["e", "\u00e8"],
  ["da", "d\u00e0"],
  ["si", "s\u00ec"],
  ["la", "l\u00e0"],
  ["ne", "n\u00e9"],
  ["se", "s\u00e9"],
  ["li", "l\u00ec"],
  ["te", "t\u00e8"],
  ["ancora", "\u00e0ncora"],
  ["meta", "met\u00e0"],
  ["terra", "terr\u00e0"],
  ["unita", "unit\u00e0"],
  ["papa", "pap\u00e0"],
  ["pero", "per\u00f2"],
  ["faro", "far\u00f2"],
];

const LISTA_3B: [string, string][] = [
  ["necessita", "necessit\u00e0"],
  ["disabilita", "disabilit\u00e0"],
  ["abilita", "abilit\u00e0"],
  ["eredita", "eredit\u00e0"],
  ["gratuita", "gratuit\u00e0"],
  ["capacita", "capacit\u00e0"],
  ["eta", "et\u00e0"],
  ["giu", "gi\u00f9"],
  ["saro", "sar\u00f2"],
  ["daro", "dar\u00f2"],
  ["verro", "verr\u00f2"],
  ["staro", "star\u00f2"],
  ["pi\u00fa", "pi\u00f9"],
  ["cos\u00ed", "cos\u00ec"],
  ["gi\u00fa", "gi\u00f9"],
];

const PREPOSIZIONI_SE: string[] = [
  "per",
  "di",
  "in",
  "con",
  "tra",
  "fra",
  "da",
  "su",
  "sopra",
  "verso",
];

const ESTENSIONI: string[] = [
  "pdf",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "zip",
  "rar",
  "jpg",
  "jpeg",
  "png",
  "gif",
  "svg",
  "webp",
  "csv",
  "txt",
  "xml",
  "json",
];

const TLD: string[] = [
  "it",
  "com",
  "org",
  "net",
  "eu",
  "edu",
  "gov",
];

function ammetteMaiuscolo(forma: string): boolean {
  for (const c of forma) {
    if (c.charCodeAt(0) > 127 || c === "'") return true;
  }
  return forma.length >= 5;
}

function coppieVarianti(sorgente: string, destinazione: string): [string, string][] {
  const coppie: [string, string][] = [[sorgente, destinazione]];
  const titolo = inizialeMaiuscola(sorgente);
  if (titolo !== sorgente) coppie.push([titolo, inizialeMaiuscola(destinazione)]);
  if (ammetteMaiuscolo(sorgente)) {
    const alto = tuttoMaiuscolo(sorgente);
    if (coppie.every((c) => c[0] !== alto)) coppie.push([alto, tuttoMaiuscolo(destinazione)]);
  }
  return coppie;
}

function eAsciiMinuscolo(forma: string): boolean {
  if (forma.length === 0) return false;
  for (const c of forma) {
    if (c < 'a' || c > 'z') return false;
  }
  return true;
}

function derivateConApostrofo(): [string, string][] {
  const fuori: [string, string][] = [];
  for (const [sorgente, destinazione] of LISTA_2.concat(LISTA_2B)) {
    if (eAsciiMinuscolo(sorgente)) fuori.push([sorgente + "'", destinazione]);
  }
  return fuori;
}

const MAPPA = new Map<string, string>();
const TIPO = new Map<string, string>();
const SEGNALA_2B = new Map<string, string>();

for (const [s, d] of (SOLO_APOSTROFO as [string, string][]).concat(derivateConApostrofo())) {
  for (const [vs, vd] of coppieVarianti(s, d)) {
    MAPPA.set(vs, vd);
    TIPO.set(vs, 'apostrofo');
  }
}
for (const [s, d] of LISTA_2) {
  for (const [vs, vd] of coppieVarianti(s, d)) {
    MAPPA.set(vs, vd);
    TIPO.set(vs, 'nuda');
  }
}
for (const [s, d] of LISTA_2B) {
  MAPPA.set(s, d);
  TIPO.set(s, 'nuda');
  // Le varianti con la maiuscola non si correggono mai, ma si segnalano
  // sempre: anche TUTTO MAIUSCOLO, che il ramo delle sigle escluderebbe.
  // Una segnalazione non tocca il testo, quindi non ha il rischio che ha
  // motivato quella soglia ("SARA UTILE PER TUTTI" va comunque notato).
  const varianti: [string, string][] = [
    [inizialeMaiuscola(s), inizialeMaiuscola(d)],
    [tuttoMaiuscolo(s), tuttoMaiuscolo(d)],
  ];
  for (const [vs, vd] of varianti) {
    if (vs === s || SEGNALA_2B.has(vs)) continue;
    SEGNALA_2B.set(vs, vd);
    TIPO.set(vs, 'nuda');
  }
}

const BASE_3 = new Map<string, [string, string]>();
const GATE_3 = new Map<string, boolean>();
for (const [s, d] of LISTA_3A.concat(LISTA_3B)) {
  const gated = LISTA_3A.some((voce) => voce[0] === s);
  for (const [vs, vd] of coppieVarianti(s, d)) {
    BASE_3.set(vs, [s, vd]);
    GATE_3.set(vs, gated);
  }
}

/** Deduplica, poi ordina: piu' lunga prima, quindi per codepoint. */
function ordinaChiavi(chiavi: string[]): string[] {
  return Array.from(new Set(chiavi)).sort(
    (a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0),
  );
}

function confineDestro(tipo: string): string {
  return tipo === 'apostrofo' ? '(?![' + C + '])' : '(?![' + C + APOS + '])';
}

const CHIAVI_PRINCIPALI = ordinaChiavi(
  Array.from(MAPPA.keys()).concat(Array.from(SEGNALA_2B.keys())),
);
const RE_PRINCIPALE = new RegExp(
  SX + '(' + CHIAVI_PRINCIPALI.map((k) => esc(k) + confineDestro(TIPO.get(k) as string)).join('|') + ')',
  'gu',
);

const CHIAVI_3 = ordinaChiavi(Array.from(BASE_3.keys()));
const RE_SEGNALAZIONI = new RegExp(
  SX + '(' + CHIAVI_3.map((k) => esc(k) + '(?![' + C + APOS + '])').join('|') + ')',
  'gu',
);

const RE_SE_PREP = new RegExp(
  SX + '((?:' + altInsensibile(PREPOSIZIONI_SE) + ')[ ' + TAB + ']+)([Ss]e\')(?![' + C + '])',
  'gu',
);

// --------------------------------------------------------- mascheramento

const LETTERE = 'A-Za-z' + String.fromCharCode(0x00c0) + '-' + String.fromCharCode(0x024f);
const NON_URL = ' ' + TAB + NL + '<>"\'()\\[\\]' + PUA;
const VIRG = "'" + String.fromCharCode(0x2018) + String.fromCharCode(0x2019);

/** Ogni maschera e' [regex, gruppo da mascherare (0 = tutta), n. gruppi]. */
const MASCHERE: [RegExp, number, number][] = [
  [new RegExp('<!--[\\s\\S]*?-->', 'gu'), 0, 0],
  [new RegExp('<' + classeInsensibile('script') + '[\\s\\S]*?</' + classeInsensibile('script') + '>', 'gu'), 0, 0],
  [new RegExp('<' + classeInsensibile('style') + '[\\s\\S]*?</' + classeInsensibile('style') + '>', 'gu'), 0, 0],
  [new RegExp('`[^`' + NL + PUA + ']+`', 'gu'), 0, 0],
  [new RegExp('<[a-zA-Z/!?](?:"[^"]*"|\'[^\']*\'|[^>"\'' + PUA + '])*>', 'gu'), 0, 0],
  [new RegExp(
    '(!\\[[^\\]' + NL + PUA + ']*\\])' +
    '(\\((?:[^()' + NL + PUA + ']|\\([^()' + NL + PUA + ']*\\))*\\))', 'gu'), 2, 2],
  [new RegExp(
    '(\\])(\\((?:[^()' + NL + PUA + ']|\\([^()' + NL + PUA + ']*\\))*\\))', 'gu'), 2, 2],
  [new RegExp('(\\[LINK:[^\\]|' + NL + ']*\\|)([^\\]' + NL + ']*)(\\])', 'gu'), 2, 3],
  [new RegExp('\\{#[0-9A-Za-z_\\-]+\\}', 'gu'), 0, 0],
  [new RegExp('(?:' + altInsensibile(['http']) + '[sS]?://|' + altInsensibile(['ftp']) + '://|' +
    altInsensibile(['www']) + '\\.)[^' + NON_URL + ']+', 'gu'), 0, 0],
  [new RegExp('[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z][A-Za-z]+', 'gu'), 0, 0],
  [new RegExp('(?:[a-zA-Z0-9\\-]+\\.)+(?:' + altInsensibile(TLD) + ')(?:/[^' + NON_URL + ']*)?', 'gu'), 0, 0],
  [new RegExp('(^|[ ' + TAB + '(\\["])((?:\\.\\.?)?/[A-Za-z0-9_\\-/.#?=&%]*)', 'gu'), 2, 2],
  [new RegExp('(^|[ ' + TAB + '(\\[])([#@][A-Za-z0-9_\\-]+)', 'gu'), 2, 2],
  [new RegExp('[A-Za-z0-9_\\-]+\\.(?:' + altInsensibile(ESTENSIONI) + ')', 'gu'), 0, 0],
  [new RegExp('[a-z]+(?:-[a-z0-9]+)*-[0-9][0-9]+', 'gu'), 0, 0],
  [new RegExp('[' + LETTERE + ']+(?:&#?[0-9A-Za-z]+;)+', 'gu'), 0, 0],
  [new RegExp('&#?[0-9A-Za-z]+;', 'gu'), 0, 0],
  [new RegExp('(^|[ ' + TAB + '(\\[' + String.fromCharCode(0x00ab) + '"])' +
    '([' + VIRG + '][^' + VIRG + NL + PUA + ']{1,24}[' + VIRG + '])(?![' + LETTERE + '0-9])', 'gu'), 2, 2],
];

const RE_PUA = new RegExp('[' + PUA + ']', 'u');
const RE_CONTROLLI = new RegExp(
  '[' + String.fromCharCode(0) + '-' + String.fromCharCode(8) +
  String.fromCharCode(11) + String.fromCharCode(12) +
  String.fromCharCode(14) + '-' + String.fromCharCode(31) +
  String.fromCharCode(127) + '-' + String.fromCharCode(159) +
  String.fromCharCode(0xfeff) + ']', 'gu');
const RE_APOSTROFO = new RegExp(
  '([' + C + '])[' + String.fromCharCode(0x2018) + String.fromCharCode(0x2019) +
  String.fromCharCode(0x02bc) + String.fromCharCode(0x02b9) +
  String.fromCharCode(0x2032) + String.fromCharCode(0x0060) +
  String.fromCharCode(0x00b4) + ']', 'gu');

function token(store: string[], testo: string): string {
  store.push(testo);
  return S_INIZIO + String(store.length - 1) + S_FINE;
}

function senzaSpaziIniziali(riga: string): string {
  let i = 0;
  while (i < riga.length && (riga[i] === ' ' || riga[i] === TAB)) i++;
  return riga.slice(i);
}

/**
 * Blocchi di codice recintati e righe di citazione: si mascherano per riga,
 * non per regex, cosi' i due gemelli non dipendono da re.M / flag m.
 */
function mascheraRighe(testo: string, store: string[]): string {
  const righe = testo.split(NL);
  const fuori: string[] = [];
  let i = 0;
  const n = righe.length;
  while (i < n) {
    const nuda = senzaSpaziIniziali(righe[i]);
    let delim: string | null = null;
    if (nuda.slice(0, 3) === '```') delim = '```';
    else if (nuda.slice(0, 3) === '~~~') delim = '~~~';
    if (delim !== null) {
      let j = i + 1;
      let chiuso = -1;
      while (j < n && j - i <= LIMITE_RIGHE_FENCE) {
        if (senzaSpaziIniziali(righe[j]).slice(0, 3) === delim) { chiuso = j; break; }
        j++;
      }
      if (chiuso >= 0) {
        fuori.push(token(store, righe.slice(i, chiuso + 1).join(NL)));
        i = chiuso + 1;
        continue;
      }
      // recinto spaiato: non si maschera nulla
    }
    if (nuda.slice(0, 1) === '>') {
      fuori.push(token(store, righe[i]));
      i++;
      continue;
    }
    fuori.push(righe[i]);
    i++;
  }
  return fuori.join(NL);
}

function maschera(testo: string, store: string[]): string {
  let lavorato = mascheraRighe(testo, store);
  for (const [regex, gruppo, nGruppi] of MASCHERE) {
    if (gruppo === 0) {
      lavorato = lavorato.replace(regex, (m: string) => token(store, m));
    } else {
      lavorato = lavorato.replace(regex, (...args: unknown[]) => {
        let fuori = '';
        for (let k = 1; k <= nGruppi; k++) {
          const valore = (args[k] as string | undefined) ?? '';
          fuori += k === gruppo ? token(store, valore) : valore;
        }
        return fuori;
      });
    }
  }
  return lavorato;
}

/**
 * Indice decrescente: un contenitore mascherato dopo il suo contenuto ha
 * indice maggiore, quindi va espanso per primo. split/join invece di
 * replace, cosi' un `$&` nel testo memorizzato resta letterale.
 */
function smaschera(testo: string, store: string[]): string {
  let lavorato = testo;
  for (let n = store.length - 1; n >= 0; n--) {
    lavorato = lavorato.split(S_INIZIO + String(n) + S_FINE).join(store[n]);
  }
  return lavorato;
}

// ------------------------------------------------------------- interfaccia

export interface Correzione {
  da: string;
  a: string;
  occorrenza: number;
}

export interface Segnalazione {
  regola: string;
  parola: string;
  occorrenza: number;
  suggerimento: string;
}

export interface RisultatoOrtografia {
  testo: string;
  correzioni: Correzione[];
  segnalazioni: Segnalazione[];
  saltato: string | null;
}

function normalizzaTerminatori(testo: string): string {
  return testo
    .split(String.fromCharCode(13) + NL).join(NL)
    .split(String.fromCharCode(13)).join(NL)
    .split(String.fromCharCode(0x2028)).join(NL)
    .split(String.fromCharCode(0x2029)).join(NL)
    .split(String.fromCharCode(0x0085)).join(NL);
}

function vuoto(testo: string, saltato: string | null): RisultatoOrtografia {
  return { testo, correzioni: [], segnalazioni: [], saltato };
}

function segnala(testo: string, gate: boolean, giaRaccolte: Segnalazione[]): Segnalazione[] {
  const fuori: Segnalazione[] = giaRaccolte.slice();
  const conteggio = new Map<string, number>();
  RE_SEGNALAZIONI.lastIndex = 0;
  for (const corrispondenza of testo.matchAll(RE_SEGNALAZIONI)) {
    const parola = corrispondenza[2];
    const voce = BASE_3.get(parola);
    if (voce === undefined) continue;
    if (GATE_3.get(parola) === true && !gate) continue;
    const visto = conteggio.get(voce[0]) ?? 0;
    if (visto >= MAX_SEGN_PER_PAROLA) continue;
    conteggio.set(voce[0], visto + 1);
    fuori.push({
      regola: 'omografo',
      parola,
      occorrenza: visto + 1,
      suggerimento: voce[1],
    });
    if (fuori.length >= MAX_SEGN_PER_TESTO) break;
  }
  return fuori.slice(0, MAX_SEGN_PER_TESTO);
}

/**
 * Corregge gli accenti italiani mancanti o resi con l'apostrofo.
 *
 * E' idempotente sul testo: `correggi(correggi(x))` produce lo stesso testo
 * di `correggi(x)`. Non lo e' sulle segnalazioni, che dipendono per
 * costruzione dallo stato de-accentato del testo in ingresso.
 */
export function correggi(testo: string): RisultatoOrtografia {
  if (typeof testo !== 'string') return vuoto(testo as unknown as string, 'non_stringa');
  if (testo === '') return vuoto(testo, null);
  const originale = testo;
  if (RE_PUA.test(originale)) {
    // Sentinelli gia' presenti nel testo dell'autore: non si tocca nulla,
    // cancellarli in silenzio sarebbe perdita di dati.
    return vuoto(originale, 'pua_in_ingresso');
  }

  let lavorato = normalizzaTerminatori(originale);
  lavorato = lavorato.replace(RE_CONTROLLI, () => '');

  const store: string[] = [];
  lavorato = maschera(lavorato, store);
  lavorato = lavorato.normalize('NFC');
  lavorato = lavorato.replace(RE_APOSTROFO, (_m: string, sinistra: string) => sinistra + "'");

  const correzioni: Correzione[] = [];
  const conteggioCorr = new Map<string, number>();
  const registra = (da: string, a: string): void => {
    const visto = (conteggioCorr.get(da) ?? 0) + 1;
    conteggioCorr.set(da, visto);
    correzioni.push({ da, a, occorrenza: visto });
  };

  lavorato = lavorato.replace(
    RE_SE_PREP,
    (_m: string, sinistra: string, preposizione: string, parola: string) => {
      const sostituto = parola[0] === 's' ? 'sé' : 'Sé';
      registra(parola, sostituto);
      return sinistra + preposizione + sostituto;
    },
  );

  const segnalazioni2b: Segnalazione[] = [];
  const conteggio2b = new Map<string, number>();

  lavorato = lavorato.replace(RE_PRINCIPALE, (_m: string, sinistra: string, parola: string) => {
    const sostituto = MAPPA.get(parola);
    if (sostituto !== undefined) {
      registra(parola, sostituto);
      return sinistra + sostituto;
    }
    const visto = (conteggio2b.get(parola) ?? 0) + 1;
    conteggio2b.set(parola, visto);
    segnalazioni2b.push({
      regola: 'nome-proprio',
      parola,
      occorrenza: visto,
      suggerimento: SEGNALA_2B.get(parola) ?? '',
    });
    return sinistra + parola;
  });

  const segnalazioni = segnala(lavorato, correzioni.length > 0, segnalazioni2b);
  lavorato = smaschera(lavorato, store);

  if (RE_PUA.test(lavorato)) {
    // Smascheramento incompleto: si restituisce l'input ricevuto, non il
    // testo a meta' strada. Mai un fallback silenzioso.
    return vuoto(originale, 'sentinello_residuo');
  }

  return { testo: lavorato, correzioni, segnalazioni, saltato: null };
}

/** Scorciatoia per i chiamanti che vogliono solo il testo corretto. */
export function applica(testo: string): string {
  return correggi(testo).testo;
}

/** Tabelle esposte per il test di parita' con il gemello Python. */
export const TABELLE = {
  LISTA_2,
  LISTA_2B,
  SOLO_APOSTROFO,
  DENY,
  LISTA_3A,
  LISTA_3B,
  PREPOSIZIONI_SE,
};

/**
 * Interni esposti solo per i test strutturali di parita'. Non usarli dal
 * codice dell'applicazione: l'interfaccia pubblica e' correggi/applica.
 */
export const INTERNI = {
  MAPPA,
  SEGNALA_2B,
  RE_PRINCIPALE,
  RE_SEGNALAZIONI,
  RE_SE_PREP,
  MASCHERE,
  inizialeMaiuscola,
  tuttoMaiuscolo,
};
