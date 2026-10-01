# -*- coding: utf-8 -*-
"""Guardie sul testo della migrazione 13 (`bando_v11_13_stato_da_verificare`).

La 13 aggiunge a `bando_controllo` le colonne che il passo `verifica-stato`
scrive (`db.COLONNE_LETTURA_STATO`) e crea `bando_stato_da_verificare`, gemella
di `stato_bando.stato_da_verificare` e di `statoDaVerificare` in TypeScript. I
difetti che contano non si vedono girando il passo:
- una colonna scritta dal codice ma assente dalla 13 fa scartare la scrittura
  da `aggiorna_lettura_stato` (che tace le colonne che lo schema non ha);
- un parametro della funzione SQL in un ordine diverso dai gemelli scambia due
  date senza nessun errore, perché i tipi coincidono;
- una GRANT di troppo ad anon espone il dettaglio interno della lettura.

Qui si controlla il TESTO dei due file. La prova vera (catena 01..12, 13, 07,
rollback, 13 su Postgres 17) si fa a mano ed è nel report del task.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_stato_da_verificare_sql
"""
import inspect
import re
import unittest

from tests.supporto import REPO, carica_modulo

db = carica_modulo("db")
stato_bando = carica_modulo("stato_bando")
date_validation = carica_modulo("date_validation")
segnali = carica_modulo("segnali")

SQL = REPO / "backend" / "sql"
MIGRAZIONE_13 = SQL / "bando_v11_13_stato_da_verificare.sql"
ROLLBACK_13 = SQL / "bando_v11_13_stato_da_verificare_rollback.sql"
GENERA_SQL = REPO / "tests" / "stato-bando" / "genera-sql.ts"

LARGHEZZA_MASSIMA = 45

#: Le colonne di `bando_controllo` che la vista legge, quindi le sole nuove
#: concesse ad anon (contratto §2.2 punto 3 con §19.2).
COLONNE_ANON: frozenset[str] = frozenset({
    "stato_letto", "stato_letto_su", "stato_letto_at", "stato_letto_metodo",
    "previsto_entro", "termine_indicato", "esaminato_attivo_at",
    "segnale_aggregatore_at", "termine_indicato_fonte",
})

_RE_COMMENTO = re.compile(r"--[^\n]*")
_RE_LETTERALE = re.compile(r"'(?:[^']|'')*'")


def testo(percorso) -> str:
    return percorso.read_text(encoding="utf-8")


def istruzioni(sql: str) -> str:
    """Il SQL senza commenti e senza letterali: restano parole chiave e nomi."""
    return _RE_LETTERALE.sub("''", _RE_COMMENTO.sub("", sql))


def colonne_aggiunte(sql: str) -> tuple[str, ...]:
    """Le colonne di `ADD COLUMN IF NOT EXISTS`, nell'ordine del file."""
    return tuple(re.findall(r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", istruzioni(sql)))


def parametri_sql(sql: str) -> tuple[tuple[str, str], ...]:
    """(nome, tipo) dei parametri di `bando_stato_da_verificare`, in ordine."""
    codice = _RE_COMMENTO.sub("", sql)
    m = re.search(
        r"CREATE OR REPLACE FUNCTION\s+public\.bando_stato_da_verificare\((.*?)\)\s*RETURNS",
        codice, re.S,
    )
    assert m, "firma di bando_stato_da_verificare non trovata"
    coppie = []
    for pezzo in m.group(1).split(","):
        parole = pezzo.split()
        coppie.append((parole[0], parole[1]))
    return tuple(coppie)


def ingressi_generatore() -> tuple[tuple[str, str], ...]:
    """`INGRESSI_CERTEZZA` di genera-sql.ts: l'ordine della chiamata del blocco CERTEZZA."""
    ts = testo(GENERA_SQL)
    m = re.search(r"const INGRESSI_CERTEZZA[^=]*=\s*\[(.*?)\];", ts, re.S)
    assert m, "INGRESSI_CERTEZZA non trovato in genera-sql.ts"
    return tuple(re.findall(r"\['(\w+)', '(\w+)'\]", m.group(1)))


class Colonne(unittest.TestCase):

    def test_la_13_aggiunge_esattamente_colonne_lettura_stato(self):
        self.assertEqual(colonne_aggiunte(testo(MIGRAZIONE_13)), db.COLONNE_LETTURA_STATO)
        self.assertEqual(len(db.COLONNE_LETTURA_STATO), 17)

    def test_il_rollback_le_toglie_tutte(self):
        tolte = re.findall(r"DROP COLUMN IF EXISTS\s+([a-z_]+)", istruzioni(testo(ROLLBACK_13)))
        self.assertEqual(set(tolte), set(db.COLONNE_LETTURA_STATO))
        self.assertEqual(len(tolte), len(db.COLONNE_LETTURA_STATO))

    def test_anon_riceve_solo_le_nove_colonne_della_vista(self):
        codice = istruzioni(testo(MIGRAZIONE_13))
        grant = re.findall(
            r"GRANT SELECT \(([^)]*)\)\s*ON TABLE public\.bando_controllo\s*TO anon;", codice,
        )
        self.assertEqual(len(grant), 1)
        self.assertEqual({c.strip() for c in grant[0].split(",")}, COLONNE_ANON)
        self.assertTrue(COLONNE_ANON <= set(db.COLONNE_LETTURA_STATO))


class Vincoli(unittest.TestCase):
    """I valori ammessi dai CHECK della 13 sono quelli che il codice scrive. Un
    valore nuovo in Python senza la 13 aggiornata fa fallire la scrittura con
    23514, che `verifica_stato` registra solo come warning: lo dice questo test."""

    @staticmethod
    def ammessi(colonna: str) -> tuple[str, ...]:
        codice = _RE_COMMENTO.sub("", testo(MIGRAZIONE_13))
        trovati = re.findall(rf"CHECK \({colonna} IN \(([^)]*)\)\)", codice)
        assert len(trovati) == 1, (colonna, trovati)
        return tuple(re.findall(r"'([^']*)'", trovati[0]))

    def test_check_uguali_alle_costanti_python(self):
        for colonna, costante in (
            ("stato_letto", stato_bando.STATI_LETTI),
            ("stato_letto_metodo", stato_bando.METODI_LETTURA),
            ("termine_indicato_fonte", date_validation.FONTI_TERMINE),
            ("segnale_aggregatore", segnali.SEGNALI_AGGREGATORE),
        ):
            with self.subTest(colonna=colonna):
                self.assertEqual(self.ammessi(colonna), tuple(costante))


class Funzione(unittest.TestCase):

    def test_parametri_nell_ordine_del_generatore(self):
        parametri = parametri_sql(testo(MIGRAZIONE_13))
        attesi = tuple((f"p_{nome}", tipo) for nome, tipo in ingressi_generatore())
        self.assertEqual(len(attesi), 16)
        self.assertEqual(parametri, attesi)

    def test_parametri_nell_ordine_del_gemello_python(self):
        nomi_py = tuple(inspect.signature(stato_bando.stato_da_verificare).parameters)
        nomi_sql = tuple(nome.removeprefix("p_") for nome, _ in parametri_sql(testo(MIGRAZIONE_13)))
        # il gemello Python chiama «stato» il primo parametro, come la SQL
        self.assertEqual(nomi_sql, nomi_py)

    def test_adesso_ha_il_default(self):
        codice = _RE_COMMENTO.sub("", testo(MIGRAZIONE_13))
        self.assertIn("p_adesso timestamptz DEFAULT now())", codice)

    def test_pura_senza_tabelle(self):
        # Pura ma NON inlinabile: il corpo ha un FROM (la sottoselect con lo
        # stato effettivo, oggi e la lettura), quindi il planner la chiama
        # riga per riga. Qui si controlla solo che non legga tabelle.
        codice = _RE_COMMENTO.sub("", testo(MIGRAZIONE_13))
        corpo = codice[codice.index("public.bando_stato_da_verificare(\n    p_stato"):]
        corpo = corpo[:corpo.index("$$;")]
        self.assertIn("LANGUAGE sql", corpo)
        self.assertIn("STABLE", corpo)
        self.assertNotIn("SECURITY DEFINER", corpo)
        self.assertNotIn("SET search_path", corpo)
        # non legge tabelle: solo i suoi argomenti e bando_stato_effettivo
        self.assertNotRegex(corpo, r"FROM\s+public\.")


class Privilegi(unittest.TestCase):

    def setUp(self):
        self.codice = istruzioni(testo(MIGRAZIONE_13))

    def test_revoke_da_public_sulle_funzioni_nuove(self):
        for nome in ("bando_stato_da_verificare", "bando_lettura_verificante"):
            with self.subTest(funzione=nome):
                self.assertRegex(
                    self.codice,
                    rf"REVOKE ALL ON FUNCTION\s+public\.{nome}\([^;]*\)\s*FROM PUBLIC, anon, authenticated;",
                )

    def test_eseguibile_solo_da_anon_e_service_role(self):
        grant = re.findall(r"GRANT EXECUTE ON FUNCTION[^;]*;", self.codice)
        self.assertEqual(len(grant), 1, grant)
        self.assertIn("public.bando_stato_da_verificare(", grant[0])
        self.assertTrue(grant[0].rstrip(";").endswith("TO anon, service_role"))

    def test_nessun_grant_ad_authenticated(self):
        for istruzione in re.findall(r"\bGRANT\b[^;]*;", self.codice):
            with self.subTest(grant=istruzione):
                self.assertNotRegex(istruzione, r"\bauthenticated\b")

    def test_la_funzione_del_trigger_non_e_security_definer(self):
        codice = _RE_COMMENTO.sub("", testo(MIGRAZIONE_13))
        corpo = codice[codice.index("FUNCTION\n  public.bando_lettura_verificante()"):]
        corpo = corpo[:corpo.index("$$;")]
        self.assertNotIn("SECURITY DEFINER", corpo)


class Vista(unittest.TestCase):
    """Il termine indicato si scrive anche in ombra (`verifica_stato.colonne_lettura`):
    le tre viste che portano le colonne della 13 lo espongono solo dopo il primo
    esame in attivo (revisione avversaria, P1). La prova su Postgres 17 è nel
    report del task; qui il testo, che un rifacimento della vista non perda la
    condizione in uno solo dei tre file."""

    TERMINE = (
        "(SELECT CASE WHEN c.esaminato_attivo_at IS NOT NULL THEN c.termine_indicato END"
        " FROM public.bando_controllo c WHERE c.bando_id = b.id) AS termine_indicato,"
    )
    FONTE = (
        "(SELECT CASE WHEN c.termine_indicato IS NOT NULL AND c.esaminato_attivo_at IS NOT NULL"
        " THEN c.termine_indicato_fonte END"
        " FROM public.bando_controllo c WHERE c.bando_id = b.id) AS termine_indicato_fonte"
    )

    def test_termine_e_fonte_solo_dopo_l_esame_in_attivo(self):
        for nome in ("bando_v11_13_stato_da_verificare.sql", "bando_v11_07_fase_d.sql",
                     "bando_v11_07_fase_d_rollback.sql"):
            with self.subTest(file=nome):
                codice = " ".join(istruzioni(testo(SQL / nome)).split())
                self.assertEqual(codice.count(self.TERMINE), 1)
                self.assertEqual(codice.count(self.FONTE), 1)
                self.assertEqual(len(re.findall(r"\bAS termine_indicato\b", codice)), 1)
                self.assertEqual(len(re.findall(r"\bAS termine_indicato_fonte\b", codice)), 1)


class TestoDeiFile(unittest.TestCase):

    def test_righe_di_al_massimo_45_caratteri(self):
        for percorso in (MIGRAZIONE_13, ROLLBACK_13):
            for numero, riga in enumerate(testo(percorso).split("\n"), 1):
                with self.subTest(file=percorso.name, riga=numero):
                    self.assertLessEqual(len(riga), LARGHEZZA_MASSIMA, riga)

    def test_guardia_sulla_12_e_sulla_07(self):
        codice = testo(MIGRAZIONE_13)
        self.assertIn("'public.monitoraggio_riepilogo')", codice)
        self.assertIn("'la 07 è applicata (la vista non ha '", codice)
        self.assertIn("'la 07 è applicata: eseguire prima '", testo(ROLLBACK_13))


if __name__ == "__main__":
    unittest.main()
