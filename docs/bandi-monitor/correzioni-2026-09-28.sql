-- ============================================================================
-- Correzioni A della prova generale del 28/09/2026 — DB «bandi», SQL Editor
-- ============================================================================
-- Tre blocchi indipendenti: si eseguono uno alla volta, controllando il
-- risultato atteso prima di passare al successivo. Nessun UPDATE diretto su
-- `bando`: stato e date passano da bando_registra_evento/bando_applica_evento,
-- come prescrive il contratto. Da lanciare fuori dai giri delle 00/06/12/18.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- A1. Tre eventi sbagliati fuori dal box «Aggiornamenti»
--     9750 e 9834: presentano come «nuovo allegato del 25/09» la
--     Determinazione DPG025/240 del 01/07/2026 (il testo del bando).
--     9828: cita una voce dell'elenco dei documenti da allegare, non un
--     documento pubblicato dall'ente.
--     `in_aggiornamenti` è fra le colonne che il trigger di immutabilità lascia
--     cambiare; l'evento resta nel registro, sparisce solo dal box.
-- ---------------------------------------------------------------------------

-- prima (atteso: 3 righe, tutte con in_aggiornamenti = true)
select id, bando_id, tipo, leggibile, in_aggiornamenti, cursore
  from bando_evento where id in (9750, 9834, 9828) order by id;

update bando_evento set in_aggiornamenti = false
 where id in (9750, 9834, 9828) and in_aggiornamenti;
-- atteso: UPDATE 3

-- dopo (atteso: 3 righe con in_aggiornamenti = false)
select id, in_aggiornamenti from bando_evento where id in (9750, 9834, 9828) order by id;


-- ---------------------------------------------------------------------------
-- A2. Bando 215460 (h2-sicilia-idrogeno-rinnovabile-decarbonizzazione)
--     A DB è «chiuso» dal 25/09 (scadenza 24/09). L'ente l'ha prorogato:
--     «Con DDG n. 1725 del 17/09/2026 è prorogato il termine di presentazione
--     delle domande alle ore 12:00 dell'8/11/2026». Il monitor l'aveva letta
--     (evento 9786) ma il G1 l'ha respinta per uno spazio prima del punto.
--     Si registra una proroga nuova, con la stessa prova, e la si applica:
--     chiuso → aperto per una proroga del worker è nella lista bianca.
-- ---------------------------------------------------------------------------

-- prima: il dominio della prova deve essere verificante (atteso: true).
-- Se dà false l'evento nascerebbe non verificato e fuori dal box: FERMARSI.
select public.bando_dominio_verificante(public.dominio_di(
  'https://www.euroinfosicilia.it/pr-fesr-sicilia-2021-2027-avviso-h2-sicilia-idrogeno-rinnovabile-decarbonizzazione-sviluppo/'));

select public.bando_registra_evento(
  p_bando_id    => 215460,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => '{"data_scadenza": "2026-11-08", "ora_scadenza": "12:00", "stato_bando": "aperto"}'::jsonb,
  p_url_prova   => 'https://www.euroinfosicilia.it/pr-fesr-sicilia-2021-2027-avviso-h2-sicilia-idrogeno-rinnovabile-decarbonizzazione-sviluppo/',
  p_citazione   => 'Con DDG n. 1725 del 17/09/2026 è prorogato il termine di presentazione delle domande alle ore 12:00 dell''8/11/2026.',
  p_data_evento => '2026-09-17',
  p_applica     => true,
  p_metodo      => 'correzione manuale del committente (prova generale 28/09): evento 9786 respinto dal G1 per la normalizzazione del testo'
);
-- atteso: {"id": <nuovo>, "nuovo": true, "applicato": true}
-- se solleva 23514 (transizione non ammessa) non è stato scritto niente.

-- dopo (atteso: aperto | 2026-11-08 | 12:00:00 | true | <id nuovo>)
select stato_bando, data_scadenza, ora_scadenza, data_scadenza_verificata, stato_bando_evento_id
  from bando where id = 215460;


-- ---------------------------------------------------------------------------
-- A3. Bando 17598 (cciaa-bologna-incentivi-trattenimento-neolaureati-neodiplomati-its)
--     A DB non ha scadenza; l'ente dichiara «Le domande di incentivo devono
--     essere inviate esclusivamente dalle ore 11.00 del 15 settembre 2026,
--     fino alle ore 13 del 16 ottobre 2026». Rettifica della scadenza su un
--     bando aperto: aperto → aperto per una rettifica è nella lista bianca, e
--     lo stato non cambia.
-- ---------------------------------------------------------------------------

-- prima: dominio verificante (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(public.dominio_di(
  'https://www.bo.camcom.gov.it/it/promozione-interna/incentivi-il-trattenimento-dei-neolaureati-e-neodiplomati-its-26'));

select public.bando_registra_evento(
  p_bando_id    => 17598,
  p_tipo        => 'rettifica',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => '{"data_scadenza": "2026-10-16", "ora_scadenza": "13:00"}'::jsonb,
  p_url_prova   => 'https://www.bo.camcom.gov.it/it/promozione-interna/incentivi-il-trattenimento-dei-neolaureati-e-neodiplomati-its-26',
  p_citazione   => 'Le domande di incentivo devono essere inviate esclusivamente dalle ore 11.00 del 15 settembre 2026, fino alle ore 13 del 16 ottobre 2026',
  p_applica     => true,
  p_metodo      => 'correzione manuale del committente (prova generale 28/09): scadenza dichiarata dall''ente e assente a DB'
);
-- atteso: {"id": <nuovo>, "nuovo": true, "applicato": true}

-- dopo (atteso: aperto | 2026-10-16 | 13:00:00 | true)
select stato_bando, data_scadenza, ora_scadenza, data_scadenza_verificata
  from bando where id = 17598;

-- Nota: la prosa delle due schede può citare ancora le date vecchie. La
-- rigenerazione usa Claude: si fa quando il credito è tornato.


-- ---------------------------------------------------------------------------
-- A4 (aggiunta il 29/09). Bando 455779 (valle-aosta-srd03-diversificazione-aziende-agricole)
--     A DB è «chiuso» con scadenza 15/09. L'ente l'ha prorogato: «Si precisa
--     che con PF n. 654 del 14 agosto 2026 la scadenza è stata prorogata alle
--     ore 23.59 del 30 ottobre 2026.» (pagina letta il 29/09). La pagina della
--     Valle d'Aosta è una di quelle che il monitor oggi non vede (RIPRESA §4.4).
-- ---------------------------------------------------------------------------

-- prima: dominio verificante (atteso: true; se false, FERMARSI)
select public.bando_dominio_verificante(public.dominio_di(
  'https://www.regione.vda.it/agricoltura/CSR_2023_2027/bandi_interventi_strutturali/srd03_investimenti_diversificazione_attivita_nonagricole_i.aspx'));

select public.bando_registra_evento(
  p_bando_id    => 455779,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => '{"data_scadenza": "2026-10-30", "ora_scadenza": "23:59", "stato_bando": "aperto"}'::jsonb,
  p_url_prova   => 'https://www.regione.vda.it/agricoltura/CSR_2023_2027/bandi_interventi_strutturali/srd03_investimenti_diversificazione_attivita_nonagricole_i.aspx',
  p_citazione   => 'Si precisa che con PF n. 654 del 14 agosto 2026 la scadenza è stata prorogata alle ore 23.59 del 30 ottobre 2026.',
  p_data_evento => '2026-08-14',
  p_applica     => true,
  p_metodo      => 'correzione manuale del committente (revisione del 29/09): proroga non vista dal monitor'
);
-- atteso: {"id": <nuovo>, "nuovo": true, "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 | 23:59:00 | true)
select stato_bando, data_scadenza, ora_scadenza, data_scadenza_verificata
  from bando where id = 455779;
