"""Document-extraction agent.

Turns an uploaded document (CV, certificate, ...) into structured fields, each
with its own confidence. Fields below the review threshold are routed to a
human review queue rather than proposed for auto-commit.

Stub: no real OCR/LLM. It accepts already-parsed field candidates and applies
the confidence-gating + provenance logic so the downstream flow is real.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult
from app.domain.common.enums import ConfidenceSource
from app.domain.verification.schemas import ProposedChange

# Below this, a field goes to human review instead of being proposed.
HUMAN_REVIEW_THRESHOLD = 0.6


class ExtractedField(BaseModel):
    field: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class DocumentExtractionInput(BaseModel):
    tenant_id: uuid.UUID
    candidate_id: uuid.UUID
    document_name: str
    fields: list[ExtractedField]


class DocumentExtractionAgent(Agent[DocumentExtractionInput]):
    name = "document_extraction"

    async def run(self, payload: DocumentExtractionInput) -> AgentResult:
        proposals: list[ProposedChange] = []
        review_items: list[str] = []
        notes: list[str] = [f"extracted from {payload.document_name}"]

        for field in payload.fields:
            if field.confidence < HUMAN_REVIEW_THRESHOLD:
                review_items.append(
                    f"low-confidence '{field.field}'={field.value!r} "
                    f"({field.confidence:.2f}) — needs human review"
                )
                continue
            proposals.append(
                ProposedChange(
                    tenant_id=payload.tenant_id,
                    entity_type="candidate",
                    entity_id=payload.candidate_id,
                    field=field.field,
                    proposed_value=field.value,
                    source=ConfidenceSource.DOCUMENT_EXTRACTION,
                    source_detail=payload.document_name,
                    confidence=field.confidence,
                )
            )

        return AgentResult(
            agent=self.name,
            proposals=proposals,
            review_items=review_items,
            notes=notes,
        )