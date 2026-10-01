-- ==========================================
-- correzioni-giro-3-sera.sql — DB «bandi»
-- Tre bandi aperti salvati come «chiuso»
-- ==========================================
-- Scritto l'01/10/2026 sera dal lead, dopo
-- il primo giro del giro 3 (avviso
-- «fermi_in_lavorazione» di salute).
--
-- Perché
--   Il preprocess ha accettato lo stato
--   «chiuso» proposto dal modello anche con
--   la scadenza nel futuro: la regola di
--   riconciliazione forza «chiuso» solo con
--   la scadenza passata, non il contrario.
--   Un bando «processed» e «chiuso» non
--   passa da enrich e SEO: resta nascosto.
--   Le pagine ufficiali, lette l'01/10 sera:
--   - 1262487 Piemonte, fiere artigiane:
--     «Stato Aperto», sportello riaperto il
--     24/09 (DD 410), scadenza 01/11/2026;
--   - 1262812 Lazio, Global Health
--     Exhibition 2026: «Aperto», scadenza
--     06/10/2026;
--   - 2773 Marche, master giovani laureati:
--     scadenza 26/07/2027, nessuna chiusura.
--
-- Cosa fa
--   Solo UPDATE di stato_bando da «chiuso»
--   ad «aperto» su questi tre id, e solo se
--   la riga è ancora non pubblicata,
--   «processed», «chiuso» e con la scadenza
--   da oggi in poi. Su una riga non
--   pubblicata il trigger dello stato lascia
--   decidere la pipeline (migrazione 14,
--   bando_stato_solo_via_evento).
--   stato_bando_verificato resta false.
--   Al giro dopo enrich e SEO li pubblicano.
--
-- Ordine
--   Prima del giro delle 00:00.
--   Rieseguibile: la seconda volta
--   aggiorna 0 righe.
--
-- Come si applica
--   SQL Editor, un blocco alla volta: 0
--   (sola lettura), 1 (scrittura), 2
--   (verifica, sola lettura).
-- ==========================================


-- 0. Anteprima (sola lettura)
-- atteso: 3 righe, tutte «chiuso»,
--   «processed», pubblicato false.
select id, stato_bando,
       stato_processing, pubblicato,
       data_scadenza
  from public.bando
 where id in (2773, 1262487, 1262812)
 order by id;


-- 1. Scrittura
-- atteso: 3 righe (2773, 1262487,
--   1262812). Rieseguita: 0 righe.
update public.bando
   set stato_bando = 'aperto'
 where id in (2773, 1262487, 1262812)
   and stato_bando = 'chiuso'
   and stato_processing = 'processed'
   and not pubblicato
   and data_scadenza >=
       (now() at time zone
        'Europe/Rome')::date
returning id, stato_bando;


-- 2. Verifica (sola lettura)
-- atteso: 3 righe «aperto», «processed».
--   Dopo il giro delle 00:00:
--   «completed» e pubblicato true.
select id, stato_bando,
       stato_processing, pubblicato
  from public.bando
 where id in (2773, 1262487, 1262812)
 order by id;
