/// <reference path="../.astro/types.d.ts" />
interface ImportMetaEnv {
  readonly PUBLIC_SUPABASE_URL: string;
  readonly PUBLIC_SUPABASE_ANON_KEY: string;
  /** API /api/v1: fiducia nelle intestazioni per l'IP del client (cloudflare | nginx | diretta). */
  readonly API_V1_FIDUCIA_IP?: string;
  /** API /api/v1: richieste per client nel token bucket (default 60). */
  readonly API_V1_RL_CAPACITA?: string;
  /** API /api/v1: gettoni ricaricati al secondo (default 1). */
  readonly API_V1_RL_RICARICA?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}