"""Lock orfani del sender dei bandi (contratto di ottobre, §8).

Un `systemctl restart` durante un giro lascia in `pipeline_lock` il lock del
processo morto per tutta la sua scadenza (RIPRESA §5.6): il 28/09 un secondo
riavvio ha trovato il lock del giro di avvio precedente, ha saltato il proprio
e avrebbe fatto saltare anche quello delle 12. All'avvio il sender rilascia
quindi i lock che erano di un suo processo precedente e non piu' vivo.

Le regole sono quelle scritte a mano in RIPRESA §3.2 punto 10:

* `bandi_pipeline@<pid>` e `resolver@<pid>`: orfano se il pid non e' vivo. Il
  pid del processo corrente non si tocca mai. Un pid riusato da un altro
  processo risulta vivo e il lock resta fino al TTL: e' la direzione sicura;
* `monitor:<giro>`: orfano se e' stato preso prima dell'avvio del sender E non
  c'e' nessun `bandi_pipeline@<pid>` vivo. Il monitor gira dentro il giro, che
  tiene il lock `bandi_pipeline`: se un altro sender e' vivo, il suo monitor
  non si tocca;
* i proprietari `…:cli` (`monitor:cli`, `applica-eventi:cli`,
  `seo-rigenera:cli`) e i formati sconosciuti non si toccano mai.

Il rilascio passa solo da `lock_rilascia` (la RPC), mai da un DELETE: e' il
chiamante a fornire la funzione. Il DB e' condiviso fra il server e il Mac, e
nessun proprietario porta il nome dell'host: un `resolver@<pid>` preso da un
`risolvi-fonte` lanciato sul Mac, o un `bandi_pipeline@<pid>` di un sender
avviato sul Mac, risulterebbe morto sul server e verrebbe rilasciato mentre il
processo sul Mac lavora ancora. Il contratto §1 vieta gia' quei comandi dal
Mac; il rischio e' accettato e scritto qui.

Modulo puro, solo libreria standard: si prova con il python di sistema, senza
DB e senza i runner di `scraper_bandi`.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

_RE_CON_PID = re.compile(r"^(bandi_pipeline|resolver)@(\d+)$")
PREFISSO_MONITOR = "monitor:"
SUFFISSO_CLI = ":cli"
PROPRIETARIO_PIPELINE = "bandi_pipeline"

_RE_FRAZIONE = re.compile(r"\.(\d+)")


@dataclass(frozen=True)
class Orfano:
    """Un lock da rilasciare, con il perche'."""
    nome: str
    proprietario: str
    motivo: str


def pid_vivo(pid: int) -> bool:
    """C'e' un processo con questo pid? Nel dubbio si', cosi' il lock resta."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # PermissionError compreso: il processo c'e', solo non e' nostro.
        return True
    except (OverflowError, ValueError):
        # Un pid oltre 2**31 (riga corrotta a DB) non e' un OSError: senza
        # questo ramo `orfani()` sollevava fuori dal try. Nel dubbio vivo.
        return True
    return True


def istante(valore: Any) -> datetime | None:
    """Un `timestamptz` di PostgREST come datetime aware, o None.

    `fromisoformat` di Python 3.10 non accetta la «Z» ne' le frazioni con meno
    di sei cifre («10:28:47.87927+00:00»), che PostgREST restituisce.
    """
    if isinstance(valore, datetime):
        return valore if valore.tzinfo else valore.replace(tzinfo=timezone.utc)
    testo = str(valore or "").strip()
    if not testo:
        return None
    testo = testo.replace("Z", "+00:00").replace(" ", "T", 1)
    testo = _RE_FRAZIONE.sub(lambda m: "." + (m.group(1) + "000000")[:6], testo, count=1)
    try:
        momento = datetime.fromisoformat(testo)
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def orfani(
    righe: Iterable[Mapping[str, Any]],
    *,
    pid_corrente: int,
    avvio: datetime,
    vivo: Callable[[int], bool] = pid_vivo,
) -> list[Orfano]:
    """I lock di `pipeline_lock` che un sender appena avviato puo' rilasciare."""
    elenco = [dict(r) for r in righe]
    giri_vivi = False
    for riga in elenco:
        trovato = _RE_CON_PID.match(str(riga.get("proprietario") or ""))
        if trovato and trovato.group(1) == PROPRIETARIO_PIPELINE:
            pid = int(trovato.group(2))
            if pid == pid_corrente or vivo(pid):
                giri_vivi = True
    esito: list[Orfano] = []
    for riga in elenco:
        nome = str(riga.get("nome") or "")
        proprietario = str(riga.get("proprietario") or "")
        if not nome or not proprietario or proprietario.endswith(SUFFISSO_CLI):
            continue
        trovato = _RE_CON_PID.match(proprietario)
        if trovato:
            pid = int(trovato.group(2))
            if pid != pid_corrente and not vivo(pid):
                esito.append(Orfano(nome, proprietario, f"processo {pid} non piu' vivo"))
            continue
        if proprietario.startswith(PREFISSO_MONITOR):
            preso = istante(riga.get("acquisito_at"))
            if preso is not None and preso < avvio and not giri_vivi:
                esito.append(Orfano(
                    nome, proprietario,
                    "preso prima dell'avvio del sender e nessun giro vivo",
                ))
            continue
        # Formato sconosciuto: non e' nostro, non si tocca.
    return esito


def rilascia_orfani(
    *,
    leggi: Callable[[], Iterable[Mapping[str, Any]]],
    rilascia: Callable[[str, str], bool],
    pid_corrente: int | None = None,
    avvio: datetime | None = None,
    vivo: Callable[[int], bool] = pid_vivo,
    registro: Any | None = None,
) -> dict[str, Any]:
    """Legge `pipeline_lock`, rilascia gli orfani, scrive nel journal. Mai un'eccezione.

    `rilascia(nome, proprietario)` e' l'adattatore su `lock_rilascia`. Un errore
    di lettura o di rilascio diventa un avviso: il sender parte comunque, e al
    peggio il lock scade da solo come prima.
    """
    registro = registro or logging.getLogger(__name__)
    pid_corrente = os.getpid() if pid_corrente is None else pid_corrente
    avvio = avvio or datetime.now(timezone.utc)
    esito: dict[str, Any] = {"letti": 0, "rilasciati": [], "falliti": [], "errore": ""}
    try:
        righe = list(leggi() or [])
    except Exception as e:
        esito["errore"] = f"{type(e).__name__}: {e}"
        registro.warning(f"[lock] pipeline_lock non leggibile, nessun rilascio: {esito['errore']}")
        return esito
    esito["letti"] = len(righe)
    for orfano in orfani(righe, pid_corrente=pid_corrente, avvio=avvio, vivo=vivo):
        voce = {"nome": orfano.nome, "proprietario": orfano.proprietario, "motivo": orfano.motivo}
        try:
            fatto = bool(rilascia(orfano.nome, orfano.proprietario))
        except Exception as e:
            fatto = False
            voce["errore"] = f"{type(e).__name__}: {e}"
        if fatto:
            esito["rilasciati"].append(voce)
            registro.warning(
                f"[lock] rilasciato il lock orfano {orfano.nome} di {orfano.proprietario}: "
                f"{orfano.motivo}"
            )
        else:
            esito["falliti"].append(voce)
            registro.warning(
                f"[lock] rilascio del lock orfano {orfano.nome} di {orfano.proprietario} "
                f"non riuscito: {voce.get('errore', 'la RPC non ha rilasciato')}"
            )
    registro.info(
        f"[lock] avvio: {len(esito['rilasciati'])} lock orfani rilasciati, "
        f"{len(esito['falliti'])} non riusciti, {esito['letti']} letti"
    )
    return esito
