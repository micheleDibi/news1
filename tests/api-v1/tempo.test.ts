/**
 * tempo.ts: euristica di published_at, conversioni Europe/Rome, parametri istante.
 * La suite gira con TZ=Asia/Kathmandu (+05:45): un uso dell'ora locale romperebbe i test.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  analizzaTimestamp, fusoPresuntoPublishedAt, istantePublishedAt, istanteInterpello, istanteTimestamptz,
  istanteDaMuroRoma, rfc3339Roma, rfc822, giornoRoma, oggiRoma, muroRoma, muroUtc, giornoUtc, giornoValido,
  mezzanotteRoma, giornoSuccessivo, timestampValido, scadenzaPlausibile, leggiParametroIstante, offsetRomaMinuti,
} from '../../src/lib/api-v1/tempo.ts';

test('euristica di published_at: 0-3 decimali UTC, 4-6 Roma, offset esplicito', () => {
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28'), 'UTC');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28.1'), 'UTC');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28.17'), 'UTC');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28.177'), 'UTC');
  assert.equal(fusoPresuntoPublishedAt('2025-03-01T10:00:00.1234'), 'Europe/Rome');
  assert.equal(fusoPresuntoPublishedAt('2025-03-01T10:00:00.12345'), 'Europe/Rome');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T08:53:20.936282'), 'Europe/Rome');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28+00:00'), 'offset');
  assert.equal(fusoPresuntoPublishedAt('2026-09-21 07:18:28.177'), 'UTC');
  assert.equal(fusoPresuntoPublishedAt('2026-02-30T07:18:28'), null);
  assert.equal(fusoPresuntoPublishedAt('infinity'), null);
  assert.equal(fusoPresuntoPublishedAt('2026-09-21T07:18:28.1234567'), null);
});

test('istantePublishedAt e rfc3339Roma', () => {
  // editor attuale (UTC, millisecondi)
  assert.equal(istantePublishedAt('2026-09-21T07:18:28.177'), Date.UTC(2026, 8, 21, 7, 18, 28, 177));
  assert.equal(rfc3339Roma(istantePublishedAt('2026-09-21T07:18:28.177')!), '2026-09-21T09:18:28+02:00');
  // backend Python (ora di Roma, microsecondi)
  assert.equal(rfc3339Roma(istantePublishedAt('2026-09-21T08:53:20.936282')!), '2026-09-21T08:53:20+02:00');
  assert.equal(rfc3339Roma(istantePublishedAt('2026-01-15T10:00:00.123456')!), '2026-01-15T10:00:00+01:00');
  // errore noto documentato: editor precedente in ora di Roma con millisecondi (id 7614)
  assert.equal(rfc3339Roma(istantePublishedAt('2025-05-28T16:09:09.461')!), '2025-05-28T18:09:09+02:00');
  // 0 decimali -> UTC
  assert.equal(rfc3339Roma(istantePublishedAt('2026-09-21T07:12:29')!), '2026-09-21T09:12:29+02:00');
  // offset esplicito vince sempre
  assert.equal(istantePublishedAt('2026-09-21T09:18:28+02:00'), Date.UTC(2026, 8, 21, 7, 18, 28));
  assert.equal(istantePublishedAt(null), null);
  assert.equal(istantePublishedAt(42), null);
  assert.equal(istantePublishedAt('2026-13-01T00:00:00'), null);
});

test('cambi d\'ora di Roma: ora inesistente +01:00, ora ambigua +02:00', () => {
  // 29/03/2026: alle 02:00 si passa alle 03:00; 02:30 non esiste -> letta come +01:00
  assert.equal(istanteDaMuroRoma(2026, 3, 29, 2, 30, 0), Date.UTC(2026, 2, 29, 1, 30, 0));
  // 25/10/2026: 02:30 capita due volte -> +02:00
  assert.equal(istanteDaMuroRoma(2026, 10, 25, 2, 30, 0), Date.UTC(2026, 9, 25, 0, 30, 0));
  assert.equal(rfc3339Roma(Date.UTC(2026, 9, 25, 0, 30, 0)), '2026-10-25T02:30:00+02:00');
  assert.equal(rfc3339Roma(Date.UTC(2026, 9, 25, 1, 30, 0)), '2026-10-25T02:30:00+01:00');
  assert.equal(offsetRomaMinuti(Date.UTC(2026, 2, 29, 0, 59, 59)), 60);
  assert.equal(offsetRomaMinuti(Date.UTC(2026, 2, 29, 1, 0, 0)), 120);
  // la parte intera e' Rome-wall e segue Python su Rome: 6 decimali in ora legale
  assert.equal(rfc3339Roma(istantePublishedAt('2026-03-29T02:30:00.000001')!), '2026-03-29T03:30:00+02:00');
});

test('rfc3339Roma tronca al secondo', () => {
  assert.equal(rfc3339Roma(Date.UTC(2026, 8, 21, 7, 18, 28, 999)), '2026-09-21T09:18:28+02:00');
});

test('rfc822 per RSS', () => {
  assert.equal(rfc822(Date.UTC(2026, 8, 21, 7, 18, 28)), 'Mon, 21 Sep 2026 09:18:28 +0200');
  assert.equal(rfc822(Date.UTC(2026, 0, 1, 0, 0, 0)), 'Thu, 01 Jan 2026 01:00:00 +0100');
});

test('giorni di Roma e UTC', () => {
  assert.equal(giornoRoma(Date.UTC(2026, 5, 30, 21, 59, 59)), '2026-06-30');
  assert.equal(giornoRoma(Date.UTC(2026, 5, 30, 22, 0, 0)), '2026-07-01');
  assert.equal(oggiRoma(Date.UTC(2026, 11, 31, 23, 0, 0)), '2027-01-01');
  assert.equal(giornoUtc(Date.UTC(2026, 9, 6, 22, 0, 0)), '2026-10-06');
  assert.equal(mezzanotteRoma('2026-09-21'), Date.UTC(2026, 8, 20, 22, 0, 0));
  assert.equal(mezzanotteRoma('2026-01-10'), Date.UTC(2026, 0, 9, 23, 0, 0));
  assert.equal(mezzanotteRoma('2026-03-29'), Date.UTC(2026, 2, 28, 23, 0, 0));
  assert.equal(mezzanotteRoma('2026-10-25'), Date.UTC(2026, 9, 24, 22, 0, 0));
  assert.equal(giornoSuccessivo('2026-12-31'), '2027-01-01');
  assert.equal(giornoSuccessivo('2028-02-28'), '2028-02-29');
  assert.equal(giornoSuccessivo('2026-02-28'), '2026-03-01');
  assert.equal(muroUtc(Date.UTC(2026, 8, 21, 7, 18, 28, 500)), '2026-09-21T07:18:28');
  assert.equal(muroRoma(Date.UTC(2026, 8, 21, 7, 18, 28, 500)), '2026-09-21T09:18:28');
  assert.equal(giornoValido('2026-02-29'), null);
  assert.equal(giornoValido('2028-02-29'), '2028-02-29');
  assert.equal(giornoValido('2026-9-1'), null);
  assert.equal(giornoValido(20260901), null);
});

test('colonne: interpelli (muro di Roma) e timestamptz', () => {
  assert.equal(rfc3339Roma(istanteInterpello('2026-09-17T00:00:00')!), '2026-09-17T00:00:00+02:00');
  assert.equal(rfc3339Roma(istanteInterpello('2026-02-20T00:00:00')!), '2026-02-20T00:00:00+01:00');
  assert.equal(istanteTimestamptz('2026-10-06T21:59:00+00:00'), Date.UTC(2026, 9, 6, 21, 59, 0));
  assert.equal(rfc3339Roma(istanteTimestamptz('2026-10-06T21:59:00+00:00')!), '2026-10-06T23:59:00+02:00');
  assert.equal(istanteTimestamptz('2026-09-14T16:03:02.418+00:00'), Date.UTC(2026, 8, 14, 16, 3, 2, 418));
  assert.equal(istanteTimestamptz(null), null);
});

test('timestampValido', () => {
  assert.equal(timestampValido(2026, 2, 29), false);
  assert.equal(timestampValido(2028, 2, 29), true);
  assert.equal(timestampValido(2026, 4, 31), false);
  assert.equal(timestampValido(2026, 0, 1), false);
  assert.equal(timestampValido(2026, 13, 1), false);
  assert.equal(timestampValido(2026, 1, 0), false);
  assert.equal(timestampValido(0, 1, 1), false);
  assert.equal(timestampValido(5026, 1, 1), true);
  assert.equal(timestampValido(2026, 1, 1, 24, 0, 0), false);
  assert.equal(timestampValido(2026, 1, 1, 23, 60, 0), false);
  assert.equal(timestampValido(2026, 1, 1, 23, 59, 60), false);
  assert.equal(analizzaTimestamp('2026-01-01T00:00:00+16:00'), null);
  assert.equal(analizzaTimestamp('2026-01-01T00:00:00+05:60'), null);
  assert.deepEqual(analizzaTimestamp('2026-01-01T00:00:00.5+05:45')?.offsetMinuti, 345);
});

test('scadenzaPlausibile: 8 anni dalla data di riferimento', () => {
  const ancora = Date.UTC(2026, 0, 1);
  const otto = 8 * 365.25 * 24 * 60 * 60 * 1000;
  assert.equal(scadenzaPlausibile(ancora + otto, ancora), true);
  assert.equal(scadenzaPlausibile(ancora + otto + 1, ancora), false);
  assert.equal(scadenzaPlausibile(Date.UTC(5026, 0, 1), ancora), false);
  assert.equal(scadenzaPlausibile(Date.UTC(5026, 0, 1), null), true);
});

test('leggiParametroIstante', () => {
  assert.equal(leggiParametroIstante('2026-09-21', 'inizio'), Date.UTC(2026, 8, 20, 22));
  assert.equal(leggiParametroIstante('2026-09-21', 'fine'), Date.UTC(2026, 8, 21, 22));
  const atteso = Date.UTC(2026, 8, 21, 7, 18, 28);
  assert.equal(leggiParametroIstante('2026-09-21T09:18:28+02:00', 'inizio'), atteso);
  assert.equal(leggiParametroIstante('2026-09-21T09:18:28 02:00', 'inizio'), atteso);
  assert.equal(leggiParametroIstante('2026-09-21T07:18:28Z', 'inizio'), atteso);
  assert.equal(leggiParametroIstante('2026-09-21T07:18:28.500Z', 'inizio'), atteso);
  assert.equal(leggiParametroIstante('2026-09-21t07:18:28.999999999z', 'fine'), atteso);
  for (const non of [
    '2026-09-21T09:18:28', '2026-02-30', '1999-12-31', '2101-01-01', '2026-09-21T24:00:00Z',
    '2026-09-21T09:18:28+15:00', '2026-09-21 09:18:28Z', '21/09/2026', '', 'oggi', '2026-09-21T09:18Z',
  ]) {
    assert.equal(leggiParametroIstante(non, 'inizio'), null, non);
  }
});

test('forma canonica idempotente, anche ai cambi d\'ora', () => {
  const inizio = Date.UTC(2026, 0, 1);
  for (let i = 0; i < 2000; i++) {
    const ms = inizio + i * 4_391_117_311 % (400 * 24 * 3600 * 1000) + (i % 1000);
    const canonico = rfc3339Roma(ms);
    const riletto = leggiParametroIstante(canonico, 'inizio');
    assert.equal(riletto, Math.floor(ms / 1000) * 1000, canonico);
    assert.equal(rfc3339Roma(riletto!), canonico);
  }
});

test('indipendente dal fuso del processo', () => {
  const originale = process.env.TZ;
  try {
    for (const tz of ['UTC', 'Europe/Rome', 'America/Los_Angeles', 'Pacific/Chatham', 'Asia/Kathmandu']) {
      process.env.TZ = tz;
      assert.equal(rfc3339Roma(istantePublishedAt('2026-09-21T07:18:28.177')!), '2026-09-21T09:18:28+02:00', tz);
      assert.equal(rfc3339Roma(istantePublishedAt('2026-09-21T08:53:20.936282')!), '2026-09-21T08:53:20+02:00', tz);
      assert.equal(giornoRoma(Date.UTC(2026, 5, 30, 22)), '2026-07-01', tz);
      assert.equal(mezzanotteRoma('2026-10-25'), Date.UTC(2026, 9, 24, 22), tz);
      assert.equal(leggiParametroIstante('2026-09-21', 'fine'), Date.UTC(2026, 8, 21, 22), tz);
      assert.equal(rfc822(Date.UTC(2026, 8, 21, 7, 18, 28)), 'Mon, 21 Sep 2026 09:18:28 +0200', tz);
    }
  } finally {
    if (originale === undefined) delete process.env.TZ;
    else process.env.TZ = originale;
  }
});
