/**
 * testo.ts: testo semplice, URL esterni, sintesi da markdown, elenchi.
 * La suite gira con TZ=Asia/Kathmandu come le altre di api-v1 (qui nessuna data).
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizzaTestoSemplice, pulisciElenco, pulisciTesto, rimuoviUrlEsterni, sintesiDaMarkdown, pulisciTestoMarkdown,
} from '../../src/lib/api-v1/testo.ts';

const SURROGATO_SPAIATO = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** Frase di riempimento senza punti, di almeno `lunghezza` caratteri, che finisce con una parola. */
function riempitivo(lunghezza: number): string {
  const parole = ['docenti', 'graduatorie', 'supplenze', 'scuola', 'ministero', 'concorso', 'ruolo', 'sede'];
  let testo = '';
  for (let i = 0; testo.length < lunghezza; i++) testo += (testo === '' ? '' : ' ') + parole[i % parole.length];
  return testo;
}

// ---------------------------------------------------------------------------
// normalizzaTestoSemplice
// ---------------------------------------------------------------------------

test('normalizzaTestoSemplice: commenti HTML', () => {
  assert.equal(normalizzaTestoSemplice('a<!-- nota -->b'), 'ab');
  assert.equal(normalizzaTestoSemplice('a <!-- su\npiu\' righe --> b'), 'a b');
  assert.equal(normalizzaTestoSemplice('<!-- a --><!-- b -->testo<!---->'), 'testo');
  assert.equal(normalizzaTestoSemplice('<!-- <b>dentro</b> -->fuori'), 'fuori');
  // senza chiusura resta testo
  assert.equal(normalizzaTestoSemplice('prima <!-- mai chiuso'), 'prima <!-- mai chiuso');
});

test('normalizzaTestoSemplice: entita\' nominate in un solo passaggio', () => {
  assert.equal(normalizzaTestoSemplice('Universit&agrave; &Egrave; perch&eacute;'), 'Università È perché');
  assert.equal(normalizzaTestoSemplice('&laquo;Bando&raquo; &ndash; 5&euro; &hellip; 30&deg;'), '«Bando» – 5€ … 30°');
  assert.equal(normalizzaTestoSemplice('&ldquo;x&rdquo; &lsquo;y&rsquo; &quot;z&quot; &apos;w&apos; a&mdash;b'), '“x” ‘y’ "z" \'w\' a—b');
  assert.equal(normalizzaTestoSemplice('A&amp;B'), 'A&B');
  assert.equal(normalizzaTestoSemplice('&amp;lt;'), '&lt;');
  assert.equal(normalizzaTestoSemplice('&amp;amp;'), '&amp;');
  assert.equal(normalizzaTestoSemplice('&amp;lt;b&amp;gt;resta&amp;lt;/b&amp;gt;'), '&lt;b&gt;resta&lt;/b&gt;');
  // sconosciute, senza punto e virgola, maiuscole sbagliate: invariate
  assert.equal(normalizzaTestoSemplice('&foo; &amp &AMP; &Nbsp;'), '&foo; &amp &AMP; &Nbsp;');
  // nbsp e' uno spazio da collassare
  assert.equal(normalizzaTestoSemplice('a&nbsp;&nbsp; b'), 'a b');
});

test('normalizzaTestoSemplice: entita\' numeriche valide e non valide', () => {
  assert.equal(normalizzaTestoSemplice('&#65;&#x41;&#X41;&#0065;'), 'AAAA');
  assert.equal(normalizzaTestoSemplice('&#128512; &#x1F600;'), '😀 😀');
  assert.equal(normalizzaTestoSemplice('&#224;'), 'à');
  // non valide: restano invariate
  assert.equal(normalizzaTestoSemplice('&#0;'), '&#0;');
  assert.equal(normalizzaTestoSemplice('&#x0;'), '&#x0;');
  assert.equal(normalizzaTestoSemplice('&#xD800;'), '&#xD800;');
  assert.equal(normalizzaTestoSemplice('&#xDFFF;'), '&#xDFFF;');
  assert.equal(normalizzaTestoSemplice('&#55296;'), '&#55296;');
  assert.equal(normalizzaTestoSemplice('&#x110000;'), '&#x110000;');
  assert.equal(normalizzaTestoSemplice('&#1114112;'), '&#1114112;');
  assert.equal(normalizzaTestoSemplice('&#99999999999999999999;'), '&#99999999999999999999;');
  // il massimo valido
  assert.equal(normalizzaTestoSemplice('&#x10FFFF;'), '\u{10FFFF}');
  // 0x80-0x9F letti in windows-1252 come fanno i browser
  assert.equal(normalizzaTestoSemplice('l&#146;anno &#150; &#x80;'), 'l’anno – €');
  // un controllo decodificato viene poi rimosso; tab e a capo diventano spazio
  assert.equal(normalizzaTestoSemplice('a&#1;b&#x81;c'), 'abc');
  assert.equal(normalizzaTestoSemplice('a&#9;b&#10;c'), 'a b c');
});

test('normalizzaTestoSemplice: tag reali via dopo la decodifica, testo con < intatto', () => {
  assert.equal(normalizzaTestoSemplice('&lt;script&gt;alert(1)&lt;/script&gt;'), 'alert(1)');
  assert.equal(normalizzaTestoSemplice('&#60;script&#62;x&#60;/script&#62;'), 'x');
  assert.equal(normalizzaTestoSemplice('<< Addetti >>'), '<< Addetti >>');
  assert.equal(normalizzaTestoSemplice('&lt;&lt; Addetti &gt;&gt;'), '<< Addetti >>');
  assert.equal(normalizzaTestoSemplice('voto < 6 e > 4'), 'voto < 6 e > 4');
  assert.equal(normalizzaTestoSemplice('x <- y, <3, a<5'), 'x <- y, <3, a<5');
  assert.equal(normalizzaTestoSemplice('accumulata.<br><br>Dal'), 'accumulata. Dal');
  assert.equal(normalizzaTestoSemplice('</summary>'), '');
  assert.equal(normalizzaTestoSemplice('a<b>grassetto</b>c'), 'a grassetto c');
  assert.equal(normalizzaTestoSemplice('<p class="lead" data-x=\'1\'>Testo</p>'), 'Testo');
  assert.equal(normalizzaTestoSemplice('riga<br/>riga<br />riga'), 'riga riga riga');
  assert.equal(normalizzaTestoSemplice('<img src="a.png" alt="x"/>'), '');
  assert.equal(normalizzaTestoSemplice('<my-tag>ok</my-tag>'), 'ok');
  assert.equal(normalizzaTestoSemplice('<a href="https://x.it">bando</a>'), 'bando');
});

test('normalizzaTestoSemplice: controlli, spazi e surrogati', () => {
  assert.equal(normalizzaTestoSemplice('a\u0000b\u0007c\u001Fd\u007Fe\u009Ff'), 'abcdef');
  assert.equal(normalizzaTestoSemplice('a\tb\nc\r\nd\re\u000Bf\u000Cg'), 'a b c d e f g');
  assert.equal(normalizzaTestoSemplice('a\u0085b\u2028c\u2029d'), 'a b c d');
  assert.equal(normalizzaTestoSemplice('a\u00A0\u00A0 b\u2009c\u3000d'), 'a b c d');
  assert.equal(normalizzaTestoSemplice('\uFEFFinizio\u200B fine\u00AD'), 'inizio fine');
  assert.equal(normalizzaTestoSemplice('   spazi   ai   bordi   '), 'spazi ai bordi');
  // surrogati spaiati via, coppie valide intatte
  assert.equal(normalizzaTestoSemplice('x\uD800y'), 'xy');
  assert.equal(normalizzaTestoSemplice('x\uDC00y'), 'xy');
  assert.equal(normalizzaTestoSemplice('x😀y'), 'x😀y');
  assert.equal(normalizzaTestoSemplice('\uD83D😀'), '😀');
  assert.equal(normalizzaTestoSemplice('😀\uDE00'), '😀');
  assert.equal(normalizzaTestoSemplice('fine\uD83D'), 'fine');
  // emoji composte (ZWJ) intatte
  assert.equal(normalizzaTestoSemplice('👩\u200D🏫 docente'), '👩\u200D🏫 docente');
  assert.equal(normalizzaTestoSemplice(''), '');
});

// ---------------------------------------------------------------------------
// rimuoviUrlEsterni
// ---------------------------------------------------------------------------

test('rimuoviUrlEsterni: URL nudi esterni -> nome host', () => {
  assert.equal(rimuoviUrlEsterni('Candidature su www.inpa.gov.it.'), 'Candidature su inpa.gov.it.');
  assert.equal(rimuoviUrlEsterni('(https://www.istruzione.it/esame_di_stato/)'), '(istruzione.it)');
  assert.equal(rimuoviUrlEsterni('Sito: HTTPS://WWW.Esteri.IT/'), 'Sito: esteri.it');
  assert.equal(
    rimuoviUrlEsterni('Fonti: https://a.example.it/x, https://www.b.example.it/y; www.c.example.it!'),
    'Fonti: a.example.it, b.example.it; c.example.it!',
  );
  assert.equal(rimuoviUrlEsterni('«https://www.mim.gov.it/bandi»'), '«mim.gov.it»');
  assert.equal(rimuoviUrlEsterni('"https://www.mim.gov.it/bandi"'), '"mim.gov.it"');
  assert.equal(rimuoviUrlEsterni('porta https://x.example.it:8443/a?b=1#c fine'), 'porta x.example.it fine');
  assert.equal(rimuoviUrlEsterni('credenziali https://edunews24.it@evil.example/x'), 'credenziali evil.example');
  // host che somigliano a edunews24.it ma sono esterni
  assert.equal(rimuoviUrlEsterni('vedi https://edunews24.it.evil.example/x'), 'vedi edunews24.it.evil.example');
  assert.equal(rimuoviUrlEsterni('vedi https://notedunews24.it/x'), 'vedi notedunews24.it');
  // lo schema attaccato a una parola non lascia passare il link
  assert.equal(rimuoviUrlEsterni('vedihttps://x.example.it/a'), 'vedix.example.it');
});

test('rimuoviUrlEsterni: link e immagini markdown, autolink', () => {
  assert.equal(rimuoviUrlEsterni('Scarica il [bando](https://www.inpa.gov.it/bandi/1).'), 'Scarica il bando.');
  assert.equal(rimuoviUrlEsterni('Vedi ![foto](https://x.example.it/a.png) qui'), 'Vedi qui');
  assert.equal(rimuoviUrlEsterni('[pagina](https://it.wikipedia.org/wiki/Scuola_(Italia)) fine'), 'pagina fine');
  assert.equal(rimuoviUrlEsterni('[titolo](https://x.it/a "Titolo del link")'), 'titolo');
  assert.equal(rimuoviUrlEsterni('[interno](https://edunews24.it/scuola/x)'), 'interno');
  assert.equal(rimuoviUrlEsterni('Vedi <https://www.inpa.gov.it/x>.'), 'Vedi inpa.gov.it.');
  assert.equal(rimuoviUrlEsterni('Vedi <www.inpa.gov.it>'), 'Vedi inpa.gov.it');
});

test('rimuoviUrlEsterni: un valore fatto solo di un URL esterno -> null', () => {
  assert.equal(rimuoviUrlEsterni('https://web.spaggiari.eu/sdg2/Documenti/GOME0015/208012662'), null);
  assert.equal(rimuoviUrlEsterni('  https://web.spaggiari.eu/sdg2/Documenti/GOME0015/208012662  '), null);
  assert.equal(rimuoviUrlEsterni('HTTPS://WWW.Esteri.IT/'), null);
  assert.equal(rimuoviUrlEsterni('www.inpa.gov.it'), null);
  assert.equal(rimuoviUrlEsterni('https://www.inpa.gov.it/.'), null);
  assert.equal(rimuoviUrlEsterni('<https://web.spaggiari.eu/x>'), null);
  assert.equal(rimuoviUrlEsterni('[https://www.inpa.gov.it](https://www.inpa.gov.it)'), null);
  assert.equal(rimuoviUrlEsterni('https://ex%22ample.com/x'), null);
  // un URL interno da solo resta
  assert.equal(rimuoviUrlEsterni('https://edunews24.it/scuola/x'), 'https://edunews24.it/scuola/x');
});

test('rimuoviUrlEsterni: URL di edunews24.it invariati', () => {
  assert.equal(
    rimuoviUrlEsterni('Leggi https://edunews24.it/scuola/supplenze-2026.'),
    'Leggi https://edunews24.it/scuola/supplenze-2026.',
  );
  assert.equal(rimuoviUrlEsterni('Leggi https://www.edunews24.it/a e poi'), 'Leggi https://www.edunews24.it/a e poi');
  assert.equal(rimuoviUrlEsterni('Link https://linkinbio.edunews24.it/x'), 'Link https://linkinbio.edunews24.it/x');
  assert.equal(rimuoviUrlEsterni('Maiuscole HTTPS://EDUNEWS24.IT/Scuola'), 'Maiuscole HTTPS://EDUNEWS24.IT/Scuola');
});

test('rimuoviUrlEsterni: menzioni che non sono link restano', () => {
  assert.equal(rimuoviUrlEsterni('protocollo@pec.regione.vda.it'), 'protocollo@pec.regione.vda.it');
  assert.equal(rimuoviUrlEsterni('Scrivere a protocollo@pec.regione.vda.it entro'), 'Scrivere a protocollo@pec.regione.vda.it entro');
  assert.equal(rimuoviUrlEsterni('mario@www.example.it'), 'mario@www.example.it');
  assert.equal(rimuoviUrlEsterni('7zip.com'), '7zip.com');
  assert.equal(rimuoviUrlEsterni('HTTP/2'), 'HTTP/2');
  assert.equal(rimuoviUrlEsterni('foo.www.example.it'), 'foo.www.example.it');
  assert.equal(rimuoviUrlEsterni('ftp://x.example.it'), 'ftp://x.example.it');
});

test('rimuoviUrlEsterni: URL non analizzabile rimosso, spazi collassati', () => {
  assert.equal(rimuoviUrlEsterni('Link https://ex%22ample.com/x fine'), 'Link fine');
  assert.equal(rimuoviUrlEsterni('Link https://ex&ample.com/x, fine'), 'Link , fine');
  assert.equal(rimuoviUrlEsterni('Link: https://[x/ poi'), 'Link: poi');
  assert.equal(rimuoviUrlEsterni('  a   b  '), 'a b');
  assert.equal(rimuoviUrlEsterni(''), '');
});

// ---------------------------------------------------------------------------
// pulisciTesto
// ---------------------------------------------------------------------------

test('pulisciTesto: non stringa, vuoto, solo markup o solo URL esterno -> null', () => {
  for (const v of [null, undefined, 42, true, {}, ['a'], '', '   ', '<p></p>', '<!-- x -->', '&nbsp;']) {
    assert.equal(pulisciTesto(v), null, `atteso null per ${JSON.stringify(v)}`);
  }
  assert.equal(pulisciTesto('https://web.spaggiari.eu/sdg2/Documenti/GOME0015/208012662'), null);
  assert.equal(pulisciTesto('&lt;https://www.inpa.gov.it&gt;'), null);
  assert.equal(pulisciTesto('<a href="https://x.it">https://web.spaggiari.eu/x</a>'), null);
});

test('pulisciTesto: catena completa', () => {
  assert.equal(
    pulisciTesto('  Testo &amp; <b>altro</b> su https://www.inpa.gov.it/bandi  '),
    'Testo & altro su inpa.gov.it',
  );
  assert.equal(pulisciTesto('&lt;a href="https://x.it"&gt;bando&lt;/a&gt;'), 'bando');
  assert.equal(pulisciTesto('&lt;script&gt;alert(1)&lt;/script&gt;'), 'alert(1)');
  assert.equal(pulisciTesto('<< Addetti >> alle pulizie'), '<< Addetti >> alle pulizie');
  assert.equal(pulisciTesto('Interpello\u00A0docenti\nclasse A022'), 'Interpello docenti classe A022');
});

// ---------------------------------------------------------------------------
// sintesiDaMarkdown
// ---------------------------------------------------------------------------

test('sintesiDaMarkdown: markdown rimosso e paragrafi uniti', () => {
  const md = [
    '# Supplenze 2026/27',
    '',
    'Gli **uffici scolastici** hanno _avviato_ le convocazioni.',
    '',
    '## Cosa sapere ##',
    '',
    '- primo punto',
    '* secondo punto',
    '+ terzo punto',
    '1. quarto',
    '2) quinto',
    '- [x] fatto',
    '',
    '> Una citazione',
    '> > annidata',
    '',
    '---',
    '***',
    '___',
    '',
    'Codice `inline` e ``doppio``.',
    '```js',
    'blocco',
    '```',
    '~~~',
    'tilde',
    '~~~',
    '',
    'Titolo setext',
    '=============',
    '',
    '***Entrambi*** e __forte__ e *corsivo* e ~~barrato~~.',
  ].join('\n');
  assert.equal(
    sintesiDaMarkdown(md, 600),
    'Supplenze 2026/27. Gli uffici scolastici hanno avviato le convocazioni. Cosa sapere. primo punto '
      + 'secondo punto terzo punto quarto quinto fatto Una citazione annidata Codice inline e doppio. '
      + 'blocco tilde Titolo setext Entrambi e forte e corsivo e barrato.',
  );
});

test('sintesiDaMarkdown: enfasi solo ai bordi di parola, niente falsi positivi', () => {
  assert.equal(sintesiDaMarkdown('esame_di_stato e snake_case_name', 600), 'esame_di_stato e snake_case_name');
  assert.equal(sintesiDaMarkdown('2*3*4 e 5 * 3 * 2', 600), '2*3*4 e 5 * 3 * 2');
  assert.equal(sintesiDaMarkdown('#hashtag resta', 600), '#hashtag resta');
  assert.equal(sintesiDaMarkdown('- **Requisiti:** laurea', 600), 'Requisiti: laurea');
  assert.equal(sintesiDaMarkdown('prezzo *scontato* del 5%', 600), 'prezzo scontato del 5%');
});

test('sintesiDaMarkdown: link, immagini, definizioni e URL esterni', () => {
  assert.equal(
    sintesiDaMarkdown('Leggi il [bando](https://www.inpa.gov.it/x) ![img](https://x.it/a.png)\n\n[1]: https://x.it/nota', 600),
    'Leggi il bando',
  );
  assert.equal(sintesiDaMarkdown('Info su https://www.istruzione.it/esame_di_stato/ e basta.', 600), 'Info su istruzione.it e basta.');
  assert.equal(sintesiDaMarkdown('[Nota]: il bando scade oggi', 600), '[Nota]: il bando scade oggi');
  assert.equal(sintesiDaMarkdown('https://web.spaggiari.eu/sdg2/Documenti/GOME0015/208012662', 600), null);
  assert.equal(sintesiDaMarkdown('![solo immagine](https://x.it/a.png)', 600), null);
});

test('sintesiDaMarkdown: HTML ed entita\'', () => {
  assert.equal(sintesiDaMarkdown('accumulata.<br><br>Dal', 600), 'accumulata. Dal');
  assert.equal(sintesiDaMarkdown('</summary>', 600), null);
  assert.equal(sintesiDaMarkdown('<summary>Testo</summary>', 600), 'Testo');
  assert.equal(sintesiDaMarkdown('Prima&nbsp;riga\r\n\r\nSeconda &amp; terza', 600), 'Prima riga Seconda & terza');
  assert.equal(sintesiDaMarkdown('&lt;script&gt;alert(1)&lt;/script&gt;', 600), 'alert(1)');
});

test('sintesiDaMarkdown: non stringa o vuoto -> null; massimo non valido -> RangeError', () => {
  for (const v of [null, undefined, 42, {}, '', '   ', '\n\n', '---', '<p></p>']) {
    assert.equal(sintesiDaMarkdown(v, 600), null, `atteso null per ${JSON.stringify(v)}`);
  }
  assert.throws(() => sintesiDaMarkdown('x', 1), RangeError);
  assert.throws(() => sintesiDaMarkdown('x', 0), RangeError);
  assert.throws(() => sintesiDaMarkdown('x', 10.5), RangeError);
  assert.throws(() => sintesiDaMarkdown('x', Number.NaN), RangeError);
});

test('sintesiDaMarkdown: sotto il massimo nessun taglio', () => {
  const testo = `${riempitivo(595)}.`;
  assert.ok(testo.length <= 600);
  assert.equal(sintesiDaMarkdown(testo, 600), testo);
  const esatto = 'a'.repeat(600);
  assert.equal(sintesiDaMarkdown(esatto, 600), esatto);
});

test('sintesiDaMarkdown: taglio all\'ultimo fine frase in [massimo/2, massimo]', () => {
  const prima = `Prima ${riempitivo(340)}.`;
  const seconda = ` Seconda ${riempitivo(150)}!`;
  const terza = ` Terza ${riempitivo(300)}.`;
  const testo = prima + seconda + terza;
  assert.ok((prima + seconda).length <= 600 && (prima + seconda + terza).length > 600);
  assert.equal(sintesiDaMarkdown(testo, 600), prima + seconda);

  // chiusure dopo la punteggiatura e virgolette d'apertura dopo lo spazio
  const citazione = `«Prima ${riempitivo(340)}.» «Poi ${riempitivo(400)}`;
  assert.equal(sintesiDaMarkdown(citazione, 600), `«Prima ${riempitivo(340)}.»`);
  const domanda = `Prima ${riempitivo(340)}?" "Poi ${riempitivo(400)}`;
  assert.equal(sintesiDaMarkdown(domanda, 600), `Prima ${riempitivo(340)}?"`);
  const puntini = `Prima ${riempitivo(340)}… Poi ${riempitivo(400)}`;
  assert.equal(sintesiDaMarkdown(puntini, 600), `Prima ${riempitivo(340)}…`);

  // fine frase esattamente a `massimo`
  const alLimite = `${'Prima ' + riempitivo(580)}`.slice(0, 599).trimEnd();
  const conPunto = `${alLimite}${'x'.repeat(599 - alLimite.length)}.`;
  assert.equal(conPunto.length, 600);
  assert.equal(sintesiDaMarkdown(`${conPunto} Dopo ${riempitivo(50)}`, 600), conPunto);
});

test('sintesiDaMarkdown: un fine frase prima di massimo/2 non basta -> ultimo spazio e …', () => {
  const testo = `Breve frase iniziale. ${riempitivo(800)}`;
  const esito = sintesiDaMarkdown(testo, 600);
  assert.ok(esito !== null);
  assert.ok(esito.endsWith('…'));
  assert.ok(esito.length <= 600);
  const senzaPuntini = esito.slice(0, -1);
  assert.ok(testo.startsWith(senzaPuntini));
  assert.equal(testo[senzaPuntini.length], ' ', 'il taglio cade su uno spazio');
  // e' l'ULTIMO spazio entro massimo-1
  assert.equal(senzaPuntini.length, testo.lastIndexOf(' ', 599));
});

test('sintesiDaMarkdown: abbreviazioni e numeri non sono fine frase', () => {
  const prima = `Prima ${riempitivo(320)}.`;
  const abbreviazioni = ' Lo dice il D.Lgs. Nel testo il prof. Rossi e il dott. Bianchi, con il sig. Verdi e '
    + 'l\'on. Neri, citano l\'art. Unico, il D.L. Sostegni, la L. Madia, il n. IV, pag. XII, es. Roma ecc. '
    + 'Poi art. 5, D.Lgs. 81/2008, comma 3.5 e 1.500 euro';
  const testo = prima + abbreviazioni + ' ' + riempitivo(300);
  assert.ok((prima + abbreviazioni).length < 600, 'le abbreviazioni cadono nella finestra di taglio');
  assert.equal(sintesiDaMarkdown(testo, 600), prima);

  // senza alcun fine frase valido si taglia allo spazio, mai dentro "3.5" o "1.500"
  const numeri = `${riempitivo(250)} art. 5 e 3.5 e 1.500 e D.Lgs. 81/2008 ${riempitivo(600)}`;
  const esito = sintesiDaMarkdown(numeri, 600);
  assert.ok(esito !== null && esito.endsWith('…'));
  assert.ok(esito.includes('art. 5 e 3.5 e 1.500 e D.Lgs. 81/2008'));
});

test('sintesiDaMarkdown: un decimale seguito da fine frase chiude la frase', () => {
  const prima = `Prima ${riempitivo(320)} versione 3.5.`;
  const testo = `${prima} Poi ${riempitivo(400)}`;
  assert.equal(sintesiDaMarkdown(testo, 600), prima);
});

test('sintesiDaMarkdown: summary di 700 caratteri con URL, taglio calcolato dopo la sostituzione', () => {
  const url = `https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id=${'a1b2c3d4'.repeat(40)}`;
  const inizio = 'Candidature aperte fino al 30 settembre. Dettagli su ';
  const fine = `. Il bando riguarda ${riempitivo(280)}.`;
  const grezzo = inizio + url + fine;
  assert.ok(grezzo.length >= 700);
  const atteso = `${inizio}inpa.gov.it${fine}`;
  assert.ok(atteso.length <= 600);
  // dopo la sostituzione il testo sta nel limite: nessun taglio
  assert.equal(sintesiDaMarkdown(grezzo, 600), atteso);

  // qui il fine frase cade oltre 600 nel grezzo ma dentro la finestra dopo la sostituzione
  const lungo = `${inizio}${url}. Seconda ${riempitivo(250)}. Terza ${riempitivo(400)}`;
  const esito = sintesiDaMarkdown(lungo, 600);
  assert.equal(esito, `${inizio}inpa.gov.it. Seconda ${riempitivo(250)}.`);
  assert.ok(lungo.indexOf(`${riempitivo(250)}.`) + riempitivo(250).length + 1 > 600);
});

test('sintesiDaMarkdown: mai una coppia di surrogati spezzata', () => {
  const emoji = '😀'.repeat(400);
  // con massimo 2 non entra nemmeno un'emoji prima di …: nessun testo
  assert.equal(sintesiDaMarkdown(emoji, 2), null);
  for (let massimo = 3; massimo <= 40; massimo++) {
    const esito = sintesiDaMarkdown(emoji, massimo);
    assert.ok(esito !== null);
    assert.ok(esito.length <= massimo, `lunghezza con massimo ${massimo}`);
    assert.ok(!SURROGATO_SPAIATO.test(esito), `surrogato spaiato con massimo ${massimo}`);
    assert.ok(esito.endsWith('…'));
  }
  const parole = Array.from({ length: 300 }, () => '😀😀').join(' ');
  for (const massimo of [599, 600, 601]) {
    const esito = sintesiDaMarkdown(parole, massimo);
    assert.ok(esito !== null && esito.length <= massimo && !SURROGATO_SPAIATO.test(esito));
  }
});

test('sintesiDaMarkdown: il taglio toglie la punteggiatura debole prima di …', () => {
  const testo = `${riempitivo(596)}, ${riempitivo(100)}`;
  const esito = sintesiDaMarkdown(testo, 600);
  assert.ok(esito !== null && esito.endsWith('…') && !esito.endsWith(',…'));
});

// ---------------------------------------------------------------------------
// pulisciElenco
// ---------------------------------------------------------------------------

test('pulisciElenco: non array -> []', () => {
  for (const v of [null, undefined, 'a', 42, {}, { length: 1, 0: 'a' }]) {
    assert.deepEqual(pulisciElenco(v), []);
  }
});

test('pulisciElenco: pulizia, scarti e deduplica mantenendo il primo e l\'ordine', () => {
  assert.deepEqual(pulisciElenco(['b', 'a', 'b', 'c', 'a']), ['b', 'a', 'c']);
  assert.deepEqual(
    pulisciElenco([1, null, '', '  ', '<b></b>', 'ok', 'https://web.spaggiari.eu/x', { a: 1 }]),
    ['ok'],
  );
  assert.deepEqual(pulisciElenco(['  docenti   precari ', 'docenti precari']), ['docenti precari']);
  assert.deepEqual(pulisciElenco(['a&amp;b', 'a&b']), ['a&b']);
  // eslint-disable-next-line no-sparse-arrays
  assert.deepEqual(pulisciElenco([, 'a']), ['a']);
  assert.deepEqual(pulisciElenco(['__proto__', 'constructor', '__proto__']), ['__proto__', 'constructor']);
});

test('pulisciElenco: senzaMaiuscole confronta con toLowerCase', () => {
  assert.deepEqual(pulisciElenco(['Scuola', 'scuola', 'SCUOLA']), ['Scuola', 'scuola', 'SCUOLA']);
  assert.deepEqual(pulisciElenco(['Scuola', 'scuola', 'SCUOLA'], { senzaMaiuscole: true }), ['Scuola']);
  assert.deepEqual(pulisciElenco(['Beta', 'alfa', 'ALFA', 'Università', 'UNIVERSITÀ'], { senzaMaiuscole: true }), ['Beta', 'alfa', 'Università']);
  assert.deepEqual(pulisciElenco(['GPS', 'gps'], { senzaMaiuscole: false }), ['GPS', 'gps']);
});

// ---------------------------------------------------------------------------
// Correzioni dopo la revisione del codice
// ---------------------------------------------------------------------------

test('intestazioni di servizio del generatore rimosse, titoli chiusi da un punto', () => {
  assert.equal(sintesiDaMarkdown('### Paragrafo 1\nTesto.', 600), 'Testo.');
  assert.equal(sintesiDaMarkdown('### Primo paragrafo (200 parole)\nTesto.', 600), 'Testo.');
  assert.equal(sintesiDaMarkdown('### Primo Paragrafo\nTesto.', 600), 'Testo.');
  assert.equal(sintesiDaMarkdown('**Paragrafo 1:** Testo.', 600), 'Testo.');
  assert.equal(sintesiDaMarkdown('**Paragrafo 1: Contesto**\nTesto.', 600), 'Contesto Testo.');
  assert.equal(sintesiDaMarkdown('Riassunto in Tre Paragrafi (600 parole totali)\nTesto.', 600), 'Testo.');
  assert.equal(sintesiDaMarkdown('### Un titolo\nTesto.', 600), 'Un titolo. Testo.');
  assert.equal(sintesiDaMarkdown('### Un titolo?\nTesto.', 600), 'Un titolo? Testo.');
  // un titolo lungo quanto un paragrafo e gia' chiuso resta com'e' (non diventa null)
  const lungo = 'Il lancio della serie sta catalizzando l\'attenzione del mercato europeo.';
  assert.equal(sintesiDaMarkdown(`### ${lungo}`, 600), lungo);
  // "paragrafo" dentro una frase normale non si tocca
  assert.equal(sintesiDaMarkdown('Il paragrafo 1 del decreto cambia.', 600), 'Il paragrafo 1 del decreto cambia.');
});

test('pulisciTestoMarkdown: titoli ed excerpt degli articoli senza markdown', () => {
  assert.equal(pulisciTestoMarkdown('**Cougar OmnyX: Innovazione e Creatività nel Design del Tuo PC**'),
    'Cougar OmnyX: Innovazione e Creatività nel Design del Tuo PC');
  assert.equal(pulisciTestoMarkdown('Un quadro delle scuole italiane\n\n# Stipula e Rinnovo della Convenzione'),
    'Un quadro delle scuole italiane Stipula e Rinnovo della Convenzione.');
  assert.equal(pulisciTestoMarkdown('https://example.org/x'), null);
  assert.equal(pulisciTestoMarkdown(''), null);
  assert.equal(pulisciTestoMarkdown(42), null);
  assert.equal(pulisciTestoMarkdown('esame_di_stato 2*3*4'), 'esame_di_stato 2*3*4');
});

test('niente backtracking quadratico (ReDoS) su input patologici', () => {
  const casi: Array<[string, () => unknown]> = [
    ['backtick dopo un carattere', () => sintesiDaMarkdown('a' + '`'.repeat(200_000), 600)],
    ['punteggiatura dopo un URL', () => pulisciTesto('https://a.it/' + '.'.repeat(200_000) + 'x')],
    ['parentesi dopo www', () => pulisciTesto('www.a.it/' + ')'.repeat(200_000) + 'x')],
    ['punteggiatura nella sintesi', () => sintesiDaMarkdown('vedi https://a.it/' + ','.repeat(200_000) + 'x fine', 600)],
  ];
  for (const [nome, esegui] of casi) {
    const inizio = performance.now();
    esegui();
    const durata = performance.now() - inizio;
    assert.ok(durata < 500, `${nome}: ${durata.toFixed(0)} ms`);
  }
  // semantica CommonMark delle serie sbilanciate
  assert.equal(sintesiDaMarkdown('a ``x`', 600), 'a ``x`');
  assert.equal(sintesiDaMarkdown('usa `npm test` ora', 600), 'usa npm test ora');
  assert.equal(pulisciTesto('vedi https://a.it/p).'), 'vedi a.it).');
});
