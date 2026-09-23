# -*- coding: utf-8 -*-
"""`bando_runner`: hash di `_build_record` e opzioni di `run` (fix 19/28).

  - `_build_record`: hash sul link, hash «senza link» sui discriminatori,
    `raw_data['hash_senza_link'] is True` forza la chiave senza link anche
    con link valorizzato (stesso hash della riga senza link: niente doppioni),
    record senza la chiave -> comportamento invariato;
  - `run(dry_run=True)` non chiama `upsert_bandi`; `run(limit=N)` tronca le
    fonti; `run()` senza argomenti scrive come prima.

DB, registro e scraper sono mock: nessuna rete, nessuna scrittura.
"""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

bando_runner = carica_modulo("bando_runner")
normalize = carica_modulo("normalize")
registro = carica_modulo("registro")
segnali_mod = carica_modulo("segnali")

ADESSO = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
BandoItem = bando_runner.BandoItem
_build_record = bando_runner._build_record
hash_bando = normalize.hash_bando

FONTE_ID = 42
LINK = "https://www.regione.example.it/bandi/avviso-1"
RAW_CSV = {"source_url": "https://www.regione.example.it/calendario.csv", "row_index": 3}


def _item(link=None, raw=None, titolo="Avviso pubblico formazione", fonte_id=FONTE_ID):
    return BandoItem(
        fonte_id=fonte_id, tipo_link="Opportunità", link_bando=link,
        titolo_raw=titolo, descrizione_raw=None, raw_data=raw,
    )


class TestBuildRecordHash(unittest.TestCase):
    def test_con_link_hash_sul_link(self):
        rec = _build_record(_item(link=LINK))
        self.assertEqual(rec["hash_bando"], hash_bando(FONTE_ID, LINK))
        self.assertEqual(rec["link_bando"], LINK)
        self.assertEqual(rec["fonte_id"], FONTE_ID)

    def test_senza_link_hash_sui_discriminatori(self):
        rec = _build_record(_item(raw=RAW_CSV))
        chiave = f"{RAW_CSV['source_url']}|p=|r=3|t={normalize.normalize_titolo('Avviso pubblico formazione')}"
        self.assertEqual(rec["hash_bando"], hash_bando(FONTE_ID, chiave))
        self.assertIsNone(rec["link_bando"])
        self.assertEqual(rec["raw_data"], RAW_CSV)

    def test_senza_link_e_senza_discriminatori_scartato(self):
        self.assertEqual(_build_record(_item(titolo=None)), {})
        self.assertEqual(_build_record(_item(titolo="  ", raw={})), {})

    def test_link_non_http_trattato_come_senza_link(self):
        rec = _build_record(_item(link="mailto:info@example.it", raw=RAW_CSV))
        self.assertEqual(rec["hash_bando"], _build_record(_item(raw=RAW_CSV))["hash_bando"])

    def test_hash_senza_link_true_mantiene_l_hash_della_riga_senza_link(self):
        """Il caso del parser CSV: la riga era in DB senza link; quando arriva un
        link l'hash resta quello vecchio e il link viene solo aggiunto."""
        prima = _build_record(_item(raw=RAW_CSV))
        dopo = _build_record(_item(link=LINK, raw={**RAW_CSV, "hash_senza_link": True}))
        self.assertEqual(dopo["hash_bando"], prima["hash_bando"])
        self.assertNotEqual(dopo["hash_bando"], hash_bando(FONTE_ID, LINK))
        self.assertEqual(dopo["link_bando"], LINK)
        self.assertIs(dopo["raw_data"]["hash_senza_link"], True)

    def test_senza_la_chiave_il_link_vince_come_prima(self):
        """Retro-compatibilita': stessi discriminatori ma senza la chiave ->
        hash sul link, esattamente come il codice storico."""
        rec = _build_record(_item(link=LINK, raw=dict(RAW_CSV)))
        self.assertEqual(rec["hash_bando"], hash_bando(FONTE_ID, LINK))

    def test_chiave_non_true_non_forza(self):
        for valore in (False, None, 0, "True", 1):
            with self.subTest(valore=valore):
                rec = _build_record(_item(link=LINK, raw={**RAW_CSV, "hash_senza_link": valore}))
                self.assertEqual(rec["hash_bando"], hash_bando(FONTE_ID, LINK))

    def test_hash_senza_link_true_senza_discriminatori_ripiega_sul_link(self):
        rec = _build_record(_item(link=LINK, raw={"hash_senza_link": True}, titolo=None))
        self.assertEqual(rec["hash_bando"], hash_bando(FONTE_ID, LINK))
        self.assertEqual(rec["link_bando"], LINK)

    def test_hash_senza_link_true_senza_link_ne_discriminatori_scartato(self):
        self.assertEqual(_build_record(_item(raw={"hash_senza_link": True}, titolo=None)), {})


class _ScraperFinto:
    """Due bandi per fonte: uno con link, uno senza."""
    name = "finto"

    async def scrape(self, fonte):
        return [
            _item(link=f"{fonte['link']}/bando-1", fonte_id=fonte["id"]),
            _item(raw={"source_url": fonte["link"], "row_index": 1}, fonte_id=fonte["id"]),
        ]


class TestRunDryRunELimit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fonti = [
            {"id": 1, "link": "https://a.example.it", "tipo_link": "Opportunità", "formato_link": "HTML"},
            {"id": 2, "link": "https://b.example.it", "tipo_link": "Opportunità", "formato_link": "HTML"},
            {"id": 3, "link": "https://c.example.it", "tipo_link": "Preavviso", "formato_link": "HTML"},
        ]
        config = {f["link"]: {"strategy": "finta"} for f in self.fonti}
        self.upsert = MagicMock(return_value={"processed": 2, "dedup_collisions": 0})
        self.select = MagicMock(return_value=list(self.fonti))
        self.log = MagicMock()
        # L'I/O dei segnali non deve mai toccare il DB: la rilettura non trova
        # niente (tutto nuovo, comportamento identico a prima di v11) e gli
        # eventi si contano senza scriverli.
        self.leggi = MagicMock(return_value={})
        self.scrivi = MagicMock(side_effect=lambda c, f: len(c.segnali) + len(c.spariti))
        patches = [
            patch.dict(bando_runner.SCRAPER_CONFIG, config, clear=True),
            patch.object(bando_runner, "get_scraper", return_value=_ScraperFinto()),
            patch.object(bando_runner, "select_fonti_ready", self.select),
            patch.object(bando_runner, "upsert_bandi", self.upsert),
            patch.object(bando_runner, "logger", self.log),
            patch.object(bando_runner, "leggi_esistenti", self.leggi),
            patch.object(bando_runner, "scrivi_segnali", self.scrivi),
            patch.object(bando_runner, "aggiorna_controlli", MagicMock(return_value=0)),
            patch.object(bando_runner, "conteggi_da_fonte_run", MagicMock(return_value={})),
            patch.object(bando_runner, "_telemetria_fonte", MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # `registro.indice()` e' in `lru_cache` sul registro VERO: senza
        # azzerarla prima e dopo, l'indice costruito con il registro finto
        # sopravvive a questa classe e fa fallire `test_registro` (che
        # interroga il registro vero). Si azzera da entrambi i lati.
        registro.indice.cache_clear()
        self.addCleanup(registro.indice.cache_clear)

    async def test_default_scrive_come_prima(self):
        counters = await bando_runner.run()
        self.assertEqual(self.upsert.call_count, 3)
        self.assertEqual(counters["fonti_totali"], 3)
        self.assertEqual(counters["fonti_processate"], 3)
        self.assertEqual(counters["bandi_estratti"], 6)
        self.assertEqual(counters["bandi_con_link"], 3)
        self.assertEqual(counters["bandi_senza_link"], 3)
        self.assertEqual(counters["bandi_upsert_processed"], 6)

    async def test_dry_run_non_chiama_upsert(self):
        counters = await bando_runner.run(dry_run=True)
        self.upsert.assert_not_called()
        self.assertEqual(counters["fonti_processate"], 3)
        self.assertEqual(counters["bandi_estratti"], 6)
        self.assertEqual(counters["bandi_con_link"], 3)
        self.assertEqual(counters["bandi_senza_link"], 3)
        self.assertEqual(counters["bandi_upsert_processed"], 0)

    async def test_dry_run_logga_i_contatori_per_fonte(self):
        await bando_runner.run(dry_run=True)
        righe = [c.args for c in self.log.info.call_args_list if "DRY-RUN fonte_id=" in str(c.args[0])]
        self.assertEqual(len(righe), 3)
        # per ogni fonte: fonte_id, totale record, con link, senza link
        self.assertEqual({r[1:] for r in righe}, {(1, 2, 1, 1), (2, 2, 1, 1), (3, 2, 1, 1)})

    async def test_limit_tronca_la_lista_delle_fonti(self):
        counters = await bando_runner.run(limit=2)
        self.select.assert_called_once_with()
        self.assertEqual(self.upsert.call_count, 2)
        fonte_ids = {rec["fonte_id"] for call in self.upsert.call_args_list for rec in call.args[0]}
        self.assertEqual(fonte_ids, {1, 2})
        self.assertEqual(counters["fonti_totali"], 2)
        self.assertEqual(counters["fonti_processate"], 2)
        self.assertEqual(counters["bandi_estratti"], 4)

    async def test_limit_zero_nessuna_fonte(self):
        counters = await bando_runner.run(limit=0)
        self.upsert.assert_not_called()
        self.assertEqual(counters["fonti_totali"], 0)
        self.assertEqual(counters["fonti_processate"], 0)

    async def test_limit_oltre_le_fonti_disponibili(self):
        counters = await bando_runner.run(limit=99)
        self.assertEqual(counters["fonti_processate"], 3)
        self.assertEqual(self.upsert.call_count, 3)

    async def test_dry_run_e_limit_insieme(self):
        counters = await bando_runner.run(dry_run=True, limit=1)
        self.upsert.assert_not_called()
        self.assertEqual(counters["fonti_processate"], 1)
        self.assertEqual(counters["bandi_estratti"], 2)


class TestRegistroNormalizzato(unittest.IsolatedAsyncioTestCase):
    """Il runner cerca la configurazione per chiave NORMALIZZATA (fix 8.a.8)."""

    CHIAVE = "https://a.example.it/bandi?a=1&b=2"
    # Stessa pagina, scritta come la tabella `fonte` la conserva: slash finale,
    # parametri in ordine diverso, frammento. `SCRAPER_CONFIG.get()` non la
    # troverebbe, e la fonte resterebbe senza strategia.
    LINK_IN_TABELLA = "https://a.example.it/bandi/?b=2&a=1#sezione"

    def setUp(self):
        self.upsert = MagicMock(return_value={"processed": 2, "dedup_collisions": 0})
        patches = [
            patch.dict(bando_runner.SCRAPER_CONFIG,
                       {self.CHIAVE: {"strategy": "finta"}}, clear=True),
            patch.object(bando_runner, "get_scraper", return_value=_ScraperFinto()),
            patch.object(bando_runner, "select_fonti_ready", MagicMock(return_value=[
                {"id": 12, "link": self.LINK_IN_TABELLA,
                 "tipo_link": "Opportunità", "formato_link": "HTML"},
            ])),
            patch.object(bando_runner, "upsert_bandi", self.upsert),
            patch.object(bando_runner, "logger", MagicMock()),
            patch.object(bando_runner, "leggi_esistenti", MagicMock(return_value={})),
            patch.object(bando_runner, "scrivi_segnali", MagicMock(return_value=0)),
            patch.object(bando_runner, "aggiorna_controlli", MagicMock(return_value=0)),
            patch.object(bando_runner, "conteggi_da_fonte_run", MagicMock(return_value={})),
            patch.object(bando_runner, "_telemetria_fonte", MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        registro.indice.cache_clear()
        self.addCleanup(registro.indice.cache_clear)

    async def test_la_fonte_non_resta_senza_strategia(self):
        self.assertIsNone(bando_runner.SCRAPER_CONFIG.get(self.LINK_IN_TABELLA))
        counters = await bando_runner.run()
        self.assertEqual(counters["fonti_skipped_no_strategy"], 0)
        self.assertEqual(counters["fonti_processate"], 1)


class TestSegnaliNelRunner(unittest.IsolatedAsyncioTestCase):
    """L'innesto di §6.1 fra la composizione dei record e l'upsert."""

    def setUp(self):
        # Fonte 12, non una delle tre di Obiettivo Europa (449-451): la
        # famiglia decide quali chiavi entrano nel confronto, e su OE il
        # titolo non e' fra quelle.
        self.fonte = {"id": 12, "link": "https://a.example.it",
                      "tipo_link": "Opportunità", "formato_link": "HTML"}
        self.upsert = MagicMock(return_value={"processed": 1, "dedup_collisions": 0})
        self.log = MagicMock()
        patches = [
            patch.dict(bando_runner.SCRAPER_CONFIG,
                       {self.fonte["link"]: {"strategy": "finta"}}, clear=True),
            patch.object(bando_runner, "get_scraper", return_value=_ScraperFinto()),
            patch.object(bando_runner, "select_fonti_ready",
                         MagicMock(return_value=[dict(self.fonte)])),
            patch.object(bando_runner, "upsert_bandi", self.upsert),
            patch.object(bando_runner, "logger", self.log),
            patch.object(bando_runner, "conteggi_da_fonte_run", MagicMock(return_value={})),
            patch.object(bando_runner, "_telemetria_fonte", MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        registro.indice.cache_clear()
        self.addCleanup(registro.indice.cache_clear)

    async def _record_attesi(self):
        """I due record che lo scraper finto produce per questa fonte."""
        items = await _ScraperFinto().scrape(self.fonte)
        return [bando_runner._build_record(i) for i in items]

    async def test_riga_identica_non_viene_riscritta(self):
        record = await self._record_attesi()
        esistenti = {r["hash_bando"]: dict(r, id=i) for i, r in enumerate(record)}
        contatori = await bando_runner.run(
            leggi=lambda hashes: esistenti, scrivi=lambda c, f: 0,
            marca=lambda c, e: 0)
        self.upsert.assert_not_called()
        self.assertEqual(contatori["bandi_identici"], 2)
        self.assertEqual(contatori["bandi_cambiati"], 0)

    async def test_riga_cambiata_viene_riscritta(self):
        record = await self._record_attesi()
        esistenti = {
            r["hash_bando"]: dict(r, id=i, titolo_raw="Titolo vecchio")
            for i, r in enumerate(record)
        }
        contatori = await bando_runner.run(
            leggi=lambda hashes: esistenti, scrivi=lambda c, f: 0,
            marca=lambda c, e: 0)
        self.upsert.assert_called_once()
        self.assertEqual(len(self.upsert.call_args.args[0]), 2)
        self.assertEqual(contatori["bandi_cambiati"], 2)
        self.assertEqual(contatori["segnali"], 2)

    async def test_rilettura_fallita_degrada_al_comportamento_storico(self):
        def esplode(hashes):
            raise RuntimeError("PostgREST giu'")

        contatori = await bando_runner.run(
            leggi=esplode, scrivi=lambda c, f: 0, marca=lambda c, e: 0)
        # Nessuna riga persa: senza «prima» tutto e' nuovo e si scrive tutto.
        self.upsert.assert_called_once()
        self.assertEqual(contatori["bandi_nuovi"], 2)

    async def test_dry_run_non_scrive_i_segnali(self):
        record = await self._record_attesi()
        esistenti = {
            r["hash_bando"]: dict(r, id=i, titolo_raw="Titolo vecchio")
            for i, r in enumerate(record)
        }
        scrittore = MagicMock(return_value=2)
        marcatore = MagicMock(return_value=2)
        await bando_runner.run(
            dry_run=True, leggi=lambda hashes: esistenti, scrivi=scrittore,
            marca=marcatore)
        marcatore.assert_not_called()
        scrittore.assert_not_called()
        self.upsert.assert_not_called()


class _Controllo:
    """`db.controllo` finto: niente rete, colonne dichiarate a mano."""

    def __init__(self, tabelle):
        self._tabelle = {k: frozenset(v) for k, v in tabelle.items()}

    def colonne(self, tabella):
        return self._tabelle.get(tabella, frozenset())

    def tabella_esiste(self, tabella):
        return bool(self.colonne(tabella))


class _Query:
    """Catena PostgREST finta: registra upsert e select, non chiama niente."""

    def __init__(self, client, tabella):
        self._client = client
        self._tabella = tabella
        self._dati = []

    def upsert(self, righe, on_conflict=None):
        self._client.upsert.append((self._tabella, list(righe), on_conflict))
        return self

    def select(self, colonne):
        self._dati = self._client.righe.get(self._tabella, [])
        return self

    def in_(self, colonna, valori):
        self._dati = [r for r in self._dati if r.get(colonna) in set(valori)]
        return self

    def order(self, colonna, desc=False):
        self._dati = sorted(self._dati, key=lambda r: r.get(colonna) or "", reverse=desc)
        return self

    def limit(self, quanti):
        self._dati = self._dati[:quanti]
        return self

    def execute(self):
        return MagicMock(data=list(self._dati))


class _Client:
    def __init__(self, righe=None):
        self.upsert = []
        self.righe = righe or {}

    def table(self, nome):
        return _Query(self, nome)


class TestPresenzaEPriorita(unittest.TestCase):
    """§6.1 passi 4 e 5: `ultimo_visto_in_fonte_at` e `priorita_controllo`.

    Senza il passo 4 `segnali.spariti()` scarta ogni riga (la condizione
    «ultimo IS NOT NULL» non e' mai vera) e `sparito_dalla_fonte` non nasce
    mai; senza il passo 5 la priorita' 90 del mismatch `deadline_label` viene
    calcolata e buttata, cioe' i segnali C non raggiungono il monitor.
    """

    COLONNE = ("bando_id", "ultimo_visto_in_fonte_at", "priorita_controllo")

    def _confronto(self, visti=(), segnali=()):
        return segnali_mod.Confronto(visti=tuple(visti), segnali=tuple(segnali))

    def test_marca_la_presenza_di_ogni_hash_visto(self):
        client = _Client()
        confronto = self._confronto(visti=("h1", "h2"))
        esistenti = {"h1": {"id": 101}, "h2": {"id": 102}}
        scritte = bando_runner.aggiorna_controlli(
            confronto, esistenti, adesso=ADESSO, client=client,
            strumento=_Controllo({"bando_controllo": self.COLONNE}),
        )
        self.assertEqual(scritte, 2)
        tabella, righe, conflitto = client.upsert[0]
        self.assertEqual(tabella, "bando_controllo")
        self.assertEqual(conflitto, "bando_id")
        self.assertEqual([r["bando_id"] for r in righe], [101, 102])
        self.assertTrue(all(r["ultimo_visto_in_fonte_at"] == ADESSO.isoformat()
                            for r in righe))
        # Un solo UPSERT in blocco, non uno per riga.
        self.assertEqual(len(client.upsert), 1)

    def test_le_righe_nuove_non_hanno_ancora_un_id(self):
        client = _Client()
        scritte = bando_runner.aggiorna_controlli(
            self._confronto(visti=("h1",)), {}, adesso=ADESSO, client=client,
            strumento=_Controllo({"bando_controllo": self.COLONNE}),
        )
        self.assertEqual(scritte, 0)
        self.assertEqual(client.upsert, [])

    def test_la_priorita_del_segnale_arriva_alla_coda(self):
        client = _Client()
        segnale = segnali_mod.Segnale(
            tipo=segnali_mod.TIPO_SEGNALE, hash_bando="h1", bando_id=101,
            priorita=segnali_mod.PRIORITA_ALTA, campi=("deadline_label",))
        esistenti = {"h1": {"id": 101, "priorita_controllo": 30}}
        bando_runner.aggiorna_controlli(
            self._confronto(visti=("h1",), segnali=(segnale,)), esistenti,
            adesso=ADESSO, client=client,
            strumento=_Controllo({"bando_controllo": self.COLONNE}),
        )
        priorita = [r for _, righe, _ in client.upsert for r in righe
                    if "priorita_controllo" in r]
        self.assertEqual(priorita, [{"bando_id": 101, "priorita_controllo": 90}])

    def test_una_priorita_piu_alta_non_viene_abbassata(self):
        client = _Client()
        segnale = segnali_mod.Segnale(
            tipo=segnali_mod.TIPO_SEGNALE, hash_bando="h1", bando_id=101,
            priorita=segnali_mod.PRIORITA_MEDIA, campi=("modified",))
        esistenti = {"h1": {"id": 101, "priorita_controllo": 95}}
        bando_runner.aggiorna_controlli(
            self._confronto(visti=("h1",), segnali=(segnale,)), esistenti,
            adesso=ADESSO, client=client,
            strumento=_Controllo({"bando_controllo": self.COLONNE}),
        )
        priorita = [r for _, righe, _ in client.upsert for r in righe
                    if "priorita_controllo" in r]
        self.assertEqual(priorita[0]["priorita_controllo"], 95)

    def test_tabella_assente_degrada_a_zero(self):
        client = _Client()
        scritte = bando_runner.aggiorna_controlli(
            self._confronto(visti=("h1",)), {"h1": {"id": 101}},
            adesso=ADESSO, client=client, strumento=_Controllo({}),
        )
        self.assertEqual(scritte, 0)
        self.assertEqual(client.upsert, [])

    def test_la_presenza_seminata_fa_nascere_lo_sparito(self):
        # La controprova dell'innesto: con `ultimo_visto_in_fonte_at` a DB il
        # segnale esiste, senza no. E' la colonna che `_fondi_controlli`
        # porta dentro le righe del confronto.
        vecchio = (ADESSO - timedelta(days=5)).isoformat()
        riga = {"id": 101, "pubblicato": True, "stato_bando": "aperto",
                "data_scadenza": "2026-12-31"}
        senza = segnali_mod.spariti({"h1": dict(riga)}, (), adesso=ADESSO)
        self.assertEqual(senza, ())
        con = segnali_mod.spariti(
            {"h1": dict(riga, ultimo_visto_in_fonte_at=vecchio)}, (), adesso=ADESSO)
        self.assertEqual(len(con), 1)
        self.assertEqual(con[0].tipo, segnali_mod.TIPO_SPARITO)
        self.assertEqual(con[0].priorita, segnali_mod.PRIORITA_SPARITO)


class TestConteggiPrecedenti(unittest.TestCase):
    """La guardia «la fonte non si e' dimezzata» ha bisogno di un «prima»."""

    def test_legge_l_ultimo_giro_per_fonte(self):
        client = _Client({"fonte_run": [
            {"fonte_id": 12, "items": 900, "creato_at": "2026-09-22T06:00:00+00:00"},
            {"fonte_id": 12, "items": 1400, "creato_at": "2026-09-23T06:00:00+00:00"},
            {"fonte_id": 13, "items": 10, "creato_at": "2026-09-23T06:00:00+00:00"},
        ]})
        conteggi = bando_runner.conteggi_da_fonte_run(
            [{"id": 12}, {"id": 13}], client=client,
            strumento=_Controllo({"fonte_run": ("fonte_id", "items", "nuovi",
                                                "cambiati", "identici", "creato_at")}),
        )
        self.assertEqual(conteggi, {12: 1400, 13: 10})

    def test_items_nullo_ripiega_sulla_somma(self):
        client = _Client({"fonte_run": [
            {"fonte_id": 12, "items": None, "nuovi": 3, "cambiati": 7,
             "identici": 90, "creato_at": "2026-09-23T06:00:00+00:00"},
        ]})
        conteggi = bando_runner.conteggi_da_fonte_run(
            [{"id": 12}], client=client,
            strumento=_Controllo({"fonte_run": ("fonte_id", "items", "nuovi",
                                                "cambiati", "identici", "creato_at")}),
        )
        self.assertEqual(conteggi, {12: 100})

    def test_tabella_assente_non_solleva(self):
        self.assertEqual(
            bando_runner.conteggi_da_fonte_run(
                [{"id": 12}], client=_Client(), strumento=_Controllo({})),
            {},
        )

    def test_un_listing_dimezzato_toglie_la_copertura(self):
        # Con 400 elementi contro i 1400 del giro prima la copertura non e'
        # piena, quindi nessuno «sparito» viene emesso: e' un guasto della
        # fonte, non 1000 bandi ritirati.
        esito = SimpleNamespace(pagine=28, troncato=False, count=0)
        vecchio = (ADESSO - timedelta(days=5)).isoformat()
        esistenti = {f"h{i}": {"id": i, "pubblicato": True, "stato_bando": "aperto",
                               "data_scadenza": "2026-12-31",
                               "ultimo_visto_in_fonte_at": vecchio}
                     for i in range(3)}
        confronto = segnali_mod.confronta(
            {"id": 12}, [], esistenti, esito=esito,
            elementi_giro_precedente=1400, adesso=ADESSO)
        self.assertFalse(confronto.copertura_piena)
        self.assertEqual(confronto.spariti, ())


if __name__ == "__main__":
    unittest.main()
