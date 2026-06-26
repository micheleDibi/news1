#!/usr/bin/env python3
"""Runner Claude Agent SDK per la skill `bandi-seo-enricher`.

Pattern speculare a `backend/skill/scripts/run_agent_sdk_json.py` ma punta alla
skill `bandi-seo-enricher` (cartella `bandi-seo-enricher/` alla root del monorepo,
contiene `SKILL.md` + scripts/ + references/ + config/).

Uso programmatico (dal backend):
    from run_agent_sdk_json_bandi import run_skill_bandi
    payload = await run_skill_bandi(
        link_bando="https://...",
        hint={"ente": "Regione Lombardia", "tipologia": "FESR", "area": "Lombardia",
              "beneficiari": [...], "settori": [...], "ateco": [...]}
    )

Uso CLI (dev):
    python run_agent_sdk_json_bandi.py "https://regione.lombardia.it/.../bando-xyz"
    python run_agent_sdk_json_bandi.py "https://..." --hint '{"ente":"Regione Lombardia"}'

Variabili d'ambiente richieste: ANTHROPIC_API_KEY, FIRECRAWL_API_KEY.
"""
from __future__ import annotations

import anyio
import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock


# La skill vive nella root del monorepo (bandi-seo-enricher/),
# fuori dalla cartella backend/. Risaliamo di 3 livelli da questo file:
# backend/skill_bandi/scripts/run_agent_sdk_json_bandi.py -> backend/skill_bandi/scripts
# -> backend/skill_bandi -> backend -> news1 (monorepo root) -> bandi-seo-enricher
_HERE = Path(__file__).resolve()
SKILL_DIR = _HERE.parent.parent.parent.parent / "bandi-seo-enricher"
OUTPUT_DIR = _HERE.parent.parent / "output"

try:
    from loguru import logger as _logger  # type: ignore
except ImportError:  # pragma: no cover
    _logger = logging.getLogger("bandi_seo_enricher")
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        _logger.addHandler(_h)
        _logger.setLevel(logging.INFO)


def _log_tool_use(block) -> None:
    """Logga una ToolUseBlock, evidenziando Firecrawl per debug del flusso scraping."""
    name = getattr(block, "name", None) or getattr(block, "tool", None) or "?"
    raw_input = getattr(block, "input", None)
    try:
        input_str = json.dumps(raw_input, ensure_ascii=False) if raw_input is not None else ""
    except (TypeError, ValueError):
        input_str = str(raw_input)

    preview = input_str[:300] + ("..." if len(input_str) > 300 else "")
    lowered = input_str.lower()

    if "firecrawl" in lowered:
        _logger.info("[BANDI_SKILL][FIRECRAWL] tool={} input={}", name, preview)
    elif name in ("WebFetch", "WebSearch"):
        _logger.info("[BANDI_SKILL][WEB] tool={} input={}", name, preview)
    elif name == "Bash":
        _logger.info("[BANDI_SKILL][BASH] input={}", preview)
    else:
        _logger.debug("[BANDI_SKILL][TOOL] tool={} input={}", name, preview)


def _build_system_override(output_path: str) -> str:
    """System prompt appendice: forza output a path specifico e regola file ausiliari in /tmp/."""
    return f"""
Stai eseguendo la skill `bandi-seo-enricher` presente nella working directory.
Il workflow e' descritto in SKILL.md e usa gli helper Python in scripts/:
  - scripts/firecrawl_scrape.py    (scraping pagina e PDF)
  - scripts/extract_bando_fields.py (estrazione campi strutturati via regex)
  - scripts/generate_json_output.py (validazione + assembla JSON output)
Le guide editoriali e SEO sono in references/.

OUTPUT FINALE OBBLIGATORIO: UN SOLO JSON scritto nel path ESATTO seguente.

    OUTPUT_PATH = {output_path}

Lo schema del JSON e' quello descritto in SKILL.md (sezione "Schema JSON output"):
campi top-level `generated_at`, `livello` (flash_bando|guida_bando), `source_url`,
`source_domain`, `slug`, `titolo`, `occhiello`, `descrizione_breve`, `contenuto.sections`,
`meta_title`, `meta_description`, oggetto `bando` (ente_erogatore, tipologia,
area_geografica, beneficiari, tematica, scadenza, scadenza_stato, importo_totale_eur,
importo_max_per_progetto_eur, link_candidatura, riferimento_normativo),
`factcheck_report`, `fonti`, `validation`.

REGOLA CRITICA - FILESYSTEM:
QUALSIASI file ausiliario che generi (script Python helper, JSON intermedi,
file di build, dump temporanei) DEVE essere scritto ESCLUSIVAMENTE nella
directory `/tmp/`, MAI dentro la working directory o sottocartelle della skill.
Esempio CORRETTO:
    Write file_path="/tmp/_gen_bando_xyz.py" content="..."
    Bash command="python /tmp/_gen_bando_xyz.py"
Esempio VIETATO (causa restart del backend in dev e sporca il codebase):
    Write file_path="scripts/_gen_xyz.py"
    Write file_path="/root/news1/bandi-seo-enricher/scripts/_gen_xyz.py"
L'unica eccezione e' l'OUTPUT_PATH del JSON finale (gia' in /tmp/).

Per la maggior parte dei casi preferisci la chiamata inline via Bash + python -c.
Esempio per assemblare il payload finale:

    python -c "
    import sys, json; sys.path.insert(0, 'scripts')
    from generate_json_output import build_seo_article_payload
    payload = build_seo_article_payload(...)
    with open('{output_path}', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    "

Se il payload e' troppo grande per python -c, scrivi lo script helper SOLO in
/tmp/ (vedi REGOLA CRITICA - FILESYSTEM sopra), poi eseguilo con `python /tmp/...`.

SCRAPING OBBLIGATORIO VIA FIRECRAWL: il comando shell `firecrawl scrape`
NON esiste. Per scaricare la pagina del bando e gli allegati PDF DEVI usare:

    python scripts/firecrawl_scrape.py "<URL>" [--format markdown] [--max-chars 20000]

Solo se Firecrawl fallisce (exit code != 0 o output vuoto) ricadi su
WebFetch/WebSearch.

Tutto il resto del workflow (STEP 0-8 di SKILL.md) resta invariato:
lettura references/, hint da config/sources.json, scrape pagina + PDF,
estrazione campi via extract_bando_fields.py, verifica link_candidatura,
generazione contenuto editoriale (flash o guida) rispettando blacklist_frasi.md
e seo_guidelines.md, assemble + validate via generate_json_output.py.

Al termine comunica SOLO il percorso del file JSON generato.
""".strip()


def _build_prompt(link_bando: str, hint: dict | None, output_path: str) -> str:
    """Costruisce il prompt utente per la skill."""
    pieces = [f"URL bando: {link_bando}"]
    if hint:
        try:
            hint_json = json.dumps(hint, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            hint_json = str(hint)
        pieces.append(
            "Hint dominio (override / suggerimenti dai dati relazionali dello scraper "
            "OpenCoesione — usa come prior, ma il dato istituzionale prevale se diverge):\n"
            f"{hint_json}"
        )
    pieces.append(
        "Esegui la skill bandi-seo-enricher end-to-end (STEP 0-8 di SKILL.md) e salva "
        f"il risultato come UN SOLO JSON nel path: {output_path}"
    )
    return "\n\n".join(pieces)


async def run_skill_bandi(
    link_bando: str,
    *,
    hint: dict | None = None,
) -> dict:
    """Esegue la skill `bandi-seo-enricher` e ritorna il payload JSON in-memory.

    L'agente scrive il JSON su un file temporaneo che viene letto e rimosso
    dopo la fine del loop.

    Raises:
        RuntimeError: se la skill non produce un file JSON valido.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="skill_payload_bando_")
    os.close(tmp_fd)
    tmp_path_posix = Path(tmp_path).as_posix()

    start_ts = time.monotonic()
    firecrawl_calls = 0
    webfetch_calls = 0
    websearch_calls = 0
    bash_calls = 0
    _logger.info(
        "[BANDI_SKILL] start link={} hint_keys={}",
        link_bando,
        list(hint.keys()) if hint else [],
    )

    try:
        options = ClaudeAgentOptions(
            cwd=str(SKILL_DIR),
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": _build_system_override(tmp_path_posix),
            },
            allowed_tools=["Read", "Write", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"],
            permission_mode="acceptEdits",
            setting_sources=["project", "user"],
        )

        prompt = _build_prompt(link_bando, hint, tmp_path_posix)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                        continue

                    if hasattr(block, "name") and hasattr(block, "input"):
                        name = getattr(block, "name", "")
                        raw_input = getattr(block, "input", None)
                        input_str = ""
                        try:
                            input_str = json.dumps(raw_input, ensure_ascii=False) if raw_input else ""
                        except (TypeError, ValueError):
                            input_str = str(raw_input)

                        lowered = input_str.lower()
                        if "firecrawl" in lowered:
                            firecrawl_calls += 1
                        if name == "WebFetch":
                            webfetch_calls += 1
                        elif name == "WebSearch":
                            websearch_calls += 1
                        elif name == "Bash":
                            bash_calls += 1

                        _log_tool_use(block)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError(
                f"La skill bandi-seo-enricher non ha prodotto output JSON valido su {tmp_path_posix}"
            )

        with open(tmp_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        elapsed = time.monotonic() - start_ts
        _logger.info(
            "[BANDI_SKILL] done in {:.1f}s | firecrawl={} webfetch={} websearch={} bash={} "
            "| livello={} slug={!r}",
            elapsed,
            firecrawl_calls, webfetch_calls, websearch_calls, bash_calls,
            payload.get("livello"), payload.get("slug"),
        )
        if firecrawl_calls == 0:
            _logger.warning(
                "[BANDI_SKILL] Firecrawl NON invocato: la skill potrebbe essere ricaduta "
                "su WebFetch/WebSearch (webfetch={}, websearch={}). "
                "Verifica FIRECRAWL_API_KEY.",
                webfetch_calls, websearch_calls,
            )
        return payload

    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _cli_main():
    """Entrypoint CLI: salva l'output in OUTPUT_DIR/bando_<slug>.json."""
    parser = argparse.ArgumentParser(description="Bandi SEO Enricher (JSON output) via Claude Agent SDK")
    parser.add_argument("link_bando", help="URL del bando da arricchire")
    parser.add_argument(
        "--hint",
        default=None,
        help='Hint dominio JSON, es. \'{"ente":"Regione Lombardia","tipologia":"FESR"}\'',
    )
    args = parser.parse_args()

    hint_obj = None
    if args.hint:
        try:
            hint_obj = json.loads(args.hint)
        except json.JSONDecodeError as e:
            print(f"[!] Hint non e' JSON valido: {e}", file=sys.stderr)
            sys.exit(2)

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("[i] Nessuna ANTHROPIC_API_KEY in env: assumo login OAuth via `claude login`.", file=sys.stderr)
    if not os.environ.get("FIRECRAWL_API_KEY"):
        print("[!] Variabile mancante: FIRECRAWL_API_KEY", file=sys.stderr)
        sys.exit(1)

    async def _run():
        payload = await run_skill_bandi(args.link_bando, hint=hint_obj)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slug = (payload.get("slug") or "bando").lower().replace(" ", "-")
        out_file = OUTPUT_DIR / f"bando_{slug}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON salvato: {out_file.as_posix()}")

    anyio.run(_run)


if __name__ == "__main__":
    _cli_main()
