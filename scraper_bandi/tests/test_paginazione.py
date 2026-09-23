# -*- coding: utf-8 -*-
"""Le letture che possono superare `max-rows` devono scorrere, non limitare.

PostgREST su questo progetto restituisce al massimo **1 000 righe** per
risposta e non lo dice: nessuna eccezione, nessun header che il client guardi,
nessun contatore. Una `.limit(5000)` riceve 1 000 righe e il chiamante le
tratta come se fossero tutte. E' la trappola piu' silenziosa del package,
perche' il danno non somiglia a un errore: somiglia a un corpus piu' piccolo.

Tre difetti misurati e chiusi qui:

* `select_pubblicati_per_gemelli(limit=5000)` leggeva i primi 1 000 pubblicati
  per id: `gemelli.py` cercava le corrispondenze esatte su meno di meta'
  corpus e i doppioni con id alto erano invisibili per costruzione;
* `select_bandi_da_monitorare` chiedeva `TETTO_CODA_MONITOR` (5 000) e ne
  riceveva 1 000 — e l'allarme scritto apposta per il troncamento era tarato
  su 5 000, quindi non poteva scattare mai;
* `select_link_da_verificare(bando_ids=[...])` con un lotto di 500 id si
  fermava a 1 000 righe: i bandi oltre quella soglia risultavano «scheda mai
  letta» e `oe-dettaglio` li riscaricava a ogni lancio (≈575 scarichi sprecati
  misurati in produzione il 23/09/2026).

Il finto client qui sotto fa due cose che un finto client ingenuo non fa:
applica il tetto di 1 000 righe **come il server**, e **solleva** se qualcuno
gli mette due volte `range`/`limit` sullo stesso oggetto. La seconda serve a
un difetto che nessun conteggio scoprirebbe: i builder di postgrest accumulano
i parametri con `add`, quindi riusare lo stesso builder per due pagine
produrrebbe `?limit=1000&limit=1000&offset=1000&offset=2000`.
"""
import sys
import unittest
import unittest.mock
from datetime import date
from types import SimpleNamespace

from tests.supporto import ALIAS, carica_modulo

db = carica_modulo("db")


TETTO_SERVER = 1000


class _Builder:
    """Una singola richiesta: accumula i filtri, li applica, taglia a 1 000."""

    def __init__(self, corpus, registro):
        self._corpus = corpus
        self._registro = registro
        self._filtri: list[tuple] = []
        self._offset = 0
        self._limite: int | None = None
        self._impaginato = 0

    # -- metodi che non cambiano le righe -----------------------------------
    def __getattr__(self, nome):
        def _chiama(*argomenti):
            self._filtri.append((nome, *argomenti))
            return self
        return _chiama

    def select(self, colonne):
        self._filtri.append(("select", colonne))
        return self

    def order(self, colonna, **_):
        self._filtri.append(("order", colonna))
        return self

    # -- impaginazione ------------------------------------------------------
    def limit(self, quanto, **_):
        self._conta_impaginazione()
        self._limite = int(quanto)
        return self

    def range(self, inizio, fine, *_, **__):
        self._conta_impaginazione()
        self._offset = int(inizio)
        self._limite = int(fine) - int(inizio) + 1
        return self

    def _conta_impaginazione(self):
        self._impaginato += 1
        if self._impaginato > 1:
            raise AssertionError(
                "range/limit messi due volte sullo stesso builder: postgrest li "
                "accumula con add(), la URL ne uscirebbe con due limit e due offset")

    # -- esecuzione ---------------------------------------------------------
    def execute(self):
        righe = list(self._corpus)
        for filtro in self._filtri:
            if filtro[0] == "in_":
                ammessi = set(filtro[2])
                righe = [r for r in righe if r.get(filtro[1]) in ammessi]
            elif filtro[0] == "eq":
                righe = [r for r in righe if r.get(filtro[1]) == filtro[2]]
        righe = righe[self._offset:]
        if self._limite is not None:
            righe = righe[:self._limite]
        # Il tetto del server, che nessun client vede: si applica per ultimo.
        troncato = len(righe) > TETTO_SERVER
        righe = righe[:TETTO_SERVER]
        self._registro.append({"filtri": self._filtri, "offset": self._offset,
                               "limite": self._limite, "righe": len(righe),
                               "troncato": troncato})
        return type("R", (), {"data": righe})()


class _Client:
    """Fa da `supabase.Client`: ogni `table()` restituisce un builder NUOVO."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.richieste: list[dict] = []

    def table(self, nome):
        return _Builder(self.corpus.get(nome, []), self.richieste)


def _strumento(colonne):
    schema = {"definitions": {
        nome: {"properties": {c: {} for c in cols}} for nome, cols in colonne.items()
    }}
    return db.Controllo(fornitore_schema=lambda: schema)


class TestScorri(unittest.TestCase):
    """Il motore dello scorrimento, da solo."""

    def test_si_ferma_quando_la_pagina_e_corta(self):
        pagine = [[{"id": i} for i in range(1000)], [{"id": i} for i in range(7)]]
        chiamate = []

        def _costruisci(quanto, salto):
            chiamate.append((quanto, salto))
            blocco = pagine.pop(0) if pagine else []
            return type("Q", (), {"execute": lambda _s=None, _b=blocco: type(
                "R", (), {"data": _b})()})()

        righe = db._scorri(_costruisci)
        self.assertEqual(len(righe), 1007)
        self.assertEqual(chiamate, [(1000, 0), (1000, 1000)])

    def test_il_tetto_e_l_unico_limite(self):
        def _costruisci(quanto, salto):
            return type("Q", (), {"execute": lambda _s=None, _q=quanto: type(
                "R", (), {"data": [{"id": i} for i in range(_q)]})()})()

        self.assertEqual(len(db._scorri(_costruisci, tetto=1500)), 1500)

    def test_tetto_zero_non_legge_niente(self):
        def _costruisci(quanto, salto):    # pragma: no cover - non deve girare
            raise AssertionError("con tetto 0 non si deve leggere nulla")

        self.assertEqual(db._scorri(_costruisci, tetto=0), [])


class TestGemelli(unittest.TestCase):
    """`select_pubblicati_per_gemelli`: 2 134 pubblicati, non i primi 1 000."""

    def setUp(self):
        self.corpus = {"bando": [
            {"id": i, "titolo": f"b{i}", "pubblicato": True} for i in range(1, 2135)]}
        self.client = _Client(self.corpus)
        self.strumento = _strumento({"bando": ["id", "titolo", "pubblicato", "slug"]})

    def test_legge_tutto_il_corpus_pubblicato(self):
        righe = db.select_pubblicati_per_gemelli(
            client=self.client, strumento=self.strumento)
        self.assertEqual(len(righe), 2134)
        self.assertEqual(righe[-1]["id"], 2134)

    def test_nessuna_richiesta_e_stata_troncata_dal_server(self):
        db.select_pubblicati_per_gemelli(client=self.client, strumento=self.strumento)
        self.assertFalse([r for r in self.client.richieste if r["troncato"]])

    def test_il_limite_esplicito_resta_un_limite(self):
        righe = db.select_pubblicati_per_gemelli(
            limit=1200, client=self.client, strumento=self.strumento)
        self.assertEqual(len(righe), 1200)


class TestCodaMonitor(unittest.TestCase):
    """`select_bandi_da_monitorare`: il tetto e' 5 000, non 1 000."""

    def _client(self, quanti):
        return _Client({"bando": [
            {"id": i, "slug": f"s{i}", "pubblicato": True,
             "fonte_ufficiale_stato": "trovata", "bando_master_id": None}
            for i in range(1, quanti + 1)]})

    def _strumento(self):
        return _strumento({"bando": [
            "id", "slug", "pubblicato", "fonte_ufficiale_stato", "bando_master_id",
            "stato_bando", "data_scadenza", "data_apertura", "titolo"]})

    def test_oltre_le_mille_righe(self):
        client = self._client(2134)
        righe = db.select_bandi_da_monitorare(client=client, strumento=self._strumento())
        self.assertEqual(len(righe), 2134)

    def test_il_tetto_dichiarato_vale_ed_e_l_allarme(self):
        client = self._client(db.TETTO_CODA_MONITOR + 500)
        righe = db.select_bandi_da_monitorare(client=client, strumento=self._strumento())
        # Il tetto taglia: e' dichiarato, e il chiamante lo riconosce contando
        # le righe (`len(righe) >= TETTO_CODA_MONITOR` in `monitoraggio`).
        self.assertEqual(len(righe), db.TETTO_CODA_MONITOR)

    def test_il_limite_dell_operatore_vince_sul_tetto(self):
        client = self._client(2134)
        righe = db.select_bandi_da_monitorare(
            limit=50, client=client, strumento=self._strumento())
        self.assertEqual(len(righe), 50)


class TestLetturePerId(unittest.TestCase):
    """`select_controlli` e `select_link_da_verificare` con lotti grandi."""

    def test_controlli_di_millecinquecento_bandi(self):
        client = _Client({"bando_controllo": [
            {"bando_id": i, "priorita_controllo": 50} for i in range(1, 1501)]})
        strumento = _strumento({"bando_controllo": [
            "bando_id", "prossimo_controllo_at", "ultimo_controllo_at",
            "priorita_controllo", "tentativi_resolver", "candidato_prioritario"]})
        mappa = db.select_controlli(
            list(range(1, 1501)), client=client, strumento=strumento)
        self.assertEqual(len(mappa), 1500)
        self.assertIn(1500, mappa)

    def test_link_di_un_lotto_con_piu_link_per_bando(self):
        """500 id, tre link a testa: 1 500 righe, una risposta sola ne dava 1 000."""
        righe = []
        for bando_id in range(1, 501):
            for n in range(3):
                righe.append({"id": bando_id * 10 + n, "bando_id": bando_id,
                              "url": f"https://ente.it/{bando_id}/{n}",
                              "impronta_pagina": "abc#1"})
        client = _Client({"bando_link": righe})
        strumento = _strumento({"bando_link": [
            "id", "bando_id", "url", "tipo", "origine", "etichetta", "esito_http",
            "pubblicabile", "ultimo_visto_at", "trovato_in_fonte_at", "content_type",
            "url_prova", "impronta_pagina", "updated_at"]})
        lette = db.select_link_da_verificare(
            bando_ids=list(range(1, 501)), client=client, strumento=strumento)
        self.assertEqual(len(lette), 1500)
        self.assertEqual(len({r["bando_id"] for r in lette}), 500)

    def test_nessun_bando_risulta_mai_letto_per_troncamento(self):
        """Il difetto misurato: i bandi in coda al lotto sembravano non letti."""
        fu = carica_modulo("fonte_ufficiale")
        righe = [{"id": i, "bando_id": i, "impronta_pagina": "sha#0"}
                 for i in range(1, 1201)]
        client = _Client({"bando_link": righe})
        strumento = _strumento({"bando_link": [
            "id", "bando_id", "url", "tipo", "origine", "etichetta", "esito_http",
            "pubblicabile", "ultimo_visto_at", "trovato_in_fonte_at", "content_type",
            "url_prova", "impronta_pagina", "updated_at"]})
        lette = db.select_link_da_verificare(
            bando_ids=list(range(1, 1201)), client=client, strumento=strumento)
        gia = fu.schede_gia_lette(list(range(1, 1201)), righe=lette)
        self.assertEqual(len(gia), 1200)
        self.assertIn(1200, gia)

    def test_i_blocchi_non_superano_la_dimensione_dichiarata(self):
        client = _Client({"bando_controllo": [
            {"bando_id": i} for i in range(1, 701)]})
        strumento = _strumento({"bando_controllo": ["bando_id", "priorita_controllo"]})
        db.select_controlli(list(range(1, 701)), client=client, strumento=strumento)
        for richiesta in client.richieste:
            blocchi = [f for f in richiesta["filtri"] if f[0] == "in_"]
            self.assertTrue(blocchi)
            self.assertLessEqual(len(blocchi[0][2]), db.BLOCCO_ID)


class TestABlocchi(unittest.TestCase):
    def test_scarta_i_none(self):
        self.assertEqual(db._a_blocchi([1, None, 2], 10), [[1, 2]])

    def test_lista_vuota(self):
        self.assertEqual(db._a_blocchi([], 10), [])

    def test_spezza_alla_dimensione(self):
        blocchi = db._a_blocchi(list(range(25)), 10)
        self.assertEqual([len(b) for b in blocchi], [10, 10, 5])


if __name__ == "__main__":    # pragma: no cover
    unittest.main()


class TestLimiteZero(unittest.TestCase):
    """`--limit 0` deve essere un no-op, in tutti i comandi che scorrono.

    La convenzione e' scritta in `db._pagina`: «uno zero e' un limite, ed e'
    quello che un operatore mette per non toccare niente». Sette selezioni la
    contraddicevano, perche' controllavano il limite **dopo** l'append: con
    `--limit 0 --attivo` il giro lavorava una riga e la scriveva davvero.

    Misurato prima della correzione: `link-verifica --limit 0 --attivo` faceva
    una HEAD e una scrittura su `bando_link`; `rigenera --malformati --limit 0
    --attivo` scriveva una riga in `bando_evento`.
    """

    SELEZIONI = (
        ("backfill", "_da_ripulire"),
        ("backfill", "_da_archiviare"),
        ("rigenera", "_malformati_da_segnalare"),
        ("rigenera", "_da_rigenerare"),
        ("fonte_ufficiale", "_da_risolvere"),
        ("fonte_ufficiale", "_da_leggere"),
        ("fonte_ufficiale", "_da_verificare"),
    )

    def test_ogni_selezione_esce_prima_di_leggere(self):
        """Con `limit=0` non si legge nulla: nemmeno la prima pagina.

        Si contano le letture invece di far sollevare il `db` finto: gli
        scorrimenti catturano `Exception` intorno alla lettura (e' il ripiego
        che tiene in piedi il giro su un DB non migrato), quindi un finto che
        solleva verrebbe zittito e il test passerebbe anche senza la guardia.
        """
        letture: list[tuple] = []

        def _registra(*argomenti, **parametri):
            letture.append((argomenti, parametri))
            return []

        for modulo_nome, funzione in self.SELEZIONI:
            with self.subTest(selezione=f"{modulo_nome}.{funzione}"):
                letture.clear()
                modulo = carica_modulo(modulo_nome)
                bersaglio = getattr(modulo, funzione)
                finto = SimpleNamespace(
                    select_bandi_pubblicati_contenuto=_registra,
                    select_processed_da_archiviare=_registra,
                    select_bandi_da_risolvere=_registra,
                    select_link_da_verificare=_registra,
                    select_eventi=_registra,
                    select_controlli=_registra,
                    controllo=SimpleNamespace(ha=lambda *_: True,
                                              tabella_esiste=lambda *_: True),
                )
                # Tre innesti, non uno: chi fa `from . import db` dentro la
                # funzione non vede l'attributo del modulo, e chi lo importa in
                # testa non vede `sys.modules`. Senza tutti e tre, il test
                # passerebbe anche senza la guardia — perche' il `db` vero
                # fallirebbe da solo sull'URL finto e tornerebbe zero righe.
                with unittest.mock.patch.dict(
                        sys.modules, {f"{ALIAS}.db": finto}), \
                        unittest.mock.patch.object(
                            sys.modules[ALIAS], "db", finto, create=True), \
                        unittest.mock.patch.object(modulo, "db", finto, create=True):
                    esito = self._chiama(bersaglio, funzione)
                righe = esito[0] if isinstance(esito, tuple) else esito
                self.assertEqual(list(righe), [])
                self.assertEqual(letture, [],
                                 "con --limit 0 la selezione ha letto dal DB")

    @staticmethod
    def _chiama(bersaglio, nome):
        """Ogni selezione ha parametri suoi: qui solo quelli obbligatori."""
        if nome == "_da_ripulire":
            return bersaglio(None, None, limit=0, offset=0, tabella_domini=None,
                             conto={"saltate": 0, "attraversate": 0})
        if nome == "_da_archiviare":
            return bersaglio(None, limit=0, offset=0, oggi=date(2026, 9, 23),
                             conto={"saltate": 0, "attraversate": 0}, da_lavorare=[])
        if nome == "_malformati_da_segnalare":
            return bersaglio(None, limit=0, offset=0,
                             contatori={"attraversati": 0, "saltati": 0})
        if nome == "_da_rigenerare":
            return bersaglio(None, None, limit=0, offset=0,
                             contatori={"attraversati": 0, "saltati": 0,
                                        "senza_riscrittore": 0})
        if nome == "_da_risolvere":
            return bersaglio(limit=0, offset=0, modo="nuovi", solo_oe=False,
                             solo_in_verifica=False, forza=False,
                             oggi=date(2026, 9, 23),
                             contatori=SimpleNamespace(saltate=0))
        if nome == "_da_leggere":
            return bersaglio(limit=0, offset=0, modo="nuovi", solo_oe=False,
                             bando_id=None, forza=False,
                             contatori={"saltate": 0, "da_scaricare": 0})
        return bersaglio(limit=0, offset=0, bando_id=None, oggi=date(2026, 9, 23),
                         contatori={"saltate": 0})
