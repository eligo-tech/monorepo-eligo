"""The ATS seam: a recruiter's own system → neutral records this product stores.

Mirrors `hub/adapters` and `documents/extraction`, and for the same reason:
callers depend on the PROTOCOL, never on a vendor. The first integration
happened to be aiFind, and for a while its name was spread through the
importer, the runner, the credential store and the settings screen — which
made "the ATS" and "aiFind" the same word in the codebase. They are not. One
is a seam this product keeps; the other is a system a customer happens to use
today and will leave tomorrow.

Every connector splits in two, like the hub's adapters:

  * ``fetch`` — does I/O and returns an ``AtsExport``.
  * the parsers — PURE functions from a captured payload to records.

That split is what lets CI exercise a real vendor's mapping against a stored
response with no credentials and no network.

The records below are deliberately the plain shape of a recruiting CRM —
company, contact, mandate, candidate — not any vendor's. A connector's job is
to express its own system in these terms; nothing downstream should ever be
able to tell which system a row came from except by reading its `source`.
"""

from __future__ import annotations

import dataclasses
from typing import Literal, Protocol, runtime_checkable


@dataclasses.dataclass(frozen=True)
class SourcedNote:
    """One dated entry from a contact history — the relationship itself."""

    external_id: str
    category: str | None
    text: str
    created_at: str | None


@dataclasses.dataclass(frozen=True)
class SourcedCompany:
    """A client account as the source holds it."""

    external_id: str
    name: str


@dataclasses.dataclass(frozen=True)
class SourcedManager:
    """A contact person at a client.

    Everything after `company_external_id` is typically a DETAIL call: list
    screens rarely carry phone numbers, skills or notes, and the detail pass
    is both the slow half of an import and the half worth running.
    """

    external_id: str
    full_name: str
    job_title: str | None = None
    company_external_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department: str | None = None
    industry: str | None = None
    sex: str | None = None
    email: str | None = None
    phone: str | None = None
    code: str | None = None
    looks_for: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    last_contact_at: str | None = None
    linkedin_url: str | None = None
    xing_url: str | None = None
    facebook_url: str | None = None
    skills: list[str] = dataclasses.field(default_factory=list)
    tags: list[str] = dataclasses.field(default_factory=list)
    notes: list[SourcedNote] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class SourcedCandidate:
    """A person in the recruiter's own pool.

    `skills` is the field that decides whether the import was worth running: a
    hard filter cannot filter on a job title.
    """

    external_id: str
    full_name: str
    job_title: str | None = None
    employment: str | None = None
    postal_code: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    sex: str | None = None
    name_prefix: str | None = None
    date_of_birth: str | None = None
    email: str | None = None
    xing_url: str | None = None
    current_company: str | None = None
    industry: str | None = None
    street: str | None = None
    city: str | None = None
    country: str | None = None
    skills: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class SourcedJob:
    """One mandate. Company and manager are optional BY TYPE.

    A mandate logged before the client contact is known is an ordinary state
    in a CRM, and an importer that assumes otherwise breaks on the first one.
    """

    external_id: str
    title: str
    is_open: bool
    priority: str | None = None
    employment: str | None = None
    company: SourcedCompany | None = None
    manager: SourcedManager | None = None
    owner: str | None = None


@dataclasses.dataclass
class AtsExport:
    """Everything one connector could read for one account."""

    companies: list[SourcedCompany] = dataclasses.field(default_factory=list)
    managers: list[SourcedManager] = dataclasses.field(default_factory=list)
    jobs: list[SourcedJob] = dataclasses.field(default_factory=list)
    candidates: list[SourcedCandidate] = dataclasses.field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "companies": len(self.companies),
            "managers": len(self.managers),
            "jobs": len(self.jobs),
            "candidates": len(self.candidates),
        }


@dataclasses.dataclass(frozen=True)
class Credentials:
    """What a workspace stored for one source.

    Two fields cover both shapes seen so far: a login (user + password) and a
    token (`secret` alone). A connector states which it needs through
    `needs`, so the settings form can ask for exactly that and no more.
    """

    username: str | None = None
    secret: str | None = None


#: How a source is read, which decides who may start it.
#:
#: "pull"  — the product logs in and reads on a SCHEDULE. Machine-triggered
#:           ingestion (ARCHITECTURE.md RULE 1): no user may start it.
#: "file"  — a human uploads an export they already have. Not ingestion at
#:           all: the data arrives with the request, nothing is crawled, and
#:           the person doing it is the one who owns the file.
#:
#: The distinction is not cosmetic. It decides whether a credential can be
#: stored for the source, whether the scheduled runner may pick it up, and
#: which control the settings screen draws.
Mode = Literal["pull", "file"]


@runtime_checkable
class AtsSource(Protocol):
    """One system this product can take a book of business from."""

    #: Stable identifier, written to every imported row as `source`, so it
    #: must not change once a workspace has used it.
    key: str
    #: What a human sees in the settings screen.
    label: str
    #: One line saying what it is, shown under the label.
    hint: str
    mode: Mode


@runtime_checkable
class AtsConnector(AtsSource, Protocol):
    """A source the product READS on a schedule, with stored credentials."""

    #: Which credential fields the form must ask for: "username", "secret".
    needs: tuple[str, ...]

    async def fetch(
        self, credentials: Credentials, *, with_details: bool = True
    ) -> AtsExport:
        """Read the account. `with_details=False` skips the slow per-row pass."""
        ...
