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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONBDict, JSONDict, JSONList

# Which kind of advertiser a corpus row is. Stamped at ingest from the QUERY
# that returned it — the source's listing records carry no flag of their own.
#: An end employer. Every recruiter-facing view shows only these.
EMPLOYER = "employer"
#: A private recruiting agency (Bundesagentur `pav=true`): a LEAD for Eligo's
#: own sales (the agency finder), a competitor to every customer.
PRIVATE_RECRUITER = "private_recruiter"
SEGMENTS = (EMPLOYER, PRIVATE_RECRUITER)


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

    payload: Mapped[dict] = mapped_column(JSONBDict, default=dict, nullable=False)


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
    # today. That is public data and allowed (RULE 2: persons as a public
    # source published them), but it must stay findable for the suppression
    # list, and no check over column NAMES can catch a person sitting in a
    # column called `name`.
    #
    # A SCREEN, not a verdict (`resolution.looks_like_natural_person`), tuned to
    # over-include: a false positive costs a visible flag, a false negative
    # leaves a person the suppression list cannot find. It hides and
    # deletes nothing by itself — §2.2's rule that a fuzzy judgement may surface
    # something for a human but never decide it. Acting on the flag (suppression,
    # Art. 14/17) is the next step.
    suspected_natural_person: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # --- corpus bookkeeping ----------------------------------------------
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    # EMPLOYER or PRIVATE_RECRUITER. Agencies resolve in their own identity
    # namespace (`dedupe_key` prefixed "pav:"), because a pav ad's `firma` is
    # sometimes the client — so an agency's ad can never attach to, or count
    # towards, an employer row, and every posting shares its company's kind.
    kind: Mapped[str] = mapped_column(
        String(30), default=EMPLOYER, server_default=EMPLOYER, nullable=False, index=True
    )
    # Denormalized BD signal: how many of this company's postings are still open.
    # Maintained on ingest so the "who is hiring hardest" list is a plain query.
    open_postings_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    bd_signals: Mapped[dict] = mapped_column(JSONBDict, default=dict, nullable=False)

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
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class HubJobPosting(Base, IDMixin, TimestampMixin):
    """One external job posting — a market signal, never a client mandate."""

    __tablename__ = "hub_job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_hub_posting_source_id"),
        Index("ix_hub_posting_company_active", "hub_company_id", "is_active"),
        # The liveness checker's queue: open suspects by due date. Partial, so
        # it holds only the queue; the checker filters on bare `is_active`
        # (not `IS true`) so the planner can prove the predicate and use it.
        # `id` is in the key so `ORDER BY check_due_at, id LIMIT n` is an index
        # walk that stops at n: a weekly listing queues 250k ads at ONE
        # timestamp, and without the tiebreak in the index every batch would
        # read and sort all of them (measured on 650k rows).
        Index(
            "ix_hub_posting_check_due",
            "check_due_at",
            "id",
            postgresql_where=text("is_active AND check_due_at IS NOT NULL"),
            sqlite_where=text("is_active AND check_due_at IS NOT NULL"),
        ),
        # The vacancy-key backfill's queue: open ads still without a key. Empty
        # once the backlog is done; new ads are keyed at ingest.
        Index(
            "ix_hub_posting_unkeyed",
            "id",
            postgresql_where=text("is_active AND vacancy_key IS NULL"),
            sqlite_where=text("is_active AND vacancy_key IS NULL"),
        ),
    )

    hub_company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("hub_companies.id"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hub_observations.id"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
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
    # Always equal to the company's `kind`. Denormalized because the search
    # predicates are deliberately single-table (see `service._companies_matching`):
    # filtering postings through a join to companies would cost the indexes.
    segment: Mapped[str] = mapped_column(
        String(30), default=EMPLOYER, server_default=EMPLOYER, nullable=False
    )

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

    # The same "attempted" marker for the partner-board page behind
    # `source_url` (adapters/partner_pages.py), for the same reason: a page that
    # 404s or sits behind a bot check yields no text, and selecting on the text
    # alone would pick it again every night. `source_page_status` is the HTTP
    # code, or 0 skipped host / 1 robots.txt / 2 network error.
    source_page_fetched_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    source_page_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Liveness (`hub/liveness.py`). A delta crawl never re-lists an old ad, so
    # absence over time proves nothing; these three record what DOES:
    #   unlisted_at     — first missing from a weekly full listing: a SUSPECT,
    #                     not a verdict (the listing reaches ~82% of the source)
    #   live_checked_at — the ad's own detail page last answered 200
    #   closed_at       — the source said "not found": it took the ad down
    #   check_due_at    — the queue: when to ask next (NULL = not queued)
    unlisted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    live_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # One vacancy across relays and sources (`hub/vacancy.py`): employer +
    # normalized title + place. Counts and lists group by it; NULL until the
    # nightly backfill reaches the row, and such an ad counts as itself.
    vacancy_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
    # `raw` and `description` live in HubPostingPayload, not here — see that
    # class for why. `payload` is selectin-loaded: one extra query per result
    # set rather than one per row, and the DTO's `description` reads through it.
    payload: Mapped["HubPostingPayload | None"] = relationship(
        "HubPostingPayload",
        back_populates="posting",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def description(self) -> str | None:
        """Read-through so `HubJobPostingRead.from_attributes` still works.

        Writers must go through `payload.description`; this is deliberately
        read-only so a write cannot silently land on a detached attribute.
        """
        return self.payload.description if self.payload else None


class HubPostingPayload(Base, TimestampMixin):
    """The COLD half of a posting: bulk text nobody scans.

    Split out for cache residency, not for tidiness. `hub_job_postings` carries
    the columns search actually reads — title, occupation, city, dates, foreign
    keys — and every sequential scan pays for the width of that table. With
    `raw` and `description` inline the main heap measured **298 MB** against a
    224 MB `shared_buffers`, so scans spilled to disk on every search. Without
    them the hot rows are a few hundred bytes each and the table fits in cache.

    Postgres already TOASTs the largest values out of line (208 MB of the 596 MB
    total), which is why this is a smaller win than the column sizes suggest —
    but the *inline* remainder was still most of the main heap.

    `raw` is the archived source record, kept for provenance and read by nothing
    in the codebase. `description` is the ad body, displayed in the UI and
    searched only when `SEARCH_AD_TEXT` is on.

    Shared corpus, so no `tenant_id` — same deliberate exception as the tables
    it hangs off (see CLAUDE.md §2.6).
    """

    __tablename__ = "hub_posting_payload"

    hub_job_posting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("hub_job_postings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Readable text of the partner-board page `source_url` points at — where
    #: the contact block often is when the BA text gives only `bewerbung@`.
    #: Public, as published (ARCHITECTURE.md RULE 2), with its fetch recorded
    #: in `source_page_observation_id`.
    source_page_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Where the fetch actually landed after redirects — the URL the evidence
    #: is shown with.
    source_page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_page_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hub_observations.id"), nullable=True
    )

    posting: Mapped["HubJobPosting"] = relationship(
        "HubJobPosting", back_populates="payload"
    )


#: What a suppression covers.
SUPPRESS_COMPANY = "company"  # every row of that normalized name, every kind
SUPPRESS_PERSON = "person"  # that full name, in every stored ad text
SUPPRESSION_SCOPES = (SUPPRESS_COMPANY, SUPPRESS_PERSON)
#: Why. Erasure = GDPR Art. 17, objection = Art. 21, legal = any other duty.
SUPPRESSION_REASONS = ("erasure", "objection", "legal")


class HubSuppression(Base, IDMixin, TimestampMixin):
    """The opt-out list: who the corpus must never hold again.

    A DELETE alone does not erase anything here — the corpus re-ingests every
    night and the source still publishes the record. This row is the tombstone
    that every write into the corpus checks (`suppression.py`).

    `key` is deliberately the minimum needed to recognise the record again: the
    normalized company name, or the folded full name ("katrin wolter"). No
    address, no reason text, no requester contact — those belong in the
    request log outside this database.

    Shared like the corpus it guards — no `tenant_id`. Readable by the app role,
    writable only by the owner connection (`scripts/hub_suppress.py`); the
    migration enforces that with a SELECT-only policy.
    """

    __tablename__ = "hub_suppressions"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_hub_suppression_scope_key"),)

    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)


class HubAgencyProfile(Base, IDMixin, TimestampMixin):
    """One private-recruiting agency, as the agency finder ranks it.

    DERIVED, not observed: rebuilt in full by the nightly job
    (`POST /hub/agencies/refresh`, machine-only) from the `private_recruiter`
    corpus rows — every branch of one agency folded into one profile
    (`agency_rank.group_key`). Reads are a plain select; the heavy part (every
    agency ad text) runs in the cron, not in a request (ARCHITECTURE.md RULE 1:
    a cron writes, presentation reads).

    `reasons` holds the verdict's and the score's evidence: counts, posting
    ids, company mail domains. Contact names stay in the ad texts, where the
    opt-out list redacts them; `name` can be a sole trader's trading name, as
    the corpus holds it, and goes with the company on a company opt-out.

    Shared corpus, no tenant_id; visible only to workspaces on the
    `agency_finder_tenants` allowlist. `company_ids` is a plain list rather
    than a foreign key so that the opt-out list can delete a company without
    touching this table; reads re-check that the companies still exist.
    """

    __tablename__ = "hub_agency_profiles"

    group_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    primary_company_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    company_ids: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    open_postings: Mapped[int] = mapped_column(Integer, nullable=False)
    new_28d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: berufsfeld → open postings, for the field filter and the mix.
    fields: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: The agency's likely website, from its own ads — UNVERIFIED candidates
    #: (`domains.py`), best first, each with its example ads. Never copied to
    #: `hub_companies.website_domain`: only the Impressum naming the firm does.
    website_candidates: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    refreshed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


#: Outcomes of checking one website candidate through its Impressum.
SITE_VERIFIED = "verified"  # the Impressum names the agency as operator
SITE_NOT_NAMED = "not_named"  # an Impressum, but someone else's
SITE_NO_IMPRESSUM = "no_impressum"  # no readable Impressum found
SITE_BLOCKED = "blocked"  # robots.txt, or an unsafe link/redirect
SITE_ERROR = "error"  # network failure — retried after a week
SITE_STATUSES = (SITE_VERIFIED, SITE_NOT_NAMED, SITE_NO_IMPRESSUM, SITE_BLOCKED, SITE_ERROR)


class HubSiteCheck(Base, IDMixin, TimestampMixin):
    """One check of one website candidate against its Impressum.

    Persistent where `HubAgencyProfile` is rebuilt: a domain is fetched once,
    not every night, and a rejected one is not tried again. Holds COMPANY facts
    only (decision 2026-11-04, option A): register, VAT, a company phone and
    function mailboxes as the Impressum publishes them. People named there are
    not stored until the GDPR Art. 14 question is answered.

    Shared corpus, no tenant_id; the fetch is a `hub_observations` row.
    """

    __tablename__ = "hub_site_checks"
    #: Per agency: a domain one agency's ad names may be another agency's own
    #: site — "not_named" for the first must not stop the second verifying it.
    __table_args__ = (UniqueConstraint("domain", "group_key", name="uq_hub_site_check_domain_group"),)

    domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    group_key: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    impressum_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("hub_observations.id"), nullable=True
    )
    #: vat_id, register, register_court, phone, emails — as published.
    facts: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HubAtsBoard(Base, IDMixin, TimestampMixin):
    """One employer's public job board on an applicant-tracking system.

    Personio, Ashby, Greenhouse, Lever and Lever's EU instance (`ats` names the
    system: personio · ashby · greenhouse · lever · lever-eu; `hub/ats.py`). Each company that switches on Personio's job feed
    publishes `{slug}.jobs.personio.de/xml`; an Ashby company's jobs are at
    `api.ashbyhq.com/posting-api/job-board/{slug}`. The board is
    the employer's own source — full text, its own offices — and the feed is a
    full snapshot, so a job missing from it is closed (`hub/ats.py`).

    Boards are DISCOVERED by a scheduled job (`scripts/hub_ats.py --discover`,
    from Common Crawl's URL index), never by a user (RULE 1). Shared corpus, no
    tenant_id.

    `offices` caches each office's postal address, read once from one job
    page (its `office_addresses` app data, schema.org as a fallback; an
    office with none is retried weekly): the feed names an office ("Berlin") but no
    postcode, and the postcode is what makes BA's copy of the same job one
    vacancy. `open_ids` is the last snapshot, the base for the next diff.
    """

    __tablename__ = "hub_ats_boards"
    __table_args__ = (UniqueConstraint("ats", "slug", name="uq_hub_ats_board"),)

    ats: Mapped[str] = mapped_column(String(30), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    #: new · active (DACH jobs) · elsewhere (jobs, none in DACH) · empty · gone · failing
    #: · unnamed (DACH jobs, but the board page gave no company name — asked weekly)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    company_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    discovered_via: Mapped[str] = mapped_column(String(60), nullable=False)
    offices: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)
    open_ids: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    jobs_listed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_dach: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Consecutive empty snapshots; one alone never closes anything.
    empty_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_fetch_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
