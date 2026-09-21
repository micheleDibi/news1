/**
 * feed.ts: percorsi dei feed, JSON Feed 1.1 e RSS 2.0.
 * La suite gira con TZ=Asia/Kathmandu; la riga "Scadenza" si prova anche con altri fusi.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  analizzaPercorsoFeed, elemento, metadatiFeed, serializzaJsonFeed, serializzaRss, testoXml,
} from '../../src/lib/api-v1/feed.ts';
import { sezioneDto } from '../../src/lib/api-v1/sezioni.ts';
import { CONTENT_SIGNAL, URL_TERMINI } from '../../src/lib/api-v1/costanti.ts';
import type { ArticoloDto, BandoDto, InterpelloDto, SelezioneDto } from '../../src/lib/api-v1/contratto.ts';

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

function articolo(sovrascritture: Partial<ArticoloDto> = {}): ArticoloDto {
  return {
    type: 'article',
    id: 39382,
    slug: 'supplenze-2026-27',
    url: 'https://edunews24.it/scuola/supplenze-2026-27',
    title: 'Supplenze 2026/27',
    title_summary: null,
    excerpt: 'Estratto breve.',
    summary: 'Sintesi dell\'articolo.',
    category: { slug: 'scuola', name: 'Scuola', color: '#2D6A4F', url: 'https://edunews24.it/scuola' },
    secondary_categories: [],
    image_url: 'https://cdn.example.org/a.webp',
    thumbnail_url: null,
    video: null,
    published_at: '2026-09-21T09:18:28+02:00',
    tags: ['supplenze', 'Scuola', 'gps'],
    author: { name: 'Redazione EduNews24' },
    ...sovrascritture,
  };
}

function selezione(sovrascritture: Partial<SelezioneDto> = {}): SelezioneDto {
  return {
    type: 'selezione-personale',
    id: 23258,
    slug: 'arpam-marche-29611',
    url: 'https://edunews24.it/selezione-personale/arpam-marche-29611',
    title: 'ARPAM Marche, avviso pubblico',
    summary: 'Candidature aperte.',
    section: sezioneDto('selezione-personale'),
    published_at: '2026-09-21T00:01:00+02:00',
    updated_at: '2026-09-21T08:04:01+02:00',
    deadline_on: '2026-10-06',
    deadline_at: '2026-10-06T23:59:00+02:00',
    status: 'open',
    regions: [{ slug: 'marche', name: 'Marche' }],
    national: false,
    details: {
      official_title: null, code: '29611', position: null, positions_count: null, procedure_type: null,
      categories: [], sectors: [], organizations: [], locations: [], salary_min: null, salary_max: null,
    },
    ...sovrascritture,
  };
}

function interpello(sovrascritture: Partial<InterpelloDto> = {}): InterpelloDto {
  return {
    type: 'interpello',
    id: 1523,
    slug: 'ic-mazzini-roma-lazio-1523',
    url: 'https://edunews24.it/interpelli/ic-mazzini-roma-lazio-1523',
    title: 'Interpello IC Mazzini',
    summary: null,
    section: sezioneDto('interpelli'),
    published_at: '2026-09-18T00:00:00+02:00',
    updated_at: null,
    deadline_on: null,
    deadline_at: null,
    status: null,
    regions: [],
    national: false,
    details: { official_title: null, competition_class: 'A022', province: 'Roma', city: null },
    ...sovrascritture,
  };
}

function bando(sovrascritture: Partial<BandoDto> = {}): BandoDto {
  return {
    type: 'bando',
    id: 4821,
    slug: 'voucher-pmi',
    url: 'https://edunews24.it/bandi/voucher-pmi',
    title: 'Voucher PMI',
    summary: 'Contributi a fondo perduto.',
    section: sezioneDto('bandi'),
    published_at: '2026-09-15T10:42:07+02:00',
    updated_at: '2026-09-20T03:12:55+02:00',
    deadline_on: '2026-11-30',
    deadline_at: null,
    status: 'open',
    regions: [{ slug: 'marche', name: 'Marche' }, { slug: 'lazio', name: 'Lazio' }],
    national: true,
    details: {
      short_title: null, issuer: null, geographic_area: null, topics: [], kind: null, program: null,
      funding_method: null, sectors: [], beneficiaries: [], ateco_codes: [], total_amount_eur: null,
      max_amount_per_project_eur: null, opens_on: null, source_published_on: null,
    },
    ...sovrascritture,
  };
}

const META_ARTICOLI = metadatiFeed({ risorsa: 'articles', categoria: null, formato: 'json' }, null);
const META_SELEZIONE = metadatiFeed({ risorsa: 'selezione-personale', categoria: null, formato: 'xml' }, null);

type Oggetto = Record<string, unknown>;

function jsonFeed(elementi: Parameters<typeof serializzaJsonFeed>[1]): { feed: Oggetto; voci: Oggetto[] } {
  const feed = JSON.parse(serializzaJsonFeed(META_ARTICOLI, elementi)) as Oggetto;
  return { feed, voci: feed.items as Oggetto[] };
}

/** Nessun membro null, '' o [] fuori dalle estensioni _edunews24. */
function membriVuoti(valore: unknown, percorso: string, trovati: string[]): string[] {
  if (Array.isArray(valore)) {
    valore.forEach((v, i) => membriVuoti(v, `${percorso}[${i}]`, trovati));
  } else if (valore !== null && typeof valore === 'object') {
    for (const [chiave, figlio] of Object.entries(valore)) {
      if (chiave === '_edunews24') continue;
      if (figlio === null || figlio === '' || (Array.isArray(figlio) && figlio.length === 0)) {
        trovati.push(`${percorso}.${chiave}`);
      }
      membriVuoti(figlio, `${percorso}.${chiave}`, trovati);
    }
  }
  return trovati;
}

/** Controllo minimo di buona forma: tag bilanciati, nessuna & fuori da un'entita', nessun < nudo nel testo. */
function verificaXmlBenFormato(xml: string): void {
  assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n'));
  const corpo = xml.slice(xml.indexOf('\n') + 1);
  const pila: string[] = [];
  const tag = /<(\/?)([A-Za-z_][\w.:-]*)((?:\s+[\w.:-]+="[^"<]*")*)\s*(\/?)>/g;
  let ultimo = 0;
  let m: RegExpExecArray | null;
  while ((m = tag.exec(corpo)) !== null) {
    const testo = corpo.slice(ultimo, m.index);
    assert.ok(!testo.includes('<') && !testo.includes('>'), `testo con < o > nudi: ${testo}`);
    assert.ok(!/&(?!(amp|lt|gt|quot|apos);)/.test(testo), `& non escapata: ${testo}`);
    if (m[4] === '/') {
      // autochiuso
    } else if (m[1] === '/') {
      assert.equal(pila.pop(), m[2], `chiusura inattesa ${m[2]}`);
    } else {
      pila.push(m[2]);
    }
    ultimo = tag.lastIndex;
  }
  assert.equal(corpo.slice(ultimo).trim(), '');
  assert.deepEqual(pila, []);
}

// ---------------------------------------------------------------------------
// Percorso
// ---------------------------------------------------------------------------

test('analizzaPercorsoFeed: percorsi validi', () => {
  assert.deepEqual(analizzaPercorsoFeed('articles.json'), { risorsa: 'articles', categoria: null, formato: 'json' });
  assert.deepEqual(analizzaPercorsoFeed('articles.xml'), { risorsa: 'articles', categoria: null, formato: 'xml' });
  assert.deepEqual(analizzaPercorsoFeed('interpelli.json'), { risorsa: 'interpelli', categoria: null, formato: 'json' });
  assert.deepEqual(analizzaPercorsoFeed('selezione-personale.xml'),
    { risorsa: 'selezione-personale', categoria: null, formato: 'xml' });
  assert.deepEqual(analizzaPercorsoFeed('bandi.json'), { risorsa: 'bandi', categoria: null, formato: 'json' });
  assert.deepEqual(analizzaPercorsoFeed('articles/scuola.json'), { risorsa: 'articles', categoria: 'scuola', formato: 'json' });
  assert.deepEqual(analizzaPercorsoFeed('articles/editoriali.xml'),
    { risorsa: 'articles', categoria: 'editoriali', formato: 'xml' });
  // Sintatticamente uno slug valido: l'appartenenza alle categorie la verifica il chiamante.
  assert.deepEqual(analizzaPercorsoFeed('articles/constructor.json'),
    { risorsa: 'articles', categoria: 'constructor', formato: 'json' });
  assert.deepEqual(analizzaPercorsoFeed(`articles/${'a'.repeat(64)}.json`),
    { risorsa: 'articles', categoria: 'a'.repeat(64), formato: 'json' });
});

test('analizzaPercorsoFeed: tutto il resto e\' null', () => {
  const rifiutati: (string | undefined)[] = [
    undefined, '', 'articles/', 'articles//scuola.json', 'articles', 'articles/scuola', 'ARTICLES.json',
    'interpelli/scuola.json', 'articles.rss', 'constructor.json', '__proto__.xml', 'articles/scuola.constructor',
    'toString.json', 'hasOwnProperty.xml', 'articles.json.json', 'articles.JSON', '.json', 'articles.',
    '/articles.json', 'articles.json/', 'articles/Scuola.json', 'articles/scuola_x.json', 'articles/-scuola.json',
    'articles/scuola--x.json', `articles/${'a'.repeat(65)}.json`, 'articles/scuola.json.xml', 'articles/__proto__.json',
    'feeds/articles.json', 'articles/scuola/x.json', ' articles.json', 'articles.json ', 'articles%2Fscuola.json',
  ];
  for (const percorso of rifiutati) assert.equal(analizzaPercorsoFeed(percorso), null, String(percorso));
});

// ---------------------------------------------------------------------------
// Metadati
// ---------------------------------------------------------------------------

test('metadatiFeed: titoli e URL', () => {
  assert.deepEqual(
    { ...META_ARTICOLI, descrizione: '' },
    {
      titolo: 'EduNews24 – Ultimi articoli', descrizione: '', homePageUrl: 'https://edunews24.it',
      feedUrl: 'https://edunews24.it/api/v1/feeds/articles.json', apiUrl: 'https://edunews24.it/api/v1/articles',
    },
  );
  assert.ok(META_ARTICOLI.descrizione.includes(URL_TERMINI));

  const categoria = metadatiFeed({ risorsa: 'articles', categoria: 'scuola', formato: 'xml' }, 'Scuola');
  assert.equal(categoria.titolo, 'EduNews24 – Scuola');
  assert.equal(categoria.homePageUrl, 'https://edunews24.it/scuola');
  assert.equal(categoria.feedUrl, 'https://edunews24.it/api/v1/feeds/articles/scuola.xml');
  assert.equal(categoria.apiUrl, 'https://edunews24.it/api/v1/articles?category=scuola');
  assert.ok(categoria.descrizione.includes(URL_TERMINI));

  const bandi = metadatiFeed({ risorsa: 'bandi', categoria: null, formato: 'json' }, null);
  assert.equal(bandi.titolo, 'EduNews24 – Bandi e finanziamenti pubblici');
  assert.equal(bandi.homePageUrl, 'https://edunews24.it/bandi');
  assert.equal(bandi.feedUrl, 'https://edunews24.it/api/v1/feeds/bandi.json');
  assert.equal(bandi.apiUrl, 'https://edunews24.it/api/v1/bandi');

  assert.equal(META_SELEZIONE.titolo, 'EduNews24 – Concorsi e selezioni pubbliche');
  assert.equal(META_SELEZIONE.feedUrl, 'https://edunews24.it/api/v1/feeds/selezione-personale.xml');
  assert.equal(metadatiFeed({ risorsa: 'interpelli', categoria: null, formato: 'xml' }, null).titolo,
    'EduNews24 – Interpelli scuola');
});

// ---------------------------------------------------------------------------
// JSON Feed 1.1
// ---------------------------------------------------------------------------

test('JSON Feed: membri obbligatori del feed e delle voci', () => {
  const { feed, voci } = jsonFeed([articolo(), selezione(), interpello(), bando()]);
  assert.deepEqual(Object.keys(feed), [
    'version', 'title', 'home_page_url', 'feed_url', 'description', 'favicon', 'language', 'authors',
    '_edunews24', 'items',
  ]);
  assert.equal(feed.version, 'https://jsonfeed.org/version/1.1');
  assert.equal(feed.title, 'EduNews24 – Ultimi articoli');
  assert.equal(feed.favicon, 'https://edunews24.it/favicon.ico');
  assert.equal(feed.language, 'it-IT');
  assert.deepEqual(feed.authors, [{ name: 'EduNews24', url: 'https://edunews24.it' }]);
  assert.deepEqual(feed._edunews24, {
    api: 'https://edunews24.it/api/v1/articles', terms: URL_TERMINI, content_signal: CONTENT_SIGNAL,
  });
  assert.equal(voci.length, 4);
  for (const voce of voci) {
    for (const membro of ['id', 'url', 'title', 'content_text', 'date_published']) {
      assert.equal(typeof voce[membro], 'string', membro);
      assert.notEqual(voce[membro], '');
    }
    assert.equal('content_html' in voce, false);
  }
  assert.equal(voci[0].id, 'tag:edunews24.it,2026:article/39382');
  assert.equal(voci[1].id, 'tag:edunews24.it,2026:selezione-personale/23258');
  assert.equal(voci[2].id, 'tag:edunews24.it,2026:interpello/1523');
  assert.equal(voci[3].id, 'tag:edunews24.it,2026:bando/4821');
  assert.equal(voci[0].date_published, '2026-09-21T09:18:28+02:00');
});

test('JSON Feed: nessun membro vuoto fuori da _edunews24', () => {
  const vuoti = articolo({ excerpt: null, summary: null, image_url: null, tags: [] });
  const { feed } = jsonFeed([vuoti, interpello(), selezione(), bando({ regions: [], updated_at: null })]);
  assert.deepEqual(membriVuoti(feed, '$', []), []);
  const [a, i] = feed.items as Oggetto[];
  assert.deepEqual(Object.keys(a), ['id', 'url', 'title', 'content_text', 'date_published', 'authors', 'tags', '_edunews24']);
  assert.deepEqual(Object.keys(i), ['id', 'url', 'title', 'content_text', 'date_published', 'tags', '_edunews24']);
  // Senza sintesi il testo parte dalla riga successiva, senza a capo iniziali.
  assert.equal(a.content_text, 'Leggi l\'articolo completo su EduNews24: https://edunews24.it/scuola/supplenze-2026-27');
  assert.equal(i.content_text, 'Scheda completa su EduNews24: https://edunews24.it/interpelli/ic-mazzini-roma-lazio-1523');
});

test('JSON Feed: _edunews24 esatto per tipo, null conservati', () => {
  const { voci } = jsonFeed([articolo(), interpello(), selezione(), bando({ status: 'upcoming', deadline_on: null })]);
  assert.deepEqual(voci[0]._edunews24, { type: 'article', category: 'scuola' });
  assert.deepEqual(voci[1]._edunews24, { type: 'interpello', status: null, deadline_on: null });
  assert.deepEqual(voci[2]._edunews24, { type: 'selezione-personale', status: 'open', deadline_on: '2026-10-06' });
  assert.deepEqual(voci[3]._edunews24, { type: 'bando', status: 'upcoming', deadline_on: null });
  assert.deepEqual(Object.keys(voci[2]._edunews24 as Oggetto), ['type', 'status', 'deadline_on']);
});

test('JSON Feed: testo, sintesi, immagine, autori, tag deduplicati', () => {
  const { voci } = jsonFeed([articolo(), articolo({ summary: null }), selezione()]);
  const [a, senzaSintesi, s] = voci;
  assert.equal(a.summary, 'Sintesi dell\'articolo.');
  assert.equal(a.content_text,
    'Sintesi dell\'articolo.\n\nLeggi l\'articolo completo su EduNews24: https://edunews24.it/scuola/supplenze-2026-27');
  assert.equal(senzaSintesi.summary, 'Estratto breve.');
  assert.ok((senzaSintesi.content_text as string).startsWith('Estratto breve.\n\n'));
  assert.equal(a.image, 'https://cdn.example.org/a.webp');
  assert.deepEqual(a.authors, [{ name: 'Redazione EduNews24' }]);
  assert.deepEqual(a.tags, ['Scuola', 'supplenze', 'gps']);
  assert.equal(s.summary, 'Candidature aperte.');
  assert.equal(s.content_text, 'Candidature aperte.\n\nScadenza: 6 ottobre 2026\n\n' +
    'Scheda completa su EduNews24: https://edunews24.it/selezione-personale/arpam-marche-29611');
  assert.deepEqual(s.tags, ['Concorsi e selezioni pubbliche', 'Marche']);
  assert.equal('image' in s, false);
  assert.equal('authors' in s, false);
});

test('JSON Feed: date_modified solo per le opportunita\' con updated_at', () => {
  const { voci } = jsonFeed([articolo(), selezione(), bando(), interpello(), bando({ updated_at: null })]);
  assert.equal('date_modified' in voci[0], false);
  assert.equal(voci[1].date_modified, '2026-09-21T08:04:01+02:00');
  assert.equal(voci[2].date_modified, '2026-09-20T03:12:55+02:00');
  assert.equal('date_modified' in voci[3], false);
  assert.equal('date_modified' in voci[4], false);
});

test('JSON Feed: allegati video solo con mime_type noto, durata facoltativa', () => {
  const conVideo = articolo({
    video: { url: 'https://cdn.example.org/v.mp4', mime_type: 'video/mp4', thumbnail_url: null, duration_seconds: 72 },
  });
  const senzaDurata = articolo({
    video: { url: 'https://cdn.example.org/v.mov', mime_type: 'video/quicktime', thumbnail_url: null, duration_seconds: null },
  });
  const mimeIgnoto = articolo({
    video: { url: 'https://cdn.example.org/v.webm', mime_type: null, thumbnail_url: null, duration_seconds: 10 },
  });
  const { voci } = jsonFeed([conVideo, senzaDurata, mimeIgnoto]);
  assert.deepEqual(voci[0].attachments,
    [{ url: 'https://cdn.example.org/v.mp4', mime_type: 'video/mp4', duration_in_seconds: 72 }]);
  assert.deepEqual(voci[1].attachments, [{ url: 'https://cdn.example.org/v.mov', mime_type: 'video/quicktime' }]);
  assert.equal('attachments' in voci[2], false);
});

test('riga Scadenza: "6 ottobre 2026" in qualunque fuso del processo', () => {
  const originale = process.env.TZ;
  try {
    for (const fuso of ['Asia/Kathmandu', 'Pacific/Kiritimati', 'Pacific/Pago_Pago', 'America/Sao_Paulo', 'UTC', 'Europe/Rome']) {
      process.env.TZ = fuso;
      const { voci } = jsonFeed([selezione({ deadline_on: '2026-10-06' })]);
      assert.ok((voci[0].content_text as string).includes('\n\nScadenza: 6 ottobre 2026\n\n'), fuso);
      const rss = serializzaRss(META_SELEZIONE, [selezione({ deadline_on: '2026-10-06' })]);
      assert.ok(rss.includes('Scadenza: 6 ottobre 2026'), fuso);
    }
  } finally {
    if (originale === undefined) delete process.env.TZ;
    else process.env.TZ = originale;
  }
  const { voci } = jsonFeed([selezione({ deadline_on: null })]);
  assert.equal((voci[0].content_text as string).includes('Scadenza'), false);
});

// ---------------------------------------------------------------------------
// XML e RSS 2.0
// ---------------------------------------------------------------------------

test('testoXml: escape e caratteri non ammessi in XML 1.0', () => {
  assert.equal(testoXml('a & b < c > d "e" \'f\''), 'a &amp; b &lt; c &gt; d &quot;e&quot; &apos;f&apos;');
  assert.equal(testoXml('x\u0000y\u0001z\u0008\u000B\u000C\u001F'), 'xyz');
  assert.equal(testoXml('tab\tnl\ncr\r'), 'tab\tnl\ncr\r');
  assert.equal(testoXml('a￾b￿c'), 'abc');
  assert.equal(testoXml('spaiato\uD800fine\uDC00'), 'spaiatofine');
  assert.equal(testoXml('emoji 😀 ok'), 'emoji 😀 ok');
  assert.equal(testoXml('�'), '�');
});

test('elemento: attributi null omessi, nessun elemento vuoto, nomi validati', () => {
  assert.equal(elemento('a', [['x', null], ['y', '1&"2"']], 'testo'), '<a y="1&amp;&quot;2&quot;">testo</a>');
  assert.equal(elemento('a', [], ''), '');
  assert.equal(elemento('a', [], '   '), '');
  assert.equal(elemento('a', [], null), '');
  assert.equal(elemento('a', [], []), '');
  assert.equal(elemento('a', [['href', 'u']], null), '<a href="u"/>');
  assert.equal(elemento('a', [], [elemento('b', [], 'x'), elemento('c', [], null)]), '<a>\n<b>x</b>\n</a>');
  assert.throws(() => elemento('a b', [], 'x'));
  assert.throws(() => elemento('a', [['x"=1', 'v']], 'x'));
});

test('RSS: canale, atom:link, lastBuildDate e voci', () => {
  const rss = serializzaRss(META_SELEZIONE, [selezione(), selezione({ id: 2, updated_at: '2026-09-21T10:30:00+02:00' })]);
  verificaXmlBenFormato(rss);
  assert.ok(rss.includes('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" ' +
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">'));
  assert.ok(rss.includes('<title>EduNews24 – Concorsi e selezioni pubbliche</title>'));
  assert.ok(rss.includes('<link>https://edunews24.it/selezione-personale</link>'));
  assert.ok(rss.includes('<language>it-it</language>'));
  assert.ok(rss.includes(`<copyright>© EduNews24 – riuso secondo i termini ${URL_TERMINI} con link all&apos;originale</copyright>`));
  assert.ok(rss.includes('<ttl>10</ttl>'));
  assert.ok(rss.includes('<atom:link rel="self" type="application/rss+xml" ' +
    'href="https://edunews24.it/api/v1/feeds/selezione-personale.xml"/>'));
  // Selezione: massimo di updated_at (non di published_at).
  assert.ok(rss.includes('<lastBuildDate>Mon, 21 Sep 2026 10:30:00 +0200</lastBuildDate>'));
  assert.ok(rss.includes('<guid isPermaLink="false">tag:edunews24.it,2026:selezione-personale/23258</guid>'));
  assert.ok(rss.includes('<pubDate>Mon, 21 Sep 2026 00:01:00 +0200</pubDate>'));
  assert.ok(rss.includes('<category>Concorsi e selezioni pubbliche</category>\n<category>Marche</category>'));
  assert.equal((rss.match(/<item>/g) ?? []).length, 2);
  assert.equal(rss.includes('CDATA'), false);
  assert.equal(rss.includes('dc:creator>'), false);
});

test('RSS: lastBuildDate e\' il massimo di published_at per le altre risorse, omesso senza voci', () => {
  const meta = metadatiFeed({ risorsa: 'articles', categoria: null, formato: 'xml' }, null);
  const rss = serializzaRss(meta, [
    articolo({ id: 1, published_at: '2026-09-20T08:00:00+02:00' }),
    articolo({ id: 2, published_at: '2026-01-15T23:30:00+01:00' }),
    articolo({ id: 3, published_at: '2026-09-21T09:18:28+02:00' }),
  ]);
  verificaXmlBenFormato(rss);
  assert.ok(rss.includes('<lastBuildDate>Mon, 21 Sep 2026 09:18:28 +0200</lastBuildDate>'));
  assert.ok(rss.includes('<pubDate>Thu, 15 Jan 2026 23:30:00 +0100</pubDate>'));

  const bandi = metadatiFeed({ risorsa: 'bandi', categoria: null, formato: 'xml' }, null);
  const rssBandi = serializzaRss(bandi, [bando()]);
  // Bandi: published_at anche se updated_at e' piu' recente.
  assert.ok(rssBandi.includes('<lastBuildDate>Tue, 15 Sep 2026 10:42:07 +0200</lastBuildDate>'));

  const vuoto = serializzaRss(meta, []);
  verificaXmlBenFormato(vuoto);
  assert.equal(vuoto.includes('lastBuildDate'), false);
  assert.equal(vuoto.includes('<item>'), false);
  assert.ok(vuoto.includes('<ttl>10</ttl>'));
});

test('RSS: escape di testi e attributi, caratteri non XML rimossi', () => {
  const meta = metadatiFeed({ risorsa: 'articles', categoria: null, formato: 'xml' }, null);
  const rss = serializzaRss(meta, [articolo({
    title: 'Voto < 6 & debiti \u0001\uD800"ok"',
    image_url: 'https://cdn.example.org/a.webp?a=1&b="2"',
    video: { url: 'https://cdn.example.org/v.mp4?x=1&y=<2>', mime_type: 'video/mp4', thumbnail_url: null, duration_seconds: 72 },
    tags: ['a&b', '<tag>'],
    author: { name: 'Mario "Rossi" & C.' },
  })]);
  verificaXmlBenFormato(rss);
  assert.ok(rss.includes('<title>Voto &lt; 6 &amp; debiti &quot;ok&quot;</title>'));
  assert.ok(rss.includes('<media:thumbnail url="https://cdn.example.org/a.webp?a=1&amp;b=&quot;2&quot;"/>'));
  assert.ok(rss.includes('<media:content url="https://cdn.example.org/v.mp4?x=1&amp;y=&lt;2&gt;" medium="video" ' +
    'type="video/mp4" duration="72"/>'));
  assert.ok(rss.includes('<category>Scuola</category>\n<category>a&amp;b</category>\n<category>&lt;tag&gt;</category>'));
  assert.ok(rss.includes('<dc:creator>Mario &quot;Rossi&quot; &amp; C.</dc:creator>'));
  assert.equal(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(rss), false);
  assert.equal(/[\uD800-\uDFFF]/.test(rss.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '')), false);

  // Il JSON conserva il testo originale (l'escape e' solo dell'XML), tranne i caratteri: JSON li codifica.
  const { voci } = jsonFeed([articolo({ title: 'Voto < 6 & debiti' })]);
  assert.equal(voci[0].title, 'Voto < 6 & debiti');
});

test('RSS: video senza mime_type e durata assente', () => {
  const meta = metadatiFeed({ risorsa: 'articles', categoria: null, formato: 'xml' }, null);
  const senzaMime = serializzaRss(meta, [articolo({
    image_url: null,
    video: { url: 'https://cdn.example.org/v.webm', mime_type: null, thumbnail_url: null, duration_seconds: 5 },
  })]);
  assert.equal(senzaMime.includes('media:content'), false);
  assert.equal(senzaMime.includes('media:thumbnail'), false);
  const senzaDurata = serializzaRss(meta, [articolo({
    video: { url: 'https://cdn.example.org/v.mp4', mime_type: 'video/mp4', thumbnail_url: null, duration_seconds: null },
  })]);
  assert.ok(senzaDurata.includes('<media:content url="https://cdn.example.org/v.mp4" medium="video" type="video/mp4"/>'));
});

test('RSS: description uguale a content_text del JSON Feed', () => {
  const elementi = [articolo(), selezione(), interpello(), bando()];
  const { voci } = jsonFeed(elementi);
  const rss = serializzaRss(META_SELEZIONE, elementi);
  for (const voce of voci) {
    assert.ok(rss.includes(`<description>${testoXml(voce.content_text as string)}</description>`), String(voce.id));
  }
});
