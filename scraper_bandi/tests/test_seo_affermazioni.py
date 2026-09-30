# -*- coding: utf-8 -*-
"""Testi SEO senza forme di partecipazione inventate (contratto di ottobre, §7).

Il 29/09 BandoFit ha segnalato tre schede (18145, 18278, 171905) che affermano
forme di partecipazione assenti dall'atto dell'ente, e il controllo dei 20
bandi del giro delle 12 ne ha trovate altre otto (RIPRESA §4.4). Qui si
verificano:

  * la regola 18 del prompt, e che il prompt costruito sui casi reali porti al
    modello la fonte e la classificazione;
  * `affermazioni_non_sostenute` sui testi REALI di quelle schede (estratti del
    `contenuto` letti in GET il 30/09), con la fonte che il modello aveva:
    campi grezzi, beneficiari collegati e, per il 1262345, la pagina del
    Piemonte;
  * che nella pipeline il controllo conti e scriva nel journal senza bloccare.

Casi reali: 10 degli 11 (18145, 18278, 171905 e 1262345, 1262398, 1262399,
1262402, 1262408, 1262411, 1262412). Manca il 1262406, fuso nel 1261867 il
30/09 (F4): `seo-rigenera` lo rifiuta, e semmai si guarda il master. Anche il
1262345 e' fuso (nel 1262082, F2), ma resta qui perche' e' l'unico con la pagina
ufficiale in mano: prova che una forma sostenuta dalla fonte non si segnala.

Il rilevatore vede solo le forme di partecipazione. 1262398, 1262402, 1262411
e 1262412 sbagliano su beneficiari e requisiti («enti no profit e del Terzo
Settore», «da almeno tre anni», «codice ATECO 03»), che per scelta non si
riconoscono in automatico: `--solo-controllo` e il salto «ancora segnalato»
di `seo-rigenera` non li fermano, e li' contano solo la regola 18 del prompt e
l'occhio di chi legge la prova. I test lo dichiarano con `attese = set()`.

Nessuna rete, nessun modello, nessun DB.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.supporto import carica_modulo

seo_skill = carica_modulo("seo_skill")
runner = carica_modulo("bando_seo_runner")
bilancio = carica_modulo("bilancio")


# ---------------------------------------------------------------------------
# Casi reali: estratti del `contenuto` pubblicato e fonte letta dal modello.
# `raw_data` e beneficiari sono quelli del DB (ridotti ai campi che contano).
# ---------------------------------------------------------------------------

def _contenuto(*frasi):
    return {"sections": [
        {"type": "h2", "text": "Chi può candidarsi"},
        {"type": "bullet_list", "items": [
            {"segments": [{"kind": "text", "text": f}]} for f in frasi
        ]},
    ]}


CASI_REALI = {
    18145: {
        "titolo_raw": "Toscana - Sovvenzioni a copertura delle spese di emissione di "
                      "obbligazioni, titoli di debito e delle commissioni di garanzia",
        "raw_data": {"source": "obiettivo_europa", "regions": ["Toscana"],
                     "beneficiaries": ["Imprese", "Micro-imprese", "Piccole Imprese",
                                       "PMI", "Società cooperative"]},
        "beneficiari": ["Imprese", "Micro-imprese", "Piccole Imprese", "PMI",
                        "Società cooperative"],
        "descrizione_breve": "Regione Toscana mette a disposizione 1,5 milioni di euro a "
                             "fondo perduto per coprire spese di emissione di obbligazioni.",
        "contenuto": _contenuto(
            "Micro-imprese e piccole imprese del territorio toscano;",
            "imprese in forma singola o associata;",
            "società cooperative operanti nei settori produttivi e dei servizi.",
        ),
        "attese": {"forma singola o associata"},
    },
    18278: {
        "titolo_raw": "CCIAA Basilicata - Bando voucher digitali I4.0",
        "raw_data": {"source": "obiettivo_europa", "regions": ["Basilicata"],
                     "beneficiaries": ["Imprese", "Imprese sociali/Società benefit"]},
        "beneficiari": ["Imprese", "Imprese sociali/Società benefit"],
        "descrizione_breve": "La Camera di Commercio della Basilicata mette a disposizione "
                             "140.000 euro a fondo perduto, rivolto a micro, piccole e medie "
                             "imprese.",
        "contenuto": _contenuto(
            "imprese sociali e società benefit con sede operativa in Basilicata;",
            "reti di imprese e aggregazioni che intendono collaborare con soggetti "
            "altamente qualificati nell'utilizzo delle tecnologie 4.0.",
        ),
        # «imprese sociali e società benefit» non e' segnalata: viene dalla
        # junction (sbagliata), che si corregge con l'SQL di `db`, non qui.
        "attese": {"reti di imprese", "aggregazioni"},
    },
    171905: {
        "titolo_raw": "MASE - Avviso pubblico per la presentazione di Progetti di ricerca, "
                      "sviluppo e innovazione tecnologica riguardanti l'area idrogeno",
        "raw_data": {"source": "obiettivo_europa", "budget": 82600000,
                     "beneficiaries": ["Imprese", "Università/Centri di ricerca"]},
        "beneficiari": ["Imprese", "Università/Centri di ricerca"],
        "descrizione_breve": "Il MASE finanzia con 82,6 milioni di euro a fondo perduto "
                             "progetti di ricerca sull'idrogeno.",
        "contenuto": _contenuto(
            "Imprese di qualsiasi dimensione operanti nei settori chimico, energetico, "
            "elettronico, ICT e ingegneristico, in forma singola o associata.",
            "Università e centri di ricerca pubblici e privati, anche in partenariato "
            "con soggetti industriali.",
            "Aggregazioni di soggetti in forma di partenariato pubblico-privato, con "
            "capofila identificato.",
        ),
        "attese": {"forma singola o associata", "aggregazioni", "partenariati", "capofila"},
    },
    1262345: {
        "titolo_raw": "Per saperne di più su Ricerca partner per co-progettazione e gestione "
                      "di interventi di promozione di attività di contrasto all'abbandono",
        "raw_data": None,
        "beneficiari": ["Enti no profit / Enti del Terzo Settore"],
        # Estratto della pagina ufficiale (bandi.regione.piemonte.it), letta il 30/09.
        "markdown": "PAGINA UFFICIALE: https://bandi.regione.piemonte.it/contributi-"
                    "finanziamenti/ricerca-partner\n\n... oppure le Associazioni Temporanee "
                    "di Scopo (ATS), costituite o costituende, tra uno o più Enti del Terzo "
                    "settore, di cui faccia parte un Centro di Servizio per il Volontariato, "
                    "con individuazione di un soggetto capofila.",
        "descrizione_breve": "La Regione Piemonte cerca partner del Terzo settore per "
                             "co-progettare interventi di ascolto contro l'abbandono sociale.",
        "contenuto": _contenuto(
            "Associazioni Temporanee di Scopo (ATS), costituite o costituende, tra uno o "
            "più enti del Terzo settore di cui faccia parte almeno un CSV, con "
            "individuazione di un soggetto capofila.",
        ),
        # Con la pagina, tutto e' sostenuto.
        "attese": set(),
    },
    1262399: {
        "titolo_raw": "Lombardia – Sismica: contributi ai Comuni per l'esercizio delle "
                      "funzioni in zone sismiche",
        "raw_data": {"source": "obiettivo_europa",
                     "beneficiaries": ["Enti pubblici", "Enti territoriali/Enti locali"]},
        "beneficiari": ["Enti pubblici", "Enti territoriali/Enti locali"],
        "descrizione_breve": "Regione Lombardia mette a disposizione 350.000 euro a fondo "
                             "perduto per i Comuni, singoli o associati, classificati in zona "
                             "sismica 2 e 3.",
        "contenuto": _contenuto(
            "Regione Lombardia stanzia 350.000 euro a fondo perduto a favore dei Comuni "
            "lombardi, singoli o associati, classificati in zona sismica 2 e 3.",
        ),
        "attese": {"forma singola o associata"},
    },
    1262402: {
        "titolo_raw": "Sicilia – Bando Spettacolo: Attività Musicali e Teatrali",
        "raw_data": {"source": "obiettivo_europa",
                     "beneficiaries": ["Enti no profit / Enti del Terzo Settore",
                                       "Enti pubblici"]},
        "beneficiari": ["Enti no profit / Enti del Terzo Settore", "Enti pubblici"],
        "descrizione_breve": "La Regione Siciliana mette a disposizione 4.961.500 euro a "
                             "fondo perduto per enti e fondazioni a partecipazione pubblica.",
        "contenuto": _contenuto(
            "Enti e fondazioni a partecipazione pubblica con sede legale in Sicilia da "
            "almeno tre anni e operanti nei settori della musica, del teatro e della danza.",
        ),
        # Fuori dal rilevatore: requisito inventato («da almeno tre anni»), non
        # una forma di partecipazione. Lo ferma solo il prompt.
        "attese": set(),
    },
    1262398: {
        "titolo_raw": "Toscana - Avviso pubblico per la concessione di incentivi per la "
                      "prevenzione dello spreco e delle eccedenze alimentari",
        "raw_data": {"source": "obiettivo_europa", "budget": 900000,
                     "beneficiaries": ["Enti no profit / Enti del Terzo Settore"]},
        "beneficiari": ["Enti no profit / Enti del Terzo Settore"],
        "descrizione_breve": "La Regione Toscana mette a disposizione 900.000 euro a fondo "
                             "perduto per enti del Terzo Settore che recuperano eccedenze "
                             "alimentari lungo la filiera agroalimentare.",
        "contenuto": _contenuto(
            "Il bando si rivolge agli enti no profit e agli enti del Terzo Settore attivi sul "
            "territorio toscano che operano nel recupero e nella ridistribuzione delle "
            "eccedenze alimentari per finalità sociali.",
        ),
        # Fuori dal rilevatore: beneficiari e requisiti, non forme di
        # partecipazione. Li ferma solo il prompt.
        "attese": set(),
    },
    1262408: {
        "titolo_raw": "GAL Valle D'Aosta – Bando PIF: Selezione di Progetti Integrati di "
                      "Filiera",
        "raw_data": {"source": "obiettivo_europa", "beneficiaries": ["Imprese"]},
        "beneficiari": ["Imprese"],
        "descrizione_breve": "Il GAL Valle d'Aosta mette a disposizione 2,57 milioni di euro "
                             "a fondo perduto per Progetti Integrati di Filiera.",
        "contenuto": _contenuto(
            "Le imprese interessate devono strutturare un partenariato composto da almeno "
            "tre soggetti di settori differenti e presentare un progetto integrato.",
        ),
        "attese": {"partenariati"},
    },
    1262412: {
        "titolo_raw": "Sicilia – Bando attuazione su indennizzi finanziari a copertura dei "
                      "maggiori costi di produzione sostenuti dalle imprese della pesca",
        "raw_data": {"source": "obiettivo_europa", "beneficiaries": ["Imprese"]},
        "beneficiari": ["Imprese"],
        "descrizione_breve": "La Regione Siciliana stanzia 12,1 milioni di euro a fondo perduto "
                             "per indennizzare le imprese della pesca e dell'acquacoltura.",
        "contenuto": _contenuto(
            "Il bando si rivolge alle imprese siciliane attive nei settori della pesca e "
            "dell'acquacoltura che hanno sostenuto maggiori costi di produzione riconducibili "
            "agli effetti economici del conflitto bellico in Medio Oriente sulla filiera ittica.",
            "Imprese che possono dimostrare l'incremento dei costi di produzione (carburante, "
            "mangimi, energia, materiali) determinato dalla crisi geopolitica.",
        ),
        # Fuori dal rilevatore: beneficiari e requisiti, non forme di
        # partecipazione. Li ferma solo il prompt.
        "attese": set(),
    },
    1262411: {
        "titolo_raw": "Emilia-Romagna – Bando per contributi ai fini dell'allineamento "
                      "canoni demanio idrico per acquacoltura",
        "raw_data": {"source": "obiettivo_europa", "beneficiaries": ["Imprese"]},
        "beneficiari": ["Imprese"],
        "descrizione_breve": "La Regione Emilia-Romagna mette a disposizione 20.000 euro a "
                             "fondo perduto per allineare i canoni del demanio idrico.",
        "contenuto": _contenuto(
            "essere imprese attive nel settore della pesca e acquacoltura (codice ATECO 03), "
            "con specifica attività di allevamento e raccolta di molluschi bivalvi;",
            "l'entità del contributo per singolo beneficiario è determinata dal "
            "differenziale tariffario applicato alla concessione posseduta.",
        ),
        "attese": set(),
    },
}


def contesto_del_caso(bando_id):
    caso = CASI_REALI[bando_id]
    return {
        "id": bando_id,
        "titolo_raw": caso["titolo_raw"],
        "descrizione_raw": None,
        "raw_data": caso["raw_data"] or {},
        "beneficiari": list(caso["beneficiari"]),
        "regioni": [], "settori": [], "codici_ateco": [],
        "tipologia": None, "modalita_erogazione": None, "programma": None,
        "data_pubblicazione": None, "data_apertura": None, "data_scadenza": "2026-10-30",
        "link_bando": "https://www.obiettivoeuropa.com/bandi/esempio",
        "tipo_link": None,
    }


def famiglie(affermazioni):
    return {famiglia for famiglia, _parole in affermazioni}


class TestCasiReali(unittest.TestCase):
    def test_le_forme_non_sostenute_dei_casi_reali_sono_segnalate(self):
        for bando_id, caso in CASI_REALI.items():
            with self.subTest(bando_id=bando_id):
                esito = seo_skill.affermazioni_del_payload(
                    caso, contesto_del_caso(bando_id), caso.get("markdown", ""),
                )
                self.assertEqual(famiglie(esito), caso["attese"])

    def test_i_tre_casi_di_bandofit_sono_tutti_segnalati(self):
        for bando_id in (18145, 18278, 171905):
            with self.subTest(bando_id=bando_id):
                caso = CASI_REALI[bando_id]
                self.assertTrue(seo_skill.affermazioni_del_payload(
                    caso, contesto_del_caso(bando_id)))

    def test_senza_la_pagina_il_1262345_risulta_non_sostenuto(self):
        # E' il motivo per cui `--solo-controllo`, che non legge la pagina, e'
        # una stima per eccesso.
        caso = CASI_REALI[1262345]
        esito = seo_skill.affermazioni_del_payload(caso, contesto_del_caso(1262345), "")
        self.assertEqual(famiglie(esito), {"raggruppamenti temporanei", "capofila"})

    def test_il_partenariato_del_171905_e_ammesso_se_la_fonte_lo_chiede(self):
        # Il decreto MASE 233/2026 (art. 4 c.1) vuole almeno due partner con
        # capofila: scritto con le parole della fonte e' giusto. «In forma
        # singola» resta non sostenuto, perche' la fonte chiede il contrario.
        fonte = "Art. 4: il progetto e' presentato da almeno due partner, di cui uno capofila."
        nuovo = "Le proposte sono presentate da almeno due partner, di cui uno capofila."
        self.assertEqual(seo_skill.affermazioni_non_sostenute(nuovo, fonte), ())
        vecchio = "imprese in forma singola o associata, anche in partenariato"
        self.assertEqual(
            famiglie(seo_skill.affermazioni_non_sostenute(vecchio, fonte)),
            {"forma singola o associata"},
        )

    def test_la_descrizione_breve_del_1262399_e_da_riscrivere(self):
        caso = CASI_REALI[1262399]
        fonte = seo_skill.fonte_del_bando(contesto_del_caso(1262399))
        self.assertTrue(seo_skill.affermazioni_non_sostenute(caso["descrizione_breve"], fonte))


class TestRiconoscimento(unittest.TestCase):
    def test_sigle_solo_in_maiuscolo_e_parole_intere(self):
        fonte = "Avviso per enti locali."
        self.assertEqual(seo_skill.affermazioni_non_sostenute("Stati membri e comuni", fonte), ())
        self.assertEqual(seo_skill.affermazioni_non_sostenute("le ats locali", fonte), ())
        self.assertEqual(
            famiglie(seo_skill.affermazioni_non_sostenute("anche costituite in ATI", fonte)),
            {"raggruppamenti temporanei"},
        )

    def test_spazi_e_a_capo_non_nascondono_la_formula(self):
        testo = "imprese in forma singola\no  associata"
        self.assertEqual(
            famiglie(seo_skill.affermazioni_non_sostenute(testo, "Bando per imprese")),
            {"forma singola o associata"},
        )

    def test_consorzi_sostenuti_dal_catalogo(self):
        ctx = {"beneficiari": ["Consorzi di tutela"], "titolo_raw": "Bando vini"}
        payload = {"descrizione_breve": "", "contenuto": _contenuto("consorzi di tutela del vino")}
        self.assertEqual(seo_skill.affermazioni_del_payload(payload, ctx), ())

    def test_testo_senza_forme_di_partecipazione(self):
        self.assertEqual(seo_skill.affermazioni_non_sostenute("", ""), ())
        self.assertEqual(
            seo_skill.affermazioni_non_sostenute("Possono partecipare le PMI.", ""), ())


class TestTestoDelContenuto(unittest.TestCase):
    def test_raccoglie_titoli_segmenti_e_faq_senza_url(self):
        contenuto = {"sections": [
            {"type": "h2", "text": "Chi può candidarsi"},
            {"type": "paragraph", "segments": [
                {"kind": "text", "text": "Le PMI"},
                {"kind": "link", "text": "sul portale", "url": "https://esempio.it/reti-di-imprese"},
            ]},
            {"type": "faq", "items": [
                {"q": "Chi partecipa?", "a": {"segments": [{"kind": "text", "text": "Le PMI."}]}},
            ]},
        ]}
        testo = seo_skill.testo_del_contenuto(contenuto)
        for pezzo in ("Chi può candidarsi", "Le PMI", "sul portale", "Chi partecipa?"):
            self.assertIn(pezzo, testo)
        self.assertNotIn("https://", testo)

    def test_contenuto_salvato_come_stringa_json(self):
        import json
        testo = seo_skill.testo_del_contenuto(json.dumps(_contenuto("reti di imprese")))
        self.assertIn("reti di imprese", testo)

    def test_stringa_non_json_e_gia_testo(self):
        self.assertEqual(seo_skill.testo_del_contenuto("testo libero"), "testo libero")
        self.assertEqual(seo_skill.testo_del_contenuto(None), "")


class TestPrompt(unittest.TestCase):
    def test_regola_18_nel_system_prompt(self):
        prompt = seo_skill.SEO_SYSTEM_PROMPT
        self.assertIn("18. **Chi partecipa e a quali condizioni", prompt)
        for formula in ("in forma singola o associata", "reti di imprese", "aggregazioni",
                        "partenariati", "capofila", "Errori comuni"):
            self.assertIn(formula, prompt)
        self.assertIn("Se la fonte non dice niente, il testo non dice niente", prompt)

    def test_errori_comuni_della_guida_rimandano_alla_regola_18(self):
        self.assertIn('"Errori comuni" (solo alle condizioni della regola 18)',
                      seo_skill.SEO_SYSTEM_PROMPT)

    def test_il_prompt_dei_casi_reali_porta_fonte_e_istruzione(self):
        for bando_id, caso in CASI_REALI.items():
            with self.subTest(bando_id=bando_id):
                prompt = seo_skill._build_seo_prompt(
                    contesto_del_caso(bando_id), caso.get("markdown", ""))
                self.assertIn("6. Chi può partecipare, in quale forma e con quali requisiti",
                              prompt)
                for beneficiario in caso["beneficiari"]:
                    self.assertIn(beneficiario, prompt)
                if caso["raw_data"]:
                    self.assertIn("obiettivo_europa", prompt)


class TestSpesaRegistrata(unittest.TestCase):
    """`_call_anthropic_tool` somma la spesa solo se riceve i contatori."""

    def _cliente(self):
        risposta = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="save_seo_bando", input={"a": 1})],
            usage={"input_tokens": 1000, "output_tokens": 100},
        )
        return SimpleNamespace(messages=SimpleNamespace(create=mock.AsyncMock(return_value=risposta)))

    def test_con_contatori_la_chiamata_ha_un_costo(self):
        contatori = bilancio.Contatori()
        esito = asyncio.run(seo_skill._call_anthropic_tool(
            self._cliente(), "claude-opus-4-7", 100, "s", "u", seo_skill.SAVE_SEO_BANDO_TOOL,
            contatori=contatori, listino={"claude-opus-4-7": (5.0, 25.0)},
        ))
        self.assertEqual(esito, {"a": 1})
        self.assertEqual(contatori.chiamate, 1)
        self.assertAlmostEqual(contatori.usd, (1000 * 5.0 + 100 * 25.0) / 1_000_000)

    def test_senza_contatori_nessun_conto(self):
        esito = asyncio.run(seo_skill._call_anthropic_tool(
            self._cliente(), "claude-opus-4-7", 100, "s", "u", seo_skill.SAVE_SEO_BANDO_TOOL,
        ))
        self.assertEqual(esito, {"a": 1})


class TestPipeline(unittest.TestCase):
    """Nella pipeline il controllo avvisa e conta: non blocca e non spende."""

    def _esegui(self, testo):
        payload = {"slug": "x", "titolo": "T", "descrizione_breve": "",
                   "contenuto": _contenuto(testo), "livello": "flash_bando"}
        arricchisci = mock.AsyncMock(return_value=dict(payload))
        registro = mock.MagicMock()
        with mock.patch.object(runner, "select_bandi_to_complete",
                               return_value=[{"id": 7, "link_bando": ""}]), \
             mock.patch.object(runner, "load_catalogo", return_value={}), \
             mock.patch.object(runner, "build_bando_input_context",
                               side_effect=lambda b, c: {"id": b["id"], "beneficiari": ["Imprese"],
                                                         "titolo_raw": "Bando per imprese"}), \
             mock.patch.object(runner, "_link_del_bando", return_value=([], False)), \
             mock.patch.object(runner, "enrich_seo", new=arricchisci), \
             mock.patch.object(runner, "update_bando_completed",
                               new=mock.AsyncMock(return_value=True)) as aggiorna, \
             mock.patch.object(runner, "logger", registro), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEDUP_CANONICAL", None)
            contatori = asyncio.run(runner.run())
        return contatori, aggiorna, arricchisci, registro

    def test_affermazione_non_sostenuta_contata_e_nel_journal_senza_blocco(self):
        contatori, aggiorna, _arr, registro = self._esegui("imprese in forma singola o associata")
        self.assertEqual(contatori["affermazioni_non_sostenute"], 1)
        self.assertEqual(aggiorna.await_count, 1)       # pubblicato lo stesso
        avvisi = [c for c in registro.warning.call_args_list
                  if "affermazioni non sostenute" in str(c.args[0])]
        self.assertEqual(len(avvisi), 1)
        self.assertEqual(avvisi[0].args[1], 7)          # l'id nel journal

    def test_testo_pulito_nessun_avviso(self):
        contatori, aggiorna, _arr, _reg = self._esegui("Possono partecipare le imprese.")
        self.assertEqual(contatori["affermazioni_non_sostenute"], 0)
        self.assertEqual(aggiorna.await_count, 1)

    def test_la_pipeline_non_passa_contatori(self):
        # RIPRESA §5.10: la riga del giro resta quella di prima.
        _c, _a, arricchisci, _r = self._esegui("testo")
        self.assertIsNone(arricchisci.await_args.kwargs.get("contatori"))


if __name__ == "__main__":
    unittest.main()
