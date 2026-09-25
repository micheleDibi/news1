/**
 * Testi e badge dello stato di un bando: etichette, classi e le frasi dei casi
 * limite di §4.2 (apertura annunciata, scadenza non verificata, sospensione,
 * revoca, fonte ufficiale).
 *
 * Perché in un modulo a parte: oggi le stesse tre righe di `if` sono copiate in
 * `CardBando.astro` e in `[slug].astro`, conoscono solo tre stati e chiamano
 * «In apertura» anche un bando la cui data di apertura è passata da mesi. Con
 * cinque stati e i flag di verifica le combinazioni diventano troppe per
 * tenerle allineate a mano in due file.
 *
 * Nessuna frase promette più di quello che sappiamo: quando un flag di verifica
 * manca (in F1 mancano tutti, le colonne non esistono ancora) il testo dice
 * «indicata dalla fonte», mai «verificata».
 *
 * Modulo «foglia»: nessun import impuro, nessuna lettura dell'orologio
 * (`oggi` lo passa il chiamante) e nessun `toLocaleDateString`, che dipende dal
 * fuso e dalla locale del processo.
 */
import { STATI_BANDO } from '../stato-bando';
import type { StatoBando } from '../stato-bando';
import type { FonteUfficiale } from './tipi';

export interface BadgeStato {
  readonly etichetta: string;
  readonly classi: string;
}

/**
 * Cinque stati più `sconosciuto` (stato nullo o fuori vocabolario).
 * Colori di §7.2: aperto verde, in apertura blu, chiuso grigio, sospeso ambra,
 * revocato grigio barrato. Il barrato distingue a colpo d'occhio un revocato da
 * un chiuso: due grigi identici li renderebbero indistinguibili.
 */
export const BADGE_STATO = {
  'aperto': {
    etichetta: 'Aperto',
    classi: 'bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200',
  },
  'in apertura prossimamente': {
    etichetta: 'In apertura',
    classi: 'bg-blue-100 text-blue-700 ring-1 ring-blue-200',
  },
  'chiuso': {
    etichetta: 'Chiuso',
    classi: 'bg-gray-100 text-gray-600 ring-1 ring-gray-200',
  },
  'sospeso': {
    etichetta: 'Sospeso',
    classi: 'bg-amber-100 text-amber-800 ring-1 ring-amber-200',
  },
  'revocato': {
    etichetta: 'Revocato',
    classi: 'bg-gray-100 text-gray-600 ring-1 ring-gray-300 line-through',
  },
  'sconosciuto': {
    etichetta: '—',
    classi: 'bg-gray-100 text-gray-500 ring-1 ring-gray-200',
  },
} as const satisfies Record<StatoBando | 'sconosciuto', BadgeStato>;

/** Badge di uno stato; `sconosciuto` per null o per un valore fuori vocabolario. */
export function badgeStato(stato: string | null | undefined): BadgeStato {
  for (const valido of STATI_BANDO) if (stato === valido) return BADGE_STATO[valido];
  return BADGE_STATO.sconosciuto;
}

// ---------------------------------------------------------------------------
// Date in italiano (senza Intl: la data è già civile, non un istante)
// ---------------------------------------------------------------------------

const MESI = [
  'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
  'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
] as const;

const FORMA_GIORNO = /^(\d{4})-(\d{2})-(\d{2})/;

/** `2026-10-31` → `31 ottobre 2026`; null se la stringa non è una data. */
export function giornoItaliano(valore: string | null | undefined): string | null {
  if (typeof valore !== 'string') return null;
  const trovato = FORMA_GIORNO.exec(valore.trim());
  if (trovato === null) return null;
  const mese = MESI[Number(trovato[2]) - 1];
  if (mese === undefined) return null;
  return `${Number(trovato[3])} ${mese} ${trovato[1]}`;
}

/** `23:59:00` → `23:59`; null se non è un'ora. */
export function oraItaliana(valore: string | null | undefined): string | null {
  if (typeof valore !== 'string') return null;
  const trovato = /^([01]\d|2[0-3]):([0-5]\d)/.exec(valore.trim());
  return trovato === null ? null : `${trovato[1]}:${trovato[2]}`;
}

function soloGiorno(valore: string | null | undefined): string | null {
  if (typeof valore !== 'string') return null;
  const giorno = valore.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(giorno) ? giorno : null;
}

// ---------------------------------------------------------------------------
// Sottotesto del badge
// ---------------------------------------------------------------------------

export interface CampiTestoStato {
  /** Stato **effettivo** (da `statoEffettivo`), non la colonna grezza. */
  readonly stato: StatoBando | null;
  readonly data_apertura?: string | null;
  readonly data_apertura_verificata?: boolean | null;
  readonly data_scadenza?: string | null;
  readonly ora_scadenza?: string | null;
  readonly data_scadenza_verificata?: boolean | null;
  /** YYYY-MM-DD nel calendario di Roma, fissato una volta dal chiamante. */
  readonly oggi: string;
}

function codaScadenza(verificata: boolean | null | undefined): string {
  return verificata === true
    ? ', come verificato sulla fonte ufficiale'
    : ': la data è quella indicata dalla fonte e non è stata verificata sulla pagina ufficiale';
}

/**
 * La frase sotto il badge, o null quando non c'è niente di utile da dire.
 * Ordine di precedenza identico a `statoEffettivo`: revoca e sospensione
 * vengono prima di qualunque ragionamento sulle date.
 */
export function sottotestoStato(campi: CampiTestoStato): string | null {
  const { stato } = campi;
  if (stato === 'revocato') {
    return 'Il bando è stato revocato: non è più possibile presentare domanda.';
  }
  if (stato === 'sospeso') {
    return 'Il bando è sospeso: le domande restano ferme fino a nuova comunicazione dell\'ente.';
  }

  const scadenza = soloGiorno(campi.data_scadenza);
  const apertura = soloGiorno(campi.data_apertura);

  if (stato === 'chiuso') {
    if (scadenza === null) return 'I termini per partecipare sono chiusi.';
    const giorno = giornoItaliano(scadenza);
    if (scadenza >= campi.oggi) {
      // Chiuso pur con la scadenza ancora davanti: è una chiusura anticipata.
      return `I termini sono stati chiusi prima della scadenza indicata (${giorno}).`;
    }
    return `I termini sono scaduti il ${giorno}${codaScadenza(campi.data_scadenza_verificata)}.`;
  }

  if (stato === 'in apertura prossimamente') {
    if (apertura === null) return 'La data di apertura non è stata comunicata dalla fonte.';
    const giorno = giornoItaliano(apertura);
    if (apertura > campi.oggi) {
      return campi.data_apertura_verificata === true
        ? `Apre il ${giorno}, come verificato sulla fonte ufficiale.`
        : `L'apertura è annunciata per il ${giorno}: la data non è ancora verificata sulla pagina ufficiale.`;
    }
    // Apertura annunciata e già passata: è il caso dei 14 bandi che il sito
    // mostrava «In apertura» senza spiegare perché non fossero aperti.
    return `L'apertura era annunciata per il ${giorno}: l'avvio non risulta ancora confermato sulla fonte ufficiale.`;
  }

  if (stato === 'aperto') {
    if (scadenza === null) return 'Sportello aperto: la fonte non indica una data di scadenza.';
    const ora = oraItaliana(campi.ora_scadenza);
    const quando = ora === null ? `${giornoItaliano(scadenza)}` : `${giornoItaliano(scadenza)} alle ${ora}`;
    return `Si può presentare domanda fino al ${quando}${codaScadenza(campi.data_scadenza_verificata)}.`;
  }

  return 'Lo stato di questo bando è in verifica.';
}

// ---------------------------------------------------------------------------
// Scadenza: giorni che mancano e riga della card
// ---------------------------------------------------------------------------

/**
 * Giorni di calendario da `oggi` alla scadenza, entrambe date civili di Roma:
 * 0 il giorno stesso, negativo se è passata, null senza una data leggibile.
 * `Date.parse` legge una data senza ora in UTC per specifica, quindi la
 * differenza è un multiplo esatto del giorno qualunque sia il fuso del processo.
 */
export function giorniAllaScadenza(dataScadenza: string | null | undefined, oggi: string): number | null {
  const scadenza = soloGiorno(dataScadenza);
  const riferimento = soloGiorno(oggi);
  if (scadenza === null || riferimento === null) return null;
  const giorni = Math.round((Date.parse(scadenza) - Date.parse(riferimento)) / 86_400_000);
  // `2026-10-32` passa la forma ma non è un giorno: Date.parse dà NaN.
  return Number.isFinite(giorni) ? giorni : null;
}

/** «tra 36 giorni», «scade domani», «scade oggi»; null se la scadenza è passata o manca. */
export function testoGiorniMancanti(giorni: number | null): string | null {
  if (giorni === null || !Number.isFinite(giorni) || giorni < 0) return null;
  if (giorni === 0) return 'scade oggi';
  if (giorni === 1) return 'scade domani';
  return `tra ${giorni} giorni`;
}

export interface RigaScadenza {
  /** «Scade il 31 ottobre 2026», «Scaduto il …» oppure «Scadenza: …». */
  readonly testo: string;
  /** Solo per un bando aperto: «tra 36 giorni», «scade domani», «scade oggi». */
  readonly mancano: string | null;
}

/**
 * La riga di scadenza della card: prima lo stato, poi la data. Un bando chiuso
 * prima della scadenza, o chiuso oggi a ora passata (la vista applica
 * `ora_scadenza`, che la lista non legge), non deve leggere «Scade il»; un
 * sospeso o un revocato non ha un conto alla rovescia.
 */
export function rigaScadenza(
  stato: string | null | undefined,
  dataScadenza: string | null | undefined,
  oggi: string,
): RigaScadenza | null {
  const scadenza = soloGiorno(dataScadenza);
  const giorno = giornoItaliano(scadenza);
  if (scadenza === null || giorno === null) return null;
  const futura = scadenza >= oggi;
  if (stato === 'aperto' && futura) {
    return { testo: `Scade il ${giorno}`, mancano: testoGiorniMancanti(giorniAllaScadenza(scadenza, oggi)) };
  }
  if (stato === 'in apertura prossimamente' && futura) return { testo: `Scade il ${giorno}`, mancano: null };
  if (stato === 'chiuso' && scadenza <= oggi) return { testo: `Scaduto il ${giorno}`, mancano: null };
  return { testo: `Scadenza: ${giorno}`, mancano: null };
}

/**
 * Su un bando sospeso o revocato la CTA e il conto alla rovescia spariscono:
 * invitare a candidarsi a un bando revocato è peggio che non dire nulla.
 */
export function partecipazioneAperta(stato: StatoBando | null | undefined): boolean {
  return stato !== 'sospeso' && stato !== 'revocato';
}

// ---------------------------------------------------------------------------
// Fonte ufficiale
// ---------------------------------------------------------------------------

const ETICHETTA_TIPO_FONTE = {
  ente: 'pagina dell\'ente',
  portale_pubblico: 'portale pubblico',
} as const;

/**
 * «Fonte ufficiale: comune.esempio.it (pagina dell'ente) — verificata il 3
 * settembre 2026 · controllata il 20 settembre 2026», oppure «Fonte ufficiale
 * in verifica» finché il resolver non ha concluso. In F1 è sempre il secondo
 * caso: le colonne non esistono ancora e il chiamante passa `null`.
 */
export function testoFonteUfficiale(
  fonte: FonteUfficiale | null | undefined,
  controllatoIl?: string | null,
): string {
  const controllo = giornoItaliano(soloGiorno(controllatoIl));
  const coda = controllo === null ? '' : ` · controllata il ${controllo}`;
  if (!fonte || fonte.stato !== 'trovata' || typeof fonte.host !== 'string' || fonte.host === '') {
    return `Fonte ufficiale in verifica${coda}`;
  }
  const tipo = fonte.e_atto === true
    ? 'atto'
    : (fonte.tipo === null || fonte.tipo === undefined ? null : ETICHETTA_TIPO_FONTE[fonte.tipo]);
  const qualifica = tipo === null ? '' : ` (${tipo})`;
  const verifica = giornoItaliano(soloGiorno(fonte.verificata_il));
  const quando = verifica === null ? '' : ` — verificata il ${verifica}`;
  return `Fonte ufficiale: ${fonte.host}${qualifica}${quando}${coda}`;
}

// ---------------------------------------------------------------------------
// Opzioni del filtro `?stato=` (chip delle liste)
// ---------------------------------------------------------------------------

export interface OpzioneStato {
  readonly value: StatoBando;
  readonly label: string;
}

const OPZIONI_BASE: readonly OpzioneStato[] = [
  { value: 'aperto', label: BADGE_STATO.aperto.etichetta },
  { value: 'in apertura prossimamente', label: BADGE_STATO['in apertura prossimamente'].etichetta },
  { value: 'chiuso', label: BADGE_STATO.chiuso.etichetta },
];

const OPZIONI_ESTESE: readonly OpzioneStato[] = [
  { value: 'sospeso', label: BADGE_STATO.sospeso.etichetta },
  { value: 'revocato', label: BADGE_STATO.revocato.etichetta },
];

/**
 * I chip che la lista mostra. `sospeso` e `revocato` compaiono solo quando il
 * DB può contenerli: prima della migrazione 06 il CHECK ne ammette tre, e un
 * chip che restituisce sempre zero risultati è peggio di un chip assente.
 */
export function opzioniStato(estesi: boolean): OpzioneStato[] {
  return estesi ? [...OPZIONI_BASE, ...OPZIONI_ESTESE] : [...OPZIONI_BASE];
}
