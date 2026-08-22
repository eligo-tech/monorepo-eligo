"""Saved-search business logic."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AdminSessionLocal
from app.core.logging import get_logger
from app.domain.searches.models import SavedSearch
from app.domain.searches.schemas import (
    CrawlProfile,
    SavedSearchCreate,
    SavedSearchUpdate,
)

logger = get_logger(__name__)


async def list_searches(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[SavedSearch]:
    rows = await session.execute(
        select(SavedSearch)
        .where(SavedSearch.tenant_id == tenant_id)
        .order_by(SavedSearch.label)
    )
    return list(rows.scalars().all())


async def get_search(
    session: AsyncSession, *, tenant_id: uuid.UUID, search_id: uuid.UUID
) -> SavedSearch | None:
    return await session.scalar(
        select(SavedSearch).where(
            SavedSearch.tenant_id == tenant_id, SavedSearch.id == search_id
        )
    )


async def create_search(
    session: AsyncSession, *, tenant_id: uuid.UUID, data: SavedSearchCreate
) -> SavedSearch:
    row = SavedSearch(tenant_id=tenant_id, **data.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_search(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search_id: uuid.UUID,
    data: SavedSearchUpdate,
) -> SavedSearch | None:
    row = await get_search(session, tenant_id=tenant_id, search_id=search_id)
    if row is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_search(
    session: AsyncSession, *, tenant_id: uuid.UUID, search_id: uuid.UUID
) -> bool:
    row = await get_search(session, tenant_id=tenant_id, search_id=search_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def record_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search_id: uuid.UUID,
    result_count: int,
) -> None:
    """Remember how many employers a profile matched when it was last run."""
    row = await get_search(session, tenant_id=tenant_id, search_id=search_id)
    if row is None:
        return
    row.last_result_count = result_count
    await session.commit()


async def list_crawl_profiles() -> list[CrawlProfile]:
    """The deduplicated union of crawl directives across ALL tenants.

    This is a deliberate CROSS-TENANT read, and the only one in the codebase
    outside admin scripts. Two things make it safe:

      * It opens the OWNER connection (`AdminSessionLocal`) explicitly, because
        the app role is RLS-bound and would correctly see nothing. Routing this
        through a normal request session would silently return an empty list —
        a crawl that quietly does nothing is worse than one that fails.
      * It returns only `(q, city, radius_km)`. No tenant_id, no label, no id.
        The crawler learns WHAT to fetch, never WHO asked. Search terms are
        competitive intelligence and must not leak between workspaces, even
        though the postings they surface land in the shared corpus.

    Deduplication is the point of the union: three workspaces all watching
    "SAP Berater" cost one crawl, not three.
    """
    async with AdminSessionLocal() as session:
        rows = await session.execute(
            select(
                SavedSearch.q, SavedSearch.city, SavedSearch.radius_km
            )
            .where(
                SavedSearch.crawl_enabled.is_(True),
                SavedSearch.q.is_not(None),
                SavedSearch.q != "",
            )
            .distinct()
        )
        profiles = [
            CrawlProfile(q=q, city=city, radius_km=radius)
            for q, city, radius in rows.all()
        ]
    logger.info("crawl profiles: %d distinct directive(s)", len(profiles))
    return profiles


async def mark_crawled(profiles: list[CrawlProfile]) -> int:
    """Stamp `last_crawled_at` on every profile matching a crawled directive.

    Cross-tenant for the same reason as `list_crawl_profiles`: one directive may
    belong to several workspaces, and each of them should see that their profile
    is current.
    """
    if not profiles:
        return 0
    now = dt.datetime.now(dt.UTC)
    touched = 0
    async with AdminSessionLocal() as session:
        for profile in profiles:
            rows = await session.execute(
                select(SavedSearch).where(
                    SavedSearch.crawl_enabled.is_(True),
                    SavedSearch.q == profile.q,
                    SavedSearch.city.is_(None)
                    if profile.city is None
                    else SavedSearch.city == profile.city,
                )
            )
            for row in rows.scalars().all():
                row.last_crawled_at = now
                touched += 1
        await session.commit()
    return touched
