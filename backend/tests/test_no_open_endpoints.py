"""Every route is authenticated unless it is declared public, here.

This exists because three endpoints shipped open without anyone deciding
they should be: `/imports/entities`, `/tenant-sources/capabilities` and
`/hub/sources`. None leaked tenant data — they return build and product
metadata — but none of them was a decision either, and "harmless to leak" is
a judgement that ages badly: the next field added to a public endpoint is
the one that is not harmless.

It also exists because the first attempt to find them by hand missed four of
the five, by walking `app.routes` naively. This FastAPI keeps included
routers unflattened, so a hand-rolled check quietly inspects almost nothing
and reports success — the same trap `test_operator_endpoints.py` documents.

Adding a public endpoint is allowed. Adding one silently is not.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

#: Routes that answer without a session, on purpose.
#:
#: `/health` is read by the platform's health check before any user exists;
#: `/` is the API's own root banner. Both are static and say nothing about
#: any workspace.
DECLARED_PUBLIC_ROUTES: set[tuple[str, str]] = {
    ("GET", "/health"),
    ("GET", "/"),
}

#: Dependencies that authenticate a request. `get_current_tenant` resolves
#: the workspace, `get_current_actor` the person as well, `require_admin` the
#: person plus a role check, and `get_ingest_tenant` a machine credential.
_AUTH_DEPENDENCIES = {
    "get_current_tenant",
    "get_current_actor",
    "require_admin",
    "get_ingest_tenant",
}


def _api_routes(router):
    """Walk nested routers — included routers are not flattened here."""
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            yield route
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from _api_routes(inner)


def _open_routes(app) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in _api_routes(app):
        names = {
            dep.call.__name__
            for dep in route.dependant.dependencies
            if getattr(dep, "call", None) is not None
        }
        if names & _AUTH_DEPENDENCIES:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found.add((method, route.path))
    return found


def test_the_walker_actually_sees_the_api() -> None:
    """Guard the guard: a walker that finds nothing passes every other test
    in this file. The API has dozens of routes; assert we can see them."""
    from app.main import app

    routes = list(_api_routes(app))
    assert len(routes) > 30, f"only {len(routes)} routes visible — the walk is broken"
    paths = {r.path for r in routes}
    assert "/candidates" in paths and "/hub/ingest" in paths


def test_no_endpoint_is_public_without_being_declared() -> None:
    from app.main import app

    assert _open_routes(app) == DECLARED_PUBLIC_ROUTES


def test_every_declared_public_route_exists() -> None:
    """A stale entry here would hide a real one added later."""
    from app.main import app

    live = {
        (method, route.path)
        for route in _api_routes(app)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert DECLARED_PUBLIC_ROUTES <= live
