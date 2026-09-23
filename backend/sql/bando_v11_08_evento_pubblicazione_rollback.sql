-- ============================================================================
-- bando_v11_08_evento_pubblicazione_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Annulla `bando_v11_08_evento_pubblicazione.sql`: toglie il trigger
--   `trg_bando_evento_pubblicazione` da `public.bando` e la funzione
--   `public.bando_evento_pubblicazione()`. Nient'altro.
--
-- Fase: (b) — rientro.
--
-- Precondizioni
--   Nessuna. Il file non dipende dalle altre migrazioni e si può eseguire in
--   qualunque fase. Le migrazioni 01–07 restano dove sono: la 08 non ha
--   toccato niente di loro.
--
-- Rompe BandoFit? NO nello schema — nessuna colonna, nessun privilegio,
--   nessuna policy cambia. Rompe invece la GARANZIA appena introdotta: da
--   subito dopo questo file i bandi pubblicati tornano a NON emettere
--   l'evento `pubblicazione`, e un consumatore che segue
--   `?cursore=gt.<ultimo>` smette di venire a sapere dei bandi nuovi. È il
--   difetto misurato il 23/09/2026 (2124 pubblicati, 2114 eventi: numeri di
--   quel giorno, non soglie), che
--   ricomincerebbe ad accumularsi al ritmo delle pubblicazioni. Non lasciare
--   il DB in questo stato più del necessario: finché ci resta, l'unico
--   rimedio è lanciare a mano il blocco «Riconciliazione» della 08 dopo ogni
--   giro di pipeline.
--
-- COSA NON È REVERSIBILE
--   GLI EVENTI GIÀ CREATI NON VENGONO CANCELLATI. Né quelli emessi dal
--   trigger, né quelli recuperati dal punto 3 della 08 (una decina alla
--   misura del 23/09/2026). Il motivo non è prudenza generica: ognuno di quegli eventi ha ricevuto un
--   CURSORE, e il cursore è la promessa scritta nel capitolo 6 del contratto
--   — monotono, mai revocato. Un consumatore può averli già letti e aver
--   spostato in avanti il proprio segnalibro; cancellarli lascerebbe buchi in
--   una numerazione che nessuno può più rileggere, e i suoi bandi nuovi
--   resterebbero senza notifica per sempre. Del resto `DELETE` su
--   `bando_evento` è revocato perfino a `service_role`, e il trigger
--   `z_evento_immutabile` impedisce di rimaneggiarli.
--   Gli eventi restano dunque leggibili e corretti: descrivono pubblicazioni
--   realmente avvenute. Rieseguire la 08 dopo questo rollback non li duplica
--   (il `NOT EXISTS` è sul tipo).
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file. Come la 08, meglio a
--   pipeline ferma: il `DROP TRIGGER` vuole un lock esclusivo su `bando` e con
--   `lock_timeout` a 5s una scrittura concorrente lo fa annullare INTERO —
--   niente resta a metà, si ritenta.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DROP TRIGGER IF EXISTS trg_bando_evento_pubblicazione ON public.bando;

DROP FUNCTION IF EXISTS public.bando_evento_pubblicazione();

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
-- 1) Il trigger e la funzione non ci sono più.
--      SELECT count(*) FROM pg_trigger
--       WHERE tgrelid='public.bando'::regclass AND NOT tgisinternal
--         AND tgname = 'trg_bando_evento_pubblicazione';
--      -- atteso: 0
--      SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--       WHERE n.nspname='public' AND p.proname='bando_evento_pubblicazione';
--      -- atteso: 0
--
-- 2) Gli altri due trigger AFTER su `bando` sono intatti.
--      SELECT tgname FROM pg_trigger
--       WHERE tgrelid='public.bando'::regclass AND NOT tgisinternal
--         AND (tgtype & 2) = 0
--       ORDER BY tgname;
--      -- atteso: trg_bando_crea_controllo, trg_bando_promuovi_eventi
--
-- 3) Gli eventi sono rimasti, con il loro cursore.
--      SELECT count(*) AS eventi, count(cursore) AS con_cursore
--        FROM bando_evento WHERE tipo='pubblicazione';
--      -- atteso: gli stessi numeri di prima del rollback, e i due uguali
--
-- 4) Il difetto è tornato (da annullare — serve solo a confermare che il
--    rollback ha fatto effetto). È il punto 6 della verifica della 08, con
--    l'esito rovesciato:
--      BEGIN;
--        SELECT count(*) AS prima FROM bando_evento WHERE tipo='pubblicazione';
--        UPDATE bando
--           SET slug             = coalesce(slug, 'verifica-08-' || id),
--               stato_bando      = coalesce(stato_bando, 'aperto'),
--               stato_processing = 'completed'
--         WHERE id = (SELECT id FROM bando
--                      WHERE NOT pubblicato AND bando_master_id IS NULL
--                        AND ritirato_at IS NULL
--                      ORDER BY id LIMIT 1);
--        SELECT count(*) AS dopo FROM bando_evento WHERE tipo='pubblicazione';
--        -- atteso: dopo = prima, cioè un pubblicato in più e nessun evento
--      ROLLBACK;
-- ============================================================================
