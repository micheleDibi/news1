/**
 * Denylist degli aggregatori: i domini che non devono mai comparire come link
 * in una superficie pubblica (scheda, card, JSON-LD, Markdown per agenti, API).
 *
 * È la proiezione in TypeScript delle righe `tipo='aggregatore'` della tabella
 * interna `dominio_ufficiale`, seminate da
 * `backend/sql/bando_v11_seed_dominio_ufficiale.sql`. La tabella non è leggibile
 * con la anon key (e non deve esserlo: contiene anche gli host «dedotti»),
 * quindi il frontend non può interrogarla: la copia qui è l'unica via.
 * `tests/estrazioni/domini-bando.test.ts` legge il seed SQL e confronta i due
 * elenchi, così una divergenza non passa inosservata.
 *
 * Perché un modulo TypeScript e non un JSON: `tsconfig.json` non ha
 * `resolveJsonModule` (TS2732) e sotto `node --test` un import di JSON
 * richiederebbe `with { type: 'json' }`.
 *
 * Il confronto è per suffisso di etichetta: `obiettivoeuropa.com` copre anche
 * `www.obiettivoeuropa.com` e `api.obiettivoeuropa.com`, mai
 * `nonobiettivoeuropa.com` (vedi `eAggregatore` in `src/lib/bandi/domini.ts`).
 */
export const DOMINI_AGGREGATORI = [
  // Aggregatori di bandi: ripubblicano i bandi altrui, non sono mai la fonte.
  'obiettivoeuropa.com',
  'fasi.eu',
  'europafacile.net',
  'contributiregione.it',
  'finanziamentinews.it',
  'bandi.it',
  'infobandi.it',
  'ticonsiglio.com',
  'contributieuropa.com',
  'first.aster.it',
  // Social, video e messaggistica: un post o un video non sono l'atto.
  'facebook.com',
  'instagram.com',
  'x.com',
  'twitter.com',
  'linkedin.com',
  'threads.net',
  'pinterest.com',
  'tiktok.com',
  'youtube.com',
  'youtu.be',
  'vimeo.com',
  't.me',
  'telegram.me',
  'wa.me',
  'whatsapp.com',
] as const;

export type DominioAggregatore = typeof DOMINI_AGGREGATORI[number];
