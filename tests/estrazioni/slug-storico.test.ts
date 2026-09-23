/**
 * `src/lib/bandi/slug-storico.ts`: 200/301/410/404/503 della scheda.
 *
 * La regola non ovvia (§16.2 M18): 301 e 410 solo su una lettura **riuscita**;
 * un errore di PostgREST dà 503 con Retry-After e **senza** noindex. Oggi la
 * scheda avvolge la query in try/catch e risponde 404 a qualunque cosa: un
 * timeout (anon ha 3 s di statement_timeout) deindicizza la pagina.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { RITENTA_DOPO_SECONDI, esitoSlug } from '../../src/lib/bandi/slug-storico.ts';

const NON_ESEGUITA = { stato: 'non_eseguita' } as const;
const ERRORE = { stato: 'errore' } as const;
const SENZA_RIGHE = { stato: 'ok', riga: null } as const;

test('scheda trovata: 200, senza nemmeno guardare lo storico', () => {
  assert.deepEqual(
    esitoSlug({ scheda: { stato: 'ok', riga: { slug: 'x' } }, storico: ERRORE }),
    { stato: 200 },
  );
});

test('errore di lettura: 503 con Retry-After, mai 404', () => {
  assert.deepEqual(esitoSlug({ scheda: ERRORE, storico: NON_ESEGUITA }), {
    stato: 503, ritentaDopoSecondi: RITENTA_DOPO_SECONDI,
  });
  // Errore sulla seconda lettura: anche qui 503, non un 404 «per mancanza di prove».
  assert.equal(esitoSlug({ scheda: SENZA_RIGHE, storico: ERRORE }).stato, 503);
  // Scheda mai letta: non si può decidere niente, 503.
  assert.equal(esitoSlug({ scheda: NON_ESEGUITA, storico: NON_ESEGUITA }).stato, 503);
});

test('F1: senza mappa degli slug storici lo slug ignoto è 404', () => {
  assert.deepEqual(esitoSlug({ scheda: SENZA_RIGHE, storico: NON_ESEGUITA }), { stato: 404 });
  assert.deepEqual(esitoSlug({ scheda: SENZA_RIGHE, storico: SENZA_RIGHE }), { stato: 404 });
});

test('301 al master, mai catene e mai verso una pagina che non c\'è', () => {
  assert.deepEqual(
    esitoSlug({
      scheda: SENZA_RIGHE,
      storico: { stato: 'ok', riga: { esito: '301', slugMaster: 'bando-master' } },
    }),
    { stato: 301, destinazione: '/bandi/bando-master' },
  );
  // Master non visibile (il chiamante risolve lo slug solo sui pubblicati):
  // 410, non un 301 verso un 404.
  assert.deepEqual(
    esitoSlug({ scheda: SENZA_RIGHE, storico: { stato: 'ok', riga: { esito: '301', slugMaster: null } } }),
    { stato: 410 },
  );
  assert.deepEqual(
    esitoSlug({ scheda: SENZA_RIGHE, storico: { stato: 'ok', riga: { esito: '301', slugMaster: '  ' } } }),
    { stato: 410 },
  );
});

test('410 sul ritiro; `annullato` torna a essere uno slug ignoto', () => {
  assert.deepEqual(
    esitoSlug({ scheda: SENZA_RIGHE, storico: { stato: 'ok', riga: { esito: '410', slugMaster: null } } }),
    { stato: 410 },
  );
  assert.deepEqual(
    esitoSlug({ scheda: SENZA_RIGHE, storico: { stato: 'ok', riga: { esito: 'annullato', slugMaster: 'x' } } }),
    { stato: 404 },
  );
  // Esito assente o sconosciuto: il contenuto non c'è più ma non sappiamo dove
  // sia andato. 410 è l'informazione vera, 301 sarebbe un'invenzione.
  assert.deepEqual(
    esitoSlug({ scheda: SENZA_RIGHE, storico: { stato: 'ok', riga: { esito: null, slugMaster: 'x' } } }),
    { stato: 410 },
  );
});
