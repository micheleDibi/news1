# Verifiche che solo Michele può fare (ottobre 2026)

Scritto il 30/09/2026 da `db` (giro «ripresa bandi, ottobre 2026», task T-D7). Sono controlli che dal Mac del giro
non si possono fare: servono le console dei fornitori, il pannello Supabase o una shell sul server.

**Come si usa.** Una voce alla volta: si fa il comando o il clic, si confronta con «atteso» e si scrive l'esito accanto
(o in chat). I comandi del server sono tutti di sola lettura e usano `journalctl -n N`, che legge le ultime N righe.
Si lanciano dalla shell del server, così come sono scritti.

**Attenzione alle righe «nessuna riga».** Il journal del sender è molto verboso (livello DEBUG): anche 3 000 righe
possono non coprire un giro intero, e allora un grep vuoto sembra «tutto bene» senza aver letto niente. Per questo ogni
comando cerca anche la riga d'inizio giro, `=== BANDI PIPELINE START | … | giro=… ===`: se non compare, la finestra
è troppo corta e il risultato non vale. Si rilancia con un N più grande (per esempio `-n 200000`: il grep filtra,
quindi l'uscita resta corta).

---

## A. Prima di lanciare i file SQL dell'01/10

**1. Backup del DB bandi.** Pannello Supabase, progetto dei bandi → *Database* → *Backups* → *Scheduled backups*.
Atteso: un backup di oggi o di ieri. Esito: ____

**2. PITR (ripristino a un istante).** Stessa pagina, scheda *Point in Time*. Atteso: «attivo»; se non c'è, basta il
backup del punto 1. Esito: ____

Servono perché un evento applicato non si toglie con una riga di SQL (RIPRESA §4.1 f): `correzioni-2026-10-01.sql` e
`correzioni-2026-10-01-testi.sql` ne scrivono 32.

## B. Crediti dei fornitori

**3. Credito Anthropic.** console.anthropic.com → *Settings* → *Billing*. Atteso: saldo sopra i 10 USD, oppure la
ricarica automatica accesa. Il monitor spende 0,05-0,12 USD al giorno, la SEO con Opus di più. Esito: ____

**4. Credito Anthropic, visto dal server.**

```bash
journalctl -u edunews-bandi-sender \
  -n 50000 --no-pager \
  | grep -i -e "BANDI PIPELINE START" \
    -e "classificazioni fallite" \
    -e "credit balance"
```

Atteso: almeno una riga «=== BANDI PIPELINE START» con `giro=06:00` o `giro=18:00` (solo quei giri fanno il
monitor, che è chi classifica), e **nessun'altra riga**. Se non c'è una riga START delle 06 o delle 18, la finestra è
troppo corta: rilanciare con `-n 200000`. Esito: ____

**5. Residuo Firecrawl, entro il 05/10.** firecrawl.dev → *Dashboard* → *Usage*. Atteso: un numero sopra zero. Il
22/09 era 180 286 su 200 000; il 05/10 il periodo si rinnova. Annotare il numero: è l'unico dato sul consumo di
preprocess, enrich e SEO. Esito: ____

## C. Sicurezza (solo il «cosa»)

**6. Rotazione della password di ObiettivoEuropa.** È la riga «P0 rotazione password OE» di `AVANZAMENTO.md`, ancora
aperta. Atteso: «fatta il …», con la data, e la nuova password già nel `scraper_bandi/.env` del server. Esito: ____

**7. Login ObiettivoEuropa, dopo la rotazione.**

```bash
journalctl -u edunews-bandi-sender \
  -n 50000 --no-pager \
  | grep -e "BANDI PIPELINE START" \
    -e "sessione non autenticata" \
    -e "SessioneOEError"
```

Atteso: almeno una riga «=== BANDI PIPELINE START» (la finestra copre un giro), e **nessun'altra riga**. Senza riga
START, rilanciare con `-n 200000`. Esito: ____

**8. Azioni manuali di sicurezza.** L'elenco è in `docs/api-v1.md` §8, «Falle di sicurezza preesistenti». Atteso: per
ogni voce, «fatta», «non fatta» o «decisa di non farla». Basta la risposta, senza dettagli. Esito: ____

## D. Database e server

**9. Errori 57014 (query interrotte per tempo scaduto).** Pannello Supabase, progetto dei bandi → *Logs* →
*Postgres*, ultimi 7 giorni; cercare `57014` oppure `statement timeout`. Atteso: nessuna riga. Se ci sono, annotare
giorno e ora: l'API v1 li restituisce come 503. Esito: ____

**10. Percorso del repo sul server.**

```bash
systemctl cat edunews-bandi-sender \
  | grep -e WorkingDirectory -e ExecStart
```

Atteso: percorsi sotto `~/projects/news1`, come scrivono RIPRESA e README. Esito: ____

**11. Nomi delle unit.**

```bash
systemctl list-units --type=service \
  --all --no-pager | grep edunews
```

Atteso: sei unit, `edunews-frontend`, `edunews-backend`, `edunews-news-sender`, `edunews-bandi-sender`,
`edunews-interpelli-sender`, `edunews-selezione-sender` (README). Se i nomi sono diversi, scriverli. Esito: ____

**12. Il sender dei bandi gira.**

```bash
systemctl is-active edunews-bandi-sender
```

Atteso: `active`. Esito: ____

**13. Il giro di avvio, dopo un riavvio, è finito bene.**

```bash
journalctl -u edunews-bandi-sender \
  -n 50000 --no-pager \
  | grep -e "Pipeline iniziale completata" \
    -e "BANDI PIPELINE START" \
    -e FAILED -e "NON PARTITO" -e ALLARME
```

Atteso: una riga «=== BANDI PIPELINE START … giro=boot» e, dopo, una riga «Pipeline iniziale completata»; nessun
`FAILED`, `NON PARTITO` o `[ALLARME]`. Se la riga con `giro=boot` non c'è, il riavvio è uscito dalla finestra:
rilanciare con `-n 200000` prima di concludere che l'avvio è fallito. Esito: ____

## E. Il 07/10, prima del giro delle 06 dell'08/10

**14. DNS della Basilicata.**

```bash
getent hosts \
  portalebandi.regione.basilicata.it
```

Atteso: una riga con un indirizzo IP. Esito: ____

**15. Se il punto 14 non risponde.**

```bash
journalctl -u edunews-bandi-sender \
  -n 50000 --no-pager \
  | grep -i -e "BANDI PIPELINE START" \
    -e "irraggiungibil"
```

Atteso, dopo il deploy di ottobre: almeno una riga «=== BANDI PIPELINE START» (la finestra copre un giro) e, per ogni
giro che ha incontrato un host morto, una riga «[resolver] host irraggiungibili (DNS) in questo giro: …» o
«[monitor] host irraggiungibili (DNS) in questo giro: …». Vuol dire che il giro salta quegli host invece di aspettarli
(contratto interno §5). Un giro che non ha incontrato l'host non scrive niente: il contatore resta anche nella riga
del giro di `pipeline_run`. Esito: ____

Il 28/09 il DNS della Basilicata non rispondeva. L'08/10 arriva l'ondata dei ricontrolli, con 101 URL su quel dominio
(RIPRESA §4.4): senza DNS e senza il deploy di ottobre, il giro delle 06 rischia 100 minuti persi.
