/**
 * parametri.ts: validazione rigorosa degli elenchi e forma canonica.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  validaQueryElenco, validaQueryAssente, validaIdPercorso, queryCanonica, filtriMeta, erroreCategoria,
  SPEC_PARAMETRI, ORDINE_PARAMETRI, type FiltriElenco,
} from '../../src/lib/api-v1/parametri.ts';
import type { Risorsa } from '../../src/lib/api-v1/contratto.ts';

function valida(risorsa: Risorsa, query: string) {
  return validaQueryElenco(risorsa, new URLSearchParams(query), query.length);
}
function ok(risorsa: Risorsa, query: string): FiltriElenco {
  const esito = valida(risorsa, query);
  assert.ok(esito.ok, `atteso valido: ${query} -> ${esito.ok ? '' : JSON.stringify(esito.problema.errori)}`);
  return esito.filtri;
}
function errore(risorsa: Risorsa, query: string) {
  const esito = valida(risorsa, query);
  assert.ok(!esito.ok, `atteso errore: ${query}`);
  return esito.problema;
}

test('SPEC_PARAMETRI segue l\'ordine canonico', () => {
  for (const [, nomi] of SPEC_PARAMETRI) {
    const posizioni = nomi.map((n) => ORDINE_PARAMETRI.indexOf(n));
    assert.deepEqual(posizioni, [...posizioni].sort((a, b) => a - b));
  }
});

test('valori predefiniti', () => {
  const f = ok('articles', '');
  assert.equal(f.limit, 20);
  assert.equal(f.category, null);
  assert.equal(f.cursor, null);
});

test('limit', () => {
  assert.equal(ok('articles', 'limit=1').limit, 1);
  assert.equal(ok('articles', 'limit=100').limit, 100);
  for (const v of ['0', '101', '01', 'abc', '-1', '1.5', ' 5', '1e2']) {
    const p = errore('articles', `limit=${encodeURIComponent(v)}`);
    assert.equal(p.codice, 'invalid-parameter', v);
    assert.equal(p.errori[0].parameter, 'limit');
  }
});

test('parametri sconosciuti, ripetuti, vuoti', () => {
  for (const nome of ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf', 'q', 'page']) {
    const p = errore('articles', `${nome}=1`);
    assert.equal(p.codice, 'unknown-parameter', nome);
    assert.equal(p.status, 400);
  }
  assert.equal(errore('articles', 'limit=5&limit=6').errori[0].detail.includes('piu\''), true);
  assert.equal(errore('articles', 'limit=').errori[0].parameter, 'limit');
  // national e updated_since non esistono sugli articoli ne' sugli interpelli
  assert.equal(errore('articles', 'national=true').codice, 'unknown-parameter');
  assert.equal(errore('articles', 'updated_since=2026-09-01').codice, 'unknown-parameter');
  assert.equal(errore('interpelli', 'national=true').codice, 'unknown-parameter');
  assert.equal(errore('interpelli', 'category=scuola').codice, 'unknown-parameter');
  // tutti gli errori raccolti
  assert.equal(errore('articles', 'limit=0&foo=1&has_video=si').errori.length, 3);
});

test('category: solo forma; appartenenza verificata dal chiamante', () => {
  assert.equal(ok('articles', 'category=scuola').category, 'scuola');
  for (const v of ['Scuola', 'scuola/', 'a--b', '-a', 'x'.repeat(65), 'scuola ']) {
    assert.equal(errore('articles', `category=${encodeURIComponent(v)}`).errori[0].parameter, 'category', v);
  }
  const p = erroreCategoria(['scuola', 'universita']);
  assert.equal(p.codice, 'invalid-parameter');
  assert.deepEqual(p.errori[0].allowed, ['scuola', 'universita']);
});

test('booleani esatti', () => {
  assert.equal(ok('articles', 'has_video=true').has_video, true);
  assert.equal(ok('articles', 'has_video=false').has_video, false);
  assert.equal(ok('bandi', 'national=false').national, false);
  for (const v of ['TRUE', '1', 'yes', 'True']) {
    assert.equal(errore('selezione-personale', `national=${v}`).errori[0].parameter, 'national', v);
  }
});

test('region dal registro delle regioni', () => {
  assert.equal(ok('interpelli', 'region=lazio').region, 'lazio');
  assert.equal(ok('bandi', 'region=valle-d-aosta').region, 'valle-d-aosta');
  for (const v of ['Lazio', 'constructor', 'lazio-', 'roma']) {
    const p = errore('interpelli', `region=${v}`);
    assert.equal(p.errori[0].allowed?.length, 20, v);
  }
});

test('istanti: forma canonica unica e since < until', () => {
  const a = ok('articles', 'since=2026-09-21T07:18:28.500Z');
  const b = ok('articles', 'since=2026-09-21T07:18:28Z');
  const c = ok('articles', `since=${encodeURIComponent('2026-09-21T09:18:28+02:00')}`);
  const d = ok('articles', 'since=2026-09-21T09:18:28+02:00'); // '+' non codificato -> spazio
  assert.equal(a.since, b.since);
  assert.equal(a.since, c.since);
  assert.equal(a.since, d.since);
  assert.equal(queryCanonica('articles', a, { conLimite: true, conCursore: true }).toString(),
    'since=2026-09-21T09%3A18%3A28%2B02%3A00');
  assert.equal(errore('articles', 'since=2026-09-21T09:18:28').errori[0].parameter, 'since');
  assert.equal(errore('articles', 'since=2026-02-30').errori[0].parameter, 'since');
  assert.equal(errore('articles', 'since=2026-09-10&until=2026-09-09').errori[0].parameter, 'until');
  // stesso giorno: [00:00, 00:00 del giorno dopo) e' valido
  const g = ok('articles', 'since=2026-09-10&until=2026-09-10');
  assert.equal(g.until! - g.since!, 24 * 3600 * 1000);
  assert.equal(errore('articles', 'since=2026-09-10T10:00:00Z&until=2026-09-10T10:00:00.900Z').errori[0].parameter, 'until');
});

test('cursore: solo caratteri base64url qui (decodifica in cursore.ts)', () => {
  assert.equal(ok('articles', 'cursor=abc_-XYZ').cursor, 'abc_-XYZ');
  assert.equal(errore('articles', 'cursor=a%2Bb').errori[0].parameter, 'cursor');
  assert.equal(errore('articles', `cursor=${'a'.repeat(301)}`).errori[0].parameter, 'cursor');
});

test('lunghezze massime', () => {
  assert.equal(errore('articles', `category=${'a'.repeat(257)}`).errori[0].parameter, 'category');
  const lunga = validaQueryElenco('articles', new URLSearchParams(''), 2049);
  assert.equal(lunga.ok, false);
});

test('dettagli: nessun parametro', () => {
  assert.equal(validaQueryAssente(new URLSearchParams(''), 0), null);
  const p = validaQueryAssente(new URLSearchParams('limit=1&x=2'), 11);
  assert.equal(p?.codice, 'unknown-parameter');
  assert.equal(p?.errori.length, 2);
});

test('id di percorso', () => {
  assert.equal(validaIdPercorso('39382'), 39382);
  for (const v of [undefined, '', '0', '01', '-1', '1.5', 'abc', '1e3', '12345678901234567', ' 1']) {
    assert.equal(validaIdPercorso(v), null, String(v));
  }
});

test('query canonica e meta.filters', () => {
  const f = ok('bandi', 'updated_since=2026-09-01&limit=20&region=lazio&national=true');
  // ordine canonico, limit predefinito omesso
  assert.equal(queryCanonica('bandi', f, { conLimite: true, conCursore: true }).toString(),
    'region=lazio&national=true&updated_since=2026-09-01T00%3A00%3A00%2B02%3A00');
  assert.deepEqual(filtriMeta('bandi', f), [
    ['region', 'lazio'], ['national', true], ['since', null], ['until', null], ['updated_since', '2026-09-01T00:00:00+02:00'],
  ]);
  const g = ok('articles', 'limit=5&category=scuola');
  assert.equal(queryCanonica('articles', g, { conLimite: true, conCursore: false }).toString(), 'category=scuola&limit=5');
  assert.equal(queryCanonica('articles', g, { conLimite: false, conCursore: false }).toString(), 'category=scuola');
  assert.deepEqual(filtriMeta('articles', g).map(([k]) => k), ['category', 'has_video', 'since', 'until']);
});
