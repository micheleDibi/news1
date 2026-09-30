# Doppioni ObiettivoEuropa da fondere

Scritto il 30/09/2026 da `db` (giro «ripresa bandi, ottobre 2026», task T-D6). Elenco di lavoro per una sessione con
Michele: **nessuna fusione è stata fatta**, e questo file non contiene SQL da lanciare.

## Da dove viene

Il controllo nuovo dello step SEO (contratto interno §6, task T-C3) rifiuta un bando di ObiettivoEuropa **prima**
della pubblicazione se esiste già un pubblicato di una fonte non OE con la stessa pagina ufficiale, oppure con lo
stesso ente, importo e scadenza. Vale solo per i bandi nuovi.

Provando la regola in sola lettura sui 2 180 pubblicati, `backend-b` ha trovato le coppie **già pubblicate tutte e
due** e mai fuse: 41 righe, 39 schede OE. Le ha lette tutte per titolo: sono doppioni veri, con 2-3 dubbi segnati
sotto. Oggi il lettore vede due schede dello stesso bando, spesso con date o testi diversi.

## Come si fonde (quando si decide)

- Con la RPC `bando_fondi(doppione, master)`, come le fusioni F1-F6 del 30/09 (`correzioni-2026-09-29.sql`): nessuna
  riga cancellata, il doppione resta `completed` con il suo slug e risponde 301 verso il master.
- Il master è la scheda costruita sulla fonte ufficiale (colonna «master» qui sotto). `bando_fondi` può stampare una
  NOTICE se i suoi criteri preferirebbero l'altra: è solo un avviso.
- Prima di fondere, per ogni coppia: le due schede devono essere lo stesso bando (non un altro lotto sulla stessa
  pagina), e il master deve avere le date giuste. Se è il doppione ad avere le date giuste, prima si correggono le date
  del master, come per F3 il 30/09.
- **BandoFit**: finché non fa la sua fase (c), legge `bando` con il predicato storico e il doppione fuso gli resta
  visibile (RIPRESA §4.4, voce L4). Da decidere con Michele: fondere dopo la (c), oppure accettare il doppione su
  BandoFit per quel periodo.
- È il lotto L4 (`fondi-doppioni`) fatto a mano e per coppie approvate: il comando del lotto non va lanciato così
  com'è (RIPRESA §4.4).

## Le 41 coppie

| # | scheda OE (doppione) | scheda della fonte ufficiale (master) | criterio | bando | nota |
|---|---|---|---|---|---|
| 1 | 17542 | 2907 | URL + ente, importo, scadenza | Offerta formativa apprendistato professionalizzante Piemonte 2026-2027 |  |
| 2 | 17558 | 2912 | ente, importo, scadenza | Contributi a fondo perduto per vivaistica forestale in Piemonte | chiudono tutti e due stanotte (scadenza 30/09) |
| 3 | 17665 | 2305 | ente, importo, scadenza | Basilaureati: bonus alle imprese per assumere laureati disoccupati in Basilicata |  |
| 4 | 17681 | 2647 | ente, importo, scadenza | Fondo perduto FESR Liguria 2026 per startup innovative |  |
| 5 | 17741 | 2918 | ente, importo, scadenza | Fondo perduto per insediamento giovani agricoltori in Piemonte, bando 2026 |  |
| 6 | 17798 | 2648 | ente, importo, scadenza | Bando economia circolare Liguria 2026: 5 milioni per PMI da Regione |  |
| 7 | 17806 | 2231 | ente, importo, scadenza | Incentivi alle imprese abruzzesi per assumere disoccupati over 36 | **no**: stesso importo e scadenza ma bando diverso (over 36); la coppia giusta è 17806/2232 |
| 8 | 17806 | 2232 | URL | Incentivi all'assunzione di giovani 18-35 anni in Abruzzo | coppia giusta (giovani 18-35); trovata anche dal reviewer |
| 9 | 17807 | 2231 | URL | Incentivi alle imprese abruzzesi per assumere disoccupati over 36 | trovata anche dal reviewer |
| 10 | 18356 | 2242 | URL + ente, importo, scadenza | Welfare aziendale Abruzzo: 4 milioni a fondo perduto per la conciliazione | trovata anche dal reviewer; il 18356 ha l'Avviso che al 2242 manca fra gli allegati |
| 11 | 109262 | 2885 | URL + ente, importo, scadenza | Piemonte: 6 milioni FSE+ per servizi creazione d'impresa 2026-2028 |  |
| 12 | 124140 | 2895 | URL | Contributi sugli interessi per cooperative agricole in Piemonte 2026 |  |
| 13 | 255052 | 53179 | URL + ente, importo, scadenza | Corsi di lingua gratuiti in Abruzzo con 2 milioni di fondi FSE+ |  |
| 14 | 258875 | 140357 | URL + ente, importo, scadenza | Dote Lavoro Giovani Abruzzo: 5 milioni a fondo perduto per PMI |  |
| 15 | 342842 | 308084 | ente, importo, scadenza | Accordi di Programma 2026-2028 in Piemonte: 5,97 milioni per opere locali |  |
| 16 | 342849 | 30537 | URL + ente, importo, scadenza | Contributi a fondo perduto per prevenire danni biotici alle colture in Piemonte | proroga applicata a tutti e due dal file dell'01/10 (A7, A8) |
| 17 | 356642 | 307528 | URL + ente, importo, scadenza | Digitalizzazione PMI Abruzzo: 10 milioni a fondo perduto dal FESR 2026 |  |
| 18 | 415163 | 327038 | ente, importo, scadenza | Contributi 2026 per Enoteche regionali e Strade del vino del Piemonte |  |
| 19 | 455777 | 352151 | URL | Contributi per defibrillatori DAE nei rifugi ed edifici pubblici del Piemonte | **da guardare a mano**: DAE nei comuni montani contro rifugi, stessa pagina |
| 20 | 459588 | 441770 | URL | Percorsi IeFP in Abruzzo: candidature aperte per il ciclo 2026-2029 |  |
| 21 | 517160 | 340501 | ente, importo, scadenza | Riqualificazione energetica alloggi sociali in Liguria: 9 milioni FESR | apertura applicata dal file dell'01/10 (B16) |
| 22 | 547031 | 340673 | URL + ente, importo, scadenza | Contributi Piemonte 2025 per polizze zootecniche agevolate | **da guardare a mano**: polizze zootecniche, forse l'edizione 2025 |
| 23 | 562298 | 512534 | ente, importo, scadenza | Bando Liguria 2026: 1 milione per attrarre produzioni audiovisive | aperture applicate dal file dell'01/10 (B14) |
| 24 | 562301 | 442285 | URL + ente, importo, scadenza | Orientamento precoce in Piemonte: 11 milioni FSE+ per il 2026-2028 |  |
| 25 | 562312 | 412981 | ente, importo, scadenza | Cantieri di lavoro 2026 in Piemonte per persone disoccupate |  |
| 26 | 562313 | 512533 | ente, importo, scadenza | Bando Liguria 2026: 750mila euro per sviluppo e produzione audiovisiva | aperture applicate dal file dell'01/10 (B13) |
| 27 | 562314 | 457427 | URL + ente, importo, scadenza | Contributi Regione Piemonte 2026 per la stampa periodica locale |  |
| 28 | 562318 | 412982 | URL + ente, importo, scadenza | Cantieri di lavoro 2026 in Piemonte per persone con disabilità |  |
| 29 | 562336 | 412983 | URL + ente, importo, scadenza | Cantieri di lavoro 2026 in Piemonte per persone con misure restrittive |  |
| 30 | 736932 | 661135 | URL + ente, importo, scadenza | Contributi Piemonte 2026 per valorizzare patrimonio linguistico e dialettale | chiudono tutti e due stanotte (scadenza 30/09) |
| 31 | 804009 | 801432 | ente, importo, scadenza | Contributi Regione Lazio per promozione turistica innovativa ed esperienziale |  |
| 32 | 850345 | 556320 | URL | Buono domiciliarità Piemonte 2026/2027: 700 euro al mese per non autosufficienti | buono domiciliarità: vedi anche 530270 e 556361, stessa pagina |
| 33 | 860670 | 556319 | URL | Contributi Regione Piemonte per iniziative a sostegno del Libano |  |
| 34 | 1046004 | 1009768 | URL | Bando Abruzzo FESR: 10 milioni per opere anti-valanghe nei Comuni montani |  |
| 35 | 1056578 | 921802 | ente, importo, scadenza | Rimborsi ad allevatori piemontesi per danni da grandi carnivori 2026 | **da guardare**: lo stesso OE ha anche la coppia per URL con 925837 |
| 36 | 1056578 | 925837 | URL | Risarcimenti predazioni da grandi carnivori in Piemonte, bando 1/2026 | coppia per URL: probabilmente quella giusta |
| 37 | 1071261 | 952614 | URL | Bando Corno d'Africa 2026: contributi Regione Piemonte per progetti in Kenya |  |
| 38 | 1168951 | 1055910 | URL | Contributi 2026 per editori e librerie indipendenti del Piemonte |  |
| 39 | 1184725 | 1055914 | URL + ente, importo, scadenza | Contributi 2026 in Piemonte per promozione del libro e concorsi letterari |  |
| 40 | 1260468 | 1055909 | URL | Voucher fino a 3.500 euro per editori piemontesi al Salone del libro 2026 |  |
| 41 | 1262403 | 1261832 | URL + ente, importo, scadenza | Contributi Regione Piemonte per la Giornata della memoria vittime mafie 2027 |  |

Da guardare a mano prima di fondere: **455777/352151**, **547031/340673**, le due righe del **17806** (vale 17806/2232)
e le due del **1056578** (probabilmente vale 1056578/925837).

## Altri doppioni visti il 30/09, fuori da questo criterio

Non sono coppie OE/fonte ufficiale, o non hanno la stessa pagina né lo stesso ente, importo e scadenza. Sono emersi
controllando i bandi di `correzioni-2026-10-01.sql` (T-D3):

- 530270, 556320 e 556361: buono domiciliarità Piemonte 2026/2027, tre schede (una con lo slug «domiciliarieta»);
- 1162829 e 1162880: IFTS Piemonte 2026-2029;
- 352150 e 356653: bando Piemonte e Africa subsahariana 2026;
- 2649 e 17727: efficienza energetica degli edifici pubblici, FESR Liguria (IV bando);
- 2612 e 18305: Acchiappa Talenti Lazio (il 18305 ha la scadenza giusta dal file dell'01/10).
