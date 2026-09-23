import { createClient } from '@supabase/supabase-js';
import { fonteBandiDa } from './bandi/pubblicazione';
import type { StatoBando } from './stato-bando';
import type { FonteBandi } from './bandi/pubblicazione';
import type { Allegato, ContenutoBando } from './bandi/tipi';

const url = import.meta.env.PUBLIC_SUPABASE_BANDI_URL;
const key = import.meta.env.PUBLIC_SUPABASE_BANDI_ANON_KEY;

export const supabaseBandi = createClient(url, key);

/**
 * Da dove si leggono i bandi: la tabella `bando` (default) o la vista
 * `bando_pubblico`, che esiste solo dopo la migrazione 05.
 *
 * Questo e' uno dei due moduli impuri autorizzati a leggere il flag (l'altro e'
 * `api-v1/rotta.ts`): i moduli di `src/lib/bandi/` sono puri e `PUBLIC_*` viene
 * compilata al build, non e' una variabile a runtime. `BANDI_FONTE_LETTURA`
 * vale invece a runtime ed e' quella da usare per tornare indietro senza
 * ricostruire. Nessun ripiego automatico "se la vista manca": il ripiego e'
 * rimettere il flag a `bando`.
 */
export const FONTE_BANDI: FonteBandi = fonteBandiDa(
  process.env.BANDI_FONTE_LETTURA ?? import.meta.env.PUBLIC_BANDI_FONTE_LETTURA,
);

/**
 * `sospeso` e `revocato` sono valori legittimi del vocabolario ma il CHECK
 * della colonna ne ammette tre finche' la migrazione 06 non e' applicata:
 * offrirli nel filtro prima di allora significa offrire due chip che
 * restituiscono sempre zero risultati.
 */
export const BANDI_STATI_ESTESI: boolean =
  (process.env.BANDI_STATI_ESTESI ?? import.meta.env.PUBLIC_BANDI_STATI_ESTESI) === 'true';

// =========================================================================
// Costanti di dominio (schema v9 — vedi backend/sql/bando_alter_v9_*.sql)
// =========================================================================

// Vocabolari delle colonne di `bando`. Non sono esportati: nessuno fuori da
// questo file li cercava piu' (chi ha bisogno degli stati editoriali usa
// `STATI_BANDO` di `stato-bando.ts`, chi ha bisogno dei tipi degli allegati usa
// `bandi/tipi.ts`, entrambi puri e caricabili sotto `node --test`, cosa che
// questo file non e' perche' crea il client Supabase a livello di modulo).
// Restano qui perche' danno il tipo alle colonne dell'interfaccia `Bando`, e
// perche' scrivono nero su bianco che cosa ammette il CHECK a DB.

// Stato pipeline interno (vedi CHECK bando_stato_processing_check).
// Frontend pubblico vede SOLO stato_processing='completed' (RLS v9).
const STATI_PROCESSING = [
  'scraped', 'processed', 'rejected', 'enriched', 'completed',
] as const;
type StatoProcessing = typeof STATI_PROCESSING[number];

// Livello editoriale emesso dalla skill SEO v8.
const LIVELLI_BANDO = ['flash_bando', 'guida_bando'] as const;
type LivelloBando = typeof LIVELLI_BANDO[number];

// Provenienza del link candidatura.
const LINK_CANDIDATURA_SOURCES = ['extracted', 'fallback_source', 'missing'] as const;
type LinkCandidaturaSource = typeof LINK_CANDIDATURA_SOURCES[number];

// Tipo link fonte (scraper).
const TIPI_LINK = ['Opportunità', 'Preavviso'] as const;
type TipoLink = typeof TIPI_LINK[number];

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
  contenuto: ContenutoBando | string | null;
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

export interface CatalogoRow { id: number; nome: string; slug?: string | null }
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
      // La colonna slug e' popolata solo su `regioni` (20/20) ed e' gia' nella forma
      // pulita: e' il primo criterio di match con il registro src/lib/regioni.ts.
      supabaseBandi.from('regioni').select('id, nome, slug').order('nome'),
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

// todayRomeISO vive in stato-bando.ts (logica pura, testabile sotto node senza
// il client Supabase creato qui sopra) ed e' l'unico helper ancora ri-esportato
// da qui: `effectiveStatoBando` e `statoEffettivo` si importano da stato-bando.
export { todayRomeISO } from './stato-bando';

/**
 * Colonne SELECT per la lista bandi (compatte, no contenuto).
 */
export const BANDO_SELECT_LIST = [
  'id', 'slug', 'titolo', 'titolo_breve', 'descrizione_breve',
  'ente_erogatore', 'area_geografica', 'tematica',
  'data_pubblicazione', 'data_apertura', 'data_scadenza',
  'importo_totale_eur', 'importo_max_per_progetto_eur',
  'stato_bando',
  'tipologia_bando_id', 'modalita_erogazione_id', 'programma_id',
].join(', ');

/**
 * Colonne SELECT per la scheda di dettaglio, riscritte da zero per il rilascio
 * F1. La `BANDO_SELECT_DETAIL` precedente e' stata rimossa: citava
 * `fonte_id, hash_bando, tipo_link, confidence_score, stato_processing,
 * titolo_raw, link_bando`, colonne che la pagina non rende e che sulla vista
 * `bando_pubblico` non esistono — una sola di loro fa rispondere PostgREST
 * 42703 e fallire l'intera richiesta, cioe' ogni scheda del sito.
 *
 * Nessuna colonna nuova: le migrazioni non sono applicate, e chiedere
 * `ultimo_controllo_at` o `fonte_ufficiale_url` oggi darebbe lo stesso 42703.
 */
export const BANDO_SELECT_DETTAGLIO = [
  'id', 'slug', 'titolo', 'titolo_breve', 'descrizione_breve', 'contenuto',
  'ente_erogatore', 'area_geografica', 'tematica',
  'data_pubblicazione', 'data_apertura', 'data_scadenza',
  'importo_totale_eur', 'importo_max_per_progetto_eur',
  'link_candidatura', 'link_candidatura_source', 'allegati', 'stato_bando',
  'tipologia_bando_id', 'modalita_erogazione_id', 'programma_id',
  'created_at', 'updated_at',
].join(', ');
