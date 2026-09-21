/**
 * Testi italiani della documentazione dell'API /api/v1, condivisi da openapi.ts
 * (descrizioni del documento OpenAPI) e da documentazione.ts (pagina
 * /sviluppatori/api). Contiene anche gli esempi: sono tipizzati con i DTO di
 * contratto.ts, quindi tsc rifiuta un esempio che non rispetta il contratto.
 *
 * Solo dati e composizione di stringhe: nessun I/O, nessuna data calcolata
 * dall'orologio (la nota sui termini e il changelog hanno date fisse).
 */
import { slugInterpello } from '../liste/slug-interpello';
import {
  AUTORE_REDAZIONE, BASE_API, CONTENT_SIGNAL, ELEMENTI_FEED, LIMITE_MASSIMO, LIMITE_PREDEFINITO,
  LUNGHEZZA_MASSIMA_CURSORE, LUNGHEZZA_MASSIMA_QUERY, LUNGHEZZA_MASSIMA_VALORE, LUNGHEZZA_SINTESI,
  RATE_LIMIT_CAPACITA, RATE_LIMIT_POLICY, RATE_LIMIT_RICARICA, SITO, TESTO_ATTRIBUZIONE, URL_DOCUMENTAZIONE,
  URL_OPENAPI, URL_TERMINI, VERSIONE_API,
} from './costanti';
import { sezioneDto } from './sezioni';
import type {
  ArticoloDto, BandoDto, CategoriaDto, InterpelloDto, Risorsa, SelezioneDto, VideoDto,
} from './contratto';
import type { CodiceErrore } from './errori';
import type { NomeParametro } from './parametri';

export const TITOLO_API = 'API pubblica EduNews24';

/** Data della prima versione pubblica e della nota provvisoria sui termini. */
export const DATA_RILASCIO = '2026-09-21';
export const DATA_RILASCIO_ESTESA = '21 settembre 2026';

export const DESCRIZIONE_BREVE =
  'API pubblica in sola lettura di EduNews24: articoli, categorie, interpelli, concorsi e selezioni ' +
  'pubbliche, bandi e finanziamenti. JSON con paginazione a cursore, più JSON Feed 1.1 e RSS 2.0 per ' +
  'ciascuna sezione. Nessuna chiave richiesta, con limiti di frequenza e cache.';

export const USER_AGENT_ESEMPIO = 'MioServizio/1.0 (+https://example.org/contatti)';

// ---------------------------------------------------------------------------
// Introduzione e formato
// ---------------------------------------------------------------------------

export const PARAGRAFI_INTRODUZIONE: readonly string[] = [
  DESCRIZIONE_BREVE,
  `Base URL: ${BASE_API}. Metodi ammessi: GET, HEAD e OPTIONS. Il formato sta nell'URL (JSON per le ` +
    'risorse, .json o .xml per i feed): la negoziazione con l\'header Accept non è usata.',
  `L'API espone solo sintesi e metadati: il testo integrale resta sulle pagine del sito, a cui ogni ` +
    'elemento rimanda con il campo url. Descrizione formale: ' + URL_OPENAPI + '.',
];

export const PARAGRAFI_FORMATO: readonly string[] = [
  'Ogni risposta JSON ha la forma {data, meta, links}: data è un array negli elenchi e un oggetto nei ' +
    'dettagli. meta riporta versione, risorsa, attribuzione obbligatoria e link ai termini; negli elenchi ' +
    'anche count, limit, has_more, sort e i filtri applicati (tutti presenti, null se non usati).',
  'Nomi di campi, parametri ed enum in inglese snake_case; testi in italiano. Le chiavi escono sempre ' +
    'nello stesso ordine.',
  'Ogni campo è sempre presente: null significa "non disponibile". Gli array non sono mai null e le ' +
    'stringhe non sono mai vuote.',
  'Gli URL sono sempre assoluti su ' + SITO + '. Non ci sono link alle fonti esterne.',
  'La chiave di un elemento è il suo id numerico, unico per tipo: gli slug sono informativi e non ' +
    'univoci. I client deduplicano per (type, id).',
];

// ---------------------------------------------------------------------------
// Date
// ---------------------------------------------------------------------------

export const PARAGRAFI_DATE: readonly string[] = [
  'Gli istanti sono in RFC 3339 con l\'offset di Europe/Rome valido in quel momento (+01:00 o +02:00) e ' +
    'sono troncati al secondo, per esempio 2026-09-21T09:18:28+02:00. Le date di calendario (campi *_on) ' +
    'sono nella forma YYYY-MM-DD.',
  'since è inclusivo e until esclusivo: finestre [since, until) contigue non si sovrappongono e non ' +
    'lasciano buchi. Poiché i valori sono troncati al secondo, usare come since l\'ultimo published_at ' +
    'visto non fa perdere elementi: al più se ne rivede qualcuno, da deduplicare.',
  'I parametri since, until e updated_since accettano un istante RFC 3339 con fuso obbligatorio (Z o ' +
    '±HH:MM; in una query "+" va codificato come %2B) oppure una data YYYY-MM-DD del calendario di Roma: ' +
    'since=2026-09-21 parte dalle 00:00 di Roma, until=2026-09-21 arriva alle 00:00 del giorno dopo ' +
    '(giorno compreso). Un istante senza fuso è rifiutato; anni ammessi 2000-2100; le frazioni di secondo ' +
    'si troncano.',
  'published_at degli articoli: la colonna di origine non conserva il fuso e contiene valori scritti da ' +
    'sistemi diversi. L\'API lo ricostruisce con un\'euristica. Errore noto: circa 436 articoli ' +
    'pubblicati fra maggio e dicembre 2025 risultano spostati in avanti di 1-2 ore. L\'ordinamento avviene ' +
    'sul valore originale, quindi fra le righe storiche l\'ordine può non essere monotono entro 2 ore.',
  'published_at delle altre risorse: interpelli, mezzanotte di Roma del giorno indicato dalla fonte; ' +
    'selezione del personale, data di pubblicazione sul portale inPA; bandi, data di inserimento in ' +
    'EduNews24 (la data della fonte è in details.source_published_on).',
  'Sono possibili date future (per esempio una pubblicazione programmata): l\'API le espone come il sito, ' +
    'senza filtrarle in base all\'orologio.',
  'deadline_on è il giorno di scadenza come mostrato sul sito. Bandi: la data di scadenza della fonte ' +
    '(deadline_at è null). Selezione del personale: il giorno UTC di data_scadenza; per le scadenze fra le ' +
    '00:00 e le 01:59 di Roma (00:59 con l\'ora solare), tipicamente «ore 24:00 del giorno D», vale D, un ' +
    'giorno prima della data locale di deadline_at. status usa deadline_on.',
];

// ---------------------------------------------------------------------------
// Paginazione e sincronizzazione
// ---------------------------------------------------------------------------

export const PARAGRAFI_PAGINAZIONE: readonly string[] = [
  `Gli elenchi sono ordinati dal più recente (sort "-published_at,-id") e paginati con un cursore ` +
    `opaco. limit vale ${LIMITE_PREDEFINITO} per default, al massimo ${LIMITE_MASSIMO}. Niente offset, ` +
    'niente conteggio totale, niente pagina precedente.',
  'Per scorrere un elenco si segue links.next (lo stesso URL è nell\'header Link con rel="next"). ' +
    'has_more vale sempre esattamente links.next !== null.',
  'Una pagina può contenere meno di limit elementi, anche zero, con has_more true: non è la fine ' +
    'dell\'elenco. Fermarsi solo quando links.next è null.',
  'Il cursore è legato ai filtri: fra una pagina e l\'altra si può cambiare limit, non i filtri (la ' +
    'risposta sarebbe 400 invalid-cursor). Il cursore non va costruito né modificato a mano.',
];

export interface PassoSincronizzazione {
  /** Etichetta umana delle risorse coinvolte. */
  risorse: string;
  /** Risorse a cui il passo si applica (per le descrizioni OpenAPI). */
  per: readonly Risorsa[];
  testo: string;
}

export const GUIDA_SINCRONIZZAZIONE: readonly PassoSincronizzazione[] = [
  {
    risorse: 'articles',
    per: ['articles'],
    testo: 'interrogare periodicamente con since = min(massimo published_at visto, adesso) − 3 ore, seguire ' +
      'links.next fino a null e deduplicare per (type, id). Un articolo ripubblicato riceve un nuovo ' +
      'published_at e risale in cima.',
  },
  {
    risorse: 'selezione-personale e bandi',
    per: ['selezione-personale', 'bandi'],
    testo: 'usare updated_since = massimo updated_at visto − 3 ore, poi deduplicare. Lo scadere di una ' +
      'scheda non aggiorna updated_at: lo stato va ricalcolato da deadline_on quando non è null; altrimenti ' +
      'vale status.',
  },
  {
    risorse: 'interpelli',
    per: ['interpelli'],
    testo: 'non hanno una data di modifica: serve una riscansione completa periodica (poco più di 1.200 ' +
      'elementi, 13 richieste con limit=100).',
  },
  {
    risorse: 'tutte',
    per: ['articles', 'interpelli', 'selezione-personale', 'bandi'],
    testo: 'una riscansione completa settimanale per accorgersi delle rimozioni; un elemento che risponde ' +
      '404 va rimosso dalla propria copia.',
  },
];

export const PARAGRAFO_DEDUPLICA =
  'Lo stesso elemento può comparire più volte (ripubblicazione, finestre sovrapposte, feed): la chiave di ' +
  'deduplica è la coppia (type, id).';

export const CODICE_SINCRONIZZAZIONE = [
  '// Sincronizzazione incrementale degli articoli (Node 18+)',
  `let url = '${BASE_API}/articles?since=2026-09-21T06:00:00%2B02:00&limit=100';`,
  'while (url) {',
  '  // Nel browser omettere User-Agent: non è ammesso nel preflight CORS.',
  `  const r = await fetch(url, { headers: { 'User-Agent': '${USER_AGENT_ESEMPIO}' } });`,
  '  if (r.status === 429 || r.status === 503) {',
  '    const attesa = Number(r.headers.get(\'retry-after\')) || 30;',
  '    await new Promise((fatto) => setTimeout(fatto, attesa * 1000));',
  '    continue;',
  '  }',
  '  if (!r.ok) throw new Error(\'HTTP \' + r.status);',
  '  const pagina = await r.json();',
  '  for (const elemento of pagina.data) salva(elemento.type + \'/\' + elemento.id, elemento);',
  '  url = pagina.links.next; // null = fine; una pagina corta o vuota NON è la fine',
  '}',
].join('\n');

// ---------------------------------------------------------------------------
// Filtri
// ---------------------------------------------------------------------------

export const REGOLE_PARAMETRI: ReadonlyMap<NomeParametro, string> = new Map<NomeParametro, string>([
  ['category', 'Slug di una categoria di /api/v1/categories. Uno slug malformato è un errore di forma come gli ' +
    'altri; uno slug ben formato ma sconosciuto dà, dopo i controlli di forma, un 400 a parte con l\'elenco ' +
    'dei valori ammessi (allowed).'],
  ['has_video', 'true o false esatti: solo articoli con (o senza) video.'],
  ['region', 'Uno dei 20 slug regione (enum nel documento OpenAPI). Seleziona gli elementi il cui array ' +
    'regions contiene la regione. Uno slug valido senza elementi dà 200 con data vuoto.'],
  ['national', 'true o false esatti: elementi di portata nazionale (o non nazionali).'],
  ['since', 'Inizio della finestra su published_at, inclusivo. Data YYYY-MM-DD (00:00 di Roma) o istante ' +
    'RFC 3339 con fuso.'],
  ['until', 'Fine della finestra su published_at, esclusiva. Una data YYYY-MM-DD comprende tutto quel ' +
    'giorno. Deve seguire since.'],
  ['updated_since', 'Solo elementi con updated_at maggiore o uguale al valore. Stessa sintassi di since.'],
  ['limit', `Intero da 1 a ${LIMITE_MASSIMO}, default ${LIMITE_PREDEFINITO}.`],
  ['cursor', 'Valore opaco ricevuto in links.next. Legato alla risorsa e ai filtri.'],
]);

export const PARAGRAFI_REGOLE_FILTRI: readonly string[] = [
  'Un parametro non previsto dà 400 unknown-parameter; ripetuto, vuoto o malformato dà 400 ' +
    `invalid-parameter. Valori oltre ${LUNGHEZZA_MASSIMA_VALORE} caratteri (${LUNGHEZZA_MASSIMA_CURSORE} per ` +
    `cursor) sono rifiutati; una query oltre ${LUNGHEZZA_MASSIMA_QUERY} caratteri dà un solo errore, con ` +
    'parameter "(query)".',
  'La risposta 400 elenca insieme tutti gli errori di forma. L\'esistenza di category si verifica dopo: ' +
    'una categoria ben formata ma sconosciuta produce un 400 a parte, con l\'elenco dei valori ammessi ' +
    '(allowed).',
  'I dettagli (/{id}) e /categories non accettano parametri: qualunque parametro dà 400 unknown-parameter ' +
    `e una query oltre ${LUNGHEZZA_MASSIMA_QUERY} caratteri un solo errore "(query)" invalid-parameter, come ` +
    'negli elenchi. Indice (/api/v1), openapi.json e feed ignorano la query.',
];

export const PARAGRAFI_REGIONI: readonly string[] = [
  'region ha un\'unica semantica: "l\'array regions dell\'elemento contiene la regione". national=true ' +
    'seleziona gli elementi di portata nazionale (per gli interpelli national è sempre false).',
  'Attenzione: le selezioni con sede "Nazionale" non escono con region, mentre i bandi nazionali o ' +
    'europei collegati a tutte le 20 regioni escono con ogni regione. Per avere tutto ciò che riguarda ' +
    'una regione: una richiesta con region=X, una seconda con national=true, poi deduplicare.',
];

// ---------------------------------------------------------------------------
// Testo, URL, stato
// ---------------------------------------------------------------------------

export const PARAGRAFI_TESTO: readonly string[] = [
  'Tutti i testi sono testo semplice UTF-8, senza HTML, markdown o entità. Titolo, title_summary ed excerpt ' +
    'degli articoli sono anch\'essi ripuliti dal markdown.',
  'summary degli articoli è testo semplice ripulito dal markdown: le intestazioni di servizio del generatore ' +
    '("Paragrafo 1", "Primo paragrafo (200 parole)", …) sono rimosse e i titoli sono chiusi da un punto. È ' +
    `troncata a circa ${LUNGHEZZA_SINTESI} caratteri, a fine frase quando possibile, altrimenti con "…". Il ` +
    'testo integrale non è mai esposto.',
  'Gli URL di siti esterni presenti nei testi sono ridotti al solo nome host (per esempio inpa.gov.it, ' +
    'senza schema né percorso); un campo composto solo da un URL diventa null. Email e domini citati senza ' +
    'schema restano come menzioni.',
  'Il campo url è sempre la pagina canonica su edunews24.it. Le immagini possono essere ospitate da terzi: ' +
    'l\'URL non costituisce una licenza d\'uso.',
  `L'autore di un articolo è il nome pubblico del giornalista oppure "${AUTORE_REDAZIONE}".`,
];

export const PARAGRAFO_STATUS =
  'status (open, closed, upcoming) usa deadline_on, confrontato con la data dell\'header Date della risposta ' +
  'nel calendario di Roma: il giorno della scadenza la scheda è ancora open, dal giorno dopo è closed. Per i ' +
  'bandi, finché la scadenza non è passata, vale lo stato indicato dalla fonte (anche upcoming); per gli ' +
  'interpelli status è sempre null. Per la selezione del personale deadline_on è il giorno UTC di ' +
  'data_scadenza (vedi le avvertenze sulle date). Una copia in cache può restare indietro di qualche minuto ' +
  'dopo la mezzanotte. Per il proprio archivio conviene ricalcolare lo stato da deadline_on. Una scadenza ' +
  'della fonte che supera di oltre 8 anni published_at è considerata implausibile: deadline_on e ' +
  'deadline_at sono null. Per la selezione del personale status è allora open; per i bandi resta quello ' +
  'indicato dalla fonte. Quando deadline_on è null lo stato non si può ricalcolare: usare status così com\'è.';

// ---------------------------------------------------------------------------
// Cache, limiti, CORS
// ---------------------------------------------------------------------------

export const PARAGRAFI_CACHE: readonly string[] = [
  'Ogni 200 ha un ETag debole (W/"…"). Rimandandolo in If-None-Match, se nulla è cambiato la risposta ' +
    'è 304 senza corpo e con gli stessi header. Last-Modified non è inviato.',
  'Rispettare Cache-Control: interrogare più spesso di max-age non porta dati più freschi. Una risposta ' +
    'con X-EduNews24-Cache: STALE è una copia servita durante un guasto del database.',
];

/** Tabella Cache-Control per tipo di risposta (piano, sezione 7). */
export const PROFILI_CACHE: readonly (readonly [string, string])[] = [
  ['elenchi', 'public, max-age=60, s-maxage=300, stale-while-revalidate=300, stale-if-error=86400'],
  ['dettagli', 'public, max-age=300, s-maxage=900, stale-while-revalidate=900, stale-if-error=86400'],
  ['feed', 'public, max-age=300, s-maxage=600, stale-while-revalidate=600, stale-if-error=86400'],
  ['categorie, indice', 'public, max-age=900, s-maxage=3600, stale-while-revalidate=3600, stale-if-error=86400'],
  ['openapi.json', 'public, max-age=3600, s-maxage=86400'],
  ['304', 'come il 200'],
  ['200 stantio dopo un errore del database', 'public, max-age=30, s-maxage=60 + X-EduNews24-Cache: STALE'],
  ['400, 404', 'public, max-age=60, s-maxage=60'],
  ['405, 429, 500, 503', 'no-store'],
  ['OPTIONS 204', 'public, max-age=86400 + Access-Control-Max-Age: 86400'],
];

export const PARAGRAFI_LIMITI: readonly string[] = [
  `${RATE_LIMIT_CAPACITA} richieste al minuto per indirizzo IPv4 o per blocco IPv6 /64: fino a ` +
    `${RATE_LIMIT_CAPACITA} richieste di fila, poi ${RATE_LIMIT_RICARICA} al secondo. Ogni metodo tranne ` +
    'OPTIONS consuma il limite, anche HEAD e le risposte servite dalla cache.',
  'Ogni risposta ha RateLimit-Policy nella forma <capacità>;w=<capacità/ricarica> (con i valori ' +
    `predefiniti ${RATE_LIMIT_POLICY}). Il 429 aggiunge Retry-After (secondi per avere di nuovo una ` +
    'richiesta), RateLimit-Limit, RateLimit-Remaining e RateLimit-Reset (secondi per tornare alla capacità ' +
    'piena): attendere Retry-After secondi prima di riprovare.',
  'Se il servizio è saturo o il database non risponde, la risposta è 503 service-unavailable con ' +
    'Retry-After. Riprovare con backoff esponenziale.',
  'Identificarsi con un User-Agent che contenga un contatto (URL o email), per esempio ' +
    `"${USER_AGENT_ESEMPIO}".`,
];

/** Risposte che possono arrivare prima dell'applicazione e non seguono il contratto. */
export const RISPOSTE_FUORI_CONTRATTO: readonly string[] = [
  '429 generati da nginx: corpo JSON ridotto (type, title, status, code, retry_after) con Retry-After: 1.',
  '403 e 503 generati da nginx, con corpo non garantito.',
  '429 dell\'edge Cloudflare (errore 1015): pagina HTML, senza header CORS.',
  '400 text/plain se gli header di inoltro della richiesta (X-Forwarded-Host, X-Forwarded-Proto, ' +
    'X-Forwarded-Port) sono malformati.',
  '500 con corpo testuale "Internal Server Error", senza Content-Type, Cache-Control né header CORS, ' +
    'generato dal server prima dell\'API se X-Forwarded-Host (o Host) non forma un URL valido, per esempio ' +
    '[1.2.3.4] o una porta oltre 65535.',
];

export const PARAGRAFO_FUORI_CONTRATTO =
  'Un client robusto tratta ogni 429 e 503 con backoff, legge Retry-After quando c\'è e non presume che ' +
  'il corpo di un errore sia sempre JSON.';

export const PARAGRAFI_CORS: readonly string[] = [
  'Tutte le risposte hanno Access-Control-Allow-Origin: * e Cross-Origin-Resource-Policy: cross-origin; ' +
    'mai Access-Control-Allow-Credentials. Sono esposti gli header ETag, Link, Retry-After, ' +
    'RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset e RateLimit-Policy. X-EduNews24-Cache non è ' +
    'esposto via CORS: da una pagina web non è leggibile.',
  'OPTIONS risponde 204 con Access-Control-Allow-Methods: GET, HEAD, OPTIONS, Access-Control-Allow-Headers: ' +
    'Accept, If-None-Match, Cache-Control e Access-Control-Max-Age: 86400. Dal browser non impostare ' +
    'User-Agent né altri header non elencati: il preflight fallirebbe.',
];

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export const PARAGRAFI_FEED: readonly string[] = [
  `Ogni risorsa ha un feed con gli ultimi ${ELEMENTI_FEED} elementi, in JSON Feed 1.1 (.json, ` +
    'application/feed+json) e in RSS 2.0 (.xml, application/rss+xml). Gli articoli hanno anche un feed per ' +
    'categoria. I feed non hanno cursore e ignorano la query string.',
  'Ogni voce contiene la sintesi e l\'attribuzione obbligatoria con il link alla pagina completa; per le ' +
    'schede con scadenza anche la riga "Scadenza". L\'id della voce è tag:edunews24.it,2026:<type>/<id>. ' +
    'I membri opzionali vuoti sono omessi; content_html non è mai presente.',
  'Ordine: articoli e interpelli per data di pubblicazione; bandi per data di inserimento; selezione del ' +
    'personale per ultimo aggiornamento, con le schede scadute escluse.',
  'Estensione _edunews24 del JSON Feed: a livello di feed {api, terms, content_signal}; per una voce ' +
    'articolo {type: "article", category}; per una voce di sezione {type, status, deadline_on}, con i null ' +
    'conservati.',
  'In RSS l\'id della voce è in guid (isPermaLink="false"), l\'autore in dc:creator, l\'immagine in ' +
    'media:thumbnail e il video in media:content; categoria, tag, sezione e regioni sono elementi category.',
];

// ---------------------------------------------------------------------------
// Evoluzione
// ---------------------------------------------------------------------------

export const PARAGRAFI_EVOLUZIONE: readonly string[] = [
  'La v1 evolve solo in modo additivo: nuovi campi, nuovi parametri, nuovi valori di enum (per esempio di ' +
    'status o type). I client devono ignorare i campi sconosciuti e tollerare valori nuovi.',
  'Le modifiche incompatibili arriveranno in /api/v2, con almeno 6 mesi di coesistenza e gli header ' +
    'Deprecation e Sunset sulla v1.',
];

// ---------------------------------------------------------------------------
// Errori
// ---------------------------------------------------------------------------

export const PARAGRAFI_ERRORI: readonly string[] = [
  'Gli errori sono application/problem+json (RFC 9457): type (URL della sezione di questa pagina), title, ' +
    'status, detail, instance (URL del solo path, senza query) e code. I 400 sui parametri aggiungono ' +
    'errors[] con parameter, detail e, per gli elenchi chiusi, allowed; 429 e 503 aggiungono retry_after.',
  'detail non riporta mai i valori ricevuti né messaggi interni.',
];

export interface TestoErrore {
  quando: string;
  cosaFare: string;
  cacheControl: string;
}

export const TESTI_ERRORE: ReadonlyMap<CodiceErrore, TestoErrore> = new Map<CodiceErrore, TestoErrore>([
  ['invalid-parameter', {
    quando: 'Un parametro ha un formato o un valore non ammesso, compare più volte o è vuoto; since non ' +
      'precede until; l\'id nel path non è un intero positivo; un valore è troppo lungo; la query supera ' +
      `${LUNGHEZZA_MASSIMA_QUERY} caratteri (un solo errore, parameter "(query)", anche su dettagli e ` +
      '/categories). Gli errori di forma arrivano tutti insieme; una categoria ben formata ma sconosciuta dà ' +
      'dopo un 400 a parte, con allowed.',
    cosaFare: 'Correggere la richiesta seguendo errors[]: ripeterla uguale darà lo stesso errore.',
    cacheControl: 'public, max-age=60, s-maxage=60',
  }],
  ['unknown-parameter', {
    quando: 'La query contiene un parametro non previsto per la risorsa. I dettagli (/{id}) e /categories ' +
      'non ne accettano nessuno; indice, openapi.json e feed ignorano la query. Negli elenchi ' +
      'errors[].allowed elenca i parametri ammessi; se ci sono anche valori non validi, errors[] riporta ' +
      'pure quelli.',
    cosaFare: 'Togliere il parametro: i parametri sconosciuti non vengono mai ignorati in silenzio.',
    cacheControl: 'public, max-age=60, s-maxage=60',
  }],
  ['invalid-cursor', {
    quando: 'Il cursore non è stato emesso da questa API per la stessa risorsa e gli stessi filtri: ' +
      'troncato, manomesso, di un\'altra risorsa, filtri cambiati o versione non più supportata.',
    cosaFare: 'Ripartire dalla prima pagina, senza cursor, con gli stessi filtri.',
    cacheControl: 'public, max-age=60, s-maxage=60',
  }],
  ['not-found', {
    quando: 'Path sconosciuto, id inesistente o non più pubblicato, feed o categoria inesistente.',
    cosaFare: 'Per un elemento già sincronizzato: rimuoverlo dalla propria copia.',
    cacheControl: 'public, max-age=60, s-maxage=60',
  }],
  ['method-not-allowed', {
    quando: 'Metodo diverso da GET, HEAD e OPTIONS. L\'header Allow elenca quelli ammessi.',
    cosaFare: 'Usare GET: l\'API è in sola lettura.',
    cacheControl: 'no-store',
  }],
  ['rate-limited', {
    quando: `Superato il limite di ${RATE_LIMIT_CAPACITA} richieste al minuto per indirizzo.`,
    cosaFare: 'Attendere i secondi indicati da Retry-After (e da retry_after nel corpo) prima di riprovare.',
    cacheControl: 'no-store',
  }],
  ['internal-error', {
    quando: 'Errore imprevisto del server.',
    cosaFare: 'Riprovare più tardi con backoff; se l\'errore persiste, segnalarlo alla redazione.',
    cacheControl: 'no-store',
  }],
  ['service-unavailable', {
    quando: 'Database non raggiungibile o troppo lento senza una copia di riserva, oppure servizio saturo.',
    cosaFare: 'Riprovare dopo Retry-After secondi, con backoff esponenziale.',
    cacheControl: 'no-store',
  }],
]);

// ---------------------------------------------------------------------------
// Termini (nota provvisoria) e changelog
// ---------------------------------------------------------------------------

export const NOTA_TERMINI_INTRODUZIONE =
  `Nota provvisoria del ${DATA_RILASCIO_ESTESA}. I termini d'uso definitivi dell'API sono in preparazione ` +
  'e verranno pubblicati in questa sezione. Fino ad allora l\'uso è consentito a queste condizioni:';

export const NOTA_TERMINI_VOCI: readonly string[] = [
  `attribuzione "${TESTO_ATTRIBUZIONE}" con un link visibile e diretto all'url canonico dell'elemento su ` +
    'edunews24.it;',
  'niente testo integrale: l\'API fornisce solo sintesi e metadati, e il testo completo non va ricostruito ' +
    'né riprodotto con altri mezzi;',
  'rispetto dei limiti di frequenza, di Cache-Control e di Retry-After;',
  `l'uso come input per sistemi di intelligenza artificiale e per l'addestramento di modelli non è ` +
    `consentito, come dichiarato dall'header Content-Signal (${CONTENT_SIGNAL});`,
  'i termini definitivi sostituiranno questa nota: le condizioni possono cambiare e l\'accesso può essere ' +
    'revocato in caso di abuso.',
];

export const NOTA_TERMINI_CHIUSURA =
  'Per usi diversi da quelli descritti scrivere alla redazione dalla pagina ' + SITO + '/contattaci.';

export interface VoceChangelog {
  versione: string;
  data: string;
  note: readonly string[];
}

export const CHANGELOG: readonly VoceChangelog[] = [
  {
    versione: VERSIONE_API,
    data: DATA_RILASCIO,
    note: [
      'Prima versione pubblica: articoli, categorie, interpelli, selezione del personale e bandi.',
      'Paginazione a cursore, filtri, ETag e limiti di frequenza.',
      'Feed JSON Feed 1.1 e RSS 2.0 per ogni risorsa e per ogni categoria di articoli.',
    ],
  },
];

// ---------------------------------------------------------------------------
// Descrizione del documento OpenAPI (CommonMark)
// ---------------------------------------------------------------------------

function paragrafi(testi: readonly string[]): string {
  return testi.join('\n\n');
}

function elencoPuntato(voci: readonly string[]): string {
  return voci.map((v) => `- ${v}`).join('\n');
}

/** Descrizione generale per info.description: tutte le avvertenze del contratto. */
export function descrizioneOpenApi(): string {
  return [
    paragrafi(PARAGRAFI_INTRODUZIONE),
    '## Formato\n\n' + paragrafi(PARAGRAFI_FORMATO),
    '## Date\n\n' + paragrafi(PARAGRAFI_DATE),
    '## Paginazione\n\n' + paragrafi(PARAGRAFI_PAGINAZIONE),
    '## Sincronizzazione\n\n' + elencoPuntato(GUIDA_SINCRONIZZAZIONE.map((p) => `**${p.risorse}**: ${p.testo}`)) +
      '\n\n' + PARAGRAFO_DEDUPLICA,
    '## Parametri\n\n' + paragrafi(PARAGRAFI_REGOLE_FILTRI),
    '## Filtri region e national\n\n' + paragrafi(PARAGRAFI_REGIONI),
    '## Testo e URL\n\n' + paragrafi(PARAGRAFI_TESTO) + '\n\n' + PARAGRAFO_STATUS,
    '## Cache\n\n' + paragrafi(PARAGRAFI_CACHE),
    '## Limiti\n\n' + paragrafi(PARAGRAFI_LIMITI),
    '## CORS\n\n' + paragrafi(PARAGRAFI_CORS),
    '## Risposte fuori contratto\n\n' + elencoPuntato(RISPOSTE_FUORI_CONTRATTO) + '\n\n' + PARAGRAFO_FUORI_CONTRATTO,
    '## Evoluzione\n\n' + paragrafi(PARAGRAFI_EVOLUZIONE),
    `## Termini\n\n${NOTA_TERMINI_INTRODUZIONE}\n\n${elencoPuntato(NOTA_TERMINI_VOCI)}\n\nDocumentazione completa: ` +
      `${URL_DOCUMENTAZIONE}. Termini: ${URL_TERMINI}.`,
  ].join('\n\n');
}

// ---------------------------------------------------------------------------
// Esempi (testi illustrativi, forma reale). Funzioni: ogni chiamata restituisce
// oggetti nuovi, nessuno stato condiviso fra i chiamanti.
// ---------------------------------------------------------------------------

/** Cursore dell'esempio del piano (sezione 3.7). */
export const CURSORE_ESEMPIO =
  'eyJ2IjoxLCJyIjoiYXJ0aWNsZXMiLCJmIjoiM2E5YzFlMjAiLCJrIjpbIjIwMjYtMDktMjFUMDc6MTg6MjguMTc3IiwzOTM4Ml19';

export function esempioArticolo(): ArticoloDto {
  return {
    type: 'article',
    id: 39382,
    slug: 'supplenze-2026-27-convocazioni-da-gps',
    url: `${SITO}/scuola/supplenze-2026-27-convocazioni-da-gps`,
    title: 'Supplenze 2026/27, al via le convocazioni da GPS: cosa sapere',
    title_summary: 'Supplenze 2026/27: le convocazioni da GPS',
    excerpt: 'Gli uffici scolastici avviano le convocazioni per le supplenze annuali: tempi, documenti e cosa ' +
      'succede in caso di rinuncia.',
    summary: 'Gli uffici scolastici provinciali hanno avviato le convocazioni per le supplenze annuali. I ' +
      'candidati inseriti nelle GPS riceveranno la proposta tramite la piattaforma ministeriale.',
    category: { slug: 'scuola', name: 'Scuola', color: '#2D6A4F', url: `${SITO}/scuola` },
    secondary_categories: [{ slug: 'insegnanti', name: 'Insegnanti' }],
    image_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/audios/supplenze-2026-27.webp',
    thumbnail_url: null,
    video: null,
    published_at: '2026-09-21T09:18:28+02:00',
    tags: ['supplenze', 'gps', 'docenti precari'],
    author: { name: AUTORE_REDAZIONE },
  };
}

export function esempioVideo(): VideoDto {
  return {
    url: 'https://audios234567.s3.eu-north-1.amazonaws.com/video/supplenze-2026-27.mp4',
    mime_type: 'video/mp4',
    thumbnail_url: 'https://audios234567.s3.eu-north-1.amazonaws.com/video/supplenze-2026-27-thumb.webp',
    duration_seconds: 72,
  };
}

export function esempioSelezione(): SelezioneDto {
  const slug = 'arpam-marche-avviso-pubblico-per-colloquio-collaboratore-tecnico-professionale-29611';
  return {
    type: 'selezione-personale',
    id: 23258,
    slug,
    url: `${SITO}/selezione-personale/${slug}`,
    title: 'ARPAM Marche, avviso pubblico per Collaboratore Tecnico Professionale',
    summary: 'L\'Agenzia Regionale per la Protezione dell\'Ambiente delle Marche apre le candidature per una ' +
      'graduatoria a tempo determinato. Domande entro il 6 ottobre 2026.',
    section: sezioneDto('selezione-personale'),
    published_at: '2026-09-21T00:01:00+02:00',
    updated_at: '2026-09-21T08:04:01+02:00',
    deadline_on: '2026-10-06',
    deadline_at: '2026-10-06T23:59:00+02:00',
    status: 'open',
    regions: [{ slug: 'marche', name: 'Marche' }],
    national: false,
    details: {
      official_title: 'AVVISO PUBBLICO, PER COLLOQUIO, PER COLLABORATORE TECNICO PROFESSIONALE',
      code: '29611',
      position: 'Collaboratore Tecnico Professionale',
      positions_count: 1,
      procedure_type: 'COLLOQUIO',
      categories: ['Concorso'],
      sectors: [],
      organizations: ['Agenzia Regionale per la Protezione dell\'Ambiente delle Marche'],
      locations: ['Marche', 'Ancona', 'Macerata'],
      salary_min: null,
      salary_max: null,
    },
  };
}

export function esempioInterpello(): InterpelloDto {
  const slug = slugInterpello({
    id: 1523,
    interpello_name: 'IC Mazzini',
    interpello_provincia: 'Roma',
    interpello_regione: 'Lazio',
  });
  return {
    type: 'interpello',
    id: 1523,
    slug,
    url: `${SITO}/interpelli/${slug}`,
    title: 'Interpello per una supplenza su A022 all\'IC Mazzini di Roma',
    summary: 'L\'istituto cerca un docente di italiano, storia e geografia per una supplenza fino al ' +
      'termine delle attività didattiche.',
    section: sezioneDto('interpelli'),
    published_at: '2026-09-18T00:00:00+02:00',
    updated_at: null,
    deadline_on: null,
    deadline_at: null,
    status: null,
    regions: [{ slug: 'lazio', name: 'Lazio' }],
    national: false,
    details: {
      official_title: 'IC Mazzini',
      competition_class: 'A022',
      province: 'Roma',
      city: 'Roma',
    },
  };
}

export function esempioBando(): BandoDto {
  const slug = 'voucher-digitalizzazione-pmi-marche-2026';
  return {
    type: 'bando',
    id: 4821,
    slug,
    url: `${SITO}/bandi/${slug}`,
    title: 'Voucher per la digitalizzazione delle PMI marchigiane 2026',
    summary: 'Contributi a fondo perduto per progetti di digitalizzazione delle micro, piccole e medie ' +
      'imprese con sede nelle Marche.',
    section: sezioneDto('bandi'),
    published_at: '2026-09-15T10:42:07+02:00',
    updated_at: '2026-09-20T03:12:55+02:00',
    deadline_on: '2026-11-30',
    deadline_at: null,
    status: 'open',
    regions: [{ slug: 'marche', name: 'Marche' }],
    national: false,
    details: {
      short_title: 'Voucher digitalizzazione PMI',
      issuer: 'Regione Marche',
      geographic_area: 'Marche',
      topics: ['Digitalizzazione', 'Innovazione'],
      kind: 'Contributo',
      program: 'PR FESR Marche 2021-2027',
      funding_method: 'Fondo perduto',
      sectors: ['Commercio', 'Servizi'],
      beneficiaries: ['PMI'],
      ateco_codes: [{ code: '62.01', description: 'Produzione di software non connesso all\'edizione' }],
      total_amount_eur: 2000000,
      max_amount_per_project_eur: 50000,
      opens_on: '2026-09-01',
      source_published_on: '2026-09-12',
    },
  };
}

export function esempioCategoria(): CategoriaDto {
  return {
    slug: 'scuola',
    name: 'Scuola',
    color: '#2D6A4F',
    position: 1,
    url: `${SITO}/scuola`,
    secondary_categories: [{ slug: 'insegnanti', name: 'Insegnanti' }],
    links: {
      articles: `${BASE_API}/articles?category=scuola`,
      feed_json: `${BASE_API}/feeds/articles/scuola.json`,
      feed_rss: `${BASE_API}/feeds/articles/scuola.xml`,
    },
  };
}

/** Corpo di un problem+json come lo descrive lo schema Problema. */
export interface CorpoProblemaEsempio {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  code: CodiceErrore;
  errors?: { parameter: string; detail: string; allowed?: string[] }[];
  retry_after?: number;
}

/**
 * Richiesta (path relativo a BASE_API) che produce esattamente esempioErroreParametri():
 * lo verificano i test di contratto.
 */
export const RICHIESTA_ERRORE_PARAMETRI = '/articles?limit=0&category=Pippo';

export function esempioErroreParametri(): CorpoProblemaEsempio {
  return {
    type: `${URL_DOCUMENTAZIONE}#error-invalid-parameter`,
    title: 'Parametro non valido',
    status: 400,
    detail: 'La richiesta contiene 2 parametri non validi.',
    instance: `${BASE_API}/articles`,
    code: 'invalid-parameter',
    errors: [
      { parameter: 'limit', detail: `Deve essere un intero tra 1 e ${LIMITE_MASSIMO}.` },
      { parameter: 'category', detail: 'Deve essere lo slug di una categoria (vedi /api/v1/categories).' },
    ],
  };
}

/** Il 429 alla prima richiesta oltre il limite (secchio vuoto, ricarica di 1 al secondo). */
export function esempioErroreLimite(): CorpoProblemaEsempio {
  return {
    type: `${URL_DOCUMENTAZIONE}#error-rate-limited`,
    title: 'Troppe richieste',
    status: 429,
    detail: 'Troppe richieste da questo indirizzo. Riprova tra 1 secondo.',
    instance: `${BASE_API}/bandi`,
    code: 'rate-limited',
    retry_after: 1,
  };
}
