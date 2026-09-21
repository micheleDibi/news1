/**
 * Righe di categories, secondary_categories e profiles per i test dei mapper.
 * I nomi dei profili sono inventati: 'Nome Reale Riservato' fa da sentinella per
 * i test di non fuga (non deve mai comparire nell'output dell'API).
 */
import type { RigaCategoria, RigaProfilo, RigaSecondaria } from '../../../src/lib/api-v1/contratto.ts';

export const RIGHE_CATEGORIE: RigaCategoria[] = [
  { slug: 'scuola', name: 'Scuola', color: 'scuola', order_id: 1 },
  { slug: 'universita', name: 'Università', color: 'universita', order_id: 2 },
  { slug: 'lavoro', name: 'Lavoro', color: 'lavoro', order_id: 3 },
  { slug: 'senza-posizione', name: 'Senza posizione', color: 'viola-sconosciuto', order_id: null },
];

export const RIGHE_SECONDARIE: RigaSecondaria[] = [
  { slug: 'insegnanti', name: 'Insegnanti', parent_category_slug: 'scuola' },
  { slug: 'ata', name: 'ATA', parent_category_slug: 'scuola' },
  { slug: 'dirigenti', name: 'Dirigenti scolastici', parent_category_slug: 'scuola' },
  { slug: 'ricerca', name: 'Ricerca', parent_category_slug: 'universita' },
  // orfana: la categoria madre non esiste nel riferimento
  { slug: 'bandi-europei', name: 'Bandi europei', parent_category_slug: 'bandi' },
];

export const RIGHE_PROFILI: RigaProfilo[] = [
  { id: 'u-redazione', full_name: 'Nome Reale Riservato', public_name: 'Redazione EduNews24', is_displayable: true },
  { id: 'u-giornalista', full_name: 'Mario Esempio Rossi', public_name: 'M. Rossi', is_displayable: true },
  { id: 'u-nascosto', full_name: 'Persona Nascosta', public_name: 'P. Nascosta', is_displayable: false },
  { id: 'u-omonimo-1', full_name: 'Omonimo Doppio', public_name: 'Omonimo Uno', is_displayable: true },
  { id: 'u-omonimo-2', full_name: 'Omonimo Doppio', public_name: 'Omonimo Due', is_displayable: true },
  { id: 'u-lungo', full_name: 'Nome Lungo', public_name: 'L'.repeat(81), is_displayable: true },
  { id: 'u-url', full_name: 'Nome Url', public_name: 'https://www.esterno.example/profilo', is_displayable: true },
  { id: 'u-null', full_name: 'Nome Senza Pubblico', public_name: null, is_displayable: true },
  { id: 'u-stringa', full_name: 'Nome Flag Stringa', public_name: 'Flag Stringa', is_displayable: 'true' },
];
