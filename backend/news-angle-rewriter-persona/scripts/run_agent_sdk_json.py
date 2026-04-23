#!/usr/bin/env python3
"""
Runner Claude Agent SDK per la skill news-angle-rewriter-persona con output JSON.

Variante della skill base: accetta due parametri aggiuntivi, tono e persona,
che modulano la scelta dell'angolo (STEP 2) e la scrittura (STEP 4).
Default: Giornalista + Neutrale.

Uso programmatico (dal backend):
    from backend.skill.scripts.run_agent_sdk_json import run_skill
    payload = await run_skill(
        url,
        livello=None,
        interlink=[...],
        target=None,
        tono="Assertivo",
        persona="Attivista",
    )

Uso CLI (sviluppatore):
    python scripts/run_agent_sdk_json.py "https://www.orizzontescuola.it/..."
    python scripts/run_agent_sdk_json.py "https://..." --tono Formale --persona Accademico
    python scripts/run_agent_sdk_json.py "https://..." --livello editoriale --tono Informale --persona Blogger

Variabili d'ambiente richieste: ANTHROPIC_API_KEY, FIRECRAWL_API_KEY.
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

TONI_VALIDI = [
    "Neutrale", "Formale", "Informale", "Persuasivo", "Umoristico",
    "Serio", "Ottimistico", "Motivazionale", "Rispettoso", "Assertivo",
    "Conversazione",
]

PERSONE_VALIDE = [
    "Copywriter", "Giornalista", "Blogger", "Esperto di settore",
    "Freelance", "Accademico", "Saggista", "Attivista",
    "Divulgatore Scientifico", "Insegnante",
]

TONO_DEFAULT = "Neutrale"
PERSONA_DEFAULT = "Giornalista"

try:
    from loguru import logger as _logger  # type: ignore
except ImportError:  # pragma: no cover
    _logger = logging.getLogger("news_angle_rewriter_persona")
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        _logger.addHandler(_h)
        _logger.setLevel(logging.INFO)


def _log_tool_use(block) -> None:
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
Stai eseguendo la skill `news-angle-rewriter-persona` presente nella working directory.

OUTPUT FINALE OBBLIGATORIO: JSON scritto nel path ESATTO seguente.

    OUTPUT_PATH = {output_path}

Usa SEMPRE `scripts/generate_json_output.py::create_seo_article_json`
come unico formato di output. Non generare DOCX, Markdown o testo libero.
Passa SEMPRE i parametri `tono` e `persona` allo script (anche se sono
i default Giornalista/Neutrale).

Esempio di invocazione via tool Bash:

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
        tono=...,
        persona=...,
        output_path='{output_path}'
    )
    "

VALIDAZIONE COMBINAZIONE TONO+PERSONA (STEP 1.5 di SKILL.md):
dopo aver classificato la natura della notizia (istituzionale / negativa /
neutra) nello STEP 1, verifica la tabella dei blocchi prima di procedere.
Se la combinazione scelta è bloccata, NON generare l'articolo, NON
invocare lo script di output: rispondi all'utente con il messaggio
indicato in `references/tono_persona_guide.md` e fermati.

SCRAPING OBBLIGATORIO VIA FIRECRAWL: il comando shell `firecrawl scrape`
NON esiste. Per leggere l'URL della notizia e qualunque PDF/pagina
istituzionale, DEVI usare lo script helper:

    python scripts/firecrawl_scrape.py "<URL>" [--format markdown] [--max-chars 4000]

Solo se Firecrawl fallisce ricadi su WebFetch/WebSearch.

Al termine (se l'articolo è stato generato) comunica SOLO il percorso
del file JSON e un riassunto di validation + meta.
""".strip()


def _build_prompt(
    url: str,
    livello: str | None,
    interlink: list[str],
    target: str | None,
    tono: str,
    persona: str,
    output_path: str,
) -> str:
    pieces = [
        f"URL notizia: {url}",
        f"Persona richiesta: {persona}",
        f"Tono richiesto: {tono}",
    ]
    if livello:
        pieces.append(f"Livello desiderato: {livello}")
    if interlink:
        pieces.append("Interlink da inserire:\n" + "\n".join(f"- {u}" for u in interlink))
    if target:
        pieces.append(f"Target: {target}")
    pieces.append(
        "Esegui la skill news-angle-rewriter-persona end-to-end. "
        "Verifica la combinazione tono+persona allo STEP 1.5 prima "
        "di scrivere. Se valida, salva il risultato come JSON nel path: "
        f"{output_path}"
    )
    return "\n\n".join(pieces)


def _validate_enum(value: str | None, allowed: list[str], default: str, label: str) -> str:
    v = (value or "").strip() or default
    if v not in allowed:
        raise ValueError(
            f"{label} non valido: {v!r}. Valori ammessi: {allowed}"
        )
    return v


async def run_skill(
    url: str,
    *,
    livello: str | None = None,
    interlink: list[str] | None = None,
    target: str | None = None,
    tono: str | None = None,
    persona: str | None = None,
) -> dict:
    """Esegue la skill e ritorna il payload JSON in-memory.

    Raises:
        ValueError: se tono o persona non sono nell'enum ammesso.
        RuntimeError: se la skill non produce un file JSON valido.
    """
    interlink = interlink or []
    tono_norm = _validate_enum(tono, TONI_VALIDI, TONO_DEFAULT, "Tono")
    persona_norm = _validate_enum(persona, PERSONE_VALIDE, PERSONA_DEFAULT, "Persona")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="skill_payload_")
    os.close(tmp_fd)
    tmp_path_posix = Path(tmp_path).as_posix()

    start_ts = time.monotonic()
    firecrawl_calls = 0
    webfetch_calls = 0
    websearch_calls = 0
    bash_calls = 0
    _logger.info(
        "[SKILL] start url={} livello={} interlink_count={} target={} tono={} persona={}",
        url, livello, len(interlink), target, tono_norm, persona_norm,
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

        prompt = _build_prompt(
            url, livello, interlink, target, tono_norm, persona_norm, tmp_path_posix,
        )

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
            # Caso legittimo: combinazione tono+persona bloccata dallo STEP 1.5.
            # L'agente ha risposto all'utente senza generare JSON.
            raise RuntimeError(
                "La skill non ha prodotto output JSON. "
                "Possibili cause: (a) combinazione tono+persona bloccata dallo "
                "STEP 1.5, l'agente ha risposto all'utente con messaggio di blocco; "
                "(b) errore nel workflow. Verifica il log assistant sopra."
            )

        with open(tmp_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        elapsed = time.monotonic() - start_ts
        meta = payload.get("meta", {})
        _logger.info(
            "[SKILL] done in {:.1f}s | firecrawl={} webfetch={} websearch={} bash={} "
            "| livello={} keyword={!r} tono={!r} persona={!r}",
            elapsed,
            firecrawl_calls, webfetch_calls, websearch_calls, bash_calls,
            payload.get("livello"), payload.get("keyword"),
            meta.get("tono"), meta.get("persona"),
        )
        if firecrawl_calls == 0:
            _logger.warning(
                "[SKILL] Firecrawl NON invocato: la skill potrebbe essere ricaduta "
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
    """Entrypoint CLI: salva l'output in OUTPUT_DIR/articolo_<slug>.json."""
    parser = argparse.ArgumentParser(
        description="News Angle Rewriter Persona Edition (JSON output) via Claude Agent SDK"
    )
    parser.add_argument("url", help="URL della notizia da riscrivere")
    parser.add_argument("--livello", choices=["flash", "editoriale", "evergreen"], default=None)
    parser.add_argument("--interlink", default="", help="URL interni separati da virgola")
    parser.add_argument("--target", default=None, help="Target di riferimento (docenti, ATA, studenti...)")
    parser.add_argument(
        "--tono",
        choices=TONI_VALIDI,
        default=TONO_DEFAULT,
        help=f"Tono della scrittura (default: {TONO_DEFAULT})",
    )
    parser.add_argument(
        "--persona",
        choices=PERSONE_VALIDE,
        default=PERSONA_DEFAULT,
        help=f"Persona autoriale (default: {PERSONA_DEFAULT})",
    )
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
            tono=args.tono,
            persona=args.persona,
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        slug = (payload.get("keyword") or "articolo").lower().replace(" ", "-")
        out_file = OUTPUT_DIR / f"articolo_{slug}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[OK] JSON salvato: {out_file.as_posix()}")
        meta = payload.get("meta", {})
        print(f"[OK] Voce: persona={meta.get('persona')} | tono={meta.get('tono')}")

    anyio.run(_run)


if __name__ == "__main__":
    _cli_main()
