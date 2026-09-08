# -*- coding: utf-8 -*-
"""Test di backend/app/sanifica.py.

Il punto che conta: la sanificazione del payload della skill NON deve toccare
nessun URL. La vecchia coppia _strip_em_dashes/_strip_null_bytes ricorreva
alla cieca su tutto il payload, quindi attraversava anche `source_url`,
`fonti[].fonte_url` e i `segments[].url` dei link inline: con l'em-dash la
cosa passava liscia, con gli accenti no.

    cd backend && python3 -m unittest discover -s tests -t .
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path

_RADICE = Path(__file__).resolve().parents[2]

# `sanifica` importa `ortografia` con un import relativo, quindi serve un
# package. Si registra sotto un nome proprio: su questa macchina esiste un
# altro package chiamato `app` sul sys.path (vedi CLAUDE.md).
_PACCHETTO = "edunews_app_test"
if _PACCHETTO not in sys.modules:
    _finto = types.ModuleType(_PACCHETTO)
    _finto.__path__ = [str(_RADICE / "backend" / "app")]
    sys.modules[_PACCHETTO] = _finto

sanifica = importlib.import_module(_PACCHETTO + ".sanifica")

ACCENTATA_E = chr(0x00E8)
ACCENTATA_A = chr(0x00E0)


def _payload_di_prova():
    """Stessa forma prodotta da backend/skill/scripts/generate_json_output.py."""
    return {
        "generated_at": "2026-09-08T10:12:33.123456Z",
        "source_url": "https://miur.gov.it/universita/gia-fatto",
        "livello": "editoriale",
        "keyword": "universita statale",
        "seo": {
            "meta_title": "Perche' cambia tutto",
            "meta_description": "La citta' e' pronta",
            "h1": "Perche' cambia tutto",
        },
        "angolo": "Il bando sara' aperto a piu' candidati",
        "competitor_report": [
            {"fonte": "Corriere", "angolo_usato": "gia' visto", "gap": "manca la citta'"},
        ],
        "factcheck_report": [
            {"dato": "sara' pubblicato a giugno", "stato": "confermato",
             "fonte_primaria": "https://x.it/piu-info"},
        ],
        "article": {
            "h1": "Perche' cambia tutto",
            "plain_text_preview": "la citta' cambia",
            "sections": [
                {"type": "h2", "id": "perche-conviene", "text": "Perche' conviene"},
                {"type": "paragraph", "segments": [
                    {"kind": "text", "text": "La qualita' e' alta. "},
                    {"kind": "link", "text": "vedi il bando",
                     "url": "https://inpa.gov.it/citta/piu-posti"},
                ]},
                {"type": "bullet_list", "items": [
                    [{"kind": "text", "text": "universita' statali"}],
                    [{"kind": "link", "text": "gia' aperto",
                      "url": "/universita/gia-aperto"}],
                ]},
                {"type": "sconosciuto", "text": ["gia'", "piu'"]},
            ],
        },
        "fonti": [{"dato": "la citta' cresce", "fonte_url": "https://y.it/universita"}],
        "validation": {"passed": True, "warnings": ["titolo troppo lungo"],
                       "word_count": 742, "title_length": 58},
    }


class TestSanitizePayload(unittest.TestCase):
    def setUp(self):
        self.dentro = _payload_di_prova()
        self.fuori, self.segnalazioni = sanifica._sanitize_payload(self.dentro)

    def test_prosa_corretta(self):
        articolo = self.fuori["article"]
        self.assertEqual(self.fuori["seo"]["h1"], "Perch" + chr(0x00E9) + " cambia tutto")
        self.assertEqual(self.fuori["seo"]["meta_description"],
                         "La citt" + ACCENTATA_A + " " + ACCENTATA_E + " pronta")
        self.assertIn("sar" + ACCENTATA_A, self.fuori["angolo"])
        self.assertIn("pi" + chr(0x00F9), self.fuori["angolo"])
        self.assertEqual(articolo["sections"][0]["text"],
                         "Perch" + chr(0x00E9) + " conviene")
        self.assertIn("qualit" + ACCENTATA_A,
                      articolo["sections"][1]["segments"][0]["text"])
        self.assertIn("universit" + ACCENTATA_A,
                      articolo["sections"][2]["items"][0][0]["text"])
        self.assertEqual(articolo["sections"][3]["text"],
                         ["gi" + ACCENTATA_A, "pi" + chr(0x00F9)])
        self.assertIn("citt" + ACCENTATA_A, self.fuori["fonti"][0]["dato"])
        self.assertIn("citt" + ACCENTATA_A, self.fuori["competitor_report"][0]["gap"])
        self.assertIn("sar" + ACCENTATA_A, self.fuori["factcheck_report"][0]["dato"])

    def test_nessun_url_alterato(self):
        """Il controllo che protegge dal rischio principale."""
        articolo = self.fuori["article"]
        self.assertEqual(self.fuori["source_url"], self.dentro["source_url"])
        self.assertEqual(self.fuori["fonti"][0]["fonte_url"],
                         "https://y.it/universita")
        self.assertEqual(self.fuori["factcheck_report"][0]["fonte_primaria"],
                         "https://x.it/piu-info")
        self.assertEqual(articolo["sections"][1]["segments"][1]["url"],
                         "https://inpa.gov.it/citta/piu-posti")
        self.assertEqual(articolo["sections"][2]["items"][1][0]["url"],
                         "/universita/gia-aperto")

    def test_campi_tecnici_intatti(self):
        articolo = self.fuori["article"]
        self.assertEqual(self.fuori["generated_at"], self.dentro["generated_at"])
        self.assertEqual(self.fuori["livello"], "editoriale")
        self.assertEqual(self.fuori["factcheck_report"][0]["stato"], "confermato")
        self.assertEqual(articolo["sections"][0]["id"], "perche-conviene")
        self.assertEqual(articolo["sections"][1]["segments"][1]["kind"], "link")
        # validation resta l'archivio di cio' che la skill ha visto
        self.assertEqual(self.fuori["validation"], self.dentro["validation"])

    def test_payload_originale_non_mutato(self):
        self.assertEqual(self.dentro["seo"]["h1"], "Perche' cambia tutto")

    def test_idempotenza(self):
        ancora, _ = sanifica._sanitize_payload(self.fuori)
        self.assertEqual(ancora, self.fuori)

    def test_em_dash_e_null_byte(self):
        payload = {"angolo": "prima " + chr(0x2014) + " dopo\x00 e "
                             + "un" + chr(0x2014) + "trattino"}
        fuori, _ = sanifica._sanitize_payload(payload)
        self.assertEqual(fuori["angolo"], "prima, dopo e un-trattino")

    def test_non_dizionario(self):
        fuori, segnalazioni = sanifica._sanitize_payload("stringa")
        self.assertEqual(fuori, "stringa")
        self.assertEqual(segnalazioni, [])


class TestNormTesto(unittest.TestCase):
    def test_none_e_vuoto(self):
        self.assertIsNone(sanifica._norm_testo(None))
        self.assertEqual(sanifica._norm_testo(""), "")

    def test_stringa(self):
        self.assertEqual(sanifica._norm_testo("perche' si"),
                         "perch" + chr(0x00E9) + " si")


if __name__ == "__main__":
    unittest.main()
