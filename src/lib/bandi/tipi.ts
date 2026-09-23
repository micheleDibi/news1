/**
 * Tipi del dominio bandi condivisi dai moduli puri di `src/lib/bandi/`.
 *
 * Vivono qui e non in `supabase-bandi.ts` perché quel file crea il client
 * Supabase a livello di modulo: importarlo da una foglia pura la renderebbe
 * impossibile da caricare sotto `node --test` senza variabili d'ambiente
 * (`tests/api-v1/purezza.test.ts` lo vieta). `supabase-bandi.ts` li ri-esporta,
 * così i chiamanti storici non cambiano import.
 *
 * Modulo di soli tipi: nessun valore a runtime, nessun import.
 */

// ---------------------------------------------------------------------------
// Contenuto editoriale generato dalla skill SEO
// ---------------------------------------------------------------------------

export type SegmentoBando =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'link'; text: string; url: string };

/**
 * Voce di FAQ nella forma che skill e tipi dichiarano: `{q, a: {segments}}`.
 * La forma `{question, answer}` esiste solo come tolleranza di lettura
 * (`contenuto.ts`): 23 schede sono state salvate così e verrebbero rese vuote.
 */
export interface VoceFaq {
  q: string;
  a: { segments: SegmentoBando[] };
}

export type SezioneBando =
  | { type: 'h2' | 'h3'; text: string }
  | { type: 'paragraph'; segments: SegmentoBando[] }
  | { type: 'bullet_list' | 'numbered_list'; items: Array<{ segments: SegmentoBando[] }> }
  | { type: 'faq'; items: VoceFaq[] };

export interface ContenutoBando {
  sections: SezioneBando[];
}

// ---------------------------------------------------------------------------
// Allegati
// ---------------------------------------------------------------------------

export const ALLEGATO_TIPI = [
  'pdf', 'doc', 'docx', 'zip', 'rtf', 'xlsx', 'xls', 'odt', 'ods',
] as const;
export type AllegatoTipo = typeof ALLEGATO_TIPI[number];

export interface Allegato {
  label: string;
  url: string;
  tipo: AllegatoTipo | string;
}

// ---------------------------------------------------------------------------
// Fonte ufficiale (P1). In F1 non esiste ancora nessuna colonna: i tipi ci sono
// perché i moduli puri siano già quelli definitivi, e i chiamanti passano null.
// ---------------------------------------------------------------------------

/**
 * Gerarchia di §13.2, due soli valori: `atto` è un sotto-tipo di `ente` (il PDF
 * dell'atto sul dominio dell'ente) e si distingue con `e_atto`, non con un terzo
 * valore dell'enumerazione.
 */
export const TIPI_FONTE_UFFICIALE = ['ente', 'portale_pubblico'] as const;
export type TipoFonteUfficiale = typeof TIPI_FONTE_UFFICIALE[number];

export const STATI_FONTE_UFFICIALE = ['trovata', 'in_verifica', 'non_trovata'] as const;
export type StatoFonteUfficiale = typeof STATI_FONTE_UFFICIALE[number];

export interface FonteUfficiale {
  readonly stato: StatoFonteUfficiale;
  readonly url: string | null;
  readonly host: string | null;
  readonly tipo: TipoFonteUfficiale | null;
  /** `true` quando l'URL punta al PDF dell'atto e non alla pagina dell'ente. */
  readonly e_atto?: boolean | null;
  /** Giorno (YYYY-MM-DD) in cui la fonte è stata verificata. */
  readonly verificata_il?: string | null;
}

// ---------------------------------------------------------------------------
// Link di un bando (tabella `bando_link`, disponibile solo da F2)
// ---------------------------------------------------------------------------

export const TIPI_LINK_BANDO = ['candidatura', 'portale', 'allegato', 'atto', 'altro'] as const;
export type TipoLinkBando = typeof TIPI_LINK_BANDO[number];

export interface LinkBando {
  readonly tipo: TipoLinkBando | string;
  readonly url: string;
  readonly etichetta?: string | null;
  /** Solo le righe pubblicabili escono da `bando_link` ad anon: cintura, non guardia. */
  readonly pubblicabile?: boolean | null;
}
