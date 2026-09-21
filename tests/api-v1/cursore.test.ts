/**
 * cursore.ts: codifica/decodifica rigorosa e legame con i filtri.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { codificaCursore, decodificaCursore, chiaveCursoreValida, hashFiltri } from '../../src/lib/api-v1/cursore.ts';
import { validaQueryElenco, type FiltriElenco } from '../../src/lib/api-v1/parametri.ts';
import { ErroreDati } from '../../src/lib/api-v1/errori.ts';
import type { Risorsa } from '../../src/lib/api-v1/contratto.ts';

function filtri(risorsa: Risorsa, query: string): FiltriElenco {
  const e = validaQueryElenco(risorsa, new URLSearchParams(query), query.length);
  if (!e.ok) throw new Error(query);
  return e.filtri;
}

const RISORSE: Risorsa[] = ['articles', 'interpelli', 'selezione-personale', 'bandi'];

test('andata e ritorno per risorsa e per forme di valore', () => {
  const valori = [
    '2026-09-21T07:12:29.519', '2026-09-21T08:53:20.936282', '2026-09-21T07:12:29', '2026-09-17T00:00:00',
    '2026-09-14T16:03:02.418+00:00', '2026-10-06T21:59:00+00:00', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00-05:30',
  ];
  for (const r of RISORSE) {
    const f = filtri(r, '');
    for (const v of valori) {
      for (const id of [1, 38934, r === 'bandi' ? 2147483647 : Number.MAX_SAFE_INTEGER]) {
        const c = codificaCursore(r, f, v, id);
        assert.ok(c.length <= 300);
        assert.match(c, /^[A-Za-z0-9_-]+$/);
        assert.deepEqual(decodificaCursore(r, f, c), { grezzo: v, id });
      }
    }
  }
});

test('il cursore e\' legato ai filtri ma non a limit', () => {
  const f1 = filtri('articles', 'category=scuola');
  const f2 = filtri('articles', 'category=scuola&limit=5');
  const f3 = filtri('articles', 'category=universita');
  assert.equal(hashFiltri('articles', f1), hashFiltri('articles', f2));
  const c = codificaCursore('articles', f1, '2026-09-21T07:12:29.519', 10);
  assert.deepEqual(decodificaCursore('articles', f2, c), { grezzo: '2026-09-21T07:12:29.519', id: 10 });
  assert.equal(decodificaCursore('articles', f3, c), null);
  assert.equal(decodificaCursore('interpelli', filtri('interpelli', ''), c), null);
});

test('rifiuta cursori manomessi', () => {
  const f = filtri('articles', '');
  const codifica = (o: unknown) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const h = hashFiltri('articles', f);
  const casi: unknown[] = [
    { v: 2, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 1] },
    { v: 1, r: 'bandi', f: h, k: ['2026-09-21T07:12:29', 1] },
    { v: 1, r: 'articles', f: '00000000', k: ['2026-09-21T07:12:29', 1] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 1], extra: 1 },
    { v: 1, r: 'articles', f: h },
    { v: 1, r: 'articles', f: h, k: { a: 1 } },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29'] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 1, 2] },
    { v: 1, r: 'articles', f: h, k: [20260921, 1] },
    { v: 1, r: 'articles', f: h, k: [['x'], 1] },
    { v: 1, r: 'articles', f: h, k: ['2026-02-30T07:12:29', 1] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29","x', 1] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 0] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', -3] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 1.5] },
    { v: 1, r: 'articles', f: h, k: ['2026-09-21T07:12:29', 2 ** 60] },
    { v: 1, r: 'articles', f: h, k: ['infinity', 1] },
    [1, 2, 3],
    null,
    'stringa',
  ];
  for (const caso of casi) assert.equal(decodificaCursore('articles', f, codifica(caso)), null, JSON.stringify(caso));
  // __proto__ come chiave propria
  const conProto = Buffer.from(`{"v":1,"r":"articles","f":"${h}","__proto__":{},"k":["2026-09-21T07:12:29",1]}`).toString('base64url');
  assert.equal(decodificaCursore('articles', f, conProto), null);
  assert.equal(decodificaCursore('articles', f, 'non-base64!'), null);
  assert.equal(decodificaCursore('articles', f, 'eyJ2Ijox'), null);
  assert.equal(decodificaCursore('articles', f, 'a'.repeat(301)), null);
});

test('il server non emette cursori che rifiuterebbe', () => {
  const f = filtri('articles', '');
  for (const [v, id] of [['infinity', 1], ['2026-09-21 07:12:29', 1], ['10000-01-01T00:00:00', 1], ['2026-09-21T07:12:29', 0], ['2026-09-21T07:12:29', 2 ** 60]] as const) {
    assert.throws(() => codificaCursore('articles', f, v, id), ErroreDati, `${v} ${id}`);
  }
  assert.equal(chiaveCursoreValida('2026-09-21T07:12:29.1234567'), false);
  assert.equal(chiaveCursoreValida('2026-09-21T07:12:29.123456+02:00'), true);
});

test('bandi: id oltre int4 rifiutato nel cursore, le altre risorse restano int8', () => {
  const fb = filtri('bandi', '');
  const fa = filtri('articles', '');
  assert.deepEqual(decodificaCursore('bandi', fb, codificaCursore('bandi', fb, '2026-09-21T10:06:21.350498+00:00', 2147483647)),
    { grezzo: '2026-09-21T10:06:21.350498+00:00', id: 2147483647 });
  assert.throws(() => codificaCursore('bandi', fb, '2026-09-21T10:06:21+00:00', 2147483648), ErroreDati);
  const forgiato = Buffer.from(JSON.stringify({ v: 1, r: 'bandi', f: hashFiltri('bandi', fb), k: ['2026-09-21T10:06:21+00:00', 2147483648] })).toString('base64url');
  assert.equal(decodificaCursore('bandi', fb, forgiato), null);
  assert.deepEqual(decodificaCursore('articles', fa, codificaCursore('articles', fa, '2026-09-21T07:12:29', 2147483648)),
    { grezzo: '2026-09-21T07:12:29', id: 2147483648 });
});
