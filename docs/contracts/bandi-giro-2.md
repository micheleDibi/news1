# Contratto interno: giro 2 dei bandi (ottobre 2026)

Proprietario: il lead della sessione news1. Gli operatori leggono questo file e basta. Una modifica si chiede con un messaggio che inizia con `CONTRATTO:`.
Branch: `claude/bandi-giro-2`, creato da main (3f0f046). Si fa un commit locale a ogni task verde, con il messaggio in italiano. Niente push.
Il contratto verso BandoFit resta `docs/contratto-db-bandi.md`. Continuano a valere `docs/contracts/bandi-ripresa-ottobre.md` §1 e §2 (regole DB e file SQL), RIPRESA §5 e §7 e CLAUDE.md.

Decisioni di Michele del 30/09, vincolanti:
- **A1**: dopo 7 giorni d'ombra, un'etichetta strutturata di chiusura su un dominio verificante chiude da sola un «in apertura».
- **A2**: senza prova non si chiude niente a tempo.
- **A-ext**: gli «aperto» senza `data_scadenza` rientrano nella stessa verifica.
- **B**: nessuna notifica push. Al suo posto ci sono il sorvegliante e il pannello di BandoFit.
- **Numerazione**: 12 = monitoraggio, 13 = stato_da_verificare.
- **Tutto automatico**: nessuna azione ricorrente a mano.

**Aggiornamento del 30/09 sera: risposte di Michele alle tre decisioni del piano.**
- **Chiusura da etichetta anche per gli «aperto» senza scadenza: SÌ**, con gli stessi limiti di A1:
  - solo lettori precisi per ente, mai il modello;
  - due letture uguali ad almeno 60 h, titolo simile, al massimo 20 chiusure per giro, freno per ente;
  - le chiusure di bandi già chiusi da tempo non compaiono in «Aggiornamenti».
- **Nel pannello NESSUN dato di consumo.** La chiave `consumo` esce dal riepilogo, che ha quindi 11 chiavi di primo
  livello, e dalla busta della 12. I segnali di spesa (`limite_di_spesa`, `consumo_mensile_alto`,
  `credito_ricerca_basso`) restano come codici con `misura: null` e un testo senza numeri; `UNITA_MISURA` per loro vale
  'nessuna'.
- **Gli «aperto» senza scadenza né prova (circa 410, di cui 258 illeggibili): IN STUDIO.** Michele vuole una soluzione
  vera, per questi e per i bandi futuri, non solo un'etichetta.

**Stato delle sezioni:**
- **OPERATIVE SUBITO (percorso B, sorveglianza):**
  - §1;
  - §2.1 (la 12, senza `consumo`);
  - §8 (senza `allarmi_verifica_stato`, che arriva con A);
  - §9 (11 chiavi);
  - §10;
  - §11 per `passi_non_ok`, `registra_avvio_saltato`, il boot saltato dopo un crash e `SystemExit(1)` (NON il passo
    `verifica_stato`);
  - §12 solo per `SORVEGLIA_SERVIZIO_SENDER`;
  - §13 per `sorveglia` e `salute`;
  - §14 per le funzioni del riepilogo e di `misure_salute`;
  - §16 per la §14 del contratto DB;
  - §17 per la parte B.
- **Percorso A: LIBERATO il 30/09 notte con §19** (versione 2 dallo studio sugli aperti senza prova, con le risposte di
  Michele). §2.2, §3, §4, §5, §6, §7, §15 e le parti A delle altre sezioni valgono **con le modifiche di §19**, che
  prevale in caso di differenza.

---

## 1. Regole per tutti

- **DB**
  - Dal Mac si fanno solo GET su PostgREST, con `order=id` e paginazione `_scorri`/`_per_id`.
  - Le chiavi si leggono solo dentro script che non le stampano.
  - Non si chiama mai una RPC di scrittura (`bando_registra_evento`, `bando_applica_evento`, `bando_fondi`, `lock_*`, …), nemmeno in GET.
  - Se l'harness nega il `.env`, non si aggira: si scrive al lead.
- **Dal Mac non si lancia mai**: `monitor`, `risolvi-fonte`, `sorveglia` senza `--dry-run`, `verifica-stato` senza `--dry-run`. `verifica-stato --dry-run` si lancia dal Mac SOLO con `--senza-modello`, che costa 0.
- **Migrazioni**:
  - le scrive `db`, le applica Michele;
  - righe di al massimo 45 caratteri;
  - ogni file passa due volte di fila su un Postgres 17 effimero (`/opt/homebrew/opt/postgresql@17/bin`, porta alta, `unix_socket_directories=''`, avvio e stop nello stesso comando);
  - prima di applicare la 12 e la 13, nel setup effimero va eseguito `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role` (e lo stesso `ON TABLES`), così il test riproduce Supabase.
- **Test**:
  - `npm test` deve chiudere con `# skipped 0`;
  - `npm run test:py:bandi` e `npm run test:py` con import per percorso (`carica_modulo`), senza rete (`httpx.MockTransport`);
  - la suite completa gira una volta per task, a fine task.
  - Niente dipendenze nuove, niente pip, niente npm.
- **Nomi verso BandoFit**. In quello che BandoFit legge (nomi SQL delle funzioni e delle tabelle della 12, chiavi e testi del riepilogo, contratto §14, testo della richiesta) non compaiono mai `edunews`, `news1`, né i nomi dei fornitori (`anthropic`, `claude`, `haiku`, `firecrawl`, `obiettivo`, `indexnow`, `supabase`).
- **Nessuna notifica**: nessuna chiamata di rete in uscita da `sorveglia` oltre a PostgREST del DB bandi, nessun webhook, niente `ALLARMI_WEBHOOK_URL`. Il docstring di `bandi_sender.py` («no Telegram/email per scelta utente») resta e viene CONFERMATO.
- **Perimetro**: ogni file appartiene a un solo task (vedi la lista dei task). Un file fuori dal proprio task si tocca solo dopo un messaggio `CONTRATTO:` e la risposta del lead.

## 2. Migrazioni

### 2.1 Migrazione 12: `backend/sql/bando_v11_12_monitoraggio.sql`, più il rollback (task D2)

Si applica dopo la 11 e prima della 13. Non dipende dalla 07 e non tocca nessun oggetto esistente.

**Tabella `public.monitoraggio_riepilogo`**

| colonna | tipo e vincoli |
|---|---|
| `id` | smallint PK, DEFAULT 1, CHECK (id=1) |
| `calcolato_at` | timestamptz NOT NULL: ora del server, solo informativa |
| `aggiornato_at` | timestamptz NOT NULL DEFAULT now(); lo imposta il trigger BEFORE INSERT OR UPDATE `monitoraggio_riepilogo_ora` con `NEW.aggiornato_at := now()`, cioè l'orologio del DB |
| `intervallo_ritardo` | interval NOT NULL DEFAULT '45 minutes', CHECK fra 15 minuti e 6 ore |
| `versione` | smallint NOT NULL, CHECK (versione=1) |
| `riepilogo` | jsonb NOT NULL, CHECK jsonb_typeof='object', octet_length(riepilogo::text) < 65536 e riepilogo->>'versione'='1' |
| `memoria` | jsonb NOT NULL DEFAULT '{}', CHECK object e octet_length < 16384; la funzione di lettura non la restituisce MAI |

- REVOKE ALL FROM PUBLIC, anon, authenticated.
- GRANT SELECT, INSERT, UPDATE TO service_role.
- RLS attiva, con una sola policy TO service_role.

**Tabella `public.monitoraggio_chiave`**

| colonna | tipo e vincoli |
|---|---|
| `nome` | text PK, CHECK nome ~ '^[a-z0-9_-]{1,32}$' |
| `impronta` | bytea NOT NULL, CHECK length(impronta)=32 |
| `valida_fino` | timestamptz NULL: resta NULL in via ordinaria e si usa solo per chiudere la chiave vecchia durante una rotazione |
| `creata_at` | timestamptz DEFAULT now() |

- RLS attiva senza policy.
- REVOKE ALL FROM PUBLIC, anon, authenticated, service_role.

**Funzione `public.monitoraggio_job_orario() RETURNS jsonb`**
- plpgsql, SECURITY DEFINER, `SET search_path = public, pg_temp`, con la guardia di ruolo copiata dalla 04.
- Legge `cron.job` e `cron.job_run_details` del job `'bandi-transizioni-orarie'`.
- Restituisce `{misurato, ultimo_avvio_at, ultimo_esito: succeeded|failed|non_misurato, ultimo_ok_at, falliti_24h}`. Senza lo schema cron restituisce `{misurato:false}`.
- `REVOKE ALL ... FROM PUBLIC, anon, authenticated`; `GRANT EXECUTE ... TO service_role`.

**Funzione `public.monitoraggio_catalogo(p_chiave text) RETURNS jsonb`**
- plpgsql, VOLATILE (solo per evitare cache e inlining: NON impedisce la GET), SECURITY DEFINER, `SET search_path = public, pg_temp`.
- Ordine delle verifiche:
  1. **Metodo.** Come PRIMA istruzione: `IF coalesce(current_setting('request.method', true), '') <> 'POST' THEN RAISE EXCEPTION 'non autorizzato' USING ERRCODE = '42501'`. Una GET con la chiave giusta dà 42501.
  2. **Chiave.** Con `p_chiave` NULL, di lunghezza fuori da 32..256, oppure senza una riga con `impronta = sha256(convert_to(p_chiave,'UTF8'))` e `valida_fino` NULL o futura, si ha lo stesso RAISE 'non autorizzato' 42501, identico in ogni caso.
  3. **Busta**, costruita con `jsonb_build_object`:
     - `versione: 1`, `generato_at: now()`, `calcolato_at`, `aggiornato_at`;
     - `minuti_dal_calcolo`: floor dei minuti fra now() e aggiornato_at;
     - `in_ritardo`: now() > aggiornato_at + intervallo_ritardo;
     - `orologio_disallineato`: |calcolato_at − aggiornato_at| > 5 minuti;
     - `riepilogo`: `jsonb_build_object` con SOLO le 11 chiavi di primo livello di §9.1 (niente `consumo`), prese una per una da `r.riepilogo`.
  4. **Senza riga**: `riepilogo` null e `in_ritardo` true.
- `REVOKE ALL ... FROM PUBLIC, anon, authenticated`; `GRANT EXECUTE ... TO anon, service_role`.

**Chiusura del file**
- `NOTIFY pgrst, 'reload schema'`.
- **Blocco di verifica** (con RAISE EXCEPTION):
  - anon non ha privilegi sulle due tabelle;
  - `has_function_privilege('anon','public.monitoraggio_job_orario()','EXECUTE')` è false;
  - nessun GRANT ad authenticated;
  - l'insieme delle funzioni eseguibili da anon è {quelle di oggi} ∪ {monitoraggio_catalogo}, con in più, SE esiste, {bando_stato_da_verificare}. Così la 12 si può rieseguire dopo la 13;
  - count(bando) invariato.
- Il blocco di verifica non inserisce chiavi.
- **Rollback**: DROP delle due funzioni, del trigger, della funzione trigger e delle due tabelle. Nient'altro.

**Test `scraper_bandi/tests/test_riepilogo_sql.py`** (guardie sul testo):
- ogni CREATE FUNCTION e CREATE TABLE ha una REVOKE che nomina anon;
- nessun GRANT ad authenticated;
- c'è `request.method`;
- nessuna riga oltre i 45 caratteri;
- nessun segreto;
- nessun nome vietato (§1) negli identificatori;
- le 11 chiavi di primo livello della busta sono estratte dal SQL ed esposte in un helper, che B6 riusa.

**Prova su PG17**, con stub di anon, authenticated, service_role, authenticator e dello schema cron:
- `SET ROLE anon` con `set_config('request.method','POST',true)`:
  - chiave nulla, corta, errata o scaduta → 42501;
  - chiave giusta → versione=1.
- `request.method='GET'` con la chiave giusta → 42501.
- SELECT delle due tabelle come anon → 42501.
- service_role su monitoraggio_chiave → 42501.
- UPDATE che prova a scrivere un aggiornato_at nel passato → il trigger lo riporta a now().
- La sequenza 12, rollback, 12 passa.

### 2.2 Migrazione 13: `backend/sql/bando_v11_13_stato_da_verificare.sql`, più il rollback (task D3)

Si applica dopo la 12. È additiva: nessuna riga di `bando` toccata, `bando_applica_evento` non ridefinita, la 04 non rieseguita.

1. **Guardie iniziali**:
   - la 12 presente (la tabella monitoraggio_riepilogo esiste), altrimenti RAISE «applicare prima la 12»;
   - l'elenco ordinato delle colonne di `bando_pubblico` (information_schema) uguale a quello atteso scritto nel file;
   - `pg_get_viewdef` contiene i predicati chiave della vista attesa (elenco di sottostringhe scritto nel file).

   Se qualcosa non torna, RAISE con un messaggio chiaro.
2. **Colonne nuove su `public.bando_controllo`** (ADD COLUMN IF NOT EXISTS):

   | colonna | tipo |
   |---|---|
   | `stato_letto` | text CHECK IN ('in apertura prossimamente','aperto','chiuso','uscito') |
   | `stato_letto_su` | text |
   | `stato_letto_at` | timestamptz |
   | `stato_letto_url` | text |
   | `stato_letto_citazione` | text |
   | `stato_letto_metodo` | text CHECK IN ('estrattore','modello') |
   | `lettura_stato` | jsonb (§5.8) |
   | `lettura_stato_at` | timestamptz |
   | `prossima_lettura_at` | timestamptz |
   | `letture_stato_nulle` | smallint NOT NULL DEFAULT 0 |
   | `previsto_entro` | date |
   | `termine_indicato` | date |

   - CHECK `bando_controllo_lettura_completa`: stato_letto IS NULL, oppure su, at, url, citazione e metodo sono tutti NOT NULL.
   - Trigger BEFORE INSERT OR UPDATE `bando_controllo_lettura_verificante`: se `stato_letto` non è NULL e `public.bando_dominio_verificante(public.dominio_di(stato_letto_url))` non è true, annulla le sei colonne stato_letto*.
   - Nessun trigger su `bando`.
3. **GRANT SELECT** (stato_letto, stato_letto_su, stato_letto_at, stato_letto_metodo, previsto_entro, termine_indicato) ON bando_controllo TO anon. Servono alla vista, che è security_invoker.
4. **Funzione `public.bando_stato_da_verificare(...)`**
   - LANGUAGE sql, STABLE; richiama `bando_stato_effettivo`.
   - Parametri in quest'ordine: p_stato, p_data_apertura, p_apertura_verificata, p_ora_apertura, p_data_scadenza, p_ora_scadenza (tipi identici a bando_stato_effettivo), p_pubblicato_at timestamptz, p_previsto_entro date, p_termine_indicato date, p_stato_letto text, p_stato_letto_su text, p_stato_letto_at timestamptz, p_stato_letto_metodo text, p_adesso timestamptz DEFAULT now().
   - `REVOKE ALL ... FROM PUBLIC, authenticated`; `GRANT EXECUTE ... TO anon, service_role`.
5. **`CREATE OR REPLACE VIEW public.bando_pubblico`**: ricopiata dall'ultima definizione nei file (05 e successive; D3 dichiara nell'intestazione quale file è la base), con quattro colonne in coda, in quest'ordine:
   - `stato_da_verificare` text;
   - `stato_letto` text, NULL se stato_letto_su ≠ stato_bando;
   - `stato_letto_at` timestamptz, NULL alle stesse condizioni;
   - `termine_indicato` date.
6. **Blocco generato `-- >>> CERTEZZA v1` / `-- <<< CERTEZZA v1`**, da `genera-sql.ts`: una SELECT sui casi di §3 che restituisce le righe discordanti. Esito atteso: 0 righe.
7. **Blocco generato `-- >>> TRANSIZIONI delta 13` / `-- <<< TRANSIZIONI delta 13`**: la sola riga di §4, con `WHERE NOT EXISTS` (stesso schema della 04).
8. **Blocco di verifica**:
   - lista bianca = 24 righe;
   - funzioni eseguibili da anon = {quelle di oggi} ∪ {monitoraggio_catalogo, bando_stato_da_verificare}, ESATTAMENTE;
   - count(bando) invariato;
   - conteggi per stato_effettivo della vista invariati rispetto alla tabella;
   - colonne della vista = quelle di prima più quattro in coda;
   - `NOTIFY pgrst, 'reload schema'`.
9. **Rollback**:
   - DROP VIEW e CREATE VIEW senza le quattro colonne, con gli stessi GRANT e COMMENT;
   - DROP della funzione, del trigger e delle colonne;
   - DELETE della sola riga delta di §4, identificata da (da, a, attore, evento).

   Nient'altro.
10. **La 07** (non applicata) e il suo rollback: la vista che ricreano porta le quattro colonne in coda. La sequenza su PG17 è 01..06, 08..11, 12, 13, poi 07, rollback della 07, rollback della 13, 13, e deve passare.
11. **Test**:
    - `tests/estrazioni/colonne-anon.test.ts` impara la vista dalla 13;
    - `tests/estrazioni/migrazione-13.test.ts` confronta byte per byte i blocchi CERTEZZA e delta con l'output di genera-sql;
    - `scraper_bandi/tests/test_stato_da_verificare_sql.py`:
      - le colonne della 13 coincidono con `db.COLONNE_LETTURA_STATO`;
      - i parametri di `bando_stato_da_verificare` sono nell'ordine di §3;
      - REVOKE da PUBLIC;
      - righe ≤ 45 caratteri.
12. **Casi su PG17**, con le RPC vere della 04 e della 11:
    - lettura con stato_letto_su ≠ stato → ignorata;
    - lettura 'chiuso' su un aperto senza scadenza → 'smentito_dalla_fonte';
    - stato_letto_url su un dominio non verificante → la lettura viene annullata dal trigger;
    - `rettifica` campo=data_scadenza con una data passata, applicata su un aperto senza scadenza → `bando_transizioni_automatiche()` registra `chiusura_automatica`;
    - `data_verificata` con una scadenza passata su un «in apertura» → `chiusura_automatica`;
    - `chiusura` del worker su un «in apertura» → passa la lista bianca;
    - `chiusura` del worker da aperto → passa, già oggi;
    - SET ROLE anon: la SELECT della vista funziona e restituisce le quattro colonne.

## 3. Regola `stato_da_verificare` v1 (fonte unica: sezione `certezza` di `tests/stato-bando/casi.json`)

**Sezione di primo livello `certezza`**:
- `versione: 1`;
- parametri: `{giorni_grazia_pubblicazione: 3, giorni_validita_conferma: 30}`;
- `motivi` (elenco chiuso, 5 valori): `data_apertura_passata`, `smentito_dalla_fonte`, `previsione_scaduta`, `senza_conferma`, `termine_passato`;
- `stati_letti`: in apertura prossimamente, aperto, chiuso, uscito;
- `metodi`: estrattore, modello;
- almeno 60 `casi`, con `sha256` per caso (stesso schema dei 77: U+0000 come separatore, U+0001 per null) e `conteggio_minimo` pari al numero dei casi.

I 77 casi esistenti e le transizioni esistenti restano identici byte per byte.

**Firma**, identica nei tre linguaggi:
- Python `stato_da_verificare(stato, data_apertura, apertura_verificata, ora_apertura, data_scadenza, ora_scadenza, pubblicato_at, previsto_entro, termine_indicato, stato_letto, stato_letto_su, stato_letto_at, stato_letto_metodo, adesso=None)` in `scraper_bandi/app/stato_bando.py`;
- TS `statoDaVerificare({...})` più le costanti `MOTIVI_DA_VERIFICARE`, `GIORNI_GRAZIA_PUBBLICAZIONE` e `GIORNI_VALIDITA_CONFERMA` in `src/lib/stato-bando.ts`, che resta un modulo foglia;
- SQL `bando_stato_da_verificare` (§2.2).

**Definizioni**:
- `oggi` è la data civile di Roma;
- «giorni fa» è la differenza fra date civili di Roma;
- `se` = stato_effettivo(stato, data_apertura, apertura_verificata, ora_apertura, data_scadenza, ora_scadenza, adesso);
- **lettura valida** = stato_letto è uno dei quattro stati letti, stato_letto_su = stato e stato_letto_at non è NULL. Un valore sconosciuto vale NULL.

**Ordine di valutazione** (vince la prima regola che si applica):
- **R0.** se = 'in apertura prossimamente' → ramo I; se = 'aperto' con data_scadenza NULL → ramo A; in tutti gli altri casi → NULL.
- **Ramo I** («in apertura»):
  - **I1.** apertura_verificata true e data_apertura non NULL → NULL.
  - **I2.** data_apertura non NULL e < oggi → `data_apertura_passata`.
  - **I3.** lettura valida con stato_letto ∈ {aperto, chiuso, uscito} → `smentito_dalla_fonte`.
  - **I4.** previsto_entro non NULL e < oggi → `previsione_scaduta`.
  - **I5.** lettura valida 'in apertura prossimamente' con stato_letto_at al massimo 30 giorni fa → NULL.
  - **I6.** pubblicato_at al massimo 3 giorni fa → NULL.
  - **I7.** altrimenti → `senza_conferma`.
- **Ramo A** («aperto» senza scadenza):
  - **A1.** lettura valida con stato_letto ∈ {chiuso, uscito, in apertura prossimamente} → `smentito_dalla_fonte`.
  - **A2.** lettura valida 'aperto' con stato_letto_metodo = 'estrattore' e stato_letto_at al massimo 30 giorni fa → NULL. Solo una conferma strutturata batte il termine: una lettura 'aperto' del modello NON spegne A3.
  - **A3.** termine_indicato non NULL e < oggi → `termine_passato`.
  - **A4.** altrimenti → NULL. Non esiste un motivo debole: IS NULL vuol dire «nessuna prova contraria», in entrambi i rami.

**Casi obbligatori** in `certezza`:
- tutti i rami I1-I7 e A1-A4;
- i confini dei 30 e dei 3 giorni a mezzanotte di Roma;
- stato_letto_su ≠ stato;
- una lettura 'aperto' del modello con il termine passato → termine_passato;
- un aperto CON scadenza → NULL;
- sospeso e revocato → NULL;
- un «in apertura» con l'apertura raggiunta e verificata → NULL, perché stato_effettivo diventa aperto (poi ramo A se non ha scadenza).

**`genera-sql.ts`**:
- `generaBloccoCertezza()`;
- `generaDeltaTransizioni(13)`;
- `generaSeedTransizioni()` emette nella 04 SOLO le transizioni senza il campo `migrazione`, così il blocco della 04 resta byte per byte.

## 4. Lista bianca: una riga nuova (24 in tutto)

`{da:'in apertura prossimamente', a:'chiuso', attore:'worker', evento:'chiusura', migrazione:13, condizione:'la pagina ufficiale dichiara chiuso, scaduto o concluso con etichetta strutturata; gate G1-G9, G7 per doppia lettura strutturata (contratto 6.1)'}`

La condizione va spezzata come le altre nel SQL generato.

- **Python.** La riga si aggiunge in `stato_bando.TRANSIZIONI`.
- **TS.** La stessa riga si aggiunge in `TRANSIZIONI` di stato-bando.ts.
- **Invariante nuovo nel test**: il worker esce da «in apertura» verso chiuso solo con 'chiusura'.
- **Restano verdi**: «nessuna redazione», «pipeline solo da null», «il cron apre solo da in apertura».
- **`eventi.transizione_evento(stato, evento, *, percorso='monitor')`**: restituisce 'chiuso' da «in apertura» SOLO con `percorso='verifica_stato'`. Il monitor resta com'è.

## 5. Passo `verifica-stato` (`scraper_bandi/app/verifica_stato.py`: nucleo puro più I/O iniettato, come `monitoraggio.py`)

### 5.1 Punto d'ingresso
- **Firma**: `esegui_passo(giro: str | None, *, modalita: str | None = None, dry_run: bool = False, senza_modello: bool = False, ids: tuple[int, ...] = ()) -> dict`.
- **Risultato**: `{status: 'ok'|'saltato'|'errore', counters: {...§5.9}, slug_modificati: [...], ids_da_rigenerare: [...]}`. Le chiavi degli slug sono le stesse che `_slug_da_notificare` legge per il monitor.
- **Senza la 13** (colonne assenti, rilevate da `db.controllo`): `status='saltato'`, `counters.motivo_saltato='migrazione_assente'`.
- Non solleva mai verso il sender. Un'eccezione dà `status='errore'`.
- **Protocollo `FonteDati`** e classe concreta `FonteDatiSupabase` stanno nel modulo e richiamano:
  - `db.select_da_verificare()`;
  - `db.select_letture_stato(ids=None, dal=None)`;
  - `db.aggiorna_lettura_stato(bando_id, colonne)`;
  - `db.select_link_delle_fonti`;
  - `eventi.registra_via_rpc`, `db.applica_evento_esito`, `db.rendi_evento_leggibile`.

### 5.2 Candidati
- **Chi entra**: bandi pubblicati non fusi (`bando_master_id` NULL) con stato_effettivo 'in apertura prossimamente', oppure 'aperto' con `data_scadenza` NULL. Nessun filtro su `fonte_ufficiale_stato`. Entrano quelli con `prossima_lettura_at` NULL o ≤ adesso.
- **Priorità** (a parità decide l'id):

  | condizione | priorità |
  |---|---|
  | data_apertura_passata | 90 |
  | termine_passato | 85 |
  | mai letto e leggibile | 80 |
  | seconda lettura in attesa (§5.5, G7e) | 75 |
  | smentito | 70 |
  | previsione_scaduta | 60 |
  | senza_conferma | 50 |
  | aperto leggibile da rinnovare | 45 |
  | rinnovo | 40 |

### 5.3 Pagina da leggere
1. `fonte_ufficiale_url`, se `fonte_ufficiale_stato='trovata'`. **Tipo (i)**.
2. `link_bando`, se il suo host non è un aggregatore ed è `dominio_ufficiale.verificabile` (anche con la fonte 'in_verifica' o 'non_trovata'). È di **tipo (ii) «pagina d'origine»** quando host(link_bando) = host dell'URL della fonte di scraping (tabella `fonte`) e `fonte_id ∉ FONTI_OE`; altrimenti è di **tipo (iv) «solo segnale»**.
3. Una `bando_link` 'pagina_bando' verificabile. **Tipo (iv)**.
4. Altrimenti 'illeggibile', senza fetch: si calcola solo `termine_indicato` (§6.3).

In più:
- **Sorella `/preavvisi/x` → `/avvisi/x`, oppure un `link_collegato`**, sullo stesso host di una pagina (i) o (ii) e con titolo simile. È di **tipo (iii)** e ammette eventi.
- **La pagina di un aggregatore** (per esempio obiettivoeuropa.com) non si legge MAI.
- **Scarico**: si usa lo `Scarico` condiviso, con `svuota(host_morti=False)`, salto degli host con DNS morto, `TETTO_TEMPO_BANDO_S=120` con asyncio.wait_for e almeno 1 s fra due GET sullo stesso host. `stato_letto_url` e l'URL di prova sono `Risposta.url_finale` (§7).

### 5.4 Lettura
- **Estrattore.** Prima `etichette_stato.leggi(html, url_finale, titolo)` (§6).
- **Modello.** Solo se l'estrattore restituisce None, la pagina è di tipo (i), (ii) o (iii), `VERIFICA_STATO_USA_MODELLO=true` e non c'è `--senza-modello`. Il modello è quello già usato dal classificatore del monitor, con le stesse regole di bilancio.
- **Gate sulla lettura del modello**:
  - `citazione_in`;
  - parola di stato con participio compiuto: `esaurit[ae]`, `chius[oa]`, `scadut[oa]`, `sospes[oa]`, `termini (sono) scaduti`, `conclus[oa]`;
  - esclusione delle formule potenziali: `fino a(d) esaurimento`, `in caso di esaurimento`, `potrà essere sospeso|chiuso`;
  - le date vincono sull'etichetta;
  - G10 (niente date presunte).
- **Esiti della lettura**: stato ∈ {in_apertura, aperto, chiuso, uscito, non_decisiva}, oppure `pagina_rimossa` (404 o 410 su due letture di fila, oppure redirect verso la radice dell'host o verso una pagina indice), oppure `errore_rete`.
- **Titolo non simile** su una pagina (ii) → non_decisiva e `forse_non_un_bando=true` in `lettura_stato`. È il caso di regione.lazio.it/documenti.

### 5.5 Gate degli eventi del passo (percorso `verifica_stato`, funzione `eventi.valuta_verifica(proposta, ctx) -> Giudizio`)

Il passo NON usa `valuta()` del monitor. Una proposta è ammessa solo se passa TUTTI questi gate:

| gate | condizione |
|---|---|
| G1 | citazione (etichetta o frase con la data) presente nel testo della pagina (`testo_da_html` + `citazione_in`) |
| G2v | pagina di tipo (i), (ii) o (iii); dominio verificabile e non aggregatore |
| G3v | titolo simile: `fonte_ufficiale.somiglianza_titolo` su `titolo` e `titolo_raw` contro `intestazioni_pagina(html)`, almeno al livello «medio» (`JACCARD_MEDIO`/`COPERTURA_MEDIA`) |
| G5 | direzione, con la logica di `g5_direzione` |
| G6 | parola: chiusura `chius\|scadut\|conclus`; rettifica data_scadenza e data_verificata con le parole di `PAROLE_G6`; apertura con quelle esistenti |
| G7e | doppia lettura strutturata (sotto) |
| G8 | dedup (`g8_dedup`) |
| G9 | `transizione_ammessa(stato riletto dal DB subito prima, a, 'worker')` |
| G10 | nessuna data presunta (`date_validation.e_presunta`) |

**G7e (doppia lettura strutturata).** Serve per ogni evento nato da un estrattore. La lettura attuale e una lettura precedente di `lettura_stato.storia` devono avere:
- stesso estrattore;
- stesso `url_finale` normalizzato (`impronte.normalizza_url`);
- stessa etichetta;
- per le date, stessa data.

Le due letture devono essere distanti almeno 60 ore.

**Letture del modello**:
- non producono MAI `chiusura`, `sospensione`, `riapertura`, `revoca` o `proroga`;
- una data letta dal modello vale solo con `g7_seconda_prova(doppia=True)` invariato.

**Registrazione del gate**: l'esito va nel `p_gate` jsonb come `{percorso:'verifica_stato', superati:[...], falliti:[...], g7:'doppia_lettura_strutturata'|'doppio_modello'}`. `p_metodo`: 'estrattore:<chiave>' oppure 'modello'. Il contratto DB §6.1 dichiara G7e come variante ammessa di G7 per il worker.

### 5.6 Decisioni
Le proposte si fanno sempre. Gli eventi si registrano solo con `VERIFICA_STATO_MODALITA=attivo`.

**Ramo I** («in apertura»):
- (a) Data certa → `data_verificata` con `p_campo` in data_apertura, ora_apertura, data_scadenza o ora_scadenza e `p_in_aggiornamenti=false`.
  - Mai stato_bando, mai data_pubblicazione, mai sovrascrivere una colonna già verificata.
  - G5-dv: un'apertura passata vale solo insieme a una scadenza verificata.
  - Poi il cron apre o chiude.
- (b) Etichetta 'Aperto' con una scadenza futura certa sulla pagina → prima `data_verificata` data_scadenza, poi `apertura`.
- (c) Etichetta con `puo_chiudere` e senza un termine futuro → `chiusura` (riga di §4).
- 'Aperto' senza scadenza e 'uscito' → nessun evento (il segnale è smentito_dalla_fonte).

**Ramo A** («aperto» senza scadenza):
- (d) Termine finale certo, futuro o passato → `rettifica` con `p_campo='data_scadenza'` e `p_valore_dopo {data_scadenza[, ora_scadenza]}`, leggibile.
  - Se la data è passata, chiude il cron (`chiusura_automatica`).
  - NON si usa `data_verificata` sugli aperti, perché BandoFit propaga le date da proroga e rettifica (R6).
- (e) Etichetta con `puo_chiudere` e senza un termine futuro sulla pagina → `chiusura` (aperto → chiuso, già in lista bianca). `p_data_evento` è la data di chiusura letta, se c'è ed è ≤ oggi, altrimenti NULL. `data_scadenza` resta intatta.
- Un 'Aperto' strutturato senza termine → nessun evento: scrive solo la conferma.

**`in_aggiornamenti`** (per chiusura e rettifica): vale `true` solo se la notizia è nuova, cioè se valgono tutte e due le condizioni:
- `lettura_stato.storia` contiene una lettura strutturata 'aperto' (o 'in apertura') dello stesso estrattore, al massimo 30 giorni prima della prima lettura di chiusura;
- l'eventuale data letta (o il termine) è ≥ oggi − 14.

Negli altri casi vale `false`: è una correzione, leggibile per lo stato ma fuori dal box Aggiornamenti. La prima passata sui 44 'Chiuso' di LazioEuropa produce quindi solo correzioni.

**Registrazione in attivo**: `registra_via_rpc` → se `nuovo`, `applica_evento_esito` → `rendi_evento_leggibile`. Se la RPC fallisce, l'evento NON si scrive: non c'è ripiego sull'INSERT d'ombra, si conta `eventi_non_scritti` e il passo va avanti.

**Freni**:
- **Tetto**: al massimo `VERIFICA_STATO_MAX_CHIUSURE` (20) eventi 'chiusura' per giro. Gli altri restano in coda (prossima_lettura_at = domani) e si contano in `chiusure_oltre_tetto`.
- **Freno per host**, per coppia (host, estrattore), su una finestra mobile di 7 giorni: `passaggi` è il numero di letture 'aperto' → 'chiuso' dello stesso bando; `letture` è il numero di letture strutturate dell'estrattore.
  - Scatta con almeno 5 passaggi e passaggi/letture > 0,5.
  - Le chiusure di quell'host si trattengono (prossima_lettura_at = domani), contate in `trattenute_per_freno`.
  - Si sblocca da solo quando la finestra torna sotto soglia.
  - La prima passata non ha passaggi.
- **Prosa**: gli eventi applicati del passo (rettifica, data_verificata, apertura, chiusura) finiscono in `ids_da_rigenerare`. Il sender li passa a `_rigenerazione_di_produzione`. Se la riscrittura fallisce: contatore `prosa_non_riscritta` e niente IndexNow per quello slug. IndexNow parte solo per gli eventi applicati, mai per un cambio del segnale.

### 5.7 Scritture: ombra e attivo
**Sempre** (ombra e attivo), con `db.aggiorna_lettura_stato`:
- `lettura_stato`, `lettura_stato_at`, `prossima_lettura_at`, `letture_stato_nulle`, `previsto_entro`, `termine_indicato`;
- `termine_indicato` e `previsto_entro` si scrivono solo quando cambiano.

**SOLO in attivo** si scrivono le sei colonne `stato_letto*`. Così in ombra i badge del sito vengono solo da date e testo, mai da una lettura non ancora validata.

**Mai**: `prossimo_controllo_at`, `controlli_falliti`, `testo_norm`, impronte, `_sospendi_fonte` e righe di `bando`.

**Letture che non si scrivono in stato_letto**:
- una lettura non_decisiva incrementa `letture_stato_nulle` e non cancella la lettura precedente;
- `errore_rete` e `pagina_rimossa` non toccano stato_letto*.

### 5.8 Forma di `lettura_stato` (jsonb, interno)
`{pagina: 'i'|'ii'|'iii'|'iv'|'illeggibile', estrattore, etichetta, stato, puo_chiudere, solo_segnale, termine_finale: {data, ora, citazione}|null, esito: 'letta'|'non_decisiva'|'pagina_rimossa'|'errore_rete'|'illeggibile', forse_non_un_bando, proposta: {tipo, campo, valore_dopo, gate, trattenuta: null|'tetto'|'freno'|'ombra'}|null, storia: [≤5 {at, estrattore, url, etichetta, stato, date}]}`

### 5.9 Cadenza, tetti e contatori
**Cadenza** (`prossima_lettura_at`):

| situazione | intervallo |
|---|---|
| segnalato, smentito o termine passato | 3 giorni |
| seconda lettura per G7e in attesa | 3 giorni |
| aperto confermato dall'estrattore | 3 giorni se created_at ≤ 60 giorni fa o se la pagina ha una finestra, altrimenti 14 giorni |
| «in apertura» confermato | 14 giorni |
| 3 letture non decisive di fila | 14 giorni |
| etichetta solo segnale identica per 3 letture | 14 giorni (torna a 3 appena l'etichetta cambia) |
| pagina_rimossa | 14 giorni |
| errore di rete | 1 giorno |
| illeggibile | 14 giorni (solo termine_indicato, senza fetch) |

**Tetti**: `VERIFICA_STATO_TETTO_LETTURE` (40) letture e `VERIFICA_STATO_TETTO_S` (900) secondi per giro.

**Contatori** (`counters`, dentro `steps.verifica_stato` della riga 'pipeline'):
- `modalita`, `candidati`, `letti`, `illeggibili`;
- `confermati`, `smentiti`, `non_decisivi`;
- `pagine_rimosse`, `errori_rete`, `host_irraggiungibili`, `termini_calcolati`;
- `proposte_per_tipo {tipo:n}`, `applicati_per_tipo {tipo:n}`;
- `trattenute_per_freno {estrattore:n}`, `chiusure_oltre_tetto`;
- `esiti_per_estrattore {estrattore:{letture, esiti}}`;
- `letture_non_verificanti`, `forse_non_bandi`;
- `eventi_non_scritti`, `prosa_non_riscritta`;
- `interrotto_per_tetto_tempo`, `costo_usd`, `crediti`, `motivo_saltato`.

**Verità nota**. `VERITA_NOTA: dict[int, str]` nel modulo, confrontata da `report-verifica-stato --verita`. Esiti attesi con `--senza-modello` (verità al 30/09):
- **ramo A**:
  - chiuso con proposta 'chiusura': 2387, 18344, 18444, 2919, 18400;
  - smentito senza proposta: 18337, 18357 (Valutazione);
  - confermati: 17903, 18454;
  - rettifica data_scadenza: 2339 (2027-01-19) e 256211 (2026-09-25, poi il cron chiude);
  - non_decisiva: 18315, 18387, 18423 (Pubblicazione); 3042 e 110821 senza modello;
  - non_decisiva con forse_non_un_bando: 2448, 2449, 2621, 2622;
- **ramo I**: 2971 uscito; i 4 'concluso' del Piemonte chiusi; 106753, 2375, 270806 con data_verificata della scadenza passata; 1072674 e 1072686 aperti; 17978 chiuso; 577475 dalla sorella; 1261858 e 327381 confermati; 10258 non decisivo.
- **Illeggibili, senza fetch**: gli OE con il solo URL dell'aggregatore e quelli senza URL.

D1 rimisura. Se un id nel frattempo è cambiato, il lead aggiorna la tabella.

## 6. Estrattori, date e testo (`etichette_stato.py` e `date_validation.py`)

### 6.1 `etichette_stato.leggi(html, url_finale, titolo) -> Lettura | None` (puro, HTML grezzo)
- **`Lettura`** (frozen): `estrattore`, `stato` ∈ {in_apertura, aperto, chiuso, uscito, non_decisiva}, `etichetta` (testo grezzo), `puo_chiudere`, `solo_segnale`, `date: tuple[(ruolo, data, ora, citazione, presunta)]`, `termine_finale: (data, ora, citazione) | None`, `finestra: bool`, `citazione_stato`, `link_collegato`.
- **Chiavi** (elenco chiuso `ESTRATTORI`, usate anche nei codici di salute): `piemonte`, `lazioeuropa`, `lombardia`, `calabria`, `calabria_rc`, `puglia`, `formazionelavoro_er`, `fesr_er`, `pninclusione`.

| chiave | host | etichetta → stato |
|---|---|---|
| piemonte | bandi.regione.piemonte.it | dl.stato-* / field-stato: pre-informazione → in_apertura (non_decisiva se la «Data presunta di apertura» è passata); aperto → aperto; scaduto → chiuso, può chiudere; concluso → chiuso, può chiudere; attuato → uscito con link_collegato sullo stesso host |
| lazioeuropa | www.lazioeuropa.it | div.single-bandi-status: Prossima Apertura → in_apertura; Aperto → aperto; Chiuso → chiuso, può chiudere; finestra «a partire dalle ore … del …» / «entro le ore … del …» |
| lombardia | bandi.regione.lombardia.it | span.chip-label: Aperto → aperto; Chiuso → chiuso, può chiudere; «Scade il: gg/mm/aaaa, ore hh:mm» → termine_finale |
| calabria | calabriaeuropa.regione.calabria.it | cem-btn-*: Aperto → aperto; Conclusione → chiuso, può chiudere; Valutazione → chiuso SOLO SEGNALE; Pubblicazione e Pre-informazione → non_decisiva |
| calabria_rc | stesso host, secondo template | #rc-status: Pubblicata → non_decisiva; il resto → None |
| puglia | regione.puglia.it | «Prossimo avviso» con data presunta → in_apertura non_decisiva |
| formazionelavoro_er | formazionelavoro.regione.emilia-romagna.it | «Bando Aperto» → aperto; termine_finale = la data più tarda con «entro e non oltre» o «termine ultimo» |
| fesr_er | fesr.regione.emilia-romagna.it | etichetta IGNORATA; solo la finestra con le date |
| pninclusione | pninclusione21-27.lavoro.gov.it | `sorella_preavviso(url)`: /preavvisi/x → /avvisi/x |

**Regole comuni**:
- 'Sospensione' o 'sospeso' strutturato → chiuso SOLO SEGNALE: mai `puo_chiudere`, mai una proposta 'sospensione'.
- **Le date vincono**: un termine finale certo e già passato → stato chiuso, `puo_chiudere=false` (la strada è la rettifica). Con più finestre conta solo il termine FINALE. Finestre periodiche senza termine finale → non_decisiva.

**Altre funzioni pure**: `sorella_preavviso(url)` e `periodo_indicativo(raw_data) -> date | None`, che restituisce None se il formato è incerto.

**Fixture** in `scraper_bandi/tests/fixtures/etichette_stato/`: pagine reali senza dati personali, una per etichetta. Comprendono: 2387, 18344, 18454, 17903, 2339, 256211, 3042, 110821; Calabria Valutazione e Pubblicazione; calabria_18089 (#rc-status); Piemonte pre-informazione, attuato e concluso; LazioEuropa Prossima Apertura; Puglia; pninclusione /avvisi/ e /preavvisi/.

### 6.2 `date_validation.py`
- `e_presunta(citazione) -> bool`: `presunt|previst|indicativ|orientativ|stimat|trimestre|semestre`. `validate_date_candidate` la usa per respingere le date presunte.
- `estrai_finestra(testo) -> list[Finestra(inizio, ora_inizio, fine, ora_fine, citazione)]` e `ora_nella_citazione(citazione, data, ruolo)`. Catturano l'ora senza cambiare `_COSTRUTTO_RE`.
- `termine_nel_testo(titolo, descrizione_breve) -> date | None`: costruita SOPRA `estrai_date_con_ruolo` (solo il ruolo 'scadenza'), `validate_date_candidate` ed `e_presunta`, senza una grammatica nuova.
  - Vale solo se nella stessa frase c'è `domand|candidatur|presentaz|invi|istanz|iscrizion`.
  - Scarta le frasi con `fier|event|manifestazion|spes[ae] ammissibil|realizzazion`.
  - Con più date prende la più tarda.
  - Non è MAI una prova: non produce eventi.
  - Casi negativi obbligatori: 18346, 1009878, 1257967, 1257980.
  - Casi positivi: le date finali passate e future elencate nei dati del 30/09.

### 6.3 Ingresso (preprocess)
- `preprocessor` passa `provenienza=<host di link_bando>` a `validate_date_candidate`.
- `bando_preprocess_runner._build_update`:
  - scrive `ora_apertura` e `ora_scadenza` quando la citazione le contiene;
  - se `data_scadenza` resta NULL e il testo della pagina ha una finestra con una fine certa (non presunta, con un verbo di presentazione, ≥ data_pubblicazione), scrive `data_scadenza` e `ora_scadenza` da `estrai_finestra`.
- I prompt NON cambiano. Nessun rifiuto all'ingresso.

## 7. `scarico.py`: URL finale
- `Risposta` riceve il campo `url_finale: str` (default = url). È additivo: resolver e monitor continuano a leggere `Risposta.url`.
- Parametro nuovo `redirect: 'tutti' | 'stesso_host'` (default 'tutti', il comportamento di oggi). Con 'stesso_host' un redirect verso un altro host si ferma e restituisce la risposta 3xx, con `url_finale` uguale all'ultimo URL sullo stesso host.
- Il passo verifica-stato usa 'stesso_host'.

## 8. Salute: codici stabili (`telemetria.py`)

- **`Voce(codice, livello, testo_cli, misura)`** (frozen) e `Salute.voci`.
  - Ogni ramo passa da `_voce(...)`, che scrive in `allarmi`/`avvisi` lo STESSO testo di oggi: CLI, `--json` ed exit code non cambiano, e `come_dizionario()` aggiunge solo `voci`.
  - Il nome `__main__._stato_salute` resta, perché test_tipi_attivi lo patcha.
- **`CODICI_SALUTE`** è un elenco chiuso. La forma è `[a-z_]+`, con un suffisso facoltativo `:[a-z0-9_]{1,32}` preso da una lista chiusa per prefisso. Un codice fuori elenco fa fallire i test.
- **Rami di oggi**:
  - codici (livello di oggi): `monitor_fermo`, `misure_non_disponibili`, `ingresso_fermo`, `classificazione_non_disponibile`, `accesso_fonte_riservata`, `limite_di_spesa`, `credito_ricerca_basso`, `consumo_mensile_alto`, `fonti_da_verificare`, `controlli_non_riusciti`, `scorta_piano_bassa`, `modello_fuori_listino`, `non_misurato`;
  - codici con suffisso: `lavorazione_lunga:<giro|controllo_pagine|ricerca_fonti|altro>`, `lavorazione_orfana:<idem>`, `configurazione:<modalita|tipi_attivi|giri|indicizzazione|verifica_stato>`;
  - i due rami di MONITOR_TIPI_ATTIVI del giro 1: chiave IndexNow assente → `configurazione:indicizzazione`; valori ignorati → `configurazione:tipi_attivi`;
  - un ramo di oggi che non rientra nell'elenco → messaggio `CONTRATTO:`.
- **Rami nuovi** (puri, soglie come costanti del modulo):

  | codice | livello | quando |
  |---|---|---|
  | `produttore_fermo` | allarme | nessuna riga 'pipeline' con giro in 00/06/12/18 conclusa da 7 h, SALVO che il lock del giro sia fresco e acquisito dopo l'ultima ora di schedulazione passata; comunque allarme dopo 11 h (7 + LOCK_TTL) |
  | `riavvii_ripetuti` | allarme | almeno 3 righe giro='boot' in 6 h (qualunque esito, comprese quelle `riavvio_dopo_crash`), OPPURE NRestarts salito di almeno 2 nella serie in memoria delle ultime 6 h |
  | `servizio_non_attivo` | allarme | ActiveState failed o inactive, oppure activating con SubState auto-restart; se non misurabile va in non_misurati 'servizio' |
  | `passo_degradato:<estrazione\|arricchimento\|redazione>` | allarme | dall'ultima riga 'pipeline' non saltata: preprocess errors == processed_total > 0; enrich enriched_total > 0 con enriched_db_ok == 0; seo (selected − doppioni_oe) > 0 con payload_ok == 0 |
  | `fermi_in_lavorazione` | avviso | bandi in processed o enriched con created_at più vecchio di 13 h (limite noto: una riga rimessa in lavorazione da un comando per id conta subito) |
  | `ingresso_guasto` | allarme | fonti_errors = fonti tentate (chiavi confermate da D1) |
  | `accesso_fonte_riservata` | allarme | una fonte di FONTI_OE in `fonti_in_errore` nelle ultime 2 righe 'pipeline' non saltate |
  | `eventi_non_applicati` | allarme | valore > 0 nell'ultimo monitor |
  | `eventi_non_scritti` | allarme | valore > 0 nell'ultimo monitor |
  | `passi_ripetuti_non_ok` | allarme | lo stesso passo in `passi_non_ok` in 2 righe consecutive |
  | `job_orario` | allarme | nessun 'succeeded' da 3 h, oppure almeno 2 fallimenti in 24 h |
  | `verifica_stato_ferma` | allarme | nessuna riga 'pipeline' con `steps.verifica_stato.status='ok'` in 26 h; se lo status è 'saltato' per migrazione_assente, va in non_misurati 'da_verificare' |
  | `leggibile_non_letto` | avviso | letture_scadute > 0 (lettura_stato.pagina ≠ 'illeggibile' e lettura_stato_at più vecchia di 16 giorni, su un candidato) |
  | `lettura_non_verificante` | avviso | letture_non_verificanti > 0 nell'ultimo giro |
  | `estrattore_muto:<chiave>` | allarme | in 7 giorni almeno 5 letture e 0 esiti per quell'estrattore |
  | `freno_chiusure:<chiave>` | avviso | trattenute_per_freno > 0 nell'ultimo giro |
  | `prosa_non_riscritta` | avviso | contatore > 0 (monitor o verifica) |
  | `riepilogo_non_valido` | allarme | lo scrive solo sorveglia |

  `allarmi_verifica_stato(stato) -> list[Voce]` è la funzione pura per gli ultimi sei codici.
- **Campi nuovi di `Stato`**, tutti con default None così il chiamante di oggi non cambia: `ultime_pipeline`, `ultimi_monitor`, `lock`, `fermi_in_lavorazione`, `ultimo_bando_nuovo_at`, `job_orario`, `servizio {active_state, sub_state, n_restarts}`, `memoria`, `da_verificare`, `letture_scadute`, `verifica_7g`.
- **`bando_runner.py`**: contatore `fonti_in_errore`, la lista dei soli fonte_id interi, riempita dove oggi si incrementa fonti_errors.

## 9. Riepilogo neutro v1 (`riepilogo_salute.py`, puro, sola stdlib)

### 9.1 Schema (`SCHEMA_V1` più `valida_v1(d) -> list[str]` errori)
Le 11 chiavi di primo livello (senza `consumo`, decisione del 30/09 sera), le stesse che la 12 seleziona, più `versione:1` e `calcolato_at`.

| chiave | forma |
|---|---|
| `stato` | ok \| attenzione \| guasto |
| `segnali` | ≤40 `{codice, livello: allarme\|avviso, testo, dal, misura}` |
| `non_misurati` | sottoinsieme di [servizio, job_orario, accesso_fonte_riservata, credito_ricerca, schede_con_sezione, da_verificare] |
| `produttore` | `{ultimo_giro_at, ore_dall_ultimo_giro, giri_24h, riavvii_24h, servizio: attivo\|non_attivo\|non_misurato}` |
| `giri` | ≤20 `{id, giro: 00\|06\|12\|18\|avvio\|manuale, avviato_at, concluso_at, durata_min, esito, interrotto_per_tetto, passi_non_ok: [nomi neutri]}`; esito ∈ enum di `esito_da_contatori` |
| `controlli` | ≤10 `{avviato_at, esito, classificazioni, classificazioni_fallite, eventi_non_applicati}` |
| `lavorazioni` | ≤10 `{nome: giro\|controllo_pagine\|ricerca_fonti\|altro, da_min, ttl_min, stato: regolare\|lunga\|probabile_orfana}` |
| `ingresso` | `{fermi_in_ingresso, fermi_in_lavorazione, ultimo_bando_nuovo_at}` |
| `eventi` | `{ammessi_non_applicati, proposte_7g, in_attesa_pubblicazione}` |
| `da_verificare` | null (prima della 13) \| `{in_apertura: {motivo:n}, aperto: {motivo:n}, proposte_in_ombra_per_tipo: {tipo:n}, chiusure_applicate_7g, host_frenati, pagine_rimosse, forse_non_bandi}` |
| `job_orario` | `{ultimo_avvio_at, ultimo_esito: succeeded\|failed\|non_misurato, ultimo_ok_at, falliti_24h}` |

Regole di contenuto:
- **Testo**: le stringhe vengono SOLO da un enum, da ISO 8601 UTC o da `TESTI_NEUTRI`.
- **Esclusi**: proprietario, PID, host, URL, elenchi di host, testi d'eccezione, `motivo` e `note` di pipeline_run, titoli, slug, dollari e crediti.
- **Stato**: guasto se c'è almeno un allarme, attenzione se c'è almeno un avviso, altrimenti ok. I non_misurati non cambiano lo stato.

### 9.2 Testi e misure
- **`TESTI_NEUTRI: dict[codice_senza_suffisso → modello]`**: frasi italiane fisse con i soli segnaposti `{n}`, `{quota}`, `{ore}`, `{minuti}`. Le chiavi coincidono ESATTAMENTE con i prefissi di CODICI_SALUTE (test). Esempio: `produttore_fermo`: «Nessun giro completato da {ore} ore.».
- **`testo_neutro(s) -> bool`**: rifiuta URL, `://`, `@`, `/`, `[A-Z_]{4,}`, `\w+\.[a-z]{2,}` e i nomi di §1. Rifiuta anche `systemd`, `bandi_pipeline` e `edunews`.
- **`UNITA_MISURA[codice]`** ∈ {quota, conteggio, ore, minuti, nessuna}.
  - `valida_v1` rifiuta una misura con unità 'nessuna' e una quota fuori da 0..1.
  - limite_di_spesa, credito_ricerca_basso e consumo_mensile_alto hanno 'nessuna' (niente numeri di spesa nel pannello).
  - Test: una salute con 123,45 $ spesi produce un JSON che non contiene 123.45.
- **`NOMI_PASSI_NEUTRI`**: discover → ingresso, scrape → lettura, preprocess → estrazione, enrich → arricchimento, resolver → ricerca_fonti, seo → redazione, monitor → controllo_pagine, ricontrolli → ricontrolli, verifica_stato → verifica_stato; un nome sconosciuto diventa altro.
- **`riepilogo_pannello(salute, misure, adesso) -> dict`**. Se `valida_v1` fallisce, sorveglia scrive il riepilogo minimo `{versione:1, calcolato_at, stato:'guasto', segnali:[{codice:'riepilogo_non_valido', livello:'allarme', testo, dal, misura:null}], …chiavi vuote}` e il dettaglio va solo nel journal, passato da `redigi`.
- Un test legge le 11 chiavi dal SQL della 12 (helper di D2) e le confronta con SCHEMA_V1.

## 10. `sorveglia` (`sorveglianza.py`, impuro)
- **`fotografa()`** è il corpo di `__main__._stato_salute`, spostato qui; `_stato_salute` la richiama. In più legge:
  - `stato_servizio()`: `systemctl show <SORVEGLIA_SERVIZIO_SENDER> -p ActiveState,SubState,NRestarts`, timeout 5 s, None sul Mac o in caso di errore;
  - la memoria.
- **`esegui(dry_run)`**, in quest'ordine:
  1. `db.leggi_memoria_riepilogo()`;
  2. fotografa;
  3. `riepilogo_pannello`;
  4. `valida_v1`;
  5. `db.scrivi_riepilogo_monitoraggio({calcolato_at, intervallo_ritardo:'45 minutes', versione:1, riepilogo, memoria})`, un upsert id=1.
- **Memoria**: `{nrestarts: [[iso, n]…] delle ultime 6 h, ≤30 voci; dal: {codice: iso}}`. Se la lettura fallisce: dal = adesso, delta non misurato, nessun errore.
- **Exit code**: 0 anche con allarmi; 1 su un'eccezione interna o se l'upsert fallisce. Dopo 45' il pannello mostra in_ritardo.
- **`--dry-run`**: legge anche la memoria, stampa il JSON validato e i codici e NON scrive.
- **Senza la 12**: un warning, exit 0 e niente upsert.
- **Nessun file di stato**: niente StateDirectory, niente flock.
- **Unit di esempio** in `scraper_bandi/deploy/`, con percorsi assoluti e `<UTENTE>`:
  - service: Type=oneshot, WorkingDirectory `.../scraper_bandi`, `Environment=PYTHONDONTWRITEBYTECODE=1`, `ExecStart=.../.venv/bin/python -m app sorveglia`, TimeoutStartSec=300, Nice=10;
  - timer: `OnCalendar=*:05,20,35,50`, Persistent=true, AccuracySec=30s;
  - drop-in del sender (`edunews-bandi-sender-riavvio.conf`): `[Unit] StartLimitIntervalSec=0`, `[Service] Restart=on-failure`, `RestartSec=20min`.

## 11. Sender e pipeline (`backend/app`)
- **`bandi_pipeline`**:
  - passo `verifica_stato` DOPO il monitor, in ogni giro compreso 'boot', con `_passo_se_esiste` e dentro il lock `bandi_pipeline@pid` già preso. Nessun lock nuovo, e `lock_orfani.py` non si tocca;
  - `ids_da_rigenerare` passa a `_rigenerazione_di_produzione` e gli slug a `_slug_da_notificare` (§5.6).
- **`_registra`**: aggiunge ai contatori della riga 'pipeline' `passi_non_ok`, la lista ordinata dei nomi VERI degli step con status diverso da ok, senza testo. Non solleva mai.
- **`registra_avvio_saltato(motivo='riavvio_dopo_crash')`**, nuova: scrive una riga pipeline_run con giro='boot', l'esito che `esito_da_contatori(saltato_per_lock=True)` restituisce e contatori `{riavvio_dopo_crash: 1}`. Non solleva mai.
- **`bandi_sender.__main__`**: se `rilascia_lock_orfani()` restituisce fra i `rilasciati` il lock del giro, cioè il processo precedente è morto a metà, il giro di boot NON parte. Al suo posto: `registra_avvio_saltato()`, poi lo scheduler. Dopo `logger.exception('[bandi_sender] Errore fatale ...')` va `raise SystemExit(1)` (copre solo gli errori dello scheduler). Il docstring resta.

## 12. Variabili d'ambiente (`scraper_bandi/.env`; in `.env.example` solo i nomi)
| variabile | default | note |
|---|---|---|
| `VERIFICA_STATO_MODALITA` | ombra | ombra \| attivo; un valore sconosciuto vale ombra e genera `configurazione:verifica_stato` |
| `VERIFICA_STATO_TETTO_LETTURE` | 40 | intero da 1 a 200 |
| `VERIFICA_STATO_TETTO_S` | 900 | secondi, da 60 a 1800 |
| `VERIFICA_STATO_MAX_CHIUSURE` | 20 | da 0 a 50 |
| `VERIFICA_STATO_USA_MODELLO` | true | |
| `SORVEGLIA_SERVIZIO_SENDER` | edunews-bandi-sender | resta sul server, mai nel riepilogo |

Il modello è `_scelta_env`, come `MONITOR_MODALITA`. `MONITOR_TIPI_ATTIVI` e `TIPI_PROPONIBILI` non cambiano.

## 13. Comandi CLI (`python -m app ...`)
- **`verifica-stato --dry-run [--ids 1,2] [--senza-modello] [--limit N]`**: senza `--dry-run` esce con 2. Non scrive, non prende lock, non scrive pipeline_run. Stampa le proposte e i gate.
- **`report-verifica-stato [--json] [--ramo in_apertura|aperto] [--verita]`**: sola lettura. Per bando mostra id, stato_effettivo, motivo, pagina, metodo, estrattore, etichetta, termine_indicato, proposta, trattenuta e forse_non_un_bando. `--verita` stampa `DIFFORME` per ogni id di VERITA_NOTA diverso dall'atteso e chiude con `difformi: N`.
- **`sorveglia [--dry-run]`**: vedi §10.
- **`salute`**: invariato, in più stampa i codici.
- `test_cli_argv`: `_COMMANDS` comprende i tre comandi nuovi.

## 14. Funzioni `db.py` (nomi fissi)
**Lettura e scrittura della verifica**:
- `COLONNE_LETTURA_STATO`: la tupla delle 12 colonne di §2.2 punto 2;
- `select_da_verificare() -> list[dict]`: `_scorri` con `order('id')`; colonne del bando, `raw_data`, `created_at`, `pubblicato_at`, `fonte_id`, la fonte ufficiale, `link_bando`, `bando_master_id`, e l'host della fonte di scraping da `fonte`;
- `select_letture_stato(ids=None, dal=None)`: `_per_id` o `_scorri`;
- `aggiorna_lettura_stato(bando_id, colonne) -> bool`: scrive solo le chiavi di COLONNE_LETTURA_STATO presenti nello schema (`Controllo`) e restituisce False se mancano tutte.

**Misure per salute e sorveglia** (solo GET, con `count=exact` per i conteggi). `misure_salute()` aggiunge:
- `ultime_pipeline`: 20 righe con id, giro, avviato_at, concluso_at, esito, interrotto_per_tetto e i soli contatori mirati di §8;
- `ultimi_monitor` con eventi_non_applicati ed eventi_non_scritti;
- `lock` con acquisito_at e scade_at;
- `fermi_in_lavorazione`, `ultimo_bando_nuovo_at`;
- i conteggi eventi: `proposte_7g`, `in_attesa_pubblicazione`, `ammessi_non_applicati`;
- `da_verificare`, dalla vista con la service key: conteggi per ramo e motivo, oppure None prima della 13;
- `letture_scadute`;
- `verifica_7g`: `esiti_per_estrattore` sommati sulle righe dei 7 giorni.

**Funzioni del monitoraggio**:
- `job_orario()`: rpc `monitoraggio_job_orario`, None se assente;
- `leggi_memoria_riepilogo() -> dict | None`;
- `scrivi_riepilogo_monitoraggio(riga) -> bool`: upsert id=1; senza tabella dà un warning e restituisce False;
- `COLONNE_RIEPILOGO`.

## 15. Sito e API v1
- **`supabase-bandi.ts`** chiede `stato_da_verificare`, `stato_letto`, `stato_letto_at` e `termine_indicato` SOLO alla vista (`COLONNE_DETTAGLIO_VISTA` e lista). Se la fonte è la tabella, calcola `statoDaVerificare` con lettura e termine NULL.
- **Badge (`aspetto.ts`, card e scheda)**:
  - «In apertura · da verificare» per ogni motivo del ramo I, senza conto alla rovescia;
  - «Aperto · da verificare» per smentito_dalla_fonte e termine_passato;
  - altrimenti il badge di oggi.
- **Sottotesti (`testi-stato.ts`, per coppia stato e motivo)**:

  | stato | motivo | sottotesto |
  |---|---|---|
  | in apertura | data_apertura_passata | il testo di oggi |
  | in apertura | smentito | «La pagina ufficiale non lo indica più come in arrivo: lo stato è in verifica.» |
  | in apertura | previsione_scaduta | «Il periodo di apertura previsto dal calendario è passato senza un avviso pubblicato.» |
  | in apertura | senza_conferma | «L'apertura è annunciata ma non è confermata sulla fonte ufficiale: verifica sul sito dell'ente.» |
  | aperto | smentito | «La pagina ufficiale dell'ente non lo indica più come aperto: verifica prima di presentare domanda.» |
  | aperto | termine_passato | «Il testo del bando indica un termine di presentazione che sembra già passato, non confermato dalla fonte: verifica sul sito dell'ente.» |

  Aperto senza scadenza con motivo NULL, solo nella scheda:
  - con stato_letto 'aperto' al massimo 30 giorni fa: «Sportello aperto: la pagina ufficiale lo indicava ancora aperto il <data>.»;
  - con termine_indicato ≥ oggi: «Il testo del bando indica come termine il <data>, non ancora verificato sulla pagina ufficiale.»;
  - altrimenti il testo di oggi, secondo la decisione 1.
- **Contatori**: l'hero degli «in apertura» mostra anche «di cui N da verificare» (`corpus.ts`, `perStato`). Il contatore degli aperti, i filtri, JSON-LD, sitemap e pagine filtro NON cambiano. Il frammento di `/api/lista` resta unico.
- **API v1**: campo additivo `stato_da_verificare`, enum dei 5 motivi oppure null, in colonne, mappa, openapi, documentazione e docs/api-v1.md, validato da contratto.test.ts.
- **Deploy**: solo dopo la 13, altrimenti la select dà 42703.

## 16. Documenti
**`docs/contratto-db-bandi.md`** (D4):
- §1.6: le due eccezioni nuove;
- §2 glossario;
- §3: le quattro colonne della vista;
- §4 «Certezza dello stato»: la regola di §3; per BandoFit, uno stato è certo SOLO con stato_da_verificare IS NULL;
- §6.1:
  - G7e come variante di G7 per il worker;
  - data_verificata prodotto dal worker;
  - rettifica data_scadenza sugli aperti;
  - chiusura da «in apertura»;
  - `in_aggiornamenti=false` per le correzioni;
- R6: le date si propagano da proroga, rettifica E data_verificata con campo data_scadenza;
- §10.2: le migrazioni 12 e 13;
- §11;
- §14 nuova «Interfaccia di monitoraggio», in forma neutra, copiabile da BandoFit:
  - firma;
  - solo POST dal backend (una GET dà 42501);
  - chiave mai nei log;
  - 42501 per la chiave e PGRST3xx o errore del gateway per la anon key, da distinguere dal corpo della risposta (entrambi arrivano come 401);
  - busta e schema v1;
  - evoluzione: chiavi nuove senza preavviso, rimozioni con versione 2;
  - al massimo una chiamata al minuto;
  - rotazione con due righe; valida_fino solo per chiudere la chiave vecchia.

**RIPRESA** (C4):
- §3.1 con un paragrafo per ogni codice: cosa significa e cosa fare;
- come si legge `sorveglia --dry-run` e `report-verifica-stato --verita`;
- §4 e §6.

**README** (C4): sorveglia, le unit e il drop-in.

**CLAUDE.md** (C4): UNA sola deroga per il giro 2, che conferma «niente notifiche».

## 17. Ordine di rilascio
1. Tutti i task verdi sul branch: le tre suite, più `tsc` senza errori nuovi rispetto ai 51 preesistenti.
2. Michele applica la 12 (dopo la 11), poi inserisce l'impronta della chiave.
3. Se D1 li ha trovati: file dei domini verificanti.
4. Michele applica la 13 (dopo la 12). La 07 resta NON applicata.
5. Un solo deploy nella finestra sicura (12:30-16:30 o 19:00-22:30):
   - `git pull` e build del sito;
   - unit di sorveglia (enable --now del timer), drop-in del sender, un solo `systemctl restart` del sender;
   - `VERIFICA_STATO_MODALITA` assente, quindi ombra.
6. Il messaggio a BandoFit, inoltrato da Michele.
7. Dopo almeno 7 giorni d'ombra: `report-verifica-stato --verita` con `difformi: 0`, poi `VERIFICA_STATO_MODALITA=attivo` e un restart. Con anche una sola difformità non si attiva: si scrive al lead.

## 18. Messaggi `CONTRATTO:`
Servono per: un nome o una chiave che manca qui; un ramo di salute senza codice; un host da aggiungere agli estrattori; un id di verità nota cambiato; un file da toccare fuori dal proprio task.
---

## 19. Percorso A, versione 2 (studio del 30/09, risposte di Michele del 30/09 notte)

Fonte: `docs/contracts/studio-aperti-senza-prova-2026-09-30.md` («Soluzione» e «Modifiche al contratto del giro 2»).
Questa sezione **libera** le sezioni del percorso A (§2.2, §3, §4, §5, §6, §7, §15 e le parti A di §8, §11, §12,
§13, §14, §16, §17) e le **modifica** come scritto qui sotto. Dove §19 e una sezione precedente dicono cose diverse,
vale §19. Tutto il resto delle sezioni A vale com'è scritto.

**Risposte di Michele (30/09 notte), vincolanti:**
- **D1, aperti senza prova: bollino «Aperto · da verificare»** (motivo `senza_conferma` sul ramo A), dal 7° giorno dopo
  la pubblicazione e solo dopo una lettura in attivo; rilettura ogni 14 giorni. Il bando resta fra gli aperti, nei
  contatori e nei filtri. A2 resta intatta: **nessun timer, nessuna chiusura senza evento**.
- **D2, doppioni certi: fusione automatica**, solo con criteri esatti (stesso URL normalizzato, oppure stessa riga di
  calendario della stessa fonte), al massimo `GEMELLI_FUSIONI_PER_GIRO` (10) per giro. Il doppione già pubblicato va
  in 301 verso il master tramite `bando_fondi` (nessuna riga cancellata, id e slug congelati). Una riga nuova gemella
  esatta di un pubblicato non viene mai pubblicata. Chiude RIPRESA §4.1 g.
- **D3, IndicePA: import COMPLETO e automatico** (non filtrato sugli host già usati), ogni mese. Vedi §19.8.
- Michele ha delegato al lead le decisioni rimanenti fino al suo ritorno. Quelle prese sono marcate **[lead]**.

### 19.1 Regole per tutti (aggiunte a §1)
- Dal Mac `domini --import` e `gemelli` solo con `--dry-run`; la fase ingresso di `verifica-stato` solo con
  `--dry-run --senza-modello`.
- Nessuna scrittura su `dominio_ufficiale` dal Mac, nemmeno di prova.

### 19.2 Migrazione 13 (modifica §2.2)
- In `bando_controllo` entrano **5 colonne additive** in più (da 12 a **17**):
  - `esaminato_attivo_at timestamptz`: si scrive **solo in attivo**, a ogni lettura con qualunque esito;
  - `termine_indicato_fonte text` CHECK IN ('calendario_ufficiale','pagina','testo','aggregatore'), con il vincolo
    `bando_controllo_termine_con_fonte`: `termine_indicato` e `termine_indicato_fonte` entrambi NULL o entrambi NOT NULL;
  - `segnale_aggregatore text` CHECK IN ('assente_dal_listing','in_uscita','scadenza_passata');
  - `segnale_aggregatore_at timestamptz`;
  - `trattenuto_dal timestamptz`.
- GRANT SELECT ad anon anche su `esaminato_attivo_at`, `segnale_aggregatore_at`, `termine_indicato_fonte` (la vista è
  `security_invoker`).
- `bando_stato_da_verificare` riceve `p_esaminato_attivo_at timestamptz` e `p_segnale_aggregatore_at timestamptz`
  **prima** di `p_adesso`. Nessuna funzione nuova per anon: l'insieme delle funzioni eseguibili da anon previsto dalla
  guardia della 12 non cambia.
- La vista riceve **5 colonne in coda**: le 4 di §2.2 più `termine_indicato_fonte` (NULL quando `termine_indicato` è
  NULL). **[lead, revisione #104]** `stato_letto` e `stato_letto_at` della vista valgono NULL anche quando
  `stato_letto_metodo` ≠ 'estrattore': il sito non deve dire «la pagina ufficiale lo indicava aperto» su una lettura
  del modello, che la regola (A2) non considera una conferma. La verifica attende colonne della vista = prima + 5. La 07 e il suo rollback portano le 5 colonne.
- Casi PG17 nuovi: in ombra (`esaminato_attivo_at` NULL) un aperto senza scadenza pubblicato da 30 giorni → NULL; lo
  stesso con `esaminato_attivo_at` → `senza_conferma`; segnale più recente di una conferma → `senza_conferma`;
  `termine_indicato` senza fonte → 23514; `SET ROLE anon`: la SELECT della vista restituisce le 5 colonne.
- **[lead] Verifica 7 della 05 con l'import completo.** Il blocco di verifica della 13 contiene, commentata, la query
  EXPLAIN (ANALYZE, BUFFERS) come anon della Verifica 7 della 05. La prova PG17 di `db` la esegue con
  **25 000 righe sintetiche `tipo='ente'`** in `dominio_ufficiale` (più le righe aggregatore del seed) e riporta nel
  commit: tempo < 300 ms su 2 000 bandi sintetici e **nessun Seq Scan su `dominio_ufficiale`**. Se il piano mostra un
  Seq Scan, la 13 aggiunge l'indice che manca (additivo) e la prova si ripete.

### 19.3 Regola `stato_da_verificare` v2 (modifica §3)
- `versione: 2`; parametri `{giorni_grazia_pubblicazione: 3, giorni_validita_conferma: 30, giorni_grazia_ramo_a: 7}`;
  motivi invariati (5). La firma nei tre linguaggi riceve `esaminato_attivo_at` e `segnale_aggregatore_at` subito
  prima di `adesso`.
- Ramo I invariato. **Ramo A v2** (vince la prima):
  - **A1.** lettura valida chiuso / uscito / in apertura prossimamente → `smentito_dalla_fonte`;
  - **A2.** lettura valida 'aperto' con metodo 'estrattore', `stato_letto_at` al massimo 30 giorni fa, E
    (`segnale_aggregatore_at` NULL oppure `stato_letto_at` > `segnale_aggregatore_at`) → NULL;
  - **A3.** `termine_indicato` non NULL e < oggi → `termine_passato`;
  - **A4.** `esaminato_attivo_at` NULL → NULL (l'ombra non accende nulla);
  - **A5.** `segnale_aggregatore_at` non NULL → `senza_conferma`;
  - **A6.** `termine_indicato` ≥ oggi → NULL;
  - **A7.** `pubblicato_at` al massimo 7 giorni fa → NULL (grazia);
  - **A8.** altrimenti → `senza_conferma`.
- **[lead, 30/09 notte, revisione #104] Ramo I in ombra**: fra I6 e I7 si inserisce **I6-bis. `esaminato_attivo_at`
  NULL → NULL**. In ombra nessuna lettura può confermare un «in apertura» (I5), quindi `senza_conferma` sul ramo I
  compare solo dopo una lettura in attivo, come sul ramo A. I codici dei casi: `i6bis-*`.
- **[lead, 30/09 notte, revisione #103] ORDINE DEFINITIVO — in ombra conta solo ciò che il bando dice di sé.**
  `previsto_entro` e `termine_indicato` li scrive il passo nuovo, anche in ombra: prima dei 7 giorni di verifica
  (`report-verifica-stato --verita`) non devono cambiare niente di pubblico. Le etichette restano le stesse, cambia
  solo l'ordine di valutazione:
  - **ramo I: I1, I2, I3, I6-bis, I4, I5, I6, I7** (in ombra solo I1 e I2; I3 richiede una lettura, che in ombra non
    si scrive);
  - **ramo A: A1, A2, A4, A3, A5, A6, A7, A8** (in ombra A1 e A2 non scattano per lo stesso motivo, quindi il ramo A
    dà sempre NULL).
  In attivo l'esito è identico all'ordine di prima, perché I6-bis e A4 non scattano. Conseguenza: in ombra l'unico
  motivo pubblico è `data_apertura_passata` (I2), che dipende solo da `bando.data_apertura`. Il passo scrive
  `esaminato_attivo_at` in attivo per OGNI candidato esaminato, compresi gli illeggibili (senza fetch).
- «Non esiste un motivo debole» vale ora solo per l'ombra.
- Casi obbligatori nuovi: A4-A8, il confine dei 7 giorni a mezzanotte di Roma, il segnale prima e dopo la conferma, il
  termine futuro con il segnale (→ `senza_conferma`), la conferma del modello che non spegne A8, l'ombra. **Almeno 80
  casi** nella sezione `certezza`.

### 19.4 Verifica-stato (modifica §5)
- **§5.2** Priorità nuova: `segnale_aggregatore` non NULL e non letto dopo il segnale → 88. Fase `ingresso`: candidati
  = righe `stato_processing='enriched'` con stato 'aperto' e `data_scadenza` NULL, oppure con status OE '2'; le prende
  `db.select_enriched_da_leggere()`, con il tetto `VERIFICA_STATO_TETTO_INGRESSO` (30).
- **§5.3** Il punto 2 usa `normalizza_link_bando(testo)` (puro, in `verifica_stato.py`): divide sugli spazi e tiene gli
  http(s); un host in `dominio_ufficiale.ACCORCIATORI` (rpu.gl, bit.ly, tinyurl.com, goo.gl, t.ly) si segue con
  redirect 'tutti' e vale solo se l'URL finale è verificante. Nuovo tipo **(ii-c)**: `bando_controllo.candidato_prioritario`
  con host uguale all'host della fonte di scraping, verificante, fuori da FONTI_OE e con G3v 'medio'; ammette eventi
  come (ii). Il punto 3 (iv) resta senza eventi; una conferma A2 da una pagina (iv) vale solo con un lettore per ente,
  titolo 'alto' e `segnale_aggregatore` NULL. Il punto 4 (illeggibile) calcola `termine_indicato` con le quattro fonti
  di §19.5. `verificabile` si calcola sulla tabella letta dal DB (`db.select_domini_ufficiali`), non sul solo seed.
- **§5.4** Dopo i lettori per ente, sulle pagine i-iv senza lettore dedicato gira il lettore `generico` (§19.5): solo
  'chiuso' con `solo_segnale`, altrimenti None. Il modello resta limitato a (i), (ii), (iii); un suo 'aperto' non
  conferma.
- **§5.7** Solo in attivo: `esaminato_attivo_at` insieme alle sei colonne `stato_letto*`. Sempre: `termine_indicato_fonte`
  insieme a `termine_indicato`. `segnale_aggregatore(_at)` li scrive `bando_runner` (§19.7), non il passo. Nella fase
  ingresso, sulle righe NON pubblicate: `data_scadenza`, `ora_scadenza` e stato 'chiuso' da un lettore per ente o dalla
  finestra, tramite `db.aggiorna_ingresso` (che rifiuta le righe pubblicate); `data_scadenza_verificata` non si tocca
  (CHECK della 03); in più `lettura_stato.storia` e `trattenuto_dal`.
- **§5.9** Cadenza: `senza_conferma` → 14 giorni; segnalato → 3 giorni. Contatori nuovi: `senza_conferma`,
  `segnalati`, `smentiti_generico`, `termini_per_fonte {fonte:n}`, `pagine_ii_c`, `link_normalizzati`; fase ingresso:
  `ingresso_letti`, `ingresso_date_scritte`, `ingresso_chiusi`, `trattenuti`, `rilasciati_a_tempo`,
  `trattenuti_senza_appiglio`, `fusi_prima_della_pubblicazione`. VERITA_NOTA estesa come nello studio (2475, 2520,
  5698, 5699, 5700, 803614/803615/803623, 562317, 17773, 18178, 17883, 18186, 18231, 18312, 18276, 18262, 18407).
- **§5.10 nuova, fase ingresso e sosta.** `esegui_passo(giro, fase='ingresso')` gira fra i ricontrolli e la SEO, con
  tetto di 30 letture e 300 s, **senza modello**. `ingresso.pubblicabile(riga, controllo, adesso) -> (bool, motivo)`
  (puro) è il filtro usato da `bando_seo_runner.run`. Trattiene: un 'aperto' senza `data_scadenza`, senza conferma
  d'estrattore nella storia e senza `termine_indicato` ≥ oggi, per al massimo `INGRESSO_SOSTA_GIRI` (4) giri da
  `trattenuto_dal`; sempre una riga senza link_bando, fonte_ufficiale_url, bando_link e senza alcuna data (motivo
  'senza_appiglio'). In ombra la sosta conta e basta: si pubblica come oggi.

- **[lead] Righe di `pipeline_run` del passo**: la fase controlli scrive una SUA riga `step='verifica_stato'`, la fase
  ingresso una riga `step='verifica_stato_ingresso'`, entrambe con `giro` e i contatori di §5.9/§19.4 (come il monitor
  con `step='monitor'`); la riga `'pipeline'` riporta solo lo stato del passo. `misure_salute` (`da_verificare`,
  `verifica_7g`) legge solo le righe `step='verifica_stato'`.

### 19.5 Estrattori, date e ingresso (modifica §6)
- **§6.1** Nuova chiave `generico` in ESTRATTORI: frasi compiute (`bando|avviso|sportello|domande` a non più di 60
  caratteri da `chius[oa]|scadut[oa]|sospes[oa]|esaurit[ae]|non è più possibile presentare`) nell'h1, nei badge/label e
  nei primi 2 000 caratteri del corpo principale, con le esclusioni di §5.4. Sempre `solo_segnale=True`,
  `puo_chiudere=False`, mai 'aperto'. Fixture positive: so.camcom (Bando Chiuso), va.camcom (CHIUSURA SPORTELLO),
  regione.puglia 5699 (sospeso), calabria 18231; negative: «fino ad esaurimento», un «Aperto» generico, una sidebar
  con altri bandi chiusi. **Secondo lotto di lettori per ente**: host con almeno 5 bandi fra i ~410 e un'etichetta
  strutturata nelle pagine già scaricate; li sceglie `backend` con un report e fixture reali.
- **§6.2** Nuove funzioni in `date_validation.py`, ognuna restituisce `(data, fonte)`: `termine_nella_pagina(testo)`
  (regole di termine_nel_testo sul testo della pagina), `termine_da_calendario(raw_data, fonte_id, host_verificante)`
  (colonne «chiusura domande», «in corso fino a», DATA_CHIUSURA, con e_presunta), `termine_da_etichetta_oe(raw_data)`
  (riusa `segnali.scadenza_da_label`). Precedenza: calendario_ufficiale > pagina > testo > aggregatore. Negativi in
  più: la data della fiera di 1257980 e l'avvio attività di ER 940320.
- **§6.3** Preprocess: blocco del prompt = `testo[:1500]` + `impronte.seleziona_sezioni(testo[1500:], 6500)`,
  `BUDGET_PROMPT_CHAR = 8000` (costante unica, per tornare a 4000 se la quota con scadenza deriva). Dopo il modello:
  lettore per ente sulla pagina (termine_finale → data_scadenza se il modello non l'ha data; 'chiuso' con puo_chiudere
  → stato 'chiuso'). OE: data dal deadline_label solo con status '1', data ≥ oggi e citazione «Scadenza: …» presente
  nel testo della scheda (validate_date_candidate con provenienza aggregatore). Status '2' → 'in apertura
  prossimamente'; `on_arrival` escluso. Prompt invariati. «Nessun rifiuto all'ingresso» resta: la sosta è in §5.10.

- **[lead, dopo #73]** Secondo lotto effettivo: `invitalia`, `toscana`, `fvg` (pr2127 è già il lettore `puglia`).
  «Le date vincono» quando l'etichetta contraddice le date («In corso»/«Aperto» con termine passato, o un chiuso solo
  segnale) → 'chiuso' senza `puo_chiudere`; un «Chiuso» strutturato con `puo_chiudere` resta chiusura (§5.6 e). Calabria
  «Pre-informazione» → 'in apertura prossimamente' (come VERITA_NOTA 1261858, prevale sulla tabella di §6.1). Firma:
  `leggi(html, url_finale, titolo, *, oggi=None)` e `leggi_generico` pubblica. **[lead, revisione #93]** Un'etichetta
  di chiusura mai vista su una pagina vera vale solo segnale (`puo_chiudere=False`) finché non entra una fixture vera:
  oggi toscana «Chiuso», fvg «[BANDO CHIUSO]», Piemonte «concluso», Calabria «Conclusione». Le fixture non contengono
  dati personali (email, anche offuscate, e nomi): un test le scandisce.

### 19.6 Salute (aggiunte a §8, codici A)
`allarmi_verifica_stato()` comprende: `aperti_senza_conferma` (avviso: quota di senza_conferma sugli aperti senza
scadenza > 60%), `ingresso_trattenuti` (avviso: trattenuti_senza_appiglio > 10, oppure rilasciati_a_tempo > 50% in 7
giorni), `indicepa_non_aggiornato` (avviso: ultimo import riuscito più vecchio di 40 giorni), **[lead]**
`vista_lenta` (allarme: la lettura di prova di `bando_pubblico` con `limit=24`, misurata da `misure_salute` come chiave
`vista_ms`, supera 2 000 ms; protegge il sito dall'effetto dell'import completo. La GET si fa come anon se nell'ambiente c'è `PUBLIC_SUPABASE_BANDI_ANON_KEY`, altrimenti con la service key: `vista_ms_ruolo` dice quale; con 'servizio' il codice è un avviso, perché la RLS non è misurata) e **[lead]** `indicepa_import_anomalo`
(avviso: l'ultimo import ha scartato più del 20% delle righe o ne ha trovate meno di 15 000).

### 19.7 Segnale dell'aggregatore (nuovo)
`segnali.segnale_aggregatore(record_listing, riga, adesso, *, copertura_piena, giri_assenza=3)` (puro): NULL visto vale
`DATA_SEMINA_VISTO = 2026-09-23`; status '2' → `in_uscita`; `scadenza_da_label` < oggi → `scadenza_passata`;
`assente_dal_listing` solo con copertura piena e dopo 3 giri. `bando_runner`, al passo 6-bis, lo scrive con
`db.aggiorna_segnale_aggregatore` e lo azzera quando la riga ricompare con status '1' e senza etichetta scaduta.
`spariti()` e gli eventi del monitor restano INVARIATI.

### 19.8 Lista bianca dal DB e IndicePA completo (nuovo)
- `_tabella_corrente()` passa a `costruisci()` le righe di `db.select_domini_ufficiali()` (con `_scorri`, `order=id`),
  in testa: **le righe del DB vincono**. Una sola lettura per processo di giro (cache in memoria).
- `ACCORCIATORI` in `dominio_ufficiale.py`.
- `run_domini_import(..., scarica_enti=True)`: GET di `INDICEPA_URL` (risorsa CKAN pubblica di `enti.xlsx`), lettura
  con `openpyxl` (già installato), import **completo**.
- **[lead] Scrittura prudente**, perché l'import è completo e automatico:
  - si inseriscono **solo host assenti** dalla tabella; una riga esistente (seed, fonte, manuale, aggregatore,
    blocklist, o indicepa di un mese precedente) **non si modifica mai**; **nessuna DELETE** e nessuna disattivazione
    automatica (le righe uscite da IndicePA si contano nel report e basta);
  - scritture a lotti da 500, ognuno idempotente (`on_conflict=host`, `ignore-duplicates`);
  - **host condivisi esclusi**: un host presente in `PIATTAFORME_CONDIVISE` (sites.google.com, wixsite.com,
    wordpress.com, blogspot.com, altervista.org, jimdo.com, weebly.com, github.io, facebook.com, linktr.ee, e i
    domini degli accorciatori), oppure che IndicePA associa a **3 o più `codice_ipa` diversi**, non entra. Ogni
    esclusione ha un motivo nel report;
  - un host che cade su un aggregatore o sulla blocklist non entra (la blocklist prevale, come oggi);
  - soglie di sanità prima di scrivere: se il foglio ha meno di 15 000 righe utili o manca una delle colonne attese,
    **non si scrive niente** e l'esito va in `indicepa_import_anomalo`;
  - se il download fallisce la tabella resta com'è e l'esito (data, righe lette, inserite, escluse per motivo) si
    registra per `indicepa_non_aggiornato` (nella riga `pipeline_run` del passo, contatori `indicepa_*`).
- Il passo `domini` gira nel giro delle 06 **se nel mese di calendario di Roma non c'è ancora un import «fatto»** (in
  ombra 'ok' o 'ombra', in attivo solo 'ok'; un import fallito si ritenta alle 06 del giorno dopo): copre il primo 06
  del mese, il primo 06 dopo il deploy e il primo 06 dopo l'attivazione. I 40 giorni restano solo nel codice di salute
  `indicepa_non_aggiornato`. [lead, allineato al codice di #82] Modalità: segue
  `VERIFICA_STATO_MODALITA` (in ombra: scarica, compone, conta, non scrive).

### 19.9 Gemelli (D2)
- Quarto criterio esatto `riga_calendario` in `gemelli.criteri_esatti`: stessa `fonte_id`, `link_bando` NULL su
  entrambe, descrizione del calendario normalizzata identica e non vuota (almeno 3 token), e stesso raw `source_url`
  oppure stessa data di chiusura del calendario. Positivi: 803614=803633, 803615=803634, 803623=803642,
  1260432=1260443. Negativi: stessa fonte con date diverse; fonti diverse.
- **[lead] Guardie di prudenza sulle coppie per URL nel passo automatico** (non in `criteri_esatti`): l'URL comune
  compare in esattamente 2 pubblicati (3 o più = pagina hub o lotti), titoli con somiglianza almeno 'medio', e
  `data_scadenza` uguale o NULL su una delle due. Le scartate si contano in `coppie_scartate_per_prudenza`.
  Per TUTTI i criteri del passo automatico: nessuna fusione se i titoli differiscono per anno, lotto, edizione,
  annualità, finestra o tranche (`anni_o_lotti_diversi`); un doppione si fonde solo con una coppia prudente diretta
  con il master; i gruppi con più di due righe restano a mano (`gruppi_oltre_due`); se la lettura dei pubblicati
  tocca il limite della select il passo si ferma con errore.
- Passo `gemelli` nel giro delle 06, con tetto `GEMELLI_FUSIONI_PER_GIRO` (10; 0 = spento). **[lead] Modalità:
  segue `VERIFICA_STATO_MODALITA`**: in ombra elenca e conta le fusioni che farebbe (riga `pipeline_run`), in attivo
  fonde. Così la prima fusione automatica arriva dopo almeno 7 giorni dal messaggio a BandoFit, che il contratto DB
  chiede prima di ogni lotto di fusioni.
- Prima della pubblicazione `bando_seo_runner` fonde i gemelli esatti (la riga nuova è il doppione) con
  `db.fondi_bandi`, con la stessa modalità. **[lead, revisione #102]** La fusione lascia tracce leggibili: una riga in
  `bando_fusione` con l'id del doppione mai pubblicato (slug_originale NULL, da ignorare), l'evento `fusione`, i link
  del doppione e un nuovo `ultimo_cambiamento_at` sul master; il doppione va in 'rejected' con il motivo.

### 19.10 Sender e pipeline (aggiunte a §11)
Nuovi passi, tutti con `_passo_se_esiste` e dentro il lock del giro esistente:
- `verifica_stato` (fase controlli) dopo il monitor, **solo nei giri delle 06 e delle 18** come il monitor ([lead, #82]); `ids_da_rigenerare` passati a
  `_rigenerazione_di_produzione`, slug solo per gli eventi applicati;
- `verifica_stato` con `fase='ingresso'` prima della SEO, in ogni giro;
- `domini` come in §19.8 (nel giro delle 06, se nel mese di calendario di Roma non c'è ancora un import «fatto»: in ombra 'ok' o 'ombra', in attivo solo 'ok');
- `gemelli` come in §19.9.

### 19.11 Variabili (aggiunte a §12)
`VERIFICA_STATO_MODALITA` (ombra|attivo, default ombra), `INGRESSO_SOSTA_GIRI` (4, da 0 a 12),
`VERIFICA_STATO_TETTO_INGRESSO` (30), `GEMELLI_FUSIONI_PER_GIRO` (10, 0 = spento), `INDICEPA_URL` (default nel codice:
la risorsa pubblica; la variabile serve solo a cambiarla). In `.env.example` solo i nomi.
Attributi di `settings` (nomi fissi, 30/09 notte): `verifica_stato_modalita`, `ingresso_sosta_giri`,
`verifica_stato_tetto_ingresso`, `gemelli_fusioni_per_giro`, `indicepa_url`. Chi li legge prima di #76 li prende con
`getattr(settings, nome, predefinito)`.

### 19.12 CLI (aggiunte a §13)
`domini --import --scarica-enti [--dry-run]`; `verifica-stato --dry-run [--fase ingresso] [--ids] [--senza-modello]
[--limit]`; `report-verifica-stato [--json] [--ramo aperto|apertura] [--motivo M] [--verita]`; `gemelli --dry-run`
elenca le fusioni che farebbe. `test_cli_argv` aggiornato.

### 19.13 db.py (aggiunte a §14)
`COLONNE_LETTURA_STATO` a 17 colonne. Funzioni nuove: `select_da_verificare`, `select_letture_stato`,
`aggiorna_lettura_stato` (scarta le colonne assenti come `aggiorna_controllo`), `select_enriched_da_leggere()`,
`aggiorna_ingresso(bando_id, colonne_bando, colonne_controllo)` (rifiuta le righe pubblicate),
`select_domini_ufficiali()`, `select_host_dei_link()`, `aggiorna_segnale_aggregatore(righe)`,
`inserisci_domini_nuovi(righe, lotto=500)` (solo host assenti) e la misura `vista_ms` in `misure_salute`.

### 19.14 Sito e API (modifica §15)
- Badge «Aperto · da verificare» anche per (aperto, `senza_conferma`). Sottotesto: «Non abbiamo una conferma recente
  dalla pagina ufficiale dell'ente: verifica prima di presentare domanda.»
- Il sottotesto del termine futuro dipende da `termine_indicato_fonte`: calendario_ufficiale «Il calendario ufficiale
  indica come termine il <data>»; pagina «La pagina dell'ente indica come termine il <data>»; testo «Il testo del
  bando indica come termine il <data>, non ancora verificato sulla pagina ufficiale»; aggregatore «Un portale
  aggregatore indica come termine il <data>, non verificato». Il sottotesto di `termine_passato` segue la stessa
  provenienza.
- `supabase-bandi.ts` chiede anche `termine_indicato_fonte` (solo alla vista).
- Contatori, filtri, sitemap e JSON-LD INVARIATI. API v1: l'enum dei 5 motivi contiene già `senza_conferma`; si
  aggiorna solo la documentazione del significato.

### 19.15 Documenti (aggiunte a §16)
Contratto DB: §3 con la quinta colonna; §4 certezza v2 (`senza_conferma` anche sugli aperti; «certo solo con IS
NULL»); `dominio_ufficiale.origine='indicepa'` e import completo mensile; fusioni automatiche con i criteri esatti,
compreso `riga_calendario`, e la regola dell'avviso (§19.9). RIPRESA: §4.1 d risolta con l'import completo; §4.1 g
risolta con D2; §4.1 c resta aperta; la trappola «resolver e monitor non leggono la tabella» è chiusa per resolver e
verifica-stato. Il messaggio a BandoFit comprende la colonna nuova, il nuovo significato di `senza_conferma`, le fusioni
automatiche (volume misurato il 30/09 in ombra, dopo tutte le guardie di prudenza: 52 fusioni (dopo la revisione del ciclo 2: 43 per URL e 9 di calendario), soprattutto le coppie LazioEuropa e schede dell'aggregatore uguali alla pagina dell'ente; con il tetto di 10 per giro delle 06 servono circa 6 giorni; il numero esatto lo dà `gemelli --dry-run` alla vigilia dell'attivazione; poi pochi al mese) e il cambio visibile in blocco
(circa 220-260 schede con «da verificare» nelle 2-3 settimane dopo l'attivazione).

### 19.16 Ordine di rilascio (modifica §17)
Invariato nella forma: la 12, la 13 estesa, un solo deploy, 7 giorni d'ombra, `report-verifica-stato --verita` con 0
difformi, poi attivo. In ombra: nessun `senza_conferma` pubblico; la sosta conta soltanto; gemelli e domini contano
soltanto; il preprocess a 8 000 caratteri è attivo subito (per 7 giorni si confrontano la quota con scadenza, oggi
87%, e la distribuzione degli stati; se derivano si torna a 4 000 con la costante). **[lead]** Dopo il primo import in
attivo Michele esegue una volta la query EXPLAIN della Verifica 7 (righe corte, in RIPRESA); il codice `vista_lenta`
resta come rete automatica.

### 19.17 Correzioni dopo la revisione avversaria (ciclo 1, 01/10)
- Le fusioni automatiche (passo `gemelli` e fusione prima della pubblicazione) usano SOLO i criteri `url` e
  `riga_calendario`; `chiave_esterna` e `atto` restano per l'uso manuale (`fondi-doppioni`).
- Le viste (13, 07, rollback 07) espongono `termine_indicato` e `termine_indicato_fonte` solo con
  `esaminato_attivo_at IS NOT NULL`: in ombra il termine non è pubblico. La funzione del motivo lo legge comunque.
- La 07 non si applica finché il sito chiede `link_candidatura`, `link_candidatura_source` e `allegati`
  (precondizione nella sua testa, test che fissa lo scarto).
- Non si riesegue la 02 dopo la 13 (toglie i grant di colonna).
