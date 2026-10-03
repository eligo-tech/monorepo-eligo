"""Wire contracts for the file import."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class EntityFieldRead(BaseModel):
    name: str
    label: str
    required: bool


class EntityRead(BaseModel):
    """One importable kind of thing, and what it can hold."""

    key: str
    label: str
    hint: str
    fields: list[EntityFieldRead]


class RowPlanRead(BaseModel):
    line: int
    #: "create" | "update" | "skip"
    action: str
    reason: str | None = None
    #: The row as it would land — shown so a wrong mapping is visible BEFORE
    #: anything is written, which is the point of the preview.
    values: dict


class PreviewRead(BaseModel):
    entity: str
    #: How the file was read ("CSV · Trennzeichen „;“ · cp1252").
    note: str
    columns: list[str]
    #: Column → canonical field. A suggestion; the UI lets it be corrected.
    mapping: dict[str, str]
    row_count: int
    counts: dict[str, int]
    sample: list[RowPlanRead]
    problems: list[str] = Field(default_factory=list)


class ImportResultRead(BaseModel):
    created: int
    updated: int
    skipped: int
    problems: list[str] = Field(default_factory=list)


class CommitRequest(BaseModel):
    """Sent alongside the file on commit, as JSON in a form field."""

    entity: str
    mapping: dict[str, str]
    tenant_id: uuid.UUID | None = None
