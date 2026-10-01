/**
 * Lo storico in fondo alla scheda (contratto interno del giro 3, §15): tutti
 * gli eventi che la anon key legge, dal più recente, con la frase per tipo e
 * l'etichetta «Correzione» solo dove corregge davvero qualcosa.
 *
 * Le invarianti:
 *
 * 1. ogni tipo pubblico del contratto DB (§6.1) ha una frase; i tipi interni
 *    non producono righe (non dovrebbero nemmeno arrivare, ma se arrivassero
 *    la pagina non inventa niente);
 * 2. l'ordine e la data mostrata sono quelli del rilevamento, nel giorno di
 *    Roma e non nell'ora locale del processo (i test girano a Kathmandu,
 *    +05:45); la data dell'ente, se è un altro giorno, resta come «data
 *    dell'atto»;
 * 3. «Correzione» non compare sugli eventi tecnici, automatici o documentali:
 *    ogni scheda ha una «Scheda pubblicata» fuori dal box, e non corregge
 *    niente;
 * 4. un evento ritirato non si racconta.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  dividiStorico, eCorrezione, STORICO_VISIBILI, vociStorico,
} from '../../src/lib/bandi/storico.ts';
import type { EventoStorico, VoceStorico } from '../../src/lib/bandi/storico.ts';
import { vociAggiornamento } from '../../src/lib/bandi/aggiornamenti.ts';

const evento = (extra: Partial<EventoStorico>): EventoStorico => ({
  id: 1,
  bando_id: 7,
  tipo: 'proroga',
  campo: 'data_scadenza',
  valore_dopo: { data_scadenza: '2026-12-01' },
  data_evento: '2026-09-18',
  rilevato_at: '2026-09-18T08:00:00+00:00',
  url_prova: 'https://regione.marche.it/bando',
  verificato: true,
  in_aggiornamenti: true,
  applicato: true,
  cursore: 100,
  riferisce_a: null,
  ...extra,
});

/** I tipi con cursore del contratto DB, §6.1. */
const TIPI_PUBBLICI = [
  'pubblicazione', 'apertura_automatica', 'chiusura_automatica', 'apertura', 'chiusura',
  'proroga', 'riapertura', 'rettifica', 'sospensione', 'revoca', 'annullamento_revoca',
  'graduatoria', 'esito', 'faq', 'nuovo_allegato', 'fonte_ufficiale_verificata',
  'data_verificata', 'fusione', 'separazione', 'cambio_slug', 'ritiro',
  'correzione_redazionale',
];

/** I tipi sempre interni del contratto DB, §6.1. */
const TIPI_INTERNI = [
  'segnale_fonte', 'sparito_dalla_fonte', 'elaborazione_bloccata',
  'fonte_ufficiale_non_trovata', 'possibile_doppione', 'preavviso_collegato',
];

test('ogni tipo pubblico ha una riga nello storico, anche fuori dal box', () => {
  for (const tipo of TIPI_PUBBLICI) {
    const voci = vociStorico([evento({ tipo, campo: null, in_aggiornamenti: false })]);
    assert.equal(voci.length, 1, `il tipo ${tipo} non ha una frase`);
    assert.ok(voci[0].testo.length > 0);
  }
});

test('un tipo interno non produce una riga', () => {
  for (const tipo of TIPI_INTERNI) {
    assert.deepEqual(vociStorico([evento({ tipo })]), [], `il tipo ${tipo} è uscito in pagina`);
  }
});

test('lo storico contiene anche ciò che il box non mostra', () => {
  // Il caso di ogni scheda: la pubblicazione e la fonte individuata sono
  // `in_aggiornamenti=false`, quindi fuori dal box, ma sono storia del bando.
  const voci = vociStorico([
    evento({ id: 1, tipo: 'pubblicazione', campo: null, valore_dopo: null,
      data_evento: '2026-06-29', rilevato_at: '2026-06-29T10:00:00+00:00',
      in_aggiornamenti: false, url_prova: null, cursore: 1 }),
    evento({ id: 2, tipo: 'fonte_ufficiale_verificata', campo: 'fonte_ufficiale_url',
      valore_dopo: { url: 'https://regione.marche.it/bando', tipo: 'ente' },
      data_evento: null, rilevato_at: '2026-07-02T10:00:00+00:00', in_aggiornamenti: false, cursore: 2 }),
  ]);
  assert.deepEqual(voci.map((v) => v.testo), [
    'Individuata la pagina ufficiale dell\'ente',
    'Scheda pubblicata su EduNews24',
  ]);
  assert.equal(voci[0].host, 'regione.marche.it');
  assert.equal(voci[1].url, null);
});

test('la data è il giorno di Roma del rilevamento', () => {
  // 21:30 UTC del 30/09 sono le 23:30 a Roma (ancora il 30) e le 03:15 del
  // 1/10 a Kathmandu; 22:30 UTC sono già l'1/10 a Roma, ma il 30 in UTC.
  const [primo, secondo] = vociStorico([
    evento({ id: 1, data_evento: null, rilevato_at: '2026-09-30T21:30:00.123456+00:00' }),
    evento({ id: 2, data_evento: null, rilevato_at: '2026-09-30T22:30:00Z' }),
  ]);
  assert.equal(primo.giorno, '2026-10-01');
  assert.equal(primo.id, 2);
  assert.equal(primo.quando, '1 ottobre 2026');
  assert.equal(secondo.giorno, '2026-09-30');
  assert.equal(primo.dataAtto, null, 'senza data dell\'ente non c\'è data dell\'atto');
});

test('il caso 215460: la proroga rilevata tardi sta sopra la chiusura automatica', () => {
  // Le righe vere del bando (sola lettura, 01/10/2026). La proroga è datata
  // dall'ente 17/09 ma è entrata nella scheda il 30/09, dopo la chiusura del
  // job orario del 25/09: in cima deve esserci lei, perché il bando è aperto.
  const voci = vociStorico([
    evento({ id: 1403, tipo: 'pubblicazione', campo: null, valore_dopo: null, url_prova: null,
      data_evento: '2026-07-13', rilevato_at: '2026-07-13T16:05:44.62037+00:00',
      in_aggiornamenti: false, verificato: false, cursore: 1403 }),
    evento({ id: 8964, tipo: 'fonte_ufficiale_verificata', campo: 'fonte_ufficiale_url',
      valore_dopo: { url: 'https://www.euroinfosicilia.it/avviso-h2/', host: 'euroinfosicilia.it', tipo: 'ente' },
      url_prova: 'https://www.euroinfosicilia.it/avviso-h2/',
      data_evento: null, rilevato_at: '2026-09-24T16:10:17.842272+00:00',
      in_aggiornamenti: false, verificato: false, cursore: 8964 }),
    evento({ id: 9412, tipo: 'chiusura_automatica', campo: 'stato_bando',
      valore_dopo: 'chiuso', url_prova: null,
      data_evento: '2026-09-25', rilevato_at: '2026-09-24T22:05:00.051133+00:00',
      in_aggiornamenti: false, verificato: false, cursore: 9412 }),
    evento({ id: 11576, tipo: 'proroga', campo: 'data_scadenza',
      valore_dopo: { stato_bando: 'aperto', ora_scadenza: '12:00', data_scadenza: '2026-11-08' },
      url_prova: 'https://www.euroinfosicilia.it/avviso-h2/',
      data_evento: '2026-09-17', rilevato_at: '2026-09-30T10:26:48.024117+00:00',
      in_aggiornamenti: true, verificato: true, cursore: 11576 }),
  ]);
  assert.deepEqual(voci.map((v) => [v.quando, v.testo, v.dataAtto]), [
    ['30 settembre 2026', 'Scadenza prorogata all\'8 novembre 2026', '17 settembre 2026'],
    // Mezzanotte di Roma del 25/09 = 22:05 UTC del 24: stesso giorno dell'ente.
    ['25 settembre 2026', 'Bando chiuso: termine di scadenza raggiunto', null],
    ['24 settembre 2026', 'Individuata la pagina ufficiale dell\'ente', null],
    ['13 luglio 2026', 'Scheda pubblicata su EduNews24', null],
  ]);
});

test('la data dell\'atto non si ripete se la frase la dice già', () => {
  const [apertura] = vociStorico([evento({
    tipo: 'apertura', campo: 'data_apertura', valore_dopo: { data_apertura: '2026-07-06' },
    data_evento: '2026-07-06', rilevato_at: '2026-07-20T09:00:00Z',
  })]);
  assert.equal(apertura.testo, 'Bando aperto dal 6 luglio 2026');
  assert.equal(apertura.quando, '20 luglio 2026');
  assert.equal(apertura.dataAtto, null);
  // «6 luglio» non è detto da «16 luglio»: lì la data dell'atto resta.
  const [altra] = vociStorico([evento({
    tipo: 'apertura', campo: 'data_apertura', valore_dopo: { data_apertura: '2026-07-16' },
    data_evento: '2026-07-06', rilevato_at: '2026-07-20T09:00:00Z',
  })]);
  assert.equal(altra.dataAtto, '6 luglio 2026');
});

test('senza rilevamento vale il giorno dell\'ente, al suo posto nell\'ordine', () => {
  const voci = vociStorico([
    evento({ id: 1, data_evento: '2026-08-01', rilevato_at: '2026-08-01T09:00:00Z' }),
    evento({ id: 2, data_evento: '2026-08-15', rilevato_at: null }),
    evento({ id: 3, data_evento: '2026-09-01', rilevato_at: '2026-09-01T09:00:00Z' }),
  ]);
  assert.deepEqual(voci.map((v) => v.id), [3, 2, 1]);
  assert.equal(voci[1].giorno, '2026-08-15');
  assert.equal(voci[1].dataAtto, null);
});

test('dal più recente; a parità di rilevamento decide il cursore, poi l\'id', () => {
  const voci = vociStorico([
    evento({ id: 1, rilevato_at: '2026-08-01T10:00:00Z', cursore: 50 }),
    evento({ id: 2, rilevato_at: '2026-09-18T10:00:00Z', cursore: '9' }),
    evento({ id: 3, rilevato_at: '2026-09-18T10:00:00Z', cursore: '10' }),
    evento({ id: 4, data_evento: null, rilevato_at: null, cursore: 99 }),
    evento({ id: 6, rilevato_at: '2026-07-01T10:00:00Z', cursore: null }),
    evento({ id: 5, rilevato_at: '2026-07-01T10:00:00Z', cursore: null }),
    // Stesso giorno, ora diversa: conta l'istante, non solo il giorno.
    evento({ id: 7, rilevato_at: '2026-09-18T11:00:00+02:00', cursore: 1 }),
  ]);
  // Il cursore arriva anche come stringa (bigint): «10» viene dopo «9» come numero.
  assert.deepEqual(voci.map((v) => v.id), [3, 2, 7, 1, 6, 5, 4]);
  const senzaData = voci[voci.length - 1];
  assert.equal(senzaData.giorno, null);
  assert.equal(senzaData.quando, null);
});

test('«Correzione» solo su chi cambia una data o uno stato, fuori dal box', () => {
  const casi: Array<[Partial<EventoStorico>, boolean]> = [
    [{ tipo: 'rettifica', in_aggiornamenti: false }, true],
    [{ tipo: 'chiusura', in_aggiornamenti: false }, true],
    [{ tipo: 'proroga', in_aggiornamenti: false }, true],
    [{ tipo: 'sospensione', in_aggiornamenti: false }, true],
    [{ tipo: 'annullamento_revoca', in_aggiornamenti: false }, true],
    [{ tipo: 'proroga', in_aggiornamenti: true }, false],
    [{ tipo: 'rettifica', in_aggiornamenti: null }, false],
    [{ tipo: 'pubblicazione', in_aggiornamenti: false }, false],
    [{ tipo: 'chiusura_automatica', in_aggiornamenti: false }, false],
    [{ tipo: 'apertura_automatica', in_aggiornamenti: false }, false],
    [{ tipo: 'fonte_ufficiale_verificata', in_aggiornamenti: false }, false],
    [{ tipo: 'data_verificata', in_aggiornamenti: false }, false],
    [{ tipo: 'fusione', in_aggiornamenti: false }, false],
    [{ tipo: 'cambio_slug', in_aggiornamenti: false }, false],
    [{ tipo: 'nuovo_allegato', in_aggiornamenti: false }, false],
    [{ tipo: 'faq', in_aggiornamenti: false }, false],
    [{ tipo: 'graduatoria', in_aggiornamenti: false }, false],
    [{ tipo: 'esito', in_aggiornamenti: false }, false],
    [{ tipo: 'correzione_redazionale', in_aggiornamenti: true }, true],
    [{ tipo: 'correzione_redazionale', in_aggiornamenti: false }, true],
  ];
  for (const [extra, atteso] of casi) {
    assert.equal(eCorrezione(evento(extra)), atteso, JSON.stringify(extra));
    assert.equal(vociStorico([evento(extra)])[0].correzione, atteso, JSON.stringify(extra));
  }
});

test('la prova su un aggregatore non si mostra, la riga sì', () => {
  const [voce] = vociStorico([evento({ url_prova: 'https://www.obiettivoeuropa.com/bandi/x' })]);
  assert.equal(voce.url, null);
  assert.equal(voce.host, null);
  assert.equal(voce.testo, 'Scadenza prorogata al 1 dicembre 2026');
});

test('una prova che non è http(s) non diventa un href, la riga sì', () => {
  // Con M3 `url_prova` di `nuovo_allegato` sarà un href preso dalla pagina
  // dell'ente: lo schema va controllato qui, non solo a monte.
  for (const url_prova of [
    'javascript://comune.it/%0Aalert(1)',
    'javascript://comune.it/%0Aalert(document.domain)',
    'JAVASCRIPT://comune.it/%0Aalert(1)',
    'data:text/html,<script>alert(1)</script>',
    'ftp://regione.marche.it/bando.pdf',
  ]) {
    const [voce] = vociStorico([evento({ url_prova })]);
    assert.equal(voce.url, null, url_prova);
    assert.equal(voce.host, null, url_prova);
    assert.equal(voce.testo, 'Scadenza prorogata al 1 dicembre 2026');
  }
  const [buona] = vociStorico([evento({ url_prova: 'https://regione.marche.it/bando' })]);
  assert.equal(buona.url, 'https://regione.marche.it/bando');
  assert.equal(buona.host, 'regione.marche.it');
});

test('un evento ritirato non si racconta, e nemmeno il suo ritiro', () => {
  const voci = vociStorico([
    evento({ id: 10, tipo: 'proroga' }),
    evento({ id: 11, tipo: 'ritiro', campo: null, valore_dopo: null, riferisce_a: 10, cursore: 101 }),
    evento({ id: 12, tipo: 'faq', campo: null, valore_dopo: {}, cursore: 102 }),
  ]);
  assert.deepEqual(voci.map((v) => v.id), [12]);
  // L'id può arrivare come numero e `riferisce_a` come stringa: conta il valore.
  assert.deepEqual(vociStorico([
    evento({ id: 10 }),
    evento({ id: 11, tipo: 'ritiro', riferisce_a: '10' }),
  ]), []);
});

test('un ritiro che non punta a un evento resta una riga', () => {
  const [voce] = vociStorico([evento({ tipo: 'ritiro', campo: null, valore_dopo: null, riferisce_a: null })]);
  assert.equal(voce.testo, 'Scheda ritirata');
});

test('box e storico tolgono gli stessi eventi ritirati', () => {
  // Un solo filtro (`senzaRitirati`) per tutti e due (§18.10).
  const eventi = [
    evento({ id: 30, tipo: 'proroga', cursore: 1 }),
    evento({ id: 31, tipo: 'ritiro', campo: null, valore_dopo: null, riferisce_a: 30, cursore: 2 }),
    evento({ id: 32, tipo: 'faq', campo: null, valore_dopo: {}, cursore: 3 }),
  ];
  assert.deepEqual(vociStorico(eventi).map((v) => v.id), [32]);
  assert.deepEqual(vociAggiornamento(eventi).map((v) => v.id), [32]);
});

test('la correzione dello stato porta lo stato nuovo e l\'etichetta «Correzione»', () => {
  const [voce] = vociStorico([evento({
    tipo: 'correzione_redazionale', campo: 'stato_bando', valore_dopo: 'chiuso',
    in_aggiornamenti: false, verificato: false, url_prova: null,
  })]);
  assert.equal(voce.testo, 'Stato corretto dalla redazione: chiuso');
  assert.equal(voce.correzione, true);
});

test('una correzione redazionale non nasconde l\'evento che corregge', () => {
  const voci = vociStorico([
    evento({ id: 20, tipo: 'proroga', cursore: 1 }),
    evento({ id: 21, tipo: 'correzione_redazionale', campo: null, valore_dopo: null, riferisce_a: 20, cursore: 2 }),
  ]);
  assert.deepEqual(voci.map((v) => [v.id, v.correzione]), [[21, true], [20, false]]);
});

test('una riga letta due volte compare una volta sola', () => {
  const voci = vociStorico([evento({ id: 1 }), evento({ id: 1 }), evento({ id: 2, cursore: 101 })]);
  assert.deepEqual(voci.map((v) => v.id), [2, 1]);
});

test('i primi dieci in vista, gli altri nel <details>', () => {
  const voci = vociStorico(Array.from({ length: 25 }, (_, i) =>
    evento({ id: i + 1, cursore: i + 1 })));
  const { visibili, altre } = dividiStorico(voci);
  assert.equal(STORICO_VISIBILI, 10);
  assert.equal(visibili.length, 10);
  assert.equal(altre.length, 15);
  assert.equal(visibili[0].id, 25, 'il più recente è il primo visibile');
  assert.equal(altre[0].id, 15, 'il <details> riprende da dove la lista si ferma');

  const dieci = dividiStorico(voci.slice(0, 10));
  assert.equal(dieci.visibili.length, 10);
  assert.equal(dieci.altre.length, 0, 'con dieci eventi niente <details>');

  const vuoto: VoceStorico[] = [];
  assert.deepEqual(dividiStorico(vuoto), { visibili: [], altre: [] });
});

test('nessun evento, nessuno storico', () => {
  for (const vuoto of [null, undefined, []]) {
    assert.deepEqual(vociStorico(vuoto), []);
  }
});
