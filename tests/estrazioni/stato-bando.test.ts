/**
 * Stato dei bandi in tre linguaggi (piano §4).
 *
 * Questo file è il guardiano della divergenza: gli stessi casi di
 * `tests/stato-bando/casi.json` girano sul modulo TypeScript, sul gemello
 * Python (eseguito davvero, con `runpy.run_path`) e — quando la migrazione 04
 * esiste — sul blocco SQL generato, confrontato byte per byte. Lo stesso vale
 * per la sezione `certezza` (regola `stato_da_verificare`, contratto interno
 * del giro 2 §3 con §19.3), il cui blocco SQL va nella migrazione 13.
 *
 *   npm test
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  ATTORI_TRANSIZIONE,
  effectiveStatoBando,
  GIORNI_GRAZIA_PUBBLICAZIONE,
  GIORNI_GRAZIA_RAMO_A,
  GIORNI_VALIDITA_CONFERMA,
  METODI_LETTURA,
  MOTIVI_DA_VERIFICARE,
  STATI_BANDO,
  STATI_BANDO_PERSISTITI,
  STATI_LETTI,
  statoDaVerificare,
  statoEffettivo,
  todayRomeISO,
  TRANSIZIONI,
  transizioneAmmessa,
  type AttoreTransizione,
  type StatoBando,
} from '../../src/lib/stato-bando.ts';
import {
  generaBloccoCasi,
  generaBloccoCertezza,
  generaDeltaTransizioni,
  generaSeedTransizioni,
  LARGHEZZA_MIGRAZIONI,
  MARCATORE_CASI_FINE,
  MARCATORE_CASI_INIZIO,
  MARCATORE_CERTEZZA_FINE,
  MARCATORE_CERTEZZA_INIZIO,
  MARCATORE_DELTA_FINE,
  MARCATORE_DELTA_INIZIO,
  MARCATORE_TRANSIZIONI_FINE,
  MARCATORE_TRANSIZIONI_INIZIO,
  type CasoCertezza,
  type CasoStatoBando,
  type DatiCertezza,
  type DatiStatoBando,
} from '../stato-bando/genera-sql.ts';

interface CasoConImpronta extends CasoStatoBando {
  readonly sha256: string;
}

interface CasoCertezzaConImpronta extends CasoCertezza {
  readonly sha256: string;
}

interface Fixture extends DatiStatoBando {
  readonly conteggio_minimo: number;
  readonly stati: string[];
  readonly attori: string[];
  readonly casi: readonly CasoConImpronta[];
  readonly certezza: DatiCertezza & { readonly casi: readonly CasoCertezzaConImpronta[] };
}

/**
 * Serializzazione canonica di un caso, gemella di `_chiave` in
 * `scraper_bandi/tests/test_stato_bando.py`: i campi che contano uniti da
 * U+0000, con U+0001 al posto di null. `nota` non entra. Se le due copie
 * divergono, uno dei due runner non ritrova lo `sha256` del fixture.
 */
function chiave(caso: CasoConImpronta): string {
  const canonico = (valore: string | boolean | null): string => {
    if (valore === null) return '\u0001';
    if (valore === true) return 'true';
    if (valore === false) return 'false';
    return valore;
  };
  return [
    caso.id, caso.stato, caso.data_apertura, caso.apertura_verificata, caso.ora_apertura,
    caso.data_scadenza, caso.ora_scadenza, caso.adesso, caso.atteso,
  ].map(canonico).join('\u0000');
}

// Gli ingressi della regola nell'ordine della firma (contratto §3 con §19.3):
// anche l'impronta di un caso `certezza` li prende in quest'ordine.
const INGRESSI_CERTEZZA = [
  'stato', 'data_apertura', 'apertura_verificata', 'ora_apertura', 'data_scadenza',
  'ora_scadenza', 'pubblicato_at', 'previsto_entro', 'termine_indicato', 'stato_letto',
  'stato_letto_su', 'stato_letto_at', 'stato_letto_metodo', 'esaminato_attivo_at',
  'segnale_aggregatore_at', 'adesso',
] as const satisfies readonly (keyof CasoCertezza)[];

/**
 * Impronta di un caso `certezza`, gemella di `_chiave_certezza` in
 * `scraper_bandi/tests/test_stato_bando.py`: stesso schema dei casi di
 * `statoEffettivo` (U+0000 fra i campi, U+0001 per null), con id, i sedici
 * ingressi e l'atteso. `regola` e `nota` non entrano.
 */
function chiaveCertezza(caso: CasoCertezzaConImpronta): string {
  const canonico = (valore: string | boolean | null): string => {
    if (valore === null) return '\u0001';
    if (valore === true) return 'true';
    if (valore === false) return 'false';
    return valore;
  };
  return [caso.id, ...INGRESSI_CERTEZZA.map((campo) => caso[campo]), caso.atteso]
    .map(canonico).join('\u0000');
}

const dati = JSON.parse(
  readFileSync(new URL('../stato-bando/casi.json', import.meta.url), 'utf8'),
) as Fixture;

const campi = (caso: CasoStatoBando) => ({
  stato: caso.stato,
  data_apertura: caso.data_apertura,
  apertura_verificata: caso.apertura_verificata,
  ora_apertura: caso.ora_apertura,
  data_scadenza: caso.data_scadenza,
  ora_scadenza: caso.ora_scadenza,
});

// ---------------------------------------------------------------------------
// Il fixture
// ---------------------------------------------------------------------------

test('nessuno puo cancellare casi in silenzio', () => {
  assert.ok(
    dati.casi.length >= dati.conteggio_minimo,
    `${dati.casi.length} casi, minimo ${dati.conteggio_minimo}`,
  );
  assert.ok(dati.transizioni.length > 0);
});

test('nessuno puo cambiare un caso in silenzio', () => {
  for (const caso of dati.casi) {
    assert.equal(
      createHash('sha256').update(chiave(caso), 'utf8').digest('hex'),
      caso.sha256,
      `${caso.id}: il fixture e' stato modificato senza rigenerare lo sha256`,
    );
  }
  // impronte tutte diverse: e' l'intero caso a essere firmato, non l'atteso
  assert.equal(new Set(dati.casi.map((c) => c.sha256)).size, dati.casi.length);
});

test('identificatori unici', () => {
  const visti = dati.casi.map((c) => c.id);
  assert.equal(visti.length, new Set(visti).size);
});

test('il vocabolario coincide con il fixture', () => {
  assert.deepEqual([...STATI_BANDO], dati.stati);
  assert.deepEqual([...ATTORI_TRANSIZIONE], dati.attori);
});

test('la tabella delle transizioni coincide con il fixture', () => {
  assert.deepEqual(
    TRANSIZIONI.map((t) => ({
      da: t.da, a: t.a, attore: t.attore, evento: t.evento, condizione: t.condizione,
      ...(t.migrazione === undefined ? {} : { migrazione: t.migrazione }),
    })),
    dati.transizioni,
  );
  // 23 righe seminate dalla 04, una dalla 13 (contratto interno del giro 2, §4)
  assert.equal(TRANSIZIONI.length, 24);
  assert.equal(TRANSIZIONI.filter((t) => t.migrazione === undefined).length, 23);
  assert.deepEqual(
    TRANSIZIONI.filter((t) => t.migrazione !== undefined)
      .map((t) => [t.da, t.a, t.attore, t.evento, t.migrazione]),
    [['in apertura prossimamente', 'chiuso', 'worker', 'chiusura', 13]],
  );
  for (const transizione of TRANSIZIONI) {
    assert.ok(dati.stati.includes(transizione.a), transizione.a);
    assert.ok(transizione.da === null || dati.stati.includes(transizione.da));
    assert.ok(dati.attori.includes(transizione.attore), transizione.attore);
  }
});

// ---------------------------------------------------------------------------
// Macchina a stati
// ---------------------------------------------------------------------------

/** Tutte le combinazioni (da, a, attore), comprese quelle non ammesse. */
function sonde(): [StatoBando | null, StatoBando, AttoreTransizione][] {
  const elenco: [StatoBando | null, StatoBando, AttoreTransizione][] = [];
  for (const da of [null, ...STATI_BANDO] as (StatoBando | null)[]) {
    for (const a of STATI_BANDO) {
      for (const attore of ATTORI_TRANSIZIONE) elenco.push([da, a, attore]);
    }
  }
  return elenco;
}

test('transizioneAmmessa: vero per ogni riga della tabella', () => {
  for (const t of TRANSIZIONI) {
    assert.equal(transizioneAmmessa(t.da, t.a, t.attore), true, `${t.da} -> ${t.a} (${t.attore})`);
  }
});

test('transizioneAmmessa: la direzione opposta non si eredita', () => {
  const chiavi = new Set(TRANSIZIONI.map((t) => `${t.da}|${t.a}|${t.attore}`));
  for (const t of TRANSIZIONI) {
    if (t.da === null) continue;
    const opposta = `${t.a}|${t.da}|${t.attore}`;
    assert.equal(
      transizioneAmmessa(t.a, t.da, t.attore),
      chiavi.has(opposta),
      `opposta ${t.a} -> ${t.da} (${t.attore})`,
    );
  }
});

test('transizioneAmmessa: lista bianca, e il resto e\' falso', () => {
  const chiavi = new Set(TRANSIZIONI.map((t) => `${t.da}|${t.a}|${t.attore}`));
  for (const [da, a, attore] of sonde()) {
    assert.equal(
      transizioneAmmessa(da, a, attore),
      chiavi.has(`${da}|${a}|${attore}`),
      `${da} -> ${a} (${attore})`,
    );
  }
});

test('invarianti della macchina a stati (§4)', () => {
  // revocato e' terminale
  assert.equal(TRANSIZIONI.some((t) => t.da === 'revocato'), false);
  // nessuno chiude un sospeso d'ufficio (A3)
  assert.equal(TRANSIZIONI.some((t) => t.da === 'sospeso' && t.a === 'chiuso'), false);
  // il cron non tocca mai sospeso ne revocato
  for (const t of TRANSIZIONI.filter((r) => r.attore === 'cron')) {
    assert.equal(t.da === 'sospeso' || t.da === 'revocato', false);
    assert.equal(t.a === 'sospeso' || t.a === 'revocato', false);
  }
  // la pipeline scrive solo i tre stati storici (il CHECK a DB ne ha tre) e
  // solo alla creazione: le righe pubblicate non le tocca mai, quindi in
  // `bando_transizione` non deve avere nessun passaggio fra stati
  for (const t of TRANSIZIONI.filter((r) => r.attore === 'pipeline')) {
    assert.equal(t.a === 'sospeso' || t.a === 'revocato', false);
    assert.equal(t.da, null, `la pipeline non passa da ${t.da} a ${t.a}`);
  }
  // la redazione non ha scritture automatiche sullo stato
  assert.equal(TRANSIZIONI.some((t) => t.attore === 'redazione'), false);
  // un chiuso riapre SOLO con un evento verificato del monitor (§4: «unico modo
  // per riaprire», §13.3: «un chiuso persistito non riapre alla lettura»)
  const riaperture = TRANSIZIONI.filter((r) => r.da === 'chiuso' && r.a === 'aperto');
  assert.ok(riaperture.length > 0);
  for (const t of riaperture) assert.equal(t.attore, 'worker', `${t.evento}: ${t.attore}`);
  assert.equal(TRANSIZIONI.some((t) => t.attore === 'cron' && t.a === 'aperto' && t.da !== 'in apertura prossimamente'), false);
  // il worker porta un «in apertura» a chiuso SOLO con l'evento 'chiusura'
  // (contratto interno del giro 2, §4: etichetta strutturata, doppia lettura)
  const chiusureDaApertura = TRANSIZIONI.filter(
    (t) => t.attore === 'worker' && t.da === 'in apertura prossimamente' && t.a === 'chiuso',
  );
  assert.ok(chiusureDaApertura.length > 0);
  for (const t of chiusureDaApertura) assert.equal(t.evento, 'chiusura', t.evento);
});

// ---------------------------------------------------------------------------
// statoEffettivo
// ---------------------------------------------------------------------------

test('statoEffettivo: tabella dei casi condivisa', () => {
  for (const caso of dati.casi) {
    assert.equal(
      statoEffettivo(campi(caso), new Date(caso.adesso)),
      caso.atteso,
      `${caso.id}: ${caso.nota}`,
    );
  }
});

test('statoEffettivo: senza "adesso" usa l\'istante corrente', () => {
  assert.equal(statoEffettivo({ stato: 'aperto', data_scadenza: '2000-01-01' }), 'chiuso');
  assert.equal(statoEffettivo({ stato: 'aperto', data_scadenza: '2999-01-01' }), 'aperto');
  assert.equal(statoEffettivo({}), null);
});

test('statoEffettivo: accetta sia data_apertura_verificata sia il nome breve', () => {
  // Una riga letta dalla vista porta `data_apertura_verificata` (§13.0); il
  // fixture usa il nome breve. Le due grafie devono dare lo stesso risultato.
  const adesso = new Date('2026-09-22T12:00:00+02:00');
  const base = { stato: 'in apertura prossimamente', data_apertura: '2026-09-01' };
  assert.equal(statoEffettivo({ ...base, data_apertura_verificata: true }, adesso), 'aperto');
  assert.equal(statoEffettivo({ ...base, apertura_verificata: true }, adesso), 'aperto');
  assert.equal(statoEffettivo({ ...base }, adesso), 'in apertura prossimamente');
  assert.equal(
    statoEffettivo({ ...base, data_apertura_verificata: false, apertura_verificata: true }, adesso),
    'in apertura prossimamente',
  );
});

test('statoEffettivo: campi malformati non inventano stati', () => {
  const adesso = new Date('2026-09-22T12:00:00+02:00');
  assert.equal(statoEffettivo({ stato: 'aperto', data_scadenza: 'boh' }, adesso), 'aperto');
  assert.equal(statoEffettivo({ stato: 'aperto', data_scadenza: '2026-09-22', ora_scadenza: 'boh' }, adesso), 'aperto');
  assert.equal(statoEffettivo({ stato: null, data_scadenza: null }, adesso), null);
});

// ---------------------------------------------------------------------------
// statoDaVerificare (sezione `certezza`)
// ---------------------------------------------------------------------------

const certezza = dati.certezza;

const REGOLE = [
  'R0', 'I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I6bis', 'I7',
  'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8',
];

test('certezza: nessuno puo cancellare o cambiare casi in silenzio', () => {
  assert.equal(certezza.versione, 2);
  assert.ok(certezza.casi.length >= 80, `${certezza.casi.length} casi, il contratto ne chiede almeno 80`);
  assert.ok(certezza.casi.length >= certezza.conteggio_minimo);
  for (const caso of certezza.casi) {
    assert.equal(
      createHash('sha256').update(chiaveCertezza(caso), 'utf8').digest('hex'),
      caso.sha256,
      `${caso.id}: il fixture e' stato modificato senza rigenerare lo sha256`,
    );
  }
  assert.equal(new Set(certezza.casi.map((c) => c.sha256)).size, certezza.casi.length);
  const visti = certezza.casi.map((c) => c.id);
  assert.equal(visti.length, new Set(visti).size);
});

test('certezza: il vocabolario e i parametri coincidono con il fixture', () => {
  assert.deepEqual([...MOTIVI_DA_VERIFICARE], certezza.motivi);
  assert.deepEqual([...STATI_LETTI], certezza.stati_letti);
  assert.deepEqual([...METODI_LETTURA], certezza.metodi);
  assert.deepEqual(
    {
      giorni_grazia_pubblicazione: GIORNI_GRAZIA_PUBBLICAZIONE,
      giorni_validita_conferma: GIORNI_VALIDITA_CONFERMA,
      giorni_grazia_ramo_a: GIORNI_GRAZIA_RAMO_A,
    },
    certezza.parametri,
  );
  assert.deepEqual(certezza.parametri, {
    giorni_grazia_pubblicazione: 3, giorni_validita_conferma: 30, giorni_grazia_ramo_a: 7,
  });
});

test('certezza: ogni regola e ogni motivo hanno almeno un caso', () => {
  for (const caso of certezza.casi) {
    assert.ok(REGOLE.includes(caso.regola), `${caso.id}: regola ${caso.regola}`);
    assert.ok(caso.atteso === null || certezza.motivi.includes(caso.atteso), `${caso.id}: ${caso.atteso}`);
  }
  for (const regola of REGOLE) {
    assert.ok(certezza.casi.some((c) => c.regola === regola), `nessun caso per ${regola}`);
  }
  for (const motivo of certezza.motivi) {
    assert.ok(certezza.casi.some((c) => c.atteso === motivo), `nessun caso con ${motivo}`);
  }
  // le regole che rispondono null non danno mai un motivo, e viceversa
  const nulle = new Set(['R0', 'I1', 'I5', 'I6', 'I6bis', 'A2', 'A4', 'A6', 'A7']);
  for (const caso of certezza.casi) {
    assert.equal(caso.atteso === null, nulle.has(caso.regola), `${caso.id} (${caso.regola})`);
  }
});

test('statoDaVerificare: tabella dei casi condivisa', () => {
  for (const caso of certezza.casi) {
    assert.equal(
      statoDaVerificare(caso, new Date(caso.adesso)),
      caso.atteso,
      `${caso.id} (${caso.regola}): ${caso.nota}`,
    );
  }
});

test('statoDaVerificare: accetta anche data_apertura_verificata', () => {
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  const base = {
    stato: 'in apertura prossimamente',
    data_apertura: '2026-10-15',
    pubblicato_at: '2026-09-01T10:00:00+00:00',
    esaminato_attivo_at: '2026-09-29T08:00:00+00:00',
  };
  assert.equal(statoDaVerificare({ ...base, data_apertura_verificata: true }, adesso), null);
  assert.equal(statoDaVerificare({ ...base, apertura_verificata: true }, adesso), null);
  assert.equal(statoDaVerificare(base, adesso), 'senza_conferma');
});

test('statoDaVerificare: i campi assenti valgono NULL (fonte tabella)', () => {
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  // senza esame in attivo (ordine definitivo di §19.3) l'unico motivo
  // possibile e' data_apertura_passata: previsione e termine passati tacciono
  assert.equal(statoDaVerificare({ stato: 'aperto', pubblicato_at: '2026-09-01' }, adesso), null);
  assert.equal(statoDaVerificare({ stato: 'aperto', termine_indicato: '2026-09-01' }, adesso), null);
  assert.equal(statoDaVerificare({ stato: 'in apertura prossimamente' }, adesso), null);
  assert.equal(
    statoDaVerificare({ stato: 'in apertura prossimamente', data_apertura: '2026-09-01' }, adesso),
    'data_apertura_passata',
  );
  assert.equal(
    statoDaVerificare({ stato: 'in apertura prossimamente', previsto_entro: '2026-09-01' }, adesso),
    null,
  );
  assert.equal(statoDaVerificare({}, adesso), null);
});

test('statoDaVerificare: timestamp come li restituisce PostgREST', () => {
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  const conferma = (stato_letto_at: string) => statoDaVerificare({
    stato: 'aperto',
    stato_letto: 'aperto',
    stato_letto_su: 'aperto',
    stato_letto_metodo: 'estrattore',
    stato_letto_at,
    esaminato_attivo_at: '2026-09-29T08:00:00+00:00',
    pubblicato_at: '2026-09-01T10:00:00+00:00',
  }, adesso);
  assert.equal(conferma('2026-09-25T08:00:00.12345+00:00'), null);
  assert.equal(conferma('2026-09-25T08:00:00Z'), null);
  assert.equal(conferma('2026-09-25 08:00:00+00'), null);
  assert.equal(conferma('2026-09-25T08:00:00+0000'), null);
  assert.equal(conferma('2026-09-25'), null);
  // malformato = NULL: la conferma non vale e resta senza_conferma
  assert.equal(conferma('boh'), 'senza_conferma');
  assert.equal(conferma('25/09/2026'), 'senza_conferma');
  assert.equal(conferma('2026-09-25T25:00:00Z'), 'senza_conferma');
});

test('statoDaVerificare: un timestamp senza fuso vale UTC, mai l\'ora locale', () => {
  // TZ=Asia/Kathmandu (+05:45): letto come ora locale, 30/08 23:50 diventerebbe
  // 30/08 20:05 a Roma, ancora il 30; letto come UTC e' il 31/08 01:50 a Roma,
  // cioe' 30 giorni prima del 30/09: la conferma vale.
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  const campi = {
    stato: 'aperto',
    stato_letto: 'aperto',
    stato_letto_su: 'aperto',
    stato_letto_metodo: 'estrattore',
    esaminato_attivo_at: '2026-09-29T08:00:00+00:00',
    pubblicato_at: '2026-09-01T10:00:00+00:00',
  };
  assert.equal(statoDaVerificare({ ...campi, stato_letto_at: '2026-08-30T23:50:00' }, adesso), null);
  assert.equal(statoDaVerificare({ ...campi, stato_letto_at: '2026-08-30T21:50:00' }, adesso), 'senza_conferma');
});

test('statoDaVerificare: senza "adesso" usa l\'istante corrente', () => {
  assert.equal(
    statoDaVerificare({ stato: 'aperto', termine_indicato: '2000-01-01', esaminato_attivo_at: '2000-01-02T00:00:00Z' }),
    'termine_passato',
  );
  assert.equal(statoDaVerificare({ stato: 'aperto', data_scadenza: '2999-01-01' }), null);
});

// ---------------------------------------------------------------------------
// Firma storica
// ---------------------------------------------------------------------------

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

test('effectiveStatoBando: sospeso e revocato non li chiude la scadenza', () => {
  // Regole 1 e 2 di §13.3 e garanzia A3: un bando si sospende quasi sempre a
  // ridosso della scadenza, e «Chiuso» sarebbe la risposta sbagliata.
  const oggi = '2026-09-21';
  assert.equal(effectiveStatoBando('sospeso', '2026-01-01', oggi), 'sospeso');
  assert.equal(effectiveStatoBando('sospeso', null, oggi), 'sospeso');
  assert.equal(effectiveStatoBando('revocato', '2026-01-01', oggi), 'revocato');
  assert.equal(effectiveStatoBando('revocato', '2030-01-01', oggi), 'revocato');
});

test('effectiveStatoBando: sui tre stati persistiti risponde come statoEffettivo', () => {
  // Retro-compatibilita' dei chiamanti storici (CardBando, scheda, corpus,
  // liste, API v1): sulla colonna a tre valori le due firme coincidono.
  const oggi = '2026-09-21';
  const mezzogiorno = new Date(`${oggi}T12:00:00+02:00`);
  for (const stato of STATI_BANDO_PERSISTITI) {
    for (const scadenza of [null, '2026-09-20', '2026-09-21', '2030-01-01']) {
      assert.equal(
        effectiveStatoBando(stato, scadenza, oggi),
        statoEffettivo({ stato, data_scadenza: scadenza }, mezzogiorno),
        `${stato} / ${scadenza}`,
      );
    }
  }
});

test('STATI_BANDO_PERSISTITI: i tre valori del CHECK, per validare gli input', () => {
  assert.deepEqual([...STATI_BANDO_PERSISTITI], ['aperto', 'chiuso', 'in apertura prossimamente']);
  for (const stato of STATI_BANDO_PERSISTITI) assert.ok(STATI_BANDO.includes(stato));
  assert.equal((STATI_BANDO_PERSISTITI as readonly string[]).includes('sospeso'), false);
  assert.equal((STATI_BANDO_PERSISTITI as readonly string[]).includes('revocato'), false);
});

test('STATI_BANDO: cinque valori, i tre storici per primi', () => {
  assert.deepEqual(
    [...STATI_BANDO],
    ['aperto', 'chiuso', 'in apertura prossimamente', 'sospeso', 'revocato'],
  );
});

// ---------------------------------------------------------------------------
// Il gemello Python
// ---------------------------------------------------------------------------

// Esegue il MODULO (non una singola funzione estratta con ast): stato_bando.py
// non ha import interni proprio per restare caricabile cosi'.
const SCRIPT_PYTHON = `
import json, runpy, sys
from datetime import datetime

spazio = runpy.run_path(sys.argv[1])
ingresso = json.loads(sys.stdin.read())
casi = [
    spazio["stato_effettivo"](
        c["stato"], c["data_apertura"], c["apertura_verificata"], c["ora_apertura"],
        c["data_scadenza"], c["ora_scadenza"], datetime.fromisoformat(c["adesso"]),
    )
    for c in ingresso["casi"]
]
ammesse = [spazio["transizione_ammessa"](s[0], s[1], s[2]) for s in ingresso["sonde"]]
# I timestamp arrivano come testo, come da PostgREST; solo adesso e' un datetime.
certezza = [
    spazio["stato_da_verificare"](
        *[c[campo] for campo in ingresso["ingressi"][:-1]],
        datetime.fromisoformat(c["adesso"]),
    )
    for c in ingresso["certezza"]
]
print(json.dumps({
    "stati": list(spazio["STATI_BANDO"]),
    "persistiti": list(spazio["STATI_BANDO_PERSISTITI"]),
    "attori": list(spazio["ATTORI_TRANSIZIONE"]),
    "transizioni": [dict(t) for t in spazio["TRANSIZIONI"]],
    "casi": casi,
    "ammesse": ammesse,
    "motivi": list(spazio["MOTIVI_DA_VERIFICARE"]),
    "stati_letti": list(spazio["STATI_LETTI"]),
    "metodi": list(spazio["METODI_LETTURA"]),
    "parametri": {
        "giorni_grazia_pubblicazione": spazio["GIORNI_GRAZIA_PUBBLICAZIONE"],
        "giorni_validita_conferma": spazio["GIORNI_VALIDITA_CONFERMA"],
        "giorni_grazia_ramo_a": spazio["GIORNI_GRAZIA_RAMO_A"],
    },
    "certezza": certezza,
}))
`;

test('parita\' con il gemello Python', (t) => {
  const interprete = fileURLToPath(new URL('../../scraper_bandi/.venv/bin/python', import.meta.url));
  const modulo = fileURLToPath(new URL('../../scraper_bandi/app/stato_bando.py', import.meta.url));
  const elenco = sonde();
  let uscita: string;
  try {
    uscita = execFileSync(interprete, ['-I', '-B', '-c', SCRIPT_PYTHON, modulo], {
      input: JSON.stringify({
        casi: dati.casi, sonde: elenco, certezza: certezza.casi, ingressi: INGRESSI_CERTEZZA,
      }),
      timeout: 30_000,
      maxBuffer: 16 * 1024 * 1024,
      encoding: 'utf8',
    });
  } catch (errore) {
    if ((errore as NodeJS.ErrnoException).code === 'ENOENT') {
      t.skip(`interprete non disponibile: ${interprete}`);
      return;
    }
    throw errore;
  }
  const python = JSON.parse(uscita) as {
    stati: string[];
    persistiti: string[];
    attori: string[];
    transizioni: unknown[];
    casi: (string | null)[];
    ammesse: boolean[];
    motivi: string[];
    stati_letti: string[];
    metodi: string[];
    parametri: unknown;
    certezza: (string | null)[];
  };
  assert.deepEqual(python.stati, [...STATI_BANDO]);
  assert.deepEqual(python.persistiti, [...STATI_BANDO_PERSISTITI]);
  assert.deepEqual(python.attori, [...ATTORI_TRANSIZIONE]);
  assert.deepEqual(python.transizioni, dati.transizioni);
  assert.equal(python.casi.length, dati.casi.length);
  dati.casi.forEach((caso, i) => {
    assert.equal(python.casi[i], caso.atteso, `${caso.id}: ${caso.nota}`);
    assert.equal(python.casi[i], statoEffettivo(campi(caso), new Date(caso.adesso)), caso.id);
  });
  assert.equal(python.ammesse.length, elenco.length);
  elenco.forEach(([da, a, attore], i) => {
    assert.equal(python.ammesse[i], transizioneAmmessa(da, a, attore), `${da} -> ${a} (${attore})`);
  });
  assert.deepEqual(python.motivi, [...MOTIVI_DA_VERIFICARE]);
  assert.deepEqual(python.stati_letti, [...STATI_LETTI]);
  assert.deepEqual(python.metodi, [...METODI_LETTURA]);
  assert.deepEqual(python.parametri, certezza.parametri);
  assert.equal(python.certezza.length, certezza.casi.length);
  certezza.casi.forEach((caso, i) => {
    assert.equal(python.certezza[i], caso.atteso, `${caso.id} (${caso.regola}): ${caso.nota}`);
    assert.equal(python.certezza[i], statoDaVerificare(caso, new Date(caso.adesso)), caso.id);
  });
});

// ---------------------------------------------------------------------------
// Il gemello SQL
// ---------------------------------------------------------------------------

function estrai(testo: string, inizio: string, fine: string): string {
  const apertura = testo.indexOf(inizio);
  const chiusura = testo.indexOf(fine);
  assert.ok(apertura >= 0, `marcatore mancante: ${inizio}`);
  assert.ok(chiusura > apertura, `marcatore mancante: ${fine}`);
  return testo.slice(apertura, chiusura + fine.length);
}

test('i blocchi generati sono deterministici e ben formati', () => {
  const blocco = generaBloccoCasi(dati);
  assert.equal(blocco, generaBloccoCasi(dati));
  assert.ok(blocco.startsWith(MARCATORE_CASI_INIZIO));
  assert.ok(blocco.endsWith(MARCATORE_CASI_FINE));
  for (const caso of dati.casi) assert.ok(blocco.includes(`'${caso.id}'`), caso.id);

  const seed = generaSeedTransizioni(dati);
  assert.equal(seed, generaSeedTransizioni(dati));
  assert.ok(seed.startsWith(MARCATORE_TRANSIZIONI_INIZIO));
  assert.ok(seed.endsWith(MARCATORE_TRANSIZIONI_FINE));
  assert.ok(seed.includes('on conflict do nothing;'));
  // la 04 semina solo le righe senza `migrazione`: la riga 24 arriva con la 13
  assert.equal(
    seed.split('\n').filter((r) => r.startsWith('  (')).length,
    dati.transizioni.filter((t) => t.migrazione === undefined).length,
  );
  assert.equal(seed.includes('doppia lettura strutturata'), false);
});

/** Righe oltre la larghezza delle migrazioni nuove. */
function troppoLunghe(blocco: string): string[] {
  return blocco.split('\n').filter((riga) => riga.length > LARGHEZZA_MIGRAZIONI);
}

test('blocco CERTEZZA: deterministico, completo, righe di al massimo 45 caratteri', () => {
  const blocco = generaBloccoCertezza(certezza);
  assert.equal(blocco, generaBloccoCertezza(certezza));
  assert.equal(LARGHEZZA_MIGRAZIONI, 45);
  assert.ok(blocco.startsWith(`${MARCATORE_CERTEZZA_INIZIO} v2\n`));
  assert.ok(blocco.endsWith(`\n${MARCATORE_CERTEZZA_FINE} v2`));
  assert.deepEqual(troppoLunghe(blocco), []);
  for (const caso of certezza.casi) assert.ok(blocco.includes(`('${caso.id}',`), caso.id);
  // una riga di values per caso, e ogni ingresso arriva alla funzione con il
  // suo tipo, nell'ordine della firma
  assert.equal(blocco.split('\n').filter((r) => r.startsWith('    (')).length, certezza.casi.length);
  const argomenti = blocco.split('\n')
    .filter((r) => /^ {6}c\.\w+::\w+,?$/.test(r))
    .map((r) => r.trim().replace(/,$/, ''));
  assert.deepEqual(argomenti, [
    'c.stato::text', 'c.data_apertura::date', 'c.apertura_verificata::boolean',
    'c.ora_apertura::time', 'c.data_scadenza::date', 'c.ora_scadenza::time',
    'c.pubblicato_at::timestamptz', 'c.previsto_entro::date', 'c.termine_indicato::date',
    'c.stato_letto::text', 'c.stato_letto_su::text', 'c.stato_letto_at::timestamptz',
    'c.stato_letto_metodo::text', 'c.esaminato_attivo_at::timestamptz',
    'c.segnale_aggregatore_at::timestamptz', 'c.adesso::timestamptz',
  ]);
  assert.ok(blocco.includes('public.bando_stato_da_verificare('));
  assert.ok(blocco.includes('where e.ottenuto is distinct from e.atteso'));
  // i valori di ogni caso, in ordine: id, i sedici ingressi, l'atteso
  const primo = certezza.casi[0];
  const valori = [primo.id, ...INGRESSI_CERTEZZA.map((campo) => primo[campo]), primo.atteso]
    .map((v) => (v === null ? 'NULL' : typeof v === 'boolean' ? String(v) : `'${v}'`));
  const righePrimo = blocco.split('\n');
  const inizio = righePrimo.findIndex((r) => r.startsWith(`    ('${primo.id}',`));
  const fine = righePrimo.findIndex((r, i) => i > inizio && r.startsWith('    ('));
  assert.equal(
    righePrimo.slice(inizio, fine).map((r) => r.trim()).join(' '),
    `(${valori.join(', ')}),`,
  );
});

test('delta 13: solo la riga 24, condizione intatta, righe di al massimo 45 caratteri', () => {
  const blocco = generaDeltaTransizioni(dati, 13);
  assert.equal(blocco, generaDeltaTransizioni(dati, 13));
  assert.ok(blocco.startsWith(`${MARCATORE_DELTA_INIZIO} 13\n`));
  assert.ok(blocco.endsWith(`\n${MARCATORE_DELTA_FINE} 13`));
  assert.deepEqual(troppoLunghe(blocco), []);
  const riga = dati.transizioni.find((t) => t.migrazione === 13);
  assert.ok(riga);
  assert.ok(blocco.includes(
    "('in apertura prossimamente'::text,\n   'chiuso'::text, 'worker'::text,\n   'chiusura'::text,",
  ));
  // i pezzi concatenati con || ricompongono la condizione del fixture
  const ricomposta = blocco.replace(/'\n {4}\|\| '/g, '');
  assert.ok(ricomposta.includes(`'${riga.condizione}')`), ricomposta);
  assert.ok(blocco.includes('where not exists ('));
  assert.ok(blocco.includes('on conflict do nothing;'));
  // nessuna riga della 04 nel delta
  for (const t of dati.transizioni.filter((r) => r.migrazione === undefined)) {
    assert.equal(blocco.includes(t.condizione.slice(0, 30)), false, t.condizione);
  }
  assert.throws(() => generaDeltaTransizioni(dati, 99), /nessuna transizione/);
});

test('delta: una parola piu larga della riga si spezza senza perdere caratteri', () => {
  const lunga = `${'x'.repeat(80)} fine`;
  const finto: DatiStatoBando = {
    versione: 1,
    transizioni: [
      { da: null, a: 'aperto', attore: 'cron', evento: 'x', condizione: "l'ente", migrazione: 14 },
      { da: 'aperto', a: 'chiuso', attore: 'cron', evento: 'y', condizione: lunga, migrazione: 14 },
    ],
    casi: [],
  };
  const blocco = generaDeltaTransizioni(finto, 14);
  assert.deepEqual(troppoLunghe(blocco), []);
  assert.ok(blocco.includes("'l''ente'),"));
  assert.ok(blocco.replace(/'\n {4}\|\| '/g, '').includes(`'${lunga}')`));
  // il cast ::text solo sulla prima riga, come nel seed della 04
  assert.ok(blocco.includes('(NULL::text,'));
  assert.ok(blocco.includes("('aperto', 'chiuso', 'cron', 'y',"));
});

test('gli apici dei testi non rompono l\'SQL generato', () => {
  const finto: DatiStatoBando = {
    versione: 99,
    transizioni: [{ da: null, a: 'aperto', attore: 'cron', evento: 'x', condizione: "l'ente" }],
    casi: [{ ...dati.casi[0], id: "l'id", nota: 'finto' }],
  };
  assert.ok(generaSeedTransizioni(finto).includes("'l''ente'"));
  assert.ok(generaBloccoCasi(finto).includes("'l''id'"));
  const certezzaFinta: DatiCertezza = {
    ...certezza,
    casi: [{ ...certezza.casi[0], id: "l'id", stato_letto: "l'etichetta" }],
  };
  const blocco = generaBloccoCertezza(certezzaFinta);
  assert.ok(blocco.includes("('l''id',"));
  assert.ok(blocco.includes("'l''etichetta'"));
});

test('i blocchi della migrazione 04 coincidono byte per byte', (t) => {
  const percorso = fileURLToPath(
    new URL('../../backend/sql/bando_v11_04_transizioni.sql', import.meta.url),
  );
  if (!existsSync(percorso)) {
    t.skip('backend/sql/bando_v11_04_transizioni.sql non esiste ancora');
    return;
  }
  const sql = readFileSync(percorso, 'utf8');
  assert.equal(estrai(sql, MARCATORE_CASI_INIZIO, MARCATORE_CASI_FINE), generaBloccoCasi(dati));
  assert.equal(
    estrai(sql, MARCATORE_TRANSIZIONI_INIZIO, MARCATORE_TRANSIZIONI_FINE),
    generaSeedTransizioni(dati),
  );
});
