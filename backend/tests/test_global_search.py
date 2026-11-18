"""ELI-52: the cockpit's search box — one query across this workspace's
candidates, mandates, companies and contacts.

Tenant-scoped like every read, and never the shared Markt corpus: a recruiter
typing a name wants their own records, not 700,000 public ads.
"""

from __future__ import annotations

import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.hub.models import HubCompany
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager
from app.domain.search import service

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000052")
OTHER = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
NOW = dt.datetime(2026, 11, 18, tzinfo=dt.UTC)


async def _seed() -> dict[str, str]:
    async with SessionLocal() as s:
        berg = Company(tenant_id=TENANT, name="Bergfreunde GmbH", location="Tübingen")
        other_co = Company(tenant_id=OTHER, name="Bergbau Fremd AG")
        s.add_all([berg, other_co])
        await s.flush()
        cand = Candidate(
            tenant_id=TENANT,
            full_name="Anna Berger",
            current_title="CTO",
            current_company="Acme",
            email="anna@example.com",
            phone="+49 111",
        )
        job = Job(tenant_id=TENANT, title="Bergführer (m/w/d)", client_company_id=berg.id, location="Tübingen")
        lead = Manager(
            tenant_id=TENANT,
            company_id=berg.id,
            full_name="Petra Vogel",
            role_title="HR",
            stage="bus_dev",
            email="petra@berg.de",
            phone="+49 222",
        )
        mgr = Manager(tenant_id=TENANT, company_id=berg.id, full_name="Klaus Mann", role_title="CEO")
        s.add_all([cand, job, lead, mgr])
        s.add_all(
            [
                Candidate(tenant_id=OTHER, full_name="Bert Bergmann"),
                Job(tenant_id=OTHER, title="Bergwerk Leitung"),
                Manager(tenant_id=OTHER, company_id=other_co.id, full_name="Berta Fremd"),
                HubCompany(
                    name="Bergmarkt Corpus GmbH",
                    normalized_name="bergmarkt corpus",
                    dedupe_key="name:bergmarkt corpus",
                    resolution_basis="name",
                    source="ba",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                ),
            ]
        )
        await s.commit()
        return {
            "cand": str(cand.id),
            "job": str(job.id),
            "berg": str(berg.id),
            "lead": str(lead.id),
            "mgr": str(mgr.id),
        }


async def test_finds_every_kind_in_this_workspace_only() -> None:
    ids = await _seed()
    async with SessionLocal() as s:
        out = (await service.search(s, tenant_id=TENANT, q="berg")).model_dump()

    assert [c["id"] for c in out["candidates"]] == [ids["cand"]]
    assert out["candidates"][0]["label"] == "Anna Berger"
    assert [j["id"] for j in out["jobs"]] == [ids["job"]]
    assert "Bergfreunde GmbH" in out["jobs"][0]["subtitle"]
    assert [c["id"] for c in out["companies"]] == [ids["berg"]]
    # A contact is found by the company too — "the CTO at Bergfreunde".
    assert {c["id"] for c in out["contacts"]} == {ids["lead"], ids["mgr"]}
    kinds = {c["id"]: c["kind"] for c in out["contacts"]}
    assert kinds == {ids["lead"]: "lead", ids["mgr"]: "manager"}

    text = str(out)
    assert "Fremd" not in text and "Bergmann" not in text and "Bergwerk" not in text
    # Never the shared Markt corpus.
    assert "Bergmarkt" not in text


async def test_results_carry_no_contact_data() -> None:
    await _seed()
    async with SessionLocal() as s:
        out = (await service.search(s, tenant_id=TENANT, q="an")).model_dump()
    assert out["candidates"] and out["contacts"]
    text = str(out)
    for secret in ("anna@example.com", "petra@berg.de", "+49 111", "+49 222"):
        assert secret not in text


async def test_short_query_and_wildcards_find_nothing() -> None:
    await _seed()
    async with SessionLocal() as s:
        for q in ("", " ", "b", "%%", "__"):
            out = (await service.search(s, tenant_id=TENANT, q=q)).model_dump()
            assert all(v == [] for v in out.values()), q


async def test_limit_per_group() -> None:
    async with SessionLocal() as s:
        s.add_all([Candidate(tenant_id=TENANT, full_name=f"Müller {i}") for i in range(9)])
        await s.commit()
    async with SessionLocal() as s:
        out = await service.search(s, tenant_id=TENANT, q="Müller", limit=5)
    assert len(out.candidates) == 5


async def test_the_route_is_tenant_scoped() -> None:
    from app.core.auth import get_current_tenant
    from app.main import app

    ids = await _seed()
    try:
        app.dependency_overrides[get_current_tenant] = lambda: OTHER
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            other = await c.get("/api/v1/search", params={"q": "berg"})
        app.dependency_overrides[get_current_tenant] = lambda: TENANT
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            mine = await c.get("/api/v1/search", params={"q": "berg"})
            empty = await c.get("/api/v1/search")
    finally:
        app.dependency_overrides.pop(get_current_tenant, None)

    assert other.status_code == 200, other.text
    assert mine.status_code == 200 and empty.status_code == 200
    for v in ids.values():
        assert v not in other.text
    assert [r["label"] for r in other.json()["candidates"]] == ["Bert Bergmann"]
    assert mine.json()["candidates"][0]["id"] == ids["cand"]
    assert empty.json() == {"candidates": [], "jobs": [], "companies": [], "contacts": []}
