-- ============================================================================
-- bando_v11_09_fonte_stato_default_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_09_fonte_stato_default.sql`: toglie il DEFAULT dalla
--   colonna `bando.fonte_ufficiale_stato` e rimette il commento a quello
--   generico della 01.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   nessuna. Il file si applica anche se la 09 non è mai stata applicata
--   (`DROP DEFAULT` su una colonna senza default non è un errore).
--
-- Rompe BandoFit? NO. Nessuno schema cambia forma; torna solo a essere
--   possibile inserire una riga con la colonna vuota.
--
-- COSA NON È REVERSIBILE
--   Le righe riempite dal punto 2 della 09 restano a 'in_verifica'. Non le
--   riportiamo a NULL di proposito: 'in_verifica' è esattamente ciò che sono
--   («fonte ufficiale non ancora trovata»), distinguerle da quelle scritte
--   dal resolver richiederebbe un'informazione che non esiste, e rimetterle
--   a NULL le farebbe sparire di nuovo dalla selezione del resolver, cioè
--   ricreerebbe il difetto che la 09 chiude.
--
--   Dopo questo rollback il buco torna: ogni riga nuova nasce a NULL e il
--   resolver non la vede, a meno che il codice che seleziona accetti anche il
--   NULL (lo fa dalla correzione del 23/09/2026: `db._filtra_selezione`).
-- ============================================================================

BEGIN;

ALTER TABLE public.bando
  ALTER COLUMN fonte_ufficiale_stato DROP DEFAULT;

COMMENT ON COLUMN public.bando.fonte_ufficiale_stato IS
  'trovata | in_verifica | non_trovata';

COMMIT;

-- ============================================================================
-- Verifica
-- ============================================================================
--   SELECT column_default FROM information_schema.columns
--    WHERE table_schema='public' AND table_name='bando'
--      AND column_name='fonte_ufficiale_stato';
--   -- atteso: NULL (nessun default)
--
--   SELECT count(*) FROM public.bando WHERE fonte_ufficiale_stato IS NULL;
--   -- atteso: 0 (le righe riempite restano riempite: vedi sopra)
-- ============================================================================
