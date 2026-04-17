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
import os
import sys
import tempfile
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock


SKILL_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SKILL_DIR / "output"


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

Tutto il resto del workflow (step 0-4 di SKILL.md) resta invariato:
lettura references, scraping, analisi competitor, fact-check.

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

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError(
                f"La skill non ha prodotto output JSON valido su {tmp_path_posix}"
            )

        with open(tmp_path, "r", encoding="utf-8") as f:
            return json.load(f)

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
