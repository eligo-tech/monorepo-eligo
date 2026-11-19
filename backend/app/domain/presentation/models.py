"""A workspace's CI for what it sends to clients (ELI-20).

One row per workspace, edited by its admins in Einstellungen. It lives in the
database and not in Railway's environment: the logo and the AGB paragraph are
the customer's, they change without a deploy, and every workspace has its own
(memory: "no product config in Railway").

Nothing here is about a candidate. The optional phone is the agency's own
switchboard or a consultant's business line, printed in the "Kontakt" box.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin

#: Neutral slate-teal, used until an admin sets the workspace's own colour.
DEFAULT_PRIMARY_COLOR = "#1F4E5A"


class WorkspaceBranding(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "workspace_branding"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_workspace_branding_tenant"),)

    #: "Panam Partners GmbH" — the PDF's author, and the logo's stand-in when
    #: no logo is uploaded.
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The centred footer line: name · street · town · website.
    company_line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: The small print under it — the agency's AGB clause, pasted by an admin.
    #: Never shipped as a default: it is a legal text, and only the agency can
    #: say what theirs is.
    legal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: "#RRGGBB" — title, values and rules.
    primary_color: Mapped[str] = mapped_column(
        String(7), default=DEFAULT_PRIMARY_COLOR, nullable=False
    )
    #: Printed in the Kontakt box when the person downloading gives no number.
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: ELI-55: the small mark left of "Cockpit" in the app's dark header — a
    #: separate slot because the cover-sheet logo is drawn for white paper.
    #: PNG, JPEG or an SVG rebuilt by `service.sanitize_svg`.
    header_icon: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    header_icon_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
