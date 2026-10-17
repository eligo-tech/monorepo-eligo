"""Wire contracts for gated features."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class FeatureStatus(BaseModel):
    key: str
    label: str
    #: The operator side is open: global switch on, workspace allowlisted.
    available: bool
    #: Available AND a workspace admin accepted the current terms.
    enabled: bool
    #: Why it is not enabled, in words the settings screen can show.
    reason: str | None = None
    terms_version: str
    terms: str
    accepted_by: str | None = None
    accepted_at: dt.datetime | None = None


class FeatureConsentWrite(BaseModel):
    #: Must equal the current terms version: the admin accepts the text they
    #: were shown, not whatever the server holds by the time they click.
    terms_version: str
