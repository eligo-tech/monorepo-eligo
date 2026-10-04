"""Adding a step to one process, and taking one out.

The nine steps are a template, not a law: a Probearbeitstag or an Assessment
Center is ordinary, and a checklist that cannot hold it sends the recruiter
back to the spreadsheet for exactly the row that does not fit.

Two rules this pins:
  * a removed CANONICAL step must stay removed — the template would otherwise
    put it straight back on the next read;
  * a step that already HAPPENED cannot be removed, because a date and a
    verdict are the record of something that took place.
"""

from __future__ import annotations

import datetime as dt

from httpx import ASGITransport, AsyncClient

from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _process(c: AsyncClient) -> tuple[str, str]:
    company = (await c.post("/api/v1/companies", json={"name": "Schritt GmbH"})).json()
    job = (
        await c.post(
            "/api/v1/jobs",
            json={"title": "Backend", "client_company_id": company["id"]},
        )
    ).json()
    cand = (await c.post("/api/v1/candidates", json={"full_name": "Pia Prozess"})).json()
    appl = (
        await c.post(
            "/api/v1/pipeline/applications",
            json={"candidate_id": cand["id"], "job_id": job["id"]},
        )
    ).json()
    # A job reaches "Laufende Prozesse" once the first candidate is presented
    # (process doc §3), so every fixture here starts there.
    await c.patch(
        f"/api/v1/pipeline/applications/{appl['id']}/steps/vorgestellt",
        json={"done_at": dt.datetime(2026, 8, 20, tzinfo=dt.UTC).isoformat()},
    )
    return appl["id"], job["id"]


async def _steps(c: AsyncClient, job_id: str) -> dict:
    rows = (await c.get("/api/v1/pipeline/processes")).json()
    job = next(j for j in rows if j["job_id"] == job_id)
    return job["candidates"][0]


async def test_a_step_can_be_added_after_a_named_one() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        r = await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps",
            json={"label": "Probearbeitstag", "after": "feedback-2"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["step_key"] == "custom_probearbeitstag"
        assert body["label"] == "Probearbeitstag"
        assert body["custom"] is True
        # It takes a date, because that is what one is for.
        assert body["kind"] == "appointment"

        person = await _steps(c, job_id)
        assert "custom_probearbeitstag" in person["step_order"]


async def test_the_added_step_sorts_where_it_was_put() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/feedback-1",
            json={"done_at": dt.datetime(2026, 9, 1, tzinfo=dt.UTC).isoformat()},
        )
        await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps",
            json={"label": "Kennenlernen Team", "after": "vorgestellt"},
        )
        keys = (await _steps(c, job_id))["step_order"]
        assert keys.index("custom_kennenlernen-team") == keys.index("vorgestellt") + 1
        assert keys.index("custom_kennenlernen-team") < keys.index("feedback-1")


async def test_without_an_anchor_the_step_goes_first() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps",
            json={"label": "Erstkontakt"},
        )
        assert (await _steps(c, job_id))["step_order"][0] == "custom_erstkontakt"


async def test_a_removed_canonical_step_stays_removed() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        r = await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/final-vorb")
        assert r.status_code == 204, r.text

        person = await _steps(c, job_id)
        assert "final-vorb" not in person["step_order"]
        assert all(s["step_key"] != "final-vorb" for s in person["steps"])


async def test_ticking_a_removed_step_brings_it_back() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/final-vorb")
        await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/final-vorb",
            json={"done_at": dt.datetime(2026, 9, 9, tzinfo=dt.UTC).isoformat()},
        )
        person = await _steps(c, job_id)
        assert "final-vorb" in person["step_order"]
        assert any(s["step_key"] == "final-vorb" for s in person["steps"])


async def test_a_step_that_happened_cannot_be_removed() -> None:
    async with _api() as c:
        app_id, _ = await _process(c)
        r = await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/vorgestellt")
        assert r.status_code == 409
        assert "stattgefunden" in r.json()["detail"]


async def test_clearing_the_entry_makes_it_removable_again() -> None:
    async with _api() as c:
        app_id, _ = await _process(c)
        await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/interview",
            json={"done_at": dt.datetime(2026, 9, 1, tzinfo=dt.UTC).isoformat()},
        )
        await c.patch(
            f"/api/v1/pipeline/applications/{app_id}/steps/interview",
            json={"clear": ["done_at"], "outcome": "open"},
        )
        r = await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/interview")
        assert r.status_code == 204


async def test_a_custom_step_can_be_removed_while_still_open() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        key = (
            await c.post(
                f"/api/v1/pipeline/applications/{app_id}/steps",
                json={"label": "Probetag", "after": "feedback-2"},
            )
        ).json()["step_key"]
        assert (
            await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/{key}")
        ).status_code == 204
        person = await _steps(c, job_id)
        assert all(s["step_key"] != key for s in person["steps"])
        assert key not in person["step_order"]


async def test_two_steps_with_the_same_name_do_not_collide() -> None:
    async with _api() as c:
        app_id, _ = await _process(c)
        first = await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps", json={"label": "Probetag"}
        )
        second = await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps", json={"label": "Probetag"}
        )
        assert first.json()["step_key"] != second.json()["step_key"]


async def test_an_empty_label_is_refused() -> None:
    async with _api() as c:
        app_id, _ = await _process(c)
        r = await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps", json={"label": "   "}
        )
        assert r.status_code in (404, 422)


async def test_the_history_records_both_edits() -> None:
    async with _api() as c:
        app_id, _ = await _process(c)
        await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps", json={"label": "Probetag"}
        )
        await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/final-vorb")
        row = (await c.get("/api/v1/pipeline/applications")).json()
        app_row = next(a for a in row if a["id"] == app_id)
        events = [h.get("event") for h in app_row.get("history", [])]
        assert "step_added" in events
        assert "step_removed" in events


async def test_several_added_steps_keep_their_order() -> None:
    """Three steps between the same pair must not collapse into one slot."""
    async with _api() as c:
        app_id, job_id = await _process(c)
        for label in ("Probetag", "Teamlunch", "Hospitation"):
            r = await c.post(
                f"/api/v1/pipeline/applications/{app_id}/steps",
                json={"label": label, "after": "feedback-2"},
            )
            assert r.status_code == 201, r.text

        order = (await _steps(c, job_id))["step_order"]
        start = order.index("feedback-2")
        # Each insert goes directly after the anchor, so the newest is first —
        # the same thing a recruiter sees when they add one more.
        assert order[start + 1 : start + 4] == [
            "custom_hospitation",
            "custom_teamlunch",
            "custom_probetag",
        ]
        assert order[start + 4] == "finaltermin"


async def test_the_order_survives_a_removal_in_the_middle() -> None:
    async with _api() as c:
        app_id, job_id = await _process(c)
        await c.post(
            f"/api/v1/pipeline/applications/{app_id}/steps",
            json={"label": "Probetag", "after": "interview"},
        )
        await c.delete(f"/api/v1/pipeline/applications/{app_id}/steps/vorbereitung")
        order = (await _steps(c, job_id))["step_order"]
        assert "vorbereitung" not in order
        assert order.index("custom_probetag") == order.index("interview") + 1


async def test_assigning_the_same_candidate_twice_is_one_process() -> None:
    """A double click is not a second process.

    Two rows would put the same person under the mandate twice, each with
    its own step list, and the first one ticked would look like the other
    had not happened.
    """
    async with _api() as c:
        company = (await c.post("/api/v1/companies", json={"name": "Doppel GmbH"})).json()
        job = (
            await c.post(
                "/api/v1/jobs",
                json={"title": "Backend", "client_company_id": company["id"]},
            )
        ).json()
        cand = (
            await c.post("/api/v1/candidates", json={"full_name": "Dana Doppel"})
        ).json()
        body = {"candidate_id": cand["id"], "job_id": job["id"]}
        first = (await c.post("/api/v1/pipeline/applications", json=body)).json()
        second = (await c.post("/api/v1/pipeline/applications", json=body)).json()
        assert first["id"] == second["id"]

        rows = (await c.get("/api/v1/pipeline/processes")).json()
        [entry] = [j for j in rows if j["job_id"] == job["id"]]
        assert len(entry["candidates"]) == 1
