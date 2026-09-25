/**
 * `src/lib/bandi/elenco.ts`: i calcoli della lista del design «Bandi Redesign»
 * (formati, chip, tessere, segmenti, preset, etichette dei bottoni rapidi,
 * opzioni raggruppate per alias).
 *
 * Dove il mock ha un valore di riferimento, il test lo usa: se una di queste
 * asserzioni cambia, la pagina non e' piu' uguale al design.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aggiungiGiorni, chipFiltri, colonnaData, contaAvanzati, contaFiltriContenuto, costruisciOpzioni, eur, eurBreve,
  etichettaRapida, idsDiValore, modelloCard, normalizzaPresentazione, numeroGrande, numeroOpzione,
  opzioneSelezionata, presetImporto, presetScadenza, segmentiStato, tessere, titoloLista, valoreDiIds, valoriReset,
  type GruppoFiltro,
} from '../../src/lib/bandi/elenco.ts';
import type { Valori } from '../../src/lib/liste/parametri.ts';

const OGGI = '2026-09-25';

/** Serializzatore minimo per i test: l'ordine delle chiavi e' quello dei valori. */
const url = (v: Valori): string => {
  const qs = new URLSearchParams();
  for (const [k, vs] of Object.entries(v)) for (const x of vs) qs.append(k, x);
  const s = qs.toString();
  return `/bandi${s ? `?${s}` : ''}`;
};

test('formati del mock', () => {
  assert.equal(numeroGrande(2148), '2.148');
  assert.equal(numeroGrande(37), '37');
  assert.equal(numeroOpzione(1391), '1391');
  assert.equal(numeroOpzione(12345), '12.345');
  assert.equal(eur(200000), '200.000 €');
  assert.equal(eur(937394), '937.394 €');
  // La formula del mock non ha decimali: i milioni si arrotondano.
  assert.equal(eurBreve(6905000), '7 mln €');
  assert.equal(eurBreve(10000000), '10 mln €');
  assert.equal(eurBreve(2000000), '2 mln €');
  assert.equal(eurBreve(432000), '432.000 €');
  assert.deepEqual(colonnaData('2026-10-31'), { giorno: '31', meseAnno: 'ott 2026' });
  assert.deepEqual(colonnaData('2027-02-06'), { giorno: '6', meseAnno: 'feb 2027' });
  assert.equal(colonnaData(null), null);
});

test('aggiungiGiorni: aritmetica UTC, anche a cavallo dell\'ora legale e dell\'anno', () => {
  assert.equal(aggiungiGiorni('2026-09-25', 7), '2026-10-02');
  assert.equal(aggiungiGiorni('2026-10-20', 15), '2026-11-04');
  assert.equal(aggiungiGiorni('2026-12-30', 3), '2027-01-02');
});

test('card: colonna data, giorni e palette urgente come card() del mock', () => {
  const aperto = modelloCard({ stato: 'aperto', data_scadenza: '2026-10-05', importo_totale_eur: 937394 }, OGGI);
  assert.equal(aperto.urgente, true);
  assert.equal(aperto.giorniTesto, 'tra 10 giorni');
  assert.deepEqual(aperto.data, { giorno: '5', meseAnno: 'ott 2026' });
  assert.equal(aperto.scadenzaLunga, '5 ottobre 2026');
  assert.equal(aperto.dotazione, '937.394 €');
  assert.equal(aperto.dotazioneBreve, '937.394 €');
  assert.equal(aperto.aspetto?.etichetta, 'Aperto');

  const lontano = modelloCard({ stato: 'aperto', data_scadenza: '2027-09-30', importo_totale_eur: 6905000 }, OGGI);
  assert.equal(lontano.urgente, false);
  assert.equal(lontano.giorniTesto, 'tra 370 giorni');
  assert.equal(lontano.dotazioneBreve, '7 mln €');

  // In apertura: niente giorni (sarebbe credere che si possa gia' partecipare).
  const inApertura = modelloCard({ stato: 'in apertura prossimamente', data_scadenza: '2026-10-05', importo_totale_eur: null }, OGGI);
  assert.equal(inApertura.giorniTesto, null);
  assert.equal(inApertura.urgente, false);
  assert.equal(inApertura.dotazione, null);
  assert.equal(inApertura.dotazioneBreve, 'Non indicata');

  const senzaData = modelloCard({ stato: 'aperto', data_scadenza: null, importo_totale_eur: null }, OGGI);
  assert.equal(senzaData.data, null);
  assert.equal(senzaData.scadenzaLunga, 'Non indicata');
  assert.equal(senzaData.giorniTesto, null);

  assert.equal(modelloCard({ stato: 'aperto', data_scadenza: OGGI, importo_totale_eur: null }, OGGI).giorniTesto, 'scade oggi');
  assert.equal(modelloCard({ stato: null, data_scadenza: null, importo_totale_eur: null }, OGGI).aspetto, null);
});

test('opzioni: gli alias diventano una voce sola, gli zeri spariscono tranne se scelti', () => {
  const righe = [
    { id: 3, etichetta: 'FESR' },
    { id: 9, etichetta: 'FSE+' },
    { id: 12, etichetta: 'FSE+ - Fondo Sociale Europeo +' },
    { id: 20, etichetta: 'Interreg' },
    { id: 21, etichetta: 'PNRR' },
  ];
  const voci = [
    { idsDb: [12, 9], etichetta: 'FSE+ — Fondo Sociale Europeo Plus', totale: 327 },
    { idsDb: [3], etichetta: 'FESR', totale: 486 },
  ];
  const perId = new Map([[3, 486], [9, 100], [12, 227], [20, 71]]);
  assert.deepEqual(costruisciOpzioni(righe, voci, perId, []), [
    { valore: '3', etichetta: 'FESR', conteggio: 486 },
    { valore: '9,12', etichetta: 'FSE+ — Fondo Sociale Europeo Plus', conteggio: 327 },
    { valore: '20', etichetta: 'Interreg', conteggio: 71 },
  ]);
  // PNRR ha zero bandi: resta solo se e' fra le scelte.
  assert.equal(costruisciOpzioni(righe, voci, perId, ['21']).some((o) => o.valore === '21'), true);
  // Senza conteggi restano tutte, senza numero.
  const senza = costruisciOpzioni(righe, null, null, []);
  assert.equal(senza.length, 5);
  assert.equal(senza[0].conteggio, null);
});

test('valori alias: ordinati, e un vecchio id singolo seleziona il gruppo', () => {
  assert.equal(valoreDiIds([12, 9, 12]), '9,12');
  assert.deepEqual(idsDiValore('9,12'), [9, 12]);
  assert.deepEqual(idsDiValore('9,x'), [9]);
  const opzione = { valore: '9,12', etichetta: 'FSE+', conteggio: 1 };
  assert.equal(opzioneSelezionata(opzione, ['9,12']), true);
  assert.equal(opzioneSelezionata(opzione, ['9']), true);
  assert.equal(opzioneSelezionata(opzione, ['3']), false);
  assert.equal(opzioneSelezionata(opzione, ['9,3']), false);
});

test('etichetta del bottone rapido e contatore di «Tutti i filtri»', () => {
  assert.equal(etichettaRapida('Regione', []), 'Regione');
  assert.equal(etichettaRapida('Regione', ['Piemonte']), 'Piemonte');
  assert.equal(etichettaRapida('Regione', ['Piemonte', 'Marche']), 'Regione · 2');
  assert.equal(contaAvanzati({}), 0);
  assert.equal(contaAvanzati({ regione: ['1', '2'], ateco: ['5'], imin: ['100'], imax: [], scad_a: ['2026-10-01'], q: ['x'], stato: ['aperto'] }), 5);
});

test('filtri di contenuto: ordinamento e vista non contano', () => {
  assert.equal(contaFiltriContenuto({ ordina: ['importo'], vista: ['griglia'] }), 0);
  assert.equal(contaFiltriContenuto({ ordina: ['importo'], regione: ['1'], q: [] }), 1);
});

test('normalizzazione: solo i valori ammessi di ordina, vista e in_scadenza', () => {
  assert.deepEqual(normalizzaPresentazione({ ordina: ['importo'], vista: ['griglia'], in_scadenza: ['si'] }).cambiato, false);
  const r = normalizzaPresentazione({ ordina: ['scadenza'], vista: ['elenco'], in_scadenza: ['on'], regione: ['1'] });
  assert.equal(r.cambiato, true);
  assert.deepEqual(r.valori, { ordina: [], vista: [], in_scadenza: [], regione: ['1'] });
});

test('reset: via i filtri, restano ordinamento e vista (resetAll del mock)', () => {
  assert.deepEqual(valoriReset({ q: ['x'], regione: ['1'], ordina: ['importo'], vista: ['griglia'] }), { ordina: ['importo'], vista: ['griglia'] });
});

test('chip nell\'ordine del mock, ognuna con il link che la toglie', () => {
  const gruppi: GruppoFiltro[] = [
    { chiave: 'regione', etichetta: 'Regione', opzioni: [{ valore: '7', etichetta: 'Piemonte', conteggio: 214 }] },
    { chiave: 'programma', etichetta: 'Programma', opzioni: [{ valore: '9,12', etichetta: 'FSE+', conteggio: 327 }] },
  ];
  const valori: Valori = {
    q: ['lingue '], regione: ['7'], programma: ['9'], stato: ['aperto'], in_scadenza: ['si'],
    imin: ['100000'], imax: ['1000000'], scad_da: ['2026-09-25'], scad_a: [], ordina: ['importo'],
  };
  const chip = chipFiltri(valori, gruppi, url);
  assert.deepEqual(chip.map((c) => [c.chiave, c.valore]), [
    ['Ricerca', '“lingue”'],
    ['Stato', 'Aperto'],
    ['', 'In scadenza'],
    ['Regione', 'Piemonte'],
    ['Programma', 'FSE+'],
    ['Importo', '100.000 € – 1 mln €'],
    ['Scadenza', 'dal 25 set'],
  ]);
  // Togliere la regione lascia tutto il resto, ordinamento compreso.
  assert.equal(chip[3].href.includes('regione='), false);
  assert.equal(chip[3].href.includes('ordina=importo'), true);
  assert.equal(chip[5].href.includes('imin='), false);
  assert.equal(chip[5].href.includes('imax='), false);
  // Importo con un solo estremo.
  assert.equal(chipFiltri({ imax: ['100000'] }, [], url)[0].valore, 'fino a 100.000 €');
  assert.equal(chipFiltri({ imin: ['1000000'] }, [], url)[0].valore, 'da 1 mln €');
  assert.equal(chipFiltri({ scad_da: ['2026-09-25'], scad_a: ['2026-10-02'] }, [], url)[0].valore, '25 set – 2 ott');
  assert.equal(chipFiltri({ scad_a: ['2026-10-02'] }, [], url)[0].valore, 'entro 2 ott');
});

test('tessere e segmenti: numeri raggruppati, link e stato attivo come nel mock', () => {
  const c = { tutti: 2148, aperti: 1284, inApertura: 212, chiusi: 652, inScadenza: 37 };
  const t = tessere({}, c, url);
  assert.deepEqual(t.map((x) => [x.numero, x.etichetta, x.attiva]), [
    ['1.284', 'bandi aperti', false],
    ['37', 'scadono entro 15 giorni', false],
    ['212', 'in apertura prossimamente', false],
  ]);
  assert.equal(t[0].href, '/bandi?stato=aperto');
  assert.equal(t[1].href, '/bandi?in_scadenza=si');
  const conUrgenti = tessere({ stato: ['aperto'], in_scadenza: ['si'], regione: ['7'] }, c, url);
  assert.deepEqual(conUrgenti.map((x) => x.attiva), [false, true, false]);
  // La tessera degli urgenti toglie lo stato e tiene gli altri filtri.
  const hrefUrgenti = new URL(conUrgenti[1].href, 'https://edunews24.it').searchParams;
  assert.deepEqual([hrefUrgenti.get('regione'), hrefUrgenti.get('in_scadenza'), hrefUrgenti.get('stato')], ['7', 'si', null]);

  const s = segmentiStato({ stato: ['in apertura prossimamente'] }, c);
  assert.deepEqual(s.map((x) => [x.etichetta, x.valore, x.conteggio, x.attivo]), [
    ['Tutti', '', '2.148', false],
    ['Aperti', 'aperto', '1.284', false],
    ['In apertura', 'in apertura prossimamente', '212', true],
    ['Chiusi', 'chiuso', '652', false],
  ]);
  assert.equal(segmentiStato({}, c)[0].attivo, true);
});

test('preset di importo e scadenza, con lo stato attivo', () => {
  const i = presetImporto({ imin: [], imax: ['100000'] });
  assert.deepEqual(i.map((p) => [p.etichetta, p.da, p.a, p.attivo]), [
    ['Fino a 100.000 €', '', '100000', true],
    ['100.000 – 1 mln €', '100000', '1000000', false],
    ['Oltre 1 mln €', '1000000', '', false],
  ]);
  const s = presetScadenza({ scad_da: [OGGI], scad_a: ['2026-10-25'] }, OGGI);
  assert.deepEqual(s.map((p) => [p.etichetta, p.a, p.attivo]), [
    ['Entro 7 giorni', '2026-10-02', false],
    ['Entro 30 giorni', '2026-10-25', true],
    ['Entro 3 mesi', '2026-12-24', false],
  ]);
});

test('title della lista', () => {
  assert.equal(titoloLista(1, 90), 'Bandi e finanziamenti pubblici - EduNews24');
  assert.equal(titoloLista(3, 90), 'Bandi e finanziamenti pubblici: pagina 3 di 90 - EduNews24');
});
