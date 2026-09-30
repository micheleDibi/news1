/**
 * JSON-LD dei bandi sicuro dentro `<script type="application/ld+json">`
 * (revisione avversaria del 30/09, S1).
 *
 * `set:html={JSON.stringify(jsonLd)}` non faceva escape: un titolo o una
 * descrizione con `</script>` (testo del modello nato da pagine esterne,
 * salvato a DB dallo step SEO) chiudeva lo script e diventava una XSS salvata.
 * Le pagine dei bandi ora passano da `serializzaJsonLd`/`proteggiJsonLd`, che
 * trasformano `<`, `>`, `&`, U+2028 e U+2029 in escape Unicode.
 *
 * Si verifica che: nel testo reso non resti nessuno di quei caratteri; il
 * JSON-LD, riletto con `JSON.parse`, sia identico all'originale (i motori
 * vedono gli stessi dati); il breadcrumb di `seo.ts` passi dalla stessa porta.
 *
 * Nessun rendering di `.astro` sotto `node --test`: le pagine chiamano queste
 * funzioni e nient'altro.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { jsonLdBando, proteggiJsonLd, serializzaJsonLd } from '../../src/lib/bandi/jsonld.ts';
import { generateBreadcrumbStructuredData } from '../../src/lib/seo.ts';

const TITOLO_OSTILE = 'Bando </script><script>alert(1)</script> per le imprese';
const DESCRIZIONE_OSTILE = 'Fondi & contributi <b>fino</b> al 30/10\u2028nuova riga\u2029fine';

const DATI = {
  urlCanonico: 'https://edunews24.it/bandi/bando-imprese',
  titolo: TITOLO_OSTILE,
  descrizione: DESCRIZIONE_OSTILE,
  enteErogatore: 'Regione <Piemonte>',
};

function senzaCaratteriPericolosi(testo: string): void {
  for (const pericoloso of ['<', '>', '&', '\u2028', '\u2029']) {
    assert.equal(testo.includes(pericoloso), false, `resta ${JSON.stringify(pericoloso)}`);
  }
  assert.equal(testo.toLowerCase().includes('</script'), false);
}

test('serializzaJsonLd: </script> nel titolo non chiude lo script', () => {
  const reso = serializzaJsonLd(jsonLdBando(DATI));
  senzaCaratteriPericolosi(reso);
  assert.ok(reso.includes('\\u003c/script\\u003e'));
});

test('serializzaJsonLd: il JSON riletto e identico all originale', () => {
  const originale = jsonLdBando(DATI);
  assert.deepEqual(JSON.parse(serializzaJsonLd(originale)), originale);
  const letto = JSON.parse(serializzaJsonLd(originale)) as { headline: string; description: string };
  assert.equal(letto.headline, TITOLO_OSTILE);
  assert.equal(letto.description, DESCRIZIONE_OSTILE);
});

test('proteggiJsonLd: il breadcrumb gia serializzato passa dalla stessa porta', () => {
  const breadcrumb = generateBreadcrumbStructuredData(
    { category: 'Bandi', category_slug: 'bandi', slug: 'bando-imprese', title: TITOLO_OSTILE },
  );
  assert.ok(breadcrumb.includes('</script>'), 'il breadcrumb grezzo contiene il titolo ostile');
  const reso = proteggiJsonLd(breadcrumb);
  senzaCaratteriPericolosi(reso);
  assert.deepEqual(JSON.parse(reso), JSON.parse(breadcrumb));
});

test('proteggiJsonLd: un JSON senza caratteri pericolosi resta identico', () => {
  const pulito = JSON.stringify({ '@type': 'BreadcrumbList', name: 'Bandi e finanziamenti' });
  assert.equal(proteggiJsonLd(pulito), pulito);
});
