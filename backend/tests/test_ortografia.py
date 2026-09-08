# -*- coding: utf-8 -*-
"""Test di backend/app/ortografia.py.

Legge la STESSA tabella di casi del runner Node
(``tests/ortografia/casi.json``): e' la difesa contro la divergenza fra i due
normalizzatori gemelli. Se una modifica tocca un solo linguaggio, uno dei due
runner fallisce.

    cd backend && python3 -m unittest discover -s tests -t .
"""

import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

_RADICE = Path(__file__).resolve().parents[2]
CASI = _RADICE / "tests" / "ortografia" / "casi.json"

# Import per percorso, non `from app import ortografia`: su questa macchina
# esiste un altro package chiamato `app` sul sys.path (altro progetto) e la
# collisione di namespace lo farebbe vincere. ortografia.py non ha import
# interni proprio per poter essere caricato cosi'.
def _carica_modulo(nome, percorso):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ortografia = _carica_modulo(
    "ortografia_edunews", _RADICE / "backend" / "app" / "ortografia.py"
)
slug = _carica_modulo("slug_edunews", _RADICE / "backend" / "app" / "slug.py")


def _carica():
    with open(CASI, encoding="utf-8-sig") as sorgente:
        return json.load(sorgente)


class TestTabellaCondivisa(unittest.TestCase):
    dati = _carica()

    def test_conteggio_minimo(self):
        """Nessuno deve poter cancellare casi in silenzio."""
        self.assertGreaterEqual(
            len(self.dati["casi"]), self.dati["conteggio_minimo"]
        )

    def test_identificatori_unici(self):
        visti = [caso["id"] for caso in self.dati["casi"]]
        self.assertEqual(len(visti), len(set(visti)))

    def test_tabelle_allineate(self):
        """Le tabelle del modulo devono coincidere con quelle del fixture."""
        atteso = self.dati["tabelle"]
        coppie = {
            "LISTA_2": ortografia.LISTA_2,
            "LISTA_2B": ortografia.LISTA_2B,
            "SOLO_APOSTROFO": ortografia.SOLO_APOSTROFO,
            "LISTA_3A": ortografia.LISTA_3A,
            "LISTA_3B": ortografia.LISTA_3B,
        }
        for nome, tabella in coppie.items():
            self.assertEqual(
                [list(voce) for voce in tabella], atteso[nome], nome
            )
        self.assertEqual(list(ortografia.DENY), atteso["DENY"])
        self.assertEqual(
            list(ortografia.PREPOSIZIONI_SE), atteso["PREPOSIZIONI_SE"]
        )

    def test_casi(self):
        for caso in self.dati["casi"]:
            with self.subTest(caso["id"]):
                risultato = ortografia.correggi(caso["input"])
                self.assertEqual(risultato["testo"], caso["atteso"], caso["nota"])
                self.assertEqual(
                    hashlib.sha256(caso["atteso"].encode("utf-8")).hexdigest(),
                    caso["sha256"],
                    "il fixture e' stato modificato senza rigenerare lo sha256",
                )
                for chiave in ("correzioni", "segnalazioni"):
                    if chiave in caso:
                        self.assertEqual(
                            len(risultato[chiave]), caso[chiave], chiave
                        )
                if "saltato" in caso:
                    self.assertEqual(risultato["saltato"], caso["saltato"])

    def test_idempotenza(self):
        """correggi(correggi(x)).testo == correggi(x).testo, sempre.

        L'idempotenza vale sul TESTO, non sulle segnalazioni: al secondo giro
        il gate anti-rumore e' spento per costruzione.
        """
        for caso in self.dati["casi"]:
            with self.subTest(caso["id"]):
                una = ortografia.correggi(caso["input"])["testo"]
                due = ortografia.correggi(una)["testo"]
                self.assertEqual(una, due)


class TestInvariantiDelleTabelle(unittest.TestCase):
    def test_deny_mai_correggibile(self):
        for parola in ortografia.DENY:
            for variante in (
                parola,
                ortografia._iniziale_maiuscola(parola),
                ortografia._tutto_maiuscolo(parola),
            ):
                self.assertNotIn(variante, ortografia._MAPPA, variante)

    def test_correggibili_e_segnalabili_disgiunti(self):
        comuni = set(ortografia._MAPPA) & set(ortografia._SEGNALA_2B)
        self.assertEqual(comuni, set())

    def test_accento_giusto_sui_composti_di_che(self):
        """Su una testata un accento sbagliato e' peggio di uno mancante."""
        acuta = chr(0x00E9)
        grave = chr(0x00E8)
        for nuda in ("perche", "poiche", "affinche", "benche", "nonche",
                     "sicche", "finche", "purche", "anziche"):
            self.assertTrue(
                ortografia._MAPPA[nuda].endswith(acuta),
                nuda + " deve finire con la e acuta",
            )
        for nuda, atteso in (("cioe", grave), ("caffé", grave)):
            self.assertTrue(ortografia._MAPPA[nuda].endswith(atteso), nuda)

    def test_nessun_metacarattere_vietato(self):
        """\\b \\w \\d \\s divergono fra i due motori: vietati nei pattern."""
        pattern = [
            ortografia._RE_PRINCIPALE.pattern,
            ortografia._RE_SEGNALAZIONI.pattern,
            ortografia._RE_SE_PREP.pattern,
        ] + [regex.pattern for regex, _ in ortografia._MASCHERE]
        vietati = ("\\b", "\\B", "\\w", "\\W", "\\d", "\\D")
        for sorgente in pattern:
            for metacarattere in vietati:
                self.assertNotIn(metacarattere, sorgente, sorgente[:60])
            # \s e' ammesso solo dentro l'idioma [\s\S] ("qualunque carattere")
            self.assertEqual(
                sorgente.count("\\s"), sorgente.count("[\\s\\S]"), sorgente[:60]
            )

    def test_nessun_lookbehind(self):
        pattern = [ortografia._RE_PRINCIPALE.pattern,
                   ortografia._RE_SEGNALAZIONI.pattern,
                   ortografia._RE_SE_PREP.pattern]
        pattern += [regex.pattern for regex, _ in ortografia._MASCHERE]
        for sorgente in pattern:
            self.assertNotIn("(?<", sorgente, sorgente[:60])

    def test_pattern_compilabili(self):
        for regex, _ in ortografia._MASCHERE:
            self.assertIsNotNone(re.compile(regex.pattern))


class TestComportamentiDiConfine(unittest.TestCase):
    def test_url_mai_alterati(self):
        """Il rischio principale: la normalizzazione non tocca gli URL."""
        testo = (
            "Vedi https://www.miur.gov.it/universita/attivita?piu=1 e anche "
            "[la citta](https://comune.it/citta-metropolitana) e "
            "miur.gov.it/gia-fatto, poi perche' no."
        )
        risultato = ortografia.correggi(testo)
        for frammento in (
            "https://www.miur.gov.it/universita/attivita?piu=1",
            "https://comune.it/citta-metropolitana",
            "miur.gov.it/gia-fatto",
        ):
            self.assertIn(frammento, risultato["testo"])
        self.assertIn("perch" + chr(0x00E9), risultato["testo"])

    def test_ancore_restano_coerenti(self):
        """Gli id degli heading sono insensibili agli accenti: correggere il
        testo visibile non desincronizza l'indice."""
        testo = "## Perche' iscriversi {#perche-iscriversi}"
        risultato = ortografia.correggi(testo)
        self.assertIn("{#perche-iscriversi}", risultato["testo"])
        self.assertIn("Perch" + chr(0x00E9), risultato["testo"])

    def test_non_stringa(self):
        for valore in (None, 12, [], {}):
            risultato = ortografia.correggi(valore)
            self.assertEqual(risultato["saltato"], "non_stringa")
            self.assertEqual(risultato["testo"], valore)


class TestSlug(unittest.TestCase):
    """Parita' di slugifica() con il gemello src/lib/slug.ts."""

    dati = _carica()

    def test_casi_condivisi(self):
        for ingresso, atteso in self.dati["casi_slug"]:
            with self.subTest(ingresso):
                self.assertEqual(slug.slugifica(ingresso), atteso)

    def test_accento_non_sposta_lo_slug(self):
        """L'invariante che rende sicura la correzione ortografica dei titoli.

        Se cadesse, correggere un accento nel titolo cambierebbe l'URL e la
        vecchia pagina risponderebbe 410.
        """
        for sbagliato, corretto in (
            ("Perche' e' cambiato tutto", "Perch" + chr(0xE9) + " " + chr(0xE8) + " cambiato tutto"),
            ("La citta cresce", "La citt" + chr(0xE0) + " cresce"),
            ("universita statale", "universit" + chr(0xE0) + " statale"),
        ):
            with self.subTest(sbagliato):
                self.assertEqual(
                    slug.slugifica(sbagliato), slug.slugifica(corretto)
                )

    def test_slug_sempre_conforme(self):
        for ingresso, atteso in self.dati["casi_slug"]:
            if atteso:
                self.assertTrue(slug.slug_valido(atteso), atteso)


if __name__ == "__main__":
    unittest.main()
