#!/usr/bin/env python3
"""
Runner Claude Agent SDK per la skill news-angle-rewriter con output JSON.

Uso programmatico (dal backend):
    from backend.skill.scripts.run_agent_sdk_json import run_skill
    payload = await run_skill(url, livello=None, interlink=[...], target=None)

Uso CLI (sviluppatore):
    python scripts/run_agent_sdk_json.py "https://www.orizzontescuola.it/..."
    python scripts/run_agent_sdk_json.py "https://..." --livello editoriale
    python scripts/run_agent_sdk_json.py "https://..." --interlink https://edunews24.it/a,https://edunews24.it/b

Variabili d'ambiente richieste: ANTHROPIC_API_KEY, FIRECRAWL_API_KEY.
Sono caricate dal `.env` del backend (load_dotenv() in backend/app/main.py)
quando la skill gira in-process. In modalità CLI devono essere già esportate
nell'ambiente shell.
"""
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


SKILL_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SKILL_DIR / "output"

# Logger: usa loguru se disponibile (quando invocata dal backend), altrimenti
# ricade sul logging stdlib per l'uso CLI.
try:
    from loguru import logger as _logger  # type: ignore
except ImportError:  # pragma: no cover
    _logger = logging.getLogger("news_angle_rewriter")
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        _logger.addHandler(_h)
        _logger.setLevel(logging.INFO)


def _log_tool_use(block) -> None:
    """Logga una ToolUseBlock della Claude Agent SDK, evidenziando Firecrawl."""
    name = getattr(block, "name", None) or getattr(block, "tool", None) or "?"
    raw_input = getattr(block, "input", None)
    try:
        input_str = json.dumps(raw_input, ensure_ascii=False) if raw_input is not None else ""
    except (TypeError, ValueError):
        input_str = str(raw_input)

    preview = input_str[:300] + ("..." if len(input_str) > 300 else "")
    lowered = input_str.lower()

    if "firecrawl" in lowered:
        _logger.info("[SKILL][FIRECRAWL] tool={} input={}", name, preview)
    elif name in ("WebFetch", "WebSearch"):
        _logger.info("[SKILL][WEB] tool={} input={}", name, preview)
    elif name == "Bash":
        _logger.info("[SKILL][BASH] input={}", preview)
    else:
        _logger.debug("[SKILL][TOOL] tool={} input={}", name, preview)


def _build_system_override(output_path: str) -> str:
    """System prompt appendice che forza l'output a un path specifico."""
    return f"""
Stai eseguendo la skill `news-angle-rewriter` presente nella working directory.

OUTPUT FINALE OBBLIGATORIO: JSON scritto nel path ESATTO seguente.

    OUTPUT_PATH = {output_path}

Usa SEMPRE `scripts/generate_json_output.py::create_seo_article_json`
come unico formato di output. Non generare DOCX, Markdown o testo libero.

Esegui lo script tramite il tool Bash, ad esempio:

    python -c "
    import sys; sys.path.insert(0, 'scripts')
    from generate_json_output import create_seo_article_json
    create_seo_article_json(
        title=...,
        meta_title=...,
        meta_description=...,
        content_sections=[...],
        fonti=[...],
        angolo=...,
        livello=...,
        factcheck_report=[...],
        competitor_report=[...],
        keyword=...,
        source_url=...,
        output_path='{output_path}'
    )
    "

SCRAPING OBBLIGATORIO VIA FIRECRAWL: il comando shell `firecrawl scrape`
NON esiste nel sistema. Per leggere l'URL della notizia (Step 1 di SKILL.md)
e qualunque PDF/pagina istituzionale citata, DEVI usare lo script helper
dedicato:

    python scripts/firecrawl_scrape.py "<URL>" [--format markdown] [--max-chars 4000]

Esempio via Bash tool:

    python scripts/firecrawl_scrape.py "https://www.esempio.it/notizia" --max-chars 6000

Usa Firecrawl tramite questo script come PRIMA SCELTA per lo scraping.
Solo se Firecrawl fallisce (exit code != 0 o output vuoto) ricadi su
WebFetch/WebSearch. NON usare mai `firecrawl scrape` come comando diretto.

Tutto il resto del workflow (step 0-4 di SKILL.md) resta invariato:
lettura references, scraping via Firecrawl, analisi competitor, fact-check.

Al termine comunica SOLO il percorso del file JSON generato.
""".strip()


def _build_prompt(url: str, livello: str | None, interlink: list[str], target: str | None, output_path: str) -> str:
    pieces = [f"URL notizia: {url}"]
    if livello:
        pieces.append(f"Livello desiderato: {livello}")
    if interlink:
        pieces.append("Interlink da inserire:\n" + "\n".join(f"- {u}" for u in interlink))
    if target:
        pieces.append(f"Target: {target}")
    pieces.append(
        "Esegui la skill news-angle-rewriter end-to-end e salva il risultato "
        f"come JSON nel path: {output_path}"
    )
    return "\n\n".join(pieces)


async def run_skill(
    url: str,
    *,
    livello: str | None = None,
    interlink: list[str] | None = None,
    target: str | None = None,
) -> dict:
    """Esegue la skill e ritorna il payload JSON in-memory.

    L'agente scrive il JSON su un file temporaneo che viene letto e rimosso
    dopo la fine del loop — il caller riceve un dict Python pronto all'uso.

    Raises:
        RuntimeError: se la skill non produce un file JSON valido.
    """
    interlink = interlink or []

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="skill_payload_")
    os.close(tmp_fd)
    # Path stile unix anche su Windows per non confondere la shell del modello
    tmp_path_posix = Path(tmp_path).as_posix()

    start_ts = time.monotonic()
    firecrawl_calls = 0
    webfetch_calls = 0
    websearch_calls = 0
    bash_calls = 0
    _logger.info(
        "[SKILL] start url={} livello={} interlink_count={} target={}",
        url, livello, len(interlink), target,
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

        prompt = _build_prompt(url, livello, interlink, target, tmp_path_posix)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                        continue

                    # Duck typing: ogni block non-text con `name`+`input` e' una ToolUseBlock
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
                f"La skill non ha prodotto output JSON valido su {tmp_path_posix}"
            )

        with open(tmp_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        elapsed = time.monotonic() - start_ts
        _logger.info(
            "[SKILL] done in {:.1f}s | firecrawl={} webfetch={} websearch={} bash={} | livello={} keyword={!r}",
            elapsed,
            firecrawl_calls, webfetch_calls, websearch_calls, bash_calls,
            payload.get("livello"), payload.get("keyword"),
        )
        if firecrawl_calls == 0:
            _logger.warning(
                "[SKILL] Firecrawl NON invocato: la skill potrebbe essere ricaduta "
                "su WebFetch/WebSearch (webfetch={}, websearch={}). "
                "Verifica FIRECRAWL_API_KEY e la disponibilita' del CLI firecrawl.",
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
    """Entrypoint CLI: salva l'output in OUTPUT_DIR/articolo_<slug>.json come prima."""
    parser = argparse.ArgumentParser(description="News Angle Rewriter (JSON output) via Claude Agent SDK")
    parser.add_argument("url", help="URL della notizia da riscrivere")
    parser.add_argument("--livello", choices=["flash", "editoriale", "evergreen"], default=None)
    parser.add_argument("--interlink", default="", help="URL interni separati da virgola")
    parser.add_argument("--target", default=None, help="Target di riferimento (docenti, ATA, studenti...)")
    args = parser.parse_args()

    interlink = [u.strip() for u in args.interlink.split(",") if u.strip()]

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("[i] Nessuna ANTHROPIC_API_KEY in env: assumo login OAuth via `claude login`.", file=sys.stderr)
    if not os.environ.get("FIRECRAWL_API_KEY"):
        print("[!] Variabile mancante: FIRECRAWL_API_KEY", file=sys.stderr)
        print("    Esportala in shell oppure definiscila nel .env del backend.", file=sys.stderr)
        sys.exit(1)

    async def _run():
        payload = await run_skill(
            args.url,
            livello=args.livello,
            interlink=interlink,
            target=args.target,
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slug = (payload.get("keyword") or "articolo").lower().replace(" ", "-")
        out_file = OUTPUT_DIR / f"articolo_{slug}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON salvato: {out_file.as_posix()}")

    anyio.run(_run)


if __name__ == "__main__":
    _cli_main()
