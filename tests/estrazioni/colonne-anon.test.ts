/**
 * Le colonne che il frontend chiede ai bandi esistono sulla vista `bando_pubblico`?
 *
 * Il test previsto da §7.9 del piano. Serve a una cosa sola: `BANDI_FONTE_LETTURA`
 * si legge **a runtime**, quindi il giorno in cui qualcuno la esporta il
 * dominio bandi cambia tabella senza che niente venga ricompilato. Se anche
 * una sola colonna citata non è fra quelle della vista, PostgREST risponde
 * 42703 e fa fallire l'**intera** richiesta: la scheda di ogni bando,
 * entrambe le sitemap e `/api/v1/bandi` vanno in 500 insieme.
 *
 * Le colonne della vista si estraggono dal file SQL della migrazione 13 (la 05
 * più le cinque colonne in coda del giro 2), che è la definizione vera;
 * l'elenco non si ricopia qui, perché una copia che nessuno confronta diverge.
 * Lo stesso confronto si fa con la vista della 07 (fase d, non applicata), che
 * toglie tre colonne che la scheda chiede ancora: la differenza deve restare
 * ESATTAMENTE quella dichiarata nella testa della 07, così una colonna nuova
 * che la 07 non porta si vede qui e non come un 42703 su ogni scheda.
 *
 * Finché `FONTI_NON_PRONTE` tiene la vista disarmata questo test è una
 * fotografia del lavoro che resta: elenca le colonne da spostare. Quando F2 le
 * avrà spostate, la guardia si toglie e questo test diventa la rete che
 * impedisce di rimetterne una.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { FONTI_NON_PRONTE } from '../../src/lib/bandi/pubblicazione.ts';

const RADICE = new URL('../../', import.meta.url);
const MIGRAZIONE_13 = new URL('backend/sql/bando_v11_13_stato_da_verificare.sql', RADICE);
const MIGRAZIONE_07 = new URL('backend/sql/bando_v11_07_fase_d.sql', RADICE);

/**
 * Le colonne che la 07 toglie dalla vista e che la scheda chiede ancora
 * (`COLONNE_DETTAGLIO_COMUNI`): la precondizione bloccante scritta nella testa
 * della 07. Finché il sito non le legge da `bando_link`, la 07 non si applica.
 */
const MANCANTI_NOTE_DELLA_07 = ['allegati', 'link_candidatura', 'link_candidatura_source'];

/**
 * Le colonne in uscita da `CREATE [OR REPLACE] VIEW public.bando_pubblico ...
 * FROM public.bando b` (la 13 la sostituisce, la 07 la ricrea da zero).
 */
function colonneDellaVista(migrazione: URL = MIGRAZIONE_13): Set<string> {
  const sql = readFileSync(migrazione, 'utf8');
  const inizio = sql.search(/CREATE (?:OR REPLACE )?VIEW public\.bando_pubblico\b/);
  assert.ok(inizio >= 0, `definizione della vista non trovata in ${migrazione.pathname}`);
  const fine = sql.indexOf('FROM public.bando b', inizio);
  assert.ok(fine > inizio, 'fine della SELECT non trovata');
  const corpo = sql
    .slice(inizio, fine)
    .replace(/--[^\n]*/g, '');            // i commenti contengono altri nomi

  const nomi = new Set<string>();
  // `... AS nome,` — le colonne calcolate (`stato_effettivo`, `contenuto`, …).
  for (const m of corpo.matchAll(/\bAS\s+([a-z_][a-z0-9_]*)\s*(?:,|$)/gim)) {
    nomi.add(m[1].toLowerCase());
  }
  // `b.nome,` a fine riga — le colonne passate intatte.
  for (const m of corpo.matchAll(/^\s*b\.([a-z_][a-z0-9_]*)\s*,?\s*$/gim)) {
    nomi.add(m[1].toLowerCase());
  }
  return nomi;
}

/**
 * Le colonne di una select PostgREST. Si divide sulle virgole fuori dalle
 * parentesi; un embed (`tipologia:tipologie_bando(nome)`) è un'altra tabella e
 * resta fuori, un alias (`updated_at:ultimo_cambiamento_at`) vale la colonna
 * dopo i due punti, un percorso JSON (`raw_data->x`) vale la colonna.
 */
function colonneDiSelect(select: string): string[] {
  const pezzi: string[] = [];
  let profondita = 0;
  let corrente = '';
  for (const carattere of select) {
    if (carattere === '(') profondita++;
    if (carattere === ')') profondita--;
    if (carattere === ',' && profondita === 0) {
      pezzi.push(corrente);
      corrente = '';
      continue;
    }
    corrente += carattere;
  }
  pezzi.push(corrente);
  const nomi: string[] = [];
  for (const grezzo of pezzi) {
    let pezzo = grezzo.trim();
    if (pezzo === '' || pezzo.includes('(')) continue;
    if (pezzo.includes(':')) pezzo = pezzo.slice(pezzo.lastIndexOf(':') + 1);
    pezzo = pezzo.split('->')[0].trim();
    if (/^[a-z_][a-z0-9_]*$/.test(pezzo)) nomi.push(pezzo);
  }
  return nomi;
}

/**
 * I letterali stringa di un pezzo di sorgente, nell'ordine. Dai template
 * spariscono i `${…}` (le parti che vengono da `FONTE_BANDI` si leggono a
 * parte); un letterale confrontato (`=== 'bando_pubblico'`) non è una colonna.
 */
function letterali(sorgente: string): string[] {
  return [...sorgente.matchAll(/(?<![=!]==\s*)'([^'\n]*)'|`([^`]*)`/g)]
    .map((m) => (m[1] ?? m[2]).replace(/\$\{[^}]*\}/g, ''));
}

function senzaCommenti(sorgente: string): string {
  return sorgente.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/**
 * Le colonne di `bando` citate dal frontend, per file.
 *
 * Si leggono dai sorgenti e non da una lista scritta a mano: una select nuova
 * deve entrare da sola. In `supabase-bandi.ts` le select si compongono da
 * array (`...COLONNE_DETTAGLIO_COMUNI`, `selectConMotivo([...])`): si leggono
 * gli array `BANDO_SELECT_*` e `COLONNE_*`, e un test controlla che ogni
 * spread punti a uno di questi. Gli embed di `api-v1` non sono colonne di
 * `bando` e restano fuori.
 */
function colonneCitate(): Map<string, string[]> {
  const per_file = new Map<string, string[]>();
  const leggi = (file: string): string => senzaCommenti(readFileSync(new URL(file, RADICE), 'utf8'));

  // supabase-bandi.ts: gli array delle costanti `BANDO_SELECT_*` e `COLONNE_*`
  // (entrambi i rami di `COLONNE_MOTIVO`: quello della tabella e' comunque
  // fatto di colonne che anche la vista ha).
  {
    const nomi: string[] = [];
    for (const m of costantiDiSelect().values()) {
      for (const array of m.matchAll(/\[([^\]]*)\]/g)) {
        for (const valore of letterali(array[1])) nomi.push(...colonneDiSelect(valore));
      }
    }
    per_file.set('src/lib/supabase-bandi.ts', nomi);
  }

  // colonne.ts: `SELECT_BANDO`, una stringa concatenata su piu' righe.
  {
    const testo = leggi('src/lib/api-v1/colonne.ts');
    const m = testo.match(/export const SELECT_BANDO\s*=\s*([\s\S]*?);\n/);
    assert.ok(m, 'SELECT_BANDO non trovata');
    per_file.set('src/lib/api-v1/colonne.ts', colonneDiSelect(letterali(m[1]).join('')));
  }

  // pubblicazione.ts: quello che la fonte `bando_pubblico` aggiunge alle select
  // (freschezza, stato calcolato, colonne v11 dell'API).
  {
    const testo = leggi('src/lib/bandi/pubblicazione.ts');
    const blocco = testo.match(/\bbando_pubblico:\s*\{([\s\S]*?)\n {2}\},/);
    assert.ok(blocco, 'fonte bando_pubblico non trovata in FONTI_BANDI');
    const nomi: string[] = [];
    for (const chiave of ['selectFreschezza', 'colonnaFreschezza', 'colonnaStato']) {
      const valore = blocco[1].match(new RegExp(`${chiave}:\\s*'([^']*)'`));
      assert.ok(valore, `${chiave} non trovata`);
      nomi.push(...colonneDiSelect(valore[1]));
    }
    const v11 = blocco[1].match(/colonneV11:\s*\[([^\]]*)\]/);
    assert.ok(v11, 'colonneV11 della vista non trovate');
    for (const valore of letterali(v11[1])) nomi.push(...colonneDiSelect(valore));
    per_file.set('src/lib/bandi/pubblicazione.ts', nomi);
  }

  // corpus.ts: la select dei conteggi, passata da `selectConMotivo`.
  {
    const testo = leggi('src/lib/corpus.ts');
    const m = testo.match(/selectConMotivo\('([^']*)'/);
    assert.ok(m, 'select del corpus non trovata');
    per_file.set('src/lib/corpus.ts', colonneDiSelect(m[1]));
  }

  // Le due sitemap: la select è sulla tabella di `FONTE_BANDI`.
  for (const file of ['src/pages/sitemap-index.xml.ts', 'src/pages/sitemap-bandi/[pagina].xml.ts']) {
    const testo = leggi(file);
    const nomi: string[] = [];
    const righe = testo.split('\n');
    righe.forEach((riga, i) => {
      if (!/\.select\(/.test(riga)) return;
      // Solo le select che seguono `FONTE_BANDI.tabella` entro poche righe.
      const contesto = righe.slice(Math.max(0, i - 3), i + 1).join('\n');
      if (!contesto.includes('FONTE_BANDI.tabella')) return;
      const m = riga.match(/\.select\(\s*('[^']*'|`[^`]*`)/);
      if (m) nomi.push(...colonneDiSelect(letterali(m[1]).join('')));
    });
    per_file.set(file, nomi);
  }
  assert.equal(per_file.size, 6, 'i sei file che leggono da FONTE_BANDI');
  for (const [file, nomi] of per_file) {
    assert.ok(nomi.length, `nessuna colonna estratta da ${file}: estrazione rotta`);
  }
  return per_file;
}

/** I corpi delle costanti `BANDO_SELECT_*` e `COLONNE_*` di supabase-bandi.ts, per nome. */
function costantiDiSelect(): Map<string, string> {
  const testo = senzaCommenti(readFileSync(new URL('src/lib/supabase-bandi.ts', RADICE), 'utf8'));
  const costanti = new Map<string, string>();
  for (const m of testo.matchAll(
    /(?:export\s+)?const\s+((?:BANDO_SELECT|COLONNE)_[A-Z_]+)\b[^=]*=\s*([\s\S]*?);\n/g,
  )) {
    costanti.set(m[1], m[2]);
  }
  return costanti;
}

test('l\'estrazione legge spread, concatenazioni, template e alias', () => {
  const citate = colonneCitate();
  const tutte = new Set([...citate.values()].flat());
  // `id` apre l'array delle colonne comuni: la regex di prima lo perdeva.
  for (const attesa of [
    'id', 'contenuto', 'link_candidatura', 'allegati',              // COLONNE_DETTAGLIO_COMUNI
    'stato_effettivo', 'stato_da_verificare', 'termine_indicato_fonte', // vista e motivo
    'ultimo_cambiamento_at', 'fonte_ufficiale_verificata_at',        // alias e colonne v11
  ]) {
    assert.ok(tutte.has(attesa), `colonna non estratta: ${attesa}`);
  }
  // SELECT_BANDO e' concatenata su piu' righe: le colonne a cavallo dei `+` ci sono.
  for (const attesa of ['data_pubblicazione', 'stato_bando', 'created_at']) {
    assert.ok(citate.get('src/lib/api-v1/colonne.ts')?.includes(attesa), `SELECT_BANDO: ${attesa}`);
  }
  // le sitemap con il template di FONTE_BANDI
  assert.deepEqual(
    [...new Set(citate.get('src/pages/sitemap-bandi/[pagina].xml.ts'))].sort(),
    ['data_pubblicazione', 'id', 'slug'],
  );
  // niente embed, niente valori confrontati
  for (const estranea of ['bando_pubblico', 'tipologie_bando', 'bando_regioni', 'regioni', 'nome']) {
    assert.equal(tutte.has(estranea), false, `non e' una colonna di bando: ${estranea}`);
  }
});

test('ogni spread delle select di supabase-bandi.ts punta a un array letto dal test', () => {
  const costanti = costantiDiSelect();
  assert.ok(costanti.has('COLONNE_DETTAGLIO_COMUNI') && costanti.has('COLONNE_DETTAGLIO_VISTA'));
  for (const [nome, corpo] of costanti) {
    for (const m of corpo.matchAll(/\.\.\.([A-Z][A-Z_]+)\b(?!\.)/g)) {
      assert.ok(costanti.has(m[1]), `${nome}: lo spread di ${m[1]} sfugge al test`);
    }
    for (const m of corpo.matchAll(/\?\s*([A-Z][A-Z_]+)\s*:/g)) {
      assert.ok(costanti.has(m[1]), `${nome}: ${m[1]} sfugge al test`);
    }
  }
});

test('la vista `bando_pubblico` espone `ultimo_cambiamento_at`, non `updated_at`', () => {
  const colonne = colonneDellaVista();
  assert.ok(colonne.has('ultimo_cambiamento_at'));
  assert.ok(!colonne.has('updated_at'));
  // Qualche colonna di controllo: se l'estrazione smette di funzionare, il
  // test non deve passare per insieme vuoto.
  for (const attesa of ['id', 'slug', 'titolo', 'stato_effettivo', 'contenuto']) {
    assert.ok(colonne.has(attesa), `la vista dovrebbe esporre ${attesa}`);
  }
  assert.ok(colonne.size > 20, `troppe poche colonne estratte: ${colonne.size}`);
});

test('ogni colonna citata dal frontend o esiste sulla vista, o la vista resta disarmata', () => {
  const colonne = colonneDellaVista();
  const mancanti = new Map<string, string[]>();
  for (const [file, nomi] of colonneCitate()) {
    const fuori = [...new Set(nomi.filter((n) => !colonne.has(n)))].sort();
    if (fuori.length) mancanti.set(file, fuori);
  }

  if (mancanti.size === 0) {
    // Lavoro F2 finito: la guardia non ha più ragione di esistere, e lasciarla
    // vorrebbe dire tenere spenta una vista funzionante.
    assert.equal(
      FONTI_NON_PRONTE.bando_pubblico, undefined,
      'nessuna colonna manca più: togliere `bando_pubblico` da FONTI_NON_PRONTE',
    );
    return;
  }

  // Ci sono colonne fuori dalla vista: il flag DEVE restare disarmato.
  assert.ok(
    FONTI_NON_PRONTE.bando_pubblico,
    'colonne assenti dalla vista ma flag armato: '
    + [...mancanti].map(([f, n]) => `${f} -> ${n.join(', ')}`).join(' | '),
  );
  // La fotografia di oggi: `updated_at` e nient'altro. Se un giorno ne
  // comparisse un'altra, questo test lo dice prima del 42703.
  const tutte = [...new Set([...mancanti.values()].flat())].sort();
  assert.deepEqual(tutte, ['updated_at']);
});

test('vista della 07: mancano ESATTAMENTE le tre colonne dichiarate nella sua testa', () => {
  const colonne = colonneDellaVista(MIGRAZIONE_07);
  // l'estrazione funziona anche sulla 07, e la 07 porta le colonne della 13
  for (const attesa of ['id', 'slug', 'stato_effettivo', 'ultimo_cambiamento_at', 'stato_da_verificare',
    'termine_indicato_fonte']) {
    assert.ok(colonne.has(attesa), `la vista della 07 dovrebbe esporre ${attesa}`);
  }
  const fuori = new Set<string>();
  for (const nomi of colonneCitate().values()) {
    for (const nome of nomi) if (!colonne.has(nome)) fuori.add(nome);
  }
  // Una colonna in piu' qui e' un 42703 su ogni scheda il giorno della 07; una
  // in meno vuol dire che il sito ha smesso di chiederla e la precondizione
  // della 07 va aggiornata.
  assert.deepEqual([...fuori].sort(), MANCANTI_NOTE_DELLA_07);
  const testa = readFileSync(MIGRAZIONE_07, 'utf8').split(/CREATE (?:OR REPLACE )?VIEW/)[0];
  for (const nome of MANCANTI_NOTE_DELLA_07) {
    assert.ok(testa.includes(`\`${nome}\``), `la testa della 07 non dichiara ${nome}`);
  }
});
