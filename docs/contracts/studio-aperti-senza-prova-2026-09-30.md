# Studio: bandi «aperti» senza scadenza né prova (30/09/2026)

Risultato del workflow `studio-aperti-senza-prova` (9 agenti, critici avversari). DA PORTARE A MICHELE prima di sbloccare il percorso A.

## Sintesi per Michele
Oggi circa 410 bandi risultano «aperto» senza scadenza e senza che nessuno l'abbia mai verificato: restano aperti per sempre, anche quelli già chiusi. Nel campione di 38 bandi controllati a mano, il 16% era chiuso.
La soluzione ha tre parti e gira tutta da sola.
1) Recupero dello stock. Il passo di verifica, già previsto dal piano, legge per ogni bando la pagina ufficiale che riusciamo a raggiungere, compresi i link agli enti delle schede ObiettivoEuropa e i domini degli enti pubblici presi ogni mese da IndicePA. Su quella pagina cerca la scadenza, l'etichetta «Chiuso/Aperto» o frasi come «bando scaduto» e «sportello sospeso».
2) Onestà. Un bando senza prova non viene chiuso a tempo. Se dopo la verifica non ha né una scadenza né una conferma recente, sul sito compare «Aperto · da verificare». Resta fra gli aperti e viene riletto ogni 14 giorni.
3) Bandi futuri. Prima di pubblicarli si legge la pagina per intero: oggi il preprocess ne vede solo i primi 4 000 caratteri, quasi tutti menu, e su LazioEuropa perde la scadenza. Si fondono i doppioni. Un «aperto» senza scadenza si trattiene fino a 24 ore, il tempo di cercarla.
Quanto ai numeri, su circa il 40% dei 410 arriva una prova: chiusura, scadenza, conferma o smentita. Il restante 60% circa (230-260, quasi tutti ObiettivoEuropa su siti di fondazioni o di enti senza etichetta di stato) prende il bollino «da verificare». È una risposta onesta e stabile, non una soluzione miracolosa.
I bandi futuri nello stesso stato scendono da circa 30 a circa 5-10 al mese, e dopo 7 giorni anche questi mostrano il bollino.
A te restano solo tre scelte (qui sotto) e i passi una tantum già previsti dal piano: applicare la migrazione 13 e passare in attivo dopo l'ombra. Nulla di ricorrente.

## Soluzione
SOLUZIONE SCELTA: si combinano la parte d'ingresso del progetto 3, il ciclo di vita del progetto 2 senza timer e senza conferma del modello, e dal progetto 1 solo la lista bianca dal DB più IndicePA filtrato. Tutto si innesta nel percorso A del giro 2. Non nasce un sistema parallelo.

PRINCIPIO. Ogni «aperto» pubblicato senza data_scadenza finisce, in automatico, in una sola di queste condizioni, calcolate alla lettura (stato_bando non cambia mai senza un evento):
(a) chiuso con prova, tramite l'evento 'chiusura' del percorso A, con i limiti già decisi (lettori per ente, G7e a 60 h, 20 per giro, freno per ente);
(b) una scadenza: con la rettifica del ramo A (d) se la pagina è di tipo i/ii/iii, altrimenti come termine_indicato con provenienza dichiarata. Quando il termine passa diventa 'termine_passato';
(c) confermato da un lettore strutturato negli ultimi 30 giorni (A2 invariata: il modello non conferma mai);
(d) smentito dalla pagina ufficiale, cioè chiuso, sospeso o scaduto, oppure segnalato dall'aggregatore: motivo pubblico, nessuna chiusura;
(e) 'senza_conferma': motivo stabile, badge «Aperto · da verificare», resta fra gli aperti e nei contatori (§15 invariato, nessun timer, A2 rispettata). Viene riletto ogni 14 giorni.

PARTE 1, RECUPERO DELLO STOCK (verifica-stato esteso):
1. Lista bianca letta dal DB: `_tabella_corrente` e verifica-stato usano le righe di dominio_ufficiale, oggi ignorate (la trappola di RIPRESA). A questa si aggiunge un import MENSILE AUTOMATICO di IndicePA, FILTRATO sugli host già citati nei nostri link. Rende leggibili circa 39 degli 89 OE fuori lista, senza toccare le prestazioni della vista (niente Verifica 7). Le fondazioni private NON entrano: rientrano nella (e).
2. Nuove pagine leggibili in §5.3:
   - (ii-c): candidato_prioritario sull'host della fonte di scraping, verificante e con titolo simile. Recupera 2475 e 2520, chiusi.
   - normalizza_link_bando: due URL nello stesso campo (5699, 5700); accorciatori come rpu.gl seguiti solo verso un dominio verificante (5698).
   Le pagine (iv) della scheda OE restano senza eventi (G2v invariato): danno segnale, termine e, solo con un lettore per ente e titolo «alto», conferma.
3. Lettore generico SOLO SEGNALE (chiave 'generico'), da usare dove non c'è un lettore per ente. Legge le frasi compiute «bando chiuso/scaduto», «sportello chiuso/sospeso», «non è più possibile presentare domanda», «dotazione esaurita», con le esclusioni delle formule potenziali di §5.4. Produce stato_letto 'chiuso' con solo_segnale, quindi 'smentito_dalla_fonte'. Non produce MAI 'aperto' né eventi. È asimmetrico per costruzione: può solo accendere un avviso, mai spegnerlo. Risponde all'obiezione sulle frasi di sportello, che nel campione compaiono su 12 bandi chiusi su 19.
4. termine_indicato da quattro fonti, con la colonna termine_indicato_fonte e un sottotesto che dice da dove viene (risponde all'obiezione del «Il testo del bando indica…» falso). In ordine di precedenza:
   - calendario_ufficiale: raw_data di VdA 280 e JTF 296, solo se l'host della fonte è verificante;
   - pagina: termine_nel_testo sul testo della pagina, con verbo di presentazione ed esclusione di fiere ed eventi;
   - testo: titolo e descrizione_breve;
   - aggregatore: deadline_label di OE.
   È sempre e solo un indizio e non genera eventi.
5. Segnale dell'aggregatore (OE), gratuito. Il listing che il giro scarica già scrive in bando_controllo segnale_aggregatore ∈ {assente_dal_listing (NULL visto trattato come 23/09, solo con copertura piena e dopo 3 giri), in_uscita (status 2), scadenza_passata (etichetta con data < oggi)}. spariti() e gli eventi del monitor NON cambiano. Il segnale alza la priorità (88), invalida una conferma più vecchia del segnale e toglie la grazia.
6. Doppioni: fusione automatica con i criteri esatti (quello per URL esiste già, più un nuovo criterio 'riga_calendario': stessa fonte, nessun link_bando, stessa descrizione normalizzata del calendario e stesso source_url o stessa data di chiusura). Riguarda le 13 coppie LazioEuropa 235/237, i 3 VdA PDF/CSV e i 2 Interreg. Tetto di 10 fusioni per giro (decisione 2).

PARTE 2, REGOLA v2 DEL RAMO A (cinque motivi invariati, API invariata):
- A1 lettura valida chiuso/uscito/in apertura → smentito_dalla_fonte;
- A2 lettura 'aperto' dell'estrattore negli ultimi 30 giorni e più recente dell'eventuale segnale_aggregatore_at → NULL;
- A3 termine_indicato < oggi → termine_passato;
- A4 esaminato_attivo_at NULL → NULL. La nuova colonna si scrive SOLO in attivo, quindi l'ombra non accende nulla: risponde all'obiezione bloccante sulla A3b del progetto 3;
- A5 segnale_aggregatore_at non NULL → senza_conferma;
- A6 termine_indicato ≥ oggi → NULL, con sottotesto e provenienza;
- A7 pubblicato_at al massimo 7 giorni fa → NULL (grazia);
- A8 → senza_conferma (decisione 1).

PARTE 3, BANDI FUTURI (ingresso, prompt invariati, nessun rifiuto):
1. Preprocess: il blocco CONTENUTO PAGINA diventa le prime 1 500 battute del testo (dove sta l'etichetta di stato) più seleziona_sezioni(testo) fino a 8 000. seleziona_sezioni prende testo, non html, e funziona anche col markdown Firecrawl. Si passa la provenienza a validate_date_candidate. Ripiego sulla finestra (§6.3) e sui lettori per ente per termine_finale ed etichetta.
2. OE: se il modello non trova una data, status = '1' e il deadline_label si converte in una data ≥ oggi, allora quella data si scrive SOLO se la citazione «Scadenza: <etichetta>» è nel testo della scheda scaricata (validate_date_candidate con provenienza aggregatore). È la stessa provenienza e la stessa regola delle 785 scadenze OE di oggi, non una data presa da raw_data.
3. OE status '2' (In uscita) → mai 'aperto': diventa 'in apertura prossimamente' e il ramo I lo segue. on_arrival NON si usa (obiezione bloccante: su OE vuol dire «a sportello»).
4. Fase 'ingresso' di verifica-stato, prima della SEO, sulle righe enriched. Stesse pagine e stessi lettori. Sulle righe non pubblicate scrive direttamente data_scadenza, ora_scadenza e lo stato 'chiuso' da estrattore; data_scadenza_verificata NON si tocca, perché il CHECK della 03 vuole un evento. Semina lettura_stato.storia, così G7e può accoppiare dopo la pubblicazione.
5. Sosta: la SEO salta un 'aperto' senza data_scadenza, senza conferma d'estrattore e senza termine per al massimo INGRESSO_SOSTA_GIRI = 4 giri (24 h, colonna trattenuto_dal), poi pubblica. È una sosta, non un rifiuto. Le righe senza alcun URL e senza alcuna data (PDF di programma, ripiego bando_resolver) restano enriched e vengono contate; si sbloccano da sole con un hash nuovo.
6. Fusione pre-pubblicazione dei gemelli esatti: il doppione non viene mai pubblicato.

COSA SI SCARTA E PERCHÉ:
- la provenienza come terzo segnale del resolver: la (b) è tautologica, la (a) è esposta alle edizioni sbagliate e comunque aggiunge poco a verifica-stato, che legge già (ii) e (iv). §4.1 c resta aperta;
- l'apprendimento automatico degli erogatori e le fondazioni in lista bianca: con 0,85 ≥ 0,80 varrebbero come 'ente' per tutti gli eventi;
- la sonda e la ricerca a pagamento;
- la conferma del modello: pagine ferme, casi 18312 e 18407;
- il timer di 90 giorni, che sarebbe una chiusura a tempo mascherata;
- stato_coerente su on_arrival;
- data_scadenza_verificata scritta senza evento;
- bando_ritira automatico: il ritiro resta solo su richiesta scritta del committente.

## Copertura
Sono stime. Le correggo con le obiezioni: non conto due volte ciò che il percorso A dà già, e le pagine (iv) non producono eventi.

SUI ~410 (base misurata: 426):
- Con una prova o un motivo specifico: circa 150-190, cioè il 37-45%:
  - chiusure con evento: circa 55-65 (44 LazioEuropa «Chiuso», 5 Piemonte, Calabria e Lombardia dal percorso A; 2475 e 2520 via ii-c);
  - conferme strutturate: circa 45-60 (41 etichette «Aperto» dei lettori, più circa 5-15 pagine iv su host con un lettore);
  - scadenze (rettifica o termine_indicato): circa 25-35 (63 descrizioni con una data; VdA e JTF dal calendario; 6 etichette OE con data; 5698). Di queste, circa 10 finiscono subito in termine_passato (562317, vecchie edizioni);
  - smentiti o segnalati: circa 20-35 (lettore generico sulle pagine iv e IPA, Calabria «Valutazione», 5699 e 5700 sospesi, 5 OE spariti dal listing, 6 con status 2).
- Residuo in 'senza_conferma' stabile: circa 220-260, quasi tutti OE su host senza un lettore per ente o di fondazioni. Scende man mano che si aggiungono lettori (il secondo lotto copre i primi host per numero di bandi) e con IndicePA.

SUI 258 ILLEGGIBILI:
- con qualcosa in mano: circa 50-75. Il dettaglio:
  - 2 chiusi e 3 Puglia trattati (1 con termine, 2 smentiti);
  - 3 VdA con termine ufficiale, dopo la fusione 6 → 3;
  - 1 Interreg, dopo la fusione;
  - circa 6 OE con termine dall'etichetta;
  - 11 OE segnalati;
  - circa 20-40 smentiti o con termine dalle pagine iv (154 già con link verificabile, circa 39 in più con IPA);
  - circa 5-10 confermati dove esiste un lettore.
- Residuo 'senza_conferma': circa 180-210.
- Non recuperabili: 22 OE con tutti i link in 404, fondazioni dietro Cloudflare o JS, 2519 e 2526 (URL troncato, salvo un candidato ii-c).

SUI FUTURI (~30 al mese oggi):
- Pubblicati senza scadenza né conferma: circa 5-10 al mese. LazioEuropa prende la data nella selezione a 8k (3 casi datati su 3) o l'etichetta; le coppie 235/237 vengono fuse; OE prende la data dall'etichetta citata o diventa 'in apertura' con status 2; i PDF senza URL non vengono pubblicati.
- 100% letti prima della pubblicazione, con una sosta di al massimo 24 h per circa il 13% dei nuovi.
- Il residuo mostra «da verificare» dal settimo giorno.

Limiti: il campione è di 38 OE e le pagine sono state scaricate una volta sola; la resa del lettore generico non è misurata sul codice finale. I numeri veri escono dai 7 giorni d'ombra (report-verifica-stato) e dal codice di salute aperti_senza_conferma.

## Modifiche al contratto del giro 2
- **Intestazione, «Stato delle sezioni»**: Il lead libera il percorso A, cioè §2.2, §3, §4, §5, §6, §7 e §15, nella versione aggiornata qui sotto. Registra le tre risposte di Michele e la nota «studio del 30/09: soluzione per gli aperti senza scadenza, versione 2 del ramo A». Resta scritto che A2 è intatta: nessun timer e nessuna chiusura senza evento.
- **§1 Regole per tutti**: Nuova regola: `domini --import --scarica-enti` e `gemelli --attivo` dal Mac solo con `--dry-run`. La fase ingresso di verifica-stato dal Mac si lancia solo con `--dry-run --senza-modello`.
- **§2.2 Migrazione 13**: Punto 2: in `bando_controllo` entrano 5 colonne additive.
- `esaminato_attivo_at` timestamptz: si scrive solo in attivo, a ogni lettura con qualunque esito.
- `termine_indicato_fonte` text CHECK IN ('calendario_ufficiale','pagina','testo','aggregatore'), con il vincolo `bando_controllo_termine_con_fonte`: termine_indicato e termine_indicato_fonte sono entrambi NULL o entrambi NOT NULL.
- `segnale_aggregatore` text CHECK IN ('assente_dal_listing','in_uscita','scadenza_passata').
- `segnale_aggregatore_at` timestamptz.
- `trattenuto_dal` timestamptz.
Le colonne passano quindi da 12 a 17.

Punto 3: il GRANT SELECT ad anon comprende anche esaminato_attivo_at, segnale_aggregatore_at e termine_indicato_fonte, perché la vista è security_invoker (obiezione GRANT).

Punto 4: la firma riceve `p_esaminato_attivo_at timestamptz` e `p_segnale_aggregatore_at timestamptz` prima di p_adesso. Nessuna funzione nuova: l'insieme delle funzioni eseguibili da anon previsto dalla guardia della 12 non cambia.

Punto 5: la vista riceve 5 colonne in coda: le 4 di prima più `termine_indicato_fonte`, NULL quando termine_indicato è NULL.

Punto 8: la verifica attende colonne della vista = prima + 5.

Punto 12, casi PG17 nuovi:
- in ombra (esaminato_attivo_at NULL) un aperto senza scadenza da 30 giorni → NULL;
- lo stesso con esaminato_attivo_at → senza_conferma;
- segnale più recente di una conferma → senza_conferma;
- termine_indicato senza fonte → 23514;
- SET ROLE anon: la SELECT della vista restituisce le 5 colonne.

La 07 e il suo rollback portano le 5 colonne.
- **§3 Regola stato_da_verificare**: `versione: 2`, parametri `{giorni_grazia_pubblicazione: 3, giorni_validita_conferma: 30, giorni_grazia_ramo_a: 7}`, motivi invariati (5). La firma nei tre linguaggi riceve esaminato_attivo_at e segnale_aggregatore_at.

Ramo I invariato. Ramo A v2:
- A1 smentito;
- A2 conferma dell'estrattore al massimo 30 giorni fa E (segnale_aggregatore_at NULL oppure stato_letto_at > segnale_aggregatore_at) → NULL;
- A3 termine passato → termine_passato;
- A4 esaminato_attivo_at NULL → NULL;
- A5 segnale_aggregatore_at non NULL → senza_conferma;
- A6 termine_indicato ≥ oggi → NULL;
- A7 pubblicato_at al massimo 7 giorni fa → NULL;
- A8 → senza_conferma.

La frase «Non esiste un motivo debole» vale ora solo per il ramo I e per l'ombra.

Casi obbligatori nuovi: A4-A8, il confine dei 7 giorni, il segnale prima e dopo la conferma, il termine futuro con il segnale (→ senza_conferma), la conferma del modello che non spegne A8, l'ombra. Almeno 80 casi.
- **§5.2 Candidati**: Nuova riga di priorità: `segnale_aggregatore non NULL e non letto dopo il segnale` → 88.

Nuova fase `ingresso` (vedi §5.10): i candidati sono le righe `stato_processing='enriched'` con stato 'aperto' e data_scadenza NULL, oppure con status OE '2'. Le prende select_enriched_da_leggere, con un tetto proprio.
- **§5.3 Pagina da leggere**: Il punto 2 usa `normalizza_link_bando(testo)` (puro, in verifica_stato.py): divide sugli spazi e tiene gli http(s); un host in `dominio_ufficiale.ACCORCIATORI` (rpu.gl, bit.ly, tinyurl.com, goo.gl, t.ly) si segue con redirect 'tutti' e vale solo se l'URL finale è verificante.

Nuovo punto 2-bis, tipo (ii-c): `bando_controllo.candidato_prioritario` con host uguale all'host della fonte di scraping, verificante, fuori da FONTI_OE e con G3v 'medio'. Ammette eventi come (ii).

Il punto 3 (iv) resta senza eventi; la conferma A2 da una pagina (iv) vale solo con un lettore per ente, titolo 'alto' e segnale_aggregatore NULL.

Il punto 4 (illeggibile) calcola termine_indicato con le quattro fonti di §6.2.

`verificabile` si calcola sulla tabella letta dal DB (db.select_domini_ufficiali), non più sul solo seed.
- **§5.4 Lettura**: Dopo i lettori per ente, sulle pagine di tipo i-iv senza un lettore dedicato, gira il lettore `generico` di §6.1: produce solo 'chiuso' con solo_segnale, altrimenti None. Il modello resta limitato a (i), (ii) e (iii), e un suo 'aperto' non conferma (A2).
- **§5.7 Scritture**: SOLO in attivo si scrive `esaminato_attivo_at`, insieme alle sei colonne stato_letto*. Sempre si scrive `termine_indicato_fonte`, insieme a termine_indicato.

segnale_aggregatore e segnale_aggregatore_at li scrive bando_runner (passo 6-bis), non il passo. Tornano NULL quando la riga ricompare con status '1' e senza un'etichetta scaduta.

Nella fase ingresso, sulle righe NON pubblicate: data_scadenza, ora_scadenza e stato 'chiuso' da un lettore per ente o dalla finestra; data_scadenza_verificata non si tocca (CHECK della 03). A queste si aggiungono lettura_stato.storia e trattenuto_dal.
- **§5.9 Cadenza, contatori, VERITA_NOTA**: Cadenza: senza_conferma (A5/A8) → 14 giorni; segnalato → 3 giorni.

Contatori nuovi: `senza_conferma`, `segnalati`, `smentiti_generico`, `termini_per_fonte {fonte:n}`, `pagine_ii_c`, `link_normalizzati`, e per la fase ingresso `ingresso_letti`, `ingresso_date_scritte`, `ingresso_chiusi`, `trattenuti`, `rilasciati_a_tempo`, `trattenuti_senza_appiglio`, `fusi_prima_della_pubblicazione`.

VERITA_NOTA estesa:
- 2475 e 2520 → chiusura via ii-c;
- 5699 e 5700 → smentito (generico, «sospeso»);
- 5698 → termine_indicato 2026-12-31;
- 803614/803615/803623 → termine calendario_ufficiale;
- 562317 → termine_passato (aggregatore);
- 17773 e 18178 → segnale in_uscita;
- 17883, 18186, 18231, 562317, 18312 → assente_dal_listing;
- 18276 e 18262 → smentito (generico);
- 18407 → NON confermato, perché non ha un lettore per ente.
- **§5.10 nuova: fase ingresso e sosta**: `esegui_passo(giro, fase='ingresso')` gira fra i ricontrolli e la SEO, con tetto di 30 letture e 300 s e senza modello.

`ingresso.pubblicabile(riga, controllo, adesso) -> (bool, motivo)` (puro) è il filtro usato da `bando_seo_runner.run`. Trattiene:
- un 'aperto' senza data_scadenza, senza conferma d'estrattore nella storia e senza termine_indicato ≥ oggi, per al massimo INGRESSO_SOSTA_GIRI (4) giri da trattenuto_dal;
- sempre una riga senza link_bando, senza fonte_ufficiale_url, senza bando_link e senza alcuna data (motivo 'senza_appiglio').

Prima della pubblicazione si fondono i gemelli esatti con `gemelli.criteri_esatti` e `db.fondi_bandi` (dup = la riga nuova).

In ombra la sosta conta e basta: pubblica come oggi.
- **§6.1 Estrattori**: Nuova chiave `generico` in ESTRATTORI. Regex compiute (`bando|avviso|sportello|domande` a non più di 60 caratteri da `chius[oa]|scadut[oa]|sospes[oa]|esaurit[ae]|non è più possibile presentare`) nell'h1, nei badge o label e nei primi 2 000 caratteri del corpo principale, con le esclusioni di §5.4. Il risultato è sempre `solo_segnale=True` e `puo_chiudere=False`, mai 'aperto'.

Fixture: so.camcom (Bando Chiuso), va.camcom (CHIUSURA SPORTELLO), regione.puglia 5699 (sospeso), calabria 18231. Negative: una pagina con «fino ad esaurimento», un «Aperto» generico e una sidebar che elenca altri bandi chiusi.

Secondo lotto di lettori per ente, scelto sui dati: gli host con almeno 5 bandi fra i 410 e un'etichetta di stato strutturata nelle pagine già scaricate. Lo sceglie backend con un report, con fixture reali.
- **§6.2 date_validation**: Nuove funzioni:
- `termine_nella_pagina(testo)`: le stesse regole di termine_nel_testo, sul testo della pagina;
- `termine_da_calendario(raw_data, fonte_id, host_verificante)`: le colonne «chiusura domande», «in corso fino a», DATA_CHIUSURA, con e_presunta;
- `termine_da_etichetta_oe(raw_data)`: riusa segnali.scadenza_da_label.

Ogni funzione restituisce (data, fonte). Precedenza: calendario_ufficiale > pagina > testo > aggregatore.

Casi negativi di §6.2 invariati, più la data della fiera di 1257980 e l'avvio attività di ER 940320.
- **§6.3 Ingresso (preprocess)**: Si aggiunge:
- blocco del prompt = testo[:1500] + `impronte.seleziona_sezioni(testo[1500:], 6500)`, con BUDGET_PROMPT_CHAR = 8000;
- dopo il modello: il lettore per ente sulla pagina (termine_finale → data_scadenza se il modello non l'ha data; 'chiuso' con puo_chiudere → stato 'chiuso');
- per OE: data dal deadline_label solo con status '1', data ≥ oggi e citazione «Scadenza: …» presente nel testo della scheda;
- status '2' → 'in apertura prossimamente'; on_arrival escluso.

«Nessun rifiuto all'ingresso» resta: la sosta è in §5.10.
- **§8 Salute**: Codici nuovi:
- `aperti_senza_conferma` (avviso, misura = quota di senza_conferma sugli aperti senza scadenza, soglia 60%);
- `ingresso_trattenuti` (avviso: trattenuti_senza_appiglio > 10, oppure rilasciati_a_tempo > 50% in 7 giorni);
- `indicepa_non_aggiornato` (avviso: l'ultimo import riuscito ha più di 40 giorni).

allarmi_verifica_stato li comprende.
- **§11 Sender e pipeline**: Nuovi passi:
- `verifica_stato` con fase='ingresso' prima della SEO, in ogni giro;
- il passo `domini` nel primo giro delle 06 di ogni mese (import IndicePA filtrato);
- il passo `gemelli` nel giro delle 06, con tetto GEMELLI_FUSIONI_PER_GIRO (10), solo se Michele approva la decisione 2.

Tutti con `_passo_se_esiste`, dentro il lock del giro.
- **§12 Variabili**: Variabili nuove:
- `INGRESSO_SOSTA_GIRI` (4, da 0 a 12);
- `VERIFICA_STATO_TETTO_INGRESSO` (30);
- `GEMELLI_FUSIONI_PER_GIRO` (10, 0 = spento);
- `INDICEPA_URL` (risorsa CKAN pubblica di enti.xlsx).

La modalità della fase ingresso segue VERIFICA_STATO_MODALITA.
- **§13 CLI**: Comandi nuovi:
- `domini --import --scarica-enti --solo-usati [--dry-run]`;
- `verifica-stato --dry-run --fase ingresso`;
- `report-verifica-stato --ramo aperto --motivo senza_conferma`.

test_cli_argv aggiornato.
- **§14 db.py**: COLONNE_LETTURA_STATO passa a 17 colonne.

Funzioni nuove:
- `select_enriched_da_leggere()`;
- `aggiorna_ingresso(bando_id, colonne_bando, colonne_controllo)`, che rifiuta le righe pubblicate;
- `select_domini_ufficiali()`, con _scorri e order id;
- `select_host_dei_link()`;
- `aggiorna_segnale_aggregatore(righe)`.
- **§15 Sito e API**: Il badge «Aperto · da verificare» vale anche per (aperto, senza_conferma). Sottotesto: «Non abbiamo una conferma recente dalla pagina ufficiale dell'ente: verifica prima di presentare domanda.»

Il sottotesto del termine futuro dipende da termine_indicato_fonte:
- calendario_ufficiale: «Il calendario ufficiale indica come termine il <data>»;
- pagina: «La pagina dell'ente indica…»;
- testo: «Il testo del bando indica…»;
- aggregatore: «Un portale aggregatore indica come termine il <data>, non verificato».

Il sottotesto di termine_passato segue la stessa provenienza. supabase-bandi.ts chiede anche termine_indicato_fonte.

Contatori, filtri, sitemap e JSON-LD restano INVARIATI. L'API v1 resta invariata: l'enum dei 5 motivi contiene già senza_conferma; si aggiorna solo la documentazione del significato.
- **§16 Documenti**: Contratto DB:
- §3 con la quinta colonna;
- §4 certezza v2 (senza_conferma anche sugli aperti);
- `dominio_ufficiale.origine='indicepa'`;
- fusioni automatiche con i criteri esatti, compreso 'riga_calendario'.

RIPRESA:
- §4.1 d risolta con l'import filtrato automatico;
- §4.1 g risolta secondo la decisione 2;
- §4.1 c resta aperta, perché la provenienza è stata scartata;
- la trappola «resolver e monitor non leggono la tabella» è chiusa per il resolver e per verifica-stato.

Il messaggio a BandoFit comprende la colonna nuova e il nuovo significato di senza_conferma.
- **§17 Ordine di rilascio**: Invariato nella forma: la 13 estesa, poi un solo deploy, poi 7 giorni d'ombra, poi `--verita` con 0 difformi, poi attivo.

In ombra: nessun senza_conferma pubblico, perché esaminato_attivo_at resta NULL; la sosta conta soltanto; il preprocess a 8k è attivo subito. Si confrontano per 7 giorni la quota con scadenza (oggi 87%) e la distribuzione degli stati: se derivano, si torna a 4000 con una costante.

Il primo import di IndicePA parte al primo giro delle 06 del mese, oppure con `domini --import --scarica-enti --solo-usati` sul server.

## Task nuovi o modificati
- **S1 (modifica di T1/regola condivisa)** [frontend] Regola stato_da_verificare v2 del ramo A nei tre linguaggi (dip: )
  - Files: tests/stato-bando/casi.json, tests/stato-bando/genera-sql.ts, tests/estrazioni/stato-bando.test.ts, src/lib/stato-bando.ts, scraper_bandi/app/stato_bando.py, scraper_bandi/tests/test_stato_bando.py
  - Sezione `certezza` versione 2:
- ramo A da A1 a A8 come in §3;
- due parametri nuovi nella firma (esaminato_attivo_at, segnale_aggregatore_at) e giorni_grazia_ramo_a = 7;
- almeno 80 casi con sha256 e conteggio_minimo.
I 77 casi storici e le transizioni restano identici byte per byte; generaBloccoCertezza() è aggiornata. Nessun motivo nuovo.
- **S2 (modifica di D3)** [db] Migrazione 13 estesa: 5 colonne di controllo, GRANT, firma, vista con 5 colonne in coda (dip: S1 (modifica di T1/regola condivisa))
  - Files: backend/sql/bando_v11_13_stato_da_verificare.sql, backend/sql/bando_v11_13_stato_da_verificare_rollback.sql, backend/sql/bando_v11_07_fase_d.sql, backend/sql/bando_v11_07_fase_d_rollback.sql, tests/estrazioni/colonne-anon.test.ts, tests/estrazioni/migrazione-13.test.ts, scraper_bandi/tests/test_stato_da_verificare_sql.py
  - §2.2 aggiornato:
- colonne esaminato_attivo_at, termine_indicato_fonte (con il CHECK di coppia), segnale_aggregatore(+_at) e trattenuto_dal;
- GRANT SELECT ad anon sulle colonne lette dalla vista;
- firma con 2 parametri in più;
- vista con termine_indicato_fonte come quinta colonna in coda;
- blocco CERTEZZA v2 generato;
- casi PG17 nuovi (ombra, segnale, SET ROLE anon).
La sequenza 01..06, 08..13, 07, rollback, 13 deve passare due volte. Nessuna funzione nuova per anon.
- **S3 (modifica di T3/estrattori)** [backend] Lettore generico solo segnale, termini a quattro fonti, secondo lotto di lettori per ente (dip: )
  - Files: scraper_bandi/app/etichette_stato.py, scraper_bandi/app/date_validation.py, scraper_bandi/tests/test_etichette_stato.py, scraper_bandi/tests/test_finestra_invio.py, scraper_bandi/tests/test_termini.py (nuovo), scraper_bandi/tests/fixtures/etichette_stato/
  - Questo task si occupa di:
- la chiave `generico` (solo 'chiuso' con solo_segnale, mai 'aperto', esclusioni di §5.4);
- termine_nella_pagina, termine_da_calendario e termine_da_etichetta_oe, con la precedenza di §6.2;
- lettori per ente del secondo lotto, scelti da un report sugli host dei 410 (almeno 5 bandi ed etichetta strutturata nelle pagine già scaricate), ognuno con fixture reali.
preprocessor.py e bando_preprocess_runner.py passano a S4.
- **S4 (nuovo, scorporato da T3)** [backend] Ingresso: selezione per sezioni, data OE citata, status 2, funzione pubblicabile (dip: S3 (modifica di T3/estrattori))
  - Files: scraper_bandi/app/preprocessor.py, scraper_bandi/app/bando_preprocess_runner.py, scraper_bandi/app/ingresso.py (nuovo, puro), scraper_bandi/tests/test_preprocess_base.py (nuovo), scraper_bandi/tests/test_ingresso.py (nuovo)
  - Contenuto:
- blocco del prompt = testa di 1 500 caratteri più seleziona_sezioni fino a 8 000 (test puro sulle 47 pagine LazioEuropa in cache: etichetta e frase di scadenza entrambe dentro il blocco);
- provenienza passata a validate_date_candidate;
- finestra e lettore per ente dopo il modello;
- data OE dal deadline_label solo con status '1', data ≥ oggi e citazione nel testo della scheda;
- status '2' → 'in apertura prossimamente'; on_arrival escluso;
- `ingresso.pubblicabile()` e `senza_appiglio()`.
Nessuna modifica ai prompt; data_scadenza_verificata non si tocca.
- **S5 (modifica di T4/verifica-stato)** [backend] verifica-stato esteso: fase ingresso, (ii-c), link normalizzati, generico, termini, esaminato_attivo_at (dip: S1 (modifica di T1/regola condivisa), S3 (modifica di T3/estrattori), S4 (nuovo, scorporato da T3))
  - Files: scraper_bandi/app/verifica_stato.py, scraper_bandi/app/eventi.py, scraper_bandi/app/settings.py, scraper_bandi/app/telemetria.py, scraper_bandi/.env.example, scraper_bandi/tests/test_verifica_stato.py, scraper_bandi/tests/test_eventi.py, scraper_bandi/tests/test_telemetria.py
  - Contenuto:
- §5.2: priorità 88 per il segnale e candidati della fase ingresso;
- §5.3: (ii-c), normalizza_link_bando, verificabile sulla tabella letta dal DB;
- §5.4: lettore generico;
- §5.7: esaminato_attivo_at solo in attivo, termine_indicato_fonte, scritture d'ingresso tramite db.aggiorna_ingresso;
- §5.9 e §5.10: contatori e VERITA_NOTA estesa;
- codici di salute aperti_senza_conferma, ingresso_trattenuti e indicepa_non_aggiornato;
- variabili INGRESSO_SOSTA_GIRI e VERIFICA_STATO_TETTO_INGRESSO.
Test:
- in ombra esaminato_attivo_at non si scrive;
- una pagina (iv) non produce mai eventi;
- il generico non conferma mai;
- rpu.gl viene rifiutato verso un host non verificante;
- una riga pubblicata non si scrive mai in fase ingresso.
- **S6 (nuovo)** [backend-b] Segnale dell'aggregatore dal listing OE (dip: S2 (modifica di D3), task B salute (proprietario di bando_runner.py))
  - Files: scraper_bandi/app/segnali.py, scraper_bandi/app/bando_runner.py, scraper_bandi/tests/test_segnali.py, scraper_bandi/tests/test_bando_runner_record.py
  - Nuova funzione pura `segnali.segnale_aggregatore(record_listing, riga, adesso, *, copertura_piena, giri_assenza=3)`:
- NULL visto vale DATA_SEMINA_VISTO = 2026-09-23;
- status '2' → in_uscita;
- scadenza_da_label < oggi → scadenza_passata.
bando_runner, al passo 6-bis, la scrive con db.aggiorna_segnale_aggregatore e la azzera alla ricomparsa pulita. spariti() e gli eventi del monitor restano INVARIATI.
bando_runner.py è anche del task B della salute (fonti_in_errore): S6 parte dopo di lui, con un passaggio di proprietà via CONTRATTO:.
- **S7 (modifica di T5/aggancio)** [backend-b] DB, sosta prima della SEO, passi nuovi nella pipeline, CLI (dip: S4 (nuovo, scorporato da T3), S5 (modifica di T4/verifica-stato), S8 (nuovo), S9 (nuovo))
  - Files: scraper_bandi/app/db.py, scraper_bandi/app/bando_seo_runner.py, scraper_bandi/app/__main__.py, backend/app/bandi_pipeline.py, scraper_bandi/tests/test_seo_gate.py, scraper_bandi/tests/test_cli_argv.py, scraper_bandi/tests/test_orchestrazione_pipeline.py, backend/tests/test_bandi_verifica_stato.py (nuovo)
  - Contenuto:
- in db.py: COLONNE_LETTURA_STATO a 17, select_enriched_da_leggere, aggiorna_ingresso (rifiuta le righe pubblicate), select_domini_ufficiali, select_host_dei_link, aggiorna_segnale_aggregatore;
- bando_seo_runner.run filtra con ingresso.pubblicabile e fonde i gemelli esatti prima della pubblicazione;
- bandi_pipeline: fase ingresso prima della SEO, passo domini mensile, passo gemelli (se la decisione 2 è sì);
- CLI di §13.
bandi_pipeline.py è condiviso con il task B del sender: si lavora dopo di lui.
- **S8 (nuovo)** [backend-b] Lista bianca letta dal DB e import mensile di IndicePA filtrato (dip: )
  - Files: scraper_bandi/app/dominio_ufficiale.py, scraper_bandi/app/fonte_ufficiale.py, scraper_bandi/tests/test_dominio_ufficiale.py, scraper_bandi/tests/test_fonte_ufficiale.py
  - Contenuto:
- `_tabella_corrente()` passa a costruisci() le righe di db.select_domini_ufficiali;
- ACCORCIATORI;
- importa_indicepa(righe, solo_host=...);
- run_domini_import(scarica_enti=True, solo_usati=True): GET di INDICEPA_URL, lettura con openpyxl già installato, upsert_domini con origine 'indicepa' e tipo 'ente'. Se il download fallisce, la tabella resta com'è e si registra l'esito per indicepa_non_aggiornato.
Nessun'altra modifica al resolver: niente provenienza, sonda né ricerca. Test con MockTransport e un xlsx di fixture.
- **S9 (nuovo, solo se la decisione 2 è sì)** [backend-b] Criterio esatto 'riga_calendario' per i doppioni senza URL (dip: )
  - Files: scraper_bandi/app/gemelli.py, scraper_bandi/tests/test_gemelli.py
  - Quarto criterio in criteri_esatti. Condizioni: stessa fonte_id, link_bando NULL su entrambe, descrizione del calendario normalizzata identica e non vuota (almeno 3 token), e stesso raw source_url oppure stessa data di chiusura del calendario.
Test positivi: 803614=803633, 803615=803634, 803623=803642, 1260432=1260443.
Test negativi: stessa fonte con date diverse; fonti diverse.
- **S10 (modifica di T6/sito)** [frontend] Badge e sottotesti per senza_conferma sugli aperti e per la provenienza del termine (dip: S1 (modifica di T1/regola condivisa), S2 (modifica di D3))
  - Files: src/lib/supabase-bandi.ts, src/lib/bandi/aspetto.ts, src/lib/bandi/testi-stato.ts, tests/estrazioni/testi-stato-bando.test.ts, src/lib/api-v1/documentazione.ts, docs/api-v1.md
  - Contenuto:
- §15 aggiornato: la vista chiede anche termine_indicato_fonte;
- badge «Aperto · da verificare» per (aperto, senza_conferma);
- sottotesti per provenienza del termine, sia futuro sia passato;
- contatori, filtri, sitemap e JSON-LD invariati; enum dell'API invariato, si aggiorna solo la documentazione del significato.
Il resto del task del sito resta com'era.
- **S11 (modifica di D4 e C4)** [db] Documenti: contratto DB, RIPRESA, AVANZAMENTO, messaggio a BandoFit (dip: S2 (modifica di D3), S5 (modifica di T4/verifica-stato), S7 (modifica di T5/aggancio))
  - Files: docs/contratto-db-bandi.md, docs/bandi-monitor/RIPRESA.md, docs/bandi-monitor/AVANZAMENTO.md
  - Contenuto:
- §3 e §4 v2 del contratto DB (senza_conferma sugli aperti; uno stato è certo solo con stato_da_verificare IS NULL);
- origine 'indicepa';
- fusioni automatiche con i criteri esatti;
- RIPRESA §4.1 d e g risolte, c aperta, trappola della tabella chiusa;
- testo neutro del messaggio a BandoFit.

## Decisioni per Michele
- Che cosa mostrare per un «aperto» senza scadenza che, dopo la verifica automatica, non ha nessuna prova (né una scadenza, né una conferma recente, né una smentita)? Saranno circa 220-260 bandi oggi e circa 5-10 al mese in futuro.
  - Raccomandazione: Il bollino «Aperto · da verificare» con il motivo senza_conferma, dal settimo giorno dopo la pubblicazione e solo dopo una lettura in attivo, con rilettura ogni 14 giorni. Il bando resta fra gli aperti, nei contatori e nei filtri, e nessuno lo chiude a tempo: A2 resta intatta. Sparisce da solo alla prima conferma o scadenza trovata.
  - Alternative: Lasciare A4 = NULL come nel piano: nessun avviso ai lettori, quindi la situazione di oggi; Togliere dal contatore e dal filtro «Aperti» i senza_conferma dopo 90 giorni: sconsigliato, è di fatto un limite di tempo senza prova e contraddice la tua decisione del 30/09
- Fusione automatica dei doppioni certi: le 13 coppie LazioEuropa pubblicate sia dalla fonte 235 sia dalla 237, i 3 bandi VdA letti due volte (PDF e CSV), i 2 Interreg, e da ora in poi ogni riga nuova gemella esatta di una già pubblicata?
  - Raccomandazione: Sì, solo con criteri esatti (stesso URL, oppure stessa riga di calendario della stessa fonte), al massimo 10 fusioni per giro. Il doppione già pubblicato passa in 301 verso il master: nessuna riga cancellata, id e slug congelati. La riga nuova gemella non viene mai pubblicata. Chiude RIPRESA §4.1 g, che aspettava il tuo ok.
  - Alternative: Fondere solo i nuovi prima della pubblicazione e lasciare i doppioni già pubblicati come sono; Nessuna fusione automatica: i doppioni restano e ricevono letture doppie
- Lista bianca degli enti: importare ogni mese in automatico IndicePA, ma solo per gli host che compaiono già nei nostri link?
  - Raccomandazione: Sì, filtrato e automatico (primo giro delle 06 del mese). Rende leggibili circa 39 degli 89 bandi OE oggi illeggibili (Credito Sportivo, Finpiemonte, Sviluppo Campania, LazioCrea, Ismea, Formez, …) senza pesare sulla vista e senza rifare la Verifica 7. Le fondazioni private (Cariplo, Compagnia di San Paolo, …) restano fuori: i loro bandi prendono «da verificare».
  - Alternative: Import completo (circa 23 000 enti): più copertura futura su comuni e GAL, ma va rifatta la Verifica 7 della 05; Aggiungere anche le fondazioni come enti ufficiali: un loro dominio varrebbe come prova per gli eventi di qualunque bando le citi, rischio non misurato; Nessun import: gli 89 restano illeggibili

## Rischi
- Cambio visibile in blocco. Dopo il passaggio ad attivo, circa 220-260 schede mostrano «Aperto · da verificare» nel giro di 2-3 settimane: il tempo della prima passata più i 7 giorni di grazia. È voluto e onesto, ma va annunciato a BandoFit, che dalla fase (c) legge la vista e lo vede subito. Il contatore degli aperti non cambia.
- Il lettore generico può dare falsi «smentito»: una pagina che nella barra laterale elenca altri bandi chiusi, oppure un'edizione vecchia. Il danno è limitato a un avviso, mai a una chiusura né a una conferma. Mitigazioni:
- regex limitate all'h1, ai badge e all'inizio del corpo;
- fixture negative;
- 7 giorni d'ombra con la verità nota.
- Edizioni sbagliate sulle pagine (iv): OE toglie l'anno dai titoli. Qui non producono eventi. Una conferma da (iv) richiede un lettore per ente, un titolo 'alto' e l'OE ancora nel listing. Resta un rischio residuo di «confermato» o «termine passato» presi dall'edizione sbagliata: sono solo avvisi, reversibili.
- La selezione a 8 000 caratteri cambia il testo che il modello legge, anche senza toccare i prompt. Dopo il deploy si controllano per 7 giorni la quota con scadenza (oggi 87%) e la distribuzione aperto/chiuso/in apertura; se derivano si torna a 4 000 con una costante. Il costo previsto è di circa 0,5-1 USD al mese in più.
- La data OE presa dal deadline_label, anche se citata nella scheda, resta un'informazione dell'aggregatore: il cron chiude a quella data con verificato=false, come già oggi per le 785 scadenze OE. Sui bandi già pubblicati vale solo come termine_indicato.
- status '2' → 'in apertura': se OE non aggiorna e la pagina ufficiale manca, la riga resta «In apertura · da verificare» (ramo I) invece di un «aperto» sbagliato. Il ramo I (b) e il cron la aprono appena c'è una prova.
- Fuori perimetro. Il commento dell'adapter OE (obiettivo_europa.py:14 e 87) mappa on_arrival a 'Preavviso'. Se su OE on_arrival significa «a sportello», come indicano i 125 aperti con scadenza, il tipo_link spinge il modello verso «in apertura» su bandi aperti. Va misurato in un intervento separato, non toccato qui.
- IndicePA comprende anche società partecipate e stazioni appaltanti: un loro host diventa 'ente' per resolver, monitor ed eventi. Il filtro sugli host già citati limita l'effetto; il passo scrive un report delle righe aggiunte.
- File condivisi con il percorso B (bando_runner.py, bandi_pipeline.py, db.py): S6 e S7 partono dopo i task B, con un passaggio di proprietà via CONTRATTO:.
- Stime basate su campioni piccoli (38 OE, pagine scaricate una volta sola il 30/09): la resa del lettore generico e del secondo lotto di lettori non è misurata sul codice finale. I numeri veri escono da report-verifica-stato e dal codice aperti_senza_conferma.

## Cosa resta manuale
Nulla di ricorrente. Una tantum, e già previsto dal piano del giro 2:
1. Applicare la migrazione 13, nella versione estesa, dopo la 12 nel SQL Editor.
2. Dopo 7 giorni d'ombra con `report-verifica-stato --verita` a 0 difformi, impostare VERIFICA_STATO_MODALITA=attivo con un restart. Da quel momento compaiono i «da verificare»; la fase ingresso e la sosta passano in attivo con la stessa variabile.
3. Inoltrare a BandoFit il messaggio preparato da S11.
4. Rispondere alle 3 decisioni. Se la decisione 2 è sì, il passo gemelli si accende da solo; con GEMELLI_FUSIONI_PER_GIRO=0 resta spento.

Facoltativo, e solo se lo vuoi: il documento del programma Interreg Alpine Space, che dopo la fusione resta un'unica scheda, non è un bando. Il contratto DB ammette il ritiro (410) solo su richiesta scritta del committente, quindi nessun passo automatico lo toglie. Senza il ritiro resta pubblicato con «da verificare».

Il primo import di IndicePA parte da solo al primo giro delle 06 del mese successivo al deploy. Per anticiparlo si può lanciare una volta `domini --import --scarica-enti --solo-usati` sul server.
