# Colonne tolte dalla migrazione 07: cosa resta a BandoFit

Misura del 30/09/2026 alle 13:26, fatta da `db` (giro «ripresa bandi, ottobre 2026»).
Serve a decidere quando applicare la 07.

**Come è stata fatta.** Solo letture GET su PostgREST, con la chiave anonima
(`PUBLIC_SUPABASE_BANDI_ANON_KEY`): è quello che vede BandoFit. Letture a pagine da 1 000 righe con
`order=id`. La service key è servita solo per capire *perché* manca qualcosa (sezione 4).

**Base.** La vista `bando_pubblico` mostra **2 180 bandi**. `bando_link` mostra **5 691 righe**:
3 629 `pagina_bando`, 2 061 `allegato`, 1 `candidatura`. Nessuna riga di tipo `atto` o `portale`.

**Cosa fa oggi BandoFit** (`frontend/src/pages/BandoDetail.tsx:118-120`, commit `6ce5cfd`):
- pulsante principale = `link_candidatura`, altrimenti `fonte_ufficiale_url`, altrimenti `link_bando`;
- link «fonte» = `fonte_ufficiale_url`, altrimenti `link_bando`;
- allegati = il jsonb `allegati`.

Dopo la 07 queste tre colonne non si leggono più. Il contratto (§5) indica i sostituti:
- pulsante: una riga `candidatura`, altrimenti `fonte_ufficiale_url`, altrimenti una riga `portale`;
- allegati: le righe `atto` e `allegato` di `bando_link`.

---

## In breve

| colonna tolta | sostituto | oggi | dopo la 07 | persi |
|---|---|---|---|---|
| `allegati` (jsonb) | righe `atto`/`allegato` di `bando_link` | 160 bandi con allegati (408 URL) | 285 bandi | **151 bandi restano senza nessun allegato** (374 URL) |
| `link_candidatura` | riga `candidatura` di `bando_link` | 146 bandi | **1 bando** | 145 senza riga `candidatura` |
| `link_bando` | `fonte_ufficiale_url` | 334 bandi | 131 di questi hanno la fonte | **203 senza fonte** |
| pulsante principale (le tre insieme) | candidatura → fonte → portale | 827 bandi | 616 bandi | **211 bandi senza pulsante**, di cui 183 aperti o in apertura |

In una frase: **se la 07 andasse in produzione oggi, 183 bandi aperti o in apertura perderebbero su
BandoFit il pulsante verso l'ente, e 151 bandi perderebbero tutti gli allegati.** Il motivo non è
un buco del contratto: le righe sostitutive esistono già a DB, ma nessuno le ha mai verificate e
anon non le può leggere (sezione 4). E il buco cresce: i bandi nuovi continuano ad avere
`link_candidatura` e nessuna riga `candidatura`. **Il 30/09 il lead ha deciso di rimandare la 07**
(sezione 5).

---

## 1. `allegati`

- Bandi con almeno un allegato nel jsonb: **160**, per **408 URL**.
- Di questi, **151 non hanno nessuna riga `atto` o `allegato`** leggibile in `bando_link`
  (111 non hanno proprio nessuna riga). Stato: 57 aperti, 62 in apertura, 32 chiusi.
- Dei 408 URL del jsonb, **nessuno** compare fra le righe `atto`/`allegato`. Due compaiono come
  `pagina_bando`, 406 non compaiono affatto (anche ignorando `http`/`https`).
- I 9 bandi che hanno sia il jsonb sia righe `allegato` hanno **documenti diversi** nei due posti.
  Esempio, il 2242 (Abruzzo, welfare aziendale): il jsonb contiene l'Avviso
  (`avviso-welfare-signed-7-53.pdf`) e la determina, `bando_link` contiene formulari e graduatorie.
  È lo stesso buco segnalato da BandoFit il 29/09 (RIPRESA §4.4, «seguire un salto»).
- Nel verso opposto, **276 bandi** oggi non hanno allegati nel jsonb e dopo la 07 ne avrebbero in
  `bando_link`. Quindi i bandi con almeno un allegato passano da 160 a 285, ma sono in gran parte
  bandi *diversi*.

Host degli URL che mancano (i primi): `portalebandi.regione.basilicata.it` 102,
`bandi.regione.piemonte.it` 100, `coesione.regione.abruzzo.it` 41, `lazioeuropa.it` 31,
`new.regione.vda.it` 27, `regione.piemonte.it` 22, `sicilia-fse.it` 15, `bandi.regione.marche.it` 12.

## 2. `link_candidatura`

- Bandi con `link_candidatura` non NULL: **146** (la vista toglie già quelli su un aggregatore).
- Con una riga `candidatura` leggibile: **1**. In tutto `bando_link` ne ha una sola.
- Per 20 bandi lo stesso URL c'è, ma come `pagina_bando`: con la regola del contratto non vale come
  candidatura.
- Dei 145 scoperti: 71 hanno la fonte ufficiale, quindi il pulsante resta ma porta alla pagina
  dell'ente invece che al modulo (51 cambiano davvero destinazione, negli altri 20 è lo stesso
  URL). **74 non hanno né la riga né la fonte**: restano senza pulsante.
- Stato dei 145: 75 aperti, 32 in apertura, 38 chiusi.
- Host principali: `bandi.regione.piemonte.it` 34, `servizi.regione.piemonte.it` 29,
  `lazioeuropa.it` 10, `rasportello.regione.abruzzo.it` 7.

## 3. `link_bando`

- Bandi con `link_bando` non NULL: **334**.
- 131 hanno anche `fonte_ufficiale_url`, **sempre uguale** a `link_bando` (nessun caso diverso).
- **203 non hanno la fonte** (201 `in_verifica`, 2 `non_trovata`): 134 aperti, 43 in apertura,
  26 chiusi. Nessuno di loro ha una riga `bando_link` leggibile, nemmeno `portale`.
- Host principali: `lazioeuropa.it` 86, `bandi.regione.piemonte.it` 33,
  `formazionelavoro.regione.emilia-romagna.it` 20, `pr2127.regione.puglia.it` 9.

## 4. Perché mancano: righe che esistono ma non si leggono

Riletto con la service key (solo GET), sugli stessi 2 180 bandi:

| cosa manca ad anon | la riga c'è in `bando_link`? |
|---|---|
| 408 URL del jsonb `allegati` | 405 sì ma **non pubblicabili**, 2 pubblicabili come `pagina_bando`, 1 assente |
| 146 `link_candidatura` | 122 sì ma **non pubblicabili**, 21 pubblicabili (20 come `pagina_bando`), 3 assenti |
| 203 `link_bando` senza fonte | 196 sì ma **non pubblicabili**, 7 assenti |

Tutte le righe non pubblicabili sono `origine='raw'`, e da quando esistono nessuno le ha verificate
(`esito_http` NULL, `trovato_in_fonte_at` NULL). Le crea la migrazione 02, copiando le vecchie
colonne (3 749 righe il 23/09), ma anche il resolver, che salva con `origine='raw'` i candidati presi
da `link_bando` e dal calendario (`app/fonte_ufficiale.py`; 27 righe il 24/09).

**Nessun comando di oggi le rende leggibili.** Il vincolo della 02 vuole, per una riga
pubblicabile, un 2xx *e* la prova che il link compare nella pagina ufficiale. `link-verifica`
controlla il 2xx, ma su una riga `raw` senza prova la lascia non pubblicabile e la conta in
`senza_prova` (`app/fonte_ufficiale.py`, `run_link_verifica`). L'unica eccezione è la riga che il
resolver ha scelto come fonte ufficiale: vale per le 131 del punto 3, non per le altre.

## 5. Cosa vuol dire per la 07

Oggi la 07 toglierebbe a BandoFit informazioni vere (pulsanti su bandi aperti, avvisi e
determine) per cui non c'è ancora un sostituto leggibile. Non è un difetto di BandoFit: anche
dopo la sua fase (c) vedrebbe gli stessi buchi.

**Il buco cresce a ogni giro.** Nessun codice crea righe `bando_link` di tipo `candidatura` (in
tutta la tabella ce n'è una leggibile), mentre la SEO continua a scrivere `link_candidatura` sui
bandi nuovi: 8 dei bandi pubblicati dal 24/09 ce l'hanno, fino al 1262520 del 30/09. Ogni bando
nuovo con un modulo di candidatura è un pulsante in più che la 07 toglierebbe.

**Ambito della 07 per BandoFit.** La 07 non revoca tutta la tabella `bando`: fa `REVOKE ALL` e
poi `GRANT SELECT` sulle sole colonne del contratto (07:152-190), con la policy su `pubblicato`.
Per BandoFit l'effetto è un 42501 sul predicato storico `stato_processing=eq.completed` finché
non passa alla fase (c).

**La strada, decisa il 30/09 dal lead** (`docs/contratto-db-bandi.md` §5.1):
1. **la 07 è rimandata**: news1 non la propone finché un bando aperto o in apertura perde il
   pulsante o gli allegati, e prima di proporla rifà questa misura e la manda a BandoFit;
2. **nella fase (c)** BandoFit legge prima `bando_link` e ripiega sulle colonne deprecate, con
   quest'ordine: pulsante = riga `candidatura` → `link_candidatura` → `fonte_ufficiale_url` →
   riga `portale` → `link_bando`; allegati = righe `atto`/`allegato` più il jsonb, senza doppioni
   per URL. Così nessuno degli 827 bandi con pulsante lo perde o cambia destinazione;
3. chiudere il buco è lavoro di news1 e richiede codice nuovo: righe `candidatura` per i bandi
   nuovi, verifica delle righe `raw` sulla pagina ufficiale, e per i 203 senza fonte prima la fonte
   (sono `in_verifica`, il limite del resolver di RIPRESA §4.1 c). Non ha ancora una data.

**Probabili doppioni aperti**, trovati dalla revisione perché hanno gli stessi allegati: tre coppie
Regione Abruzzo (fonte 217) / ObiettivoEuropa, con lo stesso titolo nella sostanza e la stessa
scadenza. Da fondere a parte, con il criterio esatto.

| Regione Abruzzo | ObiettivoEuropa | bando | scadenza |
|---|---|---|---|
| 2231 | 17807 | incentivi all'assunzione di disoccupati over 36 | 30/11/2026 |
| 2232 | 17806 | incentivi all'assunzione di giovani 18-35 anni | 30/11/2026 |
| 2242 | 18356 | welfare aziendale, 4 milioni | 18/12/2026 |

---

<details>
<summary>Elenco dei 211 bandi che perderebbero il pulsante principale</summary>

2276, 2301, 2302, 2303, 2304, 2305, 2307, 2308, 2338, 2339, 2340, 2341, 2342, 2343, 2344, 2345, 2346,
2347, 2348, 2349, 2350, 2351, 2352, 2353, 2363, 2364, 2365, 2366, 2367, 2368, 2376, 2377, 2378, 2379,
2380, 2381, 2382, 2384, 2385, 2387, 2403, 2439, 2448, 2449, 2520, 2560, 2576, 2612, 2621, 2622, 2769,
2771, 2772, 2890, 2892, 2893, 2894, 2904, 2918, 2923, 2927, 2935, 2937, 2938, 2958, 2975, 2994, 3035,
3041, 3042, 3043, 3044, 3048, 5591, 5592, 5593, 5652, 5662, 5692, 5697, 5698, 5699, 5700, 5916, 5917,
5918, 10253, 10254, 10255, 10256, 10257, 10258, 10259, 18133, 18153, 18258, 18447, 18559, 20935,
20936, 20940, 26315, 26324, 30086, 32904, 38472, 42235, 55444, 55459, 55460, 65901, 69638, 69674,
106753, 110420, 110435, 110823, 110824, 125724, 150483, 165444, 165458, 212848, 227506, 256211,
267030, 267031, 267032, 270806, 311893, 326536, 336490, 340172, 356638, 370085, 408923, 412536,
426738, 426739, 426774, 438460, 444382, 444383, 457014, 457049, 457050, 468537, 468549, 468550,
470872, 516500, 516540, 516546, 529944, 530270, 544366, 544422, 547013, 555987, 556317, 556361,
577475, 645163, 797464, 801429, 801432, 801433, 813305, 817315, 817829, 847727, 847740, 862096,
905315, 905743, 925398, 940320, 940690, 952233, 952608, 952612, 956582, 967934, 1009878, 1009892,
1029949, 1029963, 1039488, 1043486, 1055905, 1058461, 1070918, 1072674, 1072676, 1072686, 1072689,
1120620, 1135127, 1162880, 1239631, 1257967, 1257980, 1258672, 1260443, 1262080, 1262081, 1262343,
1262516, 1262517, 1262518, 1262520

</details>

<details>
<summary>Elenco dei 151 bandi che perderebbero tutti gli allegati</summary>

2230, 2276, 2301, 2302, 2303, 2304, 2305, 2307, 2308, 2363, 2365, 2367, 2368, 2376, 2475, 2519, 2520,
2526, 2527, 2528, 2529, 2548, 2551, 2554, 2556, 2769, 2772, 2886, 2890, 2892, 2893, 2894, 2895, 2899,
2902, 2904, 2912, 2918, 2919, 2923, 2924, 2934, 2935, 2937, 3042, 3043, 3048, 3120, 5532, 5534, 5544,
5549, 5550, 5584, 5587, 5596, 5597, 5598, 5599, 5662, 5692, 5694, 5695, 5698, 5704, 5916, 5917, 17962,
18560, 20935, 20936, 30535, 30537, 32904, 40744, 40745, 40746, 40747, 42235, 42683, 55903, 55904,
125724, 150482, 150483, 258890, 308084, 311893, 327038, 327381, 340673, 352147, 352151, 354487,
356638, 368237, 370085, 412981, 412982, 412983, 438460, 442283, 442285, 444382, 444383, 457427,
516497, 516540, 516541, 530270, 556317, 556320, 556361, 577475, 801429, 803607, 803608, 803609,
803610, 803611, 803612, 803613, 803614, 803615, 803616, 803617, 803618, 803619, 803620, 803621,
803622, 803623, 803626, 803640, 803641, 817830, 905743, 921802, 925837, 940690, 952608, 952610,
952612, 956582, 967934, 1009768, 1043486, 1058461, 1070918, 1239631, 1260432

</details>
