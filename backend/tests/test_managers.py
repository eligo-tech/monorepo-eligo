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


async def test_contacts_sharing_an_email_are_flagged_not_merged(company) -> None:
    """The source really does hold the same person twice.

    "Mick Drahtschmid" exists as MNGR571 and MNGR572, created seconds apart with
    the same address. Merging them here would silently pick a winner and would
    be undone by the next import, since idempotency is keyed on the source id.
    So both rows stand and both say so.
    """
    async with SessionLocal() as s:
        for _ in range(2):
            await service.create_manager(
                s,
                tenant_id=TENANT,
                payload=ManagerCreate(
                    company_id=company,
                    full_name="Mick Drahtschmid",
                    email="md@bevis.digital",
                ),
            )
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company, full_name="Einzelstueck", email="solo@example.test"
            ),
        )
        rows = await service.list_managers(s, tenant_id=TENANT)

    by_name = {r.full_name: r for r in rows}
    assert by_name["Mick Drahtschmid"].duplicate_count == 2
    assert by_name["Einzelstueck"].duplicate_count == 1
    # both rows survive — nothing was collapsed
    assert sum(1 for r in rows if r.full_name == "Mick Drahtschmid") == 2


async def test_a_contact_without_an_email_is_not_a_duplicate_of_every_other(
    company,
) -> None:
    """Absent e-mail must not group. Treating "" as a shared key would mark
    every incomplete record as a duplicate of all the others."""
    async with SessionLocal() as s:
        for name in ("Ohne Mail Eins", "Ohne Mail Zwei"):
            await service.create_manager(
                s,
                tenant_id=TENANT,
                payload=ManagerCreate(company_id=company, full_name=name, email=None),
            )
        rows = await service.list_managers(s, tenant_id=TENANT)

    for row in rows:
        if row.full_name.startswith("Ohne Mail"):
            assert row.duplicate_count == 1


async def test_duplicates_do_not_count_across_workspaces(company) -> None:
    async with SessionLocal() as s:
        await service.create_manager(
            s,
            tenant_id=TENANT,
            payload=ManagerCreate(
                company_id=company, full_name="Geteilt", email="same@example.test"
            ),
        )
        rows = await service.list_managers(s, tenant_id=TENANT)
    # another workspace holding the same address is not our duplicate
    assert [r for r in rows if r.full_name == "Geteilt"][0].duplicate_count == 1


async def test_a_shared_company_mailbox_is_not_a_duplicate(company) -> None:
    """E-mail alone is not identity.

    `info@occhio.com` is listed by three different people at Occhio, and
    `huehn.a@eplan.de` sits on Anna Vogel's record as well as Anna Huehn's — a
    typo in the source. Matching on the address alone calls all of them
    duplicates, which is worse than missing one: it accuses two real colleagues
    of being the same person.
    """
    async with SessionLocal() as s:
        for name in ("Fabian Huber", "Burkhardt Gumpricht"):
            await service.create_manager(
                s,
                tenant_id=TENANT,
                payload=ManagerCreate(
                    company_id=company, full_name=name, email="info@occhio.com"
                ),
            )
        # ...while the genuine double entry still is one
        for _ in range(2):
            await service.create_manager(
                s,
                tenant_id=TENANT,
                payload=ManagerCreate(
                    company_id=company,
                    full_name="Mick Drahtschmid",
                    email="md@bevis.digital",
                ),
            )
        rows = await service.list_managers(s, tenant_id=TENANT)

    by_name = {r.full_name: r for r in rows}
    assert by_name["Fabian Huber"].duplicate_count == 1
    assert by_name["Burkhardt Gumpricht"].duplicate_count == 1
    assert by_name["Mick Drahtschmid"].duplicate_count == 2
