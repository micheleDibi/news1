# Testi da rigenerare, ottobre 2026

Scritto il 30/09/2026 da `db` (giro «ripresa bandi, ottobre 2026», task T-D4). Misure con la service key, solo letture
GET; pagine ufficiali lette il 30/09. **Non è stato lanciato niente**: qui ci sono gli elenchi per i due comandi e il
motivo di ogni voce.

- `seo-rigenera` (nuovo, T-C1): riscrive il testo con il prompt corretto. Serve per le **forme di partecipazione e i
  beneficiari inventati**.
- `rigenera` (lotto L7, esiste già): sostituisce nella prosa la data vecchia con quella nuova. Serve per le **date
  vecchie**. Sceglie da solo i bandi: prende quelli con un evento di data **verificato e applicato**.

Il SQL che accompagna questo file è `correzioni-2026-10-01-testi.sql`: due blocchi, T3 (che contiene anche la
correzione T1) e T2, provati su Postgres 17 effimero.

---

## In breve

| cosa | quanti | cosa fare |
|---|---|---|
| gli 11 casi già segnalati | 9 pubblicati + 2 fusi | `seo-rigenera` su 6; il 18278 si chiude (T3); 1262402 dopo aver trovato la fonte; i 2 fusi non si vedono più su news1 |
| altre schede con formule di partecipazione | 166 (103 da ObiettivoEuropa) | prima il controllo gratuito, poi la prova a secco sulle 59 aperte di ObiettivoEuropa |
| campione verificato sulla fonte (uno per sito) | 15 decisi: 10 giusti, 5 no | i 5 sbagliati sono tutti di ObiettivoEuropa |
| «imprese sociali / società benefit» senza la voce nei beneficiari | 14 | `seo-rigenera` su 13 (il 661135 chiude stanotte ed è un doppione) |
| 18278: beneficiari sbagliati, ed è l'edizione 2025, esaurita il 21/10/2025 | 1 riga + stato | SQL, blocco T3 (con dentro T1: prima i beneficiari, poi la chiusura); niente `seo-rigenera` |
| 1262402 e 1262407 | avvisi 2026 veri | restano pubblicati; testo da rigenerare **dopo** aver agganciato la fonte ufficiale |
| prosa con date vecchie | 17 schede + le 31 corrette domani | `rigenera`; 112862 dopo il blocco T2; 17598 con `seo-rigenera` |
| pubblicati «aperto» senza data di scadenza | 425 su 1 249 aperti (286 di ObiettivoEuropa) | misura per il piano dei prossimi giorni (sezione 8) |

---

## 1. Gli 11 casi già segnalati

Segnalati da BandoFit il 29/09 (18145, 18278, 171905) e dal controllo dei 20 bandi del 29/09 (gli altri otto). Tutti
vengono da ObiettivoEuropa (fonte 449).

| bando | stato | cosa dice il testo | azione |
|---|---|---|---|
| 18145 | aperto | «imprese in forma singola o associata» (assente dall'atto, dice BandoFit) | `seo-rigenera` |
| 18278 | aperto (a DB) | «imprese sociali e società benefit», «reti di imprese e aggregazioni» | SQL, blocco T3 (con T1): è l'edizione 2025, fondi esauriti il giorno dell'apertura; si chiude e **non** si rigenera |
| 171905 | aperto | «in forma singola o associata» (il decreto vuole almeno due partner con capofila) | `seo-rigenera` |
| 1262398 | aperto | beneficiari non sostenuti (controllo del 29/09) | `seo-rigenera` |
| 1262399 | aperto | «Comuni lombardi, singoli o associati» (controllo del 29/09) | `seo-rigenera` |
| 1262402 | aperto | «enti no profit ed enti del Terzo settore» fra i beneficiari: l'avviso dice solo enti, associazioni e fondazioni **a partecipazione pubblica** (sezione 5) | `seo-rigenera` dopo aver agganciato la fonte (sezione 7) |
| 1262408 | aperto | requisiti non sostenuti (controllo del 29/09); l'importo è già stato corretto con B3 | `seo-rigenera` |
| 1262411 | aperto | requisiti non sostenuti (controllo del 29/09) | `seo-rigenera` |
| 1262412 | aperto | requisiti non sostenuti (controllo del 29/09) | `seo-rigenera` |
| 1262345 | **fuso** nel 1262082 (F2) | — | niente su news1 (risponde 301). Il testo del master 1262082 cita le ATS, che l'avviso del Piemonte prevede |
| 1262406 | **fuso** nel 1261867 (F4) | — | niente su news1. Il testo del master 1261867 non ha formule di partecipazione |

I due fusi restano visibili su BandoFit fino alla sua fase (c). `seo-rigenera` rifiuta gli id non pubblicati, quindi il
loro testo non si può riscrivere con il comando.

## 2. Le altre schede con le stesse formule

**Come.** Ho cercato nel testo (`contenuto`) di tutti i 2 180 pubblicati le forme di partecipazione che il prompt nuovo
non deve più affermare da solo: «in forma singola o associata», «singoli o associati», «reti di imprese», «contratti di
rete», «aggregazioni di imprese/soggetti», «ATI», «RTI», «raggruppamenti temporanei». Le «ATS» contano solo quando non
sono gli Ambiti Territoriali Sociali. «Aggregazione» nel senso di «luogo di aggregazione» non conta.

**Risultato: 166 schede.**

| | aperte o in apertura | chiuse |
|---|---|---|
| da ObiettivoEuropa | 59 | 44 |
| da altre fonti | 48 | 15 |

Per formula: «in forma singola o associata» 74, «singoli o associati» 58, aggregazioni 33, ATI/ATS/RTI 31, reti di
imprese 23 (una scheda può averne più d'una). Trenta hanno solo «singoli o associati», che negli avvisi pubblici è una
formula comune e spesso vera.

**La junction dei beneficiari non aiuta qui**: il catalogo non ha voci per le forme di partecipazione, quindi queste
frasi vengono dalla fonte o dal modello, mai dai cataloghi.

### Il campione verificato sulla fonte (uno per sito)

Una scheda per sito (la più recente), 24 siti provati. 15 si sono potuti decidere; gli altri 9 avevano la pagina
sparita (404, 5 casi), i dettagli solo nei PDF (2), un link alla home dell'ente (1) o un certificato non valido (1).

| bando | fonte | il nostro testo | la pagina dell'ente | verdetto |
|---|---|---|---|---|
| 18091 | OE | «Enti territoriali ed enti locali della provincia di Bari, anche in forma associata» | «Pro Loco, Associazioni riconosciute e non riconosciute, Fondazioni, Organismi senza scopo di lucro»: niente enti locali, niente forme associate | **sbagliato** |
| 156520 | OE | «micro e piccole imprese, consorzi e reti di imprese» | solo «Micro e piccole imprese attive» | **sbagliato** |
| 18182 | OE | «Organismi di formazione accreditati, anche in forma associata» | «unicamente in forma associata»: la forma associata è obbligatoria, non facoltativa | **sbagliato** |
| 736941 | OE | aggregazioni fra i beneficiari | solo MPMI della circoscrizione di Foggia | **sbagliato** |
| 156491 | OE | «imprese agricole singole o associate» | la pagina non ne parla (il PDF del bando non l'ho letto) | **non sostenuto** |
| 18202 | OE | reti di imprese | «loro Consorzi e Cooperative … alle reti costituite» | giusto |
| 749531 | OE | forma singola o associata | «Ambiti Territoriali … in forma singola o associata» | giusto |
| 18441 | OE | forma associata | «in forma singola o in forma aggregata» | giusto |
| 562294 | OE | forma associata | «Enti Locali, in forma singola o associata» | giusto |
| 425831 | OE | partenariati | «partenariati pubblico e/o privati … capofila» | giusto |
| 514869 | OE | forma associata | enti locali «anche in collaborazione con» università e altri | giusto |
| 17838 | OE | reti di imprese | «Reti di micro, piccole, medie imprese» | giusto |
| 342856 | OE | singoli o associati | «apicoltori professionisti singoli o associati» | giusto |
| 1257980 | Lazio Innova | consorzi e reti | «in forma singola o associata in Consorzi, Società Consortili o Reti di imprese» | giusto |
| 140357 | Regione Abruzzo | ATI/ATS | «anche in forma associata in ATI e ATS» | giusto |

**Lettura.** Nel campione i testi sbagliati sono 5 su 13 fra quelli di ObiettivoEuropa e 0 su 2 fra gli altri. Il
campione è piccolo: dice dove guardare, non quante sono. Insieme agli 11 casi noti (tutti di ObiettivoEuropa) indica
che il difetto nasce soprattutto dalle schede ObiettivoEuropa, non dal prompt in generale.

### Proposta di ordine

1. `seo-rigenera --solo-controllo` su tutti i pubblicati: è gratuito e non scrive niente (T-C1, a cura di
   `backend-b`). Il suo elenco va confrontato con i 166 di qui sotto.
2. Prova a secco (`--dry-run --ids …`) sulle **59 aperte di ObiettivoEuropa**: sono quelle che un lettore può ancora
   usare per candidarsi. La prova spende una chiamata a Opus per scheda: il costo esatto lo stampa il comando.
3. Poi le 48 aperte delle altre fonti, dopo aver guardato il risultato delle prime.
4. Le chiuse per ultime, o mai.

## 3. «Imprese sociali» e «società benefit»

- **277 schede** le nominano e hanno la voce «Imprese sociali/Società benefit» nei beneficiari. Tutte vengono da
  ObiettivoEuropa, e in tutte la voce è nella tassonomia della scheda ObiettivoEuropa (`raw_data.beneficiaries`). Il
  prompt nuovo lascia dire ciò che sta nei cataloghi collegati, quindi `seo-rigenera` **non** le cambierà. Il 18278
  mostra però che la tassonomia di ObiettivoEuropa può essere sbagliata. Non le ho verificate: decidere se fidarsi di
  quella voce è una scelta, non un conto.
- **14 schede** le nominano **senza** avere la voce nei beneficiari: 2556, 17571, 17703, 17821, 17830, 17961, 17962,
  18019, 18054, 517163, 547026, 661135, 1071265, 1261857 (12 di ObiettivoEuropa; 3 aperte, 2 in apertura, 9 chiuse).
  Qui il testo non ha appoggio né nel catalogo né, per quanto si sa, nella fonte: `seo-rigenera`. Il 661135 resta
  fuori: chiude stanotte (scadenza 30/09) ed è un doppione del 736932.

## 4. Il 18278: beneficiari sbagliati, e il bando è chiuso da un anno

L'art. 2 del bando della Camera di commercio della Basilicata dice «progetti presentati da singole imprese». Nel PDF
del bando «sociali», «benefit», «reti di imprese» e «aggregazioni» non compaiono mai. La voce «Imprese
sociali/Società benefit» viene dalla scheda di ObiettivoEuropa.

Non solo: è l'**edizione 2025**. La pagina dell'ente dice domande «a partire dalle ore 9:00 del 21 ottobre 2025» e poi
«Si comunica che il Bando Voucher Digitali ha esaurito il suo plafond alle 9:28 del 21/10/2025». A DB è ancora
«aperto», senza scadenza. Il monitor sorveglia questa pagina, ma la chiusura c'era già alla sua prima lettura: niente
cambia, niente da classificare (lo stesso limite di `ombra-2026-10.md` §3).

- **Blocco T3**, due scritture nell'ordine:
  1. **T1**: toglie la sola riga 19785 da `bando_beneficiari`. Il bando e il catalogo non si toccano;
  2. chiude il bando con un evento `chiusura` del worker (aperto → chiuso è nella lista bianca), prova e citazione
     dalla pagina dell'ente, data dell'evento 21/10/2025. La data di scadenza resta vuota.
- **Niente `seo-rigenera`**: riscrivere la prosa di un bando chiuso è una spesa inutile.
- **Perché in quest'ordine**: la DELETE non fa avanzare `ultimo_cambiamento_at` (la tabella di collegamento non
  ha il trigger), la chiusura sì. Con la DELETE prima, quando chi legge il DB (BandoFit) vede il cambiamento e
  rilegge la scheda, anche i beneficiari sono già giusti. Nell'ordine opposto potrebbe rileggerla fra le due
  scritture e perdere la correzione dei beneficiari.

## 5. Verdetto su 1262402 e 1262407

Il controllo del 29/09 non aveva trovato gli avvisi del 2026. **Esistono tutti e due**: le schede sono giuste e restano
pubblicate. Hanno però un testo da rigenerare.

- **1262402** (Regione Siciliana, spettacolo). È l'avviso allegato al D.A. n. 3021/S8 del 16/09/2026: 4 961 500 euro
  (come a DB), istanze «entro e non oltre le ore 13,00 del 20 ottobre 2026». A DB manca l'ora. Beneficiari: enti,
  associazioni e fondazioni a partecipazione pubblica. Il nostro testo aggiunge «enti no profit ed enti del Terzo
  settore» (dalla voce della junction): da rigenerare. Fonte ufficiale da agganciare:
  `https://www.regione.sicilia.it/system/files/2026-09/Avviso%20allegato%20al%20DA3021-S8%20del%2016.09.2026_0.pdf`.
- **1262407** (Provincia di Trento, biogas). È il «Bando 2026» approvato con la delibera della Giunta provinciale
  n. 1412 dell'11/09/2026, domande dal 16/09 al 15/10/2026. La pagina ammette solo «Imprese agricole associate per la
  gestione comune dei reflui zootecnici, costituite esclusivamente sotto forma di società cooperativa o consorzio».
  Il nostro testo parla di «imprese … del comparto agricolo» e di «realtà agricole singole o associate»: da rigenerare.
  Anche la junction (solo «Imprese») andrebbe allineata, per esempio con «Società cooperative»: **non** è nel SQL,
  perché il consorzio non ha una voce di catalogo precisa. Da decidere.

## 6. Prosa con date vecchie

`rigenera` prende solo i bandi con un evento di data **verificato e applicato**. Stato di oggi:

| bando | data nel testo | data a DB | evento che `rigenera` vede | chi lo sistema |
|---|---|---|---|---|
| 759891, 759892, 759894, 759895, 759896, 759897, 759898, 759900, 759902, 759907, 759909 (Toscana FSE+, 11 schede) | 30 settembre 2026 | 12/10 | sì (11564-11574) | `rigenera` |
| 215460 (Sicilia, idrogeno) | 24 settembre 2026 | 08/11 | sì (11576) | `rigenera` |
| 455779 (Valle d'Aosta) | 15 settembre 2026 | 30/10 | sì (11577) | `rigenera` |
| 1262082 (Piemonte, abbandono sociale) | 14 ottobre 2026 | 19/10 | sì (11579) | `rigenera` |
| 17792 (Sardegna, SRD13) | 30 settembre 2026 | 15/10 | sì (11562) | `rigenera` |
| 112862 (FVG, associazioni d'arma) | 30 settembre 2026 (due frasi e la descrizione breve) | 15/10 | **no**: l'evento 11295 non è verificato | blocco T2, poi `rigenera` |
| 17598 (CCIAA Bologna, neolaureati) | «scadenza non ancora comunicata» (anche nella descrizione breve) | 16/10 | sì (11575), ma non c'è una data vecchia da sostituire | `seo-rigenera` |
| 1262080 (Lazio, polizia locale) | 28 settembre e 29 ottobre 2026 | 28/09-29/10 | — | a posto, niente da fare |

**Dopo `correzioni-2026-10-01.sql`** (T-D3) si aggiungono i 31 bandi di quel file: 13 con la scadenza spostata dal
30/09 e 18 «in apertura» diventati aperti o chiusi. Avranno tutti un evento verificato e applicato, quindi `rigenera`
li vedrà da solo. Per i 16 aperti la prosa che dice «in apertura» o «apre il …» potrebbe non avere una data da
sostituire: il comando li conta in `senza_riscrittore`, e quelli vanno a `seo-rigenera`.

## 7. Elenchi pronti

Rispetto alla prima versione di questo file: tolti il 18278 (si chiude con T3), il 661135 (chiude stanotte, doppione)
e i due della sezione 5 (servono prima la fonte ufficiale); i bandi chiusi sono passati fra i facoltativi.

**Per `seo-rigenera`, priorità: aperti o in apertura** (dopo il deploy di T-C1, prima `--dry-run`), 14 schede:

- dagli 11 noti: 18145, 171905, 1262398, 1262399, 1262408, 1262411, 1262412;
- dal campione: 18091, 736941;
- con «imprese sociali/società benefit» senza la voce: 2556, 17962, 1071265, 1261857;
- per la data: 17598.

**Facoltativi: chiusi o in chiusura**, 12 schede. Un lettore non può più candidarsi, quindi il danno è minore e la
spesa rende poco: 156520 (scade il 30/09, chiude stanotte), 18182, 156491, 17571, 17703, 17821, 17830, 17961, 18019,
18054, 517163, 547026.

**Da rigenerare dopo aver agganciato la fonte ufficiale**: 1262402 e 1262407 (sezione 5). Oggi sono `in_verifica`:
senza fonte, `seo-rigenera` rileggerebbe il testo di ObiettivoEuropa e rifarebbe lo stesso errore.

**Per `rigenera`**: nessun elenco da passare, sceglie da sé. Prima `--dry-run`: deve comparire almeno ciascuno dei
bandi della sezione 6 (dopo T2 e dopo T-D3).

## 8. Pubblicati «aperto» senza data di scadenza

Misura del 30/09 (GET con la service key), chiesta dopo il caso del 18278: **425 dei 1 249 bandi pubblicati «aperto»
non hanno una data di scadenza** (34%).

| creati a | da ObiettivoEuropa | da altre fonti | totale |
|---|---|---|---|
| giugno 2026 (il primo import) | 263 | 61 | 324 |
| luglio | 8 | 33 | 41 |
| agosto | 10 | 20 | 30 |
| settembre | 5 | 25 | 30 |
| **totale** | **286** | **139** | **425** |

- Fonte ufficiale: 53 trovata, 274 in verifica, 98 non trovata.
- 236 hanno «sportello» o «esaurimento» nella descrizione breve: molti sono sportelli veri, aperti fino a esaurimento
  dei fondi. Ma il 18278 mostra che uno sportello esaurito resta «aperto» per sempre, perché senza scadenza il cron non
  lo chiude mai.
- 23 hanno «2025» nel titolo o nella descrizione breve: sono i primi da guardare.

Cinque esempi (non verificati, tranne il primo e il secondo):

| bando | fonte | titolo | nota |
|---|---|---|---|
| 18278 | OE | Voucher digitali I4.0, CCIAA Basilicata | edizione 2025, esaurita il 21/10/2025: blocco T3 |
| 2612 | Regione Lazio | Acchiappa Talenti Lazio: incentivi alle imprese per assumere giovani | doppione del 18305, che per l'ente scade il 22/12/2026 (T-D3, A12) |
| 2520 | Regione Lazio | Avviso ITS Academy Lazio: percorsi formativi 2025/2026 | anno formativo già iniziato |
| 2338 | Regione Emilia-Romagna | Percorsi duali in Emilia-Romagna per qualifica IeFP con apprendistato | «2025» nel testo |
| 925837 | Regione Piemonte | Risarcimenti predazioni da grandi carnivori, bando 1/2026 | fonte trovata: forse un aiuto sempre aperto |


<details>
<summary>Le 166 schede con formule di partecipazione, divise per gruppo</summary>

**ObiettivoEuropa, aperte o in apertura (59):** 17509, 17540, 17550, 17586, 17631, 17646, 17753, 17838, 17905, 17909,
17911, 17912, 17913, 18043, 18091, 18145, 18177, 18202, 18207, 18278, 18294, 18348, 18355, 18360, 18362, 18387, 18418,
18441, 18446, 18458, 18460, 18466, 18488, 18493, 18559, 112860, 112866, 156520, 171905, 215464, 255060, 342850, 342856,
366543, 514869, 562294, 736941, 749531, 749541, 759895, 759898, 907910, 954799, 1059145, 1260470, 1262111, 1262112,
1262399, 1262407

**ObiettivoEuropa, chiuse (44):** 17528, 17530, 17547, 17585, 17629, 17663, 17704, 17714, 17716, 17782, 17799, 17800,
17825, 17876, 17902, 17927, 17941, 18054, 18065, 18068, 18128, 18182, 18185, 18198, 18201, 18233, 18275, 44945, 57988,
146925, 156479, 156491, 215465, 245044, 258883, 342857, 415158, 425831, 425835, 473336, 528664, 562302, 562324, 850347

**Altre fonti, aperte o in apertura (48):** 2242, 2308, 2341, 2367, 2519, 2919, 2940, 2942, 2945, 2958, 2962, 2963,
2968, 2976, 3008, 3014, 10253, 10259, 26324, 30537, 32904, 55459, 55908, 110420, 110435, 110824, 140357, 212848,
311893, 336490, 468549, 470872, 512534, 516540, 801433, 905315, 925398, 952608, 952612, 1055914, 1162829, 1162880,
1257967, 1257980, 1260432, 1261831, 1262082, 1262520

**Altre fonti, chiuse (15):** 2301, 2302, 2885, 2904, 2907, 2935, 2936, 2937, 55903, 150306, 150482, 327038, 412981,
412982, 442285

</details>
