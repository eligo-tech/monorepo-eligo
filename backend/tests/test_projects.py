"""Projects — the recruiter's own grouping of target companies.

A project is a NAME and a set of corpus companies. Everything it reports (sites,
open roles, contacts) is read through that membership, so these tests check the
joins as much as the CRUD: a project must never state a number the corpus and
the record would disagree with.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domain.common.enums import ConfidenceSource
from app.domain.hub import service as hub_service
from app.domain.hub.models import HubCompany, HubJobPosting
from app.domain.managers.models import Manager
from app.domain.projects import service
from app.domain.projects.models import Project, ProjectCompany
from app.domain.projects.schemas import (
    AddContactRequest,
    ProjectCreate,
    ProjectUpdate,
)

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")  # the auth-off default
OTHER = uuid.uuid4()
NOW = dt.datetime.now(dt.UTC)


def _company(name: str, normalized: str, city: str) -> HubCompany:
    return HubCompany(
        name=name,
        normalized_name=normalized,
        dedupe_key=f"k-{uuid.uuid4()}",
        resolution_basis="name_place",
        city=city,
        source="bundesagentur",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _posting(company: HubCompany, *, active: bool = True) -> HubJobPosting:
    return HubJobPosting(
        hub_company_id=company.id,
        title="Senior Engineer (m/w/d)",
        source="bundesagentur",
        external_id=f"10001-{uuid.uuid4().hex[:10]}-S",
        posted_at=NOW,
        first_seen_at=NOW,
        last_seen_at=NOW,
        is_active=active,
        content_hash=uuid.uuid4().hex,
    )


@pytest.fixture
async def corpus() -> dict:
    """One employer on two sites (3 open roles) and a second employer (1)."""
    async with SessionLocal() as s:
        mgm_leipzig = _company("mgm technology partners", "mgm", "Leipzig")
        mgm_munich = _company("mgm technology partners GmbH", "mgm", "München")
        zalando = _company("Zalando SE", "zalando", "Berlin")
        s.add_all([mgm_leipzig, mgm_munich, zalando])
        await s.flush()
        s.add_all(
            [
                _posting(mgm_leipzig),
                _posting(mgm_munich),
                _posting(mgm_munich),
                _posting(mgm_munich, active=False),  # closed: never counted
                _posting(zalando),
            ]
        )
        await s.commit()
        return {"mgm": mgm_leipzig.id, "mgm_other_site": mgm_munich.id, "zalando": zalando.id}


async def _project(name: str = "TypeScript Berlin Q4") -> uuid.UUID:
    async with SessionLocal() as s:
        project = await service.create_project(
            s, tenant_id=TENANT, payload=ProjectCreate(name=name)
        )
        return project.id


# --------------------------------------------------------------------------
# A project is a name
# --------------------------------------------------------------------------


async def test_a_project_needs_only_a_name() -> None:
    async with SessionLocal() as s:
        project = await service.create_project(
            s, tenant_id=TENANT, payload=ProjectCreate(name="  Pflege Rhein-Main  ")
        )
    assert project.name == "Pflege Rhein-Main"  # trimmed
    assert project.note is None


async def test_the_same_name_twice_is_refused() -> None:
    await _project("TypeScript Berlin Q4")
    async with SessionLocal() as s:
        with pytest.raises(service.DuplicateName):
            await service.create_project(
                s, tenant_id=TENANT, payload=ProjectCreate(name="typescript berlin q4")
            )


async def test_renaming_keeps_the_membership(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        renamed = await service.update_project(
            s, tenant_id=TENANT, project_id=project_id, payload=ProjectUpdate(name="Q1 2027")
        )
        detail = await service.project_detail(s, tenant_id=TENANT, project_id=project_id)
    assert renamed is not None and renamed.name == "Q1 2027"
    assert [c["name"] for c in detail["companies"]] == ["mgm technology partners"]


# --------------------------------------------------------------------------
# Membership, and the numbers read through it
# --------------------------------------------------------------------------


async def test_companies_are_rolled_up_across_their_sites(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        added = await service.add_companies(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_ids=[corpus["mgm"], corpus["zalando"]],
        )
        detail = await service.project_detail(s, tenant_id=TENANT, project_id=project_id)
    assert added == 2
    mgm = next(c for c in detail["companies"] if c["name"].startswith("mgm"))
    assert mgm["sites"] == 2 and sorted(mgm["cities"]) == ["Leipzig", "München"]
    assert mgm["open_roles"] == 3  # the closed posting is not counted
    assert detail["open_roles"] == 4
    assert detail["company_count"] == 2
    # Nobody adopted anything yet, so no company has a contact.
    assert detail["companies_with_contact"] == 0


async def test_adding_the_same_company_twice_is_a_no_op(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        first = await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        again = await service.add_companies(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_ids=[corpus["mgm"], corpus["zalando"]],
        )
        rows = (await s.execute(select(ProjectCompany))).scalars().all()
    assert (first, again) == (1, 1)
    assert len(rows) == 2


async def test_an_unknown_corpus_id_is_ignored_not_fatal(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        added = await service.add_companies(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_ids=[uuid.uuid4(), corpus["zalando"]],
        )
    assert added == 1


async def test_one_company_can_be_in_several_projects(corpus) -> None:
    first, second = await _project("Projekt A"), await _project("Projekt B")
    async with SessionLocal() as s:
        for project_id in (first, second):
            await service.add_companies(
                s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
            )
        projects = await service.list_projects(s, tenant_id=TENANT)
    assert [p["company_count"] for p in projects] == [1, 1]


async def test_contacts_are_counted_through_the_adopted_company(corpus) -> None:
    """The count comes from `managers`, via the link row — never from a copy."""
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_ids=[corpus["mgm"], corpus["zalando"]],
        )
        await hub_service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=corpus["mgm"],
            manager={
                "full_name": "Sophie Bennicke",
                "source": ConfidenceSource.PUBLIC_WEB.value,
                "source_detail": "https://www.arbeitsagentur.de/jobsuche/jobdetail/x",
            },
        )
        detail = await service.project_detail(s, tenant_id=TENANT, project_id=project_id)
    by_name = {c["name"]: c for c in detail["companies"]}
    assert by_name["mgm technology partners"]["contact_count"] == 1
    assert by_name["mgm technology partners"]["company_id"] is not None
    assert by_name["Zalando SE"]["contact_count"] == 0
    assert detail["companies_with_contact"] == 1


async def test_removing_a_company_leaves_the_corpus_and_contacts_alone(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        assert await service.remove_company(
            s, tenant_id=TENANT, project_id=project_id, hub_company_id=corpus["mgm"]
        )
        assert not await service.remove_company(
            s, tenant_id=TENANT, project_id=project_id, hub_company_id=corpus["mgm"]
        )
        assert await s.get(HubCompany, corpus["mgm"]) is not None


async def test_deleting_a_project_keeps_the_company_and_its_contact(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        await hub_service.adopt_company(
            s,
            tenant_id=TENANT,
            hub_company_id=corpus["mgm"],
            manager={"full_name": "Sophie Bennicke"},
        )
        assert await service.delete_project(s, tenant_id=TENANT, project_id=project_id)
        assert (await s.execute(select(ProjectCompany))).scalars().all() == []
        assert await s.get(HubCompany, corpus["mgm"]) is not None
        assert (await s.execute(select(Manager))).scalars().first() is not None


async def test_candidates_offer_watched_companies_not_already_in_the_project(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await hub_service.track_company(s, tenant_id=TENANT, hub_company_id=corpus["mgm"])
        await hub_service.track_company(s, tenant_id=TENANT, hub_company_id=corpus["zalando"])
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        offered = await service.candidate_companies(
            s, tenant_id=TENANT, project_id=project_id
        )
    assert [c["name"] for c in offered] == ["Zalando SE"]


# --------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------


async def test_projects_are_not_visible_across_workspaces(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        assert await service.list_projects(s, tenant_id=OTHER) == []
        assert await service.project_detail(s, tenant_id=OTHER, project_id=project_id) is None
        assert not await service.delete_project(s, tenant_id=OTHER, project_id=project_id)
        # The same name is free in another workspace.
        twin = await service.create_project(
            s, tenant_id=OTHER, payload=ProjectCreate(name="TypeScript Berlin Q4")
        )
        assert twin.id != project_id
        assert (await s.execute(select(Project))).scalars().all().__len__() == 2


# --------------------------------------------------------------------------
# The HTTP surface
# --------------------------------------------------------------------------


async def test_routes(corpus) -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        created = await client.post("/api/v1/projects", json={"name": "TypeScript Berlin Q4"})
        assert created.status_code == 201
        project_id = created.json()["id"]

        duplicate = await client.post("/api/v1/projects", json={"name": "TypeScript Berlin Q4"})
        assert duplicate.status_code == 409

        added = await client.post(
            f"/api/v1/projects/{project_id}/companies",
            json={"hub_company_ids": [str(corpus["mgm"]), str(corpus["zalando"])]},
        )
        assert added.status_code == 200
        assert added.json()["company_count"] == 2

        listing = await client.get("/api/v1/projects")
        assert [p["name"] for p in listing.json()] == ["TypeScript Berlin Q4"]
        assert listing.json()[0]["open_roles"] == 4

        renamed = await client.patch(f"/api/v1/projects/{project_id}", json={"name": "Q1 2027"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Q1 2027"

        removed = await client.delete(
            f"/api/v1/projects/{project_id}/companies/{corpus['mgm']}"
        )
        assert removed.status_code == 204
        assert (await client.get(f"/api/v1/projects/{project_id}")).json()["company_count"] == 1

        assert (await client.delete(f"/api/v1/projects/{project_id}")).status_code == 204
        assert (await client.get(f"/api/v1/projects/{project_id}")).status_code == 404


# --------------------------------------------------------------------------
# Enrichment: attaching a person to a company on the shortlist
# --------------------------------------------------------------------------


async def test_a_contact_needs_only_a_name(corpus) -> None:
    """The point of the step is knowing WHO to call. An e-mail address is
    often learned later, and demanding one would stop the step."""
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        manager = await service.add_contact(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_id=corpus["mgm"],
            payload=AddContactRequest(full_name="Corina Freund"),
        )
        detail = await service.project_detail(s, tenant_id=TENANT, project_id=project_id)

    assert (manager.email, manager.phone, manager.role_title) == (None, None, None)
    # Found by us, not given by the subject: the notice is owed and visible.
    assert manager.source == ConfidenceSource.PUBLIC_WEB.value
    assert manager.art14_outstanding is True

    company = detail["companies"][0]
    assert [c["full_name"] for c in company["contacts"]] == ["Corina Freund"]
    assert company["contact_count"] == 1
    # Adding a person adopts the company, which is the gated crossing.
    assert company["company_id"] is not None
    assert detail["companies_with_contact"] == 1


async def test_a_contact_the_subject_gave_us_owes_no_notice(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        manager = await service.add_contact(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_id=corpus["mgm"],
            payload=AddContactRequest(
                full_name="Corina Freund",
                role_title="Recruiterin",
                linkedin_url="https://www.linkedin.com/in/example",
                source=ConfidenceSource.SELF_REPORTED,
            ),
        )
    assert manager.art14_outstanding is False
    assert manager.linkedin_url == "https://www.linkedin.com/in/example"


async def test_a_company_outside_the_project_takes_no_contact(corpus) -> None:
    project_id = await _project()
    async with SessionLocal() as s:
        with pytest.raises(ValueError):
            await service.add_contact(
                s,
                tenant_id=TENANT,
                project_id=project_id,
                hub_company_id=corpus["zalando"],
                payload=AddContactRequest(full_name="Niemand"),
            )


async def test_contacts_read_through_to_the_record(corpus) -> None:
    """A project shows the record's contact, never a copy: editing the manager
    changes what the project reports."""
    project_id = await _project()
    async with SessionLocal() as s:
        await service.add_companies(
            s, tenant_id=TENANT, project_id=project_id, hub_company_ids=[corpus["mgm"]]
        )
        manager = await service.add_contact(
            s,
            tenant_id=TENANT,
            project_id=project_id,
            hub_company_id=corpus["mgm"],
            payload=AddContactRequest(full_name="Corina Freund"),
        )
        manager.phone = "+49 341 1234567"
        await s.commit()
        detail = await service.project_detail(s, tenant_id=TENANT, project_id=project_id)
    assert detail["companies"][0]["contacts"][0]["phone"] == "+49 341 1234567"


async def test_contact_route(corpus) -> None:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        project_id = (await client.post("/api/v1/projects", json={"name": "Shortlist"})).json()["id"]
        await client.post(
            f"/api/v1/projects/{project_id}/companies",
            json={"hub_company_ids": [str(corpus["mgm"])]},
        )
        created = await client.post(
            f"/api/v1/projects/{project_id}/companies/{corpus['mgm']}/contacts",
            json={"full_name": "Corina Freund", "role_title": "Recruiterin"},
        )
        assert created.status_code == 201
        assert created.json()["art14_outstanding"] is True

        detail = (await client.get(f"/api/v1/projects/{project_id}")).json()
        assert [c["full_name"] for c in detail["companies"][0]["contacts"]] == ["Corina Freund"]

        missing = await client.post(
            f"/api/v1/projects/{project_id}/companies/{corpus['zalando']}/contacts",
            json={"full_name": "Niemand"},
        )
        assert missing.status_code == 404
