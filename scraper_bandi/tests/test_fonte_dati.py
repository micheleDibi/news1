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
        righe = [_bando(), _bando(id=2)]
        controlli = {905315: {"prossimo_controllo_at": "2026-09-01T00:00:00+00:00",
                              "priorita_controllo": 90},
                     2: {"prossimo_controllo_at": "2027-01-01T00:00:00+00:00"}}
        with patch.object(db, "select_bandi_da_monitorare", lambda **k: righe), \
                patch.object(db, "select_controlli", lambda ids, **k: controlli):
            scelti = monitoraggio.FonteDatiSupabase().candidati(adesso=ADESSO)
        # Il secondo ha il ricontrollo nel futuro: `selezionabile` lo esclude.
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

        with patch.object(db, "select_bandi_da_monitorare",
                          lambda **k: [_bando(), _bando(id=2)]), \
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
            self.assertEqual(fonte.consumo_oggi(), {})


class ConsumoOggi(unittest.TestCase):
    """I cinque valori di `pipeline_run` vivono dentro `contatori` (jsonb)."""

    class _Query:
        def __init__(self, dati):
            self._dati = dati

        def select(self, *_a, **_k):
            return self

        def gte(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def execute(self):
            return type("R", (), {"data": self._dati})()

    class _Client:
        def __init__(self, dati):
            self._dati = dati

        def table(self, _nome):
            return ConsumoOggi._Query(self._dati)

    class _Strumento:
        def tabella_esiste(self, _nome):
            return True

    def test_somma_le_voci_dei_giri_di_oggi(self):
        client = self._Client([
            {"id": 1, "step": "monitor", "contatori": {"crediti": 10, "usd": 0.5}},
            {"id": 2, "step": "monitor", "contatori": {"crediti": 5, "classificazioni": 3}},
            {"id": 3, "step": "monitor", "contatori": None},
        ])
        somma = db.consumo_oggi(
            adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(somma["crediti"], 15.0)
        self.assertEqual(somma["usd"], 0.5)
        self.assertEqual(somma["classificazioni"], 3.0)
        self.assertEqual(somma["ricerche"], 0.0)

    def test_i_lotti_di_backfill_non_consumano_i_tetti_di_regime(self):
        """Il 25/09/2026 i lotti `backfill:L6` della mattina avevano esaurito il
        tetto giornaliero delle classificazioni e il monitor delle 18:00 si e'
        fermato a «201/30». I lotti hanno tetti propri (M19)."""
        client = self._Client([
            {"id": 1, "step": "monitor", "contatori": {"classificazioni": 20, "usd": 0.4}},
            {"id": 2, "step": "backfill:L6", "contatori": {"classificazioni": 171, "usd": 2.2}},
            {"id": 3, "step": "resolver", "contatori": {"crediti": 7, "ricerche": 2}},
            {"id": 4, "step": "backfill:L5", "contatori": {"crediti": 900, "ricerche": 40}},
            {"id": 5, "step": None, "contatori": {"crediti": 1}},
        ])
        somma = db.consumo_oggi(
            adesso=ADESSO, client=client, strumento=self._Strumento())
        self.assertEqual(somma["classificazioni"], 20.0)
        self.assertEqual(somma["usd"], 0.4)
        self.assertEqual(somma["crediti"], 8.0)
        self.assertEqual(somma["ricerche"], 2.0)

    def test_senza_pipeline_run_nessun_consumo(self):
        class Assente:
            def tabella_esiste(self, _nome):
                return False

        self.assertEqual(db.consumo_oggi(strumento=Assente()), {})

    def test_la_giornata_e_quella_di_roma(self):
        """Il filtro parte da mezzanotte **italiana**, non da quella UTC.

        Con la data UTC il giro delle 00:00 italiane cadeva nel giorno prima
        (due ore prima in estate): il tetto giornaliero ripartiva da zero a
        mezzanotte di Londra e nella finestra fra i due mezzanotti valeva il
        doppio. E si filtra sull'ISTANTE: `avviato_at` e' un `timestamptz`, e
        una data nuda verrebbe letta come mezzanotte UTC.
        """
        chiesti = []

        class _Query(ConsumoOggi._Query):
            def gte(self, colonna, valore):
                chiesti.append((colonna, valore))
                return self

        class _Client:
            def table(self, _nome):
                return _Query([])

        # 00:30 UTC del 24 = 02:30 italiane del 24: la giornata e' il 24.
        db.consumo_oggi(
            adesso=datetime(2026, 9, 24, 0, 30, tzinfo=timezone.utc),
            client=_Client(), strumento=self._Strumento())
        self.assertEqual(chiesti[-1][0], "avviato_at")
        self.assertEqual(chiesti[-1][1], "2026-09-24T00:00:00+02:00")

        # 23:30 UTC del 23 = 01:30 italiane del **24**: con la data UTC questo
        # giro finiva nel 23 e non vedeva il consumo dei giri gia' fatti.
        db.consumo_oggi(
            adesso=datetime(2026, 9, 23, 23, 30, tzinfo=timezone.utc),
            client=_Client(), strumento=self._Strumento())
        self.assertEqual(chiesti[-1][1], "2026-09-24T00:00:00+02:00")


class CodaTroncata(unittest.TestCase):
    """Il tetto di lettura di `select_bandi_da_monitorare` (§6.2, residuo b).

    2 104 pubblicati misurati contro un tetto di 5 000: il giorno in cui il
    corpus lo supera la selezione per priorita' ordina una fetta del corpus, e
    non deve poter succedere in silenzio.
    """

    class _Strumento:
        def tabella_esiste(self, _nome):
            return True

    def _fonte(self, quante: int):
        fonte = monitoraggio.FonteDatiSupabase(controllo=self._Strumento())
        righe = [_bando(id=i) for i in range(quante)]
        with patch.object(db, "TETTO_CODA_MONITOR", 3), \
                patch.object(db, "select_bandi_da_monitorare", lambda **k: righe), \
                patch.object(db, "select_controlli", lambda *a, **k: {}):
            fonte.candidati(limite=2, adesso=ADESSO)
        return fonte

    def test_coda_piena_alza_un_allarme(self):
        self.assertEqual(self._fonte(3).allarmi, [db.ALLARME_CODA_TRONCATA])

    def test_coda_non_piena_non_alza_niente(self):
        self.assertEqual(self._fonte(2).allarmi, [])

    def test_l_allarme_non_si_trascina_al_giro_dopo(self):
        fonte = self._fonte(3)
        with patch.object(db, "TETTO_CODA_MONITOR", 3), \
                patch.object(db, "select_bandi_da_monitorare", lambda **k: []), \
                patch.object(db, "select_controlli", lambda *a, **k: {}):
            fonte.candidati(limite=2, adesso=ADESSO)
        self.assertEqual(fonte.allarmi, [])


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
