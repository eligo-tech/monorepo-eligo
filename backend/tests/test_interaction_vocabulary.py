"""One vocabulary for conversation notes, and the rows that predate it.

Three lists described the same thing before ELI-9: this enum, the strings the
aiFind import wrote, and the list the recruiters actually use. That is the
same three-way split that made 18 mandates unsaveable in ELI-7, so the tests
here are mostly about the seams between them.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.candidates.models import Candidate
from app.domain.common.enums import (
    CANDIDATE_INTERACTION_KINDS,
    CONTACT_INTERACTION_KINDS,
    MANAGER_INTERACTION_KINDS,
    InteractionType,
    normalise_interaction_type,
)
from app.domain.companies.models import Company
from app.domain.managers.models import Manager, ManagerInteraction

TENANT = settings.default_tenant_id


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_manager() -> uuid.UUID:
    async with SessionLocal() as session:
        company = Company(tenant_id=TENANT, name="Kunde GmbH")
        session.add(company)
        await session.flush()
        manager = Manager(
            tenant_id=TENANT, company_id=company.id, full_name="Petra Sommer"
        )
        session.add(manager)
        await session.commit()
        return manager.id


async def _a_candidate() -> uuid.UUID:
    async with SessionLocal() as session:
        candidate = Candidate(tenant_id=TENANT, full_name="Jana Keller")
        session.add(candidate)
        await session.commit()
        return candidate.id


# --- the vocabulary itself ----------------------------------------------


def test_the_two_lists_are_the_ones_the_ticket_names() -> None:
    """ELI-9 names five manager kinds and three candidate kinds. `note` is
    the one addition, and it is here because the rows and the composer that
    writes them already shipped."""
    assert [k.value for k in MANAGER_INTERACTION_KINDS] == [
        "meeting", "client_call", "business_call", "message", "na", "note",
    ]
    assert [k.value for k in CANDIDATE_INTERACTION_KINDS] == [
        "candidate_call", "message", "na", "note",
    ]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("N/A", "na"),
        ("n/a", "na"),
        ("NA", "na"),
        ("BD Call", "business_call"),
        ("Meeting Notes", "meeting"),
        ("E-Mail", "message"),
        ("email", "message"),
        ("note", "note"),
        ("client_call", "client_call"),
    ],
)
def test_every_spelling_in_the_record_resolves(stored, expected) -> None:
    """Read off the 366 live rows, not from the importer's documentation."""
    assert normalise_interaction_type(stored) == expected


@pytest.mark.parametrize(
    "stored", ["Job Spec", "Client Canvas", "Candidate Qualification"]
)
def test_a_kind_nobody_mapped_keeps_its_own_name(stored) -> None:
    """45 real notes are in these three, and they are on neither list.

    Absorbing them into `note` would be a silent decision about somebody
    else's data. They pass through, visibly unmapped, until a human says
    what they are.
    """
    assert normalise_interaction_type(stored) == stored


def test_being_unreachable_is_not_contact() -> None:
    """The single commonest kind in the record — 170 of 366.

    Counting a call nobody answered as contact would mark 170 managers as
    freshly touched by nobody, and clear exactly the overdue flag that is
    supposed to show it.
    """
    assert InteractionType.NOT_REACHED.value not in CONTACT_INTERACTION_KINDS
    assert InteractionType.NOTE.value not in CONTACT_INTERACTION_KINDS
    for reached in ("meeting", "client_call", "business_call", "candidate_call", "message"):
        assert reached in CONTACT_INTERACTION_KINDS


def test_the_retired_kinds_are_still_readable() -> None:
    """`call` and `email` are off the menu but still on rows written before
    ELI-9. An enum that cannot name its own history makes those unreadable."""
    assert InteractionType("call") is InteractionType.CALL
    assert InteractionType.CALL not in MANAGER_INTERACTION_KINDS
    assert InteractionType.CALL not in CANDIDATE_INTERACTION_KINDS


# --- through the API -----------------------------------------------------


async def test_an_imported_spelling_reads_back_canonical() -> None:
    """The cockpit must never have to know that "BD Call" and
    `business_call` are the same thing."""
    await create_all()
    manager_id = await _a_manager()
    async with SessionLocal() as session:
        session.add(
            ManagerInteraction(
                tenant_id=TENANT,
                manager_id=manager_id,
                interaction_type="BD Call",  # exactly as aiFind wrote it
                occurred_at=dt.datetime(2026, 3, 1, 12, tzinfo=dt.UTC),
                summary="Erstkontakt",
            )
        )
        await session.commit()

    async with _api() as client:
        resp = await client.get(f"{settings.api_v1_prefix}/managers/{manager_id}/interactions")

    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["interaction_type"] == "business_call"


async def test_an_unreached_call_does_not_move_the_contact_date() -> None:
    await create_all()
    manager_id = await _a_manager()

    async with _api() as client:
        logged = await client.post(
            f"{settings.api_v1_prefix}/managers/{manager_id}/interactions",
            json={
                "interaction_type": "na",
                "summary": "dreimal versucht",
                "occurred_at": "2026-10-01T12:00:00Z",
            },
        )
        assert logged.status_code == 201, logged.text
        profile = await client.get(f"{settings.api_v1_prefix}/managers/{manager_id}")

    assert profile.json()["last_contact_at"] is None


async def test_a_business_call_does_move_it() -> None:
    """The other half — otherwise the test above passes with contact dates
    that never move at all."""
    await create_all()
    manager_id = await _a_manager()

    async with _api() as client:
        await client.post(
            f"{settings.api_v1_prefix}/managers/{manager_id}/interactions",
            json={
                "interaction_type": "business_call",
                "summary": "erreicht",
                "occurred_at": "2026-10-01T12:00:00Z",
            },
        )
        profile = await client.get(f"{settings.api_v1_prefix}/managers/{manager_id}")

    assert (profile.json()["last_contact_at"] or "").startswith("2026-10-01")


# --- the candidate side, which did not exist -----------------------------


async def test_a_note_can_finally_be_filed_against_a_candidate() -> None:
    """`candidate_id` has been on the table since it was created and not one
    of the 366 imported rows ever filled it."""
    await create_all()
    candidate_id = await _a_candidate()

    async with _api() as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/interactions",
            json={
                "interaction_type": "candidate_call",
                "summary": "Erstgespräch, sucht ab Q1",
                "occurred_at": "2026-10-02T12:00:00Z",
            },
        )
        listed = await client.get(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/interactions"
        )

    assert created.status_code == 201, created.text
    assert created.json()["candidate_id"] == str(candidate_id)
    assert created.json()["manager_id"] is None
    assert [row["interaction_type"] for row in listed.json()] == ["candidate_call"]


async def test_a_candidate_note_does_not_appear_on_a_manager() -> None:
    """One table, two timelines. They must not bleed."""
    await create_all()
    candidate_id = await _a_candidate()
    manager_id = await _a_manager()

    async with _api() as client:
        await client.post(
            f"{settings.api_v1_prefix}/candidates/{candidate_id}/interactions",
            json={"interaction_type": "candidate_call", "summary": "nur Kandidat"},
        )
        manager_rows = await client.get(
            f"{settings.api_v1_prefix}/managers/{manager_id}/interactions"
        )

    assert manager_rows.json() == []


async def test_a_note_against_another_workspaces_candidate_is_a_404() -> None:
    await create_all()
    async with _api() as client:
        resp = await client.post(
            f"{settings.api_v1_prefix}/candidates/{uuid.uuid4()}/interactions",
            json={"interaction_type": "candidate_call", "summary": "x"},
        )
    assert resp.status_code == 404
