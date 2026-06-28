import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.PUBLIC_SUPABASE_BANDI_URL;
const key = import.meta.env.PUBLIC_SUPABASE_BANDI_ANON_KEY;

export const supabaseBandi = createClient(url, key);

// Costanti di dominio (schema v4 — vedi backend/sql/bando_v4_collapse.sql)

export const TIPOLOGIE_BANDO = [
  'FESR',
  'FSE',
  'Interreg',
  'nazionale',
  'regionale',
  'misto',
  'JTF',
] as const;
export type TipologiaBando = typeof TIPOLOGIE_BANDO[number];

// Stato scadenza calcolato in-app (NON colonna DB v4): aperto/in_scadenza (≤7gg)/scaduto.
export const STATI_SCADENZA = ['aperto', 'in_scadenza', 'scaduto'] as const;
export type StatoScadenza = typeof STATI_SCADENZA[number];

// Provenienza delle date emessa dalla skill.
// L'orchestrator sovrascrive `data_scadenza`/`data_pubblicazione` nel DB SOLO se
// source ∈ {official_pdf, official_page}. Altrimenti resta la data scraper-side.
export const DATE_SOURCES = [
  'official_pdf',
  'official_page',
  'inferred',
  'missing',
  'scraper_fallback',
] as const;
export type DateSource = typeof DATE_SOURCES[number];

// Stato della state machine `bando.state` (vedi enum SQL `bando_state`).
// Solo `confirmed` viene mostrato pubblicamente (RLS bando_public_read).
export const BANDO_STATES = [
  'discovered', // scraper l'ha trovato, skill mai chiamata o reset post-migrazione
  'enriching',  // skill in corso (lock soft, attempts++)
  'confirmed',  // skill ha confermato + verifier ∈ {verified, skipped} → PUBBLICO
  'rejected',   // skill ha bocciato (state_detail.rejection_category)
  'refuted',    // verifier Haiku 4.5 ha smentito la skill
  'error',      // transient error, riprovabile (attempts < BANDI_SKILL_MAX_ATTEMPTS)
  'stale',      // fonte non più raggiungibile dopo N tentativi
] as const;
export type BandoState = typeof BANDO_STATES[number];

// Motivo per cui un record è stato bocciato (state='rejected' o 'refuted').
// Persistito in state_detail.rejection_category.
export const REJECTION_CATEGORIES = [
  'index_page',
  'search_results',
  'category_page',
  'expired_archive',
  'not_a_funding_call',
  'unreachable',
] as const;
export type RejectionCategory = typeof REJECTION_CATEGORIES[number];

// Verdetto del verifier adversarial Claude Haiku 4.5 (in state_detail.verifier_verdict).
// 'refuted' → state='refuted' (record nascosto); 'verified'/'skipped'/null → state derivato da skill.
export const VERIFIER_VERDICTS = ['verified', 'refuted', 'skipped'] as const;
export type VerifierVerdict = typeof VERIFIER_VERDICTS[number];

// Provenienza del link candidatura.
export const LINK_CANDIDATURA_SOURCES = ['extracted', 'fallback_source', 'missing'] as const;
export type LinkCandidaturaSource = typeof LINK_CANDIDATURA_SOURCES[number];

// Tipologie allegati supportate dalla skill.
export const ALLEGATO_TIPI = [
  'pdf', 'doc', 'docx', 'zip', 'rtf', 'xlsx', 'xls', 'odt', 'ods', 'altro',
] as const;
export type AllegatoTipo = typeof ALLEGATO_TIPI[number];

export interface Allegato {
  label: string;
  url: string;
  tipo: AllegatoTipo;
}

// Citation strict per le date: la skill emette {value, source, quote} in date_quotes JSONB.
// quote = frammento letterale del markdown sorgente (max 300 char) o null se source='missing'.
export interface DateQuote {
  value: string | null;
  source: DateSource | null;
  quote: string | null;
}

// Dettaglio JSONB del verdetto persistito in `bando.state_detail`.
// Tutti i campi opzionali — il payload varia a seconda dello state.
export interface BandoStateDetail {
  rejection_category?: RejectionCategory | null;
  validation_reason?: string | null;
  verifier_verdict?: VerifierVerdict | null;
  verifier_notes?: string | null;
  refuted_fields?: string[] | null;
  last_error?: string | null;
  last_error_at?: string | null;
}

// Tipo "pubblico" del bando (ciò che il frontend legge da DB B con anon key + RLS).
// Mappa 1:1 con le colonne sopravvissute alla migrazione v4
// (`backend/sql/bando_v4_collapse.sql`).
export interface Bando {
  id: number;
  fonte_id: number;
  link_bando: string;           // URL del bando (rimasto col nome legacy)
  hash_bando: string;
  primo_scraping_at: string | null;
  ultimo_scraping_at: string | null;

  // State machine v4 — single source of truth.
  state: BandoState;
  state_detail: BandoStateDetail | null;
  state_updated_at: string;
  attempts: number;

  // Editorial (skill autoritativa). Popolato quando state='confirmed'.
  slug: string;
  livello: 'flash_bando' | 'guida_bando' | null;
  titolo: string | null;
  titolo_breve: string | null;
  descrizione_breve: string | null;
  contenuto: { sections: BandoSection[] } | null;

  // Date (skill può sovrascrivere data_pubblicazione / data_scadenza se source ∈ official_*).
  data_pubblicazione: string | null;
  data_apertura: string | null;
  data_scadenza: string | null;
  date_quotes: { pubblicazione: DateQuote | null; scadenza: DateQuote | null } | null;

  // Amounts (skill autoritativi).
  importo_totale_eur: number | null;
  importo_max_per_progetto_eur: number | null;

  // Classification (skill normalizzata, no FK).
  tipologia: TipologiaBando | null;
  programma: string | null;
  modalita_erogazione: string | null;
  area_geografica: string | null;
  tematica: string[] | null;
  beneficiari: string[] | null;
  codici_ateco: string[] | null;

  // Source/Ente
  ente_erogatore: string | null;

  // Links
  link_candidatura: string | null;
  link_candidatura_source: LinkCandidaturaSource | null;

  // Allegati
  allegati: Allegato[] | null;
}

// Sezioni del contenuto editoriale generato dalla skill.
export type BandoSection =
  | { type: 'h2' | 'h3'; text: string }
  | { type: 'paragraph'; segments: Array<{ kind: 'text' | 'bold' | 'link'; text: string; url?: string }> }
  | {
      type: 'bullet_list' | 'numbered_list';
      items: Array<{ segments: Array<{ kind: 'text' | 'bold' | 'link'; text: string; url?: string }> }>;
    }
  | { type: 'faq'; items: Array<{ question: string; answer: string }> };

// Dizionari catalogo (resta come read-only per i dropdown filtri frontend).
// I FK su `bando` sono stati droppati nella migrazione v4: i bandi tengono solo i
// nomi normalizzati skill-emitted (tipologia, programma, beneficiari[], ecc.).
export interface Regione { id: number; nome: string }
export interface Settore { id: number; nome: string }
export interface Beneficiario { id: number; nome: string }
export interface CodiceAteco { id: number; codice: string; descrizione: string | null }
export interface Programma { id: number; nome: string }
export interface ModalitaErogazione { id: number; nome: string }

// -------------------------------------------------------------
// Helper runtime
// -------------------------------------------------------------

/**
 * Calcola lo `scadenza_stato` in JS at-render-time (NON colonna DB v4).
 *  - null se data scadenza assente
 *  - 'scaduto' se data passata
 *  - 'in_scadenza' se mancano ≤7 giorni
 *  - 'aperto' altrimenti
 */
export function computeScadenzaStato(dataScadenza: string | null): StatoScadenza | null {
  if (!dataScadenza) return null;
  const scad = new Date(dataScadenza);
  if (Number.isNaN(scad.getTime())) return null;
  const now = new Date();
  const diffDays = Math.ceil((scad.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return 'scaduto';
  if (diffDays <= 7) return 'in_scadenza';
  return 'aperto';
}
