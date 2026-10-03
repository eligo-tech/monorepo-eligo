"""Wire contracts for a workspace's own sources."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class TenantSourceRead(BaseModel):
    """What a workspace may see about its own source.

    The secret is absent by construction — not masked, not truncated. A value
    the API never emits cannot leak through a log, a screenshot or a browser
    cache. `has_secret` is all the UI needs to know.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    label: str | None
    username: str
    status: str
    has_secret: bool
    import_requested_at: dt.datetime | None
    last_run_at: dt.datetime | None
    last_result: dict
    last_error: str | None


class TenantSourceWrite(BaseModel):
    """Configure (or re-configure) a source.

    `secret` is optional on an update so a recruiter can fix a typo in the
    label or the username without re-typing the password.
    """

    username: str = Field(min_length=3, max_length=255)
    secret: str | None = Field(default=None, min_length=1, max_length=512)
    label: str | None = Field(default=None, max_length=160)
    status: str | None = None


class ImportRequestRead(BaseModel):
    """The answer to "import my data now"."""

    queued: bool
    #: When the job will pick it up, in words — the UI shows this verbatim.
    detail: str
