/**
 * Il box «Aggiornamenti»: quali eventi si mostrano, con quale frase, e che
 * cosa si fa quando lo stato non si può ancora scrivere.
 *
 * Due invarianti che valgono più delle frasi:
 *
 * 1. il testo è **templato dal tipo**, non ripreso dal modello che ha
 *    classificato il cambiamento. Un evento di tipo ignoto non produce una
 *    riga: meglio niente che una frase inventata;
 * 2. la prova non si mostra se sta su un aggregatore. È la stessa regola del
 *    trigger a DB, ripetuta qui perché la pagina non deve dipendere da una
 *    migrazione per non fare una promessa falsa.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { statoDaEventi, testoEvento, vociAggiornamento } from '../../src/lib/bandi/aggiornamenti.ts';
import type { EventoBando } from '../../src/lib/bandi/tipi.ts';

const evento = (extra: Partial<EventoBando>): EventoBando => ({
  id: 1,
  tipo: 'proroga',
  data_evento: '2026-09-18',
  url_prova: 'https://regione.marche.it/bando',
  verificato: true,
  in_aggiornamenti: true,
  applicato: true,
  ...extra,
});

test('la frase è templata dal tipo e porta la data della fonte', () => {
  assert.equal(
    testoEvento(evento({ tipo: 'proroga', valore_dopo: { data_scadenza: '2026-12-01' } })),
    'Scadenza prorogata al 1 dicembre 2026',
  );
  assert.equal(
    testoEvento(evento({ tipo: 'rettifica', campo: 'data_apertura', valore_dopo: '2026-10-22' })),
    'Nuova data di apertura: 22 ottobre 2026',
  );
  assert.equal(testoEvento(evento({ tipo: 'rettifica', campo: 'contenuto' })),
    'Testo della scheda aggiornato');
  assert.equal(testoEvento(evento({ tipo: 'graduatoria', valore_dopo: null })),
    'Pubblicata la graduatoria');
});

test('un tipo che non sappiamo raccontare non produce una riga', () => {
  assert.equal(testoEvento(evento({ tipo: 'segnale_fonte' })), null);
  assert.deepEqual(vociAggiornamento([evento({ tipo: 'segnale_fonte' })]), []);
});

test('si mostra solo ciò che porta `in_aggiornamenti`', () => {
  // La chiusura per scadenza la scrive il cron e non è una notizia: la data
  // era già in pagina. Il flag è ciò che distingue un fatto per il lettore da
  // una transizione tecnica.
  const eventi = [
    evento({ id: 1, tipo: 'chiusura_automatica', in_aggiornamenti: false }),
    evento({ id: 2, tipo: 'proroga', valore_dopo: { data_scadenza: '2026-12-01' } }),
  ];
  const voci = vociAggiornamento(eventi);
  assert.equal(voci.length, 1);
  assert.equal(voci[0].id, 2);
});

test('la prova su un aggregatore non si mostra', () => {
  const voci = vociAggiornamento([evento({
    url_prova: 'https://www.obiettivoeuropa.com/bandi/x',
    valore_dopo: { data_scadenza: '2026-12-01' },
  })]);
  assert.equal(voci.length, 1, 'la voce resta: è il link che non si mostra');
  assert.equal(voci[0].url, null);
  assert.equal(voci[0].host, null);
});

test('le voci escono dalla più recente', () => {
  const voci = vociAggiornamento([
    evento({ id: 1, data_evento: '2026-08-01', valore_dopo: { d: '2026-09-01' } }),
    evento({ id: 2, data_evento: '2026-09-18', valore_dopo: { d: '2026-12-01' } }),
    evento({ id: 3, data_evento: null, valore_dopo: { d: '2026-10-01' } }),
  ]);
  assert.deepEqual(voci.map((v) => v.id), [2, 1, 3]);
});

test('l\'ordine segue la data, non la frase in italiano', () => {
  // Ordinate sulla frase, «9 luglio» e «9 ottobre» passavano davanti a
  // «25 settembre» e a «12 ottobre»: il caso reale di una scheda con due allegati.
  const voci = vociAggiornamento([
    evento({ id: 1, data_evento: '2026-10-12' }),
    evento({ id: 2, data_evento: '2026-10-09' }),
    evento({ id: 3, data_evento: '2026-11-03' }),
    evento({ id: 4, data_evento: '2026-07-09' }),
    evento({ id: 5, data_evento: '2026-09-25T08:00:00Z' }),
  ]);
  assert.deepEqual(voci.map((v) => v.id), [3, 1, 2, 5, 4]);
  assert.equal(voci[0].quando, '3 novembre 2026');
});

test('prima della migrazione 06 lo stato lo dicono gli eventi', () => {
  // Il caso che questa funzione esiste per coprire: la colonna dice «aperto»
  // perché il CHECK ammette tre valori, ma l'ente ha revocato il bando. Senza
  // questo, la scheda inviterebbe a partecipare.
  const revoca = evento({ tipo: 'revoca', applicato: false, data_evento: '2026-09-20' });
  assert.equal(statoDaEventi([revoca]), 'revocato');
  assert.equal(statoDaEventi([evento({ tipo: 'sospensione', applicato: false })]), 'sospeso');
});

test('una riapertura verificata annulla la sospensione precedente', () => {
  const eventi = [
    evento({ id: 1, tipo: 'sospensione', data_evento: '2026-09-10' }),
    evento({ id: 2, tipo: 'riapertura', data_evento: '2026-09-20' }),
  ];
  assert.equal(statoDaEventi(eventi), null);
  // E l'ordine non conta: vince il più recente, non l'ultimo dell'array.
  assert.equal(statoDaEventi([...eventi].reverse()), null);
});

test('un evento non verificato non cambia lo stato', () => {
  // I gate del monitor decidono cosa è verificato. Qui ci si fida solo di
  // quella decisione: una proposta non confermata non può spegnere una CTA.
  assert.equal(statoDaEventi([evento({ tipo: 'revoca', verificato: false })]), null);
});

test('una rettifica che propone uno stato nuovo vale come l\'evento di quel tipo', () => {
  const proposta = evento({
    tipo: 'rettifica', campo: 'stato', valore_dopo: { stato_proposto: 'sospeso' },
  });
  assert.equal(statoDaEventi([proposta]), 'sospeso');
});

test('nessun evento, nessuna voce e nessuno stato', () => {
  for (const vuoto of [null, undefined, []]) {
    assert.deepEqual(vociAggiornamento(vuoto), []);
    assert.equal(statoDaEventi(vuoto), null);
  }
});
