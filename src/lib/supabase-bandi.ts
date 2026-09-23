import { createClient } from '@supabase/supabase-js';
import { fonteBandiDa } from './bandi/pubblicazione';
import type { StatoBando } from './stato-bando';
import type { FonteBandi } from './bandi/pubblicazione';
import type { Allegato, ContenutoBando, EventoBando, LinkBando } from './bandi/tipi';

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
 * Colonne SELECT per la scheda di dettaglio.
 *
 * Riscritta da zero per F1: la `BANDO_SELECT_DETAIL` precedente citava
 * `fonte_id, hash_bando, tipo_link, confidence_score, stato_processing,
 * titolo_raw, link_bando`, colonne che la pagina non rende e che sulla vista
 * `bando_pubblico` non esistono — una sola di loro fa rispondere PostgREST
 * 42703 e fallire l'intera richiesta, cioe' ogni scheda del sito.
 *
 * Le colonne del lavoro v11 (fonte ufficiale, ore, flag di verifica, stato
 * effettivo, ultimo controllo) si chiedono **solo quando la fonte le ha**:
 * esistono sulla vista e sulla tabella dopo le migrazioni 01 e 03, ma la
 * tabella non ha `stato_effettivo` ne' `ultimo_controllo_at`, che la vista
 * calcola. Chiederle a `bando` darebbe 42703 su ogni scheda, quindi la lista
 * si compone dalla fonte e non e' una costante.
 */
const COLONNE_DETTAGLIO_COMUNI = [
  'id', 'slug', 'titolo', 'titolo_breve', 'descrizione_breve', 'contenuto',
  'ente_erogatore', 'area_geografica', 'tematica',
  'data_pubblicazione', 'data_apertura', 'data_scadenza',
  'importo_totale_eur', 'importo_max_per_progetto_eur',
  'link_candidatura', 'link_candidatura_source', 'allegati', 'stato_bando',
  'tipologia_bando_id', 'modalita_erogazione_id', 'programma_id',
  'created_at',
];

/**
 * Cio' che solo la vista sa dire: lo stato calcolato alla lettura, l'ora di
 * apertura e scadenza, se le date hanno una prova, la fonte ufficiale e quando
 * l'abbiamo controllata. Sono le colonne che rendono visibile tutto il lavoro
 * del resolver e del monitor: senza la vista la scheda resta quella di F1.
 */
const COLONNE_DETTAGLIO_VISTA = [
  'stato_effettivo', 'stato_bando_verificato',
  'ora_apertura', 'ora_scadenza',
  'data_apertura_verificata', 'data_scadenza_verificata',
  'fonte_ufficiale_url', 'fonte_ufficiale_host', 'fonte_ufficiale_tipo',
  'fonte_ufficiale_stato', 'fonte_ufficiale_e_atto', 'fonte_ufficiale_verificata_at',
  'ultimo_controllo_at',
];

export const BANDO_SELECT_DETTAGLIO = [
  ...COLONNE_DETTAGLIO_COMUNI,
  FONTE_BANDI.selectFreschezza,
  ...(FONTE_BANDI.tabella === 'bando_pubblico' ? COLONNE_DETTAGLIO_VISTA : []),
].join(', ');

// =========================================================================
// Letture di F2: i link, gli eventi e la mappa degli slug
// =========================================================================

/**
 * Se la fonte corrente ha le tabelle di F2. Le tre letture qui sotto esistono
 * solo dopo le migrazioni 02 e 03, e chiamarle prima costerebbe tre richieste
 * per scheda che tornano tutte errore. La scheda le salta e resta quella di F1.
 */
export const F2_DISPONIBILE: boolean = FONTE_BANDI.tabella === 'bando_pubblico';

/**
 * I link pubblicabili e gli eventi visibili di un bando: due letture, non un
 * embed.
 *
 * L'embed non si puo' usare per due ragioni indipendenti: `bando_link` e
 * `bando_evento` concedono ad anon **colonne** e non la tabella, quindi un
 * `select=*` dentro un embed risponde 42501; e la vista non ha una relazione
 * dichiarata verso quelle tabelle, perche' le chiavi esterne stanno su `bando`.
 *
 * Non solleva mai: una scheda deve rendersi anche se queste due letture
 * fallissero. Il prezzo di un guasto e' una scheda senza il box degli
 * aggiornamenti, non una scheda che non c'e'.
 */
export async function caricaLinkEEventi(bandoId: number | string): Promise<{
  link: LinkBando[];
  eventi: EventoBando[];
}> {
  if (!F2_DISPONIBILE) return { link: [], eventi: [] };
  const [risposteLink, risposteEventi] = await Promise.all([
    supabaseBandi
      .from('bando_link')
      // Le colonne del contratto (§13.4), una per una: `*` risponde 42501.
      .select('id, bando_id, url, dominio, tipo, etichetta, content_type, ultimo_visto_at')
      .eq('bando_id', bandoId),
    supabaseBandi
      .from('bando_evento')
      // Come sopra (§13.5). `cursore` non serve al render ma e' il gate della
      // RLS: chiederlo rende esplicito che si leggono solo gli eventi visibili.
      .select('id, tipo, campo, valore_dopo, data_evento, rilevato_at, verificato, '
        + 'url_prova, in_aggiornamenti, applicato, cursore')
      .eq('bando_id', bandoId)
      .eq('in_aggiornamenti', true)
      .order('data_evento', { ascending: false, nullsFirst: false })
      .order('id', { ascending: false })
      .limit(20),
  ]);

  if (risposteLink.error) {
    console.warn('[bandi] link del bando non letti:', risposteLink.error.message);
  }
  if (risposteEventi.error) {
    console.warn('[bandi] eventi del bando non letti:', risposteEventi.error.message);
  }
  return {
    // Solo le righe pubblicabili escono ad anon per effetto della RLS: qui non
    // si filtra di nuovo, ma i moduli puri a valle ricontrollano il dominio.
    link: (risposteLink.data ?? []) as unknown as LinkBando[],
    eventi: (risposteEventi.data ?? []) as unknown as EventoBando[],
  };
}

/**
 * Lo slug richiesto e' uno slug storico o il doppione di una fusione?
 *
 * Due tabelle e una sola risposta, nella forma che `esitoSlug` aspetta.
 * `bando_slug_storico` porta l'esito dichiarato (301, 410, annullato);
 * `bando_fusione` porta lo slug del master. Si guarda prima lo storico, perche'
 * un ritiro (410) deve vincere su una fusione.
 *
 * Lo slug di destinazione si verifica **sulla fonte corrente**: un master non
 * piu' pubblicato non e' una destinazione valida, e un 301 verso una pagina
 * che risponde 404 e' peggio di un 404 diretto.
 */
export async function risolviSlugStorico(
  slug: string,
): Promise<{ stato: 'ok'; riga: { esito: string | null; slugMaster: string | null } | null }
  | { stato: 'errore' }
  | { stato: 'non_eseguita' }> {
  if (!F2_DISPONIBILE) return { stato: 'non_eseguita' };
  const [storico, fusione] = await Promise.all([
    supabaseBandi.from('bando_slug_storico')
      .select('slug, bando_id, esito, motivo, created_at')
      .eq('slug', slug).limit(1),
    supabaseBandi.from('bando_fusione')
      .select('bando_id, slug_originale, master_id, master_slug, motivo, fuso_at')
      .eq('slug_originale', slug).limit(1),
  ]);
  if (storico.error || fusione.error) {
    console.warn('[bandi] mappa degli slug non letta:',
      storico.error?.message ?? fusione.error?.message);
    return { stato: 'errore' };
  }

  const rigaStorico = (storico.data ?? [])[0] as { esito?: string | null; bando_id?: number } | undefined;
  const rigaFusione = (fusione.data ?? [])[0] as { master_slug?: string | null } | undefined;
  if (!rigaStorico && !rigaFusione) return { stato: 'ok', riga: null };

  const esito = rigaStorico?.esito ?? '301';
  // Un 410 e' un ritiro: non ha ne' bisogno ne' diritto di una destinazione.
  if (esito === '410') return { stato: 'ok', riga: { esito, slugMaster: null } };

  const slugCandidato = rigaFusione?.master_slug ?? null;
  const master = await slugVisibile(slugCandidato, rigaStorico?.bando_id ?? null);
  if (master === 'errore') return { stato: 'errore' };
  return { stato: 'ok', riga: { esito, slugMaster: master } };
}

/** Lo slug del master, ma solo se quel bando e' ancora visibile sulla fonte. */
async function slugVisibile(
  slugCandidato: string | null,
  bandoId: number | null,
): Promise<string | null | 'errore'> {
  if (slugCandidato === null && bandoId === null) return null;
  let query = supabaseBandi.from(FONTE_BANDI.tabella).select('slug').limit(1);
  for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
    query = query.filter(colonna, operatore, valore);
  }
  const { data, error } = slugCandidato !== null
    ? await query.eq('slug', slugCandidato)
    : await query.eq('id', bandoId as number);
  if (error) {
    console.warn('[bandi] verifica del master non riuscita:', error.message);
    return 'errore';
  }
  const riga = (data ?? [])[0] as { slug?: string | null } | undefined;
  return riga?.slug ?? null;
}
