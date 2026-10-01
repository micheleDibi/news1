# Misure per il percorso A, giro 2

Misure di `db` (task #69), 30/09/2026 sera. Tutte in **sola lettura**:
- GET su PostgREST, a pagine da 1 000 righe con `order=id`;
- le chiavi stanno dentro script nello scratchpad che non le stampano;
- la anon key (`.env` di root) solo sulla vista `bando_pubblico`, per vedere quello che vede BandoFit;
- due funzioni in sola lettura, `bando_dominio_verificante` e `bando_host_aggregatore`, chiamate in GET
  (PostgREST apre una transazione read-only). Nessuna RPC di scrittura, nessuna scrittura.

Verificabilità e aggregatori si calcolano con le funzioni vere di `app/dominio_ufficiale.py`, caricate per percorso.
La tabella è quella di §19.8: `costruisci(righe del DB, fonti=fonte)` più il seed. Oggi coincide con quella di
`_tabella_corrente()`, perché le 109 righe del DB sono esattamente fonti più seed (M11).

---

## M1. Verificabilità degli host

**Prova**:
- Python: `verificabile` ed `e_aggregatore` sulla tabella di oggi e su quella di §19.8;
- DB: `GET rpc/bando_dominio_verificante?nome_host=…` e `GET rpc/bando_host_aggregatore?nome_host=…`, tutte 200.

**Tutti i 17 host sono verificanti** in Python con entrambe le tabelle **e** nel DB; nessuno è un aggregatore.
Codice e DB concordano su tutti.

| host (`dominio_di`) | riga che lo rende verificante |
|---|---|
| bandi.regione.piemonte.it | ente (fonte), più regione.piemonte.it ente e pattern `regione.*.it` |
| lazioeuropa.it (da www.) | ente (fonte) |
| bandi.regione.lombardia.it | solo il pattern `regione.*.it` (0,80) |
| calabriaeuropa.regione.calabria.it | ente (fonte) e pattern |
| formazionelavoro.regione.emilia-romagna.it | ente (fonte) e pattern |
| fesr.regione.emilia-romagna.it | ente (fonte) e pattern |
| regione.puglia.it | solo il pattern `regione.*.it` |
| pr2127.regione.puglia.it | ente (fonte) e pattern |
| jtf-taranto.regione.puglia.it | solo il pattern `regione.*.it` |
| regione.lazio.it | solo il pattern `regione.*.it` |
| sicilia-fse.it | ente (fonte) |
| interreg-euro-med.eu | ente (fonte) |
| pninclusione21-27.lavoro.gov.it | ente (fonte), lavoro.gov.it ente, pattern `*.gov.it` |
| mimit.gov.it | portale_pubblico (seed) e pattern `*.gov.it` |
| coesione.regione.abruzzo.it | ente (fonte) e pattern |
| capcoe.it | ente (fonte) |
| new.regione.vda.it | ente (fonte) e pattern |

Quattro host (bandi.regione.lombardia.it, regione.puglia.it, jtf-taranto.regione.puglia.it e regione.lazio.it)
reggono sul solo pattern a 0,80, cioè esattamente sulla soglia. Oggi basta; se qualcuno abbassasse la confidenza del
pattern, uscirebbero.

**Nessun file SQL di domini.** Il task lo chiedeva solo per host non verificanti che l'import completo non copre, e
non ce ne sono. `docs/bandi-monitor/correzioni-2026-10-domini-verificanti.sql` quindi **non esiste**.

## M2. «In apertura» pubblicati (anon key, vista)

**Prova**: `GET bando_pubblico?stato_effettivo=eq.in apertura prossimamente` con `count=exact` e la anon key.
Oggi (Roma) è il 2026-09-30.

| misura | numero |
|---|---|
| in apertura, totale | **167** |
| senza `data_apertura` | 163 |
| senza `data_apertura` né `data_scadenza` | **162** |
| `data_apertura` passata (< oggi) | **3** |
| `data_apertura` oggi o futura | 1 |
| con `data_scadenza` | 4 (nessuna passata) |

Per confronto, la vista come anon ha 2 188 righe, uguali ai pubblicati letti con la service key.

## M3. Aperti senza scadenza, per gruppo di fonte e tipo di pagina

**Popolazione**: `stato_effettivo='aperto'` e `data_scadenza` NULL nella vista, cioè **426** (tutti pubblicati,
nessuno fuso). `fonte_ufficiale_stato`: 275 in_verifica, 98 non_trovata, 53 trovata.

**Regole applicate** (§5.3 più §19.4), con precedenza i > ii > ii-c > iv > illeggibile:
- **(i)** `fonte_ufficiale_stato='trovata'` con URL;
- **(ii)** un URL di `link_bando` (diviso sugli spazi, tenuti solo gli http(s), accorciatori esclusi) verificante,
  non aggregatore, con host uguale all'host di `fonte.link` e fonte fuori da FONTI_OE;
- **(ii-c)** `bando_controllo.candidato_prioritario` con host uguale a quello della fonte, verificante, fuori da
  FONTI_OE. **G3v (titolo 'medio') non è misurato**: serve la pagina, quindi il numero è un tetto;
- **(iv)** `link_bando` verificante su un altro host, oppure una `bando_link` 'pagina_bando' verificante;
- **illeggibile**: niente di tutto questo.
- (iii) non è misurabile senza scaricare le pagine, quindi non compare.

| gruppo (host di `fonte.link`) | i | ii | ii-c | iv | illeggibile | totale |
|---|---|---|---|---|---|---|
| OE (449-451) | 42 | 0 | 0 | 154 | 89 | 285 |
| lazioeuropa.it | 2 | 63 | 4 | 4 | 0 | 73 |
| formazionelavoro.regione.emilia-romagna.it | 0 | 20 | 0 | 0 | 0 | 20 |
| bandi.regione.piemonte.it | 5 | 7 | 0 | 0 | 0 | 12 |
| jtf.gov.it | 0 | 0 | 1 | 5 | 0 | 6 |
| new.regione.vda.it | 0 | 0 | 6 | 0 | 0 | 6 |
| sicilia-fse.it | 1 | 4 | 0 | 0 | 0 | 5 |
| fesr.regione.emilia-romagna.it | 0 | 5 | 0 | 0 | 0 | 5 |
| interreg-euro-med.eu | 0 | 3 | 0 | 0 | 0 | 3 |
| pr2127.regione.puglia.it | 2 | 1 | 0 | 0 | 0 | 3 |
| pninclusione21-27.lavoro.gov.it | 0 | 3 | 0 | 0 | 0 | 3 |
| alpine-space.eu | 0 | 0 | 2 | 0 | 0 | 2 |
| regione.piemonte.it | 0 | 0 | 0 | 1 | 0 | 1 |
| regione.liguria.it | 1 | 0 | 0 | 0 | 0 | 1 |
| provincia.tn.it | 0 | 1 | 0 | 0 | 0 | 1 |
| **totale** | **53** | **107** | **13** | **164** | **89** | **426** |

Le (iv) si dividono in 154 da `bando_link` e 10 da `link_bando`.

**Rispetto allo studio.** Lo studio parla di «258 illeggibili»; con le regole di §19.4 gli illeggibili sono **89**,
tutti OE. I 154 OE con una `bando_link` verificante erano già citati nello studio («154 già con link verificabile»),
e qui passano in (iv). La somma di 89 illeggibili, 154 (iv) da `bando_link`, 13 (ii-c) e 2 (iv) con più URL
(5699, 5700) fa esattamente 258. È verosimilmente lo stesso insieme riclassificato con le regole nuove, ma non l'ho
verificato id per id: lo studio non riporta l'elenco.

## M4. Host del `link_bando` sui non 'trovata'

**Popolazione**: i 373 aperti senza scadenza con `fonte_ufficiale_stato` ≠ 'trovata'. Primo URL del campo, dopo
la divisione sugli spazi.

| gruppo | caso | righe | esempi |
|---|---|---|---|
| OE | host dell'aggregatore | **243** | 17597, 17635, 17682, 17709 |
| non OE | host = fonte di scraping | **107** | 2338, 2339, 2340, 2341 |
| non OE | host diverso, verificante | 8 | 2448, 2449, 2621, 2622 |
| non OE | senza `link_bando` | 12 | 2475, 2519, 2520, 2526 |
| non OE | più URL nel campo | 2 | 5699, 5700 |
| non OE | accorciatore | 1 | 5698 (rpu.gl) |

- Tutti i `link_bando` degli OE puntano all'aggregatore: per gli OE la pagina ufficiale arriva solo da (i) o da
  `bando_link` (iv).
- I 107 «host = fonte» sono esattamente i 107 (ii) di M3.
- 5699 e 5700 hanno due URL su regione.puglia.it, mentre la fonte è jtf.gov.it: con `normalizza_link_bando`
  diventano (iv), non (ii).

## M5. Colonne della vista viva

**Prova**:
- `GET bando_pubblico?select=*&limit=1&order=id` con la anon key: ordine delle chiavi del JSON;
- lo schema OpenAPI con la service key: ordine di `definitions.bando_pubblico.properties`;
- il SELECT di `CREATE VIEW public.bando_pubblico` nella 05 (righe 148-265), letto dal file.

**Le tre liste sono identiche, 44 colonne nello stesso ordine**: id, slug, titolo, titolo_breve, descrizione_breve,
contenuto, livello, ente_erogatore, area_geografica, tematica, data_pubblicazione, data_apertura, data_scadenza,
ora_apertura, ora_scadenza, data_pubblicazione_verificata, data_apertura_verificata, data_scadenza_verificata,
importo_totale_eur, importo_max_per_progetto_eur, stato_bando, stato_bando_verificato, stato_effettivo,
tipologia_bando_id, modalita_erogazione_id, programma_id, fonte_ufficiale_stato, fonte_ufficiale_tipo,
fonte_ufficiale_e_atto, fonte_ufficiale_url, fonte_ufficiale_host, fonte_ufficiale_verificata_at,
ultimo_controllo_at, link_candidatura, link_candidatura_source, allegati, titolo_raw, descrizione_raw,
stato_processing, link_bando, ricerca, pubblicato_at, created_at, ultimo_cambiamento_at.

La base della 13 è la 05: nessuna migrazione successiva ha cambiato la vista in produzione. La 07, che la
ricrea, non è applicata. `pg_get_viewdef` non è leggibile dal Mac: i predicati li controlla la guardia della 13.

## M8. Colonne attuali di `bando_controllo`

**Prova**: schema OpenAPI con la service key. Le colonne sono 20: bando_id, ultimo_controllo_at,
prossimo_controllo_at, priorita_controllo, volatilita, controlli_falliti, tentativi_resolver, tentativi_pipeline,
candidato_prioritario, impronta_contenuto, impronte_sezioni, testo_norm, impronta_raw, ultimo_visto_in_fonte_at,
rigenerazioni_fallite, richiede_js, etag, last_modified, created_at, updated_at.

**Nessuna collisione** con le 17 della 13: le 12 di §2.2 (stato_letto, stato_letto_su, stato_letto_at,
stato_letto_url, stato_letto_citazione, stato_letto_metodo, lettura_stato, lettura_stato_at, prossima_lettura_at,
letture_stato_nulle, previsto_entro, termine_indicato) e le 5 di §19.2 (esaminato_attivo_at, termine_indicato_fonte,
segnale_aggregatore, segnale_aggregatore_at, trattenuto_dal).

## M9. VERITA_NOTA estesa sugli stati di oggi

**Prova**: `GET bando?id=in.(…)` con la service key, più `stato_effettivo` dalla vista. «Nel ramo» vuol dire: per il
ramo A, `aperto` e `data_scadenza` NULL; per il ramo I, `in apertura prossimamente`. Il tipo di pagina segue le
regole di M3.

**Tutti i 49 id sono ancora pubblicati, non fusi e nel ramo atteso.** Nessuna voce della tabella va aggiornata.

| ramo | atteso | id | pagina oggi |
|---|---|---|---|
| A | chiusura | 2387, 2919 / 18344, 18444, 18400 | ii, i / i, i, i |
| A | smentito (Valutazione) | 18337, 18357 | i |
| A | confermato | 17903, 18454 | i |
| A | rettifica data_scadenza | 2339, 256211 | ii |
| A | non_decisiva | 18315, 18387, 18423 / 3042 / 110821 | i / ii / i |
| A | non_decisiva, forse_non_un_bando | 2448, 2449, 2621, 2622 | iv (link_bando) |
| I | uscito | 2971 | i |
| I | data_verificata scadenza passata | 106753, 270806 / 2375 | ii / i |
| I | aperto | 1072674, 1072686 | ii |
| I | chiuso | 17978 | i |
| I | dalla sorella | 577475 | ii |
| I | confermato | 1261858, 327381 | i |
| I | non decisivo | 10258 | ii |
| A+ | chiusura via ii-c | 2475, 2520 | ii-c (senza `link_bando`) |
| A+ | smentito generico (sospeso) | 5699, 5700 | iv (due URL, host diverso dalla fonte) |
| A+ | termine_indicato 2026-12-31 | 5698 | ii-c (più l'accorciatore rpu.gl) |
| A+ | termine calendario_ufficiale | 803614, 803615, 803623 | ii-c |
| A+ | termine_passato + assente_dal_listing | 562317 | iv (bando_link) |
| A+ | segnale in_uscita | 17773, 18178 | iv (bando_link) |
| A+ | assente_dal_listing | 17883, 18186, 18231 / 18312 | iv (bando_link) / illeggibile |
| A+ | smentito generico | 18276, 18262 | iv (bando_link) |
| A+ | NON confermato | 18407 | iv (bando_link) |

Punti da sapere:
- **I «4 'concluso' del Piemonte» del ramo I non hanno id nel contratto.** Gli «in apertura» con fonte
  bandi.regione.piemonte.it sono 11: 2892, 2893, 2894, 150487, 150488, 150489, 354487, 442286, 516500, 516501,
  661135. Per metterli in VERITA_NOTA serve la lista esatta: la sceglie chi ha letto le pagine.
- 110821 ha `data_apertura` 2026-06-29 e nessuna scadenza: è nel ramo A.
- 5698 è (ii-c) per il candidato prioritario. L'accorciatore del `link_bando` diventa leggibile solo se
  l'URL finale è verificante.

## M10. IndicePA, import completo

**Risorsa** (API CKAN pubblica, `package_show?id=enti`, metadati aggiornati il 2026-09-30 03:17):
- dataset `5baa3eb8-266e-455a-8de8-b1f434c279b2`, risorsa XLSX `d09adf99-dc10-4349-8c53-27b1e5aa97b6`;
- **URL stabile per `INDICEPA_URL`**:
  `https://indicepa.gov.it/ipa-dati/dataset/5baa3eb8-266e-455a-8de8-b1f434c279b2/resource/d09adf99-dc10-4349-8c53-27b1e5aa97b6/download/enti.xlsx`;
- se un giorno la risorsa cambiasse id:
  `https://indicepa.gov.it/ipa-dati/api/3/action/package_show?id=enti`, risorsa con `format='XLSX'`.
- Un download: HTTP 200, 4 275 629 byte, salvato solo nello scratchpad. Lettura con `openpyxl` (read_only) in 1,7 s.

**Colonne**: 34, fra cui `Codice_IPA`, `Denominazione_ente` e `Sito_istituzionale`. Gli alias di
`_CAMPI_INDICEPA` le trovano tutte e tre, perché `_campo` abbassa le maiuscole.

| misura | numero |
|---|---|
| righe del foglio | 23 750 |
| righe con `Sito_istituzionale` | 22 908 |
| **righe utili** (host valido per `dominio_di`) | **22 891** (soglia di sanità 15 000: passa) |
| host distinti | 22 441 |
| host con 3 o più `codice_ipa` diversi | **59**: fnofi.it, asl.bari.it, fnovi.it, fraktion.it, halleyweb.com, regione.sicilia.it, comune.poggibonsi.si.it, agrotecnici.it, cnsd.it, sanita.puglia.it, … |
| host su piattaforme condivise | **14**: altervista.org 5, jimdo.com 3, weebly.com 2, wordpress.com 2, sites.google.com 1, facebook.com 1 |
| host su aggregatore o blocklist | 1 (facebook.com, già contato fra le piattaforme) |
| host ammessi dopo le esclusioni | 22 368 |
| di cui già in `dominio_ufficiale` | 15 |
| **host da inserire** | **22 353** |

Righe della tabella in memoria dopo l'import: 22 462.

**Effetto sui nostri link** (host distinti di `bando_link`, `link_bando` e `fonte_ufficiale_url` dei 2 188 pubblicati):
- 450 host, di cui **234 verificanti oggi**;
- **285 verificanti dopo l'import**, cioè **51 in più**, tutti da `bando_link`;
- nessun nostro host cade sotto le esclusioni prudenti (3+ codici, piattaforme, blocklist).

**Effetto sui 426 di M3**: gli illeggibili scendono da **89 a 50**, e le (iv) salgono da 164 a 203. i, ii e ii-c
non cambiano. Lo studio stimava «circa 39 in più con IPA»: ne escono esattamente 39.

Da sapere per S8:
- regione.sicilia.it e sanita.puglia.it sono escluse dalla regola dei 3 codici. regione.sicilia.it resta verificante
  per il pattern `regione.*.it`; sanita.puglia.it no.
- halleyweb.com (hosting di molti comuni) è escluso correttamente dalla stessa regola.

## M11. Righe di `dominio_ufficiale`

**Prova**: `GET dominio_ufficiale?select=…&order=id`, tutte le righe (109).

| origine | tipo | righe |
|---|---|---|
| fonte | ente | 58 |
| seed | aggregatore | 25 |
| seed | portale_pubblico | 19 |
| seed | pattern | 7 |

- Tutte le righe sono attive.
- Nessuna riga verificante ha confidenza sotto 0,80.
- **Nessuna riga `indicepa`**: l'import non è mai stato fatto.
- Le 109 righe coincidono con quello che il codice ricava da solo (fonti più seed). Il passaggio di §19.8 («le righe
  del DB vincono») oggi non cambia niente; conterà dal primo import.
