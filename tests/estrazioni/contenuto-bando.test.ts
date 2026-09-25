/**
 * `src/lib/bandi/contenuto.ts`: i tre bug che il rendering del corpo aveva.
 *
 * Ogni test qui fallirebbe sul codice precedente (`renderSegments` e il blocco
 * `sections.map` dentro `[slug].astro`): i link non erano filtrati, le FAQ
 * erano lette con le chiavi sbagliate e un `contenuto` stringa o malformato
 * faceva saltare la scheda.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  corpoBando, renderSegmenti, renderSezioni, scappa, sezioniDa, vociFaq,
} from '../../src/lib/bandi/contenuto.ts';

const paragrafo = (segments: unknown): unknown => ({ sections: [{ type: 'paragraph', segments }] });

test('scappa: le cinque entità, anche negli attributi', () => {
  assert.equal(scappa('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
});

test('segmenti link: link solo se pubblicabile, altrimenti testo semplice', () => {
  const ufficiale = renderSegmenti([{ kind: 'link', text: 'Bando', url: 'https://regione.marche.it/b' }]);
  assert.equal(
    ufficiale,
    '<a href="https://regione.marche.it/b" class="text-primary underline underline-offset-2 hover:text-primary-dark" ' +
    'target="_blank" rel="noopener noreferrer nofollow">Bando</a>',
  );
  // rel: nofollow oltre a noopener/noreferrer. Prima mancava.
  assert.ok(ufficiale.includes('nofollow'));

  // Aggregatore: resta testo. Sul codice precedente erano 115 schede con il link.
  assert.equal(
    renderSegmenti([{ kind: 'link', text: 'Scheda', url: 'https://www.obiettivoeuropa.com/x' }]),
    'Scheda',
  );
  // javascript: `escapeAttr` non lo fermava.
  assert.equal(renderSegmenti([{ kind: 'link', text: 'Clicca', url: 'javascript:alert(1)' }]), 'Clicca');
  // URL mancante.
  assert.equal(renderSegmenti([{ kind: 'link', text: 'Senza' }]), 'Senza');
});

test('segmenti: bold, testo, escape e forme inservibili', () => {
  assert.equal(renderSegmenti([{ kind: 'bold', text: 'Importi' }]), '<strong>Importi</strong>');
  assert.equal(renderSegmenti([{ kind: 'text', text: 'a < b & "c"' }]), 'a &lt; b &amp; &quot;c&quot;');
  assert.equal(renderSegmenti([{ kind: 'link', text: '<img>', url: 'https://x.esempio.it/"onload' }])
    .includes('<img>'), false);
  assert.equal(renderSegmenti(null), '');
  assert.equal(renderSegmenti('non un array'), '');
  assert.equal(renderSegmenti([{ kind: 'text' }]), '');
});

test('FAQ: forma dichiarata {q, a.segments} e tolleranza {question, answer}', () => {
  assert.deepEqual(
    vociFaq([{ q: 'Chi può partecipare?', a: { segments: [{ kind: 'text', text: 'Le PMI.' }] } }]),
    [{ q: 'Chi può partecipare?', a: { segments: [{ kind: 'text', text: 'Le PMI.' }] } }],
  );
  // Le 23 schede salvate con le chiavi vecchie: prima rendevano accordion vuoti.
  assert.deepEqual(
    vociFaq([{ question: 'Quando scade?', answer: 'Il 31 ottobre.' }]),
    [{ q: 'Quando scade?', a: { segments: [{ kind: 'text', text: 'Il 31 ottobre.' }] } }],
  );
  // `a` stringa invece che oggetto.
  assert.deepEqual(vociFaq([{ q: 'Dove?', a: 'Online.' }])[0].a.segments, [{ kind: 'text', text: 'Online.' }]);
  // Senza domanda o senza risposta la voce sparisce, non diventa un vuoto.
  assert.deepEqual(vociFaq([{ q: '', a: 'x' }, { q: 'y', a: '' }, { q: 'z' }]), []);
  assert.deepEqual(vociFaq(null), []);
});

test('FAQ rese: accordion con la domanda e la risposta, link filtrati', () => {
  const html = renderSezioni({
    sections: [{
      type: 'faq',
      items: [{ question: 'Come si presenta?', answer: 'Dal portale.' }],
    }],
  });
  assert.ok(html.includes('<details class="group border-b border-[#e3e7ee]">'));
  assert.ok(html.includes('Come si presenta?'));
  assert.ok(html.includes('Dal portale.'));
  // Nessun FAQPage e nessun marcatore di dati strutturati nel corpo.
  assert.equal(html.includes('ld+json'), false);

  const conLink = renderSezioni({
    sections: [{
      type: 'faq',
      items: [{ q: 'Dove?', a: { segments: [{ kind: 'link', text: 'Qui', url: 'https://fasi.eu/x' }] } }],
    }],
  });
  assert.equal(conLink.includes('fasi.eu'), false);
  assert.ok(conLink.includes('Qui'));

  // Una sezione faq senza voci utilizzabili non lascia un contenitore vuoto.
  assert.equal(renderSezioni({ sections: [{ type: 'faq', items: [{ q: '' }] }] }), '');
});

test('contenuto stringa: parse guardato; malformato: corpo vuoto e avviso', () => {
  const comeStringa = JSON.stringify(paragrafo([{ kind: 'text', text: 'Testo dal JSON.' }]));
  assert.ok(renderSezioni(comeStringa).includes('Testo dal JSON.'));
  assert.equal(corpoBando(comeStringa).avviso, null);

  // JSON rotto: prima `contenuto?.sections` dava undefined e la pagina restava
  // muta; ora la scheda resta 200 e dichiara che il testo manca.
  assert.equal(renderSezioni('{ non json'), '');
  assert.ok((corpoBando('{ non json').avviso ?? '').includes('non è al momento disponibile'));

  // Oggetto senza `sections`, o con `sections` non array.
  assert.equal(renderSezioni({ testo: 'x' }), '');
  assert.equal(renderSezioni({ sections: 'x' }), '');
  assert.equal(renderSezioni(42), '');
  assert.deepEqual(sezioniDa({ sections: [{ testo: 'senza type' }] }), []);

  // Senza contenuto non c'è niente da avvisare: è il caso normale di molte righe.
  assert.equal(corpoBando(null).avviso, null);
  assert.equal(corpoBando(undefined).avviso, null);
});

test('corpoBando: l\'avviso segue il corpo reso, non il numero di sezioni', () => {
  // Sezioni presenti ma che non rendono niente: prima erano «corpo vuoto E
  // nessun avviso», cioè la pagina muta che il modulo esiste per chiudere.
  for (const contenuto of [
    { sections: [{ type: 'paragraph', segments: [] }] },
    { sections: [{ type: 'faq', items: [{ q: '' }] }] },
    { sections: [{ type: 'sconosciuto', text: 'x' }] },
  ]) {
    const corpo = corpoBando(contenuto);
    assert.equal(corpo.html, '', JSON.stringify(contenuto));
    assert.ok((corpo.avviso ?? '').includes('non è al momento disponibile'), JSON.stringify(contenuto));
  }
  // Corpo reso: nessun avviso.
  const pieno = corpoBando(paragrafo([{ kind: 'text', text: 'Il testo c\'è.' }]));
  assert.ok(pieno.html.includes('Il testo c'));
  assert.equal(pieno.avviso, null);
  // Il corpo è esattamente quello di renderSezioni: una sola sorgente di verità.
  assert.equal(pieno.html, renderSezioni(paragrafo([{ kind: 'text', text: 'Il testo c\'è.' }])));
});

test('corpo: markup e classi delle sezioni', () => {
  const html = renderSezioni({
    sections: [
      { type: 'h2', text: 'Requisiti & limiti' },
      { type: 'h3', text: 'Sottotitolo' },
      { type: 'paragraph', segments: [{ kind: 'text', text: 'Paragrafo.' }] },
      { type: 'bullet_list', items: [{ segments: [{ kind: 'text', text: 'Primo' }] }] },
      { type: 'numbered_list', items: [{ segments: [{ kind: 'text', text: 'Uno' }] }] },
      { type: 'sconosciuto', text: 'ignorata' },
    ],
  });
  assert.ok(html.includes(
    '<h2 id="requisiti-limiti" class="mt-11 mb-3 flex scroll-mt-4 items-baseline gap-3 font-heading text-[26px] font-bold tracking-[-.01em] text-[#0a2244] first:mt-0 [counter-increment:sezione] before:font-semibold before:text-[14px] before:tabular-nums before:text-[#004e9c] before:content-[counter(sezione,decimal-leading-zero)]">' +
    'Requisiti &amp; limiti</h2>',
  ));
  assert.ok(html.includes('<h3 class="mt-8 mb-2 font-heading text-[20px] font-semibold text-[#0a2244] first:mt-0">Sottotitolo</h3>'));
  assert.ok(html.includes('<p class="mt-4 first:mt-0 [h2+&]:mt-0 [h3+&]:mt-0">Paragrafo.</p>'));
  assert.ok(html.includes(
    '<ul class="mt-3 flex list-disc flex-col gap-2 pl-[22px] first:mt-0"><li>Primo</li></ul>',
  ));
  assert.ok(html.includes(
    '<ol class="mt-3 flex list-decimal flex-col gap-2 pl-[22px] first:mt-0"><li>Uno</li></ol>',
  ));
  assert.equal(html.includes('ignorata'), false);
});

test('corpo: id degli H2 per l\'indice, con accenti, collisioni e testo vuoto', () => {
  const html = renderSezioni({
    sections: [
      { type: 'h2', text: 'Perché partecipare? Città e comunità' },
      { type: 'h2', text: 'FAQ' },
      { type: 'h2', text: 'FAQ 2' },
      { type: 'h2', text: 'FAQ' },
      { type: 'h3', text: 'FAQ' },
      { type: 'h2', text: '—' },
      { type: 'h2' },
      { type: 'h2', text: 'Valle d\'Aosta/Vallée d\'Aoste' },
    ],
  });
  const id = [...html.matchAll(/<h2 id="([^"]*)"/g)].map((m) => m[1]);
  assert.deepEqual(id, [
    'perche-partecipare-citta-e-comunita',
    'faq',
    // Contare le occorrenze per slug darebbe `faq-2` due volte: si prova il
    // primo suffisso libero.
    'faq-2',
    'faq-3',
    'sezione',
    'sezione-2',
    'valle-d-aosta-vallee-d-aoste',
  ]);
  // Gli H3 non hanno ancora e non consumano suffissi.
  assert.ok(html.includes('<h3 class="mt-8 mb-2 font-heading text-[20px] font-semibold text-[#0a2244] first:mt-0">FAQ</h3>'));
  // Ogni id è un segmento valido: niente da scappare nell'attributo.
  for (const valore of id) assert.match(valore, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
  // Due rese dello stesso contenuto danno gli stessi id: l'indice può contarci.
  assert.equal(renderSezioni({ sections: [{ type: 'h2', text: 'In breve' }] }).includes('id="in-breve"'), true);
});
