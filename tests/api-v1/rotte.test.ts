/**
 * Rotte di src/pages/api/v1 e select esplicite: controlli statici sul sorgente.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SELECT_PER_NOME } from '../../src/lib/api-v1/colonne.ts';
import { documentoOpenApi } from '../../src/lib/api-v1/openapi.ts';

const radice = fileURLToPath(new URL('../../src/pages/api/v1/', import.meta.url));

function fileRicorsivi(cartella: string): string[] {
  return readdirSync(cartella).flatMap((nome) => {
    const percorso = join(cartella, nome);
    return statSync(percorso).isDirectory() ? fileRicorsivi(percorso) : [percorso];
  });
}

/** File di rotta -> path OpenAPI serviti. */
const MAPPA_ROTTE = new Map<string, string[]>([
  ['index.ts', ['/']],
  ['openapi.json.ts', ['/openapi.json']],
  ['[...resto].ts', []],
  ['categories.ts', ['/categories']],
  ['articles/index.ts', ['/articles']],
  ['articles/[id].ts', ['/articles/{id}']],
  ['interpelli/index.ts', ['/interpelli']],
  ['interpelli/[id].ts', ['/interpelli/{id}']],
  ['selezione-personale/index.ts', ['/selezione-personale']],
  ['selezione-personale/[id].ts', ['/selezione-personale/{id}']],
  ['bandi/index.ts', ['/bandi']],
  ['bandi/[id].ts', ['/bandi/{id}']],
  ['feeds/[...percorso].ts', [
    ...['articles', 'interpelli', 'selezione-personale', 'bandi'].flatMap((r) => [`/feeds/${r}.json`, `/feeds/${r}.xml`]),
    '/feeds/articles/{category}.json', '/feeds/articles/{category}.xml',
  ]],
]);

test('ogni rotta esporta GET, HEAD (= GET), OPTIONS e ALL, e nient\'altro', () => {
  const file = fileRicorsivi(radice).map((f) => relative(radice, f).split('\\').join('/'));
  assert.deepEqual([...file].sort(), [...MAPPA_ROTTE.keys()].sort());
  for (const f of file) {
    const s = readFileSync(join(radice, f), 'utf8');
    const esportazioni = [...s.matchAll(/^export\s+(?:const|function|async function|let)\s+(\w+)/gm)].map((m) => m[1]);
    assert.deepEqual(esportazioni, ['GET', 'HEAD', 'OPTIONS', 'ALL'], f);
    const get = /export const GET = (\w+)\.GET;/.exec(s);
    const head = /export const HEAD = (\w+)\.GET;/.exec(s);
    assert.ok(get && head && get[1] === head[1], `${f}: HEAD deve essere lo stesso handler di GET`);
    assert.ok(!/export\s+(const|function)\s+(get|head|options|all|POST|PUT|PATCH|DELETE)\b/.test(s), f);
  }
});

test('i path delle rotte coincidono con quelli di OpenAPI', () => {
  const documento = documentoOpenApi() as { paths: Record<string, unknown> };
  const attesi = [...MAPPA_ROTTE.values()].flat().sort();
  assert.deepEqual(Object.keys(documento.paths).sort(), attesi);
});

/** Colonne di una select PostgREST: percorsi tabella.colonna, alias risolti. */
function colonneDi(select: string, tabella: string): string[] {
  const risultato: string[] = [];
  let i = 0;
  function leggiLista(tab: string): void {
    while (i < select.length) {
      while (select[i] === ' ' || select[i] === ',') i++;
      if (select[i] === ')' || i >= select.length) return;
      let token = '';
      while (i < select.length && !',()'.includes(select[i])) token += select[i++];
      token = token.trim();
      const nome = token.includes(':') ? token.split(':')[1] : token;
      const tabellaFiglia = nome.replace(/!inner$/, '');
      if (select[i] === '(') {
        i++;
        leggiLista(tabellaFiglia);
        i++; // ')'
      } else {
        risultato.push(`${tab}.${nome}`);
      }
    }
  }
  leggiLista(tabella);
  return risultato;
}

test('select: insieme esatto delle colonne, nessuna colonna vietata', () => {
  const attese = new Map<string, string[]>([
    ['articolo', ['id', 'slug', 'title', 'title_summary', 'excerpt', 'summary', 'category_slug', 'secondary_category_slugs',
      'image_url', 'thumbnail_url', 'video_url', 'video_duration', 'published_at', 'tags', 'creator'].map((c) => `articles.${c}`)],
    ['categorie', ['slug', 'name', 'color', 'order_id'].map((c) => `categories.${c}`)],
    ['secondarie', ['slug', 'name', 'parent_category_slug'].map((c) => `secondary_categories.${c}`)],
    ['profili', ['id', 'full_name', 'public_name', 'is_displayable'].map((c) => `profiles.${c}`)],
    ['interpello', ['id', 'interpello_name', 'interpello_date', 'interpello_description', 'interpello_regione',
      'interpello_provincia', 'interpello_citta', 'classe_concorso', 'article_title', 'article_subtitle'].map((c) => `interpelli.${c}`)],
    ['selezione', ['id', 'slug', 'codice', 'titolo', 'article_title', 'article_subtitle', 'figura_ricercata', 'num_posti',
      'tipo_procedura', 'data_pubblicazione', 'data_scadenza', 'sedi', 'categorie', 'settori', 'enti_riferimento',
      'salary_min', 'salary_max', 'updated_at'].map((c) => `selezione_personale.${c}`)],
    // Gli alias (tipologia:, programma:, modalita:) si risolvono sulla tabella; le junction
    // bando_* non hanno colonne proprie: compaiono solo le colonne delle tabelle annidate.
    ['bando', [
      ...['id', 'slug', 'titolo', 'titolo_breve', 'descrizione_breve', 'ente_erogatore', 'area_geografica', 'tematica',
        'data_pubblicazione', 'data_apertura', 'data_scadenza', 'importo_totale_eur', 'importo_max_per_progetto_eur',
        'stato_bando', 'created_at', 'updated_at'].map((c) => `bando.${c}`),
      'tipologie_bando.nome', 'programmi.nome', 'modalita_erogazione.nome', 'regioni.nome', 'regioni.slug',
      'settori.nome', 'beneficiari.nome', 'codici_ateco.codice', 'codici_ateco.descrizione',
    ]],
  ]);
  const TABELLA = new Map([['articolo', 'articles'], ['categorie', 'categories'], ['secondarie', 'secondary_categories'],
    ['profili', 'profiles'], ['interpello', 'interpelli'], ['selezione', 'selezione_personale'], ['bando', 'bando'],
    ['bando-con-regione', 'bando']]);
  for (const [nome, select] of SELECT_PER_NOME) {
    assert.ok(!select.includes('*'), nome);
    assert.ok(!/\${|join/.test(select), nome);
    const colonne = colonneDi(select, TABELLA.get(nome)!);
    const attese_ = attese.get(nome);
    if (attese_) assert.deepEqual(new Set(colonne), new Set(attese_), nome);
    for (const vietata of [
      'articles.content', 'articles.faqs', 'articles.audio_url', 'articles.source', 'articles.isdraft', 'articles.persona_job_id',
      'interpelli.article_content', 'interpelli.interpello_link', 'interpelli.source_daily_link', 'interpelli.status', 'interpelli.link_type',
      'selezione_personale.descrizione', 'selezione_personale.descrizione_breve', 'selezione_personale.article_content',
      'selezione_personale.link_reindirizzamento', 'selezione_personale.status', 'bando.descrizione', 'bando.contenuto', 'bando.raw_data',
      'bando.confidence_score', 'bando.hash_bando', 'bando.fonte_id', 'bando.titolo_raw', 'bando.stato_processing',
      'bando.link_bando', 'bando.link_candidatura', 'bando.allegati', 'profiles.email', 'profiles.permissions', 'profiles.role',
    ]) {
      assert.ok(!colonne.includes(vietata), `${nome}: ${vietata}`);
    }
    assert.ok(!colonne.some((c) => c.startsWith('articles.skill_') || c.startsWith('profiles.') && !attese.get('profili')!.includes(c)), nome);
  }
  const bando = colonneDi(SELECT_PER_NOME.get('bando')!, 'bando');
  assert.ok(bando.includes('regioni.slug') && bando.includes('codici_ateco.descrizione'));
  const conRegione = colonneDi(SELECT_PER_NOME.get('bando-con-regione')!, 'bando');
  assert.deepEqual(conRegione.slice(0, bando.length), bando);
  assert.deepEqual(conRegione.slice(bando.length), ['regioni.slug']);
});
