/**
 * Cursore opaco della paginazione keyset.
 *
 * base64url di {"v":1,"r":<risorsa>,"f":<hash filtri>,"k":[<valore grezzo>,<id>]}.
 * - `k[0]` e' il valore ESATTO della colonna di ordinamento come lo restituisce
 *   PostgREST (microsecondi compresi): il confronto keyset avviene sul DB, senza
 *   conversioni di fuso.
 * - `f` lega il cursore ai filtri (cambiare `limit` e' lecito, cambiare i filtri
 *   no: 400 invece di paginare in silenzio su un altro insieme).
 * Niente firma: il cursore non conferisce privilegi, uno forgiato ma valido equivale
 * a un `until` lecito. Il valore arriva a PostgREST solo fra doppi apici e dopo la
 * regex qui sotto, che esclude `" , ( ) \`.
 */
import { createHash } from 'node:crypto';
import { ID_MASSIMO_INT4, LUNGHEZZA_MASSIMA_CURSORE } from './costanti';
import { ErroreDati } from './errori';
import { queryCanonica, type FiltriElenco } from './parametri';
import { analizzaTimestamp } from './tempo';
import type { Risorsa } from './contratto';

const VERSIONE = 1;
const FORMA_CHIAVE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$/;
const BASE64URL = /^[A-Za-z0-9_-]+$/;

/** Id massimo ammesso per la risorsa (bando.id e' int4). */
export function idMassimo(risorsa: Risorsa): number {
  return risorsa === 'bandi' ? ID_MASSIMO_INT4 : Number.MAX_SAFE_INTEGER;
}

export interface PosizioneCursore {
  grezzo: string;
  id: number;
}

/** Primi 8 caratteri esadecimali dello SHA-256 di risorsa + filtri canonici (senza limit e cursor). */
export function hashFiltri(risorsa: Risorsa, filtri: FiltriElenco): string {
  const canonica = queryCanonica(risorsa, filtri, { conLimite: false, conCursore: false }).toString();
  return createHash('sha256').update(`${risorsa}|${canonica}`).digest('hex').slice(0, 8);
}

/** Un valore di ordinamento ammesso nel cursore: timestamp valido, con o senza offset. */
export function chiaveCursoreValida(valore: string): boolean {
  return FORMA_CHIAVE.test(valore) && analizzaTimestamp(valore) !== null;
}

/**
 * Codifica il cursore per links.next. Se il valore di ordinamento non e' accettabile
 * lancia ErroreDati: il server non emette mai un cursore che poi rifiuterebbe.
 */
export function codificaCursore(risorsa: Risorsa, filtri: FiltriElenco, grezzo: string, id: number): string {
  if (!chiaveCursoreValida(grezzo) || !Number.isSafeInteger(id) || id <= 0 || id > idMassimo(risorsa)) {
    throw new ErroreDati('programmazione', null, 'chiave del cursore non codificabile');
  }
  const json = JSON.stringify({ v: VERSIONE, r: risorsa, f: hashFiltri(risorsa, filtri), k: [grezzo, id] });
  const cursore = Buffer.from(json, 'utf8').toString('base64url');
  if (cursore.length > LUNGHEZZA_MASSIMA_CURSORE) {
    throw new ErroreDati('programmazione', null, 'cursore troppo lungo');
  }
  return cursore;
}

/** Decodifica rigorosa; null per qualunque anomalia (-> 400 invalid-cursor). */
export function decodificaCursore(risorsa: Risorsa, filtri: FiltriElenco, cursore: string): PosizioneCursore | null {
  if (cursore.length > LUNGHEZZA_MASSIMA_CURSORE || !BASE64URL.test(cursore)) return null;
  let dati: unknown;
  try {
    dati = JSON.parse(Buffer.from(cursore, 'base64url').toString('utf8'));
  } catch {
    return null;
  }
  if (typeof dati !== 'object' || dati === null || Array.isArray(dati)) return null;
  const chiavi = Object.keys(dati);
  if (chiavi.length !== 4 || !['v', 'r', 'f', 'k'].every((c) => chiavi.includes(c))) return null;
  const { v, r, f, k } = dati as { v: unknown; r: unknown; f: unknown; k: unknown };
  if (v !== VERSIONE || r !== risorsa || f !== hashFiltri(risorsa, filtri)) return null;
  if (!Array.isArray(k) || k.length !== 2) return null;
  const [grezzo, id] = k as unknown[];
  if (typeof grezzo !== 'string' || !chiaveCursoreValida(grezzo)) return null;
  if (typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0 || id > idMassimo(risorsa)) return null;
  return { grezzo, id };
}
