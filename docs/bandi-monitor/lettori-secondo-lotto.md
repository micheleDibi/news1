# Lettori dello stato: secondo lotto e prova sulle pagine vere

Task #73 (G2A-B2), 01/10/2026. Contratto: `docs/contracts/bandi-giro-2.md` §6.1 con §19.5.
Codice: `scraper_bandi/app/etichette_stato.py`. Test: `scraper_bandi/tests/test_etichette_stato.py`,
fixture in `scraper_bandi/tests/fixtures/etichette_stato/` (con `indice.json`).

## Come si è scelto

1. **Misura in sola lettura** (GET su PostgREST, chiavi mai stampate). Candidati di verifica-stato:
   - 426 aperti senza scadenza;
   - 167 «in apertura», pubblicati e non fusi.
2. Per ognuno, la pagina che il passo leggerebbe secondo §5.3 e §19.4:
   - (i) fonte ufficiale 'trovata';
   - (ii) link_bando sullo stesso host della fonte, verificante, fuori da OE;
   - (ii-c) candidato_prioritario;
   - (iv) link_bando su un altro host, o una `bando_link` 'pagina_bando' verificante;
   - altrimenti «illeggibile».

   Poi il raggruppamento per host.
3. Pagine pubbliche scaricate **una volta**, con curl e 1 s di pausa: 2 o 3 per host, per un centinaio di file in tutto.
   Su ognuna si è cercata un'etichetta di stato strutturata, cioè un badge, un campo o una classe con Aperto,
   Chiuso, Scaduto, In corso, Attivo o Prossimo.
4. Criterio del contratto: almeno 5 bandi fra gli aperti senza scadenza **e** un'etichetta strutturata.

## Host con almeno 5 candidati

| host della pagina | aperti | in apertura | etichetta strutturata | lettore |
|---|---|---|---|---|
| lazioeuropa.it | 74 | 28 | `div.single-bandi-status` | `lazioeuropa` (§6.1) |
| bandi.regione.piemonte.it | 17 | 56 | `dl.stato-*` | `piemonte` (§6.1) |
| new.regione.vda.it | 6 | 39 | nessuna pagina: calendari PDF/CSV | nessuno (termine e periodo dal calendario, #71) |
| calabriaeuropa.regione.calabria.it | 22 | 2 | bottone `cem-btn-*` | `calabria` (§6.1) |
| formazionelavoro.regione.emilia-romagna.it | 20 | 0 | `div.bando_state` | `formazionelavoro_er` (§6.1) |
| regione.puglia.it | 20 | 0 | **no** | generico (5699, 5700 «sospeso») |
| mimit.gov.it | 18 | 2 | **no** (pagine di notizie) | generico |
| bandi.regione.lombardia.it | 12 | 0 | `span.chip-label` | `lombardia` (§6.1) |
| sicilia-fse.it | 7 | 4 | **no** | generico |
| pr2127.regione.puglia.it | 3 | 7 | campo «Stato: Prossimo avvio» | `puglia` (§6.1, vedi sotto) |
| **invitalia.it** | 8 | 0 | «Stato incentivo o strumento» + `p.active-panel` | **`invitalia` (secondo lotto)** |
| regione.lazio.it | 8 | 0 | **no** (documenti: forse non un bando) | generico |
| regione.lombardia.it | 7 | 0 | **no** | generico |
| **regione.fvg.it** | 6 | 0 | «[BANDO APERTO]» in `div.subtitle` | **`fvg` (secondo lotto)** |
| regione.liguria.it | 6 | 0 | **no** | generico |
| mise.gov.it | 6 | 0 | **no** | generico |
| pninclusione21-27.lavoro.gov.it | 4 | 2 | percorso /preavvisi/ + «Data presunta apertura» | `pninclusione` (§6.1) |
| **regione.toscana.it** | 5 | 0 | `span.rtds-chip--status` + `<time>` della scadenza | **`toscana` (secondo lotto)** |
| fesr.regione.emilia-romagna.it | 5 | 0 | `div.bando_state` (ignorata) | `fesr_er` (§6.1) |
| illeggibili (nessuna pagina) | 89 | 7 | — | — |

## Secondo lotto (approvato dal lead il 30/09)

- **`invitalia`**:
  - «Attivo» → aperto; «Chiuso» → chiuso, può chiudere;
  - «Data chiusura» (d/m/aaaa) → termine finale.
  - Esempi: 18281 attivo, 17868 chiuso con 23/6/2026.
- **`toscana`**:
  - `is-open` «Aperto» → aperto; `is-in-progress` «In corso» → non decisiva; chiuso → chiuso **solo segnale**
    (vedi «Etichette di chiusura mai viste»);
  - «Data di scadenza presentazione domande: 30.06.2026 13:00» → termine finale con l'ora.
  - Su 17989 e 18390 «In corso» ha la scadenza passata: vincono le date.
- **`fvg`**:
  - «[BANDO APERTO]» → aperto;
  - «[BANDO CHIUSO]» → chiuso **solo segnale** finché una pagina vera chiusa non entra fra le fixture (decisione del
    lead).
- **pr2127 non è un lettore nuovo**: è il `puglia` di §6.1. La pagina del calendario del PR Puglia ha «Stato:
  Prossimo avvio» e «Data presunta di apertura: II semestre 2025». È la forma «Prossimo avviso con data presunta» del
  contratto. «Prossimo avviso» su regione.puglia.it non compare in nessuna delle 20 pagine guardate.
  regione.puglia.it resta al generico, come chiede il positivo 5699.

## Esiti sulle pagine vere, contro la verità nota di §5.9

| id | lettore | esito | verità nota |
|---|---|---|---|
| 2387 | lazioeuropa | chiuso, può chiudere, senza termine letto | proposta 'chiusura' ✓ |
| 18344 | lombardia | chiuso, può chiudere, «Scade il 25/07/2025» | proposta 'chiusura' ✓ (vedi nota 1) |
| 18454, 17903 | piemonte, calabria | aperto | confermati ✓ |
| 2339 | formazionelavoro_er | aperto, termine 19/01/2027 12:00 | rettifica 2027-01-19 ✓ |
| 256211 | fesr_er | chiuso per date, termine 25/09/2026 16:00, «In corso» ignorato | rettifica 2026-09-25 ✓ |
| 18337, 18357 | calabria | Valutazione → chiuso solo segnale | smentito senza proposta ✓ |
| 18315, 18387, 18423 | calabria | Pubblicazione → non decisiva | non decisiva ✓ |
| 3042 | nessuno (sicilia-fse) | None | non decisiva senza modello ✓ |
| 110821 | puglia (pagina di notizia) | None | non decisiva senza modello ✓ |
| 2971 | piemonte | attuato → uscito | uscito ✓ |
| 106753, 2375, 270806 | lazioeuropa | chiuso con scadenza passata letta (24/07, 10/08, 31/07) | data_verificata della scadenza ✓ |
| 1072674 | lazioeuropa | aperto, termine 29/10/2026 17:00 | aperto ✓ |
| 17978 | calabria | chiuso, può chiudere | chiuso ✓ |
| 577475 | pninclusione | preavviso, data presunta passata → non decisiva; sorella /avvisi/leps-pippi | dalla sorella ✓ |
| 1261858, 327381 | calabria, pninclusione | in apertura | confermati ✓ (vedi nota 2) |
| 10253-10255 (come 10258) | puglia | Prossimo avvio, II semestre 2025 passato → non decisiva | 10258 non decisivo ✓ |

**Note per il lead:**

1. **«Le date vincono».**
   - Si applicano quando l'etichetta contraddice le date: «In corso» o «Aperto» con il termine passato, oppure un
     «chiuso» solo segnale. In quel caso il risultato è chiuso, senza `puo_chiudere` (strada rettifica).
   - Un «Chiuso» con `puo_chiudere` resta tale: è la chiusura di §5.6 (e), con la data letta come `p_data_evento`.
   - Con questa lettura tornano 2387 e 18344 (proposta 'chiusura') e anche 2375, 270806 e 106753.
   - Per questi ultimi tre il ramo I (a) sceglie la data_verificata: è una decisione del passo (#76), non del
     lettore.
2. **Calabria «Pre-informazione».** La tabella di §6.1 la dà non decisiva, la verità nota (1261858) la dà
   confermata. Il codice segue la verità nota: pre-informazione → in apertura. «Pubblicazione» resta non decisiva.
3. **I «4 concluso del Piemonte»** della verità nota: le pagine 2941-2943 oggi dicono «attuato», quindi uscito.
   L'etichetta «concluso» non compare in nessuna delle pagine Piemonte guardate. Da rimisurare nel #76.
4. **18231**, il positivo del generico secondo lo studio: al 01/10 la pagina ha solo il bottone «Valutazione», che il
   lettore `calabria` legge come chiuso solo segnale. Nessuna frase di chiusura per il generico, ma l'effetto è
   lo stesso: smentito dalla fonte.

## Il lettore generico

- **Dove gira:** solo sugli host senza lettore dedicato.
- **Dove legge:**
  - l'h1;
  - i badge (classi badge, label, chip, stato, status, tag, pill) di al massimo 80 caratteri;
  - i primi 2 000 caratteri del corpo.

  Toglie nav, header, footer, aside e i contenitori con classi di menu, colonne laterali, correlati e cookie. Le
  classi si confrontano per intero: una sottostringa toglierebbe `elementor-widget-container`, cioè tutta la
  pagina; `no-sidebar` sul body non conta.
- **Cosa riconosce:** frasi con bando, avviso, sportello o domanda/e a non più di 60 caratteri da
  chiuso/a/e/i, scaduto/…, sospeso/…, esaurito/…, oppure «non è più possibile presentare».
- **Plurali:** servono le forme plurali. La pagina vera di va.camcom dice «Domande chiuse», e la regex del contratto
  (`chius[oa]`) non la prendeva.
- **Cosa scarta:**
  - «fino ad/a esaurimento», «ad esaurimento», «in caso di esaurimento»;
  - «potrà/sarà/verrà essere sospeso/chiuso», «salvo chiusura», «chiusura anticipata»;
  - ogni frase con una data futura.
- **Positivi veri:**
  - so.camcom 18276 («Bando» + campo «Chiuso» in `div.stato_field`);
  - va.camcom 18262 («Domande chiuse», «CHIUSURA SPORTELLO», dotazione esaurita) e 17552;
  - regione.puglia 5699 e 5700 («Avviso pubblico sospeso temporaneamente»).
- **Negativi veri:**
  - mise 18564, «termini aperti (fino ad esaurimento delle risorse disponibili)»;
  - «Bando Aperto» (fesr 326536) e «Attivo» (invitalia 18281): il generico non dice mai aperto.
- **Colonna laterale con altri bandi chiusi:** nessuna pagina vera l'aveva. Il test inserisce una colonna `aside`
  nella pagina vera di 18564.

## Fixture

- 35 pagine, circa 1 MB in tutto, la più grande 74 KB.
- **Taglio:**
  - via script, stili, svg, iframe, immagini, form, nav e footer;
  - dell'head resta il solo titolo;
  - degli attributi restano class, id, href, datetime e role.

  Il test verifica che ogni lettore dia lo stesso esito sulla fixture e sulla pagina intera (0 differenze).
- **Dati personali** (rivisti dopo la revisione del #73):
  - email → `indirizzo@esempio.invalid`;
  - email offuscate da Cloudflare (`/cdn-cgi/l/email-protection#<hex>`, `data-cfemail`) → `email-protection#0`,
    attributo tolto;
  - telefoni, anche senza «tel», → `000 0000000`;
  - nomi dei responsabili → «X»: dopo «Dott./Dott.ssa» (anche minuscolo), dopo «Dirigente Generale» e nel blocco
    «Responsabile Unico del Procedimento» delle schede Calabria.

  Un test (`test_nessun_dato_personale_nelle_fixture`) scandisce tutte le fixture: nessuna email offuscata o
  nominativa, nessun `data-cfemail`, nessun «Dott.» seguito da un nome. Il mascheramento non cambia l'esito di nessun
  lettore.
- **Senza pagina vera** (Piemonte «concluso», Calabria «Conclusione» e «Sospeso», Toscana «Chiuso», FVG «[BANDO
  CHIUSO]»): il test cambia l'etichetta dentro una pagina vera e lo dichiara.

## Etichette di chiusura mai viste su una pagina vera

Decisione del lead dopo la revisione del #73: valgono **SOLO SEGNALE** (`puo_chiudere=False`) finché una fixture
vera non le mostra. Quando succede, si aggiunge la fixture e si passa a `puo_chiudere` con un test.

| lettore | etichetta | oggi | chiude davvero (visto su pagina vera) |
|---|---|---|---|
| `piemonte` | «concluso» | solo segnale | «Scaduto» (2890) |
| `calabria` | «Conclusione», «concluso» | solo segnale | «Chiuso» (17978) |
| `toscana` | «Chiuso», «scaduto», «concluso» (`is-closed`) | solo segnale | nessuna |
| `fvg` | «[BANDO CHIUSO]», «[BANDO SCADUTO]» | solo segnale | nessuna |
| `formazionelavoro_er` | «Bando Chiuso» | solo segnale (decisione del 30/09) | — |

Un termine finale certo e passato chiude comunque per date (la strada è la rettifica).
- `calabria_rc_pubblicata_18089.html` è la copia della fixture già nel repo (`tests/fixtures/impronte/`).

## Aggiunte al contratto da registrare

- **`leggi(html, url_finale, titolo, *, oggi=None)`:** il parametro `oggi` serve a «le date vincono». Senza, vale
  la data civile di Roma; i test lo passano.
- **`leggi_generico(...)`:** pubblica, per il passo e per i test.
- **Ordine dei lettori per host (`LETTORI_PER_HOST`):**
  - calabriaeuropa prova `calabria` poi `calabria_rc`;
  - www.regione.calabria.it (dove sta davvero #rc-status, 18089) prova `calabria_rc` poi `calabria`.
- **Due lettori ER:** leggono anche il blocco strutturato «<data> <ora> - Scadenza dei termini per partecipare al
  bando», perché su fesr 256211 la finestra «dalle ore 13.00 giorno 10 settembre…» non è un costrutto di
  `_COSTRUTTO_RE`.
