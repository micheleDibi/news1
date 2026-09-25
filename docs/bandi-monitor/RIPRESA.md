# Bandi — punto di ripresa e verifiche

Questo file serve a riprendere il lavoro sui bandi dopo una pausa di giorni o di settimane, senza
rileggere il piano né ricostruire il contesto. È aggiornato al **25 settembre 2026, ore 12**.

Per la cronaca di come ci siamo arrivati: `AVANZAMENTO.md`, nella stessa cartella. Per il contratto
verso BandoFit: `docs/contratto-db-bandi.md`. Il piano completo dell'intervento sta in
`~/.claude/plans/pasted-content-id-dcf2-sei-un-wondrous-seal.md`.

---

## 1. Dove siamo

L'intervento è **in esercizio**. Il resolver e i ricontrolli scrivono in produzione; il monitor
registra ma non applica (modalità ombra), tranne i due tipi di evento attivati a mano.

| | valore al 25/09/2026 |
|---|---|
| bandi pubblicati | 2 147 |
| **fonti ufficiali trovate** | **609** (erano 66 il 24/09 alle 9) |
| fonti in verifica | 1 027 |
| fonti non trovate | 511 |
| pagine con fotografia di partenza (baseline) | **609 su 609** |
| link pubblicabili | 6 174 su 10 107 |
| **CTA verso un aggregatore** | **0 su 2 147** |
| schede con un pulsante verso l'ente | 653 |
| proposte del monitor registrate | 17 (6 ammesse, 5 visibili sulle schede) |
| domini in whitelist | 109 |

### Migrazioni applicate

`01, 02, seed, 03, 04, 05, 08, 09, 10`. **Mai applicate: la 06 e la 07.**

- La **06** (cinque stati del bando, cioè `sospeso` e `revocato`) richiede prima il rilascio
  difensivo R0 di BandoFit. Finché non c'è, gli eventi di sospensione e revoca restano
  `applicato=false` ma leggibili: la scheda lo dice nel box e disattiva il pulsante.
- La **07** (fase d: REVOKE di colonna, RLS stretta) richiede che BandoFit sia passato al contratto.

### Configurazione in produzione (`scraper_bandi/.env`)

```
RESOLVER_MODALITA=attivo      ← messo il 25/09: prima valeva `ombra` per difetto
                                 e ogni giro risolveva bandi nuovi e buttava il risultato
```

`MONITOR_MODALITA` **non è impostata**, quindi vale `ombra`: il monitor registra le proposte e non
tocca stato né date. È voluto. `MONITOR_GIRI` e `MONITOR_SCENARIO` non sono impostate e i default
(`06:00,18:00`, `bilanciato`) sono quelli giusti.

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

Exit code 0 = tutto bene. Exit 1 con `[ALLARME]` se: nessun monitor riuscito da 24 ore, login
Obiettivo Europa fallito, tetto raggiunto in due giri consecutivi, crediti Firecrawl sotto il 15%,
consumo mensile oltre l'80%, più del 30% di `in_verifica` sui nuovi, schede OE con sezione sotto
l'80%, `controlli_falliti ≥ 5` su più del 2% dei bandi vivi.

```bash
systemctl is-active edunews-bandi-sender
journalctl -u edunews-bandi-sender --since today | grep -E "STEP (resolver|ricontrolli|monitor)"
```

**Cosa deve comparire**: `attivo: True` sul resolver; una riga `STEP ricontrolli`; il monitor solo
alle 06:00 e 18:00 (negli altri giri `SALTATO (giro non previsto)`, che è corretto).

### 3.2 Verifica dell'integrità del contratto (dopo ogni intervento sui bandi)

Sono le promesse fatte a chi legge il database, e vanno controllate **sui dati**, non sui contatori.

```sql
-- nel SQL Editor di Supabase. Tutte in sola lettura.

-- 1. Nessuna fonte ufficiale su un aggregatore. Atteso: 0
select count(*) from bando
 where fonte_ufficiale_host ilike any (array['%obiettivoeuropa%','%fasi.eu%','%europafacile%',
       '%contributiregione%','%finanziamentinews%','%bandi.it%','%infobandi%','%ticonsiglio%']);

-- 2. Nessun evento con la prova su un aggregatore. Atteso: 0
select count(*) from bando_evento where url_prova ilike '%obiettivoeuropa%';

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

-- 5. Nessun evento leggibile senza cursore. Atteso: 0
select count(*) from bando_evento where leggibile and cursore is null;

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

-- 9. Le RPC non sono eseguibili da anon. Atteso: false su tutte
select p.proname, has_function_privilege('anon', p.oid, 'EXECUTE') as anon_puo
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname='public' and p.proname in
       ('bando_fondi','bando_separa','bando_registra_evento','bando_applica_evento',
        'lock_acquisisci','lock_rilascia');

-- 10. Nessun lock orfano: un proprietario che non esiste più tiene fermo tutto.
select nome, proprietario, acquisito_at, scade_at, scade_at > now() as ancora_valido
  from pipeline_lock;
```

**Se la 10 mostra un lock valido da ore e nessun processo sta girando** (`ps aux | grep "m app"`),
è orfano — succede a ogni `systemctl restart` durante un giro. Si rilascia così:

```sql
select public.lock_rilascia('<nome>', '<proprietario>');
```

### 3.3 Verifica sul sito pubblico (quella che conta davvero)

I contatori dicono cosa il codice ha tentato. Solo la pagina dice cosa il lettore vede.

```bash
# nessun link all'aggregatore su un campione di schede
for s in $(curl -s https://edunews24.it/sitemap-bandi/1.xml | grep -oP '(?<=<loc>)[^<]+' | head -30); do
  curl -s --max-time 20 "$s" | grep -ci "obiettivoeuropa" | sed "s|^|$s: |"
done
# atteso: 0 su tutte
```

```bash
# una scheda con fonte ufficiale deve avere il pulsante e la riga della fonte
curl -s https://edunews24.it/bandi/<uno-slug-con-fonte-trovata> \
  | grep -oE "Apri la pagina ufficiale del bando|Consulta il bando sul portale pubblico|Fonte ufficiale[^<]{0,80}"
```

```bash
# una scheda con un evento visibile deve mostrare il box
curl -s https://edunews24.it/bandi/abruzzo-competenze-linguistiche-certificazione-fondo-perduto \
  | grep -ci "aggiornamenti"
# atteso: ≥ 2
```

### 3.4 Verifica dopo ogni modifica al codice

```bash
cd ~/projects/news1
npm run test:py:bandi     # atteso: 1461 test, OK
npm test                  # atteso: 404 test, 0 falliti
npm run test:py           # atteso: 26 test, OK
npx tsc --noEmit -p tsconfig.json   # atteso: 51 errori, tutti preesistenti, 0 nei file dei bandi
```

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

### 3.6 Verifica prima di attivare un tipo di evento

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m app report-ombra \
  --campione 100 --dal <data-inizio-ombra>
```

Il CSV elenca ogni proposta con i gate superati e falliti. **Leggere le citazioni a mano**: sono
frasi che devono esistere nella pagina dell'ente (il gate G1 lo garantisce, ma il senso no).

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

---

## 4. Cosa resta da fare

### 4.1 Decisioni aperte (non sono lavoro arretrato: sono scelte)

**a) Gli altri cinque tipi di evento.** `apertura`, `proroga`, `chiusura`, `sospensione`, `revoca`
sono in ombra. Cambiano quello che il lettore vede come stato del bando. Il monitor li registra a
ogni giro: quando ce ne saranno un centinaio, guardarli e decidere. Attivarli è
`applica-eventi --tipo <tipo> --attivo`, uno per volta.

**b) La soglia di uscita dall'ombra misura la cosa sbagliata.** `report-ombra` calcola
`precisione = ammessi / totale` e pretende 0,95. Ma quel numero dice *quante proposte grezze del
modello passano i gate*, e i gate devono respingerne la maggior parte: con questa formula la soglia
non è raggiungibile nemmeno da un monitor perfetto (misurato: 0,35 su 17 eventi, con i 6 ammessi
tutti corretti). La precisione che decide è *degli eventi ammessi, quanti sono giusti*, e si valuta
a mano. **La formula non è stata cambiata**: abbassare una soglia di sicurezza perché non passa è
il modo sbagliato di superare un esame.

**c) Il terzo segnale del resolver è il limite dei 1 027 `in_verifica`.** Delle quattro strade
previste per il segnale «contenuto», due non hanno mai prodotto niente (`numero d'atto` e
`identificatore`: zero su tutte le righe con una fonte), quindi poggia solo su scadenza e importo.
E **116 bandi non hanno a database né l'una né l'altro**: per loro è irraggiungibile qualunque
pagina si scarichi. Sbloccarli richiede di decidere se due prove di contenuto indipendenti
(scadenza esatta *e* importo coerente) valgano quanto la terna dominio+titolo+contenuto.

**d) IndicePA non è importato.** `domini --import` ha caricato i 109 host delle fonti; il foglio
`enti.xlsx` di IndicePA aggiungerebbe ~23 000 enti (comuni, scuole, università) e si passa con
`--enti PATH`. Utile soprattutto per i bandi di comuni e GAL.

### 4.2 Lavoro tecnico proposto e non fatto

- **Estendere il controllo dei tipi a tutte le tabelle.** `tests/test_eventi.py` confronta il
  payload di `bando_evento` con i tipi reali della tabella: è la guardia che avrebbe evitato due
  giorni di ombra a vuoto. Le stesse insidie possono stare in `bando_link`, `bando_controllo` e
  `bando`. Mezz'ora di lavoro.
- **`salute` non rileva un lock orfano.** Dopo un `systemctl restart` durante un giro, il lock resta
  fino alla scadenza (quattro ore per la pipeline) e blocca tutti i giri successivi. `salute`
  dovrebbe dirlo, e il sender dovrebbe rilasciare all'avvio i lock di cui era proprietario.
- **Nessun tetto di tempo per singolo bando nel resolver.** Su host morti un solo bando ha
  impiegato fino a 247 secondi.
- **`bandiavvisi.regione.lazio.it`** presenta un certificato con la catena incompleta e fallisce
  sempre lo scarico. È un problema dell'ente, non nostro: annotato.

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

Ogni comando che scrive accetta `--dry-run` e `--limit`, e senza `--attivo` non tocca nessuna
colonna pubblica. I comandi lunghi si lanciano con `nohup … &` e un file di log.

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
