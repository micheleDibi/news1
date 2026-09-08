"""Slug ASCII per gli URL, gemello di ``src/lib/slug.ts``.

Ogni passaggio corrisponde a una riga di ``slugifica()`` in quel file, nello
stesso ordine, cosi' il backend e il frontend producono lo stesso slug per lo
stesso titolo. La parita' e' verificata dai test sui casi condivisi in
``tests/ortografia/casi.json``.

Prima di questo modulo esistevano tre regole diverse nello stesso repo:

* ``src/lib/utils.ts`` ``slugify()`` CANCELLA gli accenti (``citta`` da
  ``citt``), perche' ``\\w`` in JS e' ASCII;
* ``generate_slugs()`` in main.py li CONSERVAVA, producendo slug non ASCII
  che finivano percent-encodati negli URL e grezzi nelle sitemap;
* ``slugifica()`` in slug.ts li traslittera.

Questo modulo adotta la terza, che e' l'unica invariante rispetto agli
accenti: ``"Perche' no"`` e ``"Perché no"`` danno entrambi
``perche-no``. E' quella proprieta' a rendere sicura la correzione
ortografica dei titoli.

Vale solo per gli slug NUOVI: quelli gia' a database non vengono mai
rigenerati, altrimenti gli URL indicizzati risponderebbero 410.

Nessuna dipendenza e nessun import interno, cosi' i test lo caricano da soli.
"""

import re
import unicodedata

# Stesso intervallo del gemello TS: [̀-ͯ]
_DIACRITICI_INIZIO = chr(0x0300)
_DIACRITICI_FINE = chr(0x036F)
# Apostrofi e slash diventano separatori, non spariscono: "Valle d'Aosta" ->
# "valle-d-aosta", non "valle-daosta".
_SEPARATORI = (chr(0x2019), "'", chr(0x0060), chr(0x00B4), "/", "\\")

SLUG_VALIDO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugifica(testo: str) -> str:
    decomposto = unicodedata.normalize("NFD", testo or "")
    senza_diacritici = "".join(
        c for c in decomposto
        if not (_DIACRITICI_INIZIO <= c <= _DIACRITICI_FINE)
    )
    for separatore in _SEPARATORI:
        senza_diacritici = senza_diacritici.replace(separatore, " ")
    minuscolo = senza_diacritici.lower()
    trattini = re.sub(r"[^a-z0-9]+", "-", minuscolo)
    return re.sub(r"^-+|-+$", "", trattini)


def slug_valido(valore) -> bool:
    return isinstance(valore, str) and SLUG_VALIDO.match(valore) is not None
