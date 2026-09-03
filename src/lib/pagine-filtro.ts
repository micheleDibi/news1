import {
  configSezione, dimensione as trovaDimensione, dimensioniAttive,
  type DimensioneFiltro, type Sezione,
} from '../config/pagine-filtro';
import { corpus, corpusSeCaldo, vociFaccetta, incrocio, type Corpus, type VoceFaccetta } from './corpus';
import { REGIONI, regionePerSlug, regionePerValore } from './regioni';
import { slugifica } from './slug';
import { rispostaNonTrovata } from './paginazione';

/**
 * Decide quali pagine filtro esistono e come si risolvono gli URL.
 *
 * Regola: una pagina esiste solo se ha contenuto sopra la soglia configurata.
 * Sotto soglia si risponde 404 reale, mai una pagina vuota indicizzabile.
 */

export type EsitoRisoluzione =
  | { stato: 'ok'; voce: VoceFaccetta; dim: DimensioneFiltro }
  /** Slug alternativo: va servito un 301 verso quello canonico. */
  | { stato: 'alias'; slugCanonico: string }
  | { stato: 'assente' };

/** Voce pubblicabile: sopra soglia e non esclusa. */
function pubblicabile(voce: VoceFaccetta | undefined, dim: DimensioneFiltro): boolean {
  return !!voce && voce.totale >= dim.soglia;
}

export async function risolvi(
  sezione: Sezione,
  slugDimensione: string,
  slugValore: string,
): Promise<EsitoRisoluzione> {
  const dim = trovaDimensione(sezione, slugDimensione);
  if (!dim || !dim.abilitata) return { stato: 'assente' };

  const canonico = dim.slugAlias?.[slugValore];
  if (canonico && canonico !== slugValore) return { stato: 'alias', slugCanonico: canonico };

  const c = await corpus(sezione);
  const voce = c.faccette[slugDimensione]?.get(slugValore);
  if (!pubblicabile(voce, dim)) return { stato: 'assente' };

  return { stato: 'ok', voce: applicaEtichetta(voce!, dim), dim };
}

/** Etichetta configurata (se c'e') al posto del valore grezzo del DB. */
function applicaEtichetta(voce: VoceFaccetta, dim: DimensioneFiltro): VoceFaccetta {
  const personalizzata = voce.valoriDb.map((v) => dim.etichette?.[v]).find(Boolean);
  return personalizzata ? { ...voce, etichetta: personalizzata } : voce;
}

/** Tutte le voci pubblicate di una dimensione, dalla piu' popolata. */
export async function vociPubblicate(sezione: Sezione, slugDimensione: string): Promise<VoceFaccetta[]> {
  const dim = trovaDimensione(sezione, slugDimensione);
  if (!dim || !dim.abilitata) return [];
  const c = await corpus(sezione);
  return vociFaccetta(c, slugDimensione)
    .filter((v) => pubblicabile(v, dim))
    .map((v) => applicaEtichetta(v, dim));
}

/** Come sopra ma solo se il corpus e' gia' in memoria: per i link opzionali. */
export function vociPubblicateSeCalde(c: Corpus | null, sezione: Sezione, slugDimensione: string): VoceFaccetta[] {
  if (!c) return [];
  const dim = trovaDimensione(sezione, slugDimensione);
  if (!dim || !dim.abilitata) return [];
  return vociFaccetta(c, slugDimensione).filter((v) => pubblicabile(v, dim)).map((v) => applicaEtichetta(v, dim));
}

/**
 * href verso una pagina filtro, ma SOLO se quella pagina esiste davvero: null altrove.
 *
 * La usano le schede di dettaglio per trasformare i badge in link. Non attende mai la
 * costruzione del corpus (sono ~15.000 pagine, non possono pagare quel costo): a cache
 * fredda restituisce null e il badge resta testo semplice. Meglio un link in meno che
 * un link verso un 404.
 */
export function hrefFiltroSePubblicata(
  sezione: Sezione,
  slugDimensione: string,
  valore: string | null | undefined,
): string | null {
  if (!valore) return null;
  const dim = trovaDimensione(sezione, slugDimensione);
  if (!dim || !dim.abilitata) return null;
  const c = corpusSeCaldo(sezione);
  if (!c) return null;

  const slug = slugDimensione === 'regione' ? (regionePerValore(valore)?.slug ?? slugifica(valore)) : slugifica(valore);
  const voce = c.faccette[slugDimensione]?.get(slug);
  if (!pubblicabile(voce, dim)) return null;
  return hrefFiltro(sezione, slugDimensione, slug);
}

export function hrefFiltro(sezione: Sezione, slugDimensione: string, slugValore: string): string {
  return `${configSezione(sezione).basePath}/${slugDimensione}/${slugValore}`;
}

/**
 * Guardia per le pagine hub: restituisce la Response 404 se la dimensione non esiste,
 * non e' abilitata o non ha nemmeno un valore sopra soglia. Le pagine hub la chiamano
 * come prima istruzione, perche' una Response si puo' restituire solo da una pagina.
 */
export async function hubNonDisponibile(sezione: Sezione, slugDimensione: string): Promise<Response | null> {
  const dim = trovaDimensione(sezione, slugDimensione);
  const cfg = configSezione(sezione);
  if (dim?.abilitata) {
    const voci = await vociPubblicate(sezione, slugDimensione);
    if (voci.length > 0) return null;
  }
  return rispostaNonTrovata(
    'Pagina non trovata',
    'Questa pagina indice non è disponibile.',
    cfg.basePath,
    `Torna a ${cfg.etichetta}`,
  );
}

export function hrefHub(sezione: Sezione, slugDimensione: string): string {
  return `${configSezione(sezione).basePath}/${slugDimensione}`;
}

/** Le "sorelle": gli altri valori della stessa dimensione, esclusa la pagina corrente. */
export async function sorelle(
  sezione: Sezione,
  slugDimensione: string,
  slugCorrente: string,
  quante = 24,
): Promise<VoceFaccetta[]> {
  const voci = await vociPubblicate(sezione, slugDimensione);
  return voci.filter((v) => v.slug !== slugCorrente).slice(0, quante);
}

export interface VoceIncrociata {
  slug: string;
  etichetta: string;
  totale: number;
  href: string;
}

/**
 * Blocco incrociato: da (dimensione, valore) verso un'altra dimensione.
 * Su /interpelli/regione/lazio produce le province del Lazio sopra soglia.
 * Costa zero query: i conteggi vengono dalle tabelle incrociate del corpus.
 */
export async function incrociate(
  sezione: Sezione,
  dimA: string,
  slugA: string,
  dimB: string,
  quante = 12,
): Promise<VoceIncrociata[]> {
  const dimensioneB = trovaDimensione(sezione, dimB);
  if (!dimensioneB || !dimensioneB.abilitata) return [];
  const c = await corpus(sezione);
  const mappaB = c.faccette[dimB];
  if (!mappaB) return [];

  return incrocio(c, dimA, slugA, dimB)
    .map(({ slug, totale }) => {
      const voce = mappaB.get(slug);
      if (!voce || !pubblicabile(voce, dimensioneB)) return null;
      return {
        slug,
        etichetta: applicaEtichetta(voce, dimensioneB).etichetta,
        totale,
        href: hrefFiltro(sezione, dimB, slug),
      };
    })
    .filter((v): v is VoceIncrociata => v !== null)
    .slice(0, quante);
}

/** Elenco completo delle pagine filtro pubblicate: serve alla sitemap dedicata. */
export async function tuttePubblicate(): Promise<Array<{ href: string; ultimaData: string | null; hub: boolean }>> {
  const risultato: Array<{ href: string; ultimaData: string | null; hub: boolean }> = [];
  for (const cfg of [configSezione('interpelli'), configSezione('selezione-personale'), configSezione('bandi')]) {
    for (const dim of cfg.dimensioni) {
      if (!dim.abilitata) continue;
      const voci = await vociPubblicate(cfg.sezione, dim.slug);
      if (dim.hub && voci.length > 0) {
        const piuRecente = voci.map((v) => v.ultimaData).filter(Boolean).sort().pop() ?? null;
        risultato.push({ href: hrefHub(cfg.sezione, dim.slug), ultimaData: piuRecente, hub: true });
      }
      for (const v of voci) {
        risultato.push({ href: hrefFiltro(cfg.sezione, dim.slug, v.slug), ultimaData: v.ultimaData, hub: false });
      }
    }
  }
  return risultato;
}

/** Ordine di presentazione degli hub in una sezione. */
export function hubDisponibili(sezione: Sezione): DimensioneFiltro[] {
  return dimensioniAttive(sezione).filter((d) => d.hub);
}

/** Regioni del registro, nell'ordine alfabetico, per gli elenchi statici. */
export function regioniOrdinate() {
  return [...REGIONI].sort((a, b) => a.nome.localeCompare(b.nome, 'it'));
}

export { regionePerSlug };
