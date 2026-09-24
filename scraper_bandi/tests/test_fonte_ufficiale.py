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

    def test_trovata_passa_al_monitor_subito(self):
        """Una fonte trovata resta DOVUTA, cosi' il monitor la prende al primo giro.

        `prossimo_controllo_at` e' una sola colonna per due mestieri: il
        resolver ci scrive quando tornare a cercare la fonte, il monitor ci
        legge la sua coda. Mettere sessanta giorni su un bando appena risolto
        chiudeva fuori il monitor proprio dai bandi che in quel momento
        diventavano controllabili.

        Misurato il 24/09/2026: 213 fonti risolte e `monitor --ombra` con
        `candidati: 0`, perche' tutti e 213 avevano il prossimo controllo a
        piu' di due settimane. La catena resolver -> monitor -> eventi -> box
        «Aggiornamenti» era interrotta al primo anello, e il monitor riferiva
        un giro riuscito.
        """
        data, priorita, _ = fu.prossimo_controllo(fu.STATO_TROVATA, 0, self.OGGI)
        self.assertEqual(data, self.OGGI, "la riga deve restare dovuta")
        self.assertTrue(fu.scaduto({"prossimo_controllo_at": data.isoformat()}, self.OGGI))
        self.assertEqual(priorita, fu.PRIORITA_TROVATA)

    def test_gli_altri_due_stati_tengono_la_loro_cadenza(self):
        # La correzione riguarda solo `trovata`: gli altri due sono ricontrolli
        # del resolver e la cadenza A33 resta quella.
        breve, _, _ = fu.prossimo_controllo(fu.STATO_IN_VERIFICA, 0, self.OGGI)
        self.assertEqual((breve - self.OGGI).days, fu.GIORNI_RICONTROLLO_BREVE)
        lungo, _, _ = fu.prossimo_controllo(fu.STATO_NON_TROVATA, 0, self.OGGI)
        self.assertEqual((lungo - self.OGGI).days, fu.GIORNI_RICONTROLLO_LUNGO)

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

    #: Il filtro «senza fonte» come deve arrivare al server: due rami in OR,
    #: perche' `neq` su NULL non e' vero e una riga con la colonna vuota
    #: sparirebbe dalla selezione (misurato in produzione il 23/09/2026: 9
    #: pubblicati invisibili al resolver, +11 al giorno).
    SENZA_FONTE = ("or_", "fonte_ufficiale_stato.is.null,fonte_ufficiale_stato.neq.trovata")

    def test_nuovi_filtra_enriched_e_senza_fonte(self):
        filtri = self._esegui().filtri
        self.assertIn(("eq", "stato_processing", "enriched"), filtri)
        self.assertIn(self.SENZA_FONTE, filtri)

    def test_il_filtro_senza_fonte_accetta_anche_il_null(self):
        """La riga con `fonte_ufficiale_stato` vuoto deve restare selezionabile.

        E' il difetto chiuso dalla migrazione 09: il DEFAULT ha riempito le
        righe, ma la selezione non deve dipendere da una migrazione. Un
        `INSERT` con NULL esplicito, o il rollback della 09, riaprirebbero il
        buco — e nessun contatore lo direbbe, perche' le righe non selezionate
        non compaiono da nessuna parte.
        """
        filtri = self._esegui().filtri
        self.assertNotIn(("neq", "fonte_ufficiale_stato", "trovata"), filtri)
        rami = [f[1] for f in filtri if f[0] == "or_"]
        self.assertTrue(rami, "nessun filtro OR: il NULL resterebbe fuori")
        self.assertIn("fonte_ufficiale_stato.is.null", rami[0])
        self.assertIn("fonte_ufficiale_stato.neq.trovata", rami[0])

    def test_backlog_accetta_anche_il_null(self):
        filtri = self._esegui(modo="backlog").filtri
        self.assertIn(self.SENZA_FONTE, filtri)

    def test_forza_toglie_il_filtro_senza_fonte(self):
        filtri = self._esegui(forza=True).filtri
        self.assertIn(("eq", "stato_processing", "enriched"), filtri)
        self.assertNotIn(self.SENZA_FONTE, filtri)
        self.assertNotIn(("neq", "fonte_ufficiale_stato", "trovata"), filtri)

    def test_backlog_guarda_i_pubblicati(self):
        filtri = self._esegui(modo="backlog").filtri
        self.assertIn(("eq", "pubblicato", True), filtri)

    def test_ricontrolli_solo_in_verifica_e_non_trovata(self):
        filtri = self._esegui(modo="ricontrolli").filtri
        self.assertIn(("in_", "fonte_ufficiale_stato", ["in_verifica", "non_trovata"]), filtri)

    def test_i_ricontrolli_non_toccano_gli_scarti_della_pipeline(self):
        """Il ricontrollo vale per chi la fonte ufficiale la usera' davvero.

        Senza questo filtro la selezione prendeva 4 076 righe invece di 1 283
        (misurato il 24/09/2026): 2 337 `rejected`, che sono gli scarti della
        pipeline, e 455 chiusi mai pubblicati, che sono materia del lotto L8.
        Due terzi del lavoro finivano su pagine che non esisteranno, e su una
        riga senza candidato la cascata arriva fino alla ricerca a pagamento:
        il costo non era solo tempo.
        """
        filtri = self._esegui(modo="ricontrolli").filtri
        rami = [f[1] for f in filtri if f[0] == "or_"]
        self.assertTrue(rami, "nessun filtro sulle righe che useranno la fonte")
        self.assertIn("pubblicato.eq.true", rami[0])
        self.assertIn("stato_processing.eq.enriched", rami[0])

    def test_senza_la_colonna_pubblicato_si_ripiega_su_stato_processing(self):
        # Prima della migrazione 01 `pubblicato` non c'e': il filtro deve
        # esistere comunque, altrimenti il difetto torna sui DB non migrati.
        strumento = self._strumento({"bando": [
            "id", "titolo", "stato_processing", "fonte_ufficiale_stato"]})
        filtri = self._esegui(modo="ricontrolli", strumento=strumento).filtri
        self.assertIn(("in_", "stato_processing", ["completed", "enriched"]), filtri)
        self.assertFalse([f for f in filtri if f[0] == "or_"])

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

    def test_limit_zero_con_offset_non_diventa_un_range_alla_rovescia(self):
        # `range(800, 799)` e' un intervallo vuoto scritto al contrario: un
        # limite di zero righe si dice con `limit(0)`.
        filtri = self._esegui(limit=0, offset=800).filtri
        self.assertIn(("limit", 0), filtri)
        self.assertFalse([f for f in filtri if f[0] == "range"])

    def test_offset_usa_range_perche_postgrest_non_ha_offset(self):
        filtri = self._esegui(limit=500, offset=1000).filtri
        self.assertIn(("range", 1000, 1499), filtri)

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
        self.assertTrue(visti.get("solo_oe"))
        # Alla query si chiede una PAGINA, non il limite dell'operatore: il
        # limite conta le righe da leggere davvero, non quelle guardate.
        self.assertEqual(visti.get("limit"), fu.PAGINA_SELEZIONE_OE)
        self.assertEqual(visti.get("offset"), 0)

    def test_oe_dettaglio_scorre_oltre_le_schede_gia_lette(self):
        """Due lanci di fila devono avanzare, non ripetere le stesse righe.

        Misurato in produzione il 23/09/2026: `oe-dettaglio --backlog --forza
        --limit 800` lanciato due volte ha dato gli stessi identici contatori
        (800 esaminati, 799 scaricate, 1866 link) e ha coperto 799 bandi in
        tutto. La selezione ordina per `id` e prende i primi N, e nulla
        escludeva le schede gia' lette: senza scorrere, il lotto non finisce
        mai.
        """
        pagine = {
            0: [{"id": i, "link_bando": f"https://www.obiettivoeuropa.com/bandi/{i}",
                 "raw_data": {"status": "1"}} for i in range(1, 6)],
            5: [{"id": i, "link_bando": f"https://www.obiettivoeuropa.com/bandi/{i}",
                 "raw_data": {"status": "1"}} for i in range(6, 9)],
        }
        offset_visti = []

        def _finta(**kwargs):
            offset_visti.append(kwargs.get("offset"))
            return pagine.get(kwargs.get("offset"), [])

        class _Scarico:
            fermato = ""

            async def scheda(self, url, archiviato=False):
                return None

        # I primi cinque sono gia' stati letti: devono essere saltati e NON
        # devono consumare il limite di due. La pagina della selezione va
        # ridotta a 5 perche' il finto la riempia: una pagina piu' corta di
        # quella richiesta significa «selezione finita», ed e' giusto cosi'.
        with unittest.mock.patch.object(fu, "PAGINA_SELEZIONE_OE", 5), \
                unittest.mock.patch.object(fu.db, "select_bandi_da_risolvere", _finta), \
                unittest.mock.patch.object(
                    fu, "schede_gia_lette",
                    side_effect=lambda ids: frozenset(i for i in ids if i <= 5)):
            esito = esegui(fu.run_oe_dettaglio(dry_run=True, limit=2, modo="backlog",
                                               scarico=_Scarico()))
        self.assertEqual(esito["saltate"], 5)
        self.assertEqual(esito["da_scaricare"], 2)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual(offset_visti[:2], [0, 5])

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
        # `impronta_pagina` e' la prova che l'href e' stato trovato nell'HTML
        # di una pagina: senza, il CHECK della 02 rifiuta una riga pubblicabile
        # e la riga resta non pubblicabile per costruzione (vedi
        # `test_senza_prova_non_si_pubblica`).
        righe = [
            {"id": 1, "url": "https://regione.marche.it/a", "impronta_pagina": "a#1"},
            {"id": 2, "url": "https://regione.marche.it/b", "impronta_pagina": "b#1"},
            {"id": 3, "url": "https://www.obiettivoeuropa.com/x", "impronta_pagina": "c#1"},
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
        self.assertEqual(esito["senza_prova"], 0)

    def test_senza_prova_non_si_pubblica_e_lo_dice(self):
        """Una riga che risponde 200 ma non ha prova di provenienza.

        Sono le 3 739 righe `raw` del backfill della 02: vengono da
        `bando.link_bando` e dagli allegati, non dall'HTML di una pagina che
        qualcuno ha scaricato. Il CHECK della 02 rifiuta una riga pubblicabile
        senza `trovato_in_fonte_at`, e §13.4 promette che ogni riga leggibile
        compare nell'HTML della pagina di riferimento. Prima il comando le
        dichiarava pubblicabili e l'UPDATE veniva rifiutato in silenzio.
        """
        righe = [{"id": 1, "url": "https://regione.marche.it/a"}]
        esito = esegui(fu.run_link_verifica(
            dry_run=True, righe=righe,
            verifica=lambda _url: (200, "text/html", "", None, None),
        ))
        self.assertEqual(esito["pubblicabili"], 0)
        self.assertEqual(esito["senza_prova"], 1)
        self.assertEqual(esito["ritirati"], 1)

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

    def test_fondi_doppioni_limit_zero_non_fonde_niente(self):
        # `limit or 5000` trasformava «non toccare niente» in «leggi tutto il
        # corpus e applica le fusioni»: l'esatto contrario della convenzione
        # del package («zero = nessuna riga»).
        righe = [
            {"id": 1, "link_bando": "https://regione.marche.it/b1", "titolo": "Bando",
             "fonte_id": 1},
            {"id": 2, "link_bando": "https://regione.marche.it/b1", "titolo": "Bando",
             "fonte_id": 2},
        ]
        fusioni: list[Any] = []
        with unittest.mock.patch.object(
                fu.db, "fondi_bandi",
                lambda master, doppione, motivo: fusioni.append((master, doppione)) or master):
            esito = esegui(fu.run_fondi_doppioni(attivo=True, limit=0, righe=righe))
        self.assertEqual(fusioni, [])
        self.assertEqual(esito["fusi"], 0)
        # Il report, che e' gratis, copre comunque tutto il corpus.
        self.assertEqual(esito["esaminati"], 2)
        self.assertGreater(esito["esatti"], 0)
        self.assertGreater(esito["rimandati"], 0)

    def test_fondi_doppioni_legge_il_corpus_non_la_finestra_del_limit(self):
        # Impaginare qui sarebbe SBAGLIATO: una coppia con un id in pagina 1 e
        # l'altro in pagina 3 non verrebbe trovata da nessuna delle due. Alla
        # lettura si chiede sempre il corpus, e il `--limit` e' il budget
        # delle fusioni applicate.
        visti: list[dict[str, Any]] = []

        def _selezione(**parametri):
            visti.append(dict(parametri))
            return []

        with unittest.mock.patch.object(fu.db, "select_pubblicati_per_gemelli", _selezione):
            esegui(fu.run_fondi_doppioni(dry_run=True, limit=3))
        self.assertEqual(visti[0].get("limit"), fu.TETTO_GEMELLI)

    def test_domini_import_limit_zero_non_importa_tutto(self):
        # `if limit:` faceva scrivere l'intera whitelist con `--limit 0`.
        fonti = [{"id": 10, "link": "https://regione.marche.it/bandi", "discoverable": True}]
        scritte: list[Any] = []
        with unittest.mock.patch.object(
                fu.db, "upsert_domini", lambda righe: scritte.extend(righe) or len(righe)):
            esito = esegui(fu.run_domini_import(
                attivo=True, limit=0, fonti=fonti, indicepa=[]))
        self.assertEqual(scritte, [])
        self.assertEqual(esito["domini"], 0)
        self.assertEqual(esito["scritte"], 0)
        # Il troncamento si dichiara: una whitelist parziale che risponde «ok»
        # e' il modo piu' rapido di far passare un aggregatore per dominio non
        # classificato.
        self.assertGreater(esito["troncati"], 0)
        self.assertEqual(esito["composti"], esito["troncati"])

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


class TestScorrimentoDellaSelezione(unittest.TestCase):
    """`risolvi-fonte`: due lanci di fila devono avanzare, non ripetersi.

    Stesso difetto misurato su `oe-dettaglio` il 23/09/2026 (800 esaminati,
    799 scaricate, 1866 link, due volte di fila): la selezione ordina per `id`
    e prende i primi N, e l'unico predicato capace di far uscire una riga —
    `fonte_ufficiale_stato = 'trovata'` — lo scrive `db.aggiorna_fonte_ufficiale`,
    che vive dentro il ramo `if attivo:` di `scrivi_esito` e in **ombra**, che
    e' il modo predefinito, non viene eseguito mai.
    """

    OGGI = date(2026, 9, 23)

    def _giro(self, pagine, *, controlli=None, **kwargs):
        visti: list[dict[str, Any]] = []
        amb = kwargs.pop("ambiente", ambiente(oggi=self.OGGI))

        def _selezione(**parametri):
            visti.append(dict(parametri))
            return list(pagine.get(parametri.get("offset"), []))

        with unittest.mock.patch.object(fu.blocco, "acquisisci", return_value=_LockFinto()), \
                unittest.mock.patch.object(fu.blocco, "rilascia", lambda _l: None), \
                unittest.mock.patch.object(fu.db, "select_bandi_da_risolvere", _selezione), \
                unittest.mock.patch.object(
                    fu.db, "select_controlli",
                    lambda ids, **k: {i: (controlli or {})[i] for i in ids
                                      if i in (controlli or {})}), \
                unittest.mock.patch.object(
                    fu.db, "select_pubblicati_per_gemelli", return_value=[]), \
                unittest.mock.patch.object(fu, "schede_gia_lette", return_value=frozenset()), \
                unittest.mock.patch.object(fu, "_registra", lambda *_a, **_k: None), \
                unittest.mock.patch.object(fu, "scrivi_esito", lambda *_a, **_k: {"status": "ok"}), \
                unittest.mock.patch.object(fu, "PAGINA_SELEZIONE_RESOLVER", 5):
            esito = esegui(fu.run(dry_run=True, ambiente=amb, **kwargs))
        return esito, visti

    def _pagine(self):
        def _riga(i):
            return {"id": i, "titolo": TITOLO, "ente_erogatore": ENTE,
                    "data_scadenza": "2026-09-30", "raw_data": {}}
        return {0: [_riga(i) for i in range(1, 6)],
                5: [_riga(i) for i in range(6, 9)]}

    def test_le_righe_gia_lavorate_non_consumano_il_limite(self):
        # I primi cinque sono stati lavorati ieri e il loro ricontrollo e' fra
        # due settimane: vanno saltati, e il `--limit 2` deve arrivare alla
        # pagina dopo invece di esaurirsi su di loro.
        controlli = {
            i: {"ultimo_controllo_at": "2026-09-22T10:00:00+00:00",
                "prossimo_controllo_at": "2026-10-06T10:00:00+00:00"}
            for i in range(1, 6)
        }
        esito, visti = self._giro(self._pagine(), controlli=controlli, limit=2)
        self.assertEqual(esito["saltate"], 5)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual([v.get("offset") for v in visti[:2]], [0, 5])
        # Alla query si chiede una PAGINA (qui ridotta a 5 dal patch), non il
        # limite dell'operatore.
        self.assertEqual(visti[0].get("limit"), 5)

    def test_una_riga_mai_vista_si_lavora_anche_con_la_data_futura(self):
        # La migrazione 03 semina `prossimo_controllo_at` su TUTTE le righe,
        # comprese quelle che il resolver non ha mai guardato: se la cadenza
        # valesse anche per loro, i `nuovi` aspetterebbero due settimane. Il
        # discrimine e' `ultimo_controllo_at`, non la data del prossimo giro.
        controlli = {
            i: {"ultimo_controllo_at": None,
                "prossimo_controllo_at": "2026-12-01T00:00:00+00:00"}
            for i in range(1, 6)
        }
        esito, _ = self._giro(self._pagine(), controlli=controlli, limit=2)
        self.assertEqual(esito["saltate"], 0)
        self.assertEqual(esito["esaminati"], 2)

    def test_forza_non_ripete_lo_stesso_blocco_nella_stessa_giornata(self):
        # `--forza` vuol dire «rifai», non «rifai lo stesso blocco»: con il
        # filtro dello stato tolto e la cadenza scavalcata non restava un solo
        # predicato capace di far uscire una riga, e due lanci di fila
        # davano contatori identici.
        controlli = {
            i: {"ultimo_controllo_at": "2026-09-23T09:00:00+00:00"}
            for i in range(1, 6)
        }
        esito, visti = self._giro(
            self._pagine(), controlli=controlli, limit=2, forza=True)
        self.assertEqual(esito["saltate"], 5)
        self.assertEqual([b for b in [v.get("offset") for v in visti[:2]]], [0, 5])
        self.assertEqual(esito["esaminati"], 2)

    def test_offset_fa_ripartire_lo_scorrimento(self):
        # Il modo di lanciare i blocchi a mano quando niente puo' far uscire
        # una riga dalla selezione: `--offset 0`, `800`, `1600`.
        esito, visti = self._giro(self._pagine(), limit=2, offset=5)
        self.assertEqual(visti[0].get("offset"), 5)
        self.assertEqual(esito["offset"], 5)
        self.assertEqual(esito["esaminati"], 2)

    def test_id_singolo_non_passa_dallo_scorrimento(self):
        # `--id X` e' una riga sola, chiesta a mano: saltarla perche' e' stata
        # guardata stamattina renderebbe il comando inutile proprio quando
        # serve.
        controlli = {7: {"ultimo_controllo_at": "2026-09-23T09:00:00+00:00",
                         "prossimo_controllo_at": "2026-10-06T00:00:00+00:00"}}
        pagine = {None: [{"id": 7, "titolo": TITOLO, "ente_erogatore": ENTE,
                          "data_scadenza": "2026-09-30", "raw_data": {}}]}
        esito, visti = self._giro(pagine, controlli=controlli, bando_id=7)
        self.assertEqual(esito["esaminati"], 1)
        self.assertEqual(esito["saltate"], 0)
        self.assertEqual(visti[0].get("bando_id"), 7)


class TestScorrimentoDeiLink(unittest.TestCase):
    """`link-verifica`: la selezione di `bando_link` non ha alcun predicato.

    Niente puo' far uscire una riga dopo che e' stata verificata — nemmeno in
    modalita' attiva — quindi due lanci ripetevano gli stessi N HEAD sugli
    stessi id e le righe successive non diventavano mai `pubblicabile`.
    """

    def _giro(self, pagine, **kwargs):
        visti: list[dict[str, Any]] = []

        def _selezione(**parametri):
            visti.append(dict(parametri))
            return list(pagine.get(parametri.get("offset"), []))

        def _verifica(url):
            return {"esito_http": 200, "content_type": "text/html", "ok": True}

        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", _selezione), \
                unittest.mock.patch.object(fu, "PAGINA_SELEZIONE_LINK", 5), \
                unittest.mock.patch.object(fu, "oggi_roma", lambda: date(2026, 9, 23)):
            esito = esegui(fu.run_link_verifica(
                dry_run=True, verifica=_verifica, **kwargs))
        return esito, visti

    def _pagine(self, **extra):
        def _riga(i, **campi):
            riga = {"id": i, "bando_id": i, "url": f"https://ente.it/{i}",
                    "tipo": "pagina_bando"}
            riga.update(campi)
            return riga
        return {0: [_riga(i, **extra) for i in range(1, 6)],
                5: [_riga(i) for i in range(6, 9)]}

    def test_i_link_gia_verificati_oggi_non_consumano_il_limite(self):
        pagine = self._pagine(esito_http=200, updated_at="2026-09-23T08:00:00+00:00")
        esito, visti = self._giro(pagine, limit=2)
        self.assertEqual(esito["saltate"], 5)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual([v.get("offset") for v in visti[:2]], [0, 5])
        # Alla query si chiede una pagina (ridotta a 5 dal patch), non il 2
        # dell'operatore.
        self.assertEqual(visti[0].get("limit"), 5)

    def test_un_link_mai_verificato_si_guarda_sempre(self):
        # Le righe che `oe-dettaglio` scrive nascono `esito_http` NULL e
        # `pubblicabile=false`: sono esattamente quelle da verificare, anche
        # se il loro `updated_at` e' di oggi (lo mette l'INSERT).
        pagine = self._pagine(updated_at="2026-09-23T08:00:00+00:00")
        esito, _ = self._giro(pagine, limit=2)
        self.assertEqual(esito["saltate"], 0)
        self.assertEqual(esito["esaminati"], 2)

    def test_offset_fa_ripartire_lo_scorrimento(self):
        esito, visti = self._giro(self._pagine(), limit=2, offset=5)
        self.assertEqual(visti[0].get("offset"), 5)
        self.assertEqual(esito["esaminati"], 2)

    def test_id_singolo_guarda_i_suoi_link_anche_se_verificati_oggi(self):
        # `--id X` e' chiesto a mano: se saltasse le righe guardate stamattina
        # il comando non servirebbe proprio quando serve.
        pagine = {0: [{"id": 1, "bando_id": 42, "url": "https://ente.it/1",
                       "esito_http": 200,
                       "updated_at": "2026-09-23T08:00:00+00:00"}]}
        esito, _ = self._giro(pagine, bando_id=42)
        self.assertEqual(esito["esaminati"], 1)
        self.assertEqual(esito["saltate"], 0)


class TestCodaDeiLinkMorti(unittest.TestCase):
    """`link-verifica`: una riga guardata deve uscire dalla coda, sempre.

    `_da_verificare_ora` legge `esito_http` NULL come «mai verificata». Finche'
    un fallimento riscriveva NULL — o, se il verificatore sollevava, non
    scriveva affatto — il link morto tornava «mai verificato» al lancio
    successivo: `link-verifica --attivo --limit 200` su una fetta con 200 link
    morti in testa rifaceva per sempre gli stessi 200 HEAD, `saltate: 0`, e i
    link buoni piu' in basso non venivano guardati mai.
    """

    OGGI = date(2026, 9, 23)
    ADESSO = "2026-09-23T12:00:00+00:00"

    def _magazzino(self, quanti_morti=3, quanti_vivi=2):
        """Righe nate stamattina da `oe-dettaglio`: `esito_http` NULL,
        `updated_at` di oggi (lo mette l'INSERT), nessun `trovato_in_fonte_at`."""
        righe = {}
        for i in range(1, quanti_morti + 1):
            righe[i] = {"id": i, "bando_id": i, "url": f"https://morto.invalid/{i}",
                        "tipo": "pagina_bando", "esito_http": None,
                        "impronta_pagina": f"sha{i}#0",
                        "updated_at": "2026-09-23T08:00:00+00:00",
                        "trovato_in_fonte_at": None}
        for i in range(quanti_morti + 1, quanti_morti + quanti_vivi + 1):
            righe[i] = {"id": i, "bando_id": i, "url": f"https://ente.it/{i}",
                        "tipo": "pagina_bando", "esito_http": None,
                        "impronta_pagina": f"sha{i}#0",
                        "updated_at": "2026-09-23T08:00:00+00:00",
                        "trovato_in_fonte_at": None}
        return righe

    def _giro(self, magazzino, verifica, visti, **kwargs):
        def _selezione(*, limit=None, offset=0, bando_id=None, **_extra):
            ordinate = [magazzino[i] for i in sorted(magazzino)]
            fetta = ordinate[offset: offset + (limit or len(ordinate))]
            return [dict(r) for r in fetta]

        def _aggiorna(identificativo, payload):
            magazzino[identificativo].update(payload)
            # Il trigger `trg_bando_link_updated_at` su ogni UPDATE.
            magazzino[identificativo]["updated_at"] = self.ADESSO
            return 1

        visti.clear()
        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", _selezione), \
                unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna), \
                unittest.mock.patch.object(fu, "oggi_roma", lambda: self.OGGI), \
                unittest.mock.patch.object(fu, "_adesso", lambda: self.ADESSO):
            return esegui(fu.run_link_verifica(
                attivo=True, verifica=verifica, **kwargs))

    def test_un_link_morto_non_torna_in_coda_al_lancio_dopo(self):
        magazzino = self._magazzino()
        head: list[str] = []

        def _verifica(url):
            head.append(url)
            # La richiesta non arriva a destinazione: `VerificaHttp` torna None.
            return None if "morto.invalid" in url else {"esito_http": 200}

        primo = self._giro(magazzino, _verifica, head, limit=3)
        self.assertEqual(primo["esaminati"], 3)
        self.assertEqual(primo["saltate"], 0)
        self.assertEqual(len(head), 3)

        secondo = self._giro(magazzino, _verifica, head, limit=3)
        # I tre morti sono stati guardati oggi: si saltano, e il limite arriva
        # finalmente sui due link buoni piu' in basso.
        self.assertEqual(secondo["saltate"], 3)
        self.assertEqual(secondo["esaminati"], 2)
        self.assertEqual(secondo["pubblicabili"], 2)
        self.assertEqual([u for u in head], ["https://ente.it/4", "https://ente.it/5"])

    def test_il_marcatore_non_e_mai_null_e_non_e_un_2xx(self):
        magazzino = self._magazzino(quanti_morti=1, quanti_vivi=0)
        head: list[str] = []
        self._giro(magazzino, lambda url: head.append(url) or None, head, limit=1)
        riga = magazzino[1]
        # NULL vorrebbe dire «mai verificata» e la rimetterebbe in coda.
        self.assertIsNotNone(riga["esito_http"])
        # E non puo' essere un 2xx: il CHECK della 02 lega stato e
        # pubblicabilita', e questo link non risponde.
        self.assertFalse(200 <= int(riga["esito_http"]) < 300)
        self.assertIs(riga["pubblicabile"], False)
        self.assertFalse(fu._da_verificare_ora(riga, self.OGGI))

    def test_il_verificatore_che_solleva_lascia_comunque_la_traccia(self):
        # Prima il ramo dell'eccezione faceva `continue` senza scrivere: la
        # riga restava identica e il lancio dopo la rifaceva.
        magazzino = self._magazzino(quanti_morti=2, quanti_vivi=1)
        head: list[str] = []

        def _verifica(url):
            head.append(url)
            if "morto.invalid" in url:
                raise ConnectionError("nome non risolto")
            return {"esito_http": 200}

        primo = self._giro(magazzino, _verifica, head, limit=2)
        self.assertEqual(primo["errori"], 2)
        # Un'eccezione resta un `errori`, non diventa un `ritirati`.
        self.assertEqual(primo["ritirati"], 0)
        self.assertEqual(primo["pubblicabili"], 0)

        secondo = self._giro(magazzino, _verifica, head, limit=2)
        self.assertEqual(secondo["saltate"], 2)
        self.assertEqual(secondo["esaminati"], 1)
        self.assertEqual(head, ["https://ente.it/3"])

    def test_un_esito_senza_stato_non_riscrive_null(self):
        # `Verifica.da({})` e' un esito valido con `esito_http` None: anche
        # quello e' «guardato», non «mai guardato».
        magazzino = self._magazzino(quanti_morti=1, quanti_vivi=0)
        head: list[str] = []
        self._giro(magazzino, lambda url: head.append(url) or {}, head, limit=1)
        self.assertEqual(magazzino[1]["esito_http"], fu.ESITO_IRRAGGIUNGIBILE)

    def test_in_ombra_non_si_scrive_niente(self):
        # La correzione non deve aver aperto una scrittura fuori da `--attivo`.
        magazzino = self._magazzino(quanti_morti=1, quanti_vivi=0)
        head: list[str] = []

        def _selezione(*, limit=None, offset=0, bando_id=None, **_extra):
            return [dict(magazzino[1])] if offset == 0 else []

        def _aggiorna(identificativo, payload):       # pragma: no cover - difesa
            raise AssertionError("scrittura in ombra")

        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", _selezione), \
                unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna), \
                unittest.mock.patch.object(fu, "oggi_roma", lambda: self.OGGI):
            esito = esegui(fu.run_link_verifica(
                limit=1, attivo=False, verifica=lambda url: head.append(url) or None))
        self.assertEqual(esito["esaminati"], 1)
        self.assertIsNone(magazzino[1]["esito_http"])


class TestLinkGiaRegistrati(unittest.TestCase):
    """Il passo 1 deve leggere i link che un giro precedente ha messo in tabella.

    E' la giuntura fra i due lotti, e si era spezzata in silenzio.
    `oe-dettaglio` scarica la scheda dell'aggregatore, ne estrae gli href
    all'ente e li scrive in `bando_link` con la prova `sha256#offset`. Poi la
    regola A29 vieta — giustamente — di riscaricare una scheda gia' letta,
    quindi `candidati_da_scheda` restituisce vuoto. Se nessuno rilegge la
    tabella, al passo 1 non arriva niente: il `link_bando` di quei bandi e'
    l'URL dell'aggregatore e viene scartato, e il bando scende fino alla
    ricerca a pagamento.

    Misurato in produzione il 23/09/2026: 3 887 link estratti su 1 724 bandi.
    Tutti e 1 724 avrebbero pagato una ricerca che non serviva.
    """

    LINK_OE = "https://www.obiettivoeuropa.com/bandi/formazione-2026"

    def _bando(self, **kwargs):
        valori = {
            "id": 1, "titolo": TITOLO, "ente_erogatore": ENTE,
            "data_scadenza": "2026-09-30", "importo_totale_eur": IMPORTO,
            "raw_data": {}, "link_bando": self.LINK_OE,
        }
        valori.update(kwargs)
        return valori

    def _riga_link(self, **kwargs):
        valori = {
            "id": 10, "bando_id": 1, "url": URL_BUONO, "tipo": "pagina_bando",
            "origine": "aggregatore", "etichetta": "avviso",
            "impronta_pagina": "abc123#4096", "url_prova": self.LINK_OE,
            "esito_http": None, "pubblicabile": False,
        }
        valori.update(kwargs)
        return valori

    def _conta(self):
        chiamate = {"sonda": 0, "ricerca": 0}

        async def sonda(_ctx, _host):
            chiamate["sonda"] += 1
            return []

        async def ricerca(_query, _domini):
            chiamate["ricerca"] += 1
            return []

        return chiamate, sonda, ricerca

    def test_il_link_in_tabella_chiude_la_cascata_al_passo_1(self):
        chiamate, sonda, ricerca = self._conta()
        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            sonda=sonda, ricerca=ricerca,
            link_registrati={1: [self._riga_link()]},
        )
        esito = esegui(fu.risolvi(self._bando(), amb))
        self.assertEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(esito.url, URL_BUONO)
        # Il metodo e' quello della scheda: la prova c'e', quindi vale anche il
        # punteggio «provenienza strutturata».
        self.assertEqual(esito.metodo, "oe_scheda")
        self.assertEqual(chiamate, {"sonda": 0, "ricerca": 0},
                         "con il link gia' in tabella non si paga nessuna ricerca")

    def test_senza_i_link_in_tabella_si_arriva_a_pagare(self):
        """Il contro-esempio: e' lo stato in cui era il codice."""
        chiamate, sonda, ricerca = self._conta()
        amb = ambiente(
            pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)},
            sonda=sonda, ricerca=ricerca,
        )
        esito = esegui(fu.risolvi(self._bando(), amb))
        self.assertNotEqual(esito.stato, fu.STATO_TROVATA)
        self.assertEqual(chiamate["ricerca"], 1)

    def test_il_lotto_carica_i_link_una_volta_sola(self):
        """Il giro intero: una lettura di `bando_link`, e i candidati arrivano.

        Prova la giuntura dove si era rotta: `run` deve leggere le righe e
        passarle all'ambiente, non solo `risolvi` se qualcuno gliele mette in
        mano. La stessa lettura serve anche a `schede_gia_lette`, quindi si
        controlla che sia **una**: due sarebbero 7 626 righe lette due volte.
        """
        letture: list[dict[str, Any]] = []

        def _link(**parametri):
            letture.append(dict(parametri))
            return [self._riga_link()]

        bando = self._bando()
        amb = ambiente(pagine={URL_BUONO: pagina(URL_BUONO, corpo=CORPO_COMPLETO)})
        with unittest.mock.patch.object(fu.blocco, "acquisisci", return_value=_LockFinto()), \
                unittest.mock.patch.object(fu.blocco, "rilascia", lambda _l: None), \
                unittest.mock.patch.object(
                    fu.db, "select_bandi_da_risolvere",
                    lambda **k: [bando] if not k.get("offset") else []), \
                unittest.mock.patch.object(fu.db, "select_controlli", lambda ids, **k: {}), \
                unittest.mock.patch.object(
                    fu.db, "select_pubblicati_per_gemelli", return_value=[]), \
                unittest.mock.patch.object(fu.db, "select_link_da_verificare", _link), \
                unittest.mock.patch.object(fu, "_registra", lambda *_a, **_k: None), \
                unittest.mock.patch.object(
                    fu, "scrivi_esito", lambda *_a, **_k: {"status": "ok"}):
            esito = esegui(fu.run(dry_run=True, modo="backlog", ambiente=amb))

        self.assertEqual(len(letture), 1, "bando_link letta piu' di una volta per lotto")
        self.assertEqual(letture[0].get("bando_ids"), [1])
        self.assertEqual(amb.link_registrati.get(1)[0]["url"], URL_BUONO)
        self.assertEqual(esito["trovate"], 1)

    def test_una_riga_verso_l_aggregatore_non_diventa_candidato(self):
        candidati = fu.candidati_da_link_registrati(
            [self._riga_link(url=self.LINK_OE)], tabella=TABELLA_ENTE)
        self.assertEqual(candidati, ())

    def test_senza_prova_e_un_link_grezzo_non_una_scheda(self):
        candidati = fu.candidati_da_link_registrati(
            [self._riga_link(impronta_pagina=None, origine="raw")],
            tabella=TABELLA_ENTE)
        self.assertEqual([c.metodo for c in candidati], ["link_strutturato"])
        self.assertEqual([c.prova for c in candidati], [""])

    def test_le_righe_doppie_collassano_per_url_normalizzato(self):
        candidati = fu.candidati_da_link_registrati([
            self._riga_link(),
            self._riga_link(id=11, url=URL_BUONO + "?utm_source=x"),
        ], tabella=TABELLA_ENTE)
        self.assertEqual(len(candidati), 1)

    def test_la_prova_e_l_url_della_scheda_arrivano_nel_candidato(self):
        candidati = fu.candidati_da_link_registrati(
            [self._riga_link()], tabella=TABELLA_ENTE)
        self.assertEqual(candidati[0].prova, "abc123#4096")
        self.assertEqual(candidati[0].url_prova, self.LINK_OE)


class TestScritturaRifiutata(unittest.TestCase):
    """Il comando non puo' contare un lavoro che il database ha rifiutato.

    Difetto misurato in produzione il 23/09/2026. `oe-dettaglio` scriveva le
    righe di `bando_link` **senza** `trovato_in_fonte_at`, e il CHECK della
    migrazione 02 (`NOT pubblicabile OR trovato_in_fonte_at IS NOT NULL`)
    rifiutava ogni UPDATE che provasse a renderle pubblicabili.
    `db.controllo.aggiorna` cattura l'eccezione e la mette in un warning, e
    `link-verifica` ignorava l'esito: il primo blocco da mille ha riferito
    «pubblicabili: 847, errori: 0» e ha scritto **zero** righe.

    Il seguito era peggio del conteggio sbagliato: senza scrittura
    `esito_http` restava NULL, cioe' «mai verificata», quindi il lancio dopo
    ripresentava le stesse righe. Il ciclo «rilancia finche' esaminati non
    arriva a zero» suggerito nel runbook non sarebbe finito mai.
    """

    def _righe(self, quante=3):
        return [{"id": i, "bando_id": i, "url": f"https://ente.it/{i}",
                 "tipo": "pagina_bando", "esito_http": None,
                 "impronta_pagina": f"sha{i}#0", "trovato_in_fonte_at": None}
                for i in range(1, quante + 1)]

    def _giro(self, esito_aggiorna):
        scritture = []

        def _aggiorna(identificativo, payload):
            scritture.append((identificativo, dict(payload)))
            return esito_aggiorna

        with unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna):
            esito = esegui(fu.run_link_verifica(
                attivo=True, righe=self._righe(),
                verifica=lambda _url: (200, "text/html", "", None, None),
            ))
        return esito, scritture

    def test_la_riga_rifiutata_non_conta_come_pubblicabile(self):
        esito, _ = self._giro({"scritto": False, "motivo": "vincolo"})
        self.assertEqual(esito["pubblicabili"], 0,
                         "il comando dichiara pubblicabile una riga che non ha scritto")
        self.assertEqual(esito["non_scritte"], 3)

    def test_la_riga_scritta_conta(self):
        esito, _ = self._giro({"scritto": True})
        self.assertEqual(esito["pubblicabili"], 3)
        self.assertEqual(esito["non_scritte"], 0)

    def test_la_prova_senza_istante_viene_colmata(self):
        """Le 3 887 righe gia' scritte da `oe-dettaglio` si riparano da sole.

        Portano `impronta_pagina` ma non `trovato_in_fonte_at`, perche' il
        comando che le ha scritte non lo metteva. Invece di una migrazione, lo
        scrive `link-verifica` quando le rende pubblicabili: la prova c'e', e
        l'istante e' quello in cui la pubblicabilita' viene decisa.
        """
        _, scritture = self._giro({"scritto": True})
        for _id, payload in scritture:
            self.assertTrue(payload["pubblicabile"])
            self.assertIn("trovato_in_fonte_at", payload)

    def test_chi_ha_gia_l_istante_non_lo_riscrive(self):
        scritture = []

        def _aggiorna(identificativo, payload):
            scritture.append(dict(payload))
            return {"scritto": True}

        righe = self._righe(1)
        righe[0]["trovato_in_fonte_at"] = "2026-09-20T10:00:00+00:00"
        with unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna):
            esegui(fu.run_link_verifica(
                attivo=True, righe=righe,
                verifica=lambda _url: (200, "text/html", "", None, None)))
        self.assertNotIn("trovato_in_fonte_at", scritture[0])


class TestReteGiuNonRitiraILinkBuoni(unittest.TestCase):
    """Un fallimento nostro non e' una prova sul link (N2).

    Il marcatore `ESITO_IRRAGGIUNGIBILE` fa uscire dalla coda le righe nate da
    `oe-dettaglio`, ed e' giusto. Ma viaggia insieme a `pubblicabile=false`,
    perche' il CHECK della migrazione 02 vieta una riga pubblicabile senza un
    2xx: scriverlo su un link che aveva risposto 200 lo toglie dalle schede.

    Con la rete giu' un solo giro avrebbe ritirato tutti i link verificati
    (circa 1 360) e `_da_verificare_ora` li avrebbe saltati per il resto della
    giornata di calendario, quindi nessun giro li avrebbe rimessi prima di
    domani. Lo scavalco era solo `--id X`, un bando alla volta.
    """

    OGGI = date(2026, 9, 23)
    ADESSO = "2026-09-23T12:00:00+00:00"

    def _pubblicabili(self, quanti=5):
        """Righe verificate ieri: 200, pubblicabili, in pagina."""
        return {i: {"id": i, "bando_id": i, "url": f"https://ente.it/{i}",
                    "tipo": "pagina_bando", "esito_http": 200,
                    "pubblicabile": True,
                    "updated_at": "2026-09-22T08:00:00+00:00",
                    "trovato_in_fonte_at": "2026-09-20T08:00:00+00:00"}
                for i in range(1, quanti + 1)}

    def _giro(self, magazzino, verifica, **kwargs):
        def _selezione(*, limit=None, offset=0, bando_id=None, **_extra):
            ordinate = [magazzino[i] for i in sorted(magazzino)]
            return [dict(r) for r in ordinate[offset: offset + (limit or len(ordinate))]]

        def _aggiorna(identificativo, payload):
            magazzino[identificativo].update(payload)
            magazzino[identificativo]["updated_at"] = self.ADESSO
            return 1

        with unittest.mock.patch.object(fu.db, "select_link_da_verificare", _selezione), \
                unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna), \
                unittest.mock.patch.object(fu, "oggi_roma", lambda: self.OGGI), \
                unittest.mock.patch.object(fu, "_adesso", lambda: self.ADESSO):
            return esegui(fu.run_link_verifica(attivo=True, verifica=verifica, **kwargs))

    def test_il_verificatore_che_solleva_non_ritira_niente(self):
        magazzino = self._pubblicabili()

        def _solleva(_url):
            raise OSError("rete giu'")

        esito = self._giro(magazzino, _solleva, limit=5)
        self.assertEqual(esito["esaminati"], 5)
        self.assertEqual(esito["errori"], 5)
        self.assertEqual(esito["rimandati"], 5)
        self.assertEqual(esito["ritirati"], 0)
        for riga in magazzino.values():
            self.assertTrue(riga["pubblicabile"],
                            "un link buono e' stato ritirato per un guasto nostro")
            self.assertEqual(riga["esito_http"], 200)
            # Nessuna scrittura: `updated_at` non si muove, quindi il giro
            # successivo (lo scheduler ne fa quattro al giorno) li riprova.
            self.assertEqual(riga["updated_at"], "2026-09-22T08:00:00+00:00")

    def test_il_giro_dopo_con_la_rete_a_posto_li_riverifica(self):
        magazzino = self._pubblicabili(quanti=2)
        self._giro(magazzino, lambda _url: (_ for _ in ()).throw(OSError("giu'")), limit=2)
        esito = self._giro(magazzino, lambda _url: {"esito_http": 200}, limit=2)
        self.assertEqual(esito["esaminati"], 2)
        self.assertEqual(esito["pubblicabili"], 2)
        self.assertEqual(esito["saltate"], 0)

    def test_una_risposta_vera_non_2xx_ritira_comunque(self):
        """La distinzione e' fra «non ho potuto chiedere» e «ho chiesto e non va»."""
        magazzino = self._pubblicabili(quanti=2)
        esito = self._giro(magazzino, lambda _url: {"esito_http": 404}, limit=2)
        self.assertEqual(esito["ritirati"], 2)
        self.assertEqual(esito["rimandati"], 0)
        for riga in magazzino.values():
            self.assertFalse(riga["pubblicabile"])
            self.assertEqual(riga["esito_http"], 404)

    def test_una_riga_non_ancora_pubblicabile_riceve_il_marcatore(self):
        """Il caso per cui il marcatore esiste (F3) non deve regredire."""
        magazzino = {1: {"id": 1, "bando_id": 1, "url": "https://morto.invalid/1",
                         "tipo": "pagina_bando", "esito_http": None,
                         "pubblicabile": False,
                         "updated_at": "2026-09-22T08:00:00+00:00",
                         "trovato_in_fonte_at": None}}
        esito = self._giro(magazzino, lambda _url: None, limit=1)
        self.assertEqual(esito["rimandati"], 0)
        self.assertEqual(magazzino[1]["esito_http"], fu.ESITO_IRRAGGIUNGIBILE)
        self.assertFalse(magazzino[1]["pubblicabile"])


class TestCostoDelConfrontoGemelli(unittest.TestCase):
    """`fondi-doppioni`: il confronto e' quadratico, non va moltiplicato.

    Togliere l'impaginazione (giusto: una coppia con un id in pagina 1 e
    l'altro in pagina 3 non si trova) ha reso ogni lancio un confronto su tutto
    il corpus. Su 2 104 pubblicati sono ~4,4 milioni di coppie: ripassarle due
    volte, ricostruire per ogni riga la lista degli «altri» e proseguire dopo
    che il budget delle fusioni e' finito costava 411 s per un `--limit 10`.
    """

    # Titoli e host tutti diversi: nessun blocco, nessuna coincidenza di URL.
    # Serve un corpus che non produca ne' gemelli ne' proposte, altrimenti non
    # si vede se il confronto e' stato fatto una volta o due.
    TITOLI = (
        "Contributi per la formazione professionale",
        "Voucher per l'internazionalizzazione delle imprese",
        "Fondo per la transizione ecologica",
        "Sostegno all'occupazione giovanile",
        "Incentivi per l'efficientamento energetico",
        "Credito d'imposta per la ricerca industriale",
    )

    def _corpus(self, quanti=6):
        return [
            {"id": i, "titolo": self.TITOLI[i - 1],
             "link_bando": f"https://ente{i}.it/bando", "fonte_id": i}
            for i in range(1, quanti + 1)
        ]

    def _conta_criteri(self):
        """Intercetta `gemelli.criteri_esatti` sul modulo: cosi' si vedono
        anche le chiamate che partono da dentro `possibili_doppioni`."""
        chiamate: list[Any] = []
        vero = fu.gemelli.criteri_esatti

        def _spia(candidato, pubblicati):
            chiamate.append((candidato, pubblicati))
            return vero(candidato, pubblicati)

        return chiamate, _spia

    def test_i_criteri_esatti_si_calcolano_una_volta_per_riga(self):
        corpus = self._corpus()
        chiamate, spia = self._conta_criteri()
        with unittest.mock.patch.object(fu.gemelli, "criteri_esatti", spia):
            esito = esegui(fu.run_fondi_doppioni(dry_run=True, righe=corpus))
        self.assertEqual(esito["esaminati"], len(corpus))
        # Una per riga. Erano due: quella del runner piu' quella che
        # `possibili_doppioni` rifaceva da capo.
        self.assertEqual(len(chiamate), len(corpus))

    def test_la_lista_degli_altri_non_si_ricostruisce_per_riga(self):
        corpus = self._corpus()
        chiamate, spia = self._conta_criteri()
        with unittest.mock.patch.object(fu.gemelli, "criteri_esatti", spia):
            esegui(fu.run_fondi_doppioni(dry_run=True, righe=corpus))
        elenchi = [pubblicati for _candidato, pubblicati in chiamate]
        # Sempre lo stesso oggetto, e completo: la riga corrente la salta
        # `criteri_esatti`, non una copia nuova da n-1 dizionari per riga.
        self.assertTrue(all(e is elenchi[0] for e in elenchi))
        self.assertEqual(len(elenchi[0]), len(corpus))

    def test_la_riga_corrente_resta_fuori_dalle_proprie_corrispondenze(self):
        # Passare l'elenco intero non deve far diventare una riga gemella di
        # se' stessa: sarebbe una fusione su se' stessa.
        corpus = self._corpus(quanti=3)
        esito = esegui(fu.run_fondi_doppioni(dry_run=True, righe=corpus))
        self.assertEqual(esito["esatti"], 0)
        self.assertEqual(esito["proposte"], 0)

    def _corpus_con_gemelli(self, coppie=3):
        righe = []
        for c in range(coppie):
            url = f"https://regione.marche.it/bando-{c}"
            righe.append({"id": 2 * c + 1, "titolo": f"Bando {c}",
                          "link_bando": url, "fonte_id": 1})
            righe.append({"id": 2 * c + 2, "titolo": f"Bando {c}",
                          "link_bando": url, "fonte_id": 2})
        return righe

    def test_il_budget_finito_ferma_il_confronto_quando_si_fonde(self):
        corpus = self._corpus_con_gemelli()
        with unittest.mock.patch.object(
                fu.db, "fondi_bandi", lambda master, doppione, motivo: master):
            esito = esegui(fu.run_fondi_doppioni(attivo=True, limit=1, righe=corpus))
        self.assertEqual(esito["fusi"], 1)
        # Il confronto non prosegue sul resto del corpus: e' quadratico, e
        # questo lancio non sta chiedendo il report.
        self.assertLess(esito["esaminati"], len(corpus))
        self.assertGreater(esito["rimandati"], 0)
        # E il troncamento si dichiara.
        self.assertTrue(any("budget" in a for a in esito["allarmi"]))

    def test_in_ombra_il_report_copre_comunque_tutto_il_corpus(self):
        # In ombra il report **e'** il prodotto del lancio: qui fermarsi
        # sarebbe la correzione peggiore del difetto.
        corpus = self._corpus_con_gemelli()
        esito = esegui(fu.run_fondi_doppioni(dry_run=True, limit=1, righe=corpus))
        self.assertEqual(esito["esaminati"], len(corpus))
        self.assertEqual(esito["allarmi"], [])

    def test_limit_zero_resta_solo_report_su_tutto_il_corpus(self):
        corpus = self._corpus_con_gemelli()
        fusioni: list[Any] = []
        with unittest.mock.patch.object(
                fu.db, "fondi_bandi",
                lambda master, doppione, motivo: fusioni.append(doppione) or master):
            esito = esegui(fu.run_fondi_doppioni(attivo=True, limit=0, righe=corpus))
        self.assertEqual(fusioni, [])
        self.assertEqual(esito["esaminati"], len(corpus))
        self.assertEqual(esito["allarmi"], [])

    def test_i_gemelli_certi_passati_da_fuori_danno_lo_stesso_esito(self):
        # `esatti` calcolato dentro o passato da fuori deve dare la stessa
        # tupla: e' l'unica cosa che il parametro nuovo ha il diritto di
        # cambiare, cioe' niente.
        corpus = [
            # gemello certo del primo (stesso URL): esce dal fuzzy
            {"id": 1, "titolo": "Bando per la formazione professionale 2025",
             "link_bando": "https://regione.marche.it/b1", "fonte_id": 1},
            {"id": 2, "titolo": "Titolo tutto diverso",
             "link_bando": "https://regione.marche.it/b1", "fonte_id": 2},
            # quasi doppione (stesso host, un anno di differenza): resta una
            # proposta, e le proposte non si fondono mai
            {"id": 3, "titolo": "Bando per la formazione professionale 2026",
             "link_bando": "https://regione.marche.it/b3", "fonte_id": 3},
        ]
        candidato = corpus[0]
        esatti = [c.bando_id for c in fu.gemelli.criteri_esatti(candidato, corpus)]
        self.assertEqual(esatti, [2])
        dentro = fu.gemelli.possibili_doppioni(candidato, corpus)
        fuori = fu.gemelli.possibili_doppioni(candidato, corpus, esatti=esatti)
        self.assertEqual([p.bando_id for p in dentro], [3])
        self.assertEqual(dentro, fuori)


if __name__ == "__main__":                              # pragma: no cover
    unittest.main()


class TestTitoloDellaFonte(unittest.TestCase):
    """Il segnale «titolo» va confrontato col titolo della FONTE, non col nostro.

    `bando.titolo` e' il titolo editoriale che la pipeline genera per i lettori;
    `bando.titolo_raw` e' come il bando si chiama nella fonte. La pagina
    dell'ente porta il secondo. Misurato su un caso qualunque il 24/09/2026:

        titolo      Contributi fondo perduto per cortometraggi di interesse
                    regionale in Sardegna
        titolo_raw  Sardegna - Concessione di contributi finalizzati alla
                    produzione di cortometraggi di rilevante interesse regionale

    Confrontando solo il primo, il segnale non scattava quasi mai, e senza di
    esso i tre segnali richiesti da `trovata` non si completano: **437 bandi su
    2 134 avevano un punteggio da `trovata` e restavano `in_verifica`** per
    questo motivo, dopo un giro del resolver su tutto il corpus.
    """

    TITOLO_NOSTRO = "Contributi fondo perduto per cortometraggi di interesse regionale in Sardegna"
    TITOLO_FONTE = ("Sardegna - Concessione di contributi finalizzati alla produzione "
                    "di cortometraggi di rilevante interesse regionale")

    def _contesto(self, **extra):
        valori = {"titolo": self.TITOLO_NOSTRO, "titolo_fonte": self.TITOLO_FONTE}
        valori.update(extra)
        return contesto(**valori)

    def _pagina_dell_ente(self):
        # La pagina si intitola come la fonte, non come noi.
        return pagina(URL_BUONO, titolo=self.TITOLO_FONTE, corpo=CORPO_COMPLETO)

    def test_il_titolo_della_fonte_fa_scattare_il_segnale(self):
        p = fu.punteggia(candidato(pag=self._pagina_dell_ente()), self._contesto())
        self.assertIn(fu.SEGNALE_TITOLO, p.segnali,
                      "il segnale titolo non scatta: i tre segnali non si completeranno mai")
        self.assertEqual(p.segnali, fu.SEGNALI_RICHIESTI)
        self.assertEqual(p.stato, fu.STATO_TROVATA)

    def test_senza_il_titolo_della_fonte_restava_in_verifica(self):
        """Il comportamento di prima, sullo stesso candidato."""
        p = fu.punteggia(candidato(pag=self._pagina_dell_ente()),
                         contesto(titolo=self.TITOLO_NOSTRO))
        self.assertNotIn(fu.SEGNALE_TITOLO, p.segnali)
        self.assertGreaterEqual(p.valore, fu.SOGLIA_VERIFICA)
        self.assertEqual(p.stato, fu.STATO_IN_VERIFICA,
                         "e' il difetto misurato: punteggio buono, stato no")

    def test_vince_il_confronto_migliore_dei_due(self):
        # Se e' il titolo NOSTRO a somigliare alla pagina, il segnale scatta
        # comunque: si prende il massimo, non si sostituisce una fonte all'altra.
        p = fu.punteggia(
            candidato(pag=pagina(URL_BUONO, titolo=self.TITOLO_NOSTRO, corpo=CORPO_COMPLETO)),
            self._contesto(),
        )
        self.assertIn(fu.SEGNALE_TITOLO, p.segnali)

    def test_senza_titolo_raw_niente_cambia(self):
        # Gli 86 pubblicati che non hanno `titolo_raw`: si comportano come prima.
        p = fu.punteggia(candidato(pag=self._pagina_dell_ente()),
                         self._contesto(titolo_fonte=""))
        self.assertNotIn(fu.SEGNALE_TITOLO, p.segnali)

    def test_il_contesto_legge_titolo_raw_dalla_riga(self):
        c = fu.contesto_da_bando({
            "id": 1, "titolo": self.TITOLO_NOSTRO, "titolo_raw": self.TITOLO_FONTE,
            "ente_erogatore": ENTE,
        })
        self.assertEqual(c.titolo, self.TITOLO_NOSTRO)
        self.assertEqual(c.titolo_fonte, self.TITOLO_FONTE)
        self.assertTrue(c.token_titolo_fonte)
        # L'unione serve ai gate morbidi: una pagina con il titolo ufficiale e
        # non il nostro non e' un soft-404 ne' una pagina indice.
        self.assertEqual(c.token_titolo_qualsiasi, c.token_titolo | c.token_titolo_fonte)

    def test_una_pagina_con_il_solo_titolo_ufficiale_non_e_un_soft404(self):
        # Prima il gate morbido guardava solo i token del titolo editoriale: una
        # pagina giusta, intitolata come la fonte, poteva essere scartata.
        p = fu.punteggia(candidato(pag=self._pagina_dell_ente()), self._contesto())
        self.assertTrue(p.duri_superati)
        self.assertIsNone(p.tetto)


class TestNessunaRispostaNonEAssenza(unittest.TestCase):
    """«Non ho potuto chiedere» non e' «la risposta e' no».

    `non_trovata` vuol dire «cercato e non c'e'», e costa sessanta giorni prima
    del ricontrollo (A33) contro i quattordici di `in_verifica`. Darlo quando le
    pagine dei candidati non hanno risposto significa registrare come assenza
    della fonte un guasto della nostra rete o del server dell'ente, e
    parcheggiare il bando per due mesi.

    E' lo stesso difetto che `link-verifica` aveva sui link morti, nello stesso
    punto concettuale: un esito mancante trattato come un esito negativo.
    """

    def _valutati(self, *stati):
        """Un candidato per stato HTTP, con il punteggio che i gate gli danno."""
        fuori = []
        for i, stato in enumerate(stati):
            pag = None if stato is None else fu.Pagina(
                url=f"https://regione.marche.it/{i}", stato=stato, testo="", intestazioni="")
            cand = fu.Candidato(url=f"https://regione.marche.it/{i}", pagina=pag)
            fuori.append((cand, fu.punteggia(cand, contesto())))
        return fuori

    def test_nessuna_risposta_resta_in_verifica(self):
        for stato in (None, 503, 502, 500, 429, 504):
            with self.subTest(stato=stato):
                esito, motivo = fu._esito_senza_candidato_valido(self._valutati(stato))
                self.assertEqual(esito, fu.STATO_IN_VERIFICA, f"stato HTTP {stato}")
                self.assertIn("rete", motivo)

    def test_un_404_e_un_giudizio(self):
        # La pagina non c'e': e' un'informazione sul bando, non sulla rete.
        esito, motivo = fu._esito_senza_candidato_valido(self._valutati(404))
        self.assertEqual(esito, fu.STATO_NON_TROVATA)
        self.assertIn("gate", motivo)

    def test_basta_un_candidato_giudicato_perche_sia_un_giudizio(self):
        # Misto: uno non risponde, uno risponde 404. Il secondo e' una risposta,
        # quindi il giro ha davvero guardato e `non_trovata` e' corretto.
        esito, _ = fu._esito_senza_candidato_valido(self._valutati(503, 404))
        self.assertEqual(esito, fu.STATO_NON_TROVATA)

    def test_nessun_candidato_resta_non_trovata(self):
        # Nessun URL da provare: qui `non_trovata` e' l'esito giusto, e il
        # motivo lo distingue dal caso «provati e nessuna risposta».
        esito, motivo = fu._esito_senza_candidato_valido([])
        self.assertEqual(esito, fu.STATO_NON_TROVATA)
        self.assertEqual(motivo, "nessun candidato")

    def test_la_cadenza_segue_lo_stato(self):
        """Il punto per cui la distinzione conta: quattordici giorni o sessanta."""
        oggi = date(2026, 9, 24)
        fra_in_verifica, _, _ = fu.prossimo_controllo(fu.STATO_IN_VERIFICA, 0, oggi)
        fra_non_trovata, _, _ = fu.prossimo_controllo(fu.STATO_NON_TROVATA, 0, oggi)
        self.assertLess(fra_in_verifica, fra_non_trovata,
                        "in_verifica deve tornare in coda prima di non_trovata")


class TestAncheOggi(unittest.TestCase):
    """`--anche-oggi`: rifare oggi cio' che oggi e' gia' stato fatto.

    Con `--forza` la cadenza non vale piu', ma una riga lavorata **oggi** si
    salta lo stesso: e' la guardia che impedisce a due lanci di fila nella
    stessa giornata di ripetere lo stesso blocco di id.

    C'e' pero' un caso in cui rifare e' esattamente cio' che serve: **le regole
    sono cambiate sotto le righe**. Il 24/09/2026 sono stati 1 923 bandi,
    risolti la mattina e poi rimasti indietro quando la whitelist ha smesso di
    chiamare «sconosciuti» i portali regionali. Senza questo flag l'unica
    alternativa era aspettare il giorno dopo, oppure falsificare a mano
    `ultimo_controllo_at`, che e' peggio.
    """

    OGGI = date(2026, 9, 24)

    def _controllo(self, quando):
        return {"ultimo_controllo_at": quando, "prossimo_controllo_at": "2026-11-23"}

    def test_senza_il_flag_una_riga_di_oggi_si_salta(self):
        oggi = self._controllo("2026-09-24T09:30:00+00:00")
        self.assertFalse(fu._da_risolvere_ora(oggi, self.OGGI, forza=True))

    def test_col_flag_la_stessa_riga_si_rifa(self):
        oggi = self._controllo("2026-09-24T09:30:00+00:00")
        self.assertTrue(fu._da_risolvere_ora(oggi, self.OGGI, forza=True, anche_oggi=True))

    def test_il_flag_non_serve_a_chi_e_stato_lavorato_ieri(self):
        ieri = self._controllo("2026-09-23T09:30:00+00:00")
        self.assertTrue(fu._da_risolvere_ora(ieri, self.OGGI, forza=True))
        self.assertTrue(fu._da_risolvere_ora(ieri, self.OGGI, forza=True, anche_oggi=True))

    def test_senza_forza_il_flag_non_fa_niente(self):
        # `--anche-oggi` e' una deroga alla guardia del giorno, che vive dentro
        # il ramo `--forza`. Da solo non deve scavalcare la cadenza: quella e'
        # la protezione dal rilavorare una riga ogni giro, e costa crediti.
        oggi = self._controllo("2026-09-24T09:30:00+00:00")
        self.assertFalse(fu._da_risolvere_ora(oggi, self.OGGI, forza=False, anche_oggi=True))

    def test_una_riga_mai_vista_si_lavora_comunque(self):
        self.assertTrue(fu._da_risolvere_ora(None, self.OGGI, forza=False))
        self.assertTrue(fu._da_risolvere_ora({}, self.OGGI, forza=True, anche_oggi=True))


class TestLinkDiBackfillPromosso(unittest.TestCase):
    """La fonte trovata non puo' puntare a una riga che anon non legge.

    Difetto misurato in produzione il 24/09/2026: **137 delle 495** fonti
    `trovata` avevano `fonte_ufficiale_link_id` su una riga di `bando_link`
    creata dal backfill della migrazione 02 (`origine='raw'`,
    `trovato_in_fonte_at` NULL, `pubblicabile=false`). Causa:
    `upsert_bando_link` usa `ignore_duplicates=True` perche' `url` e'
    immutabile, quindi la riga che esiste non viene riscritta; il resolver ne
    adottava l'id senza promuoverla. Risultato: una fonte dichiarata trovata
    che punta a una riga esclusa dalla RLS, contro la promessa di §13.4.
    """

    def _riga_backfill(self, **extra):
        riga = {"id": 77, "bando_id": 5, "url": "https://regione.esempio.it/bando",
                "tipo": "pagina_bando", "origine": "raw", "esito_http": 200,
                "pubblicabile": False, "trovato_in_fonte_at": None,
                "impronta_pagina": None, "url_prova": None}
        riga.update(extra)
        return riga

    def _giro(self, esito, riga, scritto=True):
        scritture = []

        def _aggiorna(identificativo, payload, **_k):
            scritture.append((identificativo, dict(payload)))
            return {"scritto": scritto}

        with unittest.mock.patch.object(fu.db, "upsert_bando_link", lambda *a, **k: 1), \
             unittest.mock.patch.object(
                 fu.db, "select_link_da_verificare", lambda **k: [riga]), \
             unittest.mock.patch.object(fu.db, "aggiorna_fonte_ufficiale",
                                        lambda *a, **k: {"scritto": True}), \
             unittest.mock.patch.object(fu.db, "aggiorna_controllo",
                                        lambda *a, **k: {"scritto": True}), \
             unittest.mock.patch.object(fu.db, "registra_evento", lambda *a, **k: True), \
             unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna):
            esito_scrittura = fu.scrivi_esito(esito, attivo=True)
        return esito_scrittura, scritture

    def _esito(self, **extra):
        valori = {"bando_id": 5, "stato": fu.STATO_TROVATA,
                  "url": "https://regione.esempio.it/bando",
                  "host": "regione.esempio.it", "tipo": None,
                  "esito_http": 200, "prova": "sha256#0",
                  "url_prova": "https://regione.esempio.it/bando"}
        valori.update(extra)
        return fu.Esito(**valori)

    def test_la_riga_di_backfill_diventa_pubblicabile(self):
        esito, scritture = self._giro(self._esito(), self._riga_backfill())
        self.assertTrue(esito["link_promosso"], "la riga adottata non e' stata promossa")
        self.assertEqual(len(scritture), 1)
        identificativo, payload = scritture[0]
        self.assertEqual(identificativo, 77)
        self.assertTrue(payload["pubblicabile"])
        self.assertIsNotNone(payload["trovato_in_fonte_at"],
                             "pubblicabile senza la data viola il CHECK della 02")
        self.assertEqual(payload["impronta_pagina"], "sha256#0")
        for vietata in ("url", "url_normalizzato", "bando_id"):
            self.assertNotIn(vietata, payload,
                             f"{vietata} e' immutabile: il trigger rifiuta l'UPDATE")

    def test_una_riga_gia_pubblicabile_non_si_riscrive(self):
        riga = self._riga_backfill(pubblicabile=True, trovato_in_fonte_at="2026-09-20T10:00:00",
                                   impronta_pagina="sha256#0",
                                   url_prova="https://regione.esempio.it/bando")
        esito, scritture = self._giro(self._esito(), riga)
        self.assertFalse(esito["link_promosso"])
        self.assertEqual(scritture, [], "UPDATE inutile su una riga gia' a posto")

    def test_senza_2xx_non_si_promuove_niente(self):
        esito, scritture = self._giro(self._esito(esito_http=None), self._riga_backfill())
        self.assertFalse(esito["link_promosso"])
        self.assertEqual(scritture, [],
                         "una riga pubblicabile senza 2xx osservato non e' scrivibile")

    def test_una_fonte_non_trovata_non_promuove(self):
        esito, scritture = self._giro(
            self._esito(stato=fu.STATO_IN_VERIFICA), self._riga_backfill())
        self.assertFalse(esito["link_promosso"])
        self.assertEqual(scritture, [])

    def test_l_atto_corregge_il_tipo_della_riga(self):
        esito, scritture = self._giro(self._esito(e_atto=True), self._riga_backfill())
        self.assertEqual(scritture[0][1]["tipo"], "atto")

    def test_il_rifiuto_del_database_non_si_conta(self):
        esito, _ = self._giro(self._esito(), self._riga_backfill(), scritto=False)
        self.assertFalse(esito["link_promosso"],
                         "promozione dichiarata su una riga che il DB ha rifiutato")


class TestProvaDellaFonteUfficiale(unittest.TestCase):
    """`link-verifica` deve poter promuovere la riga scelta dal resolver.

    Le righe `raw` del backfill della 02 non hanno prova di provenienza e
    restano giustamente non pubblicabili. Ma quando una di quelle righe e' la
    fonte ufficiale di un bando `trovata`, la prova esiste: il resolver ha
    scaricato quell'URL e ci ha puntato `fonte_ufficiale_link_id`. Senza
    questo ramo le 137 righe misurate il 24/09/2026 non avevano **nessun**
    percorso di riparazione, perche' `risolvi-fonte` non ripassa su un bando
    gia' `trovata`.
    """

    def _riga(self, identificativo=77):
        return {"id": identificativo, "bando_id": 5,
                "url": "https://regione.esempio.it/bando", "tipo": "pagina_bando",
                "origine": "raw", "esito_http": None, "pubblicabile": False,
                "trovato_in_fonte_at": None, "impronta_pagina": None}

    def _giro(self, fonti):
        scritture = []

        def _aggiorna(identificativo, payload, **_k):
            scritture.append((identificativo, dict(payload)))
            return {"scritto": True}

        with unittest.mock.patch.object(fu.db, "select_link_delle_fonti", lambda **k: fonti), \
             unittest.mock.patch.object(fu.db, "aggiorna_link", _aggiorna):
            esito = esegui(fu.run_link_verifica(
                attivo=True, righe=[self._riga()],
                verifica=lambda _url: (200, "text/html", "", None, None),
            ))
        return esito, scritture

    def test_la_fonte_ufficiale_ha_la_prova(self):
        esito, scritture = self._giro({77})
        self.assertEqual(esito["pubblicabili"], 1)
        self.assertEqual(esito["senza_prova"], 0)
        self.assertTrue(scritture[0][1]["pubblicabile"])
        self.assertIsNotNone(scritture[0][1]["trovato_in_fonte_at"],
                             "il CHECK della 02 pretende la data insieme al flag")

    def test_una_riga_raw_qualunque_resta_senza_prova(self):
        esito, scritture = self._giro(set())
        self.assertEqual(esito["pubblicabili"], 0)
        self.assertEqual(esito["senza_prova"], 1)
        self.assertFalse(scritture[0][1]["pubblicabile"],
                         "una riga che nessuno ha visto in una pagina non e' pubblicabile")
