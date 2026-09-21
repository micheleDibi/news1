/**
 * stato-bando.ts: logica estratta da supabase-bandi.ts (ri-esportata da li').
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveStatoBando, todayRomeISO, STATI_BANDO } from '../../src/lib/stato-bando.ts';

test('todayRomeISO: data del calendario di Roma, a prescindere dal fuso del processo', () => {
  assert.equal(todayRomeISO(new Date('2026-06-30T21:59:59Z')), '2026-06-30');
  assert.equal(todayRomeISO(new Date('2026-06-30T22:00:00Z')), '2026-07-01');
  // cambio d'ora di marzo (+01:00 -> +02:00) e di ottobre (+02:00 -> +01:00)
  assert.equal(todayRomeISO(new Date('2026-03-28T22:59:59Z')), '2026-03-28');
  assert.equal(todayRomeISO(new Date('2026-03-28T23:00:00Z')), '2026-03-29');
  assert.equal(todayRomeISO(new Date('2026-10-24T21:59:59Z')), '2026-10-24');
  assert.equal(todayRomeISO(new Date('2026-10-24T22:00:00Z')), '2026-10-25');
  assert.equal(todayRomeISO(new Date('2026-12-31T23:00:00Z')), '2027-01-01');
});

test('todayRomeISO: senza argomenti usa l\'istante corrente', () => {
  assert.match(todayRomeISO(), /^\d{4}-\d{2}-\d{2}$/);
});

test('effectiveStatoBando: il giorno di scadenza e\' ancora valido', () => {
  const oggi = '2026-09-21';
  assert.equal(effectiveStatoBando('aperto', '2026-09-21', oggi), 'aperto');
  assert.equal(effectiveStatoBando('aperto', '2026-09-20', oggi), 'chiuso');
  assert.equal(effectiveStatoBando('aperto', '2026-09-22', oggi), 'aperto');
  assert.equal(effectiveStatoBando('aperto', null, oggi), 'aperto');
  assert.equal(effectiveStatoBando('in apertura prossimamente', '2026-01-01', oggi), 'chiuso');
  // la scadenza puo' solo chiudere, mai riaprire
  assert.equal(effectiveStatoBando('chiuso', '2030-01-01', oggi), 'chiuso');
  assert.equal(effectiveStatoBando(null, null, oggi), null);
  assert.equal(effectiveStatoBando(undefined, '2030-01-01', oggi), null);
  // una data con orario conta solo per il giorno
  assert.equal(effectiveStatoBando('aperto', '2026-09-21T23:59:00', oggi), 'aperto');
});

test('effectiveStatoBando: senza "oggi" usa la data corrente di Roma', () => {
  assert.equal(effectiveStatoBando('aperto', '2000-01-01'), 'chiuso');
  assert.equal(effectiveStatoBando('aperto', '2999-01-01'), 'aperto');
});

test('STATI_BANDO invariati', () => {
  assert.deepEqual([...STATI_BANDO], ['aperto', 'chiuso', 'in apertura prossimamente']);
});
