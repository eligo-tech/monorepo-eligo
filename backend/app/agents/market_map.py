"""Market-map agent.

Discovers companies and open roles from PUBLIC sources only, and derives
business-development signals. Compliance guardrails are part of the contract:
  * scrape ONLY public job/company data,
  * respect robots.txt and site Terms of Service,
  * never collect data behind authentication or paywalls.

Stub: no real scraping. It accepts already-collected public observations and
turns them into company proposals + BD signals so the flow is real.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult
from app.domain.common.enums import ConfidenceSource
from app.domain.verification.schemas import ProposedChange


class PublicObservation(BaseModel):
    company_name: str
    source_url: str
    signal: str  # e.g. "posted 3 senior backend roles this month"
    robots_allowed: bool = True


class MarketMapInput(BaseModel):
    tenant_id: uuid.UUID
    observations: list[PublicObservation]


class MarketMapAgent(Agent[MarketMapInput]):
    name = "market_map"

    async def run(self, payload: MarketMapInput) -> AgentResult:
        proposals: list[ProposedChange] = []
        review_items: list[str] = []
        notes: list[str] = []

        for obs in payload.observations:
            if not obs.robots_allowed:
                # Compliance gate: refuse to propose data from disallowed sources.
                review_items.append(
                    f"skipped {obs.company_name}: robots.txt/ToS disallows "
                    f"scraping {obs.source_url}"
                )
                continue
            # Represent the discovered company as a proposed record. The
            # verification gate + human decide whether it enters the CRM.
            proposals.append(
                ProposedChange(
                    tenant_id=payload.tenant_id,
                    entity_type="company",
                    entity_id=uuid.uuid4(),  # placeholder id for a new company
                    field="bd_signal",
                    proposed_value=obs.signal,
                    source=ConfidenceSource.PUBLIC_WEB,
                    source_detail=obs.source_url,
                    confidence=0.5,
                )
            )
            notes.append(f"{obs.company_name}: {obs.signal}")

        return AgentResult(
            agent=self.name,
            proposals=proposals,
            review_items=review_items,
            notes=notes,
        )