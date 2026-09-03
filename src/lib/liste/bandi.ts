import {
  supabaseBandi, loadCatalogo, lookupNome, todayRomeISO, BANDO_SELECT_LIST,
  STATI_BANDO, type Bando, type CatalogoRow,
} from '../supabase-bandi';
import { corpus } from '../corpus';
import { orIlike, sanitizzaRicerca } from './postgrest';
import type { DefLista, Valori } from './parametri';
import { PAGINE_FILTRO } from '../../config/pagine-filtro';

/**
 * Lettura dei bandi per la pagina elenco.
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
    { nome: 'stato', multiplo: true },
    { nome: 'imin' },
    { nome: 'imax' },
    { nome: 'scad_da' },
    { nome: 'scad_a' },
  ],
  parametroRicerca: 'q',
};

const soloInteri = (valori: string[] | undefined): number[] =>
  (valori ?? []).filter((v) => /^\d+$/.test(v)).map(Number);

const soloData = (v: string | undefined): string | null => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null);

const quoteVal = (v: string) => (/[\s,()]/.test(v) ? `"${v.replace(/"/g, '')}"` : v);

export interface PaginaBandi {
  righe: Bando[];
  totale: number;
}

export async function caricaBandi(valori: Valori, pagina: number): Promise<PaginaBandi> {
  const embeds: string[] = [];
  const condizioni: string[] = [];

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

  // Stato effettivo: la colonna stato_bando corretta dalla scadenza. Copia della
  // logica che il client applicava a bandi.astro prima di questo intervento.
  const stati = (valori.stato ?? []).filter((s) => (STATI_BANDO as readonly string[]).includes(s));
  if (stati.length) {
    const oggi = todayRomeISO();
    const nonScaduto = `or(data_scadenza.gte.${oggi},data_scadenza.is.null)`;
    const altri = stati.filter((s) => s !== 'chiuso');
    if (stati.includes('chiuso')) {
      const rami = ['stato_bando.eq.chiuso', `data_scadenza.lt.${oggi}`];
      if (altri.length) rami.push(`and(stato_bando.in.(${altri.map(quoteVal).join(',')}),${nonScaduto})`);
      condizioni.push(`or(${rami.join(',')})`);
    } else {
      condizioni.push(`stato_bando.in.(${stati.map(quoteVal).join(',')})`);
      condizioni.push(nonScaduto);
    }
  }

  const imin = soloInteri(valori.imin)[0];
  const imax = soloInteri(valori.imax)[0];
  if (imin != null) condizioni.push(`importo_totale_eur.gte.${imin}`);
  if (imax != null) condizioni.push(`importo_totale_eur.lte.${imax}`);
  const scadDa = soloData(valori.scad_da?.[0]);
  const scadA = soloData(valori.scad_a?.[0]);
  if (scadDa) condizioni.push(`data_scadenza.gte.${scadDa}`);
  if (scadA) condizioni.push(`data_scadenza.lte.${scadA}`);

  const select = embeds.length ? `${BANDO_SELECT_LIST},${embeds.join(',')}` : BANDO_SELECT_LIST;
  let query = supabaseBandi.from('bando').select(select, { count: 'exact' });
  for (const g of giunzioniAttive) {
    // .filter() e' l'unico metodo di supabase-js che non riscrive il nome puntato.
    query = query.filter(`${g.tabella}.${g.colonna}`, 'in', `(${g.ids.join(',')})`);
  }
  // or=(and(a,b,c)) equivale a a AND b AND c ed e' la forma usata prima dal client.
  if (condizioni.length) query = query.or(`and(${condizioni.join(',')})`);

  const da = (pagina - 1) * PER_PAGINA;
  const [{ data, count, error }, catalogo] = await Promise.all([
    query
      .order('data_pubblicazione', { ascending: false, nullsFirst: false })
      // Tiebreak indispensabile: data_pubblicazione e' NULL sul 92% dei bandi.
      .order('id', { ascending: false })
      .range(da, da + PER_PAGINA - 1),
    loadCatalogo(),
  ]);

  if (error) {
    if ((error as { code?: string }).code !== 'PGRST103') console.error('[lista bandi]', error);
    return { righe: [], totale: 0 };
  }

  const righe = ((data ?? []) as unknown as Array<Record<string, unknown>>).map((b) => ({
    ...b,
    tipologia: lookupNome(catalogo.tipologie, b.tipologia_bando_id as number | null),
    programma: lookupNome(catalogo.programmi, b.programma_id as number | null),
    modalita_erogazione: lookupNome(catalogo.modalita, b.modalita_erogazione_id as number | null),
  })) as unknown as Bando[];

  return { righe, totale: count ?? 0 };
}

export interface OpzioneCatalogo {
  value: string;
  label: string;
}

export interface OpzioniFiltroBandi {
  multiselect: Record<string, OpzioneCatalogo[]>;
  tipologie: OpzioneCatalogo[];
  stati: OpzioneCatalogo[];
}

export async function opzioniFiltroBandi(): Promise<OpzioniFiltroBandi> {
  const c = await loadCatalogo();
  const map = (righe: CatalogoRow[]): OpzioneCatalogo[] => righe.map((r) => ({ value: String(r.id), label: r.nome }));
  return {
    multiselect: {
      regione: map(c.regioni),
      settore: map(c.settori),
      beneficiario: map(c.beneficiari),
      ateco: c.codici_ateco.map((a) => ({ value: String(a.id), label: `${a.codice}${a.descrizione ? ` — ${a.descrizione}` : ''}` })),
      programma: map(c.programmi),
      modalita: map(c.modalita),
    },
    tipologie: map(c.tipologie),
    stati: [
      { value: 'aperto', label: 'Aperto' },
      { value: 'in apertura prossimamente', label: 'In apertura' },
      { value: 'chiuso', label: 'Chiuso' },
    ],
  };
}

/**
 * Se e' attiva una sola dimensione promuovibile con un solo id, restituisce lo slug
 * della pagina statica equivalente. I valori dei filtri bandi sono id di catalogo, non
 * nomi: la traduzione id -> slug passa dalle faccette del corpus.
 */
export async function dimensioneUnicaBandi(valori: Valori, pagina: number): Promise<{ dimensione: string; slug: string } | null> {
  if (pagina !== 1) return null;
  const attivi = DEF_BANDI.parametri.filter((p) => (valori[p.nome]?.length ?? 0) > 0);
  if (attivi.length !== 1) return null;
  const p = attivi[0];
  if (!p.dimensione) return null;
  const ids = soloInteri(valori[p.nome]);
  if (ids.length !== 1) return null;

  const c = await corpus('bandi');
  for (const voce of c.faccette[p.dimensione]?.values() ?? []) {
    if (voce.idsDb.includes(ids[0])) return { dimensione: p.dimensione, slug: voce.slug };
  }
  return null;
}
