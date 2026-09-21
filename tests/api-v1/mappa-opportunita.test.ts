/**
 * mappa-opportunita.ts: interpelli, selezione del personale e bandi (piano §3.9).
 * Tre fixture complete, ripieghi, regole S e B con `oggi` fissato, scadenze
 * implausibili, `national`, embed come oggetto o come array, colonne vietate.
 * Gira con TZ=Asia/Kathmandu: nessun risultato deve dipendere dal fuso del processo.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mappaBando, mappaInterpello, mappaSelezione, regioniDaValori,
} from '../../src/lib/api-v1/mappa-opportunita.ts';
import { slugInterpello } from '../../src/lib/liste/slug-interpello.ts';
import {
  BANDO_COMPLETO, COLONNE_VIETATE_BANDO, COLONNE_VIETATE_INTERPELLO, COLONNE_VIETATE_SELEZIONE, INTERPELLO_COMPLETO,
  SELEZIONE_COMPLETA,
} from './fixture/opportunita-complete.ts';
import type {
  BandoDto, InterpelloDto, RigaBando, RigaInterpello, RigaSelezione, SelezioneDto,
} from '../../src/lib/api-v1/contratto.ts';

const OGGI = '2026-09-21';

const CHIAVI_BASE = [
  'type', 'id', 'slug', 'url', 'title', 'summary', 'section', 'published_at', 'updated_at', 'deadline_on',
  'deadline_at', 'status', 'regions', 'national', 'details',
];

function interpello(extra: Partial<RigaInterpello> = {}): InterpelloDto {
  const dto = mappaInterpello({ ...INTERPELLO_COMPLETO, ...extra });
  assert.ok(dto !== null, 'interpello atteso valido');
  return dto;
}

function selezione(extra: Partial<RigaSelezione> = {}, oggi = OGGI): SelezioneDto {
  const dto = mappaSelezione({ ...SELEZIONE_COMPLETA, ...extra }, oggi);
  assert.ok(dto !== null, 'selezione attesa valida');
  return dto;
}

function bando(extra: Partial<RigaBando> = {}, oggi = OGGI): BandoDto {
  const dto = mappaBando({ ...BANDO_COMPLETO, ...extra }, oggi);
  assert.ok(dto !== null, 'bando atteso valido');
  return dto;
}

// ---------------------------------------------------------------------------
// Regioni
// ---------------------------------------------------------------------------

test('regioniDaValori: grafie diverse, duplicati, valori estranei, ordine del registro', () => {
  assert.deepEqual(regioniDaValori([
    'Lazio', 'Emilia Romagna', 'emilia-romagna', 'Emilia-Romagna', 7, null, 'Atlantide', 'Abruzzo',
    'Trentino-Alto Adige/Südtirol', "Valle d'Aosta/Vallée d'Aoste",
  ]), [
    { slug: 'abruzzo', name: 'Abruzzo' },
    { slug: 'emilia-romagna', name: 'Emilia-Romagna' },
    { slug: 'lazio', name: 'Lazio' },
    { slug: 'trentino-alto-adige', name: 'Trentino-Alto Adige' },
    { slug: 'valle-d-aosta', name: "Valle d'Aosta" },
  ]);
  assert.deepEqual(regioniDaValori([]), []);
  assert.deepEqual(regioniDaValori(['', 'constructor', '__proto__', 'Nazionale']), []);
});

// ---------------------------------------------------------------------------
// Interpelli
// ---------------------------------------------------------------------------

const SLUG_INTERPELLO = 'interpello-supplenza-aaaa-posto-comune-interpelli-pubblicati-da-bologna-emilia-romagna-1636';

test('interpello: fixture completa', () => {
  const dto = interpello();
  assert.deepEqual(Object.keys(dto), CHIAVI_BASE);
  assert.deepEqual(dto, {
    type: 'interpello',
    id: 1636,
    slug: SLUG_INTERPELLO,
    url: `https://edunews24.it/interpelli/${SLUG_INTERPELLO}`,
    title: 'Casalecchio di Reno, interpello per una supplenza AAAA',
    summary: 'L\'istituto cerca un docente per una supplenza fino al 30 giugno.',
    section: { slug: 'interpelli', name: 'Interpelli scuola', color: '#DC2626', url: 'https://edunews24.it/interpelli' },
    published_at: '2026-09-17T00:00:00+02:00',
    updated_at: null,
    deadline_on: null,
    deadline_at: null,
    status: null,
    regions: [{ slug: 'emilia-romagna', name: 'Emilia-Romagna' }],
    national: false,
    details: {
      official_title: 'Interpello supplenza AAAA posto comune',
      competition_class: 'AAAA',
      province: 'Bologna',
      city: 'Casalecchio di Reno',
    },
  });
  assert.deepEqual(Object.keys(dto.details), ['official_title', 'competition_class', 'province', 'city']);
  assert.deepEqual(Object.keys(dto.section), ['slug', 'name', 'color', 'url']);
});

test('interpello: lo slug e\' quello del sito, calcolato sui valori grezzi', () => {
  assert.equal(slugInterpello({
    id: 1636,
    interpello_name: INTERPELLO_COMPLETO.interpello_name as string,
    interpello_provincia: INTERPELLO_COMPLETO.interpello_provincia as string,
    interpello_citta: INTERPELLO_COMPLETO.interpello_citta as string,
    interpello_regione: INTERPELLO_COMPLETO.interpello_regione as string,
  }), SLUG_INTERPELLO);
  // provincia assente -> citta'; valori non stringa ignorati come null
  assert.equal(interpello({ interpello_provincia: null }).slug,
    'interpello-supplenza-aaaa-posto-comune-interpelli-pubblicati-da-casalecchio-di-reno-emilia-romagna-1636');
  assert.equal(interpello({ interpello_name: 42, interpello_provincia: ['x'], interpello_citta: null, interpello_regione: null }).slug,
    '1636');
});

test('interpello: ripieghi di titolo e sintesi', () => {
  const senzaArticolo = interpello({ article_title: '  ', article_subtitle: null });
  assert.equal(senzaArticolo.title, 'Interpello supplenza AAAA posto comune');
  assert.equal(senzaArticolo.summary, 'Descrizione & dettagli dell\'interpello');
  assert.equal(interpello({ article_subtitle: null, interpello_description: null }).summary, null);
  assert.equal(mappaInterpello({ ...INTERPELLO_COMPLETO, article_title: null, interpello_name: null }), null);
});

test('interpello: nome = URL spaggiari -> official_title null, titolo da article_title', () => {
  const url = 'https://web.spaggiari.eu/sif/app/default/bacheca_utente.php?action=file_download&com_id=123456';
  const dto = interpello({ interpello_name: url, interpello_description: url, article_subtitle: null });
  assert.equal(dto.details.official_title, null);
  assert.equal(dto.title, 'Casalecchio di Reno, interpello per una supplenza AAAA');
  assert.equal(dto.summary, null);
  // lo slug (e quindi l'URL della scheda) usa il valore grezzo, come il sito: ma nessun link esce
  assert.match(dto.slug, /^https-web-spaggiari-eu-/);
  assert.equal(JSON.stringify(dto).includes('web.spaggiari.eu'), false);
  assert.equal(mappaInterpello({ ...INTERPELLO_COMPLETO, interpello_name: url, article_title: null }), null);
});

test('interpello: province e citta\' senza il prefisso "Interpelli Pubblicati Da:"', () => {
  const casi: Array<[unknown, string | null]> = [
    ['Interpelli Pubblicati Da: Roma', 'Roma'],
    ['Interpelli Pubblicati Da:Roma', 'Roma'],
    ['interpelli pubblicati da:   Roma  ', 'Roma'],
    ['  Interpelli Pubblicati Da: Roma', 'Roma'],
    ['Interpelli Pubblicati Da:', null],
    ['Roma', 'Roma'],
    ['Provincia di Interpelli Pubblicati Da: Roma', 'Provincia di Interpelli Pubblicati Da: Roma'],
    [null, null],
    [12, null],
  ];
  for (const [valore, atteso] of casi) {
    const dto = interpello({ interpello_provincia: valore, interpello_citta: valore });
    assert.equal(dto.details.province, atteso, String(valore));
    assert.equal(dto.details.city, atteso, String(valore));
  }
});

test('interpello: righe scartate e regioni', () => {
  for (const extra of [
    { id: null }, { id: '1636' }, { id: 0 }, { id: 3.5 },
    { interpello_date: null }, { interpello_date: '17/09/2026' }, { interpello_date: '2026-02-30T00:00:00' },
  ] as Partial<RigaInterpello>[]) {
    assert.equal(mappaInterpello({ ...INTERPELLO_COMPLETO, ...extra }), null, JSON.stringify(extra));
  }
  assert.deepEqual(interpello({ interpello_regione: null }).regions, []);
  assert.deepEqual(interpello({ interpello_regione: 'Trentino-Alto Adige/Südtirol' }).regions,
    [{ slug: 'trentino-alto-adige', name: 'Trentino-Alto Adige' }]);
  assert.equal(interpello({ interpello_regione: 'Nazionale' }).national, false);
  // mezzanotte di Roma anche in inverno
  assert.equal(interpello({ interpello_date: '2026-01-15T00:00:00' }).published_at, '2026-01-15T00:00:00+01:00');
});

// ---------------------------------------------------------------------------
// Selezione del personale
// ---------------------------------------------------------------------------

test('selezione: fixture completa', () => {
  const dto = selezione();
  assert.deepEqual(Object.keys(dto), CHIAVI_BASE);
  assert.deepEqual(dto, {
    type: 'selezione-personale',
    id: 23258,
    slug: 'arpam-marche-avviso-pubblico-29611',
    url: 'https://edunews24.it/selezione-personale/arpam-marche-avviso-pubblico-29611',
    title: 'ARPAM Marche, avviso pubblico per Collaboratore Tecnico Professionale',
    summary: 'Domande entro il 6 ottobre 2026.',
    section: {
      slug: 'selezione-personale', name: 'Concorsi e selezioni pubbliche', color: '#CA8A04',
      url: 'https://edunews24.it/selezione-personale',
    },
    published_at: '2026-09-21T00:01:00+02:00',
    updated_at: '2026-09-21T08:04:01+02:00',
    deadline_on: '2026-10-06',
    deadline_at: '2026-10-06T23:59:00+02:00',
    status: 'open',
    regions: [{ slug: 'marche', name: 'Marche' }],
    national: false,
    details: {
      official_title: 'AVVISO PUBBLICO, PER COLLOQUIO, PER COLLABORATORE TECNICO PROFESSIONALE',
      code: '29611',
      position: 'Collaboratore Tecnico Professionale',
      positions_count: 1,
      procedure_type: 'COLLOQUIO',
      categories: ['Concorso'],
      sectors: [],
      organizations: ['Agenzia Regionale per la Protezione dell\'Ambiente delle Marche'],
      locations: ['Marche', 'Ancona', 'Macerata'],
      salary_min: 1800.5,
      salary_max: 2400,
    },
  });
  assert.deepEqual(Object.keys(dto.details), [
    'official_title', 'code', 'position', 'positions_count', 'procedure_type', 'categories', 'sectors',
    'organizations', 'locations', 'salary_min', 'salary_max',
  ]);
});

test('selezione: ripieghi di titolo e sintesi, righe scartate', () => {
  const dto = selezione({ article_title: null, article_subtitle: '' });
  assert.equal(dto.title, 'AVVISO PUBBLICO, PER COLLOQUIO, PER COLLABORATORE TECNICO PROFESSIONALE');
  assert.equal(dto.summary, null);
  for (const extra of [
    { article_title: null, titolo: null }, { id: null }, { id: -4 }, { slug: null }, { slug: '   ' }, { slug: '..' },
    { slug: ' . ' }, { data_pubblicazione: null }, { data_pubblicazione: '2026-09-20' },
  ] as Partial<RigaSelezione>[]) {
    assert.equal(mappaSelezione({ ...SELEZIONE_COMPLETA, ...extra }, OGGI), null, JSON.stringify(extra));
  }
  const conSpazi = selezione({ slug: '  avviso con spazi ' });
  assert.equal(conSpazi.slug, 'avviso con spazi');
  assert.equal(conSpazi.url, 'https://edunews24.it/selezione-personale/avviso%20con%20spazi');
});

test('regola S: il giorno della scadenza e\' aperto, il giorno dopo chiuso', () => {
  const casi: Array<[string, string, string]> = [
    // data_scadenza, deadline_on (giorno UTC come il sito), deadline_at
    ['2026-10-06T21:59:00+00:00', '2026-10-06', '2026-10-06T23:59:00+02:00'],
    ['2026-10-06T22:00:00+00:00', '2026-10-06', '2026-10-07T00:00:00+02:00'],
    ['2026-10-06T22:59:00+00:00', '2026-10-06', '2026-10-07T00:59:00+02:00'],
    ['2026-10-06T10:00:00+00:00', '2026-10-06', '2026-10-06T12:00:00+02:00'],
  ];
  for (const [scadenza, giorno, istante] of casi) {
    const ilGiorno = selezione({ data_scadenza: scadenza }, '2026-10-06');
    assert.equal(ilGiorno.deadline_on, giorno, scadenza);
    assert.equal(ilGiorno.deadline_at, istante, scadenza);
    assert.equal(ilGiorno.status, 'open', `${scadenza} il giorno D`);
    assert.equal(selezione({ data_scadenza: scadenza }, '2026-10-05').status, 'open', `${scadenza} il giorno D-1`);
    assert.equal(selezione({ data_scadenza: scadenza }, '2026-10-07').status, 'closed', `${scadenza} il giorno D+1`);
  }
  // ora solare
  assert.equal(selezione({ data_scadenza: '2026-12-15T22:59:00+00:00' }).deadline_at, '2026-12-15T23:59:00+01:00');
});

test('regola S: scadenza assente -> tutto null; implausibile -> date null e open', () => {
  for (const assente of [null, '', 'domani', 12345]) {
    const dto = selezione({ data_scadenza: assente });
    assert.deepEqual([dto.deadline_on, dto.deadline_at, dto.status], [null, null, null], String(assente));
  }
  for (const implausibile of ['5026-01-01T00:00:00+00:00', '2099-12-30T00:00:00+00:00', '2034-09-21T00:00:00+00:00']) {
    const dto = selezione({ data_scadenza: implausibile }, '2100-01-01');
    assert.deepEqual([dto.deadline_on, dto.deadline_at, dto.status], [null, null, 'open'], implausibile);
  }
  // sei anni: plausibile
  const seiAnni = selezione({ data_scadenza: '2032-09-20T21:59:00+00:00' });
  assert.equal(seiAnni.deadline_on, '2032-09-20');
  assert.equal(seiAnni.status, 'open');
});

test('selezione: national solo con "Nazionale" esatto; locations senza "Nazionale"', () => {
  const nazionale = selezione({ sedi: ['Nazionale'] });
  assert.equal(nazionale.national, true);
  assert.deepEqual(nazionale.regions, []);
  assert.deepEqual(nazionale.details.locations, []);
  const mista = selezione({ sedi: ['Nazionale', 'Lazio', 'Roma', 'Emilia Romagna'] });
  assert.equal(mista.national, true);
  assert.deepEqual(mista.regions, [{ slug: 'emilia-romagna', name: 'Emilia-Romagna' }, { slug: 'lazio', name: 'Lazio' }]);
  assert.deepEqual(mista.details.locations, ['Lazio', 'Roma', 'Emilia Romagna']);
  for (const sedi of [['nazionale'], ['NAZIONALE'], [' Nazionale '], 'Nazionale', null]) {
    assert.equal(selezione({ sedi }).national, false, JSON.stringify(sedi));
  }
  assert.deepEqual(selezione({ sedi: 'Lazio' }).regions, []);
});

test('selezione: details con valori anomali', () => {
  const dto = selezione({
    num_posti: '3', tipo_procedura: '  concorso &amp; titoli ', categorie: 'Concorso', settori: ['Sanità', 'Sanità', null],
    enti_riferimento: null, salary_min: 'abc', salary_max: Number.POSITIVE_INFINITY, codice: 29611, figura_ricercata:
      'https://www.inpa.gov.it/bandi-e-avvisi/dettaglio',
  });
  assert.equal(dto.details.positions_count, 3);
  assert.equal(dto.details.procedure_type, 'CONCORSO & TITOLI');
  assert.deepEqual(dto.details.categories, []);
  assert.deepEqual(dto.details.sectors, ['Sanità']);
  assert.deepEqual(dto.details.organizations, []);
  assert.equal(dto.details.salary_min, null);
  assert.equal(dto.details.salary_max, null);
  assert.equal(dto.details.code, null);
  assert.equal(dto.details.position, null);
  for (const posti of [0, -2, 1.5, 'tre', null]) {
    assert.equal(selezione({ num_posti: posti }).details.positions_count, null, String(posti));
  }
  assert.equal(selezione({ salary_min: ' 1500 ' }).details.salary_min, 1500);
  assert.equal(selezione({ updated_at: null }).updated_at, null);
  assert.equal(selezione({ tipo_procedura: null }).details.procedure_type, null);
});

// ---------------------------------------------------------------------------
// Bandi
// ---------------------------------------------------------------------------

test('bando: fixture completa', () => {
  const dto = bando();
  assert.deepEqual(Object.keys(dto), CHIAVI_BASE);
  assert.deepEqual(dto, {
    type: 'bando',
    id: 1120620,
    slug: 'litalia-delle-donne',
    url: 'https://edunews24.it/bandi/litalia-delle-donne',
    title: 'L\'Italia delle donne',
    summary: 'Contributi a fondo perduto per progetti culturali sulla storia delle donne.',
    section: { slug: 'bandi', name: 'Bandi e finanziamenti pubblici', color: '#795548', url: 'https://edunews24.it/bandi' },
    published_at: '2026-09-14T18:03:02+02:00',
    updated_at: '2026-09-21T06:01:59+02:00',
    deadline_on: '2026-10-31',
    deadline_at: null,
    status: 'open',
    regions: [
      { slug: 'abruzzo', name: 'Abruzzo' },
      { slug: 'lazio', name: 'Lazio' },
      { slug: 'valle-d-aosta', name: 'Valle d\'Aosta' },
    ],
    national: true,
    details: {
      short_title: 'Avviso Italia delle donne',
      issuer: 'Dipartimento per le pari opportunità',
      geographic_area: 'Nazionale',
      topics: ['Cultura', 'Pari opportunità'],
      kind: 'Bandi nazionali',
      program: 'PNRR',
      funding_method: 'Fondo perduto',
      sectors: ['Arte', 'Turismo'],
      beneficiaries: ['Associazioni', 'Enti del terzo settore'],
      ateco_codes: [
        { code: '85.52', description: 'Formazione culturale' },
        { code: '90.01', description: 'Rappresentazioni artistiche' },
      ],
      total_amount_eur: 1500000,
      max_amount_per_project_eur: 50000,
      opens_on: '2026-09-15',
      source_published_on: '2026-09-10',
    },
  });
  assert.deepEqual(Object.keys(dto.details), [
    'short_title', 'issuer', 'geographic_area', 'topics', 'kind', 'program', 'funding_method', 'sectors',
    'beneficiaries', 'ateco_codes', 'total_amount_eur', 'max_amount_per_project_eur', 'opens_on', 'source_published_on',
  ]);
  for (const a of dto.details.ateco_codes) assert.deepEqual(Object.keys(a), ['code', 'description']);
});

test('regola B: stato del sito (aperto, chiuso, in apertura) e scadenza passata', () => {
  assert.equal(bando({ stato_bando: 'aperto' }).status, 'open');
  assert.equal(bando({ stato_bando: 'chiuso' }).status, 'closed');
  // domanda 8: in apertura anche con data_apertura gia' passata, come il sito
  assert.equal(bando({ stato_bando: 'in apertura prossimamente', data_apertura: '2026-01-01' }).status, 'upcoming');
  assert.equal(bando({ stato_bando: 'sconosciuto' }).status, null);
  assert.equal(bando({ stato_bando: null, data_scadenza: null }).status, null);
  assert.equal(bando({ stato_bando: 'APERTO' }).status, null);
  // la scadenza passata chiude qualunque stato; il giorno stesso e' ancora aperto
  assert.equal(bando({ stato_bando: 'aperto', data_scadenza: '2026-09-20' }).status, 'closed');
  assert.equal(bando({ stato_bando: 'aperto', data_scadenza: '2026-09-21' }).status, 'open');
  assert.equal(bando({ stato_bando: 'aperto', data_scadenza: '2026-09-21' }, '2026-09-22').status, 'closed');
  assert.equal(bando({ stato_bando: 'in apertura prossimamente', data_scadenza: '2026-09-01' }).status, 'closed');
  assert.equal(bando({ stato_bando: null, data_scadenza: '2026-09-01' }).status, 'closed');
});

test('bando: scadenza non valida o implausibile -> deadline_on null', () => {
  assert.equal(bando({ data_scadenza: '2099-12-30' }).deadline_on, null);
  assert.equal(bando({ data_scadenza: '2099-12-30' }).status, 'open');
  assert.equal(bando({ data_scadenza: '5026-10-31' }).deadline_on, null);
  assert.equal(bando({ data_scadenza: '2026-02-30' }).deadline_on, null);
  assert.equal(bando({ data_scadenza: '31/10/2026' }).deadline_on, null);
  assert.equal(bando({ data_scadenza: '2026-10-31T00:00:00+00:00' }).deadline_on, null);
  assert.equal(bando({ data_scadenza: null }).deadline_on, null);
  assert.equal(bando({ data_scadenza: '2032-10-31' }).deadline_on, '2032-10-31');
  for (const v of [bando({ data_scadenza: '2026-10-31' }), bando({ data_scadenza: null })]) assert.equal(v.deadline_at, null);
});

test('bando: national da area_geografica, senza distinguere le maiuscole', () => {
  for (const area of ['Nazionale', 'nazionale', ' NAZIONALE ']) assert.equal(bando({ area_geografica: area }).national, true, area);
  for (const area of ['Nazionale (isole minori marine)', 'Regionale', null, 7]) {
    assert.equal(bando({ area_geografica: area }).national, false, String(area));
  }
});

test('bando: embed come oggetto, come array, vuoti o malformati', () => {
  const oggetto = bando({ tipologia: { nome: 'A' }, programma: { nome: 'B' }, modalita: { nome: 'C' } });
  assert.deepEqual([oggetto.details.kind, oggetto.details.program, oggetto.details.funding_method], ['A', 'B', 'C']);
  const array = bando({ tipologia: [{ nome: 'A' }], programma: [{ nome: null }, { nome: 'B2' }], modalita: [] });
  assert.deepEqual([array.details.kind, array.details.program, array.details.funding_method], ['A', 'B2', null]);
  const assenti = bando({ tipologia: null, programma: 'PNRR', modalita: { nome: 42 } });
  assert.deepEqual([assenti.details.kind, assenti.details.program, assenti.details.funding_method], [null, null, null]);

  const giunzioniOggetto = bando({
    bando_regioni: { regioni: { nome: 'Lazio', slug: 'lazio' } },
    bando_settori: { settori: [{ nome: 'Zootecnia' }, { nome: 'Agricoltura' }] },
    bando_beneficiari: null,
    bando_codici_ateco: { codici_ateco: [{ codice: '01.11', descrizione: null }] },
  });
  assert.deepEqual(giunzioniOggetto.regions, [{ slug: 'lazio', name: 'Lazio' }]);
  assert.deepEqual(giunzioniOggetto.details.sectors, ['Agricoltura', 'Zootecnia']);
  assert.deepEqual(giunzioniOggetto.details.beneficiaries, []);
  assert.deepEqual(giunzioniOggetto.details.ateco_codes, [{ code: '01.11', description: null }]);

  const malformate = bando({
    bando_regioni: [null, 'Lazio', { regioni: null }, { regioni: { nome: 'Atlantide', slug: 'atlantide' } }, { regioni: { nome: 'Molise' } }],
    bando_settori: [{ settori: { nome: '  ' } }, { altro: { nome: 'X' } }, { settori: { nome: 'Èlite' } }, { settori: { nome: 'elite' } }],
    bando_codici_ateco: 'non un array',
  });
  assert.deepEqual(malformate.regions, [{ slug: 'molise', name: 'Molise' }]);
  assert.deepEqual(malformate.details.sectors, ['elite', 'Èlite']);
  assert.deepEqual(malformate.details.ateco_codes, []);
});

test('bando: importi, date della fonte, righe scartate', () => {
  const dto = bando({
    importo_totale_eur: 1500000.5, importo_max_per_progetto_eur: '50000', data_apertura: '2026-13-01', data_pubblicazione: null,
  });
  assert.equal(dto.details.total_amount_eur, null);
  assert.equal(dto.details.max_amount_per_project_eur, null);
  assert.equal(dto.details.opens_on, null);
  assert.equal(dto.details.source_published_on, null);
  assert.equal(bando({ importo_totale_eur: 0 }).details.total_amount_eur, 0);
  assert.equal(bando({ updated_at: 'ieri' }).updated_at, null);
  for (const extra of [
    { id: null }, { id: '1120620' }, { slug: null }, { slug: '' }, { slug: '..' }, { titolo: null }, { titolo: '<p></p>' },
    { created_at: null }, { created_at: '2026-09-14' },
  ] as Partial<RigaBando>[]) {
    assert.equal(mappaBando({ ...BANDO_COMPLETO, ...extra }, OGGI), null, JSON.stringify(extra));
  }
});

// ---------------------------------------------------------------------------
// Colonne vietate
// ---------------------------------------------------------------------------

function nessunaFuga(dto: object, vietate: Record<string, unknown>, descrizione: string): void {
  const json = JSON.stringify(dto);
  for (const [colonna, valore] of Object.entries(vietate)) {
    assert.equal(Object.keys(dto).includes(colonna) && colonna !== 'status', false, `${descrizione}: colonna ${colonna}`);
    const testi = typeof valore === 'string' ? [valore] : [JSON.stringify(valore)];
    for (const testo of testi) {
      if (testo.length < 5 || ['completed', 'single', 'diretto'].includes(testo)) continue;
      assert.equal(json.includes(testo), false, `${descrizione}: valore di ${colonna}`);
    }
  }
  assert.equal(json.includes('fonte-vietata'), false, `${descrizione}: link a una fonte`);
  assert.equal(json.includes('web.spaggiari.eu'), false, `${descrizione}: link a spaggiari`);
}

test('colonne vietate: mai in uscita, nemmeno se la riga le contiene', () => {
  const i = mappaInterpello({ ...INTERPELLO_COMPLETO, ...COLONNE_VIETATE_INTERPELLO } as RigaInterpello);
  const s = mappaSelezione({ ...SELEZIONE_COMPLETA, ...COLONNE_VIETATE_SELEZIONE } as RigaSelezione, OGGI);
  const b = mappaBando({ ...BANDO_COMPLETO, ...COLONNE_VIETATE_BANDO } as RigaBando, OGGI);
  assert.ok(i !== null && s !== null && b !== null);
  assert.deepEqual(Object.keys(i), CHIAVI_BASE);
  assert.deepEqual(Object.keys(s), CHIAVI_BASE);
  assert.deepEqual(Object.keys(b), CHIAVI_BASE);
  nessunaFuga(i, COLONNE_VIETATE_INTERPELLO, 'interpello');
  nessunaFuga(s, COLONNE_VIETATE_SELEZIONE, 'selezione');
  nessunaFuga(b, COLONNE_VIETATE_BANDO, 'bando');
  // `status` esposto e' solo quello calcolato, mai la colonna interna
  assert.equal(i.status, null);
  assert.equal(s.status, 'open');
  assert.equal(JSON.stringify(s).includes('OPEN'), false);
  assert.equal(JSON.stringify(s).includes('HTML-'), false);
});

test('nessun risultato dipende dal fuso del processo (la suite gira con TZ=Asia/Kathmandu)', () => {
  assert.equal(interpello().published_at, '2026-09-17T00:00:00+02:00');
  assert.equal(selezione().published_at, '2026-09-21T00:01:00+02:00');
  assert.equal(bando().published_at, '2026-09-14T18:03:02+02:00');
});
