// /api/v1: rotta di sola lettura, logica in src/lib/api-v1/ (vedi rotta.ts e risorse.ts).
import { definisciRotta } from '../../../../lib/api-v1/rotta';
import { FEED } from '../../../../lib/api-v1/risorse';

const rotta = definisciRotta(FEED);
export const GET = rotta.GET;
// Esplicito: con ALL esportato, Astro manderebbe HEAD su ALL (405) invece che su GET.
export const HEAD = rotta.GET;
export const OPTIONS = rotta.OPTIONS;
export const ALL = rotta.ALL;
