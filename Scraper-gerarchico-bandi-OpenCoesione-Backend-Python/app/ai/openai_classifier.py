from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.config.settings import settings


class OpenAiClassificationClient:
    """Client OpenAI dedicato alla classificazione M7 con output JSON strutturato."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or settings.openai_model
        self.client = OpenAI(api_key=api_key or settings.openai_api_key)

    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": _build_user_prompt(payload)},
            ],
        )

        content = (response.choices[0].message.content or "").strip()
        if not content:
            return {}
        return _parse_json_object(content)


def _build_system_prompt() -> str:
    return (
        "Sei un classificatore rigoroso. Restituisci solo JSON valido. "
        "Puoi scegliere esclusivamente ID o label presenti in allowed_values. "
        "Se non sei sicuro o non trovi corrispondenze, ometti il campo. "
        "Non inventare mai nuovi valori."
    )


def _build_user_prompt(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "classifica campi mancanti scegliendo solo da dizionario",
            "expected_output_type": "json_object",
            "input": payload,
        },
        ensure_ascii=True,
        indent=2,
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}