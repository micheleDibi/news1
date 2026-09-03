/**
 * Testi editoriali delle tre pagine elenco: introduzione e FAQ.
 *
 * Sono strutturati come segmenti invece che come HTML in stringa, cosi' Astro fa
 * l'escaping da solo e i link interni restano tipizzati. Le FAQ vivono in un array
 * unico: il markup visibile e il JSON-LD leggono lo stesso dato e non possono divergere.
 *
 * NIENTE claim fattuali non verificabili. Sulla frequenza di aggiornamento la formula
 * e' volutamente prudente ("piu' volte al giorno"): tutte e tre le pipeline schedulano
 * quattro esecuzioni giornaliere (backend/app/interpelli_sender.py:17,
 * backend/app/selezione_personale_sender.py:17, backend/app/bandi_sender.py:41).
 * NB: README.md:618 dichiara edunews-bandi-sender.service disabilitato in v5, ma il
 * sender bandi e' confermato attivo in produzione (03/09/2026): e' il README a essere
 * disallineato, non il codice.
 */

export type SegmentoTesto =
  | { tipo: 'testo'; testo: string }
  | { tipo: 'link'; testo: string; href: string };

export interface IntroSezione {
  titolo: string;
  /** Paragrafi: ognuno e' una sequenza di segmenti. */
  paragrafi: SegmentoTesto[][];
  /** Riga breve mostrata al posto dell'introduzione sulle pagine oltre la prima. */
  rigaBreve: string;
}

const t = (testo: string): SegmentoTesto => ({ tipo: 'testo', testo });
const a = (testo: string, href: string): SegmentoTesto => ({ tipo: 'link', testo, href });

export const INTRO_INTERPELLI: IntroSezione = {
  titolo: 'Come funzionano gli interpelli',
  paragrafi: [
    [
      t('Gli interpelli sono gli avvisi con cui le scuole cercano personale docente per coprire posti rimasti scoperti quando le graduatorie a disposizione dell’istituto non bastano. In questa pagina raccogliamo gli interpelli pubblicati dagli istituti italiani e li rendiamo consultabili per '),
      a('regione', '/interpelli/regione'),
      t(', per '),
      a('provincia', '/interpelli/provincia'),
      t(' e per '),
      a('classe di concorso', '/interpelli/classe'),
      t('.'),
    ],
    [
      t('Ogni scheda riporta la denominazione dell’avviso, la sede, la classe di concorso indicata dalla scuola e la data di pubblicazione, con il rimando al documento originale dell’istituto. Requisiti, termini e modalità di invio della candidatura cambiano da avviso ad avviso: prima di candidarti leggi sempre il testo integrale pubblicato dalla scuola, che resta l’unica fonte valida. L’elenco viene aggiornato più volte al giorno; un interpello può essere prorogato, rettificato o revocato dall’istituto dopo la pubblicazione.'),
    ],
  ],
  rigaBreve: 'Interpelli pubblicati dalle scuole italiane, consultabili per regione, provincia e classe di concorso.',
};

export const INTRO_SELEZIONE: IntroSezione = {
  titolo: 'Concorsi e selezioni nella Pubblica Amministrazione',
  paragrafi: [
    [
      t('In questa pagina raccogliamo concorsi pubblici, avvisi di mobilità e selezioni di professionisti ed esperti pubblicati da amministrazioni ed enti italiani. Puoi filtrare per '),
      a('categoria', '/selezione-personale/categoria'),
      t(', per sede e per '),
      a('regione', '/selezione-personale/regione'),
      t('.'),
    ],
    [
      t('Ogni scheda riporta l’ente di riferimento, la figura ricercata, il numero di posti, il tipo di procedura, la data di pubblicazione e la data di scadenza indicata dall’ente, e rimanda al testo integrale del bando. Requisiti, titoli richiesti, prove d’esame e modalità di presentazione della domanda sono definiti esclusivamente dal bando dell’amministrazione, che va letto per intero prima di candidarsi. L’elenco viene aggiornato più volte al giorno; gli annunci con scadenza già superata restano consultabili come archivio e compaiono dopo quelli ancora aperti.'),
    ],
  ],
  rigaBreve: 'Concorsi, avvisi di mobilità e selezioni pubblicati da amministrazioni ed enti italiani.',
};

export const INTRO_BANDI: IntroSezione = {
  titolo: 'Che cosa trovi in questa pagina',
  paragrafi: [
    [
      t('In questa pagina raccogliamo bandi e avvisi di finanziamento pubblico di livello europeo, nazionale, regionale e locale, insieme a quelli di fondazioni e altri enti. I programmi più rappresentati sono '),
      a('FSE+', '/bandi/programma/fse-fondo-sociale-europeo'),
      t(', '),
      a('FESR', '/bandi/programma/fesr'),
      t(', il '),
      a('PNRR', '/bandi/programma/pnrr'),
      t(' e i '),
      a('bandi regionali e locali', '/bandi/tipologia/bandi-regionali-locali'),
      t('.'),
    ],
    [
      t('Puoi filtrare per '),
      a('regione', '/bandi/regione'),
      t(', '),
      a('settore', '/bandi/settore'),
      t(', beneficiario, '),
      a('programma', '/bandi/programma'),
      t(', modalità di erogazione, codice ATECO, '),
      a('tipologia', '/bandi/tipologia'),
      t(', stato del bando, importo e finestra di scadenza. Ogni scheda riporta l’ente erogatore, l’area geografica, le date di pubblicazione e scadenza e, quando disponibile, la dotazione complessiva, oltre al collegamento alla fonte ufficiale. Lo stato mostrato accanto a ciascun bando tiene conto della data di scadenza indicata dalla fonte. L’elenco viene aggiornato più volte al giorno. Dotazioni, requisiti dei beneficiari, spese ammissibili e modalità di presentazione della domanda sono definiti dal testo ufficiale della misura, che va sempre consultato prima di procedere.'),
    ],
  ],
  rigaBreve: 'Bandi e avvisi di finanziamento pubblico europei, nazionali, regionali e locali.',
};

/**
 * FAQ di /interpelli. Le risposte restano generiche e rimandano sempre al testo
 * dell’avviso: le condizioni le stabilisce la singola scuola, non noi.
 * Stesso array per il markup visibile e per il JSON-LD FAQPage.
 */
export const FAQ_INTERPELLI: ReadonlyArray<{ question: string; answer: string }> = [
  {
    question: 'Che cos’è un interpello scolastico?',
    answer:
      'È l’avviso con cui una scuola cerca personale per coprire un posto rimasto scoperto quando le graduatorie a disposizione dell’istituto non consentono di individuare un supplente. Ogni interpello è pubblicato dalla singola scuola, che ne definisce ambito, durata e destinatari: le condizioni valide sono solo quelle indicate nel testo dell’avviso.',
  },
  {
    question: 'Chi può rispondere a un interpello?',
    answer:
      'I requisiti sono stabiliti dall’avviso stesso e cambiano da scuola a scuola: possono riguardare il titolo di studio, l’abilitazione, l’inserimento in determinate graduatorie o la disponibilità a raggiungere la sede. Prima di inviare la candidatura verifica sempre i requisiti nel testo integrale dell’interpello pubblicato dall’istituto.',
  },
  {
    question: 'Come si presenta la candidatura?',
    answer:
      'Modalità e termini di invio sono indicati nell’interpello: la scuola specifica a chi scrivere, quale documentazione allegare ed entro quando. In questa pagina trovi il rimando al documento originale; per candidarti segui esclusivamente le istruzioni contenute in quel testo.',
  },
  {
    question: 'Ogni quanto viene aggiornato l’elenco?',
    answer:
      'L’elenco viene aggiornato più volte al giorno con gli interpelli raccolti dalle fonti scolastiche. Un avviso può però essere prorogato, rettificato o revocato dalla scuola dopo la pubblicazione: la versione che fa fede è sempre quella pubblicata dall’istituto.',
  },
];
