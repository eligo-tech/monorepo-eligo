"""Information-hub business logic — ingestion and corpus reads.

Ingestion is deliberately *not* an agent commit path. Agents propose changes to
the system-of-record and must pass `verification.verify_and_commit`; the hub is
a corpus of observed evidence about the outside world, so a posting landing here
asserts nothing about a tenant's record and owes no receipt. The receipt is owed
at the *other* boundary — when a hub company is adopted into `companies` — and
that step goes through the gate like everything else.

What ingestion does owe is the gate in `gate.py`: preconditions on the fetch,
postconditions per record, and a re-query proving the rows landed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub import gate
from app.domain.hub.adapters.base import SourceAdapter, SourcedPosting, SourceQuery
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation
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


async def ingest(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    adapter: SourceAdapter,
    request: IngestRequest,
) -> IngestSummary:
    """Fetch one slice from a source and merge it into the tenant's corpus."""
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

    # --- precondition: is this retrieval usable at all? ------------------
    # Raises PreconditionFailed; the router maps that to 422. The observation is
    # written first so even a refused fetch leaves evidence.
    observation = HubObservation(
        tenant_id=tenant_id,
        source=result.source,
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
            select(HubCompany).where(
                HubCompany.tenant_id == tenant_id,
                HubCompany.dedupe_key.in_(dedupe_keys),
            )
        )
        existing_companies = {row.dedupe_key: row for row in rows.scalars().all()}

    company_by_key: dict[str, HubCompany] = dict(existing_companies)

    for posting, basis, key in accepted:
        company = company_by_key.get(key)
        sourced = posting.company
        if company is None:
            company = HubCompany(
                tenant_id=tenant_id,
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
                visibility="private",
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
                HubJobPosting.tenant_id == tenant_id,
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
                    tenant_id=tenant_id,
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
            select(
                HubJobPosting.hub_company_id, func.count(HubJobPosting.id)
            )
            .where(
                HubJobPosting.tenant_id == tenant_id,
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
            HubJobPosting.tenant_id == tenant_id,
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
# Corpus reads
# --------------------------------------------------------------------------


def _paginate(stmt: Select, *, limit: int, offset: int) -> Select:
    return stmt.limit(limit).offset(offset)


async def list_companies(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    q: str | None = None,
    city: str | None = None,
    hiring_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[HubCompany]:
    """Companies in the corpus, most actively hiring first.

    That ordering is the point of the hub: a recruiter wants whoever has the most
    open roles right now, not an alphabetical register extract.
    """
    stmt = select(HubCompany).where(HubCompany.tenant_id == tenant_id)
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
    stmt = stmt.order_by(
        HubCompany.open_postings_count.desc(), HubCompany.name
    )
    rows = await session.execute(_paginate(stmt, limit=limit, offset=offset))
    return list(rows.scalars().all())


async def count_companies(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> int:
    return (
        await session.scalar(
            select(func.count(HubCompany.id)).where(
                HubCompany.tenant_id == tenant_id
            )
        )
    ) or 0


async def get_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, hub_company_id: uuid.UUID
) -> HubCompany | None:
    return await session.scalar(
        select(HubCompany).where(
            HubCompany.tenant_id == tenant_id, HubCompany.id == hub_company_id
        )
    )


async def list_postings(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    hub_company_id: uuid.UUID | None = None,
    q: str | None = None,
    city: str | None = None,
    source: str | None = None,
    active_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[HubJobPosting]:
    stmt = select(HubJobPosting).where(HubJobPosting.tenant_id == tenant_id)
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
    stmt = stmt.order_by(HubJobPosting.posted_at.desc().nulls_last(), HubJobPosting.title)
    rows = await session.execute(_paginate(stmt, limit=limit, offset=offset))
    return list(rows.scalars().all())


async def list_observations(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 50
) -> list[HubObservation]:
    """The evidence ledger for this tenant's corpus, newest fetch first."""
    rows = await session.execute(
        select(HubObservation)
        .where(HubObservation.tenant_id == tenant_id)
        .order_by(HubObservation.fetched_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())
