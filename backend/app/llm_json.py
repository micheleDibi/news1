"""Chiamata JSON a Claude, condivisa fra le pipeline interpelli e selezione
personale.

I due file ne avevano una copia identica: differivano per due righe di
commento e nient'altro. Qui e' unificata.

E' anche l'imbuto da cui passa OGNI risposta LLM di quelle due pipeline,
quindi e' il punto giusto per la normalizzazione ortografica: applicarla piu'
a valle vorrebbe dire ripeterla su ogni chiamante, e in
``selezione_personale`` lo slug viene rigenerato dal titolo subito dopo,
quindi la correzione deve arrivare prima o titolo e slug divergono.

La normalizzazione lavora su una ALLOWLIST di chiavi passata dal chiamante,
mai su tutto il dizionario: ``sub_links`` contiene URL e non va toccato.
"""

import json

import anthropic

from . import ortografia
from .logger import logger


def _estrai_json(grezzo: str) -> str:
    """Toglie l'eventuale recinto markdown attorno al JSON."""
    if "```" in grezzo:
        grezzo = grezzo.split("```")[1]
        if grezzo.startswith("json"):
            grezzo = grezzo[4:]
        grezzo = grezzo.strip()
    return grezzo


def _normalizza_campi(dati: dict, campi_prosa, etichetta: str) -> dict:
    if not campi_prosa:
        return dati
    fuori = dict(dati)
    segnalazioni = []

    def _uno(valore):
        if not isinstance(valore, str) or valore == "":
            return valore
        esito = ortografia.correggi(valore)
        if esito["saltato"]:
            logger.warning(
                "ortografia saltata su {} ({}): testo lasciato intatto",
                etichetta, esito["saltato"],
            )
            return valore
        segnalazioni.extend(esito["segnalazioni"])
        return esito["testo"]

    for campo in campi_prosa:
        valore = fuori.get(campo)
        if isinstance(valore, str):
            fuori[campo] = _uno(valore)
        elif isinstance(valore, list):
            fuori[campo] = [_uno(v) if isinstance(v, str) else v for v in valore]

    if segnalazioni:
        logger.info(
            "{}: {} ambiguita' ortografiche non corrette in automatico: {}",
            etichetta, len(segnalazioni),
            ", ".join(sorted({s["parola"] for s in segnalazioni})),
        )
    return fuori


def richiesta_json(
    system_prompt: str,
    user_content: str,
    modello: str,
    api_key: str,
    max_tokens: int = 4096,
    campi_prosa=(),
    etichetta: str = "llm",
) -> dict:
    """Chiama Claude e restituisce la risposta come dizionario.

    ``campi_prosa`` elenca le chiavi di primo livello da normalizzare: solo
    testo italiano destinato alla pubblicazione, mai URL o codici.
    """
    claude = anthropic.Anthropic(api_key=api_key)

    # Forza output JSON nel system prompt
    json_system = system_prompt + (
        "\n\nIMPORTANTE: Rispondi SOLO con JSON valido. Esegui l'escape di "
        'tutte le virgolette nei valori stringa con backslash (\\")'
    )

    response = claude.messages.create(
        model=modello,
        max_tokens=max_tokens,
        system=json_system,
        messages=[{"role": "user", "content": user_content}],
    )
    grezzo = _estrai_json(response.content[0].text.strip())

    try:
        return _normalizza_campi(json.loads(grezzo), campi_prosa, etichetta)
    except json.JSONDecodeError:
        pass

    # Fallback: chiedi a Claude di sistemare il JSON malformato
    try:
        fix_response = claude.messages.create(
            model=modello,
            max_tokens=max_tokens,
            system=(
                "Correggi il seguente JSON malformato. Rispondi SOLO con il "
                "JSON corretto, senza markdown, senza spiegazioni. Assicurati "
                "che tutte le virgolette dentro i valori stringa siano "
                "escapate con backslash."
            ),
            messages=[{"role": "user", "content": grezzo}],
        )
        sistemato = _estrai_json(fix_response.content[0].text.strip())
        return _normalizza_campi(json.loads(sistemato), campi_prosa, etichetta)
    except Exception as fix_err:
        logger.error("Impossibile fixare JSON: {}", fix_err)
        raise
