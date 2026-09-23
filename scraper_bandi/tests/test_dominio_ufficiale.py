# -*- coding: utf-8 -*-
"""Whitelist e blocklist dei domini (piano §5, §16.3 punto 1).

Il test piu' importante e' `ParitaConIlSeedSQL`: le costanti del modulo e il
file `backend/sql/bando_v11_seed_dominio_ufficiale.sql` sono due copie della
stessa lista, e una copia che nessuno confronta diverge.

    cd scraper_bandi && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
"""
import re
import unittest

from tests.supporto import REPO, carica_modulo

dominio_ufficiale = carica_modulo("dominio_ufficiale")

SEED_SQL = REPO / "backend" / "sql" / "bando_v11_seed_dominio_ufficiale.sql"
MIGRAZIONE_01 = REPO / "backend" / "sql" / "bando_v11_01_pubblicazione.sql"
MIGRAZIONE_02 = REPO / "backend" / "sql" / "bando_v11_02_tabelle_di_servizio.sql"

# ('host', 'tipo', 0.00 — i campi successivi non interessano.
_RIGA_SQL = re.compile(
    r"\(\s*'([^']+)'\s*,\s*'(ente|portale_pubblico|pattern|dedotto|aggregatore)'\s*,\s*(\d+\.\d+)"
)


def _righe_sql(percorso):
    """Le righe INSERT del file, senza i blocchi di commento (la sezione
    «Riconciliazione» contiene INSERT di esempio con host finti)."""
    testo = percorso.read_text(encoding="utf-8")
    senza_commenti = "\n".join(
        riga for riga in testo.splitlines() if not riga.lstrip().startswith("--")
    )
    return {
        (host.replace("''", "'"), tipo, float(confidenza))
        for host, tipo, confidenza in _RIGA_SQL.findall(senza_commenti)
    }


class ParitaConIlSeedSQL(unittest.TestCase):
    def test_stesse_righe_del_seed(self):
        modulo = {(d.host, d.tipo, float(d.confidenza)) for d in dominio_ufficiale.SEED}
        self.assertEqual(modulo, _righe_sql(SEED_SQL))

    def test_conteggi_dichiarati_nel_blocco_verifica(self):
        per_tipo = {}
        for d in dominio_ufficiale.SEED:
            per_tipo[d.tipo] = per_tipo.get(d.tipo, 0) + 1
        self.assertEqual(per_tipo, {"aggregatore": 25, "portale_pubblico": 20, "pattern": 7})

    def test_blocklist_minima_della_02_e_un_sottoinsieme(self):
        minima = {h for h, tipo, _ in _righe_sql(MIGRAZIONE_02) if tipo == "aggregatore"}
        self.assertTrue(minima)
        self.assertLessEqual(minima, {d.host for d in dominio_ufficiale.AGGREGATORI})

    def test_nessun_aggregatore_dentro_un_pattern(self):
        # Stessa verifica del punto 5 del blocco Verifica del file SQL: la
        # blocklist prevarrebbe comunque, ma una sovrapposizione e' il segno di
        # un pattern scritto troppo largo.
        for aggregatore in dominio_ufficiale.SEED:
            if aggregatore.tipo != "aggregatore":
                continue
            for modello in dominio_ufficiale.PATTERN:
                self.assertFalse(
                    dominio_ufficiale.combacia(aggregatore.host, modello.host),
                    f"{aggregatore.host} cade dentro {modello.host}",
                )


class DominioDi(unittest.TestCase):
    """Gemello di `dominio_di(text)` della migrazione 02: gli stessi esempi del
    blocco Verifica del file SQL."""

    def test_esempi_del_blocco_verifica(self):
        casi = {
            "https://WWW.Regione.Marche.it/bandi/x?y=1#z": "regione.marche.it",
            "http://user:pw@incentivi.gov.it:8080/a": "incentivi.gov.it",
            "non un url": None,
            "": None,
            None: None,
            "esempio.it.": "esempio.it",
        }
        for url, atteso in casi.items():
            self.assertEqual(dominio_ufficiale.dominio_di(url), atteso, url)

    def test_host_non_ascii_da_none(self):
        # Un IDN non convertito non corrisponderebbe a nessuna riga: meglio
        # None che un valore che passa i confronti solo per caso.
        self.assertIsNone(dominio_ufficiale.dominio_di("https://città.example/x"))


class Registrabile(unittest.TestCase):
    def test_due_etichette(self):
        self.assertEqual(dominio_ufficiale.registrabile("bandi.lazioeuropa.it"), "lazioeuropa.it")

    def test_tre_etichette_sotto_un_suffisso_pubblico(self):
        # Senza la regola, `incentivi.gov.it` e `mimit.gov.it` sarebbero lo
        # stesso dominio e l'atto dell'uno varrebbe per l'altro.
        self.assertEqual(dominio_ufficiale.registrabile("www.incentivi.gov.it"), "incentivi.gov.it")
        self.assertEqual(dominio_ufficiale.registrabile("usr.istruzione.it"), "usr.istruzione.it")
        self.assertEqual(dominio_ufficiale.registrabile("a.b.mi.camcom.it"), "mi.camcom.it")

    def test_host_corto_o_invalido(self):
        self.assertEqual(dominio_ufficiale.registrabile("esempio.it"), "esempio.it")
        self.assertIsNone(dominio_ufficiale.registrabile("non un url"))

    def test_due_comuni_della_stessa_provincia_sono_due_domini(self):
        # Senza questa regola entrambi valgono `bo.it`, e due determine con lo
        # stesso numero nello stesso anno diventano un criterio esatto: due enti
        # diversi fusi in automatico, con 301 e `pubblicato=false`.
        self.assertEqual(
            dominio_ufficiale.registrabile("comune.imola.bo.it"), "comune.imola.bo.it"
        )
        self.assertNotEqual(
            dominio_ufficiale.registrabile("comune.imola.bo.it"),
            dominio_ufficiale.registrabile("comune.casalecchio.bo.it"),
        )

    def test_comune_e_provincia_dello_stesso_capoluogo(self):
        self.assertNotEqual(
            dominio_ufficiale.registrabile("comune.firenze.it"),
            dominio_ufficiale.registrabile("provincia.firenze.it"),
        )

    def test_il_prefisso_dell_ente_sopravvive_al_sottodominio(self):
        # Le due righe della stessa regione devono restare lo stesso dominio:
        # e' il caso che il criterio `atto` deve continuare a riconoscere.
        self.assertEqual(
            dominio_ufficiale.registrabile("bandi.regione.marche.it"),
            dominio_ufficiale.registrabile("www.regione.marche.it"),
        )

    def test_sigla_provinciale_senza_prefisso(self):
        self.assertEqual(dominio_ufficiale.registrabile("www.imola.bo.it"), "imola.bo.it")


class Classificazione(unittest.TestCase):
    def setUp(self):
        self.tabella = dominio_ufficiale.costruisci()

    def test_tipi_del_seed(self):
        self.assertEqual(dominio_ufficiale.classifica("incentivi.gov.it", self.tabella), "portale_pubblico")
        self.assertEqual(dominio_ufficiale.classifica("regione.marche.it", self.tabella), "pattern")
        self.assertEqual(dominio_ufficiale.classifica("obiettivoeuropa.com", self.tabella), "aggregatore")
        self.assertEqual(dominio_ufficiale.classifica("mai-visto.example", self.tabella), "sconosciuto")

    def test_sottodomini_e_trappola_del_suffisso(self):
        # `right(host, length+1) = '.'||host` a DB: il sottodominio si', l'host
        # che *finisce* con lo stesso testo no.
        self.assertEqual(dominio_ufficiale.classifica("cdn.obiettivoeuropa.com", self.tabella), "aggregatore")
        self.assertEqual(
            dominio_ufficiale.classifica("obiettivoeuropa.com.evil.it", self.tabella), "sconosciuto"
        )
        self.assertTrue(dominio_ufficiale.e_aggregatore("www.obiettivoeuropa.com"))
        self.assertFalse(dominio_ufficiale.e_aggregatore("obiettivoeuropa.com.evil.it"))
        self.assertFalse(dominio_ufficiale.e_aggregatore(None))

    def test_nessun_import_automatico_promuove_un_aggregatore(self):
        # IndicePA e gli host di `fonte` sono sorgenti automatiche: un host
        # riciclato o una fonte nuova su un aggregatore non devono poter
        # promuovere quell'host a fonte ufficiale.
        tabella = dominio_ufficiale.costruisci(
            fonti=[{"id": 900, "link": "https://fasi.eu/bandi"}],
            indicepa=[{"Denominazione": "X", "Sito_istituzionale": "https://bandi.it"}],
        )
        self.assertEqual(dominio_ufficiale.classifica("fasi.eu", tabella), "aggregatore")
        self.assertEqual(dominio_ufficiale.classifica("bandi.it", tabella), "aggregatore")
        self.assertFalse(dominio_ufficiale.verificabile("fasi.eu", tabella))

    def test_la_blocklist_prevale_sulle_altre_righe_dello_stesso_insieme(self):
        # Due righe per host diversi che combaciano entrambe: vince sempre
        # l'aggregatore, qualunque sia l'ordine.
        tabella = dominio_ufficiale.Tabella((
            dominio_ufficiale.Dominio("cdn.fasi.eu", "ente", 1.0),
            dominio_ufficiale.Dominio("fasi.eu", "aggregatore", 1.0),
        ))
        self.assertEqual(dominio_ufficiale.classifica("cdn.fasi.eu", tabella), "aggregatore")

    def test_una_riga_esplicita_del_db_puo_riconciliare(self):
        # E' la via documentata nel blocco «Riconciliazione» del file SQL: solo
        # una riga scritta a mano a DB (service_role) cambia la sorte di un host.
        tabella = dominio_ufficiale.costruisci(
            [dominio_ufficiale.Dominio("first.aster.it", "ente", 1.0, origine="db")]
        )
        self.assertEqual(dominio_ufficiale.classifica("first.aster.it", tabella), "ente")

    def test_la_regola_piu_forte_vince_sul_pattern(self):
        # `incentivi.gov.it` combacia anche con `*.gov.it` (0,80): deve restare
        # portale pubblico con confidenza 1,00.
        self.assertEqual(dominio_ufficiale.confidenza("incentivi.gov.it", self.tabella), 1.00)
        self.assertEqual(dominio_ufficiale.confidenza("qualcosa.gov.it", self.tabella), 0.80)

    def test_riga_disattivata_non_conta(self):
        tabella = dominio_ufficiale.Tabella((
            dominio_ufficiale.Dominio("esempio.it", "ente", 1.0, attivo=False),
        ))
        self.assertEqual(dominio_ufficiale.classifica("esempio.it", tabella), "sconosciuto")


class Verificabile(unittest.TestCase):
    """Regola del trigger di `bando_evento`: `verificato` solo per ente,
    portale o pattern con confidenza ≥ 0,80. Mai `dedotto`."""

    def test_dedotto_non_verifica_mai(self):
        tabella = dominio_ufficiale.costruisci(dedotti=["scuola-esempio.example"])
        self.assertEqual(dominio_ufficiale.classifica("scuola-esempio.example", tabella), "dedotto")
        self.assertFalse(dominio_ufficiale.verificabile("scuola-esempio.example", tabella))

    def test_pattern_e_portale_verificano(self):
        tabella = dominio_ufficiale.costruisci()
        self.assertTrue(dominio_ufficiale.verificabile("istituto.edu.it", tabella))
        self.assertTrue(dominio_ufficiale.verificabile("filse.it", tabella))

    def test_ente_sotto_soglia_non_verifica(self):
        tabella = dominio_ufficiale.Tabella((
            dominio_ufficiale.Dominio("esempio.it", "ente", 0.70),
        ))
        self.assertFalse(dominio_ufficiale.verificabile("esempio.it", tabella))

    def test_un_ente_corretto_a_mano_non_nasconde_il_pattern(self):
        # A DB e' un EXISTS: il seed `*.edu.it` a 0,80 combacia comunque. Se qui
        # si guardasse solo la riga piu' forte, abbassare la confidenza di una
        # riga `ente` — la via che il blocco «Riconciliazione» del seed
        # documenta — spegnerebbe la verifica che il SQL continua a concedere.
        tabella = dominio_ufficiale.costruisci(
            [dominio_ufficiale.Dominio("scuolax.edu.it", "ente", 0.60, origine="db")]
        )
        self.assertEqual(dominio_ufficiale.classifica("scuolax.edu.it", tabella), "ente")
        self.assertEqual(dominio_ufficiale.confidenza("scuolax.edu.it", tabella), 0.60)
        self.assertTrue(dominio_ufficiale.verificabile("scuolax.edu.it", tabella))

    def test_un_aggregatore_non_verifica_mai(self):
        tabella = dominio_ufficiale.costruisci()
        self.assertFalse(dominio_ufficiale.verificabile("obiettivoeuropa.com", tabella))


class TipoFonteUfficiale(unittest.TestCase):
    """§16.1 A11: `classifica()` e' il tipo del dominio e ha sei valori, la
    colonna `bando.fonte_ufficiale_tipo` ne ammette due."""

    def setUp(self):
        self.tabella = dominio_ufficiale.costruisci()

    def test_mappatura(self):
        casi = {
            "filse.it": "portale_pubblico",        # portale del seed
            "regione.marche.it": None,             # pattern
            "mai-visto.example": None,             # sconosciuto
            "obiettivoeuropa.com": None,           # aggregatore
        }
        for host, atteso in casi.items():
            self.assertEqual(
                dominio_ufficiale.tipo_fonte_ufficiale(host, self.tabella), atteso, host
            )
        dedotta = dominio_ufficiale.costruisci(dedotti=["scuola.example"])
        self.assertIsNone(dominio_ufficiale.tipo_fonte_ufficiale("scuola.example", dedotta))

    def test_solo_i_valori_del_check_della_migrazione_01(self):
        testo = MIGRAZIONE_01.read_text(encoding="utf-8")
        trovato = re.search(
            r"CONSTRAINT bando_fonte_ufficiale_tipo_check\s+CHECK \([^)]*IN \(([^)]*)\)",
            testo,
            re.S,
        )
        self.assertIsNotNone(trovato, "CHECK di fonte_ufficiale_tipo non trovato")
        ammessi = {v.strip().strip("'") for v in trovato.group(1).split(",")}
        self.assertEqual(ammessi, set(dominio_ufficiale.TIPI_FONTE_UFFICIALE))
        # Nessun tipo del vocabolario puo' produrre un valore fuori dal CHECK.
        prodotti = set()
        for tipo in dominio_ufficiale.TIPI + (dominio_ufficiale.SCONOSCIUTO,):
            tabella = dominio_ufficiale.Tabella((
                dominio_ufficiale.Dominio("esempio.it", tipo, 1.0),
            ))
            prodotti.add(dominio_ufficiale.tipo_fonte_ufficiale("esempio.it", tabella))
        self.assertLessEqual(prodotti - {None}, ammessi)


class IndiceDellaTabella(unittest.TestCase):
    """L'indice di `Tabella` deve dare le stesse risposte della scansione riga
    per riga: e' l'unico modo di renderla veloce senza cambiarne il senso."""

    RIGHE = (
        dominio_ufficiale.Dominio("cdn.fasi.eu", "ente", 1.0),
        dominio_ufficiale.Dominio("fasi.eu", "aggregatore", 1.0),
        dominio_ufficiale.Dominio("artea.toscana.it", "ente", 1.0),
        dominio_ufficiale.Dominio("*.toscana.it", "pattern", 0.80),
        dominio_ufficiale.Dominio("spento.it", "ente", 1.0, attivo=False),
    )

    def test_stessa_risposta_della_scansione(self):
        tabella = dominio_ufficiale.Tabella(self.RIGHE + dominio_ufficiale.SEED)
        host = [
            "cdn.fasi.eu", "fasi.eu", "artea.toscana.it", "bandi.artea.toscana.it",
            "x.toscana.it", "spento.it", "incentivi.gov.it", "obiettivoeuropa.com.evil.it",
            "mai-visto.example", "regione.marche.it", None, "non un url",
        ]
        for uno in host:
            atteso = _corrispondenza_per_scansione(tabella, uno)
            trovata = dominio_ufficiale.corrispondenza(uno, tabella)
            self.assertEqual(trovata, atteso, uno)

    def test_le_righe_restano_quelle_passate(self):
        tabella = dominio_ufficiale.Tabella(self.RIGHE)
        self.assertEqual(tabella.righe, self.RIGHE)
        self.assertEqual(len(tabella.attive()), 4)

    def test_combacianti_e_un_exists(self):
        tabella = dominio_ufficiale.Tabella(self.RIGHE)
        tipi = {r.tipo for r in tabella.combacianti("artea.toscana.it")}
        self.assertEqual(tipi, {"ente", "pattern"})


def _corrispondenza_per_scansione(tabella, host):
    """La vecchia implementazione, riga per riga: serve solo da metro."""
    normalizzato = dominio_ufficiale.dominio_di(host)
    if not normalizzato:
        return None
    for riga in tabella.blocklist():
        if dominio_ufficiale.combacia(normalizzato, riga.host):
            return riga
    migliore = None
    for riga in tabella.attive():
        if riga.tipo == "aggregatore" or riga.tipo not in dominio_ufficiale.PRECEDENZA:
            continue
        if not dominio_ufficiale.combacia(normalizzato, riga.host):
            continue
        if migliore is None or _forza(riga) < _forza(migliore):
            migliore = riga
    return migliore


def _forza(riga):
    return (
        dominio_ufficiale.PRECEDENZA.get(riga.tipo, 9),
        -riga.confidenza,
        -len(riga.host),
    )


class Costruzione(unittest.TestCase):
    def test_host_delle_fonti(self):
        fonti = [
            {"id": 237, "link": "https://www.lazioeuropa.it/bandi/"},
            {"id": 449, "link": "https://obiettivoeuropa.com/bandi"},     # aggregatore: fuori
            {"id": 500, "link": "https://x.example", "discoverable": False},
            {"id": 501, "link": "non un url"},
        ]
        prodotte = dominio_ufficiale.da_fonti(fonti)
        self.assertEqual([d.host for d in prodotte], ["lazioeuropa.it"])
        self.assertEqual(prodotte[0].tipo, "ente")
        self.assertEqual(prodotte[0].confidenza, 1.00)
        self.assertEqual(prodotte[0].fonte_id, 237)

    def test_import_indicepa_e_puro(self):
        righe = [
            {"Denominazione": "Comune di Esempio", "Codice_IPA": "c_e001",
             "Sito_istituzionale": "http://www.comune.esempio.it/"},
            {"Denominazione": "Ufficio secondo", "Codice_IPA": "c_e002",
             "Sito_istituzionale": "https://comune.esempio.it"},        # stesso host
            {"Denominazione": "Senza sito", "Codice_IPA": "c_e003", "Sito_istituzionale": ""},
            {"Denominazione": "Aggregatore", "Codice_IPA": "x",
             "Sito_istituzionale": "https://bandi.it"},                 # blocklist
        ]
        prodotte = dominio_ufficiale.importa_indicepa(righe)
        self.assertEqual([d.host for d in prodotte], ["comune.esempio.it"])
        self.assertEqual(prodotte[0].ente, "Comune di Esempio")
        self.assertEqual(prodotte[0].codice_ipa, "c_e001")
        self.assertEqual(prodotte[0].origine, "indicepa")

    def test_la_riga_del_db_vince_sul_seed(self):
        tabella = dominio_ufficiale.costruisci(
            [dominio_ufficiale.Dominio("filse.it", "ente", 1.0, origine="db")]
        )
        riga = dominio_ufficiale.corrispondenza("filse.it", tabella)
        self.assertEqual((riga.tipo, riga.origine), ("ente", "db"))

    def test_senza_seed_nessuna_riga_del_codice(self):
        tabella = dominio_ufficiale.costruisci(includi_seed=False)
        self.assertEqual(tabella.righe, ())
        self.assertEqual(dominio_ufficiale.classifica("incentivi.gov.it", tabella), "sconosciuto")


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
