/**
 * Stato dei bandi: vocabolario, macchina a stati e stato effettivo alla lettura.
 *
 * Una sola regola in tre linguaggi (piano §4): questo modulo, il gemello Python
 * `scraper_bandi/app/stato_bando.py` e la funzione SQL `bando_stato_effettivo`
 * della vista pubblica. La tabella di verità condivisa è
 * `tests/stato-bando/casi.json`: i test dei tre linguaggi girano sugli stessi
 * casi, così una divergenza non può passare inosservata.
 *
 * Perché lo stato si calcola alla lettura: la colonna `stato_bando` la scrivono
 * il cron orario, il monitor e la pipeline, ma fra due scritture passano ore; un
 * bando con la scadenza di ieri resterebbe «aperto» fino al giro successivo.
 *
 * Modulo «foglia»: nessun import, nessuna variabile d'ambiente, nessuna lettura
 * dell'ora locale del processo (`tests/api-v1/purezza.test.ts`). L'unico modo
 * ammesso per ricavare data e ora civili italiane da un istante è `Intl`.
 */

// Cinque stati: i tre storici della colonna piu' `sospeso` e `revocato`, che la
// migrazione 06 aggiunge al CHECK. Chi filtra sulla colonna persistita prima
// della 06 non trovera' mai gli ultimi due.
export const STATI_BANDO = [
  'aperto',
  'chiuso',
  'in apertura prossimamente',
  'sospeso',
  'revocato',
] as const;
export type StatoBando = typeof STATI_BANDO[number];

// I soli valori che il CHECK della colonna ammette finche' la migrazione 06
// non e' applicata. Per validare un input dell'utente (il filtro `?stato=` di
// una lista, un parametro d'API) si usa QUESTA: con `STATI_BANDO` un
// `?stato=sospeso` arriverebbe a PostgREST e tornerebbe una lista vuota invece
// della lista intera. `STATI_BANDO` resta il vocabolario completo, per badge,
// tipi e macchina a stati.
export const STATI_BANDO_PERSISTITI = [
  'aperto',
  'chiuso',
  'in apertura prossimamente',
] as const satisfies readonly StatoBando[];

// Chi puo' scrivere `stato_bando`: gli stessi valori di `bando_evento.origine`.
// Il resolver non compare di proposito: tocca fonte e link, mai lo stato.
export const ATTORI_TRANSIZIONE = ['cron', 'worker', 'pipeline', 'redazione'] as const;
export type AttoreTransizione = typeof ATTORI_TRANSIZIONE[number];

export interface Transizione {
  /** Stato di partenza; `null` = creazione della riga. */
  readonly da: StatoBando | null;
  readonly a: StatoBando;
  readonly attore: AttoreTransizione;
  /** Evento leggibile che la transizione produce (`bando_evento.tipo`). */
  readonly evento: string;
  /** Condizione in chiaro: è la prova che la transizione richiede. */
  readonly condizione: string;
}

/**
 * Tabella di §4, riga per riga. È una lista bianca, e la stessa lista che la
 * migrazione 04 semina in `bando_transizione` per autorizzare gli eventi sui
 * bandi **pubblicati**: quello che non c'è non è ammesso, quindi una riga di
 * troppo qui è un varco nella guardia a DB. Quattro assenze volute:
 *  - `revocato` non ha transizioni in uscita (§4 lo dichiara terminale);
 *  - nessuna riga chiude un `sospeso` (A3: mai chiuso d'ufficio);
 *  - nessuna riga ha attore `redazione`, perché §4 non concede alla redazione
 *    nessuna scrittura automatica su `stato_bando`; una correzione manuale
 *    passa dal SQL Editor, che la guardia di ruolo lascia passare a parte;
 *  - l'attore `pipeline` compare **solo** nelle righe di creazione (`da: null`):
 *    la pipeline LLM tocca esclusivamente le righe non ancora pubblicate, che
 *    non passano dal trigger, e §4 non le concede nessun passaggio fra stati.
 *    Concederglielo qui significherebbe far riaprire un `chiuso` pubblicato
 *    senza le prove G1-G9 + G7, che §4 e §13.3 dichiarano l'unico modo.
 * Le righe di §4 che non cambiano `stato_bando` (rettifica/FAQ/allegato,
 * fusione, ritiro) non stanno qui: agiscono su altre colonne.
 */
export const TRANSIZIONI: readonly Transizione[] = [
  {
    da: null,
    a: "aperto",
    attore: "pipeline",
    evento: "pubblicazione",
    condizione:
      "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione",
  },
  {
    da: null,
    a: "chiuso",
    attore: "pipeline",
    evento: "pubblicazione",
    condizione:
      "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione",
  },
  {
    da: null,
    a: "in apertura prossimamente",
    attore: "pipeline",
    evento: "pubblicazione",
    condizione:
      "riga nuova non ancora pubblicata: lo stato lo decide il preprocess/enrich con la guardia reconcile_stato_bando; nessun evento leggibile prima della pubblicazione",
  },
  {
    da: "in apertura prossimamente",
    a: "aperto",
    attore: "cron",
    evento: "apertura_automatica",
    condizione:
      "data_apertura_verificata=true e apertura raggiunta (data, e ora se presente); job orario 5 * * * *, evento con in_aggiornamenti=false",
  },
  {
    da: "aperto",
    a: "chiuso",
    attore: "cron",
    evento: "chiusura_automatica",
    condizione:
      "data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato",
  },
  {
    da: "in apertura prossimamente",
    a: "chiuso",
    attore: "cron",
    evento: "chiusura_automatica",
    condizione:
      "data_scadenza < oggi, oppure = oggi con ora_scadenza passata; job orario 5 * * * *, eventi con verificato=false e url_prova NULL; non tocca mai sospeso ne revocato",
  },
  {
    da: "in apertura prossimamente",
    a: "aperto",
    attore: "worker",
    evento: "apertura",
    condizione:
      "la pagina ufficiale dichiara apertura entro oggi; gate G1-G9 (citazione, url_prova scaricato, G6 su apert|dal|a partire|attiv, G7)",
  },
  {
    da: "in apertura prossimamente",
    a: "in apertura prossimamente",
    attore: "worker",
    evento: "rettifica",
    condizione:
      "differimento: date nuove di apertura e scadenza; gate G1-G9, G2 rafforzato al primo controllo; campo=data_apertura",
  },
  {
    da: "aperto",
    a: "aperto",
    attore: "worker",
    evento: "proroga",
    condizione:
      "scadenza posticipata; gate G1-G9 e vecchia data non NULL, nuova maggiore della vecchia e non anteriore a oggi",
  },
  {
    da: "aperto",
    a: "aperto",
    attore: "worker",
    evento: "rettifica",
    condizione:
      "sportello senza scadenza a cui compare una data_scadenza; gate G1-G9 come rettifica, G7 obbligatorio; campo=data_scadenza",
  },
  {
    da: "aperto",
    a: "chiuso",
    attore: "worker",
    evento: "chiusura",
    condizione:
      "esaurimento risorse o chiusura anticipata non successiva a oggi; gate G1-G9; data_scadenza resta intatta, non si scrive mai oggi",
  },
  {
    da: "chiuso",
    a: "aperto",
    attore: "worker",
    evento: "proroga",
    condizione:
      "proroga verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso",
  },
  {
    da: "chiuso",
    a: "aperto",
    attore: "worker",
    evento: "riapertura",
    condizione:
      "riapertura verificata; gate G1-G9 piu G7: unico modo per riaprire un chiuso",
  },
  {
    da: "aperto",
    a: "sospeso",
    attore: "worker",
    evento: "sospensione",
    condizione:
      "sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false",
  },
  {
    da: "in apertura prossimamente",
    a: "sospeso",
    attore: "worker",
    evento: "sospensione",
    condizione:
      "sospensione dichiarata dalla fonte ufficiale (G1-G9 su sospe); prima di R0 evento con applicato=false",
  },
  {
    da: "sospeso",
    a: "aperto",
    attore: "worker",
    evento: "riapertura",
    condizione:
      "ripresa dichiarata dalla fonte ufficiale; gate G1-G9",
  },
  {
    da: "sospeso",
    a: "in apertura prossimamente",
    attore: "worker",
    evento: "riapertura",
    condizione:
      "ripresa con nuova data di apertura dichiarata dalla fonte ufficiale; gate G1-G9",
  },
  {
    da: "aperto",
    a: "revocato",
    attore: "worker",
    evento: "revoca",
    condizione:
      "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false",
  },
  {
    da: "chiuso",
    a: "revocato",
    attore: "worker",
    evento: "revoca",
    condizione:
      "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false",
  },
  {
    da: "in apertura prossimamente",
    a: "revocato",
    attore: "worker",
    evento: "revoca",
    condizione:
      "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false",
  },
  {
    da: "sospeso",
    a: "revocato",
    attore: "worker",
    evento: "revoca",
    condizione:
      "revoca, annullamento o ritiro dichiarati dalla fonte ufficiale (G1-G9 su revoc|annull|ritir); stato terminale; prima di R0 evento con applicato=false",
  },
  {
    da: "chiuso",
    a: "chiuso",
    attore: "worker",
    evento: "graduatoria",
    condizione:
      "pubblicazione della graduatoria: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia",
  },
  {
    da: "chiuso",
    a: "chiuso",
    attore: "worker",
    evento: "esito",
    condizione:
      "pubblicazione degli esiti: link nuovo scaricato con esito 2xx; in_aggiornamenti=true, lo stato non cambia",
  },
];

/**
 * La transizione è prevista dalla macchina a stati? Lista bianca: `false` è la
 * risposta di default, anche per un attore che non scrive mai lo stato.
 */
export function transizioneAmmessa(
  da: StatoBando | null,
  a: StatoBando,
  attore: AttoreTransizione,
): boolean {
  return TRANSIZIONI.some((t) => t.da === da && t.a === a && t.attore === attore);
}

// ---------------------------------------------------------------------------
// Data e ora civili italiane
// ---------------------------------------------------------------------------

const FUSO_ROMA = 'Europe/Rome';

// 'en-CA' formatta come ISO date: e' il modo piu' corto per avere YYYY-MM-DD.
const FORMATO_GIORNO_ROMA = new Intl.DateTimeFormat('en-CA', { timeZone: FUSO_ROMA });

// hourCycle 'h23' e non hour12:false: con quest'ultimo alcune build di ICU
// rendono la mezzanotte come «24», che romperebbe il confronto fra stringhe.
const FORMATO_ISTANTE_ROMA = new Intl.DateTimeFormat('en-CA', {
  timeZone: FUSO_ROMA,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

/**
 * Data odierna (YYYY-MM-DD) nel fuso Europe/Rome, indipendente dal timezone
 * del server/browser.
 */
export function todayRomeISO(adesso: Date = new Date()): string {
  return FORMATO_GIORNO_ROMA.format(adesso);
}

interface IstanteRoma {
  readonly giorno: string;
  readonly ora: string;
}

/** Giorno e ora civili italiani di un istante, come stringhe confrontabili. */
function istanteRoma(adesso: Date): IstanteRoma {
  const parti: Record<string, string> = {};
  for (const parte of FORMATO_ISTANTE_ROMA.formatToParts(adesso)) parti[parte.type] = parte.value;
  const ore = parti.hour === '24' ? '00' : parti.hour;
  return {
    giorno: `${parti.year}-${parti.month}-${parti.day}`,
    ora: `${ore}:${parti.minute}:${parti.second}`,
  };
}

const FORMA_GIORNO = /^\d{4}-\d{2}-\d{2}$/;
const FORMA_ORA = /^(\d{2}):(\d{2})(?::(\d{2}))?/;

/** Giorno di una colonna `date` o di un timestamp: solo YYYY-MM-DD, o null. */
function soloGiorno(valore: string | null | undefined): string | null {
  if (typeof valore !== 'string') return null;
  const giorno = valore.slice(0, 10);
  return FORMA_GIORNO.test(giorno) ? giorno : null;
}

/** Ora di una colonna `time` normalizzata a HH:MM:SS, o null. */
function soloOra(valore: string | null | undefined): string | null {
  if (typeof valore !== 'string') return null;
  const trovata = FORMA_ORA.exec(valore.trim());
  if (trovata === null) return null;
  return `${trovata[1]}:${trovata[2]}:${trovata[3] ?? '00'}`;
}

function statoValido(valore: string | null | undefined): StatoBando | null {
  for (const stato of STATI_BANDO) if (valore === stato) return stato;
  return null;
}

/**
 * Le colonne che servono a calcolare lo stato effettivo. La colonna del DB si
 * chiama `data_apertura_verificata` (§13.0); `apertura_verificata` è il nome
 * breve del fixture `tests/stato-bando/casi.json` ed è accettato come sinonimo,
 * così una riga letta dalla vista funziona senza rimappare i campi. Se ci sono
 * entrambi vince il nome del DB.
 */
export interface CampiStatoBando {
  readonly stato?: string | null;
  readonly data_apertura?: string | null;
  readonly data_apertura_verificata?: boolean | null;
  /** Sinonimo del fixture di `data_apertura_verificata`. */
  readonly apertura_verificata?: boolean | null;
  readonly ora_apertura?: string | null;
  readonly data_scadenza?: string | null;
  readonly ora_scadenza?: string | null;
}

/**
 * Stato da mostrare all'utente (piano §13.3), in ordine di precedenza:
 *  1. `revocato` resta `revocato` (terminale);
 *  2. `sospeso` resta `sospeso` anche con la scadenza passata (A3);
 *  3. scadenza passata (`data_scadenza` < oggi, oppure = oggi con
 *     `ora_scadenza` passata) → `chiuso`;
 *  4. `in apertura prossimamente` con apertura **verificata** e raggiunta →
 *     `aperto`;
 *  5. altrimenti lo stato salvato.
 *
 * Due asimmetrie volute sull'istante esatto: la scadenza è passata solo *dopo*
 * l'ora dichiarata (alle 12:00:00 in punto si è ancora in tempo), l'apertura è
 * raggiunta *a partire* dall'ora dichiarata. In entrambi i casi l'istante di
 * confine sta dentro la finestra di partecipazione.
 *
 * Il giorno di scadenza senza `ora_scadenza` il bando resta aperto fino a
 * mezzanotte: chi ragiona solo per date diverge dalla vista al massimo di
 * qualche ora, e solo in quel giorno.
 */
export function statoEffettivo(
  campi: CampiStatoBando,
  adesso: Date = new Date(),
): StatoBando | null {
  const stato = statoValido(campi.stato);
  if (stato === 'revocato') return 'revocato';
  if (stato === 'sospeso') return 'sospeso';

  const scadenza = soloGiorno(campi.data_scadenza);
  const verificata = campi.data_apertura_verificata ?? campi.apertura_verificata;
  const apertura = stato === 'in apertura prossimamente' && verificata === true
    ? soloGiorno(campi.data_apertura)
    : null;
  // Senza date da confrontare non serve nemmeno leggere l'orologio.
  if (scadenza === null && apertura === null) return stato;

  const istante = istanteRoma(adesso);

  if (scadenza !== null) {
    const oraScadenza = scadenza === istante.giorno ? soloOra(campi.ora_scadenza) : null;
    if (scadenza < istante.giorno) return 'chiuso';
    if (oraScadenza !== null && oraScadenza < istante.ora) return 'chiuso';
  }

  if (apertura !== null && apertura <= istante.giorno) {
    const oraApertura = apertura === istante.giorno ? soloOra(campi.ora_apertura) : null;
    if (oraApertura === null || oraApertura <= istante.ora) return 'aperto';
  }

  return stato;
}

/**
 * Firma storica, usata da card, scheda, liste e API v1: stato salvato +
 * `data_scadenza`, con «oggi» già calcolato dal chiamante (l'API lo fissa una
 * volta per richiesta). Sui tre stati oggi persistiti il risultato è identico a
 * prima (scadenza passata → `chiuso`, un `chiuso` non riapre); `revocato` e
 * `sospeso` restano sé stessi anche con la scadenza passata, come impongono le
 * regole 1 e 2 di §13.3 e la garanzia A3 («mai chiuso d'ufficio»).
 * Chi ha `ora_scadenza` e il flag di verifica usi `statoEffettivo`.
 */
export function effectiveStatoBando(
  stato: StatoBando | null | undefined,
  dataScadenza: string | null | undefined,
  oggi: string = todayRomeISO(),
): StatoBando | null {
  const normalizzato = statoEffettivo({ stato });
  if (normalizzato === 'revocato' || normalizzato === 'sospeso') return normalizzato;
  if (dataScadenza && String(dataScadenza).slice(0, 10) < oggi) return 'chiuso';
  return normalizzato;
}
