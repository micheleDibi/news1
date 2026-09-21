/**
 * Semaforo globale per le produzioni in cache miss (piano §8.1): N slot, coda FIFO
 * limitata, attesa massima. Protegge il database, non il singolo client (a quello pensa
 * il limitatore).
 *
 * Nessun timer a riposo: l'unico timer e' quello dell'attesa di un elemento in coda, e
 * viene cancellato quando l'elemento e' servito o scade. Nessun timer all'import.
 */

export type MotivoSaturazione = 'coda-piena' | 'attesa-scaduta';

/** Il semaforo non ha concesso lo slot: il gestore risponde 503 con `Retry-After`. */
export class SemaforoSaturo extends Error {
  readonly motivo: MotivoSaturazione;

  constructor(motivo: MotivoSaturazione) {
    super(motivo === 'coda-piena' ? 'Semaforo saturo: coda piena' : 'Semaforo saturo: attesa scaduta');
    this.name = 'SemaforoSaturo';
    this.motivo = motivo;
  }
}

export interface OpzioniSemaforo {
  /** Produzioni contemporanee ammesse (>= 1). */
  slot: number;
  /** Richieste che possono attendere uno slot (>= 0); oltre si rifiuta subito. */
  coda: number;
  /** Attesa massima in coda, in millisecondi (>= 0). */
  attesaMs: number;
}

interface InAttesa {
  concedi: (rilascio: () => void) => void;
  annullaTimer: () => void;
}

export class Semaforo {
  private readonly slot: number;
  private readonly coda: number;
  private readonly attesaMs: number;
  private occupati = 0;
  /** FIFO. Invariante: non e' vuota solo se tutti gli slot sono occupati. */
  private readonly attesa: InAttesa[] = [];

  constructor(opzioni: OpzioniSemaforo) {
    if (!Number.isInteger(opzioni.slot) || opzioni.slot < 1) {
      throw new RangeError('Semaforo: slot deve essere un intero >= 1');
    }
    if (!Number.isInteger(opzioni.coda) || opzioni.coda < 0) {
      throw new RangeError('Semaforo: coda deve essere un intero >= 0');
    }
    if (!Number.isFinite(opzioni.attesaMs) || opzioni.attesaMs < 0) {
      throw new RangeError('Semaforo: attesaMs deve essere un numero finito >= 0');
    }
    this.slot = opzioni.slot;
    this.coda = opzioni.coda;
    this.attesaMs = opzioni.attesaMs;
  }

  /** Slot occupati in questo momento. */
  get inUso(): number {
    return this.occupati;
  }

  /** Richieste in attesa di uno slot. */
  get inCoda(): number {
    return this.attesa.length;
  }

  /**
   * Ottiene uno slot; la funzione restituita lo rilascia (idempotente: chiamarla di
   * nuovo non fa nulla). Va chiamata in un `finally`. Rifiuta con `SemaforoSaturo`
   * se la coda e' piena o se l'attesa supera `attesaMs`.
   */
  acquisisci(): Promise<() => void> {
    const subito = this.provaAcquisire();
    if (subito !== null) return Promise.resolve(subito);
    if (this.attesa.length >= this.coda) return Promise.reject(new SemaforoSaturo('coda-piena'));

    return new Promise<() => void>((risolvi, rifiuta) => {
      const elemento: InAttesa = { concedi: risolvi, annullaTimer: () => undefined };
      const timer = setTimeout(() => {
        const indice = this.attesa.indexOf(elemento);
        if (indice < 0) return;
        this.attesa.splice(indice, 1);
        rifiuta(new SemaforoSaturo('attesa-scaduta'));
      }, this.attesaMs);
      elemento.annullaTimer = () => clearTimeout(timer);
      this.attesa.push(elemento);
    });
  }

  /**
   * Versione non bloccante: il rilascio se c'e' uno slot libero e nessuno in coda
   * (chi aspetta ha la precedenza), altrimenti null.
   */
  provaAcquisire(): (() => void) | null {
    if (this.occupati >= this.slot || this.attesa.length > 0) return null;
    this.occupati++;
    return this.creaRilascio();
  }

  private creaRilascio(): () => void {
    let rilasciato = false;
    return () => {
      if (rilasciato) return;
      rilasciato = true;
      this.occupati--;
      this.servi();
    };
  }

  /** Passa gli slot liberi ai primi in coda, cancellando il loro timer d'attesa. */
  private servi(): void {
    while (this.occupati < this.slot && this.attesa.length > 0) {
      const elemento = this.attesa.shift();
      if (elemento === undefined) return;
      elemento.annullaTimer();
      this.occupati++;
      elemento.concedi(this.creaRilascio());
    }
  }
}
