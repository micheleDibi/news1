import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.PUBLIC_SUPABASE_BANDI_URL;
const key = import.meta.env.PUBLIC_SUPABASE_BANDI_ANON_KEY;

export const supabaseBandi = createClient(url, key);

// Costanti di dominio note (output normalizzato della skill bandi-seo-enricher)
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

export const STATI_SCADENZA = ['aperto', 'in_scadenza', 'scaduto'] as const;
export type StatoScadenza = typeof STATI_SCADENZA[number];

// Provenienza della data di scadenza, settata dalla skill (fase 2).
// L'orchestrator sovrascrive `data_scadenza` nel DB solo se source ∈ {official_pdf, official_page}.
export const SCADENZA_SOURCES = [
  'official_pdf',
  'official_page',
  'inferred',
  'missing',
  'scraper_fallback',
] as const;
export type ScadenzaSource = typeof SCADENZA_SOURCES[number];

// Motivo per cui un record e' stato bocciato dalla skill (is_bando_confermato=false).
// Quando popolato, il record NON appare nel frontend (RLS lo filtra).
export const REJECTION_CATEGORIES = [
  'index_page',
  'search_results',
  'category_page',
  'expired_archive',
  'not_a_funding_call',
  'unreachable',
] as const;
export type RejectionCategory = typeof REJECTION_CATEGORIES[number];

// v3 — Verdetto del verifier adversarial (Claude Haiku 4.5) sul payload skill.
// 'verified' = il verifier ha confermato citation + coerenza date + verdetto is_valid_bando.
// 'refuted'  = il verifier ha trovato citazioni inventate, date incoerenti, aggregator passato come bando, ecc.
// 'skipped'  = il verifier non e' stato eseguibile (API down, markdown vuoto, anthropic SDK non configurato).
// La RLS nasconde solo 'refuted': NULL/verified/skipped sono visibili (skipped non e' un giudizio negativo).
export const VERIFIER_VERDICTS = ['verified', 'refuted', 'skipped'] as const;
export type VerifierVerdict = typeof VERIFIER_VERDICTS[number];

export const ALLEGATO_TIPI = [
  'pdf', 'doc', 'docx', 'zip', 'rtf', 'xlsx', 'xls', 'odt', 'ods', 'altro',
] as const;
export type AllegatoTipo = typeof ALLEGATO_TIPI[number];

export interface Allegato {
  label: string;
  url: string;
  tipo: AllegatoTipo;
}

// Tipo del bando "pubblico" (ciò che il frontend legge da DB B con anon key + RLS).
// Mappa 1:1 con le colonne SEO aggiunte da:
//   backend/sql/bando_alter_seo_fields.sql
//   backend/sql/bando_alter_filters_and_attachments.sql
export interface Bando {
  id: number;
  // Dati dallo scraper (rimangono utili per la card / dettaglio)
  titolo: string | null;
  descrizione: string | null;
  link_bando: string;
  codice_bando: string | null;
  fondo: string | null;
  stato_bando: string | null;
  data_pubblicazione: string | null;
  data_apertura: string | null;
  data_scadenza: string | null;
  importo: string | null;
  importo_numerico: number | null;
  ultimo_scraping_at: string | null;
  // Colonne SEO popolate dalla skill (bando_alter_seo_fields.sql)
  slug: string;
  seo_livello: 'flash_bando' | 'guida_bando' | null;
  seo_titolo: string | null;
  seo_occhiello: string | null;
  seo_descrizione_breve: string | null;
  seo_meta_title: string | null;
  seo_meta_description: string | null;
  seo_contenuto: { sections: BandoSection[] } | null;
  seo_validation: Record<string, unknown> | null;
  ente_erogatore: string | null;
  tipologia_normalizzata: TipologiaBando | null;
  area_geografica: string | null;
  tematica: string[] | null;
  beneficiari_norm: string[] | null;
  scadenza_stato: StatoScadenza | null;
  importo_totale_eur: number | null;
  importo_max_per_progetto_eur: number | null;
  link_candidatura: string | null;
  link_candidatura_verified: boolean | null;
  riferimento_normativo: string | null;
  skill_processing_status: string;
  // Colonne nuove (bando_alter_filters_and_attachments.sql)
  allegati: Allegato[] | null;
  codici_ateco_norm: string[] | null;
  programma_nome: string | null;
  modalita_erogazione_nome: string | null;
  // Colonne nuove (bando_alter_validation_v2.sql)
  is_bando_confermato: boolean | null;
  data_scadenza_source: ScadenzaSource | null;
  validation_reason: string | null;
  rejection_category: RejectionCategory | null;
  // Colonne nuove (bando_alter_data_pubblicazione_source.sql)
  data_pubblicazione_source: ScadenzaSource | null;
  // Colonne nuove v3 (bando_alter_date_quotes_and_verifier.sql) — citation strict + verifier
  data_scadenza_quote: string | null;
  data_pubblicazione_quote: string | null;
  skill_verifier_verdict: VerifierVerdict | null;
  skill_verifier_notes: string | null;
  skill_verifier_refuted_fields: string[] | null;
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

export interface Regione { id: number; nome: string }
export interface Settore { id: number; nome: string }
export interface Beneficiario { id: number; nome: string }
export interface CodiceAteco { id: number; codice: string; descrizione: string | null }
export interface Programma { id: number; nome: string }
export interface ModalitaErogazione { id: number; nome: string }
