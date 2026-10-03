"""The candidate list, and the number that keeps it honest.

The cockpit searches, filters and sorts this list IN THE BROWSER. That is the
right call for a few hundred people — but it makes the page size part of the
contract: 100 rows out of 447 turns every search into a search of the first
hundred names alphabetically, and the failure is indistinguishable from "we
have nobody like that". So the response says how many exist.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_reports_the_whole_pool_not_the_page() -> None:
    async with _api() as c:
        for i in range(5):
            r = await c.post("/api/v1/candidates", json={"full_name": f"Zählkandidat {i}"})
            assert r.status_code == 201, r.text

        page = await c.get("/api/v1/candidates", params={"limit": 2})
        assert page.status_code == 200
        assert len(page.json()) == 2
        assert page.headers["x-total-count"] == "5"

        whole = await c.get("/api/v1/candidates", params={"limit": 1000})
        assert len(whole.json()) == 5


async def test_an_empty_pool_counts_zero() -> None:
    async with _api() as c:
        r = await c.get("/api/v1/candidates")
        assert r.json() == []
        assert r.headers["x-total-count"] == "0"


async def test_the_page_can_hold_more_than_the_old_ceiling() -> None:
    # The cap was 500 while the live pool was already 447. A limit the data
    # is about to cross is a bug with a date on it.
    async with _api() as c:
        r = await c.get("/api/v1/candidates", params={"limit": 1000})
        assert r.status_code == 200
        assert (await c.get("/api/v1/candidates", params={"limit": 1001})).status_code == 422
