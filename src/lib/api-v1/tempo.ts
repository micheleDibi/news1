/**
 * Date e istanti dell'API /api/v1: tutto esplicito sul fuso, niente ora locale.
 *
 * Il processo Node puo' girare in qualunque fuso (in produzione e' ignoto): qui non
 * si usano mai `new Date(stringaSenzaFuso)`, i getter locali di Date o
 * `toLocale*`. Le conversioni verso Europe/Rome passano da Intl con timeZone
 * esplicito. I test girano con TZ=Asia/Kathmandu per smascherare qualunque
 * dipendenza dall'ora locale.
 */
import { SCARTO_MAX_SCADENZA_MS } from './costanti';

const MS_ORA = 60 * 60 * 1000;
const MS_GIORNO = 24 * MS_ORA;

/** Parti di un timestamp analizzato. `frazione` sono le cifre dopo il punto ('' se assenti). */
export interface PartiTimestamp {
  anno: number;
  mese: number;
  giorno: number;
  ore: number;
  minuti: number;
  secondi: number;
  frazione: string;
  /** Offset in minuti rispetto a UTC, null se la stringa non ne ha. */
  offsetMinuti: number | null;
}

const FORMA_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?$/;

function giorniNelMese(anno: number, mese: number): number {
  if (mese === 2) {
    const bisestile = (anno % 4 === 0 && anno % 100 !== 0) || anno % 400 === 0;
    return bisestile ? 29 : 28;
  }
  return [4, 6, 9, 11].includes(mese) ? 30 : 31;
}

/** Calendario e orologio validi (anno 1-9999, niente 24:00 ne' secondi intercalari). */
export function timestampValido(
  anno: number, mese: number, giorno: number, ore = 0, minuti = 0, secondi = 0,
): boolean {
  if (!Number.isInteger(anno) || anno < 1 || anno > 9999) return false;
  if (!Number.isInteger(mese) || mese < 1 || mese > 12) return false;
  if (!Number.isInteger(giorno) || giorno < 1 || giorno > giorniNelMese(anno, mese)) return false;
  if (!Number.isInteger(ore) || ore < 0 || ore > 23) return false;
  if (!Number.isInteger(minuti) || minuti < 0 || minuti > 59) return false;
  if (!Number.isInteger(secondi) || secondi < 0 || secondi > 59) return false;
  return true;
}

function leggiOffset(testo: string): number | null {
  if (testo === 'Z') return 0;
  const segno = testo[0] === '-' ? -1 : 1;
  const ore = Number(testo.slice(1, 3));
  const minuti = Number(testo.slice(4, 6));
  if (ore > 14 || minuti > 59) return null;
  return segno * (ore * 60 + minuti);
}

/** Analizza un timestamp come lo restituisce PostgREST (con o senza offset). null se non valido. */
export function analizzaTimestamp(grezzo: string): PartiTimestamp | null {
  const m = FORMA_TIMESTAMP.exec(grezzo);
  if (!m) return null;
  const [anno, mese, giorno, ore, minuti, secondi] = m.slice(1, 7).map(Number);
  if (!timestampValido(anno, mese, giorno, ore, minuti, secondi)) return null;
  let offsetMinuti: number | null = null;
  if (m[8] !== undefined) {
    offsetMinuti = leggiOffset(m[8]);
    if (offsetMinuti === null) return null;
  }
  return { anno, mese, giorno, ore, minuti, secondi, frazione: m[7] ?? '', offsetMinuti };
}

/** Millisecondi della parte frazionaria (troncati). */
function millisecondi(frazione: string): number {
  return frazione === '' ? 0 : Number((frazione + '00').slice(0, 3));
}

/** Istante del muro UTC (Date.UTC accetta anche anni < 100 solo con setUTCFullYear). */
function muroUtcInMs(anno: number, mese: number, giorno: number, ore: number, minuti: number, secondi: number): number {
  const d = new Date(Date.UTC(2000, 0, 1, ore, minuti, secondi));
  d.setUTCFullYear(anno, mese - 1, giorno);
  return d.getTime();
}

// ---------------------------------------------------------------------------
// Europe/Rome
// ---------------------------------------------------------------------------

const FORMATO_ROMA = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Europe/Rome',
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

interface MuroRoma {
  anno: number;
  mese: number;
  giorno: number;
  ore: number;
  minuti: number;
  secondi: number;
}

/** Orologio da muro di Roma per un istante. */
function muroRomaDi(ms: number): MuroRoma {
  const parti = new Map(FORMATO_ROMA.formatToParts(new Date(ms)).map((p) => [p.type, p.value]));
  return {
    anno: Number(parti.get('year')),
    mese: Number(parti.get('month')),
    giorno: Number(parti.get('day')),
    ore: Number(parti.get('hour')),
    minuti: Number(parti.get('minute')),
    secondi: Number(parti.get('second')),
  };
}

/** Offset di Roma in minuti per un istante (60 o 120). */
export function offsetRomaMinuti(ms: number): number {
  const secondoPieno = Math.floor(ms / 1000) * 1000;
  const muro = muroRomaDi(secondoPieno);
  const comeUtc = muroUtcInMs(muro.anno, muro.mese, muro.giorno, muro.ore, muro.minuti, muro.secondi);
  return Math.round((comeUtc - secondoPieno) / 60000);
}

/**
 * Istante dell'orologio da muro di Roma. Ora inesistente (ultima domenica di
 * marzo, 02:00-02:59) -> +01:00; ora ambigua (ultima domenica di ottobre) -> +02:00.
 */
export function istanteDaMuroRoma(
  anno: number, mese: number, giorno: number, ore = 0, minuti = 0, secondi = 0,
): number {
  const comeUtc = muroUtcInMs(anno, mese, giorno, ore, minuti, secondi);
  for (const offset of [2 * MS_ORA, MS_ORA]) {
    const candidato = comeUtc - offset;
    const muro = muroRomaDi(candidato);
    if (
      muro.anno === anno && muro.mese === mese && muro.giorno === giorno &&
      muro.ore === ore && muro.minuti === minuti && muro.secondi === secondi
    ) {
      return candidato;
    }
  }
  return comeUtc - MS_ORA;
}

const due = (n: number) => String(n).padStart(2, '0');
const quattro = (n: number) => String(n).padStart(4, '0');

function testoOffset(minuti: number, conDuePunti: boolean): string {
  const segno = minuti < 0 ? '-' : '+';
  const assoluto = Math.abs(minuti);
  return `${segno}${due(Math.floor(assoluto / 60))}${conDuePunti ? ':' : ''}${due(assoluto % 60)}`;
}

/** RFC 3339 con l'offset di Roma valido in quell'istante, troncato al secondo. */
export function rfc3339Roma(ms: number): string {
  const secondoPieno = Math.floor(ms / 1000) * 1000;
  const m = muroRomaDi(secondoPieno);
  const offset = offsetRomaMinuti(secondoPieno);
  return `${quattro(m.anno)}-${due(m.mese)}-${due(m.giorno)}T${due(m.ore)}:${due(m.minuti)}:${due(m.secondi)}${testoOffset(offset, true)}`;
}

const GIORNI_SETTIMANA = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MESI_INGLESI = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Data RFC 822 (RSS 2.0) con l'offset di Roma: "Mon, 21 Sep 2026 09:18:28 +0200". */
export function rfc822(ms: number): string {
  const secondoPieno = Math.floor(ms / 1000) * 1000;
  const m = muroRomaDi(secondoPieno);
  const offset = offsetRomaMinuti(secondoPieno);
  const giornoSettimana = new Date(muroUtcInMs(m.anno, m.mese, m.giorno, 0, 0, 0)).getUTCDay();
  return `${GIORNI_SETTIMANA[giornoSettimana]}, ${due(m.giorno)} ${MESI_INGLESI[m.mese - 1]} ${quattro(m.anno)} ` +
    `${due(m.ore)}:${due(m.minuti)}:${due(m.secondi)} ${testoOffset(offset, false)}`;
}

/** Giorno del calendario di Roma (YYYY-MM-DD). */
export function giornoRoma(ms: number): string {
  const m = muroRomaDi(ms);
  return `${quattro(m.anno)}-${due(m.mese)}-${due(m.giorno)}`;
}

export function oggiRoma(adessoMs: number): string {
  return giornoRoma(adessoMs);
}

/** Orologio da muro di Roma senza fuso (YYYY-MM-DDTHH:MM:SS), per le colonne `timestamp` in ora di Roma. */
export function muroRoma(ms: number): string {
  const m = muroRomaDi(ms);
  return `${quattro(m.anno)}-${due(m.mese)}-${due(m.giorno)}T${due(m.ore)}:${due(m.minuti)}:${due(m.secondi)}`;
}

/** Orologio da muro UTC senza fuso (YYYY-MM-DDTHH:MM:SS), per le colonne `timestamp` scritte in UTC. */
export function muroUtc(ms: number): string {
  return new Date(Math.floor(ms / 1000) * 1000).toISOString().slice(0, 19);
}

/** Giorno UTC (YYYY-MM-DD): la convenzione del sito per `data_scadenza` (slice(0,10) su +00:00). */
export function giornoUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

const FORMA_GIORNO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Una data di calendario valida (YYYY-MM-DD) o null. */
export function giornoValido(valore: unknown): string | null {
  if (typeof valore !== 'string') return null;
  const m = FORMA_GIORNO.exec(valore);
  if (!m) return null;
  return timestampValido(Number(m[1]), Number(m[2]), Number(m[3])) ? valore : null;
}

/** 00:00 di Roma del giorno indicato. */
export function mezzanotteRoma(giorno: string): number {
  const [anno, mese, g] = giorno.split('-').map(Number);
  return istanteDaMuroRoma(anno, mese, g, 0, 0, 0);
}

export function giornoSuccessivo(giorno: string): string {
  const [anno, mese, g] = giorno.split('-').map(Number);
  const d = new Date(muroUtcInMs(anno, mese, g, 0, 0, 0) + MS_GIORNO);
  return d.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Colonne del DB
// ---------------------------------------------------------------------------

export type FusoPresunto = 'offset' | 'UTC' | 'Europe/Rome';

/**
 * EURISTICA TEMPORANEA per articles.published_at (timestamp SENZA fuso, valori misti).
 * Offset presente -> si usa; 0-3 cifre frazionarie (anche 0) -> UTC (editor attuale,
 * toISOString); 4-6 -> Europe/Rome (backend Python, datetime.now(ITALY_TZ)).
 * Formato non valido -> null (riga scartata, log).
 * ERRORE NOTO: ~436 articoli scritti dall'editor precedente (circa 05-12/2025) sono in
 * ora di Roma con millisecondi e risultano spostati avanti di 1-2 h.
 * DA RIMUOVERE quando la colonna sara' timestamptz: il ramo "offset" la rende inerte.
 */
export function fusoPresuntoPublishedAt(grezzo: string): FusoPresunto | null {
  const parti = analizzaTimestamp(grezzo);
  if (!parti) return null;
  if (parti.offsetMinuti !== null) return 'offset';
  return parti.frazione.length <= 3 ? 'UTC' : 'Europe/Rome';
}

function istanteDaParti(parti: PartiTimestamp, fusoSenzaOffset: 'UTC' | 'Europe/Rome'): number {
  const ms = millisecondi(parti.frazione);
  if (parti.offsetMinuti !== null) {
    return muroUtcInMs(parti.anno, parti.mese, parti.giorno, parti.ore, parti.minuti, parti.secondi) -
      parti.offsetMinuti * 60000 + ms;
  }
  if (fusoSenzaOffset === 'UTC') {
    return muroUtcInMs(parti.anno, parti.mese, parti.giorno, parti.ore, parti.minuti, parti.secondi) + ms;
  }
  return istanteDaMuroRoma(parti.anno, parti.mese, parti.giorno, parti.ore, parti.minuti, parti.secondi) + ms;
}

/** Istante (ms) di articles.published_at secondo l'euristica; null se il valore non e' riconosciuto. */
export function istantePublishedAt(grezzo: unknown): number | null {
  if (typeof grezzo !== 'string') return null;
  const parti = analizzaTimestamp(grezzo);
  if (!parti) return null;
  return istanteDaParti(parti, parti.frazione.length <= 3 ? 'UTC' : 'Europe/Rome');
}

/** interpelli.interpello_date: timestamp senza fuso, giorno della fonte -> muro di Roma. */
export function istanteInterpello(grezzo: unknown): number | null {
  if (typeof grezzo !== 'string') return null;
  const parti = analizzaTimestamp(grezzo);
  return parti ? istanteDaParti(parti, 'Europe/Rome') : null;
}

/** Colonne timestamptz (PostgREST le restituisce con +00:00); senza offset: UTC (sessione in UTC). */
export function istanteTimestamptz(grezzo: unknown): number | null {
  if (typeof grezzo !== 'string') return null;
  const parti = analizzaTimestamp(grezzo);
  return parti ? istanteDaParti(parti, 'UTC') : null;
}

/**
 * Una scadenza e' plausibile se non supera di oltre 8 anni la data di riferimento
 * (pubblicazione per la selezione, inserimento per i bandi). Senza riferimento: plausibile.
 */
export function scadenzaPlausibile(scadenzaMs: number, ancoraMs: number | null): boolean {
  if (ancoraMs === null) return true;
  return scadenzaMs - ancoraMs <= SCARTO_MAX_SCADENZA_MS;
}

// ---------------------------------------------------------------------------
// Parametri istante in ingresso (since, until, updated_since)
// ---------------------------------------------------------------------------

/** RFC 3339 con offset obbligatorio; lo spazio al posto di '+' (query non codificata) e' tollerato. */
const FORMA_PARAMETRO = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?([Zz]|[+\- ]\d{2}:\d{2})$/;

export type RuoloIstante = 'inizio' | 'fine';

/**
 * Legge un parametro istante. Accetta RFC 3339 con offset oppure una data YYYY-MM-DD
 * del calendario di Roma (inizio -> 00:00 di quel giorno; fine -> 00:00 del giorno
 * dopo, perche' `until` e' esclusivo). Le frazioni si troncano al secondo. Anni
 * ammessi 2000-2100. Restituisce null se il valore non e' valido.
 */
export function leggiParametroIstante(valore: string, ruolo: RuoloIstante): number | null {
  const giorno = FORMA_GIORNO.exec(valore);
  if (giorno) {
    const anno = Number(giorno[1]);
    if (anno < 2000 || anno > 2100 || !giornoValido(valore)) return null;
    return ruolo === 'inizio' ? mezzanotteRoma(valore) : mezzanotteRoma(giornoSuccessivo(valore));
  }
  const m = FORMA_PARAMETRO.exec(valore);
  if (!m) return null;
  const [anno, mese, g, ore, minuti, secondi] = m.slice(1, 7).map(Number);
  if (anno < 2000 || anno > 2100 || !timestampValido(anno, mese, g, ore, minuti, secondi)) return null;
  const offsetTesto = m[8].toUpperCase() === 'Z' ? 'Z' : m[8].replace(' ', '+');
  const offset = leggiOffset(offsetTesto);
  if (offset === null) return null;
  return muroUtcInMs(anno, mese, g, ore, minuti, secondi) - offset * 60000;
}
