/**
 * `src/lib/bandi/calendario.ts`: il «Calendario» della scheda come `timeline()`
 * del design «Bandi Redesign», piu' il ripiego sull'apertura quando manca la
 * pubblicazione (vale per il ~92% dei bandi).
 *
 * I due casi di riferimento sono i bandi del mock, con oggi = 25 settembre 2026.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { calendario, dataBreve } from '../../src/lib/bandi/calendario.ts';

const OGGI = '2026-09-25';

test('mock, Abruzzo in apertura: pubblicazione, apertura sotto la linea, oggi al 70,83%', () => {
  const c = calendario({
    stato: 'in apertura prossimamente',
    pubblicazione: '2026-07-02',
    apertura: '2026-07-06',
    scadenza: '2026-10-30',
    oggi: OGGI,
  });
  assert.ok(c);
  assert.deepEqual(c.sopra, [
    { x: '0.00%', tx: '0%', etichetta: 'Pubblicazione', data: '2 lug' },
    { x: '100.00%', tx: '-100%', etichetta: 'Scadenza', data: '30 ott' },
  ]);
  assert.deepEqual(c.sotto, [{ x: '3.33%', tx: '0%', etichetta: 'Apertura', data: '6 lug' }]);
  assert.deepEqual(c.punti, ['0.00%', '100.00%', '3.33%']);
  assert.equal(c.oggiX, '70.83%');
  assert.equal(c.oggiTx, '-50%');
  assert.equal(c.oggiEtichetta, 'Oggi · 25 set');
  // Non aperto: niente conto alla rovescia, la data di oggi.
  assert.equal(c.nota, 'Oggi è il 25 settembre 2026');
  assert.equal(c.trascorso, '70.8%');
});

test('mock, Piemonte aperto: «Mancano 36 giorni alla scadenza»', () => {
  const c = calendario({
    stato: 'aperto',
    pubblicazione: '2026-09-24',
    apertura: '2026-09-25',
    scadenza: '2026-10-31',
    oggi: OGGI,
  });
  assert.ok(c);
  assert.equal(c.nota, 'Mancano 36 giorni alla scadenza');
  assert.deepEqual(c.sotto, [{ x: '2.70%', tx: '0%', etichetta: 'Apertura', data: '25 set' }]);
  assert.equal(c.oggiX, '2.70%');
  assert.equal(c.oggiTx, '0%');
});

test('senza pubblicazione la linea parte dall\'apertura, con quell\'etichetta e nessuna tacca sotto', () => {
  const c = calendario({ stato: 'aperto', pubblicazione: null, apertura: '2026-09-01', scadenza: '2026-10-01', oggi: OGGI });
  assert.ok(c);
  assert.equal(c.sopra[0].etichetta, 'Apertura');
  assert.equal(c.sopra[0].data, '1 set');
  assert.deepEqual(c.sotto, []);
  assert.deepEqual(c.punti, ['0.00%', '100.00%']);
});

test('nessun calendario senza date utili o con la scadenza non dopo l\'inizio', () => {
  const base = { stato: 'aperto', pubblicazione: '2026-09-01', apertura: null, scadenza: '2026-10-01', oggi: OGGI };
  assert.equal(calendario({ ...base, scadenza: null }), null);
  assert.equal(calendario({ ...base, pubblicazione: null }), null);
  assert.equal(calendario({ ...base, scadenza: '2026-09-01' }), null);
  assert.equal(calendario({ ...base, scadenza: '2026-08-01' }), null);
  assert.equal(calendario({ ...base, scadenza: 'boh' }), null);
});

test('nota: singolare, oggi e scaduto', () => {
  const base = { pubblicazione: '2026-09-01', apertura: null, oggi: OGGI };
  assert.equal(calendario({ ...base, stato: 'aperto', scadenza: '2026-09-26' })?.nota, 'Manca 1 giorno alla scadenza');
  assert.equal(calendario({ ...base, stato: 'aperto', scadenza: '2026-09-25' })?.nota, 'Scade oggi');
  const chiuso = calendario({ ...base, stato: 'chiuso', scadenza: '2026-09-10' });
  assert.equal(chiuso?.nota, 'Oggi è il 25 settembre 2026');
  // Oggi oltre la scadenza: il segno resta sull'estremo destro, allineato a destra.
  assert.equal(chiuso?.oggiX, '100.00%');
  assert.equal(chiuso?.oggiTx, '-100%');
  assert.equal(chiuso?.trascorso, '100.0%');
});

test('dataBreve: «25 set», e una stringa illeggibile resta com\'e\'', () => {
  assert.equal(dataBreve('2026-09-25'), '25 set');
  assert.equal(dataBreve('2027-01-05'), '5 gen');
  assert.equal(dataBreve('boh'), 'boh');
});
