/**
 * Test di src/lib/ortografia.ts.
 *
 * Legge la STESSA tabella di casi del runner Python
 * (`backend/tests/test_ortografia.py`): e' la difesa contro la divergenza
 * fra i due normalizzatori gemelli.
 *
 *   node --experimental-strip-types --test tests/ortografia/ortografia.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { correggi, TABELLE, INTERNI } from '../../src/lib/ortografia.ts';
import { slugifica, slugValido } from '../../src/lib/slug.ts';

interface Caso {
  id: string;
  input: string;
  atteso: string;
  sha256: string;
  nota: string;
  correzioni?: number;
  segnalazioni?: number;
  saltato?: string | null;
}

const dati = JSON.parse(
  readFileSync(new URL('./casi.json', import.meta.url), 'utf8'),
) as {
  conteggio_minimo: number;
  casi: Caso[];
  casi_slug: [string, string][];
  tabelle: Record<string, unknown>;
};

test('nessuno puo cancellare casi in silenzio', () => {
  assert.ok(dati.casi.length >= dati.conteggio_minimo);
});

test('identificatori unici', () => {
  const visti = dati.casi.map((c) => c.id);
  assert.equal(visti.length, new Set(visti).size);
});

test('le tabelle coincidono con il fixture', () => {
  for (const nome of ['LISTA_2', 'LISTA_2B', 'SOLO_APOSTROFO', 'LISTA_3A', 'LISTA_3B']) {
    const nostra = (TABELLE as Record<string, [string, string][]>)[nome].map((v) => [v[0], v[1]]);
    assert.deepEqual(nostra, dati.tabelle[nome], nome);
  }
  assert.deepEqual(TABELLE.DENY, dati.tabelle.DENY);
  assert.deepEqual(TABELLE.PREPOSIZIONI_SE, dati.tabelle.PREPOSIZIONI_SE);
});

test('tabella dei casi condivisa', () => {
  for (const caso of dati.casi) {
    const risultato = correggi(caso.input);
    assert.equal(risultato.testo, caso.atteso, caso.id + ': ' + caso.nota);
    assert.equal(
      createHash('sha256').update(caso.atteso, 'utf8').digest('hex'),
      caso.sha256,
      caso.id + ": il fixture e' stato modificato senza rigenerare lo sha256",
    );
    if (caso.correzioni !== undefined) {
      assert.equal(risultato.correzioni.length, caso.correzioni, caso.id + ' correzioni');
    }
    if (caso.segnalazioni !== undefined) {
      assert.equal(risultato.segnalazioni.length, caso.segnalazioni, caso.id + ' segnalazioni');
    }
    if (Object.prototype.hasOwnProperty.call(caso, 'saltato')) {
      assert.equal(risultato.saltato, caso.saltato, caso.id + ' saltato');
    }
  }
});

test('idempotenza sul testo', () => {
  for (const caso of dati.casi) {
    const una = correggi(caso.input).testo;
    const due = correggi(una).testo;
    assert.equal(una, due, caso.id);
  }
});

test('la deny list non e mai correggibile', () => {
  for (const parola of TABELLE.DENY) {
    for (const variante of [
      parola,
      INTERNI.inizialeMaiuscola(parola),
      INTERNI.tuttoMaiuscolo(parola),
    ]) {
      assert.equal(INTERNI.MAPPA.has(variante), false, variante);
    }
  }
});

test('correggibili e segnalabili sono disgiunti', () => {
  for (const chiave of INTERNI.MAPPA.keys()) {
    assert.equal(INTERNI.SEGNALA_2B.has(chiave), false, chiave);
  }
});

test('accento giusto sui composti di -che', () => {
  const acuta = String.fromCharCode(0x00e9);
  const grave = String.fromCharCode(0x00e8);
  for (const nuda of ['perche', 'poiche', 'affinche', 'benche', 'nonche',
    'sicche', 'finche', 'purche', 'anziche']) {
    assert.ok(INTERNI.MAPPA.get(nuda)?.endsWith(acuta), nuda + ' deve finire con la e acuta');
  }
  assert.ok(INTERNI.MAPPA.get('cioe')?.endsWith(grave), 'cioe');
});

test('nessun metacarattere che diverge fra i due motori', () => {
  const sorgenti = [
    INTERNI.RE_PRINCIPALE.source,
    INTERNI.RE_SEGNALAZIONI.source,
    INTERNI.RE_SE_PREP.source,
    ...INTERNI.MASCHERE.map((m) => m[0].source),
  ];
  for (const sorgente of sorgenti) {
    for (const vietato of ['\\b', '\\B', '\\w', '\\W', '\\d', '\\D']) {
      assert.equal(sorgente.includes(vietato), false, sorgente.slice(0, 60));
    }
    // \s e' ammesso solo dentro l'idioma [\s\S] ("qualunque carattere")
    const s = sorgente.split('\\s').length - 1;
    const idioma = sorgente.split('[\\s\\S]').length - 1;
    assert.equal(s, idioma, sorgente.slice(0, 60));
    assert.equal(sorgente.includes('(?<'), false, sorgente.slice(0, 60));
  }
});

test('flag delle regex: sempre unicode, mai insensibile al caso', () => {
  const regex = [
    INTERNI.RE_PRINCIPALE,
    INTERNI.RE_SEGNALAZIONI,
    INTERNI.RE_SE_PREP,
    ...INTERNI.MASCHERE.map((m) => m[0]),
  ];
  for (const r of regex) {
    assert.equal(r.unicode, true, r.source.slice(0, 40));
    assert.equal(r.ignoreCase, false, r.source.slice(0, 40));
  }
});

test('nessuno stato di lastIndex fra chiamate', () => {
  const testo = "La citta' e' grande";
  const primo = correggi(testo).testo;
  const secondo = correggi(testo).testo;
  const terzo = correggi(testo).testo;
  assert.equal(primo, secondo);
  assert.equal(secondo, terzo);
});

test('gli URL non vengono mai alterati', () => {
  const testo =
    'Vedi https://www.miur.gov.it/universita/attivita?piu=1 e anche ' +
    '[la citta](https://comune.it/citta-metropolitana) e ' +
    "miur.gov.it/gia-fatto, poi perche' no.";
  const risultato = correggi(testo).testo;
  for (const frammento of [
    'https://www.miur.gov.it/universita/attivita?piu=1',
    'https://comune.it/citta-metropolitana',
    'miur.gov.it/gia-fatto',
  ]) {
    assert.ok(risultato.includes(frammento), frammento);
  }
  assert.ok(risultato.includes('perch' + String.fromCharCode(0x00e9)));
});

test('le ancore degli heading restano coerenti', () => {
  const risultato = correggi("## Perche' iscriversi {#perche-iscriversi}").testo;
  assert.ok(risultato.includes('{#perche-iscriversi}'));
  assert.ok(risultato.includes('Perch' + String.fromCharCode(0x00e9)));
});

test('slugifica: casi condivisi con backend/app/slug.py', () => {
  for (const [ingresso, atteso] of dati.casi_slug) {
    assert.equal(slugifica(ingresso), atteso, JSON.stringify(ingresso));
  }
});

test("slugifica: l'accento non sposta lo slug", () => {
  // L'invariante che rende sicura la correzione ortografica dei titoli: se
  // cadesse, correggere un accento cambierebbe l'URL e la vecchia pagina
  // risponderebbe 410.
  const a = String.fromCharCode(0xe0);
  const e = String.fromCharCode(0xe8);
  const acuta = String.fromCharCode(0xe9);
  for (const [sbagliato, corretto] of [
    ["Perche' e' cambiato tutto", 'Perch' + acuta + ' ' + e + ' cambiato tutto'],
    ['La citta cresce', 'La citt' + a + ' cresce'],
    ['universita statale', 'universit' + a + ' statale'],
  ]) {
    assert.equal(slugifica(sbagliato), slugifica(corretto), sbagliato);
  }
});

test('slugifica: gli slug attesi sono conformi', () => {
  for (const [, atteso] of dati.casi_slug) {
    if (atteso !== '') assert.equal(slugValido(atteso), true, atteso);
  }
});
