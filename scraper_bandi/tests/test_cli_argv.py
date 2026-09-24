# -*- coding: utf-8 -*-
"""Parsing della riga di comando di `python -m app` (fix 19 di §8.a / 28 parte B,
sottocomandi v11 di §5 e §6.2, exit code di §16).

Cosa si verifica:
  - `_leggi_opzioni` e' comune a tutti i comandi e produce `Opzioni`
    (dry_run, limit, resto);
  - `discover` e `scrape-bandi` accettano `--dry-run`/`--limit N` e li passano
    ai runner (sul codice vecchio i runner venivano chiamati senza argomenti);
  - i flag storici `--rerun-enriched`/`--rerun-completed` restano;
  - **ogni sottocomando che scrive** accetta `--dry-run` e `--limit N` (M20);
  - i sottocomandi v11 non ancora implementati non partono in silenzio;
  - ogni opzione con valore (`--offset`, `--lotto`, `--id`, …) vale **solo sui
    comandi che la sanno usare**: sugli altri il comando si ferma con exit 2 e
    un messaggio che la nomina, invece di accettarla e buttarla via;
  - gli exit code 3 (lock occupato) e 4 (tetto raggiunto) nascono solo qui;
  - errori di parsing -> messaggio su stderr ed exit 2, nessun runner chiamato.

I runner sono moduli finti registrati in sys.modules: nessun import reale dei
runner, nessun DB, nessuna rete.
"""
import contextlib
import dataclasses
import io
import json
import sys
import types
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from tests.supporto import ALIAS, carica_modulo

cli = carica_modulo("__main__")

# Sottocomandi aggiunti con la v11: diagnosi, import dei domini, i quattro
# sottocomandi del resolver (§5), il monitor, i due dell'ombra (§6.2) e i tre
# lotti di backfill (§6.4).
_COMANDI_V11 = {
    "salute", "domini", "risolvi-fonte", "oe-dettaglio", "link-verifica",
    "fondi-doppioni", "monitor", "report-ombra", "applica-eventi",
    "pulisci-contenuto", "rigenera", "archivia-processed",
}

# Sottocomandi che scriveranno sul DB: per ognuno `--dry-run` e `--limit N`
# devono essere gia' accettati oggi (vincolo 3, M20). `report-ombra` non scrive
# — stampa il CSV della misura — ma sta nell'elenco lo stesso: M20 non ammette
# eccezioni, e un comando che rifiuta `--limit` costringe chi scrive il runbook
# a ricordarsi quale.
_COMANDI_CHE_SCRIVONO = (
    "discover", "scrape-bandi", "preprocess", "enrich", "seo",
    "risolvi-fonte", "oe-dettaglio", "link-verifica", "fondi-doppioni",
    "monitor", "report-ombra", "applica-eventi", "pulisci-contenuto",
    "rigenera", "archivia-processed", "domini",
)

# comando -> modulo runner che `__main__` importa al volo
_RUNNER_DI = {
    "discover": "orchestrator",
    "scrape-bandi": "bando_runner",
    "preprocess": "bando_preprocess_runner",
    "enrich": "bando_enrich_runner",
    "seo": "bando_seo_runner",
}

# I quattro sottocomandi di §5 vivono tutti in `app/fonte_ufficiale.py`, con una
# funzione di ingresso ciascuno. Il modulo finto le espone tutte: senza, il
# comando troverebbe il modulo e non la funzione, che e' un guasto (exit 1) e
# non «modulo assente».
_INGRESSI_FONTE = (
    "run", "run_oe_dettaglio", "run_link_verifica", "run_fondi_doppioni",
    "run_domini_import",
)
# Gli ingressi del monitor (§6.2) e quelli dei lotti di §6.4. I tre di backfill
# vivono in moduli che oggi non hanno ancora quella funzione (o non esistono
# affatto): qui li finiamo apposta, perche' il test misura la riga di comando,
# non la presenza del lotto.
_INGRESSI_MONITORAGGIO = ("run", "run_report_ombra", "run_applica_eventi")
_MODULI_V11 = {
    "fonte_ufficiale": _INGRESSI_FONTE,
    "monitoraggio": _INGRESSI_MONITORAGGIO,
    "rigenera": ("run_rigenera",),
    "backfill": ("run_pulisci_contenuto", "run_archivia_processed"),
}


def _modulo_finto(
    nome: str,
    errore: Exception | None = None,
    ingressi: tuple[str, ...] = ("run",),
) -> types.ModuleType:
    modulo = types.ModuleType(f"{ALIAS}.{nome}")
    for ingresso in ingressi:
        setattr(modulo, ingresso, AsyncMock(return_value={"finto": 1}, side_effect=errore))
    return modulo


class _ConRunnerFinti(unittest.TestCase):
    def esegui(self, argv: list[str], errore: Exception | None = None):
        """main(argv) con tutti i runner finti e il logger sostituito.

        Ritorna (codice di uscita, stderr, {comando: mock di run}, logger finto).
        """
        finti = {nome: _modulo_finto(nome, errore) for nome in _RUNNER_DI.values()}
        # Anche i moduli v11 sono finti: `risolvi-fonte --dry-run` senza questo
        # eseguirebbe il resolver vero, che legge il DB.
        finti.update({
            nome: _modulo_finto(nome, errore, ingressi)
            for nome, ingressi in _MODULI_V11.items()
        })
        registro = {f"{ALIAS}.{nome}": modulo for nome, modulo in finti.items()}
        stderr = io.StringIO()
        log = MagicMock()
        with patch.dict(sys.modules, registro), patch.object(cli, "logger", log):
            with contextlib.redirect_stderr(stderr):
                codice = cli.main(argv)
        run_di = {cmd: finti[mod].run for cmd, mod in _RUNNER_DI.items()}
        return codice, stderr.getvalue(), run_di, log


class TestLeggiOpzioni(unittest.TestCase):
    def test_senza_argomenti_valori_di_default(self):
        self.assertEqual(cli._leggi_opzioni([]), cli.Opzioni(dry_run=False, limit=None, resto=()))

    def test_dry_run_e_limit(self):
        o = cli._leggi_opzioni(["--dry-run", "--limit", "5"])
        self.assertEqual((o.dry_run, o.limit, o.resto), (True, 5, ()))

    def test_ordine_indifferente(self):
        o = cli._leggi_opzioni(["--limit", "7", "--dry-run"])
        self.assertEqual((o.dry_run, o.limit), (True, 7))

    def test_resto_conserva_i_token_non_riconosciuti_in_ordine(self):
        o = cli._leggi_opzioni(["--rerun-enriched", "--limit", "2", "--altro", "--dry-run"])
        self.assertEqual(o.resto, ("--rerun-enriched", "--altro"))
        self.assertEqual((o.dry_run, o.limit), (True, 2))

    def test_limit_zero_ammesso(self):
        self.assertEqual(cli._leggi_opzioni(["--limit", "0"]).limit, 0)

    def test_limit_senza_valore(self):
        with self.assertRaises(cli.ErroreOpzioni):
            cli._leggi_opzioni(["--limit"])

    def test_limit_non_intero(self):
        with self.assertRaises(cli.ErroreOpzioni):
            cli._leggi_opzioni(["--limit", "dieci"])

    def test_limit_negativo(self):
        with self.assertRaises(cli.ErroreOpzioni):
            cli._leggi_opzioni(["--limit", "-1"])

    def test_errore_opzioni_e_un_value_error(self):
        self.assertTrue(issubclass(cli.ErroreOpzioni, ValueError))

    def test_opzioni_e_una_dataclass_immutabile(self):
        self.assertTrue(dataclasses.is_dataclass(cli.Opzioni))
        self.assertEqual(
            [f.name for f in dataclasses.fields(cli.Opzioni)], ["dry_run", "limit", "resto"],
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cli.Opzioni().dry_run = True  # type: ignore[misc]


class TestComandi(_ConRunnerFinti):
    def test_tutti_i_comandi_sono_registrati_e_accettano_argv(self):
        self.assertEqual(set(cli._COMMANDS), set(_RUNNER_DI) | _COMANDI_V11)
        for cmd, fn in cli._COMMANDS.items():
            self.assertTrue(callable(fn), cmd)

    def test_ogni_comando_passa_da_leggi_opzioni(self):
        for cmd in _RUNNER_DI:
            with self.subTest(cmd=cmd):
                with patch.object(cli, "_leggi_opzioni", wraps=cli._leggi_opzioni) as spia:
                    codice, _, _, _ = self.esegui([cmd, "--dry-run"])
                self.assertEqual(codice, 0)
                spia.assert_called_once_with(["--dry-run"])

    def test_discover_senza_opzioni_usa_i_default(self):
        codice, _, run_di, _ = self.esegui(["discover"])
        self.assertEqual(codice, 0)
        run_di["discover"].assert_awaited_once_with(dry_run=False, limit=None)

    def test_discover_dry_run_e_limit(self):
        codice, _, run_di, _ = self.esegui(["discover", "--dry-run", "--limit", "3"])
        self.assertEqual(codice, 0)
        run_di["discover"].assert_awaited_once_with(dry_run=True, limit=3)
        run_di["scrape-bandi"].assert_not_awaited()

    def test_scrape_bandi_senza_opzioni_usa_i_default(self):
        codice, _, run_di, _ = self.esegui(["scrape-bandi"])
        self.assertEqual(codice, 0)
        run_di["scrape-bandi"].assert_awaited_once_with(dry_run=False, limit=None)

    def test_scrape_bandi_dry_run_e_limit(self):
        codice, _, run_di, _ = self.esegui(["scrape-bandi", "--limit", "2", "--dry-run"])
        self.assertEqual(codice, 0)
        run_di["scrape-bandi"].assert_awaited_once_with(dry_run=True, limit=2)

    def test_preprocess(self):
        codice, _, run_di, _ = self.esegui(["preprocess", "--dry-run"])
        self.assertEqual(codice, 0)
        run_di["preprocess"].assert_awaited_once_with(dry_run=True, limit=None)

    def test_enrich_mantiene_rerun_enriched(self):
        codice, _, run_di, log = self.esegui(["enrich", "--rerun-enriched", "--limit", "1"])
        self.assertEqual(codice, 0)
        run_di["enrich"].assert_awaited_once_with(dry_run=False, limit=1, include_enriched=True)
        log.warning.assert_not_called()  # flag ammesso: nessun avviso

    def test_enrich_senza_rerun(self):
        _, _, run_di, _ = self.esegui(["enrich"])
        run_di["enrich"].assert_awaited_once_with(dry_run=False, limit=None, include_enriched=False)

    def test_seo_mantiene_rerun_completed(self):
        codice, _, run_di, log = self.esegui(["seo", "--dry-run", "--rerun-completed"])
        self.assertEqual(codice, 0)
        run_di["seo"].assert_awaited_once_with(dry_run=True, limit=None, include_completed=True)
        log.warning.assert_not_called()

    def test_opzione_sconosciuta_ignorata_con_avviso(self):
        codice, _, run_di, log = self.esegui(["discover", "--boh"])
        self.assertEqual(codice, 0)
        run_di["discover"].assert_awaited_once_with(dry_run=False, limit=None)
        log.warning.assert_called_once()

    def test_limit_non_valido_exit_2_e_nessun_runner_chiamato(self):
        for cmd in _RUNNER_DI:
            for argv in (["--limit"], ["--limit", "x"], ["--limit", "-3"]):
                with self.subTest(cmd=cmd, argv=argv):
                    codice, stderr, run_di, _ = self.esegui([cmd, *argv])
                    self.assertEqual(codice, 2)
                    self.assertIn("--limit richiede un intero", stderr)
                    for run in run_di.values():
                        run.assert_not_awaited()

    def test_senza_argomenti_exit_2(self):
        codice, stderr, run_di, _ = self.esegui([])
        self.assertEqual(codice, 2)
        self.assertIn("Usage", stderr)
        for run in run_di.values():
            run.assert_not_awaited()

    def test_comando_sconosciuto_exit_2(self):
        codice, stderr, run_di, _ = self.esegui(["boh", "--dry-run"])
        self.assertEqual(codice, 2)
        self.assertIn("Comando sconosciuto: boh", stderr)
        for run in run_di.values():
            run.assert_not_awaited()

    def test_errore_fatale_del_runner_exit_1(self):
        codice, _, run_di, log = self.esegui(["discover"], errore=RuntimeError("boom"))
        self.assertEqual(codice, 1)
        run_di["discover"].assert_awaited_once()
        log.exception.assert_called_once()


class TestComandiV11(_ConRunnerFinti):
    def test_exit_code_dedicati(self):
        self.assertEqual(
            (cli.EXIT_OK, cli.EXIT_ERRORE, cli.EXIT_OPZIONI, cli.EXIT_LOCK,
             cli.EXIT_TETTO, cli.EXIT_NON_CONFIGURATO),
            (0, 1, 2, 3, 4, 5),
        )

    def test_lock_e_tetto_diventano_codici_solo_qui(self):
        # Dentro la pipeline sono dati (`saltato_per_lock`, `interrotto_per_tetto`):
        # tradurli in exit code e' compito esclusivo della CLI (§16, A15).
        self.assertEqual(cli._codice_da_contatori({"saltato_per_lock": True}), cli.EXIT_LOCK)
        self.assertEqual(cli._codice_da_contatori({"interrotto_per_tetto": True}), cli.EXIT_TETTO)
        self.assertEqual(cli._codice_da_contatori({"selected": 3}), cli.EXIT_OK)
        self.assertEqual(cli._codice_da_contatori(None), cli.EXIT_OK)

    def test_ogni_comando_che_scrive_accetta_dry_run_e_limit(self):
        for cmd in _COMANDI_CHE_SCRIVONO:
            for argv in (["--dry-run"], ["--limit", "3", "--dry-run"]):
                with self.subTest(cmd=cmd, argv=argv):
                    with patch.object(cli, "_leggi_opzioni", wraps=cli._leggi_opzioni) as spia:
                        self.esegui([cmd, *argv])
                    spia.assert_called_once_with(argv)

    def test_limit_non_valido_exit_2_anche_sui_comandi_v11(self):
        for cmd in sorted(_COMANDI_V11):
            with self.subTest(cmd=cmd):
                codice, stderr, _, _ = self.esegui([cmd, "--limit", "x"])
                self.assertEqual(codice, 2)
                self.assertIn("--limit richiede un intero", stderr)

    def test_un_sottocomando_senza_modulo_non_parte_in_silenzio(self):
        # I moduli v11 esistono tutti, ora: la condizione «modulo assente» si
        # riproduce facendola dire a `_modulo_opzionale`, che e' l'unico punto
        # che la distingue da un guasto.
        stderr = io.StringIO()
        with patch.object(
            cli, "_modulo_opzionale", return_value=(None, cli.MODULO_ASSENTE),
        ), patch.object(cli, "logger", MagicMock()), contextlib.redirect_stderr(stderr):
            codice = cli.main(["risolvi-fonte", "--dry-run"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("non ancora disponibile", stderr.getvalue())

    def test_risolvi_fonte_usa_fonte_ufficiale_con_le_opzioni_di_sezione_5(self):
        finto = types.ModuleType(f"{ALIAS}.fonte_ufficiale")
        finto.run = AsyncMock(return_value={"interrotto_per_tetto": True})
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            codice = cli.main([
                "risolvi-fonte", "--dry-run", "--limit", "5", "--attivo",
                "--backlog", "--solo-oe", "--id", "42", "--forza", "--lotto", "L5",
            ])
        self.assertEqual(codice, cli.EXIT_TETTO)
        finto.run.assert_awaited_once_with(
            dry_run=True, limit=5, attivo=True, modo="backlog", solo_oe=True,
            solo_in_verifica=False, bando_id="42", forza=True, anche_oggi=False, offset=0, lotto="L5",
        )

    def test_offset_arriva_al_runner(self):
        # `--offset N` e' il modo di lanciare i blocchi a mano quando niente
        # puo' far uscire una riga dalla selezione (con `--forza`, in ombra o
        # con `--dry-run`, dove nessun marcatore viene scritto).
        finto = types.ModuleType(f"{ALIAS}.fonte_ufficiale")
        finto.run = AsyncMock(return_value={})
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            codice = cli.main([
                "risolvi-fonte", "--dry-run", "--backlog", "--forza",
                "--limit", "800", "--offset", "1600",
            ])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertEqual(finto.run.await_args.kwargs["offset"], 1600)

    def test_offset_non_intero_exit_2(self):
        stderr = io.StringIO()
        with patch.object(cli, "logger", MagicMock()), \
                contextlib.redirect_stderr(stderr):
            codice = cli.main(["risolvi-fonte", "--offset", "meta'"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        # Il messaggio dice che cosa manca: un `--offset` illeggibile passato
        # avanti come zero farebbe ripartire il blocco dall'inizio.
        self.assertIn("--offset richiede un intero", stderr.getvalue())

    def test_risolvi_fonte_default_ombra_e_selezione_nuovi(self):
        finto = types.ModuleType(f"{ALIAS}.fonte_ufficiale")
        finto.run = AsyncMock(return_value={})
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            codice = cli.main(["risolvi-fonte", "--dry-run"])
        self.assertEqual(codice, cli.EXIT_OK)
        finto.run.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, modo="nuovi", solo_oe=False,
            solo_in_verifica=False, bando_id=None, forza=False, anche_oggi=False, offset=0, lotto=None,
        )

    def test_solo_in_verifica_seleziona_i_ricontrolli(self):
        finto = types.ModuleType(f"{ALIAS}.fonte_ufficiale")
        finto.run = AsyncMock(return_value={})
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["risolvi-fonte", "--solo-in-verifica"])
        chiamata = finto.run.await_args.kwargs
        self.assertEqual(chiamata["modo"], "ricontrolli")
        self.assertTrue(chiamata["solo_in_verifica"])

    def test_id_senza_valore_exit_2(self):
        for argv in (["risolvi-fonte", "--id"], ["risolvi-fonte", "--id", "--attivo"]):
            with self.subTest(argv=argv):
                codice, stderr, _, _ = self.esegui(argv)
                self.assertEqual(codice, 2)
                self.assertIn("--id richiede un valore", stderr)

    def test_i_tre_sottocomandi_del_resolver_hanno_il_proprio_ingresso(self):
        # Sono nello stesso modulo ma non nella stessa funzione: sbagliare
        # ingresso significherebbe far girare il resolver al posto della
        # verifica dei link.
        atteso = {
            "oe-dettaglio": "run_oe_dettaglio",
            "link-verifica": "run_link_verifica",
            "fondi-doppioni": "run_fondi_doppioni",
        }
        for cmd, ingresso in atteso.items():
            with self.subTest(cmd=cmd):
                codice, _, _, _ = self.esegui([cmd, "--dry-run"])
                self.assertEqual(codice, 0)

    def test_il_valore_di_una_opzione_non_e_un_token_ignoto(self):
        # Senza togliere la coppia, `--id 42` produrrebbe un warning
        # «opzione non riconosciuta: 42» che non significa niente.
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        log = MagicMock()
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", log):
            cli.main([
                "risolvi-fonte", "--id", "42", "--lotto", "L5", "--backlog", "--ombra",
            ])
        log.warning.assert_not_called()

    def test_senza_valori_toglie_i_valori_e_tiene_i_nomi(self):
        # Il VALORE se ne va (nessun flag riconoscerebbe «42»), il NOME resta:
        # e' il comando a dire quali opzioni con valore accetta, e togliendo
        # anche il nome `--offset` passava indisturbato su tutti i comandi.
        self.assertEqual(
            cli._senza_valori(("--backlog", "--id", "42", "--forza")),
            ("--backlog", "--id", "--forza"),
        )
        # Opzione in coda senza valore: il parsing la rifiutera' comunque, ma
        # qui non deve far saltare un indice.
        self.assertEqual(cli._senza_valori(("--forza", "--id")), ("--forza", "--id"))
        # Il token dopo il nome se ne va anche quando sembra un'opzione: senza,
        # `--id --attivo` finirebbe due volte sotto gli occhi della guardia,
        # mentre a rifiutarlo e' gia' `_valore_opzione` con il suo messaggio.
        self.assertEqual(cli._senza_valori(("--id", "--attivo")), ("--id",))

    def test_oe_dettaglio_passa_forza_e_resta_in_ombra(self):
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["oe-dettaglio", "--dry-run", "--forza"])
        finto.run_oe_dettaglio.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, forza=True,
            solo_oe=True, modo="nuovi", bando_id=None, offset=0,
        )

    def test_oe_dettaglio_backlog_cambia_la_selezione(self):
        # Il lotto L2 (le 1 702 schede gia' pubblicate) non e' la coda dei
        # nuovi: senza `--backlog` il comando ne vedeva una manciata, e
        # `--forza` da solo non bastava perche' scavalca la regola di
        # ri-scarico, non la selezione.
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["oe-dettaglio", "--dry-run", "--backlog", "--forza"])
        kwargs = finto.run_oe_dettaglio.await_args.kwargs
        self.assertEqual(kwargs["modo"], "backlog")
        self.assertTrue(kwargs["forza"])

    def test_oe_dettaglio_senza_backlog_resta_sui_nuovi(self):
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["oe-dettaglio", "--dry-run", "--nuovi"])
        self.assertEqual(finto.run_oe_dettaglio.await_args.kwargs["modo"], "nuovi")

    def test_oe_dettaglio_restringe_a_un_bando(self):
        # `--id` era documentato e ignorato: il comando lavorava sull'intero
        # corpus mentre chi lo lanciava credeva di guardare una riga sola.
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["oe-dettaglio", "--dry-run", "--id", "42"])
        self.assertEqual(finto.run_oe_dettaglio.await_args.kwargs["bando_id"], "42")

    def test_link_verifica_restringe_a_un_bando(self):
        # Senza il filtro, `link-verifica --id 42 --attivo` riscriverebbe
        # `esito_http` e `pubblicabile` su tutte le righe di `bando_link`.
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        log = MagicMock()
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", log):
            cli.main(["link-verifica", "--dry-run", "--id", "42"])
        finto.run_link_verifica.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, bando_id="42", offset=0,
        )
        log.warning.assert_not_called()

    def test_scarico_non_configurato_non_e_un_giro_riuscito(self):
        # Un cron che non scarica niente e resta verde e' peggio di un cron
        # che fallisce: `saltato='scarico_non_configurato'` vale exit 5.
        self.assertEqual(
            cli._codice_da_contatori({"status": "ok", "saltato": "scarico_non_configurato"}),
            cli.EXIT_NON_CONFIGURATO,
        )
        # `colonne_assenti` resta una degradazione prevista: exit 0.
        self.assertEqual(
            cli._codice_da_contatori({"status": "ok", "saltato": "colonne_assenti"}),
            cli.EXIT_OK,
        )

    def test_monitor_ombra_di_default(self):
        finto = types.ModuleType(f"{ALIAS}.monitoraggio")
        finto.run = AsyncMock(return_value={"saltato_per_lock": True})
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": finto}), \
                patch.object(cli, "logger", MagicMock()):
            codice = cli.main(["monitor", "--dry-run"])
        self.assertEqual(codice, cli.EXIT_LOCK)
        # Senza flag la CLI passa `attivo=None`: «l'operatore non ha detto
        # niente», e decide `MONITOR_MODALITA` (ombra per difetto). In ombra
        # l'adattatore che riscrive la prosa non viene nemmeno costruito.
        # I due adattatori del G7 invece si costruirebbero anche in ombra: qui
        # restano `None` perche' il modulo finto non espone i costruttori.
        finto.run.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, senza_rete=False, rigenerazione=None,
            lotto=None, contatori=None, seconda_opinione=None, pagine_collegate=None,
        )

    def test_modulo_rotto_non_si_confonde_con_modulo_assente(self):
        # Un modulo che ESISTE e non si importa (dipendenza mancante, `run`
        # rinominato) e' un guasto, non la tappa successiva del piano: exit 1,
        # non 2, e un messaggio che dice il motivo.
        senza_run = types.ModuleType(f"{ALIAS}.monitoraggio")     # niente `run`
        log = MagicMock()
        stderr = io.StringIO()
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": senza_run}), \
                patch.object(cli, "logger", log), \
                contextlib.redirect_stderr(stderr):
            codice = cli.main(["monitor", "--dry-run"])
        self.assertEqual(codice, cli.EXIT_ERRORE)
        self.assertIn("non importabile", stderr.getvalue())
        self.assertNotIn("non ancora disponibile", stderr.getvalue())
        log.error.assert_called_once()

    def test_dipendenza_mancante_riportata_su_stderr(self):
        stderr = io.StringIO()
        with patch.object(
            cli, "_modulo_opzionale", return_value=(None, "dipendenza mancante: pandas"),
        ), patch.object(cli, "logger", MagicMock()), contextlib.redirect_stderr(stderr):
            codice = cli.main(["risolvi-fonte", "--dry-run"])
        self.assertEqual(codice, cli.EXIT_ERRORE)
        self.assertIn("pandas", stderr.getvalue())

    def test_modulo_assente_resta_esito_atteso(self):
        # Modulo non ancora scritto -> exit 2 e nessun `logger.error`: non e'
        # un guasto, e' la tappa successiva del piano.
        log = MagicMock()
        stderr = io.StringIO()
        with patch.object(
            cli, "_modulo_opzionale", return_value=(None, cli.MODULO_ASSENTE),
        ), patch.object(cli, "logger", log), contextlib.redirect_stderr(stderr):
            codice = cli.main(["monitor"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("non ancora disponibile", stderr.getvalue())
        log.error.assert_not_called()
        log.exception.assert_not_called()

    def test_ombra_vince_sull_ambiente(self):
        # Il difetto: con `MONITOR_MODALITA=attivo` il flag `--ombra` era
        # inerte, perche' la CLI passava `attivo=False` (indistinguibile da
        # «non detto») e il modulo ripiegava sull'ambiente. Ora `--ombra` e'
        # un `False` esplicito e vince.
        finti = {
            nome: _modulo_finto(nome, ingressi=ingressi)
            for nome, ingressi in _MODULI_V11.items()
        }
        registro = {f"{ALIAS}.{nome}": modulo for nome, modulo in finti.items()}
        with patch.dict(sys.modules, registro), patch.object(cli, "logger", MagicMock()):
            codice = cli.main(["pulisci-contenuto", "--ombra"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertIs(
            finti["backfill"].run_pulisci_contenuto.await_args.kwargs["attivo"], False)

    def test_ombra_e_attivo_insieme_exit_2(self):
        codice, stderr, _, _ = self.esegui(["pulisci-contenuto", "--ombra", "--attivo"])
        self.assertEqual(codice, 2)
        self.assertIn("incompatibili", stderr)

    def test_un_refuso_su_dry_run_non_fa_partire_una_scrittura(self):
        # `--dryrun` (senza trattino) passava dall'avviso e il comando girava
        # in modalita' attiva con exit 0. Un refuso su questo flag e' l'unico
        # che puo' costare righe scritte: il comando si ferma.
        codice, stderr, _, _ = self.esegui(["pulisci-contenuto", "--dryrun"])
        self.assertEqual(codice, 2)
        self.assertIn("--dry-run", stderr)
        for cmd in ("rigenera", "archivia-processed", "monitor", "risolvi-fonte",
                    "applica-eventi", "report-ombra"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.esegui([cmd, "--dryrun"])[0], 2)

    def test_flag_di_modalita_non_generano_avvisi(self):
        finto = types.ModuleType(f"{ALIAS}.monitoraggio")
        finto.run = AsyncMock(return_value={})
        log = MagicMock()
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": finto}), \
                patch.object(cli, "logger", log):
            cli.main(["monitor", "--ombra"])
        log.warning.assert_not_called()

    def test_domini_senza_import_rifiuta(self):
        codice, stderr, _, _ = self.esegui(["domini", "--dry-run"])
        self.assertEqual(codice, 2)
        self.assertIn("--import", stderr)

    def test_domini_import_in_ombra_non_scrive(self):
        # Senza `--attivo` il comando compone la whitelist e non tocca niente:
        # la scrittura si chiede per iscritto, come per ogni sottocomando v11.
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            codice = cli.main(["domini", "--import", "--limit", "10"])
        self.assertEqual(codice, 0)
        finto.run_domini_import.assert_awaited_once_with(
            dry_run=False, limit=10, attivo=None, enti=None,
        )

    def test_domini_import_legge_il_foglio_indicepa(self):
        finto = _modulo_finto("fonte_ufficiale", ingressi=_INGRESSI_FONTE)
        with patch.dict(sys.modules, {f"{ALIAS}.fonte_ufficiale": finto}), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(["domini", "--import", "--enti", "enti.xlsx", "--attivo"])
        finto.run_domini_import.assert_awaited_once_with(
            dry_run=False, limit=None, attivo=True, enti="enti.xlsx",
        )


class TestMonitorEOmbra(_ConRunnerFinti):
    """`monitor`, `report-ombra`, `applica-eventi`: §6.2."""

    def _monitor(self, argv: list[str], risposta=None):
        finto = types.ModuleType(f"{ALIAS}.monitoraggio")
        for ingresso in _INGRESSI_MONITORAGGIO:
            setattr(finto, ingresso, AsyncMock(return_value=risposta or {}))
        log = MagicMock()
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": finto}), \
                patch.object(cli, "logger", log):
            codice = cli.main(argv)
        return codice, finto, log

    def test_monitor_attivo_porta_la_rigenerazione_vera(self):
        # Senza `rigenerazione=` il monitor scrive le colonne e NON restituisce
        # lo slug: la pagina resterebbe con il testo vecchio e IndexNow non
        # verrebbe chiamato. L'adattatore e' `rigenera.rigenera` in attivo, con
        # `scrivi_su_db` come scrittore.
        rigenera = carica_modulo("rigenera")
        codice, finto, _ = self._monitor(["monitor", "--attivo"])
        self.assertEqual(codice, cli.EXIT_OK)
        passati = finto.run.await_args.kwargs
        self.assertTrue(passati["attivo"])
        adattatore = passati["rigenerazione"]
        self.assertIs(adattatore.func, rigenera.rigenera)
        self.assertEqual(
            adattatore.keywords, {"attivo": True, "scrivi": rigenera.scrivi_su_db},
        )

    def test_dry_run_e_piu_forte_di_attivo(self):
        # `--attivo --dry-run` non deve lasciare raggiungibile `scrivi_su_db`:
        # un giro che ha promesso di non scrivere non costruisce lo scrittore.
        _, finto, _ = self._monitor(["monitor", "--attivo", "--dry-run"])
        passati = finto.run.await_args.kwargs
        self.assertTrue(passati["attivo"])
        self.assertTrue(passati["dry_run"])
        self.assertIsNone(passati["rigenerazione"])

    def test_rigenerazione_assente_non_fa_fallire_il_giro(self):
        # Un modulo `rigenera` senza i nomi attesi e' un pezzo mancante, non un
        # guasto: il monitor gira lo stesso, senza notificare IndexNow.
        vuoto = types.ModuleType(f"{ALIAS}.rigenera")
        # Il package tiene il sottomodulo anche come attributo: `from . import
        # rigenera` legge quello, quindi patchare il solo sys.modules non
        # basterebbe (e il test resterebbe verde senza provare niente).
        with patch.dict(sys.modules, {f"{ALIAS}.rigenera": vuoto}), \
                patch.object(sys.modules[ALIAS], "rigenera", vuoto):
            codice, finto, log = self._monitor(["monitor", "--attivo"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertIsNone(finto.run.await_args.kwargs["rigenerazione"])
        log.warning.assert_called_once()

    def _monitor_con_g7(self, chiave: str, argv=("monitor",)):
        """Il monitor finto che espone ANCHE i due costruttori del G7."""
        visti = {}

        def seconda(impostazioni, contatori):
            visti["contatori"] = contatori
            return "seconda-opinione"

        def collegate(impostazioni):
            return "pagine-collegate"

        finto = types.ModuleType(f"{ALIAS}.monitoraggio")
        for ingresso in _INGRESSI_MONITORAGGIO:
            setattr(finto, ingresso, AsyncMock(return_value={}))
        finto.seconda_opinione_da_impostazioni = seconda
        finto.pagine_collegate_da_impostazioni = collegate
        impostazioni_vere = carica_modulo("settings")
        finte = types.SimpleNamespace(anthropic_api_key=chiave)
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": finto}), \
                patch.object(impostazioni_vere, "get_settings", lambda: finte), \
                patch.object(cli, "logger", MagicMock()):
            cli.main(list(argv))
        return finto.run.await_args.kwargs, visti

    def test_con_la_chiave_i_due_adattatori_del_g7_arrivano_al_monitor(self):
        # Senza di loro il G7 non e' soddisfacibile e il monitor respinge ogni
        # evento con una transizione o una data (§6.2).
        passati, visti = self._monitor_con_g7("chiave-finta")
        bilancio = carica_modulo("bilancio")
        self.assertEqual(passati["seconda_opinione"], "seconda-opinione")
        self.assertEqual(passati["pagine_collegate"], "pagine-collegate")
        # Gli stessi contatori vanno anche a `run`: il costo della seconda
        # opinione deve entrare nel tetto giornaliero mentre il giro corre.
        self.assertIsInstance(passati["contatori"], bilancio.Contatori)
        self.assertIs(passati["contatori"], visti["contatori"])

    def test_i_due_adattatori_si_costruiscono_anche_in_ombra(self):
        # L'ombra serve a misurare la precisione dei gate: un G7 spento
        # misurerebbe un monitor che non esiste. La rigenerazione invece no.
        passati, _ = self._monitor_con_g7("chiave-finta", ("monitor", "--ombra"))
        self.assertIsNone(passati["rigenerazione"])
        self.assertEqual(passati["seconda_opinione"], "seconda-opinione")

    def test_senza_chiave_il_g7_resta_spento(self):
        passati, visti = self._monitor_con_g7("")
        self.assertIsNone(passati["seconda_opinione"])
        self.assertIsNone(passati["pagine_collegate"])
        self.assertIsNone(passati["contatori"])
        self.assertEqual(visti, {})

    def test_senza_rete_arriva_al_monitor(self):
        _, finto, log = self._monitor(["monitor", "--senza-rete", "--limit", "20"])
        passati = finto.run.await_args.kwargs
        self.assertTrue(passati["senza_rete"])
        self.assertEqual(passati["limit"], 20)
        log.warning.assert_not_called()      # `--senza-rete` e' un flag ammesso

    def test_monitor_tetto_diventa_exit_4(self):
        codice, _, _ = self._monitor(
            ["monitor"], risposta={"status": "ok", "interrotto_per_tetto": True},
        )
        self.assertEqual(codice, cli.EXIT_TETTO)

    def test_report_ombra_campione_predefinito_cento(self):
        # §6.2 chiede la precisione su >= 100 eventi: il default non e' 1 ne' 50.
        self.assertEqual(cli.CAMPIONE_PREDEFINITO, 100)
        _, finto, log = self._monitor(["report-ombra"])
        finto.run_report_ombra.assert_awaited_once_with(
            dry_run=False, limit=None, attivo=None, campione=100, tipo=None, dal=None,
            # Nell'ambiente di prova non c'e' chiave: come `_adattatori_g7`,
            # senza chiave il G7 e' spento e il verdetto va soppresso.
            g7_disponibile=False,
        )
        log.warning.assert_not_called()

    def test_report_ombra_campione_e_tipo(self):
        _, finto, _ = self._monitor(
            ["report-ombra", "--campione", "250", "--tipo", "proroga",
             "--dal", "2026-09-01", "--dry-run"],
        )
        finto.run_report_ombra.assert_awaited_once_with(
            dry_run=True, limit=None, attivo=None, campione=250, tipo="proroga",
            dal=date(2026, 9, 1), g7_disponibile=False,
        )

    def _report_ombra_con_chiave(self, chiave, argv):
        """`report-ombra` con una chiave dichiarata: torna `g7_disponibile`."""
        impostazioni_vere = carica_modulo("settings")
        finte = types.SimpleNamespace(anthropic_api_key=chiave)
        with patch.object(impostazioni_vere, "get_settings", lambda: finte):
            _, finto, _ = self._monitor(argv)
        return finto.run_report_ombra.await_args.kwargs["g7_disponibile"]

    def test_report_ombra_con_la_chiave_il_verdetto_resta(self):
        # La guardia di `run_report_ombra` era scritta e mai collegata: nessun
        # chiamante passava `g7_disponibile`, quindi il comando emetteva un
        # verdetto anche su un periodo girato senza G7.
        self.assertTrue(self._report_ombra_con_chiave("chiave-finta", ["report-ombra"]))

    def test_report_ombra_senza_g7_sopprime_il_verdetto(self):
        # `--senza-g7` vince sulla chiave: e' l'operatore a sapere com'era
        # acceso il periodo d'ombra che sta misurando adesso.
        self.assertFalse(self._report_ombra_con_chiave(
            "chiave-finta", ["report-ombra", "--senza-g7"]))

    def test_report_ombra_senza_g7_non_e_un_refuso(self):
        # Il flag dev'essere fra gli ammessi: un token non riconosciuto su
        # questi comandi e' exit 2, non un avviso.
        codice, finto, log = self._monitor(["report-ombra", "--senza-g7"])
        self.assertEqual(codice, cli.EXIT_OK)
        finto.run_report_ombra.assert_awaited_once()
        log.warning.assert_not_called()

    def test_campione_non_valido_exit_2(self):
        for argv in (["--campione", "zero"], ["--campione", "0"], ["--campione", "-5"]):
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    codice, finto, _ = self._monitor(["report-ombra", *argv])
                self.assertEqual(codice, cli.EXIT_OPZIONI)
                self.assertIn("--campione richiede un intero", stderr.getvalue())
                finto.run_report_ombra.assert_not_awaited()

    def test_applica_eventi_dal_e_tipi(self):
        _, finto, log = self._monitor([
            "applica-eventi", "--dal", "2026-09-01", "--tipo", "proroga,rettifica",
            "--limit", "50", "--dry-run",
        ])
        finto.run_applica_eventi.assert_awaited_once_with(
            dry_run=True, limit=50, attivo=None,
            dal=date(2026, 9, 1), tipi=("proroga", "rettifica"), offset=0,
            riprova_rifiutati=False,
        )
        log.warning.assert_not_called()

    def test_applica_eventi_senza_filtri(self):
        _, finto, _ = self._monitor(["applica-eventi"])
        finto.run_applica_eventi.assert_awaited_once_with(
            dry_run=False, limit=None, attivo=None, dal=None, tipi=(), offset=0,
            riprova_rifiutati=False,
        )

    def test_riprova_rifiutati_arriva_al_comando(self):
        """La via di rientro: le annotazioni dei rifiuti non si cancellano.

        `bando_evento` non concede DELETE nemmeno alla service-role key
        (migrazione 02) e `riferisce_a` e' immutabile: senza questo flag un
        evento annotato per sbaglio resterebbe fuori dalla coda per sempre.
        """
        _, finto, log = self._monitor([
            "applica-eventi", "--riprova-rifiutati", "--limit", "10"])
        finto.run_applica_eventi.assert_awaited_once_with(
            dry_run=False, limit=10, attivo=None, dal=None, tipi=(), offset=0,
            riprova_rifiutati=True,
        )
        log.warning.assert_not_called()

    def test_dal_malformata_exit_2(self):
        # Una data illeggibile passata avanti come stringa diventerebbe
        # «nessun filtro»: l'intero archivio invece del periodo d'ombra.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            codice, finto, _ = self._monitor(["applica-eventi", "--dal", "01/09/2026"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("--dal richiede una data AAAA-MM-GG", stderr.getvalue())
        finto.run_applica_eventi.assert_not_awaited()

    def test_tipi_opzione_scompone_e_ripulisce(self):
        self.assertEqual(cli._tipi_opzione("proroga, rettifica ,,chiusura"),
                         ("proroga", "rettifica", "chiusura"))
        self.assertEqual(cli._tipi_opzione(None), ())

    def test_ingresso_non_ancora_scritto_non_e_un_guasto(self):
        # `monitoraggio.py` esiste e oggi non espone `run_report_ombra`: e' la
        # tappa successiva del piano (exit 2 e nessun `logger.error`), non un
        # modulo rotto (exit 1).
        solo_run = types.ModuleType(f"{ALIAS}.monitoraggio")
        solo_run.run = AsyncMock(return_value={})
        log = MagicMock()
        stderr = io.StringIO()
        with patch.dict(sys.modules, {f"{ALIAS}.monitoraggio": solo_run}), \
                patch.object(cli, "logger", log), contextlib.redirect_stderr(stderr):
            codice = cli.main(["report-ombra"])
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("non ancora disponibile", stderr.getvalue())
        self.assertIn("run_report_ombra()", stderr.getvalue())
        log.error.assert_not_called()
        log.exception.assert_not_called()


class TestBackfill(_ConRunnerFinti):
    """I tre lotti di §6.4: `pulisci-contenuto`, `rigenera`, `archivia-processed`."""

    def _esegui_backfill(self, argv: list[str]):
        finti = {
            nome: _modulo_finto(nome, ingressi=ingressi)
            for nome, ingressi in _MODULI_V11.items()
        }
        registro = {f"{ALIAS}.{nome}": modulo for nome, modulo in finti.items()}
        log = MagicMock()
        with patch.dict(sys.modules, registro), patch.object(cli, "logger", log):
            codice = cli.main(argv)
        return codice, finti, log

    def test_ogni_lotto_ha_il_proprio_ingresso(self):
        atteso = {
            "pulisci-contenuto": ("backfill", "run_pulisci_contenuto"),
            "rigenera": ("rigenera", "run_rigenera"),
            "archivia-processed": ("backfill", "run_archivia_processed"),
        }
        for cmd, (modulo, ingresso) in atteso.items():
            with self.subTest(cmd=cmd):
                codice, finti, _ = self._esegui_backfill([cmd, "--dry-run"])
                self.assertEqual(codice, cli.EXIT_OK)
                getattr(finti[modulo], ingresso).assert_awaited_once()

    def test_ombra_per_difetto_e_lotto(self):
        # Il lotto nomina la riga `pipeline_run.step='backfill:Lx'`: senza, i
        # crediti del backfill finirebbero nel tetto mensile del regime.
        codice, finti, log = self._esegui_backfill(
            ["pulisci-contenuto", "--limit", "115", "--lotto", "L7"],
        )
        self.assertEqual(codice, cli.EXIT_OK)
        finti["backfill"].run_pulisci_contenuto.assert_awaited_once_with(
            dry_run=False, limit=115, attivo=None, lotto="L7", offset=0,
        )
        log.warning.assert_not_called()

    def test_rigenera_malformati(self):
        codice, finti, log = self._esegui_backfill(
            ["rigenera", "--malformati", "--attivo", "--lotto", "L7", "--limit", "9"],
        )
        self.assertEqual(codice, cli.EXIT_OK)
        finti["rigenera"].run_rigenera.assert_awaited_once_with(
            dry_run=False, limit=9, attivo=True, lotto="L7", offset=0,
            malformati=True,
        )
        log.warning.assert_not_called()

    def test_archivia_processed_resta_in_ombra_senza_attivo(self):
        codice, finti, _ = self._esegui_backfill(["archivia-processed", "--limit", "408"])
        self.assertEqual(codice, cli.EXIT_OK)
        self.assertFalse(
            finti["backfill"].run_archivia_processed.await_args.kwargs["attivo"])

    def test_i_cinque_ingressi_esistono_davvero(self):
        # I moduli finti provano la riga di comando; questo prova che dietro
        # c'e' qualcosa. Senza, la CLI potrebbe restare verde per sempre
        # dicendo «non ancora disponibile» a ogni lotto.
        for modulo, ingressi in (
            ("monitoraggio", ("run_report_ombra", "run_applica_eventi")),
            ("rigenera", ("run_rigenera",)),
            ("backfill", ("run_pulisci_contenuto", "run_archivia_processed")),
        ):
            vero = carica_modulo(modulo)
            for ingresso in ingressi:
                with self.subTest(modulo=modulo, ingresso=ingresso):
                    funzione, motivo = cli._modulo_opzionale(
                        modulo, ingresso, ingresso_atteso=False)
                    self.assertEqual(motivo, "")
                    self.assertIs(funzione, getattr(vero, ingresso))

    def test_modulo_assente_exit_2(self):
        # Il messaggio «modulo assente» resta la tappa successiva del piano per
        # i lotti che verranno: exit 2, non 1, e nessun `logger.error`.
        log = MagicMock()
        stderr = io.StringIO()
        with patch.object(cli, "logger", log), contextlib.redirect_stderr(stderr):
            codice = cli._esegui_v11(
                "lotto-futuro", "run", [], modulo="lotto_che_non_esiste",
            )
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        self.assertIn("app/lotto_che_non_esiste.py assente", stderr.getvalue())
        log.error.assert_not_called()


#: Un valore valido per ogni opzione con valore del catalogo: serve a provarle
#: tutte su tutti i comandi senza inciampare nella validazione del valore
#: (`--campione 0` e `--dal 01/09/2026` sono rifiutati per conto loro).
_VALORE_VALIDO = {
    "--id": "42", "--lotto": "L7", "--enti": "enti.xlsx", "--campione": "100",
    "--tipo": "proroga", "--dal": "2026-09-01", "--offset": "800",
}

#: Quali opzioni con valore accetta ogni sottocomando v11. `--offset` ce l'hanno
#: i **sette** che scorrono una selezione a pagine; sugli altri era accettato e
#: buttato via in silenzio, con exit 0 e stderr vuoto, perche' la guardia delle
#: «opzioni non riconosciute» escludeva l'intero catalogo invece delle sole
#: opzioni del comando.
_OPZIONI_AMMESSE_DI = {
    "risolvi-fonte": {"--id", "--lotto", "--offset"},
    "oe-dettaglio": {"--id", "--offset"},
    "link-verifica": {"--id", "--offset"},
    "fondi-doppioni": set(),
    # `--lotto` sul monitor sposta il giro sui tetti del backfill: la semina
    # delle impronte passa dal modello su ogni riga (al primo controllo non
    # esiste un «prima») e i trenta del regime bastano per trenta bandi.
    "monitor": {"--lotto"},
    "report-ombra": {"--campione", "--tipo", "--dal"},
    "applica-eventi": {"--dal", "--tipo", "--offset"},
    "pulisci-contenuto": {"--lotto", "--offset"},
    "rigenera": {"--lotto", "--offset"},
    "archivia-processed": {"--lotto", "--offset"},
    "domini": {"--enti"},
}

#: comando -> (modulo finto, funzione di ingresso) dei sottocomandi v11.
_INGRESSO_DI = {
    "risolvi-fonte": ("fonte_ufficiale", "run"),
    "oe-dettaglio": ("fonte_ufficiale", "run_oe_dettaglio"),
    "link-verifica": ("fonte_ufficiale", "run_link_verifica"),
    "fondi-doppioni": ("fonte_ufficiale", "run_fondi_doppioni"),
    "domini": ("fonte_ufficiale", "run_domini_import"),
    "monitor": ("monitoraggio", "run"),
    "report-ombra": ("monitoraggio", "run_report_ombra"),
    "applica-eventi": ("monitoraggio", "run_applica_eventi"),
    "rigenera": ("rigenera", "run_rigenera"),
    "pulisci-contenuto": ("backfill", "run_pulisci_contenuto"),
    "archivia-processed": ("backfill", "run_archivia_processed"),
}

#: I sette che scorrono la selezione a pagine, e che l'offset lo usano davvero.
_CON_OFFSET = tuple(
    cmd for cmd, ammesse in _OPZIONI_AMMESSE_DI.items() if "--offset" in ammesse
)


def _argv_con(cmd: str, opzione: str) -> list[str]:
    """`cmd --dry-run [--import] <opzione> <valore valido>`."""
    argv = [cmd, "--dry-run"]
    if cmd == "domini":
        # `--import` e' l'unica modalita' prevista: senza, il comando si ferma
        # per un altro motivo e la prova non misurerebbe piu' niente.
        argv.append("--import")
    return argv + [opzione, _VALORE_VALIDO[opzione]]


class TestOpzioniConValorePerComando(_ConRunnerFinti):
    """`--offset` (e le altre opzioni con valore) valgono solo dove servono.

    `OPZIONI_CON_VALORE` era un insieme unico e globale e `_esegui_v11` toglieva
    dagli «ignorati» qualunque token vi comparisse: `fondi-doppioni --dry-run
    --offset 800` usciva 0 con stderr vuoto e con `{"dry_run": True, "limit":
    None, "attivo": None}`, cioe' senza offset. Un operatore che lancia i
    blocchi (`--offset 0`, `800`, `1600`) credeva di avanzare e ripeteva lo
    stesso giro.
    """

    def _lancia(self, argv: list[str]):
        """main(argv) con i moduli v11 finti. Ritorna (codice, stderr, ingresso)."""
        finti = {
            nome: _modulo_finto(nome, ingressi=ingressi)
            for nome, ingressi in _MODULI_V11.items()
        }
        registro = {f"{ALIAS}.{nome}": modulo for nome, modulo in finti.items()}
        stderr = io.StringIO()
        with patch.dict(sys.modules, registro), patch.object(cli, "logger", MagicMock()):
            with contextlib.redirect_stderr(stderr):
                codice = cli.main(argv)
        modulo, funzione = _INGRESSO_DI[argv[0]]
        return codice, stderr.getvalue(), getattr(finti[modulo], funzione)

    def _rifiuta_offset(self, cmd: str):
        """Il comando si ferma su `--offset` e il suo runner non parte."""
        codice, stderr, ingresso = self._lancia(_argv_con(cmd, "--offset"))
        self.assertEqual(codice, cli.EXIT_OPZIONI)
        # Il messaggio dice QUALE opzione non conosce: «opzioni non
        # riconosciute» da solo non basta a chi ha appena scritto tre blocchi.
        self.assertIn("--offset", stderr)
        self.assertIn("opzioni non riconosciute", stderr)
        # E il valore non diventa un secondo token ignoto: 800 non compare.
        self.assertNotIn("800", stderr)
        ingresso.assert_not_awaited()

    def test_fondi_doppioni_rifiuta_offset(self):
        # Legge il corpus intero e confronta le righe fra loro: impaginare
        # spezzerebbe le coppie. Il runbook lo dice gia' («non lo ha e non deve
        # averlo»), la riga di comando no.
        self._rifiuta_offset("fondi-doppioni")

    def test_monitor_rifiuta_offset(self):
        # La coda del monitor la ordina la cadenza, non un cursore dell'operatore.
        self._rifiuta_offset("monitor")

    def test_report_ombra_rifiuta_offset(self):
        # Il blocco lo sposta `--dal`, che e' un'altra cosa: con `--offset`
        # accettato e ignorato la misura restava sugli stessi eventi.
        self._rifiuta_offset("report-ombra")

    def test_domini_rifiuta_offset(self):
        # Ricompone ogni volta l'intera whitelist: non c'e' niente da scorrere.
        self._rifiuta_offset("domini")

    def test_i_sette_comandi_a_blocchi_continuano_ad_accettare_offset(self):
        self.assertEqual(len(_CON_OFFSET), 7)
        for cmd in _CON_OFFSET:
            with self.subTest(cmd=cmd):
                codice, stderr, ingresso = self._lancia(_argv_con(cmd, "--offset"))
                self.assertEqual(codice, cli.EXIT_OK, stderr)
                self.assertEqual(ingresso.await_args.kwargs["offset"], 800)

    def test_ogni_opzione_con_valore_vale_solo_dove_serve(self):
        # La matrice intera: 11 comandi x 7 opzioni. E' la difesa contro il
        # ritorno dell'insieme globale, e prende anche i casi minori dello
        # stesso difetto (`oe-dettaglio --lotto L2`, che il comando non
        # conosce e che manderebbe la riga di telemetria nel passo sbagliato).
        for cmd, ammesse in _OPZIONI_AMMESSE_DI.items():
            for opzione in sorted(cli.OPZIONI_CON_VALORE):
                with self.subTest(cmd=cmd, opzione=opzione):
                    codice, stderr, _ = self._lancia(_argv_con(cmd, opzione))
                    if opzione in ammesse:
                        self.assertEqual(codice, cli.EXIT_OK, stderr)
                    else:
                        self.assertEqual(codice, cli.EXIT_OPZIONI, stderr)
                        self.assertIn(opzione, stderr)

    def test_la_matrice_copre_i_comandi_v11_e_sta_nel_catalogo(self):
        # `salute` non passa da `_esegui_v11` (vedi TestSalute); tutti gli
        # altri sottocomandi v11 devono stare nella matrice, altrimenti un
        # comando nuovo potrebbe rinascere con l'insieme globale.
        self.assertEqual(set(_OPZIONI_AMMESSE_DI), _COMANDI_V11 - {"salute"})
        dichiarate: set[str] = set()
        for ammesse in _OPZIONI_AMMESSE_DI.values():
            dichiarate |= ammesse
        # Nessun refuso nei sette insiemi per comando, e nessuna opzione del
        # catalogo che non sia ammessa da nessuno: sarebbe ignorata ovunque.
        self.assertEqual(dichiarate, set(cli.OPZIONI_CON_VALORE))


class TestSalute(_ConRunnerFinti):
    def _stato(self, **kwargs):
        telemetria = carica_modulo("telemetria")
        return telemetria.Stato(**kwargs)

    def test_stato_sano_exit_0(self):
        stdout = io.StringIO()
        with patch.object(cli, "_stato_salute", return_value=self._stato()), \
                contextlib.redirect_stdout(stdout):
            codice, stderr, _, _ = self.esegui(["salute"])
        self.assertEqual(codice, 0)
        self.assertEqual(stderr, "")
        self.assertIn("nessun allarme", stdout.getvalue())

    def test_allarme_exit_1_su_stderr(self):
        with patch.object(cli, "_stato_salute", return_value=self._stato(login_oe_ok=False)):
            codice, stderr, _, _ = self.esegui(["salute"])
        self.assertEqual(codice, 1)
        self.assertIn("[ALLARME]", stderr)

    def test_json(self):
        stdout = io.StringIO()
        with patch.object(cli, "_stato_salute", return_value=self._stato(login_oe_ok=False)), \
                patch.object(cli, "logger", MagicMock()), \
                contextlib.redirect_stdout(stdout):
            codice = cli.main(["salute", "--json"])
        dati = json.loads(stdout.getvalue())
        self.assertEqual(codice, 1)
        self.assertEqual(dati["exit_code"], 1)
        self.assertEqual(len(dati["allarmi"]), 1)

    def test_offset_su_salute_e_avvisato_non_silenzioso(self):
        # `salute` non passa da `_esegui_v11`: sta sul percorso storico di
        # `discover` e degli altri quattro step, che avvisano e proseguono. Non
        # scorre nessuna selezione, quindi un `--offset` non puo' fargli
        # credere di aver avanzato un blocco; ma non deve nemmeno sparire in
        # silenzio, ed e' questo che il test tiene fermo (il warning finisce su
        # stderr: `logger.py` manda li' tutto da INFO in su).
        stdout = io.StringIO()
        with patch.object(cli, "_stato_salute", return_value=self._stato()), \
                contextlib.redirect_stdout(stdout):
            codice, _, _, log = self.esegui(["salute", "--offset", "800"])
        self.assertEqual(codice, 0)
        avvisi = [c.args for c in log.warning.call_args_list]
        self.assertEqual(len(avvisi), 1)
        self.assertIn("--offset", avvisi[0][-1])

    def test_salute_non_tocca_ne_db_ne_rete(self):
        # `_stato_salute` legge solo le impostazioni: se toccasse il DB, questo
        # test fallirebbe con le credenziali fittizie di tests/supporto.py.
        stato = cli._stato_salute()
        self.assertIn(stato.modalita_monitor, ("ombra", "attivo"))


if __name__ == "__main__":
    unittest.main()
