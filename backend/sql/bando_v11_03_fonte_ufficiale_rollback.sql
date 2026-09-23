-- ============================================================================
-- bando_v11_03_fonte_ufficiale_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_03_fonte_ufficiale.sql`: elimina le chiavi esterne,
--   i CHECK di provenienza e coerenza, l'indice della chiave esterna e i sei
--   trigger. Le COLONNE restano: sono della 01.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   * la migrazione 04 deve essere già annullata: `bando_registra_evento`
--     scrive gli `*_evento_id` contando sui vincoli di questo file, e
--     `bando_cambia_slug` conta sul trigger dello slug congelato;
--   * la migrazione 05 può restare: la vista legge `fonte_ufficiale_*` e
--     `fonte_ufficiale_link_id`, che restano colonne valide anche senza FK.
--     Nota però che senza `bando_fonte_coerente` la vista può esporre una
--     `fonte_ufficiale_url` senza il link corrispondente.
--
-- Rompe BandoFit? NO: nessuna colonna sparisce e i valori restano.
--   Rompe invece le GARANZIE: dopo questo file lo slug di un pubblicato
--   torna riscrivibile da qualunque UPDATE (è il difetto che la 03 chiude) e
--   una data può tornare «verificata» senza l'evento che la prova. Non
--   lasciare il DB in questo stato più del necessario.
--
-- COSA NON È REVERSIBILE
--   * i valori seminati in `bando_controllo` (priorità e
--     `prossimo_controllo_at`) NON vengono cancellati: cancellarli
--     perderebbe le impronte e i contatori accumulati dal monitor, che sono
--     molto più preziosi della semina. La riga di controllo di un bando è
--     innocua anche senza la 03. Se davvero serve azzerarla, il DELETE è
--     scritto in fondo, commentato;
--   * `fonte_ufficiale_stato='in_verifica'` resta scritto ovunque: è il
--     valore neutro e non disturba nessun consumatore. Riportarlo a NULL
--     richiederebbe un UPDATE su 5048 righe, cioè la stessa cautela sui
--     trigger `updated_at` del backfill originale (vedi in fondo).
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = 'public'
                AND p.proname IN ('bando_registra_evento', 'bando_applica_evento',
                                  'bando_cambia_slug', 'bando_fondi', 'bando_separa')) THEN
    RAISE EXCEPTION
      'le RPC della migrazione 04 esistono ancora: annullare prima bando_v11_04_transizioni_rollback.sql';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Trigger e funzioni
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_bando_fonte_ufficiale_dominio ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_fonte_ufficiale_copia   ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_provenienza_date        ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_slug_non_storico        ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_slug_congelato          ON public.bando;
DROP TRIGGER IF EXISTS trg_bando_crea_controllo          ON public.bando;

DROP FUNCTION IF EXISTS public.bando_fonte_ufficiale_dominio();
DROP FUNCTION IF EXISTS public.bando_fonte_ufficiale_copia();
DROP FUNCTION IF EXISTS public.bando_provenienza_date();
DROP FUNCTION IF EXISTS public.bando_slug_non_storico();
DROP FUNCTION IF EXISTS public.bando_slug_congelato();
DROP FUNCTION IF EXISTS public.bando_crea_controllo();

-- ---------------------------------------------------------------------------
-- 2. Vincoli e indici
-- ---------------------------------------------------------------------------

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_coerente;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_stato;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_scadenza;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_apertura;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_provenienza_data_pubblicazione;

ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_master_fk;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_stato_bando_evento_fk;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_data_scadenza_evento_fk;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_data_apertura_evento_fk;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_data_pubblicazione_evento_fk;
ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS bando_fonte_ufficiale_link_fk;

DROP INDEX IF EXISTS public.bando_fonte_chiave_esterna_uidx;
DROP INDEX IF EXISTS public.idx_bando_fonte_ufficiale_link;
DROP INDEX IF EXISTS public.idx_bando_stato_bando_evento;
DROP INDEX IF EXISTS public.idx_bando_data_scadenza_evento;
DROP INDEX IF EXISTS public.idx_bando_data_apertura_evento;
DROP INDEX IF EXISTS public.idx_bando_data_pubblicazione_evento;

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   SELECT conname FROM pg_constraint
--    WHERE conrelid='public.bando'::regclass
--      AND conname LIKE ANY (ARRAY['bando_provenienza%','bando_fonte_coerente','%_evento_fk','bando_master_fk','bando_fonte_ufficiale_link_fk']);
--   -- atteso: 0 righe
--
--   SELECT count(*) FROM pg_trigger
--    WHERE tgrelid='public.bando'::regclass AND NOT tgisinternal
--      AND tgname IN ('trg_bando_slug_congelato','trg_bando_slug_non_storico',
--                     'trg_bando_provenienza_date','trg_bando_fonte_ufficiale_copia',
--                     'trg_bando_fonte_ufficiale_dominio','trg_bando_crea_controllo');
--   -- atteso: 0
-- ============================================================================

-- ============================================================================
-- Non eseguito di proposito (se il committente lo vuole davvero):
--
--   -- azzerare la semina dei controlli (perde impronte e contatori!)
--   DELETE FROM bando_controllo;
--
--   -- riportare a NULL lo stato della fonte, con la stessa cautela del
--   -- backfill originale
--   BEGIN;
--     ALTER TABLE bando DISABLE TRIGGER trg_bando_set_updated_at;
--     ALTER TABLE bando DISABLE TRIGGER update_bando_updated_at;
--     ALTER TABLE bando DISABLE TRIGGER trg_bando_cambiamento_pubblico;
--     UPDATE bando SET fonte_ufficiale_stato = NULL WHERE fonte_ufficiale_stato = 'in_verifica';
--     ALTER TABLE bando ENABLE TRIGGER trg_bando_cambiamento_pubblico;
--     ALTER TABLE bando ENABLE TRIGGER update_bando_updated_at;
--     ALTER TABLE bando ENABLE TRIGGER trg_bando_set_updated_at;
--   COMMIT;
-- ============================================================================
