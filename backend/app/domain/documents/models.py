"""Stored source documents (the raw CV) — the evidence behind a parsed profile.

Kept so the recruiter can see the *original* CV next to the parsed one. The
bytes live in the row (bytea on Postgres) — simple and portable for the scaffold;
swap to object storage (the canonical design) by moving `content` to an URL.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class CandidateDocument(Base, IDMixin, TenantMixin, TimestampMixin):
    """The original uploaded CV for a candidate (evidence for the parsed record)."""

    __tablename__ = "candidate_documents"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), default="application/pdf", nullable=False
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
