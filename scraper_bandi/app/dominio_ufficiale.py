# -*- coding: utf-8 -*-
"""Whitelist e blocklist dei domini (piano §5, §16.1 A11, §16.3 punto 1).

Perche' esiste
--------------
Il resolver deve poter dire, **senza rete e senza LLM**, se un host e' l'ente,
un portale pubblico, un dominio istituzionale riconosciuto per forma, un
dominio solo dedotto oppure un aggregatore. Da quella risposta dipendono tre
cose che non si possono sbagliare:

1. la **pubblicabilita'** di un `bando_link` (un aggregatore non e' mai una
   fonte ufficiale, §13.4);
2. il flag `verificato` di un `bando_evento` — a DB lo decide il trigger con la
   regola «tipo ∈ {ente, portale_pubblico, pattern} e confidenza ≥ 0,80», qui
   la replica `verificabile()`: un `url_prova` su dominio `dedotto` produce un
   evento leggibile ma mai applicabile a stato o date (§5);
3. il punteggio di `punteggia()` nella cascata del resolver.

`classifica()` e' il tipo del **dominio**, non `bando.fonte_ufficiale_tipo`:
quella colonna ammette due soli valori (CHECK della migrazione 01, §16.1 A11)
piu' il flag `fonte_ufficiale_e_atto`. La mappatura verso la colonna la fa
`tipo_fonte_ufficiale()`, una volta sola: `ente → 'ente'`, `portale_pubblico →
'portale_pubblico'`, `pattern | dedotto | sconosciuto → NULL` (e allora l'esito
massimo e' `in_verifica`, mai `trovata`).

Il modulo e' **puro**: nessuna rete, nessun DB, nessun import del package oltre
alla stdlib. L'import di IndicePA e degli host di `fonte` e' una funzione che
riceve le righe gia' lette (`python -m app domini --import` fa il download).

Gemelli a DB (devono restare allineati)
---------------------------------------
* `dominio_di(url)`            → `backend/sql/bando_v11_02_tabelle_di_servizio.sql`
* `e_aggregatore(host, ...)`   → `bando_host_aggregatore(text)` della stessa 02
* le costanti del seed         → `backend/sql/bando_v11_seed_dominio_ufficiale.sql`
  (`tests/test_dominio_ufficiale.py` legge il file SQL e confronta host, tipo e
  confidenza riga per riga: una modifica su un solo lato fa fallire il test)

Regola di confronto (§16.3 punto 1), identica ai due lati:
    host = d.host  OPPURE  host termina con '.' + d.host
    righe `pattern`: il jolly `*` vale `%` di LIKE (qualunque sequenza)
    la blocklist prevale sempre, su qualunque altra riga.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

# --- vocabolario ------------------------------------------------------------

# I cinque valori del CHECK di `dominio_ufficiale.tipo` (migrazione 02).
TIPI: tuple[str, ...] = ("ente", "portale_pubblico", "pattern", "dedotto", "aggregatore")

# Esito di `classifica()` quando nessuna riga combacia: non e' un tipo del DB,
# e' l'assenza di informazione (host mai visto).
SCONOSCIUTO = "sconosciuto"

# Gerarchia di §5: `ente` (con sotto-tipo `atto`) > `portale_pubblico` > forma
# del dominio > deduzione. Piu' basso = piu' forte.
PRECEDENZA: dict[str, int] = {
    "ente": 0,
    "portale_pubblico": 1,
    "pattern": 2,
    "dedotto": 3,
}

# Sopra questa soglia un `url_prova` puo' rendere `verificato` un evento.
# E' la stessa costante del commento di colonna nella migrazione 02.
SOGLIA_VERIFICATO = 0.80

CONFIDENZA_DEDOTTO = 0.60

# Le tre fonti aggregatore del DB bandi: i loro host non entrano mai nella
# whitelist costruita da `fonte.link` (449 = obiettivoeuropa.com).
FONTI_ESCLUSE: frozenset[int] = frozenset({449, 450, 451})

# Etichette che in Italia si comportano da suffisso pubblico: sotto di esse ogni
# terzo livello e' un soggetto diverso, quindi il dominio registrabile ne ha
# tre. Senza questa lista `incentivi.gov.it` e `mimit.gov.it` sarebbero lo
# stesso dominio.
SUFFISSI_ESTESI: frozenset[str] = frozenset({
    "gov", "regione", "provincia", "comune", "edu", "camcom", "istruzione",
})

# Prefissi degli enti territoriali: sotto un dominio geografico di secondo
# livello ogni ente e' un soggetto diverso. Senza questa regola
# `comune.imola.bo.it` e `comune.casalecchio.bo.it` sarebbero lo stesso dominio
# (`bo.it`) e l'atto dell'uno varrebbe per l'altro, che e' la forma piu' comune
# dei titoli comunali («Determinazione n. 55 del …»).
PREFISSI_ENTE: frozenset[str] = frozenset({"comune", "provincia", "regione"})

# I tre tipi che, a confidenza sufficiente, rendono `verificato` un evento.
TIPI_VERIFICANTI: tuple[str, ...] = ("ente", "portale_pubblico", "pattern")

# I due soli valori ammessi da `bando.fonte_ufficiale_tipo` (CHECK di
# `backend/sql/bando_v11_01_pubblicazione.sql`): «atto» e' un sotto-tipo di
# `ente` e viaggia nel flag `fonte_ufficiale_e_atto`, «calendario» non vale mai.
TIPI_FONTE_UFFICIALE: tuple[str, ...] = ("ente", "portale_pubblico")


@dataclass(frozen=True)
class Dominio:
    """Una riga di `dominio_ufficiale`. I nomi sono quelli delle colonne."""
    host: str
    tipo: str
    confidenza: float = CONFIDENZA_DEDOTTO
    ente: str | None = None
    codice_ipa: str | None = None
    fonte_id: int | None = None
    origine: str = "seed"
    note: str | None = None
    attivo: bool = True

    @property
    def e_pattern(self) -> bool:
        return "*" in self.host


def _dom(host: str, tipo: str, confidenza: float, **extra: object) -> Dominio:
    return Dominio(host=host, tipo=tipo, confidenza=confidenza, **extra)  # type: ignore[arg-type]


# --- blocklist --------------------------------------------------------------
# I dieci aggregatori di §5: ripubblicano i bandi altrui. Da loro si leggono
# segnali, mai la fonte ufficiale.
AGGREGATORI: tuple[Dominio, ...] = (
    _dom("obiettivoeuropa.com", "aggregatore", 1.00),
    _dom("fasi.eu", "aggregatore", 1.00),
    _dom("europafacile.net", "aggregatore", 1.00),
    _dom("contributiregione.it", "aggregatore", 1.00),
    _dom("finanziamentinews.it", "aggregatore", 1.00),
    _dom("bandi.it", "aggregatore", 1.00),
    _dom("infobandi.it", "aggregatore", 1.00),
    _dom("ticonsiglio.com", "aggregatore", 1.00),
    _dom("contributieuropa.com", "aggregatore", 1.00),
    _dom("first.aster.it", "aggregatore", 1.00),
)

# Social, video e messaggistica: un post non e' l'atto, nemmeno quando lo
# pubblica l'ente.
SOCIAL: tuple[Dominio, ...] = (
    _dom("facebook.com", "aggregatore", 1.00, note="social"),
    _dom("instagram.com", "aggregatore", 1.00, note="social"),
    _dom("x.com", "aggregatore", 1.00, note="social"),
    _dom("twitter.com", "aggregatore", 1.00, note="social"),
    _dom("linkedin.com", "aggregatore", 1.00, note="social"),
    _dom("threads.net", "aggregatore", 1.00, note="social"),
    _dom("pinterest.com", "aggregatore", 1.00, note="social"),
    _dom("tiktok.com", "aggregatore", 1.00, note="video"),
    _dom("youtube.com", "aggregatore", 1.00, note="video"),
    _dom("youtu.be", "aggregatore", 1.00, note="video"),
    _dom("vimeo.com", "aggregatore", 1.00, note="video"),
    _dom("t.me", "aggregatore", 1.00, note="messaggistica"),
    _dom("telegram.me", "aggregatore", 1.00, note="messaggistica"),
    _dom("wa.me", "aggregatore", 1.00, note="messaggistica"),
    _dom("whatsapp.com", "aggregatore", 1.00, note="messaggistica"),
)

# --- whitelist --------------------------------------------------------------
# Portali pubblici versionati: non sono «l'ente» ma sono pubblici e autorevoli.
PORTALI_PUBBLICI: tuple[Dominio, ...] = (
    _dom("incentivi.gov.it", "portale_pubblico", 1.00, ente="MIMIT — Incentivi.gov.it"),
    _dom("italiadomani.gov.it", "portale_pubblico", 1.00, ente="PNRR — Italia Domani"),
    _dom("opencoesione.gov.it", "portale_pubblico", 1.00, ente="OpenCoesione"),
    _dom("agenziacoesione.gov.it", "portale_pubblico", 1.00, ente="Agenzia per la coesione territoriale"),
    _dom("gazzettaufficiale.it", "portale_pubblico", 1.00, ente="Gazzetta Ufficiale della Repubblica Italiana"),
    _dom("ec.europa.eu", "portale_pubblico", 1.00, ente="Commissione europea"),
    _dom("mimit.gov.it", "portale_pubblico", 1.00, ente="Ministero delle imprese e del made in Italy"),
    _dom("mur.gov.it", "portale_pubblico", 1.00, ente="Ministero dell'università e della ricerca"),
    _dom("istruzione.gov.it", "portale_pubblico", 1.00, ente="Ministero dell'istruzione e del merito"),
    _dom("lavoro.gov.it", "portale_pubblico", 1.00, ente="Ministero del lavoro e delle politiche sociali"),
    _dom("invitalia.it", "portale_pubblico", 1.00, ente="Invitalia"),
    _dom("inps.it", "portale_pubblico", 1.00, ente="INPS"),
    _dom("consip.it", "portale_pubblico", 1.00, ente="Consip"),
    _dom("unioncamere.it", "portale_pubblico", 1.00, ente="Unioncamere"),
    _dom("anpal.gov.it", "portale_pubblico", 1.00, ente="ANPAL"),
    _dom("lazioinnova.it", "portale_pubblico", 1.00, ente="Lazio Innova"),
    _dom("finlombarda.it", "portale_pubblico", 1.00, ente="Finlombarda"),
    _dom("artea.toscana.it", "portale_pubblico", 1.00, ente="ARTEA — Regione Toscana"),
    _dom("sviluppumbria.it", "portale_pubblico", 1.00, ente="Sviluppumbria"),
    _dom("filse.it", "portale_pubblico", 1.00, ente="FILSE — Regione Liguria"),
)

# Pattern istituzionali: 0,80 e' esattamente la soglia sopra la quale un
# `url_prova` puo' rendere «verificato» un evento. Riconosciuti per forma, senza
# margine.
PATTERN: tuple[Dominio, ...] = (
    _dom("*.gov.it", "pattern", 0.80, note="amministrazioni centrali"),
    _dom("*.edu.it", "pattern", 0.80, note="istituzioni scolastiche"),
    _dom("*.camcom.it", "pattern", 0.80, note="camere di commercio"),
    _dom("*.europa.eu", "pattern", 0.80, note="istituzioni europee"),
    _dom("regione.*.it", "pattern", 0.80, note="regioni"),
    _dom("provincia.*.it", "pattern", 0.80, note="province"),
    _dom("comune.*.it", "pattern", 0.80, note="comuni"),
)

# L'intero seed, nello stesso ordine del file SQL.
SEED: tuple[Dominio, ...] = AGGREGATORI + SOCIAL + PORTALI_PUBBLICI + PATTERN


# --- host -------------------------------------------------------------------

_RE_SCHEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_RE_AUTORITA = re.compile(r"[/?#]")
_RE_USERINFO = re.compile(r"^[^@]*@")
_RE_WWW = re.compile(r"^www\.")
_RE_PUNTO_FINALE = re.compile(r"\.$")
_RE_HOST_VALIDO = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")

# Sigla provinciale italiana: due lettere davanti al TLD (`imola.bo.it`).
_RE_SIGLA_PROVINCIA = re.compile(r"[a-z]{2}")


def dominio_di(url: str | None) -> str | None:
    """Host di confronto di un URL, gemello della funzione SQL `dominio_di`.

    Minuscolo, senza schema, userinfo, porta, `www.` e punto finale della
    radice DNS. `None` se il risultato non e' un host ASCII: meglio nessun
    valore che un valore che non corrispondera' a nessuna riga della tabella
    (un IDN non convertito passerebbe i confronti solo per caso).

    Accetta anche un host nudo (`Regione.Marche.it`), cosi' i chiamanti non
    devono sapere se hanno in mano un URL o un host.
    """
    if not url:
        return None
    resto = _RE_SCHEMA.sub("", url.strip())
    resto = _RE_AUTORITA.split(resto, maxsplit=1)[0]
    resto = _RE_USERINFO.sub("", resto)
    resto = resto.split(":", 1)[0]
    resto = resto.strip().lower()
    resto = _RE_WWW.sub("", resto)
    resto = _RE_PUNTO_FINALE.sub("", resto)
    if not resto or not _RE_HOST_VALIDO.fullmatch(resto):
        return None
    return resto


def registrabile(host: str | None) -> str | None:
    """Dominio registrabile: le ultime due etichette, di piu' quando sotto il
    TLD non c'e' un registrante solo (§5).

    Tre regole, nell'ordine:

    1. un'etichetta `comune`, `provincia` o `regione` tiene tutto cio' che sta
       da lei in poi: `comune.imola.bo.it` e `comune.casalecchio.bo.it` sono due
       enti diversi, `comune.firenze.it` e `provincia.firenze.it` pure, e
       `bandi.regione.marche.it` resta lo stesso ente di `www.regione.marche.it`;
    2. un suffisso pubblico di fatto (`gov`, `edu`, `camcom`, …) ne vuole tre:
       `incentivi.gov.it` non e' `gov.it`;
    3. una sigla provinciale di due lettere sotto `.it` ne vuole tre:
       `imola.bo.it`, non `bo.it`.

    Altrimenti due: `bandi.lazioeuropa.it` → `lazioeuropa.it`. Sbagliare per
    eccesso di specificita' costa un gemello non riconosciuto; sbagliare per
    difetto costa una fusione fra enti diversi, che non si disfa da sola.
    """
    normalizzato = dominio_di(host)
    if not normalizzato:
        return None
    etichette = normalizzato.split(".")
    if len(etichette) <= 2:
        return normalizzato
    for posizione, etichetta in enumerate(etichette[:-2]):
        if etichetta in PREFISSI_ENTE:
            return ".".join(etichette[posizione:])
    if etichette[-2] in SUFFISSI_ESTESI:
        return ".".join(etichette[-3:])
    if etichette[-1] == "it" and _RE_SIGLA_PROVINCIA.fullmatch(etichette[-2]):
        return ".".join(etichette[-3:])
    return ".".join(etichette[-2:])


def _regex_pattern(modello: str) -> re.Pattern[str]:
    r"""`*` → «qualunque sequenza», tutto il resto letterale (come LIKE a DB).

    Il prefisso `(?:.*\.)?` e' la regola dei **sottodomini**, quella che le
    righe letterali hanno sempre avuto (`host == regola or host.endswith("." +
    regola)`) e che ai pattern mancava. La regola scritta in testa a questo
    modulo la promette per tutte le righe; l'implementazione la applicava solo
    alle letterali, e la differenza pesava:

        regione.basilicata.it               -> pattern      (combaciava)
        portalebandi.regione.basilicata.it  -> sconosciuto  (NON combaciava)
        bandi.regione.lombardia.it          -> sconosciuto
        agricoltura.regione.emilia-romagna.it -> sconosciuto

    Sono i portali dei bandi delle Regioni, cioe' proprio le pagine che il
    resolver cerca. `sconosciuto` fa fallire il gate duro `whitelist`, quindi
    quei candidati non venivano nemmeno valutati e il bando finiva
    `non_trovata`, che costa sessanta giorni di attesa.

    Misurato il 24/09/2026 su 900 bandi pubblicati fra `in_verifica` e
    `non_trovata`: 1 290 candidati classificati `sconosciuto`, di cui **705**
    diventano `pattern` con questa regola (698 per `regione.*.it`), e **330 dei
    900 bandi** guadagnano almeno un candidato ammissibile.

    `www.` non c'entra: quello lo toglie `dominio_di`, ed e' il motivo per cui
    `www.regione.veneto.it` combaciava mentre `bandi.regione.veneto.it` no.
    """
    pezzi = [re.escape(p) for p in modello.lower().split("*")]
    return re.compile(r"(?:.*\.)?" + ".*".join(pezzi) + r"\Z")


def _regola(host: str | None) -> str:
    """La forma con cui una riga della tabella si confronta: l'indice della
    `Tabella` e `combacia()` devono usare la stessa, o l'indice perderebbe
    righe che il confronto riga per riga trovava."""
    return (host or "").strip().lower()


def combacia(host: str | None, regola: str) -> bool:
    """Confronto unico di §16.3 punto 1, per una sola riga della tabella."""
    normalizzato = dominio_di(host)
    if not normalizzato or not regola:
        return False
    regola = _regola(regola)
    if "*" in regola:
        return bool(_regex_pattern(regola).match(normalizzato))
    return normalizzato == regola or normalizzato.endswith("." + regola)


# --- tabella ----------------------------------------------------------------

# Le due parti dell'indice di `Tabella`.
_WHITELIST, _BLOCCO = 0, 1


@dataclass(frozen=True)
class Tabella:
    """La whitelist in memoria: le righe di `dominio_ufficiale` piu' quelle che
    il codice conosce da solo (seed, host di `fonte`, IndicePA).

    Le righe restano in ordine di precedenza di costruzione: a parita' di host
    vince la prima, cioe' la riga che viene dal DB (il committente puo' avere
    corretto una confidenza a mano e quella correzione non va sovrascritta dal
    seed compilato dentro il codice).

    Dopo `python -m app domini --import` la tabella ha ~23 000 righe IndicePA, e
    il resolver la interroga per ogni candidato di ogni bando piu' una volta per
    link in `allegati`: `__post_init__` costruisce una volta sola l'indice che a
    DB sono i due indici parziali della migrazione 02 (host esatti in un dict,
    righe `pattern` a parte, blocklist separata dalla whitelist). La ricerca
    scorre le etichette dell'host — quattro o cinque `get` — invece delle righe.
    """
    righe: tuple[Dominio, ...] = ()

    def __post_init__(self) -> None:
        esatte: tuple[dict[str, tuple[int, Dominio]], ...] = ({}, {})
        modelli: tuple[list[tuple[int, Dominio]], ...] = ([], [])
        for posizione, riga in enumerate(self.righe):
            if not riga.attivo:
                continue
            # Parte 1 = blocklist, parte 0 = whitelist: sono due insiemi che non
            # si guardano mai insieme, perche' la blocklist prevale da sola.
            parte = _BLOCCO if riga.tipo == "aggregatore" else _WHITELIST
            if parte == _WHITELIST and riga.tipo not in PRECEDENZA:
                continue
            if riga.e_pattern:
                modelli[parte].append((posizione, riga))
                continue
            chiave = _regola(riga.host)
            if not chiave:
                continue
            precedente = esatte[parte].get(chiave)
            # Nella blocklist vince la prima riga in ordine di tabella, nella
            # whitelist la piu' forte: sono le due regole che la scansione riga
            # per riga applicava, e l'indice non puo' cambiarle.
            if precedente is None or (
                parte == _WHITELIST and _chiave_forza(riga) < _chiave_forza(precedente[1])
            ):
                esatte[parte][chiave] = (posizione, riga)
        object.__setattr__(self, "_esatte", esatte)
        object.__setattr__(self, "_modelli", modelli)

    @classmethod
    def da(cls, righe: "Tabella | Iterable[Dominio] | None") -> "Tabella":
        if isinstance(righe, Tabella):
            return righe
        return cls(tuple(righe or ()))

    def attive(self) -> tuple[Dominio, ...]:
        return tuple(r for r in self.righe if r.attivo)

    def blocklist(self) -> tuple[Dominio, ...]:
        return tuple(r for r in self.attive() if r.tipo == "aggregatore")

    def combacianti(self, host: str | None, *, blocco: bool = False) -> tuple[Dominio, ...]:
        """Tutte le righe attive che combaciano con l'host, in ordine di
        tabella. E' l'EXISTS del SQL: chi deve sapere se *esiste* una riga con
        una certa proprieta' guarda qui, non la riga piu' forte."""
        return tuple(riga for _, riga in self._combacianti(host, blocco))

    def migliore(self, host: str | None, *, blocco: bool = False) -> Dominio | None:
        """La riga che vince fra quelle che combaciano: nella blocklist la prima
        in ordine di tabella, nella whitelist la piu' forte (`_chiave_forza`,
        pareggi all'ordine di tabella)."""
        trovate = self._combacianti(host, blocco)
        if not trovate:
            return None
        if blocco:
            return min(trovate, key=lambda voce: voce[0])[1]
        return min(trovate, key=lambda voce: (_chiave_forza(voce[1]), voce[0]))[1]

    def _combacianti(self, host: str | None, blocco: bool) -> list[tuple[int, Dominio]]:
        normalizzato = dominio_di(host)
        if not normalizzato:
            return []
        parte = _BLOCCO if blocco else _WHITELIST
        esatte: dict[str, tuple[int, Dominio]] = self._esatte[parte]      # type: ignore[attr-defined]
        trovate: list[tuple[int, Dominio]] = []
        # Le righe non-pattern combaciano quando l'host e' la regola o termina
        # con '.' + regola: sono esattamente i suffissi dell'host.
        etichette = normalizzato.split(".")
        for taglio in range(len(etichette)):
            voce = esatte.get(".".join(etichette[taglio:]))
            if voce is not None:
                trovate.append(voce)
        for voce in self._modelli[parte]:                                 # type: ignore[attr-defined]
            if combacia(normalizzato, voce[1].host):
                trovate.append(voce)
        return trovate

    def corrispondenza(self, host: str | None) -> Dominio | None:
        return corrispondenza(host, self)

    def classifica(self, host: str | None) -> str:
        return classifica(host, self)


# Il seed come tabella indicizzata: `e_aggregatore()` senza argomenti la
# interroga per ogni link di ogni pagina, e ricostruirla a ogni chiamata
# significherebbe reindicizzare 52 righe ogni volta.
TABELLA_SEED: "Tabella" = Tabella(SEED)


def corrispondenza(host: str | None, tabella: "Tabella | Iterable[Dominio] | None") -> Dominio | None:
    """La riga che decide la sorte dell'host, o None se nessuna combacia.

    La blocklist si guarda per prima e da sola: un host che e' un aggregatore
    resta un aggregatore anche se qualcuno lo ha inserito pure come `ente`
    (per esempio un import IndicePA sbagliato). E' la regola «la blocklist
    prevale» di §5, qui e a DB.
    """
    tab = Tabella.da(tabella)
    bloccante = tab.migliore(host, blocco=True)
    if bloccante is not None:
        return bloccante
    return tab.migliore(host)


def _chiave_forza(riga: Dominio) -> tuple[int, float, int]:
    """Ordine di scelta fra righe che combaciano tutte: prima il tipo piu'
    forte, poi la confidenza piu' alta, poi la regola piu' specifica (l'host
    piu' lungo: `artea.toscana.it` batte `*.it`)."""
    return (PRECEDENZA.get(riga.tipo, 9), -riga.confidenza, -len(riga.host))


def classifica(host: str | None, tabella: "Tabella | Iterable[Dominio] | None") -> str:
    """Tipo del **dominio**: `ente | portale_pubblico | pattern | dedotto |
    aggregatore | sconosciuto`.

    Non e' il valore di `bando.fonte_ufficiale_tipo`, che ne ammette due: per
    quella colonna si passa da `tipo_fonte_ufficiale()` (§16.1 A11).
    """
    riga = corrispondenza(host, tabella)
    return riga.tipo if riga is not None else SCONOSCIUTO


def tipo_fonte_ufficiale(
    host: str | None, tabella: "Tabella | Iterable[Dominio] | None"
) -> str | None:
    """Il valore da scrivere in `bando.fonte_ufficiale_tipo`, o None.

    Mappatura unica di §16.1 A11: `ente → 'ente'`, `portale_pubblico →
    'portale_pubblico'`, `pattern | dedotto | aggregatore | sconosciuto →
    None`. Con None la fonte non puo' essere `trovata`: l'esito massimo e'
    `in_verifica`, perche' il CHECK della migrazione 01 non conosce altri
    valori e una colonna non scrivibile non si aggira scrivendoci lo stesso.
    """
    tipo = classifica(host, tabella)
    return tipo if tipo in TIPI_FONTE_UFFICIALE else None


def confidenza(host: str | None, tabella: "Tabella | Iterable[Dominio] | None") -> float:
    """Confidenza della riga piu' forte che combacia; 0,0 se l'host non e' in
    tabella. E' il numero che serve a `punteggia()`: per sapere se l'host puo'
    *verificare* un evento si usa `verificabile()`, che e' un EXISTS e non
    guarda solo la riga piu' forte."""
    riga = corrispondenza(host, tabella)
    return float(riga.confidenza) if riga is not None else 0.0


def e_aggregatore(host: str | None, tabella: "Tabella | Iterable[Dominio] | None" = None) -> bool:
    """Gemello di `bando_host_aggregatore(text)`: vero per l'host e per ogni suo
    sottodominio. Senza tabella usa la blocklist del seed, che e' la stessa che
    la migrazione 02 semina."""
    tab = TABELLA_SEED if tabella is None else Tabella.da(tabella)
    return tab.migliore(host, blocco=True) is not None


def verificabile(host: str | None, tabella: "Tabella | Iterable[Dominio] | None") -> bool:
    """Regola del trigger di `bando_evento`: un `url_prova` rende `verificato`
    un evento solo se il dominio e' `ente`, `portale_pubblico` o `pattern` con
    confidenza ≥ 0,80. Mai `dedotto`, mai un aggregatore (§5, §13.5).

    Come il SQL (`bando_dominio_verificante`, migrazione 04) e' un **EXISTS**:
    basta che *una* riga attiva che combacia abbia tipo e confidenza giusti. Non
    si guarda la sola riga piu' forte, altrimenti una riga `ente` corretta a
    mano a 0,60 — la via che il blocco «Riconciliazione» del seed documenta —
    nasconderebbe il pattern che a DB la renderebbe comunque verificante.
    """
    tab = Tabella.da(tabella)
    if tab.migliore(host, blocco=True) is not None:
        return False
    return any(
        riga.tipo in TIPI_VERIFICANTI and float(riga.confidenza) >= SOGLIA_VERIFICATO
        for riga in tab.combacianti(host)
    )


# --- costruzione della tabella ---------------------------------------------

def _chiave_host(host: str) -> str:
    """Chiave di dedup: i pattern non passano da `dominio_di` (il `*` non e' un
    carattere valido in un host)."""
    if "*" in host:
        return host.strip().lower()
    return dominio_di(host) or host.strip().lower()


def da_fonti(fonti: Iterable[Mapping[str, object]]) -> tuple[Dominio, ...]:
    """Host di `fonte.link` come domini `ente` con confidenza 1,0 (§5).

    Sono esclusi i tre aggregatori (449/450/451), ogni host che cade nella
    blocklist del seed — la blocklist prevale anche qui, e una fonte nuova su un
    aggregatore non deve poter promuovere quell'host a `ente` — e le fonti non
    `discoverable` quando la colonna e' presente: la riga di `fonte` e' la prova
    che quell'host pubblica bandi propri, non che sia un ente.
    """
    prodotte: list[Dominio] = []
    for fonte in fonti:
        identificativo = fonte.get("id")
        try:
            numero = int(identificativo) if identificativo is not None else None
        except (TypeError, ValueError):
            numero = None
        if numero is not None and numero in FONTI_ESCLUSE:
            continue
        if "discoverable" in fonte and not fonte.get("discoverable"):
            continue
        host = dominio_di(str(fonte.get("link") or ""))
        if not host or e_aggregatore(host):
            continue
        prodotte.append(Dominio(
            host=host, tipo="ente", confidenza=1.00, fonte_id=numero, origine="fonte",
        ))
    return tuple(prodotte)


_CAMPI_INDICEPA = {
    "sito_istituzionale": ("sito_istituzionale", "sitoistituzionale", "sito"),
    "denominazione": ("denominazione", "denominazione_ente", "nome"),
    "codice_ipa": ("codice_ipa", "cod_amm", "codiceipa"),
}


def _campo(riga: Mapping[str, object], nome: str) -> str:
    """Legge una colonna IndicePA tollerando maiuscole, spazi e underscore."""
    normalizzate = {
        str(chiave).strip().lower().replace(" ", "_"): valore
        for chiave, valore in riga.items()
    }
    for alias in _CAMPI_INDICEPA[nome]:
        valore = normalizzate.get(alias)
        if valore not in (None, ""):
            return str(valore).strip()
    return ""


def importa_indicepa(righe: Iterable[Mapping[str, object]]) -> tuple[Dominio, ...]:
    """Righe di `enti.xlsx` → domini `ente` con confidenza 1,0 (§5).

    Puro: il download e la lettura del foglio stanno in `python -m app
    domini --import`. Qui si scartano le righe senza sito, quelle il cui host
    non e' un host ASCII e — la blocklist prevale — quelle che cadono su un
    aggregatore. La prima riga di un host vince: IndicePA elenca piu' uffici
    sullo stesso dominio e la denominazione della prima e' arbitraria quanto
    quella delle altre, ma almeno e' deterministica.
    """
    viste: set[str] = set()
    prodotte: list[Dominio] = []
    for riga in righe:
        host = dominio_di(_campo(riga, "sito_istituzionale"))
        if not host or host in viste:
            continue
        if e_aggregatore(host):
            continue
        viste.add(host)
        prodotte.append(Dominio(
            host=host,
            tipo="ente",
            confidenza=1.00,
            ente=_campo(riga, "denominazione") or None,
            codice_ipa=_campo(riga, "codice_ipa") or None,
            origine="indicepa",
        ))
    return tuple(prodotte)


def costruisci(
    righe: Iterable[Dominio] = (),
    *,
    fonti: Iterable[Mapping[str, object]] = (),
    indicepa: Iterable[Mapping[str, object]] = (),
    dedotti: Iterable[str] = (),
    includi_seed: bool = True,
) -> Tabella:
    """Compone la tabella in memoria dalle quattro sorgenti di §5.

    Ordine di precedenza a parita' di host: righe della tabella a DB, host di
    `fonte.link`, IndicePA, host dedotti, seed compilato. Il seed resta per
    ultimo perche' e' l'unico che nessuno puo' correggere senza un rilascio.
    """
    accumulate: list[Dominio] = []
    viste: set[str] = set()

    def aggiungi(elenco: Iterable[Dominio]) -> None:
        for riga in elenco:
            chiave = _chiave_host(riga.host)
            if not chiave or chiave in viste:
                continue
            viste.add(chiave)
            accumulate.append(replace(riga, host=chiave))

    aggiungi(righe)
    aggiungi(da_fonti(fonti))
    aggiungi(importa_indicepa(indicepa))
    aggiungi(
        Dominio(host=h, tipo="dedotto", confidenza=CONFIDENZA_DEDOTTO, origine="dedotto")
        for h in (dominio_di(d) for d in dedotti) if h
    )
    if includi_seed:
        aggiungi(SEED)
    return Tabella(tuple(accumulate))


def host_dei_domini(righe: Sequence[Dominio]) -> tuple[str, ...]:
    """Comodita' per i report e per i test: i soli host, in ordine."""
    return tuple(r.host for r in righe)
