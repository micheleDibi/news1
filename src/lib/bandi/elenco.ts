/**
 * View model della lista bandi nel design «Bandi Redesign»: gli stessi calcoli di
 * `renderVals()` e `card()` del mock, scritti una volta sola e usati dal server
 * (pagina, pagine filtro, frammento) e dallo script client (etichette dei
 * bottoni rapidi, contatore di «Tutti i filtri», preset).
 *
 * Lo stato vive nell'URL: qui nessuna funzione conosce la query string, i link
 * li costruisce il chiamante con la funzione `url` che passa (di solito
 * `urlLista(DEF_BANDI, …)`).
 *
 * Modulo «foglia»: nessun import impuro, nessuna lettura dell'orologio (`oggi`
 * lo passa il chiamante, data civile di Roma). Si carica anche nel browser.
 */
import type { Valori } from '../liste/parametri';
import { ASPETTO_STATO, aspettoStato, inScadenza, type AspettoStato } from './aspetto';
import { dataBreve } from './calendario';
import { giornoItaliano, giorniAllaScadenza, testoGiorniMancanti } from './testi-stato';

// ---------------------------------------------------------------------------
// Formati del mock
// ---------------------------------------------------------------------------

const RAGGRUPPATO = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0, useGrouping: true });
const PREDEFINITO = new Intl.NumberFormat('it-IT');
const MESI_BREVI = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'] as const;
const FORMA_GIORNO = /^(\d{4})-(\d{2})-(\d{2})/;

/** «2.148»: tessere, segmenti, conteggio dei risultati, «Mostra N bandi». */
export function numeroGrande(n: number): string {
  return RAGGRUPPATO.format(n);
}

/** «1391»: il numero accanto alle opzioni delle tendine, formato it-IT predefinito. */
export function numeroOpzione(n: number): string {
  return PREDEFINITO.format(n);
}

/** «200.000 €». */
export function eur(n: number): string {
  return `${RAGGRUPPATO.format(n)} €`;
}

/**
 * «7 mln €», «432.000 €»: la formula del mock alla lettera. Il formattatore non
 * ha decimali, quindi i milioni si arrotondano all'unita' (6.905.000 → «7 mln €»).
 * Dal miliardo in su il `.replace('.', ',')` del mock trasformerebbe il punto
 * delle migliaia in una virgola («3,292 mln €» per 3.292.000.000, che si legge
 * tre milioni): li' il punto resta.
 */
export function eurBreve(n: number): string {
  if (n >= 1e9) return `${RAGGRUPPATO.format(Math.round(n / 1e6))} mln €`;
  return n >= 1e6
    ? `${RAGGRUPPATO.format(Math.round(n / 1e5) / 10).replace('.', ',')} mln €`
    : `${RAGGRUPPATO.format(n)} €`;
}

/** `2026-10-31` → { giorno: '31', meseAnno: 'ott 2026' }: la colonna data della card. */
export function colonnaData(iso: string | null | undefined): { giorno: string; meseAnno: string } | null {
  const m = typeof iso === 'string' ? FORMA_GIORNO.exec(iso) : null;
  if (!m) return null;
  return { giorno: String(Number(m[3])), meseAnno: `${MESI_BREVI[Number(m[2]) - 1]} ${m[1]}` };
}

/** `iso` + `n` giorni, in aritmetica UTC: il risultato non dipende dal fuso del processo. */
export function aggiungiGiorni(iso: string, n: number): string {
  const t = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  return new Date(t + n * 86_400_000).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Gruppi di filtri
// ---------------------------------------------------------------------------

export type ChiaveGruppo = 'regione' | 'tipologia' | 'beneficiario' | 'settore' | 'programma' | 'modalita' | 'ateco';

/** I sette gruppi del pannello «Tutti i filtri», nell'ordine del mock. */
export const GRUPPI_FILTRO: ReadonlyArray<{ chiave: ChiaveGruppo; etichetta: string }> = [
  { chiave: 'regione', etichetta: 'Regione' },
  { chiave: 'tipologia', etichetta: 'Tipologia' },
  { chiave: 'beneficiario', etichetta: 'Beneficiario' },
  { chiave: 'settore', etichetta: 'Settore' },
  { chiave: 'programma', etichetta: 'Programma' },
  { chiave: 'modalita', etichetta: 'Modalità' },
  { chiave: 'ateco', etichetta: 'Codice ATECO' },
];

/** I quattro gruppi con un bottone rapido nella barra. */
export const GRUPPI_RAPIDI: readonly ChiaveGruppo[] = ['regione', 'tipologia', 'beneficiario', 'settore'];

export interface OpzioneFiltro {
  /** Valore della checkbox: un id, o piu' id separati da virgola per gli alias. */
  valore: string;
  etichetta: string;
  /** null se il conteggio non e' disponibile: il numero non si mostra. */
  conteggio: number | null;
}

export interface GruppoFiltro {
  chiave: ChiaveGruppo;
  etichetta: string;
  opzioni: OpzioneFiltro[];
}

export interface RigaCatalogo {
  id: number;
  etichetta: string;
}

export interface VoceRaggruppata {
  idsDb: readonly number[];
  etichetta: string;
  totale: number;
}

/** Valore di un'opzione che raccoglie piu' id: ordinati, separati da virgola. */
export function valoreDiIds(ids: readonly number[]): string {
  return [...new Set(ids)].sort((a, b) => a - b).join(',');
}

/** Gli id di un valore di filtro (`"9,12"` → [9, 12]); i pezzi non numerici si scartano. */
export function idsDiValore(valore: string): number[] {
  return valore.split(',').filter((v) => /^\d+$/.test(v)).map(Number);
}

/**
 * true se l'opzione e' fra le scelte: lo stesso valore, oppure un valore i cui id
 * sono tutti dell'opzione (un vecchio `?programma=9` quando l'opzione e' «9,12»).
 */
export function opzioneSelezionata(opzione: OpzioneFiltro, selezionati: readonly string[]): boolean {
  const propri = new Set(idsDiValore(opzione.valore));
  return selezionati.some((s) => {
    if (s === opzione.valore) return true;
    const ids = idsDiValore(s);
    return ids.length > 0 && ids.every((id) => propri.has(id));
  });
}

/**
 * Le opzioni di un gruppo, nell'ordine del catalogo.
 *
 * Le righe di catalogo che il corpus fa confluire nella stessa voce (gli alias,
 * es. le due righe di FSE+) diventano una sola opzione con tutti i loro id e il
 * conteggio della voce. Le altre hanno il conteggio per id. Le opzioni a zero
 * spariscono, tranne quelle scelte; senza conteggi (null) restano tutte.
 */
export function costruisciOpzioni(
  righe: readonly RigaCatalogo[],
  voci: readonly VoceRaggruppata[] | null,
  conteggiPerId: ReadonlyMap<number, number> | null,
  selezionati: readonly string[],
): OpzioneFiltro[] {
  const vocePerId = new Map<number, VoceRaggruppata>();
  for (const v of voci ?? []) for (const id of v.idsDb) vocePerId.set(id, v);

  const emesse = new Set<VoceRaggruppata>();
  const opzioni: OpzioneFiltro[] = [];
  for (const riga of righe) {
    const voce = vocePerId.get(riga.id);
    if (voce) {
      if (emesse.has(voce)) continue;
      emesse.add(voce);
      opzioni.push({ valore: valoreDiIds(voce.idsDb), etichetta: voce.etichetta, conteggio: voce.totale });
    } else {
      opzioni.push({
        valore: String(riga.id),
        etichetta: riga.etichetta,
        conteggio: conteggiPerId ? (conteggiPerId.get(riga.id) ?? 0) : null,
      });
    }
  }
  return opzioni.filter((o) => o.conteggio === null || o.conteggio > 0 || opzioneSelezionata(o, selezionati));
}

/** Etichetta di un valore scelto, anche se e' un vecchio id singolo di un gruppo alias. */
function etichettaValore(gruppo: GruppoFiltro | undefined, valore: string): string {
  const opzioni = gruppo?.opzioni ?? [];
  const esatta = opzioni.find((o) => o.valore === valore);
  if (esatta) return esatta.etichetta;
  const contenitore = opzioni.find((o) => opzioneSelezionata(o, [valore]));
  return contenitore?.etichetta ?? valore;
}

/** Testo del bottone rapido: «Regione», «Piemonte», «Regione · 2». */
export function etichettaRapida(etichettaGruppo: string, scelte: readonly string[]): string {
  if (scelte.length === 0) return etichettaGruppo;
  if (scelte.length === 1) return scelte[0];
  return `${etichettaGruppo} · ${scelte.length}`;
}

// ---------------------------------------------------------------------------
// Parametri e conteggi dei filtri
// ---------------------------------------------------------------------------

/** Parametri di sola presentazione: non sono filtri e il reset li conserva. */
export const PARAMETRI_PRESENTAZIONE = ['ordina', 'vista'] as const;

const valore1 = (valori: Valori, nome: string): string => valori[nome]?.[0] ?? '';

/** Filtri di contenuto attivi (tutto tranne `ordina` e `vista`). */
export function contaFiltriContenuto(valori: Valori): number {
  return Object.entries(valori)
    .filter(([nome, v]) => !(PARAMETRI_PRESENTAZIONE as readonly string[]).includes(nome) && v.length > 0)
    .length;
}

/**
 * Il numero sul bottone «Tutti i filtri»: le scelte nei sette gruppi, piu' uno
 * per l'importo e uno per la scadenza (come `advCount` del mock).
 */
export function contaAvanzati(valori: Valori): number {
  let n = 0;
  for (const g of GRUPPI_FILTRO) n += valori[g.chiave]?.length ?? 0;
  if (valore1(valori, 'imin') || valore1(valori, 'imax')) n++;
  if (valore1(valori, 'scad_da') || valore1(valori, 'scad_a')) n++;
  return n;
}

/**
 * Valori con `ordina`, `vista` e `in_scadenza` validi: un valore non ammesso
 * sparisce (es. `ordina=scadenza`, che e' il predefinito). `cambiato` dice al
 * chiamante se serve un 301 verso l'URL pulito.
 */
export function normalizzaPresentazione(valori: Valori): { valori: Valori; cambiato: boolean } {
  const ammessi: Record<string, readonly string[]> = {
    ordina: ['importo', 'recenti'],
    vista: ['griglia'],
    in_scadenza: ['si'],
  };
  let cambiato = false;
  const puliti: Valori = { ...valori };
  for (const [nome, validi] of Object.entries(ammessi)) {
    const v = puliti[nome] ?? [];
    const tenuti = v.filter((x) => validi.includes(x));
    if (tenuti.length !== v.length) {
      cambiato = true;
      puliti[nome] = tenuti;
    }
  }
  return { valori: puliti, cambiato };
}

/** Copia dei valori con alcune chiavi sostituite. */
export function conValori(valori: Valori, modifiche: Valori): Valori {
  return { ...valori, ...modifiche };
}

/** Copia dei valori senza un valore (o senza l'intero parametro se `valore` manca). */
export function senzaValore(valori: Valori, nome: string, valore?: string): Valori {
  return { ...valori, [nome]: valore === undefined ? [] : (valori[nome] ?? []).filter((v) => v !== valore) };
}

/** Valori del reset: via ogni filtro, restano ordinamento e vista (`resetAll` del mock). */
export function valoriReset(valori: Valori): Valori {
  const tenuti: Valori = {};
  for (const nome of PARAMETRI_PRESENTAZIONE) tenuti[nome] = valori[nome] ?? [];
  return tenuti;
}

// ---------------------------------------------------------------------------
// Chip dei filtri attivi
// ---------------------------------------------------------------------------

export interface Chip {
  /** «Regione», «Stato»… vuota per «In scadenza». */
  chiave: string;
  valore: string;
  /** URL della lista senza questo filtro. */
  href: string;
}

export type UrlDa = (valori: Valori) => string;

/** Le chip nell'ordine del mock: ricerca, stato, in scadenza, gruppi, importo, scadenza. */
export function chipFiltri(valori: Valori, gruppi: readonly GruppoFiltro[], url: UrlDa): Chip[] {
  const chip: Chip[] = [];
  const q = valore1(valori, 'q').trim();
  if (q) chip.push({ chiave: 'Ricerca', valore: `“${q}”`, href: url(senzaValore(valori, 'q')) });

  const stato = valore1(valori, 'stato');
  if (stato) {
    chip.push({ chiave: 'Stato', valore: aspettoStato(stato)?.etichetta ?? stato, href: url(senzaValore(valori, 'stato')) });
  }
  if (valore1(valori, 'in_scadenza')) {
    chip.push({ chiave: '', valore: 'In scadenza', href: url(senzaValore(valori, 'in_scadenza')) });
  }

  for (const g of GRUPPI_FILTRO) {
    const gruppo = gruppi.find((x) => x.chiave === g.chiave);
    for (const v of valori[g.chiave] ?? []) {
      chip.push({ chiave: g.etichetta, valore: etichettaValore(gruppo, v), href: url(senzaValore(valori, g.chiave, v)) });
    }
  }

  const imin = valore1(valori, 'imin');
  const imax = valore1(valori, 'imax');
  if (imin || imax) {
    const testo = imin && imax
      ? `${eurBreve(Number(imin))} – ${eurBreve(Number(imax))}`
      : imin ? `da ${eurBreve(Number(imin))}` : `fino a ${eurBreve(Number(imax))}`;
    chip.push({ chiave: 'Importo', valore: testo, href: url(conValori(valori, { imin: [], imax: [] })) });
  }

  const da = valore1(valori, 'scad_da');
  const a = valore1(valori, 'scad_a');
  if (da || a) {
    const testo = da && a ? `${dataBreve(da)} – ${dataBreve(a)}` : da ? `dal ${dataBreve(da)}` : `entro ${dataBreve(a)}`;
    chip.push({ chiave: 'Scadenza', valore: testo, href: url(conValori(valori, { scad_da: [], scad_a: [] })) });
  }
  return chip;
}

// ---------------------------------------------------------------------------
// Hero, segmenti di stato e preset
// ---------------------------------------------------------------------------

export interface ConteggiStato {
  tutti: number;
  aperti: number;
  inApertura: number;
  chiusi: number;
  inScadenza: number;
}

export interface Tessera {
  numero: string;
  etichetta: string;
  href: string;
  attiva: boolean;
  /** Chiave stabile per ritrovare il focus dopo la sostituzione della regione. */
  chiave: string;
}

/** Le tre tessere dell'hero: cliccarne una imposta stato e «in scadenza» come nel mock. */
export function tessere(valori: Valori, c: ConteggiStato, url: UrlDa): Tessera[] {
  const stato = valore1(valori, 'stato');
  const urgenti = valore1(valori, 'in_scadenza') === 'si';
  return [
    {
      chiave: 'aperti',
      numero: numeroGrande(c.aperti),
      etichetta: 'bandi aperti',
      href: url(conValori(valori, { stato: ['aperto'], in_scadenza: [] })),
      attiva: stato === 'aperto' && !urgenti,
    },
    {
      chiave: 'in-scadenza',
      numero: numeroGrande(c.inScadenza),
      etichetta: 'scadono entro 15 giorni',
      href: url(conValori(valori, { in_scadenza: ['si'], stato: [] })),
      attiva: urgenti,
    },
    {
      chiave: 'in-apertura',
      numero: numeroGrande(c.inApertura),
      etichetta: 'in apertura prossimamente',
      href: url(conValori(valori, { stato: ['in apertura prossimamente'], in_scadenza: [] })),
      attiva: stato === 'in apertura prossimamente',
    },
  ];
}

export interface Segmento {
  etichetta: string;
  /** Valore del radio `stato`: vuoto per «Tutti». */
  valore: string;
  conteggio: string;
  attivo: boolean;
}

/** I quattro segmenti di stato della barra. */
export function segmentiStato(valori: Valori, c: ConteggiStato): Segmento[] {
  const stato = valore1(valori, 'stato');
  const s = (etichetta: string, valore: string, n: number): Segmento =>
    ({ etichetta, valore, conteggio: numeroGrande(n), attivo: stato === valore });
  return [
    s('Tutti', '', c.tutti),
    s('Aperti', 'aperto', c.aperti),
    s(ASPETTO_STATO['in apertura prossimamente'].etichetta, 'in apertura prossimamente', c.inApertura),
    s('Chiusi', 'chiuso', c.chiusi),
  ];
}

export interface Preset {
  etichetta: string;
  da: string;
  a: string;
  attivo: boolean;
}

/** Preset dell'importo: scrivono `imin`/`imax`. */
export function presetImporto(valori: Valori): Preset[] {
  const imin = valore1(valori, 'imin');
  const imax = valore1(valori, 'imax');
  const p = (etichetta: string, da: string, a: string): Preset => ({ etichetta, da, a, attivo: imin === da && imax === a });
  return [
    p('Fino a 100.000 €', '', '100000'),
    p('100.000 – 1 mln €', '100000', '1000000'),
    p('Oltre 1 mln €', '1000000', ''),
  ];
}

/** Preset della scadenza: da oggi a oggi + N giorni. */
export function presetScadenza(valori: Valori, oggi: string): Preset[] {
  const da = valore1(valori, 'scad_da');
  const a = valore1(valori, 'scad_a');
  const p = (etichetta: string, giorni: number): Preset => {
    const fine = aggiungiGiorni(oggi, giorni);
    return { etichetta, da: oggi, a: fine, attivo: da === oggi && a === fine };
  };
  return [p('Entro 7 giorni', 7), p('Entro 30 giorni', 30), p('Entro 3 mesi', 90)];
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export interface ModelloCard {
  aspetto: AspettoStato | null;
  /** Aperto e in scadenza entro 15 giorni: palette arancio. */
  urgente: boolean;
  /** «tra 36 giorni», «scade domani», «scade oggi»: solo per un aperto non scaduto. */
  giorniTesto: string | null;
  data: { giorno: string; meseAnno: string } | null;
  /** «31 ottobre 2026» oppure «Non indicata». */
  scadenzaLunga: string;
  /** «200.000 €» oppure null. */
  dotazione: string | null;
  /** «7 mln €» oppure «Non indicata». */
  dotazioneBreve: string;
}

export function modelloCard(
  b: { stato: string | null | undefined; data_scadenza: string | null | undefined; importo_totale_eur: number | null | undefined },
  oggi: string,
): ModelloCard {
  const giorni = b.data_scadenza ? giorniAllaScadenza(b.data_scadenza, oggi) : null;
  const conGiorni = b.stato === 'aperto' && giorni !== null && giorni >= 0;
  const importo = typeof b.importo_totale_eur === 'number' && Number.isFinite(b.importo_totale_eur) ? b.importo_totale_eur : null;
  return {
    aspetto: aspettoStato(b.stato),
    urgente: inScadenza(b.stato, giorni),
    giorniTesto: conGiorni ? testoGiorniMancanti(giorni) : null,
    data: colonnaData(b.data_scadenza),
    scadenzaLunga: giornoItaliano(b.data_scadenza) ?? 'Non indicata',
    dotazione: importo !== null ? eur(importo) : null,
    dotazioneBreve: importo !== null ? eurBreve(importo) : 'Non indicata',
  };
}

// ---------------------------------------------------------------------------
// Testi della pagina
// ---------------------------------------------------------------------------

/** Title della lista, identico fra pagina e frammento. */
export function titoloLista(pagina: number, pagine: number): string {
  return pagina > 1
    ? `Bandi e finanziamenti pubblici: pagina ${pagina} di ${pagine} - EduNews24`
    : 'Bandi e finanziamenti pubblici - EduNews24';
}

/** Testata della lista /bandi: la stessa nella pagina e nel frammento. */
export const TESTATA_LISTA = {
  briciole: [{ etichetta: 'Home', href: '/' }, { etichetta: 'Bandi' }],
  titolo: 'Bandi e finanziamenti pubblici',
  testo: 'Bandi europei (FESR, FSE+, Interreg), nazionali e regionali, aggiornati ogni giorno.',
  bandofit: 'lista-hero',
} as const satisfies {
  briciole: ReadonlyArray<{ etichetta: string; href?: string }>;
  titolo: string;
  testo: string;
  bandofit: string;
};
