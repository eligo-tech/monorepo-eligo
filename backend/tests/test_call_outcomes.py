"""Call outcomes on the contact history (ELI-22 call list).

A call is already a `manager_interactions` row (who, when, what was said).
The call list needs two more facts on it: how the call ended, and when to call
again — so "who do I call next" is a query, not a recruiter's memory.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.domain.common.enums import CallOutcome, InteractionType
from app.domain.companies.models import Company
from app.domain.managers import service
from app.domain.managers.schemas import ManagerCreate, ManagerInteractionCreate, ManagerInteractionRead

TENANT = uuid.uuid4()


@pytest.fixture
async def manager_id() -> uuid.UUID:
    async with SessionLocal() as s:
        c = Company(tenant_id=TENANT, name="Eugen Forschner GmbH")
        s.add(c)
        await s.commit()
        m = await service.create_manager(
            s, tenant_id=TENANT, payload=ManagerCreate(company_id=c.id, full_name="Leonie Denkinger")
        )
        return m.id


def test_the_outcomes_are_the_ones_the_recruiters_named() -> None:
    assert [o.value for o in CallOutcome] == [
        "not_reached", "voicemail", "call_back", "wrong_person", "not_interested", "meeting_booked", "mandate",
    ]


async def test_a_call_records_its_outcome_and_the_next_call(manager_id) -> None:
    when = dt.datetime(2026, 11, 13, 9, 0, tzinfo=dt.UTC)
    async with SessionLocal() as s:
        row = await service.log_interaction(
            s, tenant_id=TENANT, manager_id=manager_id,
            payload=ManagerInteractionCreate(
                interaction_type=InteractionType.BUSINESS_CALL, outcome="call_back",
                next_action_at=when, summary="Bitte Donnerstag nochmal, dann ist die PDL da.",
            ),
        )
    read = ManagerInteractionRead.model_validate(row)
    assert read.outcome == "call_back"
    assert read.next_action_at is not None and read.next_action_at.replace(tzinfo=dt.UTC) == when


def test_an_unknown_outcome_is_refused() -> None:
    with pytest.raises(ValidationError):
        ManagerInteractionCreate(interaction_type=InteractionType.BUSINESS_CALL, outcome="maybe")


def test_call_back_needs_a_date() -> None:
    """A call-back without a date is a promise nobody can keep: it never
    surfaces as due."""
    with pytest.raises(ValidationError):
        ManagerInteractionCreate(interaction_type=InteractionType.BUSINESS_CALL, outcome="call_back")


async def test_an_interaction_without_an_outcome_is_still_fine(manager_id) -> None:
    """Notes, meetings, mails: most interactions are not calls with an outcome."""
    async with SessionLocal() as s:
        row = await service.log_interaction(
            s, tenant_id=TENANT, manager_id=manager_id,
            payload=ManagerInteractionCreate(interaction_type=InteractionType.MEETING, summary="Vor Ort"),
        )
    read = ManagerInteractionRead.model_validate(row)
    assert (read.outcome, read.next_action_at) == (None, None)
