/**
 * Il flag della fonte dei bandi deve arrivare fino alla query dell'API.
 *
 * `filtri.ts` sa già leggere `contesto.fonteBandi`, ma fino a questo giro
 * nessuno lo valorizzava: il contesto nasceva in `risorse.ts` con i soli
 * default, e `BANDI_FONTE_LETTURA=bando_pubblico` cambiava le pagine del sito
 * lasciando l'API sulla tabella `bando`. Due superfici pubbliche dello stesso
 * corpus che leggono da due posti diversi sono la cosa che questo test
 * impedisce.
 *
 * Il percorso coperto è `DipendenzeRisorse.fonteBandi` -> `contestoPiano` ->
 * `pianoQuery`, per tutti e tre i modi (elenco, dettaglio, feed): la fonte non
 * la si può dimenticare in uno solo di essi. L'ultimo anello (`rotta.ts` che
 * legge le due variabili d'ambiente) non è caricabile sotto `node --test`
 * (crea i client Supabase a livello di modulo) e si verifica sul sorgente.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ELENCO_BANDI, DETTAGLIO_BANDO, ELENCO_ARTICOLI, FEED,
  type DipendenzeRisorse, type Esecuzione,
} from '../../src/lib/api-v1/risorse.ts';
import { costruisciRiferimentoCategorie, costruisciRiferimentoProfili } from '../../src/lib/api-v1/riferimenti.ts';
import type { FonteDati, NomeSelect, PianoQuery, RighePerSelect } from '../../src/lib/api-v1/contratto.ts';
import { nomeFonteBandiDa, type NomeFonteBandi } from '../../src/lib/bandi/pubblicazione.ts';

const CATEGORIE = costruisciRiferimentoCategorie(
  [{ slug: 'scuola', name: 'Scuola', color: 'scuola', order_id: 1 }], [],
).riferimento;
const PROFILI = costruisciRiferimentoProfili([]);

/** Fonte finta: non legge niente, registra i piani che riceve. */
class FonteSpia implements FonteDati {
  piani: PianoQuery[] = [];
  async leggi<S extends NomeSelect>(piano: PianoQuery<S>): Promise<RighePerSelect[S][]> {
    this.piani.push(piano);
    return [];
  }
}

function dipendenze(fonteBandi?: NomeFonteBandi): { dip: DipendenzeRisorse; spia: FonteSpia } {
  const spia = new FonteSpia();
  const dip: DipendenzeRisorse = {
    fonte: spia,
    categorie: { async ottieni() { return CATEGORIE; }, seCaldo() { return CATEGORIE; } },
    profili: { async ottieni() { return PROFILI; }, seCaldo() { return PROFILI; } },
    valoriRegioneCorpus: () => [],
    limiteDichiarato: { requests: 60, window_seconds: 60 },
    fonteBandi,
    registra: () => {},
  };
  return { dip, spia };
}

const ESECUZIONE: Esecuzione = {
  adessoMs: Date.UTC(2026, 8, 23, 9, 0, 0),
  oggi: '2026-09-23',
  segnale: AbortSignal.timeout(5_000),
};

/** Esegue le tre rotte dei bandi e restituisce i piani osservati. */
async function pianiBandi(fonteBandi?: NomeFonteBandi): Promise<PianoQuery[]> {
  const { dip, spia } = dipendenze(fonteBandi);
  await ELENCO_BANDI.prepara(new URL('https://edunews24.it/api/v1/bandi'), {}).produci(dip, ESECUZIONE);
  // Il dettaglio non trova righe (la fonte è vuota) e solleva 404: il piano è
  // già stato registrato, ed è l'unica cosa che qui interessa.
  await assert.rejects(
    DETTAGLIO_BANDO.prepara(new URL('https://edunews24.it/api/v1/bandi/1'), { id: '1' }).produci(dip, ESECUZIONE));
  await FEED.prepara(new URL('https://edunews24.it/api/v1/feeds/bandi.json'), { percorso: 'bandi.json' })
    .produci(dip, ESECUZIONE);
  assert.equal(spia.piani.length, 3, 'elenco, dettaglio e feed');
  return spia.piani;
}

test('senza flag l\'API legge dalla tabella `bando`, con il predicato', async () => {
  for (const piano of await pianiBandi(undefined)) {
    assert.equal(piano.tabella, 'bando');
    assert.deepEqual(
      piano.operazioni.filter((o) => o.tipo === 'filtro' && o.colonna === 'stato_processing'),
      [{ tipo: 'filtro', colonna: 'stato_processing', operatore: 'eq', valore: 'completed' }]);
  }
});

test('con il flag l\'API legge dalla vista, senza predicato', async () => {
  for (const piano of await pianiBandi('bando_pubblico')) {
    assert.equal(piano.tabella, 'bando_pubblico');
    // Sulla vista il predicato è dentro (`WHERE pubblicato`): ripeterlo
    // significherebbe 42703, cioè ogni risposta dei bandi a 503.
    assert.deepEqual(piano.operazioni.filter((o) => o.tipo === 'filtro' && o.colonna === 'stato_processing'), []);
    assert.deepEqual(piano.operazioni.filter((o) => o.tipo === 'filtro' && o.colonna === 'slug'), []);
  }
});

test('il flag non tocca le altre risorse', async () => {
  const { dip, spia } = dipendenze('bando_pubblico');
  await ELENCO_ARTICOLI.prepara(new URL('https://edunews24.it/api/v1/articles'), {}).produci(dip, ESECUZIONE);
  assert.equal(spia.piani[0]?.tabella, 'articles');
});

test('override svuotato: anche l\'API resta sulla tabella', async () => {
  // `BANDI_FONTE_LETTURA=` (definita ma vuota) deve valere quanto «non
  // impostata», qui come nelle pagine: è ciò che `??` garantisce e che un
  // «primo valore non vuoto» romperebbe, mandando la sola API sulla vista.
  assert.equal(nomeFonteBandiDa(''), 'bando');
  assert.equal(nomeFonteBandiDa('   '), 'bando');
  for (const piano of await pianiBandi(nomeFonteBandiDa(''))) {
    assert.equal(piano.tabella, 'bando');
    assert.deepEqual(
      piano.operazioni.filter((o) => o.tipo === 'filtro' && o.colonna === 'stato_processing'),
      [{ tipo: 'filtro', colonna: 'stato_processing', operatore: 'eq', valore: 'completed' }]);
  }
});

/** Sorgente senza commenti: le spiegazioni nominano le variabili. */
function sorgente(url: URL): string {
  return readFileSync(url, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
}

test('rotta.ts e supabase-bandi.ts leggono il flag con la stessa espressione', () => {
  // Il gate sta sul codice, non sui commenti: senza toglierli, una riga di
  // spiegazione che nomina `process.env.BANDI_FONTE_LETTURA` basterebbe a far
  // passare un file che legge solo la variabile compilata.
  const rotta = sorgente(new URL('../../src/lib/api-v1/rotta.ts', import.meta.url));
  const supabaseBandi = sorgente(new URL('../../src/lib/supabase-bandi.ts', import.meta.url));

  // Ordine obbligato: `BANDI_FONTE_LETTURA` vale a runtime ed è il ritorno
  // indietro senza ricostruire; `PUBLIC_*` è compilata da `npm run build`.
  // `??` e non un «primo valore non vuoto»: la stringa vuota deve vincere e
  // ricadere sul default, altrimenti le due superfici divergono sul vuoto.
  const espressione = (funzione: string) => new RegExp(
    `${funzione}\\(\\s*process\\.env\\.BANDI_FONTE_LETTURA\\s*\\?\\?`
    + '\\s*import\\.meta\\.env\\.PUBLIC_BANDI_FONTE_LETTURA\\s*,?\\s*\\)');
  assert.match(rotta, espressione('nomeFonteBandiDa'));
  assert.match(supabaseBandi, espressione('fonteBandiDa'));

  // Nessuno dei due deve filtrare il valore prima di passarlo.
  for (const [nome, codice] of [['rotta.ts', rotta], ['supabase-bandi.ts', supabaseBandi]] as const) {
    assert.equal(
      /(trim|primoValorizzato|\|\|)[^\n]*BANDI_FONTE_LETTURA|BANDI_FONTE_LETTURA[^\n]*(\.trim\(|\s\|\|\s)/.test(codice),
      false, `${nome}: il valore va passato grezzo a fonteBandiDa/nomeFonteBandiDa`);
    // Il default non si scrive a mano: lo danno le due funzioni (`bando`).
    assert.equal(/BANDI_FONTE_LETTURA[^\n]*\?\?\s*'bando'/.test(codice), false, `${nome}: default ricopiato a mano`);
  }
});
