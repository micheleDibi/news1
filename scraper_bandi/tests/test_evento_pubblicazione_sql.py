# -*- coding: utf-8 -*-
"""Guardie sul testo della migrazione 08 (`bando_v11_08_evento_pubblicazione`).

Il difetto che la 08 chiude e' stato introdotto due volte in questo progetto,
sempre nello stesso modo: un trigger dichiarato `AFTER UPDATE OF <colonna>`
che non scatta mai, perche' `UPDATE OF` guarda la SET list del comando e non
il valore finale — e `bando.pubblicato` non lo scrive chi fa l'UPDATE, lo alza
il trigger BEFORE della 01. Nessuno di questi errori si vede girando il
worker: il bando viene pubblicato lo stesso, semplicemente l'evento non nasce
e il flusso del cursore resta muto. Si vede solo contando le righe settimane
dopo (2124 pubblicati, 2114 eventi).

Qui si controlla il TESTO del file, che e' l'unica cosa verificabile senza un
PostgreSQL: che il trigger abbia la forma collaudata, che i valori dell'evento
siano gli stessi del backfill 8.b della 02, e che il rollback non cancelli gli
eventi gia' emessi.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import re
import unittest

from tests.supporto import REPO

SQL = REPO / "backend" / "sql"
MIGRAZIONE_02 = SQL / "bando_v11_02_tabelle_di_servizio.sql"
MIGRAZIONE_08 = SQL / "bando_v11_08_evento_pubblicazione.sql"
ROLLBACK_08 = SQL / "bando_v11_08_evento_pubblicazione_rollback.sql"

#: Il nome del trigger e quello della funzione, citati ovunque qui sotto.
TRIGGER = "trg_bando_evento_pubblicazione"
FUNZIONE = "bando_evento_pubblicazione"


def testo(percorso) -> str:
    return percorso.read_text(encoding="utf-8")


def senza_commenti(sql: str) -> str:
    """Le sole righe eseguibili: i commenti `--` citano le forme sbagliate."""
    return "\n".join(
        riga for riga in sql.splitlines() if not riga.lstrip().startswith("--")
    )


def blocco_create_trigger(sql: str, nome: str) -> str:
    """Il `CREATE TRIGGER <nome> … ;` come testo, commenti esclusi."""
    corpo = senza_commenti(sql)
    inizio = corpo.index(f"CREATE TRIGGER {nome}")
    return corpo[inizio:corpo.index(";", inizio)]


class FormaDelTrigger(unittest.TestCase):
    """`AFTER UPDATE OF pubblicato` sarebbe un no-op silenzioso."""

    def setUp(self):
        self.blocco = blocco_create_trigger(testo(MIGRAZIONE_08), TRIGGER)

    def test_scatta_anche_sull_insert(self):
        # Una riga scritta gia' `completed` con slug viene pubblicata dal
        # trigger BEFORE della 01 senza passare da nessun UPDATE.
        self.assertIn("AFTER INSERT OR UPDATE ON public.bando", self.blocco)

    def test_nessuna_lista_di_colonne(self):
        # `UPDATE OF pubblicato` guarda la SET list, non il valore finale.
        self.assertNotIn("UPDATE OF", self.blocco)

    def test_la_when_non_nomina_old(self):
        # Su INSERT `OLD` non esiste: PostgreSQL rifiuta il CREATE TRIGGER.
        # La meta' mancante della condizione sta nel corpo della funzione.
        when = self.blocco[self.blocco.index("WHEN ("):]
        self.assertNotIn("OLD", when)
        self.assertIn("WHEN (NEW.pubblicato)", self.blocco)

    def test_la_funzione_esclude_le_righe_gia_pubblicate(self):
        corpo = senza_commenti(testo(MIGRAZIONE_08))
        self.assertIn("TG_OP = 'UPDATE' AND OLD.pubblicato", corpo)

    def test_scatta_prima_di_promuovi_eventi(self):
        # I trigger AFTER scattano in ordine alfabetico: l'evento
        # `pubblicazione` deve prendere il cursore piu' basso, altrimenti un
        # consumatore riceve notizie su un bando che non conosce ancora.
        self.assertLess(TRIGGER, "trg_bando_promuovi_eventi")
        self.assertGreater(TRIGGER, "trg_bando_crea_controllo")


class ValoriDellEvento(unittest.TestCase):
    """Gli stessi valori del backfill 8.b della 02: e' la stessa riga."""

    def setUp(self):
        self.otto = senza_commenti(testo(MIGRAZIONE_08))

    def test_le_colonne_sono_quelle_del_backfill(self):
        colonne = ("bando_id, tipo, origine, data_evento, rilevato_at,\n"
                   "       leggibile, in_aggiornamenti, verificato")
        self.assertIn(colonne.replace("\n       ", " ").replace("  ", " "),
                      re.sub(r"\s+", " ", self.otto))

    def test_origine_pipeline(self):
        self.assertIn("'pipeline'", self.otto)
        for altra in ("'cron'", "'worker'", "'redazione'"):
            self.assertNotIn(altra, self.otto)

    def test_data_evento_nel_fuso_di_roma(self):
        # `timestamptz::date` dipenderebbe da TimeZone.
        self.assertEqual(self.otto.count("AT TIME ZONE 'Europe/Rome'"), 2)

    def test_nessuna_prova_e_niente_box_aggiornamenti(self):
        self.assertNotIn("url_prova", self.otto)
        # I tre booleani, nell'ordine leggibile / in_aggiornamenti / verificato.
        compatto = re.sub(r"\s+", " ", self.otto)
        self.assertIn("true, false, false", compatto)

    def test_il_cursore_non_si_scrive_dall_esterno(self):
        # Lo assegna `a_evento_cursore` sotto advisory lock; scriverlo fa
        # scattare `a0_evento_cursore_non_esterno` (23514). Si guardano le
        # liste di colonne dei due INSERT, non tutto il file: «cursore»
        # compare anche nelle precondizioni, ed e' giusto che ci sia.
        liste = re.findall(r"INSERT INTO public\.bando_evento\s*\(([^)]*)\)", self.otto)
        self.assertEqual(len(liste), 2, "attesi due INSERT: il trigger e il recupero")
        for lista in liste:
            colonne = {c.strip() for c in lista.split(",")}
            self.assertNotIn("cursore", colonne)
            self.assertNotIn("pubblicato_at", colonne)
            self.assertNotIn("dominio_prova", colonne)   # colonna generata: 428C9

    def test_non_duplica_se_l_evento_esiste(self):
        compatto = re.sub(r"\s+", " ", self.otto)
        self.assertIn("NOT EXISTS", compatto)
        self.assertIn("e.tipo = 'pubblicazione'", compatto)
        self.assertIn("ON CONFLICT DO NOTHING", compatto)

    def test_il_tipo_e_nell_allowlist_dei_pubblici(self):
        # Senza, l'evento nascerebbe `leggibile = false` e senza cursore:
        # lo stesso silenzio di prima, ma piu' difficile da vedere.
        allowlist = testo(MIGRAZIONE_02)
        inizio = allowlist.index("FUNCTION public.bando_evento_tipo_pubblico(")
        self.assertIn("'pubblicazione'", allowlist[inizio:inizio + 900])


class IgieneDelFile(unittest.TestCase):
    """Le regole che valgono per ogni migrazione della serie v11."""

    def setUp(self):
        self.otto = testo(MIGRAZIONE_08)
        self.eseguibile = senza_commenti(self.otto)

    def test_transazione_unica(self):
        self.assertTrue(self.eseguibile.lstrip().startswith("BEGIN;"))
        self.assertIn("COMMIT;", self.eseguibile)

    def test_rieseguibile(self):
        self.assertIn(f"CREATE OR REPLACE FUNCTION public.{FUNZIONE}()", self.eseguibile)
        self.assertIn(f"DROP TRIGGER IF EXISTS {TRIGGER} ON public.bando;", self.eseguibile)
        self.assertLess(self.eseguibile.index(f"DROP TRIGGER IF EXISTS {TRIGGER}"),
                        self.eseguibile.index(f"CREATE TRIGGER {TRIGGER}"))

    def test_revoca_i_privilegi_di_default(self):
        # I default del progetto concedono ALL ad anon e authenticated: una
        # SECURITY DEFINER eseguibile con la anon key scriverebbe eventi.
        self.assertIn(
            f"REVOKE ALL ON FUNCTION public.{FUNZIONE}() FROM PUBLIC, anon, authenticated;",
            self.eseguibile)
        self.assertNotIn(f"GRANT EXECUTE ON FUNCTION public.{FUNZIONE}", self.eseguibile)

    def test_non_riscrive_nessuna_riga_di_bando(self):
        # L'unico INSERT e' su `bando_evento`; nessun UPDATE su `bando`, e
        # l'impronta di `updated_at` lo dimostra in transazione.
        self.assertNotIn("UPDATE public.bando", self.eseguibile)
        self.assertIn("_v11_08_impronta", self.eseguibile)
        self.assertIn("ha mosso updated_at", self.eseguibile)

    def test_non_aggiunge_colonne(self):
        self.assertNotIn("ADD COLUMN", self.eseguibile)

    def test_la_pubblicazione_non_fallisce_mai_per_colpa_dell_evento(self):
        self.assertIn("EXCEPTION WHEN OTHERS THEN", self.eseguibile)
        self.assertIn("RAISE WARNING", self.eseguibile)

    def test_dichiara_le_precondizioni(self):
        intestazione = self.otto[:self.otto.index("BEGIN;")]
        for atteso in ("Scopo", "Fase", "Precondizioni", "Rompe BandoFit?",
                       "Come si applica", "NON È REVERSIBILE"):
            self.assertIn(atteso, intestazione)
        self.assertIn("bando_v11_01_pubblicazione.sql", intestazione)
        self.assertIn("bando_v11_02_tabelle_di_servizio.sql", intestazione)


class Rollback(unittest.TestCase):
    """Un cursore assegnato non si revoca: gli eventi restano."""

    def setUp(self):
        self.testo = testo(ROLLBACK_08)
        self.eseguibile = senza_commenti(self.testo)

    def test_toglie_solo_trigger_e_funzione(self):
        self.assertIn(f"DROP TRIGGER IF EXISTS {TRIGGER} ON public.bando;", self.eseguibile)
        self.assertIn(f"DROP FUNCTION IF EXISTS public.{FUNZIONE}();", self.eseguibile)

    def test_non_cancella_gli_eventi(self):
        # `DELETE` su bando_evento e' revocato perfino a service_role, e un
        # consumatore puo' aver gia' letto quei cursori.
        self.assertNotIn("DELETE", self.eseguibile.upper())
        self.assertNotIn("TRUNCATE", self.eseguibile.upper())

    def test_lo_dichiara_nell_intestazione(self):
        intestazione = self.testo[:self.testo.index("BEGIN;")]
        self.assertIn("NON È REVERSIBILE", intestazione)
        self.assertIn("NON VENGONO CANCELLATI", intestazione)


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
