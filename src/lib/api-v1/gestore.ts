/**
 * Gestore HTTP dell'API /api/v1 (puro: tutte le dipendenze sono iniettate).
 *
 * Flusso di GET/HEAD: limitatore -> validazione (senza DB) -> cache in memoria
 * (fresca, stale-while-revalidate, single-flight) -> semaforo -> produzione con
 * budget -> ETag/304. Nessuna eccezione esce dal gestore: un'eccezione non gestita
 * in una rotta Astro diventerebbe la pagina 410 HTML di [category].astro.
 */
import { BUDGET_PRODUZIONE_MS } from './costanti';
import { ErroreDati, ProblemaApi } from './errori';
import {
  ifNoneMatchCorrisponde, risposta304, rispostaContenuto, rispostaPreflight, rispostaProblema, type OpzioniContenuto,
  type ProfiloCache,
} from './http';
import { chiaveClient, intestazioniRateLimit, type Limitatore, type ModalitaFiducia } from './limitatore';
import { SemaforoSaturo, type Semaforo } from './semaforo';
import { oggiRoma } from './tempo';
import type { CacheRisposte, ModoProduzione, PoliticaCache } from './cache';
import type { DescrittoreRotta, DipendenzeRisorse, RisultatoRisorsa } from './risorse';

export interface ContestoHttp {
  request: Request;
  url: URL;
  params: Readonly<Record<string, string | undefined>>;
  /** Indirizzo visto da Astro (primo X-Forwarded-For o socket); puo' mancare. */
  clientAddress: string | null;
}

export interface DipendenzeGestore {
  risorse: DipendenzeRisorse;
  limitatore: Limitatore;
  semaforo: Semaforo;
  cache: CacheRisposte<RisultatoRisorsa>;
  modalitaFiducia: ModalitaFiducia;
  /** Valore di RateLimit-Policy coerente con la configurazione (es. "60;w=60"). */
  politicaRateLimit: string;
  orologio: () => number;
  registra(evento: string, dettaglio?: string): void;
}

export interface Gestore {
  GET(contesto: ContestoHttp): Promise<Response>;
  OPTIONS(): Response;
  ALL(contesto: ContestoHttp): Promise<Response>;
}

/** Politica della cache in memoria per profilo (la cache dell'edge segue Cache-Control). */
const POLITICHE: ReadonlyMap<ProfiloCache, PoliticaCache> = new Map<ProfiloCache, PoliticaCache>([
  ['elenco', { freschezzaMs: 60_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 }],
  ['dettaglio', { freschezzaMs: 60_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 }],
  ['feed', { freschezzaMs: 60_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 }],
  ['statico', { freschezzaMs: 300_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 }],
  ['openapi', { freschezzaMs: 300_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 }],
]);
const POLITICA_PREDEFINITA: PoliticaCache = { freschezzaMs: 60_000, swrMs: 120_000, staleIfErrorMs: 3_600_000 };

/** Il rinfresco in background salta se il semaforo e' occupato. */
class RinfrescoSaltato extends Error {
  constructor() {
    super('rinfresco saltato: semaforo occupato');
    this.name = 'RinfrescoSaltato';
  }
}

/** Errori di disponibilita': DB giu', timeout, abort, semaforo saturo. */
function eDisponibilita(errore: unknown): boolean {
  if (errore instanceof ErroreDati) return errore.classe === 'disponibilita';
  if (errore instanceof SemaforoSaturo) return true;
  if (errore instanceof Error && (errore.name === 'TimeoutError' || errore.name === 'AbortError')) return true;
  return false;
}

function descrivi(errore: unknown): string {
  if (errore instanceof ErroreDati) return `${errore.classe}${errore.codiceDb ? ` ${errore.codiceDb}` : ''}: ${errore.message}`;
  if (errore instanceof Error) return `${errore.name}: ${errore.message}`;
  return String(errore);
}

export function creaGestore(descrittore: DescrittoreRotta, dipendenze: DipendenzeGestore): Gestore {
  const politica = POLITICHE.get(descrittore.profilo) ?? POLITICA_PREDEFINITA;

  /** Limitatore: ogni metodo tranne OPTIONS consuma un gettone. */
  function controllaLimite(contesto: ContestoHttp): Response | null {
    const chiave = chiaveClient({
      intestazioni: contesto.request.headers,
      indirizzoDiretto: contesto.clientAddress,
      modalita: dipendenze.modalitaFiducia,
    });
    const esito = dipendenze.limitatore.consuma(chiave);
    if (esito.consentito) return null;
    const secondi = esito.retryAfterSecondi;
    const problema = new ProblemaApi(
      'rate-limited',
      `Troppe richieste da questo indirizzo. Riprova tra ${secondi} ${secondi === 1 ? 'secondo' : 'secondi'}.`,
      { retryAfter: secondi },
    );
    return rispostaProblema(problema, contesto.url.pathname, intestazioniRateLimit(esito, dipendenze.politicaRateLimit));
  }

  /** Ogni risposta dichiara la politica effettiva (la costante di http.ts e' quella predefinita). */
  function conPolitica(risposta: Response): Response {
    risposta.headers.set('RateLimit-Policy', dipendenze.politicaRateLimit);
    return risposta;
  }

  async function GET(contesto: ContestoHttp): Promise<Response> {
    return conPolitica(await eseguiGet(contesto));
  }

  async function eseguiGet(contesto: ContestoHttp): Promise<Response> {
    const percorso = contesto.url.pathname;
    try {
      const limite = controllaLimite(contesto);
      if (limite) return limite;

      const preparazione = descrittore.prepara(contesto.url, contesto.params);
      const adessoMs = dipendenze.orologio();
      const oggi = oggiRoma(adessoMs);
      const chiave = preparazione.dipendeDaOggi ? `${preparazione.chiave}|${oggi}` : preparazione.chiave;

      const produci = async (modo: ModoProduzione): Promise<RisultatoRisorsa> => {
        let rilascia: (() => void) | null;
        if (modo === 'primo-piano') {
          rilascia = await dipendenze.semaforo.acquisisci();
        } else {
          rilascia = dipendenze.semaforo.provaAcquisire();
          if (!rilascia) throw new RinfrescoSaltato();
        }
        try {
          const segnale = AbortSignal.timeout(BUDGET_PRODUZIONE_MS);
          return await preparazione.produci(dipendenze.risorse, { adessoMs, oggi, segnale });
        } finally {
          rilascia();
        }
      };

      let risultato: RisultatoRisorsa;
      let stantio = false;
      try {
        risultato = (await dipendenze.cache.ottieni(chiave, politica, produci)).valore;
      } catch (errore) {
        if (errore instanceof ProblemaApi) throw errore;
        if (errore instanceof ErroreDati && errore.classe === 'data-non-valida' && preparazione.conCursore) {
          dipendenze.registra('cursore-rifiutato-dal-db', descrivi(errore));
          throw new ProblemaApi('invalid-cursor',
            'Il cursore non e\' valido per questa richiesta. Ricomincia dalla prima pagina.',
            { primo: preparazione.primo });
        }
        if (!eDisponibilita(errore)) throw errore;
        const copia = dipendenze.cache.stantioPerErrore(chiave, politica);
        dipendenze.registra('dati-non-disponibili', `${descrittore.nome}: ${descrivi(errore)}${copia ? ' (servita copia stantia)' : ''}`);
        if (!copia) {
          throw new ProblemaApi('service-unavailable', 'Dati momentaneamente non disponibili.', {
            retryAfter: errore instanceof SemaforoSaturo ? 5 : 30,
          });
        }
        risultato = copia;
        stantio = true;
      }

      const opzioni: OpzioniContenuto = {
        contentType: risultato.contentType,
        profilo: stantio ? 'stantio' : risultato.profilo,
        etag: risultato.etag,
        link: risultato.link,
        extra: stantio ? { 'X-EduNews24-Cache': 'STALE' } : {},
      };
      if (ifNoneMatchCorrisponde(contesto.request.headers.get('if-none-match'), risultato.etag)) {
        return risposta304(opzioni);
      }
      return rispostaContenuto(risultato.corpo, opzioni);
    } catch (errore) {
      if (errore instanceof ProblemaApi) return rispostaProblema(errore, percorso);
      dipendenze.registra('errore-interno', `${descrittore.nome}: ${descrivi(errore)}`);
      return rispostaProblema(new ProblemaApi('internal-error', 'Errore interno.'), percorso);
    }
  }

  async function ALL(contesto: ContestoHttp): Promise<Response> {
    return conPolitica(await eseguiAll(contesto));
  }

  async function eseguiAll(contesto: ContestoHttp): Promise<Response> {
    try {
      const limite = controllaLimite(contesto);
      if (limite) return limite;
      return rispostaProblema(
        new ProblemaApi('method-not-allowed', 'Metodo non consentito: l\'API e\' in sola lettura (GET, HEAD, OPTIONS).'),
        contesto.url.pathname,
      );
    } catch (errore) {
      dipendenze.registra('errore-interno', `${descrittore.nome}: ${descrivi(errore)}`);
      return rispostaProblema(new ProblemaApi('internal-error', 'Errore interno.'), contesto.url.pathname);
    }
  }

  return { GET, OPTIONS: () => conPolitica(rispostaPreflight()), ALL };
}
