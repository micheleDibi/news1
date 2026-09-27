# -*- coding: utf-8 -*-
"""Guardie sul testo della migrazione 11 (`bando_v11_11_traduzione_stato_proposto`).

Il difetto che la 11 chiude non si vede girando il worker. In ombra, con
`MONITOR_STATI_ESTESI` falso, il monitor registra sospensioni e revoche con
`valore_dopo = {"stato_proposto": …}` (A30). `bando_applica_evento` della 04,
però, tiene solo sei chiavi, tra cui `stato_bando`. Su quegli eventi trova
`campi = {}`, li marca `applicato=true` e restituisce true: la colonna non
cambia, `applica-eventi` li conta come applicati e li rende leggibili, e
`valore_dopo` è immutabile. L'evento è bruciato per sempre.

Qui si controlla il TESTO dei file: che la funzione della 11 sia quella
della 04 più un solo blocco, che quel blocco traduca solo le due coppie
prodotte dal monitor, che il marcatore letto dalla guardia di
`applica-eventi` abbia gli stessi nomi del codice Python, e che il rollback
rimetta la 04 byte per byte.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_traduzione_stato_proposto_sql
"""
import re
import unittest

from tests.supporto import REPO, carica_modulo

db = carica_modulo("db")
eventi = carica_modulo("eventi")
monitoraggio = carica_modulo("monitoraggio")

SQL = REPO / "backend" / "sql"
MIGRAZIONE_04 = SQL / "bando_v11_04_transizioni.sql"
MIGRAZIONE_06 = SQL / "bando_v11_06_stati_cinque.sql"
MIGRAZIONE_11 = SQL / "bando_v11_11_traduzione_stato_proposto.sql"
ROLLBACK_11 = SQL / "bando_v11_11_traduzione_stato_proposto_rollback.sql"

FIRMA = "CREATE OR REPLACE FUNCTION public.bando_applica_evento(p_evento_id bigint)"
INTESTAZIONE = (
    FIRMA + "\n"
    "RETURNS boolean\n"
    "LANGUAGE plpgsql\n"
    "SECURITY DEFINER\n"
    "SET search_path = public, pg_temp\n"
    "AS $$\n"
)
INIZIO_BLOCCO = "  -- >>> v11_11"
FINE_BLOCCO = "  -- <<< v11_11\n"


def testo(percorso) -> str:
    return percorso.read_text(encoding="utf-8")


def senza_commenti(sql: str) -> str:
    """Le sole righe eseguibili: i commenti `--` citano anche le forme sbagliate."""
    return "\n".join(
        riga for riga in sql.splitlines() if not riga.lstrip().startswith("--")
    )


def definizione(sql: str, firma: str = FIRMA) -> str:
    """Dalla `CREATE OR REPLACE FUNCTION` al `$$;` che la chiude."""
    inizio = sql.index(firma)
    fine = sql.index("\n$$;", inizio) + len("\n$$;")
    return sql[inizio:fine]


def corpo(sql: str, firma: str = FIRMA) -> str:
    """Il testo fra `AS $$` e `$$;`: è ciò che finisce in `pg_proc.prosrc`."""
    tutta = definizione(sql, firma)
    inizio = tutta.index("AS $$\n") + len("AS $$\n")
    return tutta[inizio:tutta.rindex("$$;")]


def commento_della_funzione(sql: str) -> str:
    inizio = sql.index("COMMENT ON FUNCTION public.bando_applica_evento(bigint) IS")
    return sql[inizio:sql.index(";", sql.index("'", inizio) + 1) + 1]


def blocco_v11_11(sql: str) -> str:
    """Il blocco aggiunto dalla 11, righe di delimitazione comprese."""
    corpo_11 = corpo(sql)
    inizio = corpo_11.index(INIZIO_BLOCCO)
    fine = corpo_11.index(FINE_BLOCCO, inizio) + len(FINE_BLOCCO)
    return corpo_11[inizio:fine]


def fuori_dai_corpi(sql: str) -> str:
    """Il file senza i corpi `$$ … $$`: le istruzioni che il file esegue da sé."""
    return re.sub(r"\$\$.*?\$\$", "$$…$$", senza_commenti(sql), flags=re.DOTALL)


class IlDifettoEsiste(unittest.TestCase):
    """Se questi falliscono, la 04 è cambiata e la 11 va ripensata."""

    def test_la_04_non_conosce_stato_proposto(self):
        self.assertNotIn("stato_proposto", corpo(testo(MIGRAZIONE_04)))

    def test_la_04_tiene_solo_sei_chiavi(self):
        corpo_04 = corpo(testo(MIGRAZIONE_04))
        self.assertIn(
            "WHERE k NOT IN ('stato_bando', 'data_pubblicazione',\n"
            "                     'data_apertura', 'ora_apertura',\n"
            "                     'data_scadenza', 'ora_scadenza')",
            corpo_04)

    def test_il_monitor_scrive_davvero_stato_proposto_in_ombra(self):
        evento = eventi.Evento(tipo="sospensione", citazione="sospeso")
        ctx = eventi.Contesto(bando_id=1, stato_bando="aperto", stati_estesi=False)
        giudizio = eventi.Giudizio(ammesso=True, nuovo_stato="sospeso")
        riga = eventi.riga_evento(evento, ctx, giudizio)
        self.assertEqual(riga["valore_dopo"], {"stato_proposto": "sospeso"})


class LaFunzioneEQuellaDella04PiuUnBlocco(unittest.TestCase):

    def setUp(self):
        self.sql_04 = testo(MIGRAZIONE_04)
        self.sql_11 = testo(MIGRAZIONE_11)

    def test_stessa_intestazione(self):
        # Stessa firma: una firma diversa creerebbe un overload e renderebbe
        # ambigua la chiamata dentro `bando_registra_evento` (04:719).
        self.assertIn(INTESTAZIONE, self.sql_04)
        self.assertIn(INTESTAZIONE, self.sql_11)
        self.assertEqual(self.sql_11.count(FIRMA), 1)

    def test_tolto_il_blocco_il_corpo_e_identico(self):
        corpo_11 = corpo(self.sql_11)
        blocco = blocco_v11_11(self.sql_11)
        # Il blocco è seguito da una riga vuota, che va via con lui.
        self.assertIn(blocco + "\n", corpo_11)
        self.assertEqual(corpo_11.replace(blocco + "\n", "", 1), corpo(self.sql_04))

    def test_un_solo_blocco(self):
        self.assertEqual(corpo(self.sql_11).count(INIZIO_BLOCCO), 1)
        self.assertEqual(corpo(self.sql_11).count(FINE_BLOCCO), 1)

    def test_il_blocco_sta_fra_il_filtro_delle_chiavi_e_il_ramo_senza_effetto(self):
        corpo_11 = corpo(self.sql_11)
        filtro = corpo_11.index("WHERE k NOT IN ('stato_bando'")
        blocco = corpo_11.index(INIZIO_BLOCCO)
        senza_effetto = corpo_11.index("IF campi = '{}'::jsonb THEN")
        self.assertLess(filtro, blocco)
        self.assertLess(blocco, senza_effetto)

    def test_il_ramo_del_check_prima_della_06_e_intatto(self):
        # È ciò che rende la 11 innocua prima della 06: il CHECK a tre valori
        # rifiuta `sospeso`, e l'evento resta NON applicato.
        corpo_11 = corpo(self.sql_11)
        self.assertIn("EXCEPTION WHEN check_violation THEN", corpo_11)
        self.assertIn(
            "IF campi ? 'stato_bando' AND stato_nuovo IN ('sospeso', 'revocato') THEN",
            corpo_11)


class IlBloccoTraduceSoloLeDueCoppie(unittest.TestCase):

    def setUp(self):
        self.blocco = senza_commenti(blocco_v11_11(testo(MIGRAZIONE_11)))

    def coppie(self) -> dict[str, str]:
        return dict(re.findall(
            r"e\.tipo = '([a-z_]+)'\s+AND e\.valore_dopo ->> 'stato_proposto' = '([a-z_]+)'",
            self.blocco))

    def test_le_coppie_sono_quelle_del_codice_python(self):
        self.assertEqual(self.coppie(), dict(monitoraggio.TRADUZIONI_STATO_PROPOSTO))
        self.assertEqual(self.coppie(), {"sospensione": "sospeso", "revoca": "revocato"})

    def test_le_coppie_sono_quelle_della_macchina_a_stati(self):
        for tipo, stato in self.coppie().items():
            self.assertEqual(
                eventi.transizione_evento("aperto", eventi.Evento(tipo=tipo)), stato)

    def test_solo_sugli_oggetti_e_mai_sopra_uno_stato_esplicito(self):
        self.assertIn("jsonb_typeof(e.valore_dopo) = 'object'", self.blocco)
        self.assertIn("NOT (campi ? 'stato_bando')", self.blocco)

    def test_scrive_solo_stato_bando(self):
        self.assertIn(
            "campi := campi || jsonb_build_object('stato_bando', "
            "e.valore_dopo ->> 'stato_proposto');",
            self.blocco)
        self.assertEqual(self.blocco.count("campi :="), 1)


class Marcatore(unittest.TestCase):
    """La guardia di `applica-eventi` lo chiama: nomi e chiavi devono coincidere."""

    def setUp(self):
        self.sql_11 = testo(MIGRAZIONE_11)
        self.definizione = definizione(
            self.sql_11, f"CREATE OR REPLACE FUNCTION public.{db.RPC_CAPACITA_EVENTI}()")

    def test_nome_e_chiavi_coincidono_con_db(self):
        self.assertEqual(db.RPC_CAPACITA_EVENTI, "bando_capacita_eventi")
        self.assertIn(f"'{db.CAPACITA_TRADUZIONE}'", self.definizione)
        self.assertIn(f"'{db.CAPACITA_STATI_CINQUE}'", self.definizione)

    def test_legge_il_corpo_vivo_della_funzione(self):
        # La 04 è rieseguibile: se qualcuno la rilancia dopo la 11, la
        # traduzione sparisce e il marcatore deve dirlo. Per questo legge
        # `prosrc` e non si limita a esistere.
        self.assertIn("pg_catalog.pg_proc", self.definizione)
        self.assertIn("position('stato_proposto' IN p.prosrc) > 0", self.definizione)
        self.assertIn("to_regprocedure('public.bando_applica_evento(bigint)')",
                      self.definizione)

    def test_riconosce_il_check_della_06(self):
        # Esclude per nome gli stessi due CHECK che la 06 non tocca.
        self.assertIn("'bando_pubblicato_implica_completed', 'bando_provenienza_stato'",
                      self.definizione)
        self.assertIn("ILIKE '%in apertura prossimamente%'", self.definizione)
        self.assertIn("ILIKE '%''sospeso''%'", self.definizione)
        self.assertIn("ILIKE '%''revocato''%'", self.definizione)
        # Senza righe `bool_and` vale NULL: nel dubbio, falso.
        self.assertIn("coalesce(bool_and(", self.definizione)

    def test_la_06_crea_un_check_che_il_marcatore_riconosce(self):
        sql_06 = senza_commenti(testo(MIGRAZIONE_06))
        check = sql_06[sql_06.index("ADD CONSTRAINT bando_stato_bando_check"):]
        check = check[:check.index(";")]
        for valore in ("'in apertura prossimamente'", "'sospeso'", "'revocato'"):
            self.assertIn(valore, check)

    def test_non_scrive_niente(self):
        self.assertIn("LANGUAGE sql\nSTABLE\n", self.definizione)
        for verbo in ("UPDATE ", "INSERT ", "DELETE "):
            self.assertNotIn(verbo, senza_commenti(self.definizione))


class Privilegi(unittest.TestCase):

    def setUp(self):
        self.eseguibile = fuori_dai_corpi(testo(MIGRAZIONE_11))

    def test_solo_service_role(self):
        for funzione in ("public.bando_applica_evento(bigint)",
                         f"public.{db.RPC_CAPACITA_EVENTI}()"):
            self.assertIn(
                f"REVOKE ALL ON FUNCTION {funzione} FROM PUBLIC, anon, authenticated;",
                self.eseguibile)
            self.assertIn(f"GRANT EXECUTE ON FUNCTION {funzione} TO service_role;",
                          self.eseguibile)

    def test_nessun_grant_ad_anon_o_authenticated(self):
        for riga in self.eseguibile.splitlines():
            if riga.strip().startswith("GRANT"):
                self.assertNotIn("anon", riga)
                self.assertNotIn("authenticated", riga)

    def test_la_guardia_sul_ruolo_resta(self):
        self.assertIn(
            "session_user IN ('postgres','supabase_admin')", corpo(testo(MIGRAZIONE_11)))


class IgieneDelFile(unittest.TestCase):

    def setUp(self):
        self.sql = testo(MIGRAZIONE_11)
        self.eseguibile = fuori_dai_corpi(self.sql)

    def test_transazione_unica(self):
        self.assertEqual(self.eseguibile.count("BEGIN;"), 1)
        self.assertEqual(self.eseguibile.count("COMMIT;"), 1)
        self.assertIn("SET LOCAL lock_timeout = '5s';", self.eseguibile)

    def test_non_tocca_i_dati(self):
        for verbo in ("UPDATE ", "INSERT ", "DELETE ", "ALTER TABLE", "DROP "):
            self.assertNotIn(verbo, self.eseguibile)

    def test_pretende_la_04(self):
        # La guardia sta in un blocco `DO $$ … $$`: si cerca nel testo eseguibile
        # intero, non in quello senza i corpi.
        guardia = senza_commenti(self.sql)
        guardia = guardia[:guardia.index("CREATE OR REPLACE FUNCTION")]
        self.assertIn("bando_v11_04_transizioni.sql", guardia)
        self.assertIn("to_regprocedure('public.bando_applica_evento(bigint)') IS NULL",
                      guardia)

    def test_dichiara_precondizioni_e_verifica(self):
        for voce in ("Precondizioni", "Rompe BandoFit?", "Come si applica",
                     "Verifica post-deploy"):
            self.assertIn(voce, self.sql)


class Rollback(unittest.TestCase):

    def setUp(self):
        self.sql_04 = testo(MIGRAZIONE_04)
        self.rollback = testo(ROLLBACK_11)

    def test_rimette_la_funzione_della_04_byte_per_byte(self):
        self.assertEqual(definizione(self.rollback), definizione(self.sql_04))

    def test_rimette_il_commento_della_04(self):
        self.assertEqual(commento_della_funzione(self.rollback),
                         commento_della_funzione(self.sql_04))

    def test_toglie_il_marcatore(self):
        self.assertIn(f"DROP FUNCTION IF EXISTS public.{db.RPC_CAPACITA_EVENTI}();",
                      senza_commenti(self.rollback))

    def test_privilegi_come_nella_04(self):
        eseguibile = fuori_dai_corpi(self.rollback)
        self.assertIn(
            "REVOKE ALL ON FUNCTION public.bando_applica_evento(bigint) "
            "FROM PUBLIC, anon, authenticated;", eseguibile)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.bando_applica_evento(bigint) TO service_role;",
            eseguibile)

    def test_non_tocca_i_dati(self):
        eseguibile = fuori_dai_corpi(self.rollback)
        for verbo in ("UPDATE ", "INSERT ", "DELETE ", "ALTER TABLE"):
            self.assertNotIn(verbo, eseguibile)
        self.assertEqual(eseguibile.count("BEGIN;"), 1)
        self.assertEqual(eseguibile.count("COMMIT;"), 1)


if __name__ == "__main__":
    unittest.main()
