"""Wire contracts for proposals as the Eligo UI reads them."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel


class ProposalRead(BaseModel):
    """One proposal for the person deciding: what it changes, from what, and why."""

    id: uuid.UUID
    kind: str
    #: pending · confirmed · declined · stale · expired
    status: str
    title: str
    tool: str
    #: The state the AI client saw when it proposed.
    before: dict[str, Any]
    #: What confirming applies.
    after: dict[str, Any]
    reason: str | None
    asked_by_name: str | None
    client_id: str | None
    created_at: dt.datetime
    expires_at: dt.datetime
    decided_by_name: str | None
    decided_at: dt.datetime | None
