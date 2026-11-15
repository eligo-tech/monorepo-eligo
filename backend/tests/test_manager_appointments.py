"""Termine on a manager (ELI-40): choosing "Meeting" in the composer puts it
in the calendar.

A Termin is not a new kind of row. It is a `manager_interactions` row whose
kind is an appointment kind (today: `meeting`) — the composer already writes
that row, and a second table holding the same meeting could only drift from
it. A future date is a scheduled meeting; a past one, a meeting that happened.
"""

from __future__ import annotations

import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.common.enums import APPOINTMENT_INTERACTION_KINDS
from app.domain.companies.models import Company
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = settings.default_tenant_id
API = settings.api_v1_prefix


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_manager(tenant_id: uuid.UUID = TENANT) -> uuid.UUID:
    async with SessionLocal() as session:
        company = Company(tenant_id=tenant_id, name="Zühlke Engineering GmbH")
        session.add(company)
        await session.flush()
        manager = Manager(tenant_id=tenant_id, company_id=company.id, full_name="Achim Dreyer")
        session.add(manager)
        await session.commit()
        return manager.id


def _iso(when: dt.datetime) -> str:
    return when.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def test_a_meeting_is_the_appointment_kind() -> None:
    assert APPOINTMENT_INTERACTION_KINDS == frozenset({"meeting"})


async def test_a_meeting_saved_from_the_composer_is_in_the_termine_list() -> None:
    await create_all()
    manager_id = await _a_manager()
    when = dt.datetime.now(dt.UTC).replace(microsecond=0) + dt.timedelta(days=3, hours=2)

    async with _api() as client:
        created = await client.post(
            f"{API}/managers/{manager_id}/interactions",
            json={"interaction_type": "meeting", "summary": "Kickoff vor Ort", "occurred_at": _iso(when)},
        )
        assert created.status_code == 201, created.text
        await client.post(
            f"{API}/managers/{manager_id}/interactions",
            json={"interaction_type": "business_call", "summary": "kein Termin"},
        )
        listed = await client.get(f"{API}/managers/{manager_id}/appointments")

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [r["summary"] for r in rows] == ["Kickoff vor Ort"]
    # The time survives — a Termin at 14:00 is not a Termin at noon.
    assert dt.datetime.fromisoformat(rows[0]["occurred_at"].replace("Z", "+00:00")) == when


async def test_a_retired_meeting_spelling_is_a_termin_too() -> None:
    """aiFind wrote "Meeting Notes"; those rows are meetings and must show."""
    await create_all()
    manager_id = await _a_manager()
    async with SessionLocal() as session:
        session.add(
            ManagerInteraction(
                tenant_id=TENANT,
                manager_id=manager_id,
                interaction_type="Meeting Notes",
                occurred_at=dt.datetime(2026, 3, 1, 10, tzinfo=dt.UTC),
                summary="importiert",
            )
        )
        await session.commit()

    async with _api() as client:
        rows = (await client.get(f"{API}/managers/{manager_id}/appointments")).json()

    assert [(r["interaction_type"], r["summary"]) for r in rows] == [("meeting", "importiert")]


async def test_another_workspaces_manager_has_no_termine_here() -> None:
    await create_all()
    foreign = await _a_manager(uuid.uuid4())
    async with SessionLocal() as session:
        session.add(
            ManagerInteraction(
                tenant_id=uuid.uuid4(),
                manager_id=foreign,
                interaction_type="meeting",
                occurred_at=dt.datetime(2026, 3, 1, 10, tzinfo=dt.UTC),
                summary="fremd",
            )
        )
        await session.commit()

    async with _api() as client:
        resp = await client.get(f"{API}/managers/{foreign}/appointments")

    assert resp.status_code == 404


async def test_a_scheduled_meeting_does_not_move_last_contact_into_the_future() -> None:
    """Booking next Thursday's meeting is not having spoken to them next
    Thursday — "Letzter Kontakt" must not show a date that has not happened."""
    await create_all()
    manager_id = await _a_manager()
    future = dt.datetime.now(dt.UTC) + dt.timedelta(days=7)

    async with _api() as client:
        await client.post(
            f"{API}/managers/{manager_id}/interactions",
            json={"interaction_type": "meeting", "summary": "geplant", "occurred_at": _iso(future)},
        )
        profile = await client.get(f"{API}/managers/{manager_id}")

    assert profile.json()["last_contact_at"] is None


async def test_a_past_meeting_still_moves_last_contact() -> None:
    await create_all()
    manager_id = await _a_manager()

    async with _api() as client:
        await client.post(
            f"{API}/managers/{manager_id}/interactions",
            json={"interaction_type": "meeting", "summary": "war gut", "occurred_at": "2026-10-01T14:30:00Z"},
        )
        profile = await client.get(f"{API}/managers/{manager_id}")

    assert (profile.json()["last_contact_at"] or "").startswith("2026-10-01")
