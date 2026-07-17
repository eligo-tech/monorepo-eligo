"""Enrichment agent.

Fills gaps in a candidate profile from third-party sources. Two obligations are
baked in:
  * POSTCONDITION verification before write (e.g. email deliverability) —
    declared via :meth:`postconditions`, enforced by the verification gate.
  * When personal data is collected from a THIRD-PARTY source, a GDPR Art. 14
    notification workflow must be triggered (the data subject did not provide
    the data themselves). This agent flags that requirement on the result.

Stub: no real lookups. Deliverability/format checks are deterministic.
"""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult
from app.domain.common.enums import ConfidenceSource
from app.domain.verification.schemas import ProposedChange
from app.domain.verification.service import Postcondition

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EnrichmentCandidateField(BaseModel):
    field: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: ConfidenceSource = ConfidenceSource.THIRD_PARTY_SOURCE
    source_detail: str | None = None


class EnrichmentInput(BaseModel):
    tenant_id: uuid.UUID
    candidate_id: uuid.UUID
    gaps: list[EnrichmentCandidateField]


def _email_deliverability_postcondition(change: ProposedChange) -> tuple[bool, str]:
    """Postcondition: an email field must look deliverable before it is written.

    Real impl would do MX/SMTP verification; here it is format-only, but it runs
    inside the same verification gate the LLM-backed version would.
    """
    if change.field != "email":
        return True, ""
    value = change.proposed_value or ""
    ok = bool(_EMAIL_RE.match(value))
    return ok, ("email format valid" if ok else f"email {value!r} undeliverable")


class EnrichmentAgent(Agent[EnrichmentInput]):
    name = "enrichment"

    def postconditions(self) -> list[Postcondition]:
        return [_email_deliverability_postcondition]

    async def run(self, payload: EnrichmentInput) -> AgentResult:
        proposals: list[ProposedChange] = []
        review_items: list[str] = []
        notes: list[str] = []
        gdpr_art14_required = False

        for gap in payload.gaps:
            proposals.append(
                ProposedChange(
                    tenant_id=payload.tenant_id,
                    entity_type="candidate",
                    entity_id=payload.candidate_id,
                    field=gap.field,
                    proposed_value=gap.value,
                    source=gap.source,
                    source_detail=gap.source_detail,
                    confidence=gap.confidence,
                )
            )
            if gap.source in {
                ConfidenceSource.THIRD_PARTY_SOURCE,
                ConfidenceSource.PUBLIC_WEB,
            }:
                gdpr_art14_required = True

        if gdpr_art14_required:
            review_items.append(
                "GDPR Art. 14 notification owed: personal data collected from a "
                "third-party source — data subject must be informed."
            )
            notes.append("gdpr_art14_notification: queued")

        return AgentResult(
            agent=self.name,
            proposals=proposals,
            review_items=review_items,
            notes=notes,
            data={"gdpr_art14_required": gdpr_art14_required},
        )