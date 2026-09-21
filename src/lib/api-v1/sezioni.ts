/**
 * Le tre sezioni "opportunita'" (interpelli, selezione personale, bandi) come
 * oggetto `section` dell'API: etichetta e path da config/pagine-filtro.ts, colore
 * da category-colors.ts. Nessuna copia dei valori: le fonti restano quelle.
 */
import { configSezione } from '../../config/pagine-filtro';
import { getCategoryHex } from '../category-colors';
import { SITO } from './costanti';
import type { SezioneDto, SezioneOpportunita } from './contratto';

export const SEZIONI: readonly SezioneOpportunita[] = ['interpelli', 'selezione-personale', 'bandi'];

export function sezioneDto(sezione: SezioneOpportunita): SezioneDto {
  const config = configSezione(sezione);
  return {
    slug: sezione,
    name: config.etichetta,
    color: getCategoryHex(sezione),
    url: new URL(config.basePath, SITO).href,
  };
}

/** basePath della sezione (es. "/selezione-personale"). */
export function percorsoSezione(sezione: SezioneOpportunita): string {
  return configSezione(sezione).basePath;
}
