/**
 * Le superfici pubbliche di un bando, viste da fuori: il Markdown che il
 * middleware serve agli agenti (`Accept: text/markdown`) e il JSON-LD che i
 * motori leggono.
 *
 * Perché serve un test a parte pur avendone uno per ogni modulo: il filtro sui
 * link è dentro `renderSezioni`, ma il Markdown lo ricava il middleware
 * convertendo l'HTML **già reso**, e il JSON-LD lo costruisce un altro modulo.
 * Un host di aggregatore che rientrasse da una di queste due strade non
 * comparirebbe in nessun test di unità. Qui si guarda solo il risultato finale.
 *
 * Nessun rendering di `.astro` sotto `node --test` (§16.3.8): si gira su
 * `htmlToMarkdown(renderSezioni(...))` e su `jsonLdBando`, che sono
 * esattamente ciò che la scheda passa al layout.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { DOMINI_AGGREGATORI } from '../../src/config/domini-aggregatori.ts';
import { renderSezioni } from '../../src/lib/bandi/contenuto.ts';
import { jsonLdBando } from '../../src/lib/bandi/jsonld.ts';
import { htmlToMarkdown } from '../../src/lib/markdown-negotiation.ts';

/** Un contenuto come quelli reali: testo utile e link all'aggregatore di origine. */
const CONTENUTO = {
  sections: [
    { type: 'h2', text: 'Come partecipare' },
    {
      type: 'paragraph',
      segments: [
        { kind: 'text', text: 'La domanda si presenta dalla ' },
        { kind: 'link', text: 'pagina ufficiale del bando', url: 'https://www.obiettivoeuropa.com/scheda/1120620' },
        { kind: 'text', text: ', entro il 31 ottobre.' },
      ],
    },
    {
      type: 'bullet_list',
      items: [
        { segments: [{ kind: 'link', text: 'Modulo A', url: 'https://fasi.eu/modulo-a' }] },
        { segments: [{ kind: 'link', text: 'Modulo B', url: 'https://regione.marche.it/modulo-b' }] },
      ],
    },
    {
      type: 'faq',
      items: [{
        question: 'Dove trovo il bando?',
        answer: 'Sul sito dell\'ente.',
      }],
    },
  ],
};

function nessunAggregatore(testo: string, etichetta: string): void {
  for (const host of DOMINI_AGGREGATORI) {
    assert.equal(testo.includes(host), false, `${etichetta}: compare ${host}`);
  }
}

test('Markdown per agenti: il testo resta, i link agli aggregatori no', () => {
  const markdown = htmlToMarkdown(renderSezioni(CONTENUTO));
  // Il contenuto utile non si perde: l'ancora degradata resta testo.
  assert.ok(markdown.includes('Come partecipare'));
  assert.ok(markdown.includes('pagina ufficiale del bando'));
  assert.ok(markdown.includes('entro il 31 ottobre'));
  assert.ok(markdown.includes('Modulo A'));
  // Il link su dominio ufficiale sopravvive come link.
  assert.ok(markdown.includes('https://regione.marche.it/modulo-b'));
  // Nessun URL di aggregatore, in nessuna forma (link markdown o testo nudo).
  nessunAggregatore(markdown, 'markdown');
  // La FAQ salvata con le chiavi vecchie arriva fino al Markdown.
  assert.ok(markdown.includes('Dove trovo il bando?'));
  assert.ok(markdown.includes('Sul sito dell\'ente.'));
});

test('Markdown per agenti: <main> non c\'è, non si perde il corpo', () => {
  // `renderSezioni` produce un frammento, non una pagina: htmlToMarkdown deve
  // ripiegare sull'intero documento invece di restituire il vuoto.
  const markdown = htmlToMarkdown(renderSezioni({
    sections: [{ type: 'paragraph', segments: [{ kind: 'text', text: 'Frammento senza main.' }] }],
  }));
  assert.ok(markdown.includes('Frammento senza main.'));
});

test('JSON-LD della scheda: nessun host di aggregatore, in F1 nessun sameAs', () => {
  const ld = jsonLdBando({
    urlCanonico: 'https://edunews24.it/bandi/italia-delle-donne',
    titolo: 'L\'Italia delle donne',
    descrizione: 'Contributi a fondo perduto.',
    enteErogatore: 'Dipartimento per le pari opportunità',
    areaGeografica: 'Nazionale',
    importoTotaleEur: 1_500_000,
    fonteUfficiale: null,
  });
  const serializzato = JSON.stringify(ld);
  nessunAggregatore(serializzato, 'json-ld');
  assert.equal(Object.hasOwn(ld.about as object, 'sameAs'), false);
  // Gli unici URL del JSON-LD sono nostri, piu' il vocabolario schema.org
  // (`@context` e il logo dell'editore, che e' comunque su edunews24.it).
  const ammessi = new Set(['edunews24.it', 'schema.org']);
  for (const trovato of serializzato.matchAll(/https?:\/\/[^"]+/g)) {
    assert.ok(ammessi.has(new URL(trovato[0]).hostname), trovato[0]);
  }
});

test('nessuna superficie linka l\'aggregatore nemmeno se glielo si passa', () => {
  // Il caso peggiore: il resolver ha marcato «trovata» una fonte su un
  // aggregatore. La cintura di `urlPubblicabile` scatta lo stesso, in entrambe
  // le superfici.
  const ld = jsonLdBando({
    urlCanonico: 'https://edunews24.it/bandi/x',
    titolo: 'X',
    fonteUfficiale: {
      stato: 'trovata', url: 'https://www.obiettivoeuropa.com/scheda/1',
      host: 'obiettivoeuropa.com', tipo: 'ente',
    },
  });
  nessunAggregatore(JSON.stringify(ld), 'json-ld con fonte sporca');
  nessunAggregatore(
    htmlToMarkdown(renderSezioni({
      sections: [{
        type: 'paragraph',
        segments: [{ kind: 'link', text: 'Vai', url: 'https://ticonsiglio.com/bando' }],
      }],
    })),
    'markdown con link sporco',
  );
});
