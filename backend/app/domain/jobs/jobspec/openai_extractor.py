"""OpenAI-backed advert reader — structured output, one call.

The same contract as the CV extractor: the model only EXTRACTS, every value
comes back with a confidence, and nothing it returns is written anywhere
without a human pressing save. The instructions forbid inference for the
same reason they do there — an invented salary band or an invented
Muss-Kriterium is worse than a blank field, because a blank field is
obviously blank.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.domain.jobs.jobspec.base import JobSpec, ProposedField
from app.domain.jobs.jobspec.heuristic import HeuristicJobSpecExtractor

logger = get_logger(__name__)

_MAX_CHARS = 16_000

_SYSTEM = (
    "You read ONE job advert for a recruiting system and return its facts.\n"
    "1. GROUNDING: use only what the advert states. Never infer, guess or "
    "round. If the advert does not give a salary, omit the salary — do not "
    "estimate one from the seniority.\n"
    "2. TITLE: the advert's own headline, including the (m/w/d) marker if it "
    "has one. Not the company name, not the page title.\n"
    "3. SALARY: annual gross in EUR as integers. '60-70 T€' is 60000 and "
    "70000. A monthly figure must be omitted, not multiplied.\n"
    "4. MUST-HAVE SKILLS: only what the advert states as REQUIRED "
    "('Voraussetzung', 'zwingend', 'Sie bringen mit'). A technology named "
    "once in a task description is NOT a requirement. These exclude "
    "candidates, so when in doubt leave it out.\n"
    "5. CONFIDENCE: 0.0-1.0, how plainly the advert states it. A labelled "
    "'Gehalt: 60.000-70.000 €' is high; a band inferred from 'attraktive "
    "Vergütung nach IG Metall' does not exist and must be omitted.\n"
    "Answer in the advert's own language."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "location", "salary_min", "salary_max", "employment_form", "must_have_skills"],
    "properties": {
        "title": {"type": ["object", "null"], "additionalProperties": False,
                  "required": ["value", "confidence"],
                  "properties": {"value": {"type": "string"}, "confidence": {"type": "number"}}},
        "location": {"type": ["object", "null"], "additionalProperties": False,
                     "required": ["value", "confidence"],
                     "properties": {"value": {"type": "string"}, "confidence": {"type": "number"}}},
        "salary_min": {"type": ["object", "null"], "additionalProperties": False,
                       "required": ["value", "confidence"],
                       "properties": {"value": {"type": "integer"}, "confidence": {"type": "number"}}},
        "salary_max": {"type": ["object", "null"], "additionalProperties": False,
                       "required": ["value", "confidence"],
                       "properties": {"value": {"type": "integer"}, "confidence": {"type": "number"}}},
        "employment_form": {"type": ["object", "null"], "additionalProperties": False,
                            "required": ["value", "confidence"],
                            "properties": {"value": {"type": "string"}, "confidence": {"type": "number"}}},
        "must_have_skills": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["value", "confidence"],
                      "properties": {"value": {"type": "string"}, "confidence": {"type": "number"}}},
        },
    },
}


def _field(raw: object) -> ProposedField | None:
    if not isinstance(raw, dict) or raw.get("value") in (None, ""):
        return None
    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return ProposedField(str(raw["value"]).strip(), max(0.0, min(1.0, confidence)))


class OpenAIJobSpecExtractor:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI  # imported here so the SDK stays optional

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(self, text: str, document_title: str = "") -> JobSpec:
        body = text[:_MAX_CHARS]
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": body},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "job_spec", "strict": True, "schema": _SCHEMA},
                },
            )
            payload = json.loads(completion.choices[0].message.content or "{}")
        except Exception as exc:
            # The feature must work without the model, exactly as CV
            # extraction does. A failed call is a quieter answer, not an error
            # in the recruiter's face.
            logger.warning("job spec extraction via OpenAI failed (%s) — heuristic", exc)
            return HeuristicJobSpecExtractor().extract(text, document_title)

        spec = JobSpec(excerpt=body[:1200])
        spec.title = _field(payload.get("title"))
        spec.location = _field(payload.get("location"))
        spec.salary_min = _field(payload.get("salary_min"))
        spec.salary_max = _field(payload.get("salary_max"))
        spec.employment_form = _field(payload.get("employment_form"))
        skills = payload.get("must_have_skills")
        if isinstance(skills, list):
            spec.must_have_skills = [f for f in (_field(s) for s in skills) if f]

        # A band the model inverted is a band nobody can use.
        if spec.salary_min and spec.salary_max:
            try:
                if int(spec.salary_min.value) > int(spec.salary_max.value):
                    spec.salary_min, spec.salary_max = spec.salary_max, spec.salary_min
            except ValueError:
                spec.salary_min = spec.salary_max = None
        return spec
