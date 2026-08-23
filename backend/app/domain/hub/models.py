"""Information-hub ORM models — the company/job corpus and its evidence.

Three tables, one job each:

``HubObservation``
    One *fetch*: we asked a source for something at a point in time and this is
    what came back. Append-only. Every posting links to the observation that
    produced it, so any claim the corpus makes is traceable to a retrieval —
    the "every displayed claim is evidence-backed" invariant, applied to layer 1.

``HubCompany``
    The canonical company. Identity is decided by the deterministic ladder in
    ``resolution.py`` (VAT → register → domain → name+PLZ); ``resolution_basis``
    records *which* rung matched, so a weak identity is visible rather than
    implied.

``HubJobPosting``
    One external posting. Deliberately NOT ``jobs.Job``: a ``Job`` is a client
    mandate that drives ``matching.apply_hard_filters`` and the pipeline. A hub
    posting is a market signal. Promotion of a posting into a real mandate is an
    explicit human action, so market noise can never reach the matcher.

**These three tables are SHARED, not tenant-scoped** — a deliberate, documented
exception to "every core row carries a tenant_id" (§2.3). "bayoonet AG is at
10115 Berlin and has three open roles" is a public fact, identical for every
tenant; storing it per tenant would mean N copies of one truth and N crawls of
one source. They are reference data, like a skills taxonomy — not the
system-of-record, which stays strictly tenant-scoped.

The tenant boundary lives in ``HubCompanyLink``: which corpus companies THIS
tenant cares about, and which of their own CRM rows each maps to. That table
carries ``tenant_id`` and is RLS-isolated exactly like everything else.

    hub_companies / hub_job_postings / hub_observations   shared public facts
                            ↓
    hub_company_link (tenant_id)        ← this tenant's interest
    companies → jobs (tenant_id)        ← this tenant's business
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict


class HubObservation(Base, IDMixin, TimestampMixin):
    """One retrieval from a public source. Append-only evidence anchor.

    Stores the *request* and its outcome, not the full body: the per-record
    payload lives on each posting (``HubJobPosting.raw``), so keeping the whole
    response here too would duplicate it a hundredfold. ``payload`` is reserved
    for small single-document fetches (an Impressum page, a registry lookup)
    where the body itself is the evidence.
    """

    __tablename__ = "hub_observations"

    source: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    request_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Stable fingerprint of the *query* (source + filters + page), as opposed to
    # `content_hash` which fingerprints the response. Lets a later caller ask
    # "has anyone already fetched this exact slice recently?" and skip the
    # network — the reason one workspace's refresh serves all of them.
    query_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Compliance gate: recorded per fetch so a refusal is auditable, not silent.
    robots_allowed: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Total the source says exist for this query (BA: `maxErgebnisse`) — lets a
    # crawler know how much it has NOT yet seen.
    total_available: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # SHA-256 over the normalized response — unchanged hash ⇒ nothing to re-parse.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    payload: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)


class HubCompany(Base, IDMixin, TimestampMixin):
    """A company observed in the wild, deduplicated by deterministic identity."""

    __tablename__ = "hub_companies"
    __table_args__ = (
        # One company, one row, corpus-wide. The whole point of a shared basis.
        UniqueConstraint("dedupe_key", name="uq_hub_company_identity"),
        Index("ix_hub_company_normalized_name", "normalized_name"),
    )

    # --- identity -------------------------------------------------------
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Blocking key: casefolded, umlaut-folded, legal form stripped. Two spellings
    # of one employer ("ARC-GREENLAB GmbH" / "ARC-Greenlab GmbH") collapse here.
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    legal_form: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # The key that actually decided this row's identity, and which rung of the
    # ladder produced it ("vat" | "register" | "domain" | "name_place").
    dedupe_key: Mapped[str] = mapped_column(String(400), nullable=False)
    resolution_basis: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- contact / location ---------------------------------------------
    website_domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- registry facts (populated later by the profile agent, verified) ----
    register_court: Mapped[str | None] = mapped_column(String(120), nullable=True)
    register_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    vat_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    vat_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # A sole trader (Einzelunternehmen, Freiberufler) often trades under their
    # own name, so THIS ROW's `name` can itself be personal data even though
    # every column here is company-shaped — "Andreas Uwe Weiss" is in the corpus
    # today. RULE 2 says the shared corpus holds no natural persons; that rule
    # was unenforceable because no check over column NAMES can catch a person
    # sitting in a column called `name`.
    #
    # A SCREEN, not a verdict (`resolution.looks_like_natural_person`), tuned to
    # over-include: a false positive costs a visible flag, a false negative
    # silently keeps personal data in a shared cross-tenant table. It hides and
    # deletes nothing by itself — §2.2's rule that a fuzzy judgement may surface
    # something for a human but never decide it. Acting on the flag (suppression,
    # Art. 14/17) is the next step.
    suspected_natural_person: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # --- corpus bookkeeping ----------------------------------------------
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    # Denormalized BD signal: how many of this company's postings are still open.
    # Maintained on ingest so the "who is hiring hardest" list is a plain query.
    open_postings_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    bd_signals: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)

    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class HubCompanyLink(Base, IDMixin, TenantMixin, TimestampMixin):
    """One tenant's relationship to one corpus company — the tenant boundary.

    The corpus says what is true of the world; this says what it means to *you*:
    that you are watching this company, that it is a prospect, and which of your
    own ``companies`` rows it corresponds to once adopted.

    Adoption (setting ``company_id``) is the corpus→record crossing and goes
    through ``verify_and_commit``, so it leaves a receipt. Merely tracking a
    company does not: noting interest asserts nothing about the record.
    """

    __tablename__ = "hub_company_link"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "hub_company_id", name="uq_hub_link_tenant_company"
        ),
    )

    hub_company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hub_companies.id"), nullable=False, index=True
    )
    # The tenant's own CRM row, once this corpus company has been adopted.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("companies.id"), nullable=True, index=True
    )
    # "watching" | "prospect" | "client" | "ignored"
    relationship: Mapped[str] = mapped_column(
        String(20), default="watching", nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class HubJobPosting(Base, IDMixin, TimestampMixin):
    """One external job posting — a market signal, never a client mandate."""

    __tablename__ = "hub_job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_hub_posting_source_id"),
        Index("ix_hub_posting_company_active", "hub_company_id", "is_active"),
    )

    hub_company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hub_companies.id"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hub_observations.id"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The source's own occupation taxonomy label (BA: `hauptberuf`).
    occupation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The coarser occupational FIELD (BA: `berufsfeld`, 144 values).
    #
    # Absent from every record the source returns — it exists only in the query
    # facets. We know it only because the crawler asked for it: a posting
    # fetched by a berufsfeld shard is stamped with that shard's field. Postings
    # pulled by a regional sweep or a saved-search keyword slice have none, so
    # this is nullable by nature, not by oversight.
    berufsfeld: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    # Bundesland, from the record's own address — reliable, unlike the `wo=`
    # QUERY parameter, which matches place names and returns 82 postings for
    # the whole of Hessen. Accurate to filter on; useless to shard on.
    region: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)

    location_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    remote_possible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    posted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)

    # When the ad text was last REQUESTED — set whether or not text came back.
    #
    # Selecting work by `description IS NULL` alone is an infinite loop: a
    # posting the source 404s has no text to store, stays NULL, and is chosen
    # again on the very next batch. That is not hypothetical — a production run
    # re-fetched the same 25 references every few seconds until it was killed.
    # Recording the ATTEMPT is what makes the pass terminate.
    description_fetched_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # SHA-256 of the meaningful fields — an unchanged posting only bumps
    # `last_seen_at` instead of rewriting the row.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Flipped false when a crawl no longer sees it — itself a BD signal
    # ("filled" or "pulled"), which is why postings are never hard-deleted.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # The source's own record, kept verbatim for grounding checks downstream.
    raw: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
