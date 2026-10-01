# -*- coding: utf-8 -*-
"""Guardie sul testo della migrazione 14 (`bando_v11_14_sospensioni`).

La 14 ridefinisce due funzioni che altre migrazioni hanno già scritto:
`bando_applica_evento` (04, poi 11) e il trigger `bando_stato_solo_via_evento`
(04). Le riscrive a righe di 45 caratteri, come le migrazioni dal giro 2, quindi
non può ricopiarle byte per byte: qui si controlla che, tolti i blocchi
`v11_14`, abbiano gli stessi TOKEN delle originali. I commenti non contano, gli
spazi nemmeno, e una stringa spezzata in letterali adiacenti su righe diverse
vale come la stringa intera (è la regola di PostgreSQL).

Si controlla anche che i blocchi stiano dove servono, che il marcatore letto da
`db.capacita_sospensioni()` abbia il nome e la forma giusti, che il rollback
rimetta la 11 e la 04, e che nessun privilegio nuovo arrivi ad anon.

Gli scenari veri (sospeso → chiuso, riapertura datata al passato,
annullamento_revoca, correzione della redazione, evento superato anche con una
data_evento nel futuro, proroga vera non superata da una chiusura, 23514
marcato, R1 e R2 della Riconciliazione: 86 controlli) sono stati provati su un
Postgres 17 effimero con la catena delle migrazioni vere, insieme a
rieseguibilita' e rollback: `docs/bandi-monitor/RIPRESA.md` §8.8, che dice anche
come ricostruire il banco.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_sospensioni_sql
"""
import re
import unittest

from tests.supporto import REPO, carica_modulo

db = carica_modulo("db")

SQL = REPO / "backend" / "sql"
MIGRAZIONE_04 = SQL / "bando_v11_04_transizioni.sql"
MIGRAZIONE_11 = SQL / "bando_v11_11_traduzione_stato_proposto.sql"
MIGRAZIONE_14 = SQL / "bando_v11_14_sospensioni.sql"
ROLLBACK_14 = SQL / "bando_v11_14_sospensioni_rollback.sql"

LARGHEZZA = 45
RPC = "bando_applica_evento"
TRIGGER = "bando_stato_solo_via_evento"
CORREGGI = "bando_correggi_stato"
MARCATORE = "bando_capacita_sospensioni"


def testo(percorso) -> str:
    return percorso.read_text(encoding="utf-8")


# --- un tokenizzatore SQL minimo ---------------------------------------------

_PAROLA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMERO = re.compile(r"\d+")
_OPERATORE = re.compile(r"[-+*/<>=~!@#%^&|`?:]+")


def token(sql: str) -> list[str]:
    """I token di un testo SQL: niente commenti `--`, niente spazi.

    Due letterali separati solo da spazi che contengono un a capo diventano
    uno solo, come fa PostgreSQL (`'ab'` a capo `'cd'` vale `'abcd'`). Le
    parole chiave restano come sono scritte: la riscrittura non deve cambiare
    neanche le maiuscole.
    """
    uscita: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i):
            fine = sql.find("\n", i)
            i = n if fine < 0 else fine
        elif c == "'":
            valore, i = _letterale(sql, i)
            while True:
                j = i
                while j < n and sql[j].isspace():
                    j += 1
                if j < n and sql[j] == "'" and "\n" in sql[i:j]:
                    seguito, i = _letterale(sql, j)
                    valore += seguito
                else:
                    break
            uscita.append("'" + valore + "'")
        elif sql.startswith("$$", i):
            uscita.append("$$")
            i += 2
        elif (m := _PAROLA.match(sql, i)):
            uscita.append(m.group())
            i = m.end()
        elif (m := _NUMERO.match(sql, i)):
            uscita.append(m.group())
            i = m.end()
        elif (m := _OPERATORE.match(sql, i)) and not sql.startswith("--", i):
            uscita.append(m.group())
            i = m.end()
        else:
            uscita.append(c)
            i += 1
    return uscita


def _letterale(sql: str, i: int) -> tuple[str, int]:
    """Il contenuto di `'…'` che parte in `i` (con `''` raddoppiato) e la fine."""
    j = i + 1
    pezzi = []
    while True:
        k = sql.index("'", j)
        pezzi.append(sql[j:k])
        if sql.startswith("''", k):
            pezzi.append("''")
            j = k + 2
            continue
        return "".join(pezzi), k + 1


def piatto(sql: str) -> str:
    """I token uniti da uno spazio: per cercare un frammento senza badare all'a capo."""
    return " ".join(token(sql))


def piegato(sql: str) -> str:
    """Come `piatto`, con le concatenazioni di costanti (`'a' || 'b'`) già fatte:
    le firme dentro `to_regprocedure` sono spezzate così per stare in 45 colonne."""
    p = piatto(sql)
    while True:
        nuovo = re.sub(r"'([^']*)' \|\| '([^']*)'", r"'\1\2'", p)
        if nuovo == p:
            return p
        p = nuovo


# --- estrazione ---------------------------------------------------------------

def definizione(sql: str, nome: str) -> str:
    """Dalla `CREATE OR REPLACE FUNCTION … public.<nome>(` al `$$;` che la chiude."""
    m = re.search(r"CREATE OR REPLACE FUNCTION\s+public\." + re.escape(nome) + r"\(", sql)
    if m is None:
        raise AssertionError(f"{nome} non trovata")
    fine = sql.index("\n$$;", m.start()) + len("\n$$;")
    return sql[m.start():fine]


def corpo(sql: str, nome: str) -> str:
    """Il testo fra `AS $$` e `$$;`: è ciò che finisce in `pg_proc.prosrc`."""
    tutta = definizione(sql, nome)
    inizio = tutta.index("AS $$\n") + len("AS $$\n")
    return tutta[inizio:tutta.rindex("$$;")]


_BLOCCO = re.compile(r"  -- >>> v11_14[^\n]*\n.*?  -- <<< v11_14[^\n]*\n", re.S)


def blocchi(testo_sql: str) -> list[str]:
    return _BLOCCO.findall(testo_sql)


def senza_blocchi(testo_sql: str) -> str:
    return _BLOCCO.sub("", testo_sql)


def senza_commenti(sql: str) -> str:
    return "\n".join(r for r in sql.splitlines() if not r.lstrip().startswith("--"))


def fuori_dai_corpi(sql: str) -> str:
    """Il file senza i corpi `$$ … $$` e senza commenti: le istruzioni del file."""
    return re.sub(r"\$\$.*?\$\$", "$$…$$", senza_commenti(sql), flags=re.DOTALL)


class IlTokenizzatore(unittest.TestCase):
    """Il confronto vale quanto il tokenizzatore: qualche caso noto."""

    def test_unisce_i_letterali_su_righe_diverse(self):
        self.assertEqual(token("x := 'ab'\n   'cd';"), ["x", ":=", "'abcd'", ";"])

    def test_non_unisce_i_letterali_sulla_stessa_riga(self):
        # Sulla stessa riga PostgreSQL dà errore: qui restano due token.
        self.assertEqual(token("'ab' 'cd'"), ["'ab'", "'cd'"])

    def test_piega_le_concatenazioni_di_costanti(self):
        self.assertEqual(piegato("f('ab' || 'cd' || 'e')"), "f ( 'abcde' )")

    def test_ignora_commenti_e_spazi(self):
        self.assertEqual(token("a   -- commento 'x'\n  b"), token("a b"))

    def test_apici_raddoppiati(self):
        self.assertEqual(token("'dell''ente'"), ["'dell''ente'"])

    def test_gli_operatori_restano_interi(self):
        self.assertEqual(token("campi ->>'x'"), ["campi", "->>", "'x'"])
        self.assertEqual(token("(a)::date"), ["(", "a", ")", "::", "date"])


class LaRpcEQuellaDella11PiuTreBlocchi(unittest.TestCase):

    def setUp(self):
        self.sql_11 = testo(MIGRAZIONE_11)
        self.sql_14 = testo(MIGRAZIONE_14)
        self.def_14 = definizione(self.sql_14, RPC)

    def test_tolti_i_blocchi_stessi_token_della_11(self):
        self.assertEqual(token(senza_blocchi(self.def_14)),
                         token(definizione(self.sql_11, RPC)))

    def test_tre_blocchi_nell_ordine(self):
        trovati = blocchi(self.def_14)
        self.assertEqual(len(trovati), 3)
        for blocco, etichetta in zip(trovati, ("(a)", "(b)", "(c)")):
            self.assertTrue(blocco.startswith(f"  -- >>> v11_14 {etichetta}"), blocco[:40])
        self.assertEqual(self.sql_14.count(f"public.{RPC}(\n    p_evento_id bigint)"), 1)

    def test_a_prima_della_lettura_dei_campi(self):
        c = corpo(self.sql_14, RPC)
        self.assertLess(c.index("IF e.applicato THEN"), c.index("-- >>> v11_14 (a)"))
        self.assertLess(c.index("-- <<< v11_14 (a)"), c.index("campi := CASE"))
        self.assertIn("IF e . scartato_per IS NOT NULL THEN RETURN false ;",
                      piatto(blocchi(c)[0]))

    def test_b_dopo_la_traduzione_e_prima_del_ramo_senza_effetto(self):
        # Prima del ramo «campi vuoti»: senza, un annullamento_revoca senza
        # stato si marcherebbe applicato con il bando ancora revocato.
        c = corpo(self.sql_14, RPC)
        traduzione = c.index("'stato_proposto')")
        self.assertLess(traduzione, c.index("-- >>> v11_14 (b)"))
        self.assertLess(c.index("-- <<< v11_14 (b)"), c.index("IF campi = '{}'::jsonb THEN"))
        b = piatto(blocchi(c)[1])
        self.assertIn("e . tipo = 'annullamento_revoca'", b)
        self.assertIn("NOT ( campi ? 'stato_bando' )", b)
        self.assertIn("x . stato_bando = 'revocato'", b)
        self.assertIn("public . bando_stato_effettivo (", b)

    def test_c_dopo_la_riga_e_prima_della_lista_bianca(self):
        c = corpo(self.sql_14, RPC)
        self.assertLess(c.index("SELECT * INTO riga"), c.index("-- >>> v11_14 (c)"))
        self.assertLess(c.index("-- <<< v11_14 (c)"),
                        c.index("'evento % (%): transizione non '"))
        self.assertLess(c.index("-- <<< v11_14 (c)"), c.index("UPDATE public.bando b SET"))


class IlBloccoC(unittest.TestCase):
    """Superato e non ammessa: le scelte approvate nel PIANO di D2."""

    def setUp(self):
        self.c = piatto(blocchi(corpo(testo(MIGRAZIONE_14), RPC))[2])

    def test_solo_se_cambia_lo_stato_di_un_pubblicato(self):
        self.assertIn("IF campi ? 'stato_bando' AND riga . pubblicato AND stato_nuovo "
                      "IS DISTINCT FROM riga . stato_bando THEN", self.c)

    def test_superato_solo_per_il_worker_e_mai_dal_cron(self):
        self.assertIn("IF e . origine = 'worker' THEN", self.c)
        self.assertIn("x . origine IN ( 'worker' , 'redazione' )", self.c)
        self.assertNotIn("'cron'", self.c)

    def test_superato_conta_solo_eventi_applicati_e_non_scartati(self):
        self.assertIn("AND x . applicato AND x . scartato_per IS NULL", self.c)

    def test_ordine_per_data_e_poi_id(self):
        self.assertIn(") , x . id ) > ( v_giorno , e . id )", self.c)
        self.assertIn("'Europe/Rome'", self.c)

    def test_la_data_non_supera_il_giorno_di_rilevamento(self):
        # Revisione #141 (P1): un evento applicato con data_evento nel futuro
        # renderebbe «superati» per sempre gli eventi veri arrivati dopo. La
        # chiave è least(data_evento, giorno di Roma di rilevato_at), per
        # l'evento e per quello che lo supera; LEAST salta i NULL, quindi una
        # data mancante vale il giorno di rilevamento.
        giorno = "( {0} . rilevato_at AT TIME ZONE 'Europe/Rome' ) :: date"
        self.assertIn("v_giorno date := least ( e . data_evento , "
                      + giorno.format("e") + " ) ;", self.c)
        self.assertIn("AND ( least ( x . data_evento , " + giorno.format("x")
                      + " ) , x . id ) > ( v_giorno , e . id )", self.c)
        self.assertIn("ORDER BY least ( x . data_evento , " + giorno.format("x")
                      + " ) DESC , x . id DESC", self.c)
        self.assertNotIn("coalesce", self.c)

    def test_dal_sospeso_e_dal_revocato_conta_anche_l_evento(self):
        self.assertIn("riga . stato_bando IN ( 'sospeso' , 'revocato' )", self.c)
        self.assertIn("AND t . evento = e . tipo", self.c)

    def test_una_proroga_con_scadenza_futura_non_la_supera_una_chiusura(self):
        # Revisione avversaria, ciclo 2 (contratto interno §19.2): chi ha
        # letto la chiusura non sapeva della proroga. Vale per proroga,
        # riapertura e rettifica che portano una scadenza non ancora passata,
        # e solo contro una `chiusura`: una revoca piu' recente la supera ancora.
        self.assertIn("v_scad boolean := e . tipo IN ( 'proroga' , 'riapertura' , "
                      "'rettifica' ) AND campi ? 'data_scadenza' AND ( campi ->> "
                      "'data_scadenza' ) :: date >= ( now ( ) AT TIME ZONE "
                      "'Europe/Rome' ) :: date ;", self.c)
        self.assertIn("AND NOT ( v_scad AND x . tipo = 'chiusura' )", self.c)

    def test_marca_e_risponde_false_senza_sollevare(self):
        self.assertIn("SET scartato_per = v_motivo , scartato_at = now ( ) , "
                      "scartato_dettaglio = v_dett", self.c)
        self.assertIn("RETURN false ;", self.c)
        self.assertNotIn("RAISE EXCEPTION", self.c)
        for motivo in ("'superato'", "'transizione_non_ammessa'"):
            self.assertIn(motivo, self.c)


class IlTriggerEQuelloDella04PiuUnBlocco(unittest.TestCase):

    def setUp(self):
        self.sql_14 = testo(MIGRAZIONE_14)
        self.def_14 = definizione(self.sql_14, TRIGGER)

    def test_tolto_il_blocco_stessi_token_della_04(self):
        self.assertEqual(token(senza_blocchi(self.def_14)),
                         token(definizione(testo(MIGRAZIONE_04), TRIGGER)))

    def test_un_blocco_fra_l_evento_dichiarato_e_la_lista_bianca(self):
        self.assertEqual(len(blocchi(self.def_14)), 1)
        c = corpo(self.sql_14, TRIGGER)
        self.assertLess(c.index("evento_dichiarato::bigint"), c.index("-- >>> v11_14"))
        self.assertLess(c.index("-- <<< v11_14"), c.index("IF NOT public.bando_transizione_ammessa("))

    def test_passa_solo_la_redazione_con_bandi_correzione(self):
        b = piatto(blocchi(self.def_14)[0])
        self.assertIn("IF attore = 'redazione' AND nullif ( current_setting ( "
                      "'bandi.correzione' , true ) , '' ) = evento_dichiarato THEN "
                      "RETURN NEW ;", b)


class LaCorrezione(unittest.TestCase):

    def setUp(self):
        self.sql = testo(MIGRAZIONE_14)
        self.c = piatto(definizione(self.sql, CORREGGI))

    def test_firma_e_sicurezza(self):
        self.assertIn(f"public . {CORREGGI} ( p_bando_id integer , p_stato text , "
                      "p_nota text ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER", self.c)
        self.assertIn("session_user IN ( 'postgres' , 'supabase_admin' )", self.c)

    def test_evento_della_redazione_fuori_dagli_aggiornamenti(self):
        self.assertIn("b . id , 'correzione_redazionale' , 'redazione' , 'stato_bando'", self.c)
        # leggibile, in_aggiornamenti, verificato
        self.assertIn("true , false , false , jsonb_build_object ( 'nota' , v_nota )", self.c)

    def test_solo_pubblicati_e_nota_obbligatoria(self):
        self.assertIn("IF NOT b . pubblicato THEN", self.c)
        self.assertIn("IF v_nota IS NULL THEN", self.c)

    def test_accende_e_spegne_bandi_correzione(self):
        self.assertIn("set_config ( 'bandi.correzione' , v_id :: text , true )", self.c)
        self.assertIn("set_config ( 'bandi.correzione' , '' , true )", self.c)

    def test_nessuna_riga_redazione_in_lista_bianca(self):
        # La correzione passa dal trigger, non dalla lista bianca: i gemelli
        # `transizione_ammessa` restano senza righe `redazione`.
        delta = self.sql[self.sql.index("-- >>> TRANSIZIONI delta 14"):
                         self.sql.index("-- <<< TRANSIZIONI delta 14")]
        self.assertNotIn("'redazione'", delta)


class Marcatore(unittest.TestCase):

    def setUp(self):
        self.sql = testo(MIGRAZIONE_14)
        self.d = definizione(self.sql, MARCATORE)
        self.p = piegato(self.d)

    def test_nome_coincide_con_db(self):
        self.assertEqual(db.RPC_CAPACITA_SOSPENSIONI, MARCATORE)

    def test_booleano_in_sola_lettura(self):
        # `db.capacita_sospensioni()` accetta solo il booleano `true`.
        self.assertIn("RETURNS boolean LANGUAGE sql STABLE", self.p)
        for verbo in ("UPDATE", "INSERT", "DELETE"):
            self.assertNotIn(verbo, token(self.d))

    def test_legge_i_corpi_vivi_della_rpc_e_del_trigger(self):
        self.assertEqual(self.p.count("position ( 'v11_14' IN p . prosrc ) > 0"), 2)
        self.assertIn(f"'public.{RPC}(bigint)'", self.p)
        self.assertIn(f"'public.{TRIGGER}()'", self.p)

    def test_controlla_colonne_correzione_righe_e_06(self):
        for pezzo in ("'scartato_per'", "'scartato_at'", "'scartato_dettaglio'",
                      f"'public.{CORREGGI}(integer, text, text)'",
                      "'annullamento_revoca'", "= 4",
                      "public . bando_capacita_eventi ( ) ->> 'stati_cinque'"):
            self.assertIn(pezzo, self.p)

    def test_i_blocchi_che_cerca_esistono(self):
        self.assertIn("-- >>> v11_14", corpo(self.sql, RPC))
        self.assertIn("-- >>> v11_14", corpo(self.sql, TRIGGER))


class LeColonne(unittest.TestCase):

    def setUp(self):
        self.p = piatto(fuori_dai_corpi(testo(MIGRAZIONE_14)))

    def test_tre_colonne_senza_default(self):
        self.assertIn("ADD COLUMN IF NOT EXISTS scartato_per text , ADD COLUMN IF NOT "
                      "EXISTS scartato_at timestamptz , ADD COLUMN IF NOT EXISTS "
                      "scartato_dettaglio jsonb ;", self.p)

    def test_due_motivi_soltanto(self):
        self.assertIn("CHECK ( scartato_per IS NULL OR scartato_per IN ( 'superato' , "
                      "'transizione_non_ammessa' ) )", self.p)
        self.assertIn("CHECK ( ( scartato_per IS NULL ) = ( scartato_at IS NULL ) )", self.p)


class Privilegi(unittest.TestCase):

    def test_nessun_grant_ad_anon_o_authenticated(self):
        for percorso in (MIGRAZIONE_14, ROLLBACK_14):
            for riga in piatto(fuori_dai_corpi(testo(percorso))).split(";"):
                if riga.strip().startswith("GRANT"):
                    self.assertNotIn("anon", riga, percorso.name)
                    self.assertNotIn("authenticated", riga, percorso.name)

    def test_solo_service_role(self):
        p = piatto(fuori_dai_corpi(testo(MIGRAZIONE_14)))
        for firma in (f"public . {RPC} ( bigint )",
                      f"public . {CORREGGI} ( integer , text , text )",
                      f"public . {MARCATORE} ( )"):
            self.assertIn(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC , anon , authenticated ;", p)
            self.assertIn(f"GRANT EXECUTE ON FUNCTION {firma} TO service_role ;", p)
        self.assertIn(f"REVOKE ALL ON FUNCTION public . {TRIGGER} ( ) FROM PUBLIC , anon , "
                      "authenticated ;", p)


class IgieneDelFile(unittest.TestCase):

    def test_righe_corte(self):
        for percorso in (MIGRAZIONE_14, ROLLBACK_14):
            for numero, riga in enumerate(testo(percorso).splitlines(), 1):
                self.assertLessEqual(len(riga), LARGHEZZA, f"{percorso.name}:{numero}")

    def test_transazione_unica(self):
        for percorso in (MIGRAZIONE_14, ROLLBACK_14):
            eseguibile = fuori_dai_corpi(testo(percorso))
            self.assertEqual(eseguibile.count("BEGIN;"), 1, percorso.name)
            self.assertEqual(eseguibile.count("COMMIT;"), 1, percorso.name)
            self.assertIn("SET LOCAL lock_timeout = '5s';", eseguibile)

    def test_guardie_e_lock(self):
        guardie = testo(MIGRAZIONE_14)
        guardie = guardie[guardie.index("-- 1. Guardie"):guardie.index("-- 2. Le colonne")]
        for voce in ("manca la 04", "manca la 11", "manca la 06", "manca la 13",
                     "nome = 'monitor'"):
            self.assertIn(voce, guardie)

    def test_intestazione(self):
        sql = testo(MIGRAZIONE_14)
        testa = sql[:sql.index("BEGIN;")]
        for voce in ("01/10/2026", "Ordine di applicazione: DOPO la 13", "Rompe BandoFit?",
                     "Breaking change", "DOPO QUESTO FILE NON RIESEGUIRE", "la 04 e la 11",
                     "la 13", "Rollback in ordine inverso", "COSA NON È REVERSIBILE"):
            self.assertIn(voce, testa)
        for voce in ("Riconciliazione", "Verifica post-deploy"):
            self.assertIn(voce, sql)

    def test_la_verifica_interna_conta_28_righe(self):
        self.assertIn("IF v_n <> 28 THEN", testo(MIGRAZIONE_14))


def indice_dedup(sql: str) -> list[str]:
    """I token della CREATE dell'indice di dedup degli eventi, senza IF NOT EXISTS."""
    m = re.search(r"CREATE UNIQUE INDEX(?: IF NOT EXISTS)?\s+bando_evento_dedup_uidx", sql)
    if m is None:
        raise AssertionError("indice di dedup non trovato")
    istruzione = sql[m.start():sql.index(";", m.start()) + 1]
    uscita = token(istruzione)
    for parola in ("IF", "NOT", "EXISTS"):
        if uscita[3:4] == [parola]:
            uscita.pop(3)
    return uscita


class IlDedup(unittest.TestCase):
    """L'indice di dedup della 02 con `correzione_redazionale` fra gli esclusi."""

    def setUp(self):
        self.originale = indice_dedup(testo(SQL / "bando_v11_02_tabelle_di_servizio.sql"))

    def test_la_14_lo_rifa_con_la_stessa_chiave_e_un_tipo_escluso_in_piu(self):
        atteso = list(self.originale)
        posizione = atteso.index("'preavviso_collegato'")
        atteso[posizione + 1:posizione + 1] = [",", "'correzione_redazionale'"]
        self.assertEqual(indice_dedup(testo(MIGRAZIONE_14)), atteso)

    def test_la_14_lo_controlla(self):
        self.assertIn("'V6: l''indice di dedup non esclude '", testo(MIGRAZIONE_14))

    def test_il_rollback_rimette_quello_della_02_se_puo(self):
        rollback = testo(ROLLBACK_14)
        self.assertEqual(indice_dedup(rollback), self.originale)
        guardia = piatto(rollback[rollback.index("-- 5-bis."):rollback.index("-- 6. Le colonne")])
        self.assertIn("WHERE tipo = 'correzione_redazionale' GROUP BY bando_id , tipo ,", guardia)
        self.assertIn("HAVING count ( * ) > 1", guardia)
        self.assertIn("resta l''indice di dedup", rollback)

    def test_la_correzione_non_parla_piu_di_correzione_identica(self):
        self.assertNotIn("correzione identica", testo(MIGRAZIONE_14))


class LaRiconciliazione(unittest.TestCase):
    """R1 e R2 sono commenti da incollare: contano solo gli eventi con uno stato."""

    def setUp(self):
        sql = testo(MIGRAZIONE_14)
        sezione = sql[sql.index("-- R1) Eventi in coda"):sql.index("-- R3) Dopo il primo")]
        righe = [r[2:] for r in sezione.splitlines() if r.startswith("--")]
        self.r1, self.r2 = ("\n".join(righe).split("R2) Eventi in coda") + [""])[:2]

    def test_solo_gli_eventi_che_portano_uno_stato(self):
        for testo_query in (self.r1, self.r2):
            self.assertIn("where c . proposto is not null", piatto(testo_query))
            self.assertIn("case when e . campo = 'stato_bando' then e . valore_dopo #>> '{}'",
                          piatto(testo_query))

    def test_r1_con_l_eccezione_della_proroga(self):
        self.assertIn("and not ( c . scad and x . tipo = 'chiusura' )", piatto(self.r1))

    def test_r2_con_l_evento_dal_sospeso_e_dal_revocato(self):
        self.assertIn("c . ora in ( 'sospeso' , 'revocato' )", piatto(self.r2))
        self.assertIn("and t . evento = c . tipo", piatto(self.r2))


class Rollback(unittest.TestCase):

    def setUp(self):
        self.rollback = testo(ROLLBACK_14)

    def test_rimette_la_rpc_della_11(self):
        self.assertEqual(token(definizione(self.rollback, RPC)),
                         token(definizione(testo(MIGRAZIONE_11), RPC)))

    def test_rimette_il_trigger_della_04(self):
        self.assertEqual(token(definizione(self.rollback, TRIGGER)),
                         token(definizione(testo(MIGRAZIONE_04), TRIGGER)))

    def test_rimette_il_commento_della_11(self):
        def commento(sql: str) -> str:
            p = piatto(fuori_dai_corpi(sql))
            inizio = p.index(f"COMMENT ON FUNCTION public . {RPC} ( bigint ) IS")
            return p[inizio:p.index(";", inizio)]
        self.assertEqual(commento(self.rollback), commento(testo(MIGRAZIONE_11)))

    def test_toglie_tutto_cio_che_la_14_aggiunge(self):
        p = piatto(fuori_dai_corpi(self.rollback))
        self.assertIn(f"DROP FUNCTION IF EXISTS public . {MARCATORE} ( ) ;", p)
        self.assertIn(f"DROP FUNCTION IF EXISTS public . {CORREGGI} ( integer , text , text ) ;", p)
        for colonna in ("scartato_dettaglio", "scartato_at", "scartato_per"):
            self.assertIn(f"DROP COLUMN IF EXISTS {colonna}", p)
        self.assertEqual(p.count("DELETE FROM public . bando_transizione"), 4)
        self.assertNotIn("v11_14", "".join(corpo(self.rollback, n) for n in (RPC, TRIGGER)))

    def test_la_verifica_conta_24_righe(self):
        self.assertIn("IF v_n <> 24 THEN", self.rollback)


if __name__ == "__main__":
    unittest.main()
