/**
 * Gli eventi di un bando, resi in parole: il box «Aggiornamenti» della scheda.
 *
 * Un evento è una riga datata con la sua prova (`bando_evento`, migrazione 02).
 * Qui non si decide niente: si sceglie quali mostrare, in che ordine, e con
 * quale frase. Le regole di cosa sia vero stanno altrove — nei nove gate del
 * monitor, che girano prima che una riga finisca in tabella.
 *
 * Due cose che sembrano dettagli e non lo sono.
 *
 * **Il testo è templato, non generato.** La frase la compone questo modulo a
 * partire dal tipo e dal valore; il modello che ha classificato il
 * cambiamento non scrive mai una parola che finisca in pagina. È la stessa
 * ragione per cui l'URL della prova non può venire dal modello.
 *
 * **Prima della migrazione 06 lo stato non si può scrivere.** Sospensione e
 * revoca sono eventi verificati che restano `applicato=false`, perché il
 * CHECK della colonna ammette ancora tre valori. La colonna quindi dice
 * «aperto» per un bando che l'ente ha sospeso. `statoDaEventi` legge gli
 * eventi e restituisce lo stato da mostrare: senza, la scheda inviterebbe a
 * partecipare a un bando revocato.
 *
 * Modulo «foglia»: nessun import impuro, nessuna data presa dall'orologio.
 */
import { eAggregatore, hostDi } from './domini';
import { giornoItaliano } from './testi-stato';
import type { StatoBando } from '../stato-bando';
import type { EventoBando } from './tipi';

/** Una voce del box, già pronta per il render. */
export interface VoceAggiornamento {
  readonly id: number | string;
  /** La frase, templata dal tipo. Mai testo di un modello. */
  readonly testo: string;
  /** Il giorno dell'evento in italiano, o null se la fonte non lo dice. */
  readonly quando: string | null;
  /** La pagina che lo prova, solo se pubblicabile. Mai un aggregatore. */
  readonly url: string | null;
  readonly host: string | null;
  /** `false` quando la prova sta su un dominio soltanto dedotto. */
  readonly verificato: boolean;
}

/** La data dentro `valore_dopo`, che a seconda del tipo è scalare o oggetto. */
function dataDa(valore: unknown): string | null {
  const giorno = (v: unknown): string | null =>
    (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10) : null);
  const diretto = giorno(valore);
  if (diretto !== null) return diretto;
  if (valore === null || typeof valore !== 'object' || Array.isArray(valore)) return null;
  for (const v of Object.values(valore as Record<string, unknown>)) {
    const g = giorno(v);
    if (g !== null) return g;
  }
  return null;
}

/** Lo stato proposto da un evento che non si è potuto applicare (§6.2, A30). */
function statoProposto(valore: unknown): StatoBando | null {
  if (valore === null || typeof valore !== 'object' || Array.isArray(valore)) return null;
  const proposto = (valore as Record<string, unknown>).stato_proposto;
  return proposto === 'sospeso' || proposto === 'revocato' ? proposto : null;
}

/**
 * La frase di un evento. `null` per i tipi che non hanno niente da dire a chi
 * legge: non si inventa una riga per far vedere che è successo qualcosa.
 */
export function testoEvento(evento: EventoBando): string | null {
  const quando = giornoItaliano(dataDa(evento.valore_dopo));
  const al = quando === null ? '' : ` al ${quando}`;
  const il = quando === null ? '' : ` il ${quando}`;
  const dal = quando === null ? '' : ` dal ${quando}`;

  switch (evento.tipo) {
    case 'proroga': return `Scadenza prorogata${al}`;
    case 'apertura': return `Bando aperto${dal}`;
    case 'riapertura': return `Bando riaperto${dal}`;
    case 'chiusura': return 'Bando chiuso prima della scadenza prevista';
    case 'sospensione': return `Bando sospeso${il}`;
    case 'revoca': return `Bando revocato${il}`;
    case 'annullamento_revoca': return `Revoca annullata${il}`;
    case 'graduatoria': return `Pubblicata la graduatoria${il}`;
    case 'esito': return `Pubblicato l'esito${il}`;
    case 'faq': return 'Aggiunte domande frequenti sulla pagina ufficiale';
    case 'nuovo_allegato': return 'Nuovo documento allegato';
    case 'rettifica':
      switch (evento.campo) {
        case 'data_scadenza': return `Nuova scadenza${quando === null ? '' : `: ${quando}`}`;
        case 'data_apertura': return `Nuova data di apertura${quando === null ? '' : `: ${quando}`}`;
        case 'contenuto': return 'Testo della scheda aggiornato';
        default: return 'Rettifica pubblicata dalla fonte ufficiale';
      }
    default: return null;
  }
}

/**
 * Le voci da mostrare, dalla più recente.
 *
 * Si mostra solo ciò che porta `in_aggiornamenti`: è il flag che distingue un
 * fatto per il lettore da una transizione tecnica. Le chiusure per scadenza
 * scritte dal cron, per esempio, non sono una notizia — la data era già in
 * pagina.
 */
export function vociAggiornamento(
  eventi: readonly EventoBando[] | null | undefined,
): VoceAggiornamento[] {
  if (!Array.isArray(eventi)) return [];
  const voci: VoceAggiornamento[] = [];
  for (const evento of eventi) {
    if (evento.in_aggiornamenti !== true) continue;
    const testo = testoEvento(evento);
    if (testo === null) continue;
    const host = hostDi(evento.url_prova);
    // La prova su un aggregatore non si mostra: la regola vale in pagina come
    // vale a DB, dove un trigger azzera `url_prova` sui domini in denylist.
    const mostrabile = host !== null && !eAggregatore(host);
    voci.push({
      id: evento.id,
      testo,
      quando: giornoItaliano(evento.data_evento ?? null),
      url: mostrabile ? (evento.url_prova ?? null) : null,
      host: mostrabile ? host : null,
      verificato: evento.verificato === true,
    });
  }
  return voci.sort((a, b) => (b.quando === null ? '' : b.quando).localeCompare(a.quando ?? ''));
}

/**
 * Lo stato da mostrare quando un evento verificato non si è potuto applicare.
 *
 * Finché la migrazione 06 non estende il CHECK a cinque valori, `stato_bando`
 * non può valere `sospeso` né `revocato`: quegli eventi restano
 * `applicato=false`. Senza questa funzione la scheda mostrerebbe «aperto» e il
 * pulsante «partecipa» su un bando che l'ente ha revocato.
 *
 * Vince l'evento più recente fra quelli che propongono uno stato, e una
 * riapertura verificata lo annulla.
 */
export function statoDaEventi(
  eventi: readonly EventoBando[] | null | undefined,
): StatoBando | null {
  if (!Array.isArray(eventi)) return null;
  let scelto: { stato: StatoBando | null; quando: string } | null = null;
  for (const evento of eventi) {
    if (evento.verificato !== true) continue;
    const quando = evento.data_evento ?? evento.rilevato_at ?? '';
    let stato: StatoBando | null = null;
    if (evento.tipo === 'sospensione') stato = 'sospeso';
    else if (evento.tipo === 'revoca') stato = 'revocato';
    else if (evento.tipo === 'riapertura' || evento.tipo === 'annullamento_revoca') stato = null;
    else {
      // Una rettifica può proporre uno dei due stati nuovi senza esserlo di tipo.
      const proposto = statoProposto(evento.valore_dopo);
      if (proposto === null) continue;
      stato = proposto;
    }
    if (scelto === null || quando >= scelto.quando) scelto = { stato, quando };
  }
  return scelto === null ? null : scelto.stato;
}
