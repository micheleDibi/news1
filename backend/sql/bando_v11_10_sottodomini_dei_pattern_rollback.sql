-- ============================================================================
-- bando_v11_10_sottodomini_dei_pattern_rollback.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Rimette le due funzioni alla forma della 02 e della 04: il ramo dei
--   pattern torna a confrontare il solo host, senza il prefisso dei
--   sottodomini.
--
-- Fase: (b) — rientro.
--
-- Effetto: i portali dei bandi delle Regioni tornano `sconosciuto` per il DB,
--   quindi un `url_prova` su `bandi.regione.lombardia.it` non potrà più
--   rendere `verificato` un evento. Gli eventi già scritti non cambiano: la
--   funzione la chiama un trigger BEFORE.
--
--   Attenzione: dopo questo rollback il DB torna più stretto di
--   `app/dominio_ufficiale.py`, che la regola dei sottodomini sui pattern la
--   applica. La direzione è sicura — il DB rifiuta, non accetta di più — ma la
--   divergenza va dichiarata a chi legge i contatori del resolver: Python
--   proporrà eventi `verificato` che il trigger rimetterà a false.
--
-- Rompe BandoFit? NO.
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.bando_host_aggregatore(nome_host text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.dominio_ufficiale d
     WHERE d.attivo
       AND d.tipo = 'aggregatore'
       AND CASE
             WHEN d.host LIKE '%*%'
               THEN lower(coalesce(nome_host, '')) LIKE replace(d.host, '*', '%')
             ELSE lower(coalesce(nome_host, '')) = d.host
                  OR right(lower(coalesce(nome_host, '')), length(d.host) + 1) = '.' || d.host
           END
  );
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public' AND p.proname = 'bando_dominio_verificante'
  ) THEN
    RAISE NOTICE 'bando_dominio_verificante assente: niente da annullare';
    RETURN;
  END IF;

  EXECUTE $fn$
    CREATE OR REPLACE FUNCTION public.bando_dominio_verificante(nome_host text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public, pg_temp
    AS $corpo$
      SELECT nome_host IS NOT NULL
         AND NOT public.bando_host_aggregatore(nome_host)
         AND EXISTS (
           SELECT 1
             FROM public.dominio_ufficiale d
            WHERE d.attivo
              AND d.tipo IN ('ente', 'portale_pubblico', 'pattern')
              AND d.confidenza >= 0.80
              AND CASE
                    WHEN d.host LIKE '%*%'
                      THEN lower(nome_host) LIKE replace(d.host, '*', '%')
                    ELSE lower(nome_host) = d.host
                         OR right(lower(nome_host), length(d.host) + 1) = '.' || d.host
                  END
         );
    $corpo$;
  $fn$;
END $$;

COMMIT;

-- ============================================================================
-- Verifica
-- ============================================================================
--   SELECT public.bando_dominio_verificante('bandi.regione.lombardia.it');
--   -- atteso: false (era true con la 10 applicata)
--   SELECT public.bando_dominio_verificante('regione.lombardia.it');
--   -- atteso: true (il dominio nudo combacia da sempre)
-- ============================================================================
