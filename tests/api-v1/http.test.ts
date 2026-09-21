/**
 * http.ts: header comuni, problem+json, ETag/304, preflight.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CACHE_CONTROL, corpoProblema, etagDebole, ifNoneMatchCorrisponde, rispostaProblema, rispostaContenuto,
  risposta304, rispostaPreflight, TIPO_JSON, TIPO_PROBLEMA,
} from '../../src/lib/api-v1/http.ts';
import { CODICI_ERRORE, ProblemaApi } from '../../src/lib/api-v1/errori.ts';

function comuni(r: Response) {
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  assert.equal(r.headers.get('X-Robots-Tag'), 'noindex');
  assert.equal(r.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.equal(r.headers.get('Vary'), 'Accept-Encoding');
  assert.equal(r.headers.get('RateLimit-Policy'), '60;w=60');
  assert.equal(r.headers.get('Access-Control-Allow-Credentials'), null);
  assert.equal(r.headers.get('Set-Cookie'), null);
}

test('problem+json: instance assoluto senza query, type con ancora', async () => {
  const p = new ProblemaApi('invalid-parameter', 'La richiesta contiene un parametro non valido.', {
    errori: [{ parameter: 'category', detail: 'Categoria sconosciuta.', allowed: ['scuola'] }],
  });
  const corpo = JSON.parse(corpoProblema(p, '/api/v1/articles'));
  assert.deepEqual(Object.keys(corpo), ['type', 'title', 'status', 'detail', 'instance', 'code', 'errors']);
  assert.equal(corpo.type, 'https://edunews24.it/sviluppatori/api#error-invalid-parameter');
  assert.equal(corpo.instance, 'https://edunews24.it/api/v1/articles');
  assert.equal(corpo.status, 400);
  const r = rispostaProblema(p, '/api/v1/articles');
  assert.equal(r.status, 400);
  assert.equal(r.headers.get('Content-Type'), TIPO_PROBLEMA);
  assert.equal(r.headers.get('Cache-Control'), 'public, max-age=60, s-maxage=60');
  comuni(r);
  assert.match(r.headers.get('Link') ?? '', /rel="service-desc".*rel="terms-of-service"/);
  assert.deepEqual((await r.json()).errors[0].allowed, ['scuola']);
});

test('ogni codice ha forma kebab-case e status coerente; 405/429/5xx no-store', () => {
  for (const codice of CODICI_ERRORE) {
    assert.match(codice, /^[a-z]+(-[a-z]+)*$/);
    const r = rispostaProblema(new ProblemaApi(codice, 'x', { retryAfter: codice === 'rate-limited' ? 17 : null }), '/api/v1/bandi');
    if (r.status === 400 || r.status === 404) assert.equal(r.headers.get('Cache-Control'), 'public, max-age=60, s-maxage=60');
    else assert.equal(r.headers.get('Cache-Control'), 'no-store', codice);
    if (codice === 'method-not-allowed') assert.equal(r.headers.get('Allow'), 'GET, HEAD, OPTIONS');
    if (codice === 'rate-limited') assert.equal(r.headers.get('Retry-After'), '17');
  }
});

test('corpo problema con retry_after e first', () => {
  const corpo = JSON.parse(corpoProblema(new ProblemaApi('invalid-cursor', 'x', { primo: 'https://edunews24.it/api/v1/articles' }), '/api/v1/articles'));
  assert.equal(corpo.first, 'https://edunews24.it/api/v1/articles');
  assert.equal('retry_after' in corpo, false);
  const c2 = JSON.parse(corpoProblema(new ProblemaApi('service-unavailable', 'x', { retryAfter: 30 }), '/api/v1/articles'));
  assert.equal(c2.retry_after, 30);
});

test('ETag debole e If-None-Match', () => {
  const e = etagDebole('{"a":1}');
  assert.match(e, /^W\/"[A-Za-z0-9_-]{27}"$/);
  assert.equal(etagDebole('{"a":1}'), e);
  assert.notEqual(etagDebole('{"a":2}'), e);
  assert.equal(ifNoneMatchCorrisponde(e, e), true);
  assert.equal(ifNoneMatchCorrisponde(e.slice(2), e), true);
  assert.equal(ifNoneMatchCorrisponde(`"x", ${e}`, e), true);
  assert.equal(ifNoneMatchCorrisponde('*', e), true);
  assert.equal(ifNoneMatchCorrisponde('W/"altro"', e), false);
  assert.equal(ifNoneMatchCorrisponde(null, e), false);
});

test('200 e 304 con gli stessi header', () => {
  const opzioni = { contentType: TIPO_JSON, profilo: 'elenco' as const, etag: 'W/"abc"', link: ['<https://edunews24.it/api/v1/articles?cursor=x>; rel="next"'] };
  const r = rispostaContenuto('{}', opzioni);
  comuni(r);
  assert.equal(r.headers.get('Cache-Control'), CACHE_CONTROL.get('elenco'));
  assert.equal(r.headers.get('ETag'), 'W/"abc"');
  assert.match(r.headers.get('Link') ?? '', /^<https:\/\/edunews24\.it\/api\/v1\/articles\?cursor=x>; rel="next", /);
  const n = risposta304(opzioni);
  assert.equal(n.status, 304);
  assert.equal(n.headers.get('ETag'), 'W/"abc"');
  assert.equal(n.headers.get('Cache-Control'), CACHE_CONTROL.get('elenco'));
  assert.equal(n.headers.get('Content-Type'), null);
  comuni(n);
});

test('preflight', () => {
  const r = rispostaPreflight();
  assert.equal(r.status, 204);
  assert.equal(r.headers.get('Access-Control-Allow-Methods'), 'GET, HEAD, OPTIONS');
  assert.equal(r.headers.get('Access-Control-Max-Age'), '86400');
  comuni(r);
});
