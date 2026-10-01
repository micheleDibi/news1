/**
 * Lo storico di un bando: tutti gli eventi che la anon key legge, in fondo
 * alla scheda (contratto interno del giro 3, §15).
 *
 * Il box «Aggiornamenti» in alto mostra solo le notizie (`in_aggiornamenti`);
 * qui c'è tutto, anche le transizioni automatiche e gli eventi tecnici, perché
 * chi legge possa ricostruire che cosa è successo alla scheda e quando. Nessuna
 * pagina globale: lo storico vive solo nella scheda del suo bando.
 *
 * Tre regole che non si vedono dalle frasi.
 *
 * **La data e l'ordine.** Lo storico racconta quando la scheda è cambiata:
 * si ordina per `rilevato_at` (poi cursore, poi id) e la data mostrata è il
 * giorno di Roma del rilevamento, mai l'ora locale del processo. Ordinare per
 * `data_evento` sembrava più naturale e non lo è: il bando 215460 ha una
 * proroga datata dall'ente 17/09 ma rilevata il 30/09, dopo la chiusura
 * automatica del 25/09, e in cima allo storico sarebbe finito «chiuso» su un
 * bando aperto. La data dell'ente non si perde: se è un altro giorno, e la
 * frase non la dice già, la voce la porta come «data dell'atto».
 *
 * **«Correzione».** Un evento fuori dal box (`in_aggiornamenti=false`) è una
 * correzione solo se cambia una data o uno stato; `correzione_redazionale` lo
 * è sempre. Gli eventi tecnici, automatici e documentali non portano
 * etichetta: «Scheda pubblicata» non corregge niente.
 *
 * **I ritiri.** Il registro è immutabile: un evento ritirato resta in tabella e
 * il ritiro è una riga nuova con `riferisce_a`. Non si mostrano né l'evento
 * ritirato né la riga del ritiro: un fatto smentito non va raccontato come
 * vero. Il filtro è uno solo per box e storico (`senzaRitirati`).
 *
 * Modulo «foglia»: nessun import impuro, nessuna data presa dall'orologio.
 */
import { senzaRitirati, testoEvento } from './aggiornamenti';
import { hostDi, urlPubblicabile } from './domini';
import { giornoItaliano } from './testi-stato';
import { giornoRoma } from '../stato-bando';
import type { EventoBando } from './tipi';

/** Quante voci si vedono subito; le altre stanno in un `<details>`. */
export const STORICO_VISIBILI = 10;

/**
 * I tipi che, fuori dal box, sono una correzione: cambiano una data o uno
 * stato già mostrati in pagina.
 */
export const TIPI_CORREZIONE: ReadonlySet<string> = new Set([
  'apertura', 'chiusura', 'proroga', 'riapertura', 'rettifica',
  'sospensione', 'revoca', 'annullamento_revoca',
]);

/** Un evento come lo legge lo storico: le colonne del box più tre. */
export interface EventoStorico extends EventoBando {
  /** Serve alla frase della fusione, che cambia fra master e doppione. */
  readonly bando_id?: number | string | null;
  /** Monotono: a parità di giorno decide l'ordine. */
  readonly cursore?: number | string | null;
  /** L'evento corretto o ritirato da questa riga. */
  readonly riferisce_a?: number | string | null;
}

/** Una voce dello storico, già pronta per il render. */
export interface VoceStorico {
  readonly id: number | string;
  /** La frase, templata dal tipo. Mai testo di un modello. */
  readonly testo: string;
  /** Il giorno in ISO (YYYY-MM-DD) per `<time datetime>`, o null. */
  readonly giorno: string | null;
  /** Lo stesso giorno in italiano, o null. */
  readonly quando: string | null;
  /**
   * Il giorno dichiarato dall'ente (`data_evento`) in italiano, solo se è un
   * altro giorno rispetto a `giorno` e la frase non lo contiene già.
   */
  readonly dataAtto: string | null;
  /** La pagina che lo prova, solo se pubblicabile. Mai un aggregatore. */
  readonly url: string | null;
  readonly host: string | null;
  /** `true` = si mostra con l'etichetta «Correzione». */
  readonly correzione: boolean;
}

const FORMA_GIORNO = /^\d{4}-\d{2}-\d{2}/;
const FORMA_ISTANTE = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}(?::?\d{2})?)?$/;

/** Il giorno dichiarato dall'ente (YYYY-MM-DD), o null. */
function giornoAtto(evento: EventoStorico): string | null {
  return typeof evento.data_evento === 'string' && FORMA_GIORNO.test(evento.data_evento)
    ? evento.data_evento.slice(0, 10)
    : null;
}

/**
 * I millisecondi di un timestamp, o null. Senza fuso vale UTC, come in
 * `stato-bando.ts`: `Date` lo leggerebbe nell'ora locale del processo.
 */
function istante(valore: string | null | undefined): number | null {
  if (typeof valore !== 'string') return null;
  const parti = FORMA_ISTANTE.exec(valore.trim());
  if (parti === null) return null;
  let fuso = parti[3] ?? 'Z';
  if (/^[+-]\d{2}$/.test(fuso)) fuso = `${fuso}:00`;
  else if (/^[+-]\d{4}$/.test(fuso)) fuso = `${fuso.slice(0, 3)}:${fuso.slice(3)}`;
  // PostgREST manda i microsecondi: bastano i millisecondi.
  const ora = parti[2].replace(/(\.\d{3})\d+$/, '$1');
  const ms = Date.parse(`${parti[1]}T${ora}${fuso}`);
  return Number.isNaN(ms) ? null : ms;
}

/**
 * Quando la scheda è cambiata: il rilevamento. Senza, il mezzogiorno UTC del
 * giorno dell'ente, così la riga resta al suo posto invece di finire in fondo.
 */
function chiaveTempo(evento: EventoStorico): number {
  const rilevato = istante(evento.rilevato_at ?? null);
  if (rilevato !== null) return rilevato;
  const atto = giornoAtto(evento);
  const ripiego = atto === null ? null : istante(`${atto}T12:00:00Z`);
  return ripiego ?? Number.NEGATIVE_INFINITY;
}

/** Un numero confrontabile da una colonna bigint, che può arrivare come stringa. */
function numero(valore: number | string | null | undefined): number {
  const n = typeof valore === 'number' ? valore : Number(valore);
  return valore === null || valore === undefined || valore === '' || Number.isNaN(n)
    ? Number.NEGATIVE_INFINITY
    : n;
}

/** L'etichetta «Correzione» (contratto interno del giro 3, §15). */
export function eCorrezione(evento: EventoBando): boolean {
  if (evento.tipo === 'correzione_redazionale') return true;
  return evento.in_aggiornamenti === false && TIPI_CORREZIONE.has(evento.tipo);
}

/**
 * Le voci dello storico, dalla più recente.
 *
 * Ordine: rilevamento decrescente (senza nessuna data, in fondo), poi cursore
 * decrescente, poi id decrescente. Un evento letto due volte (righe uguali
 * su due pagine) compare una volta sola.
 */
export function vociStorico(
  eventi: readonly EventoStorico[] | null | undefined,
): VoceStorico[] {
  if (!Array.isArray(eventi)) return [];

  const visti = new Set<string>();
  const voci: Array<{ voce: VoceStorico; tempo: number; cursore: number; id: number }> = [];
  for (const evento of senzaRitirati(eventi)) {
    const chiave = String(evento.id);
    if (visti.has(chiave)) continue;
    visti.add(chiave);
    const testo = testoEvento(evento);
    if (testo === null) continue;
    // Come nel box: la prova si mostra solo se l'URL è pubblicabile (schema
    // http(s), host fuori dalla denylist degli aggregatori).
    const mostrabile = urlPubblicabile(evento.url_prova);
    const host = mostrabile ? hostDi(evento.url_prova) : null;
    const atto = giornoAtto(evento);
    const giorno = giornoRoma(evento.rilevato_at ?? null) ?? atto;
    const attoItaliano = giornoItaliano(atto);
    // «6 luglio 2026» è già in «dal 6 luglio 2026», ma non in «dal 16 luglio
    // 2026»: il giorno deve cominciare dopo un carattere che non è una cifra.
    const giaDetta = attoItaliano !== null && new RegExp(`(^|\\D)${attoItaliano}`).test(testo);
    const dataAtto = atto !== null && atto !== giorno && !giaDetta ? attoItaliano : null;
    voci.push({
      voce: {
        id: evento.id,
        testo,
        giorno,
        quando: giornoItaliano(giorno),
        dataAtto,
        url: mostrabile ? (evento.url_prova ?? null) : null,
        host: mostrabile ? host : null,
        correzione: eCorrezione(evento),
      },
      tempo: chiaveTempo(evento),
      cursore: numero(evento.cursore),
      id: numero(evento.id),
    });
  }

  return voci.sort((a, b) => {
    if (a.tempo !== b.tempo) return b.tempo > a.tempo ? 1 : -1;
    if (a.cursore !== b.cursore) return b.cursore > a.cursore ? 1 : -1;
    if (a.id !== b.id) return b.id > a.id ? 1 : -1;
    return 0;
  }).map((v) => v.voce);
}

/** Le voci divise fra quelle visibili subito e quelle nel `<details>`. */
export function dividiStorico(
  voci: readonly VoceStorico[],
  visibili: number = STORICO_VISIBILI,
): { visibili: VoceStorico[]; altre: VoceStorico[] } {
  const n = Math.max(0, Math.floor(visibili));
  return { visibili: voci.slice(0, n), altre: voci.slice(n) };
}
