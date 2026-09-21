/**
 * Cache in memoria delle risposte v1 (piano §7): LRU per numero di voci e per byte,
 * freschezza + stale-while-revalidate + stale-if-error, single-flight.
 *
 * Pura: orologio iniettato, nessun timer. Si salvano solo i valori prodotti con
 * successo: chi produce segnala un guasto (5xx, riferimento vuoto, ...) lanciando, e
 * un'eccezione non entra mai in cache. La voce vecchia resta fino al successo
 * successivo, cosi' `stantioPerErrore` puo' ancora servirla.
 */

export interface PoliticaCache {
  /** Eta' sotto cui la voce e' servita senza altro lavoro. */
  freschezzaMs: number;
  /** Finestra dopo la freschezza in cui la voce e' servita e rinfrescata in background. */
  swrMs: number;
  /** Finestra dopo la freschezza in cui la voce puo' ancora coprire un errore. */
  staleIfErrorMs: number;
}

/** `sfondo`: rinfresco SWR, nessuno lo aspetta (il produttore puo' rinunciare prima). */
export type ModoProduzione = 'primo-piano' | 'sfondo';

export type OrigineCache = 'fresco' | 'swr' | 'prodotto' | 'agganciato';

export interface OpzioniCache<V> {
  maxVoci: number;
  maxByte: number;
  /** Millisecondi (es. `Date.now`). */
  orologio: () => number;
  /** Peso in byte di un valore; un valore oltre `maxByte` non si salva. */
  misura: (valore: V) => number;
  /** Errori dei rinfreschi in background (per il log): mai rilanciati. */
  suErroreSfondo?: (chiave: string, errore: unknown) => void;
}

/** Dopo un rinfresco fallito, per questa chiave non se ne tenta un altro prima di... */
const PAUSA_DOPO_RINFRESCO_FALLITO_MS = 10_000;

interface Voce<V> {
  valore: V;
  creata: number;
  byte: number;
}

export class CacheRisposte<V> {
  private readonly maxVoci: number;
  private readonly maxByte: number;
  private readonly orologio: () => number;
  private readonly misura: (valore: V) => number;
  private readonly suErroreSfondo: ((chiave: string, errore: unknown) => void) | undefined;

  /** Ordine di inserimento = LRU: la prima voce e' la meno usata di recente. */
  private readonly voci = new Map<string, Voce<V>>();
  private byteTotali = 0;
  /** Produzioni in primo piano in volo: chi arriva nel frattempo si aggancia. */
  private readonly inVolo = new Map<string, Promise<V>>();
  /** Rinfreschi in background in volo (le promesse non rifiutano mai). */
  private readonly rinfreschi = new Map<string, Promise<void>>();
  /** Istante dell'ultimo rinfresco fallito per chiave (solo per chiavi con una voce). */
  private readonly ultimoFallimento = new Map<string, number>();

  constructor(opzioni: OpzioniCache<V>) {
    if (!Number.isInteger(opzioni.maxVoci) || opzioni.maxVoci < 1) {
      throw new RangeError('CacheRisposte: maxVoci deve essere un intero >= 1');
    }
    if (!Number.isFinite(opzioni.maxByte) || opzioni.maxByte <= 0) {
      throw new RangeError('CacheRisposte: maxByte deve essere un numero finito > 0');
    }
    this.maxVoci = opzioni.maxVoci;
    this.maxByte = opzioni.maxByte;
    this.orologio = opzioni.orologio;
    this.misura = opzioni.misura;
    this.suErroreSfondo = opzioni.suErroreSfondo;
  }

  get dimensione(): { voci: number; byte: number } {
    return { voci: this.voci.size, byte: this.byteTotali };
  }

  /**
   * Valore per la chiave:
   * - voce fresca -> `fresco`;
   * - voce nella finestra SWR -> `swr`, e parte al massimo un rinfresco in background;
   * - altrimenti ci si aggancia alla produzione in primo piano gia' in volo
   *   (`agganciato`) o se ne avvia una (`prodotto`). Un errore di `produci` arriva a tutti
   *   quelli che la aspettano e non viene salvato.
   *
   * Un rinfresco in background non conta come produzione a cui agganciarsi: puo'
   * rinunciare (modo `sfondo`) e chi e' in primo piano deve avere una risposta vera.
   */
  async ottieni(
    chiave: string,
    politica: PoliticaCache,
    produci: (modo: ModoProduzione) => Promise<V>,
  ): Promise<{ valore: V; origine: OrigineCache }> {
    const ora = this.orologio();
    const voce = this.voci.get(chiave);
    if (voce !== undefined) {
      const eta = ora - voce.creata;
      if (eta < politica.freschezzaMs) {
        this.tocca(chiave, voce);
        return { valore: voce.valore, origine: 'fresco' };
      }
      if (eta < politica.freschezzaMs + politica.swrMs) {
        this.tocca(chiave, voce);
        this.avviaRinfresco(chiave, voce, produci, ora);
        return { valore: voce.valore, origine: 'swr' };
      }
    }

    const inVolo = this.inVolo.get(chiave);
    if (inVolo !== undefined) return { valore: await inVolo, origine: 'agganciato' };
    return { valore: await this.produciInPrimoPiano(chiave, produci), origine: 'prodotto' };
  }

  /**
   * Copia stantia per coprire un errore: la voce se esiste ed e' piu' giovane di
   * `freschezzaMs + staleIfErrorMs`, altrimenti null.
   */
  stantioPerErrore(chiave: string, politica: PoliticaCache): V | null {
    const voce = this.voci.get(chiave);
    if (voce === undefined) return null;
    if (this.orologio() - voce.creata >= politica.freschezzaMs + politica.staleIfErrorMs) return null;
    this.tocca(chiave, voce);
    return voce.valore;
  }

  /** Risolve quando tutti i rinfreschi in background (anche quelli partiti nel frattempo) sono conclusi. */
  async attendiRinfreschi(): Promise<void> {
    while (this.rinfreschi.size > 0) {
      await Promise.all([...this.rinfreschi.values()]);
    }
  }

  private produciInPrimoPiano(chiave: string, produci: (modo: ModoProduzione) => Promise<V>): Promise<V> {
    // `produci` parte in un microtask: anche se lancia in modo sincrono, la promessa e'
    // gia' registrata in `inVolo` e il `finally` la toglie.
    const promessa: Promise<V> = Promise.resolve()
      .then(() => produci('primo-piano'))
      .then((valore) => {
        this.salva(chiave, valore);
        return valore;
      })
      .finally(() => {
        if (this.inVolo.get(chiave) === promessa) this.inVolo.delete(chiave);
      });
    this.inVolo.set(chiave, promessa);
    return promessa;
  }

  /**
   * Al massimo un rinfresco per chiave, e non prima di 10 s da un rinfresco fallito.
   * Il risultato sostituisce la voce solo se e' ancora quella di partenza (o se nel
   * frattempo e' stata tolta): una produzione in primo piano piu' recente vince.
   */
  private avviaRinfresco(
    chiave: string,
    partenza: Voce<V>,
    produci: (modo: ModoProduzione) => Promise<V>,
    ora: number,
  ): void {
    if (this.rinfreschi.has(chiave) || this.inVolo.has(chiave)) return;
    const fallito = this.ultimoFallimento.get(chiave);
    if (fallito !== undefined && ora - fallito < PAUSA_DOPO_RINFRESCO_FALLITO_MS) return;

    const rinfresco: Promise<void> = Promise.resolve()
      .then(() => produci('sfondo'))
      .then((valore) => {
        const attuale = this.voci.get(chiave);
        if (attuale === undefined || attuale === partenza) this.salva(chiave, valore);
      })
      .catch((errore: unknown) => {
        this.registraFallimento(chiave, errore);
      })
      .finally(() => {
        if (this.rinfreschi.get(chiave) === rinfresco) this.rinfreschi.delete(chiave);
      });
    this.rinfreschi.set(chiave, rinfresco);
  }

  /** Mai lancia: il rinfresco in background non deve lasciare rejection non gestite. */
  private registraFallimento(chiave: string, errore: unknown): void {
    if (this.voci.has(chiave)) this.ultimoFallimento.set(chiave, this.orologio());
    if (this.suErroreSfondo === undefined) return;
    try {
      this.suErroreSfondo(chiave, errore);
    } catch {
      // il callback di log non deve poter rompere il rinfresco
    }
  }

  /** Sposta la voce in coda alla mappa: e' la piu' recente. */
  private tocca(chiave: string, voce: Voce<V>): void {
    this.voci.delete(chiave);
    this.voci.set(chiave, voce);
  }

  private rimuovi(chiave: string): void {
    const voce = this.voci.get(chiave);
    if (voce === undefined) return;
    this.voci.delete(chiave);
    this.byteTotali -= voce.byte;
    this.ultimoFallimento.delete(chiave);
  }

  /**
   * Salva un valore prodotto con successo. Sostituisce sempre la voce precedente: se il
   * nuovo valore non entra (oltre `maxByte`, o misura non valida) la vecchia viene tolta
   * comunque, perche' ormai superata.
   */
  private salva(chiave: string, valore: V): void {
    const byte = this.misura(valore);
    this.rimuovi(chiave);
    if (!Number.isFinite(byte) || byte < 0 || byte > this.maxByte) return;
    this.voci.set(chiave, { valore, creata: this.orologio(), byte });
    this.byteTotali += byte;
    // La voce appena inserita e' l'ultima: si tolgono le prime finche' i limiti tornano.
    while (this.voci.size > this.maxVoci || this.byteTotali > this.maxByte) {
      const prima = this.voci.keys().next();
      if (prima.done || prima.value === chiave) break;
      this.rimuovi(prima.value);
    }
  }
}
