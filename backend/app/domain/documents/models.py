"""Stored source documents — the evidence behind a parsed profile.

Kept so the recruiter can see the *original* document next to the parsed one:
the CV, the Gesprächstranskript the qualification data was read from, and the
Zeugnisse and Zertifikate a client asks for before an interview. The
bytes live in the row (bytea on Postgres) — simple and portable for the scaffold;
swap to object storage (the canonical design) by moving `content` to an URL.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import DocumentKind
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class CandidateDocument(Base, IDMixin, TenantMixin, TimestampMixin):
    """One uploaded file belonging to a candidate (evidence for the record)."""

    __tablename__ = "candidate_documents"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    #: What the file is — see `DocumentKind`. Rows written before kinds
    #: existed are CVs, which is true: nothing else could be uploaded.
    kind: Mapped[str] = mapped_column(
        String(20), default=DocumentKind.CV.value, server_default="cv", nullable=False
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), default="application/pdf", nullable=False
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
