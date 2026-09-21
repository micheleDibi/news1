/**
 * public/robots.txt: il JSON di /api/v1 resta escluso, i feed sono consentiti.
 * Mini valutatore RFC 9309: gruppi per user-agent (senza ereditare dal gruppo *),
 * regola con il percorso piu' lungo, a parita' vince Allow; '*' e '$' supportati.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

interface Regola { consenti: boolean; percorso: string }
interface Gruppo { agenti: string[]; regole: Regola[] }

function analizza(testo: string): Gruppo[] {
  const gruppi: Gruppo[] = [];
  let corrente: Gruppo | null = null;
  let ultimaEraAgente = false;
  for (const grezza of testo.split('\n')) {
    const riga = grezza.replace(/#.*$/, '').trim();
    if (!riga) continue;
    const i = riga.indexOf(':');
    if (i < 0) continue;
    const chiave = riga.slice(0, i).trim().toLowerCase();
    const valore = riga.slice(i + 1).trim();
    if (chiave === 'user-agent') {
      if (!corrente || !ultimaEraAgente) {
        corrente = { agenti: [], regole: [] };
        gruppi.push(corrente);
      }
      corrente.agenti.push(valore.toLowerCase());
      ultimaEraAgente = true;
    } else {
      ultimaEraAgente = false;
      if (!corrente) continue;
      if (chiave === 'allow' || chiave === 'disallow') {
        if (valore) corrente.regole.push({ consenti: chiave === 'allow', percorso: valore });
      }
    }
  }
  return gruppi;
}

function corrisponde(schema: string, percorso: string): boolean {
  const ancorato = schema.endsWith('$');
  const corpo = (ancorato ? schema.slice(0, -1) : schema)
    .split('*').map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*');
  return new RegExp('^' + corpo + (ancorato ? '$' : '')).test(percorso);
}

function consentito(gruppi: Gruppo[], agente: string, percorso: string): boolean {
  const a = agente.toLowerCase();
  const specifici = gruppi.filter((g) => g.agenti.some((x) => x !== '*' && a.includes(x)));
  const scelti = specifici.length > 0 ? specifici : gruppi.filter((g) => g.agenti.includes('*'));
  let migliore: Regola | null = null;
  for (const regola of scelti.flatMap((g) => g.regole)) {
    if (!corrisponde(regola.percorso, percorso)) continue;
    const lunghezza = regola.percorso.length;
    if (!migliore || lunghezza > migliore.percorso.length || (lunghezza === migliore.percorso.length && regola.consenti)) {
      migliore = regola;
    }
  }
  return migliore ? migliore.consenti : true;
}

const gruppi = analizza(readFileSync(new URL('../../public/robots.txt', import.meta.url), 'utf8'));

test('JSON della v1 escluso, feed consentiti, per * e per i bot con gruppo proprio', () => {
  for (const agente of ['Mozilla/5.0 (compatible; Googlebot/2.1)', 'bingbot/2.0', 'msnbot', 'AhrefsBot/7.0', 'SemrushBot', 'QualsiasiBot']) {
    for (const vietato of ['/api/v1', '/api/v1/', '/api/v1/articles?limit=1', '/api/v1/openapi.json', '/api/v1/bandi/1', '/api/v1/categories']) {
      assert.equal(consentito(gruppi, agente, vietato), false, `${agente} ${vietato}`);
    }
    for (const ammesso of ['/api/v1/feeds/articles.xml', '/api/v1/feeds/articles/scuola.json', '/api/v1/feeds/bandi.xml', '/', '/scuola']) {
      assert.equal(consentito(gruppi, agente, ammesso), true, `${agente} ${ammesso}`);
    }
  }
});

test('regole preesistenti invariate per il gruppo *', () => {
  assert.equal(consentito(gruppi, 'Googlebot', '/api/search'), true);
  assert.equal(consentito(gruppi, 'Googlebot', '/api/articlestest'), false);
  assert.equal(consentito(gruppi, 'Googlebot', '/admin/x'), false);
});
