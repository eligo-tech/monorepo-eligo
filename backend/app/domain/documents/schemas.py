"""Pydantic v2 contracts for the documents domain (uploads & extraction)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class CVField(BaseModel):
    """One extracted field, surfaced to the recruiter for review."""

    field: str
    label: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    # Below the agent's threshold → the recruiter must confirm before it's trusted.
    needs_review: bool


class CVExtractionResult(BaseModel):
    """Outcome of parsing an uploaded CV."""

    document_name: str
    fields: list[CVField]
    # Human-readable notes for fields that fell below the confidence threshold.
    review_items: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # Set when persist=true: the candidate created from the accepted fields.
    candidate_id: uuid.UUID | None = None
    # Length of extracted text — 0 usually means an image-only/scanned PDF.
    text_chars: int


class DocumentRead(BaseModel):
    """One file on a candidate — metadata only.

    The bytes stay out of the list on purpose: a dossier with four Zeugnisse
    would otherwise ship several megabytes of base64 to render four rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    #: "cv" | "transkript" | "zeugnis" | "zertifikat" | "sonstiges"
    kind: str
    filename: str
    content_type: str
    byte_size: int
    created_at: dt.datetime
