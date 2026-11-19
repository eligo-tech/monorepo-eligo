"""ELI-27: deleting data is an admin's job — and the SERVER says so.

"Generell Daten löschen darf nur ein Admin." A hidden button is a courtesy;
the 403 is the control. So this test does not list the delete endpoints it
knows about — it walks the route table, takes EVERY `DELETE` route plus the
erasure POSTs, and attacks each one as a recruiter. A delete route added
tomorrow is covered without anyone remembering this file, and the only way
around it is a line in `EXEMPT` with a reason a reviewer can disagree with.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.core.auth import RECRUITER, Actor, get_current_actor
from app.core.config import settings

#: DELETE routes a recruiter may still call, and why. Each one removes
#: nothing: it reverses a mark the same recruiter may set again.
EXEMPT: dict[tuple[str, str], str] = {
    # The watch star in Markt. PUT sets it, DELETE clears it; letting a
    # recruiter star but never unstar would be a bug, not a control.
    ("DELETE", "/hub/companies/{hub_company_id}/track"): "toggle of the watch mark",
    # ELI-33 "Verknüpfung aufheben": the link rows stay, marked IGNORED, with
    # a receipt — an undo of a wrong match, not a deletion.
    ("DELETE", "/companies/{company_id}/market-links"): "undo of a wrong link, receipted",
    # ELI-32: "Wieder kontaktierbar" clears a mark the same recruiter set
    # from a note; it removes no data, and leaves a receipt.
    ("DELETE", "/{kind}/{person_id}/do-not-contact"): "undo of the do-not-contact mark, receipted",
}

#: Deletions that are not spelled DELETE. Art. 17 erasure is a POST because
#: it carries a body (the confirmed name, the reason).
DELETING_POSTS: set[tuple[str, str]] = {
    ("POST", "/erasure/candidates/{candidate_id}"),
    ("POST", "/erasure/managers/{manager_id}"),
}

_ADMIN_GUARDS = {"require_admin", "require_admin_to_delete"}


def _routes(router):
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            yield route
        elif getattr(route, "original_router", None) is not None:
            yield from _routes(route.original_router)


def _names(dependant) -> set[str]:
    out: set[str] = set()
    for dep in dependant.dependencies:
        call = getattr(dep, "call", None)
        if call is not None:
            out.add(getattr(call, "__name__", type(call).__name__))
        out |= _names(dep)
    return out


def _deleting_routes() -> list[tuple[str, str]]:
    from app.main import app

    found: set[tuple[str, str]] = set()
    for route in _routes(app):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            key = (method, route.path)
            if (method == "DELETE" and key not in EXEMPT) or key in DELETING_POSTS:
                found.add(key)
    return sorted(found)


def test_the_route_table_has_deletes_to_guard() -> None:
    """Guard against the walk finding nothing and the test passing vacuously."""
    routes = _deleting_routes()
    assert len(routes) >= 6, routes
    # Every declared exemption and POST still exists — a stale entry hides a gap.
    from app.main import app

    present = {
        (m, r.path) for r in _routes(app) for m in r.methods - {"HEAD", "OPTIONS"}
    }
    assert set(EXEMPT) <= present
    assert DELETING_POSTS <= present


@pytest.mark.parametrize("method,path", _deleting_routes())
def test_every_delete_route_carries_an_admin_guard(method: str, path: str) -> None:
    from app.main import app

    route = next(
        r for r in _routes(app) if r.path == path and method in r.methods
    )
    assert _names(route.dependant) & _ADMIN_GUARDS, (
        f"{method} {path} deletes data but has no admin guard (ELI-27)"
    )


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


@pytest.mark.parametrize("method,path", _deleting_routes())
async def test_a_recruiter_gets_403_on_every_delete(method: str, path: str) -> None:
    from app.main import app

    app.dependency_overrides[get_current_actor] = lambda: Actor(
        tenant_id=settings.default_tenant_id,
        user_id="u_rec",
        name="R. Ecruiter",
        role=RECRUITER,
        role_known=True,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            url = f"{settings.api_v1_prefix}{_concrete(path)}"
            if method == "POST":
                resp = await client.post(url, json={"confirm_name": "x", "reason": "x"})
            else:
                resp = await client.request(method, url)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403, (method, path, resp.status_code, resp.text)
    assert "Administrator" in resp.text


async def test_an_admin_still_reaches_the_delete() -> None:
    """The guard must not lock everybody out: the demo actor (admin) deletes
    a saved search it just made."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        created = await client.post(
            f"{settings.api_v1_prefix}/searches", json={"label": "Admin darf", "query": "x"}
        )
        assert created.status_code in (200, 201), created.text
        gone = await client.delete(f"{settings.api_v1_prefix}/searches/{created.json()['id']}")
    assert gone.status_code in (200, 204), gone.text
