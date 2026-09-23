/**
 * `src/lib/bandi/pubblicazione.ts` e la guardia della fonte unica di lettura.
 *
 * Era un inventario delle copie del predicato, che doveva svuotarsi da solo;
 * ora è vuoto, e la seconda metà del file serve a tenerlo tale: sotto `src/`
 * il nome della tabella dei bandi e la condizione di pubblicazione possono
 * comparire solo nei due file autorizzati.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import {
  FONTE_BANDI_PREDEFINITA, FONTI_BANDI, FONTI_NON_PRONTE, fonteBandiDa,
  fontePerNome, nomeFonteBandiDa,
} from '../../src/lib/bandi/pubblicazione.ts';

test('la fonte `bando` porta il predicato, la vista non ne ha bisogno', () => {
  assert.equal(FONTI_BANDI.bando.tabella, 'bando');
  assert.deepEqual(FONTI_BANDI.bando.operazioni, [
    ['stato_processing', 'eq', 'completed'],
    ['slug', 'not.is', 'null'],
  ]);
  // La vista ha il predicato dentro (`WHERE pubblicato`): ripeterlo darebbe
  // 42703, perché `stato_processing` non è fra le sue colonne.
  assert.equal(FONTI_BANDI.bando_pubblico.tabella, 'bando_pubblico');
  assert.deepEqual(FONTI_BANDI.bando_pubblico.operazioni, []);
});

test('fonteBandiDa: default `bando`, nessun ripiego automatico', () => {
  assert.equal(FONTE_BANDI_PREDEFINITA, 'bando');
  assert.equal(fonteBandiDa(undefined).tabella, 'bando');
  assert.equal(fonteBandiDa(null).tabella, 'bando');
  assert.equal(fonteBandiDa('bando').tabella, 'bando');
  // Un valore ignoto non «prova» la vista: torna la tabella, che esiste sempre.
  assert.equal(fonteBandiDa('bando_pubblico_v2').tabella, 'bando');
  assert.equal(fonteBandiDa('toString').tabella, 'bando');
  assert.equal(nomeFonteBandiDa('altro'), 'bando');
  assert.equal(nomeFonteBandiDa(undefined), 'bando');
  assert.equal(nomeFonteBandiDa(null), 'bando');
});

test('`bando_pubblico` è servibile: il flag la seleziona davvero', () => {
  // Rovesciato da F2 (23/09/2026). Prima la vista restava disarmata perché
  // quattro select chiedevano `updated_at`, che sulla vista non esiste:
  // PostgREST risponde 42703 e manda in 500, nello stesso istante, la scheda
  // di ogni bando, entrambe le sitemap e /api/v1/bandi. Ora quelle select
  // passano da `selectFreschezza` e la guardia è vuota.
  assert.deepEqual(FONTI_NON_PRONTE, {}, 'nessuna fonte deve restare disarmata');
  assert.equal(fonteBandiDa(' bando_pubblico ').tabella, 'bando_pubblico');
  assert.equal(nomeFonteBandiDa('bando_pubblico'), 'bando_pubblico');
  assert.deepEqual(fontePerNome('bando_pubblico').operazioni, [],
    'sulla vista il predicato è dentro: ripeterlo darebbe 42703');
});

test('la colonna della freschezza ha un nome per fonte, e due forme per uso', () => {
  // Due campi perché servono in due posti che vogliono forme diverse: nella
  // `select` ci va l'alias, nei filtri e negli `order` il nome nudo. Un alias
  // dentro un `filter` non è ammesso, e confonderli darebbe 42703 proprio sul
  // filtro `updated_since` dell'API.
  const tabella = fontePerNome('bando');
  const vista = fontePerNome('bando_pubblico');

  assert.equal(tabella.colonnaFreschezza, 'updated_at');
  assert.equal(tabella.selectFreschezza, 'updated_at');

  assert.equal(vista.colonnaFreschezza, 'ultimo_cambiamento_at');
  assert.equal(vista.selectFreschezza, 'updated_at:ultimo_cambiamento_at',
    'sulla vista serve l\'alias: i consumatori leggono un campo `updated_at`');

  // La forma dell'alias è `nome_atteso:colonna_vera`, e la parte prima dei due
  // punti deve coincidere con il nome che la tabella usa: è ciò che permette a
  // sitemap, scheda e API di non cambiare una riga quando la fonte cambia.
  assert.equal(vista.selectFreschezza.split(':')[0], tabella.colonnaFreschezza);
  assert.equal(vista.selectFreschezza.split(':')[1], vista.colonnaFreschezza);
});

test('override svuotato: la stringa vuota vale `bando` da entrambi i lati', () => {
  // Il caso di chi «toglie l'override» lasciando `BANDI_FONTE_LETTURA=` in .env
  // o nell'unit systemd. Le due funzioni devono rispondere allo stesso modo:
  // una che salta il vuoto e ricade sul valore compilato manderebbe metà delle
  // superfici sulla vista e metà sulla tabella.
  for (const vuoto of ['', ' ', '   ', '\t']) {
    assert.equal(fonteBandiDa(vuoto).tabella, 'bando', JSON.stringify(vuoto));
    assert.deepEqual(fonteBandiDa(vuoto).operazioni, FONTI_BANDI.bando.operazioni);
    assert.equal(nomeFonteBandiDa(vuoto), 'bando', JSON.stringify(vuoto));
  }
});

/** Sorgente senza commenti: le spiegazioni possono nominare il predicato. */
function sorgente(url: URL): string {
  return readFileSync(url, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

/**
 * Tutte le superfici di `src/`, percorso relativo a `src/`.
 *
 * Non solo `.ts`/`.astro`: l'area admin e' in `.tsx`, e un `.js`/`.mjs` sotto
 * `src/` sarebbe scandito da Vite come tutto il resto. Oggi nessuno di questi
 * file tocca i bandi, ed e' proprio per questo che l'elenco va tenuto largo:
 * la guardia serve a chi arrivera' dopo.
 */
function fileDiSrc(): string[] {
  const radice = new URL('../../src/', import.meta.url);
  const trovati: string[] = [];
  const visita = (cartella: URL, prefisso: string): void => {
    for (const voce of readdirSync(cartella, { withFileTypes: true })) {
      const relativo = prefisso === '' ? voce.name : `${prefisso}/${voce.name}`;
      if (voce.isDirectory()) visita(new URL(`${voce.name}/`, cartella), relativo);
      else if (/\.(ts|tsx|astro|mjs|cjs|js|jsx)$/.test(voce.name)) trovati.push(relativo);
    }
  };
  visita(radice, '');
  return trovati.sort();
}

/**
 * La guardia della fonte unica.
 *
 * Non e' piu' un inventario che si svuota: e' l'elenco chiuso dei file
 * autorizzati a sapere come si chiama la tabella dei bandi e che cosa vuol dire
 * «pubblicato». Tutti gli altri — liste, corpus, scheda, pagine filtro, sitemap,
 * API — devono passare da `FONTI_BANDI`, altrimenti il giorno in cui
 * `BANDI_FONTE_LETTURA=bando_pubblico` accende la vista una superficie resta
 * indietro: continua a leggere da `bando` righe che la vista toglie (doppioni
 * fusi, ritirati), e i conteggi del corpus non corrispondono piu' a quello che
 * la pagina mostra. Sulla sitemap il danno e' peggiore, perche' resta scritto
 * in un file che Google rilegge.
 *
 * Il test vieta le tre forme in cui la conoscenza si ricopia: il nome della
 * tabella in `.from()`, la colonna `stato_processing` e la seconda meta' del
 * predicato (`slug IS NOT NULL`). Aggiungere un file agli `AUTORIZZATI` e' una
 * decisione, non un incidente: il predicato e' in AND con la RLS e con i punti
 * di contatto di BandoFit.
 */
const AUTORIZZATI = new Set([
  // La sede del predicato (modulo puro, nessun import).
  'lib/bandi/pubblicazione.ts',
  // Il modulo impuro che legge il flag e pubblica FONTE_BANDI; `stato_processing`
  // vi compare come dichiarazione di tipo di una colonna, non come condizione.
  'lib/supabase-bandi.ts',
  // `lib/api-v1/fonte-supabase.ts` NON e' qui, benche' sia l'unico esecutore
  // delle query dell'API: prende tabella e operazioni dal piano di filtri.ts e
  // non ne scrive nessuna, quindi non ha motivo di nominare la tabella. Un
  // permesso preventivo sarebbe l'unico punto del perimetro in cui la
  // ricopiatura passerebbe in silenzio: purezza.test.ts gli vieta i filtri
  // scritti a mano, non il nome della tabella.
]);

const RICOPIATURE: ReadonlyArray<readonly [string, RegExp]> = [
  ['nome della tabella cablato', /\.from\(\s*['"]bando(_pubblico)?['"]\s*\)/],
  ['colonna `stato_processing`', /stato_processing/],
  ['meta\' predicato: `slug IS NOT NULL`', /\.not\(\s*['"]slug['"]\s*,\s*['"]is['"]/],
];

test('fonte unica: tabella e predicato solo nei file autorizzati', () => {
  const radice = new URL('../../src/', import.meta.url);
  for (const [motivo, schema] of RICOPIATURE) {
    const fuori = fileDiSrc().filter((relativo) =>
      !AUTORIZZATI.has(relativo) && schema.test(sorgente(new URL(relativo, radice))));
    assert.deepEqual(fuori, [], `${motivo}: usare FONTI_BANDI/FONTE_BANDI`);
  }
});

test('la guardia vede davvero le ricopiature (controllo del controllo)', () => {
  // Senza questo, un refuso nelle regex trasformerebbe il test sopra in un
  // «passa sempre» e nessuno se ne accorgerebbe.
  const esempi = [
    "let q = supabaseBandi.from('bando').select('id');",
    'const q = client.from("bando_pubblico").select(x);',
    "query.eq('stato_processing', 'completed')",
    "query.not('slug', 'is', null)",
  ];
  for (const esempio of esempi) {
    assert.equal(
      RICOPIATURE.some(([, schema]) => schema.test(esempio)), true, esempio);
  }
  // E non deve inciampare su chi la fonte la chiede al modulo.
  for (const innocuo of [
    'supabaseBandi.from(FONTE_BANDI.tabella).select(select)',
    "supabaseBandi.from('bando_regioni').select('regione_id')",
    "client.from(piano.tabella).select(select)",
  ]) {
    assert.equal(RICOPIATURE.some(([, schema]) => schema.test(innocuo)), false, innocuo);
  }
});
