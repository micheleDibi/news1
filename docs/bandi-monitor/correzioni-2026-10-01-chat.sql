-- ==========================================
-- Correzioni dell'01/10/2026: versione
-- compatta per la chat. DB «bandi».
-- ==========================================
-- NON rieseguire dopo l'esecuzione:
-- segnare qui la data: __/__/2026
-- ==========================================
-- Scritto il 30/09/2026 da «db» (T-D3). È la
-- stessa correzione di
-- correzioni-2026-10-01.sql, che resta il
-- riferimento con le prove bando per bando:
-- 13 scadenze del 30/09 spostate (A) e 18
-- «in apertura» con la data passata (B).
-- Si incollano quattro blocchi, uno alla
-- volta, fuori dall'ora e mezza prima dei
-- giri. Funziona anche dopo le 00:05
-- dell'01/10, quando il cron avrà chiuso i
-- bandi di A.
-- I due file sono intercambiabili: stessi
-- valori e stesse date, quindi la RPC
-- riconosce gli eventi già registrati
-- dall'altro. Rieseguito, A e B danno 0
-- righe. Provato su Postgres 17 effimero.
-- ==========================================

-- 0. Domini delle prove
-- atteso: 11 righe, tutte true.
-- Se una è false, FERMARSI e scrivere.
select h, public.bando_dominio_verificante(
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


-- A. 13 scadenze del 30/09 spostate
-- atteso: 13 righe, tutte con
--   "nuovo": true, "applicato": true.
--   Rieseguito: 0 righe.
with v(ids, t, sc, ora, ev, u, c) as (
values
('{17642}'::int[], 'proroga', '2026-11-20',
 '13:00', '2026-09-01', null,
 '20 novembre 2026 13:00'),
('{17776}', 'proroga', '2026-11-20',
 '13:00', '2026-09-17',
 'E:gal-delta-2000-srd07-azione-5-infrastr'
 || 'utture-ricreative',
 '20 novembre 2026 13:00'),
('{17753}', 'proroga', '2026-11-30',
 '13:00', '2026-09-14',
 'E:gal-appennino-bolognese-agriturismo',
 '30 novembre 2026 13:00'),
('{17822}', 'proroga', '2026-11-06',
 '13:00', '2026-09-22', null,
 '06 novembre 2026 13:00'),
('{17824}', 'proroga', '2026-10-30',
 '13:00', '2026-09-22', null,
 '30 ottobre 2026 13:00'),
('{17839}', 'proroga', '2026-10-30',
 '13:00', '2026-09-22',
 'E:gal-ducato-enoturismo',
 '30 ottobre 2026 13:00'),
('{30537,342849}', 'proroga', '2026-10-30',
 '18:00', '2026-09-23',
 'https://bandi.regione.piemonte.it/system'
 || '/files/DD%20897_23settembre2026_proro'
 || 'ga%20bando%203_2026_SDR06.1.pdf',
 'posticipando la data di scadenza dalle '
 || 'ore 18:00 di mercoledì 30 settembre '
 || '2026 alle ore 18:00 di venerdì 30 '
 || 'ottobre 2026'),
('{356672}', 'proroga', '2026-10-30',
 '13:00', '2026-09-24', null,
 'proroga per presentare le domande di '
 || 'aiuti fino alle ore 13 del 30 '
 || 'ottobre 2026 , con decreto '
 || 'dirigenziale 21128 del 24 settembre '
 || '2026'),
('{366543}', 'proroga', '2026-10-10',
 null, '2026-09-23', null,
 'Presentazione domanda Dal 15/07/2026 Al '
 || '10/10/2026'),
('{749531}', 'proroga', '2026-10-14',
 '23:59', '2026-09-30', null,
 'la scadenza della presentazione delle '
 || 'proposte progettuali, '
 || 'originariamente prevista alle ore '
 || '23:59 del 30/09/2026, è prorogata '
 || 'alle 23:59 del 14/10/2026'),
('{18305}', 'proroga', '2026-12-22',
 '17:00', '2026-09-23',
 'https://www.regione.lazio.it/documenti/8'
 || '6812',
 'Data di scadenza: Mar, 22/12/2026 - '
 || '17:00'),
('{1045996}', 'rettifica', '2027-09-30',
 '23:59', '2026-08-31',
 'https://bandi.regione.veneto.it/Public/D'
 || 'ettaglio?idAtto=13304&fromPage=Elenco'
 || '&high=',
 'Pubblicazione: 01/09/2026 Scadenza: '
 || '30/09/2027 23:59')
)
select b.id, public.bando_registra_evento(
  p_bando_id    => b.id,
  p_tipo        => v.t,
  p_origine     => 'worker',
  p_campo       => 'data_scadenza',
  p_valore_dopo => jsonb_strip_nulls(
    jsonb_build_object(
      'data_scadenza', v.sc,
      'ora_scadenza', v.ora,
      'stato_bando', 'aperto')),
  p_url_prova   => case
    when v.u is null
      then b.fonte_ufficiale_url
    when v.u like 'E:%' then
      'https://agricoltura.regione.emilia-'
      || 'romagna.it/sviluppo-rurale-23-27'
      || '/opportunita/bandi-gal/2026/'
      || substr(v.u, 3)
    else v.u end,
  p_citazione   => case
    when v.c like '% 2026 13:00'
      then v.c || ' - Scadenza dei termini'
        || ' per partecipare al bando'
    else v.c end,
  p_data_evento => v.ev::date,
  p_applica     => true,
  p_metodo      => 'correzione manuale'
    || ' (T-D3, 01/10), versione chat')
from v
cross join unnest(v.ids) as i(id)
join bando b on b.id = i.id
where b.data_scadenza = '2026-09-30'
order by b.id;


-- B. 18 «in apertura» con la data passata
-- atteso: 18 righe, tutte con
--   "nuovo": true, "applicato": true.
--   Rieseguito: 0 righe.
with v(ids, t, ap, oa, sc, os, ev, u, c)
as (values
('{53179}'::int[], 'apertura',
 '2026-07-06', '09:00', '2026-10-30',
 '20:00', '2026-07-06', null,
 'La candidatura può essere inviata a '
 || 'partire dalle ore 09:00 del '
 || '6/07/2026 e fino alle ore 20:00 del '
 || '30/10/2026'),
('{20935}', 'apertura',
 '2026-07-15', '12:00', '2026-10-02',
 '12:00', '2026-07-15',
 'https://www.regione.sardegna.it/atti-ban'
 || 'di-archivi/atti-amministrativi/bandi/'
 || '178273476817963',
 'decorre dalle ore 12:00 del giorno '
 || '15.07.2026 fino alle ore 12.00 del '
 || 'giorno 02.10.2026'),
('{311893}', 'apertura',
 '2026-07-21', '09:00', null,
 null, '2026-07-21',
 'P:riconoscimento-area-sviluppo-dellartig'
 || 'ianato-ai-sensi-dellarticolo-9-bis-lr'
 || '-n-12009',
 'Stato Aperto Domande dal Mar, '
 || '21/07/2026 - 09:00'),
('{140357}', 'apertura',
 '2026-07-22', '09:00', '2026-11-30',
 '20:00', '2026-07-22', null,
 'a partire dalle ore 09:00:00 del giorno '
 || '22/07/2026 ed entro e non oltre le '
 || 'ore 20:00:00 del 30.11.2026'),
('{956582}', 'apertura',
 '2026-09-04', null, '2026-10-05',
 '23:59', '2026-09-04',
 'P:ecomusei-bando-2026',
 'Domande dal Ven, 04/09/2026 - 00:00 '
 || 'Scadenza Lun, 05/10/2026 - 23:59'),
('{530270,556320,556361}', 'apertura',
 '2026-09-14', null, '2026-11-02',
 '23:59', '2026-09-14',
 'P:scelta-sociale-buono-domiciliarita-202'
 || '62027',
 'Domande dal Lun, 14/09/2026 - 00:00 '
 || 'Scadenza Lun, 02/11/2026 - 23:59'),
('{307528}', 'apertura',
 '2026-09-21', '10:00', '2026-10-12',
 '10:00', '2026-09-21', null,
 'a partire dalle ore 10:00:00 del 21 '
 || 'settembre 2026 e fino alle ore '
 || '10:00:00 del 12 ottobre 2026'),
('{1162829,1162880}', 'apertura',
 '2026-09-21', '09:00', '2026-10-09',
 '17:00', '2026-09-21',
 'P:programmazione-dellofferta-formativa-i'
 || 'struzione-formazione-tecnica-superior'
 || 'e-2026-2029',
 'Domande dal Lun, 21/09/2026 - 09:00 '
 || 'Scadenza Ven, 09/10/2026 - 17:00'),
('{1262520}', 'apertura',
 '2026-09-30', '10:00', '2026-11-06',
 '12:00', '2026-09-30',
 'P:progetti-riqualificazione-urbana-ambie'
 || 'ntale-tramite-gestione-popolazione-fe'
 || 'lina-0',
 'Domande dal Mer, 30/09/2026 - 10:00 '
 || 'Scadenza Ven, 06/11/2026 - 12:00'),
('{512533,512534}', 'apertura',
 '2026-09-22', null, '2026-10-02',
 null, '2026-09-22', null,
 'Data apertura: 22 Settembre 2026 Data '
 || 'chiusura: 02 Ottobre 2026'),
('{852021}', 'apertura',
 '2026-09-22', null, null,
 null, '2026-09-22', null,
 'Data apertura: 22 Settembre 2026'),
('{340501}', 'apertura',
 '2026-09-29', null, '2026-10-06',
 null, '2026-09-29', null,
 'Data apertura: 29 Settembre 2026 Data '
 || 'chiusura: 06 Ottobre 2026'),
('{38472}', 'rettifica',
 '2026-07-20', '09:00', '2026-07-31',
 '14:00', '2026-07-20',
 'https://www.lazioeuropa.it/bandi/avviame'
 || 'nto-al-lavoro-delle-persone-con-disab'
 || 'ilita-art-1-comma-1-della-l-68-99-pre'
 || 'sso-datori-di-lavoro-pubblici-provinc'
 || 'ia-di-frosinone/',
 'a partire dalle ore 09.00 del 20 luglio '
 || '2026 fino alle ore 14.00 del 31 '
 || 'luglio 2026'),
('{412536}', 'rettifica',
 null, null, '2026-08-20',
 '12:00', '2026-07-28',
 'https://www.lazioeuropa.it/bandi/percors'
 || 'i-di-filiera-formativa-tecnologico-pr'
 || 'ofessionale-di-prima-seconda-e-terza-'
 || 'annualita-per-la-f-2026-2027/',
 'non oltre le ore 12:00 del termine '
 || 'perentorio del 20 agosto 2026')
)
select b.id, public.bando_registra_evento(
  p_bando_id    => b.id,
  p_tipo        => v.t,
  p_origine     => 'worker',
  p_campo       => case v.t
    when 'apertura' then 'data_apertura'
    else 'data_scadenza' end,
  p_valore_dopo => jsonb_strip_nulls(
    jsonb_build_object(
      'data_apertura', v.ap,
      'ora_apertura', v.oa,
      'data_scadenza', v.sc,
      'ora_scadenza', v.os,
      'stato_bando', case v.t
        when 'apertura' then 'aperto'
        end)),
  p_url_prova   => case
    when v.u is null
      then b.fonte_ufficiale_url
    when v.u like 'P:%' then
      'https://bandi.regione.piemonte.it/c'
      || 'ontributi-finanziamenti/'
      || substr(v.u, 3)
    else v.u end,
  p_citazione   => v.c,
  p_data_evento => v.ev::date,
  p_applica     => true,
  p_metodo      => 'correzione manuale'
    || ' (T-D3, 01/10), versione chat')
from v
cross join unnest(v.ids) as i(id)
join bando b on b.id = i.id
where b.stato_bando =
        'in apertura prossimamente'
  and not b.data_scadenza_verificata
order by b.id;


-- Verifica finale
-- atteso: una riga 31 | 31 | {} (oppure
--   {38472,412536} nell'ultima colonna se
--   il cron non è ancora passato: sono i
--   due già chiusi, restano «in apertura»
--   fino al minuto 5 dell'ora dopo).
with a(id, sc) as (values
(17642,'2026-11-20'), (17753,'2026-11-30'),
(17776,'2026-11-20'), (17822,'2026-11-06'),
(17824,'2026-10-30'), (17839,'2026-10-30'),
(18305,'2026-12-22'), (20935,'2026-10-02'),
(30537,'2026-10-30'), (38472,'2026-07-31'),
(53179,'2026-10-30'), (140357,'2026-11-30'),
(307528,'2026-10-12'), (311893,null),
(340501,'2026-10-06'), (342849,'2026-10-30'),
(356672,'2026-10-30'), (366543,'2026-10-10'),
(412536,'2026-08-20'), (512533,'2026-10-02'),
(512534,'2026-10-02'), (530270,'2026-11-02'),
(556320,'2026-11-02'), (556361,'2026-11-02'),
(749531,'2026-10-14'), (852021,null),
(956582,'2026-10-05'),
(1045996,'2027-09-30'),
(1162829,'2026-10-09'),
(1162880,'2026-10-09'),
(1262520,'2026-11-06'))
select count(*) as bandi,
  count(*) filter (where ok) as giusti,
  array_agg(id) filter (where not ok)
    as da_guardare
from (select a.id,
  b.stato_bando in ('aperto', 'chiuso')
  and b.data_scadenza is not distinct
      from a.sc::date as ok
  from a join bando b on b.id = a.id) x;
