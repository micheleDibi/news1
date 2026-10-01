# -*- coding: utf-8 -*-
"""`FonteDatiSupabase`: la coda del monitor e le sue tre scritture (§6.2).

Perche' esiste questo file: la sottoclasse ereditava da `FonteDati` quattro
metodi su cinque, e quelli della classe base accodano in liste **in memoria**
e ritornano `True`. Il giro avrebbe detto «salvato, registrato» e il giro
successivo non avrebbe trovato ne' baseline ne' eventi: un monitor muto che si
dichiara vivo, e nessun diff possibile al secondo passaggio.

Nessuna rete: `db` e' vero, ma tutte le sue funzioni di I/O sono sostituite.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tests.supporto import carica_modulo

db = carica_modulo("db")
monitoraggio = carica_modulo("monitoraggio")

ADESSO = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)


def _bando(**extra):
    riga = {
        "id": 905315,
        "slug": "psicologia-scolastica-lazio",
        "pubblicato": True,
        "bando_master_id": None,
        "fonte_ufficiale_stato": "trovata",
        "fonte_ufficiale_url": "https://www.lazioeuropa.it/bandi/x",
        "data_scadenza": "2026-12-01",
    }
    riga.update(extra)
    return riga


class CodaDelMonitor(unittest.TestCase):
    def test_nessun_metodo_resta_quello_in_memoria(self):
        for nome in ("candidati", "eventi_recenti", "consumo_oggi",
                     "salva_controllo", "registra_evento", "disponibile"):
            with self.subTest(metodo=nome):
                self.assertIsNot(
                    getattr(monitoraggio.FonteDatiSupabase, nome),
                    getattr(monitoraggio.FonteDati, nome),
                )

    def test_candidati_unisce_bando_e_bando_controllo(self):
        righe = [_bando(), _bando(id=2, stato_bando="chiuso", data_scadenza="2026-09-01")]
        controlli = {905315: {"prossimo_controllo_at": "2026-09-01T00:00:00+00:00",
                              "priorita_controllo": 90},
                     2: {"prossimo_controllo_at": "2027-01-01T00:00:00+00:00"}}
        with patch.object(db, "select_bandi_da_monitorare", lambda **k: righe), \
                patch.object(db, "select_controlli", lambda ids, **k: controlli):
            scelti = monitoraggio.FonteDatiSupabase().candidati(adesso=ADESSO)
        # Il secondo e' chiuso con il ricontrollo nel futuro: la cadenza dei
        # chiusi lo esclude ancora (giro 3, §5: un aperto entrerebbe lo stesso).
        self.assertEqual([r["id"] for r in scelti], [905315])
        self.assertEqual(scelti[0]["priorita_controllo"], 90)

    def test_candidati_portano_la_memoria_del_giro_precedente(self):
        """Le colonne calde devono arrivare nella riga, non solo la coda.

        `select_controlli` e' nato per il resolver e chiedeva sei colonne: la
        coda e i tentativi. Il monitor lo riusava cosi' com'era, quindi ogni
        giro ripartiva da zero — nessun `testo_norm` (nessun «prima», quindi
        ogni controllo in variante G2'), nessun ETag (nessun 304 possibile) e
        soprattutto `controlli_falliti` sempre letto come 0, cioe' la promessa
        «cinque fallimenti e il bando esce dalla coda» che non si avvera mai.
        """
        chieste: list[dict] = []
        coda = {905315: {"prossimo_controllo_at": "2026-09-01T00:00:00+00:00",
                         "priorita_controllo": 90},
                2: {"prossimo_controllo_at": "2027-01-01T00:00:00+00:00"}}
        calde = {905315: {"testo_norm": b"testo di ieri", "etag": "W/\"abc\"",
                          "impronta_contenuto": "sha-vecchia", "controlli_falliti": 4,
                          "volatilita": 0.5}}

        def _controlli(ids, **kwargs):
            chieste.append({"ids": list(ids), "colonne": kwargs.get("colonne")})
            return calde if kwargs.get("colonne") else coda

        # Il secondo e' chiuso con il ricontrollo nel futuro (giro 3, §5).
        chiuso = _bando(id=2, stato_bando="chiuso", data_scadenza="2026-09-01")
        with patch.object(db, "select_bandi_da_monitorare",
                          lambda **k: [_bando(), chiuso]), \
                patch.object(db, "select_controlli", _controlli):
            scelti = monitoraggio.FonteDatiSupabase().candidati(adesso=ADESSO)
        self.assertEqual([r["id"] for r in scelti], [905315])
        riga = scelti[0]
        self.assertEqual(riga["testo_norm"], b"testo di ieri")
        self.assertEqual(riga["impronta_contenuto"], "sha-vecchia")
        self.assertEqual(riga["controlli_falliti"], 4)
        self.assertEqual(riga["priorita_controllo"], 90)     # la coda resta
        # Due letture, non una: la seconda chiede le colonne pesanti sulle
        # sole righe scelte (`testo_norm` e' bytea e su 1 683 righe pesa
        # decine di MB), non su tutta la coda.
        self.assertEqual(len(chieste), 2)
        self.assertIsNone(chieste[0]["colonne"])
        self.assertEqual(chieste[1]["ids"], [905315])
        for colonna in monitoraggio.COLONNE_CONTROLLO:
            self.assertIn(colonna, chieste[1]["colonne"])

    def test_memoria_non_leggibile_non_butta_via_i_candidati(self):
        # Degradare qui vuol dire «giro senza baseline», che e' il
        # comportamento di prima: si dichiara con un allarme e si prosegue.
        def _controlli(ids, **kwargs):
            if kwargs.get("colonne"):
                raise RuntimeError("PostgREST giu'")
            return {905315: {"prossimo_controllo_at": "2026-09-01T00:00:00+00:00"}}

        with patch.object(db, "select_bandi_da_monitorare", lambda **k: [_bando()]), \
                patch.object(db, "select_controlli", _controlli):
            fonte = monitoraggio.FonteDatiSupabase()
            scelti = fonte.candidati(adesso=ADESSO)
        self.assertEqual([r["id"] for r in scelti], [905315])
        self.assertIn(monitoraggio.ALLARME_MEMORIA_ASSENTE, fonte.allarmi)

    def test_senza_bando_controllo_nessun_candidato(self):
        # Se le colonne calde non si leggono, ogni riga sembrerebbe «mai
        # controllata» e l'intero corpus entrerebbe in coda in un giro solo.
        def esplode(ids, **kwargs):
            raise RuntimeError("PostgREST giu'")

        with patch.object(db, "select_bandi_da_monitorare", lambda **k: [_bando()]), \
                patch.object(db, "select_controlli", esplode):
            self.assertEqual(monitoraggio.FonteDatiSupabase().candidati(), [])

    def test_salva_controllo_passa_da_aggiorna_controllo(self):
        visti = {}

        def aggiorna(bando_id, payload, **kwargs):
            visti["id"], visti["payload"] = bando_id, dict(payload)
            return {"status": "ok", "scritto": True}

        with patch.object(db, "aggiorna_controllo", aggiorna):
            scritto = monitoraggio.FonteDatiSupabase().salva_controllo(
                7, {"impronta_contenuto": "abc"})
        self.assertTrue(scritto)
        self.assertEqual(visti, {"id": 7, "payload": {"impronta_contenuto": "abc"}})

    def test_salva_controllo_falso_se_non_ha_scritto(self):
        with patch.object(db, "aggiorna_controllo",
                          lambda *a, **k: {"status": "ok", "scritto": False}):
            self.assertFalse(
                monitoraggio.FonteDatiSupabase().salva_controllo(7, {"etag": "x"}))

    def test_registra_evento_passa_da_registra_evento_esito(self):
        # Il booleano ora e' un involucro dell'esito a tre valori: chi conta il
        # lavoro fatto deve poter distinguere un rifiuto da un duplicato.
        visti = []

        def scrive(riga, **_k):
            visti.append(dict(riga))
            return db.EVENTO_SCRITTO

        with patch.object(db, "registra_evento_esito", scrive):
            esito = monitoraggio.FonteDatiSupabase().registra_evento(
                {"bando_id": 7, "tipo": "proroga"})
        self.assertTrue(esito)
        self.assertEqual(visti, [{"bando_id": 7, "tipo": "proroga"}])

    def test_il_duplicato_non_e_una_scrittura_ma_non_e_un_rifiuto(self):
        fonte = monitoraggio.FonteDatiSupabase()
        with patch.object(db, "registra_evento_esito",
                          lambda riga, **k: db.EVENTO_GIA_PRESENTE):
            # Per il booleano «non ho scritto niente di nuovo» e' corretto...
            self.assertFalse(fonte.registra_evento({"bando_id": 7, "tipo": "proroga"}))
            # ...ma l'esito dice che non e' un rifiuto, e il contatore del giro
            # guarda quello.
            self.assertEqual(
                fonte.registra_evento_esito({"bando_id": 7, "tipo": "proroga"}),
                db.EVENTO_GIA_PRESENTE)

    def test_un_guasto_nel_client_e_un_rifiuto(self):
        def esplode(riga, **_k):
            raise RuntimeError("connessione chiusa")

        with patch.object(db, "registra_evento_esito", esplode):
            fonte = monitoraggio.FonteDatiSupabase()
            self.assertEqual(
                fonte.registra_evento_esito({"bando_id": 7, "tipo": "proroga"}),
                db.EVENTO_RIFIUTATO)

    def test_eventi_recenti_filtra_per_bando_e_per_data(self):
        visti = {}

        def select_eventi(**kwargs):
            visti.update(kwargs)
            return [{"id": 1}]

        with patch.object(db, "select_eventi", select_eventi):
            righe = monitoraggio.FonteDatiSupabase().eventi_recenti(7, giorni=30)
        self.assertEqual(righe, [{"id": 1}])
        self.assertEqual(visti["bando_id"], 7)
        self.assertIsNotNone(visti["dal"])

    def test_consumo_oggi_viene_da_pipeline_run(self):
        with patch.object(db, "consumo_oggi", lambda **k: {"crediti": 12.0}):
            self.assertEqual(
                monitoraggio.FonteDatiSupabase().consumo_oggi(), {"crediti": 12.0})

    def test_un_guasto_non_solleva_mai(self):
        def esplode(*a, **k):
            raise RuntimeError("giu'")

        fonte = monitoraggio.FonteDatiSupabase()
        with patch.object(db, "select_bandi_da_monitorare", esplode), \
                patch.object(db, "aggiorna_controllo", esplode), \
                patch.object(db, "registra_evento", esplode), \
                patch.object(db, "select_eventi", esplode), \
                patch.object(db, "consumo_oggi", esplode):
            self.assertEqual(fonte.candidati(), [])
            self.assertFalse(fonte.salva_controllo(1, {"etag": "x"}))
            self.assertFalse(fonte.registra_evento({"bando_id": 1, "tipo": "proroga"}))
            self.assertEqual(fonte.eventi_recenti(1), [])
            # §18.5: None, non «niente speso».
            self.assertIsNone(fonte.consumo_oggi())


class ConsumoOggi(unittest.TestCase):
    """I valori di `pipeline_run` vivono dentro `contatori` (jsonb): una sola
    lettura dal primo del mese di Roma, voci estratte con `->>` (testo), il
    giorno separato su `avviato_at` (giro 3, §4 e §16)."""

    #: 06:00 UTC del 23/09 = 08:00 a Roma: la giornata parte alle 22:00 UTC del 22.
    OGGI = "2026-09-23T05:00:00.12345+00:00"
    IERI = "2026-09-22T21:59:00+00:00"            # 23:59 del 22 a Roma
    MEZZANOTTE = "2026-09-22T22:00:00+00:00"      # 00:00 del 23 a Roma

    class _Query:
        def __init__(self, dati, registro=None):
            self._dati = dati
            self._registro = registro if registro is not None else []

        def select(self, colonne, *_a, **_k):
            self._registro.append(("select", colonne))
            return self

        def gte(self, colonna, valore):
            self._registro.append(("gte", colonna, valore))
            return self

        def eq(self, colonna, valore):
            self._registro.append(("eq", colonna, valore))
            self._dati = [r for r in self._dati if r.get(colonna) == valore]
            return self

        def order(self, *_a, **_k):
            return self

        def limit(self, quanto):
            self._registro.append(("limit", quanto))
            return self

        def range(self, da, a):
            self._registro.append(("range", da, a))
            return self

        def execute(self):
            return type("R", (), {"data": self._dati})()

    class _Client:
        def __init__(self, dati):
            self._dati = dati
            self.registro: list = []

        def table(self, _nome):
            return ConsumoOggi._Query(self._dati, self.registro)

    class _Strumento:
        def tabella_esiste(self, _nome):
            return True

    def _riga(self, id_, step, quando=None, **voci):
        return {"id": id_, "step": step, "avviato_at": quando or self.OGGI,
                **{k: (None if v is None else str(v)) for k, v in voci.items()}}

    def test_somma_le_voci_dei_giri_di_oggi(self):
        client = self._Client([
            self._riga(1, "monitor", crediti=10, usd=0.5),
            self._riga(2, "monitor", crediti=5, classificazioni=3),
            self._riga(3, "monitor"),
        ])
        somma = db.consumo_oggi(
            adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(somma["crediti"], 15.0)
        self.assertEqual(somma["usd"], 0.5)
        self.assertEqual(somma["classificazioni"], 3.0)
        self.assertEqual(somma["ricerche"], 0.0)

    def test_consumo_passo_oggi_somma_solo_il_passo_dalla_mezzanotte(self):
        # Revisione #146: il tetto della rielaborazione vale sulla giornata.
        client = self._Client([
            self._riga(1, "backfill:rielaborazione", crediti=40, usd=12.5),
            self._riga(2, "backfill:rielaborazione", usd=20.25),
            self._riga(3, "monitor", crediti=99, usd=9),
        ])
        somma = db.consumo_passo_oggi("backfill:rielaborazione", adesso=ADESSO,
                                      client=client, strumento=self._Strumento())
        self.assertEqual(somma, {"crediti": 40.0, "usd": 32.75})
        self.assertIn(("eq", "step", "backfill:rielaborazione"), client.registro)
        self.assertIn(("gte", "avviato_at", "2026-09-23T00:00:00+02:00"), client.registro)
        select = [v[1] for v in client.registro if v[0] == "select"]
        self.assertEqual(select, ["id,crediti:contatori->>crediti,usd:contatori->>usd"])

    def test_consumo_passo_oggi_illeggibile_e_none(self):
        class _Rotto:
            def table(self, _nome):
                raise RuntimeError("rete giu'")

        self.assertIsNone(db.consumo_passo_oggi(
            "backfill:rielaborazione", adesso=ADESSO, client=_Rotto(),
            strumento=self._Strumento()))

    def test_una_sola_lettura_dal_primo_del_mese_con_le_voci_estratte(self):
        client = self._Client([])
        db.consumo_oggi(adesso=ADESSO, client=client, strumento=self._Strumento())
        gte = [v for v in client.registro if v[0] == "gte"]
        self.assertEqual(gte, [("gte", "avviato_at", "2026-09-01T00:00:00+02:00")])
        select = [v[1] for v in client.registro if v[0] == "select"]
        self.assertEqual(len(select), 1)
        for voce in db.VOCI_CONSUMO:
            self.assertIn(f"{voce}:contatori->>{voce}", select[0])
        self.assertIn("avviato_at", select[0])
        self.assertNotIn(",contatori,", f",{select[0]},")

    def test_il_mese_e_il_giorno(self):
        client = self._Client([
            self._riga(1, "seo", "2026-09-02T08:00:00+00:00", usd=1.25, crediti=4),
            self._riga(2, "preprocess", self.IERI, usd=0.75),
            self._riga(3, "preprocess", self.MEZZANOTTE, usd=0.5, crediti=1),
            self._riga(4, "enrich", usd=0.25, ricerche=2),
            self._riga(5, "backfill:rielaborazione", usd=9.0, crediti=900),
            self._riga(6, "pipeline", usd=2.75, crediti=5),
        ])
        somma = db.consumo_oggi(adesso=ADESSO, client=client, strumento=self._Strumento())
        # Giorno: dalla mezzanotte di Roma (inclusa), senza backfill ne' giro.
        self.assertEqual(somma["usd"], 0.75)
        self.assertEqual(somma["crediti"], 1.0)
        self.assertEqual(somma["ricerche"], 2.0)
        # Mese: tutte le righe di regime dal primo del mese.
        self.assertEqual(somma["usd_mese"], 1.25 + 0.75 + 0.5 + 0.25)
        self.assertEqual(somma["crediti_mese"], 4 + 1)

    def test_si_scorre_oltre_le_mille_righe(self):
        pagine = [[self._riga(i, "monitor", usd=0.01) for i in range(1000)],
                  [self._riga(1000 + i, "monitor", usd=0.01) for i in range(5)]]

        class _Query(ConsumoOggi._Query):
            def execute(self):
                return type("R", (), {"data": pagine.pop(0) if pagine else []})()

        class _Client:
            def table(self, _nome):
                return _Query([])

        somma = db.consumo_oggi(adesso=ADESSO, client=_Client(), strumento=self._Strumento())
        self.assertAlmostEqual(somma["usd_mese"], 10.05)
        self.assertAlmostEqual(somma["usd"], 10.05)

    def test_istante_illeggibile_conta_nel_giorno(self):
        # Per un tetto di spesa e' meglio fermarsi prima che spendere due volte.
        riga = self._riga(1, "monitor", usd=0.5)
        riga["avviato_at"] = "boh"
        somma = db.consumo_oggi(adesso=ADESSO, client=self._Client([riga]),
                                strumento=self._Strumento())
        self.assertEqual((somma["usd"], somma["usd_mese"]), (0.5, 0.5))

    def test_valori_non_numerici_valgono_zero(self):
        client = self._Client([self._riga(1, "monitor", usd="molto", crediti="true"),
                               self._riga(2, "monitor", usd="0.5")])
        somma = db.consumo_oggi(adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual((somma["usd"], somma["crediti"]), (0.5, 0.0))

    def test_i_lotti_di_backfill_non_consumano_i_tetti_di_regime(self):
        """Il 25/09/2026 i lotti `backfill:L6` della mattina avevano esaurito il
        tetto giornaliero delle classificazioni e il monitor delle 18:00 si e'
        fermato a «201/30». I lotti hanno tetti propri (M19)."""
        client = self._Client([
            self._riga(1, "monitor", classificazioni=20, usd=0.4),
            self._riga(2, "backfill:L6", classificazioni=171, usd=2.2),
            self._riga(3, "resolver", crediti=7, ricerche=2),
            self._riga(4, "backfill:L5", crediti=900, ricerche=40),
            self._riga(5, None, crediti=1),
        ])
        somma = db.consumo_oggi(
            adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(somma["classificazioni"], 20.0)
        self.assertEqual(somma["usd"], 0.4)
        self.assertEqual(somma["crediti"], 8.0)
        self.assertEqual(somma["ricerche"], 2.0)
        self.assertEqual((somma["crediti_mese"], somma["usd_mese"]), (8.0, 0.4))

    def test_la_riga_del_giro_non_raddoppia_i_crediti(self):
        """La riga `pipeline` risomma i crediti del resolver e dei ricontrolli,
        che hanno gia' la propria riga `resolver`."""
        client = self._Client([
            self._riga(1, "resolver", crediti=40),
            self._riga(2, "resolver", crediti=20),
            self._riga(3, "monitor", crediti=0, classificazioni=4),
            self._riga(4, "pipeline", crediti=60, usd=0),
        ])
        somma = db.consumo_oggi(adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(somma["crediti"], 60.0)
        self.assertEqual(somma["crediti_mese"], 60.0)
        self.assertEqual(somma["classificazioni"], 4.0)

    def test_senza_pipeline_run_nessun_consumo(self):
        class Assente:
            def tabella_esiste(self, _nome):
                return False

        self.assertEqual(db.consumo_oggi(strumento=Assente()), {})

    def test_lettura_fallita_e_none(self):
        # §18.5: un consumo ignoto non e' «niente speso». `{}` resta solo per la
        # tabella che non c'e' ancora.
        class _Client:
            def table(self, _nome):
                raise RuntimeError("503")

        self.assertIsNone(db.consumo_oggi(adesso=ADESSO, client=_Client(),
                                          strumento=self._Strumento()))

    def test_tabella_assente_e_vuoto(self):
        class _SenzaTabella:
            def tabella_esiste(self, _nome):
                return False

        self.assertEqual(db.consumo_oggi(adesso=ADESSO, client=object(),
                                         strumento=_SenzaTabella()), {})


class MisureSalute(unittest.TestCase):
    """`db.misure_salute` legge soltanto, e solo cio' che `salute` giudica."""

    class _Catena:
        """Query finta: registra ogni chiamata e restituisce le righe della tabella."""

        def __init__(self, registro, tabella, righe):
            self._registro, self._tabella, self._righe = registro, tabella, righe
            self.chiamate: list[tuple] = []
            registro.append((tabella, self.chiamate))

        @property
        def not_(self):
            self.chiamate.append(("not_",))
            return self

        def __getattr__(self, nome):
            if nome in ("insert", "update", "upsert", "delete", "rpc"):
                raise AssertionError(f"misure_salute non deve scrivere ({nome})")

            def _passo(*args, **kwargs):
                self.chiamate.append((nome, args, kwargs))
                return self
            return _passo

        def execute(self):
            return type("R", (), {"data": list(self._righe)})()

    class _Client:
        def __init__(self, righe_per_tabella):
            self.registro: list = []
            self._righe = righe_per_tabella

        def table(self, nome):
            return MisureSalute._Catena(self.registro, nome, self._righe.get(nome, []))

    class _Strumento:
        def __init__(self, tabelle=("bando", "pipeline_run", "pipeline_lock", "bando_controllo")):
            self._tabelle = set(tabelle)

        def tabella_esiste(self, nome):
            return nome in self._tabelle

        def ha(self, tabella, _colonna):
            return tabella in self._tabelle

    def test_legge_il_monitor_di_regime_e_non_scrive(self):
        client = self._Client({"pipeline_lock": [{"nome": "pipeline"}]})
        misure = db.misure_salute(adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(set(misure), {"monitor", "pipeline", "mese", "nuovi", "vivi", "falliti",
                                       "lock", "scraped_fermi", "ultime_pipeline",
                                       "ultimi_monitor", "fermi_in_lavorazione",
                                       "ultimo_bando_nuovo_at", "proposte_7g",
                                       "ammessi_non_applicati", "in_attesa_pubblicazione",
                                       "arretrato_in_lavorazione", "vista_ms",
                                       "vista_ms_ruolo", "ultimi_import_indicepa",
                                       "da_verificare", "letture_scadute", "verifica_7g",
                                       "ultime_verifiche", "ultimi_ingressi",
                                       "aperti_senza_scadenza"})
        # I bandi fermi in `scraped`: una lettura su `bando` filtrata per stato.
        letture_bando = [c for tabella, c in client.registro if tabella == "bando"]
        self.assertTrue(any(("eq", ("stato_processing", "scraped"), {}) in c for c in letture_bando))
        self.assertEqual(misure["lock"], [{"nome": "pipeline"}])
        prima = client.registro[0]
        self.assertEqual(prima[0], "pipeline_run")
        self.assertIn(("eq", ("step", "monitor"), {}), prima[1])
        # Solo il monitor di regime: `giro` vuoto vuol dire lancio a mano.
        self.assertIn(("not_",), prima[1])
        self.assertIn(("is_", ("giro", "null"), {}), prima[1])
        # Le classificazioni fallite e il costo del giro: servono all'allarme
        # del credito esaurito.
        selezione = next(c for c in prima[1] if c[0] == "select")[1][0]
        for colonna in ("classificazioni:contatori->>classificazioni",
                        "classificazioni_fallite:contatori->>classificazioni_fallite",
                        "seconde_opinioni_fallite:contatori->>seconde_opinioni_fallite",
                        "usd:contatori->>usd"):
            self.assertIn(colonna, selezione)

    def test_tabelle_assenti_valgono_none(self):
        misure = db.misure_salute(adesso=ADESSO, client=self._Client({}),
                                  strumento=self._Strumento(tabelle=("bando",)))
        self.assertIsNone(misure["monitor"])
        self.assertIsNone(misure["lock"])
        self.assertIsNone(misure["falliti"])

    def test_schema_illeggibile_solleva(self):
        with self.assertRaises(RuntimeError):
            db.misure_salute(adesso=ADESSO, client=self._Client({}),
                             strumento=self._Strumento(tabelle=()))

    def test_la_giornata_e_quella_di_roma(self):
        """Il filtro parte da mezzanotte **italiana**, non da quella UTC.

        Con la data UTC il giro delle 00:00 italiane cadeva nel giorno prima
        (due ore prima in estate): il tetto giornaliero ripartiva da zero a
        mezzanotte di Londra e nella finestra fra i due mezzanotti valeva il
        doppio. E si filtra sull'ISTANTE: `avviato_at` e' un `timestamptz`, e
        una data nuda verrebbe letta come mezzanotte UTC. Dal giro 3 la
        lettura parte dal primo del mese di Roma e la giornata si separa qui.
        """
        righe = [{"id": 1, "step": "monitor", "avviato_at": "2026-09-23T21:30:00+00:00",
                  "usd": "1"},                      # 23:30 del 23 a Roma
                 {"id": 2, "step": "monitor", "avviato_at": "2026-09-23T22:00:00Z",
                  "usd": "2"}]                      # 00:00 del 24 a Roma
        client = ConsumoOggi._Client(righe)

        # 00:30 UTC del 24 = 02:30 italiane del 24: la giornata e' il 24.
        somma = db.consumo_oggi(
            adesso=datetime(2026, 9, 24, 0, 30, tzinfo=timezone.utc),
            client=client, strumento=self._Strumento())
        self.assertEqual(somma["usd"], 2.0)
        self.assertEqual(client.registro[-1][0], "limit")
        self.assertIn(("gte", "avviato_at", "2026-09-01T00:00:00+02:00"), client.registro)

        # 23:30 UTC del 23 = 01:30 italiane del **24**: con la data UTC questo
        # giro finiva nel 23 e non vedeva il consumo dei giri gia' fatti.
        somma = db.consumo_oggi(
            adesso=datetime(2026, 9, 23, 23, 30, tzinfo=timezone.utc),
            client=client, strumento=self._Strumento())
        self.assertEqual(somma["usd"], 2.0)

        # 22:30 UTC del 30/09 = 00:30 dell'01/10 a Roma: il mese e' ottobre.
        client = ConsumoOggi._Client([])
        db.consumo_oggi(adesso=datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc),
                        client=client, strumento=self._Strumento())
        self.assertIn(("gte", "avviato_at", "2026-10-01T00:00:00+02:00"), client.registro)


class CodaSenzaTetto(unittest.TestCase):
    """La coda del monitor si legge tutta (giro 3, §1 e §5: niente lotti).

    Fino al giro 2 `select_bandi_da_monitorare` si fermava a 5 000 righe e il
    monitor alzava l'allarme «coda troncata». Con il tetto sparito sparisce
    anche l'allarme: una coda grande non e' piu' un guasto.
    """

    class _Strumento:
        def tabella_esiste(self, _nome):
            return True

    def test_tetto_e_allarme_non_esistono_piu(self):
        self.assertFalse(hasattr(db, "TETTO_CODA_MONITOR"))
        self.assertFalse(hasattr(db, "ALLARME_CODA_TRONCATA"))

    def test_una_coda_grande_non_alza_allarmi(self):
        fonte = monitoraggio.FonteDatiSupabase(controllo=self._Strumento())
        righe = [_bando(id=i) for i in range(6000)]
        with patch.object(db, "select_bandi_da_monitorare", lambda **k: righe), \
                patch.object(db, "select_controlli", lambda *a, **k: {}):
            fonte.candidati(limite=2, adesso=ADESSO)
        self.assertEqual(fonte.allarmi, [])

    def test_senza_limit_nessun_tetto_alla_lettura(self):
        chiesti: list = []

        def _scorri(costruisci, *, tetto=None, pagina=db.PAGINA_POSTGREST):
            chiesti.append(tetto)
            return []

        class _Strumento:
            def tabella_esiste(self, _nome):
                return True

            def ha(self, _tabella, _colonna):
                return True

        with patch.object(db, "_scorri", _scorri), \
                patch.object(db, "_colonne_disponibili", lambda *a, **k: "id"):
            db.select_bandi_da_monitorare(client=object(), strumento=_Strumento())
            db.select_bandi_da_monitorare(limit=50, client=object(), strumento=_Strumento())
        self.assertEqual(chiesti, [None, 50])


class PubblicatiPerGemelliSenzaTetto(unittest.TestCase):
    """`select_pubblicati_per_gemelli` legge tutti i pubblicati per difetto
    (giro 3, §1 e §11): il tetto di 5 000 e' sparito, `limit` resta per chi lo
    chiede a mano."""

    def test_default_senza_tetto_e_limit_esplicito(self):
        chiesti: list = []

        def _scorri(costruisci, *, tetto=None, pagina=db.PAGINA_POSTGREST):
            chiesti.append(tetto)
            return []

        class _Strumento:
            def tabella_esiste(self, _nome):
                return True

            def ha(self, _tabella, _colonna):
                return True

        with patch.object(db, "_scorri", _scorri), \
                patch.object(db, "_colonne_disponibili", lambda *a, **k: "id"):
            db.select_pubblicati_per_gemelli(client=object(), strumento=_Strumento())
            db.select_pubblicati_per_gemelli(limit=None, client=object(), strumento=_Strumento())
            db.select_pubblicati_per_gemelli(limit=1200, client=object(), strumento=_Strumento())
        self.assertEqual(chiesti, [None, None, 1200])


class SelectSullaFonteUfficiale(unittest.TestCase):
    """Giro 3 (§8): preprocess ed enrich leggono anche le colonne della fonte
    ufficiale, ma solo se lo schema le espone (DB non migrato: niente 42703)."""

    class _Query:
        def __init__(self, registro):
            self.registro = registro

        def select(self, colonne):
            self.registro.append(colonne)
            return self

        def __getattr__(self, _nome):
            return lambda *a, **k: self

        def execute(self):
            return type("R", (), {"data": []})()

    class _Strumento:
        def __init__(self, colonne):
            self._colonne = frozenset(colonne)

        def colonne(self, _tabella):
            return self._colonne

    def _colonne(self, funzione, presenti):
        registro: list[str] = []
        client = type("C", (), {"table": lambda _s, _n: self._Query(registro)})()
        with patch.object(db, "get_supabase", lambda: client):
            funzione(strumento=self._Strumento(presenti))
        return registro[0].split(",")

    def test_con_la_migrazione_01(self):
        presenti = ("id", "fonte_ufficiale_url", "fonte_ufficiale_stato")
        for funzione in (db.select_bandi_scraped, db.select_bandi_to_enrich):
            with self.subTest(funzione=funzione.__name__):
                colonne = self._colonne(funzione, presenti)
                self.assertIn("fonte_ufficiale_url", colonne)
                self.assertIn("fonte_ufficiale_stato", colonne)
                self.assertIn("link_bando", colonne)

    def test_senza_la_migrazione_01(self):
        for funzione in (db.select_bandi_scraped, db.select_bandi_to_enrich):
            with self.subTest(funzione=funzione.__name__):
                colonne = self._colonne(funzione, ("id",))
                self.assertNotIn("fonte_ufficiale_url", colonne)
        self.assertIn("data_scadenza", self._colonne(db.select_bandi_to_enrich, ()))


class _TabelleInMemoria:
    """Un client PostgREST minimo e in memoria: select/eq/in_/is_/not_/order,
    insert, delete, update, range/limit. Registra ogni operazione di scrittura."""

    def __init__(self, tabelle, *, insert_fallisce=False, delete_fallisce=False):
        self.tabelle = {nome: [dict(r) for r in righe] for nome, righe in tabelle.items()}
        self.operazioni: list[tuple] = []
        self.insert_fallisce = insert_fallisce
        self.delete_fallisce = delete_fallisce

    def table(self, nome):
        return _Interrogazione(self, nome)


class _Interrogazione:
    def __init__(self, client, nome):
        self.client, self.nome = client, nome
        self.filtri: list = []
        self.azione = ("select", None)
        self.negazione = False
        self.da, self.a = 0, None

    @property
    def not_(self):
        self.negazione = True
        return self

    def select(self, _colonne):
        return self

    def _filtro(self, f):
        if self.negazione:
            self.negazione = False
            self.filtri.append(lambda r, f=f: not f(r))
        else:
            self.filtri.append(f)
        return self

    def eq(self, c, v):
        return self._filtro(lambda r: r.get(c) == v)

    def in_(self, c, vs):
        return self._filtro(lambda r: r.get(c) in vs)

    def is_(self, c, v):
        return self._filtro(lambda r: r.get(c) is None)

    def order(self, *_a, **_k):
        return self

    def range(self, da, a):
        self.da, self.a = da, a
        return self

    def limit(self, quanto):
        self.a = self.da + quanto - 1
        return self

    def offset(self, salto):
        self.da = salto
        return self

    def insert(self, righe):
        self.azione = ("insert", righe)
        return self

    def delete(self):
        self.azione = ("delete", None)
        return self

    def update(self, payload):
        self.azione = ("update", payload)
        return self

    def execute(self):
        righe = self.client.tabelle.setdefault(self.nome, [])
        scelte = [r for r in righe if all(f(r) for f in self.filtri)]
        tipo, dati = self.azione
        if tipo == "insert":
            if self.client.insert_fallisce:
                raise RuntimeError("insert rifiutato")
            self.client.operazioni.append(("insert", self.nome, [dict(r) for r in dati]))
            righe.extend(dict(r) for r in dati)
            return type("R", (), {"data": dati})()
        if tipo == "delete":
            if self.client.delete_fallisce:
                raise RuntimeError("delete rifiutato")
            self.client.operazioni.append(("delete", self.nome, [dict(r) for r in scelte]))
            self.client.tabelle[self.nome] = [r for r in righe if r not in scelte]
            return type("R", (), {"data": scelte})()
        if tipo == "update":
            self.client.operazioni.append(("update", self.nome, dict(dati)))
            for r in scelte:
                r.update(dati)
            return type("R", (), {"data": scelte})()
        fine = len(scelte) if self.a is None else self.a + 1
        return type("R", (), {"data": [dict(r) for r in scelte[self.da:fine]]})()


class _SchemaPieno:
    def tabella_esiste(self, _nome):
        return True

    def ha(self, _tabella, _colonna):
        return True

    def colonne(self, _tabella):
        return frozenset()

    def colonne_mancanti(self, _tabella, _payload):
        return ()


class CatalogoInMemoria(unittest.TestCase):
    """§19.4: un catalogo con una tabella fallita non resta in memoria."""

    def setUp(self):
        db.azzera_catalogo()
        self.addCleanup(db.azzera_catalogo)

    def _client(self, guaste):
        letture: list[str] = []

        class _Query:
            def __init__(self, tabella):
                self.tabella = tabella

            def select(self, *_a):
                return self

            def order(self, *_a, **_k):
                return self

            def execute(self):
                letture.append(self.tabella)
                if self.tabella in guaste:
                    raise RuntimeError("503")
                return type("R", (), {"data": [{"id": 1, "nome": self.tabella}]})()

        class _Client:
            def table(self, tabella):
                return _Query(tabella)

        return _Client(), letture

    def test_tabella_fallita_non_resta_in_cache(self):
        guaste = {"regioni"}
        client, letture = self._client(guaste)
        with patch.object(db, "get_supabase", lambda: client):
            primo = db.load_catalogo()
            self.assertEqual(primo["regioni"], [])
            self.assertEqual(primo["settori"], [{"id": 1, "nome": "settori"}])
            guaste.clear()                                    # la rete torna
            secondo = db.load_catalogo()
            self.assertEqual(secondo["regioni"], [{"id": 1, "nome": "regioni"}])
            letti = len(letture)
            terzo = db.load_catalogo()
        self.assertEqual(letti, 14, "rilette tutte e 7 le tabelle")
        self.assertEqual(len(letture), letti, "il catalogo completo resta in memoria")
        self.assertIs(terzo, secondo)


class RielaborazioneDb(unittest.TestCase):
    """Le funzioni di `db` della rielaborazione (giro 3, §9)."""

    def test_allinea_inserisce_poi_toglie(self):
        client = _TabelleInMemoria({"bando_regioni": [
            {"bando_id": 7, "regione_id": 12}, {"bando_id": 7, "regione_id": 13},
            {"bando_id": 8, "regione_id": 12}]})
        esito = db.allinea_junction(7, "regioni", [11, 13], client=client)
        self.assertEqual(esito, {"cambiato": True, "prima": [12, 13], "dopo": [11, 13],
                                 "inseriti": [11], "tolti": [12]})
        self.assertEqual([o[0] for o in client.operazioni], ["insert", "delete"])
        self.assertEqual(sorted((r["bando_id"], r["regione_id"])
                                for r in client.tabelle["bando_regioni"]),
                         [(7, 11), (7, 13), (8, 12)])

    def test_mai_svuotare_e_niente_se_uguale(self):
        client = _TabelleInMemoria({"bando_regioni": [{"bando_id": 7, "regione_id": 12}]})
        self.assertFalse(db.allinea_junction(7, "regioni", [], client=client)["cambiato"])
        self.assertFalse(db.allinea_junction(7, "regioni", [12], client=client)["cambiato"])
        self.assertEqual(client.operazioni, [])
        with self.assertRaises(ValueError):
            db.allinea_junction(7, "province", [1], client=client)

    def test_insert_fallito_non_toglie_niente(self):
        client = _TabelleInMemoria({"bando_regioni": [{"bando_id": 7, "regione_id": 12}]},
                                   insert_fallisce=True)
        esito = db.allinea_junction(7, "regioni", [11], client=client)
        self.assertFalse(esito["cambiato"])
        self.assertEqual(client.tabelle["bando_regioni"], [{"bando_id": 7, "regione_id": 12}])

    def test_delete_fallito_a_meta_restituisce_il_cambio_parziale(self):
        # Revisione #146 (P2): l'INSERT e' riuscito, quindi il cambio c'e'
        # stato e il chiamante lo deve registrare per poterlo togliere con SQL.
        client = _TabelleInMemoria({"bando_regioni": [{"bando_id": 7, "regione_id": 12}]},
                                   delete_fallisce=True)
        esito = db.allinea_junction(7, "regioni", [11], client=client)
        self.assertTrue(esito["cambiato"])
        self.assertTrue(esito["parziale"])
        self.assertEqual((esito["prima"], esito["dopo"], esito["inseriti"], esito["tolti"]),
                         ([12], [11, 12], [11], []))
        self.assertIn("delete rifiutato", esito["errore"])
        self.assertEqual(sorted(r["regione_id"] for r in client.tabelle["bando_regioni"]),
                         [11, 12], "piu' voci, mai meno")

    def test_segna_cambiamento_pubblico_solo_la_colonna(self):
        # §20.1: un UPDATE della sola `ultimo_cambiamento_at`.
        from datetime import datetime, timezone
        client = _TabelleInMemoria({"bando": [{"id": 7, "titolo": "x"}]})
        strumento = db.Controllo(lambda: {}, client_factory=lambda: client)
        with patch.object(strumento, "colonne_mancanti", lambda *a: ()):
            esito = db.segna_cambiamento_pubblico(
                7, adesso=datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc), strumento=strumento)
        self.assertTrue(esito["scritto"])
        self.assertEqual(client.operazioni,
                         [("update", "bando", {"ultimo_cambiamento_at": "2026-10-01T18:00:00+00:00"})])
        with self.assertRaises(db.PayloadBandoVietato):
            db.segna_cambiamento_pubblico(7, payload={"ultimo_cambiamento_at": "x", "titolo": "y"},
                                          strumento=strumento)

    def test_le_fk_e_basta(self):
        with self.assertRaises(db.PayloadBandoVietato):
            db.aggiorna_fk_bando(7, {"tipologia_bando_id": 2, "stato_bando": "chiuso"})
        scritte: list = []
        strumento = type("S", (), {"aggiorna": lambda _s, t, i, p: scritte.append((t, i, p))
                                   or {"scritto": True}})()
        db.aggiorna_fk_bando(7, {"programma_id": 3}, strumento=strumento)
        self.assertEqual(scritte, [("bando", 7, {"programma_id": 3})])

    def test_azzera_rielaborazione(self):
        client = _TabelleInMemoria({"bando": [{"id": 7, "fonte_ufficiale_link_id": 70}]})
        scritte: list = []

        class _Strumento(_SchemaPieno):
            def aggiorna(self, tabella, id_riga, payload):
                scritte.append((tabella, id_riga, payload))
                return {"scritto": True}

        esito = db.azzera_rielaborazione(7, client=client, strumento=_Strumento())
        self.assertTrue(esito["scritto"])
        self.assertEqual(scritte, [("bando_link", 70, {"impronta_contenuto": None})])
        self.assertFalse(db.azzera_rielaborazione(99, client=client, strumento=_Strumento())["scritto"])

    def test_select_da_rielaborare_filtra_il_marcatore(self):
        bando = [{"id": i, "pubblicato": True, "fonte_ufficiale_stato": "trovata",
                  "fonte_ufficiale_link_id": i * 10, "bando_master_id": None} for i in (1, 2, 3)]
        bando.append({"id": 4, "pubblicato": True, "fonte_ufficiale_stato": "trovata",
                      "fonte_ufficiale_link_id": 40, "bando_master_id": 1})
        link = [{"id": 10, "impronta_contenuto": None},
                {"id": 20, "impronta_contenuto": "rielab:v1:2026-10-01:abc"},
                {"id": 30, "impronta_contenuto": "sha-del-monitor"}]
        client = _TabelleInMemoria({"bando": bando, "bando_link": link})
        with patch.object(db, "_colonne_disponibili", lambda *a, **k: "id"):
            scelti = db.select_da_rielaborare(client=client, strumento=_SchemaPieno())
            per_id = db.select_da_rielaborare(ids=[2], client=client, strumento=_SchemaPieno())
        self.assertEqual([r["id"] for r in scelti], [1, 3], "fuori il marcato e il fuso")
        self.assertEqual([r["id"] for r in per_id], [2], "con --ids il marcatore non filtra")
        self.assertEqual(per_id[0]["_marcatore"], "rielab:v1:2026-10-01:abc")

    def test_select_da_rielaborare_tiene_gli_incompleti(self):
        # P2 di #160: `rielab:v1:incompleto:<n>` resta in coda fino all'abbandono.
        bando = [{"id": i, "pubblicato": True, "fonte_ufficiale_stato": "trovata",
                  "fonte_ufficiale_link_id": i * 10, "bando_master_id": None} for i in (1, 2)]
        link = [{"id": 10, "impronta_contenuto": "rielab:v1:incompleto:2"},
                {"id": 20, "impronta_contenuto": "rielab:v1:2026-10-01:abc"}]
        client = _TabelleInMemoria({"bando": bando, "bando_link": link})
        with patch.object(db, "_colonne_disponibili", lambda *a, **k: "id"):
            scelti = db.select_da_rielaborare(client=client, strumento=_SchemaPieno())
        self.assertEqual([(r["id"], r["_marcatore"]) for r in scelti],
                         [(1, "rielab:v1:incompleto:2")])

    def test_da_rielaborare(self):
        self.assertTrue(db.da_rielaborare(None))
        self.assertTrue(db.da_rielaborare("sha-del-monitor"))
        self.assertTrue(db.da_rielaborare("rielab:v1:incompleto:1"))
        self.assertFalse(db.da_rielaborare("rielab:v1:2026-10-01:abc"))

    def test_select_junction(self):
        client = _TabelleInMemoria({
            "bando_regioni": [{"bando_id": 7, "regione_id": 12}, {"bando_id": 7, "regione_id": 11}],
            "bando_settori": [{"bando_id": 8, "settore_id": 5}],
            "bando_beneficiari": [], "bando_codici_ateco": []})
        esito = db.select_junction([7, 8], client=client)
        self.assertEqual(esito[7]["regioni"], [11, 12])
        self.assertEqual(esito[8], {"beneficiari": [], "codici_ateco": [], "regioni": [],
                                    "settori": [5]})

    def test_registra_evento_rpc(self):
        chiamate: list = []

        class _Rpc:
            def __init__(self, dati):
                self.dati = dati

            def execute(self):
                return type("R", (), {"data": self.dati})()

        client = type("C", (), {"rpc": lambda _s, nome, par: chiamate.append((nome, par))
                                or _Rpc([{"id": 1, "applicato": True}])})()
        strumento = type("S", (), {"rpc_disponibile": lambda _s, _n: True})()
        esito = db.registra_evento_rpc({"p_bando_id": 7}, client=client, strumento=strumento)
        self.assertEqual(esito, {"id": 1, "applicato": True})
        self.assertEqual(chiamate[0][0], "bando_registra_evento")
        assente = type("S", (), {"rpc_disponibile": lambda _s, _n: False})()
        self.assertIsNone(db.registra_evento_rpc({"p_bando_id": 7}, client=client, strumento=assente))


class CapacitaSospensioni(unittest.TestCase):
    """`db.capacita_sospensioni`: il marcatore della 14. Nel dubbio, falso."""

    def setUp(self):
        self.chiamate: list = []

    def _client(self, dati=None, errore=None):
        chiamate = self.chiamate

        class _Rpc:
            def __init__(self, nome, parametri):
                chiamate.append((nome, parametri))

            def execute(self):
                if errore is not None:
                    raise errore
                return type("R", (), {"data": dati})()

        return type("C", (), {"rpc": staticmethod(lambda nome, parametri: _Rpc(nome, parametri))})()

    @staticmethod
    def _strumento(disponibile=True):
        return type("S", (), {"rpc_disponibile": staticmethod(lambda _nome: disponibile)})()

    def test_rpc_assente_nessuna_chiamata(self):
        self.assertFalse(db.capacita_sospensioni(
            client=self._client(True), strumento=self._strumento(False)))
        self.assertEqual(self.chiamate, [])

    def test_vero_letterale(self):
        for dati in (True, [True], {"bando_capacita_sospensioni": True},
                     [{"bando_capacita_sospensioni": True}]):
            with self.subTest(dati=dati):
                self.assertTrue(db.capacita_sospensioni(
                    client=self._client(dati), strumento=self._strumento()))
        self.assertEqual(self.chiamate[0], ("bando_capacita_sospensioni", {}))

    def test_solo_true_vale_vero(self):
        for dati in (None, False, [], [False], "true", 1, [True, True], {},
                     {"bando_capacita_sospensioni": "true"},
                     {"altro": True}, [{"bando_capacita_sospensioni": "true"}]):
            with self.subTest(dati=dati):
                self.assertFalse(db.capacita_sospensioni(
                    client=self._client(dati), strumento=self._strumento()))

    def test_un_errore_vale_assente(self):
        self.assertFalse(db.capacita_sospensioni(
            client=self._client(errore=RuntimeError("503")), strumento=self._strumento()))


class VistaMs(unittest.TestCase):
    """B30 (giro 3, §10): la misura di `vista_ms` non chiede le tre colonne che
    la migrazione 07 toglie dalla vista, altrimenti fallirebbe per sempre."""

    def test_niente_link_ne_allegati(self):
        colonne = db.COLONNE_VISTA_MS.split(",")
        for tolta in ("link_bando", "link_candidatura", "allegati"):
            with self.subTest(colonna=tolta):
                self.assertNotIn(tolta, colonne)
        self.assertEqual(colonne, ["id", "slug", "titolo", "stato_effettivo", "data_scadenza"])


class TestSelectEventiPerId(unittest.TestCase):
    """`applica-eventi --ids`: il filtro esatto che gli allarmi del monitor
    scrivono (revisione avversaria del 30/09/2026)."""

    def test_gli_id_diventano_un_filtro_in(self):
        from tests.test_db_backfill import SCHEMA_DOPO, _Query, _strumento
        query = _Query()
        db.select_eventi(client=query, strumento=_strumento(SCHEMA_DOPO),
                         ids=(12, 13), applicato=False, verificato=True)
        self.assertIn(("in_", "id", [12, 13]), query.filtri)
        self.assertIn(("eq", "verificato", True), query.filtri)

    def test_senza_id_nessun_filtro_per_id(self):
        from tests.test_db_backfill import SCHEMA_DOPO, _Query, _strumento
        query = _Query()
        db.select_eventi(client=query, strumento=_strumento(SCHEMA_DOPO), tipi=("faq",))
        self.assertFalse(any(f[:2] == ("in_", "id") for f in query.filtri))


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
