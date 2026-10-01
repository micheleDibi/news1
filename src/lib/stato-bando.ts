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
// migrazione 06 (applicata il 28/09/2026) ha aggiunto al CHECK. Come filtro di
// una lista il sito li accetta solo con `BANDI_STATI_ESTESI` (vedi sotto).
export const STATI_BANDO = [
  'aperto',
  'chiuso',
  'in apertura prossimamente',
  'sospeso',
  'revocato',
] as const;
export type StatoBando = typeof STATI_BANDO[number];

// I tre valori che il CHECK della colonna ammetteva prima della migrazione 06
// (applicata il 28/09/2026). Per validare un input dell'utente (il filtro
// `?stato=` di una lista, un parametro d'API) senza `BANDI_STATI_ESTESI` si usa
// QUESTA: prima della 06 un `?stato=sospeso` arrivava a PostgREST e tornava una
// lista vuota invece della lista intera. `STATI_BANDO` resta il vocabolario
// completo, per badge, tipi e macchina a stati.
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
  /**
   * Migrazione che porta la riga in `bando_transizione`; assente = seed della
   * 04. Le righe con la migrazione le semina il blocco «delta» di quel file,
   * così il blocco della 04 resta identico byte per byte.
   */
  readonly migrazione?: number;
}

/**
 * Tabella di §4, riga per riga. È una lista bianca, e la stessa lista che la
 * migrazione 04 semina in `bando_transizione` per autorizzare gli eventi sui
 * bandi **pubblicati** (le righe con `migrazione` le aggiunge il delta di quella
 * migrazione): quello che non c'è non è ammesso, quindi una riga di troppo qui
 * è un varco nella guardia a DB. Assenze e limiti voluti:
 *  - dal `revocato` si esce solo con `annullamento_revoca` del worker (14);
 *  - un `sospeso` si chiude solo con una `chiusura` letta dal worker (14), mai
 *    d'ufficio: il cron non tocca un sospeso (A3);
 *  - nessuna riga ha attore `redazione`, perché §4 non concede alla redazione
 *    nessuna scrittura automatica su `stato_bando`; la correzione a mano passa
 *    dalla RPC `bando_correggi_stato` della migrazione 14, fuori lista;
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
  {
    da: "in apertura prossimamente",
    a: "chiuso",
    attore: "worker",
    evento: "chiusura",
    condizione:
      "la pagina ufficiale dichiara chiuso, scaduto o concluso con etichetta strutturata; gate G1-G9, G7 per doppia lettura strutturata (contratto 6.1)",
    migrazione: 13,
  },
  // Migrazione 14 (giro 3, contratto interno §14): il sospeso si chiude con
  // una chiusura letta dal worker, e dal revocato si esce solo con
  // `annullamento_revoca`, verso lo stato che la RPC calcola dalle date.
  {
    da: "sospeso",
    a: "chiuso",
    attore: "worker",
    evento: "chiusura",
    condizione:
      "la pagina ufficiale dichiara chiuso il bando sospeso (chiusura dell'ente o termine senza ripresa); gate G1-G9, G7; mai d'ufficio: il cron non tocca un sospeso",
    migrazione: 14,
  },
  {
    da: "revocato",
    a: "aperto",
    attore: "worker",
    evento: "annullamento_revoca",
    condizione:
      "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: apertura raggiunta e scadenza non passata; gate G1-G9",
    migrazione: 14,
  },
  {
    da: "revocato",
    a: "chiuso",
    attore: "worker",
    evento: "annullamento_revoca",
    condizione:
      "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: scadenza gia passata; gate G1-G9",
    migrazione: 14,
  },
  {
    da: "revocato",
    a: "in apertura prossimamente",
    attore: "worker",
    evento: "annullamento_revoca",
    condizione:
      "la fonte ufficiale annulla la revoca; stato di arrivo calcolato dalle date: apertura futura; gate G1-G9",
    migrazione: 14,
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

// ---------------------------------------------------------------------------
// Stato da verificare
// ---------------------------------------------------------------------------

/**
 * Perché lo stato mostrato non è certo (contratto interno del giro 2, §3 con
 * §19.3). Elenco chiuso, lo stesso della sezione `certezza` di
 * `tests/stato-bando/casi.json`, del gemello Python, della funzione SQL
 * `bando_stato_da_verificare` e dell'enum dell'API v1. `null` vuol dire
 * «nessuna prova contraria».
 */
export const MOTIVI_DA_VERIFICARE = [
  'data_apertura_passata',
  'smentito_dalla_fonte',
  'previsione_scaduta',
  'senza_conferma',
  'termine_passato',
] as const;
export type MotivoDaVerificare = typeof MOTIVI_DA_VERIFICARE[number];

/** Gli stati che la verifica sa leggere sulla pagina ufficiale. */
export const STATI_LETTI = ['in apertura prossimamente', 'aperto', 'chiuso', 'uscito'] as const;
export type StatoLetto = typeof STATI_LETTI[number];

/** Chi ha letto la pagina: un lettore strutturato o il modello. */
export const METODI_LETTURA = ['estrattore', 'modello'] as const;
export type MetodoLettura = typeof METODI_LETTURA[number];

/** Ramo I: giorni di grazia dopo la pubblicazione (I6). */
export const GIORNI_GRAZIA_PUBBLICAZIONE = 3;
/** Età massima di una conferma letta sulla pagina ufficiale (I5, A2). */
export const GIORNI_VALIDITA_CONFERMA = 30;
/** Ramo A: giorni di grazia dopo la pubblicazione (A7). */
export const GIORNI_GRAZIA_RAMO_A = 7;

/**
 * Le colonne di `bando_controllo` (e `pubblicato_at`) che servono alla regola,
 * oltre a quelle dello stato effettivo. Assente vale NULL: chi legge dalla
 * tabella e non dalla vista passa solo quello che ha.
 */
export interface CampiDaVerificare extends CampiStatoBando {
  readonly pubblicato_at?: string | null;
  readonly previsto_entro?: string | null;
  readonly termine_indicato?: string | null;
  readonly stato_letto?: string | null;
  readonly stato_letto_su?: string | null;
  readonly stato_letto_at?: string | null;
  readonly stato_letto_metodo?: string | null;
  readonly esaminato_attivo_at?: string | null;
  readonly segnale_aggregatore_at?: string | null;
}

// ISO 8601 come lo restituisce PostgREST: giorno, poi ora e fuso facoltativi.
const FORMA_ISTANTE = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}(?::?\d{2})?)?)?$/;

/**
 * Millisecondi di un timestamp, o null se manca o è malformato. Senza fuso
 * vale UTC, come il naive del gemello Python: `Date` lo leggerebbe nell'ora
 * locale del processo.
 */
function istante(valore: string | null | undefined): number | null {
  if (typeof valore !== 'string') return null;
  const parti = FORMA_ISTANTE.exec(valore.trim());
  if (parti === null) return null;
  const [, giorno, ora, fuso] = parti;
  let offset = fuso ?? 'Z';
  if (/^[+-]\d{2}$/.test(offset)) offset = `${offset}:00`;
  else if (/^[+-]\d{4}$/.test(offset)) offset = `${offset.slice(0, 3)}:${offset.slice(3)}`;
  const ms = Date.parse(`${giorno}T${ora ?? '00:00'}${offset}`);
  return Number.isNaN(ms) ? null : ms;
}

/** Giorni civili di Roma fra l'istante e `oggi`; negativi se nel futuro. */
function giorniFa(ms: number, oggi: string): number {
  const giorno = FORMATO_GIORNO_ROMA.format(new Date(ms));
  return (Date.parse(`${oggi}T00:00:00Z`) - Date.parse(`${giorno}T00:00:00Z`)) / 86_400_000;
}

function valoreIn<T extends string>(elenco: readonly T[], valore: string | null | undefined): T | null {
  for (const voce of elenco) if (valore === voce) return voce;
  return null;
}

/**
 * Motivo per cui lo stato mostrato va verificato, o null (contratto interno
 * del giro 2, §3 con §19.3; casi in `tests/stato-bando/casi.json`, sezione
 * `certezza`). Vince la prima regola che si applica, nell'ordine definitivo
 * di §19.3: in ombra (mai esaminato in attivo) conta solo ciò che il bando dice
 * di sé, quindi l'unico motivo pubblico è `data_apertura_passata`.
 *
 * R0: stato effettivo «in apertura» → ramo I; «aperto» senza `data_scadenza`
 * → ramo A; altrimenti null.
 *
 * Ramo I, nell'ordine I1, I2, I3, I6-bis, I4, I5, I6, I7: I1 apertura
 * verificata con data → null; I2 `data_apertura` < oggi →
 * `data_apertura_passata`; I3 lettura valida aperto/chiuso/uscito →
 * `smentito_dalla_fonte`; I6-bis mai esaminato in attivo → null; I4
 * `previsto_entro` < oggi → `previsione_scaduta`; I5 lettura valida «in
 * apertura» di al massimo 30 giorni fa → null; I6 pubblicato da al massimo 3
 * giorni → null; I7 → `senza_conferma`.
 *
 * Ramo A, nell'ordine A1, A2, A4, A3, A5, A6, A7, A8: A1 lettura valida
 * chiuso/uscito/in apertura → `smentito_dalla_fonte`; A2 lettura valida
 * «aperto» dell'estrattore di al massimo 30 giorni fa e successiva al segnale
 * dell'aggregatore → null; A4 mai esaminato in attivo → null; A3
 * `termine_indicato` < oggi → `termine_passato`; A5 segnale dell'aggregatore →
 * `senza_conferma`; A6 termine indicato da oggi in poi → null; A7 pubblicato
 * da al massimo 7 giorni → null; A8 → `senza_conferma`.
 *
 * Lettura valida: `stato_letto` fra `STATI_LETTI`, `stato_letto_su` uguale
 * allo stato salvato e `stato_letto_at` presente. «Giorni fa» è la differenza
 * fra date civili di Roma, non fra ore.
 */
export function statoDaVerificare(
  campi: CampiDaVerificare,
  adesso: Date = new Date(),
): MotivoDaVerificare | null {
  const effettivo = statoEffettivo(campi, adesso);
  const ramoA = effettivo === 'aperto' && soloGiorno(campi.data_scadenza) === null;
  if (effettivo !== 'in apertura prossimamente' && !ramoA) return null;

  const oggi = todayRomeISO(adesso);
  const entro = (ms: number | null, giorni: number): boolean =>
    ms !== null && giorniFa(ms, oggi) <= giorni;

  const letto = valoreIn(STATI_LETTI, campi.stato_letto);
  const lettoAt = istante(campi.stato_letto_at);
  const lettura = letto !== null && lettoAt !== null && campi.stato_letto_su === campi.stato
    ? letto
    : null;
  const pubblicato = istante(campi.pubblicato_at);

  if (!ramoA) {
    const verificata = campi.data_apertura_verificata ?? campi.apertura_verificata;
    const apertura = soloGiorno(campi.data_apertura);
    if (verificata === true && apertura !== null) return null;
    if (apertura !== null && apertura < oggi) return 'data_apertura_passata';
    if (lettura !== null && lettura !== 'in apertura prossimamente') return 'smentito_dalla_fonte';
    if (istante(campi.esaminato_attivo_at) === null) return null;
    const previsto = soloGiorno(campi.previsto_entro);
    if (previsto !== null && previsto < oggi) return 'previsione_scaduta';
    if (lettura === 'in apertura prossimamente' && entro(lettoAt, GIORNI_VALIDITA_CONFERMA)) return null;
    if (entro(pubblicato, GIORNI_GRAZIA_PUBBLICAZIONE)) return null;
    return 'senza_conferma';
  }

  if (lettura !== null && lettura !== 'aperto') return 'smentito_dalla_fonte';
  const segnale = istante(campi.segnale_aggregatore_at);
  if (
    lettura === 'aperto'
    && lettoAt !== null
    && valoreIn(METODI_LETTURA, campi.stato_letto_metodo) === 'estrattore'
    && entro(lettoAt, GIORNI_VALIDITA_CONFERMA)
    && (segnale === null || lettoAt > segnale)
  ) return null;
  if (istante(campi.esaminato_attivo_at) === null) return null;
  const termine = soloGiorno(campi.termine_indicato);
  if (termine !== null && termine < oggi) return 'termine_passato';
  if (segnale !== null) return 'senza_conferma';
  if (termine !== null) return null;
  if (entro(pubblicato, GIORNI_GRAZIA_RAMO_A)) return null;
  return 'senza_conferma';
}

// Motivi che hanno senso accanto allo stato mostrato: quelli del ramo I per un
// «in apertura», quelli del ramo A per un «aperto».
const MOTIVI_PER_STATO: Readonly<Partial<Record<StatoBando, readonly MotivoDaVerificare[]>>> = {
  'in apertura prossimamente': [
    'data_apertura_passata', 'smentito_dalla_fonte', 'previsione_scaduta', 'senza_conferma',
  ],
  'aperto': ['smentito_dalla_fonte', 'termine_passato', 'senza_conferma'],
};

/**
 * Il motivo da mostrare accanto allo stato, o null. Il motivo arriva dalla
 * vista (calcolato sullo stato effettivo del DB), lo stato da chi mostra: la
 * scheda può sostituirlo con quello di un evento (una sospensione), l'API usa
 * la sua regola storica. Una coppia che la regola non può produrre (un
 * «sospeso» con un motivo, un «in apertura» con `termine_passato`) non si
 * mostra: meglio nessun bollino che un bollino che contraddice lo stato.
 */
export function motivoVisibile(
  stato: string | null | undefined,
  motivo: string | null | undefined,
): MotivoDaVerificare | null {
  const valido = valoreIn(MOTIVI_DA_VERIFICARE, motivo);
  const statoValidato = statoValido(stato);
  if (valido === null || statoValidato === null) return null;
  return MOTIVI_PER_STATO[statoValidato]?.includes(valido) ? valido : null;
}

/**
 * Il motivo di una riga letta dal DB, già passato da `motivoVisibile`.
 *
 * Dalla vista arriva la colonna `stato_da_verificare`, presente anche quando
 * vale null: è il DB che conosce lettura, termine ed esame in attivo. La
 * tabella non ha la colonna, e allora si calcola con i campi della riga
 * (`stato_bando`, date, `data_apertura_verificata`, `pubblicato_at`): lettura,
 * termine ed esame restano NULL, perché solo la vista li espone.
 */
export function motivoDellaRiga(
  riga: Readonly<Record<string, unknown>>,
  statoMostrato: string | null | undefined,
  adesso: Date = new Date(),
): MotivoDaVerificare | null {
  if ('stato_da_verificare' in riga) {
    const dallaVista = riga.stato_da_verificare;
    return motivoVisibile(statoMostrato, typeof dallaVista === 'string' ? dallaVista : null);
  }
  const testo = (chiave: string): string | null => {
    const valore = riga[chiave];
    return typeof valore === 'string' ? valore : null;
  };
  const calcolato = statoDaVerificare({
    stato: testo('stato_bando'),
    data_apertura: testo('data_apertura'),
    data_apertura_verificata: riga.data_apertura_verificata === true,
    ora_apertura: testo('ora_apertura'),
    data_scadenza: testo('data_scadenza'),
    ora_scadenza: testo('ora_scadenza'),
    pubblicato_at: testo('pubblicato_at'),
  }, adesso);
  return motivoVisibile(statoMostrato, calcolato);
}

/** Data civile di Roma (YYYY-MM-DD) di un timestamp, o null se manca o è malformato. */
export function giornoRoma(valore: string | null | undefined): string | null {
  const ms = istante(valore);
  return ms === null ? null : FORMATO_GIORNO_ROMA.format(new Date(ms));
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
