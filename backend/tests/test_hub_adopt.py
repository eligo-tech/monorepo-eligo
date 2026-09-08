"""Adopting a corpus company — THE crossing into the system-of-record.

Everything before this point is observation of the outside world: shared,
re-crawlable, asserting nothing about anyone's record. This is where a public
fact becomes a tenant's own row, which is exactly where CLAUDE.md §2.6 says a
receipt is owed — not at ingest, and not at tracking.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.models import Company
from app.domain.hub import service
from app.domain.hub.models import HubCompany, HubCompanyLink
from app.domain.managers.models import Manager
from app.domain.verification.models import Receipt

TENANT = uuid.uuid4()


@pytest.fixture
async def corpus_company() -> uuid.UUID:
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        company = HubCompany(
            name="Bayoonet AG",
            normalized_name="bayoonet",
            dedupe_key=f"k-{uuid.uuid4()}",
            resolution_basis="name_place",
            website_domain="bayoonet.de",
            city="Berlin",
            source="bundesagentur",
            first_seen_at=now,
            last_seen_at=now,
        )
        s.add(company)
        await s.commit()
        await s.refresh(company)
        return company.id


async def test_adoption_creates_the_company_and_leaves_a_receipt(
    corpus_company,
) -> None:
    """The receipt is the whole point: ingest owes none, this owes one."""
    async with SessionLocal() as s:
        before = await s.scalar(
            select(func.count(Receipt.id)).where(Receipt.tenant_id == TENANT)
        )
        company, link, manager = await service.adopt_company(
            s, tenant_id=TENANT, hub_company_id=corpus_company
        )
        after = await s.scalar(
            select(func.count(Receipt.id)).where(Receipt.tenant_id == TENANT)
        )

    assert company.name == "Bayoonet AG"
    assert company.location == "Berlin"
    assert company.domain == "bayoonet.de"
    assert company.is_client is True
    assert company.tenant_id == TENANT
    # the corpus row now points at the tenant's own record
    assert link.company_id == company.id
    assert link.relationship == "client"
    assert manager is None
    assert after > before, "the crossing must leave a receipt"


async def test_adopting_twice_is_refused_rather_than_duplicated(
    corpus_company,
) -> None:
    """A second adoption would fork the account into two rows silently."""
    async with SessionLocal() as s:
        await service.adopt_company(
            s, tenant_id=TENANT, hub_company_id=corpus_company
        )
    async with SessionLocal() as s:
        with pytest.raises(service.AlreadyAdopted):
            await service.adopt_company(
                s, tenant_id=TENANT, hub_company_id=corpus_company
            )
    async with SessionLocal() as s:
        rows = await s.scalar(
            select(func.count(Company.id)).where(Company.tenant_id == TENANT)
        )
    assert rows == 1


async def test_a_contact_captured_from_a_public_page_owes_an_art14_notice(
    corpus_company,
) -> None:
    """Provenance travels with the person from the moment they are created.

    Recorded at adopt time or never: once the row exists without a source, where
    it came from is unknowable and the obligation cannot be assessed.
    """
    async with SessionLocal() as s:
        company, _link, manager = await service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=corpus_company,
            manager={
                "full_name": "Petra Vogel",
                "role_title": "Head of Engineering",
                "email": "petra@bayoonet.de",
                "source": ConfidenceSource.PUBLIC_WEB.value,
                "source_detail": "https://bayoonet.de/team",
            },
        )

    assert manager is not None
    assert manager.company_id == company.id
    assert manager.tenant_id == TENANT
    assert manager.art14_outstanding is True

    async with SessionLocal() as s:
        queue = await s.scalars(
            select(Manager).where(Manager.tenant_id == TENANT)
        )
        assert [m.full_name for m in queue] == ["Petra Vogel"]


async def test_a_contact_the_recruiter_already_knew_owes_nothing(
    corpus_company,
) -> None:
    async with SessionLocal() as s:
        _company, _link, manager = await service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=corpus_company,
            manager={"full_name": "Jens Wieland"},
        )
    assert manager.source == ConfidenceSource.SELF_REPORTED.value
    assert manager.art14_outstanding is False


async def test_a_blank_contact_creates_no_person(corpus_company) -> None:
    """Absent means absent. A placeholder person is worse than none — it puts an
    unsourced natural person into the record."""
    async with SessionLocal() as s:
        _company, _link, manager = await service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=corpus_company,
            manager={"full_name": "   "},
        )
        count = await s.scalar(
            select(func.count(Manager.id)).where(Manager.tenant_id == TENANT)
        )
    assert manager is None
    assert count == 0


async def test_adoption_is_scoped_to_the_adopting_workspace(
    corpus_company,
) -> None:
    """The corpus row is shared; the link and the company are not."""
    other = uuid.uuid4()
    async with SessionLocal() as s:
        await service.adopt_company(
            s, tenant_id=TENANT, hub_company_id=corpus_company
        )
    async with SessionLocal() as s:
        links = await s.scalars(
            select(HubCompanyLink).where(HubCompanyLink.tenant_id == other)
        )
        assert list(links) == []
        # ...and the other workspace can still adopt it for itself
        company, _link, _m = await service.adopt_company(
            s, tenant_id=other, hub_company_id=corpus_company
        )
        assert company.tenant_id == other
