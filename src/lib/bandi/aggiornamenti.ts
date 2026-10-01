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
 * **Lo stato non viene da qui.** Un evento racconta che cosa è successo; lo
 * stato del bando lo dice solo la colonna (`stato_effettivo` della vista).
 * Fino al giro 3 questo modulo aveva anche `statoDaEventi`, una seconda fonte
 * dello stato nata quando il CHECK ammetteva tre valori (prima della
 * migrazione 06, applicata il 28/09/2026): dopo una correzione la scheda
 * avrebbe detto «Sospeso» mentre lista, API e BandoFit dicevano «Aperto». È
 * stata tolta (contratto interno del giro 3, §14).
 *
 * Modulo «foglia»: nessun import impuro, nessuna data presa dall'orologio.
 */
import { hostDi, urlPubblicabile } from './domini';
import { STATI_BANDO } from '../stato-bando';
import { giornoItaliano, oraItaliana } from './testi-stato';
import type { EventoBando } from './tipi';

/** Un evento con il riferimento all'evento che corregge o ritira. */
export type EventoConRiferimento = EventoBando & { readonly riferisce_a?: number | string | null };

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

/** `valore_dopo` come oggetto, o null se è uno scalare. */
function mappaDa(valore: unknown): Record<string, unknown> | null {
  return valore === null || typeof valore !== 'object' || Array.isArray(valore)
    ? null
    : valore as Record<string, unknown>;
}

/**
 * La data dentro `valore_dopo`, che a seconda del tipo è scalare o oggetto.
 *
 * Prima la chiave che porta il nome di `campo`: un'`apertura` scrive insieme
 * `data_apertura` e `data_scadenza`, e la frase deve dire la prima. Solo se
 * manca si prende la prima data che si trova.
 */
function dataDa(valore: unknown, campo?: string | null): string | null {
  const giorno = (v: unknown): string | null =>
    (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10) : null);
  const diretto = giorno(valore);
  if (diretto !== null) return diretto;
  const mappa = mappaDa(valore);
  if (mappa === null) return null;
  if (typeof campo === 'string' && campo !== '') {
    const delCampo = giorno(mappa[campo]);
    if (delCampo !== null) return delCampo;
  }
  for (const v of Object.values(mappa)) {
    const g = giorno(v);
    if (g !== null) return g;
  }
  return null;
}

/** L'ora di un `data_verificata` su `ora_apertura` / `ora_scadenza`. */
function oraDa(valore: unknown, campo: string): string | null {
  const mappa = mappaDa(valore);
  const grezza = mappa === null ? valore : mappa[campo];
  return typeof grezza === 'string' ? oraItaliana(grezza) : null;
}

/**
 * La fusione si registra su entrambe le schede (`bando_fondi`): sul doppione,
 * che esce dalla vista, e sul master, che lo ingloba. `master_id` uguale al
 * bando dell'evento vuol dire che questa è la scheda che resta.
 */
function eFusioneSulMaster(evento: EventoBando & { readonly bando_id?: number | string | null }): boolean {
  const master = mappaDa(evento.valore_dopo)?.master_id;
  const bando = evento.bando_id;
  if (master === null || master === undefined || bando === null || bando === undefined) return false;
  return String(master) === String(bando);
}

/**
 * Lo stato nuovo di una correzione della redazione (`bando_correggi_stato`,
 * migrazione 14): `valore_dopo` è lo stato come stringa JSON, oppure un
 * oggetto con `stato_bando`. Null se non è uno dei cinque stati.
 */
function statoCorretto(valore: unknown): string | null {
  const grezzo = typeof valore === 'string' ? valore : mappaDa(valore)?.stato_bando;
  return (STATI_BANDO as readonly unknown[]).includes(grezzo) ? grezzo as string : null;
}

/**
 * La frase di un evento. `null` per i tipi che non hanno niente da dire a chi
 * legge: non si inventa una riga per far vedere che è successo qualcosa.
 *
 * Copre tutti i tipi pubblici del contratto (§6.1 di `contratto-db-bandi.md`):
 * quelli del box «Aggiornamenti» e quelli, tecnici o automatici, che compaiono
 * solo nello storico della scheda (`storico.ts`). I tipi interni non arrivano
 * mai ad anon e restano `null`.
 */
export function testoEvento(
  evento: EventoBando & { readonly bando_id?: number | string | null },
): string | null {
  const quando = giornoItaliano(dataDa(evento.valore_dopo, evento.campo));
  // «otto» e «undici» cominciano per vocale: «all'8», «dall'11», «l'8».
  const elide = quando !== null && /^(8|11) /.test(quando);
  const al = quando === null ? '' : elide ? ` all'${quando}` : ` al ${quando}`;
  const il = quando === null ? '' : elide ? ` l'${quando}` : ` il ${quando}`;
  const dal = quando === null ? '' : elide ? ` dall'${quando}` : ` dal ${quando}`;
  const duepunti = (v: string | null): string => (v === null ? '' : `: ${v}`);

  switch (evento.tipo) {
    // Tipi tecnici e automatici: solo nello storico.
    case 'pubblicazione': return 'Scheda pubblicata su EduNews24';
    case 'apertura_automatica': return 'Bando aperto: è arrivata la data di apertura';
    case 'chiusura_automatica': return 'Bando chiuso: termine di scadenza raggiunto';
    case 'fonte_ufficiale_verificata': return 'Individuata la pagina ufficiale dell\'ente';
    case 'data_verificata':
      switch (evento.campo) {
        case 'data_apertura': return `Data di apertura verificata sulla pagina ufficiale${duepunti(quando)}`;
        case 'data_scadenza': return `Scadenza verificata sulla pagina ufficiale${duepunti(quando)}`;
        case 'ora_apertura': return `Orario di apertura verificato sulla pagina ufficiale${duepunti(oraDa(evento.valore_dopo, 'ora_apertura'))}`;
        case 'ora_scadenza': return `Orario di scadenza verificato sulla pagina ufficiale${duepunti(oraDa(evento.valore_dopo, 'ora_scadenza'))}`;
        default: return 'Date verificate sulla pagina ufficiale';
      }
    case 'fusione':
      return eFusioneSulMaster(evento)
        ? 'Unita a questa scheda un\'altra scheda dello stesso bando'
        : 'Scheda unita a quella principale dello stesso bando';
    case 'separazione': return 'Scheda separata da un\'altra scheda';
    case 'cambio_slug': return 'Indirizzo della pagina aggiornato';
    case 'ritiro': return 'Scheda ritirata';
    case 'correzione_redazionale': {
      const nuovo = statoCorretto(evento.valore_dopo);
      return nuovo === null ? 'Correzione della redazione' : `Stato corretto dalla redazione: ${nuovo}`;
    }
    // Tipi del box «Aggiornamenti».
    case 'proroga': return `Scadenza prorogata${al}`;
    case 'apertura': return `Bando aperto${dal}`;
    case 'riapertura': return `Bando riaperto${dal}`;
    // Neutra: una chiusura arriva anche senza scadenza (correzioni della
    // verifica, un sospeso che chiude), e «prima della scadenza» sarebbe falso.
    case 'chiusura': return 'Bando chiuso';
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
 * Gli eventi senza i ritirati: un solo filtro per il box e per lo storico.
 *
 * Il registro è immutabile: un evento ritirato resta in tabella e il ritiro è
 * una riga nuova con `riferisce_a`. Non si mostrano né l'evento ritirato né la
 * riga del ritiro: un fatto smentito non va raccontato come vero. Un `ritiro`
 * senza `riferisce_a` riguarda la scheda, non un evento, e resta.
 */
export function senzaRitirati<T extends EventoConRiferimento>(eventi: readonly T[]): T[] {
  const ritiro = (e: EventoConRiferimento): boolean =>
    e.tipo === 'ritiro' && e.riferisce_a !== null && e.riferisce_a !== undefined;
  const ritirati = new Set<string>();
  for (const evento of eventi) if (ritiro(evento)) ritirati.add(String(evento.riferisce_a));
  return eventi.filter((e) => !ritiro(e) && !ritirati.has(String(e.id)));
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
  eventi: readonly EventoConRiferimento[] | null | undefined,
): VoceAggiornamento[] {
  if (!Array.isArray(eventi)) return [];
  const voci: Array<{ voce: VoceAggiornamento; giorno: string; id: number }> = [];
  for (const evento of senzaRitirati(eventi)) {
    if (evento.in_aggiornamenti !== true) continue;
    const testo = testoEvento(evento);
    if (testo === null) continue;
    // La prova si mostra solo se l'URL è pubblicabile: schema http(s) (niente
    // `javascript:` né `data:` in un href) e host fuori dalla denylist degli
    // aggregatori, la stessa regola del trigger a DB che azzera `url_prova`.
    const mostrabile = urlPubblicabile(evento.url_prova);
    const host = mostrabile ? hostDi(evento.url_prova) : null;
    const giorno = typeof evento.data_evento === 'string' && /^\d{4}-\d{2}-\d{2}/.test(evento.data_evento)
      ? evento.data_evento.slice(0, 10)
      : '';
    voci.push({
      voce: {
        id: evento.id,
        testo,
        quando: giornoItaliano(evento.data_evento ?? null),
        url: mostrabile ? (evento.url_prova ?? null) : null,
        host,
        verificato: evento.verificato === true,
      },
      giorno,
      id: idNumerico(evento.id),
    });
  }
  // Si ordina sulla data ISO, non sulla frase: «9 luglio 2026» viene dopo
  // «25 settembre 2026» nell'ordine dei caratteri. A parità di giorno vince
  // l'id più alto, come faceva la query quando ordinava `data_evento desc,
  // id desc` (oggi gli eventi arrivano per id crescente); le date mancanti
  // vanno in fondo.
  return voci.sort((a, b) => {
    if (a.giorno !== b.giorno) return b.giorno.localeCompare(a.giorno);
    if (a.id !== b.id) return b.id > a.id ? 1 : -1;
    return 0;
  }).map((v) => v.voce);
}

/** L'id come numero confrontabile (bigint può arrivare come stringa). */
function idNumerico(id: number | string | null | undefined): number {
  const n = typeof id === 'number' ? id : Number(id);
  return id === null || id === undefined || id === '' || Number.isNaN(n)
    ? Number.NEGATIVE_INFINITY
    : n;
}
