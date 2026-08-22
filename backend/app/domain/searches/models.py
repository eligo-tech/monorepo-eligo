"""Saved-search ORM model.

A saved search is a recruiter's standing question — "TypeScript Frontend, Raum
Stuttgart" — and it does two jobs:

  1. **A query.** Re-run it against the corpus to see who is hiring for it now.
  2. **An ingestion directive.** The nightly job reads the union of all enabled
     profiles and crawls the source with those keywords, so the corpus deepens
     exactly where people actually recruit.

Job 2 is why this matters more than a bookmark. The source's own full-text
search covers posting DESCRIPTIONS, which we do not store: measured, only 5% of
TypeScript roles and 33% of Java roles carry the term in their title. Passing a
profile's keywords to the source recovers the other 95% at a handful of requests
per profile per night, instead of fetching descriptions for the whole corpus.

**The terms are tenant-private.** What a recruiter hunts for is competitive
intelligence; the rows are RLS-isolated like every other tenant row. The crawler
reads only the DEDUPLICATED UNION of profiles across tenants — it learns what to
crawl, never who asked, and three tenants wanting "SAP Berater" cost one crawl.

This does not weaken ARCHITECTURE.md RULE 1 (ingestion is a scheduled job, no
user, no UI): a profile is configuration the nightly job reads, never a request
that performs a crawl. Saving one fetches nothing.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint

from app.domain.common.types import JSONList

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class SavedSearch(Base, IDMixin, TenantMixin, TimestampMixin):
    """One standing market question belonging to one workspace."""

    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "label", name="uq_saved_search_label"),
    )

    label: Mapped[str] = mapped_column(String(120), nullable=False)

    # Keywords. Sent to the source as its full-text parameter, which is what
    # reaches posting descriptions we do not store ourselves.
    q: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Bundesländer and occupational fields. OR-within, AND-across: several
    # regions widen the area, a Berufsfeld narrows within it.
    regions: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    berufsfelder: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_roles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Whether the nightly job should crawl the source for this profile. A
    # profile with no keywords is a corpus filter only — there is nothing
    # meaningful to ask the source for.
    crawl_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    last_crawled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Employers the profile matched when it was last run — the number that makes
    # "3 more than yesterday" possible later.
    last_result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
