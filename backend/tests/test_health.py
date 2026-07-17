"""Smoke tests — the app must start and answer the health probe on SQLite."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import create_all
from app.main import app


@pytest.fixture(scope="module", autouse=True)
async def _tables() -> None:
    await create_all()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_candidates_endpoint_runs(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/candidates")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_and_match_flow(client: AsyncClient) -> None:
    tenant = str(uuid.uuid4())

    cand = await client.post(
        "/api/v1/candidates",
        json={
            "tenant_id": tenant,
            "full_name": "Test Person",
            "email": "test.person@example.com",
            "skills": ["python", "fastapi"],
            "work_permit": "citizen",
            "salary_expectation": 80000,
        },
    )
    assert cand.status_code == 201, cand.text

    job = await client.post(
        "/api/v1/jobs",
        json={
            "tenant_id": tenant,
            "title": "Backend Dev",
            "must_have_skills": ["python"],
            "requires_work_permit": True,
            "salary_max": 90000,
        },
    )
    assert job.status_code == 201, job.text

    match = await client.post(
        "/api/v1/matching/job",
        json={"tenant_id": tenant, "job_id": job.json()["id"]},
    )
    assert match.status_code == 200, match.text
    results = match.json()
    assert len(results) == 1
    assert results[0]["passed_hard_filters"] is True
    assert results[0]["reasons"]  # has evidence-backed reasons


async def test_receipts_recorded_and_chain_intact(client: AsyncClient) -> None:
    tenant = str(uuid.uuid4())
    job = await client.post(
        "/api/v1/jobs",
        json={"tenant_id": tenant, "title": "Role", "must_have_skills": []},
    )
    await client.post(
        "/api/v1/matching/job",
        json={"tenant_id": tenant, "job_id": job.json()["id"]},
    )
    receipts = await client.get(f"/api/v1/verification/receipts?tenant_id={tenant}")
    assert receipts.status_code == 200
    assert len(receipts.json()) >= 1

    chain = await client.get(
        f"/api/v1/verification/receipts/verify-chain?tenant_id={tenant}"
    )
    assert chain.json()["intact"] is True