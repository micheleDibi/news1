/**
 * JSON-LD della scheda di un bando: `Article` con `about: MonetaryGrant`
 * (il tipo schema.org dei finanziamenti; l'erogatore non è sempre una PA,
 * quindi `Organization` e non `GovernmentOrganization`).
 *
 * Due correzioni rispetto al JSON-LD scritto in pagina:
 *  - `sameAs` valeva `link_bando`, cioè l'URL sull'aggregatore: dichiarava ai
 *    motori che la pagina «uguale» al nostro bando è quella di un concorrente,
 *    su 1 702 schede. Ora `sameAs` esce **solo** con una fonte ufficiale
 *    trovata e pubblicabile, e in F1 è quindi sempre omesso;
 *  - nessun `FAQPage`: le FAQ della scheda sono generate, non sono risposte
 *    dell'ente, e marcarle come tali esporrebbe a una penalizzazione.
 *
 * `JSON.stringify` scarta gli `undefined` ma non i `null`: ogni proprietà
 * facoltativa passa da uno spread condizionale, così una proprietà senza dato
 * non compare proprio invece di comparire vuota.
 *
 * Modulo «foglia»: nessun import impuro, nessuna lettura dell'orologio.
 */
import { urlPubblicabile } from './domini';
import type { FonteUfficiale } from './tipi';

export interface DatiJsonLdBando {
  /** URL canonico della scheda su edunews24.it: è anche `@id`. */
  readonly urlCanonico: string;
  readonly titolo: string;
  readonly titoloBreve?: string | null;
  readonly descrizione?: string | null;
  readonly dataPubblicazione?: string | null;
  /**
   * Istante dell'ultima modifica **sostanziale**, già in ISO 8601. Da F2 è
   * `ultimo_cambiamento_at`: `updated_at` avanza a ogni re-scrape (3 969 righe
   * toccate in un giorno solo) e dichiararlo come `dateModified` insegna ai
   * motori che il nostro `dateModified` non significa niente.
   */
  readonly dataModifica?: string | null;
  readonly enteErogatore?: string | null;
  readonly areaGeografica?: string | null;
  readonly beneficiari?: readonly string[] | null;
  readonly tematiche?: readonly string[] | null;
  readonly importoTotaleEur?: number | null;
  readonly fonteUfficiale?: FonteUfficiale | null;
}

const EDITORE = {
  '@type': 'Organization',
  name: 'EduNews24',
  logo: { '@type': 'ImageObject', url: 'https://edunews24.it/logo.png' },
} as const;

/** `sameAs` solo con fonte ufficiale `trovata` e URL pubblicabile: mai altrimenti. */
function sameAsDa(fonte: FonteUfficiale | null | undefined): string | null {
  if (!fonte || fonte.stato !== 'trovata') return null;
  return urlPubblicabile(fonte.url) ? (fonte.url as string).trim() : null;
}

function elencoNonVuoto(valori: readonly string[] | null | undefined): string[] | null {
  if (!Array.isArray(valori)) return null;
  const puliti = valori.filter((v) => typeof v === 'string' && v.trim() !== '');
  return puliti.length === 0 ? null : puliti;
}

export function jsonLdBando(dati: DatiJsonLdBando): Record<string, unknown> {
  const sameAs = sameAsDa(dati.fonteUfficiale);
  const beneficiari = elencoNonVuoto(dati.beneficiari);
  const tematiche = elencoNonVuoto(dati.tematiche);

  return {
    '@context': 'https://schema.org',
    '@type': 'Article',
    '@id': dati.urlCanonico,
    mainEntityOfPage: dati.urlCanonico,
    headline: dati.titolo,
    ...(dati.titoloBreve ? { alternativeHeadline: dati.titoloBreve } : {}),
    ...(dati.descrizione ? { description: dati.descrizione } : {}),
    url: dati.urlCanonico,
    ...(dati.dataPubblicazione ? { datePublished: dati.dataPubblicazione } : {}),
    ...(dati.dataModifica ? { dateModified: dati.dataModifica } : {}),
    ...(dati.areaGeografica
      ? { spatialCoverage: { '@type': 'Place', name: dati.areaGeografica } }
      : {}),
    ...(beneficiari
      ? { audience: beneficiari.map((nome) => ({ '@type': 'Audience', audienceType: nome })) }
      : {}),
    ...(tematiche ? { keywords: tematiche.join(', ') } : {}),
    author: { '@type': 'Organization', name: 'EduNews24' },
    publisher: { ...EDITORE },
    about: {
      '@type': 'MonetaryGrant',
      name: dati.titolo,
      ...(dati.enteErogatore
        ? { funder: { '@type': 'Organization', name: dati.enteErogatore } }
        : {}),
      ...(typeof dati.importoTotaleEur === 'number' && Number.isFinite(dati.importoTotaleEur)
        ? { amount: { '@type': 'MonetaryAmount', currency: 'EUR', value: dati.importoTotaleEur } }
        : {}),
      ...(sameAs === null ? {} : { sameAs }),
    },
  };
}
