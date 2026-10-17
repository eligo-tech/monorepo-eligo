"""Interviews — consent first, then questions, then proposals through verification.

Every operation that ASKS or EXTRACTS is behind the `interviewer` feature gate
(`features.service.ensure_enabled`), checked here in the service so no caller
can skip it. Two operations are deliberately NOT gated, because they protect
the candidate and must work even after a workspace switches the feature off:
reading an interview, and withdrawing consent.

The candidate's consent is a second, independent gate: no question is asked
and nothing is extracted until consent to the current notice is recorded.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.interviewer import Answer, InterviewerAgent, InterviewerInput
from app.domain.candidates.models import Candidate
from app.domain.candidates.service import recompute_scores
from app.domain.common.enums import ReceiptAction
from app.domain.features import service as features
from app.domain.interviews.models import Interview
from app.domain.interviews.script import (
    CANDIDATE_NOTICE_VERSION,
    INTERVIEW_FIELDS,
    QUESTIONS,
    SCRIPT_VERSION,
)
from app.domain.interviews.schemas import QuestionRead
from app.domain.verification.schemas import ProposedChange
from app.domain.verification.service import append_receipt, verify_and_commit

FEATURE = "interviewer"
_INT_FIELDS = {"salary_minimum", "salary_expectation"}


class NotFound(Exception):
    pass


class InvalidState(Exception):
    """The request does not fit the interview's current status."""


FeatureDisabled = features.FeatureDisabled


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _receipt(
    session: AsyncSession, interview: Interview, summary: str, payload: dict
) -> None:
    await append_receipt(
        session,
        tenant_id=interview.tenant_id,
        agent="interviewer",
        action=ReceiptAction.ASSERT,
        subject_type="interview",
        subject_id=str(interview.id),
        verified=True,
        summary=summary,
        payload=payload,
    )


async def get_interview(
    session: AsyncSession, *, tenant_id: uuid.UUID, interview_id: uuid.UUID
) -> Interview:
    row = (
        await session.execute(
            select(Interview).where(
                Interview.tenant_id == tenant_id, Interview.id == interview_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("interview not found")
    return row


async def list_for_candidate(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> list[Interview]:
    rows = await session.execute(
        select(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.candidate_id == candidate_id)
        .order_by(Interview.created_at.desc())
    )
    return list(rows.scalars())


def next_question(interview: Interview) -> QuestionRead | None:
    """The first question without an answer, while the interview is running."""
    if interview.status != "in_progress":
        return None
    answered = {t["question_key"] for t in interview.turns}
    for number, q in enumerate(QUESTIONS, start=1):
        if q.key not in answered:
            return QuestionRead(key=q.key, prompt=q.prompt, number=number, total=len(QUESTIONS))
    return None


async def start(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    candidate_id: uuid.UUID,
    started_by: str,
) -> Interview:
    await features.ensure_enabled(session, tenant_id=tenant_id, key=FEATURE)
    candidate = (
        await session.execute(
            select(Candidate.id).where(
                Candidate.tenant_id == tenant_id, Candidate.id == candidate_id
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise NotFound("candidate not found")

    interview = Interview(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        status="awaiting_consent",
        script_version=SCRIPT_VERSION,
        started_by=started_by,
        turns=[],
        outcome={},
    )
    session.add(interview)
    await session.commit()
    await session.refresh(interview)
    return interview


async def record_consent(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    notice_version: str,
    confirmed: bool,
    recorded_by: str,
) -> Interview:
    await features.ensure_enabled(session, tenant_id=tenant_id, key=FEATURE)
    interview = await get_interview(session, tenant_id=tenant_id, interview_id=interview_id)
    if interview.status != "awaiting_consent":
        raise InvalidState(f"consent cannot be recorded in status {interview.status}")
    if not confirmed:
        raise InvalidState("consent must be given explicitly")
    if notice_version != CANDIDATE_NOTICE_VERSION:
        raise InvalidState(
            f"notice {notice_version!r} is not the current {CANDIDATE_NOTICE_VERSION!r}"
        )

    interview.consent_version = notice_version
    interview.consent_at = _now()
    interview.consent_recorded_by = recorded_by
    interview.status = "in_progress"
    await _receipt(
        session, interview,
        f"candidate consent to AI interview (notice {notice_version})",
        {"candidate_id": str(interview.candidate_id), "recorded_by": recorded_by,
         "notice_version": notice_version},
    )
    await session.commit()
    await session.refresh(interview)
    return interview


async def answer(
    session: AsyncSession, *, tenant_id: uuid.UUID, interview_id: uuid.UUID, text: str
) -> Interview:
    await features.ensure_enabled(session, tenant_id=tenant_id, key=FEATURE)
    interview = await get_interview(session, tenant_id=tenant_id, interview_id=interview_id)
    if interview.status != "in_progress" or interview.consent_at is None:
        raise InvalidState("no consent recorded — the interview has not started")
    q = next_question(interview)
    if q is None:
        raise InvalidState("all questions are answered — complete the interview")

    # Reassign (not append in place) so the JSON column is marked dirty.
    interview.turns = [
        *interview.turns,
        {
            "question_key": q.key,
            "question": q.prompt,
            "answer": text.strip(),
            "at": _now().isoformat(),
        },
    ]
    await session.commit()
    await session.refresh(interview)
    return interview


async def complete(
    session: AsyncSession, *, tenant_id: uuid.UUID, interview_id: uuid.UUID
) -> Interview:
    """Run the interviewer agent and route every proposal through verification."""
    await features.ensure_enabled(session, tenant_id=tenant_id, key=FEATURE)
    interview = await get_interview(session, tenant_id=tenant_id, interview_id=interview_id)
    if interview.status != "in_progress" or interview.consent_at is None:
        raise InvalidState(f"cannot complete an interview in status {interview.status}")
    if not interview.turns:
        raise InvalidState("no answers to evaluate")

    candidate = (
        await session.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id, Candidate.id == interview.candidate_id
            )
        )
    ).scalar_one()

    agent = InterviewerAgent()
    result = await agent.run(
        InterviewerInput(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            interview_id=interview.id,
            answers=[
                Answer(question_key=t["question_key"], text=t["answer"])
                for t in interview.turns
            ],
            existing={f: getattr(candidate, f, None) for f in INTERVIEW_FIELDS},
        )
    )

    outcome: dict[str, dict] = {}
    for proposal in result.proposals:
        async def _apply(_s: AsyncSession, change: ProposedChange) -> None:
            value: object = change.proposed_value
            if change.field in _INT_FIELDS and value is not None:
                value = int(value)
            setattr(candidate, change.field, value)

        commit = await verify_and_commit(
            session,
            change=proposal,
            agent=agent.name,
            postconditions=agent.postconditions(),
            apply_hook=_apply,
        )
        outcome[proposal.field] = {
            "field": proposal.field,
            "value": proposal.proposed_value,
            "quote": agent.quote_for(proposal.field),
            "committed": commit.committed,
            "needs_human_review": commit.needs_human_review,
            "reason": commit.reason,
        }

    await session.flush()
    await recompute_scores(session, tenant_id=tenant_id, candidate=candidate)

    interview.outcome = {
        "fields": outcome,
        "review_items": result.review_items,
        "notes": result.notes,
    }
    interview.status = "completed"
    interview.completed_at = _now()
    await _receipt(
        session, interview,
        f"interview completed — {sum(o['committed'] for o in outcome.values())} "
        f"übernommen, {sum(o['needs_human_review'] for o in outcome.values())} zur Prüfung",
        {"candidate_id": str(candidate.id), "fields": sorted(outcome)},
    )
    await session.commit()
    await session.refresh(interview)
    return interview


async def withdraw(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    interview_id: uuid.UUID,
    recorded_by: str,
) -> Interview:
    """The candidate withdraws consent: erase the transcript, keep the fact.

    Not gated by the feature switch — a candidate's right to withdraw cannot
    depend on whether the workspace still has the feature on (Art. 7(3)
    GDPR). Values already committed from an earlier, completed interview stay
    on the record with their provenance; erasing those is the candidate's
    erasure request, handled like any other.
    """
    interview = await get_interview(session, tenant_id=tenant_id, interview_id=interview_id)
    if interview.status == "withdrawn":
        return interview
    interview.turns = []
    interview.status = "withdrawn"
    interview.withdrawn_at = _now()
    await _receipt(
        session, interview,
        "candidate withdrew consent — transcript erased",
        {"candidate_id": str(interview.candidate_id), "recorded_by": recorded_by},
    )
    await session.commit()
    await session.refresh(interview)
    return interview
