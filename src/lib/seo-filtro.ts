import { formatDataEstesa } from './liste/formato';
import { regionePerSlug } from './regioni';
import { hrefFiltro } from './pagine-filtro';
import type { VoceFaccetta } from './corpus';
import type { DimensioneFiltro, Sezione } from '../config/pagine-filtro';

/**
 * Testi delle pagine filtro: H1, title, meta description e le due-tre righe di
 * introduzione.
 *
 * Regola ferrea: nessun numero inventato e nessuna riga scritta a mano per un valore
 * specifico. Tutto viene da pattern applicati ai conteggi reali del corpus, e una
 * riga si emette solo se il dato che cita esiste davvero. Non si scrive mai "0".
 */

const SITO = 'https://edunews24.it';
const BRAND = ' - EduNews24';

/** Tronca su confine di parola. Nessun taglio a meta' vocabolo nelle SERP. */
export function troncaAParola(testo: string, massimo: number): string {
  if (testo.length <= massimo) return testo;
  const tagliato = testo.slice(0, massimo - 1);
  const spazio = tagliato.lastIndexOf(' ');
  return (spazio > massimo * 0.6 ? tagliato.slice(0, spazio) : tagliato).replace(/[\s,;:.-]+$/, '') + '…';
}

export interface MetaFiltro {
  h1: string;
  title: string;
  description: string;
  canonical: string;
}

export type SegmentoIntro =
  | { tipo: 'testo'; testo: string }
  | { tipo: 'link'; testo: string; href: string };

export type RigaIntro = SegmentoIntro[];

/** Complemento di luogo corretto: "nel Lazio", "nelle Marche", "in Abruzzo". */
function inLuogo(sezione: Sezione, dim: DimensioneFiltro, voce: VoceFaccetta): string {
  if (dim.slug === 'regione') return regionePerSlug(voce.slug)?.inRegione ?? `in ${voce.etichetta}`;
  if (dim.slug === 'provincia') return `in provincia di ${voce.etichetta}`;
  return '';
}

/** Titolo della pagina senza suffisso di brand, riusato anche nel breadcrumb. */
export function titoloFiltro(sezione: Sezione, dim: DimensioneFiltro, voce: VoceFaccetta): string {
  if (sezione === 'interpelli') {
    if (dim.slug === 'regione') return `Interpelli scuola ${inLuogo(sezione, dim, voce)}`;
    if (dim.slug === 'provincia') return `Interpelli scuola ${inLuogo(sezione, dim, voce)}`;
    return `Interpelli classe di concorso ${voce.etichetta}`;
  }
  if (sezione === 'selezione-personale') {
    if (dim.slug === 'regione') return `Concorsi e selezioni pubbliche ${inLuogo(sezione, dim, voce)}`;
    return `${voce.etichetta}: concorsi e selezioni pubbliche`;
  }
  if (dim.slug === 'regione') return `Bandi e finanziamenti ${inLuogo(sezione, dim, voce)}`;
  if (dim.slug === 'settore') return `Bandi per il settore ${voce.etichetta}`;
  if (dim.slug === 'programma') return `Bandi del programma ${voce.etichetta}`;
  return `${voce.etichetta}: bandi e finanziamenti`;
}

/** Etichetta breve per il breadcrumb e per i titoli delle pagine N. */
export function etichettaBreve(dim: DimensioneFiltro, voce: VoceFaccetta): string {
  return dim.slug === 'classe' ? `Classe ${voce.etichetta}` : voce.etichetta;
}

function descrizioneBase(sezione: Sezione, dim: DimensioneFiltro, voce: VoceFaccetta): string {
  const luogo = inLuogo(sezione, dim, voce);
  const aggiornato = voce.ultimaData ? `, aggiornati al ${formatDataEstesa(voce.ultimaData)}` : '';

  if (sezione === 'interpelli') {
    if (dim.slug === 'classe') {
      return `${voce.totale} interpelli per la classe di concorso ${voce.etichetta}${aggiornato}. ` +
        `Consulta gli avvisi delle scuole e apri il testo integrale di ciascuno.`;
    }
    return `${voce.totale} interpelli pubblicati dalle scuole ${luogo}${aggiornato}. ` +
      `Filtra per provincia e classe di concorso e apri il testo integrale di ogni avviso.`;
  }

  if (sezione === 'selezione-personale') {
    const aperti = voce.aperti > 0 ? ` ${voce.aperti} hanno la scadenza ancora aperta.` : '';
    if (dim.slug === 'regione') {
      return `${voce.totale} fra concorsi, avvisi di mobilità e selezioni pubbliche con sede ${luogo}.${aperti} ` +
        `Apri il testo integrale di ogni bando.`;
    }
    return `${voce.totale} annunci nella categoria ${voce.etichetta}.${aperti} ` +
      `Filtra per sede e apri il testo integrale di ogni bando.`;
  }

  const aperti = voce.aperti > 0 ? ` ${voce.aperti} sono attualmente aperti.` : '';
  if (dim.slug === 'regione') {
    return `${voce.totale} bandi di finanziamento applicabili ${luogo}.${aperti} ` +
      `Filtra per settore, beneficiario e importo.`;
  }
  if (dim.slug === 'programma') {
    return `${voce.totale} bandi finanziati dal programma ${voce.etichetta}.${aperti} ` +
      `Consulta requisiti, dotazione e scadenza di ciascuno.`;
  }
  return `${voce.totale} bandi di finanziamento nel settore ${voce.etichetta}.${aperti} ` +
    `Consulta requisiti, dotazione e scadenza di ciascuno.`;
}

export function metaFiltro(
  sezione: Sezione,
  dim: DimensioneFiltro,
  voce: VoceFaccetta,
  pagina: number,
  pagine: number,
  base: string,
): MetaFiltro {
  const titolo = titoloFiltro(sezione, dim, voce);
  const h1 = titolo;

  // Google mostra circa 60-65 caratteri: il brand si aggiunge solo se ci sta.
  const titoloPagina = pagina > 1 ? `${titolo}: pagina ${pagina} di ${pagine}` : titolo;
  const title = titoloPagina.length + BRAND.length <= 65
    ? titoloPagina + BRAND
    : troncaAParola(titoloPagina, 65);

  let description = descrizioneBase(sezione, dim, voce);
  if (pagina > 1) description = `Pagina ${pagina} di ${pagine}. ${description}`;
  description = troncaAParola(description, 160);

  return {
    h1,
    title,
    description,
    canonical: `${SITO}${pagina > 1 ? `${base}?page=${pagina}` : base}`,
  };
}

/**
 * Introduzione: due o tre righe costruite solo su dati esistenti. Ogni riga si emette
 * solo se ha i propri numeri, cosi' non compaiono mai frasi vuote o con degli zeri.
 */
export function introFiltro(
  sezione: Sezione,
  dim: DimensioneFiltro,
  voce: VoceFaccetta,
  incroci: Array<{ dimensione: string; etichettaPlurale: string; voci: Array<{ etichetta: string; totale: number; href: string }> }>,
): RigaIntro[] {
  const righe: RigaIntro[] = [];
  const luogo = inLuogo(sezione, dim, voce);
  const t = (testo: string): SegmentoIntro => ({ tipo: 'testo', testo });

  // Riga 1: quanti sono, dove, e quando e' arrivato l'ultimo.
  const soggetto =
    sezione === 'interpelli' ? (voce.totale === 1 ? 'interpello' : 'interpelli')
    : sezione === 'selezione-personale' ? (voce.totale === 1 ? 'annuncio' : 'annunci')
    : (voce.totale === 1 ? 'bando' : 'bandi');

  const dove =
    dim.slug === 'regione' || dim.slug === 'provincia' ? ` ${luogo}`
    : dim.slug === 'classe' ? ` per la classe di concorso ${voce.etichetta}`
    : dim.slug === 'programma' ? ` finanziati dal programma ${voce.etichetta}`
    : dim.slug === 'categoria' ? ` nella categoria ${voce.etichetta}`
    : ` nel settore ${voce.etichetta}`;

  const primaRiga: RigaIntro = [t(`Su EduNews24 sono raccolti ${voce.totale} ${soggetto}${dove}.`)];
  if (voce.ultimaData) primaRiga.push(t(` Il più recente è del ${formatDataEstesa(voce.ultimaData)}.`));
  if (sezione !== 'interpelli' && voce.aperti > 0 && voce.aperti < voce.totale) {
    primaRiga.push(t(` ${voce.aperti} ${voce.aperti === 1 ? 'ha' : 'hanno'} la scadenza ancora aperta.`));
  }
  righe.push(primaRiga);

  // Righe 2 e 3: le dimensioni incrociate piu' rappresentate, con i link.
  for (const incrocio of incroci) {
    const primi = incrocio.voci.slice(0, 3);
    if (primi.length < 2) continue;
    const riga: RigaIntro = [t(`${incrocio.etichettaPlurale} con più risultati: `)];
    primi.forEach((v, i) => {
      if (i > 0) riga.push(t(i === primi.length - 1 ? ' e ' : ', '));
      riga.push({ tipo: 'link', testo: v.etichetta, href: v.href });
      riga.push(t(` (${v.totale})`));
    });
    riga.push(t('.'));
    righe.push(riga);
    if (righe.length >= 3) break;
  }

  return righe;
}

/** Voce di breadcrumb del terzo livello, per generateBreadcrumbStructuredData. */
export function voceBreadcrumb(sezione: Sezione, dim: DimensioneFiltro, voce: VoceFaccetta) {
  return {
    nome: etichettaBreve(dim, voce),
    url: `${SITO}${hrefFiltro(sezione, dim.slug, voce.slug)}`,
  };
}
