-- ============================================================================
-- bando_v11_10_sottodomini_dei_pattern.sql — DB Supabase «bandi»
-- ============================================================================
-- Scopo
--   Allinea le due funzioni che confrontano un host con `dominio_ufficiale`
--   alla regola dichiarata: «host = d.host **oppure** host termina con '.' +
--   d.host», che vale per tutte le righe e non solo per quelle letterali.
--
--   Le righe `pattern` (il jolly `*`) erano confrontate con il solo
--   `LIKE replace(d.host,'*','%')`, quindi senza il prefisso del sottodominio:
--
--     regola `regione.*.it`
--       regione.basilicata.it                  -> combacia
--       portalebandi.regione.basilicata.it     -> NON combacia
--       bandi.regione.lombardia.it             -> NON combacia
--       agricoltura.regione.emilia-romagna.it  -> NON combacia
--
--   Sono i portali dei bandi delle Regioni, cioè proprio le pagine che il
--   resolver cerca. Le righe letterali non hanno mai avuto il problema, perché
--   il loro ramo del CASE porta già `right(host, length(d.host)+1) = '.' ||
--   d.host`.
--
--   Misurato in produzione il 24/09/2026, su 900 bandi pubblicati fra
--   `in_verifica` e `non_trovata`: 1 290 candidati classificati `sconosciuto`,
--   di cui **705** combaciano con un pattern se si applica la regola dei
--   sottodomini (698 per `regione.*.it`), e **330 dei 900 bandi** guadagnano
--   almeno un candidato ammissibile. Lato Python un dominio `sconosciuto` fa
--   fallire il gate duro `whitelist`, quindi quei candidati non venivano
--   nemmeno valutati.
--
-- Che cosa fa
--   Rimpiazza due funzioni, senza toccare dati né schema:
--     1. `bando_host_aggregatore(text)`  (creata dalla 02)
--     2. `bando_dominio_verificante(text)` (creata dalla 04)
--   In entrambe il ramo dei pattern diventa
--     lower(host) LIKE p  OR  lower(host) LIKE '%.' || p
--   dove `p = replace(d.host, '*', '%')`.
--
--   Sulla blocklist il cambio è **teorico**: oggi nessuna riga `aggregatore` è
--   un pattern (sono dieci host letterali più social e video), quindi
--   `bando_host_aggregatore` risponde come prima. Si rimpiazza comunque perché
--   le due funzioni devono avere la stessa forma: una sola di loro corretta è
--   il modo in cui la regola torna a divergere.
--
-- Fase: (b). Nessuna colonna, nessuna tabella, nessun dato toccato.
--
-- Precondizioni
--   * `bando_v11_02_tabelle_di_servizio.sql` applicata (crea la prima);
--   * `bando_v11_04_transizioni.sql` applicata (crea la seconda).
--   Se la 04 non c'è, il blocco che la riguarda si salta da sé.
--
-- Rompe BandoFit? NO. `bando_host_aggregatore` non cambia risposta (nessun
--   pattern in blocklist) e `bando_dominio_verificante` non è leggibile da
--   anon: serve al trigger di `bando_evento`.
--
-- Effetto da conoscere: da qui in poi un `url_prova` su un sottodominio
--   regionale può rendere `verificato` un evento. È l'effetto voluto — quelle
--   pagine sono l'ente — ma è un allargamento di ciò che il DB accetta come
--   prova, non una correzione neutra.
--
-- Come si applica
--   SQL Editor → incollare ed eseguire l'INTERO file, poi il blocco
--   «Verifica». Rieseguibile: sono due `CREATE OR REPLACE`.
--   **Riavviare il sender** non serve: nessuna colonna e nessuna tabella nuova,
--   e `db.controllo` non guarda le funzioni.
-- ============================================================================

BEGIN;

SET LOCAL lock_timeout = '5s';

-- ---------------------------------------------------------------------------
-- 0. Precondizione: la 02 deve esserci
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public' AND p.proname = 'bando_host_aggregatore'
  ) THEN
    RAISE EXCEPTION
      'manca public.bando_host_aggregatore: applicare prima bando_v11_02_tabelle_di_servizio.sql';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Blocklist: stessa risposta di prima, stessa forma delle altre
-- ---------------------------------------------------------------------------

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
               -- La regola dei sottodomini vale anche per i pattern: e' la
               -- forma dichiarata in `app/dominio_ufficiale.py`, dove il
               -- confronto ha il prefisso `(?:.*\.)?`.
               THEN lower(coalesce(nome_host, '')) LIKE replace(d.host, '*', '%')
                 OR lower(coalesce(nome_host, '')) LIKE '%.' || replace(d.host, '*', '%')
             ELSE lower(coalesce(nome_host, '')) = d.host
                  OR right(lower(coalesce(nome_host, '')), length(d.host) + 1) = '.' || d.host
           END
  );
$$;

COMMENT ON FUNCTION public.bando_host_aggregatore(text) IS
  'true se l''host (o un suo sottodominio) è nella blocklist degli aggregatori. Unica funzione che legge dominio_ufficiale per conto di anon.';

-- ---------------------------------------------------------------------------
-- 2. Chi può rendere «verificato» un evento (solo se la 04 c'è)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public' AND p.proname = 'bando_dominio_verificante'
  ) THEN
    RAISE NOTICE 'bando_dominio_verificante assente (04 non applicata): salto il punto 2';
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
                        OR lower(nome_host) LIKE '%.' || replace(d.host, '*', '%')
                    ELSE lower(nome_host) = d.host
                         OR right(lower(nome_host), length(d.host) + 1) = '.' || d.host
                  END
         );
    $corpo$;
  $fn$;

  EXECUTE $c$
    COMMENT ON FUNCTION public.bando_dominio_verificante(text) IS
      'true se l''host può rendere «verificato» un evento: ente/portale_pubblico/pattern attivo con confidenza >= 0,8 e mai in blocklist. Dalla 10 la regola dei sottodomini vale anche per i pattern.';
  $c$;
END $$;

COMMIT;

-- ============================================================================
-- Verifica post-deploy (eseguire dopo il COMMIT)
-- ============================================================================
-- 1) I portali dei bandi regionali sono riconosciuti come verificanti.
--      SELECT h, public.bando_dominio_verificante(h) AS verificante
--        FROM (VALUES ('portalebandi.regione.basilicata.it'),
--                     ('bandi.regione.lombardia.it'),
--                     ('agricoltura.regione.emilia-romagna.it'),
--                     ('regione.veneto.it'),
--                     ('servizi.comune.milano.it')) v(h);
--      -- atteso: true su tutte e cinque
--
-- 2) La blocklist non si è allentata.
--      SELECT h, public.bando_host_aggregatore(h) AS bloccato,
--                public.bando_dominio_verificante(h) AS verificante
--        FROM (VALUES ('obiettivoeuropa.com'),
--                     ('www.obiettivoeuropa.com'),
--                     ('bandi.obiettivoeuropa.com')) v(h);
--      -- atteso: bloccato true, verificante false su tutte e tre
--
-- 3) Un dominio privato resta fuori.
--      SELECT public.bando_dominio_verificante('fondazionecariplo.it');
--      -- atteso: false
--
-- 4) Il pattern non combacia a metà di un'etichetta.
--      SELECT public.bando_dominio_verificante('maxiregione.lombardia.it');
--      -- atteso: false
--
-- 5) Nessun evento già scritto cambia: la funzione la chiama un trigger
--    BEFORE, quindi vale per le righe nuove.
--      SELECT count(*) FROM public.bando_evento WHERE verificato;
--      -- atteso: lo stesso numero di prima dell'esecuzione
-- ============================================================================
