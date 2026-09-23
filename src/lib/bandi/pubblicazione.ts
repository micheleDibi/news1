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
}

export const FONTI_BANDI = {
  bando: {
    tabella: 'bando',
    operazioni: [
      ['stato_processing', 'eq', 'completed'],
      ['slug', 'not.is', 'null'],
    ],
  },
  bando_pubblico: {
    tabella: 'bando_pubblico',
    operazioni: [],
  },
} as const satisfies Record<string, FonteBandi>;

export type NomeFonteBandi = keyof typeof FONTI_BANDI;

export const FONTE_BANDI_PREDEFINITA: NomeFonteBandi = 'bando';

/**
 * Fonti dichiarate ma **non ancora servibili**, con il motivo.
 *
 * `bando_pubblico` espone `ultimo_cambiamento_at`, non `updated_at`, e quattro
 * select chiedono ancora `updated_at`: `supabase-bandi.ts`
 * (`BANDO_SELECT_DETTAGLIO`), `api-v1/colonne.ts` (`SELECT_BANDO`),
 * `sitemap-index.xml.ts` e `sitemap-bandi/[pagina].xml.ts`. PostgREST
 * risponde 42703 e fa fallire l'**intera** richiesta: la scheda di ogni
 * bando, entrambe le sitemap e `/api/v1/bandi` andrebbero in 500 insieme,
 * tutti nello stesso istante in cui qualcuno esporta la variabile.
 *
 * Finché il lavoro F2 non ha spostato quelle select, il flag si ignora: è
 * l'unica riga che sta fra una variabile d'ambiente e il dominio bandi spento.
 * Toglierla è il primo passo di F2, non un dettaglio.
 */
export const FONTI_NON_PRONTE: Readonly<Record<string, string>> = {
  bando_pubblico:
    'la vista espone `ultimo_cambiamento_at`, non `updated_at`: quattro select '
    + 'lo chiedono ancora e PostgREST risponderebbe 42703 su scheda, sitemap e /api/v1/bandi',
};

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
