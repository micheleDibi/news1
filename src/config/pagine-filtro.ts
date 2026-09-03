/**
 * Governo delle pagine filtro long-tail.
 *
 * QUESTO E' L'UNICO FILE DA EDITARE per decidere quali pagine esistono. Non importa
 * nulla da src/lib: e' configurazione pura.
 *
 * Una combinazione sotto soglia (o esclusa, o su una dimensione disabilitata)
 * risponde 404 reale: nessuna pagina vuota indicizzabile. Appena i dati superano la
 * soglia la pagina compare da sola, senza toccare il codice.
 *
 * ATTENZIONE: gli slug pubblicati non vanno piu' cambiati. Per rinominare qualcosa
 * si aggiunge una voce in `slugAlias`, che fa 301 verso lo slug canonico.
 */

export type Sezione = 'interpelli' | 'selezione-personale' | 'bandi';

/** Da dove arrivano i valori pubblicabili di una dimensione. */
export type FonteValori =
  /** Insieme chiuso: il registro delle 20 regioni in src/lib/regioni.ts. */
  | 'regioni'
  /** Valori distinti aggregati dai dati, filtrati per soglia ed esclusioni. */
  | 'dati';

export interface DimensioneFiltro {
  /** Secondo segmento dell'URL: /interpelli/<slug>/<valore>. */
  slug: string;
  etichetta: string;
  etichettaPlurale: string;
  abilitata: boolean;
  /** Se true esiste anche la pagina indice /sezione/<slug>. */
  hub: boolean;
  fonte: FonteValori;
  /** Minimo di annunci per pubblicare la pagina di un valore. */
  soglia: number;
  /** Valori DB (esatti) da non pubblicare mai. */
  esclusi?: string[];
  /** slug canonico -> altri valori DB che devono confluire nello stesso URL. */
  alias?: Record<string, string[]>;
  /** slug alternativo -> slug canonico (301). */
  slugAlias?: Record<string, string>;
  /** valore DB -> etichetta da mostrare al posto del valore grezzo. */
  etichette?: Record<string, string>;
}

export interface ConfigSezione {
  sezione: Sezione;
  basePath: string;
  etichetta: string;
  perPagina: number;
  dimensioni: DimensioneFiltro[];
}

/** TTL della cache delle faccette (le pipeline girano poche volte al giorno). */
export const TTL_CORPUS_MS = 15 * 60 * 1000;

export const PAGINE_FILTRO: ConfigSezione[] = [
  // ======================= INTERPELLI (1046 pubblicabili) =======================
  {
    sezione: 'interpelli',
    basePath: '/interpelli',
    etichetta: 'Interpelli scuola',
    perPagina: 20,
    dimensioni: [
      {
        slug: 'regione', etichetta: 'Regione', etichettaPlurale: 'Regioni',
        abilitata: true, hub: true, fonte: 'regioni', soglia: 3,
        // Al 03/09/2026 superano la soglia 18 regioni su 20:
        //   Lazio 296, Lombardia 124, Emilia-Romagna 83 (79 + 4 nella variante senza
        //   trattino), Toscana 65, Puglia 64, Sicilia 56, Veneto 56, Abruzzo 55,
        //   Campania 33, Marche 32, Liguria 32, Sardegna 31, Calabria 30,
        //   Friuli-Venezia Giulia 13, Piemonte 8, Umbria 8, Molise 7, Basilicata 6.
        // Trentino-Alto Adige e Valle d'Aosta hanno ZERO interpelli: niente pagina,
        // comparira' da sola quando arriveranno annunci.
        // 52 righe hanno interpello_regione NULL e restano fuori per costruzione.
      },
      {
        slug: 'provincia', etichetta: 'Provincia', etichettaPlurale: 'Province',
        abilitata: true, hub: true, fonte: 'dati', soglia: 3,
        // 99 valori distinti, 68 righe con provincia NULL. Roma 274, L'Aquila 37,
        // poi una coda lunga sotto 26: la soglia taglia circa la meta' dei valori.
      },
      {
        slug: 'classe', etichetta: 'Classe di concorso', etichettaPlurale: 'Classi di concorso',
        abilitata: true, hub: true, fonte: 'dati', soglia: 3,
        // 94 valori distinti, 248 righe con classe NULL, 36 valori con almeno 3 annunci.
        // PER, IC e KB non sono classi ministeriali: sono rumore dell'estrazione.
        esclusi: ['PER', 'IC', 'KB'],
        // Etichette: SOLO denominazioni ufficiali verificate. Non inventare la materia
        // di una classe di concorso: senza etichetta si mostra il codice, che va bene.
        etichette: {
          DSGA: 'DSGA — Direttore dei Servizi Generali e Amministrativi',
          ATA: 'Personale ATA',
        },
      },
    ],
  },

  // =================== SELEZIONE PERSONALE (12.441 pubblicati) ==================
  {
    sezione: 'selezione-personale',
    basePath: '/selezione-personale',
    etichetta: 'Concorsi e selezioni pubbliche',
    perPagina: 20,
    dimensioni: [
      {
        slug: 'regione', etichetta: 'Regione', etichettaPlurale: 'Regioni',
        abilitata: true, hub: true, fonte: 'regioni', soglia: 5,
        // sedi[] contiene [Regione, Provincia] nella grande maggioranza dei casi, e
        // copre tutte e 20 le regioni: da Lombardia 2391 a Valle d'Aosta 8.
        // "Nazionale" (502 righe) non e' una regione e non genera URL.
        esclusi: ['Nazionale'],
      },
      {
        slug: 'categoria', etichetta: 'Categoria', etichettaPlurale: 'Categorie',
        abilitata: true, hub: true, fonte: 'dati', soglia: 5,
        // Tutti e 8 i valori superano la soglia. ATTENZIONE agli spazi finali nel DB
        // ("Avviso OIV ", "Bando Apprendistato "): la query li usa esatti, lo slug li perde.
      },
      {
        slug: 'settore', etichetta: 'Settore', etichettaPlurale: 'Settori',
        // DISABILITATA: 9738 righe su 12.441 (78%) hanno settori vuoto, le pagine
        // coprirebbero un quinto del corpus. Riaccendere quando la copertura sale.
        abilitata: false, hub: true, fonte: 'dati', soglia: 20,
      },
    ],
  },

  // ============================= BANDI (1972) ==================================
  {
    sezione: 'bandi',
    basePath: '/bandi',
    etichetta: 'Bandi e finanziamenti pubblici',
    perPagina: 20,
    dimensioni: [
      {
        slug: 'regione', etichetta: 'Regione', etichettaPlurale: 'Regioni',
        abilitata: true, hub: true, fonte: 'regioni', soglia: 5,
        // Tutte e 20 pubblicate: da Piemonte 518 a Molise 304.
      },
      {
        slug: 'settore', etichetta: 'Settore', etichettaPlurale: 'Settori',
        abilitata: true, hub: true, fonte: 'dati', soglia: 5,
        // 89 settori su 90 hanno almeno 3 bandi. In testa: Supporto alle imprese 694,
        // Formazione e lavoro 681, Sviluppo e promozione territoriale 532.
      },
      {
        slug: 'programma', etichetta: 'Programma', etichettaPlurale: 'Programmi',
        abilitata: true, hub: true, fonte: 'dati', soglia: 5,
        // 810 bandi hanno programma_id NULL. 25 programmi superano i 3 bandi.
        // "FSE+" e "FSE+ - Fondo Sociale Europeo +" sono DUE righe distinte del
        // catalogo che descrivono lo stesso programma: confluiscono in un URL solo.
        alias: { 'fse-fondo-sociale-europeo': ['FSE+'] },
        slugAlias: { fse: 'fse-fondo-sociale-europeo' },
        // Il nome a catalogo ha un "+" in coda che a video legge male.
        etichette: { 'FSE+ - Fondo Sociale Europeo +': 'FSE+ — Fondo Sociale Europeo Plus' },
      },
      {
        slug: 'tipologia', etichetta: 'Tipologia', etichettaPlurale: 'Tipologie',
        abilitata: true, hub: true, fonte: 'dati', soglia: 5,
        // Bandi regionali / locali 1443, nazionali / PNRR 211, Fondazioni 166,
        // Europei 151. "Bandi internazionali" ha 1 bando: resta sotto soglia.
      },
      // NON abilitate: beneficiario (31 valori generici), codici ATECO (89, nessuna
      // domanda di ricerca su un portale editoriale), modalita di erogazione (4 valori,
      // non sono un intento di ricerca).
    ],
  },
];

export function configSezione(sezione: Sezione): ConfigSezione {
  const c = PAGINE_FILTRO.find((x) => x.sezione === sezione);
  if (!c) throw new Error(`Sezione sconosciuta: ${sezione}`);
  return c;
}

export function dimensione(sezione: Sezione, slugDimensione: string): DimensioneFiltro | null {
  return configSezione(sezione).dimensioni.find((d) => d.slug === slugDimensione) ?? null;
}

/** Dimensioni attive di una sezione, nell'ordine in cui vanno mostrate. */
export function dimensioniAttive(sezione: Sezione): DimensioneFiltro[] {
  return configSezione(sezione).dimensioni.filter((d) => d.abilitata);
}
