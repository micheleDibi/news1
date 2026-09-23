# -*- coding: utf-8 -*-
"""Gate degli URL della skill SEO e scelta del testo (piano §5).

Due promesse, una per modulo:

  * `seo_skill` — ogni URL dei segmenti `link` del `contenuto` deve stare
    nell'unione fra fonte ufficiale, allegati ammessi e `bando_link`
    pubblicabili; altrimenti il segmento diventa testo. Gli allegati del
    payload si intersecano con quelli verificati 2xx.
  * `bando_seo_runner` — il testo del prompt viene dalla **pagina ufficiale**
    quando esiste, con l'intestazione che dice al modello che cosa sta
    leggendo, e mai dalla scheda dell'aggregatore quando c'e' di meglio.

Nessuna rete: `_validate_payload` gira con il controllo di raggiungibilita'
spento e con `slug_exists` sostituito.
"""
import asyncio
import unittest
from unittest.mock import patch

from tests.supporto import carica_modulo

seo_skill = carica_modulo("seo_skill")
runner = carica_modulo("bando_seo_runner")


URL_UFFICIALE = "https://regione.marche.it/bandi/formazione-2026"
URL_PDF = "https://regione.marche.it/bandi/avviso-formazione.pdf"
URL_OE = "https://www.obiettivoeuropa.com/bandi/formazione-2026"
URL_INVENTATO = "https://regione.marche.it/bandi/pagina-che-non-esiste"


def contenuto_con_link(url=URL_INVENTATO):
    """Un `contenuto` con un link in un paragrafo, in un elenco e in una FAQ."""
    return {
        "sections": [
            {"type": "paragraph", "segments": [
                {"kind": "text", "text": "Le domande si presentano "},
                {"kind": "link", "text": "sul portale", "url": url},
            ]},
            {"type": "bullet_list", "items": [
                {"segments": [{"kind": "link", "text": "modulo", "url": url}]},
            ]},
            {"type": "faq", "items": [
                {"q": "Dove si presenta?", "a": {"segments": [
                    {"kind": "link", "text": "qui", "url": url},
                ]}},
            ]},
        ],
    }


def _link(nodo):
    """Tutti i segmenti `link` rimasti, a qualunque profondita'."""
    if isinstance(nodo, dict):
        if nodo.get("kind") == "link":
            return [nodo]
        return [s for valore in nodo.values() for s in _link(valore)]
    if isinstance(nodo, list):
        return [s for valore in nodo for s in _link(valore)]
    return []


class TestGateLink(unittest.TestCase):
    def test_url_non_provato_degradato_a_testo_ovunque(self):
        pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto_con_link(), frozenset({URL_UFFICIALE}),
        )
        self.assertEqual(degradati, 3, "paragrafo, elenco e FAQ, tutti e tre")
        self.assertEqual(_link(pulito), [])
        # Il testo resta: sparisce il collegamento, non la frase.
        self.assertIn("sul portale", str(pulito))

    def test_url_ammesso_resta_link(self):
        pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto_con_link(URL_UFFICIALE), frozenset({URL_UFFICIALE}),
        )
        self.assertEqual(degradati, 0)
        self.assertEqual(len(_link(pulito)), 3)

    def test_confronto_su_url_normalizzato(self):
        # Lo slash finale e i parametri di tracciamento non sono un URL diverso.
        pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto_con_link(URL_UFFICIALE + "/?utm_source=newsletter"),
            seo_skill.normalizza_ammessi([URL_UFFICIALE]),
        )
        self.assertEqual(degradati, 0)
        self.assertEqual(len(_link(pulito)), 3)

    def test_elenco_vuoto_degrada_tutto(self):
        # Un insieme vuoto e' una risposta: nessun URL e' provato.
        _pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto_con_link(), frozenset(),
        )
        self.assertEqual(degradati, 3)

    def test_elenco_assente_lascia_stare(self):
        # `None` e' «non so»: il gate non si applica e vale il comportamento
        # di prima. Distinguere i due casi e' cio' che permette di attivare il
        # gate un pezzo alla volta.
        contenuto = contenuto_con_link()
        pulito, degradati = seo_skill.degrada_link_non_ammessi(contenuto, None)
        self.assertEqual(degradati, 0)
        self.assertIs(pulito, contenuto)

    def test_link_verso_l_aggregatore_degradato(self):
        _pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto_con_link(URL_OE), frozenset({URL_UFFICIALE}),
        )
        self.assertEqual(degradati, 3)

    def test_link_senza_url_degradato(self):
        contenuto = {"sections": [{"segments": [{"kind": "link", "text": "vuoto"}]}]}
        pulito, degradati = seo_skill.degrada_link_non_ammessi(
            contenuto, frozenset({URL_UFFICIALE}),
        )
        self.assertEqual(degradati, 1)
        self.assertEqual(_link(pulito), [])


class TestGateAllegati(unittest.TestCase):
    def test_solo_gli_allegati_verificati(self):
        allegati = [
            {"label": "Avviso", "url": URL_PDF, "tipo": "pdf"},
            {"label": "Inventato", "url": URL_INVENTATO, "tipo": "pdf"},
        ]
        tenuti, scartati = seo_skill.filtra_allegati(
            allegati, seo_skill.normalizza_ammessi([URL_PDF]),
        )
        self.assertEqual([a["url"] for a in tenuti], [URL_PDF])
        self.assertEqual(scartati, 1)

    def test_senza_elenco_nessun_filtro(self):
        allegati = [{"label": "Avviso", "url": URL_PDF, "tipo": "pdf"}]
        tenuti, scartati = seo_skill.filtra_allegati(allegati, None)
        self.assertEqual(tenuti, allegati)
        self.assertEqual(scartati, 0)


def payload_valido(**extra):
    payload = {
        "slug": "contributi-formazione-professionale-2026",
        "titolo": "Contributi per la formazione professionale 2026",
        "descrizione_breve": (
            "La Regione Marche finanzia i percorsi di formazione professionale "
            "rivolti a imprese e lavoratori del territorio, con domande da "
            "presentare entro il 30 settembre 2026 secondo le modalita' "
            "indicate nell'avviso pubblico."
        ),
        "contenuto": contenuto_con_link(),
        "livello": "flash_bando",
        "allegati": [
            {"label": "Avviso", "url": URL_PDF, "tipo": "pdf"},
            {"label": "Inventato", "url": URL_INVENTATO, "tipo": "pdf"},
        ],
        "ente_erogatore": "Regione Marche",
        "tematica": ["formazione"],
        "link_candidatura_source": "missing",
        "link_candidatura": None,
    }
    payload.update(extra)
    return payload


class TestValidatePayload(unittest.TestCase):
    def _valida(self, payload, **kwargs):
        with patch.object(seo_skill, "_resolve_slug_collision") as slug:
            async def _restituisci(s, *_a, **_k):
                return s
            slug.side_effect = _restituisci
            return asyncio.run(seo_skill._validate_payload(
                payload, 1, {}, "", reachability_check=False, **kwargs,
            ))

    def test_il_gate_agisce_dentro_la_validazione(self):
        validato = self._valida(
            payload_valido(),
            link_ammessi=[URL_UFFICIALE, URL_PDF],
            allegati_ammessi=[URL_PDF],
        )
        self.assertIsNotNone(validato)
        self.assertEqual(_link(validato["contenuto"]), [], "URL non provato: niente link")
        self.assertEqual([a["url"] for a in validato["allegati"]], [URL_PDF])

    def test_link_provato_sopravvive_alla_validazione(self):
        validato = self._valida(
            payload_valido(contenuto=contenuto_con_link(URL_UFFICIALE)),
            link_ammessi=[URL_UFFICIALE],
            allegati_ammessi=[URL_PDF],
        )
        self.assertEqual(len(_link(validato["contenuto"])), 3)

    def test_senza_elenchi_il_comportamento_non_cambia(self):
        validato = self._valida(payload_valido())
        self.assertEqual(len(_link(validato["contenuto"])), 3)
        self.assertEqual(len(validato["allegati"]), 2)


class TestSceltaDellaFonte(unittest.TestCase):
    def test_prima_la_fonte_ufficiale(self):
        self.assertEqual(
            runner.scegli_fonte({
                "fonte_ufficiale_url": URL_UFFICIALE,
                "fonte_ufficiale_stato": "trovata",
                "link_bando": URL_OE,
            }),
            (URL_UFFICIALE, True),
        )

    def test_una_fonte_in_verifica_non_e_ufficiale(self):
        url, ufficiale = runner.scegli_fonte({
            "fonte_ufficiale_url": URL_UFFICIALE,
            "fonte_ufficiale_stato": "in_verifica",
            "link_bando": "https://regione.marche.it/portale",
        })
        self.assertEqual(url, "https://regione.marche.it/portale")
        self.assertTrue(ufficiale)

    def test_poi_il_link_non_aggregatore(self):
        self.assertEqual(
            runner.scegli_fonte({"link_bando": URL_UFFICIALE}), (URL_UFFICIALE, True),
        )

    def test_l_aggregatore_e_solo_un_ripiego(self):
        self.assertEqual(runner.scegli_fonte({"link_bando": URL_OE}), (URL_OE, False))

    def test_senza_link_niente_testo(self):
        self.assertEqual(runner.scegli_fonte({}), ("", False))


class TestComposizioneDelTesto(unittest.TestCase):
    TESTO = "Avviso formazione\n\nLe domande entro il 30/09/2026.\n\n" + "Dettagli. " * 200

    def test_intestazione_ufficiale_con_url(self):
        composto = runner.componi_testo(self.TESTO, URL_UFFICIALE, True)
        self.assertTrue(composto.startswith(f"PAGINA UFFICIALE: {URL_UFFICIALE}"))

    def test_intestazione_di_ripiego_senza_url(self):
        composto = runner.componi_testo(self.TESTO, URL_OE, False)
        self.assertTrue(composto.startswith(runner.INTESTAZIONE_RIPIEGO))
        self.assertNotIn(URL_OE, composto, "l'URL dell'aggregatore non entra nel prompt")

    def test_budget_rispettato_e_intestazione_mai_tagliata(self):
        composto = runner.componi_testo("x " * 20000, URL_UFFICIALE, True, budget=500)
        self.assertTrue(composto.startswith("PAGINA UFFICIALE:"))
        self.assertLessEqual(len(composto), 500 + len(runner.INTESTAZIONE_UFFICIALE) + len(URL_UFFICIALE))

    def test_gli_allegati_deterministici_vanno_in_coda(self):
        composto = runner.componi_testo(
            self.TESTO, URL_UFFICIALE, True,
            allegati=[{"label": "Avviso", "url": URL_PDF, "tipo": "pdf"}],
        )
        self.assertIn("Allegati:", composto)
        self.assertIn(URL_PDF, composto)

    def test_testo_vuoto_resta_vuoto(self):
        self.assertEqual(runner.componi_testo("", URL_UFFICIALE, True), "")


# Una riga nella forma che `db.select_bandi_to_complete` restituisce: e' su
# questa che il gate deve comportarsi bene, non su un dizionario costruito a
# mano con le chiavi giuste.
def riga_come_dal_db(**extra):
    riga = {
        "id": 42,
        "fonte_id": 449,
        "titolo_raw": "Contributi per la formazione professionale 2026",
        "descrizione_raw": None,
        "link_bando": URL_OE,
        "raw_data": {},
        "tipo_link": "HTML",
        "stato_bando": "aperto",
        "stato_processing": "enriched",
        "data_pubblicazione": None,
        "data_apertura": None,
        "data_scadenza": "2026-09-30",
        "tipologia_bando_id": None,
        "modalita_erogazione_id": None,
        "programma_id": None,
        "allegati": [{"label": "Avviso", "url": URL_PDF, "tipo": "pdf"}],
    }
    riga.update(extra)
    return riga


class TestGateSpentoQuandoNessunoHaGuardato(unittest.TestCase):
    """Il difetto che questo caso fissa: con `bando_link` assente e nessuna
    `fonte_ufficiale_url`, le due liste erano `[]` — «il resolver ha guardato e
    non ha trovato nulla» — invece di `None` — «nessuno ha ancora guardato». Il
    gate nasceva acceso con l'insieme vuoto su tutto il corpus e pubblicava
    ogni bando senza allegati e senza collegamenti."""

    def test_senza_bando_link_e_senza_fonte_il_gate_resta_spento(self):
        link, allegati = runner.elenchi_ammessi(
            riga_come_dal_db(), [], link_leggibili=False,
        )
        self.assertIsNone(link)
        self.assertIsNone(allegati)

    def test_e_il_payload_sopravvive_intatto(self):
        link, allegati = runner.elenchi_ammessi(
            riga_come_dal_db(), [], link_leggibili=False,
        )
        with patch.object(seo_skill, "_resolve_slug_collision") as slug:
            async def _restituisci(s, *_a, **_k):
                return s
            slug.side_effect = _restituisci
            validato = asyncio.run(seo_skill._validate_payload(
                payload_valido(), 42, {}, "", reachability_check=False,
                link_ammessi=link, allegati_ammessi=allegati,
            ))
        self.assertEqual(len(_link(validato["contenuto"])), 3, "i link restano link")
        self.assertEqual(len(validato["allegati"]), 2, "gli allegati restano")

    def test_una_fonte_risolta_basta_ad_accendere_il_gate(self):
        # La riga ha una fonte ufficiale: qualcuno ha guardato, l'elenco e'
        # conoscibile anche senza `bando_link`.
        link, allegati = runner.elenchi_ammessi(
            riga_come_dal_db(fonte_ufficiale_url=URL_UFFICIALE), [], link_leggibili=False,
        )
        self.assertEqual(link, [URL_UFFICIALE, URL_PDF])
        self.assertEqual(allegati, [URL_PDF])

    def test_bando_link_leggibile_e_vuoto_e_una_risposta(self):
        # La tabella c'e' e per questo bando non ha righe: l'elenco e' vuoto,
        # non ignoto, e il gate deve mordere.
        link, allegati = runner.elenchi_ammessi(
            riga_come_dal_db(allegati=[]), [], link_leggibili=True,
        )
        self.assertEqual(link, [])
        self.assertEqual(allegati, [])


class TestUrlAmmessi(unittest.TestCase):
    def test_unione_di_fonte_allegati_e_link_pubblicabili(self):
        bando = {
            "fonte_ufficiale_url": URL_UFFICIALE,
            "allegati": [{"label": "Avviso", "url": URL_PDF}],
        }
        link = [
            {"url": "https://regione.marche.it/faq", "tipo": "faq", "pubblicabile": True},
            {"url": URL_INVENTATO, "tipo": "altro", "pubblicabile": False},
        ]
        self.assertEqual(
            runner.url_ammessi(bando, link),
            [URL_UFFICIALE, URL_PDF, "https://regione.marche.it/faq"],
        )

    def test_gli_allegati_ammessi_sono_i_soli_documenti(self):
        bando = {"allegati": [{"label": "Avviso", "url": URL_PDF}]}
        link = [
            {"url": "https://regione.marche.it/faq", "tipo": "faq", "pubblicabile": True},
            {"url": "https://regione.marche.it/altro.pdf", "tipo": "allegato",
             "pubblicabile": True},
        ]
        self.assertEqual(
            runner.allegati_ammessi(bando, link),
            [URL_PDF, "https://regione.marche.it/altro.pdf"],
        )

    def test_senza_niente_l_elenco_e_vuoto(self):
        # `link_leggibili=True` (il default) significa «bando_link l'ho letta»:
        # una riga senza niente ha davvero zero URL provati.
        self.assertEqual(runner.url_ammessi({}), [])
        self.assertEqual(runner.allegati_ammessi({}), [])

    def test_ma_senza_bando_link_l_elenco_e_ignoto(self):
        self.assertIsNone(runner.url_ammessi({}, link_leggibili=False))
        self.assertIsNone(runner.allegati_ammessi({}, link_leggibili=False))


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
