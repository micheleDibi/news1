/**
 * mappa-articoli.ts: DTO completo, media, video, secondarie, tag, righe scartate,
 * autore (piano §3.6) e non fuga di `creator` / `full_name`.
 * Gira con TZ=Asia/Kathmandu: published_at non deve dipendere dal fuso del processo.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { interoPositivo, mappaArticolo, nomeAutore } from '../../src/lib/api-v1/mappa-articoli.ts';
import { costruisciRiferimentoCategorie, costruisciRiferimentoProfili } from '../../src/lib/api-v1/riferimenti.ts';
import { RIGHE_CATEGORIE, RIGHE_PROFILI, RIGHE_SECONDARIE } from './fixture/riferimenti-base.ts';
import type { ArticoloDto, RigaArticolo } from '../../src/lib/api-v1/contratto.ts';

const { riferimento: CATEGORIE } = costruisciRiferimentoCategorie(RIGHE_CATEGORIE, RIGHE_SECONDARIE);
const PROFILI = costruisciRiferimentoProfili(RIGHE_PROFILI);
const CONTESTO = { categorie: CATEGORIE, profili: PROFILI };

const CHIAVI_ARTICOLO = [
  'type', 'id', 'slug', 'url', 'title', 'title_summary', 'excerpt', 'summary', 'category', 'secondary_categories',
  'image_url', 'thumbnail_url', 'video', 'published_at', 'tags', 'author',
];

function riga(extra: Partial<RigaArticolo> = {}): RigaArticolo {
  return {
    id: 39382,
    slug: 'supplenze-2026-27-convocazioni-da-gps',
    title: 'Supplenze 2026/27, al via le convocazioni da GPS',
    title_summary: 'Supplenze 2026/27: le convocazioni da GPS',
    excerpt: 'Gli uffici scolastici avviano le convocazioni per le supplenze annuali.',
    summary: '## Le convocazioni\n\nGli **uffici scolastici** avviano le convocazioni. Vedi [il bando](https://www.miur.gov.it/x).',
    category_slug: 'scuola',
    secondary_category_slugs: ['insegnanti', 'ata'],
    image_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze.webp',
    thumbnail_url: '',
    video_url: null,
    video_duration: null,
    published_at: '2026-09-21T07:18:28.177',
    tags: ['supplenze', 'GPS', 'docenti precari'],
    creator: 'Nome Reale Riservato',
    ...extra,
  };
}

function mappa(extra: Partial<RigaArticolo> = {}): ArticoloDto {
  const dto = mappaArticolo(riga(extra), CONTESTO);
  assert.ok(dto !== null, 'riga attesa valida');
  return dto;
}

test('articolo: DTO completo, campo per campo, nell\'ordine del contratto', () => {
  const dto = mappa();
  assert.deepEqual(Object.keys(dto), CHIAVI_ARTICOLO);
  assert.deepEqual(dto, {
    type: 'article',
    id: 39382,
    slug: 'supplenze-2026-27-convocazioni-da-gps',
    url: 'https://edunews24.it/scuola/supplenze-2026-27-convocazioni-da-gps',
    title: 'Supplenze 2026/27, al via le convocazioni da GPS',
    title_summary: 'Supplenze 2026/27: le convocazioni da GPS',
    excerpt: 'Gli uffici scolastici avviano le convocazioni per le supplenze annuali.',
    summary: 'Le convocazioni. Gli uffici scolastici avviano le convocazioni. Vedi il bando.',
    category: { slug: 'scuola', name: 'Scuola', color: '#2D6A4F', url: 'https://edunews24.it/scuola' },
    secondary_categories: [{ slug: 'ata', name: 'ATA' }, { slug: 'insegnanti', name: 'Insegnanti' }],
    image_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze.webp',
    thumbnail_url: null,
    video: null,
    published_at: '2026-09-21T09:18:28+02:00',
    tags: ['supplenze', 'GPS', 'docenti precari'],
    author: { name: 'Redazione EduNews24' },
  });
  assert.deepEqual(Object.keys(dto.category), ['slug', 'name', 'color', 'url']);
});

test('articolo: published_at con l\'euristica dei decimali (UTC <=3, Roma 4-6, offset esplicito)', () => {
  assert.equal(mappa({ published_at: '2026-09-21T07:18:28' }).published_at, '2026-09-21T09:18:28+02:00');
  assert.equal(mappa({ published_at: '2026-09-21T09:18:28.123456' }).published_at, '2026-09-21T09:18:28+02:00');
  assert.equal(mappa({ published_at: '2026-01-10T08:00:00+00:00' }).published_at, '2026-01-10T09:00:00+01:00');
});

test('articolo: righe scartate (null)', () => {
  for (const [descrizione, extra] of [
    ['id stringa', { id: '39382' }],
    ['id zero', { id: 0 }],
    ['id negativo', { id: -1 }],
    ['id decimale', { id: 1.5 }],
    ['id oltre il sicuro', { id: 2 ** 53 }],
    ['slug null', { slug: null }],
    ['slug vuoto', { slug: '   ' }],
    ['slug con ?', { slug: 'a?b' }],
    ['slug ..', { slug: '..' }],
    ['categoria bandi', { category_slug: 'bandi' }],
    ['categoria assente', { category_slug: null }],
    ['categoria con spazi', { category_slug: ' scuola ' }],
    ['categoria constructor', { category_slug: 'constructor' }],
    ['published_at null', { published_at: null }],
    ['published_at non valido', { published_at: '21/09/2026' }],
    ['published_at data impossibile', { published_at: '2026-02-30T10:00:00' }],
    ['published_at numero', { published_at: 1758439108000 }],
  ] as const) {
    assert.equal(mappaArticolo(riga(extra as Partial<RigaArticolo>), CONTESTO), null, descrizione);
  }
});

test('articolo: slug con spazi ai bordi -> trim, URL corretto', () => {
  const dto = mappa({ slug: '  articolo-con-spazi  ' });
  assert.equal(dto.slug, 'articolo-con-spazi');
  assert.equal(dto.url, 'https://edunews24.it/scuola/articolo-con-spazi');
});

test('articolo: ripieghi del titolo (title_summary, poi slug)', () => {
  assert.equal(mappa({ title: '  ' }).title, 'Supplenze 2026/27: le convocazioni da GPS');
  assert.equal(mappa({ title: null, title_summary: '<b></b>' }).title, 'supplenze-2026-27-convocazioni-da-gps');
  assert.equal(mappa({ title: 'https://www.esterno.example/pagina' }).title, 'Supplenze 2026/27: le convocazioni da GPS');
  assert.equal(mappa({ title: 'Titolo &amp; <em>enfasi</em>' }).title, 'Titolo & enfasi');
  assert.equal(mappa({ title_summary: '' }).title_summary, null);
  assert.equal(mappa({ excerpt: 42 }).excerpt, null);
});

test('articolo: sintesi ripulita e tagliata a 600 caratteri', () => {
  assert.equal(mappa({ summary: null }).summary, null);
  const frase = 'Questa e\' una frase di prova per la sintesi dell\'articolo. ';
  const lunga = frase.repeat(30);
  const sintesi = mappa({ summary: lunga }).summary;
  assert.ok(sintesi !== null && sintesi.length <= 600 && sintesi.length >= 300);
  assert.ok(sintesi.endsWith('.'));
});

test('articolo: media non validi -> null, relativi -> assoluti', () => {
  for (const cattivo of ['', '   ', 'blob:https://edunews24.it/abc', 'data:image/png;base64,AAAA', 'javascript:alert(1)',
    'https://utente:pw@x.it/a.jpg', 42, null]) {
    const dto = mappa({ image_url: cattivo, thumbnail_url: cattivo });
    assert.equal(dto.image_url, null, String(cattivo));
    assert.equal(dto.thumbnail_url, null, String(cattivo));
  }
  const dto = mappa({ image_url: '/immagini/a b.webp', thumbnail_url: '//cdn.example.com/t.webp' });
  assert.equal(dto.image_url, 'https://edunews24.it/immagini/a%20b.webp');
  assert.equal(dto.thumbnail_url, 'https://cdn.example.com/t.webp');
});

test('articolo: video, mime, miniatura di ripiego e durata', () => {
  const conMiniatura = mappa({
    video_url: 'https://cdn.example.com/v/clip.MP4?x=1', thumbnail_url: 'https://cdn.example.com/v/clip.webp', video_duration: 72,
  });
  assert.deepEqual(conMiniatura.video, {
    url: 'https://cdn.example.com/v/clip.MP4?x=1',
    mime_type: 'video/mp4',
    thumbnail_url: 'https://cdn.example.com/v/clip.webp',
    duration_seconds: 72,
  });
  assert.deepEqual(Object.keys(conMiniatura.video ?? {}), ['url', 'mime_type', 'thumbnail_url', 'duration_seconds']);

  // miniatura non valida -> ripiego su image_url
  const ripiego = mappa({ video_url: '/video/clip.mov', thumbnail_url: 'blob:x', video_duration: '45' });
  assert.deepEqual(ripiego.video, {
    url: 'https://edunews24.it/video/clip.mov',
    mime_type: 'video/quicktime',
    thumbnail_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze.webp',
    duration_seconds: 45,
  });
  assert.equal(ripiego.thumbnail_url, null);

  // estensione sconosciuta, nessuna immagine, durate non valide
  for (const durata of [0, -3, 1.5, '1.5', 'abc', '', null, Number.NaN, '99999999999999999']) {
    const dto = mappa({ video_url: 'https://cdn.example.com/v/stream', image_url: null, video_duration: durata });
    assert.deepEqual(dto.video, {
      url: 'https://cdn.example.com/v/stream', mime_type: null, thumbnail_url: null, duration_seconds: null,
    }, String(durata));
  }

  for (const cattivo of ['', 'blob:https://edunews24.it/x', 'ftp://x.it/a.mp4', null]) {
    assert.equal(mappa({ video_url: cattivo }).video, null, String(cattivo));
  }
});

test('interoPositivo: numeri e stringhe di sole cifre', () => {
  assert.equal(interoPositivo(72), 72);
  assert.equal(interoPositivo(' 72 '), 72);
  assert.equal(interoPositivo('007'), 7);
  for (const v of [0, -1, 1.2, '1e3', '+5', '0x10', '', null, true, Number.POSITIVE_INFINITY, 2 ** 53]) {
    assert.equal(interoPositivo(v), null, String(v));
  }
});

test('articolo: secondarie orfane, di altre madri e non stringa scartate, ordine del riferimento', () => {
  assert.deepEqual(mappa({ secondary_category_slugs: ['insegnanti', 'ricerca', 'bandi-europei', 7, null, 'inesistente'] })
    .secondary_categories, [{ slug: 'insegnanti', name: 'Insegnanti' }]);
  assert.deepEqual(mappa({ secondary_category_slugs: ['insegnanti', 'dirigenti', 'ata', 'ata'] }).secondary_categories, [
    { slug: 'ata', name: 'ATA' }, { slug: 'dirigenti', name: 'Dirigenti scolastici' }, { slug: 'insegnanti', name: 'Insegnanti' },
  ]);
  for (const v of [null, 'insegnanti', { insegnanti: true }, []]) {
    assert.deepEqual(mappa({ secondary_category_slugs: v }).secondary_categories, [], JSON.stringify(v));
  }
  assert.deepEqual(mappa({ category_slug: 'universita', secondary_category_slugs: ['insegnanti', 'ricerca'] })
    .secondary_categories, [{ slug: 'ricerca', name: 'Ricerca' }]);
});

test('articolo: tag anomali, vuoti e duplicati senza distinguere le maiuscole', () => {
  assert.deepEqual(
    mappa({ tags: ['Scuola', 'scuola', ' SCUOLA ', '', '   ', null, 42, { a: 1 }, '<b>Esami</b>', 'esami', 'https://www.x.example/y', 'GPS'] }).tags,
    ['Scuola', 'Esami', 'GPS'],
  );
  for (const v of [null, 'scuola, gps', { 0: 'scuola' }, 7]) {
    assert.deepEqual(mappa({ tags: v }).tags, [], JSON.stringify(v));
  }
});

// ---------------------------------------------------------------------------
// Autore
// ---------------------------------------------------------------------------

test('autore: per id, per full_name unico, altrimenti Redazione', () => {
  assert.equal(nomeAutore('u-giornalista', PROFILI), 'M. Rossi');
  assert.equal(nomeAutore('Mario Esempio Rossi', PROFILI), 'M. Rossi');
  assert.equal(nomeAutore('u-redazione', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('Nome Reale Riservato', PROFILI), 'Redazione EduNews24');
});

test('autore: profilo non visualizzabile, ambiguo, nome pubblico non idoneo -> Redazione', () => {
  assert.equal(nomeAutore('u-nascosto', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('Persona Nascosta', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('Omonimo Doppio', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('u-omonimo-1', PROFILI), 'Omonimo Uno', 'per id l\'omonimia non conta');
  assert.equal(nomeAutore('u-lungo', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('u-url', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('u-null', PROFILI), 'Redazione EduNews24');
  assert.equal(nomeAutore('u-stringa', PROFILI), 'Redazione EduNews24');
});

test('autore: creator assente, vuoto, sconosciuto o non stringa -> Redazione', () => {
  for (const creator of [null, undefined, '', 'Sconosciuto', 42, { id: 'u-giornalista' }, ['u-giornalista'],
    ' Mario Esempio Rossi', 'mario esempio rossi', 'constructor', '__proto__']) {
    assert.equal(nomeAutore(creator, PROFILI), 'Redazione EduNews24', String(creator));
  }
  assert.equal(nomeAutore('u-giornalista', costruisciRiferimentoProfili([])), 'Redazione EduNews24');
});

test('autore: nome pubblico ripulito (entita\', tag, spazi)', () => {
  const profili = costruisciRiferimentoProfili([
    { id: 'p1', full_name: 'Tizio', public_name: '  Anna &amp; <b>Bruno</b>  ', is_displayable: true },
    { id: 'p2', full_name: 'Caio', public_name: 'x'.repeat(80), is_displayable: true },
  ]);
  assert.equal(nomeAutore('p1', profili), 'Anna & Bruno');
  assert.equal(nomeAutore('p2', profili), 'x'.repeat(80));
});

test('NON FUGA: creator e full_name non compaiono mai nell\'output', () => {
  const sensibili = RIGHE_PROFILI.map((p) => p.full_name).filter((n): n is string => typeof n === 'string');
  assert.ok(sensibili.includes('Nome Reale Riservato'));
  const creatori: unknown[] = [
    'Nome Reale Riservato', 'Mario Esempio Rossi', 'Persona Nascosta', 'Omonimo Doppio', 'Nome Lungo', 'Nome Url',
    'Nome Senza Pubblico', 'Nome Flag Stringa', ...RIGHE_PROFILI.map((p) => p.id), 'Sconosciuto Qualunque', null,
  ];
  for (const creator of creatori) {
    const json = JSON.stringify(mappa({ creator }));
    assert.equal(json.includes('creator'), false);
    for (const nome of sensibili) assert.equal(json.includes(nome), false, `${nome} in uscita per creator=${String(creator)}`);
    if (typeof creator === 'string') assert.equal(json.includes(creator), false, `creator ${creator} in uscita`);
  }
});

test('articolo: colonne non previste nella riga non escono', () => {
  const conExtra = {
    ...riga(),
    content: 'TESTO-INTEGRALE', faqs: [{ q: 'FAQ-INTERNA' }], audio_url: 'https://x.example/a.mp3', source: 'https://fonte.example',
    is_featured: true, isdraft: false, skill_x: 'SKILL', persona_job_id: 'JOB', category: 'Scuola legacy',
    secondary_categories: ['legacy'], created_at: '2026-01-01T00:00:00',
  } as RigaArticolo;
  const dto = mappaArticolo(conExtra, CONTESTO);
  assert.ok(dto !== null);
  assert.deepEqual(Object.keys(dto), CHIAVI_ARTICOLO);
  const json = JSON.stringify(dto);
  for (const vietato of ['TESTO-INTEGRALE', 'FAQ-INTERNA', 'a.mp3', 'fonte.example', 'SKILL', 'JOB', 'legacy', 'is_featured']) {
    assert.equal(json.includes(vietato), false, vietato);
  }
});
