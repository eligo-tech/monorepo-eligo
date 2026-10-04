"""Writing down what was said — the conversation that defines a mandate.

Phase 2 of the Prozess-Doku is a briefing call with the hiring manager, and
until now the product had nowhere to put it: the Suchprofil fields held the
OUTCOME (Muss-Kriterien, Band, Ort) and nothing held the conversation. The
awkward part was the schema: `manager_interactions.manager_id` was NOT NULL,
so the note could only be written once a contact existed — while the live
showcase mandate reads "Kein Ansprechpartner hinterlegt".
"""

from __future__ import annotations

import datetime as dt

from httpx import ASGITransport, AsyncClient

from app.main import app


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _job(c: AsyncClient) -> tuple[str, str]:
    company = (await c.post("/api/v1/companies", json={"name": "Briefing GmbH"})).json()
    job = (
        await c.post(
            "/api/v1/jobs",
            json={"title": "Senior Backend", "client_company_id": company["id"]},
        )
    ).json()
    return job["id"], company["id"]


async def test_a_briefing_can_be_written_without_a_contact() -> None:
    async with _api() as c:
        job_id, _ = await _job(c)
        r = await c.post(
            f"/api/v1/jobs/{job_id}/briefings",
            json={
                "interaction_type": "briefing",
                "summary": "Muss: Java, WildFly. Kein Remote vor dem 3. Monat.",
                "occurred_at": "2026-09-18T09:00:00Z",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["manager_id"] is None
        assert r.json()["job_id"] == job_id


async def test_it_comes_back_on_the_mandate() -> None:
    async with _api() as c:
        job_id, _ = await _job(c)
        for n, when in enumerate(("2026-09-01T09:00:00Z", "2026-09-18T09:00:00Z")):
            await c.post(
                f"/api/v1/jobs/{job_id}/briefings",
                json={
                    "interaction_type": "briefing",
                    "summary": f"Runde {n}",
                    "occurred_at": when,
                },
            )
        rows = (await c.get(f"/api/v1/jobs/{job_id}/briefings")).json()
        assert [r["summary"] for r in rows] == ["Runde 1", "Runde 0"], "newest first"


async def test_a_briefing_with_a_contact_shows_in_both_places() -> None:
    """One table, two questions: what did we discuss with her, and what do we
    know about this mandate."""
    async with _api() as c:
        job_id, company_id = await _job(c)
        manager = (
            await c.post(
                "/api/v1/managers",
                json={"company_id": company_id, "full_name": "Frau Brief"},
            )
        ).json()
        await c.post(
            f"/api/v1/jobs/{job_id}/briefings",
            json={
                "interaction_type": "briefing",
                "summary": "Profil geschärft",
                "manager_id": manager["id"],
            },
        )
        on_job = (await c.get(f"/api/v1/jobs/{job_id}/briefings")).json()
        on_manager = (
            await c.get(f"/api/v1/managers/{manager['id']}/interactions")
        ).json()
        assert len(on_job) == 1
        assert [r["id"] for r in on_job] == [r["id"] for r in on_manager]


async def test_an_unknown_mandate_is_refused() -> None:
    async with _api() as c:
        r = await c.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/briefings",
            json={"interaction_type": "briefing", "summary": "x"},
        )
        assert r.status_code == 404


async def test_the_date_defaults_to_now_but_can_be_given() -> None:
    async with _api() as c:
        job_id, _ = await _job(c)
        now = (
            await c.post(
                f"/api/v1/jobs/{job_id}/briefings",
                json={"interaction_type": "briefing", "summary": "heute"},
            )
        ).json()
        assert now["occurred_at"]

        back_then = (
            await c.post(
                f"/api/v1/jobs/{job_id}/briefings",
                json={
                    "interaction_type": "briefing",
                    "summary": "damals",
                    "occurred_at": "2026-07-01T08:30:00Z",
                },
            )
        ).json()
        assert back_then["occurred_at"].startswith("2026-07-01")
        # A briefing recorded late is still dated when it happened — the
        # Suchprofil it produced has to be readable against it.
        assert dt.datetime.fromisoformat(
            back_then["occurred_at"].replace("Z", "+00:00")
        ) < dt.datetime.now(dt.UTC)


async def test_a_whole_transcript_fits() -> None:
    """The input people will actually paste.

    `summary` was capped at 5,000 characters by a validator while the column
    behind it is TEXT. A Qualifikationsgespräch transcript is longer than
    that, and it is the single most valuable thing anyone types into this
    product — so the cap would have been hit by exactly the note worth
    keeping, and hit as a 422 after the writing was done.
    """
    async with _api() as c:
        job_id, _ = await _job(c)
        transcript = (
            "Interviewer: Erzählen Sie von Ihrer Architekturverantwortung.\n"
            "Kandidat: Gerne. Ich verantworte seit 2018 die Architektur …\n"
        ) * 400  # ~44k characters, a realistic hour-long call
        assert len(transcript) > 40_000

        r = await c.post(
            f"/api/v1/jobs/{job_id}/briefings",
            json={"interaction_type": "briefing", "summary": transcript},
        )
        assert r.status_code == 201, r.text[:200]

        [row] = (await c.get(f"/api/v1/jobs/{job_id}/briefings")).json()
        assert row["summary"] == transcript, "stored whole, not truncated"


# --------------------------------------------------------------------------
# Feedback about a candidate — a row per remark, not one field per step
# --------------------------------------------------------------------------


async def _candidate_on(c: AsyncClient, job_id: str, name: str) -> str:
    candidate = (await c.post("/api/v1/candidates", json={"full_name": name})).json()
    await c.post(
        "/api/v1/pipeline/applications",
        json={"candidate_id": candidate["id"], "job_id": job_id},
    )
    return candidate["id"]


async def test_feedback_accumulates_instead_of_overwriting() -> None:
    """THE bug. Feedback was written into the process step's `note`, which is
    one field — so the second remark on a step silently replaced the first,
    and nothing said so. A row per remark means both are still there."""
    async with _api() as c:
        job_id, _ = await _job(c)
        candidate_id = await _candidate_on(c, job_id, "AnonymGE")
        for n, when in enumerate(("2026-09-20T09:00:00Z", "2026-09-22T09:00:00Z")):
            r = await c.post(
                f"/api/v1/jobs/{job_id}/feedback",
                json={
                    "interaction_type": "feedback",
                    "candidate_id": candidate_id,
                    "summary": f"Rückmeldung {n}",
                    "occurred_at": when,
                },
            )
            assert r.status_code == 201, r.text

        rows = (await c.get(f"/api/v1/jobs/{job_id}/feedback")).json()
        assert [r["summary"] for r in rows] == ["Rückmeldung 1", "Rückmeldung 0"]
        assert {r["candidate_id"] for r in rows} == {candidate_id}


async def test_feedback_is_always_about_somebody() -> None:
    """A remark filed against nobody is a remark nobody finds again, and one
    about a person who was never put forward on this mandate is worse."""
    async with _api() as c:
        job_id, _ = await _job(c)
        other = (await c.post("/api/v1/candidates", json={"full_name": "Nicht im Prozess"})).json()

        nobody = await c.post(
            f"/api/v1/jobs/{job_id}/feedback",
            json={"interaction_type": "feedback", "summary": "gut"},
        )
        assert nobody.status_code == 422

        stranger = await c.post(
            f"/api/v1/jobs/{job_id}/feedback",
            json={
                "interaction_type": "feedback",
                "candidate_id": other["id"],
                "summary": "gut",
            },
        )
        assert stranger.status_code == 404


async def test_the_two_lists_do_not_bleed_into_each_other() -> None:
    """"What does the client want?" and "what did they think of him?" are
    different questions. A Muss-Kriterium among the remarks about one person
    is how a briefing gets read as feedback."""
    async with _api() as c:
        job_id, _ = await _job(c)
        candidate_id = await _candidate_on(c, job_id, "AnonymGE")
        await c.post(
            f"/api/v1/jobs/{job_id}/briefings",
            json={"interaction_type": "briefing", "summary": "Muss: Java, WildFly."},
        )
        await c.post(
            f"/api/v1/jobs/{job_id}/feedback",
            json={
                "interaction_type": "feedback",
                "candidate_id": candidate_id,
                "summary": "Kunde: fachlich überzeugend.",
            },
        )

        briefings = (await c.get(f"/api/v1/jobs/{job_id}/briefings")).json()
        feedback = (await c.get(f"/api/v1/jobs/{job_id}/feedback")).json()
        assert [b["summary"] for b in briefings] == ["Muss: Java, WildFly."]
        assert [f["summary"] for f in feedback] == ["Kunde: fachlich überzeugend."]
