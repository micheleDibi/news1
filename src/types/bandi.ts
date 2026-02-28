export interface Group {
  id: string | null;
  titolo: string | null;
  concorsi: any[] | null; // Replace 'any' with a more specific type if known
}

export interface Bando {
  sedi: string[];
  settori: string[];
  categorie: string[];
  calculatedStatus: 'OPEN' | 'CLOSED' | 'PENDING';
  statusLabel: string;
  id: string;
  codice: string;
  titolo: string;
  descrizione: string;
  descrizioneBreve: string;
  figuraRicercata: string;
  dataPubblicazione: string; // ISO date string
  dataScadenza: string;      // ISO date string
  dataVisibilita: string;    // ISO date string
  linkReindirizzamento: string | null;
  tipoProcedura: string;
  group: Group;
  importaCandidature: any | null;
  options: any | null;
  salaryMin: number | null;
  salaryMax: number | null;
  numPosti: number;
  ente: any | null;
  entiRiferimento: string[];
  allegatoMediaId: string | null;
  tipiProcedureGruppo: any | null;
  numCandidaturePending: number | null;
  numCandidatureSubmitted: number | null;
} 