# -*- coding: utf-8 -*-
"""CLI del percorso A del giro 2 (contratto `bandi-giro-2` §13 e §19.12).

`verifica-stato`, `report-verifica-stato`, `domini --import --scarica-enti` e
`gemelli --dry-run`. Nessuno di questi scrive: le scritture del percorso A le
fanno i passi del giro. Qui si prova che:

- senza `--dry-run` `verifica-stato` e `gemelli` escono con 2 e non partono;
- le opzioni arrivano al modulo come devono (fase, ids, senza_modello, limit);
- un token sconosciuto o un valore fuori elenco escono con 2;
- `--verita` stampa `DIFFORME` e `difformi: N`, confronta il report intero
  (senza i filtri) ed esce con 1 se N > 0;
- `verifica_stato.py` si carica solo quando serve: il modulo e' finto.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_cli_verifica_stato
"""
import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.supporto import ALIAS, carica_modulo

cli = carica_modulo("__main__")
db = carica_modulo("db")
gemelli = carica_modulo("gemelli")


def _esegui(argv, **patch_moduli):
    """main(argv) con stdout e stderr catturati e il logger finto."""
    uscita, errori = io.StringIO(), io.StringIO()
    with patch.dict(sys.modules, patch_moduli), patch.object(cli, "logger", MagicMock()), \
            contextlib.redirect_stdout(uscita), contextlib.redirect_stderr(errori):
        codice = cli.main(argv)
    return codice, uscita.getvalue(), errori.getvalue()


def _verifica_finta(esito=None, report=(), difformi=()):
    modulo = types.ModuleType(f"{ALIAS}.verifica_stato")
    modulo.esegui_passo = AsyncMock(return_value=esito if esito is not None else {
        "status": "ok", "counters": {"modalita": "ombra", "fase": "controlli", "candidati": 3,
                                     "letti": 2, "smentiti": 1},
        "slug_modificati": [], "ids_da_rigenerare": [],
        "proposte": [{"bando_id": 2387, "tipo": "chiusura", "campo": None, "esito": "ombra",
                      "gate": {"superati": ["G1", "G2v"], "falliti": ["G7e"]}}],
    })
    modulo.righe_report = MagicMock(return_value=list(report))
    modulo.confronta_verita = MagicMock(return_value=list(difformi))
    return {f"{ALIAS}.verifica_stato": modulo}, modulo


class VerificaStato(unittest.TestCase):
    def test_senza_dry_run_exit_2_e_non_parte(self):
        moduli, finto = _verifica_finta()
        codice, _, errori = _esegui(["verifica-stato", "--senza-modello"], **moduli)
        self.assertEqual(codice, 2)
        self.assertIn("--dry-run", errori)
        finto.esegui_passo.assert_not_awaited()

    def test_le_opzioni_arrivano_al_passo(self):
        moduli, finto = _verifica_finta()
        codice, uscita, errori = _esegui(
            ["verifica-stato", "--dry-run", "--fase", "ingresso", "--ids", "12, 13,12",
             "--senza-modello", "--limit", "5"], **moduli)
        self.assertEqual(codice, 0, errori)
        finto.esegui_passo.assert_awaited_once_with(
            None, fase="ingresso", dry_run=True, senza_modello=True, ids=(12, 13), limit=5)
        self.assertNotIn("costa", errori)

    def test_default_fase_controlli_e_avviso_sul_modello(self):
        moduli, finto = _verifica_finta()
        codice, _, errori = _esegui(["verifica-stato", "--dry-run"], **moduli)
        self.assertEqual(codice, 0)
        kwargs = finto.esegui_passo.await_args.kwargs
        self.assertEqual((kwargs["fase"], kwargs["senza_modello"], kwargs["ids"]),
                         ("controlli", False, ()))
        self.assertIn("usa il modello e costa", errori)

    def test_stampa_contatori_e_proposte_coi_gate_falliti(self):
        moduli, _ = _verifica_finta()
        _, uscita, _ = _esegui(["verifica-stato", "--dry-run", "--senza-modello"], **moduli)
        self.assertIn("status ok", uscita)
        self.assertIn("candidati: 3", uscita)
        self.assertIn("proposta 2387 chiusura -> ombra | gate falliti: G7e", uscita)
        self.assertIn("niente scritto", uscita)

    def test_stampa_da_riprovare_ed_eventi_non_leggibili(self):
        moduli, _ = _verifica_finta({"status": "ok", "counters": {
            "candidati": 4, "da_riprovare": 2, "eventi_non_leggibili": 1}, "proposte": []})
        _, uscita, _ = _esegui(["verifica-stato", "--dry-run", "--senza-modello"], **moduli)
        self.assertIn("da_riprovare: 2", uscita)
        self.assertIn("eventi_non_leggibili: 1", uscita)

    def test_opzioni_sbagliate_exit_2(self):
        for argv in (["--fase", "boh"], ["--ids", "x"], ["--offset", "800"], ["--attivo"],
                     ["--fase"]):
            with self.subTest(argv=argv):
                moduli, finto = _verifica_finta()
                codice, _, _ = _esegui(["verifica-stato", "--dry-run", *argv], **moduli)
                self.assertEqual(codice, 2)
                finto.esegui_passo.assert_not_awaited()

    def test_saltato_e_errore(self):
        moduli, _ = _verifica_finta({"status": "saltato",
                                     "counters": {"motivo_saltato": "migrazione_assente"}})
        codice, uscita, _ = _esegui(["verifica-stato", "--dry-run", "--senza-modello"], **moduli)
        self.assertEqual(codice, 0)
        self.assertIn("migrazione 13 assente", uscita)
        moduli, _ = _verifica_finta({"status": "errore", "counters": {}})
        codice, _, _ = _esegui(["verifica-stato", "--dry-run", "--senza-modello"], **moduli)
        self.assertEqual(codice, 1)

    def test_modulo_assente_exit_2(self):
        codice, _, errori = _esegui(["verifica-stato", "--dry-run", "--senza-modello"],
                                    **{f"{ALIAS}.verifica_stato": None})
        self.assertEqual(codice, 2)
        self.assertIn("non ancora disponibile", errori)


class ReportVerificaStato(unittest.TestCase):
    RIGHE = [{"id": 2387}, {"id": 18454}]
    REPORT = [
        {"id": 2387, "stato_effettivo": "aperto", "motivo": "smentito_dalla_fonte",
         "pagina": "ii", "metodo": "estrattore", "estrattore": "calabria",
         "etichetta": "Conclusione", "termine_indicato": None, "termine_indicato_fonte": None,
         "proposta": {"tipo": "chiusura"}, "trattenuta": "ombra", "forse_non_un_bando": False,
         "esito": "chiusura"},
    ]

    def _lancia(self, argv, *, difformi=(), letture=None):
        moduli, finto = _verifica_finta(report=self.REPORT, difformi=difformi)
        with patch.object(db, "select_da_verificare", return_value=list(self.RIGHE)) as leggi, \
                patch.object(db, "select_letture_stato",
                             return_value={2387: {}} if letture is None else letture) as letture_:
            risultato = _esegui(["report-verifica-stato", *argv], **moduli)
        return risultato, finto, leggi, letture_

    def test_tabella(self):
        (codice, uscita, _), finto, _, letture = self._lancia([])
        self.assertEqual(codice, 0)
        self.assertIn("ID  STATO_EFFETTIVO  MOTIVO", uscita)
        self.assertIn("2387  aperto  smentito_dalla_fonte  ii  estrattore  calabria", uscita)
        self.assertIn("chiusura", uscita)
        letture.assert_called_once_with(ids=[2387, 18454])
        finto.confronta_verita.assert_not_called()

    def test_json_e_filtri(self):
        (codice, uscita, _), finto, _, _ = self._lancia(
            ["--json", "--ramo", "aperto", "--motivo", "smentito_dalla_fonte"])
        self.assertEqual(codice, 0)
        self.assertEqual(json.loads(uscita)[0]["id"], 2387)
        self.assertEqual(finto.righe_report.call_args.kwargs,
                         {"ramo": "aperto", "motivo": "smentito_dalla_fonte"})

    def test_verita_senza_difformi(self):
        (codice, uscita, _), _, _, _ = self._lancia(["--verita"])
        self.assertEqual(codice, 0)
        self.assertIn("difformi: 0", uscita)

    def test_verita_confermati_dallo_stato(self):
        # Giro 3, §13: gli id della verita' assenti dal report si leggono per
        # stato effettivo; 661135 (chiuso dal job orario) non e' difforme.
        moduli, finto = _verifica_finta(report=self.REPORT)
        finto.VERITA_NOTA = {2387: "chiusura", 661135: "chiusura", 2892: "chiusura"}
        finto.stati_effettivi = MagicMock(return_value={661135: "chiuso", 2892: "aperto"})
        finto.confermati_da_stato = MagicMock(
            return_value=[{"id": 661135, "atteso": "chiusura", "stato": "chiuso"}])
        finto.confronta_verita = MagicMock(
            return_value=[{"id": 2892, "atteso": "chiusura", "trovato": None}])
        with patch.object(db, "select_da_verificare", return_value=list(self.RIGHE)), \
                patch.object(db, "select_letture_stato", return_value={2387: {}}):
            codice, uscita, _ = _esegui(["report-verifica-stato", "--verita"], **moduli)
        self.assertEqual(codice, 1)
        finto.stati_effettivi.assert_called_once_with([661135, 2892])
        stati = {661135: "chiuso", 2892: "aperto"}
        self.assertEqual(finto.confronta_verita.call_args.kwargs, {"stati": stati})
        self.assertEqual(finto.confermati_da_stato.call_args.kwargs, {"stati": stati})
        self.assertIn("CONFERMATO_DA_STATO 661135 atteso=chiusura stato=chiuso", uscita)
        self.assertIn("DIFFORME 2892 atteso=chiusura trovato=None", uscita)
        self.assertIn("confermati_da_stato: 1", uscita)
        self.assertTrue(uscita.rstrip().endswith("difformi: 1"))

    def test_verita_con_difformi_exit_1_e_report_intero(self):
        difformi = [{"id": 18454, "atteso": "confermato", "trovato": "non_decisiva"},
                    {"id": 2339, "atteso": "rettifica:2027-01-19", "trovato": None}]
        (codice, uscita, _), finto, _, _ = self._lancia(["--verita", "--ramo", "apertura"],
                                                       difformi=difformi)
        self.assertEqual(codice, 1)
        self.assertIn("DIFFORME 18454 atteso=confermato trovato=non_decisiva", uscita)
        self.assertIn("DIFFORME 2339 atteso=rettifica:2027-01-19 trovato=None", uscita)
        self.assertTrue(uscita.rstrip().endswith("difformi: 2"))
        # Il confronto e' sul report senza filtri: due chiamate, la seconda senza ramo.
        chiamate = finto.righe_report.call_args_list
        self.assertEqual(chiamate[0].kwargs, {"ramo": "apertura", "motivo": None})
        self.assertEqual(chiamate[1].kwargs, {})

    def test_verita_in_json(self):
        difformi = [{"id": 1, "atteso": "chiusura", "trovato": None}]
        (codice, uscita, _), _, _, _ = self._lancia(["--verita", "--json"], difformi=difformi)
        self.assertEqual(codice, 1)
        self.assertEqual(json.loads(uscita)["difformi"], difformi)

    def test_valori_fuori_elenco_exit_2(self):
        for argv in (["--ramo", "chiuso"], ["--motivo", "boh"], ["--attivo"]):
            with self.subTest(argv=argv):
                (codice, _, _), _, leggi, _ = self._lancia(argv)
                self.assertEqual(codice, 2)
                leggi.assert_not_called()

    def test_senza_letture_lo_dice(self):
        (codice, _, errori), _, _, _ = self._lancia([], letture={})
        self.assertEqual(codice, 0)
        self.assertIn("migrazione 13 assente o passo mai girato", errori)


class DominiScaricaEnti(unittest.TestCase):
    def _finto(self):
        modulo = types.ModuleType(f"{ALIAS}.fonte_ufficiale")
        modulo.run_domini_import = AsyncMock(return_value={"status": "ok",
                                                           "indicepa_esito": "ombra"})
        return {f"{ALIAS}.fonte_ufficiale": modulo}, modulo

    def test_scarica_enti_arriva_al_modulo(self):
        moduli, finto = self._finto()
        codice, _, errori = _esegui(["domini", "--import", "--scarica-enti", "--dry-run"], **moduli)
        self.assertEqual(codice, 0, errori)
        finto.run_domini_import.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, enti=None, scarica_enti=True)

    def test_con_enti_insieme_exit_2(self):
        moduli, finto = self._finto()
        codice, _, errori = _esegui(
            ["domini", "--import", "--scarica-enti", "--enti", "enti.xlsx", "--dry-run"], **moduli)
        self.assertEqual(codice, 2)
        self.assertIn("--scarica-enti", errori)
        finto.run_domini_import.assert_not_awaited()


class Gemelli(unittest.TestCase):
    ESITO = {"status": "ok", "esaminati": 2188, "coppie_per_criterio": {"url": 40},
             "gruppi": 49, "gruppi_oltre_due": 0, "fusioni_previste": 49,
             "fusioni": [[40744, 5596, "riga_calendario"], [942936, 905315, "url"]]}

    def test_senza_dry_run_exit_2(self):
        with patch.object(gemelli, "esegui_passo") as passo:
            codice, _, errori = _esegui(["gemelli"])
        self.assertEqual(codice, 2)
        self.assertIn("--dry-run", errori)
        passo.assert_not_called()

    def test_elenca_in_ombra_tutte_le_fusioni(self):
        # Giro 3, §1 e §17: nessun tetto, l'elenco e' completo (52 fusioni attese).
        with patch.object(gemelli, "esegui_passo", return_value=dict(self.ESITO)) as passo:
            codice, uscita, _ = _esegui(["gemelli", "--dry-run"])
        self.assertEqual(codice, 0)
        passo.assert_called_once_with(None, modalita="ombra", elenco_max=None)
        self.assertIn("40744 -> 5596 (riga_calendario)", uscita)
        self.assertIn("942936 -> 905315 (url)", uscita)
        self.assertIn("fusioni_previste: 49", uscita)
        self.assertNotIn("tetto", uscita)

    def test_limit_ignorato_e_detto(self):
        log = MagicMock()
        uscita = io.StringIO()
        with patch.object(gemelli, "esegui_passo", return_value=dict(self.ESITO)) as passo, \
                patch.object(cli, "logger", log), contextlib.redirect_stdout(uscita):
            codice = cli.main(["gemelli", "--dry-run", "--limit", "3"])
        self.assertEqual(codice, 0)
        passo.assert_called_once_with(None, modalita="ombra", elenco_max=None)
        self.assertTrue(any("--limit ignorato" in str(c.args) for c in log.warning.call_args_list))

    def test_errore_exit_1(self):
        with patch.object(gemelli, "esegui_passo",
                          return_value={"status": "errore", "motivo": "RuntimeError"}):
            codice, _, errori = _esegui(["gemelli", "--dry-run", "--limit", "3"])
        self.assertEqual(codice, 1)
        self.assertIn("RuntimeError", errori)


if __name__ == "__main__":
    unittest.main()
