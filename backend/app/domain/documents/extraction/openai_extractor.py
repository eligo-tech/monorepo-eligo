"""OpenAI-backed CV extractor.

Uses OpenAI structured outputs (a strict JSON schema) so the model returns a
fixed shape in a SINGLE call: the flat aiFind fields (each {name, value,
confidence}) AND the structured per-entry history (roles + education with dates
and highlights). The model only *extracts*; every value is still gated by
confidence, grounded against the source text, and re-checked by the laufwise
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
    ExtractionResult,
    FIELD_ORDER,
    TRANSCRIPT_FIELD_ORDER,
    WorkRole,
)

logger = get_logger(__name__)

# Cap input so a huge PDF can't blow the token budget; CVs are short.
_MAX_CHARS = 16_000

# The structured history replaces the flat `working_experience` / `education`
# fields, so the flat field set for the combined call excludes them.
_FLAT_FIELDS = [f for f in FIELD_ORDER if f not in ("working_experience", "education")]

# Anti-hallucination is the whole point: the instructions below forbid inference
# and the downstream gate drops any role/education not grounded in the CV text.
_SYSTEM = (
    "You extract data from a CV/resume for a recruiting system. Follow these "
    "rules strictly:\n"
    "1. GROUNDING: use ONLY information explicitly written in the text. Never "
    "invent, infer, guess, or embellish. If a fact is not stated, omit it — do "
    "not fill gaps with plausible-sounding values.\n"
    "2. VERBATIM FACTS: copy company names, institutions, job titles and dates "
    "exactly as written (e.g. 'Mar 2024', 'Present', '2017–2021'). Do not "
    "normalize, translate, or reformat them.\n"
    "3. FLAT FIELDS (`fields`): one entry per aiFind field you can actually find; "
    "omit absent fields (no empty values). Each value is a STRING; for list "
    "fields (skills, languages) join items with '; '. For booleans "
    "(willing_to_relocate) use 'ja'/'nein'.\n"
    "4. WORK HISTORY (`work_history`): one entry per position, most-recent first, "
    "with title, company, location, start_date, end_date, and 3-6 highlights. A "
    "highlight is a concise rephrasing of a responsibility/achievement ACTUALLY "
    "listed under THAT role — never a skill or claim not written there, and never "
    "carried over from a different role.\n"
    "5. EDUCATION (`education`): degree, institution, location and dates as "
    "written.\n"
    "6. CONFIDENCE: each flat field's confidence in [0,1] reflects how directly "
    "the text states it; lower it when you are unsure. No commentary."
)

_FIELD_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "enum": _FLAT_FIELDS},
        "value": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["name", "value", "confidence"],
}

_ROLE_ITEM = {
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
    "required": ["title", "company", "location", "start_date", "end_date", "highlights"],
}

_EDU_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "degree": {"type": "string"},
        "institution": {"type": "string"},
        "location": {"type": "string"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
    },
    "required": ["degree", "institution", "location", "start_date", "end_date"],
}

# One strict schema covering flat fields + structured history.
_SCHEMA = {
    "name": "cv_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fields": {"type": "array", "items": _FIELD_ITEM},
            "work_history": {"type": "array", "items": _ROLE_ITEM},
            "education": {"type": "array", "items": _EDU_ITEM},
        },
        "required": ["fields", "work_history", "education"],
    },
}


# ── Gesprächstranskript ────────────────────────────────────────────────────
#
# A second, much smaller schema. The transcript is read for what the
# conversation establishes and the CV cannot: the salary floor as well as the
# wish, the notice period as stated out loud, why they are leaving, which other
# processes are running, and when they can take an interview.
#
# The grounding rule is stricter here than for a CV, because an interview is
# full of hedging. "Ich könnte mir vorstellen, so um die 100" is a wish stated
# loosely; "mindestens 92" is a floor. Anything softer than a statement is
# either left out or returned with a low confidence, which routes it to review
# instead of into the record.
_TRANSCRIPT_SYSTEM = (
    "You extract data from a transcript or notes of a recruiting qualification "
    "interview (Qualifikationsgespräch), usually in German. Rules:\n"
    "1. GROUNDING: only what the candidate or recruiter actually SAYS. Never "
    "infer, average, or complete a number. If the candidate did not state it, "
    "omit the field.\n"
    "2. SALARY: `current_salary` is what they earn now, `salary_minimum` the "
    "floor they would accept, `expected_salary` the figure they want. Return "
    "digits only in euro (e.g. '95000'). If a range is named for the floor, "
    "take the LOWER number. Never copy one of the three into another.\n"
    "3. VERBATIM-ISH: `notice_period`, `availability` and "
    "`interview_availability` keep the candidate's own phrasing "
    "('3 Monate zum Monatsende', 'Mi/Do ab 11 Uhr').\n"
    "4. `motivation` is why they are leaving, in one or two sentences. "
    "`other_processes` names the other companies or processes they are in, "
    "with the company names if given. `profile_summary` is two or three "
    "sentences describing the professional profile the conversation revealed.\n"
    "5. `skills` are technologies the candidate states they have worked with; "
    "join with '; '. Do not include technologies merely mentioned by the "
    "recruiter or named as something the candidate does NOT know.\n"
    "6. CONFIDENCE in [0,1]: how plainly the transcript states it. Hedged, "
    "approximate or implied values get a LOW confidence. No commentary."
)

_TRANSCRIPT_FIELD_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "enum": TRANSCRIPT_FIELD_ORDER},
        "value": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["name", "value", "confidence"],
}

_TRANSCRIPT_SCHEMA = {
    "name": "qualification_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"fields": {"type": "array", "items": _TRANSCRIPT_FIELD_ITEM}},
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

    def _call(self, text: str) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text[:_MAX_CHARS]},
            ],
            response_format=cast(Any, {"type": "json_schema", "json_schema": _SCHEMA}),
            temperature=0,  # deterministic; no creative gap-filling
        )
        return json.loads(response.choices[0].message.content or "{}")

    def _parse_fields(
        self, raw: list[dict], allowed: list[str] | None = None
    ) -> list[ExtractedField]:
        allowed = allowed if allowed is not None else _FLAT_FIELDS
        seen: set[str] = set()
        fields: list[ExtractedField] = []
        for entry in raw:
            name = entry.get("name")
            value = (entry.get("value") or "").strip()
            if name in allowed and value and name not in seen:
                seen.add(name)
                fields.append(
                    ExtractedField(
                        field=name,
                        value=value,
                        confidence=self._clamp(entry.get("confidence", 0.7)),
                    )
                )
        return fields

    @staticmethod
    def _parse_sections(data: dict) -> CVSections:
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
        roles = [r for r in roles if r.title or r.company]
        education = [e for e in education if e.degree or e.institution]
        return CVSections(work_history=roles, education=education)

    def extract_all(self, text: str) -> ExtractionResult:
        """Flat fields + structured history in one call."""
        data = self._call(text)
        return ExtractionResult(
            fields=self._parse_fields(data.get("fields", [])),
            sections=self._parse_sections(data),
        )

    def extract(self, text: str) -> list[ExtractedField]:
        """Flat fields only (Protocol conformance; the app uses `extract_all`)."""
        return self.extract_all(text).fields

    def extract_qualification(self, text: str) -> list[ExtractedField]:
        """Read a Gesprächstranskript for the post-interview fields."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _TRANSCRIPT_SYSTEM},
                {"role": "user", "content": text[:_MAX_CHARS]},
            ],
            response_format=cast(
                Any, {"type": "json_schema", "json_schema": _TRANSCRIPT_SCHEMA}
            ),
            temperature=0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return self._parse_fields(data.get("fields", []), TRANSCRIPT_FIELD_ORDER)
