/**
 * I moduli puri di /api/v1 non devono tirarsi dietro client Supabase, variabili
 * d'ambiente, ora locale o import che strip-types non gestisce; fonte-supabase.ts
 * non deve contenere filtri scritti a mano (stanno tutti nel piano di filtri.ts).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';

const cartella = new URL('../../src/lib/api-v1/', import.meta.url);
const IMPURI = new Set(['fonte-supabase.ts', 'rotta.ts']);
const puri = readdirSync(cartella).filter((f) => f.endsWith('.ts') && !IMPURI.has(f));
const foglie = [
  new URL('../../src/lib/stato-bando.ts', import.meta.url),
  new URL('../../src/lib/liste/slug-interpello.ts', import.meta.url),
  new URL('../../src/lib/intestazioni-inoltro.ts', import.meta.url),
  // Dominio bandi (piano §16.3.7): un modulo, un test omonimo in tests/estrazioni/.
  // Sono foglie per forza: la scheda e le liste le usano, ma anche i test devono
  // poterle caricare sotto `node --test`, dove non esiste nessuna PUBLIC_*.
  new URL('../../src/config/domini-aggregatori.ts', import.meta.url),
  new URL('../../src/lib/bandi/tipi.ts', import.meta.url),
  new URL('../../src/lib/bandi/domini.ts', import.meta.url),
  new URL('../../src/lib/bandi/contenuto.ts', import.meta.url),
  new URL('../../src/lib/bandi/testi-stato.ts', import.meta.url),
  new URL('../../src/lib/bandi/filtro-stato.ts', import.meta.url),
  new URL('../../src/lib/bandi/cta.ts', import.meta.url),
  new URL('../../src/lib/bandi/jsonld.ts', import.meta.url),
  new URL('../../src/lib/bandi/pubblicazione.ts', import.meta.url),
  new URL('../../src/lib/bandi/slug-storico.ts', import.meta.url),
  new URL('../../src/lib/bandi/aggiornamenti.ts', import.meta.url),
];

function sorgente(url: URL): string {
  // senza commenti, per non segnalare le spiegazioni
  return readFileSync(url, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

test('moduli puri: niente dipendenze impure ne\' costrutti vietati', () => {
  assert.ok(puri.length >= 20, `trovati solo ${puri.length} moduli`);
  for (const url of [...puri.map((f) => new URL(f, cartella)), ...foglie]) {
    const s = sorgente(url);
    const nome = url.pathname.split('/').slice(-2).join('/');
    for (const vietato of [
      /from ['"][^'"]*\/supabase['"]/, /from ['"][^'"]*\/supabase-bandi['"]/, /from ['"][^'"]*\/corpus['"]/,
      /from ['"][^'"]*\/categories['"]/, /from ['"][^'"]*\/logger['"]/, /import\.meta\.env/, /\bprocess\.env\b/, /from ['"]@\//,
      /from ['"][^'"]+\.ts['"]/, /import\s*\{\s*type\s+\w+(\s*,\s*type\s+\w+)*\s*,?\s*\}\s*from/, /\bsetInterval\s*\(/,
      /^\s*(export\s+)?(declare\s+)?(const\s+)?enum\s+\w+/m, /^\s*(export\s+)?(declare\s+)?namespace\s+\w+/m, /\.getHours\(|\.getDate\(|\.getMonth\(|\.getFullYear\(|\.getDay\(/,
      /\.toLocale(Date|Time)?String\(/, /\bany\b(?=[\s,;>)\]])/,
    ]) {
      assert.equal(vietato.test(s), false, `${nome}: ${vietato}`);
    }
  }
});

test('fonte-supabase.ts: solo cablaggio', () => {
  const s = sorgente(new URL('fonte-supabase.ts', cartella));
  for (const vietato of [
    '.eq(', '.neq(', '.in(', '.gt(', '.gte(', '.lt(', '.lte(', '.like(', '.ilike(', '.contains(', '.overlaps(',
    '.range(', '.match(', '.single(', '.maybeSingle(', '.not(', 'isdraft', 'stato_processing', 'completed', "'*'",
  ]) {
    assert.equal(s.includes(vietato), false, vietato);
  }
  assert.equal(/^\s*let\s/m.test(s.replace(/\n {2,}let query[^\n]*/g, '')), false, 'stato a livello di modulo');
});

test('i moduli puri si importano sotto node senza variabili d\'ambiente', async () => {
  for (const f of puri) {
    await import(new URL(f, cartella).href);
  }
  for (const url of foglie) {
    await import(url.href);
  }
});
