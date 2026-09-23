/**
 * `src/lib/bandi/jsonld.ts`.
 *
 * Il bug chiuso: `sameAs: bando.link_bando`, cioè l'URL sull'aggregatore, su
 * ogni scheda che ne aveva uno. `sameAs` dice ai motori «questa è la stessa
 * entità»: dichiararlo verso un aggregatore regala a lui la nostra pagina.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { jsonLdBando } from '../../src/lib/bandi/jsonld.ts';

const BASE = {
  urlCanonico: 'https://edunews24.it/bandi/voucher-digitalizzazione',
  titolo: 'Voucher digitalizzazione',
};

test('forma minima: nessuna proprietà vuota, mai null nel JSON', () => {
  const ld = jsonLdBando(BASE);
  assert.equal(ld['@type'], 'Article');
  assert.equal(ld['@id'], BASE.urlCanonico);
  assert.equal(ld.headline, 'Voucher digitalizzazione');
  const serializzato = JSON.parse(JSON.stringify(ld)) as Record<string, unknown>;
  for (const [nome, valore] of Object.entries(serializzato)) assert.notEqual(valore, null, nome);
  for (const assente of ['alternativeHeadline', 'description', 'datePublished', 'dateModified',
    'spatialCoverage', 'audience', 'keywords']) {
    assert.equal(Object.hasOwn(serializzato, assente), false, assente);
  }
  assert.equal(Object.hasOwn(serializzato.about as object, 'sameAs'), false);
});

test('sameAs: solo con fonte ufficiale trovata e pubblicabile', () => {
  const conFonte = jsonLdBando({
    ...BASE,
    fonteUfficiale: {
      stato: 'trovata', url: 'https://regione.marche.it/bando', host: 'regione.marche.it', tipo: 'ente',
    },
  });
  assert.equal((conFonte.about as Record<string, unknown>).sameAs, 'https://regione.marche.it/bando');

  // F1: nessuna colonna, nessun sameAs.
  assert.equal(Object.hasOwn(jsonLdBando(BASE).about as object, 'sameAs'), false);

  // Fonte non conclusa: niente sameAs, anche se un URL c'è.
  const inVerifica = jsonLdBando({
    ...BASE,
    fonteUfficiale: { stato: 'in_verifica', url: 'https://forse.esempio.it/b', host: 'forse.esempio.it', tipo: null },
  });
  assert.equal(Object.hasOwn(inVerifica.about as object, 'sameAs'), false);

  // Il bug storico: un URL di aggregatore non passa nemmeno come «trovata».
  const aggregatore = jsonLdBando({
    ...BASE,
    fonteUfficiale: {
      stato: 'trovata', url: 'https://www.obiettivoeuropa.com/scheda/1',
      host: 'obiettivoeuropa.com', tipo: 'ente',
    },
  });
  assert.equal(Object.hasOwn(aggregatore.about as object, 'sameAs'), false);
  assert.equal(JSON.stringify(aggregatore).includes('obiettivoeuropa'), false);
});

test('nessun FAQPage e nessun marcatore di FAQ', () => {
  const testo = JSON.stringify(jsonLdBando({ ...BASE, descrizione: 'Domande frequenti incluse.' }));
  assert.equal(testo.includes('FAQPage'), false);
  assert.equal(testo.includes('Question'), false);
  assert.equal(testo.includes('acceptedAnswer'), false);
});

test('proprietà facoltative: emesse solo con un dato vero', () => {
  const ld = jsonLdBando({
    ...BASE,
    titoloBreve: 'Voucher PMI',
    descrizione: 'Contributi a fondo perduto.',
    dataPubblicazione: '2026-09-10',
    dataModifica: '2026-09-20T03:12:55+02:00',
    enteErogatore: 'Regione Marche',
    areaGeografica: 'Marche',
    beneficiari: ['PMI', '', '  '],
    tematiche: ['Digitalizzazione', 'Innovazione'],
    importoTotaleEur: 1_500_000,
  });
  assert.equal(ld.alternativeHeadline, 'Voucher PMI');
  assert.equal(ld.datePublished, '2026-09-10');
  assert.equal(ld.dateModified, '2026-09-20T03:12:55+02:00');
  assert.deepEqual(ld.spatialCoverage, { '@type': 'Place', name: 'Marche' });
  // Le stringhe vuote spariscono, non diventano audience senza nome.
  assert.deepEqual(ld.audience, [{ '@type': 'Audience', audienceType: 'PMI' }]);
  assert.equal(ld.keywords, 'Digitalizzazione, Innovazione');
  const about = ld.about as Record<string, unknown>;
  assert.deepEqual(about.funder, { '@type': 'Organization', name: 'Regione Marche' });
  assert.deepEqual(about.amount, { '@type': 'MonetaryAmount', currency: 'EUR', value: 1_500_000 });

  // Elenchi vuoti o importo non finito: la proprietà non esce affatto.
  const vuoti = jsonLdBando({ ...BASE, beneficiari: [], tematiche: null, importoTotaleEur: Number.NaN });
  assert.equal(Object.hasOwn(vuoti, 'audience'), false);
  assert.equal(Object.hasOwn(vuoti, 'keywords'), false);
  assert.equal(Object.hasOwn(vuoti.about as object, 'amount'), false);
});
