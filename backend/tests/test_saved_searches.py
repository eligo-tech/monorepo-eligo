"""Saved searches — standing market questions, and crawl directives.

The two properties worth pinning: a saved search must never trigger a fetch
(ARCHITECTURE.md RULE 1), and the crawl directives handed to the nightly job
must not reveal which workspace asked for them.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.searches import service
from app.domain.searches.schemas import SavedSearchCreate
from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def tenant() -> uuid.UUID:
    return settings.default_tenant_id


async def test_saving_a_search_fetches_nothing(client, monkeypatch) -> None:
    """RULE 1: configuration, not a request that crawls."""
    import httpx

    def _boom(*args, **kwargs):
        raise AssertionError("saving a search must not touch a public source")

    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)
    resp = await client.post(
        "/api/v1/searches",
        json={"label": "TS Frontend Stuttgart", "q": "TypeScript", "city": "Stuttgart"},
    )
    assert resp.status_code == 201
    assert resp.json()["q"] == "TypeScript"
    assert resp.json()["last_crawled_at"] is None


async def test_crud_round_trip(client) -> None:
    created = (
        await client.post(
            "/api/v1/searches", json={"label": "SAP", "q": "SAP Berater"}
        )
    ).json()
    assert (await client.get("/api/v1/searches")).json()[0]["label"] == "SAP"

    patched = await client.patch(
        f"/api/v1/searches/{created['id']}", json={"min_roles": 3}
    )
    assert patched.status_code == 200 and patched.json()["min_roles"] == 3
    # Untouched fields survive a partial update.
    assert patched.json()["q"] == "SAP Berater"

    assert (
        await client.delete(f"/api/v1/searches/{created['id']}")
    ).status_code == 204
    assert (await client.get("/api/v1/searches")).json() == []


async def test_labels_are_unique_per_workspace(client) -> None:
    from sqlalchemy.exc import IntegrityError

    await client.post("/api/v1/searches", json={"label": "dup", "q": "a"})
    # The DB constraint is what enforces this, so assert on IT rather than on
    # "something raised" — a blind Exception would also pass if the request
    # failed for an unrelated reason.
    with pytest.raises(IntegrityError):
        await client.post("/api/v1/searches", json={"label": "dup", "q": "b"})


async def test_crawl_directives_are_deduplicated_and_unattributed(tenant) -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        # Two workspaces watching the same thing, plus one distinct profile.
        await service.create_search(
            s, tenant_id=tenant, data=SavedSearchCreate(label="a", q="SAP Berater")
        )
        await service.create_search(
            s, tenant_id=other, data=SavedSearchCreate(label="b", q="SAP Berater")
        )
        await service.create_search(
            s,
            tenant_id=other,
            data=SavedSearchCreate(label="c", q="TypeScript", city="Stuttgart"),
        )
        # Disabled profiles are not crawled...
        await service.create_search(
            s,
            tenant_id=tenant,
            data=SavedSearchCreate(label="d", q="Java", crawl_enabled=False),
        )
        # ...and neither is a keyword-less corpus filter: there is nothing to ask
        # the source for.
        await service.create_search(
            s, tenant_id=tenant, data=SavedSearchCreate(label="e", city="Berlin")
        )

    profiles = await service.list_crawl_profiles()
    terms = sorted(p.q for p in profiles)
    assert terms == ["SAP Berater", "TypeScript"], "must dedupe across tenants"

    # The crawler must not learn WHO asked.
    for profile in profiles:
        assert not hasattr(profile, "tenant_id")
        assert set(profile.model_dump()) == {"q", "city", "radius_km"}


async def test_marking_crawled_stamps_every_owner_of_a_directive(tenant) -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        await service.create_search(
            s, tenant_id=tenant, data=SavedSearchCreate(label="a", q="SAP Berater")
        )
        await service.create_search(
            s, tenant_id=other, data=SavedSearchCreate(label="b", q="SAP Berater")
        )

    profiles = await service.list_crawl_profiles()
    # One directive, two owners — both should see their profile as current.
    assert await service.mark_crawled(profiles) == 2

    async with SessionLocal() as s:
        rows = await service.list_searches(s, tenant_id=tenant)
    assert rows[0].last_crawled_at is not None


async def test_a_search_is_only_visible_to_its_own_workspace(tenant) -> None:
    other = uuid.uuid4()
    async with SessionLocal() as s:
        await service.create_search(
            s, tenant_id=other, data=SavedSearchCreate(label="theirs", q="secret")
        )
        mine = await service.list_searches(s, tenant_id=tenant)
    assert mine == [], "search terms are competitive intelligence"


async def test_running_a_saved_search_records_its_result_count(client) -> None:
    created = (
        await client.post("/api/v1/searches", json={"label": "x", "q": "nothingmatches"})
    ).json()
    results = await client.get(f"/api/v1/searches/{created['id']}/results")
    assert results.status_code == 200 and results.json() == []

    listed = (await client.get("/api/v1/searches")).json()[0]
    assert listed["last_result_count"] == 0


async def test_unknown_search_is_404(client) -> None:
    assert (
        await client.get(f"/api/v1/searches/{uuid.uuid4()}/results")
    ).status_code == 404
    assert (
        await client.patch(f"/api/v1/searches/{uuid.uuid4()}", json={"min_roles": 1})
    ).status_code == 404
