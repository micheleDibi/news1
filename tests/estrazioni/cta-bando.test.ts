/**
 * `src/lib/bandi/cta.ts`: l'unica CTA della scheda.
 *
 * Il caso che dà il nome al bug: `link_candidatura_source='fallback_source'` +
 * `link_bando` sull'aggregatore. Il codice precedente mostrava «Apri la pagina
 * ufficiale del bando» e mandava lì (94 CTA su 230 misurate). Qui non c'è
 * proprio un ingresso `link_bando`.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { sceltaCta } from '../../src/lib/bandi/cta.ts';

test('F1: solo link_candidatura estratto e pubblicabile', () => {
  assert.deepEqual(sceltaCta({ candidaturaEstratta: 'https://comune.esempio.it/domanda' }), {
    url: 'https://comune.esempio.it/domanda',
    etichetta: 'Vai al modulo di candidatura',
  });
  // Il ripiego su un aggregatore non esiste più: nessun box.
  assert.equal(sceltaCta({ candidaturaEstratta: 'https://www.obiettivoeuropa.com/scheda/1' }), null);
  assert.equal(sceltaCta({ candidaturaEstratta: 'javascript:alert(1)' }), null);
  assert.equal(sceltaCta({ candidaturaEstratta: null }), null);
  assert.equal(sceltaCta({}), null);
});

test('la cascata: candidatura, ente/atto, portale pubblico', () => {
  const fonteEnte = {
    stato: 'trovata', url: 'https://comune.esempio.it/bando', host: 'comune.esempio.it', tipo: 'ente',
  } as const;

  // 1. Il link di candidatura vince sulla fonte ufficiale.
  assert.deepEqual(
    sceltaCta({
      link: [{ tipo: 'candidatura', url: 'https://comune.esempio.it/domanda', pubblicabile: true }],
      fonteUfficiale: fonteEnte,
    }),
    { url: 'https://comune.esempio.it/domanda', etichetta: 'Vai al modulo di candidatura' },
  );

  // 2. Senza candidatura: la pagina dell'ente.
  assert.deepEqual(sceltaCta({ fonteUfficiale: fonteEnte }), {
    url: 'https://comune.esempio.it/bando',
    etichetta: 'Apri la pagina ufficiale del bando',
  });

  // L'atto (PDF sul dominio dell'ente) ha la stessa etichetta dell'ente.
  assert.equal(
    sceltaCta({
      fonteUfficiale: {
        stato: 'trovata', url: 'https://comune.esempio.it/atto.pdf',
        host: 'comune.esempio.it', tipo: null, e_atto: true,
      },
    })?.etichetta,
    'Apri la pagina ufficiale del bando',
  );

  // 3. Portale pubblico: etichetta diversa, perché non è l'ente.
  assert.deepEqual(
    sceltaCta({
      fonteUfficiale: {
        stato: 'trovata', url: 'https://incentivi.gov.it/b', host: 'incentivi.gov.it', tipo: 'portale_pubblico',
      },
    }),
    { url: 'https://incentivi.gov.it/b', etichetta: 'Consulta il bando sul portale pubblico' },
  );

  // 4. Riga bando_link di tipo portale, in coda a tutto.
  assert.deepEqual(
    sceltaCta({ link: [{ tipo: 'portale', url: 'https://incentivi.gov.it/p', pubblicabile: true }] }),
    { url: 'https://incentivi.gov.it/p', etichetta: 'Consulta il bando sul portale pubblico' },
  );
});

test('una fonte trovata con tipo nullo ha comunque il suo pulsante', () => {
  // Gli host riconosciuti solo per forma (`regione.*.it`, `*.gov.it`,
  // `*.camcom.it`) non hanno un valore da scrivere in `fonte_ufficiale_tipo`,
  // ma il resolver li ammette a `trovata` di proposito. In produzione sono 193
  // fonti su 495: pretendere `tipo='ente'` le lasciava senza nessun pulsante.
  for (const url of [
    'https://bandi.regione.piemonte.it/contributi/avviso-1',
    'https://creativitacontemporanea.cultura.gov.it/edizione1/',
    'https://bs.camcom.it/bando',
  ]) {
    assert.deepEqual(
      sceltaCta({ fonteUfficiale: { stato: 'trovata', url, host: new URL(url).hostname, tipo: null } }),
      { url, etichetta: 'Apri la pagina ufficiale del bando' },
    );
  }

  // Resta vero che un aggregatore non diventa una CTA per il fatto di avere
  // `tipo` nullo: lo esclude `urlPubblicabile`, non il tipo.
  assert.equal(
    sceltaCta({
      fonteUfficiale: {
        stato: 'trovata', url: 'https://www.obiettivoeuropa.com/bandi/x',
        host: 'obiettivoeuropa.com', tipo: null,
      },
    }),
    null,
  );
});

test('nessuna CTA quando nessuna destinazione è affidabile', () => {
  // Fonte non ancora conclusa: il suo URL non si usa, anche se c'è.
  assert.equal(sceltaCta({
    fonteUfficiale: { stato: 'in_verifica', url: 'https://forse.esempio.it/b', host: 'forse.esempio.it', tipo: 'ente' },
  }), null);
  // Fonte «trovata» su un host in denylist: la cintura scatta comunque.
  assert.equal(sceltaCta({
    fonteUfficiale: { stato: 'trovata', url: 'https://fasi.eu/b', host: 'fasi.eu', tipo: 'ente' },
  }), null);
  // Riga di bando_link marcata non pubblicabile dal produttore.
  assert.equal(sceltaCta({
    link: [{ tipo: 'candidatura', url: 'https://comune.esempio.it/d', pubblicabile: false }],
  }), null);
  // Solo allegati: non sono una CTA.
  assert.equal(sceltaCta({
    link: [{ tipo: 'allegato', url: 'https://comune.esempio.it/a.pdf', pubblicabile: true }],
  }), null);
  assert.equal(sceltaCta({ link: null, fonteUfficiale: null, candidaturaEstratta: null }), null);
});

test('la prima riga utile vince, le precedenti inservibili si saltano', () => {
  assert.equal(
    sceltaCta({
      link: [
        { tipo: 'candidatura', url: 'https://www.obiettivoeuropa.com/d', pubblicabile: true },
        { tipo: 'candidatura', url: 'https://comune.esempio.it/d2', pubblicabile: true },
      ],
    })?.url,
    'https://comune.esempio.it/d2',
  );
});
