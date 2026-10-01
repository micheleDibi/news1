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



# --- sosta d'ingresso e gemelli esatti (contratto `bandi-giro-2` §19.4, §19.9) ---

from datetime import datetime, timedelta, timezone  # noqa: E402

ADESSO_SOSTA = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)


class _Finti:
    """L'I/O di `trattieni_e_fondi`, registrato."""

    def __init__(self, controlli=None, link=(), pubblicati=(), fondi="master", errore=None):
        self.controlli = controlli or {}
        self.link = list(link)
        self.pubblicati = list(pubblicati)
        self._fondi = fondi
        self.errore = errore
        self.fusioni: list = []
        self.rifiutati: list = []
        self.segnati: list = []
        self.letture_pubblicati = 0

    def leggi_controlli(self, ids):
        if self.errore:
            raise self.errore
        return {i: c for i, c in self.controlli.items() if i in ids}

    def leggi_link(self, ids):
        return [r for r in self.link if r["bando_id"] in ids]

    def leggi_pubblicati(self):
        self.letture_pubblicati += 1
        return list(self.pubblicati)

    def fondi(self, master, dup, motivo):
        self.fusioni.append((master, dup, motivo))
        return master if self._fondi == "master" else self._fondi

    def rifiuta(self, bando_id, motivo):
        self.rifiutati.append((bando_id, motivo))
        return True

    def segna(self, bando_id, colonne):
        self.segnati.append((bando_id, dict(colonne)))
        return True

    def lancia(self, bandi, **opzioni):
        opzioni.setdefault("attivo", True)
        # I due interruttori insieme, salvo che il test li separi (giro 3, §11).
        opzioni.setdefault("attivo_gemelli", opzioni["attivo"])
        opzioni.setdefault("colonna_sosta", True)
        return asyncio.run(runner.trattieni_e_fondi(
            bandi, adesso=ADESSO_SOSTA, sosta_giri=4,
            leggi_controlli=self.leggi_controlli, leggi_link=self.leggi_link,
            leggi_pubblicati=self.leggi_pubblicati, fondi=self.fondi, rifiuta=self.rifiuta,
            segna_trattenuto=self.segna, **opzioni))


def _bando(bando_id, **extra):
    riga = {"id": bando_id, "fonte_id": 237, "stato_bando": "aperto", "data_scadenza": None,
            "link_bando": f"https://www.lazioeuropa.it/bandi/avviso-{bando_id}",
            "titolo_raw": f"Avviso {bando_id}"}
    riga.update(extra)
    return riga


class TestSostaDIngresso(unittest.TestCase):
    def test_in_attivo_l_aperto_senza_scadenza_sosta_e_trattenuto_dal_si_scrive(self):
        finti = _Finti()
        rimasti, contatori = finti.lancia([_bando(1), _bando(2, data_scadenza="2026-12-31")])
        self.assertEqual([b["id"] for b in rimasti], [2])
        self.assertEqual(contatori["trattenuti"], 1)
        self.assertEqual(finti.segnati, [(1, {"trattenuto_dal": ADESSO_SOSTA.isoformat()})])

    def test_trattenuto_dal_non_si_riscrive(self):
        dal = (ADESSO_SOSTA - timedelta(hours=7)).isoformat()
        finti = _Finti(controlli={1: {"trattenuto_dal": dal}})
        rimasti, _ = finti.lancia([_bando(1)])
        self.assertEqual((rimasti, finti.segnati), ([], []))

    def test_passati_quattro_giri_si_pubblica(self):
        dal = (ADESSO_SOSTA - timedelta(hours=25)).isoformat()
        finti = _Finti(controlli={1: {"trattenuto_dal": dal}})
        rimasti, contatori = finti.lancia([_bando(1)])
        self.assertEqual([b["id"] for b in rimasti], [1])
        self.assertEqual(contatori["rilasciati_a_tempo"], 1)

    def test_senza_appiglio_resta_fermo(self):
        finti = _Finti()
        rimasti, contatori = finti.lancia([_bando(1, link_bando=None, stato_bando="aperto")])
        self.assertEqual(rimasti, [])
        self.assertEqual(contatori["trattenuti_senza_appiglio"], 1)
        # Una riga di bando_link basta come appiglio.
        finti = _Finti(link=[{"bando_id": 1}])
        rimasti, _ = finti.lancia([_bando(1, link_bando=None, data_scadenza="2026-12-31")])
        self.assertEqual([b["id"] for b in rimasti], [1])

    def test_in_ombra_passa_tutto_e_conta(self):
        finti = _Finti()
        rimasti, contatori = finti.lancia([_bando(1), _bando(2, link_bando=None)], attivo=False)
        self.assertEqual([b["id"] for b in rimasti], [1, 2])
        self.assertEqual((contatori["trattenuti"], contatori["trattenuti_senza_appiglio"]), (1, 1))
        self.assertEqual(finti.segnati, [])
        self.assertEqual(contatori["modalita_ingresso"], "ombra")

    def test_dry_run_non_scrive_anche_in_attivo(self):
        finti = _Finti()
        rimasti, _ = finti.lancia([_bando(1)], dry_run=True)
        self.assertEqual(([b["id"] for b in rimasti], finti.segnati), ([1], []))

    def test_lettura_fallita_passa_tutto(self):
        finti = _Finti(errore=ConnectionError("giu'"))
        with patch.object(runner, "logger"):
            rimasti, contatori = finti.lancia([_bando(1)])
        self.assertEqual([b["id"] for b in rimasti], [1])
        self.assertTrue(contatori["controllo_ingresso_saltato"])

    def test_senza_la_colonna_la_sosta_si_pubblica_e_si_conta_solo_li(self):
        # Senza bando_controllo.trattenuto_dal la sosta non finirebbe mai. Non
        # va in `trattenuti`: in attivo la telemetria la sottrarrebbe.
        finti = _Finti()
        rimasti, contatori = finti.lancia([_bando(1)], colonna_sosta=False)
        self.assertEqual([b["id"] for b in rimasti], [1])
        self.assertEqual((contatori["sosta_senza_colonna"], contatori["trattenuti"]), (1, 0))
        self.assertEqual(finti.segnati, [])

    def test_senza_la_colonna_il_senza_appiglio_resta_fermo(self):
        # A lui `trattenuto_dal` non serve: si ferma come con la colonna.
        finti = _Finti()
        rimasti, contatori = finti.lancia(
            [_bando(1), _bando(2, link_bando=None, stato_bando="aperto")], colonna_sosta=False)
        self.assertEqual([b["id"] for b in rimasti], [1])
        self.assertEqual(contatori["trattenuti_senza_appiglio"], 1)
        self.assertEqual((contatori["sosta_senza_colonna"], contatori["trattenuti"]), (1, 0))
        self.assertEqual(finti.segnati, [])

    def test_senza_la_colonna_in_ombra_si_conta_come_prima(self):
        finti = _Finti()
        rimasti, contatori = finti.lancia(
            [_bando(1), _bando(2, link_bando=None)], attivo=False, colonna_sosta=False)
        self.assertEqual([b["id"] for b in rimasti], [1, 2])
        self.assertEqual((contatori["trattenuti"], contatori["trattenuti_senza_appiglio"],
                          contatori["sosta_senza_colonna"]), (1, 1, 0))

    def test_la_colonna_si_legge_dallo_schema(self):
        db_vero = carica_modulo("db")

        class _Schema:
            def __init__(self, colonne):
                self.colonne = colonne
                self.chieste: list = []

            def ha(self, tabella, colonna):
                self.chieste.append((tabella, colonna))
                return colonna in self.colonne

        for colonne, attese in ((set(), [1]), ({"trattenuto_dal"}, [])):
            schema = _Schema(colonne)
            finti = _Finti()
            with patch.object(db_vero, "controllo", schema):
                rimasti, _ = finti.lancia([_bando(1)], colonna_sosta=None)
            self.assertEqual([b["id"] for b in rimasti], attese)
            self.assertEqual(schema.chieste, [("bando_controllo", "trattenuto_dal")])

    def test_schema_illeggibile_vale_come_colonna_assente(self):
        db_vero = carica_modulo("db")

        class _Rotto:
            def ha(self, *_a):
                raise ConnectionError("giu'")

        finti = _Finti()
        with patch.object(db_vero, "controllo", _Rotto()):
            rimasti, contatori = finti.lancia([_bando(1)], colonna_sosta=None)
        self.assertEqual(([b["id"] for b in rimasti], contatori["sosta_senza_colonna"]), ([1], 1))


class TestGemelliPrimaDellaPubblicazione(unittest.TestCase):
    PUBBLICATO = {"id": 905315, "fonte_id": 237, "bando_master_id": None,
                  "link_bando": "https://www.lazioeuropa.it/bandi/psicologia-scolastica",
                  "titolo_raw": "Psicologia scolastica nelle scuole del Lazio",
                  "titolo": "Psicologia scolastica nelle scuole del Lazio",
                  "data_scadenza": "2026-12-31"}
    NUOVO = {"id": 942936, "fonte_id": 449, "stato_bando": "aperto", "data_scadenza": "2026-12-31",
             "link_bando": "https://obiettivoeuropa.com/bandi/942936",
             "fonte_ufficiale_url": "https://www.lazioeuropa.it/bandi/psicologia-scolastica/",
             "titolo_raw": "Lazio - Psicologia scolastica nelle scuole"}

    def test_in_attivo_si_fonde_e_non_si_pubblica(self):
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        rimasti, contatori = finti.lancia([dict(self.NUOVO)])
        self.assertEqual(rimasti, [])
        self.assertEqual(finti.fusioni, [(905315, 942936, "gemello esatto: url")])
        self.assertEqual(finti.rifiutati, [(942936, "gemello esatto di 905315: fuso")])
        self.assertEqual(contatori["fusi_prima_della_pubblicazione"], 1)

    def test_in_ombra_si_conta_e_si_pubblica(self):
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        rimasti, contatori = finti.lancia([dict(self.NUOVO)], attivo=False)
        self.assertEqual([b["id"] for b in rimasti], [942936])
        self.assertEqual((finti.fusioni, contatori["gemelli_trovati"]), ([], 1))

    def test_pagina_condivisa_non_si_fonde(self):
        altro = dict(self.PUBBLICATO, id=905316,
                     link_bando="https://www.lazioeuropa.it/bandi/altro",
                     fonte_ufficiale_url=self.PUBBLICATO["link_bando"])
        finti = _Finti(pubblicati=[self.PUBBLICATO, altro])
        rimasti, _ = finti.lancia([dict(self.NUOVO)])
        self.assertEqual([b["id"] for b in rimasti], [942936])
        self.assertEqual(finti.fusioni, [])

    def test_fusione_non_riuscita_non_si_pubblica_e_si_ritenta(self):
        finti = _Finti(pubblicati=[self.PUBBLICATO], fondi=None)
        with patch.object(runner, "logger"):
            rimasti, contatori = finti.lancia([dict(self.NUOVO)])
        self.assertEqual(rimasti, [])
        self.assertEqual((contatori["fusioni_non_riuscite"], finti.rifiutati), (1, []))

    def test_i_gia_fusi_non_sono_master(self):
        finti = _Finti(pubblicati=[dict(self.PUBBLICATO, bando_master_id=1)])
        rimasti, _ = finti.lancia([dict(self.NUOVO)])
        self.assertEqual([b["id"] for b in rimasti], [942936])

    def test_chiave_esterna_e_atto_non_si_fondono_in_automatico(self):
        # Revisione del 01/10: in automatico solo 'url' e 'riga_calendario'.
        gemelli = carica_modulo("gemelli")
        pubblicato = dict(self.PUBBLICATO, link_bando="https://www.lazioeuropa.it/bandi/a")
        for criterio, fuso in (("chiave_esterna", False), ("atto", False),
                               ("riga_calendario", True)):
            trovata = (gemelli.Corrispondenza(905315, criterio, "x"),)
            finti = _Finti(pubblicati=[pubblicato])
            with patch.object(gemelli, "criteri_esatti", lambda *_a, t=trovata: t):
                rimasti, contatori = finti.lancia([dict(self.NUOVO)])
            self.assertEqual(rimasti == [], fuso, criterio)
            self.assertEqual(contatori["fusi_prima_della_pubblicazione"], int(fuso), criterio)
            self.assertEqual(contatori["gemelli_trovati"], int(fuso), criterio)
            if not fuso:
                self.assertEqual((finti.fusioni, finti.rifiutati), ([], []), criterio)

    def test_corpus_troncato_niente_fusioni(self):
        finti = _Finti(pubblicati=[self.PUBBLICATO, dict(self.PUBBLICATO, id=1, link_bando="x")])
        with patch.object(runner, "logger"):
            rimasti, contatori = finti.lancia([dict(self.NUOVO)], limite_lettura=2)
        self.assertEqual([b["id"] for b in rimasti], [942936])
        self.assertEqual(finti.fusioni, [])
        self.assertTrue(contatori["controllo_gemelli_troncato"])
        self.assertEqual(contatori["gemelli_trovati"], 0)
        # Sotto il limite la stessa coppia si fonde.
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        rimasti, contatori = finti.lancia([dict(self.NUOVO)], limite_lettura=2)
        self.assertEqual((rimasti, contatori["controllo_gemelli_troncato"]), ([], False))

    def test_la_lettura_dei_pubblicati_e_completa(self):
        # Giro 3, §1 e §11: niente TETTO_GEMELLI, si leggono tutti i pubblicati.
        db_vero = carica_modulo("db")
        chiamate: list = []

        def leggi(**opzioni):
            chiamate.append(opzioni)
            return []

        finti = _Finti()
        with patch.object(db_vero, "select_pubblicati_per_gemelli", leggi):
            asyncio.run(runner.trattieni_e_fondi(
                [dict(self.NUOVO)], attivo=True, attivo_gemelli=True, adesso=ADESSO_SOSTA,
                sosta_giri=4, colonna_sosta=True, leggi_controlli=finti.leggi_controlli,
                leggi_link=finti.leggi_link, fondi=finti.fondi, rifiuta=finti.rifiuta,
                segna_trattenuto=finti.segna))
        self.assertEqual(chiamate, [{"limit": None, "con_calendario": True}])
        self.assertFalse(hasattr(carica_modulo("gemelli"), "LIMITE_LETTURA_PUBBLICATI"))

    def test_la_fusione_segue_gemelli_modalita_non_la_verifica(self):
        # Sosta in ombra e gemelli attivi: si fonde.
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        rimasti, contatori = finti.lancia([dict(self.NUOVO)], attivo=False, attivo_gemelli=True)
        self.assertEqual((rimasti, len(finti.fusioni)), ([], 1))
        self.assertEqual((contatori["modalita_ingresso"], contatori["modalita_gemelli"]),
                         ("ombra", "attivo"))
        # Sosta attiva e gemelli in ombra: si conta e si pubblica.
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        rimasti, contatori = finti.lancia([dict(self.NUOVO)], attivo=True, attivo_gemelli=False)
        self.assertEqual(([b["id"] for b in rimasti], finti.fusioni), ([942936], []))
        self.assertEqual(contatori["gemelli_trovati"], 1)

    def test_l_interruttore_viene_da_gemelli_modalita(self):
        from types import SimpleNamespace
        for valore, attesa in (("attivo", "attivo"), ("ombra", "ombra")):
            with self.subTest(valore=valore), patch.object(
                    runner, "get_settings", lambda v=valore: SimpleNamespace(
                        gemelli_modalita=v, verifica_stato_modalita="ombra", ingresso_sosta_giri=4)):
                finti = _Finti(pubblicati=[self.PUBBLICATO])
                _rimasti, contatori = finti.lancia([dict(self.NUOVO)], attivo=None,
                                                   attivo_gemelli=None)
                self.assertEqual(contatori["modalita_gemelli"], attesa)
                self.assertEqual(contatori["modalita_ingresso"], "ombra")
        # Il dry-run vince sempre.
        finti = _Finti(pubblicati=[self.PUBBLICATO])
        _rimasti, contatori = finti.lancia([dict(self.NUOVO)], attivo_gemelli=True, dry_run=True)
        self.assertEqual((contatori["modalita_gemelli"], finti.fusioni), ("ombra", []))

    def test_un_gia_fuso_non_rende_l_url_condiviso(self):
        # B4 (giro 3, §11): il fuso e' lo stesso bando del suo master.
        fuso = dict(self.PUBBLICATO, id=905316, bando_master_id=905315)
        finti = _Finti(pubblicati=[self.PUBBLICATO, fuso])
        rimasti, _ = finti.lancia([dict(self.NUOVO)])
        self.assertEqual((rimasti, len(finti.fusioni)), ([], 1))


class TestSpesaDellaSeo(unittest.TestCase):
    """Giro 3, §4: la SEO conta la spesa e scrive la propria riga `pipeline_run`."""

    def _giro(self, *, dry_run=False, payload_ok=(True, False)):
        from types import SimpleNamespace
        bilancio = carica_modulo("bilancio")
        bandi = [{"id": i, "stato_processing": "enriched"} for i in range(len(payload_ok))]
        esiti = dict(zip([b["id"] for b in bandi], payload_ok))
        contatori_visti = []

        async def genera(b, input_ctx, *, contatori=None, **k):
            contatori_visti.append(contatori)
            bilancio.registra_chiamata(contatori, "opus", {"input_tokens": 1_000_000}, {"opus": (5.0, 0.0)})
            payload = {"titolo": "x"} if esiti[b["id"]] else None
            return SimpleNamespace(payload=payload, affermazioni=(), motivo="no")

        async def scrivi(bando_id, payload, *, gia_pubblicato):
            return True

        async def nessun_doppione(bandi, **k):
            return list(bandi), {}

        async def niente_sosta(bandi, **k):
            return list(bandi), {}

        impostazioni = SimpleNamespace(seo_model="opus", seo_concurrency=2)
        with patch.object(runner, "get_settings", lambda: impostazioni), \
                patch.object(runner, "select_bandi_to_complete", lambda **k: list(bandi)), \
                patch.object(runner, "escludi_doppioni_oe", nessun_doppione), \
                patch.object(runner, "trattieni_e_fondi", niente_sosta), \
                patch.object(runner, "load_catalogo", lambda: {}), \
                patch.object(runner, "build_bando_input_context", lambda b, c: {"id": b["id"]}), \
                patch.object(runner, "genera_per_bando", genera), \
                patch.object(runner, "update_bando_completed", scrivi), \
                patch.object(runner, "_tabella_dei_domini", lambda: None), \
                patch.object(runner, "scrivi_righe_link", lambda *a, **k: 0), \
                patch.object(runner.telemetria, "scrivi_pipeline_run") as riga:
            counters = asyncio.run(runner.run(dry_run=dry_run, giro="06:00"))
        return counters, riga, contatori_visti

    def test_spesa_e_copertura_nella_riga_del_passo(self):
        counters, riga, contatori_visti = self._giro()
        # Uno stesso oggetto per tutti i bandi: la spesa del passo.
        self.assertEqual(len({id(c) for c in contatori_visti}), 1)
        self.assertEqual(counters["costo_usd"], 10.0)
        self.assertEqual(counters["copertura"],
                         {"candidati": 2, "fatti": 1, "rimasti": 1, "motivo_rimasti": "errore"})
        scritta = riga.call_args.args[0]
        self.assertEqual((scritta.step, scritta.giro), ("seo", "06:00"))
        self.assertEqual(scritta.come_riga()["contatori"]["usd"], 10.0)
        self.assertEqual(scritta.contatori["copertura"], counters["copertura"])

    def test_dry_run_niente_riga(self):
        counters, riga, _ = self._giro(dry_run=True)
        riga.assert_not_called()
        self.assertEqual(counters["costo_usd"], 10.0)


class TestRigheLinkDeiNuovi(unittest.TestCase):
    """Giro 3, §10: dopo la pubblicazione, le righe `bando_link` dal payload."""

    def test_scegli_fonte_viene_da_dominio_ufficiale(self):
        dominio = carica_modulo("dominio_ufficiale")
        self.assertIs(runner.scegli_fonte, dominio.scegli_fonte)
        # La guardia sui PDF di B3 vale anche per la SEO.
        pdf = {"fonte_ufficiale_url": "https://www.regione.lazio.it/bando.pdf",
               "fonte_ufficiale_stato": "trovata", "link_bando": "https://www.lazioeuropa.it/b"}
        self.assertEqual(runner.scegli_fonte(pdf)[0], "https://www.lazioeuropa.it/b")

    def test_passa_html_e_url_effettivo_e_scrive(self):
        from types import SimpleNamespace
        chiamate, scritte = [], []

        def righe_da(b, payload, html, *, url_riferimento=None, tabella=None):
            chiamate.append((b["id"], html, url_riferimento, tabella))
            return [{"bando_id": b["id"], "url": "https://ente.it/modulo.pdf", "tipo": "allegato"}]

        generazione = SimpleNamespace(html="<a href='/modulo.pdf'>m</a>", url_finale="https://ente.it/b")
        n = runner.scrivi_righe_link({"id": 7}, {"allegati": []}, generazione, tabella="T",
                                     righe_da=righe_da, scrivi=lambda r: scritte.append(r) or len(r))
        self.assertEqual(n, 1)
        self.assertEqual(chiamate, [(7, "<a href='/modulo.pdf'>m</a>", "https://ente.it/b", "T")])
        self.assertEqual(scritte[0][0]["url"], "https://ente.it/modulo.pdf")

    def test_senza_righe_niente_upsert_e_un_errore_non_ferma(self):
        from types import SimpleNamespace
        scritte = []
        n = runner.scrivi_righe_link({"id": 7}, {}, SimpleNamespace(), righe_da=lambda *a, **k: [],
                                     scrivi=lambda r: scritte.append(r) or 1)
        self.assertEqual((n, scritte), (0, []))

        def rotto(*a, **k):
            raise RuntimeError("giu'")

        with patch.object(runner, "logger"):
            self.assertIsNone(runner.scrivi_righe_link({"id": 7}, {}, SimpleNamespace(), righe_da=rotto))

    def test_html_solo_dalla_cache_dello_scarico(self):
        from types import SimpleNamespace
        scarico = carica_modulo("scarico")
        finto = SimpleNamespace(_da_cache=lambda url: SimpleNamespace(
            html="<html>x</html>", url_finale="https://ente.it/finale") if url == "https://ente.it/b" else None)
        with patch.object(scarico, "scarico_corrente", lambda: finto):
            self.assertEqual(runner._pagina_in_cache("https://ente.it/b"),
                             ("<html>x</html>", "https://ente.it/finale"))
            self.assertEqual(runner._pagina_in_cache("https://ente.it/altra"), ("", ""))

    def test_solo_i_nuovi_pubblicati(self):
        # Un rerun dei completed (gia' pubblicati) non riscrive le righe.
        from types import SimpleNamespace
        bandi = [{"id": 1, "stato_processing": "enriched"}, {"id": 2, "stato_processing": "completed"}]
        visti = []

        async def genera(b, input_ctx, *, contatori=None, **k):
            return SimpleNamespace(payload={"titolo": "x"}, affermazioni=(), motivo="")

        async def scrivi(bando_id, payload, *, gia_pubblicato):
            return True

        async def passa(bandi, **k):
            return list(bandi), {}

        with patch.object(runner, "get_settings", lambda: SimpleNamespace(seo_model="o", seo_concurrency=1)), \
                patch.object(runner, "select_bandi_to_complete", lambda **k: list(bandi)), \
                patch.object(runner, "escludi_doppioni_oe", passa), \
                patch.object(runner, "trattieni_e_fondi", passa), \
                patch.object(runner, "load_catalogo", lambda: {}), \
                patch.object(runner, "build_bando_input_context", lambda b, c: {"id": b["id"]}), \
                patch.object(runner, "genera_per_bando", genera), \
                patch.object(runner, "update_bando_completed", scrivi), \
                patch.object(runner, "_tabella_dei_domini", lambda: None), \
                patch.object(runner, "scrivi_righe_link",
                             lambda b, p, g, **k: visti.append(b["id"]) or 2), \
                patch.object(runner.telemetria, "scrivi_pipeline_run"):
            counters = asyncio.run(runner.run(include_completed=True))
        self.assertEqual(visti, [1])
        self.assertEqual((counters["righe_link_scritte"], counters["righe_link_fallite"]), (2, 0))


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
