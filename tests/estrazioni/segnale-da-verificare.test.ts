/**
 * Il bollino «da verificare» sul sito (contratto interno del giro 2, §15 con
 * §19.14): quale motivo si mostra accanto a quale stato, da dove arriva (vista
 * o tabella), come cambia la pillola e la nota «di cui N da verificare»
 * nell'hero degli «in apertura».
 *
 *   npm test
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  giornoRoma,
  MOTIVI_DA_VERIFICARE,
  motivoDellaRiga,
  motivoVisibile,
  STATI_BANDO,
} from '../../src/lib/stato-bando.ts';
import { ASPETTO_STATO, aspettoConVerifica, aspettoStato } from '../../src/lib/bandi/aspetto.ts';
import { modelloCard, tessere } from '../../src/lib/bandi/elenco.ts';
import type { Valori } from '../../src/lib/liste/parametri.ts';

// Le coppie che la regola può produrre: ramo I per «in apertura», ramo A per «aperto».
const AMMESSE: Readonly<Record<string, readonly string[]>> = {
  'in apertura prossimamente': [
    'data_apertura_passata', 'smentito_dalla_fonte', 'previsione_scaduta', 'senza_conferma',
  ],
  'aperto': ['smentito_dalla_fonte', 'termine_passato', 'senza_conferma'],
};

test('motivoVisibile: solo le coppie (stato, motivo) che la regola produce', () => {
  for (const stato of [...STATI_BANDO, null, 'boh']) {
    for (const motivo of [...MOTIVI_DA_VERIFICARE, null, 'boh', '']) {
      const atteso = stato !== null && motivo !== null && (AMMESSE[stato] ?? []).includes(motivo) ? motivo : null;
      assert.equal(motivoVisibile(stato, motivo), atteso, `${stato} / ${motivo}`);
    }
  }
});

test('motivoDellaRiga: dalla vista vale la colonna, anche quando e\' null', () => {
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  // Una riga della vista porta sempre la chiave: null vuol dire «nessuna prova
  // contraria», e non si ricalcola niente anche se la riga sembrerebbe dubbia.
  const vista = {
    stato_bando: 'in apertura prossimamente',
    data_apertura: '2026-09-01',
    stato_da_verificare: null,
  };
  assert.equal(motivoDellaRiga(vista, 'in apertura prossimamente', adesso), null);
  assert.equal(
    motivoDellaRiga({ ...vista, stato_da_verificare: 'previsione_scaduta' }, 'in apertura prossimamente', adesso),
    'previsione_scaduta',
  );
  // un motivo incompatibile con lo stato mostrato (uno stato da evento) si spegne
  assert.equal(
    motivoDellaRiga({ ...vista, stato_da_verificare: 'senza_conferma' }, 'sospeso', adesso),
    null,
  );
  assert.equal(motivoDellaRiga({ ...vista, stato_da_verificare: 'boh' }, 'in apertura prossimamente', adesso), null);
});

test('motivoDellaRiga: dalla tabella si ricalcola con i campi della riga', () => {
  const adesso = new Date('2026-09-30T12:00:00+02:00');
  const inApertura = { stato_bando: 'in apertura prossimamente', data_scadenza: null };
  // data di apertura passata e non verificata → I2
  assert.equal(
    motivoDellaRiga({ ...inApertura, data_apertura: '2026-09-01', data_apertura_verificata: false }, 'in apertura prossimamente', adesso),
    'data_apertura_passata',
  );
  // pubblicato ieri → grazia (I6); pubblicato da un mese → null anche lui:
  // la tabella non ha `esaminato_attivo_at`, e senza un esame in attivo il ramo
  // I non accende senza_conferma (I6-bis)
  assert.equal(
    motivoDellaRiga({ ...inApertura, pubblicato_at: '2026-09-29T10:00:00+00:00' }, 'in apertura prossimamente', adesso),
    null,
  );
  assert.equal(
    motivoDellaRiga({ ...inApertura, pubblicato_at: '2026-08-30T10:00:00+00:00' }, 'in apertura prossimamente', adesso),
    null,
  );
  // apertura futura verificata → I1
  assert.equal(
    motivoDellaRiga(
      { ...inApertura, data_apertura: '2026-10-15', data_apertura_verificata: true, pubblicato_at: '2026-08-30T10:00:00+00:00' },
      'in apertura prossimamente',
      adesso,
    ),
    null,
  );
  // un aperto senza scadenza dalla tabella non ha mai un esame in attivo: A4
  assert.equal(
    motivoDellaRiga({ stato_bando: 'aperto', data_scadenza: null, pubblicato_at: '2026-08-30T10:00:00+00:00' }, 'aperto', adesso),
    null,
  );
});

test('giornoRoma: la data civile di Roma di un timestamp', () => {
  assert.equal(giornoRoma('2026-09-19T22:30:00+00:00'), '2026-09-20');
  assert.equal(giornoRoma('2026-09-19T21:59:59Z'), '2026-09-19');
  // senza fuso vale UTC, mai l'ora locale del processo (i test girano a +05:45)
  assert.equal(giornoRoma('2026-09-19T22:30:00'), '2026-09-20');
  assert.equal(giornoRoma('2026-09-19T20:00:00'), '2026-09-19');
  assert.equal(giornoRoma('boh'), null);
  assert.equal(giornoRoma(null), null);
  assert.equal(giornoRoma(undefined), null);
});

test('pillola: «In apertura · da verificare» e «Aperto · da verificare», stessa palette', () => {
  const inApertura = aspettoConVerifica('in apertura prossimamente', 'senza_conferma');
  assert.equal(inApertura?.etichetta, 'In apertura · da verificare');
  assert.equal(inApertura?.pillola, ASPETTO_STATO['in apertura prossimamente'].pillola);
  assert.equal(inApertura?.barra, ASPETTO_STATO['in apertura prossimamente'].barra);
  for (const motivo of AMMESSE['in apertura prossimamente']) {
    assert.equal(aspettoConVerifica('in apertura prossimamente', motivo)?.etichetta, 'In apertura · da verificare', motivo);
  }
  for (const motivo of AMMESSE.aperto) {
    const aperto = aspettoConVerifica('aperto', motivo);
    assert.equal(aperto?.etichetta, 'Aperto · da verificare', motivo);
    assert.equal(aperto?.pillola, ASPETTO_STATO.aperto.pillola);
  }
  // senza motivo, o con un motivo incompatibile, la pillola di sempre
  for (const stato of STATI_BANDO) {
    assert.deepEqual(aspettoConVerifica(stato, null), aspettoStato(stato), stato);
  }
  assert.deepEqual(aspettoConVerifica('aperto', 'previsione_scaduta'), aspettoStato('aperto'));
  assert.deepEqual(aspettoConVerifica('in apertura prossimamente', 'termine_passato'), aspettoStato('in apertura prossimamente'));
  assert.deepEqual(aspettoConVerifica('chiuso', 'senza_conferma'), aspettoStato('chiuso'));
  assert.equal(aspettoConVerifica(null, 'senza_conferma'), null);
  // l'oggetto condiviso della palette non viene modificato
  assert.equal(ASPETTO_STATO.aperto.etichetta, 'Aperto');
});

test('card: nessun conto alla rovescia per un aperto senza scadenza o per un «in apertura»', () => {
  const oggi = '2026-09-30';
  assert.equal(modelloCard({ stato: 'aperto', data_scadenza: null, importo_totale_eur: null }, oggi).giorniTesto, null);
  assert.equal(
    modelloCard({ stato: 'in apertura prossimamente', data_scadenza: '2026-10-10', importo_totale_eur: null }, oggi).giorniTesto,
    null,
  );
});

const url = (v: Valori): string => {
  const qs = new URLSearchParams();
  for (const [k, vs] of Object.entries(v)) for (const x of vs) qs.append(k, x);
  const s = qs.toString();
  return `/bandi${s ? `?${s}` : ''}`;
};

test('hero: «di cui N da verificare» solo sulla tessera degli «in apertura» e solo con N > 0', () => {
  const base = { tutti: 2148, aperti: 1284, inApertura: 212, chiusi: 652, inScadenza: 37 };
  const conNota = tessere({}, { ...base, inAperturaDaVerificare: 1234 }, url);
  assert.deepEqual(conNota.map((t) => t.nota), [undefined, undefined, 'di cui 1.234 da verificare']);
  // numero, etichetta e link della tessera non cambiano
  assert.deepEqual(
    conNota.map((t) => [t.numero, t.etichetta, t.href]),
    tessere({}, base, url).map((t) => [t.numero, t.etichetta, t.href]),
  );
  // zero o assente (pagine filtro): nessuna nota, nemmeno la chiave
  for (const c of [base, { ...base, inAperturaDaVerificare: 0 }]) {
    for (const t of tessere({}, c, url)) assert.equal('nota' in t, false, t.chiave);
  }
});

test('card, scheda e tessere usano il motivo, con un solo markup', () => {
  const card = readFileSync(new URL('../../src/components/liste/CardBando.astro', import.meta.url), 'utf8');
  assert.ok(card.includes('aspettoConVerifica(stato, motivoDellaRiga(riga, stato))'));
  assert.equal(card.includes('m.aspetto'), false, 'la card non deve piu\' usare la pillola senza motivo');
  const scheda = readFileSync(new URL('../../src/pages/bandi/[slug].astro', import.meta.url), 'utf8');
  assert.ok(scheda.includes('const motivo = motivoDellaRiga(colonne, stato);'));
  assert.ok(scheda.includes('aspettoConVerifica(stato, motivo)'));
  assert.ok(scheda.includes('motivo_da_verificare: motivo,'));
  const tessereAstro = readFileSync(new URL('../../src/components/bandi/TessereBandi.astro', import.meta.url), 'utf8');
  assert.ok(tessereAstro.includes('{t.nota && '));
});
