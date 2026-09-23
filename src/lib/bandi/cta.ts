/**
 * Scelta dell'unica CTA della scheda.
 *
 * Il bug che chiude: la scheda ripiegava su `link_bando` senza nessun filtro, e
 * `link_bando` è l'URL della riga **sull'aggregatore** da cui il bando è stato
 * raccolto. Risultato misurato: 94 CTA su 230 mandavano l'utente
 * sull'aggregatore, 31 con l'etichetta «Apri la pagina ufficiale del bando».
 * Qui `link_bando` non è nemmeno un ingresso: non si può più ripiegarci per
 * distrazione.
 *
 * Cascata di §13.4, dalla più autorevole:
 *  1. link di candidatura → «Vai al modulo di candidatura»
 *  2. fonte ufficiale trovata, pagina dell'ente o atto → «Apri la pagina
 *     ufficiale del bando»
 *  3. portale pubblico → «Consulta il bando sul portale pubblico»
 *  4. altrimenti **nessun box**: meglio nessun pulsante che un pulsante che
 *     porta altrove.
 *
 * In F1 (nessuna colonna nuova) arriva solo `candidaturaEstratta`, cioè
 * `link_candidatura` quando `link_candidatura_source = 'extracted'`: è l'unico
 * valore che la skill ha davvero trovato nell'HTML: `fallback_source` ricade
 * sull'URL della fonte, che è di nuovo l'aggregatore.
 *
 * Modulo «foglia»: nessun import impuro.
 */
import { urlPubblicabile } from './domini';
import type { FonteUfficiale, LinkBando } from './tipi';

export interface Cta {
  readonly url: string;
  readonly etichetta: string;
}

export interface IngressoCta {
  /** Righe di `bando_link` (solo da F2): si usano le pubblicabili. */
  readonly link?: readonly LinkBando[] | null;
  /** Fonte ufficiale del bando (solo da F2). */
  readonly fonteUfficiale?: FonteUfficiale | null;
  /** F1: `link_candidatura` se e solo se `link_candidatura_source='extracted'`. */
  readonly candidaturaEstratta?: string | null;
}

function primoLinkUtile(
  link: readonly LinkBando[] | null | undefined,
  tipo: string,
): string | null {
  if (!Array.isArray(link)) return null;
  for (const voce of link) {
    if (voce.tipo !== tipo) continue;
    if (voce.pubblicabile === false) continue;
    if (!urlPubblicabile(voce.url)) continue;
    return voce.url.trim();
  }
  return null;
}

function urlFonte(fonte: FonteUfficiale | null | undefined): string | null {
  if (!fonte || fonte.stato !== 'trovata') return null;
  return urlPubblicabile(fonte.url) ? (fonte.url as string).trim() : null;
}

/** La CTA da mostrare, o `null` se nessuna destinazione è affidabile. */
export function sceltaCta(ingresso: IngressoCta): Cta | null {
  const candidatura = primoLinkUtile(ingresso.link, 'candidatura');
  if (candidatura !== null) return { url: candidatura, etichetta: 'Vai al modulo di candidatura' };

  const estratta = ingresso.candidaturaEstratta;
  if (typeof estratta === 'string' && urlPubblicabile(estratta)) {
    return { url: estratta.trim(), etichetta: 'Vai al modulo di candidatura' };
  }

  const fonte = ingresso.fonteUfficiale;
  const url = urlFonte(fonte);
  if (url !== null && fonte) {
    if (fonte.tipo === 'ente' || fonte.e_atto === true) {
      return { url, etichetta: 'Apri la pagina ufficiale del bando' };
    }
    if (fonte.tipo === 'portale_pubblico') {
      return { url, etichetta: 'Consulta il bando sul portale pubblico' };
    }
  }

  const portale = primoLinkUtile(ingresso.link, 'portale');
  if (portale !== null) return { url: portale, etichetta: 'Consulta il bando sul portale pubblico' };

  return null;
}
