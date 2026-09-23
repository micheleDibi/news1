/**
 * Select esplicite dell'API /api/v1: MAI '*'. Ogni colonna e' qui per un motivo;
 * quelle interne o sensibili (content, skill_*, article_content, descrizione HTML,
 * contenuto, raw_data, email...) non compaiono. I link alle fonti dello scraper
 * -- link_bando, allegati, raw_data -- non compaiono: l'unica eccezione e' la
 * fonte ufficiale verificata (details.official_source della 1.1), che non e'
 * ancora una colonna. Il test di contratto verifica l'insieme esatto delle colonne.
 */
import type { NomeSelect } from './contratto';

/** `creator` serve solo al lookup dell'autore e non esce mai (contiene il nome reale). */
export const SELECT_ARTICOLO =
  'id, slug, title, title_summary, excerpt, summary, category_slug, secondary_category_slugs, ' +
  'image_url, thumbnail_url, video_url, video_duration, published_at, tags, creator';

export const SELECT_CATEGORIE = 'slug, name, color, order_id';

export const SELECT_SECONDARIE = 'slug, name, parent_category_slug';

/** profiles e' leggibile dall'anon con email e permessi: solo queste quattro colonne. */
export const SELECT_PROFILI = 'id, full_name, public_name, is_displayable';

export const SELECT_INTERPELLO =
  'id, interpello_name, interpello_date, interpello_description, interpello_regione, ' +
  'interpello_provincia, interpello_citta, classe_concorso, article_title, article_subtitle';

export const SELECT_SELEZIONE =
  'id, slug, codice, titolo, article_title, article_subtitle, figura_ricercata, num_posti, tipo_procedura, ' +
  'data_pubblicazione, data_scadenza, sedi, categorie, settori, enti_riferimento, salary_min, salary_max, updated_at';

/**
 * Relazioni dei bandi in UNA query con embed annidati via junction (l'embed
 * diretto fallisce: PGRST200).
 *
 * **Senza la colonna della freschezza**: si chiama `updated_at` sulla tabella e
 * `ultimo_cambiamento_at` sulla vista, quindi la mette il piano
 * (`PianoQuery.colonneExtra`, da `FonteBandi.selectFreschezza`). Scriverla qui
 * vorrebbe dire scegliere una delle due fonti a compile time, e questo modulo
 * e' puro: il flag non lo puo' leggere.
 */
export const SELECT_BANDO =
  'id, slug, titolo, titolo_breve, descrizione_breve, ente_erogatore, area_geografica, tematica, ' +
  'data_pubblicazione, data_apertura, data_scadenza, importo_totale_eur, importo_max_per_progetto_eur, ' +
  'stato_bando, created_at, ' +
  'tipologia:tipologie_bando(nome), programma:programmi(nome), modalita:modalita_erogazione(nome), ' +
  'bando_regioni(regioni(nome, slug)), bando_settori(settori(nome)), bando_beneficiari(beneficiari(nome)), ' +
  'bando_codici_ateco(codici_ateco(codice, descrizione))';

/** Come SELECT_BANDO piu' l'embed !inner usato solo per filtrare per regione (non esce nel DTO). */
export const SELECT_BANDO_CON_REGIONE =
  SELECT_BANDO + ', filtro_regione:bando_regioni!inner(regioni!inner(slug))';

export const SELECT_PER_NOME: ReadonlyMap<NomeSelect, string> = new Map<NomeSelect, string>([
  ['articolo', SELECT_ARTICOLO],
  ['interpello', SELECT_INTERPELLO],
  ['selezione', SELECT_SELEZIONE],
  ['bando', SELECT_BANDO],
  ['bando-con-regione', SELECT_BANDO_CON_REGIONE],
  ['categorie', SELECT_CATEGORIE],
  ['secondarie', SELECT_SECONDARIE],
  ['profili', SELECT_PROFILI],
]);
