/**
 * Documento OpenAPI 3.1 dell'API /api/v1, scritto a mano e servito da
 * /api/v1/openapi.json.
 *
 * - Gli schemi dei DTO rispecchiano contratto.ts campo per campo: ogni campo e'
 *   `required` (sempre presente), la nullabilita' e' `type: [..., 'null']`.
 * - Parametri degli elenchi e schemi Filtri* sono GENERATI da SPEC_PARAMETRI:
 *   un parametro aggiunto li' appare qui senza toccare questo file.
 * - Niente `additionalProperties: false`: la v1 evolve in modo additivo e i
 *   client devono tollerare campi nuovi.
 * - I test (tests/api-v1/openapi.test.ts) difendono la coerenza con i DTO.
 */
import { SLUG_VALIDO } from '../slug';
import {
  BASE_API, ELEMENTI_FEED, LIMITE_MASSIMO, LIMITE_PREDEFINITO, LUNGHEZZA_MASSIMA_CURSORE, LUNGHEZZA_MASSIMA_QUERY,
  LUNGHEZZA_SINTESI, RATE_LIMIT_CAPACITA, RATE_LIMIT_POLICY, RATE_LIMIT_RICARICA, SITO, TESTO_ATTRIBUZIONE,
  URL_DOCUMENTAZIONE, URL_OPENAPI, URL_TERMINI, VERSIONE_API, VERSIONE_OPENAPI,
} from './costanti';
import { CODICI_ERRORE, DEFINIZIONE_ERRORE } from './errori';
import { datiIndice } from './indice';
import { COLONNA_DATA, ORDINE_PARAMETRI, SLUG_REGIONI, SPEC_PARAMETRI } from './parametri';
import { SEZIONI } from './sezioni';
import {
  CURSORE_ESEMPIO, GUIDA_SINCRONIZZAZIONE, PARAGRAFI_FEED, PARAGRAFI_REGIONI, PARAGRAFO_STATUS, REGOLE_PARAMETRI,
  RICHIESTA_ERRORE_PARAMETRI, TESTI_ERRORE, TITOLO_API, descrizioneOpenApi, esempioArticolo, esempioBando,
  esempioCategoria, esempioErroreLimite, esempioErroreParametri, esempioInterpello, esempioSelezione, esempioVideo,
} from './testi-doc';
import type { Risorsa, TipoOpportunita } from './contratto';
import type { CodiceErrore } from './errori';
import type { NomeParametro } from './parametri';

type Schema = Record<string, unknown>;
type Proprieta = ReadonlyArray<readonly [string, Schema]>;

const TIPI_OPPORTUNITA: readonly TipoOpportunita[] = ['interpello', 'selezione-personale', 'bando'];
const RISORSE: readonly Risorsa[] = ['articles', 'interpelli', 'selezione-personale', 'bandi'];
// v1.1: `suspended` e `revoked` si aggiungono in coda. L'ordine conta solo
// per il confronto dei test, ma i valori nuovi vanno dopo i vecchi: un client
// che generi codice dall'enum non deve vedersi rinumerare quelli esistenti.
const STATI: readonly (string | null)[] = ['open', 'closed', 'upcoming', 'suspended', 'revoked', null];
const PATTERN_SLUG = SLUG_VALIDO.source;

// ---------------------------------------------------------------------------
// Riferimenti
// ---------------------------------------------------------------------------

const rif = (nome: string): Schema => ({ $ref: `#/components/schemas/${nome}` });
const rifParametro = (nome: string): Schema => ({ $ref: `#/components/parameters/${nome}` });
const rifRisposta = (nome: string): Schema => ({ $ref: `#/components/responses/${nome}` });
const rifHeader = (nome: string): Schema => ({ $ref: `#/components/headers/${nome}` });
const rifEsempio = (nome: string): Schema => ({ $ref: `#/components/examples/${nome}` });

// ---------------------------------------------------------------------------
// Mattoni degli schemi (funzioni: ogni chiamata restituisce oggetti nuovi)
// ---------------------------------------------------------------------------

function conDescrizione(schema: Schema, descrizione: string | undefined): Schema {
  return descrizione === undefined ? schema : { description: descrizione, ...schema };
}

const testo = (d?: string): Schema => conDescrizione({ type: 'string', minLength: 1 }, d);
const testoONull = (d?: string): Schema => conDescrizione({ type: ['string', 'null'], minLength: 1 }, d);
const uri = (d?: string): Schema => conDescrizione({ type: 'string', format: 'uri' }, d);
const uriONull = (d?: string): Schema => conDescrizione({ type: ['string', 'null'], format: 'uri' }, d);
// `hostname`: minuscolo, senza `www.`. E' un host, non testo libero: la guardia
// «nessun URL esterno nei testi» di contratto.test.ts lo esenta come fa con `uri`.
const nomeHost = (d?: string): Schema => conDescrizione({ type: 'string', format: 'hostname', minLength: 1 }, d);
const istante = (d?: string): Schema => conDescrizione({ type: 'string', format: 'date-time' }, d);
const istanteONull = (d?: string): Schema => conDescrizione({ type: ['string', 'null'], format: 'date-time' }, d);
const giornoONull = (d?: string): Schema => conDescrizione({ type: ['string', 'null'], format: 'date' }, d);
const intero = (d?: string, minimo?: number): Schema =>
  conDescrizione(minimo === undefined ? { type: 'integer' } : { type: 'integer', minimum: minimo }, d);
const interoONull = (d?: string): Schema => conDescrizione({ type: ['integer', 'null'] }, d);
const numeroONull = (d?: string): Schema => conDescrizione({ type: ['number', 'null'] }, d);
const booleano = (d?: string): Schema => conDescrizione({ type: 'boolean' }, d);
const colore = (): Schema => ({ type: 'string', pattern: '^#[0-9A-Fa-f]{6}$', description: 'Colore esadecimale.' });
const costante = (valore: string): Schema => ({ type: 'string', const: valore });
const elencoDi = (elementi: Schema, d?: string): Schema => conDescrizione({ type: 'array', items: elementi }, d);
const oppureNull = (schema: Schema, d?: string): Schema => conDescrizione({ oneOf: [schema, { type: 'null' }] }, d);
const id = (): Schema => intero('Id numerico, chiave dell\'elemento (unico per tipo).', 1);

/** Oggetto con TUTTE le proprieta' obbligatorie, nell'ordine dato. */
function oggetto(proprieta: Proprieta, descrizione?: string): Schema {
  return conDescrizione({
    type: 'object',
    required: proprieta.map(([nome]) => nome),
    properties: Object.fromEntries(proprieta),
  }, descrizione);
}

/** Oggetto con un sottoinsieme di proprieta' obbligatorie (errori, feed). */
function oggettoParziale(proprieta: Proprieta, obbligatorie: readonly string[], descrizione?: string): Schema {
  return conDescrizione({
    type: 'object',
    required: [...obbligatorie],
    properties: Object.fromEntries(proprieta),
  }, descrizione);
}

// ---------------------------------------------------------------------------
// Descrittori delle risorse con elenco
// ---------------------------------------------------------------------------

interface DescrittoreRisorsa {
  risorsa: Risorsa;
  tag: string;
  elemento: string;
  elenco: string;
  dettaglio: string;
  filtri: string;
  idElenco: string;
  idDettaglio: string;
  sommarioElenco: string;
  sommarioDettaglio: string;
  descrizione: string;
  esempioDettaglio: string;
}

const DESCRITTORI: readonly DescrittoreRisorsa[] = [
  {
    risorsa: 'articles', tag: 'Articoli', elemento: 'Articolo', elenco: 'ElencoArticoli',
    dettaglio: 'DettaglioArticolo', filtri: 'FiltriArticoli', idElenco: 'elencoArticoli',
    idDettaglio: 'dettaglioArticolo', sommarioElenco: 'Articoli pubblicati',
    sommarioDettaglio: 'Un articolo',
    descrizione: 'Articoli pubblicati, dal più recente. Solo sintesi e metadati: il testo completo è alla ' +
      'pagina indicata da url.',
    esempioDettaglio: 'DettaglioArticolo',
  },
  {
    risorsa: 'interpelli', tag: 'Interpelli', elemento: 'Interpello', elenco: 'ElencoInterpelli',
    dettaglio: 'DettaglioInterpello', filtri: 'FiltriInterpelli', idElenco: 'elencoInterpelli',
    idDettaglio: 'dettaglioInterpello', sommarioElenco: 'Interpelli delle scuole',
    sommarioDettaglio: 'Un interpello',
    descrizione: 'Interpelli delle scuole per supplenze, dal più recente per data della fonte. deadline_*, ' +
      'status e updated_at sono sempre null.',
    esempioDettaglio: 'DettaglioInterpello',
  },
  {
    risorsa: 'selezione-personale', tag: 'Selezione personale', elemento: 'SelezionePersonale',
    elenco: 'ElencoSelezionePersonale', dettaglio: 'DettaglioSelezionePersonale', filtri: 'FiltriSelezione',
    idElenco: 'elencoSelezionePersonale', idDettaglio: 'dettaglioSelezionePersonale',
    sommarioElenco: 'Concorsi e selezioni pubbliche', sommarioDettaglio: 'Un concorso o una selezione',
    descrizione: 'Concorsi e selezioni pubbliche, dal più recente per data di pubblicazione sul portale inPA.',
    esempioDettaglio: 'DettaglioSelezionePersonale',
  },
  {
    risorsa: 'bandi', tag: 'Bandi', elemento: 'Bando', elenco: 'ElencoBandi', dettaglio: 'DettaglioBando',
    filtri: 'FiltriBandi', idElenco: 'elencoBandi', idDettaglio: 'dettaglioBando',
    sommarioElenco: 'Bandi e finanziamenti pubblici', sommarioDettaglio: 'Un bando',
    descrizione: 'Bandi e finanziamenti pubblici, dal più recente inserimento in EduNews24.',
    esempioDettaglio: 'DettaglioBando',
  },
];

function guidaPer(risorsa: Risorsa): string {
  return GUIDA_SINCRONIZZAZIONE
    .filter((passo) => passo.per.includes(risorsa))
    .map((passo) => `- ${passo.testo}`)
    .join('\n');
}

// ---------------------------------------------------------------------------
// Parametri (generati da SPEC_PARAMETRI)
// ---------------------------------------------------------------------------

function testoColonneData(): string {
  return 'Colonna per risorsa: ' + RISORSE.map((r) => `${r} → ${COLONNA_DATA.get(r) ?? 'published_at'}`).join('; ') + '.';
}

function parametroQuery(nome: NomeParametro): Schema {
  const regola = REGOLE_PARAMETRI.get(nome) ?? '';
  const base = (descrizione: string, schema: Schema): Schema => ({
    name: nome, in: 'query', required: false, description: descrizione, schema,
  });
  switch (nome) {
    case 'category':
      return { ...base(regola, { type: 'string', pattern: PATTERN_SLUG, maxLength: 64 }), example: 'scuola' };
    case 'has_video':
    case 'national':
      return base(regola, { type: 'boolean' });
    case 'region':
      return { ...base(regola, { type: 'string', enum: [...SLUG_REGIONI] }), example: 'marche' };
    case 'since':
    case 'until':
    case 'updated_since': {
      const descrizione = nome === 'updated_since' ? regola : `${regola} ${testoColonneData()}`;
      return {
        ...base(descrizione, { type: 'string', anyOf: [{ format: 'date' }, { format: 'date-time' }] }),
        example: '2026-09-21',
      };
    }
    case 'limit':
      return base(regola, { type: 'integer', minimum: 1, maximum: LIMITE_MASSIMO, default: LIMITE_PREDEFINITO });
    case 'cursor':
      return base(regola, { type: 'string', pattern: '^[A-Za-z0-9_-]+$', maxLength: LUNGHEZZA_MASSIMA_CURSORE });
  }
}

function parametri(): Schema {
  const voci: [string, Schema][] = ORDINE_PARAMETRI.map((nome) => [nome, parametroQuery(nome)]);
  voci.push(['id', {
    name: 'id', in: 'path', required: true, description: 'Id numerico dell\'elemento.',
    schema: { type: 'integer', minimum: 1, maximum: Number.MAX_SAFE_INTEGER }, example: 39382,
  }]);
  voci.push(['categoriaFeed', {
    name: 'category', in: 'path', required: true, description: 'Slug di una categoria di /categories.',
    schema: { type: 'string', pattern: PATTERN_SLUG, maxLength: 64 }, example: 'scuola',
  }]);
  return Object.fromEntries(voci);
}

function parametriElenco(risorsa: Risorsa): Schema[] {
  return (SPEC_PARAMETRI.get(risorsa) ?? []).map((nome) => rifParametro(nome));
}

// ---------------------------------------------------------------------------
// Schemi
// ---------------------------------------------------------------------------

function schemaFiltro(nome: NomeParametro): Schema {
  switch (nome) {
    case 'category':
      return { type: ['string', 'null'], pattern: PATTERN_SLUG };
    case 'has_video':
    case 'national':
      return { type: ['boolean', 'null'] };
    case 'region':
      return { type: ['string', 'null'], enum: [...SLUG_REGIONI, null] };
    case 'since':
    case 'until':
    case 'updated_since':
      return { type: ['string', 'null'], format: 'date-time', description: 'Forma canonica RFC 3339 (offset di Roma).' };
    case 'limit':
      return { type: 'integer' };
    case 'cursor':
      return { type: ['string', 'null'] };
  }
}

/** meta.filters: i parametri della risorsa senza limit e cursor, nello stesso ordine. */
function schemaFiltri(risorsa: Risorsa): Schema {
  const nomi = (SPEC_PARAMETRI.get(risorsa) ?? []).filter((n) => n !== 'limit' && n !== 'cursor');
  return oggetto(
    nomi.map((nome) => [nome, schemaFiltro(nome)] as const),
    'Filtri applicati in forma canonica; null se il parametro non è stato usato.',
  );
}

function schemaOpportunitaBase(): Schema {
  return oggetto([
    ['type', { type: 'string', enum: [...TIPI_OPPORTUNITA], description: 'Discriminatore.' }],
    ['id', id()],
    ['slug', testo('Informativo: non univoco, non usarlo come chiave.')],
    ['url', uri('Pagina canonica su edunews24.it.')],
    ['title', testo()],
    ['summary', testoONull('Sintesi in testo semplice.')],
    ['section', rif('Sezione')],
    ['published_at', istante()],
    ['updated_at', istanteONull('Ultima modifica (lo scadere non la aggiorna); null per gli interpelli.')],
    ['deadline_on', giornoONull('Giorno di scadenza (YYYY-MM-DD) come mostrato sul sito; null se assente o ' +
      'implausibile (oltre 8 anni dopo published_at). Bandi: la data di scadenza della fonte (deadline_at è ' +
      'null). Selezione del personale: il giorno UTC di data_scadenza; per le scadenze fra le 00:00 e le 01:59 ' +
      'di Roma (00:59 con l\'ora solare), tipicamente «ore 24:00 del giorno D», vale D, un giorno prima della ' +
      'data locale di deadline_at. status usa deadline_on.')],
    ['deadline_at', istanteONull('Istante di scadenza; null se ignoto o implausibile (oltre 8 anni dopo ' +
      'published_at).')],
    ['status', { type: ['string', 'null'], enum: [...STATI], description: PARAGRAFO_STATUS }],
    ['regions', elencoDi(rif('Regione'))],
    ['national', booleano('Portata nazionale.')],
  ], 'Campi comuni a interpelli, selezione del personale e bandi.');
}

function schemaTipoOpportunita(tipo: TipoOpportunita, dettagli: string, descrizione: string): Schema {
  return {
    description: descrizione,
    allOf: [
      rif('OpportunitaBase'),
      oggetto([
        ['type', costante(tipo)],
        ['details', rif(dettagli)],
      ]),
    ],
  };
}

function schemaArticolo(): Schema {
  return oggetto([
    ['type', costante('article')],
    ['id', id()],
    ['slug', testo('Informativo: non univoco, non usarlo come chiave.')],
    ['url', uri('Pagina canonica dell\'articolo.')],
    ['title', testo('Testo semplice ripulito dal markdown.')],
    ['title_summary', testoONull('Testo semplice ripulito dal markdown.')],
    ['excerpt', testoONull('Testo semplice ripulito dal markdown.')],
    ['summary', testoONull('Testo semplice ripulito dal markdown: intestazioni di servizio del generatore ' +
      '("Paragrafo 1", "Primo paragrafo (200 parole)", …) rimosse e titoli chiusi da un punto; troncato a circa ' +
      `${LUNGHEZZA_SINTESI} caratteri a fine frase.`)],
    ['category', rif('CategoriaArticolo')],
    ['secondary_categories', elencoDi(rif('CategoriaSecondaria'))],
    ['image_url', uriONull('Può essere ospitata da terzi: l\'URL non è una licenza.')],
    ['thumbnail_url', uriONull()],
    ['video', oppureNull(rif('Video'))],
    ['published_at', istante('Vedi le avvertenze sull\'euristica nella descrizione generale.')],
    ['tags', elencoDi(testo())],
    ['author', rif('Autore')],
  ], 'Articolo pubblicato (senza testo integrale).');
}

function schemaCategoria(): Schema {
  return oggetto([
    ['slug', testo()],
    ['name', testo()],
    ['color', colore()],
    ['position', interoONull('Ordine di esposizione; null in fondo.')],
    ['url', uri()],
    ['secondary_categories', elencoDi(rif('CategoriaSecondaria'))],
    ['links', oggetto([
      ['articles', uri()],
      ['feed_json', uri()],
      ['feed_rss', uri()],
    ])],
  ], 'Categoria degli articoli con le sue secondarie.');
}

function schemaDettagliSelezione(): Schema {
  return oggetto([
    ['official_title', testoONull()],
    ['code', testoONull('Codice del bando sul portale inPA.')],
    ['position', testoONull('Figura ricercata.')],
    ['positions_count', interoONull()],
    ['procedure_type', testoONull()],
    ['categories', elencoDi(testo())],
    ['sectors', elencoDi(testo())],
    ['organizations', elencoDi(testo())],
    ['locations', elencoDi(testo())],
    ['salary_min', numeroONull()],
    ['salary_max', numeroONull()],
  ]);
}

function schemaFonteUfficiale(): Schema {
  return oggetto([
    ['url', uri('Pagina o atto sul dominio dell\'ente, oppure scheda su un portale pubblico.')],
    ['host', nomeHost('Host in minuscolo, senza www.')],
    ['type', { type: ['string', 'null'], enum: ['institution', 'public_portal', null],
      description: 'institution: pagina o atto dell\'ente. public_portal: portale pubblico.' }],
    ['verified_on', giornoONull('Giorno della verifica.')],
  ], 'Fonte ufficiale del bando. Presente solo quando la verifica si è conclusa; mai un sito ' +
    'che si limita a ripubblicare bandi altrui.');
}

function schemaDettagliBando(): Schema {
  return oggetto([
    ['short_title', testoONull()],
    ['issuer', testoONull('Ente erogatore.')],
    ['geographic_area', testoONull('Testo libero, informativo.')],
    ['topics', elencoDi(testo())],
    ['kind', testoONull()],
    ['program', testoONull()],
    ['funding_method', testoONull()],
    ['sectors', elencoDi(testo())],
    ['beneficiaries', elencoDi(testo())],
    ['ateco_codes', elencoDi(rif('CodiceAteco'))],
    ['total_amount_eur', numeroONull()],
    ['max_amount_per_project_eur', numeroONull()],
    ['opens_on', giornoONull()],
    ['source_published_on', giornoONull('Data di pubblicazione presso la fonte.')],
    ['official_source', oppureNull(rif('FonteUfficiale'),
      'null finché la verifica non è conclusa. Aggiunto in 1.1.')],
    ['opens_on_verified', { type: ['boolean', 'null'],
      description: 'La data di apertura è stata verificata sulla fonte ufficiale? null = non lo sappiamo. Aggiunto in 1.1.' }],
    ['deadline_verified', { type: ['boolean', 'null'],
      description: 'La data di scadenza è stata verificata sulla fonte ufficiale? null = non lo sappiamo. Aggiunto in 1.1.' }],
    ['last_checked_at', istanteONull('Ultimo controllo sulla fonte ufficiale. Aggiunto in 1.1.')],
  ]);
}

function schemaElenco(d: DescrittoreRisorsa): Schema {
  return oggetto([
    ['data', elencoDi(rif(d.elemento))],
    ['meta', {
      allOf: [
        rif('MetaElenco'),
        { type: 'object', properties: { resource: { const: d.risorsa }, filters: rif(d.filtri) } },
      ],
    }],
    ['links', rif('LinksElenco')],
  ]);
}

function schemaDettaglio(d: DescrittoreRisorsa): Schema {
  return oggetto([
    ['data', rif(d.elemento)],
    ['meta', {
      allOf: [rif('MetaDettaglio'), { type: 'object', properties: { resource: { const: d.risorsa } } }],
    }],
    ['links', rif('LinksDettaglio')],
  ]);
}

function schemaVoceJsonFeed(): Schema {
  return oggettoParziale([
    ['id', testo('tag:edunews24.it,2026:<type>/<id>')],
    ['url', uri()],
    ['title', testo()],
    ['summary', testo()],
    ['content_text', testo('Sintesi, eventuale riga "Scadenza" e attribuzione con il link.')],
    ['image', uri()],
    ['date_published', istante()],
    ['date_modified', istante()],
    ['authors', elencoDi(oggetto([['name', testo()]]))],
    ['tags', elencoDi(testo())],
    ['attachments', elencoDi(oggettoParziale([
      ['url', uri()],
      ['mime_type', testo()],
      ['duration_in_seconds', intero(undefined, 1)],
    ], ['url', 'mime_type']))],
    ['_edunews24', {
      oneOf: [
        oggetto([['type', costante('article')], ['category', testo()]]),
        oggetto([
          ['type', { type: 'string', enum: [...TIPI_OPPORTUNITA] }],
          ['status', { type: ['string', 'null'], enum: [...STATI] }],
          ['deadline_on', giornoONull()],
        ]),
      ],
    }],
  ], ['id', 'url', 'title', 'content_text', 'date_published', '_edunews24'],
  'Voce di JSON Feed 1.1: i membri opzionali vuoti sono omessi, content_html non è mai presente.');
}

function schemi(): Schema {
  const voci: [string, Schema][] = [
    // Meta, attribuzione, filtri, link
    ['Attribuzione', oggetto([
      ['text', costante(TESTO_ATTRIBUZIONE)],
      ['url', uri('Link da rendere visibile accanto al contenuto.')],
    ], 'Attribuzione obbligatoria.')],
    ['MetaElenco', oggetto([
      ['api_version', testo()],
      ['resource', { type: 'string', enum: [...RISORSE] }],
      ['count', intero('Elementi in questa pagina (può essere minore di limit, anche 0, con has_more true).', 0)],
      ['limit', intero(undefined, 1)],
      ['has_more', booleano('Sempre uguale a links.next !== null.')],
      ['sort', testo()],
      ['filters', { anyOf: RISORSE.map((r) => rif(nomeFiltri(r))) }],
      ['attribution', rif('Attribuzione')],
      ['terms', uri()],
    ])],
    ['MetaDettaglio', oggetto([
      ['api_version', testo()],
      ['resource', { type: 'string', enum: [...RISORSE] }],
      ['attribution', rif('Attribuzione')],
      ['terms', uri()],
    ])],
    ['MetaCategorie', oggetto([
      ['api_version', testo()],
      ['resource', costante('categories')],
      ['count', intero(undefined, 0)],
      ['attribution', rif('Attribuzione')],
      ['terms', uri()],
    ])],
    ['MetaIndice', oggetto([
      ['api_version', testo()],
      ['resource', costante('index')],
      ['attribution', rif('Attribuzione')],
      ['terms', uri()],
    ])],
    ...RISORSE.map((r): [string, Schema] => [nomeFiltri(r), schemaFiltri(r)]),
    ['LinksElenco', oggetto([
      ['self', uri()],
      ['first', uri()],
      ['next', uriONull('Pagina successiva; null = fine dell\'elenco.')],
      ['describedby', uri()],
    ])],
    ['LinksDettaglio', oggetto([
      ['self', uri()],
      ['collection', uri()],
      ['html', uri('URL canonico sul sito.')],
      ['describedby', uri()],
    ])],
    ['LinksSemplici', oggetto([
      ['self', uri()],
      ['describedby', uri()],
    ])],
    // DTO
    ['Regione', oggetto([
      ['slug', { type: 'string', enum: [...SLUG_REGIONI] }],
      ['name', testo()],
    ])],
    ['Sezione', oggetto([
      ['slug', { type: 'string', enum: [...SEZIONI] }],
      ['name', testo()],
      ['color', colore()],
      ['url', uri()],
    ])],
    ['CategoriaArticolo', oggetto([
      ['slug', testo()],
      ['name', testo()],
      ['color', colore()],
      ['url', uri()],
    ])],
    ['CategoriaSecondaria', oggetto([
      ['slug', testo()],
      ['name', testo()],
    ])],
    ['Categoria', schemaCategoria()],
    ['Video', {
      ...oggetto([
        ['url', uri()],
        ['mime_type', testoONull('video/mp4 o video/quicktime se riconosciuto dall\'estensione.')],
        ['thumbnail_url', uriONull()],
        ['duration_seconds', { type: ['integer', 'null'], minimum: 1 }],
      ]),
      examples: [esempioVideo()],
    }],
    ['Autore', oggetto([
      ['name', testo('Nome pubblico del giornalista o "Redazione EduNews24".')],
    ])],
    ['Articolo', schemaArticolo()],
    ['OpportunitaBase', schemaOpportunitaBase()],
    ['DettagliInterpello', oggetto([
      ['official_title', testoONull()],
      ['competition_class', testoONull('Classe di concorso.')],
      ['province', testoONull()],
      ['city', testoONull()],
    ])],
    ['DettagliSelezione', schemaDettagliSelezione()],
    ['CodiceAteco', oggetto([
      ['code', testo()],
      ['description', testoONull()],
    ])],
    ['FonteUfficiale', schemaFonteUfficiale()],
    ['DettagliBando', schemaDettagliBando()],
    ['Interpello', schemaTipoOpportunita('interpello', 'DettagliInterpello', 'Interpello di una scuola.')],
    ['SelezionePersonale', schemaTipoOpportunita('selezione-personale', 'DettagliSelezione', 'Concorso o selezione pubblica.')],
    ['Bando', schemaTipoOpportunita('bando', 'DettagliBando', 'Bando o finanziamento pubblico.')],
    ['Opportunita', {
      description: 'Elemento di una delle tre sezioni.',
      oneOf: [rif('Interpello'), rif('SelezionePersonale'), rif('Bando')],
      discriminator: {
        propertyName: 'type',
        mapping: {
          interpello: '#/components/schemas/Interpello',
          'selezione-personale': '#/components/schemas/SelezionePersonale',
          bando: '#/components/schemas/Bando',
        },
      },
    }],
    // Envelope
    ...DESCRITTORI.flatMap((d): [string, Schema][] => [[d.elenco, schemaElenco(d)], [d.dettaglio, schemaDettaglio(d)]]),
    ['ElencoCategorie', oggetto([
      ['data', elencoDi(rif('Categoria'))],
      ['meta', rif('MetaCategorie')],
      ['links', rif('LinksSemplici')],
    ])],
    ['RisorsaIndice', oggetto([
      ['name', testo()],
      ['url', uri()],
      ['feeds', oppureNull(oggetto([['json', uri()], ['rss', uri()]]))],
    ])],
    ['DatiIndice', oggetto([
      ['name', testo()],
      ['version', testo()],
      ['documentation', uri()],
      ['openapi', uri()],
      ['terms_of_service', uri()],
      ['content_signal', testo()],
      ['rate_limit', oggetto([['requests', intero(undefined, 1)], ['window_seconds', intero(undefined, 1)]])],
      ['resources', elencoDi(rif('RisorsaIndice'))],
      ['sections', elencoDi(rif('Sezione'))],
    ])],
    ['Indice', oggetto([
      ['data', rif('DatiIndice')],
      ['meta', rif('MetaIndice')],
      ['links', rif('LinksSemplici')],
    ])],
    // Errori
    ['ErroreParametro', oggettoParziale([
      ['parameter', testo()],
      ['detail', testo()],
      ['allowed', elencoDi(testo(), 'Valori ammessi, per i parametri con un elenco chiuso.')],
    ], ['parameter', 'detail'])],
    ['Problema', oggettoParziale([
      ['type', uri('https://edunews24.it/sviluppatori/api#error-<code>')],
      ['title', testo()],
      ['status', { type: 'integer', minimum: 100, maximum: 599 }],
      ['detail', testo('Mai valori ricevuti né messaggi interni.')],
      ['instance', uri('URL del solo path, senza query.')],
      ['code', { type: 'string', enum: [...CODICI_ERRORE] }],
      ['errors', elencoDi(rif('ErroreParametro'), 'Solo sui 400 dei parametri.')],
      ['retry_after', intero('Secondi di attesa, solo su 429 e 503.', 1)],
      ['first', uri('Solo su invalid-cursor: la prima pagina con gli stessi filtri, senza cursore.')],
    ], ['type', 'title', 'status', 'detail', 'instance', 'code'], 'Errore RFC 9457 (application/problem+json).')],
    // Feed
    ['JsonFeed', oggetto([
      ['version', costante('https://jsonfeed.org/version/1.1')],
      ['title', testo()],
      ['home_page_url', uri()],
      ['feed_url', uri()],
      ['description', testo()],
      ['favicon', uri()],
      ['language', costante('it-IT')],
      ['authors', elencoDi(oggetto([['name', testo()], ['url', uri()]]))],
      ['_edunews24', oggetto([['api', uri()], ['terms', uri()], ['content_signal', testo()]])],
      ['items', elencoDi(rif('VoceJsonFeed'))],
    ], 'JSON Feed 1.1 con l\'estensione _edunews24.')],
    ['VoceJsonFeed', schemaVoceJsonFeed()],
  ];
  return Object.fromEntries(voci);
}

function nomeFiltri(risorsa: Risorsa): string {
  return DESCRITTORI.find((d) => d.risorsa === risorsa)?.filtri ?? 'FiltriArticoli';
}

// ---------------------------------------------------------------------------
// Header, risposte, esempi
// ---------------------------------------------------------------------------

function headers(): Schema {
  const intestazione = (descrizione: string, schema: Schema, esempio?: string | number): Schema =>
    esempio === undefined ? { description: descrizione, schema } : { description: descrizione, schema, example: esempio };
  return Object.fromEntries([
    ['ETag', intestazione('ETag debole del corpo: rimandarlo in If-None-Match per ottenere 304.', { type: 'string' },
      'W/"Xb1q0m4Tq3o2Zr8kPp7yWc5dLh2"')],
    ['Cache-Control', intestazione('Durata di cache per tipo di risposta (vedi la documentazione).', { type: 'string' })],
    ['Link', intestazione('rel="next" negli elenchi, rel="canonical" nei dettagli, più service-desc e ' +
      'terms-of-service.', { type: 'string' })],
    ['RateLimit-Policy', intestazione('Politica del limite: <capacità>;w=<capacità/ricarica>, cioè richieste ' +
      `di fila e secondi per ricaricarle tutte (predefinita ${RATE_LIMIT_POLICY}).`, { type: 'string' },
      RATE_LIMIT_POLICY)],
    ['RateLimit-Limit', intestazione('Capacità: richieste ammesse di fila.', { type: 'integer' }, RATE_LIMIT_CAPACITA)],
    ['RateLimit-Remaining', intestazione('Richieste ancora disponibili.', { type: 'integer' }, 0)],
    ['RateLimit-Reset', intestazione('Secondi per tornare alla capacità piena.', { type: 'integer' },
      Math.ceil(RATE_LIMIT_CAPACITA / RATE_LIMIT_RICARICA))],
    ['Retry-After', intestazione('Secondi da attendere prima di riprovare.', { type: 'integer' }, 1)],
    ['Allow', intestazione('Metodi ammessi.', { type: 'string' }, 'GET, HEAD, OPTIONS')],
    ['X-EduNews24-Cache', intestazione('STALE se la risposta è una copia servita durante un guasto del database. ' +
      'Non esposto via CORS.', { type: 'string', enum: ['STALE'] })],
  ]);
}

function rispostaProblema(codici: readonly CodiceErrore[], intestazioni: readonly string[], esempio: string | null): Schema {
  const descrizione = codici.map((codice) => {
    const definizione = DEFINIZIONE_ERRORE.get(codice);
    const quando = TESTI_ERRORE.get(codice)?.quando ?? '';
    return `${codice} (${definizione?.titolo ?? ''}): ${quando}`;
  }).join(' ');
  const media: Schema = { schema: rif('Problema') };
  if (esempio !== null) media.examples = Object.fromEntries([[esempio, rifEsempio(esempio)]]);
  return {
    description: descrizione,
    headers: Object.fromEntries(intestazioni.map((h) => [h, rifHeader(h)])),
    content: { 'application/problem+json': media },
  };
}

function risposte(): Schema {
  return {
    NonModificato: {
      description: 'Nessuna modifica rispetto all\'ETag inviato in If-None-Match: nessun corpo, header come il 200.',
      headers: { ETag: rifHeader('ETag'), 'Cache-Control': rifHeader('Cache-Control'), 'RateLimit-Policy': rifHeader('RateLimit-Policy') },
    },
    RichiestaNonValida: rispostaProblema(['invalid-parameter', 'unknown-parameter', 'invalid-cursor'],
      ['Cache-Control', 'RateLimit-Policy'], 'ErroreParametri'),
    NonTrovato: rispostaProblema(['not-found'], ['Cache-Control', 'RateLimit-Policy'], null),
    MetodoNonConsentito: rispostaProblema(['method-not-allowed'], ['Allow', 'Cache-Control', 'RateLimit-Policy'], null),
    TroppeRichieste: rispostaProblema(['rate-limited'],
      ['Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset', 'RateLimit-Policy', 'Cache-Control'],
      'ErroreLimite'),
    ErroreInterno: rispostaProblema(['internal-error'], ['Cache-Control', 'RateLimit-Policy'], null),
    ServizioNonDisponibile: rispostaProblema(['service-unavailable'], ['Retry-After', 'Cache-Control', 'RateLimit-Policy'], null),
  };
}

const ATTRIBUZIONE_SITO = { text: TESTO_ATTRIBUZIONE, url: SITO };

function metaDettaglio(risorsa: Risorsa): Schema {
  return { api_version: VERSIONE_API, resource: risorsa, attribution: ATTRIBUZIONE_SITO, terms: URL_TERMINI };
}

function linksDettaglio(percorso: string, idElemento: number, html: string): Schema {
  return {
    self: `${BASE_API}/${percorso}/${idElemento}`,
    collection: `${BASE_API}/${percorso}`,
    html,
    describedby: URL_OPENAPI,
  };
}

function esempi(): Schema {
  const articolo = esempioArticolo();
  const selezione = esempioSelezione();
  const interpello = esempioInterpello();
  const bando = esempioBando();
  const primaPagina = `${BASE_API}/articles?category=scuola&limit=1`;
  return {
    ElencoArticoli: {
      summary: 'GET /articles?category=scuola&limit=1 (testi illustrativi)',
      value: {
        data: [articolo],
        meta: {
          api_version: VERSIONE_API, resource: 'articles', count: 1, limit: 1, has_more: true,
          sort: '-published_at,-id',
          filters: { category: 'scuola', has_video: null, since: null, until: null },
          attribution: ATTRIBUZIONE_SITO, terms: URL_TERMINI,
        },
        links: {
          self: primaPagina,
          first: primaPagina,
          next: `${primaPagina}&cursor=${CURSORE_ESEMPIO}`,
          describedby: URL_OPENAPI,
        },
      },
    },
    DettaglioArticolo: {
      summary: 'GET /articles/39382 (testi illustrativi)',
      value: { data: articolo, meta: metaDettaglio('articles'), links: linksDettaglio('articles', articolo.id, articolo.url) },
    },
    DettaglioInterpello: {
      summary: `GET /interpelli/${interpello.id} (testi illustrativi)`,
      value: {
        data: interpello, meta: metaDettaglio('interpelli'),
        links: linksDettaglio('interpelli', interpello.id, interpello.url),
      },
    },
    DettaglioSelezionePersonale: {
      summary: `GET /selezione-personale/${selezione.id} (testi illustrativi)`,
      value: {
        data: selezione, meta: metaDettaglio('selezione-personale'),
        links: linksDettaglio('selezione-personale', selezione.id, selezione.url),
      },
    },
    DettaglioBando: {
      summary: `GET /bandi/${bando.id} (testi illustrativi)`,
      value: { data: bando, meta: metaDettaglio('bandi'), links: linksDettaglio('bandi', bando.id, bando.url) },
    },
    ElencoCategorie: {
      summary: 'GET /categories (estratto)',
      value: {
        data: [esempioCategoria()],
        meta: { api_version: VERSIONE_API, resource: 'categories', count: 1, attribution: ATTRIBUZIONE_SITO, terms: URL_TERMINI },
        links: { self: `${BASE_API}/categories`, describedby: URL_OPENAPI },
      },
    },
    Indice: {
      summary: 'GET /',
      value: {
        data: datiIndice({ requests: RATE_LIMIT_CAPACITA, window_seconds: 60 }),
        meta: { api_version: VERSIONE_API, resource: 'index', attribution: ATTRIBUZIONE_SITO, terms: URL_TERMINI },
        links: { self: BASE_API, describedby: URL_OPENAPI },
      },
    },
    ErroreParametri: {
      summary: `GET ${RICHIESTA_ERRORE_PARAMETRI}: 400 con due errori di forma`,
      value: esempioErroreParametri(),
    },
    ErroreLimite: { summary: 'GET /bandi: 429 alla prima richiesta oltre il limite', value: esempioErroreLimite() },
  };
}

// ---------------------------------------------------------------------------
// Percorsi
// ---------------------------------------------------------------------------

type CodiceRisposta = '304' | '400' | '404' | '429' | '500' | '503';

function nomeRisposta(codice: CodiceRisposta): string {
  switch (codice) {
    case '304': return 'NonModificato';
    case '400': return 'RichiestaNonValida';
    case '404': return 'NonTrovato';
    case '429': return 'TroppeRichieste';
    case '500': return 'ErroreInterno';
    case '503': return 'ServizioNonDisponibile';
  }
}

const HEADER_OK: readonly string[] = ['Cache-Control', 'ETag', 'Link', 'RateLimit-Policy', 'X-EduNews24-Cache'];

function rispostaOk(descrizione: string, tipoMedia: string, schema: Schema, esempio: string | null): Schema {
  const media: Schema = { schema };
  if (esempio !== null) media.examples = Object.fromEntries([[esempio, rifEsempio(esempio)]]);
  return {
    description: descrizione,
    headers: Object.fromEntries(HEADER_OK.map((h) => [h, rifHeader(h)])),
    content: Object.fromEntries([[tipoMedia, media]]),
  };
}

interface OpzioniOperazione {
  id: string;
  tag: string;
  sommario: string;
  descrizione: string;
  parametri: Schema[];
  ok: Schema;
  errori: readonly CodiceRisposta[];
}

function operazione(o: OpzioniOperazione): Schema {
  const get: Schema = {
    operationId: o.id,
    tags: [o.tag],
    summary: o.sommario,
    description: o.descrizione,
  };
  if (o.parametri.length > 0) get.parameters = o.parametri;
  get.responses = Object.fromEntries([
    ['200', o.ok],
    ...o.errori.map((codice) => [codice, rifRisposta(nomeRisposta(codice))] as const),
  ]);
  return { get };
}

const ERRORI_ELENCO: readonly CodiceRisposta[] = ['304', '400', '429', '500', '503'];

/** Dettagli e /categories: la query deve essere vuota. */
const NESSUN_PARAMETRO = 'Nessun parametro di query ammesso: qualunque parametro dà 400 unknown-parameter e una ' +
  `query oltre ${LUNGHEZZA_MASSIMA_QUERY} caratteri un solo errore "(query)" invalid-parameter.`;
const ERRORI_DETTAGLIO: readonly CodiceRisposta[] = ['304', '400', '404', '429', '500', '503'];
const ERRORI_FEED: readonly CodiceRisposta[] = ['304', '404', '429', '500', '503'];

function percorsiRisorsa(d: DescrittoreRisorsa): [string, Schema][] {
  const percorso = `/${d.risorsa}`;
  const descrizioneElenco = [
    d.descrizione,
    d.risorsa === 'articles' ? '' : PARAGRAFI_REGIONI.join(' '),
    `Sincronizzazione:\n\n${guidaPer(d.risorsa)}`,
  ].filter((t) => t !== '').join('\n\n');
  return [
    [percorso, operazione({
      id: d.idElenco,
      tag: d.tag,
      sommario: d.sommarioElenco,
      descrizione: descrizioneElenco,
      parametri: parametriElenco(d.risorsa),
      ok: rispostaOk('Una pagina dell\'elenco.', 'application/json', rif(d.elenco),
        d.risorsa === 'articles' ? 'ElencoArticoli' : null),
      errori: ERRORI_ELENCO,
    })],
    [`${percorso}/{id}`, operazione({
      id: d.idDettaglio,
      tag: d.tag,
      sommario: d.sommarioDettaglio,
      descrizione: `${d.descrizione} ${NESSUN_PARAMETRO} Header Link con rel="canonical".`,
      parametri: [rifParametro('id')],
      ok: rispostaOk('L\'elemento.', 'application/json', rif(d.dettaglio), d.esempioDettaglio),
      errori: ERRORI_DETTAGLIO,
    })],
  ];
}

function percorsoFeed(risorsa: Risorsa, formato: 'json' | 'xml', perCategoria: boolean): [string, Schema] {
  const percorso = perCategoria ? `/feeds/articles/{category}.${formato}` : `/feeds/${risorsa}.${formato}`;
  const nomeFormato = formato === 'json' ? 'JSON Feed 1.1' : 'RSS 2.0';
  const idOperazione = 'feed' + (perCategoria ? 'Categoria' : '') +
    risorsa.split('-').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('') +
    (formato === 'json' ? 'Json' : 'Rss');
  const ok = formato === 'json'
    ? rispostaOk(nomeFormato, 'application/feed+json', rif('JsonFeed'), null)
    : rispostaOk(nomeFormato, 'application/rss+xml', { type: 'string' }, null);
  return [percorso, operazione({
    id: idOperazione,
    tag: 'Feed',
    sommario: `${nomeFormato}: ${perCategoria ? 'articoli di una categoria' : risorsa}`,
    descrizione: `Ultimi ${ELEMENTI_FEED} elementi in ${nomeFormato}. ${PARAGRAFI_FEED.join(' ')}`,
    parametri: perCategoria ? [rifParametro('categoriaFeed')] : [],
    ok,
    errori: ERRORI_FEED,
  })];
}

function percorsi(): Schema {
  const voci: [string, Schema][] = [
    ['/', operazione({
      id: 'indice',
      tag: 'Indice',
      sommario: 'Indice dell\'API',
      descrizione: 'Versione, documentazione, limiti, risorse con i loro feed e sezioni. Nessun accesso al database. ' +
        'La query string è ignorata.',
      parametri: [],
      ok: rispostaOk('Indice.', 'application/json', rif('Indice'), 'Indice'),
      errori: ['304', '429', '500'],
    })],
    ['/openapi.json', operazione({
      id: 'openapi',
      tag: 'Indice',
      sommario: 'Questo documento',
      descrizione: 'Descrizione OpenAPI 3.1 (application/vnd.oai.openapi+json;version=3.1). La query string è ignorata.',
      parametri: [],
      ok: rispostaOk('Documento OpenAPI.', 'application/vnd.oai.openapi+json;version=3.1', { type: 'object' }, null),
      errori: ['304', '429', '500'],
    })],
  ];
  const [articoli, ...opportunita] = DESCRITTORI;
  voci.push(...percorsiRisorsa(articoli));
  voci.push(['/categories', operazione({
    id: 'elencoCategorie',
    tag: 'Categorie',
    sommario: 'Categorie degli articoli',
    descrizione: 'Categorie valide con le secondarie, nell\'ordine del sito. Le sezioni (interpelli, selezione ' +
      'del personale, bandi) non sono categorie: sono nell\'indice. ' + NESSUN_PARAMETRO,
    parametri: [],
    ok: rispostaOk('Tutte le categorie.', 'application/json', rif('ElencoCategorie'), 'ElencoCategorie'),
    errori: ['304', '400', '429', '500', '503'],
  })]);
  for (const d of opportunita) voci.push(...percorsiRisorsa(d));
  for (const risorsa of RISORSE) {
    voci.push(percorsoFeed(risorsa, 'json', false), percorsoFeed(risorsa, 'xml', false));
  }
  voci.push(percorsoFeed('articles', 'json', true), percorsoFeed('articles', 'xml', true));
  return Object.fromEntries(voci);
}

// ---------------------------------------------------------------------------
// Documento
// ---------------------------------------------------------------------------

/** Documento OpenAPI 3.1 completo. Ogni chiamata costruisce un oggetto nuovo. */
export function documentoOpenApi(): Record<string, unknown> {
  return {
    openapi: '3.1.0',
    info: {
      title: TITOLO_API,
      version: VERSIONE_OPENAPI,
      summary: 'Articoli, categorie, interpelli, concorsi e bandi di EduNews24, in sola lettura.',
      description: descrizioneOpenApi(),
      termsOfService: URL_TERMINI,
      contact: { url: URL_DOCUMENTAZIONE },
      license: { name: 'Uso soggetto ai termini EduNews24', url: URL_TERMINI },
    },
    servers: [{ url: BASE_API }],
    security: [],
    tags: [
      { name: 'Indice', description: 'Punto di ingresso e descrizione formale.' },
      { name: 'Articoli', description: 'Articoli pubblicati.' },
      { name: 'Categorie', description: 'Categorie degli articoli.' },
      { name: 'Interpelli', description: 'Interpelli delle scuole.' },
      { name: 'Selezione personale', description: 'Concorsi e selezioni pubbliche.' },
      { name: 'Bandi', description: 'Bandi e finanziamenti pubblici.' },
      { name: 'Feed', description: 'JSON Feed 1.1 e RSS 2.0.' },
    ],
    externalDocs: { description: 'Documentazione e termini d\'uso', url: URL_DOCUMENTAZIONE },
    paths: percorsi(),
    components: {
      schemas: schemi(),
      parameters: parametri(),
      headers: headers(),
      responses: risposte(),
      examples: esempi(),
    },
  };
}
