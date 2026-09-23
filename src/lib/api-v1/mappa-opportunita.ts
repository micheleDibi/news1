/**
 * Da righe di interpelli, selezione del personale e bandi ai DTO dell'API (piano §3.9).
 *
 * - Oggetti costruiti campo per campo nell'ordine del contratto: nessuna colonna
 *   interna o link dello scraper puo' uscire (niente spread della riga).
 * - Ogni testo passa da pulisciTesto/pulisciElenco; gli URL sono di EduNews24, con
 *   una sola eccezione dichiarata: details.official_source.url dei bandi (1.1),
 *   la pagina dell'ente, mai un sito che ripubblica bandi altrui. In F1 e' null.
 * - `oggi` (YYYY-MM-DD di Roma) arriva dal chiamante, fissato una volta per richiesta:
 *   l'uscita non dipende dall'orologio ne' dal fuso del processo.
 * - Una riga inservibile (id, slug, titolo o data di pubblicazione non validi) da'
 *   null: il chiamante la scarta e la registra nel log.
 */
import { REGIONI, regionePerValore } from '../regioni';
import { STATI_BANDO, effectiveStatoBando } from '../stato-bando';
import { slugInterpello } from '../liste/slug-interpello';
import { interoPositivo } from './mappa-articoli';
import { percorsoSezione, sezioneDto } from './sezioni';
import {
  giornoUtc, giornoValido, istanteInterpello, istanteTimestamptz, mezzanotteRoma, rfc3339Roma, scadenzaPlausibile,
} from './tempo';
import { pulisciElenco, pulisciTesto } from './testo';
import { urlScheda } from './url';
// Le tre guardie del dominio (host, aggregatori, schema dell'URL) vengono dai
// moduli puri dei bandi: sono le stesse che usano la scheda e le liste, e
// riscriverle qui vorrebbe dire avere due denylist da tenere allineate.
import { eAggregatore, hostDi, urlPubblicabile } from '../bandi/domini';
import type { StatoBando } from '../stato-bando';
import type {
  BandoDto, CodiceAtecoDto, FonteUfficialeDto, InterpelloDto, RegioneDto, RigaBando, RigaInterpello,
  RigaSelezione, SelezioneDto, SezioneOpportunita, StatoOpportunita,
} from './contratto';

const COLLATORE_IT = new Intl.Collator('it');

/** Posizione di ogni regione nel registro: l'ordine di uscita di `regions`. */
const ORDINE_REGIONE: ReadonlyMap<string, number> = new Map(REGIONI.map((r, i) => [r.slug, i]));

const PREFISSO_INTERPELLI = /^Interpelli Pubblicati Da:\s*/i;

// v1.1: cinque stati. `sospeso` e `revocato` non usciranno finche' la
// migrazione 06 non estende il CHECK della colonna, ma la mappa e' completa da
// subito: mapparli su `closed` (o lasciarli cadere a null) sarebbe una bugia,
// e un bando revocato che esce come `open` e' il difetto che la v1.0 aveva.
const STATO_DA_BANDO: ReadonlyMap<StatoBando, StatoOpportunita> = new Map<StatoBando, StatoOpportunita>([
  ['aperto', 'open'],
  ['chiuso', 'closed'],
  ['in apertura prossimamente', 'upcoming'],
  ['sospeso', 'suspended'],
  ['revocato', 'revoked'],
]);

// ---------------------------------------------------------------------------
// Utilita'
// ---------------------------------------------------------------------------

/** Id di riga: intero sicuro > 0 (solo number: PostgREST restituisce gli integer come numeri). */
function idValido(v: unknown): number | null {
  return typeof v === 'number' && Number.isSafeInteger(v) && v > 0 ? v : null;
}

function slugRipulito(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const slug = v.trim();
  return slug === '' ? null : slug;
}

/**
 * URL della scheda, verificato: deve restare `/{sezione}/{un solo segmento}`.
 * urlScheda non codifica i punti, quindi uno slug `.` o `..` farebbe collassare
 * il percorso su un'altra pagina: in quel caso null (riga scartata).
 */
function urlSchedaVerificata(sezione: SezioneOpportunita, slug: string): string | null {
  const base = percorsoSezione(sezione);
  const url = urlScheda(base, slug);
  const segmenti = new URL(url).pathname.split('/');
  if (segmenti.length !== 3 || `/${segmenti[1]}` !== base || segmenti[2] === '') return null;
  return url;
}

function istanteOppureNull(ms: number | null): string | null {
  return ms === null ? null : rfc3339Roma(ms);
}

/** Proprieta' propria di un oggetto non array; altrimenti undefined. */
function campo(oggetto: unknown, nome: string): unknown {
  if (typeof oggetto !== 'object' || oggetto === null || Array.isArray(oggetto)) return undefined;
  if (!Object.prototype.hasOwnProperty.call(oggetto, nome)) return undefined;
  return (oggetto as Record<string, unknown>)[nome];
}

/** Embed PostgREST come elenco: un array resta tale, un oggetto diventa [oggetto], altro -> []. */
function comeElenco(v: unknown): readonly unknown[] {
  if (Array.isArray(v)) {
    const elenco: readonly unknown[] = v;
    return elenco;
  }
  if (typeof v === 'object' && v !== null) return [v];
  return [];
}

/** Nome da un embed a cardinalita' uno: `{nome}`, `[{nome}]` o null. */
function nomeDaEmbed(v: unknown): string | null {
  for (const elemento of comeElenco(v)) {
    const nome = pulisciTesto(campo(elemento, 'nome'));
    if (nome !== null) return nome;
  }
  return null;
}

function confrontaTesti(a: string, b: string): number {
  const perCollatore = COLLATORE_IT.compare(a, b);
  if (perCollatore !== 0) return perCollatore;
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Nomi da una junction con embed annidato (es. bando_settori(settori(nome))):
 * ripuliti, senza duplicati, ordinati con il collator italiano.
 */
function listaDaGiunzione(giunzione: unknown, relazione: string): string[] {
  const nomi = new Set<string>();
  for (const legame of comeElenco(giunzione)) {
    for (const voce of comeElenco(campo(legame, relazione))) {
      const nome = pulisciTesto(campo(voce, 'nome'));
      if (nome !== null) nomi.add(nome);
    }
  }
  return [...nomi].sort(confrontaTesti);
}

/** Codici ATECO da bando_codici_ateco(codici_ateco(codice, descrizione)): senza duplicati, per codice. */
function codiciAteco(giunzione: unknown): CodiceAtecoDto[] {
  const perCodice = new Map<string, CodiceAtecoDto>();
  for (const legame of comeElenco(giunzione)) {
    for (const voce of comeElenco(campo(legame, 'codici_ateco'))) {
      const code = pulisciTesto(campo(voce, 'codice'));
      if (code === null || perCodice.has(code)) continue;
      perCodice.set(code, { code, description: pulisciTesto(campo(voce, 'descrizione')) });
    }
  }
  return [...perCodice.values()].sort((a, b) => (a.code < b.code ? -1 : a.code > b.code ? 1 : 0));
}

/** Numero finito da un number o da una stringa numerica decimale; altrimenti null. */
function numeroFinito(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v !== 'string') return null;
  const testo = v.trim();
  if (!/^-?[0-9]{1,15}(?:\.[0-9]{1,6})?$/.test(testo)) return null;
  const n = Number(testo);
  return Number.isFinite(n) ? n : null;
}

/** Intero sicuro (solo number) o null: importi dei bandi (colonne bigint). */
function interoSicuro(v: unknown): number | null {
  return typeof v === 'number' && Number.isSafeInteger(v) ? v : null;
}

function statoBandoValido(v: unknown): StatoBando | null {
  for (const stato of STATI_BANDO) if (v === stato) return stato;
  return null;
}

/**
 * Regioni da valori grezzi (qualunque grafia delle tre fonti): riconosciute con il
 * registro REGIONI, senza duplicati, nell'ordine del registro. Valori non
 * stringa o non riconosciuti spariscono.
 */
export function regioniDaValori(valori: readonly unknown[]): RegioneDto[] {
  const trovate = new Map<string, RegioneDto>();
  for (const valore of valori) {
    if (typeof valore !== 'string') continue;
    const regione = regionePerValore(valore);
    if (regione !== null && !trovate.has(regione.slug)) trovate.set(regione.slug, { slug: regione.slug, name: regione.nome });
  }
  return [...trovate.values()].sort(
    (a, b) => (ORDINE_REGIONE.get(a.slug) ?? 0) - (ORDINE_REGIONE.get(b.slug) ?? 0),
  );
}

// ---------------------------------------------------------------------------
// Interpelli
// ---------------------------------------------------------------------------

function stringaOppureNull(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

/** Provincia e citta': testo ripulito senza il prefisso "Interpelli Pubblicati Da:". */
function luogoInterpello(v: unknown): string | null {
  const testo = pulisciTesto(v);
  if (testo === null) return null;
  const senzaPrefisso = testo.replace(PREFISSO_INTERPELLI, '').trim();
  return senzaPrefisso === '' ? null : senzaPrefisso;
}

/**
 * Interpello (piano §3.9). Lo slug si ricalcola con slugInterpello dai valori
 * grezzi (identico al sito e al gemello Python); le date di scadenza e lo stato
 * non esistono per questa fonte.
 */
export function mappaInterpello(riga: RigaInterpello): InterpelloDto | null {
  const id = idValido(riga.id);
  if (id === null) return null;
  const title = pulisciTesto(riga.article_title) ?? pulisciTesto(riga.interpello_name);
  if (title === null) return null;
  const pubblicazione = istanteInterpello(riga.interpello_date);
  if (pubblicazione === null) return null;
  const slug = slugInterpello({
    id,
    interpello_name: stringaOppureNull(riga.interpello_name),
    interpello_provincia: stringaOppureNull(riga.interpello_provincia),
    interpello_citta: stringaOppureNull(riga.interpello_citta),
    interpello_regione: stringaOppureNull(riga.interpello_regione),
  });
  const url = urlSchedaVerificata('interpelli', slug);
  if (url === null) return null;

  return {
    type: 'interpello',
    id,
    slug,
    url,
    title,
    summary: pulisciTesto(riga.article_subtitle) ?? pulisciTesto(riga.interpello_description),
    section: sezioneDto('interpelli'),
    published_at: rfc3339Roma(pubblicazione),
    updated_at: null,
    deadline_on: null,
    deadline_at: null,
    status: null,
    regions: regioniDaValori([riga.interpello_regione]),
    national: false,
    details: {
      official_title: pulisciTesto(riga.interpello_name),
      competition_class: pulisciTesto(riga.classe_concorso),
      province: luogoInterpello(riga.interpello_provincia),
      city: luogoInterpello(riga.interpello_citta),
    },
  };
}

// ---------------------------------------------------------------------------
// Selezione del personale
// ---------------------------------------------------------------------------

interface ScadenzaDto {
  deadline_on: string | null;
  deadline_at: string | null;
  status: StatoOpportunita | null;
}

/**
 * Regola S (piano §3.9 e domanda 7):
 * - nessuna scadenza -> tutto null;
 * - scadenza oltre 8 anni dalla pubblicazione -> date null, `open`;
 * - altrimenti `deadline_on` = giorno UTC (la slice(0,10) del sito),
 *   `deadline_at` = istante con l'offset di Roma, `open` fino al giorno della
 *   scadenza compreso, poi `closed`.
 */
function scadenzaSelezione(dataScadenza: unknown, pubblicazioneMs: number, oggi: string): ScadenzaDto {
  const scadenza = istanteTimestamptz(dataScadenza);
  if (scadenza === null) return { deadline_on: null, deadline_at: null, status: null };
  if (!scadenzaPlausibile(scadenza, pubblicazioneMs)) return { deadline_on: null, deadline_at: null, status: 'open' };
  const giorno = giornoUtc(scadenza);
  return { deadline_on: giorno, deadline_at: rfc3339Roma(scadenza), status: giorno >= oggi ? 'open' : 'closed' };
}

/** Selezione del personale (piano §3.9, regola S). `oggi` e' il giorno di Roma della richiesta. */
export function mappaSelezione(riga: RigaSelezione, oggi: string): SelezioneDto | null {
  const id = idValido(riga.id);
  if (id === null) return null;
  const slug = slugRipulito(riga.slug);
  if (slug === null) return null;
  const url = urlSchedaVerificata('selezione-personale', slug);
  if (url === null) return null;
  const title = pulisciTesto(riga.article_title) ?? pulisciTesto(riga.titolo);
  if (title === null) return null;
  const pubblicazione = istanteTimestamptz(riga.data_pubblicazione);
  if (pubblicazione === null) return null;

  const scadenza = scadenzaSelezione(riga.data_scadenza, pubblicazione, oggi);
  const sedi: readonly unknown[] = Array.isArray(riga.sedi) ? riga.sedi : [];
  const tipoProcedura = pulisciTesto(riga.tipo_procedura);

  return {
    type: 'selezione-personale',
    id,
    slug,
    url,
    title,
    summary: pulisciTesto(riga.article_subtitle),
    section: sezioneDto('selezione-personale'),
    published_at: rfc3339Roma(pubblicazione),
    updated_at: istanteOppureNull(istanteTimestamptz(riga.updated_at)),
    deadline_on: scadenza.deadline_on,
    deadline_at: scadenza.deadline_at,
    status: scadenza.status,
    regions: regioniDaValori(sedi),
    national: sedi.includes('Nazionale'),
    details: {
      official_title: pulisciTesto(riga.titolo),
      code: pulisciTesto(riga.codice),
      position: pulisciTesto(riga.figura_ricercata),
      positions_count: interoPositivo(riga.num_posti),
      procedure_type: tipoProcedura === null ? null : tipoProcedura.toUpperCase(),
      categories: pulisciElenco(riga.categorie),
      sectors: pulisciElenco(riga.settori),
      organizations: pulisciElenco(riga.enti_riferimento),
      locations: pulisciElenco(sedi).filter((sede) => sede !== 'Nazionale'),
      salary_min: numeroFinito(riga.salary_min),
      salary_max: numeroFinito(riga.salary_max),
    },
  };
}

// ---------------------------------------------------------------------------
// Bandi
// ---------------------------------------------------------------------------

/** Regioni dall'embed bando_regioni(regioni(nome, slug)): lo slug se c'e', altrimenti il nome. */
function regioniBando(giunzione: unknown): RegioneDto[] {
  const valori: unknown[] = [];
  for (const legame of comeElenco(giunzione)) {
    for (const regione of comeElenco(campo(legame, 'regioni'))) {
      const slug = campo(regione, 'slug');
      valori.push(typeof slug === 'string' ? slug : campo(regione, 'nome'));
    }
  }
  return regioniDaValori(valori);
}

/**
 * Bando (piano §3.9, regola B). `published_at` e' l'inserimento (created_at); la
 * data della fonte sta in `details.source_published_on`. Lo stato e' quello del
 * sito (effectiveStatoBando): la scadenza passata chiude, il giorno stesso e' aperto.
 */
/**
 * `official_source` dal contratto (§13.2 e 2.c.2), o `null`.
 *
 * Tre condizioni, tutte necessarie: lo stato deve essere `trovata`, l'URL deve
 * essere assoluto e http(s), e l'host non deve essere un aggregatore. La terza
 * e' una cintura: a DB c'e' un trigger che rifiuta un host in denylist, e la
 * promessa pubblica dell'API e' che nessun campo URL punti a un aggregatore.
 *
 * L'host esce minuscolo e senza `www.`, perche' lo schema lo dichiara
 * `format: hostname` e la guardia degli URL esterni dei test lo pretende.
 */
function fonteUfficialeDto(riga: RigaBando): FonteUfficialeDto | null {
  if (pulisciTesto(riga.fonte_ufficiale_stato) !== 'trovata') return null;
  // **Non** `pulisciTesto`: quella funzione toglie gli URL esterni dai campi di
  // testo, ed e' giusto che lo faccia — una stringa che e' soltanto un URL
  // esterno diventa `null`. Qui l'URL esterno e' il valore, ed e' l'unica
  // eccezione dichiarata nella promessa in testa a questo modulo. La
  // validazione la fa `urlPubblicabile`: schema http(s), niente altro.
  const grezzo = typeof riga.fonte_ufficiale_url === 'string' ? riga.fonte_ufficiale_url.trim() : '';
  const url = grezzo === '' ? null : grezzo;
  if (url === null || !urlPubblicabile(url)) return null;
  const host = hostDi(url);
  if (host === null || eAggregatore(host)) return null;
  const tipo = pulisciTesto(riga.fonte_ufficiale_tipo);
  return {
    url,
    host,
    // L'atto e' un sotto-tipo dell'ente (A32): fuori restano due valori.
    type: riga.fonte_ufficiale_e_atto === true || tipo === 'ente'
      ? 'institution'
      : (tipo === 'portale_pubblico' ? 'public_portal' : null),
    verified_on: giornoValido(
      typeof riga.fonte_ufficiale_verificata_at === 'string'
        ? riga.fonte_ufficiale_verificata_at.slice(0, 10)
        : riga.fonte_ufficiale_verificata_at,
    ),
  };
}

/** Un booleano che sappiamo, o `null` quando la fonte non lo dice. */
function booleanoONull(valore: unknown): boolean | null {
  return typeof valore === 'boolean' ? valore : null;
}

export function mappaBando(riga: RigaBando, oggi: string): BandoDto | null {
  const id = idValido(riga.id);
  if (id === null) return null;
  const slug = slugRipulito(riga.slug);
  if (slug === null) return null;
  const url = urlSchedaVerificata('bandi', slug);
  if (url === null) return null;
  const title = pulisciTesto(riga.titolo);
  if (title === null) return null;
  const inserimento = istanteTimestamptz(riga.created_at);
  if (inserimento === null) return null;

  const giornoScadenza = giornoValido(riga.data_scadenza);
  const deadlineOn = giornoScadenza !== null && scadenzaPlausibile(mezzanotteRoma(giornoScadenza), inserimento)
    ? giornoScadenza
    : null;
  const stato = effectiveStatoBando(
    statoBandoValido(riga.stato_bando),
    typeof riga.data_scadenza === 'string' ? riga.data_scadenza : null,
    oggi,
  );

  return {
    type: 'bando',
    id,
    slug,
    url,
    title,
    summary: pulisciTesto(riga.descrizione_breve),
    section: sezioneDto('bandi'),
    published_at: rfc3339Roma(inserimento),
    updated_at: istanteOppureNull(istanteTimestamptz(riga.updated_at)),
    deadline_on: deadlineOn,
    deadline_at: null,
    status: stato === null ? null : STATO_DA_BANDO.get(stato) ?? null,
    regions: regioniBando(riga.bando_regioni),
    national: pulisciTesto(riga.area_geografica)?.toLowerCase() === 'nazionale',
    details: {
      short_title: pulisciTesto(riga.titolo_breve),
      issuer: pulisciTesto(riga.ente_erogatore),
      geographic_area: pulisciTesto(riga.area_geografica),
      topics: pulisciElenco(riga.tematica),
      kind: nomeDaEmbed(riga.tipologia),
      program: nomeDaEmbed(riga.programma),
      funding_method: nomeDaEmbed(riga.modalita),
      sectors: listaDaGiunzione(riga.bando_settori, 'settori'),
      beneficiaries: listaDaGiunzione(riga.bando_beneficiari, 'beneficiari'),
      ateco_codes: codiciAteco(riga.bando_codici_ateco),
      total_amount_eur: interoSicuro(riga.importo_totale_eur),
      max_amount_per_project_eur: interoSicuro(riga.importo_max_per_progetto_eur),
      opens_on: giornoValido(riga.data_apertura),
      source_published_on: giornoValido(riga.data_pubblicazione),
      // v1.1, additivi. Restano null finche' le migrazioni 01-02 non creano le
      // colonne: `colonne.ts` non le puo' chiedere prima (PostgREST risponde
      // 42703 e fa fallire l'intera richiesta, non il singolo campo). Il
      // contratto pubblico e' pero' gia' quello definitivo, cosi' i client si
      // preparano a leggerli senza aspettare un'altra versione.
      // v1.1. Restano `null` quando si legge dalla tabella `bando`: quelle
      // colonne le da' solo la vista, e chiederle altrove farebbe rispondere
      // 42703 a PostgREST — cioe' 500 sull'intera risorsa, non un campo vuoto.
      // Il contratto e' additivo proprio per questo: un client legge `null` e
      // non si rompe.
      official_source: fonteUfficialeDto(riga),
      opens_on_verified: booleanoONull(riga.data_apertura_verificata),
      deadline_verified: booleanoONull(riga.data_scadenza_verificata),
      last_checked_at: istanteOppureNull(istanteTimestamptz(riga.ultimo_controllo_at)),
    },
  };
}
