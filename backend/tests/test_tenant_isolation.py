"""One workspace must never read another's rows. Asserted, not argued.

Multi-tenancy is the oldest invariant in this codebase (`backend/CLAUDE.md`
§2.3, ARCHITECTURE.md RULE 3) and until now **nothing tested it**. The files
with "auth" in the name check configuration — that a Postgres deployment
refuses to boot without auth, that operator routes reject a user session — and
none of them ever puts two tenants in a database and looks.

So this does. Two organizations are admitted, one of them is given a row in
every tenant-scoped table that has an HTTP surface, and then every listing the
API offers is fetched **as the other organization** and searched for those ids.

What this proves and what it does not:

* It proves the **query layer** — the `WHERE tenant_id = …` in every service.
  That is the layer a new domain gets wrong, and it is the only layer SQLite
  has, so it is the one CI can check.
* It does **not** prove RLS. The database policies are the real backstop and
  they exist only on Postgres; `test_rls_coverage.py` checks that every
  tenant-scoped table has one, and the fail-closed behaviour of an unset GUC
  has to be verified against a real Postgres.

Both layers matter and they fail differently: a forgotten `WHERE` is caught
here, a forgotten *policy* is caught there.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.pipeline.models import Application
from app.domain.projects.models import Project
from app.domain.searches.models import SavedSearch
from app.domain.tenants import service as tenants_service

ORG_A = "org_alpha"
ORG_B = "org_beta"

#: Listings that must answer 200 for a signed-in member of an admitted
#: workspace. Without this, a route that 500s for everyone would "pass" the
#: disclosure check by returning nothing at all, and the suite would be green
#: because the API was broken.
MUST_ANSWER = [
    "/candidates",
    "/jobs",
    "/companies",
    "/managers",
    "/pipeline/applications",
    "/projects",
]


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _as(org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer session-for-{org_id}"}


@pytest.fixture
def two_orgs(monkeypatch):
    """Turn real auth on and resolve the bearer token back to its org.

    `verify_token` is the only thing stubbed — org → tenant mapping, admission
    and the GUC all run for real, so the test exercises the production path.
    """
    from app.core import auth as auth_module

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token: {
            "org_id": token.removeprefix("session-for-"),
            "sub": f"user-of-{token.removeprefix('session-for-')}",
            "name": "Test Person",
        },
    )


async def _admit(org_id: str) -> uuid.UUID:
    async with SessionLocal() as session:
        tenant = await tenants_service.get_or_create(
            session, clerk_org_id=org_id, name=org_id
        )
        return tenant.id


async def _populate(tenant_id: uuid.UUID) -> dict[str, str]:
    """One row in every tenant-scoped table reachable over HTTP.

    Returns the ids as strings, which is how they appear in a JSON body — the
    search below is a substring match over the raw response, so it cannot be
    fooled by a nesting depth nobody thought to walk.
    """
    async with SessionLocal() as session:
        company = Company(tenant_id=tenant_id, name="Alpha Industrie GmbH")
        candidate = Candidate(tenant_id=tenant_id, full_name="Alpha Kandidatin")
        session.add_all([company, candidate])
        await session.flush()

        job = Job(
            tenant_id=tenant_id,
            title="Alpha Mandat",
            client_company_id=company.id,
            status="open",
        )
        manager = Manager(
            tenant_id=tenant_id, company_id=company.id, full_name="Alpha Manager"
        )
        project = Project(tenant_id=tenant_id, name="Alpha Projekt")
        search = SavedSearch(tenant_id=tenant_id, label="Alpha Suche")
        session.add_all([job, manager, project, search])
        await session.flush()

        application = Application(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            job_id=job.id,
            status=ApplicationStatus.SOURCED,
            stage=PipelineStage.BEWERBUNG,
        )
        interaction = ManagerInteraction(
            tenant_id=tenant_id,
            manager_id=manager.id,
            interaction_type="note",
            occurred_at=dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC),
            summary="Alpha Gesprächsnotiz",
        )
        session.add_all([application, interaction])
        await session.commit()

        return {
            "company": str(company.id),
            "candidate": str(candidate.id),
            "job": str(job.id),
            "manager": str(manager.id),
            "project": str(project.id),
            "saved_search": str(search.id),
            "application": str(application.id),
            "interaction": str(interaction.id),
        }


def _listing_paths() -> list[str]:
    """Every GET route that takes no path parameter, derived from the app.

    Derived rather than listed so a new domain is covered the day its router is
    included — the same reason `test_operator_endpoints.py` introspects instead
    of enumerating.
    """
    from app.core.auth import get_current_actor, get_current_tenant
    from app.main import app

    human = {get_current_tenant.__name__, get_current_actor.__name__}
    paths: set[str] = set()

    def walk(router):
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                names = {
                    d.call.__name__
                    for d in route.dependant.dependencies
                    if getattr(d, "call", None) is not None
                }
                if "GET" in route.methods and "{" not in route.path and names & human:
                    paths.add(route.path)
            else:
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    walk(inner)

    walk(app)
    return sorted(paths)


async def test_no_listing_leaks_another_workspaces_rows(two_orgs) -> None:
    """The broad sweep: every listing, as the other organization."""
    await create_all()
    tenant_a = await _admit(ORG_A)
    await _admit(ORG_B)
    ids = await _populate(tenant_a)

    answered: set[str] = set()
    leaks: list[str] = []

    async with _api() as client:
        for path in _listing_paths():
            resp = await client.get(
                f"{settings.api_v1_prefix}{path}", headers=_as(ORG_B)
            )
            if resp.status_code == 200:
                answered.add(path)
            body = resp.text
            for label, value in ids.items():
                if value in body:
                    leaks.append(f"{path} disclosed {label} {value}")

    assert not leaks, "cross-tenant disclosure:\n  " + "\n  ".join(leaks)

    missing = [p for p in MUST_ANSWER if p not in answered]
    assert not missing, (
        "these listings did not return 200, so the check above was vacuous "
        f"for them: {missing}"
    )


@pytest.mark.parametrize(
    ("template", "key"),
    [
        ("/candidates/{id}", "candidate"),
        ("/jobs/{id}", "job"),
        ("/companies/{id}", "company"),
        ("/managers/{id}", "manager"),
        ("/projects/{id}", "project"),
        # No `GET /pipeline/applications/{id}` exists — an application is only
        # ever read through a listing, which the sweep above covers.
    ],
)
async def test_fetching_another_workspaces_row_by_id_is_a_404(
    two_orgs, template, key
) -> None:
    """Knowing the id must not be enough — the id is in every URL a colleague
    pastes. 404 rather than 403: whether that id exists is itself the other
    workspace's business."""
    await create_all()
    tenant_a = await _admit(ORG_A)
    await _admit(ORG_B)
    ids = await _populate(tenant_a)

    url = f"{settings.api_v1_prefix}{template.format(id=ids[key])}"
    async with _api() as client:
        as_owner = await client.get(url, headers=_as(ORG_A))
        as_stranger = await client.get(url, headers=_as(ORG_B))

    # The route works — otherwise the 404 below proves nothing.
    assert as_owner.status_code == 200, f"{url} is broken for its owner: {as_owner.text}"
    assert as_stranger.status_code == 404, (
        f"{url} returned {as_stranger.status_code} to another workspace"
    )
    assert ids[key] not in as_stranger.text


async def test_a_write_lands_in_the_callers_workspace_not_the_one_it_names(
    two_orgs,
) -> None:
    """A create that carries `tenant_id` must not be able to choose one.

    `POST /pipeline/applications` takes a `tenant_id` in its body and the
    router overwrites it (`payload.tenant_id = tenant_id`). That line is one
    deletion away from letting a caller write into another workspace, and
    nothing noticed it was load-bearing.
    """
    await create_all()
    tenant_a = await _admit(ORG_A)
    tenant_b = await _admit(ORG_B)
    ids = await _populate(tenant_b)

    async with _api() as client:
        resp = await client.post(
            f"{settings.api_v1_prefix}/pipeline/applications",
            headers=_as(ORG_B),
            json={
                "tenant_id": str(tenant_a),  # the lie
                "candidate_id": ids["candidate"],
                "job_id": ids["job"],
            },
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["tenant_id"] == str(tenant_b), (
        "the body's tenant_id was honoured — a caller can write into another "
        "workspace"
    )
