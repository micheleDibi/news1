/**
 * `src/lib/bandi/filtro-stato.ts`: il filtro `?stato=` delle liste.
 *
 * Due regressioni difese qui:
 *  - `?stato=sospeso` non deve arrivare a PostgREST senza il flag degli stati
 *    estesi, o la lista torna vuota invece che intera; e chip, segmenti e
 *    tessere non devono mostrare un filtro che la query ignora (giro 3, §14);
 *  - il ramo `chiuso` non deve catturare un sospeso o un revocato con la
 *    scadenza passata (A3: un sospeso non si chiude mai d'ufficio).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { condizioneStatoBando, statiAmmessi, statiRichiesti } from '../../src/lib/bandi/filtro-stato.ts';
import { statoEffettivo } from '../../src/lib/stato-bando.ts';
import { chipFiltri, segmentiStato, tessere } from '../../src/lib/bandi/elenco.ts';
import type { Valori } from '../../src/lib/liste/parametri.ts';

const OGGI = '2026-09-23';

test('stati ammessi: tre senza il flag, cinque con il flag', () => {
  assert.deepEqual([...statiAmmessi(false)], ['aperto', 'chiuso', 'in apertura prossimamente']);
  assert.deepEqual([...statiAmmessi(true)],
    ['aperto', 'chiuso', 'in apertura prossimamente', 'sospeso', 'revocato']);
});

test('statiRichiesti: filtra, deduplica e usa l\'ordine del vocabolario', () => {
  assert.deepEqual(statiRichiesti(['sospeso', 'aperto'], false), ['aperto']);
  assert.deepEqual(statiRichiesti(['sospeso', 'aperto'], true), ['aperto', 'sospeso']);
  // L'ordine della query string non deve cambiare la condizione prodotta.
  assert.deepEqual(statiRichiesti(['chiuso', 'aperto'], false), statiRichiesti(['aperto', 'chiuso'], false));
  assert.deepEqual(statiRichiesti(['aperto', 'aperto'], false), ['aperto']);
  assert.deepEqual(statiRichiesti(['APERTO', 'scaduto', ''], true), []);
  assert.deepEqual(statiRichiesti([], false), []);
  assert.deepEqual(statiRichiesti(undefined, false), []);
});

test('chiuso: scadenza passata oppure colonna, mai un sospeso o un revocato', () => {
  const [condizione] = condizioneStatoBando(['chiuso'], OGGI);
  assert.equal(
    condizione,
    'and(or(stato_bando.not.in.(sospeso,revocato),stato_bando.is.null),' +
    `or(stato_bando.eq.chiuso,data_scadenza.lt.${OGGI}))`,
  );
  // È la differenza con la condizione precedente, che era il solo `or(...)`.
  assert.ok(condizione.startsWith('and(or(stato_bando.not.in.(sospeso,revocato)'));
});

test('chiuso: una riga senza stato e già scaduta resta nella lista', () => {
  // `NULL NOT IN (...)` vale NULL: con il solo `not.in` PostgREST scartava le
  // righe con `stato_bando` NULL, che `statoEffettivo` marca comunque «chiuso».
  // Lista e badge divergevano per costruzione.
  const [condizione] = condizioneStatoBando(['chiuso'], OGGI);
  assert.ok(condizione.includes('stato_bando.is.null'), 'le righe senza stato vanno tenute');
  assert.equal(
    statoEffettivo({ stato: null, data_scadenza: '2026-09-22' }, new Date('2026-09-23T10:00:00Z')),
    'chiuso',
  );
});

test('aperto e in apertura: colonna più scadenza non passata, valore quotato', () => {
  assert.deepEqual(condizioneStatoBando(['aperto'], OGGI), [
    `and(stato_bando.eq.aperto,or(data_scadenza.gte.${OGGI},data_scadenza.is.null))`,
  ]);
  // Il valore ha spazi: va fra doppi apici o PostgREST non lo interpreta.
  assert.deepEqual(condizioneStatoBando(['in apertura prossimamente'], OGGI), [
    `and(stato_bando.eq."in apertura prossimamente",or(data_scadenza.gte.${OGGI},data_scadenza.is.null))`,
  ]);
});

test('sospeso e revocato: nessuna condizione sulla data (A3)', () => {
  assert.deepEqual(condizioneStatoBando(['sospeso'], OGGI), ['stato_bando.eq.sospeso']);
  assert.deepEqual(condizioneStatoBando(['revocato'], OGGI), ['stato_bando.eq.revocato']);
  for (const condizione of condizioneStatoBando(['sospeso', 'revocato'], OGGI)) {
    assert.equal(condizione.includes('data_scadenza'), false);
  }
});

test('più stati: un ramo ciascuno dentro un solo or()', () => {
  const [condizione] = condizioneStatoBando(['aperto', 'chiuso', 'sospeso'], OGGI);
  assert.ok(condizione.startsWith('or('));
  assert.ok(condizione.endsWith(')'));
  assert.ok(condizione.includes('stato_bando.eq.aperto'));
  assert.ok(condizione.includes('stato_bando.eq.chiuso'));
  assert.ok(condizione.includes('stato_bando.eq.sospeso'));
  // Parentesi bilanciate: una query sbilanciata dà 400 PGRST100.
  let livello = 0;
  for (const c of condizione) {
    if (c === '(') livello += 1;
    if (c === ')') livello -= 1;
    assert.ok(livello >= 0);
  }
  assert.equal(livello, 0);
});

test('nessuno stato richiesto: nessuna condizione', () => {
  assert.deepEqual(condizioneStatoBando([], OGGI), []);
});

// ---------------------------------------------------------------------------
// F2: quando la fonte calcola lo stato, la ricostruzione non serve piu'
// ---------------------------------------------------------------------------

test('sulla vista il filtro è una condizione sola', () => {
  // Tutta la ricostruzione di sopra esiste perché la tabella non ha lo stato
  // effettivo: va ricomposto da `stato_bando` e `data_scadenza` con un
  // intreccio di or/and. La vista lo calcola lei, quindi il filtro diventa una
  // riga — e diventa anche più giusto, perché la vista conosce l'ora di
  // scadenza e sa se la data di apertura ha una prova.
  assert.deepEqual(
    condizioneStatoBando(['aperto'], OGGI, 'stato_effettivo'),
    ['stato_effettivo.in.(aperto)'],
  );
  // Nessuna condizione sulle date: la vista le ha già applicate. Se ne
  // restasse una, un bando scaduto ma non ancora allineato sparirebbe dalla
  // lista pur avendo il badge «Chiuso».
  const [condizione] = condizioneStatoBando(['aperto'], OGGI, 'stato_effettivo');
  assert.ok(!condizione.includes('data_scadenza'));
  assert.ok(!condizione.includes(OGGI));
});

test('sulla vista i valori con spazi restano fra apici', () => {
  assert.deepEqual(
    condizioneStatoBando(['in apertura prossimamente'], OGGI, 'stato_effettivo'),
    ['stato_effettivo.in.("in apertura prossimamente")'],
  );
});

test('sulla vista i cinque stati stanno in un solo `in`', () => {
  const [condizione] = condizioneStatoBando(
    ['aperto', 'chiuso', 'sospeso'], OGGI, 'stato_effettivo',
  );
  assert.equal(condizione, 'stato_effettivo.in.(aperto,chiuso,sospeso)');
  // In particolare `chiuso` non porta più l'esclusione di sospeso e revocato:
  // sulla vista un sospeso non è chiuso per costruzione.
  assert.ok(!condizione.includes('not.in'));
});

test('senza colonna calcolata la ricostruzione resta quella di prima', () => {
  // Il ripiego deve continuare a funzionare: tornare indietro sul flag è il
  // modo di rientrare da un guasto, e non deve cambiare comportamento.
  const conColonna = condizioneStatoBando(['chiuso'], OGGI, 'stato_effettivo');
  const senza = condizioneStatoBando(['chiuso'], OGGI, null);
  assert.notDeepEqual(conColonna, senza);
  assert.ok(senza[0].includes('data_scadenza.lt.' + OGGI));
  assert.ok(senza[0].includes('not.in.(sospeso,revocato)'));
  // E il default del parametro è la ricostruzione: chi non passa nulla si
  // comporta come prima di F2.
  assert.deepEqual(condizioneStatoBando(['chiuso'], OGGI), senza);
});

test('nessuno stato richiesto: nessuna condizione, con o senza colonna', () => {
  assert.deepEqual(condizioneStatoBando([], OGGI, 'stato_effettivo'), []);
  assert.deepEqual(condizioneStatoBando([], OGGI, null), []);
});

// ---------------------------------------------------------------------------
// Chip, segmenti e tessere: dicono solo il filtro che la query applica
// ---------------------------------------------------------------------------

/** URL leggibile per le asserzioni: solo `stato`, nell'ordine dei valori. */
const urlStato = (v: Valori): string =>
  `/bandi${(v.stato ?? []).length > 0 ? `?${(v.stato ?? []).map((s) => `stato=${s}`).join('&')}` : ''}`;
const CONTEGGI = { tutti: 2148, aperti: 1284, inApertura: 212, chiusi: 652, inScadenza: 37 };

test('?stato=sospeso senza il flag: nessuna chip «Stato» sopra una lista non filtrata', () => {
  // `caricaBandi` ignora il valore (`statiRichiesti(…, false)` = []): la chip
  // «Stato: Sospeso» prometteva un filtro che la lista non aveva (§14).
  for (const stato of [['sospeso'], ['revocato'], ['scaduto']]) {
    assert.deepEqual(chipFiltri({ stato }, [], urlStato, false).filter((c) => c.chiave === 'Stato'), [], stato[0]);
  }
  // Con il flag acceso il filtro c'è, e la chip anche.
  const conFlag = chipFiltri({ stato: ['sospeso'] }, [], urlStato, true);
  assert.deepEqual(conFlag.map((c) => [c.chiave, c.valore, c.href]), [['Stato', 'Sospeso', '/bandi']]);
});

test('una chip per stato applicato, e il suo link toglie anche i valori ignorati', () => {
  const chip = chipFiltri({ stato: ['sospeso', 'chiuso', 'aperto'] }, [], urlStato, false);
  assert.deepEqual(chip.map((c) => [c.valore, c.href]), [
    ['Aperto', '/bandi?stato=chiuso'],
    ['Chiuso', '/bandi?stato=aperto'],
  ]);
  // Il caso di sempre resta com'era: una chip, che toglie il filtro.
  assert.deepEqual(chipFiltri({ stato: ['aperto'] }, [], urlStato, false).map((c) => c.href), ['/bandi']);
});

test('segmenti: con uno stato ignorato è attivo «Tutti», perché la lista è quella', () => {
  const attivi = (stato: string[], estesi: boolean) =>
    segmentiStato({ stato }, CONTEGGI, estesi).filter((s) => s.attivo).map((s) => s.etichetta);
  assert.deepEqual(attivi(['sospeso'], false), ['Tutti']);
  assert.deepEqual(attivi(['chiuso'], false), ['Chiusi']);
  // Con il flag il sospeso è un filtro vero, che la barra non ha: nessun segmento.
  assert.deepEqual(attivi(['sospeso'], true), []);
  assert.deepEqual(attivi([], false), ['Tutti']);
});

test('tessere: attive solo per uno stato applicato', () => {
  const attive = (valori: Valori, estesi: boolean) =>
    tessere(valori, CONTEGGI, urlStato, estesi).filter((t) => t.attiva).map((t) => t.chiave);
  assert.deepEqual(attive({ stato: ['aperto'] }, false), ['aperti']);
  assert.deepEqual(attive({ stato: ['in apertura prossimamente'] }, false), ['in-apertura']);
  assert.deepEqual(attive({ stato: ['sospeso'] }, false), []);
  assert.deepEqual(attive({ stato: ['sospeso', 'aperto'] }, false), ['aperti']);
});
