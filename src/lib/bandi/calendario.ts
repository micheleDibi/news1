/**
 * Il «Calendario» della scheda di un bando e la barra di avanzamento del
 * pannello Partecipazione, come nel design «Bandi Redesign» (`timeline()` del
 * mock): una linea dalla pubblicazione alla scadenza, il segno di oggi e,
 * se c'e', l'apertura.
 *
 * La pubblicazione manca sul ~92% dei bandi: in quel caso la linea parte
 * dall'apertura (etichetta «Apertura»). Senza nessuna delle due, o con una
 * scadenza che non viene dopo l'inizio, calendario e barra non ci sono.
 *
 * Gli «sportelli» del mock non hanno un dato a DB: non si rendono.
 *
 * Posizioni e larghezze sono percentuali calcolate qui e finiscono in
 * `style="left:…"`; solo il `translateX` e' uno di tre valori fissi.
 *
 * Modulo «foglia»: `oggi` lo passa il chiamante (data civile di Roma).
 */
import { giornoItaliano } from './testi-stato';

const MESI_BREVI = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'] as const;
const FORMA_GIORNO = /^(\d{4})-(\d{2})-(\d{2})/;

/** Spostamento orizzontale di un'etichetta: agli estremi non esce dalla linea. */
export type Spostamento = '0%' | '-50%' | '-100%';

export interface Tacca {
  /** Posizione orizzontale, es. «37.52%». */
  x: string;
  tx: Spostamento;
  etichetta: string;
  data: string;
}

export interface Calendario {
  sopra: Tacca[];
  sotto: Tacca[];
  /** Posizioni dei pallini sulla linea. */
  punti: string[];
  oggiX: string;
  oggiTx: Spostamento;
  /** «Oggi · 25 set». */
  oggiEtichetta: string;
  /** «Mancano 36 giorni alla scadenza» oppure «Oggi è il 25 settembre 2026». */
  nota: string;
  /** Percentuale gia' trascorsa fra inizio e scadenza, es. «43.1%». */
  trascorso: string;
}

export interface DatiCalendario {
  stato: string | null | undefined;
  pubblicazione: string | null | undefined;
  apertura: string | null | undefined;
  scadenza: string | null | undefined;
  oggi: string;
}

function giorno(valore: string | null | undefined): string | null {
  const m = typeof valore === 'string' ? FORMA_GIORNO.exec(valore) : null;
  if (!m) return null;
  const iso = `${m[1]}-${m[2]}-${m[3]}`;
  return Number.isFinite(Date.parse(iso)) ? iso : null;
}

/** Giorni dall'epoca: `Date.parse` legge una data senza ora in UTC per specifica. */
const inGiorni = (iso: string): number => Date.parse(iso) / 86_400_000;

/** `2026-09-25` → «25 set». */
export function dataBreve(iso: string): string {
  const m = FORMA_GIORNO.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MESI_BREVI[Number(m[2]) - 1]}`;
}

const spostamento = (v: number): Spostamento => (v < 7 ? '0%' : v > 93 ? '-100%' : '-50%');
const percento = (v: number): string => `${v.toFixed(2)}%`;

/** Nota a destra del titolo: quanto manca per un aperto, altrimenti la data di oggi. */
function notaCalendario(stato: string | null | undefined, giorni: number, oggi: string): string {
  if (stato === 'aperto' && giorni >= 0) {
    if (giorni === 0) return 'Scade oggi';
    if (giorni === 1) return 'Manca 1 giorno alla scadenza';
    return `Mancano ${giorni} giorni alla scadenza`;
  }
  return `Oggi è il ${giornoItaliano(oggi) ?? oggi}`;
}

/** Il calendario, o null se mancano le date per disegnarlo. */
export function calendario(d: DatiCalendario): Calendario | null {
  const fine = giorno(d.scadenza);
  const pubblicazione = giorno(d.pubblicazione);
  const apertura = giorno(d.apertura);
  const oggi = giorno(d.oggi);
  const inizio = pubblicazione ?? apertura;
  if (!fine || !inizio || !oggi) return null;

  const durata = inGiorni(fine) - inGiorni(inizio);
  if (!(durata > 0)) return null;

  const x = (s: string): number => Math.max(0, Math.min(100, ((inGiorni(s) - inGiorni(inizio)) / durata) * 100));

  const sopra: Tacca[] = [
    { x: percento(0), tx: '0%', etichetta: pubblicazione ? 'Pubblicazione' : 'Apertura', data: dataBreve(inizio) },
    { x: percento(100), tx: '-100%', etichetta: 'Scadenza', data: dataBreve(fine) },
  ];
  const sotto: Tacca[] = [];
  const punti = [percento(0), percento(100)];
  if (apertura && apertura !== inizio) {
    const v = x(apertura);
    sotto.push({ x: percento(v), tx: spostamento(v), etichetta: 'Apertura', data: dataBreve(apertura) });
    punti.push(percento(v));
  }

  const vOggi = x(oggi);
  const giorniAllaFine = Math.round(inGiorni(fine) - inGiorni(oggi));
  return {
    sopra,
    sotto,
    punti,
    oggiX: percento(vOggi),
    oggiTx: spostamento(vOggi),
    oggiEtichetta: `Oggi · ${dataBreve(oggi)}`,
    nota: notaCalendario(d.stato, giorniAllaFine, oggi),
    trascorso: `${Math.max(0, Math.min(100, ((inGiorni(oggi) - inGiorni(inizio)) / durata) * 100)).toFixed(1)}%`,
  };
}
