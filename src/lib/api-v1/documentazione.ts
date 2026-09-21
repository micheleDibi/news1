/**
 * Contenuti della pagina umana /sviluppatori/api come dati puri: la pagina .astro
 * si limita a iterare le sezioni e a rendere i blocchi. Tutta la logica sta qui,
 * dove tsc e i test la vedono (i .astro non sono controllati dai tipi).
 *
 * Le ancore `error-<code>` coincidono con il membro `type` dei problem+json e
 * `termini` con URL_TERMINI: non vanno rinominate.
 */
import {
  BASE_API, CONTENT_SIGNAL, ELEMENTI_FEED, URL_OPENAPI, URL_TERMINI,
} from './costanti';
import { CODICI_ERRORE, DEFINIZIONE_ERRORE } from './errori';
import { metadatiFeed, serializzaJsonFeed, serializzaRss } from './feed';
import { ORDINE_PARAMETRI, SPEC_PARAMETRI } from './parametri';
import {
  CHANGELOG, CODICE_SINCRONIZZAZIONE, GUIDA_SINCRONIZZAZIONE, NOTA_TERMINI_CHIUSURA, NOTA_TERMINI_INTRODUZIONE,
  NOTA_TERMINI_VOCI, PARAGRAFI_CACHE, PARAGRAFI_CORS, PARAGRAFI_DATE, PARAGRAFI_ERRORI, PARAGRAFI_EVOLUZIONE,
  PARAGRAFI_FEED, PARAGRAFI_FORMATO, PARAGRAFI_INTRODUZIONE, PARAGRAFI_LIMITI, PARAGRAFI_PAGINAZIONE,
  PARAGRAFI_REGIONI, PARAGRAFI_REGOLE_FILTRI, PARAGRAFI_TESTO, PARAGRAFO_DEDUPLICA, PARAGRAFO_FUORI_CONTRATTO,
  PARAGRAFO_STATUS, PROFILI_CACHE, REGOLE_PARAMETRI, RICHIESTA_ERRORE_PARAMETRI, RISPOSTE_FUORI_CONTRATTO,
  TESTI_ERRORE, USER_AGENT_ESEMPIO, esempioArticolo, esempioErroreLimite, esempioErroreParametri, esempioSelezione,
} from './testi-doc';
import type { Risorsa } from './contratto';

export type Blocco =
  | { tipo: 'paragrafo'; testo: string }
  | { tipo: 'elenco'; voci: string[] }
  | { tipo: 'codice'; linguaggio: string; testo: string }
  | { tipo: 'tabella'; intestazioni: string[]; righe: string[][] };

export interface SezioneDoc {
  id: string;
  titolo: string;
  blocchi: Blocco[];
}

const RISORSE: readonly Risorsa[] = ['articles', 'interpelli', 'selezione-personale', 'bandi'];

const paragrafo = (testo: string): Blocco => ({ tipo: 'paragrafo', testo });
const paragrafiDi = (testi: readonly string[]): Blocco[] => testi.map(paragrafo);
const elenco = (voci: readonly string[]): Blocco => ({ tipo: 'elenco', voci: [...voci] });
const codice = (linguaggio: string, testo: string): Blocco => ({ tipo: 'codice', linguaggio, testo });
const json = (valore: unknown): Blocco => codice('json', JSON.stringify(valore, null, 2));

/** Colonna "Parametri" delle risorse senza parametri: query rifiutata (400) o ignorata. */
const QUERY_RIFIUTATA = '— (400 con parametri)';
const QUERY_IGNORATA = '— (query ignorata)';

function parametriDi(risorsa: Risorsa): string {
  return (SPEC_PARAMETRI.get(risorsa) ?? []).join(', ');
}

// ---------------------------------------------------------------------------
// Sezioni
// ---------------------------------------------------------------------------

function introduzione(): SezioneDoc {
  return {
    id: 'introduzione',
    titolo: 'Introduzione',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_INTRODUZIONE),
      elenco([
        `Base URL: ${BASE_API}`,
        'Accesso libero, senza chiave, in sola lettura (GET, HEAD, OPTIONS).',
        'Formati: JSON (application/json), JSON Feed 1.1 e RSS 2.0.',
        `Descrizione OpenAPI 3.1: ${URL_OPENAPI}`,
        `Termini d'uso: ${URL_TERMINI}`,
      ]),
    ],
  };
}

function risorse(): SezioneDoc {
  const righe: string[][] = [
    ['/api/v1', 'Indice: versione, documentazione, limiti, risorse, feed e sezioni.', QUERY_IGNORATA],
    ['/api/v1/openapi.json', 'Descrizione OpenAPI 3.1.', QUERY_IGNORATA],
    ['/api/v1/articles', 'Articoli pubblicati, dal più recente.', parametriDi('articles')],
    ['/api/v1/articles/{id}', 'Un articolo.', QUERY_RIFIUTATA],
    ['/api/v1/categories', 'Categorie degli articoli con le secondarie.', QUERY_RIFIUTATA],
    ['/api/v1/interpelli', 'Interpelli delle scuole.', parametriDi('interpelli')],
    ['/api/v1/interpelli/{id}', 'Un interpello.', QUERY_RIFIUTATA],
    ['/api/v1/selezione-personale', 'Concorsi e selezioni pubbliche.', parametriDi('selezione-personale')],
    ['/api/v1/selezione-personale/{id}', 'Un concorso o una selezione.', QUERY_RIFIUTATA],
    ['/api/v1/bandi', 'Bandi e finanziamenti pubblici.', parametriDi('bandi')],
    ['/api/v1/bandi/{id}', 'Un bando.', QUERY_RIFIUTATA],
    ['/api/v1/feeds/{risorsa}.json · .xml', `Ultimi ${ELEMENTI_FEED} elementi di articles, interpelli, ` +
      'selezione-personale o bandi, in JSON Feed 1.1 o RSS 2.0.', QUERY_IGNORATA],
    ['/api/v1/feeds/articles/{categoria}.json · .xml', `Ultimi ${ELEMENTI_FEED} articoli di una categoria.`,
      QUERY_IGNORATA],
  ];
  return {
    id: 'risorse',
    titolo: 'Risorse ed endpoint',
    blocchi: [
      { tipo: 'tabella', intestazioni: ['Path', 'Contenuto', 'Parametri'], righe },
      paragrafo('Qualunque altro path sotto /api/v1 risponde 404 in JSON; un metodo diverso da GET, HEAD e ' +
        'OPTIONS risponde 405. Dettagli e /categories rispondono 400 unknown-parameter a qualunque parametro; ' +
        'indice, openapi.json e feed ignorano la query.'),
    ],
  };
}

function formato(): SezioneDoc {
  return {
    id: 'formato',
    titolo: 'Formato delle risposte',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_FORMATO),
      paragrafo('Esempio: GET /api/v1/selezione-personale/23258 (campo data, testi illustrativi).'),
      json(esempioSelezione()),
    ],
  };
}

function esempiCurl(): SezioneDoc {
  const ua = `-A '${USER_AGENT_ESEMPIO}'`;
  return {
    id: 'esempi',
    titolo: 'Esempi con curl',
    blocchi: [
      paragrafo('Ultimi 5 articoli della categoria Scuola:'),
      codice('bash', `curl -sS ${ua} '${BASE_API}/articles?category=scuola&limit=5'`),
      paragrafo('Concorsi nelle Marche aggiornati dal 20 settembre 2026:'),
      codice('bash', `curl -sS ${ua} '${BASE_API}/selezione-personale?region=marche&updated_since=2026-09-20'`),
      paragrafo('Richiesta condizionale: con l\'ETag ricevuto, la risposta è 304 se nulla è cambiato.'),
      codice('bash', `curl -sS -i ${ua} -H 'If-None-Match: W/"Xb1q0m4Tq3o2Zr8kPp7yWc5dLh2"' '${BASE_API}/categories'`),
      paragrafo('Feed RSS dei bandi:'),
      codice('bash', `curl -sS ${ua} '${BASE_API}/feeds/bandi.xml'`),
      paragrafo('Risposta di GET /api/v1/articles?category=scuola&limit=1 (campo data, testi illustrativi):'),
      json([esempioArticolo()]),
    ],
  };
}

function paginazione(): SezioneDoc {
  return {
    id: 'paginazione',
    titolo: 'Paginazione e sincronizzazione',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_PAGINAZIONE),
      paragrafo('Guida alla sincronizzazione:'),
      elenco(GUIDA_SINCRONIZZAZIONE.map((passo) => `${passo.risorse}: ${passo.testo}`)),
      paragrafo(PARAGRAFO_DEDUPLICA),
      codice('js', CODICE_SINCRONIZZAZIONE),
    ],
  };
}

function filtri(): SezioneDoc {
  const intestazioni = ['Parametro', ...RISORSE, 'Regole'];
  const righe = ORDINE_PARAMETRI.map((nome) => [
    nome,
    ...RISORSE.map((r) => ((SPEC_PARAMETRI.get(r) ?? []).includes(nome) ? 'sì' : '—')),
    REGOLE_PARAMETRI.get(nome) ?? '',
  ]);
  return {
    id: 'filtri',
    titolo: 'Filtri',
    blocchi: [
      { tipo: 'tabella', intestazioni, righe },
      ...paragrafiDi(PARAGRAFI_REGOLE_FILTRI),
      ...paragrafiDi(PARAGRAFI_REGIONI),
    ],
  };
}

function sezioneDate(): SezioneDoc {
  return { id: 'date', titolo: 'Date e istanti', blocchi: paragrafiDi(PARAGRAFI_DATE) };
}

function testoEUrl(): SezioneDoc {
  return {
    id: 'testo',
    titolo: 'Testo, URL e stato',
    blocchi: [...paragrafiDi(PARAGRAFI_TESTO), paragrafo(PARAGRAFO_STATUS)],
  };
}

function cache(): SezioneDoc {
  return {
    id: 'cache',
    titolo: 'Cache ed ETag',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_CACHE),
      {
        tipo: 'tabella',
        intestazioni: ['Risposta', 'Cache-Control'],
        righe: PROFILI_CACHE.map(([risposta, valore]) => [risposta, valore]),
      },
    ],
  };
}

function limiti(): SezioneDoc {
  return {
    id: 'limiti',
    titolo: 'Limiti e risposte fuori contratto',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_LIMITI),
      paragrafo('Risposte che possono arrivare prima dell\'API e non seguono il contratto:'),
      elenco(RISPOSTE_FUORI_CONTRATTO),
      paragrafo(PARAGRAFO_FUORI_CONTRATTO),
    ],
  };
}

function cors(): SezioneDoc {
  return { id: 'cors', titolo: 'CORS', blocchi: paragrafiDi(PARAGRAFI_CORS) };
}

function feed(): SezioneDoc {
  const articolo = esempioArticolo();
  const selezione = esempioSelezione();
  const metaArticoli = metadatiFeed({ risorsa: 'articles', categoria: null, formato: 'json' }, null);
  const metaSelezione = metadatiFeed({ risorsa: 'selezione-personale', categoria: null, formato: 'xml' }, null);
  return {
    id: 'feed',
    titolo: 'Feed ed estensione _edunews24',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_FEED),
      elenco([
        ...RISORSE.map((r) => `${BASE_API}/feeds/${r}.json · .xml`),
        `${BASE_API}/feeds/articles/{categoria}.json · .xml`,
      ]),
      paragrafo(`Le preferenze d'uso dichiarate valgono anche per i feed: ${CONTENT_SIGNAL}.`),
      paragrafo('Esempio di JSON Feed con una voce articolo (testi illustrativi):'),
      codice('json', JSON.stringify(JSON.parse(serializzaJsonFeed(metaArticoli, [articolo])), null, 2)),
      paragrafo('Esempio di RSS con una voce della selezione del personale (testi illustrativi):'),
      codice('xml', serializzaRss(metaSelezione, [selezione]).trimEnd()),
    ],
  };
}

function errori(): SezioneDoc[] {
  const introduzioneErrori: SezioneDoc = {
    id: 'errori',
    titolo: 'Errori',
    blocchi: [
      ...paragrafiDi(PARAGRAFI_ERRORI),
      {
        tipo: 'tabella',
        intestazioni: ['Status', 'code', 'Titolo'],
        righe: CODICI_ERRORE.map((c) => {
          const definizione = DEFINIZIONE_ERRORE.get(c);
          return [String(definizione?.status ?? ''), c, definizione?.titolo ?? ''];
        }),
      },
    ],
  };
  const perCodice = CODICI_ERRORE.map((c): SezioneDoc => {
    const definizione = DEFINIZIONE_ERRORE.get(c);
    const testo = TESTI_ERRORE.get(c);
    const blocchi: Blocco[] = [
      paragrafo(`Status HTTP ${definizione?.status ?? ''}. ${testo?.quando ?? ''}`),
      paragrafo(`Cosa fare: ${testo?.cosaFare ?? ''}`),
      paragrafo(`Cache-Control: ${testo?.cacheControl ?? ''}`),
    ];
    if (c === 'invalid-parameter') {
      blocchi.push(paragrafo(`Risposta a GET /api/v1${RICHIESTA_ERRORE_PARAMETRI}:`), json(esempioErroreParametri()));
    }
    if (c === 'rate-limited') {
      blocchi.push(paragrafo('Risposta alla prima richiesta oltre il limite:'), json(esempioErroreLimite()));
    }
    return { id: `error-${c}`, titolo: `${c} · ${definizione?.titolo ?? ''}`, blocchi };
  });
  return [introduzioneErrori, ...perCodice];
}

function evoluzione(): SezioneDoc {
  return { id: 'evoluzione', titolo: 'Versioni ed evoluzione', blocchi: paragrafiDi(PARAGRAFI_EVOLUZIONE) };
}

function termini(): SezioneDoc {
  return {
    id: 'termini',
    titolo: 'Termini d\'uso',
    blocchi: [
      paragrafo(NOTA_TERMINI_INTRODUZIONE),
      elenco(NOTA_TERMINI_VOCI),
      paragrafo(NOTA_TERMINI_CHIUSURA),
    ],
  };
}

function changelog(): SezioneDoc {
  return {
    id: 'changelog',
    titolo: 'Changelog',
    blocchi: [{
      tipo: 'tabella',
      intestazioni: ['Versione', 'Data', 'Novità'],
      righe: CHANGELOG.map((voce) => [voce.versione, voce.data, voce.note.join(' ')]),
    }],
  };
}

/** Sezioni della pagina, nell'ordine di lettura. Gli id sono unici e stabili (ancore pubbliche). */
export function sezioniDocumentazione(): SezioneDoc[] {
  return [
    introduzione(),
    risorse(),
    formato(),
    esempiCurl(),
    paginazione(),
    filtri(),
    sezioneDate(),
    testoEUrl(),
    cache(),
    limiti(),
    cors(),
    feed(),
    ...errori(),
    evoluzione(),
    termini(),
    changelog(),
  ];
}
