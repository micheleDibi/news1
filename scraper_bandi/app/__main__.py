"""CLI entry-point: `python -m app <comando> [opzioni]`.

Opzioni comuni a TUTTI i comandi (lette da `_leggi_opzioni`):
  --dry-run    Non scrive il DB: solo log dei risultati e dei contatori.
  --limit N    Processa solo i primi N elementi (smoke test), N intero >= 0.

Comandi:
  discover       Step 1 — Estrae le fonti dalla pagina OpenCoesione e popola
                 la tabella `fonte` su Supabase DB B.
                 Con --dry-run niente upsert ne' mark deprecated; con
                 --limit N solo le prime N fonti scoperte (e il mark
                 deprecated e' saltato comunque: l'elenco e' parziale).
  scrape-bandi   Step 2 — Per ogni fonte ready+attivo, esegue scraping della
                 pagina + popola la tabella `bando`.
                 Con --dry-run niente upsert; con --limit N solo le prime N
                 fonti ready.
  preprocess     Step intermedio — Per ogni bando in stato 'scraped',
                 analizza con Claude Haiku 4.5: valida + stato_bando +
                 confidence_score. Opzioni: --dry-run, --limit N.
  enrich         Step v7 — Per ogni bando 'processed' con stato_bando
                 aperto/in_apertura/NULL: refinement stato (se NULL) +
                 estrazione FK (tipologia, modalita, programma) +
                 junction (beneficiari, ateco, regioni, settori) +
                 estrazione date (pubblicazione/apertura/scadenza con gate
                 substring + source autoritativo).
                 Stato finale: 'enriched'.
                 Opzioni: --dry-run, --limit N, --rerun-enriched
                 (--rerun-enriched include anche bandi gia' 'enriched').
  seo            Step v8 — Skill SEO Opus 4.7: per ogni bando 'enriched'
                 genera contenuto editoriale + meta (slug, titolo,
                 titolo_breve, descrizione_breve, contenuto, livello,
                 allegati, ente_erogatore, area_geografica, tematica,
                 importi, link_candidatura). Stato finale: 'completed'.
                 Opzioni: --dry-run, --limit N, --rerun-completed.
  salute         Diagnosi: allarmi di configurazione e di consumo.
                 Opzioni: --json. Exit 1 se c'e' almeno un allarme.
  domini         Whitelist/blocklist dei domini ufficiali. `--import` compone
                 la tabella dagli host di `fonte`, dal seed e (con
                 `--enti PATH`) dal foglio IndicePA. Opzioni: --dry-run,
                 --limit N, --enti PATH, --ombra/--attivo.
  risolvi-fonte  Step 5 — fonte ufficiale del bando (`app/fonte_ufficiale.py`).
                 Opzioni: --dry-run, --limit N, --nuovi|--backlog,
                 --solo-oe, --solo-in-verifica, --id X, --ombra|--attivo,
                 --forza, --offset N, --lotto Lx.
                 `--limit` conta le righe da LAVORARE: la selezione si scorre
                 e le righe il cui ricontrollo non e' ancora dovuto finiscono
                 in `saltate`. `--offset N` fa ripartire lo scorrimento oltre
                 le prime N righe (serve con --forza, che toglie ogni filtro).
  oe-dettaglio   Scarico delle schede Obiettivo Europa e registrazione dei
                 candidati in `bando_link`. Opzioni: --dry-run, --limit N,
                 --id X, --ombra|--attivo, --forza (--solo-oe e' accettato ed
                 e' gia' il comportamento: il comando guarda solo le fonti OE).
                 Con --dry-run non scarica nulla (le schede consumano il tetto
                 OE_SCHEDE_GIORNO): conta quelle che avrebbe letto.
                 --offset N riparte oltre le prime N righe della selezione:
                 con --forza nessuna riga e' «gia' letta» e senza offset il
                 lotto ripartirebbe ogni volta dalla prima pagina.
  link-verifica  Ricontrollo di `bando_link`: 2xx e dominio non aggregatore
                 decidono `pubblicabile`. Opzioni: --dry-run, --limit N,
                 --id X, --offset N, --ombra|--attivo.
                 `--limit` conta le righe da verificare davvero: quelle gia'
                 verificate oggi finiscono in `saltate`.
  fondi-doppioni Gemelli esatti (fusione) e possibili doppioni (report).
                 Opzioni: --dry-run, --limit N, --ombra|--attivo.
                 Qui il confronto e' fra righe dello stesso elenco e non si
                 impagina: si legge il corpus e `--limit` e' il numero di
                 FUSIONI applicate (--limit 0 = solo report).
  monitor        Step 7 — ricontrollo delle pagine ufficiali
                 (`app/monitoraggio.py`). Opzioni: --dry-run, --limit N,
                 --ombra|--attivo, --senza-rete (seleziona, ordina e riepiloga
                 senza fare una sola richiesta: e' il modo di provare la
                 selezione su dati veri senza spendere niente).
                 Da CLI il giro vale «sempre»: il confronto con MONITOR_GIRI
                 lo fa la pipeline, non la riga di comando.
  report-ombra   Misura della precisione prima di attivare (§6.2): gate
                 superati e falliti per evento. Opzioni: --dry-run, --limit N,
                 --campione N (default 100), --tipo X, --senza-g7 (il periodo
                 d'ombra ha girato senza i due adattatori del G7: il verdetto
                 `sufficiente` sparisce, perche' su quel campione ogni evento
                 con transizione o con una data era respinto in partenza),
                 --ombra|--attivo.
  applica-eventi Applica a posteriori gli eventi raccolti in ombra, a blocchi
                 (§6.2: senza questo comando la baseline delle impronte li
                 perderebbe). Opzioni: --dry-run, --limit N, --dal AAAA-MM-GG,
                 --tipo a,b,c (elenco separato da virgole: i tipi si attivano
                 uno alla volta), --offset N, --ombra|--attivo.
                 Il --limit conta gli eventi da APPLICARE: quelli gia'
                 rifiutati dalla RPC non consumano piu' il blocco.
  pulisci-contenuto  Backfill L7 (§6.4): toglie dal `contenuto` gia' generato i
                 segmenti che puntano all'aggregatore. Opzioni: --dry-run,
                 --limit N, --lotto Lx, --offset N, --ombra|--attivo.
  rigenera       Backfill L7: rigenerazione mirata delle pagine il cui testo
                 non dice piu' quello che dicono le colonne. Opzioni:
                 --dry-run, --limit N, --malformati (le righe con `contenuto`
                 non JSON), --lotto Lx, --offset N, --ombra|--attivo.
  archivia-processed  Backfill L8: porta ad `archiviato` i `processed` chiusi
                 che non verranno piu' lavorati. Opzioni: --dry-run,
                 --limit N, --lotto Lx, --offset N, --ombra|--attivo.
                 Il --limit conta le ARCHIVIAZIONI, non le occhiate.

**`--limit` conta il lavoro, non le occhiate.** Tutti i comandi a lotti
scorrono la propria selezione a pagine e fanno consumare il limite alle sole
righe su cui c'e' davvero qualcosa da fare; le altre finiscono in un contatore
`saltate`/`saltati` del riepilogo. `--offset N` riparte oltre le prime N righe
della selezione ed e' il modo di lanciare i blocchi a mano quando niente puo'
far uscire una riga dalla selezione (con `--forza`, in ombra o con
`--dry-run`, dove nessun marcatore viene scritto).

`--offset` lo hanno i **sette** comandi che scorrono una selezione a pagine
(`risolvi-fonte`, `oe-dettaglio`, `link-verifica`, `applica-eventi`,
`pulisci-contenuto`, `rigenera`, `archivia-processed`). I quattro sottocomandi
v11 che non lo scorrono (`fondi-doppioni`, `monitor`, `report-ombra`,
`domini`) ora lo **rifiutano** con exit 2 invece di accettarlo e buttarlo via:
un blocco che non si sposta e un comando che dice di averlo spostato danno la
stessa riga di log, ma il secondo fa ripetere il giro. `salute` sta sul
percorso storico (`_avvisa_ignorati`, come `discover` e gli altri quattro step):
avvisa e prosegue, e non avendo nessuna selezione da scorrere non puo'
illudere nessuno di aver avanzato.

**Modalita' ombra per difetto** su tutti i sottocomandi v11: senza `--attivo`
esplicito (o `RESOLVER_MODALITA=attivo` / `MONITOR_MODALITA=attivo` in `.env`)
nessuna colonna pubblica viene toccata.

I tre sottocomandi di §6.4 (`pulisci-contenuto`, `rigenera`,
`archivia-processed`) e i due dell'ombra (`report-ombra`, `applica-eventi`)
hanno la riga di comando qui e l'ingresso nei moduli: `app/monitoraggio.py`
(`run_report_ombra`, `run_applica_eventi`), `app/rigenera.py` (`run_rigenera`,
lotto L7) e `app/backfill.py` (`run_pulisci_contenuto`, `run_archivia_processed`,
lotti L7 e L8). La riga di comando era arrivata prima apposta — i lotti si sono
scritti e provati senza toccare questo file, e `--dry-run` e `--limit`
(vincolo 3, M20) erano gia' obbligatori dal primo giro. `ingresso_atteso=False`
resta sui tre che vivono in moduli nati per altro: e' il caso «modulo c'e',
funzione no», che vale exit 2 e non un traceback.

Opzioni non valide (es. `--limit` senza intero) -> messaggio su stderr ed
exit 2. Comando assente o sconosciuto -> exit 2. Errore fatale del runner ->
exit 1. **Lock occupato -> exit 3; tetto raggiunto -> exit 4; pezzo non
configurato -> exit 5**: sono i tre esiti che dentro la pipeline sono dizionari
(`saltato_per_lock`, `interrotto_per_tetto`, `saltato='scarico_non_configurato'`)
e che diventano codici di uscita **solo qui** (§5, §16, A15). Il quinto esiste
perche' un giro che non ha potuto fare niente non deve somigliare a un giro
riuscito: senza credenziali OE, `oe-dettaglio` restituirebbe zero schede e
zero errori, e un cron notturno risulterebbe verde su un no-op. Un `SystemExit` alzato dentro uno step attraverserebbe `_safe_run` e
`_run_sync` di `bandi_pipeline.py`, che catturano solo `Exception`, e
ucciderebbe il sender.

Gli exit code vivono solo qui: i runner non chiamano mai `sys.exit` e restano
invocabili senza argomenti da `backend/app/bandi_pipeline.py`.
"""
from __future__ import annotations

import asyncio
import functools
import sys
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .logger import logger


EXIT_OK = 0
EXIT_ERRORE = 1
EXIT_OPZIONI = 2
EXIT_LOCK = 3
EXIT_TETTO = 4
EXIT_NON_CONFIGURATO = 5

#: I valori di `saltato` che valgono un exit code diverso da zero. Gli altri
#: (`colonne_assenti`) sono degradazioni previste dal piano: il giro ha fatto
#: cio' che poteva e resta un esito buono.
SALTATI_NON_CONFIGURATI: frozenset[str] = frozenset({"scarico_non_configurato"})

# Flag di modalita': restano in `Opzioni.resto` e li legge il comando. Il
# default e' l'ombra (`MONITOR_MODALITA`/`RESOLVER_MODALITA`), quindi la
# modalita' attiva si chiede sempre per iscritto, con `--attivo`.
FLAG_MODALITA = frozenset({"--ombra", "--attivo"})

#: Campione predefinito di `report-ombra`: §6.2 chiede la precisione su almeno
#: 100 eventi prima di uscire dall'ombra, e un campione piu' piccolo non
#: misurerebbe quello che il committente deve firmare.
CAMPIONE_PREDEFINITO = 100


class ErroreOpzioni(ValueError):
    """Opzioni della riga di comando non valide; il messaggio va su stderr."""


@dataclass(frozen=True)
class Opzioni:
    """Opzioni comuni a tutti i comandi.

    `resto` conserva, nell'ordine originale, i token che `_leggi_opzioni` non
    riconosce: i flag specifici di un comando (es. --rerun-enriched) li legge
    il comando stesso da qui.
    """
    dry_run: bool = False
    limit: int | None = None
    resto: tuple[str, ...] = ()


def _leggi_opzioni(argv: list[str]) -> Opzioni:
    """Parsing comune: `--dry-run` e `--limit N`; tutto il resto in `resto`.

    `--limit` senza valore, con valore non intero o negativo -> ErroreOpzioni
    (main() lo traduce in messaggio + exit 2).
    """
    dry_run = False
    limit: int | None = None
    resto: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--dry-run":
            dry_run = True
        elif token == "--limit":
            try:
                limit = int(argv[i + 1])
            except (IndexError, ValueError):
                raise ErroreOpzioni("--limit richiede un intero (es. --limit 10)") from None
            if limit < 0:
                raise ErroreOpzioni("--limit richiede un intero >= 0 (es. --limit 10)")
            i += 1  # salta il valore appena consumato
        else:
            resto.append(token)
        i += 1
    return Opzioni(dry_run=dry_run, limit=limit, resto=tuple(resto))


def _avvisa_ignorati(cmd: str, opzioni: Opzioni, ammessi: frozenset[str] = frozenset()) -> None:
    """Token non riconosciuti ne' da `_leggi_opzioni` ne' dal comando: come in
    passato non bloccano l'esecuzione, ma ora vengono segnalati nel log."""
    ignorati = [t for t in opzioni.resto if t not in ammessi]
    if ignorati:
        logger.warning("[main] {}: opzioni non riconosciute, ignorate: {}", cmd, ignorati)


def _cmd_discover(argv: list[str]) -> None:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("discover", opzioni)
    from .orchestrator import run as discover_run
    counters = asyncio.run(discover_run(dry_run=opzioni.dry_run, limit=opzioni.limit))
    logger.info("[main] counters finali: {}", counters)


def _cmd_scrape_bandi(argv: list[str]) -> None:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("scrape-bandi", opzioni)
    from .bando_runner import run as scrape_run
    counters = asyncio.run(scrape_run(dry_run=opzioni.dry_run, limit=opzioni.limit))
    logger.info("[main] counters finali: {}", counters)


def _cmd_preprocess(argv: list[str]) -> None:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("preprocess", opzioni)
    from .bando_preprocess_runner import run as preprocess_run
    counters = asyncio.run(preprocess_run(dry_run=opzioni.dry_run, limit=opzioni.limit))
    logger.info("[main] counters finali: {}", counters)


def _cmd_enrich(argv: list[str]) -> None:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("enrich", opzioni, frozenset({"--rerun-enriched"}))
    include_enriched = "--rerun-enriched" in opzioni.resto
    from .bando_enrich_runner import run as enrich_run
    counters = asyncio.run(
        enrich_run(dry_run=opzioni.dry_run, limit=opzioni.limit, include_enriched=include_enriched)
    )
    logger.info("[main] counters finali: {}", counters)


def _cmd_seo(argv: list[str]) -> None:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("seo", opzioni, frozenset({"--rerun-completed"}))
    include_completed = "--rerun-completed" in opzioni.resto
    from .bando_seo_runner import run as seo_run
    counters = asyncio.run(
        seo_run(dry_run=opzioni.dry_run, limit=opzioni.limit, include_completed=include_completed)
    )
    logger.info("[main] counters finali: {}", counters)


# --- comandi v11 -----------------------------------------------------------

def _codice_da_contatori(contatori: object) -> int:
    """Traduce in exit code i due esiti che la pipeline esprime come dati.

    `saltato_per_lock` e `interrotto_per_tetto` non sono errori: il giro ha
    fatto la cosa giusta fermandosi. Chi lancia il comando da uno script, pero',
    ha bisogno di distinguerli da un giro completo — e ancora di piu' dal caso
    in cui un pezzo non e' configurato e il giro non ha fatto proprio niente.
    """
    if not isinstance(contatori, dict):
        return EXIT_OK
    if contatori.get("saltato_per_lock"):
        return EXIT_LOCK
    if contatori.get("interrotto_per_tetto"):
        return EXIT_TETTO
    if contatori.get("saltato") in SALTATI_NON_CONFIGURATI:
        return EXIT_NON_CONFIGURATO
    return EXIT_OK


MODULO_ASSENTE = "modulo_assente"
#: Il modulo c'e' ma la funzione di ingresso no, e la sua assenza e' prevista:
#: e' il caso dei sottocomandi di §6.4, la cui riga di comando arriva prima del
#: lotto che la usera'. Vale exit 2 come `MODULO_ASSENTE`, non 1.
INGRESSO_ASSENTE = "ingresso_assente"


def _modulo_opzionale(
    modulo: str, funzione: str = "run", *, ingresso_atteso: bool = True,
) -> tuple[Callable | None, str]:
    """Import protetto di uno step non ancora scritto.

    Ritorna `(funzione, motivo)`. «Il modulo non c'e' ancora» e «il modulo c'e'
    ed e' rotto» non sono la stessa cosa: il primo e' la tappa successiva del
    piano, il secondo un guasto da leggere nel log con il traceback. Dirli con
    lo stesso messaggio («non ancora disponibile») nasconderebbe l'unico indizio.

    `ingresso_atteso=False` aggiunge il terzo caso: un modulo che esiste e non
    espone ANCORA quella funzione. Serve ai sottocomandi di §6.4, che vivono in
    moduli gia' scritti per altro (`rigenera.py`) o ancora da scrivere: senza
    questa distinzione `rigenera --malformati` direbbe «guasto» (exit 1) una
    tappa prima del previsto, e chi legge il log andrebbe a cercare un
    traceback che non esiste.
    """
    nome = f"{__package__}.{modulo}"
    try:
        importato = __import__(nome, fromlist=[funzione])
    except ModuleNotFoundError as e:
        if e.name == nome or (e.name and nome.startswith(f"{e.name}.")):
            return None, MODULO_ASSENTE
        logger.exception("[main] {} non importabile: dipendenza {} mancante", nome, e.name)
        return None, f"dipendenza mancante: {e}"
    except Exception as e:
        logger.exception("[main] {} non importabile: {}", nome, e)
        return None, f"errore di import: {e}"
    esecuzione = getattr(importato, funzione, None)
    if esecuzione is None:
        if not ingresso_atteso:
            logger.info("[main] {}.{} non ancora scritta", nome, funzione)
            return None, INGRESSO_ASSENTE
        logger.error("[main] {}.{} non esiste", nome, funzione)
        return None, f"{nome}.{funzione} non esiste"
    return esecuzione, ""


# Il catalogo delle opzioni che prendono un valore: `--id 12`, `--lotto L5`,
# `--enti enti.xlsx`, `--campione 100`, `--tipo proroga`, `--dal 2026-09-01`,
# `--offset 800`. `_leggi_opzioni` le lascia in `resto` come due token, e serve
# a `_senza_valori` per togliere il SECONDO, che nessun flag riconoscerebbe.
#
# **Quali siano ammesse lo decide il singolo comando** (`con_valore=` di
# `_esegui_v11`): questo insieme dice solo «dopo questo nome c'e' un valore».
# Finche' e' stato anche l'elenco delle ammesse, `_esegui_v11` escludeva dalle
# «opzioni non riconosciute» qualunque token vi comparisse, e i quattro
# sottocomandi v11 che l'offset non ce l'hanno accettavano `--offset 800` in
# silenzio, con exit 0: l'operatore credeva di aver spostato il blocco e
# rilanciava lo stesso identico giro.
OPZIONI_CON_VALORE = frozenset({
    "--id", "--lotto", "--enti", "--campione", "--tipo", "--dal", "--offset",
})

#: Le opzioni con valore dei tre lotti di §6.4 (`pulisci-contenuto`,
#: `rigenera`, `archivia-processed`): `--lotto` nomina la riga
#: `pipeline_run.step`, `--offset` sposta il blocco.
OPZIONI_BACKFILL = frozenset({"--lotto", "--offset"})

# Flag del resolver (§5). Sono qui e non dentro il modulo perche' `--attivo` e'
# una decisione della riga di comando, non del codice che scrive.
FLAG_RESOLVER = frozenset({
    "--nuovi", "--backlog", "--solo-oe", "--solo-in-verifica", "--forza",
}) | FLAG_MODALITA

# `--senza-rete` e' del solo monitor: e' l'unico step che, se non scarica, ha
# comunque qualcosa da dire (la selezione e l'ordine della coda).
FLAG_MONITOR = FLAG_MODALITA | frozenset({"--senza-rete"})


def _valore_opzione(resto: tuple[str, ...], nome: str) -> tuple[str | None, tuple[str, ...]]:
    """Legge `--nome VALORE` da `resto` e lo toglie.

    Ritorna `(valore, resto senza i due token)`. L'opzione senza valore — o
    seguita da un'altra opzione — e' un errore: ammetterla significherebbe
    lanciare `--id` su tutto il corpus invece che su una riga.
    """
    token = list(resto)
    if nome not in token:
        return None, resto
    posizione = token.index(nome)
    if posizione + 1 >= len(token) or token[posizione + 1].startswith("--"):
        raise ErroreOpzioni(f"{nome} richiede un valore (es. {nome} 123)")
    valore = token[posizione + 1]
    del token[posizione:posizione + 2]
    return valore, tuple(token)


def _intero_opzione(valore: str | None, nome: str, *, predefinito: int) -> int:
    """`--campione 100` -> 100. Non intero o < 1 -> ErroreOpzioni (exit 2).

    Zero e' escluso apposta: `report_ombra` fa `max(1, campione)` e un
    `--campione 0` produrrebbe una riga sola facendo credere di averne chieste
    zero.
    """
    if valore is None:
        return predefinito
    try:
        numero = int(valore)
    except ValueError:
        raise ErroreOpzioni(f"{nome} richiede un intero (es. {nome} 100)") from None
    if numero < 1:
        raise ErroreOpzioni(f"{nome} richiede un intero >= 1 (es. {nome} 100)")
    return numero


def _offset_opzione(valore: str | None) -> int:
    """`--offset 800` -> 800; assente -> 0. Non intero o negativo -> exit 2.

    E' «da dove ricominciare a scorrere la selezione», e serve ai lotti che si
    lanciano a blocchi: `--offset 0`, `800`, `1600`. Zero e' ammesso perche' e'
    il valore normale (dall'inizio), al contrario di `--campione`.
    """
    if valore is None:
        return 0
    try:
        numero = int(valore)
    except ValueError:
        raise ErroreOpzioni("--offset richiede un intero (es. --offset 800)") from None
    if numero < 0:
        raise ErroreOpzioni("--offset richiede un intero >= 0 (es. --offset 800)")
    return numero


def _giorno_opzione(valore: str | None, nome: str) -> date | None:
    """`--dal 2026-09-01` -> `date`. Formato diverso -> ErroreOpzioni.

    Una data illeggibile passata avanti come stringa diventerebbe silenziosamente
    «nessun filtro»: `applica-eventi --dal 01/09/2026` applicherebbe l'intero
    archivio invece del solo periodo d'ombra.
    """
    if valore is None:
        return None
    try:
        return date.fromisoformat(valore)
    except ValueError:
        raise ErroreOpzioni(f"{nome} richiede una data AAAA-MM-GG (es. {nome} 2026-09-01)") from None


def _tipi_opzione(valore: str | None) -> tuple[str, ...]:
    """`--tipo proroga,rettifica` -> `('proroga', 'rettifica')`.

    L'attivazione di §6.2 procede per tipo, e i tipi si chiedono insieme
    (prima proroga e rettifiche di data, poi chiusura, poi sospensione e revoca
    dopo R0): l'elenco separato da virgole e' la forma scritta nel piano.
    """
    if valore is None:
        return ()
    return tuple(t.strip() for t in valore.split(",") if t.strip())


def _senza_valori(resto: tuple[str, ...]) -> tuple[str, ...]:
    """`resto` senza i VALORI delle opzioni con valore, ma con i loro NOMI.

    Il valore di `--id 42` e' un token che nessun flag riconosce, e senza
    toglierlo ogni `--id` produrrebbe un «opzione non riconosciuta: 42» che non
    significa niente. Il nome invece resta, perche' e' il comando a dire quali
    opzioni con valore accetta: togliendo anche lui, `--offset` passava
    indisturbato su tutti i sottocomandi, compresi quelli che non sanno
    scorrere niente.

    Un nome in coda senza valore non fa saltare un indice: `_valore_opzione` lo
    rifiutera' comunque con il suo messaggio.
    """
    ripulito: list[str] = []
    salta = False
    for token in resto:
        if salta:
            salta = False
            continue
        ripulito.append(token)
        salta = token in OPZIONI_CON_VALORE
    return tuple(ripulito)


def _modo_selezione(resto: tuple[str, ...]) -> str:
    """`--nuovi` (default) o `--backlog`; `--solo-in-verifica` vale ricontrolli."""
    if "--backlog" in resto:
        return "backlog"
    if "--solo-in-verifica" in resto:
        return "ricontrolli"
    return "nuovi"


def _esegui_v11(
    nome: str,
    funzione: str,
    argv: list[str],
    *,
    modulo: str = "fonte_ufficiale",
    ammessi: frozenset[str] = FLAG_MODALITA,
    con_valore: frozenset[str] = frozenset(),
    extra: Callable[[Opzioni], dict] | None = None,
    ingresso_atteso: bool = True,
) -> int:
    """Corpo comune dei sottocomandi v11.

    I quattro del resolver stanno tutti in `app/fonte_ufficiale.py` (il
    predefinito): cosi' `oe-dettaglio`, `link-verifica` e `fondi-doppioni`
    condividono whitelist, contatori e regole di scrittura del resolver invece
    di riscriverle ognuno a modo suo. `modulo=` serve ai sottocomandi
    dell'ombra (`app/monitoraggio.py`) e a quelli di §6.4.

    Un solo punto legge `--attivo` e un solo punto traduce i contatori in exit
    code: e' quello che tiene insieme «ombra per difetto» (vincolo 3) e «gli
    exit code vivono solo qui» (A15) su tutti i comandi, anche quelli che
    verranno.

    `ammessi` sono i flag del comando, `con_valore` le sue opzioni con valore:
    due elenchi per comando e nessuno globale, perche' un `--offset` ammesso
    dappertutto e' un `--offset` ignorato da chi non lo sa scorrere.
    """
    opzioni = _leggi_opzioni(argv)
    parametri = extra(opzioni) if extra is not None else {}
    # Su questi comandi un token non riconosciuto e' un errore, non un avviso:
    # `--dryrun` al posto di `--dry-run` passava dal warning e faceva partire
    # una scrittura vera con exit 0. `--limit` senza intero era gia' severo da
    # sempre; qui la severita' arriva sul flag che conta di piu'.
    ignorati = [
        t for t in _senza_valori(opzioni.resto)
        if t not in (ammessi | con_valore)
    ]
    if ignorati:
        raise ErroreOpzioni(
            f"{nome}: opzioni non riconosciute: {ignorati}. "
            "Un refuso su --dry-run farebbe partire una scrittura, e un --offset "
            "accettato da chi non lo sa scorrere farebbe rilanciare lo stesso "
            "blocco: il comando si ferma."
        )
    if "--ombra" in opzioni.resto and "--attivo" in opzioni.resto:
        raise ErroreOpzioni(f"{nome}: --ombra e --attivo sono incompatibili")
    # Tre valori, non due: `None` e' «l'operatore non ha detto niente» e lascia
    # decidere l'ambiente, `False` e' «ha scritto --ombra» e vince anche su
    # `MONITOR_MODALITA=attivo`. Senza il terzo valore `--ombra` era inerte.
    modalita_richiesta = (
        True if "--attivo" in opzioni.resto
        else False if "--ombra" in opzioni.resto
        else None
    )
    esecuzione, motivo = _modulo_opzionale(modulo, funzione, ingresso_atteso=ingresso_atteso)
    if esecuzione is None:
        return _riporta_modulo_assente(nome, modulo, motivo, funzione)
    contatori = asyncio.run(esecuzione(
        dry_run=opzioni.dry_run,
        limit=opzioni.limit,
        attivo=modalita_richiesta,
        **parametri,
    ))
    logger.info("[main] counters finali: {}", contatori)
    return _codice_da_contatori(contatori)


def _riporta_modulo_assente(
    nome: str, modulo: str, motivo: str, funzione: str = "run",
) -> int:
    if motivo == MODULO_ASSENTE:
        print(f"{nome}: non ancora disponibile (modulo app/{modulo}.py assente)", file=sys.stderr)
        return EXIT_OPZIONI
    if motivo == INGRESSO_ASSENTE:
        # Il messaggio nomina la funzione cercata: e' cio' che serve a chi
        # scrivera' il lotto per sapere dove attaccarsi senza rileggere la CLI.
        print(
            f"{nome}: non ancora disponibile "
            f"(app/{modulo}.py non espone {funzione}())",
            file=sys.stderr,
        )
        return EXIT_OPZIONI
    print(f"{nome}: modulo app/{modulo}.py non importabile ({motivo})", file=sys.stderr)
    return EXIT_ERRORE


def _cmd_risolvi_fonte(argv: list[str]) -> int:
    def parametri(opzioni: Opzioni) -> dict:
        identificativo, resto = _valore_opzione(opzioni.resto, "--id")
        lotto, resto = _valore_opzione(resto, "--lotto")
        offset, _ = _valore_opzione(resto, "--offset")
        return {
            "modo": _modo_selezione(opzioni.resto),
            "solo_oe": "--solo-oe" in opzioni.resto,
            "solo_in_verifica": "--solo-in-verifica" in opzioni.resto,
            "bando_id": identificativo,
            "forza": "--forza" in opzioni.resto,
            # Con `--forza` non resta nessun predicato capace di far uscire una
            # riga dalla selezione: `--offset` e' il solo modo di lanciare i
            # blocchi a mano senza ripetere sempre gli id piu' bassi.
            "offset": _offset_opzione(offset),
            "lotto": lotto,
        }

    return _esegui_v11(
        "risolvi-fonte", "run", argv, ammessi=FLAG_RESOLVER,
        con_valore=frozenset({"--id", "--lotto", "--offset"}), extra=parametri,
    )


def _cmd_oe_dettaglio(argv: list[str]) -> int:
    def parametri(opzioni: Opzioni) -> dict:
        identificativo, resto = _valore_opzione(opzioni.resto, "--id")
        offset, _ = _valore_opzione(resto, "--offset")
        return {
            "forza": "--forza" in opzioni.resto,
            # Con `--forza` nessuna riga e' «gia' letta», quindi lo
            # scorrimento non scarta niente e il lotto ripartirebbe sempre
            # dalla prima pagina: i blocchi si lanciano con `--offset`.
            "offset": _offset_opzione(offset),
            # `--solo-oe` e' il default del comando: il flag lo rende esplicito,
            # e la sua assenza non deve allargare la selezione per sbaglio.
            "solo_oe": True,
            # `--backlog` sceglie i PUBBLICATI senza fonte (il lotto L2 delle
            # 1 702 schede); senza il flag si guarda la coda dei nuovi, che in
            # regime sono una manciata. Il modo lo conosceva gia'
            # `db.select_bandi_da_risolvere`: il comando lo cablava su "nuovi".
            "modo": "backlog" if "--backlog" in opzioni.resto else "nuovi",
            "bando_id": identificativo,
        }

    return _esegui_v11(
        "oe-dettaglio", "run_oe_dettaglio", argv,
        ammessi=FLAG_MODALITA | frozenset({"--forza", "--solo-oe", "--backlog", "--nuovi"}),
        con_valore=frozenset({"--id", "--offset"}), extra=parametri,
    )


def _cmd_link_verifica(argv: list[str]) -> int:
    def parametri(opzioni: Opzioni) -> dict:
        identificativo, resto = _valore_opzione(opzioni.resto, "--id")
        offset, _ = _valore_opzione(resto, "--offset")
        return {"bando_id": identificativo, "offset": _offset_opzione(offset)}

    return _esegui_v11(
        "link-verifica", "run_link_verifica", argv,
        con_valore=frozenset({"--id", "--offset"}), extra=parametri,
    )


def _cmd_fondi_doppioni(argv: list[str]) -> int:
    return _esegui_v11("fondi-doppioni", "run_fondi_doppioni", argv)


def _rigenerazione_di_produzione(scrive: bool) -> Callable | None:
    """L'adattatore che porta la prosa in linea con le date nuove (§6.2, §12).

    Il monitor lo chiama solo quando un evento ha cambiato `data_apertura` o
    `data_scadenza`, e solo in modalita' attiva. Senza di lui il giro scrive le
    colonne ma **non** restituisce lo slug in `slug_modificati`: notificare a
    Google una pagina il cui testo dice ancora la data vecchia e' peggio che
    tacere, e la scelta e' del chiamante.

    In ombra e in `--dry-run` non si costruisce affatto: `scrivi_su_db` non
    deve nemmeno essere raggiungibile da un giro che ha promesso di non
    scrivere. Il gemello di questa funzione sta in
    `backend/app/bandi_pipeline.py` (STEP 7): i due chiamanti sono due, e un
    modulo condiviso solo per tre righe legherebbe la pipeline alla CLI.
    """
    if not scrive:
        return None
    try:
        from . import rigenera
        return functools.partial(rigenera.rigenera, attivo=True, scrivi=rigenera.scrivi_su_db)
    except Exception as e:
        # Anche l'AttributeError sta dentro: un modulo `rigenera` senza i due
        # nomi attesi e' un pezzo mancante, non un giro da far fallire. Il
        # monitor gira lo stesso e semplicemente non notifica IndexNow.
        logger.warning("[main] rigenerazione non disponibile: {}", e)
        return None


def _adattatori_g7() -> dict:
    """La seconda prova del G7 (§6.2): seconda opinione Sonnet e pagine collegate.

    Senza questi due adattatori il G7 non e' soddisfacibile e il monitor
    respinge **ogni** evento con una transizione di stato o una data — cioe'
    proprio quelli che deve raccogliere. Per questo si costruiscono **anche in
    ombra**: l'ombra serve a misurare la precisione dei gate su eventi veri, e
    un G7 spento misurerebbe un monitor che non esiste.

    Senza `ANTHROPIC_API_KEY` restano entrambi `None`, e il comportamento resta
    quello di oggi: senza chiave non c'e' nemmeno il classificatore, `controlla`
    esce prima del fetch, e un raccoglitore di pagine collegate preparerebbe
    solo GET che nessuno userebbe. Il riepilogo lo dichiara
    (`g7_disponibile=false`) invece di lasciar credere che il monitor non trovi
    niente. Si costruiscono o si perdono **insieme** apposta: la variante G2'
    del gate pretende entrambe le prove, e `g7_disponibile` e' l'AND dei due
    (`monitoraggio._campi_g7`).

    I `contatori` sono quelli del giro e vanno passati anche a `run()`: la
    seconda opinione registra li' dentro le proprie chiamate, e solo cosi' il
    suo costo entra nel tetto giornaliero in $ **mentre** il giro corre.

    Il gemello sta in `backend/app/bandi_pipeline.py` (STEP 7): i chiamanti del
    monitor sono due, e un modulo condiviso per dieci righe legherebbe la
    pipeline alla CLI.
    """
    vuoto = {"contatori": None, "seconda_opinione": None, "pagine_collegate": None}
    # I due costruttori si risolvono come qualunque ingresso opzionale: se
    # `monitoraggio.py` e' una tappa indietro il comando non deve fallire.
    costruisci_seconda, _ = _modulo_opzionale(
        "monitoraggio", "seconda_opinione_da_impostazioni", ingresso_atteso=False)
    costruisci_collegate, _ = _modulo_opzionale(
        "monitoraggio", "pagine_collegate_da_impostazioni", ingresso_atteso=False)
    if costruisci_seconda is None or costruisci_collegate is None:
        return vuoto
    try:
        from . import bilancio
        from .settings import get_settings
        impostazioni = get_settings()
        if not getattr(impostazioni, "anthropic_api_key", ""):
            logger.info("[main] ANTHROPIC_API_KEY assente: G7 non soddisfacibile")
            return vuoto
        contatori = bilancio.Contatori()
        return {
            "contatori": contatori,
            "seconda_opinione": costruisci_seconda(impostazioni, contatori),
            "pagine_collegate": costruisci_collegate(impostazioni),
        }
    except Exception as e:
        # Come per la rigenerazione: un pezzo mancante non fa fallire il giro,
        # il monitor lavora lo stesso e il riepilogo dice che il G7 e' spento.
        logger.warning("[main] adattatori del G7 non costruiti: {}", e)
        return vuoto


def _cmd_monitor(argv: list[str]) -> int:
    def parametri(opzioni: Opzioni) -> dict:
        attivo = "--attivo" in opzioni.resto
        return {
            "senza_rete": "--senza-rete" in opzioni.resto,
            # `--dry-run` e' piu' forte di `--attivo` anche qui: il monitor lo
            # sa gia' (forza l'ombra), ma l'adattatore che scrive non deve
            # nemmeno essere costruito.
            "rigenerazione": _rigenerazione_di_produzione(attivo and not opzioni.dry_run),
            # I due adattatori del G7 e i contatori che li misurano: in ombra
            # si costruiscono lo stesso (vedi `_adattatori_g7`).
            **_adattatori_g7(),
        }

    return _esegui_v11(
        "monitor", "run", argv, modulo="monitoraggio",
        ammessi=FLAG_MONITOR, extra=parametri,
    )


def _g7_del_periodo(senza_g7: bool) -> bool:
    """Se il periodo d'ombra che si sta misurando aveva il G7 acceso.

    Serve a collegare la guardia di `run_report_ombra`, che sopprime il
    verdetto `sufficiente` quando il G7 non c'era: senza i due adattatori ogni
    evento con transizione o con una data e' stato respinto in partenza, e una
    precisione misurata su quel campione direbbe soltanto questo.

    `--senza-g7` lo dichiara a mano (e' l'operatore a sapere com'era acceso il
    periodo). Senza il flag si guarda la chiave, che e' la stessa condizione
    di `_adattatori_g7`: senza `ANTHROPIC_API_KEY` i due adattatori non nascono
    e il monitor ha girato con il G7 spento. Impostazioni illeggibili valgono
    «spento»: meglio nessun verdetto che un verdetto su una misura che non c'e'.
    """
    if senza_g7:
        return False
    try:
        from .settings import get_settings
        return bool(getattr(get_settings(), "anthropic_api_key", ""))
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[main] impostazioni non leggibili, G7 dato per spento: {}", e)
        return False


def _cmd_report_ombra(argv: list[str]) -> int:
    """`report-ombra --dal AAAA-MM-GG --campione 100 [--tipo X] [--senza-g7]`.

    La misura di §6.2. Non scrive niente per costruzione (legge gli esiti e
    stampa il CSV), ma accetta `--dry-run` e `--limit` come tutti gli altri:
    M20 non ammette eccezioni, e un comando che li rifiuta costringe chi scrive
    il runbook a ricordarsi quale.
    """
    def parametri(opzioni: Opzioni) -> dict:
        campione, resto = _valore_opzione(opzioni.resto, "--campione")
        tipo, resto = _valore_opzione(resto, "--tipo")
        dal, _ = _valore_opzione(resto, "--dal")
        return {
            "campione": _intero_opzione(campione, "--campione", predefinito=CAMPIONE_PREDEFINITO),
            "tipo": tipo,
            # Senza `--dal` la lettura parte dagli `id` piu' bassi: il
            # campione resterebbe per sempre quello dei primi 100 eventi mai
            # registrati, e la misura si congelerebbe il primo giorno.
            "dal": _giorno_opzione(dal, "--dal"),
            "g7_disponibile": _g7_del_periodo("--senza-g7" in opzioni.resto),
        }

    return _esegui_v11(
        "report-ombra", "run_report_ombra", argv, modulo="monitoraggio",
        ammessi=FLAG_MODALITA | frozenset({"--senza-g7"}),
        con_valore=frozenset({"--campione", "--tipo", "--dal"}),
        extra=parametri, ingresso_atteso=False,
    )


def _cmd_applica_eventi(argv: list[str]) -> int:
    """`applica-eventi --dal AAAA-MM-GG [--tipo a,b] [--limit 50] [--dry-run]`.

    `--tipo` e' l'interruttore dell'attivazione progressiva di §6.2: senza,
    il comando guarderebbe tutti i tipi insieme, compresi sospensione e revoca,
    che prima di R0 non hanno una colonna dove andare.

    `--riprova-rifiutati` ignora le annotazioni dei rifiuti e ripresenta anche
    gli eventi gia' respinti. Esiste perche' quelle annotazioni non si possono
    cancellare: `bando_evento` non concede DELETE nemmeno alla service-role key
    e `riferisce_a` e' immutabile. E' l'unico modo di rimettere in coda un
    evento annotato per sbaglio.
    """
    def parametri(opzioni: Opzioni) -> dict:
        dal, resto = _valore_opzione(opzioni.resto, "--dal")
        tipo, resto = _valore_opzione(resto, "--tipo")
        offset, _ = _valore_opzione(resto, "--offset")
        return {"dal": _giorno_opzione(dal, "--dal"), "tipi": _tipi_opzione(tipo),
                "offset": _offset_opzione(offset),
                "riprova_rifiutati": "--riprova-rifiutati" in opzioni.resto}

    return _esegui_v11(
        "applica-eventi", "run_applica_eventi", argv, modulo="monitoraggio",
        ammessi=FLAG_MODALITA | frozenset({"--riprova-rifiutati"}),
        con_valore=frozenset({"--dal", "--tipo", "--offset"}),
        extra=parametri, ingresso_atteso=False,
    )


def _lotto_del_backfill(opzioni: Opzioni) -> dict:
    """`--lotto Lx` e `--offset N` dei comandi di §6.4.

    `--lotto` nomina la riga `pipeline_run.step`: senza, i crediti e i dollari
    di un backfill finirebbero nella stessa riga del regime e il tetto mensile
    conterebbe due volte lo stesso consumo.

    `--offset` fa ripartire lo scorrimento della selezione oltre le prime N
    righe: e' il modo di lanciare i blocchi a mano, e serve in ombra e con
    `--dry-run`, dove nessuna scrittura lascia un marcatore.
    """
    lotto, resto = _valore_opzione(opzioni.resto, "--lotto")
    offset, _ = _valore_opzione(resto, "--offset")
    return {"lotto": lotto, "offset": _offset_opzione(offset)}


def _cmd_pulisci_contenuto(argv: list[str]) -> int:
    return _esegui_v11(
        "pulisci-contenuto", "run_pulisci_contenuto", argv, modulo="backfill",
        con_valore=OPZIONI_BACKFILL, extra=_lotto_del_backfill,
    )


def _cmd_rigenera(argv: list[str]) -> int:
    def parametri(opzioni: Opzioni) -> dict:
        return dict(_lotto_del_backfill(opzioni), malformati="--malformati" in opzioni.resto)

    return _esegui_v11(
        "rigenera", "run_rigenera", argv, modulo="rigenera",
        ammessi=FLAG_MODALITA | frozenset({"--malformati"}),
        con_valore=OPZIONI_BACKFILL, extra=parametri, ingresso_atteso=False,
    )


def _cmd_archivia_processed(argv: list[str]) -> int:
    return _esegui_v11(
        "archivia-processed", "run_archivia_processed", argv, modulo="backfill",
        con_valore=OPZIONI_BACKFILL, extra=_lotto_del_backfill,
    )


def _cmd_domini(argv: list[str]) -> int:
    """`domini --import`: whitelist da `fonte.link`, IndicePA e seed.

    `--import` resta obbligatorio (e' l'unica modalita' prevista) e la scrittura
    resta dietro `--attivo`: in ombra il comando compone la tabella, dice quante
    righe sarebbero scritte e non tocca niente. Se `dominio_ufficiale` non
    esiste ancora, `db.upsert_domini` degrada con un log.
    """
    def parametri(opzioni: Opzioni) -> dict:
        enti, _ = _valore_opzione(opzioni.resto, "--enti")
        if "--import" not in opzioni.resto:
            raise ErroreOpzioni("domini: specificare --import (unica modalita' prevista)")
        return {"enti": enti}

    return _esegui_v11(
        "domini", "run_domini_import", argv,
        ammessi=FLAG_MODALITA | frozenset({"--import"}),
        con_valore=frozenset({"--enti"}), extra=parametri,
    )


def _stato_salute():
    """Fotografia che `salute` giudica.

    Per ora contiene solo cio' che si sa senza toccare il DB: le misure su
    `pipeline_run`/`fonte_run` (ultimo monitor OK, giri a tetto, crediti
    residui) si aggiungono qui quando la migrazione 02 sara' applicata e il
    monitor scrivera' le righe. Cosi' `salute` e' gia' utile — segnala una
    configurazione incoerente — e non mente su cio' che non ha misurato.
    """
    from .settings import get_settings
    from .telemetria import Stato
    impostazioni = get_settings()
    return Stato(
        modalita_monitor=impostazioni.monitor_modalita,
        indexnow_configurata=bool(impostazioni.indexnow_api_key),
        monitor_giri_validi=impostazioni.monitor_giri_validi,
    )


def _cmd_salute(argv: list[str]) -> int:
    opzioni = _leggi_opzioni(argv)
    _avvisa_ignorati("salute", opzioni, frozenset({"--json"}))
    from .telemetria import righe_allarme, salute
    esito = salute(_stato_salute())
    if "--json" in opzioni.resto:
        import json
        print(json.dumps(esito.come_dizionario(), ensure_ascii=False, sort_keys=True))
    else:
        for riga in righe_allarme(esito):
            print(riga, file=sys.stderr)
        for avviso in esito.avvisi:
            print(f"[AVVISO] {avviso}", file=sys.stderr)
        if not esito.allarmi and not esito.avvisi:
            print("salute: nessun allarme")
    return esito.exit_code


# Ogni comando riceve l'argv residuo (senza il nome del comando) e passa da
# `_leggi_opzioni`: niente piu' casi speciali nel dispatcher. Il valore di
# ritorno e' l'exit code (None vale 0, per i comandi storici).
_COMMANDS: dict[str, Callable[[list[str]], int | None]] = {
    "discover": _cmd_discover,
    "scrape-bandi": _cmd_scrape_bandi,
    "preprocess": _cmd_preprocess,
    "enrich": _cmd_enrich,
    "seo": _cmd_seo,
    "risolvi-fonte": _cmd_risolvi_fonte,
    "oe-dettaglio": _cmd_oe_dettaglio,
    "link-verifica": _cmd_link_verifica,
    "fondi-doppioni": _cmd_fondi_doppioni,
    "monitor": _cmd_monitor,
    "report-ombra": _cmd_report_ombra,
    "applica-eventi": _cmd_applica_eventi,
    "pulisci-contenuto": _cmd_pulisci_contenuto,
    "rigenera": _cmd_rigenera,
    "archivia-processed": _cmd_archivia_processed,
    "domini": _cmd_domini,
    "salute": _cmd_salute,
}


def main(argv: list[str] | None = None) -> int:
    # `argv=[]` esplicito vale "nessun argomento": non si ricade su sys.argv.
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: python -m app <comando> [--dry-run] [--limit N]\n"
            "  comandi: " + ", ".join(_COMMANDS.keys()),
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    cmd_argv = args[1:]

    if cmd not in _COMMANDS:
        print(f"Comando sconosciuto: {cmd}", file=sys.stderr)
        print("Comandi disponibili: " + ", ".join(_COMMANDS.keys()), file=sys.stderr)
        return 2

    try:
        return _COMMANDS[cmd](cmd_argv) or EXIT_OK
    except ErroreOpzioni as e:
        print(str(e), file=sys.stderr)
        return EXIT_OPZIONI
    except Exception:
        logger.exception("[main] errore fatale durante {}", cmd)
        return EXIT_ERRORE


if __name__ == "__main__":
    sys.exit(main())
