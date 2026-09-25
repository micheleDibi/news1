/**
 * Single source of truth per il link alla piattaforma BandoFit
 * (supporto progettuale sui bandi). L'URL non va mai hardcodato nei
 * componenti: usare bandofitCtaUrl() dichiarando la posizione del CTA,
 * cosi' ogni pulsante e' misurabile separatamente via utm_content.
 */
export const BANDOFIT_URL = 'https://bandofit.edunews24.it';

/** Posizioni dei CTA verso BandoFit: il valore diventa lo utm_content. */
// `lista-banner` (il banner a tutta larghezza della lista) e' stato tolto: i
// valori rimasti non cambiano, cosi' le serie storiche restano confrontabili.
// `filtro-hero` e' l'hero delle pagine filtro (/bandi/regione/…): una serie a
// parte, per non gonfiare quella della lista.
export type BandofitCtaPosition = 'lista-hero' | 'filtro-hero' | 'dettaglio-sidebar';

export function bandofitCtaUrl(position: BandofitCtaPosition): string {
  const url = new URL(BANDOFIT_URL);
  url.searchParams.set('utm_source', 'edunews24');
  url.searchParams.set('utm_medium', 'cta');
  url.searchParams.set('utm_campaign', 'bandi');
  url.searchParams.set('utm_content', position);
  return url.toString();
}
