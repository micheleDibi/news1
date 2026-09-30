-- ==========================================
-- Correzioni dell'01/10/2026, DB «bandi»
-- ==========================================
-- NON rieseguire dopo l'esecuzione:
-- ESEGUITO il 30/09/2026 sera nella
--   versione chat (stessi 31 eventi).
--   NON rieseguire.
-- ==========================================
-- Scritto il 30/09/2026 da «db», giro
-- «ripresa bandi, ottobre 2026» (task T-D3).
-- Ogni data è stata letta sulla pagina
-- dell'ente (o nell'atto PDF) il 30/09/2026
-- fra le 13:30 e le 14.
--
-- Cosa corregge:
-- A. 13 bandi pubblicati che a DB scadono il
--    30/09, ma l'ente ha spostato il termine
--    (12 proroghe) o la data a DB è
--    sbagliata (1). Senza correzione il cron
--    li chiude alle 00:05 dell'01/10 e il
--    sito li mostra chiusi.
-- B. 18 bandi «in apertura» con la data di
--    apertura già passata (query 12 di
--    RIPRESA §3.2): per l'ente 16 sono
--    aperti e 2 sono già chiusi.
-- C. In fondo, solo commenti: i casi
--    guardati e non corretti, e perché.
--
-- Come si esegue:
-- un blocco alla volta nel SQL Editor, fuori
--   dall'ora e mezza prima dei giri delle
--   00, 06, 12 e 18. Prima il blocco 0. Dopo
--   ogni chiamata, la select di controllo
--   deve dare il valore scritto sotto
--   «atteso».
--
-- Se il file gira dopo le 00:05 dell'01/10:
-- i bandi della parte A risultano già
--   «chiuso» nel controllo «prima». È
--   previsto: la proroga li riporta ad
--   «aperto» (chiuso → aperto per una
--   proroga del worker è nella lista
--   bianca).
--
-- Se il file gira due volte:
-- la RPC riconosce l'evento già registrato
--   (stesso bando, tipo, valore e data) e
--   risponde {"nuovo": false, "applicato":
--   true}: non scrive niente.
--
--
-- Provato su Postgres 17 effimero con le
-- RPC vere (04 e 11), tre volte: con lo
-- stato di oggi (31 eventi nuovi e
-- applicati), rieseguito subito dopo (0
-- nuovi, bandi invariati), e con i bandi
-- della parte A già chiusi dal cron
-- (stesso risultato della prima prova).
--
-- La stessa correzione in forma compatta,
-- da incollare in chat: correzioni-
-- 2026-10-01-chat.sql. I due file sono
-- intercambiabili (provato).
--
-- Niente UPDATE diretti: stato e date
-- passano da bando_registra_evento.
-- ==========================================


-- ------------------------------------------
-- 0. I domini delle prove sono verificanti
-- ------------------------------------------
select h,
  public.bando_dominio_verificante(
    public.dominio_di('https://' || h))
  from unnest(array[
    'agricoltura.regione.emilia-romagna.it',
    'bandi.regione.piemonte.it',
    'www.regione.toscana.it',
    'applicazioni.regione.umbria.it',
    'www.regione.campania.it',
    'www.regione.lazio.it',
    'bandi.regione.veneto.it',
    'coesione.regione.abruzzo.it',
    'www.regione.sardegna.it',
    'www.regione.liguria.it',
    'www.lazioeuropa.it'
  ]) as h;
-- atteso: 11 righe, tutte true. Se una è
-- false, saltare i blocchi con quel dominio
-- (l'evento nascerebbe non verificato e
-- fuori dal box).


-- ==========================================
-- PARTE A. Scadenze del 30/09 spostate
-- ==========================================

-- ------------------------------------------
-- A1. Bando 17642: GAL Delta 2000,
--     agriturismo (SRD03).
--     A DB scade il 30/09. Per l'ente:
--     2026-11-20 ore 13:00.
--     Sulla stessa pagina: «Proroga
--     approvata con Deliberazione n. 7 del
--     1° settembre 2026».
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17642;

select public.bando_registra_evento(
  p_bando_id    => 17642,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-11-20',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-delta-200'
    || '0-agriturismo',
  p_citazione   =>
    '20 novembre 2026 13:00 - Scadenza dei '
    || 'termini per partecipare al bando',
  p_data_evento => '2026-09-01',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-11-20 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17642;


-- ------------------------------------------
-- A2. Bando 17776: GAL Delta 2000,
--     infrastrutture ricreative (SRD07).
--     A DB scade il 30/09. Per l'ente:
--     2026-11-20 ore 13:00.
--     Il PDF del bando prorogato: «approvata
--     con Delibera del CDA n.8 del
--     17/09/2026».
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17776;

select public.bando_registra_evento(
  p_bando_id    => 17776,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-11-20',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-delta-200'
    || '0-srd07-azione-5-infrastrutture-ric'
    || 'reative',
  p_citazione   =>
    '20 novembre 2026 13:00 - Scadenza dei '
    || 'termini per partecipare al bando',
  p_data_evento => '2026-09-17',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-11-20 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17776;


-- ------------------------------------------
-- A3. Bando 17753: GAL Appennino Bolognese,
--     agriturismo.
--     A DB scade il 30/09. Per l'ente:
--     2026-11-30 ore 13:00.
--     Il PDF del bando: «prorogato con
--     delibera del Consiglio di
--     Amministrazione del GAL appennino
--     Bolognese n° 11 del 14 settembre
--     2026».
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17753;

select public.bando_registra_evento(
  p_bando_id    => 17753,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-11-30',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-appennino'
    || '-bolognese-agriturismo',
  p_citazione   =>
    '30 novembre 2026 13:00 - Scadenza dei '
    || 'termini per partecipare al bando',
  p_data_evento => '2026-09-14',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-11-30 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17753;


-- ------------------------------------------
-- A4. Bando 17822: GAL del Ducato, attività
--     commerciali e turistiche.
--     A DB scade il 30/09. Per l'ente:
--     2026-11-06 ore 13:00.
--     Allegato «..._proroga_6.11.26.pdf».
--     L'atto di proroga non è citato:
--     data_evento è l'ultimo aggiornamento
--     della pagina (22/09/2026).
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17822;

select public.bando_registra_evento(
  p_bando_id    => 17822,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-11-06',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-ducato-at'
    || 'tivit-commerciali-turismo',
  p_citazione   =>
    '06 novembre 2026 13:00 - Scadenza dei '
    || 'termini per partecipare al bando',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-11-06 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17822;


-- ------------------------------------------
-- A5. Bando 17824: GAL del Ducato,
--     trasformazione prodotti (SRD03 d).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-30 ore 13:00.
--     Allegato «..._proroga_30.10.2026.pdf».
--     data_evento: ultimo aggiornamento
--     della pagina (22/09/2026).
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17824;

select public.bando_registra_evento(
  p_bando_id    => 17824,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-ducato-tr'
    || 'asformazione-prodotti-agricoli',
  p_citazione   =>
    '30 ottobre 2026 13:00 - Scadenza dei t'
    || 'ermini per partecipare al bando',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17824;


-- ------------------------------------------
-- A6. Bando 17839: GAL del Ducato,
--     enoturismo (SRD03 e).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-30 ore 13:00.
--     A DB l'ente è «Regione Emilia-Romagna»
--     (scheda ObiettivoEuropa): stessa
--     dotazione (300.000 euro) e stesso
--     intervento. Allegato «..._Enoturismo_p
--     roroga_30.10.2026.pdf».
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17839;

select public.bando_registra_evento(
  p_bando_id    => 17839,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://agricoltura.regione.emilia-rom'
    || 'agna.it/sviluppo-rurale-23-27/oppor'
    || 'tunita/bandi-gal/2026/gal-ducato-en'
    || 'oturismo',
  p_citazione   =>
    '30 ottobre 2026 13:00 - Scadenza dei t'
    || 'ermini per partecipare al bando',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 17839;


-- ------------------------------------------
-- A7. Bando 30537: Piemonte, danni biotici
--     (SRD06 az. 1.1).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-30 ore 18:00.
--     DD 897 del 23/09/2026. La pagina
--     scrive 17:59, l'atto 18:00: vale
--     l'atto. Il 342849 (A8) è un doppione
--     dello stesso bando.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 30537;

select public.bando_registra_evento(
  p_bando_id    => 30537,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '18:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/syst'
    || 'em/files/DD%20897_23settembre2026_p'
    || 'roroga%20bando%203_2026_SDR06.1.pdf',
  p_citazione   =>
    'posticipando la data di scadenza dalle'
    || ' ore 18:00 di mercoledì 30 settembr'
    || 'e 2026 alle ore 18:00 di venerdì 30'
    || ' ottobre 2026',
  p_data_evento => '2026-09-23',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 |
--   18:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 30537;


-- ------------------------------------------
-- A8. Bando 342849: Piemonte, danni biotici
--     (doppione di A7).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-30 ore 18:00.
--     Stessa prova di A7. Resta da fondere
--     con A7 (non qui).
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 342849;

select public.bando_registra_evento(
  p_bando_id    => 342849,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '18:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/syst'
    || 'em/files/DD%20897_23settembre2026_p'
    || 'roroga%20bando%203_2026_SDR06.1.pdf',
  p_citazione   =>
    'posticipando la data di scadenza dalle'
    || ' ore 18:00 di mercoledì 30 settembr'
    || 'e 2026 alle ore 18:00 di venerdì 30'
    || ' ottobre 2026',
  p_data_evento => '2026-09-23',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 |
--   18:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 342849;


-- ------------------------------------------
-- A9. Bando 356672: Toscana, risorse
--     genetiche forestali (SRA31).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-30 ore 13:00.
--     Decreto dirigenziale 21128 del
--     24/09/2026.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 356672;

select public.bando_registra_evento(
  p_bando_id    => 356672,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '13:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.toscana.it/-/risor'
    || 'se-genetiche-forestali-contributi-p'
    || 'er-conservazione-uso-e-sviluppo-sos'
    || 'tenibile-il-bando-2026',
  p_citazione   =>
    'proroga per presentare le domande di a'
    || 'iuti fino alle ore 13 del 30 ottobr'
    || 'e 2026 , con decreto dirigenziale 2'
    || '1128 del 24 settembre 2026',
  p_data_evento => '2026-09-24',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-30 |
--   13:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 356672;


-- ------------------------------------------
-- A10. Bando 366543: Umbria, azioni pilota
--     innovazione (SRG08).
--     A DB scade il 30/09. Per l'ente:
--     2026-10-10.
--     La scheda regionale elenca fra gli
--     atti la «D.D n. 9451 del 23/09/2026 -
--     Bur n. 46», da cui la data
--     dell'evento. L'ora non è scritta. È
--     uno dei bandi che il monitor non ha
--     potuto classificare il 26/09 col
--     credito a zero.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 366543;

select public.bando_registra_evento(
  p_bando_id    => 366543,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-10',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://applicazioni.regione.umbria.it'
    || '/widget/bandi1?p_p_id=bandi_WAR_ban'
    || 'diportlet&p_p_lifecycle=1&p_p_state'
    || '=maximized&p_p_mode=view&_bandi_WAR'
    || '_bandiportlet_codBando=2026-002-776'
    || '1&_bandi_WAR_bandiportlet_javax.por'
    || 'tlet.action=viewDettaglio',
  p_citazione   =>
    'Presentazione domanda Dal 15/07/2026 A'
    || 'l 10/10/2026',
  p_data_evento => '2026-09-23',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-10 |
--   NULL | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 366543;


-- ------------------------------------------
-- A11. Bando 749531: Campania, inclusione
--     persone con disabilità.
--     A DB scade il 30/09. Per l'ente:
--     2026-10-14 ore 23:59.
--     Comunicato del 30/09/2026 sulla pagina
--     della Regione.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 749531;

select public.bando_registra_evento(
  p_bando_id    => 749531,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-10-14',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.campania.it/region'
    || 'e-informa/notizie/progetti-territor'
    || 'iali-finalizzati-all-inclusione-all'
    || '-autonomia-persone-disabilita-appro'
    || 'vato-l-avviso-pubblico',
  p_citazione   =>
    'la scadenza della presentazione delle '
    || 'proposte progettuali, originariamen'
    || 'te prevista alle ore 23:59 del 30/0'
    || '9/2026, è prorogata alle 23:59 del '
    || '14/10/2026',
  p_data_evento => '2026-09-30',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-10-14 |
--   23:59:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 749531;


-- ------------------------------------------
-- A12. Bando 18305: Lazio, Acchiappa
--     Talenti.
--     A DB scade il 30/09. Per l'ente:
--     2026-12-22 ore 17:00.
--     Sulla stessa pagina, fra gli atti:
--     «Determinazione n. G12900 del
--     23/09/2026 - Avviso Acchiappa Talenti:
--     Approvazione elenchi delle domande
--     relative alla 8° finestra mensile e
--     proroga dei termini». Avviso a
--     finestre mensili.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 18305;

select public.bando_registra_evento(
  p_bando_id    => 18305,
  p_tipo        => 'proroga',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-12-22',
    'ora_scadenza', '17:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.lazio.it/documenti'
    || '/86812',
  p_citazione   =>
    'Data di scadenza: Mar, 22/12/2026 - 17'
    || ':00',
  p_data_evento => '2026-09-23',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): pror'
    || 'oga letta sulla pagina ufficiale'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2026-12-22 |
--   17:00:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 18305;


-- ------------------------------------------
-- A13. Bando 1045996: Veneto, edilizia
--     scolastica a sportello.
--     A DB scade il 30/09. Per l'ente:
--     2027-09-30 ore 23:59.
--     Non è una proroga: la data a DB è
--     sbagliata di un anno (viene da
--     ObiettivoEuropa). L'avviso (DGR 935
--     del 31/08/2026) tiene aperto lo
--     sportello «fino all'esaurimento delle
--     risorse»; il portale regionale dà come
--     scadenza il 30/09/2027 alle 23:59.
--     Tipo «rettifica»: aperto → aperto e
--     chiuso → aperto per il worker sono
--     nella lista bianca.
-- ------------------------------------------

-- prima (atteso: aperto | 2026-09-30 |
--   NULL | false; «chiuso» dopo le 00:05
--   dell'01/10)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 1045996;

select public.bando_registra_evento(
  p_bando_id    => 1045996,
  p_tipo        => 'rettifica',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2027-09-30',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.veneto.it/Public'
    || '/Dettaglio?idAtto=13304&fromPage=El'
    || 'enco&high=',
  p_citazione   =>
    'Pubblicazione: 01/09/2026 Scadenza: 30'
    || '/09/2027 23:59',
  p_data_evento => '2026-08-31',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): scad'
    || 'enza a DB sbagliata di un anno'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto | 2027-09-30 |
--   23:59:00 | true)
select id, stato_bando, data_scadenza,
       ora_scadenza,
       data_scadenza_verificata
  from bando where id = 1045996;



-- ==========================================
-- PARTE B. «In apertura» già aperti
-- ==========================================
-- in apertura → aperto per un'apertura del
-- worker è nella lista bianca. La data
-- dell'evento è quella di apertura.

-- ------------------------------------------
-- B1. Bando 53179: Abruzzo, competenze
--     linguistiche (FSE+).
--     Per l'ente: aperto dal 2026-07-06 ore
--     09:00 al 2026-10-30 ore 20:00.
--     Il monitor ha già registrato in ombra
--     l'apertura (evento 9749, non
--     applicato): vedi la nota C4.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 53179;

select public.bando_registra_evento(
  p_bando_id    => 53179,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-07-06',
    'ora_apertura', '09:00',
    'data_scadenza', '2026-10-30',
    'ora_scadenza', '20:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://coesione.regione.abruzzo.it/av'
    || 'visi-pubblici/fse/potenziamento-com'
    || 'petenze-linguistiche-e-certificazio'
    || 'ne',
  p_citazione   =>
    'La candidatura può essere inviata a pa'
    || 'rtire dalle ore 09:00 del 6/07/2026'
    || ' e fino alle ore 20:00 del 30/10/20'
    || '26',
  p_data_evento => '2026-07-06',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-07-06 | 09:00:00 | 2026-10-30 |
--   20:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 53179;


-- ------------------------------------------
-- B2. Bando 20935: Sardegna, JTF Sulcis
--     2026.
--     Per l'ente: aperto dal 2026-07-15 ore
--     12:00 al 2026-10-02 ore 12:00.
--     Termine già prorogato dall'ente
--     l'11/09 (Det. 943/8561): la data di
--     scadenza a DB manca.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 20935;

select public.bando_registra_evento(
  p_bando_id    => 20935,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-07-15',
    'ora_apertura', '12:00',
    'data_scadenza', '2026-10-02',
    'ora_scadenza', '12:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.sardegna.it/atti-b'
    || 'andi-archivi/atti-amministrativi/ba'
    || 'ndi/178273476817963',
  p_citazione   =>
    'decorre dalle ore 12:00 del giorno 15.'
    || '07.2026 fino alle ore 12.00 del gio'
    || 'rno 02.10.2026',
  p_data_evento => '2026-07-15',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-07-15 | 12:00:00 | 2026-10-02 |
--   12:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 20935;


-- ------------------------------------------
-- B3. Bando 311893: Piemonte, aree di
--     sviluppo dell'artigianato.
--     Per l'ente: aperto dal 2026-07-21 ore
--     09:00.
--     Nessuna scadenza sulla pagina.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 311893;

select public.bando_registra_evento(
  p_bando_id    => 311893,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-07-21',
    'ora_apertura', '09:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/riconoscimento'
    || '-area-sviluppo-dellartigianato-ai-s'
    || 'ensi-dellarticolo-9-bis-lr-n-12009',
  p_citazione   =>
    'Stato Aperto Domande dal Mar, 21/07/20'
    || '26 - 09:00',
  p_data_evento => '2026-07-21',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-07-21 | 09:00:00 | invariata |
--   invariata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 311893;


-- ------------------------------------------
-- B4. Bando 140357: Abruzzo, Dote Lavoro
--     Giovani.
--     Per l'ente: aperto dal 2026-07-22 ore
--     09:00 al 2026-11-30 ore 20:00.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 140357;

select public.bando_registra_evento(
  p_bando_id    => 140357,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-07-22',
    'ora_apertura', '09:00',
    'data_scadenza', '2026-11-30',
    'ora_scadenza', '20:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://coesione.regione.abruzzo.it/av'
    || 'visi-pubblici/fse/dote-lavoro-giova'
    || 'ni',
  p_citazione   =>
    'a partire dalle ore 09:00:00 del giorn'
    || 'o 22/07/2026 ed entro e non oltre l'
    || 'e ore 20:00:00 del 30.11.2026',
  p_data_evento => '2026-07-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-07-22 | 09:00:00 | 2026-11-30 |
--   20:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 140357;


-- ------------------------------------------
-- B5. Bando 956582: Piemonte, ecomusei 2026.
--     Per l'ente: aperto dal 2026-09-04 al
--     2026-10-05 ore 23:59.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 956582;

select public.bando_registra_evento(
  p_bando_id    => 956582,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-04',
    'data_scadenza', '2026-10-05',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/ecomusei-bando'
    || '-2026',
  p_citazione   =>
    'Domande dal Ven, 04/09/2026 - 00:00 Sc'
    || 'adenza Lun, 05/10/2026 - 23:59',
  p_data_evento => '2026-09-04',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-04 | NULL | 2026-10-05 |
--   23:59:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 956582;


-- ------------------------------------------
-- B6. Bando 530270: Piemonte, buono
--     domiciliarità 2026/2027.
--     Per l'ente: aperto dal 2026-09-14 al
--     2026-11-02 ore 23:59.
--     B6, B7 e B8 sono tre schede dello
--     stesso bando (RIPRESA §4.1 g): si
--     correggono tutte e tre, la fusione è
--     un'altra cosa.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 530270;

select public.bando_registra_evento(
  p_bando_id    => 530270,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-14',
    'data_scadenza', '2026-11-02',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/scelta-sociale'
    || '-buono-domiciliarieta-20262027',
  p_citazione   =>
    'Domande dal Lun, 14/09/2026 - 00:00 Sc'
    || 'adenza Lun, 02/11/2026 - 23:59',
  p_data_evento => '2026-09-14',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-14 | NULL | 2026-11-02 |
--   23:59:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 530270;


-- ------------------------------------------
-- B7. Bando 556320: Piemonte, buono
--     domiciliarità (doppione).
--     Per l'ente: aperto dal 2026-09-14 al
--     2026-11-02 ore 23:59.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 556320;

select public.bando_registra_evento(
  p_bando_id    => 556320,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-14',
    'data_scadenza', '2026-11-02',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/scelta-sociale'
    || '-buono-domiciliarita-20262027',
  p_citazione   =>
    'Domande dal Lun, 14/09/2026 - 00:00 Sc'
    || 'adenza Lun, 02/11/2026 - 23:59',
  p_data_evento => '2026-09-14',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-14 | NULL | 2026-11-02 |
--   23:59:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 556320;


-- ------------------------------------------
-- B8. Bando 556361: Piemonte, buono
--     domiciliarità (doppione).
--     Per l'ente: aperto dal 2026-09-14 al
--     2026-11-02 ore 23:59.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 556361;

select public.bando_registra_evento(
  p_bando_id    => 556361,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-14',
    'data_scadenza', '2026-11-02',
    'ora_scadenza', '23:59',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/scelta-sociale'
    || '-buono-domiciliarita-20262027',
  p_citazione   =>
    'Domande dal Lun, 14/09/2026 - 00:00 Sc'
    || 'adenza Lun, 02/11/2026 - 23:59',
  p_data_evento => '2026-09-14',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-14 | NULL | 2026-11-02 |
--   23:59:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 556361;


-- ------------------------------------------
-- B9. Bando 307528: Abruzzo,
--     digitalizzazione delle PMI.
--     Per l'ente: aperto dal 2026-09-21 ore
--     10:00 al 2026-10-12 ore 10:00.
--     La pagina avvisa che le domande hanno
--     già superato la dotazione più il 30%,
--     ma «restano fermi i termini di
--     chiusura dello sportello» al 12/10.
--     Evento 11299 del monitor in coda: nota
--     C4.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 307528;

select public.bando_registra_evento(
  p_bando_id    => 307528,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-21',
    'ora_apertura', '10:00',
    'data_scadenza', '2026-10-12',
    'ora_scadenza', '10:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://coesione.regione.abruzzo.it/av'
    || 'visi-pubblici/fesr/digitalizzazione'
    || '-delle-pmi',
  p_citazione   =>
    'a partire dalle ore 10:00:00 del 21 se'
    || 'ttembre 2026 e fino alle ore 10:00:'
    || '00 del 12 ottobre 2026',
  p_data_evento => '2026-09-21',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-21 | 10:00:00 | 2026-10-12 |
--   10:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 307528;


-- ------------------------------------------
-- B10. Bando 1162829: Piemonte, IFTS
--     2026-2029.
--     Per l'ente: aperto dal 2026-09-21 ore
--     09:00 al 2026-10-09 ore 17:00.
--     Il 1162880 (B11) è un doppione dello
--     stesso bando.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1162829;

select public.bando_registra_evento(
  p_bando_id    => 1162829,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-21',
    'ora_apertura', '09:00',
    'data_scadenza', '2026-10-09',
    'ora_scadenza', '17:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/programmazione'
    || '-dellofferta-formativa-istruzione-f'
    || 'ormazione-tecnica-superiore-2026-20'
    || '29',
  p_citazione   =>
    'Domande dal Lun, 21/09/2026 - 09:00 Sc'
    || 'adenza Ven, 09/10/2026 - 17:00',
  p_data_evento => '2026-09-21',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-21 | 09:00:00 | 2026-10-09 |
--   17:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1162829;


-- ------------------------------------------
-- B11. Bando 1162880: Piemonte, IFTS
--     2026-2029 (doppione).
--     Per l'ente: aperto dal 2026-09-21 ore
--     09:00 al 2026-10-09 ore 17:00.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1162880;

select public.bando_registra_evento(
  p_bando_id    => 1162880,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-21',
    'ora_apertura', '09:00',
    'data_scadenza', '2026-10-09',
    'ora_scadenza', '17:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/programmazione'
    || '-dellofferta-formativa-istruzione-f'
    || 'ormazione-tecnica-superiore-2026-20'
    || '29',
  p_citazione   =>
    'Domande dal Lun, 21/09/2026 - 09:00 Sc'
    || 'adenza Ven, 09/10/2026 - 17:00',
  p_data_evento => '2026-09-21',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-21 | 09:00:00 | 2026-10-09 |
--   17:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1162880;


-- ------------------------------------------
-- B12. Bando 1262520: Piemonte, popolazione
--     felina nei Comuni.
--     Per l'ente: aperto dal 2026-09-30 ore
--     10:00 al 2026-11-06 ore 12:00.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1262520;

select public.bando_registra_evento(
  p_bando_id    => 1262520,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-30',
    'ora_apertura', '10:00',
    'data_scadenza', '2026-11-06',
    'ora_scadenza', '12:00',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://bandi.regione.piemonte.it/cont'
    || 'ributi-finanziamenti/progetti-riqua'
    || 'lificazione-urbana-ambientale-trami'
    || 'te-gestione-popolazione-felina-0',
  p_citazione   =>
    'Domande dal Mer, 30/09/2026 - 10:00 Sc'
    || 'adenza Ven, 06/11/2026 - 12:00',
  p_data_evento => '2026-09-30',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-30 | 10:00:00 | 2026-11-06 |
--   12:00:00)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 1262520;


-- ------------------------------------------
-- B13. Bando 512533: Liguria, sviluppo e
--     produzione audiovisiva.
--     Per l'ente: aperto dal 2026-09-22 al
--     2026-10-02.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 512533;

select public.bando_registra_evento(
  p_bando_id    => 512533,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-22',
    'data_scadenza', '2026-10-02',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.liguria.it/homepag'
    || 'e-fondi-europei/cosa-cerchi/le-prog'
    || 'rammazioni-fesr/programma-operativo'
    || '-fesr-2021-2027/bandi-por-fesr-2021'
    || '-2027/publiccompetition/4703:azione'
    || '-134-audiovisivi-sviluppo-produzion'
    || 'i-2026.html',
  p_citazione   =>
    'Data apertura: 22 Settembre 2026 Data '
    || 'chiusura: 02 Ottobre 2026',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-22 | NULL | 2026-10-02 | NULL)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 512533;


-- ------------------------------------------
-- B14. Bando 512534: Liguria, attrazione
--     produzioni audiovisive.
--     Per l'ente: aperto dal 2026-09-22 al
--     2026-10-02.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 512534;

select public.bando_registra_evento(
  p_bando_id    => 512534,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-22',
    'data_scadenza', '2026-10-02',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.liguria.it/homepag'
    || 'e-fondi-europei/cosa-cerchi/le-prog'
    || 'rammazioni-fesr/programma-operativo'
    || '-fesr-2021-2027/bandi-por-fesr-2021'
    || '-2027/publiccompetition/4702:azione'
    || '134-attrazione-audiovisivo-2026.htm'
    || 'l',
  p_citazione   =>
    'Data apertura: 22 Settembre 2026 Data '
    || 'chiusura: 02 Ottobre 2026',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-22 | NULL | 2026-10-02 | NULL)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 512534;


-- ------------------------------------------
-- B15. Bando 852021: Liguria, fondo di
--     capitale di rischio.
--     Per l'ente: aperto dal 2026-09-22.
--     Nessuna data di chiusura sulla pagina.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 852021;

select public.bando_registra_evento(
  p_bando_id    => 852021,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-22',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.liguria.it/homepag'
    || 'e-fondi-europei/cosa-cerchi/le-prog'
    || 'rammazioni-fesr/programma-operativo'
    || '-fesr-2021-2027/bandi-por-fesr-2021'
    || '-2027/publiccompetition/4731:azione'
    || '-136-startupligurcapital.html',
  p_citazione   =>
    'Data apertura: 22 Settembre 2026',
  p_data_evento => '2026-09-22',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-22 | NULL | invariata |
--   invariata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 852021;


-- ------------------------------------------
-- B16. Bando 340501: Liguria,
--     riqualificazione alloggi sociali.
--     Per l'ente: aperto dal 2026-09-29 al
--     2026-10-06.
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | con la data di apertura passata)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 340501;

select public.bando_registra_evento(
  p_bando_id    => 340501,
  p_tipo        => 'apertura',
  p_origine     => 'worker',
  p_campo       => 'data_apertura',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-09-29',
    'data_scadenza', '2026-10-06',
    'stato_bando', 'aperto'),
  p_url_prova   =>
    'https://www.regione.liguria.it/homepag'
    || 'e-fondi-europei/cosa-cerchi/le-prog'
    || 'rammazioni-fesr/programma-operativo'
    || '-fesr-2021-2027/bandi-por-fesr-2021'
    || '-2027/publiccompetition/4692:fesr-2'
    || '021-2027-2-11-1-riqualificazione-en'
    || 'ergeticaerpers.html',
  p_citazione   =>
    'Data apertura: 29 Settembre 2026 Data '
    || 'chiusura: 06 Ottobre 2026',
  p_data_evento => '2026-09-29',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» con la data di apertura p'
    || 'assata, aperto per l''ente'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: aperto |
--   2026-09-29 | NULL | 2026-10-06 | NULL)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 340501;


-- ------------------------------------------
-- B17. Bando 38472: Lazio, avviamento al
--     lavoro disabili (Frosinone).
--     Per l'ente è già chiuso: domande dal
--     2026-07-20 ore 09:00 fino al
--     2026-07-31 ore 14:00. Nessuna apertura
--     da applicare: si rettificano le date,
--     e al minuto 5 dell'ora successiva il
--     cron lo porta a «chiuso» (in apertura
--     → chiuso per il cron è nella lista
--     bianca).
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | data di scadenza NULL)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 38472;

select public.bando_registra_evento(
  p_bando_id    => 38472,
  p_tipo        => 'rettifica',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_apertura', '2026-07-20',
    'ora_apertura', '09:00',
    'data_scadenza', '2026-07-31',
    'ora_scadenza', '14:00'),
  p_url_prova   =>
    'https://www.lazioeuropa.it/bandi/avvia'
    || 'mento-al-lavoro-delle-persone-con-d'
    || 'isabilita-art-1-comma-1-della-l-68-'
    || '99-presso-datori-di-lavoro-pubblici'
    || '-provincia-di-frosinone/',
  p_citazione   =>
    'a partire dalle ore 09.00 del 20 lugli'
    || 'o 2026 fino alle ore 14.00 del 31 l'
    || 'uglio 2026',
  p_data_evento => '2026-07-20',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» già chiuso per l''ente, d'
    || 'ate rettificate; lo chiude il cron'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: in apertura prossimamente
--   | ... | 2026-07-31 | 14:00:00; dopo il
--   minuto 5 dell'ora successiva: chiuso)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 38472;


-- ------------------------------------------
-- B18. Bando 412536: Lazio, percorsi IeFP
--     tecnologico-professionali.
--     Per l'ente è già chiuso: domande fino
--     al 2026-08-20 ore 12:00. Nessuna
--     apertura da applicare: si rettificano
--     le date, e al minuto 5 dell'ora
--     successiva il cron lo porta a «chiuso»
--     (in apertura → chiuso per il cron è
--     nella lista bianca).
-- ------------------------------------------

-- prima (atteso: in apertura prossimamente
--   | data di scadenza NULL)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 412536;

select public.bando_registra_evento(
  p_bando_id    => 412536,
  p_tipo        => 'rettifica',
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_build_object(
    'data_scadenza', '2026-08-20',
    'ora_scadenza', '12:00'),
  p_url_prova   =>
    'https://www.lazioeuropa.it/bandi/perco'
    || 'rsi-di-filiera-formativa-tecnologic'
    || 'o-professionale-di-prima-seconda-e-'
    || 'terza-annualita-per-la-f-2026-2027/',
  p_citazione   =>
    'non oltre le ore 12:00 del termine per'
    || 'entorio del 20 agosto 2026',
  p_data_evento => '2026-07-28',
  p_applica     => true,
  p_metodo      =>
    'correzione manuale (T-D3, 01/10): «in '
    || 'apertura» già chiuso per l''ente, d'
    || 'ate rettificate; lo chiude il cron'
);
-- atteso: {"id": <nuovo>, "nuovo": true,
--   "applicato": true}

-- dopo (atteso: in apertura prossimamente
--   | ... | 2026-08-20 | 12:00:00; dopo il
--   minuto 5 dell'ora successiva: chiuso)
select id, stato_bando, data_apertura,
       ora_apertura, data_scadenza,
       ora_scadenza
  from bando where id = 412536;



-- ------------------------------------------
-- Controllo finale, dopo tutti i blocchi
-- ------------------------------------------
-- atteso: 31 righe; nessun «in apertura»
-- tranne B17-B18 nell'ora prima del cron;
-- tutte le date di scadenza nel futuro
-- tranne B17-B18.
select id, stato_bando, data_apertura,
       data_scadenza, ora_scadenza
  from bando
 where id in (
    17642, 17776, 17753, 17822, 17824, 17839,
    30537, 342849, 356672, 366543, 749531,
    18305, 1045996, 53179, 20935, 311893,
    140357, 956582, 530270, 556320, 556361,
    307528, 1162829, 1162880, 1262520,
    512533, 512534, 852021, 340501, 38472,
    412536)
 order by id;


-- ==========================================
-- PARTE C. Guardati e non corretti
-- ==========================================

-- C1. I 120 pubblicati con scadenza 30/09
--   (misura del 30/09 alle 13:30): 85 hanno
--   sulla pagina dell'ente la scadenza del
--   30/09 o una chiusura precedente (niente
--   da fare: stanotte li chiude il cron), 13
--   sono nella parte A, 22 non si sono
--   potuti decidere (C2, C3 e C5).

-- C2. Prova certa ma non usabile. 255055
--   (SMAQ Veneto, Fondazioni Cariparo e
--   Cariverona): prorogato al 30/10 (digital
--   ambassador) e al 06/11 ore 13 (aziende),
--   ma fondazionecariparo.it non è un
--   dominio verificante: l'evento nascerebbe
--   non verificato. Resta da decidere a
--   mano.

-- C3. Pagina non leggibile o non decisiva:
--   17633 e 2308 (Basilicata, connessione
--   rifiutata: è il DNS rotto di RIPRESA
--   §4.4); 229687, 352805, 352806, 352814
--   (DNS delle fondazioni non risolve);
--   1016536 e 1046003 (Marche, pagina
--   bloccata da un anti-bot); 1256672
--   (Abruzzo, certificato non valido); 17886
--   (Camera di commercio di Milano, pagina
--   vuota senza JavaScript); 18082, 18195,
--   18211, 143119 (fondazioni, scadenza solo
--   nei PDF o non scritta); 112850
--   (Calabria, date solo nell'atto PDF);
--   749524 (Finmolise, nessuna data); 156488
--   (Irpinia Sannio, solo l'apertura);
--   562292 e 562293 (FRIHUB, solo date di
--   apertura).

-- C4. Eventi del monitor in coda. 9749
--   (53179) e 11299 (307528) sono aperture
--   già registrate in ombra, verificate e
--   non applicate. Dopo B1 e B9 restano in
--   coda. Attenzione: se un giorno si
--   lanciasse applica-eventi sul tipo
--   apertura dopo la chiusura di quei bandi,
--   la RPC porterebbe il bando da chiuso ad
--   aperto (la lista bianca guarda solo
--   stato di partenza, di arrivo e attore).
--   Vale per ogni apertura vecchia in coda.
--   MONITOR_TIPI_ATTIVI non li tocca
--   (applica solo gli eventi nati nel giro):
--   il rischio è solo un applica-eventi
--   --tipo apertura lanciato a mano.

-- C5. Casi strani, da guardare con calma.
--   18115 (Cosenza, filiera agroalimentare):
--   la pagina dice che il bando «sarà
--   attivato prossimamente», quindi forse
--   non è mai stato aperto. 18218 (Lecce,
--   transizione energetica): la pagina dà
--   domande fino al 28/02/2026, non al
--   30/09. 17845 (E-R, SRD03 azione a,
--   716.438 euro): la pagina collegata è di
--   un altro GAL (770.000 euro, scadenza
--   11/01/2027). 411542 (Gran Sasso, doppia
--   transizione): sportello chiuso in
--   anticipo il 22/09; stanotte lo chiude
--   comunque il cron.

-- C6. Dei 21 «in apertura» della query 12,
--   tre non sono qui: 2955 (pagina di
--   pre-informazione del Piemonte, senza
--   date), 2308 (Basilicata, non
--   raggiungibile), 661135 (aperto dal 01/09
--   al 30/09 alle 12: stanotte il cron lo
--   chiude, ed è giusto).

-- C7. Doppioni visti lungo il controllo, da
--   fondere a parte: 30537 e 342849; 530270,
--   556320 e 556361; 1162829 e 1162880;
--   661135 e 736932; 2912 e 17558; 352150 e
--   356653; 2649 e 17727.
