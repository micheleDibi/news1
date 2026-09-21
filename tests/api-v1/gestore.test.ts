/**
 * gestore.ts + risorse.ts con una FonteDati finta: flusso HTTP completo senza DB.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { creaGestore, type DipendenzeGestore } from '../../src/lib/api-v1/gestore.ts';
import {
  CATEGORIE, DETTAGLIO_ARTICOLO, DETTAGLIO_BANDO, DETTAGLIO_SELEZIONE, ELENCO_ARTICOLI, ELENCO_BANDI, ELENCO_INTERPELLI,
  ELENCO_SELEZIONE, FEED, INDICE, NON_TROVATO, OPENAPI, type DescrittoreRotta, type DipendenzeRisorse,
  type RisultatoRisorsa,
} from '../../src/lib/api-v1/risorse.ts';
import { Limitatore } from '../../src/lib/api-v1/limitatore.ts';
import { Semaforo } from '../../src/lib/api-v1/semaforo.ts';
import { CacheRisposte } from '../../src/lib/api-v1/cache.ts';
import { ErroreDati } from '../../src/lib/api-v1/errori.ts';
import { costruisciRiferimentoCategorie, costruisciRiferimentoProfili } from '../../src/lib/api-v1/riferimenti.ts';
import type {
  FonteDati, NomeSelect, PianoQuery, RighePerSelect, RiferimentoCategorie, RiferimentoProfili,
  RigaArticolo, RigaInterpello, RigaSelezione, RigaBando,
} from '../../src/lib/api-v1/contratto.ts';

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

const { riferimento: CATEGORIE_RIF } = costruisciRiferimentoCategorie(
  [
    { slug: 'scuola', name: 'Scuola', color: 'scuola', order_id: 1 },
    { slug: 'universita', name: 'Università', color: 'universita', order_id: 2 },
  ],
  [{ slug: 'insegnanti', name: 'Insegnanti', parent_category_slug: 'scuola' }],
);
const PROFILI_RIF = costruisciRiferimentoProfili([
  { id: 'u1', full_name: 'Nome Reale Riservato', public_name: 'Redazione EduNews24', is_displayable: true },
  { id: 'u2', full_name: 'Giornalista Uno', public_name: 'G. Uno', is_displayable: true },
]);

function articolo(id: number, publishedAt: string, extra: Partial<RigaArticolo> = {}): RigaArticolo {
  return {
    id, slug: `articolo-${id}`, title: `Titolo ${id}`, title_summary: null, excerpt: `Sintesi ${id}`, summary: null,
    category_slug: 'scuola', secondary_category_slugs: ['insegnanti'], image_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/a.webp',
    thumbnail_url: '', video_url: '', video_duration: null, published_at: publishedAt, tags: ['a', 'b'],
    creator: 'Nome Reale Riservato', ...extra,
  };
}

const INTERPELLO: RigaInterpello = {
  id: 1636, interpello_name: 'Interpello supplenze AAAA', interpello_date: '2026-09-17T00:00:00',
  interpello_description: 'Descrizione', interpello_regione: 'Lazio', interpello_provincia: 'Roma',
  interpello_citta: 'Castel Madama', classe_concorso: 'AAAA', article_title: 'Castel Madama, interpello', article_subtitle: 'Sottotitolo',
};

const SELEZIONE: RigaSelezione = {
  id: 23258, slug: 'arpam-marche-29611', codice: '29611', titolo: 'AVVISO PUBBLICO', article_title: 'ARPAM Marche, avviso',
  article_subtitle: 'Domande entro il 6 ottobre 2026.', figura_ricercata: 'Collaboratore', num_posti: 1, tipo_procedura: 'colloquio',
  data_pubblicazione: '2026-09-20T22:01:00+00:00', data_scadenza: '2026-10-06T21:59:00+00:00', sedi: ['Marche', 'Ancona'],
  categorie: ['Concorso'], settori: [], enti_riferimento: ['ARPAM'], salary_min: null, salary_max: null, updated_at: '2026-09-21T06:04:01+00:00',
};

const BANDO: RigaBando = {
  id: 1120620, slug: 'italia-delle-donne', titolo: "L'Italia delle donne", titolo_breve: 'Avviso', descrizione_breve: 'Descrizione breve',
  ente_erogatore: 'Dipartimento', area_geografica: 'Nazionale', tematica: ['Cultura'], data_pubblicazione: null, data_apertura: null,
  data_scadenza: null, importo_totale_eur: null, importo_max_per_progetto_eur: null, stato_bando: 'aperto',
  created_at: '2026-09-14T16:03:02.418+00:00', updated_at: '2026-09-21T04:01:59+00:00',
  tipologia: { nome: 'Bandi nazionali' }, programma: null, modalita: [{ nome: 'Fondo perduto' }],
  bando_regioni: [{ regioni: { nome: 'Lazio', slug: 'lazio' } }], bando_settori: [{ settori: { nome: 'Arte' } }],
  bando_beneficiari: [], bando_codici_ateco: [],
};

// ---------------------------------------------------------------------------
// Fonte finta
// ---------------------------------------------------------------------------

class FonteFinta implements FonteDati {
  piani: PianoQuery[] = [];
  righe = new Map<NomeSelect, unknown[]>();
  errore: Error | null = null;

  async leggi<S extends NomeSelect>(piano: PianoQuery<S>, _segnale: AbortSignal): Promise<RighePerSelect[S][]> {
    this.piani.push(piano);
    if (this.errore) throw this.errore;
    const tutte = (this.righe.get(piano.select) ?? []) as RighePerSelect[S][];
    const limite = piano.operazioni.find((o) => o.tipo === 'limite');
    return tutte.slice(0, limite && limite.tipo === 'limite' ? limite.n : undefined);
  }
}

interface Ambiente {
  fonte: FonteFinta;
  adesso: { ms: number };
  dipendenze: DipendenzeGestore;
  registro: string[];
  categorie: { valore: RiferimentoCategorie | Error };
}

function ambiente(opzioni: { capacita?: number; valoriCorpus?: readonly string[] } = {}): Ambiente {
  const fonte = new FonteFinta();
  const adesso = { ms: Date.UTC(2026, 8, 21, 10, 0, 0) };
  const orologio = () => adesso.ms;
  const registro: string[] = [];
  const categorie: { valore: RiferimentoCategorie | Error } = { valore: CATEGORIE_RIF };
  const risorse: DipendenzeRisorse = {
    fonte,
    categorie: {
      async ottieni() { if (categorie.valore instanceof Error) throw categorie.valore; return categorie.valore; },
      seCaldo() { return categorie.valore instanceof Error ? null : categorie.valore; },
    },
    profili: {
      async ottieni(): Promise<RiferimentoProfili> { return PROFILI_RIF; },
      seCaldo() { return PROFILI_RIF; },
    },
    valoriRegioneCorpus: () => opzioni.valoriCorpus ?? [],
    limiteDichiarato: { requests: 60, window_seconds: 60 },
    registra: (evento, dettaglio) => { registro.push(`${evento} ${dettaglio ?? ''}`); },
  };
  const dipendenze: DipendenzeGestore = {
    risorse,
    limitatore: new Limitatore({ capacita: opzioni.capacita ?? 1000, ricaricaPerSecondo: 1, maxChiavi: 1000, orologio }),
    semaforo: new Semaforo({ slot: 4, coda: 8, attesaMs: 500 }),
    cache: new CacheRisposte<RisultatoRisorsa>({ maxVoci: 100, maxByte: 10_000_000, orologio, misura: (r) => r.corpo.length }),
    modalitaFiducia: 'diretta',
    politicaRateLimit: `${opzioni.capacita ?? 1000};w=1000`,
    orologio,
    registra: (evento, dettaglio) => { registro.push(`${evento} ${dettaglio ?? ''}`); },
  };
  return { fonte, adesso, dipendenze, registro, categorie };
}

async function chiama(
  amb: Ambiente,
  descrittore: DescrittoreRotta,
  percorsoEQuery: string,
  opzioni: { params?: Record<string, string | undefined>; metodo?: string; intestazioni?: Record<string, string>; ip?: string } = {},
): Promise<Response> {
  const url = new URL(percorsoEQuery, 'https://edunews24.it');
  const gestore = creaGestore(descrittore, amb.dipendenze);
  const contesto = {
    request: new Request(url, { method: opzioni.metodo ?? 'GET', headers: opzioni.intestazioni }),
    url,
    params: opzioni.params ?? {},
    clientAddress: opzioni.ip ?? '203.0.113.7',
  };
  if (opzioni.metodo === 'OPTIONS') return gestore.OPTIONS();
  if (opzioni.metodo && opzioni.metodo !== 'GET' && opzioni.metodo !== 'HEAD') return gestore.ALL(contesto);
  return gestore.GET(contesto);
}

function comuni(r: Response): void {
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  assert.equal(r.headers.get('X-Robots-Tag'), 'noindex');
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('elenco articoli: envelope, next, Link, has_more', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [
    articolo(3, '2026-09-21T07:18:28.177'), articolo(2, '2026-09-21T06:00:00.5'), articolo(1, '2026-09-20T08:53:20.936282'),
  ]);
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?limit=2&category=scuola');
  assert.equal(r.status, 200);
  comuni(r);
  assert.equal(r.headers.get('Content-Type'), 'application/json; charset=utf-8');
  const corpo = await r.json();
  assert.equal(corpo.data.length, 2);
  assert.equal(corpo.meta.count, 2);
  assert.equal(corpo.meta.has_more, true);
  assert.equal(corpo.meta.sort, '-published_at,-id');
  assert.deepEqual(corpo.meta.filters, { category: 'scuola', has_video: null, since: null, until: null });
  assert.equal(corpo.links.self, 'https://edunews24.it/api/v1/articles?category=scuola&limit=2');
  assert.match(corpo.links.next, /^https:\/\/edunews24\.it\/api\/v1\/articles\?category=scuola&limit=2&cursor=[A-Za-z0-9_-]+$/);
  assert.match(r.headers.get('Link') ?? '', /rel="next"/);
  assert.equal(corpo.data[0].published_at, '2026-09-21T09:18:28+02:00');
  assert.equal(corpo.data[0].author.name, 'Redazione EduNews24');
  assert.ok(!JSON.stringify(corpo).includes('Nome Reale Riservato'), 'fuga del nome reale');
  // il piano ha i predicati di pubblicazione e legge limit + 1
  const piano = amb.fonte.piani.at(-1)!;
  assert.ok(piano.operazioni.some((o) => o.tipo === 'filtro' && o.colonna === 'isdraft' && o.valore === 'false'));
  assert.deepEqual(piano.operazioni.at(-1), { tipo: 'limite', n: 3 });

  // pagina successiva: il cursore porta la chiave grezza dell'ultima riga letta
  const next = new URL(corpo.links.next);
  await chiama(amb, ELENCO_ARTICOLI, next.pathname + next.search);
  const keyset = amb.fonte.piani.at(-1)!.operazioni.find((o) => o.tipo === 'or');
  assert.deepEqual(keyset, { tipo: 'or', espressione: 'published_at.lt."2026-09-21T06:00:00.5",and(published_at.eq."2026-09-21T06:00:00.5",id.lt.2)' });
});

test('elenco senza altre righe: next null e has_more false', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(1, '2026-09-21T07:18:28.177')]);
  const corpo = await (await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles')).json();
  assert.equal(corpo.links.next, null);
  assert.equal(corpo.meta.has_more, false);
});

test('post-filtro di since: pagina corta ma next presente', async () => {
  const amb = ambiente();
  // since = 2026-09-21T09:00:00+02:00 = 07:00Z; la riga Roma 08:30 = 06:30Z va scartata
  amb.fonte.righe.set('articolo', [
    articolo(3, '2026-09-21T07:18:28.177'), articolo(2, '2026-09-21T08:30:00.123456'), articolo(1, '2026-09-21T07:05:00.1'),
  ]);
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?limit=2&since=2026-09-21T07:00:00Z');
  const corpo = await r.json();
  assert.deepEqual(corpo.data.map((a: { id: number }) => a.id), [3]);
  assert.equal(corpo.meta.count, 1);
  assert.equal(corpo.meta.has_more, true);
  assert.notEqual(corpo.links.next, null);
});

test('categoria sconosciuta: 400 con allowed; parametro sconosciuto: 400', async () => {
  const amb = ambiente();
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?category=sport');
  assert.equal(r.status, 400);
  assert.equal(r.headers.get('Content-Type'), 'application/problem+json; charset=utf-8');
  const corpo = await r.json();
  assert.equal(corpo.code, 'invalid-parameter');
  assert.deepEqual(corpo.errors[0].allowed, ['scuola', 'universita']);
  const r2 = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?constructor=1');
  assert.equal((await r2.json()).code, 'unknown-parameter');
  assert.equal(amb.fonte.piani.length, 0, 'nessuna query per richieste non valide');
});

test('cursore manomesso: 400 invalid-cursor con first', async () => {
  const amb = ambiente();
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?category=scuola&cursor=eyJ2IjoxfQ');
  assert.equal(r.status, 400);
  const corpo = await r.json();
  assert.equal(corpo.code, 'invalid-cursor');
  assert.equal(corpo.first, 'https://edunews24.it/api/v1/articles?category=scuola');
});

test('guasto del DB: 503 senza copia, 200 STALE con copia', async () => {
  const amb = ambiente();
  amb.fonte.errore = new ErroreDati('disponibilita', '57014');
  const r = await chiama(amb, ELENCO_INTERPELLI, '/api/v1/interpelli');
  assert.equal(r.status, 503);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
  assert.equal(r.headers.get('Retry-After'), '30');
  assert.equal((await r.json()).code, 'service-unavailable');

  amb.fonte.errore = null;
  amb.fonte.righe.set('interpello', [INTERPELLO]);
  assert.equal((await chiama(amb, ELENCO_INTERPELLI, '/api/v1/interpelli')).status, 200);
  amb.adesso.ms += 10 * 60_000; // oltre freschezza + swr
  amb.fonte.errore = new ErroreDati('disponibilita', null);
  const stantia = await chiama(amb, ELENCO_INTERPELLI, '/api/v1/interpelli');
  assert.equal(stantia.status, 200);
  assert.equal(stantia.headers.get('X-EduNews24-Cache'), 'STALE');
  assert.equal(stantia.headers.get('Cache-Control'), 'public, max-age=30, s-maxage=60');
});

test('errore di programmazione: 500 senza dettagli interni', async () => {
  const amb = ambiente();
  amb.fonte.errore = new ErroreDati('programmazione', '42703', 'column articles.updated_at does not exist');
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles');
  assert.equal(r.status, 500);
  const testo = await r.text();
  assert.ok(!testo.includes('updated_at') && !testo.includes('42703'));
  assert.ok(amb.registro.some((e) => e.startsWith('errore-interno')));
});

test('22007 con cursore: 400 invalid-cursor', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(3, '2026-09-21T07:18:28.177'), articolo(2, '2026-09-21T06:00:00.5')]);
  const corpo = await (await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles?limit=1')).json();
  amb.fonte.errore = new ErroreDati('data-non-valida', '22007');
  const next = new URL(corpo.links.next);
  const r = await chiama(amb, ELENCO_ARTICOLI, next.pathname + next.search);
  assert.equal(r.status, 400);
  assert.equal((await r.json()).code, 'invalid-cursor');
});

test('riferimento categorie non disponibile: 503, mai 200 vuoto', async () => {
  const amb = ambiente();
  amb.categorie.valore = new ErroreDati('disponibilita', null, 'riferimento categorie vuoto');
  for (const descrittore of [CATEGORIE, ELENCO_ARTICOLI]) {
    const r = await chiama(amb, descrittore, descrittore === CATEGORIE ? '/api/v1/categories' : '/api/v1/articles?category=scuola');
    assert.equal(r.status, 503, descrittore.nome);
  }
});

test('dettaglio: 200 con canonical, 404 se assente, 400 se id malformato', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(39382, '2026-09-21T07:18:28.177')]);
  const r = await chiama(amb, DETTAGLIO_ARTICOLO, '/api/v1/articles/39382', { params: { id: '39382' } });
  assert.equal(r.status, 200);
  const corpo = await r.json();
  assert.equal(corpo.data.id, 39382);
  assert.equal(corpo.links.html, 'https://edunews24.it/scuola/articolo-39382');
  assert.match(r.headers.get('Link') ?? '', /<https:\/\/edunews24\.it\/scuola\/articolo-39382>; rel="canonical"/);
  assert.equal(r.headers.get('Cache-Control'), 'public, max-age=300, s-maxage=900, stale-while-revalidate=900, stale-if-error=86400');
  // piano del dettaglio: predicati di pubblicazione e categorie valide
  const piano = amb.fonte.piani.at(-1)!;
  assert.ok(piano.operazioni.some((o) => o.tipo === 'filtro' && o.colonna === 'isdraft'));
  assert.ok(piano.operazioni.some((o) => o.tipo === 'filtro' && o.colonna === 'category_slug' && o.operatore === 'in'));

  amb.fonte.righe.set('articolo', []);
  const assente = await chiama(amb, DETTAGLIO_ARTICOLO, '/api/v1/articles/7', { params: { id: '7' } });
  assert.equal(assente.status, 404);
  assert.equal(assente.headers.get('Cache-Control'), 'public, max-age=60, s-maxage=60');
  const malformato = await chiama(amb, DETTAGLIO_ARTICOLO, '/api/v1/articles/abc', { params: { id: 'abc' } });
  assert.equal(malformato.status, 400);
  const conQuery = await chiama(amb, DETTAGLIO_ARTICOLO, '/api/v1/articles/7?x=1', { params: { id: '7' } });
  assert.equal((await conQuery.json()).code, 'unknown-parameter');
});

test('ETag e 304', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(1, '2026-09-21T07:18:28.177')]);
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles');
  const etag = r.headers.get('ETag')!;
  assert.match(etag, /^W\//);
  const n = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { intestazioni: { 'If-None-Match': etag } });
  assert.equal(n.status, 304);
  assert.equal(n.headers.get('ETag'), etag);
  comuni(n);
});

test('HEAD: stessi header del GET', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(1, '2026-09-21T07:18:28.177')]);
  const get = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles');
  const head = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { metodo: 'HEAD' });
  assert.equal(head.status, 200);
  for (const h of ['ETag', 'Cache-Control', 'Content-Type', 'Link', 'Access-Control-Allow-Origin', 'X-Robots-Tag']) {
    assert.equal(head.headers.get(h), get.headers.get(h), h);
  }
});

test('rate limit: 429 con Retry-After e RateLimit-*', async () => {
  const amb = ambiente({ capacita: 3 });
  amb.fonte.righe.set('articolo', []);
  for (let i = 0; i < 3; i++) assert.equal((await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles')).status, 200);
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles');
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
  assert.ok(Number(r.headers.get('Retry-After')) >= 1);
  assert.equal(r.headers.get('RateLimit-Remaining'), '0');
  assert.equal(r.headers.get('RateLimit-Policy'), '3;w=1000');
  assert.equal(r.headers.get('RateLimit-Limit'), '3');
  assert.equal((await r.json()).code, 'rate-limited');
  // un altro client non e' toccato
  assert.equal((await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { ip: '198.51.100.9' })).status, 200);
});

test('OPTIONS 204 senza consumo; metodi non ammessi 405', async () => {
  const amb = ambiente({ capacita: 1 });
  for (let i = 0; i < 5; i++) assert.equal((await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { metodo: 'OPTIONS' })).status, 204);
  const r = await chiama(amb, ELENCO_ARTICOLI, '/api/v1/articles', { metodo: 'POST' });
  assert.equal(r.status, 405);
  assert.equal(r.headers.get('Allow'), 'GET, HEAD, OPTIONS');
  assert.equal(r.headers.get('Cache-Control'), 'no-store');
});

test('percorso sconosciuto: 404 JSON senza DB', async () => {
  const amb = ambiente();
  const r = await chiama(amb, NON_TROVATO, '/api/v1/constructor');
  assert.equal(r.status, 404);
  assert.equal((await r.json()).instance, 'https://edunews24.it/api/v1/constructor');
  assert.equal(amb.fonte.piani.length, 0);
});

test('regione degli interpelli: valori del corpus solo se il registro li riconosce, sempre quotati', async () => {
  // I valori del corpus sono valori esatti del DB: entrano se il registro li attribuisce alla
  // regione richiesta (anche con spazi o caratteri strani, quotati da listaInPg), mai se
  // appartengono a un'altra regione o contengono caratteri di controllo.
  const amb = ambiente({ valoriCorpus: ['Lazio', 'Lazio")', 'Lombardia', 'Lazio ', '\u0000Lazio'] });
  amb.fonte.righe.set('interpello', [INTERPELLO]);
  const r = await chiama(amb, ELENCO_INTERPELLI, '/api/v1/interpelli?region=lazio');
  assert.equal(r.status, 200);
  const filtro = amb.fonte.piani.at(-1)!.operazioni.find((o) => o.tipo === 'filtro' && o.colonna === 'interpello_regione');
  assert.deepEqual(filtro, { tipo: 'filtro', colonna: 'interpello_regione', operatore: 'in', valore: '("Lazio","Lazio\\")","Lazio ")' });
});

test('selezione e bandi: status calcolato su oggi, chiave di cache con la data', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('selezione', [SELEZIONE]);
  amb.fonte.righe.set('bando', [BANDO]);
  amb.fonte.righe.set('bando-con-regione', [BANDO]);
  const oggi = await (await chiama(amb, ELENCO_SELEZIONE, '/api/v1/selezione-personale')).json();
  assert.equal(oggi.data[0].status, 'open');
  assert.equal(oggi.data[0].deadline_on, '2026-10-06');
  amb.adesso.ms = Date.UTC(2026, 9, 7, 10, 0, 0); // 7 ottobre: scaduto
  const dopo = await (await chiama(amb, ELENCO_SELEZIONE, '/api/v1/selezione-personale')).json();
  assert.equal(dopo.data[0].status, 'closed');
  const dettaglio = await (await chiama(amb, DETTAGLIO_SELEZIONE, '/api/v1/selezione-personale/23258', { params: { id: '23258' } })).json();
  assert.equal(dettaglio.data.type, 'selezione-personale');
  const bandi = await (await chiama(amb, ELENCO_BANDI, '/api/v1/bandi?region=lazio')).json();
  assert.equal(bandi.data[0].type, 'bando');
  assert.equal(amb.fonte.piani.at(-1)!.select, 'bando-con-regione');
});

test('categorie, indice, openapi', async () => {
  const amb = ambiente();
  const cat = await chiama(amb, CATEGORIE, '/api/v1/categories');
  assert.equal(cat.status, 200);
  const corpo = await cat.json();
  assert.equal(corpo.data[0].slug, 'scuola');
  assert.equal(corpo.data[0].color, '#2D6A4F');
  assert.equal(corpo.meta.count, 2);
  const indice = await chiama(amb, INDICE, '/api/v1?qualsiasi=1');
  assert.equal(indice.status, 200);
  assert.match(indice.headers.get('Link') ?? '', /rel="api-catalog"/);
  const openapi = await chiama(amb, OPENAPI, '/api/v1/openapi.json');
  assert.equal(openapi.headers.get('Content-Type'), 'application/vnd.oai.openapi+json;version=3.1');
  assert.equal((await openapi.json()).openapi, '3.1.0');
});

test('feed: JSON e RSS, 404 per percorsi e categorie inesistenti', async () => {
  const amb = ambiente();
  amb.fonte.righe.set('articolo', [articolo(1, '2026-09-21T07:18:28.177')]);
  const json = await chiama(amb, FEED, '/api/v1/feeds/articles/scuola.json', { params: { percorso: 'articles/scuola.json' } });
  assert.equal(json.status, 200);
  assert.equal(json.headers.get('Content-Type'), 'application/feed+json; charset=utf-8');
  const feed = await json.json();
  assert.equal(feed.version, 'https://jsonfeed.org/version/1.1');
  assert.equal(feed.items.length, 1);
  const piano = amb.fonte.piani.at(-1)!;
  assert.ok(piano.operazioni.some((o) => o.tipo === 'filtro' && o.colonna === 'category_slug' && o.valore === 'scuola'));
  const rss = await chiama(amb, FEED, '/api/v1/feeds/articles.xml', { params: { percorso: 'articles.xml' } });
  assert.equal(rss.headers.get('Content-Type'), 'application/rss+xml; charset=utf-8');
  assert.match(await rss.text(), /^<\?xml/);
  const assente = await chiama(amb, FEED, '/api/v1/feeds/articles/sport.json', { params: { percorso: 'articles/sport.json' } });
  assert.equal(assente.status, 404);
  const malformato = await chiama(amb, FEED, '/api/v1/feeds/constructor.json', { params: { percorso: 'constructor.json' } });
  assert.equal(malformato.status, 404);
  const radice = await chiama(amb, FEED, '/api/v1/feeds', { params: { percorso: undefined } });
  assert.equal(radice.status, 404);
});

test('correzioni della revisione: id oltre int4, query lunghe sui dettagli, instance con //', async () => {
  const amb = ambiente();
  const r = await chiama(amb, DETTAGLIO_BANDO, '/api/v1/bandi/2147483648', { params: { id: '2147483648' } });
  assert.equal(r.status, 404);
  assert.equal(r.headers.get('Cache-Control'), 'public, max-age=60, s-maxage=60');
  assert.equal(amb.fonte.piani.length, 0, 'nessuna query per un id impossibile');
  const lunga = '?' + Array.from({ length: 700 }, (_, i) => `p${i}=1`).join('&');
  for (const [descrittore, percorso, params] of [
    [DETTAGLIO_ARTICOLO, '/api/v1/articles/5', { id: '5' }],
    [CATEGORIE, '/api/v1/categories', {}],
  ] as const) {
    const risposta = await chiama(amb, descrittore, percorso + lunga, { params });
    assert.equal(risposta.status, 400);
    const corpo = await risposta.json();
    assert.equal(corpo.code, 'invalid-parameter');
    assert.deepEqual(corpo.errors.map((e: { parameter: string }) => e.parameter), ['(query)']);
  }
  // Astro passa il pathname cosi' com'e': '//api/v1/x'
  const doppio = await chiama(amb, NON_TROVATO, 'https://edunews24.it//api/v1/x');
  assert.equal((await doppio.json()).instance, 'https://edunews24.it/api/v1/x');
});
