/**
 * Unico accesso ai dati dell'API /api/v1: esegue un PianoQuery (filtri.ts) sul client
 * Supabase giusto. Solo cablaggio: nessun filtro, ordinamento o limite scritto qui
 * (lo verifica tests/api-v1/purezza.test.ts), nessuno stato.
 */
import { supabase } from '../supabase';
import { supabaseBandi } from '../supabase-bandi';
import { SELECT_PER_NOME } from './colonne';
import { TIMEOUT_QUERY_MS } from './costanti';
import { ErroreDati, classificaErrore } from './errori';
import { applicaPiano, type CostruttoreQuery } from './filtri';
import type { FonteDati, NomeSelect, PianoQuery, RighePerSelect } from './contratto';

async function leggi<S extends NomeSelect>(piano: PianoQuery<S>, segnale: AbortSignal): Promise<RighePerSelect[S][]> {
  const client = piano.db === 'bandi' ? supabaseBandi : supabase;
  const select = SELECT_PER_NOME.get(piano.select);
  if (!select) throw new ErroreDati('programmazione', null, `select sconosciuta: ${piano.select}`);
  // Le colonne che dipendono dalla fonte e non dalla risorsa: la freschezza,
  // che ha un nome per fonte, e le colonne v11 che solo la vista sa dare. Il
  // piano le porta gia' pronte (`filtri.ts`), qui si appendono e basta.
  const colonne = piano.colonneExtra ? `${select}, ${piano.colonneExtra}` : select;

  // Adattatore: il builder di postgrest-js restituisce `this` a ogni chiamata.
  let query = client.from(piano.tabella).select(colonne);
  const adattatore: CostruttoreQuery = {
    filter(colonna, operatore, valore) { query = query.filter(colonna, operatore, valore); return adattatore; },
    or(espressione) { query = query.or(espressione); return adattatore; },
    order(colonna, opzioni) { query = query.order(colonna, opzioni); return adattatore; },
    limit(n) { query = query.limit(n); return adattatore; },
  };
  applicaPiano(adattatore, piano.operazioni);

  // Timeout per singola query dentro il budget della richiesta.
  const { data, error, status } = await query.abortSignal(AbortSignal.any([segnale, AbortSignal.timeout(TIMEOUT_QUERY_MS)]));
  if (error) {
    throw new ErroreDati(classificaErrore({ status, code: error.code }), error.code ?? null, 'errore PostgREST');
  }
  if (!Array.isArray(data)) throw new ErroreDati('programmazione', null, 'risposta PostgREST senza array');
  // Senza tipi generati del DB postgrest-js non conosce le colonne: la forma la validano i mapper.
  return data as unknown as RighePerSelect[S][];
}

export function creaFonteSupabase(): FonteDati {
  return { leggi };
}
