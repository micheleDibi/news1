/**
 * Rate limiting applicativo dell'API v1 (piano §8.1): chiave del client e token bucket.
 *
 * Tutto in memoria e per processo. Nessun timer: la ricarica dei secchi e l'eviction
 * della mappa si calcolano in modo pigro con l'orologio iniettato.
 *
 * Chiave del client:
 * - IPv4 -> `4:<ip>`; IPv6 -> `6:<primi 4 gruppi>` (il /64, che di norma e' un solo
 *   abbonato); un IPv4 mappato in IPv6 (`::ffff:a.b.c.d`) vale come IPv4.
 * - `CF-Connecting-IP` si legge SOLO se l'ultimo hop appartiene ai range di Cloudflare:
 *   altrimenti chiunque aggiri Cloudflare potrebbe scegliersi la chiave a ogni richiesta.
 * - `clientAddress` di Astro e' il valore piu' a sinistra di X-Forwarded-For (falsificabile):
 *   qui entra solo come ripiego quando XFF non contiene nessun IP valido.
 */
import { BlockList, isIP } from 'node:net';
import { CIDR_CLOUDFLARE } from './costanti';

export type ModalitaFiducia = 'cloudflare' | 'nginx' | 'diretta';

const MODALITA_NOTE: ReadonlySet<string> = new Set<ModalitaFiducia>(['cloudflare', 'nginx', 'diretta']);

function eModalita(valore: string): valore is ModalitaFiducia {
  return MODALITA_NOTE.has(valore);
}

/**
 * Legge API_V1_FIDUCIA_IP. Assente o vuota -> `cloudflare` (riconosciuta). Un valore
 * sconosciuto ripiega su `cloudflare` con `riconosciuta: false`, cosi' il chiamante puo'
 * segnalarlo nei log senza far cadere il processo. Maiuscole e spazi sono tollerati.
 */
export function leggiModalitaFiducia(
  valore: string | undefined | null,
): { modalita: ModalitaFiducia; riconosciuta: boolean } {
  const pulito = (valore ?? '').trim().toLowerCase();
  if (pulito === '') return { modalita: 'cloudflare', riconosciuta: true };
  if (eModalita(pulito)) return { modalita: pulito, riconosciuta: true };
  return { modalita: 'cloudflare', riconosciuta: false };
}

// --- Indirizzi IP --------------------------------------------------------------------

const GRUPPO_ESADECIMALE = /^[0-9a-f]{1,4}$/;
const OTTETTO = /^(0|[1-9]\d{0,2})$/;

/** Ottetti di un IPv4 in notazione decimale puntata (niente zeri iniziali), o null. */
function ottettiIpv4(testo: string): number[] | null {
  const parti = testo.split('.');
  if (parti.length !== 4) return null;
  const ottetti: number[] = [];
  for (const parte of parti) {
    if (!OTTETTO.test(parte)) return null;
    const n = Number(parte);
    if (n > 255) return null;
    ottetti.push(n);
  }
  return ottetti;
}

/**
 * Parser puro IPv6 (senza zona): gli 8 gruppi da 16 bit, o null se la forma non e' valida.
 * Gestisce `::` in qualunque posizione, maiuscole, zeri iniziali e un IPv4 incorporato
 * nelle ultime 32 bit.
 */
function gruppiIpv6(indirizzo: string): number[] | null {
  let testo = indirizzo.toLowerCase();
  const ultimiDuePunti = testo.lastIndexOf(':');
  if (ultimiDuePunti < 0) return null;
  const coda = testo.slice(ultimiDuePunti + 1);
  if (coda.includes('.')) {
    const ottetti = ottettiIpv4(coda);
    if (ottetti === null) return null;
    const alto = ((ottetti[0] << 8) | ottetti[1]).toString(16);
    const basso = ((ottetti[2] << 8) | ottetti[3]).toString(16);
    testo = `${testo.slice(0, ultimiDuePunti + 1)}${alto}:${basso}`;
  }

  const meta = testo.split('::');
  if (meta.length > 2) return null;
  const sinistra = meta[0] === '' ? [] : meta[0].split(':');
  const destra = meta.length === 2 && meta[1] !== '' ? meta[1].split(':') : [];

  let parti: string[];
  if (meta.length === 1) {
    if (sinistra.length !== 8) return null;
    parti = sinistra;
  } else {
    const mancanti = 8 - sinistra.length - destra.length;
    if (mancanti < 1) return null;
    parti = [...sinistra, ...new Array<string>(mancanti).fill('0'), ...destra];
  }

  const gruppi: number[] = [];
  for (const parte of parti) {
    if (!GRUPPO_ESADECIMALE.test(parte)) return null;
    gruppi.push(parseInt(parte, 16));
  }
  return gruppi;
}

/** IPv4 mappato in IPv6 (`::ffff:0:0/96`): i primi 80 bit a zero e poi 0xffff. */
function eIpv4Mappato(gruppi: readonly number[]): boolean {
  return gruppi[0] === 0 && gruppi[1] === 0 && gruppi[2] === 0 && gruppi[3] === 0
    && gruppi[4] === 0 && gruppi[5] === 0xffff;
}

/**
 * IP validato e normalizzato. Spazi esterni tolti; la validita' la decide `net.isIP`
 * (niente porte, niente parentesi quadre, niente zeri iniziali negli IPv4).
 * - IPv4 -> invariato;
 * - IPv6 -> zona (`%eth0`) tolta, forma estesa in minuscolo senza zeri iniziali
 *   (`2001:db8:0:0:0:0:0:1`), cosi' la stessa rete ha una sola scrittura;
 * - IPv4 mappato (`::ffff:1.2.3.4`) -> famiglia 4.
 */
export function ipNormalizzato(valore: string): { famiglia: 4 | 6; ip: string } | null {
  const testo = valore.trim();
  const famiglia = isIP(testo);
  if (famiglia === 4) return { famiglia: 4, ip: testo };
  if (famiglia !== 6) return null;

  const zona = testo.indexOf('%');
  const senzaZona = zona < 0 ? testo : testo.slice(0, zona);
  const gruppi = gruppiIpv6(senzaZona);
  if (gruppi === null) return null;
  if (eIpv4Mappato(gruppi)) {
    const ip = [gruppi[6] >> 8, gruppi[6] & 0xff, gruppi[7] >> 8, gruppi[7] & 0xff].join('.');
    return { famiglia: 4, ip };
  }
  return { famiglia: 6, ip: gruppi.map((g) => g.toString(16)).join(':') };
}

/**
 * Chiave del token bucket per un IP: `4:<ipv4>` oppure `6:<prefisso /64>`
 * (es. `2001:db8:1:2::5` -> `6:2001:db8:1:2`). Null se il valore non e' un IP.
 */
export function chiaveIp(valore: string): string | null {
  const normalizzato = ipNormalizzato(valore);
  if (normalizzato === null) return null;
  if (normalizzato.famiglia === 4) return `4:${normalizzato.ip}`;
  return `6:${normalizzato.ip.split(':').slice(0, 4).join(':')}`;
}

// --- Range di Cloudflare ---------------------------------------------------------------

let rangeCloudflare: BlockList | null = null;

/** BlockList dei range di Cloudflare, costruita alla prima richiesta e poi riusata. */
function listaCloudflare(): BlockList {
  if (rangeCloudflare !== null) return rangeCloudflare;
  const lista = new BlockList();
  for (const cidr of CIDR_CLOUDFLARE) {
    const [rete, prefisso] = cidr.split('/');
    const famiglia = isIP(rete);
    if (famiglia === 0 || prefisso === undefined) {
      throw new Error(`CIDR di Cloudflare non valido in costanti.ts: ${cidr}`);
    }
    lista.addSubnet(rete, Number(prefisso), famiglia === 4 ? 'ipv4' : 'ipv6');
  }
  rangeCloudflare = lista;
  return lista;
}

function diCloudflare(ip: { famiglia: 4 | 6; ip: string }): boolean {
  return listaCloudflare().check(ip.ip, ip.famiglia === 4 ? 'ipv4' : 'ipv6');
}

// --- Chiave del client -----------------------------------------------------------------

/** Quel che serve delle intestazioni: `Headers` va bene cosi' com'e' (get case-insensitive). */
export interface IntestazioniLeggibili {
  get(nome: string): string | null;
}

export interface IngressoChiaveClient {
  intestazioni: IntestazioniLeggibili;
  /** `clientAddress` della richiesta, se disponibile. */
  indirizzoDiretto: string | null;
  modalita: ModalitaFiducia;
}

const CHIAVE_SCONOSCIUTA = 'sconosciuto';

/** Un header a valore unico (niente liste) che contiene un IP valido, o null. */
function ipUnico(valore: string | null): string | null {
  if (valore === null || valore.includes(',')) return null;
  return ipNormalizzato(valore) === null ? null : valore;
}

/** L'ultimo IP valido di X-Forwarded-For, saltando i valori non validi. */
function ultimoIpInoltrato(valore: string | null): { famiglia: 4 | 6; ip: string } | null {
  if (valore === null) return null;
  const voci = valore.split(',');
  for (let i = voci.length - 1; i >= 0; i--) {
    const ip = ipNormalizzato(voci[i]);
    if (ip !== null) return ip;
  }
  return null;
}

/** Algoritmo `cloudflare` (§8.1): ultimo hop, e CF-Connecting-IP solo se l'hop e' di Cloudflare. */
function chiaveDaCatena(intestazioni: IntestazioniLeggibili, indirizzoDiretto: string | null): string | null {
  const ultimo = ultimoIpInoltrato(intestazioni.get('x-forwarded-for'))
    ?? (indirizzoDiretto === null ? null : ipNormalizzato(indirizzoDiretto));
  if (ultimo === null) return null;
  if (diCloudflare(ultimo)) {
    const originale = ipUnico(intestazioni.get('cf-connecting-ip'));
    if (originale !== null) return chiaveIp(originale);
  }
  return chiaveIp(ultimo.ip);
}

/** Chiave del token bucket per la richiesta, secondo la modalita' di fiducia. Mai vuota. */
export function chiaveClient(input: IngressoChiaveClient): string {
  const { intestazioni, indirizzoDiretto, modalita } = input;
  let chiave: string | null;
  if (modalita === 'diretta') {
    chiave = indirizzoDiretto === null ? null : chiaveIp(indirizzoDiretto);
  } else {
    const daNginx = modalita === 'nginx' ? ipUnico(intestazioni.get('x-edunews24-client-ip')) : null;
    chiave = daNginx !== null ? chiaveIp(daNginx) : chiaveDaCatena(intestazioni, indirizzoDiretto);
  }
  return chiave ?? CHIAVE_SCONOSCIUTA;
}

// --- Token bucket ----------------------------------------------------------------------

export interface OpzioniLimitatore {
  capacita: number;
  ricaricaPerSecondo: number;
  maxChiavi: number;
  /** Millisecondi (es. `Date.now`); iniettato per i test. */
  orologio: () => number;
}

export interface EsitoLimite {
  consentito: boolean;
  limite: number;
  /** Gettoni interi rimasti dopo questa richiesta. */
  rimanenti: number;
  /** Secondi (arrotondati per eccesso) per tornare a secchio pieno. */
  ripristinoSecondi: number;
  /** Secondi (per eccesso, minimo 1) per avere un gettone; 0 se la richiesta e' consentita. */
  retryAfterSecondi: number;
}

interface Secchio {
  gettoni: number;
  aggiornato: number;
}

/**
 * Token bucket per chiave. La mappa usa l'ordine di inserimento come LRU (ogni accesso
 * cancella e reinserisce). A mappa piena una chiave nuova libera la voce piu' vecchia solo
 * se quella e' gia' tornata piena (cioe' inattiva: dimenticarla non regala gettoni a
 * nessuno); altrimenti consuma da un secchio condiviso `__overflow__`, fuori dalla mappa,
 * cosi' un'ondata di chiavi nuove non puo' azzerare i secchi dei client attivi.
 */
export class Limitatore {
  private readonly capacita: number;
  private readonly ricaricaPerSecondo: number;
  private readonly maxChiavi: number;
  private readonly orologio: () => number;
  private readonly secchi = new Map<string, Secchio>();
  /** Il secchio condiviso `__overflow__`, creato al primo trabocco. */
  private overflow: Secchio | null = null;

  constructor(opzioni: OpzioniLimitatore) {
    if (!Number.isFinite(opzioni.capacita) || opzioni.capacita < 1) {
      throw new RangeError('Limitatore: capacita deve essere un numero finito >= 1');
    }
    if (!Number.isFinite(opzioni.ricaricaPerSecondo) || opzioni.ricaricaPerSecondo <= 0) {
      throw new RangeError('Limitatore: ricaricaPerSecondo deve essere un numero finito > 0');
    }
    if (!Number.isInteger(opzioni.maxChiavi) || opzioni.maxChiavi < 1) {
      throw new RangeError('Limitatore: maxChiavi deve essere un intero >= 1');
    }
    this.capacita = opzioni.capacita;
    this.ricaricaPerSecondo = opzioni.ricaricaPerSecondo;
    this.maxChiavi = opzioni.maxChiavi;
    this.orologio = opzioni.orologio;
  }

  /** Numero di chiavi tracciate (il secchio `__overflow__` escluso). */
  get numeroChiavi(): number {
    return this.secchi.size;
  }

  /** Consuma un gettone per la chiave e dice se la richiesta passa. */
  consuma(chiave: string): EsitoLimite {
    const ora = this.orologio();
    return this.preleva(this.secchioPer(chiave, ora), ora);
  }

  private secchioPer(chiave: string, ora: number): Secchio {
    const esistente = this.secchi.get(chiave);
    if (esistente !== undefined) {
      this.secchi.delete(chiave);
      this.secchi.set(chiave, esistente);
      return esistente;
    }
    if (this.secchi.size >= this.maxChiavi) {
      const piuVecchia = this.secchi.entries().next();
      if (!piuVecchia.done) {
        const [chiaveVecchia, secchioVecchio] = piuVecchia.value;
        if (this.gettoniA(secchioVecchio, ora) >= this.capacita) {
          this.secchi.delete(chiaveVecchia);
        } else {
          if (this.overflow === null) this.overflow = { gettoni: this.capacita, aggiornato: ora };
          return this.overflow;
        }
      }
    }
    const nuovo: Secchio = { gettoni: this.capacita, aggiornato: ora };
    this.secchi.set(chiave, nuovo);
    return nuovo;
  }

  /** Gettoni del secchio all'istante `ora`, ricarica compresa (un orologio che torna indietro non toglie nulla). */
  private gettoniA(secchio: Secchio, ora: number): number {
    const trascorsi = Math.max(0, ora - secchio.aggiornato) / 1000;
    return Math.min(this.capacita, secchio.gettoni + trascorsi * this.ricaricaPerSecondo);
  }

  private preleva(secchio: Secchio, ora: number): EsitoLimite {
    let gettoni = this.gettoniA(secchio, ora);
    const consentito = gettoni >= 1;
    if (consentito) gettoni -= 1;
    secchio.gettoni = gettoni;
    // Il tempo trascorso negativo e' gia' azzerato in gettoniA: un orologio che torna
    // indietro non deve congelare la ricarica.
    secchio.aggiornato = ora;
    return {
      consentito,
      limite: this.capacita,
      rimanenti: Math.max(0, Math.floor(gettoni)),
      ripristinoSecondi: Math.max(0, Math.ceil((this.capacita - gettoni) / this.ricaricaPerSecondo)),
      retryAfterSecondi: consentito ? 0 : Math.max(1, Math.ceil((1 - gettoni) / this.ricaricaPerSecondo)),
    };
  }
}

/**
 * Intestazioni del 429 (draft IETF RateLimit): valori interi come stringhe.
 * `RateLimit-Reset` e' il tempo per tornare a secchio pieno; `Retry-After` quello per
 * avere di nuovo un gettone. Include anche `RateLimit-Policy`, che il gestore mette
 * comunque su tutte le risposte: con `Headers.set` il valore resta uno solo.
 */
export function intestazioniRateLimit(esito: EsitoLimite, politica: string): Record<string, string> {
  return {
    'RateLimit-Policy': politica,
    'RateLimit-Limit': String(Math.floor(esito.limite)),
    'RateLimit-Remaining': String(Math.max(0, Math.floor(esito.rimanenti))),
    'RateLimit-Reset': String(Math.max(0, Math.ceil(esito.ripristinoSecondi))),
    'Retry-After': String(Math.max(1, Math.ceil(esito.retryAfterSecondi))),
  };
}
