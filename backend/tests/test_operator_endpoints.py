"""Operator endpoints must be machine-only. Enforced by behaviour, not by grep.

F1 shipped past a review whose checklist claimed to cover it, because the check
was a grep over the FRONTEND for `/hub/ingest`. The frontend was clean; the
backend dependency quietly fell back to the human path. A rule that is only
checked where it happens to be easy to check is not enforced.

So this file does two things a grep cannot:

  * derives the machine-only route set from the app itself, by introspecting
    which routes depend on `get_ingest_tenant`, and requires it to match an
    explicit declaration — so adding an operator endpoint without declaring it
    fails, and declaring one that was never wired up fails too;
  * asserts the BEHAVIOUR with the strongest user credential that exists — a
    valid session for a real organisation — rather than trusting the wiring.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.core.config import settings

# Every endpoint that only a scheduled job may call. Keep in step with the
# routers; the first test fails loudly if they drift apart.
DECLARED_OPERATOR_ROUTES: set[tuple[str, str]] = {
    ("POST", "/hub/ingest"),
    ("POST", "/hub/descriptions/fetch"),
    ("POST", "/hub/maintenance/expire-stale"),
    ("GET", "/hub/crawl-profiles"),
    ("POST", "/hub/crawl-profiles/mark-crawled"),
}

_TOKEN = "t" * 44


def _api_routes(router):
    """Walk nested routers — this FastAPI keeps included routers unflattened."""
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            yield route
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from _api_routes(inner)


def _dependency_names(route: APIRoute) -> set[str]:
    return {
        dep.call.__name__
        for dep in route.dependant.dependencies
        if getattr(dep, "call", None) is not None
    }


def _machine_routes(app) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in _api_routes(app):
        if "get_ingest_tenant" in _dependency_names(route):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found.add((method, route.path))
    return found


def test_the_declared_operator_set_matches_the_wiring() -> None:
    """A new machine endpoint cannot appear without being declared and tested."""
    from app.main import app

    assert _machine_routes(app) == DECLARED_OPERATOR_ROUTES


def test_no_operator_route_also_accepts_the_human_dependency() -> None:
    """`get_current_tenant` on an operator route would reopen F1 exactly."""
    from app.main import app

    for route in _api_routes(app):
        methods = route.methods - {"HEAD", "OPTIONS"}
        if any((m, route.path) in DECLARED_OPERATOR_ROUTES for m in methods):
            assert "get_current_tenant" not in _dependency_names(route), route.path


@pytest.mark.parametrize(("method", "path"), sorted(DECLARED_OPERATOR_ROUTES))
async def test_a_valid_user_session_is_refused(method, path, monkeypatch) -> None:
    """The strongest user credential that exists must still be refused."""
    from app.core import auth as auth_module
    from app.main import app

    monkeypatch.setattr(settings, "ingest_token", _TOKEN)
    monkeypatch.setattr(settings, "auth_enabled", True)
    # A real, valid session for a real organisation.
    monkeypatch.setattr(
        auth_module, "verify_token", lambda _t: {"org_id": "org_real", "sub": "user_1"}
    )

    url = f"{settings.api_v1_prefix}{path}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            method, url, json={}, headers={"Authorization": "Bearer real-user-session"}
        )
    assert resp.status_code == 401, f"{method} {path} accepted a user session"
    assert "machine credential" in resp.json()["detail"]


@pytest.mark.parametrize(("method", "path"), sorted(DECLARED_OPERATOR_ROUTES))
async def test_the_machine_credential_is_accepted(method, path, monkeypatch) -> None:
    """The other half: the guard must not lock out the scheduler itself."""
    from app.core import auth as auth_module
    from app.main import app

    monkeypatch.setattr(settings, "ingest_token", _TOKEN)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda _t: (_ for _ in ()).throw(AssertionError("must not reach Clerk")),
    )

    url = f"{settings.api_v1_prefix}{path}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            method, url, json={}, headers={"Authorization": f"Bearer {_TOKEN}"}
        )
    # Anything but an auth failure means it got past the guard: 200/201 for the
    # reads, 422 for a POST whose empty body is invalid.
    assert resp.status_code not in (401, 403), f"{method} {path} rejected the scheduler"
