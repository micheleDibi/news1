from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable
from unicodedata import normalize as unicode_normalize

from app.ai.output_validator import AiClassificationOutputValidator, AllowedValue
from app.repos.base import ReferenceDataRepo


@dataclass(frozen=True)
class ReferenceOption:
    id: int
    label: str
    normalized: str
    tokens: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceCatalog:
    tipologie_bando: tuple[ReferenceOption, ...]
    modalita_erogazione: tuple[ReferenceOption, ...]
    programmi: tuple[ReferenceOption, ...]
    regioni: tuple[ReferenceOption, ...]
    settori: tuple[ReferenceOption, ...]
    beneficiari: tuple[ReferenceOption, ...]
    codici_ateco: tuple[ReferenceOption, ...]
    categoria_programma: tuple[ReferenceOption, ...]
    tipologia_programma: tuple[ReferenceOption, ...]


class ControlledClassificationService:
    """Classificazione deterministica limitata ai valori gia' esistenti nel DB."""

    def __init__(
        self,
        reference_repo: ReferenceDataRepo | None = None,
        catalog: ReferenceCatalog | None = None,
    ) -> None:
        self.reference_repo = reference_repo or ReferenceDataRepo()
        self.catalog = catalog or self.reload_catalog()

    def reload_catalog(self) -> ReferenceCatalog:
        self.catalog = ReferenceCatalog(
            tipologie_bando=tuple(
                _build_option(item["id"], item["nome"], _tipologia_aliases(item["nome"]))
                for item in self.reference_repo.get_tipologie_bando()
            ),
            modalita_erogazione=tuple(
                _build_option(item["id"], item["nome"], _modalita_aliases(item["nome"]))
                for item in self.reference_repo.get_modalita_erogazione()
            ),
            programmi=tuple(
                _build_option(item["id"], item["nome"], _programma_aliases(item["nome"]))
                for item in self.reference_repo.get_programmi()
            ),
            regioni=tuple(
                _build_option(item["id"], item["nome"], (item.get("slug") or "",))
                for item in self.reference_repo.get_regioni()
            ),
            settori=tuple(
                _build_option(item["id"], item["nome"])
                for item in self.reference_repo.get_settori()
            ),
            beneficiari=tuple(
                _build_option(item["id"], item["nome"])
                for item in self.reference_repo.get_beneficiari()
            ),
            codici_ateco=tuple(
                _build_option(
                    item["id"],
                    f"{item['codice']} {item['descrizione']}",
                    (str(item["codice"]), str(item["descrizione"])),
                )
                for item in self.reference_repo.get_codici_ateco()
            ),
            categoria_programma=tuple(
                _build_option(item["id"], item["nome"])
                for item in self.reference_repo.get_categorie_programma()
            ),
            tipologia_programma=tuple(
                _build_option(item["id"], item["nome"])
                for item in self.reference_repo.get_tipologie_programma()
            ),
        )
        return self.catalog

    def classify_candidate(self, payload: dict[str, Any], fonte: Any | None = None) -> dict[str, Any]:
        fragments = self._extract_fragments(payload, fonte=fonte)
        normalized_fragments = [_normalize_text(fragment) for fragment in fragments if fragment]

        result: dict[str, Any] = {}

        is_bando_confermato = self._infer_is_bando_confermato(payload, normalized_fragments)
        if is_bando_confermato is not None:
            result["is_bando_confermato"] = is_bando_confermato

        tipologia = self._match_single(self.catalog.tipologie_bando, normalized_fragments)
        if tipologia is None:
            tipologia = self._infer_tipologia_from_context(normalized_fragments, fonte=fonte)
        if tipologia is not None:
            result["tipologia_bando_id"] = tipologia.id

        modalita = self._match_single(self.catalog.modalita_erogazione, normalized_fragments)
        if modalita is not None:
            result["modalita_erogazione_id"] = modalita.id

        programma = self._match_single(self.catalog.programmi, normalized_fragments, min_similarity=0.93)
        if programma is not None:
            result["programma_id"] = programma.id

        regione_ids = self._match_many(self.catalog.regioni, normalized_fragments)
        if regione_ids:
            result["regione_ids"] = regione_ids

        settore_ids = self._match_many(self.catalog.settori, normalized_fragments, min_similarity=0.9)
        if settore_ids:
            result["settore_ids"] = settore_ids

        beneficiario_ids = self._match_many(self.catalog.beneficiari, normalized_fragments, min_similarity=0.9)
        if beneficiario_ids:
            result["beneficiario_ids"] = beneficiario_ids

        ateco_ids = self._match_many(self.catalog.codici_ateco, normalized_fragments, min_similarity=0.95)
        if ateco_ids:
            result["codice_ateco_ids"] = ateco_ids

        return result

    def classify_candidates(self, payloads: list[dict[str, Any]], fonte: Any | None = None) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for payload in payloads:
            classified = dict(payload)
            classified.update(self.classify_candidate(payload, fonte=fonte))
            enriched.append(classified)
        return enriched

    def prepare_ai_fallback_payload(self, unresolved_fields: Iterable[str]) -> dict[str, Any]:
        fields = list(dict.fromkeys(field for field in unresolved_fields if field))
        allowed_values: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            if field == "is_bando_confermato":
                allowed_values[field] = [
                    {"value": True, "label": "sì — la pagina descrive un bando, avviso o opportunità di finanziamento"},
                    {"value": False, "label": "no — la pagina non è un bando (es. pagina generica, navigazione, documento non pertinente)"},
                ]
                continue
            options = self._allowed_values().get(field, [])
            allowed_values[field] = [{"id": item.id, "label": item.label} for item in options]
        return {
            "mode": "choose-existing-only",
            "unresolved_fields": fields,
            "allowed_values": allowed_values,
        }

    def build_ai_validator(self) -> AiClassificationOutputValidator:
        return AiClassificationOutputValidator(
            {
                field: [AllowedValue(id=item.id, label=item.label) for item in options]
                for field, options in self._allowed_values().items()
            }
        )

    def _allowed_values(self) -> dict[str, tuple[ReferenceOption, ...]]:
        return {
            "tipologia_bando_id": self.catalog.tipologie_bando,
            "modalita_erogazione_id": self.catalog.modalita_erogazione,
            "programma_id": self.catalog.programmi,
            "regione_ids": self.catalog.regioni,
            "settore_ids": self.catalog.settori,
            "beneficiario_ids": self.catalog.beneficiari,
            "codice_ateco_ids": self.catalog.codici_ateco,
            "categoria_programma_id": self.catalog.categoria_programma,
            "tipologia_programma_id": self.catalog.tipologia_programma,
        }

    def _match_single(
        self,
        options: tuple[ReferenceOption, ...],
        normalized_fragments: list[str],
        min_similarity: float = 0.9,
    ) -> ReferenceOption | None:
        scored = self._score_options(options, normalized_fragments, min_similarity=min_similarity)
        return scored[0][0] if scored else None

    def _match_many(
        self,
        options: tuple[ReferenceOption, ...],
        normalized_fragments: list[str],
        min_similarity: float = 0.88,
    ) -> list[int]:
        scored = self._score_options(options, normalized_fragments, min_similarity=min_similarity)
        return [option.id for option, _score in scored]

    def _score_options(
        self,
        options: tuple[ReferenceOption, ...],
        normalized_fragments: list[str],
        min_similarity: float,
    ) -> list[tuple[ReferenceOption, float]]:
        matches: list[tuple[ReferenceOption, float]] = []
        for option in options:
            best_score = 0.0
            for fragment in normalized_fragments:
                score = _score_match(option, fragment)
                if score > best_score:
                    best_score = score
            if best_score >= min_similarity:
                matches.append((option, best_score))

        matches.sort(key=lambda item: (-item[1], item[0].label))
        return matches

    def _extract_fragments(self, payload: dict[str, Any], fonte: Any | None = None) -> list[str]:
        fragments: list[str] = []
        for key in ["titolo", "descrizione", "codice_bando", "fondo", "importo", "link_bando"]:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                fragments.append(value)

        raw_data_obj = payload.get("raw_data_obj") or {}
        fragments.extend(_extract_strings(raw_data_obj))

        data_extra = payload.get("data_extra") or {}
        fragments.extend(_extract_strings(data_extra))

        if fonte is not None:
            for attr in ["titolo", "link", "tipo_link", "formato_link"]:
                value = getattr(fonte, attr, None)
                if isinstance(value, str) and value.strip():
                    fragments.append(value)

        return fragments

    def _infer_tipologia_from_context(
        self,
        normalized_fragments: list[str],
        fonte: Any | None = None,
    ) -> ReferenceOption | None:
        combined = " ".join(normalized_fragments)
        prefer_label: str | None = None

        if any(term in combined for term in ["pnrr", "programma nazionale", "pn "]):
            prefer_label = "Bandi nazionali / PNRR"
        elif any(term in combined for term in ["programma regionale", "regione ", "regionali", "pr "]):
            prefer_label = "Bandi regionali / locali"
        elif any(term in combined for term in ["europa", "europe", "interreg", "horizon", "erasmus"]):
            prefer_label = "Bandi Europei"

        if prefer_label is None and fonte is not None:
            fonte_title = _normalize_text(getattr(fonte, "titolo", "") or "")
            if "regionale" in fonte_title:
                prefer_label = "Bandi regionali / locali"
            elif "nazionale" in fonte_title:
                prefer_label = "Bandi nazionali / PNRR"

        if prefer_label is None:
            return None

        for option in self.catalog.tipologie_bando:
            if option.label == prefer_label:
                return option
        return None

    def _infer_is_bando_confermato(self, payload: dict[str, Any], normalized_fragments: list[str]) -> bool | None:
        raw_data_obj = payload.get("raw_data_obj") or {}
        diagnostics = raw_data_obj.get("link_diagnostics") or {}

        accepted = bool(diagnostics.get("accepted", False))
        score = int(diagnostics.get("score") or 0)
        reason_reject = str(diagnostics.get("reason_reject") or "")

        if accepted and score >= 2:
            return True

        lowered_blob = " ".join(normalized_fragments)
        if any(term in lowered_blob for term in ["privacy", "cookie", "login", "logout", "mappa del sito"]):
            return False

        if reason_reject in {"DENY_HOST", "DENY_PATH", "DENY_KEYWORD", "NON_HTML_OR_PDF"}:
            return False

        # Fallback conservativo: se ci sono segnali bando ma non abbastanza forti,
        # preferiamo indicare FALSE anziché lasciare NULL, così il KPI si chiude.
        if any(term in lowered_blob for term in ["bando", "bandi", "avviso", "opportunit", "voucher", "contribut", "finanzi", "incentiv", "manifestazione", "domanda", "graduatoria", "selezione", "invito", "agevolaz"]):
            return True

        return False


def _extract_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if value.strip():
            strings.append(value)
        return strings

    if isinstance(value, dict):
        for child in value.values():
            strings.extend(_extract_strings(child))
        return strings

    if isinstance(value, list):
        for child in value:
            strings.extend(_extract_strings(child))
        return strings

    return strings


def _build_option(identifier: int, label: str, aliases: Iterable[str] = ()) -> ReferenceOption:
    normalized_label = _normalize_text(label)
    alias_values = tuple(
        alias_normalized
        for alias in aliases
        for alias_normalized in [_normalize_text(alias)]
        if alias_normalized
    )
    tokens = tuple(token for token in normalized_label.split() if len(token) > 2)
    return ReferenceOption(
        id=int(identifier),
        label=str(label),
        normalized=normalized_label,
        tokens=tokens,
        aliases=alias_values,
    )


def _normalize_text(value: str) -> str:
    ascii_text = unicode_normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.casefold()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def _score_match(option: ReferenceOption, fragment: str) -> float:
    if not fragment:
        return 0.0

    candidates = (option.normalized, *option.aliases)
    best = 0.0
    fragment_tokens = set(fragment.split())

    for candidate in candidates:
        if not candidate:
            continue
        if candidate == fragment:
            return 1.0
        if candidate in fragment:
            best = max(best, 0.99)
            continue

        candidate_tokens = {token for token in candidate.split() if len(token) > 2}
        if candidate_tokens and candidate_tokens.issubset(fragment_tokens):
            best = max(best, 0.97)
            continue

        ratio = SequenceMatcher(None, candidate, fragment).ratio()
        if ratio > best:
            best = ratio

        for token in candidate_tokens:
            if token in fragment_tokens:
                best = max(best, 0.9)

    return best


def _tipologia_aliases(label: str) -> tuple[str, ...]:
    mapping = {
        "Bandi Europei": ("europei", "ue", "europe", "interreg", "horizon"),
        "Bandi nazionali / PNRR": ("nazionali", "nazionale", "pnrr", "pn"),
        "Bandi regionali / locali": ("regionali", "regionale", "locali", "locale", "pr"),
        "Bandi internazionali": ("internazionali", "internazionale"),
        "Bandi delle Fondazioni / altri enti": ("fondazioni", "fondazione", "enti"),
    }
    return mapping.get(label, ())


def _modalita_aliases(label: str) -> tuple[str, ...]:
    mapping = {
        "Fondo perduto": ("contributo a fondo perduto", "fondo perduto"),
        "Tasso Agevolato": ("tasso agevolato", "finanziamento agevolato"),
        "Misto": ("misto",),
        "Contributo in conto interessi": ("conto interessi",),
    }
    return mapping.get(label, ())


def _programma_aliases(label: str) -> tuple[str, ...]:
    aliases: list[str] = []
    if " - " in label:
        prefix, suffix = label.split(" - ", 1)
        aliases.append(prefix)
        aliases.append(suffix)

    acronym_match = re.match(r"^([A-Z0-9]{2,})\b", label.strip())
    if acronym_match:
        aliases.append(acronym_match.group(1))

    return tuple(dict.fromkeys(alias for alias in aliases if alias))