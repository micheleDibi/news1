/**
 * Guardia di /api/indexnow-notify (fix 8.a.25): il confronto del segreto deve essere
 * fail-closed. L'handler non e' importabile fuori da Astro (in Node `import.meta.env`
 * e' undefined e l'accesso lancerebbe prima del confronto), quindi si testa la
 * funzione pura di src/lib/verifica-segreto.ts e, staticamente, che la rotta la usi.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { segretoValido } from '../../src/lib/verifica-segreto.ts';

test('segretoValido: senza segreto configurato nessuna chiave passa (fail-closed)', () => {
  // Il caso del bug: variabile assente e header assente. Il vecchio confronto
  // `undefined !== undefined` dava false e lasciava passare la richiesta.
  assert.equal(segretoValido(undefined, undefined), false);
  assert.equal(segretoValido(null, undefined), false);
  assert.equal(segretoValido(undefined, null), false);
  assert.equal(segretoValido('', ''), false);
  assert.equal(segretoValido(undefined, ''), false);
  assert.equal(segretoValido('qualunque-chiave', undefined), false);
  assert.equal(segretoValido('qualunque-chiave', ''), false);
});

test('segretoValido: con segreto configurato passa solo la chiave identica', () => {
  assert.equal(segretoValido('segreto-di-prova', 'segreto-di-prova'), true);
  assert.equal(segretoValido('segreto-di-prov', 'segreto-di-prova'), false);
  assert.equal(segretoValido('segreto-di-prova ', 'segreto-di-prova'), false);
  assert.equal(segretoValido('Segreto-di-prova', 'segreto-di-prova'), false);
  assert.equal(segretoValido(undefined, 'segreto-di-prova'), false);
  assert.equal(segretoValido(null, 'segreto-di-prova'), false);
  assert.equal(segretoValido('', 'segreto-di-prova'), false);
});

test('indexnow-notify.ts: la rotta usa segretoValido e non il confronto fail-open', () => {
  const sorgente = readFileSync(
    fileURLToPath(new URL('../../src/pages/api/indexnow-notify.ts', import.meta.url)),
    'utf8',
  );
  assert.match(sorgente, /import \{ segretoValido \} from '\.\.\/\.\.\/lib\/verifica-segreto';/);
  assert.match(sorgente, /if \(!segretoValido\(apiKey, import\.meta\.env\.API_SECRET_KEY\)\)/);
  assert.doesNotMatch(sorgente, /!==\s*import\.meta\.env\.API_SECRET_KEY/);
  // La risposta del rifiuto resta quella storica: 401 con corpo JSON.
  assert.match(sorgente, /status: 401/);
  assert.match(sorgente, /error: 'Unauthorized'/);
});
