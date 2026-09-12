"""Managers — the hiring-side person, and the tenant boundary around them.

These rows are personal data, so the tests that matter are not "can I create
one" but the two that protect the subject: a manager cannot be attached to
another workspace's company, and a person sourced from a third party is visibly
owed a GDPR Art. 14 notice until someone records having sent it.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource, InteractionType
from app.domain.companies.models import Company
from app.domain.managers import service
from app.domain.managers.schemas import (
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerUpdate,
)

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


@pytest.fixture
async def company() -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=TENANT, name="Bayoonet AG")
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c.id


@pytest.fixture
async def foreign_company() -> uuid.UUID:
    """A company belonging to a DIFFERENT workspace."""
    async with SessionLocal() as s:
        c = Company(tenant_id=OTHER_TENANT, name="Someone Else GmbH")
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c.id


async def test_manager_cannot_be_attached_to_another_workspaces_company(
    foreign_company,
) -> None:
    """The check RLS cannot make for us.

    `company_id` is client-supplied. Writing a manager row with this tenant's
    own `tenant_id` is a perfectly valid write as far as row-level security is
    concerned — the policy only asks whether the ROW belongs to the writer, not
    whether the thing it points at does. So the service verifies ownership
    explicitly, and this pins that it does.
    """
    async with SessionLocal() as s:
        with pytest.raises(service.CompanyNotInTenant):
            await service.create_manager(
                s,
                tenant_id=TENANT,
                payload=ManagerCreate(
                    company_id=foreign_company, full_name="Nicht Erlaubt"
                ),
            )


async def test_third_party_sourced_manager_owes_an_art14_notice(company) -> None:
    """Provenance decides the obligation, and it stays visible until discharged."""
    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company,
                full_name="Petra Vogel",
                role_title="Head of Engineering",
                source=ConfidenceSource.PUBLIC_WEB,
                source_detail="https://example.com/team",
            ),
        )
        assert m.art14_outstanding is True

        queue = await service.managers_owing_art14(s, tenant_id=TENANT)
        assert [x.id for x in queue] == [m.id]

        await service.mark_art14_notified(s, tenant_id=TENANT, manager_id=m.id)

    async with SessionLocal() as s:
        again = await service.get_manager(s, tenant_id=TENANT, manager_id=m.id)
        assert again.art14_notified_at is not None
        assert again.art14_outstanding is False
        assert await service.managers_owing_art14(s, tenant_id=TENANT) == []


async def test_a_manager_the_subject_gave_us_owes_nothing(company) -> None:
    """Art. 14 is about data NOT obtained from the subject. Self-reported is 13."""
    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company,
                full_name="Jens Wieland",
                source=ConfidenceSource.SELF_REPORTED,
            ),
        )
        assert m.art14_outstanding is False
        assert await service.managers_owing_art14(s, tenant_id=TENANT) == []


async def test_managers_are_not_visible_across_workspaces(company) -> None:
    async with SessionLocal() as s:
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(company_id=company, full_name="Nur Fuer Uns"),
        )
        assert await service.list_managers(s, tenant_id=OTHER_TENANT) == []
        assert len(await service.list_managers(s, tenant_id=TENANT)) == 1


async def test_interactions_record_who_was_discussed(company) -> None:
    """The point of logging: "who have I already sent them?" must be answerable."""
    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(company_id=company, full_name="Petra Vogel"),
        )
        await service.log_interaction(
            s,
            tenant_id=TENANT,
            manager_id=m.id,
            payload=ManagerInteractionCreate(
                interaction_type=InteractionType.CALL,
                summary="Briefing on the embedded role",
                occurred_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
            ),
        )
        await service.log_interaction(
            s,
            tenant_id=TENANT,
            manager_id=m.id,
            payload=ManagerInteractionCreate(
                interaction_type=InteractionType.EMAIL,
                summary="Sent two profiles",
                occurred_at=dt.datetime(2026, 9, 3, tzinfo=dt.UTC),
            ),
        )
        rows = await service.list_interactions(
            s, tenant_id=TENANT, manager_id=m.id
        )
    # newest first
    assert [r.interaction_type for r in rows] == ["email", "call"]


async def test_update_does_not_touch_the_art14_timestamp(company) -> None:
    """Editing a phone number must not be able to discharge a legal obligation."""
    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company,
                full_name="Petra Vogel",
                source=ConfidenceSource.THIRD_PARTY_SOURCE,
            ),
        )
        updated = await service.update_manager(
            s,
            tenant_id=TENANT,
            manager_id=m.id,
            payload=ManagerUpdate(phone="+49 30 123456"),
        )
        assert updated.phone == "+49 30 123456"
        assert updated.art14_notified_at is None
        assert updated.art14_outstanding is True


async def test_search_finds_a_contact_by_their_employer(company) -> None:
    """A recruiter remembers "the CTO at Bergfreunde" as often as a name.

    With 650 contacts imported, a name-only search sends them scrolling an
    alphabetical list — so the company name is searchable too.
    """
    async with SessionLocal() as s:
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company, full_name="Marc Götte", role_title="Leiter IT"
            ),
        )
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company, full_name="Sophia Erber", role_title="HR"
            ),
        )

        by_name = await service.list_managers(s, tenant_id=TENANT, q="götte")
        by_role = await service.list_managers(s, tenant_id=TENANT, q="leiter")
        by_company = await service.list_managers(s, tenant_id=TENANT, q="bayoonet")
        no_match = await service.list_managers(s, tenant_id=TENANT, q="zzzz")

    assert [m.full_name for m in by_name] == ["Marc Götte"]
    assert [m.full_name for m in by_role] == ["Marc Götte"]
    # the fixture company is "Bayoonet AG" — both contacts work there
    assert len(by_company) == 2
    assert no_match == []


async def test_search_stays_inside_the_workspace(company) -> None:
    async with SessionLocal() as s:
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(company_id=company, full_name="Marc Götte"),
        )
        assert await service.list_managers(s, tenant_id=OTHER_TENANT, q="götte") == []


async def test_the_profile_carries_its_own_counts(company) -> None:
    """The stat strip needs numbers the list row does not have.

    Counted on the single read so the profile is one request, and set as
    transient attributes rather than columns: they are facts ABOUT the row, and
    storing them would mean keeping two numbers in step with the tables that
    produce them.
    """
    import datetime as dt

    from app.domain.jobs.models import Job
    from app.domain.managers.schemas import ManagerInteractionCreate

    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(company_id=company, full_name="Mathias Ams"),
        )
        s.add_all(
            [
                Job(tenant_id=TENANT, title="Head of R&D", manager_id=m.id, status="open"),
                Job(tenant_id=TENANT, title="Alt", manager_id=m.id, status="closed"),
            ]
        )
        await s.commit()
        await service.log_interaction(
            s,
            tenant_id=TENANT,
            manager_id=m.id,
            payload=ManagerInteractionCreate(
                interaction_type=InteractionType.CALL,
                summary="BD call",
                occurred_at=dt.datetime(2026, 7, 3, tzinfo=dt.UTC),
            ),
        )

    async with SessionLocal() as s:
        profile = await service.get_manager(s, tenant_id=TENANT, manager_id=m.id)

    assert profile.job_count == 2
    # the strip shows OPEN mandates: a closed one is not work waiting to be done
    assert profile.open_job_count == 1
    assert profile.note_count == 1


async def test_counts_do_not_leak_another_workspaces_mandates(company) -> None:
    from app.domain.jobs.models import Job

    async with SessionLocal() as s:
        m = await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(company_id=company, full_name="Nur Unsere"),
        )
        # same manager id, another tenant's job row — must not be counted
        s.add(Job(tenant_id=OTHER_TENANT, title="Fremd", manager_id=m.id, status="open"))
        await s.commit()

    async with SessionLocal() as s:
        profile = await service.get_manager(s, tenant_id=TENANT, manager_id=m.id)
    assert profile.job_count == 0
