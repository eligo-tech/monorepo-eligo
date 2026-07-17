"""Pydantic v2 contracts for the verification domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.enums import ConfidenceSource, ReceiptAction


class ProposedChange(BaseModel):
    """A single field change an agent wants applied to an entity.

    Agents emit these; ``verify_and_commit`` decides whether to persist them.
    """

    tenant_id: uuid.UUID
    entity_type: str = Field(..., description="e.g. 'candidate'")
    entity_id: uuid.UUID
    field: str
    proposed_value: str | None = None
    source: ConfidenceSource
    source_detail: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class ReceiptRead(BaseModel):
    """Public shape of an append-only receipt."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent: str
    action: ReceiptAction
    subject_type: str
    subject_id: str
    verified: bool
    summary: str
    payload: dict = Field(default_factory=dict)
    prev_hash: str | None
    receipt_hash: str
    created_at: dt.datetime


class EnrichmentRecordRead(BaseModel):
    """Public shape of a proposed-change record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    field: str
    proposed_value: str | None
    source: ConfidenceSource
    source_detail: str | None
    confidence: float
    committed: bool
    needs_human_review: bool
    receipt_id: uuid.UUID | None
    created_at: dt.datetime


class CommitResult(BaseModel):
    """Outcome of ``verify_and_commit`` for one proposed change."""

    committed: bool
    needs_human_review: bool
    reason: str
    receipt: ReceiptRead
    record: EnrichmentRecordRead