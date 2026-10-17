"""Interviewer agent — turns a pre-screen transcript into proposed profile fields.

Layer: agents. It reads a finished interview (questions from
`domain/interviews/script.py`, the candidate's answers) and PROPOSES one value
per answered question for that question's field. It never writes.

Every proposal carries its evidence: the verbatim words of the candidate it
was read from (`source_detail`). The postconditions then check, against the
transcript and the record as they actually are — never against the agent's
own say-so — that:

1. the field is one the interview is allowed to set (no work permit, no
   protected attributes);
2. the quote really occurs in the candidate's answer to THAT question;
3. the value re-derives from the quote alone by the same deterministic reader;
4. the source is SELF_REPORTED — what a candidate says is a claim, and it does
   not count as evidence in `verification_score`;
5. it does not overwrite a value already on the record — a conflict between
   what the file says and what the candidate says is for a recruiter.

A failed postcondition or a low-confidence reading goes to the human review
queue (`verify_and_commit`). Nothing here rejects or ranks a candidate.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent, AgentResult
from app.domain.common.enums import ConfidenceSource
from app.domain.interviews.script import (
    INTERVIEW_FIELDS,
    QUESTIONS_BY_KEY,
    normalize,
    read_answer,
    rederive,
)
from app.domain.verification.schemas import ProposedChange
from app.domain.verification.service import Postcondition


class Answer(BaseModel):
    question_key: str
    text: str


class InterviewerInput(BaseModel):
    tenant_id: uuid.UUID
    candidate_id: uuid.UUID
    interview_id: uuid.UUID
    answers: list[Answer]
    #: The candidate's current values for the interview fields, as stored.
    existing: dict[str, Any] = {}


class _Evidence(BaseModel):
    question_key: str
    quote: str
    answer: str


class InterviewerAgent(Agent[InterviewerInput]):
    """One instance per interview: the postconditions check against ITS transcript."""

    name = "interviewer"

    def __init__(self) -> None:
        self._evidence: dict[str, _Evidence] = {}
        self._existing: dict[str, Any] = {}

    async def run(self, payload: InterviewerInput) -> AgentResult:
        self._evidence = {}
        self._existing = dict(payload.existing)
        proposals: list[ProposedChange] = []
        review_items: list[str] = []
        notes: list[str] = []

        for answer in payload.answers:
            q = QUESTIONS_BY_KEY.get(answer.question_key)
            if q is None:
                notes.append(f"unbekannte Frage {answer.question_key!r} übersprungen")
                continue
            reading = read_answer(q, answer.text)
            if reading is None:
                notes.append(f"{q.field}: keine verwertbare Angabe")
                continue
            if reading.note:
                review_items.append(f"{q.field}: {reading.note} — „{reading.quote}“")

            self._evidence[q.field] = _Evidence(
                question_key=q.key, quote=reading.quote, answer=answer.text
            )
            proposals.append(
                ProposedChange(
                    tenant_id=payload.tenant_id,
                    entity_type="candidate",
                    entity_id=payload.candidate_id,
                    field=q.field,
                    proposed_value=reading.value,
                    source=ConfidenceSource.SELF_REPORTED,
                    source_detail=(
                        f"interview {payload.interview_id} · {q.key}: "
                        f"„{reading.quote[:300]}“"
                    ),
                    confidence=reading.confidence,
                )
            )

        return AgentResult(
            agent=self.name,
            proposals=proposals,
            review_items=review_items,
            notes=notes,
            data={"interview_id": str(payload.interview_id)},
        )

    def quote_for(self, field: str) -> str | None:
        """The candidate's words a proposal for `field` was read from."""
        ev = self._evidence.get(field)
        return ev.quote if ev else None

    # --- postconditions: pure predicates over the transcript and the record ---

    def postconditions(self) -> list[Postcondition]:
        return [
            self._allowed_field,
            self._self_reported,
            self._quote_in_answer,
            self._value_from_quote,
            self._no_overwrite,
        ]

    def _allowed_field(self, change: ProposedChange) -> tuple[bool, str]:
        if change.field in INTERVIEW_FIELDS:
            return True, ""
        return False, f"{change.field} darf nicht per Interview gesetzt werden"

    def _self_reported(self, change: ProposedChange) -> tuple[bool, str]:
        if change.source is ConfidenceSource.SELF_REPORTED:
            return True, ""
        return False, "Interview-Angaben sind Selbstauskunft"

    def _quote_in_answer(self, change: ProposedChange) -> tuple[bool, str]:
        ev = self._evidence.get(change.field)
        if ev is None:
            return False, "kein Beleg im Transkript"
        if normalize(ev.quote) and normalize(ev.quote) in normalize(ev.answer):
            return True, ""
        return False, "Beleg steht nicht in der Antwort"

    def _value_from_quote(self, change: ProposedChange) -> tuple[bool, str]:
        ev = self._evidence.get(change.field)
        if ev is None:
            return False, "kein Beleg im Transkript"
        q = QUESTIONS_BY_KEY[ev.question_key]
        if rederive(q, ev.quote) == change.proposed_value:
            return True, ""
        return False, "Wert folgt nicht aus dem Beleg"

    def _no_overwrite(self, change: ProposedChange) -> tuple[bool, str]:
        current = self._existing.get(change.field)
        if current is None or (isinstance(current, str) and not current.strip()):
            return True, ""
        if str(current).strip() == (change.proposed_value or "").strip():
            return True, ""
        return False, f"vorhandener Wert {current!r} — Recruiter entscheidet"
