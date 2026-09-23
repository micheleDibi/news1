-- ============================================================================
-- bando_v11_06_stati_cinque_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Riporta il CHECK di `bando.stato_bando` ai 3 valori storici
--   (aperto / chiuso / in apertura prossimamente).
--
-- Fase: (b) — rientro.
--
-- Precondizione BLOCCANTE (e questa è la ragione per cui il rollback della
-- 06 non è una formalità): NON devono esistere righe con `stato_bando` =
--   'sospeso' o 'revocato'. Il CHECK a 3 valori le rifiuterebbe e
--   l'ALTER TABLE fallirebbe. La guardia qui sotto lo dice esplicitamente e
--   conta le righe da sistemare.
--
--   Riportare un sospeso o un revocato a uno dei 3 valori NON è
--   un'operazione neutra: significa dire al pubblico che un bando sospeso è
--   di nuovo aperto, o che un bando revocato è semplicemente chiuso. È una
--   decisione editoriale del committente, non del rollback. Per questo il
--   file NON la esegue: si limita a fallire e a mostrare le righe.
--
-- Rompe BandoFit? NO (torna allo stato che R0 già gestisce). Rompe però la
--   pipeline: gli eventi `sospensione`/`revoca` tornano inapplicabili e
--   vanno rimessi in attesa spegnendo `MONITOR_STATI_ESTESI`.
--
-- COSA NON È REVERSIBILE
--   L'informazione «questo bando era sospeso» sopravvive negli eventi
--   (`bando_evento` è immutabile), ma la colonna la perde. Dopo il rientro
--   news1 torna a mostrare lo stato dagli eventi `applicato=false`, mentre
--   BandoFit non lo saprà più.
--
-- Come si applica
--   1. spegnere `MONITOR_STATI_ESTESI` e fermare `applica-eventi`;
--   2. eseguire il blocco «transizioni di rientro» qui sotto (sta FUORI dalla
--      transazione apposta: senza di lui il passo 3 è impossibile);
--   3. decidere, riga per riga, dove riportare i sospesi e i revocati;
--   4. applicare le UPDATE dal blocco in fondo (passando da
--      `bando_registra_evento`, non da un UPDATE diretto, finché la 04 è
--      applicata);
--   5. eseguire questo file.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 0. Transizioni di rientro per la redazione — FUORI dalla transazione
-- ---------------------------------------------------------------------------
-- La lista bianca generata da tests/stato-bando/casi.json non ha nessuna riga
-- con attore='redazione': senza queste, né `bando_registra_evento` né un
-- UPDATE diretto possono riportare un sospeso/revocato ai 3 valori storici
-- (`bando_transizione_ammessa` filtra su t.attore = p_attore e
-- `bando_applica_evento` solleva 23514, come il trigger
-- trg_bando_stato_solo_via_evento), e il rientro si blocca: anche il rollback
-- della 04 rifiuta di partire finché quelle righe esistono.
-- Restano innocue: descrivono una transizione possibile, non la eseguono.
--
-- Perché fuori dal BEGIN: la guardia qui sotto solleva un'eccezione finché
-- ci sono sospesi o revocati, e un'eccezione annullerebbe anche questo INSERT
-- — cioè proprio ciò che serve per sbloccare il rientro. Eseguito da solo è
-- idempotente.
--
-- A regime la sede giusta è tests/stato-bando/casi.json, rigenerando il
-- blocco TRANSIZIONI della 04 con tests/stato-bando/genera-sql.ts.
DO $$
BEGIN
  IF to_regclass('public.bando_transizione') IS NULL THEN
    RAISE NOTICE 'migrazione 04 non applicata: nessuna lista bianca da estendere';
    RETURN;
  END IF;
  INSERT INTO public.bando_transizione (da, a, attore, evento, condizione)
  SELECT v.da, v.a, 'redazione', 'correzione_redazionale',
         'rientro dalla migrazione 06: scelta editoriale del committente, tracciata da un evento'
    FROM (VALUES ('sospeso','aperto'), ('sospeso','chiuso'),
                 ('sospeso','in apertura prossimamente'),
                 ('revocato','aperto'), ('revocato','chiuso'),
                 ('revocato','in apertura prossimamente')) AS v(da, a)
   WHERE NOT EXISTS (
     SELECT 1 FROM public.bando_transizione t
      WHERE t.da IS NOT DISTINCT FROM v.da AND t.a = v.a
        AND t.attore = 'redazione' AND t.evento = 'correzione_redazionale')
  ON CONFLICT DO NOTHING;
END $$;

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE n_sospesi bigint; n_revocati bigint;
BEGIN
  SELECT count(*) FILTER (WHERE stato_bando = 'sospeso'),
         count(*) FILTER (WHERE stato_bando = 'revocato')
    INTO n_sospesi, n_revocati
    FROM public.bando;

  IF n_sospesi + n_revocati > 0 THEN
    RAISE EXCEPTION
      'esistono % righe sospese e % revocate: il CHECK a 3 valori le rifiuterebbe. Decidere dove riportarle (è una scelta editoriale) e solo dopo rieseguire. Elenco: SELECT id, slug, stato_bando FROM bando WHERE stato_bando IN (''sospeso'',''revocato'');',
      n_sospesi, n_revocati;
  END IF;
END $$;

DO $$
DECLARE c_name text;
BEGIN
  FOR c_name IN
    SELECT conname
      FROM pg_constraint
     WHERE conrelid = 'public.bando'::regclass
       AND contype = 'c'
       AND conname NOT IN ('bando_pubblicato_implica_completed', 'bando_provenienza_stato')
       AND pg_get_constraintdef(oid) ILIKE '%in apertura prossimamente%'
  LOOP
    EXECUTE format('ALTER TABLE public.bando DROP CONSTRAINT IF EXISTS %I', c_name);
  END LOOP;
END $$;

ALTER TABLE public.bando
  ADD CONSTRAINT bando_stato_bando_check
  CHECK (stato_bando IS NULL OR stato_bando IN (
    'chiuso', 'aperto', 'in apertura prossimamente'
  ));

-- Il COMMENT che la 06 riscrive a cinque valori è l'unico residuo della
-- catena di rollback che nessun file dichiarava: senza questa riga la colonna
-- continuerebbe a documentare cinque stati su un CHECK che ne ammette tre.
-- Nota: prima della 06 la colonna non aveva NESSUN commento (schema.sql), per
-- cui un rientro alla lettera sarebbe `IS NULL`; si preferisce un commento
-- corretto a un commento assente.
COMMENT ON COLUMN public.bando.stato_bando IS
  'Stato persistito a 3 valori (aperto / chiuso / in apertura prossimamente). La verità sullo stato è bando_pubblico.stato_effettivo, non questa colonna.';

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   SELECT pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conrelid='public.bando'::regclass AND conname='bando_stato_bando_check';
--   -- atteso: i 3 valori storici
--
--   SELECT count(*) FROM bando_evento
--    WHERE tipo IN ('sospensione','revoca') AND applicato;
--   -- atteso: 0 (se non lo è, la colonna e gli eventi sono in disaccordo)
-- ============================================================================

-- ============================================================================
-- Da eseguire PRIMA, riga per riga, se ci sono sospesi o revocati (esempio;
-- la scelta del valore di arrivo è del committente):
--
--   SELECT id, slug, stato_bando, data_scadenza FROM bando
--    WHERE stato_bando IN ('sospeso','revocato') ORDER BY id;
--
--   -- con la migrazione 04 applicata (via evento, tracciato):
--   SELECT bando_registra_evento(
--            <id>, 'correzione_redazionale', 'redazione',
--            'stato_bando', to_jsonb('chiuso'::text), NULL, NULL, NULL, true);
--
--   -- senza la 04 (UPDATE diretto, ammesso solo perché il trigger
--   -- trg_bando_stato_solo_via_evento non esiste):
--   UPDATE bando SET stato_bando='chiuso' WHERE id=<id>;
-- ============================================================================
