/**
 * Il filtro `?stato=` delle liste: quali valori si accettano e in che
 * condizione PostgREST si traducono.
 *
 * Due difetti da chiudere.
 *
 * 1. **Quali valori accettare.** `STATI_BANDO` è a cinque valori, ma finché la
 *    migrazione 06 non estende il CHECK la colonna ne ammette tre: un
 *    `?stato=sospeso` arriverebbe a PostgREST e tornerebbe una lista vuota,
 *    indistinguibile da «nessun bando sospeso». Il flag
 *    `PUBLIC_BANDI_STATI_ESTESI` (default: assente, cioè no) decide, e un
 *    valore non ammesso viene semplicemente ignorato come oggi.
 *
 * 2. **`chiuso` catturava troppo.** La condizione era
 *    `or(stato_bando.eq.chiuso, data_scadenza.lt.oggi)`: un bando sospeso o
 *    revocato con la scadenza passata finiva fra i chiusi. La garanzia A3 dice
 *    che un sospeso non si chiude mai d'ufficio, e questa lista lo faceva
 *    apparire chiuso. Ora il ramo `chiuso` esclude esplicitamente i due stati.
 *
 *    L'esclusione e' scritta come `or(...not.in..., ...is.null)` e non come il
 *    solo `not.in`: in SQL `NULL NOT IN ('sospeso','revocato')` vale NULL, cosi'
 *    una riga senza `stato_bando` e con la scadenza passata sparirebbe da
 *    `?stato=chiuso` mentre `statoEffettivo` le mette il badge «Chiuso». Oggi
 *    quelle righe sono zero (§2.b) e il CHECK della migrazione 01 le vietera'
 *    sui pubblicati, ma la colonna e' nullable adesso e lista e badge non devono
 *    divergere per costruzione.
 *
 * Il chiamante fissa `oggi` una volta per richiesta (calendario di Roma) così
 * che due rami della stessa query non possano cadere a cavallo della mezzanotte.
 *
 * Modulo «foglia»: nessun import impuro, nessuna lettura dell'orologio.
 */
import { STATI_BANDO, STATI_BANDO_PERSISTITI } from '../stato-bando';
import type { StatoBando } from '../stato-bando';

/** Stati che il DB può contenere oggi: cinque solo con il flag esteso. */
export function statiAmmessi(estesi: boolean): readonly StatoBando[] {
  return estesi ? STATI_BANDO : STATI_BANDO_PERSISTITI;
}

/**
 * I valori di `?stato=` da usare: quelli ammessi, senza duplicati e
 * nell'ordine del vocabolario (non in quello della query string, che è del
 * client e non deve cambiare la condizione prodotta).
 */
export function statiRichiesti(
  valori: readonly string[] | undefined,
  estesi: boolean,
): StatoBando[] {
  if (!Array.isArray(valori) || valori.length === 0) return [];
  const chiesti = new Set(valori);
  return statiAmmessi(estesi).filter((s) => chiesti.has(s));
}

/** Valore PostgREST: fra doppi apici quando contiene spazi, virgole o parentesi. */
function valore(v: string): string {
  return /[\s,()]/.test(v) ? `"${v.replace(/"/g, '')}"` : v;
}

/**
 * La condizione (o nessuna) da aggiungere all'`and(...)` della query.
 *
 * Un ramo per stato richiesto, uniti in `or(...)`:
 *  - `chiuso`: stato chiuso **oppure** scadenza passata, ma mai un sospeso o un
 *    revocato (le righe senza stato restano dentro: vedi sopra);
 *  - `sospeso` / `revocato`: solo la colonna, nessuna condizione sulla data —
 *    la scadenza non li chiude (A3);
 *  - `aperto` / `in apertura prossimamente`: la colonna **e** una scadenza non
 *    passata, altrimenti la lista mostrerebbe come aperti bandi già scaduti che
 *    il cron non ha ancora allineato.
 */
export function condizioneStatoBando(stati: readonly StatoBando[], oggi: string): string[] {
  if (stati.length === 0) return [];
  const rami: string[] = [];
  for (const stato of stati) {
    if (stato === 'chiuso') {
      rami.push(
        'and(or(stato_bando.not.in.(sospeso,revocato),stato_bando.is.null),' +
        `or(stato_bando.eq.chiuso,data_scadenza.lt.${oggi}))`,
      );
    } else if (stato === 'sospeso' || stato === 'revocato') {
      rami.push(`stato_bando.eq.${valore(stato)}`);
    } else {
      rami.push(
        `and(stato_bando.eq.${valore(stato)},` +
        `or(data_scadenza.gte.${oggi},data_scadenza.is.null))`,
      );
    }
  }
  return [rami.length === 1 ? rami[0] : `or(${rami.join(',')})`];
}
