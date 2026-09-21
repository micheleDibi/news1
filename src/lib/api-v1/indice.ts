/**
 * Dati dell'indice GET /api/v1: nessun accesso al DB, solo costanti e sezioni.
 * Il limite di frequenza arriva dal chiamante (che conosce la configurazione
 * effettiva letta dall'ambiente).
 */
import {
  BASE_API, CONTENT_SIGNAL, URL_DOCUMENTAZIONE, URL_OPENAPI, URL_TERMINI, VERSIONE_API,
} from './costanti';
import { SEZIONI, sezioneDto } from './sezioni';
import type { SezioneDto } from './contratto';

export interface FeedIndice {
  json: string;
  rss: string;
}

export interface RisorsaIndice {
  name: string;
  url: string;
  /** null per le risorse senza feed (categories). */
  feeds: FeedIndice | null;
}

export interface LimiteIndice {
  requests: number;
  window_seconds: number;
}

export interface IndiceDati {
  name: string;
  version: string;
  documentation: string;
  openapi: string;
  terms_of_service: string;
  content_signal: string;
  rate_limit: LimiteIndice;
  resources: RisorsaIndice[];
  sections: SezioneDto[];
}

/** Risorse nell'ordine di esposizione. */
const RISORSE_INDICE: readonly { nome: string; conFeed: boolean }[] = [
  { nome: 'articles', conFeed: true },
  { nome: 'categories', conFeed: false },
  { nome: 'interpelli', conFeed: true },
  { nome: 'selezione-personale', conFeed: true },
  { nome: 'bandi', conFeed: true },
];

function risorsaIndice(nome: string, conFeed: boolean): RisorsaIndice {
  return {
    name: nome,
    url: `${BASE_API}/${nome}`,
    feeds: conFeed ? { json: `${BASE_API}/feeds/${nome}.json`, rss: `${BASE_API}/feeds/${nome}.xml` } : null,
  };
}

export function datiIndice(limite: LimiteIndice): IndiceDati {
  return {
    name: 'API pubblica EduNews24',
    version: VERSIONE_API,
    documentation: URL_DOCUMENTAZIONE,
    openapi: URL_OPENAPI,
    terms_of_service: URL_TERMINI,
    content_signal: CONTENT_SIGNAL,
    rate_limit: { requests: limite.requests, window_seconds: limite.window_seconds },
    resources: RISORSE_INDICE.map((r) => risorsaIndice(r.nome, r.conFeed)),
    sections: SEZIONI.map((s) => sezioneDto(s)),
  };
}
