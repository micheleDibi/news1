export interface EUFundingOpportunity {
  // Campos base estándar
  source: string;
  title: string;
  description: string;
  published_date: string;
  deadline: string;
  budget: string;
  category: string;
  url: string;
  status: string | number;
  scraped_at: string;

  // Campos específicos de Incentivi.gov.it
  titolo_base?: string;
  titolo_dettagliato?: string;
  stato_incentivo?: string;
  data_apertura?: string;
  data_chiusura?: string;
  link_ufficiale?: string;
  sezioni?: Record<string, string>;

  // Campos específicos de Obiettivo Europa
  id?: number;
  scadenza?: string;
  giorni_rimanenti?: number | null;
  budget_totale?: number;
  budget_formattato?: string;
  url_relativo?: string;
  url_completo?: string;
  status_codice?: number;
  status_descrizione?: string;
  settori?: string;
  beneficiari?: string;
  regioni?: string;
  programmi?: string;
  tipi_bando?: string;
  tipo_finanziamento?: string;
  codici_ateco?: string;
  pnrr?: boolean;
  recente?: boolean;
  like?: boolean;
  visited?: boolean;
  on_arrival?: boolean;
  updates_active?: boolean;

  // Campos específicos de Italia Domani
  area_geografica?: string;
  destinatari?: string;
  tipologia?: string;
  amministrazione_titolare?: string;
  focus_pnrr?: string;
  descrizione_fondo_pnrr?: string;
}

export interface EUFundingDetails {
  url: string;
  title: string;
  description: string;
  requirements: string;
  eligibility: string;
  application_process: string;
  contact_info: string;
  documents: Array<{
    name: string;
    url: string;
  }>;
}

export interface EUFundingData {
  incentivi_gov_it: EUFundingOpportunity[];
  obiettivoeuropa_com: EUFundingOpportunity[];
  italiadomani_gov_it: EUFundingOpportunity[];
  summary: {
    total_opportunities: number;
    last_updated: string;
    sources: Record<string, number>;
  };
}

export interface EUFundingSource {
  name: string;
  display_name: string;
  url: string;
  type: "api" | "scraping";
  status: "active" | "inactive" | "error";
  last_scraped?: string;
  opportunities_count: number;
}

export interface EUFundingFilters {
  sources?: string[];
  categories?: string[];
  status?: string[];
  date_from?: string;
  date_to?: string;
  budget_min?: number;
  budget_max?: number;
  search_term?: string;
}

export interface EUFundingSearchResult {
  opportunities: EUFundingOpportunity[];
  total: number;
  page: number;
  page_size: number;
  filters: EUFundingFilters;
}
