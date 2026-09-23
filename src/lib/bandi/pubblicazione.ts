/**
 * Un solo punto in cui è scritto «quali righe di `bando` sono pubbliche».
 *
 * Oggi la stessa coppia di condizioni (`stato_processing='completed'` e
 * `slug IS NOT NULL`) è ricopiata in quattro file. Non è ridondanza innocua: è
 * in AND con la RLS del DB, e finché BandoFit non migra al contratto un bando
 * pubblicato **non deve** uscire da `completed` durante le rielaborazioni. Chi
 * cambia il predicato deve poterlo fare in un posto solo.
 *
 * Dopo la migrazione 05 la lettura si sposta sulla vista `bando_pubblico`, che
 * il predicato ce l'ha dentro (`WHERE pubblicato`): lì le operazioni sono zero.
 *
 * Il flag che sceglie la fonte **non si legge qui**: questo è un modulo puro e
 * `PUBLIC_*` viene compilata al build, non è una variabile a runtime. Lo
 * leggono i moduli impuri (`supabase-bandi.ts`, `api-v1/rotta.ts`) e passano il
 * risultato a `fonteBandiDa`. Nessun ripiego automatico «se la vista manca»: il
 * ripiego è rimettere il flag a `bando`.
 *
 * Modulo «foglia»: nessun import, nessuna variabile d'ambiente.
 */

/**
 * Operatori PostgREST che il predicato usa. Volutamente stretto: e' un
 * sottoinsieme di `OperatoreFiltro` di `api-v1/contratto.ts`, cosi' le
 * operazioni si possono passare a `filtri.ts` senza nessuna conversione, e
 * nessuno puo' infilare qui un operatore che quel modulo non sa eseguire.
 */
export type OperatorePubblicazione = 'eq' | 'not.is';

/** Operazione del predicato: `[colonna, operatore, valore]`, come in `filtri.ts`. */
export type OperazionePubblicazione = readonly [string, OperatorePubblicazione, string];

export interface FonteBandi {
  readonly tabella: string;
  readonly operazioni: readonly OperazionePubblicazione[];
  /**
   * Il frammento di `select` che porta la **freschezza pubblica**, sempre sotto
   * il nome `updated_at` qualunque sia la fonte.
   *
   * Le due fonti la chiamano in modo diverso e non e' un dettaglio di nomi: su
   * `bando` la colonna e' `updated_at`, che l'upsert dello scrape riscrive a
   * ogni giro (3 969 righe toccate in sei minuti, misurate il 22/09) anche
   * quando niente e' cambiato per chi legge; sulla vista e'
   * `ultimo_cambiamento_at`, che si muove solo per una modifica pubblica. La
   * differenza si vede: sullo stesso bando la prima diceva 23 settembre e la
   * seconda 16 luglio.
   *
   * L'alias di PostgREST (`updated_at:ultimo_cambiamento_at`, verificato sulla
   * vista anche con gli embed) fa arrivare il campo col nome che i consumatori
   * usano gia', quindi il `lastmod` delle sitemap e l'`updated_since` dell'API
   * cambiano **significato** senza che una riga a valle cambi forma.
   *
   * Due campi e non uno, perche' servono in due posti che vogliono forme
   * diverse: `selectFreschezza` e' il frammento con l'alias e va nella
   * `select`; `colonnaFreschezza` e' il nome nudo e va nei **filtri** e negli
   * ordinamenti, dove un alias non e' ammesso. Confonderli darebbe 42703
   * proprio sul filtro `updated_since` dell'API.
   */
  readonly selectFreschezza: string;
  /** Il nome nudo della colonna, per filtri e `order`. */
  readonly colonnaFreschezza: string;
  /**
   * Le colonne del lavoro v11 che **solo la vista** sa dare: la fonte
   * ufficiale, i flag di verifica delle date, l'ora di scadenza, l'ultimo
   * controllo. Sulla tabella `bando` alcune esistono e altre no
   * (`ultimo_controllo_at` vive in `bando_controllo`, `stato_effettivo` e' un
   * calcolo della vista), e una sola colonna assente fa rispondere 42703 a
   * PostgREST, cioe' fa fallire l'intera richiesta. Per questo l'elenco e'
   * vuoto sulla tabella: meglio campi `null` in un contratto additivo che una
   * risorsa che risponde 500.
   */
  readonly colonneV11: readonly string[];
  /**
   * La colonna con lo stato **effettivo**, quando la fonte lo calcola lei.
   *
   * Sulla vista e' `stato_effettivo`: una condizione sola, esatta per
   * costruzione, e che sa cose che una ricostruzione lato client non puo'
   * sapere — l'ora di scadenza e se la data di apertura ha una prova.
   *
   * Sulla tabella e' `null`, e chi filtra deve ricostruire lo stato con un
   * intreccio di `or`/`and` su `stato_bando` e `data_scadenza`
   * (`filtro-stato.ts`). Quella ricostruzione e' corretta ma piu' grossolana, e
   * finche' esiste puo' divergere dal badge: e' il motivo per cui la vista e'
   * la destinazione e non un'alternativa.
   */
  readonly colonnaStato: string | null;
}

export const FONTI_BANDI = {
  bando: {
    tabella: 'bando',
    operazioni: [
      ['stato_processing', 'eq', 'completed'],
      ['slug', 'not.is', 'null'],
    ],
    selectFreschezza: 'updated_at',
    colonnaFreschezza: 'updated_at',
    colonneV11: [],
    colonnaStato: null,
  },
  bando_pubblico: {
    tabella: 'bando_pubblico',
    operazioni: [],
    selectFreschezza: 'updated_at:ultimo_cambiamento_at',
    colonnaFreschezza: 'ultimo_cambiamento_at',
    colonneV11: [
      'fonte_ufficiale_url', 'fonte_ufficiale_host', 'fonte_ufficiale_tipo',
      'fonte_ufficiale_stato', 'fonte_ufficiale_e_atto', 'fonte_ufficiale_verificata_at',
      'data_apertura_verificata', 'data_scadenza_verificata',
      'ora_scadenza', 'ultimo_controllo_at',
    ],
    colonnaStato: 'stato_effettivo',
  },
} as const satisfies Record<string, FonteBandi>;

export type NomeFonteBandi = keyof typeof FONTI_BANDI;

export const FONTE_BANDI_PREDEFINITA: NomeFonteBandi = 'bando';

/**
 * Fonti dichiarate ma **non ancora servibili**, con il motivo.
 *
 * Vuoto da F2 (23/09/2026), e va tenuto vuoto. Prima conteneva
 * `bando_pubblico`, perche' quattro select chiedevano `updated_at`, che sulla
 * vista non esiste: PostgREST risponde 42703 e fa fallire l'**intera**
 * richiesta, quindi la scheda di ogni bando, entrambe le sitemap e
 * `/api/v1/bandi` sarebbero andate in 500 insieme nell'istante in cui qualcuno
 * esportava la variabile. Ora quelle quattro select passano da
 * `FonteBandi.freschezza` e chiedono la colonna giusta per la fonte giusta.
 *
 * Il meccanismo resta perche' serve alla prossima volta: e' il modo di
 * dichiarare una fonte scritta nel codice ma non ancora pronta, senza che una
 * variabile d'ambiente possa spegnere il dominio bandi.
 * `tests/estrazioni/colonne-anon.test.ts` confronta le colonne citate dai
 * quattro file con quelle della migrazione 05 e impone di rimettere la guardia
 * se una colonna torna fuori dalla vista.
 */
export const FONTI_NON_PRONTE: Readonly<Record<string, string>> = {};

/** Il nome pulito del flag, o `null` se non nomina una fonte conosciuta. */
function nomeRiconosciuto(valore: string | null | undefined): NomeFonteBandi | null {
  if (typeof valore !== 'string') return null;
  const pulito = valore.trim();
  if (!Object.prototype.hasOwnProperty.call(FONTI_BANDI, pulito)) return null;
  const motivo = FONTI_NON_PRONTE[pulito];
  if (motivo !== undefined) {
    // Non si solleva: un errore qui spegnerebbe il sito esattamente come il
    // 42703 che si vuole evitare. Si scrive perché il flag è stato messo da
    // qualcuno che si aspetta un effetto, e non averlo va detto.
    console.warn(
      `[bandi] BANDI_FONTE_LETTURA=${pulito} ignorato: ${motivo}. Si legge da `
      + `\`${FONTE_BANDI_PREDEFINITA}\`.`,
    );
    return null;
  }
  return pulito as NomeFonteBandi;
}

/**
 * La fonte indicata dal flag, con `bando` come default. Un valore ignoto non
 * solleva e non «prova» la vista: torna la tabella, che esiste sempre. Una
 * fonte dichiarata ma non ancora servibile (`FONTI_NON_PRONTE`) fa lo stesso,
 * con un avviso.
 */
export function fonteBandiDa(valore: string | null | undefined): FonteBandi {
  const nome = nomeRiconosciuto(valore);
  return FONTI_BANDI[nome ?? FONTE_BANDI_PREDEFINITA];
}

/** Il nome della fonte indicata dal flag (per chi deve tipizzare il contesto). */
export function nomeFonteBandiDa(valore: string | null | undefined): NomeFonteBandi {
  return nomeRiconosciuto(valore) ?? FONTE_BANDI_PREDEFINITA;
}

/**
 * La fonte di un nome **gia' validato** dal flag.
 *
 * Le due funzioni sopra leggono una variabile d'ambiente e sono il posto in
 * cui la guardia di `FONTI_NON_PRONTE` deve stare. Questa no: riceve un
 * `NomeFonteBandi`, cioe' un valore che il confine ha gia' accettato, e si
 * limita a tradurlo. Rimetterci la guardia significherebbe rendere
 * inosservabile — e quindi non verificabile — l'instradamento verso la vista.
 */
export function fontePerNome(nome: NomeFonteBandi): FonteBandi {
  return FONTI_BANDI[nome];
}
