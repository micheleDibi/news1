/**
 * /api/indexnow-key risponde solo con lo stato e non rivela mai la chiave.
 * L'handler non e' importabile fuori da Astro (`import.meta.env` e' undefined in
 * Node), quindi si testa la funzione pura di src/lib/indexnow-chiave.ts e,
 * staticamente, che la rotta la usi.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { rispostaStatoChiave } from '../../src/lib/indexnow-chiave.ts';

const CHIAVE = 'chiave-di-prova-0123456789abcdef';

test('rispostaStatoChiave: con la chiave configurata 200 senza la chiave nel corpo', async () => {
  const risposta = rispostaStatoChiave(CHIAVE);
  assert.equal(risposta.status, 200);
  assert.equal(risposta.headers.get('Cache-Control'), 'no-store');
  const corpo = await risposta.text();
  assert.equal(corpo, 'ok');
  assert.ok(!corpo.includes(CHIAVE));
});

test('rispostaStatoChiave: senza chiave 404 con il corpo storico', async () => {
  for (const assente of [undefined, null, '']) {
    const risposta = rispostaStatoChiave(assente);
    assert.equal(risposta.status, 404);
    assert.equal(risposta.headers.get('Cache-Control'), 'no-store');
    assert.equal(await risposta.text(), 'IndexNow key not configured');
  }
});

test('indexnow-key.ts: la rotta usa rispostaStatoChiave e non mette la chiave nel corpo', () => {
  const sorgente = readFileSync(
    fileURLToPath(new URL('../../src/pages/api/indexnow-key.ts', import.meta.url)),
    'utf8',
  );
  assert.match(sorgente, /import \{ rispostaStatoChiave \} from '\.\.\/\.\.\/lib\/indexnow-chiave';/);
  assert.match(sorgente, /rispostaStatoChiave\(import\.meta\.env\.INDEXNOW_API_KEY\)/);
  assert.doesNotMatch(sorgente, /new Response\(/);
});
