/**
 * Tre righe complete (una per fonte) con in piu' colonne che l'API non deve mai
 * esporre: servono ai test di mappa-opportunita, compreso quello sulle colonne
 * vietate. I valori imitano la forma reale restituita da PostgREST.
 */
import type { RigaBando, RigaInterpello, RigaSelezione } from '../../../src/lib/api-v1/contratto.ts';

/** Colonne interne o link alle fonti: se ne compare una nell'output, e' una fuga. */
export const COLONNE_VIETATE_INTERPELLO = {
  article_content: 'TESTO-INTEGRALE-INTERPELLO',
  interpello_link: 'https://web.spaggiari.eu/sif/app/default/bacheca_personale.php?fonte-vietata',
  source_daily_link: 'https://fonte-vietata.example/daily',
  status: 'completed',
  link_type: 'single',
  city_name: 'CITTA-INTERNA',
  article_keywords: 'KEYWORDS-INTERNE',
};

export const COLONNE_VIETATE_SELEZIONE = {
  descrizione: '<p>HTML-INTEGRALE-SELEZIONE</p>',
  descrizione_breve: '<p>HTML-BREVE-SELEZIONE</p>',
  article_content: 'TESTO-INTEGRALE-SELEZIONE',
  link_reindirizzamento: 'https://fonte-vietata.example/inpa',
  link_candidatura: 'https://fonte-vietata.example/candidatura',
  allegati: [{ url: 'https://fonte-vietata.example/allegato.pdf' }],
  calculated_status: 'OPEN',
  status_label: 'ETICHETTA-INTERNA',
  status: 'completed',
  allegato_media_id: 991,
};

export const COLONNE_VIETATE_BANDO = {
  contenuto: 'TESTO-INTEGRALE-BANDO',
  link_bando: 'https://fonte-vietata.example/bando',
  link_candidatura: 'https://fonte-vietata.example/candidatura-bando',
  stato_processing: 'completed',
  raw_data: { segreto: 'RAW-DATA-INTERNO' },
  confidence_score: 0.97,
  hash_bando: 'HASH-INTERNO',
  fonte_id: 17,
  titolo_raw: 'TITOLO-RAW-INTERNO',
  descrizione_raw: 'DESCRIZIONE-RAW-INTERNA',
  canonical_key: 'CHIAVE-CANONICA-INTERNA',
  fonti_aggiuntive: ['https://fonte-vietata.example/altra'],
  rejection_reason: 'MOTIVO-INTERNO',
  tipo_link: 'diretto',
  livello: 'nazionale-interno',
  data_visibilita: '2026-09-01',
  filtro_regione: [{ regioni: { slug: 'lazio' } }],
};

export const INTERPELLO_COMPLETO: RigaInterpello = {
  id: 1636,
  interpello_name: 'Interpello supplenza AAAA posto comune',
  interpello_date: '2026-09-17T00:00:00',
  interpello_description: 'Descrizione &amp; dettagli dell&#39;interpello',
  interpello_regione: 'Emilia Romagna',
  interpello_provincia: 'Interpelli Pubblicati Da: Bologna',
  interpello_citta: 'Interpelli Pubblicati Da:Casalecchio di Reno',
  classe_concorso: 'AAAA',
  article_title: 'Casalecchio di Reno, interpello per una supplenza AAAA',
  article_subtitle: 'L\'istituto cerca un docente per una supplenza fino al 30 giugno.',
};

export const SELEZIONE_COMPLETA: RigaSelezione = {
  id: 23258,
  slug: 'arpam-marche-avviso-pubblico-29611',
  codice: '29611',
  titolo: 'AVVISO PUBBLICO, PER COLLOQUIO, PER COLLABORATORE TECNICO PROFESSIONALE',
  article_title: 'ARPAM Marche, avviso pubblico per Collaboratore Tecnico Professionale',
  article_subtitle: 'Domande entro il 6 ottobre 2026.',
  figura_ricercata: 'Collaboratore Tecnico Professionale',
  num_posti: 1,
  tipo_procedura: 'colloquio',
  data_pubblicazione: '2026-09-20T22:01:00+00:00',
  data_scadenza: '2026-10-06T21:59:00+00:00',
  sedi: ['Marche', 'Ancona', 'Macerata', 'Marche'],
  categorie: ['Concorso'],
  settori: [],
  enti_riferimento: ['Agenzia Regionale per la Protezione dell\'Ambiente delle Marche'],
  salary_min: '1800.50',
  salary_max: 2400,
  updated_at: '2026-09-21T06:04:01+00:00',
};

export const BANDO_COMPLETO: RigaBando = {
  id: 1120620,
  slug: 'litalia-delle-donne',
  titolo: 'L\'Italia delle donne',
  titolo_breve: 'Avviso Italia delle donne',
  descrizione_breve: 'Contributi a fondo perduto per progetti culturali sulla storia delle donne.',
  ente_erogatore: 'Dipartimento per le pari opportunità',
  area_geografica: 'Nazionale',
  tematica: ['Cultura', 'Pari opportunità', 'Cultura'],
  data_pubblicazione: '2026-09-10',
  data_apertura: '2026-09-15',
  data_scadenza: '2026-10-31',
  importo_totale_eur: 1500000,
  importo_max_per_progetto_eur: 50000,
  stato_bando: 'aperto',
  created_at: '2026-09-14T16:03:02.418+00:00',
  updated_at: '2026-09-21T04:01:59+00:00',
  tipologia: { nome: 'Bandi nazionali' },
  programma: [{ nome: 'PNRR' }],
  modalita: [{ nome: 'Fondo perduto' }],
  bando_regioni: [
    { regioni: { nome: 'Lazio', slug: 'lazio' } },
    { regioni: [{ nome: 'Valle d\'Aosta/Vallée d\'Aoste', slug: null }] },
    { regioni: { nome: 'Abruzzo', slug: 'abruzzo' } },
    { regioni: { nome: 'Lazio', slug: 'lazio' } },
  ],
  bando_settori: [{ settori: { nome: 'Turismo' } }, { settori: [{ nome: 'Arte' }] }, { settori: { nome: 'Arte' } }],
  bando_beneficiari: [{ beneficiari: { nome: 'Enti del terzo settore' } }, { beneficiari: { nome: 'Associazioni' } }],
  bando_codici_ateco: [
    { codici_ateco: { codice: '90.01', descrizione: 'Rappresentazioni artistiche' } },
    { codici_ateco: { codice: '85.52', descrizione: 'Formazione culturale' } },
    { codici_ateco: { codice: '90.01', descrizione: 'Duplicato' } },
    { codici_ateco: { codice: null, descrizione: 'Senza codice' } },
  ],
};
