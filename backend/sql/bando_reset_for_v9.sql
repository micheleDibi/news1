-- ---------------------------------------------------------------------------
-- v9 reset: porta tutti i bandi NON-rejected a 'scraped' per ri-eseguire la
-- pipeline completa con preprocess v2 (Firecrawl + Haiku + Sonnet fallback,
-- stato_bando data-driven, 3 date estratte gia' al preprocess).
--
-- I bandi 'rejected' sono mantenuti tali (decisione utente).
--
-- Operazione DISTRUTTIVA: cancella le junction tables e azzera tutte le
-- colonne popolate dalle fasi successive (preprocess, enrich, seo).
--
-- PREREQUISITO: applica prima `bando_alter_v9_add_titolo.sql` per assicurare
-- che la colonna `titolo` esista (la skill SEO v8 la popola; lo schema attuale
-- potrebbe non averla).
-- ---------------------------------------------------------------------------

BEGIN;

-- 1. Clear junction tables (only per i bandi che resettiamo)
DELETE FROM public.bando_beneficiari
  WHERE bando_id IN (SELECT id FROM public.bando WHERE stato_processing <> 'rejected');
DELETE FROM public.bando_codici_ateco
  WHERE bando_id IN (SELECT id FROM public.bando WHERE stato_processing <> 'rejected');
DELETE FROM public.bando_regioni
  WHERE bando_id IN (SELECT id FROM public.bando WHERE stato_processing <> 'rejected');
DELETE FROM public.bando_settori
  WHERE bando_id IN (SELECT id FROM public.bando WHERE stato_processing <> 'rejected');

-- 2. Reset colonne bando per i non-rejected
UPDATE public.bando SET
  stato_processing = 'scraped',
  stato_bando = NULL,
  confidence_score = NULL,
  rejection_reason = NULL,
  data_pubblicazione = NULL,
  data_apertura = NULL,
  data_scadenza = NULL,
  tipologia_bando_id = NULL,
  modalita_erogazione_id = NULL,
  programma_id = NULL,
  slug = NULL,
  titolo = NULL,
  titolo_breve = NULL,
  descrizione_breve = NULL,
  contenuto = NULL,
  livello = NULL,
  allegati = NULL,
  ente_erogatore = NULL,
  area_geografica = NULL,
  tematica = NULL,
  importo_totale_eur = NULL,
  importo_max_per_progetto_eur = NULL,
  link_candidatura = NULL,
  link_candidatura_source = NULL
WHERE stato_processing <> 'rejected';

COMMIT;

-- Sanity check post-reset:
--   SELECT stato_processing, COUNT(*) FROM bando GROUP BY 1 ORDER BY 1;
--   Expected: solo 'scraped' e 'rejected'.
