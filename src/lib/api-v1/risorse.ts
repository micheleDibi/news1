/**
 * Orchestrazione delle risorse /api/v1 (pura: l'accesso ai dati e' iniettato).
 *
 * Ogni rotta ha un descrittore:
 * - `prepara` valida path e query SENZA toccare il DB (400/404 immediati) e produce
 *   la chiave canonica per la cache;
 * - `produci` legge i dati tramite la FonteDati iniettata e serializza la risposta.
 * Il gestore (gestore.ts) mette insieme limitatore, cache, semaforo ed errori HTTP.
 */
import {
  BASE_API, SITO, TESTO_ATTRIBUZIONE, URL_CATALOGO, URL_OPENAPI, URL_TERMINI, VERSIONE_API,
} from './costanti';
import { ErroreDati, ProblemaApi } from './errori';
import { etagDebole, TIPO_JSON, TIPO_JSON_FEED, TIPO_OPENAPI, TIPO_RSS, type ProfiloCache } from './http';
import {
  erroreCategoria, filtriMeta, queryCanonica, validaIdPercorso, validaQueryAssente, validaQueryElenco,
  type FiltriElenco,
} from './parametri';
import { codificaCursore, decodificaCursore, idMassimo, type PosizioneCursore } from './cursore';
import { COLONNA_ORDINAMENTO, pianoQuery, type ContestoPiano, type ModoQuery } from './filtri';
import { istantePublishedAt } from './tempo';
import { urlApi } from './url';
import { mappaArticolo } from './mappa-articoli';
import { mappaCategorie } from './mappa-categorie';
import { mappaBando, mappaInterpello, mappaSelezione } from './mappa-opportunita';
import { analizzaPercorsoFeed, metadatiFeed, serializzaJsonFeed, serializzaRss } from './feed';
import { datiIndice } from './indice';
import { documentoOpenApi } from './openapi';
import { regionePerSlug, regionePerValore } from '../regioni';
import type {
  ArticoloDto, FonteDati, OpportunitaDto, PianoQuery, RiferimentoCategorie, RiferimentoProfili, Risorsa,
  RigaArticolo, RigaBando, RigaInterpello, RigaSelezione,
} from './contratto';

// ---------------------------------------------------------------------------
// Contratti con il gestore e con il cablaggio
// ---------------------------------------------------------------------------

export interface RiferimentoInCache<T> {
  ottieni(segnale: AbortSignal): Promise<T>;
  seCaldo(): T | null;
}

export interface DipendenzeRisorse {
  fonte: FonteDati;
  categorie: RiferimentoInCache<RiferimentoCategorie>;
  profili: RiferimentoInCache<RiferimentoProfili>;
  /** valoriDb della faccetta regione del corpus, se gia' caldo (mai atteso); [] altrimenti. */
  valoriRegioneCorpus(sezione: 'interpelli' | 'selezione-personale', slugRegione: string): readonly string[];
  /** Limite dichiarato nell'indice. */
  limiteDichiarato: { requests: number; window_seconds: number };
  registra(evento: string, dettaglio?: string): void;
}

export interface Esecuzione {
  adessoMs: number;
  /** YYYY-MM-DD di Roma, fissato una volta per richiesta. */
  oggi: string;
  segnale: AbortSignal;
}

export interface RisultatoRisorsa {
  corpo: string;
  contentType: string;
  profilo: ProfiloCache;
  etag: string;
  /** Valori dell'header Link specifici della risposta (next, canonical, api-catalog). */
  link: readonly string[];
}

export interface Preparazione {
  /** Chiave canonica per la cache in memoria (senza la data: la aggiunge il gestore se serve). */
  chiave: string;
  /** La risposta contiene `status` calcolato su "oggi". */
  dipendeDaOggi: boolean;
  /** Presenza di un cursore: un 22007/8/9 del DB diventa 400 invalid-cursor. */
  conCursore: boolean;
  /** Prima pagina senza cursore (per invalid-cursor). */
  primo: string | null;
  produci(dipendenze: DipendenzeRisorse, esecuzione: Esecuzione): Promise<RisultatoRisorsa>;
}

export interface DescrittoreRotta {
  nome: string;
  /** Profilo di cache della risposta riuscita (decide anche la politica della cache in memoria). */
  profilo: ProfiloCache;
  /** Valida senza toccare il DB. Lancia ProblemaApi per 400/404. */
  prepara(url: URL, parametri: Readonly<Record<string, string | undefined>>): Preparazione;
}

// ---------------------------------------------------------------------------
// Comuni
// ---------------------------------------------------------------------------

const PERCORSO: ReadonlyMap<Risorsa, string> = new Map<Risorsa, string>([
  ['articles', '/articles'],
  ['interpelli', '/interpelli'],
  ['selezione-personale', '/selezione-personale'],
  ['bandi', '/bandi'],
]);

const ORDINAMENTO_PUBBLICO = '-published_at,-id';
const DETTAGLIO_CURSORE =
  'Il cursore non e\' valido per questa richiesta (formato, filtri o versione). Ricomincia dalla prima pagina.';

const ATTRIBUZIONE = { text: TESTO_ATTRIBUZIONE, url: SITO };

function metaBase(resource: string): { api_version: string; resource: string } {
  return { api_version: VERSIONE_API, resource };
}

function risultatoJson(dati: unknown, profilo: ProfiloCache, link: readonly string[] = []): RisultatoRisorsa {
  const corpo = JSON.stringify(dati);
  return { corpo, contentType: TIPO_JSON, profilo, etag: etagDebole(corpo), link };
}

function dipendeDaOggi(risorsa: Risorsa): boolean {
  return risorsa === 'selezione-personale' || risorsa === 'bandi';
}

function lunghezzaQuery(url: URL): number {
  return url.search.length > 0 ? url.search.length - 1 : 0;
}

/** Valori DB ammessi per la regione: varianti del registro piu' quelle viste nel corpus, solo se riconosciute. */
function valoriRegione(
  dipendenze: DipendenzeRisorse,
  sezione: 'interpelli' | 'selezione-personale',
  slug: string,
): string[] {
  const regione = regionePerSlug(slug);
  if (!regione) return [];
  const candidati = [...regione.varianti, ...dipendenze.valoriRegioneCorpus(sezione, slug)];
  const ammessi = new Set<string>();
  for (const v of candidati) {
    if (v.length >= 1 && v.length <= 100 && !/[\u0000-\u001f\u007f]/.test(v) && regionePerValore(v)?.slug === slug) {
      ammessi.add(v);
    }
  }
  return [...ammessi];
}

function contestoPiano(extra: Partial<ContestoPiano> & { modo: ModoQuery; oggi: string }): ContestoPiano {
  return {
    filtri: null, slugCategorieValide: [], categoria: null, valoriRegione: null, dopo: null, id: null, righe: 1,
    ...extra,
  };
}

/** Valore grezzo della colonna di ordinamento e id, per il cursore. */
function posizioneDi(risorsa: Risorsa, riga: RigaArticolo | RigaInterpello | RigaSelezione | RigaBando): PosizioneCursore {
  const colonna = COLONNA_ORDINAMENTO.get(risorsa) as string;
  const grezzo = (riga as unknown as Record<string, unknown>)[colonna];
  const id = riga.id;
  if (typeof grezzo !== 'string' || typeof id !== 'number') {
    throw new ErroreDati('programmazione', null, 'riga senza chiave di ordinamento');
  }
  return { grezzo, id };
}

interface Mappatura {
  dati: Array<ArticoloDto | OpportunitaDto>;
}

interface RiferimentiArticoli {
  categorie: RiferimentoCategorie;
  profili: RiferimentoProfili;
}

async function riferimentiArticoli(dipendenze: DipendenzeRisorse, segnale: AbortSignal): Promise<RiferimentiArticoli> {
  const [categorie, profili] = await Promise.all([
    dipendenze.categorie.ottieni(segnale),
    dipendenze.profili.ottieni(segnale),
  ]);
  return { categorie, profili };
}

/** Legge le righe del piano per la risorsa e le mappa; le righe scartate finiscono nel log. */
async function leggiEMappa(
  risorsa: Risorsa,
  piano: PianoQuery,
  dipendenze: DipendenzeRisorse,
  esecuzione: Esecuzione,
  riferimenti: RiferimentiArticoli | null,
  accetta: (riga: RigaArticolo) => boolean = () => true,
): Promise<{ righe: Array<RigaArticolo | RigaInterpello | RigaSelezione | RigaBando>; mappa: (limite: number) => Mappatura }> {
  const { fonte } = dipendenze;
  let righe: Array<RigaArticolo | RigaInterpello | RigaSelezione | RigaBando>;
  switch (risorsa) {
    case 'articles': righe = await fonte.leggi(piano as PianoQuery<'articolo'>, esecuzione.segnale); break;
    case 'interpelli': righe = await fonte.leggi(piano as PianoQuery<'interpello'>, esecuzione.segnale); break;
    case 'selezione-personale': righe = await fonte.leggi(piano as PianoQuery<'selezione'>, esecuzione.segnale); break;
    case 'bandi': righe = await fonte.leggi(piano as PianoQuery<'bando'>, esecuzione.segnale); break;
  }
  const mappa = (limite: number): Mappatura => {
    const dati: Array<ArticoloDto | OpportunitaDto> = [];
    for (const riga of righe.slice(0, limite)) {
      let dto: ArticoloDto | OpportunitaDto | null;
      switch (risorsa) {
        case 'articles': {
          const r = riga as RigaArticolo;
          if (!accetta(r)) continue;
          dto = riferimenti ? mappaArticolo(r, riferimenti) : null;
          break;
        }
        case 'interpelli': dto = mappaInterpello(riga as RigaInterpello); break;
        case 'selezione-personale': dto = mappaSelezione(riga as RigaSelezione, esecuzione.oggi); break;
        case 'bandi': dto = mappaBando(riga as RigaBando, esecuzione.oggi); break;
      }
      if (dto) dati.push(dto);
      else dipendenze.registra('riga-scartata', `${risorsa} id=${String(riga.id)}`);
    }
    return { dati };
  };
  return { righe, mappa };
}

// ---------------------------------------------------------------------------
// Elenchi
// ---------------------------------------------------------------------------

function descrittoreElenco(risorsa: Risorsa): DescrittoreRotta {
  const percorso = PERCORSO.get(risorsa) as string;
  return {
    nome: `elenco:${risorsa}`,
    profilo: 'elenco',
    prepara(url) {
      const esito = validaQueryElenco(risorsa, url.searchParams, lunghezzaQuery(url));
      if (!esito.ok) throw esito.problema;
      const filtri = esito.filtri;
      const primo = urlApi(percorso, queryCanonica(risorsa, filtri, { conLimite: true, conCursore: false }));
      let dopo: PosizioneCursore | null = null;
      if (filtri.cursor !== null) {
        dopo = decodificaCursore(risorsa, filtri, filtri.cursor);
        if (!dopo) throw new ProblemaApi('invalid-cursor', DETTAGLIO_CURSORE, { primo });
      }
      const canonica = queryCanonica(risorsa, filtri, { conLimite: true, conCursore: true }).toString();
      return {
        chiave: `${percorso}?${canonica}`,
        dipendeDaOggi: dipendeDaOggi(risorsa),
        conCursore: filtri.cursor !== null,
        primo,
        produci: (dipendenze, esecuzione) => produciElenco(risorsa, filtri, dopo, primo, dipendenze, esecuzione),
      };
    },
  };
}

async function produciElenco(
  risorsa: Risorsa,
  filtri: FiltriElenco,
  dopo: PosizioneCursore | null,
  primo: string,
  dipendenze: DipendenzeRisorse,
  esecuzione: Esecuzione,
): Promise<RisultatoRisorsa> {
  const percorso = PERCORSO.get(risorsa) as string;
  let riferimenti: RiferimentiArticoli | null = null;
  let valori: string[] | null = null;

  if (risorsa === 'articles') {
    riferimenti = await riferimentiArticoli(dipendenze, esecuzione.segnale);
    if (filtri.category !== null && !riferimenti.categorie.perSlug.has(filtri.category)) {
      throw erroreCategoria([...riferimenti.categorie.perSlug.keys()]);
    }
  }
  if ((risorsa === 'interpelli' || risorsa === 'selezione-personale') && filtri.region !== null) {
    valori = valoriRegione(dipendenze, risorsa, filtri.region);
  }

  const piano = pianoQuery(risorsa, contestoPiano({
    modo: 'elenco',
    oggi: esecuzione.oggi,
    filtri,
    slugCategorieValide: riferimenti ? [...riferimenti.categorie.perSlug.keys()] : [],
    categoria: filtri.category,
    valoriRegione: valori,
    dopo,
    righe: filtri.limit + 1,
  }));

  // Articoli: il DB ha filtrato un superinsieme (published_at senza fuso); qui il taglio esatto.
  const accetta = (riga: RigaArticolo): boolean => {
    if (filtri.since === null && filtri.until === null) return true;
    const istante = istantePublishedAt(riga.published_at);
    if (istante === null) return false;
    if (filtri.since !== null && istante < filtri.since) return false;
    if (filtri.until !== null && istante >= filtri.until) return false;
    return true;
  };

  const { righe, mappa } = await leggiEMappa(risorsa, piano, dipendenze, esecuzione, riferimenti, accetta);
  const { dati } = mappa(filtri.limit);

  // Il cursore successivo parte dall'ultima riga LETTA fra le prime `limit` (anche se
  // scartata dal post-filtro o dal mapper): nessun buco, nessun duplicato.
  let next: string | null = null;
  if (righe.length > filtri.limit) {
    const ultima = righe[filtri.limit - 1];
    const posizione = posizioneDi(risorsa, ultima);
    const cursore = codificaCursore(risorsa, filtri, posizione.grezzo, posizione.id);
    next = urlApi(percorso, queryCanonica(risorsa, { ...filtri, cursor: cursore }, { conLimite: true, conCursore: true }));
  }

  const corpo = {
    data: dati,
    meta: {
      ...metaBase(risorsa),
      count: dati.length,
      limit: filtri.limit,
      has_more: next !== null,
      sort: ORDINAMENTO_PUBBLICO,
      filters: Object.fromEntries(filtriMeta(risorsa, filtri)),
      attribution: ATTRIBUZIONE,
      terms: URL_TERMINI,
    },
    links: {
      self: urlApi(percorso, queryCanonica(risorsa, filtri, { conLimite: true, conCursore: true })),
      first: primo,
      next,
      describedby: URL_OPENAPI,
    },
  };
  return risultatoJson(corpo, 'elenco', next ? [`<${next}>; rel="next"`] : []);
}

// ---------------------------------------------------------------------------
// Dettagli
// ---------------------------------------------------------------------------

function descrittoreDettaglio(risorsa: Risorsa): DescrittoreRotta {
  const percorso = PERCORSO.get(risorsa) as string;
  return {
    nome: `dettaglio:${risorsa}`,
    profilo: 'dettaglio',
    prepara(url, parametri) {
      const problema = validaQueryAssente(url.searchParams, lunghezzaQuery(url));
      if (problema) throw problema;
      const id = validaIdPercorso(parametri.id);
      if (id === null) {
        throw new ProblemaApi('invalid-parameter', 'L\'identificativo deve essere un intero positivo.', {
          errori: [{ parameter: 'id', detail: 'Deve essere un intero positivo.' }],
        });
      }
      // Ben formato ma oltre il tipo della colonna (bando.id e' int4): inesistente, senza query.
      if (id > idMassimo(risorsa)) throw nonTrovato();
      return {
        chiave: `${percorso}/${id}`,
        dipendeDaOggi: dipendeDaOggi(risorsa),
        conCursore: false,
        primo: null,
        produci: (dipendenze, esecuzione) => produciDettaglio(risorsa, id, dipendenze, esecuzione),
      };
    },
  };
}

function nonTrovato(): ProblemaApi {
  return new ProblemaApi('not-found', 'Nessun elemento pubblicato con questo identificativo.');
}

async function produciDettaglio(
  risorsa: Risorsa,
  id: number,
  dipendenze: DipendenzeRisorse,
  esecuzione: Esecuzione,
): Promise<RisultatoRisorsa> {
  const percorso = PERCORSO.get(risorsa) as string;
  const riferimenti = risorsa === 'articles' ? await riferimentiArticoli(dipendenze, esecuzione.segnale) : null;
  const piano = pianoQuery(risorsa, contestoPiano({
    modo: 'dettaglio',
    oggi: esecuzione.oggi,
    id,
    slugCategorieValide: riferimenti ? [...riferimenti.categorie.perSlug.keys()] : [],
  }));
  const { righe, mappa } = await leggiEMappa(risorsa, piano, dipendenze, esecuzione, riferimenti);
  if (righe.length === 0) throw nonTrovato();
  const dto = mappa(1).dati[0];
  if (!dto) throw nonTrovato();
  const corpo = {
    data: dto,
    meta: { ...metaBase(risorsa), attribution: ATTRIBUZIONE, terms: URL_TERMINI },
    links: {
      self: urlApi(`${percorso}/${id}`),
      collection: urlApi(percorso),
      html: dto.url,
      describedby: URL_OPENAPI,
    },
  };
  return risultatoJson(corpo, 'dettaglio', [`<${dto.url}>; rel="canonical"`]);
}

// ---------------------------------------------------------------------------
// Categorie, indice, OpenAPI
// ---------------------------------------------------------------------------

export const CATEGORIE: DescrittoreRotta = {
  nome: 'categorie',
  profilo: 'statico',
  prepara(url) {
    const problema = validaQueryAssente(url.searchParams, lunghezzaQuery(url));
    if (problema) throw problema;
    return {
      chiave: '/categories',
      dipendeDaOggi: false,
      conCursore: false,
      primo: null,
      async produci(dipendenze, esecuzione) {
        const riferimento = await dipendenze.categorie.ottieni(esecuzione.segnale);
        const dati = mappaCategorie(riferimento);
        return risultatoJson({
          data: dati,
          meta: { ...metaBase('categories'), count: dati.length, attribution: ATTRIBUZIONE, terms: URL_TERMINI },
          links: { self: urlApi('/categories'), describedby: URL_OPENAPI },
        }, 'statico');
      },
    };
  },
};

/** Indice: i parametri sono ignorati (e fuori dalla chiave di cache). */
export const INDICE: DescrittoreRotta = {
  nome: 'indice',
  profilo: 'statico',
  prepara() {
    return {
      chiave: '/',
      dipendeDaOggi: false,
      conCursore: false,
      primo: null,
      async produci(dipendenze) {
        return risultatoJson({
          data: datiIndice(dipendenze.limiteDichiarato),
          meta: { ...metaBase('index'), attribution: ATTRIBUZIONE, terms: URL_TERMINI },
          links: { self: BASE_API, describedby: URL_OPENAPI },
        }, 'statico', [`<${URL_CATALOGO}>; rel="api-catalog"`]);
      },
    };
  },
};

export const OPENAPI: DescrittoreRotta = {
  nome: 'openapi',
  profilo: 'openapi',
  prepara() {
    return {
      chiave: '/openapi.json',
      dipendeDaOggi: false,
      conCursore: false,
      primo: null,
      async produci() {
        const corpo = JSON.stringify(documentoOpenApi());
        return { corpo, contentType: TIPO_OPENAPI, profilo: 'openapi', etag: etagDebole(corpo), link: [] };
      },
    };
  },
};

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export const FEED: DescrittoreRotta = {
  nome: 'feed',
  profilo: 'feed',
  prepara(_url, parametri) {
    const richiesta = analizzaPercorsoFeed(parametri.percorso);
    if (!richiesta) throw new ProblemaApi('not-found', 'Feed inesistente.');
    const { risorsa } = richiesta;
    return {
      chiave: `/feeds/${parametri.percorso ?? ''}`,
      dipendeDaOggi: dipendeDaOggi(risorsa),
      conCursore: false,
      primo: null,
      async produci(dipendenze, esecuzione) {
        let riferimenti: RiferimentiArticoli | null = null;
        let nomeCategoria: string | null = null;
        if (risorsa === 'articles') {
          riferimenti = await riferimentiArticoli(dipendenze, esecuzione.segnale);
          if (richiesta.categoria !== null) {
            const categoria = riferimenti.categorie.perSlug.get(richiesta.categoria);
            if (!categoria) throw new ProblemaApi('not-found', 'Feed inesistente.');
            nomeCategoria = categoria.name;
          }
        }
        const piano = pianoQuery(risorsa, contestoPiano({
          modo: 'feed',
          oggi: esecuzione.oggi,
          categoria: richiesta.categoria,
          slugCategorieValide: riferimenti ? [...riferimenti.categorie.perSlug.keys()] : [],
        }));
        const { mappa } = await leggiEMappa(risorsa, piano, dipendenze, esecuzione, riferimenti);
        const { dati } = mappa(Number.MAX_SAFE_INTEGER);
        const meta = metadatiFeed(richiesta, nomeCategoria);
        const corpo = richiesta.formato === 'json' ? serializzaJsonFeed(meta, dati) : serializzaRss(meta, dati);
        return {
          corpo,
          contentType: richiesta.formato === 'json' ? TIPO_JSON_FEED : TIPO_RSS,
          profilo: 'feed',
          etag: etagDebole(corpo),
          link: [],
        };
      },
    };
  },
};

// ---------------------------------------------------------------------------
// Percorsi sconosciuti
// ---------------------------------------------------------------------------

export const NON_TROVATO: DescrittoreRotta = {
  nome: 'non-trovato',
  profilo: 'errore',
  prepara() {
    throw new ProblemaApi('not-found', 'Percorso sconosciuto: vedi la documentazione dell\'API.');
  },
};

export const ELENCO_ARTICOLI = descrittoreElenco('articles');
export const DETTAGLIO_ARTICOLO = descrittoreDettaglio('articles');
export const ELENCO_INTERPELLI = descrittoreElenco('interpelli');
export const DETTAGLIO_INTERPELLO = descrittoreDettaglio('interpelli');
export const ELENCO_SELEZIONE = descrittoreElenco('selezione-personale');
export const DETTAGLIO_SELEZIONE = descrittoreDettaglio('selezione-personale');
export const ELENCO_BANDI = descrittoreElenco('bandi');
export const DETTAGLIO_BANDO = descrittoreDettaglio('bandi');
