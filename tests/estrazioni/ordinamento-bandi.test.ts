/**
 * `src/lib/bandi/ordinamento.ts`: come una pagina della lista si divide fra i
 * tre segmenti di «Scadenza più vicina» (future, senza data, scadute).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { ordinamentoDa, pianoPagina } from '../../src/lib/bandi/ordinamento.ts';

test('pagina tutta dentro il primo segmento', () => {
  assert.deepEqual(pianoPagina(0, 23, [100, 50, 900]), [{ segmento: 0, da: 0, a: 23 }]);
});

test('pagina a cavallo fra due segmenti: il secondo riparte da zero', () => {
  assert.deepEqual(pianoPagina(96, 119, [100, 50, 900]), [
    { segmento: 0, da: 96, a: 99 },
    { segmento: 1, da: 0, a: 19 },
  ]);
});

test('pagina che attraversa un segmento intero', () => {
  assert.deepEqual(pianoPagina(0, 23, [10, 5, 900]), [
    { segmento: 0, da: 0, a: 9 },
    { segmento: 1, da: 0, a: 4 },
    { segmento: 2, da: 0, a: 8 },
  ]);
});

test('segmenti vuoti saltati, pagina nell\'ultimo', () => {
  assert.deepEqual(pianoPagina(48, 71, [0, 30, 100]), [{ segmento: 2, da: 18, a: 41 }]);
  assert.deepEqual(pianoPagina(0, 23, [0, 0, 0]), []);
});

test('pagina oltre la fine: nessun tratto; coda parziale', () => {
  assert.deepEqual(pianoPagina(200, 223, [100, 50, 20]), []);
  assert.deepEqual(pianoPagina(168, 191, [100, 50, 20]), [{ segmento: 2, da: 18, a: 19 }]);
});

test('ordinamentoDa: solo importo e recenti, il resto e\' il predefinito', () => {
  assert.equal(ordinamentoDa('importo'), 'importo');
  assert.equal(ordinamentoDa('recenti'), 'recenti');
  assert.equal(ordinamentoDa(undefined), 'scadenza');
  assert.equal(ordinamentoDa('scadenza'), 'scadenza');
  assert.equal(ordinamentoDa('boh'), 'scadenza');
});
