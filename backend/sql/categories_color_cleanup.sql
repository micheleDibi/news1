-- ---------------------------------------------------------------------------
-- Rebrand v1: pulizia valori legacy in categories.color.
--
-- Contesto: dopo il rebrand del 2026-07-01 i colori 'calcio', 'motori', 'tennis',
-- 'basket' e 'commenti' sono stati rimossi da `tailwind.config.mjs` e dalla
-- safelist. Se in DB esistono ancora categorie con `color` in questi valori,
-- la UI le renderizzerebbe senza stile (classe Tailwind non esistente).
--
-- Questa migration MIGRA quelle categorie a 'sport-500' (fallback brand). È
-- IDEMPOTENTE — se non ci sono righe da migrare l'UPDATE tocca 0 righe.
-- ---------------------------------------------------------------------------

-- Verifica preventiva (esegui per prima cosa e ispeziona il risultato):
-- SELECT slug, name, color FROM categories
--  WHERE color IN ('calcio','motori','tennis','basket','commenti');

BEGIN;

UPDATE categories
   SET color = 'sport-500'
 WHERE color IN ('calcio', 'motori', 'tennis', 'basket', 'commenti');

COMMIT;

-- Verifica finale:
-- SELECT DISTINCT color FROM categories ORDER BY color;
-- Atteso: solo valori in
--   {scuola, universita, ricerca, mondo, formazione, editoriali, cultura,
--    lavoro, tecnologia, bandi, sport-500, red-500, blue-500, green-500}.
