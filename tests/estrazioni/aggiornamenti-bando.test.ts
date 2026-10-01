/**
 * Il box «Aggiornamenti»: quali eventi si mostrano e con quale frase. Lo
 * stato del bando non si decide qui: lo dà solo la colonna.
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
import { senzaRitirati, testoEvento, vociAggiornamento } from '../../src/lib/bandi/aggiornamenti.ts';
import type { EventoBando } from '../../src/lib/bandi/tipi.ts';

type EventoConBando = EventoBando & {
  readonly bando_id?: number | string | null;
  readonly riferisce_a?: number | string | null;
};

const evento = (extra: Partial<EventoConBando>): EventoConBando => ({
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

test('davanti a 8 e 11 la preposizione si elide', () => {
  // Il caso reale del bando 215460: «prorogata al 8 novembre» non è italiano.
  assert.equal(testoEvento(evento({ tipo: 'proroga', valore_dopo: { data_scadenza: '2026-11-08' } })),
    'Scadenza prorogata all\'8 novembre 2026');
  assert.equal(testoEvento(evento({ tipo: 'riapertura', valore_dopo: '2026-11-11' })),
    'Bando riaperto dall\'11 novembre 2026');
  assert.equal(testoEvento(evento({ tipo: 'sospensione', valore_dopo: '2026-10-08' })),
    'Bando sospeso l\'8 ottobre 2026');
  // 18 e 28 cominciano per consonante: niente elisione.
  assert.equal(testoEvento(evento({ tipo: 'proroga', valore_dopo: { data_scadenza: '2026-11-18' } })),
    'Scadenza prorogata al 18 novembre 2026');
  assert.equal(testoEvento(evento({ tipo: 'apertura', valore_dopo: '2026-11-28' })),
    'Bando aperto dal 28 novembre 2026');
});

test('un tipo che non sappiamo raccontare non produce una riga', () => {
  assert.equal(testoEvento(evento({ tipo: 'segnale_fonte' })), null);
  assert.deepEqual(vociAggiornamento([evento({ tipo: 'segnale_fonte' })]), []);
});

test('la data della frase è quella del campo dell\'evento', () => {
  // Un'apertura reale porta insieme apertura e scadenza: la frase deve dire
  // l'apertura anche se la scadenza viene prima fra le chiavi.
  assert.equal(
    testoEvento(evento({
      tipo: 'apertura', campo: 'data_apertura',
      valore_dopo: { data_scadenza: '2026-10-29', data_apertura: '2026-09-28', stato_bando: 'aperto' },
    })),
    'Bando aperto dal 28 settembre 2026',
  );
  // Senza `campo` resta la prima data che si trova.
  assert.equal(
    testoEvento(evento({ tipo: 'proroga', campo: null, valore_dopo: { ora_scadenza: '23:59', data_scadenza: '2026-10-15' } })),
    'Scadenza prorogata al 15 ottobre 2026',
  );
});

test('le frasi dei tipi tecnici e automatici, che stanno solo nello storico', () => {
  assert.equal(testoEvento(evento({ tipo: 'pubblicazione', valore_dopo: null })),
    'Scheda pubblicata su EduNews24');
  assert.equal(testoEvento(evento({ tipo: 'chiusura_automatica', campo: 'stato_bando', valore_dopo: 'chiuso' })),
    'Bando chiuso: termine di scadenza raggiunto');
  assert.equal(testoEvento(evento({ tipo: 'apertura_automatica', campo: 'stato_bando', valore_dopo: 'aperto' })),
    'Bando aperto: è arrivata la data di apertura');
  assert.equal(testoEvento(evento({ tipo: 'fonte_ufficiale_verificata', campo: 'fonte_ufficiale_url',
    valore_dopo: { url: 'https://regione.marche.it/bando', host: 'regione.marche.it', tipo: 'ente' } })),
  'Individuata la pagina ufficiale dell\'ente');
  assert.equal(testoEvento(evento({ tipo: 'cambio_slug', valore_dopo: 'nuovo-slug' })),
    'Indirizzo della pagina aggiornato');
  assert.equal(testoEvento(evento({ tipo: 'separazione' })), 'Scheda separata da un\'altra scheda');
  assert.equal(testoEvento(evento({ tipo: 'ritiro' })), 'Scheda ritirata');
  assert.equal(testoEvento(evento({ tipo: 'correzione_redazionale' })), 'Correzione della redazione');
  // Fuori dal box restano fuori: il box mostra solo `in_aggiornamenti`.
  assert.deepEqual(vociAggiornamento([evento({ tipo: 'pubblicazione', in_aggiornamenti: false })]), []);
});

test('data_verificata dice quale data o quale ora è stata verificata', () => {
  assert.equal(testoEvento(evento({ tipo: 'data_verificata', campo: 'data_scadenza',
    valore_dopo: { data_scadenza: '2026-11-30' } })),
  'Scadenza verificata sulla pagina ufficiale: 30 novembre 2026');
  assert.equal(testoEvento(evento({ tipo: 'data_verificata', campo: 'data_apertura',
    valore_dopo: { data_apertura: '2026-10-05', ora_apertura: '09:00' } })),
  'Data di apertura verificata sulla pagina ufficiale: 5 ottobre 2026');
  assert.equal(testoEvento(evento({ tipo: 'data_verificata', campo: 'ora_scadenza',
    valore_dopo: { ora_scadenza: '13:00:00' } })),
  'Orario di scadenza verificato sulla pagina ufficiale: 13:00');
  assert.equal(testoEvento(evento({ tipo: 'data_verificata', campo: 'ora_apertura', valore_dopo: '09:30' })),
    'Orario di apertura verificato sulla pagina ufficiale: 09:30');
  assert.equal(testoEvento(evento({ tipo: 'data_verificata', campo: 'altro', valore_dopo: {} })),
    'Date verificate sulla pagina ufficiale');
});

test('la fusione si racconta diversa sul master e sul doppione', () => {
  // `bando_fondi` scrive due eventi, uno per parte, con lo stesso `master_id`.
  const sulMaster = { tipo: 'fusione', campo: 'bando_master_id', bando_id: 1262343,
    valore_dopo: { master_id: 1262343, master_slug: 'business-opportunities', fuso_id: 5 } };
  const sulDoppione = { tipo: 'fusione', campo: 'bando_master_id', bando_id: 5,
    valore_dopo: { master_id: 1262343, master_slug: 'business-opportunities' } };
  assert.equal(testoEvento(evento(sulMaster)), 'Unita a questa scheda un\'altra scheda dello stesso bando');
  assert.equal(testoEvento(evento(sulDoppione)), 'Scheda unita a quella principale dello stesso bando');
  // L'id del bando può arrivare come stringa: conta il valore, non il tipo.
  assert.equal(testoEvento(evento({ ...sulMaster, bando_id: '1262343' })),
    'Unita a questa scheda un\'altra scheda dello stesso bando');
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

test('una prova che non è http(s) non diventa un href', () => {
  // `hostDi` trova un host anche in `javascript://comune.it/…`: senza il
  // controllo dello schema quella stringa finiva nell'href della scheda.
  for (const url_prova of [
    'javascript://comune.it/%0Aalert(1)',
    'javascript://comune.it/%0Aalert(document.domain)',
    'JavaScript://regione.marche.it/%0Aalert(1)',
    'data:text/html,<script>alert(1)</script>',
    'ftp://regione.marche.it/bando.pdf',
  ]) {
    const voci = vociAggiornamento([evento({ url_prova, valore_dopo: { data_scadenza: '2026-12-01' } })]);
    assert.equal(voci.length, 1, `la voce resta anche con ${url_prova}`);
    assert.equal(voci[0].url, null, url_prova);
    assert.equal(voci[0].host, null, url_prova);
  }
});

test('nello stesso giorno la notizia più recente sta sopra', () => {
  // La query ordinava `data_evento desc, id desc`; ora gli eventi arrivano per
  // id crescente e l'ordine dello stesso giorno lo decide il sort.
  const voci = vociAggiornamento([
    evento({ id: 3, data_evento: '2026-09-18' }),
    evento({ id: 10, data_evento: '2026-09-18' }),
    evento({ id: '9', data_evento: '2026-09-18' }),
    evento({ id: 4, data_evento: '2026-09-20' }),
  ]);
  assert.deepEqual(voci.map((v) => v.id), [4, 10, '9', 3]);
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

test('lo stato non viene dagli eventi: il modulo non esporta più una seconda fonte', async () => {
  // `statoDaEventi` faceva vincere gli eventi sulla colonna: dopo una
  // correzione la scheda diceva «Sospeso» mentre lista, API e BandoFit
  // dicevano «Aperto» (RIPRESA §4.1 i, punto 3). Lo stato lo dà solo
  // `stato_effettivo` (contratto interno del giro 3, §14).
  const modulo = await import('../../src/lib/bandi/aggiornamenti.ts');
  assert.equal('statoDaEventi' in modulo, false);
  // La lista esatta degli export di valore (i tipi non compaiono): una seconda
  // fonte dello stato con un altro nome non passerebbe inosservata. Chi
  // aggiunge un export lo aggiunge qui, e chi rivede vede che cosa entra.
  assert.deepEqual(Object.keys(modulo).sort(), ['senzaRitirati', 'testoEvento', 'vociAggiornamento']);
});

test('la chiusura ha una frase neutra: può arrivare senza scadenza', () => {
  // Correzioni della verifica e sospeso → chiuso: «prima della scadenza
  // prevista» era falso quando una scadenza non c'era (revisione finale, §18.10).
  for (const valore_dopo of [{ stato_bando: 'chiuso' }, null, 'chiuso']) {
    const testo = testoEvento(evento({ tipo: 'chiusura', campo: 'stato_bando', valore_dopo }));
    assert.equal(testo, 'Bando chiuso');
  }
});

test('la correzione della redazione dice lo stato nuovo', () => {
  // `bando_correggi_stato` (migrazione 14) scrive lo stato come stringa JSON;
  // si accetta anche la forma `{stato_bando: …}`.
  const correzione = (valore_dopo: unknown) =>
    testoEvento(evento({ tipo: 'correzione_redazionale', campo: 'stato_bando', valore_dopo }));
  assert.equal(correzione('aperto'), 'Stato corretto dalla redazione: aperto');
  assert.equal(correzione('sospeso'), 'Stato corretto dalla redazione: sospeso');
  assert.equal(correzione({ stato_bando: 'in apertura prossimamente' }),
    'Stato corretto dalla redazione: in apertura prossimamente');
  // Un valore che non è uno dei cinque stati non finisce in pagina.
  for (const strano of ['APERTO', 'scaduto', '<b>x</b>', null, {}, ['aperto'], 3]) {
    assert.equal(correzione(strano), 'Correzione della redazione', JSON.stringify(strano));
  }
});

test('il box toglie gli eventi ritirati, come lo storico', () => {
  // Prima il box mostrava una proroga ritirata e lo storico no (§18.10).
  const eventi = [
    evento({ id: 10, tipo: 'proroga', valore_dopo: { data_scadenza: '2026-12-01' } }),
    evento({ id: 11, tipo: 'ritiro', riferisce_a: 10 } as Partial<EventoConBando>),
    evento({ id: 12, tipo: 'faq', data_evento: '2026-09-19' }),
  ];
  assert.deepEqual(vociAggiornamento(eventi).map((v) => v.id), [12]);
});

test('senzaRitirati: toglie il ritirato e il ritiro, lascia il ritiro della scheda', () => {
  const righe = [
    { id: 1, tipo: 'proroga' },
    { id: '2', tipo: 'faq' },
    { id: 3, tipo: 'ritiro', riferisce_a: '1' },
    { id: 4, tipo: 'ritiro', riferisce_a: 2 },
    { id: 5, tipo: 'ritiro', riferisce_a: null },
    { id: 6, tipo: 'correzione_redazionale', riferisce_a: 1 },
  ];
  // L'id e `riferisce_a` possono arrivare come numero o come stringa.
  assert.deepEqual(senzaRitirati(righe).map((e) => e.id), [5, 6]);
  assert.deepEqual(senzaRitirati([]), []);
});

test('nessun evento, nessuna voce', () => {
  for (const vuoto of [null, undefined, []]) {
    assert.deepEqual(vociAggiornamento(vuoto), []);
  }
});
