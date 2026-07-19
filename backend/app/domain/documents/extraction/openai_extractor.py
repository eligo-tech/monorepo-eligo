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
from app.domain.documents.extraction.base import (
    CVSections,
    EducationEntry,
    FIELD_ORDER,
    WorkRole,
)

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

# Focused prompt + strict schema for the per-entry history. A dedicated call
# (rather than cramming this into the flat schema) lets the model attend to
# parsing each role's dates and achievement bullets accurately.
_SECTIONS_SYSTEM = (
    "You parse the WORK EXPERIENCE and EDUCATION sections of a CV/resume into "
    "structured entries for a recruiting system. Use ONLY what the text states — "
    "never invent titles, employers, dates or achievements. For each role return "
    "its title, company, location, start_date and end_date (verbatim as written, "
    "e.g. 'Mar 2024', 'Present'), and 3-6 concise highlights: the concrete "
    "responsibilities/achievements listed for THAT role (short phrases, no leading "
    "bullet characters). Order roles most-recent first. For education return "
    "degree, institution, location and dates. Leave a string empty if the CV does "
    "not state it; return an empty highlights list if none are given. No commentary."
)

_SECTIONS_SCHEMA = {
    "name": "cv_sections",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "work_history": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "location": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "highlights": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "title", "company", "location",
                        "start_date", "end_date", "highlights",
                    ],
                },
            },
            "education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "degree": {"type": "string"},
                        "institution": {"type": "string"},
                        "location": {"type": "string"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                    "required": [
                        "degree", "institution", "location",
                        "start_date", "end_date",
                    ],
                },
            },
        },
        "required": ["work_history", "education"],
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

    def extract_sections(self, text: str) -> CVSections:
        """Structured per-entry work history + education (dates + highlights)."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SECTIONS_SYSTEM},
                {"role": "user", "content": text[:_MAX_CHARS]},
            ],
            response_format=cast(
                Any, {"type": "json_schema", "json_schema": _SECTIONS_SCHEMA}
            ),
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        roles = [
            WorkRole(
                title=(r.get("title") or "").strip(),
                company=(r.get("company") or "").strip(),
                location=(r.get("location") or "").strip(),
                start_date=(r.get("start_date") or "").strip(),
                end_date=(r.get("end_date") or "").strip(),
                highlights=[h.strip() for h in (r.get("highlights") or []) if h.strip()],
            )
            for r in data.get("work_history", [])
        ]
        education = [
            EducationEntry(
                degree=(e.get("degree") or "").strip(),
                institution=(e.get("institution") or "").strip(),
                location=(e.get("location") or "").strip(),
                start_date=(e.get("start_date") or "").strip(),
                end_date=(e.get("end_date") or "").strip(),
            )
            for e in data.get("education", [])
        ]
        # Drop wholly-empty entries the model may emit.
        roles = [r for r in roles if r.title or r.company]
        education = [e for e in education if e.degree or e.institution]
        return CVSections(work_history=roles, education=education)
