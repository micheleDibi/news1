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
    '<a href="https://regione.marche.it/b" class="text-blue-700 hover:underline" ' +
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
  assert.ok(html.includes('<details class="bg-gray-50 rounded-lg p-4 group">'));
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
  assert.ok(html.includes('<h2 class="text-2xl font-bold text-gray-900 mt-8 mb-3">Requisiti &amp; limiti</h2>'));
  assert.ok(html.includes('<h3 class="text-xl font-semibold text-gray-900 mt-6 mb-2">Sottotitolo</h3>'));
  assert.ok(html.includes('<p class="text-gray-700 leading-relaxed mb-4">Paragrafo.</p>'));
  assert.ok(html.includes('<ul class="list-disc list-inside space-y-2 mb-4 text-gray-700"><li>Primo</li></ul>'));
  assert.ok(html.includes('<ol class="list-decimal list-inside space-y-2 mb-4 text-gray-700"><li>Uno</li></ol>'));
  assert.equal(html.includes('ignorata'), false);
});
