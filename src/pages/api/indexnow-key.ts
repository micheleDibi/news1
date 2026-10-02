export const prerender = false;

import type { APIRoute } from 'astro';
import { rispostaStatoChiave } from '../../lib/indexnow-chiave';

// Solo lo stato: la chiave non va mai nel corpo (la serve /<chiave>.txt a chi la conosce).
export const GET: APIRoute = async () => rispostaStatoChiave(import.meta.env.INDEXNOW_API_KEY);
