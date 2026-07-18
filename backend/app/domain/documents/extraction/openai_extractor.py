"""OpenAI-backed CV extractor.

Uses OpenAI structured outputs (a strict JSON schema) so the model returns a
fixed shape — a list of {name, value, confidence} entries over the canonical
aiFind field set — instead of free text. The model only *extracts*; every value
it returns is still gated by confidence and re-checked by the laufwise
pre/postcondition gate before anything is trusted or written. That is the
"verified AI" boundary: the LLM proposes, deterministic checks decide.
"""

from __future__ import annotations

import json
from typing import Any, cast

from app.agents.document_extraction import ExtractedField
from app.core.logging import get_logger
from app.domain.documents.extraction.base import FIELD_ORDER

logger = get_logger(__name__)

# Cap input so a huge PDF can't blow the token budget; CVs are short.
_MAX_CHARS = 16_000

_SYSTEM = (
    "You extract structured fields from a CV/resume for a recruiting system. "
    "Use ONLY information present in the text — never invent or infer beyond what "
    "is written. Return one entry per field you can actually find; omit fields "
    "that are absent (do not emit empty values). Every value is a STRING: for list "
    "fields (skills, languages, education, working_experience) join the items with "
    "'; '. For booleans (willing_to_relocate) use 'ja'/'nein'. Give each entry a "
    "confidence in [0,1] reflecting how certain the text makes it. No commentary."
)

# Strict structured-output schema: a list of typed field entries. Extending the
# field set = extend FIELD_ORDER; the enum below follows automatically.
_SCHEMA = {
    "name": "cv_fields",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "enum": FIELD_ORDER},
                        "value": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "value", "confidence"],
                },
            }
        },
        "required": ["fields"],
    },
}


class OpenAIExtractor:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI  # lazy: only imported when this provider is used

        self._client = OpenAI(api_key=api_key)
        self._model = model

    @staticmethod
    def _clamp(x: object) -> float:
        try:
            return max(0.0, min(1.0, float(x)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5

    def extract(self, text: str) -> list[ExtractedField]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text[:_MAX_CHARS]},
            ],
            response_format=cast(Any, {"type": "json_schema", "json_schema": _SCHEMA}),
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        seen: set[str] = set()
        fields: list[ExtractedField] = []
        for entry in data.get("fields", []):
            name = entry.get("name")
            value = (entry.get("value") or "").strip()
            if name in FIELD_ORDER and value and name not in seen:
                seen.add(name)
                fields.append(
                    ExtractedField(
                        field=name,
                        value=value,
                        confidence=self._clamp(entry.get("confidence", 0.7)),
                    )
                )
        return fields
