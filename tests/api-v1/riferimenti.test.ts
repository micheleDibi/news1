/**
 * riferimenti.ts: validazione di categorie e secondarie, profili, CacheRiferimento
 * (TTL, single-flight, copia vecchia su errore, memoria negativa, nessuna
 * rejection non gestita). Orologio finto: nessuna attesa reale.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CacheRiferimento, MEMORIA_NEGATIVA_MS, PAUSA_RINFRESCO_FALLITO_MS, costruisciRiferimentoCategorie,
  costruisciRiferimentoProfili,
} from '../../src/lib/api-v1/riferimenti.ts';
import { ErroreDati } from '../../src/lib/api-v1/errori.ts';
import { RIGHE_CATEGORIE, RIGHE_PROFILI, RIGHE_SECONDARIE } from './fixture/riferimenti-base.ts';
import type { RigaCategoria, RigaSecondaria, RiferimentoCategorie } from '../../src/lib/api-v1/contratto.ts';

// ---------------------------------------------------------------------------
// Categorie
// ---------------------------------------------------------------------------

test('categorie: riferimento dalla fixture, ordine, colori, URL', () => {
  const { riferimento, scarti } = costruisciRiferimentoCategorie(RIGHE_CATEGORIE, RIGHE_SECONDARIE);
  assert.deepEqual(riferimento.ordinate.map((c) => c.slug), ['scuola', 'universita', 'lavoro', 'senza-posizione']);
  assert.deepEqual(riferimento.ordinate[0], {
    slug: 'scuola', name: 'Scuola', color: '#2D6A4F', position: 1, url: 'https://edunews24.it/scuola',
  });
  assert.equal(riferimento.perSlug.get('senza-posizione')?.color, '#004e9c');
  assert.equal(riferimento.perSlug.get('senza-posizione')?.position, null);
  assert.equal(riferimento.perSlug.size, 4);
  // secondaria orfana ('bandi' non esiste) scartata e segnalata
  assert.equal(scarti.length, 1);
  assert.match(scarti[0], /secondaria #4/);
  assert.deepEqual(
    riferimento.secondariePerParent.get('scuola')?.map((s) => s.slug),
    ['ata', 'dirigenti', 'insegnanti'],
  );
  assert.equal(riferimento.secondariePerParent.has('bandi'), false);
  for (const s of riferimento.secondariePerParent.get('scuola') ?? []) assert.equal(s.parent, 'scuola');
});

test('categorie: validazione di slug e nome', () => {
  const righe: RigaCategoria[] = [
    { slug: 'Scuola', name: 'Maiuscole', color: null, order_id: 1 },
    { slug: 'doppio--trattino', name: 'Doppio', color: null, order_id: 1 },
    { slug: 'a'.repeat(65), name: 'Troppo lungo', color: null, order_id: 1 },
    { slug: 'b'.repeat(64), name: 'Lungo giusto', color: null, order_id: 1 },
    { slug: 42, name: 'Numero', color: null, order_id: 1 },
    { slug: 'nome-vuoto', name: '   ', color: null, order_id: 1 },
    { slug: 'nome-html', name: '<b></b>', color: null, order_id: 1 },
    { slug: 'nome-lungo', name: 'n'.repeat(81), color: null, order_id: 1 },
    { slug: 'nome-80', name: 'n'.repeat(80), color: null, order_id: 2 },
    { slug: 'nome-url', name: 'https://www.esterno.example/x', color: null, order_id: 3 },
    { slug: 'nome-entita', name: 'Scuola &amp; <i>formazione</i>', color: 'constructor', order_id: 4 },
  ];
  const { riferimento, scarti } = costruisciRiferimentoCategorie(righe, []);
  assert.deepEqual(riferimento.ordinate.map((c) => c.slug), ['b'.repeat(64), 'nome-80', 'nome-entita']);
  assert.equal(riferimento.perSlug.get('nome-entita')?.name, 'Scuola & formazione');
  // 'constructor' non deve pescare dal prototipo di CATEGORY_COLORS
  assert.equal(riferimento.perSlug.get('nome-entita')?.color, '#004e9c');
  assert.equal(scarti.length, 8);
  for (const s of scarti) assert.doesNotMatch(s, /Maiuscole|Numero|Troppo/);
});

test('categorie: colore hex diretto e nomi di colore noti', () => {
  const { riferimento } = costruisciRiferimentoCategorie([
    { slug: 'a', name: 'A', color: '#123abc', order_id: 1 },
    { slug: 'b', name: 'B', color: 'universita', order_id: 2 },
    { slug: 'c', name: 'C', color: 7, order_id: 3 },
    { slug: 'd', name: 'D', color: 'toString', order_id: 4 },
  ], []);
  assert.deepEqual(riferimento.ordinate.map((c) => c.color), ['#123abc', '#1B3A7B', '#004e9c', '#004e9c']);
});

test('categorie: duplicati -> vale la prima riga valida', () => {
  const { riferimento, scarti } = costruisciRiferimentoCategorie([
    { slug: 'scuola', name: 'Scuola', color: 'scuola', order_id: 5 },
    { slug: 'scuola', name: 'Scuola bis', color: 'lavoro', order_id: 1 },
  ], []);
  assert.equal(riferimento.ordinate.length, 1);
  assert.equal(riferimento.perSlug.get('scuola')?.name, 'Scuola');
  assert.equal(riferimento.perSlug.get('scuola')?.position, 5);
  assert.deepEqual(scarti, ['categoria #1: slug duplicato']);
});

test('categorie: position null in fondo, poi slug; order_id non intero -> null', () => {
  const { riferimento } = costruisciRiferimentoCategorie([
    { slug: 'zeta', name: 'Zeta', color: null, order_id: null },
    { slug: 'alfa', name: 'Alfa', color: null, order_id: null },
    { slug: 'due', name: 'Due', color: null, order_id: 2 },
    { slug: 'uno-b', name: 'Uno B', color: null, order_id: 1 },
    { slug: 'uno-a', name: 'Uno A', color: null, order_id: 1 },
    { slug: 'frazione', name: 'Frazione', color: null, order_id: 1.5 },
    { slug: 'stringa', name: 'Stringa', color: null, order_id: '3' },
    { slug: 'negativa', name: 'Negativa', color: null, order_id: -1 },
    { slug: 'enorme', name: 'Enorme', color: null, order_id: 2 ** 53 },
  ], []);
  assert.deepEqual(
    riferimento.ordinate.map((c) => [c.slug, c.position]),
    [['negativa', -1], ['uno-a', 1], ['uno-b', 1], ['due', 2],
      ['alfa', null], ['enorme', null], ['frazione', null], ['stringa', null], ['zeta', null]],
  );
});

test('categorie: oltre 30 restano le prime 30 per posizione', () => {
  const righe: RigaCategoria[] = [];
  for (let i = 35; i >= 1; i -= 1) righe.push({ slug: `categoria-${i}`, name: `Categoria ${i}`, color: null, order_id: i });
  const { riferimento, scarti } = costruisciRiferimentoCategorie(righe, [
    { slug: 'figlia', name: 'Figlia', parent_category_slug: 'categoria-33' },
  ]);
  assert.equal(riferimento.ordinate.length, 30);
  assert.equal(riferimento.perSlug.size, 30);
  assert.equal(riferimento.ordinate[0].slug, 'categoria-1');
  assert.equal(riferimento.ordinate[29].slug, 'categoria-30');
  assert.equal(riferimento.perSlug.has('categoria-31'), false);
  // la secondaria di una categoria tagliata diventa orfana
  assert.equal(riferimento.secondariePerParent.size, 0);
  assert.ok(scarti.some((s) => /5 oltre il massimo di 30/.test(s)));
  assert.ok(scarti.some((s) => /secondaria #0: categoria madre assente/.test(s)));
});

test('categorie: nessuna categoria valida -> ErroreDati disponibilita', () => {
  for (const righe of [[], [{ slug: 'Non Valido', name: 'X', color: null, order_id: 1 }]] as RigaCategoria[][]) {
    assert.throws(
      () => costruisciRiferimentoCategorie(righe, RIGHE_SECONDARIE),
      (e: unknown) => e instanceof ErroreDati && e.classe === 'disponibilita' && e.message === 'riferimento categorie vuoto',
    );
  }
});

test('secondarie: validazione, orfane, duplicate, ordine per nome (collator it) poi slug', () => {
  const secondarie: RigaSecondaria[] = [
    { slug: 'zaino', name: 'Ãncora', parent_category_slug: 'scuola' },
    { slug: 'beta', name: 'Élite', parent_category_slug: 'scuola' },
    { slug: 'alfa', name: 'elite', parent_category_slug: 'scuola' },
    { slug: 'omonima-b', name: 'Omonima', parent_category_slug: 'scuola' },
    { slug: 'omonima-a', name: 'Omonima', parent_category_slug: 'scuola' },
    { slug: 'zeta', name: 'Zeta', parent_category_slug: 'scuola' },
    { slug: 'zeta', name: 'Zeta doppia', parent_category_slug: 'scuola' },
    { slug: 'zeta', name: 'Zeta in altra madre', parent_category_slug: 'universita' },
    { slug: 'Maiuscola', name: 'Slug non valido', parent_category_slug: 'scuola' },
    { slug: 'senza-nome', name: null, parent_category_slug: 'scuola' },
    { slug: 'madre-numero', name: 'Madre numero', parent_category_slug: 1 },
    { slug: 'madre-assente', name: 'Madre assente', parent_category_slug: 'inesistente' },
  ];
  const { riferimento, scarti } = costruisciRiferimentoCategorie(RIGHE_CATEGORIE, secondarie);
  assert.deepEqual(
    riferimento.secondariePerParent.get('scuola')?.map((s) => [s.slug, s.name]),
    [['zaino', 'Ãncora'], ['alfa', 'elite'], ['beta', 'Élite'], ['omonima-a', 'Omonima'], ['omonima-b', 'Omonima'],
      ['zeta', 'Zeta']],
  );
  assert.deepEqual(riferimento.secondariePerParent.get('universita')?.map((s) => s.name), ['Zeta in altra madre']);
  assert.equal(scarti.length, 5);
});

// ---------------------------------------------------------------------------
// Profili
// ---------------------------------------------------------------------------

test('profili: indici per id e per full_name esatto, campi normalizzati', () => {
  const rif = costruisciRiferimentoProfili([
    ...RIGHE_PROFILI,
    { id: '', full_name: 'Id vuoto', public_name: 'X', is_displayable: true },
    { id: 7, full_name: 'Id numerico', public_name: 'X', is_displayable: true },
    { id: 'u-giornalista', full_name: 'Duplicato', public_name: 'Duplicato', is_displayable: false },
    { id: 'u-spazi', full_name: '  Con Spazi  ', public_name: 42, is_displayable: null },
  ]);
  assert.equal(rif.perId.size, RIGHE_PROFILI.length + 1);
  assert.deepEqual(rif.perId.get('u-giornalista'), {
    id: 'u-giornalista', fullName: 'Mario Esempio Rossi', publicName: 'M. Rossi', visualizzabile: true,
  });
  assert.deepEqual(rif.perId.get('u-spazi'), { id: 'u-spazi', fullName: 'Con Spazi', publicName: null, visualizzabile: false });
  assert.equal(rif.perId.get('u-stringa')?.visualizzabile, false);
  assert.equal(rif.perNomeCompleto.get('Omonimo Doppio')?.length, 2);
  assert.equal(rif.perNomeCompleto.get('Mario Esempio Rossi')?.length, 1);
  // chiave esatta, non trimmata
  assert.equal(rif.perNomeCompleto.has('  Con Spazi  '), true);
  assert.equal(rif.perNomeCompleto.has('Con Spazi'), false);
  assert.equal(rif.perNomeCompleto.has('Duplicato'), false);
  assert.equal(rif.perNomeCompleto.has('Id vuoto'), false);
});

test('profili: nessuna riga -> riferimento vuoto (degrado previsto, non errore)', () => {
  const rif = costruisciRiferimentoProfili([]);
  assert.equal(rif.perId.size, 0);
  assert.equal(rif.perNomeCompleto.size, 0);
});

// ---------------------------------------------------------------------------
// CacheRiferimento
// ---------------------------------------------------------------------------

interface Rinviata<T> {
  promessa: Promise<T>;
  risolvi: (v: T) => void;
  rifiuta: (e: unknown) => void;
}

function rinviata<T>(): Rinviata<T> {
  let risolvi: (v: T) => void = () => undefined;
  let rifiuta: (e: unknown) => void = () => undefined;
  const promessa = new Promise<T>((ok, ko) => { risolvi = ok; rifiuta = ko; });
  return { promessa, risolvi, rifiuta };
}

/** Lascia girare i microtask (le promesse gia' risolte proseguono). */
async function scorri(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

function cacheDiProva<T>(carica: (segnale: AbortSignal) => Promise<T>, ttlMs = 1000) {
  const adesso = { ms: 1_000_000 };
  const eventi: string[] = [];
  const cache = new CacheRiferimento<T>({
    nome: 'prova',
    ttlMs,
    timeoutMs: 60_000,
    orologio: () => adesso.ms,
    carica,
    registra: (evento, dettaglio) => { eventi.push(`${evento}|${dettaglio ?? ''}`); },
  });
  return { cache, adesso, eventi };
}

const MAI = new AbortController().signal;

test('CacheRiferimento: fresco entro il TTL, poi valore vecchio e un solo rinfresco in background', async () => {
  let chiamate = 0;
  const { cache, adesso } = cacheDiProva(async () => { chiamate += 1; return `v${chiamate}`; }, 1000);
  assert.equal(cache.seCaldo(), null);
  assert.equal(await cache.ottieni(MAI), 'v1');
  assert.equal(cache.seCaldo(), 'v1');
  adesso.ms += 999;
  assert.equal(await cache.ottieni(MAI), 'v1');
  assert.equal(chiamate, 1);
  adesso.ms += 1;
  assert.equal(await cache.ottieni(MAI), 'v1', 'scaduto: si serve subito il vecchio');
  assert.equal(await cache.ottieni(MAI), 'v1');
  await cache.attendiRinfreschi();
  assert.equal(chiamate, 2, 'un solo rinfresco anche con due chiamate');
  assert.equal(await cache.ottieni(MAI), 'v2');
  assert.equal(cache.seCaldo(), 'v2');
});

test('CacheRiferimento: single-flight a freddo', async () => {
  let chiamate = 0;
  const attesa = rinviata<string>();
  const { cache } = cacheDiProva(() => { chiamate += 1; return attesa.promessa; });
  const tre = [cache.ottieni(MAI), cache.ottieni(MAI), cache.ottieni(new AbortController().signal)];
  await scorri();
  assert.equal(chiamate, 1);
  attesa.risolvi('valore');
  assert.deepEqual(await Promise.all(tre), ['valore', 'valore', 'valore']);
  assert.equal(chiamate, 1);
});

test('CacheRiferimento: il segnale del chiamante arriva combinato a carica', async () => {
  const controllore = new AbortController();
  let ricevuto: AbortSignal | null = null;
  const { cache } = cacheDiProva((segnale) => {
    ricevuto = segnale;
    return new Promise<string>((_ok, ko) => segnale.addEventListener('abort', () => ko(new Error('annullato'))));
  });
  const esito = cache.ottieni(controllore.signal);
  await scorri();
  assert.ok(ricevuto !== null);
  assert.notEqual(ricevuto, controllore.signal);
  controllore.abort();
  await assert.rejects(esito, (e: unknown) => e instanceof ErroreDati && e.classe === 'disponibilita');
  assert.equal((ricevuto as AbortSignal | null)?.aborted, true);
});

test('CacheRiferimento: un caricamento che ignora il segnale viene comunque chiuso dal timeout', async () => {
  const cache = new CacheRiferimento<string>({
    nome: 'lento', ttlMs: 1000, timeoutMs: 20, orologio: () => 0,
    carica: () => new Promise<string>(() => undefined),
  });
  // Il timer di AbortSignal.timeout e' unref: in un server il ciclo resta vivo da se',
  // qui lo tiene vivo un timer normale finche' la promessa non si chiude.
  const tieniVivo = setTimeout(() => undefined, 5_000);
  try {
    await assert.rejects(cache.ottieni(MAI), (e: unknown) => e instanceof ErroreDati && e.classe === 'disponibilita');
  } finally {
    clearTimeout(tieniVivo);
  }
});

test('CacheRiferimento: rinfresco fallito -> resta il vecchio, evento nel log, pausa prima di ritentare', async () => {
  let chiamate = 0;
  let fallisci = false;
  const { cache, adesso, eventi } = cacheDiProva(async () => {
    chiamate += 1;
    if (fallisci) throw new ErroreDati('disponibilita', '57014', 'timeout');
    return `v${chiamate}`;
  }, 1000);
  assert.equal(await cache.ottieni(MAI), 'v1');
  fallisci = true;
  adesso.ms += 1000;
  assert.equal(await cache.ottieni(MAI), 'v1');
  await cache.attendiRinfreschi();
  assert.equal(chiamate, 2);
  assert.equal(eventi.length, 1);
  assert.match(eventi[0], /^riferimento-rinfresco-fallito\|prova: disponibilita 57014/);
  // entro la pausa nessun nuovo tentativo
  adesso.ms += PAUSA_RINFRESCO_FALLITO_MS - 1;
  assert.equal(await cache.ottieni(MAI), 'v1');
  await cache.attendiRinfreschi();
  assert.equal(chiamate, 2);
  // dopo la pausa si ritenta, e con successo il valore si aggiorna
  fallisci = false;
  adesso.ms += 1;
  assert.equal(await cache.ottieni(MAI), 'v1');
  await cache.attendiRinfreschi();
  assert.equal(chiamate, 3);
  assert.equal(await cache.ottieni(MAI), 'v3');
});

test('CacheRiferimento: errore a freddo -> memoria negativa di 5 s con lo stesso errore', async () => {
  let chiamate = 0;
  const errore = new ErroreDati('disponibilita', null, 'giu');
  let fallisci = true;
  const { cache, adesso, eventi } = cacheDiProva(async () => {
    chiamate += 1;
    if (fallisci) throw errore;
    return 'ok';
  });
  await assert.rejects(cache.ottieni(MAI), (e: unknown) => e === errore);
  assert.equal(chiamate, 1);
  adesso.ms += MEMORIA_NEGATIVA_MS - 1;
  await assert.rejects(cache.ottieni(MAI), (e: unknown) => e === errore);
  await assert.rejects(cache.ottieni(MAI), (e: unknown) => e === errore);
  assert.equal(chiamate, 1, 'carica non viene richiamata durante la memoria negativa');
  assert.equal(cache.seCaldo(), null);
  fallisci = false;
  adesso.ms += 1;
  assert.equal(await cache.ottieni(MAI), 'ok');
  assert.equal(chiamate, 2);
  assert.ok(eventi.some((e) => e.startsWith('riferimento-non-disponibile|prova')));
});

test('CacheRiferimento: riferimento categorie vuoto -> errore, mai in cache', async () => {
  const righe: { categorie: RigaCategoria[] } = { categorie: [] };
  const { cache, adesso } = cacheDiProva<RiferimentoCategorie>(
    async () => costruisciRiferimentoCategorie(righe.categorie, []).riferimento,
  );
  await assert.rejects(cache.ottieni(MAI), (e: unknown) => e instanceof ErroreDati && e.classe === 'disponibilita');
  assert.equal(cache.seCaldo(), null);
  righe.categorie = RIGHE_CATEGORIE;
  adesso.ms += MEMORIA_NEGATIVA_MS;
  const rif = await cache.ottieni(MAI);
  assert.equal(rif.perSlug.size, 4);
  // un rinfresco che torna vuoto non sostituisce il riferimento buono
  righe.categorie = [];
  adesso.ms += 1000;
  assert.equal(await cache.ottieni(MAI), rif);
  await cache.attendiRinfreschi();
  assert.equal(cache.seCaldo(), rif);
});

test('CacheRiferimento: il chiamante che interrompe non avvelena la cache, gli agganciati ritentano', async () => {
  let chiamate = 0;
  const { cache } = cacheDiProva((segnale) => {
    chiamate += 1;
    if (chiamate === 1) {
      return new Promise<string>((_ok, ko) => segnale.addEventListener('abort', () => ko(new Error('annullato'))));
    }
    return Promise.resolve('secondo');
  });
  const primo = new AbortController();
  const esitoPrimo = cache.ottieni(primo.signal);
  const esitoSecondo = cache.ottieni(new AbortController().signal);
  await scorri();
  primo.abort();
  await assert.rejects(esitoPrimo);
  assert.equal(await esitoSecondo, 'secondo');
  assert.equal(chiamate, 2);
  // nessuna memoria negativa per l'interruzione del primo
  assert.equal(await cache.ottieni(MAI), 'secondo');
});

test('CacheRiferimento: nessuna unhandledRejection su errori a freddo e rinfreschi falliti', async () => {
  const nonGestite: unknown[] = [];
  const ascolta = (motivo: unknown) => { nonGestite.push(motivo); };
  process.on('unhandledRejection', ascolta);
  try {
    let modo: 'ok' | 'errore-sincrono' | 'errore' = 'errore';
    const { cache, adesso } = cacheDiProva((): Promise<string> => {
      if (modo === 'errore-sincrono') throw new Error('sincrono');
      if (modo === 'errore') return Promise.reject(new Error('asincrono'));
      return Promise.resolve('ok');
    });
    await assert.rejects(cache.ottieni(MAI));
    adesso.ms += MEMORIA_NEGATIVA_MS;
    modo = 'errore-sincrono';
    await assert.rejects(cache.ottieni(MAI), /sincrono/);
    adesso.ms += MEMORIA_NEGATIVA_MS;
    modo = 'ok';
    assert.equal(await cache.ottieni(MAI), 'ok');
    for (const m of ['errore', 'errore-sincrono'] as const) {
      modo = m;
      adesso.ms += 10_000;
      assert.equal(await cache.ottieni(MAI), 'ok');
      await cache.attendiRinfreschi();
    }
    await new Promise((fatto) => setImmediate(fatto));
    assert.deepEqual(nonGestite, []);
  } finally {
    process.off('unhandledRejection', ascolta);
  }
});

test('CacheRiferimento: parametri non validi -> RangeError', () => {
  const carica = async () => 'x';
  assert.throws(() => new CacheRiferimento({ nome: 'x', ttlMs: 0, timeoutMs: 1, orologio: () => 0, carica }), RangeError);
  assert.throws(() => new CacheRiferimento({ nome: 'x', ttlMs: 1, timeoutMs: Number.NaN, orologio: () => 0, carica }), RangeError);
});
