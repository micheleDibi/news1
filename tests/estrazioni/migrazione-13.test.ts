/**
 * La migrazione 13 porta due blocchi generati da `tests/stato-bando/genera-sql.ts`:
 * i casi della regola `stato_da_verificare` (CERTEZZA) e la riga 24 della lista
 * bianca (TRANSIZIONI delta 13). Qui si controlla che il file li porti byte per
 * byte, che il rollback tolga esattamente quella riga e niente altro, e che la
 * vista finisca con le cinque colonne nuove nell'ordine del contratto.
 *
 * Se un caso cambia in `casi.json` questo test fallisce finché qualcuno non
 * rigenera il blocco nella 13: la migrazione non può restare indietro in
 * silenzio rispetto ai due gemelli.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  generaBloccoCertezza,
  generaDeltaTransizioni,
  LARGHEZZA_MIGRAZIONI,
  MARCATORE_CERTEZZA_FINE,
  MARCATORE_CERTEZZA_INIZIO,
  MARCATORE_DELTA_FINE,
  MARCATORE_DELTA_INIZIO,
  type DatiStatoBando,
} from '../stato-bando/genera-sql.ts';

const RADICE = new URL('../../', import.meta.url);
const leggi = (percorso: string): string => readFileSync(new URL(percorso, RADICE), 'utf8');

const MIGRAZIONE = leggi('backend/sql/bando_v11_13_stato_da_verificare.sql');
const ROLLBACK = leggi('backend/sql/bando_v11_13_stato_da_verificare_rollback.sql');
const dati = JSON.parse(leggi('tests/stato-bando/casi.json')) as DatiStatoBando;
const certezza = dati.certezza;
const delta = dati.transizioni.filter((transizione) => transizione.migrazione === 13);

/**
 * Il testo fra la riga `inizio` e la riga `fine`, comprese, cercate come righe
 * INTERE: `-- >>> TRANSIZIONI` (04) è un prefisso anche del delta.
 */
function blocco(testo: string, inizio: string, fine: string): string {
  const righe = testo.split('\n');
  const aperture = righe.flatMap((riga, i) => (riga === inizio ? [i] : []));
  assert.equal(aperture.length, 1, `marcatore ${inizio}: ${aperture.length} occorrenze`);
  const chiusura = righe.findIndex((riga, i) => i > aperture[0] && riga === fine);
  assert.ok(chiusura > aperture[0], `marcatore mancante: ${fine}`);
  return righe.slice(aperture[0], chiusura + 1).join('\n');
}

test('la 13 porta il blocco CERTEZZA di genera-sql byte per byte', () => {
  assert.ok(certezza, 'casi.json senza la sezione certezza');
  const inizio = `${MARCATORE_CERTEZZA_INIZIO} v${certezza.versione}`;
  const fine = `${MARCATORE_CERTEZZA_FINE} v${certezza.versione}`;
  assert.equal(blocco(MIGRAZIONE, inizio, fine), generaBloccoCertezza(certezza));
  // la riga prima lo trasforma in una vista temporanea che la verifica legge
  assert.ok(MIGRAZIONE.includes(`CREATE TEMP VIEW _m13_certezza AS\n${inizio}\n`));
  assert.ok(MIGRAZIONE.includes('FROM pg_temp._m13_certezza k;'));
});

test('la 13 porta il delta della lista bianca byte per byte', () => {
  assert.equal(delta.length, 1, 'la 13 porta una sola riga nuova');
  const inizio = `${MARCATORE_DELTA_INIZIO} 13`;
  const fine = `${MARCATORE_DELTA_FINE} 13`;
  assert.equal(blocco(MIGRAZIONE, inizio, fine), generaDeltaTransizioni(dati, 13));
});

test('il rollback toglie la sola riga del delta, per (da, a, attore, evento)', () => {
  const cancellazioni = ROLLBACK.match(/DELETE FROM public\.bando_transizione[^;]*;/g) ?? [];
  assert.equal(cancellazioni.length, 1);
  for (const transizione of delta) {
    const condizioni = [
      `da = '${transizione.da}'`,
      `a = '${transizione.a}'`,
      `attore = '${transizione.attore}'`,
      `evento = '${transizione.evento}'`,
    ];
    for (const condizione of condizioni) {
      assert.ok(cancellazioni[0].includes(condizione), condizione);
    }
  }
});

test('le verifiche contano le righe della lista bianca giuste', () => {
  // Le righe che la lista bianca ha DOPO la 13: il seed della 04 e il delta
  // della 13. Quelle delle migrazioni successive (la 14) non le conta: la V2
  // della 13 resta a 24 e, dopo la 14, la 13 non si riesegue.
  const tutte = dati.transizioni.filter(
    (transizione) => transizione.migrazione === undefined || transizione.migrazione <= 13,
  ).length;
  const senzaDelta = dati.transizioni.filter((transizione) => transizione.migrazione === undefined).length;
  assert.equal(tutte, senzaDelta + delta.length);
  assert.match(MIGRAZIONE, new RegExp(`IF v_n <> ${tutte} THEN`));
  assert.match(ROLLBACK, new RegExp(`IF v_n <> ${senzaDelta} THEN`));
});

test('la vista finisce con le cinque colonne nuove, nell\'ordine del contratto', () => {
  const inizio = MIGRAZIONE.indexOf('CREATE OR REPLACE VIEW public.bando_pubblico');
  const fine = MIGRAZIONE.indexOf('\nFROM public.bando b\nWHERE b.pubblicato;', inizio);
  assert.ok(inizio >= 0 && fine > inizio, 'vista non trovata nella 13');
  const corpo = MIGRAZIONE.slice(inizio, fine).replace(/--[^\n]*/g, '');
  // le colonne in uscita: `AS nome` a fine riga, oppure `b.nome` da sola
  // sulla riga al primo livello (due spazi di rientro)
  const colonne = [...corpo.matchAll(/^(?: {2}b\.([a-z_]+),?| .*\bAS ([a-z_]+),?)$/gm)]
    .map((m) => m[1] ?? m[2])
    .filter((nome) => nome !== 'uno');
  assert.equal(colonne.length, 49);
  assert.deepEqual(colonne.slice(-5), [
    'stato_da_verificare', 'stato_letto', 'stato_letto_at', 'termine_indicato',
    'termine_indicato_fonte',
  ]);
});

test('righe di al massimo 45 caratteri nella 13 e nel suo rollback', () => {
  for (const [nome, testo] of [['13', MIGRAZIONE], ['rollback 13', ROLLBACK]] as const) {
    const lunghe = testo.split('\n')
      .map((riga, i) => ({ riga, numero: i + 1 }))
      .filter(({ riga }) => riga.length > LARGHEZZA_MIGRAZIONI);
    assert.deepEqual(lunghe, [], `${nome}: righe oltre ${LARGHEZZA_MIGRAZIONI} caratteri`);
  }
});
