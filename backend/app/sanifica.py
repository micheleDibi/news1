"""Sanificazione del testo prodotto dai modelli, prima della scrittura su
Supabase: em-dash, null byte e ortografia italiana.

Vive fuori da main.py per poter essere testato: e' il pezzo che non deve MAI
toccare gli URL dentro il payload della skill, e quel comportamento va
verificato, non sperato.

Dipende solo da `ortografia`, che a sua volta non ha dipendenze.
"""

from . import ortografia


def _strip_em_dashes(value):
    """Rimuove l'em-dash (U+2014 `—`) dai contenuti generati dalla skill.

    La redazione non vuole questo carattere nei testi. Sostituisce:
    - " — " (con spazi attorno) -> ", "  (preserva la pausa grammaticale)
    - "—"   (attaccato o solo)   -> "-"   (hyphen)

    Applicato ricorsivamente su dict/list cosi' da coprire le sections
    strutturate e i report annidati del payload skill.
    """
    if isinstance(value, str):
        s = value.replace(" — ", ", ")
        s = s.replace("—", "-")
        return s
    if isinstance(value, list):
        return [_strip_em_dashes(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_em_dashes(v) for k, v in value.items()}
    return value


def _strip_null_bytes(value):
    """Rimuove i null byte (U+0000) dai contenuti generati dalla skill.

    Postgres rifiuta sempre i null byte nei campi `text` con errore 22P05
    ('unsupported Unicode escape sequence: \\u0000 cannot be converted to
    text'). La skill puo' produrli inavvertitamente quando l'output viene
    de-serializzato (es. \\u0000 dentro stringhe JSON). Applicato
    ricorsivamente come _strip_em_dashes.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_null_bytes(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_null_bytes(v) for k, v in value.items()}
    return value


def _norm_testo(valore, raccolta=None):
    """Sanifica UNA stringa di prosa: null byte, em-dash, ortografia.

    E' l'unico punto in cui si tocca del testo. Tutto il resto del payload
    (url, id, enum, contatori) non passa da qui.
    """
    if not isinstance(valore, str) or valore == "":
        return valore
    pulito = _strip_null_bytes(_strip_em_dashes(valore))
    esito = ortografia.correggi(pulito)
    if esito["saltato"]:
        if raccolta is not None:
            raccolta.append({
                "regola": "saltato",
                "parola": esito["saltato"],
                "occorrenza": 1,
                "suggerimento": "",
            })
        return pulito
    if raccolta is not None:
        raccolta.extend(esito["segnalazioni"])
    return esito["testo"]


def _sanitize_segmento(segmento, raccolta):
    """Di un segmento inline si tocca SOLO `text`: `url` e `kind` restano."""
    if not isinstance(segmento, dict):
        return segmento
    nuovo = dict(segmento)
    if isinstance(nuovo.get("text"), str):
        nuovo["text"] = _norm_testo(nuovo["text"], raccolta)
    return nuovo


def _sanitize_sezioni(sezioni, raccolta):
    if not isinstance(sezioni, list):
        return sezioni
    fuori = []
    for sezione in sezioni:
        if not isinstance(sezione, dict):
            fuori.append(sezione)
            continue
        nuova = dict(sezione)
        testo = nuova.get("text")
        if isinstance(testo, str):
            nuova["text"] = _norm_testo(testo, raccolta)
        elif isinstance(testo, list):
            # ramo di fallback di sections_to_markdown: text puo' essere
            # una lista di stringhe
            nuova["text"] = [
                _norm_testo(v, raccolta) if isinstance(v, str) else v for v in testo
            ]
        if isinstance(nuova.get("segments"), list):
            nuova["segments"] = [
                _sanitize_segmento(seg, raccolta) for seg in nuova["segments"]
            ]
        if isinstance(nuova.get("items"), list):
            # items e' una lista di liste di segmenti (doppio annidamento)
            nuova["items"] = [
                [_sanitize_segmento(seg, raccolta) for seg in voce]
                if isinstance(voce, list) else voce
                for voce in nuova["items"]
            ]
        # `id` (l'ancora HTML) NON si tocca: e' gia' senza accenti e i link
        # dell'indice ci puntano.
        fuori.append(nuova)
    return fuori


def _sanitize_elenco(elenco, chiavi, raccolta):
    if not isinstance(elenco, list):
        return elenco
    fuori = []
    for voce in elenco:
        if not isinstance(voce, dict):
            fuori.append(voce)
            continue
        nuova = dict(voce)
        for chiave in chiavi:
            if isinstance(nuova.get(chiave), str):
                nuova[chiave] = _norm_testo(nuova[chiave], raccolta)
        fuori.append(nuova)
    return fuori


def _sanitize_payload(payload):
    """Unico punto di sanificazione del payload skill: em-dash, null byte e
    ortografia italiana, su una ALLOWLIST di chiavi di prosa.

    Sostituisce la vecchia coppia _strip_em_dashes/_strip_null_bytes, che
    ricorreva alla cieca sull'intero payload e quindi attraversava anche
    `source_url`, `fonti[].fonte_url`, `factcheck_report[].fonte_primaria` e
    i `segments[].url` dei link inline. Con l'em-dash la cosa passava liscia;
    con gli accenti corromperebbe gli URL.

    Restano volutamente fuori dall'allowlist:
    - ogni url, `generated_at`, `livello`, `stato`, `kind`, `type`, `id`;
    - `validation`, che e' l'archivio di cio' che la skill ha visto: i suoi
      contatori (title_length, h1_length, word_count) sono calcolati DENTRO
      la skill, prima di qui, e riscriverli cancellerebbe l'unica traccia del
      suo comportamento. Il disallineamento e' noto e accettato;
    - `meta.tono` / `meta.persona` della variante persona, che sono enum.

    Ritorna (payload_sanificato, segnalazioni).
    """
    if not isinstance(payload, dict):
        return payload, []
    raccolta = []
    fuori = dict(payload)

    for chiave in ("keyword", "angolo"):
        if chiave in fuori:
            fuori[chiave] = _norm_testo(fuori[chiave], raccolta)

    if isinstance(fuori.get("seo"), dict):
        seo = dict(fuori["seo"])
        for chiave in ("meta_title", "meta_description", "h1"):
            if chiave in seo:
                seo[chiave] = _norm_testo(seo[chiave], raccolta)
        fuori["seo"] = seo

    if isinstance(fuori.get("article"), dict):
        articolo = dict(fuori["article"])
        for chiave in ("h1", "plain_text_preview"):
            if chiave in articolo:
                articolo[chiave] = _norm_testo(articolo[chiave], raccolta)
        if "sections" in articolo:
            articolo["sections"] = _sanitize_sezioni(articolo["sections"], raccolta)
        fuori["article"] = articolo

    if "competitor_report" in fuori:
        fuori["competitor_report"] = _sanitize_elenco(
            fuori["competitor_report"], ("fonte", "angolo_usato", "gap"), raccolta
        )
    if "factcheck_report" in fuori:
        fuori["factcheck_report"] = _sanitize_elenco(
            fuori["factcheck_report"], ("dato",), raccolta
        )
    if "fonti" in fuori:
        fuori["fonti"] = _sanitize_elenco(fuori["fonti"], ("dato",), raccolta)

    return fuori, raccolta
