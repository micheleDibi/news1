/**
 * `src/lib/bandi/domini.ts` e la parità con il seed SQL.
 *
 * La denylist esiste in due posti (la tabella interna `dominio_ufficiale`, che
 * il frontend non può leggere con la anon key, e la costante TypeScript) e i
 * due devono restare identici: un host aggiunto solo al seed lascerebbe passare
 * i suoi link in pagina senza che nessuno se ne accorga. Il test legge il file
 * SQL con `readFileSync` (niente import di JSON: `tsconfig.json` non ha
 * `resolveJsonModule`) e confronta gli insiemi.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DOMINI_AGGREGATORI } from '../../src/config/domini-aggregatori.ts';
import { eAggregatore, hostDi, soloPubblicabili, urlPubblicabile } from '../../src/lib/bandi/domini.ts';

const SEED = new URL('../../backend/sql/bando_v11_seed_dominio_ufficiale.sql', import.meta.url);

/** Host delle righe `tipo='aggregatore'` degli INSERT del seed (commenti esclusi). */
function hostAggregatoriDelSeed(): string[] {
  const righe = readFileSync(SEED, 'utf8').split('\n');
  const host: string[] = [];
  for (const riga of righe) {
    if (riga.trimStart().startsWith('--')) continue;
    const trovato = /^\s*\('([^']+)',\s*'aggregatore'/.exec(riga);
    if (trovato !== null) host.push(trovato[1]);
  }
  return host;
}

test('denylist: parità con il seed SQL di dominio_ufficiale', () => {
  const nelSeed = hostAggregatoriDelSeed();
  assert.ok(nelSeed.length >= 25, `nel seed solo ${nelSeed.length} aggregatori: il parser non ha trovato gli INSERT`);
  assert.deepEqual([...nelSeed].sort(), [...DOMINI_AGGREGATORI].sort());
  assert.equal(new Set(DOMINI_AGGREGATORI).size, DOMINI_AGGREGATORI.length, 'duplicati nella costante');
  // L'aggregatore da cui viene l'80% del corpus non può mancare per nessun motivo.
  assert.ok((DOMINI_AGGREGATORI as readonly string[]).includes('obiettivoeuropa.com'));
});

test('hostDi: minuscolo, senza www., senza punto finale', () => {
  assert.equal(hostDi('https://WWW.Comune.Esempio.IT/bandi?x=1#y'), 'comune.esempio.it');
  assert.equal(hostDi('http://obiettivoeuropa.com./scheda'), 'obiettivoeuropa.com');
  assert.equal(hostDi('  https://regione.marche.it/  '), 'regione.marche.it');
  // Non è un URL assoluto: niente host da cui ricavare qualcosa.
  assert.equal(hostDi('/bandi/qualcosa'), null);
  assert.equal(hostDi('non un url'), null);
  assert.equal(hostDi(''), null);
  assert.equal(hostDi(null), null);
  assert.equal(hostDi(undefined), null);
});

test('eAggregatore: confronto per etichette, mai per sottostringa', () => {
  assert.equal(eAggregatore('obiettivoeuropa.com'), true);
  assert.equal(eAggregatore('www.obiettivoeuropa.com'), true);
  assert.equal(eAggregatore('api.obiettivoeuropa.com'), true);
  assert.equal(eAggregatore('OBIETTIVOEUROPA.COM'), true);
  assert.equal(eAggregatore('first.aster.it'), true);
  // Il bug che il confronto per suffisso di etichetta evita: questi NON sono
  // in denylist, mentre un `includes()` li avrebbe bloccati (o lasciati passare).
  assert.equal(eAggregatore('nonobiettivoeuropa.com'), false);
  assert.equal(eAggregatore('obiettivoeuropa.com.example.org'), false);
  assert.equal(eAggregatore('aster.it'), false);
  assert.equal(eAggregatore('regione.marche.it'), false);
  assert.equal(eAggregatore(''), false);
  assert.equal(eAggregatore(null), false);
});

test('urlPubblicabile: solo http(s), mai aggregatori, mai javascript:/data:', () => {
  assert.equal(urlPubblicabile('https://regione.marche.it/bando'), true);
  assert.equal(urlPubblicabile('http://comune.esempio.it/atto.pdf'), true);
  // Lo schema: `escapeAttr` (la difesa precedente) non fermava nessuno di questi.
  assert.equal(urlPubblicabile('javascript:alert(1)'), false);
  assert.equal(urlPubblicabile('JavaScript:alert(1)'), false);
  assert.equal(urlPubblicabile('data:text/html;base64,PHNjcmlwdD4='), false);
  assert.equal(urlPubblicabile('mailto:info@comune.esempio.it'), false);
  assert.equal(urlPubblicabile('ftp://comune.esempio.it/file'), false);
  // La denylist.
  assert.equal(urlPubblicabile('https://www.obiettivoeuropa.com/scheda/123'), false);
  assert.equal(urlPubblicabile('https://youtu.be/abc'), false);
  // Non analizzabile o relativo.
  assert.equal(urlPubblicabile('/bandi/relativo'), false);
  assert.equal(urlPubblicabile(''), false);
  assert.equal(urlPubblicabile(null), false);
});

test('soloPubblicabili: conserva l\'ordine e scarta il resto', () => {
  const allegati = [
    { url: 'https://regione.marche.it/a.pdf' },
    { url: 'https://obiettivoeuropa.com/b.pdf' },
    { url: 'javascript:void(0)' },
    { url: 'https://comune.esempio.it/c.pdf' },
  ];
  assert.deepEqual(soloPubblicabili(allegati, (a) => a.url).map((a) => a.url), [
    'https://regione.marche.it/a.pdf',
    'https://comune.esempio.it/c.pdf',
  ]);
  assert.deepEqual(soloPubblicabili(null, (a: { url: string }) => a.url), []);
});
