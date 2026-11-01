"""A change an AI client proposed, waiting for a human in Eligo (PR 4, ADR 0003 §3.7).

Its own table rather than a reuse of `enrichment_records`: those are
field-level provenance (which value came from where, GDPR Art. 14). A proposal
is an *action* — "mark this step done", "add this note" — with a lifecycle
(pending → confirmed / declined / stale), an author who asked and a different
person who decided. Stretching the provenance table to hold that would mix
two things a regulator reads separately.

Classification (ARCHITECTURE.md): **personal data, tenant-scoped.** A note
proposal carries the note text Claude drafted; declining erases it.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONBDict


class AgentProposal(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "agent_proposals"

    #: "step" | "candidate_note" — which applier confirms it.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    #: pending | confirmed | declined | stale. "expired" is derived from age,
    #: never stored, so no job has to sweep it.
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False, index=True)
    #: The registry action that created it ("pipeline.propose_step").
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    #: What a human reads in the list: "Anna Beispiel · COC Lead — Interviewtermin".
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    #: The validated arguments the applier runs with on confirm.
    args: Mapped[dict] = mapped_column(JSONBDict, default=dict, nullable=False)
    #: What the client saw when it proposed. Confirm re-reads it and refuses
    #: when it changed — a proposal is about a state, not a blind write.
    snapshot: Mapped[dict] = mapped_column(JSONBDict, default=dict, nullable=False)
    #: Claude's stated reason, shown to the confirmer. Erased on decline.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    asked_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    asked_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: The OAuth client (one Clerk application per AI product).
    client_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    decided_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
