/**
 * Stato dei bandi in tre linguaggi (piano §4).
 *
 * Questo file è il guardiano della divergenza: gli stessi casi di
 * `tests/stato-bando/casi.json` girano sul modulo TypeScript, sul gemello
 * Python (eseguito davvero, con `runpy.run_path`) e — quando la migrazione 04
 * esiste — sul blocco SQL generato, confrontato byte per byte.
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
  STATI_BANDO,
  STATI_BANDO_PERSISTITI,
  statoEffettivo,
  todayRomeISO,
  TRANSIZIONI,
  transizioneAmmessa,
  type AttoreTransizione,
  type StatoBando,
} from '../../src/lib/stato-bando.ts';
import {
  generaBloccoCasi,
  generaSeedTransizioni,
  MARCATORE_CASI_FINE,
  MARCATORE_CASI_INIZIO,
  MARCATORE_TRANSIZIONI_FINE,
  MARCATORE_TRANSIZIONI_INIZIO,
  type CasoStatoBando,
  type DatiStatoBando,
} from '../stato-bando/genera-sql.ts';

interface CasoConImpronta extends CasoStatoBando {
  readonly sha256: string;
}

interface Fixture extends DatiStatoBando {
  readonly conteggio_minimo: number;
  readonly stati: string[];
  readonly attori: string[];
  readonly casi: readonly CasoConImpronta[];
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
    })),
    dati.transizioni,
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
print(json.dumps({
    "stati": list(spazio["STATI_BANDO"]),
    "persistiti": list(spazio["STATI_BANDO_PERSISTITI"]),
    "attori": list(spazio["ATTORI_TRANSIZIONE"]),
    "transizioni": [dict(t) for t in spazio["TRANSIZIONI"]],
    "casi": casi,
    "ammesse": ammesse,
}))
`;

test('parita\' con il gemello Python', (t) => {
  const interprete = fileURLToPath(new URL('../../scraper_bandi/.venv/bin/python', import.meta.url));
  const modulo = fileURLToPath(new URL('../../scraper_bandi/app/stato_bando.py', import.meta.url));
  const elenco = sonde();
  let uscita: string;
  try {
    uscita = execFileSync(interprete, ['-I', '-B', '-c', SCRIPT_PYTHON, modulo], {
      input: JSON.stringify({ casi: dati.casi, sonde: elenco }),
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
  assert.equal(seed.split('\n').filter((r) => r.startsWith('  (')).length, dati.transizioni.length);
});

test('gli apici dei testi non rompono l\'SQL generato', () => {
  const finto: DatiStatoBando = {
    versione: 99,
    transizioni: [{ da: null, a: 'aperto', attore: 'cron', evento: 'x', condizione: "l'ente" }],
    casi: [{ ...dati.casi[0], id: "l'id", nota: 'finto' }],
  };
  assert.ok(generaSeedTransizioni(finto).includes("'l''ente'"));
  assert.ok(generaBloccoCasi(finto).includes("'l''id'"));
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
