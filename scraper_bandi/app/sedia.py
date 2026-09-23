# -*- coding: utf-8 -*-
"""API SEDIA di EU Funding & Tenders (piano §5 passo 1, §6.2 pre-filtri).

Perche' esiste
--------------
Il portale Funding & Tenders e' una SPA: risponde 200 con una shell vuota, e
uno scrape ne ricava zero informazioni. Le due vie che funzionano davvero sono
l'API di ricerca SEDIA e il JSON del topic, e sono entrambe gratuite:

    POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=***
         corpo multipart con le parti `query`, `languages` e `sort`, ognuna
         **tipizzata** `;type=application/json` (senza il tipo l'API risponde 400)
    GET  https://ec.europa.eu/info/funding-tenders/opportunities/data/
         topicDetails/{identifier.lower()}.json      (con l'ID maiuscolo → 404)

Qui non si fa nessuna chiamata: il trasporto e' **iniettato**. `richiesta()`
compone la richiesta tipizzata, `analizza()` legge la risposta, `dettaglio()`
verifica il JSON del topic con la funzione che il chiamante gli passa. Cosi' i
test girano offline e la regola di accettazione — la parte che conta — si puo'
provare riga per riga.

Regola di accettazione (§5, gate anti-allucinazione): un risultato SEDIA vale
come fonte solo se **l'identifier coincide** e **almeno il 60 % dei token del
titolo del bando compare nel titolo SEDIA**. Nessun URL nasce da un modello:
`url_topic` costruisce l'indirizzo solo da un identifier gia' verificato.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date as date_cls, datetime as datetime_cls
from typing import Any, Callable, Iterable, Mapping, Sequence

from .normalize import normalize_for_canonical

URL_RICERCA = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
CHIAVE_API = "SEDIA"
MODELLO_TOPIC = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{}.json"
)

# I tre tipi di record che contengono bandi (misurati: 1 334 risultati).
TIPI_PREDEFINITI: tuple[str, ...] = ("1", "2", "8")

# Codici di stato del portale, e la loro traduzione nel vocabolario di §4.
CODICI_STATO: dict[str, str] = {
    "31094501": "forthcoming",
    "31094502": "open",
    "31094503": "closed",
}
STATO_BANDO: dict[str, str] = {
    "forthcoming": "in apertura prossimamente",
    "open": "aperto",
    "closed": "chiuso",
}

QUOTA_TOKEN_TITOLO = 0.60
PER_PAGINA_PREDEFINITO = 50

# L'identifier di un topic: `HORIZON-CL2-2026-01-DEMOCRACY-01`, `ERASMUS-EDU-2026-PI`.
RE_IDENTIFIER = re.compile(r"\b[A-Z0-9]+-\d{4}-[A-Z0-9-]+\b")
# Per estrarlo da un titolo serve il token intero: la regex sopra, cercata in
# «HORIZON-CL2-2026-01-X», partirebbe da «CL2» e restituirebbe un identifier
# troncato, che non combacerebbe con niente (o peggio, con un altro topic).
_RE_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9-]*")
_RE_IDENTIFIER_SICURO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# --- richiesta --------------------------------------------------------------

@dataclass(frozen=True)
class Parte:
    """Una parte del multipart, con il suo tipo dichiarato."""
    nome: str
    contenuto: str
    tipo_contenuto: str = "application/json"


@dataclass(frozen=True)
class Richiesta:
    """Richiesta SEDIA pronta da eseguire, senza dipendere da httpx."""
    url: str
    parametri: tuple[tuple[str, str], ...]
    parti: tuple[Parte, ...]

    def files(self) -> dict[str, tuple[None, str, str]]:
        """Forma attesa da `httpx.post(..., files=...)`: ogni parte porta il
        proprio `;type=application/json`, che e' il motivo per cui questa
        chiamata funziona e una `data=` no."""
        return {p.nome: (None, p.contenuto, p.tipo_contenuto) for p in self.parti}

    def parte(self, nome: str) -> str:
        for p in self.parti:
            if p.nome == nome:
                return p.contenuto
        return ""


def _json(valore: Any) -> str:
    """JSON deterministico: stesse chiavi, stesso ordine, stesso byte."""
    return json.dumps(valore, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def codice_stato(stato: str) -> str:
    """Accetta il codice numerico o l'etichetta (`open`, `forthcoming`, `closed`)."""
    testo = str(stato).strip().lower()
    if testo in CODICI_STATO:
        return testo
    for codice, etichetta in CODICI_STATO.items():
        if etichetta == testo:
            return codice
    return testo


def richiesta(
    testo: str = "***",
    *,
    tipi: Sequence[str] = TIPI_PREDEFINITI,
    stati: Sequence[str] = (),
    identificatori: Sequence[str] = (),
    pagina: int = 1,
    per_pagina: int = PER_PAGINA_PREDEFINITO,
    lingue: Sequence[str] = ("it", "en"),
    ordinamento: Mapping[str, str] | None = None,
) -> Richiesta:
    """Compone la ricerca. `text='***'` significa «tutto»: il filtro vero sta
    nella parte `query`, non nella stringa di ricerca."""
    condizioni: list[dict[str, Any]] = []
    if tipi:
        condizioni.append({"terms": {"type": [str(t) for t in tipi]}})
    if stati:
        condizioni.append({"terms": {"status": [codice_stato(s) for s in stati]}})
    if identificatori:
        condizioni.append({"terms": {"identifier": [str(i).upper() for i in identificatori]}})
    query: dict[str, Any] = {"bool": {"must": condizioni}} if condizioni else {"match_all": {}}

    parametri = (
        ("apiKey", CHIAVE_API),
        ("text", testo or "***"),
        ("pageSize", str(max(int(per_pagina), 1))),
        ("pageNumber", str(max(int(pagina), 1))),
    )
    parti = (
        Parte("query", _json(query)),
        Parte("languages", _json([str(l) for l in lingue])),
        Parte("sort", _json(dict(ordinamento or {"field": "sortStatus", "order": "ASC"}))),
    )
    return Richiesta(URL_RICERCA, parametri, parti)


# --- risposta ---------------------------------------------------------------

@dataclass(frozen=True)
class Informazione:
    """Una voce di `latestInfos`: e' una delle prove indipendenti del gate G7."""
    data: date_cls | None
    testo: str


@dataclass(frozen=True)
class Risultato:
    identifier: str
    call_identifier: str = ""
    titolo: str = ""
    stato: str = ""                     # forthcoming | open | closed
    stato_codice: str = ""
    apertura: date_cls | None = None
    scadenze: tuple[date_cls, ...] = ()
    ultime_informazioni: tuple[Informazione, ...] = ()
    url: str | None = None

    @property
    def stato_bando(self) -> str | None:
        """Lo stato nel vocabolario di §4, o None se SEDIA non lo dice."""
        return STATO_BANDO.get(self.stato)

    @property
    def scadenza(self) -> date_cls | None:
        """La scadenza piu' lontana: SEDIA ne elenca una per ogni fase."""
        return max(self.scadenze) if self.scadenze else None


def _valore(metadati: Mapping[str, Any], *nomi: str) -> str:
    for nome in nomi:
        valore = metadati.get(nome)
        if isinstance(valore, (list, tuple)):
            valore = valore[0] if valore else None
        if valore not in (None, ""):
            return str(valore).strip()
    return ""


def _valori(metadati: Mapping[str, Any], nome: str) -> tuple[str, ...]:
    valore = metadati.get(nome)
    if valore in (None, ""):
        return ()
    if isinstance(valore, (list, tuple)):
        return tuple(str(v).strip() for v in valore if str(v).strip())
    return (str(valore).strip(),)


def data_sedia(valore: str | None) -> date_cls | None:
    """Le tre scritture che SEDIA usa davvero: ISO con fuso, ISO nuda e la
    forma a trattini `2026-12-01-17-00-00`."""
    if not valore:
        return None
    testo = str(valore).strip()
    if not testo:
        return None
    pezzi = testo.split("-")
    if len(pezzi) >= 6 and all(p.isdigit() for p in pezzi[:6]):
        testo = "-".join(pezzi[:3])
    try:
        return datetime_cls.fromisoformat(testo.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date_cls.fromisoformat(testo[:10])
    except ValueError:
        return None


def url_topic(identifier: str | None) -> str | None:
    """URL deterministico del JSON del topic, in minuscolo (con l'identifier in
    maiuscolo il portale risponde 404).

    None se l'identifier non e' fatto di caratteri sicuri: un URL non si
    costruisce mai da una stringa che non si e' guardata (gate di §5).
    """
    if not identifier:
        return None
    pulito = str(identifier).strip()
    if not pulito or not _RE_IDENTIFIER_SICURO.match(pulito):
        return None
    return MODELLO_TOPIC.format(pulito.lower())


def analizza(payload: Mapping[str, Any] | None) -> tuple[Risultato, ...]:
    """Legge la risposta della ricerca. Tollera i metadati scalari e quelli in
    lista (SEDIA usa entrambe le forme a seconda del campo)."""
    if not payload:
        return ()
    risultati = payload.get("results") or []
    letti: list[Risultato] = []
    for voce in risultati:
        if not isinstance(voce, Mapping):
            continue
        metadati = voce.get("metadata")
        metadati = metadati if isinstance(metadati, Mapping) else {}
        identifier = _valore(metadati, "identifier") or str(voce.get("reference") or "").strip()
        if not identifier:
            continue
        codice = _valore(metadati, "status")
        informazioni = tuple(
            Informazione(data_sedia(_data_informazione(i)), _testo_informazione(i))
            for i in _elenco_informazioni(metadati)
        )
        letti.append(Risultato(
            identifier=identifier,
            call_identifier=_valore(metadati, "callIdentifier"),
            titolo=_valore(metadati, "title") or str(voce.get("title") or "").strip(),
            # `status` arriva come codice; si accetta anche l'etichetta gia'
            # sciolta, che e' cio' che scrive chi costruisce una fixture a mano.
            stato=CODICI_STATO.get(codice) or (codice if codice in CODICI_STATO.values() else ""),
            stato_codice=codice,
            apertura=data_sedia(_valore(metadati, "startDate")),
            scadenze=tuple(
                d for d in (data_sedia(v) for v in _valori(metadati, "deadlineDate")) if d
            ),
            ultime_informazioni=informazioni,
            url=url_topic(identifier),
        ))
    return tuple(letti)


def _elenco_informazioni(metadati: Mapping[str, Any]) -> tuple[Any, ...]:
    grezzo = metadati.get("latestInfos")
    if not grezzo:
        return ()
    if isinstance(grezzo, (list, tuple)):
        voci = grezzo
    else:
        voci = (grezzo,)
    lette: list[Any] = []
    for voce in voci:
        if isinstance(voce, str):
            try:
                voce = json.loads(voce)
            except ValueError:
                pass
        if isinstance(voce, (list, tuple)):
            lette.extend(voce)
        else:
            lette.append(voce)
    return tuple(lette)


def _data_informazione(voce: Any) -> str:
    if isinstance(voce, Mapping):
        for nome in ("date", "publicationDate", "updateDate"):
            if voce.get(nome):
                return str(voce[nome])
    return ""


def _testo_informazione(voce: Any) -> str:
    if isinstance(voce, Mapping):
        for nome in ("summary", "text", "title", "description"):
            if voce.get(nome):
                return re.sub(r"\s+", " ", str(voce[nome])).strip()
        return _json(voce)
    return re.sub(r"\s+", " ", str(voce)).strip()


# --- accettazione -----------------------------------------------------------

def identificatori(testo: str | None) -> tuple[str, ...]:
    """Gli identifier F&T contenuti in un testo, in ordine e senza doppioni.

    Si estrae il **token intero** che contiene la forma `…-AAAA-…`: restituire
    un pezzo dell'identifier significherebbe chiedere a SEDIA un topic che non
    esiste, o peggio un topic diverso.
    """
    if not testo:
        return ()
    trovati: list[str] = []
    for token in _RE_TOKEN.finditer(str(testo)):
        candidato = token.group(0).strip("-")
        if not RE_IDENTIFIER.search(candidato):
            continue
        if candidato not in trovati:
            trovati.append(candidato)
    return tuple(trovati)


def copertura_titolo(titolo: str | None, titolo_sedia: str | None) -> float:
    """Quota dei token del titolo del bando presenti nel titolo SEDIA."""
    attesi = {t for t in normalize_for_canonical(titolo or "").split() if len(t) > 2}
    if not attesi:
        return 0.0
    presenti = {t for t in normalize_for_canonical(titolo_sedia or "").split() if len(t) > 2}
    return len(attesi & presenti) / len(attesi)


def accetta(
    risultato: Risultato,
    identifier: str | None,
    titolo: str | None,
    *,
    quota: float = QUOTA_TOKEN_TITOLO,
) -> bool:
    """Le due condizioni di §5, entrambe obbligatorie: identifier coincidente e
    almeno `quota` dei token del titolo nel titolo SEDIA."""
    if not identifier or not risultato.identifier:
        return False
    if risultato.identifier.strip().upper() != str(identifier).strip().upper():
        return False
    return copertura_titolo(titolo, risultato.titolo) >= quota


def scegli(
    risultati: Iterable[Risultato],
    identifier: str | None,
    titolo: str | None,
    *,
    quota: float = QUOTA_TOKEN_TITOLO,
) -> Risultato | None:
    """Il primo risultato accettabile, o None. Non esiste un «migliore»: o le
    due condizioni valgono, o il candidato non entra."""
    for risultato in risultati:
        if accetta(risultato, identifier, titolo, quota=quota):
            return risultato
    return None


def cerca(
    trasporto: Callable[[Richiesta], Mapping[str, Any] | None],
    richiesta_: Richiesta,
) -> tuple[Risultato, ...]:
    """Esegue la ricerca con il trasporto iniettato e legge la risposta."""
    return analizza(trasporto(richiesta_))


def identifier_nel_json(dato: Any, identifier: str) -> bool:
    """Vero se l'identifier compare come stringa dentro il JSON del topic.

    E' il secondo gate di §5 sul passo F&T: l'URL e' deterministico, ma finche'
    non si legge l'identifier dentro la risposta non si sa se e' il topic giusto.
    """
    atteso = str(identifier or "").strip().casefold()
    if not atteso:
        return False
    if isinstance(dato, str):
        return atteso in dato.casefold()
    if isinstance(dato, Mapping):
        return any(identifier_nel_json(v, identifier) for v in dato.values())
    if isinstance(dato, (list, tuple, set)):
        return any(identifier_nel_json(v, identifier) for v in dato)
    return False


def dettaglio(
    identifier: str | None,
    trasporto: Callable[[str], tuple[int, Any] | None],
) -> tuple[str, Any] | None:
    """`topicDetails/{id}.json` con il trasporto iniettato.

    `trasporto(url)` restituisce `(stato_http, payload)`. Si accetta solo un 200
    il cui payload contiene l'identifier: qualunque altra risposta vale «non
    trovato», mai «trovato senza prova».
    """
    url = url_topic(identifier)
    if not url:
        return None
    esito = trasporto(url)
    if not esito:
        return None
    stato, payload = esito
    if int(stato) != 200 or not identifier_nel_json(payload, identifier or ""):
        return None
    return url, payload
