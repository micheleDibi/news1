/**
 * La migrazione 14 (sospensione e revoca) porta il blocco generato da
 * `tests/stato-bando/genera-sql.ts` con le quattro righe della lista bianca che
 * hanno `migrazione: 14` in `casi.json`. Qui si controlla che il file lo porti
 * byte per byte, che il rollback tolga esattamente quelle quattro righe, che le
 * verifiche interne contino le righe giuste e che i due file stiano nelle 45
 * colonne.
 *
 * Il confronto delle due funzioni riscritte (RPC e trigger) con la 11 e la 04
 * sta in `scraper_bandi/tests/test_sospensioni_sql.py`.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  generaDeltaTransizioni,
  LARGHEZZA_MIGRAZIONI,
  MARCATORE_DELTA_FINE,
  MARCATORE_DELTA_INIZIO,
  type DatiStatoBando,
} from '../stato-bando/genera-sql.ts';

const RADICE = new URL('../../', import.meta.url);
const leggi = (percorso: string): string => readFileSync(new URL(percorso, RADICE), 'utf8');

const MIGRAZIONE = leggi('backend/sql/bando_v11_14_sospensioni.sql');
const ROLLBACK = leggi('backend/sql/bando_v11_14_sospensioni_rollback.sql');
const dati = JSON.parse(leggi('tests/stato-bando/casi.json')) as DatiStatoBando;
const delta = dati.transizioni.filter((transizione) => transizione.migrazione === 14);

/** Il testo fra le due righe intere `inizio` e `fine`, comprese. */
function blocco(testo: string, inizio: string, fine: string): string {
  const righe = testo.split('\n');
  const aperture = righe.flatMap((riga, i) => (riga === inizio ? [i] : []));
  assert.equal(aperture.length, 1, `marcatore ${inizio}: ${aperture.length} occorrenze`);
  const chiusura = righe.findIndex((riga, i) => i > aperture[0] && riga === fine);
  assert.ok(chiusura > aperture[0], `marcatore mancante: ${fine}`);
  return righe.slice(aperture[0], chiusura + 1).join('\n');
}

test('la 14 porta il delta della lista bianca byte per byte', () => {
  assert.deepEqual(
    delta.map((t) => [t.da, t.a, t.attore, t.evento]),
    [
      ['sospeso', 'chiuso', 'worker', 'chiusura'],
      ['revocato', 'aperto', 'worker', 'annullamento_revoca'],
      ['revocato', 'chiuso', 'worker', 'annullamento_revoca'],
      ['revocato', 'in apertura prossimamente', 'worker', 'annullamento_revoca'],
    ],
  );
  const inizio = `${MARCATORE_DELTA_INIZIO} 14`;
  const fine = `${MARCATORE_DELTA_FINE} 14`;
  assert.equal(blocco(MIGRAZIONE, inizio, fine), generaDeltaTransizioni(dati, 14));
});

test('nessuna riga della redazione e nessuna uscita dal revocato senza annullamento', () => {
  for (const transizione of delta) {
    assert.equal(transizione.attore, 'worker');
    if (transizione.da === 'revocato') assert.equal(transizione.evento, 'annullamento_revoca');
  }
});

test('il rollback toglie le sole quattro righe del delta, per (da, a, attore, evento)', () => {
  const cancellazioni = ROLLBACK.match(/DELETE FROM public\.bando_transizione[^;]*;/g) ?? [];
  assert.equal(cancellazioni.length, delta.length);
  delta.forEach((transizione, i) => {
    for (const condizione of [
      `da = '${transizione.da}'`,
      `a = '${transizione.a}'`,
      `attore = '${transizione.attore}'`,
      `evento = '${transizione.evento}'`,
    ]) {
      assert.ok(cancellazioni[i].includes(condizione), `${i}: ${condizione}`);
    }
  });
});

test('le verifiche contano le righe della lista bianca giuste', () => {
  const finoAlla14 = dati.transizioni.filter(
    (transizione) => transizione.migrazione === undefined || transizione.migrazione <= 14,
  ).length;
  const primaDella14 = finoAlla14 - delta.length;
  assert.equal(finoAlla14, 28);
  assert.match(MIGRAZIONE, new RegExp(`IF v_n <> ${finoAlla14} THEN`));
  assert.match(ROLLBACK, new RegExp(`IF v_n <> ${primaDella14} THEN`));
});

test('la 14 si applica dopo la 13 e lo dice', () => {
  assert.ok(MIGRAZIONE.includes('-- Ordine di applicazione: DOPO la 13'));
  assert.ok(MIGRAZIONE.includes('DOPO QUESTO FILE NON RIESEGUIRE'));
});

test('righe di al massimo 45 caratteri in migrazione e rollback', () => {
  for (const [nome, testo] of [['migrazione', MIGRAZIONE], ['rollback', ROLLBACK]] as const) {
    testo.split('\n').forEach((riga, i) => {
      assert.ok(
        [...riga].length <= LARGHEZZA_MIGRAZIONI,
        `${nome}:${i + 1} ha ${[...riga].length} caratteri`,
      );
    });
  }
});
