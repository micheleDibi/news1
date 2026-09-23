/**
 * Cablaggio dell'API /api/v1 per le rotte Astro (impuro): crea una volta per
 * processo limitatore, semaforo, cache e riferimenti, legge la configurazione e
 * collega il corpus. Le rotte in src/pages/api/v1/ sono di poche righe:
 *
 *   const r = definisciRotta(ELENCO_ARTICOLI);
 *   export const GET = r.GET; export const HEAD = r.GET;
 *   export const OPTIONS = r.OPTIONS; export const ALL = r.ALL;
 *
 * HEAD va esportato esplicitamente: con ALL presente Astro manderebbe HEAD su ALL.
 *
 * Configurazione (ambiente del processo, poi valore compilato da .env, poi default):
 *   API_V1_FIDUCIA_IP    cloudflare (default) | nginx | diretta  -> limitatore.ts
 *   API_V1_RL_CAPACITA   richieste per client (default 60)
 *   API_V1_RL_RICARICA   gettoni al secondo (default 1)
 *   BANDI_FONTE_LETTURA  bando (default) | bando_pubblico          -> filtri.ts
 *
 * Le prime tre saltano il valore vuoto e ricadono su quello compilato;
 * BANDI_FONTE_LETTURA no, perche' deve dare lo stesso risultato di
 * `supabase-bandi.ts` anche quando l'override e' definito ma vuoto (vedi sotto).
 */
import type { APIContext, APIRoute } from 'astro';
import { corpusSeCaldo } from '../corpus';
import { nomeFonteBandiDa } from '../bandi/pubblicazione';
import {
  ATTESA_SEMAFORO_MS, CODA_SEMAFORO, RATE_LIMIT_CAPACITA, RATE_LIMIT_MAX_CHIAVI, RATE_LIMIT_RICARICA, SLOT_SEMAFORO,
  TIMEOUT_QUERY_MS, TTL_RIFERIMENTI_MS,
} from './costanti';
import { CacheRisposte } from './cache';
import { ErroreDati } from './errori';
import { creaFonteSupabase } from './fonte-supabase';
import { pianoRiferimento } from './filtri';
import { creaGestore, type DipendenzeGestore, type Gestore } from './gestore';
import { Limitatore, leggiModalitaFiducia } from './limitatore';
import { CacheRiferimento, costruisciRiferimentoCategorie, costruisciRiferimentoProfili } from './riferimenti';
import { Semaforo } from './semaforo';
import type { PianoQuery, RiferimentoCategorie, RiferimentoProfili } from './contratto';
import type { DescrittoreRotta, DipendenzeRisorse, RisultatoRisorsa } from './risorse';

function primoValorizzato(...valori: Array<string | undefined>): string | undefined {
  for (const v of valori) if (typeof v === 'string' && v.trim() !== '') return v.trim();
  return undefined;
}

function interoPositivo(valore: string | undefined, predefinito: number): number {
  if (valore === undefined || !/^[1-9]\d{0,6}$/.test(valore)) return predefinito;
  return Number(valore);
}

// Log campionato: al massimo un messaggio al minuto per tipo di evento.
const ultimoLog = new Map<string, number>();
function registra(evento: string, dettaglio?: string): void {
  const adesso = Date.now();
  if (adesso - (ultimoLog.get(evento) ?? 0) < 60_000) return;
  ultimoLog.set(evento, adesso);
  console.error(`[api-v1] ${evento}${dettaglio ? `: ${dettaglio}` : ''}`);
}

let dipendenze: DipendenzeGestore | null = null;

function creaDipendenze(): DipendenzeGestore {
  // Data e ora (oggi di Roma, ETag delle date) dall'orologio di sistema; scadenze di
  // cache e gettoni da un orologio monotono, immune ai passi indietro dell'ora.
  const orologio = () => Date.now();
  const monotono = () => performance.now();
  const valoreFiducia = primoValorizzato(process.env.API_V1_FIDUCIA_IP, import.meta.env.API_V1_FIDUCIA_IP);
  const fiducia = leggiModalitaFiducia(valoreFiducia);
  if (!fiducia.riconosciuta) registra('configurazione', 'API_V1_FIDUCIA_IP non riconosciuta: uso "cloudflare"');
  const capacita = interoPositivo(
    primoValorizzato(process.env.API_V1_RL_CAPACITA, import.meta.env.API_V1_RL_CAPACITA), RATE_LIMIT_CAPACITA);
  const ricarica = interoPositivo(
    primoValorizzato(process.env.API_V1_RL_RICARICA, import.meta.env.API_V1_RL_RICARICA), RATE_LIMIT_RICARICA);
  // Da quale fonte legge i bandi l'API. Il flag lo legge questo modulo e non
  // `filtri.ts`: quello e' puro, e `PUBLIC_*` viene compilata al build mentre
  // `BANDI_FONTE_LETTURA` vale a runtime (e' il ritorno indietro senza
  // ricostruire). Un valore ignoto non solleva e non "prova" la vista:
  // `nomeFonteBandiDa` torna `bando`.
  //
  // `??` e NON `primoValorizzato`: qui l'espressione dev'essere la stessa,
  // carattere per carattere, di `supabase-bandi.ts`. Con l'override svuotato
  // (`BANDI_FONTE_LETTURA=` in .env o nell'unit systemd) e
  // `PUBLIC_BANDI_FONTE_LETTURA=bando_pubblico` compilata, `??` tiene la
  // stringa vuota e ricade sul default `bando` — come le pagine —, mentre
  // `primoValorizzato` salterebbe il vuoto e manderebbe la sola API sulla
  // vista: due superfici pubbliche dello stesso corpus con insiemi di righe
  // diversi (la vista toglie doppioni fusi e ritirati). Il vuoto che ricade
  // sul valore compilato resta invece giusto per API_V1_FIDUCIA_IP e per i
  // due interi, dove non c'e' nessun'altra superficie da tenere allineata.
  const fonteBandi = nomeFonteBandiDa(
    process.env.BANDI_FONTE_LETTURA ?? import.meta.env.PUBLIC_BANDI_FONTE_LETTURA,
  );
  console.error(
    `[api-v1] configurazione: fiducia_ip=${fiducia.modalita}, rate_limit=${capacita} (+${ricarica}/s), `
    + `fonte_bandi=${fonteBandi}`);

  const fonte = creaFonteSupabase();

  const categorie = new CacheRiferimento<RiferimentoCategorie>({
    nome: 'categorie',
    ttlMs: TTL_RIFERIMENTI_MS,
    timeoutMs: TIMEOUT_QUERY_MS,
    orologio: monotono,
    registra,
    async carica(segnale) {
      const [righeCategorie, righeSecondarie] = await Promise.all([
        fonte.leggi(pianoRiferimento('categories') as PianoQuery<'categorie'>, segnale),
        fonte.leggi(pianoRiferimento('secondary_categories') as PianoQuery<'secondarie'>, segnale),
      ]);
      const { riferimento, scarti } = costruisciRiferimentoCategorie(righeCategorie, righeSecondarie);
      if (scarti.length > 0) registra('riferimento-categorie', `${scarti.length} righe scartate`);
      return riferimento;
    },
  });

  const profili = new CacheRiferimento<RiferimentoProfili>({
    nome: 'profili',
    ttlMs: TTL_RIFERIMENTI_MS,
    timeoutMs: TIMEOUT_QUERY_MS,
    orologio: monotono,
    registra,
    async carica(segnale) {
      try {
        const righe = await fonte.leggi(pianoRiferimento('profiles') as PianoQuery<'profili'>, segnale);
        return costruisciRiferimentoProfili(righe);
      } catch (errore) {
        // profiles chiusa all'anon (GRANT revocato, 42501): nessun nome pubblico disponibile,
        // tutti gli articoli firmati "Redazione EduNews24". Non e' un guasto: niente 503.
        if (errore instanceof ErroreDati && errore.classe === 'permesso') {
          registra('profili-non-leggibili', '42501: autori esposti come Redazione EduNews24');
          return costruisciRiferimentoProfili([]);
        }
        throw errore;
      }
    },
  });

  const risorse: DipendenzeRisorse = {
    fonte,
    categorie,
    profili,
    fonteBandi,
    valoriRegioneCorpus(sezione, slugRegione) {
      return corpusSeCaldo(sezione)?.faccette.regione?.get(slugRegione)?.valoriDb ?? [];
    },
    limiteDichiarato: { requests: capacita, window_seconds: Math.round(capacita / ricarica) },
    registra,
  };

  return {
    risorse,
    limitatore: new Limitatore({ capacita, ricaricaPerSecondo: ricarica, maxChiavi: RATE_LIMIT_MAX_CHIAVI, orologio: monotono }),
    semaforo: new Semaforo({ slot: SLOT_SEMAFORO, coda: CODA_SEMAFORO, attesaMs: ATTESA_SEMAFORO_MS }),
    cache: new CacheRisposte<RisultatoRisorsa>({
      maxVoci: 1000,
      maxByte: 16 * 1024 * 1024,
      orologio: monotono,
      misura: (r) => r.corpo.length * 2 + 256,
      suErroreSfondo: (chiave, errore) => registra('rinfresco-fallito', `${chiave}: ${errore instanceof Error ? errore.name : 'errore'}`),
    }),
    modalitaFiducia: fiducia.modalita,
    politicaRateLimit: `${capacita};w=${Math.max(1, Math.round(capacita / ricarica))}`,
    orologio,
    registra,
  };
}

function dipendenzeProcesso(): DipendenzeGestore {
  if (!dipendenze) dipendenze = creaDipendenze();
  return dipendenze;
}

function indirizzoCliente(contesto: APIContext): string | null {
  try {
    return contesto.clientAddress ?? null;
  } catch {
    return null;
  }
}

export interface Rotta {
  GET: APIRoute;
  OPTIONS: APIRoute;
  ALL: APIRoute;
}

export function definisciRotta(descrittore: DescrittoreRotta): Rotta {
  let gestore: Gestore | null = null;
  const ottieniGestore = () => (gestore ??= creaGestore(descrittore, dipendenzeProcesso()));
  const contestoHttp = (contesto: APIContext) => ({
    request: contesto.request,
    url: contesto.url,
    params: contesto.params,
    clientAddress: indirizzoCliente(contesto),
  });
  return {
    GET: (contesto) => ottieniGestore().GET(contestoHttp(contesto)),
    OPTIONS: () => ottieniGestore().OPTIONS(),
    ALL: (contesto) => ottieniGestore().ALL(contestoHttp(contesto)),
  };
}
