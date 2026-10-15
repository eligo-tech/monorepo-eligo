"""Setting a mandate up: the client, the job, and who to call there.

This is the first thing a new workspace has to be able to do, and none of it
was reachable. `POST /jobs` existed; `jobs.manager_id` existed since the first
migration and appeared in NO schema — not `JobCreate`, not `JobUpdate`, not
`JobRead` — so a mandate could only ever read "Kein Ansprechpartner
hinterlegt" and point the reader at a different screen.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _client_with_contact(c: AsyncClient, name: str) -> tuple[str, str]:
    company = (await c.post("/api/v1/companies", json={"name": name})).json()
    manager = (
        await c.post(
            "/api/v1/managers",
            json={
                "company_id": company["id"],
                "full_name": f"Head of IT · {name}",
                "source": "self_reported",
            },
        )
    ).json()
    return company["id"], manager["id"]


async def test_a_mandate_can_be_created_with_its_contact() -> None:
    async with _api() as c:
        company_id, manager_id = await _client_with_contact(c, "Linde + Wiemann")
        created = await c.post(
            "/api/v1/jobs",
            json={
                "title": "IT-Administrator produktionsnahe IT / OT",
                "client_company_id": company_id,
                "manager_id": manager_id,
                "location": "Dillenburg",
                "salary_min": 60000,
                "salary_max": 70000,
                "must_have_skills": ["Produktionsnahe IT (OT)"],
            },
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["manager_id"] == manager_id
        # And it comes back on a read, which is what the mandate renders.
        assert (await c.get(f"/api/v1/jobs/{job['id']}")).json()["manager_id"] == manager_id


async def test_a_contact_at_another_client_is_refused() -> None:
    """The row would look valid either way — `manager_id` is a UUID — and the
    shortlist would go to someone at the wrong company."""
    async with _api() as c:
        ours, _ = await _client_with_contact(c, "Linde + Wiemann")
        _, theirs = await _client_with_contact(c, "Ganz andere GmbH")

        refused = await c.post(
            "/api/v1/jobs",
            json={"title": "IT-Admin", "client_company_id": ours, "manager_id": theirs},
        )
        assert refused.status_code == 422
        assert "client" in refused.json()["detail"]


async def test_the_contact_can_be_set_later_and_is_checked_then_too() -> None:
    """The commonest real order: the mandate exists, the contact comes after."""
    async with _api() as c:
        company_id, manager_id = await _client_with_contact(c, "Linde + Wiemann")
        job = (
            await c.post(
                "/api/v1/jobs",
                json={"title": "IT-Admin", "client_company_id": company_id},
            )
        ).json()
        assert job["manager_id"] is None

        patched = await c.patch(
            f"/api/v1/jobs/{job['id']}", json={"manager_id": manager_id}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["manager_id"] == manager_id

        _, theirs = await _client_with_contact(c, "Ganz andere GmbH")
        assert (
            await c.patch(f"/api/v1/jobs/{job['id']}", json={"manager_id": theirs})
        ).status_code == 422

        # Moving the mandate to another client with the old contact still on
        # it is the same mistake arriving from the other side.
        other_company = (
            await c.post("/api/v1/companies", json={"name": "Dritte GmbH"})
        ).json()
        assert (
            await c.patch(
                f"/api/v1/jobs/{job['id']}",
                json={"client_company_id": other_company["id"]},
            )
        ).status_code == 422


async def test_a_mandate_without_a_contact_is_still_a_mandate() -> None:
    """A search can start before anybody knows who to call — the showcase
    mandate literally did. Refusing it would mean nothing gets written down."""
    async with _api() as c:
        company = (await c.post("/api/v1/companies", json={"name": "Neu GmbH"})).json()
        created = await c.post(
            "/api/v1/jobs",
            json={"title": "IT-Admin", "client_company_id": company["id"]},
        )
        assert created.status_code == 201
        assert created.json()["manager_id"] is None


async def test_setting_the_contact_leaves_a_receipt() -> None:
    """Same discipline as the band: who put which contact on this mandate,
    and when, is a question the ledger has to answer."""
    async with _api() as c:
        company_id, manager_id = await _client_with_contact(c, "Linde + Wiemann")
        job = (
            await c.post(
                "/api/v1/jobs",
                json={"title": "IT-Admin", "client_company_id": company_id},
            )
        ).json()
        await c.patch(f"/api/v1/jobs/{job['id']}", json={"manager_id": manager_id})

        trail = await c.get(f"/api/v1/verification/history/job/{job['id']}")
        assert trail.status_code == 200, trail.text
        assert any(
            e.get("field") == "manager_id" for e in trail.json()
        ), trail.json()
