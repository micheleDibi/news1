# -*- coding: utf-8 -*-
"""Rigenerazione mirata del contenuto dopo un evento (piano §6.2).

Il problema
-----------
Quando il monitor accerta che una scadenza e' stata prorogata, aggiornare la
colonna non basta: nel corpo dell'articolo restano frasi come «le domande vanno
presentate entro il 6 ottobre 2026». Il lettore legge la prosa, non la colonna,
e trova due verita' diverse nella stessa pagina.

Rigenerare l'intero contenuto con un modello sarebbe la soluzione piu' cara e
la meno sicura: ogni rigenerazione e' un'occasione per perdere un paragrafo,
cambiare un importo o riscrivere il titolo. Qui si procede per gradi, dal piu'
economico e piu' sicuro al meno:

1. **box «Aggiornamenti»** — reso dal frontend dagli eventi con
   `in_aggiornamenti=true`. Zero token, zero rischi, sempre disponibile;
2. **sostituzione deterministica** — la data vecchia si sostituisce con la
   nuova **solo nelle frasi che contengono una parola del ruolo giusto**
   («entro», «scadenza» per la scadenza; «dal», «apertura» per l'apertura).
   Copre ~70 % dei casi senza chiamare nessun modello. Il vincolo sul ruolo e'
   cio' che impedisce di riscrivere la data di un decreto citato;
3. **riscrittura dei soli paragrafi** che contengono ancora la data vecchia,
   con gate severi sul risultato;
4. se dopo tre tentativi il gate non passa, **si pubblica comunque il box
   templato**: meglio una scheda con il contenuto vecchio e un avviso in cima
   che una scheda riscritta male.

Due regole di scrittura che non si negoziano (§6.2 punto 4): si scrive con
`update_bando_completed(..., gia_pubblicato=True)`, che toglie dal payload
`slug` **e** `titolo` — lo slug e' l'URL pubblico, il titolo e' uno snapshot
dentro `saved_bandi` e `consultation_requests` di BandoFit.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from . import bilancio, telemetria
from .date_validation import estrai_date_con_ruolo, norm_cit
from .logger import logger
from .stato_bando import data_italiana, oggi_roma

TENTATIVI_MASSIMI = 3

# §6.2: la descrizione breve resta dentro la finestra SEO gia' in uso.
DESCRIZIONE_MIN = 180
DESCRIZIONE_MAX = 320

# Parole che autorizzano la sostituzione di una data, per ruolo. Sono le stesse
# di `date_validation._PAROLE_RUOLO`, ma qui servono a decidere se una FRASE
# parla di quel ruolo, non a dedurre il ruolo di una data.
PAROLE_RUOLO: dict[str, re.Pattern[str]] = {
    "scadenza": re.compile(r"\bscadenz\w*|\bentro\b|\btermin[ei]\b|\bfino al\b|\bchius\w*|\bprorog\w*", re.I),
    "apertura": re.compile(r"\bapertur\w*|\ba partire\b|\bdecorr\w*|\bdal(?:le)?\b|\bapre\b", re.I),
    "pubblicazione": re.compile(r"\bpubblicat\w*|\bBUR\w*|\bGURI\b", re.I),
}

# Fine frase: punto, punto e virgola, punto esclamativo o interrogativo seguiti
# da spazio, oppure un a capo. Serve a isolare la frase in cui la data vive,
# che e' l'unita' su cui si decide.
#
# I due punti NON chiudono una frase: introducono. Nelle schede dei bandi la
# forma piu' comune e' proprio l'etichetta («Scadenza: 06/10/2026», «termini:
# dal 22 ottobre al 1° dicembre 2026»), e spezzare li' separerebbe la data
# dalla parola che ne dichiara il ruolo — cioe' proprio i casi che vanno
# sostituiti.
_FINE_FRASE = re.compile(r"(?<=[.;!?])\s+|\n+")

# Importi in euro: il gate li confronta prima e dopo la riscrittura.
_IMPORTO = re.compile(r"\d[\d.\s]*(?:,\d+)?\s*(?:€|euro|mln|milioni|mila)", re.I)

# Voce del box «Aggiornamenti», una per tipo di evento (§6.2 punto 1).
MODELLI_VOCE: dict[str, str] = {
    "proroga": "Termine prorogato al {data}.",
    "apertura": "Domande aperte dal {data}.",
    "riapertura": "Bando riaperto: domande dal {data}.",
    "chiusura": "Sportello chiuso in anticipo il {data}.",
    "sospensione": "Bando sospeso secondo {ente} il {data}.",
    "revoca": "Bando revocato secondo {ente} il {data}.",
    "annullamento_revoca": "Revoca annullata: il bando torna valido dal {data}.",
    "graduatoria": "Pubblicata la graduatoria il {data}.",
    "esito": "Pubblicati gli esiti il {data}.",
    "faq": "Pubblicate nuove FAQ il {data}.",
    "nuovo_allegato": "Pubblicato un nuovo documento il {data}.",
    "rettifica:data_apertura": "Apertura differita al {data}.",
    "rettifica:data_scadenza": "Nuovo termine per la presentazione: {data}.",
    "rettifica:contenuto": "Il testo del bando e' stato rettificato il {data}.",
    "rettifica:allegati": "Gli allegati del bando sono stati aggiornati il {data}.",
    "rettifica": "Il bando e' stato rettificato il {data}.",
}

VOCE_PREDEFINITA = "Aggiornamento pubblicato dall'ente il {data}."


@dataclass(frozen=True)
class Voce:
    """Una riga del box «Aggiornamenti»."""
    testo: str
    data: date_cls | None = None
    url: str = ""
    tipo: str = ""

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "testo": self.testo,
            "data": self.data.isoformat() if self.data else None,
            "url": self.url,
            "tipo": self.tipo,
        }


def voce_aggiornamento(evento: Mapping[str, Any], *, ente: str | None = None) -> Voce:
    """La voce templata del box, dal payload di `bando_evento`.

    Non c'e' nessun modello di mezzo: il box deve funzionare anche quando la
    rigenerazione fallisce, ed e' la sola cosa che il piano garantisce sempre.
    """
    tipo = str(evento.get("tipo") or "")
    campo = str(evento.get("campo") or "")
    chiave = f"{tipo}:{campo}" if campo else tipo
    modello = MODELLI_VOCE.get(chiave) or MODELLI_VOCE.get(tipo) or VOCE_PREDEFINITA

    quando = _data(evento.get("data_evento")) or _data(evento.get("rilevato_at"))
    dopo = evento.get("valore_dopo")
    if isinstance(dopo, Mapping) and campo in ("data_apertura", "data_scadenza"):
        quando = _data(dopo.get(campo)) or quando
    if quando is None:
        quando = oggi_roma()

    testo = modello.format(
        data=data_italiana(quando),
        ente=(ente or evento.get("dominio_prova") or "la fonte ufficiale"),
    )
    return Voce(testo=testo, data=quando, url=str(evento.get("url_prova") or ""), tipo=tipo)


def box_aggiornamenti(
    eventi: Iterable[Mapping[str, Any]], *, ente: str | None = None,
) -> tuple[Voce, ...]:
    """Tutte le voci del box, dalla piu' recente. Solo `in_aggiornamenti=true`."""
    voci = [
        voce_aggiornamento(e, ente=ente)
        for e in eventi
        if e.get("in_aggiornamenti") and e.get("leggibile")
    ]
    return tuple(sorted(voci, key=lambda v: (v.data or date_cls.min), reverse=True))


# --- sostituzione deterministica -------------------------------------------

def _forma(testo_data: str) -> str:
    """Forma tipografica della data trovata: `iso`, `numerica` o `estesa`."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", testo_data):
        return "iso"
    if re.search(r"[/.\-]", testo_data):
        return "numerica"
    return "estesa"


def rendi_data(giorno: date_cls, forma: str, *, campione: str = "") -> str:
    """La data nuova scritta come era scritta quella vecchia.

    Sostituire «6 ottobre 2026» con «2026-12-01» sarebbe corretto e illeggibile:
    la forma la detta il testo, non il database. Il separatore della forma
    numerica si copia dal campione, cosi' `06.10.2026` non diventa `01/12/2026`.
    """
    if forma == "iso":
        return giorno.isoformat()
    if forma == "numerica":
        separatore = next((c for c in campione if c in "/.-"), "/")
        return f"{giorno.day:02d}{separatore}{giorno.month:02d}{separatore}{giorno.year}"
    return data_italiana(giorno)


def frasi(testo: str) -> list[tuple[int, int]]:
    """Gli intervalli (inizio, fine) delle frasi del testo."""
    limiti = [0]
    for m in _FINE_FRASE.finditer(testo):
        limiti.append(m.end())
    limiti.append(len(testo))
    intervalli: list[tuple[int, int]] = []
    for i in range(len(limiti) - 1):
        inizio, fine = limiti[i], limiti[i + 1]
        if fine > inizio:
            intervalli.append((inizio, fine))
    return intervalli


def _frase_di(intervalli: Sequence[tuple[int, int]], posizione: int) -> tuple[int, int]:
    for inizio, fine in intervalli:
        if inizio <= posizione < fine:
            return (inizio, fine)
    return (0, 0)


def sostituisci_data(
    testo: str, vecchia: date_cls, nuova: date_cls, ruolo: str,
) -> tuple[str, int]:
    """Sostituisce `vecchia` con `nuova`, solo nelle frasi che parlano di `ruolo`.

    Ritorna (testo nuovo, numero di sostituzioni). Le date con ruolo
    `normativa` non si toccano mai: «ai sensi del DD 12 del 6 ottobre 2026» e'
    l'atto che ha disposto la proroga, e riscriverlo falsificherebbe la fonte.
    """
    if not testo or vecchia == nuova:
        return testo, 0
    modello = PAROLE_RUOLO.get(ruolo)
    if modello is None:
        return testo, 0

    intervalli = frasi(testo)
    sostituzioni: list[tuple[int, int, str]] = []
    for trovata in estrai_date_con_ruolo(testo):
        if trovata.data != vecchia or trovata.ruolo == "normativa":
            continue
        inizio, fine = _frase_di(intervalli, trovata.inizio)
        if fine <= inizio:
            continue
        if not modello.search(testo[inizio:fine]):
            # La frase non parla di questo ruolo: e' una data di contesto.
            continue
        originale = testo[trovata.inizio:trovata.fine]
        sostituzioni.append((
            trovata.inizio, trovata.fine,
            rendi_data(nuova, _forma(originale), campione=originale),
        ))

    if not sostituzioni:
        return testo, 0
    pezzi: list[str] = []
    cursore = 0
    for inizio, fine, nuovo in sostituzioni:
        pezzi.append(testo[cursore:inizio])
        pezzi.append(nuovo)
        cursore = fine
    pezzi.append(testo[cursore:])
    return "".join(pezzi), len(sostituzioni)


def paragrafi(testo: str) -> list[str]:
    """I paragrafi del contenuto (separatore: riga vuota)."""
    return re.split(r"\n\s*\n", testo or "")


def paragrafi_con_data(testo: str, giorno: date_cls) -> tuple[int, ...]:
    """Indici dei paragrafi in cui la data compare ancora (ruolo non normativo)."""
    trovati: list[int] = []
    for indice, paragrafo in enumerate(paragrafi(testo)):
        for trovata in estrai_date_con_ruolo(paragrafo):
            if trovata.data == giorno and trovata.ruolo != "normativa":
                trovati.append(indice)
                break
    return tuple(trovati)


# --- gate della riscrittura -------------------------------------------------

#: Un URL dentro il testo. Serve al gate di invarianza: una riscrittura che
#: sposta una data non ha mai motivo di toccare un link, e CLAUDE.md lo dice
#: esplicitamente («gli URL non vanno toccati»). La classe di caratteri si
#: ferma su spazi, virgolette, parentesi e angolari: sono i delimitatori con
#: cui un URL finisce dentro una frase o dentro un JSON.
_URL = re.compile(r"""https?://[^\s"'<>)\]]+""")


def _url(testo: str) -> set[str]:
    return set(_URL.findall(testo or ""))


def _date_non_normative(testo: str) -> set[date_cls]:
    return {d.data for d in estrai_date_con_ruolo(testo) if d.ruolo != "normativa"}


def _importi(testo: str) -> set[str]:
    return {norm_cit(m.group(0)).replace(" ", "") for m in _IMPORTO.finditer(testo or "")}


def _maiuscole(testo: str) -> set[str]:
    """Nomi propri approssimati: parole con l'iniziale maiuscola dentro la frase.

    Non e' un NER: e' una cintura contro la riscrittura che cambia «Regione
    Lazio» in «Regione Lazio e Lazio Innova». Bastano le differenze, non la
    classificazione.
    """
    return {
        p for p in re.findall(r"\b[A-ZÀ-Þ][a-zà-ÿ']{2,}\b", testo or "")
    }


@dataclass(frozen=True)
class EsitoGate:
    ammesso: bool = False
    motivi: tuple[str, ...] = ()

    @property
    def motivo(self) -> str:
        return "; ".join(self.motivi)


def gate_riscrittura(
    prima: str,
    dopo: str,
    *,
    vecchia: date_cls,
    nuova: date_cls,
    descrizione_breve: str | None = None,
) -> EsitoGate:
    """I quattro gate di §6.2 sulla riscrittura mirata.

    Sono tutti negativi: nessuno dice «e' scritto bene», tutti dicono «non ha
    rotto niente». E' l'unica cosa che si puo' verificare senza rileggere.
    """
    # Invarianza degli URL, per prima e da sola: se un link e' cambiato la
    # riscrittura si butta senza nemmeno guardare il resto. Un URL fabbricato
    # e' un danno di natura diversa da una data sbagliata — porta il lettore
    # su una pagina che non e' mai esistita — e non c'e' nessun caso in cui
    # una sostituzione di data debba produrlo.
    if _url(prima) != _url(dopo):
        return EsitoGate(ammesso=False, motivi=("la riscrittura ha cambiato un URL",))

    motivi: list[str] = []
    date_dopo = _date_non_normative(dopo)
    if nuova not in date_dopo:
        motivi.append(f"la data nuova {nuova.isoformat()} non compare nel testo riscritto")
    if vecchia in date_dopo:
        motivi.append(f"la data vecchia {vecchia.isoformat()} e' ancora nel testo riscritto")

    altre_prima = _date_non_normative(prima) - {vecchia, nuova}
    altre_dopo = date_dopo - {vecchia, nuova}
    if altre_prima != altre_dopo:
        motivi.append("altre date cambiate dalla riscrittura")

    if _importi(prima) != _importi(dopo):
        motivi.append("importi cambiati dalla riscrittura")

    persi = _maiuscole(prima) - _maiuscole(dopo)
    if persi:
        motivi.append("nomi propri spariti: " + ", ".join(sorted(persi)[:5]))

    if descrizione_breve is not None:
        lunghezza = len(descrizione_breve.strip())
        if not (DESCRIZIONE_MIN <= lunghezza <= DESCRIZIONE_MAX):
            motivi.append(
                f"descrizione_breve di {lunghezza} caratteri (attesi {DESCRIZIONE_MIN}-{DESCRIZIONE_MAX})")

    return EsitoGate(ammesso=not motivi, motivi=tuple(motivi))


# --- orchestrazione ---------------------------------------------------------

@dataclass
class Rigenerazione:
    """Esito della rigenerazione di un bando."""
    bando_id: Any = None
    via: str = "box"                  # box | sostituzione | riscrittura
    sostituzioni: int = 0
    sostituzioni_descrizione: int = 0
    tentativi: int = 0
    scritto: bool = False
    voci: tuple[Voce, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    motivi: tuple[str, ...] = ()

    def come_dizionario(self) -> dict[str, Any]:
        return {
            "bando_id": self.bando_id,
            "via": self.via,
            "sostituzioni": self.sostituzioni,
            "sostituzioni_descrizione": self.sostituzioni_descrizione,
            "tentativi": self.tentativi,
            "scritto": self.scritto,
            "voci": [v.come_dizionario() for v in self.voci],
            "motivi": list(self.motivi),
        }


async def rigenera(
    bando: Mapping[str, Any],
    evento: Mapping[str, Any],
    *,
    vecchia: date_cls | None = None,
    nuova: date_cls | None = None,
    ruolo: str = "scadenza",
    attivo: bool = False,
    riscrittore: Callable[[str, date_cls, date_cls], Awaitable[str]] | None = None,
    scrivi: Callable[[Any, dict[str, Any]], Awaitable[bool]] | None = None,
    tentativi_massimi: int = TENTATIVI_MASSIMI,
) -> Rigenerazione:
    """Porta il contenuto in linea con la data nuova. Non solleva mai.

    `scrivi(bando_id, payload)` e' l'adattatore su
    `db.update_bando_completed(..., gia_pubblicato=True)`: qui dentro non si
    importa il DB, cosi' il modulo resta verificabile senza rete.
    """
    esito = Rigenerazione(bando_id=bando.get("id"))
    esito.voci = (voce_aggiornamento(evento),)

    contenuto = str(bando.get("contenuto") or "")
    if vecchia is None or nuova is None or not contenuto:
        # Nessuna data da sostituire: il box templato e' gia' tutto cio' che
        # serve, ed e' un esito legittimo, non un fallimento.
        esito.motivi = ("nessuna data da sostituire: solo box",)
        return esito

    # Passo 2: sostituzione deterministica.
    testo, sostituzioni = sostituisci_data(contenuto, vecchia, nuova, ruolo)
    esito.sostituzioni = sostituzioni
    if sostituzioni:
        esito.via = "sostituzione"

    # Passo 3: riscrittura dei soli paragrafi rimasti con la data vecchia.
    residui = paragrafi_con_data(testo, vecchia)
    if residui and riscrittore is not None:
        testo, esito.tentativi, motivi = await _riscrivi_paragrafi(
            testo, residui, vecchia, nuova, riscrittore, tentativi_massimi,
        )
        esito.motivi = motivi
        if not motivi:
            esito.via = "riscrittura"

    finale = gate_riscrittura(
        contenuto, testo, vecchia=vecchia, nuova=nuova,
        descrizione_breve=bando.get("descrizione_breve"),
    )
    if not finale.ammesso:
        # §6.2: dopo tre tentativi si pubblica comunque il box templato. Il
        # contenuto NON si tocca: meglio vecchio e coerente che riscritto male.
        logger.info(
            "[rigenera] bando {}: gate non superato ({}), resta il box templato",
            bando.get("id"), finale.motivo,
        )
        esito.via = "box"
        esito.motivi = esito.motivi + finale.motivi
        return esito

    # Passo 4: scrittura. `slug` e `titolo` non entrano MAI nel payload: li
    # toglie anche `_payload_completed`, ma non metterceli e' la prima difesa.
    payload = {"contenuto": testo}

    # `descrizione_breve` e' la meta description e il testo della card: e' la
    # superficie piu' vista di tutte, e lasciarcela vecchia rimetterebbe in
    # pagina la contraddizione che questo modulo esiste per togliere. Stessa
    # sostituzione deterministica del contenuto, stesso vincolo di ruolo, e
    # il gate dedicato: se non passa, la descrizione resta com'era e basta.
    descrizione = bando.get("descrizione_breve")
    if isinstance(descrizione, str) and descrizione.strip():
        riscritta, quante = sostituisci_data(descrizione, vecchia, nuova, ruolo)
        if quante:
            gate_breve = gate_riscrittura(
                descrizione, riscritta, vecchia=vecchia, nuova=nuova,
                descrizione_breve=riscritta,
            )
            if gate_breve.ammesso:
                payload["descrizione_breve"] = riscritta
                esito.sostituzioni_descrizione = quante
            else:
                logger.info(
                    "[rigenera] bando {}: descrizione_breve non riscritta ({})",
                    bando.get("id"), gate_breve.motivo,
                )
                esito.motivi = esito.motivi + gate_breve.motivi

    payload.pop("slug", None)
    payload.pop("titolo", None)
    esito.payload = payload
    if attivo and scrivi is not None:
        try:
            esito.scritto = bool(await scrivi(bando.get("id"), payload))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[rigenera] scrittura del bando {} fallita: {}", bando.get("id"), e)
            esito.scritto = False
    return esito


async def _riscrivi_paragrafi(
    testo: str,
    indici: Sequence[int],
    vecchia: date_cls,
    nuova: date_cls,
    riscrittore: Callable[[str, date_cls, date_cls], Awaitable[str]],
    tentativi_massimi: int,
) -> tuple[str, int, tuple[str, ...]]:
    """Riscrive i paragrafi indicati, un tentativo alla volta, con gate propri."""
    blocchi = paragrafi(testo)
    tentativi = 0
    motivi: list[str] = []
    for indice in indici:
        if indice >= len(blocchi):
            continue
        originale = blocchi[indice]
        for _ in range(max(1, tentativi_massimi)):
            tentativi += 1
            try:
                proposto = await riscrittore(originale, vecchia, nuova)
            except Exception as e:
                motivi.append(f"riscrittore fallito: {e}")
                break
            gate = gate_riscrittura(originale, proposto or "", vecchia=vecchia, nuova=nuova)
            if gate.ammesso:
                blocchi[indice] = proposto
                break
            motivi.append(gate.motivo)
        else:
            motivi.append(f"paragrafo {indice}: {tentativi_massimi} tentativi senza esito")
    return ("\n\n".join(blocchi), tentativi, tuple(motivi))


async def scrivi_su_db(bando_id: Any, payload: dict[str, Any]) -> bool:   # pragma: no cover - I/O
    """Adattatore di produzione: `update_bando_completed(gia_pubblicato=True)`.

    `gia_pubblicato=True` e' il punto: la riga e' gia' letta dal frontend e da
    BandoFit, quindi `slug` e `titolo` restano congelati e `stato_processing`
    non viene toccato.
    """
    from .db import update_bando_completed
    return await update_bando_completed(bando_id, payload, gia_pubblicato=True)


def _data(valore: Any) -> date_cls | None:
    if isinstance(valore, date_cls):
        return valore
    if isinstance(valore, str) and len(valore) >= 10:
        try:
            return date_cls.fromisoformat(valore[:10])
        except ValueError:
            return None
    return None


# --- ingresso della riga di comando: lotto L7 (§6.4) ------------------------

STEP_RIGENERA = "rigenera"
LOTTO_PREDEFINITO = "L7"

#: I tipi di evento che spostano una data che compare **in prosa**. `chiusura`
#: non c'e' apposta: §6.2 chiude il bando lasciando `data_scadenza` intatta,
#: quindi non c'e' nessuna data vecchia da sostituire nel testo.
TIPI_CON_DATA: tuple[str, ...] = (
    "proroga", "rettifica", "apertura", "riapertura",
)

#: Colonna -> ruolo, nell'ordine in cui si guardano. Sono le sole due date che
#: il testo editoriale nomina.
COLONNE_DATA: tuple[tuple[str, str], ...] = (
    ("data_apertura", "apertura"),
    ("data_scadenza", "scadenza"),
)


def _valori(valore: Any) -> Mapping[str, Any]:
    return valore if isinstance(valore, Mapping) else {}


def date_da_evento(evento: Mapping[str, Any]) -> tuple[date_cls | None, date_cls | None, str]:
    """(vecchia, nuova, ruolo) da una riga di `bando_evento`.

    `valore_prima` e `valore_dopo` sono i due jsonb che `eventi.riga_evento`
    scrive; `campo` dice quale data, e per `proroga` la colonna e' sempre
    `data_scadenza`. Senza una data nuova non c'e' niente da rigenerare, e il
    chiamante salta la riga invece di chiamare il modello a vuoto.
    """
    prima = _valori(evento.get("valore_prima"))
    dopo = _valori(evento.get("valore_dopo"))
    campo = str(evento.get("campo") or "")
    tipo = str(evento.get("tipo") or "")
    if tipo == "proroga":
        campo = "data_scadenza"
    elif tipo in ("apertura", "riapertura") and campo not in dict(COLONNE_DATA):
        campo = "data_apertura"
    for colonna, ruolo in COLONNE_DATA:
        if campo and campo != colonna:
            continue
        nuova = _data(dopo.get(colonna) or (dopo.get("valore") if campo == colonna else None))
        if nuova is None:
            continue
        return _data(prima.get(colonna)), nuova, ruolo
    return None, None, "scadenza"


def contenuto_malformato(valore: Any) -> bool:
    """Vero per le 9 righe che la scheda non riesce a rendere (§2.b, §8.a.20).

    Il `contenuto` utile e' un oggetto con `sections`: una stringa (anche JSON
    valido) e una lista non lo sono, e la vista della 05 le porta a NULL. Il
    re-parse non le recupera — 8 sono troncate a meta' — quindi qui si
    riconoscono soltanto, e la rigenerazione vera resta allo step SEO.
    """
    if isinstance(valore, Mapping):
        return not isinstance(valore.get("sections"), list)
    if valore is None:
        return False
    if isinstance(valore, str):
        import json
        try:
            letto = json.loads(valore)
        except (ValueError, TypeError):
            return True
        return not (isinstance(letto, Mapping) and isinstance(letto.get("sections"), list))
    return True


async def run_rigenera(
    dry_run: bool = False,
    limit: int | None = None,
    attivo: bool | None = None,
    *,
    lotto: str | None = None,
    malformati: bool = False,
    righe: Sequence[Mapping[str, Any]] | None = None,
    eventi: Sequence[Mapping[str, Any]] | None = None,
    riscrittore: Callable[[str, date_cls, date_cls], Awaitable[str]] | None = None,
    scrivi: Callable[[Any, dict[str, Any]], Awaitable[bool]] | None = None,
    segnala: Callable[[Any, Mapping[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """`rigenera [--malformati]`: il lotto L7 di §6.4. Non solleva mai.

    Due modi, perche' i due problemi non si curano allo stesso modo:

    * **default** — i bandi su cui un evento verificato ha spostato una data:
      la prosa va portata in linea con le colonne. E' la via deterministica di
      §6.2 (sostituzione nelle sole frasi del ruolo giusto), zero token se il
      `riscrittore` non serve o non c'e';
    * **`--malformati`** — le 9 righe il cui `contenuto` non e' un oggetto con
      `sections`. Qui non c'e' niente da sostituire: il testo non esiste. Il
      comando le **riconosce e le segnala** (priorita' 90 + evento interno
      `elaborazione_bloccata`), perche' la rigenerazione completa e' un giro
      Opus dello step SEO e non un effetto collaterale di un backfill.

    Ombra per difetto e `--dry-run` piu' forte di `--attivo`: senza l'uno e
    senza l'altro non parte nessuna scrittura. Slug e titolo restano congelati
    (`scrivi_su_db` passa da `gia_pubblicato=True`) e **nessuna riga viene mai
    spubblicata**: questo comando non tocca `stato_processing` ne' `pubblicato`.
    """
    avvio = time.monotonic()
    lotto = lotto or LOTTO_PREDEFINITO
    step = f"backfill:{lotto}"
    scrive = _attivo(attivo) and not dry_run
    contatori = {
        "esaminati": 0, "candidati": 0, "rigenerati": 0, "scritti": 0,
        "segnalati": 0, "saltati": 0, "errori": 0,
    }
    # E' l'unico dei tre lotti che puo' chiamare il modello (passo 3): senza
    # questi due il suo consumo non sarebbe attribuibile a nessuna riga di
    # `pipeline_run`, non sarebbe fermabile da `BACKFILL_TETTO_USD` e non
    # sarebbe riconoscibile come «fuori dal mensile» (§6.2, M19).
    spesa = bilancio.Contatori()
    tetti = _tetti()
    esiti: list[dict[str, Any]] = []
    interrotto = False
    motivo_tetto = ""
    try:
        if malformati:
            riepilogo = await _lotto_malformati(
                righe, limit=limit, scrive=scrive, contatori=contatori,
                esiti=esiti, segnala=segnala,
            )
        else:
            riepilogo = await _lotto_date(
                righe, eventi, limit=limit, scrive=scrive, contatori=contatori,
                esiti=esiti, riscrittore=riscrittore, scrivi=scrivi,
                spesa=spesa, tetti=tetti, step=step,
            )
            interrotto = bool(riepilogo.pop("interrotto_per_tetto", False))
            motivo_tetto = str(riepilogo.pop("motivo", "") or "")
    except Exception as e:
        logger.error("[rigenera] lotto {} fallito: {}", lotto, e)
        esito = {"status": "errore", "step": step, "motivo": str(e), **contatori}
        _scrivi_run(step, esito, tempo=time.monotonic() - avvio)
        return esito

    riepilogo = {
        "status": "ok",
        "step": step,
        "lotto": lotto,
        "modo": "malformati" if malformati else "date",
        "dry_run": dry_run,
        "attivo": scrive,
        "interrotto_per_tetto": interrotto,
        "motivo": motivo_tetto,
        "saltato_per_lock": False,
        "crediti": spesa.crediti_firecrawl,
        "costo_usd": round(spesa.usd, 6),
        "chiamate": spesa.classificazioni,
        **contatori,
        **riepilogo,
        "esiti": esiti,
    }
    _scrivi_run(step, riepilogo, tempo=time.monotonic() - avvio, spesa=spesa)
    logger.info("[rigenera] {}", {k: v for k, v in riepilogo.items() if k != "esiti"})
    return riepilogo


def _tetti() -> bilancio.Tetti:
    """I tetti del lotto. Senza impostazioni leggibili, nessun tetto (0)."""
    try:
        from .settings import get_settings
        return bilancio.tetti_da_impostazioni(get_settings())
    except Exception as e:                                # pragma: no cover - ripiego
        logger.info("[rigenera] tetti non leggibili ({}): giro senza tetti", e)
        return bilancio.Tetti()


def _scrivi_run(
    step: str, riepilogo: Mapping[str, Any], *, tempo: float,
    spesa: bilancio.Contatori | None = None,
) -> None:
    """La riga `pipeline_run` del lotto (M19). Non fa mai fallire il giro."""
    riga = telemetria.PipelineRun(step=step).concludi(
        durata_s=tempo,
        esito=telemetria.esito_da_contatori(
            errori=int(riepilogo.get("errori") or 0),
            interrotto_per_tetto=bool(riepilogo.get("interrotto_per_tetto")),
        ),
        contatori={k: v for k, v in riepilogo.items() if k != "esiti"},
        crediti=spesa.crediti_firecrawl if spesa is not None else 0,
        costo_usd=spesa.usd if spesa is not None else 0.0,
        interrotto_per_tetto=bool(riepilogo.get("interrotto_per_tetto")),
    )
    try:
        telemetria.scrivi_pipeline_run(riga)
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[rigenera] telemetria non scritta: {}", e)


def _attivo(attivo: bool | None) -> bool:
    """Ombra per difetto; `--ombra` (False esplicito) vince anche sull'ambiente.

    `None` significa «l'operatore non ha detto niente»: decide `MONITOR_MODALITA`.
    `False` significa «ha scritto `--ombra`», e allora non si scrive comunque:
    un interruttore d'ambiente non puo' annullare una richiesta scritta a mano
    sulla riga di comando.
    """
    if attivo is not None:
        return bool(attivo)
    try:
        from .settings import get_settings
        return get_settings().monitor_modalita == "attivo"
    except Exception:
        return False


def _bandi(righe: Sequence[Mapping[str, Any]] | None, **filtri: Any) -> list[dict[str, Any]]:
    """I pubblicati su cui lavorare, dal DB o iniettati dal chiamante."""
    if righe is not None:
        return [dict(r) for r in righe]
    try:
        from . import db
        return [dict(r) for r in db.select_bandi_pubblicati_contenuto(**filtri)]
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[rigenera] lettura dei pubblicati fallita: {}", e)
        return []


async def _lotto_malformati(
    righe: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int | None,
    scrive: bool,
    contatori: dict[str, int],
    esiti: list[dict[str, Any]],
    segnala: Callable[[Any, Mapping[str, Any]], Any] | None,
) -> dict[str, Any]:
    """Le righe con il `contenuto` irrecuperabile: si elencano e si segnalano."""
    elenco = _bandi(righe, limit=limit)
    identificativi: list[Any] = []
    for riga in elenco:
        contatori["esaminati"] += 1
        if not contenuto_malformato(riga.get("contenuto")):
            continue
        contatori["candidati"] += 1
        identificativi.append(riga.get("id"))
        esiti.append({"bando_id": riga.get("id"), "slug": riga.get("slug"),
                      "via": "segnalazione", "scritto": False})
        if not scrive:
            continue
        if _segnala_malformato(riga, segnala):
            contatori["segnalati"] += 1
        else:
            contatori["saltati"] += 1
    if identificativi:
        # Gli id servono al committente per lanciare il giro SEO mirato: senza
        # di essi il comando direbbe «9» e non quali.
        logger.info("[rigenera] contenuto malformato su {} righe: {}",
                    len(identificativi), identificativi)
    return {"ids": identificativi}


def _segnala_malformato(
    riga: Mapping[str, Any], segnala: Callable[[Any, Mapping[str, Any]], Any] | None,
) -> bool:
    """Priorita' 90 + evento interno. Nessuna colonna editoriale viene toccata."""
    bando_id = riga.get("id")
    evento = {
        "bando_id": bando_id,
        "tipo": "elaborazione_bloccata",
        "origine": "pipeline",
        "campo": "contenuto",
        "valore_dopo": {"motivo": "contenuto non e' un oggetto con sections"},
        # Interno per definizione (§13.5): mai un cursore, mai leggibile.
        "leggibile": False,
        "in_aggiornamenti": False,
        "verificato": False,
        "applicato": False,
    }
    if segnala is not None:
        try:
            return bool(segnala(bando_id, evento))
        except Exception as e:                            # pragma: no cover - ripiego
            logger.warning("[rigenera] segnalazione del bando {} fallita: {}", bando_id, e)
            return False
    try:
        from . import db
        db.aggiorna_controllo(bando_id, {"priorita_controllo": 90})
        return bool(db.registra_evento(evento))
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[rigenera] segnalazione del bando {} fallita: {}", bando_id, e)
        return False


async def _lotto_date(
    righe: Sequence[Mapping[str, Any]] | None,
    eventi: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int | None,
    scrive: bool,
    contatori: dict[str, int],
    esiti: list[dict[str, Any]],
    riscrittore: Callable[[str, date_cls, date_cls], Awaitable[str]] | None,
    scrivi: Callable[[Any, dict[str, Any]], Awaitable[bool]] | None,
    spesa: bilancio.Contatori | None = None,
    tetti: bilancio.Tetti | None = None,
    step: str = STEP_RIGENERA,
) -> dict[str, Any]:
    """Le pagine la cui prosa non dice piu' quello che dicono le colonne."""
    elenco_eventi = _eventi_con_data(eventi, limit=limit)
    if not elenco_eventi:
        return {"eventi": 0}
    per_bando: dict[Any, dict[str, Any]] = {}
    for evento in elenco_eventi:
        bando_id = evento.get("bando_id")
        if bando_id is not None:
            # Un bando con due eventi (il differimento ne porta due) si
            # rigenera una volta per evento, in ordine: la seconda passata
            # parte dal contenuto gia' corretto dalla prima.
            per_bando.setdefault(bando_id, {"eventi": []})["eventi"].append(evento)

    bandi = {r.get("id"): r for r in _bandi(righe, bando_ids=tuple(per_bando))}
    if scrivi is None and scrive:
        scrivi = scrivi_su_db

    interrotto = False
    motivo_tetto = ""
    for bando_id, gruppo in per_bando.items():
        if spesa is not None and tetti is not None:
            # Il tetto si guarda **prima** di ogni bando: un tetto che se ne
            # accorge a giro finito non e' un tetto.
            verifica = bilancio.verifica(spesa, tetti, step=step)
            if not verifica.consentito:
                interrotto = True
                motivo_tetto = verifica.motivo
                logger.warning("[ALLARME] [rigenera] {}", verifica.motivo)
                break
        riga = bandi.get(bando_id)
        contatori["esaminati"] += 1
        if riga is None:
            contatori["saltati"] += 1
            continue
        if contenuto_malformato(riga.get("contenuto")):
            # Non e' roba di questo modo: il testo non esiste, non c'e' niente
            # da sostituire. Lo prende `--malformati`.
            contatori["saltati"] += 1
            continue
        trasformato = _testo_del_contenuto(riga)
        if trasformato is None:
            contatori["saltati"] += 1
            continue
        corrente, struttura, era_stringa = trasformato
        scrittore = (
            _scrittore_json(scrivi, struttura, era_stringa) if scrive else scrivi)
        fatto = False
        for evento in gruppo["eventi"]:
            vecchia, nuova, ruolo = date_da_evento(evento)
            if nuova is None:
                contatori["saltati"] += 1
                continue
            contatori["candidati"] += 1
            try:
                prodotto = await rigenera(
                    corrente, evento, vecchia=vecchia, nuova=nuova, ruolo=ruolo,
                    attivo=scrive, riscrittore=riscrittore, scrivi=scrittore,
                )
            except Exception as e:                        # pragma: no cover - ripiego
                contatori["errori"] += 1
                logger.warning("[rigenera] bando {} fallito: {}", bando_id, e)
                continue
            esiti.append(prodotto.come_dizionario())
            corrente.update(prodotto.payload)
            contatori["scritti"] += 1 if prodotto.scritto else 0
            fatto = True
        contatori["rigenerati"] += 1 if fatto else 0
    return {"eventi": len(elenco_eventi),
            "interrotto_per_tetto": interrotto, "motivo": motivo_tetto}


#: Separatore fra un nodo di testo e il successivo. E' lo stesso che
#: `paragrafi()` riconosce, e non e' un caso: un nodo del `contenuto` (un
#: paragrafo, una voce di lista, una domanda di FAQ) e' esattamente l'unita'
#: su cui lavorano la sostituzione e la riscrittura.
SEPARATORE = "\n\n"


def _mappa_testi(contenuto: Any, funzione: Callable[[str], str]) -> Any:
    """Applica `funzione` ai soli nodi di **testo** di un `contenuto` jsonb.

    Attraversa le forme che la skill SEO produce — il `text` di una sezione
    `h2`, i `segments` di un paragrafo, gli `items[].segments` delle liste e la
    coppia `q` / `a.segments` delle FAQ — nello stesso ordine in cui i nodi si
    leggono. L'ordine e' la chiave: e' cio' che rende l'estrazione reversibile.

    Un segmento `kind == "link"` passa **intatto**, `url` compreso: il testo
    dell'ancora e' scritto per accompagnare quel documento, e l'URL non si
    tocca mai (CLAUDE.md). Gli altri segmenti (`text`, `bold`, …) entrano: una
    scadenza in grassetto e' scadenza come le altre, e lasciarla fuori
    significherebbe lasciarla vecchia **senza che nessun gate se ne accorga**.

    Qui sta il motivo per cui il modulo non serializza piu' il JSON intero: su
    una stringa `json.dumps` la sostituzione della data lavora per offset e
    riscrive qualunque cosa contenga quella data — compreso un
    `https://…/2026-10-06/avviso.pdf`, che diventava un link mai esistito.
    """
    if not isinstance(contenuto, Mapping):
        return contenuto
    sezioni = contenuto.get("sections")
    if not isinstance(sezioni, list):
        return contenuto
    return dict(contenuto, sections=[_mappa_sezione(s, funzione) for s in sezioni])


def _mappa_sezione(sezione: Any, funzione: Callable[[str], str]) -> Any:
    if not isinstance(sezione, Mapping):
        return sezione
    nuova = dict(sezione)
    for chiave in ("heading", "text"):
        if isinstance(sezione.get(chiave), str):
            nuova[chiave] = funzione(sezione[chiave])
    if isinstance(sezione.get("segments"), list):
        nuova["segments"] = _mappa_segmenti(sezione["segments"], funzione)
    if isinstance(sezione.get("items"), list):
        nuova["items"] = [_mappa_voce(v, funzione) for v in sezione["items"]]
    return nuova


def _mappa_voce(voce: Any, funzione: Callable[[str], str]) -> Any:
    """Una voce di lista (`{segments}`) o di FAQ (`{q, a: {segments}}`)."""
    if not isinstance(voce, Mapping):
        return voce
    nuova = dict(voce)
    if isinstance(voce.get("q"), str):
        nuova["q"] = funzione(voce["q"])
    if isinstance(voce.get("segments"), list):
        nuova["segments"] = _mappa_segmenti(voce["segments"], funzione)
    risposta = voce.get("a")
    if isinstance(risposta, Mapping) and isinstance(risposta.get("segments"), list):
        nuova["a"] = dict(risposta, segments=_mappa_segmenti(risposta["segments"], funzione))
    return nuova


def _mappa_segmenti(segmenti: Any, funzione: Callable[[str], str]) -> list[Any]:
    nuovi: list[Any] = []
    for segmento in segmenti if isinstance(segmenti, list) else []:
        if (isinstance(segmento, Mapping) and segmento.get("kind") != "link"
                and isinstance(segmento.get("text"), str)):
            nuovi.append(dict(segmento, text=funzione(segmento["text"])))
        else:
            nuovi.append(segmento)
    return nuovi


def _nodi_di_testo(contenuto: Any) -> list[str]:
    raccolti: list[str] = []

    def raccogli(testo: str) -> str:
        raccolti.append(testo)
        return testo

    _mappa_testi(contenuto, raccogli)
    return raccolti


def _rimonta(contenuto: Any, nodi: Sequence[str]) -> Any:
    """Rimette i nodi riscritti al loro posto, nello stesso ordine."""
    coda = iter(nodi)
    return _mappa_testi(contenuto, lambda _: next(coda))


def _testo_del_contenuto(
    riga: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, bool] | None:
    """(riga con `contenuto` come testo, struttura originale, era una stringa).

    `None` significa «questa riga non e' trattabile»: il chiamante la salta.

    `rigenera()` lavora sul testo — e' li' che vivono le frasi e le parole di
    ruolo — mentre la colonna e' un jsonb con `sections`. Il testo che gli si
    passa **non** e' piu' il JSON serializzato: sono i soli nodi di testo,
    uniti da una riga vuota. Cosi' nessuna chiave, nessun `kind` e soprattutto
    nessun `url` puo' finire sotto una sostituzione, e ogni nodo coincide con
    un paragrafo, che e' l'unita' su cui il passo 3 riscrive.

    Il giro e' reversibile solo se nessun nodo contiene a sua volta una riga
    vuota: si verifica prima di partire, e se non torna si lascia stare. Una
    rimonta sbagliata sposterebbe le frasi da una sezione all'altra, che e'
    peggio di una data vecchia.
    """
    corrente = dict(riga)
    contenuto = corrente.get("contenuto")
    era_stringa = False
    if isinstance(contenuto, str):
        import json
        try:
            letto = json.loads(contenuto)
        except (ValueError, TypeError):
            # Prosa vera in colonna: si lavora sulla stringa com'e'.
            return corrente, None, False
        if not isinstance(letto, (Mapping, list)):
            return corrente, None, False
        contenuto, era_stringa = letto, True
    if not isinstance(contenuto, (Mapping, list)):
        return corrente, None, False

    nodi = _nodi_di_testo(contenuto)
    testo = SEPARATORE.join(nodi)
    if paragrafi(testo) != nodi:
        logger.info(
            "[rigenera] bando {}: contenuto non scomponibile in nodi (riga vuota "
            "dentro un nodo), riga saltata", riga.get("id"))
        return None
    corrente["contenuto"] = testo
    return corrente, contenuto, era_stringa


def _scrittore_json(
    scrivi: Callable[[Any, dict[str, Any]], Awaitable[bool]] | None,
    struttura: Any,
    era_stringa: bool,
) -> Callable[[Any, dict[str, Any]], Awaitable[bool]] | None:
    """Rimette il `contenuto` in forma jsonb un attimo prima della scrittura.

    Se i nodi riscritti non sono piu' tanti quanti erano, la scrittura del
    `contenuto` viene **buttata**, non tentata: rimontare un numero diverso di
    nodi significherebbe perdere o spostare un pezzo di testo.
    """
    if scrivi is None or struttura is None:
        return scrivi

    attesi = len(_nodi_di_testo(struttura))

    async def dentro(bando_id: Any, payload: dict[str, Any]) -> bool:
        dati = dict(payload)
        if "contenuto" in dati:
            nodi = paragrafi(str(dati["contenuto"]))
            if len(nodi) != attesi:
                logger.warning(
                    "[rigenera] bando {}: la riscrittura ha cambiato il numero di "
                    "nodi ({} invece di {}), il contenuto non si scrive",
                    bando_id, len(nodi), attesi)
                dati.pop("contenuto", None)
            else:
                rimontato = _rimonta(struttura, nodi)
                if era_stringa:
                    import json
                    rimontato = json.dumps(rimontato, ensure_ascii=False)
                dati["contenuto"] = rimontato
        if not dati:
            return False
        return bool(await scrivi(bando_id, dati))

    return dentro


def _eventi_con_data(
    eventi: Sequence[Mapping[str, Any]] | None, *, limit: int | None,
) -> list[dict[str, Any]]:
    """Gli eventi verificati che hanno spostato una data, dal DB o iniettati."""
    if eventi is not None:
        return [dict(e) for e in eventi]
    try:
        from . import db
        # `applicato=True` non e' un di piu': in ombra un evento nasce
        # `verificato=True, applicato=False`, e rigenerare la prosa prima di
        # `applica-eventi` scriverebbe nel testo una data che la colonna non
        # ha ancora. Con questo filtro il comando diventa impossibile da
        # lanciare fuori ordine.
        return [dict(e) for e in db.select_eventi(
            tipi=TIPI_CON_DATA, verificato=True, applicato=True, limit=limit)]
    except Exception as e:                                # pragma: no cover - ripiego
        logger.warning("[rigenera] lettura degli eventi fallita: {}", e)
        return []


__all__ = [
    "DESCRIZIONE_MAX", "DESCRIZIONE_MIN", "EsitoGate", "MODELLI_VOCE",
    "PAROLE_RUOLO", "Rigenerazione", "TENTATIVI_MASSIMI", "VOCE_PREDEFINITA",
    "Voce", "box_aggiornamenti", "frasi", "gate_riscrittura", "paragrafi",
    "paragrafi_con_data", "rendi_data", "rigenera", "scrivi_su_db",
    "sostituisci_data", "voce_aggiornamento",
    "COLONNE_DATA", "LOTTO_PREDEFINITO", "STEP_RIGENERA", "TIPI_CON_DATA",
    "contenuto_malformato", "date_da_evento", "run_rigenera",
]
