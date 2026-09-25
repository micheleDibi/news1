/**
 * Aspetto degli stati di un bando nel design «Bandi Redesign»: le pillole con il
 * pallino di lista, griglia e scheda, e la palette «urgente» (aperto, scadenza
 * fra 0 e 15 giorni).
 *
 * Classi complete e non frammenti da comporre: Tailwind le trova solo se sono
 * scritte per intero nel sorgente. I colori sono quelli del mock; sospeso e
 * revocato il mock non li ha, quindi il sospeso riusa la palette «urgente» e il
 * revocato quella del chiuso, barrato come in `BADGE_STATO`.
 *
 * `BADGE_STATO` di testi-stato.ts resta com'è: lo coprono i test e lo usano
 * altre superfici.
 *
 * Modulo «foglia»: nessun import impuro, nessuna lettura dell'orologio.
 */
import { STATI_BANDO } from '../stato-bando';
import type { StatoBando } from '../stato-bando';

export interface AspettoStato {
  readonly etichetta: string;
  /** Sfondo e colore del testo della pillola. */
  readonly pillola: string;
  /** Colore del pallino dentro la pillola. */
  readonly punto: string;
  /** Barra alta 4px in cima alla card in griglia (fuori dalla palette urgente). */
  readonly barra: string;
  /** Classi in piu' sull'etichetta (il barrato del revocato). */
  readonly extraEtichetta: string;
}

export const ASPETTO_STATO = {
  'aperto': {
    etichetta: 'Aperto',
    pillola: 'bg-[#e2f4ea] text-[#0b6b45]',
    punto: 'bg-[#12a36a]',
    barra: 'bg-[#12a36a]',
    extraEtichetta: '',
  },
  'in apertura prossimamente': {
    etichetta: 'In apertura',
    pillola: 'bg-[#e5eefa] text-[#0b4f9c]',
    punto: 'bg-[#2f7de1]',
    barra: 'bg-[#2f7de1]',
    extraEtichetta: '',
  },
  'chiuso': {
    etichetta: 'Chiuso',
    pillola: 'bg-[#eef0f3] text-[#4b5565]',
    punto: 'bg-[#9aa3b2]',
    barra: 'bg-[#9aa3b2]',
    extraEtichetta: '',
  },
  'sospeso': {
    etichetta: 'Sospeso',
    pillola: 'bg-[#fff1dc] text-[#7a3d00]',
    punto: 'bg-[#e07b00]',
    barra: 'bg-[#e07b00]',
    extraEtichetta: '',
  },
  'revocato': {
    etichetta: 'Revocato',
    pillola: 'bg-[#eef0f3] text-[#4b5565]',
    punto: 'bg-[#9aa3b2]',
    barra: 'bg-[#9aa3b2]',
    extraEtichetta: 'line-through',
  },
} as const satisfies Record<StatoBando, AspettoStato>;

/** Barra della card in griglia per uno stato sconosciuto: nessuna pillola, barra neutra. */
export const BARRA_SCONOSCIUTO = 'bg-[#d5dbe4]';

/** Aspetto di uno stato; null per null o per un valore fuori vocabolario (niente pillola). */
export function aspettoStato(stato: string | null | undefined): AspettoStato | null {
  for (const valido of STATI_BANDO) if (stato === valido) return ASPETTO_STATO[valido];
  return null;
}

/**
 * Palette della colonna data, della pillola dei giorni e della barra in
 * griglia: «urgente» per un aperto che scade entro 15 giorni, normale altrimenti.
 */
export const PALETTE_SCADENZA = {
  urgente: {
    sfondoData: 'bg-[#fff5e6]',
    giorno: 'text-[#9a4d00]',
    pillolaGiorni: 'bg-[#ffe3bf] text-[#7a3d00]',
    barra: 'bg-[#e07b00]',
  },
  normale: {
    sfondoData: 'bg-[#f8fafc]',
    giorno: 'text-[#0a2244]',
    pillolaGiorni: 'bg-[#e8f0fb] text-[#0a3d7a]',
    barra: '',
  },
} as const;

/** Giorni entro cui un bando aperto e' «in scadenza»: tessera, filtro e colori. */
export const GIORNI_IN_SCADENZA = 15;

/** true per un bando aperto la cui scadenza cade fra oggi e oggi+15 (estremi compresi). */
export function inScadenza(stato: string | null | undefined, giorni: number | null): boolean {
  return stato === 'aperto' && giorni !== null && giorni >= 0 && giorni <= GIORNI_IN_SCADENZA;
}
