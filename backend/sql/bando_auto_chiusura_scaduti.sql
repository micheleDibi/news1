-- ============================================================================
-- Chiusura automatica dei bandi scaduti (pg_cron) — DB Supabase BANDI
-- ============================================================================
-- Problema: la colonna `stato_bando` viene scritta dal preprocess dello
-- scraper e mai piu' aggiornata → i bandi restavano "aperto" per sempre anche
-- dopo la scadenza.
--
-- Soluzione a due livelli:
--   1. Frontend: stato EFFETTIVO derivato a render-time (effectiveStatoBando
--      in src/lib/supabase-bandi.ts) — copre in tempo reale anche la finestra
--      tra la mezzanotte e l'esecuzione del job, e ogni eventuale fallimento
--      del job.
--   2. DB (questo script): job giornaliero pg_cron che rende persistente lo
--      stato, cosi' anche il dato grezzo e' corretto per qualsiasi consumer.
--
-- Regola: un bando e' "chiuso" dal giorno SUCCESSIVO alla data di scadenza
-- (il giorno stesso le domande sono ancora ammesse, tipicamente fino alle
-- 23:59). Fuso di riferimento: Europe/Rome. La scadenza puo' solo chiudere,
-- mai riaprire.
--
-- COME ESEGUIRLO: Supabase Dashboard → SQL Editor → incolla ed esegui.
-- (pg_cron gira con orari in UTC; 23:20 UTC = 00:20 Roma d'inverno,
--  01:20 Roma d'estate — in entrambi i casi subito dopo la mezzanotte).
-- ============================================================================

-- 1) Abilita l'estensione pg_cron (no-op se gia' abilitata; in alternativa
--    Dashboard → Database → Extensions → pg_cron).
create extension if not exists pg_cron;

-- 2) Job giornaliero. cron.schedule con lo stesso nome sostituisce il job
--    esistente, quindi lo script e' rieseguibile senza duplicare.
select cron.schedule(
  'chiudi-bandi-scaduti',
  '20 23 * * *',
  $$
  update bando
     set stato_bando = 'chiuso'
   where data_scadenza < (now() at time zone 'Europe/Rome')::date
     and stato_bando is distinct from 'chiuso'
  $$
);

-- 3) (Retroattivo) Stessa UPDATE una tantum per il pregresso.
--    NB: gia' eseguita il 2026-07-06 via API service-role (101 righe, tutte
--    'aperto' → 'chiuso'). Rieseguirla e' innocuo: e' idempotente.
update bando
   set stato_bando = 'chiuso'
 where data_scadenza < (now() at time zone 'Europe/Rome')::date
   and stato_bando is distinct from 'chiuso';

-- ============================================================================
-- Verifiche
-- ============================================================================
-- Job registrato:
--   select jobid, jobname, schedule, active from cron.job;
-- Ultime esecuzioni:
--   select jobid, status, return_message, start_time
--     from cron.job_run_details order by start_time desc limit 10;
-- Non deve restare nessun bando scaduto non chiuso:
--   select count(*) from bando
--    where data_scadenza < (now() at time zone 'Europe/Rome')::date
--      and stato_bando is distinct from 'chiuso';
