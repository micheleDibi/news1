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
 * Le colonne della vista si estraggono dal file SQL della migrazione 05, che è
 * la definizione vera; l'elenco non si ricopia qui, perché una copia che
 * nessuno confronta diverge.
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
const MIGRAZIONE_05 = new URL('backend/sql/bando_v11_05_vista_pubblica.sql', RADICE);

/** Le colonne in uscita da `CREATE VIEW public.bando_pubblico ... FROM public.bando b`. */
function colonneDellaVista(): Set<string> {
  const sql = readFileSync(MIGRAZIONE_05, 'utf8');
  const inizio = sql.indexOf('CREATE VIEW public.bando_pubblico');
  assert.ok(inizio >= 0, 'definizione della vista non trovata nella 05');
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
 * Le colonne di `bando` citate dal frontend, per file.
 *
 * Si leggono dai sorgenti e non da una lista scritta a mano: una select nuova
 * deve entrare da sola. Gli embed di `api-v1` (`tipologia:tipologie_bando(...)`)
 * non sono colonne di `bando` e restano fuori.
 */
function colonneCitate(): Map<string, string[]> {
  const per_file = new Map<string, string[]>();

  const daElenco = (testo: string): string[] => testo
    .split(',')
    .map((p) => p.trim().replace(/^['"]|['"]$/g, '').trim())
    .filter((p) => /^[a-z_][a-z0-9_]*$/.test(p));

  // supabase-bandi.ts e colonne.ts: le costanti `BANDO_SELECT_*` / `SELECT_BANDO`.
  for (const file of ['src/lib/supabase-bandi.ts', 'src/lib/api-v1/colonne.ts']) {
    const testo = readFileSync(new URL(file, RADICE), 'utf8');
    const nomi: string[] = [];
    for (const m of testo.matchAll(
      /export const (BANDO_SELECT_[A-Z_]+|SELECT_BANDO)\s*=\s*([\s\S]*?);\n/g,
    )) {
      nomi.push(...daElenco(m[2]));
    }
    per_file.set(file, nomi);
  }

  // Le due sitemap: la select è sulla tabella di `FONTE_BANDI`.
  for (const file of ['src/pages/sitemap-index.xml.ts', 'src/pages/sitemap-bandi/[pagina].xml.ts']) {
    const testo = readFileSync(new URL(file, RADICE), 'utf8');
    const nomi: string[] = [];
    const righe = testo.split('\n');
    righe.forEach((riga, i) => {
      if (!/\.select\(/.test(riga)) return;
      // Solo le select che seguono `FONTE_BANDI.tabella` entro poche righe.
      const contesto = righe.slice(Math.max(0, i - 3), i + 1).join('\n');
      if (!contesto.includes('FONTE_BANDI.tabella')) return;
      const m = riga.match(/\.select\(\s*'([^']*)'/);
      if (m) nomi.push(...daElenco(m[1]));
    });
    per_file.set(file, nomi);
  }
  assert.equal(per_file.size, 4, 'i quattro file che leggono da FONTE_BANDI');
  for (const [file, nomi] of per_file) {
    assert.ok(nomi.length, `nessuna colonna estratta da ${file}: estrazione rotta`);
  }
  return per_file;
}

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
