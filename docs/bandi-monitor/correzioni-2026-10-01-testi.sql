-- ==========================================
-- Correzioni dei testi, 01/10/2026
-- DB «bandi»
-- ==========================================
-- NON rieseguire dopo l'esecuzione:
-- ESEGUITO il 30/09/2026 sera (Michele):
--   T3 e T2, tutti gli esiti attesi.
--   NON rieseguire.
-- ==========================================
-- Scritto il 30/09/2026 da «db», giro
-- «ripresa bandi, ottobre 2026» (task T-D4).
-- Spiegazione completa in docs/bandi-monitor
-- /rigenerazione-2026-10.md.
--
-- Cosa corregge:
-- T3. Bando 18278: toglie dai beneficiari la
--     voce «Imprese sociali/Società
--     benefit», che l'atto dell'ente non
--     prevede (è la correzione T1, ora
--     dentro questo blocco), e chiude il
--     bando: è l'edizione 2025, e i fondi
--     sono finiti il 21/10/2025, il giorno
--     stesso dell'apertura.
-- T2. Bando 112862: registra come verificata
--     la proroga al 15/10 già applicata il
--     30/09. Serve perché il testo della
--     scheda dice ancora «30 settembre 2026»
--     e il comando rigenera guarda solo gli
--     eventi verificati.
--
-- Ordine di esecuzione: T3, poi T2, come
-- sono nel file. Dentro T3 la DELETE dei
-- beneficiari viene prima della chiusura (il
-- motivo è nel blocco).
--
-- Nessun blocco cambia il testo delle
-- schede. Il 18278, chiuso, non va
-- rigenerato (spesa inutile); il 112862 lo
-- riscrive poi rigenera, con la prova a
-- secco prima.
--
-- Provato su Postgres 17 effimero con le RPC
-- vere: due esecuzioni di fila, la seconda
-- non cambia niente.
-- ==========================================


-- ------------------------------------------
-- T3. Bando 18278 (voucher digitali I4.0,
--     CCIAA Basilicata): beneficiari
--     corretti (T1) e chiusura.
--     È l'edizione 2025. La pagina della
--     Camera di commercio: domande «a
--     partire dalle ore 9:00 del 21 ottobre
--     2025», e poi «Si comunica che il Bando
--     Voucher Digitali ha esaurito il suo
--     plafond alle 9:28 del 21/10/2025». A
--     DB è ancora «aperto», senza scadenza.
--     aperto → chiuso per una chiusura del
--     worker è nella lista bianca; la data
--     di scadenza resta com'è (vuota).
--     T1, dentro questo blocco: l'art. 2 del
--     bando dice «progetti presentati da
--     singole imprese», e imprese sociali,
--     società benefit, reti o aggregazioni
--     non compaiono mai. La voce viene dalla
--     scheda di ObiettivoEuropa. Si toglie
--     una sola riga della tabella di
--     collegamento (id 19785); bando e
--     catalogo non si toccano.
--     Ordine: prima la DELETE, poi la
--     chiusura. La DELETE non fa avanzare
--     ultimo_cambiamento_at (la tabella di
--     collegamento non ha il trigger), la
--     chiusura sì: così chi legge il DB
--     (BandoFit) rilegge la scheda quando
--     anche i beneficiari sono già giusti.
--     Dopo, la scheda non va rigenerata.
-- ------------------------------------------

-- prima: dominio verificante
-- (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(
  public.dominio_di('https://'
    || 'www.basilicata.camcom.it'));

-- prima (atteso: aperto | NULL)
select stato_bando, data_scadenza
  from bando where id = 18278;

-- prima (atteso: 5 righe, fra cui
--   19785 | 17 | Imprese sociali/Società
--   benefit)
select bb.id, bb.beneficiario_id, b.nome
  from bando_beneficiari bb
  join beneficiari b
    on b.id = bb.beneficiario_id
 where bb.bando_id = 18278
 order by bb.id;

-- T1: la riga sbagliata dei beneficiari
delete from bando_beneficiari
 where id = 19785
   and bando_id = 18278
   and beneficiario_id = (
     select id from beneficiari
      where nome =
        'Imprese sociali/Società benefit'
   );
-- atteso: DELETE 1 (DELETE 0 se già fatto)

-- la chiusura
select public.bando_registra_evento(
  p_bando_id    => 18278,
  p_tipo        => 'chiusura',
  p_origine     => 'worker',
  p_campo       => 'stato_bando',
  p_valore_dopo => jsonb_build_object(
    'stato_bando', 'chiuso'),
  p_url_prova   =>
    'https://www.basilicata.camcom.it/promo'
    || 'zione/innovazione-digitale/voucher-'
    || 'digitali-40/bando-voucher-digitali-'
    || 'ed-2025',
  p_citazione   =>
    'Si comunica che il Bando Voucher Digit'
    || 'ali ha esaurito il suo plafond alle'
    || ' 9:28 del 21/10/2025',
  p_data_evento => '2025-10-21',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D4, 01/10): esau'
    || 'rimento risorse, edizione 2025 chiu'
    || 'sa il giorno dell''apertura'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: chiuso | NULL | true)
select stato_bando, data_scadenza,
       stato_bando_verificato
  from bando where id = 18278;

-- dopo (atteso: 4 righe, senza la 19785)
select bb.id, bb.beneficiario_id, b.nome
  from bando_beneficiari bb
  join beneficiari b
    on b.id = bb.beneficiario_id
 where bb.bando_id = 18278
 order by bb.id;


-- ------------------------------------------
-- T2. Bando 112862 (FVG, associazioni
--     combattentistiche).
--     Il blocco C2 del 30/09
--     (correzioni-2026-09-29.sql) ha
--     spostato la scadenza al 15/10, ma la
--     RPC ha riusato l'evento 11295 del
--     monitor, che non è verificato: la
--     proroga non compare nel box e il
--     comando rigenera non la vede. Qui si
--     registra lo stesso fatto con la stessa
--     prova, questa volta verificato. Le
--     colonne non cambiano (la scadenza è
--     già il 15/10): cambiano solo la
--     provenienza della data e il box.
--     "stato_bando" nel valore rende
--     l'evento diverso dall'11295 e lo tiene
--     giusto anche se il bando fosse già
--     chiuso.
-- ------------------------------------------

-- prima: dominio verificante
-- (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(
  public.dominio_di('https://'
    || 'www.regione.fvg.it'));

-- prima (atteso: aperto | 2026-10-15 |
--   false | 11295)
select stato_bando, data_scadenza,
       data_scadenza_verificata,
       data_scadenza_evento_id
  from bando where id = 112862;

select public.bando_registra_evento(
  p_bando_id    => 112862,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-15',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.fvg.it/rafvg/cms/R'
    || 'AFVG/MODULI/bandi_avvisi/BANDI/9026'
    || '.html',
  p_citazione   =>
    'l''articolo 10, comma 1, con proroga d'
    || 'el termine perentorio di presentazi'
    || 'one delle domande al 15 ottobre 202'
    || '6',
  p_data_evento => '2026-09-07',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D4, 01/10): la s'
    || 'tessa proroga del blocco C2, verifi'
    || 'cata; l''evento 11295 del monitor n'
    || 'on lo era'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-15 |
--   true | <id nuovo>)
select stato_bando, data_scadenza,
       data_scadenza_verificata,
       data_scadenza_evento_id
  from bando where id = 112862;

-- dopo (atteso: la riga nuova con
--   verificato, applicato, leggibile e
--   in_aggiornamenti tutti true)
select id, verificato, applicato,
       leggibile, in_aggiornamenti
  from bando_evento
 where bando_id = 112862
   and tipo = 'proroga'
 order by id;
