import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.PUBLIC_SUPABASE_BANDI_URL;
const key = import.meta.env.PUBLIC_SUPABASE_BANDI_ANON_KEY;

export const supabaseBandi = createClient(url, key);

// =========================================================================
// Costanti di dominio (schema v9 — vedi backend/sql/bando_alter_v9_*.sql)
// =========================================================================

// Stato pipeline interno (vedi CHECK bando_stato_processing_check).
// Frontend pubblico vede SOLO stato_processing='completed' (RLS v9).
export const STATI_PROCESSING = [
  'scraped', 'processed', 'rejected', 'enriched', 'completed',
] as const;
export type StatoProcessing = typeof STATI_PROCESSING[number];

// Stato editoriale del bando (data-driven dal preprocess v2).
export const STATI_BANDO = ['aperto', 'chiuso', 'in apertura prossimamente'] as const;
export type StatoBando = typeof STATI_BANDO[number];

// Stato scadenza calcolato in-app (NON colonna DB).
export const STATI_SCADENZA = ['aperto', 'in_scadenza', 'scaduto'] as const;
export type StatoScadenza = typeof STATI_SCADENZA[number];

// Livello editoriale emesso dalla skill SEO v8.
export const LIVELLI_BANDO = ['flash_bando', 'guida_bando'] as const;
export type LivelloBando = typeof LIVELLI_BANDO[number];

// Provenienza del link candidatura.
export const LINK_CANDIDATURA_SOURCES = ['extracted', 'fallback_source', 'missing'] as const;
export type LinkCandidaturaSource = typeof LINK_CANDIDATURA_SOURCES[number];

// Tipo link fonte (scraper).
export const TIPI_LINK = ['Opportunità', 'Preavviso'] as const;
export type TipoLink = typeof TIPI_LINK[number];

// Tipologie allegati supportate dalla skill SEO.
export const ALLEGATO_TIPI = [
  'pdf', 'doc', 'docx', 'zip', 'rtf', 'xlsx', 'xls', 'odt', 'ods',
] as const;
export type AllegatoTipo = typeof ALLEGATO_TIPI[number];

export interface Allegato {
  label: string;
  url: string;
  tipo: AllegatoTipo | string;
}

// Sezioni del contenuto editoriale generato dalla skill SEO v8.
export type BandoSegment =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'link'; text: string; url: string };

export type BandoSection =
  | { type: 'h2' | 'h3'; text: string }
  | { type: 'paragraph'; segments: BandoSegment[] }
  | { type: 'bullet_list' | 'numbered_list'; items: Array<{ segments: BandoSegment[] }> }
  | { type: 'faq'; items: Array<{ q: string; a: { segments: BandoSegment[] } }> };

// =========================================================================
// Tipo principale Bando (schema v9 — frontend pubblico)
// =========================================================================

/**
 * Bando come letto dalla tabella `bando` post-v9.
 * RLS public: stato_processing='completed' AND slug IS NOT NULL.
 * Colonne droppate (v4-v8): state, state_detail, date_quotes, tipologia,
 * programma, modalita_erogazione, beneficiari, codici_ateco, attempts,
 * is_bando_confermato — NON sono qui.
 */
export interface Bando {
  // Identita'
  id: number;
  fonte_id: number;
  hash_bando: string;
  tipo_link: TipoLink | null;

  // Pipeline state
  stato_processing: StatoProcessing;
  stato_bando: StatoBando | null;
  confidence_score: number | null;
  rejection_reason: string | null;

  // FK classificazione (enricher v7)
  tipologia_bando_id: number | null;
  modalita_erogazione_id: number | null;
  programma_id: number | null;

  // Date (preprocess v2 + reconciliation data-driven)
  data_pubblicazione: string | null;  // YYYY-MM-DD
  data_apertura: string | null;
  data_scadenza: string | null;

  // Skill SEO output (v8 — 14 campi editoriali)
  slug: string;
  titolo: string | null;
  titolo_breve: string | null;
  descrizione_breve: string | null;
  contenuto: { sections: BandoSection[] } | null;
  livello: LivelloBando | null;
  allegati: Allegato[] | null;
  ente_erogatore: string | null;
  area_geografica: string | null;
  tematica: string[] | null;
  importo_totale_eur: number | null;
  importo_max_per_progetto_eur: number | null;
  link_candidatura: string | null;
  link_candidatura_source: LinkCandidaturaSource | null;

  // Raw scraper (per dettaglio link "vai alla fonte")
  link_bando: string | null;
  titolo_raw: string | null;

  // Audit
  created_at: string;
  updated_at: string;
}

/**
 * Bando con relazioni FK + junction risolte a nomi leggibili.
 * Costruito da resolveBandoRelations() per la pagina dettaglio.
 */
export interface BandoDetail extends Bando {
  tipologia_nome: string | null;       // tipologie_bando.nome via FK
  modalita_nome: string | null;        // modalita_erogazione.nome via FK
  programma_nome: string | null;       // programmi.nome via FK
  beneficiari_nomi: string[];          // via junction bando_beneficiari
  regioni_nomi: string[];              // via junction bando_regioni
  settori_nomi: string[];              // via junction bando_settori
  codici_ateco_resolved: CodiceAteco[]; // via junction bando_codici_ateco
}

// =========================================================================
// Catalogo (read-only)
// =========================================================================

export interface CatalogoRow { id: number; nome: string }
export interface CodiceAteco { id: number; codice: string; descrizione: string | null }

export interface Catalogo {
  tipologie: CatalogoRow[];
  programmi: CatalogoRow[];
  modalita: CatalogoRow[];
  beneficiari: CatalogoRow[];
  codici_ateco: CodiceAteco[];
  regioni: CatalogoRow[];
  settori: CatalogoRow[];
}

let _catalogoCache: Catalogo | null = null;
let _catalogoPromise: Promise<Catalogo> | null = null;

/**
 * Carica e cacha il catalogo completo (singleton per processo).
 * Chiamare prima di renderizzare lista bandi o dettaglio.
 */
export async function loadCatalogo(): Promise<Catalogo> {
  if (_catalogoCache) return _catalogoCache;
  if (_catalogoPromise) return _catalogoPromise;

  _catalogoPromise = (async () => {
    const [
      tipologie, programmi, modalita, beneficiari,
      codici_ateco, regioni, settori,
    ] = await Promise.all([
      supabaseBandi.from('tipologie_bando').select('id, nome').order('id'),
      supabaseBandi.from('programmi').select('id, nome').order('nome'),
      supabaseBandi.from('modalita_erogazione').select('id, nome').order('id'),
      supabaseBandi.from('beneficiari').select('id, nome').order('nome'),
      supabaseBandi.from('codici_ateco').select('id, codice, descrizione').order('codice'),
      supabaseBandi.from('regioni').select('id, nome').order('nome'),
      supabaseBandi.from('settori').select('id, nome').order('nome'),
    ]);
    const cat: Catalogo = {
      tipologie: (tipologie.data ?? []) as CatalogoRow[],
      programmi: (programmi.data ?? []) as CatalogoRow[],
      modalita: (modalita.data ?? []) as CatalogoRow[],
      beneficiari: (beneficiari.data ?? []) as CatalogoRow[],
      codici_ateco: (codici_ateco.data ?? []) as CodiceAteco[],
      regioni: (regioni.data ?? []) as CatalogoRow[],
      settori: (settori.data ?? []) as CatalogoRow[],
    };
    _catalogoCache = cat;
    _catalogoPromise = null;
    return cat;
  })();
  return _catalogoPromise;
}

/**
 * Lookup nome catalogo per FK id. Ritorna null se non trovato.
 */
export function lookupNome(rows: CatalogoRow[], id: number | null): string | null {
  if (id == null) return null;
  const r = rows.find(x => x.id === id);
  return r ? r.nome : null;
}

/**
 * Risolve le relazioni FK + junction di un singolo bando.
 * 4 SELECT su junction + lookup nomi locale dal catalogo.
 */
export async function resolveBandoRelations(
  bando: Bando, catalogo: Catalogo,
): Promise<BandoDetail> {
  const [benRes, regRes, setRes, atecoRes] = await Promise.all([
    supabaseBandi.from('bando_beneficiari').select('beneficiario_id').eq('bando_id', bando.id),
    supabaseBandi.from('bando_regioni').select('regione_id').eq('bando_id', bando.id),
    supabaseBandi.from('bando_settori').select('settore_id').eq('bando_id', bando.id),
    supabaseBandi.from('bando_codici_ateco').select('codice_ateco_id').eq('bando_id', bando.id),
  ]);

  const benIds = (benRes.data ?? []).map((r: any) => r.beneficiario_id);
  const regIds = (regRes.data ?? []).map((r: any) => r.regione_id);
  const setIds = (setRes.data ?? []).map((r: any) => r.settore_id);
  const atecoIds = (atecoRes.data ?? []).map((r: any) => r.codice_ateco_id);

  const beneficiari_nomi = benIds.map(i => lookupNome(catalogo.beneficiari, i)).filter(Boolean) as string[];
  const regioni_nomi = regIds.map(i => lookupNome(catalogo.regioni, i)).filter(Boolean) as string[];
  const settori_nomi = setIds.map(i => lookupNome(catalogo.settori, i)).filter(Boolean) as string[];
  const codici_ateco_resolved = atecoIds
    .map(i => catalogo.codici_ateco.find(c => c.id === i))
    .filter(Boolean) as CodiceAteco[];

  return {
    ...bando,
    tipologia_nome: lookupNome(catalogo.tipologie, bando.tipologia_bando_id),
    modalita_nome: lookupNome(catalogo.modalita, bando.modalita_erogazione_id),
    programma_nome: lookupNome(catalogo.programmi, bando.programma_id),
    beneficiari_nomi,
    regioni_nomi,
    settori_nomi,
    codici_ateco_resolved,
  };
}

// =========================================================================
// Helper runtime
// =========================================================================

/**
 * Calcola lo `scadenza_stato` in JS at-render-time (NON colonna DB).
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

/**
 * Formatta un importo EUR senza decimali in italiano (es. "12.500.000 €").
 */
export function formatImportoEur(value: number | null): string | null {
  if (value == null) return null;
  return new Intl.NumberFormat('it-IT').format(value) + ' €';
}

/**
 * Colonne SELECT per la lista bandi (compatte, no contenuto).
 */
export const BANDO_SELECT_LIST = [
  'id', 'slug', 'titolo', 'titolo_breve', 'descrizione_breve',
  'ente_erogatore', 'area_geografica', 'tematica',
  'data_pubblicazione', 'data_apertura', 'data_scadenza',
  'importo_totale_eur', 'importo_max_per_progetto_eur',
  'link_bando', 'stato_bando',
  'tipologia_bando_id', 'modalita_erogazione_id', 'programma_id',
].join(', ');

/**
 * Colonne SELECT per il dettaglio bando (complete).
 */
export const BANDO_SELECT_DETAIL = [
  'id', 'fonte_id', 'hash_bando', 'tipo_link',
  'stato_processing', 'stato_bando', 'confidence_score',
  'data_pubblicazione', 'data_apertura', 'data_scadenza',
  'tipologia_bando_id', 'modalita_erogazione_id', 'programma_id',
  'slug', 'titolo', 'titolo_breve', 'descrizione_breve', 'contenuto',
  'livello', 'allegati',
  'ente_erogatore', 'area_geografica', 'tematica',
  'importo_totale_eur', 'importo_max_per_progetto_eur',
  'link_candidatura', 'link_candidatura_source',
  'link_bando', 'titolo_raw',
  'created_at', 'updated_at',
].join(', ');
