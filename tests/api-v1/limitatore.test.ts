/**
 * limitatore.ts: modalita' di fiducia, normalizzazione IP, chiave del client (§8.1),
 * token bucket con orologio finto, eviction e secchio di overflow.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  leggiModalitaFiducia, ipNormalizzato, chiaveIp, chiaveClient, Limitatore, intestazioniRateLimit,
} from '../../src/lib/api-v1/limitatore.ts';
import type { ModalitaFiducia } from '../../src/lib/api-v1/limitatore.ts';

// Un IP per ciascun ruolo. 162.158.0.0/15 e 173.245.48.0/20 sono range di Cloudflare.
const CF_V4 = '162.158.1.1';
const CF_V4_BIS = '173.245.48.5';
const CF_V6 = '2400:cb00::1';
const CLIENT = '198.51.100.7';
const FALSO = '1.1.1.1';
const ALTRO = '203.0.113.9';

function chiave(
  modalita: ModalitaFiducia,
  intestazioni: Record<string, string>,
  indirizzoDiretto: string | null = null,
): string {
  return chiaveClient({ intestazioni: new Headers(intestazioni), indirizzoDiretto, modalita });
}

test('leggiModalitaFiducia: default, valori noti, valori sconosciuti', () => {
  assert.deepEqual(leggiModalitaFiducia(undefined), { modalita: 'cloudflare', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia(null), { modalita: 'cloudflare', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia(''), { modalita: 'cloudflare', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia('   '), { modalita: 'cloudflare', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia('cloudflare'), { modalita: 'cloudflare', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia('nginx'), { modalita: 'nginx', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia(' diretta '), { modalita: 'diretta', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia('NGINX'), { modalita: 'nginx', riconosciuta: true });
  assert.deepEqual(leggiModalitaFiducia('nginx-rigida'), { modalita: 'cloudflare', riconosciuta: false });
  assert.deepEqual(leggiModalitaFiducia('constructor'), { modalita: 'cloudflare', riconosciuta: false });
  assert.deepEqual(leggiModalitaFiducia('__proto__'), { modalita: 'cloudflare', riconosciuta: false });
});

test('ipNormalizzato: IPv4, IPv6, mappati, zone, porte e spazzatura', () => {
  assert.deepEqual(ipNormalizzato('1.2.3.4'), { famiglia: 4, ip: '1.2.3.4' });
  assert.deepEqual(ipNormalizzato('  1.2.3.4 '), { famiglia: 4, ip: '1.2.3.4' });
  assert.deepEqual(ipNormalizzato('::ffff:1.2.3.4'), { famiglia: 4, ip: '1.2.3.4' });
  assert.deepEqual(ipNormalizzato('::FFFF:1.2.3.4'), { famiglia: 4, ip: '1.2.3.4' });
  assert.deepEqual(ipNormalizzato('0:0:0:0:0:ffff:102:304'), { famiglia: 4, ip: '1.2.3.4' });
  assert.deepEqual(ipNormalizzato('2001:DB8::1'), { famiglia: 6, ip: '2001:db8:0:0:0:0:0:1' });
  assert.deepEqual(ipNormalizzato('fe80::1%eth0'), { famiglia: 6, ip: 'fe80:0:0:0:0:0:0:1' });
  assert.deepEqual(ipNormalizzato('::'), { famiglia: 6, ip: '0:0:0:0:0:0:0:0' });
  for (const nonValido of [
    '', '   ', 'abc', '1.2.3', '1.2.3.4.5', '01.2.3.4', '256.1.1.1', '1.2.3.4:5678', '[::1]', '[::1]:80',
    '1.2.3.4%eth0', 'fe80::1%', '1:2:3:4:5:6:7:8:9', '::ffff:1.2.3', 'unknown', '1.2.3.4, 5.6.7.8',
  ]) {
    assert.equal(ipNormalizzato(nonValido), null, nonValido);
  }
});

test('chiaveIp: IPv4 intero, IPv6 al /64 con ogni scrittura dello stesso prefisso', () => {
  assert.equal(chiaveIp('1.2.3.4'), '4:1.2.3.4');
  assert.equal(chiaveIp('::ffff:1.2.3.4'), '4:1.2.3.4');
  const stessoPrefisso = [
    '2001:db8:1:2::5',
    '2001:DB8:1:2::5',
    '2001:0db8:0001:0002:0000:0000:0000:0005',
    '2001:db8:1:2:ffff:ffff:ffff:ffff',
    '2001:db8:1:2::',
    '2001:db8:1:2:0:0:1.2.3.4',
    '2001:db8:1:2::1.2.3.4',
    '2001:db8:1:2:a:b:c:d%eth0',
    ' 2001:db8:1:2::5 ',
  ];
  for (const ip of stessoPrefisso) assert.equal(chiaveIp(ip), '6:2001:db8:1:2', ip);
  assert.equal(chiaveIp('2001:db8:1:3::5'), '6:2001:db8:1:3');
  assert.notEqual(chiaveIp('2001:db8:1:3::5'), chiaveIp('2001:db8:1:2::5'));
  // '::' in testa, in mezzo, in coda
  assert.equal(chiaveIp('::1'), '6:0:0:0:0');
  assert.equal(chiaveIp('::'), '6:0:0:0:0');
  assert.equal(chiaveIp('1::'), '6:1:0:0:0');
  assert.equal(chiaveIp('2001:db8::1'), '6:2001:db8:0:0');
  assert.equal(chiaveIp('1:2:3::4:5'), '6:1:2:3:0');
  assert.equal(chiaveIp('1:2:3:4:5:6:7::'), '6:1:2:3:4');
  assert.equal(chiaveIp('::2:3:4:5:6:7:8'), '6:0:2:3:4');
  assert.equal(chiaveIp('abc'), null);
  assert.equal(chiaveIp('1.2.3.4:5678'), null);
});

test('cloudflare: ultimo hop di Cloudflare -> CF-Connecting-IP; client falsificato a sinistra ignorato', () => {
  // nginx con $proxy_add_x_forwarded_for: "<falso>, <client aggiunto da CF>, <hop CF aggiunto da nginx>"
  assert.equal(
    chiave('cloudflare', { 'X-Forwarded-For': `${FALSO}, ${CLIENT}, ${CF_V4}`, 'CF-Connecting-IP': CLIENT }),
    `4:${CLIENT}`,
  );
  // nginx che sovrascrive XFF con $remote_addr
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': CF_V4_BIS, 'CF-Connecting-IP': CLIENT }), `4:${CLIENT}`);
  // nginx che non tocca XFF: l'ultimo e' il client aggiunto da Cloudflare
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': `${FALSO}, ${CLIENT}`, 'CF-Connecting-IP': CLIENT }), `4:${CLIENT}`);
  // hop di Cloudflare IPv6 e client IPv6: chiave al /64
  assert.equal(
    chiave('cloudflare', { 'X-Forwarded-For': CF_V6, 'CF-Connecting-IP': '2001:db8:1:2::5' }),
    '6:2001:db8:1:2',
  );
  // hop di Cloudflare scritto come IPv4 mappato
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': `::ffff:${CF_V4}`, 'CF-Connecting-IP': CLIENT }), `4:${CLIENT}`);
  // CF-Connecting-IP mappato
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': CF_V4, 'CF-Connecting-IP': '::ffff:1.2.3.4' }), '4:1.2.3.4');
  // header in minuscolo o maiuscolo: Headers e' case-insensitive
  assert.equal(chiave('cloudflare', { 'x-forwarded-for': CF_V4, 'cf-connecting-ip': CLIENT }), `4:${CLIENT}`);
});

test('cloudflare: hop di Cloudflare ma CF-Connecting-IP assente o non valido -> ultimo hop', () => {
  const xff = { 'X-Forwarded-For': `${FALSO}, ${CF_V4}` };
  assert.equal(chiave('cloudflare', xff), `4:${CF_V4}`);
  for (const cattivo of ['', 'abc', '1.2.3', `${CLIENT}, ${ALTRO}`, `${CLIENT},`, '1.2.3.4:80', '[::1]']) {
    assert.equal(chiave('cloudflare', { ...xff, 'CF-Connecting-IP': cattivo }), `4:${CF_V4}`, cattivo);
  }
});

test('cloudflare: ultimo hop NON di Cloudflare -> CF-Connecting-IP ignorato', () => {
  // client che aggira Cloudflare e parla con nginx inventandosi gli header
  assert.equal(
    chiave('cloudflare', { 'X-Forwarded-For': `${FALSO}, ${CLIENT}`, 'CF-Connecting-IP': ALTRO }),
    `4:${CLIENT}`,
  );
  // Node raggiungibile direttamente senza XFF: vale l'indirizzo diretto, non CF-Connecting-IP
  assert.equal(chiave('cloudflare', { 'CF-Connecting-IP': ALTRO }, CLIENT), `4:${CLIENT}`);
  // un hop di Cloudflare a SINISTRA non conta: conta l'ultimo
  assert.equal(
    chiave('cloudflare', { 'X-Forwarded-For': `${CF_V4}, ${CLIENT}`, 'CF-Connecting-IP': ALTRO }),
    `4:${CLIENT}`,
  );
});

test('cloudflare: valori non validi in XFF saltati, ripiego sull\'indirizzo diretto, sconosciuto', () => {
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': `${CLIENT}, spazzatura, 1.2.3.4:80` }), `4:${CLIENT}`);
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': 'unknown, ' }, ALTRO), `4:${ALTRO}`);
  assert.equal(chiave('cloudflare', {}, ALTRO), `4:${ALTRO}`);
  assert.equal(chiave('cloudflare', {}, CF_V4), `4:${CF_V4}`);
  assert.equal(chiave('cloudflare', { 'CF-Connecting-IP': CLIENT }, CF_V4), `4:${CLIENT}`);
  assert.equal(chiave('cloudflare', {}, null), 'sconosciuto');
  assert.equal(chiave('cloudflare', { 'X-Forwarded-For': 'unknown' }, 'nonunip'), 'sconosciuto');
  assert.equal(chiave('cloudflare', { 'CF-Connecting-IP': CLIENT }, null), 'sconosciuto');
});

test('nginx: header dedicato solo se unico e valido, altrimenti algoritmo cloudflare', () => {
  const catena = { 'X-Forwarded-For': `${FALSO}, ${CF_V4}`, 'CF-Connecting-IP': CLIENT };
  assert.equal(chiave('nginx', { 'X-EduNews24-Client-IP': ALTRO, ...catena }), `4:${ALTRO}`);
  assert.equal(chiave('nginx', { 'X-EduNews24-Client-IP': ' 2001:db8:9:9::1 ' }), '6:2001:db8:9:9');
  // lista, vuoto, non valido, assente -> come cloudflare
  assert.equal(chiave('nginx', { 'X-EduNews24-Client-IP': `${ALTRO}, ${FALSO}`, ...catena }), `4:${CLIENT}`);
  assert.equal(chiave('nginx', { 'X-EduNews24-Client-IP': '', ...catena }), `4:${CLIENT}`);
  assert.equal(chiave('nginx', { 'X-EduNews24-Client-IP': 'abc', ...catena }), `4:${CLIENT}`);
  assert.equal(chiave('nginx', catena), `4:${CLIENT}`);
  assert.equal(chiave('nginx', { 'X-Forwarded-For': `${FALSO}, ${ALTRO}`, 'CF-Connecting-IP': CLIENT }), `4:${ALTRO}`);
  assert.equal(chiave('nginx', {}, null), 'sconosciuto');
});

test('diretta: solo l\'indirizzo diretto, header ignorati', () => {
  const header = { 'X-Forwarded-For': CLIENT, 'CF-Connecting-IP': CLIENT, 'X-EduNews24-Client-IP': CLIENT };
  assert.equal(chiave('diretta', header, ALTRO), `4:${ALTRO}`);
  assert.equal(chiave('diretta', header, '::1'), '6:0:0:0:0');
  assert.equal(chiave('diretta', header, '::ffff:127.0.0.1'), '4:127.0.0.1');
  assert.equal(chiave('diretta', header, null), 'sconosciuto');
  assert.equal(chiave('diretta', header, 'abc'), 'sconosciuto');
});

function orologioFinto(inizio = 1_000_000): { ora: () => number; avanza: (ms: number) => void } {
  let adesso = inizio;
  return { ora: () => adesso, avanza: (ms) => { adesso += ms; } };
}

test('token bucket: 60 consentite, poi 429; ricarica di 1 al secondo', () => {
  const t = orologioFinto();
  const l = new Limitatore({ capacita: 60, ricaricaPerSecondo: 1, maxChiavi: 100, orologio: t.ora });
  for (let i = 0; i < 60; i++) {
    const esito = l.consuma('4:1.2.3.4');
    assert.equal(esito.consentito, true, `richiesta ${i + 1}`);
    assert.equal(esito.rimanenti, 59 - i);
    assert.equal(esito.limite, 60);
    assert.equal(esito.retryAfterSecondi, 0);
    assert.equal(esito.ripristinoSecondi, i + 1);
  }
  const negato = l.consuma('4:1.2.3.4');
  assert.deepEqual(negato, { consentito: false, limite: 60, rimanenti: 0, ripristinoSecondi: 60, retryAfterSecondi: 1 });

  // un'altra chiave ha il suo secchio
  assert.equal(l.consuma('4:5.6.7.8').consentito, true);

  // mezzo secondo non basta, ma retry-after resta un intero >= 1
  t.avanza(500);
  const ancoraNegato = l.consuma('4:1.2.3.4');
  assert.equal(ancoraNegato.consentito, false);
  assert.equal(ancoraNegato.retryAfterSecondi, 1);
  assert.equal(ancoraNegato.ripristinoSecondi, 60);

  // un secondo dopo lo svuotamento: un gettone, una richiesta
  t.avanza(500);
  const uno = l.consuma('4:1.2.3.4');
  assert.equal(uno.consentito, true);
  assert.equal(uno.rimanenti, 0);
  assert.equal(l.consuma('4:1.2.3.4').consentito, false);

  // la ricarica si ferma alla capacita'
  t.avanza(10 * 60_000);
  let consentite = 0;
  while (l.consuma('4:1.2.3.4').consentito) consentite++;
  assert.equal(consentite, 60);
});

test('token bucket: ricarica frazionaria e orologio che torna indietro', () => {
  const t = orologioFinto();
  const l = new Limitatore({ capacita: 2, ricaricaPerSecondo: 0.5, maxChiavi: 10, orologio: t.ora });
  assert.equal(l.consuma('k').consentito, true);
  assert.equal(l.consuma('k').consentito, true);
  const negato = l.consuma('k');
  assert.equal(negato.consentito, false);
  assert.equal(negato.retryAfterSecondi, 2);
  assert.equal(negato.ripristinoSecondi, 4);
  t.avanza(-5_000);
  assert.equal(l.consuma('k').consentito, false, 'un orologio all\'indietro non regala gettoni');
  t.avanza(5_000 + 2_000);
  assert.equal(l.consuma('k').consentito, true);
});

test('token bucket: parametri non validi rifiutati', () => {
  const orologio = (): number => 0;
  assert.throws(() => new Limitatore({ capacita: 0, ricaricaPerSecondo: 1, maxChiavi: 1, orologio }), RangeError);
  assert.throws(() => new Limitatore({ capacita: 60, ricaricaPerSecondo: 0, maxChiavi: 1, orologio }), RangeError);
  assert.throws(() => new Limitatore({ capacita: 60, ricaricaPerSecondo: Number.NaN, maxChiavi: 1, orologio }), RangeError);
  assert.throws(() => new Limitatore({ capacita: 60, ricaricaPerSecondo: 1, maxChiavi: 0, orologio }), RangeError);
});

test('tetto della mappa: la piu\' vecchia esce solo se piena, altrimenti secchio __overflow__', () => {
  const t = orologioFinto();
  const l = new Limitatore({ capacita: 3, ricaricaPerSecondo: 1, maxChiavi: 2, orologio: t.ora });
  l.consuma('a');
  l.consuma('b');
  assert.equal(l.numeroChiavi, 2);

  // 'a' non e' ancora piena: 'c' e 'd' consumano dal secchio condiviso, senza entrare
  assert.equal(l.consuma('c').consentito, true);
  assert.equal(l.consuma('d').consentito, true);
  assert.equal(l.consuma('c').consentito, true);
  const overflowVuoto = l.consuma('e');
  assert.equal(overflowVuoto.consentito, false, 'il secchio condiviso e\' unico per tutte le chiavi nuove');
  assert.equal(l.numeroChiavi, 2);

  // le chiavi gia' tracciate non risentono dell'overflow
  assert.equal(l.consuma('a').consentito, true);

  // accesso ad 'a' -> la piu' vecchia ora e' 'b'; dopo 1 s 'b' e' tornata piena
  t.avanza(1_000);
  assert.equal(l.consuma('c').consentito, true);
  assert.equal(l.numeroChiavi, 2);
  // 'c' ha preso il posto di 'b' con un secchio suo, pieno
  assert.equal(l.consuma('c').consentito, true);
  assert.equal(l.consuma('c').rimanenti, 0);
  // 'a' e' ancora tracciata: aveva 1 gettone, +1 di ricarica, -1 ora
  assert.equal(l.consuma('a').rimanenti, 1);

  // 'b' torna come chiave nuova: la piu' vecchia ('c', vuota) non e' piena -> overflow,
  // che nel frattempo si e' ricaricato di 1 gettone
  const b = l.consuma('b');
  assert.equal(b.consentito, true);
  assert.equal(b.rimanenti, 0);
  assert.equal(l.consuma('b').consentito, false);
  assert.equal(l.numeroChiavi, 2);
});

test('tetto della mappa: con maxChiavi 1 e chiavi a rotazione nessuno supera la capacita\'', () => {
  const t = orologioFinto();
  const l = new Limitatore({ capacita: 5, ricaricaPerSecondo: 1, maxChiavi: 1, orologio: t.ora });
  let consentite = 0;
  for (let i = 0; i < 100; i++) if (l.consuma(`4:10.0.0.${i}`).consentito) consentite++;
  // 1 della prima chiave (entra nella mappa e non torna piena) + 5 dell'overflow condiviso
  assert.equal(consentite, 6);
  assert.equal(l.numeroChiavi, 1);
});

test('intestazioniRateLimit: interi come stringhe', () => {
  const t = orologioFinto();
  const l = new Limitatore({ capacita: 1, ricaricaPerSecondo: 1, maxChiavi: 10, orologio: t.ora });
  l.consuma('k');
  const esito = l.consuma('k');
  assert.deepEqual(intestazioniRateLimit(esito, '60;w=60'), {
    'RateLimit-Policy': '60;w=60',
    'RateLimit-Limit': '1',
    'RateLimit-Remaining': '0',
    'RateLimit-Reset': '1',
    'Retry-After': '1',
  });
  for (const valore of Object.values(intestazioniRateLimit(esito, '60;w=60'))) {
    assert.ok(typeof valore === 'string' && valore.length > 0);
  }
});
