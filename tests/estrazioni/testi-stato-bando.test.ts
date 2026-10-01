/**
 * `src/lib/bandi/testi-stato.ts`: badge a cinque stati, frasi dei casi limite
 * di §4.2 e opzioni del filtro.
 *
 * Il codice precedente conosceva tre stati, chiamava «In apertura» anche un
 * bando la cui data di apertura era passata e non diceva mai se una data fosse
 * verificata o solo dichiarata dalla fonte.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BADGE_STATO, badgeStato, giornoItaliano, giorniAllaScadenza, opzioniStato, oraItaliana, partecipazioneAperta,
  rigaScadenza, sottotestoStato, testoFonteUfficiale, testoGiorniMancanti,
} from '../../src/lib/bandi/testi-stato.ts';
import { STATI_BANDO } from '../../src/lib/stato-bando.ts';

const OGGI = '2026-09-23';

test('badge: un\'etichetta per ognuno dei cinque stati, più sconosciuto', () => {
  for (const stato of STATI_BANDO) {
    const badge = badgeStato(stato);
    assert.notEqual(badge.etichetta, '—', stato);
    assert.ok(badge.classi.length > 0, stato);
  }
  assert.equal(badgeStato('aperto').etichetta, 'Aperto');
  assert.equal(badgeStato('in apertura prossimamente').etichetta, 'In apertura');
  assert.equal(badgeStato('chiuso').etichetta, 'Chiuso');
  assert.equal(badgeStato('sospeso').etichetta, 'Sospeso');
  assert.equal(badgeStato('revocato').etichetta, 'Revocato');
  // Revocato e chiuso sono entrambi grigi: il barrato è l'unica cosa che li
  // distingue a colpo d'occhio, e va difesa.
  assert.ok(BADGE_STATO.revocato.classi.includes('line-through'));
  assert.equal(BADGE_STATO.chiuso.classi.includes('line-through'), false);
  // Stato nullo o fuori vocabolario: «—», mai un'etichetta inventata.
  assert.equal(badgeStato(null).etichetta, '—');
  assert.equal(badgeStato('APERTO').etichetta, '—');
  assert.equal(badgeStato('sconosciuto').etichetta, '—');
});

test('date e ore in italiano senza toLocaleDateString', () => {
  assert.equal(giornoItaliano('2026-10-31'), '31 ottobre 2026');
  assert.equal(giornoItaliano('2026-01-05T12:00:00+02:00'), '5 gennaio 2026');
  assert.equal(giornoItaliano('2026-13-01'), null);
  assert.equal(giornoItaliano('domani'), null);
  assert.equal(giornoItaliano(null), null);
  assert.equal(oraItaliana('23:59:00'), '23:59');
  assert.equal(oraItaliana('09:00'), '09:00');
  assert.equal(oraItaliana('25:00'), null);
  assert.equal(oraItaliana(null), null);
});

test('revocato e sospeso vengono prima di qualunque data', () => {
  const revocato = sottotestoStato({ stato: 'revocato', data_scadenza: '2026-12-31', oggi: OGGI });
  assert.ok(revocato !== null && revocato.includes('revocato'));
  // A3: un sospeso con la scadenza passata resta sospeso e non diventa «chiuso».
  const sospeso = sottotestoStato({ stato: 'sospeso', data_scadenza: '2020-01-01', oggi: OGGI });
  assert.ok(sospeso !== null && sospeso.includes('sospeso'));
  assert.equal(sospeso.includes('scadut'), false);
});

test('aperto: scadenza con ora, e mai «verificata» senza il flag', () => {
  const senzaFlag = sottotestoStato({ stato: 'aperto', data_scadenza: '2026-10-31', oggi: OGGI });
  assert.ok(senzaFlag !== null && senzaFlag.includes('31 ottobre 2026'));
  assert.ok(senzaFlag.includes('indicata dalla fonte'));
  assert.equal(senzaFlag.includes('come verificato'), false);

  const conFlag = sottotestoStato({
    stato: 'aperto', data_scadenza: '2026-10-31', data_scadenza_verificata: true, oggi: OGGI,
  });
  assert.ok((conFlag ?? '').includes('come verificato sulla fonte ufficiale'));

  const conOra = sottotestoStato({
    stato: 'aperto', data_scadenza: '2026-10-31', ora_scadenza: '12:00:00', oggi: OGGI,
  });
  assert.ok((conOra ?? '').includes('31 ottobre 2026 alle 12:00'));

  // Sportello senza scadenza: lo si dice, non si tace.
  const sportello = sottotestoStato({ stato: 'aperto', data_scadenza: null, oggi: OGGI });
  assert.ok((sportello ?? '').includes('non indica una data di scadenza'));
});

test('chiuso: scaduto, verificato o no; e chiusura anticipata', () => {
  const scaduto = sottotestoStato({ stato: 'chiuso', data_scadenza: '2026-09-01', oggi: OGGI });
  assert.ok((scaduto ?? '').includes('scaduti il 1 settembre 2026'));
  assert.ok((scaduto ?? '').includes('non è stata verificata'));

  const verificato = sottotestoStato({
    stato: 'chiuso', data_scadenza: '2026-09-01', data_scadenza_verificata: true, oggi: OGGI,
  });
  assert.ok((verificato ?? '').includes('come verificato sulla fonte ufficiale'));

  // Chiuso con la scadenza ancora davanti: è una chiusura anticipata, non un errore.
  const anticipata = sottotestoStato({ stato: 'chiuso', data_scadenza: '2026-12-31', oggi: OGGI });
  assert.ok((anticipata ?? '').includes('prima della scadenza indicata'));

  assert.ok((sottotestoStato({ stato: 'chiuso', data_scadenza: null, oggi: OGGI }) ?? '').includes('chiusi'));
});

test('in apertura: futura verificata, annunciata, già passata, non comunicata', () => {
  const verificata = sottotestoStato({
    stato: 'in apertura prossimamente', data_apertura: '2026-11-02',
    data_apertura_verificata: true, oggi: OGGI,
  });
  assert.ok((verificata ?? '').includes('Apre il 2 novembre 2026'));

  const annunciata = sottotestoStato({
    stato: 'in apertura prossimamente', data_apertura: '2026-11-02', oggi: OGGI,
  });
  assert.ok((annunciata ?? '').includes('annunciata per il 2 novembre 2026'));
  assert.ok((annunciata ?? '').includes('non è ancora verificata'));

  // I 14 bandi che il sito mostrava «In apertura» con l'apertura passata.
  const passata = sottotestoStato({
    stato: 'in apertura prossimamente', data_apertura: '2026-01-01', oggi: OGGI,
  });
  assert.ok((passata ?? '').includes('era annunciata per il 1 gennaio 2026'));

  const senzaData = sottotestoStato({ stato: 'in apertura prossimamente', data_apertura: null, oggi: OGGI });
  assert.ok((senzaData ?? '').includes('non è stata comunicata'));
});

test('stato ignoto: «in verifica», mai un\'affermazione', () => {
  assert.ok((sottotestoStato({ stato: null, oggi: OGGI }) ?? '').includes('in verifica'));
});

test('CTA e conto alla rovescia nascosti su sospeso e revocato', () => {
  assert.equal(partecipazioneAperta('aperto'), true);
  assert.equal(partecipazioneAperta('chiuso'), true);
  assert.equal(partecipazioneAperta('in apertura prossimamente'), true);
  assert.equal(partecipazioneAperta('sospeso'), false);
  assert.equal(partecipazioneAperta('revocato'), false);
  assert.equal(partecipazioneAperta(null), true);
});

test('fonte ufficiale: host, qualifica, verifica e controllo', () => {
  assert.equal(
    testoFonteUfficiale(
      { stato: 'trovata', url: 'https://comune.esempio.it/b', host: 'comune.esempio.it', tipo: 'ente', verificata_il: '2026-09-03' },
      '2026-09-20',
    ),
    'Fonte ufficiale: comune.esempio.it (pagina dell\'ente) — verificata il 3 settembre 2026 · controllata il 20 settembre 2026',
  );
  assert.ok(testoFonteUfficiale(
    { stato: 'trovata', url: 'https://incentivi.gov.it/b', host: 'incentivi.gov.it', tipo: 'portale_pubblico' },
  ).includes('(portale pubblico)'));
  assert.ok(testoFonteUfficiale(
    { stato: 'trovata', url: 'https://comune.esempio.it/atto.pdf', host: 'comune.esempio.it', tipo: 'ente', e_atto: true },
  ).includes('(atto)'));

  // F1 e casi non conclusi: mai un host inventato.
  assert.equal(testoFonteUfficiale(null), 'Fonte ufficiale in verifica');
  assert.equal(testoFonteUfficiale(null, '2026-09-20'), 'Fonte ufficiale in verifica · controllata il 20 settembre 2026');
  assert.equal(
    testoFonteUfficiale({ stato: 'in_verifica', url: null, host: null, tipo: null }),
    'Fonte ufficiale in verifica',
  );
  // Stato `trovata` ma host vuoto: si degrada, non si stampa una riga monca.
  assert.equal(
    testoFonteUfficiale({ stato: 'trovata', url: 'https://x.esempio.it', host: '', tipo: 'ente' }),
    'Fonte ufficiale in verifica',
  );
});

test('opzioni del filtro: i due stati nuovi solo con il flag esteso', () => {
  assert.deepEqual(opzioniStato(false).map((o) => o.value), ['aperto', 'in apertura prossimamente', 'chiuso']);
  assert.deepEqual(opzioniStato(true).map((o) => o.value),
    ['aperto', 'in apertura prossimamente', 'chiuso', 'sospeso', 'revocato']);
  // Le etichette dei chip sono le stesse dei badge: un solo vocabolario visibile.
  for (const opzione of opzioniStato(true)) assert.equal(opzione.label, badgeStato(opzione.value).etichetta);
});

test('giorni alla scadenza: date civili, nessun fuso', () => {
  assert.equal(giorniAllaScadenza('2026-10-29', OGGI), 36);
  assert.equal(giorniAllaScadenza('2026-09-23', OGGI), 0);
  assert.equal(giorniAllaScadenza('2026-09-24T12:00:00', OGGI), 1);
  assert.equal(giorniAllaScadenza('2026-09-20', OGGI), -3);
  // A cavallo del cambio d'ora (25 ottobre) resta un numero intero di giorni.
  assert.equal(giorniAllaScadenza('2026-10-26', '2026-10-24'), 2);
  assert.equal(giorniAllaScadenza(null, OGGI), null);
  assert.equal(giorniAllaScadenza('entro fine mese', OGGI), null);
  assert.equal(giorniAllaScadenza('2026-10-29', ''), null);
  // Forma giusta, giorno inesistente: null, non NaN («tra NaN giorni»).
  assert.equal(giorniAllaScadenza('2026-10-32', OGGI), null);
  assert.equal(testoGiorniMancanti(Number.NaN), null);

  assert.equal(testoGiorniMancanti(36), 'tra 36 giorni');
  assert.equal(testoGiorniMancanti(1), 'scade domani');
  assert.equal(testoGiorniMancanti(0), 'scade oggi');
  // Mai «Scaduto da N giorni»: il passato non ha conto alla rovescia.
  assert.equal(testoGiorniMancanti(-3), null);
  assert.equal(testoGiorniMancanti(null), null);
});

test('riga scadenza della card: prima lo stato, poi la data', () => {
  assert.deepEqual(rigaScadenza('aperto', '2026-10-29', OGGI), { testo: 'Scade il 29 ottobre 2026', mancano: 'tra 36 giorni' });
  assert.deepEqual(rigaScadenza('aperto', '2026-09-24', OGGI), { testo: 'Scade il 24 settembre 2026', mancano: 'scade domani' });
  assert.deepEqual(rigaScadenza('aperto', '2026-09-23', OGGI), { testo: 'Scade il 23 settembre 2026', mancano: 'scade oggi' });
  // Dati incoerenti (aperto con data passata): niente «Scade il» al passato.
  assert.deepEqual(rigaScadenza('aperto', '2026-09-01', OGGI), { testo: 'Scadenza: 1 settembre 2026', mancano: null });
  assert.deepEqual(
    rigaScadenza('in apertura prossimamente', '2026-12-15', OGGI),
    { testo: 'Scade il 15 dicembre 2026', mancano: null },
  );
  assert.deepEqual(rigaScadenza('chiuso', '2026-09-01', OGGI), { testo: 'Scaduto il 1 settembre 2026', mancano: null });
  // Chiuso oggi a ora di scadenza passata: la vista lo dà già chiuso.
  assert.deepEqual(rigaScadenza('chiuso', '2026-09-23', OGGI), { testo: 'Scaduto il 23 settembre 2026', mancano: null });
  // Chiusura anticipata: la data è ancora davanti, ma «Scade il» mentirebbe.
  assert.deepEqual(rigaScadenza('chiuso', '2026-10-31', OGGI), { testo: 'Scadenza: 31 ottobre 2026', mancano: null });
  assert.deepEqual(rigaScadenza('sospeso', '2026-10-31', OGGI), { testo: 'Scadenza: 31 ottobre 2026', mancano: null });
  assert.deepEqual(rigaScadenza('revocato', '2026-10-31', OGGI), { testo: 'Scadenza: 31 ottobre 2026', mancano: null });
  assert.deepEqual(rigaScadenza(null, '2026-10-31', OGGI), { testo: 'Scadenza: 31 ottobre 2026', mancano: null });
  // Senza una data leggibile la riga non c'è: niente placeholder.
  assert.equal(rigaScadenza('aperto', null, OGGI), null);
  assert.equal(rigaScadenza('aperto', 'da definire', OGGI), null);
});

// ---------------------------------------------------------------------------
// Stato da verificare (contratto interno del giro 2, §15 con §19.14)
// ---------------------------------------------------------------------------

test('sottotesto: «in apertura» per ogni motivo', () => {
  const base = { stato: 'in apertura prossimamente' as const, data_apertura: '2026-10-15', oggi: OGGI };
  assert.equal(
    sottotestoStato({ ...base, motivo_da_verificare: 'smentito_dalla_fonte' }),
    'La pagina ufficiale non lo indica più come in arrivo: lo stato è in verifica.',
  );
  assert.equal(
    sottotestoStato({ ...base, motivo_da_verificare: 'previsione_scaduta' }),
    'Il periodo di apertura previsto dal calendario è passato senza un avviso pubblicato.',
  );
  assert.equal(
    sottotestoStato({ ...base, motivo_da_verificare: 'senza_conferma' }),
    'L\'apertura è annunciata ma non è confermata sulla fonte ufficiale: verifica sul sito dell\'ente.',
  );
  // data_apertura_passata: il testo di sempre, costruito sulla data
  assert.equal(
    sottotestoStato({ ...base, data_apertura: '2026-09-01', motivo_da_verificare: 'data_apertura_passata' }),
    sottotestoStato({ ...base, data_apertura: '2026-09-01' }),
  );
  assert.match(
    sottotestoStato({ ...base, data_apertura: '2026-09-01', motivo_da_verificare: 'data_apertura_passata' }) ?? '',
    /^L'apertura era annunciata per il 1 settembre 2026/,
  );
  // senza motivo non cambia niente
  assert.equal(
    sottotestoStato(base),
    'L\'apertura è annunciata per il 15 ottobre 2026: la data non è ancora verificata sulla pagina ufficiale.',
  );
});

test('sottotesto: «aperto» per smentita e mancata conferma', () => {
  const base = { stato: 'aperto' as const, oggi: OGGI };
  assert.equal(
    sottotestoStato({ ...base, motivo_da_verificare: 'smentito_dalla_fonte' }),
    'La pagina ufficiale dell\'ente non lo indica più come aperto: verifica prima di presentare domanda.',
  );
  assert.equal(
    sottotestoStato({ ...base, motivo_da_verificare: 'senza_conferma' }),
    'Non abbiamo una conferma recente dalla pagina ufficiale dell\'ente: verifica prima di presentare domanda.',
  );
});

test('sottotesto: termine passato secondo la provenienza (fonte NULL = testo)', () => {
  const passato = (termine_indicato_fonte: string | null) => sottotestoStato({
    stato: 'aperto', motivo_da_verificare: 'termine_passato',
    termine_indicato: '2026-09-01', termine_indicato_fonte, oggi: OGGI,
  });
  // il calendario ufficiale e' la fonte: nessuna riserva «non confermato dalla fonte»
  assert.equal(
    passato('calendario_ufficiale'),
    'Il calendario ufficiale indica un termine di presentazione che sembra già passato: verifica sul sito dell\'ente.',
  );
  assert.equal(passato('calendario_ufficiale')?.includes('non confermato'), false);
  assert.equal(
    passato('pagina'),
    'La pagina dell\'ente indica un termine di presentazione che sembra già passato: verifica sul sito dell\'ente prima di presentare domanda.',
  );
  assert.equal(
    passato('testo'),
    'Il testo del bando indica un termine di presentazione che sembra già passato, non confermato dalla fonte: verifica sul sito dell\'ente.',
  );
  assert.equal(
    passato('aggregatore'),
    'Un portale aggregatore indica un termine di presentazione che sembra già passato, non verificato: verifica sul sito dell\'ente.',
  );
  assert.equal(passato(null), passato('testo'));
  assert.equal(passato('boh'), passato('testo'));
});

test('sottotesto: aperto senza scadenza e senza motivo, lettura e termine futuro', () => {
  const base = { stato: 'aperto' as const, oggi: OGGI };
  const sportello = 'Sportello aperto: la fonte non indica una data di scadenza.';
  // una lettura «aperto» recente, con la data civile di Roma
  assert.equal(
    sottotestoStato({ ...base, stato_letto: 'aperto', stato_letto_at: '2026-09-20T08:00:00+00:00' }),
    'Sportello aperto: la pagina ufficiale lo indicava ancora aperto il 20 settembre 2026.',
  );
  // 22:30 UTC del 19/09 e' gia' il 20/09 a Roma
  assert.equal(
    sottotestoStato({ ...base, stato_letto: 'aperto', stato_letto_at: '2026-09-19T22:30:00+00:00' }),
    'Sportello aperto: la pagina ufficiale lo indicava ancora aperto il 20 settembre 2026.',
  );
  // confine dei 30 giorni: il 24/08 vale (30 giorni prima del 23/09), il 23/08 no
  assert.match(
    sottotestoStato({ ...base, stato_letto: 'aperto', stato_letto_at: '2026-08-24T08:00:00+02:00' }) ?? '',
    /il 24 agosto 2026\.$/,
  );
  assert.equal(
    sottotestoStato({ ...base, stato_letto: 'aperto', stato_letto_at: '2026-08-23T23:59:00+02:00' }),
    sportello,
  );
  // una lettura diversa da «aperto» o senza data non conferma niente
  assert.equal(sottotestoStato({ ...base, stato_letto: 'chiuso', stato_letto_at: '2026-09-20T08:00:00+00:00' }), sportello);
  assert.equal(sottotestoStato({ ...base, stato_letto: 'aperto', stato_letto_at: null }), sportello);
  // termine indicato da oggi in poi, secondo la provenienza
  const futuro = (termine_indicato_fonte: string | null, termine_indicato = '2026-10-31') =>
    sottotestoStato({ ...base, termine_indicato, termine_indicato_fonte });
  assert.equal(futuro('calendario_ufficiale'), 'Il calendario ufficiale indica come termine il 31 ottobre 2026.');
  assert.equal(futuro('pagina'), 'La pagina dell\'ente indica come termine il 31 ottobre 2026.');
  assert.equal(
    futuro('testo'),
    'Il testo del bando indica come termine il 31 ottobre 2026, non ancora verificato sulla pagina ufficiale.',
  );
  assert.equal(futuro('aggregatore'), 'Un portale aggregatore indica come termine il 31 ottobre 2026, non verificato.');
  assert.equal(futuro(null), futuro('testo'));
  assert.equal(futuro('pagina', OGGI), 'La pagina dell\'ente indica come termine il 23 settembre 2026.');
  // un termine passato senza motivo (in ombra) non si racconta come futuro
  assert.equal(futuro('pagina', '2026-09-22'), sportello);
  // la lettura viene prima del termine
  assert.match(
    sottotestoStato({
      ...base, stato_letto: 'aperto', stato_letto_at: '2026-09-20T08:00:00+00:00',
      termine_indicato: '2026-10-31', termine_indicato_fonte: 'pagina',
    }) ?? '',
    /^Sportello aperto: la pagina ufficiale/,
  );
  // con una scadenza il testo resta quello di sempre, lettura o no
  assert.match(
    sottotestoStato({
      ...base, data_scadenza: '2026-10-31', stato_letto: 'aperto', stato_letto_at: '2026-09-20T08:00:00+00:00',
    }) ?? '',
    /^Si può presentare domanda fino al 31 ottobre 2026/,
  );
});

test('sottotesto: il motivo non tocca chiuso, sospeso e revocato', () => {
  for (const stato of ['chiuso', 'sospeso', 'revocato'] as const) {
    assert.equal(
      sottotestoStato({ stato, data_scadenza: '2026-09-01', motivo_da_verificare: 'senza_conferma', oggi: OGGI }),
      sottotestoStato({ stato, data_scadenza: '2026-09-01', oggi: OGGI }),
      stato,
    );
  }
});
