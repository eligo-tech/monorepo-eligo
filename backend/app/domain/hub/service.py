"""Information-hub business logic — ingestion, corpus reads, tenant overlay.

Two layers with different ownership, and the split is the whole design:

  * **The corpus** (`hub_companies`, `hub_job_postings`, `hub_observations`) is
    SHARED. Public facts about the outside world are the same for everyone, so
    they are stored once and crawled once. Ingestion takes no `tenant_id`.
  * **The overlay** (`hub_company_link`) is tenant-scoped like everything else:
    which corpus companies this tenant is watching, and which of their own CRM
    rows each maps to.

Ingestion is deliberately NOT an agent commit path. Agents propose changes to
the system-of-record and must pass `verification.verify_and_commit`; a posting
landing in the corpus asserts nothing about anyone's record and owes no receipt.
The receipt is owed at the crossing — adopting a corpus company into
`companies` — which is what `HubCompanyLink.company_id` marks.

What ingestion does owe is the gate in `gate.py`: preconditions on the fetch,
postconditions per record, and a re-query proving the rows landed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub import gate
from app.domain.hub.adapters.base import SourceAdapter, SourcedPosting, SourceQuery
from app.domain.hub.models import (
    HubCompany,
    HubCompanyLink,
    HubJobPosting,
    HubObservation,
)
from app.domain.hub.resolution import (
    extract_legal_form,
    identity_key,
    normalize_company_name,
    normalize_domain,
)
from app.domain.hub.schemas import IngestRequest, IngestSummary, RejectedRecord

logger = get_logger(__name__)


def _posting_hash(posting: SourcedPosting) -> str:
    """Fingerprint the fields that make a posting materially different.

    `last_seen_at` and the raw payload are excluded on purpose: a re-crawl that
    returns an identical vacancy must be a cheap touch, not a rewrite.
    """
    material = "|".join(
        str(part)
        for part in (
            posting.title,
            posting.description,
            posting.occupation,
            posting.employment_type,
            posting.postal_code,
            posting.city,
            posting.salary_min,
            posting.salary_max,
            posting.posted_at,
            posting.source_url,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def query_key(request: IngestRequest) -> str:
    """Stable fingerprint of a crawl slice — the *question*, not the answer.

    Two callers asking for "Berlin, 25km, page 1, no staffing" produce the same
    key, which is what lets the second one reuse the first one's fetch.
    `page` is part of the key on purpose: page 2 is a different question.
    """
    material = json.dumps(
        {
            "source": request.source,
            "what": (request.what or "").strip().lower() or None,
            "where": (request.where or "").strip().lower() or None,
            "radius_km": request.radius_km,
            "published_since_days": request.published_since_days,
            "page": request.page,
            "size": request.size,
            "include_staffing": request.include_staffing,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _recent_observation(
    session: AsyncSession, *, key: str, max_age_minutes: int
) -> HubObservation | None:
    """The newest successful fetch of this exact slice, if it is still fresh.

    Only a 200 counts: reusing a failed fetch would cache an outage.
    """
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=max_age_minutes)
    return await session.scalar(
        select(HubObservation)
        .where(
            HubObservation.query_key == key,
            HubObservation.http_status == 200,
            HubObservation.fetched_at >= cutoff,
        )
        .order_by(HubObservation.fetched_at.desc())
        .limit(1)
    )


# --------------------------------------------------------------------------
# Ingestion — writes the SHARED corpus, so it takes no tenant
# --------------------------------------------------------------------------


async def ingest(
    session: AsyncSession,
    *,
    adapter: SourceAdapter,
    request: IngestRequest,
) -> IngestSummary:
    """Fetch one slice from a public source and merge it into the shared corpus.

    With `max_age_minutes` set, a recent fetch of the identical slice short-
    circuits the whole thing: no request, no writes, a summary saying so. That
    is what makes a per-user "refresh" button safe — the corpus is shared, so
    the first press does the work and the rest are free.
    """
    key = query_key(request)
    if request.max_age_minutes is not None:
        fresh = await _recent_observation(
            session, key=key, max_age_minutes=request.max_age_minutes
        )
        if fresh is not None:
            # Postgres returns an aware timestamptz; SQLite hands back a naive
            # datetime for the same column. Everything is written as UTC, so
            # re-attach the zone rather than branching on the dialect.
            fetched_at = fresh.fetched_at
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=dt.UTC)
            age = int((dt.datetime.now(dt.UTC) - fetched_at).total_seconds() // 60)
            return IngestSummary(
                source=request.source,
                skipped=True,
                skipped_reason=(
                    f"corpus already current — this slice was fetched "
                    f"{age} minute(s) ago"
                ),
                reused_age_minutes=age,
                observation_id=fresh.id,
                fetched=fresh.record_count,
                total_available=fresh.total_available,
                companies_created=0,
                companies_matched=0,
                postings_created=0,
                postings_updated=0,
                notes=[f"✓ reused observation {str(fresh.id)[:8]} ({age} min old)"],
            )

    query = SourceQuery(
        what=request.what,
        where=request.where,
        radius_km=request.radius_km,
        published_since_days=request.published_since_days,
        page=request.page,
        size=request.size,
        include_staffing=request.include_staffing,
    )
    result = await adapter.fetch(query)

    observation = HubObservation(
        source=result.source,
        query_key=key,
        request_url=result.request_url,
        http_status=result.http_status,
        robots_allowed=result.robots_allowed,
        record_count=len(result.postings),
        total_available=result.total_available,
        content_hash=result.content_hash,
        fetched_at=result.fetched_at,
        note=result.note,
    )
    session.add(observation)
    # Committed BEFORE the gate runs: if a precondition then rejects this fetch,
    # the request rolls back, and the record that we asked and were refused must
    # survive that rollback. A refusal is evidence too.
    await session.commit()

    # --- precondition: is this retrieval usable at all? ------------------
    # Raises PreconditionFailed; the router maps that to 422.
    notes = [outcome.as_note() for outcome in gate.check_fetch(result)]

    now = dt.datetime.now(dt.UTC)
    rejected: list[RejectedRecord] = []
    accepted: list[tuple[SourcedPosting, str, str]] = []  # posting, basis, key

    # --- postcondition: per record --------------------------------------
    for posting in result.postings:
        ok, reason = gate.check_posting(posting, now=now)
        if not ok:
            rejected.append(
                RejectedRecord(
                    external_id=posting.external_id or None,
                    company=posting.company.name or None,
                    reason=reason,
                )
            )
            continue
        identity = identity_key(
            name=posting.company.name,
            website_domain=posting.company.website_domain,
            postal_code=posting.company.postal_code,
            city=posting.company.city,
        )
        if identity is None:  # unreachable via check_posting; never trust that
            rejected.append(
                RejectedRecord(
                    external_id=posting.external_id or None,
                    company=posting.company.name or None,
                    reason="employer identity did not resolve",
                )
            )
            continue
        accepted.append((posting, identity[0], identity[1]))

    # --- merge companies -------------------------------------------------
    # One query for every company in the batch rather than one per posting: a
    # 100-record page touches ~60 distinct employers, most already known.
    dedupe_keys = {key for _, _, key in accepted}
    existing_companies: dict[str, HubCompany] = {}
    if dedupe_keys:
        rows = await session.execute(
            select(HubCompany).where(HubCompany.dedupe_key.in_(dedupe_keys))
        )
        existing_companies = {row.dedupe_key: row for row in rows.scalars().all()}

    company_by_key: dict[str, HubCompany] = dict(existing_companies)

    for posting, basis, key in accepted:
        company = company_by_key.get(key)
        sourced = posting.company
        if company is None:
            company = HubCompany(
                name=sourced.name,
                normalized_name=normalize_company_name(sourced.name),
                legal_form=extract_legal_form(sourced.name),
                dedupe_key=key,
                resolution_basis=basis,
                website_domain=normalize_domain(sourced.website_domain),
                street=sourced.street,
                postal_code=sourced.postal_code,
                city=sourced.city,
                region=sourced.region,
                country=sourced.country,
                latitude=sourced.latitude,
                longitude=sourced.longitude,
                industry=sourced.industry,
                source=result.source,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(company)
            company_by_key[key] = company
        else:
            company.last_seen_at = now
            # Backfill only. An observed value never overwrites one already
            # present — a later verified fact (VAT, register) outranks anything
            # a job board says, and this keeps ingest from trampling it.
            for field, value in (
                ("street", sourced.street),
                ("postal_code", sourced.postal_code),
                ("city", sourced.city),
                ("region", sourced.region),
                ("country", sourced.country),
                ("latitude", sourced.latitude),
                ("longitude", sourced.longitude),
                ("industry", sourced.industry),
            ):
                if getattr(company, field) is None and value is not None:
                    setattr(company, field, value)
            domain = normalize_domain(sourced.website_domain)
            if company.website_domain is None and domain:
                company.website_domain = domain

    # Counted per distinct company, not per posting — one employer with eleven
    # vacancies is one matched company, not eleven.
    companies_matched = len(existing_companies)
    companies_created = len(company_by_key) - companies_matched

    await session.flush()  # assign company ids

    # --- merge postings --------------------------------------------------
    external_ids = {posting.external_id for posting, _, _ in accepted}
    existing_postings: dict[str, HubJobPosting] = {}
    if external_ids:
        rows = await session.execute(
            select(HubJobPosting).where(
                HubJobPosting.source == result.source,
                HubJobPosting.external_id.in_(external_ids),
            )
        )
        existing_postings = {row.external_id: row for row in rows.scalars().all()}

    postings_created = 0
    postings_updated = 0

    for posting, _, key in accepted:
        company = company_by_key[key]
        content_hash = _posting_hash(posting)
        row = existing_postings.get(posting.external_id)

        if row is None:
            session.add(
                HubJobPosting(
                    hub_company_id=company.id,
                    observation_id=observation.id,
                    title=posting.title,
                    description=posting.description,
                    occupation=posting.occupation,
                    employment_type=posting.employment_type,
                    location_text=posting.location_text,
                    postal_code=posting.postal_code,
                    city=posting.city,
                    country=posting.country,
                    latitude=posting.latitude,
                    longitude=posting.longitude,
                    remote_possible=posting.remote_possible,
                    salary_min=posting.salary_min,
                    salary_max=posting.salary_max,
                    salary_currency=posting.salary_currency,
                    posted_at=posting.posted_at,
                    expires_at=posting.expires_at,
                    source=result.source,
                    source_url=posting.source_url,
                    external_id=posting.external_id,
                    content_hash=content_hash,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                    raw=posting.raw,
                )
            )
            postings_created += 1
            continue

        # Seen before: a touch when nothing changed, a rewrite when it did.
        row.last_seen_at = now
        row.is_active = True
        row.observation_id = observation.id
        if row.content_hash != content_hash:
            row.title = posting.title
            row.description = posting.description
            row.occupation = posting.occupation
            row.employment_type = posting.employment_type
            row.location_text = posting.location_text
            row.postal_code = posting.postal_code
            row.city = posting.city
            row.latitude = posting.latitude
            row.longitude = posting.longitude
            row.remote_possible = posting.remote_possible
            row.salary_min = posting.salary_min
            row.salary_max = posting.salary_max
            row.posted_at = posting.posted_at
            row.source_url = posting.source_url
            row.content_hash = content_hash
            row.raw = posting.raw
        postings_updated += 1

    await session.flush()

    # --- recompute the BD signal for every company this slice touched ----
    touched = [company.id for company in company_by_key.values()]
    if touched:
        counts = await session.execute(
            select(HubJobPosting.hub_company_id, func.count(HubJobPosting.id))
            .where(
                HubJobPosting.hub_company_id.in_(touched),
                HubJobPosting.is_active.is_(True),
            )
            .group_by(HubJobPosting.hub_company_id)
        )
        open_counts = dict(counts.all())
        for company in company_by_key.values():
            company.open_postings_count = open_counts.get(company.id, 0)

    await session.commit()

    # --- postcondition: prove the rows are actually in the database ------
    # Re-queried after commit, not inferred from the ORM's bookkeeping.
    observed = await session.scalar(
        select(func.count(HubJobPosting.id)).where(
            HubJobPosting.source == result.source,
            HubJobPosting.external_id.in_(external_ids or {""}),
        )
    )
    landed = gate.check_persisted(expected=len(accepted), observed=observed or 0)
    notes.append(landed.as_note())
    if rejected:
        notes.append(f"✗ {len(rejected)} record(s) rejected by postconditions")

    logger.info(
        "hub ingest source=%s fetched=%d companies=+%d/~%d postings=+%d/~%d rejected=%d",
        result.source,
        len(result.postings),
        companies_created,
        companies_matched,
        postings_created,
        postings_updated,
        len(rejected),
    )

    return IngestSummary(
        source=result.source,
        observation_id=observation.id,
        fetched=len(result.postings),
        total_available=result.total_available,
        companies_created=companies_created,
        companies_matched=companies_matched,
        postings_created=postings_created,
        postings_updated=postings_updated,
        rejected=rejected,
        notes=notes,
    )


# --------------------------------------------------------------------------
# Corpus reads — shared, so no tenant filter
# --------------------------------------------------------------------------


def _paginate(stmt: Select, *, limit: int, offset: int) -> Select:
    return stmt.limit(limit).offset(offset)


async def list_companies(
    session: AsyncSession,
    *,
    q: str | None = None,
    city: str | None = None,
    hiring_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[HubCompany]:
    """Corpus companies, most actively hiring first.

    That ordering is the point of the hub: a recruiter wants whoever has the most
    open roles right now, not an alphabetical register extract.
    """
    stmt = select(HubCompany)
    if q:
        needle = f"%{normalize_company_name(q) or q.lower()}%"
        stmt = stmt.where(
            or_(
                HubCompany.normalized_name.like(needle),
                func.lower(HubCompany.name).like(f"%{q.lower()}%"),
            )
        )
    if city:
        stmt = stmt.where(func.lower(HubCompany.city) == city.lower())
    if hiring_only:
        stmt = stmt.where(HubCompany.open_postings_count > 0)
    stmt = stmt.order_by(HubCompany.open_postings_count.desc(), HubCompany.name)
    rows = await session.execute(_paginate(stmt, limit=limit, offset=offset))
    return list(rows.scalars().all())


async def count_companies(session: AsyncSession) -> int:
    return (await session.scalar(select(func.count(HubCompany.id)))) or 0


async def get_company(
    session: AsyncSession, *, hub_company_id: uuid.UUID
) -> HubCompany | None:
    return await session.scalar(
        select(HubCompany).where(HubCompany.id == hub_company_id)
    )


async def list_postings(
    session: AsyncSession,
    *,
    hub_company_id: uuid.UUID | None = None,
    q: str | None = None,
    city: str | None = None,
    source: str | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[HubJobPosting]:
    stmt = select(HubJobPosting)
    if hub_company_id is not None:
        stmt = stmt.where(HubJobPosting.hub_company_id == hub_company_id)
    if q:
        stmt = stmt.where(func.lower(HubJobPosting.title).like(f"%{q.lower()}%"))
    if city:
        stmt = stmt.where(func.lower(HubJobPosting.city) == city.lower())
    if source:
        stmt = stmt.where(HubJobPosting.source == source)
    if active_only:
        stmt = stmt.where(HubJobPosting.is_active.is_(True))
    stmt = stmt.order_by(
        HubJobPosting.posted_at.desc().nulls_last(), HubJobPosting.title
    )
    rows = await session.execute(_paginate(stmt, limit=limit, offset=offset))
    return list(rows.scalars().all())


async def list_observations(
    session: AsyncSession, *, limit: int = 50
) -> list[HubObservation]:
    """The evidence ledger the corpus was built from, newest fetch first."""
    rows = await session.execute(
        select(HubObservation).order_by(HubObservation.fetched_at.desc()).limit(limit)
    )
    return list(rows.scalars().all())


# --------------------------------------------------------------------------
# Tenant overlay — this is where tenant_id (and the JWT) actually matter
# --------------------------------------------------------------------------


async def track_company(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    hub_company_id: uuid.UUID,
    relationship: str = "watching",
    note: str | None = None,
) -> HubCompanyLink:
    """Record (or update) this tenant's interest in a corpus company.

    Tracking asserts nothing about the system-of-record, so it leaves no receipt.
    Adoption — pointing ``company_id`` at one of the tenant's own CRM rows — is
    the crossing that does, and it goes through the verification gate.
    """
    link = await session.scalar(
        select(HubCompanyLink).where(
            HubCompanyLink.tenant_id == tenant_id,
            HubCompanyLink.hub_company_id == hub_company_id,
        )
    )
    if link is None:
        link = HubCompanyLink(
            tenant_id=tenant_id,
            hub_company_id=hub_company_id,
            relationship=relationship,
            note=note,
        )
        session.add(link)
    else:
        link.relationship = relationship
        if note is not None:
            link.note = note
    await session.commit()
    await session.refresh(link)
    return link


async def untrack_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, hub_company_id: uuid.UUID
) -> bool:
    link = await session.scalar(
        select(HubCompanyLink).where(
            HubCompanyLink.tenant_id == tenant_id,
            HubCompanyLink.hub_company_id == hub_company_id,
        )
    )
    if link is None:
        return False
    await session.delete(link)
    await session.commit()
    return True


async def list_links(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    relationship: str | None = None,
    limit: int = 200,
) -> list[HubCompanyLink]:
    stmt = select(HubCompanyLink).where(HubCompanyLink.tenant_id == tenant_id)
    if relationship:
        stmt = stmt.where(HubCompanyLink.relationship == relationship)
    rows = await session.execute(stmt.limit(limit))
    return list(rows.scalars().all())


async def tracked_company_ids(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> set[uuid.UUID]:
    """Corpus company ids this tenant has an overlay row for.

    Lets a corpus listing be annotated with the tenant's own view in one extra
    query, without pushing tenant_id back into the shared tables.
    """
    rows = await session.execute(
        select(HubCompanyLink.hub_company_id).where(
            HubCompanyLink.tenant_id == tenant_id
        )
    )
    return set(rows.scalars().all())
