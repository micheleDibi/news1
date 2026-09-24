# -*- coding: utf-8 -*-
"""Orchestrazione di `backend/app/bandi_pipeline.py`: gli step 5 e 7 e IndexNow.

Che cosa si verifica (§16.3.10 per l'ordine, §5 per il resolver, §6.2 per il
monitor, §7.5 per IndexNow, A15 per i codici di uscita):

  - i sette step girano **in ordine**, con il resolver fra `enrich` e `seo` e il
    monitor dopo `seo`, e i due coesistono senza pestarsi i piedi;
  - il monitor riceve `rigenerazione=` solo con `MONITOR_MODALITA=attivo`: e'
    quel parametro a decidere se uno slug entra in `slug_modificati`;
  - `submit_to_indexnow` viene chiamata **una volta sola per giro**, con gli
    URL pubblici composti dagli slug, e mai se non c'e' niente da notificare;
  - lock occupato, tetto raggiunto, modulo assente e modulo rotto restano
    **dati** nel dizionario: nessuno step alza `SystemExit`, che attraverserebbe
    `_safe_run` e ucciderebbe il sender;
  - il client HTTP viene azzerato a inizio giro e chiuso nel `finally`, anche
    quando qualcosa va storto.

Come gira senza rete e senza DB: `backend/app/bandi_pipeline.py` viene caricato
per percorso sotto un package finto, con un finto package `app` (i cinque runner
storici sono AsyncMock; `telemetria`, `blocco` e `settings` sono invece i moduli
veri, caricati dall'alias `scraper_app`). `backend/app/indexnow.py` e' quello
VERO — e' il suo filtro «solo https://edunews24.it/» a dire se gli URL composti
qui passano davvero — con `requests.post` sostituito.

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_orchestrazione_pipeline
"""
import asyncio
import contextlib
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.supporto import ALIAS, REPO, carica_modulo

BACKEND_APP = REPO / "backend" / "app"
#: Nome del package finto sotto cui si carica `bandi_pipeline`: NON "backend.app",
#: cosi' non si rischia di importare il backend vero (che vuole altre variabili
#: d'ambiente e altri pacchetti).
PKG = "backend_app_di_prova"

telemetria = carica_modulo("telemetria")
blocco = carica_modulo("blocco")
impostazioni_vere = carica_modulo("settings")
rigenera_vero = carica_modulo("rigenera")
bilancio_vero = carica_modulo("bilancio")

#: I cinque runner storici. Sono creati una volta sola perche' `bandi_pipeline`
#: ne lega le `run` come attributi di modulo al primo import: ricrearli a ogni
#: test lascerebbe la pipeline attaccata ai primi.
RUNNER = ("orchestrator", "bando_runner", "bando_preprocess_runner",
          "bando_enrich_runner", "bando_seo_runner")

APP_FINTO = types.ModuleType("app")
APP_FINTO.__path__ = []          # nessun sottomodulo si importa dal disco

MODULI_APP: dict[str, types.ModuleType] = {"app": APP_FINTO}
for _nome in RUNNER:
    _modulo = types.ModuleType(f"app.{_nome}")
    _modulo.run = AsyncMock(return_value={})
    MODULI_APP[f"app.{_nome}"] = _modulo
    setattr(APP_FINTO, _nome, _modulo)

SCARICO_FINTO = types.ModuleType("app.scarico")
SCARICO_FINTO.svuota = MagicMock()
SCARICO_FINTO.chiudi = AsyncMock()
MODULI_APP["app.scarico"] = SCARICO_FINTO
setattr(APP_FINTO, "scarico", SCARICO_FINTO)

for _nome, _vero in (("telemetria", telemetria), ("blocco", blocco),
                     ("settings", impostazioni_vere), ("rigenera", rigenera_vero),
                     ("bilancio", bilancio_vero)):
    MODULI_APP[f"app.{_nome}"] = _vero
    setattr(APP_FINTO, _nome, _vero)


@contextlib.contextmanager
def _ambiente(**extra: types.ModuleType):
    """Il finto package `app` in `sys.modules`, piu' gli `extra` del test.

    Vive solo dentro il `with`: lasciarlo registrato per tutta la suite
    nasconderebbe l'altro package `app` che sta sul `sys.path` di questa
    macchina, e un test successivo che lo importasse per sbaglio troverebbe il
    nostro senza accorgersene.
    """
    registro = dict(MODULI_APP)
    registro[f"{PKG}.logger"] = sys.modules[f"{ALIAS}.logger"]
    attributi = []
    for nome, modulo in extra.items():
        registro[f"app.{nome}"] = modulo
        attributi.append(nome)
    with contextlib.ExitStack() as pila:
        pila.enter_context(patch.dict(sys.modules, registro))
        for nome in attributi:
            pila.enter_context(
                patch.object(APP_FINTO, nome, registro[f"app.{nome}"], create=True))
        yield


def _carica() -> types.ModuleType:
    """Carica `bandi_pipeline` e `indexnow` per percorso, con `sys.path` intatto.

    `bandi_pipeline` fa `sys.path.insert(0, scraper_bandi)` a import-time: qui
    lo si lascia fare e poi si rimette a posto, altrimenti da questo momento in
    poi `import app` prenderebbe il package vero in ogni altro test.
    """
    pacchetto = types.ModuleType(PKG)
    pacchetto.__path__ = [str(BACKEND_APP)]
    percorso = list(sys.path)
    with _ambiente():
        with patch.dict(sys.modules, {PKG: pacchetto}):
            try:
                indexnow = _esegui(f"{PKG}.indexnow", BACKEND_APP / "indexnow.py")
                setattr(pacchetto, "indexnow", indexnow)
                modulo = _esegui(f"{PKG}.bandi_pipeline", BACKEND_APP / "bandi_pipeline.py")
            finally:
                sys.path[:] = percorso
    modulo.indexnow_vero = indexnow
    return modulo


def _esegui(nome: str, percorso) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(nome, percorso)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo          # il `with` esterno lo toglie a fine caricamento
    spec.loader.exec_module(modulo)
    return modulo


pipeline = _carica()


def _monitoraggio(risposta: dict | None = None, errore: Exception | None = None):
    modulo = types.ModuleType("app.monitoraggio")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {"status": "ok"},
                           side_effect=errore)
    return modulo


def _fonte_ufficiale(risposta: dict | None = None):
    modulo = types.ModuleType("app.fonte_ufficiale")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {"status": "ok"})
    return modulo


class _ConPipeline(unittest.TestCase):
    """Base: log muto, telemetria non scritta, IndexNow non inviato."""

    def setUp(self):
        for nome in RUNNER:
            MODULI_APP[f"app.{nome}"].run.reset_mock()
        SCARICO_FINTO.svuota.reset_mock()
        SCARICO_FINTO.chiudi.reset_mock()
        self.log = MagicMock()
        self.righe: list = []
        self.invii: list[list[str]] = []
        self.pila = contextlib.ExitStack()
        self.pila.enter_context(patch.object(pipeline, "logger", self.log))
        self.pila.enter_context(patch.object(
            telemetria, "scrivi_pipeline_run", side_effect=self.righe.append))
        self.indexnow = self.pila.enter_context(patch.object(
            pipeline, "submit_to_indexnow", side_effect=self.invii.append))
        # Il lock: tre esiti, come in produzione. Il predefinito e' «acquisito».
        self.lock = self.pila.enter_context(patch.object(
            blocco, "acquisisci",
            side_effect=lambda nome, prop, ttl=0, **k: blocco.Blocco(nome, prop, blocco.ACQUISITO)))
        self.rilascia = self.pila.enter_context(patch.object(blocco, "rilascia"))
        self.addCleanup(self.pila.close)

    def esegui(self, *, giro: str | None = "06:00", monitor=None, resolver=None,
               modalita: str = "ombra", chiave: str = "") -> dict:
        extra = {}
        if monitor is not None:
            extra["monitoraggio"] = monitor
        if resolver is not None:
            extra["fonte_ufficiale"] = resolver
        # `anthropic_api_key` decide i due adattatori del G7: vuota per
        # difetto, cosi' i test che non la riguardano restano quelli di prima.
        finte = types.SimpleNamespace(
            monitor_modalita=modalita, monitor_giri=("06:00", "18:00"),
            anthropic_api_key=chiave)
        with _ambiente(**extra), patch.object(pipeline, "_get_settings", return_value=finte):
            return asyncio.run(pipeline.run_bandi_pipeline(giro))


class TestOrdineDegliStep(_ConPipeline):
    def test_gli_step_nell_ordine_del_piano(self):
        stato = self.esegui(monitor=_monitoraggio(), resolver=_fonte_ufficiale())
        self.assertEqual(
            list(stato["steps"]),
            ["discover", "scrape", "preprocess", "enrich", "resolver",
             "ricontrolli", "seo", "monitor"],
        )
        self.assertEqual(stato["status"], "completed")

    def test_resolver_e_monitor_coesistono(self):
        # Step 5 e step 7 sono due moduli diversi con due lock diversi: il
        # secondo non deve ne' sostituire ne' ereditare i parametri del primo.
        monitor, resolver = _monitoraggio(), _fonte_ufficiale()
        self.esegui(monitor=monitor, resolver=resolver)
        # Due chiamate allo stesso modulo: i nuovi (step 5) e gli arretrati
        # (step 5-bis). La prima non porta `modo`, cioe' vale il default.
        self.assertEqual(resolver.run.await_count, 2)
        primo = resolver.run.await_args_list[0].kwargs
        self.assertEqual(primo, {"giro": "06:00"})
        monitor.run.assert_awaited_once()
        self.assertEqual(monitor.run.await_args.kwargs["giro"], "06:00")
        # `rigenerazione` e' del solo monitor: il resolver non la conosce.
        for chiamata in resolver.run.await_args_list:
            self.assertNotIn("rigenerazione", chiamata.kwargs)

    def test_il_monitor_viene_dopo_la_seo(self):
        # Il monitor semina l'impronta della pagina: prima della SEO
        # fotograferebbe una riga senza `contenuto`.
        ordine: list[str] = []
        monitor = _monitoraggio()

        async def segna_seo(**_kwargs):
            ordine.append("seo")
            return {}

        async def segna_monitor(**_kwargs):
            ordine.append("monitor")
            return {"status": "ok"}

        monitor.run = AsyncMock(side_effect=segna_monitor)
        with patch.object(pipeline, "_seo_run", AsyncMock(side_effect=segna_seo)):
            self.esegui(monitor=monitor)
        self.assertEqual(ordine, ["seo", "monitor"])

    def test_giro_non_previsto_salta_il_monitor(self):
        monitor = _monitoraggio()
        stato = self.esegui(giro="12:00", monitor=monitor)
        self.assertEqual(stato["steps"]["monitor"],
                         {"status": "ok", "saltato": "giro_non_previsto"})
        monitor.run.assert_not_awaited()
        self.assertEqual(stato["status"], "completed")


class TestRicontrolli(_ConPipeline):
    """Step 5-bis: la cadenza di A33 deve avere qualcuno che la legge.

    Difetto misurato il 24/09/2026 sui log di produzione: lo step 5 gira in
    modo `nuovi`, e `prossimo_controllo_at` di 1 141 righe `in_verifica` e
    507 `non_trovata` non veniva letto da nessuno. Una fonte non trovata oggi
    non si sarebbe trovata mai piu', nemmeno dopo un `domini --import` che
    rende riconoscibili centinaia di host.
    """

    def test_i_ricontrolli_partono_nei_giri_del_monitor(self):
        resolver = _fonte_ufficiale()
        stato = self.esegui(giro="06:00", resolver=resolver, monitor=_monitoraggio())
        self.assertEqual(resolver.run.await_count, 2)
        secondo = resolver.run.await_args_list[1].kwargs
        self.assertEqual(secondo["modo"], "ricontrolli")
        self.assertEqual(secondo["limit"], pipeline.RICONTROLLI_PER_GIRO)
        self.assertEqual(secondo["giro"], "06:00")
        self.assertEqual(stato["status"], "completed")

    def test_negli_altri_giri_non_partono(self):
        # Manutenzione due volte al giorno, non quattro: il traffico verso gli
        # enti e' lo stesso che il monitor sta gia' facendo in quelle ore.
        resolver = _fonte_ufficiale()
        stato = self.esegui(giro="12:00", resolver=resolver)
        self.assertEqual(resolver.run.await_count, 1,
                         "fuori dai giri del monitor gira solo lo step 5")
        self.assertEqual(stato["steps"]["ricontrolli"],
                         {"status": "ok", "saltato": "giro_non_previsto"})

    def test_i_nuovi_vengono_prima_degli_arretrati(self):
        # Se la manutenzione rubasse la finestra ai nuovi, i bandi del giorno
        # uscirebbero senza fonte: e' l'unico ordine accettabile.
        ordine: list[str] = []
        resolver = _fonte_ufficiale()

        async def segna(**kwargs):
            ordine.append(kwargs.get("modo", "nuovi"))
            return {"status": "ok"}

        resolver.run = AsyncMock(side_effect=segna)
        self.esegui(giro="06:00", resolver=resolver, monitor=_monitoraggio())
        self.assertEqual(ordine, ["nuovi", "ricontrolli"])

    def test_un_ricontrollo_che_esplode_non_ferma_il_giro(self):
        resolver = _fonte_ufficiale()
        chiamate = {"n": 0}

        async def a_volte(**_kwargs):
            chiamate["n"] += 1
            if chiamate["n"] == 2:
                raise RuntimeError("rete giu'")
            return {"status": "ok"}

        resolver.run = AsyncMock(side_effect=a_volte)
        stato = self.esegui(giro="06:00", resolver=resolver, monitor=_monitoraggio())
        self.assertEqual(stato["steps"]["ricontrolli"]["status"], "error")
        self.assertIn("monitor", stato["steps"], "il giro deve proseguire")

    def test_giro_none_vale_sempre(self):
        monitor = _monitoraggio()
        self.esegui(giro=None, monitor=monitor)
        monitor.run.assert_awaited_once()
        self.assertIsNone(monitor.run.await_args.kwargs["giro"])


class TestRigenerazione(_ConPipeline):
    def test_in_ombra_nessun_adattatore(self):
        # In ombra il monitor non riscrive niente: costruire l'adattatore
        # lascerebbe raggiungibile `scrivi_su_db` da un giro che non scrive.
        monitor = _monitoraggio()
        self.esegui(monitor=monitor, modalita="ombra")
        self.assertIsNone(monitor.run.await_args.kwargs["rigenerazione"])

    def test_in_attivo_l_adattatore_e_quello_di_rigenera(self):
        monitor = _monitoraggio()
        self.esegui(monitor=monitor, modalita="attivo")
        adattatore = monitor.run.await_args.kwargs["rigenerazione"]
        self.assertIs(adattatore.func, rigenera_vero.rigenera)
        self.assertEqual(adattatore.keywords,
                         {"attivo": True, "scrivi": rigenera_vero.scrivi_su_db})

    def test_la_pipeline_non_decide_la_modalita(self):
        # `RESOLVER_MODALITA` e `MONITOR_MODALITA` sono decisioni del `.env`
        # (ombra per difetto): la pipeline non deve poter accendere l'attivo
        # passando `attivo=True`, altrimenti il cron scriverebbe colonne
        # pubbliche senza che nessuno l'abbia chiesto per iscritto.
        monitor, resolver = _monitoraggio(), _fonte_ufficiale()
        self.esegui(monitor=monitor, resolver=resolver, modalita="attivo")
        self.assertNotIn("attivo", monitor.run.await_args.kwargs)
        self.assertNotIn("attivo", resolver.run.await_args.kwargs)

    def test_impostazioni_illeggibili_non_fermano_il_giro(self):
        monitor = _monitoraggio()
        with _ambiente(monitoraggio=monitor), patch.object(
            pipeline, "_get_settings", side_effect=RuntimeError("env assente"),
        ):
            stato = asyncio.run(pipeline.run_bandi_pipeline(None))
        self.assertIsNone(monitor.run.await_args.kwargs["rigenerazione"])
        self.assertEqual(stato["steps"]["monitor"]["status"], "ok")
        self.log.warning.assert_called()


class TestAdattatoriG7(_ConPipeline):
    """STEP 7: la seconda prova del G7 si costruisce qui (§6.2, LAVORO 3).

    Senza i due adattatori il monitor respinge ogni evento con una transizione
    di stato o una data — cioe' tutto cio' che l'intervento deve raccogliere.
    """

    def _costruttori(self, monitor):
        visti = {}

        def seconda(impostazioni, contatori):
            visti["impostazioni"] = impostazioni
            visti["contatori"] = contatori
            return "seconda-opinione"

        def collegate(impostazioni):
            return "pagine-collegate"

        monitor.seconda_opinione_da_impostazioni = seconda
        monitor.pagine_collegate_da_impostazioni = collegate
        return visti

    def test_con_la_chiave_i_due_adattatori_arrivano_al_monitor(self):
        monitor = _monitoraggio()
        visti = self._costruttori(monitor)
        self.esegui(monitor=monitor, chiave="chiave-finta")
        passati = monitor.run.await_args.kwargs
        self.assertEqual(passati["seconda_opinione"], "seconda-opinione")
        self.assertEqual(passati["pagine_collegate"], "pagine-collegate")
        # I contatori sono gli STESSI: solo cosi' il costo della seconda
        # opinione entra nel tetto giornaliero mentre il giro corre.
        self.assertIsInstance(passati["contatori"], bilancio_vero.Contatori)
        self.assertIs(passati["contatori"], visti["contatori"])

    def test_si_costruiscono_anche_in_ombra(self):
        # Al contrario della rigenerazione: l'ombra serve a misurare la
        # precisione dei gate, e un G7 spento misurerebbe un monitor che non c'e'.
        monitor = _monitoraggio()
        self._costruttori(monitor)
        self.esegui(monitor=monitor, modalita="ombra", chiave="chiave-finta")
        passati = monitor.run.await_args.kwargs
        self.assertIsNone(passati["rigenerazione"])
        self.assertEqual(passati["seconda_opinione"], "seconda-opinione")

    def test_senza_chiave_restano_none(self):
        monitor = _monitoraggio()
        self._costruttori(monitor)
        self.esegui(monitor=monitor, chiave="")
        passati = monitor.run.await_args.kwargs
        self.assertIsNone(passati["seconda_opinione"])
        self.assertIsNone(passati["pagine_collegate"])
        self.assertIsNone(passati["contatori"])

    def test_costruttori_assenti_non_fermano_il_giro(self):
        # `monitoraggio.py` una tappa indietro: il monitor gira lo stesso, con
        # il G7 spento e il riepilogo che lo dichiara.
        monitor = _monitoraggio()
        stato = self.esegui(monitor=monitor, chiave="chiave-finta")
        self.assertIsNone(monitor.run.await_args.kwargs["seconda_opinione"])
        self.assertEqual(stato["steps"]["monitor"]["status"], "ok")

    def test_un_costruttore_che_esplode_non_ferma_il_giro(self):
        monitor = _monitoraggio()
        self._costruttori(monitor)
        monitor.seconda_opinione_da_impostazioni = MagicMock(
            side_effect=RuntimeError("SDK assente"))
        stato = self.esegui(monitor=monitor, chiave="chiave-finta")
        self.assertIsNone(monitor.run.await_args.kwargs["seconda_opinione"])
        self.assertEqual(stato["steps"]["monitor"]["status"], "ok")
        self.log.warning.assert_called()


class TestIndexNow(_ConPipeline):
    def test_una_sola_chiamata_con_gli_url_pubblici(self):
        monitor = _monitoraggio({"status": "ok", "slug_modificati": ["bando-uno", "bando-due"]})
        stato = self.esegui(monitor=monitor)
        self.assertEqual(self.invii, [[
            "https://edunews24.it/bandi/bando-uno",
            "https://edunews24.it/bandi/bando-due",
        ]])
        self.assertEqual(stato["indexnow"], {"inviati": 2, "slug": 2})

    def test_niente_slug_niente_chiamata(self):
        stato = self.esegui(monitor=_monitoraggio({"status": "ok", "slug_modificati": []}))
        self.assertEqual(self.invii, [])
        self.assertEqual(stato["indexnow"], {"inviati": 0})

    def test_doppioni_notificati_una_volta_sola(self):
        monitor = _monitoraggio({"status": "ok", "slug_modificati": ["x", "x", "/x/", " x "]})
        self.esegui(monitor=monitor)
        self.assertEqual(self.invii, [["https://edunews24.it/bandi/x"]])

    def test_un_errore_di_indexnow_non_rovina_il_giro(self):
        # La notifica e' un di piu': la scrittura a DB era il lavoro, ed e' gia'
        # avvenuta quando si arriva qui.
        monitor = _monitoraggio({"status": "ok", "slug_modificati": ["uno"]})
        self.indexnow.side_effect = RuntimeError("rete giu'")
        stato = self.esegui(monitor=monitor)
        self.assertEqual(stato["status"], "completed")
        self.assertEqual(stato["indexnow"]["inviati"], 0)
        self.log.warning.assert_called()

    def test_lock_occupato_non_notifica(self):
        self.lock.side_effect = lambda nome, prop, ttl=0, **k: blocco.Blocco(
            nome, prop, blocco.OCCUPATO)
        stato = self.esegui(monitor=_monitoraggio({"slug_modificati": ["uno"]}))
        self.assertEqual(stato["status"], "saltato")
        self.assertTrue(stato["saltato_per_lock"])
        self.assertEqual(self.invii, [])
        MODULI_APP["app.orchestrator"].run.assert_not_awaited()

    def test_gli_url_composti_passano_il_filtro_del_modulo_vero(self):
        # `indexnow.submit_to_indexnow` scarta tutto cio' che non comincia con
        # `https://edunews24.it/`: se il percorso qui fosse sbagliato, il lotto
        # verrebbe buttato in silenzio e resterebbe solo un warning.
        vero = pipeline.indexnow_vero
        posta = MagicMock(return_value=types.SimpleNamespace(status_code=200))
        monitor = _monitoraggio({"status": "ok", "slug_modificati": ["bando-uno"]})
        with patch.object(vero, "requests", MagicMock(post=posta)), \
                patch.object(vero, "logger", MagicMock()), \
                patch.dict("os.environ", {"INDEXNOW_API_KEY": "chiave-di-prova"}), \
                patch.object(pipeline, "submit_to_indexnow", vero.submit_to_indexnow):
            self.esegui(monitor=monitor)
        posta.assert_called_once()
        self.assertEqual(
            posta.call_args.kwargs["json"]["urlList"],
            ["https://edunews24.it/bandi/bando-uno"],
        )


class TestEsitiCheRestanoDati(_ConPipeline):
    def test_tetto_raggiunto_non_e_un_errore_ma_si_vede_nella_riga(self):
        # Exit code 4 esiste solo nella CLI (A15): qui il tetto e' un dato, e il
        # giro resta `completed`. Ma la riga di `pipeline_run` deve dirlo,
        # altrimenti `salute` non puo' accorgersi di due giri a tetto di fila.
        monitor = _monitoraggio({"status": "ok", "interrotto_per_tetto": True,
                                 "motivo": "tetto fetch"})
        stato = self.esegui(monitor=monitor)
        self.assertEqual(stato["status"], "completed")
        self.assertNotIn("saltato_per_lock", stato["steps"]["monitor"])
        riga = self.righe[-1]
        self.assertTrue(riga.interrotto_per_tetto)
        self.assertEqual(riga.esito, telemetria.ESITO_INTERROTTO)

    def test_crediti_e_dollari_sommati_su_tutti_gli_step(self):
        # Il resolver gira due volte (nuovi e ricontrolli) e il monitor una.
        # La spesa degli arretrati e' spesa come le altre: se non entrasse nel
        # totale, `salute` misurerebbe un consumo piu' basso del vero e i tetti
        # mensili scatterebbero tardi.
        stato = self.esegui(
            resolver=_fonte_ufficiale({"status": "ok", "crediti": 12, "costo_usd": 0.25}),
            monitor=_monitoraggio({"status": "ok", "crediti": 30, "costo_usd": 1.5}),
        )
        riga = self.righe[-1]
        self.assertEqual(riga.crediti, 12 + 12 + 30)
        self.assertAlmostEqual(riga.costo_usd, 0.25 + 0.25 + 1.5)
        self.assertEqual(stato["status"], "completed")

    def test_slug_modificati_finiscono_anche_nella_riga(self):
        self.esegui(monitor=_monitoraggio({"status": "ok", "slug_modificati": ["a", "b"]}))
        self.assertEqual(self.righe[-1].slug_modificati, ("a", "b"))

    def test_modulo_assente_e_un_esito_buono(self):
        # Nessun `app.monitoraggio` registrato: e' la tappa successiva del piano.
        stato = self.esegui(monitor=None, resolver=None)
        for nome in ("resolver", "monitor"):
            with self.subTest(step=nome):
                self.assertEqual(stato["steps"][nome]["status"], "ok")
                self.assertEqual(stato["steps"][nome]["saltato"], pipeline.MODULO_ASSENTE)
        self.assertEqual(stato["status"], "completed")

    def test_modulo_senza_run_e_un_guasto(self):
        rotto = types.ModuleType("app.monitoraggio")      # niente `run`
        stato = self.esegui(monitor=rotto)
        self.assertEqual(stato["steps"]["monitor"]["status"], "error")
        self.assertEqual(stato["status"], "partial")
        self.assertEqual(self.righe[-1].esito, telemetria.ESITO_ERRORE)

    def test_uno_step_che_solleva_non_ferma_gli_altri(self):
        monitor = _monitoraggio(errore=RuntimeError("boom"))
        stato = self.esegui(monitor=monitor, resolver=_fonte_ufficiale())
        self.assertEqual(stato["steps"]["monitor"]["status"], "error")
        self.assertEqual(stato["steps"]["seo"]["status"], "ok")
        self.assertEqual(stato["status"], "partial")

    def test_systemexit_attraversa_ma_il_lock_viene_rilasciato(self):
        # `_safe_run` cattura `Exception`, non `BaseException`: per questo
        # nessuno step v11 alza mai `SystemExit` (A15). Se succedesse, il
        # sender morirebbe — ma il `finally` chiude comunque lo scarico e
        # rilascia il lock, che e' l'unica cosa che questo file puo' garantire.
        monitor = _monitoraggio(errore=SystemExit(3))
        with self.assertRaises(SystemExit):
            self.esegui(monitor=monitor)
        self.rilascia.assert_called_once()
        SCARICO_FINTO.chiudi.assert_awaited_once()


class TestScarico(_ConPipeline):
    def test_azzerato_a_inizio_giro_e_chiuso_alla_fine(self):
        self.esegui(monitor=_monitoraggio())
        SCARICO_FINTO.svuota.assert_called_once()
        SCARICO_FINTO.chiudi.assert_awaited_once()

    def test_chiusura_fallita_non_rompe_il_giro(self):
        SCARICO_FINTO.chiudi.side_effect = RuntimeError("client gia' morto")
        try:
            stato = self.esegui(monitor=_monitoraggio())
        finally:
            SCARICO_FINTO.chiudi.side_effect = None
        self.assertEqual(stato["status"], "completed")
        self.log.warning.assert_called()


class TestFunzioniPure(unittest.TestCase):
    def test_slug_da_notificare_ignora_contatori_non_dizionario(self):
        stato = {"steps": {
            "a": {"counters": None},
            "b": {"counters": {"slug_modificati": ["uno"]}},
            "c": "non un passo",
        }}
        self.assertEqual(pipeline._slug_da_notificare(stato), ["uno"])

    def test_consumo_ignora_i_booleani(self):
        # `True` non vale 1: un contatore booleano finito qui per sbaglio non
        # deve diventare un credito speso.
        stato = {"steps": {"a": {"counters": {"crediti": True, "costo_usd": "2"}},
                           "b": {"counters": {"crediti": 5, "costo_usd": 0.5}}}}
        self.assertEqual(pipeline._consumo(stato), (5, 0.5))

    def test_interrotto_per_tetto_guarda_tutti_gli_step(self):
        self.assertFalse(pipeline._interrotto_per_tetto({"steps": {"a": {"counters": {}}}}))
        self.assertTrue(pipeline._interrotto_per_tetto(
            {"steps": {"a": {"counters": {}}, "b": {"counters": {"interrotto_per_tetto": True}}}}))


if __name__ == "__main__":
    unittest.main()
