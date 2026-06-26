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

// Tipo del bando "pubblico" (ciò che il frontend legge da DB B con anon key + RLS).
// Mappa 1:1 con le colonne SEO aggiunte da backend/sql/bando_alter_seo_fields.sql.
export interface Bando {
  id: number;
  // Dati dallo scraper (rimangono utili per la card / dettaglio)
  titolo: string | null;            // titolo grezzo (fallback)
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
  // Colonne SEO popolate dalla skill
  slug: string;
  seo_livello: 'flash_bando' | 'guida_bando' | null;
  seo_titolo: string | null;
  seo_occhiello: string | null;
  seo_descrizione_breve: string | null;
  seo_meta_title: string | null;
  seo_meta_description: string | null;
  seo_contenuto: { sections: BandoSection[] } | null;
  seo_factcheck: Array<{ dato: string; stato: string; fonte_primaria: string }> | null;
  seo_fonti: Array<{ dato: string; fonte_url: string }> | null;
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
  riferimento_normativo: string | null;
  skill_processing_status: string;
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
