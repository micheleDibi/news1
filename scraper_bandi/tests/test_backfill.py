# -*- coding: utf-8 -*-
"""`backfill.py`: i lotti L7 (`pulisci-contenuto`) e L8 (`archivia-processed`).

Le due regole che questi test difendono sono quelle che, se saltassero, non si
noterebbero subito:

1. un link all'aggregatore si sostituisce con la fonte ufficiale **solo se e'
   `trovata`**; altrimenti il segmento si declassa a testo. Mai un link
   inventato, mai un aggregatore che resta spacciato per «scheda ufficiale»;
2. `archivia-processed` non tocca **nessuna** riga pubblicata e non fabbrica
   chiusure: una riga senza scadenza e senza stato chiuso resta dov'e'.

Nessuna rete, nessun DB: righe, link, scrittura e archiviazione sono iniettati.
"""
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tests.supporto import carica_modulo

backfill = carica_modulo("backfill")

OGGI = date(2026, 9, 23)
AGGREGATORE = "https://www.obiettivoeuropa.com/bandi/942936"
UFFICIALE = "https://www.lazioeuropa.it/bandi/psicologia-scolastica"


def _segmenti(*voci):
    return [dict(v) for v in voci]


def _contenuto_con_link(url=AGGREGATORE):
    return {
        "sections": [
            {"type": "h2", "text": "Come partecipare"},
            {"type": "paragraph", "segments": _segmenti(
                {"kind": "text", "text": "Consulta la "},
                {"kind": "link", "text": "scheda ufficiale del bando", "url": url},
            )},
            {"type": "bullet_list", "items": [
                {"segments": _segmenti(
                    {"kind": "link", "text": "pagina ufficiale", "url": url})},
            ]},
            {"type": "faq", "items": [
                {"q": "Dove si presenta?", "a": {"segments": _segmenti(
                    {"kind": "link", "text": "qui", "url": url})}},
            ]},
        ]
    }


def _bando(**extra):
    riga = {
        "id": 942936,
        "slug": "psicologia-scolastica",
        "titolo": "Psicologia scolastica",
        "contenuto": _contenuto_con_link(),
        "link_candidatura": AGGREGATORE,
        "link_candidatura_source": "fallback_source",
        "fonte_ufficiale_url": UFFICIALE,
        "fonte_ufficiale_stato": "trovata",
        "stato_processing": "completed",
        "pubblicato": True,
    }
    riga.update(extra)
    return riga


def _registra_finto():
    """Nessun test deve arrivare a `db.registra_evento`: il DB non esiste."""
    return lambda evento: True


def _scrivi(registro, esito=True):
    async def scrivi(bando_id, payload):
        registro.append((bando_id, payload))
        return esito
    return scrivi


def _urls(contenuto):
    """Tutti gli `url` dei segmenti, in qualunque forma di sezione vivano."""
    trovati = []

    def leggi(segmenti):
        for segmento in segmenti or ():
            if isinstance(segmento, dict) and segmento.get("kind") == "link":
                trovati.append(segmento.get("url"))

    for sezione in contenuto.get("sections", ()):
        leggi(sezione.get("segments"))
        for voce in sezione.get("items", ()) or ():
            leggi(voce.get("segments"))
            risposta = voce.get("a") or {}
            leggi(risposta.get("segments"))
    return trovati


# --- L7: pulizia del contenuto (funzioni pure) ------------------------------

class TestRipulisciContenuto(unittest.TestCase):
    def test_con_fonte_trovata_i_link_diventano_ufficiali(self):
        nuovo, conto = backfill.ripulisci_contenuto(
            _contenuto_con_link(), fonte_url=UFFICIALE)
        self.assertEqual(conto, {"sostituiti": 3, "declassati": 0})
        self.assertEqual(_urls(nuovo), [UFFICIALE] * 3)

    def test_senza_fonte_il_segmento_si_declassa_a_testo(self):
        nuovo, conto = backfill.ripulisci_contenuto(
            _contenuto_con_link(), fonte_url=None)
        self.assertEqual(conto, {"sostituiti": 0, "declassati": 3})
        self.assertEqual(_urls(nuovo), [])
        # Il testo dell'anchor resta: sparisce il link, non la frase.
        primo = nuovo["sections"][1]["segments"][1]
        self.assertEqual(primo, {"kind": "text", "text": "scheda ufficiale del bando"})

    def test_i_link_non_aggregatori_non_si_toccano(self):
        contenuto = _contenuto_con_link(UFFICIALE)
        nuovo, conto = backfill.ripulisci_contenuto(contenuto, fonte_url=UFFICIALE)
        self.assertEqual(conto, {"sostituiti": 0, "declassati": 0})
        # Niente da cambiare: torna lo **stesso** oggetto, non una copia.
        self.assertIs(nuovo, contenuto)

    def test_contenuto_non_oggetto_passa_intatto(self):
        for valore in ('{"sections": [', None, ["x"], {"testo": "x"}):
            with self.subTest(valore=valore):
                nuovo, conto = backfill.ripulisci_contenuto(valore, fonte_url=UFFICIALE)
                self.assertIs(nuovo, valore)
                self.assertEqual(conto, {"sostituiti": 0, "declassati": 0})

    def test_segmenti_storti_non_fanno_saltare_il_giro(self):
        contenuto = {"sections": [
            {"type": "paragraph", "segments": ["stringa", None,
                                               {"kind": "link"}]},
            "sezione non oggetto",
        ]}
        nuovo, conto = backfill.ripulisci_contenuto(contenuto, fonte_url=UFFICIALE)
        self.assertEqual(conto, {"sostituiti": 0, "declassati": 0})
        self.assertIs(nuovo, contenuto)


class TestScegliCandidatura(unittest.TestCase):
    def test_il_bando_link_di_candidatura_vince(self):
        esito = backfill.scegli_candidatura(
            _bando(), candidatura_url="https://ente.it/domanda")
        self.assertEqual(esito[:2], ("https://ente.it/domanda", "extracted"))

    def test_senza_bando_link_ripiega_sulla_fonte(self):
        url, sorgente, _ = backfill.scegli_candidatura(_bando())
        self.assertEqual((url, sorgente), (UFFICIALE, "fallback_source"))

    def test_fonte_non_trovata_significa_nessun_pulsante(self):
        url, sorgente, _ = backfill.scegli_candidatura(
            _bando(fonte_ufficiale_stato="in_verifica"))
        self.assertIsNone(url)
        self.assertEqual(sorgente, "missing")

    def test_un_aggregatore_non_e_mai_un_ripiego(self):
        # Ne' come CTA gia' in colonna ne' come `bando_link`.
        url, _, _ = backfill.scegli_candidatura(
            _bando(fonte_ufficiale_stato="non_trovata"), candidatura_url=AGGREGATORE)
        self.assertIsNone(url)

    def test_source_incoerente_si_riallinea_senza_toccare_l_url(self):
        # 28 righe hanno un URL buono con `source='missing'`.
        url, sorgente, motivo = backfill.scegli_candidatura(
            _bando(link_candidatura="https://ente.it/domanda",
                   link_candidatura_source="missing"))
        self.assertEqual(url, "https://ente.it/domanda")
        self.assertEqual(sorgente, "fallback_source")
        self.assertEqual(motivo, "source incoerente")

    def test_source_resta_dentro_i_tre_valori_ammessi(self):
        ammessi = {"extracted", "fallback_source", "missing"}
        casi = [
            (_bando(), None),
            (_bando(), "https://ente.it/x"),
            (_bando(fonte_ufficiale_stato="non_trovata", link_candidatura=None,
                    link_candidatura_source=None), None),
        ]
        for riga, candidatura in casi:
            with self.subTest(candidatura=candidatura):
                self.assertIn(
                    backfill.scegli_candidatura(riga, candidatura_url=candidatura)[1],
                    ammessi)


class TestPayloadPulizia(unittest.TestCase):
    def test_riga_gia_pulita_non_produce_payload(self):
        riga = _bando(contenuto=_contenuto_con_link(UFFICIALE),
                      link_candidatura=UFFICIALE)
        payload, _ = backfill.payload_pulizia(riga)
        self.assertEqual(payload, {})

    def test_source_nulla_vale_missing(self):
        # Senza questa equivalenza il lotto riscriverebbe 1 900 righe per
        # cambiare NULL in «missing».
        riga = _bando(fonte_ufficiale_stato="non_trovata", link_candidatura=None,
                      link_candidatura_source=None,
                      contenuto=_contenuto_con_link(UFFICIALE))
        payload, _ = backfill.payload_pulizia(riga)
        self.assertEqual(payload, {})

    def test_paga_solo_le_colonne_che_deve(self):
        payload, conto = backfill.payload_pulizia(_bando())
        self.assertEqual(
            set(payload), {"contenuto", "link_candidatura", "link_candidatura_source"})
        self.assertEqual(conto["sostituiti"], 3)
        self.assertEqual(conto["cta"], 1)


# --- L7: il comando ---------------------------------------------------------

class TestOmbraPerDifetto(unittest.TestCase):
    """`--ombra` vince sull'ambiente: i tre gemelli devono rispondere uguale.

    Il difetto: i lotti ereditavano l'interruttore del monitor e l'operatore
    che scriveva `--ombra` non otteneva nulla. Con `MONITOR_MODALITA=attivo`
    (la configurazione che la tappa D prescrive) `pulisci-contenuto --ombra`
    girava in modalita' attiva.
    """

    def _con_modalita(self, valore):
        finte = MagicMock()
        finte.monitor_modalita = valore
        finte.resolver_modalita = valore
        return finte

    def test_i_tre_gemelli(self):
        rigenera = carica_modulo("rigenera")
        fonte_ufficiale = carica_modulo("fonte_ufficiale")
        gemelli = (
            ("backfill", backfill._attivo),
            ("rigenera", rigenera._attivo),
            ("fonte_ufficiale", fonte_ufficiale._modalita_attiva),
        )
        for nome, funzione in gemelli:
            for modalita, atteso_none in (("attivo", True), ("ombra", False)):
                with self.subTest(modulo=nome, ambiente=modalita):
                    finte = self._con_modalita(modalita)
                    with patch.object(
                        carica_modulo("settings"), "get_settings", lambda: finte,
                    ):
                        # `None` = «non detto»: decide l'ambiente.
                        self.assertEqual(funzione(None), atteso_none)
                        # `False` = «--ombra»: vince sempre.
                        self.assertFalse(funzione(False))
                        # `True` = «--attivo».
                        self.assertTrue(funzione(True))


class TestRunPulisciContenuto(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for bersaglio in (
            patch.object(backfill, "_scrivi_run", MagicMock()),
            patch.object(backfill, "_tetti", lambda: backfill.bilancio.Tetti()),
        ):
            bersaglio.start()
            self.addCleanup(bersaglio.stop)

    async def test_ombra_per_difetto_non_scrive(self):
        scritture = []
        esito = await backfill.run_pulisci_contenuto(
            righe=[_bando()], link=[], scrivi=_scrivi(scritture))
        self.assertEqual(esito["step"], "backfill:L7")
        self.assertEqual(esito["cambiati"], 1)
        self.assertEqual(esito["scritti"], 0)
        self.assertEqual(scritture, [])

    async def test_attivo_scrive_e_registra_la_rettifica(self):
        scritture, eventi = [], []
        esito = await backfill.run_pulisci_contenuto(
            attivo=True, righe=[_bando()], link=[],
            scrivi=_scrivi(scritture), registra=lambda e: eventi.append(e) or True)
        self.assertEqual(esito["scritti"], 1)
        self.assertEqual(esito["eventi"], 1)
        self.assertEqual(_urls(scritture[0][1]["contenuto"]), [UFFICIALE] * 3)
        evento = eventi[0]
        self.assertEqual((evento["tipo"], evento["campo"]), ("rettifica", "contenuto"))
        # Non e' una notizia per il lettore: e' una correzione nostra. Ma deve
        # ricevere il cursore, perche' e' cosi' che i consumatori invalidano.
        self.assertFalse(evento["in_aggiornamenti"])
        self.assertTrue(evento["leggibile"])
        self.assertFalse(evento["verificato"])

    async def test_dry_run_e_piu_forte_di_attivo(self):
        scritture = []
        await backfill.run_pulisci_contenuto(
            attivo=True, dry_run=True, righe=[_bando()], link=[],
            scrivi=_scrivi(scritture), registra=_registra_finto())
        self.assertEqual(scritture, [])

    async def test_il_payload_non_tocca_mai_slug_titolo_o_pubblicazione(self):
        scritture = []
        await backfill.run_pulisci_contenuto(
            attivo=True, righe=[_bando()], link=[], scrivi=_scrivi(scritture),
            registra=_registra_finto())
        vietate = {"slug", "titolo", "stato_processing", "pubblicato",
                   "data_pubblicazione"}
        self.assertFalse(vietate & set(scritture[0][1]))

    async def test_il_bando_link_di_candidatura_arriva_dal_lotto(self):
        scritture = []
        await backfill.run_pulisci_contenuto(
            attivo=True, righe=[_bando()], scrivi=_scrivi(scritture),
            registra=_registra_finto(),
            link=[{"bando_id": 942936, "tipo": "candidatura",
                   "pubblicabile": True, "url": "https://ente.it/domanda"}],
        )
        payload = scritture[0][1]
        self.assertEqual(payload["link_candidatura"], "https://ente.it/domanda")
        self.assertEqual(payload["link_candidatura_source"], "extracted")

    async def test_i_link_non_pubblicabili_non_diventano_cta(self):
        scritture = []
        await backfill.run_pulisci_contenuto(
            attivo=True, righe=[_bando()], scrivi=_scrivi(scritture),
            registra=_registra_finto(),
            link=[{"bando_id": 942936, "tipo": "candidatura",
                   "pubblicabile": False, "url": "https://ente.it/domanda"}],
        )
        self.assertEqual(scritture[0][1]["link_candidatura"], UFFICIALE)

    async def test_scrittura_fallita_e_un_errore_contato_non_un_arresto(self):
        esito = await backfill.run_pulisci_contenuto(
            attivo=True, righe=[_bando(), _bando(id=2)], link=[],
            scrivi=_scrivi([], esito=False))
        self.assertEqual(esito["status"], "ok")
        self.assertEqual(esito["errori"], 2)
        self.assertEqual(esito["scritti"], 0)

    async def test_tetto_del_backfill_ferma_il_lotto(self):
        # M19: un lotto risponde SOLO ai propri tetti, e il tetto raggiunto e'
        # un dizionario, non un `SystemExit`. Qui si prova il cablaggio;
        # l'aritmetica dei tetti sta in `test_bilancio`.
        passati = {}

        def verifica(contatori, tetti, **kwargs):
            passati.update(kwargs)
            return backfill.bilancio.Esito(False, True, "tetto backfill crediti")

        scritture = []
        with patch.object(backfill.bilancio, "verifica", verifica):
            esito = await backfill.run_pulisci_contenuto(
                attivo=True, righe=[_bando()], link=[], scrivi=_scrivi(scritture))
        self.assertTrue(esito["interrotto_per_tetto"])
        self.assertEqual(esito["esaminati"], 0)
        self.assertEqual(scritture, [])
        # Il lotto si dichiara come `backfill:Lx`: e' cio' che fa rispondere
        # `bilancio.verifica` ai soli tetti del backfill.
        self.assertEqual(passati["step"], "backfill:L7")

    async def test_lotto_nomina_la_riga_di_pipeline_run(self):
        esito = await backfill.run_pulisci_contenuto(righe=[], link=[], lotto="L9")
        self.assertEqual(esito["step"], "backfill:L9")

    async def test_un_guasto_non_solleva(self):
        with patch.object(backfill, "payload_pulizia", side_effect=RuntimeError("giu'")):
            esito = await backfill.run_pulisci_contenuto(righe=[_bando()], link=[])
        self.assertEqual(esito["status"], "errore")


# --- L8: destinazione dei `processed` ---------------------------------------

def _processed(**extra):
    riga = {
        "id": 700,
        "stato_processing": "processed",
        "stato_bando": "chiuso",
        "data_scadenza": "2026-08-01",
        "fonte_ufficiale_stato": "trovata",
        "pubblicato": False,
    }
    riga.update(extra)
    return riga


class TestDestinazione(unittest.TestCase):
    def test_chiuso_da_poco_con_fonte_va_in_lavorazione(self):
        scelta, _ = backfill.destinazione(_processed(), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_LAVORAZIONE)

    def test_chiuso_da_poco_senza_fonte_si_archivia(self):
        scelta, _ = backfill.destinazione(
            _processed(fonte_ufficiale_stato="non_trovata"), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_ARCHIVIO)

    def test_oltre_novanta_giorni_si_archivia_anche_con_la_fonte(self):
        scelta, motivo = backfill.destinazione(
            _processed(data_scadenza="2026-01-10"), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_ARCHIVIO)
        self.assertIn("256 giorni", motivo)

    def test_il_confine_dei_novanta_giorni_e_incluso(self):
        confine = _processed(data_scadenza="2026-06-25")   # 90 giorni esatti
        self.assertEqual(
            backfill.destinazione(confine, oggi=OGGI)[0],
            backfill.DESTINAZIONE_LAVORAZIONE)
        fuori = _processed(data_scadenza="2026-06-24")
        self.assertEqual(
            backfill.destinazione(fuori, oggi=OGGI)[0],
            backfill.DESTINAZIONE_ARCHIVIO)

    def test_una_riga_pubblicata_non_si_tocca_mai(self):
        scelta, motivo = backfill.destinazione(
            _processed(pubblicato=True, stato_processing="completed"), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_SALTA)
        self.assertEqual(motivo, "riga pubblicata")

    def test_solo_i_processed_entrano_nel_lotto(self):
        for stato in ("completed", "enriched", "scraped", "rejected", "archiviato"):
            with self.subTest(stato=stato):
                scelta, _ = backfill.destinazione(
                    _processed(stato_processing=stato), oggi=OGGI)
                self.assertEqual(scelta, backfill.DESTINAZIONE_SALTA)

    def test_senza_scadenza_e_non_chiuso_resta_dov_e(self):
        # Archiviare perche' la data manca chiuderebbe righe vive.
        scelta, _ = backfill.destinazione(
            _processed(data_scadenza=None, stato_bando="aperto"), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_SALTA)

    def test_chiuso_senza_scadenza_e_terminale(self):
        # Non e' databile, quindi non puo' entrare nella corsia dei 90 giorni.
        scelta, motivo = backfill.destinazione(
            _processed(data_scadenza=None), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_ARCHIVIO)
        self.assertEqual(motivo, "chiuso senza scadenza")

    def test_scadenza_futura_non_e_chiusura(self):
        scelta, _ = backfill.destinazione(
            _processed(data_scadenza="2026-12-01", stato_bando="aperto"), oggi=OGGI)
        self.assertEqual(scelta, backfill.DESTINAZIONE_SALTA)


class TestRunArchiviaProcessed(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        zitto = patch.object(backfill, "_scrivi_run", MagicMock())
        zitto.start()
        self.addCleanup(zitto.stop)

    async def test_ombra_per_difetto_non_archivia(self):
        archiviati = []
        esito = await backfill.run_archivia_processed(
            righe=[_processed(data_scadenza="2026-01-10")], oggi=OGGI,
            archivia=lambda i: archiviati.append(i) or {"scritto": True})
        self.assertEqual(esito["archiviabili"], 1)
        self.assertEqual(esito["archiviati"], 0)
        self.assertEqual(archiviati, [])

    async def test_attivo_archivia_solo_il_ramo_terminale(self):
        archiviati = []
        esito = await backfill.run_archivia_processed(
            attivo=True, oggi=OGGI,
            righe=[
                _processed(id=1, data_scadenza="2026-01-10"),     # vecchio
                _processed(id=2),                                  # lavorabile
                _processed(id=3, pubblicato=True),                 # intoccabile
            ],
            archivia=lambda i: archiviati.append(i) or {"scritto": True},
        )
        self.assertEqual(archiviati, [1])
        self.assertEqual(esito["lavorabili"], 1)
        self.assertEqual(esito["ids_lavorabili"], [2])
        self.assertEqual(esito["saltati"], 1)
        self.assertEqual(esito["step"], "backfill:L8")

    async def test_dry_run_e_piu_forte_di_attivo(self):
        archiviati = []
        await backfill.run_archivia_processed(
            attivo=True, dry_run=True, oggi=OGGI,
            righe=[_processed(data_scadenza="2026-01-10")],
            archivia=lambda i: archiviati.append(i) or {"scritto": True})
        self.assertEqual(archiviati, [])

    async def test_archiviazione_degradata_e_un_salto_non_un_successo(self):
        # `archivia_bando` risponde cosi' finche' la migrazione 01 non e'
        # applicata: il valore `archiviato` non e' ancora ammesso dal CHECK.
        esito = await backfill.run_archivia_processed(
            attivo=True, oggi=OGGI, righe=[_processed(data_scadenza="2026-01-10")],
            archivia=lambda i: {"status": "ok", "saltato": "colonne_assenti",
                                "scritto": False})
        self.assertEqual(esito["archiviati"], 0)
        self.assertEqual(esito["saltati"], 1)

    async def test_un_errore_su_una_riga_non_ferma_le_altre(self):
        def archivia(bando_id):
            if bando_id == 1:
                raise RuntimeError("giu'")
            return {"scritto": True}

        esito = await backfill.run_archivia_processed(
            attivo=True, oggi=OGGI,
            righe=[_processed(id=1, data_scadenza="2026-01-10"),
                   _processed(id=2, data_scadenza="2026-01-10")],
            archivia=archivia,
        )
        self.assertEqual(esito["errori"], 1)
        self.assertEqual(esito["archiviati"], 1)

    async def test_un_guasto_non_solleva(self):
        with patch.object(backfill, "destinazione", side_effect=RuntimeError("giu'")):
            esito = await backfill.run_archivia_processed(righe=[_processed()])
        self.assertEqual(esito["status"], "errore")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
