/**
 * filtri.ts: piano delle query. Le condizioni di pubblicazione devono esserci in
 * OGNI modo (elenco, dettaglio, feed), e nessun valore grezzo del client arriva a PostgREST.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  pianoQuery, pianoRiferimento, applicaPiano, listaInPg, letteraleArrayPg, condizioneKeyset,
  type ContestoPiano, type CostruttoreQuery,
} from '../../src/lib/api-v1/filtri.ts';
import { validaQueryElenco, type FiltriElenco } from '../../src/lib/api-v1/parametri.ts';
import { FONTI_BANDI } from '../../src/lib/bandi/pubblicazione.ts';
import type { Operazione, Risorsa } from '../../src/lib/api-v1/contratto.ts';

function filtri(risorsa: Risorsa, query: string): FiltriElenco {
  const e = validaQueryElenco(risorsa, new URLSearchParams(query), query.length);
  if (!e.ok) throw new Error(query);
  return e.filtri;
}

const CATEGORIE = ['scuola', 'universita'];

function contesto(extra: Partial<ContestoPiano>): ContestoPiano {
  return {
    modo: 'elenco', filtri: null, slugCategorieValide: CATEGORIE, categoria: null, valoriRegione: null,
    oggi: '2026-09-21', dopo: null, id: null, righe: 21, ...extra,
  };
}

const filtroOp = (ops: readonly Operazione[], colonna: string) =>
  ops.filter((o): o is Extract<Operazione, { tipo: 'filtro' }> => o.tipo === 'filtro' && o.colonna === colonna);

const MODI = ['elenco', 'dettaglio', 'feed'] as const;

test('articoli: isdraft eq false e categorie valide in ogni modo', () => {
  for (const modo of MODI) {
    const p = pianoQuery('articles', contesto({ modo, filtri: modo === 'elenco' ? filtri('articles', '') : null, id: modo === 'dettaglio' ? 5 : null }));
    assert.equal(p.tabella, 'articles');
    assert.equal(p.db, 'principale');
    assert.equal(p.select, 'articolo');
    const isdraft = p.operazioni.filter((o) => JSON.stringify(o).includes('isdraft'));
    assert.deepEqual(isdraft, [{ tipo: 'filtro', colonna: 'isdraft', operatore: 'eq', valore: 'false' }], modo);
    assert.deepEqual(filtroOp(p.operazioni, 'category_slug'), [{ tipo: 'filtro', colonna: 'category_slug', operatore: 'in', valore: '("scuola","universita")' }], modo);
    assert.deepEqual(filtroOp(p.operazioni, 'published_at').find((o) => o.operatore === 'not.is'), { tipo: 'filtro', colonna: 'published_at', operatore: 'not.is', valore: 'null' });
  }
  const conCategoria = pianoQuery('articles', contesto({ filtri: filtri('articles', 'category=scuola'), categoria: 'scuola' }));
  assert.deepEqual(filtroOp(conCategoria.operazioni, 'category_slug'), [{ tipo: 'filtro', colonna: 'category_slug', operatore: 'eq', valore: 'scuola' }]);
});

test('articoli: ordinamento, limiti, keyset, dettaglio', () => {
  const p = pianoQuery('articles', contesto({ filtri: filtri('articles', ''), dopo: { grezzo: '2026-09-21T07:12:29.519', id: 38934 } }));
  const coda = p.operazioni.slice(-4);
  assert.deepEqual(coda, [
    { tipo: 'or', espressione: 'published_at.lt."2026-09-21T07:12:29.519",and(published_at.eq."2026-09-21T07:12:29.519",id.lt.38934)' },
    { tipo: 'ordina', colonna: 'published_at', crescente: false },
    { tipo: 'ordina', colonna: 'id', crescente: false },
    { tipo: 'limite', n: 21 },
  ]);
  const d = pianoQuery('articles', contesto({ modo: 'dettaglio', id: 39382 }));
  assert.deepEqual(filtroOp(d.operazioni, 'id'), [{ tipo: 'filtro', colonna: 'id', operatore: 'eq', valore: '39382' }]);
  assert.deepEqual(d.operazioni.at(-1), { tipo: 'limite', n: 1 });
  assert.deepEqual(pianoQuery('articles', contesto({ modo: 'feed' })).operazioni.at(-1), { tipo: 'limite', n: 50 });
  assert.throws(() => pianoQuery('articles', contesto({ modo: 'dettaglio', id: null })));
});

test('articoli: since/until come superinsieme, has_video', () => {
  const f = filtri('articles', 'since=2026-09-21T09:00:00%2B02:00&until=2026-09-22&has_video=true');
  const p = pianoQuery('articles', contesto({ filtri: f }));
  assert.deepEqual(filtroOp(p.operazioni, 'published_at').filter((o) => o.operatore !== 'not.is'), [
    { tipo: 'filtro', colonna: 'published_at', operatore: 'gte', valore: '2026-09-21T07:00:00' },
    // until = 2026-09-23T00:00 Roma = 22:00Z del 22, piu' 2 h di margine
    { tipo: 'filtro', colonna: 'published_at', operatore: 'lt', valore: '2026-09-23T00:00:00' },
  ]);
  assert.deepEqual(filtroOp(p.operazioni, 'video_url'), [{ tipo: 'filtro', colonna: 'video_url', operatore: 'like', valore: 'http*' }]);
  const senza = pianoQuery('articles', contesto({ filtri: filtri('articles', 'has_video=false') }));
  assert.ok(senza.operazioni.some((o) => o.tipo === 'or' && o.espressione === 'video_url.is.null,video_url.not.like.http*'));
});

test('interpelli: link_type single e status completed in ogni modo', () => {
  for (const modo of MODI) {
    const p = pianoQuery('interpelli', contesto({ modo, filtri: modo === 'elenco' ? filtri('interpelli', '') : null, id: modo === 'dettaglio' ? 1 : null }));
    assert.deepEqual(filtroOp(p.operazioni, 'link_type'), [{ tipo: 'filtro', colonna: 'link_type', operatore: 'eq', valore: 'single' }], modo);
    assert.deepEqual(filtroOp(p.operazioni, 'status'), [{ tipo: 'filtro', colonna: 'status', operatore: 'eq', valore: 'completed' }], modo);
  }
  const f = filtri('interpelli', 'region=emilia-romagna&since=2026-09-01&until=2026-09-10');
  const p = pianoQuery('interpelli', contesto({ filtri: f, valoriRegione: ['Emilia-Romagna', 'Emilia Romagna'] }));
  assert.deepEqual(filtroOp(p.operazioni, 'interpello_regione'), [{ tipo: 'filtro', colonna: 'interpello_regione', operatore: 'in', valore: '("Emilia-Romagna","Emilia Romagna")' }]);
  assert.deepEqual(filtroOp(p.operazioni, 'interpello_date').filter((o) => o.operatore !== 'not.is').map((o) => o.valore), ['2026-09-01T00:00:00', '2026-09-11T00:00:00']);
  assert.deepEqual(p.operazioni.slice(-3, -1), [
    { tipo: 'ordina', colonna: 'interpello_date', crescente: false }, { tipo: 'ordina', colonna: 'id', crescente: false },
  ]);
});

test('selezione: status completed in ogni modo, feed senza scaduti', () => {
  for (const modo of MODI) {
    const p = pianoQuery('selezione-personale', contesto({ modo, filtri: modo === 'elenco' ? filtri('selezione-personale', '') : null, id: modo === 'dettaglio' ? 1 : null }));
    assert.deepEqual(filtroOp(p.operazioni, 'status'), [{ tipo: 'filtro', colonna: 'status', operatore: 'eq', valore: 'completed' }], modo);
    assert.ok(filtroOp(p.operazioni, 'data_pubblicazione').some((o) => o.operatore === 'not.is'), modo);
  }
  const feed = pianoQuery('selezione-personale', contesto({ modo: 'feed' }));
  assert.deepEqual(feed.operazioni.slice(-4), [
    { tipo: 'filtro', colonna: 'data_scadenza', operatore: 'gte', valore: '2026-09-21T00:00:00+00:00' },
    { tipo: 'ordina', colonna: 'updated_at', crescente: false },
    { tipo: 'ordina', colonna: 'id', crescente: false },
    { tipo: 'limite', n: 50 },
  ]);
  const f = filtri('selezione-personale', 'region=lazio&national=true&updated_since=2026-09-01T00:00:00Z');
  const p = pianoQuery('selezione-personale', contesto({ filtri: f, valoriRegione: ['Lazio'] }));
  assert.deepEqual(filtroOp(p.operazioni, 'sedi'), [
    { tipo: 'filtro', colonna: 'sedi', operatore: 'ov', valore: '{"Lazio"}' },
    { tipo: 'filtro', colonna: 'sedi', operatore: 'cs', valore: '{"Nazionale"}' },
  ]);
  assert.deepEqual(filtroOp(p.operazioni, 'updated_at'), [{ tipo: 'filtro', colonna: 'updated_at', operatore: 'gte', valore: '2026-09-01T00:00:00.000Z' }]);
  const nonNazionali = pianoQuery('selezione-personale', contesto({ filtri: filtri('selezione-personale', 'national=false') }));
  assert.ok(nonNazionali.operazioni.some((o) => o.tipo === 'or' && o.espressione === 'sedi.is.null,sedi.not.cs.{Nazionale}'));
});

test('bandi: filtro equivalente alla RLS in ogni modo, regione via embed', () => {
  for (const modo of MODI) {
    const p = pianoQuery('bandi', contesto({ modo, filtri: modo === 'elenco' ? filtri('bandi', '') : null, id: modo === 'dettaglio' ? 1 : null }));
    assert.equal(p.db, 'bandi');
    assert.equal(p.tabella, 'bando');
    assert.equal(p.select, 'bando');
    assert.deepEqual(filtroOp(p.operazioni, 'stato_processing'), [{ tipo: 'filtro', colonna: 'stato_processing', operatore: 'eq', valore: 'completed' }], modo);
    assert.deepEqual(filtroOp(p.operazioni, 'slug'), [{ tipo: 'filtro', colonna: 'slug', operatore: 'not.is', valore: 'null' }], modo);
  }
  const p = pianoQuery('bandi', contesto({ filtri: filtri('bandi', 'region=lazio&national=false&since=2026-09-01') }));
  assert.equal(p.select, 'bando-con-regione');
  assert.deepEqual(filtroOp(p.operazioni, 'filtro_regione.regioni.slug'), [{ tipo: 'filtro', colonna: 'filtro_regione.regioni.slug', operatore: 'eq', valore: 'lazio' }]);
  assert.deepEqual(filtroOp(p.operazioni, 'created_at').filter((o) => o.operatore === 'gte'), [{ tipo: 'filtro', colonna: 'created_at', operatore: 'gte', valore: '2026-08-31T22:00:00.000Z' }]);
  assert.ok(p.operazioni.some((o) => o.tipo === 'or' && o.espressione === 'area_geografica.is.null,area_geografica.not.ilike.nazionale'));
  assert.deepEqual(p.operazioni.slice(-3, -1), [
    { tipo: 'ordina', colonna: 'created_at', crescente: false }, { tipo: 'ordina', colonna: 'id', crescente: false },
  ]);
});

test('bandi: il predicato viene da FONTI_BANDI, tabella compresa', () => {
  // Non e' un doppione del test sopra: li' si controlla il valore, qui che il
  // valore arrivi dal modulo e non da una copia ricopiata in filtri.ts.
  const daModulo = FONTI_BANDI.bando.operazioni.map(([colonna, operatore, valore]) =>
    ({ tipo: 'filtro', colonna, operatore, valore }));
  const p = pianoQuery('bandi', contesto({ modo: 'dettaglio', id: 1 }));
  assert.deepEqual(p.operazioni.slice(0, daModulo.length), daModulo);

  // Sulla vista il predicato e' dentro la vista: ripeterlo darebbe 42703.
  const vista = pianoQuery('bandi', contesto({ modo: 'dettaglio', id: 1, fonteBandi: 'bando_pubblico' }));
  assert.equal(vista.tabella, 'bando_pubblico');
  assert.deepEqual(filtroOp(vista.operazioni, 'stato_processing'), []);
  assert.deepEqual(filtroOp(vista.operazioni, 'slug'), []);
  // `created_at` resta: non e' pubblicazione, e' la chiave del cursore.
  assert.deepEqual(filtroOp(vista.operazioni, 'created_at'),
    [{ tipo: 'filtro', colonna: 'created_at', operatore: 'not.is', valore: 'null' }]);

  // Solo i bandi cambiano tabella: le altre risorse non hanno una vista.
  assert.equal(pianoQuery('articles', contesto({ modo: 'dettaglio', id: 1, fonteBandi: 'bando_pubblico' })).tabella, 'articles');
});

test('builder di valori', () => {
  assert.equal(listaInPg(['Lazio']), '("Lazio")');
  assert.equal(listaInPg(['Lazio")']), '("Lazio\\")")');
  assert.equal(listaInPg(['"Lazio"']), '("\\"Lazio\\"")');
  assert.equal(listaInPg(['Lazio,\\']), '("Lazio,\\\\")');
  assert.equal(listaInPg(['Avviso OIV ', "Valle d'Aosta", 'Valle d’Aosta', 'Valle d\'Aosta']), '("Avviso OIV ","Valle d\'Aosta","Valle d’Aosta")');
  assert.throws(() => listaInPg([]));
  assert.equal(letteraleArrayPg(['Lazio', 'a"b']), '{"Lazio","a\\"b"}');
  assert.equal(condizioneKeyset('created_at', { grezzo: '2026-09-14T16:03:02.418+00:00', id: 7 }),
    'created_at.lt."2026-09-14T16:03:02.418+00:00",and(created_at.eq."2026-09-14T16:03:02.418+00:00",id.lt.7)');
});

test('nessun valore grezzo del client nei piani', () => {
  // i soli valori variabili ammessi: slug di categoria validati, regioni del registro, istanti riformattati, cursori validati
  const f = filtri('articles', 'category=scuola&since=2026-09-21T07:18:28.9Z');
  const p = pianoQuery('articles', contesto({ filtri: f, categoria: 'scuola' }));
  assert.ok(!JSON.stringify(p).includes('07:18:28.9'), 'istante non riformattato');
});

test('riferimenti: ordinamento e limite espliciti, nessun filtro sui profili', () => {
  assert.deepEqual(pianoRiferimento('categories').operazioni, [
    { tipo: 'ordina', colonna: 'order_id', crescente: true }, { tipo: 'ordina', colonna: 'slug', crescente: true }, { tipo: 'limite', n: 100 },
  ]);
  assert.deepEqual(pianoRiferimento('profiles'), {
    db: 'principale', tabella: 'profiles', select: 'profili',
    operazioni: [{ tipo: 'ordina', colonna: 'id', crescente: true }, { tipo: 'limite', n: 500 }],
  });
});

test('applicaPiano: una chiamata del builder per operazione', () => {
  const chiamate: string[] = [];
  const finto: CostruttoreQuery = {
    filter(c, o, v) { chiamate.push(`filter ${c} ${o} ${v}`); return finto; },
    or(e) { chiamate.push(`or ${e}`); return finto; },
    order(c, op) { chiamate.push(`order ${c} ${op.ascending}`); return finto; },
    limit(n) { chiamate.push(`limit ${n}`); return finto; },
  };
  const p = pianoQuery('bandi', contesto({ modo: 'dettaglio', id: 3 }));
  applicaPiano(finto, p.operazioni);
  assert.deepEqual(chiamate, [
    'filter stato_processing eq completed', 'filter slug not.is null', 'filter created_at not.is null',
    'filter id eq 3', 'order created_at false', 'order id false', 'limit 1',
  ]);
});
