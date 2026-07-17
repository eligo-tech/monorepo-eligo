"""Outreach agent.

Drafts personalized candidate outreach and client-facing candidate
presentations. Hard rule: **nothing is sent without explicit human approval.**
This agent only ever produces drafts; the result is always flagged for human
review and it emits no auto-committable proposals.

Stub: templated drafts, no real LLM and no send capability.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.agents.base import Agent, AgentResult


class OutreachInput(BaseModel):
    tenant_id: uuid.UUID
    candidate_name: str
    candidate_headline: str
    job_title: str
    company_name: str
    channel: str = "email"  # email | linkedin | ...


class OutreachAgent(Agent[OutreachInput]):
    name = "outreach"

    async def run(self, payload: OutreachInput) -> AgentResult:
        outreach_draft = (
            f"Hi {payload.candidate_name.split()[0]},\n\n"
            f"Your background as {payload.candidate_headline} stood out for a "
            f"{payload.job_title} role we're hiring for at {payload.company_name}. "
            f"Would you be open to a short call this week?\n\nBest regards"
        )
        presentation_draft = (
            f"Candidate presentation — {payload.candidate_name}\n"
            f"Headline: {payload.candidate_headline}\n"
            f"Proposed for: {payload.job_title} @ {payload.company_name}\n"
            f"[evidence-backed summary generated here]"
        )

        return AgentResult(
            agent=self.name,
            # Draft only — never a ProposedChange, never sent automatically.
            proposals=[],
            review_items=[
                "outreach draft requires human approval before sending",
                "candidate presentation requires human approval before sharing",
            ],
            notes=[f"channel={payload.channel}"],
            data={
                "outreach_draft": outreach_draft,
                "presentation_draft": presentation_draft,
                "approved": False,
                "sent": False,
            },
        )