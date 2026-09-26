# Bandi — punto di ripresa e verifiche

Questo file serve a riprendere il lavoro sui bandi dopo una pausa di giorni o di settimane, senza
rileggere il piano né ricostruire il contesto. È aggiornato al **26 settembre 2026, ore 12**
(controllo completo sul DB, sul sito pubblico e sui test; la versione precedente era del 25/09
alle 12).

Per la cronaca di come ci siamo arrivati: `AVANZAMENTO.md`, nella stessa cartella. Per il contratto
verso BandoFit: `docs/contratto-db-bandi.md`. Il piano completo dell'intervento sta in
`~/.claude/plans/pasted-content-id-dcf2-sei-un-wondrous-seal.md`.

---

## 1. Dove siamo

L'intervento è **in esercizio**. Il resolver e i ricontrolli scrivono in produzione; il monitor
registra ma non applica e non rende visibile niente, di nessun tipo (modalità ombra). Il 25/09 gli
eventi `faq` e `nuovo_allegato` già raccolti sono stati resi visibili una volta, a mano, con
`applica-eventi` (vedi sotto).

| | valore al 26/09/2026 | al 25/09 |
|---|---|---|
| bandi pubblicati | 2 162 | 2 147 |
| **fonti ufficiali trovate** (pubblicati) | **614** — 693 contando 79 bandi `processed` mai pubblicati | 609 |
| fonti in verifica (pubblicati) | 1 031 | 1 027 |
| fonti non trovate (pubblicati) | 517 | 511 |
| fonti trovate con link non leggibile | 0 su 693 | — |
| **CTA verso un aggregatore** | **0** (query 1 a DB e 30 schede lette) | 0 su 2 147 |
| proposte del monitor registrate dal 24/09 | 24 (6 ammesse, 5 visibili sulle schede) | 17 |
| domini in whitelist | 109 (non rimisurato) | 109 |

Il numero «653 schede con un pulsante verso l'ente» del 25/09 non si confronta più: dal
ridisegno (vedi sotto) i bandi chiusi non mostrano nessun pulsante.

**Frontend.** Dal 25/09 sera in produzione c'è il ridisegno di lista, pagine filtro, hub e
scheda (commit `4c48e1a..5203602`); la lettura passa dalla vista `bando_pubblico` (F2 acceso,
API v1.1). Per i bandi chiusi, sospesi e revocati la scheda non mostra la CTA ma un messaggio.
Le verifiche visive le ha fatte il committente.

### Migrazioni applicate

`01, 02, seed, 03, 04, 05, 08, 09, 10`. **Mai applicate: la 06 e la 07.**

- La **06** (cinque stati del bando, cioè `sospeso` e `revocato`) richiede prima il rilascio
  difensivo R0 di BandoFit. Finché non c'è, gli eventi di sospensione e revoca restano
  `applicato=false`. Sarebbero leggibili (box sulla scheda, pulsante disattivato) solo con
  `MONITOR_MODALITA=attivo`: oggi, in ombra, nascono `leggibile=false`.
- La **07** (fase d: REVOKE di colonna, RLS stretta) richiede che BandoFit sia passato al contratto.

### Configurazione in produzione (`scraper_bandi/.env`)

```
RESOLVER_MODALITA=attivo      ← messo il 25/09: prima valeva `ombra` per difetto
                                 e ogni giro risolveva bandi nuovi e buttava il risultato
```

`MONITOR_MODALITA` **non è impostata**, quindi vale `ombra`: il monitor registra le proposte e non
tocca stato né date. È voluto. `MONITOR_GIRI` e `MONITOR_SCENARIO` non sono impostate e i default
(`06:00,18:00`, `bilanciato`) sono quelli giusti.

**L'attivazione di `faq` e `nuovo_allegato` del 25/09 è valsa una volta sola.** Un'attivazione per
tipo non esiste nel codice: in ombra ogni evento nuovo nasce `leggibile=false`, qualunque sia il
tipo, e la pipeline non rilancia `applica-eventi`. Il 26/09 nessun evento ammesso di quei due tipi
era rimasto nascosto (l'unico nuovo, del 26/09, non ha passato i gate), ma il prossimo ammesso
resterà invisibile finché qualcuno non rilancia `applica-eventi --tipo faq,nuovo_allegato
--attivo`. Vedi §4.1 a.

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
  160'); oltre un terzo del TTL, e comunque oltre i 60', è un avviso;
- il DB non risponde.

Login OE, residuo Firecrawl e schede OE **non si misurano dal DB**: `salute` lo dice negli avvisi
(«non misurato da salute: …»), e si controllano come sotto.

**Esito atteso oggi: exit 1**, con un solo allarme: «fonti in verifica sui nuovi 34% (> 30%)» (22
su 64 al 26/09). È un allarme vero secondo la soglia del piano, e resterà finché non si decide il
§4.1 c (il terzo segnale del resolver).

```bash
systemctl is-active edunews-bandi-sender
journalctl -u edunews-bandi-sender --since today \
  | grep -E "STEP (resolver|ricontrolli|monitor)|FAILED|NON PARTITO|\[ALLARME\]"
```

**Cosa deve comparire**: `attivo: True` sul resolver; una riga `STEP ricontrolli`; il monitor solo
alle 06:00 e 18:00 (negli altri giri `SALTATO (giro non previsto)`, che è corretto); nessun
`FAILED`, `NON PARTITO` o `[ALLARME]` scritto dagli step. Il login OE si vede qui: nessuna riga
`obiettivo_europa/auth`, `sessione non autenticata` o `SessioneOEError`.

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

-- 8. Nessuno stato fuori vocabolario prima della migrazione 06. Atteso: 0
select count(*) from bando
 where stato_bando is not null
   and stato_bando not in ('aperto','chiuso','in apertura prossimamente');

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
--     dopo la mezzanotte di Roma; sospesi e revocati esclusi dopo la 06).
select count(*) from bando
 where pubblicato and stato_bando <> 'chiuso'
   and data_scadenza < (now() at time zone 'Europe/Rome')::date;

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
npm run test:py:bandi     # atteso: 1485 test, OK (erano 1461 prima del 26/09)
npm test                  # atteso: 433 test, 0 falliti, 0 skipped (erano 404 prima del ridisegno)
npm run test:py           # atteso: 26 test, OK
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

**a) I tipi di evento.**

- `apertura`, `proroga`, `chiusura`, `sospensione` e `revoca` sono in ombra. Cambiano quello che il
  lettore vede come stato del bando. Il monitor li registra a ogni giro: quando saranno un
  centinaio, si guardano e si decide (al 26/09 sono 13, vedi §3.6). Attivarli è
  `applica-eventi --tipo <tipo> --attivo`, uno per volta.
- **`apertura` ha già un costo visibile**: 19 bandi pubblicati risultano «in apertura» con la data
  di apertura passata (query 12 di §3.2; il più vecchio è del 31/05). Le date non sono verificate,
  quindi il cron non li apre, e solo un evento `apertura` può correggerli.
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

### 4.2 Lavoro tecnico proposto e non fatto

- **Estendere il controllo dei tipi a tutte le tabelle.** `tests/test_eventi.py` confronta il
  payload di `bando_evento` con i tipi reali della tabella: è la guardia che avrebbe evitato due
  giorni di ombra a vuoto. Le stesse insidie possono stare in `bando_link`, `bando_controllo` e
  `bando`. Mezz'ora di lavoro.
- **Il sender non rilascia all'avvio i lock di cui era proprietario.** Dal 26/09 `salute` vede
  un lock tenuto a lungo; il rilascio automatico dopo un `systemctl restart` resta da fare.
- **Il tetto mensile non è applicato** (§3.7): `bilancio.verifica()` non riceve mai i consumi
  del mese.
- **Nessun tetto di tempo per singolo bando nel resolver.** Su host morti un solo bando ha
  impiegato fino a 247 secondi.
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
| ogni giorno | §3.1 (journal o `salute`) |
| **02/10** | settimo giorno d'ombra: `report-ombra --dal 2026-09-24`, lettura a mano delle citazioni degli ammessi |
| **prima del 05/10** | leggere il residuo di Firecrawl: il 05/10 si rinnova il periodo del piano (200 000 crediti al mese; il 22/09 ne restavano 180 286), ed è l'unico dato che conta anche preprocess, enrich e SEO |
| **08/10** | ondata dei ricontrolli (§3.1): una decina di giorni con 120 righe al giorno |
| **09/10** | quattordicesimo giorno d'ombra: nuovo `report-ombra`, poi le decisioni di §4.1 a e b |
| **verso il 24/10** | `domini --import` mensile (§6) |

**BandoFit.** La migrazione 06 aspetta il rilascio R0-a di BandoFit. Al 26/09 il lavoro R0-a
esiste solo come modifiche non committate nel repo di BandoFit (12 file), e in HEAD il filtro
accetta ancora solo tre stati. Poi, in ordine:

1. la conferma scritta che R0-a è in produzione;
2. la 06, poi `MONITOR_STATI_ESTESI=true` e il riavvio verificato del sender (§3.5);
3. `applica-eventi --tipo sospensione,revoca`, **ma prima va chiuso un punto aperto dalla
   revisione del 26/09**: gli eventi di sospensione e revoca raccolti in ombra portano
   `valore_dopo = {"stato_proposto": …}` e non `stato_bando` (`eventi.py`, `riga_evento`).
   Secondo la revisione `bando_applica_evento` scrive solo le colonne che riconosce, quindi li
   segnerebbe applicati senza cambiare lo stato. Serve una traduzione `stato_proposto` →
   `stato_bando` (nella RPC o nella CLI). Da verificare e sistemare prima di questo passo;
4. la fase (c);
5. la 07.

Le otto richieste di BandoFit (§12 del contratto) rispondono tutte, con la chiave anonima, in meno
di mezzo secondo al 26/09. Il conteggio della vista come anon (2 162) è uguale a quello del
predicato storico.

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
   §3.2 punto 10.

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

# attivazione di un tipo di evento
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app applica-eventi --dal <data> --tipo <tipo> --attivo

# whitelist dei domini (mensile, o dopo aver aggiunto fonti)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app domini --import --attivo [--enti enti.xlsx]
```

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
