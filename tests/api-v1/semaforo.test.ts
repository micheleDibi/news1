/**
 * semaforo.ts: slot, coda FIFO, coda piena, attesa scaduta, rilascio idempotente e su
 * eccezione, provaAcquisire, nessun timer pendente a riposo.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { Semaforo, SemaforoSaturo } from '../../src/lib/api-v1/semaforo.ts';

/** Timer reali attivi nel processo (per verificare che il semaforo non ne lasci). */
function timerAttivi(): number {
  return process.getActiveResourcesInfo().filter((r) => r === 'Timeout').length;
}

/** Lascia girare le microtask. */
async function svuotaMicrotask(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

function eSaturo(motivo: 'coda-piena' | 'attesa-scaduta'): (errore: unknown) => boolean {
  return (errore) => errore instanceof SemaforoSaturo && errore.motivo === motivo;
}

test('SemaforoSaturo: e\' un Error con motivo e nome', () => {
  const e = new SemaforoSaturo('coda-piena');
  assert.ok(e instanceof Error);
  assert.equal(e.name, 'SemaforoSaturo');
  assert.equal(e.motivo, 'coda-piena');
  assert.equal(new SemaforoSaturo('attesa-scaduta').motivo, 'attesa-scaduta');
});

test('parametri non validi rifiutati', () => {
  assert.throws(() => new Semaforo({ slot: 0, coda: 1, attesaMs: 1 }), RangeError);
  assert.throws(() => new Semaforo({ slot: 1.5, coda: 1, attesaMs: 1 }), RangeError);
  assert.throws(() => new Semaforo({ slot: 1, coda: -1, attesaMs: 1 }), RangeError);
  assert.throws(() => new Semaforo({ slot: 1, coda: 1, attesaMs: Number.NaN }), RangeError);
});

test('slot liberi concessi subito, poi coda FIFO servita al rilascio', async () => {
  const baseline = timerAttivi();
  const s = new Semaforo({ slot: 2, coda: 3, attesaMs: 60_000 });
  const r1 = await s.acquisisci();
  const r2 = await s.acquisisci();
  assert.equal(s.inUso, 2);
  assert.equal(s.inCoda, 0);
  assert.equal(timerAttivi(), baseline, 'nessun timer per chi ottiene subito lo slot');

  const ordine: string[] = [];
  const p3 = s.acquisisci().then((r) => { ordine.push('terzo'); return r; });
  const p4 = s.acquisisci().then((r) => { ordine.push('quarto'); return r; });
  const p5 = s.acquisisci().then((r) => { ordine.push('quinto'); return r; });
  assert.equal(s.inCoda, 3);
  assert.equal(timerAttivi(), baseline + 3, 'un timer d\'attesa per elemento in coda');

  r2();
  const r3 = await p3;
  assert.deepEqual(ordine, ['terzo']);
  assert.equal(s.inUso, 2);
  assert.equal(s.inCoda, 2);

  r1();
  r3();
  const r4 = await p4;
  const r5 = await p5;
  assert.deepEqual(ordine, ['terzo', 'quarto', 'quinto']);
  assert.equal(s.inCoda, 0);
  assert.equal(s.inUso, 2);
  assert.equal(timerAttivi(), baseline, 'i timer degli elementi serviti sono cancellati');

  r4();
  r5();
  assert.equal(s.inUso, 0);
  assert.equal(timerAttivi(), baseline, 'a riposo nessun timer pendente');
});

test('coda piena: rifiuto immediato con motivo coda-piena', async () => {
  const s = new Semaforo({ slot: 1, coda: 1, attesaMs: 60_000 });
  const r1 = await s.acquisisci();
  const inCoda = s.acquisisci();
  await assert.rejects(s.acquisisci(), eSaturo('coda-piena'));
  assert.equal(s.inCoda, 1);
  r1();
  const r2 = await inCoda;
  r2();
  assert.equal(s.inUso, 0);

  // coda 0: nessuna attesa possibile
  const senzaCoda = new Semaforo({ slot: 1, coda: 0, attesaMs: 60_000 });
  const unico = await senzaCoda.acquisisci();
  await assert.rejects(senzaCoda.acquisisci(), eSaturo('coda-piena'));
  unico();
});

test('attesa scaduta: rifiuto, elemento tolto dalla coda, gli altri restano in ordine', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const s = new Semaforo({ slot: 1, coda: 3, attesaMs: 2_000 });
  const r1 = await s.acquisisci();

  const primo = s.acquisisci();
  t.mock.timers.tick(1_000);
  const secondo = s.acquisisci();
  const esito: { errore: unknown } = { errore: null };
  primo.catch((e: unknown) => { esito.errore = e; });

  t.mock.timers.tick(999);
  await svuotaMicrotask();
  assert.equal(esito.errore, null, 'prima dei 2 s nessun rifiuto');
  t.mock.timers.tick(1);
  await svuotaMicrotask();
  assert.ok(eSaturo('attesa-scaduta')(esito.errore));
  await assert.rejects(primo, eSaturo('attesa-scaduta'));
  assert.equal(s.inCoda, 1);
  assert.equal(s.inUso, 1);

  // il secondo e' ancora in tempo: il rilascio lo serve e il suo timer non scatta piu'
  r1();
  const r2 = await secondo;
  assert.equal(s.inCoda, 0);
  t.mock.timers.tick(10_000);
  await svuotaMicrotask();
  assert.equal(s.inUso, 1);
  r2();
  assert.equal(s.inUso, 0);
});

test('timer d\'attesa cancellato quando l\'elemento e\' servito (timer reali)', async () => {
  const baseline = timerAttivi();
  const s = new Semaforo({ slot: 1, coda: 1, attesaMs: 60_000 });
  const r1 = await s.acquisisci();
  const attesa = s.acquisisci();
  assert.equal(timerAttivi(), baseline + 1);
  r1();
  const r2 = await attesa;
  assert.equal(timerAttivi(), baseline, 'clearTimeout chiamato: nessun timer da 60 s pendente');
  r2();
  assert.equal(timerAttivi(), baseline);
});

test('attesa scaduta con timer reali brevi', async () => {
  const baseline = timerAttivi();
  const s = new Semaforo({ slot: 1, coda: 2, attesaMs: 20 });
  const r1 = await s.acquisisci();
  await assert.rejects(s.acquisisci(), eSaturo('attesa-scaduta'));
  assert.equal(s.inCoda, 0);
  assert.equal(timerAttivi(), baseline);
  r1();
  assert.equal(s.inUso, 0);
});

test('rilascio idempotente: un secondo rilascio non libera un altro slot', async () => {
  const s = new Semaforo({ slot: 1, coda: 2, attesaMs: 60_000 });
  const r1 = await s.acquisisci();
  const p2 = s.acquisisci();
  const p3 = s.acquisisci();
  r1();
  r1();
  r1();
  const r2 = await p2;
  await svuotaMicrotask();
  assert.equal(s.inUso, 1);
  assert.equal(s.inCoda, 1, 'il terzo aspetta ancora: i rilasci ripetuti non contano');
  r2();
  const r3 = await p3;
  r3();
  r3();
  assert.equal(s.inUso, 0);
  assert.equal(s.inCoda, 0);
});

test('rilascio su eccezione con try/finally', async () => {
  const s = new Semaforo({ slot: 1, coda: 0, attesaMs: 1_000 });
  async function lavoro(): Promise<never> {
    const rilascia = await s.acquisisci();
    try {
      throw new Error('guasto del DB');
    } finally {
      rilascia();
    }
  }
  await assert.rejects(lavoro(), /guasto del DB/);
  assert.equal(s.inUso, 0);
  const r = await s.acquisisci();
  r();
});

test('provaAcquisire: slot libero -> rilascio; pieno o con coda -> null', async () => {
  const s = new Semaforo({ slot: 2, coda: 2, attesaMs: 60_000 });
  const a = s.provaAcquisire();
  assert.ok(a !== null);
  assert.equal(s.inUso, 1);
  const b = s.provaAcquisire();
  assert.ok(b !== null);
  assert.equal(s.provaAcquisire(), null);
  assert.equal(s.inUso, 2);

  // con qualcuno in coda non si scavalca: il rilascio va a chi aspetta
  const inAttesa = s.acquisisci();
  a();
  assert.equal(s.provaAcquisire(), null);
  const c = await inAttesa;
  assert.equal(s.inUso, 2);

  b();
  c();
  assert.equal(s.inUso, 0);
  const d = s.provaAcquisire();
  assert.ok(d !== null);
  d();
  d();
  assert.equal(s.inUso, 0);
});
