/**
 * url.ts: URL dei media, delle schede, degli articoli e dell'API.
 * La suite gira con TZ=Asia/Kathmandu come le altre di api-v1 (qui nessuna data).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  hostValido, mimeVideo, urlApi, urlArticolo, urlMediaAssoluto, urlScheda,
} from '../../src/lib/api-v1/url.ts';

test('urlMediaAssoluto: valori assenti, vuoti, troppo lunghi o non analizzabili -> null', () => {
  for (const v of [null, undefined, 42, true, {}, [], '', '   ', '\t\n']) {
    assert.equal(urlMediaAssoluto(v), null, `atteso null per ${JSON.stringify(v)}`);
  }
  const base = 'https://x.it/';
  assert.equal(urlMediaAssoluto(base + 'a'.repeat(2048 - base.length)), base + 'a'.repeat(2048 - base.length));
  assert.equal(urlMediaAssoluto(base + 'a'.repeat(2049 - base.length)), null);
  assert.equal(urlMediaAssoluto('non un url'), null);
  assert.equal(urlMediaAssoluto('immagini/foto.jpg'), null);
  assert.equal(urlMediaAssoluto('https://x.it:99999/a.jpg'), null);
  assert.equal(urlMediaAssoluto('//'), null);
});

test('urlMediaAssoluto: schemi diversi da http(s) -> null', () => {
  for (const v of [
    'blob:https://edunews24.it/1b3c9d1e-7f00-4c1a-9a55-4d2d0b7e1a11',
    'data:image/png;base64,iVBORw0KGgo=',
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    'ftp://x.it/a.jpg',
    'mailto:redazione@edunews24.it',
    'file:///etc/passwd',
  ]) {
    assert.equal(urlMediaAssoluto(v), null, v);
  }
});

test('urlMediaAssoluto: credenziali -> null, ma una @ nel percorso e\' legittima', () => {
  assert.equal(urlMediaAssoluto('https://utente:segreto@x.it/a.jpg'), null);
  assert.equal(urlMediaAssoluto('https://utente@x.it/a.jpg'), null);
  assert.equal(urlMediaAssoluto('https://:segreto@x.it/a.jpg'), null);
  assert.equal(urlMediaAssoluto('https://edunews24.it@evil.example/a.jpg'), null);
  assert.equal(
    urlMediaAssoluto('https://img.example/foto-1440x752@IlSole24Ore.webp'),
    'https://img.example/foto-1440x752@IlSole24Ore.webp',
  );
});

test('urlMediaAssoluto: host malformati -> null', () => {
  for (const v of [
    'https://ex%22ample.com/a.jpg',
    'https://ex&ample.com/a.jpg',
    'https://ex..com/a.jpg',
    'https://example.com./a.jpg',
    'https://.example.com/a.jpg',
    `https://${'a'.repeat(64)}.com/a.jpg`,
    'https://ex!ample.com/a.jpg',
  ]) {
    assert.equal(urlMediaAssoluto(v), null, v);
  }
  assert.equal(urlMediaAssoluto(`https://${'a'.repeat(63)}.com/a.jpg`), `https://${'a'.repeat(63)}.com/a.jpg`);
  assert.equal(urlMediaAssoluto('http://[::1]/a.jpg'), 'http://[::1]/a.jpg');
  assert.equal(urlMediaAssoluto('https://cdn_1.example.com/a.jpg'), 'https://cdn_1.example.com/a.jpg');
  assert.equal(urlMediaAssoluto('https://exämple.com/a.jpg'), 'https://xn--exmple-cua.com/a.jpg');
});

test('urlMediaAssoluto: percorsi relativi e protocol-relative', () => {
  assert.equal(urlMediaAssoluto('/immagini/foto.webp'), 'https://edunews24.it/immagini/foto.webp');
  assert.equal(urlMediaAssoluto('/immagini/una foto.webp'), 'https://edunews24.it/immagini/una%20foto.webp');
  assert.equal(urlMediaAssoluto('  /immagini/foto.webp  '), 'https://edunews24.it/immagini/foto.webp');
  // WHATWG legge "/\evil" come "//evil": un percorso non deve uscire dal sito.
  assert.equal(urlMediaAssoluto('/\\evil.example/x.jpg'), null);
  assert.equal(urlMediaAssoluto('//cdn.example.com/x.jpg'), 'https://cdn.example.com/x.jpg');
  assert.equal(urlMediaAssoluto('//utente@cdn.example.com/x.jpg'), null);
});

test('urlMediaAssoluto: http(s) di terzi conservato e normalizzato', () => {
  assert.equal(
    urlMediaAssoluto('https://images.example.com/foto.jpg?quality=80&w=550'),
    'https://images.example.com/foto.jpg?quality=80&w=550',
  );
  assert.equal(
    urlMediaAssoluto('https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze-2026-27.webp'),
    'https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze-2026-27.webp',
  );
  assert.equal(urlMediaAssoluto('HTTP://Example.COM/A.jpg'), 'http://example.com/A.jpg');
  assert.equal(urlMediaAssoluto('https://example.com'), 'https://example.com/');
  assert.equal(urlMediaAssoluto('https://example.com:443/a.jpg'), 'https://example.com/a.jpg');
});

test('hostValido', () => {
  assert.equal(hostValido('edunews24.it'), true);
  assert.equal(hostValido('[2001:db8::1]'), true);
  assert.equal(hostValido(''), false);
  assert.equal(hostValido('[]'), false);
  assert.equal(hostValido('ex..com'), false);
  assert.equal(hostValido('ex"ample.com'), false);
});

test('urlArticolo: getArticlePublicUrl normalizzato', () => {
  assert.equal(urlArticolo('scuola', 'supplenze-2026-27'), 'https://edunews24.it/scuola/supplenze-2026-27');
  assert.equal(urlArticolo(' scuola ', ' supplenze '), 'https://edunews24.it/scuola/supplenze');
  assert.equal(urlArticolo('scuola', 'città-e-scuola'), 'https://edunews24.it/scuola/citt%C3%A0-e-scuola');
  assert.equal(urlArticolo('scuola', 'Titolo Con Spazi'), 'https://edunews24.it/scuola/Titolo%20Con%20Spazi');
});

test('urlArticolo: valori mancanti o che porterebbero a un\'altra pagina -> null', () => {
  for (const [categoria, slug] of [
    [null, 'x'], ['scuola', null], [undefined, undefined], [42, 'x'], ['scuola', 7],
    ['', 'x'], ['scuola', ''], ['scuola', '   '],
    ['scuola', 'a?b'], ['scuola', 'a#b'], ['scuola', 'a/b'], ['scuola', '..'], ['scuola', '.'],
    ['..', 'x'], ['\\evil', 'x'], ['scuola', 'a\\b'],
  ] as const) {
    assert.equal(urlArticolo(categoria, slug), null, `${String(categoria)} / ${String(slug)}`);
  }
});

test('urlScheda: basePath + slug sicuro', () => {
  assert.equal(urlScheda('/bandi', 'bando-regione-marche-2026'), 'https://edunews24.it/bandi/bando-regione-marche-2026');
  assert.equal(urlScheda('/selezione-personale', 'Addetti_2026'), 'https://edunews24.it/selezione-personale/Addetti_2026');
  assert.equal(urlScheda('/selezione-personale', 'a b/c?d#e'), 'https://edunews24.it/selezione-personale/a%20b%2Fc%3Fd%23e');
  assert.equal(urlScheda('/interpelli', 'città'), 'https://edunews24.it/interpelli/citt%C3%A0');
});

test('urlApi: BASE_API + percorso + query solo se non vuota', () => {
  assert.equal(urlApi(''), 'https://edunews24.it/api/v1');
  assert.equal(urlApi('/articles'), 'https://edunews24.it/api/v1/articles');
  assert.equal(urlApi('/articles', null), 'https://edunews24.it/api/v1/articles');
  assert.equal(urlApi('/articles', new URLSearchParams()), 'https://edunews24.it/api/v1/articles');
  assert.equal(
    urlApi('/articles', new URLSearchParams([['category', 'scuola'], ['limit', '1']])),
    'https://edunews24.it/api/v1/articles?category=scuola&limit=1',
  );
  // l'ordine e' quello ricevuto
  assert.equal(
    urlApi('/bandi', new URLSearchParams([['region', 'marche'], ['cursor', 'eyJ2Ijox-_']])),
    'https://edunews24.it/api/v1/bandi?region=marche&cursor=eyJ2Ijox-_',
  );
  assert.equal(
    urlApi('/articles', new URLSearchParams([['since', '2026-09-21T09:18:28+02:00']])),
    'https://edunews24.it/api/v1/articles?since=2026-09-21T09%3A18%3A28%2B02%3A00',
  );
  assert.equal(urlApi('/feeds/articles.json'), 'https://edunews24.it/api/v1/feeds/articles.json');
});

test('mimeVideo: estensione del percorso, query e frammento ignorati', () => {
  assert.equal(mimeVideo('https://x.it/video/a.mp4'), 'video/mp4');
  assert.equal(mimeVideo('https://x.it/video/a.MP4'), 'video/mp4');
  assert.equal(mimeVideo('https://x.it/video/a.mov'), 'video/quicktime');
  assert.equal(mimeVideo('https://x.it/video/a.MoV'), 'video/quicktime');
  assert.equal(mimeVideo('https://x.it/video/a.webm'), 'video/webm');
  assert.equal(mimeVideo('https://x.it/video/a.mp4?download=1'), 'video/mp4');
  assert.equal(mimeVideo('https://x.it/video/a.mp4#t=10'), 'video/mp4');
  assert.equal(mimeVideo('https://x.it/video/a?formato=.mp4'), null);
  assert.equal(mimeVideo('https://x.it/video/a.avi'), null);
  assert.equal(mimeVideo('https://x.it/video/a'), null);
  assert.equal(mimeVideo('https://x.mp4/'), null);
  assert.equal(mimeVideo('https://x.mp4'), null);
  assert.equal(mimeVideo('https://x.it/.mp4'), null);
  assert.equal(mimeVideo('/video/a.mp4?x=1'), 'video/mp4');
  assert.equal(mimeVideo(''), null);
});
