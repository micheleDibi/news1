/**
 * Costanti dell'API pubblica /api/v1. Nessuna logica, nessun import di valori.
 */

/** Host pubblico: tutti gli URL emessi sono assoluti su questa base, mai su request.url. */
export const SITO = 'https://edunews24.it';
export const BASE_API = `${SITO}/api/v1`;
export const VERSIONE_API = '1.0';
export const VERSIONE_OPENAPI = '1.0.0';

export const URL_DOCUMENTAZIONE = `${SITO}/sviluppatori/api`;
export const URL_TERMINI = `${URL_DOCUMENTAZIONE}#termini`;
export const URL_OPENAPI = `${BASE_API}/openapi.json`;
export const URL_CATALOGO = `${SITO}/.well-known/api-catalog`;

/** Preferenze d'uso dichiarate in public/robots.txt (Content Signals). */
export const CONTENT_SIGNAL = 'search=yes, ai-train=no, ai-input=no';

export const AUTORE_REDAZIONE = 'Redazione EduNews24';
export const TESTO_ATTRIBUZIONE = 'Fonte: EduNews24';

// Paginazione e dimensioni.
export const LIMITE_PREDEFINITO = 20;
export const LIMITE_MASSIMO = 100;
export const ELEMENTI_FEED = 50;
export const LUNGHEZZA_SINTESI = 600;
export const LUNGHEZZA_MASSIMA_CURSORE = 300;
export const LUNGHEZZA_MASSIMA_VALORE = 256;
export const LUNGHEZZA_MASSIMA_QUERY = 2048;

/** Scarto massimo fra l'ora di Roma e UTC: margine dei filtri su published_at. */
export const MARGINE_FUSO_MS = 2 * 60 * 60 * 1000;

/** Oltre questo scarto dalla pubblicazione una scadenza e' considerata implausibile. */
export const SCARTO_MAX_SCADENZA_MS = 8 * 365.25 * 24 * 60 * 60 * 1000;

/**
 * Id massimo per risorsa: bando.id e' int4 nel DB bandi, le altre tabelle usano int8
 * (bastano gli interi sicuri di JavaScript). Un id oltre il tipo della colonna fa
 * rispondere PostgREST 400/22003: va fermato prima, come id inesistente.
 */
export const ID_MASSIMO_INT4 = 2_147_483_647;

// Tempi e protezione del processo.
export const TIMEOUT_QUERY_MS = 5_000;
export const BUDGET_PRODUZIONE_MS = 10_000;
export const SLOT_SEMAFORO = 8;
export const CODA_SEMAFORO = 32;
export const ATTESA_SEMAFORO_MS = 2_000;
export const TTL_RIFERIMENTI_MS = 10 * 60 * 1000;

/** Token bucket per client: capacita' e ricarica al secondo (sovrascrivibili da env). */
export const RATE_LIMIT_CAPACITA = 60;
export const RATE_LIMIT_RICARICA = 1;
export const RATE_LIMIT_MAX_CHIAVI = 100_000;
export const RATE_LIMIT_POLICY = `${RATE_LIMIT_CAPACITA};w=60`;

/**
 * Range IP di Cloudflare, da https://www.cloudflare.com/ips-v4 e /ips-v6
 * (letti il 2026-09-21). Vanno riallineati se Cloudflare li cambia: un range
 * mancante fa trattare quel traffico come client diretto (limite piu' severo,
 * mai un aggiramento).
 */
export const CIDR_CLOUDFLARE: readonly string[] = [
  '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
  '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
  '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
  '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
  '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
  '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
];
