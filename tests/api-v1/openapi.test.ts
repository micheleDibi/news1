/**
 * openapi.ts: forma del documento e coerenza con i DTO di contratto.ts e con
 * SPEC_PARAMETRI. Gli oggetti DTO di esempio sono costruiti qui, completi: se un
 * campo viene aggiunto al contratto senza aggiornare lo schema (o viceversa) il
 * confronto delle chiavi fallisce.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { documentoOpenApi } from '../../src/lib/api-v1/openapi.ts';
import { datiIndice } from '../../src/lib/api-v1/indice.ts';
import { CODICI_ERRORE } from '../../src/lib/api-v1/errori.ts';
import { SPEC_PARAMETRI, SLUG_REGIONI, filtriMeta } from '../../src/lib/api-v1/parametri.ts';
import { sezioneDto } from '../../src/lib/api-v1/sezioni.ts';
import { BASE_API, URL_DOCUMENTAZIONE, URL_TERMINI, VERSIONE_OPENAPI } from '../../src/lib/api-v1/costanti.ts';
import {
  esempioArticolo, esempioBando, esempioCategoria, esempioInterpello, esempioSelezione, esempioVideo,
} from '../../src/lib/api-v1/testi-doc.ts';
import type {
  ArticoloDto, BandoDto, CategoriaDto, FonteUfficialeDto, InterpelloDto, OpportunitaBaseDto, Risorsa,
  SelezioneDto, VideoDto,
} from '../../src/lib/api-v1/contratto.ts';
import type { FiltriElenco } from '../../src/lib/api-v1/parametri.ts';

type Oggetto = Record<string, unknown>;

const doc = documentoOpenApi();
const componenti = doc.components as Oggetto;
const schemi = componenti.schemas as Record<string, Oggetto>;
const RISORSE: readonly Risorsa[] = ['articles', 'interpelli', 'selezione-personale', 'bandi'];

function schema(nome: string): Oggetto {
  const s = schemi[nome];
  assert.ok(s, `schema ${nome} assente`);
  return s;
}

/** Risolve un JSON pointer locale ("#/a/b"). */
function risolvi(ref: string): unknown {
  assert.ok(ref.startsWith('#/'), ref);
  let nodo: unknown = doc;
  for (const pezzo of ref.slice(2).split('/').map((p) => p.replace(/~1/g, '/').replace(/~0/g, '~'))) {
    assert.ok(nodo !== null && typeof nodo === 'object' && Object.hasOwn(nodo, pezzo), `ref non risolvibile: ${ref}`);
    nodo = (nodo as Oggetto)[pezzo];
  }
  return nodo;
}

function visita(nodo: unknown, azione: (chiave: string, valore: unknown, genitore: Oggetto) => void): void {
  if (Array.isArray(nodo)) {
    for (const figlio of nodo) visita(figlio, azione);
  } else if (nodo !== null && typeof nodo === 'object') {
    for (const [chiave, valore] of Object.entries(nodo)) {
      azione(chiave, valore, nodo as Oggetto);
      visita(valore, azione);
    }
  }
}

/** Proprieta' di uno schema oggetto, fondendo gli allOf (con risoluzione dei $ref). */
function proprieta(s: Oggetto): { chiavi: string[]; obbligatorie: string[] } {
  const chiavi: string[] = [];
  const obbligatorie: string[] = [];
  const parti = Array.isArray(s.allOf) ? (s.allOf as Oggetto[]) : [s];
  for (const parte of parti) {
    const reale = typeof parte.$ref === 'string' ? (risolvi(parte.$ref) as Oggetto) : parte;
    for (const k of Object.keys((reale.properties as Oggetto | undefined) ?? {})) if (!chiavi.includes(k)) chiavi.push(k);
    for (const k of (reale.required as string[] | undefined) ?? []) if (!obbligatorie.includes(k)) obbligatorie.push(k);
  }
  return { chiavi, obbligatorie };
}

function tipiDi(s: Oggetto): string[] {
  return Array.isArray(s.type) ? (s.type as string[]) : typeof s.type === 'string' ? [s.type] : [];
}

// ---------------------------------------------------------------------------
// DTO di esempio completi (costruiti qui, non presi dal modulo sotto test)
// ---------------------------------------------------------------------------

const VIDEO: VideoDto = {
  url: 'https://cdn.example.org/v.mp4', mime_type: 'video/mp4', thumbnail_url: null, duration_seconds: 10,
};

const ARTICOLO: ArticoloDto = {
  type: 'article', id: 1, slug: 's', url: 'https://edunews24.it/scuola/s', title: 't', title_summary: null,
  excerpt: null, summary: null,
  category: { slug: 'scuola', name: 'Scuola', color: '#2D6A4F', url: 'https://edunews24.it/scuola' },
  secondary_categories: [{ slug: 'insegnanti', name: 'Insegnanti' }], image_url: null, thumbnail_url: null,
  video: VIDEO, published_at: '2026-09-21T09:18:28+02:00', tags: [], author: { name: 'Redazione EduNews24' },
};

const BASE: OpportunitaBaseDto = {
  type: 'interpello', id: 1, slug: 's', url: 'https://edunews24.it/interpelli/s', title: 't', summary: null,
  section: sezioneDto('interpelli'), published_at: '2026-09-21T00:00:00+02:00', updated_at: null,
  deadline_on: null, deadline_at: null, status: null, regions: [{ slug: 'lazio', name: 'Lazio' }], national: false,
};

const INTERPELLO: InterpelloDto = {
  ...BASE, type: 'interpello',
  details: { official_title: null, competition_class: null, province: null, city: null },
};

const SELEZIONE: SelezioneDto = {
  ...BASE, type: 'selezione-personale',
  details: {
    official_title: null, code: null, position: null, positions_count: null, procedure_type: null, categories: [],
    sectors: [], organizations: [], locations: [], salary_min: null, salary_max: null,
  },
};

const FONTE_UFFICIALE: FonteUfficialeDto = {
  url: 'https://comune.esempio.it/bando', host: 'comune.esempio.it', type: 'institution', verified_on: '2026-09-18',
};

const BANDO: BandoDto = {
  ...BASE, type: 'bando',
  details: {
    short_title: null, issuer: null, geographic_area: null, topics: [], kind: null, program: null,
    funding_method: null, sectors: [], beneficiaries: [], ateco_codes: [{ code: '62.01', description: null }],
    total_amount_eur: null, max_amount_per_project_eur: null, opens_on: null, source_published_on: null,
    official_source: FONTE_UFFICIALE, opens_on_verified: null, deadline_verified: null, last_checked_at: null,
  },
};

const CATEGORIA: CategoriaDto = {
  slug: 'scuola', name: 'Scuola', color: '#2D6A4F', position: 1, url: 'https://edunews24.it/scuola',
  secondary_categories: [],
  links: { articles: 'https://x', feed_json: 'https://x', feed_rss: 'https://x' },
};

const INDICE = datiIndice({ requests: 60, window_seconds: 60 });

/** [schema, oggetto DTO completo] */
const COPPIE: readonly (readonly [string, object])[] = [
  ['Articolo', ARTICOLO],
  ['Video', VIDEO],
  ['CategoriaArticolo', ARTICOLO.category],
  ['CategoriaSecondaria', ARTICOLO.secondary_categories[0]],
  ['Autore', ARTICOLO.author],
  ['Categoria', CATEGORIA],
  ['OpportunitaBase', BASE],
  ['Sezione', BASE.section],
  ['Regione', BASE.regions[0]],
  ['Interpello', INTERPELLO],
  ['SelezionePersonale', SELEZIONE],
  ['Bando', BANDO],
  ['DettagliInterpello', INTERPELLO.details],
  ['DettagliSelezione', SELEZIONE.details],
  ['DettagliBando', BANDO.details],
  ['CodiceAteco', BANDO.details.ateco_codes[0]],
  ['FonteUfficiale', FONTE_UFFICIALE],
  ['DatiIndice', INDICE],
  ['RisorsaIndice', INDICE.resources[0]],
];

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('documento serializzabile, OpenAPI 3.1.0, info e server', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(doc)), doc);
  assert.equal(doc.openapi, '3.1.0');
  const info = doc.info as Oggetto;
  assert.equal(info.version, VERSIONE_OPENAPI);
  assert.equal(info.termsOfService, URL_TERMINI);
  assert.deepEqual(info.contact, { url: URL_DOCUMENTAZIONE });
  assert.deepEqual(info.license, { name: 'Uso soggetto ai termini EduNews24', url: URL_TERMINI });
  assert.equal(typeof info.description, 'string');
  for (const frammento of ['436', '2 ore', 'links.next', 'nome host', 'region=X', 'Retry-After', 'nginx', 'Cloudflare']) {
    assert.ok((info.description as string).includes(frammento), frammento);
  }
  assert.deepEqual(doc.servers, [{ url: BASE_API }]);
  assert.deepEqual(doc.security, []);
  // Due chiamate: oggetti distinti ma uguali.
  const altro = documentoOpenApi();
  assert.notEqual(altro, doc);
  assert.deepEqual(altro, doc);
});

test('tutti i path del piano presenti, tutti in GET', () => {
  const attesi = [
    '/', '/openapi.json', '/articles', '/articles/{id}', '/categories', '/interpelli', '/interpelli/{id}',
    '/selezione-personale', '/selezione-personale/{id}', '/bandi', '/bandi/{id}',
    ...RISORSE.flatMap((r) => [`/feeds/${r}.json`, `/feeds/${r}.xml`]),
    '/feeds/articles/{category}.json', '/feeds/articles/{category}.xml',
  ];
  const paths = doc.paths as Record<string, Oggetto>;
  assert.deepEqual(Object.keys(paths).sort(), [...attesi].sort());
  const id = new Set<string>();
  for (const [percorso, voce] of Object.entries(paths)) {
    assert.deepEqual(Object.keys(voce), ['get'], percorso);
    const get = voce.get as Oggetto;
    assert.ok(!id.has(get.operationId as string), `operationId duplicato ${String(get.operationId)}`);
    id.add(get.operationId as string);
    const risposte = get.responses as Oggetto;
    assert.ok(risposte['200'], percorso);
    assert.ok(risposte['429'], percorso);
  }
});

test('parametri degli elenchi = SPEC_PARAMETRI (nome e ordine)', () => {
  const paths = doc.paths as Record<string, Oggetto>;
  for (const risorsa of RISORSE) {
    const get = paths[`/${risorsa}`].get as Oggetto;
    const nomi = (get.parameters as Oggetto[]).map((p) => {
      const parametro = risolvi(p.$ref as string) as Oggetto;
      assert.equal(parametro.in, 'query');
      assert.equal(parametro.required, false);
      return parametro.name;
    });
    assert.deepEqual(nomi, SPEC_PARAMETRI.get(risorsa), risorsa);
  }
  const parametri = componenti.parameters as Record<string, Oggetto>;
  assert.deepEqual((parametri.region.schema as Oggetto).enum, SLUG_REGIONI);
  assert.equal(SLUG_REGIONI.length, 20);
  assert.equal((parametri.category.schema as Oggetto).pattern, '^[a-z0-9]+(?:-[a-z0-9]+)*$');
  assert.deepEqual(parametri.limit.schema, { type: 'integer', minimum: 1, maximum: 100, default: 20 });
  for (const nome of ['has_video', 'national']) assert.deepEqual(parametri[nome].schema, { type: 'boolean' });
  for (const nome of ['since', 'until', 'updated_since']) {
    const s = parametri[nome].schema as Oggetto;
    assert.equal(s.type, 'string');
    assert.deepEqual(s.anyOf, [{ format: 'date' }, { format: 'date-time' }]);
    assert.ok((parametri[nome].description as string).length > 20);
  }
  assert.equal((parametri.cursor.schema as Oggetto).type, 'string');
  // I dettagli hanno solo l'id di path, i feed per categoria solo la categoria.
  const idDettaglio = risolvi(((paths['/bandi/{id}'].get as Oggetto).parameters as Oggetto[])[0].$ref as string) as Oggetto;
  assert.equal(idDettaglio.in, 'path');
  assert.equal(idDettaglio.name, 'id');
  const categoriaFeed = risolvi(((paths['/feeds/articles/{category}.xml'].get as Oggetto).parameters as Oggetto[])[0].$ref as string) as Oggetto;
  assert.equal(categoriaFeed.in, 'path');
  assert.equal(categoriaFeed.name, 'category');
  assert.equal('parameters' in (paths['/feeds/articles.json'].get as Oggetto), false);
});

test('ogni $ref e ogni mapping del discriminatore e\' risolvibile; niente additionalProperties', () => {
  let riferimenti = 0;
  visita(doc, (chiave, valore, genitore) => {
    assert.notEqual(chiave, 'additionalProperties');
    if (chiave === '$ref') {
      assert.equal(typeof valore, 'string');
      assert.notEqual(risolvi(valore as string), undefined);
      riferimenti += 1;
    }
    if (chiave === 'mapping' && genitore.propertyName === 'type') {
      for (const destinazione of Object.values(valore as Oggetto)) risolvi(destinazione as string);
    }
  });
  assert.ok(riferimenti > 100, `solo ${riferimenti} riferimenti`);
});

test('Filtri*: stesse chiavi, stesso ordine di meta.filters, senza limit e cursor, tutte nullable', () => {
  const filtriVuoti: FiltriElenco = {
    category: null, has_video: null, region: null, national: null, since: null, until: null,
    updated_since: null, limit: 20, cursor: null,
  };
  const nomiSchema = new Map<Risorsa, string>([
    ['articles', 'FiltriArticoli'], ['interpelli', 'FiltriInterpelli'],
    ['selezione-personale', 'FiltriSelezione'], ['bandi', 'FiltriBandi'],
  ]);
  for (const risorsa of RISORSE) {
    const s = schema(nomiSchema.get(risorsa) ?? '');
    const chiavi = Object.keys(s.properties as Oggetto);
    assert.equal(chiavi.includes('limit') || chiavi.includes('cursor'), false);
    assert.deepEqual(chiavi, filtriMeta(risorsa, filtriVuoti).map(([nome]) => nome), risorsa);
    assert.deepEqual(chiavi, (SPEC_PARAMETRI.get(risorsa) ?? []).filter((n) => n !== 'limit' && n !== 'cursor'));
    assert.deepEqual(s.required, chiavi);
    for (const k of chiavi) assert.ok(tipiDi((s.properties as Record<string, Oggetto>)[k]).includes('null'), `${risorsa}.${k}`);
  }
  assert.deepEqual(
    ((schema('FiltriInterpelli').properties as Oggetto).region as Oggetto).enum,
    [...SLUG_REGIONI, null],
  );
});

test('Problema: code enum = CODICI_ERRORE; risposte d\'errore complete', () => {
  const problema = schema('Problema');
  const props = problema.properties as Record<string, Oggetto>;
  assert.deepEqual(props.code.enum, CODICI_ERRORE);
  assert.deepEqual(problema.required, ['type', 'title', 'status', 'detail', 'instance', 'code']);
  assert.deepEqual(Object.keys(props), ['type', 'title', 'status', 'detail', 'instance', 'code', 'errors', 'retry_after', 'first']);
  assert.deepEqual(schema('ErroreParametro').required, ['parameter', 'detail']);

  const risposte = componenti.responses as Record<string, Oggetto>;
  assert.deepEqual(Object.keys(risposte), [
    'NonModificato', 'RichiestaNonValida', 'NonTrovato', 'MetodoNonConsentito', 'TroppeRichieste',
    'ErroreInterno', 'ServizioNonDisponibile',
  ]);
  assert.equal('content' in risposte.NonModificato, false);
  for (const nome of Object.keys(risposte).filter((n) => n !== 'NonModificato')) {
    assert.deepEqual(Object.keys(risposte[nome].content as Oggetto), ['application/problem+json'], nome);
  }
  const headers429 = Object.keys(risposte.TroppeRichieste.headers as Oggetto);
  for (const h of ['Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset', 'RateLimit-Policy']) {
    assert.ok(headers429.includes(h), h);
  }
  assert.ok(Object.keys(risposte.ServizioNonDisponibile.headers as Oggetto).includes('Retry-After'));
  assert.ok(Object.keys(risposte.MetodoNonConsentito.headers as Oggetto).includes('Allow'));
});

test('schemi DTO: tutte le proprieta\' required e uguali ai campi dei DTO', () => {
  for (const [nome, esempio] of COPPIE) {
    const { chiavi, obbligatorie } = proprieta(schema(nome));
    assert.deepEqual(chiavi, Object.keys(esempio), nome);
    assert.deepEqual([...obbligatorie].sort(), [...chiavi].sort(), nome);
  }
  // OpportunitaBase = campi comuni, senza details.
  assert.deepEqual(proprieta(schema('OpportunitaBase')).chiavi, Object.keys(INTERPELLO).filter((k) => k !== 'details'));
  // Oggetti annidati senza schema proprio.
  const linksCategoria = (schema('Categoria').properties as Record<string, Oggetto>).links;
  assert.deepEqual(Object.keys(linksCategoria.properties as Oggetto), Object.keys(CATEGORIA.links));
  assert.deepEqual(linksCategoria.required, Object.keys(CATEGORIA.links));
  const limite = (schema('DatiIndice').properties as Record<string, Oggetto>).rate_limit;
  assert.deepEqual(limite.required, Object.keys(INDICE.rate_limit));
});

test('schemi DTO: nullabilita\' coerente con i DTO', () => {
  const nullabili = new Map<string, readonly string[]>([
    ['Articolo', ['title_summary', 'excerpt', 'summary', 'image_url', 'thumbnail_url', 'video']],
    ['Video', ['mime_type', 'thumbnail_url', 'duration_seconds']],
    ['Categoria', ['position']],
    ['OpportunitaBase', ['summary', 'updated_at', 'deadline_on', 'deadline_at', 'status']],
    ['DettagliInterpello', ['official_title', 'competition_class', 'province', 'city']],
    ['DettagliSelezione', ['official_title', 'code', 'position', 'positions_count', 'procedure_type', 'salary_min', 'salary_max']],
    ['DettagliBando', ['short_title', 'issuer', 'geographic_area', 'kind', 'program', 'funding_method',
      'total_amount_eur', 'max_amount_per_project_eur', 'opens_on', 'source_published_on',
      // v1.1: tutti nullabili, perche' oggi sono tutti null.
      'official_source', 'opens_on_verified', 'deadline_verified', 'last_checked_at']],
    ['FonteUfficiale', ['type', 'verified_on']],
    ['CodiceAteco', ['description']],
    ['RisorsaIndice', ['feeds']],
  ]);
  for (const [nome, campi] of nullabili) {
    const props = schema(nome).properties as Record<string, Oggetto>;
    for (const [campo, s] of Object.entries(props)) {
      const ammetteNull = tipiDi(s).includes('null') ||
        (Array.isArray(s.oneOf) && (s.oneOf as Oggetto[]).some((v) => v.type === 'null'));
      assert.equal(ammetteNull, campi.includes(campo), `${nome}.${campo}`);
      // Gli array non sono mai null.
      if (tipiDi(s).includes('array')) assert.deepEqual(s.type, 'array', `${nome}.${campo}`);
    }
  }
  const status = (schema('OpportunitaBase').properties as Record<string, Oggetto>).status;
  // v1.1: due valori in piu', in coda ai tre gia' pubblicati.
  assert.deepEqual(status.enum, ['open', 'closed', 'upcoming', 'suspended', 'revoked', null]);
  // `host` e' un host, non un URL: format hostname (minuscolo, senza www.).
  const host = (schema('FonteUfficiale').properties as Record<string, Oggetto>).host;
  assert.equal(host.format, 'hostname');
});

test('Opportunita: oneOf con discriminatore type; tipi costanti', () => {
  const opportunita = schema('Opportunita');
  assert.deepEqual(opportunita.oneOf, [
    { $ref: '#/components/schemas/Interpello' },
    { $ref: '#/components/schemas/SelezionePersonale' },
    { $ref: '#/components/schemas/Bando' },
  ]);
  assert.equal((opportunita.discriminator as Oggetto).propertyName, 'type');
  const costanti = new Map([['Interpello', 'interpello'], ['SelezionePersonale', 'selezione-personale'], ['Bando', 'bando']]);
  for (const [nome, tipo] of costanti) {
    const parte = (schema(nome).allOf as Oggetto[])[1];
    assert.equal(((parte.properties as Oggetto).type as Oggetto).const, tipo);
  }
  assert.equal(((schema('Articolo').properties as Oggetto).type as Oggetto).const, 'article');
});

test('envelope {data, meta, links} per ogni risorsa', () => {
  const envelope = [
    'ElencoArticoli', 'DettaglioArticolo', 'ElencoInterpelli', 'DettaglioInterpello', 'ElencoSelezionePersonale',
    'DettaglioSelezionePersonale', 'ElencoBandi', 'DettaglioBando', 'ElencoCategorie', 'Indice',
  ];
  for (const nome of envelope) {
    const s = schema(nome);
    assert.deepEqual(Object.keys(s.properties as Oggetto), ['data', 'meta', 'links'], nome);
    assert.deepEqual(s.required, ['data', 'meta', 'links'], nome);
  }
  assert.deepEqual(schema('LinksElenco').required, ['self', 'first', 'next', 'describedby']);
  assert.deepEqual(schema('LinksDettaglio').required, ['self', 'collection', 'html', 'describedby']);
  assert.deepEqual(schema('LinksSemplici').required, ['self', 'describedby']);
  assert.deepEqual(schema('MetaElenco').required,
    ['api_version', 'resource', 'count', 'limit', 'has_more', 'sort', 'filters', 'attribution', 'terms']);
  assert.deepEqual(schema('MetaDettaglio').required, ['api_version', 'resource', 'attribution', 'terms']);
  assert.deepEqual(schema('MetaCategorie').required, ['api_version', 'resource', 'count', 'attribution', 'terms']);
  assert.deepEqual(schema('MetaIndice').required, ['api_version', 'resource', 'attribution', 'terms']);
  assert.deepEqual(schema('Attribuzione').required, ['text', 'url']);
});

test('esempi: chiavi coerenti con gli schemi e con gli esempi tipizzati di testi-doc', () => {
  const esempi = componenti.examples as Record<string, Oggetto>;
  const elenco = esempi.ElencoArticoli.value as Oggetto;
  assert.deepEqual(Object.keys(elenco), ['data', 'meta', 'links']);
  assert.deepEqual(Object.keys((elenco.data as Oggetto[])[0]), Object.keys(ARTICOLO));
  assert.deepEqual(Object.keys(elenco.meta as Oggetto), schema('MetaElenco').required);
  assert.deepEqual(Object.keys((elenco.meta as Oggetto).filters as Oggetto), Object.keys(schema('FiltriArticoli').properties as Oggetto));
  assert.deepEqual(Object.keys(elenco.links as Oggetto), schema('LinksElenco').required);
  const dettaglio = esempi.DettaglioSelezionePersonale.value as Oggetto;
  assert.deepEqual(Object.keys(dettaglio.data as Oggetto), Object.keys(SELEZIONE));
  assert.deepEqual(Object.keys(dettaglio.links as Oggetto), schema('LinksDettaglio').required);
  assert.deepEqual(Object.keys((esempi.DettaglioInterpello.value as Oggetto).data as Oggetto), Object.keys(INTERPELLO));
  assert.deepEqual(Object.keys((esempi.DettaglioBando.value as Oggetto).data as Oggetto), Object.keys(BANDO));
  assert.deepEqual(Object.keys((esempi.Indice.value as Oggetto).data as Oggetto), Object.keys(INDICE));
  assert.equal((esempi.ErroreParametri.value as Oggetto).code, 'invalid-parameter');
  assert.equal((esempi.ErroreLimite.value as Oggetto).retry_after, 1);

  // Gli esempi di testi-doc (controllati da tsc) hanno le stesse chiavi dei DTO costruiti qui.
  assert.deepEqual(Object.keys(esempioArticolo()), Object.keys(ARTICOLO));
  assert.deepEqual(Object.keys(esempioVideo()), Object.keys(VIDEO));
  assert.deepEqual(Object.keys(esempioSelezione()), Object.keys(SELEZIONE));
  assert.deepEqual(Object.keys(esempioSelezione().details), Object.keys(SELEZIONE.details));
  assert.deepEqual(Object.keys(esempioInterpello().details), Object.keys(INTERPELLO.details));
  assert.deepEqual(Object.keys(esempioBando().details), Object.keys(BANDO.details));
  assert.deepEqual(Object.keys(esempioCategoria()), Object.keys(CATEGORIA));
});

test('feed: tipi media e indice con le risorse', () => {
  const paths = doc.paths as Record<string, Oggetto>;
  const contenuto = (percorso: string): string[] =>
    Object.keys((((paths[percorso].get as Oggetto).responses as Oggetto)['200'] as Oggetto).content as Oggetto);
  for (const r of RISORSE) {
    assert.deepEqual(contenuto(`/feeds/${r}.json`), ['application/feed+json']);
    assert.deepEqual(contenuto(`/feeds/${r}.xml`), ['application/rss+xml']);
  }
  assert.deepEqual(contenuto('/feeds/articles/{category}.json'), ['application/feed+json']);
  assert.deepEqual(contenuto('/articles'), ['application/json']);
  assert.deepEqual(contenuto('/openapi.json'), ['application/vnd.oai.openapi+json;version=3.1']);

  assert.deepEqual(INDICE.resources.map((r) => r.name), ['articles', 'categories', 'interpelli', 'selezione-personale', 'bandi']);
  assert.equal(INDICE.resources[1].feeds, null);
  assert.deepEqual(INDICE.resources[0].feeds, {
    json: 'https://edunews24.it/api/v1/feeds/articles.json', rss: 'https://edunews24.it/api/v1/feeds/articles.xml',
  });
  assert.deepEqual(INDICE.sections.map((s) => s.slug), ['interpelli', 'selezione-personale', 'bandi']);
  assert.deepEqual(INDICE.rate_limit, { requests: 60, window_seconds: 60 });
  assert.equal(INDICE.terms_of_service, URL_TERMINI);
});
