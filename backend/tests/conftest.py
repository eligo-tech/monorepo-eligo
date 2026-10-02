"""Test environment defaults.

Force a hermetic, auth-free SQLite setup *before* the app imports its settings,
so `pytest` works out of the box regardless of a local `.env` (which may enable
Clerk auth or point at Postgres). `setdefault` means an explicit inline env var
still wins, and CI — which has no `.env` — is unaffected.
"""

from __future__ import annotations

import os

os.environ.setdefault("ELIGO_AUTH_ENABLED", "false")  # noqa: E402 — must precede app import
os.environ.setdefault("ELIGO_DATABASE_URL", "sqlite+aiosqlite:///./ci_test.db")
# Pin the ADMIN url too (create_all/DDL runs on it). Otherwise it is read from a
# local `.env` and DDL lands on the real Postgres while the runtime engine is
# this hermetic SQLite — so DB-backed tests would see "no such table".
os.environ.setdefault("ELIGO_ADMIN_DATABASE_URL", os.environ["ELIGO_DATABASE_URL"])
os.environ.setdefault("ELIGO_LLM_PROVIDER", "heuristic")
os.environ.setdefault("ELIGO_DB_SSL", "false")

import pytest  # noqa: E402 — after the env is pinned, before fixtures use the app


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Give every test an empty schema.

    With auth disabled every request resolves to the single default tenant, so
    rows created by one test are visible to the next; the SQLite file also
    persists across the session. Drop + recreate before each test so counts
    (e.g. "matching returns exactly one candidate") are deterministic.
    """
    from app.core.database import Base, admin_engine
    from app.domain import registry  # noqa: F401 — registers every table on Base

    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """No test may touch the internet.

    `POST /hub/ingest` with an empty body is a valid request, so an operator
    test that only meant to check authorization ran a real crawl against the
    Bundesagentur API from CI — minutes when it worked, a read timeout when it
    did not (run 36868354414). A suite whose colour depends on a third party's
    uptime teaches people to re-run red builds, which is how a real failure
    gets waved through.

    Loopback stays open: ASGI transports do not use sockets, but a local
    database or a debugger might.
    """
    import socket

    real_connect = socket.socket.connect

    def guard(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(
                f"a test tried to reach {host} — stub the adapter instead "
                "(see _StubAdapter in test_operator_endpoints.py)"
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard)
