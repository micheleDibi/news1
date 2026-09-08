/**
 * Normalizzazione ortografica dei campi di prosa di un articolo, applicata
 * lato server prima di scrivere su Supabase.
 *
 * Vale per tutto cio' che passa dalle rotte API: la generazione via skill,
 * la persona in modalita' modifica (che persiste SOLO attraverso il PUT) e
 * il testo digitato a mano dai redattori.
 *
 * L'elenco dei campi e' una ALLOWLIST, mai una ricorsione cieca sul payload:
 * `slug`, `category_slug`, `secondary_category_slugs`, gli URL e `source`
 * non devono essere toccati. Con l'em-dash una ricorsione cieca passava
 * liscia, con gli accenti no.
 */
import { correggi, type Segnalazione } from './ortografia';

/** Campi di testo semplice. */
const CAMPI_TESTO = [
  'title',
  'content',
  'excerpt',
  'summary',
  'title_summary',
  'skill_meta_title',
  'skill_meta_description',
  'skill_angolo',
] as const;

/** Campi che sono array di stringhe. */
const CAMPI_ARRAY = ['tags'] as const;

export interface SegnalazioneCampo extends Segnalazione {
  campo: string;
}

export interface EsitoNormalizzazione {
  /** Ambiguita' che NON sono state corrette: vanno mostrate al redattore. */
  segnalazioni: SegnalazioneCampo[];
  /** Campi effettivamente modificati, per il log. */
  campiCorretti: string[];
  /** Campi lasciati intatti dal normalizzatore, con il motivo. */
  campiSaltati: { campo: string; motivo: string }[];
}

/**
 * Normalizza in place i campi di prosa dell'oggetto ricevuto dal client.
 * Ritorna cosa e' cambiato e cosa resta da controllare a mano.
 */
export function normalizzaArticolo(
  articolo: Record<string, unknown>
): EsitoNormalizzazione {
  const segnalazioni: SegnalazioneCampo[] = [];
  const campiCorretti: string[] = [];
  const campiSaltati: { campo: string; motivo: string }[] = [];

  const passa = (campo: string, valore: unknown): unknown => {
    if (typeof valore !== 'string' || valore === '') return valore;
    const esito = correggi(valore);
    if (esito.saltato) {
      campiSaltati.push({ campo, motivo: esito.saltato });
      return valore;
    }
    if (esito.testo !== valore) campiCorretti.push(campo);
    for (const segnalazione of esito.segnalazioni) {
      segnalazioni.push({ ...segnalazione, campo });
    }
    return esito.testo;
  };

  for (const campo of CAMPI_TESTO) {
    if (campo in articolo) articolo[campo] = passa(campo, articolo[campo]);
  }

  for (const campo of CAMPI_ARRAY) {
    const valore = articolo[campo];
    if (Array.isArray(valore)) {
      articolo[campo] = valore.map((voce, indice) =>
        passa(`${campo}[${indice}]`, voce)
      );
    }
  }

  // faqs: [{ question, answer }]
  const faqs = articolo['faqs'];
  if (Array.isArray(faqs)) {
    articolo['faqs'] = faqs.map((voce, indice) => {
      if (!voce || typeof voce !== 'object') return voce;
      const faq = voce as Record<string, unknown>;
      return {
        ...faq,
        question: passa(`faqs[${indice}].question`, faq['question']),
        answer: passa(`faqs[${indice}].answer`, faq['answer']),
      };
    });
  }

  return { segnalazioni, campiCorretti, campiSaltati };
}
