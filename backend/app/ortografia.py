"""Normalizzazione ortografica dei testi italiani generati dai modelli.

Gemello di ``src/lib/ortografia.ts``: le due implementazioni devono produrre
lo stesso risultato carattere per carattere. Ogni modifica va fatta su
ENTRAMBI i file e verificata con la tabella di casi condivisa in
``tests/ortografia/casi.json``.

Vincoli di parita' Python/JS rispettati qui:

* mai ``\\b \\w \\d \\s`` nei pattern (``\\d`` sono 680 codepoint in Python e
  10 in JS, ``\\w`` differisce di oltre 5000): le classi sono congelate a
  intervalli espliciti costruiti con ``chr()``. L'unica eccezione ammessa e'
  ``[\\s\\S]``, che in entrambi i motori significa "qualunque carattere";
* mai lookbehind: si consuma il carattere di confine e lo si riemette;
* mai ``IGNORECASE``: le varianti di caso sono precalcolate;
* mai ``re.escape`` e mai una stringa di rimpiazzo (``\\1`` fa fallire
  Python, ``$&`` corrompe JS): sempre una funzione.

Nessuna dipendenza esterna e nessun import interno: i test devono poter
importare questo modulo senza tirarsi dietro loguru o supabase.
"""

import re
import unicodedata

# --------------------------------------------------------------- costanti

# Sentinelli di mascheramento: area a uso privato, mai presente in prosa.
_S_INIZIO = chr(0xE000)
_S_FINE = chr(0xE001)
# Frammento di classe: l'intero intervallo riservato ai sentinelli.
_PUA = chr(0xE000) + "-" + chr(0xE00F)

# "Carattere di parola", congelato a intervalli espliciti: lettere latine di
# base, cifre ASCII, underscore, i supplementi latini e i segni combinanti.
_C = (
    "A-Za-z0-9_"
    + chr(0x00C0) + "-" + chr(0x024F)
    + chr(0x0300) + "-" + chr(0x036F)
    + chr(0x1E00) + "-" + chr(0x1EFF)
)
# Tutte le forme usate come apostrofo.
_APOS = (
    "'"
    + chr(0x2018) + chr(0x2019) + chr(0x02BC)
    + chr(0x02B9) + chr(0x2032) + chr(0x0060) + chr(0x00B4)
)
# Confine sinistro: inizio del testo oppure un carattere che non e' di parola.
_SX = "(^|[^" + _C + "])"
# Spazi orizzontali, esplicitati per non usare \s.
_SPAZI = " \t"

_LIMITE_RIGHE_FENCE = 200
_MAX_SEGN_PER_PAROLA = 3
_MAX_SEGN_PER_TESTO = 12

# Maiuscole senza chiamare str.upper(): mappa esplicita, identica in JS.
_MAIUSCOLE = {}
for _i in range(26):
    _MAIUSCOLE[chr(97 + _i)] = chr(65 + _i)
for _basso, _alto in (
    (0x00E0, 0x00C0), (0x00E1, 0x00C1), (0x00E8, 0x00C8), (0x00E9, 0x00C9),
    (0x00EC, 0x00CC), (0x00ED, 0x00CD), (0x00F2, 0x00D2), (0x00F3, 0x00D3),
    (0x00F9, 0x00D9), (0x00FA, 0x00DA),
):
    _MAIUSCOLE[chr(_basso)] = chr(_alto)


def _su(carattere):
    return _MAIUSCOLE.get(carattere, carattere)


def _iniziale_maiuscola(testo):
    if not testo:
        return testo
    return _su(testo[0]) + testo[1:]


def _tutto_maiuscolo(testo):
    return "".join(_su(c) for c in testo)


# `-` e `/` sono letterali fuori da una classe in entrambi i motori, e
# `\\-` fuori da una classe e' un errore in JS con il flag u: non si escapano.
_DA_ESCAPARE = set(".*+?^$}{()|[]\\")


def _esc(testo):
    """Escaping deterministico: mai re.escape, che differisce fra le versioni."""
    return "".join(("\\" + c) if c in _DA_ESCAPARE else c for c in testo)


def _classe_parola_insensibile(parola):
    """`pdf` -> `[Pp][Dd][Ff]`: alternativa a IGNORECASE, identica in JS."""
    fuori = []
    for c in parola:
        alto = _su(c)
        fuori.append("[" + c + alto + "]" if alto != c else c)
    return "".join(fuori)


# ----------------------------------------------------------------- tabelle
#
# LISTA 2 - correzione automatica. Criterio di ammissione: la forma senza
# accento NON e' una parola italiana valida ne' un nome proprio d'uso, e la
# forma accentata lo e'. Le voci con un omografo verbale reale (necessita,
# disabilita, abilita, eredita, capacita, gratuita, unita) stanno in LISTA 3.

LISTA_2 = [
    # composti di -che: accento ACUTO
    ("perche", "perché"), ("poiche", "poiché"),
    ("affinche", "affinché"), ("benche", "benché"),
    ("nonche", "nonché"), ("sicche", "sicché"),
    ("finche", "finché"), ("purche", "purché"),
    ("anziche", "anziché"), ("dopodiche", "dopodiché"),
    ("cosicche", "cosicché"), ("fuorche", "fuorché"),
    ("dacche", "dacché"),
    # accento GRAVE
    ("cioe", "cioè"), ("percio", "perciò"), ("puo", "può"),
    ("cosi", "così"), ("gia", "già"), ("piu", "più"),
    # nomi in -ita senza omografo verbale
    ("citta", "città"), ("universita", "università"),
    ("societa", "società"), ("liberta", "libertà"),
    ("qualita", "qualità"), ("accessibilita", "accessibilità"),
    ("attivita", "attività"), ("novita", "novità"),
    ("possibilita", "possibilità"), ("identita", "identità"),
    ("comunita", "comunità"), ("autorita", "autorità"),
    ("realta", "realtà"), ("modalita", "modalità"),
    ("priorita", "priorità"), ("validita", "validità"),
    ("verita", "verità"), ("responsabilita", "responsabilità"),
    ("difficolta", "difficoltà"), ("facolta", "facoltà"),
    ("specialita", "specialità"),
    ("particolarita", "particolarità"),
    ("opportunita", "opportunità"), ("maturita", "maturità"),
    ("idoneita", "idoneità"), ("anzianita", "anzianità"),
    ("continuita", "continuità"), ("titolarita", "titolarità"),
    ("disponibilita", "disponibilità"), ("parita", "parità"),
    ("professionalita", "professionalità"),
    ("invalidita", "invalidità"), ("annualita", "annualità"),
    ("mensilita", "mensilità"),
    ("obbligatorieta", "obbligatorietà"),
    ("legalita", "legalità"), ("scolarita", "scolarità"),
    ("sanita", "sanità"), ("pubblicita", "pubblicità"),
    # futuri di terza persona singolare
    ("potra", "potrà"), ("dovra", "dovrà"),
    ("sapra", "saprà"), ("vorra", "vorrà"),
    ("stara", "starà"), ("bastera", "basterà"),
    ("restera", "resterà"), ("tornera", "tornerà"),
    ("arrivera", "arriverà"), ("iniziera", "inizierà"),
    ("partira", "partirà"), ("scadra", "scadrà"),
    ("chiudera", "chiuderà"), ("aprira", "aprirà"),
    ("entrera", "entrerà"), ("avra", "avrà"),
    ("seguira", "seguirà"), ("finira", "finirà"),
    ("servira", "servirà"), ("costera", "costerà"),
    ("durera", "durerà"), ("permettera", "permetterà"),
    ("consentira", "consentirà"), ("prevedera", "prevederà"),
    ("stabilira", "stabilirà"), ("decidera", "deciderà"),
    ("ricevera", "riceverà"), ("otterra", "otterrà"),
    ("rimarra", "rimarrà"), ("avverra", "avverrà"),
    ("riguardera", "riguarderà"), ("cambiera", "cambierà"),
    ("aumentera", "aumenterà"),
    ("partecipera", "parteciperà"),
    ("presentera", "presenterà"),
    ("pubblichera", "pubblicherà"),
    ("comunichera", "comunicherà"), ("varera", "varerà"),
    # futuri di prima persona singolare, senza omografi
    ("andro", "andrò"), ("potro", "potrò"),
    ("dovro", "dovrò"), ("sapro", "saprò"),
    ("vorro", "vorrò"), ("terro", "terrò"),
    # giorni della settimana
    ("lunedi", "lunedì"), ("martedi", "martedì"),
    ("mercoledi", "mercoledì"), ("giovedi", "giovedì"),
    ("venerdi", "venerdì"),
    # accento presente ma sbagliato: la forma scritta non esiste comunque
    ("perchè", "perché"), ("poichè", "poiché"),
    ("affinchè", "affinché"), ("benchè", "benché"),
    ("nonchè", "nonché"), ("sicchè", "sicché"),
    ("finchè", "finché"), ("purchè", "purché"),
    ("anzichè", "anziché"), ("dopodichè", "dopodiché"),
    ("cosicchè", "cosicché"), ("fuorchè", "fuorché"),
    ("giacchè", "giacché"), ("dacchè", "dacché"),
    ("nè", "né"), ("sè", "sé"), ("pò", "po'"),
    ("cioé", "cioè"), ("caffé", "caffè"),
    ("qual'è", "qual è"), ("qual'era", "qual era"),
    ("qual'erano", "qual erano"),
]

# LISTA 2b - si corregge SOLO se tutta minuscola: con l'iniziale maiuscola la
# forma e' un nome proprio d'uso corrente e si emette solo una segnalazione.
LISTA_2B = [
    ("sara", "sarà"), ("dara", "darà"), ("fara", "farà"),
    ("andra", "andrà"), ("verra", "verrà"),
    ("caffe", "caffè"),
]

# LISTA 1 - forme che esistono SOLO con l'apostrofo. Le altre sono derivate
# automaticamente da LISTA 2 e 2b come "forma nuda + apostrofo".
SOLO_APOSTROFO = [
    ("e'", "è"), ("si'", "sì"), ("la'", "là"),
    ("li'", "lì"), ("giu'", "giù"), ("eta'", "età"),
    ("meta'", "metà"), ("pero'", "però"),
    ("terra'", "terrà"), ("papa'", "papà"),
    ("faro'", "farò"), ("saro'", "sarò"),
    ("daro'", "darò"), ("verro'", "verrò"),
    ("staro'", "starò"), ("unita'", "unità"),
    ("necessita'", "necessità"),
    ("disabilita'", "disabilità"), ("abilita'", "abilità"),
    ("capacita'", "capacità"), ("eredita'", "eredità"),
    ("gratuita'", "gratuità"),
]

# Apostrofo legittimo di troncamento o di aferesi: mai candidato.
# Non e' una struttura di runtime, e' il contratto verificato dai test.
DENY = [
    "po'", "mo'", "fa'", "da'", "di'", "va'", "sta'", "be'", "to'", "ca'",
    "de'", "fra'", "pro'", "ne'", "a'", "co'", "vo'", "so'", "i'", "tra'",
    "me'", "ve'", "su'", "no'",
]

# LISTA 3a - omografe ad alta frequenza: segnalate solo se il testo in
# ingresso era gia' dimostrabilmente de-accentato (vedi il gate anti-rumore).
LISTA_3A = [
    ("e", "è"), ("da", "dà"), ("si", "sì"),
    ("la", "là"), ("ne", "né"), ("se", "sé"),
    ("li", "lì"), ("te", "tè"), ("ancora", "àncora"),
    ("meta", "metà"), ("terra", "terrà"),
    ("unita", "unità"), ("papa", "papà"),
    ("pero", "però"), ("faro", "farò"),
]

# LISTA 3b - omografe rare o tecniche: segnalate sempre, il rumore e' basso.
LISTA_3B = [
    ("necessita", "necessità"), ("disabilita", "disabilità"),
    ("abilita", "abilità"), ("eredita", "eredità"),
    ("gratuita", "gratuità"), ("capacita", "capacità"),
    ("eta", "età"), ("giu", "giù"), ("saro", "sarò"),
    ("daro", "darò"), ("verro", "verrò"),
    ("staro", "starò"),
    # varianti editoriali storiche con l'acuto su i/u: mai correggere
    ("piú", "più"), ("cosí", "così"),
    ("giú", "giù"),
]

# Preposizioni che reggono il pronome tonico: solo dopo una di queste
# "se'" viene corretto in "se'" accentato (di per se', in se', fra se').
PREPOSIZIONI_SE = [
    "per", "di", "in", "con", "tra", "fra", "da", "su", "sopra", "verso",
]

# Estensioni di file riconosciute come token da mascherare.
_ESTENSIONI = [
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar",
    "jpg", "jpeg", "png", "gif", "svg", "webp", "csv", "txt", "xml", "json",
]
# Domini di primo livello riconosciuti nei riferimenti senza schema.
_TLD = ["it", "com", "org", "net", "eu", "edu", "gov"]


# ------------------------------------------------------- varianti di caso

def _ammette_maiuscolo(forma):
    """Il ramo TUTTO MAIUSCOLO e' spento sotto le 5 lettere per non toccare
    le sigle (ETA, PIU, GIA, PUO). Un accento o un apostrofo nella forma
    escludono la sigla, quindi riabilitano il ramo."""
    for c in forma:
        if ord(c) > 127 or c == "'":
            return True
    return len(forma) >= 5


def _coppie_varianti(sorgente, destinazione):
    coppie = [(sorgente, destinazione)]
    titolo = _iniziale_maiuscola(sorgente)
    if titolo != sorgente:
        coppie.append((titolo, _iniziale_maiuscola(destinazione)))
    if _ammette_maiuscolo(sorgente):
        alto = _tutto_maiuscolo(sorgente)
        if all(alto != c[0] for c in coppie):
            coppie.append((alto, _tutto_maiuscolo(destinazione)))
    return coppie


def _e_ascii_minuscolo(forma):
    for c in forma:
        if not ("a" <= c <= "z"):
            return False
    return len(forma) > 0


def _derivate_con_apostrofo():
    """LISTA 1 non si scrive a mano: ogni forma nuda di LISTA 2 e 2b diventa
    automaticamente una voce con l'apostrofo finale. L'apostrofo disambigua,
    quindi anche le voci di 2b qui valgono in tutte le varianti di caso."""
    fuori = []
    for sorgente, destinazione in LISTA_2 + LISTA_2B:
        if _e_ascii_minuscolo(sorgente):
            fuori.append((sorgente + "'", destinazione))
    return fuori


_MAPPA = {}
_TIPO = {}
_SEGNALA_2B = {}

for _s, _d in SOLO_APOSTROFO + _derivate_con_apostrofo():
    for _vs, _vd in _coppie_varianti(_s, _d):
        _MAPPA[_vs] = _vd
        _TIPO[_vs] = "apostrofo"

for _s, _d in LISTA_2:
    for _vs, _vd in _coppie_varianti(_s, _d):
        _MAPPA[_vs] = _vd
        _TIPO[_vs] = "nuda"

for _s, _d in LISTA_2B:
    _MAPPA[_s] = _d
    _TIPO[_s] = "nuda"
    # Le varianti con la maiuscola non si correggono mai, ma si segnalano
    # sempre: anche TUTTO MAIUSCOLO, che il ramo delle sigle escluderebbe.
    # Una segnalazione non tocca il testo, quindi non ha il rischio che ha
    # motivato quella soglia ("SARA UTILE PER TUTTI" va comunque notato).
    for _vs, _vd in (
        (_iniziale_maiuscola(_s), _iniziale_maiuscola(_d)),
        (_tutto_maiuscolo(_s), _tutto_maiuscolo(_d)),
    ):
        if _vs == _s or _vs in _SEGNALA_2B:
            continue
        _SEGNALA_2B[_vs] = _vd
        _TIPO[_vs] = "nuda"

_BASE_3 = {}
_GATE_3 = {}
for _s, _d in LISTA_3A + LISTA_3B:
    _gated = any(_s == a for a, _ in LISTA_3A)
    for _vs, _vd in _coppie_varianti(_s, _d):
        _BASE_3[_vs] = (_s, _vd)
        _GATE_3[_vs] = _gated


def _ordina_chiavi(chiavi):
    """Deduplica, poi ordina: piu' lunga prima, quindi per codepoint. Tutte
    le chiavi stanno nel BMP, quindi l'ordinamento Python e quello JS
    coincidono (codepoint contro unita' UTF-16)."""
    viste = {}
    for chiave in chiavi:
        viste[chiave] = True
    return sorted(viste.keys(), key=lambda k: (-len(k), k))


def _confine_destro(tipo):
    if tipo == "apostrofo":
        return "(?![" + _C + "])"
    return "(?![" + _C + _APOS + "])"


def _alternanza(chiavi, tipi):
    return "|".join(_esc(k) + _confine_destro(tipi[k]) for k in chiavi)


_CHIAVI_PRINCIPALI = _ordina_chiavi(list(_MAPPA.keys()) + list(_SEGNALA_2B.keys()))
_RE_PRINCIPALE = re.compile(
    _SX + "(" + _alternanza(_CHIAVI_PRINCIPALI, _TIPO) + ")"
)

_CHIAVI_3 = _ordina_chiavi(list(_BASE_3.keys()))
_RE_SEGNALAZIONI = re.compile(
    _SX + "(" + "|".join(
        _esc(k) + "(?![" + _C + _APOS + "])" for k in _CHIAVI_3
    ) + ")"
)

# "se'" si corregge solo dopo una preposizione che regge il pronome tonico.
_ALT_PREP = "|".join(
    _classe_parola_insensibile(p) for p in PREPOSIZIONI_SE
)
_RE_SE_PREP = re.compile(
    _SX + "((?:" + _ALT_PREP + ")[" + _SPAZI + "]+)([Ss]e')(?![" + _C + "])"
)


# --------------------------------------------------------- mascheramento

_LETTERE = "A-Za-z" + chr(0x00C0) + "-" + chr(0x024F)
_NON_URL = " " + chr(9) + chr(10) + "<>\"'()\\[\\]" + _PUA
_VIRG = "'" + chr(0x2018) + chr(0x2019)


def _alt_insensibile(parole):
    return "|".join(_classe_parola_insensibile(p) for p in parole)


def _c(*parti):
    return "".join(parti)


# Ogni maschera e' (regex, indice del gruppo da mascherare). Indice 0 =
# tutta la corrispondenza. L'ordine conta: i contenitori prima dei contenuti,
# e i bersagli dei link prima degli URL nudi.
_MASCHERE = [
    # commenti e blocchi non testuali
    (re.compile("<!--[\\s\\S]*?-->"), 0),
    (re.compile("<" + _classe_parola_insensibile("script")
                + "[\\s\\S]*?</" + _classe_parola_insensibile("script") + ">"), 0),
    (re.compile("<" + _classe_parola_insensibile("style")
                + "[\\s\\S]*?</" + _classe_parola_insensibile("style") + ">"), 0),
    # codice inline prima dei tag: dentro i backtick il markup resta intatto
    (re.compile("`[^`" + chr(10) + _PUA + "]+`"), 0),
    # tag HTML consapevole delle virgolette: <img alt="a > b" src="...">
    (re.compile("<[a-zA-Z/!?](?:\"[^\"]*\"|'[^']*'|[^>\"'" + _PUA + "])*>"), 0),
    # bersaglio di immagine: parentesi bilanciate, la didascalia resta prosa
    (re.compile("(!\\[[^\\]" + chr(10) + _PUA + "]*\\])"
                + "(\\((?:[^()" + chr(10) + _PUA + "]"
                + "|\\([^()" + chr(10) + _PUA + "]*\\))*\\))"), 2),
    # bersaglio di link
    (re.compile("(\\])(\\((?:[^()" + chr(10) + _PUA + "]"
                + "|\\([^()" + chr(10) + _PUA + "]*\\))*\\))"), 2),
    # sintassi della skill: [LINK:testo|url]
    (re.compile("(\\[LINK:[^\\]|" + chr(10) + "]*\\|)([^\\]" + chr(10) + "]*)(\\])"), 2),
    # ancora di heading
    (re.compile("\\{#[0-9A-Za-z_\\-]+\\}"), 0),
    # URL con schema o con www.
    (re.compile("(?:" + _alt_insensibile(["http"]) + "[sS]?://|"
                + _alt_insensibile(["ftp"]) + "://|"
                + _alt_insensibile(["www"]) + "\\.)[^" + _NON_URL + "]+"), 0),
    # email
    (re.compile("[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z][A-Za-z]+"), 0),
    # dominio nudo senza schema: miur.gov.it/attivita
    (re.compile("(?:[a-zA-Z0-9\\-]+\\.)+(?:" + _alt_insensibile(_TLD) + ")"
                + "(?:/[^" + _NON_URL + "]*)?"), 0),
    # percorso relativo, solo se preceduto da inizio riga o da un separatore
    (re.compile("(^|[ " + chr(9) + "(\\[\"])((?:\\.\\.?)?/[A-Za-z0-9_\\-/.#?=&%]*)"), 2),
    # hashtag e menzioni
    (re.compile("(^|[ " + chr(9) + "(\\[])([#@][A-Za-z0-9_\\-]+)"), 2),
    # nome di file
    (re.compile("[A-Za-z0-9_\\-]+\\.(?:" + _alt_insensibile(_ESTENSIONI) + ")"), 0),
    # slug con cifre finali: bando-universita-2026
    (re.compile("[a-z]+(?:-[a-z0-9]+)*-[0-9][0-9]+"), 0),
    # parola seguita da entita': impedisce il doppio accento su perche&#768;
    (re.compile("[" + _LETTERE + "]+(?:&#?[0-9A-Za-z]+;)+"), 0),
    # entita' residue
    (re.compile("&#?[0-9A-Za-z]+;"), 0),
    # menzione fra virgolette brevi: 'e' citato come parola, non elisione
    (re.compile("(^|[ " + chr(9) + "(\\[" + chr(0x00AB) + "\"])"
                + "([" + _VIRG + "][^" + _VIRG + chr(10) + _PUA + "]{1,24}["
                + _VIRG + "])(?![" + _LETTERE + "0-9])"), 2),
]

_RE_PUA = re.compile("[" + _PUA + "]")
_RE_CONTROLLI = re.compile(
    "[" + chr(0) + "-" + chr(8) + chr(11) + chr(12) + chr(14) + "-" + chr(31)
    + chr(127) + "-" + chr(159) + chr(0xFEFF) + "]"
)
_RE_APOSTROFO = re.compile(
    "([" + _C + "])[" + chr(0x2018) + chr(0x2019) + chr(0x02BC)
    + chr(0x02B9) + chr(0x2032) + chr(0x0060) + chr(0x00B4) + "]"
)


def _token(store, testo):
    store.append(testo)
    return _S_INIZIO + str(len(store) - 1) + _S_FINE


def _senza_spazi_iniziali(riga):
    i = 0
    while i < len(riga) and (riga[i] == " " or riga[i] == chr(9)):
        i += 1
    return riga[i:]


def _maschera_righe(testo, store):
    """Blocchi di codice recintati e righe di citazione: si mascherano per
    riga, non per regex, cosi' i due gemelli non dipendono da re.M / flag m."""
    righe = testo.split(chr(10))
    fuori = []
    i = 0
    n = len(righe)
    while i < n:
        nuda = _senza_spazi_iniziali(righe[i])
        delim = None
        if nuda[:3] == "```":
            delim = "```"
        elif nuda[:3] == "~~~":
            delim = "~~~"
        if delim is not None:
            j = i + 1
            chiuso = -1
            while j < n and (j - i) <= _LIMITE_RIGHE_FENCE:
                if _senza_spazi_iniziali(righe[j])[:3] == delim:
                    chiuso = j
                    break
                j += 1
            if chiuso >= 0:
                fuori.append(_token(store, chr(10).join(righe[i:chiuso + 1])))
                i = chiuso + 1
                continue
            # recinto spaiato: non si maschera nulla
        if nuda[:1] == ">":
            fuori.append(_token(store, righe[i]))
            i += 1
            continue
        fuori.append(righe[i])
        i += 1
    return chr(10).join(fuori)


def _maschera(testo, store):
    testo = _maschera_righe(testo, store)
    for regex, gruppo in _MASCHERE:
        if gruppo == 0:
            testo = regex.sub(lambda m: _token(store, m.group(0)), testo)
        else:
            testo = regex.sub(
                lambda m, g=gruppo: (
                    "".join(m.group(k) or "" for k in range(1, g))
                    + _token(store, m.group(g))
                    + "".join(
                        m.group(k) or ""
                        for k in range(g + 1, (m.re.groups or 0) + 1)
                    )
                ),
                testo,
            )
    return testo


def _smaschera(testo, store):
    """Indice decrescente: un contenitore mascherato dopo il suo contenuto ha
    indice maggiore, quindi va espanso per primo."""
    for n in range(len(store) - 1, -1, -1):
        testo = testo.replace(_S_INIZIO + str(n) + _S_FINE, store[n])
    return testo


# ------------------------------------------------------------- interfaccia

def _normalizza_terminatori(testo):
    testo = testo.replace(chr(13) + chr(10), chr(10))
    testo = testo.replace(chr(13), chr(10))
    testo = testo.replace(chr(0x2028), chr(10))
    testo = testo.replace(chr(0x2029), chr(10))
    testo = testo.replace(chr(0x0085), chr(10))
    return testo


def _vuoto(testo, saltato):
    return {
        "testo": testo,
        "correzioni": [],
        "segnalazioni": [],
        "saltato": saltato,
    }


def _segnala(testo, gate, gia_raccolte):
    fuori = list(gia_raccolte)
    conteggio = {}
    for corrispondenza in _RE_SEGNALAZIONI.finditer(testo):
        parola = corrispondenza.group(2)
        base, suggerimento = _BASE_3[parola]
        if _GATE_3[parola] and not gate:
            continue
        visto = conteggio.get(base, 0)
        if visto >= _MAX_SEGN_PER_PAROLA:
            continue
        conteggio[base] = visto + 1
        fuori.append({
            "regola": "omografo",
            "parola": parola,
            "occorrenza": visto + 1,
            "suggerimento": suggerimento,
        })
        if len(fuori) >= _MAX_SEGN_PER_TESTO:
            break
    return fuori[:_MAX_SEGN_PER_TESTO]


def correggi(testo):
    """Corregge gli accenti italiani mancanti o resi con l'apostrofo.

    Ritorna un dizionario con ``testo`` (il risultato), ``correzioni`` (cosa
    e' stato cambiato), ``segnalazioni`` (le ambiguita' che NON si correggono
    da sole) e ``saltato`` (il motivo, se il testo e' stato lasciato intatto).

    E' idempotente sul testo: ``correggi(correggi(x))`` produce lo stesso
    testo di ``correggi(x)``. Non lo e' sulle segnalazioni, che dipendono per
    costruzione dallo stato de-accentato del testo in ingresso.
    """
    if not isinstance(testo, str):
        return _vuoto(testo, "non_stringa")
    if testo == "":
        return _vuoto(testo, None)
    originale = testo
    if _RE_PUA.search(originale):
        # Sentinelli gia' presenti nel testo dell'autore: non si tocca nulla,
        # cancellarli in silenzio sarebbe perdita di dati.
        return _vuoto(originale, "pua_in_ingresso")

    lavorato = _normalizza_terminatori(originale)
    lavorato = _RE_CONTROLLI.sub("", lavorato)

    store = []
    lavorato = _maschera(lavorato, store)
    lavorato = unicodedata.normalize("NFC", lavorato)
    lavorato = _RE_APOSTROFO.sub(lambda m: m.group(1) + "'", lavorato)

    correzioni = []
    conteggio_corr = {}

    def _registra(da, a):
        visto = conteggio_corr.get(da, 0) + 1
        conteggio_corr[da] = visto
        correzioni.append({"da": da, "a": a, "occorrenza": visto})

    def _corr_se(corrispondenza):
        parola = corrispondenza.group(3)
        sostituto = "sé" if parola[0] == "s" else "Sé"
        _registra(parola, sostituto)
        return corrispondenza.group(1) + corrispondenza.group(2) + sostituto

    lavorato = _RE_SE_PREP.sub(_corr_se, lavorato)

    segnalazioni_2b = []
    conteggio_2b = {}

    def _corr(corrispondenza):
        sinistra = corrispondenza.group(1)
        parola = corrispondenza.group(2)
        if parola in _MAPPA:
            sostituto = _MAPPA[parola]
            _registra(parola, sostituto)
            return sinistra + sostituto
        visto = conteggio_2b.get(parola, 0) + 1
        conteggio_2b[parola] = visto
        segnalazioni_2b.append({
            "regola": "nome-proprio",
            "parola": parola,
            "occorrenza": visto,
            "suggerimento": _SEGNALA_2B[parola],
        })
        return sinistra + parola

    lavorato = _RE_PRINCIPALE.sub(_corr, lavorato)
    segnalazioni = _segnala(lavorato, len(correzioni) > 0, segnalazioni_2b)
    lavorato = _smaschera(lavorato, store)

    if _RE_PUA.search(lavorato):
        # Smascheramento incompleto: si restituisce l'input ricevuto, non il
        # testo a meta' strada. Mai un fallback silenzioso.
        return _vuoto(originale, "sentinello_residuo")

    return {
        "testo": lavorato,
        "correzioni": correzioni,
        "segnalazioni": segnalazioni,
        "saltato": None,
    }


def applica(testo):
    """Scorciatoia per i chiamanti che vogliono solo il testo corretto."""
    return correggi(testo)["testo"]
