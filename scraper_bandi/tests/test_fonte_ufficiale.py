# -*- coding: utf-8 -*-
"""Resolver della fonte ufficiale: cascata, punteggio e gate (piano §5).

Nessuna rete e nessun DB: lo scarico, la sonda, la ricerca, l'arbitro e SEDIA
arrivano dall'`Ambiente`, che nei test e' fatto di dizionari e di funzioni
finte. Le scritture passano da un `db.Controllo` con lo schema iniettato.

I contro-esempi sono il cuore del file: la pagina indice dell'ente, il
soft-404, il dominio dedotto, il calendario e l'arbitro che non promuove sono
i cinque modi in cui un resolver ingenuo pubblicherebbe il link sbagliato.
"""
import asyncio
import unittest
import unittest.mock
from datetime import date
from typing import Any

from tests.supporto import carica_modulo

fu = carica_modulo("fonte_ufficiale")
bilancio = carica_modulo("bilancio")
dominio_ufficiale = carica_modulo("dominio_ufficiale")
db = carica_modulo("db")
oe = carica_modulo("oe_scheda")


TITOLO = "Contributi per la formazione professionale 2026"
ENTE = "Regione Marche"
SCADENZA = date(2026, 9, 30)
IMPORTO = 1_000_000
URL_BUONO = "https://regione.marche.it/bandi/contributi-formazione-professionale-2026"
URL_INDICE = "https://regione.marche.it/bandi"
URL_PDF = "https://regione.marche.it/bandi/avviso-formazione.pdf"

# Testo lungo abbastanza da superare il gate dei 500 caratteri: sotto quella
# soglia una pagina non prova niente, e nessun punteggio viene nemmeno calcolato.
RIEMPITIVO = (
    "Il presente avviso disciplina le modalita' di presentazione delle domande "
    "di contributo per i percorsi di formazione professionale rivolti alle "
    "imprese e ai lavoratori del territorio regionale, secondo quanto previsto "
    "dalla normativa vigente e dalle disposizioni attuative adottate "
    "dall'amministrazione competente in materia di politiche del lavoro. "
) * 3


def tabella(*righe):
    """Whitelist di prova: le righe passate piu' il seed (blocklist compresa)."""
    return dominio_ufficiale.costruisci(righe=list(righe))


TABELLA_ENTE = tabella(
    dominio_ufficiale.Dominio(host="regione.marche.it", tipo="ente", confidenza=1.0,
                              ente="Regione Marche"),
)
TABELLA_DEDOTTA = tabella(
    dominio_ufficiale.Dominio(host="formazione-marche.it", tipo="dedotto", confidenza=0.6),
)


def pagina(url, *, stato=200, titolo=TITOLO, corpo="", extra_html=""):
    corpo_completo = f"{corpo} {RIEMPITIVO}"
    html = (
        f"<html><head><title>{titolo} — {ENTE}</title>"
        f'<meta property="og:title" content="{titolo}"></head>'
        f"<body><h1>{titolo}</h1><p>{corpo_completo}</p>{extra_html}</body></html>"
    )
    return fu.Pagina(
        url=url, stato=stato, html=html,
        testo=f"{titolo} {ENTE}\n{corpo_completo}",
        intestazioni=fu.intestazioni_pagina(html),
    )


def contesto(tab=TABELLA_ENTE, **kwargs):
    valori = dict(
        bando_id=1, titolo=TITOLO, ente=ENTE, data_scadenza=SCADENZA, importo=IMPORTO,
        tabella=tab,
    )
    valori.update(kwargs)
    return fu.Contesto(**valori)


def candidato(url=URL_BUONO, pag=None, **kwargs):
    return fu.Candidato(url=url, pagina=pag if pag is not None else pagina(url), **kwargs)


def ambiente(pagine=None, **kwargs):
    mappa = pagine or {}

    async def scarica(url):
        if url in mappa:
            return mappa[url]
        return fu.Pagina(url=url, stato=404)

    parametri = dict(tabella=TABELLA_ENTE, scarica=scarica)
    parametri.update(kwargs)
    return fu.Ambiente(**parametri)


def esegui(coroutine):
    return asyncio.run(coroutine)


CORPO_COMPLETO = (
    "Le domande devono essere presentate entro il 30/09/2026. "
    "La dotazione complessiva e' pari a 1.000.000 di euro."
)


class TestPunteggioPieno(unittest.TestCase):
    def test_pagina_giusta_e_trovata(self):
        c = candidato(pag=pagina(URL_BUONO, corpo=CORPO_COMPLETO))
        p = fu.punteggia(c, contesto())
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)
        self.assertEqual(p.segnali, fu.SEGNALI_RICHIESTI)
        self.assertEqual(p.stato, fu.STATO_TROVATA)
        self.assertEqual(p.tipo, "ente")

    def test_il_totale_e_la_somma_delle_voci(self):
        # Il punteggio deve restare rifacibile a mano da chi rilegge un esito.
        p = fu.punteggia(candidato(pag=pagina(URL_BUONO, corpo=CORPO_COMPLETO)), contesto())
        self.assertEqual(p.valore, sum(punti for _, punti in p.voci))
        self.assertIn(("dominio", fu.PUNTI["dominio_ente"]), p.voci)
        self.assertIn(("titolo", fu.PUNTI["titolo_alto"]), p.voci)
        self.assertIn(("scadenza", fu.PUNTI["scadenza"]), p.voci)
        self.assertIn(("strutturata", fu.PUNTI["strutturata"]), p.voci)

    def test_senza_segnale_di_contenuto_resta_in_verifica(self):
        # 30 + 25 + 10 + 10 = 75: sopra la soglia, ma la pagina non conferma
        # nessun fatto del bando. §5: «≥70 senza segnale di contenuto →
        # in_verifica».
        p = fu.punteggia(candidato(pag=pagina(URL_BUONO)), contesto())
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)
        self.assertNotIn(fu.SEGNALE_CONTENUTO, p.segnali)
        self.assertEqual(p.stato, fu.STATO_IN_VERIFICA)

    def test_titolo_dal_corpo_non_conta(self):
        # Un ente che elenca cento bandi in home ha nel corpo i token di tutti:
        # il Jaccard si misura solo su <title>/h1/og:title.
        pag = fu.Pagina(
            url=URL_BUONO, stato=200,
            html="<html><head><title>Portale</title></head><body></body></html>",
            testo=f"{TITOLO} {RIEMPITIVO}",
            intestazioni="Portale",
        )
        p = fu.punteggia(candidato(pag=pag), contesto())
        self.assertNotIn(fu.SEGNALE_TITOLO, p.segnali)

    def test_scadenza_diversa_toglie_punti_e_segnala_la_proroga(self):
        corpo = "Le domande devono essere presentate entro il 31/10/2026."
        p = fu.punteggia(candidato(pag=pagina(URL_BUONO, corpo=corpo)), contesto())
        self.assertIn(("scadenza_diversa", fu.PUNTI["scadenza_diversa"]), p.voci)
        self.assertTrue(p.proroga)
        self.assertNotIn(fu.SEGNALE_CONTENUTO, p.segnali)

    def test_pdf_dell_atto_sul_dominio(self):
        extra = '<a href="https://regione.marche.it/avviso-formazione.pdf">Avviso</a>'
        p = fu.punteggia(
            candidato(pag=pagina(URL_BUONO, corpo=CORPO_COMPLETO, extra_html=extra)),
            contesto(),
        )
        self.assertIn(("pdf_atto", fu.PUNTI["pdf_atto"]), p.voci)

    def test_fonte_che_e_l_atto(self):
        url = "https://regione.marche.it/bandi/dd-55-2026-formazione.pdf"
        p = fu.punteggia(
            candidato(url=url, pag=pagina(url, corpo=CORPO_COMPLETO), ancora="Decreto 55/2026"),
            contesto(numero_atto="decreto:55/2026"),
        )
        self.assertTrue(p.e_atto)


class TestGateDuri(unittest.TestCase):
    """I cinque modi di pubblicare il link sbagliato, uno per test."""

    def _falliti(self, c, ctx=None):
        return fu.punteggia(c, ctx or contesto()).falliti()

    def test_aggregatore_mai(self):
        url = "https://www.obiettivoeuropa.com/bandi/formazione-2026"
        p = fu.punteggia(candidato(url=url, pag=pagina(url, corpo=CORPO_COMPLETO)), contesto())
        self.assertIn("blocklist", p.falliti())
        self.assertEqual(p.stato, fu.STATO_NON_TROVATA)

    def test_dominio_sconosciuto_mai(self):
        url = "https://formazione-privata.example/bando"
        p = fu.punteggia(candidato(url=url, pag=pagina(url, corpo=CORPO_COMPLETO)), contesto())
        self.assertIn("whitelist", p.falliti())
        self.assertEqual(p.stato, fu.STATO_NON_TROVATA)

    def test_testo_troppo_corto(self):
        corta = fu.Pagina(url=URL_BUONO, stato=200, html="<p>ok</p>", testo="ok" * 10,
                          intestazioni=TITOLO)
        p = fu.punteggia(candidato(pag=corta), contesto())
        self.assertIn("http_2xx_500", p.falliti())
        self.assertEqual(p.valore, 0)
        self.assertEqual(p.stato, fu.STATO_NON_TROVATA)

    def test_404_non_e_una_fonte(self):
        p = fu.punteggia(candidato(pag=pagina(URL_BUONO, stato=404)), contesto())
        self.assertIn("http_2xx_500", p.falliti())

    def test_soft_404_trattato_come_404(self):
        # 200 con «Pagina non trovata» e nessun token del titolo: un 404
        # travestito, che senza questo gate passerebbe i 500 caratteri.
        pag = fu.Pagina(
            url=URL_BUONO, stato=200,
            html="<html><head><title>Errore</title></head><body></body></html>",
            testo="Pagina non trovata. " + "Torna alla home del portale. " * 30,
            intestazioni="Errore",
        )
        p = fu.punteggia(candidato(pag=pag), contesto())
        self.assertIn("non_soft_404", p.falliti())
        self.assertEqual(p.stato, fu.STATO_NON_TROVATA)

    def test_pagina_indice_dell_ente_non_e_trovata(self):
        # L'elenco dei bandi della regione: dominio giusto, titoli giusti,
        # contenuto ricco. E' il falso positivo piu' facile da produrre.
        p = fu.punteggia(
            candidato(url=URL_INDICE, pag=pagina(URL_INDICE, corpo=CORPO_COMPLETO)),
            contesto(),
        )
        self.assertIn("non_indice", p.falliti())
        self.assertEqual(p.stato, fu.STATO_IN_VERIFICA)
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)

    def test_titolo_di_sezione_senza_token_del_titolo(self):
        pag = fu.Pagina(
            url="https://regione.marche.it/finanziamenti/scheda-42", stato=200,
            html="<html><head><title>Finanziamenti</title></head><body></body></html>",
            testo=f"{CORPO_COMPLETO} {RIEMPITIVO}",
            intestazioni="Finanziamenti",
        )
        p = fu.punteggia(candidato(url=pag.url, pag=pag), contesto())
        self.assertIn("non_indice", p.falliti())
        self.assertNotEqual(p.stato, fu.STATO_TROVATA)

    def test_dominio_dedotto_al_massimo_in_verifica(self):
        url = "https://formazione-marche.it/bando-2026"
        p = fu.punteggia(
            candidato(url=url, pag=pagina(url, corpo=CORPO_COMPLETO)),
            contesto(tab=TABELLA_DEDOTTA),
        )
        self.assertIn("dominio_provato", p.falliti())
        self.assertNotEqual(p.stato, fu.STATO_TROVATA)
        self.assertIsNone(p.tipo, "un dominio dedotto non e' un valore di fonte_ufficiale_tipo")

    def test_calendario_non_vale_mai_trovata(self):
        # A11/A32: punteggio pieno, dominio d'ente, tre segnali — e nonostante
        # tutto il tipo dichiarato lo ferma a `in_verifica`.
        c = candidato(pag=pagina(URL_BUONO, corpo=CORPO_COMPLETO), tipo_dichiarato="calendario")
        p = fu.punteggia(c, contesto())
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)
        self.assertEqual(p.segnali, fu.SEGNALI_RICHIESTI)
        self.assertEqual(p.stato, fu.STATO_IN_VERIFICA)

    def test_pattern_istituzionale_e_trovata_con_tipo_nullo(self):
        # `regione.*.it` riconosce l'host per forma: 25 punti di dominio, che
        # §5 assegna proprio perche' quel caso possa arrivare a 70. Il tipo
        # resta NULL — A11 ammette in colonna solo `ente` e `portale_pubblico`
        # — e il CHECK della 01 ammette NULL: bloccare qui l'esito fermerebbe a
        # `in_verifica` tutta la fetta regionale, che e' la piu' grande.
        p = fu.punteggia(
            candidato(pag=pagina(URL_BUONO, corpo=CORPO_COMPLETO)),
            contesto(tab=tabella()),
        )
        self.assertIsNone(p.tipo)
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)
        self.assertEqual(p.segnali, fu.SEGNALI_RICHIESTI)
        self.assertEqual(p.stato, fu.STATO_TROVATA)
        # E la colonna che ne nasce e' NULL, non una stringa inventata.
        esito = fu.Esito(bando_id=1, stato=p.stato, url=URL_BUONO, tipo=p.tipo)
        self.assertIsNone(fu.payload_fonte(esito, link_id=1)["fonte_ufficiale_tipo"])


class TestArbitro(unittest.TestCase):
    def _grigi(self):
        """Due candidati in zona grigia: dominio + titolo medio + strutturata."""
        pagine = {}
        candidati = []
        for suffisso in ("scheda-a", "scheda-b"):
            url = f"https://regione.marche.it/finanziamenti/{suffisso}"
            pag = fu.Pagina(
                url=url, stato=200,
                html=f"<html><head><title>Formazione professionale {suffisso}</title>"
                     f"</head><body><h1>Formazione professionale</h1></body></html>",
                testo=RIEMPITIVO,
                intestazioni=f"Formazione professionale {suffisso}",
            )
            pagine[url] = pag
            candidati.append(fu.Candidato(url=url, pagina=pag))
        return candidati, pagine

    def test_zona_grigia_riconosciuta(self):
        candidati, _ = self._grigi()
        valutati = [(c, fu.punteggia(c, contesto())) for c in candidati]
        for _, p in valutati:
            self.assertTrue(fu.SOGLIA_VERIFICA <= p.valore < fu.SOGLIA_TROVATA, p.valore)
        self.assertEqual(len(fu.zona_grigia(valutati)), 2)

    def test_arbitro_non_promuove_ma_segna_il_prioritario(self):
        candidati, _ = self._grigi()
        valutati = [(c, fu.punteggia(c, contesto())) for c in candidati]

        async def arbitro(_ctx, _candidati):
            return 1

        amb = ambiente(arbitro=arbitro)
        scelto = esegui(fu._passo_arbitro(contesto(), valutati, amb))
        self.assertEqual(scelto, candidati[1].url)
        self.assertEqual(amb.contatori.arbitri, 1)
        # E nessun punteggio e' cambiato: l'arbitro sceglie, non vota.
        self.assertEqual([p.valore for _, p in valutati],
                         [fu.punteggia(c, contesto()).valore for c in candidati])

    def test_arbitro_con_un_solo_candidato_non_viene_chiamato(self):
        candidati, _ = self._grigi()
        valutati = [(candidati[0], fu.punteggia(candidati[0], contesto()))]
        chiamate = []

        async def arbitro(_ctx, _candidati):
            chiamate.append(1)
            return 0

        amb = ambiente(arbitro=arbitro)
        self.assertIsNone(esegui(fu._passo_arbitro(contesto(), valutati, amb)))
        self.assertEqual(chiamate, [])

    def test_indice_fuori_intervallo_ignorato(self):
        # Un indice inventato non si «aggiusta» con un clamp: darebbe per buona
        # una scelta che il modello non ha fatto.
        candidati, _ = self._grigi()
        valutati = [(c, fu.punteggia(c, contesto())) for c in candidati]

        async def arbitro(_ctx, _candidati):
            return 7

        self.assertIsNone(esegui(fu._passo_arbitro(contesto(), valutati, ambiente(arbitro=arbitro))))

    def test_url_inventato_non_puo_entrare(self):
        # L'arbitro sceglie per indice: non c'e' modo di far entrare un URL
        # nuovo, e un valore non intero viene scartato.
        candidati, _ = self._grigi()
        valutati = [(c, fu.punteggia(c, contesto())) for c in candidati]

        async def arbitro(_ctx, _candidati):
            return "https://sito-inventato.example/bando"

        self.assertIsNone(esegui(fu._passo_arbitro(contesto(), valutati, ambiente(arbitro=arbitro))))


class TestCascata(unittest.TestCase):
    def _bando(self, **kwargs):
        valori = {
            "id": 1, "titolo": TITOLO, "ente_erogatore": ENTE,
            "data_scadenza": "2026-09-30", "importo_totale_eur": IMPORTO,
            "raw_data": {"external_link": URL_BUONO},
        }
        valori.update(kwargs)
        return valori

    def test_passo_1_basta_e_ferma_la_cascata(self):
        chiamate = {"sonda": 0, "ricerca": 0}

        async def sonda(_ctx, _host):
            chiamate["sonda"] += 1
            return []

        async def ricerca(_query, _domini):
            chiamate["ricerca"] += 1
            return []

        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            sonda=sonda, ricerca=ricerca,
        )
        esito = esegui(fu.risolvi(self._bando(), amb))
        self.assertEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(esito.url, URL_BUONO)
        self.assertEqual(esito.metodo, "link_strutturato")
        self.assertEqual(chiamate, {"sonda": 0, "ricerca": 0})
        self.assertEqual(amb.contatori.trovate, 1)

    def test_link_verso_l_aggregatore_non_e_un_candidato(self):
        bando = self._bando(
            raw_data={}, link_bando="https://www.obiettivoeuropa.com/bandi/x",
        )
        self.assertEqual(fu.candidati_strutturati(bando, tabella=TABELLA_ENTE), ())

    def test_deep_link_del_contenuto(self):
        bando = self._bando(raw_data={}, contenuto={
            "sections": [{"segments": [
                {"kind": "link", "url": URL_BUONO, "text": "avviso"},
                {"kind": "link", "url": "https://fasi.eu/bando", "text": "aggregatore"},
            ]}],
        })
        urls = [c.url for c in fu.candidati_strutturati(bando, tabella=TABELLA_ENTE)]
        self.assertEqual(urls, [URL_BUONO])

    def test_source_url_del_calendario_e_dichiarato_calendario(self):
        bando = self._bando(raw_data={"source_url": URL_BUONO})
        candidati = fu.candidati_strutturati(bando, tabella=TABELLA_ENTE)
        self.assertEqual([c.tipo_dichiarato for c in candidati], ["calendario"])

    def test_gemello_eredita_la_fonte(self):
        link_oe = "https://www.obiettivoeuropa.com/bandi/formazione-2026"
        bando = self._bando(raw_data={}, link_bando=link_oe)
        pubblicato = {
            "id": 99, "link_bando": link_oe, "fonte_ufficiale_url": URL_BUONO,
            "fonte_ufficiale_stato": "trovata", "titolo": TITOLO,
        }
        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            pubblicati=[pubblicato],
        )
        esito = esegui(fu.risolvi(bando, amb))
        self.assertEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(esito.metodo, "gemello")
        self.assertEqual(amb.contatori.gemelli, 1)

    def test_gemello_senza_fonte_non_eredita_niente(self):
        link_oe = "https://www.obiettivoeuropa.com/bandi/formazione-2026"
        bando = self._bando(raw_data={}, link_bando=link_oe)
        pubblicato = {
            "id": 99, "link_bando": link_oe, "fonte_ufficiale_stato": "in_verifica",
            "fonte_ufficiale_url": None, "titolo": TITOLO,
        }
        amb = ambiente(pubblicati=[pubblicato])
        esito = esegui(fu.risolvi(bando, amb))
        self.assertEqual(esito.stato, fu.STATO_NON_TROVATA)
        self.assertEqual(amb.contatori.gemelli, 0)

    def test_la_ricerca_e_l_ultima_e_costa_due_crediti(self):
        query = []

        async def ricerca(testo, domini):
            query.append((testo, tuple(domini)))
            return [URL_BUONO]

        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            ricerca=ricerca,
        )
        esito = esegui(fu.risolvi(self._bando(raw_data={}), amb))
        self.assertEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(esito.metodo, fu.METODO_RICERCA)
        self.assertEqual(len(query), 1)
        self.assertEqual(amb.spesa.crediti_firecrawl, 2)
        self.assertEqual(amb.contatori.ricerche, 1)

    def test_su_segnale_la_ricerca_non_parte(self):
        chiamate = []

        async def ricerca(_testo, _domini):
            chiamate.append(1)
            return [URL_BUONO]

        amb = ambiente(ricerca=ricerca, da_segnale=True)
        esegui(fu.risolvi(self._bando(raw_data={}), amb))
        self.assertEqual(chiamate, [])
        self.assertEqual(amb.contatori.ricerche, 0)
        self.assertEqual(amb.contatori.ricerche_da_segnale, 1)

    def test_il_tetto_ferma_la_ricerca(self):
        chiamate = []

        async def ricerca(_testo, _domini):
            chiamate.append(1)
            return []

        spesa = bilancio.Contatori(ricerche=5)
        amb = ambiente(
            ricerca=ricerca, spesa=spesa, tetti=bilancio.Tetti(ricerche_giorno=5),
        )
        esegui(fu.risolvi(self._bando(raw_data={}), amb))
        self.assertEqual(chiamate, [])
        self.assertTrue(amb.contatori.interrotto_per_tetto)

    def test_sonda_prima_della_ricerca(self):
        ordine = []

        async def sonda(_ctx, host):
            ordine.append(f"sonda:{host}")
            return [URL_BUONO]

        async def ricerca(_testo, _domini):
            ordine.append("ricerca")
            return []

        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            sonda=sonda, ricerca=ricerca,
        )
        bando = self._bando(raw_data={}, link_bando="https://regione.marche.it/portale")
        esito = esegui(fu.risolvi(bando, amb))
        self.assertEqual(ordine, ["sonda:regione.marche.it"])
        self.assertEqual(esito.metodo, fu.METODO_SONDA)

    def test_candidati_dalla_scheda_oe_portano_la_prova(self):
        html = (
            "<html><body><h2>Link e Documenti</h2>"
            f'<div class="prose"><p><a href="{URL_BUONO}">Sito</a></p></div>'
            "</body></html>"
        )
        scheda = oe.analizza(html, "https://www.obiettivoeuropa.com/bandi/x")

        async def scheda_oe(_bando):
            return scheda

        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            scheda_oe=scheda_oe,
        )
        esito = esegui(fu.risolvi(self._bando(raw_data={}), amb))
        self.assertEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(esito.metodo, "oe_scheda")
        self.assertIn("#", esito.prova)
        self.assertEqual(esito.url_prova, "https://www.obiettivoeuropa.com/bandi/x")

    def test_allegati_solo_sulla_pagina_scelta(self):
        extra = '<main><a href="https://regione.marche.it/modulo-domanda.pdf">Modulo</a></main>'
        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO, extra_html=extra)},
            verifica_allegato=lambda _url: (200, "application/pdf", "", None, None),
        )
        esito = esegui(fu.risolvi(self._bando(), amb))
        self.assertEqual([a["url"] for a in esito.allegati],
                         ["https://regione.marche.it/modulo-domanda.pdf"])
        self.assertEqual(set(esito.allegati[0]), {"label", "url", "tipo"})

    def test_nessun_candidato_e_non_trovata(self):
        amb = ambiente()
        esito = esegui(fu.risolvi(self._bando(raw_data={}), amb))
        self.assertEqual(esito.stato, fu.STATO_NON_TROVATA)
        self.assertIsNone(esito.url)
        self.assertEqual(amb.contatori.non_trovate, 1)


class TestCadenze(unittest.TestCase):
    OGGI = date(2026, 9, 23)

    def test_in_verifica_quattordici_giorni_per_tre_volte(self):
        for tentativi, giorni in ((0, 14), (1, 14), (2, 14), (3, 60), (9, 60)):
            with self.subTest(tentativi=tentativi):
                data, priorita, nuovi = fu.prossimo_controllo(
                    fu.STATO_IN_VERIFICA, tentativi, self.OGGI,
                )
                self.assertEqual((data - self.OGGI).days, giorni)
                self.assertEqual(priorita, fu.PRIORITA_IN_VERIFICA)
                self.assertEqual(nuovi, tentativi + 1)

    def test_non_trovata_sempre_sessanta(self):
        for tentativi in (0, 5, 50):
            data, priorita, _ = fu.prossimo_controllo(
                fu.STATO_NON_TROVATA, tentativi, self.OGGI,
            )
            self.assertEqual((data - self.OGGI).days, fu.GIORNI_RICONTROLLO_LUNGO)
            self.assertEqual(priorita, fu.PRIORITA_NON_TROVATA)

    def test_trovata_non_torna_al_resolver(self):
        data, priorita, _ = fu.prossimo_controllo(fu.STATO_TROVATA, 0, self.OGGI)
        self.assertEqual((data - self.OGGI).days, fu.GIORNI_RICONTROLLO_LUNGO)
        self.assertEqual(priorita, fu.PRIORITA_TROVATA)

    def test_scaduto_solo_quando_la_data_e_passata(self):
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": "2026-09-23"}, self.OGGI))
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": "2026-09-01"}, self.OGGI))
        self.assertFalse(fu.scaduto({"prossimo_controllo_at": "2026-10-07"}, self.OGGI))

    def test_senza_riga_di_controllo_si_ricontrolla(self):
        self.assertTrue(fu.scaduto(None, self.OGGI))
        self.assertTrue(fu.scaduto({}, self.OGGI))
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": None}, self.OGGI))

    def test_forza_ignora_la_data(self):
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": "2099-01-01"}, self.OGGI, True))

    def test_data_illeggibile_non_nasconde_la_riga_per_sempre(self):
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": "domani"}, self.OGGI))


class TestScritture(unittest.TestCase):
    """Il resolver scrive poco e passa sempre da `db.controllo`."""

    def _controllo(self, colonne=None, rpc=()):
        definizioni = {
            nome: {"properties": {c: {} for c in cols}}
            for nome, cols in (colonne or {}).items()
        }
        schema = {
            "definitions": definizioni,
            "paths": {f"/rpc/{n}": {} for n in rpc},
        }
        return db.Controllo(fornitore_schema=lambda: schema)

    def _esito(self, stato=fu.STATO_TROVATA, **extra):
        valori = dict(
            bando_id=7, stato=stato, url=URL_BUONO, host="regione.marche.it",
            tipo="ente", confidenza=90, metodo="link_strutturato", esito_http=200,
            prossimo_controllo=date(2026, 10, 7), priorita=30, tentativi=1,
        )
        valori.update(extra)
        return fu.Esito(**valori)

    def test_payload_degrada_senza_link_id(self):
        # `trovata` senza `fonte_ufficiale_link_id` viola il CHECK della 03.
        payload = fu.payload_fonte(self._esito(), link_id=None)
        self.assertEqual(payload["fonte_ufficiale_stato"], fu.STATO_IN_VERIFICA)
        self.assertIsNone(payload["fonte_ufficiale_url"])
        pieno = fu.payload_fonte(self._esito(), link_id=12)
        self.assertEqual(pieno["fonte_ufficiale_stato"], fu.STATO_TROVATA)
        self.assertEqual(pieno["fonte_ufficiale_link_id"], 12)

    def test_il_resolver_non_scrive_altre_colonne(self):
        with self.assertRaises(db.PayloadBandoVietato):
            db.aggiorna_fonte_ufficiale(1, {"slug": "nuovo-slug"})
        with self.assertRaises(db.PayloadBandoVietato):
            db.aggiorna_fonte_ufficiale(1, {"stato_processing": "completed"})

    def test_html_e_impronte_non_arrivano_a_bando(self):
        # L'assert del chokepoint di §5: la scheda OE non finisce in tabella.
        for chiave in ("testo_norm", "oe_html", "impronta_contenuto", "impronte_sezioni"):
            with self.subTest(chiave=chiave):
                with self.assertRaises(db.PayloadBandoVietato):
                    db.assicura_payload_bando({chiave: "x"})
        db.assicura_payload_bando({"fonte_ufficiale_url": URL_BUONO})

    def test_e_atto_non_e_una_colonna_di_bando(self):
        # La vista lo calcola con un EXISTS su `bando_link.tipo = 'atto'`
        # (migrazione 05): scriverlo su `bando` darebbe una colonna che non
        # esiste, ignorata in silenzio, e un flag sempre falso.
        payload = fu.payload_fonte(self._esito(), link_id=3)
        self.assertNotIn("fonte_ufficiale_e_atto", payload)
        self.assertNotIn("fonte_ufficiale_e_atto", db.COLONNE_FONTE_UFFICIALE)
        with self.assertRaises(db.PayloadBandoVietato):
            db.aggiorna_fonte_ufficiale(1, {"fonte_ufficiale_e_atto": True})

    def test_l_atto_si_esprime_con_il_tipo_del_link(self):
        atto = fu.Esito(
            bando_id=7, stato=fu.STATO_TROVATA, url=URL_BUONO, e_atto=True,
        )
        self.assertEqual(fu.righe_link(atto, tabella=TABELLA_ENTE)[0]["tipo"], "atto")
        self.assertEqual(
            fu.righe_link(self._esito(), tabella=TABELLA_ENTE)[0]["tipo"], "pagina_bando",
        )

    def test_payload_fonte_scrive_solo_colonne_ammesse(self):
        payload = fu.payload_fonte(self._esito(), link_id=3)
        self.assertEqual(set(payload), set(db.COLONNE_FONTE_UFFICIALE))

    def test_righe_link_pubblicabili_solo_se_trovata(self):
        righe = fu.righe_link(self._esito(), tabella=TABELLA_ENTE)
        self.assertTrue(righe[0]["pubblicabile"])
        self.assertEqual(righe[0]["origine"], "ente")
        righe = fu.righe_link(
            fu.Esito(bando_id=7, stato=fu.STATO_IN_VERIFICA, url=URL_BUONO),
            tabella=TABELLA_ENTE,
        )
        self.assertFalse(righe[0]["pubblicabile"])

    def test_esito_http_e_quello_osservato_non_un_duecento_di_convenzione(self):
        riga = fu.righe_link(self._esito(esito_http=203), tabella=TABELLA_ENTE)[0]
        self.assertEqual(riga["esito_http"], 203)
        # Senza stato osservato la riga non puo' essere pubblicabile: il CHECK
        # `bando_link_pubblicabile_http_check` della 02 la rifiuterebbe.
        muta = fu.righe_link(self._esito(esito_http=None), tabella=TABELLA_ENTE)[0]
        self.assertIsNone(muta["esito_http"])
        self.assertFalse(muta["pubblicabile"])

    def test_origine_ricerca_non_si_perde_nel_dominio(self):
        # `ricerca` e' un valore del CHECK della 02 ed e' l'unico modo, a
        # posteriori, di sapere quali fonti sono costate crediti.
        riga = fu.righe_link(self._esito(metodo=fu.METODO_RICERCA), tabella=TABELLA_ENTE)[0]
        self.assertEqual(riga["origine"], "ricerca")
        riga = fu.righe_link(self._esito(metodo="contenuto"), tabella=TABELLA_ENTE)[0]
        self.assertEqual(riga["origine"], "contenuto")
        # E un link all'ente trovato sulla scheda OE resta `aggregatore`: e'
        # dove l'href e' stato visto, non dove punta (02, commento a bando_link).
        riga = fu.righe_link(self._esito(metodo="oe_scheda"), tabella=TABELLA_ENTE)[0]
        self.assertEqual(riga["origine"], "aggregatore")
        self.assertTrue(riga["pubblicabile"], "la pubblicabilita' la decide il dominio")

    def test_allegato_con_il_suo_stato_osservato(self):
        esito = self._esito(
            allegati=({"label": "Avviso", "url": URL_PDF, "tipo": "pdf"},),
            stati_allegati=((URL_PDF, 206),),
        )
        riga = [r for r in fu.righe_link(esito, tabella=TABELLA_ENTE)
                if r["tipo"] == "allegato"][0]
        self.assertEqual(riga["esito_http"], 206)
        self.assertTrue(riga["pubblicabile"])

    def test_dry_run_non_scrive_niente(self):
        esito = fu.scrivi_esito(self._esito(), attivo=True, dry_run=True)
        self.assertTrue(esito["dry_run"])
        self.assertEqual((esito["bando"], esito["link"], esito["controllo"]), (False, 0, False))

    def test_in_ombra_le_colonne_pubbliche_restano_ferme(self):
        strumento = self._controllo({
            "bando": list(db.COLONNE_FONTE_UFFICIALE),
            "bando_controllo": ["bando_id", "prossimo_controllo_at", "priorita_controllo"],
        })
        esito = fu.scrivi_esito(
            self._esito(), attivo=False, strumento=strumento, client=_ClientFinto(),
        )
        self.assertFalse(esito["bando"])
        self.assertEqual(esito["link"], 0)

    def test_tabelle_assenti_degradano(self):
        strumento = self._controllo({})          # schema vuoto: «non so»
        esito = fu.scrivi_esito(
            self._esito(), attivo=True, strumento=strumento, client=_ClientFinto(),
        )
        self.assertEqual(esito["link"], 0)
        self.assertFalse(esito["controllo"])

    def test_evento_non_trovata_e_sempre_interno(self):
        eventi = fu.eventi(self._esito(fu.STATO_NON_TROVATA), attivo=True)
        self.assertEqual(eventi[0]["tipo"], "fonte_ufficiale_non_trovata")
        self.assertFalse(eventi[0]["leggibile"])
        self.assertFalse(eventi[0]["applicato"])

    def test_evento_verificata_muto_in_ombra(self):
        muto = fu.eventi(self._esito(), attivo=False)[0]
        self.assertEqual(muto["tipo"], "fonte_ufficiale_verificata")
        self.assertFalse(muto["leggibile"])
        parlante = fu.eventi(self._esito(), attivo=True)[0]
        self.assertTrue(parlante["leggibile"])
        self.assertFalse(parlante["in_aggiornamenti"])

    def test_payload_controllo_ha_solo_colonne_calde(self):
        payload = fu.payload_controllo(self._esito())
        self.assertEqual(set(payload), {
            "ultimo_controllo_at", "prossimo_controllo_at", "priorita_controllo",
            "tentativi_resolver", "candidato_prioritario",
        })
        db.assicura_payload_bando({"priorita_controllo": 30})    # non e' vietata su `bando`


class _ClientFinto:
    """Client Supabase che registra le chiamate e non ne esegue nessuna."""

    def __init__(self):
        self.chiamate: list[str] = []

    def table(self, nome):
        self.chiamate.append(nome)
        return self

    def __getattr__(self, _nome):
        def _passa(*_a, **_k):
            return self
        return _passa

    def execute(self):
        return type("R", (), {"data": []})()


class _Query:
    """Registra i filtri invece di eseguirli: nessuna richiesta parte.

    `__getattr__` copre tutti i metodi di PostgREST che non ci interessano uno
    per uno (`eq`, `neq`, `in_`, `order`, `limit`, …): quello che conta e' che
    la sequenza dei filtri resti leggibile in `filtri`.
    """

    def __init__(self, dati=()):
        self.dati = list(dati)
        self.colonne = ""
        self.filtri: list[tuple] = []

    def __getattr__(self, nome):
        def _chiama(*argomenti):
            self.filtri.append((nome, *argomenti))
            return self
        return _chiama

    def table(self, nome):
        self.filtri.append(("table", nome))
        return self

    def select(self, colonne):
        self.colonne = colonne
        self.filtri.append(("select", colonne))
        return self

    def execute(self):
        return type("R", (), {"data": self.dati})()


class TestSelezione(unittest.TestCase):
    """La selezione dei candidati: colonne esplicite e filtri dietro `ha()`."""

    def _strumento(self, colonne):
        schema = {"definitions": {
            nome: {"properties": {c: {} for c in cols}} for nome, cols in colonne.items()
        }}
        return db.Controllo(fornitore_schema=lambda: schema)

    def _esegui(self, **kwargs):
        query = _Query([{"id": 1}])
        strumento = kwargs.pop("strumento", self._strumento({
            "bando": ["id", "titolo", "link_bando", "stato_processing",
                      "fonte_ufficiale_stato", "pubblicato", "fonte_id"],
        }))
        db.select_bandi_da_risolvere(client=query, strumento=strumento, **kwargs)
        return query

    def test_colonne_esplicite_mai_asterisco(self):
        query = self._esegui()
        self.assertNotIn("*", query.colonne)
        self.assertIn("id", query.colonne.split(","))

    def test_solo_le_colonne_che_lo_schema_espone(self):
        query = self._esegui()
        # `contenuto` e `allegati` non sono nello schema finto: non vanno chieste.
        self.assertNotIn("contenuto", query.colonne.split(","))

    def test_nuovi_filtra_enriched_e_senza_fonte(self):
        filtri = self._esegui().filtri
        self.assertIn(("eq", "stato_processing", "enriched"), filtri)
        self.assertIn(("neq", "fonte_ufficiale_stato", "trovata"), filtri)

    def test_forza_toglie_il_filtro_senza_fonte(self):
        filtri = self._esegui(forza=True).filtri
        self.assertIn(("eq", "stato_processing", "enriched"), filtri)
        self.assertNotIn(("neq", "fonte_ufficiale_stato", "trovata"), filtri)

    def test_backlog_guarda_i_pubblicati(self):
        filtri = self._esegui(modo="backlog").filtri
        self.assertIn(("eq", "pubblicato", True), filtri)

    def test_ricontrolli_solo_in_verifica_e_non_trovata(self):
        filtri = self._esegui(modo="ricontrolli").filtri
        self.assertIn(("in_", "fonte_ufficiale_stato", ["in_verifica", "non_trovata"]), filtri)

    def test_senza_le_colonne_nuove_nessun_filtro_le_cita(self):
        # Prima della migrazione 01 un filtro su `fonte_ufficiale_stato`
        # risponderebbe 42703 e fermerebbe lo step su tutte le righe.
        strumento = self._strumento({"bando": ["id", "stato_processing", "titolo"]})
        filtri = self._esegui(strumento=strumento).filtri
        self.assertFalse([f for f in filtri if "fonte_ufficiale_stato" in f])

    def test_tiebreak_su_id_sempre(self):
        # `data_pubblicazione` e' NULL sul 92% delle righe: senza `order('id')`
        # due pagine si sovrappongono.
        self.assertIn(("order", "id"), self._esegui().filtri)

    def test_tabella_assente_restituisce_nessun_candidato(self):
        strumento = db.Controllo(fornitore_schema=lambda: {})
        self.assertEqual(
            db.select_bandi_da_risolvere(client=_Query(), strumento=strumento), [],
        )

    def test_limit_zero_non_significa_nessun_limite(self):
        # `--limit 0` e' cio' che un operatore mette per non toccare niente:
        # trattarlo come «nessun limite» farebbe girare `risolvi-fonte
        # --limit 0 --attivo` sull'intero corpus.
        self.assertIn(("limit", 0), self._esegui(limit=0).filtri)
        self.assertNotIn(
            "limit", [f[0] for f in self._esegui(limit=None).filtri],
        )

    def test_id_singolo_ignora_gli_altri_filtri(self):
        filtri = self._esegui(bando_id=42).filtri
        self.assertIn(("eq", "id", 42), filtri)
        self.assertNotIn(("eq", "stato_processing", "enriched"), filtri)


class TestColonneDellaSeo(unittest.TestCase):
    """L'alimentazione della SEO con il testo ufficiale (§5, D.6) vive o muore
    nella `select` di `select_bandi_to_complete`: se le colonne non sono
    chieste, `scegli_fonte` ricade sempre su `link_bando` — per i 1 702 OE,
    l'aggregatore — e l'intestazione «PAGINA UFFICIALE» non nasce mai."""

    def _colonne(self, esposte):
        query = _Query([])
        strumento = db.Controllo(
            fornitore_schema=lambda: {
                "definitions": {"bando": {"properties": {c: {} for c in esposte}}},
            }
        )
        with unittest.mock.patch.object(db, "get_supabase", lambda: query):
            db.select_bandi_to_complete(strumento=strumento)
        return query.colonne.split(",")

    def test_con_lo_schema_completo_le_tre_colonne_ci_sono(self):
        colonne = self._colonne(
            list(db.COLONNE_SEO_BASE) + list(db.COLONNE_SEO_RESOLVER)
        )
        for attesa in ("allegati", "fonte_ufficiale_url", "fonte_ufficiale_stato"):
            self.assertIn(attesa, colonne)

    def test_senza_la_migrazione_01_le_due_nuove_non_si_chiedono(self):
        # Chiederle su un DB non migrato sarebbe un 42703 che ferma lo step SEO
        # su tutte le righe. `allegati` invece esiste gia' oggi.
        colonne = self._colonne(list(db.COLONNE_SEO_BASE))
        self.assertIn("allegati", colonne)
        self.assertNotIn("fonte_ufficiale_url", colonne)
        self.assertNotIn("fonte_ufficiale_stato", colonne)

    def test_schema_illeggibile_non_chiede_le_colonne_nuove(self):
        colonne = self._colonne([])
        self.assertIn("allegati", colonne)
        self.assertNotIn("fonte_ufficiale_url", colonne)

    def test_mai_un_asterisco(self):
        self.assertNotIn("*", self._colonne(list(db.COLONNE_SEO_BASE)))


class TestSchedeGiaLette(unittest.TestCase):
    def test_la_prova_distingue_la_scheda_letta_dal_bando_nuovo(self):
        # `raw_data` c'e' sempre (viene dal listing): senza questa distinzione
        # nessuna scheda verrebbe mai scaricata la prima volta.
        righe = [
            {"bando_id": 1, "impronta_pagina": "abc#12"},
            {"bando_id": 2, "impronta_pagina": None},
            {"bando_id": 3},
        ]
        self.assertEqual(fu.schede_gia_lette([1, 2, 3], righe=righe), frozenset({1}))

    def test_bando_mai_letto_e_una_scoperta(self):
        gia = fu.schede_gia_lette([1], righe=[])
        prima = {"status": "1"} if 1 in gia else None
        self.assertEqual(
            oe.deve_riscaricare(prima=prima, dopo={"status": "1"}),
            (True, oe.MOTIVO_SCOPERTA),
        )


class TestRunnerAusiliari(unittest.TestCase):
    def test_oe_dettaglio_senza_forza_non_riscarica_le_gia_lette(self):
        chiamate = []

        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                chiamate.append(url)
                return None

        bandi = [{"id": 1, "link_bando": "https://www.obiettivoeuropa.com/bandi/x",
                  "raw_data": {"status": "1"}}]
        with unittest.mock.patch.object(
            fu, "schede_gia_lette", return_value=frozenset({1}),
        ):
            esito = esegui(fu.run_oe_dettaglio(dry_run=True, bandi=bandi, scarico=_Scarico()))
        self.assertEqual(chiamate, [])
        self.assertEqual(esito["saltate"], 1)

    def test_oe_dettaglio_backlog_arriva_alla_selezione(self):
        """Il modo scelto sulla riga di comando deve arrivare alla query.

        Il comando cablava `modo="nuovi"`: con 1 702 schede gia' pubblicate da
        leggere ne selezionava una manciata (la coda degli `enriched`), e
        `--forza` non cambiava nulla perche' scavalca la regola di ri-scarico,
        non la selezione. Misurato in produzione il 23/09/2026:
        `oe-dettaglio --dry-run --limit 5` esaminava 1 riga.
        """
        visti = {}

        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                return None

        def _finta(**kwargs):
            visti.update(kwargs)
            return []

        with unittest.mock.patch.object(fu.db, "select_bandi_da_risolvere", _finta):
            esegui(fu.run_oe_dettaglio(
                dry_run=True, limit=7, modo="backlog", forza=True, scarico=_Scarico(),
            ))
        self.assertEqual(visti.get("modo"), "backlog")
        self.assertTrue(visti.get("forza"))
        self.assertEqual(visti.get("limit"), 7)
        self.assertTrue(visti.get("solo_oe"))

    def test_oe_dettaglio_modo_predefinito_nuovi(self):
        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                return None

        visti = {}

        def _finta(**kwargs):
            visti.update(kwargs)
            return []

        with unittest.mock.patch.object(fu.db, "select_bandi_da_risolvere", _finta):
            esegui(fu.run_oe_dettaglio(dry_run=True, scarico=_Scarico()))
        self.assertEqual(visti.get("modo"), "nuovi")

    def test_oe_dettaglio_con_forza_riscarica(self):
        chiamate = []

        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                chiamate.append(url)
                return None

        bandi = [{"id": 1, "link_bando": "https://www.obiettivoeuropa.com/bandi/x",
                  "raw_data": {"status": "1"}}]
        with unittest.mock.patch.object(
            fu, "schede_gia_lette", return_value=frozenset({1}),
        ):
            esegui(fu.run_oe_dettaglio(bandi=bandi, scarico=_Scarico(), forza=True))
        self.assertEqual(chiamate, ["https://www.obiettivoeuropa.com/bandi/x"])

    def test_oe_dettaglio_in_prova_a_vuoto_non_scarica_niente(self):
        # Una scheda costa una richiesta autenticata, un secondo di throttle e
        # una unita' del tetto `OE_SCHEDE_GIORNO`: `--dry-run` su tutto il
        # corpus ne consumerebbe 1 702 senza scrivere una riga.
        chiamate = []

        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                chiamate.append(url)
                return None

        bandi = [{"id": 1, "link_bando": "https://www.obiettivoeuropa.com/bandi/x",
                  "raw_data": {"status": "1"}}]
        with unittest.mock.patch.object(
            fu, "schede_gia_lette", return_value=frozenset(),
        ):
            esito = esegui(fu.run_oe_dettaglio(dry_run=True, bandi=bandi, scarico=_Scarico()))
        self.assertEqual(chiamate, [])
        self.assertEqual(esito["da_scaricare"], 1)
        self.assertEqual(esito["scaricate"], 0)

    def test_oe_dettaglio_senza_scarico_non_somiglia_a_un_giro_riuscito(self):
        # Senza credenziali il comando non ha fatto niente: dirlo con
        # `saltato` e' l'unico modo perche' un cron notturno non risulti verde.
        with unittest.mock.patch.object(
            fu.oe_scheda, "scarico_predefinito", return_value=None,
        ), unittest.mock.patch.object(fu, "_tabella_corrente", return_value=TABELLA_ENTE):
            esito = esegui(fu.run_oe_dettaglio(dry_run=True, bandi=[]))
        self.assertEqual(esito["saltato"], "scarico_non_configurato")

    def test_link_verifica_pubblicabile_solo_con_2xx(self):
        righe = [
            {"id": 1, "url": "https://regione.marche.it/a"},
            {"id": 2, "url": "https://regione.marche.it/b"},
            {"id": 3, "url": "https://www.obiettivoeuropa.com/x"},
        ]
        esiti = {
            "https://regione.marche.it/a": (200, "text/html", "", None, None),
            "https://regione.marche.it/b": (404, None, "", None, None),
            "https://www.obiettivoeuropa.com/x": (200, "text/html", "", None, None),
        }
        esito = esegui(fu.run_link_verifica(
            dry_run=True, righe=righe, verifica=lambda url: esiti[url],
        ))
        # L'aggregatore risponde 200 ma non e' pubblicabile: il dominio decide.
        self.assertEqual(esito["pubblicabili"], 1)
        self.assertEqual(esito["ritirati"], 2)

    def test_fondi_doppioni_in_ombra_non_fonde(self):
        righe = [
            {"id": 1, "link_bando": "https://regione.marche.it/b1", "titolo": "Bando",
             "fonte_id": 1},
            {"id": 2, "link_bando": "https://regione.marche.it/b1", "titolo": "Bando",
             "fonte_id": 2},
        ]
        esito = esegui(fu.run_fondi_doppioni(dry_run=True, righe=righe))
        self.assertGreater(esito["esatti"], 0)
        self.assertEqual(esito["fusi"], 0)

    def test_domini_import_in_ombra_conta_e_non_scrive(self):
        fonti = [{"id": 10, "link": "https://regione.marche.it/bandi", "discoverable": True}]
        esito = esegui(fu.run_domini_import(fonti=fonti, indicepa=[]))
        self.assertEqual(esito["fonti"], 1)
        self.assertGreater(esito["domini"], 1)          # il seed c'e' sempre
        self.assertEqual(esito["scritte"], 0)


class TestRicercaVincolata(unittest.TestCase):
    """§5: «ente non mappato -> ricerca senza `include_domains` ma esito
    massimo `in_verifica`». Stesso candidato, stesso punteggio: cambia solo
    che qualcuno abbia potuto vincolare la ricerca."""

    def _punteggio(self, vincolata):
        c = fu.Candidato(
            url=URL_BUONO, metodo=fu.METODO_RICERCA, origine="ricerca",
            pagina=pagina(URL_BUONO, corpo=CORPO_COMPLETO), vincolata=vincolata,
        )
        return fu.punteggia(c, contesto())

    def test_vincolata_arriva_a_trovata(self):
        p = self._punteggio(True)
        self.assertGreaterEqual(p.valore, fu.SOGLIA_TROVATA)
        self.assertEqual(p.stato, fu.STATO_TROVATA)

    def test_libera_si_ferma_a_in_verifica(self):
        p = self._punteggio(False)
        self.assertEqual(p.valore, self._punteggio(True).valore, "stesso punteggio")
        self.assertIn("ricerca_vincolata", p.falliti())
        self.assertEqual(p.stato, fu.STATO_IN_VERIFICA)

    def test_la_cascata_marca_i_risultati_non_vincolati(self):
        domini_usati = []

        async def ricerca(_testo, domini):
            domini_usati.append(tuple(domini))
            return [URL_BUONO]

        # Ente non mappato: nessuna riga della whitelist condivide un token con
        # «Unione Montana Zolfara» e il `link_bando` non c'e'. La ricerca parte
        # senza `include_domains` e il candidato nasce `vincolata=False`.
        amb = ambiente(
            tabella=tabella(), ricerca=ricerca,
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
        )
        bando = {"id": 1, "titolo": TITOLO, "ente_erogatore": "Unione Montana Zolfara",
                 "data_scadenza": "2026-09-30", "importo_totale_eur": IMPORTO,
                 "raw_data": {}}
        esito = esegui(fu.risolvi(bando, amb))
        self.assertEqual(domini_usati, [()], "nessun dominio a cui vincolare")
        self.assertGreaterEqual(esito.confidenza, fu.SOGLIA_TROVATA)
        self.assertEqual(esito.stato, fu.STATO_IN_VERIFICA)
        self.assertEqual(amb.contatori.ricerche_libere, 1)


class TestSpesaDelloScarico(unittest.TestCase):
    """I tetti devono vedere la spesa vera: lo scarico ha contatori propri, e
    senza fonderli `fetch` resta a zero e i crediti del ripiego Firecrawl non
    entrano nel tetto giornaliero."""

    class _ContatoriScarico:
        def __init__(self, fetch=0, crediti=0):
            self.fetch = fetch
            self.fetch_304 = 0
            self.crediti_firecrawl = crediti

    def _bando(self):
        return {"id": 1, "titolo": TITOLO, "ente_erogatore": ENTE,
                "data_scadenza": "2026-09-30", "importo_totale_eur": IMPORTO,
                "raw_data": {"external_link": URL_BUONO}}

    def test_i_crediti_del_ripiego_fermano_il_giro(self):
        spesi = self._ContatoriScarico(fetch=4, crediti=9)
        amb = ambiente(
            spesa_scarico=lambda: spesi,
            tetti=bilancio.Tetti(crediti_giorno=5),
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
        )
        esegui(fu.risolvi(self._bando(), amb))
        self.assertTrue(amb.contatori.interrotto_per_tetto)
        self.assertIn("crediti", amb.contatori.motivo)
        self.assertEqual(amb.spesa.crediti_firecrawl, 9)
        self.assertEqual(amb.spesa.fetch, 4)

    def test_si_somma_il_delta_non_il_totale_ogni_volta(self):
        # I contatori dello scarico sono cumulativi sul giro: risommarli a
        # ogni verifica moltiplicherebbe la spesa e il tetto scatterebbe da
        # solo dopo tre bandi.
        spesi = self._ContatoriScarico(fetch=2, crediti=1)
        amb = ambiente(spesa_scarico=lambda: spesi)
        amb.assorbi_spesa()
        amb.assorbi_spesa()
        self.assertEqual((amb.spesa.fetch, amb.spesa.crediti_firecrawl), (2, 1))
        spesi.fetch, spesi.crediti_firecrawl = 5, 3
        amb.assorbi_spesa()
        self.assertEqual((amb.spesa.fetch, amb.spesa.crediti_firecrawl), (5, 3))

    def test_il_tetto_per_giro_sul_fetch_morde(self):
        spesi = self._ContatoriScarico(fetch=30)
        amb = ambiente(
            spesa_scarico=lambda: spesi, tetti=bilancio.Tetti(fetch_giro=10),
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
        )
        esito = esegui(fu.risolvi(self._bando(), amb))
        self.assertTrue(amb.contatori.interrotto_per_tetto)
        self.assertEqual(esito.stato, fu.STATO_NON_TROVATA, "cascata monca, non un verdetto")


class _LockFinto:
    proseguire = True
    stato = "acquisito"


class TestGiroCompleto(unittest.TestCase):
    """`run()`: un bando per volta, e un tetto non produce verdetti falsi."""

    def _run(self, bandi, scrivi=None, **kwargs):
        chiamate: list[Any] = []

        def _scrivi(esito, **_k):
            chiamate.append(esito)
            if scrivi is not None:
                scrivi(esito)
            return {"status": "ok"}

        amb = kwargs.pop("ambiente", ambiente())
        with unittest.mock.patch.object(fu.blocco, "acquisisci", return_value=_LockFinto()), \
                unittest.mock.patch.object(fu.blocco, "rilascia", lambda _l: None), \
                unittest.mock.patch.object(
                    fu.db, "select_bandi_da_risolvere", return_value=list(bandi)), \
                unittest.mock.patch.object(fu.db, "select_controlli", return_value={}), \
                unittest.mock.patch.object(
                    fu.db, "select_pubblicati_per_gemelli", return_value=[]), \
                unittest.mock.patch.object(fu, "schede_gia_lette", return_value=frozenset()), \
                unittest.mock.patch.object(fu, "_registra", lambda *_a, **_k: None), \
                unittest.mock.patch.object(fu, "scrivi_esito", _scrivi):
            esito = esegui(fu.run(dry_run=True, ambiente=amb, **kwargs))
        return esito, chiamate

    def _bandi(self, quanti=3):
        return [
            {"id": i, "titolo": TITOLO, "ente_erogatore": ENTE,
             "data_scadenza": "2026-09-30", "raw_data": {}}
            for i in range(1, quanti + 1)
        ]

    def test_un_errore_su_una_riga_non_butta_via_il_lotto(self):
        # Su un backfill L2 da 1 702 righe una pagina malformata alla riga 500
        # non puo' portarsi dietro le altre 1 200.
        def _rompi(esito):
            if esito.bando_id == 2:
                raise db.PayloadBandoVietato("payload con chiavi vietate")

        amb = ambiente()
        risultato, chiamate = self._run(self._bandi(), scrivi=_rompi, ambiente=amb)
        self.assertEqual(amb.contatori.esaminati, 3)
        self.assertEqual([e.bando_id for e in chiamate], [1, 2, 3])
        self.assertEqual(risultato["errori"], 1)
        self.assertEqual(risultato["status"], "ok")

    def test_al_tetto_il_bando_a_meta_resta_intatto(self):
        # Scrivere un `non_trovata` ricavato da mezza cascata condannerebbe il
        # bando a sessanta giorni di attesa per colpa di un tetto.
        spesi = TestSpesaDelloScarico._ContatoriScarico(fetch=99)
        amb = ambiente(spesa_scarico=lambda: spesi, tetti=bilancio.Tetti(fetch_giro=1))
        risultato, chiamate = self._run(self._bandi(), ambiente=amb)
        self.assertEqual(chiamate, [])
        self.assertTrue(risultato["interrotto_per_tetto"])

    def test_il_giro_riporta_i_crediti_spesi(self):
        spesi = TestSpesaDelloScarico._ContatoriScarico(fetch=3, crediti=7)
        amb = ambiente(spesa_scarico=lambda: spesi)
        risultato, _ = self._run(self._bandi(1), ambiente=amb)
        self.assertEqual(risultato["crediti"], 7)
        self.assertEqual(risultato["fetch"], 3)


class TestAmbientePredefinito(unittest.TestCase):
    """La sorgente principale della resa dev'essere raggiungibile da un
    ingresso di produzione: `scheda_oe` non puo' restare `None`."""

    def _ambiente(self, schede):
        with unittest.mock.patch.object(fu, "_tabella_corrente", return_value=TABELLA_ENTE), \
                unittest.mock.patch.object(
                    fu.oe_scheda, "scarico_predefinito", return_value=schede):
            return fu._ambiente_predefinito(step="resolver", attivo=False)

    def test_la_scheda_oe_e_collegata(self):
        letti: list[str] = []

        class _Schede:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                letti.append(url)
                return None

        amb = self._ambiente(_Schede())
        self.assertIsNotNone(amb.scheda_oe)
        self.assertIsNotNone(amb.verifica_allegato)
        self.assertIsNotNone(amb.spesa_scarico)
        url = "https://www.obiettivoeuropa.com/bandi/x"
        esegui(amb.scheda_oe({"id": 1, "link_bando": url, "raw_data": {"status": "1"}}))
        self.assertEqual(letti, [url])

    def test_la_regola_a29_vale_anche_dentro_la_cascata(self):
        # Una scheda gia' letta non si riscarica a ogni giro del resolver:
        # sarebbero 1 702 richieste al portale quattro volte al giorno.
        letti: list[str] = []

        class _Schede:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                letti.append(url)
                return None

        amb = self._ambiente(_Schede())
        amb.schede_lette = frozenset({1})
        url = "https://www.obiettivoeuropa.com/bandi/x"
        esegui(amb.scheda_oe({"id": 1, "link_bando": url, "raw_data": {"status": "1"}}))
        self.assertEqual(letti, [])

    def test_un_host_non_oe_non_passa_dallo_scarico_autenticato(self):
        amb = self._ambiente(None)
        self.assertIsNone(
            esegui(amb.scheda_oe({"id": 1, "link_bando": URL_BUONO, "raw_data": {}}))
        )


class TestQueryEDomini(unittest.TestCase):
    def test_query_senza_stopword(self):
        query = fu.query_ricerca(contesto())
        self.assertIn("contributi", query)
        self.assertNotIn(" per ", f" {query} ")
        self.assertIn("2026", query)

    def test_seconda_query_con_filetype(self):
        self.assertTrue(fu.query_ricerca(contesto(), filetype_pdf=True).endswith("filetype:pdf"))

    def test_domini_vincolati_al_massimo_venti(self):
        righe = [
            dominio_ufficiale.Dominio(host=f"ente{i}.marche.it", tipo="ente",
                                      confidenza=1.0, ente="Regione Marche")
            for i in range(30)
        ]
        domini = fu.domini_ammessi(contesto(tab=tabella(*righe)), {})
        self.assertLessEqual(len(domini), 20)

    def test_gli_aggregatori_non_entrano_fra_i_domini(self):
        domini = fu.domini_ammessi(
            contesto(), {"link_bando": "https://www.obiettivoeuropa.com/bandi/x"},
        )
        self.assertNotIn("obiettivoeuropa.com", domini)


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()
