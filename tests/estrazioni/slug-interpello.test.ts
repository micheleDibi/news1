/**
 * slugInterpello dopo l'estrazione in src/lib/liste/slug-interpello.ts.
 *
 * Due difese:
 *  1. identita' con una copia letterale della vecchia implementazione
 *     (liste/interpelli.ts prima dell'estrazione): l'estrazione non cambia nulla;
 *  2. parita' con il gemello Python `_generate_interpello_slug`
 *     (backend/app/interpelli.py), eseguito isolato: gli URL delle schede sono
 *     indicizzati e le due copie devono produrre lo stesso slug.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { slugInterpello, type CampiSlugInterpello } from '../../src/lib/liste/slug-interpello.ts';

// Copia letterale della vecchia implementazione (non modificare).
function slugInterpelloVecchio(interpello: CampiSlugInterpello): string {
  const parts = [
    interpello.interpello_name,
    interpello.interpello_provincia || interpello.interpello_citta,
    interpello.interpello_regione,
    interpello.id?.toString(),
  ].filter(Boolean);

  return parts
    .join('-')
    .toLowerCase()
    .replace(/[^a-z0-9\-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

// PRNG deterministico (mulberry32): stessi casi a ogni esecuzione.
function prng(seme: number): () => number {
  let a = seme >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ALFABETO = [
  ...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
  ' ', ' ', '-', '--', '_', '.', ',', "'", '’', '"', '/', '(', ')', ':', '&', '+',
  'à', 'è', 'é', 'ì', 'ò', 'ù', 'À', 'È', 'É', 'ß', 'ẞ', 'Σ', 'ς', 'ü', 'Ö',
  'K', 'İ', 'ı', ' ', '\t', '\n', '😀', '🇮🇹', '\uD800', '\uDC00',
];

// I surrogati spaiati non sono codificabili in UTF-8 verso Python: il campione
// per la parita' li esclude (restano nel confronto con la vecchia implementazione).
const ALFABETO_UTF8 = ALFABETO.filter((c) => c !== '\uD800' && c !== '\uDC00');

function stringaCasuale(r: () => number, alfabeto: readonly string[]): string | null | undefined {
  const x = r();
  if (x < 0.04) return null;
  if (x < 0.08) return undefined;
  if (x < 0.1) return '';
  const lunghezza = Math.floor(r() * 40);
  let s = '';
  for (let i = 0; i < lunghezza; i++) s += alfabeto[Math.floor(r() * alfabeto.length)];
  return s;
}

function casiCasuali(n: number, alfabeto: readonly string[] = ALFABETO): CampiSlugInterpello[] {
  const r = prng(20260921);
  const casi: CampiSlugInterpello[] = [];
  for (let i = 0; i < n; i++) {
    const caso: CampiSlugInterpello = { id: 1 + Math.floor(r() * 3_000_000) };
    const nome = stringaCasuale(r, alfabeto);
    const provincia = stringaCasuale(r, alfabeto);
    const citta = stringaCasuale(r, alfabeto);
    const regione = stringaCasuale(r, alfabeto);
    if (nome !== undefined) caso.interpello_name = nome;
    if (provincia !== undefined) caso.interpello_provincia = provincia;
    if (citta !== undefined) caso.interpello_citta = citta;
    if (regione !== undefined) caso.interpello_regione = regione;
    casi.push(caso);
  }
  return casi;
}

const CASI_FISSI: CampiSlugInterpello[] = [
  { id: 1636, interpello_name: 'Interpello supplenze AAAA e ADAA - Scuola Infanzia', interpello_provincia: 'Roma', interpello_regione: 'Lazio' },
  { id: 12, interpello_name: 'Interpello', interpello_citta: 'Castel Madama', interpello_regione: 'Lazio' },
  { id: 7, interpello_name: 'Interpello', interpello_provincia: '', interpello_citta: 'Aosta', interpello_regione: "Valle d'Aosta" },
  { id: 8, interpello_name: 'Scuola dell’infanzia – sostegno', interpello_provincia: 'Forlì-Cesena', interpello_regione: 'Emilia-Romagna' },
  { id: 9, interpello_name: 'https://web.spaggiari.eu/sdg2/Documenti/GOME0015/208012662', interpello_regione: 'Lombardia' },
  { id: 10, interpello_name: 'Interpelli Pubblicati Da:Roma', interpello_provincia: 'Interpelli Pubblicati Da:Roma' },
  { id: 11, interpello_name: '---', interpello_provincia: '--a--', interpello_regione: '-' },
  { id: 13, interpello_name: ' ', interpello_regione: null },
  { id: 14 },
  { id: 15, interpello_name: 'ÀÈÉ 😀 Kİ ßẞ', interpello_citta: 'Città' },
  { id: 16, interpello_name: 'Classe A022 (ex A043)', interpello_provincia: null, interpello_citta: 'Napoli', interpello_regione: 'Campania' },
];

test('slugInterpello: identico alla vecchia implementazione', () => {
  for (const caso of [...CASI_FISSI, ...casiCasuali(5000)]) {
    assert.equal(slugInterpello(caso), slugInterpelloVecchio(caso), JSON.stringify(caso));
  }
});

test('slugInterpello: casi noti', () => {
  assert.equal(
    slugInterpello(CASI_FISSI[0]),
    'interpello-supplenze-aaaa-e-adaa-scuola-infanzia-roma-lazio-1636',
  );
  assert.equal(slugInterpello({ id: 14 }), '14');
  assert.equal(slugInterpello(CASI_FISSI[6]), 'a-11');
});

// Esegue in un processo python3 isolato la SOLA funzione _generate_interpello_slug,
// estratta dal sorgente con ast (senza importare il modulo, che ha dipendenze).
const SCRIPT_PYTHON = `
import ast, json, sys
percorso = sys.argv[1]
albero = ast.parse(open(percorso, encoding='utf-8').read())
funzione = next(n for n in albero.body if isinstance(n, ast.FunctionDef) and n.name == '_generate_interpello_slug')
modulo = ast.Module(body=[funzione], type_ignores=[])
spazio = {}
exec(compile(modulo, percorso, 'exec'), spazio)
casi = json.loads(sys.stdin.read())
print(json.dumps([spazio['_generate_interpello_slug'](c) for c in casi]))
`;

test('slugInterpello: parita\' con il gemello Python', (t) => {
  const percorsoPython = fileURLToPath(new URL('../../backend/app/interpelli.py', import.meta.url));
  const senzaSurrogatiSpaiati = (c: CampiSlugInterpello) =>
    ![c.interpello_name, c.interpello_provincia, c.interpello_citta, c.interpello_regione]
      .some((v) => typeof v === 'string' && /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(v));
  const casi = [...CASI_FISSI, ...casiCasuali(5000, ALFABETO_UTF8)].filter(senzaSurrogatiSpaiati);
  let uscita: string;
  try {
    uscita = execFileSync('python3', ['-I', '-B', '-c', SCRIPT_PYTHON, percorsoPython], {
      input: JSON.stringify(casi),
      timeout: 10_000,
      maxBuffer: 16 * 1024 * 1024,
      encoding: 'utf8',
    });
  } catch (errore) {
    if ((errore as NodeJS.ErrnoException).code === 'ENOENT') {
      t.skip('python3 non disponibile');
      return;
    }
    throw errore;
  }
  const attesi = JSON.parse(uscita) as string[];
  assert.equal(attesi.length, casi.length);
  // il filtro sui surrogati spaiati non deve svuotare il campione (emoji comprese)
  assert.ok(casi.length > 5000, `solo ${casi.length} casi confrontati`);
  assert.ok(casi.some((c) => c.interpello_name?.includes('😀')), 'nessuna emoji nel campione');
  casi.forEach((caso, i) => {
    assert.equal(slugInterpello(caso), attesi[i], JSON.stringify(caso));
  });
});
