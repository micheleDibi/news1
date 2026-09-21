/**
 * mappa-categorie.ts: colori hex, ordine, URL e link assoluti, secondarie ordinate.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mappaCategorie } from '../../src/lib/api-v1/mappa-categorie.ts';
import { costruisciRiferimentoCategorie } from '../../src/lib/api-v1/riferimenti.ts';
import { RIGHE_CATEGORIE, RIGHE_SECONDARIE } from './fixture/riferimenti-base.ts';

const { riferimento } = costruisciRiferimentoCategorie(RIGHE_CATEGORIE, RIGHE_SECONDARIE);

test('categorie: DTO completo della prima categoria, campi nell\'ordine del contratto', () => {
  const dati = mappaCategorie(riferimento);
  assert.deepEqual(dati[0], {
    slug: 'scuola',
    name: 'Scuola',
    color: '#2D6A4F',
    position: 1,
    url: 'https://edunews24.it/scuola',
    secondary_categories: [
      { slug: 'ata', name: 'ATA' },
      { slug: 'dirigenti', name: 'Dirigenti scolastici' },
      { slug: 'insegnanti', name: 'Insegnanti' },
    ],
    links: {
      articles: 'https://edunews24.it/api/v1/articles?category=scuola',
      feed_json: 'https://edunews24.it/api/v1/feeds/articles/scuola.json',
      feed_rss: 'https://edunews24.it/api/v1/feeds/articles/scuola.xml',
    },
  });
  for (const c of dati) {
    assert.deepEqual(Object.keys(c), ['slug', 'name', 'color', 'position', 'url', 'secondary_categories', 'links']);
    assert.deepEqual(Object.keys(c.links), ['articles', 'feed_json', 'feed_rss']);
    for (const s of c.secondary_categories) assert.deepEqual(Object.keys(s), ['slug', 'name'], 'niente parent in uscita');
  }
});

test('categorie: colore hex (scuola -> #2D6A4F, nome sconosciuto -> #004e9c)', () => {
  const perSlug = new Map(mappaCategorie(riferimento).map((c) => [c.slug, c.color]));
  assert.equal(perSlug.get('scuola'), '#2D6A4F');
  assert.equal(perSlug.get('universita'), '#1B3A7B');
  assert.equal(perSlug.get('senza-posizione'), '#004e9c');
  for (const colore of perSlug.values()) assert.match(colore, /^#[0-9A-Fa-f]{6}$/);
});

test('categorie: ordine del riferimento (position asc, null in fondo, poi slug)', () => {
  const { riferimento: rif } = costruisciRiferimentoCategorie([
    { slug: 'zeta', name: 'Zeta', color: null, order_id: null },
    { slug: 'beta', name: 'Beta', color: null, order_id: 2 },
    { slug: 'alfa', name: 'Alfa', color: null, order_id: null },
    { slug: 'gamma', name: 'Gamma', color: null, order_id: 1 },
  ], []);
  const dati = mappaCategorie(rif);
  assert.deepEqual(dati.map((c) => [c.slug, c.position]), [['gamma', 1], ['beta', 2], ['alfa', null], ['zeta', null]]);
  assert.deepEqual(dati.map((c) => c.secondary_categories), [[], [], [], []]);
});

test('categorie: URL e link sempre assoluti su edunews24.it', () => {
  for (const c of mappaCategorie(riferimento)) {
    for (const u of [c.url, c.links.articles, c.links.feed_json, c.links.feed_rss]) {
      const url = new URL(u);
      assert.equal(url.origin, 'https://edunews24.it');
      assert.equal(url.href, u, 'gia\' normalizzato');
    }
    assert.equal(new URL(c.links.articles).searchParams.get('category'), c.slug);
  }
});

test('categorie: secondarie ordinate per nome con il collator italiano, poi slug', () => {
  const { riferimento: rif } = costruisciRiferimentoCategorie(
    [{ slug: 'scuola', name: 'Scuola', color: 'scuola', order_id: 1 }],
    [
      { slug: 'z', name: 'Zaino', parent_category_slug: 'scuola' },
      { slug: 'e-accentata', name: 'Èlite', parent_category_slug: 'scuola' },
      { slug: 'a', name: 'agenda', parent_category_slug: 'scuola' },
      { slug: 'b', name: 'Banchi', parent_category_slug: 'scuola' },
      { slug: 'b-bis', name: 'Banchi', parent_category_slug: 'scuola' },
    ],
  );
  assert.deepEqual(mappaCategorie(rif)[0].secondary_categories.map((s) => s.slug), ['a', 'b', 'b-bis', 'e-accentata', 'z']);
});
