"""Agent base contract.

An agent takes typed input, does its narrow job, and returns an ``AgentResult``.
The result carries:
  * ``proposals`` — ``ProposedChange`` objects for the verification gate,
  * ``review_items`` — things a human must look at (low confidence, sensitive),
  * ``notes`` — free-form diagnostics.

Agents never touch the database. The ``commit`` helper is the ONLY bridge to
persistence, and it routes every proposal through ``verify_and_commit`` so a
Receipt is always recorded.
"""

from __future__ import annotations

import abc
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.verification import service as verification_service
from app.domain.verification.schemas import CommitResult, ProposedChange
from app.domain.verification.service import Postcondition

InputT = TypeVar("InputT")


class AgentResult(BaseModel):
    """Uniform output contract for every agent."""

    agent: str
    proposals: list[ProposedChange] = Field(default_factory=list)
    review_items: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def requires_human_review(self) -> bool:
        return bool(self.review_items)


class Agent(abc.ABC, Generic[InputT]):
    """Base class for narrow workers.

    Subclasses implement :meth:`run` (pure — no DB writes). Postconditions that
    proposals must satisfy before commit are declared per agent.
    """

    name: str = "agent"

    def postconditions(self) -> list[Postcondition]:
        """Deterministic checks a proposal must pass before it can be written.

        Override per agent (e.g. email format, allowed provenance source).
        """
        return []

    @abc.abstractmethod
    async def run(self, payload: InputT) -> AgentResult:
        """Do the agent's narrow job and return proposals — never write."""
        raise NotImplementedError

    async def commit(
        self, session: AsyncSession, result: AgentResult
    ) -> list[CommitResult]:
        """Route every proposal through the verification gate.

        This is the single, audited path from an agent to the system-of-record.
        """
        outcomes: list[CommitResult] = []
        for proposal in result.proposals:
            outcome = await verification_service.verify_and_commit(
                session,
                change=proposal,
                agent=result.agent,
                postconditions=self.postconditions(),
            )
            outcomes.append(outcome)
        await session.commit()
        return outcomes