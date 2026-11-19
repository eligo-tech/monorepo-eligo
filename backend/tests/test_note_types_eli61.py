"""ELI-61: two more kinds of note on a manager — „Gesprächsnotiz“ (the
manager was reached; the note says what was discussed) and „Anonyme Profile
gesendet“ (profiles went out; the cockpit files a Wiedervorlage for the
feedback).

Both are members of the one vocabulary (`InteractionType`), so the composer,
the normaliser, "letzter Kontakt" and the KPI all learn them from one place.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import SessionLocal, create_all
from app.domain.activity.kpis import manager_call_spellings
from app.domain.common.enums import (
    CANDIDATE_INTERACTION_KINDS,
    CONTACT_INTERACTION_KINDS,
    MANAGER_INTERACTION_KINDS,
    InteractionType,
    normalise_interaction_type,
)
from app.domain.companies.models import Company
from app.domain.managers.models import Manager

TENANT = settings.default_tenant_id


def _api() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_manager() -> uuid.UUID:
    async with SessionLocal() as session:
        company = Company(tenant_id=TENANT, name="Profil GmbH")
        session.add(company)
        await session.flush()
        manager = Manager(tenant_id=TENANT, company_id=company.id, full_name="Lena Vogt")
        session.add(manager)
        await session.commit()
        return manager.id


def test_both_are_offered_on_a_manager_only() -> None:
    assert InteractionType.CONVERSATION in MANAGER_INTERACTION_KINDS
    assert InteractionType.PROFILES_SENT in MANAGER_INTERACTION_KINDS
    # Profiles go to a client, and a Gesprächsnotiz is "Manager erreicht".
    assert InteractionType.CONVERSATION not in CANDIDATE_INTERACTION_KINDS
    assert InteractionType.PROFILES_SENT not in CANDIDATE_INTERACTION_KINDS


def test_a_gespraechsnotiz_is_contact_and_a_manager_call() -> None:
    """„heißt Manager erreicht“ — it must move "letzter Kontakt" and count
    as a call with a manager, like a business call does."""
    assert "conversation" in CONTACT_INTERACTION_KINDS
    assert "conversation" in manager_call_spellings()


def test_sending_profiles_is_contact_but_not_a_call() -> None:
    """Sent to the manager, like a message — contact, not a conversation."""
    assert "profiles_sent" in CONTACT_INTERACTION_KINDS
    assert "profiles_sent" not in manager_call_spellings()


def test_the_german_names_resolve_too() -> None:
    """An import that writes the label rather than the value lands on the
    same kind — never a second spelling of it."""
    assert normalise_interaction_type("Gesprächsnotiz") == "conversation"
    assert normalise_interaction_type("Anonyme Profile gesendet") == "profiles_sent"
    assert normalise_interaction_type("conversation") == "conversation"
    assert normalise_interaction_type("profiles_sent") == "profiles_sent"
    # The label spelling reaches the SQL filter of the call KPI as well.
    assert "gesprächsnotiz" in manager_call_spellings()


async def test_a_gespraechsnotiz_moves_the_contact_date() -> None:
    await create_all()
    manager_id = await _a_manager()
    async with _api() as client:
        logged = await client.post(
            f"{settings.api_v1_prefix}/managers/{manager_id}/interactions",
            json={
                "interaction_type": "conversation",
                "summary": "Bedarf 2027 besprochen",
                "occurred_at": "2026-10-02T12:00:00Z",
            },
        )
        assert logged.status_code == 201, logged.text
        assert logged.json()["interaction_type"] == "conversation"
        profile = await client.get(f"{settings.api_v1_prefix}/managers/{manager_id}")
    assert (profile.json()["last_contact_at"] or "").startswith("2026-10-02")


async def test_profiles_sent_is_saved_under_its_own_kind() -> None:
    await create_all()
    manager_id = await _a_manager()
    async with _api() as client:
        logged = await client.post(
            f"{settings.api_v1_prefix}/managers/{manager_id}/interactions",
            json={
                "interaction_type": "profiles_sent",
                "summary": "3 Profile, Java",
                "occurred_at": "2026-10-03T12:00:00Z",
            },
        )
    assert logged.status_code == 201, logged.text
    assert logged.json()["interaction_type"] == "profiles_sent"
