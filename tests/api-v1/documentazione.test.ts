/**
 * documentazione.ts e pagina /sviluppatori/api: ancore stabili e contenuti minimi.
 * Le ancore `error-<code>` e `termini` sono citate dalle risposte dell'API
 * (membro `type` dei problem+json, meta.terms): non possono sparire.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { sezioniDocumentazione } from '../../src/lib/api-v1/documentazione.ts';
import { CODICI_ERRORE, DEFINIZIONE_ERRORE } from '../../src/lib/api-v1/errori.ts';
import { ORDINE_PARAMETRI, SPEC_PARAMETRI } from '../../src/lib/api-v1/parametri.ts';
import { CONTENT_SIGNAL, URL_TERMINI } from '../../src/lib/api-v1/costanti.ts';
import type { Blocco, SezioneDoc } from '../../src/lib/api-v1/documentazione.ts';

const sezioni = sezioniDocumentazione();

function sezione(id: string): SezioneDoc {
  const trovata = sezioni.find((s) => s.id === id);
  assert.ok(trovata, `sezione ${id} assente`);
  return trovata;
}

function testoDi(s: SezioneDoc): string {
  return s.blocchi.map((b: Blocco) => {
    switch (b.tipo) {
      case 'paragrafo': return b.testo;
      case 'elenco': return b.voci.join('\n');
      case 'codice': return b.testo;
      case 'tabella': return [b.intestazioni.join(' | '), ...b.righe.map((r) => r.join(' | '))].join('\n');
    }
  }).join('\n');
}

test('id unici, stabili e utilizzabili come ancore', () => {
  const id = sezioni.map((s) => s.id);
  assert.equal(new Set(id).size, id.length);
  for (const valore of id) assert.match(valore, /^[a-z][a-z0-9-]*$/);
  for (const s of sezioni) {
    assert.notEqual(s.titolo.trim(), '', s.id);
    assert.ok(s.blocchi.length > 0, s.id);
  }
  // Due chiamate: stessi contenuti, oggetti nuovi.
  assert.deepEqual(sezioniDocumentazione(), sezioni);
  assert.notEqual(sezioniDocumentazione(), sezioni);
});

test('una sezione error-<code> per ogni codice, in ordine', () => {
  const errori = sezioni.filter((s) => s.id.startsWith('error-')).map((s) => s.id);
  assert.deepEqual(errori, CODICI_ERRORE.map((c) => `error-${c}`));
  for (const codice of CODICI_ERRORE) {
    const s = sezione(`error-${codice}`);
    const definizione = DEFINIZIONE_ERRORE.get(codice);
    assert.ok(definizione);
    assert.ok(s.titolo.includes(codice));
    assert.ok(testoDi(s).includes(`Status HTTP ${definizione.status}`), codice);
    assert.ok(testoDi(s).includes('Cosa fare:'), codice);
  }
  assert.ok(testoDi(sezione('error-invalid-parameter')).includes('"errors"'));
  assert.ok(testoDi(sezione('error-rate-limited')).includes('"retry_after": 1'));
  assert.ok(testoDi(sezione('error-method-not-allowed')).includes('no-store'));
});

test('sezione termini: nota provvisoria datata con attribuzione, limiti e Content-Signal', () => {
  const termini = sezione('termini');
  assert.equal(URL_TERMINI.endsWith('#termini'), true);
  const testo = testoDi(termini);
  for (const frammento of [
    'Nota provvisoria del 21 settembre 2026', 'Fonte: EduNews24', 'url canonico', 'testo integrale', 'Cache-Control',
    CONTENT_SIGNAL, 'addestramento', 'termini d\'uso definitivi',
  ]) {
    assert.ok(testo.includes(frammento), frammento);
  }
});

test('sezioni richieste presenti', () => {
  for (const id of [
    'introduzione', 'risorse', 'esempi', 'paginazione', 'filtri', 'date', 'testo', 'cache', 'limiti', 'cors', 'feed',
    'errori', 'termini', 'changelog',
  ]) {
    sezione(id);
  }
  assert.ok(testoDi(sezione('changelog')).includes('1.0 | 2026-09-21'));
  assert.ok(testoDi(sezione('introduzione')).includes('https://edunews24.it/api/v1'));
  assert.ok(testoDi(sezione('esempi')).includes('curl '));
  assert.ok(testoDi(sezione('paginazione')).includes('links.next'));
  assert.ok(testoDi(sezione('date')).includes('436'));
  assert.ok(testoDi(sezione('testo')).includes('nome host'));
  const limiti = testoDi(sezione('limiti'));
  for (const frammento of ['/64', 'RateLimit-Policy', 'nginx', 'Cloudflare', 'User-Agent']) assert.ok(limiti.includes(frammento), frammento);
  const feed = testoDi(sezione('feed'));
  for (const frammento of ['_edunews24', 'application/feed+json', 'application/rss+xml', '<rss version="2.0"', '"version": "https://jsonfeed.org/version/1.1"']) {
    assert.ok(feed.includes(frammento), frammento);
  }
});

test('tabella dei filtri generata da SPEC_PARAMETRI', () => {
  const tabella = sezione('filtri').blocchi.find((b) => b.tipo === 'tabella');
  assert.ok(tabella && tabella.tipo === 'tabella');
  const risorse = tabella.intestazioni.slice(1, -1);
  assert.deepEqual(risorse, ['articles', 'interpelli', 'selezione-personale', 'bandi']);
  assert.deepEqual(tabella.righe.map((r) => r[0]), ORDINE_PARAMETRI);
  for (const riga of tabella.righe) {
    risorse.forEach((risorsa, i) => {
      const ammesso = (SPEC_PARAMETRI.get(risorsa as 'articles') ?? []).some((n) => n === riga[0]);
      assert.equal(riga[i + 1], ammesso ? 'sì' : '—', `${riga[0]} su ${risorsa}`);
    });
    assert.notEqual(riga[riga.length - 1], '', riga[0]);
  }
});

test('tabella Cache-Control del piano (sezione 7)', () => {
  const tabella = sezione('cache').blocchi.find((b) => b.tipo === 'tabella');
  assert.ok(tabella && tabella.tipo === 'tabella');
  const righe = new Map(tabella.righe.map((r) => [r[0], r[1]]));
  assert.equal(righe.get('elenchi'), 'public, max-age=60, s-maxage=300, stale-while-revalidate=300, stale-if-error=86400');
  assert.equal(righe.get('dettagli'), 'public, max-age=300, s-maxage=900, stale-while-revalidate=900, stale-if-error=86400');
  assert.equal(righe.get('feed'), 'public, max-age=300, s-maxage=600, stale-while-revalidate=600, stale-if-error=86400');
  assert.equal(righe.get('categorie, indice'), 'public, max-age=900, s-maxage=3600, stale-while-revalidate=3600, stale-if-error=86400');
  assert.equal(righe.get('openapi.json'), 'public, max-age=3600, s-maxage=86400');
  assert.equal(righe.get('400, 404'), 'public, max-age=60, s-maxage=60');
  assert.equal(righe.get('405, 429, 500, 503'), 'no-store');
  assert.equal(tabella.righe.length, 10);
});

test('blocchi ben formati: niente testi vuoti, tabelle rettangolari', () => {
  for (const s of sezioni) {
    for (const b of s.blocchi) {
      switch (b.tipo) {
        case 'paragrafo':
          assert.notEqual(b.testo.trim(), '', s.id);
          break;
        case 'elenco':
          assert.ok(b.voci.length > 0, s.id);
          for (const voce of b.voci) assert.notEqual(voce.trim(), '', s.id);
          break;
        case 'codice':
          assert.notEqual(b.linguaggio, '', s.id);
          assert.notEqual(b.testo.trim(), '', s.id);
          break;
        case 'tabella':
          assert.ok(b.righe.length > 0, s.id);
          for (const riga of b.righe) assert.equal(riga.length, b.intestazioni.length, s.id);
          break;
      }
    }
  }
});

test('la pagina .astro e\' SSR, usa il Layout e itera le sezioni senza logica propria', () => {
  const pagina = readFileSync(new URL('../../src/pages/sviluppatori/api.astro', import.meta.url), 'utf8');
  assert.ok(pagina.includes('export const prerender = false;'));
  assert.ok(pagina.includes('prerender = false'));
  assert.ok(pagina.includes("from '../../layouts/Layout.astro'"));
  assert.ok(pagina.includes('sezioniDocumentazione()'));
  assert.ok(pagina.includes('title="API pubblica EduNews24 – Documentazione"'));
  assert.ok(pagina.includes('<section id={sezione.id}'));
  assert.ok(/<h2 class="font-heading[^"]*"/.test(pagina));
  assert.ok(pagina.includes('<pre') && pagina.includes('<code'));
  assert.ok(pagina.includes('<table'));
  assert.equal(pagina.includes('<script'), false);
  assert.equal(pagina.includes('supabase'), false);
});
