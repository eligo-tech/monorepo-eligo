"""Wiedervorlagen (ELI-44): a dated to-do on a lead, a manager or a candidate.

"Aktuell kann ich bei Managern Ereignisse hinzufügen, aber keine Follow-Up
erstellen." A follow-up is its own tenant row — due date (time optional),
a short text, open until somebody marks it done — attached to exactly one
person: a `managers` row (Leads and Manager are both that table) or a
candidate. It may point at the note it came from.

Nothing here creates one on its own: `/follow-ups/suggest` only READS a note
and offers dates; a person confirms by creating it.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.followups.models import FollowUp
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = settings.default_tenant_id
API = settings.api_v1_prefix


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _people(tenant_id: uuid.UUID = TENANT) -> dict:
    async with SessionLocal() as s:
        company = Company(tenant_id=tenant_id, name="Zühlke Engineering GmbH")
        s.add(company)
        await s.flush()
        lead = Manager(tenant_id=tenant_id, company_id=company.id, full_name="Petra Weber", stage="bus_dev")
        boss = Manager(tenant_id=tenant_id, company_id=company.id, full_name="Achim Dreyer")
        cand = Candidate(tenant_id=tenant_id, full_name="Erika Muster")
        s.add_all([lead, boss, cand])
        await s.commit()
        return {"company": company.id, "lead": lead.id, "manager": boss.id, "candidate": cand.id}


async def test_a_follow_up_on_a_lead_from_its_note() -> None:
    await create_all()
    p = await _people()
    async with _api() as client:
        note = await client.post(
            f"{API}/managers/{p['lead']}/interactions",
            json={"interaction_type": "business_call", "summary": "Kein Bedarf, Anfang Februar wieder melden."},
        )
        assert note.status_code == 201, note.text
        created = await client.post(
            f"{API}/follow-ups",
            json={
                "manager_id": str(p["lead"]),
                "due_date": "2027-02-01",
                "text": "Wieder melden — Bedarf 2027?",
                "source_interaction_id": note.json()["id"],
                "origin": "note",
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()
        listed = await client.get(f"{API}/follow-ups")

    assert row["status"] == "open"
    assert row["due_date"] == "2027-02-01"
    assert row["due_time"] is None
    assert row["origin"] == "note"
    assert row["source_interaction_id"] == note.json()["id"]
    # What the to-do list needs to link to the person and say who they are.
    assert row["subject_kind"] == "lead"
    assert row["person_name"] == "Petra Weber"
    assert row["company_name"] == "Zühlke Engineering GmbH"
    assert row["company_id"] == str(p["company"])
    assert [r["id"] for r in listed.json()] == [row["id"]]


async def test_on_a_manager_and_on_a_candidate_with_a_time() -> None:
    await create_all()
    p = await _people()
    async with _api() as client:
        m = await client.post(
            f"{API}/follow-ups",
            json={"manager_id": str(p["manager"]), "due_date": "2026-12-01", "due_time": "09:30", "text": "Shortlist"},
        )
        c = await client.post(
            f"{API}/follow-ups",
            json={"candidate_id": str(p["candidate"]), "due_date": "2026-11-20", "text": "Gehalt klären"},
        )
        assert m.status_code == 201, m.text
        assert c.status_code == 201, c.text
        on_candidate = await client.get(f"{API}/follow-ups", params={"candidate_id": str(p["candidate"])})
        everything = await client.get(f"{API}/follow-ups")

    assert m.json()["subject_kind"] == "manager"
    assert m.json()["due_time"] == "09:30:00"
    assert c.json()["subject_kind"] == "candidate"
    assert c.json()["person_name"] == "Erika Muster"
    assert c.json()["company_name"] is None
    assert [r["text"] for r in on_candidate.json()] == ["Gehalt klären"]
    # Soonest first: the list is a to-do list.
    assert [r["text"] for r in everything.json()] == ["Gehalt klären", "Shortlist"]


@pytest.mark.parametrize(
    "body",
    [
        {"due_date": "2027-02-01", "text": "niemand"},
        {"manager_id": "MANAGER", "candidate_id": "CANDIDATE", "due_date": "2027-02-01", "text": "beide"},
        {"manager_id": "MANAGER", "due_date": "2027-02-01", "text": "   "},
        {"manager_id": "MANAGER", "due_date": "2027-02-01", "text": "x" * 501},
        {"manager_id": "MANAGER", "text": "ohne Datum"},
    ],
)
async def test_exactly_one_person_a_date_and_a_short_text(body: dict) -> None:
    await create_all()
    p = await _people()
    body = {
        k: (str(p["manager"]) if v == "MANAGER" else str(p["candidate"]) if v == "CANDIDATE" else v)
        for k, v in body.items()
    }
    async with _api() as client:
        r = await client.post(f"{API}/follow-ups", json=body)
    assert r.status_code == 422, r.text


async def test_done_edit_reopen() -> None:
    await create_all()
    p = await _people()
    async with _api() as client:
        row = (
            await client.post(
                f"{API}/follow-ups", json={"manager_id": str(p["manager"]), "due_date": "2026-11-18", "text": "Anrufen"}
            )
        ).json()
        moved = await client.patch(f"{API}/follow-ups/{row['id']}", json={"due_date": "2026-11-25", "text": "Später anrufen"})
        done = await client.patch(f"{API}/follow-ups/{row['id']}", json={"status": "done"})
        open_after = await client.get(f"{API}/follow-ups")
        done_list = await client.get(f"{API}/follow-ups", params={"status": "done"})
        reopened = await client.patch(f"{API}/follow-ups/{row['id']}", json={"status": "open"})

    assert moved.status_code == 200, moved.text
    assert moved.json()["due_date"] == "2026-11-25"
    assert moved.json()["text"] == "Später anrufen"
    assert done.json()["status"] == "done"
    assert done.json()["done_at"] is not None
    # Done drops off the to-do list, and is still there to look back at.
    assert open_after.json() == []
    assert [r["id"] for r in done_list.json()] == [row["id"]]
    assert reopened.json()["status"] == "open"
    assert reopened.json()["done_at"] is None


async def test_an_admin_deletes_anyones_and_a_recruiter_none() -> None:
    """ELI-27: deleting is an admin's job (the route-table walk in
    `test_delete_admin_only.py` attacks this route as a recruiter too).
    Marking done is everyone's."""
    from app.core.auth import RECRUITER, Actor, get_current_actor
    from app.main import app

    await create_all()
    p = await _people()
    async with SessionLocal() as s:
        theirs = FollowUp(
            tenant_id=TENANT, manager_id=p["manager"], due_date=dt.date(2026, 12, 1), text="von Kollegin",
            created_by_user_id="user_colleague",
        )
        s.add(theirs)
        await s.commit()
        theirs_id = theirs.id
    async with _api() as client:
        mine = (
            await client.post(f"{API}/follow-ups", json={"manager_id": str(p["manager"]), "due_date": "2026-12-01", "text": "meins"})
        ).json()
        app.dependency_overrides[get_current_actor] = lambda: Actor(
            tenant_id=TENANT, user_id="user_r", name="R", role=RECRUITER, role_known=True
        )
        try:
            refused = await client.delete(f"{API}/follow-ups/{mine['id']}")
            done = await client.patch(f"{API}/follow-ups/{theirs_id}", json={"status": "done"})
        finally:
            app.dependency_overrides.pop(get_current_actor, None)
        deleted = await client.delete(f"{API}/follow-ups/{theirs_id}")
        left = await client.get(f"{API}/follow-ups", params={"status": "all"})

    assert refused.status_code == 403
    assert done.status_code == 200
    assert done.json()["done_by_name"] == "R"
    assert deleted.status_code == 204
    assert [r["text"] for r in left.json()] == ["meins"]


async def test_another_workspace_is_invisible_and_untouchable() -> None:
    await create_all()
    mine = await _people()
    other_tenant = uuid.uuid4()
    theirs = await _people(other_tenant)
    async with SessionLocal() as s:
        foreign = FollowUp(tenant_id=other_tenant, manager_id=theirs["manager"], due_date=dt.date(2026, 12, 1), text="fremd")
        s.add(foreign)
        await s.commit()
        foreign_id = foreign.id
    async with _api() as client:
        listed = await client.get(f"{API}/follow-ups")
        patched = await client.patch(f"{API}/follow-ups/{foreign_id}", json={"status": "done"})
        deleted = await client.delete(f"{API}/follow-ups/{foreign_id}")
        # Attaching one to another workspace's person is refused too.
        attach = await client.post(
            f"{API}/follow-ups", json={"manager_id": str(theirs["manager"]), "due_date": "2026-12-01", "text": "x"}
        )
        attach_c = await client.post(
            f"{API}/follow-ups", json={"candidate_id": str(theirs["candidate"]), "due_date": "2026-12-01", "text": "x"}
        )
        # ... and so is pointing at another workspace's note.
        async with SessionLocal() as s:
            note = ManagerInteraction(
                tenant_id=other_tenant, manager_id=theirs["manager"], interaction_type="note",
                occurred_at=dt.datetime.now(dt.UTC), summary="fremd",
            )
            s.add(note)
            await s.commit()
            note_id = note.id
        attach_n = await client.post(
            f"{API}/follow-ups",
            json={"manager_id": str(mine["manager"]), "due_date": "2026-12-01", "text": "x", "source_interaction_id": str(note_id)},
        )

    assert listed.json() == []
    assert patched.status_code == 404
    assert deleted.status_code == 404
    assert attach.status_code == 404
    assert attach_c.status_code == 404
    assert attach_n.status_code == 404


async def test_suggest_reads_the_note_and_creates_nothing() -> None:
    await create_all()
    async with _api() as client:
        r = await client.post(
            f"{API}/follow-ups/suggest",
            json={"text": "Aktuell brauchen sie nichts, ich soll mich Anfang Februar wieder melden.", "reference_date": "2026-11-17"},
        )
        none = await client.post(f"{API}/follow-ups/suggest", json={"text": "Kein Interesse.", "reference_date": "2026-11-17"})
    assert r.status_code == 200, r.text
    assert r.json() == {"suggestions": [{"due_date": "2027-02-01", "phrase": "Anfang Februar"}]}
    assert none.json() == {"suggestions": []}
    async with SessionLocal() as s:
        assert (await s.execute(select(FollowUp))).first() is None


async def test_erasing_the_person_erases_their_follow_ups(monkeypatch) -> None:
    from app.domain.erasure import service as erasure

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    await create_all()
    p = await _people()
    async with SessionLocal() as s:
        s.add_all([
            FollowUp(tenant_id=TENANT, manager_id=p["manager"], due_date=dt.date(2026, 12, 1), text="Achim anrufen"),
            FollowUp(tenant_id=TENANT, candidate_id=p["candidate"], due_date=dt.date(2026, 12, 1), text="Erika anrufen"),
            FollowUp(tenant_id=TENANT, manager_id=p["lead"], due_date=dt.date(2026, 12, 1), text="bleibt"),
        ])
        await s.commit()
    async with SessionLocal() as s:
        await erasure.erase_manager(
            s, tenant_id=TENANT, manager_id=p["manager"], confirm_name="Achim Dreyer", reason="objection",
            requested_on=dt.date(2026, 11, 17), actor_user_id="u", actor_name="A",
        )
        await erasure.erase_candidate(
            s, tenant_id=TENANT, candidate_id=p["candidate"], confirm_name="Erika Muster", reason="erasure",
            requested_on=dt.date(2026, 11, 17), actor_user_id="u", actor_name="A",
        )
        await s.commit()
    async with SessionLocal() as s:
        left = (await s.scalars(select(FollowUp.text))).all()
    assert left == ["bleibt"]


async def test_a_note_about_someone_else_is_not_a_source() -> None:
    await create_all()
    p = await _people()
    async with SessionLocal() as s:
        note = ManagerInteraction(
            tenant_id=TENANT, manager_id=p["lead"], interaction_type="note",
            occurred_at=dt.datetime.now(dt.UTC), summary="über Petra",
        )
        s.add(note)
        await s.commit()
        note_id = note.id
    async with _api() as client:
        r = await client.post(
            f"{API}/follow-ups",
            json={"manager_id": str(p["manager"]), "due_date": "2026-12-01", "text": "x", "source_interaction_id": str(note_id)},
        )
    assert r.status_code == 404


async def test_erasing_a_candidate_takes_a_follow_up_copied_from_a_note_about_them(monkeypatch) -> None:
    """A manager note can name a candidate; a follow-up confirmed from it
    carries the note's text. Erasing the candidate deletes the note — and
    the follow-up that copied it (review of #277)."""
    from app.domain.erasure import service as erasure

    monkeypatch.setattr(settings, "suppression_key", "k" * 40)
    await create_all()
    p = await _people()
    async with SessionLocal() as s:
        note = ManagerInteraction(
            tenant_id=TENANT, manager_id=p["manager"], candidate_id=p["candidate"], interaction_type="note",
            occurred_at=dt.datetime.now(dt.UTC), summary="Erika Muster vorgestellt, Anfang Februar Feedback",
        )
        s.add(note)
        await s.flush()
        s.add(FollowUp(
            tenant_id=TENANT, manager_id=p["manager"], due_date=dt.date(2027, 2, 1),
            text="Erika Muster vorgestellt, Anfang Februar Feedback", source_interaction_id=note.id, origin="note",
        ))
        await s.commit()
    async with SessionLocal() as s:
        await erasure.erase_candidate(
            s, tenant_id=TENANT, candidate_id=p["candidate"], confirm_name="Erika Muster", reason="erasure",
            requested_on=dt.date(2026, 11, 17), actor_user_id="u", actor_name="A",
        )
        await s.commit()
    async with SessionLocal() as s:
        assert (await s.scalars(select(FollowUp.text))).all() == []


async def test_suggest_refuses_an_unbounded_text() -> None:
    await create_all()
    async with _api() as client:
        r = await client.post(f"{API}/follow-ups/suggest", json={"text": "x" * 20_001, "reference_date": "2026-11-17"})
    assert r.status_code == 422
