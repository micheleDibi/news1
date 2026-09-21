/**
 * Tipi condivisi dell'API pubblica /api/v1: DTO in uscita, righe lette dal DB,
 * riferimenti in memoria e piano delle query. Solo tipi: nessun valore a runtime.
 *
 * Regole del contratto (vedi anche openapi.ts):
 * - ogni campo dei DTO e' sempre presente; `null` = non disponibile;
 * - gli array non sono mai null, le stringhe mai vuote;
 * - istanti RFC 3339 con l'offset di Europe/Rome, date di calendario YYYY-MM-DD;
 * - URL sempre assoluti.
 */

/** Risorse con elenco paginato. */
export type Risorsa = 'articles' | 'interpelli' | 'selezione-personale' | 'bandi';

/** Le tre sezioni "opportunita'" del sito (chiavi di CATEGORY_COLORS e di configSezione). */
export type SezioneOpportunita = 'interpelli' | 'selezione-personale' | 'bandi';

export type TipoOpportunita = 'interpello' | 'selezione-personale' | 'bando';
export type StatoOpportunita = 'open' | 'closed' | 'upcoming';
export type Db = 'principale' | 'bandi';

// ---------------------------------------------------------------------------
// DTO in uscita
// ---------------------------------------------------------------------------

export interface RegioneDto {
  slug: string;
  name: string;
}

export interface SezioneDto {
  slug: SezioneOpportunita;
  name: string;
  color: string;
  url: string;
}

export interface CategoriaArticoloDto {
  slug: string;
  name: string;
  color: string;
  url: string;
}

export interface CategoriaSecondariaDto {
  slug: string;
  name: string;
}

export interface VideoDto {
  url: string;
  mime_type: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
}

export interface AutoreDto {
  name: string;
}

export interface ArticoloDto {
  type: 'article';
  id: number;
  slug: string;
  url: string;
  title: string;
  title_summary: string | null;
  excerpt: string | null;
  summary: string | null;
  category: CategoriaArticoloDto;
  secondary_categories: CategoriaSecondariaDto[];
  image_url: string | null;
  thumbnail_url: string | null;
  video: VideoDto | null;
  published_at: string;
  tags: string[];
  author: AutoreDto;
}

export interface CategoriaDto {
  slug: string;
  name: string;
  color: string;
  position: number | null;
  url: string;
  secondary_categories: CategoriaSecondariaDto[];
  links: {
    articles: string;
    feed_json: string;
    feed_rss: string;
  };
}

export interface OpportunitaBaseDto {
  type: TipoOpportunita;
  id: number;
  slug: string;
  url: string;
  title: string;
  summary: string | null;
  section: SezioneDto;
  published_at: string;
  updated_at: string | null;
  deadline_on: string | null;
  deadline_at: string | null;
  status: StatoOpportunita | null;
  regions: RegioneDto[];
  national: boolean;
}

export interface DettagliInterpello {
  official_title: string | null;
  competition_class: string | null;
  province: string | null;
  city: string | null;
}

export interface DettagliSelezione {
  official_title: string | null;
  code: string | null;
  position: string | null;
  positions_count: number | null;
  procedure_type: string | null;
  categories: string[];
  sectors: string[];
  organizations: string[];
  locations: string[];
  salary_min: number | null;
  salary_max: number | null;
}

export interface CodiceAtecoDto {
  code: string;
  description: string | null;
}

export interface DettagliBando {
  short_title: string | null;
  issuer: string | null;
  geographic_area: string | null;
  topics: string[];
  kind: string | null;
  program: string | null;
  funding_method: string | null;
  sectors: string[];
  beneficiaries: string[];
  ateco_codes: CodiceAtecoDto[];
  total_amount_eur: number | null;
  max_amount_per_project_eur: number | null;
  opens_on: string | null;
  source_published_on: string | null;
}

export interface InterpelloDto extends OpportunitaBaseDto {
  type: 'interpello';
  details: DettagliInterpello;
}

export interface SelezioneDto extends OpportunitaBaseDto {
  type: 'selezione-personale';
  details: DettagliSelezione;
}

export interface BandoDto extends OpportunitaBaseDto {
  type: 'bando';
  details: DettagliBando;
}

export type OpportunitaDto = InterpelloDto | SelezioneDto | BandoDto;

// ---------------------------------------------------------------------------
// Righe lette dal DB (una per costante di colonne.ts). I valori sono `unknown`:
// i mapper li validano uno per uno, niente fiducia sulla forma.
// ---------------------------------------------------------------------------

export interface RigaArticolo {
  id: unknown;
  slug: unknown;
  title: unknown;
  title_summary: unknown;
  excerpt: unknown;
  summary: unknown;
  category_slug: unknown;
  secondary_category_slugs: unknown;
  image_url: unknown;
  thumbnail_url: unknown;
  video_url: unknown;
  video_duration: unknown;
  published_at: unknown;
  tags: unknown;
  /** Solo per il lookup dell'autore: MAI in uscita (contiene il nome reale). */
  creator: unknown;
}

export interface RigaInterpello {
  id: unknown;
  interpello_name: unknown;
  interpello_date: unknown;
  interpello_description: unknown;
  interpello_regione: unknown;
  interpello_provincia: unknown;
  interpello_citta: unknown;
  classe_concorso: unknown;
  article_title: unknown;
  article_subtitle: unknown;
}

export interface RigaSelezione {
  id: unknown;
  slug: unknown;
  codice: unknown;
  titolo: unknown;
  article_title: unknown;
  article_subtitle: unknown;
  figura_ricercata: unknown;
  num_posti: unknown;
  tipo_procedura: unknown;
  data_pubblicazione: unknown;
  data_scadenza: unknown;
  sedi: unknown;
  categorie: unknown;
  settori: unknown;
  enti_riferimento: unknown;
  salary_min: unknown;
  salary_max: unknown;
  updated_at: unknown;
}

export interface RigaBando {
  id: unknown;
  slug: unknown;
  titolo: unknown;
  titolo_breve: unknown;
  descrizione_breve: unknown;
  ente_erogatore: unknown;
  area_geografica: unknown;
  tematica: unknown;
  data_pubblicazione: unknown;
  data_apertura: unknown;
  data_scadenza: unknown;
  importo_totale_eur: unknown;
  importo_max_per_progetto_eur: unknown;
  stato_bando: unknown;
  created_at: unknown;
  updated_at: unknown;
  /** Embed PostgREST: oggetto, array o null a seconda della cardinalita'. */
  tipologia: unknown;
  programma: unknown;
  modalita: unknown;
  bando_regioni: unknown;
  bando_settori: unknown;
  bando_beneficiari: unknown;
  bando_codici_ateco: unknown;
}

export interface RigaCategoria {
  slug: unknown;
  name: unknown;
  color: unknown;
  order_id: unknown;
}

export interface RigaSecondaria {
  slug: unknown;
  name: unknown;
  parent_category_slug: unknown;
}

export interface RigaProfilo {
  id: unknown;
  full_name: unknown;
  public_name: unknown;
  is_displayable: unknown;
}

// ---------------------------------------------------------------------------
// Riferimenti in memoria (costruiti da riferimenti.ts, validati)
// ---------------------------------------------------------------------------

export interface CategoriaRif {
  slug: string;
  name: string;
  /** Hex gia' risolto con getCategoryHex. */
  color: string;
  position: number | null;
  url: string;
}

export interface SecondariaRif {
  slug: string;
  name: string;
  parent: string;
}

export interface RiferimentoCategorie {
  /** slug -> categoria valida. Solo questa mappa alimenta filtri, whitelist e `allowed`. */
  perSlug: ReadonlyMap<string, CategoriaRif>;
  /** Categorie nell'ordine di esposizione: position asc (null in fondo), poi slug. */
  ordinate: readonly CategoriaRif[];
  /** parent -> secondarie valide, ordinate per nome (collator it), poi slug. */
  secondariePerParent: ReadonlyMap<string, readonly SecondariaRif[]>;
}

export interface ProfiloRif {
  id: string;
  fullName: string | null;
  publicName: string | null;
  visualizzabile: boolean;
}

export interface RiferimentoProfili {
  perId: ReadonlyMap<string, ProfiloRif>;
  /** full_name esatto -> profili con quel nome (piu' di uno = ambiguo). */
  perNomeCompleto: ReadonlyMap<string, readonly ProfiloRif[]>;
}

// ---------------------------------------------------------------------------
// Piano delle query (filtri.ts lo produce, fonte-supabase.ts lo esegue)
// ---------------------------------------------------------------------------

export type Tabella =
  | 'articles'
  | 'interpelli'
  | 'selezione_personale'
  | 'bando'
  | 'categories'
  | 'secondary_categories'
  | 'profiles';

export type NomeSelect =
  | 'articolo'
  | 'interpello'
  | 'selezione'
  | 'bando'
  | 'bando-con-regione'
  | 'categorie'
  | 'secondarie'
  | 'profili';

/** Operatori PostgREST ammessi nei piani (passati a builder.filter(colonna, operatore, valore)). */
export type OperatoreFiltro =
  | 'eq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'like'
  | 'ilike'
  | 'in'
  | 'cs'
  | 'ov'
  | 'is'
  | 'not.is';

export type Operazione =
  | { tipo: 'filtro'; colonna: string; operatore: OperatoreFiltro; valore: string }
  | { tipo: 'or'; espressione: string }
  | { tipo: 'ordina'; colonna: string; crescente: boolean }
  | { tipo: 'limite'; n: number };

export interface RighePerSelect {
  articolo: RigaArticolo;
  interpello: RigaInterpello;
  selezione: RigaSelezione;
  bando: RigaBando;
  'bando-con-regione': RigaBando;
  categorie: RigaCategoria;
  secondarie: RigaSecondaria;
  profili: RigaProfilo;
}

export interface PianoQuery<S extends NomeSelect = NomeSelect> {
  db: Db;
  tabella: Tabella;
  select: S;
  operazioni: readonly Operazione[];
}

/**
 * Accesso ai dati iniettato: l'unica implementazione reale e' fonte-supabase.ts,
 * i test usano una fonte finta che registra i piani ricevuti. Errori del DB ->
 * ErroreDati (errori.ts), mai righe vuote al posto di un guasto.
 */
export interface FonteDati {
  leggi<S extends NomeSelect>(piano: PianoQuery<S>, segnale: AbortSignal): Promise<RighePerSelect[S][]>;
}
