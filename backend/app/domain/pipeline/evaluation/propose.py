"""Material → model → checks → a pending proposal (ELI-42).

The model's answer never touches `application_assessments`. It becomes an
`agent_proposals` row of kind "assessment" — the same table, lifecycle and
receipts the MCP proposals use — and a recruiter confirms or declines it in
the mandate view. Confirming runs `pipeline.set_assessment`, the write a
manual save runs, attributed to the person who confirmed (GDPR Art. 22: the
evaluation is a recommendation; a human makes it the record).

A new evaluation of the same process supersedes the open one (it goes
"stale"), so the card never shows two competing drafts.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.pipeline import bewertung
from app.domain.pipeline import service as pipeline
from app.domain.pipeline.evaluation.base import CandidateEvaluator
from app.domain.pipeline.evaluation.checks import check
from app.domain.proposals import service as proposals
from app.domain.proposals.models import AgentProposal

logger = get_logger(__name__)

KIND = "assessment"
TOOL = "pipeline.evaluate_candidate"
#: Recorded as the proposal's client: the in-app evaluator, not an MCP client.
CLIENT = "eligo-ki"


class NoEvaluator(RuntimeError):
    """No model is configured — the caller offers the copy-prompt instead."""


class EvaluatorFailed(RuntimeError):
    """The model call failed or answered nothing usable. Nothing was stored."""


async def pending_for(
    session: AsyncSession, *, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> AgentProposal | None:
    """The open AI evaluation of this process, if there is one."""
    rows = await session.execute(
        select(AgentProposal)
        .where(
            AgentProposal.tenant_id == tenant_id,
            AgentProposal.kind == KIND,
            AgentProposal.status == proposals.PENDING,
        )
        .order_by(AgentProposal.created_at.desc())
    )
    for row in rows.scalars():
        if (row.args or {}).get("application_id") == str(application_id) and (
            proposals.effective_status(row) == proposals.PENDING
        ):
            return row
    return None


async def propose_evaluation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    evaluator: CandidateEvaluator | None,
    user_id: str | None,
    name: str | None,
) -> AgentProposal | None:
    """Evaluate one candidate on one mandate. None if the process is not ours."""
    if evaluator is None:
        raise NoEvaluator("no model configured")
    material = await pipeline.evaluation_material(
        session, tenant_id=tenant_id, application_id=application_id
    )
    if material is None:
        return None
    prompt = bewertung.build_prompt(material)
    try:
        # The SDK is synchronous; keep the event loop free while it waits.
        answer = await asyncio.to_thread(evaluator.evaluate, prompt)
    except Exception as exc:
        # The type only: an SDK error can quote the request, i.e. the CV.
        logger.warning("evaluator %s failed (%s)", evaluator.name, type(exc).__name__)
        raise EvaluatorFailed(type(exc).__name__) from None
    if not answer.strip():
        raise EvaluatorFailed("empty answer")

    checked = check(answer, material)
    generated_at = dt.datetime.now(dt.UTC)
    snapshot = await proposals.snapshot(
        session, tenant_id=tenant_id, kind=KIND, args={"application_id": str(application_id)}
    )

    previous = await pending_for(session, tenant_id=tenant_id, application_id=application_id)
    if previous is not None:
        await proposals.supersede(session, row=previous, user_id=user_id, name=name)

    assessment = dict(checked.assessment)
    assessment["assessed_at"] = generated_at.isoformat()
    draft = proposals.ProposalDraft(
        kind=KIND,
        title=f"{material.candidate_name} · {material.job_title} — KI-Kandidatenauswertung",
        args={
            "application_id": str(application_id),
            "model": evaluator.model,
            "provider": evaluator.name,
            "generated_at": generated_at.isoformat(),
            "text": answer,
            "assessment": assessment,
            "flags": checked.flags,
            "client_text_withheld": checked.client_text_withheld,
        },
        snapshot=snapshot or {},
        refs=(("application", str(application_id)),),
    )
    return await proposals.create(
        session,
        tenant_id=tenant_id,
        draft=draft,
        tool=TOOL,
        asked_by_user_id=user_id,
        asked_by_name=name,
        client_id=CLIENT,
    )
