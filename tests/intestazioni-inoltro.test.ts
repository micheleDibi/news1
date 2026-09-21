/**
 * Guardia sugli header di inoltro (src/lib/intestazioni-inoltro.ts).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { verificaIntestazioniInoltro } from '../src/lib/intestazioni-inoltro.ts';

const verifica = (h: Record<string, string>) => verificaIntestazioniInoltro(new Headers(h));

test('accetta le richieste normali', () => {
  assert.equal(verifica({}), null);
  assert.equal(verifica({ host: '127.0.0.1:4000' }), null);
  assert.equal(verifica({ host: 'edunews24.it' }), null);
  assert.equal(verifica({ host: 'linkinbio.edunews24.it' }), null);
  assert.equal(verifica({ host: '[::1]:4000' }), null);
  assert.equal(verifica({ 'x-forwarded-proto': 'https' }), null);
  assert.equal(verifica({ 'x-forwarded-proto': 'https, http' }), null);
  assert.equal(verifica({ 'x-forwarded-host': 'edunews24.it' }), null);
  assert.equal(verifica({ 'x-forwarded-host': 'edunews24.it:443' }), null);
  assert.equal(verifica({ 'x-forwarded-host': 'edunews24.it.' }), null);
  assert.equal(verifica({ 'x-forwarded-host': 'a.edunews24.it, b.example' }), null);
  assert.equal(verifica({ 'x-forwarded-host': 'servizio_interno:8080' }), null);
  assert.equal(verifica({ 'x-forwarded-port': '443' }), null);
});

test('rifiuta X-Forwarded-Host che sposta il path o la query', () => {
  for (const valore of [
    'edunews24.it/api/interpelli?',
    'edunews24.it\\api',
    'edunews24.it#x',
    'user@edunews24.it',
    'edunews24.it?x=1',
    '',
    ' ',
    'edunews24.it, ',
    'edu news24.it',
    'edunews24.it:443/x',
    'a'.repeat(300),
  ]) {
    assert.equal(verifica({ 'x-forwarded-host': valore }), 'x-forwarded-host', JSON.stringify(valore));
  }
});

test('rifiuta X-Forwarded-Proto diverso da http/https', () => {
  for (const valore of ['https://x/y?', 'http, x:admin?', 'ftp', 'HTTPS', '']) {
    assert.equal(verifica({ 'x-forwarded-proto': valore }), 'x-forwarded-proto', valore);
  }
});

test('rifiuta X-Forwarded-Port non numerico', () => {
  for (const valore of ['443/x?', '443x', '', '123456']) {
    assert.equal(verifica({ 'x-forwarded-port': valore }), 'x-forwarded-port', valore);
  }
});

test('Host conta solo senza X-Forwarded-Host', () => {
  assert.equal(verifica({ host: 'edunews24.it/x?' }), 'host');
  assert.equal(verifica({ host: 'edunews24.it/x?', 'x-forwarded-host': 'edunews24.it' }), null);
});
