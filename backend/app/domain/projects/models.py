"""Projects — a named set of target companies.

Markt answers "who is hiring X near Y" across the shared corpus, and
"Beobachten" keeps an employer in this workspace. A project is the next step:
the recruiter's own grouping of those employers under a name they chose —
"TypeScript Berlin Q4", "Pflege Rhein-Main" — so a search that produced forty
interesting companies becomes a piece of work with a boundary.

Deliberately thin. A project holds a NAME and a set of corpus companies; the
contacts belong to the companies (`managers`) and the ads to the corpus. There
is no status machine and no copied data: everything else is read through the
membership, so a project can never disagree with the record it points at.

Tenant-scoped like every other record row, and RLS-isolated: which companies a
recruiter is working is competitive intelligence.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class Project(Base, IDMixin, TenantMixin, TimestampMixin):
    """One named piece of work: "TypeScript Berlin Q4"."""

    __tablename__ = "projects"
    __table_args__ = (
        # Two projects with the same name in one workspace are a mistake, not a
        # feature: the name is how a recruiter refers to the work.
        UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    companies: Mapped[list["ProjectCompany"]] = relationship(
        "ProjectCompany",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ProjectCompany(Base, IDMixin, TenantMixin, TimestampMixin):
    """One employer in one project.

    Points at the SHARED corpus row (`hub_company_id`), not at a copy: the
    company's name, sites and open roles stay the corpus's to tell. An employer
    can be in several projects — the same company is a target for more than one
    piece of work, and forcing a choice would lose that.
    """

    __tablename__ = "project_companies"
    __table_args__ = (
        UniqueConstraint("project_id", "hub_company_id", name="uq_project_company"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hub_company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hub_companies.id"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="companies")
