import { supabase } from './supabase';
import { supabaseBandi, loadCatalogo, effectiveStatoBando, todayRomeISO, type CatalogoRow } from './supabase-bandi';
import { regionePerValore, regionePerSlug } from './regioni';
import { slugifica } from './slug';
import { TTL_CORPUS_MS, configSezione, type Sezione } from '../config/pagine-filtro';

/**
 * Aggregazione delle faccette delle tre sezioni: quali valori esistono, quanti
 * annunci hanno, quanti sono ancora aperti, qual e' il piu' recente, e gli incroci
 * fra dimensioni (le province di una regione, i settori di una regione...).
 *
 * Perche' in memoria e non a query: PostgREST con la chiave anon non fa GROUP BY, e
 * il backend e' fuori dal perimetro. Prima di questo modulo le faccette venivano
 * ricalcolate a OGNI pageview con una select senza .range(), che PostgREST tronca a
 * 1000 righe: su /selezione-personale significava aggregare l'8% del corpus e
 * scaricare ~150 KB inutili per ogni visita.
 *
 * La cache e' per processo, con TTL e stale-while-revalidate: solo la primissima
 * richiesta dopo l'avvio attende, poi si serve sempre il dato in memoria mentre
 * l'aggiornamento gira dietro le quinte.
 */

export interface VoceFaccetta {
  /** Segmento URL. */
  slug: string;
  /** Testo da mostrare. */
  etichetta: string;
  /** Valori DB esatti che confluiscono in questo slug (filtri testuali e array). */
  valoriDb: string[];
  /** Id di catalogo che confluiscono in questo slug (FK e junction dei bandi). */
  idsDb: number[];
  totale: number;
  /** Annunci non scaduti. Per gli interpelli non esiste una scadenza: vale totale. */
  aperti: number;
  ultimaData: string | null;
}

export interface Corpus {
  sezione: Sezione;
  totale: number;
  aperti: number;
  /** dimensione -> slug del valore -> voce. */
  faccette: Record<string, Map<string, VoceFaccetta>>;
  /** "dimA|dimB" -> slugA -> slugB -> conteggio. */
  incroci: Map<string, Map<string, Map<string, number>>>;
  generatoIl: number;
}

// ---------------------------------------------------------------------------
// Accumulatore
// ---------------------------------------------------------------------------

class Accumulatore {
  faccette: Record<string, Map<string, VoceFaccetta>> = {};
  incroci: Map<string, Map<string, Map<string, number>>> = new Map();

  /** dimensione -> valore DB escluso. */
  private esclusi: Record<string, Set<string>> = {};
  /** dimensione -> valore DB -> slug canonico in cui deve confluire. */
  private aliasValore: Record<string, Map<string, string>> = {};

  constructor(sezione: Sezione) {
    // Esclusioni e alias vengono applicati QUI e non a valle, cosi' i conteggi sono
    // gli stessi ovunque: pagina filtro, elenco degli hub, sitemap e testi generati.
    for (const dim of configSezione(sezione).dimensioni) {
      this.esclusi[dim.slug] = new Set(dim.esclusi ?? []);
      const mappa = new Map<string, string>();
      for (const [slugCanonico, valori] of Object.entries(dim.alias ?? {})) {
        for (const v of valori) mappa.set(v, slugCanonico);
      }
      this.aliasValore[dim.slug] = mappa;
    }
  }

  /** true se il valore DB non deve generare ne' conteggi ne' URL. */
  escluso(dimensione: string, valoreDb: string | null | undefined): boolean {
    return !!valoreDb && (this.esclusi[dimensione]?.has(valoreDb) ?? false);
  }

  /** Slug definitivo del valore, tenendo conto degli alias di configurazione. */
  slugDi(dimensione: string, valoreDb: string, slugCalcolato: string): string {
    return this.aliasValore[dimensione]?.get(valoreDb) ?? slugCalcolato;
  }

  aggiungi(
    dimensione: string,
    slug: string,
    etichetta: string,
    opzioni: { valoreDb?: string; idDb?: number; aperto: boolean; data: string | null },
  ): void {
    if (this.escluso(dimensione, opzioni.valoreDb)) return;
    const mappa = (this.faccette[dimensione] ??= new Map());
    let voce = mappa.get(slug);
    if (!voce) {
      // L'etichetta si ripulisce agli estremi ("Avviso OIV " -> "Avviso OIV"): e' solo
      // testo da mostrare. I valori in valoriDb restano invece ESATTI, spazio finale
      // compreso, perche' senza di quello la query non trova nulla.
      voce = { slug, etichetta: etichetta.trim(), valoriDb: [], idsDb: [], totale: 0, aperti: 0, ultimaData: null };
      mappa.set(slug, voce);
    }
    if (opzioni.valoreDb && !voce.valoriDb.includes(opzioni.valoreDb)) voce.valoriDb.push(opzioni.valoreDb);
    if (opzioni.idDb != null && !voce.idsDb.includes(opzioni.idDb)) voce.idsDb.push(opzioni.idDb);
    voce.totale++;
    if (opzioni.aperto) voce.aperti++;
    if (opzioni.data && (!voce.ultimaData || opzioni.data > voce.ultimaData)) voce.ultimaData = opzioni.data;
  }

  incrocia(dimA: string, slugA: string, dimB: string, slugB: string): void {
    const chiave = `${dimA}|${dimB}`;
    const perA = this.incroci.get(chiave) ?? new Map<string, Map<string, number>>();
    this.incroci.set(chiave, perA);
    const perB = perA.get(slugA) ?? new Map<string, number>();
    perA.set(slugA, perB);
    perB.set(slugB, (perB.get(slugB) ?? 0) + 1);
  }
}

/** Legge una tabella a blocchi da 1000 righe: PostgREST tronca li' di default. */
async function leggiTutto<T>(
  costruisci: (da: number, a: number) => PromiseLike<{ data: unknown; error: unknown }>,
): Promise<T[]> {
  const righe: T[] = [];
  const blocco = 1000;
  for (let pagina = 0; pagina < 200; pagina++) {
    const { data, error } = await costruisci(pagina * blocco, (pagina + 1) * blocco - 1);
    if (error) throw error;
    const lotto = (data ?? []) as T[];
    righe.push(...lotto);
    if (lotto.length < blocco) break;
  }
  return righe;
}

// ---------------------------------------------------------------------------
// Costruzione per sezione
// ---------------------------------------------------------------------------

interface RigaInterpello {
  id: number;
  interpello_regione: string | null;
  interpello_provincia: string | null;
  classe_concorso: string | null;
  interpello_date: string | null;
}

async function costruisciInterpelli(): Promise<Corpus> {
  const righe = await leggiTutto<RigaInterpello>((da, a) =>
    supabase
      .from('interpelli')
      .select('id, interpello_regione, interpello_provincia, classe_concorso, interpello_date')
      .eq('link_type', 'single')
      .eq('status', 'completed')
      .order('interpello_date', { ascending: false })
      .order('id', { ascending: false })
      .range(da, a),
  );

  const acc = new Accumulatore('interpelli');
  for (const r of righe) {
    const data = r.interpello_date;
    const regione = regionePerValore(r.interpello_regione);
    const slugRegione = regione?.slug ?? null;
    const slugProvincia = r.interpello_provincia ? slugifica(r.interpello_provincia) : null;
    const slugClasse = r.classe_concorso ? slugifica(r.classe_concorso) : null;

    if (regione) {
      acc.aggiungi('regione', regione.slug, regione.nome, { valoreDb: r.interpello_regione!, aperto: true, data });
    }
    if (slugProvincia) {
      acc.aggiungi('provincia', slugProvincia, r.interpello_provincia!, { valoreDb: r.interpello_provincia!, aperto: true, data });
    }
    if (slugClasse) {
      acc.aggiungi('classe', slugClasse, r.classe_concorso!, { valoreDb: r.classe_concorso!, aperto: true, data });
    }

    if (slugRegione && slugProvincia) acc.incrocia('regione', slugRegione, 'provincia', slugProvincia);
    if (slugRegione && slugClasse) acc.incrocia('regione', slugRegione, 'classe', slugClasse);
    if (slugClasse && slugRegione) acc.incrocia('classe', slugClasse, 'regione', slugRegione);
    if (slugProvincia && slugClasse) acc.incrocia('provincia', slugProvincia, 'classe', slugClasse);
  }

  return {
    sezione: 'interpelli',
    totale: righe.length,
    aperti: righe.length,
    faccette: acc.faccette,
    incroci: acc.incroci,
    generatoIl: Date.now(),
  };
}

interface RigaSelezione {
  id: number;
  sedi: string[] | null;
  categorie: string[] | null;
  settori: string[] | null;
  data_scadenza: string | null;
  data_pubblicazione: string | null;
}

async function costruisciSelezione(): Promise<Corpus> {
  const righe = await leggiTutto<RigaSelezione>((da, a) =>
    supabase
      .from('selezione_personale')
      .select('id, sedi, categorie, settori, data_scadenza, data_pubblicazione')
      .eq('status', 'completed')
      .order('data_pubblicazione', { ascending: false })
      .order('id', { ascending: false })
      .range(da, a),
  );

  const oggi = todayRomeISO();
  const acc = new Accumulatore('selezione-personale');
  let aperti = 0;

  for (const r of righe) {
    // calculated_status vale 'OPEN' su TUTTE le righe, anche su quelle scadute da
    // mesi: lo stato reale si ricava solo da data_scadenza.
    const aperto = !r.data_scadenza || r.data_scadenza.slice(0, 10) >= oggi;
    if (aperto) aperti++;
    const data = r.data_pubblicazione;

    // sedi[] contiene tipicamente [Regione, Provincia]: si contano solo le regioni
    // riconosciute, una volta sola per annuncio anche se compaiono piu' volte.
    const regioniRiga = new Map<string, { slug: string; nome: string; valoreDb: string }>();
    for (const sede of r.sedi ?? []) {
      const reg = regionePerValore(sede);
      if (reg && !regioniRiga.has(reg.slug)) regioniRiga.set(reg.slug, { slug: reg.slug, nome: reg.nome, valoreDb: sede });
    }
    for (const reg of regioniRiga.values()) {
      acc.aggiungi('regione', reg.slug, reg.nome, { valoreDb: reg.valoreDb, aperto, data });
    }

    // Faccetta 'sede': TUTTI i valori di sedi[], regioni e province insieme, come li
    // scrive INPA. Non e' una dimensione pubblicabile (non genera URL), serve solo a
    // popolare il select e a tradurre slug <-> valore DB nella query.
    for (const sede of new Set(r.sedi ?? [])) {
      if (!sede) continue;
      acc.aggiungi('sede', slugifica(sede), sede, { valoreDb: sede, aperto, data });
    }

    const categorieRiga = new Set(r.categorie ?? []);
    for (const cat of categorieRiga) {
      acc.aggiungi('categoria', slugifica(cat), cat, { valoreDb: cat, aperto, data });
    }
    const settoriRiga = new Set((r.settori ?? []).filter(Boolean));
    for (const set of settoriRiga) {
      acc.aggiungi('settore', slugifica(set), set, { valoreDb: set, aperto, data });
    }

    for (const reg of regioniRiga.values()) {
      for (const cat of categorieRiga) acc.incrocia('regione', reg.slug, 'categoria', slugifica(cat));
      for (const set of settoriRiga) acc.incrocia('regione', reg.slug, 'settore', slugifica(set));
    }
    for (const cat of categorieRiga) {
      for (const reg of regioniRiga.values()) acc.incrocia('categoria', slugifica(cat), 'regione', reg.slug);
    }
  }

  return {
    sezione: 'selezione-personale',
    totale: righe.length,
    aperti,
    faccette: acc.faccette,
    incroci: acc.incroci,
    generatoIl: Date.now(),
  };
}

interface RigaBando {
  id: number;
  programma_id: number | null;
  tipologia_bando_id: number | null;
  stato_bando: string | null;
  data_scadenza: string | null;
  data_pubblicazione: string | null;
}

/** Slug di una voce di catalogo: per le regioni vince il registro statico. */
function slugCatalogo(riga: CatalogoRow, dimensione: string): { slug: string; etichetta: string } | null {
  if (dimensione === 'regione') {
    const reg = regionePerValore(riga.slug ?? riga.nome) ?? regionePerValore(riga.nome);
    return reg ? { slug: reg.slug, etichetta: reg.nome } : null;
  }
  const slug = slugifica(riga.nome);
  return slug ? { slug, etichetta: riga.nome } : null;
}

async function costruisciBandi(): Promise<Corpus> {
  const [righe, catalogo] = await Promise.all([
    leggiTutto<RigaBando>((da, a) =>
      supabaseBandi
        .from('bando')
        .select('id, programma_id, tipologia_bando_id, stato_bando, data_scadenza, data_pubblicazione')
        .eq('stato_processing', 'completed')
        .not('slug', 'is', null)
        .order('data_pubblicazione', { ascending: false, nullsFirst: false })
        .order('id', { ascending: false })
        .range(da, a),
    ),
    loadCatalogo(),
  ]);

  const visibili = new Map(righe.map((r) => [r.id, r]));

  // Le junction non sono soggette alla RLS di `bando`: si filtrano sui bandi visibili.
  const [legamiRegioni, legamiSettori] = await Promise.all([
    leggiTutto<{ bando_id: number; regione_id: number }>((da, a) =>
      supabaseBandi.from('bando_regioni').select('bando_id, regione_id').order('bando_id', { ascending: true }).range(da, a),
    ),
    leggiTutto<{ bando_id: number; settore_id: number }>((da, a) =>
      supabaseBandi.from('bando_settori').select('bando_id, settore_id').order('bando_id', { ascending: true }).range(da, a),
    ),
  ]);

  const regioniPerBando = new Map<number, Set<number>>();
  for (const l of legamiRegioni) {
    if (!visibili.has(l.bando_id)) continue;
    (regioniPerBando.get(l.bando_id) ?? regioniPerBando.set(l.bando_id, new Set()).get(l.bando_id)!).add(l.regione_id);
  }
  const settoriPerBando = new Map<number, Set<number>>();
  for (const l of legamiSettori) {
    if (!visibili.has(l.bando_id)) continue;
    (settoriPerBando.get(l.bando_id) ?? settoriPerBando.set(l.bando_id, new Set()).get(l.bando_id)!).add(l.settore_id);
  }

  const perId = (righeCatalogo: CatalogoRow[]) => new Map(righeCatalogo.map((r) => [r.id, r]));
  const catRegioni = perId(catalogo.regioni);
  const catSettori = perId(catalogo.settori);
  const catProgrammi = perId(catalogo.programmi);
  const catTipologie = perId(catalogo.tipologie);

  const acc = new Accumulatore('bandi');
  let aperti = 0;

  for (const b of righe) {
    const aperto = effectiveStatoBando(b.stato_bando, b.data_scadenza) === 'aperto';
    if (aperto) aperti++;
    const data = b.data_pubblicazione;

    const slugRegioni: string[] = [];
    for (const idRegione of regioniPerBando.get(b.id) ?? []) {
      const riga = catRegioni.get(idRegione);
      const v = riga ? slugCatalogo(riga, 'regione') : null;
      if (!v || !riga) continue;
      const slug = acc.slugDi('regione', riga.nome, v.slug);
      acc.aggiungi('regione', slug, v.etichetta, { valoreDb: riga.nome, idDb: idRegione, aperto, data });
      slugRegioni.push(v.slug);
    }

    const slugSettori: string[] = [];
    for (const idSettore of settoriPerBando.get(b.id) ?? []) {
      const riga = catSettori.get(idSettore);
      const v = riga ? slugCatalogo(riga, 'settore') : null;
      if (!v || !riga) continue;
      const slug = acc.slugDi('settore', riga.nome, v.slug);
      acc.aggiungi('settore', slug, v.etichetta, { valoreDb: riga.nome, idDb: idSettore, aperto, data });
      slugSettori.push(v.slug);
    }

    let slugProgramma: string | null = null;
    if (b.programma_id != null) {
      const riga = catProgrammi.get(b.programma_id);
      const v = riga ? slugCatalogo(riga, 'programma') : null;
      if (v && riga) {
        // Alias: "FSE+" e "FSE+ - Fondo Sociale Europeo +" sono due righe distinte del
        // catalogo per lo stesso programma e devono confluire in un URL solo.
        const slug = acc.slugDi('programma', riga.nome, v.slug);
        acc.aggiungi('programma', slug, v.etichetta, { valoreDb: riga.nome, idDb: b.programma_id, aperto, data });
        slugProgramma = slug;
      }
    }
    if (b.tipologia_bando_id != null) {
      const riga = catTipologie.get(b.tipologia_bando_id);
      const v = riga ? slugCatalogo(riga, 'tipologia') : null;
      if (v && riga) {
        acc.aggiungi('tipologia', acc.slugDi('tipologia', riga.nome, v.slug), v.etichetta,
          { valoreDb: riga.nome, idDb: b.tipologia_bando_id, aperto, data });
      }
    }

    for (const sr of slugRegioni) {
      for (const ss of slugSettori) acc.incrocia('regione', sr, 'settore', ss);
      if (slugProgramma) acc.incrocia('regione', sr, 'programma', slugProgramma);
    }
    for (const ss of slugSettori) {
      for (const sr of slugRegioni) acc.incrocia('settore', ss, 'regione', sr);
    }
  }

  return {
    sezione: 'bandi',
    totale: righe.length,
    aperti,
    faccette: acc.faccette,
    incroci: acc.incroci,
    generatoIl: Date.now(),
  };
}

const COSTRUTTORI: Record<Sezione, () => Promise<Corpus>> = {
  interpelli: costruisciInterpelli,
  'selezione-personale': costruisciSelezione,
  bandi: costruisciBandi,
};

// ---------------------------------------------------------------------------
// Cache: TTL + stale-while-revalidate + single flight
// ---------------------------------------------------------------------------

const cache = new Map<Sezione, Corpus>();
const inCorso = new Map<Sezione, Promise<Corpus>>();

function rinfresca(sezione: Sezione): Promise<Corpus> {
  const gia = inCorso.get(sezione);
  if (gia) return gia;
  const promessa = COSTRUTTORI[sezione]()
    .then((c) => {
      cache.set(sezione, c);
      return c;
    })
    .catch((e) => {
      console.error(`[corpus] costruzione fallita per ${sezione}:`, e);
      const vecchio = cache.get(sezione);
      if (vecchio) return vecchio; // meglio un dato stantio che un errore
      throw e;
    })
    .finally(() => {
      inCorso.delete(sezione);
    });
  inCorso.set(sezione, promessa);
  return promessa;
}

/**
 * Corpus della sezione. Attende solo alla primissima richiesta dopo l'avvio del
 * processo: dopo, se il dato e' scaduto lo si serve comunque e l'aggiornamento parte
 * in background. Non si restituisce mai un 404 per cache fredda, perche' sarebbe un
 * 404 su un URL valido e gia' indicizzato.
 */
export async function corpus(sezione: Sezione): Promise<Corpus> {
  const attuale = cache.get(sezione);
  if (!attuale) return rinfresca(sezione);
  if (Date.now() - attuale.generatoIl > TTL_CORPUS_MS) void rinfresca(sezione);
  return attuale;
}

/** Corpus solo se gia' in memoria. Non attende e non innesca letture. */
export function corpusSeCaldo(sezione: Sezione): Corpus | null {
  return cache.get(sezione) ?? null;
}

/** Riscalda le tre sezioni in background, senza far attendere nessuno. */
export function riscaldaCorpus(): void {
  for (const sezione of Object.keys(COSTRUTTORI) as Sezione[]) {
    if (!cache.get(sezione)) void rinfresca(sezione);
  }
}

/** Voci di una dimensione ordinate per numero di annunci. */
export function vociFaccetta(c: Corpus, dimensione: string): VoceFaccetta[] {
  return [...(c.faccette[dimensione]?.values() ?? [])].sort((a, b) => b.totale - a.totale || a.slug.localeCompare(b.slug));
}

/** Conteggi incrociati: da (dimA, slugA) verso dimB, ordinati per frequenza. */
export function incrocio(c: Corpus, dimA: string, slugA: string, dimB: string): Array<{ slug: string; totale: number }> {
  const perB = c.incroci.get(`${dimA}|${dimB}`)?.get(slugA);
  if (!perB) return [];
  return [...perB.entries()]
    .map(([slug, totale]) => ({ slug, totale }))
    .sort((a, b) => b.totale - a.totale || a.slug.localeCompare(b.slug));
}

// Riferimento usato dal registro regioni per validare gli slug del catalogo bandi.
export { regionePerSlug };
