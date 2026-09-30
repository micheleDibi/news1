# Bandi — punto di ripresa e verifiche

Questo file serve a riprendere il lavoro sui bandi dopo una pausa di giorni o di settimane, senza
rileggere il piano né ricostruire il contesto. È aggiornato al **30 settembre 2026**, alla fine del
giro «ripresa bandi, ottobre 2026»:
- il 27/09: conferma di R0-a e migrazione 11 scritta;
- il 28/09 mattina: 11 e 06 applicate, `MONITOR_STATI_ESTESI=true`, sender riavviato (§4.3,
  passi 2-6);
- il 29/09: rilascio 2 del pacchetto «eventi affidabili» (§4.2);
- il 30/09: il committente ha eseguito le correzioni del 28-29/09 e riavviato il sender alle 12:33
  (giro di avvio finito bene). **Sul server gira il rilascio 2**: lo conferma il monitor delle 18
  (56 righe con `__link__`). Il giro di ottobre ha preparato codice, misure e file SQL, **ma il suo
  deploy non è ancora fatto** (§1, «Giro di ottobre»).

Il controllo sul DB (query di §3.2 e numeri qui sotto) è del 30/09 alle 13:29, più il monitor delle
18 misurato alle 18:30, in `misure-2026-09-30.md`. Il sito pubblico non è stato riletto dopo il
26/09.

Per la cronaca di come ci siamo arrivati: `AVANZAMENTO.md`, nella stessa cartella. Per il contratto
verso BandoFit: `docs/contratto-db-bandi.md`. Il piano completo dell'intervento sta in
`~/.claude/plans/pasted-content-id-dcf2-sei-un-wondrous-seal.md`.

---

## 1. Dove siamo

L'intervento è **in esercizio**. Il resolver e i ricontrolli scrivono in produzione; il monitor
registra ma non applica e non rende visibile niente, di nessun tipo (modalità ombra). Il 25/09 gli
eventi `faq` e `nuovo_allegato` già raccolti sono stati resi visibili una volta, a mano, con
`applica-eventi` (vedi sotto). **Dal deploy di ottobre** cinque tipi si applicano da soli
(`MONITOR_TIPI_ATTIVI`, qui sotto).

| | 30/09/2026, 13:29 | 26/09 | 25/09 |
|---|---|---|---|
| bandi pubblicati | 2 180 | 2 162 | 2 147 |
| — aperti / chiusi / in apertura | 1 249 / 747 / 184 | — | — |
| **fonti ufficiali trovate** (pubblicati) | **616** — 696 in tutto, con 79 `processed` mai pubblicati e 1 fuso | 614 (693) | 609 |
| fonti in verifica (pubblicati) | 1 044 | 1 031 | 1 027 |
| fonti non trovate (pubblicati) | 520 | 517 | 511 |
| fonti trovate con link non leggibile | 0 su 696 | 0 su 693 | — |
| **CTA verso un aggregatore** | **0** (query 1; schede non rilette) | 0 (anche 30 schede lette) | 0 su 2 147 |
| proposte del monitor dal 24/09 | 75: 23 ammesse, 5 visibili (senza le 17 correzioni a mano del 30/09) | 24 (6, 5) | 17 |
| «aperto» senza data di scadenza | 425 su 1 249 (286 di ObiettivoEuropa) | — | — |
| «in apertura» con la data passata (query 12) | 21 (18 li corregge il file dell'01/10) | 19 | — |
| righe di `dominio_ufficiale` | 109: 58 enti, 19 portali, 7 pattern, 25 aggregatori | 109 | 109 |

**Il monitor delle 18 del 30/09**, primo giro col rilascio 2: 62 pagine controllate, 53 invariate, 7
classificazioni (sopra le 2-4 attese, perché al primo giro i link salvati non c'erano ancora: il numero
giusto si legge dai prossimi), 9 proposte e 2 ammesse, 0,09 USD. Nello stesso giro 7 bandi nuovi
pubblicati, tutti da ObiettivoEuropa. Uno risulta «aperto» ma apre l'01/10 alle 12 (1262673).

### Giro «ripresa bandi, ottobre 2026»: codice pronto, deploy da fare

Il 30/09 un giro di lavoro ha preparato tutto sul branch `claude/bandi-ripresa-ottobre`. **Il
deploy è a carico del committente.** Contratto interno: `docs/contracts/bandi-ripresa-ottobre.md`.

Cosa porta il codice (dettagli in §4.2):
- pagine «cieche» del Piemonte e della Valle d'Aosta di nuovo leggibili, con un riallineamento
  delle impronte che non classifica e non spende;
- `MONITOR_TIPI_ATTIVI`: i tipi scelti si applicano e diventano visibili nel giro stesso;
- host morti: un tetto di 120 secondi per bando e gli host senza DNS saltati per il giro;
- SEO: prompt senza forme di partecipazione inventate, comando `seo-rigenera`, titoli oltre 80
  caratteri gestiti (il 772894 fermo da settimane), bandi di ObiettivoEuropa già pubblicati da una
  fonte ufficiale rifiutati prima della SEO;
- all'avvio il sender rilascia i lock orfani dei propri processi precedenti.

**Stato al 30/09/2026 sera: passi 1-4 FATTI da Michele.** Backup di oggi presente; SQL delle date
(versione chat: 13 + 18 eventi, verifica `31 | 31 | {}`) e SQL dei testi (18278 chiuso con i beneficiari giusti,
112862 verificato) eseguiti; deploy fatto alle 18:47 (giro di avvio finito alle 18:52, `salute` stampa i cinque tipi
attivi; nuovo allarme «INDEXNOW_API_KEY assente con MONITOR_TIPI_ATTIVI valorizzata», vedi §4.1 h); frontend
ricostruito e riavviato (`/bandi` risponde 200). Restano i passi 5-9.

**I passi, in ordine** (le verifiche con un clic o un comando sono in
`verifiche-michele-2026-10.md`):
1. controllare backup e PITR del progetto bandi (voci 1-2 del foglio);
2. fuori dall'ora e mezza prima dei giri delle 00, 06, 12 e 18, lanciare
   `correzioni-2026-10-01-chat.sql` (o il file lungo
   `correzioni-2026-10-01.sql`: sono intercambiabili), un blocco alla volta: 13 scadenze del 30/09
   spostate e 18 «in apertura» sistemati. Funziona anche dopo le 00:05 dell'01/10, quando il cron
   avrà chiuso i primi 13;
3. lanciare `correzioni-2026-10-01-testi.sql`: beneficiari e chiusura del 18278, proroga
   verificata del 112862;
4. **deploy, entro il 07/10**, in una finestra sicura (12:30-16:30 o 19:00-22:30):
   - pull del codice sul server;
   - in `scraper_bandi/.env` la riga
     `MONITOR_TIPI_ATTIVI=faq,nuovo_allegato,graduatoria,esito,proroga`;
   - **un solo** `systemctl restart edunews-bandi-sender`, poi l'attesa di «Pipeline iniziale
     completata» (voce 13 del foglio);
   - `salute` deve stampare «tipi attivi del monitor: faq, nuovo_allegato, graduatoria, esito,
     proroga» (un valore sconosciuto dà `[ALLARME]`);
5. dopo il primo monitor (06 o 18): nella riga del giro `riallineate` sopra zero, e
   `bando_controllo.impronte_sezioni` con `__versione__` = 2;
6. per una settimana, ogni mattina, la query di sorveglianza delle proroghe (§6);
7. `rigenera --dry-run`, poi `--attivo` (§6), nella finestra sicura e mai durante un giro: è un
   lotto e non prende lock. Sistema la prosa con le date vecchie (elenco in
   `rigenerazione-2026-10.md` §6);
8. `seo-rigenera`: prima `--solo-controllo`, poi la prova a secco sui 14 aperti di
   `rigenerazione-2026-10.md` §7, lettura, e solo allora `--attivo --proposte` (§6);
9. il 07/10, il DNS della Basilicata (voce 14 del foglio).

Il numero «653 schede con un pulsante verso l'ente» del 25/09 non si confronta più: dal
ridisegno (vedi sotto) i bandi chiusi non mostrano nessun pulsante.

**Frontend.** Dal 25/09 sera in produzione c'è il ridisegno di lista, pagine filtro, hub e
scheda (commit `4c48e1a..5203602`); la lettura passa dalla vista `bando_pubblico` (F2 acceso,
API v1.1). Per i bandi chiusi, sospesi e revocati la scheda non mostra la CTA ma un messaggio.
Le verifiche visive le ha fatte il committente.

### Migrazioni applicate

`01, 02, seed, 03, 04, 05, 08, 09, 10`, più **11 e 06 applicate il 28/09/2026**, in quest'ordine.
**Mai applicata: la 07.**

- La **06** (cinque stati del bando, cioè `sospeso` e `revocato`) aspettava il rilascio difensivo
  R0-a di BandoFit, confermato per iscritto dal committente il 27/09/2026 (commit `a9d520a` di
  BandoFit). Dal 28/09 la colonna ammette i cinque valori. Oggi però nessun bando è sospeso o
  revocato, e nessun evento di quei tipi è stato applicato (§4.3 passo 7).
- La **07** aspetta la fase (c) di BandoFit. **R0-b è in produzione dal 30/09/2026** (`main`
  6ce5cfd di BandoFit): ricerca su `ricerca`, miss risolti su `bando_slug_storico` e
  `bando_fusione`, colonne `fonte_ufficiale_*`. BandoFit legge ancora `bando` con il predicato
  storico, quindi fino alla (c) un doppione fuso resta visibile nelle sue liste.
  **Aggiornamento del 30/09 sera: la fase (c), passo c1, di BandoFit è in produzione** (commit 878acb0 e
  f5e232d di BandoFit, conferma scritta).
  - BandoFit ora legge solo `bando_pubblico`, `bando_link`, `bando_slug_storico` e `bando_fusione`, mai la tabella
    `bando`; tiene i ripieghi deprecati di §5.1 del contratto e rimappa i fusi ogni ora.
  - La 07 è **rimandata**: si propone solo dopo il c2 di BandoFit (niente ripieghi), che parte dopo una nuova misura
    di §5.1 annunciata con almeno 7 giorni di preavviso.
  - Prima di un lotto di fusioni (L4) o di una separazione, e prima della prima applicazione attiva di sospensioni o
    revoche, **avvisare BandoFit** (va in modalità `prova`).
  - Le verifiche di §11 in versione (c) del 30/09 passano tutte; le 13 risposte a BandoFit sono nel contratto
    (§3, §5, §5.1, §6.2, §8, §10.1, §11, §12).
- La **11** (`bando_v11_11_traduzione_stato_proposto.sql`) fa tradurre a `bando_applica_evento`
  lo `stato_proposto` degli eventi raccolti in ombra. Senza, la RPC della 04 li marca applicati
  senza cambiare lo stato. Il marcatore `bando_capacita_eventi()` risponde, dal 28/09,
  `{"stati_cinque": true, "traduce_stato_proposto": true}`.
- La **07** (fase d: REVOKE di colonna, RLS stretta) richiede che BandoFit sia passato al contratto.
  **Il 30/09 è stata rimandata** anche oltre la (c), finché il suo effetto su BandoFit non è nullo
  (§4.5, `misure-colonne-07.md`).

### Configurazione in produzione (`scraper_bandi/.env`)

```
RESOLVER_MODALITA=attivo      ← messo il 25/09: prima valeva `ombra` per difetto
                                 e ogni giro risolveva bandi nuovi e buttava il risultato
MONITOR_STATI_ESTESI=true     ← messo il 28/09, dopo la 06: le sospensioni e le revoche
                                 nuove nascono con `stato_bando` (in ombra, invisibili)
```

**Da aggiungere al deploy di ottobre** (non ancora in produzione al 30/09):

```
MONITOR_TIPI_ATTIVI=faq,nuovo_allegato,graduatoria,esito,proroga
```

`proroga` c'è per decisione del committente del 30/09, dopo il controllo di `ombra-2026-10.md`
(nessuna proroga ammessa sbagliata).

`applica-eventi` stampa `stati_estesi` nel riepilogo: `True` solo se questo flag è letto **e**
il DB ha il CHECK a cinque stati. Il 28/09 la prima prova a secco ha dato `False` per una riga
scritta male nel `.env`: è il controllo più rapido che il flag sia davvero letto.

`MONITOR_MODALITA` **non è impostata**, quindi vale `ombra`: il monitor registra le proposte e non
tocca stato né date. È voluto. `MONITOR_GIRI` e `MONITOR_SCENARIO` non sono impostate e i default
(`06:00,18:00`, `bilanciato`) sono quelli giusti.

**L'attivazione di `faq` e `nuovo_allegato` del 25/09 è valsa una volta sola.** Un'attivazione per
tipo non esiste nel codice: in ombra ogni evento nuovo nasce `leggibile=false`, qualunque sia il
tipo, e la pipeline non rilancia `applica-eventi`. Il 26/09 nessun evento ammesso di quei due tipi
era rimasto nascosto (l'unico nuovo, del 26/09, non ha passato i gate), ma il prossimo ammesso
resterà invisibile finché qualcuno non rilancia `applica-eventi --tipo faq,nuovo_allegato
--attivo`. Vedi §4.1 a. **Dal deploy di ottobre** l'attivazione per tipo esiste
(`MONITOR_TIPI_ATTIVI`) e vale per gli eventi nati da quel momento: l'arretrato resta fermo, e per
decisione del lead non si pubblica (`ombra-2026-10.md` §5).

**`RESOLVER_MODALITA=attivo` vale anche per i comandi lanciati a mano.** Senza `--dry-run` o
`--ombra` scritti per esteso, `risolvi-fonte`, `oe-dettaglio`, `link-verifica`, `fondi-doppioni` e
`domini --import` scrivono sul DB (vedi §6). E `--ombra` non vuol dire «senza effetti»: non tocca
le colonne pubbliche, ma scrive le tabelle di servizio.

---

## 2. Come funziona a regime

Il sender (`edunews-bandi-sender.service`) gira **quattro volte al giorno** — 00:00, 06:00, 12:00,
18:00 — ed esegue:

```
1. discover        2. scrape-bandi     3. preprocess      4. enrich
5. resolver              (fonte ufficiale dei bandi nuovi)
5-bis. ricontrolli       (60 arretrati per giro, solo alle 06:00 e 18:00)
6. seo
7. monitor               (solo alle 06:00 e 18:00)
```

Più il **cron orario** a DB (`5 * * * *`) che chiude i bandi scaduti e apre quelli in apertura con
data verificata.

Costo misurato del monitor a regime: **97 pagine su 100 risultano invariate**, 2 classificazioni,
**3 centesimi per cento bandi**. Con 609 fonti due volte al giorno siamo intorno ai dieci centesimi
al giorno.

---

## 3. Verifiche

### 3.1 Verifica rapida (cinque minuti, quando vuoi sapere se tutto gira)

```bash
cd ~/projects/news1/scraper_bandi
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app salute --json
```

**Fino al 26/09 `salute` guardava solo tre valori di configurazione** (`MONITOR_MODALITA`, chiave
IndexNow, `MONITOR_GIRI`): gli allarmi elencati qui sotto non potevano scattare e un exit 0 non
provava niente. Dal commit `53c1897` legge il DB (solo letture) e si può lanciare anche dal Mac.
Exit 1 con `[ALLARME]` se:

- nessun monitor **di regime** riuscito da 24 ore;
- tetto raggiunto in due giri consecutivi (col motivo);
- consumo del mese, senza i lotti, oltre l'80% del tetto;
- più del 30% di `in_verifica` sui pubblicati degli ultimi 7 giorni (solo se sono almeno 10);
- `controlli_falliti ≥ 5` su più del 2% dei bandi vivi;
- un lock valido tenuto da oltre due terzi del suo TTL (monitor 120', resolver 80', pipeline
  160'); oltre un terzo del TTL, con un massimo di 60' (monitor e pipeline 60', resolver 40'), è
  un avviso;
- il DB non risponde;
- nell'ultimo monitor di regime che ha provato a classificare, le classificazioni fallite sono
  almeno quante le riuscite (dal 28/09): credito Anthropic esaurito o API giù. Qualche errore
  isolato fra tante riuscite è solo un avviso. Sulle righe precedenti la correzione vale la firma
  «classificazioni > 0 con `usd = 0`». Lo stesso giro scrive anche un `[ALLARME]` nel journal.

Login OE, residuo Firecrawl e schede OE **non si misurano dal DB**: `salute` lo dice negli avvisi
(«non misurato da salute: …»), e si controllano come sotto.

**Esito atteso oggi: exit 1**, con un solo allarme: «fonti in verifica sui nuovi 45% (> 30%)» (era
34% il 26/09). È un allarme vero secondo la soglia del piano, e resterà finché non si decide il
§4.1 c (il terzo segnale del resolver). Dal deploy di ottobre `salute` stampa anche la riga
«salute: tipi attivi del monitor: …»: deve elencare i cinque tipi; un valore sconosciuto dà
`[ALLARME]` ed exit 1.

```bash
systemctl is-active edunews-bandi-sender
journalctl -u edunews-bandi-sender --since today \
  | grep -E "STEP (resolver|ricontrolli|monitor)|FAILED|NON PARTITO|\[ALLARME\]"
```

**Cosa deve comparire**: `attivo: True` sul resolver; una riga `STEP ricontrolli`; il monitor solo
alle 06:00 e 18:00 (negli altri giri `SALTATO (giro non previsto)`, che è corretto); nessun
`FAILED`, `NON PARTITO` o `[ALLARME]` scritto dagli step. Il login OE si controlla a parte:
`journalctl -u edunews-bandi-sender --since today | grep -E "sessione non autenticata|SessioneOEError"`
deve essere vuoto.

Le stesse cose si leggono anche da `pipeline_run` (§3.7), da qualunque macchina abbia la service
key: un giro per ogni orario, `esito`, `interrotto_per_tetto`, `contatori`.

**Ricontrolli.** A ogni giro «esaminati 0, saltate ~1 550» è corretto finché nessuna data è dovuta.
L'ondata arriva l'**08/10/2026**: 1 252 righe di `bando_controllo` con il prossimo controllo quel
giorno (pubblicati e no; per i pubblicati `in_verifica` è il primo dei tre tentativi a 14 giorni),
al ritmo di 60 per giro solo alle 06 e alle 18 (120 al giorno): una decina di giorni. In quei giorni guardare
`interrotto_per_tetto` sulle righe `resolver` e il consumo (§3.7).

### 3.2 Verifica dell'integrità del contratto (dopo ogni intervento sui bandi)

Sono le promesse fatte a chi legge il database, e vanno controllate **sui dati**, non sui contatori.

Tutte tranne la 9 si possono fare anche dal Mac via PostgREST con la service key (solo GET), come
il 26/09; la 9 legge `pg_proc` e vuole il SQL Editor.

```sql
-- nel SQL Editor di Supabase. Tutte in sola lettura.

-- 1. Nessuna fonte ufficiale su un aggregatore. Atteso: 0
--    La funzione del DB copre tutti gli aggregatori della whitelist, i social e
--    quelli aggiunti dopo, senza il falso positivo di '%bandi.it%' (che prende
--    anche infobandi.it). Il 26/09 la versione con i pattern dava 0.
select count(*) from bando
 where fonte_ufficiale_host is not null and public.bando_host_aggregatore(fonte_ufficiale_host);

-- 2. Nessun evento con la prova su un aggregatore. Atteso: 0
select count(*) from bando_evento
 where dominio_prova is not null and public.bando_host_aggregatore(dominio_prova);

-- 3. Ogni fonte trovata ha un link leggibile. Atteso: 0 righe
select b.id, b.slug from bando b
  left join bando_link l on l.id = b.fonte_ufficiale_link_id
 where b.fonte_ufficiale_stato = 'trovata'
   and (l.id is null or not l.pubblicabile or l.trovato_in_fonte_at is null);

-- 4. Nessun evento applicato e invisibile (attivazione a metà). Atteso: 0
select count(*) from bando_evento
 where applicato and not leggibile and verificato
   and tipo in ('proroga','rettifica','apertura','chiusura','sospensione','revoca',
                'riapertura','faq','graduatoria','esito','nuovo_allegato');

-- 5. Nessun evento leggibile senza cursore su un bando che deve averlo
--    (pubblicato, fuso o ritirato: la condizione del trigger a_evento_cursore, 02).
--    Atteso: 0. Sugli altri bandi non pubblicati il cursore manca per costruzione:
--    l'evento resta «in attesa» e lo promuove la pubblicazione. Senza il join la
--    query dava 79 il 26/09: tutti `fonte_ufficiale_verificata` del 24/09 su
--    bandi `processed`, non un difetto.
select count(*) from bando_evento e join bando b on b.id = e.bando_id
 where e.leggibile and e.cursore is null
   and (b.pubblicato or b.bando_master_id is not null or b.ritirato_at is not null);

-- 6. Un pubblicato non è mai uscito da `completed`. Atteso: 0
select count(*) from bando where pubblicato and (stato_processing <> 'completed' or slug is null);

-- 7. Conteggio di riferimento per BandoFit: il primo ≥ il secondo,
--    la differenza sono i doppioni fusi.
select count(*) filter (where stato_processing='completed' and slug is not null) as predicato_storico,
       count(*) filter (where pubblicato) as flag_nuovo from bando;

-- 8. Nessuno stato fuori vocabolario (cinque valori dalla 06, applicata il 28/09).
--    Atteso: 0.
select count(*) from bando
 where stato_bando is not null
   and stato_bando not in ('aperto','chiuso','in apertura prossimamente','sospeso','revocato');

-- 9. Anon esegue solo le tre funzioni della vista (più quelle di pg_trgm).
--    Atteso: esattamente 3 righe, bando_stato_effettivo, dominio_di,
--    bando_host_aggregatore (Verifica 6 della migrazione 05). Nessuna RPC di
--    scrittura (bando_fondi, bando_separa, bando_registra_evento,
--    bando_applica_evento, lock_*) deve comparire.
select p.oid::regprocedure as funzione
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname='public'
   and has_function_privilege('anon', p.oid, 'EXECUTE')
   and p.proname not like '%trgm%' and p.proname not like 'gtrgm%'
   and p.proname not like 'similarity%' and p.proname not like 'word_similarity%'
   and p.proname not like 'strict_word_similarity%' and p.proname not like 'set_limit%'
   and p.proname not like 'show_limit%' and p.proname not like 'show_trgm%'
 order by 1;

-- 10. Nessun lock orfano: un proprietario che non esiste più tiene fermo tutto.
--     Dal 26/09 lo segnala anche `salute` (soglie in proporzione al TTL, §3.1).
select nome, proprietario, acquisito_at, scade_at, scade_at > now() as ancora_valido
  from pipeline_lock;

-- 11. Il cron orario chiude i bandi scaduti. Atteso: 0 (fuori dalla prima ora
--     dopo la mezzanotte di Roma). Il cron non chiude mai sospesi e revocati
--     (04:1209-1210): senza l'ultima riga, dopo la 06 la query conterebbe come
--     guasto ogni sospeso o revocato già scaduto.
select count(*) from bando
 where pubblicato and stato_bando <> 'chiuso'
   and data_scadenza < (now() at time zone 'Europe/Rome')::date
   and stato_bando not in ('sospeso','revocato');

-- 12. «In apertura» con una data di apertura NON verificata già raggiunta. Non è
--     un difetto del cron, che apre solo con data_apertura_verificata: sono date
--     che solo un evento `apertura` del monitor può correggere. 19 il 26/09.
select count(*) from bando
 where pubblicato and stato_bando = 'in apertura prossimamente'
   and not data_apertura_verificata
   and data_apertura <= (now() at time zone 'Europe/Rome')::date;

-- 12b. Il cron orario apre i bandi con data di apertura verificata. Atteso: 0
--      (fuori dalla prima ora dopo la mezzanotte di Roma).
select count(*) from bando
 where pubblicato and stato_bando = 'in apertura prossimamente'
   and data_apertura_verificata
   and data_apertura < (now() at time zone 'Europe/Rome')::date;
```

**Se la 10 mostra un lock valido da molto tempo**, si guarda il proprietario, sul server. Il
processo del sender è sempre vivo, quindi `ps` sul suo nome non dice niente del giro.

- `bandi_pipeline@<pid>` e `resolver@<pid>`: è orfano se `ps -p <pid> >/dev/null || echo
  orfano` stampa «orfano» (c'è un piccolo rischio che il pid sia stato riusato).
- `monitor:<giro>`: è orfano se il sender è ripartito dopo `acquisito_at`
  (`systemctl show -p ActiveEnterTimestamp edunews-bandi-sender`).
- `…:cli`: è orfano se non c'è nessun comando in corso
  (`ps aux | grep -- "-m app" | grep -v grep` vuoto).

Succede a ogni `systemctl restart` durante un giro. Si rilascia così:

```sql
select public.lock_rilascia('<nome>', '<proprietario>');
```

### 3.3 Verifica sul sito pubblico (quella che conta davvero)

I contatori dicono cosa il codice ha tentato. Solo la pagina dice cosa il lettore vede.

I comandi funzionano con il `grep` di macOS (BSD) e con quello del server (GNU): niente `grep -P`,
che su macOS esce con errore e fa sembrare pulito un ciclo che non ha letto niente; niente
`grep -c`, che conta le righe e non le occorrenze. Provati il 26/09 con `/usr/bin/grep`.

```bash
# nessun link agli aggregatori su un campione di schede
# (elenco da tenere allineato a src/config/domini-aggregatori.ts; i social restano fuori
# perché le schede hanno link di condivisione legittimi)
curl -sf https://edunews24.it/sitemap-bandi/1.xml | grep -oE '<loc>[^<]+</loc>' \
  | sed -E 's#</?loc>##g' | head -30 | while read -r s; do
  if ! p=$(curl -sf --max-time 20 "$s") || [ -z "$p" ]; then echo "$s: NON LETTA"; continue; fi
  n=$(printf '%s' "$p" | grep -oiE 'obiettivoeuropa|fasi\.eu|europafacile|contributiregione|finanziamentinews|infobandi|ticonsiglio|contributieuropa|first\.aster\.it|//(www\.)?bandi\.it' | wc -l | tr -d ' ')
  echo "$s: $n"
done
# atteso: 30 righe, tutte con 0. Una «NON LETTA», o meno di 30 righe, e la verifica non vale.
# Il campione sono le prime 30 URL del primo blocco, non un campione casuale.
```

```bash
# una scheda APERTA con fonte ufficiale deve avere il pulsante e la riga della fonte
# (dal ridisegno i chiusi, i sospesi e i revocati non hanno pulsante)
curl -s https://edunews24.it/bandi/<uno-slug-aperto-con-fonte-trovata> \
  | grep -oE 'Vai al modulo di candidatura|Apri la pagina ufficiale del bando|Consulta il bando sul portale pubblico|Fonte ufficiale[^<]{0,80}'
```

```bash
# una scheda con un evento visibile deve mostrare il box
curl -s https://edunews24.it/bandi/abruzzo-competenze-linguistiche-certificazione-fondo-perduto \
  | grep -o 'id="scheda_aggiornamenti"' | wc -l
# atteso: 1
```

### 3.4 Verifica dopo ogni modifica al codice

```bash
cd ~/projects/news1
npm run test:py:bandi     # atteso: 1879 test, OK (30/09 sera, giro di ottobre; 1533 prima)
npm test                  # atteso: 437 test, 0 falliti, 0 skipped (erano 404 prima del ridisegno)
npm run test:py           # atteso: 46 test, OK (30/09; 26 prima dei test sui lock orfani)
npx tsc --noEmit -p tsconfig.json   # atteso: 51 errori, tutti preesistenti, 0 nei file dei bandi
```

`tsc` non legge i file `.astro` e `astro check` non è installato: per le pagine l'unico controllo
automatico è la build.

**Non committare con test rossi.** È successo due volte il 25/09 e ha fatto perdere tempo.

### 3.5 Verifica dopo ogni migrazione SQL

```bash
sudo systemctl restart edunews-bandi-sender
```

**Obbligatorio.** `db.controllo` legge lo schema PostgREST **una volta per processo**: un sender
avviato prima della migrazione tiene la fotografia vecchia per tutta la sua vita e degrada in
silenzio — filtra via le colonne nuove senza un errore e senza una riga di log.

Poi, dall'esterno, verificare che il codice veda le colonne nuove: un giro di `--dry-run` del
comando interessato deve mostrare contatori diversi da zero.

**Lo stesso riavvio serve dopo ogni pull che tocca `scraper_bandi/app/` o `backend/app/`**: il
sender importa `scraper_bandi` nel proprio processo e legge `.env` una volta sola (`get_settings`
in cache). I comandi a mano (`salute`, `report-ombra`, `applica-eventi`) partono ogni volta da
zero e non ne hanno bisogno. Dopo un pull che tocca `src/` serve invece la build del frontend
(`npm run build`) e il riavvio della sua unit.

**Non riavviare il sender nell'ora e mezza prima delle 00, 06, 12 o 18.** All'avvio esegue un
giro «boot» intero e registra gli orari solo alla fine: se il boot finisce dopo l'orario, quel giro
salta al giorno dopo, monitor e ricontrolli compresi (la libreria `schedule` rimanda un'ora già
passata). Il giro più lento misurato dura circa 80'. Il momento sicuro è subito dopo la fine di un
giro: un riavvio a giro in corso lascia invece il lock fino al TTL (§3.2 punto 10).
Verifica: `journalctl -u edunews-bandi-sender --since "<ora del riavvio>" | grep -E "Pipeline
iniziale completata|Pipeline schedulata"`, con la prima riga prima del giro successivo.

### 3.6 Verifica prima di attivare un tipo di evento

**Dal deploy di ottobre** un tipo si attiva aggiungendolo a `MONITOR_TIPI_ATTIVI` (poi il riavvio
verificato, §3.5): vale per gli eventi nati da quel momento. `applica-eventi`, qui sotto, resta lo
strumento per l'arretrato, che al 30/09 si è deciso di non pubblicare. La verifica prima di
aggiungere un tipo resta questa: leggere a mano le proposte ammesse di quel tipo.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-ombra \
  --campione 100 --dal <data-inizio-ombra>
```

Il CSV elenca ogni proposta con i gate superati e falliti. **Leggere le citazioni a mano**: sono
frasi che devono esistere nella pagina dell'ente (il gate G1 lo garantisce, ma il senso no).
`report-ombra` è in sola lettura e si può lanciare dal Mac (`> file.csv`: il CSV va su stdout).

**Al 26/09** (`--dal 2026-09-24`): 24 proposte, 6 ammesse e 18 respinte, per una «precisione»
di 0,25 secondo la formula di §4.1 b. Per tipo: `apertura` 11 (1 ammessa), `nuovo_allegato` 7
(4), `graduatoria` 2, `faq` 1 (1), `proroga` 1, `chiusura` 1, `rettifica` 1. Le 6 ammesse stanno su
tre bandi (53179, 17598, 255052).

Poi, per ogni tipo, prima in prova e poi davvero:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi \
  --dal <data> --tipo <tipo> --dry-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi \
  --dal <data> --tipo <tipo> --attivo
```

**Nel riepilogo**: `applicati` per i nuovi, `resi_visibili` per quelli rimasti a metà in un giro
precedente. Poi la verifica 4 e 5 di §3.2, e la pagina pubblica.

### 3.7 Verifica dei costi

```sql
-- consumo per giorno, dagli ultimi giri
select date_trunc('day', avviato_at) as giorno, step,
       count(*) as giri,
       sum((contatori->>'usd')::numeric) as usd,
       sum((contatori->>'crediti')::numeric) as crediti,
       sum((contatori->>'classificazioni')::numeric) as classificazioni
  from pipeline_run
 where avviato_at > now() - interval '7 days'
 group by 1, 2 order by 1 desc, 2;
```

**Valori sani**: il monitor a regime sotto i 10 centesimi al giorno; i lotti (`step` che inizia per
`backfill:`) hanno contatori separati e non consumano i tetti del regime. Se le `classificazioni`
sono vicine al numero dei `controllati`, il diff non sta funzionando e ogni pagina passa dal
modello: è normale solo durante una semina.

**Fino al 26/09 i lotti consumavano i tetti giornalieri del regime** (`db.consumo_oggi` sommava
anche le righe `backfill:*`): il 25/09 i lotti L6 della mattina hanno fermato il monitor delle
18:00 a «201/30 classificazioni». Corretto nel commit `d31db9f`, che richiede il riavvio del
sender (§3.5).

Tre limiti della misura:

- `pipeline_run` **non registra** i costi di preprocess, enrich e SEO (le righe `pipeline` hanno
  `usd: 0`): il dato completo sta nelle console di Firecrawl e Anthropic;
- la riga `pipeline` di ogni giro **risomma** i crediti del resolver, che hanno già la propria riga:
  nelle somme a mano va esclusa (`where step not like 'backfill:%' and step <> 'pipeline'`).
  `consumo_oggi` e `salute` la escludono dal 26/09; prima i crediti del resolver contavano doppio;
- la chiave Firecrawl è condivisa con news e interpelli;
- il **tetto mensile** oggi non lo applica nessuno, perché `bilancio.verifica()` non riceve mai
  `crediti_mese`/`usd_mese`. Lo misura soltanto `salute` (§3.1).

Al 26/09 il mese vale 0,88 $ su 16 $ di tetto di regime.

---

## 4. Cosa resta da fare

### 4.1 Decisioni aperte (non sono lavoro arretrato: sono scelte)

**a) I tipi di evento.** **Deciso il 30/09**: `faq`, `nuovo_allegato`, `graduatoria`, `esito` e
`proroga` si applicano da soli dal deploy di ottobre (`MONITOR_TIPI_ATTIVI`, contratto interno §3).
Gli eventi già in coda non si pubblicano (decisione del lead, `ombra-2026-10.md` §5). Restano in
ombra `apertura`, `chiusura`, `rettifica`, `riapertura`, `sospensione` e `revoca`. La chiave
`valore` del punto sotto è corretta dal rilascio 2. Il resto di questo punto è la storia della
decisione.

- `apertura`, `proroga`, `chiusura`, `sospensione` e `revoca` sono in ombra. Cambiano quello che il
  lettore vede come stato del bando. Il monitor li registra a ogni giro: quando saranno un
  centinaio, si guardano e si decide (al 26/09 sono 13, vedi §3.6). Attivarli è
  `applica-eventi --tipo <tipo> --attivo`, uno per volta.
- **`apertura` ha già un costo visibile**: 19 bandi pubblicati risultano «in apertura» con la data
  di apertura passata (query 12 di §3.2; il più vecchio è del 31/05). Le date non sono verificate,
  quindi il cron non li apre, e solo un evento `apertura` può correggerli.
- **Prima di attivare `proroga`, `apertura` e `riapertura`: la chiave `valore`.** Quando il
  modello omette `campo`, la data finisce in `valore_dopo = {"valore": …}` (`eventi.py`,
  `riga_evento`) e `bando_applica_evento` scarta quella chiave: l'evento risulta applicato e la
  data non cambia. Una proroga su un bando aperto verrebbe così annunciata nel box («Scadenza
  prorogata al …») e il cron chiuderebbe il bando alla scadenza vecchia. Provato il 27/09 su un
  Postgres effimero (proroga `{"valore": "2026-12-01"}`: la RPC risponde true e `data_scadenza`
  resta com'era). A DB la forma esiste già: evento 9786, una proroga non verificata con
  `{"valore": "2026-11-08"}` e `campo` nullo. La 11 non la corregge, perché era fuori dalla scelta
  del 27/09. Servono una traduzione `valore` → colonna per tipo nella RPC (una 12 sullo schema
  della 11), la chiave giusta in `riga_evento` per gli eventi nuovi o almeno una guardia come
  quella di `stato_proposto`.
- **Da decidere anche per `faq` e `nuovo_allegato`**, già «attivati»: l'attivazione vale una volta
  sola (§1). Le strade sono tre:
  1. rilanciare `applica-eventi --dal <data> --tipo faq,nuovo_allegato --attivo` dopo i giri
     delle 06 e delle 18;
  2. aggiungere al codice un'attivazione per tipo (serve una deroga su `scraper_bandi/`);
  3. `MONITOR_MODALITA=attivo`, che però attiva tutti i tipi e cambia il default dei lotti
     (vedi §5.12).
- `graduatoria` ed `esito` vanno solo nel box «Aggiornamenti» e AVANZAMENTO ne raccomandava
  l'attivazione insieme a `faq` e `nuovo_allegato`: non risultano attivati.

**b) La soglia di uscita dall'ombra misura la cosa sbagliata.** `report-ombra` calcola
`precisione = ammessi / totale` e pretende 0,95. Ma quel numero dice *quante proposte grezze del
modello passano i gate*, e i gate devono respingerne la maggior parte: con questa formula la soglia
non è raggiungibile nemmeno da un monitor perfetto (misurato: 0,35 su 17 eventi il 25/09, 0,25 su
24 il 26/09, con i 6 ammessi tutti corretti). La precisione che decide è *degli eventi ammessi,
quanti sono giusti*, e si valuta a mano. **La formula non è stata cambiata**: abbassare una soglia
di sicurezza perché non passa è il modo sbagliato di superare un esame.

**c) Il terzo segnale del resolver è il limite dei 1 031 `in_verifica`.** Delle quattro strade
previste per il segnale «contenuto», due non hanno mai prodotto niente (`numero d'atto` e
`identificatore`: zero su tutte le righe con una fonte), quindi poggia solo su scadenza e importo.
E **116 bandi non hanno a database né l'una né l'altro**: per loro è irraggiungibile qualunque
pagina si scarichi. Sbloccarli richiede di decidere se due prove di contenuto indipendenti
(scadenza esatta *e* importo coerente) valgano quanto la terna dominio+titolo+contenuto. È anche
l'unico allarme di `salute` al 26/09 (34% di `in_verifica` sui nuovi).

**d) IndicePA non è importato.** `domini --import` ha caricato i 109 host delle fonti; il foglio
`enti.xlsx` di IndicePA aggiungerebbe ~23 000 enti (comuni, scuole, università) e si passa con
`--enti PATH`. Utile soprattutto per i bandi di comuni e GAL. Dopo l'import va rifatta la Verifica
7 della 05 (prestazioni della vista come anon).

**e) Lotto L8 (chiusi mai pubblicati): con il criterio del piano oggi non c'è niente da
lavorare.** I 561 `processed` sono tutti chiusi. Il piano ammette solo i chiusi da ≤ 90 giorni
**con fonte trovata**, e al 26/09 sono zero: i 79 con fonte trovata sono chiusi da più di 90
giorni, i 46 dentro la finestra sono tutti `in_verifica` ed escono dalla finestra giorno per
giorno. Le strade sono due:

- archiviarli tutti (`archivia-processed`, stato terminale: fatelo dopo un backup, vedi f);
- far passare il resolver sui 46 prima che escano dalla finestra (lavoro tecnico su
  `scraper_bandi/`).

**f) Operazioni irreversibili in coda, senza un backup documentato.** Non si annullano con una riga
di SQL:

- la 06 (una volta che ci sono eventi applicati);
- `applica-eventi --attivo` (le righe di `bando_evento` non si cancellano);
- `archivia-processed --attivo`;
- le fusioni di `fondi-doppioni` (si annullano con `bando_separa`, ma gli eventi restano).

Prima di queste, controllare nel pannello Supabase del progetto bandi (Database → Backups) che ci
sia un backup recente o il PITR.

**g) Doppioni visibili ai lettori.** Il lotto L4 (`fondi-doppioni`) non è mai stato eseguito. Al
26/09 si vedono, fra gli altri:

- tre schede `scelta-sociale-buono-domiciliarita-piemonte-2026-2027` (una con il suffisso `-2`,
  una scritta «domiciliarieta»);
- due IFTS Piemonte 2026-2029;
- due audiovisivi FESR Liguria.

Il dry-run elenca le coppie; le fusioni solo con il criterio esatto e dopo l'ok.

**h) IndexNow è rotto in produzione per tutto il sito.** `https://edunews24.it/api/indexnow-key`
risponde 404 «IndexNow key not configured», quindi anche il file chiave `/<chiave>.txt` dà 404 e
IndexNow non può verificare le notifiche di interpelli e selezione. La chiave si legge con
`import.meta.env`: va messa nel `.env` della root **prima** di `npm run build` sul server, poi si
ricostruisce. Inoltre i bandi nuovi non vengono mai notificati: lo step SEO non chiama IndexNow,
e oggi l'unico produttore di `slug_modificati` è il monitor in modalità attiva.

**i) Sospensione e revoca: cosa decidere prima di applicarle.** La 06 e la 11 sono sicure. La 06
allarga un CHECK. La 11 è innocua prima della 06 e ricopia la 04 (provate entrambe il 27/09 su un
Postgres effimero, §4.3). Il rischio sta nel passo dopo, quando un bando diventa davvero
`sospeso` o `revocato`. La verifica del 27/09 ha trovato questi buchi: un workflow in sola
lettura su news1, BandoFit e SQL, con ogni rilievo confermato da due verificatori. Sono tutti di
progetto, e nessuno è stato toccato.

1. **Un sospeso non ha uscite realistiche** (`src/lib/stato-bando.ts:63-68`, 04:198-205):
   - non esiste `sospeso → chiuso`;
   - una riapertura datata al passato è respinta dal G5 (`eventi.py:612-614`);
   - `annullamento_revoca` è respinta dal G9, anche se il contratto la promette come uscita dal
     revocato.

   Un bando sospeso e poi chiuso dall'ente resta «Sospeso» per sempre.
2. **Nessun percorso di correzione** per un sospeso o un revocato sbagliato. La lista bianca non
   ha righe `redazione`, e il trigger della 04 non ha l'eccezione di ruolo che il commento di
   `stato-bando.ts:66-68` promette. Oggi l'unico rientro è il blocco 0 del rollback della 06.
3. **`statoDaEventi` resta una seconda fonte dello stato** (`src/lib/bandi/aggiornamenti.ts:151-172`,
   `src/pages/bandi/[slug].astro:212`):
   - gli eventi hanno la precedenza sulla colonna;
   - non riconosce come uscite `correzione_redazionale` o una `chiusura`;
   - a parità di data vince l'evento più vecchio.

   Dopo una correzione la scheda direbbe ancora «Sospeso», mentre lista, API e BandoFit dicono
   «Aperto».
4. **Il monitor riscarica un revocato a ogni giro, per sempre**. Per la fase revocato la
   frequenza è `None`, quindi `prossimo_controllo_at` non si aggiorna e `selezionabile` resta
   vero (`monitoraggio.py`). Si pagano GET, crediti Firecrawl e classificazioni su un bando
   terminale. Lo stesso buco c'è già oggi per i chiusi oltre i 12 mesi.
5. **Una sospensione applicata a posteriori riporta a sospeso un bando riaperto nel frattempo**:
   la riapertura registrata dopo non la annulla. Prima di applicare si controlla con la query 9
   della Verifica della 11.
6. **Stallo su una transizione non più ammessa**: se il cron ha chiuso il bando dopo la
   sospensione, la RPC solleva 23514. `applica_evento_esito` lo conta come `non_tentato` e
   l'evento torna in coda a ogni lancio (query 7 della Verifica della 11). Riprodotto sul banco
   del 27/09.
7. Minori:
   - il feed RSS/JSON non riporta lo stato di un revocato (`api-v1/feed.ts:191-197`);
   - la documentazione dell'API consiglia di ricalcolare lo stato da `deadline_on`, cosa falsa
     per `suspended` (`api-v1/testi-doc.ts:236-249`);
   - con `?stato=sospeso` compare la chip «Stato: Sospeso» sopra una lista non filtrata finché
     `BANDI_STATI_ESTESI` è spento (`bandi/elenco.ts:279-281`);
   - il G9 lascia passare eventi incompatibili con sospeso e revocato (`eventi.py:822-829`);
   - il G8 non deduplica la forma `stato_proposto`;
   - in BandoFit, conto alla rovescia e CTA su sospesi e revocati, e chip incoerenti con
     `?stato=`. Non sono precondizioni della 06.

Il 27/09 a DB non c'è nessun evento `sospensione`, `revoca`, `riapertura` o `annullamento_revoca`:
niente preme.

### 4.2 Lavoro tecnico proposto e non fatto

**Fatto nel giro di ottobre** (30/09, codice pronto sul branch `claude/bandi-ripresa-ottobre`,
in produzione dal deploy; §1):
- **Pagine cieche** (T-B1): `impronte.pulisci` non toglie più il contenuto. Ancore su `main` o
  sugli h1 fuori da header, nav, footer e aside. Misurato su 611 pagine vere: le cieche passano da
  164 a 1, e le altre danno lo stesso testo di prima.
- **Riallineamento** (T-B2): `VERSIONE_PULIZIA = 2`, salvata in
  `impronte_sezioni["__versione__"]`. Una pagina con la versione vecchia si riscrive senza diff e
  senza classificazione (contatore `riallineate`), una volta sola. Il prezzo accettato: un
  cambiamento vero proprio in quell'intervallo non si vede.
- **`MONITOR_TIPI_ATTIVI`** (T-B3): per ogni evento nato nel giro di un tipo attivo, registrazione,
  applicazione e visibilità nello stesso giro. Se la RPC non scrive, l'evento resta non applicato e
  scatta l'allarme; mai un INSERT «applicato».
- **Host morti** (T-B4): tetto di 120 secondi per bando (`TETTO_TEMPO_BANDO_S`) nel resolver e nei
  ricontrolli, e gli host senza DNS saltati per il resto del giro, senza consumare tentativi. Nella
  riga del giro: `host_irraggiungibili` ed elenco (massimo 20).
- **SEO** (T-C1, T-C2, T-C3):
  - il prompt non afferma più forme di partecipazione, beneficiari o requisiti che non si leggono
    nella fonte o nei cataloghi collegati;
  - comando `seo-rigenera` (§6);
  - il 772894 era fermo per un titolo di 88 caratteri: ora si usa `titolo_breve`, poi una
    richiamata al modello, poi lo scarto con il motivo in `payload_failed_motivi`. Sui pubblicati il
    titolo è congelato e non si valida;
  - un bando di ObiettivoEuropa con una controparte pubblicata di una fonte non OE (stessa pagina,
    oppure stesso ente, importo e scadenza) si rifiuta prima della SEO: `rejection_reason` =
    «doppione probabile di <id>: …», contatore `doppioni_oe`. Mai una fusione automatica.
- **Lock orfani** (T-C4): all'avvio il sender rilascia con `lock_rilascia` i lock dei propri
  processi precedenti non più vivi, e lo scrive nel journal. `:cli` e processi vivi non si toccano.

**Emersi dalla verifica del 27/09**, fuori dal perimetro dell'intervento:

- **Monitor attivo: un INSERT diretto dopo una RPC fallita.** In modalità attiva `controlla` fa
  sempre l'INSERT diretto della riga con `applicato=true` dopo `bando_registra_evento`
  (`monitoraggio.py:1091-1106`, `eventi.py:1063-1073`). Se la RPC è fallita (5xx, 23514),
  l'evento risulta pubblico e applicato con la colonna intatta, e parte anche la rigenerazione
  della prosa. Da correggere prima di `MONITOR_MODALITA=attivo`.
- **Il 23514 della lista bianca diventa `non_tentato`** (`db.applica_evento_esito`, ramo
  `except Exception`): va trattato come
  rifiuto, nella RPC (`RETURN false`) o in Python (SQLSTATE 23514 → `rifiutato`). Vedi §4.1 i
  punto 6.
- L'intestazione del rollback della 06 dice che dopo il rientro news1 «torna a mostrare lo stato
  dagli eventi `applicato=false`»: non è vero, gli eventi saranno già applicati. Non corretta.
- `BANDI_STATI_ESTESI` / `PUBLIC_BANDI_STATI_ESTESI` non è in `.env.example`.

**Due difetti emersi il 26/09 con il credito Anthropic esaurito: corretti il 28/09** (commit
`811ff22`, rilascio 1). Il credito è rimasto a zero dal 26/09 pomeriggio almeno fino al 28/09.

- **Monitor.** Una classificazione fallita non vale più «nessun evento», e nemmeno una seconda
  opinione (Sonnet) fallita. Il controllo non salva niente: impronta, `testo_norm` e prossimo
  controllo restano quelli di prima, la pagina risulta ancora cambiata e il giro dopo il modello
  la rivede.
  - È contata in `classificazioni_fallite` e in `errori`, non in `classificazioni`: i tentativi
    falliti non consumano il tetto giornaliero, altrimenti dopo qualche giorno di credito a zero
    avrebbero fermato anche i controlli gratuiti.
  - Due interruttori per giro, uno per modello. Dopo 3 fallimenti di fila di Haiku il giro
    smette di chiamarlo e prosegue con il resto. Dopo 3 di Sonnet la seconda opinione torna a
    valere «nessuna concordanza» per il resto del giro, come prima: il G7 passa solo con la
    prova indipendente.
  - `salute` e il journal alzano un allarme (§3.1). Prima della correzione se ne sono perse 10: i
  bandi 366543, 356672, 156520 e 804007 del 26/09, più tre il 27/09 alle 18 e tre il 28/09 alle
  06. Quelle modifiche non tornano da sole: vedi §4.4.
- **Preprocess.** Il ripiego sulla pagina della fonte non scarta più un bando per un errore
  passeggero: rete, 5xx, 429, filtro WAF, ripiego Firecrawl fallito, eccezione del modello. Il
  bando resta `scraped` e il giro dopo riprova, come quando fallisce il percorso principale; il
  contatore è `fallback_rinviati`.
  - Il rinvio non ha limite d'età, per scelta. Dopo giorni senza credito, un solo guasto della
    fonte scarterebbe per sempre un bando vero. Il prezzo è che un host morto lascia il bando
    `scraped` e lo riscarica a ogni giro. Finché il rilascio 2 non porta l'allarme sull'ingresso
    fermo, si guarda a mano:
    `select id, created_at from bando where stato_processing = 'scraped' and created_at < now() - interval '2 days';`
  - Restano rifiuti una pagina vuota, una sparita (404/410) e un errore dello scarico che
    riprovando non passa (redirect infiniti, URL non valida).
  - Prima della correzione i rifiuti del ramo Firecrawl erano 25 (dal 02/07 al 23/09), e non si
    sa quanti fossero errori passeggeri: il log li registrava a livello debug.
  - Controllo: questa query deve dare 0 dopo la correzione. Gli altri motivi `fallback fallito:`
    restano legittimi.

  `select count(*) from bando where stato_processing = 'rejected' and rejection_reason =
  'fallback fallito: Sonnet API error' and updated_at > '2026-09-28';`

**Rilascio 2 del pacchetto «eventi affidabili» (29/09, branch `claude/eventi-affidabili-2`).**
- **Il diff del monitor confronta testo con testo e link con link.** Prima confrontava il
  `testo_norm` salvato (testo semplice) con l'HTML nuovo, e ogni cambio d'impronta rendeva nuova
  la pagina intera: su 20 pagine vere il vecchio diff era «rilevante» 19 volte. È la causa dei
  falsi «nuovo allegato».
  - I link della pagina si salvano in `bando_controllo.impronte_sezioni["__link__"]`, così al
    giro dopo c'è un «prima» anche per i link.
  - Il modello si chiama quando il diff non è rumore, quindi anche per una data spostata senza
    parole chiave.
  - Le righe solo spostate non contano.
- **Gate**:
  - G1/G4 confrontano le citazioni anche a spazi diversi, senza fondere le cifre;
  - G2 dei tipi «da link» vuole la citazione nelle righe nuove o nel nome di un link nuovo,
    valutato link per link (percorso e valori della query, dove molti enti mettono il nome del
    file);
  - G3 accetta la data dell'atto per graduatorie, esiti, FAQ e allegati solo se l'atto è una
    novità: al massimo 30 giorni, oppure datato dopo l'ultimo controllo meno 15 giorni (i chiusi
    si ricontrollano ogni 22-37 giorni). Se il modello non dà la data, contano le date d'atto
    della citazione;
  - i tipi «da link» senza data non prendono più il giorno del controllo.
- **I link con `;jsessionid=`** (Regione Umbria) non contano come link nuovi.
- **Costo misurato** (verifica del 29/09 su 42 pagine vere): delle 7 pagine cambiate in coda, al
  modello ne vanno 2 invece di 7. A regime 2-4 classificazioni per giro, circa 0,05-0,12 USD al
  giorno per il monitor (0,011-0,015 USD a classificazione, seconde opinioni comprese).
- **La data di proroghe e aperture va nella colonna giusta**, non più in `valore`. Gli eventi
  vecchi in quella forma restano in coda (`in_attesa_valore`); oggi è uno solo, il 9786, non
  verificato.
- **Il 23514 «transizione non ammessa» è un rifiuto.**
- **Monitor attivo**: niente INSERT «applicato» se la RPC non ha scritto; IndexNow solo per gli
  eventi applicati; allarme per gli eventi ammessi ma non applicati.
- **`salute`**: allarme per i bandi fermi in `scraped` da oltre 13 ore (ingresso bloccato).
- **Tetto ai tentativi SEO (il 772894)**: il committente ha scelto il 29/09 di **non**
  aggiungerlo, e di tenere Opus per la SEO.

**Da guardare: un bando fermo nello step SEO.** **Causa trovata e corretta il 30/09 (T-C2)**: il
titolo proposto aveva 88 caratteri e la validazione lo scartava a ogni giro, dopo una chiamata a
Opus pagata (circa 26 dal 23/09). Il bando 772894 (fonte OE, `enriched` dal 22/08,
senza titolo né slug) fallisce la SEO a ogni giro (`seo.payload_failed: 1`). Non si sa se ogni
tentativo costi una chiamata a Claude, perché la riga del giro non registra il costo della SEO.
Sul server: `journalctl -u edunews-bandi-sender --since today | grep 772894`.

- **Estendere il controllo dei tipi a tutte le tabelle.** `tests/test_eventi.py` confronta il
  payload di `bando_evento` con i tipi reali della tabella: è la guardia che avrebbe evitato due
  giorni di ombra a vuoto. Le stesse insidie possono stare in `bando_link`, `bando_controllo` e
  `bando`. Mezz'ora di lavoro.
- **Il sender non rilascia all'avvio i lock di cui era proprietario.** Dal 26/09 `salute` vede
  un lock tenuto a lungo. **Fatto nel giro di ottobre** (T-C4), in produzione dal deploy.
- **Il tetto mensile non è applicato** (§3.7): `bilancio.verifica()` non riceve mai i consumi
  del mese.
- **Nessun tetto di tempo per singolo bando nel resolver.** Su host morti un solo bando ha
  impiegato fino a 247 secondi. **Fatto nel giro di ottobre** (T-B4): 120 secondi.
- **Il logger del sender rimette `diagnose=True`.** `backend/app/logger.py` sostituisce i sink di
  `scraper_bandi` e i traceback possono contenere i valori delle variabili locali (per esempio la
  password OE a `obiettivo_europa.py:211`): il filtro `redigi` agisce solo sul messaggio. È
  dedotto dal codice, non osservato. Sul server:
  `grep -c Traceback ~/projects/news1/logs/backend-*.log | grep -v ':0$'`.
- **La lista in errore risponde 200 indicizzabile** a pagina 1 («Elenco momentaneamente non
  disponibile»), mentre la scheda risponde 503. Proposta: 503 con `Retry-After` anche qui.
- **Il pulsante «Vai al modulo di candidatura» compare anche sui bandi in apertura.** Può essere
  voluto, perché il modulo può esistere prima dell'apertura: da confermare.
- **`bandiavvisi.regione.lazio.it`** presenta un certificato con la catena incompleta e fallisce
  sempre lo scarico. È un problema dell'ente, non nostro: annotato.

### 4.3 Calendario

| quando | cosa |
|---|---|
| ogni giorno | §3.1 (journal o `salute`); dal 28/09 anche il credito Anthropic, che `salute` vede solo dal monitor delle 06 e delle 18 |
| **01/10** | `correzioni-2026-10-01-chat.sql` (o il file lungo) e `correzioni-2026-10-01-testi.sql`, fra un giro e l'altro (§1, passi 1-3) |
| **entro il 07/10** | deploy del giro di ottobre con `MONITOR_TIPI_ATTIVI` nello stesso riavvio (§1, passo 4) |
| **prima settimana dopo il deploy** | ogni mattina, la query di sorveglianza delle proroghe (§6) |
| **02/10** | settimo giorno d'ombra: `report-ombra --dal 2026-09-24`, lettura a mano delle citazioni degli ammessi |
| **prima del 05/10** | leggere il residuo di Firecrawl: il 05/10 si rinnova il periodo del piano (200 000 crediti al mese; il 22/09 ne restavano 180 286), ed è l'unico dato che conta anche preprocess, enrich e SEO |
| **07/10** | prima del giro delle 06 dell'08/10: il DNS di `regione.basilicata.it` era rotto il 28/09 (§4.4). Dal server: `getent hosts portalebandi.regione.basilicata.it` |
| **08/10** | ondata dei ricontrolli: 690 righe (non 1 252), 60 per giro alle 06 e alle 18, finisce il 13/10 alle 18 (§4.4) |
| **09/10** | quattordicesimo giorno d'ombra: nuovo `report-ombra`, poi le decisioni di §4.1 a e b |
| **verso il 24/10** | `domini --import` mensile (§6) |

**BandoFit.** La migrazione 06 aspettava il rilascio R0-a di BandoFit. Il 27/09/2026 il
committente ha confermato per iscritto che R0-a è in produzione: è il commit `a9d520a` sul `main`
di BandoFit («rilascio difensivo R0-a per gli stati sospeso/revocato», 12 file). Poi, in ordine:

Passi 1-6 **fatti il 27 e 28/09/2026**; tutte le verifiche hanno dato il valore atteso:
- Verifica 3 della 06: solo i tre stati storici più i NULL dei non pubblicati;
- Verifica 5 della 06: nessuna riga, perché non ci sono ancora sospesi;
- marcatore: `{"stati_cinque": true, "traduce_stato_proposto": true}`;
- prova a secco: `traduzione_stato_proposto: True`, `stati_estesi: True`,
  `in_attesa_traduzione: 0`, `candidati: 0`.

Il riavvio delle 08:21 è arrivato a giro di avvio in corso (partito alle 08:17). Il giro nuovo è
risultato `saltato` per il lock `bandi_pipeline` del processo vecchio, e il lock è stato
rilasciato a mano con `lock_rilascia` (§3.2 punto 10). **Resta da fare il passo 7.**

1. ~~la conferma scritta che R0-a è in produzione~~: data il 27/09/2026;
2. **backup** (§4.1 f): nel pannello Supabase del progetto bandi (Database → Backups) un backup
   recente o il PITR. La 06 e la 11 hanno un rollback, gli eventi applicati dopo no;
3. **la 11**, fra un giro e l'altro (non nell'ora e mezza prima delle 00, 06, 12 e 18): SQL Editor
   → `backend/sql/bando_v11_11_traduzione_stato_proposto.sql` intero, poi il suo blocco
   «Verifica post-deploy». Valori attesi:
   - il marcatore risponde `{"stati_cinque": false, "traduce_stato_proposto": true}`;
   - le due funzioni le esegue solo `service_role`;
   - c'è una sola `bando_applica_evento`;
   - le query 5, 7 e 9 danno 0 righe (la prova 8 è facoltativa e si annulla da sola).

   Non serve riavviare il sender. Va **prima** della 06: i controlli dei passi 4 e 6 leggono il
   suo marcatore, e senza la 11 `applica-eventi` non vede nemmeno il CHECK della 06;
4. **la 06**, fra un giro e l'altro: file intero, poi le sue Verifiche 1-5. Il marcatore della 11
   ora deve dire `"stati_cinque": true`. La query 8 di §3.2 con i cinque valori deve dare 0;
5. **`MONITOR_STATI_ESTESI=true`** in `scraper_bandi/.env` sul server, poi il riavvio verificato
   del sender (§3.5), subito dopo la fine di un giro. Effetti:
   - le sospensioni e le revoche nuove nascono con `stato_bando` invece di `stato_proposto`;
   - con il monitor in ombra restano `leggibile=false, applicato=false`: per i lettori non
     cambia niente;
   - `applica-eventi` annota i rifiuti di sospensione e revoca solo se il flag è acceso **e** il
     marcatore dice `stati_cinque: true`. I rifiuti degli altri tipi li annota sempre, come
     prima;
6. **prova a secco**: `applica-eventi --tipo sospensione,revoca --dry-run`. Nel riepilogo devono
   comparire `traduzione_stato_proposto: true`, `stati_estesi: true` e `in_attesa_traduzione: 0`;
   i candidati il 27/09 sarebbero 0;
7. **fermarsi qui finché non sono decisi i punti di §4.1 i**. Poi, e solo allora:
   - le query 7 e 9 della Verifica della 11 (0 righe), poi
     `applica-eventi --tipo sospensione,revoca --attivo --limit <piccolo>`;
   - le verifiche 4 e 5 di §3.2 e la scheda pubblica;
   - se ci sono bandi sospesi o revocati, accendere il flag del frontend che fa accettare
     `?stato=sospeso|revocato` come filtro (senza, il valore viene ignorato e la lista non si
     filtra). Due strade:
     - `BANDI_STATI_ESTESI=true` nell'ambiente dell'unit del frontend, poi il riavvio
       dell'unit, come per `BANDI_FONTE_LETTURA` (AVANZAMENTO, F2). Si legge solo da
       `process.env` e nessuno carica il `.env` della root;
     - `PUBLIC_BANDI_STATI_ESTESI=true` nel `.env` della root prima di `npm run build`, poi il
       riavvio;
8. la fase (c): **c1 in produzione dal 30/09/2026** (BandoFit 878acb0 e f5e232d); il c2 (niente ripieghi) parte
   dopo una nuova misura di §5.1 del contratto, annunciata a BandoFit con almeno 7 giorni di preavviso;
9. la 07.

**Misurato il 27/09** (PostgREST, solo GET):
- nessun evento `sospensione`, `revoca`, `riapertura` o `annullamento_revoca`;
- nessun evento con `stato_proposto` (il filtro JSON è stato controprovato su un evento con
  `stato_bando`);
- query 8 di §3.2 a 0;
- `stato_bando`: 1 256 aperto, 1 284 chiuso, 184 in apertura, 2 426 NULL, 0 sospeso e 0
  revocato.

**Provato il 27/09 su un Postgres 17 effimero** (tabelle minime, con lista bianca, trigger e RPC
estratti dalla 04; poi i file 11, 06 e rollback della 11 così come sono nel repo):
- con la 04 la sospensione `{"stato_proposto": "sospeso"}` risponde true, resta «aperto» ed è
  applicata (il difetto);
- con la 11 e senza la 06 risponde false e l'evento non è applicato;
- con 11 e 06 lo stato diventa `sospeso` (e `revocato` per la revoca), con evento e flag di
  provenienza;
- il rollback rimette la funzione della 04 con lo stesso md5;
- rieseguendo la RPC della 04 sopra la 11, il marcatore risponde `traduce_stato_proposto: false`;
- la 11 due volte di fila passa;
- con i privilegi di default di Supabase, anon non esegue niente di nuovo.

Una seconda serie ha provato le correzioni della revisione del 27/09:
- la query 7 non conta più le sospensioni senza stato;
- la query 9 trova una sospensione superata da una riapertura;
- la prova 8 si annulla da sola e lascia il bando com'era;
- il rollback della 11 è rifiutato finché il lock `monitor` è tenuto.

Il banco non è nel repo, ma si ricostruisce in pochi minuti:
- Postgres 17 di Homebrew (`/opt/homebrew/opt/postgresql@17/bin`), `initdb` in una cartella
  temporanea;
- TCP su 127.0.0.1 con una porta alta e `unix_socket_directories=''`;
- avvio e `stop` nello stesso comando;
- ruoli `anon`, `authenticated` e `service_role`, con i privilegi di default di Supabase;
- tabelle `bando` e `bando_evento` ridotte alle colonne che la RPC tocca;
- dalla 04 si copiano la lista bianca, il trigger dello stato e la RPC;
- poi si eseguono i file 11, 06 e rollback così come sono.

Le otto richieste di BandoFit (§12 del contratto) rispondono tutte, con la chiave anonima, in meno
di mezzo secondo al 26/09. Il conteggio della vista come anon (2 162) è uguale a quello del
predicato storico.

### 4.4 Prova generale del 28/09/2026

Il 28/09 si sono anticipate le operazioni in calendario, in sola lettura e senza spesa: 55
agenti, 25 rilievi (24 confermati da due verificatori, 1 smentito) più 4 del critico. Ecco cosa
ne è uscito e cosa è stato deciso.

**Corretti o in correzione** (pacchetto «eventi affidabili»):
- rilascio 1 (`811ff22`): monitor e preprocess col credito esaurito (§4.2);
- rilascio 2 (29/09):
  - la chiave `valore` e la sua guardia;
  - il 23514 contato come rifiuto;
  - l'INSERT diretto del monitor attivo;
  - le citazioni vere respinte da G1/G4 (il modello cita il diff di `sezioni()`, i gate
    confrontano `testo_normalizzato`, che toglie spazi e orari);
  - G2 che per i tipi «da link» passa su qualunque citazione (19 su 19);
  - `data_evento` presa dal giorno del controllo;
  - G3 che respinge le graduatorie datate dall'atto;
  - l'allarme di `salute` sull'ingresso fermo (4 bandi fermi in `scraped` col credito a zero,
    nessuna pubblicazione dal 25/09).

**Correzioni a mano preparate** (`docs/bandi-monitor/correzioni-2026-09-28.sql`, da far girare al committente):
- tre eventi falsi tolti dal box: 9750, 9834, 9828;
- la proroga reale del 215460, all'08/11;
- la scadenza del 17598, 16/10.

**Decisioni del committente ancora aperte:**
- **Nessun «in apertura» esce da solo.** Nessuna data di apertura è mai stata verificata e il
  cron non ha mai aperto un bando: attivare `apertura` sistemerebbe 1 dei 19 con la data
  passata. Dei 19, 9 non li guarda il monitor, perché la fonte è `in_verifica`: 6 sono in realtà
  aperti e 2 chiusi. Altri 163 «in apertura» non hanno nessuna data, e in un campione 4 su 5 erano
  sbagliati. Le strade:
  - un percorso redazionale nella lista bianca;
  - il monitor sul `link_bando` quando l'host è ufficiale;
  - «stato da verificare» per un «in apertura» con la data passata da N giorni;
  - un evento di conferma quando la pagina ripete la data in colonna.
- **46 pubblicati hanno la fonte su una pagina di pre-informazione** del Piemonte (45) o della
  Calabria (1). Quella pagina non annuncia mai né l'apertura né la chiusura.
- **Il lotto L4 (fondi-doppioni) non va lanciato così com'è:**
  - il dry-run non elenca le coppie;
  - non si può fondere solo quelle approvate;
  - il criterio per URL fonderebbe 5591/5593, che sono due avvisi diversi sulla stessa pagina
    elenco;
  - il master ignora lo stato: in 7 fusioni su 70 sparisce l'unica scheda giusta;
  - i calendari senza link e i redirect restano fuori;
  - i doppioni esatti rinascono dalla pipeline;
  - **BandoFit** (R0-b, 29/09): finché non fa la sua fase (c), legge `bando` con il predicato
    storico (`completed` e slug), che include ancora il doppione fuso. Un L4 lanciato prima
    della (c) lascia su BandoFit una seconda scheda. Da decidere col committente: L4 dopo la
    (c), oppure accettare il doppione su BandoFit per quel periodo.
- **Ingresso.** `ora_scadenza` e `ora_apertura` non sono mai valorizzate, e la finestra d'invio
  non viene letta: 3 «aperti» su 14 in realtà aprivano giorni dopo.
- **Ricontrolli.** I lotti del 23-24/09 hanno già consumato i «tre tentativi a 14 giorni»: dopo
  l'08/10 i pubblicati `in_verifica` passano a 60 giorni. Seconda ondata il 23/11, con 854 righe.
- **Resolver e monitor non leggono la tabella `dominio_ufficiale`.** Un import di IndicePA
  (§4.1 d) cambierebbe solo le funzioni SQL.
- **L8.** 35 dei 43 `processed` nella finestra dei 90 giorni ne escono il 29/09. `destinazione()`
  archivierebbe il 2773, che ha la scadenza nel 2027.
- **Le 10 classificazioni perse col credito a zero.** Non esiste oggi un modo sicuro di
  ripresentarle: azzerare l'impronta le farebbe rileggere come prima lettura, dove il G2' non
  ammette quasi niente. Da progettare.

**Trovati dalla revisione del rilascio 2, non corretti** (29/09):
- **Il 28% delle pagine monitorate è «cieco»**: 171 su 614 `testo_norm` hanno 3 righe o meno.
  Sono cieche tutte le 145 del Piemonte e tutte quelle della Valle d'Aosta. `impronte.pulisci`
  toglie i nodi che contengono il contenuto (il `form`, classi confrontate per sottostringa), e il
  monitor non vede nessun cambiamento. Correggerlo cambia l'impronta di tutte le pagine: serve
  prima un riallineamento senza diff, altrimenti un giro classificherebbe tutto.
- **Bando 455779** (Valle d'Aosta): chiuso a DB, prorogato dall'ente al 30/10. Correzione A4 in
  `correzioni-2026-09-28.sql`.
- **Il primo giro dopo il deploy non ha link salvati**: i link comparsi nel frattempo entrano nel
  «prima» senza essere visti una volta.
- **Box «Aggiornamenti»**: gli eventi senza data vanno in fondo e sono i primi a uscire dal limite
  di 20 (`src/lib/bandi/aggiornamenti.ts`). Serve la deroga sul frontend.
- **G8**:
  - non deduplica le sospensioni con `stato_proposto`;
  - due graduatorie diverse entro 30 giorni si deduplicano.
- **Monitor attivo**:
  - un timeout dopo il commit della RPC lascia la colonna cambiata e la prosa vecchia;
  - un evento registrato ma non applicato (date incoerenti) resta visibile nel box;
  - solo se si torna indietro dalla 06 (o con `MONITOR_STATI_ESTESI=false`) e il monitor è
    attivo: una sospensione o revoca ammessa fa scattare l'allarme «eventi non applicati» senza
    motivo e il suo slug non va a IndexNow. Con la configurazione di oggi non succede.
- **G2, caso residuo**: se il modello cita un paragrafo che c'era già (Toscana, «graduatoria
  approvata con decreto …») e i link agli allegati arrivano dopo, la citazione non è né nelle
  righe nuove né nel nome dei link, e l'evento è respinto.
- **G1/G4**: cifre spezzate da un tag inline («<b>1</b>5 ottobre» diventa «1 5 ottobre») non
  combaciano più con «15 ottobre». Raro.

**Segnalato da BandoFit il 29/09, non corretto: testi SEO con forme di partecipazione inventate.**
Tre schede affermano nel `contenuto` forme di partecipazione che l'atto dell'ente non prevede:
- 18145: «imprese in forma singola o associata», assente dall'All. 1 del DD 1246/2026;
- 18278: «reti di imprese e aggregazioni» e «imprese sociali e società benefit», mentre il bando
  CCIAA finanzia solo singole imprese (art. 2);
- 171905: «in forma singola o associata», mentre il decreto MASE 233/2026 (art. 4 c.1) vuole almeno
  due partner con capofila.

Le cause sono due, misurate sul DB:
- per 18278 l'enricher ha messo il beneficiario «Imprese sociali/Società benefit» nella junction,
  e la SEO lo ha trasformato in prosa;
- il resto è formula generica aggiunta dalla SEO: il prompt di `seo_skill.py` non la contiene.

Le tre schede sono di giugno-luglio. Non si sa quante altre ne abbiano; il committente decide se
cercarle ed eventualmente rigenerarle.

**Proposta di BandoFit il 29/09, da decidere: seguire un salto dalla pagina ufficiale.** Su alcuni
bandi le regole stanno in atti linkati dalla pagina ufficiale, e `bando_link` non li contiene.
Verificato con la chiave anonima:
- 18351 (MIMIT): ci sono la pagina del DM (HTML) e l'informativa privacy, ma non i PDF del DM e del
  DD in `/images/stories/normativa/`;
- 18207 (Sardegna Ricerche): ci sono la pagina e un PDF del 19/12/2025 (secondo BandoFit la sola
  locandina), ma non le disposizioni attuative, gli allegati e le FAQ; l'avviso sembra riemesso
  a febbraio 2026;
- 2242 (Abruzzo, welfare aziendale): ci sono 19 allegati (commissione, FAQ, graduatorie), ma non
  l'Avviso.

La proposta è seguire un salto sullo stesso dominio istituzionale per raccogliere i documenti
principali. Tocca il resolver e la raccolta dei link, quindi serve la decisione del committente.

**Controllo dei 20 bandi pubblicati dal giro delle 12 del 29/09** (confronto con le fonti
ufficiali, un verificatore più uno scettico per ogni difetto grave o importante):
- **6 doppioni su 20**, tutti confermati sul DB. Quattro sono schede di ObiettivoEuropa (fonte
  449) di avvisi già pubblicati dalla fonte ufficiale, con stesso ente, importo e scadenza. Uno
  nasce dal cambio d'URL della pagina del Piemonte dopo una rettifica. L'ultimo è la stessa
  pagina lazioeuropa.it arrivata da due fonti. Fusioni F1-F6 in
  `docs/bandi-monitor/correzioni-2026-09-29.sql`, da lanciare dal committente.
- **17 dei 20 bandi vengono da ObiettivoEuropa.** Ne copiano anche gli errori: il 1262408 dichiara
  25,7 milioni invece di 2,57, anche nel titolo (B3).
- **Date strutturate mancanti.** Nessuno dei 20 ha `data_apertura`, e tre non hanno la scadenza,
  che pure la fonte dichiara. Due risultano «aperti» ma aprono il 30/09 e l'01/10 (1262404,
  1262412). Sui pubblicati, `data_apertura` è valorizzata su 111 su 2182.
- **Testi SEO con beneficiari o requisiti non sostenuti dalla fonte** in 8 schede: 1262345,
  1262398, 1262399, 1262402, 1262406, 1262408, 1262411, 1262412. Stesso difetto della
  segnalazione di BandoFit.
- **Da verificare a mano**: 1262402 (Sicilia, spettacolo: trovato solo l'avviso 2025) e 1262407
  (Trento, biogas: atto ufficiale non trovato). Potrebbero non essere avvisi del 2026.
- **Corretti a DB con B1-B2** (da lanciare): la proroga del 1262082 al 19/10, che il monitor non
  ha visto perché la pagina del Piemonte è cieca; apertura e scadenza del 1262080.

**Correzioni eseguite il 30/09/2026** dal committente nel SQL Editor, verificate sul DB e sulle
pagine pubbliche:
- 13 proroghe di bandi in scadenza il 30/09 (blocco C);
- A1-A4;
- B1-B3;
- F1-F6: i 6 doppioni rispondono 301 verso il master.

I due file `correzioni-2026-09-2{8,9}.sql` portano in testa «NON rieseguire». Sul 112862 l'RPC ha
riusato per dedup l'evento 11295 del monitor, che non è verificato: la scadenza è giusta, ma la
proroga non compare nel box «Aggiornamenti».

**Scadenze nate dalla prova:**
- 07/10: la Basilicata. Col DNS rotto, il giro delle 06 dell'08/10 rischia 100 minuti di
  ricontrolli su 101 URL morti.
- Credito Anthropic ogni giorno finché il rilascio 2 non aggiunge l'allarme sull'ingresso.

### 4.5 Giro «ripresa bandi, ottobre 2026» (30/09/2026)

Oltre al codice (§4.2), il giro ha misurato il DB e riletto le pagine ufficiali. Tutto in sola
lettura; le correzioni sono file SQL che lancia il committente.

- **La 07 è rimandata** (`misure-colonne-07.md`, contratto verso BandoFit §5.1). Letta con la anon
  key, toglierebbe il pulsante verso l'ente a 211 bandi (183 aperti o in apertura) e tutti gli
  allegati a 151. Le righe sostitutive di `bando_link` esistono quasi tutte, ma sono righe `raw`
  mai verificate. E il buco cresce: nessun codice crea righe `candidatura`, mentre la SEO continua
  a scrivere `link_candidatura`. Nella fase (c) BandoFit leggerà prima `bando_link` e ripiegherà
  sulle colonne deprecate.
- **Scadenze e aperture sbagliate** (`correzioni-2026-10-01.sql` e la versione per la chat). Dei
  120 pubblicati che scadevano il 30/09, 13 hanno una data nuova per l'ente (12 proroghe, una data
  sbagliata di un anno). Dei 21 «in apertura» con la data passata, 16 sono aperti e 2 già chiusi.
  Provati su Postgres 17 effimero.
- **Testi** (`rigenerazione-2026-10.md`, `correzioni-2026-10-01-testi.sql`): 166 schede con forme
  di partecipazione, soprattutto da ObiettivoEuropa (nel campione, 5 sbagliate su 13 OE, 0 su 2
  delle altre fonti); 14 aperti da passare a `seo-rigenera`; il 18278 è l'edizione 2025, esaurita
  il 21/10/2025, e si chiude. `rigenera` prende la prosa con le date vecchie.
- **Periodo d'ombra** (`ombra-2026-10.md`): nessuna proroga falsa in 12 proposte, ma il monitor non
  ha visto nessuna delle 13 proroghe trovate a mano. Vede i cambiamenti, non le date già sbagliate
  alla prima lettura (§5.13).
- **425 dei 1 249 «aperto» non hanno una scadenza** (286 di ObiettivoEuropa): uno sportello
  esaurito resta aperto per sempre, perché il cron non ha una data per chiuderlo
  (`rigenerazione-2026-10.md` §8).
- **41 coppie ObiettivoEuropa / fonte ufficiale** pubblicate tutte e due e mai fuse
  (`doppioni-oe-da-fondere.md`): lavoro con il committente, con `bando_fondi` e dopo aver deciso
  per BandoFit.
- **Verifiche che solo il committente può fare**: `verifiche-michele-2026-10.md` (crediti, backup,
  rotazione della password OE, 57014, unit, DNS della Basilicata).

---

## 5. Trappole imparate (leggere prima di lavorarci)

1. **PostgREST tronca a 1 000 righe e non lo dice.** Una `.limit(5000)` riceve 1 000 righe come se
   fossero tutte. In `app/db.py` ci sono `PAGINA_POSTGREST`, `_scorri()` e `_per_id()`: ogni lettura
   che può superare il tetto passa da lì.

2. **Un campione preso con `--limit N` non è un campione.** Le selezioni ordinano per `id`, quindi i
   primi N sono i bandi più vecchi del corpus, da fonti che non funzionano più. Il 25/09 un campione
   di 60 ha dato `trovate: 0` e mi ha portato a dire «non lanciare il giro pieno»; il giro pieno ne
   ha trovate 113. **Per stimare una resa: uno per host, mai i primi N.**

3. **Il `--limit` deve contare le righe utili, non quelle lette.** Corretto tre volte in tre posti
   diversi (`link-verifica`, selezione del resolver, `report-ombra`): se il filtro sta a valle della
   lettura, il comando dichiara di aver guardato tutto e guarda una coda vuota.

4. **I contatori dicono cosa il codice ha tentato, non cosa è successo.** Tutti i difetti del 24 e
   25 settembre sono stati trovati misurando il database e confrontandolo con il riepilogo:
   `eventi: 0` sembrava «i gate respingono» e invece gli insert venivano rifiutati; `applicati: 5`
   sembrava «fatto» e le righe erano invisibili. **Prima di dire che qualcosa funziona, leggere il
   database o la pagina.**

5. **`db.controllo` legge lo schema una volta per processo.** Dopo ogni migrazione il sender va
   riavviato, e il riavvio va verificato dall'esterno.

6. **Un `systemctl restart` durante un giro lascia il lock orfano** per tutta la sua scadenza. Vedi
   §3.2 punto 10. Il giro di avvio conta come un giro: il 28/09 un secondo riavvio, quattro
   minuti dopo il primo, ha trovato il lock del giro di avvio precedente, ha saltato il proprio
   e avrebbe fatto saltare anche quello delle 12 (il TTL della pipeline è di 4 ore,
   `backend/app/bandi_pipeline.py:95`). Fra due riavvii si aspetta la riga «Pipeline iniziale
   completata» del primo.

7. **Una colonna, una scala.** `bando_evento.confidenza` è uno `smallint` e il resolver ci scriveva
   0-100 mentre il monitor 0-1: Postgres rifiutava ogni insert e l'errore finiva in un warning.

8. **Applicare un evento non lo rende visibile.** `bando_applica_evento` marca `applicato` e non
   tocca `leggibile`; il trigger del cursore scatta su `UPDATE OF leggibile`. Servono due scritture.

9. **Un controllo che non legge niente dice sempre «tutto bene».** Fino al 26/09 `salute` giudicava
   tre valori di configurazione: exit 0 a ogni esecuzione, anche con il monitor fermato dal tetto
   due giri di fila il 25/09. Prima di fidarsi di un controllo, guardare **che cosa legge**.

10. **Due contatori «separati» possono sommarsi in un terzo punto.** I lotti avevano tetti propri in
    `bilancio.verifica()`, ma `db.consumo_oggi()` li sommava al consumo del regime: un lotto la
    mattina fermava il monitor la sera. Quando una regola dice «X non conta per Y», cercare
    **tutte** le somme di Y.

11. **I comandi di verifica devono girare anche sul Mac.** `grep -P` non esiste nel grep di macOS:
    il ciclo di §3.3 non stampava niente e sembrava pulito. `grep -c` conta le righe, non le
    occorrenze, e sul box «Aggiornamenti» dava un falso allarme. I comandi di §3.3 ora usano solo
    `grep -oE` e `wc -l`.

12. **Senza flag decide l'ambiente, e in produzione il resolver è attivo.** «Senza `--attivo` non
    tocca niente» era falso: con `RESOLVER_MODALITA=attivo`, `risolvi-fonte`, `oe-dettaglio`,
    `link-verifica`, `fondi-doppioni` e `domini --import` scrivono. Lo stesso varrà per
    `archivia-processed`, `pulisci-contenuto`, `rigenera` e `applica-eventi` il giorno in cui
    `MONITOR_MODALITA=attivo`. **Scrivere sempre per esteso `--dry-run` (per provare) o `--ombra`
    (che non tocca le colonne pubbliche ma scrive comunque le tabelle di servizio).**

13. **Il monitor vede i cambiamenti, non le date già sbagliate.** Il 30/09 nessuna delle 13
    proroghe trovate a mano era stata proposta: tre pagine dei GAL dell'Emilia-Romagna avevano la
    proroga già alla prima lettura, e niente cambia dopo. Lo stesso per il 18278, esaurito da un
    anno e ancora «aperto». Una data sbagliata alla pubblicazione (quasi sempre da ObiettivoEuropa)
    resta sbagliata finché qualcuno non la confronta con la pagina.

14. **Un evento vecchio in coda può riaprire un bando.** La lista bianca guarda solo lo stato di
    partenza, quello di arrivo e l'attore, non il tipo né l'età dell'evento. Un'apertura ammessa
    settimane fa e applicata dopo la chiusura del bando lo riporta ad «aperto» (chiuso → aperto è
    ammesso per il worker). Al 30/09 ce ne sono due (9749 e 11299): `MONITOR_TIPI_ATTIVI` non li
    tocca, il rischio è un `applica-eventi` lanciato a mano sull'arretrato.

---

## 6. Comandi utili, in ordine di frequenza

```bash
cd ~/projects/news1/scraper_bandi

# stato di salute
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app salute --json

# fonte ufficiale dei bandi nuovi (lo fa già la pipeline)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app risolvi-fonte --dry-run --limit 20

# ripassare gli arretrati dopo un cambio di regole o di whitelist
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app risolvi-fonte \
  --attivo --solo-in-verifica --forza --anche-oggi --lotto L5x

# ricontrollo dei link (ripara le righe non pubblicabili delle fonti)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app link-verifica --attivo --solo-fonti --limit 600

# un giro di monitor fuori cadenza (--forza) sui tetti del backfill (--lotto)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app monitor --ombra --lotto L6 --forza --limit 100

# misura del periodo d'ombra
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-ombra --campione 100 --dal <data>

# attivazione a posteriori di un tipo di evento (arretrato dell'ombra)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi --dal <data> --tipo <tipo> --attivo

# ripresa di eventi precisi, per id: è il comando che scrivono gli allarmi
# del monitor («eventi ammessi non applicati»); prima --dry-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi --ids 1,2 --dry-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi --ids 1,2 --attivo

# whitelist dei domini (mensile, o dopo aver aggiunto fonti)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app domini --import --attivo [--enti enti.xlsx]

# testi già pubblicati da riscrivere col prompt nuovo (dal giro di ottobre)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app seo-rigenera --solo-controllo
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app seo-rigenera \
  --dry-run --ids 1,2,3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app seo-rigenera \
  --attivo --proposte ~/seo-proposte-AAAA-MM-GG.json

# prosa con le date vecchie dopo eventi verificati (lotto L7: niente lock,
# quindi nella finestra sicura e mai durante un giro)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app rigenera --dry-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app rigenera --attivo
```

**`seo-rigenera`**, tre modi:
- `--solo-controllo [--ids …]`: cerca nei testi attuali le forme di partecipazione non sostenute.
  Niente modello, lock, scritture o spesa; la stima è per eccesso, perché non legge la pagina
  ufficiale. Non vede i beneficiari e i requisiti inventati: quelli si trovano solo leggendo;
- `--dry-run --ids … [--uscita FILE]`: **spende** (Opus e lo scarico della pagina), stampa vecchio,
  nuovo e costo, e salva le proposte nel file (default `~/seo-proposte-AAAA-MM-GG.json`, con l'ora
  in coda se esiste già). Non scrive sul DB. Meglio non passare `--uscita` con un nome fisso: se il
  file esiste già, la seconda prova si ferma con exit 2;
- `--attivo --proposte FILE [--ids …]`: scrive le proposte del file **senza richiamare il modello**,
  cioè esattamente il testo letto. Salta i bandi non più pubblicati, quelli cambiati dopo la prova
  e quelli con affermazioni ancora segnalate. Prende il lock `bandi_pipeline` e scrive
  `pipeline_run`: solo nella finestra sicura (12:30-16:30 o 19:00-22:30), altrimenti il giro del
  sender salta.

Rifiuta gli id non pubblicati o fusi; `--limit N` conta le schede lavorate. Riscrive solo
`contenuto` e, se la prova l'ha deciso, `descrizione_breve`: slug, titolo, date, importi, stato e
junction restano come sono. Le junction sbagliate si correggono con SQL.

**`applica-eventi`**: `--tipo` e `--dal` prendono tutto l'arretrato di quei tipi e di quei giorni.
`--ids` prende **solo** gli eventi indicati: è il filtro da usare quando un allarme del monitor dice
«eventi ammessi non applicati» e scrive il comando di ripresa (`applica-eventi --ids … --attivo`),
perché riprende gli eventi di quel giro e non tocca l'arretrato. Con `--ids` si possono combinare
`--dry-run` e `--limit`. `--riprova-rifiutati` ripresenta anche gli eventi già respinti dalla RPC:
serve solo se un rifiuto è stato annotato per sbaglio.

**`MONITOR_TIPI_ATTIVI`** (in `scraper_bandi/.env`, letto all'avvio: dopo una modifica serve il
riavvio verificato, §3.5): lista separata da virgole dei tipi che il monitor applica e rende
visibili nello stesso giro, anche con `MONITOR_MODALITA` in ombra. Vale solo per gli eventi nati
da quel momento. Un valore sconosciuto è ignorato, con `[ALLARME]` nel journal e in `salute`.
Nella riga del giro: `tipi_attivi`, cioè la lista **usata** da quel giro (vuota con `--ombra` o
`--dry-run`), `applicati_per_tipo` ed `eventi_non_applicati`.

**Sorveglianza delle proroghe** (la prima settimana dopo il deploy, ogni mattina, con la pagina
ufficiale aperta accanto). Il filtro su `metodo` esclude le correzioni a mano, che sono
`origine='worker'` come il monitor:

```sql
select id, bando_id, valore_dopo, url_prova, citazione
  from bando_evento
 where tipo = 'proroga' and applicato
   and applicato_at > now() - interval '1 day'
   and coalesce(metodo, '') not like 'correzione manuale%'
 order by id;
```

**Doppione di ObiettivoEuropa rifiutato per sbaglio** (contratto interno §6). Il controllo della
SEO può rifiutare un bando OE vero. Per rimetterlo in coda:

```sql
update bando
   set stato_processing = 'enriched',
       rejection_reason = 'doppione escluso a mano'
 where id = <id> and stato_processing = 'rejected';
```

Al giro dopo il bando va alla SEO e il controllo non lo rifiuta più. `rejection_reason =
'doppione escluso a mano'` resta sulla riga anche dopo la pubblicazione: è voluto, è il segno che
qualcuno l'ha deciso. I rifiuti del controllo:
`select id, rejection_reason from bando where rejection_reason like 'doppione probabile di %';`

Ogni comando che scrive accetta `--dry-run` e `--limit`. **Senza `--attivo` e senza `--ombra`
decide `RESOLVER_MODALITA` (o `MONITOR_MODALITA` per monitor, eventi e lotti)**, e in produzione il
resolver è attivo. Per provare senza effetti serve `--dry-run` (§5.12). `--ombra` non tocca le
colonne pubbliche ma scrive `bando_controllo` (ultimo e prossimo controllo, tentativi) ed eventi
muti, oltre a lock e `pipeline_run`: un esito `in_verifica` o `non_trovata` fa uscire il bando
dalla coda del resolver per 14 o 60 giorni.

Anche in `--dry-run`:

- `risolvi-fonte`, `monitor` e `applica-eventi` prendono un lock e scrivono una riga in
  `pipeline_run`;
- i lotti (`pulisci-contenuto`, `rigenera`, `archivia-processed`) scrivono la riga ma non prendono
  nessun lock, quindi non vanno lanciati mentre gira un giro del sender;
- `monitor` spende (scarichi e classificazioni), quindi non si lancia dal Mac.

`salute`, `report-ombra` e `link-verifica --dry-run` sono in sola lettura. I comandi lunghi si
lanciano con `nohup … &` e un file di log. Il percorso `~/projects/news1` è quello del server; sul
Mac il repo sta in `~/Developer/news1`.

---

## 7. Regole di lavoro su questo dominio

- **Il database si legge, non si scrive a mano.** Le migrazioni sono file idempotenti in
  `backend/sql/`, con blocco di verifica e rollback, e le applica il committente nel SQL Editor.
- **`PYTHONDONTWRITEBYTECODE=1`** su ogni comando Python. I test importano i moduli per percorso
  (`from tests.supporto import carica_modulo`) perché su questa macchina esiste un altro package
  chiamato `app` sul `sys.path`.
- **Nessuna dipendenza nuova**, npm o pip.
- **Italiano** per commenti, docstring, nomi dei moduli nuovi e testi visibili.
- **Mai stampare** i valori di `.env`, cookie, token.
- **BandoFit** (`~/Developer/BandoFit`) legge lo stesso database con la chiave anonima: un
  pubblicato non esce mai da `completed`, gli id e gli slug sono congelati, le REVOKE solo in
  fase (d).
