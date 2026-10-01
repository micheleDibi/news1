# -*- coding: utf-8 -*-
"""Guardie sul testo della migrazione 12 (`bando_v11_12_monitoraggio`).

La 12 apre ad anon una sola porta, `monitoraggio_catalogo(p_chiave)`, e il
pannello di BandoFit la chiama con la anon key, che sta nel bundle pubblico.
I difetti che contano non si vedono girando il sorvegliante:
- una tabella nuova senza REVOKE resta leggibile con la anon key, perché i
  privilegi di default del progetto danno ALL ad anon;
- un GRANT ad authenticated apre un appiglio che nessuno usa;
- un controllo del metodo spostato dopo quello della chiave rende la GET un
  oracolo;
- una chiave del riepilogo aggiunta per sbaglio esce verso il pannello.

Qui si controlla il TESTO dei due file. La prova vera (12, rollback, 12 su
Postgres 17 con i ruoli finti) si fa a mano ed è nel report del task.

`chiavi_busta()` estrae dal SQL le chiavi di primo livello che il catalogo
copia dal riepilogo: il test dello schema v1 (`riepilogo_salute`) la riusa per
confrontarle con `SCHEMA_V1`.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_riepilogo_sql
"""
import re
import unittest

from tests.supporto import REPO

SQL = REPO / "backend" / "sql"
MIGRAZIONE_12 = SQL / "bando_v11_12_monitoraggio.sql"
ROLLBACK_12 = SQL / "bando_v11_12_monitoraggio_rollback.sql"

#: Le 11 chiavi di primo livello di §9.1 del contratto del giro 2, senza
#: `consumo` (decisione del 30/09 sera), nell'ordine della busta.
CHIAVI_ATTESE: tuple[str, ...] = (
    "stato", "segnali", "non_misurati", "produttore", "giri", "controlli",
    "lavorazioni", "ingresso", "eventi", "da_verificare", "job_orario",
)

#: Nomi che non devono comparire in nulla che BandoFit legga (§1).
NOMI_VIETATI: tuple[str, ...] = (
    "edunews", "news1", "anthropic", "claude", "haiku", "firecrawl",
    "obiettivo", "indexnow", "supabase",
)

LARGHEZZA_MASSIMA = 45

_RE_COMMENTO = re.compile(r"--[^\n]*")
_RE_LETTERALE = re.compile(r"'(?:[^']|'')*'")
_RE_CHIAVE_BUSTA = re.compile(r"\br\.riepilogo\s*->\s*'([a-z_]+)'")


def testo(percorso) -> str:
    return percorso.read_text(encoding="utf-8")


def senza_commenti(sql: str) -> str:
    """Il SQL senza i commenti `--`. Nei due file nessun letterale contiene
    `--`, quindi basta togliere tutto da `--` a fine riga."""
    return _RE_COMMENTO.sub("", sql)


def chiavi_busta(sql: str | None = None) -> tuple[str, ...]:
    """Le chiavi di primo livello che `monitoraggio_catalogo` copia dal
    riepilogo, nell'ordine in cui il SQL le scrive.

    Le cerca nella forma `r.riepilogo -> '<chiave>'` (non `->>`) fuori dai
    commenti: è l'unico modo in cui la 12 copia una chiave nella busta.
    """
    if sql is None:
        sql = testo(MIGRAZIONE_12)
    return tuple(_RE_CHIAVE_BUSTA.findall(senza_commenti(sql)))


def _corpo_catalogo(sql: str) -> str:
    """Il corpo `$$ … $$` di `monitoraggio_catalogo`, senza commenti."""
    codice = senza_commenti(sql)
    inizio = codice.index("public.monitoraggio_catalogo(\n    p_chiave text)")
    apertura = codice.index("$$", inizio)
    return codice[apertura + 2:codice.index("$$", apertura + 2)]


class ChiaviDellaBusta(unittest.TestCase):

    def test_undici_chiavi_nell_ordine_di_9_1(self):
        self.assertEqual(chiavi_busta(), CHIAVI_ATTESE)

    def test_niente_consumo_nel_codice(self):
        self.assertNotIn("consumo", senza_commenti(testo(MIGRAZIONE_12)))

    def test_memoria_mai_nella_busta(self):
        self.assertNotIn("memoria", _corpo_catalogo(testo(MIGRAZIONE_12)))

    def test_helper_su_testo_passato(self):
        sql = "-- r.riepilogo -> 'finta'\n'a', r.riepilogo -> 'vera', r.riepilogo ->> 'no'"
        self.assertEqual(chiavi_busta(sql), ("vera",))


class Privilegi(unittest.TestCase):

    def setUp(self):
        self.codice = senza_commenti(testo(MIGRAZIONE_12))
        # Per i GRANT si guardano solo le istruzioni: i messaggi del blocco
        # di verifica ('V6: GRANT ad authenticated') non contano.
        self.istruzioni = _RE_LETTERALE.sub("''", self.codice)

    def _oggetti_creati(self, tipo: str) -> list[str]:
        modello = {
            "FUNCTION": r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+public\.(\w+)",
            "TABLE": r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+public\.(\w+)",
        }[tipo]
        return re.findall(modello, self.codice)

    def test_ogni_funzione_e_tabella_ha_una_revoke_che_nomina_anon(self):
        oggetti = [("FUNCTION", n) for n in self._oggetti_creati("FUNCTION")]
        oggetti += [("TABLE", n) for n in self._oggetti_creati("TABLE")]
        self.assertEqual(len(oggetti), 5, oggetti)
        for tipo, nome in oggetti:
            with self.subTest(oggetto=nome):
                self.assertRegex(
                    self.codice,
                    rf"REVOKE\s+ALL\s+ON\s+{tipo}\s+public\.{nome}\b[^;]*"
                    rf"\bFROM\b[^;]*\banon\b",
                )

    def test_nessun_grant_ad_authenticated(self):
        grant = re.findall(r"\bGRANT\b[^;]*;", self.istruzioni)
        self.assertTrue(grant)
        for istruzione in grant:
            with self.subTest(grant=istruzione):
                self.assertNotRegex(istruzione, r"\bauthenticated\b")

    def test_anon_esegue_solo_il_catalogo(self):
        grant_anon = [g for g in re.findall(r"\bGRANT\b[^;]*;", self.istruzioni)
                      if re.search(r"\banon\b", g)]
        self.assertEqual(len(grant_anon), 1, grant_anon)
        self.assertIn("public.monitoraggio_catalogo(text)", grant_anon[0])

    def test_funzioni_security_definer_con_search_path(self):
        for nome in ("monitoraggio_catalogo", "monitoraggio_job_orario"):
            with self.subTest(funzione=nome):
                self.assertRegex(
                    self.codice,
                    rf"FUNCTION\s+public\.{nome}\([^)]*\)\s*RETURNS jsonb\s+"
                    r"LANGUAGE plpgsql\s+\w+\s+SECURITY DEFINER\s+"
                    r"SET search_path = public, pg_temp",
                )


class MetodoPrimaDellaChiave(unittest.TestCase):

    def test_request_method_e_la_prima_istruzione(self):
        corpo = _corpo_catalogo(testo(MIGRAZIONE_12))
        dopo_begin = corpo[corpo.index("BEGIN") + len("BEGIN"):].lstrip()
        prima_istruzione = dopo_begin[:dopo_begin.index("END IF;")]
        self.assertTrue(prima_istruzione.startswith("IF "), prima_istruzione)
        self.assertIn("'request.method'", prima_istruzione)
        self.assertIn("'POST'", prima_istruzione)
        self.assertNotIn("p_chiave", prima_istruzione)

    def test_rifiuti_uniformi(self):
        corpo = _corpo_catalogo(testo(MIGRAZIONE_12))
        rifiuti = re.findall(r"RAISE EXCEPTION\s+'([^']*)'\s+USING ERRCODE = '(\w+)'", corpo)
        self.assertEqual(rifiuti, [("non autorizzato", "42501")] * 2)
        self.assertNotRegex(corpo, r"RAISE[^;]*p_chiave")


class TestoDeiFile(unittest.TestCase):

    def test_righe_di_al_massimo_45_caratteri(self):
        for percorso in (MIGRAZIONE_12, ROLLBACK_12):
            for numero, riga in enumerate(testo(percorso).split("\n"), 1):
                with self.subTest(file=percorso.name, riga=numero):
                    self.assertLessEqual(len(riga), LARGHEZZA_MASSIMA, riga)

    def test_nessun_segreto(self):
        segreti = (
            r"eyJ[A-Za-z0-9_-]{10,}",       # JWT
            r"\b[0-9a-fA-F]{64}\b",          # impronta o chiave esadecimale
            r"\\x[0-9a-fA-F]{16,}",          # bytea letterale
            r"\bsk-[A-Za-z0-9_-]{8,}",
            r"\bsb_(?:secret|publishable)_",
        )
        for percorso in (MIGRAZIONE_12, ROLLBACK_12):
            for modello in segreti:
                with self.subTest(file=percorso.name, modello=modello):
                    self.assertNotRegex(testo(percorso), modello)

    def test_nessun_nome_vietato_negli_identificatori(self):
        # Fuori da commenti e letterali restano solo parole chiave e
        # identificatori. Il letterale 'supabase_admin' della guardia di
        # ruolo copiata dalla 04 è un nome di ruolo, non un oggetto creato.
        for percorso in (MIGRAZIONE_12, ROLLBACK_12):
            codice = _RE_LETTERALE.sub("''", senza_commenti(testo(percorso))).lower()
            for nome in NOMI_VIETATI:
                with self.subTest(file=percorso.name, nome=nome):
                    self.assertNotIn(nome, codice)

    def test_rollback_toglie_tutti_gli_oggetti(self):
        codice = senza_commenti(testo(ROLLBACK_12))
        for oggetto in (
            r"DROP FUNCTION IF EXISTS\s+public\.monitoraggio_catalogo\(text\)",
            r"DROP FUNCTION IF EXISTS\s+public\.monitoraggio_job_orario\(\)",
            r"DROP TRIGGER IF EXISTS\s+monitoraggio_riepilogo_ora",
            r"DROP TABLE IF EXISTS\s+public\.monitoraggio_riepilogo;",
            r"DROP TABLE IF EXISTS\s+public\.monitoraggio_chiave;",
            r"DROP FUNCTION IF EXISTS\s+public\.monitoraggio_riepilogo_ora\(\)",
        ):
            with self.subTest(oggetto=oggetto):
                self.assertRegex(codice, oggetto)
        self.assertNotIn("CASCADE", codice)

    def test_verifica_non_inserisce_chiavi(self):
        codice = senza_commenti(testo(MIGRAZIONE_12))
        self.assertNotRegex(codice, r"INSERT\s+INTO\s+public\.monitoraggio_chiave")


if __name__ == "__main__":
    unittest.main()
