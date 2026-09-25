import {
  supabaseBandi, loadCatalogo, lookupNome, todayRomeISO, BANDO_SELECT_LIST,
  BANDI_STATI_ESTESI, FONTE_BANDI, type Bando, type CatalogoRow,
} from '../supabase-bandi';
import { corpus, type Corpus, type VoceFaccetta } from '../corpus';
import { condizioneStatoBando, statiRichiesti } from '../bandi/filtro-stato';
import { orIlike, sanitizzaRicerca } from './postgrest';
import type { DefLista, Valori } from './parametri';
import { PAGINE_FILTRO, dimensione as trovaDimensione } from '../../config/pagine-filtro';
import { applicaEtichetta } from '../pagine-filtro';
import { GIORNI_IN_SCADENZA } from '../bandi/aspetto';
import { aggiungiGiorni, costruisciOpzioni, GRUPPI_FILTRO, idsDiValore, type ConteggiStato, type GruppoFiltro, type RigaCatalogo } from '../bandi/elenco';
import { ordinamentoDa, pianoPagina } from '../bandi/ordinamento';

/**
 * Lettura dei bandi per la pagina elenco, le pagine filtro e il frammento.
 *
 * I filtri riproducono esattamente quelli che prima lo script inline mandava a
 * PostgREST dal browser: stessi operatori, stessa logica sullo stato. La differenza e'
 * che ora la query gira sul server, quindi il risultato e' nell'HTML e la chiave anon
 * non viene piu' serializzata nella pagina.
 */

const PER_PAGINA = PAGINE_FILTRO.find((c) => c.sezione === 'bandi')!.perPagina;

/** Le sei tendine a scelta multipla, con la loro tabella di giunzione o la FK. */
export const MULTISELECT = [
  { nome: 'regione', etichetta: 'Regione', giunzione: { tabella: 'bando_regioni', colonna: 'regione_id' } },
  { nome: 'settore', etichetta: 'Settore', giunzione: { tabella: 'bando_settori', colonna: 'settore_id' } },
  { nome: 'beneficiario', etichetta: 'Beneficiario', giunzione: { tabella: 'bando_beneficiari', colonna: 'beneficiario_id' } },
  { nome: 'ateco', etichetta: 'Codice ATECO', giunzione: { tabella: 'bando_codici_ateco', colonna: 'codice_ateco_id' } },
  { nome: 'programma', etichetta: 'Programma', fk: 'programma_id' },
  { nome: 'modalita', etichetta: 'Modalità', fk: 'modalita_erogazione_id' },
] as const;

export const DEF_BANDI: DefLista = {
  sezione: 'bandi',
  base: '/bandi',
  frammento: '/api/lista/bandi',
  perPagina: PER_PAGINA,
  parametri: [
    { nome: 'q' },
    { nome: 'regione', multiplo: true, dimensione: 'regione' },
    { nome: 'settore', multiplo: true, dimensione: 'settore' },
    { nome: 'beneficiario', multiplo: true },
    { nome: 'ateco', multiplo: true },
    { nome: 'programma', multiplo: true, dimensione: 'programma' },
    { nome: 'modalita', multiplo: true },
    { nome: 'tipologia', multiplo: true, dimensione: 'tipologia' },
    // Un valore solo: i segmenti della barra sono radio. `?stato=a&stato=b`
    // fa 301 sul primo (normalizzazioneRichiesta).
    { nome: 'stato' },
    { nome: 'imin' },
    { nome: 'imax' },
    { nome: 'scad_da' },
    { nome: 'scad_a' },
    // `si`: aperti che scadono fra oggi e oggi+15 (tessera e bottone «In scadenza»).
    { nome: 'in_scadenza' },
    // Presentazione: `importo` | `recenti` (assente = scadenza piu' vicina) e
    // `griglia` (assente = elenco). Contano come filtri attivi, quindi le loro
    // varianti restano noindex con canonical su se stesse.
    { nome: 'ordina' },
    { nome: 'vista' },
  ],
  parametroRicerca: 'q',
};

/** Id numerici dei valori; un valore puo' portarne piu' d'uno («9,12», gli alias). */
const soloInteri = (valori: string[] | undefined): number[] => (valori ?? []).flatMap(idsDiValore);

const soloData = (v: string | undefined): string | null => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null);

export interface PaginaBandi {
  righe: Bando[];
  totale: number;
  /** true se la lettura e' fallita: la lista e' vuota per un guasto, non per i filtri. */
  errore: boolean;
}

type Ordine = { colonna: string; ascendente: boolean; nulliPrima?: boolean };

export async function caricaBandi(valori: Valori, pagina: number): Promise<PaginaBandi> {
  const embeds: string[] = [];
  const condizioni: string[] = [];
  const oggi = todayRomeISO();

  const termine = sanitizzaRicerca(valori.q?.[0] ?? '');
  if (termine) condizioni.push(`or(${orIlike(['titolo', 'descrizione_breve', 'ente_erogatore'], termine)})`);

  // Relazioni molti-a-molti: PostgREST vuole l'embed !inner nella select e il filtro
  // sulla colonna puntata. Dentro and() darebbe un 400 PGRST100.
  const giunzioniAttive: Array<{ tabella: string; colonna: string; ids: number[] }> = [];
  for (const m of MULTISELECT) {
    const ids = soloInteri(valori[m.nome]);
    if (ids.length === 0) continue;
    if ('giunzione' in m && m.giunzione) {
      embeds.push(`${m.giunzione.tabella}!inner(${m.giunzione.colonna})`);
      giunzioniAttive.push({ ...m.giunzione, ids });
    } else if ('fk' in m && m.fk) {
      condizioni.push(`${m.fk}.in.(${ids.join(',')})`);
    }
  }

  const tipologie = soloInteri(valori.tipologia);
  if (tipologie.length) condizioni.push(`tipologia_bando_id.in.(${tipologie.join(',')})`);

  // Stato effettivo: la colonna stato_bando corretta dalla scadenza. La
  // condizione sta in `bandi/filtro-stato.ts`, dove e' testabile riga per riga:
  // qui era un intreccio di or/and che faceva finire fra i "chiusi" anche i
  // sospesi e i revocati con la scadenza passata.
  let stati = statiRichiesti(valori.stato, BANDI_STATI_ESTESI);
  if (valori.in_scadenza?.[0] === 'si') {
    // «In scadenza» vale solo per gli aperti: con un altro stato scelto
    // l'intersezione e' vuota, come nel design.
    if (stati.length > 0 && !stati.includes('aperto')) return { righe: [], totale: 0, errore: false };
    stati = ['aperto'];
    condizioni.push(`data_scadenza.gte.${oggi}`, `data_scadenza.lte.${aggiungiGiorni(oggi, GIORNI_IN_SCADENZA)}`);
  }
  condizioni.push(...condizioneStatoBando(stati, oggi, FONTE_BANDI.colonnaStato));

  const imin = soloInteri(valori.imin)[0];
  const imax = soloInteri(valori.imax)[0];
  if (imin != null) condizioni.push(`importo_totale_eur.gte.${imin}`);
  if (imax != null) condizioni.push(`importo_totale_eur.lte.${imax}`);
  const scadDa = soloData(valori.scad_da?.[0]);
  const scadA = soloData(valori.scad_a?.[0]);
  if (scadDa) condizioni.push(`data_scadenza.gte.${scadDa}`);
  if (scadA) condizioni.push(`data_scadenza.lte.${scadA}`);

  // Lo stato calcolato entra nella select solo se la fonte ce l'ha: la card lo
  // preferisce alla colonna, e chiederlo alla tabella darebbe 42703 su tutta la
  // lista.
  const colonne = FONTE_BANDI.colonnaStato === null
    ? BANDO_SELECT_LIST
    : `${BANDO_SELECT_LIST},${FONTE_BANDI.colonnaStato}`;
  const select = embeds.length ? `${colonne},${embeds.join(',')}` : colonne;

  /** Query sulla fonte con i filtri comuni piu' le condizioni del segmento. */
  const costruisci = (extra: string[], soloConteggio: boolean) => {
    // Tabella e predicato di pubblicazione da FONTE_BANDI (sulla tabella la RLS
    // li ripete gia', ma dalla vista il nome cambia e le operazioni spariscono).
    let query = supabaseBandi
      .from(FONTE_BANDI.tabella)
      .select(select, soloConteggio ? { count: 'exact', head: true } : { count: 'exact' });
    for (const [colonna, operatore, valore] of FONTE_BANDI.operazioni) {
      query = query.filter(colonna, operatore, valore);
    }
    for (const g of giunzioniAttive) {
      // .filter() e' l'unico metodo di supabase-js che non riscrive il nome puntato.
      query = query.filter(`${g.tabella}.${g.colonna}`, 'in', `(${g.ids.join(',')})`);
    }
    // or=(and(a,b,c)) equivale a a AND b AND c ed e' la forma usata prima dal client.
    const tutte = [...condizioni, ...extra];
    if (tutte.length) query = query.or(`and(${tutte.join(',')})`);
    return query;
  };

  const ordina = <Q extends { order: (c: string, o: { ascending: boolean; nullsFirst?: boolean }) => Q }>(query: Q, ordini: Ordine[]): Q =>
    ordini.reduce((q, o) => q.order(o.colonna, { ascending: o.ascendente, nullsFirst: o.nulliPrima ?? false }), query);

  // «Scadenza piu' vicina» (il predefinito) si legge in tre segmenti: scadenze
  // da oggi in avanti, bandi senza scadenza, bandi scaduti. Un ordine su una
  // colonna sola metterebbe in cima i bandi chiusi da anni. Ogni segmento
  // ha il tiebreak su `id`: data_pubblicazione e' NULL sul 92% dei bandi e
  // molte scadenze coincidono.
  const segmenti: Array<{ extra: string[]; ordini: Ordine[] }> = (() => {
    switch (ordinamentoDa(valori.ordina?.[0])) {
      case 'importo':
        return [{ extra: [], ordini: [{ colonna: 'importo_totale_eur', ascendente: false }, { colonna: 'id', ascendente: false }] }];
      case 'recenti':
        return [{ extra: [], ordini: [{ colonna: 'data_pubblicazione', ascendente: false }, { colonna: 'id', ascendente: false }] }];
      default:
        return [
          { extra: [`data_scadenza.gte.${oggi}`], ordini: [{ colonna: 'data_scadenza', ascendente: true }, { colonna: 'id', ascendente: true }] },
          { extra: ['data_scadenza.is.null'], ordini: [{ colonna: 'id', ascendente: false }] },
          { extra: [`data_scadenza.lt.${oggi}`], ordini: [{ colonna: 'data_scadenza', ascendente: false }, { colonna: 'id', ascendente: false }] },
        ];
    }
  })();

  const da = (pagina - 1) * PER_PAGINA;
  const a = da + PER_PAGINA - 1;

  try {
    let grezze: Array<Record<string, unknown>> = [];
    let totale = 0;

    if (segmenti.length === 1) {
      const { data, count, error } = await ordina(costruisci(segmenti[0].extra, false), segmenti[0].ordini).range(da, a);
      if (error) {
        // PGRST103: pagina oltre l'ultima. Non e' un guasto: la pagina rispondera' 404.
        if ((error as { code?: string }).code === 'PGRST103') return { righe: [], totale: 0, errore: false };
        throw error;
      }
      grezze = (data ?? []) as unknown as Array<Record<string, unknown>>;
      totale = count ?? 0;
    } else {
      const conteggi = await Promise.all(segmenti.map((s) => costruisci(s.extra, true)));
      for (const c of conteggi) if (c.error) throw c.error;
      const dimensioni = conteggi.map((c) => c.count ?? 0);
      totale = dimensioni.reduce((x, y) => x + y, 0);
      const tratti = pianoPagina(da, a, dimensioni);
      const blocchi = await Promise.all(tratti.map((t) =>
        ordina(costruisci(segmenti[t.segmento].extra, false), segmenti[t.segmento].ordini).range(t.da, t.a)));
      for (const b of blocchi) {
        if (b.error) throw b.error;
        grezze.push(...((b.data ?? []) as unknown as Array<Record<string, unknown>>));
      }
    }

    const catalogo = await loadCatalogo();
    const righe = grezze.map((b) => ({
      ...b,
      tipologia: lookupNome(catalogo.tipologie, b.tipologia_bando_id as number | null),
      programma: lookupNome(catalogo.programmi, b.programma_id as number | null),
      modalita_erogazione: lookupNome(catalogo.modalita, b.modalita_erogazione_id as number | null),
    })) as unknown as Bando[];

    return { righe, totale, errore: false };
  } catch (e) {
    console.error('[lista bandi]', e);
    return { righe: [], totale: 0, errore: true };
  }
}

/**
 * I sette gruppi del pannello filtri, con i conteggi del corpus.
 *
 * Per regione, settore, programma e tipologia le righe di catalogo che il
 * corpus fa confluire nella stessa voce (gli alias, es. le due righe di FSE+)
 * diventano un'opzione sola; le altre hanno il conteggio per id. Le opzioni a
 * zero si nascondono, tranne quelle scelte. Senza corpus le opzioni restano,
 * senza numeri.
 */
export async function gruppiFiltroBandi(valori: Valori, c: Corpus | null): Promise<GruppoFiltro[]> {
  const cat = await loadCatalogo();
  const righe = (r: CatalogoRow[]): RigaCatalogo[] => r.map((x) => ({ id: x.id, etichetta: x.nome }));
  const catalogoPerGruppo: Record<string, RigaCatalogo[]> = {
    regione: righe(cat.regioni),
    tipologia: righe(cat.tipologie),
    beneficiario: righe(cat.beneficiari),
    settore: righe(cat.settori),
    programma: righe(cat.programmi),
    modalita: righe(cat.modalita),
    ateco: cat.codici_ateco.map((a) => ({ id: a.id, etichetta: `${a.codice}${a.descrizione ? ` — ${a.descrizione}` : ''}` })),
  };

  const vociDi = (chiave: string): VoceFaccetta[] | null => {
    const mappa = c?.faccette[chiave];
    const dim = trovaDimensione('bandi', chiave);
    if (!mappa || !dim) return null;
    return [...mappa.values()].map((v) => applicaEtichetta(v, dim));
  };

  return GRUPPI_FILTRO.map((g) => ({
    chiave: g.chiave,
    etichetta: g.etichetta,
    opzioni: costruisciOpzioni(
      catalogoPerGruppo[g.chiave] ?? [],
      vociDi(g.chiave),
      c?.bandi?.perId[g.chiave] ?? null,
      valori[g.chiave] ?? [],
    ),
  }));
}

/**
 * Numeri delle tessere dell'hero e dei segmenti di stato: dell'intera sezione,
 * oppure di una voce (pagina filtro). Vengono dal corpus (TTL 15 minuti).
 */
export function conteggiStatoBandi(c: Corpus | null, voce?: VoceFaccetta): ConteggiStato {
  const perStato = voce ? voce.perStato : c?.bandi?.perStato;
  return {
    tutti: voce ? voce.totale : (c?.totale ?? 0),
    aperti: perStato?.['aperto'] ?? 0,
    inApertura: perStato?.['in apertura prossimamente'] ?? 0,
    chiusi: perStato?.['chiuso'] ?? 0,
    inScadenza: (voce ? voce.inScadenza : c?.bandi?.inScadenza) ?? 0,
  };
}

/** Corpus dei bandi, oppure null se non si riesce a costruirlo (la lista resta in piedi). */
export async function corpusBandi(): Promise<Corpus | null> {
  try {
    return await corpus('bandi');
  } catch {
    return null;
  }
}

/**
 * Se e' attiva una sola dimensione promuovibile con una sola opzione, restituisce
 * lo slug della pagina statica equivalente. I valori dei filtri bandi sono id di
 * catalogo (piu' d'uno per gli alias, «9,12»), non nomi: la traduzione id -> slug
 * passa dalle faccette del corpus.
 */
export async function dimensioneUnicaBandi(valori: Valori, pagina: number): Promise<{ dimensione: string; slug: string } | null> {
  if (pagina !== 1) return null;
  const attivi = DEF_BANDI.parametri.filter((p) => (valori[p.nome]?.length ?? 0) > 0);
  if (attivi.length !== 1) return null;
  const p = attivi[0];
  if (!p.dimensione) return null;
  const scelte = valori[p.nome];
  if (scelte.length !== 1) return null;
  const ids = idsDiValore(scelte[0]);
  if (ids.length === 0) return null;

  const c = await corpus('bandi');
  for (const voce of c.faccette[p.dimensione]?.values() ?? []) {
    if (ids.every((id) => voce.idsDb.includes(id))) return { dimensione: p.dimensione, slug: voce.slug };
  }
  return null;
}
