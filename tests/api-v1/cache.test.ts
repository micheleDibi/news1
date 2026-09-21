/**
 * cache.ts: fresco, stale-while-revalidate con un solo rinfresco, rinfresco fallito
 * (mai unhandledRejection, riprova dopo 10 s), single-flight, errori mai salvati,
 * eviction per voci e per byte, stale-if-error, attendiRinfreschi.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { CacheRisposte } from '../../src/lib/api-v1/cache.ts';
import type { ModoProduzione, PoliticaCache } from '../../src/lib/api-v1/cache.ts';

const POLITICA: PoliticaCache = { freschezzaMs: 60_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 };

interface Orologio {
  ora: () => number;
  avanza: (ms: number) => void;
}

function orologioFinto(): Orologio {
  let adesso = 1_700_000_000_000;
  return { ora: () => adesso, avanza: (ms) => { adesso += ms; } };
}

function nuovaCache(
  orologio: Orologio,
  opzioni: { maxVoci?: number; maxByte?: number; errori?: Array<[string, unknown]> } = {},
): CacheRisposte<string> {
  return new CacheRisposte<string>({
    maxVoci: opzioni.maxVoci ?? 100,
    maxByte: opzioni.maxByte ?? 1_000_000,
    orologio: orologio.ora,
    misura: (v) => v.length,
    suErroreSfondo: (chiave, errore) => { opzioni.errori?.push([chiave, errore]); },
  });
}

/** Produttore che registra i modi con cui e' chiamato e restituisce valori in sequenza. */
function produttore(valori: string[]): { chiamate: ModoProduzione[]; produci: (modo: ModoProduzione) => Promise<string> } {
  const chiamate: ModoProduzione[] = [];
  let i = 0;
  return {
    chiamate,
    produci: async (modo) => {
      chiamate.push(modo);
      const valore = valori[Math.min(i, valori.length - 1)];
      i++;
      return valore;
    },
  };
}

/** Promessa risolvibile dall'esterno. */
function differita<T>(): { promessa: Promise<T>; risolvi: (v: T) => void; rifiuta: (e: unknown) => void } {
  let risolvi: (v: T) => void = () => undefined;
  let rifiuta: (e: unknown) => void = () => undefined;
  const promessa = new Promise<T>((ok, ko) => { risolvi = ok; rifiuta = ko; });
  return { promessa, risolvi, rifiuta };
}

/** Registra le unhandledRejection per tutta la durata del test. */
function sorvegliaRejection(t: { after: (fn: () => void) => void }): unknown[] {
  const raccolte: unknown[] = [];
  const ascoltatore = (motivo: unknown): void => { raccolte.push(motivo); };
  process.on('unhandledRejection', ascoltatore);
  t.after(() => { process.off('unhandledRejection', ascoltatore); });
  return raccolte;
}

/** Due giri di macrotask: le unhandledRejection vengono emesse dopo le microtask. */
async function lasciaGirare(): Promise<void> {
  await new Promise<void>((ok) => setImmediate(ok));
  await new Promise<void>((ok) => setImmediate(ok));
}

test('parametri non validi rifiutati', () => {
  const orologio = (): number => 0;
  const misura = (v: string): number => v.length;
  assert.throws(() => new CacheRisposte<string>({ maxVoci: 0, maxByte: 10, orologio, misura }), RangeError);
  assert.throws(() => new CacheRisposte<string>({ maxVoci: 1, maxByte: 0, orologio, misura }), RangeError);
});

test('miss -> prodotto in primo piano, poi fresco senza altre produzioni', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  const p = produttore(['v1']);
  assert.deepEqual(await cache.ottieni('k', POLITICA, p.produci), { valore: 'v1', origine: 'prodotto' });
  assert.deepEqual(p.chiamate, ['primo-piano']);
  t.avanza(59_999);
  assert.deepEqual(await cache.ottieni('k', POLITICA, p.produci), { valore: 'v1', origine: 'fresco' });
  assert.deepEqual(p.chiamate, ['primo-piano']);
  assert.deepEqual(cache.dimensione, { voci: 1, byte: 2 });
});

test('SWR: voce vecchia servita subito, un solo rinfresco in background, poi fresca', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  await cache.ottieni('k', POLITICA, produttore(['v1']).produci);
  t.avanza(60_000);

  const rinfresco = differita<string>();
  const chiamate: ModoProduzione[] = [];
  const produci = (modo: ModoProduzione): Promise<string> => { chiamate.push(modo); return rinfresco.promessa; };

  const risposte = await Promise.all([
    cache.ottieni('k', POLITICA, produci),
    cache.ottieni('k', POLITICA, produci),
    cache.ottieni('k', POLITICA, produci),
  ]);
  for (const r of risposte) assert.deepEqual(r, { valore: 'v1', origine: 'swr' });
  await Promise.resolve();
  assert.deepEqual(chiamate, ['sfondo'], 'un solo rinfresco per chiave');

  rinfresco.risolvi('v2');
  await cache.attendiRinfreschi();
  assert.deepEqual(await cache.ottieni('k', POLITICA, produci), { valore: 'v2', origine: 'fresco' });
  assert.deepEqual(chiamate, ['sfondo']);
});

test('SWR: al limite della finestra si torna al primo piano', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  await cache.ottieni('k', POLITICA, produttore(['v1']).produci);
  t.avanza(60_000 + 120_000 - 1);
  const p = produttore(['v2']);
  assert.equal((await cache.ottieni('k', POLITICA, p.produci)).origine, 'swr');
  await cache.attendiRinfreschi();
  t.avanza(180_000);
  const q = produttore(['v3']);
  assert.deepEqual(await cache.ottieni('k', POLITICA, q.produci), { valore: 'v3', origine: 'prodotto' });
  assert.deepEqual(q.chiamate, ['primo-piano']);
});

test('rinfresco fallito: voce intatta, errore al callback, nessuna unhandledRejection, riprova dopo 10 s', async (tt) => {
  const rejection = sorvegliaRejection(tt);
  const t = orologioFinto();
  const errori: Array<[string, unknown]> = [];
  const cache = nuovaCache(t, { errori });
  await cache.ottieni('k', POLITICA, produttore(['v1']).produci);
  t.avanza(70_000);

  const guasto = new Error('DB giu\'');
  let tentativi = 0;
  const fallisce = async (modo: ModoProduzione): Promise<string> => {
    assert.equal(modo, 'sfondo');
    tentativi++;
    throw guasto;
  };
  assert.deepEqual(await cache.ottieni('k', POLITICA, fallisce), { valore: 'v1', origine: 'swr' });
  await cache.attendiRinfreschi();
  await lasciaGirare();
  assert.equal(tentativi, 1);
  assert.deepEqual(errori, [['k', guasto]]);
  assert.deepEqual(rejection, []);

  // entro 10 s dal fallimento nessun nuovo tentativo, la voce resta servita
  t.avanza(9_999);
  assert.deepEqual(await cache.ottieni('k', POLITICA, fallisce), { valore: 'v1', origine: 'swr' });
  await cache.attendiRinfreschi();
  assert.equal(tentativi, 1);

  // dopo 10 s si riprova; un produttore che lancia in modo sincrono e' gestito uguale
  t.avanza(1);
  const lanciaSubito = (): Promise<string> => { tentativi++; throw new Error('sincrono'); };
  assert.deepEqual(await cache.ottieni('k', POLITICA, lanciaSubito), { valore: 'v1', origine: 'swr' });
  await cache.attendiRinfreschi();
  await lasciaGirare();
  assert.equal(tentativi, 2);
  assert.equal(errori.length, 2);
  assert.deepEqual(rejection, []);

  // un callback di log che lancia non rompe nulla
  const cacheCallbackRotto = new CacheRisposte<string>({
    maxVoci: 10, maxByte: 1_000, orologio: t.ora, misura: (v) => v.length,
    suErroreSfondo: () => { throw new Error('logger rotto'); },
  });
  await cacheCallbackRotto.ottieni('k', POLITICA, produttore(['v1']).produci);
  t.avanza(70_000);
  assert.equal((await cacheCallbackRotto.ottieni('k', POLITICA, fallisce)).origine, 'swr');
  await cacheCallbackRotto.attendiRinfreschi();
  await lasciaGirare();
  assert.deepEqual(rejection, []);

  // dopo il successo del rinfresco la voce e' nuova
  t.avanza(10_000);
  assert.equal((await cache.ottieni('k', POLITICA, produttore(['v2']).produci)).origine, 'swr');
  await cache.attendiRinfreschi();
  assert.deepEqual(await cache.ottieni('k', POLITICA, fallisce), { valore: 'v2', origine: 'fresco' });
});

test('single-flight in primo piano: una produzione, gli altri agganciati', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  const produzione = differita<string>();
  const chiamate: ModoProduzione[] = [];
  const produci = (modo: ModoProduzione): Promise<string> => { chiamate.push(modo); return produzione.promessa; };

  const a = cache.ottieni('k', POLITICA, produci);
  const b = cache.ottieni('k', POLITICA, produci);
  const c = cache.ottieni('k', POLITICA, produci);
  const altra = cache.ottieni('altra', POLITICA, async () => 'x');
  produzione.risolvi('v1');
  assert.deepEqual(await a, { valore: 'v1', origine: 'prodotto' });
  assert.deepEqual(await b, { valore: 'v1', origine: 'agganciato' });
  assert.deepEqual(await c, { valore: 'v1', origine: 'agganciato' });
  assert.deepEqual(await altra, { valore: 'x', origine: 'prodotto' });
  assert.deepEqual(chiamate, ['primo-piano']);
  assert.deepEqual(await cache.ottieni('k', POLITICA, produci), { valore: 'v1', origine: 'fresco' });
});

test('errori mai salvati: si propagano a tutti gli agganciati, poi si riprova', async (tt) => {
  const rejection = sorvegliaRejection(tt);
  const t = orologioFinto();
  const cache = nuovaCache(t);
  const produzione = differita<string>();
  let chiamate = 0;
  const produci = (): Promise<string> => { chiamate++; return produzione.promessa; };

  const a = cache.ottieni('k', POLITICA, produci);
  const b = cache.ottieni('k', POLITICA, produci);
  const guasto = new Error('timeout');
  produzione.rifiuta(guasto);
  await assert.rejects(a, (e) => e === guasto);
  await assert.rejects(b, (e) => e === guasto);
  assert.equal(chiamate, 1);
  assert.deepEqual(cache.dimensione, { voci: 0, byte: 0 });
  assert.equal(cache.stantioPerErrore('k', POLITICA), null);

  // la produzione fallita non resta "in volo": la richiesta dopo produce di nuovo
  assert.deepEqual(await cache.ottieni('k', POLITICA, async () => 'v1'), { valore: 'v1', origine: 'prodotto' });

  // anche un produttore che lancia in modo sincrono
  const lanciaSubito = (): Promise<string> => { throw new Error('sincrono'); };
  await assert.rejects(cache.ottieni('z', POLITICA, lanciaSubito), /sincrono/);
  assert.deepEqual(await cache.ottieni('z', POLITICA, async () => 'z1'), { valore: 'z1', origine: 'prodotto' });
  await lasciaGirare();
  assert.deepEqual(rejection, []);
});

test('errore in primo piano su voce scaduta: la voce vecchia resta per stale-if-error', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  await cache.ottieni('k', POLITICA, produttore(['v1']).produci);
  t.avanza(200_000);
  await assert.rejects(cache.ottieni('k', POLITICA, async () => { throw new Error('DB giu\''); }));
  assert.equal(cache.stantioPerErrore('k', POLITICA), 'v1');
  assert.equal(cache.dimensione.voci, 1);
});

test('stantioPerErrore: entro freschezza + staleIfError, poi null', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  assert.equal(cache.stantioPerErrore('assente', POLITICA), null);
  await cache.ottieni('k', POLITICA, produttore(['v1']).produci);
  assert.equal(cache.stantioPerErrore('k', POLITICA), 'v1');
  t.avanza(60_000 + 3_600_000 - 1);
  assert.equal(cache.stantioPerErrore('k', POLITICA), 'v1');
  t.avanza(1);
  assert.equal(cache.stantioPerErrore('k', POLITICA), null);
});

test('eviction per numero di voci: LRU, l\'accesso rende recente', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t, { maxVoci: 2 });
  await cache.ottieni('a', POLITICA, async () => 'A');
  await cache.ottieni('b', POLITICA, async () => 'B');
  assert.equal((await cache.ottieni('a', POLITICA, async () => 'A2')).origine, 'fresco');
  await cache.ottieni('c', POLITICA, async () => 'C');
  assert.equal(cache.dimensione.voci, 2);
  assert.equal(cache.stantioPerErrore('b', POLITICA), null, 'b era la meno recente');
  assert.equal(cache.stantioPerErrore('a', POLITICA), 'A');
  assert.equal(cache.stantioPerErrore('c', POLITICA), 'C');
  // anche stantioPerErrore conta come accesso: ora la meno recente e' 'a'
  await cache.ottieni('d', POLITICA, async () => 'D');
  assert.equal(cache.stantioPerErrore('a', POLITICA), null);
  assert.equal(cache.stantioPerErrore('c', POLITICA), 'C');
  assert.equal(cache.stantioPerErrore('d', POLITICA), 'D');
});

test('eviction per byte e valori troppo grandi mai salvati', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t, { maxByte: 10 });
  await cache.ottieni('a', POLITICA, async () => 'aaaa');
  await cache.ottieni('b', POLITICA, async () => 'bbbb');
  assert.deepEqual(cache.dimensione, { voci: 2, byte: 8 });
  await cache.ottieni('c', POLITICA, async () => 'cccc');
  assert.deepEqual(cache.dimensione, { voci: 2, byte: 8 });
  assert.equal(cache.stantioPerErrore('a', POLITICA), null);

  // un valore da 10 byte entra da solo, svuotando il resto
  await cache.ottieni('d', POLITICA, async () => 'dddddddddd');
  assert.deepEqual(cache.dimensione, { voci: 1, byte: 10 });

  // uno da 11 byte viene restituito ma non salvato
  const grande = await cache.ottieni('e', POLITICA, async () => 'eeeeeeeeeee');
  assert.deepEqual(grande, { valore: 'eeeeeeeeeee', origine: 'prodotto' });
  assert.deepEqual(cache.dimensione, { voci: 1, byte: 10 });
  assert.equal(cache.stantioPerErrore('e', POLITICA), null);

  // sostituire una voce ricalcola i byte; se il nuovo valore non entra, la vecchia esce
  t.avanza(200_000);
  await cache.ottieni('d', POLITICA, async () => 'dd');
  assert.deepEqual(cache.dimensione, { voci: 1, byte: 2 });
  t.avanza(200_000);
  await cache.ottieni('d', POLITICA, async () => 'd'.repeat(50));
  assert.deepEqual(cache.dimensione, { voci: 0, byte: 0 });
});

test('attendiRinfreschi: subito senza rinfreschi, altrimenti alla fine di tutti', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  await cache.attendiRinfreschi();

  await cache.ottieni('a', POLITICA, async () => 'A');
  await cache.ottieni('b', POLITICA, async () => 'B');
  t.avanza(61_000);
  const ra = differita<string>();
  const rb = differita<string>();
  await cache.ottieni('a', POLITICA, () => ra.promessa);
  await cache.ottieni('b', POLITICA, () => rb.promessa);

  let concluso = false;
  const attesa = cache.attendiRinfreschi().then(() => { concluso = true; });
  ra.risolvi('A2');
  await lasciaGirare();
  assert.equal(concluso, false, 'manca ancora il rinfresco di b');
  rb.rifiuta(new Error('b fallito'));
  await attesa;
  assert.equal(concluso, true);
  assert.equal((await cache.ottieni('a', POLITICA, async () => 'X')).valore, 'A2');
  assert.equal((await cache.ottieni('b', POLITICA, async () => 'X')).valore, 'B');
});

test('rinfresco in background non sovrascrive una voce piu\' recente prodotta in primo piano', async () => {
  const t = orologioFinto();
  const cache = nuovaCache(t);
  await cache.ottieni('k', POLITICA, async () => 'v1');
  t.avanza(100_000);
  const lento = differita<string>();
  assert.equal((await cache.ottieni('k', POLITICA, () => lento.promessa)).origine, 'swr');

  // la voce esce dalla finestra SWR mentre il rinfresco e' ancora in volo:
  // chi arriva non si aggancia al rinfresco, produce in primo piano
  t.avanza(100_000);
  assert.deepEqual(await cache.ottieni('k', POLITICA, async () => 'v3'), { valore: 'v3', origine: 'prodotto' });
  lento.risolvi('v2-vecchio');
  await cache.attendiRinfreschi();
  assert.deepEqual(await cache.ottieni('k', POLITICA, async () => 'X'), { valore: 'v3', origine: 'fresco' });
});
