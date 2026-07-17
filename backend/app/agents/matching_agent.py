"""Matching agent — a thin wrapper over the matching domain service.

Exists so matching can be orchestrated alongside other agents with the same
contract. Matching produces read/assert outputs (recommendations), not writes to
candidate/job records, so it emits no ``ProposedChange`` — its Match Receipts
are written by the matching service itself.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.agents.base import Agent, AgentResult
from app.domain.matching import service as matching_service
from sqlalchemy.ext.asyncio import AsyncSession


class MatchingInput(BaseModel):
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    include_rejected: bool = False


class MatchingAgent(Agent[MatchingInput]):
    name = "matching_agent"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, payload: MatchingInput) -> AgentResult:
        results = await matching_service.match_job(
            self._session,
            job_id=payload.job_id,
            tenant_id=payload.tenant_id,
            include_rejected=payload.include_rejected,
        )
        return AgentResult(
            agent=self.name,
            notes=[f"surfaced {len(results)} candidate(s)"],
            data={"matches": [r.model_dump(mode="json") for r in results]},
        )