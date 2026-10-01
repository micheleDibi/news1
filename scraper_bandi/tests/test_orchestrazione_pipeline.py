# -*- coding: utf-8 -*-
"""Orchestrazione di `backend/app/bandi_pipeline.py`: l'ordine del giro e IndexNow.

Che cosa si verifica (contratto `bandi-giro-3` §2 per l'ordine, §5 per il
resolver, §6.2 per il monitor, §7.5 per IndexNow, A15 per i codici di uscita):

  - i quindici step girano **in ordine** (§2 del giro 3), con tre passate del
    resolver (`precoce`, `nuovi`, `ricontrolli` senza `limit`), la
    manutenzione solo nei giri di `MONITOR_GIRI` e mai al giro di avvio;
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

#: Le chiavi di `state["steps"]` nell'ordine del giro 3 (contratto §2), in un
#: giro delle 06 con l'import dei domini gia' fatto nel mese.
ORDINE_DEL_GIRO_3 = [
    "discover", "scrape", "domini", "resolver_precoce", "preprocess", "enrich",
    "resolver", "ricontrolli", "verifica_stato_ingresso", "seo", "link_verifica",
    "rielaborazione", "monitor", "verifica_stato", "gemelli",
]
#: I passi della manutenzione (8, 11-15): solo nei giri di MONITOR_GIRI.
MANUTENZIONE = ("ricontrolli", "link_verifica", "rielaborazione", "monitor",
                "verifica_stato", "gemelli")


def _monitoraggio(risposta: dict | None = None, errore: Exception | None = None):
    modulo = types.ModuleType("app.monitoraggio")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {"status": "ok"},
                           side_effect=errore)
    return modulo


def _fonte_ufficiale(risposta: dict | None = None):
    modulo = types.ModuleType("app.fonte_ufficiale")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {"status": "ok"})
    # Il passo 11 (giro 3): stesso modulo, ingresso diverso. Risposta propria,
    # cosi' i test sui crediti del resolver contano solo le sue tre passate.
    modulo.run_link_verifica = AsyncMock(return_value={"status": "ok"})
    return modulo


def _modi(resolver) -> list[str]:
    """I `modo` delle chiamate a `fonte_ufficiale.run`, nell'ordine."""
    return [c.kwargs.get("modo") for c in resolver.run.await_args_list]


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
               modalita: str = "ombra", chiave: str = "", verifica: str | None = None,
               giri: tuple[str, ...] = ("06:00", "18:00"), **moduli) -> dict:
        extra = dict(moduli)
        if monitor is not None:
            extra["monitoraggio"] = monitor
        if resolver is not None:
            extra["fonte_ufficiale"] = resolver
        # `anthropic_api_key` decide i due adattatori del G7: vuota per
        # difetto, cosi' i test che non la riguardano restano quelli di prima.
        # `giri`: due ore e non le quattro del default, cosi' i test vedono
        # anche un giro (12:00) in cui la manutenzione non parte.
        finte = types.SimpleNamespace(
            monitor_modalita=modalita, monitor_giri=giri,
            anthropic_api_key=chiave)
        if verifica is not None:
            finte.verifica_stato_modalita = verifica
        with _ambiente(**extra), patch.object(pipeline, "_get_settings", return_value=finte):
            return asyncio.run(pipeline.run_bandi_pipeline(giro))


class TestOrdineDegliStep(_ConPipeline):
    def test_gli_step_nell_ordine_del_piano(self):
        stato = self.esegui(monitor=_monitoraggio(), resolver=_fonte_ufficiale())
        self.assertEqual(list(stato["steps"]), ORDINE_DEL_GIRO_3)
        self.assertEqual(stato["status"], "completed")

    def test_resolver_e_monitor_coesistono(self):
        # Resolver e monitor sono due moduli diversi con due lock diversi: il
        # secondo non deve ne' sostituire ne' ereditare i parametri del primo.
        monitor, resolver = _monitoraggio(), _fonte_ufficiale()
        self.esegui(monitor=monitor, resolver=resolver)
        # Tre chiamate allo stesso modulo (giro 3, §2): precoce (step 4),
        # nuovi (step 7) e ricontrolli (step 8), ciascuna con il suo `modo`.
        self.assertEqual(resolver.run.await_count, 3)
        self.assertEqual([c.kwargs for c in resolver.run.await_args_list[:2]],
                         [{"giro": "06:00", "modo": "precoce"},
                          {"giro": "06:00", "modo": "nuovi"}])
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

    def test_i_ricontrolli_partono_nei_giri_del_monitor_senza_limit(self):
        # Giro 3 (§1 e §7): niente lotti. Il tetto di 60 righe per giro e'
        # sparito; resta solo il tempo, che il resolver gestisce da se'.
        resolver = _fonte_ufficiale()
        stato = self.esegui(giro="06:00", resolver=resolver, monitor=_monitoraggio())
        self.assertEqual(resolver.run.await_count, 3)
        terzo = resolver.run.await_args_list[2].kwargs
        self.assertEqual(terzo, {"giro": "06:00", "modo": "ricontrolli"})
        self.assertNotIn("limit", terzo)
        self.assertFalse(hasattr(pipeline, "RICONTROLLI_PER_GIRO"))
        self.assertEqual(stato["status"], "completed")

    def test_negli_altri_giri_non_partono(self):
        # Manutenzione due volte al giorno, non quattro: il traffico verso gli
        # enti e' lo stesso che il monitor sta gia' facendo in quelle ore.
        resolver = _fonte_ufficiale()
        stato = self.esegui(giro="12:00", resolver=resolver)
        self.assertEqual(_modi(resolver), ["precoce", "nuovi"],
                         "fuori dai giri del monitor girano solo le due passate d'ingresso")
        self.assertEqual(stato["steps"]["ricontrolli"],
                         {"status": "ok", "saltato": "giro_non_previsto"})

    def test_i_nuovi_vengono_prima_degli_arretrati(self):
        # Se la manutenzione rubasse la finestra ai nuovi, i bandi del giorno
        # uscirebbero senza fonte: e' l'unico ordine accettabile.
        ordine: list[str] = []
        resolver = _fonte_ufficiale()

        async def segna(**kwargs):
            ordine.append(kwargs["modo"])
            return {"status": "ok"}

        resolver.run = AsyncMock(side_effect=segna)
        self.esegui(giro="06:00", resolver=resolver, monitor=_monitoraggio())
        self.assertEqual(ordine, ["precoce", "nuovi", "ricontrolli"])

    def test_un_ricontrollo_che_esplode_non_ferma_il_giro(self):
        resolver = _fonte_ufficiale()
        chiamate = {"n": 0}

        async def a_volte(**_kwargs):
            chiamate["n"] += 1
            if chiamate["n"] == 3:
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
        # Il resolver gira tre volte (precoce, nuovi e ricontrolli) e il
        # monitor una.
        # La spesa degli arretrati e' spesa come le altre: se non entrasse nel
        # totale, `salute` misurerebbe un consumo piu' basso del vero e i tetti
        # mensili scatterebbero tardi.
        stato = self.esegui(
            resolver=_fonte_ufficiale({"status": "ok", "crediti": 12, "costo_usd": 0.25}),
            monitor=_monitoraggio({"status": "ok", "crediti": 30, "costo_usd": 1.5}),
        )
        riga = self.righe[-1]
        self.assertEqual(riga.crediti, 12 * 3 + 30)
        self.assertAlmostEqual(riga.costo_usd, 0.25 * 3 + 1.5)
        self.assertEqual(stato["status"], "completed")

    def test_slug_modificati_finiscono_anche_nella_riga(self):
        self.esegui(monitor=_monitoraggio({"status": "ok", "slug_modificati": ["a", "b"]}))
        self.assertEqual(self.righe[-1].slug_modificati, ("a", "b"))

    def test_modulo_assente_e_un_esito_buono(self):
        # Nessun `app.monitoraggio` registrato: e' la tappa successiva del piano.
        stato = self.esegui(monitor=None, resolver=None)
        for nome in ("resolver_precoce", "resolver", "ricontrolli", "link_verifica",
                     "rielaborazione", "monitor"):
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

    def test_la_riga_del_giro_non_copia_i_cambi_della_rielaborazione(self):
        # Revisione #146: l'elenco dei cambi sta nella riga del passo.
        cambi = [{"bando_id": 7, "dimensione": "regioni", "prima": [12], "dopo": [11]}]
        stato = {"steps": {"rielaborazione": {"status": "ok", "counters": {
            "status": "ok", "rielaborati": 1, "junction_cambiate": 1, "cambi": cambi,
            "slug_modificati": ["contributi"], "copertura": {"candidati": 1}}}}}
        riga = pipeline._contatori_della_riga(stato)
        self.assertEqual(riga["rielaborazione"], {
            "status": "ok", "rielaborati": 1, "junction_cambiate": 1,
            "slug_modificati": ["contributi"], "copertura": {"candidati": 1}})
        # Lo stato del giro resta intero: IndexNow legge gli slug da li'.
        self.assertEqual(stato["steps"]["rielaborazione"]["counters"]["cambi"], cambi)
        self.assertEqual(pipeline._slug_da_notificare(stato), ["contributi"])

    def test_interrotto_per_tetto_guarda_tutti_gli_step(self):
        self.assertFalse(pipeline._interrotto_per_tetto({"steps": {"a": {"counters": {}}}}))
        self.assertTrue(pipeline._interrotto_per_tetto(
            {"steps": {"a": {"counters": {}}, "b": {"counters": {"interrotto_per_tetto": True}}}}))



# --- giro 2 (contratto `bandi-giro-2` §11 e §19.10) ---------------------------

def _verifica_stato(risposta: dict | None = None):
    modulo = types.ModuleType("app.verifica_stato")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {
        "status": "ok", "counters": {}, "slug_modificati": [], "ids_da_rigenerare": []})
    return modulo


def _gemelli(risposta: dict | None = None):
    modulo = types.ModuleType("app.gemelli")
    # Sincrona, come quella vera: `_safe_run` deve saperla chiamare.
    modulo.esegui_passo = MagicMock(return_value=risposta if risposta is not None else {
        "status": "ok", "fusioni": []})
    return modulo


class TestPassiDelGiro2(_ConPipeline):
    def _fasi(self, verifica):
        return [c.kwargs.get("fase") for c in verifica.run.await_args_list]

    def test_verifica_stato_nei_giri_del_monitor_e_ingresso_in_ogni_giro(self):
        for giro, fasi in (("06:00", ["ingresso", "controlli"]), ("18:00", ["ingresso", "controlli"]),
                           ("12:00", ["ingresso"]), ("boot", ["ingresso"]), (None, ["ingresso", "controlli"])):
            with self.subTest(giro=giro):
                verifica = _verifica_stato()
                stato = self.esegui(giro=giro, verifica_stato=verifica, monitor=_monitoraggio())
                self.assertEqual(self._fasi(verifica), fasi)
                if "controlli" not in fasi:
                    self.assertEqual(stato["steps"]["verifica_stato"]["saltato"], "giro_non_previsto")

    def test_ordine_ingresso_prima_della_seo_controlli_dopo_il_monitor(self):
        ordine: list[str] = []
        verifica, monitor = _verifica_stato(), _monitoraggio()

        async def passo(**kwargs):
            ordine.append(f"verifica:{kwargs['fase']}")
            return {"status": "ok", "counters": {}}

        async def segna_monitor(**_kwargs):
            ordine.append("monitor")
            return {"status": "ok"}

        async def segna_seo(**_kwargs):
            ordine.append("seo")
            return {}

        verifica.run = AsyncMock(side_effect=passo)
        monitor.run = AsyncMock(side_effect=segna_monitor)
        with patch.object(pipeline, "_seo_run", AsyncMock(side_effect=segna_seo)):
            self.esegui(verifica_stato=verifica, monitor=monitor)
        self.assertEqual(ordine, ["verifica:ingresso", "seo", "monitor", "verifica:controlli"])

    def test_la_fase_controlli_riceve_l_adattatore_della_prosa(self):
        verifica = _verifica_stato()
        adattatore = object()
        with patch.object(pipeline, "_rigenerazione_di_produzione", return_value=adattatore):
            self.esegui(verifica_stato=verifica)
        controlli = next(c for c in verifica.run.await_args_list if c.kwargs["fase"] == "controlli")
        self.assertIs(controlli.kwargs["rigenerazione"], adattatore)
        ingresso = next(c for c in verifica.run.await_args_list if c.kwargs["fase"] == "ingresso")
        self.assertNotIn("rigenerazione", ingresso.kwargs)

    def test_con_la_verifica_attiva_l_adattatore_c_e_anche_a_monitor_in_ombra(self):
        # Revisione del 01/10: prima arrivava solo con il monitor attivo.
        verifica, monitor = _verifica_stato(), _monitoraggio()
        self.esegui(verifica_stato=verifica, monitor=monitor, modalita="ombra", verifica="attivo")
        controlli = next(c for c in verifica.run.await_args_list if c.kwargs["fase"] == "controlli")
        adattatore = controlli.kwargs["rigenerazione"]
        self.assertIs(adattatore.func, rigenera_vero.rigenera)
        self.assertEqual(adattatore.keywords, {"attivo": True, "scrivi": rigenera_vero.scrivi_su_db})
        # Al monitor in ombra senza tipi attivi no: lui non scrive.
        self.assertIsNone(monitor.run.await_args.kwargs["rigenerazione"])

    def test_verifica_in_ombra_e_monitor_in_ombra_nessun_adattatore(self):
        verifica = _verifica_stato()
        self.esegui(verifica_stato=verifica, modalita="ombra", verifica="ombra")
        controlli = next(c for c in verifica.run.await_args_list if c.kwargs["fase"] == "controlli")
        self.assertIsNone(controlli.kwargs["rigenerazione"])

    def test_la_riga_pipeline_porta_solo_esito_e_contatori_della_verifica(self):
        verifica = _verifica_stato({
            "status": "ok", "counters": {"esaminati": 4, "slug_modificati": ["bando-chiuso"]},
            "slug_modificati": ["bando-chiuso"], "ids_da_rigenerare": [7, 8],
            "proposte": [{"bando_id": 7, "stato_proposto": "chiuso"}]})
        self.esegui(verifica_stato=verifica)
        riga = self.righe[-1]
        attesi = {"status": "ok", "counters": {"esaminati": 4, "slug_modificati": ["bando-chiuso"]}}
        self.assertEqual(riga.contatori["verifica_stato"], attesi)
        self.assertEqual(riga.contatori["verifica_stato_ingresso"], attesi)
        # Gli slug restano quelli del giro: IndexNow e la colonna della riga.
        self.assertEqual(riga.slug_modificati, ("bando-chiuso",))
        self.assertEqual(self.invii, [["https://edunews24.it/bandi/bando-chiuso"]])

    def test_gli_slug_della_verifica_vanno_a_indexnow(self):
        verifica = _verifica_stato({"status": "ok", "counters": {},
                                    "slug_modificati": ["bando-chiuso"], "ids_da_rigenerare": [7]})
        self.esegui(verifica_stato=verifica)
        self.assertEqual(self.invii, [["https://edunews24.it/bandi/bando-chiuso"]])

    def test_un_errore_interno_del_passo_e_un_passo_non_ok(self):
        verifica = _verifica_stato({"status": "errore", "counters": {}})
        stato = self.esegui(verifica_stato=verifica)
        self.assertEqual(stato["steps"]["verifica_stato"]["status"], "error")
        self.assertEqual(stato["status"], "partial")
        riga = self.righe[-1]
        self.assertIn("verifica_stato", riga.contatori["passi_non_ok"])

    def test_gemelli_nei_giri_del_monitor_e_funzione_sincrona(self):
        # Giro 3 (§2, §11): non piu' solo alle 06, ma a ogni giro di MONITOR_GIRI.
        for giro in ("06:00", "18:00"):
            with self.subTest(giro=giro):
                gemelli = _gemelli()
                stato = self.esegui(giro=giro, gemelli=gemelli)
                gemelli.esegui_passo.assert_called_once_with(giro=giro)
                self.assertEqual(stato["steps"]["gemelli"]["status"], "ok")
        for giro in ("12:00", "boot"):
            with self.subTest(giro=giro):
                gemelli = _gemelli()
                stato = self.esegui(giro=giro, gemelli=gemelli)
                gemelli.esegui_passo.assert_not_called()
                self.assertEqual(stato["steps"]["gemelli"],
                                 {"status": "ok", "saltato": "giro_non_previsto"})

    def test_domini_alle_06_se_dovuto(self):
        fonte = _fonte_ufficiale()
        fonte.run_domini_import = AsyncMock(return_value={"status": "ok", "indicepa_esito": "ombra"})
        with patch.object(pipeline, "_import_domini_dovuto", return_value=True):
            stato = self.esegui(giro="06:00", resolver=fonte)
        fonte.run_domini_import.assert_awaited_once_with(giro="06:00", scarica_enti=True)
        self.assertEqual(stato["steps"]["domini"]["status"], "ok")
        fonte.run_domini_import.reset_mock()
        with patch.object(pipeline, "_import_domini_dovuto", return_value=False):
            stato = self.esegui(giro="06:00", resolver=fonte)
        fonte.run_domini_import.assert_not_awaited()
        self.assertEqual(stato["steps"]["domini"]["saltato"], "gia_fatto_nel_mese")
        with patch.object(pipeline, "_import_domini_dovuto", return_value=True):
            stato = self.esegui(giro="12:00", resolver=fonte)
        fonte.run_domini_import.assert_not_awaited()
        self.assertNotIn("domini", stato["steps"])

    def test_la_tabella_dei_domini_si_azzera_a_inizio_giro(self):
        ordine: list[str] = []
        fonte = _fonte_ufficiale()
        fonte.azzera_tabella_corrente = MagicMock(side_effect=lambda: ordine.append("azzera"))

        async def discover(**_kwargs):
            ordine.append("discover")
            return {}

        with patch.object(pipeline, "_discover_run", AsyncMock(side_effect=discover)):
            self.esegui(resolver=fonte)
        self.assertEqual(ordine[:2], ["azzera", "discover"])

    def test_domini_dovuto(self):
        from datetime import datetime, timedelta, timezone
        roma = timezone(timedelta(hours=2))
        adesso = datetime(2026, 10, 1, 6, 0, tzinfo=roma)
        del_mese = {"avviato_at": "2026-10-01T04:00:30Z", "esito": "ombra"}
        del_mese_prima = {"avviato_at": "2026-09-30T21:00:00Z", "esito": "ok"}
        self.assertTrue(pipeline.domini_dovuto(adesso, [], False))
        # Ombra: 'ombra' conta come fatto; attivo: solo 'ok'.
        self.assertFalse(pipeline.domini_dovuto(adesso, [del_mese], False))
        self.assertTrue(pipeline.domini_dovuto(adesso, [del_mese], True))
        # 23:00 del 30/09 a Roma e' ancora settembre: il mese di ottobre e' da fare.
        self.assertTrue(pipeline.domini_dovuto(adesso, [del_mese_prima], True))
        # Un import fallito si ritenta.
        self.assertTrue(pipeline.domini_dovuto(
            adesso, [{"avviato_at": "2026-10-01T04:00:00Z", "esito": "download_fallito"}], False))
        self.assertTrue(pipeline.domini_dovuto(adesso, [{"avviato_at": "boh", "esito": "ok"}], True))

    def test_import_dovuto_senza_db_non_importa(self):
        # Nel package finto non c'e' `app.db`: la lettura fallisce e non si importa.
        with _ambiente():
            self.assertFalse(pipeline._import_domini_dovuto())


# --- giro 3 (contratto `bandi-giro-3` §2) ------------------------------------

def _rielabora_fonte(risposta: dict | None = None):
    modulo = types.ModuleType("app.rielabora_fonte")
    modulo.run = AsyncMock(return_value=risposta if risposta is not None else {"status": "ok"})
    return modulo


class TestOrdineDelGiro3(_ConPipeline):
    def _tutti(self):
        return {"resolver": _fonte_ufficiale(), "monitor": _monitoraggio(),
                "verifica_stato": _verifica_stato(), "gemelli": _gemelli(),
                "rielabora_fonte": _rielabora_fonte()}

    def test_ordine_dei_passi_che_partono_davvero(self):
        # Non solo le chiavi: l'ordine in cui i moduli vengono CHIAMATI.
        ordine: list[str] = []
        moduli = self._tutti()

        def segna(nome, risposta=None):
            async def _passo(**kwargs):
                ordine.append(kwargs.get("modo") and f"{nome}:{kwargs['modo']}"
                              or (kwargs.get("fase") and f"{nome}:{kwargs['fase']}") or nome)
                return risposta if risposta is not None else {"status": "ok"}
            return AsyncMock(side_effect=_passo)

        fonte = moduli["resolver"]
        fonte.run = segna("resolver")
        fonte.run_link_verifica = segna("link_verifica")
        fonte.run_domini_import = segna("domini")
        moduli["rielabora_fonte"].run = segna("rielaborazione")
        moduli["monitor"].run = segna("monitor")
        moduli["verifica_stato"].run = segna("verifica", {"status": "ok", "counters": {}})
        moduli["gemelli"].esegui_passo = MagicMock(
            side_effect=lambda **k: ordine.append("gemelli") or {"status": "ok"})
        storici = {nome: segna(nome, {}) for nome in
                   ("discover", "scrape", "preprocess", "enrich", "seo")}
        with patch.object(pipeline, "_import_domini_dovuto", return_value=True), \
                patch.object(pipeline, "_discover_run", storici["discover"]), \
                patch.object(pipeline, "_scrape_run", storici["scrape"]), \
                patch.object(pipeline, "_preprocess_run", storici["preprocess"]), \
                patch.object(pipeline, "_enrich_run", storici["enrich"]), \
                patch.object(pipeline, "_seo_run", storici["seo"]):
            stato = self.esegui(giro="06:00", **moduli)
        self.assertEqual(ordine, [
            "discover", "scrape", "domini", "resolver:precoce", "preprocess", "enrich",
            "resolver:nuovi", "resolver:ricontrolli", "verifica:ingresso", "seo",
            "link_verifica", "rielaborazione", "monitor", "verifica:controlli", "gemelli",
        ])
        self.assertEqual(list(stato["steps"]), ORDINE_DEL_GIRO_3)
        self.assertEqual(stato["status"], "completed")

    def test_i_passi_nuovi_ricevono_il_giro(self):
        moduli = self._tutti()
        self.esegui(giro="18:00", **moduli)
        moduli["resolver"].run_link_verifica.assert_awaited_once_with(giro="18:00")
        moduli["rielabora_fonte"].run.assert_awaited_once_with(giro="18:00")

    def test_rielaborazione_assente_vale_saltata(self):
        # `app.rielabora_fonte` arriva con B4: fino ad allora il passo 12 e'
        # «saltato, tutto bene», non un guasto del giro.
        stato = self.esegui(giro="06:00", resolver=_fonte_ufficiale(), monitor=_monitoraggio())
        self.assertEqual(stato["steps"]["rielaborazione"],
                         {"status": "ok", "saltato": pipeline.MODULO_ASSENTE,
                          "modulo": "app.rielabora_fonte"})
        self.assertEqual(stato["status"], "completed")

    def test_boot_senza_manutenzione(self):
        moduli = self._tutti()
        stato = self.esegui(giro="boot", **moduli)
        self.assertEqual(_modi(moduli["resolver"]), ["precoce", "nuovi"])
        for nome in MANUTENZIONE:
            with self.subTest(passo=nome):
                self.assertEqual(stato["steps"][nome],
                                 {"status": "ok", "saltato": "giro_non_previsto"})
        moduli["resolver"].run_link_verifica.assert_not_awaited()
        moduli["rielabora_fonte"].run.assert_not_awaited()
        moduli["monitor"].run.assert_not_awaited()
        moduli["gemelli"].esegui_passo.assert_not_called()
        self.assertNotIn("domini", stato["steps"])
        self.assertEqual(stato["status"], "completed")

    def test_con_i_giri_di_default_la_manutenzione_gira_a_ogni_ora(self):
        # MONITOR_GIRI vale per difetto le quattro ore dello scheduler (§2).
        self.assertEqual(impostazioni_vere._GIRI_DEFAULT, impostazioni_vere.GIRI_SCHEDULER)
        for giro in impostazioni_vere.GIRI_SCHEDULER:
            with self.subTest(giro=giro):
                moduli = self._tutti()
                stato = self.esegui(giro=giro, giri=impostazioni_vere._GIRI_DEFAULT, **moduli)
                self.assertEqual(_modi(moduli["resolver"]), ["precoce", "nuovi", "ricontrolli"])
                for nome in MANUTENZIONE:
                    self.assertNotIn("saltato", stato["steps"][nome], nome)
                moduli["gemelli"].esegui_passo.assert_called_once_with(giro=giro)

    def test_la_cli_fa_tutto(self):
        moduli = self._tutti()
        stato = self.esegui(giro=None, **moduli)
        self.assertEqual(_modi(moduli["resolver"]), ["precoce", "nuovi", "ricontrolli"])
        for nome in MANUTENZIONE:
            self.assertNotIn("saltato", stato["steps"][nome], nome)

    def test_un_resolver_precoce_rotto_non_ferma_l_ingresso(self):
        fonte = _fonte_ufficiale()

        async def precoce_rotto(**kwargs):
            if kwargs["modo"] == "precoce":
                raise RuntimeError("rete giu'")
            return {"status": "ok"}

        fonte.run = AsyncMock(side_effect=precoce_rotto)
        stato = self.esegui(giro="12:00", resolver=fonte)
        self.assertEqual(stato["steps"]["resolver_precoce"]["status"], "error")
        self.assertEqual(stato["steps"]["resolver"]["status"], "ok")
        MODULI_APP["app.bando_preprocess_runner"].run.assert_awaited_once()
        self.assertEqual(stato["status"], "partial")

    def test_db_conosce_gli_stessi_passi(self):
        # `db.CONTATORI_PIPELINE` legge la copertura di questi passi: un passo
        # aggiunto qui e non li' resterebbe fuori da `salute` in silenzio.
        self.assertEqual(list(carica_modulo("db").PASSI_DEL_GIRO), ORDINE_DEL_GIRO_3)

    def test_la_riga_del_giro_conserva_la_copertura(self):
        copertura = {"candidati": 12, "fatti": 10, "rimasti": 2, "motivo_rimasti": "tempo"}
        verifica = _verifica_stato({
            "status": "ok", "counters": {"esaminati": 4}, "copertura": copertura,
            "proposte": [{"bando_id": 7}], "ids_da_rigenerare": [7]})
        monitor = _monitoraggio({"status": "ok", "copertura": copertura})
        self.esegui(verifica_stato=verifica, monitor=monitor)
        riga = self.righe[-1]
        self.assertEqual(riga.contatori["verifica_stato"],
                         {"status": "ok", "counters": {"esaminati": 4}, "copertura": copertura})
        self.assertEqual(riga.contatori["monitor"]["copertura"], copertura)

    def test_la_seo_riceve_il_giro(self):
        # Giro 3 (§4, M3): la riga di spesa della SEO porta il giro.
        self.esegui(giro="18:00")
        MODULI_APP["app.bando_seo_runner"].run.assert_awaited_once_with(giro="18:00")

    def test_lucchetto_del_giro_di_sei_ore(self):
        self.assertEqual(pipeline.LOCK_TTL_S, 6 * 3600)
        self.assertEqual(self.esegui(giro="12:00")["lock"], blocco.ACQUISITO)
        self.assertEqual(self.lock.call_args.args[2], 6 * 3600)


class TestImportDominiSuDominiModalita(unittest.TestCase):
    """`_import_domini_dovuto` legge DOMINI_MODALITA (giro 3, §3 e §12), non
    piu' VERIFICA_STATO_MODALITA: in attivo conta come fatto solo un 'ok'."""

    def _dovuto(self, *, domini: str, verifica: str) -> bool:
        from datetime import datetime, timedelta, timezone
        roma = timezone(timedelta(hours=2))
        righe = [{"avviato_at": "2026-10-01T04:00:30Z", "esito": "ombra"}]

        class _Query:
            def __getattr__(self, _nome):
                return lambda *a, **k: self

            def execute(self):
                return types.SimpleNamespace(data=righe)

        db_finto = types.ModuleType("app.db")
        db_finto.get_supabase = lambda: types.SimpleNamespace(table=lambda _n: _Query())
        stato_bando = types.ModuleType("app.stato_bando")
        stato_bando.adesso_roma = lambda: datetime(2026, 10, 1, 12, 0, tzinfo=roma)
        finte = types.SimpleNamespace(domini_modalita=domini, verifica_stato_modalita=verifica)
        with _ambiente(db=db_finto, stato_bando=stato_bando), \
                patch.object(pipeline, "_get_settings", return_value=finte):
            return pipeline._import_domini_dovuto()

    def test_domini_in_ombra_un_import_in_ombra_basta(self):
        self.assertFalse(self._dovuto(domini="ombra", verifica="attivo"))

    def test_domini_attivo_serve_un_ok(self):
        self.assertTrue(self._dovuto(domini="attivo", verifica="ombra"))


if __name__ == "__main__":
    unittest.main()
