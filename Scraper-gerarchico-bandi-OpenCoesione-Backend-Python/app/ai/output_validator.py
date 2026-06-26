from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AllowedValue:
    id: int
    label: str


# Campi booleani: non sono vincolati a un dizionario chiuso DB.
_BOOLEAN_FIELDS: frozenset[str] = frozenset({"is_bando_confermato"})


class AiClassificationOutputValidator:
    """Valida output AI ammettendo solo ID o valori gia' presenti nei dizionari."""

    def __init__(self, allowed_values: dict[str, list[AllowedValue]]) -> None:
        self.allowed_values = allowed_values
        self.allowed_ids = {
            field: {item.id for item in values}
            for field, values in allowed_values.items()
        }
        self.allowed_labels = {
            field: {item.label.casefold(): item.id for item in values}
            for field, values in allowed_values.items()
        }

    def validate(self, output: dict[str, Any] | None) -> dict[str, Any]:
        if not output:
            return {}

        sanitized: dict[str, Any] = {}
        for field, value in output.items():
            # Campi booleani: accetta True/False o stringhe "true"/"false".
            if field in _BOOLEAN_FIELDS:
                if isinstance(value, bool):
                    sanitized[field] = value
                elif isinstance(value, str) and value.lower() in ("true", "false"):
                    sanitized[field] = value.lower() == "true"
                continue

            if field not in self.allowed_values:
                continue

            if isinstance(value, list):
                validated_ids = self._validate_many(field, value)
                if validated_ids:
                    sanitized[field] = validated_ids
                continue

            validated_id = self._validate_one(field, value)
            if validated_id is not None:
                sanitized[field] = validated_id

        return sanitized

    def _validate_one(self, field: str, value: Any) -> int | None:
        if isinstance(value, int) and value in self.allowed_ids[field]:
            return value

        if isinstance(value, str):
            maybe_numeric = value.strip()
            if maybe_numeric.isdigit():
                numeric_id = int(maybe_numeric)
                if numeric_id in self.allowed_ids[field]:
                    return numeric_id

            mapped = self.allowed_labels[field].get(maybe_numeric.casefold())
            if mapped is not None:
                return mapped

        return None

    def _validate_many(self, field: str, values: list[Any]) -> list[int]:
        seen: set[int] = set()
        validated: list[int] = []
        for value in values:
            candidate_id = self._validate_one(field, value)
            if candidate_id is None or candidate_id in seen:
                continue
            seen.add(candidate_id)
            validated.append(candidate_id)
        return validated