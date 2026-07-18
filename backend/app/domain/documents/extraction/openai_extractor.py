"""OpenAI-backed CV extractor.

Uses OpenAI structured outputs (a strict JSON schema) so the model returns a
fixed shape — the seven canonical fields plus a per-field confidence — instead
of free text. The model only *extracts*; every value it returns is still
gated by confidence and re-checked by the laufwise pre/postcondition gate before
anything is trusted or written. That is the "verified AI" boundary: the LLM
proposes, deterministic checks decide.
"""

from __future__ import annotations

import json
from typing import Any, cast

from app.agents.document_extraction import ExtractedField
from app.core.logging import get_logger

logger = get_logger(__name__)

# Cap input so a huge PDF can't blow the token budget; CVs are short.
_MAX_CHARS = 12_000

_SYSTEM = (
    "You extract structured fields from a CV/resume. Use ONLY information present "
    "in the text — never invent or infer beyond what is written. For each field, "
    "return the value and a confidence in [0,1] reflecting how certain the text "
    "makes it. Use null when a field is absent. 'skills' is a list of short skill "
    "tokens actually mentioned. Do not include commentary."
)

# Strict structured-output schema: fixed keys, all required, no extras.
_SCHEMA = {
    "name": "cv_fields",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "full_name": {"type": ["string", "null"]},
            "email": {"type": ["string", "null"]},
            "phone": {"type": ["string", "null"]},
            "current_title": {"type": ["string", "null"]},
            "current_company": {"type": ["string", "null"]},
            "location": {"type": ["string", "null"]},
            "skills": {"type": "array", "items": {"type": "string"}},
            "confidence": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "full_name": {"type": "number"},
                    "email": {"type": "number"},
                    "phone": {"type": "number"},
                    "current_title": {"type": "number"},
                    "current_company": {"type": "number"},
                    "location": {"type": "number"},
                    "skills": {"type": "number"},
                },
                "required": [
                    "full_name", "email", "phone", "current_title",
                    "current_company", "location", "skills",
                ],
            },
        },
        "required": [
            "full_name", "email", "phone", "current_title",
            "current_company", "location", "skills", "confidence",
        ],
    },
}


class OpenAIExtractor:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI  # lazy: only imported when this provider is used

        self._client = OpenAI(api_key=api_key)
        self._model = model

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
        return self._to_fields(data)

    @staticmethod
    def _clamp(x: object) -> float:
        try:
            return max(0.0, min(1.0, float(x)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5

    def _to_fields(self, data: dict) -> list[ExtractedField]:
        conf = data.get("confidence") or {}
        fields: list[ExtractedField] = []
        for key in ("full_name", "email", "phone", "current_title", "current_company", "location"):
            value = data.get(key)
            if value:
                fields.append(
                    ExtractedField(
                        field=key,
                        value=str(value).strip(),
                        confidence=self._clamp(conf.get(key, 0.7)),
                    )
                )
        skills = [s.strip() for s in (data.get("skills") or []) if str(s).strip()]
        if skills:
            fields.append(
                ExtractedField(
                    field="skills",
                    value=", ".join(skills),
                    confidence=self._clamp(conf.get("skills", 0.7)),
                )
            )
        return fields