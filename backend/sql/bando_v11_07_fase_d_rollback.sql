-- ============================================================================
-- bando_v11_07_fase_d_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Riporta il DB alla fase (b)/(c): la vista `bando_pubblico` torna a
--   esporre le colonne deprecate, la policy di `bando` torna al predicato
--   storico e anon riottiene i privilegi che aveva prima della 07.
--
--   È il rollback più importante della serie, perché la 07 è l'unica
--   migrazione che TOGLIE qualcosa a un consumatore: va tenuto a portata di
--   mano mentre si applica la 07 e deve poter girare senza pensarci.
--
-- Fase: (d) → (c).
--
-- Precondizioni: nessuna. Si può eseguire in qualunque momento dopo la 07.
--
-- Rompe BandoFit? NO: restituisce colonne, non ne toglie. Una BandoFit già
--   in fase (c) continua a funzionare (le colonne nuove restano tutte).
--
-- COSA NON È REVERSIBILE
--   Niente: la 07 non tocca nessun dato, solo definizioni e privilegi.
--   L'unica cosa che questo file NON rimette è il `GRANT ALL ON TABLE bando
--   TO anon, authenticated` originale, cioè i privilegi di SCRITTURA che
--   anon aveva per un difetto dei privilegi di default. Restituisce SELECT
--   sull'intera tabella (che è ciò che serve ai consumatori) e basta. Se
--   servisse davvero il ripristino letterale, è in fondo, commentato.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'intero file.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 1. Privilegi su `bando`
-- ---------------------------------------------------------------------------
-- I GRANT di colonna vanno revocati prima, altrimenti restano accanto al
-- GRANT di tabella e confondono ogni verifica successiva.

REVOKE ALL ON TABLE public.bando FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE public.bando TO anon;
GRANT SELECT ON TABLE public.bando TO authenticated;

-- L'allowlist torna a tre funzioni: la vista della fase (b) maschera di nuovo
-- `link_bando`, `link_candidatura` e `allegati`, e senza questi due EXECUTE
-- ogni lettura di `bando_pubblico` come anon risponderebbe 42501.
GRANT EXECUTE ON FUNCTION public.dominio_di(text) TO anon;
GRANT EXECUTE ON FUNCTION public.bando_host_aggregatore(text) TO anon;

-- ---------------------------------------------------------------------------
-- 2. Policy storica
-- ---------------------------------------------------------------------------

DROP POLICY IF EXISTS bando_public_read ON public.bando;
CREATE POLICY bando_public_read ON public.bando
  FOR SELECT TO anon
  USING (
    stato_processing::text = 'completed'
    AND slug IS NOT NULL
  );

-- ---------------------------------------------------------------------------
-- 3. Vista della fase (b) — copia letterale di bando_v11_05_vista_pubblica.sql
-- ---------------------------------------------------------------------------
-- È duplicata di proposito: un rollback che dipendesse da un altro file non
-- sarebbe un rollback. Se la 05 cambia, questa copia va aggiornata insieme.

DROP VIEW IF EXISTS public.bando_pubblico;

CREATE VIEW public.bando_pubblico
WITH (security_invoker = true) AS
SELECT
  b.id,
  b.slug,
  b.titolo,
  b.titolo_breve,
  b.descrizione_breve,
  CASE WHEN jsonb_typeof(b.contenuto) = 'object' THEN b.contenuto END AS contenuto,
  b.livello,
  b.ente_erogatore,
  b.area_geografica,
  b.tematica,
  b.data_pubblicazione,
  b.data_apertura,
  b.data_scadenza,
  b.ora_apertura,
  b.ora_scadenza,
  b.data_pubblicazione_verificata,
  b.data_apertura_verificata,
  b.data_scadenza_verificata,
  b.importo_totale_eur,
  b.importo_max_per_progetto_eur,
  b.stato_bando,
  b.stato_bando_verificato,
  public.bando_stato_effettivo(
    b.stato_bando,
    b.data_apertura,
    b.data_apertura_verificata,
    b.ora_apertura,
    b.data_scadenza,
    b.ora_scadenza,
    now()
  ) AS stato_effettivo,
  b.tipologia_bando_id,
  b.modalita_erogazione_id,
  b.programma_id,
  b.fonte_ufficiale_stato,
  b.fonte_ufficiale_tipo,
  EXISTS (
    SELECT 1 FROM public.bando_link l
     WHERE l.id = b.fonte_ufficiale_link_id AND l.tipo = 'atto'
  ) AS fonte_ufficiale_e_atto,
  b.fonte_ufficiale_url,
  b.fonte_ufficiale_host,
  b.fonte_ufficiale_verificata_at,
  (SELECT c.ultimo_controllo_at
     FROM public.bando_controllo c
    WHERE c.bando_id = b.id) AS ultimo_controllo_at,
  -- Le tre colonne mascherate come nella 05: nessun link ad aggregatori esce
  -- dalle colonne leggibili con la anon key, nemmeno tornando indietro.
  CASE
    WHEN b.link_candidatura IS NULL THEN NULL
    WHEN public.dominio_di(b.link_candidatura) IS NULL THEN NULL
    WHEN public.bando_host_aggregatore(public.dominio_di(b.link_candidatura)) THEN NULL
    ELSE b.link_candidatura
  END AS link_candidatura,
  CASE
    WHEN b.link_candidatura IS NULL
      OR public.dominio_di(b.link_candidatura) IS NULL
      OR public.bando_host_aggregatore(public.dominio_di(b.link_candidatura)) THEN NULL
    ELSE b.link_candidatura_source
  END AS link_candidatura_source,
  CASE
    WHEN jsonb_typeof(b.allegati) <> 'array' THEN b.allegati
    ELSE (
      SELECT coalesce(jsonb_agg(e.value), '[]'::jsonb)
        FROM jsonb_array_elements(b.allegati) AS e(value)
       WHERE NOT public.bando_host_aggregatore(public.dominio_di(e.value ->> 'url'))
    )
  END AS allegati,
  b.titolo_raw,
  b.descrizione_raw,
  'completed'::character varying AS stato_processing,
  -- `dominio_di` è fail-open: host non riconosciuto ⇒ non si pubblica (C4).
  CASE
    WHEN public.dominio_di(b.link_bando) IS NULL THEN NULL
    WHEN public.bando_host_aggregatore(public.dominio_di(b.link_bando)) THEN NULL
    ELSE b.link_bando
  END AS link_bando,
  b.ricerca,
  b.pubblicato_at,
  b.created_at,
  b.ultimo_cambiamento_at
FROM public.bando b
WHERE b.pubblicato;

COMMENT ON VIEW public.bando_pubblico IS
  'Contratto di lettura del DB bandi (§13). Contiene i soli pubblicati non fusi. La verità sullo stato è stato_effettivo, non stato_bando. Un id o uno slug che qui non si trova si risolve su bando_fusione / bando_slug_storico. `fonte_ufficiale_e_atto` è true solo se il link dell''atto è a sua volta PUBBLICABILE: la vista è security_invoker, quindi il flag dipende anche dalla RLS di bando_link e un ruolo interno può leggerlo true dove anon lo legge false.';

REVOKE ALL ON TABLE public.bando_pubblico FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.bando_pubblico TO anon;
GRANT SELECT ON TABLE public.bando_pubblico TO service_role;

COMMIT;

-- ============================================================================
-- Verifica post-rollback
-- ============================================================================
--   Blocco auto-contenuto: fuori da una transazione `SET LOCAL` dà solo un
--   WARNING e la query gira come proprietario, che scavalca la RLS e rende
--   vero qualunque esito atteso. Incollarlo per intero.
--   BEGIN;
--     SET LOCAL ROLE anon;
--     SELECT link_bando, stato_processing FROM bando_pubblico LIMIT 1;  -- atteso: 200
--     SELECT link_bando FROM bando LIMIT 1;                             -- atteso: 200
--     SELECT count(*) FROM bando;   -- atteso: 2104 (predicato storico, fusi compresi)
--   ROLLBACK;
--
--   Il privilegio su `bando` è di nuovo di TABELLA. Attenzione a non leggerlo
--   su `information_schema.column_privileges`: quella vista è l'UNION fra i
--   privilegi di colonna e quelli di tabella espansi colonna per colonna,
--   quindi dopo il `GRANT SELECT ON TABLE ... TO anon` qui sopra restituisce
--   una riga per OGNI colonna, non zero.
--   SELECT privilege_type FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND table_name='bando' AND grantee='anon';
--   -- atteso: 1 riga, SELECT
--   SELECT count(*) FROM pg_attribute a
--    WHERE a.attrelid = 'public.bando'::regclass AND a.attacl IS NOT NULL;
--   -- atteso: 0 (nessun privilegio di COLONNA residuo)
--
--   SELECT policyname, qual FROM pg_policies
--    WHERE schemaname='public' AND tablename='bando';
--   -- atteso: bando_public_read con il predicato completed + slug
-- ============================================================================

-- ============================================================================
-- Ripristino letterale dei privilegi originali (rimette anche INSERT,
-- UPDATE e DELETE ad anon: erano un difetto dei privilegi di default del
-- progetto, bloccato solo dalla RLS). Da eseguire solo se il committente lo
-- chiede esplicitamente:
--
--   GRANT ALL ON TABLE public.bando TO anon;
--   GRANT ALL ON TABLE public.bando TO authenticated;
-- ============================================================================
