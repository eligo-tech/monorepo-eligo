"""Who is acting, what they may do, and what the ledger remembers.

Three things these pin:

1. The role comes from the TOKEN. Clerk writes it two ways across token
   versions, an unrecognised role must not grant anything, and a missing one
   must not either.
2. Admin-only means the SERVER refuses, not that the button is hidden.
3. A change names the person who made it, and that history is readable —
   attribution nobody can see is not attribution.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import auth
from app.core.database import SessionLocal
from app.domain.candidates.models import Candidate
from app.domain.candidates.schemas import CandidateUpdate
from app.domain.candidates import service as candidates_service
from app.domain.verification import service as verification

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Reading the role out of a Clerk token
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims,expected,known",
    [
        # v2 session token: the org claim carries a bare role.
        ({"o": {"id": "org_1", "rol": "admin"}}, auth.ADMIN, True),
        ({"o": {"id": "org_1", "rol": "member"}}, auth.RECRUITER, True),
        # v1: prefixed.
        ({"org_role": "org:admin"}, auth.ADMIN, True),
        ({"org_role": "org:member"}, auth.RECRUITER, True),
        # Clerk's owner role, and a custom one nobody taught us.
        ({"org_role": "org:owner"}, auth.ADMIN, True),
        ({"org_role": "org:billing_manager"}, auth.RECRUITER, True),
        # No role claim at all: least privilege, and we know we are guessing.
        ({}, auth.RECRUITER, False),
        ({"o": {"id": "org_1"}}, auth.RECRUITER, False),
    ],
)
def test_the_role_comes_from_the_token(claims, expected, known) -> None:
    assert auth._role(claims) == (expected, known)


def test_an_unknown_custom_role_never_grants_admin() -> None:
    """A workspace that invents a Clerk role must not accidentally get the
    keys — the mapping is an allow-list, not a guess."""
    role, known = auth._role({"org_role": "org:super_recruiter"})
    assert role == auth.RECRUITER and known is True


@pytest.mark.parametrize(
    "claims,expected",
    [
        ({"name": "T. Bauer", "sub": "user_1"}, "T. Bauer"),
        ({"given_name": "Tim", "family_name": "Bauer"}, "Tim Bauer"),
        ({"email": "tim@example.de", "sub": "user_1"}, "tim@example.de"),
        # A default Clerk token carries only `sub`. Still attributable.
        ({"sub": "user_3Gj"}, "user_3Gj"),
    ],
)
def test_the_receipt_gets_the_most_human_name_available(claims, expected) -> None:
    assert auth._actor_name(claims) == expected


# ---------------------------------------------------------------------------
# What a role may do
# ---------------------------------------------------------------------------


def _actor(role: str) -> auth.Actor:
    return auth.Actor(
        tenant_id=TENANT, user_id="user_1", name="T. Bauer", role=role, role_known=True
    )


async def test_require_admin_refuses_a_recruiter() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await auth.require_admin(_actor(auth.RECRUITER))
    assert raised.value.status_code == 403
    # The message has to say what to do about it.
    assert "Administratoren" in raised.value.detail


async def test_require_admin_says_when_the_token_carried_no_role() -> None:
    """Otherwise a locked-out admin has no way to tell a permission problem
    from a Clerk configuration problem."""
    from fastapi import HTTPException

    nameless = auth.Actor(
        tenant_id=TENANT, user_id="u", name="u", role=auth.RECRUITER, role_known=False
    )
    with pytest.raises(HTTPException) as raised:
        await auth.require_admin(nameless)
    assert "keine Rolle" in raised.value.detail


async def test_an_admin_passes_through() -> None:
    assert (await auth.require_admin(_actor(auth.ADMIN))).is_admin


def test_the_admin_only_routes_are_the_ones_we_meant() -> None:
    """A new endpoint that writes over the workspace's record should be a
    deliberate decision, so the set is asserted rather than described."""
    from fastapi.routing import APIRoute

    from app.main import app

    def walk(router):
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                yield route
            elif getattr(route, "original_router", None) is not None:
                yield from walk(route.original_router)

    admin_only = {
        (method, route.path)
        for route in walk(app)
        for method in route.methods - {"HEAD", "OPTIONS"}
        if "require_admin"
        in {d.call.__name__ for d in route.dependant.dependencies if d.call}
    }
    assert admin_only == {
        ("PUT", "/tenant-sources/{kind}"),
        ("DELETE", "/tenant-sources/{kind}"),
        ("POST", "/tenant-sources/{kind}/import"),
        ("POST", "/imports/commit"),
    }


# ---------------------------------------------------------------------------
# The ledger, read back
# ---------------------------------------------------------------------------


async def test_a_change_names_the_person_and_shows_up_in_the_history() -> None:
    async with SessionLocal() as s:
        candidate = Candidate(tenant_id=TENANT, full_name="Anna Schmidt")
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id

        await candidates_service.update_candidate(
            s,
            tenant_id=TENANT,
            candidate_id=candidate_id,
            patch=CandidateUpdate(current_title="Lead Engineer"),
            editor="T. Bauer",
        )
        history = await verification.history_for(
            s, tenant_id=TENANT, entity_type="candidate", entity_id=candidate_id
        )

    assert history, "a verified change left no history"
    entry = history[0]
    assert entry["actor"] == "T. Bauer"
    assert entry["field"] == "current_title"
    assert "Lead Engineer" in entry["summary"]
    assert entry["source"] == "human_verified"


async def test_the_history_is_newest_first_and_stays_in_its_tenant() -> None:
    async with SessionLocal() as s:
        candidate = Candidate(tenant_id=TENANT, full_name="Vielfach Geändert")
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id
        for title in ("Erst", "Dann", "Zuletzt"):
            await candidates_service.update_candidate(
                s,
                tenant_id=TENANT,
                candidate_id=candidate_id,
                patch=CandidateUpdate(current_title=title),
                editor="T. Bauer",
            )
        mine = await verification.history_for(
            s, tenant_id=TENANT, entity_type="candidate", entity_id=candidate_id
        )
        theirs = await verification.history_for(
            s, tenant_id=uuid.uuid4(), entity_type="candidate", entity_id=candidate_id
        )

    assert "Zuletzt" in mine[0]["summary"]
    assert len(mine) == 3
    assert theirs == []


async def test_routes() -> None:
    from app.main import app as fastapi_app

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://t"
    ) as client:
        # Auth is disabled in tests: the demo actor is an admin so the local
        # stack is not locked out of its own settings.
        me = (await client.get("/api/v1/me")).json()
        assert me["role"] == auth.ADMIN and me["role_known"] is False

        created = (
            await client.post(
                "/api/v1/candidates", json={"full_name": "Verlauf Test"}
            )
        ).json()
        await client.patch(
            f"/api/v1/candidates/{created['id']}", json={"phone": "+49 89 1"}
        )
        history = (
            await client.get(f"/api/v1/verification/history/candidate/{created['id']}")
        ).json()

    assert history[0]["field"] == "phone"
    assert history[0]["actor"] == "Demo"
