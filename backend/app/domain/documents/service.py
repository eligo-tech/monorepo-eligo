"""CV extraction orchestration.

Ties the pieces together: parse PDF → heuristic field extraction → the
document-extraction agent (confidence gating + human-review routing) →
optionally persist a candidate and record receipts through the verification gate.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.document_extraction import (
    HUMAN_REVIEW_THRESHOLD,
    DocumentExtractionAgent,
    DocumentExtractionInput,
    ExtractedField,
)
from app.domain.candidates import service as candidates_service
from app.domain.candidates.schemas import CandidateCreate
from app.domain.documents import parser
from app.domain.documents.schemas import CVExtractionResult, CVField

# Display labels for the extracted fields (product-facing).
FIELD_LABELS: dict[str, str] = {
    "full_name": "Name",
    "email": "E-Mail",
    "phone": "Telefon",
    "current_title": "Job Title",
    "current_company": "Aktuelles Unternehmen",
    "location": "Standort",
    "skills": "Skills",
}


def _accepted(fields: list[ExtractedField]) -> dict[str, str]:
    """Fields at/above the confidence threshold, keyed by field name."""
    return {
        f.field: f.value
        for f in fields
        if f.confidence >= HUMAN_REVIEW_THRESHOLD
    }


def _build_candidate(tenant_id: uuid.UUID, fields: list[ExtractedField]) -> CandidateCreate:
    """Assemble a CandidateCreate from the accepted (high-confidence) fields."""
    acc = _accepted(fields)
    skills = [s.strip() for s in acc.get("skills", "").split(",") if s.strip()]
    return CandidateCreate(
        tenant_id=tenant_id,
        full_name=acc.get("full_name") or "Unbekannt (aus CV)",
        email=acc.get("email"),
        phone=acc.get("phone"),
        current_title=acc.get("current_title"),
        current_company=acc.get("current_company"),
        location=acc.get("location"),
        skills=skills,
    )


async def extract_cv(
    session: AsyncSession,
    *,
    filename: str,
    content: bytes,
    tenant_id: uuid.UUID,
    persist: bool,
) -> CVExtractionResult:
    text = parser.pdf_to_text(content)
    extracted = parser.extract_cv_fields(text)

    agent = DocumentExtractionAgent()
    candidate_id: uuid.UUID | None = None

    if persist:
        # Create the candidate skeleton from accepted fields, then run the agent
        # against it so every proposed field leaves a Receipt via verification.
        created = await candidates_service.create_candidate(
            session, data=_build_candidate(tenant_id, extracted)
        )
        candidate_id = created.id
        agent_result = await agent.run(
            DocumentExtractionInput(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                document_name=filename,
                fields=extracted,
            )
        )
        await agent.commit(session, agent_result)
    else:
        # Preview only — gate fields for display, but write nothing.
        agent_result = await agent.run(
            DocumentExtractionInput(
                tenant_id=tenant_id,
                candidate_id=uuid.uuid4(),
                document_name=filename,
                fields=extracted,
            )
        )

    fields = [
        CVField(
            field=f.field,
            label=FIELD_LABELS.get(f.field, f.field),
            value=f.value,
            confidence=round(f.confidence, 2),
            needs_review=f.confidence < HUMAN_REVIEW_THRESHOLD,
        )
        for f in extracted
    ]

    return CVExtractionResult(
        document_name=filename,
        fields=fields,
        review_items=agent_result.review_items,
        notes=agent_result.notes,
        candidate_id=candidate_id,
        text_chars=len(text),
    )