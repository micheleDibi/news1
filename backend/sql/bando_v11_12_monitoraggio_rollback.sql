-- ==========================================
-- bando_v11_12_monitoraggio_rollback.sql
-- DB bandi: rollback della migrazione 12
-- ==========================================
-- Toglie i cinque oggetti della 12 e
-- nient'altro:
--   monitoraggio_catalogo(text),
--   monitoraggio_job_orario(),
--   il trigger monitoraggio_riepilogo_ora,
--   le tabelle monitoraggio_riepilogo e
--   monitoraggio_chiave,
--   la funzione del trigger,
--   monitoraggio_riepilogo_ora().
--
-- ATTENZIONE: cancella il riepilogo e le
--   impronte delle chiavi. Dopo il rollback
--   il pannello riceve un errore di funzione
--   inesistente; se la 12 si riapplica,
--   l'impronta va reinserita.
--
-- Senza CASCADE: se un oggetto di altri
--   dipendesse da questi, il DROP si ferma
--   e non cancella niente di non suo.
-- Rieseguibile. Non tocca la 13: la sua
--   guardia controlla la 12 solo quando la
--   13 si applica.
-- ==========================================

DROP FUNCTION IF EXISTS
  public.monitoraggio_catalogo(text);
DROP FUNCTION IF EXISTS
  public.monitoraggio_job_orario();

DO $$
BEGIN
  IF to_regclass(
       'public.monitoraggio_riepilogo')
     IS NOT NULL
  THEN
    DROP TRIGGER IF EXISTS
      monitoraggio_riepilogo_ora
      ON public.monitoraggio_riepilogo;
  END IF;
END
$$;

DROP TABLE IF EXISTS
  public.monitoraggio_riepilogo;
DROP TABLE IF EXISTS
  public.monitoraggio_chiave;
DROP FUNCTION IF EXISTS
  public.monitoraggio_riepilogo_ora();

NOTIFY pgrst, 'reload schema';


-- ------------------------------------------
-- Verifica
-- ------------------------------------------
DO $$
BEGIN
  IF to_regprocedure(
       'public.monitoraggio_catalogo(text)')
       IS NOT NULL
     OR to_regprocedure(
       'public.monitoraggio_job_orario()')
       IS NOT NULL
     OR to_regprocedure(
       'public.monitoraggio_riepilogo_ora()')
       IS NOT NULL
     OR to_regclass(
       'public.monitoraggio_riepilogo')
       IS NOT NULL
     OR to_regclass(
       'public.monitoraggio_chiave')
       IS NOT NULL
  THEN
    RAISE EXCEPTION
      'rollback 12: un oggetto è rimasto';
  END IF;
  RAISE NOTICE
    'rollback 12: verifica superata';
END
$$;
