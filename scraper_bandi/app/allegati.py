# -*- coding: utf-8 -*-
"""Allegati deterministici della pagina ufficiale (piano §5, §13.4).

Perche' esiste
--------------
Oggi gli allegati li estrae il modello dentro `seo_skill` («estrai dal markdown
TUTTI i link a documenti»): un LLM che guarda un markdown non sa distinguere il
PDF dell'avviso dal PDF di un **bando correlato** che sta nella sidebar, e non
puo' garantire che l'URL risponda 2xx. §13.4 promette a BandoFit che ogni riga
leggibile di `bando_link` «ha risposto 2xx all'ultimo controllo e compare
nell'HTML della pagina di riferimento»: e' una promessa che solo del codice
deterministico puo' mantenere.

Qui dentro non c'e' nessuna rete: la verifica HTTP e' **iniettata**

    verifica(url) -> (esito_http, content_type, sha256_64k, etag, last_modified)

cosi' i test girano senza toccare niente, e in produzione la stessa funzione
sara' un sottile adattatore su `reachability._check_one` (HEAD con ripiego GET
su 405/501). Anche le sottopagine sono dati, non effetti: `estrai` dice **quali**
sottopagine varrebbe la pena aprire (httpx-only, massimo sei), il chiamante le
scarica e richiama `estrai` su ognuna, poi `unisci`.

Regole, tutte di §5:
  * si guarda **dentro** `<main>` (o la sezione del bando), dopo la stessa
    ripulitura di `impronte.pulisci`: i «bandi correlati» in sidebar sono gia'
    spariti prima che si legga il primo href;
  * sottopagine a un livello, stesso host, solo se figlie del percorso della
    pagina **oppure** con un'ancora che contiene ≥ 50 % dei token del titolo;
    le parole `normativa|modulistica|allegat|document|faq|avviso` da sole non
    bastano;
  * estensioni e content-type ammessi, 2xx obbligatorio, dedup, etichetta
    dall'ancora o dal nome del file;
  * forma fissa `{label, url, tipo}` (BandoFit legge `url` e `label`).
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urljoin, urlsplit

from . import impronte
from .dominio_ufficiale import Tabella, dominio_di, e_aggregatore
from .normalize import normalize_for_canonical

# --- costanti di §5 ---------------------------------------------------------

ESTENSIONI_AMMESSE: frozenset[str] = frozenset({
    "pdf", "doc", "docx", "xls", "xlsx", "odt", "ods", "zip", "rtf", "p7m",
})

CONTENT_TYPE_AMMESSI: dict[str, str] = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "application/pkcs7-mime": "p7m",
    "application/x-pkcs7-mime": "p7m",
}

MAX_SOTTOPAGINE = 6
QUOTA_TOKEN_ANCORA = 0.50
LUNGHEZZA_ETICHETTA = 120

# Da sole non fanno di un link una sottopagina da aprire (§5): sono le voci di
# navigazione di meta' dei siti istituzionali.
PAROLE_DEBOLI: frozenset[str] = frozenset({
    "normativa", "modulistica", "allegati", "allegato", "documenti",
    "documentazione", "faq", "avviso", "avvisi",
})

# Ancore che non dicono niente: l'etichetta si prende dal nome del file.
_ANCORE_GENERICHE = re.compile(
    r"^(?:scarica(?:\s+il\s+file)?|download|clicca\s+qui|qui|leggi(?:\s+tutto)?|"
    r"apri|vedi|link|file|allegato|documento|pdf)$",
    re.IGNORECASE,
)

# Un'ancora che promette un documento: basta a spendere una verifica HTTP su un
# URL senza estensione (`/download/1234`).
_ANCORA_DOCUMENTO = re.compile(
    r"allegat|modulistic|document|avviso|bando|domanda|modulo|decret|determin|"
    r"deliber|scarica|download|\bpdf\b|graduatori|faq",
    re.IGNORECASE,
)

_SCHEMI_VIETATI = ("mailto:", "tel:", "javascript:", "data:", "file:")


# --- tipi -------------------------------------------------------------------

@dataclass(frozen=True)
class Verifica:
    """Esito della verifica HTTP iniettata. Tutti i campi possono mancare."""
    esito_http: int | None = None
    content_type: str | None = None
    sha256: str | None = None
    etag: str | None = None
    last_modified: str | None = None

    @property
    def ok(self) -> bool:
        return self.esito_http is not None and 200 <= int(self.esito_http) < 300

    @classmethod
    def da(cls, valore: "Verifica | Sequence[object] | Mapping[str, object] | None") -> "Verifica | None":
        """Accetta la tupla di §5, un dizionario o un `Verifica` gia' pronto."""
        if valore is None or isinstance(valore, Verifica):
            return valore
        if isinstance(valore, Mapping):
            return cls(
                esito_http=_intero(valore.get("esito_http")),
                content_type=_stringa(valore.get("content_type")),
                sha256=_stringa(valore.get("sha256")),
                etag=_stringa(valore.get("etag")),
                last_modified=_stringa(valore.get("last_modified")),
            )
        pezzi = list(valore) + [None] * 5
        return cls(
            esito_http=_intero(pezzi[0]),
            content_type=_stringa(pezzi[1]),
            sha256=_stringa(pezzi[2]),
            etag=_stringa(pezzi[3]),
            last_modified=_stringa(pezzi[4]),
        )


@dataclass(frozen=True)
class Allegato:
    """Un allegato riconosciuto. `forma()` e' cio' che va in `bando.allegati`."""
    label: str
    url: str
    tipo: str
    origine: str = ""            # URL della pagina in cui l'href e' stato trovato
    ancora: str = ""
    verifica: Verifica | None = None

    def forma(self) -> dict[str, str]:
        """La forma fissa `{label, url, tipo}` di §13.4: nient'altro.

        BandoFit legge `url` e `label`: aggiungere chiavi qui significa
        cambiare un contratto, non arricchire un dizionario.
        """
        return {"label": self.label, "url": self.url, "tipo": self.tipo}


@dataclass(frozen=True)
class Scarto:
    url: str
    motivo: str


@dataclass(frozen=True)
class Estrazione:
    allegati: tuple[Allegato, ...] = ()
    sottopagine: tuple[str, ...] = ()
    scartati: tuple[Scarto, ...] = ()

    def forma(self) -> list[dict[str, str]]:
        return [a.forma() for a in self.allegati]


def _intero(valore: object) -> int | None:
    try:
        return int(valore)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _stringa(valore: object) -> str | None:
    if valore in (None, ""):
        return None
    return str(valore).strip() or None


# --- token e ambito ---------------------------------------------------------

def token(testo: str | None) -> frozenset[str]:
    """Token confrontabili di un titolo o di un'ancora: senza accenti, senza
    stopword italiane (`normalize.normalize_for_canonical`) e senza parole di
    due lettere, che combaciano per caso."""
    return frozenset(t for t in normalize_for_canonical(testo or "").split() if len(t) > 2)


def copertura(titolo: str | None, testo: str | None) -> float:
    """Quota dei token del titolo presenti nel testo (0,0-1,0)."""
    attesi = token(titolo)
    if not attesi:
        return 0.0
    presenti = token(testo)
    return len(attesi & presenti) / len(attesi)


def ambito(zuppa, titolo: str = ""):
    """Il nodo dentro cui si cercano gli href: `<main>`, il nodo con
    `role=main`, l'`<article>`, altrimenti la sezione il cui titolo combacia con
    quello del bando, altrimenti il corpo gia' ripulito."""
    for ricerca in (
        lambda: zuppa.find("main"),
        lambda: zuppa.find(attrs={"role": "main"}),
        lambda: zuppa.find("article"),
    ):
        nodo = ricerca()
        if nodo is not None:
            return nodo
    if titolo:
        for intestazione in zuppa.find_all(impronte.TITOLI):
            if copertura(titolo, intestazione.get_text(" ", strip=True)) >= QUOTA_TOKEN_ANCORA:
                genitore = intestazione.parent
                if genitore is not None and genitore.name not in ("body", "html"):
                    return genitore
    return zuppa.body or zuppa


# --- estrazione -------------------------------------------------------------

def estensione(url: str) -> str:
    """Estensione in minuscolo del percorso, senza il punto. '' se non c'e'."""
    percorso = urlsplit(url).path
    nome = posixpath.basename(unquote(percorso))
    if "." not in nome:
        return ""
    return nome.rsplit(".", 1)[-1].strip().lower()


def etichetta_da(ancora: str, url: str) -> str:
    """Etichetta dell'allegato: l'ancora se dice qualcosa, altrimenti il nome
    del file (senza estensione, con trattini e underscore sciolti)."""
    pulita = re.sub(r"\s+", " ", (ancora or "").strip())
    if pulita and not _ANCORE_GENERICHE.match(pulita):
        return pulita[:LUNGHEZZA_ETICHETTA]
    nome = posixpath.basename(unquote(urlsplit(url).path))
    if "." in nome:
        nome = nome.rsplit(".", 1)[0]
    nome = re.sub(r"[\-_+]+", " ", nome).strip()
    nome = re.sub(r"\s+", " ", nome)
    if nome:
        return (nome[:1].upper() + nome[1:])[:LUNGHEZZA_ETICHETTA]
    return (pulita or url)[:LUNGHEZZA_ETICHETTA]


def _e_figlia(url_pagina: str, url: str) -> bool:
    """Vero se `url` sta sotto il percorso della pagina (un livello o piu')."""
    base = urlsplit(url_pagina).path.rstrip("/")
    altro = urlsplit(url).path.rstrip("/")
    if not base or base == altro:
        return False
    return altro.startswith(base + "/")


def _ancora_forte(ancora: str, titolo: str) -> bool:
    """Ancora che vale una sottopagina: ≥ 50 % dei token del titolo, e non le
    sole parole deboli (`modulistica`, `documenti`, …)."""
    parole = token(ancora)
    if not parole or parole <= PAROLE_DEBOLI:
        return False
    return copertura(titolo, ancora) >= QUOTA_TOKEN_ANCORA


def estrai(
    html: str | None,
    url_pagina: str,
    titolo: str = "",
    *,
    verifica: Callable[[str], object] | None = None,
    blocklist: Tabella | Iterable[object] | None = None,
    max_sottopagine: int = MAX_SOTTOPAGINE,
) -> Estrazione:
    """Allegati e sottopagine di **una** pagina gia' scaricata.

    `verifica` e' la funzione iniettata di §5. Senza di lei gli allegati tornano
    non verificati (`verifica=None`) e **non** vanno scritti come
    `pubblicabile`: il 2xx e' una condizione del contratto, non un dettaglio.
    """
    if not html:
        return Estrazione()

    zuppa = impronte.pulisci(html)
    radice = ambito(zuppa, titolo)
    pagina_normalizzata = impronte.normalizza_url(url_pagina)

    allegati: list[Allegato] = []
    sottopagine: list[str] = []
    scartati: list[Scarto] = []
    viste: set[str] = set()

    for nodo in radice.find_all("a"):
        href = (nodo.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith(_SCHEMI_VIETATI):
            continue
        assoluto = urljoin(url_pagina, href)
        if urlsplit(assoluto).scheme not in ("http", "https"):
            continue
        normalizzato = impronte.normalizza_url(assoluto)
        if not normalizzato or normalizzato in viste:
            continue
        viste.add(normalizzato)
        if normalizzato == pagina_normalizzata:
            continue

        if _vietato(assoluto, blocklist):
            scartati.append(Scarto(assoluto, "dominio aggregatore"))
            continue

        ancora = nodo.get_text(" ", strip=True)
        ext = estensione(assoluto)

        if ext in ESTENSIONI_AMMESSE:
            esito = _verifica_e_componi(assoluto, ancora, ext, url_pagina, verifica)
            (allegati if isinstance(esito, Allegato) else scartati).append(esito)  # type: ignore[arg-type]
            continue

        stesso_host = dominio_di(assoluto) == dominio_di(url_pagina)
        # Prima le sottopagine, poi i documenti senza estensione: un link
        # figlio del percorso e' una pagina del bando, e chiederne il
        # content-type per scoprirlo sarebbe una richiesta buttata (e il
        # risultato dipenderebbe da cosa risponde il sito, non dalle regole).
        if stesso_host and (_e_figlia(url_pagina, assoluto) or _ancora_forte(ancora, titolo)):
            if len(sottopagine) >= max_sottopagine:
                scartati.append(Scarto(assoluto, "oltre il tetto delle sottopagine"))
            else:
                sottopagine.append(assoluto)
            continue

        if verifica is not None and _ANCORA_DOCUMENTO.search(ancora or ""):
            esito = _verifica_e_componi(assoluto, ancora, "", url_pagina, verifica)
            (allegati if isinstance(esito, Allegato) else scartati).append(esito)  # type: ignore[arg-type]
            continue

        scartati.append(Scarto(
            assoluto,
            "non figlia del percorso, ancora debole" if stesso_host
            else "host esterno senza documento",
        ))

    return Estrazione(tuple(allegati), tuple(sottopagine), tuple(scartati))


def _vietato(url: str, blocklist: Tabella | Iterable[object] | None) -> bool:
    if blocklist is None:
        return e_aggregatore(url)
    return e_aggregatore(url, blocklist)


def _verifica_e_componi(
    url: str,
    ancora: str,
    ext: str,
    url_pagina: str,
    verifica: Callable[[str], object] | None,
) -> Allegato | Scarto:
    """Applica la verifica iniettata e compone l'allegato, o dice perche' no."""
    esito = Verifica.da(verifica(url)) if verifica is not None else None
    tipo = ext
    if esito is not None:
        if not esito.ok:
            return Scarto(url, f"http {esito.esito_http}")
        principale = (esito.content_type or "").split(";", 1)[0].strip().lower()
        if not tipo:
            tipo = CONTENT_TYPE_AMMESSI.get(principale, "")
            if not tipo:
                return Scarto(url, f"content-type non ammesso: {principale or 'assente'}")
    if not tipo:
        return Scarto(url, "estensione non ammessa")
    return Allegato(
        label=etichetta_da(ancora, url),
        url=url,
        tipo=tipo,
        origine=url_pagina,
        ancora=ancora,
        verifica=esito,
    )


def unisci(*estrazioni: Estrazione, massimo: int | None = None) -> Estrazione:
    """Fonde le estrazioni della pagina e delle sue sottopagine.

    Dedup per URL normalizzato, vince la prima occorrenza (la pagina
    principale precede le sottopagine); l'etichetta generica viene sostituita
    da una parlante se una pagina successiva ne ha una migliore.
    """
    per_url: dict[str, Allegato] = {}
    sottopagine: list[str] = []
    scartati: list[Scarto] = []
    for estrazione in estrazioni:
        for allegato in estrazione.allegati:
            chiave = impronte.normalizza_url(allegato.url) or allegato.url
            esistente = per_url.get(chiave)
            if esistente is None:
                per_url[chiave] = allegato
            elif _etichetta_debole(esistente) and not _etichetta_debole(allegato):
                per_url[chiave] = allegato
        for pagina in estrazione.sottopagine:
            if pagina not in sottopagine:
                sottopagine.append(pagina)
        scartati.extend(estrazione.scartati)
    allegati = tuple(per_url.values())
    if massimo is not None:
        allegati = allegati[:max(massimo, 0)]
    return Estrazione(allegati, tuple(sottopagine), tuple(scartati))


def _etichetta_debole(allegato: Allegato) -> bool:
    return not allegato.ancora or bool(_ANCORE_GENERICHE.match(allegato.ancora.strip()))
