# -*- coding: utf-8 -*-
"""`seo-rigenera` (contratto di ottobre, §7, con l'aggiunta del 30/09).

Tre modi, e per ognuno cio' che promette:

  * `--solo-controllo` — niente modello, lock, scritture ne' `pipeline_run`;
  * prova (`--dry-run`, o nessun flag) — chiama il modello e SPENDE, stampa
    vecchio, nuovo e costo e salva le proposte in un file JSON; non scrive sul
    DB, non prende lock e non scrive `pipeline_run`;
  * `--attivo --proposte FILE` — scrive le proposte del file SENZA modello,
    sotto il lock `bandi_pipeline` (proprietario `seo-rigenera:cli`), con una
    riga `pipeline_run` fuori dai consumi di regime. Salta i bandi non piu'
    pubblicati, quelli cambiati dopo la prova e quelli ancora segnalati.

Il modello, il lock e il DB sono finti; i file delle proposte stanno in una
cartella temporanea, e ogni test fallisce se il comando prova a scrivere nel
percorso predefinito della home.
"""
import asyncio
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tests.supporto import ALIAS, carica_modulo
from tests.test_seo_affermazioni import CASI_REALI

runner = carica_modulo("bando_seo_runner")
blocco = carica_modulo("blocco")
bilancio = carica_modulo("bilancio")
db = carica_modulo("db")
cli = carica_modulo("__main__")

LISTINO = {"claude-opus-4-7": (5.0, 25.0)}


def _contenuto(frase):
    return {"sections": [
        {"type": "h2", "text": "Chi può candidarsi"},
        {"type": "paragraph", "segments": [{"kind": "text", "text": frase}]},
    ]}


def riga(bando_id, **campi):
    """Una riga come la legge `db.select_bandi_per_rigenera_seo`."""
    base = {
        "id": bando_id, "slug": f"bando-{bando_id}", "stato_processing": "completed",
        "pubblicato": True, "bando_master_id": None,
        "titolo_raw": "Bando per imprese", "descrizione_raw": None, "raw_data": {},
        "descrizione_breve": "Contributi a fondo perduto per le imprese.",
        "contenuto": _contenuto("imprese in forma singola o associata"),
    }
    base.update(campi)
    return base


class LockFinto:
    def __init__(self, esito=blocco.ACQUISITO):
        self.esito = esito
        self.acquisiti = []
        self.rilasciati = []

    def acquisisci(self, nome, proprietario, ttl_s):
        self.acquisiti.append((nome, proprietario, ttl_s))
        return blocco.Blocco(nome, proprietario, self.esito)

    def rilascia(self, preso):
        self.rilasciati.append(preso)
        return True


#: Una descrizione nuova entro 180-320 caratteri.
DESCRIZIONE_NUOVA = ("Contributi a fondo perduto per le imprese del territorio: il bando finanzia "
                     "progetti di innovazione e digitalizzazione con una dotazione complessiva "
                     "indicata nell'avviso. Domande entro il 30 ottobre 2026.")


URL_BANDO = "https://ente.it/bando"


def generatore_finto(contenuto="Possono partecipare le imprese.",
                     descrizione=DESCRIZIONE_NUOVA,
                     payload_nullo=False,
                     contenuto_oggetto=None,
                     link_ammessi=None):
    chiamate = []
    opzioni = []

    async def genera(b, input_ctx, *, contatori=None, descrizione_facoltativa=False):
        chiamate.append(b["id"])
        opzioni.append(descrizione_facoltativa)
        if contatori is not None:
            bilancio.registra_chiamata(
                contatori, "claude-opus-4-7",
                {"input_tokens": 10_000, "output_tokens": 3_000}, LISTINO,
            )
        if payload_nullo:
            return runner.Generazione(None, "md", True)
        payload = {"contenuto": contenuto_oggetto or _contenuto(contenuto),
                   "descrizione_breve": descrizione,
                   "slug": "non-deve-arrivare-al-db", "titolo": "Titolo nuovo"}
        return runner.Generazione(payload, "PAGINA UFFICIALE: https://ente.it\n\nBando per imprese",
                                  True, link_ammessi=link_ammessi)

    genera.chiamate = chiamate
    genera.opzioni = opzioni
    return genera


async def _mai(*args, **kwargs):
    raise AssertionError("l'attivo e il solo controllo non devono chiamare il modello")


def _contesto(b, _catalogo):
    return {"id": b["id"], "beneficiari": ["Imprese"], "titolo_raw": b.get("titolo_raw")}


class ConCartella(unittest.TestCase):
    """Cartella temporanea per i file, e la home vietata."""

    def setUp(self):
        self._cartella = tempfile.TemporaryDirectory()
        self.cartella = Path(self._cartella.name)
        vieta_home = mock.patch.object(
            runner, "_percorso_predefinito",
            side_effect=AssertionError("un test non deve scrivere nella home"),
        )
        vieta_home.start()
        self.addCleanup(vieta_home.stop)
        self.addCleanup(self._cartella.cleanup)

    def esegui(self, ids, righe, **opzioni):
        righe_stampate = []
        parametri = dict(righe=righe, catalogo={}, contesto=_contesto,
                         stampa=righe_stampate.append)
        if not opzioni.get("attivo") and not opzioni.get("solo_controllo"):
            parametri["uscita"] = self.cartella / "proposte.json"
        parametri.update(opzioni)
        esito = asyncio.run(runner.run_seo_rigenera(ids, **parametri))
        return esito, "\n".join(righe_stampate)

    def prova(self, ids, righe, **opzioni):
        """Una prova completa: ritorna (esito, stampa, dati del file)."""
        esito, testo = self.esegui(ids, righe, **opzioni)
        dati = json.loads(Path(esito["uscita"]).read_text(encoding="utf-8"))
        return esito, testo, dati

    def attivo(self, proposte, righe, **opzioni):
        ids = opzioni.pop("ids", [])
        parametri = dict(attivo=True, proposte=proposte, generatore=_mai,
                         scrivi=mock.MagicMock(return_value=True), lock=LockFinto(),
                         registra_run=mock.MagicMock())
        parametri.update(opzioni)
        esito, testo = self.esegui(ids, righe, **parametri)
        return esito, testo, parametri


class TestProva(ConCartella):
    def test_la_prova_stampa_vecchio_nuovo_e_costo_senza_scrivere(self):
        lock, scrivi, registra = LockFinto(), mock.MagicMock(), mock.MagicMock()
        generatore = generatore_finto()
        esito, testo, _dati = self.prova([5], [riga(5)], generatore=generatore, scrivi=scrivi,
                                         lock=lock, registra_run=registra)
        self.assertEqual(esito["modo"], runner.MODO_PROVA)
        self.assertEqual(generatore.chiamate, [5])
        scrivi.assert_not_called()
        registra.assert_not_called()
        self.assertEqual(lock.acquisiti, [])
        self.assertIn("contenuto, vecchio", testo)
        self.assertIn("imprese in forma singola o associata", testo)
        self.assertIn("Possono partecipare le imprese.", testo)
        self.assertIn("costo della chiamata: 0.1250 USD", testo)
        self.assertIn("--attivo --proposte", testo)
        self.assertAlmostEqual(esito["usd"], 0.125)
        self.assertEqual(esito["segnalati"], 1)

    def test_la_prova_salva_le_proposte(self):
        vecchia = riga(5)
        esito, _t, dati = self.prova([5], [vecchia], generatore=generatore_finto())
        self.assertEqual(dati["versione"], runner.VERSIONE_PROPOSTE)
        self.assertEqual(dati["ids"], [5])
        self.assertAlmostEqual(dati["costo_usd"], 0.125)
        (voce,) = dati["proposte"]
        self.assertEqual(voce["id"], 5)
        self.assertEqual(voce["sha256_contenuto"], runner.impronta_testo(vecchia["contenuto"]))
        self.assertEqual(voce["contenuto"], _contenuto("Possono partecipare le imprese."))
        self.assertIsNone(voce["descrizione_breve"])          # la vecchia era pulita
        self.assertEqual(voce["affermazioni_vecchie"],
                         [["forma singola o associata", "forma singola o associata"]])
        self.assertEqual(voce["affermazioni_nuove"], [])
        self.assertAlmostEqual(voce["costo_usd"], 0.125)
        self.assertEqual(esito["proposte_salvate"], 1)
        self.assertNotIn("titolo", voce)                       # solo testi, mai il titolo

    def test_la_descrizione_si_propone_se_afferma_le_stesse_forme(self):
        vecchia = riga(5, descrizione_breve="Per le imprese, in forma singola o associata.")
        _e, _t, dati = self.prova([5], [vecchia], generatore=generatore_finto())
        voce = dati["proposte"][0]
        self.assertEqual(voce["descrizione_breve"], DESCRIZIONE_NUOVA)
        self.assertEqual(voce["sha256_descrizione_breve"],
                         runner.impronta_testo(vecchia["descrizione_breve"]))

    def test_la_prova_chiede_la_descrizione_facoltativa(self):
        generatore = generatore_finto()
        self.prova([5], [riga(5)], generatore=generatore)
        self.assertEqual(generatore.opzioni, [True])

    def test_descrizione_fuori_misura_la_proposta_resta_senza(self):
        # Revisione #25, P2: la lunghezza si giudica solo se la descrizione si
        # riscrive; fuori misura, la proposta si salva senza e resta la vecchia.
        vecchia = riga(5, descrizione_breve="Per le imprese, in forma singola o associata.")
        esito, testo, dati = self.prova(
            [5], [vecchia], generatore=generatore_finto(descrizione="Troppo corta."))
        voce = dati["proposte"][0]
        self.assertIsNone(voce["descrizione_breve"])
        self.assertEqual(voce["nota_descrizione"],
                         "descrizione nuova di 13 caratteri, fuori da 180-320: resta la vecchia")
        self.assertEqual(esito["descrizioni_fuori_misura"], 1)
        self.assertEqual(esito["proposte_salvate"], 1)
        self.assertIn("resta la vecchia", testo)

    def test_descrizione_non_riscritta_non_si_giudica(self):
        esito, _t, dati = self.prova(
            [5], [riga(5)], generatore=generatore_finto(descrizione="Troppo corta."))
        self.assertIsNone(dati["proposte"][0]["descrizione_breve"])
        self.assertNotIn("nota_descrizione", dati["proposte"][0])
        self.assertEqual(esito["descrizioni_fuori_misura"], 0)

    def test_testo_nuovo_ancora_segnalato_salvato_ma_marcato(self):
        esito, testo, dati = self.prova(
            [5], [riga(5)], generatore=generatore_finto(contenuto="Anche reti di imprese."))
        self.assertEqual(esito["ancora_non_sostenuti"], 1)
        self.assertEqual(dati["proposte"][0]["affermazioni_nuove"],
                         [["reti di imprese", "reti di imprese"]])
        self.assertIn("nuovo: reti di imprese", testo)

    def test_seo_fallita_niente_proposta(self):
        esito, _t, dati = self.prova([5], [riga(5)], generatore=generatore_finto(payload_nullo=True))
        self.assertEqual(esito["falliti"], 1)
        self.assertEqual(dati["proposte"], [])

    def test_dry_run_vince_su_attivo(self):
        lock, scrivi, registra = LockFinto(), mock.MagicMock(), mock.MagicMock()
        esito, _ = self.esegui([5], [riga(5)], dry_run=True, attivo=True,
                               uscita=self.cartella / "p.json", generatore=generatore_finto(),
                               scrivi=scrivi, lock=lock, registra_run=registra)
        self.assertFalse(esito["attivo"])
        scrivi.assert_not_called()
        registra.assert_not_called()
        self.assertEqual(lock.acquisiti, [])

    def test_file_non_scrivibile_ferma_prima_di_spendere(self):
        generatore = generatore_finto()
        esito, _ = self.esegui([5], [riga(5)], generatore=generatore,
                               uscita=self.cartella / "manca" / "p.json")
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(generatore.chiamate, [])


class TestPercorsoPredefinito(unittest.TestCase):
    def test_nome_con_la_data_e_ora_se_esiste_gia(self):
        adesso = datetime(2026, 9, 30, 14, 5, 9)
        cartella = Path("/casa")
        self.assertEqual(runner.percorso_proposte(cartella, adesso, esiste=lambda p: False),
                         Path("/casa/seo-proposte-2026-09-30.json"))
        self.assertEqual(runner.percorso_proposte(cartella, adesso, esiste=lambda p: True),
                         Path("/casa/seo-proposte-2026-09-30-140509.json"))


class TestImpronta(unittest.TestCase):
    def test_oggetto_e_stringa_json_danno_la_stessa_impronta(self):
        contenuto = {"sections": [{"type": "h2", "text": "Città"}], "b": 1}
        self.assertEqual(runner.impronta_testo(contenuto),
                         runner.impronta_testo(json.dumps(contenuto)))
        self.assertEqual(runner.impronta_testo(contenuto),
                         runner.impronta_testo({"b": 1, "sections": [{"text": "Città", "type": "h2"}]}))
        self.assertNotEqual(runner.impronta_testo(contenuto),
                            runner.impronta_testo({"sections": [], "b": 1}))
        self.assertEqual(runner.impronta_testo(None), runner.impronta_testo(""))


class TestAttivo(ConCartella):
    def _proposte(self, righe, **opzioni):
        """Il file di una prova vera, fatta con il generatore finto."""
        esito, _t, _d = self.prova([r["id"] for r in righe], righe,
                                   generatore=opzioni.pop("generatore", generatore_finto()))
        return esito["uscita"]

    def test_scrive_le_proposte_senza_modello_sotto_lock(self):
        righe = [riga(5)]
        percorso = self._proposte(righe)
        esito, testo, p = self.attivo(percorso, righe)
        self.assertEqual(esito["modo"], runner.MODO_ATTIVO)
        self.assertEqual(p["lock"].acquisiti, [("bandi_pipeline", "seo-rigenera:cli", 3600)])
        self.assertEqual(len(p["lock"].rilasciati), 1)
        p["scrivi"].assert_called_once()
        bando_id, campi = p["scrivi"].call_args.args
        self.assertEqual(bando_id, 5)
        self.assertEqual(campi, {"contenuto": _contenuto("Possono partecipare le imprese.")})
        self.assertEqual(esito["scritti"], 1)
        self.assertEqual(esito["usd"], 0)                      # nessuna chiamata
        self.assertIn("scritto 5: contenuto", testo)

    def test_scrive_esattamente_il_testo_della_prova(self):
        # Il testo scritto e' quello del file, anche se Michele lo ha letto e
        # un'altra chiamata al modello ne darebbe uno diverso.
        vecchia = riga(5, descrizione_breve="Per le imprese, in forma singola o associata.")
        percorso = self._proposte([vecchia])
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
        _e, _t, p = self.attivo(percorso, [vecchia])
        _id, campi = p["scrivi"].call_args.args
        self.assertEqual(campi["contenuto"], dati["proposte"][0]["contenuto"])
        self.assertEqual(campi["descrizione_breve"], dati["proposte"][0]["descrizione_breve"])

    def test_salta_il_bando_non_piu_pubblicato(self):
        percorso = self._proposte([riga(5), riga(6)])
        oggi = [riga(5, pubblicato=False), riga(6, bando_master_id=1)]
        esito, testo, p = self.attivo(percorso, oggi)
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_non_pubblicati"], 2)
        self.assertIn("saltato 6: fuso nel 1", testo)

    def test_salta_il_bando_sparito(self):
        percorso = self._proposte([riga(5)])
        esito, _t, p = self.attivo(percorso, [])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_non_pubblicati"], 1)

    def test_salta_il_contenuto_cambiato_dopo_la_prova(self):
        percorso = self._proposte([riga(5)])
        cambiata = riga(5, contenuto=_contenuto("imprese in forma singola o associata, rivisto"))
        esito, testo, p = self.attivo(percorso, [cambiata])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_cambiati"], 1)
        self.assertIn("contenuto cambiato", testo)

    def test_salta_la_descrizione_cambiata_se_la_si_riscrive(self):
        vecchia = riga(5, descrizione_breve="Per le imprese, in forma singola o associata.")
        percorso = self._proposte([vecchia])
        cambiata = dict(vecchia, descrizione_breve="Corretta a mano nel frattempo.")
        esito, _t, p = self.attivo(percorso, [cambiata])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_cambiati"], 1)

    def test_la_descrizione_cambiata_non_conta_se_non_si_riscrive(self):
        percorso = self._proposte([riga(5)])                   # descrizione pulita: resta
        cambiata = riga(5, descrizione_breve="Corretta a mano nel frattempo.")
        esito, _t, p = self.attivo(percorso, [cambiata])
        self.assertEqual(esito["scritti"], 1)
        self.assertEqual(set(p["scrivi"].call_args.args[1]), {"contenuto"})

    def test_salta_il_testo_ancora_segnalato(self):
        percorso = self._proposte(
            [riga(5)], generatore=generatore_finto(contenuto="Anche reti di imprese."))
        esito, testo, p = self.attivo(percorso, [riga(5)])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_non_sostenuti"], 1)
        self.assertIn("ancora segnalato", testo)

    def test_salta_le_proposte_fuori_forma(self):
        # Il file si puo' ritoccare a mano: un testo fuori dal contratto DB
        # (§3, `{sections: [...]}`) non deve arrivare sul sito ne' a BandoFit.
        righe = [riga(i) for i in range(1, 7)]
        percorso = Path(self._proposte(righe))
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        fuori_forma = {
            1: "testo semplice al posto dell'oggetto",
            2: {"blocchi": []},
            3: {"sections": []},
            4: {"sections": ["paragrafo senza tipo"]},
        }
        for voce in dati["proposte"]:
            if voce["id"] in fuori_forma:
                voce["contenuto"] = fuori_forma[voce["id"]]
            if voce["id"] == 5:
                voce["descrizione_breve"] = "Troppo corta."        # fuori da 180-320
            voce["sha256_proposta"] = runner.impronta_proposta(voce)   # ritocco «firmato»
        percorso.write_text(json.dumps(dati), encoding="utf-8")
        esito, testo, p = self.attivo(str(percorso), righe)
        self.assertEqual(esito["saltati_forma_non_valida"], 5)
        self.assertEqual([c.args[0] for c in p["scrivi"].call_args_list], [6])
        self.assertIn("fuori forma 5", testo)

    def test_forma_valida(self):
        buona = {"contenuto": _contenuto("x"), "descrizione_breve": None}
        self.assertTrue(runner.forma_valida(buona))
        self.assertTrue(runner.forma_valida(dict(buona, descrizione_breve=DESCRIZIONE_NUOVA)))
        self.assertFalse(runner.forma_valida(dict(buona, descrizione_breve="Nuova.")))
        self.assertFalse(runner.forma_valida(dict(buona, descrizione_breve="x" * 321)))
        self.assertFalse(runner.forma_valida(dict(buona, descrizione_breve=42)))
        self.assertFalse(runner.forma_valida(dict(buona, descrizione_breve="  ")))
        self.assertFalse(runner.forma_valida(dict(buona, contenuto=json.dumps(_contenuto("x")))))

    def _ritocca(self, percorso, bando_id, firma=False, **campi):
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
        for voce in dati["proposte"]:
            if voce["id"] == bando_id:
                voce.update(campi)
                if firma:
                    voce["sha256_proposta"] = runner.impronta_proposta(voce)
        Path(percorso).write_text(json.dumps(dati), encoding="utf-8")

    def test_testo_ritoccato_dopo_la_prova_non_si_scrive(self):
        # Revisione avversaria P2-g: si scrive esattamente il testo provato.
        percorso = self._proposte([riga(5)])
        self._ritocca(percorso, 5, contenuto=_contenuto("Testo cambiato a mano nel file."))
        esito, testo, p = self.attivo(percorso, [riga(5)])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_testo_alterato"], 1)
        self.assertIn("diverso da quello della prova", testo)

    def test_le_affermazioni_si_ricalcolano_non_si_leggono_dal_file(self):
        percorso = self._proposte([riga(5)])
        # Il ritocco «firmato» dice ancora affermazioni_nuove = []: non basta.
        self._ritocca(percorso, 5, firma=True,
                      contenuto=_contenuto("Anche reti di imprese e aggregazioni."))
        esito, testo, p = self.attivo(percorso, [riga(5)])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_non_sostenuti"], 1)
        self.assertIn("reti di imprese", testo)

    def test_il_gate_dei_link_si_rifa(self):
        con_link = {"sections": [
            {"type": "h2", "text": "Come partecipare"},
            {"type": "paragraph", "segments": [
                {"kind": "link", "text": "avviso", "url": URL_BANDO}]},
        ]}
        percorso = self._proposte(
            [riga(5)], generatore=generatore_finto(contenuto_oggetto=con_link,
                                                   link_ammessi=(URL_BANDO,)))
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
        self.assertEqual(dati["proposte"][0]["link_ammessi"], [URL_BANDO])
        # Link ammesso: si scrive.
        esito, _t, p = self.attivo(percorso, [riga(5)])
        self.assertEqual(esito["scritti"], 1)
        # Link cambiato (e firmato): il gate lo rifiuta.
        altro = json.loads(json.dumps(con_link))
        altro["sections"][1]["segments"][0]["url"] = "https://aggregatore.example/bando"
        self._ritocca(percorso, 5, firma=True, contenuto=altro)
        esito, testo, p = self.attivo(percorso, [riga(5)])
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_link_non_ammessi"], 1)
        self.assertIn("link non ammessi 1", testo)

    def test_la_prova_salva_fonte_link_e_impronta(self):
        percorso = self._proposte([riga(5)])
        voce = json.loads(Path(percorso).read_text(encoding="utf-8"))["proposte"][0]
        self.assertIn("Bando per imprese", voce["fonte"])
        self.assertIsNone(voce["link_ammessi"])
        self.assertEqual(voce["sha256_proposta"], runner.impronta_proposta(voce))

    def test_un_file_della_versione_1_va_rifatto(self):
        percorso = self.cartella / "vecchio.json"
        percorso.write_text(json.dumps({"versione": 1, "proposte": []}), encoding="utf-8")
        esito, _t, p = self.attivo(str(percorso), [riga(5)])
        self.assertEqual(esito["status"], "errore")
        self.assertIn("nuova prova", esito["motivo"])
        self.assertEqual(p["lock"].acquisiti, [])

    def test_la_scrittura_porta_ultimo_cambiamento_at_della_prova(self):
        # Revisione avversaria: fra il controllo e l'UPDATE un altro comando
        # (`rigenera`, `monitor --attivo` da CLI) puo' riscrivere il bando.
        # L'UPDATE pretende l'`ultimo_cambiamento_at` salvato dalla PROVA (R1).
        righe = [riga(5, ultimo_cambiamento_at="2026-09-30T10:00:00.123456+00:00")]
        percorso = self._proposte(righe)
        voce = json.loads(Path(percorso).read_text(encoding="utf-8"))["proposte"][0]
        self.assertEqual(voce["ultimo_cambiamento_at"], "2026-09-30T10:00:00.123456+00:00")
        _e, _t, p = self.attivo(percorso, righe)
        self.assertEqual(p["scrivi"].call_args.kwargs,
                         {"ultimo_cambiamento_at": "2026-09-30T10:00:00.123456+00:00"})

    def test_bando_cambiato_dopo_la_prova_non_si_scrive(self):
        # R1: date o stato cambiati dopo la prova muovono ultimo_cambiamento_at
        # anche se il testo e' lo stesso: il testo provato non vale piu'.
        prima = [riga(5, ultimo_cambiamento_at="2026-09-30T10:00:00+00:00")]
        percorso = self._proposte(prima)
        dopo = [riga(5, ultimo_cambiamento_at="2026-09-30T14:00:00+00:00",
                     data_scadenza="2026-11-30")]
        esito, testo, p = self.attivo(percorso, dopo)
        p["scrivi"].assert_not_called()
        self.assertEqual(esito["saltati_cambiati"], 1)
        self.assertIn("cambiato dopo la prova", testo)

    def test_senza_ultimo_cambiamento_at_nessun_filtro(self):
        # DB senza la migrazione 01: la colonna non c'e', la prova salva None.
        percorso = self._proposte([riga(5)])
        esito, _t, p = self.attivo(percorso, [riga(5)])
        self.assertEqual(esito["scritti"], 1)
        self.assertEqual(p["scrivi"].call_args.kwargs, {"ultimo_cambiamento_at": None})

    def test_zero_righe_aggiornate_vale_cambiato(self):
        righe = [riga(5)]
        percorso = self._proposte(righe)
        esito, testo, _p = self.attivo(percorso, righe, scrivi=mock.MagicMock(return_value=False))
        self.assertEqual(esito["scritti"], 0)
        self.assertEqual(esito["saltati_cambiati"], 1)
        self.assertIn("cambiato fra il controllo e la scrittura", testo)

    def test_ids_filtrano_le_proposte(self):
        righe = [riga(5), riga(6)]
        percorso = self._proposte(righe)
        esito, _t, p = self.attivo(percorso, righe, ids=[6, 99])
        self.assertEqual([c.args[0] for c in p["scrivi"].call_args_list], [6])
        self.assertEqual(esito["rifiutati"], [{"id": 99, "motivo": "assente dalle proposte"}])

    def test_riga_pipeline_run_con_step_di_backfill(self):
        righe = [riga(5)]
        percorso = self._proposte(righe)
        _e, _t, p = self.attivo(percorso, righe)
        p["registra_run"].assert_called_once()
        run = p["registra_run"].call_args.args[0]
        self.assertEqual(run.step, "backfill:seo-rigenera")
        self.assertEqual(run.costo_usd, 0)
        self.assertEqual(run.contatori["scritti"], 1)
        self.assertNotIn("esiti", run.contatori)

    def test_lock_occupato_non_scrive(self):
        righe = [riga(5)]
        percorso = self._proposte(righe)
        esito, _t, p = self.attivo(percorso, righe, lock=LockFinto(blocco.OCCUPATO))
        self.assertTrue(esito["saltato_per_lock"])
        p["scrivi"].assert_not_called()
        self.assertEqual(cli._codice_da_contatori(esito), cli.EXIT_LOCK)
        self.assertTrue(p["registra_run"].call_args.args[0].saltato_per_lock)

    def test_attivo_senza_proposte_non_parte(self):
        lock = LockFinto()
        esito, _ = self.esegui([5], [riga(5)], attivo=True, generatore=_mai, lock=lock,
                               registra_run=mock.MagicMock())
        self.assertEqual(esito["status"], "errore")
        self.assertIn("--proposte", esito["motivo"])
        self.assertEqual(lock.acquisiti, [])

    def test_file_malformato_non_prende_il_lock(self):
        percorso = self.cartella / "rotto.json"
        percorso.write_text(json.dumps({"versione": 99, "proposte": []}), encoding="utf-8")
        esito, _t, p = self.attivo(str(percorso), [riga(5)])
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(p["lock"].acquisiti, [])
        p["scrivi"].assert_not_called()

    def test_la_chiave_vietata_ferma_il_comando(self):
        # Il chokepoint vero: un errore di programmazione non si trasforma in
        # un contatore «errori».
        def scrivi(bando_id, campi, **_opzioni):
            return db.aggiorna_testo_seo(bando_id, {**campi, "slug": "x"}, client=mock.MagicMock())

        righe = [riga(5)]
        percorso = self._proposte(righe)
        esito, _t, _p = self.attivo(percorso, righe, scrivi=scrivi)
        self.assertEqual(esito["status"], "errore")
        self.assertEqual(esito["scritti"], 0)


class TestRifiuti(ConCartella):
    def test_non_pubblicati_fusi_e_inesistenti_rifiutati(self):
        righe = [
            riga(1),
            riga(2, stato_processing="enriched", pubblicato=False, slug=None),
            riga(3, bando_master_id=1),
            riga(4, pubblicato=False),
        ]
        generatore = generatore_finto()
        esito, testo = self.esegui([1, 2, 3, 4, 99], righe, generatore=generatore)
        self.assertEqual(generatore.chiamate, [1])
        motivi = {r["id"]: r["motivo"] for r in esito["rifiutati"]}
        self.assertEqual(set(motivi), {2, 3, 4, 99})
        self.assertIn("fuso", motivi[3])
        self.assertEqual(motivi[99], "inesistente")
        self.assertIn("rifiutato 2", testo)

    def test_senza_colonna_pubblicato_vale_il_predicato_storico(self):
        vecchia = {k: v for k, v in riga(1).items() if k != "pubblicato"}
        self.assertIsNone(runner.motivo_rifiuto(vecchia))
        self.assertIsNotNone(runner.motivo_rifiuto({**vecchia, "slug": None}))

    def test_limit_conta_le_schede_lavorate(self):
        generatore = generatore_finto()
        righe = [riga(1, stato_processing="enriched", pubblicato=False), riga(2), riga(3)]
        self.esegui([1, 2, 3], righe, generatore=generatore, limit=1)
        self.assertEqual(generatore.chiamate, [2])


class TestSoloControllo(ConCartella):
    def test_niente_modello_lock_scritture_ne_telemetria(self):
        lock, scrivi, registra = LockFinto(), mock.MagicMock(), mock.MagicMock()
        esito, testo = self.esegui(
            [], [riga(1), riga(2, contenuto=_contenuto("Possono partecipare le PMI."))],
            solo_controllo=True, beneficiari={1: ["Imprese"], 2: ["PMI"]},
            generatore=_mai, contesto=_mai, scrivi=scrivi, lock=lock,
            registra_run=registra,
        )
        self.assertEqual(esito["modo"], runner.MODO_CONTROLLO)
        self.assertEqual((esito["esaminati"], esito["segnalati"]), (2, 1))
        self.assertEqual(esito["usd"], 0)
        scrivi.assert_not_called()
        registra.assert_not_called()
        self.assertEqual(lock.acquisiti, [])
        self.assertIn("1\tbando-1\tforma singola o associata", testo)
        self.assertIn("Stima per eccesso", testo)
        self.assertNotIn("uscita", esito)                      # nessun file

    def test_attivo_ignorato_in_solo_controllo(self):
        lock = LockFinto()
        esito, _ = self.esegui([], [riga(1)], solo_controllo=True, attivo=True, beneficiari={},
                               lock=lock, registra_run=mock.MagicMock())
        self.assertFalse(esito["attivo"])
        self.assertEqual(lock.acquisiti, [])

    def test_i_casi_reali_con_i_soli_campi_grezzi(self):
        righe, beneficiari = [], {}
        for bando_id, caso in CASI_REALI.items():
            righe.append(riga(bando_id, titolo_raw=caso["titolo_raw"],
                              raw_data=caso["raw_data"],
                              descrizione_breve=caso["descrizione_breve"],
                              contenuto=caso["contenuto"]))
            beneficiari[bando_id] = caso["beneficiari"]
        esito, testo = self.esegui([], righe, solo_controllo=True, beneficiari=beneficiari)
        segnalati = {int(r.split("\t")[0]) for r in testo.splitlines() if "\t" in r}
        # I sei con forme di partecipazione, piu' il 1262345: senza la pagina
        # del Piemonte la sua ATS non risulta sostenuta (stima per eccesso).
        self.assertEqual(segnalati, {18145, 18278, 171905, 1262345, 1262399, 1262408})
        self.assertEqual(esito["segnalati"], 6)


class TestConsumiDiRegime(unittest.TestCase):
    """RIPRESA §5.10: la riga di `seo-rigenera` non entra in `consumo_oggi`."""

    def test_lo_step_e_fuori_dal_regime(self):
        self.assertFalse(bilancio.conta_nel_regime(runner.STEP_SEO_RIGENERA))
        self.assertTrue(bilancio.e_backfill(runner.STEP_SEO_RIGENERA))

    def test_consumo_oggi_non_somma_la_rigenerazione(self):
        righe = [
            {"id": 1, "step": "monitor", "contatori": {"usd": 0.10, "classificazioni": 2}},
            {"id": 2, "step": runner.STEP_SEO_RIGENERA,
             "contatori": {"usd": 5.0, "classificazioni": 40}},
        ]
        client = mock.MagicMock()
        (client.table.return_value.select.return_value.gte.return_value
         .order.return_value.execute.return_value) = types.SimpleNamespace(data=righe)
        strumento = mock.MagicMock()
        strumento.tabella_esiste.return_value = True
        somma = db.consumo_oggi(client=client, strumento=strumento)
        self.assertAlmostEqual(somma["usd"], 0.10)
        self.assertEqual(somma["classificazioni"], 2)


class TestScritturaDb(unittest.TestCase):
    def test_solo_contenuto_e_descrizione(self):
        for campi in ({"contenuto": {}, "slug": "x"}, {"titolo": "x"}, {"data_scadenza": "x"}, {}):
            with self.subTest(campi=campi):
                client = mock.MagicMock()
                with self.assertRaises(db.PayloadBandoVietato):
                    db.aggiorna_testo_seo(5, campi, client=client)
                client.table.assert_not_called()

    def test_update_filtrato_sui_completed(self):
        client = mock.MagicMock()
        catena = client.table.return_value.update.return_value.eq.return_value.eq.return_value
        catena.execute.return_value = types.SimpleNamespace(data=[{"id": 5}])
        campi = {"contenuto": {"sections": []}, "descrizione_breve": "d"}
        self.assertTrue(db.aggiorna_testo_seo(5, campi, client=client))
        client.table.assert_called_once_with("bando")
        client.table.return_value.update.assert_called_once_with(campi)
        client.table.return_value.update.return_value.eq.assert_called_once_with("id", 5)
        client.table.return_value.update.return_value.eq.return_value.eq.assert_called_once_with(
            "stato_processing", "completed")

    def test_update_filtrato_anche_su_ultimo_cambiamento_at(self):
        client = mock.MagicMock()
        primo = client.table.return_value.update.return_value.eq.return_value
        terzo = primo.eq.return_value.eq.return_value
        terzo.execute.return_value = types.SimpleNamespace(data=[])
        valore = "2026-09-30T10:00:00.123456+00:00"
        self.assertFalse(db.aggiorna_testo_seo(5, {"contenuto": {}}, client=client,
                                               ultimo_cambiamento_at=valore))
        primo.eq.return_value.eq.assert_called_once_with("ultimo_cambiamento_at", valore)

    def test_la_lettura_chiede_ultimo_cambiamento_at(self):
        self.assertIn("ultimo_cambiamento_at", db.COLONNE_SEO_RIGENERA_OPZIONALI)

    def test_riga_uscita_dai_pubblicati_non_risulta_scritta(self):
        client = mock.MagicMock()
        catena = client.table.return_value.update.return_value.eq.return_value.eq.return_value
        catena.execute.return_value = types.SimpleNamespace(data=[])
        self.assertFalse(db.aggiorna_testo_seo(5, {"contenuto": {}}, client=client))


class TestRigaDiComando(unittest.TestCase):
    def setUp(self):
        self._cartella = tempfile.TemporaryDirectory()
        self.addCleanup(self._cartella.cleanup)
        self.cartella = Path(self._cartella.name)
        self.file_proposte = self.cartella / "proposte.json"
        self.file_proposte.write_text("{}", encoding="utf-8")

    def _lancia(self, argv, esito=None):
        finto = types.ModuleType(f"{ALIAS}.bando_seo_runner")
        finto.run_seo_rigenera = mock.AsyncMock(return_value=esito or {"status": "ok"})
        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, {f"{ALIAS}.bando_seo_runner": finto}), \
             mock.patch.object(cli, "logger", mock.MagicMock()), \
             contextlib.redirect_stderr(stderr):
            codice = cli.main(["seo-rigenera", *argv])
        return codice, stderr.getvalue(), finto.run_seo_rigenera

    def test_prova_con_ids(self):
        codice, _, ingresso = self._lancia(["--dry-run", "--ids", "18145,18278"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertEqual(ingresso.await_args.args[0], (18145, 18278))
        self.assertEqual(ingresso.await_args.kwargs,
                         {"dry_run": True, "attivo": False, "solo_controllo": False,
                          "limit": None, "uscita": None, "proposte": None})

    def test_prova_con_uscita(self):
        uscita = str(self.cartella / "nuovo.json")
        codice, _, ingresso = self._lancia(["--ids", "5", "--uscita", uscita])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertEqual(ingresso.await_args.kwargs["uscita"], uscita)

    def test_attivo_con_proposte(self):
        codice, _, ingresso = self._lancia(
            ["--attivo", "--proposte", str(self.file_proposte), "--limit", "1"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertEqual(ingresso.await_args.args[0], ())
        self.assertTrue(ingresso.await_args.kwargs["attivo"])
        self.assertEqual(ingresso.await_args.kwargs["proposte"], str(self.file_proposte))
        self.assertEqual(ingresso.await_args.kwargs["limit"], 1)

    def test_solo_controllo_senza_ids(self):
        codice, _, ingresso = self._lancia(["--solo-controllo"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertEqual(ingresso.await_args.args[0], ())
        self.assertTrue(ingresso.await_args.kwargs["solo_controllo"])

    def test_attivo_senza_proposte_spiega_la_sequenza(self):
        codice, stderr, ingresso = self._lancia(["--ids", "5", "--attivo"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("--dry-run --ids", stderr)
        self.assertIn("--attivo --proposte FILE", stderr)
        ingresso.assert_not_awaited()

    def test_opzioni_rifiutate_con_exit_2(self):
        esistente = str(self.file_proposte)
        casi = (
            ["--ids", "5", "--dry-run", "--attivo", "--proposte", esistente],
            ["--solo-controllo", "--attivo", "--proposte", esistente],
            ["--ids", "5", "--proposte", esistente],                  # senza --attivo
            ["--attivo", "--proposte", str(self.cartella / "manca.json")],
            ["--ids", "5", "--uscita", esistente],                    # sovrascriverebbe
            ["--attivo", "--proposte", esistente, "--uscita", "x.json"],
            ["--solo-controllo", "--uscita", "x.json"],
            [],
            ["--ids", "x"],
            ["--ids", "0"],
            ["--ids"],
            # Un `--ids` scritto ma vuoto: con la definizione unica e' un errore
            # anche qui (correzione finale del 30/09/2026).
            ["--solo-controllo", "--ids", ","],
            ["--ids", "5", "--ombra"],
            ["--ids", "5", "--dryrun"],
        )
        for argv in casi:
            with self.subTest(argv=argv):
                codice, stderr, ingresso = self._lancia(argv)
                self.assertEqual(codice, cli.EXIT_OPZIONI)
                self.assertTrue(stderr)
                ingresso.assert_not_awaited()

    def test_lock_occupato_exit_3_ed_errore_exit_1(self):
        argv = ["--attivo", "--proposte", str(self.file_proposte)]
        codice, _, _ = self._lancia(argv, {"status": "ok", "saltato_per_lock": True})
        self.assertEqual(codice, cli.EXIT_LOCK)
        codice, _, _ = self._lancia(argv, {"status": "errore"})
        self.assertEqual(codice, cli.EXIT_ERRORE)

    def test_l_help_dice_che_la_prova_spende_e_la_finestra_sicura(self):
        self.assertIn("SPENDE", cli.__doc__)
        self.assertIn("finestra sicura", cli.__doc__)
        self.assertIn("--attivo --proposte FILE", cli.__doc__)
        self.assertIn("seo-rigenera", cli._COMMANDS)

    def test_l_help_dice_cosa_il_rilevatore_non_vede(self):
        # Revisione #24: beneficiari e requisiti inventati (1262398, 1262412)
        # non li ferma nessun controllo automatico.
        testo = " ".join(cli.__doc__.split())
        self.assertIn("NON si rilevano in automatico beneficiari e requisiti", testo)
        with open(runner.__file__, encoding="utf-8") as sorgente:
            self.assertIn("beneficiari e requisiti inventati", sorgente.read().lower())


if __name__ == "__main__":
    unittest.main()
