/**
 * Riferimenti in memoria dell'API /api/v1 (piano §3.6, §3.8, §12):
 * - categorie e secondarie validate, che alimentano filtri, whitelist, `allowed`
 *   e il campo `category` degli articoli;
 * - profili degli autori, letti solo per risolvere `author.name`;
 * - CacheRiferimento: TTL, single-flight a freddo, copia vecchia su errore,
 *   memoria negativa breve.
 *
 * Modulo puro: le righe arrivano dal chiamante, l'orologio e il caricamento sono
 * iniettati. Nessun timer all'import (AbortSignal.timeout parte solo a richiesta).
 */
import { CATEGORY_COLORS, getCategoryHex } from '../category-colors';
import { SLUG_VALIDO } from '../slug';
import { SITO } from './costanti';
import { ErroreDati } from './errori';
import { pulisciTesto } from './testo';
import type {
  CategoriaRif, ProfiloRif, RiferimentoCategorie, RiferimentoProfili, RigaCategoria, RigaProfilo, RigaSecondaria,
  SecondariaRif,
} from './contratto';

/** Lunghezza massima di uno slug di categoria o di secondaria. */
const LUNGHEZZA_MASSIMA_SLUG = 64;
/** Lunghezza massima (in code point) di un nome di categoria o di un nome pubblico. */
export const LUNGHEZZA_MASSIMA_NOME = 80;
/** Oltre questo numero le categorie in piu' (le ultime per posizione) vengono scartate. */
const MASSIMO_CATEGORIE = 30;

const COLLATORE_IT = new Intl.Collator('it');

/** Chiavi note di CATEGORY_COLORS: evita che `constructor` o `toString` peschino dal prototipo. */
const CHIAVI_COLORE: ReadonlySet<string> = new Set(Object.keys(CATEGORY_COLORS));
const COLORE_HEX = /^#[0-9A-Fa-f]{6}$/;

/** Numero di code point (non di unita' UTF-16). */
function lunghezzaTesto(testo: string): number {
  return Array.from(testo).length;
}

function slugConforme(v: unknown): v is string {
  return typeof v === 'string' && v.length <= LUNGHEZZA_MASSIMA_SLUG && SLUG_VALIDO.test(v);
}

/** Nome ripulito, non vuoto e di al massimo 80 caratteri; altrimenti null. */
export function nomeValido(v: unknown): string | null {
  const nome = pulisciTesto(v);
  if (nome === null || lunghezzaTesto(nome) > LUNGHEZZA_MASSIMA_NOME) return null;
  return nome;
}

/**
 * Hex della categoria: `categories.color` contiene un NOME di colore (es. 'scuola').
 * Un nome sconosciuto o un valore non stringa danno il colore del brand (#004e9c).
 */
function coloreCategoria(v: unknown): string {
  if (typeof v === 'string' && (CHIAVI_COLORE.has(v) || COLORE_HEX.test(v))) return getCategoryHex(v);
  return getCategoryHex(null);
}

function confrontaCategorie(a: CategoriaRif, b: CategoriaRif): number {
  if (a.position !== b.position) {
    if (a.position === null) return 1;
    if (b.position === null) return -1;
    return a.position - b.position;
  }
  return a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0;
}

function confrontaSecondarie(a: SecondariaRif, b: SecondariaRif): number {
  const perNome = COLLATORE_IT.compare(a.name, b.name);
  if (perNome !== 0) return perNome;
  return a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0;
}

/**
 * Riferimento validato delle categorie (piano §3.8).
 *
 * Categoria: slug conforme a SLUG_VALIDO e lungo al massimo 64 caratteri, nome
 * ripulito non vuoto e al massimo 80; a parita' di slug vale la prima riga; al
 * massimo 30 (restano le prime per posizione). Secondaria: slug conforme, nome
 * valido, parent fra le categorie valide, una sola per (parent, slug).
 *
 * `scarti` descrive le righe escluse con il solo indice (nessun nome reale), per il log.
 * Nessuna categoria valida -> ErroreDati 'disponibilita': un riferimento vuoto non
 * deve mai finire in cache ne' produrre un 200 con un elenco vuoto.
 */
export function costruisciRiferimentoCategorie(
  categorie: readonly RigaCategoria[],
  secondarie: readonly RigaSecondaria[],
): { riferimento: RiferimentoCategorie; scarti: string[] } {
  const scarti: string[] = [];

  const valide: CategoriaRif[] = [];
  const slugVisti = new Set<string>();
  categorie.forEach((riga, indice) => {
    if (!slugConforme(riga.slug)) {
      scarti.push(`categoria #${indice}: slug non valido`);
      return;
    }
    const nome = nomeValido(riga.name);
    if (nome === null) {
      scarti.push(`categoria #${indice}: nome assente o troppo lungo`);
      return;
    }
    if (slugVisti.has(riga.slug)) {
      scarti.push(`categoria #${indice}: slug duplicato`);
      return;
    }
    slugVisti.add(riga.slug);
    const posizione = riga.order_id;
    valide.push({
      slug: riga.slug,
      name: nome,
      color: coloreCategoria(riga.color),
      position: typeof posizione === 'number' && Number.isSafeInteger(posizione) ? posizione : null,
      url: new URL(`/${riga.slug}`, SITO).href,
    });
  });

  valide.sort(confrontaCategorie);
  if (valide.length > MASSIMO_CATEGORIE) {
    scarti.push(`categorie: ${valide.length - MASSIMO_CATEGORIE} oltre il massimo di ${MASSIMO_CATEGORIE}`);
  }
  const ordinate = valide.slice(0, MASSIMO_CATEGORIE);
  if (ordinate.length === 0) {
    throw new ErroreDati('disponibilita', null, 'riferimento categorie vuoto');
  }
  const perSlug = new Map<string, CategoriaRif>(ordinate.map((c) => [c.slug, c]));

  const perParent = new Map<string, SecondariaRif[]>();
  const coppieViste = new Set<string>();
  secondarie.forEach((riga, indice) => {
    if (!slugConforme(riga.slug)) {
      scarti.push(`secondaria #${indice}: slug non valido`);
      return;
    }
    const nome = nomeValido(riga.name);
    if (nome === null) {
      scarti.push(`secondaria #${indice}: nome assente o troppo lungo`);
      return;
    }
    const parent = riga.parent_category_slug;
    if (typeof parent !== 'string' || !perSlug.has(parent)) {
      scarti.push(`secondaria #${indice}: categoria madre assente`);
      return;
    }
    // Entrambi gli slug sono conformi (niente '/'): la coppia e' una chiave univoca.
    const coppia = `${parent}/${riga.slug}`;
    if (coppieViste.has(coppia)) {
      scarti.push(`secondaria #${indice}: duplicata`);
      return;
    }
    coppieViste.add(coppia);
    const elenco = perParent.get(parent);
    const secondaria: SecondariaRif = { slug: riga.slug, name: nome, parent };
    if (elenco) elenco.push(secondaria);
    else perParent.set(parent, [secondaria]);
  });

  const secondariePerParent = new Map<string, readonly SecondariaRif[]>();
  for (const categoria of ordinate) {
    const elenco = perParent.get(categoria.slug);
    if (elenco) secondariePerParent.set(categoria.slug, elenco.sort(confrontaSecondarie));
  }

  return { riferimento: { perSlug, ordinate, secondariePerParent }, scarti };
}

/**
 * Riferimento dei profili (piano §3.6). `perNomeCompleto` e' indicizzato sul
 * full_name ESATTO, come l'uguaglianza della pagina dell'articolo
 * (`.eq('full_name', creator)`); piu' profili con lo stesso nome = ambiguo.
 * `fullName` serve solo al lookup e non deve mai uscire dall'API.
 */
export function costruisciRiferimentoProfili(righe: readonly RigaProfilo[]): RiferimentoProfili {
  const perId = new Map<string, ProfiloRif>();
  const perNomeCompleto = new Map<string, ProfiloRif[]>();
  for (const riga of righe) {
    if (typeof riga.id !== 'string' || riga.id === '' || perId.has(riga.id)) continue;
    const nomeCompleto = typeof riga.full_name === 'string' ? riga.full_name : null;
    const ripulito = nomeCompleto === null ? '' : nomeCompleto.trim();
    const profilo: ProfiloRif = {
      id: riga.id,
      fullName: ripulito === '' ? null : ripulito,
      publicName: typeof riga.public_name === 'string' ? riga.public_name : null,
      visualizzabile: riga.is_displayable === true,
    };
    perId.set(riga.id, profilo);
    if (nomeCompleto !== null && nomeCompleto !== '') {
      const stessi = perNomeCompleto.get(nomeCompleto);
      if (stessi) stessi.push(profilo);
      else perNomeCompleto.set(nomeCompleto, [profilo]);
    }
  }
  return { perId, perNomeCompleto };
}

// ---------------------------------------------------------------------------
// Cache dei riferimenti
// ---------------------------------------------------------------------------

/** Per quanto un errore a freddo viene rilanciato senza ritentare il caricamento. */
export const MEMORIA_NEGATIVA_MS = 5_000;
/** Dopo un rinfresco in background fallito, non se ne avvia un altro prima di... */
export const PAUSA_RINFRESCO_FALLITO_MS = 5_000;
/** Tentativi di un chiamante agganciato a caricamenti interrotti da altri chiamanti. */
const TENTATIVI_AGGANCIO = 3;

export interface OpzioniCacheRiferimento<T> {
  /** Nome per il log (es. 'categorie'). */
  nome: string;
  /** Eta' sotto cui il valore e' fresco. */
  ttlMs: number;
  /** Millisecondi (es. `Date.now`). */
  orologio: () => number;
  /** Carica e valida il riferimento; lancia su guasto o su riferimento inservibile. */
  carica: (segnale: AbortSignal) => Promise<T>;
  /** Tetto di durata di ogni caricamento. */
  timeoutMs: number;
  registra?: (evento: string, dettaglio?: string) => void;
}

interface Caricamento<T> {
  promessa: Promise<T>;
  /** Segnale del chiamante che l'ha avviato: se viene interrotto, gli agganciati ritentano. */
  segnaleOrigine: AbortSignal;
}

function descriviErrore(errore: unknown): string {
  if (errore instanceof ErroreDati) {
    return `${errore.classe}${errore.codiceDb ? ` ${errore.codiceDb}` : ''}: ${errore.message}`;
  }
  if (errore instanceof Error) return `${errore.name}: ${errore.message}`;
  return 'errore';
}

/**
 * Esegue `avvio` e ne restituisce l'esito, ma rifiuta appena `segnale` viene
 * interrotto anche se il caricamento non onora il segnale: cosi' una promessa in
 * volo si chiude sempre entro il timeout. Il rifiuto per interruzione e' un
 * ErroreDati 'disponibilita' (503 o copia stantia a valle).
 */
function entroSegnale<T>(avvio: (segnale: AbortSignal) => Promise<T>, segnale: AbortSignal, nome: string): Promise<T> {
  const interrotto = () => new ErroreDati('disponibilita', null, `riferimento ${nome}: caricamento interrotto`);
  if (segnale.aborted) return Promise.reject(interrotto());
  return new Promise<T>((risolvi, rifiuta) => {
    const suInterruzione = () => rifiuta(interrotto());
    segnale.addEventListener('abort', suInterruzione, { once: true });
    let promessa: Promise<T>;
    try {
      promessa = Promise.resolve(avvio(segnale));
    } catch (errore) {
      segnale.removeEventListener('abort', suInterruzione);
      rifiuta(errore);
      return;
    }
    promessa.then(
      (valore) => {
        segnale.removeEventListener('abort', suInterruzione);
        risolvi(valore);
      },
      (errore: unknown) => {
        segnale.removeEventListener('abort', suInterruzione);
        rifiuta(errore);
      },
    );
  });
}

/**
 * Cache per processo di un riferimento (categorie, profili):
 * - fresco (eta' < ttlMs) -> il valore;
 * - scaduto -> subito il valore vecchio e al massimo un rinfresco in background
 *   (timeout proprio); se fallisce resta il vecchio e l'evento va nel log, senza
 *   rejection non gestite; dopo un fallimento si attende 5 s prima di ritentare;
 * - freddo -> caricamento single-flight con il segnale del chiamante combinato
 *   con il timeout; un errore viene rilanciato e, per 5 s, rilanciato di nuovo
 *   senza richiamare `carica` (memoria negativa). Un'interruzione del solo
 *   chiamante non entra in memoria negativa e chi era agganciato ritenta.
 *
 * Un errore non entra mai in cache come valore: un riferimento vuoto (che
 * `carica` segnala lanciando) non sostituisce mai quello buono.
 */
export class CacheRiferimento<T> {
  private readonly nome: string;
  private readonly ttlMs: number;
  private readonly orologio: () => number;
  private readonly carica: (segnale: AbortSignal) => Promise<T>;
  private readonly timeoutMs: number;
  private readonly registra: (evento: string, dettaglio?: string) => void;

  private valore: { dato: T; caricato: number } | null = null;
  private caricamento: Caricamento<T> | null = null;
  private rinfresco: Promise<void> | null = null;
  private ultimoRinfrescoFallito: number | null = null;
  private erroreFreddo: { errore: unknown; istante: number } | null = null;

  constructor(opzioni: OpzioniCacheRiferimento<T>) {
    if (!Number.isFinite(opzioni.ttlMs) || opzioni.ttlMs <= 0) {
      throw new RangeError('CacheRiferimento: ttlMs deve essere un numero finito > 0');
    }
    if (!Number.isFinite(opzioni.timeoutMs) || opzioni.timeoutMs <= 0) {
      throw new RangeError('CacheRiferimento: timeoutMs deve essere un numero finito > 0');
    }
    this.nome = opzioni.nome;
    this.ttlMs = opzioni.ttlMs;
    this.orologio = opzioni.orologio;
    this.carica = opzioni.carica;
    this.timeoutMs = opzioni.timeoutMs;
    this.registra = opzioni.registra ?? (() => undefined);
  }

  /** Il valore se e' stato caricato almeno una volta (fresco o scaduto), altrimenti null. Non carica mai. */
  seCaldo(): T | null {
    return this.valore === null ? null : this.valore.dato;
  }

  async ottieni(segnale: AbortSignal): Promise<T> {
    const ora = this.orologio();
    if (this.valore !== null) {
      if (ora - this.valore.caricato >= this.ttlMs) this.avviaRinfresco(ora);
      return this.valore.dato;
    }

    if (this.erroreFreddo !== null) {
      if (ora - this.erroreFreddo.istante < MEMORIA_NEGATIVA_MS) throw this.erroreFreddo.errore;
      this.erroreFreddo = null;
    }

    for (let tentativo = 0; ; tentativo += 1) {
      const caricamento = this.caricamento ?? this.avviaCaricamento(segnale);
      try {
        return await caricamento.promessa;
      } catch (errore) {
        const altroInterrotto = caricamento.segnaleOrigine !== segnale && caricamento.segnaleOrigine.aborted;
        if (!altroInterrotto || segnale.aborted || tentativo + 1 >= TENTATIVI_AGGANCIO) throw errore;
        // Il caricamento a cui ci si era agganciati e' stato interrotto dal suo
        // chiamante (client andato via): si ritenta con il proprio segnale.
        const caricato = this.voceCorrente();
        if (caricato !== null) return caricato.dato;
      }
    }
  }

  /** Letta tramite metodo: dopo un await il restringimento di `this.valore` non vale piu'. */
  private voceCorrente(): { dato: T; caricato: number } | null {
    return this.valore;
  }

  /** Attende il rinfresco in background in corso, se c'e' (per i test). Non rifiuta mai. */
  async attendiRinfreschi(): Promise<void> {
    while (this.rinfresco !== null) await this.rinfresco;
  }

  private avviaCaricamento(segnale: AbortSignal): Caricamento<T> {
    const combinato = AbortSignal.any([segnale, AbortSignal.timeout(this.timeoutMs)]);
    const promessa = (async (): Promise<T> => {
      try {
        const dato = await entroSegnale((s) => this.carica(s), combinato, this.nome);
        this.valore = { dato, caricato: this.orologio() };
        this.erroreFreddo = null;
        return dato;
      } catch (errore) {
        // Un'interruzione del solo chiamante non dice nulla sulla salute del DB.
        if (!segnale.aborted) this.erroreFreddo = { errore, istante: this.orologio() };
        this.registra('riferimento-non-disponibile', `${this.nome}: ${descriviErrore(errore)}`);
        throw errore;
      } finally {
        this.caricamento = null;
      }
    })();
    const caricamento: Caricamento<T> = { promessa, segnaleOrigine: segnale };
    this.caricamento = caricamento;
    return caricamento;
  }

  private avviaRinfresco(ora: number): void {
    if (this.rinfresco !== null) return;
    if (this.ultimoRinfrescoFallito !== null && ora - this.ultimoRinfrescoFallito < PAUSA_RINFRESCO_FALLITO_MS) return;
    this.rinfresco = (async (): Promise<void> => {
      try {
        const dato = await entroSegnale((s) => this.carica(s), AbortSignal.timeout(this.timeoutMs), this.nome);
        this.valore = { dato, caricato: this.orologio() };
        this.ultimoRinfrescoFallito = null;
      } catch (errore) {
        this.ultimoRinfrescoFallito = this.orologio();
        this.registra('riferimento-rinfresco-fallito', `${this.nome}: ${descriviErrore(errore)}`);
      } finally {
        this.rinfresco = null;
      }
    })();
  }
}
