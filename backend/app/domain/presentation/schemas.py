"""Wire contracts for branding and the cover sheet (ELI-20)."""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CoverSheetVariant(str, enum.Enum):
    """What goes to the client. The four the ticket names."""

    #: The Kandidatenprofil page alone.
    COVER = "cover"
    #: + the newest CV on file.
    COVER_CV = "cover_cv"
    #: + the CV, every Zeugnis and every Zertifikat.
    COVER_CV_REFERENCES = "cover_cv_references"
    #: The page alone, name cut to initials, nothing attached.
    ANONYMOUS = "anonymous"


class BrandingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_name: str | None = None
    company_line: str | None = None
    legal_text: str | None = None
    primary_color: str
    contact_phone: str | None = None
    has_logo: bool = False
    updated_at: dt.datetime | None = None
    updated_by_name: str | None = None


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class BrandingUpdate(BaseModel):
    """Every text field the admin form holds. Sent whole: an empty field
    clears the value, so the form and the row cannot drift apart."""

    company_name: str | None = Field(default=None, max_length=200)
    company_line: str | None = Field(default=None, max_length=500)
    legal_text: str | None = Field(default=None, max_length=4000)
    primary_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    contact_phone: str | None = Field(default=None, max_length=50)

    _strip = field_validator(
        "company_name", "company_line", "legal_text", "contact_phone"
    )(_blank_to_none)


class CoverSheetAttachment(BaseModel):
    document_id: uuid.UUID
    filename: str
    kind: str
    included: bool
    #: Why a file of the chosen kinds is left out: "not_pdf" | "unreadable" |
    #: "encrypted". None when it is attached.
    reason: str | None = None


class CoverSheetPreview(BaseModel):
    """What the PDF will hold, before anyone downloads it.

    The UI lists `missing` so the recruiter can complete the record first —
    or send it as it is: empty rows are left off the page, never invented.
    """

    variant: CoverSheetVariant
    title: str
    position: str | None
    #: "mandate" (from the chosen process) | "given" | "current_title" | None.
    position_source: str | None
    #: German section labels with no value, in page order.
    missing: list[str]
    attachments: list[CoverSheetAttachment]
    #: Branding parts the workspace has not set: "logo" | "company_line" |
    #: "legal_text".
    branding_missing: list[str]
